"""Shared weekly-plan slice tests without a real database.

The local suite uses the same isolated in-memory SQLite schema pattern as the
promotion tests to exercise authorization, versioning, confirmation freezing
and request receipts.  A separate opt-in class runs the same service on an
explicit ``KGM_COLLAB_TEST_DATABASE_URL`` after 0001-0004 have been applied.
It never creates a database or applies a migration.
"""

from __future__ import annotations

import os
import threading
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.dialects.mysql import dialect as mysql_dialect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.collaboration.app import create_collaboration_app
from app.collaboration.class_promotion_models import (
    ClassPromotionHistory,
    ClassPromotionState,
    CollaborationTerm,
)
from app.collaboration.config import CollaborationSettings
from app.collaboration.db import create_collaboration_engine
from app.collaboration.errors import CollaborationError
from app.collaboration.models import (
    Classroom,
    School,
    Teacher,
    TeacherClassMembership,
)
from app.collaboration.security import TeacherPrincipal
from app.collaboration.weekly_plan_models import (
    WeeklyPlanConfirmation,
    WeeklyPlanOperation,
    WeeklyPlanWeek,
)
from app.collaboration.weekly_plan_schemas import (
    WeeklyConfirmIn,
    WeeklyConfirmOut,
    WeeklyConfirmationOut,
    WeeklyOperationOut,
    WeeklyReadOut,
    WeeklySaveIn,
    WeeklySaveOut,
)
from app.collaboration.weekly_plan_service import (
    GAME_KEYS,
    confirm_weekly_plan,
    get_confirmation,
    get_operation,
    get_weekly_plan,
    normalize_content,
    save_weekly_plan,
)

PEPPER = "synthetic-weekly-pepper-0123456789abcdef"
PREVIEW = "synthetic-weekly-preview-0123456789abcdef"
BACKEND = Path(__file__).resolve().parents[2]

TERM_START = date(2026, 9, 1)
TERM_END = date(2027, 1, 31)
WEEK = date(2026, 11, 2)
PARTIAL_START = date(2026, 11, 4)
PARTIAL_END = date(2026, 11, 20)
SHORT_START = date(2026, 10, 26)
SHORT_END = date(2026, 11, 4)
FUTURE_START = date(2027, 2, 1)
FUTURE_END = date(2027, 6, 30)
FUTURE_WEEK = date(2027, 2, 1)


def _settings(url: str) -> CollaborationSettings:
    return CollaborationSettings(
        database_url=url,
        token_pepper=PEPPER,
        preview_secret=PREVIEW,
    )


def _principal(
    teacher_id: UUID, school_id: UUID, name: str = "合成教师"
) -> TeacherPrincipal:
    return TeacherPrincipal(
        teacher_id=teacher_id,
        school_id=school_id,
        display_name=name,
        school_name="合成幼儿园",
        token_id=uuid4(),
    )


def _empty_games() -> dict:
    return {key: None for key in GAME_KEYS}


def _content(days=None, games=None) -> dict:
    return {
        "days": list(days or []),
        "games": _empty_games() if games is None else games,
    }


def _day(value: date | str, talk=None, theme=None) -> dict:
    return {
        "date": value.isoformat() if isinstance(value, date) else value,
        "morning_talk_topic": talk,
        "group_activity_theme": theme,
    }


def _create_sqlite_schema(engine) -> None:
    tables = (
        School.__table__,
        Classroom.__table__,
        Teacher.__table__,
        TeacherClassMembership.__table__,
        CollaborationTerm.__table__,
        ClassPromotionState.__table__,
        ClassPromotionHistory.__table__,
        WeeklyPlanWeek.__table__,
        WeeklyPlanConfirmation.__table__,
        WeeklyPlanOperation.__table__,
    )
    with engine.begin() as connection:
        for table in tables:
            ddl = str(CreateTable(table).compile(dialect=engine.dialect))
            # SQLite has no CURRENT_TIMESTAMP(6) spelling; business values in
            # these tests are supplied explicitly by the service.
            ddl = ddl.replace("CURRENT_TIMESTAMP(6)", "CURRENT_TIMESTAMP")
            connection.exec_driver_sql(ddl)


class WeeklyPlanSQLiteUnitTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def _register_char_length(dbapi_connection, _record):
            dbapi_connection.create_function("char_length", 1, len)

        _create_sqlite_schema(self.engine)
        self.Session = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )
        self.school_id = uuid4()
        self.class_id = uuid4()
        self.other_class_id = uuid4()
        self.teacher_a = uuid4()
        self.teacher_b = uuid4()
        self.outsider = uuid4()
        self.without_membership = uuid4()
        self.term_id = uuid4()
        self.partial_term_id = uuid4()
        self.short_term_id = uuid4()
        self.future_term_id = uuid4()
        now = datetime.now(timezone.utc)
        with self.Session() as session:
            with session.begin():
                session.add(School(id=self.school_id, name="合成幼儿园"))
                session.flush()
                session.add_all(
                    [
                        Classroom(
                            id=self.class_id,
                            school_id=self.school_id,
                            display_name="合成班",
                        ),
                        Classroom(
                            id=self.other_class_id,
                            school_id=self.school_id,
                            display_name="合成二班",
                        ),
                        Teacher(
                            id=self.teacher_a,
                            school_id=self.school_id,
                            display_name="合成教师甲",
                            active=True,
                        ),
                        Teacher(
                            id=self.teacher_b,
                            school_id=self.school_id,
                            display_name="合成教师乙",
                            active=True,
                        ),
                        Teacher(
                            id=self.outsider,
                            school_id=self.school_id,
                            display_name="合成教师丙",
                            active=True,
                        ),
                        Teacher(
                            id=self.without_membership,
                            school_id=self.school_id,
                            display_name="合成教师丁",
                            active=True,
                        ),
                    ]
                )
                session.flush()
                session.add_all(
                    [
                        TeacherClassMembership(
                            teacher_id=self.teacher_a,
                            school_id=self.school_id,
                            class_id=self.class_id,
                            membership_generation=uuid4(),
                            selected_at=now,
                            updated_at=now,
                        ),
                        TeacherClassMembership(
                            teacher_id=self.teacher_b,
                            school_id=self.school_id,
                            class_id=self.class_id,
                            membership_generation=uuid4(),
                            selected_at=now,
                            updated_at=now,
                        ),
                        TeacherClassMembership(
                            teacher_id=self.outsider,
                            school_id=self.school_id,
                            class_id=self.other_class_id,
                            membership_generation=uuid4(),
                            selected_at=now,
                            updated_at=now,
                        ),
                        CollaborationTerm(
                            id=self.term_id,
                            school_id=self.school_id,
                            name="秋季学期",
                            start_date=TERM_START,
                            end_date=TERM_END,
                        ),
                        CollaborationTerm(
                            id=self.partial_term_id,
                            school_id=self.school_id,
                            name="周中开学学期",
                            start_date=PARTIAL_START,
                            end_date=PARTIAL_END,
                        ),
                        CollaborationTerm(
                            id=self.short_term_id,
                            school_id=self.school_id,
                            name="周中结束学期",
                            start_date=SHORT_START,
                            end_date=SHORT_END,
                        ),
                        CollaborationTerm(
                            id=self.future_term_id,
                            school_id=self.school_id,
                            name="春季学期",
                            start_date=FUTURE_START,
                            end_date=FUTURE_END,
                        ),
                        ClassPromotionState(
                            class_id=self.class_id,
                            school_id=self.school_id,
                            class_number=1,
                            base_grade="small",
                            version=1,
                        ),
                        ClassPromotionState(
                            class_id=self.other_class_id,
                            school_id=self.school_id,
                            class_number=2,
                            base_grade="small",
                            version=1,
                        ),
                    ]
                )

    def _teacher_a(self) -> TeacherPrincipal:
        return _principal(self.teacher_a, self.school_id, "合成教师甲")

    def _teacher_b(self) -> TeacherPrincipal:
        return _principal(self.teacher_b, self.school_id, "合成教师乙")

    def _read(
        self,
        *,
        week: date = WEEK,
        term_id: UUID | None = None,
        principal: TeacherPrincipal | None = None,
    ) -> dict:
        with self.Session() as session:
            return get_weekly_plan(
                session,
                principal or self._teacher_a(),
                self.class_id,
                self.term_id if term_id is None else term_id,
                week,
            )

    def _save(
        self,
        content: dict,
        *,
        expected_version: int = 0,
        request_id: UUID | None = None,
        week: date = WEEK,
        term_id: UUID | None = None,
        principal: TeacherPrincipal | None = None,
    ) -> dict:
        with self.Session() as session:
            return save_weekly_plan(
                session,
                principal or self._teacher_a(),
                self.class_id,
                self.term_id if term_id is None else term_id,
                week,
                request_id=request_id or uuid4(),
                expected_version=expected_version,
                content=content,
            )

    def _confirm(
        self,
        *,
        expected_version: int,
        request_id: UUID | None = None,
        week: date = WEEK,
        term_id: UUID | None = None,
        principal: TeacherPrincipal | None = None,
    ) -> dict:
        with self.Session() as session:
            return confirm_weekly_plan(
                session,
                principal or self._teacher_a(),
                self.class_id,
                self.term_id if term_id is None else term_id,
                week,
                request_id=request_id or uuid4(),
                expected_version=expected_version,
            )

    def _assert_code(self, code: str, callback):
        with self.assertRaises(CollaborationError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_save_normalizes_sorted_days_and_rejects_unshared_fields(self):
        content = _content(
            days=[
                _day(date(2026, 11, 6), "  周五晨谈  ", " 周五主题 "),
                _day(date(2026, 11, 3), "", None),
            ],
            games={
                "collective_1": {"name": " 接力赛 ", "date": "2026-11-03"},
                "collective_2": None,
                "free_choice_1": {"name": "积木"},
                "focus_area": {"name": "美工区", "date": None},
            },
        )
        request_id = uuid4()
        saved = self._save(content, request_id=request_id)
        self.assertEqual(saved["version"], 1)
        self.assertEqual(WeeklySaveOut.model_validate(saved).version, 1)
        self.assertEqual(saved["class_name"], "小一班")
        self.assertEqual(saved["term_name"], "秋季学期")
        self.assertIsNone(saved["confirmation"])
        self.assertEqual(saved["request_id"], str(request_id))
        self.assertFalse(saved["replayed"])
        self.assertEqual(
            [item["date"] for item in saved["content"]["days"]],
            ["2026-11-03", "2026-11-06"],
        )
        self.assertIsNone(saved["content"]["days"][0]["morning_talk_topic"])
        self.assertEqual(
            saved["content"]["days"][1]["morning_talk_topic"], "周五晨谈"
        )
        self.assertEqual(
            saved["content"]["games"]["collective_1"],
            {"name": "接力赛", "date": "2026-11-03"},
        )
        self.assertEqual(
            saved["content"]["games"]["free_choice_1"],
            {"name": "积木", "date": None},
        )
        self.assertEqual(set(saved["content"]), {"days", "games"})
        self.assertEqual(set(saved["content"]["days"][0]), {
            "date", "morning_talk_topic", "group_activity_theme"
        })

        with self.Session() as session:
            read = get_weekly_plan(
                session, self._teacher_a(), self.class_id, self.term_id, WEEK
            )
        self.assertEqual(read["version"], 1)
        self.assertEqual(read["content"], saved["content"])

        bad_contents = {
            "top_level_material": _content() | {"materials": ["未共享材料"]},
            "day_lesson_body": _content(
                days=[
                    _day(WEEK)
                    | {"group_activity_process": "集体活动正文"}
                ]
            ),
            "day_source_id": _content(
                days=[_day(WEEK) | {"daily_plan_id": str(uuid4())}]
            ),
            "game_source_id": _content(
                games=_empty_games()
                | {"collective_1": {"name": "接力赛", "source_id": "x"}}
            ),
            "games_extra_slot": _content(
                games=_empty_games() | {"extra_slot": None}
            ),
            "photo": _content() | {"photos": ["synthetic.jpg"]},
        }
        for label, bad in bad_contents.items():
            with self.subTest(label=label):
                self._assert_code(
                    "WEEKLY_PLAN_INVALID",
                    lambda bad=bad: self._save(bad, expected_version=1),
                )

    def test_day_count_duplicates_and_week_term_rules(self):
        seven_days = [
            _day(WEEK + timedelta(days=offset)) for offset in range(7)
        ]
        saved = self._save(_content(days=seven_days))
        self.assertEqual(saved["version"], 1)
        self.assertEqual(len(saved["content"]["days"]), 7)

        self._assert_code(
            "WEEKLY_PLAN_INVALID",
            lambda: self._save(
                _content(
                    days=[
                        _day(WEEK + timedelta(days=offset))
                        for offset in range(8)
                    ]
                )
            ),
        )
        self._assert_code(
            "WEEKLY_PLAN_INVALID",
            lambda: self._save(
                _content(days=[_day(WEEK), _day(WEEK), _day(WEEK + timedelta(days=1))])
            ),
        )
        # Not a Monday, even though the week containing it intersects a term.
        self._assert_code(
            "WEEKLY_PLAN_INVALID",
            lambda: self._save(_content(days=[_day(date(2026, 11, 3))]), week=date(2026, 11, 3)),
        )
        # Day outside the requested week but inside the term.
        self._assert_code(
            "WEEKLY_PLAN_INVALID",
            lambda: self._save(_content(days=[_day(date(2026, 11, 1))])),
        )
        # Game date outside the requested week but inside the term.
        self._assert_code(
            "WEEKLY_PLAN_INVALID",
            lambda: self._save(
                _content(
                    games=_empty_games()
                    | {"collective_1": {"name": "接力赛", "date": "2026-11-09"}}
                )
            ),
        )
        # Week entirely before the term.
        self._assert_code(
            "WEEKLY_PLAN_INVALID",
            lambda: self._save(_content(), week=date(2026, 8, 24)),
        )
        # Week entirely after the term.
        self._assert_code(
            "WEEKLY_PLAN_INVALID",
            lambda: self._save(_content(), week=FUTURE_WEEK),
        )

        # The week starts before this term but Wednesday is the first date
        # inside both the week and the term.
        partial = self._save(
            _content(days=[_day(PARTIAL_START)]),
            term_id=self.partial_term_id,
        )
        self.assertEqual(partial["class_name"], "小一班")
        self._assert_code(
            "WEEKLY_PLAN_INVALID",
            lambda: self._save(
                _content(days=[_day(date(2026, 11, 3))]),
                term_id=self.partial_term_id,
            ),
        )
        self._assert_code(
            "WEEKLY_PLAN_INVALID",
            lambda: self._save(
                _content(days=[_day(PARTIAL_START)]),
                week=date(2026, 10, 26),
                term_id=self.partial_term_id,
            ),
        )
        # The week ends after this term; the term end is the last valid date.
        short = self._save(
            _content(days=[_day(SHORT_END)]),
            term_id=self.short_term_id,
        )
        self.assertEqual(short["class_name"], "小一班")
        self._assert_code(
            "WEEKLY_PLAN_INVALID",
            lambda: self._save(
                _content(days=[_day(date(2026, 11, 5))]),
                term_id=self.short_term_id,
            ),
        )

    def test_week_first_date_inside_term_selects_frozen_name_and_grade(self):
        with self.Session() as session:
            with session.begin():
                session.add(
                    ClassPromotionHistory(
                        id=uuid4(),
                        class_id=self.class_id,
                        school_id=self.school_id,
                        term_id=self.partial_term_id,
                        grade="middle",
                        version_after=2,
                    )
                )
        # Both reads use the same Monday, but each term resolves the first
        # date that is actually inside that term.
        self.assertEqual(self._read()["class_name"], "小一班")
        partial_read = self._read(
            week=WEEK, term_id=self.partial_term_id
        )
        self.assertEqual(partial_read["class_name"], "中一班")
        saved = self._save(
            _content(days=[_day(PARTIAL_START)]),
            term_id=self.partial_term_id,
        )
        self.assertEqual(saved["class_name"], "中一班")
        confirmed = self._confirm(
            expected_version=1, term_id=self.partial_term_id
        )
        self.assertEqual(confirmed["class_name"], "中一班")
        self.assertEqual(confirmed["grade"], "middle")

    def test_version_zero_replay_and_stale_conflict(self):
        empty = self._read()
        self.assertEqual(empty["version"], 0)
        self.assertEqual(empty["content"], _content())
        self.assertIsNone(empty["confirmation"])
        self.assertEqual(
            WeeklyReadOut.model_validate(empty).content.days, []
        )

        request_id = uuid4()
        first = self._save(
            _content(days=[_day(WEEK, "第一版晨谈")]),
            request_id=request_id,
        )
        self.assertEqual(first["version"], 1)
        replay = self._save(
            _content(days=[_day(WEEK, "第一版晨谈")]),
            expected_version=0,
            request_id=request_id,
        )
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["version"], 1)
        self.assertEqual(replay["content"], first["content"])

        second_id = uuid4()
        second = self._save(
            _content(days=[_day(WEEK, "第二版晨谈")]),
            expected_version=1,
            request_id=second_id,
        )
        self.assertEqual(second["version"], 2)

        stale = self._assert_code(
            "WEEKLY_PLAN_VERSION_CONFLICT",
            lambda: self._save(_content(), expected_version=0),
        )
        self.assertEqual(stale.details["current_version"], 2)
        stale_again = self._assert_code(
            "WEEKLY_PLAN_VERSION_CONFLICT",
            lambda: self._save(_content(), expected_version=1),
        )
        self.assertEqual(stale_again.details["current_version"], 2)

        self._assert_code(
            "REQUEST_CONFLICT",
            lambda: self._save(
                _content(days=[_day(WEEK, "换内容")]),
                expected_version=1,
                request_id=second_id,
            ),
        )

        not_saved = self._assert_code(
            "WEEKLY_PLAN_NOT_SAVED",
            lambda: self._confirm(
                expected_version=0,
                week=FUTURE_WEEK,
                term_id=self.future_term_id,
            ),
        )
        self.assertEqual(not_saved.status_code, 409)
        self._assert_code(
            "WEEKLY_PLAN_VERSION_CONFLICT",
            lambda: self._confirm(expected_version=1),
        )
        confirmed = self._confirm(expected_version=2)
        self.assertEqual(confirmed["version"], 2)
        self.assertEqual(confirmed["confirmation_version"], 1)
        self.assertEqual(
            confirmed["content"],
            _content(days=[_day(WEEK, "第二版晨谈")]),
        )

    def test_read_caps_confirmation_to_the_draft_version_read(self):
        first = self._save(_content(days=[_day(WEEK, "第一版")]))
        self.assertEqual(first["version"], 1)
        self._confirm(expected_version=1)

        second = self._save(
            _content(days=[_day(WEEK, "第二版")]), expected_version=1
        )
        self.assertEqual(second["version"], 2)
        self._confirm(expected_version=2)

        third = self._save(
            _content(days=[_day(WEEK, "第三版")]), expected_version=2
        )
        self.assertEqual(third["version"], 3)

        # Simulate the observed read race state: the draft read below is
        # version 3, while a concurrently committed confirmation for version
        # 4 already exists.  The cap must keep the pair at (3, 2).
        future_content = _content(days=[_day(WEEK, "未来第四版")])
        no_draft_week = WEEK + timedelta(days=7)
        with self.Session() as session:
            with session.begin():
                session.add(
                    WeeklyPlanConfirmation(
                        id=uuid4(),
                        class_id=self.class_id,
                        school_id=self.school_id,
                        term_id=self.term_id,
                        week_start=WEEK,
                        confirmation_version=3,
                        version=4,
                        class_name="中一班",
                        grade="middle",
                        term_name="秋季学期",
                        content=future_content,
                        confirmed_by=self.teacher_b,
                        confirmed_at=datetime.now(timezone.utc),
                    )
                )
                session.add(
                    WeeklyPlanConfirmation(
                        id=uuid4(),
                        class_id=self.class_id,
                        school_id=self.school_id,
                        term_id=self.term_id,
                        week_start=no_draft_week,
                        confirmation_version=1,
                        version=1,
                        class_name="小一班",
                        grade="small",
                        term_name="秋季学期",
                        content=_content(days=[_day(no_draft_week, "无稿确认")]),
                        confirmed_by=self.teacher_b,
                        confirmed_at=datetime.now(timezone.utc),
                    )
                )

        result = self._read()
        self.assertEqual(result["version"], 3)
        self.assertEqual(result["confirmation"]["version"], 2)
        self.assertEqual(result["confirmation"]["confirmation_version"], 2)
        self.assertEqual(result["confirmation"]["content"], second["content"])
        self.assertLessEqual(
            result["confirmation"]["version"], result["version"]
        )

        # A confirmation without a draft row is never exposed as a draft.
        no_draft = self._read(week=no_draft_week)
        self.assertEqual(no_draft["version"], 0)
        self.assertIsNone(no_draft["confirmation"])
        self.assertEqual(no_draft["content"], _content())

    def test_class_name_is_built_from_the_single_grade_read(self):
        with patch(
            "app.collaboration.weekly_plan_service.latest_grade_at_date",
            return_value="middle",
        ) as grade_mock:
            read = self._read()
        self.assertEqual(read["class_name"], "中一班")
        self.assertEqual(grade_mock.call_count, 1)

    def test_class_without_stage_two_state_and_missing_term_are_rejected(self):
        new_class_id = uuid4()
        with self.Session() as session:
            with session.begin():
                session.add(
                    Classroom(
                        id=new_class_id,
                        school_id=self.school_id,
                        display_name="未登记班",
                    )
                )
                membership = session.get(
                    TeacherClassMembership, self.teacher_a
                )
                membership.class_id = new_class_id
        with self.Session() as session:
            with self.assertRaises(CollaborationError) as not_ready:
                get_weekly_plan(
                    session,
                    self._teacher_a(),
                    new_class_id,
                    self.term_id,
                    WEEK,
                )
        self.assertEqual(
            not_ready.exception.code, "CLASS_PROMOTION_NOT_READY"
        )

        with self.Session() as session:
            with self.assertRaises(CollaborationError) as missing_term:
                get_weekly_plan(
                    session,
                    self._teacher_b(),
                    self.class_id,
                    uuid4(),
                    WEEK,
                )
        self.assertEqual(missing_term.exception.code, "TERM_NOT_FOUND")

    def test_reads_and_writes_require_current_same_class_membership(self):
        self.assertEqual(
            self._read(principal=self._teacher_b())["version"], 0
        )
        self._assert_code(
            "MEMBERSHIP_CHANGED",
            lambda: self._read(
                principal=_principal(self.outsider, self.school_id)
            ),
        )
        self._assert_code(
            "CLASS_NOT_SELECTED",
            lambda: self._read(
                principal=_principal(self.without_membership, self.school_id)
            ),
        )
        self._assert_code(
            "CLASS_NOT_FOUND",
            lambda: self._read(
                principal=_principal(self.teacher_b, uuid4())
            ),
        )
        self._assert_code(
            "MEMBERSHIP_CHANGED",
            lambda: self._save(
                _content(),
                principal=_principal(self.outsider, self.school_id),
            ),
        )
        self.assertEqual(self._read()["version"], 0)

        # Both same-class teachers are authorized; either can save.
        saved = self._save(
            _content(days=[_day(WEEK, "乙老师保存")]),
            principal=self._teacher_b(),
        )
        self.assertEqual(saved["version"], 1)
        self.assertEqual(
            self._read(principal=self._teacher_a())["version"], 1
        )

        with self.Session() as session:
            with session.begin():
                membership = session.get(
                    TeacherClassMembership, self.teacher_b
                )
                membership.class_id = self.other_class_id
        self._assert_code(
            "MEMBERSHIP_CHANGED",
            lambda: self._read(principal=self._teacher_b()),
        )
        self._assert_code(
            "MEMBERSHIP_CHANGED",
            lambda: self._confirm(
                expected_version=1, principal=self._teacher_b()
            ),
        )

    def test_confirmation_freezes_snapshot_and_keeps_older_versions(self):
        first_content = _content(
            days=[_day(WEEK, "第一版晨谈", "第一版主题")],
            games=_empty_games()
            | {"collective_1": {"name": "第一版游戏", "date": "2026-11-04"}},
        )
        first = self._save(first_content)
        self.assertEqual(first["version"], 1)

        first_request = uuid4()
        confirmed = self._confirm(
            expected_version=1, request_id=first_request
        )
        self.assertEqual(confirmed["confirmation_version"], 1)
        self.assertEqual(
            WeeklyConfirmOut.model_validate(confirmed).confirmation_version,
            1,
        )
        self.assertEqual(confirmed["version"], 1)
        self.assertEqual(confirmed["class_name"], "小一班")
        self.assertEqual(confirmed["grade"], "small")
        self.assertEqual(confirmed["term_name"], "秋季学期")
        self.assertEqual(confirmed["content"], first["content"])
        self.assertEqual(confirmed["confirmed_by"], str(self.teacher_a))
        self.assertFalse(confirmed["replayed"])
        confirmation_id = confirmed["confirmation_id"]

        replay = self._confirm(
            expected_version=1, request_id=first_request
        )
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["confirmation_id"], confirmation_id)

        # A different teacher, new request, same saved version: return the
        # already-frozen confirmation instead of creating a second snapshot.
        duplicate_request = uuid4()
        duplicate = self._confirm(
            expected_version=1,
            request_id=duplicate_request,
            principal=self._teacher_b(),
        )
        self.assertTrue(duplicate["replayed"])
        self.assertEqual(duplicate["confirmation_id"], confirmation_id)
        self.assertEqual(duplicate["confirmed_by"], str(self.teacher_a))
        self.assertEqual(duplicate["content"], first["content"])
        duplicate_receipt = self._get_operation(
            duplicate_request, principal=self._teacher_b()
        )
        self.assertEqual(duplicate_receipt["kind"], "confirm")
        self.assertEqual(
            duplicate_receipt["result"]["confirmation_id"], confirmation_id
        )
        self.assertTrue(duplicate_receipt["result"]["replayed"])

        # Later promotion state changes the current class name but must not
        # rewrite the old confirmation snapshot.
        with self.Session() as session:
            with session.begin():
                session.add(
                    ClassPromotionHistory(
                        id=uuid4(),
                        class_id=self.class_id,
                        school_id=self.school_id,
                        term_id=self.term_id,
                        grade="middle",
                        version_after=2,
                    )
                )
        self.assertEqual(self._read()["class_name"], "中一班")
        with self.Session() as session:
            frozen = get_confirmation(
                session,
                self._teacher_b(),
                self.class_id,
                self.term_id,
                WEEK,
                UUID(confirmation_id),
            )
        self.assertEqual(frozen["class_name"], "小一班")
        self.assertEqual(frozen["grade"], "small")
        self.assertEqual(frozen["content"], first["content"])
        self.assertEqual(
            WeeklyConfirmationOut.model_validate(frozen).version, 1
        )

        second_content = _content(days=[_day(WEEK, "第二版晨谈", "第二版主题")])
        second = self._save(second_content, expected_version=1)
        self.assertEqual(second["version"], 2)
        self.assertEqual(second["class_name"], "中一班")
        self.assertEqual(second["confirmation"]["confirmation_id"], confirmation_id)

        self._assert_code(
            "WEEKLY_PLAN_VERSION_CONFLICT",
            lambda: self._confirm(expected_version=1),
        )
        latest = self._confirm(expected_version=2)
        self.assertEqual(latest["confirmation_version"], 2)
        self.assertEqual(latest["version"], 2)
        self.assertEqual(latest["class_name"], "中一班")
        self.assertEqual(latest["grade"], "middle")
        self.assertEqual(latest["content"], second["content"])
        self.assertNotEqual(latest["confirmation_id"], confirmation_id)

        with self.Session() as session:
            old = get_confirmation(
                session,
                self._teacher_a(),
                self.class_id,
                self.term_id,
                WEEK,
                UUID(confirmation_id),
            )
        self.assertEqual(old["confirmation_version"], 1)
        self.assertEqual(old["content"], first["content"])
        self.assertEqual(old["class_name"], "小一班")

        self._assert_code(
            "CONFIRMATION_NOT_FOUND",
            lambda: self._get_confirmation(UUID(str(uuid4()))),
        )
        self._assert_code(
            "CONFIRMATION_NOT_FOUND",
            lambda: self._get_confirmation(
                UUID(confirmation_id),
                week=FUTURE_WEEK,
                term_id=self.future_term_id,
            ),
        )

    def _get_confirmation(
        self,
        confirmation_id: UUID,
        *,
        week: date = WEEK,
        term_id: UUID | None = None,
        principal: TeacherPrincipal | None = None,
    ) -> dict:
        with self.Session() as session:
            return get_confirmation(
                session,
                principal or self._teacher_a(),
                self.class_id,
                self.term_id if term_id is None else term_id,
                week,
                confirmation_id,
            )

    def _get_operation(
        self,
        request_id: UUID,
        *,
        week: date = WEEK,
        term_id: UUID | None = None,
        principal: TeacherPrincipal | None = None,
    ) -> dict:
        with self.Session() as session:
            return get_operation(
                session,
                principal or self._teacher_a(),
                self.class_id,
                self.term_id if term_id is None else term_id,
                week,
                request_id,
            )

    def test_operation_receipts_are_frozen_and_actor_scoped(self):
        save_request = uuid4()
        saved = self._save(
            _content(days=[_day(WEEK, "第一版")]), request_id=save_request
        )
        confirm_request = uuid4()
        confirmed = self._confirm(
            expected_version=1, request_id=confirm_request
        )

        receipt = self._get_operation(save_request)
        self.assertEqual(receipt["request_id"], str(save_request))
        self.assertEqual(receipt["kind"], "save")
        self.assertEqual(
            WeeklyOperationOut.model_validate(receipt).result["version"], 1
        )
        self.assertEqual(receipt["result"]["version"], 1)
        self.assertEqual(receipt["result"]["content"], saved["content"])
        self.assertFalse(receipt["result"]["replayed"])

        confirm_receipt = self._get_operation(confirm_request)
        self.assertEqual(confirm_receipt["kind"], "confirm")
        self.assertEqual(
            confirm_receipt["result"]["confirmation_id"],
            confirmed["confirmation_id"],
        )
        self.assertEqual(
            confirm_receipt["result"]["confirmation_version"], 1
        )

        self._save(
            _content(days=[_day(WEEK, "第二版")]), expected_version=1
        )
        frozen_save = self._get_operation(save_request)
        self.assertEqual(frozen_save["result"]["version"], 1)
        frozen_confirm = self._get_operation(confirm_request)
        self.assertEqual(frozen_confirm["result"]["version"], 1)

        self._assert_code(
            "OPERATION_NOT_FOUND",
            lambda: self._get_operation(uuid4()),
        )
        self._assert_code(
            "OPERATION_NOT_FOUND",
            lambda: self._get_operation(
                save_request, principal=self._teacher_b()
            ),
        )
        self._assert_code(
            "REQUEST_CONFLICT",
            lambda: self._confirm(
                expected_version=2, request_id=save_request
            ),
        )
        self._assert_code(
            "REQUEST_CONFLICT",
            lambda: self._save(
                _content(), expected_version=2, request_id=confirm_request
            ),
        )

    def test_optional_shapes_limits_and_direct_normalization(self):
        minimal = self._save(
            _content(
                days=[_day(WEEK)],
                games=_empty_games() | {"free_choice_1": {"name": "自由游戏"}},
            )
        )
        self.assertIsNone(minimal["content"]["days"][0]["morning_talk_topic"])
        self.assertEqual(
            minimal["content"]["games"]["free_choice_1"],
            {"name": "自由游戏", "date": None},
        )

        normalized = normalize_content(
            {
                "days": [{"date": "2026-11-05"}],
                "games": {"collective_1": {"name": " 接力赛 "}},
            }
        )
        self.assertEqual(normalized["days"][0]["date"], "2026-11-05")
        self.assertIsNone(normalized["days"][0]["morning_talk_topic"])
        self.assertEqual(
            normalized["games"]["collective_1"],
            {"name": "接力赛", "date": None},
        )
        self.assertEqual(set(normalized["games"]), set(GAME_KEYS))

        invalid = (
            _content() | {"days": "not-a-list"},
            _content() | {"games": []},
            _content(days=[{"date": "2026-11-05"} | {"unknown": None}]),
            _content(days=[{"morning_talk_topic": "无日期"}]),
            _content(
                games=_empty_games() | {"collective_1": {"name": "   "}}
            ),
            _content(
                games=_empty_games()
                | {"collective_1": {"name": "x", "date": "2026-13-01"}}
            ),
            _content(
                games=_empty_games()
                | {"collective_1": {"name": "x" * 201}}
            ),
            _content(days=[_day(WEEK, "x" * 2001)]),
            _content(days=[_day(WEEK, "bad\x00text")]),
        )
        for content in invalid:
            with self.subTest(content=content):
                with self.assertRaises(CollaborationError) as caught:
                    normalize_content(content)
                self.assertEqual(
                    caught.exception.code, "WEEKLY_PLAN_INVALID"
                )

        self._assert_code(
            "WEEKLY_PLAN_INVALID",
            lambda: self._save(_content(), expected_version=-1),
        )


