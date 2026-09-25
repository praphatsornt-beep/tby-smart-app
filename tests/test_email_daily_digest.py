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


class TestResolveNoticeItem(unittest.TestCase):
    """เพิ่ม 2026-09-21 ตามคำขอ user — ชื่อสินค้าจากอีเมล Shopee ยาวเกินไปสำหรับข้อความ LINE,
    แก้เพิ่มรอบสองวันเดียวกันให้คูณ units_per_pack ด้วย (พลาดรอบแรก user ทักหลัง map "ยาสีฟัน
    3 หลอด" แล้วสังเกตว่าไม่มีตัวคูณ)"""

    def test_mapped_name_returns_short_code(self):
        notice_map = {"กาแฟโสมซูเลียน ขนาด 40 ซอง คอฟฟี่พลัส": {"product_id": "TF2581", "units_per_pack": 1}}
        label, qty = edd._resolve_notice_item("กาแฟโสมซูเลียน ขนาด 40 ซอง คอฟฟี่พลัส", "", 2, notice_map)
        self.assertEqual(label, "TF2581")
        self.assertEqual(qty, 2)

    def test_mapped_name_with_variant_uses_combined_key(self):
        notice_map = {"แชมพู :: ผิวแห้ง": {"product_id": "SP2001", "units_per_pack": 1}}
        label, qty = edd._resolve_notice_item("แชมพู", "ผิวแห้ง", 1, notice_map)
        self.assertEqual(label, "SP2001")
        self.assertEqual(qty, 1)

    def test_mapped_bundle_multiplies_qty_by_units_per_pack(self):
        # ยาสีฟัน 3 หลอด map เป็นรหัสเดี่ยว + units_per_pack=3 — 1 ออเดอร์ต้องนับเป็น 3 หลอด
        notice_map = {"ยาสีฟันแพค 3 หลอด": {"product_id": "TU2315", "units_per_pack": 3}}
        label, qty = edd._resolve_notice_item("ยาสีฟันแพค 3 หลอด", "", 1, notice_map)
        self.assertEqual(label, "TU2315")
        self.assertEqual(qty, 3)

    def test_unmapped_short_name_unchanged(self):
        label, qty = edd._resolve_notice_item("กาแฟโสม", "", 4, {})
        self.assertEqual(label, "กาแฟโสม")
        self.assertEqual(qty, 4)

    def test_unmapped_long_name_kept_full(self):
        # เดิมตัดให้สั้นเหลือ 27 ตัวอักษร+"..." — user ทักท้วง 2026-09-21 ว่าอ่านไม่ออกว่าเป็น
        # สินค้าอะไร เปลี่ยนให้คงชื่อเต็มไว้เสมอถ้ายังไม่ map (_capped_rows() คุมความยาวรวม
        # ของข้อความ LINE แทนที่จุดนี้)
        long_name = "กาแฟโสมซูเลียน ขนาด 40 ซอง คอฟฟี่พลัส สูตรพรีเมียม"
        label, qty = edd._resolve_notice_item(long_name, "", 1, {})
        self.assertEqual(label, long_name)
        self.assertEqual(qty, 1)


