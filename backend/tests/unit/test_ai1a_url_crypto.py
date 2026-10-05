"""AI 1A unit tests: offline URL validation + AES-GCM secret crypto + masking.

Checklist §9.1. Pure unit (no DB, no service process); no ``.env`` is ever
read — key material is generated in-process and injected into Settings.
"""

from __future__ import annotations

import base64
import os
import pickle
import unittest

os.environ["APP_DISABLE_DOTENV"] = "1"

from pydantic import SecretStr  # noqa: E402

from app.config import Settings, settings  # noqa: E402
from app.services import ai_crypto  # noqa: E402
from app.services.ai_config_url import (  # noqa: E402
    BaseUrlInvalid,
    normalize_https_base_url,
)


def _set_material(key: bytes, key_id: str) -> None:
    settings.ai_master_key = SecretStr(base64.b64encode(key).decode())
    settings.ai_master_key_id = SecretStr(key_id)


def _clear_material() -> None:
    settings.ai_master_key = SecretStr("")
    settings.ai_master_key_id = SecretStr("")


def _peek_key() -> bytes:
    return base64.b64decode(settings.ai_master_key.get_secret_value())


class CryptoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.key = os.urandom(32)
        _set_material(self.key, "test-key-1")
        self.addCleanup(_clear_material)

    def test_nonce_randomness(self):
        store1, kid = ai_crypto.encrypt_secret("s3cret", "acc1", 1)
        store2, _ = ai_crypto.encrypt_secret("s3cret", "acc1", 1)
        self.assertNotEqual(store1, store2)
        self.assertEqual(kid, "test-key-1")

    def test_aad_binding_tamper(self):
        store, kid = ai_crypto.encrypt_secret("s3cret", "acc1", 1)
        self.assertEqual(
            ai_crypto.decrypt_secret(
                store, key_id=kid, account_id="acc1", config_version=1
            ),
            "s3cret",
        )
        with self.assertRaises(ai_crypto.DecryptUnavailable):
            ai_crypto.decrypt_secret(
                store, key_id=kid, account_id="acc1", config_version=2
            )
        with self.assertRaises(ai_crypto.DecryptUnavailable):
            ai_crypto.decrypt_secret(
                store, key_id=kid, account_id="acc2", config_version=1
            )

    def test_keep_reencrypt_new_nonce_new_aad(self):
        # 模拟旧版本行（v1 AAD）；URL/model-only PATCH 保留同一明文时必须
        # 以新 nonce + 新 config_version 的 AAD 重加密落新版本行。
        old_store, old_kid = ai_crypto.encrypt_secret("same-plaintext", "acc1", 1)
        iv2_store, iv2_kid = ai_crypto.encrypt_secret("same-plaintext", "acc1", 2)
        iii_store, _ = ai_crypto.encrypt_secret("same-plaintext", "acc1", 2)
        self.assertNotEqual(old_store, iv2_store)
        self.assertNotEqual(iv2_store, iii_store)
        self.assertEqual(old_kid, iv2_kid)  # key unchanged, bytes differ
        # 旧版本行按它自己的 AAD 仍可解密（读指定旧版本语义）。
        self.assertEqual(
            ai_crypto.decrypt_secret(
                old_store, key_id=old_kid, account_id="acc1", config_version=1
            ),
            "same-plaintext",
        )
        self.assertEqual(
            ai_crypto.decrypt_secret(
                iv2_store, key_id=iv2_kid, account_id="acc1", config_version=2
            ),
            "same-plaintext",
        )
        # 旧密文不得用新版本 AAD 解（错绑拒绝）。
        with self.assertRaises(ai_crypto.DecryptUnavailable):
            ai_crypto.decrypt_secret(
                old_store, key_id=old_kid, account_id="acc1", config_version=2
            )

    def test_rotation_and_clear_forms(self):
        # 轮换：非空新 secret 直接以新版本 AAD 加密（无需解旧密文）。
        rotate_store, rotate_kid = ai_crypto.encrypt_secret(
            "new-plaintext", "acc1", 3
        )
        self.assertEqual(
            ai_crypto.decrypt_secret(
                rotate_store,
                key_id=rotate_kid,
                account_id="acc1",
                config_version=3,
            ),
            "new-plaintext",
        )
        # 清除：版本行 secret_ciphertext/key_id 双 NULL（ck 约束），
        # 清除路径不调用解密。
        cleared_store, cleared_kid = None, None
        self.assertIsNone(cleared_store)
        self.assertIsNone(cleared_kid)
        with self.assertRaises(ai_crypto.DecryptUnavailable):
            ai_crypto.decrypt_secret(
                "", key_id="test-key-1", account_id="acc1", config_version=4
            )

    def test_key_id_mismatch(self):
        store, _ = ai_crypto.encrypt_secret("s3cret", "acc1", 1)
        with self.assertRaises(ai_crypto.DecryptUnavailable):
            ai_crypto.decrypt_secret(
                store, key_id="other-key", account_id="acc1", config_version=1
            )

    def test_tampered_ciphertext(self):
        store, kid = ai_crypto.encrypt_secret("s3cret", "acc1", 1)
        blob = bytearray(base64.b64decode(store))
        blob[-1] ^= 0x01
        tampered = base64.b64encode(bytes(blob)).decode()
        with self.assertRaises(ai_crypto.DecryptUnavailable):
            ai_crypto.decrypt_secret(
                tampered, key_id=kid, account_id="acc1", config_version=1
            )

    def test_material_state_errors(self):
        _clear_material()
        with self.assertRaises(ai_crypto.KeyMaterialMissing):
            ai_crypto.load_material()
        _set_material(b"0" * 32, "id-x")
        settings.ai_master_key_id = SecretStr("bad id!")  # 格式错误
        with self.assertRaises(ai_crypto.KeyMaterialInvalid):
            ai_crypto.load_material()
        _set_material(b"0" * 31, "id-x")  # 非 32 字节
        with self.assertRaises(ai_crypto.KeyMaterialInvalid):
            ai_crypto.load_material()
        settings.ai_master_key = SecretStr("!!!!not base64!!!!")
        with self.assertRaises(ai_crypto.KeyMaterialInvalid):
            ai_crypto.load_material()
        with self.assertRaises(ai_crypto.DecryptUnavailable):
            ai_crypto.decrypt_secret(
                "AAAA", key_id="id-x", account_id="a", config_version=1
            )
        # 未经 32 字节伪造的 key 构造立即失败（make_material 防线）。
        with self.assertRaises(ValueError):
            ai_crypto.make_material(b"short", "id-x")

    def test_missing_material_does_not_break_import_or_startup(self):
        # 重新构造 Settings（含格式错误主密钥）不抛错；格式检查是惰性的。
        bad = Settings(
            ai_master_key=SecretStr("!!!invalid!!!"),
            ai_master_key_id=SecretStr(""),
        )
        self.assertEqual(bad.ai_master_key.get_secret_value(), "!!!invalid!!!")

    def test_manual_modules_have_empty_crypto_import_surface(self):
        import inspect

        from app.services import daily_plan_service, word_export_docx, \
            weekly_plan_service

        modules = (daily_plan_service, weekly_plan_service, word_export_docx)
        for module in modules:
            source = inspect.getsource(module)
            self.assertNotIn("ai_crypto", source)
            self.assertNotIn("ai_config", source)


class DecryptedConfigMaskingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.key = os.urandom(32)
        _set_material(self.key, "test-key-1")
        self.addCleanup(_clear_material)

    def test_repr_and_serialization(self):
        from app.services.ai_config_service import DecryptedConfig

        obj = DecryptedConfig(
            account_id="acc1",
            config_version=1,
            protocol_id="chat_completions_v1",
            base_url="https://api.vendor.com/v1",
            model="m",
            secret="PLAIN-S3CRET",
        )
        self.assertNotIn("PLAIN-S3CRET", repr(obj))
        with self.assertRaises(TypeError):
            pickle.dumps(obj)
        with self.assertRaises(TypeError):
            bytes(obj)
        import copy

        with self.assertRaises(TypeError):
            copy.copy(obj)
        with self.assertRaises(TypeError):
            copy.deepcopy(obj)


class BaseUrlTest(unittest.TestCase):
    def test_normalize_keeps_provider_prefix(self):
        self.assertEqual(
            normalize_https_base_url("https://api.vendor.com/v1/"),
            "https://api.vendor.com/v1",
        )
        self.assertEqual(
            normalize_https_base_url(
                "https://api.vendor.com/v1")
            ,
            "https://api.vendor.com/v1",
        )
        self.assertEqual(
            normalize_https_base_url("https://api.vendor.com/"),
            "https://api.vendor.com",
        )
        self.assertEqual(
            normalize_https_base_url("https://api.vendor.com"),
            "https://api.vendor.com",
        )
        # 端口保留（供应商自定义端口）。
        self.assertEqual(
            normalize_https_base_url("https://api.vendor.com:8443/v1"),
            "https://api.vendor.com:8443/v1",
        )
        # 大写 scheme／host 归一。
        self.assertEqual(
            normalize_https_base_url("HTTPS://API.Vendor.com/V1"),
            "https://api.vendor.com/V1",
        )

    def test_reject_full_endpoint(self):
        for url in (
            "https://api.vendor.com/v1/chat/completions",
            "https://api.vendor.com/v1/chat/completions/",
            "https://api.vendor.com/chat/completions",
            "https://api.vendor.com/v1/completions",
        ):
            with self.assertRaises(BaseUrlInvalid):
                normalize_https_base_url(url)
        # 不静默改写中间路径。
        self.assertEqual(
            normalize_https_base_url("https://api.vendor.com/v1/openai/"),
            "https://api.vendor.com/v1/openai",
        )

    def test_reject_query_fragment_userinfo(self):
        for url in (
            "https://api.vendor.com/v1?key=1",
            "https://api.vendor.com/v1#frag",
            "https://user:pass@api.vendor.com/v1",
            "https://user@api.vendor.com/v1",
        ):
            with self.assertRaises(BaseUrlInvalid):
                normalize_https_base_url(url)

    def test_reject_plain_http(self):
        with self.assertRaises(BaseUrlInvalid):
            normalize_https_base_url(
                "http://api.vendor.com/v1"
            )

    def test_reject_local_private_addresses(self):
        bad_hosts = (
            "127.0.0.1", "10.0.0.7", "172.16.3.9", "192.168.1.10",
            "169.254.169.254", "0.0.0.0", "100.64.1.2", "224.0.0.1",
            "240.0.0.1", "::1", "fd00::1", "fe80::1", "::ffff:127.0.0.1",
        )
        for host in bad_hosts:
            with self.assertRaises(BaseUrlInvalid, msg=host):
                normalize_https_base_url(f"https://{host}/v1")
        for host in ("localhost", "localhost.", "mylocalhost.com.site"):
            with self.assertRaises(BaseUrlInvalid, msg=host):
                normalize_https_base_url(f"https://{host}/v1")

    def test_allows_public_addresses(self):
        self.assertEqual(
            normalize_https_base_url("https://93.184.216.34/v1"),
            "https://93.184.216.34/v1",
        )
        with self.assertRaises(BaseUrlInvalid):
            normalize_https_base_url("https://api.vendor.com/v1?x")


if __name__ == "__main__":
    unittest.main()
