"""Generate real synthetic observation-export Word samples for Word review.

This entry point uses the product export service (synthetic database, synthetic
JPEGs, fake local profile) and writes the actual managed DOCX artifacts.  It
never calls AI, reads the teacher's real database/credentials, or touches the
real experience directory.

Run (desktop/.venv-d1):
    python desktop/verify_observation_export_word.py \
        --output-dir C:/.../opencode-evidence/word-samples
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from PIL import Image  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.local import (  # noqa: E402
    observation_assets,
    observation_export_service,
    observation_service,
    profile_service,
)
from app.local.models import LocalProfile  # noqa: E402
from app.local.normalize import normalize_initialization  # noqa: E402
from app.local.runtime import LocalRuntime  # noqa: E402


def jpeg_bytes(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def full_payload(
    record_type: str,
    date: str,
    subject: str,
    process: str,
    *,
    start: str = "10:00",
    goal: str = "观察幼儿在游戏中的合作与表达",
    school: str | None = None,
) -> dict:
    payload = {
        "record_type": record_type,
        "observation_date": date,
        "start_time": start,
        "end_time": "10:20",
        "adult_count": 2,
        "child_count": 6,
        "observer_name": "王老师",
        "age_years": 5,
        "subjects": [{"name": subject}],
        "environment": "积木区",
        "observation_goal": goal,
        "observation_process": process,
        "analysis_evaluation": {
            "health": "动作协调，能持续参与。",
            "language": "能用完整语句表达自己的想法。",
            "social": "愿意与同伴协商并分工。",
            "science": "尝试比较积木的长短和稳定性。",
            "arts": "用不同颜色和形状表现搭建结果。",
        },
        "support_strategy": "提供更多连接材料，鼓励幼儿记录搭建过程。",
    }
    if school is not None:
        payload["school_name"] = school
    return payload


def create_record(
    session,
    runtime,
    profile_id: str,
    *,
    record_type: str,
    payload: dict,
    photos: list[tuple[int, int, tuple[int, int, int]]],
    caption: str | None = None,
    observation_date: str | None | object = ...,
) -> str:
    kwargs = {}
    if observation_date is not ...:
        kwargs["observation_date"] = observation_date
    created = observation_service.create_observation(
        session,
        profile_id=profile_id,
        request_id=str(uuid.uuid4()),
        record_type=record_type,
        payload=payload,
        **kwargs,
    )
    observation_id = created["observation_id"]
    assets: list[dict] = []
    for index, (width, height, color) in enumerate(photos):
        asset = observation_assets.import_asset(
            session,
            runtime,
            profile_id=profile_id,
            observation_id=observation_id,
            request_id=str(uuid.uuid4()),
            expected_revision=observation_service.read_current(
                session, profile_id=profile_id, observation_id=observation_id
            )["revision"],
            stream=io.BytesIO(jpeg_bytes(width, height, color)),
            display_name=f"synthetic-{index}.jpg",
            caption=caption,
        )
        assets.append(asset)
    current = observation_service.read_current(
        session, profile_id=profile_id, observation_id=observation_id
    )
    observation_service.save_observation(
        session,
        profile_id=profile_id,
        observation_id=observation_id,
        request_id=str(uuid.uuid4()),
        expected_revision=current["revision"],
        payload=payload,
        photos=[
            {"asset_id": asset["asset_id"], "caption": caption} for asset in assets
        ],
        save_reason="manual",
        term_decision="keep_current",
    )
    return observation_id


def export_sample(
    session,
    runtime,
    profile_id: str,
    observation_ids: list[str],
    output: Path,
    *,
    ack_missing: bool = True,
) -> dict:
    preview = observation_export_service.preview_export(
        session,
        runtime,
        profile_id=profile_id,
        request_id=str(uuid.uuid4()),
        observation_ids=observation_ids,
        launch_id="",
        session_scope="",
    )
    created = observation_export_service.create_export(
        session,
        runtime,
        profile_id=profile_id,
        request_id=str(uuid.uuid4()),
        snapshot_id=preview["snapshot_id"],
        ack_missing=ack_missing,
        launch_id="",
        session_scope="",
    )
    artifact = observation_export_service.read_export_content(
        session,
        runtime,
        profile_id=profile_id,
        export_id=created["export_id"],
        launch_id="",
        session_scope="",
    )
    try:
        data = artifact.handle.read()
    finally:
        observation_export_service.release_artifact(runtime, artifact)
    output.write_bytes(data)
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "preview_missing": preview["missing"],
    }


def inspect_in_word(output_dir: Path, expected_path: Path) -> int:
    inspection_path = output_dir / "word-inspection.json"
    script = Path(__file__).resolve().parent / "verify_observation_export_word_com.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--input-dir",
            str(output_dir),
            "--expected",
            str(expected_path),
            "--output",
            str(inspection_path),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if completed.returncode != 0:
        print(completed.stdout)
        print(completed.stderr)
        raise SystemExit("Word COM inspection failed")
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    inspections = {
        item["file"]: item
        for item in json.loads(inspection_path.read_text(encoding="utf-8"))
    }
    failures: list[str] = []
    word_versions = set()
    word_builds = set()
    for sample in expected["samples"]:
        name = sample["file"]
        word = inspections.get(name)
        if word is None:
            failures.append(f"{name}: no Word inspection")
            continue
        word_versions.add(word.get("word_version"))
        word_builds.add(word.get("word_build"))
        def check(condition: bool, message: str) -> None:
            if not condition:
                failures.append(f"{name}: {message}")
        check(word["pages"] >= sample["min_pages"], f"pages {word['pages']} < {sample['min_pages']}")
        check(word["tables"] == sample["records"], f"tables {word['tables']} != {sample['records']}")
        check(word["table_rows"] == 8, f"table rows {word['table_rows']} != 8")
        check(word["table_columns"] == 6, f"table columns {word['table_columns']} != 6")
        check(word["inline_shapes"] == sample["photos"], f"inline shapes {word['inline_shapes']} != {sample['photos']}")
        check(abs(word["page_width"] - 595.3) < 1.0, "page width is not A4")
        check(abs(word["page_height"] - 841.9) < 1.0, "page height is not A4")
        check(word["orientation"] == 0, "page is not portrait")
        for key, expected_margin in (
            ("margin_top", 72.0),
            ("margin_bottom", 72.0),
            ("margin_left", 90.0),
            ("margin_right", 90.0),
        ):
            check(abs(word[key] - expected_margin) < 1.0, f"{key} {word[key]} != {expected_margin}")
        check(word["title_size"] == 16, f"title size {word['title_size']} != 16")
        check(word["title_bold"] == -1, "title is not bold")
        check(word["title_alignment"] == 1, "title is not centered")
        check(word["cell_sizes"] == [11.0, 12.0, 12.0], f"cell sizes {word['cell_sizes']} != [11,12,12]")
        check(
            len(word["title_pages"]) == sample["records"],
            f"title pages {word['title_pages']} do not cover every record",
        )
        check(all(page >= 1 for page in word["title_pages"]), "a record title is missing")
        check(
            all(a < b for a, b in zip(word["title_pages"], word["title_pages"][1:])),
            f"records do not start on strictly later pages: {word['title_pages']}",
        )
        check(
            word["last_page_visible_length"] > 0 or word["last_page_shapes"] > 0,
            "last page has no visible text or image",
        )
        check(not word["caption_printed"], "photo caption was printed")
        shapes = word["shapes"]
        check(len(shapes) == sample["photos"], "shape count mismatch")
        for index, (shape, aspect) in enumerate(zip(shapes, sample["aspects"])):
            check(shape["type"] == 3, f"shape {index} is not a picture")
            expected_ratio = aspect[0] / aspect[1]
            actual_ratio = shape["width"] / shape["height"]
            check(
                abs(actual_ratio - expected_ratio) / expected_ratio < 0.03,
                f"shape {index} aspect {actual_ratio:.4f} != {expected_ratio:.4f}",
            )
        groups = sample.get("group_sizes")
        if not isinstance(groups, list) or sum(groups) != sample["photos"]:
            failures.append(f"{name}: invalid group_sizes metadata")
            groups = []
        cursor = 0
        for group_index, size in enumerate(groups):
            group = shapes[cursor : cursor + size]
            cursor += size
            if len(group) != size:
                failures.append(f"{name}: group {group_index} shape count mismatch")
                continue
            if size == 1:
                shape = group[0]
                check(
                    shape.get("paragraph_alignment") == 1,
                    f"group {group_index} single image is not centered",
                )
                check(
                    shape["left"] >= 0
                    and shape["width"]
                    <= word["page_width"] - word["margin_left"] - word["margin_right"] + 2,
                    f"group {group_index} single image exceeds usable width",
                )
            elif size == 2:
                first, second = group
                check(
                    first["page"] == second["page"],
                    f"group {group_index} images are on different pages",
                )
                check(
                    first.get("paragraph_alignment") == 1
                    and second.get("paragraph_alignment") == 1,
                    f"group {group_index} images are not centered inline",
                )
                check(
                    second["left"] >= first["left"] + first["width"] - 2,
                    f"group {group_index} images overlap horizontally",
                )
                vertical_overlap = min(
                    first["top"] + first["height"],
                    second["top"] + second["height"],
                ) - max(first["top"], second["top"])
                check(
                    vertical_overlap > 0.5 * min(first["height"], second["height"]),
                    f"group {group_index} images are stacked, not side by side",
                )
                check(
                    first["left"] >= 0
                    and second["left"] >= 0
                    and first["width"] + second["width"]
                    <= word["page_width"] - word["margin_left"] - word["margin_right"] + 2,
                    f"group {group_index} images exceed usable width",
                )
        if cursor != len(shapes):
            failures.append(f"{name}: group_sizes do not cover all shapes")
    if failures:
        for failure in failures:
            print("FAIL", failure)
        raise SystemExit(f"{len(failures)} Word checks failed")
    print(
        "Word checks passed for "
        f"{len(expected['samples'])} samples; Word {sorted(word_versions)} build {sorted(word_builds)}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="output directory; defaults to a new temporary directory",
    )
    parser.add_argument(
        "--word",
        action="store_true",
        help="also open every sample in the installed Microsoft Word and validate pages",
    )
    args = parser.parse_args()
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else Path(tempfile.mkdtemp(prefix="kgm-observation-word-samples-")).resolve()
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    root = Path(tempfile.mkdtemp(prefix="kgm-word-verify-"))
    runtime = LocalRuntime(root / "data", credential_root=root / "credentials")
    runtime.prepare()
    session = runtime.session()
    samples: list[dict] = []
    try:
        profile_service.initialize(
            session,
            normalize_initialization(
                request_id=str(uuid.uuid4()),
                display_name="王老师",
                class_name="中一班",
                grade="middle",
                term_name="2026 年秋季学期",
                start_date="2026-09-01",
                end_date="2026-09-30",
                school_name="长园所名称示例幼儿园",
            ),
        )
        session.commit()
        profile = session.scalars(select(LocalProfile)).one()

        # 01: zero photos, public, full content.
        o1 = create_record(
            session,
            runtime,
            profile.id,
            record_type="public",
            payload=full_payload(
                "public", "2026-09-15", "小明", "幼儿在积木区合作搭建一座桥。"
            ),
            photos=[],
        )
        p1 = output_dir / "01_public_zero_photo.docx"
        meta1 = export_sample(session, runtime, profile.id, [o1], p1)
        samples.append(
            {
                "file": p1.name,
                "records": 1,
                "photos": 0,
                "group_sizes": [],
                "titles": ["长园所名称示例幼儿园游戏观察记录（公共）"],
                "min_pages": 1,
                "aspects": [],
                "caption": None,
                **meta1,
            }
        )

        # 02: one portrait photo, indoor.
        o2 = create_record(
            session,
            runtime,
            profile.id,
            record_type="indoor",
            payload=full_payload(
                "indoor", "2026-09-16", "小红", "幼儿在室内阅读区讲述图画书。"
            ),
            photos=[(600, 900, (200, 40, 40))],
            caption="不得打印的照片说明",
        )
        p2 = output_dir / "02_indoor_one_portrait.docx"
        meta2 = export_sample(session, runtime, profile.id, [o2], p2)
        samples.append(
            {
                "file": p2.name,
                "records": 1,
                "photos": 1,
                "group_sizes": [1],
                "titles": ["长园所名称示例幼儿园游戏观察记录（室内）"],
                "min_pages": 1,
                "aspects": [[600, 900]],
                "caption": "不得打印的照片说明",
                **meta2,
            }
        )

        # 03: two mixed-orientation photos, outdoor.
        o3 = create_record(
            session,
            runtime,
            profile.id,
            record_type="outdoor",
            payload=full_payload(
                "outdoor", "2026-09-17", "小刚", "幼儿在户外运动区合作搬运器械。"
            ),
            photos=[(1200, 600, (30, 160, 30)), (600, 1200, (30, 30, 200))],
            caption="不得打印的照片说明",
        )
        p3 = output_dir / "03_outdoor_two_mixed.docx"
        meta3 = export_sample(session, runtime, profile.id, [o3], p3)
        samples.append(
            {
                "file": p3.name,
                "records": 1,
                "photos": 2,
                "group_sizes": [2],
                "titles": ["长园所名称示例幼儿园游戏观察记录（户外）"],
                "min_pages": 1,
                "aspects": [[1200, 600], [600, 1200]],
                "caption": "不得打印的照片说明",
                **meta3,
            }
        )

        # 04: three records in explicit mixed order (outdoor, public, indoor).
        o4a = create_record(
            session,
            runtime,
            profile.id,
            record_type="outdoor",
            payload=full_payload(
                "outdoor", "2026-09-18", "小美", "幼儿在户外观察蚂蚁搬家。"
            ),
            photos=[(900, 600, (180, 120, 20))],
            caption="不得打印的照片说明",
        )
        o4b = create_record(
            session,
            runtime,
            profile.id,
            record_type="public",
            payload=full_payload(
                "public", "2026-09-19", "小华", "幼儿在公共建构区协商搭建。"
            ),
            photos=[(600, 900, (120, 20, 180))],
            caption="不得打印的照片说明",
        )
        o4c = create_record(
            session,
            runtime,
            profile.id,
            record_type="indoor",
            payload=full_payload(
                "indoor", "2026-09-20", "小乐", "幼儿在室内美工区合作制作海报。"
            ),
            photos=[(1000, 700, (20, 160, 160))],
            caption="不得打印的照片说明",
        )
        p4 = output_dir / "04_mixed_three.docx"
        meta4 = export_sample(
            session, runtime, profile.id, [o4a, o4b, o4c], p4
        )
        samples.append(
            {
                "file": p4.name,
                "records": 3,
                "photos": 3,
                "group_sizes": [1, 1, 1],
                "titles": [
                    "长园所名称示例幼儿园游戏观察记录（户外）",
                    "长园所名称示例幼儿园游戏观察记录（公共）",
                    "长园所名称示例幼儿园游戏观察记录（室内）",
                ],
                "min_pages": 3,
                "aspects": [[900, 600], [600, 900], [1000, 700]],
                "caption": "不得打印的照片说明",
                **meta4,
            }
        )

        # 05: long school name/text and three photos (groups 2 + 1).
        long_school = "长园所名称示例幼儿园" + "（超长园所名称）" * 4
        o5 = create_record(
            session,
            runtime,
            profile.id,
            record_type="public",
            payload=full_payload(
                "public",
                "2026-09-21",
                "小安",
                ("这是一段用于验证自然分页的长观察正文。" * 80),
                school=long_school,
            ),
            photos=[
                (1400, 500, (200, 80, 80)),
                (500, 1400, (80, 200, 80)),
                (900, 900, (80, 80, 200)),
            ],
            caption="不得打印的照片说明",
        )
        p5 = output_dir / "05_long_text_three_photos.docx"
        meta5 = export_sample(session, runtime, profile.id, [o5], p5)
        samples.append(
            {
                "file": p5.name,
                "records": 1,
                "photos": 3,
                "group_sizes": [2, 1],
                "titles": [f"{long_school}游戏观察记录（公共）"],
                "min_pages": 2,
                "aspects": [[1400, 500], [500, 1400], [900, 900]],
                "caption": "不得打印的照片说明",
                **meta5,
            }
        )

        # 06: five photos (groups 2 + 2 + 1), public.
        o6 = create_record(
            session,
            runtime,
            profile.id,
            record_type="public",
            payload=full_payload(
                "public", "2026-09-22", "小星", "幼儿连续尝试不同的搭建方案。"
            ),
            photos=[
                (1200, 600, (220, 40, 40)),
                (600, 1200, (40, 220, 40)),
                (1000, 700, (40, 40, 220)),
                (700, 1000, (220, 220, 40)),
                (800, 800, (40, 220, 220)),
            ],
            caption="不得打印的照片说明",
        )
        p6 = output_dir / "06_five_photos.docx"
        meta6 = export_sample(session, runtime, profile.id, [o6], p6)
        samples.append(
            {
                "file": p6.name,
                "records": 1,
                "photos": 5,
                "group_sizes": [2, 2, 1],
                "titles": ["长园所名称示例幼儿园游戏观察记录（公共）"],
                "min_pages": 2,
                "aspects": [
                    [1200, 600],
                    [600, 1200],
                    [1000, 700],
                    [700, 1000],
                    [800, 800],
                ],
                "caption": "不得打印的照片说明",
                **meta6,
            }
        )

        # 07: missing facts and no date; body text makes it non-empty.
        missing_payload = {
            "record_type": "public",
            "observation_date": None,
            "observation_process": "只有观察记录正文，其他栏目留空。",
        }
        o7 = create_record(
            session,
            runtime,
            profile.id,
            record_type="public",
            payload=missing_payload,
            photos=[],
            observation_date=None,
        )
        p7 = output_dir / "07_missing_no_date.docx"
        meta7 = export_sample(session, runtime, profile.id, [o7], p7)
        samples.append(
            {
                "file": p7.name,
                "records": 1,
                "photos": 0,
                "group_sizes": [],
                "titles": ["长园所名称示例幼儿园游戏观察记录（公共）"],
                "min_pages": 1,
                "aspects": [],
                "caption": None,
                **meta7,
            }
        )

        expected = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "samples": samples,
        }
        (output_dir / "expected.json").write_text(
            json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"output_dir": str(output_dir), "samples": len(samples)}, ensure_ascii=False))
        if args.word:
            return inspect_in_word(output_dir, output_dir / "expected.json")
        return 0
    finally:
        session.close()
        runtime.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
