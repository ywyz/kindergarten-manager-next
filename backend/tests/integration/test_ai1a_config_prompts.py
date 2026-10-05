"""AI 1A integration tests against a real one-shot local MySQL 8.4/InnoDB.

Covers checklist §9.2 row by row; uses two whitelisted databases:
* ``kindergarten_test_ai1a_fresh`` — empty-database full-chain migration,
  then the functional world for all service tests (every test re-seeds);
* ``kindergarten_test_ai1a`` — upgrade over an I3/I4-representative row set.

Key material is generated in-process and injected via Settings (never read
from ``.env``; APP_DISABLE_DOTENV=1 is forced by the guard). Typed errors
must map exactly as designed: only genuinely conflicting logic maps to
conflict; forced integrity errors surface as-is.
"""

from __future__ import annotations

import base64
import json
import threading
import unittest
from datetime import date, datetime, timedelta

from tests.integration.ai1a_guard import (  # noqa: F401
    ALLOWED_DATABASES,
    INTEGRATION_ENABLED,
    check_environment,
    ensure_schema,
    make_engine,
    reset_ai1a_tables,
    reset_base_tables,
    run_alembic,
    skip_unless_enabled,
)

from pydantic import SecretStr  # noqa: E402

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.exc import (  # noqa: E402
    IntegrityError,
    OperationalError,
)

from app import security  # noqa: E402
from app.config import settings  # noqa: E402
from app.services import ai_config_service, ai_crypto, ai_locks  # noqa: E402
from app.services import prompt_service  # noqa: E402
from app.services.auth_service import AuthSnapshot  # noqa: E402

TASK = "daily_lesson_split"

ADMIN = {
    "id": "adm_ai1a", "username": "adm_ai1a", "display": "管理员甲",
    "role": "admin", "session": "sesadm_ai1a",
}
TEACHER_A = {
    "id": "tow_ai1a", "username": "tow_ai1a", "display": "老师甲",
    "role": "teacher", "session": "sesa_ai1a",
}
TEACHER_B = {
    "id": "twb_ai1a", "username": "twb_ai1a", "display": "老师乙",
    "role": "teacher", "session": "sesb_ai1a",
}
ACCOUNTS = (ADMIN, TEACHER_A, TEACHER_B)

WORLD_STAMP = datetime(2026, 8, 1, 0, 0, 0)
TERM_START = date(2026, 8, 3)
TERM_END = date(2026, 8, 30)


def _canonical_value(value):
    """JSON 内容比较的键序无关标准化（不依赖数据库 JSON 键序／字节格式）。"""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return value
        if isinstance(parsed, (dict, list)):
            return json.dumps(parsed, sort_keys=True, ensure_ascii=False)
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return value


def dump_world_rows(engine, tables: tuple[str, ...]) -> dict[str, list]:
    """Dump every row (whole row, JSON canonicalized) for old-table compare."""
    out: dict[str, list] = {}
    with engine.begin() as conn:
        for table in tables:
            rows = conn.execute(
                text(f"SELECT * FROM `{table}` ORDER BY 1, 2, 3")
                if table not in ("calendar_days", "daily_plan_contents",
                                 "first_admin_control", "school_settings")
                else text(f"SELECT * FROM `{table}`")
            ).mappings().all()
            out[table] = [
                tuple(sorted((k, _canonical_value(v)) for k, v in dict(r).items()))
                for r in rows
            ]
    return out


def full_day_content(theme: str = "主题活动") -> dict:
    """本片纯夹具：满足日计划导出缺项检查的已采用内容（不经过带
    I5 guard 的 support 模块导入）。"""
    return {
        "morning_games": [
            {"group_kind": "collective", "games": [{"name": "老狼老狼几点了"}],
             "shared_objectives": "集体活动目标", "guidance_points": "集体指导要点",
             "focus_guidance": "集体重点指导"},
            {"group_kind": "free_choice", "games": [{"name": "沙包投准"}],
             "shared_objectives": "自主活动目标", "guidance_points": "自主指导要点",
             "focus_guidance": "自主重点指导"},
        ],
        "morning_talk": {"topic": "天气问候", "questions": "今天天气怎么样？"},
        "group_activity": {
            "theme": theme, "objectives": "活动目标", "preparation": "活动准备",
            "key_points": "活动重点", "difficult_points": "活动难点",
            "process": "活动过程",
        },
        "post_group_games": [
            {"context_kind": "area", "area": "建构区", "games": [{"name": "搭高楼"}],
             "focus_guidance": "区域重点指导", "objectives": "区域组目标",
             "guidance": "区域指导", "support_strategy": "区域支持策略"},
        ],
        "afternoon_outdoor": {
            "area": "操场", "games": [{"name": "踩影子"}],
            "observation_focus": "观察点", "objectives": "下午活动目标",
            "guidance": "下午指导", "support_strategy": "下午支持策略",
        },
        "reflection": "一日反思",
    }


def snap(account: dict) -> AuthSnapshot:
    return AuthSnapshot(
        account_id=account["id"],
        role=account["role"],
        auth_version=1,
        session_id=account["session"],
        is_active=True,
        password_hash="x",
    )


def _set_material(key: bytes, key_id: str) -> None:
    settings.ai_master_key = SecretStr(base64.b64encode(key).decode())
    settings.ai_master_key_id = SecretStr(key_id)


def _clear_material() -> None:
    settings.ai_master_key = SecretStr("")
    settings.ai_master_key_id = SecretStr("")


def register_material_cleanup() -> None:
    _clear_material()


def seed_world(engine) -> None:
    """I1–I4 代表行（accounts/classes/assignment/term/calendar）。"""
    with engine.begin() as conn:
        for account in ACCOUNTS:
            conn.execute(
                text(
                    "INSERT INTO accounts (id, username, password_hash, "
                    "display_name, role, is_active, version, auth_version, "
                    "created_at, updated_at) VALUES "
                    "(:id, :username, 'x', :display, :role, 1, 1, 1, :ts, :ts)"
                ),
                {"id": account["id"], "username": account["username"],
                 "display": account["display"], "role": account["role"],
                 "ts": WORLD_STAMP},
            )
            conn.execute(
                text(
                    "INSERT INTO sessions (id, token_hash, account_id, "
                    "auth_version, created_at, expires_at, revoked_at) "
                    "VALUES (:id, :hash, :account, 1, :ts, :expires, NULL)"
                ),
                {"id": account["session"],
                 "hash": security.hash_token("tok-" + account["id"]),
                 "account": account["id"],
                 "ts": WORLD_STAMP,
                 "expires": datetime(2100, 1, 1, 0, 0, 0)},
            )
        conn.execute(
            text(
                "INSERT INTO classes (id, name, grade, header_teacher_names, "
                "caregiver_name, version, created_at, updated_at) VALUES "
                "('cls_ai1a', '小班甲', 'small', CAST(:teachers AS JSON), "
                "'李保育', 1, :ts, :ts)"
            ),
            {"teachers": json.dumps(["老师甲", "老师乙"], ensure_ascii=False),
             "ts": WORLD_STAMP},
        )
        for teacher_id in (TEACHER_A["id"], TEACHER_B["id"]):
            conn.execute(
                text(
                    "INSERT INTO teacher_assignments (teacher_id, class_id, "
                    "assigned_by, assigned_at) VALUES "
                    "(:teacher, 'cls_ai1a', :admin, :ts)"
                ),
                {"teacher": teacher_id, "admin": ADMIN["id"], "ts": WORLD_STAMP},
            )
        conn.execute(
            text(
                "INSERT INTO terms (id, name, start_date, end_date, version, "
                "current_calendar_revision_id, created_at, updated_at) VALUES "
                "('ter_ai1a', '2026夏秋', :start, :end, 1, NULL, :ts, :ts)"
            ),
            {"start": TERM_START, "end": TERM_END, "ts": WORLD_STAMP},
        )
        conn.execute(
            text(
                "INSERT INTO calendar_revisions (id, term_id, revision_no, "
                "term_version, start_date, end_date, library_version, "
                "created_by, created_at) VALUES "
                "('rev_ai1a', 'ter_ai1a', 1, 1, :start, :end, 'fixture-1', "
                ":admin, :ts)"
            ),
            {"start": TERM_START, "end": TERM_END, "admin": ADMIN["id"],
             "ts": WORLD_STAMP},
        )
        conn.execute(
            text(
                "UPDATE terms SET current_calendar_revision_id = 'rev_ai1a', "
                "updated_at = :ts WHERE id = 'ter_ai1a'"
            ),
            {"ts": WORLD_STAMP},
        )
        current = TERM_START
        while current <= TERM_END:
            state = "teaching" if current.isoweekday() <= 5 else "non_teaching"
            conn.execute(
                text(
                    "INSERT INTO calendar_days (revision_id, date, base_state, "
                    "base_library_version, override_state, override_reason, "
                    "effective_state) VALUES "
                    "('rev_ai1a', :day, :state, 'fixture-1', NULL, NULL, :state)"
                ),
                {"day": current, "state": state},
            )
            current += timedelta(days=1)


def _world(engine) -> None:
    reset_ai1a_tables(engine)
    seed_world(engine)
    _seed_ai_tables(engine)


def _session_from_factory():
    from app.database import get_sessionlocal

    return get_sessionlocal()()


def _reset_variant_contracts(engine, task: str) -> None:
    """测试内的合成 v2/v3 契约只属于本测试；每类测试前先清掉变体行。"""
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        conn.execute(
            text(
                "DELETE FROM prompt_default_versions "
                "WHERE task_type = :t AND contract_version > 1"
            ),
            {"t": task},
        )
        conn.execute(
            text(
                "DELETE FROM prompt_contract_versions "
                "WHERE task_type = :t AND contract_version > 1"
            ),
            {"t": task},
        )
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))