class TestBuildCodUnbilledRows(unittest.TestCase):
    """เพิ่ม 2026-09-21 ตามคำขอ user — ให้ digest รายวันบอกด้วยว่า COD รับเงินแล้วแต่ยังไม่
    เปิดบิลมีลูกค้าคนไหนบ้าง (เหมือนการ์ด "✅ รับแล้ว — ยังไม่เปิดบิล" ใน dashboard_ui.py)"""

    def test_matches_shipment_to_unbilled_customer_by_name(self):
        txn_rows = [{"customer_id": "C-001", "customers": {"name": "สมชาย"}}]
        ship_rows = [{
            "customers": {"name": "สมชาย"}, "cod_amount": 500, "cod_transferred_at": "2026-09-20T10:00:00+00:00",
            "tracking_no": "TH123", "items": [{"name": "กาแฟโสม", "qty": 2}],
        }]
        rows = edd._build_cod_unbilled_rows(txn_rows, ship_rows)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["customer"], "สมชาย")
        self.assertEqual(rows[0]["cod_amount"], 500.0)
        self.assertEqual(rows[0]["tracking_no"], "TH123")
        self.assertIn("กาแฟโสม x2", rows[0]["items"])

    def test_shipment_for_already_billed_customer_excluded(self):
        # ลูกค้าไม่มีแถวค้าง "ยังไม่เปิดบิล" เลย (txn_rows ว่าง) → ไม่ต้องแสดง
        ship_rows = [{
            "customers": {"name": "สมหญิง"}, "cod_amount": 300, "cod_transferred_at": "2026-09-20T10:00:00+00:00",
            "tracking_no": "TH999", "items": [],
        }]
        rows = edd._build_cod_unbilled_rows([], ship_rows)
        self.assertEqual(rows, [])

    def test_shipment_for_different_unbilled_customer_excluded(self):
        txn_rows = [{"customer_id": "C-002", "customers": {"name": "คนอื่น"}}]
        ship_rows = [{
            "customers": {"name": "สมหญิง"}, "cod_amount": 300, "cod_transferred_at": "2026-09-20T10:00:00+00:00",
            "tracking_no": "TH999", "items": [],
        }]
        rows = edd._build_cod_unbilled_rows(txn_rows, ship_rows)
        self.assertEqual(rows, [])

    def test_no_items_falls_back_to_dash(self):
        txn_rows = [{"customer_id": "C-003", "customers": {"name": "ก."}}]
        ship_rows = [{
            "customers": {"name": "ก."}, "cod_amount": 100, "cod_transferred_at": "2026-09-20T10:00:00+00:00",
            "tracking_no": "TH1", "items": [],
        }]
        rows = edd._build_cod_unbilled_rows(txn_rows, ship_rows)
        self.assertEqual(rows[0]["items"], "—")

    def test_cod_not_yet_transferred_excluded(self):
        # ยังไม่โอน COD มา (cod_transferred_at ว่าง) — ยังไม่ควรนับว่า "รับเงินแล้ว"
        txn_rows = [{"customer_id": "C-004", "customers": {"name": "สมศรี"}}]
        ship_rows = [{
            "customers": {"name": "สมศรี"}, "cod_amount": 200, "cod_transferred_at": None,
            "tracking_no": "TH2", "items": [],
        }]
        rows = edd._build_cod_unbilled_rows(txn_rows, ship_rows)
        self.assertEqual(rows, [])

    def test_sorted_by_cod_amount_descending(self):
        # เรียงยอด COD สูงสุดก่อน — สำคัญตอน _capped_rows() ตัดเหลือ N รายการแรกสำหรับ LINE
        txn_rows = [
            {"customer_id": "C-005", "customers": {"name": "เล็ก"}},
            {"customer_id": "C-006", "customers": {"name": "ใหญ่"}},
        ]
        ship_rows = [
            {"customers": {"name": "เล็ก"}, "cod_amount": 100, "cod_transferred_at": "2026-09-20T10:00:00+00:00",
             "tracking_no": "TH1", "items": []},
            {"customers": {"name": "ใหญ่"}, "cod_amount": 999, "cod_transferred_at": "2026-09-20T10:00:00+00:00",
             "tracking_no": "TH2", "items": []},
        ]
        rows = edd._build_cod_unbilled_rows(txn_rows, ship_rows)
        self.assertEqual([r["customer"] for r in rows], ["ใหญ่", "เล็ก"])


class TestCappedRows(unittest.TestCase):
    """เพิ่ม 2026-09-21 หลังเจอ dry-run จริง: "พัสดุค้างส่งเกิน 3 วัน" มี 107 รายการ รวมข้อความ
    ยาว 16,028 ตัวอักษร เกินขีดจำกัด LINE push text (5,000 ตัวอักษร) — ถ้าส่งจริงจะโดนปฏิเสธ
    ทั้งฉบับ ผู้ใช้ยืนยันให้จำกัดไว้ 10 รายการต่อส่วน"""

    def test_fewer_than_max_returns_all_no_remainder(self):
        rows = [{"x": i} for i in range(5)]
        shown, more = edd._capped_rows(rows, max_items=10)
        self.assertEqual(len(shown), 5)
        self.assertEqual(more, 0)

    def test_more_than_max_truncates_and_counts_remainder(self):
        rows = [{"x": i} for i in range(107)]
        shown, more = edd._capped_rows(rows, max_items=10)
        self.assertEqual(len(shown), 10)
        self.assertEqual(more, 97)
        self.assertEqual([r["x"] for r in shown], list(range(10)))

    def test_exactly_max_no_remainder(self):
        rows = [{"x": i} for i in range(10)]
        shown, more = edd._capped_rows(rows, max_items=10)
        self.assertEqual(len(shown), 10)
        self.assertEqual(more, 0)

    def test_default_max_is_10(self):
        rows = [{"x": i} for i in range(15)]
        shown, more = edd._capped_rows(rows)
        self.assertEqual(len(shown), 10)
        self.assertEqual(more, 5)


