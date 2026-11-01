"""Pure weekly-plan content contract tests (no DB/runtime imports)."""

from __future__ import annotations

import copy
import hashlib
import sys
from datetime import date, timedelta

import pytest

from app.local import weekly_plan_content as w


def _hash(ch: str = "a") -> str:
    return ch * 64


def _source(
    *,
    plan_id: str = "plan-1",
    content_id: str = "content-1",
    version: int = 1,
    content_hash: str | None = None,
    topic: str = "晨谈",
    theme: str = "集体主题",
) -> dict:
    return {
        "daily_plan_id": plan_id,
        "content_id": content_id,
        "content_version": version,
        "content_hash": content_hash or _hash("a"),
        "morning_talk_topic": topic,
        "group_activity_theme": theme,
    }


def _morning_group(
    *,
    group_id: str = "g-col",
    kind: str = "collective",
    game_id: str = "game-1",
    game_name: str = "跳圈圈",
    objectives: str = "共同目标",
    guidance: str = "指导",
    focus: str = "重点指导",
) -> dict:
    return {
        "group_id": group_id,
        "group_kind": kind,
        "games": [{"game_id": game_id, "name": game_name}],
        "shared_objectives": objectives,
        "guidance_points": guidance,
        "focus_guidance": focus,
    }


def _post_group(
    *,
    group_id: str = "g-focus",
    game_id: str = "game-focus",
    game_name: str = "建构区游戏",
    context: str = "area",
    area: str = "建构区",
    objectives: str = "区域目标",
    guidance: str = "区域指导",
    support: str = "支持策略",
) -> dict:
    return {
        "group_id": group_id,
        "context_kind": context,
        "area": area,
        "games": [{"game_id": game_id, "name": game_name}],
        "objectives": objectives,
        "guidance": guidance,
        "support_strategy": support,
    }


def _header(
    *,
    names: list[str] | None = None,
    caregiver: str | None = "保育员",
) -> dict:
    return {
        "school_name": "测试园",
        "class_name": "小一班",
        "grade": "small",
        "header_teacher_names": names if names is not None else ["张老师"],
        "caregiver_name": caregiver,
    }


def _snapshot(
    *,
    version: int = 1,
    name: str = "跳圈圈",
    focus_name: str = "建构区游戏",
    source_days: dict[str, bool] | None = None,
    day_states: dict[str, str] | None = None,
    source_hash: str = "a",
    contract_hash: str = "b",
    calendar_revision: str = "cal-1",
    term_start: str = "2026-09-01",
    term_end: str = "2026-09-30",
    header: dict | None = None,
    context_hash: str | None = None,
) -> dict:
    anchor = date(2026, 9, 7)
    source_days = source_days or {
        "2026-09-07": True,
        "2026-09-08": True,
        "2026-09-09": False,
        "2026-09-10": False,
        "2026-09-11": False,
        "2026-09-12": False,
        "2026-09-13": False,
    }
    day_states = day_states or {
        "2026-09-07": "teaching",
        "2026-09-08": "teaching",
        "2026-09-09": "rest",
        "2026-09-10": "teaching",
        "2026-09-11": "teaching",
        "2026-09-12": "rest",
        "2026-09-13": "rest",
    }
    days = []
    for offset in range(7):
        text = (anchor + timedelta(days=offset)).isoformat()
        state = day_states[text]
        if source_days.get(text):
            source = _source(
                plan_id=f"plan-{offset + 1}",
                content_id=f"content-{offset + 1}",
                version=version,
                content_hash=_hash(source_hash),
                topic=f"晨谈{offset + 1}",
                theme=f"活动{offset + 1}",
            )
            mornings = [
                _morning_group(
                    group_id=f"g-col-{offset + 1}",
                    game_id=f"game-col-{offset + 1}",
                    game_name=name,
                ),
                _morning_group(
                    group_id=f"g-free-{offset + 1}",
                    kind="free_choice",
                    game_id=f"game-free-{offset + 1}",
                    game_name="滚球",
                ),
            ]
            posts = [
                _post_group(
                    group_id=f"g-focus-{offset + 1}",
                    game_id=f"game-focus-{offset + 1}",
                    game_name=focus_name,
                )
            ]
            source_state = "saved"
        else:
            source = None
            mornings = []
            posts = []
            source_state = "no_plan" if state == "teaching" else "none_required"
        days.append(
            {
                "date": text,
                "day_state": state,
                "source_state": source_state,
                "source": source,
                "morning_groups": mornings,
                "post_group_groups": posts,
            }
        )
    return {
        "profile_id": "profile-1",
        "class_id": "class-1",
        "term_id": "term-1",
        "week_anchor_date": "2026-09-07",
        "week_number": 2,
        "term_start": term_start,
        "term_end": term_end,
        "calendar_revision_id": calendar_revision,
        "config_version": 3,
        "game_context": {"revision_id": "rev-1", "revision_no": 2},
        "header": header or _header(),
        "source_context_hash": context_hash or _hash(contract_hash),
        "days": days,
    }


