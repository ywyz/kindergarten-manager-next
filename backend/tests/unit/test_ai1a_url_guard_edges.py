"""AI 1A 第二轮补修：URL 离线边界（S1）＋guard 异常文本合成边界（S2）。

本文件不连接数据库；密钥／凭证只用合成标记串且永不打印。
"""

from __future__ import annotations

import os
import traceback
import unittest
from unittest import mock

os.environ["APP_DISABLE_DOTENV"] = "1"

from app.services.ai_config_url import (  # noqa: E402
    BaseUrlInvalid,
    AiInputInvalid,
    normalize_https_base_url,
)

_MARKERS = ("SCHEMA-TAG-PASSWORD", "SECRET-TAG-KEY-1")


class S1UrlBoundaryTest(unittest.TestCase):
    """S1: ? / # 分隔符一律拒绝；解析异常转固定消息 BaseUrlInvalid。"""

    def _reject(self, raw: str) -> None:
        with self.assertRaises(BaseUrlInvalid) as ctx:
            normalize_https_base_url(raw)
        # 固定错误消息，不回显原始地址。
        self.assertNotIn(raw, str(ctx.exception))
        self.assertNotIn(raw.split("//", 1)[-1], str(ctx.exception))

    def test_raw_separators_rejected(self):
        # 原始输入带 ? 或 # 分隔符即拒绝（含空 query／空 fragment）。
        for raw in (
            "https://api.vendor.com/v1?",
            "https://api.vendor.com/v1#",
            "https://api.vendor.com/v1?#",
            "https://api.vendor.com/v1?a=1",
            "https://api.vendor.com/v1#top",
            "https://api.vendor.com/v1?a=1#top",
            "https://api.vendor.com/#",
            "https://api.vendor.com?#",
        ):
            self._reject(raw)

    def test_malformed_parse_raises_typed_fixed_message(self):
        # 畸形解析（括号／端口）统一 BaseUrlInvalid，固定消息。
        for raw in (
            "https://[broken/v1",
            "https://api.vendor.com:port/v1",
            "https://api.vendor.com:0x1f/v1",
            "https://api.vendor.com:9999999999/v1",
            "https://[::1/v1",
        ):
            self._reject(raw)

    def test_percent_encoded_path_kept_literal(self):
        # 百分号编码路径保持原样（不解码／不改写）。
        self.assertEqual(
            normalize_https_base_url("https://api.vendor.com/v1%2Fx?%20y".replace("?%20y", "")),
            "https://api.vendor.com/v1%2Fx",
        )
        self.assertEqual(
            normalize_https_base_url("https://api.vendor.com/v1/openai"),
            "https://api.vendor.com/v1/openai",
        )
        with self.assertRaises(BaseUrlInvalid):
            normalize_https_base_url("https://api.vendor.com/v1?x=1")

    def test_reasonable_prefixes_still_pass(self):
        self.assertEqual(
            normalize_https_base_url("https://api.vendor.com:8443/v1/custom-prefix/"),
            "https://api.vendor.com:8443/v1/custom-prefix",
        )
        self.assertEqual(
            normalize_https_base_url("https://93.184.216.34/v1"),
            "https://93.184.216.34/v1",
        )

    def test_error_type_family(self):
        # BaseUrlInvalid 属于 AiInputInvalid 家族（422 类映射入口稳定）。
        self.assertTrue(issubclass(BaseUrlInvalid, AiInputInvalid))


class S2GuardExceptionTest(unittest.TestCase):
    """S2: Alembic 失败异常文本不可能带出原始 stdout／stderr（mock 边界）。"""

    _VALID_SYNTHETIC_URL = (
        "mysql+pymysql://synthetic-user:synthetic-pass"
        "@127.0.0.1:13387/kindergarten_test_ai1a"
    )

    def _run(self, stdout: str, stderr: str):
        from tests.integration import ai1a_guard as guard

        completed = mock.Mock()
        completed.returncode = 3
        completed.stdout = stdout
        completed.stderr = stderr
        with mock.patch.object(guard, "_database_url", self._VALID_SYNTHETIC_URL), \
                mock.patch.object(guard, "INTEGRATION_ENABLED", True), \
                mock.patch.object(guard.subprocess, "run", return_value=completed):
            try:
                guard.run_alembic(["upgrade", "head"])
            except RuntimeError as exc:
                return exc
            raise AssertionError("失败退出必须抛 RuntimeError")

    def test_failure_text_carries_no_markers(self):
        synth_stdout = (
            "Running upgrade ...\nDSN= mysql+pymysql://fanout:" + _MARKERS[0]
            + "@127.0.0.1:3306/k=...\n"
        )
        synth_stderr = (
            "Traceback (most recent call last):\n"
            "sqlalchemy.exc.OperationalError: " + _MARKERS[0] + " "
            "key=" + _MARKERS[1] + "\n"
        )
        exc = self._run(synth_stdout, synth_stderr)
        self.assertNotIn(_MARKERS[0], str(exc))
        self.assertNotIn(_MARKERS[1], str(exc))
        self.assertNotIn(_MARKERS[0], repr(exc))
        self.assertNotIn(_MARKERS[1], repr(exc))
        formatted = "".join(traceback.format_exception(exc))
        self.assertNotIn(_MARKERS[0], formatted)
        self.assertNotIn(_MARKERS[1], formatted)
        # 固定类别仍存在：退出码与已校验目标信息可见。
        self.assertIn("exit=", str(exc))
        self.assertIn("category=alembic_child_process_nonzero_exit", str(exc))

    def test_no_cause_chain_carries_credentials(self):
        synth_stderr = "psycopg raw: PASSWORD=" + _MARKERS[0] + "\n"
        exc = self._run("", synth_stderr)
        self.assertIsNone(exc.__cause__)
        self.assertIsNone(exc.__context__)
        formatted = "".join(traceback.format_exception(exc))
        self.assertNotIn(_MARKERS[0], formatted)

    def test_guard_refusals_are_fixed_messages(self):
        from tests.integration import ai1a_guard as guard

        for raw, db in (
            ("mysql+pymysql://u:" + _MARKERS[0]
             + "@127.0.0.1:13387/kindergarten_test_i5", "kindergarten_test_i5"),
            ("mysql+pymysql://u:" + _MARKERS[0]
             + "@10.0.0.5:13387/kindergarten_test_ai1a", "kindergarten_test_ai1a"),
        ):
            with self.subTest(url="redacted"):
                with self.assertRaises(RuntimeError):
                    guard.require_authorized_url(raw)
        # 异常文本不含合成标记／具体 URL。
        try:
            guard.require_authorized_url(
                "mysql+pymysql://u:" + _MARKERS[0]
                + "@127.0.0.1:13387/kindergarten_test_i5"
            )
        except RuntimeError as exc:
            self.assertNotIn(_MARKERS[0], str(exc))
            self.assertNotIn("pymysql", str(exc))
        else:
            self.fail(" Hawaiexpected db must be refused")

    def test_disabled_guard_never_connects(self):
        import subprocess

        code = subprocess.run(
            [
                os.path.join(os.path.dirname(__file__), "..", "..", ".venv", "bin", "python"),
                "-c",
                "import tests.integration.ai1a_guard as g;"
                " assert not g.INTEGRATION_ENABLED;"
                " assert 'AI_MASTER_KEY' not in __import__('os').environ;",
            ],
            capture_output=True,
            text=True,
            cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
        )
        self.assertEqual(code.returncode, 0, code.stderr)


if __name__ == "__main__":
    unittest.main()
