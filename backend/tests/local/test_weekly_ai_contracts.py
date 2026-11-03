"""Pure contract tests for `weekly_ai_contracts` (no DB/runtime/network)."""

from __future__ import annotations

import copy
import json
import re

import pytest

from app.local import weekly_ai_contracts as c


def _hash(ch: str = "a") -> str:
    return ch * 64


def _plan() -> dict:
    return {
        "weekly_plan_id": "plan-1",
        "draft_id": "draft-1",
        "draft_version": 2,
        "content_hash": _hash(),
        "profile_id": "profile-1",
        "class_id": "class-1",
        "term_id": "term-1",
        "week_anchor_date": "2026-09-07",
        "week_number": 2,
    }


def _handles() -> dict:
    return {
        "m1": {
            "kind": "morning_game",
            "date": "2026-09-07",
            "daily_plan_id": "daily-1",
            "content_id": "content-1",
            "content_version": 1,
            "content_hash": _hash(),
            "group_id": "group-m",
            "group_kind": "collective",
            "game_id": "game-m",
            "name": "跳圈圈",
            "shared_objectives": "共同目标",
            "guidance_points": "指导",
            "focus_guidance": "重点",
        },
        "p1": {
            "kind": "post_group_game",
            "date": "2026-09-07",
            "daily_plan_id": "daily-1",
            "content_id": "content-1",
            "content_version": 1,
            "content_hash": _hash(),
            "group_id": "group-p",
            "context_kind": "area",
            "area": "建构区",
            "game_id": "game-p",
            "name": "建构游戏",
            "objectives": "区域目标",
            "guidance": "区域指导",
            "support_strategy": "支持",
        },
        "c1": {
            "kind": "config_location",
            "revision_id": "rev-1",
            "revision_no": 2,
            "location_kind": "area",
            "name": "建构区",
            "occurrence": 1,
            "guidance": "建构区材料",
            "game_scope": "室内",
            "config_guidance": "配置说明",
        },
    }


def _manifest(task_type: str = "weekly_games_select") -> dict:
    return {
        "schema_version": 1,
        "task_type": task_type,
        "plan": _plan(),
        "source_context_hash": _hash("b"),
        "handles": _handles(),
    }


def test_weekly_bundle_definitions_are_exact_and_ordered():
    bundles = c.weekly_bundle_definitions()
    assert [item["task_type"] for item in bundles] == [
        "weekly_games_select",
        "weekly_key_week_focus",
        "weekly_environment_setup",
        "weekly_habit_culture",
        "weekly_home_cooperation",
        "weekly_materials_generate",
    ]
    required = {
        "task_type",
        "contract_version",
        "default_revision",
        "input_schema_json",
        "output_schema_json",
        "guidance_defaults_json",
    }
    for item in bundles:
        assert set(item) == required
        expected_contract = 2 if item["task_type"] in (
            "weekly_games_select",
            "weekly_materials_generate",
        ) else 1
        assert item["contract_version"] == expected_contract
        assert item["default_revision"] == 1
        assert isinstance(item["input_schema_json"], dict)
        assert isinstance(item["output_schema_json"], dict)
        assert isinstance(item["guidance_defaults_json"], dict)
    assert c.TARGETS == (
        "games",
        "key_week_focus",
        "environment_setup",
        "habit_culture",
        "home_cooperation",
        "materials",
    )


def test_strict_json_rejects_free_text_duplicate_keys_and_nonfinite():
    assert c.strict_json_object('  {"a": 1}  ') == {"a": 1}
    for raw in (
        "",
        "\ufeff{}",
        "```json\n{}\n```",
        '{"a":1}{"b":2}',
        '{"a":1,"a":2}',
        '{"a":NaN}',
        "[]",
        '{"a":"\x00"}',
    ):
        with pytest.raises(c.WeeklyAIContractError):
            c.strict_json_object(raw)


