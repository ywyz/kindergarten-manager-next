"""Pure materials basis/evidence/synthesis/provenance tests."""

from __future__ import annotations

import copy
import json
from datetime import date, timedelta

import pytest

from app.local import weekly_ai_contracts as c
from app.local import weekly_ai_contracts as contracts
from app.local import weekly_ai_inputs as inputs
from app.local import weekly_materials as m
from app.local import weekly_plan_content as w
from tests.local.weekly_ai_fake_transport import (
    make_snapshot as _snapshot,
    selector as _selector,
    source_candidate as _candidate,
)


def _raw(snapshot: dict, content: dict, **overrides) -> dict:
    raw = {
        "schema_version": 1,
        "contract_version": 1,
        "source_kind": "weekly_plan",
        "profile_id": snapshot["profile_id"],
        "class_id": snapshot["class_id"],
        "term_id": snapshot["term_id"],
        "weekly_plan_id": "plan-1",
        "draft_id": "draft-1",
        "draft_version": 1,
        "content_hash": w.content_hash(content),
        "week_anchor_date": snapshot["week_anchor_date"],
        "week_number": snapshot["week_number"],
        "term_start": snapshot["term_start"],
        "term_end": snapshot["term_end"],
        "calendar_revision_id": snapshot["calendar_revision_id"],
        "config_version": snapshot["config_version"],
        "header": snapshot["header"],
        "source_context_hash": snapshot["source_context_hash"],
        "days": [],
        "calendar_window": {"start": "2026-08-31", "end": "2026-09-20", "days": []},
        "game_config": {
            "revision_id": "rev-1",
            "revision_no": 2,
            "locations": [
                {
                    "kind": "area",
                    "name": "建构区",
                    "occurrence": 1,
                    "guidance": "建构区材料",
                }
            ],
            "game_scope": "室内",
            "guidance": "配置说明",
        },
    }
    for day in snapshot["days"]:
        source = day["source"]
        raw["days"].append(
            {
                "date": day["date"],
                "day_state": day["day_state"],
                "source_state": day["source_state"],
                "source": (
                    {
                        **source,
                        "group_activity_objectives": "活动目标",
                        "group_activity_process": "活动过程",
                    }
                    if source
                    else None
                ),
                "morning_groups": day["morning_groups"],
                "post_group_groups": day["post_group_groups"],
            }
        )
    anchor = date(2026, 9, 7)
    for offset in range(-7, 14):
        day_text = (anchor + timedelta(days=offset)).isoformat()
        raw["calendar_window"]["days"].append(
            {
                "date": day_text,
                "day_state": "teaching",
                "holiday_names": ["中秋节"] if day_text == "2026-09-25" else [],
                "coverage": "known",
            }
        )
    raw.update(overrides)
    return raw


def _selected_content() -> tuple[dict, dict]:
    snapshot = _snapshot()
    content = w.new_content(snapshot)
    content = w.apply_patch(
        content,
        {
            "outdoor_game_slots": {
                "collective_1": _selector(_candidate(snapshot, "collective")),
            },
            "focus_area": _selector(_candidate(snapshot, "focus")),
        },
        snapshot,
    )
    return snapshot, content


def _manifest(content: dict, snapshot: dict) -> dict:
    projected = inputs.project_weekly_input(
        "weekly_materials_generate", _raw(snapshot, content), content
    )
    return projected.server_manifest


def _wire_items(manifest: dict) -> list[dict]:
    handle = sorted(
        key
        for key, entry in manifest["handles"].items()
        if entry["kind"] in ("morning_game", "post_group_game")
    )[0]
    entry = manifest["handles"][handle]
    quote = entry["name"]
    return [
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
        },
        {"text": "胶水", "origin": "suggested", "evidence_refs": []},
    ]


