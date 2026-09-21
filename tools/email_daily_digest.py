"""
รัน: uv run tools/email_daily_digest.py
หรือ: python tools/email_daily_digest.py

เช็คอีเมล 4 บัญชี (IMAP) หา 3 อย่าง แล้วสรุปส่งเข้า LINE ส่วนตัวเจ้าของร้านวันละครั้ง:
  1. พัสดุ Shopee/Lazada/TikTok ที่มีปัญหา/ตีกลับ/ถูกตีคืน (เชื่อม API ทั้ง 3 แพลตฟอร์ม
     ไม่ได้ — Shopee ถูกปฏิเสธที่ Seller Identification เพราะไม่ใช่ Managed/Mall Seller,
     Lazada/TikTok ก็ไม่มี integration เหมือนกัน — อีเมลคือทางเดียวที่มีตอนนี้)
  2. อีเมลแจ้งยอดบัตรเครดิต/statement จากธนาคาร
  3. อีเมลแจ้งออเดอร์ใหม่/ยกเลิกของ Shopee — สรุปจำนวนออเดอร์+สินค้า/จำนวนต่อร้านแบบ
     เรียลไทม์ (ดู `ecom_calc.parse_shopee_order_notice_email`) บันทึกลง Supabase ตาราง
     `ecommerce_order_notices` ให้แอปโชว์ต่อที่ 🛒 E-commerce → ตรวจสอบปัญหา เหมือนกัน
     (Lazada/TikTok ยังไม่เช็คว่ามีอีเมลแบบนี้หรือไม่ — ทำ Shopee ก่อน)

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

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

import httpx
from supabase import create_client

import ecom_calc

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


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


def _build_cod_unbilled_rows(txn_rows: list[dict], ship_rows: list[dict]) -> list[dict]:
    """จับคู่ shipments ที่เป็น COD และโอนเงินมาแล้ว (cod_transferred_at ไม่ null) กับลูกค้า
    ที่ยังมีแถว transactions สถานะ COD+"ยังไม่เปิดบิล" ค้างอยู่ — แมตช์ด้วยชื่อลูกค้าเหมือนกับ
    ที่ dashboard_ui.py ทำในการ์ด "✅ รับแล้ว — ยังไม่เปิดบิล" (shipments ไม่มี FK ตรงไปยัง
    transactions/bill รายตัวให้จับคู่แม่นกว่านี้ได้) รับ txn_rows/ship_rows เป็นผลลัพธ์ดิบจาก
    .execute().data ของ Supabase ตรงๆ — แยกออกมาเป็นฟังก์ชัน pure ให้ทดสอบได้โดยไม่ต้องปลอม
    Supabase client (เพิ่ม 2026-09-21 ตามคำขอ user)"""
    unbilled_names = {
        (t.get("customers") or {}).get("name")
        for t in txn_rows
        if (t.get("customers") or {}).get("name")
    }
    if not unbilled_names:
        return []
    rows = []
    for sh in ship_rows:
        cname = (sh.get("customers") or {}).get("name") or sh.get("recipient_name") or "—"
        if cname not in unbilled_names:
            continue
        items = sh.get("items") or []
        items_str = ", ".join(
            f"{it.get('name') or it.get('product_id', '')} x{it.get('qty', 1)}" for it in items
        ) or "—"
        rows.append({
            "customer": cname,
            "items": items_str,
            "cod_amount": float(sh.get("cod_amount") or 0),
            "tracking_no": sh.get("tracking_no") or "—",
        })
    return rows


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


_BANK_DOMAINS = [
    "scb.co.th", "kasikornbank.com", "bangkokbank.com",
    "ktb.co.th", "krungsri.com", "tmbthanachart.com",
]
_BANK_KEYWORDS = ["statement", "ยอดชำระ", "บัตรเครดิต", "credit card", "ใบแจ้งยอด"]


def _is_bank_statement(subject: str, sender: str, body: str) -> bool:
    if not any(d in sender.lower() for d in _BANK_DOMAINS):
        return False
    text = f"{subject} {body}".lower()
    return any(k in text for k in _BANK_KEYWORDS)


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
    bank_lines = []
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
            if _is_bank_statement(mail["subject"], mail["sender"], mail["body"]):
                bank_lines.append(f"• {mail['subject']}")
                continue
            # เช็คอีเมลแจ้งออเดอร์ใหม่/ยกเลิกของ Shopee (คนละแบบกับพัสดุตีกลับด้านบน) —
            # เก็บล่าสุดต่อ order_sn ไว้ก่อน ค่อย upsert+สรุปทีเดียวหลัง loop เพราะถ้าออเดอร์
            # เดียวกันถูกยกเลิกในรอบ 24 ชม.เดียวกัน ต้องไม่นับเข้าสรุปว่าเป็นออเดอร์ที่ยืนยันแล้ว
            order = ecom_calc.parse_shopee_order_notice_email(mail["subject"], mail["body"])
            if order:
                order_notices[order["order_sn"]] = (order, mail["subject"])

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
            entry["items"][it["name"]] = entry["items"].get(it["name"], 0) + it["qty"]

    if n_saved:
        print(f"💾 บันทึกลง Supabase แล้ว {n_saved} รายการ (ตีกลับ+ออเดอร์ใหม่ รวมกัน)")

    # ── COD (ระบบขายของร้านเอง ไม่ใช่ Shopee/e-commerce) ที่รับเงินแล้วแต่ยังไม่เปิดบิล ──
    # เหมือนการ์ด "✅ รับแล้ว — ยังไม่เปิดบิล" ใน dashboard_ui.py ทุกประการ — เพิ่มเข้า digest
    # เพราะเป็นรายการที่ต้องรีบเปิดบิลให้ลูกค้า (เงินเข้าร้านแล้วแต่บัญชียังไม่ตัด)
    txn_rows = _fetch_all_sb(lambda: sb.table("transactions").select("customer_id, customers(name)")
                              .eq("pay_status", "COD").eq("bill_status", "ยังไม่เปิดบิล").order("id"))
    ship_rows = _fetch_all_sb(lambda: sb.table("shipments").select("*, customers(name)")
                               .gt("cod_amount", 0).not_.is_("cod_transferred_at", "null").order("id"))
    cod_unbilled = _build_cod_unbilled_rows(txn_rows, ship_rows)

    if not platform_lines and not bank_lines and not shop_summary and not cod_unbilled:
        print("วันนี้ไม่มีอีเมลที่เข้าเกณฑ์ — ไม่ส่ง LINE")
        return

    parts = [f"📧 สรุปอีเมลประจำวัน ({datetime.now().strftime('%d/%m/%Y')})"]
    for platform in ["Shopee", "Lazada", "TikTok"]:
        lines = platform_lines.get(platform)
        if lines:
            parts.append(f"\n📦 พัสดุ {platform} มีปัญหา/ตีกลับ/ตีคืน:")
            parts += lines
    if bank_lines:
        parts.append("\n💳 แจ้งยอดบัตรเครดิต:")
        parts += bank_lines
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
        parts.append(f"\n💰 COD รับเงินแล้ว แต่ยังไม่เปิดบิล ({len(cod_unbilled)} รายการ):")
        for r in cod_unbilled:
            parts.append(f"• {r['customer']} — {r['items']} ({r['cod_amount']:,.0f}฿, {r['tracking_no']})")
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