def _seed_ai_tables(engine) -> None:
    """Re-seed contract/default tables from the migration's fixed literals
    (reset_ai1a_tables wipes them; alembic won't replay an applied revision)."""
    import importlib.util
    from pathlib import Path

    migration_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "20261003_ai1a_config_prompts.py"
    )
    spec = importlib.util.spec_from_file_location(
        "ai1a_seed_module_", migration_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from app.models import PromptContractVersion, PromptDefaultVersion

    contract_rows, default_rows = [], []
    for raw in module.SEED_ROWS:
        row = dict(raw)
        for key in ("input_vars", "output_schema", "guidance_fields",
                    "guidance_map"):
            if key in row:
                row[key] = json.loads(row[key])
        row["created_by"] = None
        row["created_at"] = module.SEED_CREATED_AT
        if "default_revision" in row:
            default_rows.append(row)
        else:
            contract_rows.append(row)
    with engine.begin() as conn:
        if contract_rows:
            conn.execute(PromptContractVersion.__table__.insert(), contract_rows)
        if default_rows:
            conn.execute(PromptDefaultVersion.__table__.insert(), default_rows)

@skip_unless_enabled
class A1MigrationCompatibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _clear_material()
        cls.addClassCleanup(_clear_material)
        cls.fresh_engine = make_engine("kindergarten_test_ai1a_fresh")
        check_environment(cls.fresh_engine)

    def test_a_empty_database_upgrade(self):
        run_alembic(["upgrade", "head"], "kindergarten_test_ai1a_fresh")
        engine = make_engine("kindergarten_test_ai1a_fresh")
        revision = ensure_schema(engine)
        self.assertEqual(revision, "20261003_ai1a_config_prompts")

    def test_b_representative_rows_survive_upgrade(self):
        engine = make_engine("kindergarten_test_ai1a")
        # 先整链升到 I4 head，再造代表行（含日内容、周草稿／确认快照与
        # 来源状态），最后 upgrade 至 1A head 并做升前后整个旧表行集比较。
        run_alembic(
            ["upgrade", "20260924_i4_weekly_plans"], "kindergarten_test_ai1a"
        )
        reset_base_tables(engine)
        seed_world(engine)
        from app.services import daily_plan_service, weekly_plan_service
        from sqlalchemy.orm import Session

        session = Session(engine, future=True)
        try:
            daily_plan, _content, _created = daily_plan_service.create_or_open(
                session, snap(TEACHER_A), class_id=None,
                plan_date=date(2026, 8, 10),
            )
            daily_plan_service.save(
                session, snap(TEACHER_A), plan_id=daily_plan.id,
                expected_content_version=1,
                adopted_content=full_day_content(),
            )
            weekly = weekly_plan_service.create_or_open_weekly_plan(
                session, snap(TEACHER_A), term_id="ter_ai1a", week_number=2
            )
            import app.services.weekly_plan_read_service as read_service

            detail = read_service.get_detail(
                session, weekly.plan.id, account_id=TEACHER_A["id"],
                role="teacher", class_id="cls_ai1a",
            )
            candidates = [
                c for c in detail["source_candidates"]
                if c["category"] == "collective"
            ]
            self.assertTrue(candidates, "必须有真实来源候选")
            candidate = candidates[0]
            ref = {
                "source_kind": candidate["source_kind"],
                "daily_plan_id": candidate["daily_plan_id"],
                "content_id": candidate["content_id"],
                "content_version": candidate["content_version"],
                "group_id": candidate["group_id"],
                "game_id": candidate["game_id"],
            }
            weekly = weekly_plan_service.save_weekly_plan(
                session, snap(TEACHER_A), plan_id=weekly.plan.id,
                expected_draft_version=weekly.draft.version,
                patch={"theme": "升级前的周主题",
                       "outdoor_game_slots": {"collective_1": ref}},
                class_id=None,
            )
            confirmed = weekly_plan_service.confirm_weekly_plan(
                session, snap(TEACHER_A), plan_id=weekly.plan.id,
                expected_draft_version=weekly.draft.version,
                acknowledge_missing=True, acknowledge_stale=True,
                note=None, class_id=None,
            )
            self.assertGreaterEqual(confirmed.confirmed.version, 1)
            # 草稿／确认 JSON 包含真实来源身份与非空引用文本（S5）。
            with engine.begin() as conn:
                draft_content = conn.execute(
                    text(
                        "SELECT content FROM weekly_plan_contents "
                        "WHERE weekly_plan_id = :p ORDER BY version DESC "
                        "LIMIT 1"
                    ),
                    {"p": weekly.plan.id},
                ).scalar()
                confirmed_content = conn.execute(
                    text(
                        "SELECT content FROM "
                        "weekly_plan_confirmed_contents "
                        "WHERE weekly_plan_id = :p ORDER BY version DESC "
                        "LIMIT 1"
                    ),
                    {"p": weekly.plan.id},
                ).scalar()
            draft_json = draft_content if isinstance(
                draft_content, dict
            ) else json.loads(draft_content)
            confirmed_json = confirmed_content if isinstance(
                confirmed_content, dict
            ) else json.loads(confirmed_content)
            slot = draft_json["outdoor_game_slots"]["collective_1"]
            self.assertIsNotNone(slot)
            self.assertEqual(slot["daily_plan_id"], candidate["daily_plan_id"])
            self.assertEqual(slot["game_id"], candidate["game_id"])
            self.assertTrue(slot.get("name"))
            self.assertTrue(draft_json["theme"])  # 非空文本
            confirmed_slot = confirmed_json["outdoor_game_slots"]["collective_1"]
            self.assertIsNotNone(confirmed_slot)
            self.assertEqual(
                confirmed_slot["daily_plan_id"], candidate["daily_plan_id"]
            )
            self.assertTrue(confirmed_slot.get("name"))
        finally:
            session.close()

        compare_tale = (
            "daily_plans",
            "daily_plan_contents",
            "weekly_plans",
            "weekly_plan_contents",
            "weekly_plan_confirmed_contents",
            "weekly_plan_sync_states",
            "operation_records",
            "accounts",
            "sessions",
            "classes",
            "teacher_assignments",
            "terms",
            "calendar_revisions",
            "calendar_days",
            "school_settings",
            "first_admin_control",
        )
        before = dump_world_rows(engine, compare_tale)
        run_alembic(["upgrade", "head"], "kindergarten_test_ai1a")
        after = dump_world_rows(engine, compare_tale)
        for table in compare_tale:
            self.assertEqual(before[table], after[table], f"旧表 {table} 行在升级后必须完全一致")

        revision = ensure_schema(engine)
        self.assertEqual(revision, "20261003_ai1a_config_prompts")
        self._assert_seed_matches_registry(engine)

    def _assert_seed_matches_registry(self, engine) -> None:
        from app.services.ai_prompt_registry import (
            contract_snapshot,
            guidance_defaults_snapshot,
        )
        with engine.begin() as conn:
            contracts = conn.execute(
                text(
                    "SELECT task_type, contract_version, input_vars, "
                    "output_schema, guidance_fields, created_by "
                    "FROM prompt_contract_versions"
                )
            ).fetchall()
            defaults = conn.execute(
                text(
                    "SELECT task_type, default_revision, contract_version, "
                    "guidance_map, created_by FROM prompt_default_versions"
                )
            ).fetchall()
        snapshot = contract_snapshot()
        defaults_snapshot = guidance_defaults_snapshot()
        self.assertEqual(len(contracts), 7)
        self.assertEqual(len(defaults), 7)
        for row in contracts:
            task = row[0]
            self.assertEqual(row[1], 1)
            self.assertEqual(json.loads(row[2]), snapshot[task]["input_vars"])
            self.assertEqual(json.loads(row[3]), snapshot[task]["output_schema"])
            self.assertEqual(json.loads(row[4]), snapshot[task]["guidance_fields"])
            self.assertIsNone(row[5])
        for row in defaults:
            task = row[0]
            self.assertEqual(row[1], 1)
            self.assertEqual(row[2], 1)
            self.assertEqual(json.loads(row[3]), defaults_snapshot[task])
            self.assertIsNone(row[4])

    def test_c_unique_head_and_composite_fks(self):
        engine = self.fresh_engine
        self.assertEqual(ensure_schema(engine),
                         "20261003_ai1a_config_prompts")
        # 先放一个真实账号与审计行（FK 参照）。
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO accounts (id, username, password_hash, "
                    "display_name, role, is_active, version, auth_version, "
                    "created_at, updated_at) VALUES "
                    "('xacc', 'xacc', 'x', 'x', 'teacher', 1, 1, 1, NOW(), NOW())"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO operation_records (id, operator_id, "
                    "operator_type, action, target_type, target_id, "
                    "target_version_after, target_account_id, "
                    "account_version_after, created_at) VALUES "
                    "('oprc_ai1a', NULL, 'server_operator', 'fixture', "
                    "'account', 'xacc', 1, 'xacc', 1, NOW())"
                )
            )
        with self.assertRaises((IntegrityError, OperationalError)):
            with engine.begin() as conn:
                # 无对应 version 行的 head 指针：复合 FK 拒绝。
                conn.execute(
                    text(
                        "INSERT INTO ai_config_heads (account_id, "
                        "config_version, updated_at) VALUES "
                        "('xacc', 5, NOW())"
                    )
                )
        with self.assertRaises((IntegrityError, OperationalError)):
            with engine.begin() as conn:
                # CIPHER 有值而 key_id 为 NULL：CHECK 拒绝。
                conn.execute(
                    text(
                        "INSERT INTO ai_config_versions (id, account_id, "
                        "version, protocol_id, base_url, model, "
                        "secret_ciphertext, key_id, operation_record_id, "
                        "created_by, created_at) VALUES "
                        "('xv1', 'xacc', 1, 'chat_completions_v1', "
                        "'https://a.b/v1', 'm', 'C', NULL, 'oprc_ai1a', "
                        "'xacc', NOW())"
                    )
                )


@skip_unless_enabled
class B1PersonalIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _clear_material()
        cls.addClassCleanup(_clear_material)
        cls.engine = make_engine("kindergarten_test_ai1a_fresh")

    def setUp(self) -> None:
        _world(self.engine)
        import os as _os

        _set_material(_os.urandom(32), "ai1a-b1-key")
        self.addCleanup(_clear_material)

    def test_cross_account_access_forbidden(self):
        # 甲先建一版配置（带密钥）。
        session = _session_from_factory()
        try:
            ai_config_service.save_config(
                session, snap(TEACHER_A), 0,
                "chat_completions_v1", "https://api.a.com/v1", "model-x",
                secret="A-S3CRET",
            )
        finally:
            session.close()
        # 乙不能读／改甲的配置或指导。
        session = _session_from_factory()
        try:
            from app.services.auth_service import Forbidden

            with self.assertRaises(Forbidden):
                ai_config_service.get_config(
                    session, snap(TEACHER_B), TEACHER_A["id"]
                )
            with self.assertRaises(Forbidden):
                prompt_service.initialize_task(
                    session, snap(TEACHER_B), TEACHER_A["id"], TASK
                )
        finally:
            session.close()

    def test_non_admin_cannot_publish_default(self):
        from app.services.auth_service import Forbidden

        session = _session_from_factory()
        try:
            with self.assertRaises(Forbidden):
                prompt_service.update_default(
                    session, snap(TEACHER_A), TASK,
                    {"theme": "教师自己的默认"},
                    1,
                )
        finally:
            session.close()

    def test_inactive_account_session_paths_rejected(self):
        # 快照与锁定行不一致（auth_version / 角色变化）→ AuthRequired／AuthRequired。
        from app.services.auth_service import AuthRequired

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE accounts SET auth_version = 2, version = 2 "
                    "WHERE id = :id"
                ),
                {"id": TEACHER_A["id"]},
            )
        # 有效快照（auth_version=1）与锁定行不一致。
        session = _session_from_factory()
        try:
            with self.assertRaises(AuthRequired):
                ai_config_service.save_config(
                    session, snap(TEACHER_A), 0,
                    "chat_completions_v1", "https://api.a.com/v1", "m",
                    secret="s",
                )
        finally:
            session.close()
        # 会话撤销。
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE sessions SET revoked_at = NOW() "
                    "WHERE id = :id"
                ),
                {"id": TEACHER_A["session"]},
            )
        session = _session_from_factory()
        try:
            with self.assertRaises(AuthRequired):
                prompt_service.initialize_task(
                    session, snap(TEACHER_A), TEACHER_A["id"], TASK
                )
        finally:
            session.close()


