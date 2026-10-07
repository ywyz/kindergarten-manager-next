"""AI 1C 夹具工具 — 真实 MySQL 8.4/InnoDB 集成测试（一次性库）。

2026-10-07 补修（对齐复审报告与补修提示词）：

* 拒绝矩阵只用真实旧 expected（合法 v2→v3 在成功场景断言）；
* ``BACKEND_ROOT`` 在本文件明确定义；CLI 子进程以确定 cwd 与
  backend/.venv 解释器运行，并带有限超时；
* JSON 列全部经 ORM 读出解码；map 断言不依赖对象键序，仅
  guidance_fields 作为有序数组比较；
* head 断言核对全部保护列（required／last_seen／last_rejected），且与
  种子值和发布前快照一致；
* SQL 写失败错误契约与超长 ID 故障注入一致（核心转换为固定去敏码；
  原始异常不进入输出）；
* 线程生命周期：有限超时、确认退出、异常收集；清理在退出后进行；
* 新增真实竞争：工具发布与既有产品 ``prompt_service.update_default``
  在同任务 v1 锚点争用（合法身份／会话由 seed 提供、版本基线现场读
  取、屏障同步、完成时间线记录），不改产品服务；
* 新增高 default revision 基线场景：v2/v3 从全历史 MAX+1 延续
  （不是简单 1→2→3 编号）；
* 全局规范化快照断言：个人完整文字／head／accounts／sessions／
  school_settings／operation_records／prompt_change_records／其他任务
  与合成业务记录；保留第二份写失败、后置失败与旧 expected 拒绝的
  零增量断言。

2026-10-07 第二轮集中补修（ai-slice1c-fixture-repair2-opencode-prompt-2026-10-07.md）：

* S4：同 expected 双发布者只校验拒绝方的错误码，成功方结果另行单独
  校验（此前把成功方的 ``code=None`` 一起收集进错误码集合）。
* S5：保护断言与审计断言分离（guard 纯函数：工具发布成功不写审计；
  真实管理员发布成功合法追加且仅追加审计；非法额外写入一律失败）。
* S6：不再用"屏障放行间隔"或"输家函数返回晚于赢家函数返回"的时间
  推定锁竞争。锚点竞争由真实 MySQL 行锁本身证明：
  * 受控锁持有／释放——控制连接真实持有 v1 锚点排他锁（SELECT …
    FOR UPDATE），竞争线程在锁等待窗口内以最短
    ``innodb_lock_wait_timeout`` 被锁管理器自身确定拒绝，受控持有
    期间零增量；释放后同一 expected 成功，证明拒绝只依赖锚点锁；
  * 工具胜出与产品胜出分别用两条确定性方向覆盖（按动作断言审计；
    不用时间推定胜负）；
  * 真实的同锚点同时争用保留（双发布者／工具×产品），赢家身份由
    锁顺序自然决定，不计时间。产品竞争会话使用实际 API 的
    ``expire_on_commit=False``；
  * 所有工作线程有限 join 并确认退出后才允许恢复库；任一线程未退
    出时 tearDownClass 跳过 reset，不在活跃线程运行时删除其数据。
* 新增离线检查类（不连接数据库；SQLite 内存离线单元证据）：覆盖
  ``make_engine`` 接入顺序、真实种子与 ``world_state`` 的 Row／实体
  结果形状、无行分支、以及 S4/S5 断言语义（两种合法胜负＋非法额外
  写入）。它们只发现以上确定性运行错误，不替代真库锁／回滚验证。

资源契约：仅在 ``AI1C_TEST_ALLOW_PREPARE=yes`` 与
``AI1C_TEST_DATABASE_URL`` 精确指向 127.0.0.1:13387
``kindergarten_test_ai1c_fixture`` 时启用；guard 在任何测试连接与迁移
之前生效；绝不指向远程验收库。环境不具备时真库用例整体 skip，并在
报告登记真库受阻，不宣称真库通过；离线检查类不受 skip 影响。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import unittest
from datetime import timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "scripts"))
sys.path.insert(0, str(BACKEND_ROOT / "tests" / "integration"))

from tests.integration.ai1c_guard import (  # noqa: E402
    ADMIN_ACCOUNT,
    ADMIN_SESSION_ID,
    INTEGRATION_URL,
    TEACHER_ACCOUNT,
    assert_audits_unchanged,
    assert_product_audit_append_legal,
    assert_protected_state_untouched,
    changed_keys,
    ensure_migration_head,
    make_engine,
    reset_prompt_tables,
    seed_v1_world,
    skip_unless_enabled,
    venv_python,
    world_state,
)

import tests.integration.ai1c_guard as ai1c_guard_module  # noqa: E402,F811

from sqlalchemy import insert, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from unittest import mock  # noqa: E402

import ai1c_acceptance_fixture as fixture  # noqa: E402
from app import security  # noqa: E402,F401
from app.models import (  # noqa: E402
    PromptContractVersion,
    PromptDefaultVersion,
)
from app.services import auth_service  # noqa: E402
from app.services import prompt_service  # noqa: E402
from app.services import ai_prompt_registry  # noqa: E402

TASK = "daily_lesson_split"

V2_FIELDS = [
    "theme",
    "objectives",
    "key_points",
    "difficult_points",
    "process",
    "acceptance_support",
]
V3_FIELDS = [
    "theme",
    "objectives",
    "key_points",
    "difficult_points",
    "acceptance_support",
]

# 种子确定的 head 五个保护列（R2d：与查询列一致）。
SEEDED_HEAD = (1, "current", None, 1, None)
# 高修订基线场景的任务全历史最新修订（本测试独占种子构造）。
HIGH_BASE_REVISION = 42

_admin_snapshot = auth_service.AuthSnapshot(
    account_id=ADMIN_ACCOUNT,
    role="admin",
    auth_version=1,
    session_id=ADMIN_SESSION_ID,
    is_active=True,
    password_hash="not-a-real-hash",
)


def _daily_rows(engine) -> dict:
    """daily_lesson_split 契约／默认（ORM 读出，JSON 已解码）。"""
    with Session(engine, future=True) as session:
        contracts = session.execute(
            select(
                PromptContractVersion.contract_version,
                PromptContractVersion.guidance_fields,
                PromptContractVersion.input_vars,
                PromptContractVersion.output_schema,
                PromptContractVersion.created_by,
            )
            .where(PromptContractVersion.task_type == TASK)
            .order_by(PromptContractVersion.contract_version)
        ).all()
        defaults = session.execute(
            select(
                PromptDefaultVersion.default_revision,
                PromptDefaultVersion.contract_version,
                PromptDefaultVersion.guidance_map,
                PromptDefaultVersion.created_by,
            )
            .where(PromptDefaultVersion.task_type == TASK)
            .order_by(PromptDefaultVersion.default_revision)
        ).all()
    return {
        "contracts": [tuple(c) for c in contracts],
        "defaults": [tuple(d) for d in defaults],
    }


def _task_wide_max_revision(engine) -> int:
    """该任务全历史最新默认修订（现场读取，不硬编码）。"""
    with Session(engine, future=True) as session:
        return int(
            session.execute(
                select(PromptDefaultVersion.default_revision)
                .where(PromptDefaultVersion.task_type == TASK)
                .order_by(PromptDefaultVersion.default_revision.desc())
                .limit(1)
            ).scalar_one()
        )


def _mysql_error_code(error: Exception) -> int | None:
    """从数据库驱动异常中提取 MySQL 错误号（用于锁等待证明）。"""
    orig = getattr(error, "orig", None)
    args = getattr(orig, "args", ())
    if args and isinstance(args[0], int):
        return int(args[0])
    return None


@skip_unless_enabled
class FixtureIntegrationTests(unittest.TestCase):
    """真实 MySQL 覆盖（v2/v3 原子成功／零增量拒绝／回滚／锁争用）。"""

    @classmethod
    def setUpClass(cls):
        cls.engine = make_engine()
        with cls.engine.connect() as connection:
            version = connection.execute(text("SELECT VERSION()")).scalar()
            engine_row = connection.execute(
                text("SHOW VARIABLES LIKE 'default_storage_engine'")
            ).fetchone()
        if not str(version).startswith("8.4"):
            raise AssertionError(f"integration requires MySQL 8.4, found {version}")
        if not engine_row or str(engine_row[1].lower()) != "innodb":
            raise AssertionError("integration requires InnoDB")
        ensure_migration_head(cls.engine)

    @classmethod
    def tearDownClass(cls):
        # S6：先给任何仍在运行的线程一次有限退出的机会；只有所有线程
        # 都确实退出后，才允许恢复库内容并关闭引擎。绝不在活跃线程
        # 运行时删除它们的数据。
        leftover = bool(
            cls._join_class_threads_before_teardown()
        )
        engine = getattr(cls, "engine", None)
        if engine is None:
            return
        try:
            if not leftover:
                # 恢复干净夹具世界（仅本一次性精确库）。
                reset_prompt_tables(engine)
                seed_v1_world(engine)
            else:
                sys.stderr.write(
                    "AI1C fixture: skipping teardown reset; worker threads"
                    " did not exit cleanly.\n"
                )
        finally:
            engine.dispose()

    @classmethod
    def _join_class_threads_before_teardown(cls) -> int:
        """有限 join 所有登记的工作线程；返回仍未退出的线程数。"""
        leftover = 0
        for thread in getattr(cls, "_threads", []):
            if thread.is_alive():
                thread.join(timeout=30)
            if thread.is_alive():
                leftover += 1
        return leftover

    def _register_thread(self, thread: threading.Thread) -> None:
        """登记工作线程，供 tearDownClass 做退出确认。"""
        threads = getattr(type(self), "_threads", None)
        if threads is None:
            threads = []
            type(self)._threads = threads
        threads.append(thread)

    def setUp(self):
        # 进入本测试时，上一个测试的线程必须都已退出（每个测试自己
        # 保证 join），否则拒绝继续覆盖夹具世界。
        leftover = type(self)._join_class_threads_before_teardown()
        self.assertEqual(leftover, 0, "上一测试的工作线程未全部退出")
        reset_prompt_tables(self.engine)
        seed_v1_world(self.engine)
        self.before = world_state(self.engine)

    # ------------------------------------------------------------ helpers

    def _publish(self, target_version: int, expected_contract: int,
                 expected_default: int) -> dict:
        with Session(self.engine, future=True) as session:
            return fixture.run_publish(
                session,
                target_contract_version=target_version,
                expected_contract_version=expected_contract,
                expected_default_revision=expected_default,
            )

    def _product_update_default(self, patch: dict, expected_default: int):
        """真实产品发布路径（合法管理员身份＋实际 API 会话设置）。

        S6：产品竞争/发布会话使用 ``expire_on_commit=False``，与实际
        API（app/database.py SessionLocal 两个分支）一致。
        """
        with Session(self.engine, future=True, expire_on_commit=False) as session:
            return prompt_service.update_default(
                session,
                _admin_snapshot,
                TASK,
                patch,
                expected_default_revision=expected_default,
            )

    def _tool_publish_assertions(self, before: dict, after: dict) -> None:
        """工具发布成功（或拒绝后）应有的完整状态语义（S5）。"""
        assert_protected_state_untouched(before, after, rationale="工具发布")
        # 工具发布不写审计；拒绝时的非法额外写入同样不允许。
        assert_audits_unchanged(before, after, rationale="工具发布")

    def _product_publish_assertions(
        self,
        before: dict,
        after: dict,
        *,
        changed_fields: tuple,
    ) -> None:
        """产品管理员发布成功的完整状态语义（S5）：合法追加审计。"""
        assert_protected_state_untouched(before, after, rationale="产品发布")
        added = assert_product_audit_append_legal(
            before,
            after,
            task_type=TASK,
            changed_fields=list(changed_fields),
            rationale="产品发布",
        )
        operation = added["operations"]
        change_record = added["change_records"]
        # 审计增量恰好伴随一次合法的默认修订追加（MAX+1 由调用方核对）。
        self.assertEqual(change_record[3], "default_update")
        self.assertEqual(operation[3], "prompt_default_update")

    def _seed_high_baseline(self, revision: int) -> None:
        """构造已有较高 default revision 的合法 v1 契约默认行。"""
        with Session(self.engine, future=True) as session:
            contract_row = session.execute(
                select(PromptContractVersion)
                .where(
                    PromptContractVersion.task_type == TASK,
                    PromptContractVersion.contract_version == 1,
                )
            ).scalar_one()
            mapping = {
                field: f"AI1C-FIXTURE-ADMIN-v1-{field}-r{revision}"
                for field in list(contract_row.guidance_fields)
            }
            session.execute(
                insert(PromptDefaultVersion),
                [dict(
                    id=security.generate_id(),
                    task_type=TASK,
                    default_revision=revision,
                    contract_version=1,
                    guidance_map=mapping,
                    created_by=ADMIN_ACCOUNT,
                    created_at=(
                        auth_service.utc_now() + timedelta(hours=1)
                    ),
                )],
            )
            session.commit()

    # ------------------------------------------------------------- tests

    def test_publish_v2_success_is_atomic(self):
        result = self._publish(2, 1, 1)
        self.assertEqual(result["status"], "published")
        self.assertEqual(result["task_type"], TASK)
        self.assertEqual(result["old_contract_version"], 1)
        self.assertEqual(result["new_contract_version"], 2)
        self.assertEqual(result["old_default_revision"], 1)
        self.assertEqual(result["new_default_revision"], 2)
        self.assertEqual(result["fields"], V2_FIELDS)

        after = world_state(self.engine)
        # 除 daily 契约／默认全文之外，一切不变（个人完整文字／head 保护
        # 列／accounts／sessions／school_settings／审计／其他任务）。
        self.assertEqual(
            changed_keys(self.before, after),
            {"contracts_daily", "defaults_daily"},
        )
        # S5：工具发布成功明确不写审计（与保护断言分离的单项校验）。
        self._tool_publish_assertions(self.before, after)
        rows = _daily_rows(self.engine)
        self.assertEqual([row[0] for row in rows["contracts"]], [1, 2])
        self.assertEqual(list(rows["contracts"][1][1]), V2_FIELDS)
        self.assertIsNone(rows["contracts"][1][4])  # created_by NULL
        self.assertEqual([row[0] for row in rows["defaults"]], [1, 2])
        self.assertEqual(rows["defaults"][1][1], 2)  # 链到契约 v2
        # R2c：map 直接与 recipe_guidance_map(2) 全量 dict 相等比较
        # （不依赖键序）；字段间值互换会被该断言拒绝，不再允许仅凭
        # 键集合／值集合一致的弱对应通过。
        self.assertEqual(
            rows["defaults"][1][2], fixture.recipe_guidance_map(2)
        )
        self.assertIsNone(rows["defaults"][1][3])
        # input_vars / output_schema 从上一契约快照原样复制。
        self.assertEqual(rows["contracts"][0][2], rows["contracts"][1][2])
        self.assertEqual(rows["contracts"][0][3], rows["contracts"][1][3])
        # R2d：head 五个保护列与种子及发布前快照一致。
        self.assertEqual(
            after["heads"][f"{TEACHER_ACCOUNT}:{TASK}"],
            SEEDED_HEAD,
        )
        self.assertEqual(
            self.before["heads"][f"{TEACHER_ACCOUNT}:{TASK}"],
            SEEDED_HEAD,
        )
        # 个人完整文字（种子为完整六字段合成 map）未被触碰。
        seeded_personal_map = self.before["personal_versions"][
            (TEACHER_ACCOUNT, TASK, 1)
        ]
        self.assertEqual(
            sorted(seeded_personal_map),
            sorted(fixture.V1_FIELDS),
        )
        self.assertEqual(
            after["personal_versions"],
            self.before["personal_versions"],
        )

    # ------------------------------------------------------ 锁竞争基础

    def _hold_anchor_lock(self):
        """受控锁持有（S6）：真实持有 v1 锚点排他行锁，不伪造。

        用独立控制连接执行真实 ``SELECT … FOR UPDATE``（SQLAlchemy 2 的
        ``RootTransaction`` 只负责事务生命周期、不提供 execute，因此锁
        查询必须在连接上执行）并保持事务打开；这是与发布路径完全相同
        的真实 MySQL 行锁。返回 (engine, connection, transaction)，由
        ``_release_anchor_lock`` 只读释放。

        取得连接／begin／执行锁查询任一步失败时，函数在此处清理其已
        取得的资源（rollback／close／dispose，逆序、best-effort），再把
        原始错误原样抛出——调用方尚未拿到返回三元组，不能依赖其
        finally 清理。
        """
        control_engine = make_engine()
        control_connection = None
        control_tx = None
        try:
            control_connection = control_engine.connect()
            control_tx = control_connection.begin()
            # 真实锁（不以事件或替身代替 MySQL 行锁）：本行即发布路径
            # 取得的同一 v1 锚点排他锁；在连接上执行，事务只做 rollback。
            control_connection.execute(
                select(PromptContractVersion)
                .where(
                    PromptContractVersion.task_type == TASK,
                    PromptContractVersion.contract_version == 1,
                )
                .with_for_update()
            )
        except Exception as original_error:
            # 每个已取得资源的清理都必须尝试（rollback／close／dispose
            # 逆序）；任一清理失败在原异常上以固定步骤名 add_note 记录
            #（不含异常原文），不替换、不掩盖原始错误，最后原样抛出。
            if control_tx is not None:
                try:
                    control_tx.rollback()
                except Exception:
                    original_error.add_note(
                        "AI1C fixture: anchor-lock cleanup step failed:"
                        " tx.rollback"
                    )
            if control_connection is not None:
                try:
                    control_connection.close()
                except Exception:
                    original_error.add_note(
                        "AI1C fixture: anchor-lock cleanup step failed:"
                        " connection.close"
                    )
            try:
                control_engine.dispose()
            except Exception:
                original_error.add_note(
                    "AI1C fixture: anchor-lock cleanup step failed:"
                    " engine.dispose"
                )
            raise
        return control_engine, control_connection, control_tx

    def _release_anchor_lock(self, engine, connection, transaction) -> None:
        """纯资源释放（T2）：只负责 rollback、close、dispose。

        不读业务数据、不假定发布成功、不引用任何 after 快照、不执行
        发布断言。三个清理步骤各自独立 try、全部尝试，不因单步失败
        跳过后续步骤。失败步骤名以固定去敏文本（只含步骤名，不含异
        常原文）处理：

        * 入口用 ``sys.exc_info()[1]`` 取调用方活动异常（例如测试体
          已有原始失败、本函数在 finally 中被调用）：失败步骤名
          ``add_note`` 到原异常上后正常 return——不掩盖、不替换原
          错，原错继续向外传播，清理失败同时可经 note 诊断；
        * 无活动异常时（单独清理调用），失败步骤以固定去敏文本抛出
          ``RuntimeError``（``from None``），不静默通过。
        无失败步骤时正常返回；调用方在本函数返回后自行断言真实状态。
        """
        original_error = sys.exc_info()[1]
        failed_steps = []
        try:
            transaction.rollback()
        except Exception:
            failed_steps.append("tx.rollback")
        try:
            connection.close()
        except Exception:
            failed_steps.append("connection.close")
        try:
            engine.dispose()
        except Exception:
            failed_steps.append("engine.dispose")
        if not failed_steps:
            return
        if original_error is not None:
            for step in failed_steps:
                original_error.add_note(
                    f"AI1C fixture: anchor-lock cleanup step failed: {step}"
                )
            return
        raise RuntimeError(
            "AI1C fixture: anchor-lock cleanup step failed: "
            + ", ".join(failed_steps)
        ) from None

    def test_publish_v3_after_high_revision_continues_max_plus_1(self):
        """构造较高默认修订基线后发布：默认修订从全历史 MAX+1 延续。"""
        self._seed_high_baseline(HIGH_BASE_REVISION)
        baseline = _task_wide_max_revision(self.engine)
        self.assertEqual(baseline, HIGH_BASE_REVISION)
        before = world_state(self.engine)

        result_v2 = self._publish(2, 1, HIGH_BASE_REVISION)
        self.assertEqual(result_v2["status"], "published")
        self.assertEqual(result_v2["old_default_revision"], HIGH_BASE_REVISION)
        self.assertEqual(
            result_v2["new_default_revision"], HIGH_BASE_REVISION + 1
        )
        after_v2 = world_state(self.engine)
        self.assertEqual(
            changed_keys(before, after_v2),
            {"contracts_daily", "defaults_daily"},
        )

        result_v3 = self._publish(
            3, 2, HIGH_BASE_REVISION + 1
        )
        self.assertEqual(result_v3["status"], "published")
        self.assertEqual(
            result_v3["new_default_revision"], HIGH_BASE_REVISION + 2
        )
        after_v3 = world_state(self.engine)
        self.assertEqual(
            changed_keys(after_v2, after_v3),
            {"contracts_daily", "defaults_daily"},
        )
        rows = _daily_rows(self.engine)
        self.assertEqual(
            [row[0] for row in rows["contracts"]], [1, 2, 3]
        )
        self.assertEqual(
            [row[0] for row in rows["defaults"]],
            [1, HIGH_BASE_REVISION, HIGH_BASE_REVISION + 1,
             HIGH_BASE_REVISION + 2],
        )
        self.assertEqual(list(rows["contracts"][2][1]), V3_FIELDS)
        self.assertEqual(
            sorted(rows["defaults"][3][2]), sorted(V3_FIELDS)
        )
        # 只有工具发布发生：保护状态与审计都必须保持不变（S5 分离断言）。
        self._tool_publish_assertions(before, after_v3)

    def test_repeats_and_stale_expected_refused_with_zero_increments(self):
        """拒绝矩阵只用真实旧 expected；合法 v2→v3 在成功场景断言。"""
        self._publish(2, 1, 1)
        baseline = world_state(self.engine)
        # 当前状态：最新契约 v2、全历史最新默认 r2。
        # 注意顺序判定（v1→v2、v2→v3）先于 expected 校验。
        for case, expected_code in (
            # 重复 publish-v2：契约 v2 已存在，(2→2) 顺序不允许。
            ((2, 1, 1), fixture.ERR_TRANSITION_REFUSED),
            # 同上：顺序拒绝不受 expected 取值影响。
            ((2, 1, 2), fixture.ERR_TRANSITION_REFUSED),
            # 旧契约 expected（v1 已被 v2 取代，而 2→3 合法）：
            # expected 契约必须等于当前最新契约 → 拒绝。
            ((3, 1, 2), fixture.ERR_EXPECTED_MISMATCH),
            # 契约 expected 正确但旧默认 expected（r1 已被 r2 取代）→ 拒绝。
            ((3, 2, 1), fixture.ERR_EXPECTED_MISMATCH),
        ):
            with self.assertRaises(fixture.FixtureError) as caught:
                self._publish(*case)
            self.assertEqual(caught.exception.code, expected_code)
            self.assertEqual(
                world_state(self.engine), baseline,
                f"拒绝后必须零增量（case={case}）",
            )

    def test_post_verify_failure_rolls_back(self):
        with mock.patch.object(
            fixture,
            "_post_verify",
            side_effect=fixture.FixtureError(
                fixture.ERR_POST_VERIFY_FAILED,
                fixture.MESSAGE_POST_VERIFY_FAILED,
            ),
        ):
            with self.assertRaises(fixture.FixtureError) as caught:
                self._publish(2, 1, 1)
        self.assertEqual(caught.exception.code, fixture.ERR_POST_VERIFY_FAILED)
        after = world_state(self.engine)
        # 后置失败发生在提交前：防整库零增量；工具路径也不允许写审计
        # （S5：拒绝路径审计零增量，保护状态同样未变）。
        self.assertEqual(changed_keys(self.before, after), set())
        self._tool_publish_assertions(self.before, after)

    def test_second_insert_failure_rolls_back_both_rows(self):
        """第二份插入失败时 contract/default 一起回滚（真实 MySQL 事务）。

        注入：为默认行生成一个超长 ID（varchar(32) 拒绝），模拟真实
        写失败。核心错误契约：提交前的写失败被转换为固定去敏码
        ``AI1C_DB_OPERATIONAL``，事务确定回滚，零增量；原始异常／SQL
        参数不进入 FixtureError 的固定输出。
        """
        calls = {"n": 0}
        real_generate_id = security.generate_id

        def _fail_default_id():
            calls["n"] += 1
            if calls["n"] == 1:
                return real_generate_id()
            return "X" * 80

        with mock.patch.object(security, "generate_id", new=_fail_default_id):
            with self.assertRaises(fixture.FixtureError) as caught:
                self._publish(2, 1, 1)
        # 错误契约：核心把该真实 SQL 写失败固定转换为同一个去敏码。
        self.assertEqual(caught.exception.code, fixture.ERR_DB_OPERATIONAL)
        self.assertEqual(
            caught.exception.message, fixture.MESSAGE_DB_OPERATIONAL
        )
        self.assertEqual(calls["n"], 2)
        after = world_state(self.engine)
        self.assertEqual(changed_keys(self.before, after), set())
        rows = _daily_rows(self.engine)
        self.assertEqual([row[0] for row in rows["contracts"]], [1])
        self.assertEqual([row[0] for row in rows["defaults"]], [1])
        self._tool_publish_assertions(self.before, after)

    def test_concurrent_publishers_same_expected_at_most_one_success(self):
        """同 expected 并发：anchor FOR UPDATE 顺序化，至多一个成功。

        真实竞争证据（S6）：双方经屏障同时放行，真实争用同一 v1 锚点
        排他行锁；胜者在临界区内提交完成才释放锚点，败者随后在锁内的
        锁定读（当前读，不是快照读）中看到胜者已提交的新状态。拒绝由
        结果数据本身证明：败者看到契约已是 v2，（v2→v2）顺序判定即
        拒绝，不使用时刻或间隔推定。
        """
        results = {}
        thread_errors = []
        barrier = threading.Barrier(2)

        def _publisher(name: str):
            engine = None
            try:
                engine = make_engine()
                with Session(engine, future=True) as session:
                    session.execute(
                        text(
                            "SELECT COUNT(*) FROM prompt_default_versions "
                            "WHERE task_type = :t"
                        ),
                        {"t": TASK},
                    )
                    barrier.wait(timeout=15)
                    try:
                        fixture.run_publish(session, 2, 1, 1)
                        results[name] = {"status": "success"}
                    except fixture.FixtureError as error:
                        results[name] = {
                            "status": "refused", "code": error.code,
                        }
            except Exception as error:  # 收集线程异常（不含原始细节）
                thread_errors.append((name, type(error).__name__))
            finally:
                if engine is not None:
                    engine.dispose()

        threads = [
            threading.Thread(target=_publisher, args=(f"publisher-{n}",))
            for n in (1, 2)
        ]
        for thread in threads:
            self._register_thread(thread)
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
            self.assertFalse(
                thread.is_alive(), "工作线程未在有限超时内退出"
            )
        self.assertEqual(thread_errors, [])
        # S4：同 expected 下至多一方成功。错误码集合只来自拒绝方；
        # 成功方结果另行单独校验（成功方没有 code，不能混进来）。
        successes = [
            record for record in results.values()
            if record["status"] == "success"
        ]
        refusals = [
            record for record in results.values()
            if record["status"] == "refused"
        ]
        self.assertEqual(len(results), 2)
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(refusals), 1)
        # 败者拒绝码确定：它先被锚点锁序列化到胜者提交之后，锁定读必
        # 然看到/latest 契约 v2，（v2→v2）顺序判定即拒绝。
        self.assertEqual(
            refusals[0]["code"], fixture.ERR_TRANSITION_REFUSED
        )
        # 成功方另行校验（恰好发布 v2/r2 一次）。
        rows = _daily_rows(self.engine)
        self.assertEqual([row[0] for row in rows["contracts"]], [1, 2])
        self.assertEqual([row[0] for row in rows["defaults"]], [1, 2])
        # S5：胜者也是工具发布——不写审计，保护状态完全未变。
        after = world_state(self.engine)
        self.assertEqual(
            changed_keys(self.before, after),
            {"contracts_daily", "defaults_daily"},
        )
        self._tool_publish_assertions(self.before, after)

    def test_anchor_lock_blocks_tool_publish_until_holder_releases(self):
        """受控锁持有／释放（S6）：真实 MySQL 锚点排他锁阻塞工具发布。

        控制连接真实持有 v1 锚点排他行锁（SELECT … FOR UPDATE，不伪造
        也不改产品实现）。竞争线程进入发布临界区前必须先取得该行锁：
        持有窗口内它以最短 ``innodb_lock_wait_timeout`` 被 MySQL 锁管理
        器自身确定拒绝（锁等待超时错误，非时间推定），持有期间零增量；
        释放后同一 expected 立即成功，证明拒绝只依赖这一把锚点锁。
        """
        control_engine, control_connection, control_tx = (
            self._hold_anchor_lock()
        )
        try:
            outcome = {}

            def _blocked_publisher():
                engine = None
                try:
                    engine = make_engine()
                    with Session(engine, future=True) as session:
                        session.execute(
                            text("SET SESSION innodb_lock_wait_timeout = 2")
                        )
                        outcome["phase"] = "attempting"
                        outcome["attempting"] = True
                        try:
                            fixture.run_publish(session, 2, 1, 1)
                            outcome["status"] = "success"
                        except fixture.FixtureError as error:
                            outcome["status"] = "refused"
                            outcome["code"] = error.code
                except Exception as error:  # 收集线程异常（不含原始细节）
                    outcome["thread_error"] = type(error).__name__
                finally:
                    outcome["phase"] = "exited"
                    if engine is not None:
                        engine.dispose()

            thread = threading.Thread(
                target=_blocked_publisher, name="tool-blocked-publish"
            )
            self._register_thread(thread)
            thread.start()
            thread.join(timeout=60)
            self.assertFalse(thread.is_alive(), "工作线程未在有限超时内退出")
            self.assertEqual(outcome.get("phase"), "exited")
            self.assertNotIn("thread_error", outcome)
            # 阶段事件：竞争线程确实到达发布尝试。持有窗口内它无法进入
            # 受保护临界区——其失败原因是 MySQL 锁管理器自身的锚点行锁
            # 等待超时（不是时间推定），且持有期间零增量。
            self.assertTrue(outcome.get("attempting", False))
            self.assertEqual(outcome.get("status"), "refused")
            self.assertEqual(outcome.get("code"), fixture.ERR_DB_OPERATIONAL)
            # 持有窗口内零增量：保护状态与审计都完全未变。
            self.assertEqual(world_state(self.engine), self.before)
        finally:
            self._release_anchor_lock(
                control_engine, control_connection, control_tx
            )
        # 释放后：同一 expected 的发布成功——拒绝只依赖锚点锁的持有。
        result = self._publish(2, 1, 1)
        self.assertEqual(result["status"], "published")
        rows = _daily_rows(self.engine)
        self.assertEqual([row[0] for row in rows["contracts"]], [1, 2])
        self.assertEqual([row[0] for row in rows["defaults"]], [1, 2])
        after = world_state(self.engine)
        self.assertEqual(
            changed_keys(self.before, after),
            {"contracts_daily", "defaults_daily"},
        )
        self._tool_publish_assertions(self.before, after)

    def test_anchor_lock_blocks_product_update_default_until_released(self):
        """受控锁持有／释放（S6）：真实锚点锁同样阻塞产品管理发布。

        产品侧使用实际 API 的会话口径（``expire_on_commit=False``）与
        合法管理员身份；持有窗口内 product update_default 在锚点
        FOR UPDATE 处被锁管理器确定拒绝（MySQL 1205 锁等待超时），
        零增量；释放后同一 expected 成功并合法追加审计。
        """
        control_engine, control_connection, control_tx = (
            self._hold_anchor_lock()
        )
        try:
            outcome = {}

            def _blocked_product_update():
                engine = None
                try:
                    engine = make_engine()
                    with Session(
                        engine, future=True, expire_on_commit=False
                    ) as session:
                        session.execute(
                            text("SET SESSION innodb_lock_wait_timeout = 2")
                        )
                        outcome["phase"] = "attempting"
                        outcome["attempting"] = True
                        try:
                            prompt_service.update_default(
                                session,
                                _admin_snapshot,
                                TASK,
                                {
                                    "theme":
                                    "AI1C-FIXTURE-ADMIN-EDIT-blocked-theme"
                                },
                                expected_default_revision=1,
                            )
                            outcome["status"] = "success"
                        except Exception as error:
                            outcome["status"] = "refused"
                            outcome["error_class"] = type(error).__name__
                            outcome["error_code"] = _mysql_error_code(error)
                except Exception as error:  # 收集线程异常（不含原始细节）
                    outcome["thread_error"] = type(error).__name__
                finally:
                    outcome["phase"] = "exited"
                    if engine is not None:
                        engine.dispose()

            thread = threading.Thread(
                target=_blocked_product_update, name="product-blocked-default"
            )
            self._register_thread(thread)
            thread.start()
            thread.join(timeout=60)
            self.assertFalse(thread.is_alive(), "工作线程未在有限超时内退出")
            self.assertEqual(outcome.get("phase"), "exited")
            self.assertNotIn("thread_error", outcome)
            # 阶段事件：产品竞争线程确实到达发布尝试；其失败原因是
            # MySQL 锁管理器自身的 1205 锁等待超时。
            self.assertTrue(outcome.get("attempting", False))
            self.assertEqual(outcome.get("status"), "refused")
            # MySQL 锁管理器自身的 1205 锁等待超时：确实是等在被持有的
            # 锚点行锁上，而不是其他失败原因。
            self.assertEqual(outcome.get("error_code"), 1205)
            # 持有窗口内零增量：保护状态与审计都完全未变。
            self.assertEqual(world_state(self.engine), self.before)
        finally:
            self._release_anchor_lock(
                control_engine, control_connection, control_tx
            )
        # 释放后：同一 expected 的产品发布成功并合法追加审计（S5）。
        self._product_update_default(
            {"theme": "AI1C-FIXTURE-ADMIN-EDIT-released-theme"}, 1
        )
        after = world_state(self.engine)
        self.assertEqual(
            changed_keys(self.before, after),
            {"defaults_daily", "operations", "change_records"},
        )
        rows = _daily_rows(self.engine)
        self.assertEqual([row[0] for row in rows["contracts"]], [1])
        self.assertEqual([row[0] for row in rows["defaults"]], [1, 2])
        self._product_publish_assertions(
            self.before, after, changed_fields=("theme",)
        )

    def test_tool_and_product_race_same_anchor_at_most_one_wins(self):
        """工具×产品真实同锚点争用（屏障同时放行；不使用时间推定）。

        两个竞争方都以合法身份与真实 expected 放行并争用同一 v1 锚点
        排他行锁；胜者身份由锁顺序自然决定，全部断言按实际胜负落点：
        至多一方成功；败者在胜者提交后的锁定读中被确定拒绝；审计按
        动作判定（工具发布不写审计；产品发布合法追加）。任何时序无
        关的间隔或完成时刻都不进入断言。
        """
        with Session(self.engine, future=True) as session:
            baseline_revision = int(
                session.execute(
                    select(PromptDefaultVersion.default_revision)
                    .where(PromptDefaultVersion.task_type == TASK)
                    .order_by(PromptDefaultVersion.default_revision.desc())
                    .limit(1)
                ).scalar_one()
            )
        self.assertEqual(baseline_revision, 1)

        barrier = threading.Barrier(2)
        results = {"tool": {}, "product": {}}
        thread_errors = []

        def _tool_thread():
            engine = None
            try:
                engine = make_engine()
                with Session(engine, future=True) as session:
                    session.execute(
                        text(
                            "SELECT COUNT(*) FROM prompt_default_versions "
                            "WHERE task_type = :t"
                        ),
                        {"t": TASK},
                    )
                    barrier.wait(timeout=15)
                    try:
                        fixture.run_publish(
                            session,
                            target_contract_version=2,
                            expected_contract_version=1,
                            expected_default_revision=baseline_revision,
                        )
                        results["tool"] = {"status": "success"}
                    except fixture.FixtureError as error:
                        results["tool"] = {
                            "status": "refused", "code": error.code,
                        }
            except Exception as error:  # 收集线程异常（不含原始细节）
                thread_errors.append(("tool", type(error).__name__))
            finally:
                if engine is not None:
                    engine.dispose()

        def _product_thread():
            engine = None
            try:
                engine = make_engine()
                # S6：产品竞争会话与实际 API 一致（expire_on_commit=False）。
                with Session(
                    engine, future=True, expire_on_commit=False
                ) as session:
                    session.execute(
                        text(
                            "SELECT COUNT(*) FROM prompt_default_versions "
                            "WHERE task_type = :t"
                        ),
                        {"t": TASK},
                    )
                    barrier.wait(timeout=15)
                    try:
                        prompt_service.update_default(
                            session,
                            _admin_snapshot,
                            TASK,
                            {"theme": "AI1C-FIXTURE-ADMIN-EDIT-race-theme"},
                            expected_default_revision=baseline_revision,
                        )
                        results["product"] = {"status": "success"}
                    except (
                        fixture.FixtureError,
                        auth_service.AuthServiceError,
                    ) as error:
                        results["product"] = {
                            "status": "refused",
                            "error_class": type(error).__name__,
                        }
            except Exception as error:  # 收集线程异常（不含原始细节）
                thread_errors.append(("product", type(error).__name__))
            finally:
                if engine is not None:
                    engine.dispose()

        threads = [
            threading.Thread(target=_tool_thread, name="tool-publish"),
            threading.Thread(
                target=_product_thread, name="product-update-default"
            ),
        ]
        for thread in threads:
            self._register_thread(thread)
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
            self.assertFalse(
                thread.is_alive(), "工作线程未在有限超时内退出"
            )
        self.assertEqual(thread_errors, [])
        # S4/S5：至多一方成功。错误码/错误类型只来自拒绝方；成功方结果
        # 另行校验。胜负由锚点锁顺序决定，任何合法胜负都必须满足：
        # MAX+1、保护状态未变、审计按动作判定。
        statuses = {
            name: record["status"] for name, record in results.items()
        }
        self.assertEqual(sorted(statuses.values()), ["refused", "success"])
        winner = next(
            name for name, status in statuses.items() if status == "success"
        )
        rows = _daily_rows(self.engine)
        after = world_state(self.engine)
        # 任务全历史 MAX+1：无论哪一方赢，新默认修订都是基线 MAX+1。
        self.assertEqual(
            [row[0] for row in rows["defaults"]], [1, baseline_revision + 1]
        )
        if winner == "tool":
            # 产品败者读到契约 v2／r2：expected 修订不再匹配 → 409。
            self.assertEqual(
                results["product"]["error_class"], "VersionConflict"
            )
            self.assertEqual(
                changed_keys(self.before, after),
                {"contracts_daily", "defaults_daily"},
            )
            self.assertEqual([row[0] for row in rows["contracts"]], [1, 2])
            # 工具发布胜出：审计零增量（S5）。
            self._tool_publish_assertions(self.before, after)
        else:
            # 工具败者读到任务全历史最新 r2：expected default 不再匹配。
            self.assertEqual(
                results["tool"]["code"], fixture.ERR_EXPECTED_MISMATCH
            )
            self.assertEqual(
                changed_keys(self.before, after),
                {"defaults_daily", "operations", "change_records"},
            )
            self.assertEqual([row[0] for row in rows["contracts"]], [1])
            # 产品赢家把 theme 改为合成标记文本：其余字段与上一个默认
            # 快照（种子 v1 全文）同名保留；审计合法追加（S5）。
            previous_map = dict(
                self.before["defaults_daily"][-1][2]
            )
            previous_map["theme"] = "AI1C-FIXTURE-ADMIN-EDIT-race-theme"
            latest_map = rows["defaults"][-1][2]
            self.assertEqual(latest_map, previous_map)
            self._product_publish_assertions(
                self.before, after, changed_fields=("theme",)
            )

    def test_tool_wins_product_refuses_with_stale_expected_deterministically(
        self,
    ):
        """方向一（确定性）：工具胜出，产品用旧 expected 被确定拒绝。

        工具先在真实锚点排他锁内提交 v2/r2；随后产品侧以旧的
        ``expected_default_revision=1`` 尝试。产品路径同样在真实锚点
        锁内执行锁定读：读到的提交状态（r2）使 expected 确定失配，
        VersionConflict 必然发生且零增量。不涉及任何时间推定。
        """
        result = self._publish(2, 1, 1)
        self.assertEqual(result["status"], "published")
        after_tool = world_state(self.engine)
        rows = _daily_rows(self.engine)
        self.assertEqual([row[0] for row in rows["contracts"]], [1, 2])
        self.assertEqual([row[0] for row in rows["defaults"]], [1, 2])
        self.assertEqual(
            changed_keys(self.before, after_tool),
            {"contracts_daily", "defaults_daily"},
        )
        self._tool_publish_assertions(self.before, after_tool)

        # 产品败方：同一锁内锁定读到 r2，expected=1 确定失配。
        with self.assertRaises(auth_service.VersionConflict):
            self._product_update_default(
                {"theme": "AI1C-FIXTURE-ADMIN-EDIT-lost-theme"}, 1
            )
        # 拒绝路径零增量：工具发布后的真实状态保持不变。
        self.assertEqual(world_state(self.engine), after_tool)

    def test_product_wins_tool_refuses_with_stale_expected_deterministically(
        self,
    ):
        """方向二（确定性）：产品胜出（含 MAX+1），工具用旧 expected 被
        确定拒绝。真实管理员发布把任务全历史最新默认推进到 r43（种下
        r42 基线，而不是 1→2→3）；工具随后以旧 expected=42 尝试 v2，
        在真实锚点锁内的锁定读读到 r43，expected 确定失配、零增量。
        """
        self._seed_high_baseline(HIGH_BASE_REVISION)
        baseline = _task_wide_max_revision(self.engine)
        self.assertEqual(baseline, HIGH_BASE_REVISION)
        before = world_state(self.engine)

        self._product_update_default(
            {
                "theme":
                f"AI1C-FIXTURE-ADMIN-EDIT-win-theme-r{HIGH_BASE_REVISION}"
            },
            HIGH_BASE_REVISION,
        )
        after_product = world_state(self.engine)
        rows = _daily_rows(self.engine)
        self.assertEqual([row[0] for row in rows["contracts"]], [1])
        self.assertEqual(
            [row[0] for row in rows["defaults"]],
            [1, HIGH_BASE_REVISION, HIGH_BASE_REVISION + 1],
        )
        self.assertEqual(
            changed_keys(before, after_product),
            {"defaults_daily", "operations", "change_records"},
        )
        self._product_publish_assertions(
            before, after_product, changed_fields=("theme",)
        )

        # 工具败方：expected default=42 已被 r43 取代 → 确定拒绝。
        with self.assertRaises(fixture.FixtureError) as caught:
            self._publish(2, 1, HIGH_BASE_REVISION)
        self.assertEqual(caught.exception.code, fixture.ERR_EXPECTED_MISMATCH)
        # 拒绝路径零增量。
        self.assertEqual(world_state(self.engine), after_product)

    def test_cli_subprocess_publish_end_to_end(self):
        """CLI 子进程：BACKEND_ROOT＋确定 cwd＋venv 解释器＋有限超时。"""
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in ("DATABASE_URL", "AI_MASTER_KEY", "AI_MASTER_KEY_ID")
        }
        env["APP_DISABLE_DOTENV"] = "1"
        env[fixture.DSN_ENV_VAR] = INTEGRATION_URL
        env[fixture.PUBLISH_SWITCH_VAR] = "yes"
        completed = subprocess.run(
            [
                venv_python(),
                str(BACKEND_ROOT / "scripts" / "ai1c_acceptance_fixture.py"),
                "--mode",
                "integration",
                "publish-v2",
                "--expected-contract-version",
                "1",
                "--expected-default-revision",
                "1",
            ],
            cwd=str(BACKEND_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "published")
        self.assertEqual(payload["new_contract_version"], 2)
        self.assertEqual(payload["new_default_revision"], 2)
        # CLI 输出去敏：不含 DSN／密钥变量值，无 traceback。
        self.assertNotIn(fixture.DSN_ENV_VAR, completed.stdout)
        self.assertNotIn(fixture.DSN_ENV_VAR, completed.stderr)
        self.assertNotIn(fixture.PUBLISH_SWITCH_VAR, completed.stdout)
        self.assertNotIn("Traceback", completed.stdout + completed.stderr)
        after = world_state(self.engine)
        self.assertEqual(
            changed_keys(self.before, after),
            {"contracts_daily", "defaults_daily"},
        )

    def test_registry_not_mutated_by_publish(self):
        before_fields = list(
            ai_prompt_registry.TASK_REGISTRY[TASK].guidance_defaults.keys()
        )
        before_defaults = dict(
            ai_prompt_registry.TASK_REGISTRY[TASK].guidance_defaults
        )
        self._publish(2, 1, 1)
        self._publish(3, 2, 2)
        after_fields = list(
            ai_prompt_registry.TASK_REGISTRY[TASK].guidance_defaults.keys()
        )
        after_defaults = dict(
            ai_prompt_registry.TASK_REGISTRY[TASK].guidance_defaults
        )
        self.assertEqual(before_fields, after_fields)
        self.assertEqual(before_defaults, after_defaults)

    def test_invariant_of_inspect_after_publishes(self):
        result = self._publish(2, 1, 1)
        self.assertEqual(result["status"], "published")
        with Session(self.engine, future=True) as session:
            report = fixture.inspect_fixture(session)
        self.assertEqual(report["task_type"], TASK)
        self.assertEqual(report["v1_anchor_present"], True)
        self.assertEqual(report["latest_contract_version"], 2)
        self.assertEqual(report["latest_default_revision"], 2)
        # inspect 不读取／输出默认指导全文：报告只有版本、字段名与状态。
        self.assertNotIn("guidance_map", report)
        self.assertNotIn("input_vars", report)
        self.assertNotIn("output_schema", report)

# ---------------------------------------------------------------------------
# 离线检查（不连接数据库；SQLite 内存离线单元证据）
#
# 目的：在真库资源不具备时，发现 S1–S5 这类确定性运行错误（调用时
# NameError、把 Row 当 ORM 实体读属性、断言把合法胜负判为失败）。
# 这些检查走真实执行路径（真实 SQLAlchemy Session、真实种子／快照
# 函数、真实断言纯函数），不是源代码字符串比对；它们只能证明"接入
# 数据库前即崩溃"的入口与断言语义本身成立，不能替代真库锁／回滚／
# 方言验证。
# ---------------------------------------------------------------------------


def _register_sqlite_native_adapters() -> None:
    """注册显式 datetime/date 适配器，消除 Python 3.12+ 的默认适配器
    DeprecationWarning（sqlite3 版 stdlib 变化；语义与默认适配器一致）。"""
    import datetime as datetime_module

    import sqlite3

    sqlite3.register_adapter(
        datetime_module.datetime,
        lambda value: value.isoformat(" "),
    )
    sqlite3.register_adapter(
        datetime_module.date,
        lambda value: value.isoformat(),
    )


def _offline_world_engine():
    """SQLite 内存引擎：仅建 seed／world_state 涉及的表。

    诚实边界：只能作为"SQLite 内存离线单元证据"，驱动与方言与 MySQL
    不同；不宣称 MySQL 验证。调用方必须在 finally／addCleanup 中
    dispose 引擎，避免遗留未关闭连接的 ResourceWarning。
    """
    from sqlalchemy import create_engine, event
    from app.models import (
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

    _register_sqlite_native_adapters()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    @event.listens_for(engine, "connect")
    def _register_unicode_collation(dbapi_connection, record):
        dbapi_connection.create_collation(
            "utf8mb4_bin", lambda a, b: (a > b) - (a < b)
        )

    for table in (
        Account.__table__,
        AccountSession.__table__,
        SchoolSettings.__table__,
        OperationRecord.__table__,
        PromptContractVersion.__table__,
        PromptDefaultVersion.__table__,
        PersonalPromptVersion.__table__,
        PersonalPromptHead.__table__,
        PromptChangeRecord.__table__,
    ):
        table.create(engine)
    return engine


class MakeEngineGuardOfflineTests(unittest.TestCase):
    """S1 离线替身：合法目标确实到达 engine 创建；非法目标先拒绝。

    替身替换 guard 模块的 ``create_engine`` 符号：只记录调用并返回
    占位对象，不建立任何连接；验证的是真实调用路径（make_engine 到
    创建入口这一步），而不是替身本身。
    """

    VALID_INTEGRATION_URL = (
        "mysql+pymysql://u:pw@127.0.0.1:13387/"
        "kindergarten_test_ai1c_fixture"
    )
    FORBIDDEN_TARGET_URL = (
        "mysql+pymysql://u:pw@127.0.0.1:13386/kg_next_i5_acceptance"
    )

    def test_make_engine_reaches_engine_creation_for_valid_target(self):
        calls = []

        def _stub(*args, **kwargs):
            calls.append((args, kwargs))
            return object()  # 占位对象；不建立任何连接

        original_create = ai1c_guard_module.create_engine
        original_url = ai1c_guard_module._DATABASE_URL
        ai1c_guard_module.create_engine = _stub
        ai1c_guard_module._DATABASE_URL = self.VALID_INTEGRATION_URL
        try:
            ai1c_guard_module.make_engine()
        finally:
            ai1c_guard_module.create_engine = original_create
            ai1c_guard_module._DATABASE_URL = original_url
        # 修复前：make_engine 一调用即 NameError（create_engine 未导入）；
        # 修复后：合法 integration 目标恰好到达一次创建入口，参数与
        # guard 白名单一致。
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        url = fixture.make_url(args[0])
        self.assertEqual(url.drivername, "mysql+pymysql")
        self.assertIn(url.host, ("127.0.0.1", "localhost"))
        self.assertEqual(url.port, 13387)
        self.assertEqual(url.database, "kindergarten_test_ai1c_fixture")
        self.assertIs(kwargs.get("poolclass"), NullPool)
        self.assertEqual(kwargs.get("isolation_level"), "REPEATABLE READ")

    def test_make_engine_refuses_invalid_target_before_engine(self):
        calls = []

        def _stub(*args, **kwargs):  # 不连接任何数据库
            calls.append(args)
            raise AssertionError("非法目标不应走到 engine 创建")

        original_create = ai1c_guard_module.create_engine
        original_url = ai1c_guard_module._DATABASE_URL
        ai1c_guard_module.create_engine = _stub
        ai1c_guard_module._DATABASE_URL = self.FORBIDDEN_TARGET_URL
        try:
            with self.assertRaises(fixture.FixtureGuardError):
                ai1c_guard_module.make_engine()
        finally:
            ai1c_guard_module.create_engine = original_create
            ai1c_guard_module._DATABASE_URL = original_url
        # 连接前目标拒绝保持成立：替换体零调用。
        self.assertEqual(calls, [])


class SeedAndWorldStateOfflineTests(unittest.TestCase):
    """S2/S3 离线：真实种子与 world_state 的结果形状与无行分支。

    用真实 SQLAlchemy Session（SQLite 内存引擎）执行真实
    ``seed_v1_world`` 与 ``world_state``：
    * S2 — 种子沿真实函数路径执行（调用时 NameError 会在此暴露），
      个人版本／head 的身份统一为 ``TEACHER_ACCOUNT``；
    * S3 — 提取结果形状实拍（incl. 旧行为对照：包装 Row 不是实体），
      无行分支与之一起产出完整规范化快照与不变式证据。
    """

    def setUp(self):
        self.engine = _offline_world_engine()
        self.addCleanup(self.engine.dispose)

    def test_seed_and_world_state_execute_on_real_session(self):
        engine = self.engine
        # S2：真实种子路径执行；修复前这里 NameError。
        seed_v1_world(engine)
        state = world_state(engine)
        # S3：单行 SchoolSettings 的字段来自真实 ORM 实体提取。
        self.assertEqual(state["school"][0], "AI1C 夹具幼儿园")
        self.assertEqual(state["school"][1], 1)
        self.assertEqual(state["school"][2], 1)
        self.assertIsNotNone(state["school"][3])
        # S2：个人种子统一为 TEACHER_ACCOUNT，完整六字段合成 map。
        personal = state["personal_versions"][(TEACHER_ACCOUNT, TASK, 1)]
        self.assertEqual(sorted(personal), sorted(fixture.V1_FIELDS))
        # head 五个保护列与种子一致。
        self.assertEqual(
            state["heads"][f"{TEACHER_ACCOUNT}:{TASK}"],
            (1, "current", None, 1, None),
        )
        # 规范化不变式证据：同一世界两次快照逐键一致（键集合一致）。
        self.assertEqual(state, world_state(engine))
        self.assertEqual(changed_keys(state, world_state(engine)), set())
        # 合成业务记录已进入审计面（供真库零增量比较有实际内容）。
        self.assertEqual(len(state["operations"]), 1)
        self.assertEqual(len(state["change_records"]), 1)
        # 管理员账号与有效会话已在快照面（供真库产品竞争测试使用）。
        self.assertIn(ADMIN_ACCOUNT, state["accounts"])
        self.assertIn(ADMIN_SESSION_ID, state["sessions"])

    def test_school_entity_extraction_result_shapes(self):
        """S3 结果形状实拍：scalars 提取返回 ORM 实体；包装 Row 不是。

        对照组（旧行为）：同一 select 的 ``execute(...).one_or_none()``
        返回包装 Row，读 ORM 属性直接 AttributeError——复审所指的把
        Row 当实体的问题；修复后的 ``world_state`` 走 scalars 实体路径。
        """
        from app.models import SchoolSettings

        seed_v1_world(self.engine)
        with Session(self.engine, future=True) as session:
            entity = session.scalars(select(SchoolSettings)).one_or_none()
            self.assertIsNotNone(entity)
            self.assertIsInstance(entity, SchoolSettings)
            self.assertEqual(entity.school_name, "AI1C 夹具幼儿园")
            # 对照组（旧行为形状）。
            wrapped_row = session.execute(
                select(SchoolSettings)
            ).one_or_none()
            self.assertIsNotNone(wrapped_row)
            self.assertNotIsInstance(wrapped_row, SchoolSettings)
            with self.assertRaises(AttributeError):
                wrapped_row.school_name  # noqa: B018  实拍旧行为

    def test_world_state_without_school_row_branch(self):
        """S3 无行分支：school_settings 清空后快照仍完整、school=None。"""
        from app.models import SchoolSettings

        seed_v1_world(self.engine)
        with Session(self.engine, future=True) as session:
            session.execute(text("DELETE FROM school_settings"))
            session.commit()
        state = world_state(self.engine)
        self.assertIsNone(state["school"])
        # 其余快照键保持完整（无行分支不影响其他不变式面）。
        self.assertIn(f"{TEACHER_ACCOUNT}:{TASK}", state["heads"])
        self.assertEqual(state, world_state(self.engine))
        self.assertEqual(changed_keys(state, world_state(self.engine)), set())
        # 无行分支下两种提取都得到 None（实拍形状一致性）。
        with Session(self.engine, future=True) as session:
            self.assertIsNone(
                session.scalars(select(SchoolSettings)).one_or_none()
            )
            self.assertIsNone(
                session.execute(select(SchoolSettings)).one_or_none()
            )


class RaceAssertionSemanticsOfflineTests(unittest.TestCase):
    """S4/S5 断言语义离线回归：两种合法胜负＋非法额外写入。

    直接执行 guard 的断言纯函数（真库集成测试使用同一批函数），用
    合成规范化快照证明：
    * 工具胜出（审计不变）与产品胜出（合法追加审计）都能通过；
    * 工具胜出却写审计、个人保护被改动、产品胜出缺审计／删除旧行／
      改写旧行／动作或链接形状不符，都被断言拒绝（语义不放宽）。
    """

    @staticmethod
    def _base_snapshot():
        """与 world_state 键同构的合成规范化快照（合法 v1 世界）。"""
        return dict(
            heads={f"{TEACHER_ACCOUNT}:{TASK}": (1, "current", None, 1, None)},
            personal_versions={
                (TEACHER_ACCOUNT, TASK, 1): {
                    field: f"AI1C-FIXTURE-TEACHER-PERSONAL-v1-{field}"
                    for field in fixture.V1_FIELDS
                }
            },
            accounts={
                TEACHER_ACCOUNT: ("夹具老师", "teacher", True, 1, 1),
                ADMIN_ACCOUNT: ("夹具管理员", "admin", True, 1, 1),
            },
            sessions={"ses": (ADMIN_ACCOUNT, 1, "dt", None)},
            school=("AI1C 夹具幼儿园", 1, 1, None),
            operations=[(
                "op-base", TEACHER_ACCOUNT, "account",
                "prompt_personal_init", "school", "singleton", None,
            )],
            change_records=[(
                "pcr-base", "op-base", TASK, "personal_init",
                None, 1, 1, 1, ["theme"],
            )],
            contracts_daily=[(1, list(fixture.V1_FIELDS), {}, {}, None)],
            defaults_daily=[(1, 1, {"theme": "v1"}, None)],
            other_contracts=[("weekly_plan", 1, ["a"])],
            other_defaults=[("weekly_plan", 1, 1, {"a": "x"}, None)],
        )

    @staticmethod
    def _tool_win_after(before):
        """合法工具胜出：恰好追加一份契约 v2 与完整默认 r2，无审计变化。"""
        after = dict(before)
        after["contracts_daily"] = list(before["contracts_daily"]) + [
            (2, list(fixture.V2_FIELDS), {}, {}, None)
        ]
        after["defaults_daily"] = list(before["defaults_daily"]) + [
            (2, 2, dict.fromkeys(fixture.V2_FIELDS, "x"), None)
        ]
        return after

    @staticmethod
    def _product_win_after(before):
        """合法产品胜出：契约不动，追加默认 r2＋恰好一条合法审计行组。"""
        after = dict(before)
        after["defaults_daily"] = list(before["defaults_daily"]) + [
            (2, 1, {"theme": "admin-edit"}, ADMIN_ACCOUNT)
        ]
        after["operations"] = list(before["operations"]) + [
            ("op-new", ADMIN_ACCOUNT, "account", "prompt_default_update",
             "school", "singleton", None)
        ]
        after["change_records"] = list(before["change_records"]) + [
            ("pcr-new", "op-new", TASK, "default_update",
             None, None, 2, 1, ["theme"])
        ]
        return after

    def test_tool_win_legal_outcome_passes(self):
        before = self._base_snapshot()
        after = self._tool_win_after(before)
        # 工具发布：审计零增量、保护状态不变——两条断言都通过。
        ai1c_guard_module.assert_audits_unchanged(before, after, rationale="工具发布")
        ai1c_guard_module.assert_protected_state_untouched(
            before, after, rationale="工具发布"
        )

    def test_product_win_legal_outcome_passes(self):
        before = self._base_snapshot()
        after = self._product_win_after(before)
        # 产品发布：保护状态不变；审计恰好追加且形状合法。
        ai1c_guard_module.assert_protected_state_untouched(
            before, after, rationale="产品发布"
        )
        added = ai1c_guard_module.assert_product_audit_append_legal(
            before, after, task_type=TASK, changed_fields=["theme"],
            rationale="产品发布",
        )
        self.assertEqual(added["operations"][3], "prompt_default_update")
        self.assertEqual(added["change_records"][3], "default_update")
        self.assertEqual(added["operations"][2], "account")

    def test_tool_win_with_audit_append_is_refused(self):
        """工具胜出却出现审计新增（不合法额外写入）→ 断言拒绝。"""
        before = self._base_snapshot()
        after = self._tool_win_after(before)
        after["operations"] = list(before["operations"]) + [
            ("op-illegal", ADMIN_ACCOUNT, "account", "prompt_personal_init",
             "school", "singleton", None)
        ]
        after["change_records"] = list(before["change_records"]) + [
            ("pcr-illegal", "op-illegal", TASK, "personal_init",
             None, 1, 1, 1, ["theme"])
        ]
        with self.assertRaises(AssertionError):
            ai1c_guard_module.assert_audits_unchanged(
                before, after, rationale="工具发布不应写审计"
            )

    def test_tool_win_with_personal_change_is_refused(self):
        """工具胜出却改写个人保护列 → 保护断言拒绝（不放行额外写入）。"""
        before = self._base_snapshot()
        after = self._tool_win_after(before)
        after["personal_versions"] = {
            (TEACHER_ACCOUNT, TASK, 1): {"theme": "tampered"}
        }
        with self.assertRaises(AssertionError):
            ai1c_guard_module.assert_protected_state_untouched(
                before, after, rationale="保护状态"
            )

    def test_product_win_without_audit_append_is_refused(self):
        """产品胜出但审计无新增（缺合法写审计）→ 追加断言拒绝。"""
        before = self._base_snapshot()
        after = self._tool_win_after(before)  # 只有默认前进，无审计行
        with self.assertRaises(AssertionError):
            ai1c_guard_module.assert_product_audit_append_legal(
                before, after, task_type=TASK, changed_fields=["theme"],
                rationale="产品发布必须合法追加审计",
            )

    def test_product_win_with_edited_or_removed_audit_row_refused(self):
        """产品胜出但旧行被改动或新行被删除 → append-only 断言拒绝。"""
        before = self._base_snapshot()
        # 旧行被改写（append-only 被破坏）。
        after_edited = self._product_win_after(before)
        operations = list(after_edited["operations"])
        edited = list(operations[0])
        edited[3] = "prompt_default_update"
        operations[0] = tuple(edited)
        after_edited["operations"] = operations
        with self.assertRaises(AssertionError):
            ai1c_guard_module.assert_product_audit_append_legal(
                before, after_edited, task_type=TASK, changed_fields=["theme"],
                rationale="旧行改动",
            )
        # 有一行审计被删除。
        after_removed = self._product_win_after(before)
        after_removed["operations"] = after_removed["operations"][:-1]
        with self.assertRaises(AssertionError):
            ai1c_guard_module.assert_product_audit_append_legal(
                before, after_removed, task_type=TASK,
                changed_fields=["theme"], rationale="删除审计行",
            )

    def test_product_win_with_wrong_shape_or_link_refused(self):
        """产品胜出但新审计形状（动作／链接／字段）不符 → 断言拒绝。"""
        before = self._base_snapshot()
        # 新行动作不是 prompt_default_update。
        after_action = self._product_win_after(before)
        operations = list(after_action["operations"])
        edited = list(operations[-1])
        edited[3] = "prompt_personal_init"
        operations[-1] = tuple(edited)
        after_action["operations"] = operations
        with self.assertRaises(AssertionError):
            ai1c_guard_module.assert_product_audit_append_legal(
                before, after_action, task_type=TASK, changed_fields=["theme"],
                rationale="新行动作不符",
            )
        # change record 没有链接到新增 operation。
        after_link = self._product_win_after(before)
        change_records = list(after_link["change_records"])
        edited_record = list(change_records[-1])
        edited_record[1] = "op-other"
        change_records[-1] = tuple(edited_record)
        after_link["change_records"] = change_records
        with self.assertRaises(AssertionError):
            ai1c_guard_module.assert_product_audit_append_legal(
                before, after_link, task_type=TASK, changed_fields=["theme"],
                rationale="记录链接不符",
            )
        # changed_fields 与产品实际 patch 不符。
        after_fields = self._product_win_after(before)
        with self.assertRaises(AssertionError):
            ai1c_guard_module.assert_product_audit_append_legal(
                before, after_fields, task_type=TASK,
                changed_fields=["objectives"], rationale="字段集不符",
            )


class _LockHelperHarness:
    """T1/T2 离线检查的职责切面替身集合。

    诚实边界：替身与真实 SQLAlchemy 对象按职责对齐——Connection 提供
    begin／execute／close，RootTransaction 只有 rollback（真实
    RootTransaction 没有 execute，替身故意不提供以暴露向事务对象执行
    SQL 的缺陷形态——T1 原缺陷会因此 AttributeError）。替身只走真实
    辅助函数路径；不提供替代 MySQL 锁的通道。
    """

    def __init__(self, *, transaction=None, connection=None, engine=None):
        self.transaction = transaction
        self.connection = connection
        self.engine = engine


class _FakeRootTransaction:
    """真实 RootTransaction 职责切面：只有 rollback（无 execute）。"""

    def __init__(self, calls, *, fail_rollback=False):
        self._calls = calls
        self._fail_rollback = fail_rollback

    def rollback(self):
        self._calls.append("tx.rollback")
        if self._fail_rollback:
            raise RuntimeError("fake rollback failure")


class _FakeConnection:
    """真实 Connection 职责切面：begin／execute／close。"""

    def __init__(self, calls, *, begin_error=None, execute_error=None):
        self._calls = calls
        self._begin_error = begin_error
        self._execute_error = execute_error

    def begin(self):
        self._calls.append("connection.begin")
        if self._begin_error is not None:
            raise self._begin_error
        return _FakeRootTransaction(self._calls)

    def execute(self, statement, *args, **kwargs):
        self._calls.append("connection.execute")
        self._calls.append(("statement", statement))
        if self._execute_error is not None:
            raise self._execute_error
        return None

    def close(self):
        self._calls.append("connection.close")


class _FakeEngine:
    """真实 Engine 职责切面：connect／dispose。"""

    def __init__(self, calls, connection):
        self._calls = calls
        self._connection = connection

    def connect(self):
        self._calls.append("engine.connect")
        return self._connection

    def dispose(self):
        self._calls.append("engine.dispose")


class LockHelperOfflineTests(unittest.TestCase):
    """T1/T2 离线入口验证：真实 _hold_anchor_lock／_release_anchor_lock
    路径在职责一致的替身上核对资源职责与调用次序。

    这些检查不建立任何连接、不提供绕过 MySQL 的锁替身；真实锁行为
    仍仅由一次性 MySQL 资源上的真库用例验证。
    """

    @staticmethod
    def _make_instance():
        """FixtureIntegrationTests 实例（只用于执行辅助函数；不跑真库流程）。"""
        return FixtureIntegrationTests("test_publish_v2_success_is_atomic")

    def _fake_lock_resources(self, calls, *, begin_error=None,
                             execute_error=None):
        connection = _FakeConnection(
            calls, begin_error=begin_error, execute_error=execute_error
        )
        engine = _FakeEngine(calls, connection)
        return engine, connection

    def _run_hold_anchor_lock(self, engine):
        instance = self._make_instance()
        with mock.patch.object(
            sys.modules[__name__], "make_engine", return_value=engine
        ):
            return instance._hold_anchor_lock()

    def test_hold_anchor_lock_executes_real_lock_query_on_connection(self):
        calls = []
        engine, _connection = self._fake_lock_resources(calls)
        returned = self._run_hold_anchor_lock(engine)
        # 返回三元组：engine／connection／transaction（调用方拿到资源）。
        self.assertIs(returned[0], engine)
        self.assertIs(returned[1], _connection)
        self.assertIsInstance(returned[2], _FakeRootTransaction)
        # 成功路径只取得资源：不再 dispose，事务尚未 rollback。
        self.assertIn("engine.connect", calls)
        self.assertIn("connection.begin", calls)
        self.assertNotIn("engine.dispose", calls)
        self.assertNotIn("tx.rollback", calls)
        # T1：锁查询在连接上执行（RootTransaction 只有 rollback，替身
        # 没有 execute——若向事务执行 SQL，这里会 AttributeError）。
        statements = [
            item[1] for item in calls
            if isinstance(item, tuple) and item[0] == "statement"
        ]
        self.assertEqual(len(statements), 1)
        from sqlalchemy.dialects import mysql

        compiled = str(
            statements[0].compile(dialect=mysql.dialect())
        )
        self.assertIn("prompt_contract_versions", compiled)
        self.assertIn("FOR UPDATE", compiled)

    def test_hold_anchor_lock_begin_failure_cleans_up_and_reraises(self):
        calls = []
        engine, _connection = self._fake_lock_resources(
            calls, begin_error=RuntimeError("begin failed")
        )
        instance = self._make_instance()
        with mock.patch.object(
            sys.modules[__name__], "make_engine", return_value=engine
        ):
            with self.assertRaises(RuntimeError) as caught:
                instance._hold_anchor_lock()
        # 原样抛出原始错误（不转换、不吞掉）。
        self.assertEqual(str(caught.exception), "begin failed")
        # 函数内部清理已取得资源，不依赖调用方 finally。
        self.assertIn("engine.connect", calls)
        self.assertNotIn("connection.execute", calls)
        # begin 失败：事务对象未建立（无 rollback 可做），但已取得的
        # 连接必须随 close 释放，引擎以 dispose 收尾。
        self.assertNotIn("tx.rollback", calls)
        self.assertIn("connection.close", calls)
        first_close = calls.index("connection.close")
        first_dispose = calls.index("engine.dispose")
        self.assertLess(first_close, first_dispose)

    def test_hold_anchor_lock_query_failure_rolls_back_closes_disposes(
        self,
    ):
        calls = []
        engine, _connection = self._fake_lock_resources(
            calls, execute_error=RuntimeError("lock query failed")
        )
        instance = self._make_instance()
        with mock.patch.object(
            sys.modules[__name__], "make_engine", return_value=engine
        ):
            with self.assertRaises(RuntimeError) as caught:
                instance._hold_anchor_lock()
        self.assertEqual(str(caught.exception), "lock query failed")
        # 清理次序：tx.rollback → connection.close → engine.dispose。
        self.assertIn("tx.rollback", calls)
        self.assertIn("connection.close", calls)
        self.assertIn("engine.dispose", calls)
        first_tx_rollback = calls.index("tx.rollback")
        first_close = calls.index("connection.close")
        first_dispose = calls.index("engine.dispose")
        self.assertLess(first_tx_rollback, first_close)
        self.assertLess(first_close, first_dispose)

    def _run_release_anchor_lock(self, engine, connection, transaction):
        instance = self._make_instance()
        return instance._release_anchor_lock(engine, connection, transaction)

    def test_release_anchor_lock_is_pure_resource_cleanup(self):
        calls = []
        engine, connection = self._fake_lock_resources(calls)
        transaction = _FakeRootTransaction(calls)
        self.assertIsNone(
            self._run_release_anchor_lock(engine, connection, transaction)
        )
        # 纯清理次序：rollback → close → dispose；替身对象没有业务查询
        # /发布断言通道，任何额外访问都会 AttributeError。
        self.assertEqual(
            [item for item in calls if isinstance(item, str)],
            ["tx.rollback", "connection.close", "engine.dispose"],
        )

    def test_release_anchor_lock_survives_rollback_failure_and_runs_before_publish(self):
        """无活动异常时单步清理失败显式报错：rollback 失败抛固定去敏
        RuntimeError，close＋dispose 仍全部尝试。"""
        calls = []
        engine, connection = self._fake_lock_resources(calls)
        transaction = _FakeRootTransaction(calls, fail_rollback=True)
        # 无原错时清理失败不再静默通过：抛固定去敏步骤名 RuntimeError。
        with self.assertRaisesRegex(
            RuntimeError, r"anchor-lock cleanup step failed: tx.rollback"
        ):
            self._run_release_anchor_lock(engine, connection, transaction)
        self.assertIn("tx.rollback", calls)
        self.assertIn("connection.close", calls)
        self.assertIn("engine.dispose", calls)
        first_close = calls.index("connection.close")
        first_dispose = calls.index("engine.dispose")
        self.assertLess(first_close, first_dispose)
        # 释放之后的调用记录止于清理本身：没有业务读取／状态断言通道
        # （替身对象不提供 execute 之类访问路径）。
        for call in calls:
            self.assertIn(call, ("tx.rollback", "connection.close",
                                 "engine.dispose"))


class RestoredPublishV2AssertionsOfflineTests(unittest.TestCase):
    """用合成合法发布结果驱动实际 test_publish_v2_success_is_atomic。

    断言块已恢复到该测试（T2）；离线用合成快照走实际断言序列，并
    逐一证明不完整 map／改变个人文字／新建 created_by／被改动的
    input_vars / output_schema 会被拒绝。
    """

    def _run_real_test(self, before, after, rows):
        """在替身输入上直接执行真实测试方法（其内断言全部真实）。"""
        import contextlib
        import io

        instance = FixtureIntegrationTests("test_publish_v2_success_is_atomic")
        instance.before = before
        instance.engine = object()
        instance._publish = (
            lambda *args, **kwargs: dict(
                status="published",
                task_type=TASK,
                old_contract_version=1,
                new_contract_version=2,
                old_default_revision=1,
                new_default_revision=2,
                fields=list(fixture.V2_FIELDS),
            )
        )
        module = sys.modules[__name__]
        with mock.patch.object(
            module, "world_state", lambda engine: after
        ), mock.patch.object(
            module, "_daily_rows", lambda engine: rows
        ):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                # 测试方法不读取环境；直接执行以核对断言恢复位置。
                instance.test_publish_v2_success_is_atomic()
        return instance

    def _legal_after_and_rows(self, before):
        seed_contract = before["contracts_daily"][0]
        copied_input_vars = dict(seed_contract[2])
        copied_output_schema = dict(seed_contract[3])
        v2_fields = list(fixture.V2_FIELDS)
        after = dict(before)
        after["contracts_daily"] = list(before["contracts_daily"]) + [(
            2, v2_fields, copied_input_vars, copied_output_schema, None,
        )]
        after["defaults_daily"] = list(before["defaults_daily"]) + [(
            2, 2, fixture.recipe_guidance_map(2), None
        )]
        rows = {
            "contracts": list(before["contracts_daily"]) + [(
                2, list(v2_fields), dict(copied_input_vars),
                dict(copied_output_schema), None,
            )],
            "defaults": list(before["defaults_daily"]) + [(
                2, 2, fixture.recipe_guidance_map(2), None
            )],
        }
        return after, rows

    def test_legal_synthetic_publish_passes_actual_assertions(self):
        before = RaceAssertionSemanticsOfflineTests._base_snapshot()
        after, rows = self._legal_after_and_rows(before)
        # 实际测试方法在合成合法发布结果上全部通过（断言恢复位置正确）。
        self._run_real_test(before, after, rows)

    def test_incomplete_map_in_new_default_refused(self):
        before = RaceAssertionSemanticsOfflineTests._base_snapshot()
        after, rows = self._legal_after_and_rows(before)
        rows["defaults"][-1] = (2, 2, {"theme": "AI1C-FIXTURE-v2-theme"}, None)
        with self.assertRaises(AssertionError):
            self._run_real_test(before, after, rows)

    def test_swapped_field_values_in_new_default_refused(self):
        """字段间值互换：完整 dict 相等断言拒绝。

        theme／objectives 的值互换后，键集合与值集合都与配方一致——
        此前的弱断言（sorted 键＋set 值）会放行；加固后的全量 dict
        相等断言必须拒绝该发布结果。
        """
        before = RaceAssertionSemanticsOfflineTests._base_snapshot()
        after, rows = self._legal_after_and_rows(before)
        swapped = dict(fixture.recipe_guidance_map(2))
        swapped["theme"], swapped["objectives"] = (
            swapped["objectives"],
            swapped["theme"],
        )
        # 键集合／值集合确实都与配方一致（实拍缺口：旧弱断言会通过）。
        self.assertEqual(sorted(swapped), sorted(fixture.V2_FIELDS))
        self.assertEqual(
            set(swapped.values()),
            set(fixture.recipe_guidance_map(2).values()),
        )
        rows["defaults"][-1] = (2, 2, swapped, None)
        with self.assertRaises(AssertionError):
            self._run_real_test(before, after, rows)

    def test_changed_personal_text_refused(self):
        before = RaceAssertionSemanticsOfflineTests._base_snapshot()
        after, rows = self._legal_after_and_rows(before)
        after["personal_versions"] = {
            (TEACHER_ACCOUNT, TASK, 1): {"theme": "tampered"}
        }
        with self.assertRaises(AssertionError):
            self._run_real_test(before, after, rows)

    def test_non_null_created_by_refused(self):
        before = RaceAssertionSemanticsOfflineTests._base_snapshot()
        after, rows = self._legal_after_and_rows(before)
        rows["contracts"][-1] = (
            2, list(fixture.V2_FIELDS), {}, {}, ADMIN_ACCOUNT
        )
        after["contracts_daily"][-1] = (
            2, list(fixture.V2_FIELDS), {}, {}, ADMIN_ACCOUNT
        )
        with self.assertRaises(AssertionError):
            self._run_real_test(before, after, rows)

    def test_changed_copied_input_vars_refused(self):
        before = RaceAssertionSemanticsOfflineTests._base_snapshot()
        after, rows = self._legal_after_and_rows(before)
        rows["contracts"][-1] = (
            2, list(fixture.V2_FIELDS), {"changed": True},
            rows["contracts"][-1][3], None,
        )
        with self.assertRaises(AssertionError):
            self._run_real_test(before, after, rows)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
