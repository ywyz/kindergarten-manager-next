"""Pure listening observation-month and work-date rules (no database)."""

from __future__ import annotations

import unittest
from datetime import date

from types import SimpleNamespace

from app.local import listening_dates, listening_service


class DateParsingTests(unittest.TestCase):
    def test_only_strict_canonical_values_are_interpreted(self) -> None:
        self.assertEqual(listening_dates.parse_month("2026-11"), (2026, 11))
        self.assertEqual(
            listening_dates.parse_date("2027-01-31"), date(2027, 1, 31)
        )
        for value in (
            "11月1—3日",
            "上午观察",
            "2026-1",
            "2026-11-31",
            "٢٠٢٧-٠٢",
            "２０２７-０２",
            "",
            None,
        ):
            self.assertIsNone(listening_dates.parse_month(value))
        for value in (
            "11月1—3日",
            "2026-02-30",
            "2026/11/01",
            "٢٠٢٧-٠٢-٠٧",
            "２０２７-０２-０７",
            "",
            None,
        ):
            self.assertIsNone(listening_dates.parse_date(value))

    def test_cross_year_and_partial_term_months(self) -> None:
        start, end = date(2026, 9, 15), date(2027, 2, 10)
        self.assertEqual(
            listening_dates.term_month_text(start, end),
            ("2026-09", "2027-02"),
        )
        september = listening_dates.month_intersection(
            (2026, 9), start, end
        )
        self.assertEqual(september, (date(2026, 9, 15), date(2026, 9, 30)))
        january = listening_dates.month_intersection((2027, 1), start, end)
        self.assertEqual(january, (date(2027, 1, 1), date(2027, 1, 31)))
        february = listening_dates.month_intersection(
            (2027, 2), start, end
        )
        self.assertEqual(february, (date(2027, 2, 1), date(2027, 2, 10)))
        self.assertIsNone(
            listening_dates.month_intersection((2026, 8), start, end)
        )


class DateRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = date(2026, 9, 1)
        self.end = date(2027, 1, 31)
        self.groups = [
            ("g0", 0, "11月1—3日"),
            ("g1", 1, "2026-12-20"),
            ("g2", 2, "2027-01-15"),
        ]

    def _validate(self, **overrides):
        values = dict(
            old_observation="11月1—3日",
            new_observation="11月1—3日",
            observation_changed=False,
            groups=self.groups,
            patch_work_dates={},
            term_start=self.start,
            term_end=self.end,
        )
        values.update(overrides)
        return listening_dates.validate_save_dates(**values)

    def test_unrelated_legacy_save_is_not_blocked(self) -> None:
        self.assertEqual(self._validate(), [])
        self.assertEqual(
            self._validate(
                old_observation="٢٠٢٧-٠٢",
                new_observation="٢٠٢٧-٠٢",
            ),
            [],
        )

    def test_unicode_digit_values_are_not_canonical(self) -> None:
        with self.assertRaises(ValueError):
            self._validate(
                observation_changed=True,
                new_observation="٢٠٢٧-٠٢",
            )
        issues = self._validate(
            observation_changed=True,
            new_observation="2026-12",
            groups=[("g-a", 0, None)],
            patch_work_dates={"g-a": "٢٠٢٧-٠٢-٠٧"},
        )
        self.assertEqual(len(issues), 1)
        self.assertIn("不是规范日期", issues[0].reason)

    def test_month_change_flags_legacy_and_out_of_range_groups(self) -> None:
        issues = self._validate(
            observation_changed=True,
            new_observation="2027-01",
        )
        self.assertEqual([issue.group_id for issue in issues], ["g0", "g1"])
        self.assertIn("原作品日期不是规范日期", issues[0].reason)
        self.assertIn("交集", issues[1].reason)

    def test_month_change_allows_in_range_and_cleared_groups(self) -> None:
        issues = self._validate(
            observation_changed=True,
            new_observation="2027-01",
            patch_work_dates={"g0": "", "g1": "2027-01-05"},
        )
        self.assertEqual(issues, [])

    def test_changed_work_date_requires_observation_month(self) -> None:
        issues = self._validate(
            patch_work_dates={"g1": "2026-12-21"},
        )
        self.assertEqual(len(issues), 1)
        self.assertIn("请先选择规范观察月份", issues[0].reason)

    def test_changed_canonical_work_date_is_checked(self) -> None:
        issues = self._validate(
            old_observation="2026-12",
            new_observation="2026-12",
            patch_work_dates={"g1": "2026-12-21"},
        )
        self.assertEqual(issues, [])

    def test_observation_month_outside_term_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self._validate(
                observation_changed=True,
                new_observation="2026-08",
            )
        with self.assertRaises(ValueError):
            self._validate(
                observation_changed=True,
                new_observation="2027-02",
            )

    def test_clearing_observation_preserves_legacy_work_dates(self) -> None:
        issues = self._validate(
            observation_changed=True,
            new_observation=None,
        )
        self.assertEqual(issues, [])

    def test_cross_year_month_switch(self) -> None:
        groups = [
            ("g0", 0, "2026-12-31"),
            ("g1", 1, "2027-01-01"),
            ("g2", 2, "2027-01-31"),
        ]
        self.assertEqual(
            self._validate(
                old_observation="2026-12",
                new_observation="2027-01",
                observation_changed=True,
                groups=groups,
            )[0].group_id,
            "g0",
        )
        self.assertEqual(
            self._validate(
                old_observation="2026-12",
                new_observation="2027-01",
                observation_changed=True,
                groups=groups,
                patch_work_dates={"g0": "2027-01-01"},
            ),
            [],
        )