@skip_unless_enabled
class C1InitAndDoubleWrite(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _clear_material()
        cls.addClassCleanup(_clear_material)
        cls.engine = make_engine("kindergarten_test_ai1a_fresh")

    def setUp(self) -> None:
        _world(self.engine)
        import os as _os

        _set_material(_os.urandom(32), "ai1a-c1-key")
        self.addCleanup(_clear_material)

    def test_concurrent_first_initialize_idempotent(self):
        results = []
        errors = []

        def run(index: int) -> None:
            session = _session_from_factory()
            try:
                results.append(prompt_service.initialize_task(
                    session, snap(TEACHER_A), TEACHER_A["id"], TASK
                ))
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(exc)
            finally:
                session.close()

        run(0)
        run(1)
        self.assertFalse(errors)
        created = [r for r in results if not r.get("idempotent")]
        idem = [r for r in results if r.get("idempotent")]
        self.assertEqual(len(created), 1)
        self.assertEqual(len(idem), 1)
        with self.engine.begin() as conn:
            heads = conn.execute(
                text(
                    "SELECT account_id, task_type, current_personal_revision "
                    "FROM personal_prompt_heads WHERE account_id = :id"
                ),
                {"id": TEACHER_A["id"]},
            ).fetchall()
            version_rows = conn.execute(
                text(
                    "SELECT personal_revision FROM personal_prompt_versions "
                    "WHERE account_id = :id"
                ),
                {"id": TEACHER_A["id"]},
            ).fetchall()
        self.assertEqual(len(heads), 1)
        self.assertEqual(len(version_rows), 1)  # 仅 1 版本行，无悬空行

    def test_concurrent_config_same_expected(self):
        from app.services import auth_service
        from app.services.ai_config_service import AiConfigValidationError

        ok, conflict = [], []

        def run(index: int) -> None:
            session = _session_from_factory()
            try:
                ai_config_service.save_config(
                    session, snap(TEACHER_B), 0,
                    "chat_completions_v1",
                    "https://api.b.com/v1", "model-b", secret="B3",
                )
                ok.append(index)
            except auth_service.VersionConflict:
                conflict.append(index)
            except AiConfigValidationError:
                raise
            finally:
                session.close()

        run(0)
        run(1)
        self.assertEqual(len(ok), 1)
        self.assertEqual(len(conflict), 1)
        with self.engine.begin() as conn:
            heads = conn.execute(
                text(
                    "SELECT account_id, config_version FROM ai_config_heads "
                    "WHERE account_id = :id"
                ),
                {"id": TEACHER_B["id"]},
            ).fetchall()
            version_rows = conn.execute(
                text(
                    "SELECT version FROM ai_config_versions "
                    "WHERE account_id = :id"
                ),
                {"id": TEACHER_B["id"]},
            ).fetchall()
        self.assertEqual(len(heads), 1)
        self.assertEqual(len(version_rows), 1)




@skip_unless_enabled
class D1KeepReEncryptRotateClear(unittest.TestCase):
    """§9.2 保留重加密／轮换／清除 + NULL 约束 + 执行器读取语义。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = make_engine("kindergarten_test_ai1a_fresh")
        check_environment(cls.engine)

    def setUp(self) -> None:
        _world(self.engine)
        import os as _os

        self.key = _os.urandom(32)
        _set_material(self.key, "ai1a-test-key")
        self.addCleanup(_clear_material)

    def _config_row(self, account_id: str, version: int):
        with self.engine.begin() as conn:
            return conn.execute(
                text(
                    "SELECT secret_ciphertext, key_id FROM "
                    "ai_config_versions WHERE account_id = :id AND "
                    "version = :v"
                ),
                {"id": account_id, "v": version},
            ).fetchone()

    def test_keep_reencrypt_and_pinned_read(self):
        session = _session_from_factory()
        try:
            ai_config_service.save_config(
                session, snap(TEACHER_A), 0, "chat_completions_v1",
                "https://api.a.com/v1", "model-1", secret="PLAINT1",
            )
            # URL/model-only PATCH：未传 secret → 保留重加密（新 nonce + 新 AAD）。
            ai_config_service.save_config(
                session, snap(TEACHER_A), 1, "chat_completions_v1",
                "https://api.a.com/v2", "model-1",
            )
        finally:
            session.close()
        v1 = self._config_row(TEACHER_A["id"], 1)
        v2 = self._config_row(TEACHER_A["id"], 2)
        self.assertIsNotNone(v1[0])
        self.assertNotEqual(v1[0], v2[0])
        # head 在 v2；指定旧版本读取仍可解密、不换代。
        session = _session_from_factory()
        try:
            pinned = ai_config_service.read_pinned_config(
                session, TEACHER_A["id"], 1
            )
            self.assertEqual(pinned.reveal_secret(), "PLAINT1")
            self.assertEqual(pinned.base_url, "https://api.a.com/v1")
            head = ai_config_service.get_config(
                session, snap(TEACHER_A), TEACHER_A["id"]
            )
            self.assertEqual(head.version, 2)
            self.assertEqual(head.base_url, "https://api.a.com/v2")
        finally:
            session.close()

    def test_tampered_old_ciphertext_blocks_keep_patch_atomically(self):
        session = _session_from_factory()
        try:
            ai_config_service.save_config(
                session, snap(TEACHER_A), 0, "chat_completions_v1",
                "https://api.a.com/v1", "model-1", secret="PLAINT1",
            )
        finally:
            session.close()
        v1 = self._config_row(TEACHER_A["id"], 1)
        # 篡改旧版本密文（模拟篡改／换库）。
        blob = bytearray(base64.b64decode(v1[0]))
        blob[13] ^= 0xFF
        tampered = base64.b64encode(bytes(blob)).decode()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE ai_config_versions SET secret_ciphertext = :c "
                    "WHERE account_id = :id AND version = 1"
                ),
                {"c": tampered, "id": TEACHER_A["id"]},
            )
        from app.services.auth_service import (
            Account,
            OperationRecord,
        )

        # 保留式 PATCH → DecryptUnavailable，事务整体回滚：head 不推进、
        # 无新版本行、无新审计行。
        ops_before = self._count("operation_records")
        events_before = self._count("prompt_change_records")
        session = _session_from_factory()
        try:
            with self.assertRaises(ai_crypto.DecryptUnavailable):
                ai_config_service.save_config(
                    session, snap(TEACHER_A), 1, "chat_completions_v1",
                    "https://api.a.com/v9", "model-9",
                )
        finally:
            session.close()
        self.assertEqual(ops_before, self._count("operation_records"))
        self.assertEqual(events_before, self._count("prompt_change_records"))
        self.assertEqual(
            self._head_version(TEACHER_A["id"]), 1
        )
        self.assertEqual(len(self._all_versions(TEACHER_A["id"])), 1)
        # 重连后一致性持久。
        session = _session_from_factory()
        try:
            view = ai_config_service.get_config(
                session, snap(TEACHER_A), TEACHER_A["id"]
            )
            self.assertEqual(view.version, 1)
        finally:
            session.close()

    def test_rotation_new_secret(self):
        session = _session_from_factory()
        try:
            ai_config_service.save_config(
                session, snap(TEACHER_A), 0, "chat_completions_v1",
                "https://api.a.com/v1", "model-1", secret="OLDSECRET",
            )
            # 轮换：非空新 secret；旧行字节不动。
            v1 = self._config_row(TEACHER_A["id"], 1)
            ai_config_service.save_config(
                session, snap(TEACHER_A), 1, "chat_completions_v1",
                "https://api.a.com/v1", "model-1", secret="NEWSECRET",
            )
            v1_after = self._config_row(TEACHER_A["id"], 1)
            v2 = self._config_row(TEACHER_A["id"], 2)
            self.assertEqual(v1[0], v1_after[0])
            self.assertNotEqual(v1[0], v2[0])
            pinned = ai_config_service.read_pinned_config(
                session, TEACHER_A["id"], 1
            )
            self.assertEqual(pinned.reveal_secret(), "OLDSECRET")
            pinned2 = ai_config_service.read_pinned_config(
                session, TEACHER_A["id"], 2
            )
            self.assertEqual(pinned2.reveal_secret(), "NEWSECRET")
        finally:
            session.close()

    def test_clear_secret_without_key_material(self):
        session = _session_from_factory()
        try:
            ai_config_service.save_config(
                session, snap(TEACHER_A), 0, "chat_completions_v1",
                "https://api.a.com/v1", "model-1", secret="S",
            )
        finally:
            session.close()
        # 主密钥清除（缺失材料）下 clear_secret 仍成功：新“未配置”版本。
        _clear_material()
        session = _session_from_factory()
        try:
            view = ai_config_service.clear_secret(session, snap(TEACHER_A), 1)
            self.assertEqual(view.version, 2)
            self.assertFalse(view.has_secret)
            self.assertEqual(view.ready_reason, "MISSING_SECRET")
        finally:
            session.close()
        row = self._config_row(TEACHER_A["id"], 2)
        self.assertIsNone(row[0])
        self.assertIsNone(row[1])
        # 已清除版本的非密钥更新仍然无密钥且无需解密。
        session = _session_from_factory()
        try:
            view = ai_config_service.save_config(
                session, snap(TEACHER_A), 2, "chat_completions_v1",
                "https://api.a.com/v3", "model-1",
            )
            self.assertEqual(view.version, 3)
            self.assertFalse(view.has_secret)
        finally:
            session.close()

    def test_key_id_mismatch_rejected(self):
        session = _session_from_factory()
        try:
            ai_config_service.save_config(
                session, snap(TEACHER_A), 0, "chat_completions_v1",
                "https://api.a.com/v1", "model-1", secret="S",
            )
        finally:
            session.close()
        # 模拟 key_id 记录意外变化 → 解密拒绝。
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE ai_config_versions SET key_id = 'wrong' "
                    "WHERE account_id = :id AND version = 1"
                ),
                {"id": TEACHER_A["id"]},
            )
        session = _session_from_factory()
        try:
            with self.assertRaises(ai_crypto.DecryptUnavailable):
                ai_config_service.read_pinned_config(
                    session, TEACHER_A["id"], 1
                )
        finally:
            session.close()

    def _count(self, table: str) -> int:
        with self.engine.begin() as conn:
            return conn.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar()

    def _head_version(self, account_id: str):
        with self.engine.begin() as conn:
            return conn.execute(
                text(
                    "SELECT config_version FROM ai_config_heads "
                    "WHERE account_id = :id"
                ),
                {"id": account_id},
            ).scalar()

    def _all_versions(self, account_id: str):
        with self.engine.begin() as conn:
            return conn.execute(
                text(
                    "SELECT version FROM ai_config_versions "
                    "WHERE account_id = :id"
                ),
                {"id": account_id},
            ).fetchall()


VARIANT_FIELD_V2 = "assist_notes_v2"  # R2: v1 中不存在的新字段
VARIANT_FIELD_V3 = "assist_notes_v3"  # v2 中不存在的新字段（v3 场景）


def publish_variant_contract(engine, task: str, from_field: str) -> int:
    """测试夹具按系统发布协议构造合成契约 v2（DML 事务；锚点排他锁，
    不新增产品 schema 编辑入口）：

    * guidance_fields 在 v1 基础上真实新增 ``from_field``（v1 不存在的字段），
      并发布匹配的默认修订（全部字段，新字段有预填文本）；
    * 默认修订为该任务全局追加的一个 revision，不能与 v1 revision 1 冲突。
    返回新默认修订号。
    """
    from app.services.ai_prompt_registry import get_registry

    new_fields = [from_field]
    mapping = dict(get_registry(task).guidance_defaults)
    for field in new_fields:
        mapping[field] = "由契约v2预填的默认指导"
    with engine.begin() as conn:
        conn.execute(text("SET innodb_lock_wait_timeout = 10"))
        # 排他锚点锁（与迁移级 FOR UPDATE 发布协议一致）。
        conn.execute(
            text(
                "SELECT id FROM prompt_contract_versions "
                "WHERE task_type = :task AND contract_version = 1 FOR UPDATE"
            ),
            {"task": task},
        )
        next_revision = conn.execute(
            text(
                "SELECT COALESCE(MAX(default_revision), 0) + 1 FROM "
                "prompt_default_versions WHERE task_type = :task"
            ),
            {"task": task},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO prompt_contract_versions (id, task_type, "
                "contract_version, input_vars, output_schema, "
                "guidance_fields, created_by, created_at) "
                "SELECT CONCAT('pcv2|', :task), :task, 2, c.input_vars, "
                "c.output_schema, :fields, NULL, NOW() "
                "FROM prompt_contract_versions c "
                "WHERE c.task_type = :task AND c.contract_version = 1"
            ),
            {"task": task, "fields": json.dumps(
                _contract_fields_sorted(task, get_registry, new_fields),
                ensure_ascii=False)},
        )
        conn.execute(
            text(
                "INSERT INTO prompt_default_versions (id, task_type, "
                "default_revision, contract_version, guidance_map, "
                "created_by, created_at) VALUES "
                "(CONCAT('pdv2|', :task), :task, :rev, 2, :map, NULL, NOW())"
            ),
            {"task": task, "rev": next_revision,
             "map": json.dumps(mapping, ensure_ascii=False)},
        )
    return next_revision


def _contract_fields_sorted(task: str, get_registry, new_fields) -> list[str]:
    base = list(get_registry(task).guidance_defaults.keys())
    return sorted(set(base) | set(new_fields))


def read_contract_fields(engine, task: str, version: int) -> list[str]:
    with engine.begin() as conn:
        raw = conn.execute(
            text(
                "SELECT guidance_fields FROM prompt_contract_versions "
                "WHERE task_type = :t AND contract_version = :v"
            ),
            {"t": task, "v": version},
        ).scalar_one()
    return json.loads(raw)


def publish_contract_v3(engine, task: str, base_version: int = 2) -> int:
    """合成 v3：在 v2 基础上再真实新增 ``VARIANT_FIELD_V3`` 字段并发布匹配
    默认修订；同样按系统协议（ＤＭＬ ＋ 锚点排他锁）。"""
    v2_fields = read_contract_fields(engine, task, base_version)
    new_fields = list(v2_fields) + [VARIANT_FIELD_V3]
    mapping_projection = fetch_matching_default(engine, task, base_version)
    mapping = dict(mapping_projection)
    mapping[VARIANT_FIELD_V3] = "由契约v3预填的默认指导"
    with engine.begin() as conn:
        conn.execute(text("SET innodb_lock_wait_timeout = 10"))
        conn.execute(
            text(
                "SELECT id FROM prompt_contract_versions "
                "WHERE task_type = :task AND contract_version = 1 FOR UPDATE"
            ),
            {"task": task},
        )
        next_revision = conn.execute(
            text(
                "SELECT COALESCE(MAX(default_revision), 0) + 1 FROM "
                "prompt_default_versions WHERE task_type = :task"
            ),
            {"task": task},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO prompt_contract_versions (id, task_type, "
                "contract_version, input_vars, output_schema, "
                "guidance_fields, created_by, created_at) "
                "SELECT CONCAT('pcv3|', :task), :task, 3, c.input_vars, "
                "c.output_schema, :fields, NULL, NOW() "
                "FROM prompt_contract_versions c "
                "WHERE c.task_type = :task AND c.contract_version = :from"
            ),
            {"task": task, "from": base_version,
             "fields": json.dumps(new_fields, ensure_ascii=False)},
        )
        conn.execute(
            text(
                "INSERT INTO prompt_default_versions (id, task_type, "
                "default_revision, contract_version, guidance_map, "
                "created_by, created_at) VALUES "
                "(CONCAT('pdv3|', :task), :task, :rev, 3, :map, NULL, NOW())"
            ),
            {"task": task, "rev": next_revision,
             "map": json.dumps(mapping, ensure_ascii=False)},
        )
    return next_revision


def fetch_matching_default(engine, task: str, contract_version: int) -> dict:
    """读取某 contract 下最新匹配默认修订的字段映射（仅测试共用夹具）。"""
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT guidance_map FROM prompt_default_versions "
                "WHERE task_type = :t AND contract_version = :c "
                "ORDER BY default_revision DESC LIMIT 1"
            ),
            {"t": task, "c": contract_version},
        ).scalar_one_or_none()
    return dict(json.loads(row)) if row else {}


@skip_unless_enabled
class E1ContractPublishAndAdapt(unittest.TestCase):
    """§7.4：发布先／适配先两种合法提交顺序 + 待适配态阻断。"""

    @classmethod
    def setUpClass(cls) -> None:
        _clear_material()
        cls.addClassCleanup(_clear_material)
        cls.engine = make_engine("kindergarten_test_ai1a_fresh")
        check_environment(cls.engine)

    def setUp(self) -> None:
        _world(self.engine)
        _reset_variant_contracts(self.engine, TASK)

    def test_a_publish_first_old_adapt_rejected_rolls_back(self):
        session = _session_from_factory()
        try:
            prompt_service.initialize_task(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
        finally:
            session.close()
        # 同一连接先建普通 REPEATABLE READ 快照；另一连接发布提交后，同一
        # Session 中 adapt 的 locking read 必须看见 v2 并拒绝旧目标。
        session = _session_from_factory()
        try:
            latest_before = prompt_service.resolve_prompt(
                session, TEACHER_A["id"], TASK
            )
            self.assertEqual(latest_before.based_contract_version, 1)
            variant_revision = publish_variant_contract(
                self.engine, TASK, VARIANT_FIELD_V2
            )
            v2_fields = read_contract_fields(self.engine, TASK, 2)
            self.assertIn(VARIANT_FIELD_V2, v2_fields)
            full_map = {f: "甲老师适配后的指导" for f in v2_fields}
            with self.assertRaises(prompt_service.ContractAdvanced):
                prompt_service.adapt(
                    session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                    1, full_map, 1,
                )
        finally:
            session.close()
        # 回滚彻底：无新个人版本、adapt 事件/审计均未落。
        with self.engine.begin() as conn:
            versions = conn.execute(
                text(
                    "SELECT personal_revision FROM personal_prompt_versions "
                    "WHERE account_id = :id"
                ),
                {"id": TEACHER_A["id"]},
            ).fetchall()
            adapt_events = conn.execute(
                text(
                    "SELECT COUNT(*) FROM prompt_change_records "
                    "WHERE task_type = :t AND event_kind = 'adapt'"
                ),
                {"t": TASK},
            ).scalar()
            adapt_ops = conn.execute(
                text(
                    "SELECT COUNT(*) FROM operation_records "
                    "WHERE action = 'prompt_adapt'"
                )
            ).scalar()
        self.assertEqual([v[0] for v in versions], [1])
        self.assertEqual(adapt_events, 0)
        self.assertEqual(adapt_ops, 0)
        # 重新读取后按 v2 适配成功（含新字段与匹配默认修订号）。
        session = _session_from_factory()
        try:
            result = prompt_service.adapt(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                2, full_map, 1,
            )
            self.assertEqual(result["personal_revision"], 2)
            self.assertEqual(result["accepted_default_revision"], variant_revision)
            self.assertEqual(result["based_contract_version"], 2)
        finally:
            session.close()

    _publish_error: list = []

    def _try_publish_once(self, done: threading.Event) -> None:
        try:
            publish_variant_contract(self.engine, TASK, VARIANT_FIELD_V2)
        except Exception as exc:
            __class__._publish_error.append(exc)
        finally:
            done.set()

    def test_b_publish_waits_for_held_share_anchor(self):
        """持共享锚点期间发布排他锁被阻塞；释放后可继续（互斥证明）。"""
        __class__._publish_error = []
        started = threading.Event()
        share_conn = self.engine.connect()
        try:
            share_conn.execute(text("SET innodb_lock_wait_timeout = 10"))
            share_conn.execute(
                text(
                    "SELECT id FROM prompt_contract_versions "
                    "WHERE task_type = :t AND contract_version = 1 FOR SHARE"
                ),
                {"t": TASK},
            )
            thread = threading.Thread(
                target=self._try_publish_once, args=(started,)
            )
            thread.start()
            import time

            time.sleep(2.0)
            self.assertFalse(started.is_set())
        finally:
            share_conn.commit()  # 释放共享锚点
            share_conn.close()
            thread.join(30)
            self.assertFalse(thread.is_alive())
            self.assertEqual(__class__._publish_error, [])
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT contract_version FROM prompt_contract_versions "
                    "WHERE task_type = :t"
                ),
                {"t": TASK},
            ).fetchall()
        self.assertEqual([v[0] for v in rows], [1, 2])

    def test_c_adapt_first_then_publisher_flags_required(self):
        # 甲初始化并基于 v1；adapt 先提交（旧契约仍有效时合法），随后发布
        # 推进 → 解析显示待适配；钉住读取保持旧版本；其他任务不受阻。
        session = _session_from_factory()
        try:
            prompt_service.initialize_task(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
        finally:
            session.close()
        v1_fields = read_contract_fields(self.engine, TASK, 1)
        self.assertNotIn(VARIANT_FIELD_V2, v1_fields)
        full_map = {f: "甲老师适配后的指导" for f in v1_fields}
        session = _session_from_factory()
        try:
            result = prompt_service.adapt(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                1, full_map, 1,
            )
            self.assertEqual(result["personal_revision"], 2)
        finally:
            session.close()
        publish_variant_contract(self.engine, TASK, VARIANT_FIELD_V2)
        session = _session_from_factory()
        try:
            resolution = prompt_service.resolve_prompt(
                session, TEACHER_A["id"], TASK
            )
            self.assertEqual(resolution.personal_revision, 2)
            self.assertEqual(resolution.based_contract_version, 1)
            self.assertFalse(resolution.ready)
            self.assertEqual(resolution.ready_reason, "ADAPTATION_REQUIRED")
            pinned = prompt_service.resolve_prompt(
                session, TEACHER_A["id"], TASK, pinned_revision=1
            )
            self.assertTrue(pinned.ready)
            self.assertEqual(pinned.based_contract_version, 1)
            other = prompt_service.read_task(
                session, snap(TEACHER_A), TEACHER_A["id"], "weekly_columns"
            )
            self.assertEqual(other["state"], "not_initialized")
        finally:
            session.close()

    def test_d_accept_reject_blocked_in_adaptation_required(self):
        session = _session_from_factory()
        try:
            prompt_service.initialize_task(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
        finally:
            session.close()
        publish_variant_contract(self.engine, TASK, VARIANT_FIELD_V2)
        session = _session_from_factory()
        try:
            with self.assertRaises(prompt_service.PromptAdaptationRequired):
                prompt_service.accept_default(
                    session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                    1, ["process"], 1,
                )
            with self.assertRaises(prompt_service.PromptAdaptationRequired):
                prompt_service.reject_default(
                    session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                    1, 1,
                )
        finally:
            session.close()
        with self.engine.begin() as conn:
            seen, rejected = conn.execute(
                text(
                    "SELECT last_seen_default_revision, "
                    "last_rejected_default_revision FROM "
                    "personal_prompt_heads WHERE account_id = :id AND "
                    "task_type = :t"
                ),
                {"id": TEACHER_A["id"], "t": TASK},
            ).fetchone()
        self.assertEqual(seen, 1)
        self.assertIsNone(rejected)



@skip_unless_enabled
class E2ContractFieldsetScenarios(unittest.TestCase):
    """R2: 合成 v2/v3 真新增字段下的初始化/适配/编辑/默认发布。"""

    @classmethod
    def setUpClass(cls) -> None:
        _clear_material()
        cls.addClassCleanup(_clear_material)
        cls.engine = make_engine("kindergarten_test_ai1a_fresh")
        check_environment(cls.engine)

    def setUp(self) -> None:
        _world(self.engine)
        _reset_variant_contracts(self.engine, TASK)

    def test_a_initialize_after_publish_uses_v2_fields(self):
        variant_revision = publish_variant_contract(self.engine, TASK, VARIANT_FIELD_V2)
        session = _session_from_factory()
        try:
            result = prompt_service.initialize_task(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
            self.assertEqual(result["based_contract_version"], 2)
            self.assertIn(VARIANT_FIELD_V2, result["guidance_map"])
            self.assertEqual(result["accepted_default_revision"], variant_revision)
        finally:
            session.close()

    def test_b_adapt_after_publish_with_v2_map(self):
        session = _session_from_factory()
        try:
            prompt_service.initialize_task(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
        finally:
            session.close()
        variant_revision = publish_variant_contract(self.engine, TASK, VARIANT_FIELD_V2)
        v2_fields = read_contract_fields(self.engine, TASK, 2)
        full_map = {f: "适配后的指导" for f in v2_fields}
        self.assertIn(VARIANT_FIELD_V2, full_map)
        session = _session_from_factory()
        try:
            result = prompt_service.adapt(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                2, full_map, 1,
            )
            self.assertEqual(result["based_contract_version"], 2)
            self.assertIn(VARIANT_FIELD_V2, result["guidance_map"])
            self.assertEqual(result["accepted_default_revision"], variant_revision)
        finally:
            session.close()

    def test_c_personal_edit_validates_against_based_contract(self):
        """发布 v2 后：v1-based 个人编辑按 v1 字段集、based 不变且不解除待适配；
        v2 新字段 patch 被拒绝。"""
        session = _session_from_factory()
        try:
            prompt_service.initialize_task(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
        finally:
            session.close()
        publish_variant_contract(self.engine, TASK, VARIANT_FIELD_V2)
        session = _session_from_factory()
        try:
            # v2 新字段 patch 在基于 v1 的个人版本上必须拒绝。
            with self.assertRaises(prompt_service.FieldViolation):
                prompt_service.save_guidance(
                    session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                    {VARIANT_FIELD_V2: "不应可写"}, 1,
                )
            result = prompt_service.save_guidance(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                {"process": "甲老师自己的过程指导"}, 1,
            )
            self.assertEqual(result["based_contract_version"], 1)
        finally:
            session.close()
        # 结构／默认不静默改写：仍是基于 v1 的字段集；编辑不解除待适配。
        session = _session_from_factory()
        try:
            view = prompt_service.read_task(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
            self.assertNotIn(VARIANT_FIELD_V2, view["guidance_map"])
            self.assertEqual(view["based_contract_version"], 1)
            self.assertEqual(view["adaptation_state"],
                             prompt_service.STATE_ADAPTATION_REQUIRED)
            self.assertEqual(view["required_contract_version"], 2)
        finally:
            session.close()

    def test_f_edit_new_field_after_adapt_to_v2(self):
        """初始化（v1）→ 发布 v2 → 适配到 v2 → 编辑真实新增字段成功。"""
        session = _session_from_factory()
        try:
            prompt_service.initialize_task(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
        finally:
            session.close()
        variant_revision = publish_variant_contract(
            self.engine, TASK, VARIANT_FIELD_V2
        )
        v2_fields = read_contract_fields(self.engine, TASK, 2)
        full_map = {f: "适配后的通用指导" for f in v2_fields}
        session = _session_from_factory()
        try:
            adapted = prompt_service.adapt(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                2, full_map, 1,
            )
            self.assertEqual(adapted["based_contract_version"], 2)
            # 新字段可编辑。
            edited = prompt_service.save_guidance(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                {VARIANT_FIELD_V2: "甲老师给新字段的自定指导"},
                adapted["personal_revision"],
            )
            self.assertEqual(
                edited["guidance_map"][VARIANT_FIELD_V2],
                "甲老师给新字段的自定指导",
            )
            revisions_before = self._revision_count()
            # 未知字段拒绝（typed），全回滚：不产生新修订。
            with self.assertRaises(prompt_service.FieldViolation):
                prompt_service.save_guidance(
                    session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                    {"不存在字段": "x"}, edited["personal_revision"],
                )
            self.assertEqual(self._revision_count(), revisions_before)
        finally:
            session.close()

    def _revision_count(self) -> int:
        with self.engine.begin() as conn:
            return conn.execute(
                text(
                    "SELECT COUNT(*) FROM personal_prompt_versions "
                    "WHERE account_id = :a AND task_type = :t"
                ),
                {"a": TEACHER_A["id"], "t": TASK},
            ).scalar()

    def test_d_admin_default_update_uses_latest_contract(self):
        variant_revision = publish_variant_contract(self.engine, TASK, VARIANT_FIELD_V2)
        session = _session_from_factory()
        try:
            result = prompt_service.update_default(
                session, snap(ADMIN), TASK,
                {VARIANT_FIELD_V2: "管理员对v2新字段的默认"}, variant_revision,
            )
            self.assertEqual(result["default_revision"], variant_revision + 1)
            self.assertEqual(result["contract_version"], 2)
            self.assertIn(VARIANT_FIELD_V2, result["guidance_map"])
        finally:
            session.close()

    def test_e_publish_v3_old_variant_adapt_rejected(self):
        session = _session_from_factory()
        try:
            prompt_service.initialize_task(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
        finally:
            session.close()
        publish_variant_contract(self.engine, TASK, VARIANT_FIELD_V2)
        publish_contract_v3(self.engine, TASK)
        v3_fields = read_contract_fields(self.engine, TASK, 3)
        self.assertIn(VARIANT_FIELD_V2, v3_fields)
        self.assertIn(VARIANT_FIELD_V3, v3_fields)
        self.assertNotIn(VARIANT_FIELD_V3, read_contract_fields(self.engine, TASK, 2))
        session = _session_from_factory()
        try:
            with self.assertRaises(prompt_service.ContractAdvanced):
                prompt_service.adapt(
                    session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                    2, {f: "适配" for f in v3_fields}, 1,
                )
        finally:
            session.close()
        with self.engine.begin() as conn:
            versions = conn.execute(
                text(
                    "SELECT personal_revision FROM personal_prompt_versions "
                    "WHERE account_id = :id"
                ),
                {"id": TEACHER_A["id"]},
            ).fetchall()
            adapt_events = conn.execute(
                text(
                    "SELECT COUNT(*) FROM prompt_change_records "
                    "WHERE event_kind = 'adapt'"
                )
            ).scalar()
        self.assertEqual([v[0] for v in versions], [1])
        self.assertEqual(adapt_events, 0)
        # 重新读取后按 v3 适配成功。
        session = _session_from_factory()
        try:
            result = prompt_service.adapt(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                3, {f: "适配" for f in v3_fields}, 1,
            )
            self.assertEqual(result["based_contract_version"], 3)
        finally:
            session.close()


    def setUp(self) -> None:
        _world(self.engine)
        _reset_variant_contracts(self.engine, TASK)



@skip_unless_enabled
class F1RejectAcceptAndAdminRaces(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _clear_material()
        cls.addClassCleanup(_clear_material)
        cls.engine = make_engine("kindergarten_test_ai1a_fresh")
        check_environment(cls.engine)

    def setUp(self) -> None:
        _world(self.engine)

    def _update_default(self, task: str, field: str, value: str,
                        expected: int = 1) -> int:
        session = _session_from_factory()
        try:
            return prompt_service.update_default(
                session, snap(ADMIN), task, {field: value}, expected
            )["default_revision"]
        finally:
            session.close()

    def test_reject_before_accept_succeeds(self):
        new_revision = self._update_default(TASK, "process", "系统更新后的过程指导")
        session = _session_from_factory()
        try:
            prompt_service.initialize_task(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
            r1 = prompt_service.reject_default(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                new_revision, 1,
            )
            self.assertFalse(r1["idempotent"])
            a1 = prompt_service.accept_default(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                new_revision, ["process"], 1,
            )
            self.assertEqual(a1["personal_revision"], 2)
            self.assertEqual(
                a1["guidance_map"]["process"], "系统更新后的过程指导"
            )
        finally:
            session.close()
        with self.engine.begin() as conn:
            events = conn.execute(
                text(
                    "SELECT event_kind, changed_fields FROM "
                    "prompt_change_records WHERE task_type = :t "
                    "ORDER BY id"
                ),
                {"t": TASK},
            ).fetchall()
        kinds = [e[0] for e in events]
        self.assertEqual(
            sorted(kinds),
            ["accept_default", "default_update", "personal_init", "reject_default"],
        )
        # 拒绝不推进 personal_revision：事件 before == after == 1。
        with self.engine.begin() as conn:
            rej = conn.execute(
                text(
                    "SELECT personal_revision_before, "
                    "personal_revision_after FROM prompt_change_records "
                    "WHERE event_kind = 'reject_default' AND "
                    "task_type = :t"
                ),
                {"t": TASK},
            ).fetchone()
        self.assertEqual(rej[0], rej[1])

    def test_accept_first_old_expected_reject_conflicts(self):
        new_revision = self._update_default(TASK, "process", "系统更新后的过程指导")
        session = _session_from_factory()
        try:
            prompt_service.initialize_task(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
            prompt_service.accept_default(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                new_revision, ["process"], 1,
            )
        finally:
            session.close()
        session = _session_from_factory()
        try:
            from app.services.auth_service import VersionConflict

            with self.assertRaises(VersionConflict):
                prompt_service.reject_default(
                    session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                    new_revision, 1,  # 旧 expected -> 冲突
                )
        finally:
            session.close()
        with self.engine.begin() as conn:
            rejects = conn.execute(
                text(
                    "SELECT COUNT(*) FROM prompt_change_records WHERE "
                    "event_kind = 'reject_default' AND task_type = :t"
                ),
                {"t": TASK},
            ).scalar()
        self.assertEqual(rejects, 0)

    def test_duplicate_reject_idempotent(self):
        new_revision = self._update_default(TASK, "process", "旧指导 v2")
        session = _session_from_factory()
        try:
            prompt_service.initialize_task(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
            prompt_service.reject_default(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                new_revision, 1,
            )
            again = prompt_service.reject_default(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                new_revision, 1,
            )
            self.assertTrue(again["idempotent"])
        finally:
            session.close()
        with self.engine.begin() as conn:
            count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM prompt_change_records WHERE "
                    "event_kind = 'reject_default' AND task_type = :t"
                ),
                {"t": TASK},
            ).scalar()
            version_rows = conn.execute(
                text(
                    "SELECT COUNT(*) FROM personal_prompt_versions "
                    "WHERE account_id = :id"
                ),
                {"id": TEACHER_A["id"]},
            ).scalar()
        self.assertEqual(count, 1)
        self.assertEqual(version_rows, 1)

    def test_two_admins_same_expected_one_winner(self):
        from app.services.auth_service import VersionConflict

        session = _session_from_factory()
        try:
            prompt_service.update_default(
                session, snap(ADMIN), TASK, {"process": "r2"}, 1
            )
        finally:
            session.close()
        ok, conflicts = [], []

        def run(index: int) -> None:
            s = _session_from_factory()
            try:
                prompt_service.update_default(
                    s, snap(ADMIN), TASK,
                    {"theme": f"管理员{index}的默认"}, 2,
                )
                ok.append(index)
            except VersionConflict:
                conflicts.append(index)
            finally:
                s.close()

        run(0)
        run(1)
        self.assertEqual(len(ok), 1)
        self.assertEqual(len(conflicts), 1)
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT default_revision FROM prompt_default_versions "
                    "WHERE task_type = :t"
                ),
                {"t": TASK},
            ).fetchall()
        self.assertEqual(sorted(v[0] for v in rows), [1, 2, 3])

    def test_get_does_not_advance_processed_revisions(self):
        session = _session_from_factory()
        try:
            prompt_service.initialize_task(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
        finally:
            session.close()
        new_revision = self._update_default(TASK, "process", "更新了")
        session = _session_from_factory()
        try:
            for _ in range(3):
                view = prompt_service.read_task(
                    session, snap(TEACHER_A), TEACHER_A["id"], TASK
                )
            self.assertTrue(view["pending_default_update"])
        finally:
            session.close()
        with self.engine.begin() as conn:
            seen = conn.execute(
                text(
                    "SELECT last_seen_default_revision FROM "
                    "personal_prompt_heads WHERE account_id = :id AND "
                    "task_type = :t"
                ),
                {"id": TEACHER_A["id"], "t": TASK},
            ).scalar()
        self.assertEqual(seen, 1)


@skip_unless_enabled
class G1RollbackInjectionAndPersistence(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _clear_material()
        cls.addClassCleanup(_clear_material)
        cls.engine = make_engine("kindergarten_test_ai1a_fresh")
        check_environment(cls.engine)

    def setUp(self) -> None:
        _world(self.engine)
        import os as _os

        _set_material(_os.urandom(32), "ai1a-g1-key")
        self.addCleanup(_clear_material)

    def test_injected_event_failure_rolls_back_everything(self):
        original = prompt_service._add_event

        session = _session_from_factory()
        try:
            view = ai_config_service.save_config(
                session, snap(TEACHER_A), 0, "chat_completions_v1",
                "https://api.a.com/v1", "model-1", secret="S",
            )
            self.assertEqual(view.version, 1)
            initialized = prompt_service.initialize_task(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
        finally:
            session.close()

        def broken(*args, **kwargs):
            raise RuntimeError("injected failure")

        prompt_service._add_event = broken
        try:
            session = _session_from_factory()
            try:
                with self.assertRaises(RuntimeError):
                    prompt_service.save_guidance(
                        session, snap(TEACHER_A), TEACHER_A["id"], TASK,
                        {"process": "甲老师的指导"},
                        expected_personal_revision=initialized[
                            "personal_revision"
                        ],
                    )
            finally:
                session.close()
            # 版本行／head／审计／事件全回滚；重连持久。
            with self.engine.begin() as conn:
                versions = conn.execute(
                    text(
                        "SELECT personal_revision FROM "
                        "personal_prompt_versions WHERE account_id = :id"
                    ),
                    {"id": TEACHER_A["id"]},
                ).fetchall()
                heads = conn.execute(
                    text(
                        "SELECT current_personal_revision FROM "
                        "personal_prompt_heads WHERE account_id = :id"
                    ),
                    {"id": TEACHER_A["id"]},
                ).fetchall()
                audits = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM operation_records WHERE "
                        "action = 'prompt_personal_edit'"
                    )
                ).scalar()
            self.assertEqual([v[0] for v in versions], [1])
            self.assertEqual([h[0] for h in heads], [1])
            self.assertEqual(audits, 0)
        finally:
            prompt_service._add_event = original


@skip_unless_enabled
class H1ManualPathRegression(unittest.TestCase):
    """无／错主密钥下手工日／周计划与 Word 导出的定向真实回归。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = make_engine("kindergarten_test_ai1a_fresh")
        check_environment(cls.engine)
        cls.addClassCleanup(_clear_material)

    def setUp(self) -> None:
        _clear_material()
        _world(self.engine)
        self.addCleanup(_clear_material)

    def _run_manual_regression(self) -> tuple[bytes, bytes, int]:
        from app.services import daily_plan_service, word_export_docx
        from app.services import weekly_plan_service
        import app.services.export_read_service as export_read
        import app.services.word_export_mapping as mapping

        plan_date = date(2026, 8, 11)
        session = _session_from_factory()
        try:
            opened = daily_plan_service.create_or_open(
                session, snap(TEACHER_A), plan_date=plan_date, class_id=None
            )
            plan, content, _created = opened
            daily_plan_service.save(
                session, snap(TEACHER_A),
                plan_id=plan.id,
                expected_content_version=1,
                adopted_content=full_day_content(),
            )
            weekly = weekly_plan_service.create_or_open_weekly_plan(
                session, snap(TEACHER_A), term_id="ter_ai1a", week_number=2
            )
            confirmed = weekly_plan_service.confirm_weekly_plan(
                session, snap(TEACHER_A),
                plan_id=weekly.plan.id,
                expected_draft_version=weekly.draft.version,
                acknowledge_missing=True, acknowledge_stale=True,
                note=None, class_id=None,
            )
            confirmed_version = confirmed.confirmed.version
            confirmed_id = confirmed.confirmed.id if hasattr(
                confirmed.confirmed, "id") else f"{weekly.plan.id}"
        finally:
            session.close()
        # 导出（服务层重读，非 API）。
        session = _session_from_factory()
        try:
            bundle = export_read.prepare_daily_export(
                session, class_id="cls_ai1a",
                from_date=plan_date, to_date=plan_date,
                ack_missing=False, expected_context=None,
            )
            if bundle.ack_required:
                bundle = export_read.prepare_daily_export(
                    session, class_id="cls_ai1a",
                    from_date=plan_date, to_date=plan_date,
                    ack_missing=True,
                    expected_context=bundle.expected_context,
                )
            daily_views = [mapping.map_daily_plan(r) for r in bundle.items]
            item = export_read.load_weekly_single(
                session, class_id="cls_ai1a", role=TEACHER_A["role"],
                plan_id=weekly.plan.id, confirmed_version=confirmed_version,
            )
            weekly_views = [mapping.map_weekly_plan(item)]
        finally:
            session.close()
        return (
            word_export_docx.generate_daily_export_docx(daily_views),
            word_export_docx.generate_weekly_export_docx(weekly_views),
            confirmed_version,
        )

    def test_save_and_export_without_master_key(self):
        # 缺失材料：手工链路仍可用，且 AI 不可用状态明确。
        _clear_material()
        self.assertFalse(settings.ai_master_key.get_secret_value())
        daily_bytes, weekly_bytes, _version = self._run_manual_regression()
        self.assertTrue(daily_bytes.startswith(b"PK"))
        self.assertTrue(weekly_bytes.startswith(b"PK"))
        # AI ready 判定在缺材料下为 DECRYPT_UNAVAILABLE。
        session = _session_from_factory()
        try:
            view = ai_config_service.resolve_effective_config(
                session, TEACHER_A["id"]
            )
            self.assertFalse(view.ready)
            self.assertIn(
                view.ready_reason,
                ("DECRYPT_UNAVAILABLE", "NOT_CONFIGURED", "MISSING_SECRET"),
            )
        finally:
            session.close()

    def test_save_and_export_with_broken_master_key(self):
        # 错格式材料：同样不阻断手工链路。
        import os as _os

        _set_material(_os.urandom(31), "ai1a-broken")  # 31 字节 => 无效
        self.assertFalse(self._material_valid())
        daily_bytes, weekly_bytes, version = self._run_manual_regression()
        self.assertTrue(daily_bytes.startswith(b"PK"))
        self.assertTrue(weekly_bytes.startswith(b"PK"))

    @staticmethod
    def _material_valid() -> bool:
        try:
            ai_crypto.load_material()
        except (ai_crypto.KeyMaterialMissing, ai_crypto.KeyMaterialInvalid):
            return False
        return True


@skip_unless_enabled
class I1NullConstraintPaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _clear_material()
        cls.addClassCleanup(_clear_material)
        cls.engine = make_engine("kindergarten_test_ai1a_fresh")
        check_environment(cls.engine)

    def setUp(self) -> None:
        _world(self.engine)

    def _constraint_error(self, sql: str, params: dict) -> str:
        """Run one negative INSERT inside its own connection; returns the
        database error text (constraint name check, R7)。"""
        try:
            conn = self.engine.connect()
            try:
                conn.execute(text(sql), params)
                conn.commit()
            finally:
                conn.close()
        except (IntegrityError, OperationalError) as exc:
            return str(exc)
        raise AssertionError("期望的约束错误没有发生")

    def test_required_columns_and_checks(self):
        """head 缺 current_personal_revision -> NOT NULL 拒绝（先有真实账号）。"""
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO accounts (id, username, password_hash, "
                    "display_name, role, is_active, version, auth_version, "
                    "created_at, updated_at) VALUES "
                    "('nacc', 'nacc', 'x', 'x', 'teacher', 1, 1, 1, NOW(), NOW())"
                )
            )
        err = None
        try:
            err = self._constraint_error(
                "INSERT INTO personal_prompt_heads (account_id, task_type, "
                "current_personal_revision, adaptation_state, "
                "required_contract_version, created_at, updated_at) VALUES "
                "('nacc', :t, NULL, 'current', NULL, NOW(), NOW())",
                {"t": TASK},
            )
        except AssertionError:
            self.fail("违反 NOT NULL 未被拒绝")
        self.assertIn("current_personal_revision", err)

    def test_b_adapt_required_null_reference_check(self):
        """S5: 对已有合法 head 进行 UPDATE，只破坏
        adaptation_state/required_contract_version 关系 -> MySQL 3819 +
        ck_pph_adapt_ref；失败后原行不变（不再以重复主键 INSERT
        混杂 FK 冒充目标 CHECK）。"""
        session = _session_from_factory()
        try:
            prompt_service.initialize_task(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
        finally:
            session.close()
        with self.engine.begin() as conn:
            before = conn.execute(
                text(
                    "SELECT current_personal_revision, adaptation_state, "
                    "required_contract_version FROM personal_prompt_heads "
                    "WHERE account_id = :a AND task_type = :t"
                ),
                {"a": TEACHER_A["id"], "t": TASK},
            ).fetchone()
        err = None
        try:
            try:
                with self.engine.begin() as conn:
                    conn.execute(
                        text(
                            "UPDATE personal_prompt_heads SET "
                            "adaptation_state = 'adaptation_required', "
                            "required_contract_version = NULL WHERE "
                            "account_id = :a AND task_type = :t"
                        ),
                        {"a": TEACHER_A["id"], "t": TASK},
                    )
            except (IntegrityError, OperationalError) as exc:
                err = exc
            self.assertIsNotNone(err, "目标 CHECK 必须拒绝该 UPDATE")
            self.assertIn("3819", str(err))
            self.assertIn("ck_pph_adapt_ref", str(err))
        finally:
            with self.engine.begin() as conn:
                after = conn.execute(
                    text(
                        "SELECT current_personal_revision, "
                        "adaptation_state, required_contract_version "
                        "FROM personal_prompt_heads WHERE account_id = :a "
                        "AND task_type = :t"
                    ),
                    {"a": TEACHER_A["id"], "t": TASK},
                ).fetchone()
        self.assertEqual(
            (after[0], after[1], after[2]),
            (before[0], before[1], before[2]),
            "失败后原行必须保持不变",
        )

    def test_c_config_cipher_without_key_id(self):
        # 建有效账号＋审计行（其余 FK／NOT NULL 全满足）后，
        # 单独违反 ck_ai_config_versions_secret_key。
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO accounts (id, username, password_hash, "
                    "display_name, role, is_active, version, auth_version, "
                    "created_at, updated_at) VALUES "
                    "('xacc', 'xacc', 'x', 'x', 'teacher', 1, 1, 1, NOW(), NOW())"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO operation_records (id, operator_id, "
                    "operator_type, action, target_type, target_id, "
                    "target_version_after, target_account_id, "
                    "account_version_after, created_at) VALUES "
                    "('oprc_ai1c', NULL, 'server_operator', 'fixture', "
                    "'account', 'xacc', 1, 'xacc', 1, NOW())"
                )
            )
        err = self._constraint_error(
            "INSERT INTO ai_config_versions (id, account_id, version, "
            "protocol_id, base_url, model, secret_ciphertext, key_id, "
            "operation_record_id, created_by, created_at) VALUES "
            "('xv1c', 'xacc', 1, 'chat_completions_v1', "
            "'https://a.b/v1', 'm', 'CIPHER', NULL, 'oprc_ai1c', 'xacc', "
            "NOW())",
            {},
        )
        self.assertIn("3819", str(err))
        self.assertIn("ck_ai_config_versions_secret_key", str(err))
        # 失败后无残留行。
        with self.engine.begin() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM ai_config_versions WHERE id = 'xv1c'")
            ).scalar()
        self.assertEqual(count, 0)


