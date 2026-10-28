"""Safe Microsoft Word COM inspector via the existing Python.NET runtime.

The host Python environment already carries ``clr``/Python.NET but not
win32com/comtypes.  This script uses only Office document COM APIs through
Python.NET; it never changes execution policy, installs packages or invokes a
shell.  If Word/Python.NET is unavailable it exits nonzero and the caller
records that as a limitation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import clr  # noqa: F401
    from System import Activator, Enum, Type
    from System.Reflection import BindingFlags, Missing
except Exception as exc:  # noqa: BLE001
    print(f"Python.NET/COM unavailable: {type(exc).__name__}")
    raise SystemExit(2)


def enum_type(obj, method_name: str, index: int):
    for method in obj.GetType().GetMethods():
        if method.Name == method_name:
            return method.GetParameters()[index].ParameterType
    raise RuntimeError(f"COM method not found: {method_name}")


def open_word():
    word_type = Type.GetTypeFromProgID("Word.Application")
    if word_type is None:
        raise RuntimeError("Word.Application ProgID unavailable")
    word = Activator.CreateInstance(word_type)
    word.Visible = False
    return word


def open_document(word, path: Path):
    # Documents.Open has 15 optional object& parameters; explicit Missing
    # values avoid the COM DISP_E_TYPEMISMATCH seen with short positional calls.
    args = [str(path)] + [Missing.Value] * 15
    args[2] = True  # ReadOnly
    result = word.Documents.Open(*args)
    return result[0] if isinstance(result, tuple) else result


def compute_pages(doc) -> int:
    stat_type = enum_type(doc, "ComputeStatistics", 0)
    result = doc.ComputeStatistics(Enum.ToObject(stat_type, 2), Missing.Value)
    return int(result[0] if isinstance(result, tuple) else result)


def page_starts(doc, pages: int) -> list[int]:
    starts = []
    for page in range(1, pages + 1):
        result = doc.GoTo(1, 1, page, Missing.Value)
        range_obj = result[0] if isinstance(result, tuple) else result
        starts.append(int(range_obj.Start))
    return starts


def information(range_obj, code: int):
    return range_obj.GetType().InvokeMember(
        "Information", BindingFlags.GetProperty, None, range_obj, (code,)
    )


def text_of(doc, start: int, end: int) -> str:
    result = doc.Range(start, end)
    range_obj = result[0] if isinstance(result, tuple) else result
    return str(range_obj.Text)


def inspect(path: Path, sample: dict) -> dict:
    word = open_word()
    doc = open_document(word, path)
    try:
        doc.Repaginate()
        pages = compute_pages(doc)
        starts = page_starts(doc, pages)
        page_texts = []
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else int(doc.Content.End)
            page_texts.append(text_of(doc, start, end))
        page_visible_lengths = [
            len(re.sub(r"[\s\x00-\x1f\x7f]", "", text)) for text in page_texts
        ]
        page_shape_counts = [0] * pages
        shapes = []
        for index in range(1, int(doc.InlineShapes.Count) + 1):
            shape = doc.InlineShapes[index]
            shape_start = int(shape.Range.Start)
            page = int(information(shape.Range, 3))
            if page < 1 or page > pages:
                page = 1
                for page_index, page_start in enumerate(starts):
                    if shape_start >= page_start:
                        page = page_index + 1
            if 1 <= page <= pages:
                page_shape_counts[page - 1] += 1
            shapes.append(
                {
                    "width": float(shape.Width),
                    "height": float(shape.Height),
                    "type": int(shape.Type),
                    "page": page,
                    "left": float(information(shape.Range, 5)),
                    "top": float(information(shape.Range, 6)),
                    "paragraph_alignment": int(
                        shape.Range.ParagraphFormat.Alignment
                    ),
                }
            )
        title_pages = []
        for title in sample["titles"]:
            found = -1
            for page_index, text in enumerate(page_texts):
                if str(title) in text:
                    found = page_index + 1
                    break
            title_pages.append(found)
        content_text = str(doc.Content.Text)
        caption_printed = bool(
            sample.get("caption") and str(sample["caption"]) in content_text
        )
        cell_sizes = []
        table_rows = 0
        table_columns = 0
        if int(doc.Tables.Count) >= 1:
            table = doc.Tables[1]
            table_rows = int(table.Rows.Count)
            table_columns = int(table.Columns.Count)
            cell_sizes = [
                float(table.Cell(1, 2).Range.Font.Size),
                float(table.Cell(5, 2).Range.Font.Size),
                float(table.Cell(7, 2).Range.Font.Size),
            ]
        title_paragraph = doc.Paragraphs[1]
        last_page_visible = (
            page_visible_lengths[-1] if page_visible_lengths else 0
        )
        last_page_shapes = page_shape_counts[-1] if page_shape_counts else 0
        return {
            "file": sample["file"],
            "pages": pages,
            "tables": int(doc.Tables.Count),
            "table_rows": table_rows,
            "table_columns": table_columns,
            "inline_shapes": int(doc.InlineShapes.Count),
            "page_width": float(doc.PageSetup.PageWidth),
            "page_height": float(doc.PageSetup.PageHeight),
            "orientation": int(doc.PageSetup.Orientation),
            "margin_top": float(doc.PageSetup.TopMargin),
            "margin_bottom": float(doc.PageSetup.BottomMargin),
            "margin_left": float(doc.PageSetup.LeftMargin),
            "margin_right": float(doc.PageSetup.RightMargin),
            "title_size": float(title_paragraph.Range.Font.Size),
            "title_bold": int(title_paragraph.Range.Font.Bold),
            "title_alignment": int(title_paragraph.Alignment),
            "cell_sizes": cell_sizes,
            "title_pages": title_pages,
            "page_text_lengths": [len(text) for text in page_texts],
            "page_visible_lengths": page_visible_lengths,
            "page_shape_counts": page_shape_counts,
            "last_page_text_length": len(page_texts[-1]) if page_texts else 0,
            "last_page_visible_length": last_page_visible,
            "last_page_shapes": last_page_shapes,
            "word_version": str(word.Version),
            "word_build": str(word.Build),
            "caption_printed": caption_printed,
            "shapes": shapes,
        }
    finally:
        doc.Close(0)
        word.Quit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    results = []
    for sample in expected["samples"]:
        results.append(inspect(args.input_dir / sample["file"], sample))
    args.output.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"inspected {len(results)} samples with Word COM")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