def test_suggested_materials_without_focus_adopt_through_existing_flow():
    snapshot, _selected = _selected_content()
    content = w.new_content(snapshot)  # no focus_area, no selected slots
    manifest = _manifest(content, snapshot)
    basis = m.build_materials_basis(grade="small", content=content)
    assert basis["selected"]["focus_area"] is None
    wire = [{"text": "彩纸", "origin": "suggested", "evidence_refs": []}]
    items = m.materialize_materials_items(wire, server_manifest=manifest)
    provenance = m.build_materials_provenance(
        candidate_id="candidate-suggested",
        candidate_hash="a" * 64,
        input_id="input-suggested",
        execution_id="execution-suggested",
        contract_version=1,
        dependency_hash="b" * 64,
        basis=basis,
        items=items,
        original_text="彩纸",
        adopter_profile_id="profile-1",
        adopted_draft_id="draft-2",
        adopted_draft_version=2,
        adopted_at="2026-11-03T00:00:00+00:00",
    )
    adopted = w.apply_weekly_ai_adoption(
        content,
        target="materials",
        candidate_value={"items": wire},
        adoption={
            "candidate_id": provenance["candidate_id"],
            "candidate_hash": provenance["candidate_hash"],
            "input_id": provenance["input_id"],
            "execution_id": provenance["execution_id"],
            "contract_version": provenance["contract_version"],
            "dependency_hash": provenance["dependency_hash"],
            "adopter_profile_id": provenance["adopter_profile_id"],
            "adopted_draft_id": provenance["adopted_draft_id"],
            "adopted_draft_version": provenance["adopted_draft_version"],
            "adopted_at": provenance["adopted_at"],
        },
        basis=basis,
        server_manifest=manifest,
    )
    assert adopted["materials"] == "彩纸"
    assert adopted["materials_provenance"]["items"][0]["origin"] == "suggested"
    assert adopted["materials_provenance"]["basis"]["selected"]["focus_area"] is None
    m.validate_materials_provenance(
        adopted["materials_provenance"],
        materials=adopted["materials"],
        content=adopted,
    )
    with pytest.raises(w.WeeklyContentError):
        m.materialize_materials_items(
            [
                {
                    "text": "伪来源",
                    "origin": "suggested",
                    "evidence_refs": [{"source_handle": "m1"}],
                }
            ],
            server_manifest=manifest,
        )


def test_selected_and_materials_basis_are_exact_and_context_bounded():
    snapshot, content = _selected_content()
    selected = m.build_selected_basis(grade="small", content=content)
    assert set(selected) == {"outdoor_game_slots", "focus_area"}
    assert selected["outdoor_game_slots"]["collective_1"]["ai_basis"] is None
    assert selected["outdoor_game_slots"]["collective_1"]["value"]["name"] == "跳圈圈"
    assert selected["focus_area"]["value"]["context_kind"] == "area"

    basis = m.build_materials_basis(grade="small", content=content)
    assert set(basis) == {
        "schema_version",
        "target",
        "grade",
        "theme",
        "manual_text",
        "daily_sources",
        "selected",
        "config",
        "calendar",
    }
    assert basis["target"] == "materials"
    assert basis["theme"] is None and basis["manual_text"] is None
    assert basis["daily_sources"] == []
    assert basis["calendar"] is None
    assert basis["config"] == []  # no selected AI item in this fixture

    no_focus_basis = m.build_materials_basis(
        grade="small", content=w.new_content(snapshot)
    )
    assert no_focus_basis["selected"]["focus_area"] is None
    assert no_focus_basis["theme"] is None
    assert no_focus_basis["config"] == []


def test_materialize_items_attaches_typed_source_and_rejects_fake_evidence():
    snapshot, content = _selected_content()
    manifest = _manifest(content, snapshot)
    items = m.materialize_materials_items(_wire_items(manifest), server_manifest=manifest)
    ref = items[0]["evidence_refs"][0]
    assert set(ref) == {"source_handle", "field_path", "start", "end", "quote", "source"}
    assert ref["source"]["kind"] in ("morning_game", "post_group_game")
    assert ref["quote"] == ref["source"]["name"]

    broken = copy.deepcopy(_wire_items(manifest))
    broken[0]["evidence_refs"][0]["quote"] = "材料"
    with pytest.raises(w.WeeklyContentError):
        m.materialize_materials_items(broken, server_manifest=manifest)

    broken = copy.deepcopy(_wire_items(manifest))
    broken[1]["evidence_refs"] = copy.deepcopy(broken[0]["evidence_refs"])
    with pytest.raises(w.WeeklyContentError):
        m.materialize_materials_items(broken, server_manifest=manifest)


def test_synthesis_uses_one_newline_and_no_trailing_newline():
    assert m.synthesize_materials_text([]) == ""
    assert m.synthesize_materials_text([{"text": "a"}, {"text": "b"}]) == "a\nb"
    with pytest.raises(w.WeeklyContentError):
        m.synthesize_materials_text([{"text": ""}])