@skip_unless_enabled
class J1ReadinessCertifiesCiphertext(unittest.TestCase):
    """R3 真实行：ready 认证当前密文（而非仅检查 key material 形态）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = make_engine("kindergarten_test_ai1a_fresh")
        check_environment(cls.engine)
        cls.addClassCleanup(_clear_material)

    def setUp(self) -> None:
        _world(self.engine)
        import os as _os

        self.key = _os.urandom(32)
        _set_material(self.key, "ai1a-j1-key")
        self.addCleanup(_clear_material)

    def _saved(self, session):
        return ai_config_service.save_config(
            session, snap(TEACHER_A), 0, "chat_completions_v1",
            "https://api.a.com/v1", "model-1", secret="SECRET-AB",
        )

    def test_valid_config_ready_and_view_clean(self):
        session = _session_from_factory()
        try:
            view = self._saved(session)
            self.assertTrue(view.ready)
            self.assertIsNone(view.ready_reason)
            self.assertTrue(view.has_secret)
        finally:
            session.close()
        self.assertNotIn("SECRET-AB", str(view))

    def test_tampered_ciphertext_ready_false_no_head_change(self):
        session = _session_from_factory()
        try:
            self._saved(session)
        finally:
            session.close()
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT secret_ciphertext FROM ai_config_versions "
                    "WHERE account_id = :a AND version = 1"
                ),
                {"a": TEACHER_A["id"]},
            ).fetchone()
            blob = bytearray(base64.b64decode(row[0]))
            blob[15] ^= 0x5A
            conn.execute(
                text(
                    "UPDATE ai_config_versions SET secret_ciphertext = :c "
                    "WHERE account_id = :a AND version = 1"
                ),
                {"c": base64.b64encode(bytes(blob)).decode(),
                 "a": TEACHER_A["id"]},
            )
        session = _session_from_factory()
        try:
            view = ai_config_service.resolve_effective_config(
                session, TEACHER_A["id"]
            )
            self.assertFalse(view.ready)
            self.assertEqual(view.ready_reason, "DECRYPT_UNAVAILABLE")
            self.assertTrue(view.has_secret)
            self.assertEqual(view.version, 1)  # head 未被失败改写
        finally:
            session.close()

    def test_wrong_master_key_ready_false(self):
        session = _session_from_factory()
        try:
            self._saved(session)
        finally:
            session.close()
        import os as _os

        _set_material(_os.urandom(32), "ai1a-j1-key")  # 不同主密钥
        session = _session_from_factory()
        try:
            view = ai_config_service.resolve_effective_config(
                session, TEACHER_A["id"]
            )
            self.assertFalse(view.ready)
            self.assertEqual(view.ready_reason, "DECRYPT_UNAVAILABLE")
        finally:
            session.close()
        _set_material(self.key, "ai1a-j1-key")
        session = _session_from_factory()
        try:
            view = ai_config_service.resolve_effective_config(
                session, TEACHER_A["id"]
            )
            self.assertTrue(view.ready)
        finally:
            session.close()

    def test_key_id_mismatch_ready_false(self):
        session = _session_from_factory()
        try:
            self._saved(session)
        finally:
            session.close()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE ai_config_versions SET key_id = 'alien-id' "
                    "WHERE account_id = :a AND version = 1"
                ),
                {"a": TEACHER_A["id"]},
            )
        session = _session_from_factory()
        try:
            view = ai_config_service.resolve_effective_config(
                session, TEACHER_A["id"]
            )
            self.assertFalse(view.ready)
            self.assertEqual(view.ready_reason, "DECRYPT_UNAVAILABLE")
        finally:
            session.close()

    def test_missing_material_ready_false_and_clear_still_works(self):
        session = _session_from_factory()
        try:
            self._saved(session)
        finally:
            session.close()
        _clear_material()
        session = _session_from_factory()
        try:
            view = ai_config_service.resolve_effective_config(
                session, TEACHER_A["id"]
            )
            self.assertFalse(view.ready)
            self.assertEqual(view.ready_reason, "DECRYPT_UNAVAILABLE")
            # 无密钥材料下清除仍然成功（新“未配置”版本）。
            cleared = ai_config_service.clear_secret(
                session, snap(TEACHER_A), 1
            )
            self.assertEqual(cleared.version, 2)
            self.assertFalse(cleared.has_secret)
            self.assertEqual(cleared.ready_reason, "MISSING_SECRET")
        finally:
            session.close()




@skip_unless_enabled
class K1StaleSnapshotWritePaths(unittest.TestCase):
    """S3（重做）：旧 REPEATABLE READ 快照保持同一事务并直接以正确新
    expected 调写入口；写入口之前不得中途 commit／rollback／关闭 Session。
    成功路径与旧 expected 冲突路径分别建立独立 Session／快照（K2）。"""

    @classmethod
    def setUpClass(cls) -> None:
        _clear_material()
        cls.addClassCleanup(_clear_material)
        cls.engine = make_engine("kindergarten_test_ai1a_fresh")
        check_environment(cls.engine)

    def setUp(self) -> None:
        _world(self.engine)
        import os as _os

        _set_material(_os.urandom(32), "ai1a-k1-key")
        self.addCleanup(_clear_material)

    @staticmethod
    def _plain_version(session: Session, account_id: str) -> int:
        return session.execute(
            text(
                "SELECT COALESCE(MAX(version), 0) FROM ai_config_versions "
                "WHERE account_id = :a"
            ),
            {"a": account_id},
        ).scalar()

    @staticmethod
    def _plain_revision(session: Session, account_id: str) -> int:
        return session.execute(
            text(
                "SELECT COALESCE(MAX(personal_revision), 0) FROM "
                "personal_prompt_versions WHERE account_id = :a AND "
                "task_type = :t"
            ),
            {"a": account_id, "t": TASK},
        ).scalar()

    @staticmethod
    def _plain_default_revision(db: Session) -> int:
        return db.execute(
            text(
                "SELECT COALESCE(MAX(default_revision), 0) FROM "
                "prompt_default_versions WHERE task_type = :t"
            ),
            {"t": TASK},
        ).scalar()

    def _cipher(self, account_id: str, version: int):
        with self.engine.begin() as conn:
            return conn.execute(
                text(
                    "SELECT secret_ciphertext FROM ai_config_versions "
                    "WHERE account_id = :a AND version = :v"
                ),
                {"a": account_id, "v": version},
            ).scalar()

    def _counts(self) -> dict:
        with self.engine.begin() as conn:
            out = {}
            for name, sql in (
                ("events", "SELECT COUNT(*) FROM prompt_change_records"),
                ("personal_versions",
                 "SELECT COUNT(*) FROM personal_prompt_versions"),
                ("config_versions", "SELECT COUNT(*) FROM ai_config_versions"),
                ("heads", "SELECT COUNT(*) FROM ai_config_heads"),
            ):
                out[name] = conn.execute(text(sql)).scalar()
            return out

    def _account_version(self, account_id: str) -> int:
        with self.engine.begin() as conn:
            return conn.execute(
                text("SELECT version FROM accounts WHERE id = :a"),
                {"a": account_id},
            ).scalar()

    def _op_by_action(self, action: str) -> int:
        with self.engine.begin() as conn:
            return conn.execute(
                text(
                    "SELECT COUNT(*) FROM operation_records WHERE action = :a"
                ),
                {"a": action},
            ).scalar()

    def test_a_config_keep_secret_stale_snapshot_success(self):
        winner = _session_from_factory()
        try:
            ai_config_service.save_config(
                winner, snap(TEACHER_A), 0, "chat_completions_v1",
                "https://api.a.com/v1", "m", secret="REDACTED-V1",
            )
        finally:
            winner.close()
        v1_cipher_before = self._cipher(TEACHER_A["id"], 1)

        stale = _session_from_factory()
        try:
            old_version = self._plain_version(stale, TEACHER_A["id"])
            self.assertEqual(old_version, 1)
            mover = _session_from_factory()
            try:
                ai_config_service.save_config(
                    mover, snap(TEACHER_A), 1, "chat_completions_v1",
                    "https://api.a.com/v2", "m", secret="REDACTED-V2",
                )
            finally:
                mover.close()
            # 旧快照普通读仍见旧数据，且事务未结束（S3 核心断言）。
            self.assertEqual(
                self._plain_version(stale, TEACHER_A["id"]), 1
            )
            self.assertTrue(stale.in_transaction())
            # 直接以正确新 expected 写：同事务、无任何中间 commit/rollback。
            result = ai_config_service.save_config(
                stale, snap(TEACHER_A), 2, "chat_completions_v1",
                "https://api.a.com/v3", "m2",
            )
            self.assertEqual(result.version, 3)
            self.assertTrue(result.has_secret)
        finally:
            stale.close()

        fresh = _session_from_factory()
        try:
            view = ai_config_service.resolve_effective_config(fresh, TEACHER_A["id"])
            self.assertEqual(view.version, 3)
            self.assertTrue(view.ready)
            # 保留语义：新版本 v3 的明文来自 mover 的 v2（重加密）。
            self.assertEqual(
                ai_config_service.read_pinned_config(
                    fresh, TEACHER_A["id"], 3
                ).reveal_secret(),
                "REDACTED-V2",
            )
            self.assertEqual(
                ai_config_service.read_pinned_config(
                    fresh, TEACHER_A["id"], 2
                ).reveal_secret(),
                "REDACTED-V2",
            )
            self.assertEqual(
                ai_config_service.read_pinned_config(
                    fresh, TEACHER_A["id"], 1
                ).reveal_secret(),
                "REDACTED-V1",
            )
        finally:
            fresh.close()
        with self.engine.begin() as conn:
            head = conn.execute(
                text(
                    "SELECT config_version FROM ai_config_heads "
                    "WHERE account_id = :a"
                ),
                {"a": TEACHER_A["id"]},
            ).scalar()
            versions = conn.execute(
                text(
                    "SELECT COUNT(*) FROM ai_config_versions "
                    "WHERE account_id = :a"
                ),
                {"a": TEACHER_A["id"]},
            ).scalar()
            audits = conn.execute(
                text(
                    "SELECT COUNT(*) FROM operation_records WHERE "
                    "action = 'ai_config_save' AND target_id = :a"
                ),
                {"a": TEACHER_A["id"]},
            ).scalar()
        self.assertEqual(head, 3)
        self.assertEqual(versions, 3)
        self.assertEqual(audits, 3)  # 首建＋mover 保留＋stale 保留
        # 旧行字节不变（升级→轮换场景保证）。
        self.assertEqual(self._cipher(TEACHER_A["id"], 1), v1_cipher_before)

    def test_b_config_clear_stale_snapshot_success(self):
        winner = _session_from_factory()
        try:
            ai_config_service.save_config(
                winner, snap(TEACHER_A), 0, "chat_completions_v1",
                "https://api.a.com/v1", "m", secret="REDACTED-C1",
            )
        finally:
            winner.close()
        stale = _session_from_factory()
        try:
            self.assertEqual(self._plain_version(stale, TEACHER_A["id"]), 1)
            mover = _session_from_factory()
            try:
                ai_config_service.save_config(
                    mover, snap(TEACHER_A), 1, "chat_completions_v1",
                    "https://api.a.com/v2", "m", secret="REDACTED-C2",
                )
            finally:
                mover.close()
            self.assertEqual(
                self._plain_version(stale, TEACHER_A["id"]), 1
            )
            self.assertTrue(stale.in_transaction())
            cleared = ai_config_service.clear_secret(stale, snap(TEACHER_A), 2)
            self.assertEqual(cleared.version, 3)
            self.assertFalse(cleared.has_secret)
        finally:
            stale.close()

        with self.engine.begin() as conn:
            head = conn.execute(
                text(
                    "SELECT config_version FROM ai_config_heads "
                    "WHERE account_id = :a"
                ),
                {"a": TEACHER_A["id"]},
            ).scalar()
            cleared = conn.execute(
                text(
                    "SELECT secret_ciphertext, key_id FROM ai_config_versions "
                    "WHERE account_id = :a AND version = 3"
                ),
                {"a": TEACHER_A["id"]},
            ).fetchone()
            kept = conn.execute(
                text(
                    "SELECT secret_ciphertext FROM ai_config_versions "
                    "WHERE account_id = :a AND version = 2"
                ),
                {"a": TEACHER_A["id"]},
            ).scalar()
        self.assertEqual(head, 3)
        self.assertIsNone(cleared[0])
        self.assertIsNone(cleared[1])
        self.assertIsNotNone(kept)  # v2 密文字节保持
        self.assertEqual(self._op_by_action("ai_config_secret_clear"), 1)
        self.assertEqual(self._op_by_action("ai_config_save"), 2)

    def test_c_personal_edit_stale_snapshot_success(self):
        winner = _session_from_factory()
        try:
            prompt_service.initialize_task(
                winner, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
        finally:
            winner.close()
        stale = _session_from_factory()
        try:
            self.assertEqual(
                self._plain_revision(stale, TEACHER_A["id"]), 1
            )
            mover = _session_from_factory()
            try:
                prompt_service.save_guidance(
                    mover, snap(TEACHER_A), TEACHER_A["id"], TASK,
                    {"process": "另一窗口已经改过的过程"}, 1,
                )
            finally:
                mover.close()
            self.assertEqual(
                self._plain_revision(stale, TEACHER_A["id"]), 1
            )
            self.assertTrue(stale.in_transaction())
            result = prompt_service.save_guidance(
                stale, snap(TEACHER_A), TEACHER_A["id"], TASK,
                {"theme": "旧窗口最终编辑的主题"}, 2,
            )
            self.assertEqual(result["personal_revision"], 3)
        finally:
            stale.close()

        fresh = _session_from_factory()
        try:
            view = prompt_service.read_task(
                fresh, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
            self.assertEqual(view["personal_revision"], 3)
            self.assertEqual(
                view["guidance_map"]["theme"], "旧窗口最终编辑的主题"
            )
            self.assertEqual(
                view["guidance_map"]["process"], "另一窗口已经改过的过程"
            )
        finally:
            fresh.close()
        with self.engine.begin() as conn:
            head = conn.execute(
                text(
                    "SELECT current_personal_revision FROM "
                    "personal_prompt_heads WHERE account_id = :a AND "
                    "task_type = :t"
                ),
                {"a": TEACHER_A["id"], "t": TASK},
            ).scalar()
            edits = conn.execute(
                text(
                    "SELECT COUNT(*) FROM prompt_change_records WHERE "
                    "event_kind = 'personal_edit' AND task_type = :t"
                ),
                {"t": TASK},
            ).scalar()
            audits = conn.execute(
                text(
                    "SELECT COUNT(*) FROM operation_records WHERE "
                    "action = 'prompt_personal_edit'"
                )
            ).scalar()
        self.assertEqual(head, 3)
        self.assertEqual(edits, 2)
        self.assertEqual(audits, 2)
        self.assertEqual(self._account_version(TEACHER_A["id"]), 1)

    def test_d_personal_accept_stale_snapshot_success(self):
        publisher = _session_from_factory()
        try:
            r2 = prompt_service.update_default(
                publisher, snap(ADMIN), TASK, {"process": "系统默认 r2"}, 1
            )
        finally:
            publisher.close()
        starter = _session_from_factory()
        try:
            prompt_service.initialize_task(
                starter, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
        finally:
            starter.close()
        stale = _session_from_factory()
        try:
            self.assertEqual(
                self._plain_revision(stale, TEACHER_A["id"]), 1
            )
            mover = _session_from_factory()
            try:
                prompt_service.save_guidance(
                    mover, snap(TEACHER_A), TEACHER_A["id"], TASK,
                    {"key_points": "另一窗口改过的重点"}, 1,
                )
            finally:
                mover.close()
            self.assertEqual(
                self._plain_revision(stale, TEACHER_A["id"]), 1
            )
            self.assertTrue(stale.in_transaction())
            result = prompt_service.accept_default(
                stale, snap(TEACHER_A), TEACHER_A["id"], TASK,
                r2["default_revision"], ["process"], 2,
            )
            self.assertEqual(result["personal_revision"], 3)
            self.assertEqual(result["accepted_default_revision"], 2)
        finally:
            stale.close()

        fresh = _session_from_factory()
        try:
            view = prompt_service.read_task(
                fresh, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
            self.assertEqual(
                view["guidance_map"]["process"], "系统默认 r2"
            )  # 只替换选定字段
            self.assertEqual(
                view["guidance_map"]["key_points"], "另一窗口改过的重点"
            )  # 未选字段保持
            self.assertEqual(view["accepted_default_revision"], 2)
            self.assertEqual(view["personal_revision"], 3)
        finally:
            fresh.close()
        with self.engine.begin() as conn:
            accepts = conn.execute(
                text(
                    "SELECT COUNT(*) FROM prompt_change_records WHERE "
                    "event_kind = 'accept_default' AND task_type = :t"
                ),
                {"t": TASK},
            ).scalar()
        self.assertEqual(accepts, 1)
        self.assertEqual(self._account_version(TEACHER_A["id"]), 1)

    def test_e_admin_default_publish_stale_snapshot_success(self):
        stale = _session_from_factory()
        try:
            self.assertEqual(self._plain_default_revision(stale), 1)
            mover = _session_from_factory()
            try:
                r2 = prompt_service.update_default(
                    mover, snap(ADMIN), TASK, {"process": "另一管理员r2"}, 1
                )
            finally:
                mover.close()
            self.assertEqual(self._plain_default_revision(stale), 1)
            self.assertTrue(stale.in_transaction())
            result = prompt_service.update_default(
                stale, snap(ADMIN), TASK, {"theme": "旧窗口发布的新默认"},
                r2["default_revision"],
            )
            self.assertEqual(
                result["default_revision"], r2["default_revision"] + 1
            )
        finally:
            stale.close()

        fresh = _session_from_factory()
        try:
            view = prompt_service.read_task(
                fresh, snap(ADMIN), ADMIN["id"], TASK
            )
            self.assertEqual(view["latest_default_revision"], 3)
        finally:
            fresh.close()
        with self.engine.begin() as conn:
            merged = conn.execute(
                text(
                    "SELECT guidance_map FROM prompt_default_versions "
                    "WHERE task_type = :t ORDER BY default_revision DESC "
                    "LIMIT 1"
                ),
                {"t": TASK},
            ).scalar()
            school_audits = conn.execute(
                text(
                    "SELECT target_version_after FROM operation_records "
                    "WHERE action = 'prompt_default_update' ORDER BY "
                    "created_at DESC, id DESC LIMIT 1"
                )
            ).scalar()
            self._mods = None
        self.assertEqual(
            json.loads(merged).get("process"), "另一管理员r2"
        )  # 未选字段保持
        self.assertIsNone(school_audits)  # PF-1: school 目标版本 NULL
        self.assertEqual(self._account_version(ADMIN["id"]), 1)


@skip_unless_enabled
class K2StaleSnapshotConflicts(unittest.TestCase):
    """S3: 旧 expected 冲突路径独立建 Session／快照，不影响成功路径。"""

    @classmethod
    def setUpClass(cls) -> None:
        _clear_material()
        cls.addClassCleanup(_clear_material)
        cls.engine = make_engine("kindergarten_test_ai1a_fresh")
        check_environment(cls.engine)

    def setUp(self) -> None:
        _world(self.engine)
        import os as _os

        _set_material(_os.urandom(32), "ai1a-k2-key")
        self.addCleanup(_clear_material)

    def test_config_keep_old_expected_conflict(self):
        winner = _session_from_factory()
        try:
            ai_config_service.save_config(
                winner, snap(TEACHER_A), 0, "chat_completions_v1",
                "https://api.a.com/v1", "m", secret="REDACTED-K2V1",
            )
        finally:
            winner.close()
        stale = _session_from_factory()
        try:
            self.assertEqual(
                stale.execute(
                    text(
                        "SELECT MAX(version) FROM ai_config_versions "
                        "WHERE account_id = :a"
                    ),
                    {"a": TEACHER_A["id"]},
                ).scalar(),
                1,
            )
            mover = _session_from_factory()
            try:
                ai_config_service.save_config(
                    mover, snap(TEACHER_A), 1, "chat_completions_v1",
                    "https://api.a.com/v2", "m", secret="REDACTED-K2V2",
                )
            finally:
                mover.close()
            from app.services.auth_service import VersionConflict

            with self.assertRaises(VersionConflict):
                ai_config_service.save_config(
                    stale, snap(TEACHER_A), 1, "chat_completions_v1",
                    "https://api.a.com/v9", "m9",
                )
            # 冲突后无新版本（回滚完整），head 保持 v2。
            with self.engine.begin() as conn:
                count = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM ai_config_versions "
                        "WHERE account_id = :a"
                    ),
                    {"a": TEACHER_A["id"]},
                ).scalar()
            self.assertEqual(count, 2)
        finally:
            stale.close()

    def test_personal_edit_old_expected_conflict(self):
        winner = _session_from_factory()
        try:
            prompt_service.initialize_task(
                winner, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
        finally:
            winner.close()
        stale = _session_from_factory()
        try:
            stale.execute(
                text(
                    "SELECT current_personal_revision FROM "
                    "personal_prompt_heads WHERE account_id = :a AND "
                    "task_type = :t"
                ),
                {"a": TEACHER_A["id"], "t": TASK},
            ).fetchone()
            mover = _session_from_factory()
            try:
                prompt_service.save_guidance(
                    mover, snap(TEACHER_A), TEACHER_A["id"], TASK,
                    {"process": "另一窗口先改"}, 1,
                )
            finally:
                mover.close()
            from app.services.auth_service import VersionConflict

            with self.assertRaises(VersionConflict):
                prompt_service.save_guidance(
                    stale, snap(TEACHER_A), TEACHER_A["id"], TASK,
                    {"process": "过期窗口写不进去"}, 1,
                )
            with self.engine.begin() as conn:
                count = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM personal_prompt_versions "
                        "WHERE account_id = :a AND task_type = :t"
                    ),
                    {"a": TEACHER_A["id"], "t": TASK},
                ).scalar()
            self.assertEqual(count, 2)  # init + mover
        finally:
            stale.close()

    def test_admin_publish_old_expected_conflict(self):
        stale = _session_from_factory()
        try:
            stale.execute(
                text(
                    "SELECT MAX(default_revision) FROM "
                    "prompt_default_versions WHERE task_type = :t"
                ),
                {"t": TASK},
            ).fetchone()
            mover = _session_from_factory()
            try:
                prompt_service.update_default(
                    mover, snap(ADMIN), TASK, {"process": "r2"}, 1
                )
            finally:
                mover.close()
            from app.services.auth_service import VersionConflict

            with self.assertRaises(VersionConflict):
                prompt_service.update_default(
                    stale, snap(ADMIN), TASK, {"theme": "过期"}, 1
                )
            with self.engine.begin() as conn:
                count = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM prompt_default_versions "
                        "WHERE task_type = :t"
                    ),
                    {"t": TASK},
                ).scalar()
            self.assertEqual(count, 2)  # 种子 r1 + mover r2
        finally:
            stale.close()



@skip_unless_enabled
class L1RealTaskListTraversal(unittest.TestCase):
    """S4: 真库直接调用 list_tasks——七类状态、本人隔离、GET 无副作用。"""

    @classmethod
    def setUpClass(cls) -> None:
        _clear_material()
        cls.addClassCleanup(_clear_material)
        cls.engine = make_engine("kindergarten_test_ai1a_fresh")
        check_environment(cls.engine)

    def setUp(self) -> None:
        _world(self.engine)

    def _counts(self) -> dict:
        with self.engine.begin() as conn:
            out = {}
            for name, sql in (
                ("events", "SELECT COUNT(*) FROM prompt_change_records"),
                ("ops", "SELECT COUNT(*) FROM operation_records"),
                ("personal_versions",
                 "SELECT COUNT(*) FROM personal_prompt_versions"),
                ("heads", "SELECT COUNT(*) FROM personal_prompt_heads"),
            ):
                out[name] = conn.execute(text(sql)).scalar()
            return out

    def test_a_list_tasks_seven_tasks_and_get_no_side_effects(self):
        session = _session_from_factory()
        try:
            statuses = prompt_service.list_tasks(
                session, snap(TEACHER_A), TEACHER_A["id"]
            )
            self.assertEqual(
                [s.task_type for s in statuses],
                list(prompt_service.get_task_types()),
            )
            self.assertEqual(len(statuses), 7)
            self.assertTrue(all(not s.initialized for s in statuses))
            before = self._counts()
            # GET 两次：版本／head／事件／审计均不变（GET 不推进）。
            for _ in range(2):
                again = prompt_service.list_tasks(
                    session, snap(TEACHER_A), TEACHER_A["id"]
                )
            self.assertEqual([s.task_type for s in again],
                             [s.task_type for s in statuses])
            self.assertEqual(before, self._counts())

            # 初始化一个任务 → 该任务状态改变，其余六类仍未初始化。
            prompt_service.initialize_task(
                session, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
            after_init = prompt_service.list_tasks(
                session, snap(TEACHER_A), TEACHER_A["id"]
            )
            for status in after_init:
                if status.task_type == TASK:
                    self.assertTrue(status.initialized)
                else:
                    self.assertFalse(status.initialized)
            after_init_counts = self._counts()
            self.assertEqual(after_init_counts["heads"],
                             before["heads"] + 1)
            # 发布 v2（另一连接）；另开新 Session 读取（避免把上个事务的
            # 旧快照误会成服务缺陷——读事务未被提交前保持快照是 RR 语义）。
            publish_variant_contract(self.engine, TASK, VARIANT_FIELD_V2)
            reader = _session_from_factory()
            try:
                final = prompt_service.list_tasks(
                    reader, snap(TEACHER_A), TEACHER_A["id"]
                )
                for status in final:
                    if status.task_type == TASK:
                        self.assertEqual(
                            status.adaptation_state,
                            prompt_service.STATE_ADAPTATION_REQUIRED,
                        )
                        self.assertEqual(status.required_contract_version, 2)
                        self.assertTrue(status.pending_default_update)
                    else:
                        self.assertFalse(status.initialized)
                        self.assertEqual(
                            status.adaptation_state,
                            prompt_service.STATE_CURRENT,
                        )
            finally:
                reader.close()
            # 纯读不写库：读取前后事件／审计仍不增加。
            self.assertEqual(after_init_counts["events"],
                             self._counts()["events"])
        finally:
            session.close()

    def test_b_list_tasks_isolation_forbidden(self):
        from app.services.auth_service import Forbidden

        session = _session_from_factory()
        try:
            with self.assertRaises(Forbidden):
                prompt_service.list_tasks(
                    session, snap(TEACHER_B), TEACHER_A["id"]
                )
        finally:
            session.close()

    def test_c_read_task_does_not_advance_last_seen(self):
        starter = _session_from_factory()
        try:
            prompt_service.initialize_task(
                starter, snap(TEACHER_A), TEACHER_A["id"], TASK
            )
        finally:
            starter.close()
        publisher = _session_from_factory()
        try:
            prompt_service.update_default(
                publisher, snap(ADMIN), TASK, {"process": "r2"}, 1
            )
        finally:
            publisher.close()
        session = _session_from_factory()
        try:
            for _ in range(3):
                view = prompt_service.read_task(
                    session, snap(TEACHER_A), TEACHER_A["id"], TASK
                )
                self.assertTrue(view["pending_default_update"])
            with self.engine.begin() as conn:
                seen = conn.execute(
                    text(
                        "SELECT last_seen_default_revision FROM "
                        "personal_prompt_heads WHERE account_id = :a "
                        "AND task_type = :t"
                    ),
                    {"a": TEACHER_A["id"], "t": TASK},
                ).scalar()
            self.assertEqual(seen, 1)
        finally:
            session.close()

if __name__ == "__main__":
    unittest.main()
