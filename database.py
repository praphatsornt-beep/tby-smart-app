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
    return get_supabase().table("products").select("*").order("id").execute().data


def get_customers() -> list[dict]:
    return get_supabase().table("customers").select("*").order("name").execute().data


def get_customer_by_phone(phone: str) -> dict | None:
    rows = get_supabase().table("customers").select("*").eq("phone", phone.strip()).execute().data
    return rows[0] if rows else None


# ─── Customer Addresses (แยก table — 1 ลูกค้า มีได้หลายที่อยู่) ────────────

def get_customer_addresses(customer_id: str = None) -> list[dict]:
    q = get_supabase().table("customer_addresses").select("*, customers(name)")
    if customer_id:
        q = q.eq("customer_id", customer_id)
    return q.order("phone").execute().data


def get_address_by_phone(phone: str) -> dict | None:
    rows = (get_supabase().table("customer_addresses")
            .select("*, customers(name)").eq("phone", phone.strip()).execute().data)
    return rows[0] if rows else None


def upsert_customer_address(data: dict) -> None:
    db = get_supabase()
    if data.get("phone"):
        db.table("customer_addresses").delete().eq("phone", data["phone"].strip()).execute()
    db.table("customer_addresses").insert(data).execute()


def delete_customer_address(address_id: str) -> None:
    get_supabase().table("customer_addresses").delete().eq("id", address_id).execute()


def upsert_product(data: dict) -> None:
    get_supabase().table("products").upsert(data).execute()


def upsert_customer(data: dict) -> None:
    get_supabase().table("customers").upsert(data).execute()


def update_customer_address(customer_id: str, data: dict) -> None:
    """อัปเดตที่อยู่จัดส่งของลูกค้า (recipient_name, phone, address, postal_code)"""
    get_supabase().table("customers").update(data).eq("id", customer_id).execute()



# ─── Transactions ────────────────────────────────────────────────────────────

def insert_transaction(data: dict) -> None:
    get_supabase().table("transactions").insert(data).execute()


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


def delete_bill(bill_no: str) -> int:
    db = get_supabase()
    rows = db.table("transactions").select("id").eq("bill_no", bill_no).execute().data
    for r in rows:
        db.table("partial_events").delete().eq("transaction_id", r["id"]).execute()
    db.table("transactions").delete().eq("bill_no", bill_no).execute()
    return len(rows)


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

        cleared = outstanding_amount <= 0.01 and outstanding_qty <= 0 and t["bill_status"] == "เปิดบิลแล้ว"
        customer_name = (t.get("customers") or {}).get("name", t["customer_id"])
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
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ─── Finance ─────────────────────────────────────────────────────────────────

def get_finance_entry(entry_date: str) -> dict | None:
    rows = get_supabase().table("finance_daily").select("*").eq("entry_date", entry_date).execute().data
    return rows[0] if rows else None


def upsert_finance_entry(data: dict) -> None:
    db = get_supabase()
    db.table("finance_daily").delete().eq("entry_date", data["entry_date"]).execute()
    db.table("finance_daily").insert(data).execute()


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


# ─── Stock ───────────────────────────────────────────────────────────────────

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


def insert_stock_count(data: dict) -> None:
    get_supabase().table("stock_counts").insert(data).execute()


def get_stock_deposits() -> list[dict]:
    return get_supabase().table("stock_deposits").select("*, products(name)").eq("is_returned", False).execute().data


def insert_stock_deposit(data: dict) -> None:
    get_supabase().table("stock_deposits").insert(data).execute()


def return_stock_deposit(deposit_id: str) -> None:
    get_supabase().table("stock_deposits").update({"is_returned": True}).eq("id", deposit_id).execute()


def get_unbilled_received_qty_by_product() -> dict:
    db = get_supabase()
    txns = db.table("transactions").select("id, product_id, initial_qty_received").eq("bill_status", "ยังไม่เปิดบิล").execute().data
    if not txns:
        return {}
    txn_ids = [t["id"] for t in txns]
    events = db.table("partial_events").select("transaction_id, qty_received").in_("transaction_id", txn_ids).execute().data
    events_by_txn = defaultdict(int)
    for e in events:
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


def get_billed_not_received_qty_by_product() -> dict:
    """qty ที่เปิดบิลแล้วแต่ลูกค้ายังไม่รับของ (ของยังอยู่ที่สาขา)"""
    db = get_supabase()
    txns = db.table("transactions").select("id, product_id, qty, initial_qty_received").eq("bill_status", "เปิดบิลแล้ว").execute().data
    if not txns:
        return {}
    txn_ids = [t["id"] for t in txns]
    events = db.table("partial_events").select("transaction_id, qty_received").in_("transaction_id", txn_ids).execute().data
    events_by_txn = defaultdict(int)
    for e in events:
        events_by_txn[e["transaction_id"]] += e["qty_received"]
    result = defaultdict(int)
    for t in txns:
        outstanding = t["qty"] - (t["initial_qty_received"] + events_by_txn[t["id"]])
        if outstanding > 0:
            result[t["product_id"]] += outstanding
    return dict(result)


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

        if outstanding_amount > 0.01 or outstanding_qty > 0 or t["bill_status"] == "ยังไม่เปิดบิล":
            customer_name = (t.get("customers") or {}).get("name", t["customer_id"])
            rows.append({
                "id": tid,
                "วันที่": t["date"],
                "ลูกค้า": customer_name,
                "รหัส": t["product_id"],
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
                "เลขที่บิล": t.get("bill_no") or "",
            })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


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
