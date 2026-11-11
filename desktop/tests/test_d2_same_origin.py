"""D2 same-origin fingerprint stability regressions.

The normal-source hash algorithm is unchanged; the only widening is a stable
UTF-8 encoding for legal lone-surrogate constants (the XML sanitizer regex).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import d2_same_origin


def _normal_hash(code) -> str:
    payload = json.dumps(
        d2_same_origin._code_signature(code),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_normal_source_keeps_existing_utf8_hash(tmp_path):
    source = tmp_path / "normal.py"
    source.write_text("VALUE = '正常文本'\n", encoding="utf-8")
    code = compile(
        source.read_text(encoding="utf-8"),
        str(source),
        "exec",
        dont_inherit=True,
    )
    assert d2_same_origin.fingerprint_code(code) == _normal_hash(code)
    assert d2_same_origin.fingerprint_source(source) == _normal_hash(code)


def test_surrogate_constant_is_stable_and_does_not_collide(tmp_path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    copy = tmp_path / "copy.py"
    text = 'PATTERN = "[\\ud800-\\udfff]"\n'
    first.write_text(text, encoding="utf-8")
    second.write_text('PATTERN = "[\\ud801-\\udfff]"\n', encoding="utf-8")
    copy.write_bytes(first.read_bytes())
    one = d2_same_origin.fingerprint_source(first)
    assert one == d2_same_origin.fingerprint_source(copy)
    assert one != d2_same_origin.fingerprint_source(second)


def test_curriculum_content_surrogate_regex_hashes_without_error():
    root = Path(__file__).resolve().parents[2]
    source = root / "backend" / "app" / "local" / "curriculum_content.py"
    assert d2_same_origin.fingerprint_source(source)