def test_handle_manifest_requires_exact_typed_keys():
    manifest = c.validate_handle_manifest(_manifest())
    assert set(manifest["handles"]) == {"c1", "m1", "p1"}
    assert manifest["handles"]["m1"]["kind"] == "morning_game"

    for mutate in (
        lambda value: value["handles"]["m1"].update({"extra": "x"}),
        lambda value: value["handles"]["m1"].update({"kind": "post_group_game"}),
        lambda value: value["handles"]["c1"].update({"slot_key": "collective_1"}),
        lambda value: value["handles"]["m1"].update({"date": "2026/09/07"}),
        lambda value: value.update({"handles": {**value["handles"], "x": {"kind": "morning_game"}}}),
    ):
        broken = copy.deepcopy(_manifest())
        mutate(broken)
        with pytest.raises(c.WeeklyAIContractError):
            c.validate_handle_manifest(broken)


def test_games_parser_materializes_sources_and_ai_supplements():
    manifest = _manifest()
    raw = (
        '{"outdoor_game_slots":{'
        '"collective_1":{"kind":"source","source_handle":"m1"},'
        '"collective_2":{"kind":"ai_supplement","name":"新游戏",'
        '"shared_objectives":"目标","guidance_points":"指导",'
        '"focus_guidance":"重点","basis_handles":["c1"]},'
        '"free_choice_1":null},'
        '"focus_area":{"kind":"source","source_handle":"p1"}}'
    )
    value = c.parse_games_candidate(raw, server_manifest=manifest)
    assert value["outdoor_game_slots"]["collective_1"]["source_kind"] == "daily_plan"
    assert value["outdoor_game_slots"]["collective_1"]["name"] == "跳圈圈"
    assert value["outdoor_game_slots"]["collective_2"]["source_kind"] == "ai_supplement"
    assert value["outdoor_game_slots"]["collective_2"]["basis_keys"] == ["c1"]
    assert value["outdoor_game_slots"]["collective_2"]["daily_plan_id"] is None
    assert value["focus_area"]["source_kind"] == "daily_plan"
    assert c.candidate_hash(value) == c.candidate_hash(copy.deepcopy(value))

    finalized = c.finalize_games_value(
        value,
        candidate_id="candidate-1",
        input_id="input-1",
        ai_item_ids={"collective_2": "ai-1"},
    )
    ai = finalized["outdoor_game_slots"]["collective_2"]
    assert ai["ai_item_id"] == "ai-1"
    assert ai["candidate_id"] == "candidate-1"
    assert ai["input_id"] == "input-1"
    assert c.candidate_hash(value) != c.candidate_hash(finalized)


def test_games_parser_rejects_unknown_handle_wrong_kind_and_duplicate_collective_name():
    manifest = _manifest()
    for raw in (
        '{"outdoor_game_slots":{"collective_1":{"kind":"source","source_handle":"m9"},'
        '"collective_2":null,"free_choice_1":null},"focus_area":null}',
        '{"outdoor_game_slots":{"collective_1":{"kind":"source","source_handle":"p1"},'
        '"collective_2":null,"free_choice_1":null},"focus_area":null}',
        '{"outdoor_game_slots":{"collective_1":{"kind":"ai_supplement","name":"跳圈圈",'
        '"shared_objectives":"","guidance_points":"","focus_guidance":"","basis_handles":[]},'
        '"collective_2":{"kind":"source","source_handle":"m1"},'
        '"free_choice_1":null},"focus_area":null}',
        '{"outdoor_game_slots":{"collective_1":{"kind":"source","source_handle":"m1"},'
        '"collective_2":null,"free_choice_1":null},"focus_area":{"kind":"source","source_handle":"m1"}}',
        '{"outdoor_game_slots":{"collective_1":null,"collective_2":null,"free_choice_1":null},'
        '"focus_area":null,"extra":1}',
    ):
        with pytest.raises(c.WeeklyAIContractError):
            c.parse_games_candidate(raw, server_manifest=manifest)


