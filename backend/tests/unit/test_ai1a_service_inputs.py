"""AI 1A unit tests: real service entry inputs (R1), internal-object
serialization defenses (R4) and exported-contract schema accuracy (R5).

Pure unit (no DB, no service process); synthetic material only.
"""

from __future__ import annotations

import dataclasses
import os
import unittest

os.environ["APP_DISABLE_DOTENV"] = "1"

from fastapi.encoders import jsonable_encoder  # noqa: E402

from app.services.ai_config_service import (  # noqa: E402
    AiConfigValidationError,
    AiConfigView,
    DecryptedConfig,
    SECRET_UNSET,
    save_config,
)
from app.services.ai_prompt_registry import (  # noqa: E402
    FieldViolation,
    TASK_TYPES,
    get_registry,
)
from app.services.auth_service import AuthSnapshot  # noqa: E402
from app.services import prompt_service  # noqa: E402


def snap(account_id: str = "acc_u", role: str = "teacher") -> AuthSnapshot:
    return AuthSnapshot(
        account_id=account_id,
        role=role,
        auth_version=1,
        session_id="sesx",
        is_active=True,
        password_hash="x",
    )


class R1ServiceInputTest(unittest.TestCase):
    def test_task_list_resolves(self):
        self.assertEqual(len(prompt_service.get_task_types()), 7)
        self.assertEqual(
            prompt_service.get_task_types(), TASK_TYPES
        )

    def test_task_status_shape_available_for_service(self):
        """TaskStatus 是服务内部状态形状；真实 list_tasks 的库级覆盖位于
        集成 S4（不在此冒充数据库入口）。"""
        self.assertTrue(hasattr(prompt_service, "TaskStatus"))

    def test_empty_patch_rejected_before_db(self):
        with self.assertRaises(prompt_service.FieldViolation):
            prompt_service.save_guidance(
                None, snap(), "acc_u", "daily_lesson_split",
                {}, 1,
            )
        with self.assertRaises(prompt_service.FieldViolation):
            prompt_service.save_guidance(
                None, snap(), "acc_u", "daily_lesson_split",
                "not a dict", 1,
            )

    def test_empty_accepted_fields_and_bad_versions_rejected(self):
        with self.assertRaises(prompt_service.FieldViolation):
            prompt_service.accept_default(
                None, snap(), "acc_u", "daily_lesson_split",
                1, [], 1,
            )
        with self.assertRaises(prompt_service.FieldViolation):
            prompt_service.reject_default(
                None, snap(), "acc_u", "daily_lesson_split",
                0, 1,
            )
        with self.assertRaises(prompt_service.FieldViolation):
            prompt_service.reject_default(
                None, snap(), "acc_u", "daily_lesson_split",
                True, 1,  # bool 不是 int 版本号
            )

    def test_unknown_task_rejected(self):
        from app.services.ai_prompt_registry import UnknownTaskType

        with self.assertRaises(UnknownTaskType):
            prompt_service.initialize_task(
                None, snap(), "acc_u", "no_such_task"
            )
        with self.assertRaises(UnknownTaskType):
            prompt_service.update_default(
                None, snap(), "no_such_task", {"x": "y"}, 1
            )

    def test_config_secret_null_empty_and_protocol(self):
        from app.services.ai_config_url import BaseUrlInvalid

        with self.assertRaises(AiConfigValidationError):
            save_config(
                None, snap(), 0, "chat_completions_v1",
                "https://api.a.com/v1", "m", secret=None,
            )
        with self.assertRaises(AiConfigValidationError):
            save_config(
                None, snap(), 0, "chat_completions_v1",
                "https://api.a.com/v1", "m", secret="",
            )
        with self.assertRaises(AiConfigValidationError):
            save_config(
                None, snap(), 0, "no_such_protocol",
                "https://api.a.com/v1", "m", secret="s",
            )
        with self.assertRaises(BaseUrlInvalid):
            save_config(
                None, snap(), 0, "chat_completions_v1",
                "http://api.a.com/v1", "m", secret="s",
            )


class R4SerializationTest(unittest.TestCase):
    def _object(self) -> DecryptedConfig:
        return DecryptedConfig(
            account_id="acc_u",
            config_version=1,
            protocol_id="chat_completions_v1",
            base_url="https://api.vendor.com/v1",
            model="model-x",
            secret="SYNTHETIC-S3CRET",
        )

    def test_slots_and_no_dict(self):
        obj = self._object()
        self.assertFalse(hasattr(obj, "__dict__"))
        with self.assertRaises(TypeError):
            vars(obj)  # vars() 转换拒绝（无 __dict__）

    def test_iter_and_dict_helpers_rejected(self):
        obj = self._object()
        with self.assertRaises(TypeError):
            list(obj)
        with self.assertRaises(TypeError):
            dict(obj)
        with self.assertRaises(TypeError):
            obj["secret"]
        with self.assertRaises(TypeError):
            obj.keys()

    def test_dataclasses_asdict_rejected(self):
        obj = self._object()
        with self.assertRaises(TypeError):
            dataclasses.asdict(obj)

    def test_jsonable_encoder_rejected(self):
        obj = self._object()
        with self.assertRaises(Exception):
            jsonable_encoder(obj)
        # 即便被通用编码吞掉异常，也绝不产生含明文的映射。
        try:
            encoded = jsonable_encoder(obj)
        except Exception:
            encoded = None
        if encoded is not None:
            self.assertNotIn("SYNTHETIC-S3CRET", str(encoded))

    def test_repr_pickle_copy_no_plaintext(self):
        import copy
        import pickle

        obj = self._object()
        self.assertNotIn("SYNTHETIC-S3CRET", repr(obj))
        with self.assertRaises(TypeError):
            pickle.dumps(obj)
        with self.assertRaises(TypeError):
            copy.copy(obj)
        with self.assertRaises(TypeError):
            copy.deepcopy(obj)

    def test_reveal_only_via_explicit_method(self):
        obj = self._object()
        self.assertEqual(obj.reveal_secret(), "SYNTHETIC-S3CRET")
        with self.assertRaises(TypeError):
            obj.account_id = "changed"  # 不可变
        with self.assertRaises(TypeError):
            del obj.account_id

    def test_escape_shotgun_json_and_vars_no_plaintext(self):
        obj = self._object()
        import json as j

        self.assertNotIn("SYNTHETIC-S3CRET", j.dumps(jable := {
            k: getattr(obj, k)
            for k in obj.__slots__
            if k != "_secret"
        }, ensure_ascii=False))
        del jable

    def test_ai_config_view_serialization_clean(self):
        view = AiConfigView(
            account_id="acc_u",
            head_exists=True,
            version=2,
            protocol_id="chat_completions_v1",
            base_url="https://api.vendor.com/v1",
            model="model-x",
            has_secret=True,
            ready=True,
            ready_reason=None,
        )
        as_dict = jsonable_encoder(view)
        self.assertNotIn("has_secret_plain", as_dict)
        self.assertNotIn("secret", as_dict)
        self.assertTrue(as_dict["ready"])
        self.assertEqual(dataclasses.asdict(view)["version"], 2)
        self.assertNotIn("secret", [
            k for k in dataclasses.asdict(view)
        ])


