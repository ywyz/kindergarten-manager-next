"""AI 1B API/permission integration tests against real MySQL ASGI stack.

Real cookies -> real get_auth_snapshot -> real services -> real MySQL
(the AI1A guard whitelist on 127.0.0.1:13387). No business service or
identity dependency is mocked. A fixture only controls request timing:
the 1B-repair R1 tests take the timing hook BETWEEN the real cookie
snapshot and the service lock path (before any account lock is taken),
so a second connection can commit a revocation/deactivation/auth_version
change outside the request without any lock-wait deadlock.

Covers the 1B-review R1 (identity failure matrix, admin/teacher self
isolation, snapshot→lock external identity change) and R2 (unselected
field preservation, reject idempotency markers + event reconciliation,
v2 reject 409, full re-connect reconciliation of failed writes,
ciphertext rotation/reconcile, master-key missing/wrong boundaries).
"""

import json
import os
import unittest
from unittest import mock

os.environ.setdefault("APP_DISABLE_DOTENV", "1")  # guard also forces this

from fastapi import Depends, Request  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import security  # noqa: E402
from app.database import get_db  # noqa: E402
from app.deps import get_auth_snapshot  # noqa: E402
from app.main import app  # noqa: E402
from app.services import ai_config_service, auth_service  # noqa: E402

from tests.integration import test_ai1a_config_prompts as ai1a  # noqa: E402
from tests.integration.ai1a_guard import (  # noqa: E402
    INTEGRATION_ENABLED,
    make_engine,
    reset_ai1a_tables,
    skip_unless_enabled,
)
from tests.integration.i4_support import AsgiClient  # noqa: E402

TASK = ai1a.TASK
SECRET_MARKER = "sk-ai1b-synthetic-marker-7788"
SECRET_ROTATE_MARKER = "sk-ai1b-synthetic-rotated-99"

CONFIG_META = {
    "protocol_id": "chat_completions_v1",
    "base_url": "https://api.example.com/v1",
    "model": "m1",
}


def _client_for(account: dict) -> AsgiClient:
    client = AsgiClient()
    client.cookies["session"] = "tok-" + account["id"]
    return client


def _raw(client: AsgiClient, method: str, path: str, payload=None):
    response = client.request(method, path, json_body=payload)
    try:
        body = json.loads(response.content.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        body = None
    return response.status_code, dict(response.headers_list), body


def _count(engine, table: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar())


def _accounts_version(engine, account_id: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT version FROM accounts WHERE id = :id"),
                {"id": account_id},
            ).scalar()
        )


def _head_version(engine, account_id: str):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT config_version FROM ai_config_heads "
                "WHERE account_id = :id"
            ),
            {"id": account_id},
        ).scalar()


def _prompt_state(engine, account_id: str):
    """(head revision, adaptation_state, seen, rejected) 或 None。"""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT current_personal_revision, adaptation_state, "
                "last_seen_default_revision, last_rejected_default_revision "
                "FROM personal_prompt_heads WHERE account_id = :a "
                "AND task_type = :t"
            ),
            {"a": account_id, "t": TASK},
        ).fetchone()
    return tuple(row) if row else None


def _versions(engine, table: str, account_id: str, column: str) -> list[int]:
    with engine.connect() as conn:
        return [
            int(r[0])
            for r in conn.execute(
                text(
                    f"SELECT {column} FROM `{table}` "
                    "WHERE account_id = :id ORDER BY 1"
                ),
                {"id": account_id},
            ).fetchall()
        ]


def _event_count(engine, kind: str | None = None) -> int:
    with engine.connect() as conn:
        sql = (
            "SELECT COUNT(*) FROM prompt_change_records"
        )
        params: dict = {}
        if kind:
            sql += " WHERE event_kind = :k"
            params["k"] = kind
        return int(conn.execute(text(sql), params).scalar())


def _ops_count(engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(
            text("SELECT COUNT(*) FROM operation_records")
        ).scalar())


