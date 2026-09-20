"""Pure calculation helpers for E-commerce (Shopee/Lazada/TikTok) กำไร/ต้นทุน/ค่าส่งเกิน —
ย้ายมาจาก database.py (ตามแพทเทิร์นเดียวกับ calc_logic.py) เพราะเป็น business logic
ล้วนๆ ไม่แตะ streamlit/supabase เลย ทำให้ทดสอบได้จริงด้วย unittest (ดู
tests/test_ecom_calc.py) — database.py เหลือแค่ fetch ข้อมูลแล้วเรียกฟังก์ชันพวกนี้

ย้ายแบบ byte-for-byte จากของเดิมทุกจุด (ไม่ปรับสูตร) ยืนยันตัวเลขจริงตรงเป๊ะกับ
ก่อนย้ายแล้ว (ดู commit message)"""
import re

PLATFORM_LABELS = {"shopee": "Shopee", "lazada": "Lazada", "tiktok": "TikTok"}

# ยืนยันจากอีเมลจริงของ Shopee (info@mail.shopee.co.th) 2026-09-19 — ทั้ง 2 แบบหัวเรื่อง
# ("พัสดุกำลังทำการจัดส่งไปยังผู้ขาย..." / "...ไม่สามารถจัดส่งคืนร้านค้าได้สำเร็จ...") มี
# บล็อกข้อมูลรูปแบบเดียวกันเป๊ะในเนื้อหา: "หมายเลขคำสั่งซื้อ : X บริษัทขนส่ง : Y
# หมายเลขติดตามพัสดุ : Z" — findall เผื่อบางฉบับมีมากกว่า 1 ออเดอร์ต่ออีเมล (Lazada/TikTok
# ไม่มีอีเมลแจ้งตีคืนอัตโนมัติแบบนี้เลย ยืนยันแล้ว — ฟังก์ชันนี้จึงรองรับเฉพาะฟอร์แมต Shopee)
#
# หมายเหตุ: ตัวอีเมลบางฉบับมีข้อความ "(แจ้งครั้งที่ N)" กำกับ แต่ไม่ใช่ทุกฉบับ — ออเดอร์
# เดียวกันมักถูกส่งอีเมลแจ้งซ้ำหลายวันติดกันโดยไม่มีเลขกำกับเลยก็ได้ (ยืนยันจากอีเมลจริง)
# จึงไม่ใช้ตัวเลขนี้นับจำนวนครั้ง — ปล่อยให้ database.upsert_ecommerce_return_email() นับเอง
# จากจำนวนครั้งที่ถูกเรียก (นับ 1 ทุกครั้งที่เจออีเมลใหม่ ไม่สนใจเลขในเนื้อหา)
_SHOPEE_RETURN_ORDER_RE = re.compile(
    r"หมายเลขคำสั่งซื้อ\s*[:：]\s*(\S+).*?"
    # \|? ก่อน "หมายเลขติดตามพัสดุ" — กัน "|" (ตัวคั่น cell จาก _html_to_text ใน
    # tools/email_daily_digest.py ตอนอีเมลเป็น HTML ล้วน ไม่มี text/plain) ติดท้าย
    # ชื่อขนส่งไปด้วย เพราะ "|" ไม่ใช่ whitespace \s* จึงข้ามไม่ได้ ยืนยันจากข้อมูลจริงใน DB
    # 2026-09-20 (order #2609178MC6HQW4) ที่ได้ carrier_name="SPX Express |" ก่อนแก้
    r"บริษัทขนส่ง\s*[:：]\s*(.+?)\s*\|?\s*หมายเลขติดตามพัสดุ\s*[:：]\s*(\S+)",
    re.DOTALL,
)


def parse_shopee_return_emails(subject: str, body: str) -> list[dict]:
    """แกะออเดอร์ที่ตีกลับ/จัดส่งคืนร้านไม่สำเร็จ จากอีเมลแจ้งเตือนของ Shopee — คืน list
    ของ {order_sn, carrier_name, tracking_no} (ปกติมีแค่ 1 รายการต่ออีเมล แต่เผื่อกรณี
    อีเมลเดียวรวมหลายออเดอร์) คืน [] ถ้าไม่ใช่อีเมลแจ้งตีคืน/parse ไม่ได้"""
    text = " ".join(body.split())  # ยุบ whitespace/newline ให้ regex ข้ามtag/ลิงก์คั่นกลางได้
    matches = _SHOPEE_RETURN_ORDER_RE.findall(text)
    return [
        {"order_sn": order_sn.strip(), "carrier_name": carrier.strip(), "tracking_no": tracking.strip()}
        for order_sn, carrier, tracking in matches
    ]


