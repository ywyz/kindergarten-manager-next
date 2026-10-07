#!/usr/bin/env python3
"""AI 1C 验收夹具工具（仅 inspect / publish-v2 / publish-v3）。

依据 ``docs/bootstrap/ai-slice1c-fixture-plan-2026-10-07.md`` §3 与
2026-10-07 编码提示词：

* 连接前目标保护：DSN 只来自专用环境变量 ``AI1C_FIXTURE_DATABASE_URL``；
  ``--mode acceptance|integration`` 决定唯一允许目标（驱动 mysql+pymysql、
  host 127.0.0.1／localhost、固定端口与精确库名）。任何其他 schema（尤其是
  ``kg_next_i5_acceptance``）、主机、端口、驱动、空目标或 URL 查询参数
  一律在建 engine／连接前拒绝。不回显输入 URL、查询参数、密码、原始
  异常或 exception repr。
* 模块 import 时即设置 ``APP_DISABLE_DOTENV=1``，并丢弃本进程继承的
  DATABASE_URL／AI_MASTER_KEY／AI_MASTER_KEY_ID（不修改父 shell）。
  import 与 --help 不连接数据库、不写库、不加载私密配置。
* 仅有 inspect、publish-v2、publish-v3；不提供 reset/drop/truncate/任意
  map 或 schema 编辑，不做迁移、建库、GRANT，不读取 AI_MASTER_KEY，
  不启动服务。
* 固定配方仅针对 ``daily_lesson_split``：v1 六字段必须实读匹配；v2 移除
  preparation 并末尾新增 acceptance_support；v3 再移除 process。各版默认
  文字为固定、无价值合成标记；input_vars／output_schema 从数据库上一
  契约快照原样复制，不改代码 registry。
* 发布要求 ``AI1C_FIXTURE_ALLOW_PUBLISH=yes``，并按既有协议在单一事务内
  完成：v1 锚点 FOR UPDATE → 锁内 locking read 最新契约与任务全历史最新
  默认 → 期望值／顺序／完整性校验 → 原子追加一份契约行与一份完整默认行
  （created_by NULL、UTC）→ 事务内后置验证；所有提交前失败（含后置验证）
  确定回滚且零增量。重复调用或旧 expected 全部拒绝，不做 UPDATE 覆盖或
  upsert。
* 提交边界（R1 补修）：结果 dict 在 commit 前用纯标量构建；commit 成功后
  不再读取任何 ORM 属性或执行数据库读写（expire_on_commit=True 下也不会
  触发提交后隐式刷新）。``Session.commit()`` 本身抛出的异常按"COMMIT 结果
  不确定"处理（``AI1C_COMMIT_UNCERTAIN``）：不声称回滚、不自动重试，仅
  提示先 inspect 只读核对；提交前的写失败才是确定回滚
  （``AI1C_DB_OPERATIONAL``）。固定输出不含 SQL 参数／原始异常细节。

本运维工具不导入 tests 包；测试模块可以导入本工具的 guard／核心函数。
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

# 让本脚本可以直接（.venv/bin/python scripts/ai1c_acceptance_fixture.py）运行。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ---------------------------------------------------------------------------
# 进程环境隔离（必须在任何 app import 之前执行；只影响本进程，不改父 shell）
# ---------------------------------------------------------------------------
os.environ["APP_DISABLE_DOTENV"] = "1"
for _leaked in ("DATABASE_URL", "AI_MASTER_KEY", "AI_MASTER_KEY_ID"):
    os.environ.pop(_leaked, None)

from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.engine import Engine, make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app import security  # noqa: E402
from app.models import PromptContractVersion, PromptDefaultVersion  # noqa: E402
from app.services import ai_locks  # noqa: E402
from app.services.auth_service import utc_now  # noqa: E402,F401

DSN_ENV_VAR = "AI1C_FIXTURE_DATABASE_URL"
PUBLISH_SWITCH_VAR = "AI1C_FIXTURE_ALLOW_PUBLISH"

MODE_SPECS: dict[str, dict[str, Any]] = {
    "acceptance": {
        "drivername": "mysql+pymysql",
        "hosts": ("127.0.0.1", "localhost"),
        "port": 13386,
        "database": "kg_next_ai1c_fixture",
    },
    "integration": {
        "drivername": "mysql+pymysql",
        "hosts": ("127.0.0.1", "localhost"),
        "port": 13387,
        "database": "kindergarten_test_ai1c_fixture",
    },
}
MODES = tuple(sorted(MODE_SPECS))

EXPECTED_MIGRATION_HEAD = "20261003_ai1a_config_prompts"
REQUIRED_TABLES = (
    "prompt_contract_versions",
    "prompt_default_versions",
    "personal_prompt_versions",
    "personal_prompt_heads",
    "prompt_change_records",
)

FIXTURE_TASK_TYPE = "daily_lesson_split"

V1_FIELDS: tuple[str, ...] = (
    "theme",
    "objectives",
    "preparation",
    "key_points",
    "difficult_points",
    "process",
)
V2_FIELDS: tuple[str, ...] = (
    "theme",
    "objectives",
    "key_points",
    "difficult_points",
    "process",
    "acceptance_support",
)
V3_FIELDS: tuple[str, ...] = (
    "theme",
    "objectives",
    "key_points",
    "difficult_points",
    "acceptance_support",
)
CONTRACT_RECIPES: dict[int, tuple[str, ...]] = {
    1: V1_FIELDS,
    2: V2_FIELDS,
    3: V3_FIELDS,
}
# 只允许 v1→v2、v2→v3；重复、回退、跳版一律拒绝。
ALLOWED_TRANSITIONS: tuple[tuple[int, int], ...] = ((1, 2), (2, 3))

MAX_GUIDANCE_FIELD_CHARS = 8000
SYNTHETIC_PREFIX = "AI1C-FIXTURE"

# ---------------------------------------------------------------------------
# 固定错误码与固定短句（不含任何动态细节／输入回显）
# ---------------------------------------------------------------------------
ERR_TARGET_UNSET = "AI1C_TARGET_UNSET"
ERR_TARGET_REFUSED = "AI1C_TARGET_REFUSED"
ERR_PUBLISH_SWITCH_MISSING = "AI1C_PUBLISH_SWITCH_MISSING"
ERR_INPUT_INVALID = "AI1C_INPUT_INVALID"
ERR_DB_CHECK_FAILED = "AI1C_DB_CHECK_FAILED"
ERR_ANCHOR_V1_INVALID = "AI1C_ANCHOR_V1_INVALID"
ERR_PREVIOUS_STATE_INVALID = "AI1C_PREVIOUS_STATE_INVALID"
ERR_TRANSITION_REFUSED = "AI1C_TRANSITION_REFUSED"
ERR_EXPECTED_MISMATCH = "AI1C_EXPECTED_MISMATCH"
ERR_CONTRACT_EXISTS = "AI1C_CONTRACT_EXISTS"
ERR_POST_VERIFY_FAILED = "AI1C_POST_VERIFY_FAILED"
ERR_DB_OPERATIONAL = "AI1C_DB_OPERATIONAL"
ERR_COMMIT_UNCERTAIN = "AI1C_COMMIT_UNCERTAIN"
ERR_UNEXPECTED = "AI1C_UNEXPECTED"

MESSAGE_TARGET_UNSET = (
    f"未设置专用环境变量 {DSN_ENV_VAR}，工具已停止，未连接任何数据库。"
)
MESSAGE_TARGET_REFUSED = (
    "目标被拒绝（驱动／主机／端口／库名或 URL 查询参数不符合所选模式"
    "白名单），未建立任何连接。"
)
MESSAGE_PUBLISH_SWITCH = (
    f"发布被拒绝：未设置 {PUBLISH_SWITCH_VAR}=yes，本次未连接数据库。"
)
MESSAGE_INPUT_INVALID = (
    "预期契约／默认取值无效（必须是严格正整数），本次未连接数据库或未写入。"
)
MESSAGE_DB_CHECK_FAILED = (
    "目标库环境核对未通过"
    "（MySQL 8.4／InnoDB／迁移头／所需表要求不满足），目标保持不变。"
)
MESSAGE_ANCHOR_INVALID = "v1 锚点缺失或字段集与固定配方不符，已拒绝发布。"
MESSAGE_PREVIOUS_INVALID = (
    "上一契约或其最新默认完整性校验未通过，已拒绝发布。"
)
MESSAGE_TRANSITION_REFUSED = (
    "契约推进顺序不在允许范围（仅允许 v1→v2、v2→v3），未发生任何写入。"
)
MESSAGE_EXPECTED_MISMATCH = (
    "expected 与当前最新契约／默认修订不一致，未发生任何写入。"
)
MESSAGE_CONTRACT_EXISTS = "目标契约版本已存在，拒绝重复发布，未发生任何写入。"
MESSAGE_POST_VERIFY_FAILED = "发布后置校验失败，事务已回滚，目标保持不变。"
MESSAGE_DB_OPERATIONAL = "数据库操作失败，事务已回滚；不提供原始异常细节。"
MESSAGE_COMMIT_UNCERTAIN = (
    "COMMIT 结果不确定：进程在提交阶段失败，本次发布可能已生效、也可能未"
    "生效。本工具不会自动重试，也不声称回滚；请先执行 inspect 只读核对"
    "当前契约与默认状态，再决定是否重新发布。"
)
MESSAGE_UNEXPECTED = (
    "工具遇到未预期错误；事务状态可能已回滚也可能不确定，不提供原始异常"
    "细节；请先以 inspect 只读核对后再决定下一步。"
)


class FixtureError(Exception):
    """固定失败：固定错误码 + 固定短句，不含细节。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class FixtureGuardError(FixtureError):
    """建 engine／连接之前就拒绝的固定失败。"""


