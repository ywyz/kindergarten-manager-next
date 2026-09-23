"""V5 / V11 / V12 plus the spec section 5 concurrency and lock-order cases.

Everything here runs on real MySQL 8.4 / InnoDB with independent sessions
and threads: rollback is injected with real ``SIGNAL`` triggers (never a
mocked exception), persistence is re-read through a disposed-and-rebuilt
engine, and lock behaviour is proven by holding real ``FOR UPDATE`` rows
in a separate connection.
"""

from __future__ import annotations

import threading
import time
from unittest import mock

from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from tests.integration.i4_support import (
    ADMIN,
    CLASS_ID,
    DAY_MON,
    OWNER,
    ROLLBACK_MARKER,
    SAME,
    TERM_ID,
    WEEK,
    I4IntegrationTestCase,
    create_daily,
    day_content,
    make_engine,
    pick_candidate,
    ref_payload,
    require_authorized_url,
    snap,
)

_SYNC_ROW_SQL = (
    "SELECT id, class_id, term_id, week_number, status, "
    "deterministic_themes, game_source_manifest, "
    "current_week_source_manifest, last_trigger_daily_plan_id, "
    "last_trigger_content_version, last_trigger_event, created_at, updated_at "
    "FROM weekly_plan_sync_states ORDER BY id"
)

_PERSISTENCE_QUERIES = {
    "plan": (
        "SELECT id, class_id, term_id, week_number, creator_id, owner_id, "
        "current_draft_content_id, current_draft_version, "
        "current_confirmed_content_id, current_confirmed_content_version, "
        "school_name, class_name, grade, header_teacher_names, "
        "caregiver_name, projection_consumed_at, deleted_at, deleted_by, "
        "created_at, updated_at FROM weekly_plans ORDER BY id"
    ),
    "drafts": (
        "SELECT id, weekly_plan_id, version, content, editor_id, "
        "editor_role, created_at FROM weekly_plan_contents "
        "ORDER BY weekly_plan_id, version"
    ),
    "confirmed": (
        "SELECT id, weekly_plan_id, version, draft_version, content, facts, "
        "confirmed_by, created_at FROM weekly_plan_confirmed_contents "
        "ORDER BY weekly_plan_id, version"
    ),
    "records": (
        "SELECT action, target_type, target_id, target_version_after "
        "FROM operation_records ORDER BY id"
    ),
    "sync": _SYNC_ROW_SQL,
    "daily": (
        "SELECT id, plan_date, current_content_id, current_content_version "
        "FROM daily_plans ORDER BY id"
    ),
    "daily_contents": (
        "SELECT id, daily_plan_id, version, adopted_content "
        "FROM daily_plan_contents ORDER BY daily_plan_id, version"
    ),
}

_JOIN_TIMEOUT = 30.0
_BLOCK_WINDOW = 0.6


def _spawn(target) -> tuple[threading.Thread, list]:
    """Run ``target`` in a thread, capturing any escaping exception."""

    box: list = []

    def wrapper():
        try:
            box.append(("ok", target()))
        except Exception as exc:  # noqa: BLE001 - reported by the assertion
            box.append(("err", exc))

    thread = threading.Thread(target=wrapper, daemon=True)
    thread.start()
    return thread, box


def _join_or_fail(*threads: threading.Thread) -> None:
    for thread in threads:
        thread.join(timeout=_JOIN_TIMEOUT)
        if thread.is_alive():
            raise AssertionError(
                f"thread {thread.name} did not finish within "
                f"{_JOIN_TIMEOUT}s (a lock timeout counts as a failure, "
                f"never as a silent retry)"
            )


def _latest_daily_version(engine, plan_id) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT version FROM daily_plan_contents "
                    "WHERE daily_plan_id = :id ORDER BY version DESC LIMIT 1"
                ),
                {"id": plan_id},
            ).scalar_one()
        )