class WeeklyPlanSchemaAndRouteTests(unittest.TestCase):
    def test_wire_schemas_forbid_extra_fields_and_keep_version_zero(self):
        content = _content(days=[_day(WEEK, "晨谈", "主题")])
        valid = {
            "request_id": str(uuid4()),
            "expected_version": 0,
            "content": content,
        }
        parsed = WeeklySaveIn.model_validate(valid)
        self.assertEqual(parsed.expected_version, 0)
        self.assertEqual(
            parsed.model_dump(mode="json")["content"]["days"][0]["date"],
            WEEK.isoformat(),
        )

        extra_cases = (
            valid | {"unexpected": True},
            valid
            | {
                "content": content
                | {
                    "days": [
                        content["days"][0]
                        | {"group_activity_process": "正文"}
                    ]
                }
            },
            valid
            | {
                "content": content
                | {
                    "games": content["games"]
                    | {"collective_1": {"name": "x", "source_id": "y"}}
                }
            },
            valid
            | {
                "content": content
                | {"games": content["games"] | {"extra_slot": None}}
            },
        )
        for payload in extra_cases:
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    WeeklySaveIn.model_validate(payload)

        with self.assertRaises(ValidationError):
            WeeklySaveIn.model_validate(
                valid | {"expected_version": -1}
            )
        with self.assertRaises(ValidationError):
            WeeklySaveIn.model_validate(
                valid | {"expected_version": "0"}
            )
        with self.assertRaises(ValidationError):
            WeeklyConfirmIn.model_validate(
                {
                    "request_id": str(uuid4()),
                    "expected_version": 0,
                    "unexpected": True,
                }
            )
        self.assertEqual(
            WeeklyConfirmIn.model_validate(
                {"request_id": str(uuid4()), "expected_version": 0}
            ).expected_version,
            0,
        )

    def test_0004_is_additive_and_matches_mysql_models(self):
        sql = (
            BACKEND
            / "migrations_collaboration"
            / "mysql"
            / "0004_weekly_plan_sync.sql"
        ).read_text(encoding="utf-8")
        upper = sql.upper()
        self.assertEqual(sql.count("CREATE TABLE"), 3)
        self.assertEqual(sql.count("ENGINE=InnoDB"), 3)
        self.assertNotIn("CREATE DATABASE", upper)
        self.assertNotIn("CREATE SCHEMA", upper)
        self.assertNotIn("ALTER TABLE", upper)
        self.assertNotIn("DROP TABLE", upper)
        self.assertNotIn("JSONB", upper)
        for marker in (
            "weekly_plan_weeks",
            "weekly_plan_confirmations",
            "weekly_plan_operations",
            "CHAR(32)",
            "DATETIME(6)",
            "JSON",
            "ascii_bin",
            "CHAR_LENGTH",
            "STOP",
            "fk_weekly_week_class_school",
            "fk_weekly_confirmation_teacher_school",
            "fk_weekly_operation_actor_school",
            "uq_weekly_confirmation_version",
            "uq_weekly_confirmation_saved_version",
        ):
            self.assertIn(marker, sql)
        self.assertTrue(
            {
                "schools",
                "classes",
                "teachers",
                "teacher_tokens",
                "teacher_class_memberships",
                "teacher_game_configs",
                "operations",
                "terms",
                "class_promotion_states",
                "class_promotion_history",
                "class_promotion_operations",
                "weekly_plan_weeks",
                "weekly_plan_confirmations",
                "weekly_plan_operations",
            }.issubset(set(WeeklyPlanWeek.metadata.tables))
        )
        dialect = mysql_dialect()
        for model in (
            WeeklyPlanWeek,
            WeeklyPlanConfirmation,
            WeeklyPlanOperation,
        ):
            ddl = str(CreateTable(model.__table__).compile(dialect=dialect))
            self.assertIsNone(model.__table__.schema)
            self.assertIn("CHAR(32)", ddl)
            self.assertIn("DATETIME(6)", ddl)
            self.assertIn("ENGINE=InnoDB", ddl)
            self.assertIn("utf8mb4_0900_ai_ci", ddl)
            self.assertIn("JSON", ddl)

    def test_weekly_routes_are_registered(self):
        app = create_collaboration_app(
            _settings(
                "mysql+pymysql://synthetic:synthetic@127.0.0.1:3306/synthetic_collab"
            )
        )
        self.addCleanup(app.state.engine.dispose)
        paths = set(app.openapi()["paths"])
        base = "/api/collaboration/classes/{class_id}/weekly/{term_id}/{week_start}"
        self.assertTrue(
            {
                base,
                base + "/save",
                base + "/confirm",
                base + "/confirmations/{confirmation_id}",
                base + "/operations/{request_id}",
            }.issubset(paths)
        )


