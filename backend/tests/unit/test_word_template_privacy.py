"""Privacy regression for the controlled Word templates.

The test deliberately does not contain any removed personal names, school names
or sample plan text. It verifies structural allowlists, Office-property absence
and the canonical table/merge layout the exporters depend on.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from app.services import word_export_docx, word_export_observation

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC = "http://purl.org/dc/elements/1.1/"
DCTERMS = "http://purl.org/dc/terms/"
APP = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
CUSTOM = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"

REPO = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = REPO / "app" / "assets" / "word_templates"
HISTORICAL = (
    REPO.parent
    / "docs/bootstrap/evidence/browser-capabilities-2026-10-02"
    / "小班甲_日计划_2026-09-01_2026-09-01 (2).docx"
)

DAILY_LABELS = {
    "一日活动计划",
    "班级\u3000教师",
    "第 周",
    "月 日  周",
    "晨间活动：",
    "晨间谈话：",
    "集体活动：",
    "室内区域游戏：",
    "下午：户外游戏",
    "一日活动反思：",
}
WEEKLY_LABELS = {
    "每周工作计划表",
    "主题名称：《》 班级： 第（ ）周（ 年 月 日—— 月 日）",
    "教师： 保育员：",
    "周次",
    "周一",
    "周二",
    "周三",
    "周四",
    "周五",
    "学习活动",
    "晨间谈话",
    "集体活动",
    "游戏活动",
    "户外游戏",
    "区域游戏",
    "本周重点",
    "环境创设",
    "生活习惯培养",
    "家园共育",
}
OBSERVATION_LABELS = {
    "班  级",
    "日    期",
    "起止时间",
    "成人数目",
    "儿童数目",
    "观察者",
    "幼儿姓名",
    "幼儿年龄",
    "观察环境",
    "观察目标",
    "观察记录",
    "评价分析",
    "支持策略",
}
FILES = (
    ("daily", TEMPLATE_DIR / "daily_plan.docx", DAILY_LABELS, 19, 2, 5),
    ("weekly", TEMPLATE_DIR / "weekly_plan.docx", WEEKLY_LABELS, 9, 7, 5),
    ("public", TEMPLATE_DIR / "observation_public.docx", OBSERVATION_LABELS, 8, 6, 1),
    ("indoor", TEMPLATE_DIR / "observation_indoor.docx", OBSERVATION_LABELS, 8, 6, 1),
    ("outdoor", TEMPLATE_DIR / "observation_outdoor.docx", OBSERVATION_LABELS, 8, 6, 1),
)


def _texts(root):
    return [
        "".join(node.text or "" for node in paragraph.iter(f"{{{W}}}t"))
        for paragraph in root.iter(f"{{{W}}}p")
    ]


def _document_texts(root):
    """Header paragraph and complete table-cell texts (labels may span runs)."""
    body = root.find(f"{{{W}}}body")
    texts = []
    for paragraph in body.findall(f"{{{W}}}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{{{W}}}t"))
        if text.strip():
            texts.append(text)
    for cell in body.iter(f"{{{W}}}tc"):
        text = "".join(node.text or "" for node in cell.iter(f"{{{W}}}t"))
        if text.strip():
            texts.append(text)
    return texts


def _assert_core_and_app(path: Path, *, neutral: bool = True) -> None:
    with zipfile.ZipFile(path) as archive:
        core = etree.fromstring(archive.read("docProps/core.xml"))
        app = etree.fromstring(archive.read("docProps/app.xml"))
        custom_bytes = (
            archive.read("docProps/custom.xml")
            if "docProps/custom.xml" in archive.namelist()
            else None
        )
    assert core.find(f"{{{DC}}}creator") is None
    assert core.find(f"{{{CP}}}lastModifiedBy") is None
    revision = core.find(f"{{{CP}}}revision")
    assert revision is not None and revision.text == "1"
    for tag in ("created", "modified"):
        node = core.find(f"{{{DCTERMS}}}{tag}")
        assert node is not None and node.text == "2000-01-01T00:00:00Z"
    company = app.find(f"{{{APP}}}Company")
    assert company is not None and (company.text or "") == ""
    if neutral:
        assert (app.findtext(f"{{{APP}}}Pages") or "") == "1"
        assert (app.findtext(f"{{{APP}}}Words") or "") == "0"
    if custom_bytes is not None:
        custom = etree.fromstring(custom_bytes)
        for prop in custom:
            name = (prop.get("name") or "").lower()
            assert "ksotemplatedocersaverecord" not in name
            assert "user" not in name
            assert "author" not in name
            assert "lastmodified" not in name


@pytest.mark.parametrize("kind,path,labels,rows,columns,table_count", FILES)
def test_controlled_template_is_blank_and_metadata_safe(
    kind: str, path: Path, labels: set[str], rows: int, columns: int, table_count: int
) -> None:
    assert path.is_file(), path
    _assert_core_and_app(path)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert not any(name.startswith("word/media/") for name in names)
        for name in names:
            if not name.startswith("word/") or not name.endswith(".xml"):
                continue
            root = etree.fromstring(archive.read(name))
            for element in root.iter():
                assert f"{{{W}}}author" not in element.attrib
                assert f"{{{W}}}initials" not in element.attrib
            if name == "word/document.xml":
                texts = _document_texts(root)
                assert set(texts) <= labels, (kind, name, set(texts) - labels)
            else:
                texts = [text for text in _texts(root) if text.strip()]
                assert texts == [], (kind, name, texts[:3])
        document = etree.fromstring(archive.read("word/document.xml"))
    body = document.find(f"{{{W}}}body")
    tables = body.findall(f"{{{W}}}tbl")
    assert len(tables) == table_count
    table = tables[0]
    assert len(table.findall(f"{{{W}}}tr")) == rows
    grid = table.find(f"{{{W}}}tblGrid")
    assert grid is not None and len(grid.findall(f"{{{W}}}gridCol")) == columns


def test_controlled_template_hash_constants_match_assets() -> None:
    assert (
        hashlib.sha256((TEMPLATE_DIR / "daily_plan.docx").read_bytes()).hexdigest()
        == word_export_docx.DAILY_TEMPLATE_SHA256
    )
    assert (
        hashlib.sha256((TEMPLATE_DIR / "weekly_plan.docx").read_bytes()).hexdigest()
        == word_export_docx.WEEKLY_TEMPLATE_SHA256
    )
    for record_type, (name, expected) in word_export_observation.TEMPLATES.items():
        assert (
            hashlib.sha256((TEMPLATE_DIR / name).read_bytes()).hexdigest()
            == expected
        ), record_type


def test_historical_evidence_metadata_is_sanitized_but_body_preserved() -> None:
    assert HISTORICAL.is_file(), HISTORICAL
    _assert_core_and_app(HISTORICAL, neutral=False)
    with zipfile.ZipFile(HISTORICAL) as archive:
        document = etree.fromstring(archive.read("word/document.xml"))
    body = document.find(f"{{{W}}}body")
    table = body.find(f"{{{W}}}tbl")
    assert table is not None
    assert len(table.findall(f"{{{W}}}tr")) == 19
    assert any(text.strip() for text in _texts(body))