# ยืนยันจากอีเมลจริงของ Shopee (info@mail.shopee.co.th) 2026-09-20 — 3 แบบหัวเรื่อง:
#   1. "ถึงเวลาจัดส่งสินค้าหมายเลข #X แล้ว!"                      → ออเดอร์โอนปกติ ยืนยันแล้ว
#   2. "คำสั่งซื้อชำระเงินปลายทาง #X จากผู้ซื้อ Y ถูกยืนยันแล้ว"     → ออเดอร์ COD ยืนยันแล้ว
#   3. "คำสั่งซื้อหมายเลข #X ถูกทำการยกเลิกโดย Y"                   → ออเดอร์ถูกยกเลิก
# ทุกแบบมีบล็อก "รายละเอียดคำสั่งซื้อ" โครงสร้างเดียวกัน (แปลงมาจาก HTML table เป็น
# pipe-table ในเนื้อหา plaintext): "| N. ชื่อสินค้า | [ตัวเลือกสินค้า: | variant |] จำนวน: |
# qty | ราคา: | ฿price |" ซ้ำได้หลายรายการต่อออเดอร์ (ยังไม่เคยเห็นตัวอย่างจริงที่มี 2+
# รายการ — โครงสร้าง regex รองรับไว้เผื่อ แต่ยังไม่ยืนยัน) ปิดท้ายด้วย "ยอดรวมค่าสินค้า: |
# ฿total |" / "ค่าจัดส่งสินค้า: | ฿fee |" — salutation "เรียน คุณ {shop},​" ในเนื้อหาบอกว่า
# เป็นบัญชีร้านไหน (แม่นกว่าอนุมานจาก label บัญชีอีเมล)
_ORDER_ITEM_RE = re.compile(
    r"\d+\.\s*(.+?)\s+"
    # (.*?) ไม่ใช่ (.+?) — บางเทมเพลตของ Shopee (อีเมล "ถึงเวลาจัดส่งสินค้า...แล้ว!" แบบสั้น)
    # มีบรรทัด "ตัวเลือกสินค้า:" อยู่แต่ไม่มีค่า (ไม่มี variant) ถ้าบังคับ (.+?) อย่างน้อย 1
    # ตัวอักษร regex จะหาไม่เจอจุดจบเลย แล้ว backtrack ออกไปทำให้ "ตัวเลือกสินค้า:" ไปติด
    # ท้ายชื่อสินค้าแทน (ยืนยันจากอีเมลจริง #260920GPANG1SF/#260920GMB0EDEQ/#260920GM8J810Q
    # 2026-09-20 — ล้วนเป็นเทมเพลตสั้นที่มีบรรทัดนี้ว่างเปล่า)
    r"(?:ตัวเลือกสินค้า\s*:\s*(.*?)\s+)?"
    r"จำนวน\s*:\s*(\d+)\s+"
    r"ราคา\s*:\s*฿([\d,]+(?:\.\d+)?)",
)
_ORDER_SN_BODY_RE = re.compile(r"หมายเลขคำสั่งซื้อ\s*:\s*\|?\s*#(\w+)")
_ORDER_SN_SUBJECT_RE = re.compile(r"#(\w+)")
_ORDER_SHOP_RE = re.compile(r"เรียน\s*คุณ\s*(.+?)\s*,")
_ORDER_BUYER_RES = [
    re.compile(r"จากผู้ซื้อ\s+(\S+)"),
    re.compile(r"ไปยังผู้ซื้อ\s+(\S+)"),
    re.compile(r"ยกเลิกโดย\s+(\S+)"),
]
_ORDER_TOTAL_RE = re.compile(r"ยอดรวมค่าสินค้า\s*:\s*\|\s*฿([\d,]+(?:\.\d+)?)")
_ORDER_SHIP_FEE_RE = re.compile(r"ค่าจัดส่งสินค้า\s*:\s*\|\s*฿([\d,]+(?:\.\d+)?)")
_ORDER_DATE_RE = re.compile(r"วันที่สั่งซื้อ\s*:\s*\|?\s*(.+?)\s*\|")


