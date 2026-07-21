"""Parser สำหรับไฟล์ 'income_*.xlsx' export จาก TikTok Shop Seller Center (การเงิน >
รายได้) ชีต "รายละเอียดคำสั่งซื้อ" — ยอดขายสุทธิระดับออเดอร์ (1 แถว = 1 ออเดอร์ ไม่ใช่
ต่อ SKU เหมือนไฟล์ affiliate_orders — ดู tiktok_affiliate_import.py) เทียบเท่า
Shopee "Income" / Lazada "Income Overview" แต่ไม่มีราคาต่อ SKU เลยแบ่งยอดลงแต่ละ
สินค้าแบบ Shopee/Lazada ไม่ได้ — คอลัมน์ product_summary เก็บไว้อ้างอิงดิบๆ เท่านั้น

ยืนยันจากไฟล์จริงแล้วว่า 'จำนวนเงินที่ชำระทั้งหมด' (ชื่อคอลัมน์เข้าใจผิดได้ว่าลูกค้าจ่าย
เท่าไหร่ แต่จริงๆ คือยอดสุทธิที่ร้านได้รับ) = 'รายได้รวม' + 'ค่าธรรมเนียมทั้งหมด' (ค่าลบ)
พอดีเป๊ะทุกแถวที่เช็ค"""
import pandas as pd

_SHEET_NAME = "รายละเอียดคำสั่งซื้อ"


def _id_str_or_none(val) -> str | None:
    if pd.isna(val):
        return None
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    s = str(val).strip()
    return s or None


def _str_or_none(val) -> str | None:
    if pd.isna(val):
        return None
    s = str(val).strip()
    return s or None


def _num_or_zero(val) -> float:
    if pd.isna(val):
        return 0.0
    return float(val)


def _parse_date(val) -> str | None:
    """รูปแบบในไฟล์คือ 'YYYY/MM/DD' — วันที่ล้วน ไม่มีเวลา"""
    if pd.isna(val):
        return None
    ts = pd.to_datetime(val, errors="coerce")
    return None if pd.isna(ts) else ts.strftime("%Y-%m-%d")


def parse_income_report(file, shop_name: str) -> list[dict]:
    """อ่านชีต 'รายละเอียดคำสั่งซื้อ' คืน list[dict] ส่งเข้า
    db.upsert_tiktok_order_income() ตรงๆ ได้เลย"""
    df = pd.read_excel(file, sheet_name=_SHEET_NAME, header=0)
    df["_order_id"] = df["หมายเลขคำสั่งซื้อ/การปรับ"].apply(_id_str_or_none)
    df = df[df["_order_id"].notna()]
    if df.empty:
        return []

    rows = []
    for _, r in df.iterrows():
        rows.append({
            "shop_name": shop_name,
            "order_id": r["_order_id"],
            "transaction_type": _str_or_none(r.get("ประเภทธุรกรรม")),
            "order_created_at": _parse_date(r.get("เวลาที่สร้างคำสั่งซื้อ")),
            "order_paid_at": _parse_date(r.get("เวลาที่ชำระคำสั่งซื้อ")),
            "currency": _str_or_none(r.get("สกุลเงิน")),
            "net_settlement": _num_or_zero(r.get("จำนวนเงินที่ชำระทั้งหมด")),
            "gross_revenue": _num_or_zero(r.get("รายได้รวม")),
            "product_subtotal_after_disc": _num_or_zero(r.get("ยอดรวมค่าสินค้าหลังหักส่วนลดจากผู้ขาย")),
            "total_fees": _num_or_zero(r.get("ค่าธรรมเนียมทั้งหมด")),
            "tiktok_commission": _num_or_zero(r.get("ค่าคอมมิชชั่น TikTok Shop")),
            "affiliate_commission": _num_or_zero(r.get("ค่าคอมมิชชั่นแอฟฟิลิเอต")),
            "shipping_fee_paid_by_shop": _num_or_zero(r.get("ยอดรวมค่าจัดส่งที่ร้านค้าจ่ายจริง")),
            "product_summary": _str_or_none(r.get("รายละเอียดสินค้าที่ขายได้")),
        })
    return rows