@skip_unless_enabled
class Ai1bSettingsApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = make_engine("kindergarten_test_ai1a_fresh")

    def setUp(self) -> None:
        ai1a._world(self.engine)
        ai1a._set_material(os.urandom(32), "ai1b-key")
        self.addCleanup(ai1a._clear_material)
        self.admin = _client_for(ai1a.ADMIN)
        self.teacher_a = _client_for(ai1a.TEACHER_A)
        self.teacher_b = _client_for(ai1a.TEACHER_B)
        # 待分配教师（无班级/无 can_prepare）：建独立账号。
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO accounts (id, username, password_hash, "
                    "display_name, role, is_active, version, auth_version, "
                    "created_at, updated_at) VALUES "
                    "('tow_free', 'tow_free', 'x', '待分配', 'teacher', 1, 1, "
                    "1, '2026-08-01', '2026-08-01')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO sessions (id, token_hash, account_id, "
                    "auth_version, created_at, expires_at, revoked_at) "
                    "VALUES ('sess_free', :hash, 'tow_free', 1, "
                    "'2026-08-01', '2100-01-01', NULL)"
                ),
                {"hash": security.hash_token("tok-tow_free")},
            )
        self.free = AsgiClient()
        self.free.cookies["session"] = "tok-tow_free"
        self.anon = AsgiClient()

    # -- B5: identity / permission matrix over real cookies -----------------

    def test_anonymous_and_bad_cookie_401(self):
        status, _, body = _raw(self.anon, "GET", "/api/settings/ai-config")
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "AUTH_REQUIRED")
        bad = AsgiClient()
        bad.cookies["session"] = "tok-no-such-session"
        status, _, body = _raw(bad, "GET", "/api/settings/prompts")
        self.assertEqual(status, 401)

    def test_admin_routes_require_admin_even_for_unknown_task(self):
        for method, path in (
            ("GET", "/api/admin/prompt-defaults/not_a_task"),
            ("PATCH", "/api/admin/prompt-defaults/not_a_task"),
        ):
            status, _, body = _raw(
                self.teacher_a, method, path,
                {"expected_default_revision": 1, "guidance_map": {"a": "b"}}
                if method == "PATCH" else None,
            )
            self.assertEqual(status, 403)
            self.assertEqual(body["error"]["code"], "FORBIDDEN")

    def test_admin_unknown_task_404(self):
        status, _, body = _raw(
            self.admin, "GET", "/api/admin/prompt-defaults/not_a_task"
        )
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "TASK_TYPE_NOT_FOUND")

    def test_pending_teacher_manages_own_settings(self):
        status, _, body = _raw(self.free, "GET", "/api/settings/ai-config")
        self.assertEqual(status, 200)
        self.assertEqual(body["version"], 0)
        self.assertFalse(body["ready"])
        status, _, body = _raw(
            self.free, "PATCH", "/api/settings/ai-config",
            {
                "expected_version": 0,
                "protocol_id": "chat_completions_v1",
                "base_url": "https://api.example.com/v1",
                "model": "m1",
                "secret": SECRET_MARKER,
            },
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["version"], 1)
        self.assertTrue(body["has_secret"])
        self.assertTrue(body["ready"])
        status, _, body = _raw(
            self.free, "POST",
            f"/api/settings/prompts/{TASK}/initialize", {},
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["personal_revision"], 1)

    def test_personal_routes_are_self_scoped(self):
        status, _, body = _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {
                "expected_version": 0,
                "protocol_id": "chat_completions_v1",
                "base_url": "https://api.example.com/v1",
                "model": "a",
                "secret": "A-KEY",
            },
        )
        self.assertEqual(status, 200, body)
        # B 读到的仍是自己的（未配置），不是 A 的。
        status, _, body = _raw(self.teacher_b, "GET", "/api/settings/ai-config")
        self.assertEqual(status, 200)
        self.assertEqual(body["version"], 0)
        self.assertFalse(body["has_secret"])
        # admin 的本人配置与老师互不影响。
        status, _, body = _raw(self.admin, "GET", "/api/settings/ai-config")
        self.assertEqual(body["version"], 0)

    # -- B5: 身份失效矩阵（真 cookie，逐项独立） ------------------------------
    #
    # S1(re-review 修复)：四种身份条件不能连续累积 —— 每例先恢复完整有效
    # 账号/会话，用同一 cookie 确认合法 GET 200，再只改变该例目标身份
    # 条件，重连核对除目标条件外其余身份条件全部有效，然后合法
    # GET/PATCH 得 401，并逐例重连核对完整写集合零增量（不能只在循环
    # 末尾核对总量）。

    _LABEL_TO_FLAG = {
        "expired": "not_expired",
        "revoked": "not_revoked",
        "deactivated": "active",
        "auth_version_mismatch": "auth_version_ok",
    }

    _CASES = (
        # (label, 目标 UPDATE, 该例目标条件的重连确认 SQL)
        ("expired",
         "UPDATE sessions SET expires_at = '2020-01-01' WHERE id = :sid",
         "SELECT expires_at <= UTC_TIMESTAMP() FROM sessions "
         "WHERE id = :sid"),
        ("revoked",
         "UPDATE sessions SET revoked_at = NOW() WHERE id = :sid",
         "SELECT revoked_at IS NOT NULL FROM sessions WHERE id = :sid"),
        ("deactivated",
         "UPDATE accounts SET is_active = 0 WHERE id = :id",
         "SELECT is_active = 0 FROM accounts WHERE id = :id"),
        ("auth_version_mismatch",
         "UPDATE accounts SET auth_version = 2 WHERE id = :id",
         "SELECT auth_version = 2 FROM accounts WHERE id = :id"),
    )

    def _restore_identity(self) -> None:
        """恢复完整有效身份：teacher_a 的账号/会话全部回到有效状态。

        每例身份变化独立：回到初始有效快照（is_active=1、
        auth_version/version=1、未撤销、未过期），不叠加任何前例的
        失效状态。"""
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE accounts SET is_active = 1, auth_version = 1, "
                    "version = 1, password_hash = 'x' WHERE id = :id"
                ),
                {"id": ai1a.TEACHER_A["id"]},
            )
            conn.execute(
                text(
                    "UPDATE sessions SET expires_at = '2100-01-01', "
                    "revoked_at = NULL, auth_version = 1 WHERE id = :sid"
                ),
                {"sid": ai1a.TEACHER_A["session"]},
            )

    def _identity_flags_all(self) -> dict:
        """重连读取 teacher_a 全部四个身份条件的有效性。"""
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT a.is_active = 1, a.auth_version = 1, "
                    "s.revoked_at IS NULL, s.expires_at > UTC_TIMESTAMP() "
                    "FROM accounts a JOIN sessions s "
                    "ON s.account_id = a.id WHERE a.id = :a "
                    "AND s.id = :sid"
                ),
                {"a": ai1a.TEACHER_A["id"],
                 "sid": ai1a.TEACHER_A["session"]},
            ).fetchone()
        return {
            "active": bool(row[0]),
            "auth_version_ok": bool(row[1]),
            "not_revoked": bool(row[2]),
            "not_expired": bool(row[3]),
        }

    def _identity_flags_others(self, target_label: str) -> dict:
        """除目标条件外，其余身份条件在当前库内全部有效。"""
        flags = self._identity_flags_all()
        return {
            k: v for k, v in flags.items()
            if k != self._LABEL_TO_FLAG[target_label]
        }

    def _write_counters(self) -> dict:
        """完整写集合计数：审计/事件/配置版本/个人版本/默认修订/账号版本。"""
        return {
            "ops": _ops_count(self.engine),
            "events": _event_count(self.engine),
            "cfgv": _count(self.engine, "ai_config_versions"),
            "ppv": _count(self.engine, "personal_prompt_versions"),
            "pdv": _count(self.engine, "prompt_default_versions"),
            "acc": _accounts_version(self.engine, ai1a.TEACHER_A["id"]),
        }

    def test_identity_failure_matrix_401(self):
        """过期／撤销／停用／auth_version 不符逐例独立 401。

        每例：恢复完整有效身份 -> 同 cookie 合法 GET 200 基线 -> 只改
        该例目标条件 -> 重连确认目标条件已失效且其余三个身份条件仍
        有效 -> 合法 GET 与合法 PATCH 均 401 -> 重连核对完整写集合
        （审计/事件/两版本表/默认修订/accounts.version）相对本请求
        零增量、head 仍不存在。
        """
        teacher_session = ai1a.TEACHER_A["session"]
        legal_patch_payload = {
            "expected_version": 0,
            **CONFIG_META,
            "secret": SECRET_MARKER,
        }
        for label, sql, flag_sql in self._CASES:
            # (1) 恢复完整有效身份（不叠加前一例的失效状态）。
            self._restore_identity()
            params = (
                {"sid": teacher_session} if "sessions" in sql
                else {"id": ai1a.TEACHER_A["id"]}
            )
            # (2) 同一 cookie 的合法 GET 200 基线。
            status, _, baseline_body = _raw(
                self.teacher_a, "GET", "/api/settings/ai-config"
            )
            self.assertEqual(
                status, 200, f"{label}: 恢复后 GET 应 200: {baseline_body}"
            )
            # (3) 本例写集合计数基线。
            counts_before = self._write_counters()
            # (4) 只改变该例目标身份条件（另一连接提交）。
            with self.engine.begin() as conn:
                conn.execute(text(sql), params)
            # (5) 重连核对：目标条件已失效；其余身份条件全部仍有效。
            with self.engine.connect() as conn:
                target_broken = conn.execute(
                    text(flag_sql), params
                ).scalar()
            self.assertTrue(
                bool(target_broken), f"{label}: 目标条件应已失效"
            )
            others = self._identity_flags_others(label)
            self.assertTrue(
                all(others.values()),
                f"{label}: 其余身份条件不应被波及: {others}",
            )
            # (6) 合法 GET 与合法 PATCH 均 401（仅身份失效）。
            status, _, body = _raw(
                self.teacher_a, "GET", "/api/settings/ai-config"
            )
            self.assertEqual(status, 401, f"{label}: {body}")
            self.assertEqual(body["error"]["code"], "AUTH_REQUIRED", label)
            status, _, body = _raw(
                self.teacher_a, "PATCH", "/api/settings/ai-config",
                legal_patch_payload,
            )
            self.assertEqual(status, 401, f"{label}: {body}")
            self.assertEqual(body["error"]["code"], "AUTH_REQUIRED", label)
            # (7) 逐例重连核对：本例对完整写集合零增量。
            counts_after = self._write_counters()
            self.assertEqual(
                counts_before, counts_after,
                f"{label}: 401 请求产生了写增量",
            )
            self.assertEqual(
                _head_version(self.engine, ai1a.TEACHER_A["id"]), None
            )
        # 兜底总量核对（与逐例断言构成双保险）。
        self.assertEqual(
            _count(self.engine, "ai_config_versions"), 0,
            "全矩阵不应产生配置版本行",
        )
        self.assertEqual(_ops_count(self.engine), 0)
        self.assertEqual(_event_count(self.engine), 0)


    def test_admin_saves_own_config_then_isolation_both_ways(self):
        """管理员实际保存本人配置；教师与管理员本人配置互相隔离。"""
        status, _, admin_body = _raw(
            self.admin, "PATCH", "/api/settings/ai-config",
            {
                "expected_version": 0,
                "protocol_id": "chat_completions_v1",
                "base_url": "https://api.admin.example/v1",
                "model": "admin-model",
                "secret": "ADMIN-OWN-KEY",
            },
        )
        self.assertEqual(status, 200, admin_body)
        self.assertEqual(admin_body["model"], "admin-model")
        self.assertEqual(admin_body["version"], 1)
        status, _, teacher_body = _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {
                "expected_version": 0,
                "protocol_id": "chat_completions_v1",
                "base_url": "https://api.teacher.example/v1",
                "model": "teacher-model",
                "secret": "TEACHER-OWN-KEY",
            },
        )
        self.assertEqual(status, 200, teacher_body)
        # 管理员读到的是自己的配置，不是教师的。
        status, _, admin_get = _raw(
            self.admin, "GET", "/api/settings/ai-config"
        )
        self.assertEqual(admin_get["model"], "admin-model")
        self.assertEqual(admin_get["version"], 1)
        # 教师读到的是自己的配置，不是管理员的。
        status, _, teacher_get = _raw(
            self.teacher_a, "GET", "/api/settings/ai-config"
        )
        self.assertEqual(teacher_get["model"], "teacher-model")
        self.assertEqual(teacher_get["version"], 1)
        # 库内确认两账号各自 head 与版本行。
        self.assertEqual(
            _count(self.engine, "ai_config_versions"), 2
        )
        self.assertEqual(
            _versions(
                self.engine, "ai_config_versions", ai1a.ADMIN["id"], "version"
            ),
            [1],
        )
        self.assertEqual(
            _versions(
                self.engine, "ai_config_versions",
                ai1a.TEACHER_A["id"], "version",
            ),
            [1],
        )

    # -- B5/R1: snapshot 已形成、服务锁未取得前的外部身份变化 ----------------

    def _request_with_identity_tamper(
        self, client, method, path, payload, sql, params
    ):
        """时序夹具：真实 get_auth_snapshot 先形成 snapshot（真 cookie），
        snapshot 返回后、服务事务取锁之前，用另一连接提交外部身份变化，
        然后继续真实服务复核。不 mock 业务服务或身份结果；
        外部变化在请求事务开始前提交，不会与 account 锁互相等待。"""
        real_snapshot_dep = get_auth_snapshot

        def timed_snapshot(request: Request, db: Session = Depends(get_db)):
            snapshot = real_snapshot_dep(request, db)  # 真实身份判定
            # snapshot 已形成；服务尚未 begin/lock —— 无锁可死锁：
            with self.engine.begin() as conn:
                conn.execute(text(sql), params)
            return snapshot

        app.dependency_overrides[get_auth_snapshot] = timed_snapshot
        try:
            return _raw(client, method, path, payload)
        finally:
            app.dependency_overrides.pop(get_auth_snapshot, None)

    def test_revoke_between_snapshot_and_lock_blocks_config_write(self):
        # 先成功建立基线（真实通过身份检查的写）。
        status, _, body = _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {"expected_version": 0, **CONFIG_META, "secret": "BASELINE"},
        )
        self.assertEqual(status, 200, body)
        baseline = {
            "ops": _ops_count(self.engine),
            "cfgv": _count(self.engine, "ai_config_versions"),
            "cfgheads": _count(self.engine, "ai_config_heads"),
            "events": _event_count(self.engine),
            "acc": _accounts_version(self.engine, ai1a.TEACHER_A["id"]),
        }
        status, _, body = self._request_with_identity_tamper(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {"expected_version": 1, **CONFIG_META, "secret": SECRET_MARKER},
            "UPDATE sessions SET revoked_at = NOW() WHERE id = :sid",
            {"sid": ai1a.TEACHER_A["session"]},
        )
        self.assertEqual(status, 401, body)
        self.assertEqual(body["error"]["code"], "AUTH_REQUIRED")
        # 重连对账：本次请求零增量。
        self.assertEqual(_ops_count(self.engine), baseline["ops"])
        self.assertEqual(
            _count(self.engine, "ai_config_versions"), baseline["cfgv"]
        )
        self.assertEqual(
            _count(self.engine, "ai_config_heads"), baseline["cfgheads"]
        )
        self.assertEqual(_event_count(self.engine), baseline["events"])
        self.assertEqual(
            _accounts_version(self.engine, ai1a.TEACHER_A["id"]),
            baseline["acc"],
        )
        self.assertEqual(
            _head_version(self.engine, ai1a.TEACHER_A["id"]), 1
        )
        # 撤销外部变化本身已生效（独立于请求）。
        with self.engine.connect() as conn:
            revoked_at = conn.execute(
                text("SELECT revoked_at FROM sessions WHERE id = :sid"),
                {"sid": ai1a.TEACHER_A["session"]},
            ).scalar()
        self.assertIsNotNone(revoked_at)

    def test_deactivate_between_snapshot_and_lock_blocks_prompt_write(self):
        _raw(self.teacher_a, "POST", f"/api/settings/prompts/{TASK}/initialize",
             {})
        expected_state = _prompt_state(self.engine, ai1a.TEACHER_A["id"])
        self.assertIsNotNone(expected_state)
        baseline_events = _event_count(self.engine)
        baseline_ops = _ops_count(self.engine)
        baseline_versions = _versions(
            self.engine, "personal_prompt_versions",
            ai1a.TEACHER_A["id"], "personal_revision",
        )
        # S1 补验：外部 UPDATE 之前先读取 accounts.version 单列基线。
        acc_version_before_external = _accounts_version(
            self.engine, ai1a.TEACHER_A["id"]
        )
        status, _, body = self._request_with_identity_tamper(
            self.teacher_a, "PATCH", f"/api/settings/prompts/{TASK}",
            {
                "expected_personal_revision": 1,
                "guidance_map": {"process": "管理员已停用后的编辑"},
            },
            "UPDATE accounts SET is_active = 0, version = version + 1, "
            "auth_version = auth_version + 1 WHERE id = :id",
            {"id": ai1a.TEACHER_A["id"]},
        )
        self.assertEqual(status, 401, body)
        self.assertEqual(body["error"]["code"], "AUTH_REQUIRED")
        # S1 补验：外部 UPDATE 的单列 +1 精确断言（不能只读取不检查）。
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT version, auth_version, is_active FROM accounts "
                    "WHERE id = :id"
                ),
                {"id": ai1a.TEACHER_A["id"]},
            ).fetchone()
        # 精确断言：恰为外部 UPDATE 的单列 +1；本 401 请求自身零增量。
        self.assertEqual(
            row[0], acc_version_before_external + 1,
            "accounts.version 应仅为外部 UPDATE 的 +1（请求零增量）",
        )
        self.assertEqual(row[1], 2)
        self.assertEqual(row[2], 0)
        # 重连后再次核对：accounts.version 稳停在基线 +1，无后续漂移。
        self.assertEqual(
            _accounts_version(self.engine, ai1a.TEACHER_A["id"]),
            acc_version_before_external + 1,
        )
        # 请求自身无版本/事件/处理标记增量。
        self.assertEqual(
            _prompt_state(self.engine, ai1a.TEACHER_A["id"]), expected_state
        )
        self.assertEqual(_event_count(self.engine), baseline_events)
        self.assertEqual(_ops_count(self.engine), baseline_ops)
        self.assertEqual(
            _versions(
                self.engine, "personal_prompt_versions",
                ai1a.TEACHER_A["id"], "personal_revision",
            ),
            baseline_versions,
        )

    def test_auth_version_change_blocks_admin_default_write(self):
        baseline_defaults = _count(self.engine, "prompt_default_versions")
        baseline_events = _event_count(self.engine)
        baseline_ops = _ops_count(self.engine)
        # S1 补验：外部变化前先读取 admin accounts.version 单列基线。
        baseline_acc_version = _accounts_version(
            self.engine, ai1a.ADMIN["id"]
        )
        status, _, body = self._request_with_identity_tamper(
            self.admin, "PATCH", f"/api/admin/prompt-defaults/{TASK}",
            {
                "expected_default_revision": 1,
                "guidance_map": {"process": "版本变化后的发布"},
            },
            "UPDATE accounts SET auth_version = auth_version + 1, "
            "version = version + 1 WHERE id = :id",
            {"id": ai1a.ADMIN["id"]},
        )
        self.assertEqual(status, 401, body)
        self.assertEqual(body["error"]["code"], "AUTH_REQUIRED")
        self.assertEqual(
            _count(self.engine, "prompt_default_versions"), baseline_defaults
        )
        self.assertEqual(_event_count(self.engine), baseline_events)
        self.assertEqual(_ops_count(self.engine), baseline_ops)
        # S1 补验（精确断言，不能只读取不检查）：请求自身对
        # accounts.version 零增量；当前值恰为外部 UPDATE 的单列 +1。
        self.assertEqual(
            _accounts_version(self.engine, ai1a.ADMIN["id"]),
            baseline_acc_version + 1,
            "accounts.version 应仅为外部 UPDATE 的 +1（写请求零增量）",
        )
        # 外部变化自身已生效：后续同 cookie 请求仍 401（与本次请求无关）。
        status, _, body = _raw(
            self.admin, "GET", f"/api/admin/prompt-defaults/{TASK}"
        )
        self.assertEqual(status, 401)

    # -- B6: read endpoints have no side effects ----------------------------

    def test_all_get_endpoints_are_side_effect_free(self):
        # 先造一点真实状态。
        _raw(self.teacher_a, "POST", f"/api/settings/prompts/{TASK}/initialize", {})
        _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {
                "expected_version": 0,
                "protocol_id": "chat_completions_v1",
                "base_url": "https://api.example.com/v1",
                "model": "m",
                "secret": "KEEP-ME",
            },
        )
        snapshot_before = {
            "heads": _count(self.engine, "personal_prompt_heads"),
            "versions": _count(self.engine, "personal_prompt_versions"),
            "events": _count(self.engine, "prompt_change_records"),
            "ops": _count(self.engine, "operation_records"),
            "cfg": _count(self.engine, "ai_config_versions"),
            "cfg_heads": _count(self.engine, "ai_config_heads"),
            "acc": _accounts_version(self.engine, ai1a.TEACHER_A["id"]),
        }
        with self.engine.connect() as conn:
            markers_before = conn.execute(
                text(
                    "SELECT last_seen_default_revision, "
                    "last_rejected_default_revision FROM personal_prompt_heads"
                )
            ).fetchall()
        for method, path in (
            ("GET", "/api/settings/ai-config"),
            ("GET", "/api/settings/prompts"),
            ("GET", f"/api/settings/prompts/{TASK}"),
            ("GET", f"/api/admin/prompt-defaults/{TASK}".replace("admin", "x") if False else f"/api/admin/prompt-defaults/{TASK}"),
        ):
            client = self.admin if "admin" in path else self.teacher_a
            status, headers, _ = _raw(client, method, path)
            self.assertEqual(status, 200)
            self.assertIn("no-store", headers.get("cache-control", ""))
        snapshot_after = {
            "heads": _count(self.engine, "personal_prompt_heads"),
            "versions": _count(self.engine, "personal_prompt_versions"),
            "events": _count(self.engine, "prompt_change_records"),
            "ops": _count(self.engine, "operation_records"),
            "cfg": _count(self.engine, "ai_config_versions"),
            "cfg_heads": _count(self.engine, "ai_config_heads"),
            "acc": _accounts_version(self.engine, ai1a.TEACHER_A["id"]),
        }
        self.assertEqual(snapshot_before, snapshot_after)
        with self.engine.connect() as conn:
            markers_after = conn.execute(
                text(
                    "SELECT last_seen_default_revision, "
                    "last_rejected_default_revision FROM personal_prompt_heads"
                )
            ).fetchall()
        self.assertEqual(markers_before, markers_after)

    def test_detail_not_initialized_shape(self):
        status, _, body = _raw(
            self.teacher_a, "GET", f"/api/settings/prompts/{TASK}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["state"], "not_initialized")
        self.assertEqual(body["personal_revision"], None)
        self.assertEqual(body["based_guidance_fields"], [])
        self.assertEqual(body["adaptation_state"], "current")
        self.assertEqual(body["pending_default_update"], False)
        self.assertIsInstance(body["latest_default"]["guidance_map"], dict)
        # 未初始化不隐式写入版本。
        self.assertEqual(_count(self.engine, "personal_prompt_heads"), 0)

    # -- B6: lifecycle over real HTTP --------------------------------------

    def test_accept_preserves_unselected_personal_edit(self):
        """R2：先改一个不会被选中的个人字段，再按字段接受，断言未选文字
        完整保留。"""
        status, _, body = _raw(
            self.teacher_a, "POST", f"/api/settings/prompts/{TASK}/initialize",
            {},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["personal_revision"], 1)
        fields = sorted(body["guidance_map"])
        self.assertGreaterEqual(len(fields), 2)
        field_edited, field_selected = fields[0], fields[1]
        # 先改不会被选中的字段：
        status, _, body = _raw(
            self.teacher_a, "PATCH", f"/api/settings/prompts/{TASK}",
            {
                "expected_personal_revision": 1,
                "guidance_map": {field_edited: "教师甲逐字保留的编辑"},
            },
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["personal_revision"], 2)
        # 管理员发布新默认（针对同样的 edited 字段之外，再给新文字）。
        status, _, body = _raw(
            self.admin, "PATCH", f"/api/admin/prompt-defaults/{TASK}",
            {
                "expected_default_revision": 1,
                "guidance_map": {
                    field_selected: "学校新默认文本",
                },
            },
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["default_revision"], 2)
        self.assertIn("guidance_fields", body)
        new_default = body["guidance_map"]
        # 按字段接受：只选 field_selected。
        status, _, body = _raw(
            self.teacher_a, "POST",
            f"/api/settings/prompts/{TASK}/accept-default",
            {
                "expected_personal_revision": 2,
                "target_default_revision": 2,
                "accepted_fields": [field_selected],
            },
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["personal_revision"], 3)
        self.assertEqual(
            body["guidance_map"][field_selected],
            new_default[field_selected],
        )
        # 未选字段的教师编辑文字完整保留（非默认文本）。
        self.assertEqual(
            body["guidance_map"][field_edited], "教师甲逐字保留的编辑"
        )
        self.assertEqual(body["accepted_default_revision"], 2)
        # 编辑文字持久：重连核对。
        status, _, detail = _raw(
            self.teacher_a, "GET", f"/api/settings/prompts/{TASK}"
        )
        self.assertEqual(detail["personal_revision"], 3)
        self.assertEqual(
            detail["guidance_map"][field_edited], "教师甲逐字保留的编辑"
        )
        # 默认发布未推进个人版本以外的东西：事件数量核对
        # （init + edit + default_update + accept = 4 个事件）。
        self.assertEqual(_event_count(self.engine), 4)
        self.assertEqual(_event_count(self.engine, "accept_default"), 1)

    def test_reject_repeat_reconcile_then_reaccept(self):
        """R2：重复拒绝对账事件数量、seen/rejected 标记和个人版本；
        之后再接受。"""
        _raw(self.teacher_a, "POST", f"/api/settings/prompts/{TASK}/initialize",
             {})
        status, _, detail = _raw(
            self.teacher_a, "GET", f"/api/settings/prompts/{TASK}"
        )
        some_field = detail["guidance_fields"][0]
        status, _, body = _raw(
            self.admin, "PATCH", f"/api/admin/prompt-defaults/{TASK}",
            {
                "expected_default_revision": 1,
                "guidance_map": {some_field: "被拒绝的新默认"},
            },
        )
        self.assertEqual(status, 200, body)
        events_after_first_publish = _event_count(self.engine)
        status, _, body = _raw(
            self.teacher_a, "POST",
            f"/api/settings/prompts/{TASK}/reject-default",
            {"expected_personal_revision": 1, "target_default_revision": 2},
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["state"], "unchanged")
        self.assertFalse(body["idempotent"])
        self.assertEqual(body["personal_revision"], 1)
        # 重复拒绝：
        status, _, body = _raw(
            self.teacher_a, "POST",
            f"/api/settings/prompts/{TASK}/reject-default",
            {"expected_personal_revision": 1, "target_default_revision": 2},
        )
        self.assertEqual(status, 200, body)
        self.assertTrue(body["idempotent"])
        # 重连对账：
        rows_before = {
            "events": _event_count(self.engine),
            "reject_events": _event_count(self.engine, "reject_default"),
            "versions": _versions(
                self.engine, "personal_prompt_versions",
                ai1a.TEACHER_A["id"], "personal_revision",
            ),
            "ops": _ops_count(self.engine),
        }
        self.assertEqual(rows_before["events"], events_after_first_publish + 1)
        self.assertEqual(rows_before["reject_events"], 1)
        self.assertEqual(rows_before["versions"], [1])
        with self.engine.connect() as conn:
            seen, rejected = conn.execute(
                text(
                    "SELECT last_seen_default_revision, "
                    "last_rejected_default_revision FROM "
                    "personal_prompt_heads WHERE account_id = :a "
                    "AND task_type = :t"
                ),
                {"a": ai1a.TEACHER_A["id"], "t": TASK},
            ).fetchone()
        self.assertEqual(seen, 2)
        self.assertEqual(rejected, 2)
        # 管理员发布一版相同的文字不会新增对账目标（幂等仍是 1 事件）。
        expected_ops_after = rows_before["ops"]
        status, _, body = _raw(
            self.teacher_a, "POST",
            f"/api/settings/prompts/{TASK}/reject-default",
            {"expected_personal_revision": 1, "target_default_revision": 2},
        )
        self.assertTrue(body["idempotent"])
        self.assertEqual(_event_count(self.engine, "reject_default"), 1)
        self.assertEqual(_ops_count(self.engine), expected_ops_after + 0)
        # 之后再主动接受同一默认仍可成功。
        status, _, body = _raw(
            self.teacher_a, "POST",
            f"/api/settings/prompts/{TASK}/accept-default",
            {
                "expected_personal_revision": 1,
                "target_default_revision": 2,
                "accepted_fields": [some_field],
            },
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["guidance_map"][some_field], "被拒绝的新默认")
        status, _, detail = _raw(
            self.teacher_a, "GET", f"/api/settings/prompts/{TASK}"
        )
        # 接受后拒绝标记清除。
        self.assertIsNone(detail["last_rejected_default_revision"])
        with self.engine.connect() as conn:
            seen, rejected = conn.execute(
                text(
                    "SELECT last_seen_default_revision, "
                    "last_rejected_default_revision FROM "
                    "personal_prompt_heads WHERE account_id = :a "
                    "AND task_type = :t"
                ),
                {"a": ai1a.TEACHER_A["id"], "t": TASK},
            ).fetchone()
        self.assertEqual(seen, 2)
        self.assertIsNone(rejected)

    def test_conflict_versions_409_and_school_version_untouched(self):
        """旧 expected 冲突 409；默认发布不改 school_settings.version。"""
        _raw(self.teacher_a, "POST", f"/api/settings/prompts/{TASK}/initialize",
             {})
        status, _, detail = _raw(
            self.teacher_a, "GET", f"/api/settings/prompts/{TASK}"
        )
        some_field = detail["guidance_fields"][0]
        # 真实编辑推进到 rev2，之后旧 expected 才是“旧 expected”。
        status, _, body = _raw(
            self.teacher_a, "PATCH", f"/api/settings/prompts/{TASK}",
            {
                "expected_personal_revision": 1,
                "guidance_map": {some_field: "教师甲的编辑"},
            },
        )
        self.assertEqual(status, 200, body)
        status, _, body = _raw(
            self.teacher_a, "PATCH", f"/api/settings/prompts/{TASK}",
            {
                "expected_personal_revision": 1,
                "guidance_map": {some_field: "冲突"},
            },
        )
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "VERSION_CONFLICT")
        status, _, body = _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {"expected_version": 5, **CONFIG_META},
        )
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "VERSION_CONFLICT")
        # 管理员发布成功但 school version 不变。
        status, _, _ = _raw(
            self.admin, "PATCH", f"/api/admin/prompt-defaults/{TASK}",
            {
                "expected_default_revision": 1,
                "guidance_map": {some_field: "学校新默认"},
            },
        )
        self.assertEqual(_event_count(self.engine, "default_update"), 1)
        with self.engine.connect() as conn:
            school_version = conn.execute(
                text("SELECT version FROM school_settings WHERE id = 'singleton'")
            ).scalar()
        self.assertEqual(school_version, 1)

    def test_accept_requires_initialized(self):
        status, _, body = _raw(
            self.teacher_a, "POST",
            f"/api/settings/prompts/{TASK}/accept-default",
            {
                "expected_personal_revision": 1,
                "target_default_revision": 1,
                "accepted_fields": ["theme"],
            },
        )
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "PROMPT_NOT_INITIALIZED")

    def test_failed_writes_reconcile_full_state(self):
        """R2：旧 expected／非法结构失败后，重连核对完整
        head/版本/事件/审计/处理标记/accounts.version 不变。"""
        # 先建立个人与配置基线。
        _raw(self.teacher_a, "POST", f"/api/settings/prompts/{TASK}/initialize",
             {})
        _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {"expected_version": 0, **CONFIG_META, "secret": "CIPHER-BASE"},
        )
        status, _, detail = _raw(
            self.teacher_a, "GET", f"/api/settings/prompts/{TASK}"
        )
        self.assertEqual(status, 200)
        some_field = detail["guidance_fields"][0]
        v1_fields = list(detail["guidance_fields"])
        ai1a.publish_variant_contract(self.engine, TASK, "v2_new_field")

        def snapshot_state():
            with self.engine.connect() as conn:
                prompt_head = conn.execute(
                    text(
                        "SELECT current_personal_revision, "
                        "adaptation_state, required_contract_version, "
                        "last_seen_default_revision, "
                        "last_rejected_default_revision FROM "
                        "personal_prompt_heads WHERE account_id = :a "
                        "AND task_type = :t"
                    ),
                    {"a": ai1a.TEACHER_A["id"], "t": TASK},
                ).fetchone()
                return {
                    "prompt_head": tuple(prompt_head),
                    "versions": _versions(
                        self.engine, "personal_prompt_versions",
                        ai1a.TEACHER_A["id"], "personal_revision",
                    ),
                    "events": _event_count(self.engine),
                    "ops": _ops_count(self.engine),
                    "cfg_versions": _versions(
                        self.engine, "ai_config_versions",
                        ai1a.TEACHER_A["id"], "version",
                    ),
                    "cfg_head": _head_version(
                        self.engine, ai1a.TEACHER_A["id"]
                    ),
                    "acc": _accounts_version(
                        self.engine, ai1a.TEACHER_A["id"]
                    ),
                    "defaults": _count(
                        self.engine, "prompt_default_versions"
                    ),
                }

        before = snapshot_state()
        failures = [
            ("PATCH", "/api/settings/ai-config",
             {"expected_version": 0, **CONFIG_META,
              "secret": "旧 expected 写入"},
             409),
            ("DELETE", "/api/settings/ai-config",
             {"expected_version": 9},
             409),
            ("PATCH", f"/api/settings/prompts/{TASK}",
             {"expected_personal_revision": 9,
              "guidance_map": {some_field: "冲突"}},
             409),
            # 非法结构：v1-based 个人编辑包含未知字段。
            ("PATCH", f"/api/settings/prompts/{TASK}",
             {"expected_personal_revision": 1,
              "guidance_map": {v1_fields[0]: "旧字段编辑",
                               "v2_new_field": "越权字段"}},
             422),
            # 缺适配字段 422。
            ("POST", f"/api/settings/prompts/{TASK}/adapt",
             {"expected_personal_revision": 1,
              "target_contract_version": 2,
              "guidance_map": {k: "v" for k in v1_fields}},
             422),
            # 未知适配字段 422。
            ("POST", f"/api/settings/prompts/{TASK}/adapt",
             {"expected_personal_revision": 1,
              "target_contract_version": 2,
              "guidance_map": {**{k: "v" for k in v1_fields},
                               "v2_new_field": "新", "bogus": "x"}},
             422),
            # 旧 contract 的 adapt 409。
            ("POST", f"/api/settings/prompts/{TASK}/adapt",
             {"expected_personal_revision": 1,
              "target_contract_version": 1,
              "guidance_map": {k: "v" for k in v1_fields}},
             409),
            # 待适配时 accept/reject 409。
            ("POST", f"/api/settings/prompts/{TASK}/accept-default",
             {"expected_personal_revision": 1,
              "target_default_revision": 1,
              "accepted_fields": [v1_fields[0]]},
             409),
            ("POST", f"/api/settings/prompts/{TASK}/reject-default",
             {"expected_personal_revision": 1,
              "target_default_revision": 1},
             409),
            # 不存在的目标默认修订 409。
            ("POST", f"/api/settings/prompts/{TASK}/accept-default",
             {"expected_personal_revision": 1,
              "target_default_revision": 99,
              "accepted_fields": [v1_fields[0]]},
             409),
        ]
        for method, path, payload, expected_status in failures:
            status, _, body = _raw(self.teacher_a, method, path, payload)
            self.assertEqual(
                status, expected_status,
                f"{method} {path} {payload}: {body}",
            )
            after = snapshot_state()
            self.assertEqual(
                before, after, f"失败写 {method} {path} 产生了增量"
            )
        # 重连最终一致性：
        self.assertEqual(before, snapshot_state())

    def test_v2_contract_adaptation_flow(self):
        _raw(self.teacher_a, "POST", f"/api/settings/prompts/{TASK}/initialize", {})
        status, _, detail = _raw(
            self.teacher_a, "GET", f"/api/settings/prompts/{TASK}"
        )
        v1_fields = list(detail["based_guidance_fields"])
        ai1a.publish_variant_contract(self.engine, TASK, "v2_new_field")
        status, _, detail = _raw(
            self.teacher_a, "GET", f"/api/settings/prompts/{TASK}"
        )
        self.assertEqual(detail["adaptation_state"], "adaptation_required")
        self.assertEqual(detail["required_contract_version"], 2)
        self.assertEqual(detail["based_guidance_fields"], v1_fields)
        self.assertEqual(detail["latest_contract_version"], 2)
        # 普通编辑旧字段仍可用且保持待适配。
        status, _, body = _raw(
            self.teacher_a, "PATCH", f"/api/settings/prompts/{TASK}",
            {
                "expected_personal_revision": 1,
                "guidance_map": {v1_fields[0]: "旧字段编辑"},
            },
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["adaptation_state"], "adaptation_required")
        # 待适配时 accept/reject 阻断（R2: 实际发送 reject）。
        status, _, body = _raw(
            self.teacher_a, "POST",
            f"/api/settings/prompts/{TASK}/accept-default",
            {
                "expected_personal_revision": 2,
                "target_default_revision": 2,
                "accepted_fields": [v1_fields[0]],
            },
        )
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "PROMPT_ADAPTATION_REQUIRED")
        status, _, body = _raw(
            self.teacher_a, "POST",
            f"/api/settings/prompts/{TASK}/reject-default",
            {"expected_personal_revision": 2, "target_default_revision": 2},
        )
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "PROMPT_ADAPTATION_REQUIRED")
        # 拒绝被拒后标记不变：重连核对。
        with self.engine.connect() as conn:
            rejected = conn.execute(
                text(
                    "SELECT last_rejected_default_revision, "
                    "last_seen_default_revision FROM personal_prompt_heads "
                    "WHERE account_id = :a AND task_type = :t"
                ),
                {"a": ai1a.TEACHER_A["id"], "t": TASK},
            ).fetchone()
        self.assertIsNone(rejected[0])
        self.assertEqual(rejected[1], 1)
        # 旧 contract 的 adapt 被拒。
        status, _, body = _raw(
            self.teacher_a, "POST", f"/api/settings/prompts/{TASK}/adapt",
            {
                "expected_personal_revision": 2,
                "target_contract_version": 1,
                "guidance_map": {k: "v" for k in v1_fields},
            },
        )
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "PROMPT_CONTRACT_CHANGED")
        # 缺新字段的 adapt 422；未知字段 422。
        status, _, body = _raw(
            self.teacher_a, "POST", f"/api/settings/prompts/{TASK}/adapt",
            {
                "expected_personal_revision": 2,
                "target_contract_version": 2,
                "guidance_map": {k: "v" for k in v1_fields},
            },
        )
        self.assertEqual(status, 422)
        status, _, body = _raw(
            self.teacher_a, "POST", f"/api/settings/prompts/{TASK}/adapt",
            {
                "expected_personal_revision": 2,
                "target_contract_version": 2,
                "guidance_map": {**{k: "v" for k in v1_fields},
                                 "v2_new_field": "新", "bogus": "x"},
            },
        )
        self.assertEqual(status, 422)
        # 完整 v2 字段集 adapt 成功。
        status, _, body = _raw(
            self.teacher_a, "POST", f"/api/settings/prompts/{TASK}/adapt",
            {
                "expected_personal_revision": 2,
                "target_contract_version": 2,
                "guidance_map": {**{k: "v" for k in v1_fields},
                                 "v2_new_field": "新"},
            },
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["based_contract_version"], 2)
        self.assertEqual(body["adaptation_state"], "current")
        # 适配后新字段可编辑。
        status, _, body = _raw(
            self.teacher_a, "PATCH", f"/api/settings/prompts/{TASK}",
            {
                "expected_personal_revision": 3,
                "guidance_map": {"v2_new_field": "已填"},
            },
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["guidance_map"]["v2_new_field"], "已填")
        # 成功写返回的是本次版本（不冒充更晚 head）：记录最后一个 personal
        # revision 应为 4。
        with self.engine.connect() as conn:
            head_rev = conn.execute(
                text(
                    "SELECT current_personal_revision FROM "
                    "personal_prompt_heads WHERE account_id = :a "
                    "AND task_type = :t"
                ),
                {"a": ai1a.TEACHER_A["id"], "t": TASK},
            ).scalar()
        self.assertEqual(head_rev, 4)

    # -- B6: config secret lifecycle / degraded key material ----------------

    def test_config_ciphertext_reconnect_reconciles_versions(self):
        """R2：配置保留／轮换／清除后重连检查实际版本及密文认证结果；
        合成明文只断言、不打印。"""
        plaintext_first = SECRET_MARKER
        plaintext_rotated = SECRET_ROTATE_MARKER
        status, _, body = _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {"expected_version": 0, **CONFIG_META,
             "secret": plaintext_first},
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["secret_mask"], "********")
        self.assertFalse(plaintext_first in json.dumps(body))
        self.assertFalse(SECRET_ROTATE_MARKER in json.dumps(body))
        # v1 重连核对：版本行密文可解出合成原文（仅断言）。
        session = ai1a._session_from_factory()
        try:
            pinned = ai_config_service.read_pinned_config(
                session, ai1a.TEACHER_A["id"], 1
            )
            self.assertEqual(pinned.reveal_secret(), plaintext_first)
        finally:
            session.close()
        # 轮换：v2。
        status, _, body = _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {"expected_version": 1, **CONFIG_META,
             "secret": plaintext_rotated},
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["version"], 2)
        session = ai1a._session_from_factory()
        try:
            self.assertEqual(
                ai_config_service.read_pinned_config(
                    session, ai1a.TEACHER_A["id"], 2
                ).reveal_secret(),
                plaintext_rotated,
            )
            # v1 旧行字节不动、仍可认证解密。
            self.assertEqual(
                ai_config_service.read_pinned_config(
                    session, ai1a.TEACHER_A["id"], 1
                ).reveal_secret(),
                plaintext_first,
            )
        finally:
            session.close()
        # 保留（省略 secret）：v3 仍是原明文（新 nonce/AAD 重加密）。
        status, _, body = _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {"expected_version": 2, **CONFIG_META},
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["version"], 3)
        self.assertTrue(body["has_secret"])
        session = ai1a._session_from_factory()
        try:
            self.assertEqual(
                ai_config_service.read_pinned_config(
                    session, ai1a.TEACHER_A["id"], 3
                ).reveal_secret(),
                plaintext_rotated,
            )
        finally:
            session.close()
        # 清除：v4 无密文。
        status, _, body = _raw(
            self.teacher_a, "DELETE", "/api/settings/ai-config",
            {"expected_version": 3},
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["version"], 4)
        self.assertFalse(body["has_secret"])
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT secret_ciphertext, key_id FROM ai_config_versions "
                    "WHERE account_id = :id AND version = 4"
                ),
                {"id": ai1a.TEACHER_A["id"]},
            ).fetchone()
        self.assertIsNone(row[0])
        self.assertIsNone(row[1])
        # 每次 commit 各自一条审计与事件/操作记录递增核对：
        self.assertEqual(
            _versions(
                self.engine, "ai_config_versions",
                ai1a.TEACHER_A["id"], "version",
            ),
            [1, 2, 3, 4],
        )
        config_ops = None
        with self.engine.connect() as conn:
            config_ops = int(conn.execute(
                text(
                    "SELECT COUNT(*) FROM operation_records "
                    "WHERE action LIKE 'ai_config_%'"
                )
            ).scalar())
        self.assertEqual(config_ops, 4)

    def test_missing_master_key_full_write_set_blocked(self):
        """R2：含密文配置 + 移除主密钥 → GET 200 DECRYPT_UNAVAILABLE、
        DELETE 成功、需加密/保留密文 PATCH 503 且全部写集合无增量。"""
        status, _, body = _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {"expected_version": 0, **CONFIG_META, "secret": "KEEP-ME"},
        )
        self.assertEqual(status, 200, body)
        ai1a._clear_material()  # 移除主密钥
        baseline = {
            "ops": _ops_count(self.engine),
            "cfgv": _count(self.engine, "ai_config_versions"),
            "cfgheads": _count(self.engine, "ai_config_heads"),
        }
        status, _, body = _raw(
            self.teacher_a, "GET", "/api/settings/ai-config"
        )
        self.assertEqual(status, 200)
        self.assertFalse(body["ready"])
        self.assertEqual(body["ready_reason"], "DECRYPT_UNAVAILABLE")
        self.assertTrue(body["has_secret"])
        # 需保留密文的 PATCH（省略 secret）503，写集合无增量。
        status, _, body = _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {"expected_version": 1, **CONFIG_META, "model": "m2"},
        )
        self.assertEqual(status, 503, body)
        self.assertEqual(
            body["error"]["code"], "AI_CONFIG_UNAVAILABLE"
        )
        # 需加密新 secret 的 PATCH 503，写集合无增量。
        status, _, body = _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {"expected_version": 1, **CONFIG_META, "secret": "NEW-KEY"},
        )
        self.assertEqual(status, 503, body)
        self.assertEqual(
            body["error"]["code"], "AI_CONFIG_UNAVAILABLE"
        )
        self.assertEqual(_ops_count(self.engine), baseline["ops"])
        self.assertEqual(
            _count(self.engine, "ai_config_versions"), baseline["cfgv"]
        )
        self.assertEqual(
            _count(self.engine, "ai_config_heads"), baseline["cfgheads"]
        )
        self.assertEqual(
            _head_version(self.engine, ai1a.TEACHER_A["id"]), 1
        )
        # DELETE 不依赖解密：成功，且清除了密文。
        status, _, body = _raw(
            self.teacher_a, "DELETE", "/api/settings/ai-config",
            {"expected_version": 1},
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["version"], 2)
        self.assertFalse(body["has_secret"])
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT secret_ciphertext FROM ai_config_versions "
                    "WHERE account_id = :id AND version = 2"
                ),
                {"id": ai1a.TEACHER_A["id"]},
            ).scalar()
        self.assertIsNone(row)

    def test_wrong_master_key_blocks_keep_and_rotate(self):
        """R2：错误主密钥（格式非法 material）→ GET 200 DECRYPT_UNAVAILABLE，
        保留/需加密 PATCH 503 无增量，DELETE 成功。"""
        status, _, body = _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {"expected_version": 0, **CONFIG_META, "secret": "KEEP-ME"},
        )
        self.assertEqual(status, 200, body)
        # 换错误主密钥（格式不合法的材料）。
        ai1a._set_material(b"not-a-valid-key", "wrong-key-id")
        baseline = {
            "ops": _ops_count(self.engine),
            "cfgv": _count(self.engine, "ai_config_versions"),
        }
        status, _, body = _raw(
            self.teacher_a, "GET", "/api/settings/ai-config"
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["ready_reason"], "DECRYPT_UNAVAILABLE")
        status, _, body = _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {"expected_version": 1, **CONFIG_META},
        )
        self.assertEqual(status, 503)
        self.assertEqual(
            body["error"]["code"], "AI_CONFIG_UNAVAILABLE"
        )
        status, _, body = _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {"expected_version": 1, **CONFIG_META, "secret": "NEW-KEY"},
        )
        self.assertEqual(status, 503)
        self.assertEqual(
            body["error"]["code"], "AI_CONFIG_UNAVAILABLE"
        )
        self.assertEqual(_ops_count(self.engine), baseline["ops"])
        self.assertEqual(
            _count(self.engine, "ai_config_versions"), baseline["cfgv"]
        )
        # DELETE 成功。
        status, _, body = _raw(
            self.teacher_a, "DELETE", "/api/settings/ai-config",
            {"expected_version": 1},
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["version"], 2)
        self.assertFalse(body["has_secret"])

    def test_different_key_id_degrades_get(self):
        """key_id 与配置不匹配（换库/换密钥流程）：GET 降级、保留 503、
        清除成功。"""
        status, _, body = _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {"expected_version": 0, **CONFIG_META, "secret": "KEEP-ME"},
        )
        self.assertEqual(status, 200, body)
        ai1a._set_material(os.urandom(32), "another-key-id-2")
        status, _, body = _raw(
            self.teacher_a, "GET", "/api/settings/ai-config"
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["ready_reason"], "DECRYPT_UNAVAILABLE")
        status, _, body = _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {"expected_version": 1, **CONFIG_META},
        )
        self.assertEqual(status, 503)
        self.assertEqual(
            body["error"]["code"], "AI_CONFIG_UNAVAILABLE"
        )
        status, _, body = _raw(
            self.teacher_a, "DELETE", "/api/settings/ai-config",
            {"expected_version": 1},
        )
        self.assertEqual(status, 200, body)

    def test_cleared_config_metadata_save_without_key_independent(self):
        """R2：清除后的无密文元信息保存，在无主密钥时仍成功（独立测试）。"""
        status, _, body = _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {"expected_version": 0, **CONFIG_META, "secret": "TEMP"},
        )
        self.assertEqual(status, 200, body)
        status, _, body = _raw(
            self.teacher_a, "DELETE", "/api/settings/ai-config",
            {"expected_version": 1},
        )
        self.assertEqual(status, 200, body)
        self.assertFalse(body["has_secret"])
        ai1a._clear_material()
        status, _, body = _raw(
            self.teacher_a, "PATCH", "/api/settings/ai-config",
            {"expected_version": 2, "protocol_id": "chat_completions_v1",
             "base_url": "https://api.example.com/v2", "model": "m2"},
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["version"], 3)
        self.assertFalse(body["has_secret"])
        self.assertEqual(body["ready_reason"], "MISSING_SECRET")
        # 重连持久核对（无主密钥不影响 cookie 身份）。
        status, _, body = _raw(
            self.teacher_a, "GET", "/api/settings/ai-config"
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["version"], 3)
        self.assertEqual(body["model"], "m2")
        self.assertEqual(body["base_url"], "https://api.example.com/v2")


if __name__ == "__main__":
    unittest.main()
