"""独立集成 guard：AI 1C 夹具真库测试（2026-10-07；同日补修）。

严格隔离规则（对齐 ``ai-slice1c-fixture-plan-2026-10-07.md`` §4 与
``ai-slice1c-fixture-tool-review-2026-10-07.md``）：

* 仅当同时设置 ``AI1C_TEST_ALLOW_PREPARE=yes`` 与
  ``AI1C_TEST_DATABASE_URL``，且 URL 指向 127.0.0.1/localhost、
  mysql+pymysql、专用端口 13387、精确库
  ``kindergarten_test_ai1c_fixture`` 时启用。
* 本 switch 与 I2/I3/I4/I5／AI1A／AI1C 发布开关完全独立；其他 schema
  （包括远程验收库）在任何连接与迁移之前被拒绝。
* 强制 ``APP_DISABLE_DOTENV=1`` 且在模块加载前清除继承的
  DATABASE_URL／AI_MASTER_KEY／AI_MASTER_KEY_ID。
* 目标保护复用 ``backend/scripts/ai1c_acceptance_fixture.py`` 的
  ``validate_target_url``（同 13387 精确库白名单）；此外本 guard 允许
  对一次性测试库执行 alembic 与测试数据恢复（仅该精确库）。

补修要点（本文件范围）：
* ``seed_v1_world``：所有连接使用 ``with ... begin()/connect()`` 上下文
  显式关闭；v1 个人种子为完整六字段合成个人 map（不再是只有 theme 的
  不合法单字段 map）；额外种下合法管理员账号＋有效会话（供真实
  ``prompt_service.update_default`` 竞争测试使用）、school_settings 单行
  以及一条合成 operation_record＋prompt_change_record（作为"合成业务
  记录"不变式证据）。
* ``world_state``：发布前后规范化快照（JSON 正确解码、数组保序、map
  无序比较），覆盖个人完整文字／head 保护列、accounts、sessions、
  school_settings、operation_records、prompt_change_records、
  daily_lesson_split 契约与默认全文、其他任务行。
* 第二轮集中补修（ai-slice1c-fixture-repair2-opencode-prompt-2026-10-07.md）：
  * S1 ``make_engine`` 正确导入 ``create_engine``（此前是调用时
    NameError）；接入前仍先经 ``validate_target_url`` 拒绝非法目标。
  * S2 种子统一使用 ``TEACHER_ACCOUNT``，不再引用未定义的
    ``FIXTURE_TEACHER_ID``。
  * S3 ``world_state`` 用 ``session.scalars(...).one_or_none()`` 提取
    SchoolSettings ORM 实体，不再把包装的 Row 当实体读取属性。
  * S4/S5 断言语义改为纯函数：保护状态（个人／head／accounts／
    sessions／school／其他任务）与审计（operation_records／
    prompt_change_records）分开断言；工具发布成功不写审计，真实管理员
    发布成功合法追加且仅追加审计。这些纯函数同时被离线检查（SQLite
    内存离线单元证据）与真库集成测试调用。
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

os.environ["APP_DISABLE_DOTENV"] = "1"
for _leaked in ("DATABASE_URL", "AI_MASTER_KEY", "AI_MASTER_KEY_ID"):
    os.environ.pop(_leaked, None)

# I2 13384, I3 13385, I5 13386; AI1A 与 AI1C 一次性集成库共用 13387。
ALLOWED_PORT = 13387
PREPARE_SWITCH = "AI1C_TEST_ALLOW_PREPARE"
DSN_ENV_VAR = "AI1C_TEST_DATABASE_URL"

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "scripts"))

import ai1c_acceptance_fixture as fixture_tool  # noqa: E402
from sqlalchemy import create_engine, insert, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

import app.security  # noqa: E402
from app.models import (  # noqa: E402
    Account,
    AccountSession,
    OperationRecord,
    PersonalPromptHead,
    PersonalPromptVersion,
    PromptChangeRecord,
    PromptContractVersion,
    PromptDefaultVersion,
    SchoolSettings,
)
from app.services import ai_prompt_registry  # noqa: E402
from app.services.auth_service import utc_now  # noqa: E402

_DATABASE_URL = os.environ.get(DSN_ENV_VAR)


def _database_name(url: str | None) -> str | None:
    if not url:
        return None
    return urlsplit(url).path.lstrip("/") or None


def _enabled() -> bool:
    if os.environ.get(PREPARE_SWITCH) != "yes":
        return False
    if not _DATABASE_URL:
        return False
    return True


def require_authorized_url(raw_url: str) -> None:
    """Guard 每个外部传入 URL（含 alembic 子进程 env）。"""
    # 复用运维工具的同一套白名单校验（integration 模式 = 13387 精确库）。
    fixture_tool.validate_target_url("integration", raw_url)


def validate_environment() -> str:
    """Validate/disable integration mode; return the db url (or '')."""
    if not _enabled():
        return ""
    try:
        require_authorized_url(_DATABASE_URL)
    except fixture_tool.FixtureGuardError as error:
        raise RuntimeError(
            f"AI 1C fixture integration guard: {error}"
        ) from None
    return _DATABASE_URL


INTEGRATION_URL = validate_environment()
INTEGRATION_ENABLED = bool(INTEGRATION_URL)


def skip_unless_enabled(cls):
    return unittest.skipUnless(
        INTEGRATION_ENABLED,
        "AI 1C fixture integration tests disabled; set "
        "AI1C_TEST_ALLOW_PREPARE=yes and AI1C_TEST_DATABASE_URL to the "
        "dedicated one-shot MySQL on port 13387.",
    )(cls)


def venv_python() -> str:
    """backend/.venv 解释器；缺失时退回当前解释器。"""
    candidate = BACKEND_ROOT / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def make_engine():
    """guard 通过后创建一次性集成库 engine（S1：符号已正确导入）。

    非白名单目标在 ``validate_target_url`` 中被拒绝，永远到不了
    ``create_engine`` 调用（离线替身检查覆盖该顺序）。
    """
    require_authorized_url(_DATABASE_URL)
    return create_engine(
        _DATABASE_URL,
        poolclass=NullPool,
        future=True,
        isolation_level="REPEATABLE READ",
    )


def authorized_migration_env() -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("DATABASE_URL", "AI_MASTER_KEY", "AI_MASTER_KEY_ID")
    }
    env["APP_DISABLE_DOTENV"] = "1"
    env["DATABASE_URL"] = _DATABASE_URL
    return env


def run_alembic(args: list[str]) -> None:
    require_authorized_url(_DATABASE_URL)
    completed = subprocess.run(
        [venv_python(), "-m", "alembic", *args],
        cwd=str(BACKEND_ROOT),
        env=authorized_migration_env(),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "alembic subprocess refused (db="
            + str(_database_name(_DATABASE_URL))
            + ", exit=" + str(completed.returncode) + ")"
        )


def ensure_migration_head(engine) -> str:
    with engine.connect() as conn:
        names = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = DATABASE()"
                )
            ).fetchall()
        }
    head = "20261003_ai1a_config_prompts"
    if "alembic_version" not in names:
        run_alembic(["upgrade", "head"])
    else:
        with engine.connect() as conn:
            revision = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
        if revision != head:
            run_alembic(["upgrade", "head"])
    return head


def reset_prompt_tables(engine) -> None:
    """一次性 integration 库内恢复提示词相关表（不触碰业务表之外内容）。"""
    tables = (
        "prompt_change_records",
        "personal_prompt_heads",
        "personal_prompt_versions",
        "prompt_default_versions",
        "prompt_contract_versions",
    )
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for table in tables:
            conn.execute(text(f"DELETE FROM `{table}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))


TEACHER_ACCOUNT = "tow_ai1c"
ADMIN_ACCOUNT = "adm_ai1c"
ADMIN_SESSION_ID = "ses_ai1c_admin"
FIXTURE_PERSONAL_VERSION_ID = "pv_ai1c_fixture_teacher"


def _personal_seed_map() -> dict[str, str]:
    """R2f：完整六字段合成个人 map（合法 v1 个人版本，非单字段）。"""
    return {
        field: f"AI1C-FIXTURE-TEACHER-PERSONAL-v1-{field}"
        for field in fixture_tool.V1_FIELDS
    }


def _select_one(conn, sql: str, params: dict) -> bool:
    return bool(conn.execute(text(sql), params).scalar_one())


def seed_v1_world(engine) -> None:
    """Seed migration-equivalent contract v1 + default r1 for all 7 tasks
    plus synthetic accounts / session / school row / audit rows and one
    legitimate six-field personal v1 for daily_lesson_split.

    所有连接都在显式上下文内关闭；一次性精确库内幂等。
    """
    snapshot = ai_prompt_registry.contract_snapshot()
    defaults = ai_prompt_registry.guidance_defaults_snapshot()
    stamp = utc_now()
    session_expires_at = stamp + timedelta(hours=1)

    contract_rows = []
    default_rows = []
    for task_type, payload in snapshot.items():
        contract_rows.append(dict(
            id=app.security.generate_id(),
            task_type=task_type,
            contract_version=1,
            input_vars=payload["input_vars"],
            output_schema=payload["output_schema"],
            guidance_fields=list(payload["guidance_fields"]),
            created_by=None,
            created_at=stamp,
        ))
        default_rows.append(dict(
            id=app.security.generate_id(),
            task_type=task_type,
            default_revision=1,
            contract_version=1,
            guidance_map=dict(defaults[task_type]),
            created_by=None,
            created_at=stamp,
        ))

    with engine.begin() as conn:
        # —— 合成账号：教师（不变式主角）＋ 管理员（真实默认发布竞争用）——
        if not _select_one(
            conn,
            f"SELECT COUNT(*) FROM accounts WHERE id = '{TEACHER_ACCOUNT}'",
            {},
        ):
            conn.execute(
                text(
                    "INSERT INTO accounts (id, username, password_hash, "
                    "display_name, role, is_active, version, auth_version, "
                    "created_at, updated_at) VALUES ('tow_ai1c', 'tow_ai1c', "
                    "'not-a-real-hash', '夹具老师甲', 'teacher', 1, 1, 1, "
                    ":now, :now)"
                ),
                {"now": stamp},
            )
        if not _select_one(
            conn,
            f"SELECT COUNT(*) FROM accounts WHERE id = '{ADMIN_ACCOUNT}'",
            {},
        ):
            conn.execute(
                text(
                    "INSERT INTO accounts (id, username, password_hash, "
                    "display_name, role, is_active, version, auth_version, "
                    "created_at, updated_at) VALUES ('adm_ai1c', 'adm_ai1c', "
                    "'not-a-real-hash', '夹具管理员', 'admin', 1, 1, 1, "
                    ":now, :now)"
                ),
                {"now": stamp},
            )
        if not _select_one(
            conn,
            f"SELECT COUNT(*) FROM sessions WHERE id = '{ADMIN_SESSION_ID}'",
            {},
        ):
            conn.execute(
                text(
                    "INSERT INTO sessions (id, token_hash, account_id, "
                    "auth_version, created_at, expires_at, revoked_at) "
                    "VALUES ('ses_ai1c_admin', "
                    "'ai1c-fixture-not-a-real-token-hash', 'adm_ai1c', 1, "
                    ":now, :expires, NULL)"
                ),
                {"now": stamp, "expires": session_expires_at},
            )
        # school_settings 单行（业务不变式证据；只种一次）。
        if not _select_one(
            conn,
            "SELECT COUNT(*) FROM school_settings WHERE id = 'singleton'",
            {},
        ):
            conn.execute(
                text(
                    "INSERT INTO school_settings (id, school_name, version, "
                    "schedule_version, plans_started_at, created_at, "
                    "updated_at) VALUES ('singleton', 'AI1C 夹具幼儿园', "
                    "1, 1, :now, :now, :now)"
                ),
                {"now": stamp},
            )
        # 合成业务记录：一条 operation-record＋对应 prompt_change_record
        # （personal_init 形状合法），供零增量不变式比较有实际内容。
        if not _select_one(
            conn,
            "SELECT COUNT(*) FROM operation_records WHERE id = "
            "'op_ai1c_teacher_base'",
            {},
        ):
            conn.execute(
                text(
                    "INSERT INTO operation_records (id, created_at, "
                    "operator_id, operator_type, action, target_type, "
                    "target_id, target_version_after, target_account_id, "
                    "account_version_after) VALUES "
                    "('op_ai1c_teacher_base', :now, 'tow_ai1c', 'account', "
                    "'prompt_personal_init', 'school', 'singleton', NULL, "
                    "NULL, NULL)"
                ),
                {"now": stamp},
            )
        if not _select_one(
            conn,
            "SELECT COUNT(*) FROM prompt_change_records WHERE id = "
            "'pcr_ai1c_teacher_base'",
            {},
        ):
            conn.execute(
                text(
                    "INSERT INTO prompt_change_records (id, "
                    "operation_record_id, task_type, event_kind, "
                    "personal_revision_before, personal_revision_after, "
                    "default_revision_target, contract_version_target, "
                    "changed_fields, created_at) VALUES "
                    "('pcr_ai1c_teacher_base', 'op_ai1c_teacher_base', "
                    "'daily_lesson_split', 'personal_init', NULL, 1, 1, 1, "
                    "'[\"theme\"]', :now)"
                ),
                {"now": stamp},
            )

        conn.execute(insert(PromptContractVersion), contract_rows)
        conn.execute(insert(PromptDefaultVersion), default_rows)
        conn.execute(
            insert(PersonalPromptVersion),
            [dict(
                id=FIXTURE_PERSONAL_VERSION_ID,
                account_id=TEACHER_ACCOUNT,
                task_type="daily_lesson_split",
                personal_revision=1,
                guidance_map=_personal_seed_map(),
                based_contract_version=1,
                accepted_default_revision=1,
                created_by=TEACHER_ACCOUNT,
                created_at=stamp,
            )],
        )
        conn.execute(
            insert(PersonalPromptHead),
            [dict(
                account_id=TEACHER_ACCOUNT,
                task_type="daily_lesson_split",
                current_personal_revision=1,
                adaptation_state="current",
                required_contract_version=None,
                last_seen_default_revision=1,
                last_rejected_default_revision=None,
                created_at=stamp,
                updated_at=stamp,
            )],
        )


def world_state(engine) -> dict:
    """发布前后规范化快照（JSON 正确解码：数组保序、map 无序比较）。

    覆盖复审要求的不变式证据面：
    * 个人完整文字（personal versions 全字段 map）与 head 全部保护列
      （current／state／required／last_seen／last_rejected）；
    * accounts.version／auth_version／role／is_active／display_name；
    * sessions（会话表未被子例增删）；
    * school_settings 单行；
    * operation_records 与 prompt_change_records（含合成业务记录）；
    * daily_lesson_split 的契约与默认全文；
    * 其他任务的契约与默认全文。
    """
    with Session(engine, future=True) as session:
        heads = {
            f"{row.account_id}:{row.task_type}": (
                row.current_personal_revision,
                row.adaptation_state,
                row.required_contract_version,
                row.last_seen_default_revision,
                row.last_rejected_default_revision,
            )
            for row in session.scalars(select(PersonalPromptHead))
        }
        personal_versions = {
            (row.account_id, row.task_type, row.personal_revision): dict(
                row.guidance_map or {}
            )
            for row in session.scalars(select(PersonalPromptVersion))
        }
        accounts = {
            row.id: (
                row.display_name,
                row.role,
                bool(row.is_active),
                row.version,
                row.auth_version,
            )
            for row in session.scalars(select(Account))
        }
        sessions = {
            row.id: (
                row.account_id,
                row.auth_version,
                row.expires_at,
                row.revoked_at,
            )
            for row in session.scalars(select(AccountSession))
        }
        # S3：SchoolSettings 是单行 ORM 实体；用 scalars 提取实体本身，
        # 不把 execute(...).one_or_none() 返回的包装 Row 当实体读属性。
        school_row = session.scalars(select(SchoolSettings)).one_or_none()
        school = (
            None
            if school_row is None
            else (
                school_row.school_name,
                school_row.version,
                school_row.schedule_version,
                school_row.plans_started_at,
            )
        )
        # 审计与合成业务记录：按 id 排序的稳定列表。
        operations = [
            (
                row.id,
                row.operator_id,
                row.operator_type,
                row.action,
                row.target_type,
                row.target_id,
                row.target_version_after,
            )
            for row in session.scalars(
                select(OperationRecord).order_by(OperationRecord.id)
            )
        ]
        change_records = [
            (
                row.id,
                row.operation_record_id,
                row.task_type,
                row.event_kind,
                row.personal_revision_before,
                row.personal_revision_after,
                row.default_revision_target,
                row.contract_version_target,
                list(row.changed_fields or []),
            )
            for row in session.scalars(
                select(PromptChangeRecord).order_by(PromptChangeRecord.id)
            )
        ]
        contracts_daily = [
            (
                row.contract_version,
                list(row.guidance_fields or []),
                row.input_vars,
                row.output_schema,
                row.created_by,
            )
            for row in session.scalars(
                select(PromptContractVersion)
                .where(PromptContractVersion.task_type == "daily_lesson_split")
                .order_by(PromptContractVersion.contract_version)
            )
        ]
        defaults_daily = [
            (
                row.default_revision,
                row.contract_version,
                dict(row.guidance_map or {}),
                row.created_by,
            )
            for row in session.scalars(
                select(PromptDefaultVersion)
                .where(PromptDefaultVersion.task_type == "daily_lesson_split")
                .order_by(PromptDefaultVersion.default_revision)
            )
        ]
        other_contracts = [
            (
                row.task_type,
                row.contract_version,
                list(row.guidance_fields or []),
            )
            for row in session.scalars(
                select(PromptContractVersion)
                .where(PromptContractVersion.task_type != "daily_lesson_split")
                .order_by(PromptContractVersion.task_type,
                          PromptContractVersion.contract_version)
            )
        ]
        other_defaults = [
            (
                row.task_type,
                row.default_revision,
                row.contract_version,
                dict(row.guidance_map or {}),
                row.created_by,
            )
            for row in session.scalars(
                select(PromptDefaultVersion)
                .where(PromptDefaultVersion.task_type != "daily_lesson_split")
                .order_by(PromptDefaultVersion.task_type,
                          PromptDefaultVersion.default_revision)
            )
        ]

    return dict(
        heads=heads,
        personal_versions=personal_versions,
        accounts=accounts,
        sessions=sessions,
        school=school,
        operations=operations,
        change_records=change_records,
        contracts_daily=contracts_daily,
        defaults_daily=defaults_daily,
        other_contracts=other_contracts,
        other_defaults=other_defaults,
    )


def changed_keys(before: dict, after: dict) -> set[str]:
    """快照之间的实际变化键集合（键集合必须一致）。"""
    if set(before) != set(after):
        raise AssertionError(
            "world_state键集合不一致：" + str(
                set(before) ^ set(after)
            )
        )
    return {key for key in before if before[key] != after[key]}


# ---------------------------------------------------------------------------
# S4/S5 断言语义的纯函数（离线检查与真库集成测试共同调用）
# ---------------------------------------------------------------------------

# world_state 快照中代表"审计 / 合成业务记录"的键（S5）。
AUDIT_KEYS = ("operations", "change_records")
# 代表"个人／head／账号会话／学校设置／其他任务"等未被本次动作允许触碰
# 的保护状态的键（与审计键一一对应分开断言）。
PROTECTED_KEYS = (
    "personal_versions",
    "heads",
    "accounts",
    "sessions",
    "school",
    "other_contracts",
    "other_defaults",
)


def assert_protected_state_untouched(
    before: dict, after: dict, *, rationale: str = ""
) -> None:
    """保护状态断言：个人完整文字／head／accounts／sessions／school /
    其他任务在前后快照间完全未变（不含审计键）。

    与审计断言分开（S5）：工具发布成功、真实管理员发布成功、拒绝路径
    都必须通过本断言；任何额外写入个人或保护状态都视为保护被破坏。
    """
    diffs = [key for key in PROTECTED_KEYS if before[key] != after[key]]
    if diffs:
        raise AssertionError(
            "保护状态被改动" + (f"（{rationale}）" if rationale else "")
            + "：" + "; ".join(diffs)
        )


def assert_audits_unchanged(
    before: dict, after: dict, *, rationale: str = ""
) -> None:
    """审计零增量断言：工具发布成功不得新增／修改／删除任何审计记录
    （S5：工具发布不写审计）。拒绝路径同样适用。"""
    diffs = [key for key in AUDIT_KEYS if before[key] != after[key]]
    if diffs:
        raise AssertionError(
            "审计被写入（应为零增量）"
            + (f"（{rationale}）" if rationale else "")
            + "：" + "; ".join(diffs)
        )


def _hashable_row(row: tuple) -> tuple:
    """把含 JSON 列表／字典的快照行转成可比较的等值形态。

    world_state 行内含列表（如 changed_fields）；set 比较要求可哈希，
    列表递归转为元组（语义上与列表相等比较一致）。
    """
    if isinstance(row, list):
        return tuple(_hashable_row(item) for item in row)
    if isinstance(row, tuple):
        return tuple(_hashable_row(item) for item in row)
    return row


def assert_audits_append_only(
    before: dict, after: dict, *, added_per_key: int = 1, rationale: str = ""
) -> dict[str, tuple]:
    """审计合法追加断言（S5：真实管理员发布成功合法追加审计）。

    * 旧行一字不改（set 比较，行内任何字段变化都算改动）；
    * 每个 audit 键恰好新增 ``added_per_key`` 行，且不删除任何旧行；
    * 返回每个键对应的新增行。
    """
    if not rationale:
        raise RuntimeError("assert_audits_append_only 需要 rationale")
    added: dict[str, tuple] = {}
    for key in AUDIT_KEYS:
        old_rows = {_hashable_row(row) for row in before[key]}
        new_rows = {_hashable_row(row) for row in after[key]}
        removed = old_rows - new_rows
        if removed:
            raise AssertionError(
                f"审计行被删除（{rationale}；{key}）：{len(removed)} 行"
            )
        appended_hashes = new_rows - old_rows
        if len(appended_hashes) != added_per_key:
            raise AssertionError(
                f"审计新增行数不符（{rationale}；{key}）："
                f"预期 {added_per_key}，实际 {len(appended_hashes)}"
            )
        appended_hash = next(iter(appended_hashes))
        appended_row = next(
            row for row in after[key]
            if _hashable_row(row) == appended_hash
        )
        added[key] = appended_row
    return added


def assert_product_audit_append_legal(
    before: dict, after: dict, *, task_type: str, changed_fields: tuple,
    rationale: str = "",
) -> tuple:
    """产品管理员发布成功（prompt_service.update_default）的合法审计增量。

    在 ``assert_audits_append_only`` 基础上核对新行的决定性字段：
    operation（operator=管理员账号 account、action=prompt_default_update、
    target=school/singleton、target_version_after=None）与 change record
    （event_kind=default_update、task／契约／默认修订目标、changed_fields
    只含字段名、且与 operation 关联）。
    """
    added = assert_audits_append_only(before, after, rationale=rationale)
    operation_id, operator_id, operator_type, action, target_type, \
        target_id, target_version_after = added["operations"]
    (change_id, change_operation_id, record_task, event_kind,
     personal_revision_before, personal_revision_after,
     default_revision_target, contract_version_target,
     record_changed_fields) = added["change_records"]
    problems: list[str] = []
    if operator_type != "account" or action != "prompt_default_update":
        problems.append("operation_kind")
    if target_type != "school" or target_id != "singleton":
        problems.append("operation_target")
    if target_version_after is not None:
        problems.append("operation_target_version")
    if operator_id != ADMIN_ACCOUNT:
        problems.append("operation_operator")
    if record_task != task_type:
        problems.append("record_task")
    if event_kind != "default_update":
        problems.append("record_event_kind")
    if personal_revision_before is not None or personal_revision_after is not None:
        problems.append("record_personal_revisions")
    if contract_version_target is None or default_revision_target is None:
        problems.append("record_targets")
    if len(record_changed_fields) != len(changed_fields) or sorted(
        record_changed_fields
    ) != sorted(changed_fields):
        problems.append("record_changed_fields")
    if change_operation_id != operation_id:
        problems.append("record_operation_link")
    if problems:
        raise AssertionError(
            "产品发布审计增量不合法" + (
                f"（{rationale}）" if rationale else ""
            ) + "：" + "; ".join(problems)
        )
    return added
