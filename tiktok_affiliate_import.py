"""Parser สำหรับไฟล์ 'affiliate_orders_*.xlsx' export จาก TikTok Shop Seller Center
(Affiliate Marketing > Orders) — รายงานเฉพาะออเดอร์ที่มาจากนายหน้า/ครีเอเตอร์เท่านั้น
ไม่ใช่ยอดขายทั้งหมดของร้าน (ดู tiktok_affiliate_setup.sql/ecom_ui.py สำหรับส่วนที่ใช้ข้อมูลนี้)

โครงสร้างไฟล์: 1 แถว = 1 รายการสินค้าต่อออเดอร์ (ต่างจาก Lazada Income Overview ตรงที่ไฟล์นี้
ให้ตัวเลขสำเร็จรูปมาแล้วต่อแถว ไม่ต้อง groupby รวมหลาย transaction-type แถวย่อยเหมือน Lazada)"""
import uuid

import pandas as pd


def _id_str_or_none(val) -> str | None:
    """กัน pandas อ่านคอลัมน์ ID ตัวเลขล้วนเป็น float แล้วได้ต่อท้าย '.0'"""
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


def _parse_datetime(val) -> str | None:
    """รูปแบบในไฟล์คือ 'DD/MM/YYYY HH:MM:SS' (ปี ค.ศ.) — บังคับ dayfirst กันปนกับ
    การเดา MM/DD ของ pandas เวลาเจอวันที่ <=12"""
    if pd.isna(val):
        return None
    ts = pd.to_datetime(val, dayfirst=True, errors="coerce")
    return None if pd.isna(ts) else ts.isoformat()


def parse_affiliate_orders(file, shop_name: str) -> list[dict]:
    """อ่านไฟล์ 'affiliate_orders_*.xlsx' คืน list[dict] ส่งเข้า
    db.upsert_tiktok_affiliate_orders() ตรงๆ ได้เลย — ไม่ใส่คีย์ billed_in_system
    เด็ดขาด (ปล่อยให้ DB DEFAULT/ค่าที่ผู้ใช้ติ๊กไว้เดิมอยู่ ไม่โดน upsert ทับ)"""
    df = pd.read_excel(file, sheet_name=0, header=0)
    df["_order_id"] = df["หมายเลขคำสั่งซื้อ"].apply(_id_str_or_none)
    df["_sku_id"] = df["ID ของ SKU"].apply(_id_str_or_none)
    df = df[df["_order_id"].notna() & df["_sku_id"].notna()]
    if df.empty:
        return []

    rows = []
    for _, r in df.iterrows():
        rows.append({
            "id": str(uuid.uuid4()),
            "shop_name": shop_name,
            "order_id": r["_order_id"],
            "sku_id": r["_sku_id"],
            "product_code": _id_str_or_none(r.get("รหัสสินค้า")),
            "item_name": _str_or_none(r.get("ชื่อสินค้า")),
            "price": _num_or_zero(r.get("ราคา")),
            "payment_amount": _num_or_zero(r.get("Payment Amount")),
            "currency": _str_or_none(r.get("สกุลเงิน")),
            "qty": _num_or_zero(r.get("ปริมาณ")),
            "is_returned": _str_or_none(r.get("คืนสินค้าหรือคืนเงินทั้งหมดแล้ว")),
            "payment_method": _str_or_none(r.get("วิธีการชำระเงิน")),
            "order_status": _str_or_none(r.get("สถานะคำสั่งซื้อ")),
            "creator_username": _str_or_none(r.get("ชื่อผู้ใช้ของครีเอเตอร์")),
            "content_type": _str_or_none(r.get("ประเภทเนื้อหา")),
            "content_id": _id_str_or_none(r.get("รหัสเนื้อหา")),
            "commission_model": _str_or_none(r.get("commission model")),
            "standard_commission_rate": _str_or_none(r.get("อัตราค่าคอมมิชชั่นมาตรฐาน")),
            "commission_base_actual": _num_or_zero(r.get("ฐานค่าคอมมิชชั่นจริง")),
            "commission_payable_actual": _num_or_zero(r.get("ค่าคอมมิชชั่นที่ต้องชำระจริง")),
            # ประมาณการ "ยอดที่เราได้" — payment_amount หักค่าคอมนายหน้าอย่างเดียว ไม่รวม
            # ค่าธรรมเนียม/ค่าคอมโฆษณาอื่นๆ ของ TikTok เอง (ไฟล์นี้ไม่มีข้อมูลนั้น)
            "net_amount": _num_or_zero(r.get("Payment Amount")) - _num_or_zero(r.get("ค่าคอมมิชชั่นที่ต้องชำระจริง")),
            "order_created_at": _parse_datetime(r.get("เวลาที่สร้าง")),
            "payment_time": _parse_datetime(r.get("เวลาชำระเงิน")),
            "delivery_time": _parse_datetime(r.get("Order Delivery Time")),
            "commission_paid_time": _parse_datetime(r.get("เวลาที่ชำระค่าคอมมิชชั่น")),
        })
    return rows
