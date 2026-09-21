"""
รัน: uv run tools/email_daily_digest.py
หรือ: python tools/email_daily_digest.py

เช็คอีเมล 4 บัญชี (IMAP) แล้วสรุปส่งเข้า LINE ส่วนตัวเจ้าของร้านวันละครั้ง (พร้อมสถานะ COD/
พัสดุค้างส่งจากระบบร้านเองด้วย — ดู `_build_cod_unbilled_rows`/`_build_slow_shipment_rows`):
  1. พัสดุ Shopee/Lazada/TikTok ที่มีปัญหา/ตีกลับ/ถูกตีคืน (เชื่อม API ทั้ง 3 แพลตฟอร์ม
     ไม่ได้ — Shopee ถูกปฏิเสธที่ Seller Identification เพราะไม่ใช่ Managed/Mall Seller,
     Lazada/TikTok ก็ไม่มี integration เหมือนกัน — อีเมลคือทางเดียวที่มีตอนนี้)
  2. อีเมลแจ้งออเดอร์ใหม่/ยกเลิกของ Shopee — สรุปจำนวนออเดอร์+สินค้า/จำนวนต่อร้านแบบ
     เรียลไทม์ (ดู `ecom_calc.parse_shopee_order_notice_email`) บันทึกลง Supabase ตาราง
     `ecommerce_order_notices` ให้แอปโชว์ต่อที่ 🛒 E-commerce → ตรวจสอบปัญหา เหมือนกัน
     (Lazada/TikTok ยังไม่เช็คว่ามีอีเมลแบบนี้หรือไม่ — ทำ Shopee ก่อน)

(เดิมมีเช็คอีเมลแจ้งยอดบัตรเครดิต/statement จากธนาคารด้วย — เอาออกแล้ว 2026-09-21 ตามคำขอ
user "เอาเรื่องแจ้งยอดบัตรเครดิตออกก่อน" — โค้ดเดิมยังอยู่ใน git history ถ้าจะเอากลับมาทีหลัง)

ก่อนสร้างสรุป ยัง sync สถานะจัดส่ง (delivery_status) ของ shipments ที่ยังไม่จบจาก iShip ให้
อัตโนมัติด้วย (`_sync_iship_delivery_statuses`, เพิ่ม 2026-09-21 ตามคำขอ user "มันดึงทุกเช้า
ได้เองมั้ย") — เหมือนกดปุ่ม "🚚 สถานะส่ง" ใน shipment_history_ui.py ทุกประการ แค่รันอัตโนมัติ
ทุกเช้าแทน ต้องมี ISHIP_PHONE/ISHIP_PASSWORD ใน .env/secrets ด้วย (คนละตัวกับ ISHIP_TOKEN ที่
ใช้สร้างออเดอร์ — นี่คือ login เว็บ iShip ตรงๆ) ไม่ critical ถ้า sync ล้มเหลว (เช่น iShip
เปลี่ยนรหัสผ่าน) — แค่ print แจ้งเตือนแล้วรัน digest ส่วนที่เหลือต่อตามปกติ

**Shopee ยืนยันจากอีเมลจริงแล้ว** (2026-09-19, ดู `ecom_calc.parse_shopee_return_emails`)
— แกะเลขคำสั่งซื้อ/บริษัทขนส่ง/เลขติดตามพัสดุได้ครบ บันทึกลง Supabase ตาราง
`ecommerce_return_emails` ให้แอปโชว์ต่อที่ 🛒 E-commerce → ตรวจสอบปัญหา ทุกครั้งที่เจอ
**Lazada/TikTok ยังเป็นการเดา** (`_PLATFORM_SENDER_HINTS`/`_RETURN_KEYWORDS` แบบหยาบ,
ยังไม่แกะข้อมูลโครงสร้างเป็น row ในตารางเหมือน Shopee) เพราะยังไม่เคยเห็นอีเมลตีคืนจริง
จาก 2 แพลตฟอร์มนี้เลย (Lazada มีแต่เคสร้องเรียนแมนนวลเก่าปี 2023, TikTok ไม่มีเลย —
เช็คแล้วในกล่องเมลจริง) — ถ้ามีตัวอย่างจริงเมื่อไหร่ค่อยมาทำแบบเดียวกับ Shopee

รองรับเฉพาะบัญชีที่ใช้ IMAP + password ตรงๆ ได้ (เช่น Gmail ผ่าน App Password) —
Outlook/Hotmail/Microsoft 365 ปิด basic auth ไปแล้ว ต้องทำ OAuth2 แยกต่างหาก (ยังไม่ทำ)

ต้องตั้งค่าใน .env ก่อนรัน — ดู .env.example — รันอัตโนมัติทุกวันผ่าน GitHub Actions
(.github/workflows/email_digest.yml, ใช้ GitHub Secrets แทน .env) ไม่ต้องพึ่งเครื่อง
PC ที่ร้านเปิดอยู่ตลอดแบบ Windows Task Scheduler — ใช้ tools/requirements-backup.txt
ตัวเดียวกับ backup_to_drive.py (ไม่ import database.py/line_api.py ที่ลาก streamlit/
pyarrow มาด้วย — คุยกับ Supabase/LINE ตรงๆ ผ่าน supabase-py/httpx แทน ตามคอมเมนต์ใน
requirements-backup.txt ที่บอกว่าไม่อยากลากของหนักมาติดตั้งทุกรอบ cron รายวัน)
"""
import os
import re
import sys
import json
import imaplib
import email
import html as html_mod
from email.header import decode_header
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

import httpx
import requests
from supabase import create_client

import ecom_calc

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
ISHIP_WEB_BASE = "https://app.iship.cloud"


def _get_supabase():
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        print("❌ ไม่พบ SUPABASE_URL/SUPABASE_KEY ใน .env — ดู .env.example")
        sys.exit(1)
    return create_client(url, key)


