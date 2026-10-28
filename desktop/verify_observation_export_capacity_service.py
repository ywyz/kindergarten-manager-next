"""Real service/API/host capacity probe for observation export.

Unlike the pure-renderer probe, this starts the protected local HTTP app,
creates synthetic records/photos through the real services, previews/creates
the export through the HTTP API, and lets the restricted host stream and
atomically save the artifact.  It measures actual bytes, time and peak RSS and
checks that an over-budget selection leaves no token/artifact.

Run with the desktop venv and an explicit output directory; synthetic data
only.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import http.client
import io
import json
import secrets
import socket
import sys
import tempfile
import threading
import time
import zipfile
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
DESKTOP = Path(__file__).resolve().parent
for path in (BACKEND, DESKTOP):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from PIL import Image  # noqa: E402
from sqlalchemy import select  # noqa: E402
import uvicorn  # noqa: E402

from app.local import (  # noqa: E402
    observation_assets,
    observation_export_service,
    observation_service,
    profile_service,
)
from app.local.app import create_local_app  # noqa: E402
from app.local.models import LocalObservationAssetDerivative, LocalProfile  # noqa: E402
from app.local.normalize import normalize_initialization  # noqa: E402
from app.local.runtime import LocalRuntime  # noqa: E402
from d1_host_api import D1HostApi  # noqa: E402
from verify_observation_export_capacity import (  # noqa: E402
    noise_jpeg,
    peak_rss_bytes,
    smooth_jpeg,
)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def payload(index: int) -> dict:
    return {
        "record_type": ("public", "indoor", "outdoor")[index % 3],
        "school_name": "合成容量探针幼儿园",
        "class_name": "中一班",
        "observation_date": f"2026-09-{(index % 28) + 1:02d}",
        "start_time": "10:00",
        "end_time": "10:20",
        "adult_count": 2,
        "child_count": 6,
        "observer_name": "王老师",
        "age_years": 5,
        "subjects": [{"name": f"容量幼儿{index}"}],
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


def create_records(
    session,
    runtime,
    profile_id,
    *,
    count,
    noise,
    photos_per_record=3,
    width=2048,
    height=1536,
):
    ids = []
    total_photo_bytes = 0
    total_pixels = 0
    for index in range(count):
        created = observation_service.create_observation(
            session,
            profile_id=profile_id,
            request_id=str(uuid.uuid4()),
            record_type=("public", "indoor", "outdoor")[index % 3],
            payload=payload(index),
        )
        observation_id = created["observation_id"]
        assets = []
        for photo_index in range(photos_per_record):
            current = observation_service.read_current(
                session, profile_id=profile_id, observation_id=observation_id
            )
            data = (
                noise_jpeg(width, height)
                if noise
                else smooth_jpeg(
                    width, height, index * photos_per_record + photo_index
                )
            )
            total_photo_bytes += len(data)
            total_pixels += width * height
            asset = observation_assets.import_asset(
                session,
                runtime,
                profile_id=profile_id,
                observation_id=observation_id,
                request_id=str(uuid.uuid4()),
                expected_revision=current["revision"],
                stream=io.BytesIO(data),
                display_name=f"synthetic-{index}-{photo_index}.jpg",
                caption=None,
            )
            assets.append(asset)
        current = observation_service.read_current(
            session, profile_id=profile_id, observation_id=observation_id
        )
        observation_service.save_observation(
            session,
            profile_id=profile_id,
            observation_id=observation_id,
            request_id=str(uuid.uuid4()),
            expected_revision=current["revision"],
            payload=payload(index),
            photos=[
                {"asset_id": asset["asset_id"], "caption": None}
                for asset in assets
            ],
            save_reason="manual",
            term_decision="keep_current",
        )
        ids.append(observation_id)
    return ids, total_photo_bytes, total_pixels


class Client:
    def __init__(self, port: int, token: str):
        self.port = port
        self.token = token
        self.origin = f"http://127.0.0.1:{port}"

    def request(self, method, path, body=None):
        data = (
            json.dumps(body, ensure_ascii=False).encode("utf-8")
            if body is not None
            else None
        )
        headers = {
            "Host": f"127.0.0.1:{self.port}",
            "Origin": self.origin,
            "X-App-Session": self.token,
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.port, timeout=300
        )
        try:
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            status = response.status
        finally:
            connection.close()
        try:
            return status, json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return status, raw


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
        else Path(tempfile.mkdtemp(prefix="kgm-observation-capacity-service-")).resolve()
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="kgm-capacity-service-data-"))
    runtime = LocalRuntime(root / "data", credential_root=root / "credentials")
    runtime.prepare()
    session = runtime.session()
    token = secrets.token_urlsafe(32)
    port = free_port()
    app = create_local_app(port=port, session_token=token, runtime=runtime)
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while time.time() < deadline and not server.started:
        time.sleep(0.02)
    if not server.started:
        raise SystemExit("local service did not start")
    client = Client(port, token)
    report: dict = {
        "limits": {
            "photo_bytes": observation_export_service.MAX_EXPORT_TOTAL_PHOTO_BYTES,
            "payload_bytes": observation_export_service.MAX_EXPORT_TOTAL_PAYLOAD_BYTES,
            "docx_bytes": observation_export_service.MAX_EXPORT_DOCX_BYTES,
            "pixels_enforced": False,
        },
        "output_dir": str(output_dir),
    }
    try:
        profile_service.initialize(
            session,
            normalize_initialization(
                request_id=str(uuid.uuid4()),
                display_name="王老师",
                class_name="中一班",
                grade="middle",
                term_name="2026 年秋季学期",
                start_date="2026-09-01",
                end_date="2026-09-30",
                school_name="合成容量探针幼儿园",
            ),
        )
        session.commit()
        profile = session.scalars(select(LocalProfile)).one()

        started = time.perf_counter()
        success_ids, success_photo_bytes, success_pixels = create_records(
            session, runtime, profile.id, count=11, noise=False
        )
        create_elapsed = time.perf_counter() - started
        status, preview = client.request(
            "POST",
            "/api/observation-exports/preview",
            {
                "request_id": str(uuid.uuid4()),
                "observation_ids": success_ids,
            },
        )
        assert status == 200, f"preview failed: {status} {preview}"
        status, created = client.request(
            "POST",
            "/api/observation-exports",
            {
                "request_id": str(uuid.uuid4()),
                "snapshot_id": preview["snapshot_id"],
                "ack_missing": True,
                "retry_existing": False,
            },
        )
        assert status == 201, f"create failed: {status} {created}"
        save_dir = output_dir / "saved"
        host = D1HostApi(
            launch_token=token,
            verify_save_dir=save_dir,
            service_port=port,
        )
        host.page_ready({"bridge_protocol": 1})
        host_started = time.perf_counter()
        host_result = host.save_observation_export(
            {
                "export_id": created["export_id"],
                "filename": created["filename"],
            }
        )
        host_elapsed = time.perf_counter() - host_started
        assert host_result.get("status") == "saved", host_result
        saved_files = sorted(save_dir.glob("*.docx"))
        assert saved_files, "host did not save a DOCX"
        saved_bytes = saved_files[-1].read_bytes()
        report["success"] = {
            "records": len(success_ids),
            "photos": len(success_ids) * 3,
            "photo_bytes": success_photo_bytes,
            "pixels": success_pixels,
            "preview_records": len(preview["records"]),
            "create_elapsed_seconds": round(create_elapsed, 4),
            "host_elapsed_seconds": round(host_elapsed, 4),
            "docx_bytes": len(saved_bytes),
            "docx_sha256": hashlib.sha256(saved_bytes).hexdigest(),
            "host_result": host_result,
            "process_peak_rss_bytes": peak_rss_bytes(),
        }

        # A real DOCX above the old daily 30 MiB Base64 cap, still below the
        # new observation photo/file budgets, must save through the restricted
        # host download/atomic-write channel.
        large_started = time.perf_counter()
        large_ids, large_photo_bytes, large_pixels = create_records(
            session,
            runtime,
            profile.id,
            count=1,
            noise=True,
            photos_per_record=16,
            width=2048,
            height=1536,
        )
        status, large_preview = client.request(
            "POST",
            "/api/observation-exports/preview",
            {
                "request_id": str(uuid.uuid4()),
                "observation_ids": large_ids,
            },
        )
        assert status == 200, f"large preview failed: {status} {large_preview}"
        status, large_created = client.request(
            "POST",
            "/api/observation-exports",
            {
                "request_id": str(uuid.uuid4()),
                "snapshot_id": large_preview["snapshot_id"],
                "ack_missing": True,
                "retry_existing": False,
            },
        )
        assert status == 201, f"large create failed: {status} {large_created}"
        large_save_dir = output_dir / "saved-large"
        large_host = D1HostApi(
            launch_token=token,
            verify_save_dir=large_save_dir,
            service_port=port,
        )
        large_host.page_ready({"bridge_protocol": 1})
        large_host_started = time.perf_counter()
        large_host_result = large_host.save_observation_export(
            {
                "export_id": large_created["export_id"],
                "filename": large_created["filename"],
            }
        )
        large_host_elapsed = time.perf_counter() - large_host_started
        assert large_host_result.get("status") == "saved", large_host_result
        large_files = sorted(large_save_dir.glob("*.docx"))
        assert large_files, "large host did not save a DOCX"
        large_data = large_files[-1].read_bytes()
        assert len(large_data) > 30 * 1024 * 1024, (
            f"large DOCX is only {len(large_data)} bytes"
        )
        with zipfile.ZipFile(io.BytesIO(large_data)) as archive:
            large_media = [
                name for name in archive.namelist() if name.startswith("word/media/")
            ]
        status, large_receipt = client.request(
            "GET",
            f"/api/observation-exports/{large_created['export_id']}/attempts/latest",
        )
        assert status == 200, f"large receipt failed: {status} {large_receipt}"
        report["large_docx_over_30mib"] = {
            "records": 1,
            "photos": 16,
            "photo_bytes": large_photo_bytes,
            "pixels": large_pixels,
            "preview_records": len(large_preview["records"]),
            "docx_bytes": len(large_data),
            "media_count": len(large_media),
            "docx_sha256": hashlib.sha256(large_data).hexdigest(),
            "create_and_host_elapsed_seconds": round(
                time.perf_counter() - large_started, 4
            ),
            "host_elapsed_seconds": round(large_host_elapsed, 4),
            "host_result": large_host_result,
            "receipt_status": large_receipt.get("status"),
            "process_peak_rss_bytes": peak_rss_bytes(),
        }

        # 600 distinct small photos through the same material/snapshot/HTTP/
        # host chain (the existing 600-image boundary), without a business
        # photo-count gate.
        boundary_started = time.perf_counter()
        boundary_ids, boundary_photo_bytes, boundary_pixels = create_records(
            session,
            runtime,
            profile.id,
            count=1,
            noise=False,
            photos_per_record=600,
            width=800,
            height=600,
        )
        derivatives = list(
            session.scalars(
                select(LocalObservationAssetDerivative).where(
                    LocalObservationAssetDerivative.observation_id == boundary_ids[0],
                    LocalObservationAssetDerivative.purpose == "export",
                )
            ).all()
        )
        boundary_derivative_bytes = sum(
            (runtime.data_dir / item.relative_path).stat().st_size
            for item in derivatives
        )
        status, boundary_preview = client.request(
            "POST",
            "/api/observation-exports/preview",
            {
                "request_id": str(uuid.uuid4()),
                "observation_ids": boundary_ids,
            },
        )
        assert status == 200, f"600 preview failed: {status} {boundary_preview}"
        status, boundary_created = client.request(
            "POST",
            "/api/observation-exports",
            {
                "request_id": str(uuid.uuid4()),
                "snapshot_id": boundary_preview["snapshot_id"],
                "ack_missing": True,
                "retry_existing": False,
            },
        )
        assert status == 201, f"600 create failed: {status} {boundary_created}"
        boundary_save_dir = output_dir / "saved-600"
        boundary_host = D1HostApi(
            launch_token=token,
            verify_save_dir=boundary_save_dir,
            service_port=port,
        )
        boundary_host.page_ready({"bridge_protocol": 1})
        boundary_host_started = time.perf_counter()
        boundary_host_result = boundary_host.save_observation_export(
            {
                "export_id": boundary_created["export_id"],
                "filename": boundary_created["filename"],
            }
        )
        boundary_host_elapsed = time.perf_counter() - boundary_host_started
        assert boundary_host_result.get("status") == "saved", boundary_host_result
        boundary_files = sorted(boundary_save_dir.glob("*.docx"))
        assert boundary_files, "600 host did not save a DOCX"
        boundary_data = boundary_files[-1].read_bytes()
        with zipfile.ZipFile(io.BytesIO(boundary_data)) as archive:
            boundary_media = [
                name for name in archive.namelist() if name.startswith("word/media/")
            ]
        assert len(boundary_media) == 600, f"600 media count {len(boundary_media)}"
        status, boundary_receipt = client.request(
            "GET",
            f"/api/observation-exports/{boundary_created['export_id']}/attempts/latest",
        )
        assert status == 200, f"600 receipt failed: {status} {boundary_receipt}"
        report["boundary_600"] = {
            "records": 1,
            "photos": 600,
            "photo_bytes": boundary_photo_bytes,
            "derivative_bytes": boundary_derivative_bytes,
            "pixels": boundary_pixels,
            "preview_records": len(boundary_preview["records"]),
            "docx_bytes": len(boundary_data),
            "media_count": len(boundary_media),
            "docx_sha256": hashlib.sha256(boundary_data).hexdigest(),
            "create_and_host_elapsed_seconds": round(
                time.perf_counter() - boundary_started, 4
            ),
            "host_elapsed_seconds": round(boundary_host_elapsed, 4),
            "host_result": boundary_host_result,
            "receipt_status": boundary_receipt.get("status"),
            "process_peak_rss_bytes": peak_rss_bytes(),
        }

        # Real over-budget materialisation: 33 noise images exceed the actual
        # 64 MiB aggregate photo budget; preview must refuse before a snapshot.
        before_artifacts = (
            len(list((runtime.data_dir / observation_export_service.EXPORT_TEMP_ROOT).glob("*")))
            if (runtime.data_dir / observation_export_service.EXPORT_TEMP_ROOT).is_dir()
            else 0
        )
        failure_started = time.perf_counter()
        failure_ids, failure_photo_bytes, failure_pixels = create_records(
            session, runtime, profile.id, count=11, noise=True
        )
        status, failure = client.request(
            "POST",
            "/api/observation-exports/preview",
            {
                "request_id": str(uuid.uuid4()),
                "observation_ids": failure_ids,
            },
        )
        failure_elapsed = time.perf_counter() - failure_started
        after_artifacts = (
            len(list((runtime.data_dir / observation_export_service.EXPORT_TEMP_ROOT).glob("*")))
            if (runtime.data_dir / observation_export_service.EXPORT_TEMP_ROOT).is_dir()
            else 0
        )
        report["failure"] = {
            "records": len(failure_ids),
            "photos": len(failure_ids) * 3,
            "photo_bytes": failure_photo_bytes,
            "pixels": failure_pixels,
            "status": status,
            "body": failure,
            "elapsed_seconds": round(failure_elapsed, 4),
            "artifacts_before": before_artifacts,
            "artifacts_after": after_artifacts,
            "process_peak_rss_bytes": peak_rss_bytes(),
        }
        assert status == 413, f"over-budget preview was not refused: {status} {failure}"
        assert failure["error"]["code"] == "OBS_EXPORT_CONTENT_TOO_LARGE"
        assert after_artifacts == before_artifacts, "failure left an artifact"
    finally:
        session.close()
        server.should_exit = True
        thread.join(timeout=20)
        runtime.dispose()
    (output_dir / "service-capacity.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"output": str(output_dir), "success": report["success"]["docx_bytes"], "failure": report["failure"]["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
