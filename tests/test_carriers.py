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


if __name__ == "__main__":
    unittest.main()
