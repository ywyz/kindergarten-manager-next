"""One-to-one listening export preview, frozen generation and host content.

This slice deliberately has no new database table or migration.  A preview and
its generated DOCX live only in this app-launch's manager memory, bound to the
launch id, profile/class/term, selected record revisions and template hashes.
They expire and are discarded on process/launch replacement.

The saved record is the only content authority.  The preview reads it once,
freezes the exact fields/groups/image bytes and lists every missing fact; the
generator is a pure function over that frozen payload plus verified template
bytes.  A final binding re-check refuses a stale preview.
"""

from __future__ import annotations

import hashlib
import io
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.local import (
    backup_barrier,
    listening_assets,
    listening_service,
    listening_templates,
)
from app.local.base import utc_now
from app.local.errors import LocalError, LocalValidationError
from app.local.models import LocalListeningAsset, LocalListeningRecord
from app.local.normalize import normalize_request_id
from app.services.word_export_listening import (
    ListeningWordError,
    ListeningWordGroup,
    ListeningWordPhoto,
    ListeningWordUnit,
    generate_listening_docx,
)

PREVIEW_TTL_SECONDS = 15 * 60
EXPORT_TTL_SECONDS = 30 * 60
MAX_PREVIEWS = 32
MAX_EXPORTS = 32
MAX_REQUESTS = 128
MAX_EXPORT_UNITS = 200
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_UNIT_IMAGE_BYTES = 3 * MAX_IMAGE_BYTES
MAX_EXPORT_IMAGE_BYTES = 384 * 1024 * 1024
MAX_EXPORT_TEXT_BYTES = 32 * 1024 * 1024
MAX_EXPORT_DOCX_BYTES = 256 * 1024 * 1024
MAX_RESIDENT_PREVIEW_BYTES = 384 * 1024 * 1024
MAX_RESIDENT_EXPORT_BYTES = 384 * 1024 * 1024
PERSONAL_DOMAIN_ORDER = ("language", "science", "health", "social", "art")
_FILENAME_FORBIDDEN = set('<>:"/\\|?*')
_CONTROL = {chr(index) for index in range(32)}
_FILENAME_MAX = 160
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
    "CONIN$",
    "CONOUT$",
}


def _reserved_filename(name: str) -> bool:
    stem = name[:-5] if name.lower().endswith(".docx") else name
    return stem.split(".", 1)[0].strip().upper() in _WINDOWS_RESERVED


def _safe_filename(value: str) -> str:
    name = (value or "").strip()
    if not name or len(name) > _FILENAME_MAX or "\x00" in name:
        raise ListeningExportSelectionInvalid("导出文件名不合法")
    if any(char in _FILENAME_FORBIDDEN or char in _CONTROL for char in name):
        raise ListeningExportSelectionInvalid("导出文件名不合法")
    if name.startswith(".") or name.endswith(" ") or name.endswith("."):
        raise ListeningExportSelectionInvalid("导出文件名不合法")
    if not name.lower().endswith(".docx"):
        name += ".docx"
    if len(name) > _FILENAME_MAX or name.lower() == ".docx":
        raise ListeningExportSelectionInvalid("导出文件名不合法")
    if _reserved_filename(name):
        raise ListeningExportSelectionInvalid("导出文件名不合法")
    return name


def _filename_fragment(value: str | None) -> str:
    """Clean only a generated default fragment; never change the record name."""
    text = "".join(
        "_" if char in _FILENAME_FORBIDDEN or char in _CONTROL else char
        for char in str(value or "")
    )
    text = " ".join(text.split()).strip(" .")
    if not text or _reserved_filename(text):
        return "幼儿"
    return text


def _default_filename(units: tuple[_Unit, ...], mode: str) -> str:
    if mode == "record":
        fragment = _filename_fragment(
            units[0].child_name if units else "幼儿"
        )
        suffix = "·五领域·一对一倾听记录"
    else:
        domain = units[0].domain if units else "领域"
        label = listening_templates.DOMAIN_LABELS.get(domain, domain)
        fragment = _filename_fragment(label)
        suffix = f"领域·{len(units)}名幼儿·一对一倾听记录"
    limit = _FILENAME_MAX - len(suffix) - len(".docx")
    fragment = fragment[: max(1, limit)].rstrip(" .") or "幼儿"[: max(1, limit)]
    return _safe_filename(f"{fragment}{suffix}.docx")


class ListeningExportError(LocalError):
    code = "LISTENING_EXPORT_INVALID"
    status_code = 409
    message = "倾听导出请求不合法"


class ListeningExportNotFound(ListeningExportError):
    code = "LISTENING_EXPORT_NOT_FOUND"
    status_code = 404
    message = "未找到倾听导出预览或文件"


class ListeningExportStale(ListeningExportError):
    code = "LISTENING_EXPORT_STALE"
    status_code = 409
    message = "倾听记录在预览后已变化，请重新预览"


