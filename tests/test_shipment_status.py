import unittest

import shipment_status


class TestShipmentStatus(unittest.TestCase):
    """เพิ่ม 2026-09-21 — พบบั๊กจริง: iShip เปลี่ยนคำสถานะจาก "จัดส่งแล้ว" เป็น "จัดส่งสำเร็จ"
    ทำให้พัสดุที่ส่งถึงลูกค้าจริงแล้ว 107 รายการ ค้างโชว์เป็น "พัสดุค้างส่งเกิน 3 วัน" ตลอดไป
    เพราะ exact-match กับคำเก่าเท่านั้น — รวมค่าสถานะไว้ที่เดียวกันไฟล์นี้ กันเหตุการณ์
    เดียวกันเกิดซ้ำ (เดิม hardcode แยกกัน 4 ที่: database.py, dashboard_ui.py,
    shipment_history_ui.py, tools/email_daily_digest.py)"""

    def test_both_delivered_wordings_recognized(self):
        self.assertIn("จัดส่งแล้ว", shipment_status.DELIVERED_STATUSES)
        self.assertIn("จัดส่งสำเร็จ", shipment_status.DELIVERED_STATUSES)

    def test_both_returned_wordings_recognized(self):
        self.assertIn("ตีกลับ", shipment_status.RETURNED_STATUSES)
        self.assertIn("ส่งคืนสำเร็จ", shipment_status.RETURNED_STATUSES)

    def test_terminal_is_union_of_all_three_groups(self):
        expected = (
            shipment_status.DELIVERED_STATUSES
            | shipment_status.RETURNED_STATUSES
            | shipment_status.CANCELLED_STATUSES
        )
        self.assertEqual(shipment_status.TERMINAL_STATUSES, expected)

    def test_in_progress_status_not_terminal(self):
        for status in ["รอเข้ารับ", "ระหว่างขนส่ง", "กำลังนำส่ง", "พัสดุเข้าระบบ"]:
            self.assertNotIn(status, shipment_status.TERMINAL_STATUSES)


if __name__ == "__main__":
    unittest.main()