# ---------------------------------------------------------------------------
# 目标保护
# ---------------------------------------------------------------------------


def mode_spec(mode: str) -> dict[str, Any]:
    try:
        return MODE_SPECS[mode]
    except KeyError:
        raise FixtureGuardError(
            ERR_TARGET_REFUSED, "模式必须是 acceptance 或 integration。"
        ) from None


def validate_target_url(mode: str, raw_url: Any) -> Any:
    """在建 engine／连接前校验候选 DSN；失败不回显输入。"""
    spec = mode_spec(mode)
    if not isinstance(raw_url, str) or raw_url.strip() == "":
        raise FixtureGuardError(ERR_TARGET_REFUSED, MESSAGE_TARGET_REFUSED)
    try:
        url = make_url(raw_url)
        port = url.port
    except Exception:
        raise FixtureGuardError(ERR_TARGET_REFUSED, MESSAGE_TARGET_REFUSED) from None
    if url.drivername != spec["drivername"]:
        raise FixtureGuardError(ERR_TARGET_REFUSED, MESSAGE_TARGET_REFUSED)
    if url.host not in spec["hosts"]:
        raise FixtureGuardError(ERR_TARGET_REFUSED, MESSAGE_TARGET_REFUSED)
    if port != spec["port"]:
        raise FixtureGuardError(ERR_TARGET_REFUSED, MESSAGE_TARGET_REFUSED)
    if url.database != spec["database"]:
        raise FixtureGuardError(ERR_TARGET_REFUSED, MESSAGE_TARGET_REFUSED)
    if url.query:
        # 任何 URL 查询参数都不允许，防止路由参数绕过白名单库名。
        raise FixtureGuardError(ERR_TARGET_REFUSED, MESSAGE_TARGET_REFUSED)
    return url


