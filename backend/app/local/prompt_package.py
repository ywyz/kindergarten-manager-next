"""Signed default-guidance package verification (teacher feedback #6).

This module is pure: strict JSON parsing, Ed25519 verification, compatibility
and allowlist checks.  It never performs I/O, opens a database or talks to a
network.  The caller supplies one fixed trust configuration (release builds
package it; source runs intentionally leave it unconfigured) and the current
client version.

A package is one *full snapshot* of the default guidance for every task in the
first-release snapshot.  Some weekly column tasks currently have no open text
fields and are included only for identity continuity; their fixed metadata is
always local.  A later package repeats unchanged entries with their current
default revision and text.  That keeps release sequence meaningful as a
whole-package identity and lets a client apply the latest package without
guessing whether it missed a delta.

``payload_bytes`` and ``payload_sha256`` are computed over the UTF-8 canonical
JSON of the ``payload`` object (sorted keys, compact separators, no ASCII
escaping), matching :func:`app.local.prompt_bundles.canonical_json`.

Only explicitly opened guidance text may change.  Input/output JSON schemas,
weekly structural metadata (``target``, ``language``, ``strict_json``,
``no_fabricated_sources``, ``allowed_input_fields`` and similar keys), image
handling, vendor/model settings, budgets, URLs, permission and tool settings
all remain program-owned.  The package's open text is merged with the fixed
local values to form the complete registered bundle.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.local.prompt_bundles import (
    GUIDANCE_FIELDS,
    GUIDANCE_MAX_CHARS,
    OBSERVATION_TASK_TYPES,
    PROMPT_BUNDLE_MANIFEST,
    WEEKLY_TASK_TYPES,
    bundle_hash,
    canonical_json,
)

FORMAT_VERSION = 1
PAYLOAD_SCHEMA_VERSION = 1
MAX_PACKAGE_BYTES = 2 * 1024 * 1024
MAX_NOTES_CHARS = 500
MAX_KEY_ID_CHARS = 64
MAX_VERSION_CHARS = 64
MAX_SOURCE_URL_CHARS = 2048

# The source build intentionally has no remote source or production key.  A
# release build may replace these three constants with its packaged trust
# configuration; teachers never enter a URL or key in the UI.
PACKAGED_SOURCE_URL = ""
PACKAGED_KEY_ID = ""
PACKAGED_PUBLIC_KEY_B64 = ""
PACKAGED_CLIENT_VERSION = "0.1.0"

# First-release package allowlist.  It is deliberately narrower than every
# registered task: reflection, listening group notes, listening goal suggestion
# and class-game configuration are present in the local manifest but are not
# opened for remote default updates until a separate maintainer decision.  The
# list is explicit so adding a registered task can never silently open it.
PACKAGE_TASK_TYPES: tuple[str, ...] = (
    "daily_lesson_split",
    "daily_process_adapt",
    "daily_other_activities",
    *OBSERVATION_TASK_TYPES,
    *WEEKLY_TASK_TYPES,
    "listening_note_draft",
    "listening_domain_evaluate",
)

# Field-level open list.  A signed package may change only these text values;
# all other guidance keys are program structure/metadata and must match the
# locally registered bundle byte-for-byte.  The four weekly columns currently
# expose no independent guidance text, so their open tuple is empty even
# though the task remains in the full snapshot for identity continuity.
PACKAGE_OPEN_GUIDANCE_FIELDS: dict[str, tuple[str, ...]] = {
    "daily_lesson_split": tuple(GUIDANCE_FIELDS["daily_lesson_split"]),
    "daily_process_adapt": tuple(GUIDANCE_FIELDS["daily_process_adapt"]),
    "daily_other_activities": tuple(GUIDANCE_FIELDS["daily_other_activities"]),
    "game_observation_generate": tuple(
        GUIDANCE_FIELDS["game_observation_generate"]
    ),
    "game_observation_rewrite": tuple(
        GUIDANCE_FIELDS["game_observation_rewrite"]
    ),
    "weekly_games_select": ("instructions",),
    "weekly_key_week_focus": (),
    "weekly_environment_setup": (),
    "weekly_habit_culture": (),
    "weekly_home_cooperation": (),
    "weekly_materials_generate": ("instructions",),
    "listening_note_draft": tuple(GUIDANCE_FIELDS["listening_note_draft"]),
    "listening_domain_evaluate": tuple(
        GUIDANCE_FIELDS["listening_domain_evaluate"]
    ),
}
if set(PACKAGE_OPEN_GUIDANCE_FIELDS) != set(PACKAGE_TASK_TYPES):
    raise RuntimeError("prompt package open-field map is incomplete")
for _task, _open_fields in PACKAGE_OPEN_GUIDANCE_FIELDS.items():
    if not set(_open_fields).issubset(set(GUIDANCE_FIELDS[_task])):
        raise RuntimeError("prompt package open field is not registered")
PACKAGE_OPEN_TASK_TYPES: tuple[str, ...] = tuple(
    task for task in PACKAGE_TASK_TYPES if PACKAGE_OPEN_GUIDANCE_FIELDS[task]
)

_TOP_LEVEL_KEYS = frozenset(
    {
        "format_version",
        "release_sequence",
        "published_at",
        "min_client_version",
        "max_client_version",
        "notes",
        "key_id",
        "payload_bytes",
        "payload_sha256",
        "payload",
        "signature",
    }
)
_BUNDLE_KEYS = frozenset(
    {"task_type", "contract_version", "default_revision", "guidance"}
)
# Stable X.Y.Z and the application's preview X.Y.Z-listening-test.N identity
# are both accepted.  Range compatibility compares the X.Y.Z base triple;
# preview sequence does not make the same code-base build incompatible.
_VERSION_RE = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-listening-test\.(0|[1-9][0-9]*))?"
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")

# Fail at import if the explicit allowlist drifts from the local manifest.
if not set(PACKAGE_TASK_TYPES).issubset(set(GUIDANCE_FIELDS)):
    raise RuntimeError("prompt package allowlist contains an unregistered task")
if len(PACKAGE_TASK_TYPES) != len(set(PACKAGE_TASK_TYPES)):
    raise RuntimeError("prompt package allowlist contains duplicate tasks")


class PromptPackageError(ValueError):
    """A package or trust configuration was refused with a stable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PackageTrust:
    """Fixed trust material supplied by the application build."""

    source_url: str | None
    keys: Mapping[str, bytes]
    client_version: str = PACKAGED_CLIENT_VERSION

    @property
    def configured(self) -> bool:
        return bool(self.source_url and self.keys)

    @property
    def key_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.keys))


