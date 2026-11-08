"""Pure weekly input projection/dependency/facts tests."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from app.local import weekly_ai_contracts as contracts
from app.local import weekly_ai_inputs as inputs
from app.local import weekly_plan_content as w
from tests.local.weekly_ai_fake_transport import (
    make_raw,
    make_snapshot,
    selected_content,
    selector,
    source_candidate,
)


def _adoption(content: dict, projection, *, candidate_value: dict, **overrides) -> dict:
    meta = {
        "candidate_id": "candidate-1",
        "candidate_hash": contracts.candidate_hash(candidate_value),
        "input_id": "input-1",
        "execution_id": "execution-1",
        "contract_version": 1,
        "dependency_hash": projection.dependency_hash,
        "adopter_profile_id": "profile-1",
        "adopted_draft_id": "draft-2",
        "adopted_draft_version": 2,
        "adopted_at": "2026-11-03T00:00:00+00:00",
    }
    meta.update(overrides)
    return meta


def _basis(projection) -> dict:
    business = inputs.build_business_dependency_view(projection.dependencies)
    return {
        key: business[key]
        for key in (
            "schema_version",
            "target",
            "grade",
            "theme",
            "manual_text",
            "daily_sources",
            "selected",
            "config",
            "calendar",
        )
    }


def _adopt_games_ai(snapshot: dict, content: dict) -> tuple[dict, dict]:
    raw = make_raw(snapshot, content)
    projection = inputs.project_weekly_input("weekly_games_select", raw, content)
    candidate = contracts.parse_games_candidate(
        json.dumps(
            {
                "outdoor_game_slots": {
                    "collective_1": {"kind": "source", "source_handle": "m1"},
                    "collective_2": {
                        "kind": "ai_supplement",
                        "name": "新游戏",
                        "shared_objectives": "目标",
                        "guidance_points": "指导",
                        "focus_guidance": "重点",
                        "basis_handles": ["c1"],
                    },
                    "free_choice_1": None,
                },
                "focus_area": {"kind": "source", "source_handle": "p1"},
            },
            ensure_ascii=False,
        ),
        server_manifest=projection.server_manifest,
    )
    adopted = w.apply_weekly_ai_adoption(
        content,
        target="games",
        candidate_value=candidate,
        adoption=_adoption(content, projection, candidate_value=candidate),
        basis=_basis(projection),
        ai_item_ids={"collective_2": "ai-item-1"},
    )
    return adopted, make_raw(snapshot, adopted)


def _adopt_column(snapshot: dict, content: dict, field: str, text: str) -> tuple[dict, dict]:
    raw = make_raw(snapshot, content)
    task = contracts.COLUMN_TASK[field]
    projection = inputs.project_weekly_input(task, raw, content)
    candidate = contracts.parse_column_candidate(
        json.dumps({"text": text}, ensure_ascii=False), task_type=task
    )
    adopted = w.apply_weekly_ai_adoption(
        content,
        target=field,
        candidate_value=candidate,
        adoption=_adoption(content, projection, candidate_value=candidate),
        basis=_basis(projection),
    )
    return adopted, make_raw(snapshot, adopted)


def _adopt_materials(snapshot: dict, content: dict, items: list[dict] | None = None) -> tuple[dict, dict]:
    raw = make_raw(snapshot, content)
    projection = inputs.project_weekly_input("weekly_materials_generate", raw, content)
    if items is None:
        handle = sorted(
            key
            for key, entry in projection.server_manifest["handles"].items()
            if entry["kind"] in ("morning_game", "post_group_game")
        )[0]
        quote = projection.server_manifest["handles"][handle]["name"]
        items = [
            {
                "text": "彩纸",
                "origin": "extracted",
                "evidence_refs": [
                    {
                        "source_handle": handle,
                        "field_path": "name",
                        "start": 0,
                        "end": len(quote),
                        "quote": quote,
                    }
                ],
            }
        ]
    candidate = {"items": items}
    adopted = w.apply_weekly_ai_adoption(
        content,
        target="materials",
        candidate_value=candidate,
        adoption=_adoption(content, projection, candidate_value=candidate),
        basis=_basis(projection),
        server_manifest=projection.server_manifest,
    )
    return adopted, make_raw(snapshot, adopted)


def test_raw_manifest_round_trip_and_exact_keys():
    snapshot = make_snapshot()
    content = w.new_content(snapshot)
    raw = make_raw(snapshot, content)
    validated = inputs.validate_raw_manifest(raw)
    assert validated["schema_version"] == 1
    assert validated["header"]["grade"] == "small"
    assert len(validated["days"]) == 7
    assert len(validated["calendar_window"]["days"]) == 21
    assert validated == raw
    assert validated is not raw

    for mutate in (
        lambda value: value.update({"extra": 1}),
        lambda value: value["calendar_window"].update({"days": value["calendar_window"]["days"][:-1]}),
        lambda value: value["days"][0].update({"day_state": "holiday"}),
        lambda value: value["days"][0].update({"source_state": "none_required"}),
        lambda value: value["game_config"]["locations"][0].update({"occurrence": 2}),
        lambda value: value["calendar_window"]["days"][0].update({"holiday_names": ["x", "x"]}),
    ):
        broken = copy.deepcopy(raw)
        mutate(broken)
        with pytest.raises(contracts.WeeklyAIContractError):
            inputs.validate_raw_manifest(broken)


def test_calendar_keeps_unknown_coverage_and_real_holiday_names_on_teaching_day():
    snapshot = make_snapshot()
    content = w.new_content(snapshot)
    raw = make_raw(snapshot, content)
    # 2026-09-07 is index 7 in the anchor-7 window.
    raw["calendar_window"]["days"][7]["holiday_names"] = ["中秋节"]
    raw["calendar_window"]["days"][7]["day_state"] = "teaching"
    raw["calendar_window"]["days"][0]["coverage"] = "unknown"
    raw["calendar_window"]["days"][8]["coverage"] = "unknown"
    validated = inputs.validate_raw_manifest(raw)
    assert validated["calendar_window"]["days"][7]["holiday_names"] == ["中秋节"]
    assert validated["calendar_window"]["days"][8]["coverage"] == "unknown"
    # Outside-term status never silently upgrades unknown holiday coverage.
    assert validated["calendar_window"]["days"][0]["coverage"] == "unknown"


def test_all_six_payloads_follow_task_whitelists_and_handles():
    snapshot, content = selected_content()
    raw = make_raw(snapshot, content)
    snapshots = {
        task: inputs.project_weekly_input(task, raw, content) for task in inputs.TASK_TARGETS
    }
    games = snapshots["weekly_games_select"]
    assert set(games.payload) == {"schema_version", "task_type", "grade", "weekly_context", "days", "config"}
    assert all("theme" not in day for day in games.payload["days"])
    assert set(games.server_manifest["handles"]) == {"c1", "m1", "m2", "m3", "m4", "p1", "p2"}

    focus = snapshots["weekly_key_week_focus"]
    assert set(focus.payload) == {
        "schema_version",
        "task_type",
        "grade",
        "weekly_context",
        "theme",
        "days",
        "teacher_text",
    }
    assert set(focus.payload["days"][0]) == {"date", "source", "teacher_entered"}
    assert focus.server_manifest["handles"] == {}

    environment = snapshots["weekly_environment_setup"]
    assert set(environment.payload) == {
        "schema_version",
        "task_type",
        "grade",
        "weekly_context",
        "theme",
        "selection",
        "config",
        "teacher_text",
    }
    assert environment.payload["selection"]["focus_area"]["source_handle"] == "p1"

    habit = snapshots["weekly_habit_culture"]
    assert set(habit.payload) == {
        "schema_version",
        "task_type",
        "grade",
        "weekly_context",
        "theme",
        "days",
        "teacher_text",
    }
    assert set(habit.payload["days"][0]) == {
        "date",
        "morning_talk_topic",
        "morning_groups",
        "post_support",
    }
    for day in habit.payload["days"]:
        assert all(set(item) == {"guidance_points", "focus_guidance"} for item in day["morning_groups"])
        assert all(set(item) == {"support_strategy"} for item in day["post_support"])
        assert "group_kind" not in json.dumps(day, ensure_ascii=False)
        assert "shared_objectives" not in day["morning_groups"][0]
        assert "context_kind" not in day["post_support"][0]
        assert "area" not in day["post_support"][0]
    assert "group_activity_process" not in json.dumps(habit.payload, ensure_ascii=False)

    home = snapshots["weekly_home_cooperation"]
    assert set(home.payload) == {
        "schema_version",
        "task_type",
        "grade",
        "weekly_context",
        "theme",
        "group_activities",
        "teacher_entered",
        "calendar",
        "teacher_text",
    }
    assert all(set(item) == {"date", "theme", "objectives"} for item in home.payload["group_activities"])
    assert "活动过程" not in json.dumps(home.payload, ensure_ascii=False)

    materials = snapshots["weekly_materials_generate"]
    assert set(materials.payload) == {"schema_version", "task_type", "grade", "weekly_context", "selection", "config"}
    assert "theme" not in materials.payload
    assert materials.payload["selection"]["focus_area"]["source_handle"] == "p1"

    for projection in snapshots.values():
        context = projection.payload["weekly_context"]
        assert context["stage"] == "kindergarten"
        assert context["stage_label"] == "幼儿园"
        assert context["grade"] == "small"
        assert context["grade_label"] == "小班"
        assert context["term_start"] == "2026-09-01"
        assert context["term_end"] == "2026-09-30"
        assert context["week_number"] == 2
        assert context["week_start"] == "2026-09-07"
        assert context["week_end"] == "2026-09-13"
        assert "幼儿园" in context["age_guidance"]
        assert "年龄" in context["age_guidance"]

    for projection in snapshots.values():
        assert projection.as_row_kwargs().keys() == {
            "payload_json",
            "dependencies_json",
            "dependency_hash",
            "target_hashes_json",
        }
        text = json.dumps(projection.payload, ensure_ascii=False)
        assert "测试园" not in text
        assert "张老师" not in text
        for handle in projection.server_manifest["handles"]:
            assert contracts.HANDLE_RE.fullmatch(handle)


def test_target_projection_and_hash_cover_current_values():
    snapshot, content = selected_content()
    games = inputs.target_projection(content, "games")
    assert games["schema_version"] == 1
    assert games["adoption"] is None
    assert games["value"]["outdoor_game_slots"]["collective_1"]["name"] == "跳圈圈"
    assert inputs.target_hash(content, "games") == hashlib.sha256(
        w.canonical_json(games).encode("utf-8")
    ).hexdigest()

    column = inputs.target_projection(content, "key_week_focus")
    assert column["value"] == {"text": ""}
    materials = inputs.target_projection(content, "materials")
    assert materials["value"] == {"materials": None}
    for bad in ("theme", "weekly_columns", "unknown"):
        with pytest.raises(contracts.WeeklyAIContractError):
            inputs.target_projection(content, bad)


def test_dependency_hash_ignores_audit_keys_and_unrelated_config_revision():
    snapshot, content = selected_content()
    raw = make_raw(snapshot, content)
    first = inputs.project_weekly_input("weekly_games_select", raw, content)
    same = copy.deepcopy(first.dependencies)
    same["_batch_snapshot_hash"] = "c" * 64
    assert inputs.dependency_hash(first.dependencies) == inputs.dependency_hash(same)
    assert "_server_manifest" not in inputs.build_business_dependency_view(first.dependencies)
    assert inputs.server_manifest_from_dependencies(same) == first.server_manifest

    bumped = make_raw(snapshot, content, revision_id="rev-9", revision_no=9)
    second = inputs.project_weekly_input("weekly_games_select", bumped, content)
    assert second.dependency_hash == first.dependency_hash

    changed = make_raw(snapshot, content, guidance="新配置指导")
    third = inputs.project_weekly_input("weekly_games_select", changed, content)
    assert third.dependency_hash != first.dependency_hash


def test_per_task_dependencies_do_not_cross_leak_theme_or_other_columns():
    snapshot, content = selected_content()
    raw = make_raw(snapshot, content)
    themed = w.apply_patch(content, {"theme": "新主题"}, snapshot)
    raw_themed = make_raw(snapshot, themed)
    before = inputs.project_weekly_input("weekly_games_select", raw, content)
    after = inputs.project_weekly_input("weekly_games_select", raw_themed, themed)
    assert before.dependency_hash == after.dependency_hash

    focus_before = inputs.project_weekly_input("weekly_key_week_focus", raw, content)
    focus_after = inputs.project_weekly_input("weekly_key_week_focus", raw_themed, themed)
    assert focus_before.dependency_hash != focus_after.dependency_hash

    other = w.apply_patch(content, {"weekly_columns": {"habit_culture": "只改其他栏"}}, snapshot)
    raw_other = make_raw(snapshot, other)
    materials_before = inputs.project_weekly_input("weekly_materials_generate", raw, content)
    materials_after = inputs.project_weekly_input("weekly_materials_generate", raw_other, other)
    assert materials_before.dependency_hash == materials_after.dependency_hash


def test_adopted_column_does_not_self_stale_and_manual_edit_only_sets_flag():
    snapshot = make_snapshot()
    content = w.apply_patch(
        w.new_content(snapshot), {"weekly_columns": {"key_week_focus": "旧要求"}}, snapshot
    )
    adopted, raw = _adopt_column(snapshot, content, "key_week_focus", "生成文本")
    assert adopted["ai_provenance"]["key_week_focus"]["manual_edited"] is False
    assert inputs.build_ai_facts(adopted, raw) == {
        "missing": [],
        "stale_sources": [],
        "warnings": [],
    }
    edited = w.apply_patch(
        adopted, {"weekly_columns": {"key_week_focus": "手工改"}}, snapshot
    )
    raw_edited = make_raw(snapshot, edited)
    assert edited["ai_provenance"]["key_week_focus"]["manual_edited"] is True
    assert inputs.build_ai_facts(edited, raw_edited)["stale_sources"] == []


def test_games_ai_facts_follow_relevant_config_and_source_not_revision_id():
    snapshot, content = selected_content()
    adopted, raw = _adopt_games_ai(snapshot, content)
    assert inputs.build_ai_facts(adopted, raw)["stale_sources"] == []

    unrelated = make_raw(snapshot, adopted, revision_id="rev-99", revision_no=99)
    assert inputs.build_ai_facts(adopted, unrelated)["stale_sources"] == []

    relevant = make_raw(snapshot, adopted, guidance="新配置指导")
    stale = inputs.build_ai_facts(adopted, relevant)["stale_sources"]
    assert [item["field_path"] for item in stale] == ["outdoor_game_slots.collective_2"]
    assert stale[0]["details"]["reason"] == "ai_basis_changed"

    changed_source = make_raw(snapshot, adopted)
    changed_source["days"][0]["source"]["content_hash"] = "d" * 64
    stale = inputs.build_ai_facts(adopted, changed_source)["stale_sources"]
    assert [item["field_path"] for item in stale] == ["outdoor_game_slots.collective_2"]


def test_materials_facts_resolve_current_raw_and_keep_old_basis():
    snapshot, content = selected_content()
    adopted, raw = _adopt_materials(snapshot, content)
    assert adopted["materials"] == "彩纸"
    assert inputs.build_ai_facts(adopted, raw)["stale_sources"] == []
    old_basis = copy.deepcopy(adopted["materials_provenance"]["basis"])

    support_changed = make_raw(snapshot, adopted)
    support_changed["days"][0]["post_group_groups"][0]["support_strategy"] = "新支持"
    stale = inputs.build_ai_facts(adopted, support_changed)["stale_sources"]
    assert [item["field_path"] for item in stale] == ["materials_provenance.basis"]
    assert stale[0]["details"]["reason"] == "materials_basis_changed"
    assert adopted["materials_provenance"]["basis"] == old_basis

    deleted = make_raw(snapshot, adopted)
    deleted["days"][0]["source"] = None
    deleted["days"][0]["source_state"] = "no_plan"
    deleted["days"][0]["morning_groups"] = []
    deleted["days"][0]["post_group_groups"] = []
    stale = inputs.build_ai_facts(adopted, deleted)["stale_sources"]
    assert [item["field_path"] for item in stale] == ["materials_provenance.basis"]
    assert stale[0]["details"]["reason"] == "materials_basis_unresolved"

    # Theme, unrelated columns and unrelated config revisions do not stale materials.
    themed = w.apply_patch(adopted, {"theme": "新主题"}, snapshot)
    themed_raw = make_raw(snapshot, themed, revision_id="rev-99", revision_no=99)
    assert inputs.build_ai_facts(themed, themed_raw)["stale_sources"] == []


def test_materials_game_reselect_and_version_change_stale_but_unrelated_does_not():
    snapshot, content = selected_content()
    games_adopted, _games_raw = _adopt_games_ai(snapshot, content)
    adopted, raw = _adopt_materials(snapshot, games_adopted)
    assert inputs.build_ai_facts(adopted, raw)["stale_sources"] == []

    bumped = make_raw(snapshot, adopted, revision_id="rev-77", revision_no=77)
    assert inputs.build_ai_facts(adopted, bumped)["stale_sources"] == []

    reselected = w.apply_patch(
        adopted,
        {
            "outdoor_game_slots": {
                "free_choice_1": selector(source_candidate(snapshot, "free_choice")),
            }
        },
        snapshot,
    )
    stale = inputs.build_ai_facts(reselected, make_raw(snapshot, reselected))["stale_sources"]
    assert [item["field_path"] for item in stale] == ["materials_provenance.basis"]
    assert stale[0]["details"]["reason"] == "materials_basis_changed"

    version_changed = make_raw(snapshot, adopted)
    version_changed["days"][0]["source"]["content_version"] = 2
    stale = inputs.build_ai_facts(adopted, version_changed)["stale_sources"]
    paths = [item["field_path"] for item in stale]
    assert "materials_provenance.basis" in paths
    material_fact = next(
        item for item in stale if item["field_path"] == "materials_provenance.basis"
    )
    assert material_fact["details"]["reason"] in (
        "materials_basis_changed",
        "materials_basis_unresolved",
    )


def test_schema1_reads_unchanged_and_facts_are_empty():
    snapshot = make_snapshot()
    current = w.new_content(snapshot)
    legacy = {
        key: copy.deepcopy(value)
        for key, value in current.items()
        if key not in ("ai_provenance", "materials_provenance")
    }
    legacy["schema_version"] = 1
    assert w.content_schema_version(legacy) == 1
    assert w.validate_content(legacy, expected_schema=1)["schema_version"] == 1
    assert inputs.build_ai_facts(legacy, make_raw(snapshot, legacy)) == {
        "missing": [],
        "stale_sources": [],
        "warnings": [],
    }
    with pytest.raises(w.WeeklyContentError):
        w.validate_content(legacy, expected_schema=2)


def test_schema1_noop_patch_stays_schema1_and_first_change_promotes():
    snapshot = make_snapshot()
    current = w.new_content(snapshot)
    legacy = {
        key: copy.deepcopy(value)
        for key, value in current.items()
        if key not in ("ai_provenance", "materials_provenance")
    }
    legacy["schema_version"] = 1
    noop = w.apply_patch(legacy, {"theme": legacy["theme"]}, snapshot)
    assert noop == legacy
    changed = w.apply_patch(legacy, {"theme": "新主题"}, snapshot)
    assert changed["schema_version"] == 2
    assert changed["ai_provenance"] == {
        "games": None,
        "key_week_focus": None,
        "environment_setup": None,
        "habit_culture": None,
        "home_cooperation": None,
    }
    assert changed["materials_provenance"] is None
    promoted = w.promote_to_schema2(legacy)
    assert promoted["schema_version"] == 2
    assert promoted["materials"] is None
    with pytest.raises(w.WeeklyContentError):
        w.validate_content({**legacy, "schema_version": 3})


def test_grade_comes_from_week_header_for_all_tasks():
    header = {
        "school_name": "另一园",
        "class_name": "大一班",
        "grade": "large",
        "header_teacher_names": ["李老师"],
        "caregiver_name": None,
    }
    snapshot = make_snapshot(header=header)
    content = w.apply_patch(
        w.new_content(snapshot),
        {
            "focus_area": selector(source_candidate(snapshot, "focus")),
        },
        snapshot,
    )
    raw = make_raw(snapshot, content)
    for task in inputs.TASK_TARGETS:
        projection = inputs.project_weekly_input(task, raw, content)
        assert projection.payload["grade"] == "large"
        assert "李老师" not in json.dumps(projection.payload, ensure_ascii=False)
        assert "另一园" not in json.dumps(projection.payload, ensure_ascii=False)


def test_extra_raw_key_marker_is_not_echoed_in_visible_error():
    marker = "SYNTH_RAW_SECRET_MARKER_9a1"
    snapshot = make_snapshot()
    content = w.new_content(snapshot)
    raw = make_raw(snapshot, content)
    raw[marker] = marker
    with pytest.raises(contracts.WeeklyAIContractError) as exc_info:
        inputs.validate_raw_manifest(raw)
    visible = (
        str(exc_info.value),
        exc_info.value.message,
        exc_info.value.field_path,
        repr(exc_info.value.details),
        repr(vars(exc_info.value)),
    )
    assert all(marker not in item for item in visible)


def test_habit_payload_and_basis_exclude_game_names_objectives_and_places():
    marker = "SYNTH_HABIT_ONLY_MARKER_5e4"
    snapshot = make_snapshot(name=marker, focus_name=marker + "-focus")
    raw = make_raw(snapshot, w.new_content(snapshot))
    raw["days"][0]["morning_groups"][0]["shared_objectives"] = marker
    raw["days"][0]["morning_groups"][0]["games"][0]["name"] = marker
    raw["days"][0]["post_group_groups"][0]["area"] = marker
    raw["days"][0]["post_group_groups"][0]["objectives"] = marker
    raw["days"][0]["post_group_groups"][0]["games"][0]["name"] = marker
    content = w.new_content(snapshot)
    projection = inputs.project_weekly_input("weekly_habit_culture", raw, content)
    payload_text = json.dumps(projection.payload, ensure_ascii=False)
    dependency_text = json.dumps(projection.dependencies, ensure_ascii=False)
    assert marker not in payload_text
    assert marker not in dependency_text
    for day in projection.payload["days"]:
        assert set(day) == {
            "date",
            "morning_talk_topic",
            "morning_groups",
            "post_support",
        }
        for group in day["morning_groups"]:
            assert set(group) == {"guidance_points", "focus_guidance"}
        for support in day["post_support"]:
            assert set(support) == {"support_strategy"}
    for basis_day in projection.dependencies["daily_sources"]:
        for group in basis_day["morning_groups"]:
            assert group["games"] == []
            assert group["shared_objectives"] == ""
            assert group["guidance_points"] == "指导"
            assert group["focus_guidance"] == "重点指导"
        for support in basis_day["post_group_groups"]:
            assert support["games"] == []
            assert support["area"] == ""
            assert support["objectives"] == ""
            assert support["guidance"] == ""
            assert support["support_strategy"] == "支持策略"


# ---------------------------------------------------------------------------
# Stored weekly input validation (§9.10)
# ---------------------------------------------------------------------------

def _roundtrip(task: str, raw: dict, content: dict) -> inputs.ProjectedWeeklyInput:
    projected = inputs.project_weekly_input(task, raw, content)
    validated = inputs.validate_stored_weekly_input(
        task,
        projected.payload,
        projected.dependencies,
        content,
        plan_identity=projected.server_manifest["plan"],
    )
    assert validated.payload == projected.payload
    assert validated.dependencies == projected.dependencies
    assert validated.dependency_hash == projected.dependency_hash
    assert validated.target_hashes == projected.target_hashes
    assert validated.server_manifest == projected.server_manifest
    return projected


def test_validate_stored_input_roundtrip_six_tasks():
    snapshot, content = selected_content()
    raw = make_raw(snapshot, content)
    for task in inputs.TASK_TARGETS:
        _roundtrip(task, raw, content)


def test_validate_stored_input_accepts_legacy_payload_without_weekly_context():
    snapshot, content = selected_content()
    raw = make_raw(snapshot, content)
    for task in inputs.TASK_TARGETS:
        projected = inputs.project_weekly_input(task, raw, content)
        legacy = copy.deepcopy(projected.payload)
        legacy.pop("weekly_context")
        validated = inputs.validate_stored_weekly_input(
            task,
            legacy,
            projected.dependencies,
            content,
            plan_identity=projected.server_manifest["plan"],
        )
        assert validated.payload == legacy
        assert "weekly_context" not in validated.payload
        assert validated.dependency_hash == projected.dependency_hash
        assert validated.target_hashes == projected.target_hashes

        forged = copy.deepcopy(projected.payload)
        forged["weekly_context"]["term_start"] = "2020-01-01"
        with pytest.raises(contracts.WeeklyAIContractError):
            inputs.validate_stored_weekly_input(
                task,
                forged,
                projected.dependencies,
                content,
                plan_identity=projected.server_manifest["plan"],
            )


def test_validate_stored_input_roundtrip_no_daily_sources():
    snapshot = make_snapshot(source_days={date: False for date in (
        "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10",
        "2026-09-11", "2026-09-12", "2026-09-13",
    )})
    content = w.new_content(snapshot)
    raw = make_raw(snapshot, content)
    for task in (
        "weekly_games_select",
        "weekly_key_week_focus",
        "weekly_habit_culture",
        "weekly_home_cooperation",
    ):
        _roundtrip(task, raw, content)


def test_validate_stored_input_roundtrip_manual_and_ai_selected():
    snapshot, content = selected_content()
    manual = {
        "source_kind": "manual",
        "manual_item_id": None,
        "client_key": "manual-key",
        "name": "手工游戏",
        "shared_objectives": "目标",
        "guidance_points": "指导",
        "focus_guidance": "重点",
    }
    content = w.apply_patch(
        content,
        {"outdoor_game_slots": {"free_choice_1": manual}},
        snapshot,
        manual_ids={"manual-key": "manual-1"},
    )
    raw = make_raw(snapshot, content)
    for task in ("weekly_environment_setup", "weekly_materials_generate"):
        _roundtrip(task, raw, content)

    games_adopted, _games_raw = _adopt_games_ai(snapshot, selected_content()[1])
    for task in ("weekly_environment_setup", "weekly_materials_generate"):
        _roundtrip(task, make_raw(snapshot, games_adopted), games_adopted)


def test_validate_stored_input_roundtrip_newer_raw_source_than_saved_manifest():
    snapshot = make_snapshot()
    content = w.new_content(snapshot)
    newer = make_snapshot(version=2, name="新游戏", context_hash="f" * 64)
    raw = make_raw(newer, content)
    for task in (
        "weekly_games_select",
        "weekly_key_week_focus",
        "weekly_habit_culture",
        "weekly_home_cooperation",
    ):
        _roundtrip(task, raw, content)


def test_validate_stored_input_accepts_audit_source_context_and_batch_hash():
    snapshot, content = selected_content()
    raw = make_raw(snapshot, content)
    projected = inputs.project_weekly_input("weekly_games_select", raw, content)
    deps = copy.deepcopy(projected.dependencies)
    deps["_server_manifest"]["source_context_hash"] = "c" * 64
    deps["_batch_snapshot_hash"] = "d" * 64
    validated = inputs.validate_stored_weekly_input(
        "weekly_games_select",
        projected.payload,
        deps,
        content,
        plan_identity=projected.server_manifest["plan"],
    )
    assert validated.dependencies["_batch_snapshot_hash"] == "d" * 64
    assert validated.server_manifest["source_context_hash"] == "c" * 64
    assert validated.dependency_hash == projected.dependency_hash

    broken = copy.deepcopy(projected.dependencies)
    broken["_batch_snapshot_hash"] = "bad"
    with pytest.raises(contracts.WeeklyAIContractError):
        inputs.validate_stored_weekly_input(
            "weekly_games_select",
            projected.payload,
            broken,
            content,
            plan_identity=projected.server_manifest["plan"],
        )


def _assert_input_rejected(
    task: str,
    payload: object,
    dependencies: object,
    content: dict,
    *,
    plan_identity: dict,
    marker: str = "",
) -> None:
    with pytest.raises(contracts.WeeklyAIContractError) as exc_info:
        inputs.validate_stored_weekly_input(
            task, payload, dependencies, content, plan_identity=plan_identity
        )
    assert exc_info.value.code == "WEEKLY_AI_INPUT_INVALID"
    if marker:
        visible = (
            str(exc_info.value),
            exc_info.value.message,
            exc_info.value.field_path,
            repr(exc_info.value.details),
            repr(vars(exc_info.value)),
        )
        assert all(marker not in item for item in visible)


def test_validate_stored_input_rejects_payload_forgery_and_shape_changes():
    marker = "SYNTH_STORED_PAYLOAD_MARKER_3a9"
    for task in inputs.TASK_TARGETS:
        snapshot, content = selected_content()
        raw = make_raw(snapshot, content)
        projected = inputs.project_weekly_input(task, raw, content)
        plan = projected.server_manifest["plan"]

        _assert_input_rejected(task, {"forged": marker}, projected.dependencies, content, plan_identity=plan, marker=marker)

        extra = copy.deepcopy(projected.payload)
        extra[marker] = marker
        _assert_input_rejected(task, extra, projected.dependencies, content, plan_identity=plan, marker=marker)

        missing = copy.deepcopy(projected.payload)
        missing.pop(next(iter(missing)))
        _assert_input_rejected(task, missing, projected.dependencies, content, plan_identity=plan, marker=marker)

        wrong_task = copy.deepcopy(projected.payload)
        if "task_type" in wrong_task:
            wrong_task["task_type"] = "weekly_other"
        else:
            wrong_task["schema_version"] = 2
        _assert_input_rejected(task, wrong_task, projected.dependencies, content, plan_identity=plan, marker=marker)


def test_validate_stored_input_rejects_habit_inner_extra_and_text_change():
    marker = "SYNTH_STORED_HABIT_MARKER_8c2"
    snapshot = make_snapshot()
    content = w.new_content(snapshot)
    projected = inputs.project_weekly_input(
        "weekly_habit_culture", make_raw(snapshot, content), content
    )
    plan = projected.server_manifest["plan"]
    nested = copy.deepcopy(projected.payload)
    nested["days"][0]["morning_groups"][0][marker] = marker
    _assert_input_rejected(
        "weekly_habit_culture", nested, projected.dependencies, content,
        plan_identity=plan, marker=marker,
    )
    changed = copy.deepcopy(projected.payload)
    changed["days"][0]["morning_groups"][0]["guidance_points"] = marker
    _assert_input_rejected(
        "weekly_habit_culture", changed, projected.dependencies, content,
        plan_identity=plan, marker=marker,
    )


def test_validate_stored_input_rejects_materials_config_and_games_handle_forgery():
    snapshot, content = selected_content()
    raw = make_raw(snapshot, content)
    materials = inputs.project_weekly_input("weekly_materials_generate", raw, content)
    plan = materials.server_manifest["plan"]
    config = copy.deepcopy(materials.payload)
    config["config"]["locations"] = [
        {"source_handle": "c99", "kind": "area", "name": "伪造", "guidance": None}
    ]
    _assert_input_rejected(
        "weekly_materials_generate", config, materials.dependencies, content,
        plan_identity=plan,
    )

    games = inputs.project_weekly_input("weekly_games_select", raw, content)
    games_plan = games.server_manifest["plan"]
    handles = copy.deepcopy(games.dependencies)
    handles["_server_manifest"]["handles"]["m99"] = copy.deepcopy(
        handles["_server_manifest"]["handles"]["m1"]
    )
    _assert_input_rejected(
        "weekly_games_select", games.payload, handles, content,
        plan_identity=games_plan,
    )

    source_changed = copy.deepcopy(games.dependencies)
    source_changed["_server_manifest"]["handles"]["m1"]["name"] = "伪造源"
    _assert_input_rejected(
        "weekly_games_select", games.payload, source_changed, content,
        plan_identity=games_plan,
    )


def test_validate_stored_input_rejects_plan_manifest_and_dependency_mutations():
    snapshot, content = selected_content()
    raw = make_raw(snapshot, content)
    projected = inputs.project_weekly_input("weekly_games_select", raw, content)
    plan = projected.server_manifest["plan"]

    changed_plan = copy.deepcopy(projected.dependencies)
    changed_plan["_server_manifest"]["plan"]["draft_version"] += 1
    _assert_input_rejected(
        "weekly_games_select", projected.payload, changed_plan, content,
        plan_identity=plan,
    )
    extra_plan = dict(plan)
    extra_plan["extra"] = 1
    _assert_input_rejected(
        "weekly_games_select", projected.payload, projected.dependencies, content,
        plan_identity=extra_plan,
    )

    for change in (
        lambda value: value.update({"_unknown": 1}),
        lambda value: value.update({"target": "materials"}),
        lambda value: value.update({"task_type": "weekly_key_week_focus"}),
        lambda value: value.update({"grade": "large"}),
    ):
        dependencies = copy.deepcopy(projected.dependencies)
        change(dependencies)
        _assert_input_rejected(
            "weekly_games_select", projected.payload, dependencies, content,
            plan_identity=plan,
        )


def test_validate_stored_input_rejects_bad_types_and_size():
    snapshot, content = selected_content()
    raw = make_raw(snapshot, content)
    projected = inputs.project_weekly_input("weekly_key_week_focus", raw, content)
    plan = projected.server_manifest["plan"]
    for bad in (None, [], "x"):
        _assert_input_rejected(
            "weekly_key_week_focus", bad, projected.dependencies, content,
            plan_identity=plan,
        )
    big = copy.deepcopy(projected.payload)
    big["theme"] = "x" * (inputs.MAX_PAYLOAD_BYTES + 1)
    _assert_input_rejected(
        "weekly_key_week_focus", big, projected.dependencies, content,
        plan_identity=plan,
    )
    with pytest.raises(contracts.WeeklyAIContractError):
        inputs.validate_stored_weekly_input(
            "weekly_key_week_focus",
            projected.payload,
            projected.dependencies,
            content,
            plan_identity=None,
        )


def test_validate_stored_input_roundtrip_focus_only_and_empty_config():
    snapshot = make_snapshot()
    content = w.apply_patch(
        w.new_content(snapshot),
        {"focus_area": selector(source_candidate(snapshot, "focus"))},
        snapshot,
    )
    raw = make_raw(snapshot, content)
    for task in ("weekly_environment_setup", "weekly_materials_generate"):
        projected = _roundtrip(task, raw, content)
        if task == "weekly_materials_generate":
            assert projected.payload["config"]["locations"] == []


def test_validate_stored_input_rejects_empty_config_scope_guidance_changes():
    snapshot = make_snapshot()
    content = w.apply_patch(
        w.new_content(snapshot),
        {"focus_area": selector(source_candidate(snapshot, "focus"))},
        snapshot,
    )
    raw = make_raw(snapshot, content)
    projected = inputs.project_weekly_input("weekly_materials_generate", raw, content)
    plan = projected.server_manifest["plan"]
    assert projected.payload["config"]["locations"] == []
    assert len(projected.dependencies["config"]) == 1
    entry = projected.dependencies["config"][0]
    assert entry["locations"] == []
    assert entry["game_scope"] == "室内"
    assert entry["guidance"] == "配置说明"

    # This was previously (incorrectly) treated as an audit-only empty config.
    # Scope/guidance are business text and every payload value is now exact.
    for key, value in (
        ("revision_no", 99),
        ("game_scope", "伪造范围"),
        ("guidance", "伪造指导"),
    ):
        broken = copy.deepcopy(projected.payload)
        broken["config"][key] = value
        _assert_input_rejected(
            "weekly_materials_generate", broken, projected.dependencies, content,
            plan_identity=plan,
        )

    no_config = copy.deepcopy(projected.dependencies)
    no_config["config"] = []
    _assert_input_rejected(
        "weekly_materials_generate", projected.payload, no_config, content,
        plan_identity=plan,
    )


def test_config_global_text_participates_in_basis_hash_and_facts():
    snapshot = make_snapshot()
    content = w.apply_patch(
        w.new_content(snapshot),
        {"focus_area": selector(source_candidate(snapshot, "focus"))},
        snapshot,
    )
    raw = make_raw(snapshot, content)
    projected = inputs.project_weekly_input("weekly_materials_generate", raw, content)
    assert projected.dependencies["config"][0]["locations"] == []
    assert projected.payload["config"]["game_scope"] == "室内"
    assert projected.payload["config"]["guidance"] == "配置说明"

    changed = make_raw(snapshot, content)
    changed["game_config"]["game_scope"] = "新范围"
    changed["game_config"]["guidance"] = "新指导"
    changed_projection = inputs.project_weekly_input(
        "weekly_materials_generate", changed, content
    )
    assert changed_projection.dependency_hash != projected.dependency_hash
    _roundtrip("weekly_materials_generate", changed, content)

    revision_only = make_raw(snapshot, content, revision_id="rev-9", revision_no=9)
    revision_projection = inputs.project_weekly_input(
        "weekly_materials_generate", revision_only, content
    )
    assert revision_projection.dependency_hash == projected.dependency_hash

    adopted, _ = _adopt_materials(snapshot, content)
    assert inputs.build_ai_facts(adopted, make_raw(snapshot, adopted))["stale_sources"] == []
    changed_adopted = make_raw(snapshot, adopted)
    changed_adopted["game_config"]["game_scope"] = "新范围"
    changed_adopted["game_config"]["guidance"] = "新指导"
    stale = inputs.build_ai_facts(adopted, changed_adopted)
    assert any(
        item["field_path"] == "materials_provenance.basis"
        for item in stale["stale_sources"]
    )
    revision_adopted = make_raw(snapshot, adopted, revision_id="rev-9", revision_no=9)
    revision_stale = inputs.build_ai_facts(adopted, revision_adopted)
    assert revision_stale["stale_sources"] == []


def test_home_calendar_boundaries_weekend_dedup_and_coverage():
    snapshot = make_snapshot()
    content = w.new_content(snapshot)
    raw = make_raw(snapshot, content)
    days = raw["calendar_window"]["days"]
    days[0]["holiday_names"] = ["边界前"]
    days[-1]["holiday_names"] = ["边界后"]
    days[5]["holiday_names"] = ["同一节日"]
    days[6]["holiday_names"] = ["同一节日"]
    weekend = next(day for day in days if day["date"] == "2026-09-12")
    weekend["day_state"] = "rest"
    weekend["holiday_names"] = []
    uncovered = next(day for day in days if day["date"] == "2026-09-13")
    uncovered["coverage"] = "unknown"

    projection = inputs.project_weekly_input(
        "weekly_home_cooperation", raw, content
    )
    calendar = projection.payload["calendar"]
    assert calendar["window_start"] == "2026-08-31"
    assert calendar["window_end"] == "2026-09-20"
    holidays = {(item["date"], item["name"]) for item in calendar["holidays"]}
    assert ("2026-08-31", "边界前") in holidays
    assert ("2026-09-20", "边界后") in holidays
    assert all(date != "2026-09-12" for date, _name in holidays)
    assert len(holidays) == len(calendar["holidays"])
    assert ("2026-09-05", "同一节日") in holidays
    assert ("2026-09-06", "同一节日") in holidays

    basis_days = {
        item["date"]: item for item in projection.dependencies["calendar"]["days"]
    }
    assert basis_days["2026-09-13"]["coverage"] == "unknown"
    assert basis_days["2026-09-12"]["day_state"] == "rest"

    # ±8 dates are outside the frozen window; a shifted window is rejected.
    shifted = copy.deepcopy(raw)
    shifted["calendar_window"]["start"] = "2026-08-30"
    shifted["calendar_window"]["end"] = "2026-09-21"
    with pytest.raises(contracts.WeeklyAIContractError) as exc_info:
        inputs.validate_raw_manifest(shifted)
    assert exc_info.value.field_path == "calendar_window"


# ---------------------------------------------------------------------------
# #16 ordinary candidate editing, provenance and directed regeneration
# ---------------------------------------------------------------------------

from app.local import weekly_ai_adoption as adoption
from app.local import weekly_ai_service
from app.local.errors import LocalValidationError


def test_edited_column_updates_draft_but_keeps_original_provenance():
    snapshot, content = selected_content()
    raw = make_raw(snapshot, content)
    field = "key_week_focus"
    task = contracts.COLUMN_TASK[field]
    projection = inputs.project_weekly_input(task, raw, content)
    original = contracts.parse_column_candidate(
        json.dumps({"text": "原 AI 文本"}, ensure_ascii=False), task_type=task
    )
    edited = {"text": "老师改后的文本"}
    adopted = w.apply_weekly_ai_adoption(
        content,
        target=field,
        candidate_value=original,
        edited_value=edited,
        adoption=_adoption(content, projection, candidate_value=original),
        basis=_basis(projection),
    )
    assert adopted["weekly_columns"][field] == "老师改后的文本"
    provenance = adopted["ai_provenance"][field]
    assert provenance["adopted_value"] == {"text": "原 AI 文本"}
    assert provenance["manual_edited"] is True
    assert provenance["candidate_id"] == "candidate-1"


def test_edited_games_changes_only_legal_text_and_marks_manual_edited():
    snapshot, content = selected_content()
    raw = make_raw(snapshot, content)
    projection = inputs.project_weekly_input("weekly_games_select", raw, content)
    candidate = contracts.parse_games_candidate(
        json.dumps(
            {
                "outdoor_game_slots": {
                    "collective_1": {"kind": "source", "source_handle": "m1"},
                    "collective_2": {
                        "kind": "ai_supplement",
                        "name": "新游戏",
                        "shared_objectives": "目标",
                        "guidance_points": "指导",
                        "focus_guidance": "重点",
                        "basis_handles": ["c1"],
                    },
                    "free_choice_1": None,
                },
                "focus_area": {"kind": "source", "source_handle": "p1"},
            },
            ensure_ascii=False,
        ),
        server_manifest=projection.server_manifest,
    )
    edited = copy.deepcopy(candidate)
    edited["outdoor_game_slots"]["collective_2"]["name"] = "老师改名"
    adopted = w.apply_weekly_ai_adoption(
        content,
        target="games",
        candidate_value=candidate,
        edited_value=edited,
        adoption=_adoption(content, projection, candidate_value=candidate),
        basis=_basis(projection),
        ai_item_ids={"collective_2": "ai-item-1"},
    )
    assert adopted["outdoor_game_slots"]["collective_2"]["name"] == "老师改名"
    assert adopted["outdoor_game_slots"]["collective_1"] == candidate["outdoor_game_slots"]["collective_1"]
    provenance = adopted["ai_provenance"]["games"]
    assert provenance["adopted_value"]["outdoor_game_slots"]["collective_2"]["name"] == "新游戏"
    assert provenance["manual_edited"] is True


def test_edited_materials_updates_text_but_keeps_original_items_and_edited_flag():
    snapshot, content = selected_content()
    raw = make_raw(snapshot, content)
    projection = inputs.project_weekly_input("weekly_materials_generate", raw, content)
    handle = sorted(
        key
        for key, entry in projection.server_manifest["handles"].items()
        if entry["kind"] in ("morning_game", "post_group_game")
    )[0]
    quote = projection.server_manifest["handles"][handle]["name"]
    original = {
        "items": [
            {
                "text": "原材料",
                "origin": "extracted",
                "evidence_refs": [
                    {
                        "source_handle": handle,
                        "field_path": "name",
                        "start": 0,
                        "end": len(quote),
                        "quote": quote,
                    }
                ],
            }
        ]
    }
    edited = copy.deepcopy(original)
    edited["items"][0]["text"] = "老师改后的材料"
    adopted = w.apply_weekly_ai_adoption(
        content,
        target="materials",
        candidate_value=original,
        edited_value=edited,
        adoption=_adoption(content, projection, candidate_value=original),
        basis=_basis(projection),
        server_manifest=projection.server_manifest,
    )
    assert adopted["materials"] == "老师改后的材料"
    provenance = adopted["materials_provenance"]
    assert provenance["items"][0]["text"] == "原材料"
    assert provenance["original_text"] == "原材料"
    assert provenance["edited"] is True


def test_candidate_edit_rejects_structure_and_source_fields():
    with pytest.raises(LocalValidationError):
        adoption._apply_candidate_edit(
            "games",
            {
                "outdoor_game_slots": {
                    "collective_1": {"name": "原名"},
                    "collective_2": None,
                    "free_choice_1": None,
                },
                "focus_area": None,
            },
            {"outdoor_game_slots": {"collective_1": {"source_handle": "m1"}}},
        )
    with pytest.raises(LocalValidationError):
        adoption._apply_candidate_edit(
            "key_week_focus", {"text": "原文本"}, {"text": "改", "extra": "x"}
        )
    with pytest.raises(LocalValidationError):
        adoption._apply_candidate_edit(
            "materials",
            {"items": [{"text": "原文", "origin": "suggested", "evidence_refs": []}]},
            {"items": [{"text": "改", "origin": "extracted"}]},
        )


def test_weekly_create_identity_omits_absent_fields_and_keeps_old_receipts():
    old, base, instruction = weekly_ai_service.weekly_create_identity(
        plan_id="plan-1",
        expected_draft_version=3,
        operation_kind=weekly_ai_service.GAMES,
        targets=["games"],
    )
    assert base is None and instruction is None
    assert "base_candidate_id" not in old
    assert "revision_instruction" not in old
    legacy = {
        "weekly_plan_id": "plan-1",
        "expected_draft_version": 3,
        "operation_kind": weekly_ai_service.GAMES,
        "selected_fields": ["games"],
    }
    assert weekly_ai_service._fingerprint(
        weekly_ai_service.GAMES, old
    ) == weekly_ai_service._fingerprint(weekly_ai_service.GAMES, legacy)
    new, base, instruction = weekly_ai_service.weekly_create_identity(
        plan_id="plan-1",
        expected_draft_version=3,
        operation_kind=weekly_ai_service.GAMES,
        targets=["games"],
        base_candidate_id="  candidate-1  ",
        revision_instruction="  请更简洁  ",
    )
    assert base == "candidate-1"
    assert instruction == "请更简洁"
    assert new["base_candidate_id"] == "candidate-1"
    assert new["revision_instruction"] == "请更简洁"
    with pytest.raises(LocalValidationError):
        weekly_ai_service.weekly_create_identity(
            plan_id="plan-1",
            expected_draft_version=3,
            operation_kind=weekly_ai_service.GAMES,
            targets=["games"],
            revision_instruction="只给指令",
        )


def test_projection_with_base_and_instruction_keeps_business_hash():
    snapshot, content = selected_content()
    raw = make_raw(snapshot, content)
    normal = inputs.project_weekly_input("weekly_key_week_focus", raw, content)
    directed = inputs.project_weekly_input(
        "weekly_key_week_focus",
        raw,
        content,
        base_candidate={"text": "原建议"},
        revision_instruction="请更简洁",
    )
    assert directed.payload["base_candidate"] == {"text": "原建议"}
    assert directed.payload["revision_instruction"] == "请更简洁"
    assert directed.dependencies == normal.dependencies
    assert directed.dependency_hash == normal.dependency_hash
    validated = inputs.validate_stored_weekly_input(
        "weekly_key_week_focus",
        directed.payload,
        directed.dependencies,
        content,
        plan_identity=directed.server_manifest["plan"],
    )
    assert validated.payload == directed.payload
    assert validated.dependency_hash == directed.dependency_hash


def test_preview_selection_accepts_exact_edit_patch_and_rejects_duplicates():
    selected, edits = adoption._selections(
        [
            {
                "candidate_id": "c1",
                "target": "games",
                "edit": {"focus_area": {"name": "老师改后的重点"}},
            }
        ]
    )
    assert selected == [{"candidate_id": "c1", "target": "games"}]
    assert edits == {"c1": {"focus_area": {"name": "老师改后的重点"}}}
    with pytest.raises(LocalValidationError):
        adoption._selections(
            [
                {"candidate_id": "c1", "target": "games"},
                {"candidate_id": "c1", "target": "key_week_focus"},
            ]
        )
    with pytest.raises(LocalValidationError):
        adoption._selections(
            [{"candidate_id": "c1", "target": "games", "extra": "x"}]
        )


def test_weekly_preview_schema_accepts_only_the_weekly_edit_field():
    from app.local.schemas import WeeklyAIAdoptionPreviewIn

    value = WeeklyAIAdoptionPreviewIn(
        expected_draft_version=8,
        selections=[
            {
                "candidate_id": "c1",
                "target": "games",
                "edit": {"focus_area": {"name": "老师改后的重点"}},
            }
        ],
    )
    assert value.selections[0].edit == {"focus_area": {"name": "老师改后的重点"}}
    with pytest.raises(Exception):
        WeeklyAIAdoptionPreviewIn(
            expected_draft_version=8,
            selections=[{"candidate_id": "c1", "target": "games", "unknown": "x"}],
        )


def test_base_candidate_validation_rejects_extra_and_oversize_fields():
    with pytest.raises(contracts.WeeklyAIContractError):
        inputs.validate_base_candidate(
            "weekly_key_week_focus", {"text": "原建议", "profile_id": "private"}
        )
    with pytest.raises(contracts.WeeklyAIContractError):
        inputs.validate_base_candidate(
            "weekly_key_week_focus", {"text": ""}
        )
    with pytest.raises(contracts.WeeklyAIContractError):
        inputs.validate_base_candidate(
            "weekly_materials_generate",
            {
                "items": [
                    {"text": "x" * (contracts.MAX_MATERIAL_ITEM_TEXT + 1), "origin": "suggested"}
                ]
            },
        )
    inputs.validate_base_candidate(
        "weekly_key_week_focus", {"text": "合法原建议"}
    )
    inputs.validate_base_candidate(
        "weekly_materials_generate",
        {"items": [{"text": "合法材料", "origin": "extracted"}]},
    )


def test_stored_directed_input_rejects_forged_base_candidate_fields():
    snapshot, content = selected_content()
    raw = make_raw(snapshot, content)
    directed = inputs.project_weekly_input(
        "weekly_key_week_focus",
        raw,
        content,
        base_candidate={"text": "合法原建议"},
        revision_instruction="请更简洁",
    )
    forged = copy.deepcopy(directed.payload)
    forged["base_candidate"] = {
        "text": "SYNTHETIC_FORGED_PRIVATE_VALUE",
        "profile_id": "private-profile",
    }
    with pytest.raises(contracts.WeeklyAIContractError):
        inputs.validate_stored_weekly_input(
            "weekly_key_week_focus",
            forged,
            directed.dependencies,
            content,
            plan_identity=directed.server_manifest["plan"],
        )


def test_minimal_candidate_value_hides_local_source_identity():
    games = {
        "outdoor_game_slots": {
            "collective_1": {
                "source_kind": "morning_game",
                "source_handle": "m1",
                "name": "原游戏",
                "shared_objectives": "目标",
                "guidance_points": "指导",
                "focus_guidance": "重点",
            },
            "collective_2": None,
            "free_choice_1": None,
        },
        "focus_area": None,
    }
    minimal = inputs.minimal_candidate_value("games", games)
    assert "source_handle" not in json.dumps(minimal, ensure_ascii=False)
    assert minimal["outdoor_game_slots"]["collective_1"]["name"] == "原游戏"
    materials = {
        "items": [
            {
                "text": "材料",
                "origin": "extracted",
                "evidence_refs": [{"source_handle": "m1", "quote": "x"}],
            }
        ]
    }
    material_minimal = inputs.minimal_candidate_value("materials", materials)
    assert material_minimal == {"items": [{"text": "材料", "origin": "extracted"}]}
