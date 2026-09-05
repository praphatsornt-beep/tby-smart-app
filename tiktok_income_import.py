"""Parser สำหรับไฟล์ 'income_*.xlsx' export จาก TikTok Shop Seller Center (การเงิน >
รายได้) ชีต "รายละเอียดคำสั่งซื้อ" — ยอดขายสุทธิระดับออเดอร์ (1 แถว = 1 ออเดอร์ ไม่ใช่
ต่อ SKU เหมือนไฟล์ affiliate_orders — ดู tiktok_affiliate_import.py) เทียบเท่า
Shopee "Income" / Lazada "Income Overview" แต่ไม่มีราคาต่อ SKU เลยแบ่งยอดลงแต่ละ
สินค้าแบบ Shopee/Lazada ไม่ได้ — คอลัมน์ product_summary เก็บไว้อ้างอิงดิบๆ เท่านั้น

ยืนยันจากไฟล์จริงแล้วว่า 'จำนวนเงินที่ชำระทั้งหมด' (ชื่อคอลัมน์เข้าใจผิดได้ว่าลูกค้าจ่าย
เท่าไหร่ แต่จริงๆ คือยอดสุทธิที่ร้านได้รับ) = 'รายได้รวม' + 'ค่าธรรมเนียมทั้งหมด' (ค่าลบ)
พอดีเป๊ะทุกแถวที่เช็ค"""
import re

import pandas as pd

from ecom_import_common import (
    id_str_or_none as _id_str_or_none, str_or_none as _str_or_none,
    num_or_zero as _num_or_zero, parse_date as _parse_date,
)

_SHEET_NAME = "รายละเอียดคำสั่งซื้อ"

_PRODUCT_SUMMARY_RE = re.compile(r"(\d+)\s*\*\s*(\d+)")


def parse_product_summary(text: str | None) -> tuple[str, int] | None:
    """แกะ (sku_id, qty) จากคอลัมน์ product_summary ดิบๆ ("SKU_ID * qty;") — ใช้ตอน
    ออเดอร์ organic (ไม่มีข้อมูลนายหน้า) ใน db.sync_tiktok_to_ecommerce() คืน None ถ้า
    parse ไม่ได้ (ฟอร์แมตเปลี่ยน/ว่างเปล่า) — ผู้เรียกต้องเช็ค None แล้วรายงานออเดอร์ที่
    parse ไม่ได้ ห้ามทิ้งเงียบ (เคยเป็นบั๊ก: ออเดอร์แบบนี้หายไปทั้งจาก ecommerce_sales
    และ ecommerce_order_income โดยไม่มีสัญญาณเตือนอะไรเลย)"""
    m = _PRODUCT_SUMMARY_RE.search(text or "")
    if not m:
        return None
    return m.group(1), int(m.group(2))


def _get_any(row, *names):
    """ลองหลายชื่อคอลัมน์ตามลำดับ — TikTok เปลี่ยนชื่อคอลัมน์ export บางตัวไปโดยไม่แจ้ง
    (พบ 2026-09-05: 'จำนวนเงินที่ชำระทั้งหมด' → 'ยอดการชำระเงินทั้งหมด', 'รายได้รวม' →
    'รายได้ทั้งหมด' — ยืนยันจากไฟล์จริงว่าเป็นฟิลด์เดียวกัน ค่าตรงกันเป๊ะกับสูตร
    net_settlement = gross_revenue + total_fees เดิม) กันพังเงียบๆ ถ้าเจอชื่อเปลี่ยนอีก
    ในอนาคต ลองชื่อเก่าก่อนแล้วค่อย fallback ชื่อใหม่ (หรือกลับกัน) แทนที่จะ .get() ชื่อเดียว
    แล้วได้ 0 ทุกแถวแบบไม่มีสัญญาณเตือน"""
    for name in names:
        if name in row and pd.notna(row[name]):
            return row[name]
    return None


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
            "net_settlement": _num_or_zero(_get_any(r, "จำนวนเงินที่ชำระทั้งหมด", "ยอดการชำระเงินทั้งหมด")),
            "gross_revenue": _num_or_zero(_get_any(r, "รายได้รวม", "รายได้ทั้งหมด")),
            "product_subtotal_after_disc": _num_or_zero(r.get("ยอดรวมค่าสินค้าหลังหักส่วนลดจากผู้ขาย")),
            "total_fees": _num_or_zero(r.get("ค่าธรรมเนียมทั้งหมด")),
            "tiktok_commission": _num_or_zero(r.get("ค่าคอมมิชชั่น TikTok Shop")),
            "affiliate_commission": _num_or_zero(r.get("ค่าคอมมิชชั่นแอฟฟิลิเอต")),
            "shipping_fee_paid_by_shop": _num_or_zero(r.get("ยอดรวมค่าจัดส่งที่ร้านค้าจ่ายจริง")),
            "product_summary": _str_or_none(r.get("รายละเอียดสินค้าที่ขายได้")),
        })
    return rows