class ListeningExportAckRequired(ListeningExportError):
    code = "LISTENING_EXPORT_ACK_REQUIRED"
    status_code = 409
    message = "存在缺项，请先确认再生成"


class ListeningExportRequestConflict(ListeningExportError):
    code = "LISTENING_EXPORT_REQUEST_CONFLICT"
    status_code = 409
    message = "同一请求已用于不同导出预览或文件名"


class ListeningExportSelectionInvalid(ListeningExportError):
    code = "LISTENING_EXPORT_SELECTION_INVALID"
    status_code = 422
    message = "倾听导出选集不合法"


class ListeningExportTemplateInvalid(ListeningExportError):
    code = "LISTENING_EXPORT_TEMPLATE_INVALID"
    status_code = 409
    message = "倾听记录绑定的模板不可用"


class ListeningExportImageInvalid(ListeningExportError):
    code = "LISTENING_EXPORT_IMAGE_INVALID"
    status_code = 409
    message = "已登记图片文件丢失或损坏"


class ListeningExportGenerationFailed(ListeningExportError):
    code = "LISTENING_EXPORT_GENERATION_FAILED"
    status_code = 500
    message = "倾听 Word 生成失败"


class ListeningExportTooLarge(ListeningExportError):
    code = "LISTENING_EXPORT_TOO_LARGE"
    status_code = 413
    message = "倾听导出选集或图片过大"


@dataclass(frozen=True)
class _Unit:
    record_id: str
    child_name: str
    domain: str
    revision: int
    template_version: str
    template_sha256: str
    asset_ids: tuple[str | None, ...]
    word: ListeningWordUnit
    missing: tuple[dict[str, Any], ...]
    resident_bytes: int


@dataclass(frozen=True)
class _Preview:
    preview_id: str
    launch_id: str
    profile_id: str
    class_id: str
    term_id: str
    grade: str
    mode: str
    domain: str | None
    record_ids: tuple[str, ...]
    units: tuple[_Unit, ...]
    created_at: datetime
    expires_at: datetime
    filename: str
    resident_bytes: int


@dataclass(frozen=True)
class _Export:
    export_id: str
    launch_id: str
    preview_id: str
    request_id: str
    filename: str
    ack_missing: bool
    data: bytes
    sha256: str
    created_at: datetime
    expires_at: datetime


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return text or None


def _text_bytes(values: Iterable[Any]) -> int:
    total = 0
    for value in values:
        if value is None:
            continue
        total += len(str(value).encode("utf-8"))
    return total


# Same limits the listening asset import already applies to the source image.
_MAX_WORK_PIXELS = 40_000_000
_MAX_WORK_SIDE = 8192
_ORIENTATION_OPERATIONS = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}