class TestBuildSlowShipmentRows(unittest.TestCase):
    """เพิ่ม 2026-09-21 ตามคำขอ user — พัสดุไม่ใช่ COD ที่ค้างส่งเกิน 3 วัน ให้บอกชื่อลูกค้า/
    วันที่/สินค้าด้วย (เหมือนการ์ด "พัสดุล่าช้า" ใน dashboard_ui.py)"""

    def setUp(self):
        from datetime import datetime, timezone
        self.now = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)

    def test_old_non_cod_shipment_with_tracking_included(self):
        ship_rows = [{
            "customers": {"name": "สมชาย"}, "cod_amount": 0, "tracking_no": "TH1",
            "carrier": "Flash", "delivery_status": "กำลังจัดส่ง",
            "created_at": "2026-09-15T10:00:00+00:00",
            "items": [{"name": "กาแฟโสม", "qty": 1}],
        }]
        rows = edd._build_slow_shipment_rows(ship_rows, self.now, cutoff_days=3)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["customer"], "สมชาย")
        self.assertEqual(rows[0]["days"], 6)
        self.assertIn("กาแฟโสม x1", rows[0]["items"])

    def test_recent_shipment_excluded(self):
        ship_rows = [{
            "customers": {"name": "สมหญิง"}, "cod_amount": 0, "tracking_no": "TH2",
            "delivery_status": "กำลังจัดส่ง", "created_at": "2026-09-20T10:00:00+00:00", "items": [],
        }]
        rows = edd._build_slow_shipment_rows(ship_rows, self.now, cutoff_days=3)
        self.assertEqual(rows, [])

    def test_cod_shipment_excluded_tracked_separately(self):
        ship_rows = [{
            "customers": {"name": "สมศรี"}, "cod_amount": 300, "tracking_no": "TH3",
            "delivery_status": "กำลังจัดส่ง", "created_at": "2026-09-01T10:00:00+00:00", "items": [],
        }]
        rows = edd._build_slow_shipment_rows(ship_rows, self.now, cutoff_days=3)
        self.assertEqual(rows, [])

    def test_terminal_status_excluded(self):
        # "จัดส่งสำเร็จ"/"ส่งคืนสำเร็จ" เพิ่มเข้ามา 2026-09-21 — พบจริงว่า iShip เปลี่ยนคำจาก
        # "จัดส่งแล้ว" เป็น "จัดส่งสำเร็จ" ทำให้พัสดุที่ส่งถึงแล้วจริง 107 รายการค้างโชว์ใน
        # การ์ด "พัสดุค้างส่งเกิน 3 วัน" ตลอดไป (ดู shipment_status.py)
        for status in ["จัดส่งแล้ว", "จัดส่งสำเร็จ", "ตีกลับ", "ส่งคืนสำเร็จ", "ยกเลิก"]:
            ship_rows = [{
                "customers": {"name": "สมปอง"}, "cod_amount": 0, "tracking_no": "TH4",
                "delivery_status": status, "created_at": "2026-09-01T10:00:00+00:00", "items": [],
            }]
            rows = edd._build_slow_shipment_rows(ship_rows, self.now, cutoff_days=3)
            self.assertEqual(rows, [], f"status={status} ควรถูกตัดออก")

    def test_no_tracking_no_excluded(self):
        ship_rows = [{
            "customers": {"name": "สมปอง"}, "cod_amount": 0, "tracking_no": "",
            "delivery_status": "กำลังจัดส่ง", "created_at": "2026-09-01T10:00:00+00:00", "items": [],
        }]
        rows = edd._build_slow_shipment_rows(ship_rows, self.now, cutoff_days=3)
        self.assertEqual(rows, [])


class TestParseIshipStatusRows(unittest.TestCase):
    """เพิ่ม 2026-09-21 ตามคำขอ user ("มันดึงทุกเช้าได้เองมั้ย") — พอร์ต
    iship_api.get_shipment_statuses()'s HTML-parsing มาแยกเป็นฟังก์ชัน pure ให้ทดสอบได้โดยไม่
    ต้องปลอม HTTP session/mock requests"""

    def test_extracts_tracking_no_from_link_href(self):
        rows = [{
            "track_no": '<a href="https://app.iship.cloud/tracking?track=TH123456789" target="_blank">TH123456789</a>',
            "status_btn": '<button class="btn btn-sm btn-success">จัดส่งสำเร็จ</button>',
        }]
        result = edd._parse_iship_status_rows(rows)
        self.assertEqual(result, {"TH123456789": "จัดส่งสำเร็จ"})

    def test_falls_back_to_link_text_when_no_track_param(self):
        rows = [{
            "track_no": '<span>TH999888777</span>',
            "status_btn": '<button>กำลังจัดส่ง</button>',
        }]
        result = edd._parse_iship_status_rows(rows)
        self.assertEqual(result, {"TH999888777": "กำลังจัดส่ง"})

    def test_multiple_rows(self):
        rows = [
            {"track_no": '<a href="?track=TH111">TH111</a>', "status_btn": '<button>จัดส่งแล้ว</button>'},
            {"track_no": '<a href="?track=TH222">TH222</a>', "status_btn": '<button>ตีกลับ</button>'},
        ]
        result = edd._parse_iship_status_rows(rows)
        self.assertEqual(result, {"TH111": "จัดส่งแล้ว", "TH222": "ตีกลับ"})

    def test_missing_tracking_or_status_skipped(self):
        rows = [
            {"track_no": "", "status_btn": '<button>จัดส่งแล้ว</button>'},
            {"track_no": '<a href="?track=TH333">TH333</a>', "status_btn": ""},
        ]
        result = edd._parse_iship_status_rows(rows)
        self.assertEqual(result, {})

    def test_empty_rows_returns_empty_dict(self):
        self.assertEqual(edd._parse_iship_status_rows([]), {})