def test_no_focus_provenance_rejects_extracted_material_even_with_handle():
    snapshot = _snapshot()
    content = w.new_content(snapshot)
    content = w.apply_patch(
        content,
        {
            "outdoor_game_slots": {
                "collective_1": _selector(_candidate(snapshot, "collective")),
            }
        },
        snapshot,
    )
    manifest = _manifest(content, snapshot)
    handle = next(
        key
        for key, entry in manifest["handles"].items()
        if entry["kind"] in ("morning_game", "post_group_game")
    )
    name = manifest["handles"][handle]["name"]
    wire = [
        {
            "text": name,
            "origin": "extracted",
            "evidence_refs": [
                {
                    "source_handle": handle,
                    "field_path": "name",
                    "start": 0,
                    "end": len(name),
                    "quote": name,
                }
            ],
        }
    ]
    items = m.materialize_materials_items(wire, server_manifest=manifest)
    basis = m.build_materials_basis(grade="small", content=content)
    assert basis["selected"]["focus_area"] is None
    with pytest.raises(w.WeeklyContentError):
        m.build_materials_provenance(
            candidate_id="candidate-extracted",
            candidate_hash="a" * 64,
            input_id="input-extracted",
            execution_id="execution-extracted",
            contract_version=1,
            dependency_hash="b" * 64,
            basis=basis,
            items=items,
            original_text=m.synthesize_materials_text(items),
            adopter_profile_id="profile-1",
            adopted_draft_id="draft-2",
            adopted_draft_version=2,
            adopted_at="2026-11-03T00:00:00+00:00",
        )


def test_build_and_validate_materials_provenance_exact_keys():
    snapshot, content = _selected_content()
    manifest = _manifest(content, snapshot)
    items = m.materialize_materials_items(_wire_items(manifest), server_manifest=manifest)
    text = m.synthesize_materials_text(items)
    basis = m.build_materials_basis(grade="small", content=content)
    provenance = m.build_materials_provenance(
        candidate_id="candidate-1",
        candidate_hash="a" * 64,
        input_id="input-1",
        execution_id="execution-1",
        contract_version=1,
        dependency_hash="b" * 64,
        basis=basis,
        items=items,
        original_text=text,
        adopter_profile_id="profile-1",
        adopted_draft_id="draft-2",
        adopted_draft_version=2,
        adopted_at="2026-11-03T00:00:00+00:00",
    )
    assert set(provenance) == {
        "candidate_id",
        "candidate_hash",
        "input_id",
        "execution_id",
        "contract_version",
        "dependency_hash",
        "basis",
        "basis_hash",
        "items",
        "original_text",
        "edited",
        "adopter_profile_id",
        "adopted_draft_id",
        "adopted_draft_version",
        "adopted_at",
    }
    assert provenance["edited"] is False
    assert provenance["original_text"] == "彩纸\n胶水"
    assert provenance["basis_hash"] == w.content_hash(basis)

    adopted = w.apply_weekly_ai_adoption(
        content,
        target="materials",
        candidate_value={"items": _wire_items(manifest)},
        adoption={
            "candidate_id": provenance["candidate_id"],
            "candidate_hash": provenance["candidate_hash"],
            "input_id": provenance["input_id"],
            "execution_id": provenance["execution_id"],
            "contract_version": provenance["contract_version"],
            "dependency_hash": provenance["dependency_hash"],
            "adopter_profile_id": provenance["adopter_profile_id"],
            "adopted_draft_id": provenance["adopted_draft_id"],
            "adopted_draft_version": provenance["adopted_draft_version"],
            "adopted_at": provenance["adopted_at"],
        },
        basis=basis,
        server_manifest=manifest,
    )
    validated = m.validate_materials_provenance(
        adopted["materials_provenance"], materials=adopted["materials"], content=adopted
    )
    assert validated == adopted["materials_provenance"]

    broken = copy.deepcopy(adopted["materials_provenance"])
    broken["original_text"] = "伪造"
    with pytest.raises(w.WeeklyContentError):
        m.validate_materials_provenance(
            broken, materials=adopted["materials"], content=adopted
        )

    broken = copy.deepcopy(adopted["materials_provenance"])
    broken["basis_hash"] = "c" * 64
    with pytest.raises(w.WeeklyContentError):
        m.validate_materials_provenance(
            broken, materials=adopted["materials"], content=adopted
        )