def packaged_trust() -> PackageTrust:
    """Return the build's fixed trust configuration (unconfigured in source)."""
    keys: dict[str, bytes] = {}
    if PACKAGED_KEY_ID and PACKAGED_PUBLIC_KEY_B64:
        try:
            keys[PACKAGED_KEY_ID] = _decode_key(PACKAGED_PUBLIC_KEY_B64)
        except PromptPackageError:
            # A broken release-time configuration must fail closed, not fall
            # back to an arbitrary key.  Keeping the key map empty reports the
            # package source as unconfigured.
            keys = {}
    source = PACKAGED_SOURCE_URL.strip() or None
    if source is not None and len(source) > MAX_SOURCE_URL_CHARS:
        source = None
    return PackageTrust(
        source_url=source,
        keys=keys,
        client_version=PACKAGED_CLIENT_VERSION,
    )


def _decode_key(value: str) -> bytes:
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise PromptPackageError(
            "PACKAGE_TRUST_INVALID", "提示词包公钥配置无效"
        ) from exc
    if len(raw) != 32:
        raise PromptPackageError("PACKAGE_TRUST_INVALID", "提示词包公钥长度无效")
    return raw


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate key")
        obj[key] = value
    return obj


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite number")


def _reject_surrogates(value: Any) -> None:
    """Reject lone UTF-16 surrogate code points before canonical encoding."""
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise PromptPackageError(
                "PACKAGE_ENCODING", "提示词包包含孤立 Unicode 代理项"
            )
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_surrogates(key)
            _reject_surrogates(item)
        return
    if isinstance(value, list):
        for item in value:
            _reject_surrogates(item)


