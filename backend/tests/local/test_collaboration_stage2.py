"""Stage-2 desktop proxy tests without network, database, or real secrets."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from app.local.collaboration_proxy import (
    CollaborationProxy,
    PromotionIn,
    _endpoint_allowed,
    create_collaboration_proxy,
)
from app.local.errors import LocalError


SCHOOL_ID = UUID("11111111-1111-1111-1111-111111111111")
TEACHER_ID = UUID("22222222-2222-2222-2222-222222222222")
CLASS_ID = UUID("33333333-3333-3333-3333-333333333333")
TERM_ID = UUID("44444444-4444-4444-4444-444444444444")


def teacher_payload() -> dict:
    return {
        "teacher_id": str(TEACHER_ID),
        "display_name": "合成教师",
        "school_id": str(SCHOOL_ID),
        "school_name": "合成园",
    }


def membership_payload() -> dict:
    return {
        "teacher_id": str(TEACHER_ID),
        "school_id": str(SCHOOL_ID),
        "class_id": str(CLASS_ID),
        "class_name": "中一班",
        "selected_at": "2026-11-08T00:00:00+00:00",
    }


class Stage2ProxyTests(unittest.TestCase):
    def proxy(self) -> CollaborationProxy:
        return CollaborationProxy("https://collab.example")

    def test_endpoint_allowlist(self):
        self.assertTrue(_endpoint_allowed("POST", "/redeem"))
        self.assertTrue(_endpoint_allowed("GET", "/me/class/promotion"))
        self.assertTrue(_endpoint_allowed("POST", "/me/class/promotion"))
        self.assertTrue(
            _endpoint_allowed(
                "GET",
                f"/me/class/promotion/operations/{uuid4()}",
            )
        )
        self.assertFalse(_endpoint_allowed("POST", "/me"))
        self.assertFalse(
            _endpoint_allowed("GET", "/me/class/promotion/operations/not-a-uuid")
        )

    def test_packaged_release_origin_takes_priority_over_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "collaboration_release.json").write_text(
                json.dumps({"origin": "https://packaged.example/"}),
                encoding="utf-8",
            )
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "_MEIPASS", tmp, create=True),
                patch.dict(
                    os.environ,
                    {"APP_COLLABORATION_API_ORIGIN": "http://env-invalid"},
                    clear=False,
                ),
            ):
                proxy = create_collaboration_proxy()
                self.assertTrue(proxy.status().configured)
                self.assertEqual(proxy._origin, "https://packaged.example")
                self.assertEqual(
                    proxy._configuration_code, "COLLABORATION_READY"
                )

    def test_missing_packaged_file_keeps_environment_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "_MEIPASS", tmp, create=True),
                patch.dict(
                    os.environ,
                    {"APP_COLLABORATION_API_ORIGIN": "https://env.example"},
                    clear=False,
                ),
            ):
                proxy = create_collaboration_proxy()
                self.assertTrue(proxy.status().configured)
                self.assertEqual(proxy._origin, "https://env.example")

    def test_malformed_or_extra_packaged_config_fails_closed(self):
        for raw in (
            "{",
            json.dumps({"origin": "https://packaged.example", "secret": "x"}),
            json.dumps({"origin": "http://packaged.example"}),
            json.dumps({"origin": "https://packaged.example/path"}),
            json.dumps({"origin": 1}),
        ):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as tmp:
                Path(tmp, "collaboration_release.json").write_text(
                    raw, encoding="utf-8"
                )
                with (
                    patch.object(sys, "frozen", True, create=True),
                    patch.object(sys, "_MEIPASS", tmp, create=True),
                    patch.dict(
                        os.environ,
                        {"APP_COLLABORATION_API_ORIGIN": "https://env.example"},
                        clear=False,
                    ),
                ):
                    proxy = create_collaboration_proxy()
                    self.assertFalse(proxy.status().configured)
                    self.assertEqual(
                        proxy._configuration_code,
                        "COLLABORATION_ORIGIN_INVALID",
                    )

    def test_packaged_io_failure_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "collaboration_release.json").mkdir()
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "_MEIPASS", tmp, create=True),
                patch.dict(
                    os.environ,
                    {"APP_COLLABORATION_API_ORIGIN": "https://env.example"},
                    clear=False,
                ),
            ):
                proxy = create_collaboration_proxy()
                self.assertFalse(proxy.status().configured)
                self.assertEqual(
                    proxy._configuration_code, "COLLABORATION_ORIGIN_INVALID"
                )

    def test_source_mode_ignores_a_file_and_uses_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "collaboration_release.json").write_text(
                json.dumps({"origin": "https://packaged.example"}),
                encoding="utf-8",
            )
            with (
                patch.object(sys, "frozen", False, create=True),
                patch.object(sys, "_MEIPASS", tmp, create=True),
                patch.dict(
                    os.environ,
                    {"APP_COLLABORATION_API_ORIGIN": "https://env.example"},
                    clear=False,
                ),
            ):
                proxy = create_collaboration_proxy()
                self.assertEqual(proxy._origin, "https://env.example")

    def test_redeem_returns_no_token_and_join_has_no_membership(self):
        proxy = self.proxy()
        token = "synthetic-bearer-token"

        def send(generation, bearer, method, path, payload):
            self.assertEqual(method, "POST" if path == "/redeem" else "GET")
            if path == "/redeem":
                return {
                    "token": token,
                    "token_id": str(uuid4()),
                    "teacher_id": str(TEACHER_ID),
                    "teacher_name": "合成教师",
                    "school_id": str(SCHOOL_ID),
                    "school_name": "合成园",
                    "purpose": "join",
                    "membership": membership_payload(),
                }
            self.assertEqual(bearer, token)
            return teacher_payload()

        proxy._send = send  # type: ignore[method-assign]
        result = proxy.redeem("synthetic-code")
        self.assertEqual(result.purpose, "join")
        self.assertIsNone(result.membership)
        self.assertNotIn("token", result.model_dump())
        self.assertEqual(proxy._token, token)

    def test_redeem_recovery_returns_current_membership(self):
        proxy = self.proxy()
        token = "synthetic-bearer-token"

        def send(generation, bearer, method, path, payload):
            if path == "/redeem":
                return {
                    "token": token,
                    "token_id": str(uuid4()),
                    "teacher_id": str(TEACHER_ID),
                    "teacher_name": "合成教师",
                    "school_id": str(SCHOOL_ID),
                    "school_name": "合成园",
                    "purpose": "recovery",
                    "membership": membership_payload(),
                }
            return teacher_payload()

        proxy._send = send  # type: ignore[method-assign]
        result = proxy.redeem("synthetic-code")
        self.assertEqual(result.purpose, "recovery")
        self.assertIsNotNone(result.membership)
        self.assertEqual(str(result.membership.class_id), str(CLASS_ID))

    def test_redeem_identity_mismatch_is_rejected(self):
        proxy = self.proxy()

        def send(generation, bearer, method, path, payload):
            if path == "/redeem":
                return {
                    "token": "synthetic-bearer-token",
                    "token_id": str(uuid4()),
                    "teacher_id": str(TEACHER_ID),
                    "teacher_name": "合成教师",
                    "school_id": str(SCHOOL_ID),
                    "school_name": "合成园",
                    "purpose": "join",
                    "membership": None,
                }
            return {
                **teacher_payload(),
                "teacher_id": str(uuid4()),
            }

        proxy._send = send  # type: ignore[method-assign]
        with self.assertRaises(LocalError):
            proxy.redeem("synthetic-code")
        self.assertIsNone(proxy._token)

    def test_promotion_read_write_and_receipt(self):
        proxy = self.proxy()
        proxy._token = "synthetic-bearer-token"
        proxy._teacher = None
        calls = []
        overview = {
            "class_id": str(CLASS_ID),
            "class_name": "中一班",
            "grade": "middle",
            "version": 4,
            "terms": [
                {
                    "term_id": str(TERM_ID),
                    "name": "2026 秋季",
                    "start_date": "2026-09-01",
                    "end_date": "2027-01-31",
                }
            ],
        }
        result = {
            "request_id": str(uuid4()),
            "class_id": str(CLASS_ID),
            "class_name": "大四班",
            "grade": "large",
            "version": 5,
            "effective_term_id": str(TERM_ID),
            "replayed": False,
        }

        def send(generation, bearer, method, path, payload):
            calls.append((method, path, payload))
            if path == "/me/class/promotion":
                return overview if method == "GET" else {**result, "request_id": payload["request_id"]}
            return {**result, "request_id": path.rsplit("/", 1)[-1]}

        proxy._send = send  # type: ignore[method-assign]
        self.assertEqual(proxy.promotion().version, 4)
        body = PromotionIn(
            request_id=uuid4(),
            class_id=CLASS_ID,
            expected_version=4,
            target_grade="large",
            effective_term_id=TERM_ID,
        )
        promoted = proxy.promote(body)
        self.assertEqual(promoted.class_name, "大四班")
        operation = proxy.promotion_operation(body.request_id)
        self.assertEqual(operation.class_id, CLASS_ID)
        self.assertEqual(calls[1][:2], ("POST", "/me/class/promotion"))
        self.assertEqual(
            calls[2][:2],
            ("GET", f"/me/class/promotion/operations/{body.request_id}"),
        )


if __name__ == "__main__":
    unittest.main()
