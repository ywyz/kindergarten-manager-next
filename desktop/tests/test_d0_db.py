"""D0-2/D0-3: SQLite probe persistent write, failure semantics, meta facts."""

import sqlite3

import pytest
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError

from d0_db import SQLiteProbe


@pytest.fixture()
def probe(tmp_path):
    client = SQLiteProbe(tmp_path / "data")
    yield client
    client.close()


class TestSaveAndReadBack:
    def test_first_save_and_readback(self, probe):
        result = probe.save("D0 合成探针第一条")
        assert result["status"] == "saved"
        assert result["version"] == 1
        row = probe.read()
        assert row["status"] == "ok"
        assert row["content"] == "D0 合成探针第一条"
        assert row["version"] == 1

    def test_repeated_save_increments_version(self, probe):
        probe.save("v1")
        result = probe.save("v2 内容更新")
        assert result["status"] == "saved" and result["version"] == 2
        assert probe.read()["content"] == "v2 内容更新"
        assert probe.read()["version"] == 2

    def test_data_outlives_probe_object(self, probe, tmp_path):
        probe.save("退出前的内容")
        # A fresh instance = a fresh process start with the same data dir.
        reopened = SQLiteProbe(tmp_path / "data")
        try:
            row = reopened.read()
            assert row["status"] == "ok"
            assert row["content"] == "退出前的内容"
            assert row["version"] == 1
            followup = reopened.save("重启后的写入")
            assert followup["status"] == "saved"
            assert followup["version"] == 2
        finally:
            reopened.close()


class TestFailureSemantics:
    def test_simulated_failure_preserves_previous_record(self, probe):
        probe.save("原记录")
        failed = probe.save("不会保存的内容", simulate_failure=True)
        assert failed["status"] == "failed"
        assert failed["error_kind"] == "integrity"
        row = probe.read()
        assert row["content"] == "原记录"   # original preserved
        assert row["version"] == 1        # not incremented by the failed write

    def test_retry_after_failure_succeeds_with_next_version(self, probe):
        probe.save("原记录")
        assert probe.save("无效内容", simulate_failure=True)["status"] == "failed"
        retried = probe.save("重试成功")
        assert retried["status"] == "saved"
        assert retried["version"] == 2

    def test_schema_constraint_reachable(self, probe):
        # The failure comes from a real CHECK constraint, not a test hook.
        with pytest.raises(SQLAlchemyIntegrityError):
            with probe.engine.connect() as conn:
                conn.exec_driver_sql("BEGIN IMMEDIATE")
                conn.exec_driver_sql(
                    "INSERT INTO probe_synthetic_note VALUES (2, 'x', 1, 'x')"
                )

    def test_empty_state(self, probe):
        assert probe.read() == {"status": "empty"}


class TestMeta:
    def test_meta_reports_stack_facts(self, probe):
        meta = probe.meta()
        assert meta["dialect"] == "sqlite"
        assert meta["driver"] == "pysqlite"
        assert sqlite3.sqlite_version == meta["sqlite_library_version"]
        assert meta["foreign_keys_pragma"] == 1
        assert meta["journal_mode"] == "wal"
        assert meta["data_dir"] == str(probe.data_dir)