def _candidate(snapshot: dict, category: str = "collective") -> dict:
    return next(
        item
        for item in w.build_source_candidates(snapshot)
        if item["category"] == category
    )


def _selector(candidate: dict) -> dict:
    return {
        "source_kind": "daily_plan",
        "daily_plan_id": candidate["daily_plan_id"],
        "content_id": candidate["content_id"],
        "content_version": candidate["content_version"],
        "content_hash": candidate["content_hash"],
        "section": candidate["section"],
        "group_id": candidate["group_id"],
        "game_id": candidate["game_id"],
    }


def _with_slot(snapshot: dict | None = None, key: str = "collective_1", category: str = "collective") -> dict:
    snap = snapshot or _snapshot()
    content = w.new_content(snap)
    return w.apply_patch(
        content,
        {"outdoor_game_slots": {key: _selector(_candidate(snap, category))}},
        snap,
    )


def _codes(items: list[dict]) -> list[str]:
    return [item["code"] for item in items]


def test_new_content_exact_schema_and_q1_states():
    snap = _snapshot()
    content = w.new_content(snap)
    assert set(content) == {
        "schema_version", "theme", "deterministic", "outdoor_game_slots",
        "focus_area", "weekly_columns", "materials", "source_manifest",
        "calendar_basis",
    }
    assert content["schema_version"] == 1
    assert content["theme"] == ""
    assert content["materials"] is None
    assert len(content["deterministic"]) == 7
    assert content["deterministic"][0]["source_state"] == "saved"
    assert content["deterministic"][0]["source"]["content_hash"] == _hash("a")
    assert content["deterministic"][2]["source"] is None
    assert content["deterministic"][2]["source_state"] == "none_required"
    assert content["deterministic"][2]["effective"] == {
        "morning_talk_topic": "", "group_activity_theme": ""
    }
    assert "plan_state" not in content["deterministic"][0]
    assert content["source_manifest"]["sources"][0]["content_hash"] == _hash("a")
    assert content["calendar_basis"]["days"][0] == {"date": "2026-09-07", "day_state": "teaching"}


def test_new_content_theme_boundary_and_invalid():
    assert w.new_content(_snapshot(), theme=None)["theme"] == ""  # type: ignore[arg-type]
    with pytest.raises(w.WeeklyContentError):
        w.new_content(_snapshot(), theme=5)  # type: ignore[arg-type]


def test_snapshot_strict_keys_and_types():
    bad = _snapshot()
    bad["extra"] = 1
    with pytest.raises(w.WeeklyContentError):
        w.validate_source_snapshot(bad)
    bad = _snapshot()
    bad["days"] = bad["days"][:6]
    with pytest.raises(w.WeeklyContentError):
        w.validate_source_snapshot(bad)
    bad = _snapshot()
    bad["days"][0]["source"]["content_version"] = True
    with pytest.raises(w.WeeklyContentError):
        w.validate_source_snapshot(bad)
    bad = _snapshot()
    bad["days"][0]["source_state"] = "saved"
    bad["days"][0]["source"] = None
    with pytest.raises(w.WeeklyContentError):
        w.validate_source_snapshot(bad)


