"""Bounded local diagnostics store: regression tests (synthetic only).

Covers the 2026-11-24 in-app feedback adjustment: the store records
fixed-shape events (fixed event type, UTC time, fixed result and a fixed
error code from the shared finite vocabulary — never input content, paths,
ids or credentials), merges any unclassified code to ``UNKNOWN_ERROR`` at
collection, classifies real save-route failures into the fixed classes,
stays bounded by count and age (also when a restart recovers the file),
reads the file with a hard byte bound, keeps the memory update and the
atomic persistence ordered under one lock, and never raises on recording,
persisting or reading failures.  Every temporary directory is a
test-owned synthetic root; the module-level store is rebound and restored
around each test.
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.local import diagnostics as diagnostics_module
from app.local.diagnostics import (
    DiagnosticsStore,
    MAX_STORE_FILE_BYTES,
    records_save_event,
    save_error_code,
)


class DiagnosticsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory(
            prefix="kgm-diagnostics-test-"
        )
        self.addCleanup(self._tempdir.cleanup)
        self.data_dir = Path(self._tempdir.name) / "data"
        # Keep the module-level store isolated from other test modules.
        self._original_dir = diagnostics_module._store._data_dir  # noqa: SLF001
        self._original_events = list(  # noqa: SLF001
            diagnostics_module._store._events
        )
        self.addCleanup(self._restore_module_store)

    def _restore_module_store(self) -> None:
        diagnostics_module._store._data_dir = self._original_dir  # noqa: SLF001
        diagnostics_module._store._events = self._original_events  # noqa: SLF001

    # -- fixed shape -------------------------------------------------------

    def test_record_keeps_the_fixed_shape_and_nothing_else(self):
        store = DiagnosticsStore(self.data_dir)
        self.assertTrue(store.record("save_daily_plan", "failed", "VERSION_CONFLICT"))
        events = store.recent_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(
            set(event), {"event_type", "time", "result", "error_code"}
        )
        self.assertEqual(event["event_type"], "save_daily_plan")
        self.assertEqual(event["result"], "failed")
        self.assertEqual(event["error_code"], "VERSION_CONFLICT")
        # The time is a real UTC second-resolution stamp.
        parsed = datetime.strptime(event["time"], "%Y-%m-%dT%H:%M:%SZ")
        self.assertLessEqual(
            parsed.replace(tzinfo=timezone.utc),
            datetime.now(timezone.utc),
        )

    def test_invalid_shapes_are_dropped_not_guessed(self):
        store = DiagnosticsStore(self.data_dir)
        invalid = [
            ("not-a-type", "ok", None),
            ("export_word", "green", None),
            ("export_word", "ok", "SHOULD_NOT_BE_HERE"),
            ("export_word", "failed", None),
            ("export_word", "unknown", None),
        ]
        for event_type, result, code in invalid:
            with self.subTest(event_type=event_type, result=result, code=code):
                self.assertFalse(
                    store.record(event_type, result, code),
                )
        self.assertEqual(store.recent_events(), [])

    def test_unknown_codes_merge_to_the_fixed_unknown_error(self):
        # A code outside the shared finite vocabulary (a crafted canary, a
        # lowercase typo, an over-long value) is merged at collection: the
        # event still records the failure, but only as UNKNOWN_ERROR.
        store = DiagnosticsStore(self.data_dir)
        for code in (
            "SYNTHETIC_PRIVATE_CANARY",
            "lowercase",
            "x" * 100,
        ):
            with self.subTest(code=code[:12]):
                self.assertTrue(store.record("export_word", "failed", code))
        events = store.recent_events()
        self.assertEqual(len(events), 3)
        for event in reversed(events):
            self.assertEqual(event["error_code"], "UNKNOWN_ERROR")

    # -- bounds ------------------------------------------------------------

    def test_store_is_bounded_by_count(self):
        store = DiagnosticsStore(self.data_dir)
        for _ in range(diagnostics_module.MAX_STORED_EVENTS + 40):
            self.assertTrue(store.record("local_backup", "ok"))
        self.assertEqual(
            len(store.recent_events(limit=10**6)),
            diagnostics_module.MAX_STORED_EVENTS,
        )
        # The newest events survive; the oldest are dropped.
        events = store.recent_events()
        self.assertEqual(events[0]["event_type"], "local_backup")
        self.assertEqual(
            len(store.recent_events(limit=diagnostics_module.FEEDBACK_MAX_EVENTS)),
            diagnostics_module.FEEDBACK_MAX_EVENTS,
        )

    def test_store_is_bounded_by_age(self):
        store = DiagnosticsStore(self.data_dir)
        # Seed through the public API, then age the stored stamps past the
        # retention window by rewriting only the time field.
        self.assertTrue(store.record("webdav_backup", "ok"))
        self.assertTrue(
            store.record("webdav_backup", "failed", "WEBDAV_BACKUP_FAILED")
        )
        stale = (
            datetime.now(timezone.utc)
            - timedelta(days=diagnostics_module.MAX_AGE_DAYS + 5)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        with store._lock:  # noqa: SLF001 - test-only age injection
            for event in store._events:  # noqa: SLF001
                event["time"] = stale
        # A fresh record prunes the aged events.
        self.assertTrue(store.record("export_word", "ok"))
        events = store.recent_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "export_word")

    def test_restart_load_applies_the_historical_retention(self):
        # A restarted application recovers only events still inside the
        # retention window; the aged ones are dropped at load, not kept.
        store = DiagnosticsStore(self.data_dir)
        self.assertTrue(store.record("export_word", "ok"))
        self.assertTrue(store.record("local_backup", "canceled"))
        target = self.data_dir / "diagnostics-events.json"
        payload = json.loads(target.read_text("utf-8"))
        stale = (
            datetime.now(timezone.utc)
            - timedelta(days=diagnostics_module.MAX_AGE_DAYS + 5)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload["events"][0]["time"] = stale
        target.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        reopened = DiagnosticsStore(self.data_dir)
        events = reopened.recent_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "local_backup")

    def test_recent_window_limits_count(self):
        store = DiagnosticsStore(self.data_dir)
        for _ in range(30):
            self.assertTrue(store.record("update_check", "ok"))
        events = store.recent_events(limit=10)
        self.assertEqual(len(events), 10)

    # -- persistence -------------------------------------------------------

    def test_events_survive_a_restart_via_the_store_file(self):
        store = DiagnosticsStore(self.data_dir)
        self.assertTrue(
            store.record("export_word", "failed", "SAVE_PERMISSION_DENIED")
        )
        self.assertTrue(store.record("local_backup", "canceled"))
        # A brand-new instance (a restarted application) reads the same file.
        reopened = DiagnosticsStore(self.data_dir)
        events = reopened.recent_events()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["result"], "canceled")
        self.assertEqual(
            events[1]["error_code"], "SAVE_PERMISSION_DENIED"
        )
        # The file lives inside the configured data directory only.
        files = list(self.data_dir.iterdir())
        self.assertEqual(
            [path.name for path in files], ["diagnostics-events.json"]
        )
        payload = json.loads(
            (self.data_dir / "diagnostics-events.json").read_text("utf-8")
        )
        self.assertEqual(payload["version"], 1)
        self.assertEqual(len(payload["events"]), 2)

    def test_concurrent_records_stay_ordered_without_loss(self):
        # The memory update, pruning and persistence run under one lock hold:
        # two threads recording concurrently produce exactly both events and
        # the persisted file always matches the memory snapshot.
        store = DiagnosticsStore(self.data_dir)
        workers = 8
        per_worker = 10

        def worker(index: int) -> None:
            for step in range(per_worker):
                store.record(
                    "export_word",
                    "failed" if step % 2 else "ok",
                    "SAVE_IO_ERROR" if step % 2 else None,
                )

        threads = [
            threading.Thread(target=worker, args=(index,))
            for index in range(workers)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        events = store.recent_events(limit=10**6)
        self.assertEqual(len(events), workers * per_worker)
        reopened = DiagnosticsStore(self.data_dir)
        self.assertEqual(
            len(reopened.recent_events(limit=10**6)), workers * per_worker
        )

    def test_unbound_store_is_memory_only_and_never_writes(self):
        store = DiagnosticsStore(None)
        self.assertTrue(store.record("export_word", "ok"))
        self.assertEqual(len(store.recent_events()), 1)
        self.assertEqual(list(Path(self._tempdir.name).rglob("*.json")), [])

    def test_corrupt_store_file_is_ignored(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        target = self.data_dir / "diagnostics-events.json"
        target.write_text("{not valid json", encoding="utf-8")
        store = DiagnosticsStore(self.data_dir)
        self.assertEqual(store.recent_events(), [])
        # Recording recovers and rewrites a valid file.
        self.assertTrue(store.record("update_download", "ok"))
        reopened = DiagnosticsStore(self.data_dir)
        self.assertEqual(len(reopened.recent_events()), 1)

    def test_oversized_store_file_is_ignored_after_a_bounded_read(self):
        # The recovery read is bounded: an over-cap file is refused without
        # ever being fully read, and recording then rewrites a valid one.
        self.data_dir.mkdir(parents=True, exist_ok=True)
        target = self.data_dir / "diagnostics-events.json"
        target.write_bytes(b"{" + b" " * (MAX_STORE_FILE_BYTES + 64))
        store = DiagnosticsStore(self.data_dir)
        self.assertEqual(store.recent_events(), [])
        self.assertTrue(store.record("local_backup", "ok"))
        reopened = DiagnosticsStore(self.data_dir)
        self.assertEqual(len(reopened.recent_events()), 1)

    def test_same_directory_rebind_keeps_the_in_memory_state(self):
        # Same-directory re-entry is a no-op: it never reloads or resets.
        store = DiagnosticsStore(self.data_dir)
        self.assertTrue(store.record("export_word", "ok"))
        with store._lock:  # noqa: SLF001 - white-box: seed an unpersisted event
            store._events.append(  # noqa: SLF001
                {
                    "event_type": "local_backup",
                    "time": "2026-11-24T00:00:00Z",
                    "result": "ok",
                    "error_code": None,
                }
            )
        store.bind(self.data_dir)
        self.assertEqual(
            len(store.recent_events()), 2,
            "a same-directory rebind must keep the in-memory state",
        )

    def test_slow_recovery_read_cannot_leak_across_a_rebind(self):
        # A blocked recovery read for one directory must never land in
        # another directory's snapshot when the store is rebound while the
        # read is in flight (the acceptance harness models a slow disk
        # read): the bind swap, the read and the snapshot replacement are
        # ordered under the same lock as record.
        import builtins
        from unittest.mock import patch

        root_a = Path(self._tempdir.name) / "teacher-a"
        root_b = Path(self._tempdir.name) / "teacher-b"
        store_a = DiagnosticsStore(root_a)
        self.assertTrue(store_a.record("save_daily_plan", "ok"))
        store_b = DiagnosticsStore(root_b)
        self.assertTrue(store_b.record("save_listening", "ok"))
        store = DiagnosticsStore()
        started = threading.Event()
        resume = threading.Event()
        original_open = builtins.open

        def pause(file, *args, **kwargs):
            handle = original_open(file, *args, **kwargs)
            if (
                isinstance(file, (str, Path))
                and Path(file).parent == root_a
                and args
                and args[0] == "rb"
            ):
                started.set()
                self.assertTrue(resume.wait(8))
            return handle

        with patch("builtins.open", pause):
            first = threading.Thread(target=store.bind, args=(root_a,))
            first.start()
            self.assertTrue(
                started.wait(5), "the recovery read for root A began"
            )
            second = threading.Thread(target=store.bind, args=(root_b,))
            second.start()
            second.join(0.4)
            resume.set()
            first.join(10)
            second.join(10)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(
            [event["event_type"] for event in store.recent_events()],
            ["save_listening"],
            "a stale recovery read from the previous root must never leak"
            " into the newly bound root's snapshot",
        )

    # -- never raises ------------------------------------------------------

    def test_module_record_and_read_never_raise(self):
        diagnostics_module.configure(self.data_dir)
        self.assertTrue(diagnostics_module.record("export_word", "ok"))
        events = diagnostics_module.recent_events()
        self.assertEqual(len(events), 1)
        # Invalid module-level calls are dropped, not raised.
        self.assertFalse(diagnostics_module.record("nope", "ok"))
        self.assertTrue(diagnostics_module.record("nope", "ok") is False)

    def test_configure_rebind_resets_memory_for_a_new_directory(self):
        diagnostics_module.configure(self.data_dir)
        self.assertTrue(diagnostics_module.record("export_word", "ok"))
        self.assertEqual(len(diagnostics_module.recent_events()), 1)
        other = Path(self._tempdir.name) / "other-data"
        diagnostics_module.configure(other)
        self.assertEqual(
            diagnostics_module.recent_events(), [],
            "a rebound directory starts from its own file",
        )
        # The first directory keeps its own persisted events; the new one
        # starts empty and never borrows another directory's history.
        self.assertTrue((self.data_dir / "diagnostics-events.json").exists())
        self.assertFalse((other / "diagnostics-events.json").exists())


class SaveEventClassificationTests(unittest.TestCase):
    """The fixed save classes for real local API write-route failures."""

    def test_status_classes_map_to_the_fixed_vocabulary(self):
        from app.local.errors import (
            LocalPlanNotFound,
            LocalStorageError,
            LocalValidationError,
            LocalVersionConflict,
            LocalWeeklyInvalid,
        )

        cases = [
            (LocalValidationError(), "VALIDATION_FAILED"),
            (LocalWeeklyInvalid(), "VALIDATION_FAILED"),
            (LocalVersionConflict(), "VERSION_CONFLICT"),
            (LocalStorageError(), "STORAGE_FAILED"),
            # Anything unclassifiable merges to the fixed unknown code.
            (LocalPlanNotFound(), "UNKNOWN_ERROR"),
            (RuntimeError("raw exception text"), "UNKNOWN_ERROR"),
        ]
        for exc, expected in cases:
            with self.subTest(code=getattr(exc, "code", "")):
                self.assertEqual(save_error_code(exc), expected)

    def test_records_save_event_records_outcomes_and_propagates(self):
        from app.local.errors import LocalValidationError, LocalVersionConflict

        @records_save_event("save_daily_plan")
        def succeed() -> str:
            return "saved"

        @records_save_event("save_daily_plan")
        def refuse_validation() -> str:
            raise LocalValidationError("原始校验文本不带出")

        @records_save_event("save_daily_plan")
        def refuse_conflict() -> str:
            raise LocalVersionConflict()

        with tempfile.TemporaryDirectory(prefix="kgm-save-event-") as raw:
            data_dir = Path(raw) / "data"
            store = DiagnosticsStore(data_dir)
            original_store = diagnostics_module._store  # noqa: SLF001
            original_dir = original_store._data_dir  # noqa: SLF001
            original_events = list(original_store._events)  # noqa: SLF001
            diagnostics_module._store = store  # noqa: SLF001
            try:
                self.assertEqual(succeed(), "saved")
                with self.assertRaises(LocalValidationError):
                    refuse_validation()
                with self.assertRaises(LocalVersionConflict):
                    refuse_conflict()
            finally:
                diagnostics_module._store = original_store  # noqa: SLF001
                original_store._data_dir = original_dir  # noqa: SLF001
                original_store._events = original_events  # noqa: SLF001
            events = store.recent_events()
            # Newest first: the conflict, the validation refusal, the success.
            self.assertEqual(
                [
                    (event["result"], event["error_code"])
                    for event in events
                ],
                [
                    ("failed", "VERSION_CONFLICT"),
                    ("failed", "VALIDATION_FAILED"),
                    ("ok", None),
                ],
            )

    def test_unknown_save_event_type_is_refused_at_import_time(self):
        with self.assertRaises(ValueError):
            records_save_event("not-a-route-family")


if __name__ == "__main__":
    unittest.main()
