import os
import time
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client, Client
import pandas as pd
from collections import defaultdict
from math import floor
import uuid


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
    if data.get("phone"):
        db.table("customer_addresses").delete().eq("phone", data["phone"].strip()).execute()
    db.table("customer_addresses").insert(data).execute()
    _all_customer_addresses.clear()


def delete_customer_address(address_id: str) -> None:
    get_supabase().table("customer_addresses").delete().eq("id", address_id).execute()
    _all_customer_addresses.clear()


def upsert_product(data: dict) -> None:
    get_supabase().table("products").upsert(data).execute()
    get_products.clear()


def upsert_customer(data: dict) -> None:
    get_supabase().table("customers").upsert(data).execute()
    get_customers.clear()


def update_customer_address(customer_id: str, data: dict) -> None:
    """อัปเดตที่อยู่จัดส่งของลูกค้า (recipient_name, phone, address, postal_code)"""
    get_supabase().table("customers").update(data).eq("id", customer_id).execute()



# ─── Transactions ────────────────────────────────────────────────────────────

def _clear_transaction_caches() -> None:
    get_all_transactions_df.clear()
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
    get_supabase().table("transactions").insert(data).execute()
    _clear_transaction_caches()


def insert_transactions_batch(rows: list[dict]) -> None:
    if rows:
        get_supabase().table("transactions").insert(rows).execute()
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


def insert_partial_event(data: dict) -> None:
    get_supabase().table("partial_events").insert(data).execute()
    get_all_transactions_df.clear()
    get_outstanding_df.clear()
    get_unbilled_pv_summary.clear()
    bill_has_partial_events.clear()
    get_customer_ledger.clear()
    get_pending_receipts_for_customer.clear()
    get_unbilled_received_qty_by_product.clear()
    get_billed_not_received_qty_by_product.clear()
    get_today_transactions.clear()


def split_and_open_bill(transaction_id: str, qty_to_bill: int) -> None:
    """แยกรายการ: เปิดบิล qty_to_bill ชิ้น แล้วสร้างรายการใหม่สำหรับที่เหลือ"""
    db = get_supabase()
    txn = db.table("transactions").select("*").eq("id", transaction_id).single().execute().data
    qty_remaining = txn["qty"] - qty_to_bill
    price = float(txn["price_per_unit"])
    pv = float(txn["points_per_unit"])

    db.table("transactions").update({
        "qty": qty_to_bill,
        "total_amount": price * qty_to_bill,
        "bill_status": "เปิดบิลแล้ว",
        "initial_qty_received": min(txn["initial_qty_received"], qty_to_bill),
    }).eq("id", transaction_id).execute()

    if qty_remaining > 0:
        db.table("transactions").insert({
            "id": str(uuid.uuid4()),
            "date": txn["date"],
            "customer_id": txn["customer_id"],
            "product_id": txn["product_id"],
            "product_name": txn["product_name"],
            "qty": qty_remaining,
            "price_per_unit": price,
            "points_per_unit": pv,
            "total_amount": price * qty_remaining,
            "initial_qty_received": 0,
            "transaction_type": txn["transaction_type"],
            "bill_status": "ยังไม่เปิดบิล",
            "pay_status": "ค้างจ่าย",
            "notes": txn.get("notes", "") or "",
        }).execute()
    _clear_transaction_caches()


def update_transaction(transaction_id: str, data: dict) -> None:
    get_supabase().table("transactions").update(data).eq("id", transaction_id).execute()
    _clear_transaction_caches()


def update_transaction_status(transaction_id: str, bill_status: str = None, pay_status: str = None) -> None:
    updates = {}
    if bill_status:
        updates["bill_status"] = bill_status
    if pay_status:
        updates["pay_status"] = pay_status
    if updates:
        get_supabase().table("transactions").update(updates).eq("id", transaction_id).execute()
        _clear_transaction_caches()


# ─── Calculations ────────────────────────────────────────────────────────────