def resolve_target_url(mode: str) -> Any:
    """只从专用环境变量读取 DSN（guard 校验）。"""
    raw = os.environ.get(DSN_ENV_VAR)
    if not raw or raw.strip() == "":
        raise FixtureGuardError(ERR_TARGET_UNSET, MESSAGE_TARGET_UNSET)
    return validate_target_url(mode, raw)


def create_guarded_engine(mode: str, raw_url: str | None) -> Engine:
    """guard 通过后创建 engine（echo=False，NullPool）。"""
    url = validate_target_url(mode, raw_url)
    return create_engine(
        url,
        poolclass=NullPool,
        future=True,
        echo=False,
    )


# ---------------------------------------------------------------------------
# 固定配方（纯函数）
# ---------------------------------------------------------------------------


def synthetic_default_text(contract_version: int, field: str) -> str:
    """固定、无价值合成默认文字（公开标记，非真实内容）。"""
    return (
        f"{SYNTHETIC_PREFIX}-v{contract_version}-{field}"
        "（AI 1C 验收合成默认指导，与产品真实默认内容无关）"
    )


def recipe_guidance_map(contract_version: int) -> dict[str, str]:
    fields = CONTRACT_RECIPES[contract_version]
    return {
        field: synthetic_default_text(contract_version, field)
        for field in fields
    }


