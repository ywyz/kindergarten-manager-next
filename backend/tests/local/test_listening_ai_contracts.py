"""Strict listening AI input/output contracts (extra/type/required fields)."""

from __future__ import annotations

import pytest

from app.local import listening_ai_contracts as contracts


def _note_input() -> dict:
    return {
        "schema_version": 1,
        "mode": "group_note",
        "domain": "health",
        "domain_label": "健康",
        "grade": "middle",
        "grade_label": "中班",
        "template_version": "v1",
        "template_sha256": "a" * 64,
        "group_position": 0,
        "work_date": "11月1日",
        "listening_text": "孩子说：我想画太阳。",
        "photo": None,
        "photo_only": False,
    }


def _domain_input() -> dict:
    return {
        "schema_version": 1,
        "mode": "domain_evaluate",
        "domain": "health",
        "domain_label": "健康",
        "grade": "middle",
        "grade_label": "中班",
        "template_version": "v1",
        "template_sha256": "a" * 64,
        "goal": "目标",
        "observation_date": None,
        "adult_count": None,
        "child_age": None,
        "observation_area": None,
        "groups": [
            {
                "position": 0,
                "work_date": "11月1日",
                "listening_text": "孩子说想画太阳。",
                "photo": None,
            }
        ],
        "items": [
            {
                "item_id": "health_1",
                "level1": "健康领域",
                "level2": "身心状况",
                "requirement": "要求",
                "standards": {"1": "一", "2": "二", "3": "三"},
            }
        ],
    }


def test_input_rejects_extra_and_coerced_types() -> None:
    base = _note_input()
    for mutate in (
        lambda value: value.__setitem__("child_name", "甲"),
        lambda value: value.__setitem__("schema_version", True),
        lambda value: value.__setitem__("group_position", True),
        lambda value: value.__setitem__("listening_text", 3),
    ):
        value = dict(base)
        mutate(value)
        with pytest.raises(contracts.ListeningAIContractError):
            contracts.validate_input("listening_note_draft", value)


def test_nested_photo_groups_items_are_strict() -> None:
    photo_value = _note_input()
    photo_value["photo"] = {
        "work_hash": "a" * 64,
        "format": "png",
        "width": 10,
        "height": 10,
        "orientation": None,
        "path": "C:/x",
    }
    with pytest.raises(contracts.ListeningAIContractError):
        contracts.validate_input("listening_note_draft", photo_value)

    domain = _domain_input()
    domain["groups"][0]["extra"] = 1
    with pytest.raises(contracts.ListeningAIContractError):
        contracts.validate_input("listening_domain_evaluate", domain)

    domain = _domain_input()
    domain["items"][0]["standards"] = {"1": "一", "2": "二"}
    with pytest.raises(contracts.ListeningAIContractError):
        contracts.validate_input("listening_domain_evaluate", domain)

    domain = _domain_input()
    domain["items"][0]["stars"] = 1
    with pytest.raises(contracts.ListeningAIContractError):
        contracts.validate_input("listening_domain_evaluate", domain)


def test_candidate_requires_explicit_fields_and_allows_null_star() -> None:
    with pytest.raises(contracts.ListeningAIContractError):
        contracts.validate_candidate("listening_domain_evaluate", {})
    with pytest.raises(contracts.ListeningAIContractError):
        contracts.validate_candidate(
            "listening_domain_evaluate",
            {
                "overall_evaluation": "",
                "support_strategy": "",
                "items": [{"item_id": "health_1", "basis": ""}],
            },
        )
    with pytest.raises(contracts.ListeningAIContractError):
        contracts.validate_candidate(
            "listening_domain_evaluate",
            {
                "overall_evaluation": "",
                "support_strategy": "",
                "items": [{"item_id": "health_1", "stars": True, "basis": ""}],
            },
        )
    value = contracts.validate_candidate(
        "listening_domain_evaluate",
        {
            "overall_evaluation": "",
            "support_strategy": "",
            "items": [{"item_id": "health_1", "stars": None, "basis": ""}],
        },
    )
    assert value["items"][0]["stars"] is None
    with pytest.raises(contracts.ListeningAIContractError):
        contracts.validate_candidate(
            "listening_domain_evaluate",
            {
                "overall_evaluation": "",
                "support_strategy": "",
                "items": [
                    {"item_id": "health_1", "stars": None, "basis": ""},
                    {"item_id": "health_1", "stars": 1, "basis": ""},
                ],
            },
        )