def get_transaction_balance(transaction_id: str) -> dict:
    """ยอดจ่ายและรับของสะสมของรายการ พร้อมจำนวนที่รับได้อีก"""
    db = get_supabase()
    _rows = _retry(lambda: db.table("transactions").select("*").eq("id", transaction_id).execute().data)
    if not _rows:
        return None
    txn = _rows[0]
    events = _retry(lambda: db.table("partial_events").select("*").eq("transaction_id", transaction_id).execute().data)

    _partial_paid = sum(float(e["amount_paid"]) for e in events)
    total_paid = float(txn["total_amount"]) if txn["pay_status"] in ("จ่ายแล้ว", "COD จ่ายแล้ว") else _partial_paid

    total_received = txn["initial_qty_received"] + sum(e["qty_received"] for e in events)
    price = float(txn["price_per_unit"])
    max_allowed = floor(total_paid / price) if price > 0 else 0

    return {
        "transaction": txn,
        "total_paid": total_paid,
        "total_received": total_received,
        "outstanding_amount": float(txn["total_amount"]) - total_paid,
        "outstanding_qty": txn["qty"] - total_received,
        "max_allowed_qty": max_allowed,
        "can_receive": max(0, max_allowed - total_received),
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
    db.table("partial_events").delete().eq("transaction_id", transaction_id).execute()
    db.table("transactions").delete().eq("id", transaction_id).execute()
    _clear_transaction_caches()


def delete_transactions_batch(transaction_ids: list[str]) -> None:
    """ลบหลาย transaction พร้อมกัน — batch แทนการลูปทีละรายการ (ลด round-trip)"""
    if not transaction_ids:
        return
    db = get_supabase()
    for i in range(0, len(transaction_ids), 50):
        chunk = transaction_ids[i:i + 50]
        db.table("partial_events").delete().in_("transaction_id", chunk).execute()
        db.table("transactions").delete().in_("id", chunk).execute()
    _clear_transaction_caches()


def get_bill_details(bill_no: str) -> list[dict]:
    return (get_supabase().table("transactions")
            .select("product_name, qty, price_per_unit, total_amount, customers(name), date, bill_status")
            .eq("bill_no", bill_no).execute().data)


def update_bill_customer(bill_no: str, new_customer_id: str) -> None:
    get_supabase().table("transactions")\
        .update({"customer_id": new_customer_id})\
        .eq("bill_no", bill_no).execute()
    _clear_transaction_caches()


@st.cache_data(ttl=60)
def bill_has_partial_events(bill_no: str) -> bool:
    """True ถ้าบิลนี้มีการจ่าย/รับของแล้ว"""
    db = get_supabase()
    txn_ids = [r["id"] for r in db.table("transactions").select("id").eq("bill_no", bill_no).execute().data]
    if not txn_ids:
        return False
    events = db.table("partial_events").select("id").in_("transaction_id", txn_ids).limit(1).execute().data
    return bool(events)


def delete_bill(bill_no: str) -> int:
    db = get_supabase()
    rows = db.table("transactions").select("id").eq("bill_no", bill_no).execute().data
    for r in rows:
        db.table("partial_events").delete().eq("transaction_id", r["id"]).execute()
    db.table("transactions").delete().eq("bill_no", bill_no).execute()
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
        "id, date, bill_no, product_id, product_name, qty, total_amount, pay_status, "
        "bill_status, points_per_unit, initial_qty_received, notes"
    ).eq("customer_id", customer_id).order("date").execute().data)
    txn_ids = [t["id"] for t in txns]
    txn_map = {t["id"]: t for t in txns}

    # partial_events in batches
    all_events = []
    _batch = 50
    for _i in range(0, len(txn_ids), _batch):
        _chunk = txn_ids[_i:_i + _batch]
        _evts = _retry(lambda: db.table("partial_events").select(
            "id, date, transaction_id, qty_received, amount_paid, event_type"
        ).in_("transaction_id", _chunk).order("date").execute().data)
        all_events.extend(_evts)

    # shipments
    ships = _retry(lambda: db.table("shipments").select(
        "id, created_at, carrier, tracking_no, items, source"
    ).eq("customer_id", customer_id).order("created_at").execute().data)

    rows = []
    # order rows
    for t in txns:
        rows.append({
            "date":             t["date"][:10],
            "type":             "สั่งซื้อ",
            "bill_no":          t.get("bill_no") or "",
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
            "txn_id":           t["id"],
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
        })
    rows.sort(key=lambda r: r["date"])
    return rows


def delete_partial_event(event_id: str) -> None:
    get_supabase().table("partial_events").delete().eq("id", event_id).execute()
    _clear_transaction_caches()
    bill_has_partial_events.clear()


def delete_payment_events(transaction_id: str) -> None:
    """ลบ partial_events ที่เป็นการจ่ายเงิน (amount_paid > 0) ของ transaction นี้"""
    db = get_supabase()
    evts = db.table("partial_events").select("id, amount_paid").eq("transaction_id", transaction_id).execute().data
    for e in evts:
        if float(e.get("amount_paid") or 0) > 0:
            db.table("partial_events").delete().eq("id", e["id"]).execute()
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
        outstanding_qty = t["qty"] - (t["initial_qty_received"] + qty_by_txn[t["id"]])
        if outstanding_qty > 0:
            if t["pay_status"] == "จ่ายแล้ว":
                outstanding_amt = 0.0
            else:
                outstanding_amt = max(0.0, float(t["total_amount"]) - paid_by_txn[t["id"]])
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
    get_supabase().table("products").delete().eq("id", product_id).execute()