def validate_recipe(contract_version: int) -> None:
    """配方自身完整性：固定顺序、无重复、map 与字段集一致、≤8000。"""
    fields = CONTRACT_RECIPES.get(contract_version)
    if fields is None or len(fields) != len(set(fields)):
        raise FixtureError(ERR_INPUT_INVALID, MESSAGE_INPUT_INVALID)
    mapping = recipe_guidance_map(contract_version)
    if list(mapping.keys()) != list(fields):
        raise FixtureError(ERR_INPUT_INVALID, MESSAGE_INPUT_INVALID)
    for value in mapping.values():
        if not isinstance(value, str) or not value:
            raise FixtureError(ERR_INPUT_INVALID, MESSAGE_INPUT_INVALID)
        if len(value) > MAX_GUIDANCE_FIELD_CHARS:
            raise FixtureError(ERR_INPUT_INVALID, MESSAGE_INPUT_INVALID)


def validate_expected_arguments(
    expected_contract_version: Any, expected_default_revision: Any
) -> tuple[int, int]:
    """严格正整数校验（拒绝 bool、非 int、0、负数）。"""
    for value in (expected_contract_version, expected_default_revision):
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 1
        ):
            raise FixtureError(ERR_INPUT_INVALID, MESSAGE_INPUT_INVALID)
    return expected_contract_version, expected_default_revision


def transition_recipe_matches(old_version: int, target_version: int) -> bool:
    """转换配方校验：v1→v2 仅移除 preparation 并末尾新增
    acceptance_support（其余同名保留）；v2→v3 仅移除 process。
    其余组合一律不允许。"""
    if (
        old_version not in CONTRACT_RECIPES
        or target_version not in CONTRACT_RECIPES
        or (old_version, target_version) not in ALLOWED_TRANSITIONS
    ):
        return False
    old_fields = set(CONTRACT_RECIPES[old_version])
    target_fields = set(CONTRACT_RECIPES[target_version])
    added = target_fields - old_fields
    removed = old_fields - target_fields
    if old_version == 1 and target_version == 2:
        return added == {"acceptance_support"} and removed == {"preparation"}
    return added == set() and removed == {"process"}


# ---------------------------------------------------------------------------
# 连接后只读核对（inspect 与 publish 共用）
# ---------------------------------------------------------------------------


def _check_target_identity(db: Session, mode: str) -> str:
    """只读核对 DATABASE()、MySQL 8.4、InnoDB、迁移头与所需表。

    成功返回 MySQL 版本字符串；失败抛固定错误码（无细节回显）。
    """
    spec = mode_spec(mode)
    try:
        database = db.execute(text("SELECT DATABASE()")).scalar()
        version = db.execute(text("SELECT VERSION()")).scalar()
        engine_row = db.execute(
            text("SHOW VARIABLES LIKE 'default_storage_engine'")
        ).fetchone()
        revision = db.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
        table_engines = {
            row[0]: row[1]
            for row in db.execute(
                text(
                    "SELECT table_name, engine FROM information_schema.tables "
                    "WHERE table_schema = DATABASE()"
                )
            ).fetchall()
        }
    except Exception:
        raise FixtureError(
            ERR_DB_CHECK_FAILED, MESSAGE_DB_CHECK_FAILED
        ) from None
    failed = (
        database != spec["database"]
        or not isinstance(version, str)
        or not version.startswith("8.4")
        or not engine_row
        or str(engine_row[1]).lower() != "innodb"
        or revision != EXPECTED_MIGRATION_HEAD
        or any(
            str(table_engines.get(table, "")).lower() != "innodb"
            for table in REQUIRED_TABLES
        )
    )
    if failed:
        raise FixtureError(ERR_DB_CHECK_FAILED, MESSAGE_DB_CHECK_FAILED)
    return version  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# inspect（只读；不需要发布开关）
