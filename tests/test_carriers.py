import unittest

import carriers


class TestGetShippingOptions(unittest.TestCase):
    def test_flash_thunder_1kg_bangkok_normal_zone(self):
        opts = carriers.get_shipping_options(1, "10110")
        ft = next(o for o in opts if o["id"] == "flash_thunder")
        # base 19 (bkk, 1kg) + surcharge 0 (normal zone) + fuel 3
        self.assertEqual(ft["base"], 19)
        self.assertEqual(ft["surcharge"], 0)
        self.assertEqual(ft["total"], 22)
        self.assertFalse(ft["exceeds_max"])

    def test_bangkok_cheaper_than_province_same_carrier(self):
        bkk = next(o for o in carriers.get_shipping_options(1, "10110") if o["id"] == "flash_thunder")
        province = next(o for o in carriers.get_shipping_options(1, "50000") if o["id"] == "flash_thunder")
        self.assertLess(bkk["base"], province["base"])

    def test_results_sorted_cheapest_first(self):
        opts = carriers.get_shipping_options(2, "10110")
        ok = [o for o in opts if not o["exceeds_max"]]
        totals = [o["total"] for o in ok]
        self.assertEqual(totals, sorted(totals))

    def test_exceeds_max_weight(self):
        opts = carriers.get_shipping_options(999, "10110")
        spx = next(o for o in opts if o["id"] == "spx")
        self.assertTrue(spx["exceeds_max"])

    def test_cod_fee_added_only_when_cod(self):
        with_cod = carriers.get_shipping_options(1, "10110", is_cod=True, cod_amount=500)
        without_cod = carriers.get_shipping_options(1, "10110", is_cod=False)
        ft_with = next(o for o in with_cod if o["id"] == "flash_thunder")
        ft_without = next(o for o in without_cod if o["id"] == "flash_thunder")
        self.assertGreater(ft_with["cod_fee"], 0)
        self.assertEqual(ft_without["cod_fee"], 0)

    def test_remote_zone_surcharge_applied(self):
        # 96000 = remote zone, +50 surcharge for flash_thunder regardless of weight
        ft = next(o for o in carriers.get_shipping_options(1, "96000") if o["id"] == "flash_thunder")
        self.assertEqual(ft["surcharge"], 50)


class TestBracketBreakpoints(unittest.TestCase):
    def test_inter_express_flat_brackets(self):
        # ราคาเหมาเป็นช่วง 5kg (110/130/150/170) -> จุดตัดคือ kg สุดท้ายของแต่ละช่วง
        points = carriers._bracket_breakpoints(carriers._INTER_EXPRESS, 30)
        self.assertEqual(points, [15, 20, 25, 30])

    def test_smooth_pricing_falls_back_to_max_kg(self):
        # ราคาไหลลื่นเกือบทุก kg -> ไม่มีประโยชน์ลองหลายจุด คืน [max_kg] ค่าเดียว
        points = carriers._bracket_breakpoints(carriers._FLASH_THUNDER, 50)
        self.assertEqual(points, [50])


class TestPlanBoxes(unittest.TestCase):
    def test_matches_hand_calculated_inter_total(self):
        # ผงซักฟอก: 1 ลัง = 24 ชิ้น, 27 กก. -> 1.125 กก./ชิ้น
        detergent = {"id": "DET1KG", "weight_grams": 1125, "max_units_per_box": 24}
        # กาแฟ 84 ซอง: ยัดได้สูงสุด 12 ห่อ, 24 กก. -> 2 กก./ห่อ
        coffee84 = {"id": "CF84", "weight_grams": 2000, "max_units_per_box": 12}
        items = [{"product": detergent, "qty": 210}, {"product": coffee84, "qty": 13}]

        plans = carriers.plan_boxes(items, "50210")
        inter = next(p for p in plans if p["id"] == "inter_express")

        self.assertEqual(inter["box_count"], 10)
        self.assertEqual(inter["total_cost"], 1660)
        # ไม่มีกล่องไหนน้ำหนักส่งจริง (สินค้า + 0.5 กก. กล่อง) เกินเพดานที่เลือกใช้
        for box in inter["boxes"]:
            self.assertLessEqual(box["weight_kg"] + 0.5, inter["ceiling_used"] + 1e-9)

    def test_results_sorted_cheapest_first(self):
        product = {"id": "TF2581", "weight_grams": 200, "max_units_per_box": 20}
        items = [{"product": product, "qty": 50}]
        plans = carriers.plan_boxes(items, "10110")
        totals = [p["total_cost"] for p in plans]
        self.assertEqual(totals, sorted(totals))


if __name__ == "__main__":
    unittest.main()