@unittest.skipUnless(
    os.environ.get("KGM_COLLAB_TEST_DATABASE_URL", "").strip(),
    "set KGM_COLLAB_TEST_DATABASE_URL after applying 0001-0004",
)
class WeeklyPlanMySQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ["KGM_COLLAB_TEST_DATABASE_URL"].strip()
        cls.settings = _settings(url)
        cls.settings.validate()
        cls.engine = create_collaboration_engine(cls.settings)
        cls.addClassCleanup(cls.engine.dispose)
        names = set(inspect(cls.engine).get_table_names())
        required = {
            "schools",
            "classes",
            "teachers",
            "teacher_class_memberships",
            "terms",
            "class_promotion_states",
            "class_promotion_history",
            "weekly_plan_weeks",
            "weekly_plan_confirmations",
            "weekly_plan_operations",
        }
        if not required.issubset(names):
            raise AssertionError(
                "apply MySQL 0001-0004 before running weekly-plan integration"
            )
        with cls.engine.connect() as connection:
            version = connection.exec_driver_sql("SELECT VERSION()").scalar_one()
            database = connection.exec_driver_sql("SELECT DATABASE()").scalar_one()
            isolation = connection.exec_driver_sql(
                "SELECT @@transaction_isolation"
            ).scalar_one()
        if not str(version).startswith("8.4."):
            raise AssertionError(f"MySQL 8.4 required, got {version!r}")
        print(
            f"KGM_WEEKLY_MYSQL_VERSION={version} "
            f"KGM_WEEKLY_MYSQL_DATABASE={database} "
            f"KGM_WEEKLY_MYSQL_TRANSACTION_ISOLATION={isolation}"
        )
        cls.Session = sessionmaker(
            bind=cls.engine, autoflush=False, expire_on_commit=False
        )

    def _fixture(self):
        school_id = uuid4()
        class_id = uuid4()
        teacher_a = uuid4()
        teacher_b = uuid4()
        term_id = uuid4()
        now = datetime.now(timezone.utc)
        week = date(2026, 11, 2)
        with self.Session() as session:
            with session.begin():
                session.add(School(id=school_id, name="周计划合成园"))
                session.flush()
                session.add(
                    Classroom(
                        id=class_id,
                        school_id=school_id,
                        display_name="周计划合成班",
                    )
                )
                session.add_all(
                    [
                        Teacher(
                            id=teacher_a,
                            school_id=school_id,
                            display_name="周计划甲",
                            active=True,
                        ),
                        Teacher(
                            id=teacher_b,
                            school_id=school_id,
                            display_name="周计划乙",
                            active=True,
                        ),
                    ]
                )
                session.flush()
                session.add_all(
                    [
                        TeacherClassMembership(
                            teacher_id=teacher_a,
                            school_id=school_id,
                            class_id=class_id,
                            membership_generation=uuid4(),
                            selected_at=now,
                            updated_at=now,
                        ),
                        TeacherClassMembership(
                            teacher_id=teacher_b,
                            school_id=school_id,
                            class_id=class_id,
                            membership_generation=uuid4(),
                            selected_at=now,
                            updated_at=now,
                        ),
                        CollaborationTerm(
                            id=term_id,
                            school_id=school_id,
                            name="周计划合成学期",
                            start_date=TERM_START,
                            end_date=TERM_END,
                        ),
                        ClassPromotionState(
                            class_id=class_id,
                            school_id=school_id,
                            class_number=1,
                            base_grade="small",
                            version=1,
                        ),
                    ]
                )
        return (
            school_id,
            class_id,
            term_id,
            week,
            _principal(teacher_a, school_id, "周计划甲"),
            _principal(teacher_b, school_id, "周计划乙"),
        )

    def test_save_confirm_replay_and_concurrent_writers(self):
        (
            school_id,
            class_id,
            term_id,
            week,
            principal_a,
            principal_b,
        ) = self._fixture()

        def save(principal, content, expected, request_id, session=None):
            owned = session is None
            session = session or self.Session()
            try:
                return save_weekly_plan(
                    session,
                    principal,
                    class_id,
                    term_id,
                    week,
                    request_id=request_id,
                    expected_version=expected,
                    content=content,
                )
            finally:
                if owned:
                    session.close()

        def confirm(principal, expected, request_id, session=None):
            owned = session is None
            session = session or self.Session()
            try:
                return confirm_weekly_plan(
                    session,
                    principal,
                    class_id,
                    term_id,
                    week,
                    request_id=request_id,
                    expected_version=expected,
                )
            finally:
                if owned:
                    session.close()

        first_content = _content(
            days=[_day(week, "第一版晨谈", "第一版主题")],
            games=_empty_games()
            | {"collective_1": {"name": "第一版游戏", "date": "2026-11-04"}},
        )
        first_request = uuid4()
        first = save(principal_a, first_content, 0, first_request)
        self.assertEqual(first["version"], 1)
        self.assertEqual(first["class_name"], "小一班")
        replay = save(principal_a, first_content, 0, first_request)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["content"], first["content"])

        second = save(
            principal_b,
            _content(days=[_day(week, "第二版晨谈")]),
            1,
            uuid4(),
        )
        self.assertEqual(second["version"], 2)
        self.assertTrue(
            save(principal_a, first_content, 0, first_request)["replayed"]
        )
        stale = self.assertRaises(CollaborationError)
        with stale:
            save(principal_a, first_content, 1, uuid4())
        self.assertEqual(
            stale.exception.code, "WEEKLY_PLAN_VERSION_CONFLICT"
        )
        self.assertEqual(stale.exception.details["current_version"], 2)

        confirm_request = uuid4()
        confirmed = confirm(principal_b, 2, confirm_request)
        self.assertEqual(confirmed["confirmation_version"], 1)
        self.assertEqual(confirmed["version"], 2)
        self.assertEqual(confirmed["class_name"], "小一班")
        self.assertEqual(confirmed["confirmed_by"], str(principal_b.teacher_id))
        duplicate = confirm(principal_a, 2, uuid4())
        self.assertTrue(duplicate["replayed"])
        self.assertEqual(
            duplicate["confirmation_id"], confirmed["confirmation_id"]
        )
        self.assertEqual(
            duplicate["content"], confirmed["content"]
        )
        with self.Session() as session:
            save_receipt = get_operation(
                session, principal_a, class_id, term_id, week, first_request
            )
            confirm_receipt = get_operation(
                session, principal_b, class_id, term_id, week, confirm_request
            )
        self.assertEqual(save_receipt["kind"], "save")
        self.assertEqual(save_receipt["result"]["version"], 1)
        self.assertEqual(save_receipt["result"]["content"], first["content"])
        self.assertEqual(confirm_receipt["kind"], "confirm")
        self.assertEqual(
            confirm_receipt["result"]["confirmation_id"],
            confirmed["confirmation_id"],
        )
        self.assertEqual(
            confirm_receipt["result"]["content"], second["content"]
        )

        # A later promotion changes the current class name, but the frozen
        # confirmation still answers with the old name and content.
        with self.Session() as session:
            with session.begin():
                session.add(
                    ClassPromotionHistory(
                        id=uuid4(),
                        class_id=class_id,
                        school_id=school_id,
                        term_id=term_id,
                        grade="middle",
                        version_after=2,
                    )
                )
        third = save(
            principal_a,
            _content(days=[_day(week, "第三版晨谈")]),
            2,
            uuid4(),
        )
        self.assertEqual(third["version"], 3)
        self.assertEqual(third["class_name"], "中一班")
        with self.Session() as session:
            frozen = get_confirmation(
                session,
                principal_a,
                class_id,
                term_id,
                week,
                UUID(confirmed["confirmation_id"]),
            )
        self.assertEqual(frozen["class_name"], "小一班")
        self.assertEqual(frozen["grade"], "small")
        self.assertEqual(frozen["content"], second["content"])

        with self.assertRaises(CollaborationError) as old_version:
            confirm(principal_a, 2, uuid4())
        self.assertEqual(
            old_version.exception.code, "WEEKLY_PLAN_VERSION_CONFLICT"
        )
        latest = confirm(principal_b, 3, uuid4())
        self.assertEqual(latest["confirmation_version"], 2)
        self.assertEqual(latest["class_name"], "中一班")
        self.assertEqual(latest["grade"], "middle")

        # Two teachers save from the same base: exactly one advances.
        barrier = threading.Barrier(2)
        results: list[tuple[str, object]] = []

        def save_worker(principal, text):
            with self.Session() as session:
                barrier.wait()
                try:
                    value = save(
                        principal,
                        _content(days=[_day(week, text)]),
                        3,
                        uuid4(),
                        session=session,
                    )
                    results.append(("ok", value["version"]))
                except CollaborationError as exc:
                    results.append(("error", exc.code))
                except Exception as exc:  # noqa: BLE001 - diagnostic only
                    results.append(("error", type(exc).__name__))

        threads = [
            threading.Thread(target=save_worker, args=(principal_a, "并发甲")),
            threading.Thread(target=save_worker, args=(principal_b, "并发乙")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(results), 2, results)
        self.assertEqual(sum(1 for kind, _ in results if kind == "ok"), 1, results)
        self.assertIn(("error", "WEEKLY_PLAN_VERSION_CONFLICT"), results)
        with self.Session() as session:
            current = get_weekly_plan(
                session, principal_a, class_id, term_id, week
            )
        self.assertEqual(current["version"], 4)

        # Two teachers confirm the same saved version: both receive the same
        # frozen confirmation, with one creating and one replaying it.
        barrier = threading.Barrier(2)
        confirmations: list[tuple[str, object]] = []

        def confirm_worker(principal):
            with self.Session() as session:
                barrier.wait()
                try:
                    value = confirm(
                        principal, 4, uuid4(), session=session
                    )
                    confirmations.append(
                        (
                            "ok",
                            (
                                value["confirmation_id"],
                                value["confirmation_version"],
                                value["replayed"],
                            ),
                        )
                    )
                except CollaborationError as exc:
                    confirmations.append(("error", exc.code))
                except Exception as exc:  # noqa: BLE001 - diagnostic only
                    confirmations.append(("error", type(exc).__name__))

        threads = [
            threading.Thread(target=confirm_worker, args=(principal_a,)),
            threading.Thread(target=confirm_worker, args=(principal_b,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(confirmations), 2, confirmations)
        self.assertEqual(
            sum(1 for kind, _ in confirmations if kind == "ok"), 2,
            confirmations,
        )
        ids = {value[0] for _, value in confirmations}
        self.assertEqual(len(ids), 1, confirmations)
        self.assertEqual(
            {value[1] for _, value in confirmations}, {3}, confirmations
        )
        self.assertEqual(
            {value[2] for _, value in confirmations}, {False, True},
            confirmations,
        )

        # The very first save is also serialized by the class lock: one
        # writer creates version 1, the other receives its 409 baseline.
        first_week = date(2026, 11, 9)
        barrier = threading.Barrier(2)
        first_saves: list[tuple[str, object]] = []

        def first_save_worker(principal, text):
            with self.Session() as session:
                barrier.wait()
                try:
                    value = save_weekly_plan(
                        session,
                        principal,
                        class_id,
                        term_id,
                        first_week,
                        request_id=uuid4(),
                        expected_version=0,
                        content=_content(days=[_day(first_week, text)]),
                    )
                    first_saves.append(("ok", value["version"]))
                except CollaborationError as exc:
                    first_saves.append(("error", exc.code))
                except Exception as exc:  # noqa: BLE001 - diagnostic only
                    first_saves.append(("error", type(exc).__name__))

        threads = [
            threading.Thread(target=first_save_worker, args=(principal_a, "首存甲")),
            threading.Thread(target=first_save_worker, args=(principal_b, "首存乙")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(first_saves), 2, first_saves)
        self.assertEqual(
            sum(1 for kind, _ in first_saves if kind == "ok"), 1, first_saves
        )
        self.assertIn(("error", "WEEKLY_PLAN_VERSION_CONFLICT"), first_saves)
        with self.Session() as session:
            first_current = get_weekly_plan(
                session, principal_a, class_id, term_id, first_week
            )
        self.assertEqual(first_current["version"], 1)
