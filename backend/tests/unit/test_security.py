import unittest

from app import security


class PasswordHashTests(unittest.TestCase):
    def test_hash_and_verify(self):
        h = security.hash_password("correct-horse-battery-staple")
        self.assertTrue(security.verify_password("correct-horse-battery-staple", h))
        self.assertFalse(security.verify_password("wrong-password", h))

    def test_unicode_password(self):
        h = security.hash_password("密码1234!@#$%^&*()_+")
        self.assertTrue(security.verify_password("密码1234!@#$%^&*()_+", h))

    def test_invalid_phc_returns_false(self):
        self.assertFalse(security.verify_password("anything", "not-a-hash"))
        self.assertFalse(security.verify_password("anything", ""))


class UsernameNormalizationTests(unittest.TestCase):
    def test_trims_and_lowercases(self):
        self.assertEqual(security.normalize_username("  Alice_1 "), "alice_1")

    def test_rejects_too_short(self):
        with self.assertRaises(ValueError):
            security.normalize_username("ab")

    def test_rejects_too_long(self):
        with self.assertRaises(ValueError):
            security.normalize_username("a" * 33)

    def test_rejects_invalid_chars(self):
        with self.assertRaises(ValueError):
            security.normalize_username("alice@example")

    def test_requires_alphanumeric(self):
        with self.assertRaises(ValueError):
            security.normalize_username("._-")
        self.assertEqual(security.normalize_username("._-a"), "._-a")


class PasswordValidationTests(unittest.TestCase):
    def test_bounds(self):
        security.validate_password("x" * 12)
        security.validate_password("x" * 128)
        with self.assertRaises(ValueError):
            security.validate_password("x" * 11)
        with self.assertRaises(ValueError):
            security.validate_password("x" * 129)


class DisplayNameTests(unittest.TestCase):
    def test_empty_becomes_none(self):
        self.assertIsNone(security.normalize_display_name(""))
        self.assertIsNone(security.normalize_display_name("   "))
        self.assertIsNone(security.normalize_display_name(None))

    def test_trims(self):
        self.assertEqual(security.normalize_display_name("  张老师  "), "张老师")

    def test_too_long(self):
        with self.assertRaises(ValueError):
            security.normalize_display_name("x" * 81)


class SessionTokenTests(unittest.TestCase):
    def test_token_unique_and_hash_consistent(self):
        t1, h1 = security.create_session()
        t2, h2 = security.create_session()
        self.assertNotEqual(t1, t2)
        self.assertEqual(security.hash_token(t1), h1)
        self.assertEqual(len(h1), 64)


if __name__ == "__main__":
    unittest.main()
