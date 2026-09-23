"""No-DB mock tests for I3 service hardening: role re-check, sync error
mapping and the effective-date unique-violation classifier."""

import unittest
from datetime import datetime, timezone
from unittest import mock

from sqlalchemy.exc import IntegrityError

from app.models import Account
from app.services import auth_service
from app.services import daily_plan_service
from app.services import weekly_plan_sync_service
from app.services.auth_service import AuthSnapshot
from app.services.daily_plan_service import (
    DailyPlanDataError,
    is_effective_date_unique_violation,
)


def _snapshot(role: str, *, account_id: str = "acc1") -> AuthSnapshot:
    return AuthSnapshot(
        account_id=account_id,
        role=role,
        auth_version=1,
        session_id="ses1",
        is_active=True,
        password_hash="x",
    )


def _account(role: str, *, account_id: str = "acc1", auth_version: int = 1) -> Account:
    return Account(
        id=account_id,
        username="user1",
        password_hash="x",
        display_name=None,
        role=role,
        is_active=True,
        version=1,
        auth_version=auth_version,
    )


class LockOperatorRoleTests(unittest.TestCase):
    def test_role_mismatch_after_lock_is_auth_required(self):
        account = _account("teacher")
        db = mock.MagicMock()
        with mock.patch.object(
            auth_service, "_lock_account", return_value=account
        ), mock.patch.object(auth_service, "validate_locked_session") as v:
            with self.assertRaises(auth_service.AuthRequired):
                daily_plan_service._lock_operator(db, _snapshot("admin"))
            v.assert_not_called()

    def test_teacher_snapshot_vs_admin_account_is_auth_required(self):
        account = _account("admin")
        db = mock.MagicMock()
        with mock.patch.object(
            auth_service, "_lock_account", return_value=account
        ), mock.patch.object(auth_service, "validate_locked_session") as v:
            with self.assertRaises(auth_service.AuthRequired):
                daily_plan_service._lock_operator(db, _snapshot("teacher"))
            v.assert_not_called()

    def test_matching_role_proceeds_to_session_validation(self):
        account = _account("admin")
        db = mock.MagicMock()
        snapshot = _snapshot("admin")
        with mock.patch.object(
            auth_service, "_lock_account", return_value=account
        ), mock.patch.object(
            auth_service, "validate_locked_session"
        ) as v:
            locked = daily_plan_service._lock_operator(db, snapshot)
        self.assertIs(locked, account)
        v.assert_called_once_with(db, snapshot)

    def test_stale_auth_version_still_rejected_before_role(self):
        account = _account("admin", auth_version=2)
        db = mock.MagicMock()
        with mock.patch.object(
            auth_service, "_lock_account", return_value=account
        ), mock.patch.object(auth_service, "validate_locked_session") as v:
            with self.assertRaises(auth_service.AuthRequired):
                daily_plan_service._lock_operator(db, _snapshot("admin"))
            v.assert_not_called()


class WeeklySyncErrorMappingTests(unittest.TestCase):
    def _call(self):
        daily_plan_service._recompute_sync(
            mock.MagicMock(),
            class_id="cls1",
            term_id="ter1",
            week_number=2,
            trigger_daily_plan_id="plan1",
            trigger_content_version=1,
            trigger_event="create",
            now=datetime.now(timezone.utc).replace(tzinfo=None),
        )

    def test_weekly_sync_data_error_maps_to_service_unavailable(self):
        with mock.patch.object(
            weekly_plan_sync_service,
            "recompute_weekly_sync_state",
            side_effect=weekly_plan_sync_service.WeeklySyncDataError(
                "当前内容指针为空"
            ),
        ):
            with self.assertRaises(DailyPlanDataError) as ctx:
                self._call()
        self.assertEqual(ctx.exception.code, "SERVICE_UNAVAILABLE")
        self.assertIn("当前内容指针为空", str(ctx.exception))

    def test_weekly_sync_success_is_not_wrapped(self):
        with mock.patch.object(
            weekly_plan_sync_service,
            "recompute_weekly_sync_state",
            return_value=object(),
        ) as recompute:
            self._call()
        recompute.assert_called_once()


class EffectiveDateUniqueViolationTests(unittest.TestCase):
    def _exc(self, orig) -> IntegrityError:
        return IntegrityError("INSERT INTO daily_plans ...", {}, orig)

    def test_hits_pyysql_duplicate_on_effective_key(self):
        exc = self._exc(
            Exception(
                1062,
                "Duplicate entry 'cls1|2026-09-07' for key "
                "'daily_plans.uq_daily_plans_class_effective_date'",
            )
        )
        self.assertTrue(is_effective_date_unique_violation(exc))

    def test_hits_mysql8_backtick_qualified_key_form(self):
        exc = self._exc(
            Exception(
                1062,
                "Duplicate entry 'cls1|2026-09-07' for key "
                "'kg`.`daily_plans`.`uq_daily_plans_class_effective_date'",
            )
        )
        self.assertTrue(is_effective_date_unique_violation(exc))

    def test_hits_when_only_orig_string_carries_both_markers(self):
        class _Orig:
            args = (
                1062,
                "Duplicate entry 'x' for key "
                "'db.uq_daily_plans_class_effective_date'",
            )

            def __str__(self) -> str:
                return (
                    "(1062, \"Duplicate entry 'x' for key "
                    "'db.uq_daily_plans_class_effective_date'\")"
                )

        self.assertTrue(
            is_effective_date_unique_violation(self._exc(_Orig()))
        )

    def test_misses_other_unique_key(self):
        exc = self._exc(
            Exception(
                1062,
                "Duplicate entry 'plan1|1' for key "
                "'daily_plan_contents.uq_daily_plan_contents_plan_version'",
            )
        )
        self.assertFalse(is_effective_date_unique_violation(exc))

    def test_misses_foreign_key_violation(self):
        exc = self._exc(
            Exception(
                1452,
                "Cannot add or update a child row: a foreign key constraint "
                "fails",
            )
        )
        self.assertFalse(is_effective_date_unique_violation(exc))

    def test_misses_key_name_without_duplicate_marker(self):
        exc = self._exc(
            Exception(
                "constraint failed: daily_plans.uq_daily_plans_class_effective_date"
            )
        )
        self.assertFalse(is_effective_date_unique_violation(exc))

    def test_misses_unrelated_integrity_error(self):
        exc = self._exc(RuntimeError("boom"))
        self.assertFalse(is_effective_date_unique_violation(exc))

    def test_create_handler_uses_classifier_not_row_presence(self):
        snapshot = _snapshot("teacher", account_id="tch1")
        non_hit = self._exc(Exception(1452, "foreign key constraint fails"))

        db = mock.MagicMock()
        db.in_transaction.return_value = True

        with mock.patch.object(
            daily_plan_service,
            "_create_or_open_locked",
            side_effect=non_hit,
        ), mock.patch.object(
            daily_plan_service, "_find_after_conflict"
        ) as find:
            with self.assertRaises(IntegrityError) as ctx:
                daily_plan_service.create_or_open(
                    db, snapshot, plan_date=None
                )
        self.assertIs(ctx.exception, non_hit)
        db.rollback.assert_called_once()
        find.assert_not_called()


if __name__ == "__main__":
    unittest.main()