def _prepare_word_photo(
    payload: bytes,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Return frozen Word bytes plus explicit source/work metadata.

    Orientation 1/unknown keeps the original bytes unchanged.  A rotated or
    mirrored source gets a bounded, color-preserving working image whose
    pixels are already upright, so Word never needs to interpret EXIF
    orientation.  The original asset file, database row and backup hash are
    never touched.
    """
    source_mime = str(metadata["mime_type"])
    source_width = int(metadata["width"])
    source_height = int(metadata["height"])
    orientation = metadata.get("orientation")
    orientation = int(orientation) if orientation is not None else None
    source_sha = hashlib.sha256(payload).hexdigest()
    info = {
        "source_sha256": source_sha,
        "source_bytes": len(payload),
        "source_mime_type": source_mime,
        "source_width": source_width,
        "source_height": source_height,
        "orientation": orientation,
    }
    if orientation in (None, 1):
        return {
            **info,
            "data": payload,
            "mime_type": source_mime,
            "width": source_width,
            "height": source_height,
        }
    operation = _ORIENTATION_OPERATIONS.get(orientation)
    if operation is None:
        raise ListeningExportImageInvalid("图片方向登记不合法")
    try:
        with Image.open(io.BytesIO(payload)) as opened:
            opened.load()
            if (
                opened.width <= 0
                or opened.height <= 0
                or opened.width > _MAX_WORK_SIDE
                or opened.height > _MAX_WORK_SIDE
                or opened.width * opened.height > _MAX_WORK_PIXELS
            ):
                raise ListeningExportTooLarge("倾听图片尺寸过大")
            icc_profile = opened.info.get("icc_profile")
            working = opened.transpose(operation)
            working.load()
            work_mime = (
                "image/jpeg" if source_mime == "image/jpeg" else "image/png"
            )
            output = io.BytesIO()
            if work_mime == "image/jpeg":
                if working.mode not in ("RGB", "L"):
                    working = working.convert("RGB")
                for quality in (95, 85):
                    output = io.BytesIO()
                    params: dict[str, Any] = {
                        "format": "JPEG",
                        "quality": quality,
                        "optimize": True,
                    }
                    if icc_profile:
                        params["icc_profile"] = icc_profile
                    working.save(output, **params)
                    if output.tell() <= MAX_IMAGE_BYTES:
                        break
            else:
                if working.mode == "CMYK":
                    working = working.convert("RGB")
                params = {"format": "PNG", "optimize": True}
                if icc_profile:
                    params["icc_profile"] = icc_profile
                working.save(output, **params)
            data = output.getvalue()
            if len(data) > MAX_IMAGE_BYTES:
                raise ListeningExportTooLarge("倾听工作图过大")
            return {
                **info,
                "data": data,
                "mime_type": work_mime,
                "width": int(working.width),
                "height": int(working.height),
            }
    except ListeningExportError:
        raise
    except Exception as exc:  # noqa: BLE001 - corrupt image refusal
        raise ListeningExportImageInvalid("倾听图片无法解码") from exc


def _missing_for_unit(
    record_id: str,
    child_name: str,
    domain: str,
    values: dict[str, str | None],
    groups: tuple[ListeningWordGroup, ...],
    item_ids: tuple[str, ...],
    stars: dict[str, int | None],
) -> tuple[dict[str, Any], ...]:
    missing: list[dict[str, Any]] = []
    for field, label in (
        ("observation_date", "观察日期"),
        ("adult_count", "成人数目"),
        ("child_age", "幼儿年龄"),
        ("goal", "目标"),
        ("observation_area", "观察区域"),
        ("overall_evaluation", "综合评价"),
        ("support_strategy", "支持策略"),
    ):
        if not values.get(field):
            missing.append(
                {
                    "record_id": record_id,
                    "child_name": child_name,
                    "domain": domain,
                    "field": field,
                    "label": label,
                }
            )
    for group in groups:
        if not group.work_date:
            missing.append(
                {
                    "record_id": record_id,
                    "child_name": child_name,
                    "domain": domain,
                    "field": "work_date",
                    "label": "作品日期",
                    "group_id": group.group_id,
                    "position": group.position,
                }
            )
        if not group.listening_text:
            missing.append(
                {
                    "record_id": record_id,
                    "child_name": child_name,
                    "domain": domain,
                    "field": "listening_text",
                    "label": "倾听正文",
                    "group_id": group.group_id,
                    "position": group.position,
                }
            )
        if group.photo is None:
            missing.append(
                {
                    "record_id": record_id,
                    "child_name": child_name,
                    "domain": domain,
                    "field": "photo",
                    "label": "作品照片",
                    "group_id": group.group_id,
                    "position": group.position,
                }
            )
    for item_id in item_ids:
        if stars.get(item_id) is None:
            missing.append(
                {
                    "record_id": record_id,
                    "child_name": child_name,
                    "domain": domain,
                    "field": "evaluation",
                    "label": "评价星级",
                    "item_id": item_id,
                }
            )
    return tuple(missing)


class ListeningExportManager:
    def __init__(self, runtime: Any, *, launch_id: str):
        self.runtime = runtime
        self.launch_id = launch_id
        self._runtime_launch_id = str(
            getattr(runtime, "launch_id", "") or ""
        )
        self._lock = threading.Lock()
        self._generate_lock = threading.Lock()
        self._previews: dict[str, _Preview] = {}
        self._exports: dict[str, _Export] = {}
        self._requests: dict[str, str] = {}
        self._pins: dict[str, set[str]] = {}
        self._retired = False
        self._active_work = 0

    @property
    def has_active_work(self) -> bool:
        with self._lock:
            return self._active_work > 0

    def _activity_enter(self) -> None:
        with self._lock:
            self._active_work += 1

    def _activity_leave(self) -> None:
        with self._lock:
            if self._active_work > 0:
                self._active_work -= 1

    def _launch_valid(self) -> bool:
        return (
            not self._retired
            and bool(self.launch_id)
            and str(getattr(self.runtime, "launch_id", "") or "")
            == self._runtime_launch_id
        )

    def retire(self) -> None:
        with self._lock:
            self._retired = True
            self._previews.clear()
            self._exports.clear()
            self._requests.clear()
            self._pins.clear()

    def reset(self) -> None:
        with self._lock:
            if self._retired:
                return
            self._previews.clear()
            self._exports.clear()
            self._requests.clear()
            self._pins.clear()

    def _prune_previews_locked(self, now: datetime) -> None:
        for key, item in list(self._previews.items()):
            if item.expires_at <= now:
                self._previews.pop(key, None)

    def _prune_exports_locked(self, now: datetime) -> None:
        for key, item in list(self._exports.items()):
            if item.expires_at <= now and key not in self._pins:
                self._exports.pop(key, None)

    def _evict_exports_locked(self, incoming_bytes: int) -> None:
        while self._exports:
            resident = sum(len(item.data) for item in self._exports.values())
            if (
                len(self._exports) < MAX_EXPORTS
                and resident + incoming_bytes <= MAX_RESIDENT_EXPORT_BYTES
            ):
                return
            candidates = [
                (key, item)
                for key, item in self._exports.items()
                if key not in self._pins
            ]
            if not candidates:
                raise ListeningExportTooLarge("倾听导出缓存已满，请稍后再试")
            oldest_key, _oldest = min(
                candidates,
                key=lambda pair: (pair[1].created_at, pair[0]),
            )
            self._exports.pop(oldest_key, None)
        if incoming_bytes > MAX_RESIDENT_EXPORT_BYTES:
            raise ListeningExportTooLarge("倾听导出文件过大")

    def _remember_request_locked(self, request_id: str, export_id: str) -> None:
        self._requests[request_id] = export_id
        while len(self._requests) > MAX_REQUESTS:
            oldest = next(iter(self._requests))
            if oldest == request_id:
                break
            self._requests.pop(oldest, None)

    def pin_export(self, export_id: str, owner: str) -> dict[str, Any]:
        backup_barrier.get_barrier(self.runtime.data_dir).assert_writes_allowed()
        now = utc_now()
        with self._lock:
            if not self._launch_valid():
                raise ListeningExportNotFound()
            export = self._exports.get(export_id)
            if (
                export is None
                or export.launch_id != self.launch_id
                or export.expires_at <= now
            ):
                raise ListeningExportNotFound()
            self._pins.setdefault(export_id, set()).add(str(owner))
            return self._export_payload(export)

    def unpin_export(self, export_id: str, owner: str) -> None:
        with self._lock:
            owners = self._pins.get(export_id)
            if owners is None:
                return
            owners.discard(str(owner))
            if not owners:
                self._pins.pop(export_id, None)

    def _record_term_name(self, context, term_id: str) -> str:
        for term in context.terms:
            if term.id == term_id:
                return term.name
        raise ListeningExportSelectionInvalid("记录学期不属于当前档案")

    def _load_unit(
        self,
        session: Session,
        context,
        profile_id: str,
        record_id: str,
        domain: str,
        tracker: dict[str, int],
    ) -> _Unit:
        try:
            record = session.get(LocalListeningRecord, record_id)
            if record is None or record.profile_id != profile_id:
                raise ListeningExportSelectionInvalid("记录不属于当前档案")
            dto = listening_service.read_record(
                session, profile_id=profile_id, record_id=record_id
            )
        except LocalError as exc:
            if isinstance(exc, ListeningExportError):
                raise
            raise ListeningExportSelectionInvalid("倾听记录读取失败") from exc
        domain_dto = next(
            (item for item in dto["domains"] if item["domain"] == domain),
            None,
        )
        if domain_dto is None:
            raise ListeningExportSelectionInvalid("所选领域不属于该记录")
        try:
            template = listening_templates.get_template(
                record.grade,
                domain,
                domain_dto["template_version"],
            )
            if template.sha256 != domain_dto["template_sha256"]:
                raise listening_templates.ListeningTemplateInvalid(
                    "模板散列与记录不一致"
                )
            template_bytes = listening_templates.read_template_bytes(template)
        except LocalError as exc:
            raise ListeningExportTemplateInvalid(
                "记录绑定的模板缺失或散列不一致"
            ) from exc
        groups: list[ListeningWordGroup] = []
        asset_ids: list[str | None] = []
        image_bytes_before = tracker.get("image_bytes", 0)
        for group in sorted(domain_dto["groups"], key=lambda item: item["position"]):
            if group["position"] not in (0, 1, 2):
                raise ListeningExportStale("图文组位置不合法")
            photo = None
            asset_id = group.get("asset_id")
            asset_ids.append(asset_id)
            if asset_id:
                asset = session.get(LocalListeningAsset, asset_id)
                if asset is None or asset.record_id != record_id:
                    raise ListeningExportImageInvalid(
                        f"图片丢失或损坏：{record_id}/{domain}/{group['group_id']}"
                    )
                if (
                    asset.byte_size < 0
                    or asset.byte_size > MAX_IMAGE_BYTES
                    or asset.width <= 0
                    or asset.height <= 0
                ):
                    raise ListeningExportTooLarge(
                        f"图片过大或尺寸无效：{record_id}/{domain}/{group['group_id']}"
                    )
                projected = tracker.get("image_bytes", 0) + asset.byte_size
                if projected > MAX_EXPORT_IMAGE_BYTES:
                    raise ListeningExportTooLarge("倾听导出图片总量过大")
                try:
                    payload, metadata = listening_assets.read_asset(
                        session,
                        self.runtime,
                        profile_id=profile_id,
                        record_id=record_id,
                        asset_id=asset_id,
                    )
                except LocalError as exc:
                    raise ListeningExportImageInvalid(
                        f"图片丢失或损坏：{record_id}/{domain}/{group['group_id']}"
                    ) from exc
                if len(payload) != asset.byte_size:
                    raise ListeningExportImageInvalid(
                        f"图片丢失或损坏：{record_id}/{domain}/{group['group_id']}"
                    )
                prepared = _prepare_word_photo(payload, metadata)
                work_bytes = prepared["data"]
                if len(work_bytes) > MAX_IMAGE_BYTES:
                    raise ListeningExportTooLarge(
                        f"图片过大：{record_id}/{domain}/{group['group_id']}"
                    )
                projected_work = (
                    tracker.get("image_bytes", 0) + len(work_bytes)
                )
                if projected_work > MAX_EXPORT_IMAGE_BYTES:
                    raise ListeningExportTooLarge("倾听导出图片总量过大")
                tracker["image_bytes"] = projected_work
                photo = ListeningWordPhoto(
                    asset_id=asset_id,
                    data=work_bytes,
                    mime_type=prepared["mime_type"],
                    width=int(prepared["width"]),
                    height=int(prepared["height"]),
                    source_sha256=prepared["source_sha256"],
                    source_byte_size=prepared["source_bytes"],
                    source_mime_type=prepared["source_mime_type"],
                    source_width=prepared["source_width"],
                    source_height=prepared["source_height"],
                    orientation=prepared["orientation"],
                )
            groups.append(
                ListeningWordGroup(
                    group_id=group["group_id"],
                    position=int(group["position"]),
                    work_date=_clean_text(group.get("work_date")),
                    listening_text=_clean_text(group.get("listening_text")),
                    photo=photo,
                )
            )
        if len(groups) != 3:
            raise ListeningExportStale("图文组数量不是三组")
        stars = {
            item["item_id"]: item.get("stars")
            for item in domain_dto["evaluation"]
        }
        item_ids = tuple(item.item_id for item in template.items)
        values = {
            "observation_date": _clean_text(domain_dto.get("observation_date")),
            "adult_count": _clean_text(domain_dto.get("adult_count")),
            "child_age": _clean_text(domain_dto.get("child_age")),
            "goal": _clean_text(domain_dto.get("goal")),
            "observation_area": _clean_text(domain_dto.get("observation_area")),
            "overall_evaluation": _clean_text(
                domain_dto.get("overall_evaluation")
            ),
            "support_strategy": _clean_text(domain_dto.get("support_strategy")),
        }
        word = ListeningWordUnit(
            record_id=record_id,
            child_name=dto["child_name"],
            domain=domain,
            domain_label=listening_templates.DOMAIN_LABELS[domain],
            grade=record.grade,
            term_name=self._record_term_name(context, record.term_id),
            class_name=context.school_class.name,
            revision=dto["revision"],
            observation_date=values["observation_date"],
            adult_count=values["adult_count"],
            child_age=values["child_age"],
            goal=values["goal"],
            observation_area=values["observation_area"],
            overall_evaluation=values["overall_evaluation"],
            support_strategy=values["support_strategy"],
            groups=tuple(groups),
            item_ids=item_ids,
            stars=stars,
            template_version=template.version,
            template_sha256=template.sha256,
            template_bytes=template_bytes,
        )
        text_bytes = len(template_bytes) + _text_bytes(
            [dto["child_name"], *values.values()]
        )
        for group in groups:
            text_bytes += _text_bytes([group.work_date, group.listening_text])
        tracker["text_bytes"] = tracker.get("text_bytes", 0) + text_bytes
        if tracker["text_bytes"] > MAX_EXPORT_TEXT_BYTES:
            raise ListeningExportTooLarge("倾听导出文本总量过大")
        unit_image_bytes = tracker.get("image_bytes", 0) - image_bytes_before
        if unit_image_bytes > MAX_UNIT_IMAGE_BYTES:
            raise ListeningExportTooLarge("单个倾听导出图片总量过大")
        return _Unit(
            record_id=record_id,
            child_name=dto["child_name"],
            domain=domain,
            revision=dto["revision"],
            template_version=template.version,
            template_sha256=template.sha256,
            asset_ids=tuple(asset_ids),
            word=word,
            missing=_missing_for_unit(
                record_id,
                dto["child_name"],
                domain,
                values,
                tuple(groups),
                item_ids,
                stars,
            ),
            resident_bytes=unit_image_bytes + text_bytes,
        )

    def preview(
        self,
        session: Session,
        *,
        profile_id: str,
        context,
        mode: str,
        record_id: str | None = None,
        domain: str | None = None,
        record_ids: list[str] | None = None,
        term_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self._activity_enter()
        try:
            with backup_barrier.file_scope(self.runtime.data_dir):
                return self._preview_impl(
                    session,
                    profile_id=profile_id,
                    context=context,
                    mode=mode,
                    record_id=record_id,
                    domain=domain,
                    record_ids=record_ids,
                    term_id=term_id,
                    now=now,
                )
        finally:
            self._activity_leave()

    def _preview_impl(
        self,
        session: Session,
        *,
        profile_id: str,
        context,
        mode: str,
        record_id: str | None = None,
        domain: str | None = None,
        record_ids: list[str] | None = None,
        term_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not self._launch_valid():
            raise ListeningExportNotFound()
        if context.profile is None or context.profile.id != profile_id:
            raise ListeningExportSelectionInvalid("当前档案不可用")
        if context.school_class is None:
            raise ListeningExportSelectionInvalid("当前班级不可用")
        if mode not in ("record", "domain"):
            raise ListeningExportSelectionInvalid("导出方式不合法")
        if term_id is not None and not isinstance(term_id, str):
            raise ListeningExportSelectionInvalid("学期标识不合法")
        terms_by_id = {term.id: term for term in context.terms}
        requested_term = None
        if term_id is not None:
            if term_id not in terms_by_id:
                raise ListeningExportSelectionInvalid("所选学期不属于当前班级")
            requested_term = term_id
        now = now or utc_now()
        records_by_id: dict[str, LocalListeningRecord] = {}
        if mode == "record":
            if not isinstance(record_id, str) or not record_id:
                raise ListeningExportSelectionInvalid("缺少倾听记录标识")
            if domain is not None:
                raise ListeningExportSelectionInvalid("按幼儿合册不得指定单一领域")
            record = session.get(LocalListeningRecord, record_id)
            if (
                record is None
                or record.profile_id != profile_id
                or record.class_id != context.school_class.id
                or record.term_id not in terms_by_id
            ):
                raise ListeningExportSelectionInvalid("记录归属不合法")
            if requested_term is not None and requested_term != record.term_id:
                raise ListeningExportSelectionInvalid("所选学期与记录不一致")
            records_by_id[record_id] = record
            selected = (record_id,)
            selected_term = record.term_id
            domains = PERSONAL_DOMAIN_ORDER
        else:
            if domain not in listening_templates.DOMAINS:
                raise ListeningExportSelectionInvalid("导出领域不合法")
            if record_ids is None:
                if requested_term is None:
                    raise ListeningExportSelectionInvalid("请选择导出学期")
                selected_term = requested_term
                rows = session.scalars(
                    select(LocalListeningRecord)
                    .where(
                        LocalListeningRecord.profile_id == profile_id,
                        LocalListeningRecord.class_id == context.school_class.id,
                        LocalListeningRecord.term_id == selected_term,
                    )
                    .order_by(
                        LocalListeningRecord.created_at,
                        LocalListeningRecord.id,
                    )
                ).all()
                selected = tuple(row.id for row in rows)
            else:
                if (
                    not isinstance(record_ids, list)
                    or not record_ids
                    or any(not isinstance(item, str) or not item for item in record_ids)
                    or len(set(record_ids)) != len(record_ids)
                ):
                    raise ListeningExportSelectionInvalid("导出选集不合法")
                selected = tuple(record_ids)
                for selected_id in selected:
                    record = session.get(LocalListeningRecord, selected_id)
                    if (
                        record is None
                        or record.profile_id != profile_id
                        or record.class_id != context.school_class.id
                        or record.term_id not in terms_by_id
                    ):
                        raise ListeningExportSelectionInvalid("记录归属不合法")
                    records_by_id[selected_id] = record
                selected_terms = {record.term_id for record in records_by_id.values()}
                if len(selected_terms) != 1:
                    raise ListeningExportSelectionInvalid(
                        "领域合册记录必须属于同一学期"
                    )
                selected_term = selected_terms.pop()
                if requested_term is not None and requested_term != selected_term:
                    raise ListeningExportSelectionInvalid("所选学期与记录不一致")
            if not selected:
                raise ListeningExportSelectionInvalid("未选择任何记录")
            domains = (domain,)
        units: list[_Unit] = []
        if len(selected) * len(domains) > MAX_EXPORT_UNITS:
            raise ListeningExportTooLarge("倾听导出记录数量过多")
        tracker: dict[str, int] = {"image_bytes": 0, "text_bytes": 0}
        for selected_id in selected:
            record = records_by_id.get(selected_id)
            if record is None:
                record = session.get(LocalListeningRecord, selected_id)
            if (
                record is None
                or record.profile_id != profile_id
                or record.class_id != context.school_class.id
            ):
                raise ListeningExportSelectionInvalid("记录归属不合法")
            if record.term_id not in terms_by_id or record.term_id != selected_term:
                raise ListeningExportSelectionInvalid("记录学期与所选学期不一致")
            for item_domain in domains:
                units.append(
                    self._load_unit(
                        session,
                        context,
                        profile_id,
                        selected_id,
                        item_domain,
                        tracker,
                    )
                )
        term_id = selected_term
        missing = tuple(
            item for unit in units for item in unit.missing
        )
        resident_bytes = sum(unit.resident_bytes for unit in units)
        if resident_bytes > MAX_RESIDENT_PREVIEW_BYTES:
            raise ListeningExportTooLarge("倾听导出预览占用过大")
        preview_id = secrets.token_urlsafe(24)
        preview = _Preview(
            preview_id=preview_id,
            launch_id=self.launch_id,
            profile_id=profile_id,
            class_id=context.school_class.id,
            term_id=term_id,
            grade=units[0].word.grade,
            mode=mode,
            domain=domain,
            record_ids=selected,
            units=tuple(units),
            created_at=now,
            expires_at=now + timedelta(seconds=PREVIEW_TTL_SECONDS),
            filename=_default_filename(tuple(units), mode),
            resident_bytes=resident_bytes,
        )
        with self._lock:
            self._prune_previews_locked(now)
            while (
                self._previews
                and (
                    len(self._previews) >= MAX_PREVIEWS
                    or sum(
                        item.resident_bytes for item in self._previews.values()
                    )
                    + resident_bytes
                    > MAX_RESIDENT_PREVIEW_BYTES
                )
            ):
                oldest_id = min(
                    self._previews,
                    key=lambda key: (
                        self._previews[key].created_at,
                        self._previews[key].preview_id,
                    ),
                )
                self._previews.pop(oldest_id, None)
            self._previews[preview_id] = preview
        return {
            "preview_id": preview_id,
            "mode": mode,
            "domain": domain,
            "term_id": term_id,
            "class_id": context.school_class.id,
            "grade": preview.grade,
            "expires_at": preview.expires_at.isoformat(),
            "record_ids": list(selected),
            "units": [
                {
                    "record_id": unit.record_id,
                    "child_name": unit.child_name,
                    "domain": unit.domain,
                    "revision": unit.revision,
                    "template_version": unit.template_version,
                    "template_sha256": unit.template_sha256,
                    "photo_count": sum(
                        1 for group in unit.word.groups if group.photo is not None
                    ),
                    "photos": [
                        {
                            "group_id": group.group_id,
                            "position": group.position,
                            "asset_id": group.photo.asset_id,
                            "source_sha256": (
                                group.photo.source_sha256
                                or hashlib.sha256(group.photo.data).hexdigest()
                            ),
                            "source_bytes": (
                                group.photo.source_byte_size
                                if group.photo.source_byte_size is not None
                                else len(group.photo.data)
                            ),
                            "source_mime_type": (
                                group.photo.source_mime_type
                                or group.photo.mime_type
                            ),
                            "source_width": (
                                group.photo.source_width
                                if group.photo.source_width is not None
                                else group.photo.width
                            ),
                            "source_height": (
                                group.photo.source_height
                                if group.photo.source_height is not None
                                else group.photo.height
                            ),
                            "orientation": group.photo.orientation,
                            "work_sha256": hashlib.sha256(
                                group.photo.data
                            ).hexdigest(),
                            "work_bytes": len(group.photo.data),
                            "work_mime_type": group.photo.mime_type,
                            "width": group.photo.width,
                            "height": group.photo.height,
                        }
                        for group in unit.word.groups
                        if group.photo is not None
                    ],
                    "missing_count": len(unit.missing),
                }
                for unit in units
            ],
            "missing": list(missing),
            "missing_count": len(missing),
            "default_filename": preview.filename,
        }

    def _binding_unchanged(self, preview: _Preview) -> bool:
        session = self.runtime.session()
        try:
            for unit in preview.units:
                try:
                    dto = listening_service.read_record(
                        session,
                        profile_id=preview.profile_id,
                        record_id=unit.record_id,
                    )
                except LocalError:
                    return False
                if dto["revision"] != unit.revision:
                    return False
                domain_dto = next(
                    (
                        item
                        for item in dto["domains"]
                        if item["domain"] == unit.domain
                    ),
                    None,
                )
                if (
                    domain_dto is None
                    or domain_dto["template_version"] != unit.template_version
                    or domain_dto["template_sha256"] != unit.template_sha256
                ):
                    return False
                groups = sorted(
                    domain_dto["groups"], key=lambda item: item["position"]
                )
                if tuple(item.get("asset_id") for item in groups) != unit.asset_ids:
                    return False
            return True
        finally:
            session.close()

    def generate(
        self,
        *,
        preview_id: str,
        request_id: Any,
        filename: str | None,
        ack_missing: bool,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self._activity_enter()
        try:
            with backup_barrier.file_scope(self.runtime.data_dir):
                return self._generate_impl(
                    preview_id=preview_id,
                    request_id=request_id,
                    filename=filename,
                    ack_missing=ack_missing,
                    now=now,
                )
        finally:
            self._activity_leave()

    def _generate_impl(
        self,
        *,
        preview_id: str,
        request_id: Any,
        filename: str | None,
        ack_missing: bool,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        rid = normalize_request_id(request_id)
        if not isinstance(ack_missing, bool):
            raise LocalValidationError("ack_missing 必须是布尔值")
        ack = ack_missing
        now = now or utc_now()
        # One generator at a time per manager keeps one request key to one
        # export even under concurrent clicks.  Receipt-first below makes the
        # waiter return the first result instead of generating again.
        with self._generate_lock:
            with self._lock:
                if not self._launch_valid():
                    raise ListeningExportNotFound()
                existing_id = self._requests.get(rid)
                if existing_id is not None:
                    existing = self._exports.get(existing_id)
                    if (
                        existing is None
                        or existing.launch_id != self.launch_id
                        or existing.expires_at <= now
                    ):
                        raise ListeningExportNotFound()
                    replay_name = (
                        _safe_filename(filename)
                        if filename is not None
                        else existing.filename
                    )
                    if (
                        existing.preview_id != preview_id
                        or existing.filename != replay_name
                        or existing.ack_missing != ack
                    ):
                        raise ListeningExportRequestConflict()
                    return self._export_payload(existing)
                preview = self._previews.get(preview_id)
                if (
                    preview is None
                    or preview.launch_id != self.launch_id
                    or preview.expires_at <= now
                ):
                    raise ListeningExportNotFound()
                chosen = _safe_filename(filename or preview.filename)
            if any(unit.missing for unit in preview.units) and not ack:
                raise ListeningExportAckRequired()
            if not self._binding_unchanged(preview):
                raise ListeningExportStale()
            try:
                data = generate_listening_docx(
                    tuple(unit.word for unit in preview.units)
                )
            except ListeningWordError as exc:
                raise ListeningExportGenerationFailed(str(exc)) from exc
            if len(data) > MAX_EXPORT_DOCX_BYTES:
                raise ListeningExportTooLarge("倾听导出 Word 文件过大")
            if not self._binding_unchanged(preview):
                raise ListeningExportStale()
            digest = hashlib.sha256(data).hexdigest()
            export = _Export(
                export_id=secrets.token_urlsafe(24),
                launch_id=self.launch_id,
                preview_id=preview_id,
                request_id=rid,
                filename=chosen,
                ack_missing=ack,
                data=data,
                sha256=digest,
                created_at=now,
                expires_at=now + timedelta(seconds=EXPORT_TTL_SECONDS),
            )
            with self._lock:
                if not self._launch_valid():
                    raise ListeningExportNotFound()
                self._prune_exports_locked(now)
                self._evict_exports_locked(len(data))
                self._exports[export.export_id] = export
                self._remember_request_locked(rid, export.export_id)
                self._previews.pop(preview_id, None)
            return self._export_payload(export)

    @staticmethod
    def _export_payload(export: _Export) -> dict[str, Any]:
        return {
            "status": "ready",
            "export_id": export.export_id,
            "preview_id": export.preview_id,
            "filename": export.filename,
            "bytes": len(export.data),
            "sha256": export.sha256,
            "expires_at": export.expires_at.isoformat(),
        }

    def content(self, export_id: str, *, now: datetime | None = None) -> bytes:
        now = now or utc_now()
        with self._lock:
            if not self._launch_valid():
                raise ListeningExportNotFound()
            export = self._exports.get(export_id)
            if (
                export is None
                or export.launch_id != self.launch_id
                or export.expires_at <= now
            ):
                raise ListeningExportNotFound()
            return bytes(export.data)

    def meta(self, export_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        now = now or utc_now()
        with self._lock:
            if not self._launch_valid():
                raise ListeningExportNotFound()
            export = self._exports.get(export_id)
            if (
                export is None
                or export.launch_id != self.launch_id
                or export.expires_at <= now
            ):
                raise ListeningExportNotFound()
            return self._export_payload(export)

    def request_receipt(self, request_id: str) -> dict[str, Any]:
        rid = normalize_request_id(request_id)
        now = utc_now()
        with self._lock:
            if not self._launch_valid():
                raise ListeningExportNotFound()
            export_id = self._requests.get(rid)
            export = self._exports.get(export_id or "")
            if (
                export is None
                or export.launch_id != self.launch_id
                or export.expires_at <= now
            ):
                raise ListeningExportNotFound()
            return self._export_payload(export)


__all__ = [
    "ListeningExportManager",
    "ListeningExportError",
    "ListeningExportNotFound",
    "ListeningExportStale",
    "ListeningExportAckRequired",
    "ListeningExportRequestConflict",
    "ListeningExportSelectionInvalid",
    "ListeningExportTemplateInvalid",
    "ListeningExportImageInvalid",
    "ListeningExportGenerationFailed",
    "ListeningExportTooLarge",
    "PERSONAL_DOMAIN_ORDER",
]