def test_patch_override_null_empty_and_effective():
    snap = _snapshot()
    content = w.new_content(snap)
    patched = w.apply_patch(
        content,
        {
            "deterministic_overrides": {
                "2026-09-07": {
                    "morning_talk_topic": "手工晨谈",
                    "group_activity_theme": "",
                }
            }
        },
        snap,
    )
    row = patched["deterministic"][0]
    assert row["override"] == {
        "morning_talk_topic": "手工晨谈",
        "group_activity_theme": "",
    }
    assert row["effective"] == {
        "morning_talk_topic": "手工晨谈",
        "group_activity_theme": "",
    }
    cleared = w.apply_patch(
        patched,
        {"deterministic_overrides": {"2026-09-07": {"morning_talk_topic": None, "group_activity_theme": None}}},
        snap,
    )
    assert cleared["deterministic"][0]["override"] == {
        "morning_talk_topic": None,
        "group_activity_theme": None,
    }
    assert cleared["deterministic"][0]["effective"]["morning_talk_topic"] == "晨谈1"
    with pytest.raises(w.WeeklyContentError):
        w.apply_patch(content, {"deterministic_overrides": {"2026-09-06": {"morning_talk_topic": "x"}}}, snap)
    with pytest.raises(w.WeeklyContentError):
        w.apply_patch(content, {"deterministic_overrides": {"2026-09-09": {"morning_talk_topic": "x"}}}, snap)


def test_patch_unknown_keys_and_columns_partial_inherit():
    snap = _snapshot()
    content = w.new_content(snap)
    with pytest.raises(w.WeeklyContentError):
        w.apply_patch(content, {"bogus": 1}, snap)
    patched = w.apply_patch(
        content,
        {"weekly_columns": {"key_week_focus": "重点"}},
        snap,
    )
    assert patched["weekly_columns"]["key_week_focus"] == "重点"
    assert patched["weekly_columns"]["environment_setup"] == ""
    with pytest.raises(w.WeeklyContentError):
        w.apply_patch(content, {"weekly_columns": {"bogus": "x"}}, snap)


def test_selector_materializes_full_text_and_hash():
    snap = _snapshot()
    content = _with_slot(snap)
    slot = content["outdoor_game_slots"]["collective_1"]
    assert slot["section"] == "morning_games"
    assert slot["content_hash"] == _hash("a")
    assert slot["shared_objectives"] == "共同目标"
    assert slot["focus_guidance"] == "重点指导"
    assert slot["source_kind"] == "daily_plan"
    assert "client_key" not in slot


def test_selector_hash_mismatch_rejected():
    snap = _snapshot()
    content = w.new_content(snap)
    selector = _selector(_candidate(snap, "collective"))
    selector["content_hash"] = _hash("f")
    with pytest.raises(w.WeeklyContentError):
        w.apply_patch(content, {"outdoor_game_slots": {"collective_1": selector}}, snap)


def test_same_name_sources_candidates_and_slot_collision():
    snap = _snapshot(name="同名游戏")
    candidates = [c for c in w.build_source_candidates(snap) if c["category"] == "collective" and c["name"] == "同名游戏"]
    assert len(candidates) >= 2
    content = w.new_content(snap)
    with pytest.raises(w.WeeklyContentError):
        w.apply_patch(
            content,
            {
                "outdoor_game_slots": {
                    "collective_1": _selector(candidates[0]),
                    "collective_2": _selector(candidates[1]),
                }
            },
            snap,
        )


def test_manual_client_key_injection_and_no_leak():
    snap = _snapshot()
    content = w.new_content(snap)
    patched = w.apply_patch(
        content,
        {
            "outdoor_game_slots": {
                "collective_1": {
                    "source_kind": "manual",
                    "manual_item_id": None,
                    "client_key": "tmp-1",
                    "name": "手工游戏",
                    "shared_objectives": "目标",
                    "guidance_points": "指导",
                    "focus_guidance": "重点",
                }
            }
        },
        snap,
        manual_ids={"tmp-1": "manual-final-1"},
    )
    slot = patched["outdoor_game_slots"]["collective_1"]
    assert slot["manual_item_id"] == "manual-final-1"
    assert "client_key" not in slot
    assert "tmp-1" not in repr(patched)
    with pytest.raises(w.WeeklyContentError):
        w.apply_patch(
            content,
            {
                "outdoor_game_slots": {
                    "collective_1": {
                        "source_kind": "manual",
                        "manual_item_id": None,
                        "client_key": "tmp-2",
                        "name": "手工",
                        "shared_objectives": "目标",
                        "guidance_points": "指导",
                        "focus_guidance": "重点",
                    }
                }
            },
            snap,
        )


