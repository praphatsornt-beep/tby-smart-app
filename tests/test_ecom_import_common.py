import unittest

import pandas as pd

import ecom_import_common as c


class TestStrOrNone(unittest.TestCase):
    def test_strips_whitespace(self):
        self.assertEqual(c.str_or_none("  ABC123  "), "ABC123")

    def test_nan_returns_none(self):
        self.assertIsNone(c.str_or_none(pd.NA))
        self.assertIsNone(c.str_or_none(float("nan")))

    def test_empty_string_returns_none(self):
        self.assertIsNone(c.str_or_none("   "))

    def test_non_string_value_stringified(self):
        self.assertEqual(c.str_or_none(123), "123")


class TestIdStrOrNone(unittest.TestCase):
    def test_integer_float_strips_decimal(self):
        self.assertEqual(c.id_str_or_none(123.0), "123")

    def test_non_integer_float_kept(self):
        self.assertEqual(c.id_str_or_none(123.5), "123.5")

    def test_string_passthrough(self):
        self.assertEqual(c.id_str_or_none("ABC123"), "ABC123")

    def test_nan_returns_none(self):
        self.assertIsNone(c.id_str_or_none(pd.NA))

    def test_empty_string_returns_none(self):
        self.assertIsNone(c.id_str_or_none("  "))


class TestNumOrZero(unittest.TestCase):
    def test_nan_returns_zero(self):
        self.assertEqual(c.num_or_zero(pd.NA), 0.0)

    def test_numeric_value(self):
        self.assertEqual(c.num_or_zero(42), 42.0)

    def test_numeric_string(self):
        self.assertEqual(c.num_or_zero("3.5"), 3.5)


class TestParseDate(unittest.TestCase):
    def test_valid_date_string(self):
        self.assertEqual(c.parse_date("2026-03-05"), "2026-03-05")

    def test_nan_returns_none(self):
        self.assertIsNone(c.parse_date(pd.NA))

    def test_unparseable_returns_none(self):
        self.assertIsNone(c.parse_date("not a date"))

    def test_timestamp_truncated_to_date(self):
        self.assertEqual(c.parse_date(pd.Timestamp("2026-03-05 14:30:00")), "2026-03-05")


if __name__ == "__main__":
    unittest.main()
