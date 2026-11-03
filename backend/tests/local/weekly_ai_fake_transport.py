"""Deterministic in-process fake transport and shared pure fixtures.

No socket, database, runtime or provider import.  Tests inject scripted
responses and inspect the exact payload that would have been sent.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from app.local import weekly_plan_content as _content


class FakeWeeklyTransport:
    def __init__(self, responses: list[str | bytes | BaseException]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def send(self, payload: Mapping[str, Any]) -> str | bytes:
        self.calls.append(copy.deepcopy(dict(payload)))
        if not self._responses:
            raise AssertionError("fake transport has no scripted response left")
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, bytes):
            return response
        if isinstance(response, str):
            return response
        return json.dumps(response, ensure_ascii=False, separators=(",", ":"))

    @property
    def remaining(self) -> int:
        return len(self._responses)


def fake_candidate(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _hash(ch: str = "a") -> str:
    return ch * 64


def make_snapshot(
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
            source = {
                "daily_plan_id": f"plan-{offset + 1}",
                "content_id": f"content-{offset + 1}",
                "content_version": version,
                "content_hash": _hash(source_hash),
                "morning_talk_topic": f"晨谈{offset + 1}",
                "group_activity_theme": f"活动{offset + 1}",
            }
            mornings = [
                {
                    "group_id": f"g-col-{offset + 1}",
                    "group_kind": "collective",
                    "games": [{"game_id": f"game-col-{offset + 1}", "name": name}],
                    "shared_objectives": "共同目标",
                    "guidance_points": "指导",
                    "focus_guidance": "重点指导",
                },
                {
                    "group_id": f"g-free-{offset + 1}",
                    "group_kind": "free_choice",
                    "games": [{"game_id": f"game-free-{offset + 1}", "name": "滚球"}],
                    "shared_objectives": "共同目标",
                    "guidance_points": "指导",
                    "focus_guidance": "重点指导",
                },
            ]
            posts = [
                {
                    "group_id": f"g-focus-{offset + 1}",
                    "context_kind": "area",
                    "area": "建构区",
                    "games": [
                        {"game_id": f"game-focus-{offset + 1}", "name": focus_name}
                    ],
                    "objectives": "区域目标",
                    "guidance": "区域指导",
                    "support_strategy": "支持策略",
                }
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
        "header": header
        or {
            "school_name": "测试园",
            "class_name": "小一班",
            "grade": "small",
            "header_teacher_names": ["张老师"],
            "caregiver_name": "保育员",
        },
        "source_context_hash": context_hash or _hash(contract_hash),
        "days": days,
    }


def source_candidate(snapshot: dict, category: str = "collective") -> dict:
    return next(
        item
        for item in _content.build_source_candidates(snapshot)
        if item["category"] == category
    )


def selector(candidate: dict) -> dict:
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


def selected_content(snapshot: dict | None = None) -> tuple[dict, dict]:
    snapshot = snapshot or make_snapshot()
    content = _content.new_content(snapshot)
    content = _content.apply_patch(
        content,
        {
            "outdoor_game_slots": {
                "collective_1": selector(source_candidate(snapshot, "collective")),
            },
            "focus_area": selector(source_candidate(snapshot, "focus")),
        },
        snapshot,
    )
    return snapshot, content


def make_raw(
    snapshot: dict,
    content: dict,
    *,
    guidance: str = "建构区材料",
    revision_id: str = "rev-1",
    revision_no: int = 2,
    coverage: str = "known",
) -> dict:
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
        "content_hash": _content.content_hash(content),
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
            "revision_id": revision_id,
            "revision_no": revision_no,
            "locations": [
                {
                    "kind": "area",
                    "name": "建构区",
                    "occurrence": 1,
                    "guidance": guidance,
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
                        **copy.deepcopy(source),
                        "group_activity_objectives": "活动目标",
                        "group_activity_process": "活动过程",
                    }
                    if source
                    else None
                ),
                "morning_groups": copy.deepcopy(day["morning_groups"]),
                "post_group_groups": copy.deepcopy(day["post_group_groups"]),
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
                "coverage": coverage,
            }
        )
    return raw
