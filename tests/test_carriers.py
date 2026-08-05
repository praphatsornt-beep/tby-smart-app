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

    def test_volumetric_weight_used_when_bigger_than_actual(self):
        # ยืนยันจากราคาจริงบน iShip (2026-08-04): กล่อง 40x45x23cm น้ำหนักจริง 3kg
        # ส่ง กทม -> ปริมาตร 41400/4000 = 10.35 -> ปัดขึ้น 11kg -> ใช้เรท 11kg แทน 3kg
        opts = carriers.get_shipping_options(3, "10110", length_cm=40, width_cm=45, height_cm=23)
        by_id = {o["id"]: o for o in opts}
        self.assertEqual(by_id["flash_thunder"]["billed_kg"], 11.0)
        self.assertEqual(by_id["flash_thunder"]["total"], 140)
        self.assertEqual(by_id["flash_pro_dd"]["total"], 140)
        self.assertEqual(by_id["flash_pro_ok"]["total"], 140)
        self.assertEqual(by_id["flash_100cm"]["total"], 145)

    def test_volumetric_weight_ignored_when_no_dimensions(self):
        # ไม่ระบุขนาด -> ใช้น้ำหนักจริงเหมือนเดิม ไม่กระทบพฤติกรรมเดิม
        opts = carriers.get_shipping_options(3, "10110")
        ft = next(o for o in opts if o["id"] == "flash_thunder")
        self.assertEqual(ft["billed_kg"], 3.0)
        self.assertEqual(ft["volumetric_kg"], 0.0)

    def test_actual_weight_used_when_bigger_than_volumetric(self):
        # กล่องเล็กแต่หนัก -> ใช้น้ำหนักจริง ไม่ใช่ปริมาตร (ปริมาตรน้อยกว่า)
        opts = carriers.get_shipping_options(10, "10110", length_cm=20, width_cm=20, height_cm=20)
        ft = next(o for o in opts if o["id"] == "flash_thunder")
        self.assertEqual(ft["billed_kg"], 10.0)  # 20*20*20/4000=2kg < 10kg จริง

    def test_flash_thunder_max_cm_varies_by_weight_tier(self):
        # ยืนยันจากตารางจริงของ Flash Thunder (2026-08-05): ขนาดจำกัดเพิ่มทีละ 5cm/kg
        # ตั้งแต่ 6kg ขึ้นไป ไม่ใช่ 280cm คงที่ทุกน้ำหนักเหมือนเดิม
        cases = {3: 80, 6: 85, 13: 120, 44: 275, 45: 280, 50: 280}
        for kg, expected_cm in cases.items():
            with self.subTest(kg=kg):
                opts = carriers.get_shipping_options(kg, "10110")
                ft = next(o for o in opts if o["id"] == "flash_thunder")
                self.assertEqual(ft["max_cm"], expected_cm)

    def test_flash_thunder_max_cm_follows_volumetric_bracket(self):
        # กล่องเบาแต่ใหญ่ ถูกดันไปเรตน้ำหนักปริมาตรที่สูงกว่า -> ขนาดจำกัดต้องอ้างอิง
        # bracket ปริมาตร (11kg) ไม่ใช่ bracket น้ำหนักจริง (3kg)
        opts = carriers.get_shipping_options(3, "10110", length_cm=40, width_cm=45, height_cm=23)
        ft = next(o for o in opts if o["id"] == "flash_thunder")
        self.assertEqual(ft["billed_kg"], 11.0)
        self.assertEqual(ft["max_cm"], 110)

    def test_flash_pro_ok_max_cm_matches_thunder_table(self):
        # ยืนยันจากตารางจริงของ Flash Pro OK (2026-08-05) — ตรงกับ Thunder เป๊ะทุก tier
        cases = {3: 80, 6: 85, 13: 120, 44: 275, 45: 280}
        for kg, expected_cm in cases.items():
            with self.subTest(kg=kg):
                opts = carriers.get_shipping_options(kg, "10110")
                o = next(x for x in opts if x["id"] == "flash_pro_ok")
                self.assertEqual(o["max_cm"], expected_cm)

    def test_flash_pro_dd_max_cm_differs_at_low_weight(self):
        # ยืนยันจากตารางจริงของ Flash Pro DD (2026-08-05) — ต่างจาก Thunder เฉพาะ
        # 1-4kg (60/60/60/70 แทน 80 คงที่) ตั้งแต่ 5kg ขึ้นไปตรงกับ Thunder เป๊ะ
        cases = {1: 60, 2: 60, 3: 60, 4: 70, 5: 80, 6: 85, 13: 120, 45: 280}
        for kg, expected_cm in cases.items():
            with self.subTest(kg=kg):
                opts = carriers.get_shipping_options(kg, "10110")
                o = next(x for x in opts if x["id"] == "flash_pro_dd")
                self.assertEqual(o["max_cm"], expected_cm)

    def test_flash_100cm_max_cm_flat_until_10kg(self):
        # ยืนยันจากตารางจริงของ Flash 100CM (2026-08-05) — คงที่ 100 ตลอด 1-9kg
        # (ไม่ไล่ขึ้นทีละ 5cm/kg เหมือนเจ้าอื่น) แล้วค่อยไล่ขึ้นแบบเดียวกันตั้งแต่ 10kg
        cases = {1: 100, 5: 100, 9: 100, 10: 105, 13: 120, 45: 280}
        for kg, expected_cm in cases.items():
            with self.subTest(kg=kg):
                opts = carriers.get_shipping_options(kg, "10110")
                o = next(x for x in opts if x["id"] == "flash_100cm")
                self.assertEqual(o["max_cm"], expected_cm)

    def test_kex_max_cm_uses_pickup_acceptance_tiers(self):
        # ยืนยันจากเงื่อนไข "เข้ารับ" จริงของ KEX Express (2026-08-05) — แคบกว่าเพดาน
        # 180cm ทั่วไปที่ตารางราคาเขียนไว้ (คนขับปฏิเสธรับหน้างานได้ถ้าเกินเกณฑ์นี้)
        cases = {1: 75, 7: 75, 8: 90, 10: 90, 11: 120, 15: 120, 16: 180, 30: 180}
        for kg, expected_cm in cases.items():
            with self.subTest(kg=kg):
                opts = carriers.get_shipping_options(kg, "10110")
                o = next(x for x in opts if x["id"] == "kex")
                self.assertEqual(o["max_cm"], expected_cm)

    def test_dhl_max_cm_uneven_steps_then_capped_at_max_weight(self):
        # ยืนยันจากตารางจริงของ DHL eCommerce (2026-08-05) — ไล่ขึ้นแบบขั้นบันไดไม่เท่ากัน
        # ช่วง 1-13kg แล้วค่อย +5cm/kg สม่ำเสมอ 14-34kg ก่อนกระโดดไปแตะเพดาน 250cm ที่ 35kg
        cases = {1: 70, 2: 80, 5: 90, 9: 110, 14: 125, 30: 205, 34: 225, 35: 250}
        for kg, expected_cm in cases.items():
            with self.subTest(kg=kg):
                opts = carriers.get_shipping_options(kg, "10110")
                o = next(x for x in opts if x["id"] == "dhl")
                self.assertEqual(o["max_cm"], expected_cm)

    def test_dhl_next_day_max_cm_matches_dhl_ecommerce_table(self):
        # ยืนยันจากตารางจริงของ DHL Next Day (2026-08-05) — ตรงกับ DHL eCommerce เป๊ะ
        cases = {1: 70, 14: 125, 30: 205, 35: 250}
        for kg, expected_cm in cases.items():
            with self.subTest(kg=kg):
                opts = carriers.get_shipping_options(kg, "10110")
                o = next(x for x in opts if x["id"] == "dhl_next_day")
                self.assertEqual(o["max_cm"], expected_cm)


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