class V5ConcurrentCreateTests(I4IntegrationTestCase):
    def test_concurrent_create_same_week_single_effective_row(self):
        barrier = threading.Barrier(2)
        results: list = []
        lock = threading.Lock()

        def worker(account: dict) -> None:
            db = self.SessionLocal()
            try:
                from app.services import weekly_plan_service

                barrier.wait(timeout=_JOIN_TIMEOUT)
                result = weekly_plan_service.create_or_open_weekly_plan(
                    db,
                    snap(account),
                    term_id=TERM_ID,
                    week_number=WEEK,
                    theme=f"{account['username']}并发创建",
                )
                with lock:
                    results.append(
                        (
                            account["id"],
                            result.created,
                            result.plan.id,
                            result.plan.creator_id,
                            result.plan.owner_id,
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                with lock:
                    results.append((account["id"], "err", exc))
            finally:
                db.close()

        threads = [
            threading.Thread(target=worker, args=(OWNER,), daemon=True),
            threading.Thread(target=worker, args=(SAME,), daemon=True),
        ]
        for thread in threads:
            thread.start()
        _join_or_fail(*threads)

        errors = [item for item in results if item[1] == "err"]
        self.assertEqual(errors, [], errors)
        self.assertEqual(len(results), 2, results)

        created_flags = [item[1] for item in results]
        self.assertEqual(sorted(created_flags), [False, True], results)
        self.assertEqual(self.plan_count(), 1)

        plan_ids = {item[2] for item in results}
        self.assertEqual(len(plan_ids), 1, results)

        winner = next(item for item in results if item[1] is True)
        # The loser's request must not rewrite creator/owner.
        self.assertEqual({item[3] for item in results}, {winner[3]})
        self.assertEqual({item[4] for item in results}, {winner[4]})
        row = self.rows(
            "SELECT creator_id, owner_id FROM weekly_plans WHERE id = :id",
            {"id": winner[2]},
        )
        self.assertEqual(row, [(winner[3], winner[4])])

        # Opening (not creating) must not append a second draft or audit.
        self.assertEqual(self.draft_count(winner[2]), 1)
        self.assertEqual(
            self.operation_records(winner[2], "create_weekly_plan"), 1
        )

    def test_unique_key_classifier_sees_real_mysql_errors(self):
        from app.services import weekly_plan_service

        db = self.SessionLocal()
        try:
            result = weekly_plan_service.create_or_open_weekly_plan(
                db, snap(OWNER), term_id=TERM_ID, week_number=WEEK
            )
            plan = result.plan
        finally:
            db.close()

        # Genuine 1062 on the effective unique key -> recognised.
        conn = self.engine.connect()
        try:
            with self.assertRaises(IntegrityError) as ctx:
                conn.execute(
                    text(
                        "INSERT INTO weekly_plans (id, class_id, term_id, "
                        "week_number, creator_id, owner_id, class_name, "
                        "grade, header_teacher_names, created_at, updated_at) "
                        "VALUES ('dupweek00000000000000000001', :cls, :term, "
                        ":week, :owner, :owner, '小班甲', 'small', "
                        "CAST('[]' AS JSON), NOW(), NOW())"
                    ),
                    {
                        "cls": CLASS_ID,
                        "term": TERM_ID,
                        "week": WEEK,
                        "owner": OWNER["id"],
                    },
                )
        finally:
            conn.rollback()
            conn.close()
        self.assertTrue(
            weekly_plan_service.is_weekly_effective_unique_violation(
                ctx.exception
            ),
            str(ctx.exception),
        )

        # Genuine 1062 on the primary key must NOT be reclassified.
        conn = self.engine.connect()
        try:
            with self.assertRaises(IntegrityError) as ctx:
                conn.execute(
                    text(
                        "INSERT INTO weekly_plans (id, class_id, term_id, "
                        "week_number, creator_id, owner_id, class_name, "
                        "grade, header_teacher_names, created_at, updated_at) "
                        "VALUES (:id, :cls, :term, 9, :owner, :owner, "
                        "'小班甲', 'small', CAST('[]' AS JSON), NOW(), NOW())"
                    ),
                    {
                        "id": plan.id,
                        "cls": CLASS_ID,
                        "term": TERM_ID,
                        "owner": OWNER["id"],
                    },
                )
        finally:
            conn.rollback()
            conn.close()
        self.assertFalse(
            weekly_plan_service.is_weekly_effective_unique_violation(
                ctx.exception
            ),
            str(ctx.exception),
        )
        self.assertEqual(self.plan_count(), 1)


class V11RollbackTests(I4IntegrationTestCase):
    """Real MySQL ``SIGNAL`` failures raised inside the write transactions."""

    def _install_create_trigger(self) -> None:
        with self.engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TRIGGER trg_i4_create_rollback BEFORE INSERT "
                "ON weekly_plan_contents FOR EACH ROW "
                f"BEGIN IF NEW.content->>'$.theme' = '{ROLLBACK_MARKER}' "
                "THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = "
                "'i4 injected create failure'; END IF; END"
            )

    def _install_confirm_trigger(self) -> None:
        with self.engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TRIGGER trg_i4_confirm_rollback BEFORE INSERT "
                "ON weekly_plan_confirmed_contents FOR EACH ROW "
                f"BEGIN IF NEW.facts->>'$.note' = '{ROLLBACK_MARKER}' "
                "THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = "
                "'i4 injected confirm failure'; END IF; END"
            )

    def _drop_triggers(self) -> None:
        with self.engine.begin() as conn:
            conn.exec_driver_sql(
                "DROP TRIGGER IF EXISTS trg_i4_create_rollback"
            )
            conn.exec_driver_sql(
                "DROP TRIGGER IF EXISTS trg_i4_confirm_rollback"
            )

    def _fresh_verification_engine(self):
        engine = make_engine()
        require_authorized_url(str(engine.url))
        return engine

    def test_create_failure_leaves_no_partial_rows(self):
        from app.services import weekly_plan_service

        self._install_create_trigger()
        verify = self._fresh_verification_engine()
        try:
            with self.assertRaises(DatabaseError) as ctx:
                self.run_service(
                    weekly_plan_service.create_or_open_weekly_plan,
                    OWNER,
                    term_id=TERM_ID,
                    week_number=WEEK,
                    theme=ROLLBACK_MARKER,
                )
            self.assertIn("i4 injected create failure", str(ctx.exception))

            # Independent new connection: no half-written state anywhere.
            with verify.connect() as conn:
                plans = conn.execute(
                    text("SELECT COUNT(*) FROM weekly_plans")
                ).scalar()
                drafts = conn.execute(
                    text("SELECT COUNT(*) FROM weekly_plan_contents")
                ).scalar()
                confirmed = conn.execute(
                    text("SELECT COUNT(*) FROM weekly_plan_confirmed_contents")
                ).scalar()
                records = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM operation_records "
                        "WHERE target_type = 'weekly_plan'"
                    )
                ).scalar()
                pointers = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM weekly_plans WHERE "
                        "current_draft_content_id IS NOT NULL OR "
                        "current_confirmed_content_id IS NOT NULL"
                    )
                ).scalar()
                consume = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM weekly_plans WHERE "
                        "projection_consumed_at IS NOT NULL"
                    )
                ).scalar()
            self.assertEqual(plans, 0)
            self.assertEqual(drafts, 0)
            self.assertEqual(confirmed, 0)
            self.assertEqual(records, 0)
            self.assertEqual(pointers, 0)
            self.assertEqual(consume, 0)
        finally:
            verify.dispose()
            self._drop_triggers()

        # The write path still works once the injected failure is gone.
        ok = self.run_service(
            weekly_plan_service.create_or_open_weekly_plan,
            OWNER,
            term_id=TERM_ID,
            week_number=WEEK,
            theme="失败后可写",
        )
        self.assertTrue(ok.created)
        self.assertEqual(self.plan_count(), 1)

    def test_confirm_failure_leaves_no_partial_rows(self):
        from app.services import weekly_plan_service

        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK, "theme": "回滚前"},
        )
        self.assertEqual(created.status_code, 201, created.content)
        plan_id = created.json()["id"]
        patched = self.owner_client.patch(
            f"/api/weekly-plans/{plan_id}",
            {"expected_draft_version": 1, "theme": "回滚前改"},
        )
        self.assertEqual(patched.status_code, 200, patched.content)

        pointer_sql = (
            "SELECT current_draft_content_id, current_draft_version, "
            "current_confirmed_content_id, "
            "current_confirmed_content_version, projection_consumed_at "
            "FROM weekly_plans WHERE id = :id"
        )
        before = {
            "drafts": self.draft_count(plan_id),
            "confirmed": self.confirmed_count(plan_id),
            "records": self.operation_records(plan_id),
            "pointer": self.rows(pointer_sql, {"id": plan_id}),
        }
        self.assertEqual(before["drafts"], 2)
        self.assertEqual(before["confirmed"], 0)
        self.assertEqual(before["pointer"][0][2], None)
        self.assertEqual(before["pointer"][0][3], None)

        self._install_confirm_trigger()
        verify = self._fresh_verification_engine()
        try:
            with self.assertRaises(SQLAlchemyError) as ctx:
                self.run_service(
                    weekly_plan_service.confirm_weekly_plan,
                    OWNER,
                    plan_id=plan_id,
                    expected_draft_version=2,
                    acknowledge_missing=True,
                    acknowledge_stale=True,
                    note=ROLLBACK_MARKER,
                )
            self.assertIn("i4 injected confirm failure", str(ctx.exception))

            with verify.connect() as conn:
                confirmed = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM weekly_plan_confirmed_contents "
                        "WHERE weekly_plan_id = :id"
                    ),
                    {"id": plan_id},
                ).scalar()
                pointer = tuple(
                    conn.execute(
                        text(pointer_sql), {"id": plan_id}
                    ).one()
                )
                drafts = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM weekly_plan_contents "
                        "WHERE weekly_plan_id = :id"
                    ),
                    {"id": plan_id},
                ).scalar()
                records = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM operation_records "
                        "WHERE target_type = 'weekly_plan' AND target_id = :id"
                    ),
                    {"id": plan_id},
                ).scalar()
            self.assertEqual(confirmed, 0)
            self.assertEqual(pointer, before["pointer"][0])
            self.assertEqual(drafts, before["drafts"])
            self.assertEqual(records, before["records"])
        finally:
            verify.dispose()
            self._drop_triggers()

        self.assertEqual(
            self.rows(pointer_sql, {"id": plan_id}), before["pointer"]
        )
        self.assertEqual(self.confirmed_count(plan_id), 0)

        # Confirm succeeds again once the injected failure is gone.
        ok = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/confirm",
            {
                "expected_draft_version": 2,
                "acknowledge_missing": True,
                "acknowledge_stale": False,
                "note": "回滚后确认",
            },
        )
        self.assertEqual(ok.status_code, 201, ok.content)
        self.assertEqual(self.confirmed_count(plan_id), 1)


