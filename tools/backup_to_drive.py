"""
รัน: uv run tools/backup_to_drive.py
หรือ: python tools/backup_to_drive.py

Export ทุกตารางใน Supabase เป็น ZIP (1 ไฟล์ CSV ต่อตาราง) แล้วอัปโหลดขึ้น Google Drive
ของเจ้าของร้านเอง — กันเหตุการณ์แบบข้อมูลตาราง shipments หายถาวรปี 2026-07-21 ซ้ำ
(Supabase Free tier ไม่มี Point-in-Time Recovery ของตัวเอง)

ตั้งใจให้รันอัตโนมัติทุกวันผ่าน .github/workflows/backup.yml (GitHub Actions cron —
รันบนคลาวด์ของ GitHub เอง ไม่ต้องพึ่งเครื่อง PC เปิดอยู่) รันเองตรงนี้ก็ได้เหมือนกัน
ถ้าตั้งค่า .env ครบ (ดู .env.example)

ใช้ OAuth2 refresh token (ไม่ใช้ service account) เพราะ personal Gmail Drive ไม่มี
storage quota ของตัวเองให้ service account เขียนไฟล์ลงไปได้ — ต้องขอ refresh token
ผูกกับ Google account จริงของเจ้าของร้านครั้งเดียวก่อน ผ่าน tools/gdrive_get_refresh_token.py
(ดูขั้นตอนเต็มในไฟล์นั้น) แล้วเก็บ GDRIVE_CLIENT_ID/GDRIVE_CLIENT_SECRET/GDRIVE_REFRESH_TOKEN
+ GDRIVE_FOLDER_ID + SUPABASE_URL/SUPABASE_KEY เป็น GitHub Secrets (repo Settings >
Secrets and variables > Actions)

ไม่ import database.py ตั้งใจ — สคริปต์นี้เรียก Supabase ตรงผ่าน supabase-py เอง เพื่อไม่ต้อง
ลาก streamlit/pyarrow/numpy (dependency ของแอปหลัก) มาลงใน GitHub Actions runner ทุกวัน
ติดตั้งด้วย tools/requirements-backup.txt (เบากว่า requirements.txt หลักมาก)

หมายเหตุ 2026-09-20: GDRIVE_REFRESH_TOKEN จะหมดอายุทุก 7 วันถ้า OAuth app ใน Google Cloud
Console ยังอยู่สถานะ "Testing" (ยังไม่ Publish) — ลอง publish แล้วติดปัญหา "Authorized
domains" เพราะโดเมนแอปจริงคือ tby-smart.streamlit.app ซึ่งเป็น subdomain ของ streamlit.app
(โดเมนของ Streamlit เอง ไม่ใช่ของร้าน) Google ไม่ให้ authorize โดเมนที่ไม่ได้เป็นเจ้าของ
จริง — ถ้ายังหาทางแก้ไม่ได้ ให้ปล่อยเป็น Testing ต่อไป แล้วรับมือด้วยการแจ้งเตือนแทน
(ดู _notify_failure ด้านล่าง — ส่ง LINE หา STAFF_LINE_USER_ID ทันทีที่ backup ล้มเหลว
ไม่ต้องรอเจอเองใน GitHub Actions) ถ้า token หมดอายุอีก ต้องรัน
tools/gdrive_get_refresh_token.py ใหม่แล้วอัปเดต GitHub Secret ด้วยมือทุกครั้ง
"""
import os
import sys
import io
import json
import zipfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

import httpx
import pandas as pd
from supabase import create_client

# ตารางทั้งหมดที่มีจริงในระบบ (อ้างอิงจาก .table("...") ทุกจุดใน database.py) —
# แบ็กอัปทุกตารางเพราะข้อมูลของร้านเล็ก ขนาดรวมไม่ใหญ่ ไม่มีเหตุผลต้องเลือกบางตาราง
_TABLES = [
    "customers", "customer_addresses", "products", "transactions",
    "partial_events", "bill_open_events", "shipments", "box_presets",
    "finance_daily", "commission_records", "company_info",
    "stock_counts", "stock_deposits",
    "ecommerce_shops", "ecommerce_sales", "ecommerce_order_income", "ecommerce_product_map",
    "tiktok_affiliate_orders", "tiktok_order_income",
    "carrier_zones",
]

_DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&supportsAllDrives=true"
_DRIVE_FILES_URL  = "https://www.googleapis.com/drive/v3/files"
_TOKEN_URL        = "https://oauth2.googleapis.com/token"
_LINE_PUSH_URL    = "https://api.line.me/v2/bot/message/push"
_RETAIN_COUNT     = 30  # เก็บ backup ล่าสุด 30 ไฟล์ (~1 เดือนถ้ารันวันละครั้ง) ลบเก่ากว่านั้นทิ้งกัน Drive เต็ม


