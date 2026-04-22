import os
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client, Client
import pandas as pd
from collections import defaultdict
from math import floor
import uuid

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

def get_products() -> list[dict]:
    return get_supabase().table("products").select("*").order("name").execute().data


def get_customers() -> list[dict]:
    return get_supabase().table("customers").select("*").order("name").execute().data


def upsert_product(data: dict) -> None:
    get_supabase().table("products").upsert(data).execute()


def upsert_customer(data: dict) -> None:
    get_supabase().table("customers").upsert(data).execute()


# ─── Transactions ────────────────────────────────────────────────────────────

def insert_transaction(data: dict) -> None:
    get_supabase().table("transactions").insert(data).execute()


def insert_partial_event(data: dict) -> None:
    get_supabase().table("partial_events").insert(data).execute()


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


def update_transaction(transaction_id: str, data: dict) -> None:
    get_supabase().table("transactions").update(data).eq("id", transaction_id).execute()


def update_transaction_status(transaction_id: str, bill_status: str = None, pay_status: str = None) -> None:
    updates = {}
    if bill_status:
        updates["bill_status"] = bill_status
    if pay_status:
        updates["pay_status"] = pay_status
    if updates:
        get_supabase().table("transactions").update(updates).eq("id", transaction_id).execute()


# ─── Calculations ────────────────────────────────────────────────────────────

def get_transaction_balance(transaction_id: str) -> dict:
    """ยอดจ่ายและรับของสะสมของรายการ พร้อมจำนวนที่รับได้อีก"""
    db = get_supabase()
    txn = db.table("transactions").select("*").eq("id", transaction_id).single().execute().data
    events = db.table("partial_events").select("*").eq("transaction_id", transaction_id).execute().data

    total_paid = (
        float(txn["total_amount"]) if txn["pay_status"] == "จ่ายแล้ว" else 0.0
    ) + sum(float(e["amount_paid"]) for e in events)

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


def delete_transaction(transaction_id: str) -> None:
    db = get_supabase()
    db.table("partial_events").delete().eq("transaction_id", transaction_id).execute()
    db.table("transactions").delete().eq("id", transaction_id).execute()


def delete_product(product_id: str) -> None:
    get_supabase().table("products").delete().eq("id", product_id).execute()


def delete_customer(customer_id: str) -> None:
    get_supabase().table("customers").delete().eq("id", customer_id).execute()


def get_unbilled_pv_summary() -> dict:
    """สรุป PV และยอดเงินของรายการที่ยังไม่เปิดบิล"""
    rows = get_supabase().table("transactions").select(
        "qty, points_per_unit, total_amount, customers(name)"
    ).eq("bill_status", "ยังไม่เปิดบิล").execute().data

    total_pv = sum(float(r["points_per_unit"]) * r["qty"] for r in rows)
    total_amount = sum(float(r["total_amount"]) for r in rows)
    count = len(rows)
    return {"count": count, "total_pv": total_pv, "total_amount": total_amount}


def get_all_transactions_df(customer_id: str = None) -> pd.DataFrame:
    """รายการทั้งหมด รวมที่เคลียร์แล้ว"""
    db = get_supabase()

    q = db.table("transactions").select("*, customers(name)")
    if customer_id:
        q = q.eq("customer_id", customer_id)
    txns = q.order("date", desc=True).execute().data

    if not txns:
        return pd.DataFrame()

    txn_ids = [t["id"] for t in txns]
    events = db.table("partial_events").select("*").in_("transaction_id", txn_ids).execute().data

    events_by_txn: dict[str, list] = defaultdict(list)
    for e in events:
        events_by_txn[e["transaction_id"]].append(e)

    rows = []
    for t in txns:
        tid = t["id"]
        evts = events_by_txn[tid]

        total_paid = (
            float(t["total_amount"]) if t["pay_status"] == "จ่ายแล้ว" else 0.0
        ) + sum(float(e["amount_paid"]) for e in evts)

        total_received = t["initial_qty_received"] + sum(e["qty_received"] for e in evts)
        outstanding_amount = float(t["total_amount"]) - total_paid
        outstanding_qty = t["qty"] - total_received

        cleared = outstanding_amount <= 0.01 and outstanding_qty <= 0
        customer_name = (t.get("customers") or {}).get("name", t["customer_id"])
        rows.append({
            "id": tid,
            "วันที่": t["date"],
            "ลูกค้า": customer_name,
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
            "เคลียร์แล้ว": cleared,
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def get_outstanding_df(customer_id: str = None) -> pd.DataFrame:
    """รายการที่ยังค้างชำระหรือค้างรับของ"""
    db = get_supabase()

    q = db.table("transactions").select("*, customers(name)")
    if customer_id:
        q = q.eq("customer_id", customer_id)
    txns = q.order("date", desc=True).execute().data

    if not txns:
        return pd.DataFrame()

    txn_ids = [t["id"] for t in txns]
    events = db.table("partial_events").select("*").in_("transaction_id", txn_ids).execute().data

    events_by_txn: dict[str, list] = defaultdict(list)
    for e in events:
        events_by_txn[e["transaction_id"]].append(e)

    rows = []
    for t in txns:
        tid = t["id"]
        evts = events_by_txn[tid]

        total_paid = (
            float(t["total_amount"]) if t["pay_status"] == "จ่ายแล้ว" else 0.0
        ) + sum(float(e["amount_paid"]) for e in evts)

        total_received = t["initial_qty_received"] + sum(e["qty_received"] for e in evts)
        outstanding_amount = float(t["total_amount"]) - total_paid
        outstanding_qty = t["qty"] - total_received

        if outstanding_amount > 0.01 or outstanding_qty > 0:
            customer_name = (t.get("customers") or {}).get("name", t["customer_id"])
            rows.append({
                "id": tid,
                "วันที่": t["date"],
                "ลูกค้า": customer_name,
                "สินค้า": t["product_name"],
                "สั่ง": t["qty"],
                "รับแล้ว": total_received,
                "ค้างรับ": max(0, outstanding_qty),
                "ยอดรวม": float(t["total_amount"]),
                "จ่ายแล้ว": total_paid,
                "ค้างจ่าย": max(0.0, outstanding_amount),
                "PV รวม": float(t["points_per_unit"]) * t["qty"],
                "ประเภท": t["transaction_type"],
                "สถานะบิล": t["bill_status"],
            })

    return pd.DataFrame(rows) if rows else pd.DataFrame()