# ---------------------------------------------------------------------------


def inspect_fixture(session: Session) -> dict[str, Any]:
    """去敏只读报告：契约演进字段名与任务全历史最新默认修订。

    只 select 最少列（契约号＋字段名、默认修订号＋契约号），不加载
    input_vars／output_schema／guidance_map 等指导正文，也不输出配置密
    文、密码哈希或指导全文。
    """
    contract_rows = session.execute(
        select(
            PromptContractVersion.contract_version,
            PromptContractVersion.guidance_fields,
        )
        .where(PromptContractVersion.task_type == FIXTURE_TASK_TYPE)
        .order_by(PromptContractVersion.contract_version.asc())
    ).all()
    contracts = [
        dict(
            contract_version=version,
            guidance_fields=list(fields),
        )
        for version, fields in contract_rows
    ]
    latest_default = session.execute(
        select(
            PromptDefaultVersion.default_revision,
            PromptDefaultVersion.contract_version,
        )
        .where(PromptDefaultVersion.task_type == FIXTURE_TASK_TYPE)
        .order_by(PromptDefaultVersion.default_revision.desc())
        .limit(1)
    ).one_or_none()
    return {
        "task_type": FIXTURE_TASK_TYPE,
        "v1_anchor_present": bool(
            contracts and contracts[0]["contract_version"] == 1
        ),
        "v1_fields": contracts[0]["guidance_fields"] if contracts else None,
        "latest_contract_version": (
            contracts[-1]["contract_version"] if contracts else None
        ),
        "latest_contract_fields": (
            contracts[-1]["guidance_fields"] if contracts else None
        ),
        "latest_default_revision": (
            latest_default[0] if latest_default is not None else None
        ),
        "latest_default_contract_version": (
            latest_default[1] if latest_default is not None else None
        ),
        "contract_versions_count": len(contracts),
    }


def run_inspect(mode: str) -> dict[str, Any]:
    """inspect 入口：guard engine + 只读核对 + 去敏报告。"""
    engine = create_guarded_engine(mode, os.environ.get(DSN_ENV_VAR))
    try:
        with Session(engine, future=True) as session:
            mysql_version = _check_target_identity(session, mode)
            report = inspect_fixture(session)
    finally:
        engine.dispose()
    report["mysql_version"] = mysql_version
    report["migration_head"] = EXPECTED_MIGRATION_HEAD
    report["task_types_supported"] = [FIXTURE_TASK_TYPE]
    report["status"] = "inspected"
    return report


# ---------------------------------------------------------------------------
# 固定配方发布核心（单事务；CLI 与集成测试共用）
# ---------------------------------------------------------------------------


def _begin(db: Session) -> None:
    if not db.in_transaction():
        db.begin()


