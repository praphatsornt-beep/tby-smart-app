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
        _prod_name = _str_or_none(r.get("ชื่อสินค้า")) or ""
        _variant = _str_or_none(r.get("ชื่อตัวเลือก"))
        item_name = f"{_prod_name} - {_variant}" if _variant else _prod_name
        rows.append({
            "id": str(uuid.uuid4()),
            "platform": "shopee",
            "shop_name": shop_name,
            "order_sn": order_sn,
            "sale_date": _parse_date(r.get("วันที่ทำการสั่งซื้อ")),
            "product_id": None,
            "item_id_platform": item_id,
            "item_name": item_name,
            "qty": float(r.get("จำนวน") or 0),
            # "ราคาขายสุทธิ" คือยอดต่อบรรทัดสินค้าจริง (ราคาขาย×จำนวน) — ต่างจาก
            # "จำนวนเงินทั้งหมด"/"ค่าจัดส่งโดยประมาณ" ที่เป็นยอดรวมทั้งออเดอร์
            # (ซ้ำกันทุกบรรทัดสินค้าในออเดอร์เดียวกัน) ใช้ตัวหลังจะแบ่งยอดเงินผิด
            # เท่าๆ กันทุกบรรทัดโดยไม่สนราคาจริงของแต่ละสินค้า
            "item_price": float(r.get("ราคาขายสุทธิ") or 0),
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
            # ตรวจสอบค่าส่งเกิน: เทียบ "ค่าส่งที่ Shopee ประเมินไว้ล่วงหน้า" (ผู้ซื้อ
            # จ่าย + Shopee ออกให้) กับ "ค่าส่งที่ขนส่งเรียกเก็บจริง" (คอลัมน์เก็บเป็น
            # ค่าลบ เก็บเป็นบวกไว้เทียบตรงๆ) — ถ้าจริงแพงกว่าที่ประเมิน ส่วนต่างถูก
            # หักจากร้านเงียบๆ โดยไม่ขึ้นกับข้อมูลน้ำหนักสินค้าในระบบเราเลย
            "buyer_paid_shipping": float(r.get("ค่าจัดส่งที่ชำระโดยผู้ซื้อ") or 0),
            "shopee_subsidized_shipping": float(r.get("ค่าจัดส่งสินค้าที่ออกโดย Shopee") or 0),
            "shipping_fee_charged": abs(float(r.get("ค่าจัดส่งที่ Shopee ชำระโดยชื่อของคุณ") or 0)),
        })
    return rows, shop_name