def _num(s: str | None) -> float | None:
    return float(s.replace(",", "")) if s else None


def parse_shopee_order_notice_email(subject: str, body: str) -> dict | None:
    """แกะอีเมลแจ้งออเดอร์ใหม่/ยกเลิกของ Shopee — คืน {order_sn, shop_name, order_type,
    status, buyer_name, total_amount, shipping_fee, order_date,
    items: [{name, variant, qty, price}]} หรือ None ถ้าหัวเรื่องไม่ตรงกับ 3 แบบที่รู้จัก
    (ดูคอมเมนต์ด้านบน)"""
    if "ถึงเวลาจัดส่งสินค้าหมายเลข" in subject:
        order_type, status = "transfer", "ยืนยันแล้ว"
    elif "คำสั่งซื้อชำระเงินปลายทาง" in subject and "ถูกยืนยันแล้ว" in subject:
        order_type, status = "cod", "ยืนยันแล้ว"
    elif "ถูกทำการยกเลิกโดย" in subject:
        order_type, status = None, "ยกเลิก"
    else:
        return None

    text = " ".join(body.split())
    # ตัด markdown link เปล่า "[](url)" ออกก่อน (รูปสินค้า/ปุ่มลิงก์ในอีเมล) — URL พวกนี้มัก
    # เป็น query-string เข้ารหัสยาวๆ ที่มี "ตัวเลข.ตัวเลข" ปนอยู่ (เช่น "-i.262949.21589696184/")
    # ซึ่งไปแมตช์ผิดเป็นจุดเริ่มรายการสินค้าใน _ORDER_ITEM_RE ได้ (ยืนยันจากอีเมลจริง 2 สินค้า
    # ในออเดอร์เดียว #260920H0R7Y4S4 2026-09-20 — ชื่อสินค้าถูกดึงมาปนกับเศษ URL ก่อนแก้)
    text = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", text)

    m = _ORDER_SN_BODY_RE.search(text) or _ORDER_SN_SUBJECT_RE.search(subject)
    if not m:
        return None
    order_sn = m.group(1)

    shop_m = _ORDER_SHOP_RE.search(text)
    shop_name = shop_m.group(1).strip() if shop_m else None

    buyer_name = None
    for pat in _ORDER_BUYER_RES:
        bm = pat.search(subject) or pat.search(text)
        if bm:
            buyer_name = bm.group(1)
            break

    total_m = _ORDER_TOTAL_RE.search(text)
    ship_m = _ORDER_SHIP_FEE_RE.search(text)
    date_m = _ORDER_DATE_RE.search(text)

    # จำกัดช่วงค้นหารายการสินค้าไว้แค่ระหว่าง "วันที่สั่งซื้อ" ถึง "ยอดรวมค่าสินค้า" กัน
    # จับเลข/จุดที่ไม่เกี่ยวในส่วนอื่นของอีเมลผิดเป็นรายการสินค้า — ตัด "|" ที่เป็นแค่เส้นแบ่ง
    # ตาราง (แปลงจาก HTML) ออกก่อน เพราะบางทีมี "| |" คั่นระหว่างแถวทำให้ regex เดิมไม่ match
    si = text.find("วันที่สั่งซื้อ")
    ei = text.find("ยอดรวมค่าสินค้า")
    item_section = text[si:ei] if si != -1 and ei != -1 and ei > si else text
    item_section = " ".join(item_section.replace("|", " ").split())

    items = [
        {
            "name": name.strip(),
            "variant": variant.strip() if variant else None,
            "qty": int(qty),
            "price": _num(price),
        }
        for name, variant, qty, price in _ORDER_ITEM_RE.findall(item_section)
    ]

    return {
        "order_sn": order_sn,
        "shop_name": shop_name,
        "order_type": order_type,
        "status": status,
        "buyer_name": buyer_name,
        "total_amount": _num(total_m.group(1)) if total_m else None,
        "shipping_fee": _num(ship_m.group(1)) if ship_m else None,
        "order_date": date_m.group(1).strip() if date_m else None,
        "items": items,
    }