def test_column_parser_is_strict_and_nonempty():
    assert c.parse_column_candidate('{"text":" 本周重点 "}', task_type="weekly_key_week_focus") == {
        "text": " 本周重点 "
    }
    for raw in ('{"text":""}', '{"text":"   "}', '{"text":1}', '{"text":"x","y":1}'):
        with pytest.raises(c.WeeklyAIContractError):
            c.parse_column_candidate(raw, task_type="weekly_key_week_focus")
    with pytest.raises(c.WeeklyAIContractError):
        c.parse_column_candidate('{"text":"x"}', task_type="weekly_games_select")


def test_materials_parser_uses_code_point_evidence_and_rejects_fake_quotes():
    manifest = _manifest("weekly_materials_generate")
    raw = (
        '{"items":['
        '{"text":"彩纸","origin":"extracted","evidence_refs":[{"source_handle":"c1",'
        '"field_path":"guidance","start":3,"end":5,"quote":"材料"}]},'
        '{"text":"胶水","origin":"suggested","evidence_refs":[]}'
        "]}"
    )
    value = c.parse_materials_candidate(raw, server_manifest=manifest)
    assert value["items"][0]["evidence_refs"][0]["quote"] == "材料"
    assert value["items"][1]["origin"] == "suggested"

    for bad in (
        raw.replace('"start":3,"end":5', '"start":2,"end":4'),
        raw.replace('"origin":"suggested","evidence_refs":[]', '"origin":"suggested","evidence_refs":[{"source_handle":"c1","field_path":"guidance","start":0,"end":2,"quote":"建构"}]'),
        '{"items":[{"text":"x","origin":"extracted","evidence_refs":[]}]}',
        '{"items":[{"text":"x","origin":"suggested"}]}',
    ):
        with pytest.raises(c.WeeklyAIContractError):
            c.parse_materials_candidate(bad, server_manifest=manifest)


def test_materials_parser_rejects_more_than_synthesis_limit(monkeypatch):
    manifest = _manifest("weekly_materials_generate")
    items = [
        {"text": "x" * 300, "origin": "suggested", "evidence_refs": []}
        for _ in range(67)
    ]
    import json

    raw = json.dumps({"items": items}, ensure_ascii=False)
    with pytest.raises(c.WeeklyAIContractError):
        c.parse_materials_candidate(raw, server_manifest=manifest)
    # Hard cap is checked before parsing too.
    with pytest.raises(c.WeeklyAIContractError):
        c.parse_materials_candidate(
            json.dumps({"items": items * 2}, ensure_ascii=False),
            server_manifest=manifest,
        )


# ---------------------------------------------------------------------------
# Stored-candidate validation and safe error surface
# ---------------------------------------------------------------------------

SECRET = "SYNTH_SECRET_MARKER_7f3a"


def _assert_no_marker(exc: BaseException, marker: str = SECRET) -> None:
    visible = (
        str(exc),
        repr(exc),
        getattr(exc, "message", ""),
        getattr(exc, "field_path", ""),
        repr(getattr(exc, "details", {})),
        repr(vars(exc)) if hasattr(exc, "__dict__") else "",
    )
    for text in visible:
        assert marker not in text


def _valid_games_value() -> dict:
    manifest = _manifest()
    raw = (
        '{"outdoor_game_slots":{'
        '"collective_1":{"kind":"source","source_handle":"m1"},'
        '"collective_2":{"kind":"ai_supplement","name":"新游戏",'
        '"shared_objectives":"目标","guidance_points":"指导",'
        '"focus_guidance":"重点","basis_handles":["c1"]},'
        '"free_choice_1":null},'
        '"focus_area":{"kind":"source","source_handle":"p1"}}'
    )
    return c.parse_games_candidate(raw, server_manifest=manifest)


def _valid_materials_value() -> dict:
    manifest = _manifest("weekly_materials_generate")
    raw = (
        '{"items":[{"text":"彩纸","origin":"extracted","evidence_refs":['
        '{"source_handle":"c1","field_path":"guidance","start":3,"end":5,"quote":"材料"}]}]}'
    )
    return c.parse_materials_candidate(raw, server_manifest=manifest)


