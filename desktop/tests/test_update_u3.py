"""D3-U U3 source-context boundary regressions."""

from __future__ import annotations

import os
import sys
from dataclasses import replace

import d1_main
import update_helper
import test_update_u2 as u2


class _Args:
    def __init__(self, *, selftest: bool, phase: str, identity: str | None):
        self.selftest = selftest
        self.phase = phase
        self.u3_source_identity = identity


def test_source_verification_context_requires_dedicated_entry(monkeypatch):
    monkeypatch.setenv("KGM_UPDATE_VERIFICATION_CONTEXT", "1")
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert d1_main._source_verification_context(
        _Args(selftest=True, phase="u3-verify", identity="identity.json")
    ) is True
    assert d1_main._source_verification_context(
        _Args(selftest=False, phase="u3-verify", identity="identity.json")
    ) is False
    assert d1_main._source_verification_context(
        _Args(selftest=True, phase="u3-update", identity="identity.json")
    ) is False
    assert d1_main._source_verification_context(
        _Args(selftest=True, phase="u3-verify", identity=None)
    ) is False
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert d1_main._source_verification_context(
        _Args(selftest=True, phase="u3-verify", identity="identity.json")
    ) is False
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delenv("KGM_UPDATE_VERIFICATION_CONTEXT", raising=False)
    assert d1_main._source_verification_context(
        _Args(selftest=True, phase="u3-verify", identity="identity.json")
    ) is False


def test_product_helper_clears_inherited_source_context(monkeypatch, tmp_path):
    plan, _data, _cred, _old_app = u2._plan(
        tmp_path, target_revision=u2.HEAD_REV, old_revision=u2.HEAD_REV
    )
    # Product helper plans do not have a test launch command.
    plan = replace(plan, new_app_command=[])
    monkeypatch.setenv("KGM_UPDATE_VERIFICATION_CONTEXT", "1")
    _command, product_env = update_helper._new_app_command(
        plan, verification_context=False
    )
    assert "KGM_UPDATE_VERIFICATION_CONTEXT" not in product_env
    _command, source_env = update_helper._new_app_command(
        plan, verification_context=True
    )
    assert source_env.get("KGM_UPDATE_VERIFICATION_CONTEXT") == "1"
