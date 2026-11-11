"""GitHub Release discovery, binding, redirect and GitHub-mode manager tests."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
import uuid
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tests.local import w3_tls

import update_github
import update_helper
import update_install
import update_manifest
import update_service
from update_identity import AppIdentity, is_preview_version
from update_manifest import ManifestError, canonical_json
from update_trust import ReleaseConfigError, ReleaseSource, load_release_source

CURRENT = AppIdentity(
    app_id="kindergarten-manager-next",
    app_name="KindergartenManager",
    channel="stable",
    version="0.1.0",
    build_id=str(uuid.uuid4()),
    package_format="pyinstaller-onedir-zip-v1",
    platform="windows",
    arch="x64",
    python="3.14.7",
    database_revision="20261025_0006_local_game_observations",
)
KEY = Ed25519PrivateKey.generate()
PUBLIC = KEY.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw
)


def _release(
    tag: str = "v0.2.0",
    *,
    draft: bool = False,
    prerelease: bool = False,
    assets: bool = True,
) -> dict:
    names = (
        [update_github.MANIFEST_ASSET, update_github.PACKAGE_ASSET]
        if assets
        else [update_github.PACKAGE_ASSET]
    )
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "published_at": "2026-10-30T00:00:00Z",
        "body": "合成更新说明",
        "assets": [
            {
                "name": name,
                "browser_download_url": (
                    f"https://github.com/{update_github.GITHUB_REPO}/releases/"
                    f"download/{tag}/{name}"
                ),
            }
            for name in names
        ],
    }


def _manifest_bytes(
    tag: str = "v0.2.0",
    *,
    version: str = "0.2.0",
    channel: str | None = None,
    package_size: int = 1234,
    package_sha256: str = "a" * 64,
    package_url: str | None = None,
    build_id: str | None = None,
) -> bytes:
    payload = {
        "app_id": CURRENT.app_id,
        "channel": channel or CURRENT.channel,
        "version": version,
        "build_id": build_id or str(uuid.uuid4()),
        "platform": "windows",
        "arch": "x64",
        "package_format": CURRENT.package_format,
        "package_root": "KindergartenManager",
        "executable": "KindergartenManager.exe",
        "package_url": package_url
        or (
            f"/{update_github.GITHUB_REPO}/releases/download/{tag}/"
            f"{update_github.PACKAGE_ASSET}"
        ),
        "package_size": package_size,
        "package_sha256": package_sha256,
        "database_revision": "20261025_0006_local_game_observations",
        "supported_source_revisions": [CURRENT.database_revision],
        "release_notes": "合成更新说明",
        "published_at": "2026-10-30T00:00:00Z",
    }
    envelope = {
        "schema_version": 1,
        "key_id": "test-key",
        "payload": payload,
        "signature": base64.b64encode(KEY.sign(canonical_json(payload))).decode("ascii"),
    }
    return json.dumps(envelope, ensure_ascii=False).encode("utf-8")


def _source(keys=None) -> ReleaseSource:
    return update_github.api_source(keys if keys is not None else {"test-key": PUBLIC})


class _Response:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self.body = body
        self.headers = {"Content-Length": str(len(body))}

    def getheader(self, name):
        return self.headers.get(name)

    def read1(self, size: int) -> bytes:
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk

    def close(self):
        pass


class _Sock:
    def fileno(self):
        return -1

    def settimeout(self, value):
        pass

    def shutdown(self, how):
        pass


def test_latest_release_parses_only_newer_formal_release():
    release = update_github.parse_latest_release(
        json.dumps(_release()).encode(), CURRENT.version
    )
    assert release.tag == "v0.2.0"
    assert release.version == "0.2.0"
    assert release.assets_complete is True
    with pytest.raises(ManifestError) as same:
        update_github.parse_latest_release(
            json.dumps(_release("v0.1.0")).encode(), CURRENT.version
        )
    assert same.value.code == "UPDATE_NO_NEW_VERSION"
    with pytest.raises(ManifestError) as draft:
        update_github.parse_latest_release(
            json.dumps(_release(draft=True)).encode(), CURRENT.version
        )
    assert draft.value.code == "UPDATE_NO_RELEASE"
    with pytest.raises(ManifestError) as pre:
        update_github.parse_latest_release(
            json.dumps(_release(prerelease=True)).encode(), CURRENT.version
        )
    assert pre.value.code == "UPDATE_NO_RELEASE"
    for field, value in (("draft", "true"), ("prerelease", 1), ("draft", None)):
        raw = _release()
        raw[field] = value
        with pytest.raises(ManifestError) as not_bool:
            update_github.parse_latest_release(
                json.dumps(raw).encode(), CURRENT.version
            )
        assert not_bool.value.code == "UPDATE_METADATA_INVALID"


def test_latest_release_missing_and_duplicate_assets():
    missing = update_github.parse_latest_release(
        json.dumps(_release(assets=False)).encode(), CURRENT.version
    )
    assert missing.assets_complete is False
    assert missing.missing_assets == (update_github.MANIFEST_ASSET,)
    raw = _release()
    raw["assets"].append(dict(raw["assets"][0]))
    with pytest.raises(ManifestError) as duplicate:
        update_github.parse_latest_release(
            json.dumps(raw).encode(), CURRENT.version
        )
    assert duplicate.value.code == "UPDATE_ASSETS_DUPLICATE"


def test_latest_release_rejects_bad_tag_and_json():
    raw = _release()
    raw["tag_name"] = "0.2"
    with pytest.raises(ManifestError) as bad_tag:
        update_github.parse_latest_release(json.dumps(raw).encode(), CURRENT.version)
    assert bad_tag.value.code == "UPDATE_METADATA_INVALID"
    with pytest.raises(ManifestError):
        update_github.parse_latest_release(b"{", CURRENT.version)


def test_github_url_allowlist_and_repo_tag_binding():
    source = _source()
    assert (
        update_github.validate_github_url(
            source, "https://api.github.com" + update_github.GITHUB_API_PATH
        )
        == "https://api.github.com" + update_github.GITHUB_API_PATH
    )
    manifest = update_github.manifest_source(
        update_github.parse_latest_release(
            json.dumps(_release()).encode(), CURRENT.version
        ),
        {"test-key": PUBLIC},
    )
    asset = (
        f"https://github.com/{update_github.GITHUB_REPO}/releases/download/"
        f"v0.2.0/{update_github.PACKAGE_ASSET}"
    )
    assert update_github.validate_github_url(manifest, asset) == asset
    cdn = (
        "https://release-assets.githubusercontent.com/"
        "github-production-release-asset/93446099/"
        "d39d1596-8cd3-40db-9201-ef23820cb68f?sp=r&sig=x"
    )
    assert update_github.validate_github_url(manifest, cdn) == cdn
    with pytest.raises(Exception):
        # An API-only source never accepts a CDN asset URL.
        update_github.validate_github_url(source, cdn)
    for bad in (
        "http://github.com/" + update_github.GITHUB_REPO,
        "https://example.com/file.zip",
        "https://user:pass@github.com/" + update_github.GITHUB_REPO,
        f"https://github.com/other/repo/releases/download/v0.2.0/{update_github.PACKAGE_ASSET}",
        f"https://github.com/{update_github.GITHUB_REPO}/releases/download/v0.3.0/{update_github.PACKAGE_ASSET}",
        f"https://github.com/{update_github.GITHUB_REPO}/releases/download/v0.2.0/other.zip",
        "https://release-assets.githubusercontent.com/other/path",
    ):
        with pytest.raises(Exception):
            update_github.validate_github_url(manifest, bad)


def test_manifest_binding_and_config_roundtrip(tmp_path: Path):
    release = update_github.parse_latest_release(
        json.dumps(_release()).encode(), CURRENT.version
    )
    source = update_github.manifest_source(release, {"test-key": PUBLIC})
    manifest = SimpleNamespace(
        channel=release.channel,
        version="0.2.0",
        package_url=update_github.expected_package_url(release),
    )
    update_github.validate_manifest_binding(manifest, release)
    bad = SimpleNamespace(
        channel=release.channel,
        version="0.2.1",
        package_url=manifest.package_url,
    )
    with pytest.raises(ManifestError):
        update_github.validate_manifest_binding(bad, release)
    path = tmp_path / "update_release.json"
    path.write_text(json.dumps(source.as_config()), encoding="utf-8")
    loaded = load_release_source(path)
    assert loaded is not None
    assert loaded.provider == "github"
    assert loaded.github_tag == "v0.2.0"
    assert loaded.public_keys == {"test-key": PUBLIC}
    assert loaded.allowed_redirect_hosts == (update_github.GITHUB_ASSET_HOST,)


def _wait_state(manager, expected: str, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = manager.state()
        if state["state"] not in ("checking", "downloading", "verifying"):
            assert state["state"] == expected, state
            return state
        time.sleep(0.01)
    raise AssertionError(f"manager did not reach {expected}: {manager.state()}")


def test_github_manager_discovers_and_binds_signed_manifest(monkeypatch, tmp_path):
    manager = update_service.UpdateManager(
        CURRENT,
        source=_source(),
        enabled=True,
        staging_root=tmp_path / "staging",
        allow_install=False,
    )

    def fake_open(source, url, read_timeout=update_service.READ_TIMEOUT, *, deadline=None):
        if url == update_github.GITHUB_API_ORIGIN + update_github.GITHUB_API_PATH:
            return None, _Response(200, json.dumps(_release()).encode()), _Sock()
        return None, _Response(200, _manifest_bytes()), _Sock()

    monkeypatch.setattr(update_service, "_open_url", fake_open)
    manager.check()
    state = _wait_state(manager, "available")
    assert state["target"]["version"] == "0.2.0"
    assert state["download_available"] is False
    assert state["allow_install"] is False


def test_github_manager_no_release_and_rate_limit(monkeypatch, tmp_path):
    manager = update_service.UpdateManager(
        CURRENT,
        source=_source(),
        enabled=True,
        staging_root=tmp_path / "staging",
        allow_install=False,
    )
    monkeypatch.setattr(
        update_service,
        "_open_url",
        lambda *args, **kwargs: (None, _Response(404, b"{}"), _Sock()),
    )
    manager.check()
    assert _wait_state(manager, "no_release")["reason"] == "UPDATE_NO_RELEASE"

    manager2 = update_service.UpdateManager(
        CURRENT,
        source=_source(),
        enabled=True,
        staging_root=tmp_path / "staging2",
        allow_install=False,
    )
    monkeypatch.setattr(
        update_service,
        "_open_url",
        lambda *args, **kwargs: (None, _Response(429, b"{}"), _Sock()),
    )
    manager2.check()
    assert _wait_state(manager2, "failed")["error_code"] == "UPDATE_RATE_LIMITED"


def test_github_manager_missing_assets_or_trust(monkeypatch, tmp_path):
    manager = update_service.UpdateManager(
        CURRENT,
        source=_source(),
        enabled=True,
        staging_root=tmp_path / "staging",
        allow_install=False,
    )
    monkeypatch.setattr(
        update_service,
        "_open_url",
        lambda *args, **kwargs: (
            None,
            _Response(200, json.dumps(_release(assets=False)).encode()),
            _Sock(),
        ),
    )
    manager.check()
    state = _wait_state(manager, "available")
    assert state["reason"] == "UPDATE_ASSETS_MISSING"
    assert state["download_available"] is False

    manager2 = update_service.UpdateManager(
        CURRENT,
        source=_source({}),
        enabled=True,
        staging_root=tmp_path / "staging2",
        allow_install=False,
    )
    monkeypatch.setattr(
        update_service,
        "_open_url",
        lambda *args, **kwargs: (
            None,
            _Response(200, json.dumps(_release()).encode()),
            _Sock(),
        ),
    )
    manager2.check()
    state2 = _wait_state(manager2, "available")
    assert state2["reason"] == "UPDATE_TRUST_UNCONFIGURED"
    assert state2["download_available"] is False


def test_load_github_source_reads_embedded_keys(tmp_path: Path):
    path = tmp_path / "update_release.json"
    path.write_text(
        json.dumps(
            {
                "public_keys": {
                    "test-key": base64.b64encode(PUBLIC).decode("ascii")
                }
            }
        ),
        encoding="utf-8",
    )
    source = update_github.load_github_source(path)
    assert source.provider == "github"
    assert source.public_keys == {"test-key": PUBLIC}
    assert source.origin == update_github.GITHUB_API_ORIGIN


class _RedirectResponse(_Response):
    def __init__(self, status: int, location: str | None = None):
        super().__init__(status, b"")
        if location is not None:
            self.headers["Location"] = location


class _Conn:
    def __init__(self, response):
        self.response = response
        self.sock = _Sock()

    def putrequest(self, *args, **kwargs):
        pass

    def putheader(self, *args, **kwargs):
        pass

    def endheaders(self):
        pass

    def getresponse(self):
        return self.response

    def close(self):
        pass


def test_open_url_follows_allowed_redirect_and_rejects_forbidden(monkeypatch):
    release = update_github.parse_latest_release(
        json.dumps(_release()).encode(), CURRENT.version
    )
    source = update_github.manifest_source(release, {"test-key": PUBLIC})
    first = _RedirectResponse(
        302,
        "https://release-assets.githubusercontent.com/"
        "github-production-release-asset/93446099/"
        "d39d1596-8cd3-40db-9201-ef23820cb68f?sp=r",
    )
    second = _RedirectResponse(200)
    conns = iter([_Conn(first), _Conn(second)])
    monkeypatch.setattr(update_service, "_github_connection", lambda *a, **k: next(conns))
    conn, response, sock = update_service._open_url(
        source,
        "https://github.com/" + update_github.GITHUB_REPO + "/releases/download/v0.2.0/"
        + update_github.MANIFEST_ASSET,
    )
    assert response.status == 200
    assert conn is not None and sock is not None

    bad = _RedirectResponse(302, "https://evil.example/file")
    monkeypatch.setattr(update_service, "_github_connection", lambda *a, **k: _Conn(bad))
    with pytest.raises(update_service.UpdateError):
        update_service._open_url(
            source,
            "https://github.com/" + update_github.GITHUB_REPO + "/releases/download/v0.2.0/"
            + update_github.MANIFEST_ASSET,
        )

    loop = _RedirectResponse(
        302,
        "https://github.com/" + update_github.GITHUB_REPO + "/releases/download/v0.2.0/"
        + update_github.MANIFEST_ASSET,
    )
    monkeypatch.setattr(update_service, "_github_connection", lambda *a, **k: _Conn(loop))
    with pytest.raises(update_service.UpdateError):
        update_service._open_url(
            source,
            "https://github.com/" + update_github.GITHUB_REPO + "/releases/download/v0.2.0/"
            + update_github.MANIFEST_ASSET,
        )


class _NoLengthResponse:
    def __init__(self, body: bytes):
        self.body = body

    def getheader(self, name):
        return None

    def read1(self, size: int) -> bytes:
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk


def test_read_exact_accepts_bounded_chunked_response():
    assert update_service._read_exact(_NoLengthResponse(b"abc"), 10) == b"abc"
    with pytest.raises(update_service.UpdateError) as over:
        update_service._read_exact(_NoLengthResponse(b"abcdef"), 5)
    assert over.value.code == "UPDATE_DOWNLOAD_INVALID"


def test_github_download_uses_manifest_source_package_url(monkeypatch, tmp_path: Path):
    release = update_github.parse_latest_release(
        json.dumps(_release()).encode(), CURRENT.version
    )
    manifest_source = update_github.manifest_source(
        release, {"test-key": PUBLIC}
    )
    manifest = update_manifest.parse_signed_manifest(
        _manifest_bytes(),
        manifest_source,
        CURRENT.version,
        CURRENT.database_revision,
    )
    manager = update_service.UpdateManager(
        CURRENT,
        source=_source(),
        enabled=True,
        staging_root=tmp_path / "staging",
        allow_install=True,
    )
    manager._manifest_source = manifest_source
    with manager._lock:
        manager._generation = 1
    seen: dict[str, str] = {}

    def fake_open(source, url, read_timeout=update_service.READ_TIMEOUT, *, deadline=None):
        seen["url"] = url
        return None, _Response(404, b""), _Sock()

    monkeypatch.setattr(update_service, "_open_url", fake_open)
    staging = tmp_path / "staging" / "download"
    staging.mkdir(parents=True)
    manager._download_worker(1, manifest, staging)
    assert seen["url"] == (
        f"https://github.com/{update_github.GITHUB_REPO}/releases/download/"
        f"v0.2.0/{update_github.PACKAGE_ASSET}"
    )


def test_github_manager_manifest_404_is_discoverable_but_unavailable(monkeypatch, tmp_path):
    manager = update_service.UpdateManager(
        CURRENT,
        source=_source(),
        enabled=True,
        staging_root=tmp_path / "staging",
        allow_install=False,
    )

    def fake_open(source, url, read_timeout=update_service.READ_TIMEOUT, *, deadline=None):
        if url == update_github.GITHUB_API_ORIGIN + update_github.GITHUB_API_PATH:
            return None, _Response(200, json.dumps(_release()).encode()), _Sock()
        return None, _Response(404, b""), _Sock()

    monkeypatch.setattr(update_service, "_open_url", fake_open)
    manager.check()
    state = _wait_state(manager, "available")
    assert state["target"]["version"] == "0.2.0"
    assert state["reason"] == "UPDATE_ASSETS_MISSING"
    assert state["download_available"] is False


def test_github_manager_bad_signature_fails_closed(monkeypatch, tmp_path):
    envelope = json.loads(_manifest_bytes())
    signature = envelope["signature"]
    envelope["signature"] = ("A" if signature[0] != "A" else "B") + signature[1:]
    manager = update_service.UpdateManager(
        CURRENT,
        source=_source(),
        enabled=True,
        staging_root=tmp_path / "staging",
        allow_install=False,
    )

    def fake_open(source, url, read_timeout=update_service.READ_TIMEOUT, *, deadline=None):
        if url == update_github.GITHUB_API_ORIGIN + update_github.GITHUB_API_PATH:
            return None, _Response(200, json.dumps(_release()).encode()), _Sock()
        return None, _Response(200, json.dumps(envelope).encode()), _Sock()

    monkeypatch.setattr(update_service, "_open_url", fake_open)
    manager.check()
    state = _wait_state(manager, "failed")
    assert state["error_code"] == "UPDATE_METADATA_UNTRUSTED"
    assert state["download_available"] is False


def _make_package(
    tmp_path: Path,
    *,
    version: str = "0.2.0",
    channel: str | None = None,
) -> tuple[Path, str, str, int]:
    build_id = str(uuid.uuid4())
    root = "KindergartenManager"
    files: dict[str, bytes] = {
        "KindergartenManager.exe": b"MZ synthetic exe",
        "_internal/frontend/d1.html": b"<!doctype html><title>test</title>",
        "_internal/migrations_local/env.py": b"# synthetic migration\n",
        "_internal/app/assets/word_templates/daily_plan.docx": b"PK synthetic template",
    }
    identity = {
        "app_id": CURRENT.app_id,
        "app_name": CURRENT.app_name,
        "channel": channel or CURRENT.channel,
        "version": version,
        "build_id": build_id,
        "package_format": CURRENT.package_format,
        "platform": CURRENT.platform,
        "arch": CURRENT.arch,
        "python": CURRENT.python,
        "database_revision": CURRENT.database_revision,
    }
    files["_internal/build_identity.json"] = json.dumps(
        identity, ensure_ascii=False
    ).encode("utf-8")
    entries = [
        {"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in sorted(files.items())
    ]
    package_manifest = {
        "schema_version": 1,
        "app_id": CURRENT.app_id,
        "app_name": CURRENT.app_name,
        "channel": channel or CURRENT.channel,
        "version": version,
        "build_id": build_id,
        "package_format": CURRENT.package_format,
        "platform": CURRENT.platform,
        "arch": CURRENT.arch,
        "database_revision": CURRENT.database_revision,
        "files": entries,
    }
    files["_internal/package_manifest.json"] = json.dumps(
        package_manifest, ensure_ascii=False, indent=2
    ).encode("utf-8")
    package = tmp_path / "package.zip"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(f"{root}/{name}", data)
    raw = package.read_bytes()
    return package, build_id, hashlib.sha256(raw).hexdigest(), len(raw)


def test_github_check_stays_busy_until_manifest_verified(monkeypatch, tmp_path):
    calls: list[str] = []
    manifest_started = threading.Event()
    release_manifest = threading.Event()

    def fake_open(source, url, read_timeout=update_service.READ_TIMEOUT, *, deadline=None):
        calls.append(url)
        if url == update_github.GITHUB_API_ORIGIN + update_github.GITHUB_API_PATH:
            return None, _Response(200, json.dumps(_release()).encode()), _Sock()
        manifest_started.set()
        release_manifest.wait(5.0)
        return None, _Response(200, _manifest_bytes()), _Sock()

    monkeypatch.setattr(update_service, "_open_url", fake_open)
    manager = update_service.UpdateManager(
        CURRENT,
        source=_source(),
        enabled=True,
        staging_root=tmp_path / "staging",
        allow_install=False,
    )
    manager.check()
    assert manifest_started.wait(2.0)
    assert manager.state()["state"] == "checking"
    manager.check()
    api_calls = [url for url in calls if url.endswith(update_github.GITHUB_API_PATH)]
    assert len(api_calls) == 1, "a second check must not start another latest request"
    release_manifest.set()
    state = _wait_state(manager, "available")
    assert state["target"]["version"] == "0.2.0"


def test_preview_check_stays_checking_until_manifest_verified(
    monkeypatch, tmp_path
):
    manifest_started = threading.Event()
    release_manifest = threading.Event()

    def fake_open(source, url, read_timeout=update_service.READ_TIMEOUT, *, deadline=None):
        if "?per_page=" in url:
            return (
                None,
                _Response(
                    200,
                    _preview_list(["v0.2.0-listening-test.10"]),
                ),
                _Sock(),
            )
        manifest_started.set()
        release_manifest.wait(5.0)
        return (
            None,
            _Response(
                200,
                _manifest_bytes(
                    tag="v0.2.0-listening-test.10",
                    version="0.2.0-listening-test.10",
                    channel="preview",
                ),
            ),
            _Sock(),
        )

    monkeypatch.setattr(update_service, "_open_url", fake_open)
    manager = update_service.UpdateManager(
        PREVIEW_CURRENT,
        source=_source(),
        enabled=True,
        staging_root=tmp_path / "preview-blocking-staging",
        allow_install=False,
    )
    manager.check()
    assert manifest_started.wait(2.0)
    assert manager.state()["state"] == "checking"
    assert manager.state()["download_available"] is False
    release_manifest.set()
    state = _wait_state(manager, "available")
    assert state["target"]["version"] == "0.2.0-listening-test.10"
    assert state["download_available"] is False


def test_github_late_check_after_shutdown_does_not_publish(monkeypatch, tmp_path):
    manifest_started = threading.Event()
    release_manifest = threading.Event()

    def fake_open(source, url, read_timeout=update_service.READ_TIMEOUT, *, deadline=None):
        if url == update_github.GITHUB_API_ORIGIN + update_github.GITHUB_API_PATH:
            return None, _Response(200, json.dumps(_release()).encode()), _Sock()
        manifest_started.set()
        release_manifest.wait(5.0)
        return None, _Response(200, _manifest_bytes()), _Sock()

    monkeypatch.setattr(update_service, "_open_url", fake_open)
    manager = update_service.UpdateManager(
        CURRENT,
        source=_source(),
        enabled=True,
        staging_root=tmp_path / "staging",
        allow_install=False,
    )
    manager.check()
    assert manifest_started.wait(2.0)
    timer = threading.Timer(0.05, release_manifest.set)
    timer.daemon = True
    timer.start()
    manager.shutdown()
    assert manager.state()["state"] == "closed"
    assert manager.state()["target"] is None


def _helper_plan(
    tmp_path: Path,
    manifest: bytes,
    package: Path,
    *,
    current_version: str | None = None,
) -> SimpleNamespace:
    payload = json.loads(manifest)["payload"]
    metadata = tmp_path / "update_metadata.json"
    metadata.write_text(json.dumps({"raw": manifest.decode("utf-8")}), encoding="utf-8")
    target = {
        key: payload[key]
        for key in (
            "app_id",
            "channel",
            "version",
            "build_id",
            "platform",
            "arch",
            "package_format",
            "package_root",
            "executable",
            "package_size",
            "package_sha256",
            "database_revision",
        )
    }
    installed_version = current_version or CURRENT.version
    current_identity = CURRENT.as_dict()
    current_identity["version"] = installed_version
    current_identity["channel"] = (
        "preview" if is_preview_version(installed_version) else "stable"
    )
    install_root = tmp_path / "program"
    app = install_root / "KindergartenManager"
    (app / "_internal").mkdir(parents=True, exist_ok=True)
    (app / "_internal" / "build_identity.json").write_text(
        json.dumps(current_identity, ensure_ascii=False),
        encoding="utf-8",
    )
    return SimpleNamespace(
        release_config="",
        metadata_path=str(metadata),
        package_zip=str(package),
        state_dir=str(tmp_path / "state"),
        install_root=str(install_root),
        install_app_dir=str(app),
        current=current_identity,
        target=target,
    )


def _write_github_config(path: Path, public_key: bytes) -> None:
    path.write_text(
        json.dumps(
            {
                "origin": update_github.GITHUB_API_ORIGIN,
                "metadata_path": update_github.GITHUB_API_PATH,
                "channel": "stable",
                "public_keys": {
                    "test-key": base64.b64encode(public_key).decode("ascii")
                },
                "provider": "github",
                "github_repo": update_github.GITHUB_REPO,
                "github_tag": None,
                "allowed_redirect_hosts": [],
            }
        ),
        encoding="utf-8",
    )


def test_product_helper_verifies_github_manifest_and_full_zip(monkeypatch, tmp_path):
    package, build_id, sha, size = _make_package(tmp_path)
    manifest = _manifest_bytes(
        package_size=size, package_sha256=sha, build_id=build_id
    )
    plan = _helper_plan(tmp_path, manifest, package)
    config = tmp_path / "updater" / "update_release.json"
    config.parent.mkdir(parents=True)
    _write_github_config(config, PUBLIC)
    monkeypatch.setattr(update_helper, "_trusted_release_config_path", lambda: config)

    loaded = update_helper._load_manifest(plan, verification_context=False)
    assert loaded.package_sha256 == sha
    verified = update_helper._verify_saved_package(plan, loaded)
    assert (verified.root / "KindergartenManager.exe").is_file()


def test_product_helper_rejects_bad_key_signature_and_package_path(monkeypatch, tmp_path):
    package, build_id, sha, size = _make_package(tmp_path)
    manifest = _manifest_bytes(
        package_size=size, package_sha256=sha, build_id=build_id
    )
    plan = _helper_plan(tmp_path, manifest, package)
    config = tmp_path / "updater" / "update_release.json"
    config.parent.mkdir(parents=True)
    _write_github_config(config, PUBLIC)
    monkeypatch.setattr(update_helper, "_trusted_release_config_path", lambda: config)

    other_key = Ed25519PrivateKey.generate()
    other_public = other_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    _write_github_config(config, other_public)
    with pytest.raises(ManifestError) as bad_key:
        update_helper._load_manifest(plan, verification_context=False)
    assert bad_key.value.code == "UPDATE_METADATA_UNTRUSTED"

    _write_github_config(config, PUBLIC)
    envelope = json.loads(manifest)
    signature = envelope["signature"]
    envelope["signature"] = ("A" if signature[0] != "A" else "B") + signature[1:]
    bad_signature = json.dumps(envelope).encode("utf-8")
    plan.metadata_path = str(tmp_path / "bad-signature.json")
    Path(plan.metadata_path).write_text(
        json.dumps({"raw": bad_signature.decode("utf-8")}), encoding="utf-8"
    )
    with pytest.raises(ManifestError) as bad_sig:
        update_helper._load_manifest(plan, verification_context=False)
    assert bad_sig.value.code == "UPDATE_METADATA_UNTRUSTED"

    bad_path = _manifest_bytes(
        package_size=size,
        package_sha256=sha,
        build_id=build_id,
        package_url=(
            f"/{update_github.GITHUB_REPO}/releases/download/v0.3.0/"
            f"{update_github.PACKAGE_ASSET}"
        ),
    )
    plan.metadata_path = str(tmp_path / "bad-path.json")
    Path(plan.metadata_path).write_text(
        json.dumps({"raw": bad_path.decode("utf-8")}), encoding="utf-8"
    )
    with pytest.raises(ManifestError) as bad_binding:
        update_helper._load_manifest(plan, verification_context=False)
    assert bad_binding.value.code == "UPDATE_METADATA_INVALID"


def test_product_helper_rejects_package_hash_mismatch(monkeypatch, tmp_path):
    package, build_id, sha, size = _make_package(tmp_path)
    manifest = _manifest_bytes(
        package_size=size, package_sha256="b" * 64, build_id=build_id
    )
    plan = _helper_plan(tmp_path, manifest, package)
    config = tmp_path / "updater" / "update_release.json"
    config.parent.mkdir(parents=True)
    _write_github_config(config, PUBLIC)
    monkeypatch.setattr(update_helper, "_trusted_release_config_path", lambda: config)
    loaded = update_helper._load_manifest(plan, verification_context=False)
    with pytest.raises(update_install.InstallPlanError) as mismatch:
        update_helper._verify_saved_package(plan, loaded)
    assert mismatch.value.code == "INSTALL_PACKAGE_MISMATCH"


def _http(body: bytes, *, status: str = "200 OK", content_type: str = "application/json") -> bytes:
    return (
        f"HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    ).encode("ascii") + body


def _redirect(location: str) -> bytes:
    return (
        "HTTP/1.1 302 Found\r\n"
        f"Location: {location}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    ).encode("ascii")


class _GitHubTls:
    """A real controlled-TLS GitHub API/asset/CDN server on loopback."""

    MANIFEST_PATH = (
        f"/{update_github.GITHUB_REPO}/releases/download/v0.2.0/"
        f"{update_github.MANIFEST_ASSET}"
    )
    PACKAGE_PATH = (
        f"/{update_github.GITHUB_REPO}/releases/download/v0.2.0/"
        f"{update_github.PACKAGE_ASSET}"
    )
    CDN_MANIFEST = (
        "/github-production-release-asset/93446099/"
        "d39d1596-8cd3-40db-9201-ef23820cb68f?sp=r&sig=manifest"
    )
    CDN_PACKAGE = (
        "/github-production-release-asset/93446099/"
        "aaaaaaaa-8cd3-40db-9201-ef23820cb68f?sp=r&sig=package"
    )

    def __init__(
        self,
        tmp_path: Path,
        *,
        manifest: bytes,
        package: bytes,
        release: dict | None = None,
        redirect_location: str | None = None,
        hold_package: bool = False,
    ):
        self.manifest = manifest
        self.package = package
        self.release = release or _release()
        self.redirect_location = redirect_location
        self.hold_package = hold_package
        self.package_started = threading.Event()
        ca_dir = tmp_path / "ca"
        _cert, _key, pem = w3_tls.create_ca(ca_dir)
        leaf_cert, leaf_key = w3_tls.create_leaf(
            ca_dir,
            tmp_path / "leaf",
            hostnames=[
                "api.github.com",
                "github.com",
                update_github.GITHUB_ASSET_HOST,
            ],
        )
        self.ca_pem = pem.decode("ascii")
        self.server = w3_tls.TlsServer(
            cert=leaf_cert,
            key=leaf_key,
            segment_factory=self._segments,
        ).start()
        self.port = self.server.port

    def _segments(self, request: bytes):
        head = request.split(b"\r\n", 1)[0].decode("ascii", "replace")
        parts = head.split(" ")
        path = parts[1] if len(parts) > 1 else ""
        if path == update_github.GITHUB_API_PATH:
            return [(_http(json.dumps(self.release).encode()), 0)]
        if path == self.MANIFEST_PATH:
            if self.redirect_location is not None:
                return [(_redirect(self.redirect_location), 0)]
            return [
                (
                    _redirect(
                        "https://"
                        + update_github.GITHUB_ASSET_HOST
                        + self.CDN_MANIFEST
                    ),
                    0,
                )
            ]
        if path == self.PACKAGE_PATH:
            return [
                (
                    _redirect(
                        "https://"
                        + update_github.GITHUB_ASSET_HOST
                        + self.CDN_PACKAGE
                    ),
                    0,
                )
            ]
        if path == self.CDN_MANIFEST:
            return [(_http(self.manifest), 0)]
        if path == self.CDN_PACKAGE:
            if self.hold_package:
                self.package_started.set()
                header = (
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
                    b"Content-Length: "
                    + str(len(self.package)).encode()
                    + b"\r\n\r\n"
                )
                return [(header + self.package[:64], 0), (b"", 10)]
            return [(_http(self.package, content_type="application/octet-stream"), 0)]
        return [(_http(b"{}", status="404 Not Found"), 0)]

    def source(self):
        return update_github.api_source(
            {"test-key": PUBLIC},
            test_only=True,
            ca_pem=self.ca_pem,
            connect_host="127.0.0.1",
            connect_port=self.port,
        )

    def stop(self):
        self.server.stop()


def test_github_real_tls_check_redirect_manifest_download_and_verify(tmp_path):
    package, build_id, sha, size = _make_package(tmp_path)
    manifest = _manifest_bytes(
        package_size=size, package_sha256=sha, build_id=build_id
    )
    fixture = _GitHubTls(
        tmp_path,
        manifest=manifest,
        package=package.read_bytes(),
    )
    try:
        manager = update_service.UpdateManager(
            CURRENT,
            source=fixture.source(),
            enabled=True,
            staging_root=tmp_path / "staging",
            allow_install=True,
        )
        manager.check()
        state = _wait_state(manager, "available", timeout=8.0)
        assert state["download_available"] is True
        assert state["target"]["version"] == "0.2.0"
        manager.download()
        ready = _wait_state(manager, "ready", timeout=15.0)
        assert ready["progress"]["percent"] == 100
        payload = manager.install_payload()
        assert payload["package_zip"].read_bytes() == package.read_bytes()
        assert (
            payload["staging_dir"]
            / "KindergartenManager"
            / "KindergartenManager.exe"
        ).is_file()
        requests = b"".join(fixture.server.requests)
        assert b"Host: api.github.com" in requests
        assert b"Host: github.com" in requests
        assert b"Host: release-assets.githubusercontent.com" in requests
        assert b"Authorization" not in requests
    finally:
        fixture.stop()


def test_github_real_tls_bad_signature_and_hash_fail_closed(tmp_path):
    package, build_id, sha, size = _make_package(tmp_path)
    envelope = json.loads(
        _manifest_bytes(package_size=size, package_sha256=sha, build_id=build_id)
    )
    signature = envelope["signature"]
    envelope["signature"] = ("A" if signature[0] != "A" else "B") + signature[1:]
    bad_signature = json.dumps(envelope).encode()
    fixture = _GitHubTls(tmp_path, manifest=bad_signature, package=package.read_bytes())
    try:
        manager = update_service.UpdateManager(
            CURRENT,
            source=fixture.source(),
            enabled=True,
            staging_root=tmp_path / "staging-bad-signature",
            allow_install=True,
        )
        manager.check()
        state = _wait_state(manager, "failed", timeout=8.0)
        assert state["error_code"] == "UPDATE_METADATA_UNTRUSTED"
    finally:
        fixture.stop()

    fixture = _GitHubTls(
        tmp_path / "hash",
        manifest=_manifest_bytes(
            package_size=size, package_sha256="b" * 64, build_id=build_id
        ),
        package=package.read_bytes(),
    )
    try:
        manager = update_service.UpdateManager(
            CURRENT,
            source=fixture.source(),
            enabled=True,
            staging_root=tmp_path / "staging-bad-hash",
            allow_install=True,
        )
        manager.check()
        _wait_state(manager, "available", timeout=8.0)
        manager.download()
        state = _wait_state(manager, "failed", timeout=15.0)
        assert state["error_code"] == "UPDATE_PACKAGE_MISMATCH"
    finally:
        fixture.stop()

    bad_tag = _manifest_bytes(
        package_size=size,
        package_sha256=sha,
        build_id=build_id,
        package_url=(
            f"/{update_github.GITHUB_REPO}/releases/download/v0.3.0/"
            f"{update_github.PACKAGE_ASSET}"
        ),
    )
    fixture = _GitHubTls(
        tmp_path / "tag",
        manifest=bad_tag,
        package=package.read_bytes(),
    )
    try:
        manager = update_service.UpdateManager(
            CURRENT,
            source=fixture.source(),
            enabled=True,
            staging_root=tmp_path / "staging-bad-tag",
            allow_install=True,
        )
        manager.check()
        state = _wait_state(manager, "failed", timeout=8.0)
        assert state["error_code"] == "UPDATE_METADATA_INVALID"
    finally:
        fixture.stop()


def test_github_real_tls_forbidden_redirect_and_asset_fail(tmp_path):
    package, build_id, sha, size = _make_package(tmp_path)
    manifest = _manifest_bytes(
        package_size=size, package_sha256=sha, build_id=build_id
    )
    fixture = _GitHubTls(
        tmp_path / "redirect",
        manifest=manifest,
        package=package.read_bytes(),
        redirect_location="https://evil.example/file",
    )
    try:
        manager = update_service.UpdateManager(
            CURRENT,
            source=fixture.source(),
            enabled=True,
            staging_root=tmp_path / "staging-redirect",
            allow_install=True,
        )
        manager.check()
        state = _wait_state(manager, "failed", timeout=8.0)
        assert state["error_code"] == "UPDATE_DOWNLOAD_INVALID"
        assert "sig=" not in (state.get("error_message") or "")
    finally:
        fixture.stop()

    release = _release()
    release["assets"] = [
        item
        for item in release["assets"]
        if item["name"] != update_github.PACKAGE_ASSET
    ]
    fixture = _GitHubTls(
        tmp_path / "asset",
        manifest=manifest,
        package=package.read_bytes(),
        release=release,
    )
    try:
        manager = update_service.UpdateManager(
            CURRENT,
            source=fixture.source(),
            enabled=True,
            staging_root=tmp_path / "staging-asset",
            allow_install=True,
        )
        manager.check()
        state = _wait_state(manager, "available", timeout=8.0)
        assert state["reason"] == "UPDATE_ASSETS_MISSING"
        assert state["download_available"] is False
    finally:
        fixture.stop()


def test_github_real_tls_download_cancel_and_deadline(tmp_path):
    package, build_id, sha, size = _make_package(tmp_path)
    manifest = _manifest_bytes(
        package_size=size, package_sha256=sha, build_id=build_id
    )
    fixture = _GitHubTls(
        tmp_path / "cancel",
        manifest=manifest,
        package=package.read_bytes(),
        hold_package=True,
    )
    try:
        manager = update_service.UpdateManager(
            CURRENT,
            source=fixture.source(),
            enabled=True,
            staging_root=tmp_path / "staging-cancel",
            allow_install=True,
        )
        manager.check()
        _wait_state(manager, "available", timeout=8.0)
        manager.download()
        assert fixture.package_started.wait(5.0)
        manager.cancel()
        state = _wait_state(manager, "cancelled", timeout=8.0)
        assert state["reason"] == "UPDATE_CANCELLED"
    finally:
        fixture.stop()

    fixture = _GitHubTls(
        tmp_path / "deadline",
        manifest=manifest,
        package=package.read_bytes(),
        hold_package=True,
    )
    try:
        manager = update_service.UpdateManager(
            CURRENT,
            source=fixture.source(),
            enabled=True,
            staging_root=tmp_path / "staging-deadline",
            allow_install=True,
            total_timeout=2.0,
            read_timeout=0.5,
        )
        manager.check()
        _wait_state(manager, "available", timeout=8.0)
        manager.download()
        state = _wait_state(manager, "failed", timeout=8.0)
        assert state["error_code"] == "UPDATE_DOWNLOAD_TIMEOUT"
    finally:
        fixture.stop()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("test_only", True),
        ("test_only", False),
        ("test_only", None),
        ("connect_host", "127.0.0.1"),
        ("connect_port", 43210),
        ("ca_pem", "synthetic-unread-certificate"),
        ("server_hostname", "controlled-test.example"),
    ],
)
def test_product_github_loader_rejects_every_test_field(tmp_path, field, value):
    config = tmp_path / "update_release.json"
    config.write_text(
        json.dumps(
            {
                "public_keys": {
                    "test-key": base64.b64encode(PUBLIC).decode("ascii")
                },
                field: value,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ReleaseConfigError):
        update_github.load_github_source(config)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("test_only", True),
        ("test_only", False),
        ("test_only", None),
        ("connect_host", "127.0.0.1"),
        ("connect_port", 43210),
        ("ca_pem", "synthetic-unread-certificate"),
        ("server_hostname", "controlled-test.example"),
    ],
)
def test_ordinary_release_loader_rejects_test_fields(tmp_path, field, value):
    config = tmp_path / "update_release.json"
    config.write_text(
        json.dumps(
            {
                "origin": "https://updates.example.test",
                "metadata_path": "/stable/windows-x64/manifest.json",
                "public_keys": {
                    "test-key": base64.b64encode(PUBLIC).decode("ascii")
                },
                field: value,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ReleaseConfigError):
        load_release_source(config)


def test_product_github_loader_never_enables_test_transport(tmp_path):
    config = tmp_path / "update_release.json"
    config.write_text(
        json.dumps(
            {
                "public_keys": {
                    "test-key": base64.b64encode(PUBLIC).decode("ascii")
                }
            }
        ),
        encoding="utf-8",
    )
    source = update_github.load_github_source(config)
    assert source.provider == "github"
    assert source.test_only is False
    assert source.ca_pem is None
    assert source.connect_host is None
    assert source.connect_port is None
    assert source.server_hostname is None
    source.validate()
    missing = update_github.load_github_source(tmp_path / "missing.json")
    assert missing.provider == "github"
    assert missing.configured is True
    assert missing.public_keys == {}
    assert missing.test_only is False


def test_non_test_release_source_rejects_connection_overrides():
    source = ReleaseSource(
        origin="https://updates.example.test",
        metadata_path="/stable/windows-x64/manifest.json",
        public_keys={"test-key": PUBLIC},
        connect_host="127.0.0.1",
        connect_port=43210,
        ca_pem="synthetic",
        server_hostname="controlled-test.example",
    )
    with pytest.raises(ReleaseConfigError):
        source.validate()
    explicit = update_github.api_source(
        {"test-key": PUBLIC},
        test_only=True,
        ca_pem="synthetic",
        connect_host="127.0.0.1",
        connect_port=43210,
        server_hostname="controlled-test.example",
    )
    explicit.validate()
    assert explicit.test_only is True


def test_product_loader_only_keys_or_missing_still_discovers(monkeypatch, tmp_path):
    config = tmp_path / "update_release.json"
    config.write_text(
        json.dumps(
            {
                "public_keys": {
                    "test-key": base64.b64encode(PUBLIC).decode("ascii")
                }
            }
        ),
        encoding="utf-8",
    )
    source = update_github.load_github_source(config)

    def fake_open(source, url, read_timeout=update_service.READ_TIMEOUT, *, deadline=None):
        if url == update_github.GITHUB_API_ORIGIN + update_github.GITHUB_API_PATH:
            return None, _Response(200, json.dumps(_release()).encode()), _Sock()
        return None, _Response(200, _manifest_bytes()), _Sock()

    monkeypatch.setattr(update_service, "_open_url", fake_open)
    manager = update_service.UpdateManager(
        CURRENT,
        source=source,
        enabled=True,
        staging_root=tmp_path / "staging-keys",
        allow_install=True,
    )
    manager.check()
    state = _wait_state(manager, "available", timeout=8.0)
    assert state["target"]["version"] == "0.2.0"
    assert state["download_available"] is True

    missing = update_github.load_github_source(tmp_path / "missing.json")
    manager2 = update_service.UpdateManager(
        CURRENT,
        source=missing,
        enabled=True,
        staging_root=tmp_path / "staging-missing",
        allow_install=True,
    )

    def fake_open_release_only(source, url, read_timeout=update_service.READ_TIMEOUT, *, deadline=None):
        return None, _Response(200, json.dumps(_release()).encode()), _Sock()

    monkeypatch.setattr(update_service, "_open_url", fake_open_release_only)
    manager2.check()
    state2 = _wait_state(manager2, "available", timeout=8.0)
    assert state2["target"]["version"] == "0.2.0"
    assert state2["reason"] == "UPDATE_TRUST_UNCONFIGURED"
    assert state2["download_available"] is False


PREVIEW_CURRENT = AppIdentity(
    **{
        **CURRENT.as_dict(),
        "channel": "preview",
        "version": "0.1.0-listening-test.20261107",
    }
)


def _preview_list(tags: list[str]) -> bytes:
    return json.dumps(
        [
            _release(tag, prerelease=True, assets=True)
            for tag in tags
        ],
        ensure_ascii=False,
    ).encode("utf-8")


def test_preview_release_list_filters_markers_and_keeps_latest_missing_assets():
    raw = json.dumps(
        [
            _release("v0.2.0-listening-test.3", prerelease=True),
            _release("v0.2.0-listening-test.10", prerelease=True, assets=False),
            _release("v0.2.0", prerelease=False),
            _release("v0.2.0-listening-test.99", draft=True, prerelease=True),
            _release("v0.2.1", prerelease=True),
            _release("v0.2.0-preview.1", prerelease=True),
        ],
        ensure_ascii=False,
    ).encode("utf-8")
    releases, item_count, preview_count = update_github.parse_preview_release_page(raw)
    assert item_count == 6
    assert preview_count == 2
    assert [release.version for release in releases] == [
        "0.2.0-listening-test.3",
        "0.2.0-listening-test.10",
    ]
    selected = update_github.select_preview_release(
        releases, PREVIEW_CURRENT.version
    )
    assert selected is not None
    assert selected.version == "0.2.0-listening-test.10"
    assert selected.assets_complete is False
    assert selected.missing_assets == (update_github.MANIFEST_ASSET,)
    assert update_github.select_preview_release(releases, "0.2.0") is None
    bad_tags = [
        "v0.1.0-listening-test.10\n",
        "v0.1.0-listening-test.1٢",
    ]
    for bad_tag in bad_tags:
        bad_releases, bad_count, bad_preview = update_github.parse_preview_release_page(
            json.dumps(
                [_release(bad_tag, prerelease=True)], ensure_ascii=False
            ).encode("utf-8")
        )
        assert bad_count == 1
        assert bad_preview == 0
        assert bad_releases == []
    with pytest.raises(ManifestError) as bad_stable:
        update_github.parse_latest_release(
            json.dumps(_release("v0.2.0\n")).encode(), CURRENT.version
        )
    assert bad_stable.value.code == "UPDATE_METADATA_INVALID"
    with pytest.raises(ManifestError) as bad_current:
        update_github.select_preview_release(releases, "0.2.0\n")
    assert bad_current.value.code == "UPDATE_METADATA_INVALID"
    with pytest.raises(ManifestError):
        update_github.select_preview_release(
            [SimpleNamespace(version="0.2.0\n")], CURRENT.version
        )


def test_manifest_binding_rejects_non_ascii_or_trailing_newline_versions():
    release = update_github.parse_latest_release(
        json.dumps(_release("v0.2.0")).encode(), CURRENT.version
    )
    for bad_version in ("0.2.0\n", "0.2٢.0"):
        manifest = SimpleNamespace(
            channel=release.channel,
            version=bad_version,
            package_url=update_github.expected_package_url(release),
        )
        with pytest.raises(ManifestError) as caught:
            update_github.validate_manifest_binding(manifest, release)
        assert caught.value.code == "UPDATE_METADATA_INVALID"
        with pytest.raises(ManifestError) as helper:
            update_github.validate_github_manifest_for_version(
                manifest, release.version
            )
        assert helper.value.code == "UPDATE_METADATA_INVALID"


def test_stable_release_comparison_allows_same_base_promotion_and_blocks_downgrade():
    release = update_github.parse_latest_release(
        json.dumps(_release("v0.1.0")).encode(), PREVIEW_CURRENT.version
    )
    assert release.version == "0.1.0"

    higher_preview = AppIdentity(
        **{
            **CURRENT.as_dict(),
            "channel": "preview",
            "version": "0.2.0-listening-test.5",
        }
    )
    with pytest.raises(ManifestError) as below:
        update_github.parse_latest_release(
            json.dumps(_release("v0.1.0")).encode(), higher_preview.version
        )
    assert below.value.code == "UPDATE_STABLE_BELOW_INSTALLED"


def test_preview_manager_discovers_switches_to_stable_and_persists_preference(
    monkeypatch, tmp_path
):
    preference = tmp_path / "channel-preference.json"
    manager = update_service.UpdateManager(
        PREVIEW_CURRENT,
        source=_source(),
        enabled=True,
        staging_root=tmp_path / "preview-staging",
        allow_install=False,
        channel_preference_path=preference,
    )
    assert manager.state()["check_channel"] == "preview"
    assert manager.state()["available_channels"] == ["stable", "preview"]

    def fake_open(source, url, read_timeout=update_service.READ_TIMEOUT, *, deadline=None):
        if url == update_github.GITHUB_API_ORIGIN + update_github.GITHUB_API_PATH:
            return None, _Response(200, json.dumps(_release("v0.1.0")).encode()), _Sock()
        if "?per_page=100&page=1" in url:
            return (
                None,
                _Response(
                    200,
                    _preview_list(
                        [
                            "v0.2.0-listening-test.3",
                            "v0.2.0-listening-test.10",
                        ]
                    ),
                ),
                _Sock(),
            )
        if "0.2.0-listening-test.10" in url:
            return (
                None,
                _Response(
                    200,
                    _manifest_bytes(
                        tag="v0.2.0-listening-test.10",
                        version="0.2.0-listening-test.10",
                        channel="preview",
                    ),
                ),
                _Sock(),
            )
        return (
            None,
            _Response(200, _manifest_bytes(tag="v0.1.0", version="0.1.0")),
            _Sock(),
        )

    monkeypatch.setattr(update_service, "_open_url", fake_open)
    manager.check()
    preview_state = _wait_state(manager, "available")
    assert preview_state["target"]["version"] == "0.2.0-listening-test.10"
    assert preview_state["target"]["channel"] == "preview"
    assert preview_state["reason"] is None
    assert preview_state["download_available"] is False

    switched = manager.set_channel("stable")
    assert switched["check_channel"] == "stable"
    assert switched["target"] is None
    assert switched["state"] == "idle"
    assert preference.is_file()
    assert json.loads(preference.read_text(encoding="utf-8"))["channel"] == "stable"

    manager.check()
    stable_state = _wait_state(manager, "available")
    assert stable_state["target"]["version"] == "0.1.0"
    assert stable_state["target"]["channel"] == "stable"
    assert stable_state["download_available"] is False

    reopened = update_service.UpdateManager(
        PREVIEW_CURRENT,
        source=_source(),
        enabled=True,
        staging_root=tmp_path / "other-staging",
        allow_install=False,
        channel_preference_path=preference,
    )
    assert reopened.state()["check_channel"] == "stable"


def test_preview_manager_reports_incomplete_no_release_and_busy_switch(
    monkeypatch, tmp_path
):
    def full_page(source, url, read_timeout=update_service.READ_TIMEOUT, *, deadline=None):
        page = int(url.rsplit("page=", 1)[1])
        tags = [
            f"v0.2.0-listening-test.{page * 100 + index}"
            for index in range(100)
        ]
        return None, _Response(200, _preview_list(tags)), _Sock()

    manager = update_service.UpdateManager(
        PREVIEW_CURRENT,
        source=_source(),
        enabled=True,
        staging_root=tmp_path / "incomplete-staging",
        allow_install=False,
        channel_preference_path=tmp_path / "incomplete-pref.json",
    )
    monkeypatch.setattr(update_service, "_open_url", full_page)
    manager.check()
    state = _wait_state(manager, "incomplete")
    assert state["reason"] == "UPDATE_CHECK_INCOMPLETE"
    assert state["target"] is None

    empty = update_service.UpdateManager(
        PREVIEW_CURRENT,
        source=_source(),
        enabled=True,
        staging_root=tmp_path / "empty-staging",
        allow_install=False,
        channel_preference_path=tmp_path / "empty-pref.json",
    )
    monkeypatch.setattr(
        update_service,
        "_open_url",
        lambda *args, **kwargs: (None, _Response(200, b"[]"), _Sock()),
    )
    empty.check()
    empty_state = _wait_state(empty, "no_release")
    assert empty_state["reason"] == "UPDATE_NO_RELEASE"

    failure = update_service.UpdateManager(
        PREVIEW_CURRENT,
        source=_source(),
        enabled=True,
        staging_root=tmp_path / "failure-staging",
        allow_install=False,
        channel_preference_path=tmp_path / "failure-pref.json",
    )
    monkeypatch.setattr(
        update_service,
        "_open_url",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()),
    )
    failure.check()
    failure_state = _wait_state(failure, "failed")
    assert failure_state["error_code"] == "UPDATE_DOWNLOAD_TIMEOUT"

    gate = threading.Event()

    def blocked(source, url, read_timeout=update_service.READ_TIMEOUT, *, deadline=None):
        gate.wait(5.0)
        if url == update_github.GITHUB_API_ORIGIN + update_github.GITHUB_API_PATH:
            return None, _Response(200, json.dumps(_release("v0.2.0")).encode()), _Sock()
        return None, _Response(200, _manifest_bytes()), _Sock()

    busy = update_service.UpdateManager(
        CURRENT,
        source=_source(),
        enabled=True,
        staging_root=tmp_path / "busy-staging",
        allow_install=False,
        channel_preference_path=tmp_path / "busy-pref.json",
    )
    monkeypatch.setattr(update_service, "_open_url", blocked)
    busy.check()
    busy_switch = busy.set_channel("preview")
    assert busy_switch["check_channel"] == "stable"
    assert busy_switch["channel_switch_error"] == "UPDATE_CHANNEL_SWITCH_BUSY"
    gate.set()
    _wait_state(busy, "available")


def test_signed_manifest_uses_real_preview_identity_and_channel_ordering():
    preview_source = replace(_source(), channel="preview")
    stable_source = _source()
    preview_current = PREVIEW_CURRENT.version

    stable_from_preview = update_manifest.parse_signed_manifest(
        _manifest_bytes(tag="v0.1.0", version="0.1.0", channel="stable"),
        stable_source,
        preview_current,
        CURRENT.database_revision,
    )
    assert stable_from_preview.version == "0.1.0"

    preview_next = update_manifest.parse_signed_manifest(
        _manifest_bytes(
            tag="v0.2.0-listening-test.10",
            version="0.2.0-listening-test.10",
            channel="preview",
        ),
        preview_source,
        preview_current,
        CURRENT.database_revision,
    )
    assert preview_next.channel == "preview"
    assert preview_next.version == "0.2.0-listening-test.10"

    cross_channel_higher = update_manifest.parse_signed_manifest(
        _manifest_bytes(
            tag="v0.2.0-listening-test.10",
            version="0.2.0-listening-test.10",
            channel="preview",
        ),
        preview_source,
        "0.1.0",
        CURRENT.database_revision,
    )
    assert cross_channel_higher.version == "0.2.0-listening-test.10"

    with pytest.raises(ManifestError) as same_base_preview:
        update_manifest.parse_signed_manifest(
            _manifest_bytes(
                tag="v0.1.0-listening-test.10",
                version="0.1.0-listening-test.10",
                channel="preview",
            ),
            preview_source,
            "0.1.0",
            CURRENT.database_revision,
        )
    assert same_base_preview.value.code == "UPDATE_NO_NEW_VERSION"

    higher_preview = AppIdentity(
        **{
            **CURRENT.as_dict(),
            "channel": "preview",
            "version": "0.2.0-listening-test.5",
        }
    )
    with pytest.raises(ManifestError) as lower_stable:
        update_manifest.parse_signed_manifest(
            _manifest_bytes(tag="v0.1.0", version="0.1.0", channel="stable"),
            stable_source,
            higher_preview.version,
            CURRENT.database_revision,
        )
    assert lower_stable.value.code == "UPDATE_NO_NEW_VERSION"

    with pytest.raises(ManifestError) as wrong_channel:
        update_manifest.parse_signed_manifest(
            _manifest_bytes(
                tag="v0.2.0-listening-test.10",
                version="0.2.0-listening-test.10",
                channel="preview",
            ),
            stable_source,
            preview_current,
            CURRENT.database_revision,
        )
    assert wrong_channel.value.code == "UPDATE_METADATA_INVALID"


def test_manifest_binding_matches_channel_tag_and_fixed_asset_url():
    releases, _, _ = update_github.parse_preview_release_page(
        json.dumps([_release("v0.2.0-listening-test.10", prerelease=True)]).encode()
    )
    release = releases[0]
    manifest = SimpleNamespace(
        channel="preview",
        version="0.2.0-listening-test.10",
        package_url=update_github.expected_package_url(release),
    )
    update_github.validate_manifest_binding(manifest, release)

    for bad in (
        SimpleNamespace(channel="stable", version=manifest.version, package_url=manifest.package_url),
        SimpleNamespace(channel="preview", version="0.2.0-listening-test.9", package_url=manifest.package_url),
        SimpleNamespace(
            channel="preview",
            version=manifest.version,
            package_url=f"/{update_github.GITHUB_REPO}/releases/download/v0.2.0-listening-test.9/{update_github.PACKAGE_ASSET}",
        ),
    ):
        with pytest.raises(ManifestError):
            update_github.validate_manifest_binding(bad, release)
    with pytest.raises(ManifestError):
        update_github.validate_github_manifest_for_version(
            SimpleNamespace(
                channel="preview",
                version=manifest.version,
                package_url=manifest.package_url,
            ),
            "0.2.0-listening-test.9",
        )


def test_preview_release_source_accepts_matching_tag_and_rejects_channel_mismatch():
    releases, _, _ = update_github.parse_preview_release_page(
        json.dumps([_release("v0.2.0-listening-test.10", prerelease=True)]).encode()
    )
    release = releases[0]
    source = update_github.manifest_source(release, {"test-key": PUBLIC})
    source.validate()
    assert source.channel == "preview"
    assert source.github_tag == "v0.2.0-listening-test.10"
    for bad in (
        replace(source, channel="stable"),
        replace(source, github_tag="v0.2.0"),
        replace(source, github_tag="v0.2.0-listening-test.010"),
        replace(source, github_tag="v0.2.0-listening-test.10\n"),
    ):
        with pytest.raises(ReleaseConfigError):
            bad.validate()


def test_preview_manifest_rejects_untrusted_signature():
    raw = _manifest_bytes(
        tag="v0.2.0-listening-test.10",
        version="0.2.0-listening-test.10",
        channel="preview",
    )
    other = Ed25519PrivateKey.generate()
    other_public = other.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    with pytest.raises(ManifestError) as caught:
        update_manifest.parse_signed_manifest(
            raw,
            replace(_source({"test-key": other_public}), channel="preview"),
            PREVIEW_CURRENT.version,
            CURRENT.database_revision,
        )
    assert caught.value.code == "UPDATE_METADATA_UNTRUSTED"


def test_preview_package_identity_mismatch_is_rejected(monkeypatch, tmp_path):
    bad_package, build_id, sha, size = _make_package(
        tmp_path,
        version="0.2.0-listening-test.10",
        channel="stable",
    )
    manifest = _manifest_bytes(
        tag="v0.2.0-listening-test.10",
        version="0.2.0-listening-test.10",
        channel="preview",
        package_size=size,
        package_sha256=sha,
        build_id=build_id,
    )
    plan = _helper_plan(
        tmp_path,
        manifest,
        bad_package,
        current_version=PREVIEW_CURRENT.version,
    )
    config = tmp_path / "updater-preview-bad" / "update_release.json"
    config.parent.mkdir(parents=True)
    _write_github_config(config, PUBLIC)
    monkeypatch.setattr(update_helper, "_trusted_release_config_path", lambda: config)
    loaded = update_helper._load_manifest(plan, verification_context=False)
    with pytest.raises(ManifestError) as caught:
        update_helper._verify_saved_package(plan, loaded)
    assert caught.value.code == "UPDATE_PACKAGE_INVALID"


def test_preview_manager_downloads_signed_preview_and_verifies_package(monkeypatch, tmp_path):
    package, build_id, sha, size = _make_package(
        tmp_path,
        version="0.2.0-listening-test.10",
        channel="preview",
    )
    package_bytes = package.read_bytes()
    manifest = _manifest_bytes(
        tag="v0.2.0-listening-test.10",
        version="0.2.0-listening-test.10",
        channel="preview",
        package_size=size,
        package_sha256=sha,
        build_id=build_id,
    )
    preview_tag = "v0.2.0-listening-test.10"

    def fake_open(source, url, read_timeout=update_service.READ_TIMEOUT, *, deadline=None):
        if "?per_page=100&page=1" in url:
            return None, _Response(200, _preview_list([
                "v0.2.0-listening-test.3",
                preview_tag,
            ])), _Sock()
        if f"/releases/download/{preview_tag}/" in url and url.endswith(
            update_github.MANIFEST_ASSET
        ):
            return None, _Response(200, manifest), _Sock()
        if f"/releases/download/{preview_tag}/" in url and url.endswith(
            update_github.PACKAGE_ASSET
        ):
            return None, _Response(200, package_bytes), _Sock()
        raise AssertionError(f"unexpected update URL {url}")

    monkeypatch.setattr(update_service, "_open_url", fake_open)
    manager = update_service.UpdateManager(
        PREVIEW_CURRENT,
        source=_source(),
        enabled=True,
        staging_root=tmp_path / "preview-download-staging",
        allow_install=True,
        channel_preference_path=tmp_path / "preview-preference.json",
    )
    try:
        manager.check()
        available = _wait_state(manager, "available", timeout=8.0)
        assert available["target"]["channel"] == "preview"
        assert available["target"]["version"] == preview_tag[1:]
        assert available["download_available"] is True

        manager.download()
        ready = _wait_state(manager, "ready", timeout=8.0)
        assert ready["target"]["channel"] == "preview"
        assert ready["target"]["build_id"] == build_id
        payload = manager.install_payload()
        assert payload["manifest"].channel == "preview"
        assert payload["manifest"].version == preview_tag[1:]
    finally:
        manager.shutdown()


def test_product_helper_allows_same_base_preview_to_stable_promotion(
    monkeypatch, tmp_path
):
    package, build_id, sha, size = _make_package(
        tmp_path,
        version="0.1.0",
        channel="stable",
    )
    manifest = _manifest_bytes(
        tag="v0.1.0",
        version="0.1.0",
        channel="stable",
        package_size=size,
        package_sha256=sha,
        build_id=build_id,
    )
    plan = _helper_plan(
        tmp_path,
        manifest,
        package,
        current_version=PREVIEW_CURRENT.version,
    )
    config = tmp_path / "updater-promotion" / "update_release.json"
    config.parent.mkdir(parents=True)
    _write_github_config(config, PUBLIC)
    monkeypatch.setattr(update_helper, "_trusted_release_config_path", lambda: config)
    loaded = update_helper._load_manifest(plan, verification_context=False)
    assert loaded.channel == "stable"
    assert loaded.version == "0.1.0"
    verified = update_helper._verify_saved_package(plan, loaded)
    assert (verified.root / "KindergartenManager.exe").is_file()


def test_product_helper_rejects_low_version_plan_against_actual_old_package(
    monkeypatch, tmp_path
):
    package, build_id, sha, size = _make_package(
        tmp_path,
        version="0.1.0",
        channel="stable",
    )
    manifest = _manifest_bytes(
        tag="v0.1.0",
        version="0.1.0",
        channel="stable",
        package_size=size,
        package_sha256=sha,
        build_id=build_id,
    )
    plan = _helper_plan(
        tmp_path,
        manifest,
        package,
        current_version="0.2.0",
    )
    config = tmp_path / "updater-low" / "update_release.json"
    config.parent.mkdir(parents=True)
    _write_github_config(config, PUBLIC)
    monkeypatch.setattr(update_helper, "_trusted_release_config_path", lambda: config)
    with pytest.raises(ManifestError) as caught:
        update_helper._load_manifest(plan, verification_context=False)
    assert caught.value.code == "UPDATE_NO_NEW_VERSION"


def test_product_helper_rejects_changed_actual_old_package_identity(
    monkeypatch, tmp_path
):
    package, build_id, sha, size = _make_package(
        tmp_path,
        version="0.2.0",
        channel="stable",
    )
    manifest = _manifest_bytes(
        tag="v0.2.0",
        version="0.2.0",
        channel="stable",
        package_size=size,
        package_sha256=sha,
        build_id=build_id,
    )
    plan = _helper_plan(tmp_path, manifest, package, current_version="0.1.0")
    changed = CURRENT.as_dict()
    changed["version"] = "0.2.0"
    changed["channel"] = "stable"
    (Path(plan.install_app_dir) / "_internal" / "build_identity.json").write_text(
        json.dumps(changed, ensure_ascii=False),
        encoding="utf-8",
    )
    config = tmp_path / "updater-changed" / "update_release.json"
    config.parent.mkdir(parents=True)
    _write_github_config(config, PUBLIC)
    monkeypatch.setattr(update_helper, "_trusted_release_config_path", lambda: config)
    with pytest.raises(update_install.InstallPlanError) as caught:
        update_helper._load_manifest(plan, verification_context=False)
    assert caught.value.code == "INSTALL_CURRENT_IDENTITY_MISMATCH"


def test_product_helper_reverifies_preview_target_and_package_identity(monkeypatch, tmp_path):
    package, build_id, sha, size = _make_package(
        tmp_path,
        version="0.2.0-listening-test.10",
        channel="preview",
    )
    manifest = _manifest_bytes(
        tag="v0.2.0-listening-test.10",
        version="0.2.0-listening-test.10",
        channel="preview",
        package_size=size,
        package_sha256=sha,
        build_id=build_id,
    )
    plan = _helper_plan(
        tmp_path,
        manifest,
        package,
        current_version=PREVIEW_CURRENT.version,
    )
    config = tmp_path / "updater-preview" / "update_release.json"
    config.parent.mkdir(parents=True)
    _write_github_config(config, PUBLIC)
    monkeypatch.setattr(update_helper, "_trusted_release_config_path", lambda: config)

    loaded = update_helper._load_manifest(plan, verification_context=False)
    assert loaded.channel == "preview"
    assert loaded.version == "0.2.0-listening-test.10"
    verified = update_helper._verify_saved_package(plan, loaded)
    assert (verified.root / "KindergartenManager.exe").is_file()
