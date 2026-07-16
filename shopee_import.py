"""Parser สำหรับไฟล์ export จาก Shopee Seller Centre (Order.all + Income) —
แทนที่ Open API/OAuth เดิม (shopee_api.py) ที่ใช้ไม่ได้จริงเพราะร้านทั่วไปไม่มีสิทธิ์
Managed Seller ตามที่ Shopee กำหนด"""
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


def parse_order_export(file, shop_name: str) -> list[dict]:
    """อ่านไฟล์ 'Order.all...xlsx' (Shopee Seller Centre > คำสั่งซื้อ > Export) —
    รายการระดับ SKU ต่อออเดอร์ พร้อมสถานะออเดอร์/คืนสินค้า/เลขพัสดุ+ขนส่ง
    (ไฟล์นี้ไม่บอกชื่อร้าน ต้องรับ shop_name จากผู้เรียกเอง)"""
    df = pd.read_excel(file, sheet_name=0, header=0)
    rows = []
    for _, r in df.iterrows():
        order_sn = _str_or_none(r.get("หมายเลขคำสั่งซื้อ"))
        # สินค้าบางชิ้นไม่ได้ตั้งเลขอ้างอิง SKU ไว้ฝั่ง Shopee — fallback ไป Parent
        # SKU แล้วค่อยชื่อสินค้า กันไม่ให้แถวหายไปเงียบๆ จากรายงาน
        item_id = (_str_or_none(r.get("เลขอ้างอิง SKU (SKU Reference No.)"))
                   or _str_or_none(r.get("เลขอ้างอิง Parent SKU"))
                   or _str_or_none(r.get("ชื่อสินค้า")))
        if not order_sn or not item_id:
            continue
        rows.append({
            "id": str(uuid.uuid4()),
            "platform": "shopee",
            "shop_name": shop_name,
            "order_sn": order_sn,
            "sale_date": _parse_date(r.get("วันที่ทำการสั่งซื้อ")),
            "product_id": None,
            "item_id_platform": item_id,
            "qty": float(r.get("จำนวน") or 0),
            "item_price": float(r.get("จำนวนเงินทั้งหมด") or 0),
            "order_status": _str_or_none(r.get("สถานะการสั่งซื้อ")),
            "return_status": _str_or_none(r.get("สถานะการคืนเงินหรือคืนสินค้า")),
            "returned_qty": float(r.get("จำนวนที่ส่งคืน") or 0),
            "tracking_no": _str_or_none(r.get("*หมายเลขติดตามพัสดุ")),
            "carrier_name": _str_or_none(r.get("ตัวเลือกการจัดส่ง")),
            "net_amount": 0,
        })
    return rows


def parse_income_export(file) -> tuple[list[dict], str]:
    """อ่านไฟล์ 'Income...xlsx' (Shopee Seller Centre > การเงิน > รายได้ของฉัน >
    Export) — ยอดเงินสุทธิที่โอนเข้าจริงต่อออเดอร์ (คนละไฟล์กับ Order.all ไม่มี
    SKU) ชื่อร้านดึงจากหัวไฟล์ได้เอง คืน (rows, shop_name)"""
    head = pd.read_excel(file, sheet_name="Income", header=None, nrows=2)
    shop_name = str(head.iloc[1, 0]).strip()
    file.seek(0)
    df = pd.read_excel(file, sheet_name="Income", header=5)
    rows = []
    for _, r in df.iterrows():
        order_sn = _str_or_none(r.get("หมายเลขคำสั่งซื้อ"))
        if not order_sn:
            continue
        rows.append({
            "order_sn": order_sn,
            "platform": "shopee",
            "shop_name": shop_name,
            "net_amount": float(r.get("จำนวนเงินทั้งหมดที่โอนแล้ว (฿)") or 0),
            "transfer_date": _parse_date(r.get("วันที่โอนชำระเงินสำเร็จ")),
        })
    return rows, shop_name
