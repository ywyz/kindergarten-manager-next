"""Synthetic local Word export tests for frozen online weekly confirmations."""

from __future__ import annotations

import io
import tempfile
import unittest
import uuid
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.local import daily_plan_service, profile_service, weekly_plan_service
from app.local import weekly_collaboration_export as export
from app.local.api import get_session
from app.local.errors import LocalError, LocalValidationError
from app.local.models import (
    LocalProfile,
    LocalSettings,
    LocalTerm,
    LocalWeeklyPlanContent,
)
from app.local.normalize import normalize_initialization
from app.local.runtime import LocalRuntime

ANCHOR = date(2026, 9, 7)
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _adopted() -> dict:
    return {
        "morning_talk": {"topic": "本地晨谈", "questions": "本地问题"},
        "group_activity": {"theme": "本地活动", "process": "本地过程"},
        "morning_games": [
            {
                "group_kind": "collective",
                "games": [{"name": "本地游戏"}],
                "shared_objectives": "本地目标",
                "guidance_points": "本地指导",
                "focus_guidance": "本地重点",
            }
        ],
        "post_group_games": [
            {
                "context_kind": "area",
                "area": "本地区域",
                "games": [{"name": "本地区域游戏"}],
                "objectives": "本地区域目标",
                "guidance": "本地区域指导",
                "support_strategy": "本地支持",
            }
        ],
    }


def _document_text(document: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(document)) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    return "".join(node.text or "" for node in root.iter(f"{_W}t"))


class FakeProxy:
    def __init__(self, confirmation: dict, *, error: Exception | None = None):
        self.confirmation = confirmation
        self.error = error
        self.calls: list[tuple] = []

    def weekly_confirmation(self, class_id, term_id, week_start, confirmation_id):
        self.calls.append((class_id, term_id, week_start, confirmation_id))
        if self.error is not None:
            raise self.error
        return self.confirmation


class WeeklyCollaborationExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="kgm-weekly-collab-export-")
        self.root = Path(self.temp.name)
        self.runtime = LocalRuntime(
            self.root / "data", credential_root=self.root / "credentials"
        )
        self.runtime.prepare()
        self.session = self.runtime.session()
        profile_service.initialize(
            self.session,
            normalize_initialization(
                request_id=str(uuid.uuid4()),
                display_name="合成教师",
                class_name="中一班",
                grade="middle",
                term_name="合成秋季",
                start_date=ANCHOR.isoformat(),
                end_date="2026-10-30",
                school_name="合成园所",
            ),
        )
        self.session.expire_all()
        self.profile = self.session.scalars(select(LocalProfile)).one()
        self.term = self.session.scalars(select(LocalTerm)).one()
        self.settings = self.session.get(LocalSettings, "singleton")
        self.manager = self.runtime.bind_weekly_exports(
            launch_id="launch-export", session_scope="scope-export"
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.session.close()
        self.runtime.dispose()
        self.temp.cleanup()

    def _local_plan(
        self,
        *,
        theme: str,
        materials: str,
        newer_theme: str | None = None,
    ) -> tuple[str, int]:
        daily_plan_service.create_or_open(
            self.session,
            plan_date=ANCHOR + timedelta(days=1),
            raw_lesson_plan=None,
            adopted_content=_adopted(),
        )
        preview = weekly_plan_service.create_preview(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.manager.launch_id,
            session_scope_hash=self.manager.session_scope_hash,
            term_id=self.term.id,
            week_anchor_date=ANCHOR,
        )
        result, _created = weekly_plan_service.create_or_open(
            self.session,
            runtime=self.runtime,
            profile_id=self.profile.id,
            launch_id=self.manager.launch_id,
            session_scope_hash=self.manager.session_scope_hash,
            request_id=str(uuid.uuid4()),
            term_id=self.term.id,
            week_anchor_date=ANCHOR,
            expected_config_version=self.settings.config_version,
            context_token=preview["create_token"],
        )
        plan_id = result["weekly_plan_id"]
        detail = weekly_plan_service.get_detail(
            self.session, profile_id=self.profile.id, plan_id=plan_id
        )
        saved = weekly_plan_service.save_draft(
            self.session,
            profile_id=self.profile.id,
            request_id=str(uuid.uuid4()),
            plan_id=plan_id,
            expected_draft_version=detail["draft"]["version"],
            patch={
                "theme": theme,
                "weekly_columns": {
                    "key_week_focus": "本地重点",
                    "environment_setup": "本地环境",
                    "habit_culture": "本地习惯",
                    "home_cooperation": "本地家长",
                },
            },
        )
        version = saved["draft"]["version"]
        if newer_theme is not None:
            weekly_plan_service.save_draft(
                self.session,
                profile_id=self.profile.id,
                request_id=str(uuid.uuid4()),
                plan_id=plan_id,
                expected_draft_version=version,
                patch={"theme": newer_theme},
            )
        content = self.session.scalars(
            select(LocalWeeklyPlanContent).where(
                LocalWeeklyPlanContent.weekly_plan_id == plan_id,
                LocalWeeklyPlanContent.version == version,
            )
        ).one()
        body = dict(content.content_json)
        body["materials"] = materials
        content.content_json = body
        self.session.commit()
        return plan_id, version

    def _confirmation(
        self,
        *,
        class_id: uuid.UUID,
        term_id: uuid.UUID,
        week_start: date,
        confirmation_id: uuid.UUID | None = None,
        class_name: str = "升班大一班",
        grade: str = "large",
    ) -> dict:
        confirmation_id = confirmation_id or uuid.uuid4()
        days = [
            {
                "date": (week_start + timedelta(days=offset)).isoformat(),
                "morning_talk_topic": f"共享晨谈{offset + 1}",
                "group_activity_theme": f"共享活动{offset + 1}",
            }
            for offset in range(5)
        ]
        return {
            "confirmation_id": str(confirmation_id),
            "confirmation_version": 4,
            "version": 9,
            "class_id": str(class_id),
            "term_id": str(term_id),
            "week_start": week_start.isoformat(),
            "class_name": class_name,
            "grade": grade,
            "term_name": "在线秋季",
            "content": {
                "days": days,
                "games": {
                    "collective_1": {
                        "name": "共享集体一",
                        "date": week_start.isoformat(),
                    },
                    "collective_2": {"name": "共享集体二", "date": None},
                    "free_choice_1": {
                        "name": "共享自主",
                        "date": (week_start + timedelta(days=1)).isoformat(),
                    },
                    "focus_area": {
                        "name": "共享重点区域",
                        "date": (week_start + timedelta(days=2)).isoformat(),
                    },
                },
            },
            "confirmed_by": str(uuid.uuid4()),
            "confirmed_at": "2026-09-07T08:00:00+00:00",
        }

    def _word_path(
        self,
        class_id: uuid.UUID,
        term_id: uuid.UUID,
        week_start: date,
        confirmation_id: uuid.UUID,
        *,
        plan_id: str | None = None,
        version: int | None = None,
    ) -> str:
        path = (
            f"/api/local/collaboration/classes/{class_id}/weekly/"
            f"{term_id}/{week_start.isoformat()}/confirmations/"
            f"{confirmation_id}/word"
        )
        if plan_id is not None:
            path += f"?weekly_plan_id={plan_id}&local_draft_version={version}"
        return path

    def _call(
        self,
        proxy: FakeProxy,
        *,
        class_id: uuid.UUID,
        term_id: uuid.UUID,
        week_start: date,
        confirmation_id: uuid.UUID,
        plan_id: str | None = None,
        version: int | None = None,
    ):
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(collaboration_proxy=proxy)
            )
        )
        return export.weekly_collaboration_word(
            str(class_id),
            str(term_id),
            week_start,
            str(confirmation_id),
            request,
            weekly_plan_id=plan_id,
            local_draft_version=version,
            session=self.session,
        )

    def test_shared_confirmation_and_local_supplement_are_separate(self) -> None:
        plan_id, version = self._local_plan(
            theme="本地主题",
            materials="本地材料清单",
            newer_theme="更新后的本地主题",
        )
        class_id = uuid.uuid4()
        term_id = uuid.uuid4()
        confirmation_id = uuid.uuid4()
        proxy = FakeProxy(
            self._confirmation(
                class_id=class_id,
                term_id=term_id,
                week_start=ANCHOR,
                confirmation_id=confirmation_id,
            )
        )
        response = self._call(
            proxy,
            class_id=class_id,
            term_id=term_id,
            week_start=ANCHOR,
            confirmation_id=confirmation_id,
            plan_id=plan_id,
            version=version,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.media_type, export.DOCX_MEDIA_TYPE)
        self.assertEqual(
            response.headers["x-weekly-confirmation-id"], str(confirmation_id)
        )
        self.assertEqual(
            response.headers["x-weekly-confirmation-version"], "4"
        )
        self.assertIn("v4.docx", response.headers["content-disposition"])
        self.assertIn(ANCHOR.isoformat(), response.headers["content-disposition"])
        self.assertIn("filename*=UTF-8''", response.headers["content-disposition"])
        self.assertNotIn(
            str(confirmation_id), response.headers["content-disposition"]
        )
        text = _document_text(response.body)
        self.assertIn("升班大一班", text)
        self.assertNotIn("中一班", text)
        self.assertIn("大班", text)
        for offset in range(5):
            self.assertIn(f"共享晨谈{offset + 1}", text)
            self.assertIn(f"共享活动{offset + 1}", text)
        self.assertIn("共享集体一", text)
        self.assertIn(ANCHOR.isoformat(), text)
        self.assertIn("共享集体二", text)
        self.assertIn("共享自主", text)
        self.assertIn((ANCHOR + timedelta(days=1)).isoformat(), text)
        self.assertIn("共享重点区域", text)
        self.assertNotIn("本地晨谈", text)
        self.assertNotIn("本地活动", text)
        self.assertIn("本地主题", text)
        self.assertNotIn("更新后的本地主题", text)
        self.assertIn("本地重点", text)
        self.assertIn("本地环境", text)
        self.assertIn("本地习惯", text)
        self.assertIn("本地家长", text)
        self.assertIn("本地材料清单", text)
        self.assertEqual(
            proxy.calls, [(class_id, term_id, ANCHOR, confirmation_id)]
        )

    def test_app_registers_the_export_router(self) -> None:
        source = (
            Path(__file__).resolve().parents[2] / "app/local/app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("weekly_collaboration_export_router", source)
        self.assertIn(
            "include_router(weekly_collaboration_export_router)", source
        )

    def test_router_path_returns_docx_over_http(self) -> None:
        plan_id, version = self._local_plan(
            theme="HTTP 本地主题", materials="HTTP 本地材料"
        )
        class_id = uuid.uuid4()
        term_id = uuid.uuid4()
        confirmation_id = uuid.uuid4()
        proxy = FakeProxy(
            self._confirmation(
                class_id=class_id,
                term_id=term_id,
                week_start=ANCHOR,
                confirmation_id=confirmation_id,
            )
        )
        app = FastAPI()
        app.state.collaboration_proxy = proxy
        app.include_router(export.router)
        app.dependency_overrides[get_session] = lambda: self.session
        client = TestClient(app)
        response = client.get(
            self._word_path(
                class_id,
                term_id,
                ANCHOR,
                confirmation_id,
                plan_id=plan_id,
                version=version,
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], export.DOCX_MEDIA_TYPE)
        self.assertEqual(_document_text(response.content).count("HTTP 本地主题"), 1)

    def test_sparse_nullable_days_fill_weekdays_and_keep_only_present_weekends(
        self,
    ) -> None:
        class_id = uuid.uuid4()
        term_id = uuid.uuid4()
        confirmation_id = uuid.uuid4()
        base = self._confirmation(
            class_id=class_id,
            term_id=term_id,
            week_start=ANCHOR,
            confirmation_id=confirmation_id,
            class_name="合成旧班名",
        )
        base["content"]["days"] = [
            {
                "date": (ANCHOR + timedelta(days=1)).isoformat(),
                "morning_talk_topic": "合成已确认晨谈",
                "group_activity_theme": None,
            }
        ]
        parsed = export._WeeklyConfirmation.model_validate(base)
        view = export._build_view(parsed, week_start=ANCHOR, local=None)
        self.assertEqual(
            [column["weekday"] for column in view["columns"]],
            [1, 2, 3, 4, 5],
        )
        self.assertEqual(view["columns"][1]["morning_talk_topic"], "合成已确认晨谈")
        self.assertEqual(view["columns"][1]["group_activity_theme"], "")
        for index in (0, 2, 3, 4):
            self.assertEqual(view["columns"][index]["morning_talk_topic"], "")
            self.assertEqual(view["columns"][index]["group_activity_theme"], "")
        text = _document_text(export.generate_weekly_export_docx([view]))
        self.assertIn("合成旧班名", text)
        self.assertIn("合成已确认晨谈", text)
        self.assertIn("共享集体一", text)
        self.assertIn((ANCHOR + timedelta(days=1)).isoformat(), text)
        self.assertIn("周一", text)
        self.assertIn("周五", text)
        self.assertNotIn("周六", text)
        self.assertNotIn("周日", text)
        self.assertNotIn("None", text)

        base["content"]["days"] = [
            {
                "date": ANCHOR.isoformat(),
                "morning_talk_topic": None,
                "group_activity_theme": "周六活动",
            },
            {
                "date": (ANCHOR + timedelta(days=5)).isoformat(),
                "morning_talk_topic": "周六晨谈",
                "group_activity_theme": None,
            },
        ]
        parsed = export._WeeklyConfirmation.model_validate(base)
        view = export._build_view(parsed, week_start=ANCHOR, local=None)
        self.assertEqual(
            [column["weekday"] for column in view["columns"]],
            [1, 2, 3, 4, 5, 6],
        )
        weekend_text = _document_text(
            export.generate_weekly_export_docx([view])
        )
        self.assertIn("周六", weekend_text)
        self.assertNotIn("周日", weekend_text)

        base["content"]["days"] = []
        parsed = export._WeeklyConfirmation.model_validate(base)
        view = export._build_view(parsed, week_start=ANCHOR, local=None)
        self.assertEqual(
            [column["weekday"] for column in view["columns"]],
            [1, 2, 3, 4, 5],
        )
        self.assertTrue(
            all(
                column["morning_talk_topic"] == ""
                and column["group_activity_theme"] == ""
                for column in view["columns"]
            )
        )
        _document_text(export.generate_weekly_export_docx([view]))

    def test_confirmation_only_does_not_use_local_fields(self) -> None:
        plan_id, version = self._local_plan(
            theme="不应出现的本地主题", materials="不应出现的本地材料"
        )
        class_id = uuid.uuid4()
        term_id = uuid.uuid4()
        confirmation_id = uuid.uuid4()
        proxy = FakeProxy(
            self._confirmation(
                class_id=class_id,
                term_id=term_id,
                week_start=ANCHOR,
                confirmation_id=confirmation_id,
            )
        )
        response = self._call(
            proxy,
            class_id=class_id,
            term_id=term_id,
            week_start=ANCHOR,
            confirmation_id=confirmation_id,
        )
        self.assertEqual(response.status_code, 200)
        text = _document_text(response.body)
        self.assertNotIn("不应出现的本地主题", text)
        self.assertNotIn("不应出现的本地材料", text)
        self.assertNotIn("中一班", text)
        self.assertIn("共享晨谈1", text)

    def test_wrong_local_week_version_or_confirmation_is_refused(self) -> None:
        plan_id, version = self._local_plan(theme="本地主题", materials="本地材料")
        class_id = uuid.uuid4()
        term_id = uuid.uuid4()
        confirmation_id = uuid.uuid4()
        next_week = ANCHOR + timedelta(days=7)
        proxy = FakeProxy(
            self._confirmation(
                class_id=class_id,
                term_id=term_id,
                week_start=next_week,
                confirmation_id=confirmation_id,
            )
        )
        with self.assertRaises(export.WeeklyCollaborationExportInvalid) as raised:
            self._call(
                proxy,
                class_id=class_id,
                term_id=term_id,
                week_start=next_week,
                confirmation_id=confirmation_id,
                plan_id=plan_id,
                version=version,
            )
        self.assertEqual(raised.exception.code, "WEEKLY_COLLABORATION_EXPORT_INVALID")

        matching_week_proxy = FakeProxy(
            self._confirmation(
                class_id=class_id,
                term_id=term_id,
                week_start=ANCHOR,
                confirmation_id=confirmation_id,
            )
        )
        with self.assertRaises(export.WeeklyCollaborationExportInvalid):
            self._call(
                matching_week_proxy,
                class_id=class_id,
                term_id=term_id,
                week_start=next_week,
                confirmation_id=confirmation_id,
            )

        proxy = FakeProxy(
            self._confirmation(
                class_id=class_id,
                term_id=term_id,
                week_start=ANCHOR,
                confirmation_id=confirmation_id,
            )
        )
        with self.assertRaises(LocalError) as raised:
            self._call(
                proxy,
                class_id=class_id,
                term_id=term_id,
                week_start=ANCHOR,
                confirmation_id=confirmation_id,
                plan_id=plan_id,
                version=version + 1,
            )
        self.assertEqual(raised.exception.code, "WEEKLY_EXPORT_NOT_FOUND")

        other_confirmation = uuid.uuid4()
        proxy = FakeProxy(
            self._confirmation(
                class_id=class_id,
                term_id=term_id,
                week_start=ANCHOR,
                confirmation_id=other_confirmation,
            )
        )
        with self.assertRaises(export.WeeklyCollaborationExportInvalid):
            self._call(
                proxy,
                class_id=class_id,
                term_id=term_id,
                week_start=ANCHOR,
                confirmation_id=confirmation_id,
            )

    def test_one_local_query_parameter_is_refused(self) -> None:
        class_id = uuid.uuid4()
        term_id = uuid.uuid4()
        confirmation_id = uuid.uuid4()
        proxy = FakeProxy(
            self._confirmation(
                class_id=class_id,
                term_id=term_id,
                week_start=ANCHOR,
                confirmation_id=confirmation_id,
            )
        )
        with self.assertRaises(LocalValidationError):
            self._call(
                proxy,
                class_id=class_id,
                term_id=term_id,
                week_start=ANCHOR,
                confirmation_id=confirmation_id,
                plan_id="missing-only",
            )
