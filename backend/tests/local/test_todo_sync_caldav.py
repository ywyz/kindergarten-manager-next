"""Nextcloud Tasks (CalDAV) client tests with a synthetic transport.

No real Nextcloud service, URL, account or credential is involved: the
transport is an in-memory fake that answers the fixed PROPFIND/PUT shapes.
These tests pin the strict parsing, the fixed error codes and the
create/edit preconditions that keep retries duplicate-free and conflicts
non-destructive.
"""

from __future__ import annotations

import unittest
import uuid

from app.local.todo_sync_caldav import (
    DAV_ROOT_PATH,
    MAX_RESPONSE_BYTES,
    NextcloudTasksClient,
    TodoSyncError,
    build_vtodo,
    parse_vtodo,
)


def multistatus(body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:multistatus xmlns:d="DAV:" '
        'xmlns:c="urn:ietf:params:xml:ns:caldav" '
        'xmlns:cs="http://calendarserver.org/ns/">'
        + body
        + "</d:multistatus>"
    ).encode("utf-8")


PRINCIPAL_ANSWER = multistatus(
    "<d:response><d:href>/remote.php/dav/</d:href><d:propstat><d:prop>"
    "<d:current-user-principal><d:href>"
    "/remote.php/dav/principals/users/synthetic-teacher/"
    "</d:href></d:current-user-principal>"
    "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
)

HOME_ANSWER = multistatus(
    "<d:response><d:href>/remote.php/dav/principals/users/synthetic-teacher/</d:href>"
    "<d:propstat><d:prop><c:calendar-home-set><d:href>"
    "/remote.php/dav/calendars/synthetic-teacher/"
    "</d:href></c:calendar-home-set></d:prop>"
    "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
)

LISTS_ANSWER = multistatus(
    "<d:response><d:href>/remote.php/dav/calendars/synthetic-teacher/</d:href>"
    "<d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype>"
    "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
    "<d:response><d:href>/remote.php/dav/calendars/synthetic-teacher/personal/</d:href>"
    "<d:propstat><d:prop><d:resourcetype><d:collection/>"
    "<c:calendar/></d:resourcetype><d:displayname>个人</d:displayname>"
    "<cs:supported-calendar-component-set>"
    '<c:comp name="VEVENT"/><c:comp name="VTODO"/>'
    "</cs:supported-calendar-component-set>"
    "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
    "<d:response><d:href>/remote.php/dav/calendars/synthetic-teacher/tasks/</d:href>"
    "<d:propstat><d:prop><d:resourcetype><d:collection/>"
    '<c:calendar/></d:resourcetype><d:displayname>工作清单</d:displayname>'
    "<cs:supported-calendar-component-set>"
    '<c:comp name="VTODO"/>'
    "</cs:supported-calendar-component-set>"
    "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
)


def task_response(href: str, etag: str, vtodo: str) -> str:
    return (
        f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>"
        f"<d:getetag>&quot;{etag}&quot;</d:getetag>"
        f"<c:calendar-data>{vtodo}</c:calendar-data>"
        "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
    )


class FakeTransport:
    def __init__(self, answers: dict[str, tuple[int, dict, bytes]] | None = None):
        self.answers = dict(answers or {})
        self.requests: list[dict] = []

    def request(self, method, path, *, headers=None, body=None, depth=None):
        self.requests.append(
            {
                "method": method,
                "path": path,
                "headers": dict(headers or {}),
                "body": body,
                "depth": depth,
            }
        )
        key = (method, path)
        if key in self.answers:
            status, response_headers, payload = self.answers[key]
            return status, dict(response_headers), payload
        return 404, {}, b"{}"


class VtodoTests(unittest.TestCase):
    def test_roundtrip_keeps_title_due_and_completion(self) -> None:
        payload = build_vtodo(
            uid="kgm-todo-abc@kindergarten-manager-next",
            title="带, 分号; 与换行\n的标题",
            due_date="2026-12-01",
            completed=True,
        )
        parsed = parse_vtodo(payload.decode("utf-8"))
        self.assertEqual(parsed["uid"], "kgm-todo-abc@kindergarten-manager-next")
        self.assertEqual(parsed["title"], "带, 分号; 与换行\n的标题")
        self.assertEqual(parsed["due_date"], "2026-12-01")
        self.assertTrue(parsed["completed"])

    def test_percent_completed_100_counts_as_completed(self) -> None:
        text = (
            "BEGIN:VTODO\r\nUID:u1@x\r\nSUMMARY:折叠 行\r\n  续行\r\n"
            "PERCENT-COMPLETED:100\r\nEND:VTODO\r\n"
        )
        parsed = parse_vtodo(text)
        # RFC 5545 unfolding removes exactly one leading whitespace char.
        self.assertEqual(parsed["title"], "折叠 行 续行")
        self.assertTrue(parsed["completed"])

    def test_unfolded_long_line_and_plain_state(self) -> None:
        text = "BEGIN:VTODO\nUID:u2@x\nSUMMARY:普通任务\nSTATUS:NEEDS-ACTION\nEND:VTODO\n"
        parsed = parse_vtodo(text)
        self.assertFalse(parsed["completed"])
        self.assertEqual(parsed["title"], "普通任务")