class V12RestartPersistenceTests(I4IntegrationTestCase):
    def _snapshot(self, engine) -> dict[str, list[tuple]]:
        snapshot: dict[str, list[tuple]] = {}
        with engine.connect() as conn:
            for key, sql in _PERSISTENCE_QUERIES.items():
                snapshot[key] = [tuple(row) for row in conn.execute(text(sql))]
        return snapshot

    def test_writes_survive_engine_and_session_factory_restart(self):
        from app.services import weekly_plan_read_service

        create_daily(
            self.SessionLocal,
            OWNER,
            DAY_MON,
            adopted_content=day_content(
                talk="重启话题",
                theme="重启主题",
                collective={
                    "names": ["跳圈圈"],
                    "shared_objectives": "重启目标",
                    "guidance_points": "重启指导",
                },
            ),
        )
        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK, "theme": "重启前主题"},
        )
        self.assertEqual(created.status_code, 201, created.content)
        plan_id = created.json()["id"]
        candidate = pick_candidate(
            created.json(), category="collective", name="跳圈圈"
        )
        patched = self.owner_client.patch(
            f"/api/weekly-plans/{plan_id}",
            {
                "expected_draft_version": 1,
                "theme": "重启后仍应存在",
                "deterministic_overrides": {
                    DAY_MON.isoformat(): {"morning_talk_topic": "重启覆盖"}
                },
                "outdoor_game_slots": {"collective_1": ref_payload(candidate)},
            },
        )
        self.assertEqual(patched.status_code, 200, patched.content)

        confirmed = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/confirm",
            {
                "expected_draft_version": 2,
                "acknowledge_missing": True,
                "acknowledge_stale": False,
                "note": "重启前确认",
            },
        )
        self.assertEqual(confirmed.status_code, 201, confirmed.content)

        time.sleep(1.05)
        refreshed = self.owner_client.post(
            f"/api/weekly-plans/{plan_id}/refresh-sources",
            {"expected_draft_version": 2},
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.content)
        self.assertFalse(refreshed.json()["projection_pending"])

        plan_row = self.rows(
            "SELECT projection_consumed_at FROM weekly_plans WHERE id = :id",
            {"id": plan_id},
        )
        self.assertIsNotNone(plan_row[0][0])

        before = self._snapshot(self.engine)

        # -- simulate a full process restart -------------------------------
        import app.database as app_database

        if app_database._engine is not None:
            app_database._engine.dispose()
        app_database._engine = None
        app_database._SessionLocal = None
        self.engine.dispose()

        fresh_engine = make_engine()
        require_authorized_url(str(fresh_engine.url))
        type(self).engine = fresh_engine
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            bind=fresh_engine,
        )

        after = self._snapshot(fresh_engine)
        self.assertEqual(before, after)

        # ORM reads through the brand-new session factory.
        db = self.SessionLocal()
        try:
            detail = weekly_plan_read_service.get_detail(
                db,
                plan_id,
                account_id=OWNER["id"],
                role="teacher",
                class_id=CLASS_ID,
            )
            history = weekly_plan_read_service.list_confirmations(
                db, plan_id, role="teacher", class_id=CLASS_ID
            )
            single = weekly_plan_read_service.get_confirmation(
                db, plan_id, 1, role="teacher", class_id=CLASS_ID
            )
        finally:
            db.close()

        self.assertEqual(detail["draft"]["version"], 3)
        self.assertEqual(detail["draft"]["content"]["theme"], "重启后仍应存在")
        row = next(
            r
            for r in detail["draft"]["content"]["deterministic"]
            if r["date"] == DAY_MON.isoformat()
        )
        self.assertEqual(row["override"]["morning_talk_topic"], "重启覆盖")
        self.assertEqual(
            detail["draft"]["content"]["outdoor_game_slots"]["collective_1"][
                "name"
            ],
            "跳圈圈",
        )
        self.assertEqual(history["total"], 1)
        self.assertEqual(single["version"], 1)
        self.assertEqual(single["facts"]["note"], "重启前确认")

        pointers = self.rows(
            "SELECT current_draft_version, current_confirmed_content_version, "
            "projection_consumed_at FROM weekly_plans WHERE id = :id",
            {"id": plan_id},
        )
        self.assertEqual(pointers[0][0], 3)
        self.assertEqual(pointers[0][1], 1)
        self.assertIsNotNone(pointers[0][2])
        self.assertEqual(self.confirmed_count(plan_id), 1)
        self.assertGreaterEqual(self.operation_records(plan_id), 3)
        # The I3 projection row survived the restart untouched.
        self.assertEqual(len(self.rows(_SYNC_ROW_SQL)), 1)