def test_validate_stored_candidate_positive_controls_all_tasks():
    games = _valid_games_value()
    games_out = c.validate_stored_candidate(
        "weekly_games_select", games, server_manifest=_manifest()
    )
    assert games_out == games
    assert games_out is not games
    assert games_out["outdoor_game_slots"] is not games["outdoor_game_slots"]

    for field, task in c.COLUMN_TASK.items():
        manifest = _manifest(task)
        value = c.parse_column_candidate('{"text":"正文"}', task_type=task)
        out = c.validate_stored_candidate(task, value, server_manifest=manifest)
        assert out == value and out is not value

    materials = _valid_materials_value()
    materials_out = c.validate_stored_candidate(
        "weekly_materials_generate",
        materials,
        server_manifest=_manifest("weekly_materials_generate"),
    )
    assert materials_out == materials
    assert materials_out is not materials
    assert "source" not in materials_out["items"][0]["evidence_refs"][0]


def test_validate_stored_candidate_rejects_source_and_ai_tampering():
    games = _valid_games_value()
    manifest = _manifest()
    cases = []

    changed_text = copy.deepcopy(games)
    changed_text["outdoor_game_slots"]["collective_1"]["name"] = SECRET
    cases.append(changed_text)

    changed_group_text = copy.deepcopy(games)
    changed_group_text["outdoor_game_slots"]["collective_1"]["shared_objectives"] = SECRET
    cases.append(changed_group_text)

    changed_hash = copy.deepcopy(games)
    changed_hash["outdoor_game_slots"]["collective_1"]["content_hash"] = "f" * 64
    cases.append(changed_hash)

    extra_source_id = copy.deepcopy(games)
    extra_source_id["outdoor_game_slots"]["collective_1"]["ai_item_id"] = SECRET
    cases.append(extra_source_id)

    forged_ai = copy.deepcopy(games)
    forged_ai["outdoor_game_slots"]["collective_2"]["ai_item_id"] = SECRET
    forged_ai["outdoor_game_slots"]["collective_2"]["candidate_id"] = "candidate-x"
    forged_ai["outdoor_game_slots"]["collective_2"]["input_id"] = "input-x"
    cases.append(forged_ai)

    forged_focus = copy.deepcopy(games)
    forged_focus["focus_area"]["candidate_id"] = SECRET
    cases.append(forged_focus)

    extra_top = copy.deepcopy(games)
    extra_top[SECRET] = SECRET
    cases.append(extra_top)

    for value in cases:
        with pytest.raises(c.WeeklyAIContractError) as exc_info:
            c.validate_stored_candidate("weekly_games_select", value, server_manifest=manifest)
        assert exc_info.value.code == "WEEKLY_AI_OUTPUT_INVALID"
        _assert_no_marker(exc_info.value)

    # Genuinely different input manifest cannot be substituted by same names.
    other_manifest = _manifest()
    other_manifest["handles"]["m1"]["name"] = "另一游戏"
    with pytest.raises(c.WeeklyAIContractError) as exc_info:
        c.validate_stored_candidate(
            "weekly_games_select", games, server_manifest=other_manifest
        )
    assert exc_info.value.code == "WEEKLY_AI_OUTPUT_INVALID"
    _assert_no_marker(exc_info.value)


def test_validate_stored_candidate_rejects_materials_positions_and_stored_evidence():
    materials = _valid_materials_value()
    manifest = _manifest("weekly_materials_generate")
    for mutate in (
        lambda value: value["items"][0]["evidence_refs"][0].update({"quote": SECRET}),
        lambda value: value["items"][0]["evidence_refs"][0].update({"start": 0, "end": 2}),
        lambda value: value["items"][0]["evidence_refs"][0].update(
            {"source": copy.deepcopy(manifest["handles"]["c1"])}
        ),
        lambda value: value["items"][0].update({"extra": SECRET}),
        lambda value: value.update({SECRET: SECRET}),
        lambda value: value["items"][0].update({"origin": "suggested"}),
    ):
        broken = copy.deepcopy(materials)
        mutate(broken)
        with pytest.raises(c.WeeklyAIContractError) as exc_info:
            c.validate_stored_candidate(
                "weekly_materials_generate", broken, server_manifest=manifest
            )
        assert exc_info.value.code == "WEEKLY_AI_OUTPUT_INVALID"
        _assert_no_marker(exc_info.value)


