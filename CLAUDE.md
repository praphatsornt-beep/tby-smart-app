# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

**TBY SMART APP** — A Streamlit business management app deployed on Streamlit Community Cloud for a Zhulian MLM distributor. It replaces manual spreadsheets for: recording sales/orders, shipping (iShip integration), tracking outstanding balances (ค้างจ่าย/ค้างรับ) and PV points, daily company-transfer/commission finance, stock counts, and Shopee e-commerce sync. Backend is Supabase (PostgreSQL). No local dev server needed for testing — changes go live via `git push origin main`.

## Running & Deploying

```bash
# Local development
streamlit run app.py

# Deploy: just push — Streamlit Cloud auto-deploys from GitHub main branch
git add . && git commit -m "..." && git push origin main
```

Dependencies: `pip install -r requirements.txt`

Credentials live in `.streamlit/secrets.toml` (local) and Streamlit Cloud Secrets (production). Required keys: `SUPABASE_URL`, `SUPABASE_KEY`. Optional: `ISHIP_TOKEN` + iShip sender address fields, `SHOPEE_PARTNER_ID`/`SHOPEE_PARTNER_KEY`, `LINE_CHANNEL_ACCESS_TOKEN`, `APP_PASSWORD` (enables a simple password login gate — see Authentication below), `DEBUG_MODE` (shows raw API-response debug expanders when truthy).

## Architecture

`app.py` (~720 lines) is now a thin shell — page config/theme CSS, a password login gate, the Shopee OAuth callback handler, two `st.dialog` popups shared across tabs (iShip carrier-select and iShip success), and lazy tab routing. All per-tab UI lives in dedicated modules:

| File | Role |
|---|---|
| `app.py` | Page shell: theme CSS, login gate, Shopee OAuth callback, shared `st.dialog`s (`_show_carrier_select`, `_show_iship_success_dialog` — driven by `st.session_state["_iship_carrier_select"]` / `["_iship_success_info"]`), lazy tab nav (`st.pills`, renders only the active tab). |
| `record_ui.py` | UI for 📋 บันทึกรายการ (บันทึกขาย / ส่งของ / คำนวณยอด). `render(container, products, customers, customers_by_name)`. |
| `bill_detail_ui.py` | UI for 🗂️ รายละเอียดบิล — sub-tabs ยอดค้าง+จัดการบิล / บัตรลูกค้า / ประวัติทั้งหมด. `render(products, customers)`. The 4th sub-tab (ประวัติการส่ง) is split out into `shipment_history_ui.py`. |
| `shipment_history_ui.py` | UI for the 🚚 ประวัติการส่ง sub-tab of 🗂️ รายละเอียดบิล — split out of `bill_detail_ui.py` for size (delivery-status/COD-transfer/billing-report sync buttons, shipment table with tracking edit + delete + resend-to-iShip, label reprinting for both iShip and manual shipments, bulk-clear of delivered history). `render(customers)`. |
| `ui_helpers.py` | Shared helpers used by `record_ui.py` and `bill_detail_ui.py`: bill-print rendering (`_render_bill_panel`, `_bills_from_df`), address autocomplete (`_tambon_selectbox`, `_postcode_suggest`), iShip response/address parsing (`_extract_tracking`, `_build_success_info`, `_parse_iship_address`), `_quick_add_customer`, `_warn_duplicate_phone`, `calc_shipping`, `raw_weight_g`, `BOX_WEIGHT_G`, `get_bulky_presets()` (reads box-size presets from the `box_presets` table — managed in ⚙️ จัดการข้อมูล → 📐 ขนาดกล่อง, not editable at the point of use anymore). |
| `ecom_ui.py` | UI for 🛒 E-commerce (Shopee) — `render()`. Fully wired: OAuth connect → sync orders → view sales → map platform SKUs to internal products. |
| `fin_ui.py` | UI for 💵 การเงิน — `render()`. Daily finance ledger + commission/VAT-claim receipts. |
| `dashboard_ui.py` | UI for 🏠 หน้าแรก — `render()`. Today's sales, outstanding, COD-pending, PV, slow/problem shipments. |
| `stock_ui.py` | UI for 📦 สต๊อก — `render()`. Stock count sub-tab + ของฝาก (deposited items) sub-tab. |
| `master_data_ui.py` | UI for ⚙️ จัดการข้อมูล — `render()`. Products/customers/addresses editors + ZIP backup + monthly sales export. |
| `database.py` | All Supabase queries, `@st.cache_data`-cached reads, `_retry()` wrapper. |
| `calc_logic.py` | Pure calculation helpers shared by the คำนวณยอด tab and LINE OA order parsing: `parse_calc_order()`, `cod_fee()`, `pack_boxes()`, `pack_boxes_grouped()`. Covered by `tests/`. |
| `iship_api.py` | iShip shipping integration: `create_order()` (Bearer token), `get_label_url()`, `get_cod_transfers()` and `get_shipment_statuses()` (scrape the iShip web dashboard via a cached login session — no official API for these). COD orders must still be created manually in the iShip dashboard — order-create API support for COD is unreliable. |
| `line_api.py` | LINE OA push notifications: `push_tracking()`, `push_outstanding()`, `push_bill_summary()`, `push_partial_receipt()`, `push_text()`. Reads `LINE_CHANNEL_ACCESS_TOKEN` from `st.secrets`. Requires `line_user_id` (and optional `group_id`) stored on the customer row. |
| `thai_address.py` | Postcode → tambon/amphure/province lookup using local `thai_postcodes.json` (7,498 tambons). Cached indefinitely with `@st.cache_data`. |
| `bangkok_addresses.py` | Bangkok-specific lookups: `lookup_khet(แขวง, zipcode)→เขต` and `ZIPCODE_TO_AMPHURE` dict for nearby-province zipcodes (นนทบุรี, ปทุมธานี, สมุทรปราการ). Used as fallback when `thai_postcodes.json` returns ambiguous results. |
| `flash_zones.py` | Flash Express zone surcharges and SPX surcharges by postcode/weight. |
| `carriers.py` | Multi-carrier shipping rate cards (Flash Thunder, Bulky, etc.), rate comparison (`get_shipping_options`), and box planning (`plan_boxes`), built on top of `flash_zones.py` and `calc_logic.pack_boxes*`. |
| `shopee_api.py` | Shopee Open Platform OAuth + order sync. Wired into `ecom_ui.py`. |

