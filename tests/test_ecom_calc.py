import unittest

import ecom_calc


class TestSettledOrderSns(unittest.TestCase):
    def test_basic(self):
        rows = [{"order_sn": "A"}, {"order_sn": "B"}, {"order_sn": "A"}]
        self.assertEqual(ecom_calc.settled_order_sns(rows), {"A", "B"})

    def test_empty(self):
        self.assertEqual(ecom_calc.settled_order_sns([]), set())


class TestShippingOverchargeExtra(unittest.TestCase):
    def test_overcharged(self):
        row = {"buyer_paid_shipping": 30, "shopee_subsidized_shipping": 10, "shipping_fee_charged": 55}
        self.assertEqual(ecom_calc.shipping_overcharge_extra(row), 15)

    def test_undercharged_negative(self):
        row = {"buyer_paid_shipping": 30, "shopee_subsidized_shipping": 10, "shipping_fee_charged": 20}
        self.assertEqual(ecom_calc.shipping_overcharge_extra(row), -20)

    def test_missing_fields_default_zero(self):
        row = {"shipping_fee_charged": 40}
        self.assertEqual(ecom_calc.shipping_overcharge_extra(row), 40)

    def test_all_missing(self):
        self.assertEqual(ecom_calc.shipping_overcharge_extra({}), 0)


class TestAggregateProductMargin(unittest.TestCase):
    def test_settled_order_aggregates_normally(self):
        sales = [{
            "order_sn": "A", "product_id": "P1", "item_id_platform": "SKU1",
            "qty": 2, "returned_qty": 0, "net_amount": 100, "item_price": 120,
            "order_status": "สำเร็จ",
        }]
        agg, pending, pending_since, pending_until = ecom_calc.aggregate_product_margin(sales, {"A"}, {}, "shopee")
        self.assertEqual(pending, 0)
        self.assertIsNone(pending_since)
        self.assertIsNone(pending_until)
        self.assertEqual(agg["P1"], {"qty": 2.0, "net": 100.0, "gross": 120.0})

    def test_unsettled_order_goes_to_pending(self):
        sales = [{
            "order_sn": "B", "product_id": "P1", "item_id_platform": "SKU1",
            "qty": 3, "returned_qty": 0, "net_amount": 0, "item_price": 0,
            "order_status": "สำเร็จ", "sale_date": "2026-03-01",
        }]
        agg, pending, pending_since, pending_until = ecom_calc.aggregate_product_margin(sales, set(), {}, "shopee")
        self.assertEqual(agg, {})
        self.assertEqual(pending, 3)
        self.assertEqual(pending_since, "2026-03-01")
        self.assertEqual(pending_until, "2026-03-01")

    def test_pending_since_until_pick_earliest_and_latest_date(self):
        sales = [
            {"order_sn": "B1", "product_id": "P1", "item_id_platform": "SKU1",
             "qty": 1, "returned_qty": 0, "net_amount": 0, "item_price": 0,
             "order_status": "สำเร็จ", "sale_date": "2026-05-01"},
            {"order_sn": "B2", "product_id": "P1", "item_id_platform": "SKU1",
             "qty": 1, "returned_qty": 0, "net_amount": 0, "item_price": 0,
             "order_status": "สำเร็จ", "sale_date": "2026-03-01"},
        ]
        _, _, pending_since, pending_until = ecom_calc.aggregate_product_margin(sales, set(), {}, "shopee")
        self.assertEqual(pending_since, "2026-03-01")
        self.assertEqual(pending_until, "2026-05-01")

    def test_cancelled_order_excluded_entirely(self):
        sales = [{
            "order_sn": "C", "product_id": "P1", "item_id_platform": "SKU1",
            "qty": 5, "returned_qty": 0, "net_amount": 0, "item_price": 0,
            "order_status": "ยกเลิกแล้ว",
        }]
        agg, pending, pending_since, pending_until = ecom_calc.aggregate_product_margin(sales, {"C"}, {}, "shopee")
        self.assertEqual(agg, {})
        self.assertEqual(pending, 0)
        self.assertIsNone(pending_since)
        self.assertIsNone(pending_until)

    def test_returned_qty_reduces_net_qty(self):
        sales = [{
            "order_sn": "D", "product_id": "P1", "item_id_platform": "SKU1",
            "qty": 10, "returned_qty": 3, "net_amount": 50, "item_price": 60,
            "order_status": "สำเร็จ",
        }]
        agg, _, _, _ = ecom_calc.aggregate_product_margin(sales, {"D"}, {}, "shopee")
        self.assertEqual(agg["P1"]["qty"], 7.0)

    def test_units_per_pack_multiplier_applied(self):
        sales = [{
            "order_sn": "E", "product_id": "P1", "item_id_platform": "SKU-PACK",
            "qty": 2, "returned_qty": 0, "net_amount": 100, "item_price": 120,
            "order_status": "สำเร็จ",
        }]
        prod_map = {("shopee", "SKU-PACK"): {"product_id": "P1", "units_per_pack": 3}}
        agg, _, _, _ = ecom_calc.aggregate_product_margin(sales, {"E"}, prod_map, "shopee")
        self.assertEqual(agg["P1"]["qty"], 6.0)  # 2 * 3


