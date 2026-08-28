import random
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

    def test_customer_typo_space_dash_equals(self):
        # ลูกค้าพิมพ์จริง: "Ty -2010=1" / "TF--2581=1" — เว้นวรรค+ขีด(คู่)หน้าเลข, ใช้ =
        # คั่นจำนวนแทน -
        r = calc_logic.parse_calc_order("TF -2581=2", PRODUCTS)
        self.assertEqual(len(r["items"]), 1)
        self.assertEqual(r["items"][0]["product"]["id"], "TF2581")
        self.assertEqual(r["items"][0]["qty"], 2)
        self.assertEqual(r["errors"], [])

    def test_customer_typo_double_dash_equals(self):
        r = calc_logic.parse_calc_order("TF--2581=2", PRODUCTS)
        self.assertEqual(len(r["items"]), 1)
        self.assertEqual(r["items"][0]["product"]["id"], "TF2581")
        self.assertEqual(r["items"][0]["qty"], 2)

    def test_customer_typo_no_dash_equals(self):
        r = calc_logic.parse_calc_order("TF2581=2", PRODUCTS)
        self.assertEqual(len(r["items"]), 1)
        self.assertEqual(r["items"][0]["product"]["id"], "TF2581")
        self.assertEqual(r["items"][0]["qty"], 2)

    def test_customer_typo_multi_line(self):
        r = calc_logic.parse_calc_order("TY -2010=1\nTF--2581=1", PRODUCTS)
        self.assertEqual(len(r["items"]), 1)  # TY2010 ไม่มีในระบบทดสอบ → error, ไม่ใช่ item
        self.assertEqual(r["items"][0]["product"]["id"], "TF2581")
        self.assertIn("TY2010", r["errors"][0])

    def test_typo_normalization_does_not_break_sh_kg(self):
        # ตัวเลข 5 หลักของรหัสไปรษณีย์ต้องไม่ถูกกฎ typo (ต้องการเลข 4 หลักเป๊ะ) จับผิด
        r = calc_logic.parse_calc_order("TF2581-1 SH-KG12170", PRODUCTS)
        self.assertEqual(r["ship_zip"], "12170")

    def test_customer_typo_double_dot(self):
        # ลูกค้าพิมพ์จริง: "TU..2315.2" — จุดคู่คั่นหน้าเลข, จุดเดี่ยวคั่นจำนวน
        r = calc_logic.parse_calc_order("TF..2581.2", PRODUCTS)
        self.assertEqual(len(r["items"]), 1)
        self.assertEqual(r["items"][0]["product"]["id"], "TF2581")
        self.assertEqual(r["items"][0]["qty"], 2)

    def test_customer_typo_single_dot(self):
        # ลูกค้าพิมพ์จริง: "TU.3601.1" — จุดเดี่ยวคั่นทั้งสองฝั่ง
        r = calc_logic.parse_calc_order("TF.2581.1", PRODUCTS)
        self.assertEqual(len(r["items"]), 1)
        self.assertEqual(r["items"][0]["product"]["id"], "TF2581")
        self.assertEqual(r["items"][0]["qty"], 1)

    def test_phone_number_line_not_mistaken_for_code(self):
        # เบอร์โทรลูกค้าที่แปะมาด้วย (ไม่มีตัวอักษรนำหน้า) ต้องไม่ถูกตีความเป็นรหัสสินค้า
        r = calc_logic.parse_calc_order("0944382708\nTU..2315.2\nTU.3601.1", PRODUCTS)
        self.assertEqual(r["items"], [])  # TU2315/TU3601 ไม่มีในระบบทดสอบ → error ทั้งคู่
        self.assertEqual(len(r["errors"]), 2)
        self.assertIn("TU2315", r["errors"][0])
        self.assertIn("TU3601", r["errors"][1])