def _fetch_all_sb(build_query, page_size: int = 1000) -> list[dict]:
    """เหมือน database._fetch_all() แต่ทำเองตรงนี้แทน (ไม่ import database.py — ลาก
    streamlit มาด้วย ดู docstring บนสุดของไฟล์) กัน PostgREST 1,000-แถว/request cap เงียบๆ
    (ดูกติกาใน CLAUDE.md) เผื่อ transactions/shipments โตเกิน 1,000 แถวในอนาคต — build_query
    ต้องเป็นฟังก์ชันไม่รับ argument คืน query builder ใหม่ทุกครั้ง (builder เดิมเรียกซ้ำ
    หลัง .execute() ไม่ได้)"""
    rows: list[dict] = []
    offset = 0
    while True:
        page = build_query().range(offset, offset + page_size - 1).execute().data
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


_TERMINAL_SHIP_STATUSES = {"จัดส่งแล้ว", "ตีกลับ", "ยกเลิก"}


def _shipment_customer_name(sh: dict) -> str:
    return (sh.get("customers") or {}).get("name") or sh.get("recipient_name") or "—"


def _shipment_items_str(sh: dict) -> str:
    items = sh.get("items") or []
    return ", ".join(
        f"{it.get('name') or it.get('product_id', '')} x{it.get('qty', 1)}" for it in items
    ) or "—"


def _build_cod_unbilled_rows(txn_rows: list[dict], ship_rows: list[dict]) -> list[dict]:
    """จับคู่ shipments ที่เป็น COD และโอนเงินมาแล้ว (cod_transferred_at ไม่ null) กับลูกค้า
    ที่ยังมีแถว transactions สถานะ COD+"ยังไม่เปิดบิล" ค้างอยู่ — แมตช์ด้วยชื่อลูกค้าเหมือนกับ
    ที่ dashboard_ui.py ทำในการ์ด "✅ รับแล้ว — ยังไม่เปิดบิล" (shipments ไม่มี FK ตรงไปยัง
    transactions/bill รายตัวให้จับคู่แม่นกว่านี้ได้) รับ txn_rows/ship_rows เป็นผลลัพธ์ดิบจาก
    .execute().data ของ Supabase ตรงๆ (ship_rows เป็น shipments ทุกแถวไม่กรอง — ฟังก์ชันนี้
    กรอง cod_amount>0 + cod_transferred_at เองข้างใน เพื่อใช้ shipments ชุดเดียวกันกับ
    _build_slow_shipment_rows ได้โดยไม่ต้อง query ซ้ำ) แยกออกมาเป็นฟังก์ชัน pure ให้ทดสอบได้
    โดยไม่ต้องปลอม Supabase client (เพิ่ม 2026-09-21 ตามคำขอ user)"""
    unbilled_names = {
        (t.get("customers") or {}).get("name")
        for t in txn_rows
        if (t.get("customers") or {}).get("name")
    }
    if not unbilled_names:
        return []
    rows = []
    for sh in ship_rows:
        if float(sh.get("cod_amount") or 0) <= 0 or not sh.get("cod_transferred_at"):
            continue
        cname = _shipment_customer_name(sh)
        if cname not in unbilled_names:
            continue
        rows.append({
            "customer": cname,
            "items": _shipment_items_str(sh),
            "cod_amount": float(sh.get("cod_amount") or 0),
            "tracking_no": sh.get("tracking_no") or "—",
        })
    rows.sort(key=lambda r: -r["cod_amount"])
    return rows