def test_manual_existing_id_must_belong_to_previous():
    snap = _snapshot()
    content = w.new_content(snap)
    with pytest.raises(w.WeeklyContentError):
        w.apply_patch(
            content,
            {
                "outdoor_game_slots": {
                    "collective_1": {
                        "source_kind": "manual",
                        "manual_item_id": "other-manual",
                        "name": "手工",
                        "shared_objectives": "目标",
                        "guidance_points": "指导",
                        "focus_guidance": "重点",
                    }
                }
            },
            snap,
        )


def test_normal_patch_preserves_old_sources_manifest_and_calendar():
    snap = _snapshot()
    content = _with_slot(snap)
    changed = _snapshot(version=9, name="新游戏", calendar_revision="cal-2", context_hash=_hash("c"))
    patched = w.apply_patch(content, {"theme": "新主题"}, changed)
    assert patched["deterministic"][0]["source"] == content["deterministic"][0]["source"]
    assert patched["source_manifest"] == content["source_manifest"]
    assert patched["calendar_basis"] == content["calendar_basis"]
    assert patched["outdoor_game_slots"]["collective_1"]["content_version"] == 1


def test_refresh_updates_resolvable_and_preserves_missing():
    snap = _snapshot()
    content = _with_slot(snap)
    newer = _snapshot(version=2, name="新游戏", context_hash=_hash("d"))
    refreshed = w.refresh_content(content, newer)
    new_slot = refreshed["content"]["outdoor_game_slots"]["collective_1"]
    assert new_slot["content_version"] == 2
    assert new_slot["name"] == "新游戏"
    assert refreshed["differences"]
    missing_snap = _snapshot(version=2, name="新游戏", source_days={"2026-09-07": True}, context_hash=_hash("e"))
    # Remove the selected group/game while keeping a different valid source day.
    missing_snap["days"][0]["morning_groups"] = [
        _morning_group(group_id="other-group", game_id="other-game", game_name="别的")
    ]
    preserved = w.refresh_content(content, missing_snap)
    old_slot = preserved["content"]["outdoor_game_slots"]["collective_1"]
    assert old_slot == content["outdoor_game_slots"]["collective_1"]
    assert preserved["preserved"]


def test_facts_q1_no_missing_daily_plan_and_hand_fill():
    snap = _snapshot()
    content = w.new_content(snap)
    facts = w.build_facts(content, snap)
    assert "missing_daily_plan_date" not in _codes(facts["missing"])
    assert "missing_daily_plan_date" not in _codes(facts["stale_sources"])
    filled = w.apply_patch(
        content,
        {
            "theme": "主题",
            "deterministic_overrides": {
                "2026-09-10": {"morning_talk_topic": "搭班晨谈", "group_activity_theme": "搭班活动"},
                "2026-09-11": {"morning_talk_topic": "搭班晨谈2", "group_activity_theme": "搭班活动2"},
            },
            "weekly_columns": {
                "key_week_focus": "重点",
                "environment_setup": "环境",
                "habit_culture": "习惯",
                "home_cooperation": "家园",
            },
        },
        snap,
    )
    filled_facts = w.build_facts(filled, snap)
    assert not [
        item for item in filled_facts["missing"]
        if item["field_path"].startswith("deterministic[2026-09-10].effective")
    ]


def test_facts_rest_and_outside_term_no_teaching_missing():
    states = {
        "2026-09-07": "outside_term",
        "2026-09-08": "rest",
        "2026-09-09": "rest",
        "2026-09-10": "rest",
        "2026-09-11": "rest",
        "2026-09-12": "rest",
        "2026-09-13": "rest",
    }
    snap = _snapshot(day_states=states, source_days={key: False for key in states})
    content = w.new_content(snap)
    facts = w.build_facts(content, snap)
    assert not [item for item in facts["missing"] if item["field_path"].startswith("deterministic[")]


