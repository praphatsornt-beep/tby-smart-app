"""Parser สำหรับไฟล์ 'Income Overview' export จาก Lazada Seller Centre (รายรับของฉัน >
รายละเอียดรายรับ > เลือกวันที่ > ดาวน์โหลด) — ต่างจาก Shopee ตรงที่ไฟล์เดียวมีทั้งรายการสินค้าต่อออเดอร์
และยอดเงินสุทธิ ไม่ต้องแยก Order.all/Income เป็น 2 ไฟล์เหมือน Shopee

โครงสร้างไฟล์: 1 แถว = 1 รายการธุรกรรมย่อยของสินค้า 1 ชิ้น (ยอดรวมค่าสินค้า/
ค่าธรรมเนียมการชำระเงิน/หักค่าธรรมเนียมการขายสินค้า/Premium Package ฯลฯ) แชร์
"รหัสสินค้าในคำสั่งซื้อ" เดียวกัน — ยืนยันจากข้อมูลจริงแล้วว่าถ้าซื้อ N ชิ้น SKU
เดียวกันในออเดอร์เดียว จะได้ "รหัสสินค้าในคำสั่งซื้อ" แยกกัน N ชุด (ราคาต่อชุดหารลงตัว
เท่ากันเป๊ะข้ามหลายออเดอร์) จึงนับจำนวนชิ้นจาก nunique ของรหัสนี้ได้ตรงๆ โดยไม่ต้องมี
คอลัมน์ "จำนวน" แยกแบบ Shopee"""
import uuid

import pandas as pd


def _parse_date(val) -> str | None:
    if pd.isna(val):
        return None
    ts = pd.to_datetime(val, errors="coerce")
    return None if pd.isna(ts) else ts.strftime("%Y-%m-%d")


def _str_or_none(val) -> str | None:
    if pd.isna(val):
        return None
    s = str(val).strip()
    return s or None


def _id_str_or_none(val) -> str | None:
    """เหมือน _str_or_none แต่กัน pandas อ่านคอลัมน์ ID เป็น float แล้วได้ต่อท้าย
    '.0' (เช่น 'หมายเลขคำสั่งซื้อ'/'รหัสสินค้าในคำสั่งซื้อ' เป็นตัวเลขล้วนในไฟล์
    แต่ pandas เดา dtype เป็น float เพราะมีบางแถวว่าง)"""
    if pd.isna(val):
        return None
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    s = str(val).strip()
    return s or None


_TXN_PRODUCT_TOTAL = "ยอดรวมค่าสินค้า"
_TXN_RETURN = "หักเงินค่าสินค้า (คืนสินค้า)"


def parse_income_overview(file, shop_name: str) -> tuple[list[dict], list[dict]]:
    """อ่านไฟล์ 'Income Overview...xlsx' คืน (sales_rows, income_rows) ส่งเข้า
    db.upsert_ecommerce_sales / db.upsert_ecommerce_order_income ตรงๆ ได้เลย
    (ไฟล์นี้ไม่บอกชื่อร้านแบบให้ parse อัตโนมัติเหมือน Shopee Income — รับ
    shop_name จากผู้เรียกเอง เหมือน Shopee Order.all)"""
    df = pd.read_excel(file, sheet_name=0, header=0)
    df["_order_sn"] = df["หมายเลขคำสั่งซื้อ"].apply(_id_str_or_none)
    df["_item_id"] = df["รหัสสินค้าในคำสั่งซื้อ"].apply(_id_str_or_none)
    df["_sku"] = df["SKU ร้านค้า"].apply(_str_or_none)
    df["_sku"] = df["_sku"].fillna(df["Lazada SKU"].apply(_str_or_none))
    df["_sku"] = df["_sku"].fillna(df["ชื่อสินค้า"].apply(_str_or_none))
    df = df[df["_order_sn"].notna() & df["_item_id"].notna() & df["_sku"].notna()]
    if df.empty:
        return [], []

    sales_rows = []
    for (order_sn, sku), g in df.groupby(["_order_sn", "_sku"]):
        qty_rows = g[g["ชื่อรายการธุรกรรม"] == _TXN_PRODUCT_TOTAL]
        if qty_rows.empty:
            continue
        return_rows = g[g["ชื่อรายการธุรกรรม"] == _TXN_RETURN]
        first = g.iloc[0]
        sales_rows.append({
            "id": str(uuid.uuid4()),
            "platform": "lazada",
            "shop_name": shop_name,
            "order_sn": order_sn,
            "sale_date": _parse_date(first.get("วันที่สร้างคำสั่งซื้อ")),
            "product_id": None,
            "item_id_platform": sku,
            "item_name": _str_or_none(first.get("ชื่อสินค้า")) or sku,
            "qty": float(qty_rows["_item_id"].nunique()),
            "item_price": float(qty_rows["จำนวนเงิน(รวมภาษี)"].sum()),
            "order_status": _str_or_none(first.get("สถานะคำสั่งซื้อ")),
            "return_status": "คืนสินค้า" if not return_rows.empty else None,
            "returned_qty": float(return_rows["_item_id"].nunique()),
            "tracking_no": None,
            "carrier_name": None,
            "net_amount": 0,
        })

    income_rows = []
    for order_sn, g in df.groupby("_order_sn"):
        income_rows.append({
            "order_sn": order_sn,
            "platform": "lazada",
            "shop_name": shop_name,
            # ยอดสุทธิรวมทุกรายการธุรกรรม (ยอดค่าสินค้า + ค่าธรรมเนียมต่างๆ ที่เป็นค่าลบ)
            # ของทั้งออเดอร์ — Lazada รายงานยอดสุทธิจริงตรงๆ ในไฟล์เดียว ไม่ต้องเฉลี่ย
            # ตามสัดส่วนราคาแบบ Shopee (allocate_ecommerce_order_income ยังคงเรียกใช้
            # อยู่เพื่อกระจายลง ecommerce_sales.net_amount รายบรรทัด แต่ผลลัพธ์แม่นเท่าเดิม
            # เพราะสัดส่วนราคาต่อบรรทัดของ Lazada ก็เท่ากับสัดส่วนยอดสุทธิจริงอยู่แล้ว)
            "net_amount": float(g["จำนวนเงิน(รวมภาษี)"].sum()),
            "transfer_date": _parse_date(g.iloc[0].get("วันที่ปรับปรุงเข้ายอดของฉัน")),
            "buyer_paid_shipping": 0.0,
            "shopee_subsidized_shipping": 0.0,
            "shipping_fee_charged": 0.0,
        })

    return sales_rows, income_rows