def settled_order_sns(income_rows: list[dict]) -> set[str]:
    """order_sn ทั้งหมดที่มีรายงานยอดโอน (Income) มายืนยันแล้ว — ใช้เช็คว่าออเดอร์นี้
    "ปิดยอด" แล้วหรือยังรอ (ยังไม่มี Income = ยังไม่รู้ยอดจริง ไม่ควรเอามาคิดกำไร)"""
    return {r["order_sn"] for r in income_rows}


def pending_income_rows(sales_rows: list[dict], settled_sns: set[str]) -> list[dict]:
    """แถวออเดอร์ (ไม่ใช่แค่ตัวเลขสรุป) ที่ขายแล้วแต่ยังไม่มีรายงาน Income มายืนยัน —
    ไม่รวมออเดอร์ที่ยกเลิกแล้ว (จะไม่มี Income มาให้รอเลย ไม่ใช่ "ยังไม่มา") ใช้ไล่เช็ค
    เป็นออเดอร์ๆ ว่าออเดอร์ไหนกันแน่ที่ยังไม่ match ต่างจาก pending_qty/pending_since ใน
    aggregate_product_margin ที่เป็นแค่ตัวเลขสรุปรวม"""
    rows = []
    for r in sales_rows:
        if r.get("order_status") == "ยกเลิกแล้ว" or r["order_sn"] in settled_sns:
            continue
        pid = r.get("product_id")
        qty = float(r.get("qty") or 0) - float(r.get("returned_qty") or 0)
        rows.append({
            "วันที่สั่งซื้อ": r.get("sale_date"),
            "ร้าน": r.get("shop_name"),
            "เลขออเดอร์": r["order_sn"],
            "สินค้า": (r.get("products") or {}).get("name") or r.get("item_name") or pid or "ยังไม่ map",
            "จำนวน": qty,
            "ยอด": float(r.get("item_price") or 0),
            "สถานะออเดอร์": r.get("order_status") or "-",
        })
    return rows


def shipping_overcharge_extra(row: dict) -> float:
    """ส่วนต่างค่าส่งที่ Shopee หักจากร้านเกินกว่าที่ประเมินไว้ล่วงหน้า —
    estimated = ค่าส่งที่ผู้ซื้อจ่าย + Shopee ออกให้ (ประเมินตอนสั่งซื้อ)
    actual = ค่าส่งที่หักจริงตอนชั่งพัสดุจริง — ผลลัพธ์เป็นบวกแปลว่าโดนหักเกิน"""
    estimated = float(row.get("buyer_paid_shipping") or 0) + float(row.get("shopee_subsidized_shipping") or 0)
    actual = float(row.get("shipping_fee_charged") or 0)
    return actual - estimated


