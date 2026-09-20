import unittest

import ecom_calc


class TestSettledOrderSns(unittest.TestCase):
    def test_basic(self):
        rows = [{"order_sn": "A"}, {"order_sn": "B"}, {"order_sn": "A"}]
        self.assertEqual(ecom_calc.settled_order_sns(rows), {"A", "B"})

    def test_empty(self):
        self.assertEqual(ecom_calc.settled_order_sns([]), set())


class TestPendingIncomeRows(unittest.TestCase):
    def test_settled_order_excluded(self):
        sales = [{"order_sn": "A", "sale_date": "2026-03-01", "shop_name": "s1",
                  "item_price": 100, "qty": 1, "order_status": "สำเร็จ"}]
        self.assertEqual(ecom_calc.pending_income_rows(sales, {"A"}), [])

    def test_cancelled_order_excluded_even_if_unsettled(self):
        sales = [{"order_sn": "B", "sale_date": "2026-03-01", "shop_name": "s1",
                  "item_price": 100, "qty": 1, "order_status": "ยกเลิกแล้ว"}]
        self.assertEqual(ecom_calc.pending_income_rows(sales, set()), [])

    def test_unsettled_uncancelled_order_included(self):
        sales = [{"order_sn": "C", "sale_date": "2026-03-01", "shop_name": "s1",
                  "item_price": 100, "qty": 2, "returned_qty": 1, "order_status": "สำเร็จ",
                  "product_id": "P1", "products": {"name": "สินค้า A"}}]
        rows = ecom_calc.pending_income_rows(sales, set())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["เลขออเดอร์"], "C")
        self.assertEqual(rows[0]["สินค้า"], "สินค้า A")
        self.assertEqual(rows[0]["จำนวน"], 1.0)

    def test_falls_back_to_item_name_when_unmapped(self):
        sales = [{"order_sn": "D", "sale_date": "2026-03-01", "shop_name": "s1",
                  "item_price": 100, "qty": 1, "order_status": "สำเร็จ",
                  "product_id": None, "item_name": "SKU-XYZ"}]
        rows = ecom_calc.pending_income_rows(sales, set())
        self.assertEqual(rows[0]["สินค้า"], "SKU-XYZ")


class TestParseShopeeReturnEmails(unittest.TestCase):
    """ยืนยันด้วยข้อความจากอีเมลจริงของ Shopee (info@mail.shopee.co.th) 2026-09-19"""

    def test_first_notice_extracts_order_carrier_tracking(self):
        subject = "[แจ้งเตือน] พัสดุกำลังทำการจัดส่งไปยังผู้ขาย กรุณารอการติดต่อจากบริษัทขนส่ง"
        body = (
            "เรียนผู้ขาย มุ่ย, อีเมลนี้มีการแจ้งการจัดส่งไม่สำเร็จหลายคำสั่งซื้อ "
            "โปรดตรวจสอบรายละเอียดด้านล่าง เนื่องจากบริษัทขนส่งไม่สามารถจัดส่งสินค้าแก่ผู้ซื้อได้สำเร็จ "
            "รายละเอียดคำสั่งซื้อที่จัดส่งไม่สำเร็จ ดังนี้ หมายเลขคำสั่งซื้อ : 260909K1U1F0KP "
            "บริษัทขนส่ง : SPX Express หมายเลขติดตามพัสดุ : TH260595364725I หากสินค้าของผู้ขายอยู่ในขั้นตอนนี้"
        )
        result = ecom_calc.parse_shopee_return_emails(subject, body)
        self.assertEqual(result, [{
            "order_sn": "260909K1U1F0KP", "carrier_name": "SPX Express", "tracking_no": "TH260595364725I",
        }])

    def test_repeat_notice_same_fields(self):
        subject = "[แจ้งเตือน] พัสดุของคุณไม่สามารถจัดส่งคืนร้านค้าได้สำเร็จ กรุณาตรวจสอบเพื่อรับสินค้าคืน"
        body = (
            "เรียนผู้ขาย มุ่ย, (แจ้งครั้งที่ 2) บริษัทขนส่งพยายามจัดส่งสินค้าคืนผู้ขายตามที่อยู่ที่ระบุไว้ในระบบ "
            "รายละเอียดคำสั่งซื้อที่จัดส่งไม่สำเร็จ ดังนี้ หมายเลขคำสั่งซื้อ : 260909K1U1F0KP "
            "บริษัทขนส่ง : SPX Express หมายเลขติดตามพัสดุ : TH260595364725I ทั้งนี้"
        )
        result = ecom_calc.parse_shopee_return_emails(subject, body)
        self.assertEqual(result[0]["order_sn"], "260909K1U1F0KP")

    def test_unrelated_email_returns_empty(self):
        result = ecom_calc.parse_shopee_return_emails(
            "ถึงเวลาจัดส่งสินค้าหมายเลข #2609167MX3DSEW แล้ว!", "เรียน คุณ ts_shop56 คำสั่งซื้อพร้อมส่งแล้ว",
        )
        self.assertEqual(result, [])

    def test_no_order_block_returns_empty(self):
        self.assertEqual(ecom_calc.parse_shopee_return_emails("อะไรสักอย่าง", "ไม่มีเลขคำสั่งซื้อในนี้เลย"), [])

    def test_pipe_separator_from_html_conversion_not_included_in_carrier_name(self):
        """ยืนยันจากข้อมูลจริงใน DB 2026-09-20 (order #2609178MC6HQW4) — หลังแก้
        _get_body() ให้ fallback ไปแปลง HTML เอง (_html_to_text ใส่ " | " คั่นขอบเขต
        cell) ทำให้ carrier_name เพี้ยนเป็น "SPX Express |" ก่อนแก้ regex นี้"""
        subject = "[แจ้งเตือน] พัสดุกำลังทำการจัดส่งไปยังผู้ขาย กรุณารอการติดต่อจากบริษัทขนส่ง"
        body = (
            "เรียนผู้ขาย ts_shop56, รายละเอียดคำสั่งซื้อที่จัดส่งไม่สำเร็จ ดังนี้ "
            "หมายเลขคำสั่งซื้อ : 2609178MC6HQW4 "
            "บริษัทขนส่ง : SPX Express | หมายเลขติดตามพัสดุ : TH263561917946L"
        )
        result = ecom_calc.parse_shopee_return_emails(subject, body)
        self.assertEqual(result, [{
            "order_sn": "2609178MC6HQW4", "carrier_name": "SPX Express", "tracking_no": "TH263561917946L",
        }])


