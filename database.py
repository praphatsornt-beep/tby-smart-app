import os
import time
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client, Client
import pandas as pd
from collections import defaultdict
from math import floor
import uuid
import tiktok_income_import
import ecom_calc


def _retry(fn, attempts: int = 2, delay: float = 0.5):
    """เรียก fn() ซ้ำถ้าเกิด network error"""
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i < attempts - 1:
                time.sleep(delay)
            else:
                raise

load_dotenv()


@st.cache_resource
def get_supabase() -> Client:
    url = os.environ.get("SUPABASE_URL") or st.secrets.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY") or st.secrets.get("SUPABASE_KEY", "")
    if not url or not key:
        st.error("❌ ไม่พบ Supabase credentials — กรุณาตั้งค่า .env")
        st.stop()
    return create_client(url, key)


# ─── Master data ────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def get_products() -> list[dict]:
    return get_supabase().table("products").select("*").order("id").execute().data


@st.cache_data(ttl=300)
def get_customers() -> list[dict]:
    return get_supabase().table("customers").select("*").order("name").execute().data


def get_customer_by_phone(phone: str) -> dict | None:
    rows = get_supabase().table("customers").select("*").eq("phone", phone.strip()).execute().data
    return rows[0] if rows else None


# ─── Customer Addresses (แยก table — 1 ลูกค้า มีได้หลายที่อยู่) ────────────

@st.cache_data(ttl=120)
def _all_customer_addresses() -> list[dict]:
    return get_supabase().table("customer_addresses").select("*, customers(name)").order("phone").execute().data


def get_customer_addresses(customer_id: str = None) -> list[dict]:
    all_addr = _all_customer_addresses()
    if customer_id:
        return [a for a in all_addr if a.get("customer_id") == customer_id]
    return all_addr


def get_address_by_phone(phone: str) -> dict | None:
    rows = (get_supabase().table("customer_addresses")
            .select("*, customers(name)").eq("phone", phone.strip()).execute().data)
    return rows[0] if rows else None


def upsert_customer_address(data: dict) -> None:
    db = get_supabase()
    # ลบแถวเดิมที่มี id เดียวกันก่อนเสมอ (กรณีแก้ไขที่อยู่เดิม) — ถ้าใช้แค่ eq("phone", ...)
    # แล้ว phone ว่าง แถวเดิมจะไม่ถูกลบ ทำให้ insert ชนกับ primary key เดิม
    _retry(lambda: db.table("customer_addresses").delete().eq("id", data["id"]).execute())
    if data.get("phone"):
        # ตั้งใจลบทุกแถวที่เบอร์นี้ทิ้งก่อน insert เสมอ (ยืนยันจากผู้ใช้ 2026-09-01) — เบอร์
        # เดียวกัน = ที่อยู่ล่าสุดของเบอร์นั้นเท่านั้นที่ถูกต้อง ไม่เก็บที่อยู่เก่าซ้ำไว้
        _retry(lambda: db.table("customer_addresses").delete().eq("phone", data["phone"].strip()).execute())
    _retry(lambda: db.table("customer_addresses").insert(data).execute())
    _all_customer_addresses.clear()


def delete_customer_address(address_id: str) -> None:
    _retry(lambda: get_supabase().table("customer_addresses").delete().eq("id", address_id).execute())
    _all_customer_addresses.clear()


def upsert_product(data: dict) -> None:
    _retry(lambda: get_supabase().table("products").upsert(data).execute())
    get_products.clear()


def upsert_products_batch(rows: list[dict]) -> None:
    """บันทึกสินค้าหลายรายการพร้อมกัน — batch แทนการลูปทีละแถว (ลด round-trip)"""
    if not rows:
        return
    db = get_supabase()
    for i in range(0, len(rows), 50):
        _chunk = rows[i:i + 50]
        _retry(lambda: db.table("products").upsert(_chunk).execute())
    get_products.clear()


def upsert_customer(data: dict) -> None:
    _retry(lambda: get_supabase().table("customers").upsert(data).execute())
    get_customers.clear()


def upsert_customers_batch(rows: list[dict]) -> None:
    """บันทึกลูกค้าหลายรายการพร้อมกัน — batch แทนการลูปทีละแถว (ลด round-trip)"""
    if not rows:
        return
    db = get_supabase()
    for i in range(0, len(rows), 50):
        _chunk = rows[i:i + 50]
        _retry(lambda: db.table("customers").upsert(_chunk).execute())
    get_customers.clear()


def update_customer_address(customer_id: str, data: dict) -> None:
    """อัปเดตที่อยู่จัดส่งของลูกค้า (recipient_name, phone, address, postal_code)"""
    _retry(lambda: get_supabase().table("customers").update(data).eq("id", customer_id).execute())



# ─── Transactions ────────────────────────────────────────────────────────────

def _clear_transaction_caches() -> None:
    get_all_transactions_df.clear()
    get_customer_ids_with_transactions.clear()
    get_outstanding_df.clear()
    get_unbilled_pv_summary.clear()
    get_customer_ledger.clear()
    get_bill_summaries.clear()
    get_bill_list.clear()
    get_pending_receipts_for_customer.clear()
    get_unbilled_received_qty_by_product.clear()
    get_billed_not_received_qty_by_product.clear()
    get_today_transactions.clear()


def insert_transaction(data: dict) -> None:
    _retry(lambda: get_supabase().table("transactions").insert(data).execute())
    _clear_transaction_caches()


def insert_transactions_batch(rows: list[dict]) -> None:
    if rows:
        _retry(lambda: get_supabase().table("transactions").insert(rows).execute())
        _clear_transaction_caches()


def get_next_bill_no(date_str: str) -> str:
    """สร้างเลขบิล YYMMDD-NNN ถัดไปสำหรับวันที่นั้น"""
    prefix = str(date_str).replace("-", "")[2:]  # "2026-04-25" → "260425"
    rows = (get_supabase()
            .table("transactions")
            .select("bill_no")
            .like("bill_no", f"{prefix}-%")
            .execute().data)
    nums = []
    for r in rows:
        bn = r.get("bill_no") or ""
        if bn.startswith(f"{prefix}-"):
            try:
                nums.append(int(bn.split("-")[1]))
            except ValueError:
                pass
    return f"{prefix}-{max(nums, default=0) + 1:03d}"


def _clear_partial_event_caches() -> None:
    get_all_transactions_df.clear()
    get_outstanding_df.clear()
    get_unbilled_pv_summary.clear()
    bill_has_partial_events.clear()
    get_customer_ledger.clear()
    get_pending_receipts_for_customer.clear()
    get_unbilled_received_qty_by_product.clear()
    get_billed_not_received_qty_by_product.clear()
    get_today_transactions.clear()


def insert_partial_event(data: dict) -> None:
    _retry(lambda: get_supabase().table("partial_events").insert(data).execute())
    _clear_partial_event_caches()


def insert_partial_events_batch(rows: list[dict]) -> None:
    """บันทึกหลาย partial_events พร้อมกัน — batch แทนการลูปทีละรายการ (ลด round-trip)"""
    if not rows:
        return
    db = get_supabase()
    for i in range(0, len(rows), 50):
        _chunk = rows[i:i + 50]
        _retry(lambda: db.table("partial_events").insert(_chunk).execute())
    _clear_partial_event_caches()


def update_transaction_statuses_batch(transaction_ids: list[str], pay_status: str = None) -> None:
    """อัปเดต pay_status ให้หลาย transaction พร้อมกัน (ค่าเดียวกันทุกแถว) batch
    แทนการลูปทีละรายการ (ลด round-trip) — เปิดบิลไม่ใช้ฟังก์ชันนี้แล้ว (ดู
    open_bill_partial ที่ insert bill_open_events ทีละแถว เพราะแต่ละแถวอาจมี
    จำนวนที่จะเปิดบิลไม่เท่ากัน)"""
    if not pay_status or not transaction_ids:
        return
    db = get_supabase()
    for i in range(0, len(transaction_ids), 50):
        chunk = transaction_ids[i:i + 50]
        _retry(lambda: db.table("transactions").update({"pay_status": pay_status}).in_("id", chunk).execute())
    _clear_transaction_caches()


def _bill_open_qty_sum(transaction_id: str) -> int:
    """ผลรวม qty_opened จาก bill_open_events ทั้งหมดของแถวนี้ (รวม correction
    event ติดลบจาก undo_last_bill_open_event ด้วย) — floor ที่ 0"""
    db = get_supabase()
    evts = _retry(lambda: db.table("bill_open_events").select("qty_opened").eq(
        "transaction_id", transaction_id).execute()).data
    return max(0, sum(int(e["qty_opened"] or 0) for e in evts))


def open_bill_partial(transaction_id: str, qty_to_open: int, note: str = None, date: str = None) -> None:
    """เปิดบิล qty_to_open ชิ้นของแถวนี้ — ไม่แยกแถวอีกต่อไป (เทียบเท่า
    split_and_open_bill เดิม แต่เป็น event-based เหมือน partial_events) เลขบิล
    จริงจาก Zhulian (ถ้ามี) เก็บเป็นแค่โน้ต optional ไม่ validate/ไม่เช็คซ้ำข้าม
    ลูกค้า — bill_no ของแถว transactions ไม่ถูกแตะต้องเลย คงเป็นเลขอ้างอิงภายใน
    ตลอดอายุแถว bill_status จะเปลี่ยนเป็น "เปิดบิลแล้ว" ก็ต่อเมื่อผลรวมที่เปิดบิล
    สะสมครบเท่ากับ qty ทั้งหมดของแถว (แบบเดียวกับที่ pay_status เปลี่ยนเป็น
    "จ่ายแล้ว" ก็ต่อเมื่อยอดจ่ายสะสมครบ total_amount)"""
    db = get_supabase()
    txn = _retry(lambda: db.table("transactions").select("qty,bill_status").eq(
        "id", transaction_id).single().execute()).data
    from datetime import date as _dateclass
    _date = date or _dateclass.today().isoformat()
    _retry(lambda: db.table("bill_open_events").insert({
        "id": str(uuid.uuid4()), "date": _date, "transaction_id": transaction_id,
        "qty_opened": qty_to_open, "note": note,
    }).execute())
    _opened_sum = _bill_open_qty_sum(transaction_id)
    if _opened_sum >= int(txn["qty"]) and txn["bill_status"] != "เปิดบิลแล้ว":
        _retry(lambda: db.table("transactions").update({
            "bill_status": "เปิดบิลแล้ว", "bill_opened_at": _date,
        }).eq("id", transaction_id).execute())
    _clear_transaction_caches()


def undo_last_bill_open_event(transaction_id: str) -> None:
    """ยกเลิกการเปิดบิลครั้งล่าสุด (undo) — insert correction event ติดลบหักล้าง
    event ล่าสุด (ไม่ลบ/ไม่แก้ของเดิม เก็บ audit trail ไว้เหมือน partial_events)
    แล้วเช็คยอดเปิดบิลสะสมใหม่ ถ้าต่ำกว่า qty ทั้งหมดของแถว ให้คืน bill_status
    เป็น "ยังไม่เปิดบิล" และเคลียร์ bill_opened_at
    แถวเก่าที่เปิดบิลไปตั้งแต่ก่อนมี bill_open_events (bill_status ถูกตั้งตรงๆ
    ไม่มี event ผูกอยู่เลย — ดู comment ที่ get_all_transactions_df) จะไม่มี event
    ให้ undo เลย ต้องสลับ bill_status กลับตรงๆ แทน ไม่งั้นฟังก์ชันนี้จะ no-op เงียบๆ"""
    db = get_supabase()
    _last = _retry(lambda: db.table("bill_open_events").select("*").eq(
        "transaction_id", transaction_id).order("created_at", desc=True).limit(1).execute()).data
    if not _last:
        _retry(lambda: db.table("transactions").update({
            "bill_status": "ยังไม่เปิดบิล", "bill_opened_at": None,
        }).eq("id", transaction_id).execute())
        _clear_transaction_caches()
        return
    _last = _last[0]
    _retry(lambda: db.table("bill_open_events").insert({
        "id": str(uuid.uuid4()), "date": _last["date"], "transaction_id": transaction_id,
        "qty_opened": -int(_last["qty_opened"]),
        "note": "ยกเลิกเปิดบิล (undo)",
    }).execute())
    txn = _retry(lambda: db.table("transactions").select("qty").eq(
        "id", transaction_id).single().execute()).data
    _opened_sum = _bill_open_qty_sum(transaction_id)
    if _opened_sum < int(txn["qty"]):
        _retry(lambda: db.table("transactions").update({
            "bill_status": "ยังไม่เปิดบิล", "bill_opened_at": None,
        }).eq("id", transaction_id).execute())
    _clear_transaction_caches()


def update_transaction(transaction_id: str, data: dict) -> None:
    _retry(lambda: get_supabase().table("transactions").update(data).eq("id", transaction_id).execute())
    _clear_transaction_caches()


def update_transaction_status(transaction_id: str, pay_status: str = None) -> None:
    """อัปเดต pay_status — เปิด/ย้อนเปิดบิลไม่ใช้ฟังก์ชันนี้แล้ว (ดู
    open_bill_partial/undo_last_bill_open_event)"""
    if not pay_status:
        return
    _retry(lambda: get_supabase().table("transactions").update(
        {"pay_status": pay_status}).eq("id", transaction_id).execute())
    _clear_transaction_caches()


# ─── Calculations ────────────────────────────────────────────────────────────

_FULLY_PAID_STATUSES = ("จ่ายแล้ว", "COD จ่ายแล้ว")


def _compute_balance(txn: dict, partial_paid: float, qty_received_sum: int) -> dict:
    """ยอดจ่าย/รับสะสมของ transaction เดียว จาก partial_events ที่รวมมาแล้ว
    (partial_paid = Σ amount_paid, qty_received_sum = Σ qty_received) — single
    source of truth ให้ get_transaction_balance/get_all_transactions_df/
    get_pending_receipts_for_customer เรียกใช้ร่วมกัน แทนคำนวณซ้ำคนละที่
    (เคยไม่ตรงกัน: จุดหนึ่งเช็คแค่ pay_status == "จ่ายแล้ว" ไม่รวม "COD จ่ายแล้ว")"""
    total_amount = float(txn["total_amount"])
    total_paid = total_amount if txn["pay_status"] in _FULLY_PAID_STATUSES else partial_paid
    total_received = int(txn["initial_qty_received"]) + int(qty_received_sum)
    return {
        "total_paid": total_paid,
        "total_received": total_received,
        "outstanding_amount": total_amount - total_paid,
        "outstanding_qty": txn["qty"] - total_received,
    }


def get_transaction_balance(transaction_id: str) -> dict:
    """ยอดจ่ายและรับของสะสมของรายการ พร้อมจำนวนที่รับได้อีก"""
    db = get_supabase()
    _rows = _retry(lambda: db.table("transactions").select("*").eq("id", transaction_id).execute().data)
    if not _rows:
        return None
    txn = _rows[0]
    events = _retry(lambda: db.table("partial_events").select("*").eq("transaction_id", transaction_id).execute().data)

    _partial_paid = sum(float(e["amount_paid"]) for e in events)
    _qty_received_sum = sum(e["qty_received"] for e in events)
    bal = _compute_balance(txn, _partial_paid, _qty_received_sum)

    price = float(txn["price_per_unit"])
    max_allowed = floor(bal["total_paid"] / price) if price > 0 else 0

    return {
        "transaction": txn,
        **bal,
        "max_allowed_qty": max_allowed,
        "can_receive": max(0, max_allowed - bal["total_received"]),
    }


def get_last_payment_date(transaction_ids: list) -> str:
    """คืนวันที่รับเงินล่าสุด (max date ที่ amount_paid > 0) จาก partial_events"""
    if not transaction_ids:
        return ""
    try:
        db = get_supabase()
        rows = []
        for _i in range(0, len(transaction_ids), 50):
            _chunk = transaction_ids[_i:_i + 50]
            rows += (db.table("partial_events")
                     .select("date, amount_paid")
                     .in_("transaction_id", _chunk)
                     .gt("amount_paid", 0)
                     .execute().data)
        if not rows:
            return ""
        return max(r["date"] for r in rows)[:10]
    except Exception:
        return ""


