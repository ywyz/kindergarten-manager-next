"""D0-3/D0-4: session + Host/Origin guard tests for the isolated server.

Uses FastAPI's TestClient (no window). The guard under test is exactly the
one the real WebView2 window talks to in the D0 run.
"""

import secrets

import pytest
from fastapi.testclient import TestClient

import d0_paths
from d0_db import SQLiteProbe
from d0_server import LaunchContext, create_app

SESSION_HEADER = "X-App-Session"
_PORT = 49_001  # TestClient mocks transport; only the value matters


@pytest.fixture()
def guard_env(tmp_path, monkeypatch):
    fake_dist = tmp_path / "frontend-dist"
    fake_dist.mkdir()
    (fake_dist / "d0.html").write_text(
        "<html><body>D0 验证 shell</body></html>", encoding="utf-8"
    )
    monkeypatch.setenv("KGM_D0_FRONTEND_DIR", str(fake_dist))
    probe = SQLiteProbe(tmp_path / "data")
    context = LaunchContext(port=_PORT, launch_token=secrets.token_urlsafe(32))
    environment = {"python_version": "test", "frozen": False}
    app = create_app(context, probe, environment)
    client = TestClient(app, base_url=context.expected_origin)
    yield client, context, probe
    probe.close()


def _headers(token=None, *, extra=None):
    headers = {}
    if token is not None:
        headers[SESSION_HEADER] = token
    if extra:
        headers.update(extra)
    return headers


class TestSessionGuard:
    def test_health_needs_no_session_and_exposes_no_data(self, guard_env):
        client, _context, _probe = guard_env
        response = client.get("/api/probe/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "probe": "d0"}
        assert "data_dir" not in response.text and "db_path" not in response.text

    @pytest.mark.parametrize("token", [None, "", "wrong", "wrong-again"])
    def test_state_rejected_without_valid_session(self, guard_env, token):
        client, _context, _probe = guard_env
        response = client.get("/api/probe/state", headers=_headers(token))
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_REQUIRED"
        assert response.headers["cache-control"] == "no-store"

    def test_state_allowed_with_launch_session(self, guard_env):
        client, context, probe = guard_env
        probe.save("初始内容")
        response = client.get("/api/probe/state", headers=_headers(context.launch_token))
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["content"] == "初始内容"
        assert body["version"] == 1

    def test_environment_requires_session(self, guard_env):
        client, context, _probe = guard_env
        anonymous = client.get("/api/probe/environment")
        assert anonymous.status_code == 401
        allowed = client.get(
            "/api/probe/environment", headers=_headers(context.launch_token)
        )
        assert allowed.status_code == 200
        assert allowed.json()["python_version"] == "test"


class TestOriginAndHostGuard:
    def test_post_without_origin_rejected(self, guard_env):
        client, context, _probe = guard_env
        response = client.post(
            "/api/probe/state",
            json={"content": "x"},
            headers=_headers(context.launch_token),
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"

    def test_post_with_wrong_origin_rejected(self, guard_env):
        client, context, _probe = guard_env
        response = client.post(
            "/api/probe/state",
            json={"content": "x"},
            headers=_headers(
                context.launch_token,
                extra={"Origin": "http://127.0.0.1:9999"},
            ),
        )
        assert response.status_code == 403

    def test_post_with_precise_origin_allowed(self, guard_env):
        client, context, probe = guard_env
        response = client.post(
            "/api/probe/state",
            json={"content": "来源正确的写入"},
            headers=_headers(
                context.launch_token,
                extra={"Origin": context.expected_origin},
            ),
        )
        assert response.status_code == 200
        assert response.json()["status"] == "saved"
        assert response.json()["version"] == 1

    def test_non_allowed_host_rejected(self, guard_env):
        client, context, _probe = guard_env
        headers = _headers(
            context.launch_token, extra={"Host": "localhost:8000"}
        )
        response = client.get("/api/probe/state", headers=headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN_HOST"

    def test_wrong_host_on_post_rejected_even_with_session_and_origin(self, guard_env):
        client, context, probe = guard_env
        probe.save("旧内容")
        response = client.post(
            "/api/probe/state",
            json={"content": "x"},
            headers=_headers(
                context.launch_token,
                extra={"Origin": context.expected_origin, "Host": "127.0.0.1:12345"},
            ),
        )
        assert response.status_code == 403
        body = probe.read()
        assert body["content"] == "旧内容" and body["version"] == 1


class TestStaticShell:
    def test_frontend_shell_served_without_session(self, guard_env):
        client, _context, _probe = guard_env
        response = client.get("/")
        # The shell is static, fingerprinted frontend assets; no data.
        assert response.status_code == 200
        assert "D0" in response.text


class TestExportEndpoint:
    def test_export_requires_valid_origin_and_session(self, guard_env):
        client, context, _probe = guard_env
        # No Origin (anonymous): rejected before the session check.
        anonymous = client.post("/api/probe/export", json={})
        assert anonymous.status_code == 403
        wrong_origin = client.post(
            "/api/probe/export",
            json={},
            headers=_headers(
                context.launch_token, extra={"Origin": "http://127.0.0.1:9999"}
            ),
        )
        assert wrong_origin.status_code == 403

    def test_export_returns_valid_docx_payload(self, guard_env):
        import base64
        import io
        import zipfile

        client, context, _probe = guard_env
        response = client.post(
            "/api/probe/export",
            json={},
            headers=_headers(
                context.launch_token, extra={"Origin": context.expected_origin}
            ),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["filename"].endswith(".docx")
        data = base64.b64decode(body["payload_base64"])
        assert len(data) == body["bytes"] > 0
        assert zipfile.is_zipfile(io.BytesIO(data))

    def test_export_response_never_contains_raw_token(self, guard_env):
        client, context, _probe = guard_env
        response = client.post(
            "/api/probe/export",
            json={},
            headers=_headers(
                context.launch_token, extra={"Origin": context.expected_origin}
            ),
        )
        assert response.status_code == 200
        assert context.launch_token not in response.text