def _notify_failure(err: Exception) -> None:
    """แจ้ง LINE ทันทีที่ backup ล้มเหลว (เช่น GDRIVE_REFRESH_TOKEN หมดอายุ) — กันเหตุการณ์
    2026-09 ที่พังเงียบๆ ไป 3 วันกว่าจะมีคนสังเกตเห็นใน GitHub Actions เอง"""
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    user_id = os.environ.get("STAFF_LINE_USER_ID", "")
    if not token or not user_id:
        return
    text = (
        "⚠️ Backup Supabase → Google Drive ล้มเหลว\n"
        f"{type(err).__name__}: {err}\n"
        "เช็ค GitHub Actions → Daily Supabase Backup to Google Drive\n"
        "(สาเหตุที่พบบ่อย: GDRIVE_REFRESH_TOKEN หมดอายุ ต้องขอใหม่ผ่าน "
        "tools/gdrive_get_refresh_token.py แล้วอัปเดต GitHub Secret)"
    )
    try:
        httpx.post(_LINE_PUSH_URL, json={"to": user_id, "messages": [{"type": "text", "text": text}]},
                   headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, timeout=10)
    except Exception:
        pass  # การแจ้งเตือนพังไม่ควรบัง exception เดิม ปล่อยให้ GitHub Actions ขึ้นแดงตามปกติ


def _get_access_token() -> str:
    r = httpx.post(_TOKEN_URL, data={
        "client_id":     os.environ["GDRIVE_CLIENT_ID"],
        "client_secret": os.environ["GDRIVE_CLIENT_SECRET"],
        "refresh_token": os.environ["GDRIVE_REFRESH_TOKEN"],
        "grant_type":    "refresh_token",
    }, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


_PAGE_SIZE = 1000  # PostgREST คืนสูงสุด 1000 แถว/request โดยปริยาย — ต้อง .range() วนดึงเอง
                    # ไม่งั้น backup จะเงียบ ๆ ขาดข้อมูลตารางไหนก็ตามที่เกิน 1000 แถว
                    # (เจอจริง: ecommerce_sales/ecommerce_order_income เกินแล้วตอนเขียนสคริปต์นี้)


def _fetch_all(sb, tname: str) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        page = sb.table(tname).select("*").range(start, start + _PAGE_SIZE - 1).execute().data
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        start += _PAGE_SIZE
    return rows


def _build_zip(sb) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for tname in _TABLES:
            try:
                rows = _fetch_all(sb, tname)
            except Exception as e:
                print(f"  ⚠️ ข้ามตาราง {tname}: {e}")
                continue
            zf.writestr(f"{tname}.csv", pd.DataFrame(rows).to_csv(index=False))
            print(f"  {tname}: {len(rows)} แถว")
    buf.seek(0)
    return buf.getvalue()


def _upload(token: str, fname: str, data: bytes, folder_id: str) -> str:
    metadata = {"name": fname, "parents": [folder_id]}
    files = {
        "metadata": (None, json.dumps(metadata), "application/json"),
        "file":     (fname, data, "application/zip"),
    }
    r = httpx.post(_DRIVE_UPLOAD_URL, headers={"Authorization": f"Bearer {token}"}, files=files, timeout=120)
    r.raise_for_status()
    return r.json()["id"]


def _cleanup_old(token: str, folder_id: str) -> None:
    """เก็บ backup ล่าสุด _RETAIN_COUNT ไฟล์ ลบเก่ากว่านั้นทิ้ง"""
    params = {
        "q": f"'{folder_id}' in parents and name contains 'tby_backup_' and trashed = false",
        "orderBy": "createdTime desc",
        "fields": "files(id,name)",
        "pageSize": 100,
    }
    r = httpx.get(_DRIVE_FILES_URL, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=30)
    r.raise_for_status()
    for f in r.json().get("files", [])[_RETAIN_COUNT:]:
        httpx.delete(f"{_DRIVE_FILES_URL}/{f['id']}", headers={"Authorization": f"Bearer {token}"}, timeout=30)
        print(f"  🗑️ ลบ backup เก่า: {f['name']}")


def main():
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    folder_id = os.environ["GDRIVE_FOLDER_ID"]

    print("กำลังดึงข้อมูลจาก Supabase...")
    zip_bytes = _build_zip(sb)
    fname = f"tby_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.zip"

    print(f"กำลังอัปโหลด {fname} ({len(zip_bytes):,} bytes) ไป Google Drive...")
    token = _get_access_token()
    file_id = _upload(token, fname, zip_bytes, folder_id)
    print(f"✅ อัปโหลดสำเร็จ: {fname} (file id: {file_id})")

    _cleanup_old(token, folder_id)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _notify_failure(e)
        raise