def delete_transaction(transaction_id: str) -> None:
    db = get_supabase()
    _retry(lambda: db.table("partial_events").delete().eq("transaction_id", transaction_id).execute())
    _retry(lambda: db.table("transactions").delete().eq("id", transaction_id).execute())
    _clear_transaction_caches()


def delete_transactions_batch(transaction_ids: list[str]) -> None:
    """ลบหลาย transaction พร้อมกัน — batch แทนการลูปทีละรายการ (ลด round-trip)"""
    if not transaction_ids:
        return
    db = get_supabase()
    for i in range(0, len(transaction_ids), 50):
        chunk = transaction_ids[i:i + 50]
        _retry(lambda: db.table("partial_events").delete().in_("transaction_id", chunk).execute())
        _retry(lambda: db.table("transactions").delete().in_("id", chunk).execute())
    _clear_transaction_caches()


def get_bill_details(bill_no: str) -> list[dict]:
    return (get_supabase().table("transactions")
            .select("product_name, qty, price_per_unit, total_amount, customers(name), date, bill_status")
            .eq("bill_no", bill_no).execute().data)


def update_bill_customer(bill_no: str, new_customer_id: str) -> None:
    _retry(lambda: get_supabase().table("transactions")
           .update({"customer_id": new_customer_id})
           .eq("bill_no", bill_no).execute())
    _clear_transaction_caches()


@st.cache_data(ttl=60)
def bill_has_partial_events(bill_no: str) -> bool:
    """True ถ้าบิลนี้มีการจ่าย/รับของ/เปิดบิลบางส่วนไปแล้ว — กันย้ายบิลข้ามลูกค้า
    ทั้งที่มีประวัติผูกอยู่แล้ว"""
    db = get_supabase()
    txn_ids = [r["id"] for r in db.table("transactions").select("id").eq("bill_no", bill_no).execute().data]
    if not txn_ids:
        return False
    events = db.table("partial_events").select("id").in_("transaction_id", txn_ids).limit(1).execute().data
    if events:
        return True
    open_events = db.table("bill_open_events").select("id").in_("transaction_id", txn_ids).limit(1).execute().data
    return bool(open_events)


def delete_bill(bill_no: str, customer_id: str = None) -> int:
    """ลบทุก transaction ที่มีเลขบิลนี้ — ถ้าระบุ customer_id จะกรองเฉพาะของลูกค้า
    คนนั้นด้วย (defense-in-depth เผื่อเลขบิลจริงที่ staff พิมพ์เองไปชนกับของลูกค้า
    อื่นโดยไม่ตั้งใจ — กันลบข้ามลูกค้า)"""
    db = get_supabase()
    q = db.table("transactions").select("id").eq("bill_no", bill_no)
    if customer_id:
        q = q.eq("customer_id", customer_id)
    rows = _retry(lambda: q.execute()).data
    txn_ids = [r["id"] for r in rows]
    for i in range(0, len(txn_ids), 50):
        _chunk = txn_ids[i:i + 50]
        _retry(lambda: db.table("partial_events").delete().in_("transaction_id", _chunk).execute())
    if txn_ids:
        _retry(lambda: db.table("transactions").delete().in_("id", txn_ids).execute())
    _clear_transaction_caches()
    return len(rows)


@st.cache_data(ttl=120)
def get_bill_list() -> list[str]:
    rows = (get_supabase().table("transactions")
            .select("bill_no").not_.is_("bill_no", "null")
            .order("bill_no", desc=True).execute().data)
    seen, result = set(), []
    for r in rows:
        bn = r.get("bill_no")
        if bn and bn not in seen:
            seen.add(bn); result.append(bn)
    return result


@st.cache_data(ttl=120)
def get_bill_summaries() -> list[dict]:
    """คืน [{bill_no, customer_name, total, date}] ต่อบิล เรียง desc"""
    rows = _retry(lambda: get_supabase().table("transactions")
                  .select("bill_no, total_amount, date, customers(name)")
                  .not_.is_("bill_no", "null")
                  .order("bill_no", desc=True).execute().data)
    seen: dict[str, dict] = {}
    for r in rows:
        bn = r.get("bill_no")
        if not bn:
            continue
        if bn not in seen:
            seen[bn] = {
                "bill_no":       bn,
                "customer_name": (r.get("customers") or {}).get("name", ""),
                "total":         0.0,
                "date":          (r.get("date") or "")[:10],
            }
        seen[bn]["total"] += float(r.get("total_amount") or 0)
    return list(seen.values())


@st.cache_data(ttl=60)
def get_customer_ledger(customer_id: str) -> list[dict]:
    """คืน timeline ของลูกค้า 1 คน เรียงตามวันที่
    แต่ละ row: {date, type, bill_no, product, qty_in, qty_out, amount, txn_id}
    type: สั่งซื้อ | รับของ | จ่ายเงิน
    """
    db = get_supabase()
    txns = _retry(lambda: db.table("transactions").select(
        "id, date, bill_no, origin_bill_no, product_id, product_name, qty, total_amount, pay_status, "
        "bill_status, points_per_unit, price_per_unit, initial_qty_received, notes, bill_opened_at"
    ).eq("customer_id", customer_id).order("date").execute().data)
    txn_ids = [t["id"] for t in txns]
    txn_map = {t["id"]: t for t in txns}

    # bill_open_events in batches — เหตุการณ์เปิดบิลจริงแต่ละครั้ง (event-based,
    # ไม่ใช่การ infer จาก bill_status เหมือนบิลเก่าที่แยกด้วย split_and_open_bill)
    all_open_events = []
    for _i in range(0, len(txn_ids), 50):
        _chunk = txn_ids[_i:_i + 50]
        all_open_events.extend(_retry(lambda: db.table("bill_open_events").select(
            "id, date, transaction_id, qty_opened, note"
        ).in_("transaction_id", _chunk).order("date").execute().data))

    # partial_events in batches
    all_events = []
    _batch = 50
    for _i in range(0, len(txn_ids), _batch):
        _chunk = txn_ids[_i:_i + _batch]
        _evts = _retry(lambda: db.table("partial_events").select(
            "id, date, transaction_id, qty_received, amount_paid, event_type, source, recipient_name"
        ).in_("transaction_id", _chunk).order("date").execute().data)
        all_events.extend(_evts)

    # shipments
    ships = _retry(lambda: db.table("shipments").select(
        "id, created_at, carrier, tracking_no, items, source, recipient_name"
    ).eq("customer_id", customer_id).order("created_at").execute().data)

    rows = []
    # order rows
    for t in txns:
        rows.append({
            "date":             t["date"][:10],
            "type":             "สั่งซื้อ",
            "bill_no":          t.get("bill_no") or "",
            "origin_bill_no":   t.get("origin_bill_no") or t.get("bill_no") or "",
            "product":          t["product_name"],
            "product_id":       t.get("product_id") or "",
            "qty_in":           t["qty"],
            "qty_out":          0,
            "amount":           0.0,
            "total_amount":     float(t.get("total_amount") or 0),
            "pay_status":       t.get("pay_status") or "",
            "bill_status":      t.get("bill_status") or "ยังไม่เปิดบิล",
            "pv":               float(t.get("points_per_unit") or 0) * int(t.get("qty") or 0),
            "initial_received": int(t.get("initial_qty_received") or 0),
            "notes":            t.get("notes", "") or "",
            "bill_opened_at":   (t.get("bill_opened_at") or "")[:10],
            "txn_id":           t["id"],
        })
    # bill-open event rows (เปิดบิลจริงแต่ละครั้ง — qty_opened ติดลบ = event
    # ยกเลิกเปิดบิล/undo ของ event ก่อนหน้า เก็บเป็นแถวประวัติแยกต่างหาก แบบเดียว
    # กับที่ partial_events ติดลบโชว์เป็น "แก้ไขรับ" — ไม่ซ่อน กันดูเหมือนไม่มีอะไร
    # เกิดขึ้นทั้งที่จริงมีการยกเลิกไปแล้ว)
    for oe in all_open_events:
        _qo = int(oe.get("qty_opened") or 0)
        if _qo == 0:
            continue
        txn = txn_map.get(oe["transaction_id"], {})
        rows.append({
            "date":         oe["date"][:10],
            "type":         "เปิดบิล" if _qo > 0 else "ยกเลิกเปิดบิล",
            "bill_no":      txn.get("bill_no") or "",
            "product":      txn.get("product_name", ""),
            "qty_in":       0,
            "qty_out":      0,
            "amount":       0.0,
            "qty_opened":   abs(_qo),
            "note":         oe.get("note") or "",
            "amount_opened": abs(_qo) * float(txn.get("price_per_unit") or 0),
            "pv_opened":    abs(_qo) * float(txn.get("points_per_unit") or 0),
            "txn_id":       oe["transaction_id"],
            "event_id":     oe["id"] + "-o",
        })
    # partial event rows
    for e in all_events:
        txn = txn_map.get(e["transaction_id"], {})
        _qr = float(e.get("qty_received") or 0)
        if _qr != 0:
            rows.append({
                "date":     e["date"][:10],
                "type":     "รับของ" if _qr > 0 else "แก้ไขรับ",
                "bill_no":  txn.get("bill_no") or "",
                "product":  txn.get("product_name", ""),
                "qty_in":   0,
                "qty_out":  int(_qr),
                "amount":   0.0,
                "txn_id":   e["transaction_id"],
                "event_id": e["id"] + "-r",
                "source":         e.get("source") or "",
                "recipient_name": e.get("recipient_name") or "",
            })
        if float(e.get("amount_paid") or 0) > 0:
            rows.append({
                "date":     e["date"][:10],
                "type":     "จ่ายเงิน",
                "bill_no":  txn.get("bill_no") or "",
                "product":  "",
                "qty_in":   0,
                "qty_out":  0,
                "amount":   float(e["amount_paid"]),
                "txn_id":   e["transaction_id"],
                "event_id": e["id"] + "-p",
            })
    # shipment rows
    for s in ships:
        _sdate    = (s.get("created_at") or "")[:10]
        _tracking = s.get("tracking_no") or "—"
        _carrier  = s.get("carrier") or ""
        _source   = s.get("source") or "ship"
        _items    = ", ".join(
            f"{it.get('name','?')}×{it.get('qty',0)}"
            for it in (s.get("items") or [])[:3]
        )
        _type_label = "📦 ส่งของ" if _source == "ship" else "💰 ส่งของ"
        rows.append({
            "date":    _sdate,
            "type":    _type_label,
            "bill_no": _tracking,
            "product": _items or _carrier,
            "qty_in":  0,
            "qty_out": 0,
            "amount":  0.0,
            "txn_id":  "",
            "recipient_name": s.get("recipient_name") or "",
        })
    rows.sort(key=lambda r: r["date"])
    return rows


def delete_partial_event(event_id: str) -> None:
    _retry(lambda: get_supabase().table("partial_events").delete().eq("id", event_id).execute())
    _clear_transaction_caches()
    bill_has_partial_events.clear()


def delete_payment_events(transaction_id: str) -> None:
    """ลบ partial_events ที่เป็นการจ่ายเงิน (amount_paid > 0) ของ transaction นี้"""
    db = get_supabase()
    evts = _retry(lambda: db.table("partial_events").select("id, amount_paid")
                  .eq("transaction_id", transaction_id).execute()).data
    ids_to_delete = [e["id"] for e in evts if float(e.get("amount_paid") or 0) > 0]
    for i in range(0, len(ids_to_delete), 50):
        _chunk = ids_to_delete[i:i + 50]
        _retry(lambda: db.table("partial_events").delete().in_("id", _chunk).execute())
    _clear_transaction_caches()
    bill_has_partial_events.clear()


@st.cache_data(ttl=60)
def get_pending_receipts_for_customer(customer_id: str) -> list[dict]:
    """คืน transactions ที่ยังค้างรับของ สำหรับลูกค้านี้ เรียงจากเก่าสุด
    [{id, product_id, ค้างรับ, bill_no, outstanding_amt, pay_status}]"""
    db = get_supabase()
    txns = (db.table("transactions")
            .select("id, product_id, qty, initial_qty_received, date, total_amount, pay_status, bill_no")
            .eq("customer_id", customer_id)
            .order("date")
            .execute().data)
    if not txns:
        return []
    txn_ids = [t["id"] for t in txns]
    qty_by_txn: dict[str, int] = defaultdict(int)
    paid_by_txn: dict[str, float] = defaultdict(float)
    for i in range(0, len(txn_ids), 50):
        chunk = txn_ids[i:i+50]
        evts = db.table("partial_events").select("transaction_id, qty_received, amount_paid").in_("transaction_id", chunk).execute().data
        for e in evts:
            qty_by_txn[e["transaction_id"]] += int(e.get("qty_received") or 0)
            paid_by_txn[e["transaction_id"]] += float(e.get("amount_paid") or 0)
    result = []
    for t in txns:
        bal = _compute_balance(t, paid_by_txn[t["id"]], qty_by_txn[t["id"]])
        outstanding_qty = bal["outstanding_qty"]
        if outstanding_qty > 0:
            outstanding_amt = max(0.0, bal["outstanding_amount"])
            result.append({
                "id":             t["id"],
                "product_id":     t["product_id"],
                "ค้างรับ":        outstanding_qty,
                "bill_no":        t.get("bill_no") or "",
                "outstanding_amt": outstanding_amt,
                "pay_status":     t["pay_status"],
            })
    return result


def delete_product(product_id: str) -> None:
    _retry(lambda: get_supabase().table("products").delete().eq("id", product_id).execute())


def delete_customer(customer_id: str) -> None:
    _retry(lambda: get_supabase().table("customers").delete().eq("id", customer_id).execute())


@st.cache_data(ttl=60)
def get_unbilled_pv_summary() -> dict:
    """สรุป PV และยอดเงินของ "ส่วนที่ยังไม่เปิดบิล" — นับเฉพาะจำนวนที่ยังไม่เปิด
    จริงต่อแถว (qty - Σbill_open_events.qty_opened) ไม่ใช่ทั้งแถว เพราะแถวที่
    เปิดบิลบางส่วนแล้ว (bill_status ยังเป็น "ยังไม่เปิดบิล" จนกว่าจะครบ) ต้องหัก
    ส่วนที่เปิดไปแล้วออกก่อน ไม่งั้นจะนับ PV/ยอดเงินเกินจริง"""
    db = get_supabase()
    try:
        rows = _retry(lambda: db.table("transactions").select(
            "id, qty, price_per_unit, points_per_unit"
        ).eq("bill_status", "ยังไม่เปิดบิล").execute().data)
    except Exception:
        # ลอง _retry แล้วยังไม่สำเร็จ — คืนศูนย์เพื่อไม่ให้หน้าแรก crash
        # (ค่า 0 อาจไม่ตรงความจริงถ้า query ล้มเหลวจริง ไม่ใช่แค่ไม่มีรายการ)
        return {"count": 0, "total_pv": 0.0, "total_amount": 0.0}

    if not rows:
        return {"count": 0, "total_pv": 0.0, "total_amount": 0.0}

    txn_ids = [r["id"] for r in rows]
    opened_sum: dict = defaultdict(int)
    for i in range(0, len(txn_ids), 50):
        chunk = txn_ids[i:i + 50]
        evts = _retry(lambda: db.table("bill_open_events").select(
            "transaction_id, qty_opened").in_("transaction_id", chunk).execute().data)
        for e in evts:
            opened_sum[e["transaction_id"]] += int(e["qty_opened"] or 0)

    total_pv = 0.0
    total_amount = 0.0
    count = 0
    for r in rows:
        unbilled_qty = max(0, int(r["qty"]) - max(0, opened_sum.get(r["id"], 0)))
        if unbilled_qty <= 0:
            continue
        total_pv += float(r["points_per_unit"]) * unbilled_qty
        total_amount += float(r["price_per_unit"]) * unbilled_qty
        count += 1
    return {"count": count, "total_pv": total_pv, "total_amount": total_amount}


