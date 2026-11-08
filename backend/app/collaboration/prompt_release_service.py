"""Signed prompt-release drafts, preview/stable channels and rollbacks.

The service owns three things:

* immutable, complete guidance snapshots (draft -> preview -> stable);
* a serialized release ledger with strictly increasing sequences;
* signed package/manifest files written before the database becomes visible.

It deliberately imports the pure local prompt catalogue lazily so an
unconfigured collaboration service still starts and keeps the existing admin
and teacher routes working.  No request supplies a filesystem path, key id,
signing key, schema, model or tool setting.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .errors import CollaborationError
from .prompt_release_models import (
    PromptRelease,
    PromptReleaseDraft,
    PromptReleaseState,
)

FORMAT_VERSION = 1
PAYLOAD_SCHEMA_VERSION = 1
MANIFEST_PREFIX = b"kgm-prompt-manifest-v1\n"
CHANNELS = ("preview", "stable")
MAX_NOTES_CHARS = 500
MAX_KEY_ID_CHARS = 64
MIN_CLIENT_VERSION = "0.1.0"
MAX_CLIENT_VERSION = "0.1.99"
MANIFEST_NAME = "latest.json"
_VERSION_FILE_RE = re.compile(r"^v([1-9][0-9]*)-([0-9a-f]{64})\.json$")

ENV_SIGNING_KEY_FILE = "KGM_COLLAB_PROMPT_SIGNING_KEY_FILE"
ENV_KEY_ID = "KGM_COLLAB_PROMPT_KEY_ID"
ENV_PACKAGE_DIR = "KGM_COLLAB_PROMPT_PACKAGE_DIR"


@dataclass(frozen=True)
class _PromptCatalog:
    task_types: tuple[str, ...]
    open_task_types: tuple[str, ...]
    open_fields: dict[str, tuple[str, ...]]
    latest_bundles: dict[str, dict[str, Any]]
    guidance_max_chars: int
    canonical_json: Any


@lru_cache(maxsize=1)
def _catalog() -> _PromptCatalog:
    # Lazy by design: an unconfigured server must not require the desktop
    # prompt modules merely to start the existing collaboration service.
    from app.local.prompt_bundles import (
        GUIDANCE_MAX_CHARS,
        PROMPT_BUNDLE_MANIFEST,
        canonical_json,
    )
    from app.local.prompt_package import (
        PACKAGE_OPEN_GUIDANCE_FIELDS,
        PACKAGE_OPEN_TASK_TYPES,
        PACKAGE_TASK_TYPES,
    )

    latest_bundles: dict[str, dict[str, Any]] = {}
    for bundle in PROMPT_BUNDLE_MANIFEST:
        task_type = str(bundle["task_type"])
        current = latest_bundles.get(task_type)
        candidate_key = (
            int(bundle["contract_version"]),
            int(bundle["default_revision"]),
        )
        current_key = (
            (
                int(current["contract_version"]),
                int(current["default_revision"]),
            )
            if current is not None
            else (-1, -1)
        )
        if candidate_key > current_key:
            latest_bundles[task_type] = bundle
    for task_type in PACKAGE_TASK_TYPES:
        if task_type not in latest_bundles:
            raise RuntimeError("prompt release catalogue is incomplete")
    open_fields = {
        task_type: tuple(PACKAGE_OPEN_GUIDANCE_FIELDS[task_type])
        for task_type in PACKAGE_TASK_TYPES
    }
    for task_type, fields in open_fields.items():
        guidance = latest_bundles[task_type]["guidance_defaults_json"]
        if not set(fields).issubset(set(guidance)):
            raise RuntimeError("prompt release catalogue field mismatch")
    return _PromptCatalog(
        task_types=tuple(PACKAGE_TASK_TYPES),
        open_task_types=tuple(PACKAGE_OPEN_TASK_TYPES),
        open_fields=open_fields,
        latest_bundles=latest_bundles,
        guidance_max_chars=int(GUIDANCE_MAX_CHARS),
        canonical_json=canonical_json,
    )


def _not_configured() -> CollaborationError:
    return CollaborationError(
        503,
        "PROMPT_RELEASE_NOT_CONFIGURED",
        "提示词发布未配置",
    )


def _invalid(message: str) -> CollaborationError:
    return CollaborationError(422, "PROMPT_RELEASE_INVALID", message)


def _not_found(message: str = "没有找到对应提示词发布") -> CollaborationError:
    return CollaborationError(404, "PROMPT_RELEASE_NOT_FOUND", message)


def _base_stale(current_stable_sequence: int | None) -> CollaborationError:
    return CollaborationError(
        409,
        "PROMPT_RELEASE_BASE_STALE",
        "正式版已变化，请重新读取后再发布",
        details={"current_stable_sequence": current_stable_sequence},
    )


def _storage_error() -> CollaborationError:
    return CollaborationError(
        503,
        "PROMPT_RELEASE_STORAGE_ERROR",
        "提示词发布文件暂时不可用",
    )


def _state_invalid() -> CollaborationError:
    return CollaborationError(
        503,
        "PROMPT_RELEASE_STATE_INVALID",
        "提示词发布数据不完整",
    )


@dataclass(frozen=True)
class PromptReleaseConfig:
    signing_key_file: Path
    key_id: str
    package_dir: Path

    @classmethod
    def from_env(cls) -> "PromptReleaseConfig":
        raw_key = os.environ.get(ENV_SIGNING_KEY_FILE, "").strip()
        raw_key_id = os.environ.get(ENV_KEY_ID, "").strip()
        raw_dir = os.environ.get(ENV_PACKAGE_DIR, "").strip()
        if not raw_key or not raw_key_id or not raw_dir:
            raise _not_configured()
        if not _valid_key_id(raw_key_id):
            raise _not_configured()
        try:
            key_path = Path(raw_key)
            package_dir = Path(raw_dir)
            if not key_path.is_absolute() or not package_dir.is_absolute():
                raise _not_configured()
            return cls(
                signing_key_file=key_path.resolve(),
                key_id=raw_key_id,
                package_dir=package_dir.resolve(),
            )
        except (OSError, RuntimeError):
            raise _not_configured() from None

    def load_private_key(self) -> Ed25519PrivateKey:
        try:
            raw = self.signing_key_file.read_bytes()
        except OSError:
            raise _storage_error() from None
        if len(raw) != 32:
            raise _storage_error()
        try:
            return Ed25519PrivateKey.from_private_bytes(raw)
        except (TypeError, ValueError):
            raise _storage_error() from None


def package_root_from_env() -> Path:
    raw = os.environ.get(ENV_PACKAGE_DIR, "").strip()
    if not raw:
        raise _not_configured()
    try:
        path = Path(raw)
        if not path.is_absolute():
            raise _not_configured()
        return path.resolve()
    except (OSError, RuntimeError):
        raise _not_configured() from None


def _valid_key_id(value: str) -> bool:
    if not (1 <= len(value) <= MAX_KEY_ID_CHARS):
        return False
    return all(0x21 <= ord(character) <= 0x7E for character in value)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _checked_text(value: object, *, maximum: int, field: str) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} 必须是字符串")
    if "\x00" in value:
        raise _invalid(f"{field} 不能包含空字符")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise _invalid(f"{field} 不是有效文本") from None
    if len(value) > maximum:
        raise _invalid(f"{field} 最多 {maximum} 个字符")
    return value


def _checked_notes(value: object) -> str:
    return _checked_text(value, maximum=MAX_NOTES_CHARS, field="notes")


def _normalize_changes(changes: object) -> dict[str, dict[str, str]]:
    catalog = _catalog()
    if not isinstance(changes, Mapping):
        raise _invalid("changes 必须是任务到字段的对象")
    normalized: dict[str, dict[str, str]] = {}
    for task_type, fields in changes.items():
        if (
            not isinstance(task_type, str)
            or task_type not in catalog.open_fields
            or not catalog.open_fields[task_type]
        ):
            raise _invalid("changes 包含未开放的提示词任务")
        if not isinstance(fields, Mapping):
            raise _invalid(f"{task_type} 的修改必须是字段对象")
        task_changes: dict[str, str] = {}
        for field, text in fields.items():
            if (
                not isinstance(field, str)
                or field not in catalog.open_fields[task_type]
            ):
                raise _invalid(f"{task_type} 包含未开放的提示词字段")
            task_changes[field] = _checked_text(
                text,
                maximum=catalog.guidance_max_chars,
                field=f"{task_type}.{field}",
            )
        if task_changes:
            normalized[task_type] = task_changes
    return normalized


def _builtin_payload() -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    catalog = _catalog()
    content: dict[str, dict[str, str]] = {}
    revisions: dict[str, int] = {}
    for task_type in catalog.open_task_types:
        latest = catalog.latest_bundles[task_type]
        guidance = latest["guidance_defaults_json"]
        content[task_type] = {
            field: str(guidance[field])
            for field in catalog.open_fields[task_type]
        }
        revisions[task_type] = int(latest["default_revision"])
    return content, revisions


def _normalize_release_payload(
    content: object,
    revisions: object,
) -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    catalog = _catalog()
    if not isinstance(content, Mapping) or set(content) != set(
        catalog.open_task_types
    ):
        raise _state_invalid()
    if not isinstance(revisions, Mapping) or set(revisions) != set(
        catalog.open_task_types
    ):
        raise _state_invalid()
    normalized_content: dict[str, dict[str, str]] = {}
    normalized_revisions: dict[str, int] = {}
    for task_type in catalog.open_task_types:
        fields = content.get(task_type)
        if not isinstance(fields, Mapping) or set(fields) != set(
            catalog.open_fields[task_type]
        ):
            raise _state_invalid()
        task_content: dict[str, str] = {}
        for field in catalog.open_fields[task_type]:
            value = fields.get(field)
            if not isinstance(value, str) or len(value) > catalog.guidance_max_chars:
                raise _state_invalid()
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                raise _state_invalid() from None
            if "\x00" in value:
                raise _state_invalid()
            task_content[field] = value
        normalized_content[task_type] = task_content
        revision = revisions.get(task_type)
        if (
            not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 1
        ):
            raise _state_invalid()
        normalized_revisions[task_type] = revision
    return normalized_content, normalized_revisions


def _draft_payload(
    row: PromptReleaseDraft,
) -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    return _normalize_release_payload(row.content, row.revisions)


def _release_payload(
    row: PromptRelease,
) -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    return _normalize_release_payload(row.content, row.revisions)


def _latest_release(
    session: Session,
    channel: str,
    *,
    for_update: bool = False,
) -> PromptRelease | None:
    query = (
        select(PromptRelease)
        .where(PromptRelease.channel == channel)
        .order_by(PromptRelease.release_sequence.desc())
        .limit(1)
    )
    if for_update:
        query = query.with_for_update()
    return session.scalars(query).one_or_none()


def _latest_release_any(session: Session) -> PromptRelease | None:
    return session.scalars(
        select(PromptRelease)
        .order_by(PromptRelease.release_sequence.desc())
        .limit(1)
    ).one_or_none()


def _revision_base(
    session: Session,
) -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    latest = _latest_release_any(session)
    if latest is None:
        return _builtin_payload()
    return _release_payload(latest)


def _monotonic_revisions(
    base_content: dict[str, dict[str, str]],
    base_revisions: dict[str, int],
    content: dict[str, dict[str, str]],
) -> dict[str, int]:
    """Assign globally monotonic task revisions at publication time.

    The latest release of either channel is the identity baseline.  Unchanged
    task text keeps its revision; changed text gets a strictly higher revision
    no matter which channel emitted the previous release.  This prevents two
    drafts based on the same stable text from minting the same default
    revision for different guidance.
    """

    catalog = _catalog()
    revisions: dict[str, int] = {}
    for task_type in catalog.open_task_types:
        latest = catalog.latest_bundles[task_type]
        builtin = int(latest["default_revision"])
        builtin_guidance = latest["guidance_defaults_json"]
        builtin_content = {
            field: str(builtin_guidance[field])
            for field in catalog.open_fields[task_type]
        }
        current = max(builtin, int(base_revisions[task_type]))
        if content[task_type] == base_content[task_type]:
            revision = current
        else:
            revision = current + 1
        if (
            content[task_type] != builtin_content
            and revision <= builtin
        ):
            revision = builtin + 1
        revisions[task_type] = revision
    return revisions


def _release_for_draft(
    session: Session, channel: str, draft_id: UUID
) -> PromptRelease | None:
    return session.scalars(
        select(PromptRelease).where(
            PromptRelease.channel == channel,
            PromptRelease.draft_id == draft_id,
        )
    ).one_or_none()


def _rollback_for_baseline(
    session: Session,
    target_sequence: int,
    expected_stable_sequence: int,
) -> PromptRelease | None:
    return session.scalars(
        select(PromptRelease).where(
            PromptRelease.rollback_of == target_sequence,
            PromptRelease.expected_stable_sequence
            == expected_stable_sequence,
        )
    ).one_or_none()


def _lock_state(session: Session) -> PromptReleaseState:
    state = session.scalars(
        select(PromptReleaseState)
        .where(PromptReleaseState.id == 1)
        .with_for_update()
    ).one_or_none()
    if state is None:
        raise _state_invalid()
    if not isinstance(state.last_sequence, int) or state.last_sequence < 0:
        raise _state_invalid()
    return state


def _next_sequence(session: Session, state: PromptReleaseState) -> int:
    maximum = session.scalar(
        select(func.max(PromptRelease.release_sequence))
    )
    next_sequence = max(
        int(state.last_sequence), int(maximum or 0)
    ) + 1
    state.last_sequence = next_sequence
    state.updated_at = _now()
    return next_sequence


def _draft_item(row: PromptReleaseDraft) -> dict[str, Any]:
    return {
        "draft_id": str(row.id),
        "notes": row.notes,
        "base_stable_sequence": row.base_stable_sequence,
        "changes": row.changes,
    }


def _release_item(row: PromptRelease) -> dict[str, Any]:
    return {
        "release_sequence": row.release_sequence,
        "channel": row.channel,
        "draft_id": str(row.draft_id) if row.draft_id is not None else None,
        "notes": row.notes,
        "rollback_of": row.rollback_of,
    }


def _bundle_payload(
    content: dict[str, dict[str, str]],
    revisions: dict[str, int],
) -> dict[str, Any]:
    catalog = _catalog()
    bundles: list[dict[str, Any]] = []
    for task_type in catalog.task_types:
        latest = catalog.latest_bundles[task_type]
        guidance = dict(latest["guidance_defaults_json"])
        if catalog.open_fields[task_type]:
            for field in catalog.open_fields[task_type]:
                guidance[field] = content[task_type][field]
            revision = revisions[task_type]
        else:
            revision = int(latest["default_revision"])
        bundles.append(
            {
                "task_type": task_type,
                "contract_version": int(latest["contract_version"]),
                "default_revision": int(revision),
                "guidance": guidance,
            }
        )
    return {"schema_version": PAYLOAD_SCHEMA_VERSION, "bundles": bundles}


def _build_release_artifacts(
    *,
    sequence: int,
    channel: str,
    notes: str,
    content: dict[str, dict[str, str]],
    revisions: dict[str, int],
    key_id: str,
    private_key: Ed25519PrivateKey,
) -> tuple[bytes, str, str]:
    from app.local.prompt_package import PackageTrust, verify_package

    catalog = _catalog()
    payload = _bundle_payload(content, revisions)
    payload_bytes = catalog.canonical_json(payload).encode("utf-8")
    document = {
        "format_version": FORMAT_VERSION,
        "release_sequence": sequence,
        "published_at": _now().replace(microsecond=0).isoformat(),
        "min_client_version": MIN_CLIENT_VERSION,
        "max_client_version": MAX_CLIENT_VERSION,
        "notes": notes,
        "key_id": key_id,
        "payload_bytes": len(payload_bytes),
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "payload": payload,
    }
    signed = catalog.canonical_json(document).encode("utf-8")
    document["signature"] = base64.b64encode(
        private_key.sign(signed)
    ).decode("ascii")
    raw = catalog.canonical_json(document).encode("utf-8")
    package_sha256 = hashlib.sha256(raw).hexdigest()

    try:
        trust = PackageTrust(
            source_url="https://server-internal.invalid/prompt-packages",
            keys={
                key_id: private_key.public_key().public_bytes_raw()
            },
            client_version=MIN_CLIENT_VERSION,
        )
        verify_package(raw, trust)
    except Exception:
        raise _state_invalid() from None

    manifest_unsigned = {
        "format_version": FORMAT_VERSION,
        "channel": channel,
        "release_sequence": sequence,
        "package_sha256": package_sha256,
        "key_id": key_id,
    }
    manifest_signature = base64.b64encode(
        private_key.sign(
            MANIFEST_PREFIX
            + catalog.canonical_json(manifest_unsigned).encode("utf-8")
        )
    ).decode("ascii")
    return raw, package_sha256, manifest_signature


def _channel_dir(config: PromptReleaseConfig, channel: str) -> Path:
    if channel not in CHANNELS:
        raise _not_found()
    try:
        if not config.package_dir.is_absolute():
            raise _storage_error()
        base = config.package_dir.resolve()
        base.mkdir(parents=True, exist_ok=True)
        channel_dir = (base / channel).resolve()
        if not channel_dir.is_relative_to(base):
            raise _storage_error()
        channel_dir.mkdir(parents=True, exist_ok=True)
        return channel_dir
    except CollaborationError:
        raise
    except (OSError, RuntimeError):
        raise _storage_error() from None


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(f"{path.name}.tmp-{uuid4().hex}")
    try:
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        last_error: OSError | None = None
        # Windows can transiently refuse replacing a file that an indexer or
        # reader has just touched.  Retry briefly; the content is unchanged.
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                last_error = None
                break
            except OSError as exc:
                last_error = exc
                if attempt < 4:
                    time.sleep(0.01)
        if last_error is not None:
            raise last_error
    except OSError:
        raise _storage_error() from None
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def _write_package_file(
    config: PromptReleaseConfig,
    channel: str,
    sequence: int,
    package_sha256: str,
    raw: bytes,
) -> None:
    channel_dir = _channel_dir(config, channel)
    path = channel_dir / f"v{sequence}-{package_sha256}.json"
    try:
        if path.exists():
            if path.read_bytes() != raw:
                raise _storage_error()
            return
        _atomic_write(path, raw)
    except CollaborationError:
        raise
    except OSError:
        raise _storage_error() from None


def _manifest_document(row: PromptRelease) -> dict[str, Any]:
    return {
        "format_version": FORMAT_VERSION,
        "channel": row.channel,
        "release_sequence": row.release_sequence,
        "package_sha256": row.package_sha256,
        "key_id": row.key_id,
        "signature": row.manifest_signature,
    }


def _insert_release(
    session: Session,
    config: PromptReleaseConfig,
    private_key: Ed25519PrivateKey,
    *,
    sequence: int,
    channel: str,
    content: dict[str, dict[str, str]],
    revisions: dict[str, int],
    draft_id: UUID | None,
    notes: str | None,
    rollback_of: int | None,
    expected_stable_sequence: int | None,
) -> PromptRelease:
    raw, package_sha256, manifest_signature = _build_release_artifacts(
        sequence=sequence,
        channel=channel,
        notes=notes or "",
        content=content,
        revisions=revisions,
        key_id=config.key_id,
        private_key=private_key,
    )
    _write_package_file(
        config, channel, sequence, package_sha256, raw
    )
    row = PromptRelease(
        release_sequence=sequence,
        channel=channel,
        draft_id=draft_id,
        notes=notes,
        rollback_of=rollback_of,
        expected_stable_sequence=expected_stable_sequence,
        content=content,
        revisions=revisions,
        package_sha256=package_sha256,
        package_byte_size=len(raw),
        key_id=config.key_id,
        manifest_signature=manifest_signature,
        created_at=_now(),
    )
    session.add(row)
    session.flush()
    return row


def get_workspace(session: Session) -> dict[str, Any]:
    catalog = _catalog()
    releases = session.scalars(
        select(PromptRelease).order_by(
            PromptRelease.release_sequence.desc()
        )
    ).all()
    drafts = session.scalars(
        select(PromptReleaseDraft).order_by(
            PromptReleaseDraft.created_at.desc(),
            PromptReleaseDraft.id.desc(),
        )
    ).all()
    latest_preview: int | None = None
    latest_stable: int | None = None
    stable_row: PromptRelease | None = None
    for row in releases:
        if row.channel == "preview" and latest_preview is None:
            latest_preview = row.release_sequence
        elif row.channel == "stable" and latest_stable is None:
            latest_stable = row.release_sequence
            stable_row = row
        if latest_preview is not None and latest_stable is not None:
            break
    if stable_row is None:
        content, _revisions = _builtin_payload()
    else:
        content, _revisions = _release_payload(stable_row)
    editable = [
        {
            "task_type": task_type,
            "fields": {
                field: content[task_type][field]
                for field in catalog.open_fields[task_type]
            },
        }
        for task_type in catalog.open_task_types
    ]
    return {
        "editable": editable,
        "drafts": [_draft_item(row) for row in drafts],
        "releases": [_release_item(row) for row in releases],
        "latest": {"preview": latest_preview, "stable": latest_stable},
    }


def create_draft(
    session: Session,
    *,
    changes: object,
    notes: object,
) -> dict[str, Any]:
    normalized_changes = _normalize_changes(changes)
    checked_notes = _checked_notes(notes)
    with session.begin():
        stable = _latest_release(session, "stable")
        if stable is None:
            base_content, base_revisions = _builtin_payload()
            base_stable_sequence = None
        else:
            base_content, base_revisions = _release_payload(stable)
            base_stable_sequence = stable.release_sequence
        content = copy.deepcopy(base_content)
        revisions = dict(base_revisions)
        for task_type, fields in normalized_changes.items():
            for field, text in fields.items():
                content[task_type][field] = text
        for task_type in normalized_changes:
            if content[task_type] != base_content[task_type]:
                revisions[task_type] = base_revisions[task_type] + 1
        row = PromptReleaseDraft(
            id=uuid4(),
            notes=checked_notes,
            base_stable_sequence=base_stable_sequence,
            changes=normalized_changes,
            content=content,
            revisions=revisions,
            created_at=_now(),
        )
        session.add(row)
        session.flush()
        return _draft_item(row)


def publish_preview(
    session: Session,
    config: PromptReleaseConfig,
    *,
    draft_id: UUID,
) -> dict[str, Any]:
    private_key = config.load_private_key()
    with session.begin():
        state = _lock_state(session)
        draft = session.get(PromptReleaseDraft, draft_id)
        if draft is None:
            raise _not_found("没有找到该提示词草稿")
        existing = _release_for_draft(session, "preview", draft.id)
        if existing is not None:
            row = existing
        else:
            content, _draft_revisions = _draft_payload(draft)
            base_content, base_revisions = _revision_base(session)
            revisions = _monotonic_revisions(
                base_content, base_revisions, content
            )
            sequence = _next_sequence(session, state)
            row = _insert_release(
                session,
                config,
                private_key,
                sequence=sequence,
                channel="preview",
                content=content,
                revisions=revisions,
                draft_id=draft.id,
                notes=draft.notes,
                rollback_of=None,
                expected_stable_sequence=None,
            )
        item = _release_item(row)
    return item


def publish_stable(
    session: Session,
    config: PromptReleaseConfig,
    *,
    preview_sequence: int,
) -> dict[str, Any]:
    private_key = config.load_private_key()
    with session.begin():
        state = _lock_state(session)
        preview = session.get(PromptRelease, preview_sequence)
        if preview is None or preview.channel != "preview":
            raise _not_found("没有找到该预览版本")
        if preview.draft_id is None:
            raise _state_invalid()
        existing = _release_for_draft(
            session, "stable", preview.draft_id
        )
        if existing is not None:
            row = existing
        else:
            draft = session.get(PromptReleaseDraft, preview.draft_id)
            if draft is None:
                raise _state_invalid()
            current = _latest_release(session, "stable")
            current_sequence = (
                current.release_sequence if current is not None else None
            )
            if draft.base_stable_sequence != current_sequence:
                raise _base_stale(current_sequence)
            content, _preview_revisions = _release_payload(preview)
            base_content, base_revisions = _revision_base(session)
            revisions = _monotonic_revisions(
                base_content, base_revisions, content
            )
            sequence = _next_sequence(session, state)
            row = _insert_release(
                session,
                config,
                private_key,
                sequence=sequence,
                channel="stable",
                content=content,
                revisions=revisions,
                draft_id=preview.draft_id,
                notes=preview.notes,
                rollback_of=None,
                expected_stable_sequence=None,
            )
        item = _release_item(row)
    return item


def publish_rollback(
    session: Session,
    config: PromptReleaseConfig,
    *,
    target_sequence: int,
    expected_stable_sequence: int,
) -> dict[str, Any]:
    private_key = config.load_private_key()
    with session.begin():
        state = _lock_state(session)
        target = session.get(PromptRelease, target_sequence)
        if target is None or target.channel != "stable":
            raise _not_found("没有找到该正式版本")
        existing = _rollback_for_baseline(
            session, target_sequence, expected_stable_sequence
        )
        if existing is not None:
            row = existing
        else:
            current = _latest_release(session, "stable")
            current_sequence = (
                current.release_sequence if current is not None else None
            )
            if current_sequence != expected_stable_sequence:
                raise _base_stale(current_sequence)
            if target_sequence == expected_stable_sequence:
                raise _invalid("目标已经是当前正式版")
            if current is None:
                raise _state_invalid()
            target_content, _target_revisions = _release_payload(target)
            base_content, base_revisions = _revision_base(session)
            revisions = _monotonic_revisions(
                base_content, base_revisions, target_content
            )
            content = copy.deepcopy(target_content)
            sequence = _next_sequence(session, state)
            row = _insert_release(
                session,
                config,
                private_key,
                sequence=sequence,
                channel="stable",
                content=content,
                revisions=revisions,
                draft_id=None,
                notes=None,
                rollback_of=target_sequence,
                expected_stable_sequence=expected_stable_sequence,
            )
        item = _release_item(row)
    return item


def latest_manifest_bytes(session: Session, channel: str) -> bytes:
    if channel not in CHANNELS:
        raise _not_found()
    row = _latest_release(session, channel)
    if row is None:
        raise _not_found("该渠道还没有发布版本")
    return _catalog().canonical_json(
        _manifest_document(row)
    ).encode("utf-8")


def parse_package_filename(filename: str) -> tuple[int, str]:
    match = _VERSION_FILE_RE.fullmatch(filename)
    if match is None:
        raise _not_found()
    return int(match.group(1)), match.group(2)


def resolve_package_path(
    session: Session,
    package_root: Path,
    channel: str,
    sequence: int,
    package_sha256: str,
) -> Path:
    if channel not in CHANNELS:
        raise _not_found()
    row = session.get(PromptRelease, sequence)
    if (
        row is None
        or row.channel != channel
        or row.package_sha256 != package_sha256
    ):
        raise _not_found("没有找到该提示词发布包")
    try:
        if not package_root.is_absolute():
            raise _not_found("没有找到该提示词发布包")
        root = package_root.resolve()
        channel_dir = (root / channel).resolve()
        if not channel_dir.is_relative_to(root):
            raise _not_found()
        path = (
            channel_dir / f"v{sequence}-{package_sha256}.json"
        ).resolve()
        if not path.is_relative_to(channel_dir) or not path.is_file():
            raise _not_found("没有找到该提示词发布包")
        if hashlib.sha256(path.read_bytes()).hexdigest() != package_sha256:
            raise _not_found("没有找到该提示词发布包")
        return path
    except CollaborationError:
        raise
    except (OSError, RuntimeError):
        raise _not_found("没有找到该提示词发布包") from None