class TestParsePlanTargets(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(calc_logic.parse_plan_targets("plan 2500 2500 1000"), [2500, 2500, 1000])

    def test_shorthand_multiplier(self):
        self.assertEqual(calc_logic.parse_plan_targets("plan 2500*2 1000"), [2500, 2500, 1000])

    def test_no_plan_token(self):
        self.assertEqual(calc_logic.parse_plan_targets("TF2581-2 RB2306-1"), [])

    def test_sorts_descending(self):
        self.assertEqual(calc_logic.parse_plan_targets("plan 1000 2500"), [2500, 1000])


class TestParsePlanTargetList(unittest.TestCase):
    def test_basic_no_plan_keyword(self):
        self.assertEqual(calc_logic.parse_plan_target_list("2500 2500 1000"), [2500, 2500, 1000])

    def test_shorthand_multiplier(self):
        self.assertEqual(calc_logic.parse_plan_target_list("2500*2 1000"), [2500, 2500, 1000])

    def test_empty_string(self):
        self.assertEqual(calc_logic.parse_plan_target_list(""), [])

    def test_sorts_descending(self):
        self.assertEqual(calc_logic.parse_plan_target_list("1000 2500"), [2500, 1000])


class TestSplitBillsByPv(unittest.TestCase):
    def test_splits_evenly_divisible_targets(self):
        items = [{"product": PRODUCTS[0], "qty": 10}]  # 10 หน่วย x 10 PV = 100 PV
        result = calc_logic.split_bills_by_pv(items, [50, 50], rng=random.Random(1))
        self.assertEqual(len(result["bills"]), 2)
        for bill in result["bills"]:
            self.assertEqual(bill["pv"], 50)
        self.assertEqual(result["remaining"]["pv"], 0)

    def test_conserves_total_pv(self):
        items = [{"product": PRODUCTS[0], "qty": 7}, {"product": PRODUCTS[1], "qty": 5}]
        total_pv = 7 * 10 + 5 * 5
        result = calc_logic.split_bills_by_pv(items, [40, 20], rng=random.Random(2))
        assigned = sum(b["pv"] for b in result["bills"]) + result["remaining"]["pv"]
        self.assertEqual(assigned, total_pv)

    def test_bill_pv_never_exceeds_target_plus_tolerance(self):
        items = [{"product": PRODUCTS[0], "qty": 20}]
        result = calc_logic.split_bills_by_pv(items, [33], tolerance=5, rng=random.Random(4))
        self.assertLessEqual(result["bills"][0]["pv"], 33 + 5)

    def test_empty_targets_returns_all_remaining(self):
        items = [{"product": PRODUCTS[0], "qty": 3}]
        result = calc_logic.split_bills_by_pv(items, [], rng=random.Random(3))
        self.assertEqual(result["bills"], [])
        self.assertEqual(result["remaining"]["pv"], 30)


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


class TestPackBoxesGrouped(unittest.TestCase):
    def test_caps_at_max_units_not_weight(self):
        # TF2581 = 0.2kg/unit; max_kg=5 alone would allow 25/box, but max_units_per_box=3 caps it
        product = {**PRODUCTS[0], "max_units_per_box": 3}
        items = [{"product": product, "qty": 7}]
        boxes = calc_logic.pack_boxes_grouped(items, max_kg=5)
        # 7 // 3 = 2 full boxes of 3, remainder 1 -> own leftover box (nothing else to combine with)
        self.assertEqual(len(boxes), 3)
        full = [b for b in boxes if b["items"].get("TF2581") == 3]
        self.assertEqual(len(full), 2)
        for b in full:
            self.assertAlmostEqual(b["weight_kg"], 0.6)
        leftover = [b for b in boxes if b["items"].get("TF2581") == 1]
        self.assertEqual(len(leftover), 1)

    def test_even_distribute_spreads_qty_across_all_chunks(self):
        # เหมือนเทสต์บน แต่ even_distribute=True -> กระจายเท่าๆ กันแทนอัดเต็มแล้วเหลือเศษ
        product = {**PRODUCTS[0], "max_units_per_box": 3}
        items = [{"product": product, "qty": 7}]
        boxes = calc_logic.pack_boxes_grouped(items, max_kg=5, even_distribute=True)
        self.assertEqual(len(boxes), 3)
        counts = sorted(b["items"]["TF2581"] for b in boxes)
        self.assertEqual(counts, [2, 2, 3])
        self.assertEqual(sum(counts), 7)
        for b in boxes:
            self.assertLessEqual(b["items"]["TF2581"], 3)  # ไม่มีกล่องไหนเกิน cap

    def test_chunks_from_different_products_combine_to_avoid_wasted_space(self):
        # แม้แต่ "ก้อนเต็ม" ตาม max_units_per_box (ไม่ใช่แค่เศษ) ก็ควรถูกจับรวมกล่องกับสินค้า
        # อื่นได้ ถ้ายังมีที่ว่างพอ — ไม่ปล่อยให้กล่องน้ำหนักน้อยค้างเดี่ยวๆ ทั้งที่ยังใส่เพิ่มได้
        prod_a = {**PRODUCTS[0], "max_units_per_box": 2}  # 0.2kg/unit
        prod_b = {**PRODUCTS[1], "max_units_per_box": 2}  # 0.3kg/unit
        items = [{"product": prod_a, "qty": 5}, {"product": prod_b, "qty": 3}]
        boxes = calc_logic.pack_boxes_grouped(items, max_kg=5)

        # ไม่มีกล่องไหนเกินเพดาน และไม่มีกล่องไหนมี TF2581/RB2306 เกิน cap (2) ต่อกล่อง
        for b in boxes:
            self.assertLessEqual(b["weight_kg"], 5 + 1e-9)
            self.assertLessEqual(b["items"].get("TF2581", 0), 2)
            self.assertLessEqual(b["items"].get("RB2306", 0), 2)

        # จำนวนรวมต้องครบตามที่สั่ง
        self.assertEqual(sum(b["items"].get("TF2581", 0) for b in boxes), 5)
        self.assertEqual(sum(b["items"].get("RB2306", 0) for b in boxes), 3)

        # เพดานกว้าง (5kg) เมื่อเทียบกับก้อนที่หนักสุด (0.6kg) จึงควรมีอย่างน้อย 1 กล่องที่ปนกัน
        # 2 สินค้า (พิสูจน์ว่าก้อนเต็มก็ยังรวมข้ามสินค้าได้ ไม่ใช่แค่เศษ)
        mixed = [b for b in boxes if len(b["items"]) > 1]
        self.assertGreaterEqual(len(mixed), 1)

    def test_no_max_units_falls_back_to_weight_cap_like_pack_boxes(self):
        items = [{"product": PRODUCTS[0], "qty": 3}]  # no max_units_per_box set
        boxes = calc_logic.pack_boxes_grouped(items, max_kg=0.4)
        self.assertEqual(len(boxes), 2)
        total_units = sum(sum(b["items"].values()) for b in boxes)
        self.assertEqual(total_units, 3)


if __name__ == "__main__":
    unittest.main()
