"""R01 持久测试：0004 物理迁移与 D2 初始化。

使用真实 Alembic（不只是 create_all）验证：
- 新空库基线到 head：15 张 D2 表、全部 FK/UQ/CHECK/索引、3 个冻结 bundle、created_at
- 旧 0001/0002/0003 库升级：D1 历史不变、AI state/个人提示头/空游戏头一次性种子、不增 D1 config_version
- profile_service.initialize 新档案：与迁移种子等价
- 负例：active nonce=NULL、非法整数/枚举/版本、跨计划关系、双活跃任务、伪 execution/config/personal/bundle 引用

所有测试明确合成临时根，不触及真实教师库/密钥目录。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from alembic import command
from sqlalchemy import CheckConstraint, inspect
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError

_SQLITE_INTEGRITY_ERRORS = (sqlite3.IntegrityError, SQLAlchemyIntegrityError)

from app.local import daily_plan_service, profile_service
from app.local.base import LocalBase
from app.local.errors import LocalStorageError
from app.local.migrate import (
    alembic_config,
    ensure_local_schema,
    head_revision,
)
from app.local.normalize import normalize_initialization
from app.local.runtime import LocalRuntime
from app.local.sqlite import LOCAL_VERSION_TABLE
from tests.local.support import (
    LocalTestCase,
    StaticCalendarProvider,
    assert_inside,
    calendar_provider,
    execute_sql,
    initialize_body,
    query_rows,
    query_scalar,
    sqlite_connect,
)

OLD_HEAD_REVISION = "20261014_0003_local"

OLD_PROFILE_ID = "profile-d2-old-0001-abcdef"
OLD_CLASS_ID = "class-d2-old-0001-abcdefgh"
OLD_TERM_ID = "term-d2-old-0001-abcdefgh"
OLD_REVISION_ID = "rev-d2-old-0001-abcdefghij"

EXPECTED_D2_TABLES = {
    "local_ai_state",
    "local_ai_credentials",
    "local_ai_config_versions",
    "local_class_game_revisions",
    "local_class_game_heads",
    "local_prompt_bundles",
    "local_personal_prompt_versions",
    "local_personal_prompt_heads",
    "local_ai_inputs",
    "local_ai_tasks",
    "local_ai_executions",
    "local_ai_attempts",
    "local_ai_candidates",
    "local_daily_plan_ai_provenance",
    "local_ai_operations",
}

# 严格整数字段：typeof 必须为 'integer' 且满足范围
STRICT_INT_COLUMNS = {
    "local_ai_config_versions": [("version", 1)],
    "local_class_game_revisions": [("revision_no", 1)],
    "local_prompt_bundles": [
        ("contract_version", 1),
        ("default_revision", 1),
    ],
    "local_personal_prompt_versions": [
        ("revision", 1),
        ("contract_version", 1),
        ("based_default_revision", 1),
    ],
    "local_personal_prompt_heads": [
        ("current_revision", 1),
        ("required_contract_version", 1),
        ("latest_default_revision", 1),
    ],
    "local_ai_inputs": [("input_schema_version", 1)],
    "local_ai_tasks": [("generation", 0)],
    "local_ai_executions": [
        ("generation", 1),
        ("config_version", 1),
        ("personal_revision", 1),
        ("contract_version", 1),
        ("default_revision", 1),
    ],
    "local_ai_attempts": [("attempt_no", 1)],
    "local_ai_candidates": [
        ("contract_version", 1),
        ("schema_version", 1),
    ],
}

# 可空版本列，按真实机制分别取证据：
# - "fk"    ：无独立 CHECK，仅以 deferred FK 引用已存在正整数 config 版本；
#             NULL/1 正向成功，坏值在 commit 精确抛 SQLITE_CONSTRAINT_FOREIGNKEY。
# - "check" ：列本身有 typeof CHECK；坏值在 INSERT 精确抛 SQLITE_CONSTRAINT_CHECK。
# 不使用冗余 CHECK 迎合措辞，也不削弱 FK。
NULLABLE_VERSION_COLUMNS = {
    "local_ai_state": {
        "current_config_version": "fk",
        "blocked_config_version": "fk",
    },
    "local_personal_prompt_versions": {
        "rejected_default_revision": "check",
    },
}

D2_TABLES_WITH_CREATED_AT = {
    "local_ai_executions",
    "local_class_game_heads",
    "local_personal_prompt_heads",
}


def _normalize_check(sql_text: str) -> str:
    """只规范空白与大小写：不移除 typeof、约束条件或任何运算符。"""
    return " ".join(str(sql_text).split()).lower()


class D2SchemaTests(LocalTestCase):
    """R01：物理迁移与初始化持久测试。"""

    def setUp(self) -> None:
        super().setUp()
        self.provider = StaticCalendarProvider()
        self.enterContext(calendar_provider(self.provider))

    def make_runtime(self, data_dir: Path | None = None) -> LocalRuntime:
        """R01: never inherit the default (real) credential root.

        Every runtime in this module injects an explicit temporary
        ``credential_root`` under the test temp root so no test can reach
        ``%LOCALAPPDATA%\\KindergartenManager\\credentials``. The older
        shared ``support.make_runtime`` is adjusted in R09.
        """
        target = data_dir or self.data_dir
        target.mkdir(parents=True, exist_ok=True)
        credential_root = self.tmp_root / f"{target.name}-credential-root"
        runtime = LocalRuntime(data_dir=target, credential_root=credential_root)
        assert_inside(self.tmp_root, runtime.db_path)
        runtime.prepare()
        self.addCleanup(runtime.dispose)
        return runtime

    # -- 新空库 -----------------------------------------------------------

    def test_fresh_db_baselines_to_head_with_all_d2_constraints(self):
        runtime = self.make_runtime()
        db = runtime.db_path
        versions = query_rows(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}")
        self.assertEqual([row["version_num"] for row in versions], [head_revision()])

        tables = {
            row["name"]
            for row in query_rows(
                db, "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertTrue(EXPECTED_D2_TABLES <= tables, tables)
        self.assertEqual(query_rows(db, "PRAGMA foreign_key_check"), [])

        # 3 个冻结 bundle：contract_version=1, default_revision=1
        bundles = query_rows(
            db,
            "SELECT task_type, contract_version, default_revision, bundle_hash "
            "FROM local_prompt_bundles ORDER BY task_type",
        )
        self.assertEqual(len(bundles), 3)
        for b in bundles:
            self.assertEqual(b["contract_version"], 1)
            self.assertEqual(b["default_revision"], 1)
            self.assertIsNotNone(b["bundle_hash"])
            self.assertEqual(len(b["bundle_hash"]), 64)

        # created_at 存在于所有 D2 表（包括曾遗漏的 3 表）
        for table in EXPECTED_D2_TABLES:
            cols = {
                row["name"] for row in query_rows(db, f"PRAGMA table_info('{table}')")
            }
            self.assertIn("created_at", cols, f"{table} 缺少 created_at")

    def test_strict_int_check_rejects_float_text_zero(self):
        """CHECK typeof(x)='integer' 必须拒绝 1.5、'abc'、0。"""
        runtime = self.make_runtime()
        db = runtime.db_path
        conn = sqlite_connect(db)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO local_profile (id, singleton, display_name, created_at, updated_at) "
                "VALUES ('p1', 1, '测试', '2026-10-17 00:00:00', '2026-10-17 00:00:00')"
            )
            # version = 1.5 应拒绝
            with self.assertRaises(_SQLITE_INTEGRITY_ERRORS):
                conn.execute(
                    "INSERT INTO local_ai_config_versions "
                    "(profile_id, version, protocol_id, created_at) "
                    "VALUES ('p1', 1.5, 'chat_completions_v1', '2026-10-17 00:00:00')"
                )
            # version = 'abc' 应拒绝
            with self.assertRaises(_SQLITE_INTEGRITY_ERRORS):
                conn.execute(
                    "INSERT INTO local_ai_config_versions "
                    "(profile_id, version, protocol_id, created_at) "
                    "VALUES ('p1', 'abc', 'chat_completions_v1', '2026-10-17 00:00:00')"
                )
            # version = 0 应拒绝（>=1）
            with self.assertRaises(_SQLITE_INTEGRITY_ERRORS):
                conn.execute(
                    "INSERT INTO local_ai_config_versions "
                    "(profile_id, version, protocol_id, created_at) "
                    "VALUES ('p1', 0, 'chat_completions_v1', '2026-10-17 00:00:00')"
                )
            # 合法 version = 1 应成功
            conn.execute(
                "INSERT INTO local_ai_config_versions "
                "(profile_id, version, protocol_id, created_at) "
                "VALUES ('p1', 1, 'chat_completions_v1', '2026-10-17 00:00:00')"
            )
            conn.execute("COMMIT")
        finally:
            conn.rollback()
            conn.close()

    # -- 旧库升级 ---------------------------------------------------------

    def _seed_d1_old_schema(self, db: Path) -> None:
        """用原生 SQL 种子 D1A/D1B 历史数据（在 0003 schema 下）。"""
        statements = [
            f"INSERT INTO local_profile (id, singleton, display_name, created_at, updated_at) "
            f"VALUES ('{OLD_PROFILE_ID}', 1, '王老师', '2026-10-12 00:00:00', '2026-10-12 00:00:00')",
            f"INSERT INTO local_classes (id, name, grade, created_at, updated_at) "
            f"VALUES ('{OLD_CLASS_ID}', '中一班', 'middle', '2026-10-12 00:00:00', '2026-10-12 00:00:00')",
            f"INSERT INTO local_terms (id, name, start_date, end_date, current_calendar_revision_id, created_at, updated_at) "
            f"VALUES ('{OLD_TERM_ID}', '2026 秋季学期', '2026-09-01', '2026-09-30', '{OLD_REVISION_ID}', '2026-10-12 00:00:00', '2026-10-12 00:00:00')",
            f"INSERT INTO local_calendar_revisions (id, term_id, revision_no, library_version, created_by, created_at) "
            f"VALUES ('{OLD_REVISION_ID}', '{OLD_TERM_ID}', 1, 'seed-v1', '{OLD_PROFILE_ID}', '2026-10-12 00:00:00')",
            f"INSERT INTO local_settings (id, singleton, school_name, current_class_id, init_request_id, init_input_fingerprint, config_version, created_at, updated_at) "
            f"VALUES ('singleton', 1, '示范幼儿园', '{OLD_CLASS_ID}', '00000000-0000-4000-8000-000000000001', '{'a' * 64}', 1, '2026-10-12 00:00:00', '2026-10-12 00:00:00')",
        ]
        for day in range(1, 31):
            date_text = f"2026-09-{day:02d}"
            statements.append(
                f"INSERT INTO local_calendar_days (revision_id, date, base_state, base_library_version, "
                f"override_state, override_reason, effective_state) "
                f"VALUES ('{OLD_REVISION_ID}', '{date_text}', 'teaching', 'seed-v1', NULL, NULL, 'teaching')"
            )
        execute_sql_multi(db, statements)

    def test_upgrade_from_0003_with_d1_history_seeds_d2_once(self):
        self.enterContext(calendar_provider(StaticCalendarProvider()))
        data_dir = self.tmp_root / "d2-upgrade"
        data_dir.mkdir(parents=True, exist_ok=True)
        db = data_dir / "kindergarten.db"

        # 先升级到 0003
        command.upgrade(alembic_config(db), OLD_HEAD_REVISION)
        self.assertEqual(
            query_scalar(db, f"SELECT version_num FROM {LOCAL_VERSION_TABLE}"),
            OLD_HEAD_REVISION,
        )

        # 种子 D1 历史数据
        self._seed_d1_old_schema(db)
        d1_config_version = query_scalar(db, "SELECT config_version FROM local_settings")
        self.assertEqual(d1_config_version, 1)

        # W1 冷升级
        inspection = ensure_local_schema(db)
        self.assertEqual(inspection.state, "current")
        self.assertEqual(inspection.current_revision, head_revision())

        # D1 历史不变
        self.assertEqual(
            query_scalar(db, f"SELECT count(*) FROM local_profile"), 1
        )
        self.assertEqual(
            query_scalar(db, "SELECT config_version FROM local_settings"), 1
        )

        # D2 种子一次性建立
        ai_state = query_rows(
            db, "SELECT * FROM local_ai_state WHERE profile_id = ?", (OLD_PROFILE_ID,)
        )
        self.assertEqual(len(ai_state), 1)
        self.assertIsNotNone(ai_state[0]["database_uuid"])
        self.assertIsNone(ai_state[0]["current_config_version"])

        bundles = query_rows(db, "SELECT count(*) AS n FROM local_prompt_bundles")
        self.assertEqual(bundles[0]["n"], 3)

        heads = query_rows(
            db, "SELECT count(*) AS n FROM local_personal_prompt_heads WHERE profile_id = ?",
            (OLD_PROFILE_ID,),
        )
        self.assertEqual(heads[0]["n"], 3)

        game_rev = query_rows(
            db, "SELECT count(*) AS n FROM local_class_game_revisions WHERE class_id = ?",
            (OLD_CLASS_ID,),
        )
        self.assertEqual(game_rev[0]["n"], 1)
        game_head = query_rows(
            db, "SELECT count(*) AS n FROM local_class_game_heads WHERE class_id = ?",
            (OLD_CLASS_ID,),
        )
        self.assertEqual(game_head[0]["n"], 1)

        self.assertEqual(query_rows(db, "PRAGMA foreign_key_check"), [])

    # -- profile_service.initialize 新档案 --------------------------------

    def test_profile_service_initialize_seeds_d2_objects(self):
        runtime = self.make_runtime()
        session = runtime.session()
        try:
            normalized = normalize_initialization(**initialize_body())
            payload, created = profile_service.initialize(session, normalized)
            self.assertTrue(created)
            profile_id = payload["profile"]["id"]

            # AI state
            state = query_rows(
                runtime.db_path,
                "SELECT database_uuid, current_config_version FROM local_ai_state WHERE profile_id = ?",
                (profile_id,),
            )
            self.assertEqual(len(state), 1)
            self.assertIsNotNone(state[0]["database_uuid"])
            self.assertIsNone(state[0]["current_config_version"])

            # 3 类个人提示头
            heads = query_rows(
                runtime.db_path,
                "SELECT task_type, current_revision, required_contract_version, latest_default_revision "
                "FROM local_personal_prompt_heads WHERE profile_id = ? ORDER BY task_type",
                (profile_id,),
            )
            self.assertEqual(len(heads), 3)
            for h in heads:
                self.assertEqual(h["current_revision"], 1)
                self.assertEqual(h["required_contract_version"], 1)
                self.assertEqual(h["latest_default_revision"], 1)

            # 空游戏头
            class_id = payload["class"]["id"]
            game_heads = query_rows(
                runtime.db_path,
                "SELECT current_revision_id FROM local_class_game_heads WHERE class_id = ?",
                (class_id,),
            )
            self.assertEqual(len(game_heads), 1)
            game_rev = query_rows(
                runtime.db_path,
                "SELECT revision_no, payload_json FROM local_class_game_revisions WHERE id = ?",
                (game_heads[0]["current_revision_id"],),
            )
            self.assertEqual(len(game_rev), 1)
            self.assertEqual(game_rev[0]["revision_no"], 1)
            payload_json = json.loads(game_rev[0]["payload_json"])
            self.assertEqual(payload_json, {"locations": [], "game_scope": None, "guidance": None})

            self.assertEqual(query_rows(runtime.db_path, "PRAGMA foreign_key_check"), [])
        finally:
            session.close()

    # -- ORM 元数据与真实库逐表 CHECK 对照 ------------------------------

    def test_orm_metadata_matches_reflected_checks_table_by_table(self):
        """真实 Alembic 库与 ORM 元数据逐表比较 CHECK（忽略空白/大小写）。

        显式注入临时 credential_root，基真实 Alembic 库（非 create_all）
        反射，并和 LocalBase.metadata 逐表比较 CHECK 条件；typeof 等
        约束条件不被弱化或移除。
        """
        data_dir = self.tmp_root / "d2-schema-mirror"
        data_dir.mkdir(parents=True, exist_ok=True)
        credential_root = self.tmp_root / "d2-credential-root"
        credential_root.mkdir(parents=True, exist_ok=True)

        runtime = LocalRuntime(data_dir=data_dir, credential_root=credential_root)
        try:
            runtime.prepare()
            engine = runtime.engine
            inspector = inspect(engine)

            reflected_tables = {
                row["name"]
                for row in query_rows(
                    runtime.db_path,
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' AND name != ?",
                    (LOCAL_VERSION_TABLE,),
                )
            }

            # 15 张 D2 表全部落地，且 ORM 元数据全部注册
            self.assertTrue(EXPECTED_D2_TABLES <= reflected_tables, reflected_tables)
            self.assertTrue(
                EXPECTED_D2_TABLES <= set(LocalBase.metadata.tables),
                set(LocalBase.metadata.tables),
            )

            for table_name in sorted(EXPECTED_D2_TABLES):
                with self.subTest(table=table_name):
                    self.assertIn(table_name, reflected_tables, table_name)

                    orm_checks = {
                        _normalize_check(str(c.sqltext))
                        for c in LocalBase.metadata.tables[table_name].constraints
                        if isinstance(c, CheckConstraint)
                    }
                    reflected_checks = {
                        _normalize_check(rc["sqltext"])
                        for rc in inspector.get_check_constraints(table_name)
                    }
                    self.assertEqual(
                        orm_checks,
                        reflected_checks,
                        f"{table_name} CHECK 不一致:\n"
                        f"  ORM 独有: {orm_checks - reflected_checks}\n"
                        f"  反射 独有: {reflected_checks - orm_checks}",
                    )
        finally:
            runtime.dispose()

    # -- 负例 -------------------------------------------------------------

    def _insert_profile(self, conn, profile_id="p-test"):
        conn.execute(
            "INSERT INTO local_profile (id, singleton, display_name, created_at, updated_at) "
            "VALUES (?, 1, '测试', '2026-10-17 00:00:00', '2026-10-17 00:00:00')",
            (profile_id,),
        )

    def _make_runtime_with_credential_root(self, suffix: str) -> LocalRuntime:
        """创建并准备显式注入临时 credential_root 的运行时。"""
        data_dir = self.tmp_root / suffix
        data_dir.mkdir(parents=True, exist_ok=True)
        credential_root = self.tmp_root / f"{suffix}-credential-root"
        credential_root.mkdir(parents=True, exist_ok=True)
        runtime = LocalRuntime(data_dir=data_dir, credential_root=credential_root)
        runtime.prepare()
        self.addCleanup(runtime.dispose)
        return runtime

    def _build_legal_plan_content_input(
        self,
        conn,
        profile_id: str,
        class_id: str,
        term_id: str,
        rev_id: str,
        plan_id: str,
        content_id: str,
        input_id: str,
    ) -> None:
        """建立一套完整已提交的 plan→content→input 合法关系基线。"""
        conn.execute(
            "INSERT INTO local_profile (id, singleton, display_name, created_at, updated_at) "
            "VALUES (?, 1, '测试', '2026-10-17 00:00:00', '2026-10-17 00:00:00')",
            (profile_id,),
        )
        conn.execute(
            "INSERT INTO local_classes (id, name, grade, created_at, updated_at) "
            "VALUES (?, '中一班', 'middle', '2026-10-17 00:00:00', '2026-10-17 00:00:00')",
            (class_id,),
        )
        conn.execute(
            "INSERT INTO local_terms (id, name, start_date, end_date, current_calendar_revision_id, created_at, updated_at) "
            "VALUES (?, 't', '2026-09-01', '2026-09-30', ?, '2026-10-17 00:00:00', '2026-10-17 00:00:00')",
            (term_id, rev_id),
        )
        conn.execute(
            "INSERT INTO local_calendar_revisions (id, term_id, revision_no, library_version, created_by, created_at) "
            "VALUES (?, ?, 1, 'v', ?, '2026-10-17 00:00:00')",
            (rev_id, term_id, profile_id),
        )
        conn.execute(
            "INSERT INTO local_daily_plans (id, class_id, term_id, plan_date, creator_id, week_number, weekday, "
            "calendar_revision_id, current_content_id, current_content_version, creator_display_name, class_name, grade, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, '2026-09-01', ?, 1, 1, ?, ?, 1, 't', '中一班', 'middle', '2026-10-17 00:00:00', '2026-10-17 00:00:00')",
            (plan_id, class_id, term_id, profile_id, rev_id, content_id),
        )
        conn.execute(
            "INSERT INTO local_daily_plan_contents (id, daily_plan_id, version, raw_lesson_plan, adopted_content, editor_id, created_at) "
            "VALUES (?, ?, 1, NULL, '{}', ?, '2026-10-17 00:00:00')",
            (content_id, plan_id, profile_id),
        )
        conn.execute(
            "INSERT INTO local_ai_inputs (id, daily_plan_id, content_id, content_version, task_type, target_grade, "
            "input_schema_version, payload_json, dependencies_json, dependency_hash, target_hashes_json, created_at) "
            "VALUES (?, ?, ?, 1, 'daily_lesson_split', 'middle', 1, '{}', '{}', '{}', '{}', '2026-10-17 00:00:00')",
            (input_id, plan_id, content_id),
        )

    def _build_legal_execution_baseline(
        self,
        conn,
        profile_id: str,
        class_id: str,
        term_id: str,
        rev_id: str,
        plan_id: str,
        content_id: str,
        input_id: str,
        task_id: str,
        execution_id: str,
    ) -> None:
        """建立一套完整已提交的 task+execution+config+personal+bundle 合法关系基线。"""
        self._build_legal_plan_content_input(
            conn, profile_id, class_id, term_id, rev_id, plan_id, content_id, input_id
        )
        conn.execute(
            "INSERT INTO local_ai_tasks (id, profile_id, daily_plan_id, task_type, input_id, status, reason, "
            "current_execution_id, generation, runtime_meta_json, created_at, updated_at) "
            "VALUES (?, ?, ?, 'daily_lesson_split', ?, 'pending', NULL, NULL, 0, '{}', '2026-10-17 00:00:00', '2026-10-17 00:00:00')",
            (task_id, profile_id, plan_id, input_id),
        )
        conn.execute(
            "INSERT INTO local_ai_config_versions (profile_id, version, protocol_id, base_url, model, created_at) "
            "VALUES (?, 1, 'chat_completions_v1', 'https://example.com/v1', 'model-1', '2026-10-17 00:00:00')",
            (profile_id,),
        )
        # local_prompt_bundles 已由 0004 迁移预置 (daily_lesson_split, 1, 1)，此处直接引用。
        conn.execute(
            "INSERT INTO local_personal_prompt_versions (profile_id, task_type, revision, contract_version, "
            "based_default_revision, guidance_json, action, created_at) "
            "VALUES (?, 'daily_lesson_split', 1, 1, 1, '{}', 'initial', '2026-10-17 00:00:00')",
            (profile_id,),
        )
        conn.execute(
            "INSERT INTO local_ai_executions (id, task_id, daily_plan_id, input_id, task_type, generation, "
            "launch_id, permit_id, config_version, profile_id, personal_revision, contract_version, "
            "default_revision, state, runtime_meta_json, started_at, created_at) "
            "VALUES (?, ?, ?, ?, 'daily_lesson_split', 1, 'l1', 'p1', 1, ?, 1, 1, 1, 'pending', '{}', '2026-10-17 00:00:00', '2026-10-17 00:00:00')",
            (execution_id, task_id, plan_id, input_id, profile_id),
        )

    def test_active_credential_null_nonce_rejected(self):
        runtime = self.make_runtime()
        db = runtime.db_path
        conn = sqlite_connect(db)
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._insert_profile(conn)
            with self.assertRaises(_SQLITE_INTEGRITY_ERRORS):
                conn.execute(
                    "INSERT INTO local_ai_credentials (id, profile_id, key_id, nonce, ciphertext, state, created_at, updated_at) "
                    "VALUES ('c1', ?, 'k1', NULL, x'0102030405060708090a0b0c0d0e0f10', 'active', '2026-10-17 00:00:00', '2026-10-17 00:00:00')",
                    ("p-test",),
                )
            conn.rollback()
        finally:
            conn.close()

    def test_cross_plan_ai_input_rejected(self):
        """input 的 daily_plan_id/content_id/version 三元必须存在（立即 FK）。

        先提交一套完整合法的 plan+content+input 基线，再只改 content_id
        为不存在的值，断言立即抛出 SQLITE_CONSTRAINT_FOREIGNKEY。
        """
        runtime = self._make_runtime_with_credential_root("d2-fk-input")
        db = runtime.db_path
        conn = sqlite_connect(db)
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._build_legal_plan_content_input(
                conn, "p-fk-in", "c-fk-in", "t-fk-in", "r-fk-in",
                "plan-fk-in", "content-fk-in", "input-fk-in",
            )
            conn.execute("COMMIT")

            # 单字段变体：只改 content_id 为不存在的引用，其余均合法。
            conn.execute("BEGIN IMMEDIATE")
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                conn.execute(
                    "INSERT INTO local_ai_inputs (id, daily_plan_id, content_id, content_version, task_type, target_grade, "
                    "input_schema_version, payload_json, dependencies_json, dependency_hash, target_hashes_json, created_at) "
                    "VALUES ('input-bad', 'plan-fk-in', 'no-such-content', 1, 'daily_lesson_split', 'middle', 1, '{}', '{}', '{}', '{}', '2026-10-17 00:00:00')"
                )
            self.assertIn("FOREIGN KEY", str(ctx.exception))
            conn.rollback()
        finally:
            conn.close()

    def test_double_active_task_per_plan_type_rejected(self):
        """部分唯一索引：同计划同类型最多一个活跃任务。"""
        runtime = self.make_runtime()
        db = runtime.db_path
        conn = sqlite_connect(db)
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._insert_profile(conn, "p2")
            conn.execute(
                "INSERT INTO local_classes (id, name, grade, created_at, updated_at) "
                "VALUES ('c1', '中一班', 'middle', '2026-10-17 00:00:00', '2026-10-17 00:00:00')"
            )
            conn.execute(
                "INSERT INTO local_terms (id, name, start_date, end_date, current_calendar_revision_id, created_at, updated_at) "
                "VALUES ('t1', 't', '2026-09-01', '2026-09-30', 'r1', '2026-10-17 00:00:00', '2026-10-17 00:00:00')"
            )
            conn.execute(
                "INSERT INTO local_calendar_revisions (id, term_id, revision_no, library_version, created_by, created_at) "
                "VALUES ('r1', 't1', 1, 'v', 'p2', '2026-10-17 00:00:00')"
            )
            conn.execute(
                "INSERT INTO local_daily_plans (id, class_id, term_id, plan_date, creator_id, week_number, weekday, "
                "calendar_revision_id, current_content_id, current_content_version, creator_display_name, class_name, grade, "
                "created_at, updated_at) "
                "VALUES ('plan1', 'c1', 't1', '2026-09-01', 'p2', 1, 1, 'r1', 'c1', 1, 't', '中一班', 'middle', '2026-10-17 00:00:00', '2026-10-17 00:00:00')"
            )
            conn.execute(
                "INSERT INTO local_daily_plan_contents (id, daily_plan_id, version, raw_lesson_plan, adopted_content, editor_id, created_at) "
                "VALUES ('c1', 'plan1', 1, NULL, '{}', 'p2', '2026-10-17 00:00:00')"
            )
            conn.execute(
                "INSERT INTO local_ai_inputs (id, daily_plan_id, content_id, content_version, task_type, target_grade, "
                "input_schema_version, payload_json, dependencies_json, dependency_hash, target_hashes_json, created_at) "
                "VALUES ('in1', 'plan1', 'c1', 1, 'daily_lesson_split', 'middle', 1, '{}', '{}', '{}', '{}', '2026-10-17 00:00:00')"
            )
            conn.execute(
                "INSERT INTO local_ai_tasks (id, profile_id, daily_plan_id, task_type, input_id, status, reason, "
                "current_execution_id, generation, runtime_meta_json, created_at, updated_at) "
                "VALUES ('t1', 'p2', 'plan1', 'daily_lesson_split', 'in1', 'pending', NULL, NULL, 0, '{}', '2026-10-17 00:00:00', '2026-10-17 00:00:00')"
            )
            conn.execute(
                "INSERT INTO local_ai_inputs (id, daily_plan_id, content_id, content_version, task_type, target_grade, "
                "input_schema_version, payload_json, dependencies_json, dependency_hash, target_hashes_json, created_at) "
                "VALUES ('in2', 'plan1', 'c1', 1, 'daily_lesson_split', 'middle', 1, '{}', '{}', '{}', '{}', '2026-10-17 00:00:00')"
            )
            with self.assertRaises(_SQLITE_INTEGRITY_ERRORS):
                conn.execute(
                    "INSERT INTO local_ai_tasks (id, profile_id, daily_plan_id, task_type, input_id, status, reason, "
                    "current_execution_id, generation, runtime_meta_json, created_at, updated_at) "
                    "VALUES ('t2', 'p2', 'plan1', 'daily_lesson_split', 'in2', 'claimed', NULL, NULL, 0, '{}', '2026-10-17 00:00:00', '2026-10-17 00:00:00')"
                )
            conn.rollback()
        finally:
            conn.close()

    def test_fake_execution_config_rejected(self):
        """execution 的 config_version 必须引用存在的 (profile_id, version)（deferred FK，在 commit 处验）。

        先提交一套完整合法的 task+execution+config+personal+bundle 基线，再只改
        config_version 为不存在的 999，其余引用均合法，断言在 commit 时抛出
        SQLITE_CONSTRAINT_FOREIGNKEY。
        """
        runtime = self._make_runtime_with_credential_root("d2-fk-exec")
        db = runtime.db_path
        conn = sqlite_connect(db)
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._build_legal_execution_baseline(
                conn, "p-fk-ex", "c-fk-ex", "t-fk-ex", "r-fk-ex",
                "plan-fk-ex", "content-fk-ex", "input-fk-ex",
                "task-fk-ex", "exec-fk-ex",
            )
            conn.execute("COMMIT")

            # 单字段变体：只改 config_version 为不存在的 999，其余引用均合法。
            # config_version FK 为 deferred，INSERT 本身应成功，在 commit 时抛出。
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO local_ai_executions (id, task_id, daily_plan_id, input_id, task_type, generation, "
                "launch_id, permit_id, config_version, profile_id, personal_revision, contract_version, "
                "default_revision, state, runtime_meta_json, started_at, created_at) "
                "VALUES ('exec-bad', 'task-fk-ex', 'plan-fk-ex', 'input-fk-ex', 'daily_lesson_split', 2, 'l1', 'p1', 999, "
                "'p-fk-ex', 1, 1, 1, 'pending', '{}', '2026-10-17 00:00:00', '2026-10-17 00:00:00')"
            )
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                conn.execute("COMMIT")
            self.assertIn("FOREIGN KEY", str(ctx.exception))
            conn.rollback()
        finally:
            conn.close()

    # -- R01：完整合法图、单因子关系、严格整数、枚举与种子等价 -----------

    _TS = "2026-10-17 00:00:00"
    _ALL_TASKS = (
        "daily_lesson_split",
        "daily_process_adapt",
        "daily_other_activities",
    )
    _EXPECTED_EMPTY_GAME = {"locations": [], "game_scope": None, "guidance": None}
    _DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"

    def _build_full_legal_graph(self, conn, p, c, t, r):
        """插入一个完整可提交的合法 D2 图（profile p）。

        返回计划 a/b 的 content/input/task/execution/candidate id、p/c/t/r，
        以及一个没有 candidate 的额外 execution（供候选列遍历复用）。
        """
        ts = self._TS
        conn.execute(
            "INSERT INTO local_profile (id, singleton, display_name, created_at, updated_at) "
            "VALUES (?, 1, '测试', ?, ?)", (p, ts, ts))
        conn.execute(
            "INSERT INTO local_classes (id, name, grade, created_at, updated_at) "
            "VALUES (?, '中一班', 'middle', ?, ?)", (c, ts, ts))
        conn.execute(
            "INSERT INTO local_terms (id, name, start_date, end_date, current_calendar_revision_id, created_at, updated_at) "
            "VALUES (?, 't', '2026-09-01', '2026-09-30', ?, ?, ?)", (t, r, ts, ts))
        conn.execute(
            "INSERT INTO local_calendar_revisions (id, term_id, revision_no, library_version, created_by, created_at) "
            "VALUES (?, ?, 1, 'v', ?, ?)", (r, t, p, ts))
        conn.execute(
            "INSERT INTO local_ai_config_versions (profile_id, version, protocol_id, base_url, model, created_at) "
            "VALUES (?, 1, 'chat_completions_v1', 'https://example.com/v1', 'm', ?)", (p, ts))
        conn.execute(
            "INSERT INTO local_personal_prompt_versions (profile_id, task_type, revision, contract_version, "
            "based_default_revision, guidance_json, action, created_at) "
            "VALUES (?, 'daily_lesson_split', 1, 1, 1, '{}', 'initial', ?)", (p, ts))
        conn.execute(
            "INSERT INTO local_personal_prompt_heads (profile_id, task_type, current_revision, "
            "required_contract_version, latest_default_revision, created_at, updated_at) "
            "VALUES (?, 'daily_lesson_split', 1, 1, 1, ?, ?)", (p, ts, ts))
        conn.execute(
            "INSERT INTO local_ai_state (profile_id, database_uuid, current_config_version, "
            "blocked_config_version, blocked_reason, created_at, updated_at) "
            "VALUES (?, ?, NULL, NULL, NULL, ?, ?)", (p, f"{p}-uuid", ts, ts))
        game_rev = f"{p}-game-rev"
        conn.execute(
            "INSERT INTO local_class_game_revisions (id, class_id, revision_no, payload_json, payload_hash, created_at) "
            "VALUES (?, ?, 1, '{}', ?, ?)", (game_rev, c, "h" * 64, ts))
        conn.execute(
            "INSERT INTO local_class_game_heads (class_id, current_revision_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)", (c, game_rev, ts, ts))
        ids = {}
        for key, day in (("a", "01"), ("b", "02")):
            plan = f"{p}-plan-{key}"
            content = f"{p}-content-{key}"
            inp = f"{p}-input-{key}"
            task = f"{p}-task-{key}"
            exe = f"{p}-exec-{key}"
            cand = f"{p}-cand-{key}"
            conn.execute(
                "INSERT INTO local_daily_plans (id, class_id, term_id, plan_date, creator_id, week_number, weekday, "
                "calendar_revision_id, current_content_id, current_content_version, creator_display_name, class_name, grade, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?, 1, '测试', '中一班', 'middle', ?, ?)",
                (plan, c, t, f"2026-09-{day}", p, r, content, ts, ts))
            conn.execute(
                "INSERT INTO local_daily_plan_contents (id, daily_plan_id, version, raw_lesson_plan, adopted_content, editor_id, created_at) "
                "VALUES (?, ?, 1, NULL, '{}', ?, ?)", (content, plan, p, ts))
            conn.execute(
                "INSERT INTO local_ai_inputs (id, daily_plan_id, content_id, content_version, task_type, target_grade, "
                "input_schema_version, payload_json, dependencies_json, dependency_hash, target_hashes_json, created_at) "
                "VALUES (?, ?, ?, 1, 'daily_lesson_split', 'middle', 1, '{}', '{}', '{}', '{}', ?)",
                (inp, plan, content, ts))
            conn.execute(
                "INSERT INTO local_ai_tasks (id, profile_id, daily_plan_id, task_type, input_id, status, reason, "
                "current_execution_id, generation, runtime_meta_json, created_at, updated_at) "
                "VALUES (?, ?, ?, 'daily_lesson_split', ?, 'pending', NULL, ?, 0, '{}', ?, ?)",
                (task, p, plan, inp, exe, ts, ts))
            conn.execute(
                "INSERT INTO local_ai_executions (id, task_id, daily_plan_id, input_id, task_type, generation, "
                "launch_id, permit_id, config_version, profile_id, personal_revision, contract_version, "
                "default_revision, state, runtime_meta_json, started_at, created_at) "
                "VALUES (?, ?, ?, ?, 'daily_lesson_split', 1, ?, ?, 1, ?, 1, 1, 1, 'pending', '{}', ?, ?)",
                (exe, task, plan, inp, f"l-{key}", f"p-{key}", p, ts, ts))
            conn.execute(
                "INSERT INTO local_ai_candidates (id, execution_id, task_id, daily_plan_id, input_id, task_type, "
                "contract_version, schema_version, raw_candidate_json, candidate_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'daily_lesson_split', 1, 1, '{}', ?, ?)",
                (cand, exe, task, plan, inp, "h" * 64, ts))
            conn.execute(
                "INSERT INTO local_daily_plan_ai_provenance (content_id, daily_plan_id, content_version, "
                "baseline_candidate_id, adopted_candidate_id, selected_targets_json, adopted_payload_hash, created_at) "
                "VALUES (?, ?, 1, ?, ?, '{}', NULL, ?)",
                (content, plan, cand, cand, ts))
            ids[key] = {"plan": plan, "content": content, "input": inp,
                        "task": task, "exec": exe, "cand": cand}
        conn.execute(
            "INSERT INTO local_ai_attempts (id, execution_id, attempt_no, state, created_at) "
            "VALUES (?, ?, 1, 'succeeded', ?)", (f"{p}-attempt-1", ids["a"]["exec"], ts))
        conn.execute(
            "INSERT INTO local_ai_operations (id, profile_id, request_id, operation_kind, request_fingerprint, "
            "fingerprint_kind, fingerprint_key_id, result_json, created_at) "
            "VALUES (?, ?, ?, 'config_patch', ?, 'sha256', NULL, '{}', ?)",
            (f"{p}-op-1", p, f"{p}-req-1"[:36], "f" * 64, ts))
        probe = f"{p}-exec-a-probe"
        conn.execute(
            "INSERT INTO local_ai_executions (id, task_id, daily_plan_id, input_id, task_type, generation, "
            "launch_id, permit_id, config_version, profile_id, personal_revision, contract_version, "
            "default_revision, state, runtime_meta_json, started_at, created_at) "
            "VALUES (?, ?, ?, ?, 'daily_lesson_split', 2, 'lp', 'pp', 1, ?, 1, 1, 1, 'pending', '{}', ?, ?)",
            (probe, ids["a"]["task"], ids["a"]["plan"], ids["a"]["input"], p, ts, ts))
        ids.update(profile=p, cls=c, term=t, revision=r, exec_probe=probe)
        return ids

    def _expect_fk(self, conn, sql, params=(), *, at_commit=False, setup=()):
        """单条 INSERT/COMMIT 必须抛 SQLITE_CONSTRAINT_FOREIGNKEY。"""
        if conn.in_transaction:
            conn.rollback()
        conn.execute("BEGIN IMMEDIATE")
        try:
            for setup_sql, setup_params in setup:
                conn.execute(setup_sql, setup_params)
            if at_commit:
                conn.execute(sql, params)
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    conn.execute("COMMIT")
            else:
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    conn.execute(sql, params)
            self.assertEqual(
                ctx.exception.sqlite_errorname,
                "SQLITE_CONSTRAINT_FOREIGNKEY",
                str(ctx.exception),
            )
        finally:
            conn.rollback()
        # 每次回滚后库内不得残留任何外键违规。
        self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def _expect_check(self, conn, sql, params=(), *, name=None, setup=()):
        """单条 INSERT 必须抛 SQLITE_CONSTRAINT_CHECK（不被 FK 遮盖）。"""
        if conn.in_transaction:
            conn.rollback()
        conn.execute("BEGIN IMMEDIATE")
        try:
            for setup_sql, setup_params in setup:
                conn.execute(setup_sql, setup_params)
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                conn.execute(sql, params)
            self.assertEqual(
                ctx.exception.sqlite_errorname,
                "SQLITE_CONSTRAINT_CHECK",
                str(ctx.exception),
            )
            if name is not None:
                self.assertIn(name, str(ctx.exception))
        finally:
            conn.rollback()
        self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def _run_ok(self, conn, statements):
        """在单个已回滚事务内执行 statements，断言不报错且无外键残留。"""
        if conn.in_transaction:
            conn.rollback()
        conn.execute("BEGIN IMMEDIATE")
        try:
            for sql, params in statements:
                conn.execute(sql, params)
        finally:
            conn.rollback()
        self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def _commit_ok(self, conn, sql, params):
        """执行一条 UPDATE 并 COMMIT，验证 deferred FK 在提交时通过。"""
        if conn.in_transaction:
            conn.rollback()
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(sql, params)
            conn.execute("COMMIT")
        finally:
            if conn.in_transaction:
                conn.rollback()
        self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    # -- 项目 2：key_id / fingerprint_key_id 形状 ------------------------

    def test_key_id_shape_rejects_nul_and_blob_in_real_db(self):
        """真实迁移库：key_id/fingerprint_key_id 必须是无内嵌 NUL 的文本。

        SQLite length()/GLOB 会在内嵌 NUL 处截断，BLOB 的 NOT GLOB 为真；
        因此仅 IS NOT NULL 会放行 'abc\\x00/bad' 与 sqlite3.Binary(b'abc')。
        本测试在真实 0004 库验证二者被拒，正常 32hex 与 64 边界被接受。
        """
        runtime = self.make_runtime()
        conn = sqlite_connect(runtime.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._insert_profile(conn, "p-key")
            # retired 无材料约束；合法 32hex 与 64 边界可提交。
            for i, kid in enumerate(("a" * 32, "A" * 64)):
                conn.execute(
                    "INSERT INTO local_ai_credentials (id, profile_id, key_id, nonce, ciphertext, "
                    "state, created_at, updated_at) "
                    "VALUES (?, 'p-key', ?, NULL, NULL, 'retired', ?, ?)",
                    (f"c-ok-{i}", kid, self._TS, self._TS))
            bad = {
                "empty": "",
                "slash": "a/b",
                "too-long": "a" * 65,
                "nul-suffix": "abc\u0000/bad",
                "blob-legal": sqlite3.Binary(b"abc"),
                "blob-slash": sqlite3.Binary(b"a/b"),
            }
            for label, value in bad.items():
                with self.subTest(field="key_id", case=label):
                    with self.assertRaises(sqlite3.IntegrityError) as ctx:
                        conn.execute(
                            "INSERT INTO local_ai_credentials (id, profile_id, key_id, nonce, ciphertext, "
                            "state, created_at, updated_at) "
                            "VALUES (?, 'p-key', ?, NULL, NULL, 'retired', ?, ?)",
                            (f"cb-{label}", value, self._TS, self._TS))
                    self.assertEqual(ctx.exception.sqlite_errorname, "SQLITE_CONSTRAINT_CHECK")
                    self.assertIn("ck_local_ai_credentials_key_id_shape", str(ctx.exception))
            op = (
                "INSERT INTO local_ai_operations "
                "(id, profile_id, request_id, operation_kind, request_fingerprint, "
                "fingerprint_kind, fingerprint_key_id, result_json, created_at) "
                "VALUES (?, 'p-key', ?, 'config_patch', ?, 'sha256', ?, '{}', ?)"
            )
            conn.execute(op, ("op-ok", "req-ok", "f" * 64, "b" * 32, self._TS))
            for label, value in {
                "nul-suffix": "abc\u0000/bad",
                "blob-legal": sqlite3.Binary(b"abc"),
            }.items():
                with self.subTest(field="fingerprint_key_id", case=label):
                    with self.assertRaises(sqlite3.IntegrityError) as ctx:
                        conn.execute(
                            op, (f"op-{label}", f"req-{label}", "f" * 64, value, self._TS))
                    self.assertEqual(ctx.exception.sqlite_errorname, "SQLITE_CONSTRAINT_CHECK")
                    self.assertIn(
                        "ck_local_ai_operations_fingerprint_key_id_shape",
                        str(ctx.exception))
            conn.rollback()
        finally:
            conn.close()

    # -- 项目 3：完整合法图 + 单因子关系负例 -----------------------------

    def test_full_graph_and_single_factor_relationships(self):
        """完整 A/B 合法图先提交（FKcheck=0），再逐条只改一个引用。

        含 task.current_execution_id 指向本图 execution 的正向循环外键，以及
        单改指向另一图后在 commit 被拒（deferred）。本测试只证明关系/约束有效，
        W4 候选输入/基准业务语义另行验证；pending 执行 + candidate 不等同于
        完整业务链。
        """
        runtime = self.make_runtime()
        db = runtime.db_path
        conn = sqlite_connect(db)
        ts = self._TS
        try:
            conn.execute("BEGIN IMMEDIATE")
            g = self._build_full_legal_graph(conn, "p-rel", "c-rel", "t-rel", "r-rel")
            conn.execute("COMMIT")
            self.assertEqual(query_rows(db, "PRAGMA foreign_key_check"), [])
            a, b = g["a"], g["b"]

            # 1) input 内容三元：content 属于另一已提交计划 B。
            self._expect_fk(conn,
                "INSERT INTO local_ai_inputs (id, daily_plan_id, content_id, content_version, task_type, "
                "target_grade, input_schema_version, payload_json, dependencies_json, dependency_hash, "
                "target_hashes_json, created_at) "
                "VALUES ('x-in-1', ?, ?, 1, 'daily_lesson_split', 'middle', 1, '{}','{}','{}','{}', ?)",
                (a["plan"], b["content"], ts))
            # 2) input content_version 单改。
            self._expect_fk(conn,
                "INSERT INTO local_ai_inputs (id, daily_plan_id, content_id, content_version, task_type, "
                "target_grade, input_schema_version, payload_json, dependencies_json, dependency_hash, "
                "target_hashes_json, created_at) "
                "VALUES ('x-in-2', ?, ?, 2, 'daily_lesson_split', 'middle', 1, '{}','{}','{}','{}', ?)",
                (a["plan"], a["content"], ts))
            # 3) task 输入：指向 plan B 的 input（status 非活跃避免命中唯一索引）。
            self._expect_fk(conn,
                "INSERT INTO local_ai_tasks (id, profile_id, daily_plan_id, task_type, input_id, status, reason, "
                "current_execution_id, generation, runtime_meta_json, created_at, updated_at) "
                "VALUES ('x-task-3', ?, ?, 'daily_lesson_split', ?, 'succeeded', NULL, NULL, 0, '{}', ?, ?)",
                (g["profile"], a["plan"], b["input"], ts, ts))
            # 4) task 输入 task_type 单改。
            self._expect_fk(conn,
                "INSERT INTO local_ai_tasks (id, profile_id, daily_plan_id, task_type, input_id, status, reason, "
                "current_execution_id, generation, runtime_meta_json, created_at, updated_at) "
                "VALUES ('x-task-4', ?, ?, 'daily_other_activities', ?, 'succeeded', NULL, NULL, 0, '{}', ?, ?)",
                (g["profile"], a["plan"], a["input"], ts, ts))
            # 5) execution task 四元：task 指向 plan B。
            self._expect_fk(conn,
                "INSERT INTO local_ai_executions (id, task_id, daily_plan_id, input_id, task_type, generation, "
                "launch_id, permit_id, config_version, profile_id, personal_revision, contract_version, "
                "default_revision, state, runtime_meta_json, started_at, created_at) "
                "VALUES ('x-exec-5', ?, ?, ?, 'daily_lesson_split', 2, 'l', 'p', 1, ?, 1, 1, 1, 'pending', '{}', ?, ?)",
                (b["task"], a["plan"], a["input"], g["profile"], ts, ts))
            # 6) execution input 单改。
            self._expect_fk(conn,
                "INSERT INTO local_ai_executions (id, task_id, daily_plan_id, input_id, task_type, generation, "
                "launch_id, permit_id, config_version, profile_id, personal_revision, contract_version, "
                "default_revision, state, runtime_meta_json, started_at, created_at) "
                "VALUES ('x-exec-6', ?, ?, ?, 'daily_lesson_split', 3, 'l', 'p', 1, ?, 1, 1, 1, 'pending', '{}', ?, ?)",
                (a["task"], a["plan"], b["input"], g["profile"], ts, ts))
            # 7) candidate 执行五元：execution 单改（probe 无 candidate，避免唯一冲突）。
            self._expect_fk(conn,
                "INSERT INTO local_ai_candidates (id, execution_id, task_id, daily_plan_id, input_id, task_type, "
                "contract_version, schema_version, raw_candidate_json, candidate_hash, created_at) "
                "VALUES ('x-cand-7', ?, ?, ?, ?, 'daily_lesson_split', 1, 1, '{}', ?, ?)",
                (g["exec_probe"], a["task"], a["plan"], b["input"], "h" * 64, ts))
            # 8) provenance baseline：新内容 + 指向 plan B 的 baseline candidate（deferred）。
            self._expect_fk(conn,
                "INSERT INTO local_daily_plan_ai_provenance (content_id, daily_plan_id, content_version, "
                "baseline_candidate_id, adopted_candidate_id, selected_targets_json, adopted_payload_hash, created_at) "
                "VALUES ('x-content-8', ?, 2, ?, NULL, '{}', NULL, ?)",
                (a["plan"], b["cand"], ts), at_commit=True,
                setup=[(
                    "INSERT INTO local_daily_plan_contents (id, daily_plan_id, version, raw_lesson_plan, "
                    "adopted_content, editor_id, created_at) "
                    "VALUES ('x-content-8', ?, 2, NULL, '{}', ?, ?)",
                    (a["plan"], g["profile"], ts))])
            # 9) provenance adopted：另一内容 + 指向 plan B 的 adopted candidate（deferred）。
            self._expect_fk(conn,
                "INSERT INTO local_daily_plan_ai_provenance (content_id, daily_plan_id, content_version, "
                "baseline_candidate_id, adopted_candidate_id, selected_targets_json, adopted_payload_hash, created_at) "
                "VALUES ('x-content-9', ?, 3, NULL, ?, '{}', NULL, ?)",
                (a["plan"], b["cand"], ts), at_commit=True,
                setup=[(
                    "INSERT INTO local_daily_plan_contents (id, daily_plan_id, version, raw_lesson_plan, "
                    "adopted_content, editor_id, created_at) "
                    "VALUES ('x-content-9', ?, 3, NULL, '{}', ?, ?)",
                    (a["plan"], g["profile"], ts))])
            # 10) task.current_execution：指向 plan B 的 execution（deferred）。
            self._expect_fk(conn,
                "INSERT INTO local_ai_tasks (id, profile_id, daily_plan_id, task_type, input_id, status, reason, "
                "current_execution_id, generation, runtime_meta_json, created_at, updated_at) "
                "VALUES ('x-task-10', ?, ?, 'daily_lesson_split', ?, 'succeeded', NULL, ?, 0, '{}', ?, ?)",
                (g["profile"], a["plan"], a["input"], b["exec"], ts, ts), at_commit=True)
            # 11) execution config_version 伪版本（deferred）。
            self._expect_fk(conn,
                "INSERT INTO local_ai_executions (id, task_id, daily_plan_id, input_id, task_type, generation, "
                "launch_id, permit_id, config_version, profile_id, personal_revision, contract_version, "
                "default_revision, state, runtime_meta_json, started_at, created_at) "
                "VALUES ('x-exec-11', ?, ?, ?, 'daily_lesson_split', 4, 'l', 'p', 999, ?, 1, 1, 1, 'pending', '{}', ?, ?)",
                (a["task"], a["plan"], a["input"], g["profile"], ts, ts), at_commit=True)
            # 12) execution personal_revision 伪修订（deferred）。
            self._expect_fk(conn,
                "INSERT INTO local_ai_executions (id, task_id, daily_plan_id, input_id, task_type, generation, "
                "launch_id, permit_id, config_version, profile_id, personal_revision, contract_version, "
                "default_revision, state, runtime_meta_json, started_at, created_at) "
                "VALUES ('x-exec-12', ?, ?, ?, 'daily_lesson_split', 5, 'l', 'p', 1, ?, 2, 1, 1, 'pending', '{}', ?, ?)",
                (a["task"], a["plan"], a["input"], g["profile"], ts, ts), at_commit=True)
            # 13) execution default_revision 伪 bundle 修订（deferred）。
            self._expect_fk(conn,
                "INSERT INTO local_ai_executions (id, task_id, daily_plan_id, input_id, task_type, generation, "
                "launch_id, permit_id, config_version, profile_id, personal_revision, contract_version, "
                "default_revision, state, runtime_meta_json, started_at, created_at) "
                "VALUES ('x-exec-13', ?, ?, ?, 'daily_lesson_split', 6, 'l', 'p', 1, ?, 1, 1, 2, 'pending', '{}', ?, ?)",
                (a["task"], a["plan"], a["input"], g["profile"], ts, ts), at_commit=True)
            # 14) 被拒绝的个人修订必须引用存在且同 contract 的 bundle（deferred）。
            self._expect_fk(conn,
                "INSERT INTO local_personal_prompt_versions (profile_id, task_type, revision, contract_version, "
                "based_default_revision, guidance_json, action, rejected_default_revision, created_at) "
                "VALUES (?, 'daily_lesson_split', 2, 1, 1, '{}', 'reject', 2, ?)",
                (g["profile"], ts), at_commit=True)

            # 每次 rollback 后都不得残留外键违规。
            self.assertEqual(query_rows(db, "PRAGMA foreign_key_check"), [])
        finally:
            conn.close()

    # -- 项目 4：严格整数遍历 -------------------------------------------

    def _strict_int_insert(self, table, column, value, g):
        """返回在真实库插入一行、把 column 置为 value 的 SQL/参数。"""
        ts = self._TS
        p = g["profile"]
        a = g["a"]
        if table == "local_ai_config_versions":
            return (
                "INSERT INTO local_ai_config_versions "
                "(profile_id, version, protocol_id, created_at) "
                "VALUES (?, ?, 'chat_completions_v1', ?)", (p, value, ts))
        if table == "local_class_game_revisions":
            return (
                "INSERT INTO local_class_game_revisions "
                "(id, class_id, revision_no, payload_json, payload_hash, created_at) "
                "VALUES (?, ?, ?, '{}', ?, ?)",
                (f"g-{column}-{value!r}"[:32], g["cls"], value, "h" * 64, ts))
        if table == "local_prompt_bundles":
            cv = value if column == "contract_version" else 1
            dr = value if column == "default_revision" else 1
            return (
                "INSERT INTO local_prompt_bundles "
                "(task_type, contract_version, default_revision, input_schema_json, "
                "output_schema_json, guidance_defaults_json, bundle_hash, created_at) "
                "VALUES ('daily_lesson_split', ?, ?, '{}', '{}', '{}', ?, ?)",
                (cv, dr, "h" * 64, ts))
        if table == "local_personal_prompt_versions":
            rev = {"contract_version": 11, "based_default_revision": 12}.get(
                column, value)
            cv = value if column == "contract_version" else 1
            bdr = value if column == "based_default_revision" else 1
            return (
                "INSERT INTO local_personal_prompt_versions "
                "(profile_id, task_type, revision, contract_version, based_default_revision, "
                "guidance_json, action, created_at) "
                "VALUES (?, 'daily_lesson_split', ?, ?, ?, '{}', 'initial', ?)",
                (p, rev, cv, bdr, ts))
        if table == "local_personal_prompt_heads":
            cr = value if column == "current_revision" else 1
            rcv = value if column == "required_contract_version" else 1
            ldr = value if column == "latest_default_revision" else 1
            return (
                "INSERT INTO local_personal_prompt_heads "
                "(profile_id, task_type, current_revision, required_contract_version, "
                "latest_default_revision, created_at, updated_at) "
                "VALUES (?, 'daily_process_adapt', ?, ?, ?, ?, ?)",
                (p, cr, rcv, ldr, ts, ts))
        if table == "local_ai_inputs":
            return (
                "INSERT INTO local_ai_inputs (id, daily_plan_id, content_id, content_version, task_type, "
                "target_grade, input_schema_version, payload_json, dependencies_json, dependency_hash, "
                "target_hashes_json, created_at) "
                "VALUES (?, ?, ?, 1, 'daily_lesson_split', 'middle', ?, '{}','{}','{}','{}', ?)",
                (f"in-{value!r}"[:32], a["plan"], a["content"], value, ts))
        if table == "local_ai_tasks":
            return (
                "INSERT INTO local_ai_tasks (id, profile_id, daily_plan_id, task_type, input_id, status, "
                "reason, current_execution_id, generation, runtime_meta_json, created_at, updated_at) "
                "VALUES (?, ?, ?, 'daily_lesson_split', ?, 'succeeded', NULL, NULL, ?, '{}', ?, ?)",
                (f"tk-{value!r}"[:32], p, a["plan"], a["input"], value, ts, ts))
        if table == "local_ai_executions":
            gen = value if column == "generation" else 3
            cv = value if column == "config_version" else 1
            pr = value if column == "personal_revision" else 1
            ctv = value if column == "contract_version" else 1
            dr = value if column == "default_revision" else 1
            return (
                "INSERT INTO local_ai_executions (id, task_id, daily_plan_id, input_id, task_type, generation, "
                "launch_id, permit_id, config_version, profile_id, personal_revision, contract_version, "
                "default_revision, state, runtime_meta_json, started_at, created_at) "
                "VALUES (?, ?, ?, ?, 'daily_lesson_split', ?, 'l', 'p', ?, ?, ?, ?, ?, 'pending', '{}', ?, ?)",
                (f"ex-{value!r}"[:32], a["task"], a["plan"], a["input"], gen,
                 cv, p, pr, ctv, dr, ts, ts))
        if table == "local_ai_attempts":
            return (
                "INSERT INTO local_ai_attempts (id, execution_id, attempt_no, state, created_at) "
                "VALUES (?, ?, ?, 'succeeded', ?)",
                (f"at-{value!r}"[:32], a["exec"], value, ts))
        if table == "local_ai_candidates":
            cv = value if column == "contract_version" else 1
            sv = value if column == "schema_version" else 1
            return (
                "INSERT INTO local_ai_candidates (id, execution_id, task_id, daily_plan_id, input_id, "
                "task_type, contract_version, schema_version, raw_candidate_json, candidate_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'daily_lesson_split', ?, ?, '{}', ?, ?)",
                (f"cd-{value!r}"[:32], g["exec_probe"], a["task"], a["plan"], a["input"],
                 cv, sv, "h" * 64, ts))
        raise AssertionError(f"unhandled table {table!r}")

    def test_strict_int_columns_traversal(self):
        """STRICT_INT_COLUMNS 覆盖每列的实际插入：边界、1.5、text、0/-1。

        generation 允许 0；attempt_no 为 1..3（3 合法、4 拒绝）。每列在真实
        0004 库命中 typeof 的 CHECK，不被 FK 或唯一索引遮盖。可空版本指针
        另见 test_nullable_version_columns_traversal（FK 与 CHECK 两种证据）。
        """
        for table, columns in STRICT_INT_COLUMNS.items():
            runtime = self.make_runtime(self.tmp_root / f"tr-{table}")
            conn = sqlite_connect(runtime.db_path)
            try:
                conn.execute("BEGIN IMMEDIATE")
                g = self._build_full_legal_graph(
                    conn, "p-tr", "c-tr", "t-tr", "r-tr")
                conn.execute("COMMIT")
                for column, minimum in columns:
                    bad_values = [minimum - 1, 1.5, "abc"]
                    if table == "local_ai_attempts":
                        bad_values.append(4)
                    for value in bad_values:
                        with self.subTest(table=table, column=column, value=value):
                            sql, params = self._strict_int_insert(
                                table, column, value, g)
                            self._expect_check(conn, sql, params)
                    if table == "local_ai_attempts":
                        # 上边界 3 必须合法。
                        pos_sql, pos_params = self._strict_int_insert(
                            table, column, 3, g)
                        self._run_ok(conn, [(pos_sql, pos_params)])
            finally:
                conn.close()

    def test_nullable_version_columns_traversal(self):
        """可空版本列：按真实约束分别取证，不让无关错误遮盖。

        - local_ai_state.current_config_version/blocked_config_version 无独立
          CHECK，仅 deferred FK 引用已存在正整数版本：NULL/1 正向成功，坏值在
          COMMIT 精确抛 SQLITE_CONSTRAINT_FOREIGNKEY。
        - local_personal_prompt_versions.rejected_default_revision 有独立
          typeof CHECK：NULL/1 正向成功，坏值在 INSERT 精确抛
          SQLITE_CONSTRAINT_CHECK。
        """
        runtime = self.make_runtime(self.tmp_root / "tr-nullable")
        conn = sqlite_connect(runtime.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            g = self._build_full_legal_graph(conn, "p-nv", "c-nv", "t-nv", "r-nv")
            conn.execute("COMMIT")
            p = g["profile"]

            for column, kind in NULLABLE_VERSION_COLUMNS["local_ai_state"].items():
                self.assertEqual(kind, "fk")
                upd = f"UPDATE local_ai_state SET {column} = ? WHERE profile_id = ?"
                self._commit_ok(conn, upd, (None, p))
                self._commit_ok(conn, upd, (1, p))
                for value in (0, -1, 1.5, "abc"):
                    with self.subTest(table="local_ai_state", column=column,
                                      value=value):
                        self._expect_fk(conn, upd, (value, p), at_commit=True)

            for column, kind in NULLABLE_VERSION_COLUMNS[
                "local_personal_prompt_versions"
            ].items():
                self.assertEqual(kind, "check")
                upd = (
                    "UPDATE local_personal_prompt_versions SET "
                    f"{column} = ? WHERE profile_id = ? AND task_type = "
                    "'daily_lesson_split' AND revision = 1"
                )
                self._run_ok(conn, [(upd, (None, p))])
                self._run_ok(conn, [(upd, (1, p))])
                for value in (0, -1, 1.5, "abc"):
                    with self.subTest(
                        table="local_personal_prompt_versions",
                        column=column, value=value,
                    ):
                        self._expect_check(conn, upd, (value, p))
        finally:
            conn.close()

    # -- 项目 4：枚举、指针、凭据材料负例 --------------------------------

    def test_enum_state_and_credential_material_constraints(self):
        runtime = self.make_runtime()
        conn = sqlite_connect(runtime.db_path)
        ts = self._TS
        try:
            conn.execute("BEGIN IMMEDIATE")
            g = self._build_full_legal_graph(conn, "p-en", "c-en", "t-en", "r-en")
            conn.execute("COMMIT")
            a = g["a"]
            # input 枚举
            self._expect_check(conn,
                "INSERT INTO local_ai_inputs (id, daily_plan_id, content_id, content_version, task_type, "
                "target_grade, input_schema_version, payload_json, dependencies_json, dependency_hash, "
                "target_hashes_json, created_at) "
                "VALUES ('e-in-1', ?, ?, 1, 'bogus_task', 'middle', 1, '{}','{}','{}','{}', ?)",
                (a["plan"], a["content"], ts), name="ck_local_ai_inputs_task_type")
            self._expect_check(conn,
                "INSERT INTO local_ai_inputs (id, daily_plan_id, content_id, content_version, task_type, "
                "target_grade, input_schema_version, payload_json, dependencies_json, dependency_hash, "
                "target_hashes_json, created_at) "
                "VALUES ('e-in-2', ?, ?, 1, 'daily_lesson_split', 'kindergarten', 1, '{}','{}','{}','{}', ?)",
                (a["plan"], a["content"], ts), name="ck_local_ai_inputs_target_grade")
            # task / execution 状态枚举
            self._expect_check(conn,
                "INSERT INTO local_ai_tasks (id, profile_id, daily_plan_id, task_type, input_id, status, "
                "reason, current_execution_id, generation, runtime_meta_json, created_at, updated_at) "
                "VALUES ('e-task-1', ?, ?, 'daily_lesson_split', ?, 'bogus_state', NULL, NULL, 0, '{}', ?, ?)",
                (g["profile"], a["plan"], a["input"], ts, ts),
                name="ck_local_ai_tasks_status")
            self._expect_check(conn,
                "INSERT INTO local_ai_executions (id, task_id, daily_plan_id, input_id, task_type, generation, "
                "launch_id, permit_id, config_version, profile_id, personal_revision, contract_version, "
                "default_revision, state, runtime_meta_json, started_at, created_at) "
                "VALUES ('e-exec-1', ?, ?, ?, 'daily_lesson_split', 7, 'l', 'p', 1, ?, 1, 1, 1, 'bogus_state', '{}', ?, ?)",
                (a["task"], a["plan"], a["input"], g["profile"], ts, ts),
                name="ck_local_ai_executions_state")
            # active 材料：空 key_id / nonce=NULL / nonce 非 12 / ciphertext 过短
            # （单档案库只能有一个 profile，复用已提交图 profile。）
            p = g["profile"]
            self._expect_check(conn,
                "INSERT INTO local_ai_credentials (id, profile_id, key_id, nonce, ciphertext, state, "
                "created_at, updated_at) VALUES ('cr-1', ?, ?, NULL, ?, 'active', ?, ?)",
                (p, "a" * 32, sqlite3.Binary(b"\x00" * 16), ts, ts),
                name="ck_local_ai_credentials_active_has_material")
            self._expect_check(conn,
                "INSERT INTO local_ai_credentials (id, profile_id, key_id, nonce, ciphertext, state, "
                "created_at, updated_at) VALUES ('cr-2', ?, ?, ?, ?, 'active', ?, ?)",
                (p, "", sqlite3.Binary(b"\x00" * 12), sqlite3.Binary(b"\x00" * 16), ts, ts),
                name="ck_local_ai_credentials_key_id_shape")
            self._expect_check(conn,
                "INSERT INTO local_ai_credentials (id, profile_id, key_id, nonce, ciphertext, state, "
                "created_at, updated_at) VALUES ('cr-3', ?, ?, ?, ?, 'active', ?, ?)",
                (p, "a" * 32, sqlite3.Binary(b"\x00" * 11), sqlite3.Binary(b"\x00" * 16), ts, ts),
                name="ck_local_ai_credentials_active_has_material")
            self._expect_check(conn,
                "INSERT INTO local_ai_credentials (id, profile_id, key_id, nonce, ciphertext, state, "
                "created_at, updated_at) VALUES ('cr-4', ?, ?, ?, ?, 'active', ?, ?)",
                (p, "a" * 32, sqlite3.Binary(b"\x00" * 12), sqlite3.Binary(b"\x00" * 15), ts, ts),
                name="ck_local_ai_credentials_active_has_material")
            # HMAC 回执：NULL / 空 key_id
            self._expect_check(conn,
                "INSERT INTO local_ai_operations (id, profile_id, request_id, operation_kind, "
                "request_fingerprint, fingerprint_kind, fingerprint_key_id, result_json, created_at) "
                "VALUES ('e-op-1', ?, 'e-req-1', 'config_patch', ?, 'hmac_sha256', NULL, '{}', ?)",
                (p, "f" * 64, ts), name="ck_local_ai_operations_hmac_key_id")
            self._expect_check(conn,
                "INSERT INTO local_ai_operations (id, profile_id, request_id, operation_kind, "
                "request_fingerprint, fingerprint_kind, fingerprint_key_id, result_json, created_at) "
                "VALUES ('e-op-2', ?, 'e-req-2', 'config_patch', ?, 'hmac_sha256', '', '{}', ?)",
                (p, "f" * 64, ts), name="ck_local_ai_operations_fingerprint_key_id_shape")
            self.assertEqual(query_rows(runtime.db_path, "PRAGMA foreign_key_check"), [])
        finally:
            conn.close()

    # -- 项目 6：冻结 bundle 与种子等价 ---------------------------------

    def _load_bundles(self, db):
        rows = query_rows(
            db,
            "SELECT task_type, input_schema_json, output_schema_json, "
            "guidance_defaults_json, bundle_hash FROM local_prompt_bundles",
        )
        out = {}
        for row in rows:
            out[row["task_type"]] = {
                "input": json.loads(row["input_schema_json"]),
                "output": json.loads(row["output_schema_json"]),
                "guidance": json.loads(row["guidance_defaults_json"]),
                "hash": row["bundle_hash"],
            }
        return out

    @staticmethod
    def _canonical_bundle_hash(input_schema, output_schema, guidance):
        payload = {
            "input_schema_json": input_schema,
            "output_schema_json": output_schema,
            "guidance_defaults_json": guidance,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _canonical_json(obj):
        return json.dumps(
            obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    def test_frozen_bundles_and_seed_equivalence(self):
        """3 个冻结 bundle 内容/hash；新档案初始化与迁移种子逐字段等价。

        重复 initialize 不新增提示头/版本。无独立 validator，只做结构/规则
        与等价断言（W2/W3 才做运行时输出验证）。
        """
        runtime = self.make_runtime()
        db = runtime.db_path
        bundles = self._load_bundles(db)
        self.assertEqual(set(bundles), set(self._ALL_TASKS))
        for task, b in bundles.items():
            with self.subTest(task=task):
                self.assertEqual(len(b["hash"]), 64)
                self.assertEqual(
                    b["hash"],
                    self._canonical_bundle_hash(b["input"], b["output"], b["guidance"]),
                )
                for schema in (b["input"], b["output"]):
                    self.assertEqual(schema.get("$schema"), self._DRAFT_2020_12)
                    blob = self._canonical_json(schema)
                    self.assertNotIn("prefixItems", blob)
                    self.assertNotIn("additionalItems", blob)

        session = runtime.session()
        try:
            normalized = normalize_initialization(**initialize_body())
            payload, created = profile_service.initialize(session, normalized)
            self.assertTrue(created)
            profile_id = payload["profile"]["id"]
            class_id = payload["class"]["id"]
        finally:
            session.close()

        # 新档案 personal guidance 与冻结 bundle 逐字段等价。
        for task, b in bundles.items():
            rows = query_rows(
                db,
                "SELECT guidance_json FROM local_personal_prompt_versions "
                "WHERE profile_id = ? AND task_type = ? AND revision = 1",
                (profile_id, task),
            )
            self.assertEqual(len(rows), 1, task)
            self.assertEqual(json.loads(rows[0]["guidance_json"]), b["guidance"])

        # 空游戏 payload 的内容与 hash 与初始化一致。
        head = query_rows(
            db, "SELECT current_revision_id FROM local_class_game_heads WHERE class_id = ?",
            (class_id,),
        )
        self.assertEqual(len(head), 1)
        game = query_rows(
            db, "SELECT payload_json, payload_hash FROM local_class_game_revisions WHERE id = ?",
            (head[0]["current_revision_id"],),
        )
        self.assertEqual(len(game), 1)
        self.assertEqual(json.loads(game[0]["payload_json"]), self._EXPECTED_EMPTY_GAME)
        self.assertEqual(
            game[0]["payload_hash"],
            hashlib.sha256(
                self._canonical_json(self._EXPECTED_EMPTY_GAME).encode("utf-8")
            ).hexdigest(),
        )

        # 重复 initialize：不新增头/版本，config_version 不变。
        session = runtime.session()
        try:
            payload2, created2 = profile_service.initialize(session, normalized)
            self.assertFalse(created2)
            self.assertEqual(payload2["profile"]["id"], profile_id)
        finally:
            session.close()
        self.assertEqual(
            query_scalar(db, "SELECT count(*) FROM local_personal_prompt_heads"), 3)
        self.assertEqual(
            query_scalar(db, "SELECT count(*) FROM local_personal_prompt_versions"), 3)
        self.assertEqual(
            query_scalar(db, "SELECT count(*) FROM local_class_game_revisions"), 1)
        self.assertEqual(
            query_scalar(db, "SELECT config_version FROM local_settings"), 1)

    def test_old_upgrade_seed_matches_fresh_bundle(self):
        """旧 0001/0002/0003 库升级后的 guidance/空游戏与冻结 bundle 等价。"""
        self.enterContext(calendar_provider(StaticCalendarProvider()))
        data_dir = self.tmp_root / "d2-upgrade-seed"
        data_dir.mkdir(parents=True, exist_ok=True)
        db = data_dir / "kindergarten.db"
        command.upgrade(alembic_config(db), OLD_HEAD_REVISION)
        self._seed_d1_old_schema(db)
        ensure_local_schema(db)

        bundles = self._load_bundles(db)
        self.assertEqual(set(bundles), set(self._ALL_TASKS))
        for task, b in bundles.items():
            rows = query_rows(
                db,
                "SELECT guidance_json FROM local_personal_prompt_versions "
                "WHERE profile_id = ? AND task_type = ?",
                (OLD_PROFILE_ID, task),
            )
            self.assertEqual(len(rows), 1, task)
            self.assertEqual(json.loads(rows[0]["guidance_json"]), b["guidance"])

        head = query_rows(
            db, "SELECT current_revision_id FROM local_class_game_heads WHERE class_id = ?",
            (OLD_CLASS_ID,),
        )
        self.assertEqual(len(head), 1)
        game = query_rows(
            db, "SELECT payload_json, payload_hash FROM local_class_game_revisions WHERE id = ?",
            (head[0]["current_revision_id"],),
        )
        self.assertEqual(json.loads(game[0]["payload_json"]), self._EXPECTED_EMPTY_GAME)
        self.assertEqual(
            game[0]["payload_hash"],
            hashlib.sha256(
                self._canonical_json(self._EXPECTED_EMPTY_GAME).encode("utf-8")
            ).hexdigest(),
        )

    # -- 项目 5/7：冻结 schema 结构边界 ---------------------------------

    def test_frozen_schema_shape_rules(self):
        """纯 schema 有限结构断言（无 validator；W2/W3 才做运行时验证）。"""
        runtime = self.make_runtime()
        bundles = self._load_bundles(runtime.db_path)
        for task, b in bundles.items():
            with self.subTest(task=task, io="input"):
                self.assertEqual(b["input"].get("$schema"), self._DRAFT_2020_12)
            with self.subTest(task=task, io="output"):
                self.assertEqual(b["output"].get("$schema"), self._DRAFT_2020_12)

        # SPLIT 输出：group_activity 六个必需 string（可空字符串）。
        split = bundles["daily_lesson_split"]["output"]
        self.assertEqual(split["required"], ["group_activity"])
        ga_out = split["properties"]["group_activity"]
        self.assertEqual(
            set(ga_out["required"]),
            {"theme", "objectives", "preparation", "key_points",
             "difficult_points", "process"})
        self.assertEqual(set(ga_out["properties"]), set(ga_out["required"]))
        for field in ga_out["required"]:
            self.assertEqual(ga_out["properties"][field]["type"], "string")
        # ADAPT 输出：仅 process。
        self.assertEqual(bundles["daily_process_adapt"]["output"]["required"], ["process"])

        # OTHER 输出：4 块、至少 1 块、递归拒绝额外字段。
        out = bundles["daily_other_activities"]["output"]
        self.assertEqual(out["minProperties"], 1)
        self.assertIs(out["additionalProperties"], False)
        self.assertEqual(
            set(out["properties"]),
            {"morning_games", "morning_talk", "post_group_games", "afternoon_outdoor"})
        self.assertNotIn("required", out)
        mg = out["properties"]["morning_games"]
        self.assertNotIn("prefixItems", mg)
        self.assertNotIn("additionalItems", mg)
        self.assertEqual(mg["minItems"], 2)
        self.assertEqual(mg["maxItems"], 2)
        contains = {
            entry["contains"]["properties"]["group_kind"]["const"]: entry
            for entry in mg["allOf"]
        }
        self.assertEqual(set(contains), {"collective", "free_choice"})
        for entry in contains.values():
            self.assertEqual(entry["minContains"], 1)
            self.assertEqual(entry["maxContains"], 1)
        self.assertEqual(mg["items"]["properties"]["games"]["maxItems"], 1)
        # 可选文本可省略但不得为 null。
        self.assertNotIn("required", out["properties"]["morning_talk"])
        for field in ("topic", "questions"):
            self.assertEqual(
                out["properties"]["morning_talk"]["properties"][field]["type"], "string")
        for block in ("post_group_games", "afternoon_outdoor"):
            item = out["properties"][block]
            if item["type"] == "array":
                item = item["items"]
            for field in ("area", "objectives", "guidance", "support_strategy"):
                if field in item["properties"]:
                    self.assertEqual(item["properties"][field]["type"], "string")

        # OTHER 输入：未填写/未拆分合法。
        inp = bundles["daily_other_activities"]["input"]
        snapshot = inp["properties"]["daily_plan_snapshot"]
        self.assertNotIn("required", snapshot)
        ga = snapshot["properties"]["group_activity"]
        self.assertEqual(ga["type"], ["object", "null"])
        self.assertNotIn("required", ga)
        for field in ("theme", "objectives", "preparation", "key_points",
                      "difficult_points", "process"):
            self.assertEqual(ga["properties"][field]["type"], ["string", "null"])
        mg_in = snapshot["properties"]["morning_games"]
        self.assertEqual(mg_in["type"], ["array", "null"])
        input_contains = {
            entry["contains"]["properties"]["group_kind"]["const"]: entry
            for entry in mg_in["allOf"]
        }
        self.assertEqual(set(input_contains), {"collective", "free_choice"})
        for entry in input_contains.values():
            self.assertEqual(entry["minContains"], 0)
            self.assertEqual(entry["maxContains"], 1)
        # post/afternoon 允许空 games 数组与空 game.name。
        post_games = snapshot["properties"]["post_group_games"]["items"]["properties"]["games"]
        self.assertNotIn("minItems", post_games)
        self.assertNotIn("minLength", post_games["items"]["properties"]["name"])
        aft_games = snapshot["properties"]["afternoon_outdoor"]["properties"]["games"]
        self.assertNotIn("minItems", aft_games)
        self.assertNotIn("minLength", aft_games["items"]["properties"]["name"])
        # 不含原教案全文/反思/姓名/业务ID。
        blob = self._canonical_json(inp)
        for forbidden in ("raw_lesson_plan", "reflection", "creator", "display_name"):
            self.assertNotIn(forbidden, blob)


def execute_sql_multi(db_path: Path, statements: list[str]) -> None:
    """执行多条 SQL 语句（用于种子数据）。"""
    connection = sqlite3.connect(str(db_path))
    try:
        for statement in statements:
            connection.execute(statement)
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
