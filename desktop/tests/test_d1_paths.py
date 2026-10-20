"""D1 resource resolution: env overrides, source layout and defaults."""

from pathlib import Path

import d1_paths


def test_frontend_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("KGM_D1_FRONTEND_DIR", str(tmp_path))
    assert d1_paths.frontend_dist() == tmp_path.resolve()
    assert d1_paths.frontend_index() == tmp_path.resolve() / "d1.html"


def test_frontend_dir_default_in_source_checkout(monkeypatch):
    monkeypatch.delenv("KGM_D1_FRONTEND_DIR", raising=False)
    expected = d1_paths.package_root() / "build" / "desktop-d1" / "frontend"
    assert d1_paths.frontend_dist() == expected


def test_verify_save_dir_env(monkeypatch, tmp_path):
    monkeypatch.delenv("KGM_D1_VERIFY_SAVE_DIR", raising=False)
    assert d1_paths.verify_save_dir() is None
    monkeypatch.setenv("KGM_D1_VERIFY_SAVE_DIR", str(tmp_path))
    assert d1_paths.verify_save_dir() == tmp_path.resolve()


def test_not_frozen_in_tests():
    assert d1_paths.is_frozen() is False
    assert isinstance(d1_paths.package_root(), Path)
