import email
import importlib.util
import os
import unittest

_MODULE_PATH = os.path.join(os.path.dirname(__file__), "..", "tools", "email_daily_digest.py")
_spec = importlib.util.spec_from_file_location("email_daily_digest", _MODULE_PATH)
edd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(edd)


def _make_multipart_html_only(html_body: str) -> email.message.Message:
    msg = email.message.EmailMessage()
    msg["Subject"] = "test"
    msg.add_alternative(html_body, subtype="html")
    return msg


class TestGetBody(unittest.TestCase):
    """เจอจริง 2026-09-20: อีเมลแจ้งออเดอร์/ตีกลับของ Shopee เป็น multipart/alternative
    ที่มีแค่ text/html ไม่มี text/plain เลย — _get_body() เดิมคืนค่าว่างเปล่าให้ทุกฉบับ
    เงียบๆ ทำให้ parse_shopee_order_notice_email()/parse_shopee_return_emails() ได้
    body="" เสมอในโปรดักชันจริง แม้ทดสอบผ่านด้วย body จาก Gmail API ก็ตาม (Gmail แปลง
    HTML→text ให้เองอัตโนมัติ คนละเส้นทางกับ imaplib ที่ใช้ในสคริปต์นี้)"""

    def test_html_only_multipart_extracts_visible_text(self):
        html = "<html><body><div>เรียน คุณ ts_shop56,</div><div>สวัสดี</div></body></html>"
        msg = _make_multipart_html_only(html)
        body = edd._get_body(msg)
        self.assertIn("เรียน คุณ ts_shop56,", body)
        self.assertIn("สวัสดี", body)

    def test_html_only_multipart_strips_tags_and_scripts(self):
        html = "<html><body><style>.a{color:red}</style><script>alert(1)</script><p>ข้อความ</p></body></html>"
        msg = _make_multipart_html_only(html)
        body = edd._get_body(msg)
        self.assertNotIn("<p>", body)
        self.assertNotIn("alert(1)", body)
        self.assertNotIn("color:red", body)
        self.assertIn("ข้อความ", body)

    def test_html_only_multipart_inserts_pipe_separators_between_cells(self):
        # regex ใน ecom_calc.py ถูกออกแบบให้ทำงานกับข้อความที่มี "|" คั่นระหว่าง cell/บล็อก
        # (ตามที่ Gmail's HTML→text converter สร้างมาแต่เดิม ตอนทดสอบผ่าน Gmail API) —
        # ต้องคงพฤติกรรมนี้ไว้แม้ตอนนี้แปลง HTML เองแล้วก็ตาม ไม่งั้น regex เดิมพังหมด
        html = "<table><tr><td>หมายเลขคำสั่งซื้อ: #260920H0R7Y4S4</td><td>วันที่สั่งซื้อ: 20/09/2026</td></tr></table>"
        msg = _make_multipart_html_only(html)
        body = edd._get_body(msg)
        self.assertIn("|", body)

    def test_multipart_prefers_text_plain_when_present(self):
        msg = email.message.EmailMessage()
        msg["Subject"] = "test"
        msg.set_content("plain text ธรรมดา")
        msg.add_alternative("<html><body>ไม่ควรถูกใช้</body></html>", subtype="html")
        body = edd._get_body(msg)
        self.assertIn("plain text ธรรมดา", body)
        self.assertNotIn("ไม่ควรถูกใช้", body)

    def test_single_part_html_not_multipart(self):
        msg = email.message.Message()
        msg["Subject"] = "test"
        msg["Content-Type"] = "text/html; charset=utf-8"
        msg.set_payload("<div>เนื้อหา HTML ล้วน</div>".encode("utf-8"))
        self.assertFalse(msg.is_multipart())
        body = edd._get_body(msg)
        self.assertIn("เนื้อหา HTML ล้วน", body)
        self.assertNotIn("<div>", body)

    def test_end_to_end_order_notice_parses_from_html_only_email(self):
        """ยืนยัน end-to-end ด้วยโครงสร้างเดียวกับอีเมลจริง #260920H0R7Y4S4 (2026-09-20) —
        HTML ล้วน ไม่มี text/plain — ต้อง parse ออกมาได้ครบทุกฟิลด์ ไม่ใช่แค่จาก subject"""
        import ecom_calc
        html = (
            "<div>เรียน คุณ ts_shop56,</div>"
            "<table><tr><td>หมายเลขคำสั่งซื้อ:</td><td>#260920H0R7Y4S4</td></tr>"
            "<tr><td>วันที่สั่งซื้อ:</td><td>20/09/2026 13:28:49</td></tr></table>"
            "<div>1. กาแฟโสม ซูเลียน กาแฟคอลลาเจน</div>"
            "<table><tr><td>จำนวน:</td><td>1</td></tr><tr><td>ราคา:</td><td>฿253</td></tr></table>"
            "<table><tr><td>ยอดรวมค่าสินค้า:</td><td>฿253</td></tr>"
            "<tr><td>ค่าจัดส่งสินค้า:</td><td>฿0</td></tr></table>"
        )
        msg = _make_multipart_html_only(html)
        body = edd._get_body(msg)
        subject = "คำสั่งซื้อชำระเงินปลายทาง #260920H0R7Y4S4 จากผู้ซื้อ wanladaneramitkhonburi ถูกยืนยันแล้ว"
        result = ecom_calc.parse_shopee_order_notice_email(subject, body)
        self.assertEqual(result["order_sn"], "260920H0R7Y4S4")
        self.assertEqual(result["shop_name"], "ts_shop56")
        self.assertEqual(result["total_amount"], 253.0)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["name"], "กาแฟโสม ซูเลียน กาแฟคอลลาเจน")