@st.cache_data(ttl=60)
def get_today_transactions() -> list[dict]:
    """รายการวันนี้ (lightweight สำหรับ dashboard — ไม่ดึง partial_events)"""
    from datetime import date as _date
    today_str = _date.today().strftime("%Y-%m-%d")
    return _retry(lambda: get_supabase().table("transactions")
                  .select("bill_no, product_name, total_amount, bill_status, pay_status, customer_id, customers(name)")
                  .eq("date", today_str)
                  .order("bill_no", desc=True)
                  .execute().data) or []


@st.cache_data(ttl=300)
def get_all_transactions_df(customer_id: str = None, bill_no: str = None,
                             date_from: str = None, date_to: str = None) -> pd.DataFrame:
    """รายการทั้งหมด รวมที่เคลียร์แล้ว
    date_from/date_to (YYYY-MM-DD) กรองที่ระดับ query — ใช้เฉพาะหน้าที่ไม่ต้องการประวัติทั้งหมด
    (เช่นแท็บ "ประวัติทั้งหมด") ส่วนยอดค้าง/ledger ยังต้องเห็นย้อนหลังไม่จำกัดจึงไม่ส่งพารามิเตอร์นี้
    """
    db = get_supabase()

    q = db.table("transactions").select("*, customers(name)")
    if customer_id:
        q = q.eq("customer_id", customer_id)
    if bill_no:
        q = q.eq("bill_no", bill_no)
    if date_from:
        q = q.gte("date", date_from)
    if date_to:
        q = q.lte("date", date_to)
    txns = _retry(lambda: q.order("bill_no", desc=True, nullsfirst=False).order("date", desc=True).execute().data)

    _TXN_COLS = ["id","วันที่","ลูกค้า","รหัส","สินค้า","สั่ง","รับแล้ว","ยอดรวม",
                 "จ่ายแล้ว","ค้างจ่าย","ค้างรับ","สถานะบิล","สถานะจ่าย","หมายเหตุ",
                 "PV รวม","เลขที่บิล","เคลียร์แล้ว","last_payment_date","เลขอ้างอิงบิลหลัก",
                 "เปิดบิลแล้ว","ยังไม่เปิด"]
    if not txns:
        return pd.DataFrame(columns=_TXN_COLS)

    txn_ids = [t["id"] for t in txns]
    all_events: list = []
    all_open_events: list = []
    for _i in range(0, len(txn_ids), 50):
        _chunk = txn_ids[_i:_i+50]
        all_events += _retry(lambda: db.table("partial_events").select("*").in_("transaction_id", _chunk).execute().data)
        all_open_events += _retry(lambda: db.table("bill_open_events").select(
            "transaction_id,qty_opened").in_("transaction_id", _chunk).execute().data)

    events_by_txn: dict[str, list] = defaultdict(list)
    for e in all_events:
        events_by_txn[e["transaction_id"]].append(e)

    opened_sum_by_txn: dict[str, int] = defaultdict(int)
    for oe in all_open_events:
        opened_sum_by_txn[oe["transaction_id"]] += int(oe["qty_opened"] or 0)

    rows = []
    for t in txns:
        tid = t["id"]
        evts = events_by_txn[tid]

        _partial_paid = sum(float(e["amount_paid"]) for e in evts)
        _qty_received_sum = sum(e["qty_received"] for e in evts)
        bal = _compute_balance(t, _partial_paid, _qty_received_sum)
        total_paid = bal["total_paid"]
        total_received = bal["total_received"]
        outstanding_amount = bal["outstanding_amount"]
        outstanding_qty = bal["outstanding_qty"]

        # แถวเก่าที่เคยแยกด้วย split_and_open_bill (ก่อนมี bill_open_events) ไม่มี
        # event เปิดบิลผูกอยู่เลย แต่ bill_status ก็ถูกตั้งเป็น "เปิดบิลแล้ว" ไปแล้ว
        # ตอนแยก — ให้ยึด flag เดิมเป็นหลักถ้าเปิดครบแล้ว กันไม่ให้โชว์ "ยังไม่เปิด"
        # เต็มจำนวนทั้งที่จริงเปิดบิลไปแล้ว (bill_open_events sum จะเป็น 0 สำหรับแถวนี้)
        if t["bill_status"] == "เปิดบิลแล้ว":
            _opened_qty = int(t["qty"])
        else:
            _opened_qty = max(0, min(int(t["qty"]), opened_sum_by_txn.get(tid, 0)))
        _unopened_qty = max(0, int(t["qty"]) - _opened_qty)

        cleared = outstanding_amount <= 0.01 and outstanding_qty <= 0 and t["bill_status"] == "เปิดบิลแล้ว"
        customer_name = (t.get("customers") or {}).get("name", t["customer_id"])
        paid_dates = [e["date"][:10] for e in evts if float(e.get("amount_paid") or 0) > 0]
        rows.append({
            "id": tid,
            "วันที่": t["date"],
            "ลูกค้า": customer_name,
            "รหัส": t["product_id"],
            "สินค้า": t["product_name"],
            "สั่ง": t["qty"],
            "รับแล้ว": total_received,
            "ยอดรวม": float(t["total_amount"]),
            "จ่ายแล้ว": total_paid,
            "ค้างจ่าย": max(0.0, outstanding_amount),
            "ค้างรับ": max(0, outstanding_qty),
            "สถานะบิล": t["bill_status"],
            "สถานะจ่าย": t["pay_status"],
            "หมายเหตุ": t.get("notes", "") or "",
            "PV รวม": float(t["points_per_unit"]) * t["qty"],
            "เลขที่บิล": t.get("bill_no") or "",
            "เคลียร์แล้ว": cleared,
            "last_payment_date": max(paid_dates) if paid_dates else "",
            "เลขอ้างอิงบิลหลัก": t.get("origin_bill_no") or t.get("bill_no") or "",
            "เปิดบิลแล้ว": _opened_qty,
            "ยังไม่เปิด": _unopened_qty,
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=_TXN_COLS)


@st.cache_data(ttl=300)
def get_customer_ids_with_transactions() -> set:
    """customer_id ที่เคยมีรายการใน transactions อย่างน้อย 1 รายการ — ใช้กรอง dropdown
    ลูกค้าในหน้าประวัติ ไม่ต้องดึงทั้งตาราง transactions มาแค่เพื่อเช็คว่ามีข้อมูลมั้ย"""
    rows = _retry(lambda: get_supabase().table("transactions").select("customer_id").execute().data)
    return {r["customer_id"] for r in rows if r.get("customer_id")}


# ─── Finance ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_finance_entry(entry_date: str) -> dict | None:
    rows = get_supabase().table("finance_daily").select("*").eq("entry_date", entry_date).execute().data
    return rows[0] if rows else None


def upsert_finance_entry(data: dict) -> None:
    db = get_supabase()
    _retry(lambda: db.table("finance_daily").delete().eq("entry_date", data["entry_date"]).execute())
    _retry(lambda: db.table("finance_daily").insert(data).execute())
    get_finance_entry.clear()
    get_finance_df.clear()
    get_finance_summary.clear()


@st.cache_data(ttl=120)
def get_finance_df() -> pd.DataFrame:
    rows = get_supabase().table("finance_daily").select("*").order("entry_date").execute().data
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["adjustment"] = df.get("adjustment", pd.Series(0.0, index=df.index)).fillna(0.0)

    # ── Overpaid / ค้างโอน ──────────────────────────────────────────────────
    # net = Σ(โอน + BV + ปรับ) − Σ(ขาย + สมัคร)
    # BV = ยอดโอนให้บริษัทชนิดหนึ่ง (หักยอดค้างได้)
    # ค่าสมัคร = ค่าใช้จ่ายจ่ายทิ้ง ลด Overpaid แต่ไม่กระทบสต๊อก
    df["ต้องโอน"] = df["sales_amount"] + df["registration_fee"]
    df["net"] = (df["transfer_amount"] + df["bv_amount"] + df["adjustment"]).cumsum() - df["ต้องโอน"].cumsum()
    df["ยอดค้างโอน"] = df["net"].apply(lambda x: max(0.0, -x))
    df["เงินโอนเกิน"] = df["net"].apply(lambda x: max(0.0, x))

    # ── Stock สะสม ───────────────────────────────────────────────────────────
    # Actual_Stock = สต๊อกยกมา + Σ(PO) − Σ(ยอดขาย ÷ 1.07)
    # PO บวกสต๊อก, ยอดขาย (สินค้าเท่านั้น) หักสต๊อก ÷ 1.07 เพื่อถอด VAT
    # ค่าสมัครและ BV ไม่กระทบสต๊อก
    non_zero = df[df["stock_value"] > 0]["stock_value"]
    opening_stock = float(non_zero.iloc[0]) if not non_zero.empty else 0.0
    df["auto_stock"] = opening_stock + df["po_amount"].cumsum() - (df["sales_amount"] / 1.07).cumsum()

    # ── สิทธิ์สั่งของ ────────────────────────────────────────────────────────
    # สิทธิ์ = (1,100,000 + net) / 1.07 − Actual_Stock
    df["สิทธิ์สั่งของ"] = (1_100_000 + df["net"]) / 1.07 - df["auto_stock"]
    return df


@st.cache_data(ttl=120)
def get_finance_summary() -> dict:
    df = get_finance_df()
    if df.empty:
        return {"outstanding": 0.0, "overpaid": 0.0, "stock": 0.0, "credit": 0.0}
    last = df.iloc[-1]
    return {
        "outstanding": float(last["ยอดค้างโอน"]),
        "overpaid": float(last["เงินโอนเกิน"]),
        "stock": float(last["auto_stock"]),
        "credit": float(last["สิทธิ์สั่งของ"]),
    }


# ─── ค่าใช้จ่าย (ใบเสร็จรายรับ-รายจ่ายทั่วไป — น้ำมัน/อาหาร/ซุปเปอร์/เบ็ดเตล็ด ฯลฯ) ────────

@st.cache_data(ttl=60)
def get_expense_records_df(start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """คืนทุกแถว expense_records เรียงวันที่ล่าสุดก่อน กรองช่วงวันที่ถ้าระบุ (None = ทั้งหมด)"""
    q = get_supabase().table("expense_records").select("*")
    if start_date:
        q = q.gte("expense_date", start_date)
    if end_date:
        q = q.lte("expense_date", end_date)
    rows = _retry(lambda: q.order("expense_date", desc=True).execute()).data
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def upsert_expense_record(data: dict) -> None:
    """insert แถวใหม่เสมอ (v1 ยังไม่รองรับแก้ไขแถวเดิม — พิมพ์ผิดให้ลบแล้วเพิ่มใหม่)"""
    _retry(lambda: get_supabase().table("expense_records").insert(data).execute())
    get_expense_records_df.clear()


def delete_expense_record(expense_id: str) -> None:
    _retry(lambda: get_supabase().table("expense_records").delete().eq("id", expense_id).execute())
    get_expense_records_df.clear()


# ─── Commission / ใบหัก ณ ที่จ่าย (50 ทวิ) / เคลม VAT ────────────────────────

@st.cache_data(ttl=60)
def get_commission_records() -> pd.DataFrame:
    rows = (get_supabase().table("commission_records")
            .select("*").order("period", desc=True).execute().data)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


@st.cache_data(ttl=60)
def get_commission_record(period: str) -> dict | None:
    rows = get_supabase().table("commission_records").select("*").eq("period", period).execute().data
    return rows[0] if rows else None


def upsert_commission_record(data: dict) -> None:
    db = get_supabase()
    _retry(lambda: db.table("commission_records").delete().eq("period", data["period"]).execute())
    _retry(lambda: db.table("commission_records").insert(data).execute())
    get_commission_records.clear()
    get_commission_record.clear()


@st.cache_data(ttl=300)
def get_company_info() -> dict:
    rows = get_supabase().table("company_info").select("*").eq("id", 1).execute().data
    return rows[0] if rows else {}


def upsert_company_info(data: dict) -> None:
    data["id"] = 1
    _retry(lambda: get_supabase().table("company_info").upsert(data).execute())
    get_company_info.clear()


# ─── Box presets (ขนาดกล่อง — จัดการข้อมูล) ───────────────────────────────────

@st.cache_data(ttl=300)
def get_box_presets() -> list[dict]:
    return get_supabase().table("box_presets").select("*").order("name").execute().data


def replace_box_presets(presets: list[dict]) -> None:
    """แทนที่ preset ขนาดกล่องทั้งหมดด้วยรายการใหม่ (ลบของเดิมทั้งหมดแล้วใส่ใหม่) —
    ปลอดภัยที่จะ retry ทั้ง 2 call แยกกันแม้ id ของแถวใหม่สุ่มใหม่ทุกครั้ง เพราะ
    ลบทิ้งทั้งหมดก่อนเสมอ ผลลัพธ์สุดท้ายจึงเหมือนเดิมไม่ว่าจะรันกี่รอบ"""
    db = get_supabase()
    _retry(lambda: db.table("box_presets").delete().neq(
        "id", "00000000-0000-0000-0000-000000000000").execute())
    if presets:
        rows = [{
            "id":         str(uuid.uuid4()),
            "name":       p["name"],
            "length_cm":  p["length_cm"],
            "width_cm":   p["width_cm"],
            "height_cm":  p["height_cm"],
        } for p in presets]
        _retry(lambda: db.table("box_presets").insert(rows).execute())
    get_box_presets.clear()


# ─── Carrier zones (โซนพื้นที่พิเศษ/ห่างไกล — mirror ให้ gas_line_webhook.js อ่าน) ────
# flash_zones.py ยังคงเป็น hardcoded Python source of truth เหมือนเดิม (tests ต้อง
# import ได้ทันทีไม่พึ่งเน็ต) — ตาราง carrier_zones นี้เป็นแค่ mirror ให้ GAS (ซึ่งไม่มี
# access โค้ด Python) query สดๆ แทนการ hardcode ลิสต์แยกต่างหากที่เคย drift มาแล้ว
# ครั้งหนึ่ง ต้องรัน tools/sync_carrier_zones.py ทุกครั้งที่แก้โซนใน flash_zones.py

def sync_carrier_zones(rows: list[dict]) -> int:
    """แทนที่ carrier_zones ทั้งหมดด้วยรายการใหม่ (ลบของเดิมทั้งหมดแล้วใส่ใหม่) —
    เรียกจาก tools/sync_carrier_zones.py โดยส่ง rows ที่ derive จาก flash_zones.py
    เอง ไม่ใช้ตรงนี้ตัดสินใจว่าโซนไหนเป็นอะไร (flash_zones.py ยังเป็น source of
    truth เดียว). rows: [{"carrier","postcode","zone_type"}]"""
    db = get_supabase()
    _retry(lambda: db.table("carrier_zones").delete().neq(
        "id", "00000000-0000-0000-0000-000000000000").execute())
    for i in range(0, len(rows), 500):
        _chunk = rows[i:i + 500]
        _retry(lambda: db.table("carrier_zones").insert(_chunk).execute())
    return len(rows)


# ─── Stock ───────────────────────────────────────────────────────────────────

@st.cache_data(ttl=120)
def get_latest_stock_counts() -> dict:
    rows = get_supabase().table("stock_counts").select("*").order("count_date", desc=True).execute().data
    result = {}
    for row in rows:
        pid = row["product_id"]
        if pid not in result:
            result[pid] = row
    return result


def upsert_stock_count(data: dict) -> None:
    """Insert หรือ update stock count ตาม product_id + count_date"""
    db = get_supabase()
    _retry(lambda: db.table("stock_counts").delete()
           .eq("product_id", data["product_id"]).eq("count_date", data["count_date"]).execute())
    _retry(lambda: db.table("stock_counts").insert(data).execute())
    get_latest_stock_counts.clear()


def upsert_stock_counts_batch(rows: list[dict]) -> None:
    """บันทึกผลนับสต๊อกหลายสินค้าพร้อมกัน (วันเดียวกันทั้งหมด — 1 count_date ต่อ
    การบันทึก 1 ครั้งเสมอตาม UI) — batch แทนการลูป delete+insert ทีละแถว"""
    if not rows:
        return
    db = get_supabase()
    count_date = rows[0]["count_date"]
    pids = [r["product_id"] for r in rows]
    for i in range(0, len(pids), 50):
        _chunk = pids[i:i + 50]
        _retry(lambda: db.table("stock_counts").delete()
               .eq("count_date", count_date).in_("product_id", _chunk).execute())
    for i in range(0, len(rows), 50):
        _chunk = rows[i:i + 50]
        _retry(lambda: db.table("stock_counts").insert(_chunk).execute())
    get_latest_stock_counts.clear()


def insert_stock_count(data: dict) -> None:
    _retry(lambda: get_supabase().table("stock_counts").insert(data).execute())
    get_latest_stock_counts.clear()


@st.cache_data(ttl=120)
def get_stock_deposits() -> list[dict]:
    return get_supabase().table("stock_deposits").select("*, products(name)").eq("is_returned", False).execute().data


def insert_stock_deposit(data: dict) -> None:
    _retry(lambda: get_supabase().table("stock_deposits").insert(data).execute())
    get_stock_deposits.clear()


def return_stock_deposit(deposit_id: str) -> None:
    _retry(lambda: get_supabase().table("stock_deposits").update(
        {"is_returned": True}).eq("id", deposit_id).execute())
    get_stock_deposits.clear()


@st.cache_data(ttl=60)
def get_unbilled_received_qty_by_product() -> dict:
    """qty ที่ลูกค้ารับไปแล้วแต่ยังไม่เปิดบิล (เบิกของ) ต่อสินค้า — สุทธิด้วย
    bill_open_events ต่อแถว (received - opened, floor 0) เพราะแถวที่เปิดบิล
    บางส่วนแล้วยังอยู่ใน bill_status="ยังไม่เปิดบิล" จนกว่าจะครบ ถ้านับ received
    ทั้งแถวจะเกินจริง (ส่วนที่เปิดบิลไปแล้วไม่ควรนับเป็นเบิกของค้างอีก)"""
    db = get_supabase()
    txns = _retry(lambda: db.table("transactions").select(
        "id, product_id, initial_qty_received").eq("bill_status", "ยังไม่เปิดบิล").execute().data)
    if not txns:
        return {}
    txn_ids = [t["id"] for t in txns]
    events_by_txn = defaultdict(int)
    opened_by_txn = defaultdict(int)
    for _i in range(0, len(txn_ids), 50):
        _chunk = txn_ids[_i:_i+50]
        for e in _retry(lambda: db.table("partial_events").select("transaction_id, qty_received").in_("transaction_id", _chunk).execute().data):
            events_by_txn[e["transaction_id"]] += e["qty_received"]
        for oe in _retry(lambda: db.table("bill_open_events").select("transaction_id, qty_opened").in_("transaction_id", _chunk).execute().data):
            opened_by_txn[oe["transaction_id"]] += int(oe["qty_opened"] or 0)
    result = defaultdict(int)
    for t in txns:
        received = t["initial_qty_received"] + events_by_txn[t["id"]]
        unbilled_received = max(0, received - max(0, opened_by_txn[t["id"]]))
        if unbilled_received > 0:
            result[t["product_id"]] += unbilled_received
    return dict(result)


def get_deposit_qty_by_product() -> dict:
    deposits = get_stock_deposits()
    result = defaultdict(int)
    for d in deposits:
        result[d["product_id"]] += d["qty"]
    return dict(result)


@st.cache_data(ttl=60)
def get_billed_not_received_qty_by_product() -> dict:
    """qty ที่เปิดบิลแล้วแต่ลูกค้ายังไม่รับของ (ของยังอยู่ที่สาขา) — ต้องดูทุกแถว
    ไม่ใช่แค่แถวที่ bill_status="เปิดบิลแล้ว" เพราะแถวที่เปิดบิลบางส่วนแล้ว (ยังไม่
    ครบ qty) ก็มีส่วนที่ "เปิดบิลไปแล้ว" นับรวมได้เหมือนกัน แม้ตัว flag ทั้งแถวจะ
    ยังเป็น "ยังไม่เปิดบิล" อยู่ก็ตาม"""
    db = get_supabase()
    txns = _retry(lambda: db.table("transactions").select(
        "id, product_id, qty, initial_qty_received, bill_status").execute().data)
    if not txns:
        return {}
    txn_ids = [t["id"] for t in txns]
    events_by_txn: dict[str, int] = defaultdict(int)
    opened_by_txn: dict[str, int] = defaultdict(int)
    for _i in range(0, len(txn_ids), 50):
        _chunk = txn_ids[_i:_i + 50]
        _evts = _retry(lambda: db.table("partial_events").select("transaction_id, qty_received").in_("transaction_id", _chunk).execute().data)
        for e in _evts:
            events_by_txn[e["transaction_id"]] += e["qty_received"]
        _oevts = _retry(lambda: db.table("bill_open_events").select("transaction_id, qty_opened").in_("transaction_id", _chunk).execute().data)
        for oe in _oevts:
            opened_by_txn[oe["transaction_id"]] += int(oe["qty_opened"] or 0)
    result = defaultdict(int)
    for t in txns:
        if t["bill_status"] == "เปิดบิลแล้ว":
            opened = int(t["qty"])  # แถวเก่าที่แยกก่อนมี bill_open_events ก็นับเต็มแถว
        else:
            opened = max(0, min(int(t["qty"]), opened_by_txn[t["id"]]))
        if opened <= 0:
            continue
        received = t["initial_qty_received"] + events_by_txn[t["id"]]
        outstanding = opened - received
        if outstanding > 0:
            result[t["product_id"]] += outstanding
    return dict(result)


@st.cache_data(ttl=60)
def get_outstanding_df(customer_id: str = None) -> pd.DataFrame:
    """รายการที่ยังค้างชำระหรือค้างรับของ — derive จาก get_all_transactions_df()
    (cache เดียวกัน) แทนการ query Supabase ซ้ำ เพราะดึงข้อมูลชุดเดียวกันทุกประการ"""
    all_df = get_all_transactions_df(customer_id=customer_id)
    if all_df.empty:
        return pd.DataFrame()

    df = all_df[
        (all_df["ค้างจ่าย"] > 0.01) | (all_df["ค้างรับ"] > 0) | (all_df["สถานะบิล"] == "ยังไม่เปิดบิล")
    ].drop(columns=["เคลียร์แล้ว", "last_payment_date"], errors="ignore").copy()

    if df.empty:
        return pd.DataFrame()
    df.sort_values(["ลูกค้า", "เลขที่บิล", "วันที่"], ascending=[True, True, True],
                   inplace=True, na_position="last")
    return df.reset_index(drop=True)


_COD_PAY_STATUSES = ("COD", "COD จ่ายแล้ว")


@st.cache_data(ttl=60)
def get_cod_orders_df() -> pd.DataFrame:
    """รายการ COD ทั้งหมด (รอรับโอน + รับโอนแล้ว) พร้อมสถานะเปิดบิล — derive จาก
    get_all_transactions_df() (cache เดียวกันกับ get_outstanding_df ไม่ query ซ้ำ)
    ไม่ผูกกับตาราง shipments เลย เพราะ pay_status/bill_status อยู่ใน transactions
    โดยตรง — ใช้เช็คยอด COD ได้แม้ shipments จะไม่มีข้อมูล (เช่นตอนตารางว่าง)"""
    all_df = get_all_transactions_df()
    if all_df.empty:
        return pd.DataFrame()
    df = all_df[all_df["สถานะจ่าย"].isin(_COD_PAY_STATUSES)].drop(
        columns=["เคลียร์แล้ว", "last_payment_date"], errors="ignore").copy()
    if df.empty:
        return pd.DataFrame()
    df.sort_values(["วันที่", "ลูกค้า"], ascending=[False, True], inplace=True)
    return df.reset_index(drop=True)


# ─── E-commerce ──────────────────────────────────────────────────────────────

def _clear_ecommerce_caches() -> None:
    """เคลียร์ cache ของทุก read function ในโซน e-commerce/TikTok พร้อมกันทีเดียว —
    เรียกจากทุก mutation ในโซนนี้เสมอ (ดู CLAUDE.md: cache+clear ต้องอยู่คอมมิตเดียวกัน
    เสมอ ไม่งั้นจะโชว์เลขเก่าค้างหลังอัปโหลด/ซิงค์) รวมศูนย์ไว้จุดเดียวแทนเรียก .clear()
    กระจายทุกจุดเอง กันพลาดลืม clear บางตัว"""
    for _fn in (
        get_ecommerce_shops, get_ecommerce_import_coverage_df,
        get_ecommerce_unmatched_income_orders_df, get_ecommerce_product_margin_df,
        _ecommerce_order_costs, get_ecommerce_order_anomaly_df,
        get_ecommerce_order_profit_summary, get_ecommerce_monthly_summary,
        get_ecommerce_platform_totals_df, get_ecommerce_units_trend_df,
        get_ecommerce_shipping_overcharge_df, get_ecommerce_shipping_overcharge_monthly_df,
        get_ecommerce_problem_orders_df, get_ecommerce_sales_df, get_ecommerce_product_map,
        get_unmapped_ecommerce_items, get_tiktok_pending_sync_count,
        get_tiktok_unmatched_organic_orders, get_tiktok_affiliate_orders_df,
        get_tiktok_order_income_df,
    ):
        _fn.clear()


@st.cache_data(ttl=120)
def get_ecommerce_shops() -> list[dict]:
    return _retry(lambda: get_supabase().table("ecommerce_shops").select("*").order("shop_name").execute()).data


def upsert_ecommerce_shop(data: dict) -> None:
    # เดิม delete แล้ว insert แยก 2 คำสั่ง — ไม่ atomic ถ้าเน็ตหลุดกลางคันระหว่างสองคำสั่ง
    # ทะเบียนร้านหายไปเฉยๆ เปลี่ยนเป็น upsert จริงตัวเดียว (ecommerce_shops.id เป็น
    # PRIMARY KEY อยู่แล้วตาม ecommerce_setup.sql ใช้เป็น on_conflict ได้ตรงๆ)
    _retry(lambda: get_supabase().table("ecommerce_shops").upsert(data, on_conflict="id").execute())
    _clear_ecommerce_caches()


def delete_ecommerce_shop(shop_id: str) -> None:
    _retry(lambda: get_supabase().table("ecommerce_shops").delete().eq("id", shop_id).execute())
    _clear_ecommerce_caches()


def shop_has_ecommerce_data(shop_name: str, platform: str = "shopee") -> bool:
    """เช็คว่าร้านนี้มีข้อมูลขาย/รายได้ผูกอยู่แล้วหรือยัง (อ้างอิงด้วย shop_name ไม่ใช่ id) —
    ใช้เตือนก่อนลบร้านออกจากทะเบียน กันลบร้านที่มีข้อมูลจริงอยู่โดยไม่รู้ตัว"""
    db = get_supabase()
    sales = _retry(lambda: db.table("ecommerce_sales").select("order_sn").eq("shop_name", shop_name)
                    .eq("platform", platform).limit(1).execute()).data
    if sales:
        return True
    income = _retry(lambda: db.table("ecommerce_order_income").select("order_sn").eq("shop_name", shop_name)
                     .eq("platform", platform).limit(1).execute()).data
    return bool(income)


@st.cache_data(ttl=120)
def get_ecommerce_import_coverage_df(platform: str = "shopee") -> pd.DataFrame:
    """สรุปว่าแต่ละร้านมีข้อมูลนำเข้าครอบคลุมช่วงวันไหนแล้วบ้าง แยกรายงานคำสั่งซื้อ
    (Order.all) กับรายงานรายได้ (Income) คนละคอลัมน์ — เช็คก่อนอัปโหลดว่ายังขาด
    ช่วงไหน กันเผลออัปโหลดไม่ครอบคลุมออเดอร์ที่ต้องการ

    เพิ่มคอลัมน์ "ช่วงที่ Order.all ยังไม่ครอบคลุม": ปกติ Order.all จะครอบคลุมกว้างกว่า
    Income เสมอ (เงินโอนช้ากว่าวันสั่งซื้อ) ถ้า Income มีช่วงวันที่ Order.all ไม่ครอบคลุม
    (ก่อนหรือหลังช่วงของ Order.all) แปลว่ามีออเดอร์ที่ยืนยันยอดโอนแล้วแต่ไม่มีรายละเอียด
    สินค้า — สัญญาณว่าอัปโหลด Order.all ไม่ครบ ควรอัปโหลดเพิ่ม"""
    sales = _retry(lambda: get_supabase().table("ecommerce_sales").select("shop_name,sale_date")
                    .eq("platform", platform).execute()).data
    incomes = _retry(lambda: get_supabase().table("ecommerce_order_income").select("shop_name,transfer_date")
                      .eq("platform", platform).execute()).data

    by_shop_sales: dict[str, list[str]] = {}
    for r in sales:
        if r.get("sale_date"):
            by_shop_sales.setdefault(r["shop_name"], []).append(r["sale_date"])
    by_shop_income: dict[str, list[str]] = {}
    for r in incomes:
        if r.get("transfer_date"):
            by_shop_income.setdefault(r["shop_name"], []).append(r["transfer_date"])

    shop_names = sorted(set(by_shop_sales) | set(by_shop_income))
    rows = []
    for shop in shop_names:
        s_dates = by_shop_sales.get(shop, [])
        i_dates = by_shop_income.get(shop, [])
        s_min, s_max = (min(s_dates), max(s_dates)) if s_dates else (None, None)
        i_min, i_max = (min(i_dates), max(i_dates)) if i_dates else (None, None)

        gaps = []
        if i_dates and not s_dates:
            gaps.append(f"{i_min} ถึง {i_max}")
        elif i_dates and s_dates:
            if i_min < s_min:
                _before_end = (pd.to_datetime(s_min) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                gaps.append(f"{i_min} ถึง {_before_end}")
            if i_max > s_max:
                _after_start = (pd.to_datetime(s_max) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                gaps.append(f"{_after_start} ถึง {i_max}")

        rows.append({
            "ร้าน": shop,
            "รายงานคำสั่งซื้อ (Order.all)": f"{s_min} ถึง {s_max}" if s_dates else "ยังไม่มีข้อมูล",
            "รายงานรายได้ (Income)": f"{i_min} ถึง {i_max}" if i_dates else "ยังไม่มีข้อมูล",
            "ช่วงที่ Order.all ยังไม่ครอบคลุม": " | ".join(gaps) if gaps else "-",
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=120)
def get_ecommerce_unmatched_income_orders_df(platform: str = "shopee") -> pd.DataFrame:
    """หาออเดอร์ที่มีรายงานยอดโอน (Income) แล้วแต่ไม่มีแถวใน ecommerce_sales เลย (Order.all
    ยังไม่ครอบคลุมออเดอร์นี้ หรือหลุดหายตอนอัปโหลด) — เช็คทีละออเดอร์จริง แม่นยำกว่า
    get_ecommerce_import_coverage_df ที่เทียบแค่ช่วง min/max วันที่รวม เพราะ transfer_date
    อาจตกอยู่ในช่วงที่ Order.all "ดูเหมือน" ครอบคลุมแล้ว แต่ออเดอร์เฉพาะนั้นกลับหายไปจริงๆ"""
    incomes = _retry(lambda: get_supabase().table("ecommerce_order_income").select(
        "order_sn,shop_name,transfer_date,net_amount"
    ).eq("platform", platform).execute()).data
    if not incomes:
        return pd.DataFrame()
    income_sns = [r["order_sn"] for r in incomes]
    matched: set[str] = set()
    for i in range(0, len(income_sns), 50):
        chunk = income_sns[i:i + 50]
        rows = _retry(lambda _c=chunk: get_supabase().table("ecommerce_sales").select("order_sn").eq("platform", platform)
                       .in_("order_sn", _c).execute()).data
        matched.update(r["order_sn"] for r in rows)
    out = [
        {"เลขออเดอร์": r["order_sn"], "ร้าน": r["shop_name"], "วันที่โอนเงิน": r["transfer_date"],
         "ยอดโอนสุทธิ": r["net_amount"]}
        for r in incomes if r["order_sn"] not in matched
    ]
    df = pd.DataFrame(out)
    if not df.empty:
        df.sort_values("วันที่โอนเงิน", ascending=False, inplace=True)
    return df.reset_index(drop=True)


def check_ecommerce_shop_mismatch(order_sns: list[str], shop_name: str, platform: str = "shopee") -> dict[str, str]:
    """เช็คว่าออเดอร์เหล่านี้เคยถูกบันทึกไว้เป็นร้านอื่นมาก่อนหรือไม่ — ไฟล์ Order.all
    เองไม่มีชื่อร้านกำกับ (ต่างจาก Income ที่ดึงชื่อร้านจากหัวไฟล์ Shopee ได้เอง) ผู้ใช้
    ต้องเลือกร้านจาก dropdown เอง จึงเสี่ยงเลือกผิดร้านโดยไม่รู้ตัว คืน {order_sn: ชื่อร้านเดิม}
    เฉพาะที่ไม่ตรงกับ shop_name ที่กำลังจะนำเข้า"""
    if not order_sns:
        return {}
    db = get_supabase()
    mismatches: dict[str, str] = {}
    for i in range(0, len(order_sns), 50):
        chunk = order_sns[i:i + 50]
        for _table in ("ecommerce_sales", "ecommerce_order_income"):
            rows = _retry(lambda _t=_table, _c=chunk: db.table(_t).select("order_sn,shop_name").eq("platform", platform)
                           .in_("order_sn", _c).neq("shop_name", shop_name).execute()).data
            for r in rows:
                mismatches.setdefault(r["order_sn"], r["shop_name"])
    return mismatches


def _dedupe_by_key(rows: list[dict], key_fields: tuple[str, ...], sum_fields: tuple[str, ...]) -> list[dict]:
    """รวมแถวที่มี key ซ้ำกันภายในไฟล์เดียวกันก่อน upsert (เช่น สินค้าไม่มี SKU กำกับ
    หลายตัวเลือกในออเดอร์เดียวกัน fallback ไปใช้ชื่อสินค้าเหมือนกัน ชนเป็น key เดียว) —
    ไม่งั้น Postgres upsert จะ error 'ON CONFLICT DO UPDATE command cannot affect row a
    second time' เพราะมี conflict target ซ้ำในสเตทเมนต์เดียว"""
    merged: dict[tuple, dict] = {}
    for r in rows:
        key = tuple(r[f] for f in key_fields)
        if key in merged:
            for f in sum_fields:
                merged[key][f] = merged[key].get(f, 0) + (r.get(f) or 0)
        else:
            merged[key] = dict(r)
    return list(merged.values())


def upsert_ecommerce_sales(rows: list[dict]) -> None:
    """upsert ตาม (platform, order_sn, item_id_platform) — กันแถวซ้ำถ้าอัปโหลด
    ไฟล์ Order.all ซ้ำ/ช่วงวันที่ export ทับกัน"""
    if not rows:
        return
    rows = _dedupe_by_key(rows, ("platform", "order_sn", "item_id_platform"), ("qty", "item_price", "returned_qty"))
    db = get_supabase()
    for i in range(0, len(rows), 50):
        _chunk = rows[i:i + 50]
        _retry(lambda: db.table("ecommerce_sales").upsert(
            _chunk, on_conflict="platform,order_sn,item_id_platform"
        ).execute())
    _clear_ecommerce_caches()


def upsert_ecommerce_order_income(rows: list[dict]) -> None:
    """upsert ตาม order_sn — ยอดโอนสุทธิจากไฟล์ Income (คนละไฟล์กับ Order.all)"""
    if not rows:
        return
    rows = _dedupe_by_key(rows, ("order_sn",), ())
    db = get_supabase()
    for i in range(0, len(rows), 50):
        _chunk = rows[i:i + 50]
        _retry(lambda: db.table("ecommerce_order_income").upsert(
            _chunk, on_conflict="order_sn"
        ).execute())
    _clear_ecommerce_caches()


def apply_ecommerce_product_map(mappings: list[dict], platform: str = "shopee") -> None:
    """หลัง map SKU → product_id ใหม่ ผลักค่า product_id เข้า ecommerce_sales
    ที่ import มาก่อนแล้วด้วย (mappings: [{platform_item_id, product_id}])"""
    if not mappings:
        return
    db = get_supabase()
    for m in mappings:
        _retry(lambda _m=m: db.table("ecommerce_sales").update({"product_id": _m["product_id"]})
               .eq("platform", platform).eq("item_id_platform", _m["platform_item_id"]).execute())
    _clear_ecommerce_caches()


def allocate_ecommerce_order_income(platform: str = "shopee") -> int:
    """แบ่งยอดโอนสุทธิต่อออเดอร์ (ecommerce_order_income) ลงในแต่ละ SKU
    (ecommerce_sales.net_amount) ตามสัดส่วน item_price ของแต่ละ SKU ในออเดอร์
    เดียวกัน — แถวสุดท้ายรับเศษปัดเหลือ (หลักการเดียวกับแบ่งจ่ายบางส่วนใน
    บันทึกขาย) เรียกซ้ำได้ปลอดภัย (คำนวณใหม่ทับของเดิมทุกครั้ง)"""
    db = get_supabase()
    incomes = _retry(lambda: db.table("ecommerce_order_income").select("order_sn,net_amount")
                      .eq("platform", platform).execute()).data
    if not incomes:
        return 0
    income_map = {r["order_sn"]: float(r["net_amount"]) for r in incomes}
    order_sns = list(income_map.keys())
    updated = 0
    for i in range(0, len(order_sns), 50):
        chunk = order_sns[i:i + 50]
        sales = _retry(lambda _chunk=chunk: db.table("ecommerce_sales").select("id,order_sn,item_price")
                        .eq("platform", platform).in_("order_sn", _chunk).execute()).data
        by_order: dict[str, list[dict]] = {}
        for s in sales:
            by_order.setdefault(s["order_sn"], []).append(s)
        for order_sn, lines in by_order.items():
            net = income_map[order_sn]
            total_weight = sum(float(line_item["item_price"]) for line_item in lines) or 1
            remaining = net
            for idx, line_item in enumerate(lines):
                if idx == len(lines) - 1:
                    share = round(remaining, 2)
                else:
                    share = round(net * (float(line_item["item_price"]) / total_weight), 2)
                    remaining -= share
                _retry(lambda _id=line_item["id"], _share=share:
                       db.table("ecommerce_sales").update({"net_amount": _share}).eq("id", _id).execute())
                updated += 1
    _clear_ecommerce_caches()
    return updated


@st.cache_data(ttl=120)
def get_ecommerce_product_margin_df(
    start_date: str, end_date: str, platform: str = "shopee", shop_name: str = None,
) -> tuple[pd.DataFrame, int, str | None, str | None]:
    """สรุปต่อสินค้า (เฉพาะที่ map แล้ว): จำนวนขายผ่าน Shopee, ยอดเงินที่ได้รับจริง
    (เฉลี่ยจาก allocate_ecommerce_order_income), กำไร — เรียงขาดทุนมากสุดขึ้นก่อน
    (ไม่รวมสต็อกคงเหลือ/เงินจมในสต็อก เพราะเป็นสต็อกรวมทั้งร้าน ไม่ใช่เฉพาะที่ขาย
    ผ่าน Shopee — คนละสโคปกัน)

    นับเฉพาะออเดอร์ที่มีรายงาน Income มายืนยันยอดโอนแล้วเท่านั้น (ไม่งั้นออเดอร์ที่
    ยังไม่ได้อัปโหลด Income มา จะถูกหักต้นทุนเต็มแต่ได้ยอดรับ=0 ทำให้กำไรผิดเพี้ยน
    เป็นลบหลอกๆ ทั้งที่จริงยังไม่ได้เงินแค่นั้นเอง — ปกติออเดอร์จะส่งมาก่อน แล้ว Income
    จะตามมาทีหลังหลายอาทิตย์) — คืน (df, จำนวนชิ้นที่ยังรอยืนยันยอดเงิน ไม่รวมอยู่ใน df,
    sale_date เก่าสุด/ล่าสุดของออเดอร์ที่ยังค้าง หรือ None ถ้าไม่มีค้าง — บอกผู้ใช้ว่า
    ต้องไปโหลดรายงาน Income ของช่วงวันที่เท่าไหร่มาอัปโหลดเพิ่ม) ตัวคูณ units_per_pack
    ใช้กับ SKU ที่ map เป็นแพ็ครวม shop_name: ระบุเพื่อกรองดูเฉพาะร้านเดียว (None = รวมทุกร้าน)"""
    _income_q = get_supabase().table("ecommerce_order_income").select("order_sn").eq("platform", platform)
    if shop_name:
        _income_q = _income_q.eq("shop_name", shop_name)
    settled_sns = ecom_calc.settled_order_sns(_retry(lambda: _income_q.execute()).data)

    _sales_q = get_supabase().table("ecommerce_sales").select(
        "order_sn,product_id,item_id_platform,qty,returned_qty,net_amount,item_price,order_status,sale_date"
    ).eq("platform", platform).gte("sale_date", start_date).lte("sale_date", end_date) \
     .not_.is_("product_id", "null")
    if shop_name:
        _sales_q = _sales_q.eq("shop_name", shop_name)
    sales = _retry(lambda: _sales_q.execute()).data
    if not sales:
        return pd.DataFrame(), 0, None, None

    products = {p["id"]: p for p in get_products()}
    prod_map = get_ecommerce_product_map()

    agg, pending_qty, pending_since, pending_until = ecom_calc.aggregate_product_margin(sales, settled_sns, prod_map, platform)
    rows = ecom_calc.product_margin_rows(agg, products, platform)
    df = pd.DataFrame(rows)
    if not df.empty:
        df.sort_values("กำไรรวม", ascending=True, inplace=True)
    return df.reset_index(drop=True), int(pending_qty), pending_since, pending_until


@st.cache_data(ttl=120)
def get_ecommerce_product_margin_df_all(start_date: str, end_date: str) -> tuple[pd.DataFrame, int, str | None, str | None]:
    """เหมือน get_ecommerce_product_margin_df แต่รวมทุกแพลตฟอร์ม/ทุกร้านไว้ตารางเดียว
    (เพิ่มคอลัมน์ "แพลตฟอร์ม" — สินค้าเดียวกันที่ขายหลายแพลตฟอร์มจะมีหลายแถว แถวละ
    แพลตฟอร์ม เหมือนกับ loss_products_df ของ get_ecommerce_combined_summary) ใช้ตอน
    ผู้ใช้เลือกดู "ทั้งหมด (ทุกช่องทาง)" แทนการสลับดูทีละแพลตฟอร์ม pending_qty/
    pending_since/pending_until รวมข้ามแพลตฟอร์มเหมือนกัน"""
    platforms = sorted({s["platform"] for s in get_ecommerce_shops()})
    frames = []
    total_pending = 0
    pending_since = None
    pending_until = None
    for platform in platforms:
        df, pending, since, until = get_ecommerce_product_margin_df(start_date, end_date, platform=platform)
        total_pending += pending
        if since and (pending_since is None or since < pending_since):
            pending_since = since
        if until and (pending_until is None or until > pending_until):
            pending_until = until
        if not df.empty:
            df = df.rename(columns={f"ขายผ่าน {ecom_calc.PLATFORM_LABELS.get(platform, platform)} (ชิ้น)": "ขาย (ชิ้น)"})
            df.insert(0, "แพลตฟอร์ม", ecom_calc.PLATFORM_LABELS.get(platform, platform))
            frames.append(df)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not combined.empty:
        combined.sort_values("กำไรรวม", ascending=True, inplace=True)
        combined.reset_index(drop=True, inplace=True)
    return combined, total_pending, pending_since, pending_until


@st.cache_data(ttl=120)
def _ecommerce_order_costs(
    start_date: str, end_date: str, platform: str = "shopee", shop_name: str = None,
) -> tuple[dict, dict]:
    """เตรียมข้อมูลรายออเดอร์ (ยอดโอนสุทธิ + ต้นทุนรวม) ใช้ร่วมกันโดย
    get_ecommerce_order_anomaly_df และ get_ecommerce_order_profit_summary — นับเฉพาะ
    ออเดอร์ที่มี Income ยืนยันแล้วและทุก SKU ในออเดอร์ map ครบแล้ว (ถ้ามี SKU ไหนยังไม่
    map จะ flag unmapped ไว้เพราะคำนวณต้นทุนไม่ครบ) shop_name: กรองเฉพาะร้านเดียว
    (None = รวมทุกร้าน)"""
    _income_q = get_supabase().table("ecommerce_order_income") \
        .select("order_sn,shop_name,net_amount").eq("platform", platform)
    if shop_name:
        _income_q = _income_q.eq("shop_name", shop_name)
    incomes = {
        r["order_sn"]: (r["shop_name"], float(r.get("net_amount") or 0))
        for r in _retry(lambda: _income_q.execute()).data
    }
    if not incomes:
        return incomes, {}

    _sales_q = get_supabase().table("ecommerce_sales").select(
        "order_sn,product_id,item_id_platform,item_name,qty,returned_qty,order_status,sale_date"
    ).eq("platform", platform).gte("sale_date", start_date).lte("sale_date", end_date)
    if shop_name:
        _sales_q = _sales_q.eq("shop_name", shop_name)
    sales = _retry(lambda: _sales_q.execute()).data
    if not sales:
        return incomes, {}

    products = {p["id"]: p for p in get_products()}
    prod_map = get_ecommerce_product_map()

    by_order = ecom_calc.aggregate_order_costs(sales, incomes, prod_map, products, platform)
    return incomes, by_order


@st.cache_data(ttl=120)
def get_ecommerce_order_anomaly_df(
    start_date: str, end_date: str, platform: str = "shopee", warn_pct: float = 10.0, shop_name: str = None,
) -> pd.DataFrame:
    """หาออเดอร์ (ไม่ใช่สินค้ารวม) ที่กำไรติดลบ/ต่ำผิดปกติ พร้อมเลขที่ออเดอร์
    shop_name: กรองเฉพาะร้านเดียว (None = รวมทุกร้าน)"""
    incomes, by_order = _ecommerce_order_costs(start_date, end_date, platform, shop_name)
    if not incomes or not by_order:
        return pd.DataFrame()

    rows = ecom_calc.order_anomaly_rows(incomes, by_order, warn_pct)
    df = pd.DataFrame(rows)
    if not df.empty:
        df.sort_values("กำไร", ascending=True, inplace=True)
    return df.reset_index(drop=True)


@st.cache_data(ttl=120)
def get_ecommerce_order_profit_summary(
    start_date: str, end_date: str, platform: str = "shopee", shop_name: str = None,
) -> dict:
    """สรุปกำไรรวม/ขาดทุนรวมของช่วงเวลา โดยจัดกำไร-ขาดทุนเป็นรายออเดอร์ก่อนรวม (ไม่ใช่ net
    รายสินค้าทั้งช่วงแบบ get_ecommerce_product_margin_df) — รับประกันว่าตัวเลขนี้บวกกันได้
    ตรงๆ ข้ามช่วงเวลา (เช่น เดือน 6 + เดือน 7 = ช่วงรวม 6-7 พอดี) เพราะออเดอร์หนึ่งอยู่ในช่วง
    เดียวเสมอ ไม่ถูกแบ่งข้ามช่วง ต่างจากสินค้าที่กำไรเดือนหนึ่งแต่ขาดทุนอีกเดือนซึ่งพอ net รวม
    ทั้งช่วงแล้วตัวเลขจะไม่เท่ากับเอาแต่ละเดือนมาบวกกัน shop_name: กรองเฉพาะร้านเดียว
    (None = รวมทุกร้าน)"""
    incomes, by_order = _ecommerce_order_costs(start_date, end_date, platform, shop_name)
    return ecom_calc.order_profit_summary(incomes, by_order)


@st.cache_data(ttl=120)
def get_ecommerce_combined_summary(start_date: str, end_date: str, warn_pct: float = 0.0) -> dict:
    """รวมกำไร/ขาดทุน/PV ข้ามทุกแพลตฟอร์ม (Shopee/Lazada/TikTok ทุกร้าน) ในช่วงเวลาเดียว —
    ฟังก์ชัน get_ecommerce_* อื่นๆ กรองทีละ platform เดียวเสมอ อันนี้ใช้ตอบคำถามภาพรวม
    "ทั้งหมดขาดทุนหรือเปล่า / PV รวมเท่าไหร่" โดยไม่ต้องสลับแพลตฟอร์มเอง คืน
    {total_profit, total_loss, net, total_pv, pending_qty (รวมทุกแพลตฟอร์ม),
    pending_since/pending_until (sale_date เก่าสุด/ล่าสุดของออเดอร์ที่ยังไม่มี Income
    มายืนยัน ข้ามทุกแพลตฟอร์ม หรือ None ถ้าไม่มีค้าง — บอกผู้ใช้ว่าต้องไปโหลดรายงาน
    Income ของช่วงวันที่เท่าไหร่มาอัปโหลดเพิ่ม),
    loss_products_df (สินค้าที่ net ขาดทุนตลอดช่วง รวมทุกแพลตฟอร์ม — การ์ดสรุปแบบเดียวกับ
    "สินค้าที่ต้องรีบแก้" ในมุมมองรายแพลตฟอร์ม แต่ข้ามแพลตฟอร์ม — เรียงขาดทุนมากสุดขึ้นก่อน),
    loss_orders_df (ออเดอร์ขาดทุนจริง กำไร<0 ทุกแพลตฟอร์มรวมกัน มีคอลัมน์ "แพลตฟอร์ม" เพิ่ม
    เรียงขาดทุนมากสุดขึ้นก่อน — ไว้ไล่ดูรายละเอียดเป็นออเดอร์ๆ)}"""
    platforms = sorted({s["platform"] for s in get_ecommerce_shops()})
    total_profit = 0.0
    total_loss = 0.0
    total_pv = 0.0
    total_pending_qty = 0
    pending_since = None
    pending_until = None
    loss_order_frames = []
    loss_product_frames = []
    for platform in platforms:
        summary = get_ecommerce_order_profit_summary(start_date, end_date, platform=platform)
        total_profit += summary["total_profit"]
        total_loss += summary["total_loss"]

        margin_df, pending_qty, _platform_pending_since, _platform_pending_until = get_ecommerce_product_margin_df(start_date, end_date, platform=platform)
        total_pending_qty += pending_qty
        if _platform_pending_since and (pending_since is None or _platform_pending_since < pending_since):
            pending_since = _platform_pending_since
        if _platform_pending_until and (pending_until is None or _platform_pending_until > pending_until):
            pending_until = _platform_pending_until
        if not margin_df.empty:
            total_pv += float(margin_df["PV"].sum())
            loss_products = margin_df[margin_df["กำไรรวม"] < 0].copy()
            if not loss_products.empty:
                loss_products.rename(columns={f"ขายผ่าน {ecom_calc.PLATFORM_LABELS.get(platform, platform)} (ชิ้น)": "ขาย (ชิ้น)"}, inplace=True)
                loss_products.insert(0, "แพลตฟอร์ม", ecom_calc.PLATFORM_LABELS.get(platform, platform))
                loss_product_frames.append(loss_products)

        anomaly_df = get_ecommerce_order_anomaly_df(start_date, end_date, platform=platform, warn_pct=warn_pct)
        if not anomaly_df.empty:
            loss_df = anomaly_df[anomaly_df["กำไร"] < 0].copy()
            if not loss_df.empty:
                loss_df.insert(0, "แพลตฟอร์ม", ecom_calc.PLATFORM_LABELS.get(platform, platform))
                loss_order_frames.append(loss_df)

    loss_orders_df = pd.concat(loss_order_frames, ignore_index=True) if loss_order_frames else pd.DataFrame()
    if not loss_orders_df.empty:
        loss_orders_df.sort_values("กำไร", ascending=True, inplace=True)
        loss_orders_df.reset_index(drop=True, inplace=True)

    loss_products_df = pd.concat(loss_product_frames, ignore_index=True) if loss_product_frames else pd.DataFrame()
    if not loss_products_df.empty:
        loss_products_df.sort_values("กำไรรวม", ascending=True, inplace=True)
        loss_products_df.reset_index(drop=True, inplace=True)

    return {
        "total_profit": round(total_profit, 2),
        "total_loss": round(total_loss, 2),
        "net": round(total_profit + total_loss, 2),
        "total_pv": round(total_pv, 2),
        "pending_qty": total_pending_qty,
        "pending_since": pending_since,
        "pending_until": pending_until,
        "loss_products_df": loss_products_df,
        "loss_orders_df": loss_orders_df,
    }


@st.cache_data(ttl=120)
def get_ecommerce_monthly_summary(platform: str = "shopee", shop_name: str = None) -> pd.DataFrame:
    """สรุปยอดขาย/กำไร E-commerce รายเดือน (ตาม sale_date) — กำไร/ขาดทุนใช้สูตรเดียวกับ
    get_ecommerce_order_profit_summary (รายออเดอร์ ไม่ใช่ net รายสินค้า) จึงบวกข้ามเดือน
    ได้ตรงๆ shop_name: กรองเฉพาะร้านเดียว (None = รวมทุกร้าน) เรียงเดือนล่าสุดขึ้นก่อน"""
    _q = get_supabase().table("ecommerce_sales").select("sale_date,item_price").eq("platform", platform)
    if shop_name:
        _q = _q.eq("shop_name", shop_name)
    rows = _retry(lambda: _q.execute()).data
    if not rows:
        return pd.DataFrame()

    sales_by_month: dict[str, float] = {}
    for r in rows:
        d = r.get("sale_date")
        if not d:
            continue
        ym = d[:7]
        sales_by_month[ym] = sales_by_month.get(ym, 0.0) + float(r.get("item_price") or 0)

    out = []
    for ym in sorted(sales_by_month, reverse=True):
        period = pd.Period(ym, freq="M")
        start = period.start_time.strftime("%Y-%m-%d")
        end = period.end_time.strftime("%Y-%m-%d")
        summary = get_ecommerce_order_profit_summary(start, end, platform=platform, shop_name=shop_name)
        out.append({
            "เดือน": ym,
            "ยอดขาย": round(sales_by_month[ym], 2),
            "กำไรรวม": summary["total_profit"],
            "ขาดทุนรวม": summary["total_loss"],
            "สุทธิ": summary["net"],
        })
    return pd.DataFrame(out)


@st.cache_data(ttl=120)
def get_ecommerce_platform_totals_df(start_date: str, end_date: str) -> pd.DataFrame:
    """ยอดขาย/จำนวนชิ้นรวม แยกตามแพลตฟอร์ม (Shopee/Lazada/TikTok พร้อมกันทุกร้าน) สำหรับ
    ช่วงวันที่ที่กำหนด (ตาม sale_date) — ต่างจากฟังก์ชัน ecommerce อื่นๆ ที่กรองทีละ platform
    เดียวเสมอ อันนี้ตั้งใจให้เห็นสัดส่วนเทียบกันข้าม platform คืน [{platform, ยอดขาย, จำนวนชิ้น}, ...]"""
    rows = _retry(lambda: get_supabase().table("ecommerce_sales").select("platform,item_price,qty,returned_qty")
                  .gte("sale_date", start_date).lte("sale_date", end_date).execute()).data
    if not rows:
        return pd.DataFrame()

    agg: dict[str, dict] = {}
    for r in rows:
        plat = r.get("platform") or ""
        a = agg.setdefault(plat, {"sales": 0.0, "qty": 0.0})
        a["sales"] += float(r.get("item_price") or 0)
        a["qty"] += float(r.get("qty") or 0) - float(r.get("returned_qty") or 0)

    out = [{"platform": p, "ยอดขาย": round(a["sales"], 2), "จำนวนชิ้น": a["qty"]} for p, a in agg.items()]
    return pd.DataFrame(out)


@st.cache_data(ttl=120)
def get_ecommerce_units_trend_df(platform: str = "shopee", shop_name: str = None, months: int = 6) -> pd.DataFrame:
    """จำนวนชิ้นที่ขายรายเดือน (ตาม sale_date) ย้อนหลัง `months` เดือนล่าสุด — ใช้ทำกราฟเทรนด์
    จำนวนขาย เรียงเดือนเก่า→ใหม่ (ต่างจาก get_ecommerce_monthly_summary ที่เรียงใหม่→เก่าและ
    ดูยอดขาย/กำไรแทนจำนวนชิ้น) shop_name: กรองเฉพาะร้านเดียว (None = รวมทุกร้าน)"""
    _q = get_supabase().table("ecommerce_sales").select("sale_date,qty,returned_qty").eq("platform", platform)
    if shop_name:
        _q = _q.eq("shop_name", shop_name)
    rows = _retry(lambda: _q.execute()).data
    if not rows:
        return pd.DataFrame()

    qty_by_month: dict[str, float] = {}
    for r in rows:
        d = r.get("sale_date")
        if not d:
            continue
        ym = d[:7]
        qty_by_month[ym] = qty_by_month.get(ym, 0.0) + float(r.get("qty") or 0) - float(r.get("returned_qty") or 0)

    out = [{"เดือน": ym, "จำนวนชิ้น": qty_by_month[ym]} for ym in sorted(qty_by_month)]
    return pd.DataFrame(out[-months:]) if out else pd.DataFrame()


@st.cache_data(ttl=120)
def get_ecommerce_shipping_overcharge_df(
    start_date: str, end_date: str, platform: str = "shopee", overcharge_threshold: float = 0.0,
    shop_name: str = None,
) -> pd.DataFrame:
    """หาออเดอร์ที่ Shopee หักค่าส่งจากร้านเกินกว่าที่ประเมินไว้ล่วงหน้า —
    Shopee ประเมิน "ค่าส่งที่ผู้ซื้อจ่าย + Shopee ออกให้" ไว้ตอนสั่งซื้อ แต่พอ
    ขนส่งชั่งพัสดุจริงแล้วแพงกว่าที่ประเมิน ส่วนต่างจะถูกหักเพิ่มจากร้านเงียบๆ
    (ไม่ได้เทียบกับน้ำหนักสินค้าที่เราคำนวณเอง — ใช้ตัวเลขที่ Shopee รายงานมา
    ตรงๆ เท่านั้น จึงไม่ผิดเพี้ยนจากความแม่นยำของข้อมูลน้ำหนักในระบบเรา)
    shop_name: กรองเฉพาะร้านเดียว (None = รวมทุกร้าน)"""
    _q = get_supabase().table("ecommerce_order_income").select(
        "order_sn,shop_name,transfer_date,buyer_paid_shipping,shopee_subsidized_shipping,shipping_fee_charged"
    ).eq("platform", platform).gte("transfer_date", start_date).lte("transfer_date", end_date)
    if shop_name:
        _q = _q.eq("shop_name", shop_name)
    rows = _retry(lambda: _q.execute()).data
    if not rows:
        return pd.DataFrame()

    out = []
    for r in rows:
        extra = ecom_calc.shipping_overcharge_extra(r)
        if extra <= overcharge_threshold:
            continue
        out.append({
            "เลขออเดอร์": r["order_sn"],
            "ร้าน": r["shop_name"],
            "ค่าส่งที่ประเมินไว้ (ผู้ซื้อ+Shopee)": round(
                float(r.get("buyer_paid_shipping") or 0) + float(r.get("shopee_subsidized_shipping") or 0), 2),
            "ค่าส่งที่หักจริง": round(float(r.get("shipping_fee_charged") or 0), 2),
            "ส่วนต่างที่โดนหักเพิ่ม": round(extra, 2),
        })
    df = pd.DataFrame(out)
    if not df.empty:
        df.sort_values("ส่วนต่างที่โดนหักเพิ่ม", ascending=False, inplace=True)
    return df.reset_index(drop=True)


@st.cache_data(ttl=120)
def get_ecommerce_shipping_overcharge_monthly_df(
    start_date: str, end_date: str, platform: str = "shopee", overcharge_threshold: float = 0.0,
    shop_name: str = None,
) -> pd.DataFrame:
    """ผลรวมส่วนต่างค่าส่งที่โดนหักเกิน รายเดือน (ตาม transfer_date) — logic การหาส่วนต่างเดียวกับ
    get_ecommerce_shipping_overcharge_df แต่ sum รายเดือนแทนคืนรายออเดอร์ ใช้ทำกราฟแท่งรายเดือน
    เรียงเดือนเก่า→ใหม่ shop_name: กรองเฉพาะร้านเดียว (None = รวมทุกร้าน)"""
    _q = get_supabase().table("ecommerce_order_income").select(
        "transfer_date,buyer_paid_shipping,shopee_subsidized_shipping,shipping_fee_charged"
    ).eq("platform", platform).gte("transfer_date", start_date).lte("transfer_date", end_date)
    if shop_name:
        _q = _q.eq("shop_name", shop_name)
    rows = _retry(lambda: _q.execute()).data
    if not rows:
        return pd.DataFrame()

    by_month: dict[str, float] = {}
    for r in rows:
        extra = ecom_calc.shipping_overcharge_extra(r)
        if extra <= overcharge_threshold:
            continue
        d = r.get("transfer_date")
        if not d:
            continue
        ym = d[:7]
        by_month[ym] = by_month.get(ym, 0.0) + extra

    out = [{"เดือน": ym, "ส่วนต่างรวม": round(by_month[ym], 2)} for ym in sorted(by_month)]
    return pd.DataFrame(out)


@st.cache_data(ttl=120)
def get_ecommerce_problem_orders_df(platform: str = "shopee", shop_name: str = None) -> pd.DataFrame:
    """ออเดอร์ที่ตีกลับ/คืนสินค้า/ยกเลิก พร้อมเลขพัสดุ+ขนส่ง สำหรับตรวจสอบ
    shop_name: กรองเฉพาะร้านเดียว (None = รวมทุกร้าน)"""
    _q = get_supabase().table("ecommerce_sales").select(
        "order_sn,shop_name,sale_date,order_status,return_status,returned_qty,"
        "tracking_no,carrier_name,product_id,products(name)"
    ).eq("platform", platform)
    if shop_name:
        _q = _q.eq("shop_name", shop_name)
    rows = _retry(lambda: _q.execute()).data
    problem = [
        r for r in rows
        if r.get("return_status") or r.get("order_status") == "ยกเลิกแล้ว" or float(r.get("returned_qty") or 0) > 0
    ]
    if not problem:
        return pd.DataFrame()
    return pd.DataFrame([{
        "วันที่": r["sale_date"],
        "ร้าน": r["shop_name"],
        "เลขออเดอร์": r["order_sn"],
        "สินค้า": (r.get("products") or {}).get("name", r.get("product_id") or "ยังไม่ map"),
        "สถานะออเดอร์": r.get("order_status") or "",
        "สถานะคืนสินค้า": r.get("return_status") or "",
        "จำนวนที่คืน": r.get("returned_qty") or 0,
        # ออเดอร์ที่ "ยกเลิกแล้ว" คือยกเลิกก่อนขนส่งมารับพัสดุเสมอ (ต่างจากตีกลับ/คืนสินค้า
        # ที่ส่งไปแล้วจริงถึงมีเลขพัสดุ) — Shopee ยังใส่ tracking_no มาให้ในไฟล์แม้ยกเลิกก่อน
        # ส่งจริง โชว์แล้วเข้าใจผิดว่ามีพัสดุจริงเกิดขึ้น เลยไม่โชว์เลขพัสดุ/ขนส่งกรณีนี้
        "เลขพัสดุ": "" if r.get("order_status") == "ยกเลิกแล้ว" else (r.get("tracking_no") or ""),
        "ขนส่ง": "" if r.get("order_status") == "ยกเลิกแล้ว" else (r.get("carrier_name") or ""),
    } for r in problem]).sort_values("วันที่", ascending=False).reset_index(drop=True)


@st.cache_data(ttl=120)
def get_ecommerce_sales_df(start_date: str, end_date: str, platform: str = None, shop_name: str = None) -> pd.DataFrame:
    """platform: กรองเฉพาะแพลตฟอร์มเดียว (None = รวมทุกแพลตฟอร์ม) shop_name: กรองเฉพาะร้านเดียว (None = รวมทุกร้าน)"""
    _q = get_supabase().table("ecommerce_sales").select(
        "order_sn,sale_date,platform,shop_name,qty,item_price,net_amount,product_id,order_status,products(name)"
    ).gte("sale_date", start_date).lte("sale_date", end_date)
    if platform:
        _q = _q.eq("platform", platform)
    if shop_name:
        _q = _q.eq("shop_name", shop_name)
    rows = _retry(lambda: _q.order("sale_date", desc=True).execute()).data
    if not rows:
        return pd.DataFrame()

    order_sns = list({r["order_sn"] for r in rows})
    settled: set[str] = set()
    db = get_supabase()
    for i in range(0, len(order_sns), 50):
        chunk = order_sns[i:i + 50]
        inc = _retry(lambda _c=chunk: db.table("ecommerce_order_income").select("order_sn").in_("order_sn", _c).execute()).data
        settled |= ecom_calc.settled_order_sns(inc)

    return pd.DataFrame([{
        "วันที่": r["sale_date"],
        "ร้าน": r["shop_name"],
        "เลขออเดอร์": r["order_sn"],
        "สินค้า": (r.get("products") or {}).get("name", r.get("product_id") or "ยังไม่ map"),
        "จำนวน": r["qty"],
        "ยอด": float(r["item_price"] or 0),
        "ยอดเงินที่ได้รับจริง": float(r["net_amount"] or 0) if r["order_sn"] in settled else None,
        "สถานะออเดอร์": r.get("order_status") or "-",
        "สถานะการโอนเงิน": "✅ โอนแล้ว" if r["order_sn"] in settled else "⏳ รอยืนยัน",
    } for r in rows])


@st.cache_data(ttl=120)
def get_ecommerce_product_map() -> dict:
    """คืน dict {(platform, platform_item_id): {"product_id", "units_per_pack"}} —
    units_per_pack ใช้กับ SKU ที่เป็นแพ็ครวม (เช่น ยาสีฟัน 3 หลอด) ที่ 1 ออเดอร์
    จริงคือสินค้าเดี่ยวหลายชิ้น (ค่าเริ่มต้น 1 = ไม่ใช่แพ็ครวม)"""
    rows = _retry(lambda: get_supabase().table("ecommerce_product_map").select("*").execute()).data
    return {(r["platform"], r["platform_item_id"]): {
        "product_id": r["product_id"], "units_per_pack": float(r.get("units_per_pack") or 1),
    } for r in rows}


def upsert_ecommerce_product_map(rows: list[dict]) -> None:
    if not rows:
        return
    db = get_supabase()
    for i in range(0, len(rows), 50):
        _chunk = rows[i:i + 50]
        _retry(lambda: db.table("ecommerce_product_map").upsert(
            _chunk, on_conflict="platform,platform_item_id"
        ).execute())
    _clear_ecommerce_caches()


@st.cache_data(ttl=120)
def get_unmapped_ecommerce_items(platform: str = "shopee") -> list[dict]:
    rows = _retry(lambda: get_supabase().table("ecommerce_sales").select(
        "item_id_platform,shop_name,item_name"
    ).eq("platform", platform).is_("product_id", "null").execute()).data
    seen = set()
    result = []
    for r in rows:
        key = (r["item_id_platform"], r["shop_name"])
        if key not in seen:
            seen.add(key)
            result.append({
                "item_id": r["item_id_platform"], "shop_name": r["shop_name"],
                "item_name": r.get("item_name") or "",
            })
    return result


# ─── TikTok Affiliate Orders ───────────────────────────────────────────────────

def upsert_tiktok_affiliate_orders(rows: list[dict]) -> None:
    """upsert ตาม (order_id, sku_id) — กันแถวซ้ำถ้าอัปโหลดไฟล์ affiliate_orders ซ้ำ/ช่วง
    วันที่ export ทับกัน. สำคัญ: rows ต้องไม่มีคีย์ 'billed_in_system' เลย (ดู
    tiktok_affiliate_import.parse_affiliate_orders) ไม่งั้นค่าที่ผู้ใช้ติ๊กไว้แล้วจะโดน
    upsert ทับกลับเป็นค่า default ทุกครั้งที่อัปโหลดไฟล์ใหม่"""
    if not rows:
        return
    rows = _dedupe_by_key(rows, ("order_id", "sku_id"), ("qty", "payment_amount", "commission_payable_actual", "net_amount"))
    db = get_supabase()
    for i in range(0, len(rows), 50):
        _chunk = rows[i:i + 50]
        _retry(lambda: db.table("tiktok_affiliate_orders").upsert(
            _chunk, on_conflict="order_id,sku_id"
        ).execute())
    _clear_ecommerce_caches()


@st.cache_data(ttl=120)
def get_tiktok_affiliate_orders_df(shop_name: str = None) -> pd.DataFrame:
    q = get_supabase().table("tiktok_affiliate_orders").select("*")
    if shop_name:
        q = q.eq("shop_name", shop_name)
    data = _retry(lambda: q.order("order_created_at", desc=True).execute()).data
    return pd.DataFrame(data)


def set_tiktok_affiliate_billed(order_id: str, sku_id: str, billed: bool) -> None:
    """แก้เฉพาะ billed_in_system (+ billed_at) ทีละแถว — ใช้ upsert คีย์เดียวกับข้อมูลหลักแต่
    ส่งแค่ 2 คอลัมน์นี้ไป ไม่กระทบคอลัมน์อื่น (ต้องมีแถว order_id+sku_id นี้อยู่แล้วจากการนำเข้าไฟล์)
    billed_at stamp เวลาปัจจุบันตอนเปิดบิล เคลียร์เป็น null ตอนยกเลิก — ใช้ทำสรุป "เปิดบิลวันนี้"
    ที่ยืนอยู่ได้แม้รีเฟรช/ปิดหน้าไป ต่างจาก session_state ล้วนๆ ที่หายตอนปิดหน้า"""
    from datetime import datetime, timezone
    _retry(lambda: get_supabase().table("tiktok_affiliate_orders").update(
        {"billed_in_system": billed, "billed_at": datetime.now(timezone.utc).isoformat() if billed else None}
    ).eq("order_id", order_id).eq("sku_id", sku_id).execute())
    get_tiktok_affiliate_orders_df.clear()


def upsert_tiktok_order_income(rows: list[dict]) -> None:
    """upsert ตาม order_id — กันแถวซ้ำถ้าอัปโหลดไฟล์ income ซ้ำ/ช่วงวันที่ export ทับกัน"""
    if not rows:
        return
    rows = _dedupe_by_key(rows, ("order_id",), ())
    db = get_supabase()
    for i in range(0, len(rows), 50):
        _chunk = rows[i:i + 50]
        _retry(lambda: db.table("tiktok_order_income").upsert(
            _chunk, on_conflict="order_id"
        ).execute())
    _clear_ecommerce_caches()


@st.cache_data(ttl=120)
def get_tiktok_order_income_df(shop_name: str = None) -> pd.DataFrame:
    q = get_supabase().table("tiktok_order_income").select("*")
    if shop_name:
        q = q.eq("shop_name", shop_name)
    data = _retry(lambda: q.order("order_created_at", desc=True).execute()).data
    return pd.DataFrame(data)


@st.cache_data(ttl=120)
def get_tiktok_pending_sync_count(shop_name: str = None) -> int:
    """นับออเดอร์ TikTok ที่มีรายงานยอดขายสุทธิ (tiktok_order_income) แล้ว แต่ยังไม่ถูก
    ซิงค์เข้า ecommerce_order_income (platform='tiktok') — ต่างจาก Shopee/Lazada ที่เขียน
    เข้า ecommerce_sales/ecommerce_order_income ทันทีตอนอัปโหลด TikTok ต้องกด "ซิงค์เข้า
    ระบบกำไรสินค้า" แยกต่างหาก ค้างได้ง่ายถ้าลืมกด — ใช้เตือนผู้ใช้แทนการปล่อยให้ตัวเลข
    กำไรเงียบๆ ไม่ตรงกับที่อัปโหลดไว้จริง"""
    _income_df = get_tiktok_order_income_df(shop_name)
    if _income_df.empty:
        return 0
    all_ids = set(_income_df["order_id"].astype(str))
    q = get_supabase().table("ecommerce_order_income").select("order_sn").eq("platform", "tiktok")
    if shop_name:
        q = q.eq("shop_name", shop_name)
    synced_ids = {r["order_sn"] for r in _retry(lambda: q.execute()).data}
    return len(all_ids - synced_ids)


@st.cache_data(ttl=120)
def get_tiktok_unmatched_organic_orders(shop_name: str = None) -> pd.DataFrame:
    """ออเดอร์ TikTok organic (ไม่มีข้อมูลนายหน้า) ที่แกะ SKU จาก product_summary ไม่ได้ —
    ออเดอร์แบบนี้จะไม่ถูกนับเข้า ecommerce_sales/ecommerce_order_income เลยจนกว่าจะแก้ที่
    ต้นเหตุ (product_summary ไม่ตรง pattern คาดไว้) ต่างจาก get_tiktok_pending_sync_count
    ที่นับรวมทุกออเดอร์ที่ยังไม่ sync (แค่ยังไม่ได้กดปุ่ม) — อันนี้กดปุ่ม sync ไปก็ไม่หาย
    เพราะ parse ไม่ผ่านจริงๆ ใช้แสดงในแท็บ '⚠️ ตรวจสอบปัญหา' ให้ผู้ใช้เห็นว่าต้องเช็ค
    ไฟล์ต้นทางเอง ไม่ใช่แค่กดซิงค์ซ้ำ"""
    q = get_supabase().table("tiktok_order_income").select("order_id,product_summary,net_settlement,order_created_at")
    if shop_name:
        q = q.eq("shop_name", shop_name)
    income_rows = _retry(lambda: q.execute()).data
    if not income_rows:
        return pd.DataFrame()

    aq = get_supabase().table("tiktok_affiliate_orders").select("order_id")
    if shop_name:
        aq = aq.eq("shop_name", shop_name)
    aff_order_ids = {r["order_id"] for r in _retry(lambda: aq.execute()).data}

    rows = [{
        "วันที่": r.get("order_created_at"), "เลขออเดอร์": r["order_id"],
        "product_summary (ดิบ)": r.get("product_summary") or "",
        "ยอดสุทธิ": r.get("net_settlement") or 0,
    } for r in income_rows
        if r["order_id"] not in aff_order_ids
        and tiktok_income_import.parse_product_summary(r.get("product_summary")) is None]
    return pd.DataFrame(rows)


def sync_tiktok_to_ecommerce(shop_name: str) -> dict:
    """เชื่อมข้อมูล TikTok (tiktok_affiliate_orders + tiktok_order_income) เข้า pipeline
    กำไรจริงต่อสินค้าเดียวกับ Shopee/Lazada (ecommerce_sales/ecommerce_order_income,
    platform='tiktok') — ทำได้เพราะเช็คข้อมูลจริงแล้วว่าทุกออเดอร์ของร้านนี้มีแค่ 1 สินค้า
    ต่อออเดอร์ (ไม่มีออเดอร์ไหนซื้อหลายสินค้าพร้อมกันเลยสักออเดอร์) เลยไม่ต้องมีไฟล์ราคา
    ต่อ SKU แยกมาแบ่งสัดส่วนแบบ Shopee — ยอดสุทธิทั้งออเดอร์เป็นของสินค้าตัวเดียวนั้น
    100% ได้เลย ถ้าในอนาคตมีออเดอร์หลายสินค้าจริง แถวแบบนี้จะแตกเป็นหลาย sales_row ต่อ
    ออเดอร์ตามที่มีในตาราง affiliate อยู่แล้ว (ถูกต้อง) แต่ถ้าออเดอร์นั้นไม่มีข้อมูล
    affiliate เลย (organic + หลายสินค้า) จะจับได้แค่ SKU แรกจาก product_summary — เคส
    นี้ยังไม่เจอจริงในข้อมูลที่มี (ดู tests/ไม่ครอบ เป็น edge case ที่รู้ตัวไว้)"""
    income_rows = _retry(lambda: get_supabase().table("tiktok_order_income").select("*")
                          .eq("shop_name", shop_name).execute()).data
    if not income_rows:
        return {"synced_orders": 0, "sales_rows": 0, "unmatched": []}
    aff_rows = _retry(lambda: get_supabase().table("tiktok_affiliate_orders").select("*")
                       .eq("shop_name", shop_name).execute()).data
    # เช็คสินค้าที่ map ไว้แล้ว (จากรอบ sync ก่อนหน้า) ใส่ product_id ให้เลยตอน insert —
    # เดิมฟังก์ชันนี้ hardcode "product_id": None เสมอ ต่อให้ SKU เคย map แล้วก็ตาม
    # ทำให้แถวใหม่ทุกครั้งที่ sync ไม่ถูกนับกำไร/PV เลยจนกว่าจะมีคนไป "Map สินค้า" ซ้ำ
    # อีกรอบ — แต่ SKU ที่ map แล้วจะไม่โผล่ในรายการที่ต้อง map อีก เลยไม่มีทางกดซ้ำได้
    # เจอตอนช่วยผู้ใช้เช็คกำไร TikTok จริง 2026-09-05 (20 SKU map ไว้แล้วแต่กำไรออกมา 0)
    prod_map = get_ecommerce_product_map()
    aff_by_order: dict[str, list[dict]] = defaultdict(list)
    sku_name_lookup: dict[str, str] = {}
    for r in aff_rows:
        aff_by_order[r["order_id"]].append(r)
        if r.get("item_name") and r["sku_id"] not in sku_name_lookup:
            sku_name_lookup[r["sku_id"]] = r["item_name"]

    sales_rows = []
    income_out_rows = []
    unmatched = []  # ออเดอร์ organic ที่แกะ SKU จาก product_summary ไม่ได้ — ไม่ทิ้งเงียบ
    for inc in income_rows:
        oid = inc["order_id"]
        _sale_date = inc.get("order_created_at") or inc.get("order_paid_at")
        _aff = aff_by_order.get(oid)
        if _aff:
            # มีข้อมูลนายหน้า — ใช้ SKU/ราคา/ชื่อ/สถานะจากตรงนั้น (แม่นสุด)
            for a in _aff:
                sales_rows.append({
                    "id": str(uuid.uuid4()), "platform": "tiktok", "shop_name": shop_name,
                    "order_sn": oid, "sale_date": _sale_date,
                    "product_id": prod_map.get(("tiktok", a["sku_id"]), {}).get("product_id"),
                    "item_id_platform": a["sku_id"], "item_name": a.get("item_name") or a["sku_id"],
                    "qty": a.get("qty") or 1, "item_price": a.get("payment_amount") or 0,
                    "order_status": a.get("order_status"), "net_amount": 0,
                })
        else:
            # ออเดอร์ organic (ไม่ผ่านนายหน้า) — แกะ SKU จาก product_summary ของไฟล์
            # income เอง ("SKU_ID * qty;") ยืนยันจากข้อมูลจริงแล้วว่าออเดอร์แบบนี้มีแค่
            # 1 SKU เสมอ เลยให้ยอดทั้งออเดอร์ (gross_revenue) เป็นของ SKU นั้น 100% ได้
            _parsed = tiktok_income_import.parse_product_summary(inc.get("product_summary"))
            if not _parsed:
                # ข้ามออเดอร์นี้จริง (ไม่มี SKU ให้แม็ป ทั้ง ecommerce_sales และ
                # ecommerce_order_income จะไม่มีแถวนี้เลย) แต่เก็บไว้รายงานผู้ใช้แทนการ
                # ทิ้งเงียบแบบเดิม — ดู get_tiktok_unmatched_organic_orders()
                unmatched.append({"order_id": oid, "product_summary": inc.get("product_summary") or ""})
                continue
            _sku, _qty = _parsed
            # ชื่อสินค้า: หาจาก SKU เดียวกันในออเดอร์อื่นที่มีข้อมูลนายหน้า (SKU เดียวกัน
            # ย่อมเป็นสินค้าเดียวกันไม่ว่าจะออเดอร์ไหน) ก่อน — ไม่งั้นจะเห็นแค่รหัส SKU
            # ล้วนๆ ใน "Map สินค้า" หาไม่เจอว่าคือสินค้าอะไร (ผู้ใช้เจอปัญหานี้จริง)
            _item_name = sku_name_lookup.get(_sku) or f"TikTok SKU {_sku}"
            sales_rows.append({
                "id": str(uuid.uuid4()), "platform": "tiktok", "shop_name": shop_name,
                "order_sn": oid, "sale_date": _sale_date,
                "product_id": prod_map.get(("tiktok", _sku), {}).get("product_id"),
                "item_id_platform": _sku, "item_name": _item_name,
                "qty": _qty, "item_price": inc.get("gross_revenue") or 0,
                "order_status": inc.get("transaction_type"), "net_amount": 0,
            })
        income_out_rows.append({
            "order_sn": oid, "platform": "tiktok", "shop_name": shop_name,
            "net_amount": inc.get("net_settlement") or 0,
            "transfer_date": inc.get("order_paid_at") or inc.get("order_created_at"),
        })

    if not sales_rows:
        return {"synced_orders": 0, "sales_rows": 0, "unmatched": unmatched}

    # ให้แน่ใจว่ามีร้านนี้ลงทะเบียนใน ecommerce_shops แล้ว ไม่งั้น dropdown เลือกร้าน
    # ในแท็บ ยอดขาย/กำไร กับ Map สินค้า จะไม่เห็นร้านนี้เป็นตัวเลือก
    _existing = _retry(lambda: get_supabase().table("ecommerce_shops").select("id").eq(
        "platform", "tiktok").eq("shop_name", shop_name).limit(1).execute()).data
    if not _existing:
        upsert_ecommerce_shop({"id": str(uuid.uuid4()), "platform": "tiktok", "shop_name": shop_name, "shop_id": 0})

    upsert_ecommerce_sales(sales_rows)
    upsert_ecommerce_order_income(income_out_rows)
    _n_alloc = allocate_ecommerce_order_income("tiktok")
    return {
        "synced_orders": len(income_out_rows), "sales_rows": len(sales_rows),
        "allocated": _n_alloc, "unmatched": unmatched,
    }


def reconcile_tiktok_cancelled_orders(status_map: dict[str, str], shop_name: str) -> dict:
    """แก้ order_status ให้ตรงกับความจริงสำหรับออเดอร์ที่ "ยกเลิกแล้ว" จริง — status_map
    มาจาก tiktok_order_status_import.parse_order_statuses() (ไฟล์ "ทั้งหมด คำสั่งซื้อ")
    ซึ่งเป็นแหล่งเดียวที่บอกสถานะยกเลิกตรงๆ ("ยกเลิกแล้ว" เป๊ะ) ต่างจาก order_status ใน
    tiktok_affiliate_orders/tiktok_order_income.transaction_type ที่ใช้คำศัพท์อื่น
    ("ไม่มีสิทธิ์"/"ชำระแล้ว") ไม่เคยตรงกับ "ยกเลิกแล้ว" ที่ ecom_calc.aggregate_order_costs
    เช็คอยู่เลย ทำให้ออเดอร์ที่ยกเลิกจริง (พัสดุ COD ตีกลับ) ไม่เคยถูกตัดออกจากต้นทุน

    แก้แค่ 2 จุดที่จำเป็น (ไม่แตะ schema ใหม่เลย): (1) tiktok_affiliate_orders.order_status
    สำหรับออเดอร์ที่มีข้อมูลนายหน้า (2) tiktok_order_income.transaction_type สำหรับ
    ออเดอร์ organic (ไม่มีข้อมูลนายหน้า) — ทั้งสองจุดนี้คือ field ที่ sync_tiktok_to_ecommerce()
    ใช้กำหนด order_status ของ sales_rows อยู่แล้ว แก้ตรงนี้แล้วเรียก sync ซ้ำ ผลจะไหลลง
    ไป ecommerce_sales.order_status ถูกต้องเอง — ต้องรันซ้ำทุกครั้งที่อัปโหลดไฟล์
    affiliate_orders ใหม่ทับ (upsert จะดึงค่า order_status เดิมจากไฟล์นั้นกลับมาทับอีก)"""
    cancelled_ids = {oid for oid, status in status_map.items() if status == "ยกเลิกแล้ว"}
    if not cancelled_ids:
        return {"affiliate_fixed": 0, "income_fixed": 0}

    db = get_supabase()
    aff_rows = _retry(lambda: db.table("tiktok_affiliate_orders").select("order_id,sku_id,order_status")
                       .eq("shop_name", shop_name).execute()).data
    to_fix_aff = [r for r in aff_rows if r["order_id"] in cancelled_ids and r["order_status"] != "ยกเลิกแล้ว"]
    for r in to_fix_aff:
        _retry(lambda _r=r: db.table("tiktok_affiliate_orders").update({"order_status": "ยกเลิกแล้ว"})
               .eq("order_id", _r["order_id"]).eq("sku_id", _r["sku_id"]).execute())

    aff_order_ids = {r["order_id"] for r in aff_rows}
    income_rows = _retry(lambda: db.table("tiktok_order_income").select("order_id,transaction_type")
                          .eq("shop_name", shop_name).execute()).data
    to_fix_inc = [r for r in income_rows if r["order_id"] in cancelled_ids and r["order_id"] not in aff_order_ids
                  and r["transaction_type"] != "ยกเลิกแล้ว"]
    for r in to_fix_inc:
        _retry(lambda _r=r: db.table("tiktok_order_income").update({"transaction_type": "ยกเลิกแล้ว"})
               .eq("order_id", _r["order_id"]).execute())

    _clear_ecommerce_caches()
    return {"affiliate_fixed": len(to_fix_aff), "income_fixed": len(to_fix_inc)}


# ─── Shipments ────────────────────────────────────────────────────────────────

def create_shipment(data: dict) -> None:
    _retry(lambda: get_supabase().table("shipments").insert(data).execute())
    get_shipments.clear()
    get_customer_ledger.clear()


@st.cache_data(ttl=60)
def get_shipments(customer_id: str = None) -> list[dict]:
    q = get_supabase().table("shipments").select("*, customers(name)")
    if customer_id:
        q = q.eq("customer_id", customer_id)
    return q.order("created_at", desc=True).execute().data


def update_shipment_tracking(shipment_id: str, tracking_no: str, carrier: str = None) -> None:
    _upd = {"tracking_no": tracking_no}
    if carrier:
        _upd["carrier"] = carrier
    _retry(lambda: get_supabase().table("shipments").update(
        _upd
    ).eq("id", shipment_id).execute())
    get_shipments.clear()
    get_customer_ledger.clear()


def delete_shipment(shipment_id: str) -> None:
    _retry(lambda: get_supabase().table("shipments").delete().eq("id", shipment_id).execute())
    get_shipments.clear()
    get_customer_ledger.clear()


def count_shipped_by_date_range(date_from: str, date_to: str) -> int:
    """นับ shipments ที่จัดส่งสำเร็จในช่วง date_from..date_to (YYYY-MM-DD, Bangkok time)"""
    res = (get_supabase().table("shipments")
           .select("id")
           .eq("delivery_status", "จัดส่งแล้ว")
           .gte("created_at", f"{date_from}T00:00:00+07:00")
           .lte("created_at", f"{date_to}T23:59:59+07:00")
           .execute())
    return len(res.data) if res.data else 0


def delete_shipped_by_date_range(date_from: str, date_to: str) -> int:
    """ลบ shipments ที่จัดส่งสำเร็จในช่วงวันที่กำหนด คืนจำนวนแถวที่ลบ"""
    q = (get_supabase().table("shipments")
         .delete()
         .eq("delivery_status", "จัดส่งแล้ว")
         .gte("created_at", f"{date_from}T00:00:00+07:00")
         .lte("created_at", f"{date_to}T23:59:59+07:00"))
    res = _retry(lambda: q.execute())
    get_shipments.clear()
    get_customer_ledger.clear()
    return len(res.data) if res.data else 0


def mark_cod_transferred(tracking_nos: list[str]) -> None:
    """บันทึกวันที่ COD โอนแล้วสำหรับ tracking numbers ที่ระบุ"""
    if not tracking_nos:
        return
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    db = get_supabase()
    _retry(lambda: db.table("shipments")
           .update({"cod_transferred_at": now})
           .in_("tracking_no", tracking_nos)
           .is_("cod_transferred_at", "null")
           .execute())


def mark_cod_paid(tracking_no_to_date: dict[str, str]) -> int:
    """เมื่อ COD ของ tracking ใน tracking_no_to_date ถูกโอนเข้าระบบแล้ว
    mark เฉพาะ transactions ที่ผูกกับ shipment นั้น (จับคู่ผ่าน product_id ใน items)
    ถ้า shipment ไม่มีข้อมูล items → fallback mark ทุก COD ของลูกค้า (legacy)
    คืนจำนวน transaction ที่ mark

    ดึง COD transactions ของทุกลูกค้าที่เกี่ยวข้องครั้งเดียว (แทน query ต่อ
    shipment) แล้ว insert/update เป็น batch เดียวตอนท้าย (แทนทีละแถวในลูป) —
    ลด round-trip จาก O(shipments × transactions) เหลือ O(1) ต่อ 50 แถว"""
    if not tracking_no_to_date:
        return 0
    db = get_supabase()
    ships = (db.table("shipments")
             .select("customer_id, tracking_no, items")
             .in_("tracking_no", list(tracking_no_to_date.keys()))
             .execute().data) or []
    ships = [s for s in ships if s.get("customer_id")]
    if not ships:
        return 0

    cust_ids = list({s["customer_id"] for s in ships})
    all_cod_txns = []
    for i in range(0, len(cust_ids), 50):
        chunk = cust_ids[i:i + 50]
        all_cod_txns += (db.table("transactions")
                          .select("id, customer_id, total_amount, product_id")
                          .in_("customer_id", chunk)
                          .eq("pay_status", "COD")
                          .execute().data) or []
    txns_by_cust: dict[str, list] = defaultdict(list)
    for t in all_cod_txns:
        txns_by_cust[t["customer_id"]].append(t)

    pe_rows = []
    txn_ids_to_mark = []
    for s in ships:
        cust_id = s["customer_id"]
        tn      = s.get("tracking_no")
        transfer_date = (tracking_no_to_date.get(tn) or "")[:10]
        if not transfer_date:
            from datetime import datetime, timezone
            transfer_date = datetime.now(timezone.utc).date().isoformat()

        all_txns = txns_by_cust.get(cust_id, [])
        # จับคู่ด้วย product_id จาก items ของ shipment นี้
        ship_pids = {it.get("product_id") for it in (s.get("items") or [])
                     if it.get("product_id")}
        if ship_pids:
            txns = [t for t in all_txns if t.get("product_id") in ship_pids]
            if not txns:
                # product_id ใน items ไม่ match (ข้อมูลเก่า/ไม่สมบูรณ์) → fallback
                txns = all_txns
        else:
            # shipment เก่าไม่มี items data → fallback เหมือนเดิม
            txns = all_txns

        for t in txns:
            pe_rows.append({
                "id":             str(uuid.uuid4()),
                "date":           transfer_date,
                "transaction_id": t["id"],
                "qty_received":   0,
                "amount_paid":    float(t["total_amount"]),
                "event_type":     "จ่ายเงิน",
                "notes":          f"COD โอนจาก iShip ({tn})",
            })
            txn_ids_to_mark.append(t["id"])

    count = len(txn_ids_to_mark)
    # pe_rows ผูก id คงที่มาแล้วตั้งแต่ลูปด้านบน — retry แต่ละ chunk แยกกันจึง
    # idempotent (ไม่ได้สุ่ม id ใหม่ตอน retry)
    for i in range(0, len(pe_rows), 50):
        _chunk = pe_rows[i:i + 50]
        _retry(lambda: db.table("partial_events").insert(_chunk).execute())
    for i in range(0, len(txn_ids_to_mark), 50):
        _chunk = txn_ids_to_mark[i:i + 50]
        _retry(lambda: db.table("transactions").update(
            {"pay_status": "COD จ่ายแล้ว"}).in_("id", _chunk).execute())
    if count:
        _clear_transaction_caches()
    return count


def get_pending_cod_tracking() -> list[str]:
    """คืน tracking_no ที่ยังไม่ได้รับโอน COD"""
    rows = (get_supabase().table("shipments")
            .select("tracking_no")
            .gt("cod_amount", 0)
            .is_("cod_transferred_at", "null")
            .not_.is_("tracking_no", "null")
            .neq("tracking_no", "")
            .execute().data)
    return [r["tracking_no"] for r in rows if r.get("tracking_no")]


def mark_actual_shipping_costs(tracking_no_to_cost: dict[str, float]) -> int:
    """บันทึก actual_shipping_cost (ยอดที่ iShip คิดจริง จาก get_shipping_report) ลง shipments
    ให้ถาวร แทนที่จะเก็บแค่ session_state — group ตามค่าเดียวกันแล้ว batch .in_() เหมือน
    update_delivery_statuses คืนจำนวนที่อัปเดต"""
    if not tracking_no_to_cost:
        return 0
    db = get_supabase()
    by_cost: dict[float, list[str]] = defaultdict(list)
    for track_no, cost in tracking_no_to_cost.items():
        if track_no and cost:
            by_cost[float(cost)].append(track_no)
    count = 0
    for cost, track_nos in by_cost.items():
        for i in range(0, len(track_nos), 50):
            chunk = track_nos[i:i + 50]
            _retry(lambda: db.table("shipments").update(
                {"actual_shipping_cost": cost}).in_("tracking_no", chunk).execute())
            count += len(chunk)
    if count:
        get_shipments.clear()
    return count


_DELIVERY_TERMINAL = {"จัดส่งแล้ว", "ตีกลับ", "ยกเลิก"}

def update_delivery_statuses(statuses: dict) -> int:
    """อัปเดต delivery_status ใน shipments, คืนจำนวนที่อัปเดต — group tracking
    number ตามค่า status เดียวกันแล้ว batch ด้วย .in_() แทนอัปเดตทีละแถว"""
    db = get_supabase()
    by_status: dict[str, list[str]] = defaultdict(list)
    for track_no, status in statuses.items():
        if track_no:
            by_status[status].append(track_no)
    count = 0
    for status, track_nos in by_status.items():
        for i in range(0, len(track_nos), 50):
            chunk = track_nos[i:i + 50]
            _retry(lambda: db.table("shipments").update(
                {"delivery_status": status}).in_("tracking_no", chunk).execute())
            count += len(chunk)
    return count


def get_pending_delivery_tracking() -> list[str]:
    """คืน tracking_no ที่ยังไม่จัดส่งสำเร็จ (delivery_status IS NULL หรือไม่ใช่ terminal)"""
    rows = (get_supabase().table("shipments")
            .select("tracking_no, delivery_status")
            .not_.is_("tracking_no", "null")
            .neq("tracking_no", "")
            .execute().data)
    return [r["tracking_no"] for r in rows
            if r.get("delivery_status") not in _DELIVERY_TERMINAL]


def get_customer_line_user_id(customer_id: str) -> str:
    """คืน line_user_id ของลูกค้า หรือ '' ถ้าไม่มี"""
    if not customer_id:
        return ""
    rows = get_supabase().table("customers").select("line_user_id").eq("id", customer_id).execute().data
    return (rows[0].get("line_user_id") or "") if rows else ""


def get_customer_line_ids(customer_id: str) -> tuple[str, str]:
    """คืน (line_user_id, group_id) ของลูกค้า"""
    if not customer_id:
        return "", ""
    rows = get_supabase().table("customers").select("line_user_id,group_id").eq("id", customer_id).execute().data
    if not rows:
        return "", ""
    return (rows[0].get("line_user_id") or ""), (rows[0].get("group_id") or "")


def mark_line_notified(shipment_id: str) -> None:
    """บันทึกวันที่ส่ง LINE notification แล้ว"""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    _retry(lambda: get_supabase().table("shipments").update(
        {"line_notified_at": now}).eq("id", shipment_id).execute())