def delete_customer(customer_id: str) -> None:
    get_supabase().table("customers").delete().eq("id", customer_id).execute()


@st.cache_data(ttl=60)
def get_unbilled_pv_summary() -> dict:
    """สรุป PV และยอดเงินของรายการที่ยังไม่เปิดบิล"""
    try:
        rows = get_supabase().table("transactions").select(
            "qty, points_per_unit, total_amount, customers(name)"
        ).eq("bill_status", "ยังไม่เปิดบิล").execute().data
    except Exception:
        return {"count": 0, "total_pv": 0.0, "total_amount": 0.0}

    total_pv = sum(float(r["points_per_unit"]) * r["qty"] for r in rows)
    total_amount = sum(float(r["total_amount"]) for r in rows)
    count = len(rows)
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
def get_all_transactions_df(customer_id: str = None, bill_no: str = None) -> pd.DataFrame:
    """รายการทั้งหมด รวมที่เคลียร์แล้ว"""
    db = get_supabase()

    q = db.table("transactions").select("*, customers(name)")
    if customer_id:
        q = q.eq("customer_id", customer_id)
    if bill_no:
        q = q.eq("bill_no", bill_no)
    txns = _retry(lambda: q.order("bill_no", desc=True, nullsfirst=False).order("date", desc=True).execute().data)

    _TXN_COLS = ["id","วันที่","ลูกค้า","รหัส","สินค้า","สั่ง","รับแล้ว","ยอดรวม",
                 "จ่ายแล้ว","ค้างจ่าย","ค้างรับ","สถานะบิล","สถานะจ่าย","หมายเหตุ",
                 "PV รวม","เลขที่บิล","เคลียร์แล้ว","last_payment_date"]
    if not txns:
        return pd.DataFrame(columns=_TXN_COLS)

    txn_ids = [t["id"] for t in txns]
    all_events: list = []
    for _i in range(0, len(txn_ids), 50):
        _chunk = txn_ids[_i:_i+50]
        all_events += _retry(lambda: db.table("partial_events").select("*").in_("transaction_id", _chunk).execute().data)

    events_by_txn: dict[str, list] = defaultdict(list)
    for e in all_events:
        events_by_txn[e["transaction_id"]].append(e)

    rows = []
    for t in txns:
        tid = t["id"]
        evts = events_by_txn[tid]

        _partial_paid = sum(float(e["amount_paid"]) for e in evts)
        total_paid = float(t["total_amount"]) if t["pay_status"] in ("จ่ายแล้ว", "COD จ่ายแล้ว") else _partial_paid

        total_received = t["initial_qty_received"] + sum(e["qty_received"] for e in evts)
        outstanding_amount = float(t["total_amount"]) - total_paid
        outstanding_qty = t["qty"] - total_received

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
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=_TXN_COLS)


# ─── Finance ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_finance_entry(entry_date: str) -> dict | None:
    rows = get_supabase().table("finance_daily").select("*").eq("entry_date", entry_date).execute().data
    return rows[0] if rows else None


def upsert_finance_entry(data: dict) -> None:
    db = get_supabase()
    db.table("finance_daily").delete().eq("entry_date", data["entry_date"]).execute()
    db.table("finance_daily").insert(data).execute()
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
    db.table("commission_records").delete().eq("period", data["period"]).execute()
    db.table("commission_records").insert(data).execute()
    get_commission_records.clear()
    get_commission_record.clear()


@st.cache_data(ttl=300)
def get_company_info() -> dict:
    rows = get_supabase().table("company_info").select("*").eq("id", 1).execute().data
    return rows[0] if rows else {}


def upsert_company_info(data: dict) -> None:
    data["id"] = 1
    get_supabase().table("company_info").upsert(data).execute()
    get_company_info.clear()


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
    db.table("stock_counts").delete().eq("product_id", data["product_id"]).eq("count_date", data["count_date"]).execute()
    db.table("stock_counts").insert(data).execute()
    get_latest_stock_counts.clear()


def insert_stock_count(data: dict) -> None:
    get_supabase().table("stock_counts").insert(data).execute()
    get_latest_stock_counts.clear()


