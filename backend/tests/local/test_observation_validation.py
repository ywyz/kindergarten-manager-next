"""E01 pure field, validation-layer and aggregate-hash tests."""

from __future__ import annotations

import unittest

from app.local.observation_validation import (
    EVALUATION_KEYS,
    ObservationValidationError,
    aggregate_hash,
    ai_readiness,
    analyze_payload,
    is_empty_record,
    missing_fields,
    normalize_payload,
)


class ObservationValidationTests(unittest.TestCase):
    def _payload(self, **overrides):
        base = {
            "record_type": "public",
            "observation_date": "2026-10-26",
            "start_time": "09:00",
            "end_time": "09:30",
            "school_name": " 示范园 ",
            "class_name": "中一班",
            "observer_name": "王老师",
            "adult_count": 1,
            "child_count": 2,
            "age_years": 5,
            "subjects": [{"name": "小明"}, {"name": "小红"}, {"name": "小明"}],
            "environment": "建构区",
            "observation_goal": "观察合作",
            "observation_process": "两人商量搭建。",
            "support_strategy": "提供更多连接件。",
            "analysis_evaluation": {
                "health": "",
                "language": "能表达",
                "social": "能合作",
                "science": "",
                "arts": "",
            },
        }
        base.update(overrides)
        return base

    def test_flat_payload_and_subject_order_are_preserved(self):
        payload = normalize_payload(self._payload())
        self.assertEqual(payload["school_name"], "示范园")
        self.assertEqual(
            payload["subjects"],
            [{"name": "小明"}, {"name": "小红"}, {"name": "小明"}],
        )
        self.assertEqual(tuple(payload["analysis_evaluation"]), EVALUATION_KEYS)
        self.assertEqual(payload["age_years"], 5)

    def test_missing_fixed_five_domains_are_filled_not_dropped(self):
        payload = normalize_payload(self._payload(analysis_evaluation=None))
        self.assertEqual(
            payload["analysis_evaluation"], {key: "" for key in EVALUATION_KEYS}
        )

    def test_strict_non_negative_integers_reject_bool_float_and_string(self):
        for value in (True, 1.0, "1", -1):
            with self.subTest(value=value):
                with self.assertRaises(ObservationValidationError):
                    normalize_payload(self._payload(age_years=value))

    def test_illegal_time_and_date_are_rejected(self):
        with self.assertRaises(ObservationValidationError):
            normalize_payload(self._payload(start_time="9:00"))
        with self.assertRaises(ObservationValidationError):
            normalize_payload(self._payload(observation_date="2026-02-30"))

    def test_unknown_payload_and_evaluation_keys_are_rejected(self):
        with self.assertRaises(ObservationValidationError):
            normalize_payload(self._payload(extra="x"))
        with self.assertRaises(ObservationValidationError):
            normalize_payload(
                self._payload(analysis_evaluation={"health": "", "unknown": ""})
            )

    def test_client_term_snapshot_is_rejected_and_service_snapshot_is_single(self):
        with self.assertRaises(ObservationValidationError):
            normalize_payload(
                self._payload(
                    term_id="term1",
                    term_snapshot={
                        "term_id": "term1",
                        "name": "秋",
                        "start_date": "2026-09-01",
                        "end_date": "2026-09-30",
                    },
                )
            )
        payload = normalize_payload(
            self._payload(term_id="term1"),
            term_snapshot={
                "term_id": "term1",
                "name": "秋",
                "start_date": "2026-09-01",
                "end_date": "2026-09-30",
            },
        )
        self.assertEqual(payload["term_snapshot"]["term_id"], "term1")

    def test_contradictions_are_warnings_not_hard_blocks(self):
        analysis = analyze_payload(
            self._payload(child_count=1, end_time="08:00")
        )
        codes = {item["code"] for item in analysis.warnings}
        self.assertIn("subjects_exceed_child_count", codes)
        self.assertIn("end_before_start", codes)
        self.assertEqual(analysis.payload["child_count"], 1)

    def test_missing_and_ai_readiness_are_separate_from_save(self):
        payload = normalize_payload(
            self._payload(
                observation_date=None,
                school_name=None,
                class_name=None,
                observer_name=None,
                age_years=None,
                subjects=[],
                environment=None,
                observation_goal=None,
                observation_process=None,
                support_strategy=None,
            )
        )
        missing = missing_fields(payload)
        self.assertIn("age_years", missing)
        self.assertIn("subjects", missing)
        self.assertIn("school_name", missing)
        self.assertIn("class_name", missing)
        self.assertIn("observer_name", missing)
        ready, required = ai_readiness(payload, valid_photo_count=0)
        self.assertFalse(ready)
        self.assertEqual(set(required), {"subjects", "age_years", "environment", "photos"})

    def test_empty_record_exact_definition(self):
        empty = normalize_payload(
            self._payload(
                observation_goal=None,
                observation_process=None,
                support_strategy=None,
                analysis_evaluation=None,
            )
        )
        self.assertTrue(is_empty_record(empty, valid_photo_count=0))
        self.assertFalse(is_empty_record(empty, valid_photo_count=1))
        self.assertFalse(
            is_empty_record(
                normalize_payload(self._payload(observation_process="有正文")),
                valid_photo_count=0,
            )
        )
        self.assertFalse(
            is_empty_record(
                normalize_payload(
                    self._payload(
                        observation_goal=None,
                        observation_process=None,
                        support_strategy=None,
                        analysis_evaluation={"health": "证据不足"},
                    )
                ),
                valid_photo_count=0,
            )
        )

    def test_aggregate_hash_is_single_payload_plus_ordered_original_manifest(self):
        payload = normalize_payload(
            self._payload(term_id="term1"),
            term_snapshot={
                "term_id": "term1",
                "name": "秋",
                "start_date": "2026-09-01",
                "end_date": "2026-09-30",
            },
        )
        manifest = [
            {
                "asset_id": "a1",
                "content_hash": "b" * 64,
                "format": "jpeg",
                "width": 100,
                "height": 80,
                "orientation": 1,
                "sort_order": 0,
                "caption": "说明一",
            },
            {
                "asset_id": "a2",
                "content_hash": "c" * 64,
                "format": "png",
                "width": 90,
                "height": 70,
                "orientation": 6,
                "sort_order": 1,
                "caption": None,
            },
        ]
        first = aggregate_hash(payload, manifest)
        self.assertEqual(first, aggregate_hash(payload, list(manifest)))
        changed_order = [
            dict(manifest[1], sort_order=0),
            dict(manifest[0], sort_order=1),
        ]
        self.assertNotEqual(first, aggregate_hash(payload, changed_order))
        changed_caption = [dict(manifest[0], caption="说明二"), manifest[1]]
        self.assertNotEqual(first, aggregate_hash(payload, changed_caption))
        with self.assertRaises(ObservationValidationError):
            aggregate_hash(payload, [dict(manifest[0], work_hash="d" * 64)])
        self.assertNotIn("term_snapshot", manifest[0])

    def test_mirrored_orientation_and_manifest_identity_are_validated(self):
        payload = normalize_payload(self._payload())
        base = {
            "asset_id": "a1",
            "content_hash": "A" * 64,
            "format": "jpeg",
            "width": 10,
            "height": 10,
            "orientation": 2,
            "sort_order": 0,
            "caption": None,
        }
        # Mirrored EXIF orientation 2/4/5/7 is legal; hash normalizes case.
        first = aggregate_hash(payload, [base])
        self.assertEqual(first, aggregate_hash(payload, [dict(base, content_hash="a" * 64)]))
        for orientation in (2, 4, 5, 7):
            with self.subTest(orientation=orientation):
                self.assertIsNotNone(
                    aggregate_hash(payload, [dict(base, orientation=orientation)])
                )
        with self.assertRaises(ObservationValidationError):
            aggregate_hash(payload, [dict(base, orientation=9)])
        with self.assertRaises(ObservationValidationError):
            aggregate_hash(payload, [base, dict(base, sort_order=1)])
        with self.assertRaises(ObservationValidationError):
            aggregate_hash(payload, [dict(base, content_hash="not-a-sha")])
        with self.assertRaises(ObservationValidationError):
            aggregate_hash(payload, [base, dict(base, asset_id="a2", sort_order=0)])

    def test_unknown_keys_do_not_echo_sensitive_key_text(self):
        with self.assertRaises(ObservationValidationError) as caught:
            normalize_payload(
                self._payload(**{"小明-家庭住址-C:/secret": "不应回显"})
            )
        self.assertEqual(
            caught.exception.details, {"field": "payload", "unknown_field_count": 1}
        )
        self.assertNotIn("小明", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))
        with self.assertRaises(ObservationValidationError) as caught:
            aggregate_hash(
                normalize_payload(self._payload()),
                [
                    {
                        "asset_id": "a1",
                        "content_hash": "b" * 64,
                        "format": "jpeg",
                        "width": 10,
                        "height": 10,
                        "orientation": 1,
                        "sort_order": 0,
                        "caption": None,
                        "儿童姓名": "不应回显",
                    }
                ],
            )
        self.assertEqual(
            caught.exception.details,
            {"field": "photo_manifest[0]", "unknown_field_count": 1},
        )
        self.assertNotIn("儿童姓名", str(caught.exception))

    def test_no_new_business_quotas_for_age_names_or_text(self):
        payload = normalize_payload(
            self._payload(
                age_years=999,
                subjects=[{"name": f"幼儿{i}"} for i in range(150)],
                observation_process="长" * 20000,
            )
        )
        self.assertEqual(payload["age_years"], 999)
        self.assertEqual(len(payload["subjects"]), 150)
        self.assertEqual(len(payload["observation_process"]), 20000)

    def test_photo_manifest_rejects_duplicate_order_and_bad_format(self):
        with self.assertRaises(ObservationValidationError):
            aggregate_hash(
                normalize_payload(self._payload()),
                [
                    {
                        "asset_id": "a1",
                        "content_hash": "b" * 64,
                        "format": "jpeg",
                        "width": 10,
                        "height": 10,
                        "orientation": 1,
                        "sort_order": 0,
                        "caption": None,
                    },
                    {
                        "asset_id": "a2",
                        "content_hash": "c" * 64,
                        "format": "jpeg",
                        "width": 10,
                        "height": 10,
                        "orientation": 1,
                        "sort_order": 0,
                        "caption": None,
                    },
                ],
            )
        with self.assertRaises(ObservationValidationError):
            aggregate_hash(
                normalize_payload(self._payload()),
                [
                    {
                        "asset_id": "a1",
                        "content_hash": "b" * 64,
                        "format": "tiff",
                        "width": 10,
                        "height": 10,
                        "orientation": 1,
                        "sort_order": 0,
                        "caption": None,
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
