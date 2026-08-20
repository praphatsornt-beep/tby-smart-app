"""Helper บริสุทธิ์ (pure functions, import แค่ pandas) ใช้ร่วมกันระหว่างตัวแยกไฟล์
export ทั้ง 4 แพลตฟอร์ม (shopee_import.py, lazada_import.py, tiktok_affiliate_import.py,
tiktok_income_import.py) — เดิมก็อปวางเป็นฟังก์ชัน private ซ้ำแยกไฟล์ ย้ายมารวมที่นี่
แบบ byte-for-byte (พฤติกรรมเหมือนเดิมทุกจุด ยืนยันด้วย tests/test_ecom_import_common.py)

หมายเหตุ: shopee_import.py ยังไม่ใช้ id_str_or_none (ยังใช้ str_or_none เฉยๆ กับคอลัมน์ ID)
ทั้งที่เสี่ยงบั๊กเดียวกับที่ Lazada/TikTok เคยเจอมาแล้ว (pandas อ่านคอลัมน์ ID ล้วนเป็น float
ได้ต่อท้าย '.0') — จงใจไม่แก้ในรอบนี้เพราะไม่มีไฟล์ Shopee export จริงมาทดสอบเทียบก่อน push
(ดู CLAUDE.md/แผนเฟส 6: ต้องทดสอบกับไฟล์จริงก่อนเปลี่ยนพฤติกรรมจุดนี้)"""
import pandas as pd


def str_or_none(val) -> str | None:
    if pd.isna(val):
        return None
    s = str(val).strip()
    return s or None


def id_str_or_none(val) -> str | None:
    """เหมือน str_or_none แต่กัน pandas อ่านคอลัมน์ ID ตัวเลขล้วนเป็น float แล้วได้
    ต่อท้าย '.0' (เช่น "หมายเลขคำสั่งซื้อ" เป็นตัวเลขล้วนในไฟล์ แต่ pandas เดา dtype
    เป็น float เพราะมีบางแถวว่าง)"""
    if pd.isna(val):
        return None
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    s = str(val).strip()
    return s or None


def num_or_zero(val) -> float:
    if pd.isna(val):
        return 0.0
    return float(val)


def parse_date(val) -> str | None:
    if pd.isna(val):
        return None
    ts = pd.to_datetime(val, errors="coerce")
    return None if pd.isna(ts) else ts.strftime("%Y-%m-%d")