def test_empty_items_materializes_empty_text_with_real_basis():
    snapshot, content = _selected_content()
    manifest = _manifest(content, snapshot)
    basis = m.build_materials_basis(grade="small", content=content)
    adopted = w.apply_weekly_ai_adoption(
        content,
        target="materials",
        candidate_value={"items": []},
        adoption={
            "candidate_id": "candidate-empty",
            "candidate_hash": "a" * 64,
            "input_id": "input-empty",
            "execution_id": "execution-empty",
            "contract_version": 1,
            "dependency_hash": "b" * 64,
            "adopter_profile_id": "profile-1",
            "adopted_draft_id": "draft-2",
            "adopted_draft_version": 2,
            "adopted_at": "2026-11-03T00:00:00+00:00",
        },
        basis=basis,
        server_manifest=manifest,
    )
    assert adopted["materials"] == ""
    assert adopted["materials_provenance"]["original_text"] == ""
    assert adopted["materials_provenance"]["items"] == []
    assert adopted["materials_provenance"]["edited"] is False


# ---------------------------------------------------------------------------
# Frozen-basis evidence binding
# ---------------------------------------------------------------------------

def _games_manifest(snapshot: dict, content: dict) -> dict:
    return inputs.project_weekly_input(
        "weekly_games_select", _raw(snapshot, content), content
    ).server_manifest


def _stored_item_from_source(source: dict, *, field_path: str = "name") -> dict:
    quote = source[field_path]
    return {
        "text": "彩纸",
        "origin": "extracted",
        "evidence_refs": [
            {
                "source_handle": "m1",
                "field_path": field_path,
                "start": 0,
                "end": len(quote),
                "quote": quote,
                "source": source,
            }
        ],
    }


def _provenance(basis: dict, items: list[dict]) -> dict:
    return m.build_materials_provenance(
        candidate_id="candidate-1",
        candidate_hash="a" * 64,
        input_id="input-1",
        execution_id="execution-1",
        contract_version=1,
        dependency_hash="b" * 64,
        basis=basis,
        items=items,
        original_text=m.synthesize_materials_text(items),
        adopter_profile_id="profile-1",
        adopted_draft_id="draft-2",
        adopted_draft_version=2,
        adopted_at="2026-11-03T00:00:00+00:00",
    )


def _projection_basis(projection) -> dict:
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