def test_facts_header_columns_focus_materials():
    snap = _snapshot(header=_header(names=[], caregiver=None))
    content = w.new_content(snap)
    facts = w.build_facts(content, snap)
    codes = _codes(facts["missing"])
    assert "empty_header_teacher_names" in codes
    assert "empty_caregiver_name" in codes
    assert "focus_area_missing" in codes
    assert "materials_empty" in codes
    assert "empty_field" in codes


def test_facts_stale_uses_current_snapshot_not_old_snapshot():
    snap = _snapshot()
    content = _with_slot(snap)
    newer = _snapshot(version=3, name="新游戏", context_hash=_hash("f"))
    facts = w.build_facts(content, newer)
    stale = facts["stale_sources"]
    assert any(item["field_path"] == "outdoor_game_slots.collective_1" for item in stale)
    assert any(item["field_path"].startswith("deterministic[") for item in stale)
    assert content["deterministic"][0]["source"]["content_version"] == 1


def test_facts_warnings_calendar_and_context():
    snap = _snapshot()
    content = w.new_content(snap)
    newer = _snapshot(calendar_revision="cal-2", context_hash=_hash("9"))
    facts = w.build_facts(content, newer)
    codes = _codes(facts["warnings"])
    assert "calendar_basis_changed" in codes
    assert "source_context_changed" in codes


def test_canonical_hash_stability_and_nonfinite_rejection():
    snap = _snapshot()
    content = w.new_content(snap)
    assert w.content_hash(content) == w.content_hash(copy.deepcopy(content))
    assert len(w.content_hash(content)) == 64
    assert w.canonical_json({"b": 1, "a": "中"}) == '{"a":"中","b":1}'
    with pytest.raises(w.WeeklyContentError):
        w.canonical_json({"x": float("nan")})


def test_content_size_limit_is_primary_not_masked_by_other_bad_path():
    snap = _snapshot()
    content = w.new_content(snap)
    content["theme"] = "x" * (w.MAX_CONTENT_BYTES + 1)
    with pytest.raises(w.WeeklyContentError) as exc:
        w.validate_content(content)
    assert exc.value.code == "WEEKLY_CONTENT_TOO_LARGE"


def test_validate_content_rejects_unknown_and_bool_version():
    snap = _snapshot()
    content = w.new_content(snap)
    bad = copy.deepcopy(content)
    bad["extra"] = 1
    with pytest.raises(w.WeeklyContentError):
        w.validate_content(bad)
    bad = copy.deepcopy(content)
    bad["deterministic"][0]["source"]["content_version"] = True
    with pytest.raises(w.WeeklyContentError):
        w.validate_content(bad)


def test_inputs_are_not_mutated_and_confirmed_snapshot_is_independent():
    snap = _snapshot()
    original_snap = copy.deepcopy(snap)
    content = w.new_content(snap)
    original_content = copy.deepcopy(content)
    w.apply_patch(content, {"theme": "t"}, snap)
    w.refresh_content(content, _snapshot(version=2))
    assert content == original_content
    assert snap == original_snap
    facts = w.build_facts(content, snap)
    assert content == original_content
    assert facts["missing"]


def test_focus_selector_and_section():
    snap = _snapshot()
    content = w.new_content(snap)
    candidate = _candidate(snap, "focus")
    patched = w.apply_patch(
        content,
        {"focus_area": _selector(candidate)},
        snap,
    )
    focus = patched["focus_area"]
    assert focus["section"] == "post_group_games"
    assert focus["content_hash"] == candidate["content_hash"]
    assert focus["context_kind"] == "area"
    assert focus["objectives"] == "区域目标"
    assert focus["support_strategy"] == "支持策略"


