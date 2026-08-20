import unittest

import tiktok_income_import as tii


class TestParseProductSummary(unittest.TestCase):
    def test_valid_match(self):
        self.assertEqual(tii.parse_product_summary("1729384756 * 2;"), ("1729384756", 2))

    def test_valid_match_no_trailing_semicolon(self):
        self.assertEqual(tii.parse_product_summary("1729384756 * 2"), ("1729384756", 2))

    def test_valid_match_extra_whitespace(self):
        self.assertEqual(tii.parse_product_summary("1729384756  *  2 ;"), ("1729384756", 2))

    def test_none_input(self):
        self.assertIsNone(tii.parse_product_summary(None))

    def test_empty_string(self):
        self.assertIsNone(tii.parse_product_summary(""))

    def test_no_asterisk(self):
        self.assertIsNone(tii.parse_product_summary("1729384756 x 2;"))

    def test_multiple_products_still_matches_first(self):
        # เคสหลายสินค้าในออเดอร์เดียว — ยังไม่มีข้อมูลจริงยืนยัน แต่ regex ต้อง match
        # ตัวแรกได้อย่างน้อย ไม่ throw/พัง (ดู docstring ของ sync_tiktok_to_ecommerce
        # เรื่อง edge case นี้)
        self.assertEqual(tii.parse_product_summary("111 * 1; 222 * 3;"), ("111", 1))


if __name__ == "__main__":
    unittest.main()
