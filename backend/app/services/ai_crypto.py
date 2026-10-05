"""1A AI secret crypto: AES-256-GCM with lazy master-key material loading.

Per checklist §5.1–5.3:

* Storage: standard Base64(nonce || AESGCM ciphertext-with-tag); nonce is a
  fresh random 12 bytes per encryption; AAD is UTF-8 ``account_id + ":" +
  config_version``.
* Key material is loaded lazily on every encrypt/decrypt call (no global
  cache); import and process start never validate non-default formats.
* Missing or malformed key material disables AI capabilities (typed errors)
  but never blocks startup or the manual paths; ``ai_crypto`` has an empty
  import surface for the manual plan/export services.
* ``key_id`` must match the target row exactly before decryption.
"""

from __future__ import annotations

import base64
import binascii
import os
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_BYTES = 12
KEY_BYTES = 32

_KEY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class KeyMaterialMissing(Exception):
    """No master key configured (degraded state; AI paused)."""


class KeyMaterialInvalid(Exception):
    """Configured key material has a wrong format (AI paused)."""


class DecryptUnavailable(Exception):
    """Decryption failed: missing/invalid material, tampered ciphertext or
    account/version AAD mismatch, or key_id mismatch."""


def load_material() -> tuple[bytes, str]:
    """Lazily read and strictly validate the configured master key material.

    Returns ``(key_bytes, key_id)``. Raises :class:`KeyMaterialMissing` when
    no key is configured and :class:`KeyMaterialInvalid` when configured
    material is malformed. Import-time / process-start safe (lazy).
    """
    from app.config import settings

    encoded = settings.ai_master_key.get_secret_value()
    if not encoded:
        raise KeyMaterialMissing()
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise KeyMaterialInvalid("主密钥必须是标准 Base64 编码") from exc
    if len(raw) != KEY_BYTES:
        raise KeyMaterialInvalid(
            f"主密钥解码后必须恰为 {KEY_BYTES} 字节（AES-256）"
        )
    key_id = settings.ai_master_key_id.get_secret_value()
    if not key_id or not _KEY_ID_RE.match(key_id):
        raise KeyMaterialInvalid(
            "ai_master_key_id 必须匹配 [A-Za-z0-9._-]{1,64}"
        )
    return raw, key_id


def _aad(account_id: str, config_version: int) -> bytes:
    return f"{account_id}:{config_version}".encode("utf-8")


def encrypt_secret(
    plaintext: str, account_id: str, config_version: int, *, material=None
) -> tuple[str, str]:
    """Encrypt for a specific (account_id, config_version) binding.

    Returns ``(storage_b64, key_id)``; the caller stores both, with the
    ``key_id`` REQUIRED by ck_ai_config_versions_secret_key for every
    non-null ciphertext row.
    """
    key, key_id = material if material is not None else load_material()
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(
        nonce, plaintext.encode("utf-8"), _aad(account_id, config_version)
    )
    return (
        base64.b64encode(nonce + ciphertext).decode("ascii"),
        key_id,
    )


def _decode_storage(storage_b64: str) -> tuple[bytes, bytes]:
    try:
        blob = base64.b64decode(storage_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DecryptUnavailable("密文不是合法的 Base64 存储") from exc
    if len(blob) < NONCE_BYTES + 16:  # nonce + GCM tag minimum
        raise DecryptUnavailable("密文长度不足")
    return blob[:NONCE_BYTES], blob[NONCE_BYTES:]


def decrypt_secret(
    storage_b64: str,
    *,
    key_id: str,
    account_id: str,
    config_version: int,
    material=None,
) -> str:
    """Decrypt a stored secret bound to that row's own account/version AAD.

    Raises :class:`DecryptUnavailable` on any mismatch (missing/invalid
    material, tampered ciphertext, wrong key_id, wrong account or version),
    never leaking material or plaintext into the error text.
    """
    try:
        key, configured_key_id = (
            material if material is not None else load_material()
        )
    except KeyMaterialMissing:
        raise DecryptUnavailable("加密材料不可用，无法解密") from None
    except KeyMaterialInvalid:
        raise DecryptUnavailable("加密材料无效，无法解密") from None
    if key_id != configured_key_id:
        raise DecryptUnavailable("key_id 不匹配，拒绝解密")
    nonce, ciphertext = _decode_storage(storage_b64)
    try:
        plaintext = AESGCM(key).decrypt(
            nonce, ciphertext, _aad(account_id, config_version)
        )
    except Exception as exc:  # InvalidTag / ValueError: tamper or wrong AAD
        raise DecryptUnavailable("密文校验失败") from exc
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DecryptUnavailable("密文解出的字节不是合法 UTF-8") from exc


def make_material(key_bytes: bytes, key_id: str) -> tuple[bytes, str]:
    """Test helper: build an equivalent (key, key_id) material tuple."""
    if len(key_bytes) != KEY_BYTES:
        raise ValueError("test key must be 32 bytes")
    return key_bytes, key_id