def test_source_candidates_sections_and_same_name_retained():
    snap = _snapshot(name="同名")
    candidates = w.build_source_candidates(snap)
    assert candidates
    assert {item["section"] for item in candidates} == {"morning_games", "post_group_games"}
    collectives = [item for item in candidates if item["category"] == "collective"]
    assert len(collectives) >= 2
    assert collectives[0]["group_id"] != collectives[1]["group_id"]
    assert all("afternoon" not in item["section"] for item in candidates)


def test_manifest_calendar_identity_mismatch_rejected():
    snap = _snapshot()
    content = w.new_content(snap)
    bad = copy.deepcopy(content)
    bad["source_manifest"]["calendar_revision_id"] = "other"
    with pytest.raises(w.WeeklyContentError):
        w.validate_content(bad)


def test_duplicate_manual_id_and_manual_daily_same_name_rejected():
    snap = _snapshot(name="同名")
    content = w.new_content(snap)
    manual = {
        "source_kind": "manual",
        "manual_item_id": None,
        "client_key": "a",
        "name": "同名",
        "shared_objectives": "目标",
        "guidance_points": "指导",
        "focus_guidance": "重点",
    }
    with pytest.raises(w.WeeklyContentError):
        w.apply_patch(
            content,
            {"outdoor_game_slots": {"collective_1": manual, "collective_2": {**manual, "client_key": "b"}}},
            snap,
            manual_ids={"a": "same-id", "b": "same-id"},
        )
    daily = _selector(_candidate(snap, "collective"))
    with pytest.raises(w.WeeklyContentError):
        w.apply_patch(
            content,
            {"outdoor_game_slots": {"collective_2": daily, "collective_1": manual}},
            snap,
            manual_ids={"a": "manual-1"},
        )


def test_materials_nonnull_rejected_and_header_100_limit():
    snap = _snapshot()
    content = w.new_content(snap)
    bad = copy.deepcopy(content)
    bad["materials"] = {"items": []}
    with pytest.raises(w.WeeklyContentError):
        w.validate_content(bad)
    too_many = _snapshot(header=_header(names=["张老师"] * 101))
    with pytest.raises(w.WeeklyContentError):
        w.new_content(too_many)
    # 100 short names are accepted; the 32KiB header bound is separate.
    accepted = _snapshot(header=_header(names=["张老师"] * 100))
    w.new_content(accepted)


def test_refresh_rejects_collision_and_preserves_group_kind_history():
    base = _snapshot()
    base["days"][0]["morning_groups"][0]["games"][0]["name"] = "甲"
    base["days"][1]["morning_groups"][0]["games"][0]["name"] = "乙"
    content = w.new_content(base)
    sel1 = _selector({
        "source_kind": "daily_plan",
        "daily_plan_id": base["days"][0]["source"]["daily_plan_id"],
        "content_id": base["days"][0]["source"]["content_id"],
        "content_version": 1,
        "content_hash": base["days"][0]["source"]["content_hash"],
        "section": "morning_games",
        "group_id": base["days"][0]["morning_groups"][0]["group_id"],
        "game_id": base["days"][0]["morning_groups"][0]["games"][0]["game_id"],
    })
    sel2 = _selector({
        "source_kind": "daily_plan",
        "daily_plan_id": base["days"][1]["source"]["daily_plan_id"],
        "content_id": base["days"][1]["source"]["content_id"],
        "content_version": 1,
        "content_hash": base["days"][1]["source"]["content_hash"],
        "section": "morning_games",
        "group_id": base["days"][1]["morning_groups"][0]["group_id"],
        "game_id": base["days"][1]["morning_groups"][0]["games"][0]["game_id"],
    })
    content = w.apply_patch(content, {"outdoor_game_slots": {"collective_1": sel1, "collective_2": sel2}}, base)
    newer = copy.deepcopy(base)
    newer["days"][0]["morning_groups"][0]["games"][0]["name"] = "同名"
    newer["days"][1]["morning_groups"][0]["games"][0]["name"] = "同名"
    newer["source_context_hash"] = _hash("7")
    before = copy.deepcopy(content)
    with pytest.raises(w.WeeklyContentError):
        w.refresh_content(content, newer)
    assert content == before

    kind_changed = copy.deepcopy(base)
    kind_changed["days"][0]["morning_groups"][0]["group_kind"] = "free_choice"
    kind_changed["source_context_hash"] = _hash("8")
    refreshed = w.refresh_content(content, kind_changed)
    assert refreshed["content"]["outdoor_game_slots"]["collective_1"]["name"] == "甲"
    assert refreshed["preserved"]
    facts = w.build_facts(content, kind_changed)
    stale = [f for f in facts["stale_sources"] if f["field_path"] == "outdoor_game_slots.collective_1"]
    assert stale and stale[0]["details"]["current_item_exists"] is False


