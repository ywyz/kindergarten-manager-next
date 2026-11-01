"""Appearance preference service tests (desktop appearance spec §2)."""

from __future__ import annotations

import unittest
import uuid
from datetime import date

from app.local import appearance_service, profile_service
from app.local.errors import (
    LocalAppearanceVersionConflict,
    LocalValidationError,
)
from app.local.models import LocalSettings
from app.local.normalize import normalize_initialization
from tests.local.support import LocalTestCase


class AppearanceTests(LocalTestCase):
    def _initialize(self):
        runtime = self.make_runtime()
        session = runtime.session()
        self.addCleanup(session.close)
        normalized = normalize_initialization(
            request_id=str(uuid.uuid4()),
            display_name="测试教师",
            class_name="中一班",
            grade="middle",
            term_name="秋季学期",
            start_date=date(2026, 9, 7).isoformat(),
            end_date=date(2026, 10, 30).isoformat(),
            school_name="测试幼儿园",
        )
        profile_service.initialize(session, normalized)
        session.expire_all()
        return runtime, session

    def test_default_is_light_and_update_only_touches_preference(self) -> None:
        runtime, session = self._initialize()
        settings = session.get(LocalSettings, "singleton")
        self.assertIsNotNone(settings)
        self.assertEqual(settings.ui_theme, "light")
        self.assertEqual(settings.ui_theme_version, 1)
        config_version = settings.config_version
        updated_at = settings.updated_at
        result = appearance_service.update_appearance(
            session, mode="dark", expected_version=1
        )
        self.assertEqual(result, {"mode": "dark", "version": 2})
        session.expire_all()
        settings = session.get(LocalSettings, "singleton")
        self.assertEqual(settings.ui_theme, "dark")
        self.assertEqual(settings.ui_theme_version, 2)
        self.assertEqual(settings.config_version, config_version)
        self.assertEqual(settings.updated_at, updated_at)

    def test_same_mode_is_idempotent(self) -> None:
        _, session = self._initialize()
        result = appearance_service.update_appearance(
            session, mode="light", expected_version=1
        )
        self.assertEqual(result, {"mode": "light", "version": 1})

    def test_stale_version_conflicts_with_actual_details(self) -> None:
        _, session = self._initialize()
        appearance_service.update_appearance(
            session, mode="dark", expected_version=1
        )
        with self.assertRaises(LocalAppearanceVersionConflict) as raised:
            appearance_service.update_appearance(
                session, mode="light", expected_version=1
            )
        self.assertEqual(raised.exception.details, {"mode": "dark", "version": 2})

    def test_invalid_inputs_are_rejected(self) -> None:
        _, session = self._initialize()
        with self.assertRaises(LocalValidationError):
            appearance_service.update_appearance(
                session, mode="sepia", expected_version=1
            )
        for value in (True, 0, -1, "1", 1.5, None):
            with self.subTest(value=value):
                with self.assertRaises(LocalValidationError):
                    appearance_service.update_appearance(
                        session, mode="dark", expected_version=value
                    )

    def test_uninitialized_profile_is_refused(self) -> None:
        runtime = self.make_runtime()
        session = runtime.session()
        self.addCleanup(session.close)
        from app.local.errors import LocalProfileRequired

        with self.assertRaises(LocalProfileRequired):
            appearance_service.read_appearance(session)

    def test_context_class_carries_header_fields(self) -> None:
        _, session = self._initialize()
        context = profile_service.read_context(session, date.today())
        self.assertEqual(context["class"]["header_teacher_names"], [])
        self.assertIsNone(context["class"]["caregiver_name"])