class TestProductMarginRows(unittest.TestCase):
    def test_platform_label_in_column_name(self):
        agg = {"P1": {"qty": 2.0, "net": 100.0, "gross": 120.0}}
        products = {"P1": {"name": "สินค้า A", "cost_price": 30, "points_per_unit": 5}}
        rows = ecom_calc.product_margin_rows(agg, products, "lazada")
        self.assertIn("ขายผ่าน Lazada (ชิ้น)", rows[0])
        self.assertNotIn("ขายผ่าน Shopee (ชิ้น)", rows[0])

    def test_unknown_platform_falls_back_to_capitalized(self):
        agg = {"P1": {"qty": 1.0, "net": 10.0, "gross": 10.0}}
        rows = ecom_calc.product_margin_rows(agg, {}, "newplatform")
        self.assertIn("ขายผ่าน Newplatform (ชิ้น)", rows[0])

    def test_profit_calculation(self):
        agg = {"P1": {"qty": 2.0, "net": 100.0, "gross": 120.0}}
        products = {"P1": {"name": "สินค้า A", "cost_price": 30, "points_per_unit": 0}}
        rows = ecom_calc.product_margin_rows(agg, products, "shopee")
        # profit = net - cost*qty = 100 - 30*2 = 40
        self.assertEqual(rows[0]["กำไรรวม"], 40)
        self.assertEqual(rows[0]["กำไร/ชิ้น"], 20)

    def test_zero_qty_sold_avoids_division_by_zero(self):
        agg = {"P1": {"qty": 0.0, "net": 0.0, "gross": 0.0}}
        products = {"P1": {"cost_price": 30}}
        rows = ecom_calc.product_margin_rows(agg, products, "shopee")
        self.assertEqual(rows[0]["กำไร/ชิ้น"], 0)
        self.assertIsNone(rows[0]["ราคาขายสุทธิที่ควรได้ต่อชิ้น (คุ้มทุน)"])