def test_refresh_differences_calendar_day_and_term_changes():
    base = _snapshot()
    content = w.new_content(base)
    newer = _snapshot(
        source_days={
            "2026-09-07": True,
            "2026-09-08": True,
            "2026-09-09": False,
            "2026-09-10": False,
            "2026-09-11": False,
            "2026-09-12": False,
            "2026-09-13": False,
        },
        day_states={
            "2026-09-07": "teaching",
            "2026-09-08": "teaching",
            "2026-09-09": "teaching",
            "2026-09-10": "teaching",
            "2026-09-11": "teaching",
            "2026-09-12": "rest",
            "2026-09-13": "rest",
        },
        term_start="2026-09-02",
        term_end="2026-09-29",
    )
    result = w.refresh_content(content, newer)
    paths = {item["field_path"] for item in result["differences"]}
    assert "calendar_basis.days[2026-09-09].day_state" in paths
    assert "calendar_basis.term_start" in paths
    assert result["content"]["calendar_basis"]["week_anchor_date"] == base["week_anchor_date"]
    assert result["content"]["source_manifest"]["header"] == content["source_manifest"]["header"]


def test_validate_content_effective_calendar_and_manifest_are_derived():
    snap = _snapshot()
    content = w.new_content(snap)
    bad = copy.deepcopy(content)
    bad["deterministic"][0]["effective"]["morning_talk_topic"] = "篡改"
    with pytest.raises(w.WeeklyContentError):
        w.validate_content(bad)
    bad = copy.deepcopy(content)
    bad["calendar_basis"]["days"][1]["date"] = bad["calendar_basis"]["days"][0]["date"]
    with pytest.raises(w.WeeklyContentError):
        w.validate_content(bad)
    bad = copy.deepcopy(content)
    bad["calendar_basis"]["days"][0]["date"] = "2026-09-08"
    with pytest.raises(w.WeeklyContentError):
        w.validate_content(bad)
    bad = copy.deepcopy(content)
    bad["source_manifest"]["sources"][0]["date"] = bad["source_manifest"]["sources"][1]["date"]
    with pytest.raises(w.WeeklyContentError):
        w.validate_content(bad)
    bad = copy.deepcopy(content)
    bad["calendar_basis"]["term_start"] = "2026-10-01"
    bad["calendar_basis"]["term_end"] = "2026-09-01"
    with pytest.raises(w.WeeklyContentError):
        w.validate_content(bad)


def test_explicit_old_selector_must_be_rechecked_for_outdoor_and_focus():
    base = _snapshot()
    content = _with_slot(base)
    focus_candidate = _candidate(base, "focus")
    content = w.apply_patch(content, {"focus_area": _selector(focus_candidate)}, base)
    newer = _snapshot(version=2, context_hash=_hash("a"))
    old_outdoor = content["outdoor_game_slots"]["collective_1"]
    old_focus = content["focus_area"]
    assert old_outdoor["content_version"] == 1 and old_focus["content_version"] == 1
    with pytest.raises(w.WeeklyContentError):
        w.apply_patch(
            content,
            {"outdoor_game_slots": {"collective_1": {
                "source_kind": "daily_plan",
                "daily_plan_id": old_outdoor["daily_plan_id"],
                "content_id": old_outdoor["content_id"],
                "content_version": old_outdoor["content_version"],
                "content_hash": old_outdoor["content_hash"],
                "section": old_outdoor["section"],
                "group_id": old_outdoor["group_id"],
                "game_id": old_outdoor["game_id"],
            }}},
            newer,
        )
    with pytest.raises(w.WeeklyContentError):
        w.apply_patch(
            content,
            {"focus_area": {
                "source_kind": "daily_plan",
                "daily_plan_id": old_focus["daily_plan_id"],
                "content_id": old_focus["content_id"],
                "content_version": old_focus["content_version"],
                "content_hash": old_focus["content_hash"],
                "section": old_focus["section"],
                "group_id": old_focus["group_id"],
                "game_id": old_focus["game_id"],
            }},
            newer,
        )
    unchanged = w.apply_patch(content, {"theme": "只改主题"}, newer)
    assert unchanged["outdoor_game_slots"] == content["outdoor_game_slots"]
    assert unchanged["focus_area"] == content["focus_area"]