def test_validate_stored_candidate_rejects_columns_and_cross_type():
    manifest = _manifest("weekly_key_week_focus")
    value = c.parse_column_candidate('{"text":"正文"}', task_type="weekly_key_week_focus")
    broken = {"text": "正文", SECRET: SECRET}
    with pytest.raises(c.WeeklyAIContractError) as exc_info:
        c.validate_stored_candidate("weekly_key_week_focus", broken, server_manifest=manifest)
    assert exc_info.value.code == "WEEKLY_AI_OUTPUT_INVALID"
    _assert_no_marker(exc_info.value)

    with pytest.raises(c.WeeklyAIContractError) as exc_info:
        c.validate_stored_candidate(
            "weekly_materials_generate", value, server_manifest=manifest
        )
    assert exc_info.value.code == "WEEKLY_AI_OUTPUT_INVALID"
    _assert_no_marker(exc_info.value)

    with pytest.raises(c.WeeklyAIContractError):
        c.validate_stored_candidate("weekly_key_week_focus", value, server_manifest=_manifest())


def test_safe_error_surface_for_extra_duplicate_key_and_invalid_handle_markers():
    cases = []

    try:
        c.strict_json_object('{"' + SECRET + '":1,"' + SECRET + '":2}')
    except c.WeeklyAIContractError as exc:
        cases.append(exc)

    try:
        c.parse_games_candidate(
            '{"outdoor_game_slots":{"collective_1":null,"collective_2":null,'
            '"free_choice_1":null},"focus_area":null,"' + SECRET + '":1}',
            server_manifest=_manifest(),
        )
    except c.WeeklyAIContractError as exc:
        cases.append(exc)

    try:
        c.parse_games_candidate(
            '{"outdoor_game_slots":{"collective_1":{"kind":"source",'
            '"source_handle":"' + SECRET + '"},"collective_2":null,'
            '"free_choice_1":null},"focus_area":null}',
            server_manifest=_manifest(),
        )
    except c.WeeklyAIContractError as exc:
        cases.append(exc)

    try:
        broken_manifest = copy.deepcopy(_manifest())
        broken_manifest["handles"][SECRET] = copy.deepcopy(broken_manifest["handles"]["m1"])
        c.validate_handle_manifest(broken_manifest)
    except c.WeeklyAIContractError as exc:
        cases.append(exc)

    try:
        c.finalize_games_value(
            _valid_games_value(),
            candidate_id="candidate-1",
            input_id="input-1",
            ai_item_ids={"collective_2": "ai-1", SECRET: "ai-2"},
        )
    except c.WeeklyAIContractError as exc:
        cases.append(exc)

    assert len(cases) == 5
    for exc in cases:
        _assert_no_marker(exc)
        assert exc.code in ("WEEKLY_AI_OUTPUT_INVALID", "WEEKLY_AI_INPUT_INVALID")
        # No dynamic unknown key or secret is echoed in any visible attribute.
        assert SECRET not in repr(vars(exc))


def test_habit_bundle_schema_locks_inner_whitelist():
    habit = next(
        item
        for item in c.weekly_bundle_definitions()
        if item["task_type"] == "weekly_habit_culture"
    )
    schema = habit["input_schema_json"]
    day = schema["properties"]["days"]["items"]
    assert set(day["required"]) == {
        "date",
        "morning_talk_topic",
        "morning_groups",
        "post_support",
    }
    morning = day["properties"]["morning_groups"]["items"]
    assert set(morning["required"]) == {"guidance_points", "focus_guidance"}
    assert set(morning["properties"]) == {"guidance_points", "focus_guidance"}
    post = day["properties"]["post_support"]["items"]
    assert set(post["required"]) == {"support_strategy"}
    assert set(post["properties"]) == {"support_strategy"}
    assert habit["guidance_defaults_json"]["allowed_input_fields"] == [
        "date",
        "morning_talk_topic",
        "morning_groups.guidance_points",
        "morning_groups.focus_guidance",
        "post_support.support_strategy",
    ]