def _latest_default_of_contract_locked(
    db: Session, contract_version: int
) -> Any:
    """某契约下最新默认行（排他锁定读；发布路径）。"""
    return db.execute(
        select(PromptDefaultVersion)
        .where(
            PromptDefaultVersion.task_type == FIXTURE_TASK_TYPE,
            PromptDefaultVersion.contract_version == contract_version,
        )
        .order_by(PromptDefaultVersion.default_revision.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _task_wide_latest_default_locked(db: Session) -> Any:
    """任务全历史（全部契约）最新默认行（排他锁定读）。"""
    return db.execute(
        select(PromptDefaultVersion)
        .where(PromptDefaultVersion.task_type == FIXTURE_TASK_TYPE)
        .order_by(PromptDefaultVersion.default_revision.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _map_is_complete(mapping: Any, fields: tuple[str, ...]) -> bool:
    """完整性：map（键序无关）与字段集一致，每字段均为字符串且 ≤8000。"""
    if not isinstance(mapping, dict):
        return False
    if sorted(mapping.keys()) != sorted(fields):
        return False
    for value in mapping.values():
        if not isinstance(value, str):
            return False
        if len(value) > MAX_GUIDANCE_FIELD_CHARS:
            return False
    return True


def run_publish(
    db: Session,
    target_contract_version: int,
    expected_contract_version: int,
    expected_default_revision: int,
) -> dict[str, Any]:
    """固定配方发布：单事务、原子追加、提交前失败即回滚零增量。

    协议（与产品发布路径同锚点）：

    1. 严格正整数预处理（建连接之前）。
    2. v1 锚点 FOR UPDATE。
    3. 锁内 locking read 最新契约；校验允许顺序（v1→v2、v2→v3）。
    4. 上一契约字段必须匹配固定配方；该契约最新默认 map 必须完整。
    5. 锁内 locking read 任务全历史最新默认（MAX 修订）。
    6. expected 契约／修订必须精确匹配当前状态。
    7. 原子追加一份契约行 + 一份完整默认行（created_by=None、UTC）。
    8. 事务内后置验证；失败抛错（提交前，确定回滚，零增量）。
    9. 结果 dict 在 commit 前用纯标量构建；commit 后不读任何 ORM 属性、
       不执行任何数据库读写（expire_on_commit=True 也不会触发提交后刷新）。
       ``Session.commit()`` 本身抛出的异常一律按 "COMMIT 结果不确定"
       处理（AI1C_COMMIT_UNCERTAIN）：不声称回滚、不自动重试，仅提示先
       inspect 只读核对；提交前的写失败才按确定回滚（AI1C_DB_OPERATIONAL）。
    """
    validate_expected_arguments(
        expected_contract_version, expected_default_revision
    )
    if target_contract_version not in (2, 3):
        raise FixtureError(ERR_INPUT_INVALID, MESSAGE_INPUT_INVALID)

    _begin(db)
    try:
        # —— 提交前阶段：全部校验、读取、写入与后置验证 ——
        # 1. 固定 v1 锚点 FOR UPDATE。
        anchor = ai_locks.lock_contract_anchor(
            db, FIXTURE_TASK_TYPE, for_update=True
        )
        if list(anchor.guidance_fields or []) != list(V1_FIELDS):
            raise FixtureError(ERR_ANCHOR_V1_INVALID, MESSAGE_ANCHOR_INVALID)

        # 2. 锁内 locking read 最新契约（排他）。
        prev = ai_locks.latest_contract_row_locked(
            db, FIXTURE_TASK_TYPE, share=False
        )
        prev_version = prev.contract_version

        # 3. 允许的推进顺序（重复、回退、跳版在此拒绝）。
        if (prev_version, target_contract_version) not in ALLOWED_TRANSITIONS:
            raise FixtureError(ERR_TRANSITION_REFUSED, MESSAGE_TRANSITION_REFUSED)

        # 4. 上一契约字段必须匹配固定配方，且两版差异符合固定配方。
        prev_fields = CONTRACT_RECIPES[prev_version]
        if list(prev.guidance_fields or []) != list(prev_fields):
            raise FixtureError(ERR_PREVIOUS_STATE_INVALID, MESSAGE_PREVIOUS_INVALID)
        if not transition_recipe_matches(prev_version, target_contract_version):
            raise FixtureError(ERR_TRANSITION_REFUSED, MESSAGE_TRANSITION_REFUSED)

        # 5. 最新该契约默认必须存在且 map 完整（排他锁定读）。
        prev_default_row = _latest_default_of_contract_locked(db, prev_version)
        if prev_default_row is None or not _map_is_complete(
            prev_default_row.guidance_map, prev_fields
        ):
            raise FixtureError(ERR_PREVIOUS_STATE_INVALID, MESSAGE_PREVIOUS_INVALID)

        # 6. expected 契约版本必须等于当前最新契约版本。
        if expected_contract_version != prev_version:
            raise FixtureError(ERR_EXPECTED_MISMATCH, MESSAGE_EXPECTED_MISMATCH)

        # 7. 任务全历史最新默认修订（MAX+1）；结果标量全部在提交前捕获。
        overall_latest = _task_wide_latest_default_locked(db)
        if overall_latest is None:
            raise FixtureError(ERR_PREVIOUS_STATE_INVALID, MESSAGE_PREVIOUS_INVALID)
        if expected_default_revision != overall_latest.default_revision:
            raise FixtureError(ERR_EXPECTED_MISMATCH, MESSAGE_EXPECTED_MISMATCH)
        if overall_latest.default_revision < prev_default_row.default_revision:
            raise FixtureError(ERR_PREVIOUS_STATE_INVALID, MESSAGE_PREVIOUS_INVALID)
        old_default_revision = overall_latest.default_revision
        new_revision = old_default_revision + 1

        # 8. 单事务原子追加一份契约行 + 一份完整默认行。
        new_contract = PromptContractVersion(
            id=security.generate_id(),
            task_type=FIXTURE_TASK_TYPE,
            contract_version=target_contract_version,
            input_vars=copy.deepcopy(dict(prev.input_vars or {})),
            output_schema=copy.deepcopy(dict(prev.output_schema or {})),
            guidance_fields=list(CONTRACT_RECIPES[target_contract_version]),
            created_by=None,
            created_at=utc_now(),
        )
        new_default = PromptDefaultVersion(
            id=security.generate_id(),
            task_type=FIXTURE_TASK_TYPE,
            default_revision=new_revision,
            contract_version=target_contract_version,
            guidance_map=recipe_guidance_map(target_contract_version),
            created_by=None,
            created_at=utc_now(),
        )
        db.add(new_contract)
        db.add(new_default)
        db.flush()

        # 9. 事务内后置验证（失败 → 异常 → 回滚，零增量）。
        _post_verify(
            db,
            target_contract_version=target_contract_version,
            expected_default_revision=expected_default_revision,
            new_default_revision=new_revision,
        )

        # 10. 提交前用纯标量构建完整结果；commit 后不再读任何 ORM 属性。
        result = {
            "status": "published",
            "task_type": FIXTURE_TASK_TYPE,
            "old_contract_version": prev_version,
            "new_contract_version": target_contract_version,
            "old_default_revision": old_default_revision,
            "new_default_revision": new_revision,
            "fields": list(CONTRACT_RECIPES[target_contract_version]),
        }
    except FixtureError:
        # 提交前拒绝路径：确定回滚，零增量声称保持准确。
        db.rollback()
        raise
    except Exception:
        # 提交前写失败（含 SQL 错误）：确定回滚；转换为固定去敏码，
        # 不输出原始异常／SQL 参数。
        db.rollback()
        raise FixtureError(ERR_DB_OPERATIONAL, MESSAGE_DB_OPERATIONAL) from None

    # —— 提交边界：Session.commit() 抛出异常时 COMMIT 结果不确定 ——
    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            # 连接可能已损坏；best effort 清理，不改变固定输出语义。
            pass
        # 不声称回滚、不声称零增量、不自动重试：只提示先 inspect 核对。
        raise FixtureError(
            ERR_COMMIT_UNCERTAIN, MESSAGE_COMMIT_UNCERTAIN
        ) from None
    return result


def _post_verify(
    db: Session,
    *,
    target_contract_version: int,
    expected_default_revision: int,
    new_default_revision: int,
) -> None:
    """事务内后置验证；失败抛固定错误码（调用方回滚，零增量）。"""
    from sqlalchemy import func

    problems: list[str] = []

    contract_count = db.execute(
        select(func.count())
        .select_from(PromptContractVersion)
        .where(
            PromptContractVersion.task_type == FIXTURE_TASK_TYPE,
            PromptContractVersion.contract_version == target_contract_version,
        )
    ).scalar_one()
    if contract_count != 1:
        problems.append("contract_row_count")

    contract_row = db.execute(
        select(PromptContractVersion)
        .where(
            PromptContractVersion.task_type == FIXTURE_TASK_TYPE,
            PromptContractVersion.contract_version == target_contract_version,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if contract_row is None:
        problems.append("contract_row_missing")
    else:
        if list(contract_row.guidance_fields or []) != list(
            CONTRACT_RECIPES[target_contract_version]
        ):
            problems.append("contract_fields")
        if contract_row.created_by is not None:
            problems.append("contract_created_by")

    default_count = db.execute(
        select(func.count())
        .select_from(PromptDefaultVersion)
        .where(
            PromptDefaultVersion.task_type == FIXTURE_TASK_TYPE,
            PromptDefaultVersion.default_revision == new_default_revision,
        )
    ).scalar_one()
    if default_count != 1:
        problems.append("default_row_count")

    default_row = db.execute(
        select(PromptDefaultVersion)
        .where(
            PromptDefaultVersion.task_type == FIXTURE_TASK_TYPE,
            PromptDefaultVersion.default_revision == new_default_revision,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if default_row is None:
        problems.append("default_row_missing")
    else:
        if default_row.contract_version != target_contract_version:
            problems.append("default_contract_link")
        if default_row.created_by is not None:
            problems.append("default_created_by")
        if not _map_is_complete(
            default_row.guidance_map, CONTRACT_RECIPES[target_contract_version]
        ):
            problems.append("default_map")

    if new_default_revision != expected_default_revision + 1:
        problems.append("revision_numbering")

    if problems:
        raise FixtureError(ERR_POST_VERIFY_FAILED, MESSAGE_POST_VERIFY_FAILED)


# ---------------------------------------------------------------------------
# CLI（去敏输出；固定退出码；无 traceback）
# ---------------------------------------------------------------------------


def _strict_positive_int(value: str) -> int:
    try:
        number = int(value, 10)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("必须是严格正整数") from None
    if number < 1:
        raise argparse.ArgumentTypeError("必须是严格正整数")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai1c_acceptance_fixture",
        description=(
            "AI 1C 验收夹具工具：inspect 只读去敏报告；publish-v2/v3 在"
            "单一事务内按固定配方原子追加契约与默认（需要显式允许开关与"
            "现场 inspect 的 expected）。任何非白名单目标在连接前被拒绝。"
        ),
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=MODES,
        help="acceptance（13386/kg_next_ai1c_fixture）或 integration"
        "（13387/kindergarten_test_ai1c_fixture）；均精确限定。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="只读核对目标库并输出去敏状态。"
    )
    inspect_parser.set_defaults(target_version=None)

    for command, version in (("publish-v2", 2), ("publish-v3", 3)):
        publish_parser = subparsers.add_parser(
            command,
            help=f"固定配方单事务发布契约 v{version} 与配套完整默认。",
        )
        publish_parser.add_argument(
            "--expected-contract-version",
            required=True,
            type=_strict_positive_int,
            help="当前最新契约版本（正整数；以现场 inspect 为准）。",
        )
        publish_parser.add_argument(
            "--expected-default-revision",
            required=True,
            type=_strict_positive_int,
            help="当前该任务最新默认修订（正整数；以现场 inspect 为准）。",
        )
        publish_parser.set_defaults(target_version=version)

    return parser


def run_inspect_command(mode: str) -> dict[str, Any]:
    return run_inspect(mode)


def run_publish_command(
    mode: str,
    target_version: int,
    expected_contract: int,
    expected_default: int,
) -> dict[str, Any]:
    """发布入口：开关检查 → guard → engine → 连接后核对 → 发布。"""
    # 发布开关缺失：在建 engine／连接之前直接拒绝（不连任何数据库）。
    if os.environ.get(PUBLISH_SWITCH_VAR) != "yes":
        raise FixtureGuardError(ERR_PUBLISH_SWITCH_MISSING, MESSAGE_PUBLISH_SWITCH)
    engine = create_guarded_engine(mode, os.environ.get(DSN_ENV_VAR))
    try:
        with Session(engine, future=True) as session:
            _check_target_identity(session, mode)
            result = run_publish(
                session,
                target_contract_version=target_version,
                expected_contract_version=expected_contract,
                expected_default_revision=expected_default,
            )
    finally:
        engine.dispose()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.target_version is None:
            result = run_inspect_command(args.mode)
        else:
            result = run_publish_command(
                mode=args.mode,
                target_version=args.target_version,
                expected_contract=args.expected_contract_version,
                expected_default=args.expected_default_revision,
            )
    except FixtureGuardError as error:
        sys.stderr.write(f"{error.code}: {error.message}\n")
        return 2
    except FixtureError as error:
        sys.stderr.write(f"{error.code}: {error.message}\n")
        return 1
    except Exception:
        # 不输出 traceback（可能携带 SQL 参数／DSN／指导正文等敏感内容）。
        sys.stderr.write(f"{ERR_UNEXPECTED}: {MESSAGE_UNEXPECTED}\n")
        return 1
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
