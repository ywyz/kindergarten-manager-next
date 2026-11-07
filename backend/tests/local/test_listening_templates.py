"""Controlled listening template registry and cleaned DOCX checks."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from app.local import listening_templates as templates


EXPECTED_COUNTS = {
    "small": {"health": 7, "language": 6, "social": 7, "science": 6, "art": 4},
    "middle": {"health": 6, "language": 6, "social": 7, "science": 6, "art": 4},
    "large": {"health": 6, "language": 6, "social": 7, "science": 6, "art": 4},
}


def test_manifest_registers_fifteen_cleaned_templates() -> None:
    entries = templates.list_templates()
    assert len(entries) == 15
    assert {(entry.grade, entry.domain) for entry in entries} == {
        (grade, domain)
        for grade in templates.GRADES
        for domain in templates.DOMAINS
    }
    for entry in entries:
        assert entry.version == "v1"
        assert entry.sha256 == hashlib.sha256(
            templates.TEMPLATE_ROOT.joinpath(*entry.path.split("/")).read_bytes()
        ).hexdigest()
        assert len(entry.items) == EXPECTED_COUNTS[entry.grade][entry.domain]
        item_ids = [item.item_id for item in entry.items]
        assert len(item_ids) == len(set(item_ids))
        for item in entry.items:
            assert item.item_id.startswith(entry.domain + "_")
            assert item.requirement
            assert set(item.standards) == {"1", "2", "3"}
            assert all(item.standards[star] for star in ("1", "2", "3"))


def test_missing_explicit_version_never_falls_back_to_latest() -> None:
    with pytest.raises(templates.ListeningTemplateNotFound):
        templates.get_template("small", "health", "v2")
    with pytest.raises(templates.ListeningTemplateNotFound):
        templates.get_template("small", "health", "v0")
    with pytest.raises(templates.ListeningTemplateNotFound):
        templates.get_template("unknown", "health")
    with pytest.raises(templates.ListeningTemplateNotFound):
        templates.get_template("small", "unknown")


def test_cleaned_docx_parts_have_no_personal_or_external_material() -> None:
    for entry in templates.list_templates():
        path = templates.TEMPLATE_ROOT.joinpath(*entry.path.split("/"))
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            assert "docProps/custom.xml" not in names
            core = archive.read("docProps/core.xml").decode("utf-8")
            assert "dc:creator" not in core
            assert "cp:lastModifiedBy" not in core
            assert "Rebecca" not in core
            assert "WPS" not in core
            for rel_name in names:
                if not rel_name.endswith(".rels"):
                    continue
                rel = archive.read(rel_name)
                assert b'TargetMode="External"' not in rel
            from xml.etree import ElementTree as ET

            root = ET.fromstring(archive.read("word/document.xml"))
            text = "".join(
                node.text or ""
                for node in root.iter(
                    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
                )
            )
            assert "一对一倾听" in text
            for item in entry.items:
                assert item.requirement.replace("\n", "") in text
                for star in ("1", "2", "3"):
                    assert item.standards[star].replace("\n", "") in text


def test_manifest_counts_match_repository_assets() -> None:
    manifest = json.loads(
        (templates.TEMPLATE_ROOT / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["format_version"] == 1
    assert manifest["default_version"] == "v1"
    assert len(manifest["templates"]) == 15


def test_template_bytes_are_reverified() -> None:
    entry = templates.get_template("middle", "health")
    payload = templates.read_template_bytes(entry)
    assert payload.startswith(b"PK")
    assert hashlib.sha256(payload).hexdigest() == entry.sha256