def _ai_games_content(snapshot: dict, content: dict) -> dict:
    projection = inputs.project_weekly_input(
        "weekly_games_select", _raw(snapshot, content), content
    )
    candidate = c.parse_games_candidate(
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
    meta = {
        "candidate_id": "candidate-games",
        "candidate_hash": c.candidate_hash(candidate),
        "input_id": "input-games",
        "execution_id": "execution-games",
        "contract_version": 1,
        "dependency_hash": projection.dependency_hash,
        "adopter_profile_id": "profile-1",
        "adopted_draft_id": "draft-2",
        "adopted_draft_version": 2,
        "adopted_at": "2026-11-03T00:00:00+00:00",
    }
    return w.apply_weekly_ai_adoption(
        content,
        target="games",
        candidate_value=candidate,
        adoption=meta,
        basis=_projection_basis(projection),
        ai_item_ids={"collective_2": "ai-1"},
    )


def test_related_config_evidence_is_accepted_and_fake_config_rejected():
    snapshot, content = _selected_content()
    content = _ai_games_content(snapshot, content)
    basis = m.build_materials_basis(grade="small", content=content)
    assert basis["config"]
    manifest = inputs.project_weekly_input(
        "weekly_materials_generate", _raw(snapshot, content), content
    ).server_manifest
    config = copy.deepcopy(manifest["handles"]["c1"])
    item = {
        "text": "彩纸",
        "origin": "extracted",
        "evidence_refs": [
            {
                "source_handle": "c1",
                "field_path": "guidance",
                "start": 3,
                "end": 5,
                "quote": "材料",
                "source": config,
            }
        ],
    }
    _provenance(basis, [item])

    fake = copy.deepcopy(config)
    fake["guidance"] = "伪造指导"
    fake_item = copy.deepcopy(item)
    fake_item["evidence_refs"][0].update(
        {"start": 0, "end": 4, "quote": "伪造指导", "source": fake}
    )
    with pytest.raises(w.WeeklyContentError):
        _provenance(basis, [fake_item])


def test_evidence_source_must_belong_to_frozen_selected_source():
    snapshot, content = _selected_content()
    basis = m.build_materials_basis(grade="small", content=content)
    games = _games_manifest(snapshot, content)

    selected = copy.deepcopy(games["handles"]["m1"])
    _provenance(basis, [_stored_item_from_source(selected)])

    unselected = copy.deepcopy(games["handles"]["m2"])
    with pytest.raises(w.WeeklyContentError):
        _provenance(basis, [_stored_item_from_source(unselected)])

    different_version = copy.deepcopy(games["handles"]["m1"])
    different_version["content_version"] = 2
    with pytest.raises(w.WeeklyContentError):
        _provenance(basis, [_stored_item_from_source(different_version)])

    spliced = copy.deepcopy(games["handles"]["m1"])
    spliced["guidance_points"] = "拼接的指导"
    with pytest.raises(w.WeeklyContentError):
        _provenance(
            basis,
            [_stored_item_from_source(spliced, field_path="guidance_points")],
        )


def test_evidence_config_source_must_be_referenced_by_frozen_selected_ai_basis():
    snapshot, content = _selected_content()
    basis = m.build_materials_basis(grade="small", content=content)
    games = _games_manifest(snapshot, content)
    config = copy.deepcopy(games["handles"]["c1"])
    with pytest.raises(w.WeeklyContentError):
        _provenance(
            basis,
            [
                {
                    "text": "彩纸",
                    "origin": "extracted",
                    "evidence_refs": [
                        {
                            "source_handle": "c1",
                            "field_path": "guidance",
                            "start": 3,
                            "end": 5,
                            "quote": "材料",
                            "source": config,
                        }
                    ],
                }
            ],
        )
    fake = copy.deepcopy(config)
    fake["revision_id"] = "fake-revision"
    with pytest.raises(w.WeeklyContentError):
        _provenance(
            basis,
            [
                {
                    "text": "彩纸",
                    "origin": "extracted",
                    "evidence_refs": [
                        {
                            "source_handle": "c1",
                            "field_path": "guidance",
                            "start": 3,
                            "end": 5,
                            "quote": "材料",
                            "source": fake,
                        }
                    ],
                }
            ],
        )


def test_material_provenance_uses_old_basis_after_current_reselection():
    snapshot, content = _selected_content()
    manifest = _manifest(content, snapshot)
    items = m.materialize_materials_items(_wire_items(manifest), server_manifest=manifest)
    basis = m.build_materials_basis(grade="small", content=content)
    provenance = _provenance(basis, items)
    adopted = w.apply_weekly_ai_adoption(
        content,
        target="materials",
        candidate_value={"items": _wire_items(manifest)},
        adoption={
            "candidate_id": provenance["candidate_id"],
            "candidate_hash": provenance["candidate_hash"],
            "input_id": provenance["input_id"],
            "execution_id": provenance["execution_id"],
            "contract_version": provenance["contract_version"],
            "dependency_hash": provenance["dependency_hash"],
            "adopter_profile_id": provenance["adopter_profile_id"],
            "adopted_draft_id": provenance["adopted_draft_id"],
            "adopted_draft_version": provenance["adopted_draft_version"],
            "adopted_at": provenance["adopted_at"],
        },
        basis=basis,
        server_manifest=manifest,
    )
    old_provenance = copy.deepcopy(adopted["materials_provenance"])

    # Remove the current selection that supplied the evidence; the old frozen
    # basis remains the authority for already-adopted material evidence.
    changed = w.apply_patch(
        adopted,
        {"outdoor_game_slots": {"collective_1": None}},
        snapshot,
    )
    assert changed["outdoor_game_slots"]["collective_1"] is None
    assert changed["materials_provenance"] == old_provenance
    validated = m.validate_materials_provenance(
        changed["materials_provenance"],
        materials=changed["materials"],
        content=changed,
    )
    assert validated["basis"] == old_provenance["basis"]

    # Replacing the selected source with a different real source also keeps
    # the old evidence valid until a new explicit materials adoption.
    reselected = w.apply_patch(
        adopted,
        {
            "outdoor_game_slots": {
                "free_choice_1": _selector(_candidate(snapshot, "free_choice"))
            }
        },
        snapshot,
    )
    assert reselected["outdoor_game_slots"]["free_choice_1"]["name"] == "滚球"
    assert reselected["materials_provenance"] == old_provenance
    m.validate_materials_provenance(
        reselected["materials_provenance"],
        materials=reselected["materials"],
        content=reselected,
    )


def test_normal_materials_projection_allocates_only_selected_and_related_config():
    snapshot, content = _selected_content()
    content = _ai_games_content(snapshot, content)
    projection = inputs.project_weekly_input(
        "weekly_materials_generate", _raw(snapshot, content), content
    )
    manifest = projection.server_manifest
    assert set(manifest["handles"]) == {"m1", "a1", "p1", "c1"}
    assert {"m2", "m3", "m4", "p2", "m99"}.isdisjoint(manifest["handles"])

    # A normal materials manifest has no alias for an unselected source; the
    # materializer rejects both an absent handle and a quote copied from a
    # different selected source.
    absent = {
        "text": "彩纸",
        "origin": "extracted",
        "evidence_refs": [
            {
                "source_handle": "m99",
                "field_path": "name",
                "start": 0,
                "end": 1,
                "quote": "跳",
            }
        ],
    }
    with pytest.raises(w.WeeklyContentError):
        m.materialize_materials_items([absent], server_manifest=manifest)

    p1_name = manifest["handles"]["p1"]["name"]
    wrong_source = {
        "text": "彩纸",
        "origin": "extracted",
        "evidence_refs": [
            {
                "source_handle": "m1",
                "field_path": "name",
                "start": 0,
                "end": len(p1_name),
                "quote": p1_name,
            }
        ],
    }
    with pytest.raises(w.WeeklyContentError):
        m.materialize_materials_items([wrong_source], server_manifest=manifest)


def test_materials_provenance_512k_boundary_and_content_1m():
    snapshot, content = _selected_content()
    manual = {
        "source_kind": "manual",
        "manual_item_id": None,
        "client_key": "long-manual",
        "name": "长指导",
        "shared_objectives": "a" * 2000,
        "guidance_points": "指",
        "focus_guidance": "b" * 2000,
    }
    content = w.apply_patch(
        content,
        {"outdoor_game_slots": {"free_choice_1": manual}},
        snapshot,
        manual_ids={"long-manual": "manual-long-1"},
    )
    manifest = inputs.project_weekly_input(
        "weekly_materials_generate", _raw(snapshot, content), content
    ).server_manifest
    source = copy.deepcopy(manifest["handles"]["h1"])
    basis = m.build_materials_basis(grade="small", content=content)

    def stored_item() -> dict:
        return {
            "text": "x",
            "origin": "extracted",
            "evidence_refs": [
                {
                    "source_handle": "h1",
                    "field_path": "shared_objectives",
                    "start": 0,
                    "end": 2000,
                    "quote": "a" * 2000,
                    "source": copy.deepcopy(source),
                },
                {
                    "source_handle": "h1",
                    "field_path": "focus_guidance",
                    "start": 0,
                    "end": 2000,
                    "quote": "b" * 2000,
                    "source": copy.deepcopy(source),
                },
            ],
        }

    small_items = [stored_item()]
    small_provenance = _provenance(basis, small_items)
    assert len(w.canonical_json(small_provenance).encode("utf-8")) < 524288
    small_content = copy.deepcopy(content)
    small_content["materials"] = small_provenance["original_text"]
    small_content["materials_provenance"] = small_provenance
    assert w.validate_content(small_content)["materials_provenance"] == small_provenance

    large_items = [stored_item() for _ in range(70)]
    large_provenance = _provenance(basis, large_items)
    provenance_bytes = len(w.canonical_json(large_provenance).encode("utf-8"))
    assert provenance_bytes > 524288
    large_content = copy.deepcopy(content)
    large_content["materials"] = large_provenance["original_text"]
    large_content["materials_provenance"] = large_provenance
    content_bytes = len(w.canonical_json(large_content).encode("utf-8"))
    assert content_bytes < 1048576
    with pytest.raises(w.WeeklyContentError) as exc_info:
        w.validate_content(large_content)
    assert exc_info.value.code == "WEEKLY_CONTENT_TOO_LARGE"
    assert exc_info.value.field_path == "content"


def test_materials_schema_revision_and_guidance_are_complete():
    bundle = next(
        item
        for item in contracts.weekly_bundle_definitions()
        if item["task_type"] == "weekly_materials_generate"
    )
    assert bundle["contract_version"] == 2
    assert bundle["default_revision"] == 1
    schema = bundle["output_schema_json"]
    assert schema["additionalProperties"] is False
    item_schemas = schema["properties"]["items"]["items"]["oneOf"]
    assert len(item_schemas) == 2
    for item_schema in item_schemas:
        assert set(item_schema["required"]) == {"text", "origin", "evidence_refs"}
        assert item_schema["additionalProperties"] is False
    instructions = bundle["guidance_defaults_json"]["instructions"]
    for term in ("text", "origin", "evidence_refs", "Unicode", "20000"):
        assert term in instructions