def aggregate_product_margin(
    sales_rows: list[dict], settled_sns: set[str], prod_map: dict, platform: str,
) -> tuple[dict[str, dict], float, str | None, str | None]:
    """รวมยอดขาย/ยอดเงินที่ได้รับจริงต่อสินค้า (เฉพาะออเดอร์ที่ปิดยอดแล้ว) — คืน
    (agg: {product_id: {qty, net, gross}}, pending_qty: จำนวนชิ้นที่ยังไม่ปิดยอด,
    pending_since/pending_until: sale_date เก่าสุด/ล่าสุดในบรรดาที่ยังไม่ปิดยอด หรือ
    None ถ้าไม่มีค้าง — ปกติออเดอร์จะส่งมาก่อน แล้ว Income จะตามมาทีหลังหลายอาทิตย์ ใช้
    บอกผู้ใช้ว่าต้องไปโหลดรายงาน Income ของช่วงวันที่เท่าไหร่มาอัปโหลดเพิ่ม ไม่ใช่แค่
    จำนวนชิ้นเฉยๆ) ตัวคูณ units_per_pack ใช้กับ SKU ที่ map เป็นแพ็ครวม

    แถวที่ถูกคืนสินค้าเต็มจำนวน (net_qty <= 0 หลังหัก returned_qty) ไม่เอามารวมกำไร/
    ขาดทุนต่อสินค้าเลย — ไม่ใช่การขาดทุนของสินค้าที่ขายได้จริง แต่เป็นค่าปรับ/ยอดหักคืน
    ของ Lazada/Shopee ต่อออเดอร์นั้นเอง ถ้ารวมเข้าไปจะเอา net_amount ติดลบของแถวคืนสินค้า
    (ไม่มี qty ที่ขายจับคู่ด้วยเลย) ไปหารเฉลี่ยกับสินค้าชิ้นอื่นที่ขายได้จริงในสินค้าเดียวกัน
    ทำให้กำไร/ชิ้นของสินค้านั้นดูแย่เกินจริง (ยอดขาดทุนจริงยังเห็นได้ที่ระดับออเดอร์ใน
    order_anomaly_rows ตามปกติ — ไม่ได้ถูกซ่อนไปเฉยๆ)"""
    agg: dict[str, dict] = {}
    pending_qty = 0.0
    pending_since = None
    pending_until = None
    for r in sales_rows:
        if r.get("order_status") == "ยกเลิกแล้ว":
            continue
        pid = r["product_id"]
        mult = prod_map.get((platform, r["item_id_platform"]), {}).get("units_per_pack", 1)
        net_qty = (float(r["qty"] or 0) - float(r.get("returned_qty") or 0)) * mult
        if r["order_sn"] not in settled_sns:
            pending_qty += net_qty
            _sd = r.get("sale_date")
            if _sd and (pending_since is None or _sd < pending_since):
                pending_since = _sd
            if _sd and (pending_until is None or _sd > pending_until):
                pending_until = _sd
            continue
        if net_qty <= 0:
            continue
        a = agg.setdefault(pid, {"qty": 0.0, "net": 0.0, "gross": 0.0})
        a["qty"] += net_qty
        a["net"] += float(r.get("net_amount") or 0)
        a["gross"] += float(r.get("item_price") or 0)
    return agg, pending_qty, pending_since, pending_until


def product_margin_rows(agg: dict[str, dict], products: dict[str, dict], platform: str) -> list[dict]:
    """แปลง agg (จาก aggregate_product_margin) เป็นแถวตารางกำไรต่อสินค้า — ชื่อคอลัมน์
    จำนวนชิ้นระบุแพลตฟอร์มจริงตาม platform ที่ส่งเข้ามา (เดิม hardcode "Shopee" เฉยๆ
    ไม่ว่าจะดู Lazada/TikTok อยู่ก็ตาม เป็นข้อมูลผิดที่โชว์ในหน้าแอปจริง)"""
    _label = PLATFORM_LABELS.get(platform, platform.capitalize())
    rows = []
    for pid, a in agg.items():
        prod = products.get(pid, {})
        cost = float(prod.get("cost_price") or 0)
        pv = float(prod.get("points_per_unit") or 0)
        qty_sold = a["qty"]
        profit = a["net"] - cost * qty_sold
        # อัตราส่วนยอดเงินที่ได้รับจริงเทียบกับ "ราคาขายสุทธิ" ต่อบรรทัด (item_price
        # จาก Order.all — ราคาที่ขายจริงในแต่ละออเดอร์ หลังหักโค้ดส่วนลด/โปรโมชัน
        # ที่ Shopee/ผู้ซื้อใช้ ณ ตอนนั้น ไม่ใช่ราคาที่ตั้งไว้ในหน้าสินค้า) ใช้ย้อน
        # คำนวณว่าราคาขายสุทธิเฉลี่ยต่อชิ้นต้องได้อย่างน้อยเท่าไหร่ถึงจะคุ้มทุน —
        # ถ้ามีโค้ดส่วนลดเพิ่มอีกตอนขายจริง ราคาที่ตั้งในหน้าสินค้าอาจต้องสูงกว่านี้
        _net_rate = (a["net"] / a["gross"]) if a["gross"] else 0
        breakeven_price = round(cost / _net_rate, 2) if _net_rate > 0 else None
        rows.append({
            "รหัสสินค้า": pid,
            "ชื่อสินค้า": prod.get("name", pid),
            "ต้นทุน/ชิ้น": cost,
            f"ขายผ่าน {_label} (ชิ้น)": qty_sold,
            "PV": round(pv * qty_sold, 2),
            "ยอดเงินที่ได้รับจริง": round(a["net"], 2),
            "กำไรรวม": round(profit, 2),
            "กำไร/ชิ้น": round(profit / qty_sold, 2) if qty_sold else 0,
            "ราคาขายสุทธิที่ควรได้ต่อชิ้น (คุ้มทุน)": breakeven_price,
        })
    return rows