@st.cache_data(ttl=120)
def get_stock_deposits() -> list[dict]:
    return get_supabase().table("stock_deposits").select("*, products(name)").eq("is_returned", False).execute().data


def insert_stock_deposit(data: dict) -> None:
    get_supabase().table("stock_deposits").insert(data).execute()
    get_stock_deposits.clear()


def return_stock_deposit(deposit_id: str) -> None:
    get_supabase().table("stock_deposits").update({"is_returned": True}).eq("id", deposit_id).execute()
    get_stock_deposits.clear()


@st.cache_data(ttl=60)
def get_unbilled_received_qty_by_product() -> dict:
    db = get_supabase()
    txns = _retry(lambda: db.table("transactions").select("id, product_id, initial_qty_received").eq("bill_status", "ยังไม่เปิดบิล").execute().data)
    if not txns:
        return {}
    txn_ids = [t["id"] for t in txns]
    events_by_txn = defaultdict(int)
    for _i in range(0, len(txn_ids), 50):
        _chunk = txn_ids[_i:_i+50]
        for e in _retry(lambda: db.table("partial_events").select("transaction_id, qty_received").in_("transaction_id", _chunk).execute().data):
            events_by_txn[e["transaction_id"]] += e["qty_received"]
    result = defaultdict(int)
    for t in txns:
        received = t["initial_qty_received"] + events_by_txn[t["id"]]
        if received > 0:
            result[t["product_id"]] += received
    return dict(result)


def get_deposit_qty_by_product() -> dict:
    deposits = get_stock_deposits()
    result = defaultdict(int)
    for d in deposits:
        result[d["product_id"]] += d["qty"]
    return dict(result)


@st.cache_data(ttl=60)
def get_billed_not_received_qty_by_product() -> dict:
    """qty ที่เปิดบิลแล้วแต่ลูกค้ายังไม่รับของ (ของยังอยู่ที่สาขา)"""
    db = get_supabase()
    txns = _retry(lambda: db.table("transactions").select("id, product_id, qty, initial_qty_received").eq("bill_status", "เปิดบิลแล้ว").execute().data)
    if not txns:
        return {}
    txn_ids = [t["id"] for t in txns]
    events_by_txn: dict[str, int] = defaultdict(int)
    for _i in range(0, len(txn_ids), 50):
        _chunk = txn_ids[_i:_i + 50]
        _evts = _retry(lambda: db.table("partial_events").select("transaction_id, qty_received").in_("transaction_id", _chunk).execute().data)
        for e in _evts:
            events_by_txn[e["transaction_id"]] += e["qty_received"]
    result = defaultdict(int)
    for t in txns:
        outstanding = t["qty"] - (t["initial_qty_received"] + events_by_txn[t["id"]])
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


# ─── E-commerce ──────────────────────────────────────────────────────────────

def get_ecommerce_shops() -> list[dict]:
    return get_supabase().table("ecommerce_shops").select("*").order("shop_name").execute().data


def upsert_ecommerce_shop(data: dict) -> None:
    db = get_supabase()
    db.table("ecommerce_shops").delete().eq("id", data["id"]).execute()
    db.table("ecommerce_shops").insert(data).execute()


def insert_ecommerce_sales(rows: list[dict]) -> None:
    if rows:
        get_supabase().table("ecommerce_sales").insert(rows).execute()


def get_ecommerce_sales_df(start_date: str, end_date: str) -> pd.DataFrame:
    rows = get_supabase().table("ecommerce_sales").select(
        "sale_date,platform,shop_name,qty,item_price,product_id,products(name)"
    ).gte("sale_date", start_date).lte("sale_date", end_date).order("sale_date", desc=True).execute().data
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([{
        "วันที่": r["sale_date"],
        "ร้าน": r["shop_name"],
        "สินค้า": (r.get("products") or {}).get("name", r.get("product_id") or "ยังไม่ map"),
        "จำนวน": r["qty"],
        "ยอด": float(r["item_price"] or 0),
    } for r in rows])


def get_ecommerce_product_map() -> dict:
    rows = get_supabase().table("ecommerce_product_map").select("*").execute().data
    return {(r["platform"], r["platform_item_id"]): r["product_id"] for r in rows}


def upsert_ecommerce_product_map(rows: list[dict]) -> None:
    for row in rows:
        get_supabase().table("ecommerce_product_map").upsert(
            row, on_conflict="platform,platform_item_id"
        ).execute()


