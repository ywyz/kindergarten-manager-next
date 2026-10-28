"""Synthetic observation-export capacity probe (bytes/pixels/time/peak RSS).

Runs the real DOCX renderer with representative multi-record and 600-photo
sets, plus the actual aggregate byte-budget refusal.  It does not use the
teacher database, AI, real photos or a frozen package.  Run with the desktop
venv; Codex can execute it against an independent output directory.
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import hashlib
import io
import json
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from PIL import Image, ImageDraw  # noqa: E402

from app.local import observation_export_service  # noqa: E402
from app.services.word_export_observation import (  # noqa: E402
    ObservationWordPhoto,
    ObservationWordRecord,
    generate_observation_export_docx,
)


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def peak_rss_bytes() -> int:
    if sys.platform != "win32":
        return 0
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
        ctypes.c_uint32,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
    if not psapi.GetProcessMemoryInfo(
        kernel32.GetCurrentProcess(),
        ctypes.byref(counters),
        counters.cb,
    ):
        return 0
    return int(counters.PeakWorkingSetSize)


def smooth_jpeg(width: int, height: int, variant: int = 0) -> bytes:
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        draw.line(
            [(0, y), (width, y)],
            fill=(
                (y * 255 // max(1, height - 1) + variant * 7) % 256,
                (80 + variant * 11) % 256,
                (200 - y * 200 // max(1, height - 1) + variant * 13) % 256,
            ),
        )
    stripe = variant % max(1, width)
    draw.rectangle(
        [stripe, 0, min(width - 1, stripe + 2), height - 1],
        fill=((variant * 37) % 256, (variant * 73) % 256, (variant * 109) % 256),
    )
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def noise_jpeg(width: int, height: int) -> bytes:
    image = Image.effect_noise((width, height), 64).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def payload(index: int) -> dict:
    return {
        "record_type": "public",
        "school_name": "合成容量探针幼儿园",
        "class_name": "中一班",
        "observation_date": f"2026-09-{(index % 28) + 1:02d}",
        "start_time": "10:00",
        "end_time": "10:20",
        "adult_count": 2,
        "child_count": 6,
        "observer_name": "王老师",
        "age_years": 5,
        "subjects": [{"name": f"幼儿{index}"}],
        "environment": "积木区",
        "observation_goal": "容量探针观察目标",
        "observation_process": "容量探针正文。" * 20,
        "analysis_evaluation": {
            "health": "健康",
            "language": "语言",
            "social": "社会",
            "science": "科学",
            "arts": "艺术",
        },
        "support_strategy": "容量探针支持策略",
    }


def run_render(
    *,
    records: int,
    photos_per_record: int,
    width: int,
    height: int,
    noise: bool,
) -> dict:
    photos: list[bytes] = []
    for index in range(records * photos_per_record):
        photos.append(
            noise_jpeg(width, height)
            if noise
            else smooth_jpeg(width, height, index)
        )
    total_photo_bytes = sum(len(item) for item in photos)
    total_pixels = records * photos_per_record * width * height
    word_records = []
    cursor = 0
    for record_index in range(records):
        record_photos = []
        for _ in range(photos_per_record):
            data = photos[cursor]
            cursor += 1
            record_photos.append(
                ObservationWordPhoto(
                    data=data,
                    width=width,
                    height=height,
                    content_hash=hashlib.sha256(data).hexdigest(),
                )
            )
        word_records.append(
            ObservationWordRecord(
                payload=payload(record_index), photos=tuple(record_photos)
            )
        )
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    data = generate_observation_export_docx(tuple(word_records))
    elapsed = time.perf_counter() - started
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "records": records,
        "photos": records * photos_per_record,
        "photo_bytes": total_photo_bytes,
        "pixels": total_pixels,
        "docx_bytes": len(data),
        "elapsed_seconds": round(elapsed, 4),
        "tracemalloc_peak_bytes": peak,
        "process_peak_rss_bytes": peak_rss_bytes(),
        "docx_sha256": hashlib.sha256(data).hexdigest(),
        "within_photo_budget": total_photo_bytes
        <= observation_export_service.MAX_EXPORT_TOTAL_PHOTO_BYTES,
        "within_file_budget": len(data)
        <= observation_export_service.MAX_EXPORT_DOCX_BYTES,
    }


def over_budget_probe() -> dict:
    total = 0
    count = 0
    started = time.perf_counter()
    # Generate and discard one image at a time; this measures actual aggregate
    # bytes without holding a huge synthetic set in memory.
    while total <= observation_export_service.MAX_EXPORT_TOTAL_PHOTO_BYTES:
        data = noise_jpeg(2048, 1536)
        total += len(data)
        count += 1
        if count > 100:
            break
    elapsed = time.perf_counter() - started
    error = None
    try:
        observation_export_service.check_export_content_limits(
            {"total_photo_bytes": total, "total_payload_bytes": 0}
        )
    except observation_export_service.ObservationExportContentTooLarge as exc:
        error = {"code": exc.code, "details": exc.details}
    return {
        "photos_generated": count,
        "actual_photo_bytes": total,
        "limit_photo_bytes": observation_export_service.MAX_EXPORT_TOTAL_PHOTO_BYTES,
        "elapsed_seconds": round(elapsed, 4),
        "refused": error is not None,
        "error": error,
        "process_peak_rss_bytes": peak_rss_bytes(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="output directory; defaults to a new temporary directory",
    )
    args = parser.parse_args()
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else Path(tempfile.mkdtemp(prefix="kgm-observation-capacity-")).resolve()
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "limits": {
            "photo_bytes": observation_export_service.MAX_EXPORT_TOTAL_PHOTO_BYTES,
            "payload_bytes": observation_export_service.MAX_EXPORT_TOTAL_PAYLOAD_BYTES,
            "docx_bytes": observation_export_service.MAX_EXPORT_DOCX_BYTES,
            "pixels_enforced": False,
        },
        "scenarios": {},
    }
    report["scenarios"]["multi_11x3_2048x1536"] = run_render(
        records=11,
        photos_per_record=3,
        width=2048,
        height=1536,
        noise=False,
    )
    report["scenarios"]["boundary_600_800x600"] = run_render(
        records=1,
        photos_per_record=600,
        width=800,
        height=600,
        noise=False,
    )
    report["scenarios"]["over_photo_budget"] = over_budget_probe()
    output = output_dir / "capacity.json"
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"output": str(output), "limits": report["limits"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
