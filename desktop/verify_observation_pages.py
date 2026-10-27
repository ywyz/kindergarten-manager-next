"""D4 E09/E10 observation page verifier (real local HTTP, synthetic data).

Runs the real FastAPI app on a loopback port with an isolated ``--data-dir``
and writes its report / manifest to ``--output-dir``. It never calls a real
AI provider: the optional AI phase uses the reviewed in-process executor with
the fake spawn worker and a synthetic credential root.

Usage:
    python verify_observation_pages.py \
        [--data-dir DIR] [--output-dir DIR] [--keep] [--skip-ai]

Exit codes: 0 all checks passed, 1 a check failed, 2 startup/environment
failure. The script is re-runnable; it never touches the real teacher data
directory, real credentials, OneDrive originals or the old package.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import os
import secrets
import shutil
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
BACKEND = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from PIL import Image  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.local import ai_config_service, ai_executor, profile_service  # noqa: E402
from app.local.app import create_local_app  # noqa: E402
from app.local.normalize import normalize_initialization  # noqa: E402
from app.local.runtime import LocalRuntime  # noqa: E402
from tests.local.obs_ai_workers import observation_worker_entry  # noqa: E402
from tests.local.support import free_port, initialize_body  # noqa: E402

import uvicorn  # noqa: E402


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Report:
    def __init__(self, output_dir: Path, data_dir: Path):
        self.output_dir = output_dir
        self.data_dir = data_dir
        self.checks: list[dict] = []
        self.notes: list[str] = []

    def check(self, name: str, ok: bool, detail=None) -> bool:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok and detail is not None:
            print(f"       {detail}")
        return bool(ok)

    def note(self, text: str) -> None:
        self.notes.append(text)
        print(f"[note] {text}")

    @property
    def ok(self) -> bool:
        return all(item["ok"] for item in self.checks)

    def write(self) -> Path:
        payload = {
            "ok": self.ok,
            "generated_at": now_iso(),
            "data_dir": str(self.data_dir),
            "output_dir": str(self.output_dir),
            "checks": self.checks,
            "notes": self.notes,
            "python": sys.version,
            "platform": sys.platform,
        }
        report = self.output_dir / "report.json"
        report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        files = []
        for path in sorted(self.output_dir.glob("**/*")):
            if not path.is_file():
                continue
            files.append(
                {
                    "path": str(path.relative_to(self.output_dir)),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "bytes": path.stat().st_size,
                }
            )
        source_files = [
            "backend/app/local/observation_api.py",
            "backend/app/local/observation_service.py",
            "backend/app/local/observation_assets.py",
            "backend/app/local/observation_history_service.py",
            "backend/app/local/observation_ai_service.py",
            "frontend/src/d1/views/ObservationsView.vue",
            "frontend/src/d1/views/ObservationEditorView.vue",
            "frontend/src/d1/observation.ts",
            "frontend/src/d1/observation-photos.ts",
        ]
        sources = {}
        for relative in source_files:
            path = REPO_ROOT / relative
            if path.is_file():
                sources[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = self.output_dir / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "generated_at": now_iso(),
                    "report": "report.json",
                    "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
                    "evidence_files": files,
                    "source_sha256": sources,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return report


class Client:
    def __init__(self, port: int, token: str):
        self.port = port
        self.token = token
        self.origin = f"http://127.0.0.1:{port}"
        self.host = f"127.0.0.1:{port}"

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        token: bool = True,
        origin: bool = True,
        content_type: str | None = None,
        raw_body: bytes | None = None,
        read: bool = True,
        timeout: float = 120.0,
    ):
        headers = {"Host": self.host}
        if token:
            headers["X-App-Session"] = self.token
        if origin:
            headers["Origin"] = self.origin
        payload = raw_body
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            content_type = content_type or "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            connection.request(method, path, body=payload, headers=headers)
            if not read:
                return None
            response = connection.getresponse()
            data = response.read()
            status = response.status
            response_headers = {k.lower(): v for k, v in response.getheaders()}
        finally:
            connection.close()
        try:
            parsed = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = data
        return status, parsed, response_headers

    def json(self, method: str, path: str, body: dict | None = None, **kwargs):
        result = self.request(method, path, body, **kwargs)
        return result[0], result[1]

    def get(self, path: str, **kwargs):
        return self.json("GET", path, None, **kwargs)

    def post(self, path: str, body: dict | None = None, **kwargs):
        return self.json("POST", path, body, **kwargs)

    def patch(self, path: str, body: dict, **kwargs):
        return self.json("PATCH", path, body, **kwargs)

    def delete(self, path: str, body: dict, **kwargs):
        return self.json("DELETE", path, body, **kwargs)


def jpeg(color=(200, 40, 40)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (96, 64), color).save(buffer, "JPEG", quality=88)
    return buffer.getvalue()


def multipart(
    fields: dict[str, str], file_bytes: bytes, *, filename="photo.jpg"
) -> tuple[bytes, str]:
    boundary = "----kgm" + secrets.token_hex(12)
    body = bytearray()
    for key, value in fields.items():
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")
    body += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: image/jpeg\r\n\r\n"
    ).encode("utf-8")
    body += file_bytes + b"\r\n"
    body += f"--{boundary}--\r\n".encode("utf-8")
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def start_service(runtime: LocalRuntime, executor=None):
    token = secrets.token_urlsafe(32)
    port = free_port()
    app = create_local_app(
        port=port, session_token=token, runtime=runtime, executor=executor
    )
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="obs-verify", daemon=True)
    thread.start()
    deadline = time.time() + 20
    while time.time() < deadline:
        if server.started:
            return server, thread, Client(port, token)
        if not thread.is_alive():
            raise RuntimeError("verification server thread exited")
        time.sleep(0.02)
    raise RuntimeError("verification server did not start")


def stop_service(server, thread) -> None:
    server.should_exit = True
    thread.join(timeout=20)
    if thread.is_alive():
        raise RuntimeError("verification server did not stop")


def wait_for(predicate, *, timeout=30.0, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--skip-ai", action="store_true")
    args = parser.parse_args()

    root_env = os.environ.get("KGM_OBSERVATION_EVIDENCE_ROOT")
    if args.output_dir:
        output_dir = Path(args.output_dir).resolve()
    elif root_env:
        output_dir = (
            Path(root_env).resolve()
            / f"verify-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        )
    else:
        output_dir = Path(tempfile.mkdtemp(prefix="kgm-obs-pages-")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.data_dir:
        data_dir = Path(args.data_dir).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        temporary = False
    else:
        data_dir = Path(tempfile.mkdtemp(prefix="kgm-obs-pages-data-"))
        temporary = True
    # The credential store creates its own restricted directory; pre-creating
    # it would give it inherited permissions and the store correctly refuses.
    credential_dir = data_dir.parent / (data_dir.name + "-credentials")

    report = Report(output_dir, data_dir)
    report.note(f"output_dir={output_dir}")
    report.note(f"data_dir={data_dir}")
    report.note(f"credential_root={credential_dir}")
    report.note("real AI is never called; synthetic DB/images and fake worker only")

    runtime = None
    server = None
    thread = None
    executor = None
    try:
        runtime = LocalRuntime(data_dir, credential_root=credential_dir)
        runtime.prepare()
        session = runtime.session()
        profile_service.initialize(
            session, normalize_initialization(**initialize_body())
        )
        session.commit()
        session.close()
        server, thread, client = start_service(runtime)

        # -- guards -------------------------------------------------------
        status, body = client.get("/api/observations", token=False)
        report.check("guard: observation list requires the app session", status == 401, status)
        status, body = client.post(
            "/api/observations",
            {"request_id": str(uuid.uuid4()), "record_type": "public"},
            origin=False,
        )
        report.check("guard: mutating observation request requires Origin", status == 403, status)

        # -- create / list / read ----------------------------------------
        status, created = client.post(
            "/api/observations",
            {
                "request_id": str(uuid.uuid4()),
                "record_type": "public",
                "payload": {
                    "observation_date": "2026-09-15",
                    "subjects": [{"name": "小明"}, {"name": "小红"}],
                    "environment": "积木区",
                    "age_years": 5,
                },
            },
        )
        report.check("create: observation created", status == 201, (status, created))
        observation_id = created["observation_id"]
        status, current = client.get(f"/api/observations/{observation_id}")
        report.check(
            "create: school/class/observer are brought from the local profile",
            status == 200
            and current["payload"]["school_name"] == "示范幼儿园"
            and current["payload"]["class_name"] == "中一班",
            (status, current.get("payload") if isinstance(current, dict) else current),
        )
        status, listed = client.get("/api/observations?limit=10")
        report.check(
            "list: same-day record is listed with ordered subjects",
            status == 200
            and listed["total"] == 1
            and listed["items"][0]["subjects"] == ["小明", "小红"],
            (status, listed),
        )
        status, filtered = client.get(
            "/api/observations?subject=" + quote("小红")
        )
        report.check("list: subject filter matches the stored order", status == 200 and filtered["total"] == 1, (status, filtered))
        status, filtered = client.get("/api/observations?unassigned=true")
        report.check("list: unassigned filter excludes the assigned record", status == 200 and filtered["total"] == 0, (status, filtered))

        # -- save / conflict / lost reply ---------------------------------
        save_request = str(uuid.uuid4())
        status, saved = client.patch(
            f"/api/observations/{observation_id}",
            {
                "request_id": save_request,
                "expected_revision": 1,
                "payload": {"observation_goal": "观察合作"},
                "save_reason": "manual",
            },
        )
        report.check("save: manual save creates a retained version", status == 200 and saved["history_created"], (status, saved))
        status, replay = client.patch(
            f"/api/observations/{observation_id}",
            {
                "request_id": save_request,
                "expected_revision": 1,
                "payload": {"observation_goal": "观察合作"},
                "save_reason": "manual",
            },
        )
        report.check("save: same request id replays the committed result", status == 200 and replay["revision"] == saved["revision"], (status, replay))
        status, conflict = client.patch(
            f"/api/observations/{observation_id}",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": 1,
                "payload": {"observation_goal": "旧版本"},
                "save_reason": "manual",
            },
        )
        report.check(
            "save: stale revision returns OBS_REVISION_CONFLICT",
            status == 409 and conflict["error"]["code"] == "OBS_REVISION_CONFLICT",
            (status, conflict),
        )
        lost_request = str(uuid.uuid4())
        current = client.get(f"/api/observations/{observation_id}")[1]
        client.request(
            "PATCH",
            f"/api/observations/{observation_id}",
            {
                "request_id": lost_request,
                "expected_revision": current["revision"],
                "payload": {"observation_goal": "丢失回包的保存"},
                "save_reason": "manual",
            },
            read=False,
        )
        receipt = wait_for(
            lambda: client.get(
                f"/api/observations/{observation_id}/operations/{lost_request}"
            )[1]
            if client.get(
                f"/api/observations/{observation_id}/operations/{lost_request}"
            )[0]
            == 200
            else None,
            timeout=10,
        )
        report.check(
            "save: a lost reply is read back from the observation receipt",
            bool(receipt)
            and receipt["result"]["revision"] == current["revision"] + 1,
            receipt,
        )

        # -- term decision ------------------------------------------------
        status, cross = client.patch(
            f"/api/observations/{observation_id}",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": receipt["result"]["revision"],
                "payload": {"observation_date": "2026-02-10"},
                "save_reason": "manual",
            },
        )
        options = (cross.get("error", {}).get("details") or {}).get("options") if isinstance(cross, dict) else None
        report.check(
            "term: cross-term date change requires an explicit decision",
            status == 409
            and cross["error"]["code"] == "OBS_TERM_DECISION_REQUIRED"
            and bool(options),
            (status, cross),
        )
        status, term_saved = client.patch(
            f"/api/observations/{observation_id}",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": receipt["result"]["revision"],
                "payload": {"observation_date": "2026-02-10"},
                "save_reason": "manual",
                "term_decision": "assign_selected",
                "selected_term_id": options[0]["term_id"],
            },
        )
        report.check(
            "term: explicit selected term is stored",
            status == 200
            and client.get(f"/api/observations/{observation_id}")[1]["payload"]["term_id"]
            == options[0]["term_id"],
            (status, term_saved),
        )

        # -- photos -------------------------------------------------------
        current = client.get(f"/api/observations/{observation_id}")[1]
        body, content_type = multipart(
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": str(current["revision"]),
                "caption": "第一张",
                "display_name": "a.jpg",
            },
            jpeg(),
        )
        status, uploaded, headers = client.request(
            "POST",
            f"/api/observations/{observation_id}/photos",
            raw_body=body,
            content_type=content_type,
        )
        report.check("photos: multipart import commits an asset", status == 201, (status, uploaded))
        asset_id = uploaded["asset_id"]
        body, content_type = multipart(
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": str(uploaded["revision"]),
                "display_name": "b.jpg",
            },
            jpeg((40, 60, 200)),
        )
        status, uploaded2, headers = client.request(
            "POST",
            f"/api/observations/{observation_id}/photos",
            raw_body=body,
            content_type=content_type,
        )
        report.check("photos: second import keeps order", status == 201, (status, uploaded2))
        status, photos = client.get(f"/api/observations/{observation_id}/photos")
        report.check(
            "photos: ordered list keeps caption and sort order",
            status == 200
            and [item["caption"] for item in photos] == ["第一张", None]
            and [item["sort_order"] for item in photos] == [0, 1],
            (status, photos),
        )
        status, _data, headers = client.request(
            "GET",
            f"/api/observations/{observation_id}/photos/{asset_id}/derivatives/ai/content",
        )
        report.check(
            "photos: authenticated derivative Blob is served as JPEG",
            status == 200 and headers.get("content-type") == "image/jpeg" and len(_data) > 0,
            (status, headers.get("content-type"), len(_data) if isinstance(_data, bytes) else _data),
        )
        status, _data, headers = client.request(
            "GET",
            f"/api/observations/{observation_id}/photos/{asset_id}/content",
            token=False,
        )
        report.check("photos: original binary route requires the session", status == 401, status)
        current = client.get(f"/api/observations/{observation_id}")[1]
        status, captioned = client.patch(
            f"/api/observations/{observation_id}/photos/{asset_id}",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": current["revision"],
                "caption": "新说明",
            },
        )
        report.check("photos: caption update is a draft revision", status == 200 and captioned["changed"], (status, captioned))
        current = client.get(f"/api/observations/{observation_id}")[1]
        ids = [item["asset_id"] for item in current["photos"]]
        status, reordered = client.post(
            f"/api/observations/{observation_id}/photos/order",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": current["revision"],
                "asset_ids": list(reversed(ids)),
            },
        )
        report.check(
            "photos: explicit reorder persists",
            status == 200
            and [item["asset_id"] for item in reordered["photos"]] == list(reversed(ids)),
            (status, reordered),
        )
        current = client.get(f"/api/observations/{observation_id}")[1]
        removed_id = current["photos"][1]["asset_id"]
        status, removed = client.delete(
            f"/api/observations/{observation_id}/photos/{removed_id}",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": current["revision"],
            },
        )
        report.check("photos: remove only detaches the current association", status == 200 and len(removed["photos"]) == 1, (status, removed))

        # -- history / restore -------------------------------------------
        status, history = client.get(f"/api/observations/{observation_id}/history")
        report.check("history: retained versions are listed", status == 200 and len(history) >= 1, (status, history))
        oldest = history[-1]["version"]
        status, detail = client.get(f"/api/observations/{observation_id}/history/{oldest}")
        report.check("history: version detail carries payload and photos", status == 200 and "payload" in detail and "photos" in detail, status)
        current = client.get(f"/api/observations/{observation_id}")[1]
        # The current draft must already be the latest retained node; the
        # protective save is the normal editor save.
        status, protected = client.patch(
            f"/api/observations/{observation_id}",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": current["revision"],
                "payload": {},
                "save_reason": "pre_restore",
            },
        )
        report.check("restore: pre_restore save succeeds", status == 200, (status, protected))
        current = client.get(f"/api/observations/{observation_id}")[1]
        preview_request = str(uuid.uuid4())
        status, preview = client.post(
            f"/api/observations/{observation_id}/history/preview-restore",
            {
                "request_id": preview_request,
                "source_version": oldest,
                "base_draft_revision": current["revision"],
                "base_draft_hash": current["payload_hash"],
                "term_decision": "keep_history",
            },
        )
        report.check("restore: preview binds the current draft and source", status == 200 and bool(preview.get("restore_token")), (status, preview))
        status, restored = client.post(
            f"/api/observations/{observation_id}/history/restore",
            {
                "request_id": preview_request,
                "restore_token": preview["restore_token"],
                "expected_base_revision": preview["base_draft_revision"],
                "expected_base_hash": preview["base_draft_hash"],
                "term_decision": "keep_history",
            },
        )
        report.check("restore: restore commits a new version", status == 200 and restored["changed"], (status, restored))
        status, receipt = client.get(
            f"/api/observations/{observation_id}/history/restore-operations/{preview_request}"
        )
        report.check("restore: operation receipt is readable", status == 200 and receipt["result"]["revision"] == restored["revision"], (status, receipt))
        # The restored source version may predate the photo imports; add one
        # valid photo again so the AI readiness gate can be exercised.
        current = client.get(f"/api/observations/{observation_id}")[1]
        body, content_type = multipart(
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": str(current["revision"]),
                "caption": "恢复后照片",
                "display_name": "restored.jpg",
            },
            jpeg((20, 120, 60)),
        )
        status, post_restore_photo, _headers = client.request(
            "POST",
            f"/api/observations/{observation_id}/photos",
            raw_body=body,
            content_type=content_type,
        )
        report.check(
            "photos: a post-restore import prepares the AI input",
            status == 201,
            (status, post_restore_photo),
        )

        # -- daily regression --------------------------------------------
        status, plan = client.post(
            "/api/daily-plans",
            {"plan_date": "2026-09-15"},
        )
        report.check("daily: the existing create route still works", status in (200, 201) and plan.get("id"), (status, plan))
        status, plans = client.get("/api/daily-plans?from=2026-09-01&to=2026-09-30")
        report.check("daily: list stays on the daily source", status == 200 and plans["total"] == 1, (status, plans))
        status, tasks = client.get("/api/local/ai/tasks")
        report.check("daily: task list does not expose observation tasks", status == 200 and tasks["items"] == [], (status, tasks))

        # -- optional fake-AI candidate flow ------------------------------
        if not args.skip_ai:
            session = runtime.session()
            version = (
                session.execute(
                    text("SELECT current_config_version FROM local_ai_state")
                ).scalar()
                or 0
            )
            ai_config_service.patch_config(
                session,
                expected_ai_config_version=version,
                base_url="https://api.deepseek.com/v1",
                model="deepseek-flash",
                secret="synthetic-secret",
                secret_provided=True,
                request_id=str(uuid.uuid4()),
                credential_root=runtime.credential_root,
            )
            session.close()
            executor = ai_executor.AiExecutor(
                runtime, worker_target=observation_worker_entry
            )
            executor.start()
            stop_service(server, thread)
            server, thread, client = start_service(runtime, executor)
            current = client.get(f"/api/observations/{observation_id}")[1]
            status, task = client.post(
                f"/api/observations/{observation_id}/ai-tasks",
                {
                    "request_id": str(uuid.uuid4()),
                    "task_type": "game_observation_generate",
                    "expected_revision": current["revision"],
                    "expected_hash": current["payload_hash"],
                },
            )
            report.check("ai: observation task is accepted", status == 202 and bool(task.get("id")), (status, task))
            task_id = task.get("id")
            if not task_id:
                report.note("AI phase stopped: task was not created")
                report.write()
                return 0 if report.ok else 1
            final = wait_for(
                lambda: (
                    lambda pair: pair[1]
                    if pair[0] == 200
                    and pair[1].get("status")
                    in ("succeeded", "failed", "paused", "outcome_unknown")
                    else None
                )(
                    client.get(
                        f"/api/observations/{observation_id}/ai-tasks/{task_id}"
                    )
                ),
                timeout=40,
            )
            report.check(
                "ai: fake worker finishes the task",
                bool(final) and final["status"] == "succeeded",
                final,
            )
            status, candidates = client.get(
                f"/api/observations/{observation_id}/ai-candidates"
            )
            report.check("ai: candidate is persisted", status == 200 and bool(candidates["items"]), (status, candidates))
            candidate_id = candidates["items"][-1]["id"]
            status, detail = client.get(
                f"/api/observations/{observation_id}/ai-candidates/{candidate_id}"
            )
            report.check("ai: candidate detail carries raw_candidate", status == 200 and "raw_candidate" in detail, status)
            current = client.get(f"/api/observations/{observation_id}")[1]
            status, adoption_preview = client.post(
                f"/api/observations/{observation_id}/ai-candidates/{candidate_id}/preview-adoption",
                {
                    "request_id": str(uuid.uuid4()),
                    "expected_revision": current["revision"],
                    "expected_hash": current["payload_hash"],
                    "selected_targets": ["observation_goal"],
                },
            )
            report.check("ai: adoption preview issues a token", status == 200 and bool(adoption_preview.get("adoption_token")), (status, adoption_preview))
            status, adopted = client.post(
                f"/api/observations/{observation_id}/ai-candidates/{candidate_id}/adopt",
                {
                    "request_id": str(uuid.uuid4()),
                    "expected_revision": current["revision"],
                    "expected_hash": current["payload_hash"],
                    "selected_targets": ["observation_goal"],
                    "preview_token": adoption_preview["adoption_token"],
                },
            )
            report.check(
                "ai: adoption writes the selected target only",
                status == 200 and adopted["selected_targets"] == ["observation_goal"],
                (status, adopted),
            )
        else:
            report.note("AI candidate phase skipped by --skip-ai")

        report.note("service / real HTTP / synthetic AI checks completed")
        report.write()
        return 0 if report.ok else 1
    except Exception as exc:  # noqa: BLE001 - report startup/environment failures
        report.check("verification completed without an unexpected exception", False, repr(exc))
        report.write()
        return 2
    finally:
        try:
            if executor is not None:
                executor.dispose()
        except Exception:
            pass
        try:
            if server is not None and thread is not None:
                stop_service(server, thread)
        except Exception:
            pass
        try:
            if runtime is not None:
                runtime.dispose()
        except Exception:
            pass
        if temporary and not args.keep:
            shutil.rmtree(data_dir, ignore_errors=True)
            shutil.rmtree(credential_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
