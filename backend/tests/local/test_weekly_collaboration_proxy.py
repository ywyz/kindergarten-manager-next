"""Stage-3 weekly collaboration proxy allowlist and public-read tests (no DB/net)."""

from __future__ import annotations

import unittest
from datetime import date
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.local.collaboration_proxy import (
    ClassmateOut,
    CollaborationProxy,
    WeeklyConfirmIn,
    WeeklySaveIn,
    _endpoint_allowed,
    collaboration_router,
)

CLASS_ID = UUID("11111111-1111-1111-1111-111111111111")
TERM_ID = UUID("22222222-2222-2222-2222-222222222222")
CONFIRM_ID = UUID("33333333-3333-3333-3333-333333333333")
WEEK = date(2026, 11, 9)


def content() -> dict:
    return {
        "days": [
            {
                "date": "2026-11-09",
                "morning_talk_topic": "晨谈",
                "group_activity_theme": "集体活动",
            }
        ],
        "games": {
            "collective_1": {"name": "集体一", "date": "2026-11-09"},
            "collective_2": None,
            "free_choice_1": {"name": "自选", "date": None},
            "focus_area": None,
        },
    }


def confirmation() -> dict:
    return {
        "confirmation_id": str(CONFIRM_ID),
        "confirmation_version": 2,
        "version": 2,
        "class_id": str(CLASS_ID),
        "term_id": str(TERM_ID),
        "week_start": WEEK.isoformat(),
        "class_name": "中一班",
        "grade": "middle",
        "term_name": "合成学期",
        "content": content(),
        "confirmed_by": "合成教师",
        "confirmed_at": "2026-11-09T08:00:00+08:00",
    }


def shared() -> dict:
    return {
        "class_id": str(CLASS_ID),
        "term_id": str(TERM_ID),
        "week_start": WEEK.isoformat(),
        "class_name": "中一班",
        "term_name": "合成学期",
        "version": 2,
        "content": content(),
        "confirmation": confirmation(),
    }


