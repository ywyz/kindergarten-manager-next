"""Structural DOCX checks for the generated observation samples.

Complements the real-Word page inspection: verifies the fixed six-column /
eight-row template, merges, font sizes, title page breaks, inline image groups
and absence of nested paragraphs/captions.  This is not a substitute for the
real Word check in ``verify_observation_export_word.ps1``.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from lxml import etree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"


def cell_text(cell) -> str:
    return "".join(node.text or "" for node in cell.iter(W + "t"))


def first_size(cell) -> int | None:
    # The value run is appended after the template paragraph properties; use
    # the last run-level size (the actual rendered value), not a template
    # paragraph-mark size that Word ignores for the run.
    sizes = cell.findall(".//" + W + "r/" + W + "rPr/" + W + "sz")
    if not sizes:
        return None
    value = sizes[-1].get(W + "val")
    return int(value) if value is not None else None


def inspect(path: Path, sample: dict) -> list[str]:
    failures: list[str] = []
    name = sample["file"]
    try:
        with zipfile.ZipFile(path) as archive:
            root = etree.fromstring(archive.read("word/document.xml"))
    except Exception as exc:  # noqa: BLE001
        return [f"{name}: DOCX unreadable ({type(exc).__name__})"]
    body = root.find(W + "body")
    if body is None:
        return [f"{name}: missing body"]
    tables = body.findall(W + "tbl")
    if len(tables) != sample["records"]:
        return [f"{name}: tables {len(tables)} != {sample['records']}"]
    title_paragraphs = [child for child in body if child.tag == W + "p"]
    if len(title_paragraphs) != sample["records"]:
        failures.append(
            f"{name}: title paragraphs {len(title_paragraphs)} != {sample['records']}"
        )
    for index, table in enumerate(tables):
        rows = table.findall(W + "tr")
        if len(rows) != 8:
            failures.append(f"{name}: table {index} rows {len(rows)} != 8")
            continue
        grid = table.find(W + "tblGrid")
        if grid is None or len(grid.findall(W + "gridCol")) != 6:
            failures.append(f"{name}: table {index} grid is not 6 columns")
        cells = [row.findall(W + "tc") for row in rows]
        if any(len(row) != 6 for row in cells[:2]):
            failures.append(f"{name}: table {index} rows 1-2 are not 6 cells")
        if len(cells[2]) != 4:
            failures.append(f"{name}: table {index} row 3 is not 4 cells")
        if any(len(row) != 2 for row in cells[3:]):
            failures.append(f"{name}: table {index} rows 4-8 are not 2 cells")
        if len(cells[2]) == 4:
            span = cells[2][1].find(W + "tcPr/" + W + "gridSpan")
            if span is None or span.get(W + "val") != "3":
                failures.append(f"{name}: table {index} name span != 3")
        for row_index in range(3, 8):
            if len(cells[row_index]) != 2:
                continue
            span = cells[row_index][1].find(W + "tcPr/" + W + "gridSpan")
            if span is None or span.get(W + "val") != "5":
                failures.append(
                    f"{name}: table {index} row {row_index + 1} span != 5"
                )
        if first_size(cells[0][1]) != 22:
            failures.append(f"{name}: table {index} basic size != 11pt")
        if cell_text(cells[4][1]).strip() and first_size(cells[4][1]) != 24:
            failures.append(f"{name}: table {index} body size != 12pt")
        if first_size(cells[6][1]) != 24:
            failures.append(f"{name}: table {index} evaluation size != 12pt")
        evaluation = cell_text(cells[6][1])
        for label in ("健康", "语言", "社会", "科学", "艺术"):
            if label not in evaluation:
                failures.append(f"{name}: table {index} missing {label}")
        photo_cell = cells[5][1]
        photo_paragraphs = [
            paragraph
            for paragraph in photo_cell.findall(W + "p")
            if paragraph.findall(W + "r/" + W + "drawing")
        ]
        for paragraph in photo_paragraphs:
            drawings = paragraph.findall(W + "r/" + W + "drawing")
            if not 1 <= len(drawings) <= 2:
                failures.append(
                    f"{name}: table {index} photo group has {len(drawings)} drawings"
                )
        if photo_cell.findall(W + "p/" + W + "p"):
            failures.append(f"{name}: table {index} has nested paragraphs")
    nested = root.findall(".//" + W + "p/" + W + "p")
    if nested:
        failures.append(f"{name}: nested w:p count {len(nested)}")
    anchors = root.findall(".//" + WP + "anchor")
    if anchors:
        failures.append(f"{name}: floating anchors count {len(anchors)}")
    doc_ids = [node.get("id") for node in root.findall(".//" + WP + "docPr")]
    if len(doc_ids) != len(set(doc_ids)):
        failures.append(f"{name}: duplicate wp:docPr ids")
    if len(doc_ids) != sample["photos"]:
        failures.append(f"{name}: wp:docPr {len(doc_ids)} != photos {sample['photos']}")
    all_text = "".join(node.text or "" for node in root.iter(W + "t"))
    if sample.get("caption") and sample["caption"] in all_text:
        failures.append(f"{name}: caption was printed")
    for index, title in enumerate(sample["titles"]):
        if title not in all_text:
            failures.append(f"{name}: title {index} missing")
    if len(title_paragraphs) == sample["records"]:
        for index, paragraph in enumerate(title_paragraphs):
            if cell_text(paragraph) != sample["titles"][index]:
                failures.append(f"{name}: title {index} text mismatch")
            sizes = paragraph.findall(".//" + W + "sz")
            if not sizes or any(size.get(W + "val") != "32" for size in sizes):
                failures.append(f"{name}: title {index} is not 16pt")
            if paragraph.find(".//" + W + "rPr/" + W + "b") is None:
                failures.append(f"{name}: title {index} is not bold")
            alignment = paragraph.find(W + "pPr/" + W + "jc")
            if alignment is None or alignment.get(W + "val") != "center":
                failures.append(f"{name}: title {index} is not centered")
            page_break = paragraph.find(W + "pPr/" + W + "pageBreakBefore")
            if index == 0 and page_break is not None:
                failures.append(f"{name}: first title has a page break")
            if index > 0 and page_break is None:
                failures.append(f"{name}: title {index} lacks a page break")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    args = parser.parse_args()
    expected_path = args.input_dir / "expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    for sample in expected["samples"]:
        failures.extend(inspect(args.input_dir / sample["file"], sample))
    if failures:
        for failure in failures:
            print("FAIL", failure)
        return 1
    print(f"DOCX XML checks passed for {len(expected['samples'])} samples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