## Tests

`tests/` — unittest suite for `calc_logic.py`, `flash_zones.py`, `carriers.py`. Run: `py -m unittest discover -s tests -v` (pytest not installed, use stdlib unittest).

## Authentication

If `APP_PASSWORD` is set in secrets, `app.py` shows a password form before rendering anything and gates on `st.session_state["_authenticated"]`. No per-user accounts — one shared password for all staff. If `APP_PASSWORD` is unset, the app has no login gate at all.

`DEBUG_MODE` (secret) toggles visibility of raw-response `st.expander`s (iShip create/label responses, etc.) used for troubleshooting integration issues in production.

## Tab Layout

Top nav is `st.pills` (falls back to `st.radio` on old Streamlit) in this order — only the active tab's `render()` runs each rerun:

```
🏠 หน้าแรก        — dashboard_ui.py
📋 บันทึกรายการ   — record_ui.py, sub-tabs (in this order): 📝 บันทึกขาย, 📦 ส่งของ, 🔢 คำนวณยอด
🗂️ รายละเอียดบิล  — bill_detail_ui.py, sub-tabs: 💰 ยอดค้าง / จัดการบิล, 👤 บัตรลูกค้า, 📋 ประวัติทั้งหมด, 🚚 ประวัติการส่ง
📦 สต๊อก          — stock_ui.py: 📦 สต๊อก (counts), 📋 ของฝาก (deposited items)
💵 การเงิน        — fin_ui.py: 💰 ยอดขาย (daily finance), 📑 ใบเสร็จ/เคลม VAT (commission + VAT)
🛒 E-commerce     — ecom_ui.py (Shopee)
⚙️ จัดการข้อมูล   — master_data_ui.py
```

Note: จัดการบิล (bill management/deletion) is no longer a separate sub-tab — it was merged into ยอดค้าง as part of the same panel.

## Business Logic by Tab

### 📋 บันทึกรายการ (`record_ui.py`)

