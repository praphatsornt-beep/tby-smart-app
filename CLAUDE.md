# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

**TBY SMART APP** — A Streamlit business management app deployed on Streamlit Community Cloud for a Zhulian MLM distributor. Backend is Supabase (PostgreSQL). No local dev server needed for testing — changes go live via `git push origin main`.

## Running & Deploying

```bash
# Local development
streamlit run app.py

# Deploy: just push — Streamlit Cloud auto-deploys from GitHub main branch
git add . && git commit -m "..." && git push origin main
```

Dependencies: `pip install -r requirements.txt`

Credentials live in `.streamlit/secrets.toml` (local) and Streamlit Cloud Secrets (production). Required keys: `SUPABASE_URL`, `SUPABASE_KEY`. Optional: `ISHIP_TOKEN` + iShip sender address fields, `SHOPEE_PARTNER_ID/KEY`.

## Architecture

Single-file app (`app.py`, ~5440 lines) with supporting modules:

| File | Role |
|---|---|
| `app.py` | All UI — Streamlit tabs, forms, session state |
| `database.py` | All Supabase queries. Cached functions: `get_products()` (5 min), `get_customers()` (5 min), `get_customer_addresses()` (2 min). Mutations call `.clear()` on the relevant cache. |
| `iship_api.py` | iShip shipping integration. Non-COD: Bearer token to `/api/create_order`. COD must be created manually in the iShip dashboard — API support is unreliable. |
| `line_api.py` | LINE OA push notifications: `push_tracking()`, `push_outstanding()`, `push_bill_summary()`. Reads `LINE_CHANNEL_ACCESS_TOKEN` from `st.secrets`. Requires `line_user_id` stored on the customer row. |
| `thai_address.py` | Postcode → tambon/amphure/province lookup using local `thai_postcodes.json` (7,498 tambons). Cached indefinitely with `@st.cache_data`. |
| `bangkok_addresses.py` | Bangkok-specific lookups: `lookup_khet(แขวง, zipcode)→เขต` and `ZIPCODE_TO_AMPHURE` dict for nearby-province zipcodes (นนทบุรี, ปทุมธานี, สมุทรปราการ). Used as fallback when `thai_postcodes.json` returns ambiguous results. |
| `flash_zones.py` | Flash Express zone surcharges and SPX surcharges by postcode/weight. |
| `carriers.py` | Multi-carrier shipping rate cards (Flash Thunder, etc.) and rate comparison, built on top of `flash_zones.py`. |
| `shopee_api.py` | Shopee Open Platform OAuth + order sync (integration not yet fully wired into the UI). |

## Tab Layout (`app.py`)

```
tab_dash: 🏠 หน้าแรก       — dashboard
tab1: 📋 บันทึกรายการ
  ├── _sub_calc: 🔢 คำนวณยอด  — shipping/price calculator
  ├── _sub_ship: 📦 ส่งของ    — shipping-only form
  └── _sub_sale: 📝 บันทึกขาย — main sale form
tab5: 🗂️ รายละเอียดบิล
  ├── _t5_out:    💰 ยอดค้าง   — outstanding balances, per-transaction actions
  ├── _t5_ledger: 👤 บัตรลูกค้า — per-customer ledger, one table per bill
  ├── _t5_txn:    📋 ประวัติทั้งหมด — bill detail / print view (1/2-copy layout)
  ├── _t5_cust:   🖨️ จัดการบิล — bill management, deletion
  └── _t5_ship:   🚚 ประวัติการส่ง — shipment history
tab6: 📦 สต๊อก
  ├── t6a: สรุปสต๊อก — stock counts per product
  └── t6b: ของฝาก   — deposited items: products awaiting shipment grouped by customer
tab_fin: 💵 การเงิน
tab_ecom: 🛒 E-commerce (Shopee)
tab4: ⚙️ จัดการข้อมูล — products, customers, addresses, bill deletion
```

## database.py Patterns

**Cache invalidation**: `_clear_transaction_caches()` clears all transaction-related caches at once (`get_all_transactions_df`, `get_outstanding_df`, `get_bill_summaries`, `get_unbilled_pv_summary`, `get_unbilled_received_qty_by_product`). Every mutation must call it.

**Retry wrapper**: All Supabase calls should go through `_retry(fn, attempts=2, delay=0.5)` to handle transient network errors.

**PostgREST `.in_()` limit**: URL length caps out around 50 IDs. All `.in_()` queries are batched in chunks of 50. Do not increase this — PostgREST will silently fail or return HTTP 414.

**`split_and_open_bill(transaction_id, qty_to_bill)`**: splits a ฝากของ transaction into two rows (billed qty vs. remaining), then marks the new row as เปิดบิลแล้ว.

## Key Patterns

**Session state for widgets**: Streamlit widgets can't have their key set after rendering. Use staging keys (e.g., `_fsp_dt`, `_fr_dt`) that are applied to widget keys BEFORE the widget renders on the next rerun.

**Cart persistence**: `st.data_editor` stores only edit diffs relative to its initial DataFrame. Always keep the same base DataFrame in `st.session_state["_cart_base"]` across reruns — never re-initialize with an empty DataFrame while the user is mid-entry.

**Address autocomplete**: Two directions — postcode→tambon (`thai_address.lookup()`) and tambon→postcode (`thai_address.lookup_by_tambon()`). Both use `_sp_last_dt`/`_r_last_dt` flags to suppress re-showing suggestions after a selection.

**COD calculation**: `collect = total_amt + ship_fee + cod_fee` where `cod_fee = (total_amt + ship_fee) × 3.21%`

**Customer IDs**: Always `C-NNN` format (e.g., `C-014`). The quick-add form in บันทึกขาย auto-generates the next C-NNN by scanning existing IDs for the max number.

**Bill numbers**: Format `YYMMDD-NNN` (e.g., `260427-001`). Generated by `db.get_next_bill_no(date_str)`. Column `bill_no` was added to `transactions` via ALTER TABLE — not in `supabase_setup.sql`.

## Database Schema Key Points

- `transactions`: one row = one product line. Multiple rows share the same `bill_no`.
- `partial_events`: records each payment/receipt event against a transaction.
- `customer_addresses`: separate table, one customer → many addresses.
- `shipments`: records iShip shipments with `items` as JSONB.
- `pay_status` CHECK includes `'COD'` (added via ALTER TABLE, not in setup SQL).

## LINE OA Integration

Customers register by texting `สมัคร 0812345678` to the LINE OA. A Google Apps Script (GAS) webhook handles this, queries Supabase for the matching phone number, and writes `line_user_id` back to the `customers` row.

Once `line_user_id` is set, `app.py` can call `line_api.push_tracking()` after a successful iShip shipment to notify the customer via LINE.

Secrets needed: `LINE_CHANNEL_ACCESS_TOKEN` in Streamlit secrets (for push) and `SUPABASE_URL`/`SUPABASE_KEY` in the GAS script (for the registration webhook).

## WAT Framework (existing tools/)

The `tools/` and `workflows/` directories are for separate scripting tasks unrelated to the Streamlit app. Use `uv run tools/<script>.py` (fallback: `python`). Credentials in `.env` via `python-dotenv`. Ask before creating or overwriting any workflow file.
