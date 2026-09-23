"""No-DB unit tests for I2 configuration normalization helpers."""

import os
import unittest

os.environ.setdefault("APP_DISABLE_DOTENV", "1")

from app.services import config_service as cs


class NormalizationTests(unittest.TestCase):
    def test_school_name(self):
        self.assertEqual(cs.normalize_school_name("  阳光幼儿园 "), "阳光幼儿园")
        self.assertIsNone(cs.normalize_school_name(None))
        self.assertIsNone(cs.normalize_school_name("   "))
        with self.assertRaises(cs.ValidationError):
            cs.normalize_school_name("x" * 121)

    def test_class_name(self):
        self.assertEqual(cs.normalize_class_name(" 小一班 "), "小一班")
        with self.assertRaises(cs.ValidationError):
            cs.normalize_class_name("   ")
        with self.assertRaises(cs.ValidationError):
            cs.normalize_class_name("x" * 81)

    def test_grade(self):
        self.assertEqual(cs.normalize_grade("small"), "small")
        self.assertEqual(cs.normalize_grade("middle"), "middle")
        self.assertEqual(cs.normalize_grade("large"), "large")
        with self.assertRaises(ValueError):
            cs.normalize_grade("baby")

    def test_header_names(self):
        self.assertEqual(
            cs.normalize_header_names([" 张三 ", "李四"]),
            ["张三", "李四"],
        )
        self.assertEqual(cs.normalize_header_names([]), [])
        with self.assertRaises(cs.ValidationError):
            cs.normalize_header_names(["x"] * 21)
        with self.assertRaises(cs.ValidationError):
            cs.normalize_header_names(["  "])
        with self.assertRaises(cs.ValidationError):
            cs.normalize_header_names(["x" * 81])

    def test_caregiver_name(self):
        self.assertEqual(cs.normalize_caregiver_name(" 王阿姨 "), "王阿姨")
        self.assertIsNone(cs.normalize_caregiver_name(None))
        self.assertIsNone(cs.normalize_caregiver_name("  "))
        with self.assertRaises(cs.ValidationError):
            cs.normalize_caregiver_name("x" * 81)


if __name__ == "__main__":
    unittest.main()