- **📝 บันทึกขาย**: pick/quick-add customer, paste product codes (`_parse_quick_order`) or edit an `st.data_editor` cart, optionally receive outstanding items from old bills in the same flow (`db.get_pending_receipts_for_customer` + `_process_old_items_receipt`), set delivery status (ส่งพัสดุ/ฝากของ/รับแล้ว) and pay status (ค้างจ่าย/จ่ายแล้ว/COD/จ่ายบางส่วน). Saves a batch of transaction rows (`db.insert_transactions_batch`); partial payment is split proportionally across cart lines by `line_total/cart_total` share, with the **last row absorbing the rounding remainder**, and fully-paid lines flip to `จ่ายแล้ว`.
- **📦 ส่งของ**: shipping-only — no product/sales rows, cart items are informational only for weight/iShip payload. Saves straight to `db.create_shipment(source="ship")`.
- **🔢 คำนวณยอด**: parses LINE-OA-style order text (`calc_logic.parse_calc_order`, e.g. `TF2581-2 RB2306-1 SH-kg12170 COD`), shows customer-facing quote vs. actual cheapest carrier cost (`carriers.get_shipping_options`), can push the quote via LINE, trigger a trial iShip order, and includes a box-packing planner (`carriers.plan_boxes`) plus a separate manual (non-iShip) label printer with custom box-size presets that also writes `db.create_shipment(source="manual")`.
- **iShip flow (shared by บันทึกขาย/ส่งของ)**: both stage a request into `st.session_state["_iship_carrier_select"]` (with `tab: "sale"/"ship"`) rather than calling `iship_api.create_order` inline — the actual dialog/order-create lives in `app.py`. On success, `_build_success_info` populates `_iship_success_info` (shared success dialog with a "ส่งแจ้งลูกค้าทาง LINE" button), and `_do_clear_after_iship` triggers a full form reset.
- **Key formulas**: COD fee = `ceil((product_total + ship_fee) × 0.0321)`, editable via a manual override input. Shipping base (`calc_shipping()`): Flash Express `39 ฿` for first 5kg + `10 ฿`/kg beyond, plus `zone_surcharge(postcode)`. `BOX_WEIGHT_G = 500` (0.5kg) is added on top of raw product weight everywhere shipping cost is computed — `raw_weight_g()` deliberately excludes it, don't double-add. Carrier auto-pick (`_pick_carrier`): Bangkok-area postcodes (`10`/`11`/`12` prefix) or weight > 3kg → SPX Express, else Flash Express.
- **Session-state patterns**: staging keys (`_fr_*`, `_fsp_*`) are popped into the real widget key before that widget renders next rerun (Streamlit forbids setting a widget's key after render). Cart persistence: the `st.data_editor` base DataFrame lives in `_cart_base`/`_sp_cart_base`, and the editor key is version-suffixed (`m_cart_{version}`) — bumping the version int + popping the old key is the reliable way to force-reset a data_editor.

### 🗂️ รายละเอียดบิล (`bill_detail_ui.py`)

- **💰 ยอดค้าง / จัดการบิล**: per-customer expanders grouped from `db.get_outstanding_df()`. Only the "active" customer (from search, or a flagged `_t5_out_active_cust`) gets its full action panel rendered — everyone else shows a collapsed static table (perf guard against rendering 20+ heavy panels every rerun). Multi-row select (`st.dataframe(selection_mode="multi-row")`) + a mode radio (กำหนดเอง / จ่ายเงินอย่างเดียว / รับของอย่างเดียว / เปิดบิลอย่างเดียว) drives a combo `st.data_editor` for recording payment/receipt across several rows at once. Also has bill/item delete and a bulk "✅ เคลียร์บิล" (mark several bills paid+billed at once).
- **👤 บัตรลูกค้า**: ledger view from `db.get_customer_ledger(cid)`; per-bill timeline with a delivery-method heuristic (🚚 ส่งพัสดุ if ship date matches order date, 🏪 รับหน้าร้าน if bill_no found in receipts, else 📦 ฝากของ); a "สรุปรายสินค้า" expander computes billed-vs-prepaid netting (`ค้างสุทธิ = ค้างจ่ายบิล − จ่ายล่วงหน้า`, and the reverse `เครดิตเหลือ`) plus an เบิกของ (unbilled+unpaid, grouped by product) table.
- **📋 ประวัติทั้งหมด**: full history / bulk-edit view. Editing qty/paid columns in the `st.data_editor` is diffed against the original row and turned into new `partial_events` (never a direct field overwrite, preserving audit trail) — only customer/product/bill&pay-status edits go through `db.update_transaction` directly.
- **🚚 ประวัติการส่ง**: syncs delivery status (`iship_api.get_shipment_statuses` → `db.update_delivery_statuses`) and COD-transferred status (`iship_api.get_cod_transfers` → `db.mark_cod_transferred`/`mark_cod_paid`); can resend to iShip (repopulates the shared `_iship_carrier_select` dialog in `app.py`) or reprint a label; manual (non-iShip) shipments reconstruct box/COD details by regex-parsing a `[กล่อง: ...]` tag stashed in `notes` (no structured box table for manual shipments).
- **Key formulas**: outstanding = `total_amount − total_paid` / `qty − total_received` (`db.get_transaction_balance`), summed across `partial_events` unless `pay_status` is already `จ่ายแล้ว`/`COD จ่ายแล้ว` (then treated as fully paid/received). `db.split_and_open_bill(txn_id, qty_to_open)` shrinks a ฝากของ row to the billed qty (marks เปิดบิลแล้ว) and inserts a sibling row for the remainder (still ยังไม่เปิดบิล). `ui_helpers._bills_from_df()` groups a transactions dataframe by `เลขที่บิล` (total/owed/pending-qty/is_paid/is_billed/pv_unbilled) — reused by ยอดค้าง, บัตรลูกค้า, and the shared print panel. `ui_helpers._render_bill_panel()` is the one shared print/LINE-summary template used for both single-bill and "รวมทุกบิล" prints — it detects shipped bills via a `[ส่งพัสดุ|carrier|postcode|น้ำหนัก=Xkg|ค่าส่ง=Y]` tag embedded in `หมายเหตุ`.
- **COD note**: COD amounts are excluded from "ค้างจ่าย"/LINE outstanding messages (tracked separately as owed_cod) since they're settled at delivery, not invoiced.

### 💵 การเงิน (`fin_ui.py`)

Two sub-tabs: **💰 ยอดขาย** and **📑 ใบเสร็จ/เคลม VAT**. The ภาษีซื้อ-ขาย feature described as "wishlist, not yet implemented" in earlier notes **is now implemented** — do not treat it as pending.

- **Daily entries** (`finance_daily` table, one row/day via delete+insert upsert): `transfer_amount` (โอนให้บริษัท), `sales_amount` (ยอดขาย รวม VAT), `po_amount` (PO สั่งของ, ไม่รวม VAT), `registration_fee`, `bv_amount`, `stock_value` (opening stock, set once via "เปิดเดือนใหม่"), `adjustment` (carry-forward), `notes`.
- **Running formulas** (`db.get_finance_df()`): `net = Σ(transfer + bv + adjustment) − Σ(sales + registration_fee)` (ยอดค้างโอน vs. เงินโอนเกิน); `auto_stock = opening_stock + Σ(po_amount) − Σ(sales_amount/1.07)`; **order credit limit** `สิทธิ์สั่งของ = (1,100,000 + net)/1.07 − auto_stock` — note the hardcoded ฿1.1M ceiling.
- **VAT**: ภาษีขาย (output VAT) = `sales_amount − sales_amount/1.07`; ภาษีซื้อ (input VAT) = `po_amount × 0.07`; net = output − input ("ต้องจ่าย"/"ขอคืนได้"). Separately, commission VAT claim = `commission_amount × 0.07`, tracked in `commission_records.vat_claim_amount`.
- **Commission records** (`commission_records`, one row/period `YYYY-MM`): commission amount, WHT (withholding tax, default 3%), net amount, auto-incrementing receipt numbering per Thai Buddhist year (recomputed by scanning prior records, not a DB sequence), VAT-claim doc tracking fields. `company_info` table stores TBY + HQ tax-ID/address printed on receipts.
- **Printing**: `_render_receipt_html` builds a full A4 ใบเสร็จรับเงิน/ใบกำกับภาษี (incl. a Thai-baht-to-words converter), rendered via `components.html` + `window.print()` — no server-side PDF library.
- `commission_rls_fix.sql` (repo root) disables RLS on `commission_records`/`company_info` — these tables default to RLS-enabled-with-no-policy when created via the Supabase Table Editor, which blocks all inserts since the app has no per-user auth (single shared `SUPABASE_KEY`).

### 🏠 หน้าแรก (`dashboard_ui.py`)

Today's sales total/count, total ค้างจ่าย + customer count, COD-pending count/amount, PV รอเปิดบิล, and (if `finance_daily` has data) remaining order credit. Below that: a COD tracking table (💛 รอรับ COD / ✅ รับแล้วยังไม่เปิดบิล, refreshable via `iship_api.get_cod_transfers`), shipments idle >3 days with no COD, and shipments marked ตีกลับ/ยกเลิก.

### 📦 สต๊อก (`stock_ui.py`)

**สรุปสต๊อก**: per-product row combines คอม (`qty_system`, keyed-in count), นับจริง (`qty_physical`), เบิก (unbilled-received qty), ฝาก (billed-not-received qty); `ส่วนต่าง = คอม − นับจริง + ฝาก − เบิก` flags 🔴เกิน/🟡ขาด/✅ตรง. **ของฝาก**: per-customer/per-product breakdown of items billed but not yet physically received (`เปิดบิลแล้ว` + `ค้างรับ > 0` rows from `get_outstanding_df()`).

### 🛒 E-commerce (`ecom_ui.py`)

Fully wired Shopee flow: OAuth connect (auth URL + CSRF `state` round-trip handled in `app.py`'s query-param callback) → per-shop token refresh-on-sync → order/item sync into an `ecommerce_sales`-style table → view rollups by product/date range → map unmapped Shopee `item_id`s to internal `product_id`s.

### ⚙️ จัดการข้อมูล (`master_data_ui.py`)

Products/customers/addresses/box-size presets editable via `st.data_editor` (`num_rows="dynamic"`) across 4 sub-tabs (🏷️ สินค้า, 👤 ลูกค้า, 📍 ที่อยู่, 📐 ขนาดกล่อง). The 📐 ขนาดกล่อง sub-tab is the single source of truth for Bulky-carrier box-size presets (`box_presets` table, `db.get_box_presets()`/`db.replace_box_presets()`) — `app.py`'s carrier-select dialog and `record_ui.py`'s manual label printer only *read* this list (`ui_helpers.get_bulky_presets()`), no editing at point of use anymore. Also: full-table ZIP backup download and a monthly sales CSV export (`db.get_all_transactions_df()` filtered by year/month).

## database.py Patterns

**Cache invalidation**: `_clear_transaction_caches()` clears all transaction-related caches at once (`get_all_transactions_df`, `get_outstanding_df`, `get_bill_summaries`, `get_unbilled_pv_summary`, `get_unbilled_received_qty_by_product`, `get_billed_not_received_qty_by_product`). Every mutation must call it. Other cached reads worth knowing about: `get_products`/`get_customers` (5 min), `_all_customer_addresses` (2 min), `get_customer_ledger`/`get_today_transactions`/`get_pending_receipts_for_customer`/`bill_has_partial_events` (~1 min), `get_finance_df`/`get_finance_summary`/`get_bill_list`/`get_latest_stock_counts`/`get_stock_deposits` (2 min), `get_commission_records`/`get_commission_record` (1 min), `get_company_info` (5 min).

**Retry wrapper**: All Supabase calls should go through `_retry(fn, attempts=2, delay=0.5)` to handle transient network errors.

**PostgREST `.in_()` limit**: URL length caps out around 50 IDs. All `.in_()` queries are batched in chunks of 50. Do not increase this — PostgREST will silently fail or return HTTP 414.

**"Upsert" pattern for daily/period tables**: `finance_daily` and `commission_records` don't use real Postgres upsert — mutations delete the existing row for that key (`entry_date`/`period`) then insert the new one.

**`split_and_open_bill(transaction_id, qty_to_bill)`**: splits a ฝากของ transaction into two rows (billed qty vs. remaining), then marks the new row as เปิดบิลแล้ว.

**Corrections preserve audit trail**: bulk-edit flows (ประวัติทั้งหมด) never overwrite `qty_received`/`amount_paid` directly — they insert a new `partial_events` delta row so history stays reconstructable.

## Key Patterns

**Session state for widgets**: Streamlit widgets can't have their key set after rendering. Use staging keys (e.g., `_fsp_dt`, `_fr_dt`) that are applied to widget keys BEFORE the widget renders on the next rerun.

**Cart persistence**: `st.data_editor` stores only edit diffs relative to its initial DataFrame. Always keep the same base DataFrame in `st.session_state["_cart_base"]` across reruns — never re-initialize with an empty DataFrame while the user is mid-entry. Editor keys are version-suffixed (e.g. `m_cart_{version}`) so a full reset is done by bumping the version and popping the old key, not by clearing the DataFrame in place.

**Address autocomplete**: postcode→tambon and tambon→postcode both live in `ui_helpers.py` (`_postcode_suggest`, `_tambon_selectbox`), backed by `thai_address._load_tambon_index()` with `bangkok_addresses.py` as a fallback for ambiguous/Bangkok-adjacent postcodes.

**COD calculation**: `collect = total_amt + ship_fee + cod_fee` where `cod_fee = ceil((total_amt + ship_fee) × 3.21%)`, editable via a manual override.

**Customer IDs**: Always `C-NNN` format (e.g., `C-014`). Quick-add (in บันทึกขาย and จัดการข้อมูล) auto-generates the next C-NNN by scanning existing IDs for the max number.

**Bill numbers**: Format `YYMMDD-NNN` (e.g., `260427-001`). Generated by `db.get_next_bill_no(date_str)`. Column `bill_no` was added to `transactions` via ALTER TABLE — not in `supabase_setup.sql`.

**Shared iShip dialogs**: the carrier-select and success dialogs are defined once in `app.py` (`@st.dialog`) and driven purely by session-state (`_iship_carrier_select`, `_iship_success_info`) so any tab (บันทึกขาย, ส่งของ, ประวัติการส่ง resend) can trigger them by populating those keys and calling `st.rerun()`.

## Database Schema Key Points

- `transactions`: one row = one product line. Multiple rows share the same `bill_no`.
- `partial_events`: records each payment/receipt event against a transaction.
- `customer_addresses`: separate table, one customer → many addresses.
- `shipments`: records iShip shipments with `items` as JSONB.
- `pay_status` CHECK includes `'COD'` (added via ALTER TABLE, not in setup SQL).
- `finance_daily`: one row per calendar date — daily company-transfer/sales/PO/BV entries (see การเงิน above).
- `commission_records`: one row per period (`YYYY-MM`) — commission/WHT/receipt/VAT-claim tracking. RLS must be disabled (`commission_rls_fix.sql`) or inserts fail.
- `company_info`: single-row(ish) table of TBY + HQ tax-ID/address used on printed receipts. Same RLS caveat as `commission_records`.
- `box_presets`: box-size presets (name/length_cm/width_cm/height_cm) for Bulky-carrier shipping and manual label printing. Managed only in ⚙️ จัดการข้อมูล → 📐 ขนาดกล่อง (`db.replace_box_presets()` does a full delete+reinsert on save); everywhere else just reads via `ui_helpers.get_bulky_presets()`. Same RLS caveat — see `box_presets_setup.sql`.
- Shopee tables (names inferred from `database.py` usage, not yet formalized in a setup SQL): ecommerce shops (OAuth tokens), ecommerce sales (synced order items), ecommerce product map (platform SKU → internal `product_id`).

## LINE OA Integration

Customers register by texting `สมัคร 0812345678` to the LINE OA. A Google Apps Script (GAS) webhook (`gas_line_webhook.js`) handles this, queries Supabase for the matching phone number, and writes `line_user_id` back to the `customers` row.

Once `line_user_id` is set, the app can call `line_api.push_tracking()` after a successful iShip shipment, `push_outstanding()`/`push_bill_summary()` from รายละเอียดบิล, and `push_partial_receipt()` after partial payment/receipt — all gated on `line_api.is_configured()` and a non-empty `line_user_id` (optionally paired with a `group_id`).

Secrets needed: `LINE_CHANNEL_ACCESS_TOKEN` in Streamlit secrets (for push) and `SUPABASE_URL`/`SUPABASE_KEY` in the GAS script (for the registration webhook).

**`gas_line_webhook.js`** also handles LINE OA order-taking (bot-style conversational ordering, old-goods pickup menus, cancel buttons in every confirm menu) — this file is edited/deployed to Google Apps Script independently of the Streamlit app's git history; check its own inline comments/`LAST_ERROR` script-property debugging before assuming behavior matches what's deployed live.

## WAT Framework (existing tools/)

The `tools/` and `workflows/` directories are for separate scripting tasks unrelated to the Streamlit app. Use `uv run tools/<script>.py` (fallback: `python`). Credentials in `.env` via `python-dotenv`. Ask before creating or overwriting any workflow file.