class ClientParsingTests(unittest.TestCase):
    def _client(self, transport: FakeTransport) -> NextcloudTasksClient:
        return NextcloudTasksClient(transport)

    def test_probe_reports_principal(self) -> None:
        transport = FakeTransport(
            {("PROPFIND", DAV_ROOT_PATH): (207, {}, PRINCIPAL_ANSWER)}
        )
        probe = self._client(transport).probe_connection()
        self.assertTrue(probe["ok"])
        self.assertEqual(
            probe["principal"], "/remote.php/dav/principals/users/synthetic-teacher/"
        )

    def test_calendar_home_uses_home_set_answer(self) -> None:
        transport = FakeTransport(
            {
                ("PROPFIND", DAV_ROOT_PATH): (207, {}, PRINCIPAL_ANSWER),
                (
                    "PROPFIND",
                    "/remote.php/dav/principals/users/synthetic-teacher/",
                ): (207, {}, HOME_ANSWER),
            }
        )
        client = self._client(transport)
        home = client.calendar_home(client.probe_connection()["principal"])
        self.assertEqual(home, "/remote.php/dav/calendars/synthetic-teacher/")

    def test_list_lists_filters_calendars_and_orders_vtodo_first(self) -> None:
        transport = FakeTransport(
            {
                (
                    "PROPFIND",
                    "/remote.php/dav/calendars/synthetic-teacher/",
                ): (207, {}, LISTS_ANSWER)
            }
        )
        lists = self._client(transport).list_lists(
            "/remote.php/dav/calendars/synthetic-teacher/"
        )
        self.assertEqual(len(lists), 2)
        # Both lists advertise VTODO; the ordering is the deterministic
        # (VTODO-capable first, then display name) rule.
        names = [item.display_name for item in lists]
        self.assertEqual(names, sorted(names))
        self.assertTrue(all(item.supports_vtodo for item in lists))
        self.assertIn("工作清单", names)
        self.assertIn("个人", names)

    def test_list_tasks_reads_etag_uid_and_fields(self) -> None:
        vtodo = build_vtodo(
            uid="remote-1@nextcloud", title="远端任务", due_date="2026-12-02",
            completed=False,
        ).decode("utf-8")
        body = multistatus(
            task_response(
                "/remote.php/dav/calendars/synthetic-teacher/tasks/remote-1.ics",
                "etag-1",
                vtodo.replace("&", "&amp;").replace("<", "&lt;"),
            )
        )
        transport = FakeTransport(
            {
                (
                    "PROPFIND",
                    "/remote.php/dav/calendars/synthetic-teacher/tasks/",
                ): (207, {}, body)
            }
        )
        tasks = self._client(transport).list_tasks(
            "/remote.php/dav/calendars/synthetic-teacher/tasks/"
        )
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].uid, "remote-1@nextcloud")
        self.assertEqual(tasks[0].etag, "etag-1")
        self.assertEqual(tasks[0].title, "远端任务")
        self.assertEqual(tasks[0].due_date, "2026-12-02")
        self.assertFalse(tasks[0].completed)

    def test_put_create_uses_if_none_match_and_reads_etag(self) -> None:
        transport = FakeTransport()
        transport.answers[("PUT", "/remote.php/dav/calendars/t/x.ics")] = (
            201,
            {"etag": '"etag-new"'},
            b"",
        )
        etag = self._client(transport).put_task(
            "/remote.php/dav/calendars/t/x.ics",
            build_vtodo(uid="u@x", title="新任务", due_date=None, completed=False),
            etag=None,
        )
        self.assertEqual(etag, "etag-new")
        request = transport.requests[0]
        self.assertEqual(request["headers"].get("If-None-Match"), "*")
        self.assertIsNone(request["headers"].get("If-Match"))

    def test_put_edit_uses_if_match_and_412_is_a_conflict(self) -> None:
        transport = FakeTransport()
        transport.answers[("PUT", "/remote.php/dav/calendars/t/x.ics")] = (
            412,
            {},
            b"",
        )
        with self.assertRaises(TodoSyncError) as caught:
            self._client(transport).put_task(
                "/remote.php/dav/calendars/t/x.ics",
                build_vtodo(uid="u@x", title="编辑", due_date=None, completed=True),
                etag="etag-old",
            )
        self.assertEqual(caught.exception.code, "SYNC_PRECONDITION_FAILED")
        self.assertEqual(transport.requests[0]["headers"].get("If-Match"), '"etag-old"')

    def test_auth_and_redirect_and_oversize_answers_map_to_fixed_codes(self) -> None:
        auth = FakeTransport({("PROPFIND", DAV_ROOT_PATH): (401, {}, b"")})
        with self.assertRaises(TodoSyncError) as caught:
            self._client(auth).probe_connection()
        self.assertEqual(caught.exception.code, "SYNC_AUTH_FAILED")

        redirect = FakeTransport({("PROPFIND", DAV_ROOT_PATH): (302, {}, b"")})
        with self.assertRaises(TodoSyncError) as caught:
            self._client(redirect).probe_connection()
        self.assertEqual(caught.exception.code, "SYNC_RESPONSE_INVALID")

        broken = FakeTransport({("PROPFIND", DAV_ROOT_PATH): (207, {}, b"not-xml")})
        with self.assertRaises(TodoSyncError) as caught:
            self._client(broken).probe_connection()
        self.assertEqual(caught.exception.code, "SYNC_RESPONSE_INVALID")

        self.assertGreater(MAX_RESPONSE_BYTES, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
