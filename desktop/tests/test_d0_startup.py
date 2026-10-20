"""D0-3-adjacent: startup failure behaviour without opening a window."""

import socket

import pytest

from d0_server import LaunchContext, create_app
from d0_db import SQLiteProbe
from d0_main import ServiceRun, free_loopback_port


class TestStartupFailure:
    def test_occupied_port_reports_failure(self, tmp_path, monkeypatch):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
            blocker.bind(("127.0.0.1", 0))
            occupied_port = blocker.getsockname()[1]
            blocker.listen(1)

            probe = SQLiteProbe(tmp_path / "data")
            import secrets

            context = LaunchContext(
                port=occupied_port, launch_token=secrets.token_urlsafe(32)
            )
            monkeypatch.setenv(
                "KGM_D0_FRONTEND_DIR", str(_fake_frontend(tmp_path))
            )
            app = create_app(context, probe, {"frozen": False})
            service = ServiceRun(app, occupied_port, timeout=3.0)
            try:
                assert service.start_and_wait() is False
                assert service.error is not None
                assert "退出" in service.error or "未就绪" in service.error
                # The uvicorn startup SystemExit is contained in the daemon
                # thread (no unhandled thread exception) and the thread is gone.
                assert service.alive() is False
            finally:
                service.stop()
                probe.close()

    def test_free_loopback_port_picks_different_values(self):
        first = free_loopback_port()
        second = free_loopback_port()
        assert first != second or first > 0


def _fake_frontend(tmp_path):
    dist = tmp_path / "frontend-dist"
    dist.mkdir(exist_ok=True)
    (dist / "d0.html").write_text("<html>D0</html>", encoding="utf-8")
    return dist
