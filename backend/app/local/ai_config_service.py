"""D2 local AI configuration service (engineering spec §3 and §5).

Manages AI configuration versions, encrypted credentials, and operation
receipts for the single local teacher profile. No frontend UI, no vendor
requests, no real AI call.

Hard rules (R06-R08):
- Configuration version is a strict positive integer; unconfigured is 0.
- Secret is never echoed, never logged, never stored as a plain SHA-256
  fingerprint. Every secret-bearing request (including a same-secret no-op)
  uses an HMAC-SHA256 fingerprint keyed by a key derived from the random
  master key (never from the secret); the canonical JSON being signed
  includes the secret value itself (in memory only, never persisted).
  Requests that carry no secret (omitted secret / clear) use a plain
  ``sha256`` fingerprint.
- Missing / corrupt / wrong-ACL / hard-linked key file, or an unsafe
  ``credential_root`` alias, degrades GET to ready=false with
  CREDENTIAL_UNAVAILABLE while keeping the has_secret/configured facts; it
  never pushes DB state. An explicit re-fill with a new secret creates brand
  new material and does not depend on reading the old key.
- Clear-secret is an independent action (client-supplied request_id, never
  server-random): at version 0 it is legal and does not bump; otherwise it
  creates a new config version with credential_id=null and clears every
  historical credential's nonce/ciphertext (history metadata and master key
  files are retained for receipt verification).
- GET returns has_secret/configured/ready/reason; ready requires local
  AES-GCM decryption of the stored ciphertext with AAD verification, not
  provider connectivity.
- All changes: query the persistent (profile_id, request_id) receipt FIRST,
  then the expected version — in both the initial check and the final
  BEGIN IMMEDIATE transaction. A committed re-send returns the persisted
  full redacted result unchanged; a different secret/content under the same
  key -> 409 AI_REQUEST_CONFLICT; old key unreadable -> 409
  AI_RECEIPT_UNVERIFIABLE with the persisted redacted result. Unknown
  receipt -> 404 AI_OPERATION_NOT_FOUND.
- Version conflicts use AI_VERSION_CONFLICT (never the generic D1 code).
- New key_id material is always written fresh; an ID/file collision is never
  loaded or reused (retry another ID or fail safely).
- Status reads use populate_existing to avoid SQLAlchemy identity-map staleness.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local.base import utc_now
from app.local.credentials import (
    CredentialStore,
    SavedSecret,
    derive_hmac_key,
)
from app.local.errors import (
    LocalProfileRequired,
    LocalStorageError,
    LocalValidationError,
    LocalVersionConflict,
)
from app.local.models import (
    LocalAIConfigVersion,
    LocalAICredential,
    LocalAIExecution,
    LocalAIOperation,
    LocalAIState,
    LocalAITask,
    LocalOperationRecord,
)
from app.local.tx import begin_immediate, read_scope, rollback

MAX_SECRET_LEN = 8192
MIN_SECRET_LEN = 1
MAX_MODEL_LEN = 200
PROTOCOL_ID = "chat_completions_v1"

REASON_CREDENTIAL_UNAVAILABLE = "CREDENTIAL_UNAVAILABLE"
REASON_NOT_CONFIGURED = "NOT_CONFIGURED"

# Receipt operation domains (part of the signed canonical payload).
RECEIPT_OPERATION_PATCH = "ai_config_patch"
RECEIPT_OPERATION_CLEAR = "ai_config_clear_secret"
FINGERPRINT_SALT = b"kgm-local-ai-receipt-v1"

# Execution / task states that still pin a credential and may need safe retry.
# An execution exists only once a claim starts (engineering §4.1), so a
# ``pending`` task never retains retry material; resume/retry requeues create a
# new execution that takes the new configuration. Any other state
# (pending / paused / outcome_unknown / succeeded / failed / cancelled / ended)
# must not keep a recoverable key.
_LIVE_EXECUTION_STATES = ("claimed", "dispatching", "retry_wait")
_LIVE_TASK_STATES = ("claimed", "dispatching", "retry_wait")

# Public error codes (R08).
ERROR_AI_OPERATION_NOT_FOUND = "AI_OPERATION_NOT_FOUND"
ERROR_AI_VERSION_CONFLICT = "AI_VERSION_CONFLICT"
ERROR_AI_REQUEST_CONFLICT = "AI_REQUEST_CONFLICT"
ERROR_AI_RECEIPT_UNVERIFIABLE = "AI_RECEIPT_UNVERIFIABLE"
ERROR_AI_ENDPOINT_INVALID = "AI_ENDPOINT_INVALID"


# ---------------------------------------------------------------------------
# Public error types
# ---------------------------------------------------------------------------


class AiOperationNotFound(LocalValidationError):
    code = ERROR_AI_OPERATION_NOT_FOUND
    status_code = 404
    message = "未找到该 AI 操作回执"


class AiVersionConflict(LocalVersionConflict):
    code = ERROR_AI_VERSION_CONFLICT
    message = "AI 配置版本已被其他操作更新，请重新读取后重试"


class AiRequestConflict(LocalValidationError):
    code = ERROR_AI_REQUEST_CONFLICT
    status_code = 409
    message = "同一请求 ID 使用了不同输入，不得自动换键"


class AiReceiptUnverifiable(LocalValidationError):
    code = ERROR_AI_RECEIPT_UNVERIFIABLE
    status_code = 409
    message = "原密钥不可读，无法核验该请求指纹，附已提交脱敏结果"


# ---------------------------------------------------------------------------
# ConfigOut
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigOut:
    ai_config_version: int
    protocol_id: str
    base_url: str | None
    model: str | None
    has_secret: bool
    configured: bool
    ready: bool
    reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ai_config_version": self.ai_config_version,
            "protocol_id": self.protocol_id,
            "base_url": self.base_url,
            "model": self.model,
            "has_secret": self.has_secret,
            "configured": self.configured,
            "ready": self.ready,
            "reason": self.reason,
        }


def _snapshot(out: ConfigOut, *, changed: bool, operation_kind: str) -> dict:
    """Full redacted original result persisted on a receipt (spec §5.1)."""
    data = out.to_dict()
    data["status"] = "applied"
    data["changed"] = changed
    data["operation_kind"] = operation_kind
    return data


def _config_from_result(result: dict) -> ConfigOut:
    """Replay the persisted original response without re-deriving it."""
    return ConfigOut(
        ai_config_version=int(result.get("ai_config_version", 0) or 0),
        protocol_id=result.get("protocol_id") or PROTOCOL_ID,
        base_url=result.get("base_url"),
        model=result.get("model"),
        has_secret=bool(result.get("has_secret", False)),
        configured=bool(result.get("configured", False)),
        ready=bool(result.get("ready", False)),
        reason=result.get("reason"),
    )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


# Pure endpoint helpers live in ``ai_endpoint`` so the network worker can
# normalize a target without importing the ORM/credential layer. The names
# are re-exported here unchanged for the reviewed W1 callers and tests.
from app.local.ai_endpoint import (  # noqa: F401
    AiEndpointInvalid,
    MAX_BASE_URL_LEN,
    _has_forbidden_control,
    _has_whitespace_or_control,
    _ip_allowed,
    _is_completions_path,
    _is_utf8_encodable,
    _looks_numeric_host,
    _normalize_base_url,
    _valid_hostname,
)


def _validate_secret(value: object) -> str:
    """Validate a provided secret (422). Explicit null is rejected upstream."""
    if not isinstance(value, str):
        raise LocalValidationError("secret 必须是字符串")
    if not _is_utf8_encodable(value):
        raise LocalValidationError("secret 必须是有效 UTF-8 文本")
    if len(value) < MIN_SECRET_LEN or len(value) > MAX_SECRET_LEN:
        raise LocalValidationError("secret 长度必须在 1–8192 个字符之间")
    if value != value.strip():
        raise LocalValidationError("secret 不得有首尾空白")
    if _has_forbidden_control(value):
        raise LocalValidationError("secret 不得包含控制字符")
    return value


def _normalize_model(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise LocalValidationError("model 必填且不得为空")
    if not _is_utf8_encodable(value):
        raise LocalValidationError("model 必须是有效 UTF-8 文本")
    if len(value) > MAX_MODEL_LEN:
        raise LocalValidationError("model 长度必须在 1–200 个字符之间")
    if value != value.strip():
        raise LocalValidationError("model 不得有首尾空白")
    if _has_forbidden_control(value):
        raise LocalValidationError("model 不得包含控制字符")
    return value


def _normalize_request_id(value: object) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise LocalValidationError("request_id 必须是 UUID")


# ---------------------------------------------------------------------------
# DB / credential helpers
# ---------------------------------------------------------------------------


def _get_state(session: Session) -> LocalAIState | None:
    return session.scalars(select(LocalAIState)).first()


def _read_config(
    session: Session,
) -> tuple[LocalAIState | None, LocalAIConfigVersion | None, LocalAICredential | None]:
    state = _get_state(session)
    if state is None:
        return None, None, None
    config: LocalAIConfigVersion | None = None
    if state.current_config_version is not None:
        config = session.get(
            LocalAIConfigVersion,
            (state.profile_id, state.current_config_version),
            populate_existing=True,
        )
    credential: LocalAICredential | None = None
    if config is not None and config.credential_id is not None:
        credential = session.scalars(
            select(LocalAICredential)
            .where(
                LocalAICredential.profile_id == state.profile_id,
                LocalAICredential.id == config.credential_id,
            )
            .execution_options(populate_existing=True)
        ).first()
    return state, config, credential


def _find_receipt(session: Session, profile_id: str, request_id: str):
    return session.scalars(
        select(LocalAIOperation).where(
            LocalAIOperation.profile_id == profile_id,
            LocalAIOperation.request_id == request_id,
        )
    ).first()


def _build_store(
    profile_id: str, database_uuid: str, credential_root: str | Path
) -> CredentialStore | None:
    """Construct a store, or return None if the path/uuid is unsafe."""
    try:
        return CredentialStore(credential_root, database_uuid)
    except (LocalStorageError, LocalValidationError):
        return None


def _require_store(
    profile_id: str, database_uuid: str, credential_root: str | Path
) -> CredentialStore:
    try:
        return CredentialStore(credential_root, database_uuid)
    except (LocalStorageError, LocalValidationError) as exc:
        raise LocalStorageError("凭据目录不可用") from exc


def _safe_load_master_key(store: CredentialStore | None, key_id: str | None):
    if store is None or not key_id:
        return None
    try:
        return store.load_master_key(key_id)
    except (LocalStorageError, LocalValidationError):
        return None


def _decrypt_secret(
    credential: LocalAICredential | None,
    store: CredentialStore | None,
    profile_id: str,
    credential_id: str,
) -> str | None:
    """Try to decrypt the stored secret; return None on any failure."""
    if store is None or credential is None:
        return None
    if credential.state != "active" or not credential.key_id:
        return None
    if credential.nonce is None or credential.ciphertext is None:
        return None
    if len(credential.nonce) != 12 or len(credential.ciphertext) == 0:
        return None
    try:
        master_key = store.load_master_key(credential.key_id)
    except (LocalStorageError, LocalValidationError):
        return None
    try:
        saved = SavedSecret(
            key_id=credential.key_id,
            nonce=credential.nonce,
            ciphertext=credential.ciphertext,
        )
        return store.decrypt_secret(master_key, saved, profile_id, credential_id)
    except Exception:
        return None


def _assess_ready(
    profile_id: str,
    config: LocalAIConfigVersion | None,
    credential: LocalAICredential | None,
    store: CredentialStore | None,
) -> tuple[bool, str | None, bool, bool]:
    """Return (ready, reason, configured, has_secret).

    ready requires successful AES-GCM decryption + AAD verification of the
    stored ciphertext using the locally available master key. Any credential
    failure (missing/corrupt/wrong-ACL/hardlink/unsafe root) degrades to
    CREDENTIAL_UNAVAILABLE without changing the persisted facts.
    """
    if config is None:
        return False, None, False, False
    configured = (
        config.base_url is not None
        and config.model is not None
        and config.credential_id is not None
    )
    has_secret = (
        credential is not None
        and credential.state == "active"
        and credential.nonce is not None
        and credential.ciphertext is not None
        and len(credential.nonce) == 12
        and len(credential.ciphertext) > 0
    )
    if not configured:
        return False, None, configured, has_secret
    if not has_secret:
        return False, REASON_NOT_CONFIGURED, configured, has_secret
    decrypted = _decrypt_secret(
        credential, store, profile_id, credential.id or ""
    )
    if decrypted is None:
        return False, REASON_CREDENTIAL_UNAVAILABLE, configured, has_secret
    return True, None, configured, has_secret


def _config_out(
    *,
    version: int,
    profile_id: str,
    config: LocalAIConfigVersion | None,
    credential: LocalAICredential | None,
    store: CredentialStore | None,
) -> ConfigOut:
    ready, reason, configured, has_secret = _assess_ready(
        profile_id, config, credential, store
    )
    return ConfigOut(
        ai_config_version=version,
        protocol_id=config.protocol_id if config else PROTOCOL_ID,
        base_url=config.base_url if config else None,
        model=config.model if config else None,
        has_secret=has_secret,
        configured=configured,
        ready=ready,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# GET /api/local/ai/config
# ---------------------------------------------------------------------------


def get_config(
    session: Session,
    *,
    credential_root: str | Path,
) -> ConfigOut:
    """GET /api/local/ai/config: read back redacted configuration.

    An uninitialized database is a 409 LOCAL_PROFILE_REQUIRED; an initialized
    but unconfigured profile returns version 0. Reading never creates the
    credential directory or a key and never modifies an ACL.
    """
    with read_scope(session):
        state = _get_state(session)
        if state is None:
            raise LocalProfileRequired()
        version = state.current_config_version or 0
        _, config, credential = _read_config(session)
        store = _build_store(
            state.profile_id, state.database_uuid, credential_root
        )
        return _config_out(
            version=version,
            profile_id=state.profile_id,
            config=config,
            credential=credential,
            store=store,
        )


# ---------------------------------------------------------------------------
# Fingerprint helpers (R07)
# ---------------------------------------------------------------------------


def _build_receipt_fingerprint(
    *,
    operation_kind: str,
    profile_id: str,
    expected_version: int,
    protocol_id: str | None,
    base_url: str | None,
    model: str | None,
    secret_present: bool,
    secret: str | None,
    hmac_key: bytes | None,
) -> tuple[str, str]:
    """Build (fingerprint, fingerprint_kind).

    When a secret is present the fingerprint is HMAC-SHA256 keyed by the
    master-key-derived HMAC key over canonical JSON that includes the secret
    value (in-memory only). A secret-bearing request may never fall back to a
    plain SHA-256 fingerprint. Requests with no secret use SHA-256.
    """
    payload = {
        "operation_kind": operation_kind,
        "profile_id": profile_id,
        "expected_version": expected_version,
        "protocol_id": protocol_id,
        "base_url": base_url,
        "model": model,
        "secret_present": secret_present,
        "secret": secret,
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if secret_present:
        if hmac_key is None:
            raise LocalStorageError("缺少用于回执指纹的 HMAC 密钥")
        return hmac.new(hmac_key, canonical, hashlib.sha256).hexdigest(), "hmac_sha256"
    return hashlib.sha256(canonical).hexdigest(), "sha256"


def _verify_receipt_resend(
    store: CredentialStore | None,
    receipt: LocalAIOperation,
    *,
    client_expected_version: int,
    client_operation_kind: str,
    protocol_id: str | None,
    base_url: str | None,
    model: str | None,
    secret_present: bool,
    secret: str | None,
) -> None:
    """Verify a re-send against the persisted receipt fingerprint.

    Operation domain is judged first (cross domain -> AI_REQUEST_CONFLICT,
    without reading any old key). A secret-bearing request must never match a
    plain-SHA receipt. Different content -> AI_REQUEST_CONFLICT; unreadable
    old key -> AI_RECEIPT_UNVERIFIABLE with the persisted redacted result.
    """
    if receipt.operation_kind != client_operation_kind:
        raise AiRequestConflict(details={"expected_operation": receipt.operation_kind})
    version = receipt.result_json.get("ai_config_version", 0)
    want_kind = "hmac_sha256" if secret_present else "sha256"
    if receipt.fingerprint_kind != want_kind:
        raise AiRequestConflict(details={"ai_config_version": version})
    hmac_key: bytes | None = None
    if secret_present:
        key_id = receipt.fingerprint_key_id
        master_key = _safe_load_master_key(store, key_id)
        if master_key is None:
            raise AiReceiptUnverifiable(
                details={
                    "ai_config_version": version,
                    "result": receipt.result_json,
                }
            )
        hmac_key = derive_hmac_key(master_key, FINGERPRINT_SALT)
    fingerprint, _ = _build_receipt_fingerprint(
        operation_kind=client_operation_kind,
        profile_id=receipt.profile_id,
        expected_version=client_expected_version,
        protocol_id=protocol_id,
        base_url=base_url,
        model=model,
        secret_present=secret_present,
        secret=secret,
        hmac_key=hmac_key,
    )
    if not hmac.compare_digest(fingerprint, receipt.request_fingerprint):
        raise AiRequestConflict(details={"ai_config_version": version})


def _replay(
    store: CredentialStore | None,
    receipt: LocalAIOperation,
    *,
    client_operation_kind: str,
    client_expected_version: int,
    protocol_id: str | None,
    base_url: str | None,
    model: str | None,
    secret_present: bool,
    secret: str | None,
) -> ConfigOut:
    _verify_receipt_resend(
        store,
        receipt,
        client_expected_version=client_expected_version,
        client_operation_kind=client_operation_kind,
        protocol_id=protocol_id,
        base_url=base_url,
        model=model,
        secret_present=secret_present,
        secret=secret,
    )
    return _config_from_result(receipt.result_json)


def _create_new_credential(
    store: CredentialStore, secret: str, profile_id: str
) -> tuple[str, bytes, SavedSecret]:
    """Allocate a fresh key_id and persist brand-new material.

    A key_id whose file already exists is never loaded or overwritten; the
    call retries with another id (or fails safely).
    """
    for _ in range(8):
        key_id = new_opaque_id()
        try:
            master_key = store.save_master_key(key_id)
        except LocalValidationError:
            continue  # id/name collision: never reuse the existing file
        saved = store.encrypt_secret(master_key, secret, profile_id, key_id, key_id)
        return key_id, master_key, saved
    raise LocalStorageError("无法分配唯一凭据密钥 ID")


def _retained_credential_ids(session: Session, profile_id: str) -> set[str]:
    """Credential ids pinned by a live execution that may still be retried.

    An execution only pins material while it is the owning task's current
    execution, the task is still active, and the execution has not ended. A
    retired or replaced execution (or a finished/paused task) must not keep a
    recoverable key.
    """
    rows = session.execute(
        select(LocalAIConfigVersion.credential_id)
        .join(
            LocalAIExecution,
            (LocalAIExecution.profile_id == LocalAIConfigVersion.profile_id)
            & (LocalAIExecution.config_version == LocalAIConfigVersion.version),
        )
        .join(
            LocalAITask,
            (LocalAITask.id == LocalAIExecution.task_id)
            & (LocalAITask.current_execution_id == LocalAIExecution.id),
        )
        .where(
            LocalAIExecution.profile_id == profile_id,
            LocalAIExecution.ended_at.is_(None),
            LocalAIExecution.state.in_(_LIVE_EXECUTION_STATES),
            LocalAITask.profile_id == profile_id,
            LocalAITask.status.in_(_LIVE_TASK_STATES),
        )
    ).all()
    return {row[0] for row in rows if row[0]}


def _clear_replaced_credentials(
    session: Session, profile_id: str, keep_id: str | None, now
) -> None:
    """Retire or wipe superseded credentials.

    A superseded credential that a live (claimed/dispatching/retry_wait)
    execution still pins is marked ``retired`` and keeps its material so a
    safe retry can still decrypt it. Every other superseded credential is
    ``cleared`` with its nonce/ciphertext removed.
    """
    retained = _retained_credential_ids(session, profile_id)

    def _scope():
        statement = update(LocalAICredential).where(
            LocalAICredential.profile_id == profile_id
        )
        if keep_id is not None:
            statement = statement.where(LocalAICredential.id != keep_id)
        return statement

    wipe = _scope()
    if retained:
        wipe = wipe.where(LocalAICredential.id.notin_(retained))
    session.execute(
        wipe.values(state="cleared", nonce=None, ciphertext=None, updated_at=now)
    )
    if retained:
        session.execute(
            _scope()
            .where(LocalAICredential.id.in_(retained))
            .values(state="retired", updated_at=now)
        )


# ---------------------------------------------------------------------------
# PATCH /api/local/ai/config
# ---------------------------------------------------------------------------


def patch_config(
    session: Session,
    *,
    expected_ai_config_version: int,
    base_url: object,
    model: object,
    secret: object,
    secret_provided: bool,
    request_id: str,
    credential_root: str | Path,
) -> ConfigOut:
    """PATCH /api/local/ai/config (R06-R08).

    1. Receipt first, then expected version (both here and inside the final
       BEGIN IMMEDIATE transaction).
    2. Prepare credential material outside the long write transaction.
    3. Short BEGIN IMMEDIATE: re-check receipt, re-check version with
       populate_existing, write config/credential/receipt/audit, commit.
    4. A semantically identical input records a real committed receipt but
       does not bump the version.
    """
    if not isinstance(expected_ai_config_version, int) or isinstance(
        expected_ai_config_version, bool
    ):
        raise LocalValidationError("expected_ai_config_version 必须是非负整数")
    if expected_ai_config_version < 0:
        raise LocalValidationError("expected_ai_config_version 必须是非负整数")

    rid = _normalize_request_id(request_id)
    normalized_base_url = _normalize_base_url(base_url)
    normalized_model = _normalize_model(model)
    if secret_provided:
        if secret is None:
            raise LocalValidationError("secret 不得为 null")
        normalized_secret: str | None = _validate_secret(secret)
    else:
        normalized_secret = None

    now = utc_now()

    # ---------- First read: receipt first, then expected version ----------
    with read_scope(session):
        state = _get_state(session)
        if state is None:
            raise LocalProfileRequired()
        profile_id = state.profile_id
        database_uuid = state.database_uuid
        current_version = state.current_config_version or 0
        receipt = _find_receipt(session, profile_id, rid)
        if receipt is not None:
            store = _build_store(profile_id, database_uuid, credential_root)
            return _replay(
                store,
                receipt,
                client_operation_kind=RECEIPT_OPERATION_PATCH,
                client_expected_version=expected_ai_config_version,
                protocol_id=PROTOCOL_ID,
                base_url=normalized_base_url,
                model=normalized_model,
                secret_present=secret_provided,
                secret=normalized_secret,
            )
        if current_version != expected_ai_config_version:
            raise AiVersionConflict(details={"ai_config_version": current_version})

    # ---------- Prepare material outside the long write transaction ----------
    # An omit-secret configuration change (and any no-secret receipt) must not
    # be blocked by an unsafe credential root; only writing/reading secret
    # material requires a real store.
    store = _build_store(profile_id, database_uuid, credential_root)

    current_config: LocalAIConfigVersion | None = None
    current_credential: LocalAICredential | None = None
    if current_version > 0:
        current_config = session.get(
            LocalAIConfigVersion,
            (profile_id, current_version),
            populate_existing=True,
        )
    if current_config is not None and current_config.credential_id is not None:
        current_credential = session.scalars(
            select(LocalAICredential)
            .where(
                LocalAICredential.profile_id == profile_id,
                LocalAICredential.id == current_config.credential_id,
            )
            .execution_options(populate_existing=True)
        ).first()

    current_secret = _decrypt_secret(
        current_credential,
        store,
        profile_id,
        current_credential.id if current_credential is not None else "",
    )

    same_url = (
        current_config.base_url if current_config else None
    ) == normalized_base_url
    same_model = (current_config.model if current_config else None) == normalized_model

    new_master_key: bytes | None = None
    new_credential_id: str | None
    new_nonce: bytes | None
    new_ciphertext: bytes | None
    secret_changed = False

    if secret_provided:
        same_secret_content = current_secret is not None and hmac.compare_digest(
            current_secret.encode("utf-8"), normalized_secret.encode("utf-8")
        )
        if same_secret_content and current_credential is not None:
            # Same secret content: reuse the row, but still derive an HMAC
            # fingerprint key from the existing master key (never plain SHA).
            new_credential_id = current_credential.id
            new_nonce = current_credential.nonce
            new_ciphertext = current_credential.ciphertext
            new_master_key = _safe_load_master_key(
                store, current_credential.key_id
            )
            if new_master_key is None:
                raise LocalStorageError("无法读取当前凭据主密钥")
        else:
            store = _require_store(profile_id, database_uuid, credential_root)
            new_credential_id, new_master_key, saved = _create_new_credential(
                store, normalized_secret, profile_id
            )
            new_nonce = saved.nonce
            new_ciphertext = saved.ciphertext
            secret_changed = True
    else:
        same_secret_content = True
        new_credential_id = current_credential.id if current_credential else None
        new_nonce = current_credential.nonce if current_credential else None
        new_ciphertext = current_credential.ciphertext if current_credential else None

    no_op = (
        same_url
        and same_model
        and same_secret_content
        and new_credential_id
        == (current_credential.id if current_credential else None)
    )

    hmac_key: bytes | None = None
    if secret_provided:
        if new_master_key is None:
            raise LocalStorageError("缺少用于回执指纹的 HMAC 密钥")
        hmac_key = derive_hmac_key(new_master_key, FINGERPRINT_SALT)

    # ---------- Short write transaction ----------
    begin_immediate(session)
    try:
        state = session.get(LocalAIState, profile_id, populate_existing=True)
        if state is None:
            rollback(session)
            raise LocalProfileRequired()

        # Receipt FIRST (a concurrent same-key commit must replay, not 409).
        receipt = _find_receipt(session, profile_id, rid)
        if receipt is not None:
            rollback(session)
            store_r = _build_store(profile_id, database_uuid, credential_root)
            return _replay(
                store_r,
                receipt,
                client_operation_kind=RECEIPT_OPERATION_PATCH,
                client_expected_version=expected_ai_config_version,
                protocol_id=PROTOCOL_ID,
                base_url=normalized_base_url,
                model=normalized_model,
                secret_present=secret_provided,
                secret=normalized_secret,
            )

        current_version_locked = state.current_config_version or 0
        if current_version_locked != expected_ai_config_version:
            rollback(session)
            raise AiVersionConflict(
                details={"ai_config_version": current_version_locked}
            )

        if no_op:
            fingerprint, fkind = _build_receipt_fingerprint(
                operation_kind=RECEIPT_OPERATION_PATCH,
                profile_id=profile_id,
                expected_version=current_version_locked,
                protocol_id=PROTOCOL_ID,
                base_url=normalized_base_url,
                model=normalized_model,
                secret_present=secret_provided,
                secret=normalized_secret,
                hmac_key=hmac_key,
            )
            noop_config = (
                session.get(
                    LocalAIConfigVersion,
                    (profile_id, current_version_locked),
                    populate_existing=True,
                )
                if current_version_locked > 0
                else None
            )
            noop_cred = None
            if noop_config is not None and noop_config.credential_id is not None:
                noop_cred = session.scalars(
                    select(LocalAICredential)
                    .where(
                        LocalAICredential.profile_id == profile_id,
                        LocalAICredential.id == noop_config.credential_id,
                    )
                    .execution_options(populate_existing=True)
                ).first()
            out = _config_out(
                version=current_version_locked,
                profile_id=profile_id,
                config=noop_config,
                credential=noop_cred,
                store=store,
            )
            _store_receipt_and_audit(
                session,
                state,
                rid,
                RECEIPT_OPERATION_PATCH,
                fingerprint,
                fkind,
                new_credential_id,
                _snapshot(out, changed=False, operation_kind=RECEIPT_OPERATION_PATCH),
                now,
            )
            session.commit()
            return out

        # Real change.
        if secret_changed and new_credential_id is not None:
            session.add(
                LocalAICredential(
                    id=new_credential_id,
                    profile_id=profile_id,
                    key_id=new_credential_id,
                    nonce=new_nonce,
                    ciphertext=new_ciphertext,
                    state="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            _clear_replaced_credentials(session, profile_id, new_credential_id, now)

        new_version = current_version_locked + 1
        new_config = LocalAIConfigVersion(
            profile_id=profile_id,
            version=new_version,
            protocol_id=PROTOCOL_ID,
            base_url=normalized_base_url,
            model=normalized_model,
            credential_id=new_credential_id,
            created_at=now,
        )
        session.add(new_config)
        session.flush()

        state.current_config_version = new_version
        state.blocked_config_version = None
        state.blocked_reason = None
        state.updated_at = now

        new_cred_row = None
        if new_credential_id is not None:
            new_cred_row = session.scalars(
                select(LocalAICredential)
                .where(
                    LocalAICredential.profile_id == profile_id,
                    LocalAICredential.id == new_credential_id,
                )
                .execution_options(populate_existing=True)
            ).first()
        out = _config_out(
            version=new_version,
            profile_id=profile_id,
            config=new_config,
            credential=new_cred_row,
            store=store,
        )

        fingerprint, fkind = _build_receipt_fingerprint(
            operation_kind=RECEIPT_OPERATION_PATCH,
            profile_id=profile_id,
            expected_version=current_version_locked,
            protocol_id=PROTOCOL_ID,
            base_url=normalized_base_url,
            model=normalized_model,
            secret_present=secret_provided,
            secret=normalized_secret,
            hmac_key=hmac_key,
        )
        _store_receipt_and_audit(
            session,
            state,
            rid,
            RECEIPT_OPERATION_PATCH,
            fingerprint,
            fkind,
            new_credential_id,
            _snapshot(out, changed=True, operation_kind=RECEIPT_OPERATION_PATCH),
            now,
        )
        session.commit()
        return out
    except BaseException:
        rollback(session)
        raise


def _store_receipt_and_audit(
    session: Session,
    state: LocalAIState,
    request_id: str,
    operation_kind: str,
    fingerprint: str,
    fingerprint_kind: str,
    fingerprint_key_id: str | None,
    result: dict,
    now,
) -> None:
    session.add(
        LocalAIOperation(
            id=new_opaque_id(),
            profile_id=state.profile_id,
            request_id=request_id,
            operation_kind=operation_kind,
            request_fingerprint=fingerprint,
            fingerprint_kind=fingerprint_kind,
            fingerprint_key_id=fingerprint_key_id,
            result_json=result,
            created_at=now,
        )
    )
    action = (
        "clear_local_ai_secret"
        if operation_kind == RECEIPT_OPERATION_CLEAR
        else "update_local_ai_config"
    )
    version = int(result.get("ai_config_version", 0) or 0)
    session.add(
        LocalOperationRecord(
            id=new_opaque_id(),
            created_at=now,
            actor_id=state.profile_id,
            action=action,
            target_type="local_ai_config",
            target_id=str(version),
            # The legacy audit column allows NULL or >= 1 only; version 0
            # (unconfigured) is recorded as NULL without touching the schema.
            target_version_after=version if version >= 1 else None,
        )
    )


# ---------------------------------------------------------------------------
# POST /api/local/ai/config/clear-secret
# ---------------------------------------------------------------------------


def clear_secret(
    session: Session,
    *,
    expected_ai_config_version: int,
    request_id: str,
    credential_root: str | Path,
) -> ConfigOut:
    """POST /api/local/ai/config/clear-secret (R06-R08).

    Client-supplied request_id (never server-random). At version 0 it is legal
    and does not bump; the state pointer stays NULL and the audit
    target_version_after is NULL. Otherwise it creates a new config version
    with credential_id=null and clears every historical credential's
    nonce/ciphertext. Master key files and history metadata are retained for
    receipt verification.

    Re-send under the same request_id verifies operation_kind first, then the
    full fingerprint; a cross-domain or different-content re-send is
    AI_REQUEST_CONFLICT.
    """
    if not isinstance(expected_ai_config_version, int) or isinstance(
        expected_ai_config_version, bool
    ):
        raise LocalValidationError("expected_ai_config_version 必须是非负整数")
    if expected_ai_config_version < 0:
        raise LocalValidationError("expected_ai_config_version 必须是非负整数")

    rid = _normalize_request_id(request_id)
    now = utc_now()

    # ---------- First read: receipt first, then expected version ----------
    with read_scope(session):
        state = _get_state(session)
        if state is None:
            raise LocalProfileRequired()
        profile_id = state.profile_id
        database_uuid = state.database_uuid
        current_version = state.current_config_version or 0
        receipt = _find_receipt(session, profile_id, rid)
        if receipt is not None:
            store = _build_store(profile_id, database_uuid, credential_root)
            return _replay(
                store,
                receipt,
                client_operation_kind=RECEIPT_OPERATION_CLEAR,
                client_expected_version=expected_ai_config_version,
                protocol_id=None,
                base_url=None,
                model=None,
                secret_present=False,
                secret=None,
            )
        if current_version != expected_ai_config_version:
            raise AiVersionConflict(details={"ai_config_version": current_version})

    # ---------- Short write transaction ----------
    begin_immediate(session)
    try:
        state = session.get(LocalAIState, profile_id, populate_existing=True)
        if state is None:
            rollback(session)
            raise LocalProfileRequired()

        receipt = _find_receipt(session, profile_id, rid)  # receipt FIRST
        if receipt is not None:
            rollback(session)
            store_r = _build_store(profile_id, database_uuid, credential_root)
            return _replay(
                store_r,
                receipt,
                client_operation_kind=RECEIPT_OPERATION_CLEAR,
                client_expected_version=expected_ai_config_version,
                protocol_id=None,
                base_url=None,
                model=None,
                secret_present=False,
                secret=None,
            )

        current_version = state.current_config_version or 0
        if current_version != expected_ai_config_version:
            rollback(session)
            raise AiVersionConflict(details={"ai_config_version": current_version})

        current_config = None
        if current_version > 0:
            current_config = session.get(
                LocalAIConfigVersion,
                (profile_id, current_version),
                populate_existing=True,
            )

        if current_config is None or current_config.credential_id is None:
            # Already clear (or unconfigured): record a receipt but do not
            # bump the version and keep the state pointer as-is (NULL at 0).
            out = ConfigOut(
                ai_config_version=current_version,
                protocol_id=PROTOCOL_ID,
                base_url=current_config.base_url if current_config else None,
                model=current_config.model if current_config else None,
                has_secret=False,
                configured=False,
                ready=False,
                reason=None,
            )
            fingerprint, fkind = _build_receipt_fingerprint(
                operation_kind=RECEIPT_OPERATION_CLEAR,
                profile_id=profile_id,
                expected_version=current_version,
                protocol_id=None,
                base_url=None,
                model=None,
                secret_present=False,
                secret=None,
                hmac_key=None,
            )
            _store_receipt_and_audit(
                session,
                state,
                rid,
                RECEIPT_OPERATION_CLEAR,
                fingerprint,
                fkind,
                None,
                _snapshot(out, changed=False, operation_kind=RECEIPT_OPERATION_CLEAR),
                now,
            )
            session.commit()
            return out

        # Real clear: wipe every historical credential's material.
        session.execute(
            update(LocalAICredential)
            .where(LocalAICredential.profile_id == profile_id)
            .values(state="cleared", nonce=None, ciphertext=None, updated_at=now)
        )
        new_version = current_version + 1
        new_config = LocalAIConfigVersion(
            profile_id=profile_id,
            version=new_version,
            protocol_id=PROTOCOL_ID,
            base_url=current_config.base_url,
            model=current_config.model,
            credential_id=None,
            created_at=now,
        )
        session.add(new_config)
        session.flush()
        state.current_config_version = new_version
        state.blocked_config_version = None
        state.blocked_reason = None
        state.updated_at = now

        out = ConfigOut(
            ai_config_version=new_version,
            protocol_id=PROTOCOL_ID,
            base_url=new_config.base_url,
            model=new_config.model,
            has_secret=False,
            configured=False,
            ready=False,
            reason=None,
        )
        fingerprint, fkind = _build_receipt_fingerprint(
            operation_kind=RECEIPT_OPERATION_CLEAR,
            profile_id=profile_id,
            expected_version=current_version,
            protocol_id=None,
            base_url=None,
            model=None,
            secret_present=False,
            secret=None,
            hmac_key=None,
        )
        _store_receipt_and_audit(
            session,
            state,
            rid,
            RECEIPT_OPERATION_CLEAR,
            fingerprint,
            fkind,
            None,
            _snapshot(out, changed=True, operation_kind=RECEIPT_OPERATION_CLEAR),
            now,
        )
        session.commit()
        return out
    except BaseException:
        rollback(session)
        raise


# ---------------------------------------------------------------------------
# GET /api/local/ai/operations/{request_id}
# ---------------------------------------------------------------------------


def get_operation(
    session: Session,
    *,
    request_id: str,
) -> dict[str, Any]:
    """GET /api/local/ai/operations/{request_id}: read back a receipt.

    Unknown request_id -> 404 AI_OPERATION_NOT_FOUND (not a failure).
    Receipts never contain secret material.
    """
    rid = _normalize_request_id(request_id)
    receipt = session.scalars(
        select(LocalAIOperation).where(LocalAIOperation.request_id == rid)
    ).first()
    if receipt is None:
        raise AiOperationNotFound()
    return {
        "request_id": receipt.request_id,
        "operation_kind": receipt.operation_kind,
        "result": receipt.result_json,
        "committed_at": receipt.created_at.isoformat() if receipt.created_at else None,
    }
