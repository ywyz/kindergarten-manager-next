"""Optional Nextcloud Tasks two-way todo sync acceptance (synthetic only).

Every test uses a temporary data/credential root, a real Uvicorn local API
server and a *stateful in-memory fake* Nextcloud CalDAV service injected
through the runtime's transport seam.  No real Nextcloud instance, URL,
account or teacher credential is ever contacted.

Pinned behaviours (the teacher's explicit 2026-11-26 choice):

- default off; connect stores the password only in the machine-local DPAPI
  store — never in SQLite, never in the frontend, never in a backup;
- selecting a list is the explicit enable of 「双向同步所选清单（新增、编辑
  和完成）」;
- creates/edits/completions travel both ways with stable UIDs/ETags;
- a retried or partial create never duplicates the remote task;
- a both-sides conflict is skipped and reported, never overwritten;
- deletes are never propagated: remote delete keeps the local todo (and
  stops pushing it back), local delete keeps the remote task;
- disable stops the linkage; a local todo write no longer triggers runs.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
import xml.sax.saxutils as saxutils
from datetime import date

from tests.local.support import LocalTestCase

from app.local.todo_sync_caldav import build_vtodo, parse_vtodo
from app.local.todo_sync_credentials import NextcloudCredentialStore
from app.local.todo_sync_service import deterministic_uid

ACCOUNT_URL = "https://nextcloud.example/"
USERNAME = "synthetic-teacher"
PASSWORD = "synthetic-app-password-4711"

PRINCIPAL_HREF = "/remote.php/dav/principals/users/synthetic-teacher/"
HOME_HREF = "/remote.php/dav/calendars/synthetic-teacher/"
LIST_HREF = HOME_HREF + "tasks/"


def _multistatus(inner: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:multistatus xmlns:d="DAV:" '
        'xmlns:c="urn:ietf:params:xml:ns:caldav" '
        'xmlns:cs="http://calendarserver.org/ns/">'
        + inner
        + "</d:multistatus>"
    ).encode("utf-8")


def _principal_xml() -> bytes:
    return _multistatus(
        "<d:response><d:href>/remote.php/dav/</d:href><d:propstat><d:prop>"
        "<d:current-user-principal><d:href>" + PRINCIPAL_HREF + "</d:href>"
        "</d:current-user-principal></d:prop>"
        "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
    )


def _home_xml() -> bytes:
    return _multistatus(
        "<d:response><d:href>" + PRINCIPAL_HREF + "</d:href><d:propstat>"
        "<d:prop><c:calendar-home-set><d:href>" + HOME_HREF + "</d:href>"
        "</c:calendar-home-set></d:prop>"
        "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
    )


def _lists_xml() -> bytes:
    def calendar(href: str, name: str, components: str) -> str:
        return (
            f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>"
            "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"
            f"<d:displayname>{name}</d:displayname>"
            "<c:supported-calendar-component-set>" + components +
            "</c:supported-calendar-component-set>"
            "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
        )

    return _multistatus(
        f"<d:response><d:href>{HOME_HREF}</d:href><d:propstat><d:prop>"
        "<d:resourcetype><d:collection/></d:resourcetype></d:prop>"
        "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
        + calendar(
            HOME_HREF + "personal/",
            "个人",
            '<c:comp name="VEVENT"/>',
        )
        + calendar(
            LIST_HREF,
            "工作清单",
            '<c:comp name="VTODO"/>',
        )
    )


def _task_response(href: str, etag: str, vtodo: str) -> str:
    escaped = saxutils.escape(vtodo)
    return (
        f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>"
        f"<d:getetag>&quot;{etag}&quot;</d:getetag>"
        f"<c:calendar-data>{escaped}</c:calendar-data>"
        "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
    )


class FakeNextcloud:
    """A stateful in-memory Nextcloud Tasks service (the only 'server')."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.tasks: dict[str, dict] = {}
        self.etag_seq = 0
        self.put_log: list[dict] = []
        self.propfind_log: list[str] = []
        self.propfind_bodies: list[bytes] = []

    # -- test-side helpers ------------------------------------------------
    def add_task(
        self,
        uid: str,
        title: str,
        *,
        due_date: str | None = None,
        completed: bool = False,
    ) -> str:
        with self.lock:
            self.etag_seq += 1
            etag = f"etag-{self.etag_seq}"
            href = f"{LIST_HREF}{uid}.ics"
            self.tasks[href] = {
                "etag": etag,
                "vtodo": build_vtodo(
                    uid=uid, title=title, due_date=due_date, completed=completed
                ).decode("utf-8"),
            }
            return href

    def remove_task(self, uid: str) -> None:
        with self.lock:
            self.tasks.pop(f"{LIST_HREF}{uid}.ics", None)

    def task(self, uid: str) -> dict | None:
        with self.lock:
            return self.tasks.get(f"{LIST_HREF}{uid}.ics")

    def wait_for_task(self, uid: str, timeout: float = 10.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task = self.task(uid)
            if task is not None:
                return task
            time.sleep(0.02)
        raise AssertionError(f"remote task {uid} never appeared")

    def edit_task_title(self, uid: str, title: str) -> None:
        with self.lock:
            task = self.tasks.get(f"{LIST_HREF}{uid}.ics")
            if task is None:
                raise AssertionError(f"remote task {uid} missing")
            parsed = parse_vtodo(task["vtodo"])
            self.etag_seq += 1
            task["etag"] = f"etag-{self.etag_seq}"
            task["vtodo"] = build_vtodo(
                uid=uid,
                title=title,
                due_date=parsed["due_date"],
                completed=bool(parsed["completed"]),
            ).decode("utf-8")

    # -- transport --------------------------------------------------------
    def transport_factory(self, account):
        server = self

        class _Transport:
            def request(self, method, path, *, headers=None, body=None, depth=None):
                return server.handle(
                    method, path, dict(headers or {}), body, depth
                )

        return _Transport()

    def handle(self, method, path, headers, body, depth):
        with self.lock:
            if method == "PROPFIND":
                self.propfind_log.append(path)
                self.propfind_bodies.append(body or b"")
                if path == "/remote.php/dav/":
                    return 207, {}, _principal_xml()
                if path == PRINCIPAL_HREF:
                    return 207, {}, _home_xml()
                if path == HOME_HREF:
                    return 207, {}, _lists_xml()
                if path == LIST_HREF:
                    inner = "".join(
                        _task_response(href, task["etag"], task["vtodo"])
                        for href, task in sorted(self.tasks.items())
                    )
                    return 207, {}, _multistatus(inner)
                return 404, {}, b"{}"
            if method == "PUT" and path.startswith(LIST_HREF):
                ical = (body or b"").decode("utf-8")
                uid = ""
                for line in ical.replace("\r\n", "\n").split("\n"):
                    if line.startswith("UID:"):
                        uid = line[4:].strip()
                if not uid:
                    return 400, {}, b""
                if headers.get("If-None-Match") == "*":
                    if path in self.tasks:
                        return 412, {}, b""
                    self.etag_seq += 1
                    etag = f"etag-{self.etag_seq}"
                    self.tasks[path] = {"etag": etag, "vtodo": ical}
                    self.put_log.append(
                        {"href": path, "uid": uid, "precondition": "create"}
                    )
                    return 201, {"etag": f'"{etag}"'}, b""
                existing = self.tasks.get(path)
                if existing is None:
                    return 404, {}, b""
                match = headers.get("If-Match")
                if match != f'"{existing["etag"]}"':
                    return 412, {}, b""
                self.etag_seq += 1
                etag = f"etag-{self.etag_seq}"
                existing["etag"] = etag
                existing["vtodo"] = ical
                self.put_log.append(
                    {"href": path, "uid": uid, "precondition": "edit"}
                )
                return 204, {"etag": f'"{etag}"'}, b""
        return 404, {}, b"{}"


class TodoSyncTests(LocalTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.nextcloud = FakeNextcloud()
        self.runtime = self.make_runtime()
        self.runtime.todo_sync_transport_factory = (
            self.nextcloud.transport_factory
        )
        self.server = self.start_server(self.runtime)
        self.client = self.server.client()
        self.initialize(self.client)
        # The write-hook background sync is suppressed for deterministic
        # engine tests; the dedicated hook test restores the real scheduler.
        from app.local import todo_sync_service

        self._todo_sync_service = todo_sync_service
        self._real_schedule = todo_sync_service.schedule_background_sync
        todo_sync_service.schedule_background_sync = lambda runtime: None
        self.addCleanup(
            setattr,
            todo_sync_service,
            "schedule_background_sync",
            self._real_schedule,
        )

    def _restore_background_scheduling(self) -> None:
        self._todo_sync_service.schedule_background_sync = self._real_schedule

    # -- helpers ----------------------------------------------------------
    def sync_status(self) -> dict:
        status, payload = self.client.get("/api/local/todos/nextcloud/status")
        self.assertEqual(status, 200, payload)
        return payload

    def connect(self, *, request_id: str | None = None, password=PASSWORD):
        body = {
            "request_id": request_id or str(uuid.uuid4()),
            "url": ACCOUNT_URL,
            "username": USERNAME,
            "password": password,
        }
        status, payload = self.client.post(
            "/api/local/todos/nextcloud/connect", body
        )
        self.assertEqual(status, 200, payload)
        return payload

    def select_list(self, expected_version: int):
        status, payload = self.client.post(
            "/api/local/todos/nextcloud/select",
            {
                "request_id": str(uuid.uuid4()),
                "expected_version": expected_version,
                "list_href": LIST_HREF,
            },
        )
        self.assertEqual(status, 200, payload)
        return payload

    def connect_and_enable(self) -> dict:
        result = self.connect()
        self.assertEqual(result["enabled"], False)
        status, lists = self.client.post("/api/local/todos/nextcloud/lists", {})
        self.assertEqual(status, 200, lists)
        selected = self.select_list(result["setting_version"])
        self.assertTrue(selected["enabled"])
        return selected

    def run_sync(self, request_id: str | None = None) -> dict:
        status, payload = self.client.post(
            "/api/local/todos/nextcloud/sync",
            {"request_id": request_id or str(uuid.uuid4())},
        )
        self.assertEqual(status, 200, payload)
        return payload

    def create_todo(self, title: str, due: str | None = None) -> dict:
        status, payload = self.client.post(
            "/api/local/todos",
            {"request_id": str(uuid.uuid4()), "title": title, "due_date": due},
        )
        self.assertEqual(status, 200, payload)
        return payload

    def update_todo(self, todo_id: str, version: int, fields: dict) -> dict:
        body = {
            "request_id": str(uuid.uuid4()),
            "expected_version": version,
            **fields,
        }
        status, payload = self.client.patch(
            f"/api/local/todos/{todo_id}", body
        )
        self.assertEqual(status, 200, payload)
        return payload

    def delete_todo(self, todo_id: str, version: int) -> dict:
        status, payload = self.client.request(
            "DELETE",
            f"/api/local/todos/{todo_id}",
            {"request_id": str(uuid.uuid4()), "expected_version": version},
        )
        self.assertEqual(status, 200, payload)
        return payload

    def list_todos(self) -> list[dict]:
        status, payload = self.client.get("/api/local/todos")
        self.assertEqual(status, 200, payload)
        return payload["items"]

    def _wait_background(self, uid: str, timeout: float = 15.0) -> dict:
        return self.nextcloud.wait_for_task(uid, timeout)

    # -- tests ------------------------------------------------------------
    def test_status_defaults_off_and_password_never_reaches_sqlite(self) -> None:
        status = self.sync_status()
        self.assertEqual(status["setting"]["enabled"], False)
        self.assertEqual(status["setting"]["configured"], False)
        self.assertEqual(status["credential"]["configured"], False)

        rid = str(uuid.uuid4())
        first = self.connect(request_id=rid)
        self.assertEqual(first["enabled"], False)
        replay = self.connect(request_id=rid)
        self.assertEqual(replay, first)
        # A different fingerprint on the same request key is a conflict.
        status, payload = self.client.post(
            "/api/local/todos/nextcloud/connect",
            {
                "request_id": rid,
                "url": ACCOUNT_URL,
                "username": "other-teacher",
                "password": PASSWORD,
            },
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "SYNC_REQUEST_CONFLICT")

        db_bytes = self.runtime.db_path.read_bytes()
        self.assertNotIn(PASSWORD.encode("utf-8"), db_bytes)
        cred_file = (
            self.runtime.credential_root
            / "todo-sync-store"
            / "nextcloud.json"
        )
        self.assertTrue(cred_file.is_file())
        self.assertNotIn(PASSWORD.encode("utf-8"), cred_file.read_bytes())
        status = self.sync_status()
        self.assertEqual(status["credential"]["password_available"], True)
        # The display-safe status carries the URL/user name and the
        # *availability* flag only — never the password value.
        status_text = json.dumps(status, ensure_ascii=False)
        self.assertNotIn(PASSWORD, status_text)
        self.assertEqual(status["setting"]["server_url"], ACCOUNT_URL)
        self.assertEqual(status["setting"]["username"], USERNAME)

    def test_select_is_the_explicit_enable_and_version_is_guarded(self) -> None:
        connected = self.connect()
        status, lists = self.client.post("/api/local/todos/nextcloud/lists", {})
        self.assertEqual(status, 200, lists)
        hrefs = [item["href"] for item in lists["lists"]]
        self.assertIn(LIST_HREF, hrefs)
        self.assertFalse(lists["enabled"])
        # A stale setting version is refused, never silently applied.
        status, payload = self.client.post(
            "/api/local/todos/nextcloud/select",
            {
                "request_id": str(uuid.uuid4()),
                "expected_version": connected["setting_version"] + 5,
                "list_href": LIST_HREF,
            },
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "SYNC_VERSION_CONFLICT")
        selected = self.select_list(connected["setting_version"])
        self.assertTrue(selected["enabled"])
        self.assertEqual(selected["list_href"], LIST_HREF)
        status = self.sync_status()
        self.assertTrue(status["setting"]["enabled"])

    def test_two_way_create_edit_and_complete(self) -> None:
        self.connect_and_enable()

        # Local create → pushed with the deterministic stable UID.
        todo = self.create_todo("本地新增任务", "2026-12-08")
        uid = deterministic_uid(todo["todo_id"])
        self.run_sync()
        remote = self._wait_background(uid)
        parsed = parse_vtodo(remote["vtodo"])
        self.assertEqual(parsed["title"], "本地新增任务")
        self.assertEqual(parsed["due_date"], "2026-12-08")
        self.assertFalse(parsed["completed"])

        # Local edit → conditional remote edit via If-Match.
        edited = self.update_todo(
            todo["todo_id"], todo["version"], {"title": "本地改名任务"}
        )
        self.run_sync()
        remote = self.nextcloud.task(uid)
        parsed = parse_vtodo(remote["vtodo"])
        self.assertEqual(parsed["title"], "本地改名任务")
        self.assertEqual(
            self.nextcloud.put_log[-1]["precondition"], "edit"
        )

        # Local complete → remote completion.
        completed = self.update_todo(
            edited["todo_id"], edited["version"], {"completed": True}
        )
        self.run_sync()
        remote = self.nextcloud.task(uid)
        parsed = parse_vtodo(remote["vtodo"])
        self.assertTrue(parsed["completed"])

        # Remote create → pulled as a new local todo.
        self.nextcloud.add_task(
            "remote-uid-1@nextcloud", "远端新增任务", due_date="2026-12-09"
        )
        result = self.run_sync()
        self.assertEqual(result["pulled_created"], 1)
        items = self.list_todos()
        pulled = next(
            item for item in items if item["title"] == "远端新增任务"
        )
        self.assertEqual(pulled["due_date"], "2026-12-09")

        # Remote edit → pulled into the local todo.
        self.nextcloud.edit_task_title("remote-uid-1@nextcloud", "远端改名任务")
        result = self.run_sync()
        self.assertEqual(result["pulled_updated"], 1)
        items = self.list_todos()
        pulled = next(item for item in items if item["title"] == "远端改名任务")

        # Remote complete → local completion.
        task = self.nextcloud.task("remote-uid-1@nextcloud")
        parsed = parse_vtodo(task["vtodo"])
        self.nextcloud.tasks[f"{LIST_HREF}remote-uid-1@nextcloud.ics"] = {
            "etag": f"etag-bump-{time.monotonic_ns()}",
            "vtodo": build_vtodo(
                uid="remote-uid-1@nextcloud",
                title="远端改名任务",
                due_date=parsed["due_date"],
                completed=True,
            ).decode("utf-8"),
        }
        result = self.run_sync()
        self.assertEqual(result["pulled_updated"], 1)
        items = self.list_todos()
        pulled = next(item for item in items if item["title"] == "远端改名任务")
        self.assertTrue(pulled["completed"])

    def test_conflict_never_overwrites_either_side(self) -> None:
        self.connect_and_enable()
        todo = self.create_todo("冲突任务")
        uid = deterministic_uid(todo["todo_id"])
        self.run_sync()
        self._wait_background(uid)

        # Both sides change without an intervening sync.
        self.nextcloud.edit_task_title(uid, "远端抢先修改")
        self.update_todo(
            todo["todo_id"], todo["version"], {"title": "本地抢先修改"}
        )
        result = self.run_sync()
        self.assertEqual(result["conflicts"], 1)
        remote = parse_vtodo(self.nextcloud.task(uid)["vtodo"])
        self.assertEqual(remote["title"], "远端抢先修改")
        items = self.list_todos()
        local = next(item for item in items if item["todo_id"] == todo["todo_id"])
        self.assertEqual(local["title"], "本地抢先修改")

    def test_remote_delete_keeps_local_and_never_pushes_back(self) -> None:
        self.connect_and_enable()
        todo = self.create_todo("远端删除后保留")
        uid = deterministic_uid(todo["todo_id"])
        self.run_sync()
        self._wait_background(uid)

        self.nextcloud.remove_task(uid)
        result = self.run_sync()
        self.assertEqual(result["remote_missing"], 1)
        items = self.list_todos()
        self.assertTrue(any(item["todo_id"] == todo["todo_id"] for item in items))

        # A second run must not resurrect the remote task.
        puts_before = len(self.nextcloud.put_log)
        second = self.run_sync()
        self.assertEqual(second["pushed_created"], 0)
        self.assertEqual(len(self.nextcloud.put_log), puts_before)
        self.assertIsNone(self.nextcloud.task(uid))

    def test_local_delete_keeps_the_remote_task(self) -> None:
        self.connect_and_enable()
        todo = self.create_todo("本地删除后远端保留")
        uid = deterministic_uid(todo["todo_id"])
        self.run_sync()
        self._wait_background(uid)

        current = next(
            item for item in self.list_todos() if item["todo_id"] == todo["todo_id"]
        )
        self.delete_todo(todo["todo_id"], current["version"])
        result = self.run_sync()
        self.assertEqual(result["pushed_created"], 0)
        self.assertEqual(result["remote_kept_local"], 0)
        remote = self.nextcloud.task(uid)
        self.assertIsNotNone(remote, "local delete must never touch the remote")
        # The task still exists remotely and a later local todo never adopts
        # it by accident.
        items = self.list_todos()
        self.assertFalse(any(item["todo_id"] == todo["todo_id"] for item in items))

    def test_partial_create_retry_adopts_without_duplicating(self) -> None:
        self.connect_and_enable()
        todo = self.create_todo("断点重试任务")
        uid = deterministic_uid(todo["todo_id"])
        # Simulate a create whose link commit never landed: the remote task
        # exists with the same content, the link table does not.
        self.nextcloud.add_task(uid, "断点重试任务")
        result = self.run_sync()
        self.assertEqual(result["pushed_created"], 0)
        self.assertEqual(result["reattached"], 1)
        puts_before = len(self.nextcloud.put_log)
        again = self.run_sync()
        self.assertEqual(again["pushed_created"], 0)
        self.assertEqual(again["pushed_updated"], 0)
        self.assertEqual(len(self.nextcloud.put_log), puts_before)
        # The adopted link keeps the remote etag, so the stable pairing is
        # intact for later edits.  Adoption imported the remote content, so
        # the edit must use the version from after that import.
        items = self.list_todos()
        adopted_version = items[0]["version"]
        edited = self.update_todo(
            todo["todo_id"], adopted_version, {"title": "断点重试改名"}
        )
        self.run_sync()
        remote = parse_vtodo(self.nextcloud.task(uid)["vtodo"])
        self.assertEqual(remote["title"], "断点重试改名")
        self.assertEqual(edited["title"], "断点重试改名")

    def test_disable_stops_linkage_and_clear_removes_the_secret(self) -> None:
        enabled = self.connect_and_enable()
        todo = self.create_todo("关闭联动后停止推送")
        uid = deterministic_uid(todo["todo_id"])
        # Push the create explicitly (the background hook is suppressed in
        # these engine tests); the disable assertions below are about what
        # happens after the linkage is off.
        self.run_sync()
        self._wait_background(uid)

        status, payload = self.client.post(
            "/api/local/todos/nextcloud/disable",
            {
                "request_id": str(uuid.uuid4()),
                "expected_version": enabled["setting_version"],
                "clear_credentials": False,
            },
        )
        self.assertEqual(status, 200, payload)
        result = self.run_sync()
        self.assertEqual(result, {"state": "disabled"})

        # With the real write hook active again, a local write while
        # disabled triggers no further remote PUT.
        self._restore_background_scheduling()
        puts_before = len(self.nextcloud.put_log)
        self.update_todo(todo["todo_id"], todo["version"], {"completed": True})
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            self.assertEqual(len(self.nextcloud.put_log), puts_before)
            time.sleep(0.02)
        self.assertEqual(len(self.nextcloud.put_log), puts_before)

        # The explicit clear also forgets the machine-local password.
        status_now = self.sync_status()
        version = status_now["setting"]["setting_version"]
        status, payload = self.client.post(
            "/api/local/todos/nextcloud/disable",
            {
                "request_id": str(uuid.uuid4()),
                "expected_version": version,
                "clear_credentials": True,
            },
        )
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["credentials_cleared"])
        final = self.sync_status()
        self.assertFalse(final["credential"]["configured"])

    def test_background_write_triggers_the_push_once(self) -> None:
        # This test exercises the real write hook: the local todo write
        # itself must trigger the bounded background push without any
        # manual sync call.
        self._restore_background_scheduling()
        self.connect_and_enable()
        todo = self.create_todo("后台自动推送")
        uid = deterministic_todo_uid(todo["todo_id"])
        remote = self._wait_background(uid)
        parsed = parse_vtodo(remote["vtodo"])
        self.assertEqual(parsed["title"], "后台自动推送")

    def test_sync_receipt_is_idempotent_by_request_id(self) -> None:
        self.connect_and_enable()
        self.create_todo("回执幂等任务")
        rid = str(uuid.uuid4())
        first = self.run_sync(request_id=rid)
        self.assertEqual(first["pushed_created"], 1)
        replay = self.run_sync(request_id=rid)
        self.assertEqual(replay, first)
        status, payload = self.client.get(
            f"/api/local/todos/nextcloud/operations/{rid}"
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["action"], "sync")
        self.assertEqual(payload["result"], first)


    def test_pull_of_titleless_remote_task_uses_a_placeholder(self) -> None:
        self.connect_and_enable()
        self.nextcloud.add_task("remote-titleless@nextcloud", "")
        # An over-long remote summary is stored truncated, never dropped.
        self.nextcloud.add_task(
            "remote-long@nextcloud", "长" * 260
        )
        result = self.run_sync()
        self.assertEqual(result["pulled_created"], 2)
        items = self.list_todos()
        self.assertTrue(
            any(item["title"] == "无标题任务" for item in items)
        )
        long_item = next(
            item for item in items if item["title"].startswith("长")
        )
        self.assertEqual(len(long_item["title"]), 200)

    def test_restored_profile_never_uses_another_accounts_password(self) -> None:
        """Backup A restored onto a machine holding account B's password:
        status must not present B's password as usable for A, and lists /
        select / sync refuse until an explicit reconnect."""
        from app.local import todo_sync_service as sync_service
        from app.local.base import utc_now
        from app.local.todo_sync_credentials import NextcloudCredentialStore
        from app.local.todo_sync_models import (
            LocalTodoSyncLink,
            LocalTodoSyncSetting,
        )

        store = NextcloudCredentialStore(self.runtime.credential_root)
        store.save(
            url="https://other.example/",
            username="machine-user-b",
            password="machine-password-b",
        )
        session = self.runtime.session()
        try:
            profile_id = sync_service._profile_id(session)
            session.add(
                LocalTodoSyncSetting(
                    profile_id=profile_id,
                    enabled=True,
                    server_url="https://origin.example/",
                    username="origin-user-a",
                    list_href="/remote.php/dav/calendars/origin-user-a/list/",
                    list_name="A 的清单",
                    setting_version=9,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
            session.add(
                LocalTodoSyncLink(
                    profile_id=profile_id,
                    todo_id="todo-x",
                    server_url="https://origin.example/",
                    username="origin-user-a",
                    list_href="/remote.php/dav/calendars/origin-user-a/list/",
                    remote_uid="uid-x",
                    remote_href="/remote.php/dav/calendars/origin-user-a/list/x.ics",
                    remote_etag="e",
                    pushed_state="s",
                    remote_missing=False,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
            session.commit()
        finally:
            session.close()

        view = self.sync_status()
        self.assertEqual(view["setting"]["configured"], True)
        self.assertEqual(view["setting"]["server_url"], "https://origin.example/")
        self.assertEqual(view["credential"]["password_available"], False)
        self.assertEqual(
            view["credential"]["reason"], "SYNC_CREDENTIAL_ACCOUNT_MISMATCH"
        )
        status, payload = self.client.post("/api/local/todos/nextcloud/lists", {})
        self.assertEqual(status, 409, payload)
        self.assertEqual(
            payload["error"]["code"], "SYNC_CREDENTIAL_ACCOUNT_MISMATCH"
        )
        status, payload = self.client.post(
            "/api/local/todos/nextcloud/select",
            {
                "request_id": str(uuid.uuid4()),
                "expected_version": view["setting"]["setting_version"],
                "list_href": "/remote.php/dav/calendars/u/personal/",
            },
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(
            payload["error"]["code"], "SYNC_CREDENTIAL_ACCOUNT_MISMATCH"
        )
        status, sync_payload = self.client.post(
            "/api/local/todos/nextcloud/sync", {"request_id": str(uuid.uuid4())}
        )
        self.assertEqual(status, 409, sync_payload)
        self.assertEqual(
            sync_payload["error"]["code"], "SYNC_CREDENTIAL_ACCOUNT_MISMATCH"
        )
        # Scenario 2 — the real recovery: the teacher reconnects with the
        # account this machine actually holds (account change).  Connect
        # succeeds, the stale binding is dropped (enabled False, list
        # cleared), the credential becomes usable, and a sync is a clean
        # 200 "disabled" — never a silent network call.
        status, connected = self.client.post(
            "/api/local/todos/nextcloud/connect",
            {
                "request_id": str(uuid.uuid4()),
                "url": "https://other.example/",
                "username": "machine-user-b",
                "password": "machine-password-b",
            },
        )
        self.assertEqual(status, 200, connected)
        self.assertEqual(connected["enabled"], False)
        view = self.sync_status()
        self.assertEqual(view["credential"]["password_available"], True)
        self.assertIsNone(view["credential"].get("reason"))
        session = self.runtime.session()
        try:
            row = session.get(
                LocalTodoSyncSetting, sync_service._profile_id(session)
            )
            self.assertEqual(row.enabled, False)
            self.assertIsNone(row.list_href)
            link = session.get(
                LocalTodoSyncLink, (sync_service._profile_id(session), "todo-x")
            )
            self.assertIsNotNone(link)
        finally:
            session.close()
        status, disabled = self.client.post(
            "/api/local/todos/nextcloud/sync", {"request_id": str(uuid.uuid4())}
        )
        self.assertEqual(status, 200, disabled)
        self.assertEqual(disabled, {"state": "disabled"})

    def test_lost_create_reply_claimed_when_content_matches(self) -> None:
        """PUT landed remotely, the reply was lost before the link write:
        with identical content the next run only claims the link — 1 remote
        / 1 local, never 2 local, and the local version stays untouched so
        the current editor keeps working."""
        self.connect_and_enable()
        todo = self.create_todo("丢回执任务")
        uid = deterministic_uid(todo["todo_id"])
        self.nextcloud.add_task(uid, "丢回执任务")
        result = self.run_sync()
        self.assertEqual(result["pulled_created"], 0)
        self.assertEqual(result["reattached"], 1)
        self.assertEqual(result["conflicts"], 0)
        items = self.list_todos()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "丢回执任务")
        self.assertEqual(items[0]["version"], todo["version"])
        puts_before = len(self.nextcloud.put_log)
        again = self.run_sync()
        self.assertEqual(again["pushed_created"], 0)
        self.assertEqual(again["pushed_updated"], 0)
        self.assertEqual(len(self.nextcloud.put_log), puts_before)
        # The claimed link carries the remote etag: later edits push
        # through it without re-deciding anything.
        edited = self.update_todo(
            todo["todo_id"], todo["version"], {"title": "丢回执改名"}
        )
        self.run_sync()
        self.assertEqual(edited["title"], "丢回执改名")

    def test_lost_create_reply_conflicts_when_content_differs(self) -> None:
        """No baseline exists for a lost reply whose remote content now
        differs from the local todo: both sides are kept as-is and the run
        reports a conflict instead of silently overwriting either."""
        self.connect_and_enable()
        todo = self.create_todo("丢回执任务")
        uid = deterministic_uid(todo["todo_id"])
        self.nextcloud.add_task(uid, "远端独立内容", due_date="2026-12-01")
        result = self.run_sync()
        self.assertEqual(result["pulled_created"], 0)
        self.assertEqual(result["reattached"], 0)
        self.assertEqual(result["conflicts"], 1)
        items = self.list_todos()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "丢回执任务")
        remote = parse_vtodo(self.nextcloud.task(uid)["vtodo"])
        self.assertEqual(remote["title"], "远端独立内容")
        self.assertEqual(remote["due_date"], "2026-12-01")
        puts_before = len(self.nextcloud.put_log)
        again = self.run_sync()
        self.assertEqual(again["pushed_created"], 0)
        self.assertEqual(again["pushed_updated"], 0)
        self.assertEqual(again["conflicts"], 1)
        self.assertEqual(len(self.nextcloud.put_log), puts_before)

    def test_merge_preserves_remote_fields_on_edit(self) -> None:
        """The edit PUT merges into the real remote VCALENDAR: DESCRIPTION,
        PRIORITY, a timed remote DUE and VALARM survive; PERCENT-COMPLETE is
        the RFC property name and DTSTAMP is present."""
        self.connect_and_enable()
        todo = self.create_todo("合并任务", due="2026-12-01")
        uid = deterministic_uid(todo["todo_id"])
        # Push the create first so the link exists; then the rich remote
        # VCALENDAR is written in place under the SAME etag (metadata for
        # this test only), so the pull stays quiet and the edit merge is
        # what reads and preserves the rich fields.
        self.run_sync()
        rich = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Tests//EN\r\n"
            "BEGIN:VTODO\r\n"
            f"UID:{uid}\r\n"
            f"SUMMARY:{uid}\r\n"
            "DESCRIPTION:保留这段备注\r\n"
            "PRIORITY:5\r\n"
            "RELATED-TO;RELTYPE=PARENT:parent-1\r\n"
            "RRULE:FREQ=WEEKLY\r\n"
            "DUE;TZID=Asia/Shanghai:20261201T090000\r\n"
            "BEGIN:VALARM\r\n"
            "ACTION:DISPLAY\r\n"
            "TRIGGER:-PT10M\r\n"
            "END:VALARM\r\n"
            "END:VTODO\r\n"
            "END:VCALENDAR\r\n"
        )
        from app.local import todo_sync_service as sync_service
        from app.local.todo_sync_models import LocalTodoSyncLink

        session = self.runtime.session()
        try:
            link = session.get(
                LocalTodoSyncLink,
                (sync_service._profile_id(session), todo["todo_id"]),
            )
            self.assertIsNotNone(link)
            self.nextcloud.tasks[link.remote_href]["vtodo"] = rich
        finally:
            session.close()
        self.update_todo(todo["todo_id"], todo["version"], {"title": "本地改名"})
        self.run_sync()
        stored = self.nextcloud.task(uid)["vtodo"]
        self.assertIn("DESCRIPTION:保留这段备注", stored)
        self.assertIn("PRIORITY:5", stored)
        self.assertIn("RELATED-TO;RELTYPE=PARENT:parent-1", stored)
        self.assertIn("RRULE:FREQ=WEEKLY", stored)
        self.assertIn("DUE;TZID=Asia/Shanghai:20261201T090000", stored)
        self.assertIn("BEGIN:VALARM", stored)
        self.assertIn("SUMMARY:本地改名", stored)
        self.assertIn("PERCENT-COMPLETE:0", stored)
        self.assertNotIn("PERCENT-COMPLETED", stored)
        self.assertRegex(stored, r"DTSTAMP:\d{8}T\d{6}Z")

    def test_inflight_run_stops_after_config_change(self) -> None:
        """An engine run started under account A must stop before its next
        network write once the teacher connects account B (version bump):
        the new local todo created after the switch is never PUT to A."""
        from app.local import todo_sync_service as sync_service

        # Account A is bound and enabled first; the gated run below starts
        # against that binding.
        self.connect_and_enable()
        release_listing = threading.Event()
        listing_entered = threading.Event()
        real_client_factory = self.runtime.todo_sync_transport_factory

        def gating_factory(account):
            inner = real_client_factory(account)

            class _Gating:
                def request(self, method, path, *, headers=None, body=None, depth=None):
                    if method == "PROPFIND" and path.rstrip("/").endswith("/tasks"):
                        listing_entered.set()
                        release_listing.wait(timeout=10)
                    return inner.request(
                        method, path, headers=headers, body=body, depth=depth
                    )

            return _Gating()

        self.runtime.todo_sync_transport_factory = gating_factory
        engine_thread = threading.Thread(
            target=lambda: sync_service.run_sync(self.runtime.session(), self.runtime),
            daemon=True,
        )
        engine_thread.start()
        self.assertTrue(listing_entered.wait(timeout=10))
        # The teacher switches accounts and creates a new local todo while
        # the A listing is still held.
        status, connected = self.client.post(
            "/api/local/todos/nextcloud/connect",
            {
                "request_id": str(uuid.uuid4()),
                "url": "https://other.example/",
                "username": "user-b",
                "password": PASSWORD,
            },
        )
        self.assertEqual(status, 200, connected)
        todo = self.create_todo("切换后新增")
        release_listing.set()
        engine_thread.join(timeout=30)
        self.runtime.todo_sync_transport_factory = real_client_factory
        # The stalled A run must not have PUT the new todo anywhere.
        target_uid = deterministic_uid(todo["todo_id"])
        puts_during = [
            entry
            for entry in self.nextcloud.put_log
            if entry["uid"] == target_uid
        ]
        self.assertEqual(puts_during, [])
        # The new todo syncs under B once a run starts with B's binding.
        self.nextcloud.add_task("seed-b", "B 种子")
        view = self.sync_status()
        status, lists = self.client.post("/api/local/todos/nextcloud/lists", {})
        self.assertEqual(status, 200, lists)
        selected = self.select_list(
            view["setting"]["setting_version"]
        )
        self.assertTrue(selected["enabled"])
        result = self.run_sync()
        self.assertEqual(result["pushed_created"], 1)


def deterministic_todo_uid(todo_id: str) -> str:
    return deterministic_uid(todo_id)


if __name__ == "__main__":  # pragma: no cover
    import unittest

    unittest.main()
