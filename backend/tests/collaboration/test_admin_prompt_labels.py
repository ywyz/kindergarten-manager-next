"""Authoritative prompt-release task/field display labels.

The Chinese display labels live beside the package catalogue in
``prompt_release_service`` and are validated against it at catalogue build
time; the API layer only consumes them.  Unknown future identifiers fall
back to the raw key, which stays recognizable for review, and the deployed
admin page additionally carries a presentation-only fallback so an older
backend without the label fields still renders Chinese names.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import Response

from app.collaboration import prompt_release_api, prompt_release_service
from app.local.prompt_package import (
    PACKAGE_OPEN_GUIDANCE_FIELDS,
    PACKAGE_OPEN_TASK_TYPES,
)

BACKEND = Path(__file__).resolve().parents[2]


class PromptLabelAuthorityTests(unittest.TestCase):
    def test_labels_are_defined_once_beside_the_catalogue(self):
        api_source = (
            BACKEND / "app" / "collaboration" / "prompt_release_api.py"
        ).read_text(encoding="utf-8")
        service_source = (
            BACKEND / "app" / "collaboration" / "prompt_release_service.py"
        ).read_text(encoding="utf-8")
        # The API layer no longer keeps its own label copies.
        self.assertNotIn("TASK_LABELS", api_source)
        self.assertNotIn("FIELD_LABELS", api_source)
        self.assertIn("TASK_DISPLAY_LABELS", service_source)
        self.assertIn("FIELD_DISPLAY_LABELS", service_source)
        # It consumes the single authoritative source.
        self.assertIn("task_display_label", api_source)
        self.assertIn("field_display_label", api_source)
        # The catalogue build refuses a label gap for any opened identifier.
        self.assertIn(
            "prompt release display labels incomplete", service_source
        )

    def test_every_open_task_and_field_has_a_chinese_label(self):
        for task_type in PACKAGE_OPEN_TASK_TYPES:
            label = prompt_release_service.task_display_label(task_type)
            self.assertNotEqual(label, task_type)
            self.assertNotEqual(label, "其他任务")
            for field_name in PACKAGE_OPEN_GUIDANCE_FIELDS[task_type]:
                field_label = prompt_release_service.field_display_label(
                    field_name
                )
                self.assertNotEqual(field_label, field_name)
                self.assertNotEqual(field_label, "其他字段")

    def test_unknown_future_keys_fall_back_to_the_raw_key(self):
        for task_type in ("future_task_x", "legacy_task"):
            self.assertEqual(
                prompt_release_service.task_display_label(task_type),
                task_type,
            )
            self.assertEqual(
                prompt_release_api.task_display_label(task_type),
                task_type,
            )
        for field_name in ("future_field_y", "legacy_field"):
            self.assertEqual(
                prompt_release_service.field_display_label(field_name),
                field_name,
            )
            self.assertEqual(
                prompt_release_api.field_display_label(field_name),
                field_name,
            )

    def test_catalogue_build_fails_loudly_on_a_missing_label(self):
        catalog = prompt_release_service._catalog
        try:
            catalog.cache_clear()
            with patch.dict(
                prompt_release_service.TASK_DISPLAY_LABELS,
                {
                    task: "标签"
                    for task in PACKAGE_OPEN_TASK_TYPES
                    if task != "weekly_games_select"
                },
                clear=True,
            ):
                with self.assertRaises(RuntimeError) as raised:
                    catalog()
                self.assertIn("weekly_games_select", str(raised.exception))
                self.assertIn("display labels incomplete", str(raised.exception))
            catalog.cache_clear()
            with patch.dict(
                prompt_release_service.FIELD_DISPLAY_LABELS,
                {"text": "文字内容"},
                clear=True,
            ):
                with self.assertRaises(RuntimeError) as raised:
                    catalog()
                self.assertIn(
                    "listening_note_draft.uncertainties",
                    str(raised.exception),
                )
        finally:
            catalog.cache_clear()

    def test_workspace_route_labels_keep_real_identifiers(self):
        workspace = {
            "editable": [
                {
                    "task_type": "daily_lesson_split",
                    "fields": {
                        "theme": "主题文字",
                        "legacy_key": "旧字段",
                    },
                }
            ],
            "drafts": [],
            "releases": [],
            "latest": {"preview": None, "stable": None},
        }
        with patch.object(
            prompt_release_api, "_require_configured", return_value=None
        ), patch.object(
            prompt_release_api, "get_workspace", return_value=workspace
        ):
            result = prompt_release_api.read_prompt_releases(
                Response(), session=None, _principal=None
            )
        item = result.editable[0]
        self.assertEqual(item.task_type, "daily_lesson_split")
        self.assertEqual(item.task_label, "日计划·教案拆分")
        self.assertEqual(item.fields["theme"], "主题文字")
        self.assertEqual(item.fields["legacy_key"], "旧字段")
        self.assertEqual(item.field_labels["theme"], "活动主题")
        self.assertEqual(item.field_labels["legacy_key"], "legacy_key")

    def test_admin_page_keeps_real_keys_and_a_fallback_registry(self):
        page = (
            BACKEND / "app" / "collaboration" / "admin_page.html"
        ).read_text(encoding="utf-8")
        # Options always show the Chinese label together with the real
        # identifier, and unknown keys render as themselves.
        self.assertIn("function optionText(label, key)", page)
        self.assertIn('label + "（" + key + "）"', page)
        self.assertIn("return taskType;", page)
        self.assertIn("return fieldName;", page)
        # A deployed backend without the label fields still gets Chinese
        # names from the page's presentation-only fallback copies.
        self.assertIn("TASK_LABEL_FALLBACK", page)
        self.assertIn("FIELD_LABEL_FALLBACK", page)
        self.assertIn('game_observation_generate: "游戏观察·记录生成"', page)
        self.assertIn('observation_goal: "观察目标"', page)
        # The generic fallbacks are gone from the page.
        self.assertNotIn('"其他任务"', page)
        self.assertNotIn('"其他字段"', page)


if __name__ == "__main__":
    unittest.main()