def _materials_manifest_with_guidance(length: int) -> dict:
    manifest = _manifest("weekly_materials_generate")
    manifest["handles"]["c1"]["guidance"] = "材" * length
    return manifest


def _materials_wire(items: list[dict]) -> str:
    import json

    return json.dumps({"items": items}, ensure_ascii=False)


def _extracted_config_item(quote_length: int | None = None) -> dict:
    if quote_length is None:
        quote_length = 5
    quote = "材" * quote_length
    return {
        "text": "彩纸",
        "origin": "extracted",
        "evidence_refs": [
            {
                "source_handle": "c1",
                "field_path": "guidance",
                "start": 0,
                "end": quote_length,
                "quote": quote,
            }
        ],
    }


def test_materials_limit_boundaries_item_count_text_quote_and_synthesis():
    manifest = _manifest("weekly_materials_generate")
    count_100 = [{"text": "x", "origin": "suggested", "evidence_refs": []} for _ in range(100)]
    assert len(c.parse_materials_candidate(_materials_wire(count_100), server_manifest=manifest)["items"]) == 100
    with pytest.raises(c.WeeklyAIContractError) as exc_info:
        c.parse_materials_candidate(_materials_wire(count_100 + [count_100[0]]), server_manifest=manifest)
    assert exc_info.value.field_path == "materials.items"
    assert exc_info.value.code == "WEEKLY_AI_OUTPUT_INVALID"

    assert c.parse_materials_candidate(
        _materials_wire([{"text": "x" * 300, "origin": "suggested", "evidence_refs": []}]),
        server_manifest=manifest,
    )["items"][0]["text"] == "x" * 300
    with pytest.raises(c.WeeklyAIContractError) as exc_info:
        c.parse_materials_candidate(
            _materials_wire([{"text": "x" * 301, "origin": "suggested", "evidence_refs": []}]),
            server_manifest=manifest,
        )
    assert exc_info.value.field_path == "materials.items[0].text"
    assert exc_info.value.code in ("WEEKLY_AI_INPUT_INVALID", "WEEKLY_AI_OUTPUT_INVALID")

    quote_2000 = _materials_manifest_with_guidance(2000)
    assert c.parse_materials_candidate(
        _materials_wire([_extracted_config_item(2000)]), server_manifest=quote_2000
    )["items"][0]["evidence_refs"][0]["quote"] == "材" * 2000
    quote_2001 = _materials_manifest_with_guidance(2001)
    with pytest.raises(c.WeeklyAIContractError) as exc_info:
        c.parse_materials_candidate(
            _materials_wire([_extracted_config_item(2001)]), server_manifest=quote_2001
        )
    assert exc_info.value.field_path == "materials.items[0].evidence_refs[0].quote"
    assert exc_info.value.code in ("WEEKLY_AI_INPUT_INVALID", "WEEKLY_AI_OUTPUT_INVALID")

    texts_20000 = ["x" * 200] + ["x" * 199 for _ in range(99)]
    assert sum(len(text) for text in texts_20000) + 99 == 20000
    items_20000 = [
        {"text": text, "origin": "suggested", "evidence_refs": []}
        for text in texts_20000
    ]
    assert c.parse_materials_candidate(
        _materials_wire(items_20000), server_manifest=manifest
    )["items"][0]["text"] == "x" * 200

    texts_20001 = ["x" * 201] + ["x" * 199 for _ in range(99)]
    assert sum(len(text) for text in texts_20001) + 99 == 20001
    items_20001 = [
        {"text": text, "origin": "suggested", "evidence_refs": []}
        for text in texts_20001
    ]
    with pytest.raises(c.WeeklyAIContractError) as exc_info:
        c.parse_materials_candidate(_materials_wire(items_20001), server_manifest=manifest)
    assert exc_info.value.field_path == "materials.items"
    assert exc_info.value.code == "WEEKLY_AI_OUTPUT_INVALID"