class TestParseShopeeOrderNoticeEmail(unittest.TestCase):
    """ยืนยันด้วยข้อความจากอีเมลจริงของ Shopee (info@mail.shopee.co.th) 2026-09-20 —
    คนละแบบกับอีเมลตีกลับ (TestParseShopeeReturnEmails) นี่คืออีเมลแจ้งออเดอร์ใหม่/ยกเลิก"""

    def test_transfer_order_single_item(self):
        subject = "ถึงเวลาจัดส่งสินค้าหมายเลข #260920FGENFKS8 แล้ว!"
        body = (
            "เรียน คุณ ts_shop56, คำสั่งซื้อหมายเลข #260920FGENFKS8 ได้รับการยืนยันการชำระเงินเรียบร้อยแล้ว. "
            "กรุณาจัดส่งสินค้าไปยังผู้ซื้อ saifah_02 ลูกค้าควรได้รับสินค้าภายในวันที่25 ก.ย. 2026. "
            "รายละเอียดคำสั่งซื้อ | หมายเลขคำสั่งซื้อ: | #260920FGENFKS8 |\n"
            "| วันที่สั่งซื้อ: | 19 ก.ย. 2026 23:04:28 |\n"
            "| 1. แอลทิน่า แชมพูสระผม/ครีมนวดผม ผสมเลมอนโสมและวิตามินอี ซูเลียน zhulian |\n"
            "| ตัวเลือกสินค้า: | แชมพูสระผม |\n| จำนวน: | 1 |\n| ราคา: | ฿238 |\n"
            "| ยอดรวมค่าสินค้า: | ฿238 |\n| ค่าจัดส่งสินค้า: | ฿0 |\n| ยอดที่ต้องชำระทั้งหมด: | ฿238 |"
        )
        result = ecom_calc.parse_shopee_order_notice_email(subject, body)
        self.assertEqual(result["order_sn"], "260920FGENFKS8")
        self.assertEqual(result["shop_name"], "ts_shop56")
        self.assertEqual(result["order_type"], "transfer")
        self.assertEqual(result["status"], "ยืนยันแล้ว")
        self.assertEqual(result["buyer_name"], "saifah_02")
        self.assertEqual(result["total_amount"], 238.0)
        self.assertEqual(result["shipping_fee"], 0.0)
        self.assertEqual(result["items"], [{
            "name": "แอลทิน่า แชมพูสระผม/ครีมนวดผม ผสมเลมอนโสมและวิตามินอี ซูเลียน zhulian",
            "variant": "แชมพูสระผม", "qty": 1, "price": 238.0,
        }])

    def test_cod_order_no_variant(self):
        subject = "คำสั่งซื้อชำระเงินปลายทาง #260920GMXWHBXG จากผู้ซื้อ chattikanimthanom ถูกยืนยันแล้ว"
        body = (
            "เรียน คุณ ts_shop56, คำสั่งซื้อขอชำระเงินปลายทางหมายเลข #260920GMXWHBXG ได้รับการยืนยันเรียบร้อยแล้ว "
            "รายละเอียดคำสั่งซื้อ | หมายเลขคำสั่งซื้อ: | #260920GMXWHBXG |\n"
            "| วันที่สั่งซื้อ: | 20/09/2026 09:57:48 |\n"
            "| 1. Xtra Wash เอ็กซ์ตร้า วอช ผงซักฟอกเข้มข้น 3.3 กิโลกรัม ผงซักฟอกซูเลียน แฟ้บซูเลียน |\n"
            "| จำนวน: | 3 |\n| ราคา: | ฿668 |\n"
            "| ยอดรวมค่าสินค้า: | ฿2,004 |\n| ค่าจัดส่งสินค้า: | ฿0 |"
        )
        result = ecom_calc.parse_shopee_order_notice_email(subject, body)
        self.assertEqual(result["order_sn"], "260920GMXWHBXG")
        self.assertEqual(result["order_type"], "cod")
        self.assertEqual(result["buyer_name"], "chattikanimthanom")
        self.assertEqual(result["total_amount"], 2004.0)
        self.assertEqual(result["items"][0]["variant"], None)
        self.assertEqual(result["items"][0]["qty"], 3)

    def test_cancelled_order(self):
        subject = "คำสั่งซื้อหมายเลข #260920GM8J810Q ถูกทำการยกเลิกโดย koxra"
        body = "เรียน คุณ ts_shop56, คำสั่งซื้อหมายเลข #260920GM8J810Q ถูกยกเลิกโดยร้าน koxra"
        result = ecom_calc.parse_shopee_order_notice_email(subject, body)
        self.assertEqual(result["order_sn"], "260920GM8J810Q")
        self.assertIsNone(result["order_type"])
        self.assertEqual(result["status"], "ยกเลิก")
        self.assertEqual(result["buyer_name"], "koxra")

    def test_cancelled_order_alternate_subject_wording(self):
        """พบเพิ่ม 2026-09-20 จากอีเมลจริง #260909K1U1F0KP (2026-09-16) — Shopee ใช้คำว่า
        "ถูกยกเลิก" เฉยๆ (ไม่มี "ทำการ...โดย") กับหัวเรื่องแบบนี้ด้วย ก่อนแก้ parse ไม่ออก
        เลยสักฟิลด์เดียว เพราะไม่ตรงกับแบบที่ 3 ("ถูกทำการยกเลิกโดย") ที่เช็คไว้แต่เดิม"""
        subject = "คำสั่งซื้อ  #260909K1U1F0KP จากผู้ซื้อ ig6587v6m7 ถูกยกเลิก"
        body = (
            "เรียน คุณ ts_shop56, คำสั่งซื้อหมายเลข #260909K1U1F0KP ของคุณถูกยกเลิก "
            "เนื่องจากเราไม่สามารถดำเนินการจัดส่งสินค้าให้แก่ผู้ซื้อ ig6587v6m7 ได้ตามเวลาที่กำหนด "
            "รายละเอียดคำสั่งซื้อ หมายเลขคำสั่งซื้อ: | #260909K1U1F0KP | "
            "วันที่สั่งซื้อ: | 09/09/2026 19:06:56 | "
            "1. ยาสีฟันซูเลียน สไมล์ออน zhulian smile on ว่านหางจระเข้ 250 กรัม | "
            "จำนวน: | 1 | ราคา: | ฿92 | "
            "ยอดรวมค่าสินค้า: | ฿92 | ค่าจัดส่งสินค้า: | ฿0 |"
        )
        result = ecom_calc.parse_shopee_order_notice_email(subject, body)
        self.assertEqual(result["order_sn"], "260909K1U1F0KP")
        self.assertEqual(result["shop_name"], "ts_shop56")
        self.assertIsNone(result["order_type"])
        self.assertEqual(result["status"], "ยกเลิก")
        self.assertEqual(result["buyer_name"], "ig6587v6m7")
        self.assertEqual(result["total_amount"], 92.0)

    def test_multi_item_order_synthetic(self):
        """ยืนยันว่าโครงสร้าง regex วนซ้ำได้ตามที่ออกแบบไว้ (เคสง่าย ไม่มี URL รูปสินค้าคั่น)"""
        subject = "ถึงเวลาจัดส่งสินค้าหมายเลข #TEST123 แล้ว!"
        body = (
            "เรียน คุณ jipata5656, รายละเอียดคำสั่งซื้อ | หมายเลขคำสั่งซื้อ: | #TEST123 |\n"
            "| วันที่สั่งซื้อ: | 01/01/2026 00:00:00 |\n"
            "| 1. สินค้า A |\n| จำนวน: | 2 |\n| ราคา: | ฿100 |\n"
            "| 2. สินค้า B |\n| จำนวน: | 5 |\n| ราคา: | ฿50 |\n"
            "| ยอดรวมค่าสินค้า: | ฿450 |"
        )
        result = ecom_calc.parse_shopee_order_notice_email(subject, body)
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["items"][0]["name"], "สินค้า A")
        self.assertEqual(result["items"][0]["qty"], 2)
        self.assertEqual(result["items"][1]["name"], "สินค้า B")
        self.assertEqual(result["items"][1]["qty"], 5)

    def test_multi_item_order_real_email_with_image_links(self):
        """ยืนยันด้วยอีเมลจริง #260920H0R7Y4S4 (2026-09-20, ts_shop56) — ออเดอร์แรกที่เจอจริง
        ว่ามี 2 สินค้าในอีเมลเดียว แต่ละสินค้ามีลิงก์รูปภาพ [](url) คั่นก่อนหน้า — URL พวกนี้
        เป็น query-string เข้ารหัสยาวที่มี "ตัวเลข.ตัวเลข" ปนอยู่ (เช่น "-i.262949.21589696184/")
        ซึ่งก่อนแก้ ทำให้ _ORDER_ITEM_RE จับ URL ปนเข้าไปในชื่อสินค้า (regression test)"""
        subject = "คำสั่งซื้อชำระเงินปลายทาง #260920H0R7Y4S4 จากผู้ซื้อ wanladaneramitkhonburi ถูกยืนยันแล้ว"
        body = (
            "เรียน คุณ ts_shop56, คำสั่งซื้อขอชำระเงินปลายทางหมายเลข #260920H0R7Y4S4 "
            "ได้รับการยืนยันเรียบร้อยแล้ว รายละเอียดคำสั่งซื้อ | หมายเลขคำสั่งซื้อ: | #260920H0R7Y4S4 |\n"
            "| วันที่สั่งซื้อ: | 20/09/2026 13:28:49 |\n"
            "[](https://shopee.co.th/universal-link/%E0%B8%81%E0%B8%B2%E0%B9%81%E0%B8%9F-"
            "i.262949.21589696184/?smtt=583.262957.7)\n"
            "| 1. กาแฟโสม ซูเลียน กาแฟคอลลาเจน (บรรจุ 18 ซอง) กาแฟโสมผสมคอลลาเจน คอฟฟี่พลัส ของแท้ |\n"
            "| จำนวน: | 1 |\n| ราคา: | ฿253 |\n"
            "[](https://shopee.co.th/universal-link/%E0%B8%81%E0%B8%B2%E0%B9%81%E0%B8%9F-"
            "i.262949.22970658454/?smtt=583.262957.7)\n"
            "| 2. กาแฟซูเลียน ไวท์คอฟฟี่ 3 อิน 1 เลส ซูการ์ 15 ซอง น้ำตาลน้อย คอฟฟี่พลัส "
            "White coffee plus 3 in 1 Less Sugar ของแท้ 100% |\n"
            "| จำนวน: | 1 |\n| ราคา: | ฿222 |\n"
            "| ยอดรวมค่าสินค้า: | ฿475 |\n| ค่าจัดส่งสินค้า: | ฿0 |\n| ยอดที่ต้องชำระทั้งหมด: | ฿475 |"
        )
        result = ecom_calc.parse_shopee_order_notice_email(subject, body)
        self.assertEqual(result["order_sn"], "260920H0R7Y4S4")
        self.assertEqual(result["shop_name"], "ts_shop56")
        self.assertEqual(result["order_type"], "cod")
        self.assertEqual(result["total_amount"], 475.0)
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(
            result["items"][0]["name"],
            "กาแฟโสม ซูเลียน กาแฟคอลลาเจน (บรรจุ 18 ซอง) กาแฟโสมผสมคอลลาเจน คอฟฟี่พลัส ของแท้",
        )
        self.assertEqual(result["items"][0]["qty"], 1)
        self.assertEqual(result["items"][0]["price"], 253.0)
        self.assertEqual(
            result["items"][1]["name"],
            "กาแฟซูเลียน ไวท์คอฟฟี่ 3 อิน 1 เลส ซูการ์ 15 ซอง น้ำตาลน้อย คอฟฟี่พลัส "
            "White coffee plus 3 in 1 Less Sugar ของแท้ 100%",
        )
        self.assertEqual(result["items"][1]["qty"], 1)
        self.assertEqual(result["items"][1]["price"], 222.0)

    def test_unrelated_email_returns_none(self):
        self.assertIsNone(ecom_calc.parse_shopee_order_notice_email("แจ้งเตือนอย่างอื่น", "เนื้อหาอะไรก็ได้"))

    def test_transfer_order_compact_template_empty_variant_line(self):
        """ยืนยันด้วยอีเมลจริง #260920GPANG1SF (2026-09-20, ts_shop56) — เทมเพลตสั้นของอีเมล
        "ถึงเวลาจัดส่งสินค้า...แล้ว!" มีบรรทัด "ตัวเลือกสินค้า:" อยู่เสมอแม้ไม่มี variant จริง
        (ค่าว่างเปล่า) ก่อนแก้ (.+?) เป็น (.*?) ข้อความ "ตัวเลือกสินค้า:" ไปติดท้ายชื่อสินค้า
        (regression test)"""
        subject = "ถึงเวลาจัดส่งสินค้าหมายเลข #260920GPANG1SF แล้ว!"
        body = (
            "เรียน คุณ ts_shop56, คำสั่งซื้อหมายเลข #260920GPANG1SF ได้รับการยืนยันการชำระเงินเรียบร้อยแล้ว. "
            "กรุณาจัดส่งสินค้าไปยังผู้ซื้อ pcherdchan รายละเอียดคำสั่งซื้อ | หมายเลขคำสั่งซื้อ: | #260920GPANG1SF |\n"
            "| วันที่สั่งซื้อ: | 20 ก.ย. 2026 10:22:17 |\n"
            "| 1. กาแฟโสม ซูเลียน กาแฟคอลลาเจน (บรรจุ 18 ซอง) กาแฟโสมผสมคอลลาเจน คอฟฟี่พลัส ของแท้ |\n"
            "| ตัวเลือกสินค้า: | |\n| จำนวน: | 1 |\n| ราคา: | ฿253 |\n"
            "| ยอดรวมค่าสินค้า: | ฿253 |\n| ค่าจัดส่งสินค้า: | ฿0 |"
        )
        result = ecom_calc.parse_shopee_order_notice_email(subject, body)
        self.assertEqual(result["order_type"], "transfer")
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(
            result["items"][0]["name"],
            "กาแฟโสม ซูเลียน กาแฟคอลลาเจน (บรรจุ 18 ซอง) กาแฟโสมผสมคอลลาเจน คอฟฟี่พลัส ของแท้",
        )
        self.assertIsNone(result["items"][0]["variant"])
        self.assertEqual(result["items"][0]["qty"], 1)
        self.assertEqual(result["items"][0]["price"], 253.0)


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

    def test_fully_returned_line_excluded_from_margin(self):
        # คืนสินค้าเต็มจำนวน (net_qty = 0) พร้อมค่าปรับติดลบจาก Lazada — ไม่ควรถูกรวม
        # เข้าไปในกำไร/ขาดทุนของสินค้าเลย (ไม่มี qty ที่ขายจับคู่ด้วย)
        sales = [
            {"order_sn": "F1", "product_id": "P1", "item_id_platform": "SKU1",
             "qty": 2, "returned_qty": 2, "net_amount": -74.46, "item_price": 476,
             "order_status": "สินค้าถูกคืน"},
            {"order_sn": "F2", "product_id": "P1", "item_id_platform": "SKU1",
             "qty": 1, "returned_qty": 0, "net_amount": 175.04, "item_price": 242,
             "order_status": "ยืนยันแล้ว"},
        ]
        agg, pending, _, _ = ecom_calc.aggregate_product_margin(sales, {"F1", "F2"}, {}, "lazada")
        self.assertEqual(pending, 0)
        self.assertEqual(agg["P1"], {"qty": 1.0, "net": 175.04, "gross": 242.0})

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