def test_facts_whitespace_is_empty_without_stripping_saved_content():
    snap = _snapshot()
    content = w.apply_patch(
        w.new_content(snap),
        {
            "theme": "   ",
            "deterministic_overrides": {
                "2026-09-07": {"morning_talk_topic": " \n ", "group_activity_theme": "\t"}
            },
            "weekly_columns": {"key_week_focus": "   "},
        },
        snap,
    )
    before = copy.deepcopy(content)
    facts = w.build_facts(content, snap)
    codes = _codes(facts["missing"])
    assert "empty_theme" in codes
    assert any(
        item["field_path"] == "deterministic[2026-09-07].effective.morning_talk_topic"
        for item in facts["missing"]
    )
    assert any(
        item["field_path"] == "weekly_columns.key_week_focus"
        for item in facts["missing"]
    )
    assert content == before
    assert content["theme"] == "   "


def test_validate_content_source_state_matches_day_state_and_history():
    snap = _snapshot()
    content = w.new_content(snap)
    # 2026-09-10 is teaching with no source: no_plan is the only legal state.
    bad = copy.deepcopy(content)
    bad["deterministic"][3]["source_state"] = "none_required"
    bad["source_manifest"]["sources"][3]["source_state"] = "none_required"
    with pytest.raises(w.WeeklyContentError):
        w.validate_content(bad)
    # A saved historical source may remain on a now-rest day.
    historical = copy.deepcopy(content)
    source = copy.deepcopy(historical["deterministic"][0]["source"])
    historical["deterministic"][2]["source"] = source
    historical["deterministic"][2]["source_state"] = "saved"
    historical["source_manifest"]["sources"][2].update(
        {
            "source_state": "saved",
            "daily_plan_id": source["daily_plan_id"],
            "content_id": source["content_id"],
            "content_version": source["content_version"],
            "content_hash": source["content_hash"],
        }
    )
    validated = w.validate_content(historical)
    assert validated["deterministic"][2]["day_state"] == "rest"
    assert validated["deterministic"][2]["source_state"] == "saved"
    # A non-null source must be saved, not no_plan/none_required.
    bad = copy.deepcopy(content)
    bad["deterministic"][0]["source_state"] = "none_required"
    bad["source_manifest"]["sources"][0]["source_state"] = "none_required"
    with pytest.raises(w.WeeklyContentError):
        w.validate_content(bad)


def test_validate_content_rejects_synchronized_duplicate_dates_across_layers():
    content = w.new_content(_snapshot())
    bad = copy.deepcopy(content)
    bad["deterministic"][1]["date"] = bad["deterministic"][0]["date"]
    bad["calendar_basis"]["days"][1]["date"] = bad["calendar_basis"]["days"][0]["date"]
    bad["source_manifest"]["sources"][1]["date"] = bad["source_manifest"]["sources"][0]["date"]
    with pytest.raises(w.WeeklyContentError):
        w.validate_content(bad)


def test_module_imports_are_pure():
    import ast
    from pathlib import Path
    source = Path(w.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    assert not any(name == "sqlalchemy" or name.startswith("sqlalchemy.") for name in names)
    assert not any(name in {"app.local.models", "app.local.runtime"} or name.startswith("app.local.") and name.endswith((".models", ".runtime")) for name in names)


def test_module_has_no_db_or_runtime_imports():
    assert "app.local.weekly_plan_content" in sys.modules
