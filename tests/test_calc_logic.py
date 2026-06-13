import unittest

import calc_logic


PRODUCTS = [
    {"id": "TF2581", "price": 100, "points_per_unit": 10, "weight_grams": 200},
    {"id": "RB2306", "price": 50,  "points_per_unit": 5,  "weight_grams": 300},
]


class TestParseCalcOrder(unittest.TestCase):
    def test_basic_items(self):
        r = calc_logic.parse_calc_order("TF2581-2 RB2306-1", PRODUCTS)
        self.assertEqual(len(r["items"]), 2)
        self.assertEqual(r["items"][0]["product"]["id"], "TF2581")
        self.assertEqual(r["items"][0]["qty"], 2)
        self.assertEqual(r["ship_zip"], "")
        self.assertEqual(r["manual_ship"], -1)
        self.assertFalse(r["is_cod"])
        self.assertEqual(r["errors"], [])

    def test_unknown_code_reports_error(self):
        r = calc_logic.parse_calc_order("XX9999-1", PRODUCTS)
        self.assertEqual(r["items"], [])
        self.assertIn("XX9999", r["errors"][0])

    def test_cod_flag(self):
        r = calc_logic.parse_calc_order("TF2581-1 COD", PRODUCTS)
        self.assertTrue(r["is_cod"])

    def test_sh_kg_no_space(self):
        r = calc_logic.parse_calc_order("TF2581-1 SH-KG12170", PRODUCTS)
        self.assertEqual(r["ship_zip"], "12170")

    def test_sh_kg_with_space(self):
        r = calc_logic.parse_calc_order("TF2581-1 SH-KG 12170", PRODUCTS)
        self.assertEqual(r["ship_zip"], "12170")

    def test_sh_manual_price(self):
        r = calc_logic.parse_calc_order("TF2581-1 SH-50", PRODUCTS)
        self.assertEqual(r["manual_ship"], 50.0)
        self.assertEqual(r["ship_zip"], "")


class TestCodFee(unittest.TestCase):
    def test_rounds_up(self):
        # (1000 + 39) * 0.0321 = 33.3399 -> ceil -> 34
        self.assertEqual(calc_logic.cod_fee(1039), 34)

    def test_zero(self):
        self.assertEqual(calc_logic.cod_fee(0), 0)


class TestPackBoxes(unittest.TestCase):
    def test_single_box_fits_all(self):
        items = [{"product": PRODUCTS[0], "qty": 2}, {"product": PRODUCTS[1], "qty": 1}]
        # total weight = 0.2*2 + 0.3*1 = 0.7 kg
        boxes = calc_logic.pack_boxes(items, max_kg=5)
        self.assertEqual(len(boxes), 1)
        self.assertAlmostEqual(boxes[0]["weight_kg"], 0.7)
        self.assertEqual(boxes[0]["items"], {"TF2581": 2, "RB2306": 1})

    def test_splits_across_boxes_when_exceeding_max(self):
        items = [{"product": PRODUCTS[0], "qty": 3}]  # 3 x 0.2kg = 0.6kg total
        boxes = calc_logic.pack_boxes(items, max_kg=0.4)
        # max 2 units (0.4kg) per box -> 2 boxes
        self.assertEqual(len(boxes), 2)
        total_units = sum(sum(b["items"].values()) for b in boxes)
        self.assertEqual(total_units, 3)


if __name__ == "__main__":
    unittest.main()
