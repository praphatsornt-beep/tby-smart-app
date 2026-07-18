"""Parser สำหรับไฟล์ "รายงานสินค้าคงเหลือปัจจุบัน/มูลค่า" export จากเมนู "รายงานคลังสินค้า"
ในระบบของบริษัท (.xls แบบ print-layout — หัวรายงาน/รหัสหมวดหมู่/ยอดรวมต่อหมวดปนอยู่ในคอลัมน์เดียวกับ
สินค้า) ใช้ตำแหน่งคอลัมน์ตายตัวเพราะไฟล์นี้ generate จากระบบเดียวกันเสมอ ไม่ใช่ไฟล์ที่
ผู้ใช้พิมพ์เองซึ่งอาจสลับคอลัมน์ได้ — คอลัมน์ 0=รหัสสินค้า, 4=ชื่อสินค้า, 9=หน่วย,
12=ราคาสมาชิก, 14=จำนวนคงเหลือ ยืนยันจากไฟล์จริง (stock18072026.xls) แล้ว: แถวสินค้า
คือแถวที่มีทั้งรหัส (คอลัมน์ 0) และชื่อ (คอลัมน์ 4) พร้อมกัน — แถวหัวข้อหมวดหมู่ (เช่น
"PS", "RB") มีแค่รหัสไม่มีชื่อ, แถวยอดรวมต่อหมวดไม่มีทั้งคู่"""
import pandas as pd


def parse_stock_report(file) -> list[dict]:
    """คืน list of {code, name, unit, member_price, qty} — qty คือ "ส/ค คงเหลือ"
    ตรงกับความหมาย "คอม" (qty_system) ในแท็บ 📦 สต๊อกของแอป"""
    df = pd.read_excel(file, sheet_name=0, header=None)
    cand = df[df[0].notna() & df[4].notna()]
    rows = []
    for _, r in cand.iterrows():
        code = str(r[0]).strip()
        name = str(r[4]).strip()
        if not code or not name:
            continue
        rows.append({
            "code": code,
            "name": name,
            "unit": str(r[9]).strip() if pd.notna(r[9]) else "",
            "member_price": float(r[12]) if pd.notna(r[12]) else 0.0,
            "qty": float(r[14]) if pd.notna(r[14]) else 0.0,
        })
    return rows