class ServiceDateValidationTests(unittest.TestCase):
    def test_service_validation_reports_group_specific_issues(self) -> None:
        domain = SimpleNamespace(observation_date_text="11月1—3日")
        groups = [
            SimpleNamespace(
                id="g0", position=0, work_date_text="11月1—3日"
            ),
            SimpleNamespace(
                id="g1", position=1, work_date_text="2026-12-20"
            ),
            SimpleNamespace(
                id="g2", position=2, work_date_text=None
            ),
        ]
        term = SimpleNamespace(
            start_date=date(2026, 9, 1), end_date=date(2027, 1, 31)
        )
        with self.assertRaises(listening_service.ListeningDateRuleError) as raised:
            listening_service._validate_date_changes(
                domain,
                groups,
                {"observation_date": "2027-01"},
                term,
            )
        self.assertIn("第 1 组", str(raised.exception))
        self.assertIn("第 2 组", str(raised.exception))
        issues = raised.exception.details["issues"]
        self.assertEqual([item["group_id"] for item in issues], ["g0", "g1"])

    def test_service_unrelated_save_and_valid_change(self) -> None:
        domain = SimpleNamespace(observation_date_text="11月1—3日")
        groups = [
            SimpleNamespace(id="g0", position=0, work_date_text="旧文字"),
            SimpleNamespace(id="g1", position=1, work_date_text="2026-12-20"),
            SimpleNamespace(id="g2", position=2, work_date_text=None),
        ]
        term = SimpleNamespace(
            start_date=date(2026, 9, 1), end_date=date(2027, 1, 31)
        )
        listening_service._validate_date_changes(
            domain, groups, {"goal": "只改目标"}, term
        )
        listening_service._validate_date_changes(
            domain,
            groups,
            {
                "observation_date": "2027-01",
                "groups": [
                    {"group_id": "g0", "work_date": ""},
                    {"group_id": "g1", "work_date": "2027-01-02"},
                ],
            },
            term,
        )

    def test_save_domain_calls_date_validation(self) -> None:
        source = (
            __import__("pathlib").Path(__file__).resolve().parents[2]
            / "app"
            / "local"
            / "listening_service.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_validate_date_changes(", source)
        self.assertIn("ListeningDateRuleError", source)


if __name__ == "__main__":
    unittest.main()