def _build_slow_shipment_rows(ship_rows: list[dict], now_utc: datetime, cutoff_days: int = 3) -> list[dict]:
    """พัสดุที่ไม่ใช่ COD (ติดตามแยกในการ์ด COD อยู่แล้ว) ค้างเกิน `cutoff_days` วันโดยยังไม่ถึง
    สถานะจบ (จัดส่งแล้ว/ตีกลับ/ยกเลิก) — เงื่อนไขเดียวกับ dashboard_ui.py's `_slow_ships` ทุก
    ประการ (คัดลอกมาตรงนี้แทนการ import database.py/streamlit — ดู docstring บนสุดของไฟล์)
    เพิ่ม 2026-09-21 ตามคำขอ user ("พัสดุค้างส่งเกิน 3 วัน... ให้แสดงชื่อผู้ส่ง วันที่ และสินค้า")"""
    cutoff = now_utc - timedelta(days=cutoff_days)
    bkk = timezone(timedelta(hours=7))
    rows = []
    for sh in ship_rows:
        if float(sh.get("cod_amount") or 0) != 0:
            continue
        if not sh.get("tracking_no"):
            continue
        if sh.get("delivery_status") in _TERMINAL_SHIP_STATUSES:
            continue
        try:
            sdt = datetime.fromisoformat((sh.get("created_at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if sdt >= cutoff:
            continue
        rows.append({
            "customer": _shipment_customer_name(sh),
            "items": _shipment_items_str(sh),
            "date": sdt.astimezone(bkk).strftime("%d/%m/%y"),
            "days": (now_utc - sdt).days,
            "tracking_no": sh.get("tracking_no") or "—",
            "carrier": sh.get("carrier") or "",
            "status": sh.get("delivery_status") or "ไม่มีข้อมูล",
        })
    rows.sort(key=lambda r: -r["days"])
    return rows


_MAX_DIGEST_ROWS = 10  # กัน LINE push text เกิน 5,000 ตัวอักษร (ขีดจำกัดจริงของ LINE Messaging
# API) — พบจริง 2026-09-21 ตอนทดสอบ dry-run: "พัสดุค้างส่งเกิน 3 วัน" มีค้างสะสมถึง 107 รายการ
# (พัสดุเก่าที่ไม่เคย sync สถานะ ไม่ใช่พัสดุที่เพิ่งค้างจริงๆ) รวมเป็นข้อความยาว 16,028
# ตัวอักษร ถ้าส่งจริงจะโดน LINE ปฏิเสธทั้งฉบับทันที (รวมส่วนอื่นที่ปกติดีไปด้วย) — ผู้ใช้
# ยืนยันให้จำกัดไว้ 10 รายการต่อส่วน (ที่สำคัญที่สุดก่อน — เรียงมาแล้วจาก caller: ค้างนานสุด/
# ยอด COD สูงสุด) ที่เหลือสรุปเป็นตัวเลขรวมแทนแทนการแจกแจงทุกแถว


def _capped_rows(rows: list[dict], max_items: int = _MAX_DIGEST_ROWS) -> tuple[list[dict], int]:
    """คืน (แถวที่จะแสดงใน LINE, จำนวนที่เหลือที่ไม่ได้แสดง) — rows ต้องเรียงลำดับความสำคัญ
    มาก่อนหน้าแล้วจาก caller (เอาอันสำคัญสุดขึ้นก่อนเสมอ ไม่ใช่สุ่ม/เรียงตาม id)"""
    shown = rows[:max_items]
    return shown, max(0, len(rows) - len(shown))


# ── sync สถานะจัดส่งจาก iShip อัตโนมัติทุกเช้า ──────────────────────────────────────
# เพิ่ม 2026-09-21 ตามคำขอ user ("มันดึงทุกเช้าได้เองมั้ย") หลังเจอว่า "พัสดุค้างส่งเกิน 3 วัน"
# มีของเก่าที่ไม่เคย sync สถานะปนอยู่เพียบ (107 รายการ, เก่าสุด 46 วัน) — เดิมต้องกดปุ่ม
# "🚚 สถานะส่ง" เองใน shipment_history_ui.py เท่านั้น พอร์ตมาที่นี่ให้รันอัตโนมัติก่อนสร้าง
# digest ทุกเช้าแทน เพื่อให้ทั้งแอปและ LINE เห็นข้อมูลสดตรงกัน
#
# ทำไมพอร์ตได้ง่าย: iship_api.py ที่มีอยู่แล้ว import streamlit แต่จริงๆ ใช้แค่ 2 จุดผิวเผิน —
# (1) อ่าน st.secrets เป็น fallback ของ env var (ไม่จำเป็นเลยที่นี่ เพราะรันผ่าน GitHub Actions
# ตั้ง env var ตรงอยู่แล้ว) และ (2) แคช session ไว้ใน st.session_state กันต้อง login ซ้ำระหว่าง
# user คลิกไปมาในแอป (ไม่จำเป็นเลยเหมือนกัน เพราะ script นี้รันครั้งเดียวจบ ไม่มี rerun ให้แคช
# ข้าม) ตัว login/scrape จริง (_web_session()/get_shipment_statuses()) เป็น requests ล้วนๆ —
# คัดลอกมาตรงนี้แทนการ import iship_api.py (เหตุผลเดียวกับที่ไม่ import database.py/line_api.py
# ทั้งไฟล์ ดู docstring บนสุดของไฟล์)


def _iship_login() -> tuple[requests.Session | None, str]:
    """เหมือน iship_api._web_session() ทุกประการ แต่อ่าน ISHIP_PHONE/ISHIP_PASSWORD จาก env
    ตรงๆ (ไม่ผ่าน st.secrets) และไม่แคช session (รันครั้งเดียวจบ ไม่มี rerun ให้แคชข้าม)"""
    phone = os.environ.get("ISHIP_PHONE", "")
    password = os.environ.get("ISHIP_PASSWORD", "")
    if not phone or not password:
        return None, "ไม่มี ISHIP_PHONE/ISHIP_PASSWORD ใน .env"
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "th,en-US;q=0.9,en;q=0.8",
    })
    try:
        r = s.get(f"{ISHIP_WEB_BASE}/login", timeout=10)
        m = re.search(r'<input[^>]+name="_token"[^>]+value="([^"]+)"', r.text)
        if not m:
            return None, f"หาไม่เจอ _token ใน login page (status={r.status_code})"
        r2 = s.post(f"{ISHIP_WEB_BASE}/login", data={
            "_token": m.group(1), "phone": phone, "password": password, "remember": "1",
        }, headers={
            "Referer": f"{ISHIP_WEB_BASE}/login", "Origin": ISHIP_WEB_BASE,
            "Content-Type": "application/x-www-form-urlencoded",
        }, timeout=10, allow_redirects=True)
        if "login" in r2.url:
            _err = re.search(r'text-danger[^>]*>([^<]+)<', r2.text)
            _msg = _err.group(1).strip() if _err else r2.text[:200]
            return None, f"Login ไม่สำเร็จ: {_msg}"
        return s, f"Login OK -> {r2.url}"
    except Exception as e:
        return None, f"Exception: {e}"


def _parse_iship_status_rows(rows: list[dict]) -> dict[str, str]:
    """แกะ {tracking_no: status_text} จากแถวดิบของ iShip's getdt-new-shipment API — เหมือน
    iship_api.get_shipment_statuses() ทุกประการ (แยกเป็นฟังก์ชัน pure ต่างหากให้ทดสอบได้
    โดยไม่ต้องปลอม HTTP session)"""
    statuses: dict[str, str] = {}
    for row in rows:
        track_html = row.get("track_no", "") or ""
        status_html = row.get("status_btn", "") or ""
        m_tn = re.search(r'track=([A-Z0-9]+)', track_html)
        if not m_tn:
            m_tn = re.search(r'>([A-Z0-9]{8,})<', track_html)
        tn = m_tn.group(1).strip() if m_tn else track_html.strip()
        m_st = re.search(r'>([^<>]+)</', status_html)
        status_text = m_st.group(1).strip() if m_st else status_html.strip()
        if tn and status_text:
            statuses[tn] = status_text
    return statuses


def _iship_get_shipment_statuses(days_back: int = 90) -> dict:
    """เหมือน iship_api.get_shipment_statuses() ทุกประการ แต่ใช้ _iship_login() (ไม่แคช
    session) แทน คืน {"statuses": {track_no: status_text}, "error": str|None}"""
    sess, login_msg = _iship_login()
    if not sess:
        return {"statuses": {}, "error": login_msg}

    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days_back)

    sess.get(f"{ISHIP_WEB_BASE}/shipment", timeout=10)
    xsrf = unquote(sess.cookies.get("XSRF-TOKEN", ""))
    hdrs = {
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": f"{ISHIP_WEB_BASE}/shipment",
        "X-XSRF-TOKEN": xsrf,
    }
    _cols = [
        ("checkbox", "", False, False),
        ("order_date", "orders.created_at", True, True),
        ("track_no", "shippings.track_no", True, True),
        ("custom_order_id", "shippings.custom_order_id", True, True),
        ("status_btn", "status_btn", False, False),
        ("name", "", True, True),
        ("dst_name", "", True, True),
        ("dst_phone", "", True, True),
        ("dst_address", "", True, True),
        ("print_btn", "print_count", False, False),
        ("cod_amount", "", True, True),
        ("remark", "", True, True),
        ("cancel_btn", "", True, True),
        ("detail_btn", "", True, True),
    ]
    params = {
        "draw": 1, "start": 0, "length": 200,
        "order[0][column]": 1, "order[0][dir]": "desc",
        "search[value]": "", "search[regex]": "false",
        "status_id": "", "start_date": str(start_date), "end_date": str(end_date),
        "order_print": 3, "courier_filter": "all",
    }
    for i, (data, name, searchable, orderable) in enumerate(_cols):
        params[f"columns[{i}][data]"] = data
        params[f"columns[{i}][name]"] = name
        params[f"columns[{i}][searchable]"] = "true" if searchable else "false"
        params[f"columns[{i}][orderable]"] = "true" if orderable else "false"
        params[f"columns[{i}][search][value]"] = ""
        params[f"columns[{i}][search][regex]"] = "false"

    try:
        r = sess.get(f"{ISHIP_WEB_BASE}/getdt-new-shipment", headers=hdrs, params=params, timeout=15)
        if r.status_code != 200 or not r.text.strip():
            return {"statuses": {}, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        try:
            rows = r.json().get("data", [])
        except Exception:
            return {"statuses": {}, "error": f"JSON parse failed: {r.text[:300]}"}
        return {"statuses": _parse_iship_status_rows(rows), "error": None}
    except Exception as e:
        return {"statuses": {}, "error": str(e)}


def _sync_iship_delivery_statuses(sb) -> None:
    """sync delivery_status ของ shipments ที่ยังไม่จบ (ไม่ terminal) จาก iShip เข้า Supabase —
    เหมือนปุ่ม "🚚 สถานะส่ง" ใน shipment_history_ui.py ทุกประการ (db.get_pending_delivery_tracking
    + iship_api.get_shipment_statuses + db.update_delivery_statuses) แค่รันอัตโนมัติแทนต้องกดเอง
    ไม่ critical ถ้าล้มเหลว (เช่น iShip login ไม่ผ่าน/รหัสผ่านเปลี่ยน) — แค่ print แจ้งเตือนแล้ว
    ปล่อยให้ digest ส่วนที่เหลือทำงานต่อตามปกติ ไม่ทำให้ทั้งฉบับล้มไปด้วย"""
    try:
        _ship_rows = _fetch_all_sb(
            lambda: sb.table("shipments").select("tracking_no,delivery_status")
            .not_.is_("tracking_no", "null").neq("tracking_no", "")
        )
        _pending_tn = {r["tracking_no"] for r in _ship_rows
                       if r.get("delivery_status") not in _TERMINAL_SHIP_STATUSES}
        if not _pending_tn:
            print("🚚 ไม่มี tracking ที่รอสถานะ — ข้าม sync iShip")
            return
        _sr = _iship_get_shipment_statuses(days_back=90)
        if _sr.get("error"):
            print(f"⚠️ ดึงสถานะจัดส่งจาก iShip ไม่สำเร็จ: {_sr['error']}")
            return
        _to_update = {tn: st for tn, st in _sr["statuses"].items() if tn in _pending_tn}
        if not _to_update:
            print("🚚 ไม่มีสถานะใหม่จาก iShip")
            return
        by_status: dict[str, list[str]] = {}
        for tn, st in _to_update.items():
            by_status.setdefault(st, []).append(tn)
        n_updated = 0
        for st_text, tns in by_status.items():
            for i in range(0, len(tns), 50):
                chunk = tns[i:i + 50]
                sb.table("shipments").update({"delivery_status": st_text}).in_("tracking_no", chunk).execute()
                n_updated += len(chunk)
        print(f"🚚 sync สถานะจัดส่งจาก iShip แล้ว {n_updated} tracking")
    except Exception as e:
        print(f"⚠️ sync สถานะจัดส่งจาก iShip ล้มเหลว: {e}")


def _resolve_notice_item(name: str, variant: str, qty: int, notice_map: dict[str, dict]) -> tuple[str, int]:
    """คืน (label, จำนวนจริง) สำหรับ 1 รายการสินค้าในอีเมลแจ้งออเดอร์ Shopee — ย่อชื่อยาวจาก
    หน้าประกาศขาย (เช่น "กาแฟโสมซูเลียน ขนาด 40 ซอง คอฟฟี่พลัส...") เป็นรหัสสินค้าภายในสั้นๆ
    ถ้าเคย map ไว้แล้ว (คีย์เดียวกับ database.notice_item_map_key()/ecom_ui.py's mapping UI,
    namespace "shopee_notice" ใน ecommerce_product_map — คัดลอกสูตรคีย์มาตรงนี้แทนการ import
    database.py ดู docstring บนสุดของไฟล์) พร้อม**คูณด้วย units_per_pack** ด้วยเสมอ (เช่น
    "ยาสีฟันแพค 3 หลอด" map ไว้เป็นรหัสเดี่ยว + units_per_pack=3 → 1 ออเดอร์ต้องนับเป็น 3
    หลอดจริง ไม่ใช่ 1) เหมือนกับที่ database.get_ecommerce_order_notices_df() คำนวณ "จำนวนรวม"
    ให้ตารางในแอป — เดิม (2026-09-21 รอบแรก) ลืมคูณจุดนี้ ทำให้ตัวเลขใน LINE digest น้อยกว่า
    ความจริงสำหรับสินค้าที่เป็นแพครวม ผู้ใช้ทักท้วง 2026-09-21 หลัง map "ยาสีฟัน 3 หลอด" แล้ว
    สังเกตว่ารหัสที่โชว์เป็นแค่ "TU2315" ไม่มีตัวคูณกำกับ — แก้ไขให้คูณจำนวนจริงแทนการเติมต่อ
    ท้ายรหัส (เช่น "TU2315-3") เพราะรหัสสินค้าในระบบต้องเป็น LETTERS+4DIGITS ล้วนเท่านั้น ไม่มี
    "-" — ดู calc_logic.py's parse_calc_order() comment) ยังไม่เคย map มาก่อนคงชื่อเต็มไว้เสมอ
    (เดิม 2026-09-21 ตัดให้สั้นเหลือ 27 ตัวอักษร+"..." กันข้อความ LINE ยาว แต่ user ทักท้วง
    วันเดียวกันว่าอ่านไม่ออกว่าเป็นสินค้าอะไร — ยอมให้ข้อความยาวขึ้นแทนเพื่อให้อ่านรู้เรื่อง
    ดีกว่า ตัวป้องกันข้อความ LINE เกิน 5,000 ตัวอักษรคือ _capped_rows() ที่จำกัดจำนวน*แถว*
    อยู่แล้ว ไม่ได้พึ่งการตัดสั้นชื่อสินค้าจุดนี้)"""
    key = f"{name} :: {variant}" if variant else name
    mapped = notice_map.get(key)
    if mapped:
        pack = int(round(float(mapped.get("units_per_pack") or 1)))
        return mapped["product_id"], int(qty) * pack
    return name, int(qty)


def _push_line_text(user_id: str, text: str) -> dict:
    """ทำเหมือน line_api.push_text() แบบย่อ — ไม่ import line_api.py ตรงๆ เพราะไฟล์นั้น
    `import streamlit as st` ไว้ใช้ st.secrets fallback (ไม่จำเป็นตรงนี้ เพราะรันผ่าน
    GitHub Actions ตั้ง env var ตรงอยู่แล้ว) จะลาก streamlit มาติดตั้งเปล่าๆ"""
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return {"ok": False, "error": "ไม่มี LINE_CHANNEL_ACCESS_TOKEN"}
    try:
        r = httpx.post(
            LINE_PUSH_URL,
            json={"to": user_id, "messages": [{"type": "text", "text": text}]},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=10,
        )
        return {"ok": r.status_code == 200, "error": None if r.status_code == 200 else r.text}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _upsert_ecommerce_order_notice(sb, order: dict, notice_subject: str, platform: str = "shopee") -> None:
    """upsert คีย์ (platform, order_sn) ลง ecommerce_order_notices — ถ้าเจอออเดอร์เดิมมาอีก
    (เช่นอีเมลยกเลิกที่มาทีหลังอีเมลยืนยัน) อัปเดตทับด้วยข้อมูลล่าสุด (status จะเปลี่ยนเป็น
    'ยกเลิก' ตอนนั้น)"""
    now = datetime.now(timezone.utc).isoformat()
    existing = sb.table("ecommerce_order_notices").select("id") \
        .eq("platform", platform).eq("order_sn", order["order_sn"]).execute().data
    row = {
        "platform": platform, "shop_name": order.get("shop_name"), "order_sn": order["order_sn"],
        "order_type": order.get("order_type"), "status": order.get("status") or "ยืนยันแล้ว",
        "buyer_name": order.get("buyer_name"), "order_date": order.get("order_date"),
        "total_amount": order.get("total_amount"), "shipping_fee": order.get("shipping_fee"),
        "items": order.get("items") or [], "notice_subject": notice_subject, "last_seen_at": now,
    }
    if existing:
        sb.table("ecommerce_order_notices").update(row).eq("id", existing[0]["id"]).execute()
    else:
        row["first_seen_at"] = now
        sb.table("ecommerce_order_notices").insert(row).execute()


def _upsert_ecommerce_return_email(
    sb, order_sn: str, carrier_name: str, tracking_no: str, notice_subject: str,
    shop_name: str | None = None, platform: str = "shopee",
) -> None:
    """เหมือน database.upsert_ecommerce_return_email() แต่คุย Supabase ตรงๆ ผ่าน sb ที่รับมา
    (ไม่ import database.py — ดู docstring บนสุดของไฟล์) upsert คีย์ (platform, order_sn)
    เอง, notice_count +1 ทุกครั้งที่เจอซ้ำ, คง first_seen_at เดิมไว้

    shop_name มาจาก label ของบัญชีอีเมลที่เจออีเมลนี้ (account["label"] ใน EMAIL_ACCOUNTS)
    ไม่ได้ parse จากเนื้อหาอีเมล — ยืนยันกับผู้ใช้ 2026-09-20 ว่าอีเมลตีกลับของ Shopee
    เองไม่มีชื่อร้าน/สินค้าอยู่ในเนื้อหาเลย (มีแค่ชื่อเล่นเจ้าของร้าน ไม่ตรงกับ shop_name ที่ใช้
    ในตารางอื่น) แต่ 4 บัญชีอีเมลที่ตั้งค่าไว้ผูก 1 ต่อ 1 กับร้านจริง จึงใช้ label แทนได้เลย
    ทันทีโดยไม่ต้องรอไฟล์ยอดขายมาจับคู่ — เขียนทับ shop_name เดิมทุกครั้งที่เจอซ้ำด้วย (เผื่อ
    label ถูกแก้ทีหลังให้ตรงมากขึ้น)"""
    existing = sb.table("ecommerce_return_emails").select("id,notice_count") \
        .eq("platform", platform).eq("order_sn", order_sn).execute().data
    now = datetime.now(timezone.utc).isoformat()
    if existing:
        row = existing[0]
        sb.table("ecommerce_return_emails").update({
            "carrier_name": carrier_name, "tracking_no": tracking_no, "notice_subject": notice_subject,
            "shop_name": shop_name, "notice_count": (row.get("notice_count") or 1) + 1, "last_seen_at": now,
        }).eq("id", row["id"]).execute()
    else:
        sb.table("ecommerce_return_emails").insert({
            "platform": platform, "order_sn": order_sn, "carrier_name": carrier_name,
            "tracking_no": tracking_no, "notice_subject": notice_subject, "shop_name": shop_name,
            "notice_count": 1, "first_seen_at": now, "last_seen_at": now,
        }).execute()


# ── ตรวจจับอีเมลที่เกี่ยวข้อง (หยาบ — รอ refine จากตัวอย่างจริง, ดู docstring ด้านบน) ──

# sender เดาจากชื่อแพลตฟอร์มตรงๆ (เช่น "Shopee <noreply@shopee.co.th>") — ยังไม่เคยเห็น
# อีเมลจริงจาก Lazada/TikTok เลย ถ้า sender จริงไม่ตรงกับนี้ (เช่นใช้โดเมนอื่น) ต้องมา
# เพิ่ม hint ทีหลังจากตัวอย่างจริง
_PLATFORM_SENDER_HINTS = {
    "Shopee": ["shopee"],
    "Lazada": ["lazada"],
    "TikTok": ["tiktok"],
}
_RETURN_KEYWORDS = [
    # ยืนยันจากหัวเรื่องอีเมล Shopee จริง 2026-09-19: "[แจ้งเตือน] พัสดุกำลังทำการ
    # จัดส่งไปยังผู้ขาย กรุณารอการติดต่อจากบริษัทขนส่ง" (พัสดุกำลังตีกลับ) และ
    # "[แจ้งเตือน] พัสดุของคุณไม่สามารถจัดส่งคืนร้านค้าได้สำเร็จ ..." (ตีกลับไม่สำเร็จ)
    "จัดส่งไปยังผู้ขาย", "จัดส่งคืนร้านค้า",
    "ตีกลับ", "ตีคืน", "ส่งไม่สำเร็จ", "จัดส่งไม่สำเร็จ", "คืนสินค้า", "คืนพัสดุ",
    "return", "returned", "failed delivery", "delivery failed", "refund",
]


def _detect_platform_return_problem(subject: str, sender: str, body: str) -> str | None:
    """คืนชื่อแพลตฟอร์ม (Shopee/Lazada/TikTok) ถ้าอีเมลนี้ดูเหมือนแจ้งพัสดุมีปัญหา/
    ตีกลับ/ถูกตีคืน ไม่งั้นคืน None — เดาจาก sender + keyword คร่าวๆ (ดู docstring บนสุด
    ของไฟล์ ยังไม่มีตัวอย่างอีเมลจริงมายืนยันฟอร์แมตของทั้ง 3 แพลตฟอร์ม)"""
    sender_lower = sender.lower()
    platform = next(
        (p for p, hints in _PLATFORM_SENDER_HINTS.items() if any(h in sender_lower for h in hints)),
        None,
    )
    if not platform:
        return None
    text = f"{subject} {body}".lower()
    return platform if any(k in text for k in _RETURN_KEYWORDS) else None


# ── IMAP fetch ────────────────────────────────────────────────────────────────

# บางอีเมล (เจอจริงจากบัญชี ts_shop56) ประกาศ charset เป็นชื่อที่ Python ไม่รู้จักตรงๆ
# เช่น "windows-874" (ชื่อที่ Windows/เมลไคลเอนต์บางตัวใช้เรียก codec ไทย — Python เรียก
# "cp874") ถ้าไม่ normalize ก่อน .decode() จะได้ LookupError ทำให้อีเมลทั้งฉบับ (และเดิม
# ทั้งบัญชี เพราะ error หลุดออกไปทำให้ fetch_account() ล้มทั้งลูป) หายไปเงียบๆ
_CHARSET_ALIASES = {"windows-874": "cp874"}


def _normalize_charset(enc: str | None) -> str:
    enc = (enc or "utf-8").lower()
    return _CHARSET_ALIASES.get(enc, enc)


def _decode(raw: str) -> str:
    if not raw:
        return ""
    out = ""
    for text, enc in decode_header(raw):
        if not isinstance(text, bytes):
            out += text
            continue
        try:
            out += text.decode(_normalize_charset(enc), errors="replace")
        except LookupError:
            out += text.decode("utf-8", errors="replace")
    return out


def _html_to_text(raw_html: str) -> str:
    """แปลง HTML → ข้อความอ่านได้ ใส่ " | " คั่นตรงขอบเขต block/cell (br, tr, p, div, li, td)
    ให้ได้ฟอร์แมตแบบเดียวกับที่ Gmail's own HTML→text converter สร้าง (ซึ่ง regex ทั้งหมด
    ใน ecom_calc.py ถูกออกแบบ/ทดสอบมาให้ตรงกับรูปแบบนี้อยู่แล้ว — ดูคอมเมนต์ที่นั่น) —
    ตั้งใจไม่เปลี่ยน regex ฝั่ง ecom_calc.py เลย เก็บ compatibility ไว้ที่จุดนี้จุดเดียว"""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw_html)
    text = re.sub(r"(?i)<(br|/tr|/p|/div|/li|/td)\s*/?>", " | ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return html_mod.unescape(text)


def _get_body(msg: email.message.Message) -> str:
    """คืนเนื้อหาอีเมลแบบอ่านได้ — ใช้ text/plain ถ้ามี ไม่งั้น fallback ไป text/html
    (แปลงผ่าน _html_to_text) เพราะยืนยันจากอีเมลจริงของ Shopee (info@mail.shopee.co.th)
    2026-09-20 ว่าเป็น multipart/alternative ที่มีแค่ text/html ล้วนๆ ไม่มี text/plain เลย —
    ก่อนแก้จุดนี้ฟังก์ชันคืนค่าว่างเปล่าให้อีเมลพวกนี้ทุกฉบับเงียบๆ (ไม่ error ไม่มี log)
    ทำให้ ecom_calc.parse_shopee_order_notice_email()/parse_shopee_return_emails() ได้
    body="" เสมอในโปรดักชันจริง แม้จะทดสอบผ่านแล้วด้วย body ที่ดึงผ่าน Gmail API (ซึ่ง
    Gmail แปลง HTML→text ให้เองอัตโนมัติ คนละเส้นทางกับ imaplib ที่ใช้ที่นี่ ไม่เจอปัญหานี้
    ตอนทดสอบเพราะไม่ได้จำลอง fetch แบบ IMAP จริง)"""
    if msg.is_multipart():
        html_part = None
        for part in msg.walk():
            if part.get("Content-Disposition"):
                continue
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode(_normalize_charset(part.get_content_charset()), errors="replace")
                except Exception:
                    continue
            elif part.get_content_type() == "text/html" and html_part is None:
                html_part = part
        if html_part is not None:
            try:
                raw_html = html_part.get_payload(decode=True).decode(_normalize_charset(html_part.get_content_charset()), errors="replace")
                return _html_to_text(raw_html)
            except Exception:
                return ""
        return ""
    try:
        payload = msg.get_payload(decode=True).decode(_normalize_charset(msg.get_content_charset()), errors="replace")
    except Exception:
        return ""
    return _html_to_text(payload) if msg.get_content_type() == "text/html" else payload


def fetch_account(account: dict) -> list[dict]:
    """คืน [{subject, sender, body}] ของอีเมลที่ได้รับใน 24 ชม.ที่ผ่านมาจากบัญชีนี้"""
    label = account.get("label") or account.get("user", "?")
    found = []
    try:
        conn = imaplib.IMAP4_SSL(account["host"])
        conn.login(account["user"], account["password"])
        conn.select("INBOX")
        since = (datetime.now() - timedelta(days=1)).strftime("%d-%b-%Y")
        status, data = conn.search(None, f'(SINCE "{since}")')
        if status != "OK":
            print(f"⚠️ [{label}] ค้นหาอีเมลไม่สำเร็จ")
            return found
        for num in data[0].split():
            status, msg_data = conn.fetch(num, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            try:
                msg = email.message_from_bytes(msg_data[0][1])
                found.append({
                    "subject": _decode(msg.get("Subject", "")),
                    "sender": _decode(msg.get("From", "")),
                    "body": _get_body(msg),
                })
            except Exception as e:
                # อีเมล 1 ฉบับพังไม่ควรทำให้ทั้งบัญชีเสียหมด (เจอจริง: charset แปลกใน
                # Subject header ทำให้ LookupError หลุดออกมาที่นี่ ก่อนแก้ _decode())
                print(f"⚠️ [{label}] ข้ามอีเมล 1 ฉบับที่ parse ไม่ได้: {e}")
        conn.logout()
        print(f"✅ [{label}] เช็คแล้ว {len(found)} ฉบับ (24 ชม.ที่ผ่านมา)")
    except Exception as e:
        print(f"❌ [{label}] เช็คอีเมลไม่สำเร็จ: {e}")
    return found


def main():
    accounts_raw = os.environ.get("EMAIL_ACCOUNTS", "")
    if not accounts_raw:
        print("❌ ไม่พบ EMAIL_ACCOUNTS ใน .env — ดู .env.example")
        sys.exit(1)
    try:
        accounts = json.loads(accounts_raw)
    except json.JSONDecodeError as e:
        print(f"❌ EMAIL_ACCOUNTS ใน .env ไม่ใช่ JSON ที่ถูกต้อง: {e}")
        sys.exit(1)

    sb = _get_supabase()
    platform_lines: dict[str, list[str]] = {}
    order_notices: dict[str, tuple[dict, str]] = {}  # order_sn -> (parsed, notice_subject), เอาตัวหลังสุดในรอบนี้
    n_saved = 0
    for account in accounts:
        for mail in fetch_account(account):
            platform = _detect_platform_return_problem(mail["subject"], mail["sender"], mail["body"])
            if platform:
                platform_lines.setdefault(platform, []).append(f"• {mail['subject']}")
                # เก็บลง Supabase เฉพาะ Shopee เท่านั้น — parser โครงสร้าง
                # (ecom_calc.parse_shopee_return_emails) รู้จักฟอร์แมตอีเมลจริงของ Shopee
                # แค่แพลตฟอร์มเดียว (ยืนยันด้วยอีเมลจริง 2026-09-19) ให้แอปโชว์ต่อที่
                # 🛒 E-commerce → ตรวจสอบปัญหา → "ออเดอร์ตีกลับ (จากอีเมลแจ้งเตือน Shopee)"
                if platform == "Shopee":
                    for order in ecom_calc.parse_shopee_return_emails(mail["subject"], mail["body"]):
                        _upsert_ecommerce_return_email(
                            sb, order_sn=order["order_sn"], carrier_name=order["carrier_name"],
                            tracking_no=order["tracking_no"], notice_subject=mail["subject"],
                            shop_name=account.get("label"), platform="shopee",
                        )
                        n_saved += 1
                continue
            # เช็คอีเมลแจ้งออเดอร์ใหม่/ยกเลิกของ Shopee (คนละแบบกับพัสดุตีกลับด้านบน) —
            # เก็บล่าสุดต่อ order_sn ไว้ก่อน ค่อย upsert+สรุปทีเดียวหลัง loop เพราะถ้าออเดอร์
            # เดียวกันถูกยกเลิกในรอบ 24 ชม.เดียวกัน ต้องไม่นับเข้าสรุปว่าเป็นออเดอร์ที่ยืนยันแล้ว
            order = ecom_calc.parse_shopee_order_notice_email(mail["subject"], mail["body"])
            if order:
                order_notices[order["order_sn"]] = (order, mail["subject"])

    # ชื่อสินค้าที่เคย map ไว้แล้วผ่าน 🛒 E-commerce → ⚙️ ตั้งค่า/นำเข้าข้อมูล → "Map ชื่อสินค้า
    # จากอีเมล → รหัสสินค้า" — ใช้ย่อชื่อยาวๆ ในข้อความ LINE ด้วย (เดิมส่งชื่อดิบเต็มความยาว)
    _notice_map_rows = _fetch_all_sb(
        lambda: sb.table("ecommerce_product_map").select("platform_item_id,product_id,units_per_pack")
        .eq("platform", "shopee_notice")
    )
    notice_map = {
        r["platform_item_id"]: {"product_id": r["product_id"], "units_per_pack": r.get("units_per_pack")}
        for r in _notice_map_rows
    }

    shop_summary: dict[str, dict] = {}
    for order, notice_subject in order_notices.values():
        _upsert_ecommerce_order_notice(sb, order, notice_subject=notice_subject, platform="shopee")
        n_saved += 1
        shop = order.get("shop_name") or "?"
        entry = shop_summary.setdefault(shop, {"cod": 0, "transfer": 0, "cancelled": 0, "items": {}})
        if order["status"] == "ยกเลิก":
            entry["cancelled"] += 1
            continue
        if order.get("order_type") == "cod":
            entry["cod"] += 1
        elif order.get("order_type") == "transfer":
            entry["transfer"] += 1
        for it in order.get("items") or []:
            label, eff_qty = _resolve_notice_item(it["name"], it.get("variant") or "", it["qty"], notice_map)
            entry["items"][label] = entry["items"].get(label, 0) + eff_qty

    if n_saved:
        print(f"💾 บันทึกลง Supabase แล้ว {n_saved} รายการ (ตีกลับ+ออเดอร์ใหม่ รวมกัน)")

    # sync สถานะจัดส่งจาก iShip ก่อน (ดู _sync_iship_delivery_statuses docstring) ให้ ship_rows
    # ด้านล่างเห็นสถานะสดของวันนี้เลย ไม่ใช่ของเก่าที่ไม่เคย sync
    _sync_iship_delivery_statuses(sb)

    # ── shipments (ระบบขายของร้านเอง ไม่ใช่ Shopee/e-commerce) — ดึงครั้งเดียวใช้ร่วมกัน 2 จุด:
    # COD ที่รับเงินแล้วแต่ยังไม่เปิดบิล + พัสดุไม่ใช่ COD ที่ค้างส่งเกิน 3 วัน (เหมือน
    # dashboard_ui.py's การ์ด COD + การ์ดพัสดุล่าช้าทุกประการ — เพิ่มเข้า digest เพราะทั้งคู่
    # เป็นรายการที่ต้องรีบตามงาน ไม่ใช่แค่ดูเฉยๆ)
    txn_rows = _fetch_all_sb(lambda: sb.table("transactions").select("customer_id, customers(name)")
                              .eq("pay_status", "COD").eq("bill_status", "ยังไม่เปิดบิล").order("id"))
    ship_rows = _fetch_all_sb(lambda: sb.table("shipments").select("*, customers(name)").order("id"))
    cod_unbilled = _build_cod_unbilled_rows(txn_rows, ship_rows)
    slow_ships = _build_slow_shipment_rows(ship_rows, datetime.now(timezone.utc))

    if not platform_lines and not shop_summary and not cod_unbilled and not slow_ships:
        print("วันนี้ไม่มีอีเมลที่เข้าเกณฑ์ — ไม่ส่ง LINE")
        return

    parts = [f"📧 สรุปอีเมลประจำวัน ({datetime.now().strftime('%d/%m/%Y')})"]
    for platform in ["Shopee", "Lazada", "TikTok"]:
        lines = platform_lines.get(platform)
        if lines:
            parts.append(f"\n📦 พัสดุ {platform} มีปัญหา/ตีกลับ/ตีคืน:")
            parts += lines
    if shop_summary:
        parts.append("\n📦 สรุปออเดอร์วันนี้ (Shopee จากอีเมล):")
        for shop, s in shop_summary.items():
            total_orders = s["cod"] + s["transfer"]
            line = f"ร้าน {shop}: {total_orders} ออเดอร์ (COD {s['cod']} / โอนแล้ว {s['transfer']})"
            if s["cancelled"]:
                line += f" — ยกเลิก {s['cancelled']}"
            parts.append(line)
            for name, qty in s["items"].items():
                parts.append(f"  • {name} x{qty}")
    if cod_unbilled:
        _shown, _more = _capped_rows(cod_unbilled)
        parts.append(f"\n💰 COD รับเงินแล้ว แต่ยังไม่เปิดบิล ({len(cod_unbilled)} รายการ):")
        for r in _shown:
            parts.append(f"• {r['customer']} — {r['items']} ({r['cod_amount']:,.0f}฿, {r['tracking_no']})")
        if _more:
            parts.append(f"...และอีก {_more} รายการ ดูทั้งหมดที่หน้าแรก")
    if slow_ships:
        _shown, _more = _capped_rows(slow_ships)
        parts.append(f"\n🐌 พัสดุค้างส่งเกิน 3 วัน ({len(slow_ships)} รายการ — แสดง {len(_shown)} รายการที่ค้างนานสุด):")
        for r in _shown:
            parts.append(f"• {r['customer']} — {r['date']} ({r['days']} วัน) — {r['items']} [{r['carrier']} {r['tracking_no']}]")
        if _more:
            parts.append(f"...และอีก {_more} รายการ ดูทั้งหมดที่หน้าแรก")
    text = "\n".join(parts)

    staff_line_id = os.environ.get("STAFF_LINE_USER_ID", "")
    if not staff_line_id:
        print("❌ ไม่พบ STAFF_LINE_USER_ID ใน .env — พิมพ์สรุปที่จะส่งไว้แทน:\n")
        print(text)
        return

    result = _push_line_text(staff_line_id, text)
    print("✅ ส่ง LINE สรุปแล้ว" if result.get("ok") else f"❌ ส่ง LINE ไม่สำเร็จ: {result.get('error')}")


if __name__ == "__main__":
    main()