class _FakeQuery:
    """ปลอม query builder ของ supabase-py แบบขั้นต่ำ — เก็บ data คงที่ไว้ ทุก chained method
    (select/eq/order/range ฯลฯ) คืน self ไปเรื่อยๆ จนกว่าจะ .execute() แล้วได้ data กลับ"""
    def __init__(self, data):
        self._data = data

    def __getattr__(self, _name):
        return lambda *a, **kw: self

    def execute(self):
        from types import SimpleNamespace
        return SimpleNamespace(data=self._data)


class _FakeSupabaseRaises:
    """ปลอม sb client ที่ระเบิดทันทีถ้าถูกเรียก .table() เลย — ใช้พิสูจน์ว่า path ที่เจอ
    fresh_notices แล้วไม่ต้อง query DB เพิ่มจริงๆ"""
    def table(self, _name):
        raise AssertionError("ไม่ควร query DB เมื่อเจอใน fresh_notices แล้ว")


class _FakeSupabaseByTable:
    def __init__(self, table_data: dict):
        self._table_data = table_data

    def table(self, name):
        return _FakeQuery(self._table_data.get(name, []))


class TestShopeeReturnItemSummary(unittest.TestCase):
    """เพิ่ม 2026-09-25 ตามคำขอ user — บรรทัด "พัสดุ Shopee มีปัญหา/ตีกลับ" ใน digest เดิมมีแค่
    เลขออเดอร์/ขนส่ง ไม่มีสินค้า/จำนวนเลย"""

    def test_uses_fresh_notices_without_db_call(self):
        fresh = {"26091545QUFXSM": ({"items": [{"name": "กาแฟโสม", "variant": "", "qty": 2}]}, "subj")}
        notice_map = {"กาแฟโสม": {"product_id": "TF2581", "units_per_pack": 1}}
        result = edd._shopee_return_item_summary(_FakeSupabaseRaises(), "26091545QUFXSM", fresh, notice_map)
        self.assertEqual(result, "TF2581 x2")

    def test_falls_back_to_db_order_notices_when_not_fresh(self):
        sb = _FakeSupabaseByTable({
            "ecommerce_order_notices": [{"items": [{"name": "แชมพู", "variant": "", "qty": 1}]}],
        })
        result = edd._shopee_return_item_summary(sb, "260901ABC", {}, {})
        self.assertEqual(result, "แชมพู x1")

    def test_falls_back_to_ecommerce_sales_when_no_notices(self):
        sb = _FakeSupabaseByTable({
            "ecommerce_order_notices": [],
            "ecommerce_sales": [{"product_id": "TF2504", "item_name": None, "qty": 2.0, "products": {"name": "กาแฟโสม"}}],
        })
        result = edd._shopee_return_item_summary(sb, "260901XYZ", {}, {})
        self.assertEqual(result, "กาแฟโสม x2")

    def test_whole_number_qty_not_shown_as_decimal(self):
        # ecommerce_sales.qty เป็น float ใน DB จริง — "x2.0" อ่านแปลก ต้องโชว์ "x2" ถ้าเป็นจำนวนเต็ม
        sb = _FakeSupabaseByTable({
            "ecommerce_order_notices": [],
            "ecommerce_sales": [{"product_id": "TF2504", "item_name": None, "qty": 1.5, "products": None}],
        })
        result = edd._shopee_return_item_summary(sb, "260901QTY", {}, {})
        self.assertEqual(result, "TF2504 x1.5")

    def test_returns_empty_string_when_nothing_found(self):
        sb = _FakeSupabaseByTable({"ecommerce_order_notices": [], "ecommerce_sales": []})
        result = edd._shopee_return_item_summary(sb, "260901NONE", {}, {})
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
