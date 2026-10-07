"""AI 1C 验收夹具工具 — 离线单元测试。

覆盖 2026-10-07 编码提示词 §4 的单元层要求：

* 目标保护在任何 engine／连接建立之前拒绝（驱动、主机、端口、库名、
  空目标、URL 查询参数、跨模式、非法模式）；
* 发布开关缺失／非法 expected 在建 engine 之前拒绝；
* import 与 --help 不需要 DSN、不连接数据库，且进程内清除继承的
  DATABASE_URL／AI_MASTER_KEY／AI_MASTER_KEY_ID；
* 固定配方完整性（字段固定顺序、map 一致、每字段 ≤8000、允许的转换）；
* 固定错误输出去敏：不含 DSN／密码／合成标记，无 traceback。

这些测试全部离线，不声称任何真库覆盖；真库事务／回滚／锁与并发在
``tests/integration/test_ai1c_acceptance_fixture.py``。
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = BACKEND_ROOT / "scripts" / "ai1c_acceptance_fixture.py"
PYTHON = sys.executable

LEAKED_ENV = ("DATABASE_URL", "AI_MASTER_KEY", "AI_MASTER_KEY_ID")

os.environ["APP_DISABLE_DOTENV"] = "1"
for _leaked in LEAKED_ENV:
    os.environ.pop(_leaked, None)

sys.path.insert(0, str(BACKEND_ROOT / "scripts"))
sys.path.insert(0, str(BACKEND_ROOT))

import ai1c_acceptance_fixture as fixture  # noqa: E402

SECRET_MARKER = "PW-AI1C-UNIT-SECRET-MARK"

GOOD_ACCEPTANCE_URL = (
    f"mysql+pymysql://fixture_user:{SECRET_MARKER}@127.0.0.1:13386/"
    "kg_next_ai1c_fixture"
)
GOOD_INTEGRATION_URL = (
    f"mysql+pymysql://fixture_user:{SECRET_MARKER}@127.0.0.1:13387/"
    "kindergarten_test_ai1c_fixture"
)


class TargetGuardTests(unittest.TestCase):
    """guard 拒绝不发生在 engine 创建之后；固定短句且不回显输入。"""

    def _refused(self, mode: str, raw_url) -> fixture.FixtureGuardError:
        with self.assertRaises(fixture.FixtureGuardError) as caught:
            fixture.validate_target_url(mode, raw_url)
        return caught.exception

    def test_valid_targets_pass(self):
        acceptance = fixture.validate_target_url("acceptance", GOOD_ACCEPTANCE_URL)
        integration = fixture.validate_target_url("integration", GOOD_INTEGRATION_URL)
        self.assertEqual(acceptance.database, "kg_next_ai1c_fixture")
        self.assertEqual(acceptance.port, 13386)
        self.assertEqual(integration.database, "kindergarten_test_ai1c_fixture")
        self.assertEqual(integration.port, 13387)

    def test_cross_mode_targets_refused(self):
        self._refused("acceptance", GOOD_INTEGRATION_URL)
        self._refused("integration", GOOD_ACCEPTANCE_URL)

    def test_wrong_target_refused_before_any_connection(self):
        bad_targets = (
            # 远程验收库绝不允许
            "mysql+pymysql://u:{p}@127.0.0.1:13386/kg_next_i5_acceptance",
            # 其他套件／开发库
            "mysql+pymysql://u:{p}@127.0.0.1:13387/kindergarten_test_ai1a",
            "mysql+pymysql://u:{p}@127.0.0.1:13387/kindergarten_test",
            "mysql+pymysql://u:{p}@127.0.0.1:13387/kindergarten_dev",
            # 空库名
            "mysql+pymysql://u:{p}@127.0.0.1:13386/",
        )
        for target in bad_targets:
            error = self._refused("acceptance", target.format(p=SECRET_MARKER))
            # 固定消息不镜像具体库名
            self.assertNotIn("kg_next_i5_acceptance", str(error))
            self.assertNotIn("kindergarten", str(error))
            self.assertNotIn(SECRET_MARKER, str(error))

    def test_driver_host_port_refused(self):
        for target in (
            f"mysql+mysqldb://u:{SECRET_MARKER}@127.0.0.1:13386/kg_next_ai1c_fixture",
            f"postgresql://u:{SECRET_MARKER}@127.0.0.1:13386/kg_next_ai1c_fixture",
            f"mysql+pymysql://u:{SECRET_MARKER}@bwh.ywyz.tech:13386/kg_next_ai1c_fixture",
            f"mysql+pymysql://u:{SECRET_MARKER}@10.1.2.3:13386/kg_next_ai1c_fixture",
            f"mysql+pymysql://u:{SECRET_MARKER}@127.0.0.1:13385/kg_next_ai1c_fixture",
            f"mysql+pymysql://u:{SECRET_MARKER}@127.0.0.1:13387/kg_next_ai1c_fixture",
        ):
            self._refused("acceptance", target)

    def test_query_routing_parameters_refused(self):
        poisoned = (
            f"mysql+pymysql://u:{SECRET_MARKER}@127.0.0.1:13386/"
            f"kg_next_ai1c_fixture?setting=unexpected"
        )
        self._refused("acceptance", poisoned)

    def test_empty_or_missing_mode_refused(self):
        self._refused("acceptance", "")
        self._refused("acceptance", None)
        error = self._refused("bogus-mode", GOOD_ACCEPTANCE_URL)
        self.assertNotIn("bogus", str(error))


class GuardBeforeEngineTests(unittest.TestCase):
    """guard 拒绝必须发生在 create_engine 被调用之前。"""

    def _tracks_engine(self):
        calls = []

        original = fixture.create_engine

        def _tracking(*args, **kwargs):
            calls.append(args)
            raise AssertionError("engine created after refusal")

        fixture.create_engine = _tracking
        return calls, original

    def test_create_guarded_engine_refuses_before_engine(self):
        calls, original = self._tracks_engine()
        try:
            with self.assertRaises(fixture.FixtureGuardError):
                fixture.create_guarded_engine(
                    "acceptance",
                    f"mysql+pymysql://u:{SECRET_MARKER}@10.0.0.1:13386/"
                    "kg_next_i5_acceptance",
                )
        finally:
            fixture.create_engine = original
        self.assertEqual(calls, [])

    def test_missing_switch_refused_before_engine(self):
        """缺发布开关时，publish 命令在建 engine 之前拒绝。

        最终工具的开关检查在 ``run_publish_command``（CLI 层），
        ``create_guarded_engine`` 本身不负责开关；用跟踪替换证明
        engine 从未被创建。"""
        calls = []

        def _tracking(*args, **kwargs):  # pragma: no cover
            calls.append(args)
            raise AssertionError("engine created without the publish switch")

        original = fixture.create_guarded_engine
        fixture.create_guarded_engine = _tracking
        previous = os.environ.pop(fixture.PUBLISH_SWITCH_VAR, None)
        try:
            exit_code = fixture.main(
                [
                    "--mode",
                    "acceptance",
                    "publish-v2",
                    "--expected-contract-version",
                    "1",
                    "--expected-default-revision",
                    "1",
                ]
            )
        finally:
            fixture.create_guarded_engine = original
            if previous is not None:
                os.environ[fixture.PUBLISH_SWITCH_VAR] = previous
        self.assertNotEqual(exit_code, 0)
        self.assertEqual(calls, [])


class ExpectedArgumentsTests(unittest.TestCase):
    """expected 必须严格正整数；bool／0／负数／非整数／None 一律拒绝。"""

    def test_valid_values_pass(self):
        self.assertEqual(
            fixture.validate_expected_arguments(1, 2), (1, 2)
        )
        self.assertEqual(
            fixture.validate_expected_arguments(3, 7), (3, 7)
        )

    def test_invalid_values_refused(self):
        for value in (0, -1, True, False, "1", 1.5, None, [], {}):
            with self.assertRaises(fixture.FixtureError, msg=repr(value)):
                fixture.validate_expected_arguments(value, 1)
            with self.assertRaises(fixture.FixtureError, msg=repr(value)):
                fixture.validate_expected_arguments(1, value)


class RecipeTests(unittest.TestCase):
    """固定配方：有序字段集、合成默认、≤8000、允许的转换集合。"""

    def test_fixed_field_orders(self):
        self.assertEqual(
            fixture.CONTRACT_RECIPES[1],
            (
                "theme",
                "objectives",
                "preparation",
                "key_points",
                "difficult_points",
                "process",
            ),
        )
        self.assertEqual(
            fixture.CONTRACT_RECIPES[2],
            (
                "theme",
                "objectives",
                "key_points",
                "difficult_points",
                "process",
                "acceptance_support",
            ),
        )
        self.assertEqual(
            fixture.CONTRACT_RECIPES[3],
            (
                "theme",
                "objectives",
                "key_points",
                "difficult_points",
                "acceptance_support",
            ),
        )

    def test_validate_recipe_accepts_each_version(self):
        for version in (1, 2, 3):
            fixture.validate_recipe(version)

    def test_synthetic_defaults_match_fields_and_limits(self):
        for version in (1, 2, 3):
            mapping = fixture.recipe_guidance_map(version)
            self.assertEqual(
                list(mapping.keys()), list(fixture.CONTRACT_RECIPES[version])
            )
            for field, text in mapping.items():
                self.assertIn("AI1C-FIXTURE-", text)
                self.assertIsInstance(text, str)
                self.assertLessEqual(len(text), 8000)
                self.assertGreater(len(text), 0)

    def test_recipe_rejects_unknown_version(self):
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_recipe(4)
        with self.assertRaises(fixture.FixtureError):
            fixture.validate_recipe(0)

    def test_allowed_transitions_only(self):
        self.assertEqual(
            fixture.ALLOWED_TRANSITIONS, ((1, 2), (2, 3))
        )
        self.assertTrue(fixture.transition_recipe_matches(1, 2))
        self.assertTrue(fixture.transition_recipe_matches(2, 3))
        for old, target in ((1, 3), (2, 2), (2, 1), (3, 2), (3, 3), (1, 1)):
            self.assertFalse(
                fixture.transition_recipe_matches(old, target),
                (old, target),
            )


class ParserTests(unittest.TestCase):
    """非法 CLI 组合在 argparse 层拒绝；不会连接数据库。"""

    def _parses(self, argv):
        return fixture.build_parser().parse_args(argv)

    def _rejects(self, argv):
        with self.assertRaises(SystemExit) as caught:
            fixture.build_parser().parse_args(argv)
        return caught.exception.code

    def test_valid_commands_parse(self):
        args = self._parses(["--mode", "acceptance", "inspect"])
        self.assertEqual(args.command, "inspect")
        self.assertIsNone(args.target_version)
        args = self._parses(
            [
                "--mode",
                "integration",
                "publish-v3",
                "--expected-contract-version",
                "2",
                "--expected-default-revision",
                "7",
            ]
        )
        self.assertEqual(args.target_version, 3)
        self.assertEqual(args.expected_contract_version, 2)
        self.assertEqual(args.expected_default_revision, 7)

    def test_missing_mode_refused(self):
        self.assertNotEqual(self._rejects(["inspect"]), 0)
        self.assertNotEqual(
            self._rejects(
                [
                    "publish-v2",
                    "--expected-contract-version",
                    "1",
                    "--expected-default-revision",
                    "1",
                ]
            ),
            0,
        )

    def test_unknown_command_refused(self):
        self.assertNotEqual(self._rejects(["--mode", "acceptance", "publish-v4"]), 0)

    def test_non_publish_actions_do_not_require_expected(self):
        args = self._parses(["--mode", "acceptance", "inspect"])
        self.assertFalse(hasattr(args, "expected_contract_version"))

    def test_publish_without_expected_refused(self):
        self.assertNotEqual(
            self._rejects(["--mode", "acceptance", "publish-v2"]), 0
        )

    def test_zero_or_negative_expected_refused(self):
        for expected in ("0", "-3"):
            self.assertNotEqual(
                self._rejects(
                    [
                        "--mode",
                        "acceptance",
                        "publish-v2",
                        "--expected-contract-version",
                        expected,
                        "--expected-default-revision",
                        "1",
                    ]
                ),
                0,
            )
            self.assertNotEqual(
                self._rejects(
                    [
                        "--mode",
                        "acceptance",
                        "publish-v2",
                        "--expected-contract-version",
                        "1",
                        "--expected-default-revision",
                        expected,
                    ]
                ),
                0,
            )


class CommandDispatchTests(unittest.TestCase):
    """inspect 无需发布开关；publish 缺开关在建 engine 之前拒绝。"""

    def setUp(self):
        self._original_dsn = os.environ.pop(fixture.DSN_ENV_VAR, None)
        self._original_switch = os.environ.pop(fixture.PUBLISH_SWITCH_VAR, None)

    def tearDown(self):
        for name, value in (
            (fixture.DSN_ENV_VAR, self._original_dsn),
            (fixture.PUBLISH_SWITCH_VAR, self._original_switch),
        ):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_missing_dsn_raises_target_unset_guard(self):
        with self.assertRaises(fixture.FixtureGuardError) as caught:
            fixture.resolve_target_url("acceptance")
        self.assertEqual(caught.exception.code, fixture.ERR_TARGET_UNSET)

    def test_resolved_dsn_is_guarded(self):
        os.environ[fixture.DSN_ENV_VAR] = (
            f"mysql+pymysql://u:{SECRET_MARKER}@127.0.0.1:13386/"
            "kg_next_i5_acceptance"
        )
        try:
            with self.assertRaises(fixture.FixtureGuardError):
                fixture.resolve_target_url("acceptance")
        finally:
            os.environ.pop(fixture.DSN_ENV_VAR, None)

    def test_publish_switch_missing_refuses_guard_level(self):
        engine_calls = []

        def _reject(*args, **kwargs):  # pragma: no cover - guard must fire first
            engine_calls.append(args)
            raise AssertionError("engine was created without the publish switch")

        original = fixture.create_guarded_engine
        fixture.create_guarded_engine = _reject
        args = fixture.build_parser().parse_args(
            [
                "--mode",
                "acceptance",
                "publish-v2",
                "--expected-contract-version",
                "1",
                "--expected-default-revision",
                "1",
            ]
        )
        try:
            with self.assertRaises(fixture.FixtureGuardError) as caught:
                fixture.run_publish_command(
                    mode="acceptance",
                    target_version=2,
                    expected_contract=int(args.expected_contract_version),
                    expected_default=int(args.expected_default_revision),
                )
        finally:
            fixture.create_guarded_engine = original
        self.assertEqual(caught.exception.code, fixture.ERR_PUBLISH_SWITCH_MISSING)
        self.assertEqual(engine_calls, [])

    def test_publish_valid_args_with_switch_reaches_engine_guard(self):
        os.environ[fixture.PUBLISH_SWITCH_VAR] = "yes"
        os.environ[fixture.DSN_ENV_VAR] = (
            f"mysql+pymysql://u:{SECRET_MARKER}@10.0.0.1:13386/"
            "kg_next_i5_acceptance"
        )
        try:
            with self.assertRaises(fixture.FixtureGuardError) as caught:
                fixture.run_publish_command(
                    mode="acceptance",
                    target_version=2,
                    expected_contract=1,
                    expected_default=1,
                )
        finally:
            os.environ.pop(fixture.PUBLISH_SWITCH_VAR, None)
            os.environ.pop(fixture.DSN_ENV_VAR, None)
        self.assertEqual(caught.exception.code, fixture.ERR_TARGET_REFUSED)


class ImportAndHelpSafetyTests(unittest.TestCase):
    """import／--help 不连库、不读私密配置。"""

    def _clean_env(self, dsn_value: str | None = None):
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in LEAKED_ENV
        }
        environment["APP_DISABLE_DOTENV"] = "1"
        if dsn_value is not None:
            environment[fixture.DSN_ENV_VAR] = dsn_value
        return environment

    def test_import_does_not_need_dsn_or_connection(self):
        completed = subprocess.run(
            [
                PYTHON,
                "-c",
                "import sys; sys.path.insert(0, "
                + repr(str(BACKEND_ROOT / "scripts"))
                + "); import ai1c_acceptance_fixture as m; "
                "print('IMPORT_OK', m.FIXTURE_TASK_TYPE)",
            ],
            env=self._clean_env(),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("IMPORT_OK", completed.stdout)
        self.assertIn("daily_lesson_split", completed.stdout)

    def test_help_does_not_connect(self):
        completed = subprocess.run(
            [PYTHON, str(SCRIPT_PATH), "--help"],
            env=self._clean_env(),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertNotIn("AI1C_TARGET_REFUSED", completed.stderr)
        self.assertNotIn("AI1C_TARGET_UNSET", completed.stderr)

    def test_import_forces_dotenv_off_and_drops_leaked_secrets(self):
        completed = subprocess.run(
            [
                PYTHON,
                "-c",
                "import sys, os; sys.path.insert(0, "
                + repr(str(BACKEND_ROOT / "scripts"))
                + "); import ai1c_acceptance_fixture; "
                "print(os.environ.get('APP_DISABLE_DOTENV')); "
                "print('DATABASE_URL' in os.environ); "
                "print('AI_MASTER_KEY' in os.environ); "
                "print('AI_MASTER_KEY_ID' in os.environ)",
            ],
            env={
                **self._clean_env(),
                "DATABASE_URL": f"mysql+pymysql://u:{SECRET_MARKER}@10.0.0.1:13386/kg_next_i5_acceptance",
                "AI_MASTER_KEY": "leaked-master-material",
            },
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0)
        lines = completed.stdout.strip().splitlines()
        self.assertEqual(lines, ["1", "False", "False", "False"])


def register_sqlite_native_adapters() -> None:
    """注册显式 datetime/date 适配器，消除 Python 3.12+ 默认适配器
    DeprecationWarning（sqlite3 stdlib 变化；语义与默认适配器一致）。"""
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


def _memory_prompt_engine():
    """离线驱动无关的内存引擎（仅建两张提示词表并种入 v1 世界）。

    用途说明（诚实边界）：仅用于会话级行为的离线单元回归（commit
    边界、expire_on_commit=True 下有无提交后隐式刷新）。它不替代真
    实 MySQL 8.4 验证；真库事务／回滚／锁与并发行为仍由
    ``tests/integration/test_ai1c_acceptance_fixture.py`` 在一次性受
    控资源上证明。
    """
    from sqlalchemy import create_engine, event, insert
    from app.models import PromptContractVersion, PromptDefaultVersion

    register_sqlite_native_adapters()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    @event.listens_for(engine, "connect")
    def _register(dbapi_connection, record):
        dbapi_connection.create_collation(
            "utf8mb4_bin", lambda a, b: (a > b) - (a < b)
        )

    PromptContractVersion.__table__.create(engine)
    PromptDefaultVersion.__table__.create(engine)
    v1_fields = list(fixture.V1_FIELDS)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with engine.begin() as connection:
        connection.execute(insert(PromptContractVersion), [dict(
            id="c" * 32,
            task_type=fixture.FIXTURE_TASK_TYPE,
            contract_version=1,
            input_vars={},
            output_schema={},
            guidance_fields=v1_fields,
            created_by=None,
            created_at=now,
        )])
        connection.execute(insert(PromptDefaultVersion), [dict(
            id="d" * 32,
            task_type=fixture.FIXTURE_TASK_TYPE,
            default_revision=1,
            contract_version=1,
            guidance_map=fixture.recipe_guidance_map(1),
            created_by=None,
            created_at=now,
        )])
    return engine


class CommitBoundaryRegressionTests(unittest.TestCase):
    """R1 离线回归：提交前捕获全部结果标量；commit 成功后零隐式 SELECT。

    使用真实 SQLAlchemy Session（expire_on_commit=True，与 CLI 默认一
    致）＋离线内存 oracle，统计 after_commit 之后实际执行的语句数。
    """

    @staticmethod
    def _post_commit_recorder(engine) -> dict:
        from sqlalchemy import event

        recorder = {"on": False, "statements": []}

        @event.listens_for(engine, "after_cursor_execute")
        def _count(connection, cursor, statement, parameters,
                   context, executemany):
            if recorder["on"]:
                recorder["statements"].append(statement)

        return recorder

    def test_success_publish_has_zero_post_commit_statements(self):
        from sqlalchemy import event
        from sqlalchemy.orm import Session

        engine = _memory_prompt_engine()
        # 离线测试资源清理：内存引擎显式 dispose，避免遗留未关闭连接。
        self.addCleanup(engine.dispose)
        recorder = self._post_commit_recorder(engine)
        with Session(
            engine, future=True, expire_on_commit=True
        ) as session:
            @event.listens_for(session, "after_commit")
            def _mark_committed(session):
                recorder["on"] = True

            result = fixture.run_publish(
                session,
                target_contract_version=2,
                expected_contract_version=1,
                expected_default_revision=1,
            )
        # 会话 after_commit 已触发（提交真实发生）。
        self.assertTrue(recorder["on"])
        # R1：commit 成功后没有再执行任何语句（无 ORM 属性读取触发的
        # 隐式刷新 SELECT，也没有额外读写）。
        self.assertEqual(recorder["statements"], [])
        # 结果全部为提交前捕获的纯标量／容器。
        self.assertEqual(result, {
            "status": "published",
            "task_type": fixture.FIXTURE_TASK_TYPE,
            "old_contract_version": 1,
            "new_contract_version": 2,
            "old_default_revision": 1,
            "new_default_revision": 2,
            "fields": list(fixture.V2_FIELDS),
        })
        for key, value in result.items():
            if key == "fields":
                self.assertTrue(
                    all(isinstance(item, str) for item in value)
                )
            elif key == "task_type" or key == "status":
                self.assertIsInstance(value, str)
            else:
                self.assertIsInstance(value, int)

    def test_success_publish_numbering_follows_history_max_plus_1(self):
        """已有较高默认修订的世界：新修订仍是全历史 MAX+1（43 预期）。"""
        from sqlalchemy import insert, select
        from sqlalchemy import event
        from sqlalchemy.orm import Session
        from app.models import PromptDefaultVersion, PromptContractVersion

        engine = _memory_prompt_engine()
        # 离线测试资源清理：内存引擎显式 dispose，避免遗留未关闭连接。
        self.addCleanup(engine.dispose)
        with Session(engine, future=True) as session:
            contract_row = session.execute(
                select(PromptContractVersion).where(
                    PromptContractVersion.task_type
                    == fixture.FIXTURE_TASK_TYPE
                )
            ).scalar_one()
            session.execute(insert(PromptDefaultVersion), [dict(
                id="h" * 32,
                task_type=fixture.FIXTURE_TASK_TYPE,
                default_revision=42,
                contract_version=1,
                guidance_map={
                    field: f"AI1C-FIXTURE-OFFLINE-v1-{field}-r42"
                    for field in list(contract_row.guidance_fields)
                },
                created_by=None,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )])
            session.commit()

        recorder = self._post_commit_recorder(engine)
        with Session(
            engine, future=True, expire_on_commit=True
        ) as session:
            @event.listens_for(session, "after_commit")
            def _mark_committed(session):
                recorder["on"] = True

            result = fixture.run_publish(
                session,
                target_contract_version=2,
                expected_contract_version=1,
                expected_default_revision=42,
            )
        self.assertEqual(recorder["statements"], [])
        self.assertEqual(result["old_default_revision"], 42)
        self.assertEqual(result["new_default_revision"], 43)

    def test_commit_failure_is_uncertain_not_zero_increment(self):
        """Session.commit() 抛错＝COMMIT 结果不确定：固定码，不自动重试。"""
        from unittest import mock
        from sqlalchemy.orm import Session

        engine = _memory_prompt_engine()
        # 离线测试资源清理：内存引擎显式 dispose，避免遗留未关闭连接。
        self.addCleanup(engine.dispose)
        commit_attempts = {"n": 0}

        def _failing_commit(*args, **kwargs):
            commit_attempts["n"] += 1
            raise OSError("connection dropped mid-commit")

        with Session(engine, future=True, expire_on_commit=True) as session:
            with mock.patch.object(
                Session, "commit", autospec=True, side_effect=_failing_commit
            ):
                with self.assertRaises(fixture.FixtureError) as caught:
                    fixture.run_publish(session, 2, 1, 1)
        self.assertEqual(
            caught.exception.code, fixture.ERR_COMMIT_UNCERTAIN
        )
        self.assertEqual(
            caught.exception.message, fixture.MESSAGE_COMMIT_UNCERTAIN
        )
        # 不自动重试：commit 恰好只尝试一次。
        self.assertEqual(commit_attempts["n"], 1)
        # 固定输出不含原始异常细节。
        self.assertNotIn("OSError", caught.exception.message)
        self.assertNotIn("connection dropped", caught.exception.message)
        self.assertNotIn("PW-AI1C-UNIT-SECRET-MARK", str(caught.exception))

    def test_precommit_write_failure_is_db_operational_and_rolled_back(self):
        """提交前写失败＝确定回滚：转换固定码，不透传原始异常。"""
        from unittest import mock
        from sqlalchemy.orm import Session

        engine = _memory_prompt_engine()
        # 离线测试资源清理：内存引擎显式 dispose，避免遗留未关闭连接。
        self.addCleanup(engine.dispose)
        with Session(engine, future=True, expire_on_commit=True) as session:
            with mock.patch.object(
                Session,
                "flush",
                autospec=True,
                side_effect=ValueError(
                    "RAW DataError detail must never surface"
                ),
            ):
                with self.assertRaises(fixture.FixtureError) as caught:
                    fixture.run_publish(session, 2, 1, 1)
        self.assertEqual(caught.exception.code, fixture.ERR_DB_OPERATIONAL)
        self.assertEqual(
            caught.exception.message, fixture.MESSAGE_DB_OPERATIONAL
        )
        self.assertNotIn("RAW DataError", caught.exception.message)

    def test_control_post_commit_read_triggers_one_refresh_select(self):
        """对照组：提交后读 ORM 属性确实触发一次刷新 SELECT。

        证明上面的零语句断言并非形式（复审所描述的旧行为路径）。
        """
        from sqlalchemy import event, select
        from sqlalchemy.orm import Session
        from app.models import PromptContractVersion

        engine = _memory_prompt_engine()
        # 离线测试资源清理：内存引擎显式 dispose，避免遗留未关闭连接。
        self.addCleanup(engine.dispose)
        recorder = self._post_commit_recorder(engine)
        with Session(
            engine, future=True, expire_on_commit=True
        ) as session:
            anchor = session.execute(
                select(PromptContractVersion).where(
                    PromptContractVersion.task_type
                    == fixture.FIXTURE_TASK_TYPE
                )
            ).scalar_one()
            session.commit()
            # 统计起点：commit 完成之后（模拟 run_publish 返回前状态）。
            recorder["on"] = True
            before = len(recorder["statements"])
            _ = anchor.guidance_fields  # 旧行为模式：提交后读 ORM 属性
            refreshed = len(recorder["statements"]) - before
        self.assertEqual(refreshed, 1)


class CliErrorBoundaryTests(unittest.TestCase):
    """CLI 边界：核心错误→固定码输出；未预期错误不透传原始细节。"""

    def _main_with_core(self, side_effect):
        from unittest import mock

        saved_switch = os.environ.pop(fixture.PUBLISH_SWITCH_VAR, None)
        saved_dsn = os.environ.pop(fixture.DSN_ENV_VAR, None)
        try:
            os.environ[fixture.PUBLISH_SWITCH_VAR] = "yes"
            os.environ[fixture.DSN_ENV_VAR] = (
                f"mysql+pymysql://u:{SECRET_MARKER}@127.0.0.1:13386/"
                "kg_next_ai1c_fixture"
            )
            with mock.patch.object(
                fixture, "run_publish_command", side_effect=side_effect
            ):
                exit_code = fixture.main([
                    "--mode",
                    "acceptance",
                    "publish-v2",
                    "--expected-contract-version",
                    "1",
                    "--expected-default-revision",
                    "1",
                ])
        finally:
            os.environ.pop(fixture.PUBLISH_SWITCH_VAR, None)
            os.environ.pop(fixture.DSN_ENV_VAR, None)
            if saved_switch is not None:
                os.environ[fixture.PUBLISH_SWITCH_VAR] = saved_switch
            if saved_dsn is not None:
                os.environ[fixture.DSN_ENV_VAR] = saved_dsn
        return exit_code

    def test_commit_uncertain_maps_to_fixed_cli_output(self):
        import contextlib
        import io

        stderr = io.StringIO()
        stdout = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            exit_code = self._main_with_core(
                fixture.FixtureError(
                    fixture.ERR_COMMIT_UNCERTAIN,
                    fixture.MESSAGE_COMMIT_UNCERTAIN,
                ),
            )
        self.assertNotEqual(exit_code, 0)
        combined = stdout.getvalue() + stderr.getvalue()
        self.assertIn(
            f"{fixture.ERR_COMMIT_UNCERTAIN}: "
            f"{fixture.MESSAGE_COMMIT_UNCERTAIN}",
            stderr.getvalue(),
        )
        self.assertNotIn(SECRET_MARKER, combined)
        self.assertNotIn("Traceback", combined)

    def test_unexpected_error_never_leaks_raw_detail(self):
        import contextlib
        import io

        stderr = io.StringIO()
        stdout = io.StringIO()
        raw_marker = "RAW-UNEXPECTED-DETAIL-MUST-NOT-PRINT"
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            exit_code = self._main_with_core(
                RuntimeError(f"boom {raw_marker}"),
            )
        self.assertNotEqual(exit_code, 0)
        combined = stdout.getvalue() + stderr.getvalue()
        self.assertIn(
            f"{fixture.ERR_UNEXPECTED}: {fixture.MESSAGE_UNEXPECTED}",
            stderr.getvalue(),
        )
        self.assertNotIn(raw_marker, combined)
        self.assertNotIn(SECRET_MARKER, combined)
        self.assertNotIn("Traceback", combined)
        # 未预期路径也不声称确定回滚。
        self.assertNotIn("事务已回滚", combined)


class SanitizedFailureOutputTests(unittest.TestCase):
    """固定错误输出不含合成敏感标记或 DSN；无 traceback 展开。"""

    def _run_cli(self, argv: list[str]) -> subprocess.CompletedProcess:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in LEAKED_ENV
        }
        environment["APP_DISABLE_DOTENV"] = "1"
        return subprocess.run(
            [PYTHON, str(SCRIPT_PATH), *argv],
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_bad_environment_error_is_sanitized(self):
        bad_dsn = (
            f"mysql+pymysql://operator:{SECRET_MARKER}@10.0.0.1:13386/"
            "kg_next_i5_acceptance"
        )
        os.environ[fixture.PUBLISH_SWITCH_VAR] = "yes"
        error_code = None
        message = None
        try:
            os.environ[fixture.DSN_ENV_VAR] = bad_dsn
            fixture.run_publish_command(
                mode="acceptance",
                target_version=2,
                expected_contract=1,
                expected_default=1,
            )
        except fixture.FixtureGuardError as error:
            error_code = error.code
            message = str(error)
        finally:
            os.environ.pop(fixture.PUBLISH_SWITCH_VAR, None)
            os.environ.pop(fixture.DSN_ENV_VAR, None)
        self.assertEqual(error_code, fixture.ERR_TARGET_REFUSED)
        self.assertNotIn(SECRET_MARKER, message)
        self.assertNotIn("kg_next_i5_acceptance", message)
        self.assertNotIn("10.0.0.1", message)
        completed = self._run_cli(["--mode", "acceptance", "inspect"])
        self.assertEqual(completed.returncode, 2)
        self.assertNotIn(SECRET_MARKER, completed.stdout + completed.stderr)
        self.assertNotIn("Traceback", completed.stdout + completed.stderr)

    def test_failed_publish_message_has_no_synthetic_secret(self):
        completed = self._run_cli(
            [
                "--mode",
                "acceptance",
                "publish-v2",
                "--expected-contract-version",
                "0",
                "--expected-default-revision",
                "1",
            ]
        )
        # argparse 层拒绝；任何输出都不含敏感标记或 DSN。
        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn(SECRET_MARKER, completed.stdout + completed.stderr)
        self.assertNotIn("Traceback", completed.stdout + completed.stderr)

    def test_cli_output_is_sanitized_across_failures(self):
        for argv in (
            ["--mode", "acceptance", "inspect"],
            [
                "--mode",
                "acceptance",
                "publish-v2",
                "--expected-contract-version",
                "1",
                "--expected-default-revision",
                "1",
            ],
        ):
            completed = self._run_cli(argv)
            self.assertNotIn(SECRET_MARKER, completed.stdout + completed.stderr)
            self.assertNotIn("1.5", completed.stdout + completed.stderr)
            self.assertNotIn("Traceback", completed.stdout + completed.stderr)
        bad_dsn = (
            f"mysql+pymysql://operator:{SECRET_MARKER}@10.0.0.1:13386/"
            "kg_next_i5_acceptance"
        )
        completed = subprocess.run(
            [PYTHON, str(SCRIPT_PATH), "--mode", "acceptance", "inspect"],
            env={
                **{
                    k: v
                    for k, v in os.environ.items()
                    if k not in LEAKED_ENV
                },
                "APP_DISABLE_DOTENV": "1",
                fixture.DSN_ENV_VAR: bad_dsn,
            },
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn(SECRET_MARKER, completed.stdout + completed.stderr)
        self.assertNotIn("Traceback", completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
