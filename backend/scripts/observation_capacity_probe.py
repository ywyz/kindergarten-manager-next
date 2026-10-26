"""Synthetic capacity probe for observation image material (E03).

Run from ``backend`` with the reviewed desktop Python:

    ../desktop/.venv-d1/Scripts/python.exe scripts/observation_capacity_probe.py \
        --output <evidence>/capacity.json

Each case runs in a fresh child process so ``PeakWorkingSetSize`` is not
polluted by a previous decode.  The script uses only synthetic images and
writes them under a temporary directory.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageCms, ImageDraw, ImageOps

AI_MAX_SIDE = 2048
AI_QUALITY = 85
AI_TARGET_BYTES = 1_048_576
EXPORT_MAX_SIDE = 2400
EXPORT_QUALITY = 90


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.wintypes.DWORD),
        ("PageFaultCount", ctypes.wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _rss_mb() -> float:
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.POINTER(_ProcessMemoryCounters),
        ctypes.wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.wintypes.BOOL
    if not psapi.GetProcessMemoryInfo(
        kernel32.GetCurrentProcess(),
        ctypes.byref(counters),
        counters.cb,
    ):
        raise OSError("GetProcessMemoryInfo failed")
    return counters.PeakWorkingSetSize / (1024 * 1024)


def _rgb_high_entropy(width: int, height: int) -> Image.Image:
    raw = os.urandom(width * height * 3)
    return Image.frombytes("RGB", (width, height), raw)


def _solid(width: int, height: int) -> Image.Image:
    return Image.new("RGB", (width, height), (180, 120, 80))


def _rgba(width: int, height: int) -> Image.Image:
    image = Image.new("RGBA", (width, height), (20, 80, 160, 128))
    draw = ImageDraw.Draw(image)
    for i in range(0, min(width, height), 64):
        draw.rectangle((i, i, i + 32, i + 32), fill=(255, 0, 0, 64))
    return image


def _palette(width: int, height: int) -> Image.Image:
    image = Image.new("P", (width, height))
    palette = []
    for i in range(256):
        palette.extend((i, (i * 3) % 256, (i * 7) % 256))
    image.putpalette(palette)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width // 2, height // 2), fill=0)
    return image


def _cmyk(width: int, height: int) -> Image.Image:
    return Image.new("CMYK", (width, height), (20, 80, 120, 10))


def _icc(width: int, height: int) -> tuple[Image.Image, bytes]:
    image = _solid(width, height)
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    return image, profile.tobytes()


def _save_case(case: str, root: Path) -> tuple[Path, dict]:
    meta: dict = {}
    if case == "rgb_12mp_high_entropy":
        image = _rgb_high_entropy(4000, 3000)
        path = root / "rgb_12mp_high_entropy.jpg"
        image.save(path, "JPEG", quality=95)
    elif case == "rgb_16mp_high_entropy":
        image = _rgb_high_entropy(4899, 3266)
        path = root / "rgb_16mp_high_entropy.jpg"
        image.save(path, "JPEG", quality=95)
    elif case == "solid_40mp":
        image = _solid(8000, 5000)
        path = root / "solid_40mp.jpg"
        image.save(path, "JPEG", quality=95)
    elif case == "rgba_png":
        image = _rgba(3000, 2000)
        path = root / "rgba_png.png"
        image.save(path, "PNG", optimize=False)
    elif case == "palette_gif":
        image = _palette(2000, 2000)
        path = root / "palette_gif.gif"
        image.save(path, "GIF")
    elif case == "cmyk_jpeg":
        image = _cmyk(3000, 2000)
        path = root / "cmyk_jpeg.jpg"
        image.save(path, "JPEG", quality=90)
    elif case == "bmp":
        image = _solid(3000, 2000)
        path = root / "bmp.bmp"
        image.save(path, "BMP")
    elif case == "webp":
        image = _rgba(3000, 2000)
        path = root / "webp.webp"
        image.save(path, "WEBP", quality=90)
    elif case == "icc_jpeg":
        image, icc = _icc(3000, 2000)
        path = root / "icc_jpeg.jpg"
        image.save(path, "JPEG", quality=90, icc_profile=icc)
        meta["icc_bytes"] = len(icc)
    elif case.startswith("exif_"):
        orientation = int(case.split("_", 1)[1])
        image = _solid(1200, 800)
        exif = Image.Exif()
        exif[0x0112] = orientation
        path = root / f"exif_{orientation}.jpg"
        image.save(path, "JPEG", quality=90, exif=exif)
    else:
        raise ValueError(f"unknown case {case}")
    meta.update(
        {
            "case": case,
            "source_bytes": path.stat().st_size,
            "source_width": image.width,
            "source_height": image.height,
            "source_mode": image.mode,
        }
    )
    return path, meta


def _encode(image: Image.Image, max_side: int, quality: int) -> tuple[int, int, int]:
    work = image.copy()
    work.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    if work.mode in ("RGBA", "LA", "P"):
        work = work.convert("RGBA")
        background = Image.new("RGB", work.size, (255, 255, 255))
        background.paste(work, mask=work.getchannel("A"))
        work = background
    else:
        work = work.convert("RGB")
    buffer = io.BytesIO()
    work.save(buffer, "JPEG", quality=quality, optimize=True)
    return len(buffer.getvalue()), work.width, work.height


def _run_case(case: str) -> dict:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="kgm-e03-cap-") as raw:
        root = Path(raw)
        path, meta = _save_case(case, root)
        decode_started = time.perf_counter()
        with Image.open(path) as opened:
            opened.load()
            orientation = None
            try:
                orientation = opened.getexif().get(0x0112)
            except Exception:
                orientation = None
            transposed = ImageOps.exif_transpose(opened)
            transposed.load()
            ai_bytes, ai_w, ai_h = _encode(transposed, AI_MAX_SIDE, AI_QUALITY)
            export_bytes, ex_w, ex_h = _encode(
                transposed, EXPORT_MAX_SIDE, EXPORT_QUALITY
            )
            decode_ms = (time.perf_counter() - decode_started) * 1000
            meta.update(
                {
                    "orientation": orientation,
                    "decoded_width": transposed.width,
                    "decoded_height": transposed.height,
                    "ai_bytes": ai_bytes,
                    "ai_width": ai_w,
                    "ai_height": ai_h,
                    "ai_under_target": ai_bytes <= AI_TARGET_BYTES,
                    "export_bytes": export_bytes,
                    "export_width": ex_w,
                    "export_height": ex_h,
                    "peak_rss_mb": _rss_mb(),
                    "decode_encode_ms": decode_ms,
                    "elapsed_ms": (time.perf_counter() - started) * 1000,
                }
            )
            return meta


def _child(case: str) -> int:
    try:
        print(json.dumps(_run_case(case), ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001 - evidence probe
        print(json.dumps({"case": case, "error": type(exc).__name__, "message": str(exc)}))
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.case:
        return _child(args.case)
    cases = [
        "rgb_12mp_high_entropy",
        "rgb_16mp_high_entropy",
        "solid_40mp",
        "rgba_png",
        "palette_gif",
        "cmyk_jpeg",
        "bmp",
        "webp",
        "icc_jpeg",
        *[f"exif_{i}" for i in range(1, 9)],
    ]
    results = []
    for case in cases:
        completed = subprocess.run(
            [sys.executable, __file__, "--case", case],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        line = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
        try:
            result = json.loads(line)
        except json.JSONDecodeError:
            result = {
                "case": case,
                "error": "probe_output_invalid",
                "exit": completed.returncode,
                "stderr": completed.stderr[-500:],
            }
        result["exit"] = completed.returncode
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "python": sys.version,
                    "ai_max_side": AI_MAX_SIDE,
                    "ai_quality": AI_QUALITY,
                    "ai_target_bytes": AI_TARGET_BYTES,
                    "export_max_side": EXPORT_MAX_SIDE,
                    "export_quality": EXPORT_QUALITY,
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0 if all(item.get("exit") == 0 for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
