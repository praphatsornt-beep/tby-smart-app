import unittest

import flash_zones as fz


class TestZoneLookup(unittest.TestCase):
    def test_normal_zone(self):
        self.assertEqual(fz.lookup_zone("10110"), "normal")
        self.assertEqual(fz.zone_surcharge("10110"), 0)

    def test_tourist_island_zone(self):
        self.assertEqual(fz.lookup_zone("83000"), "tourist")
        self.assertEqual(fz.zone_surcharge("83000"), 30)

    def test_remote_zone(self):
        self.assertEqual(fz.lookup_zone("96000"), "remote")
        self.assertEqual(fz.zone_surcharge("96000"), 50)


class TestZoneSurchargeByWeight(unittest.TestCase):
    def test_tourist_tiers(self):
        # 83000 = tourist: <=7kg=+30, <=20kg=+100, >20kg=+200
        self.assertEqual(fz.zone_surcharge_by_weight("83000", 5), 30)
        self.assertEqual(fz.zone_surcharge_by_weight("83000", 10), 100)
        self.assertEqual(fz.zone_surcharge_by_weight("83000", 25), 200)

    def test_tourist_island_tiers(self):
        # 84140 = tourist_island: <=7kg=+60, <=20kg=+130, >20kg=+230
        self.assertEqual(fz.zone_surcharge_by_weight("84140", 5), 60)
        self.assertEqual(fz.zone_surcharge_by_weight("84140", 10), 130)
        self.assertEqual(fz.zone_surcharge_by_weight("84140", 25), 230)

    def test_remote_unaffected_by_weight(self):
        self.assertEqual(fz.zone_surcharge_by_weight("96000", 1), 50)
        self.assertEqual(fz.zone_surcharge_by_weight("96000", 25), 50)


class TestSpxSurcharge(unittest.TestCase):
    def test_spx_remote(self):
        self.assertEqual(fz.spx_surcharge("96110"), 50)

    def test_spx_normal(self):
        self.assertEqual(fz.spx_surcharge("10110"), 0)


if __name__ == "__main__":
    unittest.main()