def strict_json_object(text: str | bytes) -> dict[str, Any]:
    """Parse exactly one UTF-8 JSON object; duplicate keys and NaN refused."""
    if isinstance(text, bytes):
        raw_bytes = text
    elif isinstance(text, str):
        try:
            raw_bytes = text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise PromptPackageError(
                "PACKAGE_ENCODING", "提示词包不是 UTF-8"
            ) from exc
    else:
        raise PromptPackageError("PACKAGE_ENCODING", "提示词包内容类型无效")
    if len(raw_bytes) > MAX_PACKAGE_BYTES:
        raise PromptPackageError("PACKAGE_TOO_LARGE", "提示词包超过大小上限")
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PromptPackageError("PACKAGE_ENCODING", "提示词包不是 UTF-8") from exc
    try:
        obj = json.loads(
            text,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except (ValueError, RecursionError) as exc:
        raise PromptPackageError("PACKAGE_JSON_INVALID", "提示词包 JSON 无效") from exc
    if not isinstance(obj, dict):
        raise PromptPackageError("PACKAGE_JSON_INVALID", "提示词包必须是 JSON 对象")
    _reject_surrogates(obj)
    return obj


def _require_exact_keys(
    value: Any, keys: frozenset[str], code: str, message: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise PromptPackageError(code, message)
    return value


def _strict_int(value: Any, code: str, message: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PromptPackageError(code, message)
    return value


def _strict_str(
    value: Any, code: str, message: str, *, maximum: int
) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise PromptPackageError(code, message)
    return value


def _sha256_hex(value: Any, code: str, message: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise PromptPackageError(code, message)
    return value


def _semver(value: Any, code: str, message: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or len(value) > MAX_VERSION_CHARS:
        raise PromptPackageError(code, message)
    match = _VERSION_RE.fullmatch(value)
    if match is None:
        raise PromptPackageError(code, message)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _published_at(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 64:
        raise PromptPackageError("PACKAGE_MANIFEST_INVALID", "发布时间格式无效")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PromptPackageError(
            "PACKAGE_MANIFEST_INVALID", "发布时间格式无效"
        ) from exc
    if parsed.tzinfo is None:
        raise PromptPackageError("PACKAGE_MANIFEST_INVALID", "发布时间必须带时区")
    return value


def _decode_signature(value: Any) -> bytes:
    if not isinstance(value, str) or len(value) > 256:
        raise PromptPackageError("PACKAGE_SIGNATURE_INVALID", "签名格式无效")
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise PromptPackageError("PACKAGE_SIGNATURE_INVALID", "签名格式无效") from exc
    if len(raw) != 64:
        raise PromptPackageError("PACKAGE_SIGNATURE_INVALID", "签名长度无效")
    return raw


@dataclass(frozen=True)
class PackageBundle:
    task_type: str
    contract_version: int
    default_revision: int
    guidance: Mapping[str, str]

    def identity(self) -> tuple[str, int, int]:
        return (self.task_type, self.contract_version, self.default_revision)

    def guidance_hash(self) -> str:
        return hashlib.sha256(
            canonical_json(dict(self.guidance)).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class VerifiedPackage:
    document: Mapping[str, Any]
    payload: Mapping[str, Any]
    bundles: tuple[PackageBundle, ...]
    release_sequence: int
    published_at: str
    min_client_version: str
    max_client_version: str
    notes: str
    key_id: str
    content_sha256: str
    raw_sha256: str

    def bundle_map(self) -> dict[tuple[str, int, int], PackageBundle]:
        return {bundle.identity(): bundle for bundle in self.bundles}


def _manifest_contract_map() -> dict[str, int]:
    result: dict[str, int] = {}
    for bundle in PROMPT_BUNDLE_MANIFEST:
        task = str(bundle["task_type"])
        contract = int(bundle["contract_version"])
        if contract > result.get(task, 0):
            result[task] = contract
    return result


def _manifest_bundle(task_type: str, contract_version: int) -> dict[str, Any]:
    matches = [
        bundle
        for bundle in PROMPT_BUNDLE_MANIFEST
        if bundle["task_type"] == task_type
        and int(bundle["contract_version"]) == contract_version
    ]
    if not matches:
        raise PromptPackageError(
            "PACKAGE_CONTRACT_INCOMPATIBLE",
            "提示词包引用了本程序未登记的契约",
        )
    shapes = {
        (
            canonical_json(bundle["input_schema_json"]),
            canonical_json(bundle["output_schema_json"]),
            tuple(sorted(bundle["guidance_defaults_json"].keys())),
        )
        for bundle in matches
    }
    if len(shapes) != 1:
        raise PromptPackageError(
            "PACKAGE_CONTRACT_INCOMPATIBLE",
            "本地提示词契约结构不一致",
        )
    return matches[0]


def _builtin_latest(task_type: str, contract_version: int) -> tuple[int, dict[str, str]]:
    matches = [
        bundle
        for bundle in PROMPT_BUNDLE_MANIFEST
        if bundle["task_type"] == task_type
        and int(bundle["contract_version"]) == contract_version
    ]
    if not matches:
        raise PromptPackageError(
            "PACKAGE_CONTRACT_INCOMPATIBLE", "提示词包契约未登记"
        )
    latest = max(matches, key=lambda item: int(item["default_revision"]))
    return int(latest["default_revision"]), dict(latest["guidance_defaults_json"])


def _validate_payload(payload: Any) -> tuple[PackageBundle, ...]:
    payload = _require_exact_keys(
        payload,
        frozenset({"schema_version", "bundles"}),
        "PACKAGE_PAYLOAD_INVALID",
        "提示词包负载字段无效",
    )
    schema_version = _strict_int(
        payload["schema_version"], "PACKAGE_PAYLOAD_INVALID", "负载版本无效"
    )
    if schema_version != PAYLOAD_SCHEMA_VERSION:
        raise PromptPackageError("PACKAGE_INCOMPATIBLE", "提示词包负载版本不兼容")
    raw_bundles = payload["bundles"]
    if not isinstance(raw_bundles, list):
        raise PromptPackageError("PACKAGE_PAYLOAD_INVALID", "提示词包条目无效")

    contracts = _manifest_contract_map()
    seen: dict[str, PackageBundle] = {}
    for raw in raw_bundles:
        raw = _require_exact_keys(
            raw,
            _BUNDLE_KEYS,
            "PACKAGE_PAYLOAD_INVALID",
            "提示词包条目字段无效",
        )
        task_type = raw["task_type"]
        if not isinstance(task_type, str) or task_type not in PACKAGE_TASK_TYPES:
            raise PromptPackageError(
                "PACKAGE_TASK_NOT_ALLOWED", "提示词包包含未开放的任务类型"
            )
        if task_type in seen:
            raise PromptPackageError(
                "PACKAGE_IDENTITY_DUPLICATE", "提示词包任务条目重复"
            )
        contract = _strict_int(
            raw["contract_version"],
            "PACKAGE_PAYLOAD_INVALID",
            "提示词包契约版本无效",
        )
        if contract != contracts.get(task_type):
            raise PromptPackageError(
                "PACKAGE_CONTRACT_INCOMPATIBLE",
                "提示词包契约版本与当前程序不兼容",
            )
        default = _strict_int(
            raw["default_revision"],
            "PACKAGE_PAYLOAD_INVALID",
            "提示词包默认修订无效",
        )
        if default < 1:
            raise PromptPackageError("PACKAGE_PAYLOAD_INVALID", "提示词包默认修订无效")
        guidance = raw["guidance"]
        if not isinstance(guidance, dict):
            raise PromptPackageError("PACKAGE_GUIDANCE_INVALID", "默认指导必须是对象")
        source = _manifest_bundle(task_type, contract)
        local_guidance = dict(source["guidance_defaults_json"])
        allowed_fields = set(GUIDANCE_FIELDS[task_type])
        open_fields = set(PACKAGE_OPEN_GUIDANCE_FIELDS[task_type])
        if not open_fields.issubset(guidance):
            raise PromptPackageError(
                "PACKAGE_GUIDANCE_FIELDS", "默认指导缺少已开放文字字段"
            )
        if not set(guidance).issubset(allowed_fields):
            raise PromptPackageError(
                "PACKAGE_GUIDANCE_FIELDS", "默认指导包含程序未开放字段"
            )
        cleaned = dict(local_guidance)
        for key, value in guidance.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise PromptPackageError("PACKAGE_GUIDANCE_INVALID", "默认指导文字无效")
            if len(value) > GUIDANCE_MAX_CHARS:
                raise PromptPackageError(
                    "PACKAGE_GUIDANCE_TOO_LONG", "默认指导文字超过长度上限"
                )
            if key in open_fields:
                cleaned[key] = value
            elif value != local_guidance.get(key):
                raise PromptPackageError(
                    "PACKAGE_STRUCTURE_IMMUTABLE",
                    "提示词包不得改动程序结构或元数据字段",
                )
        if set(cleaned) != allowed_fields:
            raise PromptPackageError(
                "PACKAGE_GUIDANCE_FIELDS", "默认指导字段集与程序契约不一致"
            )

        builtin_revision, builtin_guidance = _builtin_latest(task_type, contract)
        if open_fields:
            if default < builtin_revision:
                raise PromptPackageError(
                    "PACKAGE_DEFAULT_ROLLBACK",
                    "提示词包默认修订低于程序内置修订",
                )
            if default == builtin_revision and cleaned != builtin_guidance:
                raise PromptPackageError(
                    "PACKAGE_IDENTITY_CONFLICT", "相同默认修订必须对应相同内容"
                )
            effective_revision = default
        else:
            # No remotely editable text: the task is a fixed identity
            # placeholder only.  Any declared revision is normalized to the
            # program's built-in revision; the package cannot advance it.
            effective_revision = builtin_revision
        seen[task_type] = PackageBundle(
            task_type=task_type,
            contract_version=contract,
            default_revision=effective_revision,
            guidance=cleaned,
        )

    missing = set(PACKAGE_TASK_TYPES) - set(seen)
    if missing:
        raise PromptPackageError(
            "PACKAGE_INCOMPLETE", "提示词包不是完整的默认指导快照"
        )
    return tuple(seen[task] for task in PACKAGE_TASK_TYPES)


def verify_package(
    raw: bytes | str,
    trust: PackageTrust,
    *,
    client_version: str | None = None,
) -> VerifiedPackage:
    """Verify one signed package without any I/O or database access."""
    if not trust.configured:
        raise PromptPackageError(
            "PACKAGE_SOURCE_UNCONFIGURED", "提示词包来源未配置"
        )
    if isinstance(raw, bytes) and len(raw) > MAX_PACKAGE_BYTES:
        raise PromptPackageError("PACKAGE_TOO_LARGE", "提示词包超过大小上限")
    try:
        raw_bytes = raw.encode("utf-8") if isinstance(raw, str) else raw
    except UnicodeEncodeError as exc:
        raise PromptPackageError("PACKAGE_ENCODING", "提示词包不是 UTF-8") from exc
    document = strict_json_object(raw)
    document = _require_exact_keys(
        document,
        _TOP_LEVEL_KEYS,
        "PACKAGE_MANIFEST_INVALID",
        "提示词包清单字段无效",
    )

    format_version = _strict_int(
        document["format_version"],
        "PACKAGE_MANIFEST_INVALID",
        "提示词包格式版本无效",
    )
    if format_version != FORMAT_VERSION:
        raise PromptPackageError("PACKAGE_INCOMPATIBLE", "提示词包格式版本不兼容")
    release_sequence = _strict_int(
        document["release_sequence"],
        "PACKAGE_MANIFEST_INVALID",
        "发布序号无效",
    )
    if release_sequence < 1:
        raise PromptPackageError("PACKAGE_MANIFEST_INVALID", "发布序号无效")
    published_at = _published_at(document["published_at"])
    min_client = _strict_str(
        document["min_client_version"],
        "PACKAGE_MANIFEST_INVALID",
        "兼容客户端版本无效",
        maximum=MAX_VERSION_CHARS,
    )
    max_client = _strict_str(
        document["max_client_version"],
        "PACKAGE_MANIFEST_INVALID",
        "兼容客户端版本无效",
        maximum=MAX_VERSION_CHARS,
    )
    min_key = _semver(min_client, "PACKAGE_MANIFEST_INVALID", "兼容客户端版本无效")
    max_key = _semver(max_client, "PACKAGE_MANIFEST_INVALID", "兼容客户端版本无效")
    if min_key > max_key:
        raise PromptPackageError("PACKAGE_MANIFEST_INVALID", "兼容客户端版本范围无效")
    current = _semver(
        client_version or trust.client_version,
        "PACKAGE_MANIFEST_INVALID",
        "当前客户端版本无效",
    )
    if current < min_key or current > max_key:
        raise PromptPackageError(
            "PACKAGE_INCOMPATIBLE", "提示词包与当前客户端版本不兼容"
        )
    notes = _strict_str(
        document["notes"],
        "PACKAGE_MANIFEST_INVALID",
        "变更说明无效",
        maximum=MAX_NOTES_CHARS,
    )
    key_id = _strict_str(
        document["key_id"],
        "PACKAGE_SIGNATURE_INVALID",
        "签名密钥编号无效",
        maximum=MAX_KEY_ID_CHARS,
    )
    payload_bytes = _strict_int(
        document["payload_bytes"],
        "PACKAGE_PAYLOAD_INVALID",
        "负载长度无效",
    )
    if payload_bytes < 2 or payload_bytes > MAX_PACKAGE_BYTES:
        raise PromptPackageError("PACKAGE_PAYLOAD_INVALID", "负载长度无效")
    payload_sha = _sha256_hex(
        document["payload_sha256"],
        "PACKAGE_PAYLOAD_INVALID",
        "负载摘要无效",
    )
    payload = document["payload"]
    payload_canonical = canonical_json(payload).encode("utf-8")
    if len(payload_canonical) != payload_bytes:
        raise PromptPackageError("PACKAGE_PAYLOAD_INVALID", "负载长度不一致")
    if hashlib.sha256(payload_canonical).hexdigest() != payload_sha:
        raise PromptPackageError("PACKAGE_PAYLOAD_INVALID", "负载摘要不一致")
    bundles = _validate_payload(payload)

    if key_id not in trust.keys:
        raise PromptPackageError("PACKAGE_KEY_UNKNOWN", "提示词包签名密钥不受信任")
    signature = _decode_signature(document["signature"])
    signed = dict(document)
    del signed["signature"]
    signed_bytes = canonical_json(signed).encode("utf-8")
    try:
        Ed25519PublicKey.from_public_bytes(trust.keys[key_id]).verify(
            signature, signed_bytes
        )
    except (InvalidSignature, ValueError) as exc:
        raise PromptPackageError(
            "PACKAGE_SIGNATURE_INVALID", "提示词包签名校验失败"
        ) from exc

    content_sha = hashlib.sha256(signed_bytes).hexdigest()
    raw_sha = hashlib.sha256(raw_bytes).hexdigest()
    return VerifiedPackage(
        document=dict(document),
        payload=dict(payload),
        bundles=bundles,
        release_sequence=release_sequence,
        published_at=published_at,
        min_client_version=min_client,
        max_client_version=max_client,
        notes=notes,
        key_id=key_id,
        content_sha256=content_sha,
        raw_sha256=raw_sha,
    )


def validate_against_existing_heads(
    package: VerifiedPackage,
    heads: Iterable[tuple[str, int, int]],
) -> None:
    """Refuse a package that would rewind a locally newer default.

    ``heads`` is an iterable of ``(task_type, required_contract, latest_default)``.
    This check is done against the restored/current database before the
    accepted ledger advances, so a stale package cannot claim a higher release
    sequence while leaving newer local revisions in place.
    """
    bundles = {bundle.task_type: bundle for bundle in package.bundles}
    for task_type, required_contract, latest_default in heads:
        bundle = bundles.get(task_type)
        if bundle is None:
            continue
        if (
            not isinstance(required_contract, int)
            or isinstance(required_contract, bool)
            or not isinstance(latest_default, int)
            or isinstance(latest_default, bool)
        ):
            raise PromptPackageError(
                "PACKAGE_STORAGE_INVALID", "本地提示词头数据无效"
            )
        if required_contract > bundle.contract_version:
            raise PromptPackageError(
                "PACKAGE_CONTRACT_INCOMPATIBLE",
                "本地提示词契约高于提示词包，不做降级",
            )
        if (
            required_contract == bundle.contract_version
            and latest_default > bundle.default_revision
        ):
            raise PromptPackageError(
                "PACKAGE_DEFAULT_ROLLBACK",
                "本地已登记较新的默认修订，拒绝回退提示词包",
            )


def materialize_bundle_rows(package: VerifiedPackage) -> tuple[dict[str, Any], ...]:
    """Copy local schemas and turn verified guidance into bundle rows.

    The package never supplies a schema.  The input/output schema and the
    guidance field set come from the local manifest entry with the same
    ``(task_type, contract_version)``.  This is the enforcement point that keeps
    weekly structural metadata, input fields, images, models, budgets, secrets,
    URLs and permissions program-owned.
    """
    rows: list[dict[str, Any]] = []
    for bundle in package.bundles:
        source = _manifest_bundle(bundle.task_type, bundle.contract_version)
        guidance = dict(bundle.guidance)
        rows.append(
            {
                "task_type": bundle.task_type,
                "contract_version": bundle.contract_version,
                "default_revision": bundle.default_revision,
                "input_schema_json": source["input_schema_json"],
                "output_schema_json": source["output_schema_json"],
                "guidance_defaults_json": guidance,
                "bundle_hash": bundle_hash(
                    source["input_schema_json"],
                    source["output_schema_json"],
                    guidance,
                ),
            }
        )
    return tuple(rows)


__all__ = [
    "FORMAT_VERSION",
    "PAYLOAD_SCHEMA_VERSION",
    "MAX_PACKAGE_BYTES",
    "PACKAGE_OPEN_GUIDANCE_FIELDS",
    "PACKAGE_OPEN_TASK_TYPES",
    "PACKAGE_TASK_TYPES",
    "PACKAGED_CLIENT_VERSION",
    "PackageBundle",
    "PackageTrust",
    "PromptPackageError",
    "VerifiedPackage",
    "materialize_bundle_rows",
    "packaged_trust",
    "strict_json_object",
    "validate_against_existing_heads",
    "verify_package",
]