class LockOrderTests(I4IntegrationTestCase):
    def _prepare_plan_with_source(self) -> tuple[str, object]:
        daily_plan, _content, _ = create_daily(
            self.SessionLocal,
            OWNER,
            DAY_MON,
            adopted_content=day_content(
                talk="锁话题",
                theme="锁主题",
                collective={
                    "names": ["跳圈圈"],
                    "shared_objectives": "锁目标",
                    "guidance_points": "锁指导",
                },
            ),
        )
        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK, "theme": "锁序"},
        )
        self.assertEqual(created.status_code, 201, created.content)
        plan_id = created.json()["id"]
        candidate = pick_candidate(
            created.json(), category="collective", name="跳圈圈"
        )
        patched = self.owner_client.patch(
            f"/api/weekly-plans/{plan_id}",
            {
                "expected_draft_version": 1,
                "outdoor_game_slots": {"collective_1": ref_payload(candidate)},
            },
        )
        self.assertEqual(patched.status_code, 200, patched.content)
        return plan_id, daily_plan

    def test_daily_save_and_weekly_refresh_serialize_on_shared_class_row(self):
        from app.services import daily_plan_service, weekly_plan_service

        plan_id, daily_plan = self._prepare_plan_with_source()
        # Three parties: both workers and this thread start together.
        barrier = threading.Barrier(3)
        outcomes: dict[str, object] = {}

        def daily_worker() -> None:
            try:
                barrier.wait(timeout=_JOIN_TIMEOUT)
                version = _latest_daily_version(self.engine, daily_plan.id)
                db = self.SessionLocal()
                try:
                    daily_plan_service.save(
                        db,
                        snap(OWNER),
                        plan_id=daily_plan.id,
                        expected_content_version=version,
                        adopted_content=day_content(
                            talk="并发锁话题", theme="并发锁主题"
                        ),
                    )
                finally:
                    db.close()
                outcomes["daily"] = "ok"
            except Exception as exc:  # noqa: BLE001
                outcomes["daily"] = exc

        def weekly_worker() -> None:
            try:
                barrier.wait(timeout=_JOIN_TIMEOUT)
                db = self.SessionLocal()
                try:
                    weekly_plan_service.refresh_weekly_sources(
                        db,
                        snap(OWNER),
                        plan_id=plan_id,
                        expected_draft_version=2,
                    )
                finally:
                    db.close()
                outcomes["weekly"] = "ok"
            except Exception as exc:  # noqa: BLE001
                outcomes["weekly"] = exc

        holder = self.engine.connect()
        holder_txn = holder.begin()
        try:
            holder.execute(
                text("SELECT id FROM classes WHERE id = :id FOR UPDATE"),
                {"id": CLASS_ID},
            )
            daily_thread, _ = _spawn(daily_worker)
            weekly_thread, _ = _spawn(weekly_worker)
            barrier.wait(timeout=_JOIN_TIMEOUT)

            # Both sides must be waiting on the real shared class-row lock.
            time.sleep(_BLOCK_WINDOW)
            self.assertNotIn("daily", outcomes)
            self.assertNotIn("weekly", outcomes)
            self.assertTrue(daily_thread.is_alive())
            self.assertTrue(weekly_thread.is_alive())
        finally:
            holder_txn.rollback()
            holder.close()

        _join_or_fail(daily_thread, weekly_thread)
        self.assertEqual(outcomes.get("daily"), "ok", outcomes)
        self.assertEqual(outcomes.get("weekly"), "ok", outcomes)

        # Serialized, completed, nothing lost.
        self.assertEqual(
            int(
                self.scalar(
                    "SELECT current_content_version FROM daily_plans "
                    "WHERE id = :id",
                    {"id": daily_plan.id},
                )
            ),
            2,
        )
        self.assertEqual(
            int(
                self.scalar(
                    "SELECT current_draft_version FROM weekly_plans "
                    "WHERE id = :id",
                    {"id": plan_id},
                )
            ),
            3,
        )

    def test_weekly_takes_weekly_lock_before_daily_lock(self):
        from app.services import weekly_plan_service as wps

        plan_id, daily_plan = self._prepare_plan_with_source()
        weekly_locked = threading.Event()
        finished = threading.Event()
        outcome: dict[str, object] = {}

        original = wps._lock_weekly_plan

        def observing(db, plan_id_arg):
            row = original(db, plan_id_arg)
            weekly_locked.set()
            return row

        def weekly_worker() -> None:
            try:
                db = self.SessionLocal()
                try:
                    wps.refresh_weekly_sources(
                        db,
                        snap(OWNER),
                        plan_id=plan_id,
                        expected_draft_version=2,
                    )
                finally:
                    db.close()
                outcome["result"] = "ok"
            except Exception as exc:  # noqa: BLE001
                outcome["result"] = exc
            finally:
                finished.set()

        holder = self.engine.connect()
        holder_txn = holder.begin()
        try:
            holder.execute(
                text("SELECT id FROM daily_plans WHERE id = :id FOR UPDATE"),
                {"id": daily_plan.id},
            )
            with mock.patch.object(wps, "_lock_weekly_plan", observing):
                thread, _ = _spawn(weekly_worker)

                # 1) the weekly row lock is acquired first...
                self.assertTrue(
                    weekly_locked.wait(5.0),
                    "weekly plan row lock was never acquired",
                )
                # 2) ...and the writer then waits on the daily row, so the
                #    held order is weekly -> daily, never the reverse.
                time.sleep(_BLOCK_WINDOW)
                self.assertTrue(thread.is_alive())
                self.assertFalse(finished.is_set())
        finally:
            holder_txn.rollback()
            holder.close()

        _join_or_fail(thread)
        self.assertEqual(outcome.get("result"), "ok", outcome)
        self.assertEqual(
            int(
                self.scalar(
                    "SELECT current_draft_version FROM weekly_plans "
                    "WHERE id = :id",
                    {"id": plan_id},
                )
            ),
            3,
        )

    def test_patch_and_confirm_race_single_consistent_outcome(self):
        from app.services import weekly_plan_service as wps

        created = self.owner_client.post(
            "/api/weekly-plans",
            {"term_id": TERM_ID, "week_number": WEEK, "theme": "竞争基线"},
        )
        self.assertEqual(created.status_code, 201, created.content)
        plan_id = created.json()["id"]

        barrier = threading.Barrier(2)
        outcomes: dict[str, object] = {}

        def admin_patch() -> None:
            try:
                db = self.SessionLocal()
                try:
                    barrier.wait(timeout=_JOIN_TIMEOUT)
                    wps.save_weekly_plan(
                        db,
                        snap(ADMIN),
                        plan_id=plan_id,
                        expected_draft_version=1,
                        patch={"theme": "管理员并发写"},
                        class_id=CLASS_ID,
                    )
                finally:
                    db.close()
                outcomes["patch"] = "ok"
            except Exception as exc:  # noqa: BLE001
                outcomes["patch"] = exc

        def owner_confirm() -> None:
            try:
                db = self.SessionLocal()
                try:
                    barrier.wait(timeout=_JOIN_TIMEOUT)
                    wps.confirm_weekly_plan(
                        db,
                        snap(OWNER),
                        plan_id=plan_id,
                        expected_draft_version=1,
                        acknowledge_missing=True,
                        acknowledge_stale=True,
                    )
                finally:
                    db.close()
                outcomes["confirm"] = "ok"
            except Exception as exc:  # noqa: BLE001
                outcomes["confirm"] = exc

        threads = [
            threading.Thread(target=admin_patch, daemon=True),
            threading.Thread(target=owner_confirm, daemon=True),
        ]
        for thread in threads:
            thread.start()
        _join_or_fail(*threads)

        # The admin write is never lost: confirm does not block it.
        self.assertEqual(outcomes.get("patch"), "ok", outcomes)

        confirmed_now = self.confirmed_count(plan_id)
        draft_version = int(
            self.scalar(
                "SELECT current_draft_version FROM weekly_plans "
                "WHERE id = :id",
                {"id": plan_id},
            )
        )
        confirmed_version = self.scalar(
            "SELECT current_confirmed_content_version FROM weekly_plans "
            "WHERE id = :id",
            {"id": plan_id},
        )
        self.assertEqual(draft_version, 2)

        if outcomes.get("confirm") == "ok":
            # Confirm won: it snapshotted draft v1 while the draft moved on.
            self.assertEqual(confirmed_now, 1)
            self.assertEqual(confirmed_version, 1)
            self.assertEqual(
                self.rows(
                    "SELECT draft_version FROM weekly_plan_confirmed_contents "
                    "WHERE weekly_plan_id = :id",
                    {"id": plan_id},
                ),
                [(1,)],
            )
        else:
            # Confirm lost: a clean version conflict, never a partial write.
            self.assertIsInstance(
                outcomes.get("confirm"), wps.WeeklyPlanVersionConflict
            )
            self.assertEqual(confirmed_now, 0)
            self.assertIsNone(confirmed_version)
            self.assertEqual(
                self.scalar(
                    "SELECT content->>'$.theme' FROM weekly_plan_contents "
                    "WHERE weekly_plan_id = :id AND version = 2",
                    {"id": plan_id},
                ),
                "管理员并发写",
            )

        detail = self.owner_client.get(f"/api/weekly-plans/{plan_id}").json()
        self.assertTrue(detail["needs_confirm"])
        if confirmed_now == 1:
            self.assertEqual(detail["confirmation_status"], "draft_ahead")
        else:
            self.assertEqual(detail["confirmation_status"], "never_confirmed")
