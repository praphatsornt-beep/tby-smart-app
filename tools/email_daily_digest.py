"""
รัน: uv run tools/email_daily_digest.py
หรือ: python tools/email_daily_digest.py

เช็คอีเมล 4 บัญชี (IMAP) หา 2 อย่าง แล้วสรุปส่งเข้า LINE ส่วนตัวเจ้าของร้านวันละครั้ง:
  1. พัสดุ Shopee/Lazada/TikTok ที่มีปัญหา/ตีกลับ/ถูกตีคืน (เชื่อม API ทั้ง 3 แพลตฟอร์ม
     ไม่ได้ — Shopee ถูกปฏิเสธที่ Seller Identification เพราะไม่ใช่ Managed/Mall Seller,
     Lazada/TikTok ก็ไม่มี integration เหมือนกัน — อีเมลคือทางเดียวที่มีตอนนี้)
  2. อีเมลแจ้งยอดบัตรเครดิต/statement จากธนาคาร

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
import sys
import json
import imaplib
import email
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


def _upsert_ecommerce_return_email(
    sb, order_sn: str, carrier_name: str, tracking_no: str, notice_subject: str, platform: str = "shopee",
) -> None:
    """เหมือน database.upsert_ecommerce_return_email() แต่คุย Supabase ตรงๆ ผ่าน sb ที่รับมา
    (ไม่ import database.py — ดู docstring บนสุดของไฟล์) upsert คีย์ (platform, order_sn)
    เอง, notice_count +1 ทุกครั้งที่เจอซ้ำ, คง first_seen_at เดิมไว้"""
    existing = sb.table("ecommerce_return_emails").select("id,notice_count") \
        .eq("platform", platform).eq("order_sn", order_sn).execute().data
    now = datetime.now(timezone.utc).isoformat()
    if existing:
        row = existing[0]
        sb.table("ecommerce_return_emails").update({
            "carrier_name": carrier_name, "tracking_no": tracking_no, "notice_subject": notice_subject,
            "notice_count": (row.get("notice_count") or 1) + 1, "last_seen_at": now,
        }).eq("id", row["id"]).execute()
    else:
        sb.table("ecommerce_return_emails").insert({
            "platform": platform, "order_sn": order_sn, "carrier_name": carrier_name,
            "tracking_no": tracking_no, "notice_subject": notice_subject,
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

def _decode(raw: str) -> str:
    if not raw:
        return ""
    out = ""
    for text, enc in decode_header(raw):
        out += text.decode(enc or "utf-8", errors="replace") if isinstance(text, bytes) else text
    return out


def _get_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get("Content-Disposition"):
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                except Exception:
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return ""


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
            msg = email.message_from_bytes(msg_data[0][1])
            found.append({
                "subject": _decode(msg.get("Subject", "")),
                "sender": _decode(msg.get("From", "")),
                "body": _get_body(msg),
            })
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
                            platform="shopee",
                        )
                        n_saved += 1
            elif _is_bank_statement(mail["subject"], mail["sender"], mail["body"]):
                bank_lines.append(f"• {mail['subject']}")
    if n_saved:
        print(f"💾 บันทึกออเดอร์ตีกลับ (Shopee) ลง Supabase แล้ว {n_saved} ออเดอร์")

    if not platform_lines and not bank_lines:
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