class R5SchemaExportTest(unittest.TestCase):
    def test_split_required_six_no_defaults(self):
        schema = get_registry("daily_lesson_split").output_model.model_json_schema()
        self.assertEqual(schema["required"], ["group_activity"])
        group = schema["$defs"]["DailyLessonSplitGroupActivity"]
        self.assertEqual(
            sorted(group["required"]),
            ["difficult_points", "key_points", "objectives",
             "preparation", "process", "theme"],
        )
        for field in group["properties"].values():
            self.assertNotIn("default", field)
            self.assertNotIn("anyOf", field)

    def test_weekly_games_five_required_slots_nullable(self):
        import json as _json

        schema = get_registry("weekly_games").output_model.model_json_schema()
        self.assertEqual(
            sorted(schema["required"]),
            ["collective_1", "collective_2", "focus_area",
             "free_choice_1", "insufficient_supplements"],
        )
        supplement = schema["$defs"]["InsufficientSupplement"]
        self.assertEqual(
            supplement["properties"]["target_slot"]["enum"],
            ["collective_1", "collective_2", "free_choice_1", "focus_area"],
        )
        # 部分槽 schema 准确表达“可为显式 null”。
        slot = _json.loads(_json.dumps(schema["properties"]["collective_1"]))
        self.assertIn('"null"', _json.dumps(schema))
        if "anyOf" in slot:
            self.assertIn({"type": "null"}, slot["anyOf"])

    def test_other_activities_sections_not_null_enums(self):
        import json

        schema = get_registry(
            "daily_other_activities"
        ).output_model.model_json_schema()
        section_types = {
            k: v.get("type") or ("$ref" if "$ref" in v else None)
            for k, v in schema["properties"].items()
        }
        self.assertEqual(section_types["morning_games"], "array")
        self.assertEqual(section_types["post_group_games"], "array")
        self.assertEqual(section_types["afternoon_outdoor"], "$ref")
        self.assertEqual(section_types["morning_talk"], "$ref")
        self.assertNotIn('"anyOf"', json.dumps(schema["properties"]))
        self.assertEqual(
            schema["$defs"]["MorningGameGroup"]["properties"]["group_kind"]["enum"],
            ["collective", "free_choice"],
        )
        # 显式 null 在运行时仍拒绝；schema 无 null 联合。
        with self.assertRaises(Exception):
            get_registry("daily_other_activities").output_model.model_validate(
                {"afternoon_outdoor": None}
            )

    def test_material_item_requireds_and_enums(self):
        schema = get_registry("weekly_materials").output_model.model_json_schema()
        item = schema["$defs"]["MaterialItem"]
        self.assertEqual(
            sorted(item["required"]), ["evidence_refs", "origin", "text"]
        )
        self.assertEqual(
            item["properties"]["origin"]["enum"], ["extracted", "suggested"]
        )
        self.assertEqual(item["properties"]["text"]["maxLength"], 300)
        evidence = schema["$defs"]["MaterialEvidenceRef"]
        self.assertEqual(evidence["properties"]["quote"]["maxLength"], 2000)
        self.assertEqual(schema["properties"]["items"]["maxItems"], 100)

    def test_no_shared_default_state(self):
        # 两次校验互不共享列表状态；默认不使用可变类级默认值。
        registry = get_registry("weekly_games")
        first = registry.output_model.model_validate({
            "collective_1": None, "collective_2": None, "free_choice_1": None,
            "focus_area": None, "insufficient_supplements": [],
        })
        second = registry.output_model.model_validate({
            "collective_1": {"source_ref": "s", "game_id": "g",
                             "group_id": "gr", "name": "n"},
            "collective_2": None, "free_choice_1": None,
            "focus_area": None, "insufficient_supplements": [],
        })
        self.assertNotEqual(first.collective_1, second.collective_1)
        del second
        self.assertIsNone(first.collective_1)

    def test_enum_literals_disallow_invalid(self):
        registry = get_registry("daily_other_activities")
        with self.assertRaises(Exception):
            registry.output_model.model_validate({
                "morning_games": [{
                    "group_kind": "other", "games": [{"name": "a"}],
                }],
            })


if __name__ == "__main__":
    unittest.main()
