"""Pure calculation helpers for E-commerce (Shopee/Lazada/TikTok) กำไร/ต้นทุน/ค่าส่งเกิน —
ย้ายมาจาก database.py (ตามแพทเทิร์นเดียวกับ calc_logic.py) เพราะเป็น business logic
ล้วนๆ ไม่แตะ streamlit/supabase เลย ทำให้ทดสอบได้จริงด้วย unittest (ดู
tests/test_ecom_calc.py) — database.py เหลือแค่ fetch ข้อมูลแล้วเรียกฟังก์ชันพวกนี้

ย้ายแบบ byte-for-byte จากของเดิมทุกจุด (ไม่ปรับสูตร) ยืนยันตัวเลขจริงตรงเป๊ะกับ
ก่อนย้ายแล้ว (ดู commit message)"""

PLATFORM_LABELS = {"shopee": "Shopee", "lazada": "Lazada", "tiktok": "TikTok"}


def settled_order_sns(income_rows: list[dict]) -> set[str]:
    """order_sn ทั้งหมดที่มีรายงานยอดโอน (Income) มายืนยันแล้ว — ใช้เช็คว่าออเดอร์นี้
    "ปิดยอด" แล้วหรือยังรอ (ยังไม่มี Income = ยังไม่รู้ยอดจริง ไม่ควรเอามาคิดกำไร)"""
    return {r["order_sn"] for r in income_rows}


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