class TestAggregateOrderCosts(unittest.TestCase):
    def test_unmapped_product_flags_order(self):
        sales = [{
            "order_sn": "A", "product_id": None, "item_id_platform": "SKU1", "item_name": "?",
            "qty": 1, "returned_qty": 0, "order_status": "สำเร็จ", "sale_date": "2026-01-01",
        }]
        incomes = {"A": ("shop1", 100.0)}
        by_order = ecom_calc.aggregate_order_costs(sales, incomes, {}, {}, "shopee")
        self.assertTrue(by_order["A"]["unmapped"])

    def test_unsettled_order_excluded(self):
        sales = [{
            "order_sn": "B", "product_id": "P1", "item_id_platform": "SKU1", "item_name": "x",
            "qty": 1, "returned_qty": 0, "order_status": "สำเร็จ", "sale_date": "2026-01-01",
        }]
        by_order = ecom_calc.aggregate_order_costs(sales, {}, {}, {}, "shopee")
        self.assertEqual(by_order, {})

    def test_cost_accumulates_across_lines(self):
        sales = [
            {"order_sn": "C", "product_id": "P1", "item_id_platform": "SKU1", "item_name": "x",
             "qty": 2, "returned_qty": 0, "order_status": "สำเร็จ", "sale_date": "2026-01-01"},
            {"order_sn": "C", "product_id": "P2", "item_id_platform": "SKU2", "item_name": "y",
             "qty": 1, "returned_qty": 0, "order_status": "สำเร็จ", "sale_date": "2026-01-01"},
        ]
        incomes = {"C": ("shop1", 500.0)}
        products = {"P1": {"cost_price": 10, "name": "A"}, "P2": {"cost_price": 20, "name": "B"}}
        by_order = ecom_calc.aggregate_order_costs(sales, incomes, {}, products, "shopee")
        self.assertEqual(by_order["C"]["cost"], 40.0)  # 10*2 + 20*1
        self.assertEqual(set(by_order["C"]["items"]), {"A", "B"})


class TestOrderProfitSummary(unittest.TestCase):
    def test_profit_and_loss_split(self):
        incomes = {"A": ("shop1", 100.0), "B": ("shop1", 20.0)}
        by_order = {
            "A": {"cost": 60.0, "unmapped": False, "items": ["x"]},
            "B": {"cost": 50.0, "unmapped": False, "items": ["y"]},
        }
        result = ecom_calc.order_profit_summary(incomes, by_order)
        self.assertEqual(result["total_profit"], 40.0)
        self.assertEqual(result["total_loss"], -30.0)
        self.assertEqual(result["net"], 10.0)

    def test_unmapped_orders_excluded(self):
        incomes = {"A": ("shop1", 100.0)}
        by_order = {"A": {"cost": 999.0, "unmapped": True, "items": []}}
        result = ecom_calc.order_profit_summary(incomes, by_order)
        self.assertEqual(result, {"total_profit": 0.0, "total_loss": 0.0, "net": 0.0})

    def test_empty_input(self):
        self.assertEqual(ecom_calc.order_profit_summary({}, {}), {"total_profit": 0.0, "total_loss": 0.0, "net": 0.0})


class TestOrderAnomalyRows(unittest.TestCase):
    def test_flags_loss_order(self):
        incomes = {"A": ("shop1", 50.0)}
        by_order = {"A": {"cost": 80.0, "unmapped": False, "items": ["x"], "sale_date": "2026-01-01"}}
        rows = ecom_calc.order_anomaly_rows(incomes, by_order, warn_pct=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["สถานะ"], "🔴 ขาดทุน")
        self.assertEqual(rows[0]["กำไร"], -30.0)

    def test_flags_low_margin_order(self):
        incomes = {"A": ("shop1", 100.0)}
        by_order = {"A": {"cost": 95.0, "unmapped": False, "items": ["x"], "sale_date": "2026-01-01"}}
        # profit=5, margin=5% < warn_pct=10% -> flagged as low margin
        rows = ecom_calc.order_anomaly_rows(incomes, by_order, warn_pct=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["สถานะ"], "🟡 กำไรต่ำ")

    def test_healthy_order_not_flagged(self):
        incomes = {"A": ("shop1", 100.0)}
        by_order = {"A": {"cost": 50.0, "unmapped": False, "items": ["x"], "sale_date": "2026-01-01"}}
        rows = ecom_calc.order_anomaly_rows(incomes, by_order, warn_pct=10)
        self.assertEqual(rows, [])

    def test_unmapped_order_excluded(self):
        incomes = {"A": ("shop1", 100.0)}
        by_order = {"A": {"cost": 999.0, "unmapped": True, "items": [], "sale_date": "2026-01-01"}}
        rows = ecom_calc.order_anomaly_rows(incomes, by_order, warn_pct=10)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
