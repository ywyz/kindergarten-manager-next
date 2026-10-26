"""Actual E03 capacity matrix using the delivered material pipeline.

Generation runs in a separate process.  Every measured decode runs in a fresh
child, and the serial cases run several images in one long-lived child.  The
measured entry is ``observation_assets._prepare_asset``; the byte-limit gate
uses ``observation_assets._write_staging``.  The parent asserts expected
accept/reject outcomes, error codes, derivative caps and the working-set
budget, returning non-zero on any mismatch.

This is evidence tooling, not a product process.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import gc
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageCms

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.local import observation_assets  # noqa: E402


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


def _memory_mb() -> tuple[float, float]:
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
        kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    ):
        raise OSError("GetProcessMemoryInfo failed")
    return (
        counters.WorkingSetSize / (1024 * 1024),
        counters.PeakWorkingSetSize / (1024 * 1024),
    )


def _write_image(path: Path, image: Image.Image, **kwargs) -> None:
    image.save(path, **kwargs)


def _exif(orientation: int) -> bytes:
    value = Image.Exif()
    value[0x0112] = orientation
    return value.tobytes()


def _generate(root: Path) -> list[dict]:
    cases: list[dict] = []

    def add(
        case: str,
        image: Image.Image,
        name: str,
        *,
        expect: str = "accept",
        expected_code: str | None = None,
        orientation: int | None = None,
        **kwargs,
    ) -> None:
        path = root / name
        _write_image(path, image, **kwargs)
        cases.append(
            {
                "case": case,
                "path": str(path),
                "expect": expect,
                "expected_code": expected_code,
                "orientation": orientation,
                "source_size": list(image.size),
            }
        )

    # Near-limit matrix: every supported source format, including the
    # transparent/oriented combinations that produced the R05 counterexamples.
    add(
        "png_40mp_rgba",
        Image.new("RGBA", (8000, 5000), (20, 80, 160, 128)),
        "png_40mp_rgba.png",
        format="PNG",
    )
    add(
        "png_40mp_rgba_oriented6",
        Image.new("RGBA", (8000, 5000), (20, 80, 160, 128)),
        "png_40mp_rgba_oriented6.png",
        format="PNG",
        exif=_exif(6),
        orientation=6,
    )
    add(
        "webp_40mp_rgba_oriented6",
        Image.new("RGBA", (8000, 5000), (20, 80, 160, 128)),
        "webp_40mp_rgba_oriented6.webp",
        format="WEBP",
        quality=90,
        exif=_exif(6),
        orientation=6,
    )
    add(
        "jpeg_40mp_rgb_oriented6",
        Image.new("RGB", (8000, 5000), (180, 120, 80)),
        "jpeg_40mp_rgb_oriented6.jpg",
        format="JPEG",
        quality=90,
        exif=_exif(6),
        orientation=6,
    )
    add(
        "gif_40mp_transparent",
        Image.new("P", (8000, 5000), 0),
        "gif_40mp_transparent.gif",
        format="GIF",
        transparency=0,
    )
    add(
        "bmp_40mp_rgb",
        Image.new("RGB", (8000, 5000), "gray"),
        "bmp_40mp_rgb.bmp",
        format="BMP",
    )

    high = Image.frombytes("RGB", (5500, 3600), os.urandom(5500 * 3600 * 3))
    add(
        "high_entropy_near_25mib_jpeg",
        high,
        "high_entropy_near_25mib.jpg",
        format="JPEG",
        quality=95,
    )
    add(
        "side_8192_jpeg",
        Image.new("RGB", (8192, 1953), "gray"),
        "side_8192.jpg",
        format="JPEG",
        quality=90,
    )
    add(
        "pixel_over_42mp_jpeg",
        Image.new("RGB", (7000, 6000), "red"),
        "pixel_over_42mp.jpg",
        format="JPEG",
        quality=90,
        expect="reject",
        expected_code="OBS_MATERIAL_LIMIT",
    )
    add(
        "side_over_8193_jpeg",
        Image.new("RGB", (8193, 1000), "red"),
        "side_over_8193.jpg",
        format="JPEG",
        quality=90,
        expect="reject",
        expected_code="OBS_MATERIAL_LIMIT",
    )
    add(
        "rgba_png_metadata",
        Image.new("RGBA", (3000, 2000), (20, 80, 160, 128)),
        "rgba_png_metadata.png",
        format="PNG",
    )
    add(
        "cmyk_jpeg",
        Image.new("CMYK", (3000, 2000), (20, 80, 120, 10)),
        "cmyk.jpg",
        format="JPEG",
        quality=90,
    )
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    add(
        "icc_jpeg",
        Image.new("RGB", (3000, 2000), "green"),
        "icc.jpg",
        format="JPEG",
        quality=90,
        icc_profile=profile,
    )
    add(
        "static_gif",
        Image.new("P", (1200, 800), 0),
        "static.gif",
        format="GIF",
    )
    add(
        "bmp_small",
        Image.new("RGB", (1200, 800), "blue"),
        "small.bmp",
        format="BMP",
    )
    add(
        "webp_small",
        Image.new("RGBA", (1200, 800), (20, 80, 160, 128)),
        "small.webp",
        format="WEBP",
        quality=90,
    )
    for orientation in range(1, 9):
        add(
            f"exif_{orientation}",
            Image.new("RGB", (1200, 800), "yellow"),
            f"exif_{orientation}.jpg",
            format="JPEG",
            quality=90,
            exif=_exif(orientation),
            orientation=orientation,
        )

    # A real staging gate case: append bytes to a valid JPEG so the source
    # exceeds MAX_SOURCE_BYTES without making the probe depend on a decoder.
    valid = (root / "high_entropy_near_25mib.jpg").read_bytes()
    over = valid + b"x" * (
        observation_assets.MAX_SOURCE_BYTES + 1 - len(valid)
    )
    (root / "bytes_over_25mib.jpg").write_bytes(over)
    cases.append(
        {
            "case": "bytes_over_25mib_jpeg",
            "path": str(root / "bytes_over_25mib.jpg"),
            "expect": "reject",
            "expected_code": "OBS_MATERIAL_LIMIT",
            "orientation": None,
            "source_size": None,
            "gate": "bytes",
        }
    )
    return cases


def _decode_case(case: dict) -> dict:
    initial, _ = _memory_mb()
    started = time.perf_counter()
    result = dict(case)
    result["initial_rss_mb"] = initial
    try:
        prepared = observation_assets._prepare_asset(Path(case["path"]))
        result.update(
            {
                "accepted": True,
                "ai_bytes": len(prepared.ai_bytes),
                "export_bytes": len(prepared.export_bytes),
                "ai_size": [prepared.ai_width, prepared.ai_height],
                "export_size": [prepared.export_width, prepared.export_height],
                "source_size": [prepared.width, prepared.height],
                "orientation": prepared.orientation,
            }
        )
    except Exception as exc:  # noqa: BLE001 - evidence probe
        result.update(
            {
                "accepted": False,
                "error": type(exc).__name__,
                "code": getattr(exc, "code", None),
            }
        )
    final, peak = _memory_mb()
    result["final_rss_mb"] = final
    result["peak_rss_mb"] = peak
    result["elapsed_ms"] = (time.perf_counter() - started) * 1000
    result["source_bytes"] = Path(case["path"]).stat().st_size
    return result


def _serial(paths: list[str]) -> dict:
    initial, _ = _memory_mb()
    started = time.perf_counter()
    items = []
    for path in paths:
        item_started = time.perf_counter()
        try:
            prepared = observation_assets._prepare_asset(Path(path))
            items.append(
                {
                    "path": path,
                    "accepted": True,
                    "ai_bytes": len(prepared.ai_bytes),
                    "export_bytes": len(prepared.export_bytes),
                    "elapsed_ms": (time.perf_counter() - item_started) * 1000,
                }
            )
        except Exception as exc:  # noqa: BLE001
            items.append(
                {
                    "path": path,
                    "accepted": False,
                    "error": type(exc).__name__,
                    "code": getattr(exc, "code", None),
                }
            )
        gc.collect()
    final, peak = _memory_mb()
    return {
        "initial_rss_mb": initial,
        "final_rss_mb": final,
        "peak_rss_mb": peak,
        "elapsed_ms": (time.perf_counter() - started) * 1000,
        "items": items,
    }


def _gate_bytes(path: str) -> dict:
    root = Path(tempfile.mkdtemp(prefix="kgm-e03-byte-gate-"))
    target = root / "observations" / "staging" / "probe" / "upload.bin"
    initial, _ = _memory_mb()
    try:
        observation_assets._write_staging(
            target, io.BytesIO(Path(path).read_bytes()), root
        )
        result = {"accepted": True}
    except Exception as exc:  # noqa: BLE001
        result = {
            "accepted": False,
            "error": type(exc).__name__,
            "code": getattr(exc, "code", None),
        }
    final, peak = _memory_mb()
    result.update(
        {
            "initial_rss_mb": initial,
            "final_rss_mb": final,
            "peak_rss_mb": peak,
            "root": str(root),
        }
    )
    return result


def _validate(results: list[dict], serial_large: dict, serial_small: dict, gate: dict, budget: float) -> list[str]:
    failures: list[str] = []
    for result in results:
        case = result["case"]
        if result["expect"] == "accept":
            if not result.get("accepted"):
                failures.append(f"{case}: expected accept, got {result.get('code')}")
                continue
            if result["ai_bytes"] > observation_assets.AI_TARGET_BYTES:
                failures.append(f"{case}: AI derivative exceeds target")
            if max(result["ai_size"]) > observation_assets.AI_MAX_SIDE:
                failures.append(f"{case}: AI derivative exceeds max side")
            if max(result["export_size"]) > observation_assets.EXPORT_MAX_SIDE:
                failures.append(f"{case}: export derivative exceeds max side")
            if result["peak_rss_mb"] > budget:
                failures.append(
                    f"{case}: peak {result['peak_rss_mb']:.1f} MiB > {budget:.0f} MiB"
                )
            if result["source_size"] != result.get("expected_source_size"):
                failures.append(f"{case}: decoded source dimensions changed")
            if result["orientation"] != result.get("expected_orientation"):
                failures.append(f"{case}: orientation changed")
        else:
            if result.get("accepted"):
                failures.append(f"{case}: expected reject but was accepted")
            elif result.get("code") != result["expected_code"]:
                failures.append(
                    f"{case}: expected {result['expected_code']}, got {result.get('code')}"
                )
            if result["peak_rss_mb"] > budget:
                failures.append(
                    f"{case}: rejected case peak {result['peak_rss_mb']:.1f} MiB > {budget:.0f} MiB"
                )
    for name, serial in (("large", serial_large), ("small", serial_small)):
        if serial.get("peak_rss_mb", 0) > budget:
            failures.append(
                f"serial {name}: peak {serial['peak_rss_mb']:.1f} MiB > {budget:.0f} MiB"
            )
        for item in serial.get("items", []):
            if not item.get("accepted"):
                failures.append(f"serial {name}: {item['path']} rejected")
    if gate.get("accepted"):
        failures.append("bytes_over_25mib_jpeg: staging gate accepted oversized source")
    elif gate.get("code") != "OBS_MATERIAL_LIMIT":
        failures.append(
            f"bytes_over_25mib_jpeg: expected OBS_MATERIAL_LIMIT, got {gate.get('code')}"
        )
    return failures


def _run_child(args: list[str]) -> dict:
    completed = subprocess.run(
        [sys.executable, __file__, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    try:
        return json.loads(completed.stdout.strip().splitlines()[-1])
    except Exception:
        return {
            "accepted": False,
            "error": "invalid_probe_output",
            "stderr": completed.stderr[-2000:],
            "returncode": completed.returncode,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate-dir", type=Path)
    parser.add_argument("--decode", type=Path)
    parser.add_argument("--case")
    parser.add_argument("--serial", nargs="*")
    parser.add_argument("--gate-bytes", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--budget-mb", type=float, default=float(observation_assets.WORKING_SET_BUDGET_MB))
    args = parser.parse_args()

    if args.generate_dir:
        args.generate_dir.mkdir(parents=True, exist_ok=True)
        print(json.dumps(_generate(args.generate_dir), ensure_ascii=False))
        return 0
    if args.decode:
        case = {"case": args.case or args.decode.stem, "path": str(args.decode)}
        print(json.dumps(_decode_case(case), ensure_ascii=False))
        return 0
    if args.serial is not None:
        print(json.dumps(_serial(args.serial), ensure_ascii=False))
        return 0
    if args.gate_bytes:
        print(json.dumps(_gate_bytes(str(args.gate_bytes)), ensure_ascii=False))
        return 0

    root = Path(tempfile.mkdtemp(prefix="kgm-e03-actual-"))
    generated = subprocess.run(
        [sys.executable, __file__, "--generate-dir", str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if generated.returncode != 0:
        print(generated.stderr, file=sys.stderr)
        return 1
    cases = json.loads(generated.stdout.strip().splitlines()[-1])
    results = []
    for case in cases:
        if case.get("gate") == "bytes":
            continue
        result = _run_child(["--decode", case["path"], "--case", case["case"]])
        result["expect"] = case["expect"]
        result["expected_code"] = case["expected_code"]
        result["expected_source_size"] = case.get("source_size")
        result["expected_orientation"] = case.get("orientation")
        result["exit"] = 0
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))

    large_names = {
        "png_40mp_rgba",
        "png_40mp_rgba_oriented6",
        "webp_40mp_rgba_oriented6",
        "jpeg_40mp_rgb_oriented6",
        "gif_40mp_transparent",
        "bmp_40mp_rgb",
    }
    small_names = {
        "high_entropy_near_25mib_jpeg",
        "side_8192_jpeg",
        "rgba_png_metadata",
        "cmyk_jpeg",
        "icc_jpeg",
        "static_gif",
        "bmp_small",
        "webp_small",
        *(f"exif_{index}" for index in range(1, 9)),
    }
    by_name = {case["case"]: case for case in cases}
    serial_large = _run_child(
        ["--serial", *[by_name[name]["path"] for name in large_names]]
    )
    serial_small = _run_child(
        ["--serial", *[by_name[name]["path"] for name in small_names]]
    )
    gate = _run_child(["--gate-bytes", by_name["bytes_over_25mib_jpeg"]["path"]])
    failures = _validate(results, serial_large, serial_small, gate, args.budget_mb)
    payload = {
        "python": sys.version,
        "root": str(root),
        "pipeline": "app.local.observation_assets._prepare_asset",
        "staging_gate": "app.local.observation_assets._write_staging",
        "budget_mb": args.budget_mb,
        "results": results,
        "serial_large": serial_large,
        "serial_small": serial_small,
        "gate": gate,
        "failures": failures,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps({"failures": failures, "output": str(args.output) if args.output else None}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