class WeeklyProxyTests(unittest.TestCase):
    def proxy(self) -> CollaborationProxy:
        proxy = CollaborationProxy("https://collab.example")
        proxy._token = "synthetic-bearer"
        return proxy

    def test_exact_route_allowlist(self):
        base = f"/classes/{CLASS_ID}/weekly/{TERM_ID}/{WEEK.isoformat()}"
        self.assertTrue(_endpoint_allowed("GET", base))
        self.assertTrue(_endpoint_allowed("POST", f"{base}/save"))
        self.assertTrue(_endpoint_allowed("POST", f"{base}/confirm"))
        self.assertTrue(_endpoint_allowed("GET", f"{base}/confirmations/{CONFIRM_ID}"))
        self.assertTrue(_endpoint_allowed("GET", f"{base}/operations/{uuid4()}"))
        self.assertFalse(_endpoint_allowed("POST", base))
        self.assertFalse(_endpoint_allowed("GET", f"{base}/word"))
        self.assertFalse(_endpoint_allowed("GET", f"{base}/operations/not-a-uuid"))
        self.assertFalse(
            _endpoint_allowed("GET", f"/classes/{CLASS_ID}/weekly/not-a-term/{WEEK}/")
        )

    def test_public_confirmation_returns_sanitized_dict(self):
        proxy = self.proxy()
        calls = []

        def send(generation, bearer, method, path, payload):
            calls.append((method, path, payload))
            self.assertEqual(bearer, "synthetic-bearer")
            return confirmation()

        proxy._send = send  # type: ignore[method-assign]
        result = proxy.weekly_confirmation(CLASS_ID, TERM_ID, WEEK, CONFIRM_ID)
        self.assertEqual(result["confirmation_id"], str(CONFIRM_ID))
        self.assertEqual(result["content"], content())
        self.assertEqual(calls[0][:2], (
            "GET",
            f"/classes/{CLASS_ID}/weekly/{TERM_ID}/{WEEK}/confirmations/{CONFIRM_ID}",
        ))

    def test_save_confirm_and_operation_shapes(self):
        proxy = self.proxy()
        calls = []

        def send(generation, bearer, method, path, payload):
            calls.append((method, path, payload))
            if path.endswith("/save"):
                return {**shared(), "request_id": payload["request_id"], "replayed": False}
            if path.endswith("/confirm"):
                return {
                    **confirmation(),
                    "request_id": payload["request_id"],
                    "replayed": False,
                }
            return {
                "request_id": str(uuid4()),
                "kind": "save",
                "result": {**shared(), "request_id": str(uuid4()), "replayed": False},
            }

        proxy._send = send  # type: ignore[method-assign]
        body = WeeklySaveIn(
            request_id=uuid4(),
            expected_version=1,
            content=content(),
        )
        saved = proxy.save_weekly(CLASS_ID, TERM_ID, WEEK, body)
        self.assertEqual(saved.class_id, CLASS_ID)
        confirmed = proxy.confirm_weekly(
            CLASS_ID,
            TERM_ID,
            WEEK,
            WeeklyConfirmIn(request_id=uuid4(), expected_version=2),
        )
        self.assertEqual(confirmed.confirmation_id, CONFIRM_ID)
        operation = proxy.weekly_operation(CLASS_ID, TERM_ID, WEEK, uuid4())
        self.assertEqual(operation.kind, "save")
        self.assertEqual(calls[0][:2], (
            "POST",
            f"/classes/{CLASS_ID}/weekly/{TERM_ID}/{WEEK}/save",
        ))

    def test_classmates_route_is_actually_mounted(self):
        class FakeProxy:
            def classmates(self):
                return [
                    ClassmateOut(
                        teacher_id=UUID("44444444-4444-4444-4444-444444444444"),
                        display_name="合成同班老师",
                        config_version=3,
                        config_updated_at=None,
                    )
                ]

        app = FastAPI()
        app.state.collaboration_proxy = FakeProxy()
        app.include_router(collaboration_router)
        client = TestClient(app)
        response = client.get("/api/local/collaboration/classmates")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()[0]["display_name"], "合成同班老师")
        self.assertEqual(response.json()[0]["config_version"], 3)
        paths = {
            route.path
            for route in collaboration_router.routes
            if "GET" in getattr(route, "methods", set())
        }
        self.assertIn("/api/local/collaboration/classmates", paths)

    def test_sparse_wire_nulls_are_normalized_for_read_save_and_operation(self):
        from app.local.collaboration_proxy import (
            WeeklyConfirmOut,
            WeeklyOperationOut,
            WeeklySaveOut,
            WeeklySharedOut,
        )

        sparse = content()
        sparse["days"] = [
            {
                "date": "2026-11-09",
                "morning_talk_topic": None,
                "group_activity_theme": None,
            },
            {
                "date": "2026-11-10",
                "morning_talk_topic": "周二晨谈",
                "group_activity_theme": "周二集体",
            },
        ]
        read = WeeklySharedOut.model_validate({**shared(), "content": sparse})
        self.assertEqual(read.content.days[0].morning_talk_topic, "")
        self.assertEqual(read.content.days[0].group_activity_theme, "")
        self.assertEqual(read.content.days[1].morning_talk_topic, "周二晨谈")
        self.assertEqual(
            read.content.games.collective_1.name,
            "集体一",
        )
        saved = WeeklySaveOut.model_validate({
            **shared(),
            "content": sparse,
            "request_id": str(uuid4()),
            "replayed": False,
        })
        self.assertEqual(saved.content.days[0].morning_talk_topic, "")
        confirmed = WeeklyConfirmOut.model_validate({
            **confirmation(),
            "content": sparse,
            "request_id": str(uuid4()),
            "replayed": False,
        })
        self.assertEqual(confirmed.content.days[0].group_activity_theme, "")
        operation = WeeklyOperationOut.model_validate({
            "request_id": str(uuid4()),
            "kind": "save",
            "result": {
                **shared(),
                "content": sparse,
                "request_id": str(uuid4()),
                "replayed": False,
            },
        })
        self.assertEqual(operation.result.content.days[0].morning_talk_topic, "")

    def test_local_ids_are_not_in_weekly_content_contract(self):
        from app.local.collaboration_proxy import SharedContent

        parsed = SharedContent.model_validate(content())
        self.assertEqual(set(parsed.model_dump()), {"days", "games"})
        self.assertEqual(
            set(parsed.model_dump()["games"]),
            {"collective_1", "collective_2", "free_choice_1", "focus_area"},
        )
        with self.assertRaises(Exception):
            SharedContent.model_validate(
                {**content(), "weekly_plan_id": "local-plan"}
            )


if __name__ == "__main__":
    unittest.main()
