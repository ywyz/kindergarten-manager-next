"""1A per-account AI config versioning service (pure service layer).

Checklist §4.1 / §5.1–5.5 / §7:

* append-only ``ai_config_versions`` rows with a composite-FK head pointer
  (``ai_config_heads``); head missing behaves as expected_version 0;
* secret kept/restored/rotated/cleared strictly per §5.1: keeping means
  re-encrypting the SAME plaintext under a fresh nonce and the NEW
  config_version AAD; the previous row's ciphertext bytes never change;
* writes commit version row + head + operation record + row link in one
  transaction; any failure rolls the whole path back;
* typed separation of the desensitized view and the internal decrypted
  object (§5.4), with repr/log leakage blocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pydantic import SecretStr

from app import security
from app.models import Account, AiConfigHead, AiConfigVersion
from app.services import ai_crypto, auth_service, ai_locks
from app.services.ai_config_url import normalize_https_base_url
from app.services.auth_service import AuthSnapshot

SUPPORTED_PROTOCOLS = ("chat_completions_v1",)

MAX_MODEL_CHARS = 200


class _SecretUnset:
    def __repr__(self) -> str:  # never carries material
        return "SECRET_UNSET"


SECRET_UNSET = _SecretUnset()


class AiConfigValidationError(Exception):
    """Typed VALIDATION_ERROR (422-class mapping in 1B)."""


READY_REASONS = (
    "MISSING_URL",
    "MISSING_MODEL",
    "MISSING_SECRET",
    "DECRYPT_UNAVAILABLE",
    "NOT_CONFIGURED",
)


@dataclass(frozen=True)
class AiConfigView:
    """Desensitized config view for settings/GET/logging (no secret ever).

    This is the ONLY object intended for serialization (API / logs); the
    dataclass conversion chain stays clean because it never contains the
    secret.
    """

    account_id: str
    head_exists: bool
    version: int | None
    protocol_id: str | None
    base_url: str | None
    model: str | None
    has_secret: bool
    ready: bool
    ready_reason: str | None


class _SecretVaultStrError(TypeError):
    pass


class DecryptedConfig:
    """Internal authorized-executor object; NOT for settings/GET/logging.

    R4: not a dataclass, ``__slots__`` only (no ``__dict__``), no iterable /
    mapping exits — ``vars()``, ``dict()``, ``dataclasses.asdict()`` and
    FastAPI ``jsonable_encoder`` all fail instead of exposing plaintext. The
    secret is stored as ``SecretStr`` and is only readable through the
    explicit ``reveal_secret()`` accessor for authorized internal callers.
    """

    __slots__ = (
        "account_id",
        "config_version",
        "protocol_id",
        "base_url",
        "model",
        "_secret",
    )

    def __init__(
        self,
        *,
        account_id: str,
        config_version: int,
        protocol_id: str,
        base_url: str,
        model: str,
        secret: str,
    ) -> None:
        object.__setattr__(self, "account_id", account_id)
        object.__setattr__(self, "config_version", config_version)
        object.__setattr__(self, "protocol_id", protocol_id)
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "_secret", SecretStr(secret))

    def reveal_secret(self) -> str:
        """Authorized internal path to the plaintext (call, use, release)."""
        return object.__getattribute__(self, "_secret").get_secret_value()

    def __setattr__(self, name: str, value: Any) -> None:
        raise TypeError("DecryptedConfig is immutable after creation")

    def __delattr__(self, name: str) -> None:
        raise TypeError("DecryptedConfig is immutable")

    def __repr__(self) -> str:
        return (
            "DecryptedConfig(account_id=%r, config_version=%r, "
            "protocol_id=%r, base_url=%r, model=%r, secret=<redacted>)"
            % (
                self.account_id,
                self.config_version,
                self.protocol_id,
                self.base_url,
                self.model,
            )
        )

    def __bytes__(self) -> bytes:  # defensive
        raise _SecretVaultStrError("DecryptedConfig is not serializable")

    def __reduce__(self):  # unreachable for pickle/copy
        raise _SecretVaultStrError("DecryptedConfig must not be serialized")

    def __iter__(self):  # no dict()/kwargs-style exit
        raise _SecretVaultStrError("DecryptedConfig is not iterable")

    def keys(self):  # no dict(**obj) style exit
        raise _SecretVaultStrError("DecryptedConfig has no key view")

    def __getitem__(self, key: str) -> Any:
        raise _SecretVaultStrError("DecryptedConfig is not subscriptable")


def _read_head(db: Session, account_id: str) -> int | None:
    return db.scalar(
        select(AiConfigHead.config_version).where(
            AiConfigHead.account_id == account_id
        )
    )


def _read_version_row(
    db: Session, account_id: str, version: int, *, current: bool = False
) -> AiConfigVersion | None:
    """``current=False``：纯展示读（普通快照）；``current=True``：写路径在
    head 已锁定后的 current 锁定读（FOR SHARE ＋ populate_existing，R6）。
    版本行 append-only，无写冲突，但新指针指向的行必须用 current 读。"""
    query = select(AiConfigVersion).where(
        AiConfigVersion.account_id == account_id,
        AiConfigVersion.version == version,
    )
    if current:
        query = query.with_for_update(read=True).execution_options(
            populate_existing=True
        )
    return db.execute(query).scalar_one_or_none()


def _evaluate_ready(
    row: AiConfigVersion | None, *, head_missing: bool
) -> tuple[bool, str | None]:
    """R3: readiness proves the CURRENT ciphertext authenticates.

    A stored secret is only ready when the row's own account/version/key_id
    chain still decrypts: missing/invalid material, foreign key_id, tampered
    ciphertext or AAD mismatch all degrade to DECRYPT_UNAVAILABLE. No secret
    stays MISSING_SECRET; the view never carries plaintext and nothing is
    cached on success.
    """
    if head_missing or row is None:
        return False, "NOT_CONFIGURED"
    if not row.base_url:
        return False, "MISSING_URL"
    if not row.model:
        return False, "MISSING_MODEL"
    if row.secret_ciphertext is None:
        return False, "MISSING_SECRET"
    try:
        plaintext = ai_crypto.decrypt_secret(
            row.secret_ciphertext,
            key_id=row.key_id,
            account_id=row.account_id,
            config_version=row.version,
        )
    except (
        ai_crypto.KeyMaterialMissing,
        ai_crypto.KeyMaterialInvalid,
        ai_crypto.DecryptUnavailable,
    ):
        return False, "DECRYPT_UNAVAILABLE"
    del plaintext  # 认证即丢弃，不缓存明文（R3）
    return True, None


def _validate_save_inputs(
    *, protocol_id: str, base_url: str, model: str
) -> tuple[str, str]:
    if protocol_id not in SUPPORTED_PROTOCOLS:
        raise AiConfigValidationError(f"不支持的协议 {protocol_id!r}")
    normalized_url = normalize_https_base_url(base_url, protocol_id=protocol_id)
    if not isinstance(model, str) or not model.strip():
        raise AiConfigValidationError("model 不能为空")
    model = model.strip()
    if len(model) > MAX_MODEL_CHARS:
        raise AiConfigValidationError(f"model 长度不能超过 {MAX_MODEL_CHARS} 字符")
    return normalized_url, model


def _check_expected(
    head_version: int | None, expected_version: Any
) -> None:
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise AiConfigValidationError("expected_version 必须是非负整数")
    if expected_version < 0:
        raise AiConfigValidationError("expected_version 必须是非负整数")
    current = head_version if head_version is not None else 0
    if expected_version != current:
        raise auth_service.VersionConflict(
            f"expected_version {expected_version} 与当前 {current} 不一致"
        )


def get_config(
    db: Session,
    snapshot: AuthSnapshot,
    target_account_id: str,
) -> AiConfigView:
    """Read own desensitized config (latest head); operator must be target."""
    ai_locks.assert_self(snapshot.account_id, target_account_id)
    ai_locks.verify_self_read(db, snapshot)
    return resolve_effective_config(db, target_account_id)


def resolve_effective_config(
    db: Session, target_account_id: str
) -> AiConfigView:
    """Shared 'latest effective config' resolution (API + future worker).

    No locking, no adaptation/readiness filtering beyond the plain ready
    evaluation of the head version row; head missing => NOT_CONFIGURED.
    """
    head_version = _read_head(db, target_account_id)
    row = None if head_version is None else _read_version_row(
        db, target_account_id, head_version
    )
    ready, ready_reason = _evaluate_ready(
        row, head_missing=head_version is None
    )
    return AiConfigView(
        account_id=target_account_id,
        head_exists=head_version is not None,
        version=head_version,
        protocol_id=row.protocol_id if row else None,
        base_url=row.base_url if row else None,
        model=row.model if row else None,
        has_secret=row.secret_ciphertext is not None if row else False,
        ready=ready,
        ready_reason=ready_reason,
    )


def read_pinned_config(
    db: Session, target_account_id: str, config_version: int
) -> DecryptedConfig:
    """Read one exact version and decrypt with THAT row's own AAD/key_id.

    Does not touch the head, never re-resolves to another version and does
    no readiness/adaptation filtering (caller decides). decryption happens
    inside the caller's transaction for safe rollback.
    """
    row = _read_version_row(db, target_account_id, config_version)
    if row is None:
        raise auth_service.AccountNotFound()
    plaintext = _decrypt_row(db, row)
    return DecryptedConfig(
        account_id=row.account_id,
        config_version=row.version,
        protocol_id=row.protocol_id,
        base_url=row.base_url,
        model=row.model,
        secret=plaintext,
    )


def _decrypt_row(db: Session, row: AiConfigVersion) -> str:
    if row.secret_ciphertext is None or row.key_id is None:
        raise ai_crypto.DecryptUnavailable("该版本没有密钥")
    return ai_crypto.decrypt_secret(
        row.secret_ciphertext,
        key_id=row.key_id,
        account_id=row.account_id,
        config_version=row.version,
    )


def _audit_for_account(
    db: Session, account: Account, operator, action: str
) -> dict[str, Any]:
    """Insert the operation record and return info for the version row.

    The account version is recorded as-is (real ``accounts.version``); the
    config change itself never advances the account version.
    """
    record = auth_service.record_operation(
        db,
        operator_id=operator,
        operator_type="account",
        action=action,
        target_type="account",
        target_id=account.id,
        target_version_after=account.version,
    )
    # 审计先行 flush 取得引用（§7.3），保证后续 FK 的行内引用在提交前有效。
    db.flush()
    return dict(record_id=record.id, account_version=account.version)


def save_config(
    db: Session,
    snapshot: AuthSnapshot,
    expected_version: int,
    protocol_id: str,
    base_url: str,
    model: str,
    secret: str | _SecretUnset = SECRET_UNSET,
) -> AiConfigView:
    """Append a new config version (operator == target), §4.1.

    Not passed secret -> keep semantics: same plaintext encrypted again with
    a fresh nonce and the NEW version AAD (old row bytes unchanged).
    Explicit null/"" -> VALIDATION_ERROR; clearing is clear_secret().
    """
    ai_locks.assert_self(snapshot.account_id, snapshot.account_id)
    normalized_url, normalized_model = _validate_save_inputs(
        protocol_id=protocol_id, base_url=base_url, model=model
    )
    if secret is not SECRET_UNSET and (secret is None or secret == ""):
        raise AiConfigValidationError(
            "secret 为 null／空串不等同于清除；清除请使用 clear_secret"
        )

    if not db.in_transaction():
        db.begin()
    try:
        account = ai_locks.lock_self(db, snapshot)
        head = ai_locks.lock_config_head(db, account.id)

        head_version = None if head is None else head.config_version
        _check_expected(head_version, expected_version)

        if secret is SECRET_UNSET:
            if head is None:
                raise AiConfigValidationError(
                    "首个有效配置必须 URL＋model＋secret"
                )
            current_row = _read_version_row(
                db, account.id, head.config_version, current=True
            )
            assert current_row is not None  # composite FK guarantees it
            if current_row.secret_ciphertext is not None:
                # 保留路径先解密再以新 nonce + 新版本 AAD 重加密；
                # 解密失败 -> 整个事务回滚，不落“缺密”新版本。
                plaintext = _decrypt_row(db, current_row)
            else:
                plaintext = None
        else:
            plaintext = secret

        new_version = (head_version or 0) + 1
        audit = _audit_for_account(
            db, account, account.id, "ai_config_save"
        )
        if plaintext is None:
            ciphertext = None
            key_id = None
        else:
            # 加密在事务内、版本行写入前完成；失败随事务回滚（§5.3）。
            ciphertext, key_id = ai_crypto.encrypt_secret(
                plaintext, account.id, new_version
            )
            del plaintext  # 引用即释放，明文不留在作用域内
        version_row = AiConfigVersion(
            id=security.generate_id(),
            account_id=account.id,
            version=new_version,
            protocol_id=protocol_id,
            base_url=normalized_url,
            model=normalized_model,
            secret_ciphertext=ciphertext,
            key_id=key_id,
            created_by=account.id,
            operation_record_id=audit["record_id"],
            created_at=auth_service.utc_now(),
        )
        db.add(version_row)
        # 先落版本行再动 head（复合 FK 需要 (account, version) 已存在）。
        db.flush()
        if head is None:
            db.add(
                AiConfigHead(
                    account_id=account.id,
                    config_version=new_version,
                    updated_at=auth_service.utc_now(),
                )
            )
        else:
            head.config_version = new_version
            head.updated_at = auth_service.utc_now()
        db.commit()
    except auth_service.VersionConflict:
        db.rollback()
        raise
    except AiConfigValidationError:
        db.rollback()
        raise
    except ai_crypto.DecryptUnavailable:
        db.rollback()
        raise
    except IntegrityError:
        # 强制完整性错误按真实原因原样 re-raise，不伪装 409。
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return resolve_effective_config(db, account.id)


def clear_secret(
    db: Session,
    snapshot: AuthSnapshot,
    expected_version: int,
) -> AiConfigView:
    """Produce a new 'not configured' version keeping URL/model (§4.1).

    Never needs to decrypt the old ciphertext, so it also succeeds when the
    key material is missing/invalid. Idempotent when head missing and
    expected_version == 0.
    """
    ai_locks.assert_self(snapshot.account_id, snapshot.account_id)
    if not db.in_transaction():
        db.begin()
    try:
        account = ai_locks.lock_self(db, snapshot)
        head = ai_locks.lock_config_head(db, account.id)
        head_version = None if head is None else head.config_version

        _check_expected(head_version, expected_version)
        if head is None:
            db.commit()
            return resolve_effective_config(db, account.id)

        current_row = _read_version_row(
            db, account.id, head.config_version, current=True
        )
        assert current_row is not None

        new_version = head.config_version + 1
        audit = _audit_for_account(
            db, account, account.id, "ai_config_secret_clear"
        )
        db.add(
            AiConfigVersion(
                id=security.generate_id(),
                account_id=account.id,
                version=new_version,
                protocol_id=current_row.protocol_id,
                base_url=current_row.base_url,
                model=current_row.model,
                secret_ciphertext=None,
                key_id=None,
                created_by=account.id,
                operation_record_id=audit["record_id"],
                created_at=auth_service.utc_now(),
            )
        )
        db.flush()  # 先落版本行再推进 head（复合 FK 依赖）
        head.config_version = new_version
        head.updated_at = auth_service.utc_now()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return resolve_effective_config(db, account.id)