def get_unmapped_ecommerce_items(platform: str = "shopee") -> list[dict]:
    rows = get_supabase().table("ecommerce_sales").select(
        "item_id_platform,shop_name"
    ).eq("platform", platform).is_("product_id", "null").execute().data
    seen = set()
    result = []
    for r in rows:
        key = (r["item_id_platform"], r["shop_name"])
        if key not in seen:
            seen.add(key)
            result.append({"item_id": r["item_id_platform"], "shop_name": r["shop_name"]})
    return result


# ─── Shipments ────────────────────────────────────────────────────────────────

def create_shipment(data: dict) -> None:
    get_supabase().table("shipments").insert(data).execute()
    get_shipments.clear()
    get_customer_ledger.clear()


@st.cache_data(ttl=60)
def get_shipments(customer_id: str = None) -> list[dict]:
    q = get_supabase().table("shipments").select("*, customers(name)")
    if customer_id:
        q = q.eq("customer_id", customer_id)
    return q.order("created_at", desc=True).execute().data


def update_shipment_tracking(shipment_id: str, tracking_no: str) -> None:
    get_supabase().table("shipments").update(
        {"tracking_no": tracking_no}
    ).eq("id", shipment_id).execute()
    get_shipments.clear()
    get_customer_ledger.clear()


def delete_shipment(shipment_id: str) -> None:
    get_supabase().table("shipments").delete().eq("id", shipment_id).execute()
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
    res = (get_supabase().table("shipments")
           .delete()
           .eq("delivery_status", "จัดส่งแล้ว")
           .gte("created_at", f"{date_from}T00:00:00+07:00")
           .lte("created_at", f"{date_to}T23:59:59+07:00")
           .execute())
    get_shipments.clear()
    get_customer_ledger.clear()
    return len(res.data) if res.data else 0


def mark_cod_transferred(tracking_nos: list[str]) -> None:
    """บันทึกวันที่ COD โอนแล้วสำหรับ tracking numbers ที่ระบุ"""
    if not tracking_nos:
        return
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    (get_supabase().table("shipments")
     .update({"cod_transferred_at": now})
     .in_("tracking_no", tracking_nos)
     .is_("cod_transferred_at", "null")
     .execute())


def mark_cod_paid(tracking_no_to_date: dict[str, str]) -> int:
    """เมื่อ COD ของ tracking ใน tracking_no_to_date ถูกโอนเข้าระบบแล้ว
    mark เฉพาะ transactions ที่ผูกกับ shipment นั้น (จับคู่ผ่าน product_id ใน items)
    ถ้า shipment ไม่มีข้อมูล items → fallback mark ทุก COD ของลูกค้า (legacy)
    คืนจำนวน transaction ที่ mark"""
    if not tracking_no_to_date:
        return 0
    db = get_supabase()
    ships = (db.table("shipments")
             .select("customer_id, tracking_no, items")
             .in_("tracking_no", list(tracking_no_to_date.keys()))
             .execute().data) or []
    count = 0
    for s in ships:
        cust_id = s.get("customer_id")
        tn      = s.get("tracking_no")
        if not cust_id:
            continue
        transfer_date = (tracking_no_to_date.get(tn) or "")[:10]
        if not transfer_date:
            from datetime import datetime, timezone
            transfer_date = datetime.now(timezone.utc).date().isoformat()

        # ดึง COD transactions ทั้งหมดของลูกค้านี้ที่ยังค้างอยู่
        all_txns = (db.table("transactions")
                    .select("id, total_amount, product_id")
                    .eq("customer_id", cust_id)
                    .eq("pay_status", "COD")
                    .execute().data) or []

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
            db.table("partial_events").insert({
                "id":             str(uuid.uuid4()),
                "date":           transfer_date,
                "transaction_id": t["id"],
                "qty_received":   0,
                "amount_paid":    float(t["total_amount"]),
                "event_type":     "จ่ายเงิน",
                "notes":          f"COD โอนจาก iShip ({tn})",
            }).execute()
            db.table("transactions").update({"pay_status": "COD จ่ายแล้ว"}).eq("id", t["id"]).execute()
            count += 1
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


_DELIVERY_TERMINAL = {"จัดส่งแล้ว", "ตีกลับ", "ยกเลิก"}

def update_delivery_statuses(statuses: dict) -> int:
    """อัปเดต delivery_status ใน shipments, คืนจำนวนที่อัปเดต"""
    db = get_supabase()
    count = 0
    for track_no, status in statuses.items():
        if track_no:
            db.table("shipments").update({"delivery_status": status}).eq("tracking_no", track_no).execute()
            count += 1
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
    get_supabase().table("shipments").update({"line_notified_at": now}).eq("id", shipment_id).execute()
