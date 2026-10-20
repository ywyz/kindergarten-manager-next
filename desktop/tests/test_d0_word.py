"""D0-5 basis: synthetic daily Word generation reuses the real I5 pipeline."""

import io
import sys
import zipfile
from datetime import date
from pathlib import Path

from lxml import etree

DESKTOP_DIR = Path(__file__).resolve().parent.parent
BACKEND_ROOT = DESKTOP_DIR.parent / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import d0_paths
import d0_word
from app.services import word_export_docx as docx


W = docx.W
_w = docx._w


def _text_of(data: bytes) -> str:
    assert zipfile.is_zipfile(io.BytesIO(data))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    return "".join(t.text or "" for t in root.iter(_w("t")))


class TestSyntheticDailyDocx:
    def test_template_is_repo_controlled_asset(self):
        assert d0_paths.daily_word_template_path() == docx.DAILY_TEMPLATE

    def test_generates_nonempty_valid_docx_with_synthetic_content(self):
        data = d0_word.synthetic_docx_bytes(date(2026, 10, 14))
        assert len(data) > 1000
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            bad = archive.testzip()
            assert bad is None
        text = _text_of(data)
        for expected in (
            "D0 合成园一日活动计划",
            "合成小班",
            "D0 合成教师",
            "第 3 周",
            "10 月 14 日",
            "D0 合成活动主题",
            "D0 合成第一步。",
            "D0 合成第二步。",
            "D0 合成一日常反思。",
        ):
            assert expected in text

    def test_red_baseline_absent_when_no_split_baseline(self):
        data = d0_word.synthetic_docx_bytes()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            root = etree.fromstring(archive.read("word/document.xml"))
        red = [
            "".join(t.text or "" for t in run.iter(_w("t")))
            for run in root.iter(_w("r"))
            for color in [run.find(f"{_w('rPr')}/{_w('color')}")]
            if color is not None and color.get(_w("val")) == "FF0000"
        ]
        # D0 probe uses no split baseline: no artificial red text.
        assert "".join(red) == ""

    def test_record_view_contract_matches_mapping(self):
        view = d0_word.synthetic_daily_view()
        assert view["kind"] == "daily_plan"
        assert view["content_version"] == 7
        assert view["header"]["grade"] == "小班"