def _schema_ok(schema: dict, value: object) -> bool:
    if "const" in schema:
        if value != schema["const"]:
            return False
    if "enum" in schema:
        if value not in schema["enum"]:
            return False
    if "oneOf" in schema:
        matches = 0
        for variant in schema["oneOf"]:
            try:
                if _schema_ok(variant, value):
                    matches += 1
            except AssertionError:
                pass
        return matches == 1
    expected_type = schema.get("type")
    if expected_type is not None:
        names = expected_type if isinstance(expected_type, list) else [expected_type]
        valid = False
        for name in names:
            if name == "null":
                valid = valid or value is None
            elif name == "object":
                valid = valid or isinstance(value, dict)
            elif name == "array":
                valid = valid or isinstance(value, list)
            elif name == "string":
                valid = valid or isinstance(value, str)
            elif name == "integer":
                valid = valid or (type(value) is int)
        if not valid:
            return False
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            return False
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            return False
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            return False
    if type(value) is int:
        if "minimum" in schema and value < schema["minimum"]:
            return False
        if "maximum" in schema and value > schema["maximum"]:
            return False
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            return False
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return False
        if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value}) != len(value):
            return False
        if "items" in schema:
            for item in value:
                if not _schema_ok(schema["items"], item):
                    return False
    if isinstance(value, dict):
        required = set(schema.get("required") or ())
        if not required.issubset(value):
            return False
        properties = schema.get("properties") or {}
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            return False
        for key, item in value.items():
            if key in properties and not _schema_ok(properties[key], item):
                return False
    return True


def _games_raw(**overrides) -> dict:
    value = {
        "outdoor_game_slots": {
            "collective_1": None,
            "collective_2": None,
            "free_choice_1": None,
        },
        "focus_area": None,
    }
    value.update(overrides)
    return value


def _games_bundle() -> dict:
    return next(x for x in c.weekly_bundle_definitions() if x["task_type"] == "weekly_games_select")


def _materials_bundle() -> dict:
    return next(x for x in c.weekly_bundle_definitions() if x["task_type"] == "weekly_materials_generate")


def test_prompt_contract_versions_and_support_matrix():
    assert c.CONTRACT_VERSION == 1
    assert c.prompt_contract_version("weekly_games_select") == 2
    assert c.prompt_contract_version("weekly_materials_generate") == 2
    for task in c.COLUMN_TASK.values():
        assert c.prompt_contract_version(task) == 1
    for task in c.TASK_TARGETS:
        assert c.supports_prompt_contract(task, c.prompt_contract_version(task))
    assert c.supports_prompt_contract("weekly_games_select", 1)
    assert c.supports_prompt_contract("weekly_games_select", 2)
    assert c.supports_prompt_contract("weekly_materials_generate", 1)
    assert c.supports_prompt_contract("weekly_materials_generate", 2)
    for task in c.COLUMN_TASK.values():
        assert c.supports_prompt_contract(task, 1)
        assert not c.supports_prompt_contract(task, 2)

    for bad in ("weekly_unknown", "", 1, None, []):
        with pytest.raises(c.WeeklyAIContractError):
            c.prompt_contract_version(bad)
        assert not c.supports_prompt_contract(bad, 1)
    for bad in (True, False, 0, -1, 1.0, "1", None, 3):
        assert not c.supports_prompt_contract("weekly_games_select", bad)