def aggregate_order_costs(
    sales_rows: list[dict], incomes: dict[str, tuple[str, float]], prod_map: dict,
    products: dict[str, dict], platform: str,
) -> dict[str, dict]:
    """รวมต้นทุนรายออเดอร์ (เฉพาะออเดอร์ที่มี Income ยืนยันแล้ว) — คืน
    {order_sn: {cost, unmapped, items, sale_date}} unmapped=True ถ้ามี SKU ไหนใน
    ออเดอร์ยังไม่ map เพราะคำนวณต้นทุนไม่ครบ ใช้ร่วมกันโดย order_profit_summary และ
    order_anomaly_rows ด้านล่าง"""
    by_order: dict[str, dict] = {}
    for r in sales_rows:
        sn = r["order_sn"]
        if sn not in incomes or r.get("order_status") == "ยกเลิกแล้ว":
            continue
        o = by_order.setdefault(sn, {"cost": 0.0, "unmapped": False, "items": [], "sale_date": r.get("sale_date")})
        pid = r["product_id"]
        if not pid:
            o["unmapped"] = True
            continue
        mult = prod_map.get((platform, r["item_id_platform"]), {}).get("units_per_pack", 1)
        qty = (float(r["qty"] or 0) - float(r.get("returned_qty") or 0)) * mult
        cost = float(products.get(pid, {}).get("cost_price") or 0)
        o["cost"] += cost * qty
        o["items"].append(products.get(pid, {}).get("name") or r.get("item_name") or pid)
    return by_order


def order_profit_summary(incomes: dict[str, tuple[str, float]], by_order: dict[str, dict]) -> dict:
    """สรุปกำไรรวม/ขาดทุนรวม โดยจัดกำไร-ขาดทุนเป็นรายออเดอร์ก่อนรวม (รับประกันว่า
    บวกกันข้ามช่วงเวลาได้ตรงๆ) ข้ามออเดอร์ที่ unmapped/ไม่มีสินค้าเลย"""
    total_profit = 0.0
    total_loss = 0.0
    for sn, o in by_order.items():
        if o["unmapped"] or not o["items"]:
            continue
        _, net = incomes[sn]
        profit = net - o["cost"]
        if profit >= 0:
            total_profit += profit
        else:
            total_loss += profit
    return {
        "total_profit": round(total_profit, 2),
        "total_loss": round(total_loss, 2),
        "net": round(total_profit + total_loss, 2),
    }


def order_anomaly_rows(incomes: dict[str, tuple[str, float]], by_order: dict[str, dict], warn_pct: float) -> list[dict]:
    """หาออเดอร์ที่กำไรติดลบ/ต่ำกว่า warn_pct ของยอดโอน — คืนแถวพร้อมเลขที่ออเดอร์
    ข้ามออเดอร์ที่ unmapped/ไม่มีสินค้าเลย (คำนวณต้นทุนไม่ครบ ไม่ควร flag ว่าผิดปกติ)"""
    rows = []
    for sn, o in by_order.items():
        if o["unmapped"] or not o["items"]:
            continue
        shop_name, net = incomes[sn]
        profit = net - o["cost"]
        margin_pct = (profit / net * 100) if net else 0
        if profit >= 0 and margin_pct >= warn_pct:
            continue
        rows.append({
            "สถานะ": "🔴 ขาดทุน" if profit < 0 else "🟡 กำไรต่ำ",
            "เลขออเดอร์": sn,
            "วันที่สั่งซื้อ": o["sale_date"],
            "ร้าน": shop_name,
            "สินค้า": ", ".join(dict.fromkeys(o["items"])),
            "ต้นทุนรวม": round(o["cost"], 2),
            "ยอดเงินที่ได้รับจริง": round(net, 2),
            "กำไร": round(profit, 2),
        })
    return rows