class TestBuildCodUnbilledRows(unittest.TestCase):
    """เพิ่ม 2026-09-21 ตามคำขอ user — ให้ digest รายวันบอกด้วยว่า COD รับเงินแล้วแต่ยังไม่
    เปิดบิลมีลูกค้าคนไหนบ้าง (เหมือนการ์ด "✅ รับแล้ว — ยังไม่เปิดบิล" ใน dashboard_ui.py)"""

    def test_matches_shipment_to_unbilled_customer_by_name(self):
        txn_rows = [{"customer_id": "C-001", "customers": {"name": "สมชาย"}}]
        ship_rows = [{
            "customers": {"name": "สมชาย"}, "cod_amount": 500, "tracking_no": "TH123",
            "items": [{"name": "กาแฟโสม", "qty": 2}],
        }]
        rows = edd._build_cod_unbilled_rows(txn_rows, ship_rows)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["customer"], "สมชาย")
        self.assertEqual(rows[0]["cod_amount"], 500.0)
        self.assertEqual(rows[0]["tracking_no"], "TH123")
        self.assertIn("กาแฟโสม x2", rows[0]["items"])

    def test_shipment_for_already_billed_customer_excluded(self):
        # ลูกค้าไม่มีแถวค้าง "ยังไม่เปิดบิล" เลย (txn_rows ว่าง) → ไม่ต้องแสดง
        ship_rows = [{"customers": {"name": "สมหญิง"}, "cod_amount": 300, "tracking_no": "TH999", "items": []}]
        rows = edd._build_cod_unbilled_rows([], ship_rows)
        self.assertEqual(rows, [])

    def test_shipment_for_different_unbilled_customer_excluded(self):
        txn_rows = [{"customer_id": "C-002", "customers": {"name": "คนอื่น"}}]
        ship_rows = [{"customers": {"name": "สมหญิง"}, "cod_amount": 300, "tracking_no": "TH999", "items": []}]
        rows = edd._build_cod_unbilled_rows(txn_rows, ship_rows)
        self.assertEqual(rows, [])

    def test_no_items_falls_back_to_dash(self):
        txn_rows = [{"customer_id": "C-003", "customers": {"name": "ก."}}]
        ship_rows = [{"customers": {"name": "ก."}, "cod_amount": 100, "tracking_no": "TH1", "items": []}]
        rows = edd._build_cod_unbilled_rows(txn_rows, ship_rows)
        self.assertEqual(rows[0]["items"], "—")


if __name__ == "__main__":
    unittest.main()