def test_games_bundle_nested_schema_covers_raw_null_source_and_ai_variants():
    bundle = _games_bundle()
    schema = bundle["output_schema_json"]
    slots = schema["properties"]["outdoor_game_slots"]
    assert set(slots["required"]) == set(c.OUTDOOR_KEYS)
    assert slots["additionalProperties"] is False
    for key in c.OUTDOOR_KEYS:
        variants = slots["properties"][key]["oneOf"]
        assert [variant.get("type") for variant in variants] == ["null", "object", "object"]
    assert bundle["default_revision"] == 1
    assert bundle["contract_version"] == 2
    assert "source_handle" in bundle["guidance_defaults_json"]["instructions"]
    assert "basis_handles" in bundle["guidance_defaults_json"]["instructions"]

    raw_values = [
        _games_raw(),
        _games_raw(
            outdoor_game_slots={
                "collective_1": {"kind": "source", "source_handle": "m1"},
                "collective_2": None,
                "free_choice_1": None,
            },
            focus_area={"kind": "source", "source_handle": "p1"},
        ),
        _games_raw(
            outdoor_game_slots={
                "collective_1": None,
                "collective_2": {
                    "kind": "ai_supplement",
                    "name": "AI游戏",
                    "shared_objectives": "目标",
                    "guidance_points": "指导",
                    "focus_guidance": "重点",
                    "basis_handles": ["c1"],
                },
                "free_choice_1": None,
            },
            focus_area={
                "kind": "ai_supplement",
                "context_kind": "area",
                "area": "建构区",
                "name": "AI区域",
                "objectives": "目标",
                "guidance": "指导",
                "support_strategy": "支持",
                "basis_handles": ["c1"],
            },
        ),
    ]
    manifest = _manifest()
    for raw in raw_values:
        assert _schema_ok(schema, raw)
        c.parse_games_candidate(json.dumps(raw, ensure_ascii=False), server_manifest=manifest)

    extra = copy.deepcopy(raw_values[2])
    extra["outdoor_game_slots"]["collective_2"]["candidate_id"] = "leaked-id"
    assert not _schema_ok(schema, extra)
    with pytest.raises(c.WeeklyAIContractError):
        c.parse_games_candidate(json.dumps(extra, ensure_ascii=False), server_manifest=manifest)


def test_materials_bundle_nested_schema_covers_extracted_suggested_and_empty():
    bundle = _materials_bundle()
    schema = bundle["output_schema_json"]
    items = schema["properties"]["items"]
    assert items["maxItems"] == c.MAX_MATERIAL_ITEMS
    item_schemas = items["items"]["oneOf"]
    assert len(item_schemas) == 2
    for item_schema in item_schemas:
        assert set(item_schema["required"]) == {"text", "origin", "evidence_refs"}
        assert item_schema["additionalProperties"] is False
        evidence = item_schema["properties"]["evidence_refs"]
        assert evidence["items"]["additionalProperties"] is False
        assert set(evidence["items"]["required"]) == {
            "source_handle", "field_path", "start", "end", "quote"
        }
    assert bundle["default_revision"] == 1
    assert bundle["contract_version"] == 2
    instructions = bundle["guidance_defaults_json"]["instructions"]
    for term in ("extracted", "suggested", "Unicode", "20000"):
        assert term in instructions

    extracted = {
        "text": "彩纸",
        "origin": "extracted",
        "evidence_refs": [
            {
                "source_handle": "c1",
                "field_path": "guidance",
                "start": 3,
                "end": 5,
                "quote": "材料",
            }
        ],
    }
    suggested = {"text": "胶水", "origin": "suggested", "evidence_refs": []}
    manifest = _manifest("weekly_materials_generate")
    for raw in ({"items": []}, {"items": [extracted]}, {"items": [suggested]}):
        assert _schema_ok(schema, raw)
        c.parse_materials_candidate(json.dumps(raw, ensure_ascii=False), server_manifest=manifest)

    invalid = copy.deepcopy(extracted)
    invalid["evidence_refs"][0]["candidate_id"] = "leaked-id"
    assert not _schema_ok(schema, {"items": [invalid]})
    with pytest.raises(c.WeeklyAIContractError):
        c.parse_materials_candidate(
            json.dumps({"items": [invalid]}, ensure_ascii=False),
            server_manifest=manifest,
        )
    invalid = {"text": "胶水", "origin": "suggested", "evidence_refs": [extracted["evidence_refs"][0]]}
    assert not _schema_ok(schema, {"items": [invalid]})
    with pytest.raises(c.WeeklyAIContractError):
        c.parse_materials_candidate(
            json.dumps({"items": [invalid]}, ensure_ascii=False),
            server_manifest=manifest,
        )
