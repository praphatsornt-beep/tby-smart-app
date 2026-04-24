import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from datetime import date
from math import floor
import uuid
import io

import database as db
import shopee_api

st.set_page_config(page_title="TBY SMART APP", page_icon="🛍️", layout="wide")

# ── Shopee OAuth callback ────────────────────────────────────────────────────
_qp = st.query_params
if "code" in _qp and "shop_id" in _qp:
    _code    = _qp["code"]
    _shop_id = int(_qp["shop_id"])
    try:
        _tok = shopee_api.exchange_token(_shop_id, _code)
        if "access_token" in _tok:
            import datetime as _dt
            expiry = _dt.datetime.utcnow() + _dt.timedelta(seconds=_tok.get("expire_in", 14400))
            db.upsert_ecommerce_shop({
                "id":            str(_shop_id),
                "platform":      "shopee",
                "shop_name":     f"Shopee-{_shop_id}",
                "shop_id":       _shop_id,
                "access_token":  _tok["access_token"],
                "refresh_token": _tok["refresh_token"],
                "token_expiry":  expiry.isoformat(),
            })
            st.success(f"✅ เชื่อมต่อร้าน shop_id={_shop_id} สำเร็จ")
        else:
            st.error(f"❌ ได้รับ code แต่ token ผิดพลาด: {_tok.get('message','')}")
    except Exception as _e:
        st.error(f"❌ OAuth error: {_e}")
    st.query_params.clear()

def _style_status(val):
    colors = {
        "เปิดบิลแล้ว":   "background-color:#1a5c2e;color:white",
        "ยังไม่เปิดบิล": "background-color:#7c4a00;color:white",
        "จ่ายแล้ว":      "background-color:#1a5c2e;color:white",
        "ค้างจ่าย":      "background-color:#6b1a1a;color:white",
    }
    return colors.get(val, "")


st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 1.4rem; }
[data-testid="stMetricLabel"] { font-size: 0.8rem; }
</style>
""", unsafe_allow_html=True)

st.title("🛍️ TBY SMART APP")

tab1, tab2, tab3, tab5, tab6, tab7, tab_fin, tab_ecom, tab4 = st.tabs([
    "📋 บันทึกรายการ",
    "💰 จัดการออเดอร์",
    "📊 ยอดค้าง",
    "🗂️ ประวัติทั้งหมด",
    "📦 สต๊อก",
    "🖨️ พิมพ์บิล",
    "💵 การเงิน",
    "🛒 E-commerce",
    "⚙️ จัดการข้อมูล",
])



# ─────────────────────────────────────────────────────────────────────────────
# Tab 1: บันทึกรายการขาย
# ─────────────────────────────────────────────────────────────────────────────
def _parse_quick_order(text: str, products: list) -> tuple:
    product_by_id = {p["id"].upper(): p for p in products}
    found, unknown = [], []
    for token in text.strip().split():
        parts = token.rsplit("-", 1)
        if len(parts) == 2:
            code, qty_str = parts[0].upper(), parts[1]
            if qty_str.isdigit() and int(qty_str) > 0:
                p = product_by_id.get(code)
                if p:
                    found.append({"product": p, "qty": int(qty_str)})
                else:
                    unknown.append(code)
    return found, unknown


with tab1:
    st.subheader("บันทึกรายการขาย")

    products = db.get_products()
    customers = db.get_customers()

    if not products:
        st.warning("⚠️ ยังไม่มีข้อมูลสินค้า กรุณาเพิ่มสินค้าใน Tab ⚙️ ก่อน")
    elif not customers:
        st.warning("⚠️ ยังไม่มีข้อมูลลูกค้า กรุณาเพิ่มลูกค้าใน Tab ⚙️ ก่อน")
    else:
        product_map = {p["name"]: p for p in products}
        customer_map = {c["name"]: c for c in customers}

        # ── บันทึกแบบเร็ว ────────────────────────────────────────────────
        with st.expander("⚡ บันทึกแบบเร็ว — วางข้อความจากไลน์", expanded=False):
            qc1, qc2 = st.columns([2, 2])
            q_customer = qc1.selectbox("ลูกค้า", ["— เลือกลูกค้า —"] + list(customer_map.keys()), key="q_cust")
            q_date     = qc2.date_input("วันที่", value=date.today(), key="q_date")

            qs1, qs2, qs3 = st.columns(3)
            q_bill    = qs1.radio("สถานะบิล", ["เปิดบิลแล้ว", "ยังไม่เปิดบิล"], index=None, horizontal=True, key="q_bill")
            q_pay     = qs2.radio("สถานะจ่าย", ["จ่ายแล้ว", "ค้างจ่าย"], index=None, horizontal=True, key="q_pay")
            q_receipt = qs3.radio("สถานะของ", ["รับของแล้ว", "ฝากของ"], index=None, horizontal=True, key="q_receipt")

            q_text = st.text_area(
                "วางรายการสินค้า (รหัส-จำนวน คั่นด้วยเว้นวรรค)",
                placeholder="เช่น: tf2581-38 ty2006-1 rb2306-1 tu3315-1",
                height=80, key="q_text",
            )

            if st.button("🔍 ดูตัวอย่าง", key="q_preview"):
                st.session_state["q_parsed"] = True

            if st.session_state.get("q_parsed") and q_text.strip():
                found, unknown = _parse_quick_order(q_text, products)
                if unknown:
                    st.error(f"❌ รหัสไม่พบ: {', '.join(unknown)}")
                if found:
                    preview_rows = [{
                        "รหัส":      item["product"]["id"],
                        "ชื่อสินค้า": item["product"]["name"],
                        "จำนวน":    item["qty"],
                        "ราคา/ชิ้น": float(item["product"]["price"]),
                        "ยอดรวม":   float(item["product"]["price"]) * item["qty"],
                        "PV":        float(item["product"]["points_per_unit"]) * item["qty"],
                    } for item in found]
                    prev_df = pd.DataFrame(preview_rows)
                    st.dataframe(prev_df.style.format({
                        "ราคา/ชิ้น": "{:,.0f}", "ยอดรวม": "{:,.0f}", "PV": "{:.0f}",
                    }), use_container_width=True, hide_index=True)
                    pc1, pc2, pc3 = st.columns(3)
                    pc1.metric("รวมรายการ", f"{len(found)} สินค้า")
                    pc2.metric("ยอดรวม", f"{prev_df['ยอดรวม'].sum():,.0f} บาท")
                    pc3.metric("PV รวม", f"{prev_df['PV'].sum():.0f}")

                    q_errors = []
                    if q_customer == "— เลือกลูกค้า —": q_errors.append("กรุณาเลือกลูกค้า")
                    if q_bill is None:    q_errors.append("กรุณาเลือกสถานะบิล")
                    if q_pay is None:     q_errors.append("กรุณาเลือกสถานะจ่าย")
                    if q_receipt is None: q_errors.append("กรุณาเลือกสถานะของ")

                    if q_errors:
                        for e in q_errors: st.warning(e)
                    else:
                        if st.button(f"💾 บันทึกทั้งหมด {len(found)} รายการ", key="q_submit", type="primary", use_container_width=True):
                            customer = customer_map[q_customer]
                            receive_now = q_receipt == "รับของแล้ว"
                            for item in found:
                                p   = item["product"]
                                qty = item["qty"]
                                db.insert_transaction({
                                    "id":                  str(uuid.uuid4()),
                                    "date":                str(q_date),
                                    "customer_id":         customer["id"],
                                    "product_id":          p["id"],
                                    "product_name":        p["name"],
                                    "qty":                 qty,
                                    "price_per_unit":      float(p["price"]),
                                    "points_per_unit":     float(p["points_per_unit"]),
                                    "total_amount":        float(p["price"]) * qty,
                                    "initial_qty_received": qty if receive_now else 0,
                                    "transaction_type":    "เบิกของก่อน" if q_bill == "ยังไม่เปิดบิล" and receive_now else "ขายปกติ",
                                    "bill_status":         q_bill,
                                    "pay_status":          q_pay,
                                    "notes":               "",
                                })
                            st.success(f"✅ บันทึก {len(found)} รายการแล้ว")
                            st.session_state["q_parsed"] = False
                            st.rerun()

        st.divider()
        # ── บันทึกทีละรายการ ─────────────────────────────────────────────
        with st.form("new_transaction", clear_on_submit=True):
            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                customer_label = st.selectbox(
                    "ลูกค้า",
                    ["— เลือกลูกค้า —"] + list(customer_map.keys()),
                )
            with col2:
                product_label = st.selectbox(
                    "สินค้า",
                    ["— เลือกสินค้า —"] + list(product_map.keys()),
                )
            with col3:
                qty = st.number_input("จำนวน", min_value=1, value=1, step=1)

            if product_label != "— เลือกสินค้า —":
                selected_product = product_map[product_label]
                total = float(selected_product["price"]) * qty
                total_pts = float(selected_product["points_per_unit"]) * qty
                c1, c2, c3 = st.columns(3)
                c1.metric("ราคา/ชิ้น", f"{float(selected_product['price']):,.0f} บาท")
                c2.metric("ยอดรวม", f"{total:,.0f} บาท")
                c3.metric("PV รวม", f"{total_pts:.0f}")

            sc1, sc2, sc3 = st.columns(3)
            with sc1:
                bill_status = st.radio("สถานะบิล", ["เปิดบิลแล้ว", "ยังไม่เปิดบิล"], index=None, horizontal=True)
            with sc2:
                pay_status = st.radio("สถานะจ่าย", ["จ่ายแล้ว", "ค้างจ่าย"], index=None, horizontal=True)
            with sc3:
                receipt_status = st.radio("สถานะของ", ["รับของแล้ว", "ฝากของ"], index=None, horizontal=True)

            col4, col5 = st.columns([3, 1])
            with col4:
                notes = st.text_input("หมายเหตุ (ถ้ามี)")
            with col5:
                txn_date = st.date_input("วันที่", value=date.today())

            submitted = st.form_submit_button("💾 บันทึก", use_container_width=True, type="primary")

            if submitted:
                errors = []
                if customer_label == "— เลือกลูกค้า —":
                    errors.append("กรุณาเลือกลูกค้า")
                if product_label == "— เลือกสินค้า —":
                    errors.append("กรุณาเลือกสินค้า")
                if bill_status is None:
                    errors.append("กรุณาเลือกสถานะบิล")
                if pay_status is None:
                    errors.append("กรุณาเลือกสถานะจ่าย")
                if receipt_status is None:
                    errors.append("กรุณาเลือกสถานะของ")
                if errors:
                    for e in errors:
                        st.error(e)
                else:
                    selected_product = product_map[product_label]
                    total = float(selected_product["price"]) * qty
                    receive_now = receipt_status == "รับของแล้ว"
                    initial_qty_received = int(qty) if receive_now else 0
                    txn_type = "เบิกของก่อน" if bill_status == "ยังไม่เปิดบิล" and receive_now else "ขายปกติ"
                    customer = customer_map[customer_label]
                    db.insert_transaction({
                        "id": str(uuid.uuid4()),
                        "date": str(txn_date),
                        "customer_id": customer["id"],
                        "product_id": selected_product["id"],
                        "product_name": selected_product["name"],
                        "qty": int(qty),
                        "price_per_unit": float(selected_product["price"]),
                        "points_per_unit": float(selected_product["points_per_unit"]),
                        "total_amount": total,
                        "initial_qty_received": initial_qty_received,
                        "transaction_type": txn_type,
                        "bill_status": bill_status,
                        "pay_status": pay_status,
                        "notes": notes,
                    })
                    st.success(f"✅ บันทึกแล้ว: {selected_product['name']} × {qty} ชิ้น = {total:,.0f} บาท")


# ─────────────────────────────────────────────────────────────────────────────
# Tab 2: รับของ / จ่ายเงิน / เปิดบิล
# ─────────────────────────────────────────────────────────────────────────────
with tab2:
    st.subheader("รับของ / จ่ายเงิน / เปิดบิล")

    customers = db.get_customers()
    if not customers:
        st.info("ยังไม่มีข้อมูล")
    else:
        customer_options = {c["name"]: c for c in customers}
        sel_customer_label = st.selectbox(
            "เลือกลูกค้า",
            ["— เลือกลูกค้า —"] + list(customer_options.keys()),
            key="tab2_customer",
        )

        if sel_customer_label != "— เลือกลูกค้า —":
            sel_customer = customer_options[sel_customer_label]

            # Clear checkboxes when customer changes
            prev_cust = st.session_state.get("tab2_prev_cust")
            if prev_cust != sel_customer_label:
                for k in list(st.session_state.keys()):
                    if k.startswith("chk_"):
                        del st.session_state[k]
                st.session_state["tab2_prev_cust"] = sel_customer_label

            outstanding_df = db.get_outstanding_df(customer_id=sel_customer["id"])

            if outstanding_df.empty:
                st.success(f"✅ {sel_customer['name']} ไม่มียอดค้าง")
            else:
                # ── Select all / deselect all ──────────────────────────────
                txn_ids_all = outstanding_df["id"].tolist()
                ctl1, ctl2, ctl3 = st.columns([2, 2, 3])
                if ctl1.button("เลือกทั้งหมด", key="tab2_sel_all"):
                    for tid in txn_ids_all:
                        st.session_state[f"chk_{tid}"] = True
                    st.rerun()
                if ctl2.button("ยกเลิกทั้งหมด", key="tab2_desel_all"):
                    for tid in txn_ids_all:
                        st.session_state[f"chk_{tid}"] = False
                    st.rerun()

                # ── Render one checkbox row per transaction ─────────────────
                st.divider()
                for _, row in outstanding_df.iterrows():
                    txn_id = row["id"]
                    bill_icon = "🟡" if row["สถานะบิล"] == "ยังไม่เปิดบิล" else "🟢"
                    label = f"{bill_icon} **{row['สินค้า']}** × {row['สั่ง']}"
                    if row["ค้างจ่าย"] > 0.01:
                        label += f"  —  ค้างจ่าย **{row['ค้างจ่าย']:,.0f}** บาท"
                    if row["ค้างรับ"] > 0:
                        label += f"  —  ค้างรับ **{row['ค้างรับ']}** ชิ้น"
                    st.checkbox(label, key=f"chk_{txn_id}")

                # Collect currently checked IDs
                selected_ids = [tid for tid in txn_ids_all
                                if st.session_state.get(f"chk_{tid}", False)]

                # Show running total
                if selected_ids:
                    sel_rows = outstanding_df[outstanding_df["id"].isin(selected_ids)]
                    total_selected = sel_rows["ค้างจ่าย"].sum()
                    ctl3.metric("ยอดที่เลือก", f"{total_selected:,.0f} บาท")

                st.divider()

                # ── Action panel ───────────────────────────────────────────
                if len(selected_ids) == 0:
                    st.info("☝️ เลือกรายการด้านบนเพื่อดำเนินการ")

                elif len(selected_ids) == 1:
                    # ── Single: full action panel ─────────────────────────
                    txn_id  = selected_ids[0]
                    balance = db.get_transaction_balance(txn_id)
                    txn     = balance["transaction"]

                    sel_row = outstanding_df[outstanding_df["id"] == txn_id].iloc[0]
                    st.caption(f"วันที่ {sel_row['วันที่']}  |  ราคา {float(txn['price_per_unit']):,.0f} บาท/ชิ้น  |  ยอดรวม {float(txn['total_amount']):,.0f} บาท")
                    mc1, mc2, mc3, mc4 = st.columns(4)
                    mc1.metric("จ่ายแล้ว", f"{balance['total_paid']:,.0f} บาท")
                    mc2.metric("ค้างจ่าย", f"{balance['outstanding_amount']:,.0f} บาท")
                    mc3.metric("รับแล้ว",  f"{balance['total_received']} ชิ้น")
                    mc4.metric("ค้างรับ",  f"{balance['outstanding_qty']} ชิ้น")

                    st.divider()

                    is_unbilled = txn["bill_status"] == "ยังไม่เปิดบิล"
                    radio_opts  = (["📄 เปิดบิล"] if is_unbilled else []) + ["💵 จ่ายเงิน", "📦 รับของ", "💵+📦 จ่ายเงิน + รับของ"]
                    action = st.radio("บันทึก", radio_opts, horizontal=True, key=f"etype_{txn_id}")

                    if action == "📄 เปิดบิล":
                        with st.form(f"bill_{txn_id}", clear_on_submit=True):
                            bc1, bc2 = st.columns([3, 1])
                            qty_to_open = bc1.number_input(
                                "จำนวนที่เปิดบิล", min_value=1,
                                max_value=int(txn["qty"]), value=int(txn["qty"]), step=1,
                            )
                            bc2.write("")
                            submit_bill = bc2.form_submit_button("📄 เปิดบิล", use_container_width=True, type="primary")
                        if submit_bill:
                            if qty_to_open == int(txn["qty"]):
                                db.update_transaction_status(txn_id, bill_status="เปิดบิลแล้ว")
                            else:
                                db.split_and_open_bill(txn_id, qty_to_open)
                            st.rerun()
                    else:
                        evt_map  = {"💵 จ่ายเงิน": "จ่ายเงิน", "📦 รับของ": "รับของ", "💵+📦 จ่ายเงิน + รับของ": "จ่ายเงิน + รับของ"}
                        evt_type = evt_map[action]
                        with st.form(f"evt_{txn_id}", clear_on_submit=True):
                            fc1, fc2, fc3 = st.columns([2, 2, 1])
                            amount_paid  = fc1.number_input("เงินที่จ่าย (บาท)", min_value=0.0, step=100.0,
                                                            disabled=(evt_type == "รับของ"))
                            qty_received = fc2.number_input("จำนวนที่รับ (ชิ้น)", min_value=0, step=1,
                                                            disabled=(evt_type == "จ่ายเงิน"))
                            event_date   = fc3.date_input("วันที่", value=date.today())
                            event_notes  = st.text_input("หมายเหตุ", key=f"enotes_{txn_id}")
                            submit_evt   = st.form_submit_button("💾 บันทึก", use_container_width=True, type="primary")

                        if submit_evt:
                            error = None
                            if evt_type in ("รับของ", "จ่ายเงิน + รับของ") and qty_received > 0:
                                new_paid = balance["total_paid"] + amount_paid
                                price    = float(txn["price_per_unit"])
                                max_ok   = floor(new_paid / price) if price > 0 else 0
                                if balance["total_received"] + qty_received > max_ok:
                                    can   = max(0, max_ok - balance["total_received"])
                                    error = f"❌ รับได้สูงสุด {can} ชิ้น (จ่ายแล้ว {new_paid:,.0f} บาท)"
                            if error:
                                st.error(error)
                            else:
                                db.insert_partial_event({
                                    "id": str(uuid.uuid4()),
                                    "date": str(event_date),
                                    "transaction_id": txn_id,
                                    "qty_received": int(qty_received),
                                    "amount_paid":  float(amount_paid),
                                    "event_type":   evt_type,
                                    "notes":        event_notes,
                                })
                                st.success("✅ บันทึกแล้ว")
                                st.rerun()

                    # ยกเลิกบิล (เฉพาะที่เปิดบิลแล้ว)
                    if not is_unbilled:
                        st.divider()
                        if st.button("↩️ ยกเลิกบิล", key=f"cancel_{txn_id}"):
                            db.update_transaction_status(txn_id, bill_status="ยังไม่เปิดบิล")
                            st.rerun()

                else:
                    # ── Multi: proportional payment ───────────────────────
                    sel_rows = outstanding_df[outstanding_df["id"].isin(selected_ids)]
                    total_owed = sel_rows["ค้างจ่าย"].sum()

                    st.write(f"**เลือก {len(selected_ids)} รายการ — ยอดค้างรวม {total_owed:,.0f} บาท**")
                    st.dataframe(
                        sel_rows[["สินค้า", "สั่ง", "ค้างจ่าย", "สถานะบิล"]].style.format({"ค้างจ่าย": "{:,.0f}"}),
                        use_container_width=True, hide_index=True,
                    )

                    with st.form("multi_pay_form", clear_on_submit=True):
                        mp1, mp2, mp3 = st.columns([2, 2, 1])
                        payment_amount = mp1.number_input(
                            "จำนวนที่จ่าย (บาท)", min_value=0.0, step=100.0,
                            value=float(total_owed),
                        )
                        mp_notes = mp2.text_input("หมายเหตุ")
                        mp_date  = mp3.date_input("วันที่", value=date.today())
                        submit_multi = st.form_submit_button(
                            "💾 บันทึกการจ่ายเงิน", use_container_width=True, type="primary",
                        )

                    if submit_multi:
                        if total_owed <= 0:
                            st.error("ไม่มียอดค้างในรายการที่เลือก")
                        else:
                            for _, sel_row in sel_rows.iterrows():
                                ratio            = sel_row["ค้างจ่าย"] / total_owed
                                amount_for_this  = round(payment_amount * ratio, 2)
                                if amount_for_this > 0:
                                    db.insert_partial_event({
                                        "id":             str(uuid.uuid4()),
                                        "date":           str(mp_date),
                                        "transaction_id": sel_row["id"],
                                        "qty_received":   0,
                                        "amount_paid":    amount_for_this,
                                        "event_type":     "จ่ายเงิน",
                                        "notes":          mp_notes,
                                    })
                            st.success(f"✅ บันทึกการจ่าย {payment_amount:,.0f} บาท ครอบ {len(selected_ids)} รายการแล้ว")
                            for tid in txn_ids_all:
                                st.session_state[f"chk_{tid}"] = False
                            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Tab 3: ยอดค้างลูกค้า
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    st.subheader("ยอดค้างลูกค้า")

    unbilled = db.get_unbilled_pv_summary()
    if unbilled["count"] > 0:
        ub1, ub2, ub3 = st.columns(3)
        ub1.metric("ยังไม่เปิดบิล", f"{unbilled['count']} รายการ")
        ub2.metric("PV รอเปิดบิล", f"{unbilled['total_pv']:,.0f}")
        ub3.metric("ยอดเงินรอเปิดบิล", f"{unbilled['total_amount']:,.0f} บาท")
        st.divider()

    customers = db.get_customers()
    filter_opts = ["ทั้งหมด"] + [c["name"] for c in customers]
    filter_sel = st.selectbox("กรองตามลูกค้า", filter_opts, key="tab3_filter")

    cid_filter = None
    if filter_sel != "ทั้งหมด":
        cid_filter = next(c["id"] for c in customers if c["name"] == filter_sel)

    outstanding_df = db.get_outstanding_df(customer_id=cid_filter)

    if outstanding_df.empty:
        st.success("✅ ไม่มียอดค้าง")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("รายการค้าง", len(outstanding_df))
        c2.metric("ยอดเงินค้างรวม", f"{outstanding_df['ค้างจ่าย'].sum():,.0f} บาท")
        c3.metric("จำนวนค้างรับรวม", f"{int(outstanding_df['ค้างรับ'].sum()):,} ชิ้น")

        if cid_filter is None:
            # แสดงรายละเอียดต่อลูกค้า
            st.divider()
            for customer_name, grp in outstanding_df.groupby("ลูกค้า"):
                owed = grp["ค้างจ่าย"].sum()
                pending_qty = int(grp["ค้างรับ"].sum())
                label = f"**{customer_name}**  —  ค้างจ่าย {owed:,.0f} บาท  |  ค้างรับ {pending_qty} ชิ้น"
                with st.expander(label, expanded=True):
                    display_cols = ["วันที่", "สินค้า", "สั่ง", "รับแล้ว", "ค้างรับ", "ยอดรวม", "จ่ายแล้ว", "ค้างจ่าย", "สถานะบิล", "ประเภท"]
                    st.dataframe(
                        grp[display_cols].style.format({
                            "ยอดรวม": "{:,.0f}", "จ่ายแล้ว": "{:,.0f}", "ค้างจ่าย": "{:,.0f}",
                        }).map(_style_status, subset=["สถานะบิล"]),
                        use_container_width=True,
                        hide_index=True,
                    )
                    tc1, tc2, tc3 = st.columns(3)
                    tc1.metric("ยอดรวมทั้งหมด", f"{grp['ยอดรวม'].sum():,.0f} บาท")
                    tc2.metric("จ่ายแล้วรวม", f"{grp['จ่ายแล้ว'].sum():,.0f} บาท")
                    tc3.metric("ค้างจ่ายรวม", f"{owed:,.0f} บาท")

                    st.divider()
                    del_opts = {
                        f"{r['วันที่']} — {r['สินค้า']} ×{r['สั่ง']}": r["id"]
                        for _, r in grp.iterrows()
                    }
                    dcol1, dcol2, dcol3 = st.columns([4, 1, 1])
                    with dcol1:
                        del_sel = st.selectbox("เลือกรายการที่จะลบ", list(del_opts.keys()),
                                               key=f"delsel_{customer_name}")
                    with dcol2:
                        st.write("")
                        confirm = st.checkbox("ยืนยัน", key=f"delchk_{customer_name}")
                    with dcol3:
                        st.write("")
                        if st.button("🗑️ ลบ", key=f"delbtn_{customer_name}",
                                     disabled=not confirm, type="secondary"):
                            db.delete_transaction(del_opts[del_sel])
                            st.rerun()
        else:
            # กรองลูกค้าเดียว — แสดงตารางปกติ
            unbilled_df = outstanding_df[outstanding_df["สถานะบิล"] == "ยังไม่เปิดบิล"]
            tc1, tc2 = st.columns(2)
            tc1.metric("ยังไม่เปิดบิล", f"{len(unbilled_df)} รายการ")
            tc2.metric("PV รอเปิดบิล", f"{unbilled_df['PV รวม'].sum():,.0f}")

            if not unbilled_df.empty:
                with st.expander(f"📄 รายการยังไม่เปิดบิล ({len(unbilled_df)} รายการ)"):
                    st.dataframe(
                        unbilled_df[["วันที่", "สินค้า", "สั่ง", "ยอดรวม", "PV รวม"]].style.format({
                            "ยอดรวม": "{:,.0f}", "PV รวม": "{:.0f}",
                        }),
                        use_container_width=True,
                        hide_index=True,
                    )

            st.divider()
            display_cols2 = ["วันที่", "สินค้า", "สั่ง", "รับแล้ว", "ค้างรับ", "ยอดรวม", "จ่ายแล้ว", "ค้างจ่าย", "PV รวม", "สถานะบิล"]
            st.dataframe(
                outstanding_df[display_cols2].style.format({
                    "ยอดรวม": "{:,.0f}", "จ่ายแล้ว": "{:,.0f}", "ค้างจ่าย": "{:,.0f}", "PV รวม": "{:.0f}",
                }).map(_style_status, subset=["สถานะบิล"]),
                use_container_width=True,
                hide_index=True,
            )
            st.divider()
            del_opts2 = {
                f"{r['วันที่']} — {r['สินค้า']} ×{r['สั่ง']}": r["id"]
                for _, r in outstanding_df.iterrows()
            }
            dcol1, dcol2, dcol3 = st.columns([4, 1, 1])
            with dcol1:
                del_sel2 = st.selectbox("เลือกรายการที่จะลบ", list(del_opts2.keys()), key="delsel_single")
            with dcol2:
                st.write("")
                confirm2 = st.checkbox("ยืนยัน", key="delchk_single")
            with dcol3:
                st.write("")
                if st.button("🗑️ ลบ", key="delbtn_single", disabled=not confirm2, type="secondary"):
                    db.delete_transaction(del_opts2[del_sel2])
                    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Tab 4: จัดการข้อมูลหลัก
# ─────────────────────────────────────────────────────────────────────────────
with tab4:
    st.subheader("จัดการข้อมูลหลัก")

    sub1, sub2 = st.tabs(["🏷️ สินค้า", "👤 ลูกค้า"])

    with sub1:
        products = db.get_products()

        prod_cols = ["id", "name", "price", "points_per_unit", "bv_per_unit", "weight_grams"]
        col_rename = {
            "id": "รหัส", "name": "ชื่อสินค้า", "price": "ราคา (บาท)",
            "points_per_unit": "PV/หน่วย", "bv_per_unit": "BV/หน่วย", "weight_grams": "น้ำหนัก (g)",
        }
        if products:
            prod_df = pd.DataFrame(products)[prod_cols].rename(columns=col_rename)
        else:
            prod_df = pd.DataFrame(columns=list(col_rename.values()))

        st.write("**แก้ไขหรือเพิ่มสินค้า** — แก้ในตารางได้โดยตรง กด `+` ที่มุมล่างขวาเพื่อเพิ่มแถวใหม่")
        edited_prod_df = st.data_editor(
            prod_df,
            num_rows="dynamic",
            use_container_width=True,
            key="prod_editor",
            column_config={
                "รหัส":        st.column_config.TextColumn("รหัส", required=True),
                "ชื่อสินค้า":  st.column_config.TextColumn("ชื่อสินค้า", required=True),
                "ราคา (บาท)":  st.column_config.NumberColumn("ราคา (บาท)", min_value=0, step=10.0, format="%.2f"),
                "PV/หน่วย":    st.column_config.NumberColumn("PV/หน่วย",   min_value=0, step=1.0,  format="%.2f"),
                "BV/หน่วย":    st.column_config.NumberColumn("BV/หน่วย",   min_value=0, step=1.0,  format="%.2f"),
                "น้ำหนัก (g)": st.column_config.NumberColumn("น้ำหนัก (g)", min_value=0, step=10.0, format="%.0f"),
            },
        )
        if st.button("💾 บันทึกทั้งหมด", key="save_prod_editor", use_container_width=True, type="primary"):
            valid = edited_prod_df.dropna(subset=["รหัส", "ชื่อสินค้า"])
            valid = valid[valid["รหัส"].astype(str).str.strip() != ""]
            if valid.empty:
                st.error("ไม่มีข้อมูลที่จะบันทึก")
            else:
                for _, row in valid.iterrows():
                    db.upsert_product({
                        "id":              str(row["รหัส"]).strip(),
                        "name":            str(row["ชื่อสินค้า"]).strip(),
                        "price":           float(row["ราคา (บาท)"]  or 0),
                        "points_per_unit": float(row["PV/หน่วย"]    or 0),
                        "bv_per_unit":     float(row["BV/หน่วย"]    or 0),
                        "weight_grams":    float(row["น้ำหนัก (g)"] or 0),
                    })
                st.success(f"✅ บันทึก {len(valid)} รายการแล้ว")
                st.rerun()

        if products:
            with st.expander("🗑️ ลบสินค้า"):
                prod_opts = {f"{p['id']} — {p['name']}": p["id"] for p in products}
                pc1, pc2, pc3 = st.columns([4, 1, 1])
                with pc1:
                    del_prod = st.selectbox("เลือกสินค้า", list(prod_opts.keys()), key="delsel_prod")
                with pc2:
                    st.write("")
                    confirm_prod = st.checkbox("ยืนยัน", key="delchk_prod")
                with pc3:
                    st.write("")
                    if st.button("🗑️ ลบ", key="delbtn_prod", disabled=not confirm_prod, type="secondary"):
                        try:
                            db.delete_product(prod_opts[del_prod])
                            st.success("✅ ลบแล้ว")
                            st.rerun()
                        except Exception:
                            st.error("❌ ลบไม่ได้ — สินค้านี้มีรายการขายอยู่")

    with sub2:
        customers = db.get_customers()
        if customers:
            cust_df = pd.DataFrame(customers)[["id", "name", "phone"]].rename(
                columns={"id": "รหัส", "name": "ชื่อลูกค้า", "phone": "เบอร์โทร"}
            )
        else:
            cust_df = pd.DataFrame(columns=["รหัส", "ชื่อลูกค้า", "เบอร์โทร"])

        st.write("**แก้ไขหรือเพิ่มลูกค้า** — แก้ในตารางได้โดยตรง กด `+` ที่มุมล่างขวาเพื่อเพิ่มแถวใหม่")
        edited_cust_df = st.data_editor(
            cust_df,
            num_rows="dynamic",
            use_container_width=True,
            key="cust_editor",
            column_config={
                "รหัส":      st.column_config.TextColumn("รหัส", required=True),
                "ชื่อลูกค้า": st.column_config.TextColumn("ชื่อลูกค้า", required=True),
                "เบอร์โทร":  st.column_config.TextColumn("เบอร์โทร"),
            },
        )
        if st.button("💾 บันทึกทั้งหมด", key="save_cust_editor", use_container_width=True, type="primary"):
            valid = edited_cust_df.dropna(subset=["รหัส", "ชื่อลูกค้า"])
            valid = valid[valid["รหัส"].astype(str).str.strip() != ""]
            if valid.empty:
                st.error("ไม่มีข้อมูลที่จะบันทึก")
            else:
                for _, row in valid.iterrows():
                    db.upsert_customer({
                        "id":    str(row["รหัส"]).strip(),
                        "name":  str(row["ชื่อลูกค้า"]).strip(),
                        "phone": str(row["เบอร์โทร"]).strip() if pd.notna(row["เบอร์โทร"]) else "",
                    })
                st.success(f"✅ บันทึก {len(valid)} รายการแล้ว")
                st.rerun()

        if customers:
            with st.expander("🗑️ ลบลูกค้า"):
                cust_opts = {f"{c['id']} — {c['name']}": c["id"] for c in customers}
                cc1, cc2, cc3 = st.columns([4, 1, 1])
                with cc1:
                    del_cust = st.selectbox("เลือกลูกค้า", list(cust_opts.keys()), key="delsel_cust")
                with cc2:
                    st.write("")
                    confirm_cust = st.checkbox("ยืนยัน", key="delchk_cust")
                with cc3:
                    st.write("")
                    if st.button("🗑️ ลบ", key="delbtn_cust", disabled=not confirm_cust, type="secondary"):
                        try:
                            db.delete_customer(cust_opts[del_cust])
                            st.success("✅ ลบแล้ว")
                            st.rerun()
                        except Exception:
                            st.error("❌ ลบไม่ได้ — ลูกค้านี้มีรายการขายอยู่")


# ─────────────────────────────────────────────────────────────────────────────
# Tab 5: ประวัติทั้งหมด
# ─────────────────────────────────────────────────────────────────────────────
with tab5:
    st.subheader("ประวัติรายการทั้งหมด")

    customers_h = db.get_customers()
    h_col1, h_col2 = st.columns(2)
    with h_col1:
        h_filter_cust = st.selectbox(
            "กรองตามลูกค้า",
            ["ทั้งหมด"] + [c["name"] for c in customers_h],
            key="hist_cust",
        )
    with h_col2:
        h_filter_status = st.selectbox(
            "กรองตามสถานะ",
            ["ทั้งหมด", "ค้างอยู่", "เคลียร์แล้ว"],
            key="hist_status",
        )

    h_cid = None
    if h_filter_cust != "ทั้งหมด":
        h_cid = next(c["id"] for c in customers_h if c["name"] == h_filter_cust)

    all_df = db.get_all_transactions_df(customer_id=h_cid)

    if not all_df.empty:
        if h_filter_status == "ค้างอยู่":
            all_df = all_df[~all_df["เคลียร์แล้ว"]]
        elif h_filter_status == "เคลียร์แล้ว":
            all_df = all_df[all_df["เคลียร์แล้ว"]]

    if all_df.empty:
        st.info("ไม่มีข้อมูล")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("รายการทั้งหมด", len(all_df))
        m2.metric("เคลียร์แล้ว", int(all_df["เคลียร์แล้ว"].sum()))
        m3.metric("ยังค้างอยู่", int((~all_df["เคลียร์แล้ว"]).sum()))

        display_cols_h = ["วันที่", "ลูกค้า", "สินค้า", "สั่ง", "รับแล้ว",
                          "ยอดรวม", "จ่ายแล้ว", "ค้างจ่าย", "ค้างรับ",
                          "สถานะบิล", "สถานะจ่าย", "หมายเหตุ"]
        show_df = all_df[display_cols_h].reset_index(drop=True)

        st.dataframe(
            show_df.style
                .format({"ยอดรวม": "{:,.0f}", "จ่ายแล้ว": "{:,.0f}", "ค้างจ่าย": "{:,.0f}"})
                .map(_style_status, subset=["สถานะบิล", "สถานะจ่าย"])
                .map(lambda v: "background-color:#6b1a1a;color:white" if isinstance(v, (int, float)) and v > 0 else "", subset=["ค้างรับ"]),
            use_container_width=True,
            hide_index=True,
        )

        st.divider()
        with st.expander("✏️ แก้ไขรายการ"):
            all_products_e = db.get_products()
            all_customers_e = db.get_customers()
            product_map_e = {p["name"]: p for p in all_products_e}
            customer_map_e = {c["name"]: c for c in all_customers_e}

            edit_opts = {
                f"{r['วันที่']}  {r['ลูกค้า']}  {r['สินค้า']} ×{r['สั่ง']}": r["id"]
                for _, r in all_df.iterrows()
            }
            edit_sel = st.selectbox("เลือกรายการที่จะแก้ไข", list(edit_opts.keys()), key="edit_sel")
            edit_txn_id = edit_opts[edit_sel]

            edit_balance = db.get_transaction_balance(edit_txn_id)
            et = edit_balance["transaction"]

            prod_names = list(product_map_e.keys())
            cust_names = list(customer_map_e.keys())
            cur_prod_idx = next((i for i, p in enumerate(all_products_e) if p["id"] == et["product_id"]), 0)
            cur_cust_idx = next((i for i, c in enumerate(all_customers_e) if c["id"] == et["customer_id"]), 0)
            cur_bill_idx = 0 if et["bill_status"] == "เปิดบิลแล้ว" else 1
            cur_pay_idx = 0 if et["pay_status"] == "จ่ายแล้ว" else 1
            cur_receipt_idx = 0 if et["initial_qty_received"] > 0 else 1

            with st.form("edit_transaction"):
                ec1, ec2, ec3 = st.columns([2, 2, 1])
                with ec1:
                    e_customer = st.selectbox("ลูกค้า", cust_names, index=cur_cust_idx)
                with ec2:
                    e_product = st.selectbox("สินค้า", prod_names, index=cur_prod_idx)
                with ec3:
                    e_qty = st.number_input("จำนวน", min_value=1, value=int(et["qty"]), step=1)

                e_sel_prod = product_map_e[e_product]
                e_total = float(e_sel_prod["price"]) * e_qty
                e_total_pts = float(e_sel_prod["points_per_unit"]) * e_qty

                em1, em2, em3 = st.columns(3)
                em1.metric("ราคา/ชิ้น", f"{float(e_sel_prod['price']):,.0f} บาท")
                em2.metric("ยอดรวม", f"{e_total:,.0f} บาท")
                em3.metric("PV รวม", f"{e_total_pts:.0f}")

                es1, es2, es3 = st.columns(3)
                with es1:
                    e_bill = st.radio("สถานะบิล", ["เปิดบิลแล้ว", "ยังไม่เปิดบิล"], index=cur_bill_idx, horizontal=True)
                with es2:
                    e_pay = st.radio("สถานะจ่าย", ["จ่ายแล้ว", "ค้างจ่าย"], index=cur_pay_idx, horizontal=True)
                with es3:
                    e_receipt = st.radio("สถานะของ", ["รับของแล้ว", "ฝากของ"], index=cur_receipt_idx, horizontal=True)

                ed1, ed2 = st.columns([3, 1])
                with ed1:
                    e_notes = st.text_input("หมายเหตุ", value=et.get("notes") or "")
                with ed2:
                    e_date = st.date_input("วันที่", value=pd.to_datetime(et["date"]).date())

                if edit_balance["total_received"] > 0 or edit_balance["total_paid"] > 0:
                    st.warning(
                        f"⚠️ รายการนี้มีการรับของ/จ่ายเงินไปแล้ว "
                        f"({edit_balance['total_received']} ชิ้น / {edit_balance['total_paid']:,.0f} บาท) "
                        f"— แก้จำนวนหรือราคาอาจทำให้ยอดไม่ตรง"
                    )

                if st.form_submit_button("💾 บันทึกการแก้ไข", use_container_width=True, type="primary"):
                    e_receive_now = e_receipt == "รับของแล้ว"
                    e_initial_qty = int(e_qty) if e_receive_now else 0
                    e_txn_type = "เบิกของก่อน" if e_bill == "ยังไม่เปิดบิล" and e_receive_now else "ขายปกติ"
                    db.update_transaction(edit_txn_id, {
                        "date": str(e_date),
                        "customer_id": customer_map_e[e_customer]["id"],
                        "product_id": e_sel_prod["id"],
                        "product_name": e_sel_prod["name"],
                        "qty": int(e_qty),
                        "price_per_unit": float(e_sel_prod["price"]),
                        "points_per_unit": float(e_sel_prod["points_per_unit"]),
                        "total_amount": e_total,
                        "initial_qty_received": e_initial_qty,
                        "transaction_type": e_txn_type,
                        "bill_status": e_bill,
                        "pay_status": e_pay,
                        "notes": e_notes,
                    })
                    st.success("✅ แก้ไขแล้ว")
                    st.rerun()

        st.divider()
        st.write("**ลบรายการ**")

        del_col1, del_col2 = st.columns([3, 1])
        with del_col1:
            h_del_opts = {
                f"{r['วันที่']}  {r['ลูกค้า']}  {r['สินค้า']} ×{r['สั่ง']}  {'✅' if all_df.loc[i,'เคลียร์แล้ว'] else '⏳'}": r["id"]
                for i, r in all_df.iterrows()
            }
            h_del_sel = st.selectbox("เลือกรายการที่จะลบ", list(h_del_opts.keys()), key="hist_del_sel")
        with del_col2:
            st.write("")
            h_confirm = st.checkbox("ยืนยัน", key="hist_del_chk")

        bcol1, bcol2 = st.columns(2)
        with bcol1:
            if st.button("🗑️ ลบรายการที่เลือก", disabled=not h_confirm,
                         use_container_width=True, key="hist_del_one"):
                db.delete_transaction(h_del_opts[h_del_sel])
                st.success("✅ ลบแล้ว")
                st.rerun()

        cleared_ids = all_df[all_df["เคลียร์แล้ว"]]["id"].tolist()
        with bcol2:
            h_confirm_bulk = st.checkbox(
                f"ยืนยันลบทั้งหมดที่เคลียร์แล้ว ({len(cleared_ids)} รายการ)",
                key="hist_bulk_chk",
                disabled=len(cleared_ids) == 0,
            )
            if st.button(
                f"🗑️ ลบทั้งหมดที่เคลียร์แล้ว ({len(cleared_ids)})",
                disabled=not h_confirm_bulk or len(cleared_ids) == 0,
                use_container_width=True,
                key="hist_del_bulk",
                type="primary",
            ):
                for tid in cleared_ids:
                    db.delete_transaction(tid)
                st.success(f"✅ ลบ {len(cleared_ids)} รายการแล้ว")
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Tab 6: สต๊อก
# ─────────────────────────────────────────────────────────────────────────────
with tab6:
    st.subheader("สรุปสต๊อก")

    products = db.get_products()
    if not products:
        st.warning("⚠️ ยังไม่มีข้อมูลสินค้า")
    else:
        latest_counts   = db.get_latest_stock_counts()
        unbilled_qty    = db.get_unbilled_received_qty_by_product()
        billed_not_rcv  = db.get_billed_not_received_qty_by_product()

        # เก็บ product_ids แยก เพื่อใช้ตอน save (ไม่พึ่ง hidden column)
        product_ids = [p["id"] for p in products]
        stock_rows  = []

        for p in products:
            pid             = p["id"]
            count           = latest_counts.get(pid, {})
            qty_system      = int(count.get("qty_system",   0) or 0)
            qty_physical    = int(count.get("qty_physical", 0) or 0)
            qty_unbilled    = unbilled_qty.get(pid, 0)
            qty_billed_wait = billed_not_rcv.get(pid, 0)
            diff = qty_system - qty_physical + qty_billed_wait - qty_unbilled
            stock_rows.append({
                "สินค้า":   p["name"],
                "คอม":      qty_system,
                "นับจริง":  qty_physical,
                "เบิก":     qty_unbilled,
                "ฝาก":      qty_billed_wait,
                "ส่วนต่าง": diff,
                "สถานะ":   "🔴 เกิน" if diff > 0 else ("🟡 ขาด" if diff < 0 else "✅ ตรง"),
            })

        stock_df = pd.DataFrame(stock_rows)
        cnt_date = st.date_input("วันที่นับ", value=date.today(), key="stock_cnt_date")

        edited_stock = st.data_editor(
            stock_df,
            use_container_width=True,
            hide_index=True,
            disabled=["สินค้า", "เบิก", "ฝาก", "ส่วนต่าง", "สถานะ"],
            column_config={
                "คอม":      st.column_config.NumberColumn("คอม",     min_value=0, step=1, format="%d"),
                "นับจริง":  st.column_config.NumberColumn("นับจริง", min_value=0, step=1, format="%d"),
                "เบิก":     st.column_config.NumberColumn("เบิก",    format="%d"),
                "ฝาก":      st.column_config.NumberColumn("ฝาก",     format="%d"),
                "ส่วนต่าง": st.column_config.NumberColumn("ส่วนต่าง", format="%d"),
            },
            key="stock_editor",
        )
        st.caption("เบิก = เบิกของไปยังไม่มีบิล  |  ฝาก = เปิดบิลแล้วยังไม่รับของ  |  ส่วนต่าง = คอม − นับจริง + ฝาก − เบิก  |  ส่วนต่างอัปเดตหลังกด บันทึก")

        if st.button("💾 บันทึกการนับสต๊อก", use_container_width=True, type="primary", key="save_stock"):
            saved = 0
            errors = []
            debug_lines = []
            for pid, (_, row) in zip(product_ids, edited_stock.iterrows()):
                new_sys  = int(row["คอม"])     if pd.notna(row["คอม"])     else 0
                new_phys = int(row["นับจริง"]) if pd.notna(row["นับจริง"]) else 0
                debug_lines.append(f"{row['สินค้า']}: คอม={new_sys}, นับจริง={new_phys}, pid={pid}")
                try:
                    db.upsert_stock_count({
                        "id":           str(uuid.uuid4()),
                        "product_id":   pid,
                        "count_date":   str(cnt_date),
                        "qty_system":   new_sys,
                        "qty_physical": new_phys,
                        "notes":        "",
                    })
                    saved += 1
                except Exception as e:
                    errors.append(f"{row['สินค้า']}: {e}")
            if errors:
                st.error("❌ บันทึกไม่สำเร็จบางรายการ:\n" + "\n".join(errors))
            if saved:
                st.success(f"✅ บันทึก {saved} รายการแล้ว")
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Tab 7: พิมพ์บิล
# ─────────────────────────────────────────────────────────────────────────────
with tab7:
    st.subheader("พิมพ์บิล")

    customers_p = db.get_customers()
    if not customers_p:
        st.info("ยังไม่มีข้อมูลลูกค้า")
    else:
        cust_map_p = {c["name"]: c for c in customers_p}
        pc1, pc2 = st.columns([3, 1])
        sel_p    = pc1.selectbox("เลือกลูกค้า", ["— เลือก —"] + list(cust_map_p.keys()), key="print_cust")
        filter_p = pc2.radio("แสดงรายการ", ["ค้างอยู่", "ทั้งหมด"], horizontal=True, key="print_filter")

        if sel_p != "— เลือก —":
            customer_p  = cust_map_p[sel_p]
            all_df_p    = db.get_all_transactions_df(customer_id=customer_p["id"])

            if all_df_p.empty:
                st.info("ไม่มีรายการ")
            else:
                show_p = all_df_p[~all_df_p["เคลียร์แล้ว"]].copy() if filter_p == "ค้างอยู่" else all_df_p.copy()

                if show_p.empty:
                    st.success(f"✅ {sel_p} ไม่มียอดค้าง")
                else:
                    rows_html = ""
                    for _, r in show_p.iterrows():
                        bill_color  = "#b8860b" if r["สถานะบิล"] == "ยังไม่เปิดบิล" else "#1a7a3a"
                        owed_color  = "#c0392b" if r["ค้างจ่าย"] > 0.01 else "#1a7a3a"
                        rows_html += f"""
                        <tr>
                          <td>{r['วันที่']}</td>
                          <td>{r['สินค้า']}</td>
                          <td style="text-align:center">{int(r['สั่ง'])}</td>
                          <td style="text-align:center">{int(r['รับแล้ว'])}</td>
                          <td style="text-align:right">{r['ยอดรวม']:,.0f}</td>
                          <td style="text-align:right">{r['จ่ายแล้ว']:,.0f}</td>
                          <td style="text-align:right;color:{owed_color};font-weight:600">{r['ค้างจ่าย']:,.0f}</td>
                          <td style="text-align:center;color:{bill_color}">{r['สถานะบิล']}</td>
                          <td>{r.get('หมายเหตุ','') or ''}</td>
                        </tr>"""

                    total_amount      = show_p["ยอดรวม"].sum()
                    total_paid        = show_p["จ่ายแล้ว"].sum()
                    total_outstanding = show_p["ค้างจ่าย"].sum()
                    today_str         = date.today().strftime("%d/%m/%Y")
                    filter_label      = "รายการค้างอยู่" if filter_p == "ค้างอยู่" else "รายการทั้งหมด"

                    bill_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Sarabun:wght@400;600;700&display=swap" rel="stylesheet">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Sarabun',sans-serif;padding:24px;color:#111;background:#fff;font-size:14px}}
  .header{{border-bottom:2px solid #222;padding-bottom:12px;margin-bottom:16px}}
  .header h1{{font-size:18px;font-weight:700}}
  .header h2{{font-size:15px;font-weight:600;margin-top:4px}}
  .info{{color:#666;font-size:12px;margin-top:4px}}
  table{{width:100%;border-collapse:collapse;margin-top:8px}}
  th{{background:#222;color:#fff;padding:8px 10px;text-align:left;font-size:13px}}
  td{{padding:6px 10px;border-bottom:1px solid #e0e0e0;font-size:13px}}
  tr:nth-child(even) td{{background:#f7f7f7}}
  .summary{{margin-top:18px;border-top:2px solid #222;padding-top:12px;text-align:right}}
  .summary table{{width:auto;margin-left:auto}}
  .summary td{{padding:4px 12px;border:none;font-size:14px}}
  .summary .big td{{font-weight:700;font-size:16px;border-top:1px solid #ccc;padding-top:8px}}
  .btn{{display:block;margin:0 auto 20px;padding:10px 36px;background:#c0392b;color:#fff;
        border:none;border-radius:6px;font-size:15px;cursor:pointer;font-family:'Sarabun',sans-serif}}
  @media print{{.btn{{display:none}}}}
</style>
</head><body>
<button class="btn" onclick="window.print()">🖨️ พิมพ์</button>
<div class="header">
  <h1>TBY SMART APP — สรุปรายการ</h1>
  <h2>ลูกค้า: {sel_p}</h2>
  <div class="info">วันที่พิมพ์: {today_str} &nbsp;|&nbsp; {filter_label} ({len(show_p)} รายการ)</div>
</div>
<table>
  <thead><tr>
    <th>วันที่</th><th>สินค้า</th>
    <th style="text-align:center">สั่ง</th><th style="text-align:center">รับแล้ว</th>
    <th style="text-align:right">ยอดรวม</th><th style="text-align:right">จ่ายแล้ว</th>
    <th style="text-align:right">ค้างจ่าย</th><th style="text-align:center">สถานะบิล</th>
    <th>หมายเหตุ</th>
  </tr></thead>
  <tbody>{rows_html}</tbody>
</table>
<div class="summary">
  <table>
    <tr><td>ยอดรวมทั้งหมด</td><td><b>{total_amount:,.0f} บาท</b></td></tr>
    <tr><td>จ่ายแล้ว</td><td><b style="color:#1a7a3a">{total_paid:,.0f} บาท</b></td></tr>
    <tr class="big"><td>ค้างจ่าย</td><td><b style="color:#c0392b">{total_outstanding:,.0f} บาท</b></td></tr>
  </table>
</div>
<br>
<button class="btn" onclick="window.print()">🖨️ พิมพ์</button>
</body></html>"""

                    components.html(bill_html, height=700, scrolling=True)


# ─────────────────────────────────────────────────────────────────────────────
# Tab E-commerce: Shopee API sync
# ─────────────────────────────────────────────────────────────────────────────
with tab_ecom:
    st.subheader("🛒 E-commerce — Shopee")

    if not shopee_api.is_configured():
        st.warning("⚙️ ยังไม่ได้ตั้งค่า Shopee Partner ID/Key — กรอกใน `.streamlit/secrets.toml` ก่อนครับ")
        st.code('SHOPEE_PARTNER_ID = "12345"\nSHOPEE_PARTNER_KEY = "xxxxx"', language="toml")
    else:
        # ── Section 1: เชื่อมต่อร้าน ────────────────────────────────────────
        st.markdown("### 1. เชื่อมต่อร้าน Shopee")
        redirect_url = st.text_input(
            "Redirect URL (URL ของแอปนี้)", value="https://your-app.streamlit.app",
            key="ecom_redirect", help="ต้องตรงกับที่ลงทะเบียนใน Shopee Open Platform"
        )
        auth_url = shopee_api.get_auth_url(redirect_url)
        st.link_button("🔗 Authorize ร้านใหม่", url=auth_url)
        st.caption("กดปุ่มด้านบน → เข้า Shopee → เลือกร้าน → ระบบจะ redirect กลับมาพร้อม token อัตโนมัติ")

        shops = db.get_ecommerce_shops()
        if shops:
            st.divider()
            shops_df = pd.DataFrame([{
                "ชื่อร้าน": s["shop_name"], "Shop ID": s["shop_id"],
                "Token หมดอายุ": (s.get("token_expiry") or "")[:16],
            } for s in shops])
            st.dataframe(shops_df, use_container_width=True, hide_index=True)

            # rename shop
            with st.expander("✏️ เปลี่ยนชื่อร้าน"):
                for s in shops:
                    new_name = st.text_input(f"Shop ID {s['shop_id']}", value=s["shop_name"], key=f"sname_{s['id']}")
                    if new_name != s["shop_name"] and st.button("บันทึก", key=f"sname_btn_{s['id']}"):
                        s["shop_name"] = new_name
                        db.upsert_ecommerce_shop(s)
                        st.rerun()

        st.divider()

        # ── Section 2: Sync orders ────────────────────────────────────────────
        st.markdown("### 2. ดึงยอดขาย (Sync)")
        if not shops:
            st.info("เพิ่มร้านก่อนครับ")
        else:
            import datetime as _dt
            shop_options = {s["shop_name"]: s for s in shops}
            sel_shops = st.multiselect("เลือกร้าน", list(shop_options.keys()), default=list(shop_options.keys()), key="ecom_shops_sel")
            sc1, sc2 = st.columns(2)
            sync_from = sc1.date_input("วันที่เริ่ม", value=date.today().replace(day=1), key="sync_from")
            sync_to   = sc2.date_input("ถึง", value=date.today(), key="sync_to")

            if st.button("🔄 Sync Orders", type="primary", use_container_width=True, key="ecom_sync"):
                prod_map  = db.get_ecommerce_product_map()
                new_items  = []
                new_unmapped = []
                from_ts = int(_dt.datetime.combine(sync_from, _dt.time.min).timestamp())
                to_ts   = int(_dt.datetime.combine(sync_to,   _dt.time.max).timestamp())

                for shop_name in sel_shops:
                    shop = shop_options[shop_name]
                    with st.spinner(f"ดึง {shop_name}..."):
                        # refresh token ถ้าใกล้หมดอายุ
                        if shop.get("token_expiry"):
                            exp = _dt.datetime.fromisoformat(shop["token_expiry"].replace("Z", ""))
                            if exp - _dt.datetime.utcnow() < _dt.timedelta(hours=1):
                                r = shopee_api.do_refresh_token(shop["shop_id"], shop["refresh_token"])
                                if "access_token" in r:
                                    shop["access_token"]  = r["access_token"]
                                    shop["refresh_token"] = r["refresh_token"]
                                    new_exp = _dt.datetime.utcnow() + _dt.timedelta(seconds=r.get("expire_in", 14400))
                                    shop["token_expiry"] = new_exp.isoformat()
                                    db.upsert_ecommerce_shop(shop)

                        orders = shopee_api.get_orders(shop["shop_id"], shop["access_token"], from_ts, to_ts)
                        if not orders:
                            continue
                        order_sns = [o["order_sn"] for o in orders]
                        details   = shopee_api.get_order_details(shop["shop_id"], shop["access_token"], order_sns)

                        for order in details:
                            order_date = str(_dt.date.fromtimestamp(order.get("create_time", 0)))
                            for item in order.get("item_list", []):
                                item_id = str(item.get("item_id", ""))
                                qty     = item.get("model_quantity_purchased", 0)
                                price   = float(item.get("item_price", 0))
                                mapped_pid = prod_map.get(("shopee", item_id))
                                new_items.append({
                                    "id":               str(uuid.uuid4()),
                                    "platform":         "shopee",
                                    "shop_name":        shop_name,
                                    "order_sn":         order["order_sn"],
                                    "sale_date":        order_date,
                                    "product_id":       mapped_pid,
                                    "item_id_platform": item_id,
                                    "qty":              qty,
                                    "item_price":       price,
                                })
                                if not mapped_pid:
                                    new_unmapped.append((item_id, item.get("item_name", ""), shop_name))

                if new_items:
                    db.insert_ecommerce_sales(new_items)
                    st.success(f"✅ Sync แล้ว {len(new_items)} รายการ")
                else:
                    st.info("ไม่มี order ใหม่ในช่วงเวลานี้")
                if new_unmapped:
                    st.warning(f"⚠️ {len(set(i[0] for i in new_unmapped))} สินค้ายังไม่ได้ map — ไปที่ Section 4")
                st.rerun()

        st.divider()

        # ── Section 3: ยอดขาย ────────────────────────────────────────────────
        st.markdown("### 3. ยอดขาย E-commerce")
        ev1, ev2 = st.columns(2)
        view_from = ev1.date_input("จาก", value=date.today().replace(day=1), key="ecom_vfrom")
        view_to   = ev2.date_input("ถึง",  value=date.today(), key="ecom_vto")
        ecom_df   = db.get_ecommerce_sales_df(str(view_from), str(view_to))
        if ecom_df.empty:
            st.info("ยังไม่มีข้อมูล — กด Sync ก่อนครับ")
        else:
            st.dataframe(ecom_df.style.format({"ยอด": "{:,.2f}"}), use_container_width=True, hide_index=True)
            st.caption(f"รวม {ecom_df['จำนวน'].sum():,} ชิ้น | ยอดรวม {ecom_df['ยอด'].sum():,.2f} บาท")
            st.dataframe(
                ecom_df.groupby("สินค้า")[["จำนวน", "ยอด"]].sum().reset_index()
                    .sort_values("จำนวน", ascending=False),
                use_container_width=True, hide_index=True,
            )

        st.divider()

        # ── Section 4: Map สินค้า ─────────────────────────────────────────────
        st.markdown("### 4. Map สินค้า Shopee → ระบบ")
        unmapped_rows = db.get_unmapped_ecommerce_items("shopee") if shops else []

        if unmapped_rows:
            st.warning(f"มี {len(unmapped_rows)} รายการที่ยังไม่ได้ map")
            all_products = db.get_products()
            prod_opts    = {"— ยังไม่ map —": None} | {p["name"]: p["id"] for p in all_products}
            map_rows     = []
            for i, row in enumerate(unmapped_rows):
                mc1, mc2 = st.columns([2, 3])
                mc1.write(f"`{row['item_id']}` ({row['shop_name']})")
                sel = mc2.selectbox("สินค้าในระบบ", list(prod_opts.keys()), key=f"map_{i}")
                if prod_opts[sel]:
                    map_rows.append({
                        "id": str(uuid.uuid4()),
                        "platform": "shopee",
                        "platform_item_id": row["item_id"],
                        "product_id": prod_opts[sel],
                        "platform_product_name": row["item_id"],
                    })
            if map_rows and st.button("💾 บันทึก Mapping", type="primary", key="ecom_map_save"):
                db.upsert_ecommerce_product_map(map_rows)
                st.success(f"✅ Map แล้ว {len(map_rows)} รายการ")
                st.rerun()
        else:
            st.success("✅ สินค้าทุกรายการ map แล้ว")


# ─────────────────────────────────────────────────────────────────────────────
# Tab การเงิน: บันทึกยอดรายวัน + วงเงินสั่งของ
# ─────────────────────────────────────────────────────────────────────────────
with tab_fin:
    st.subheader("💵 การเงิน")

    fin_summary = db.get_finance_summary()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🚩 ยอดค้างโอน (฿)", f"{fin_summary['outstanding']:,.2f}")
    m2.metric("💰 เงินโอนเกิน (฿)", f"{fin_summary['overpaid']:,.2f}")
    m3.metric("📦 สต๊อก ไม่รวม VAT (฿)", f"{fin_summary['stock']:,.2f}")
    credit_val = fin_summary["credit"]
    m4.metric("🛒 สิทธิ์สั่งของคงเหลือ (฿)", f"{credit_val:,.2f}",
              delta=None if credit_val >= 0 else "⚠️ เกินวงเงิน")

    st.divider()

    with st.expander("🗓️ เปิดเดือนใหม่ (กรอกครั้งเดียวต้นเดือน)"):
        ob_date  = st.date_input("วันที่เปิดเดือน", value=date.today().replace(day=1), key="ob_date")
        _ob = db.get_finance_entry(str(ob_date)) or {}
        ob_adj = float(_ob.get("adjustment", 0))
        ob1, ob2 = st.columns(2)
        with ob1:
            ob_overpaid = st.number_input("โอนเกินยกมา (฿)", min_value=0.0, step=100.0,
                value=max(0.0, ob_adj), key=f"ob_over_{ob_date}")
            ob_stock    = st.number_input("สต๊อกยกมา ไม่รวม VAT (฿)", min_value=0.0, step=100.0,
                value=float(_ob.get("stock_value", 0)), key=f"ob_stock_{ob_date}")
        with ob2:
            ob_owed     = st.number_input("ค้างโอนยกมา (฿)", min_value=0.0, step=100.0,
                value=max(0.0, -ob_adj), key=f"ob_owed_{ob_date}")
        if st.button("💾 บันทึกยอดยกมา", type="secondary", use_container_width=True, key="ob_save"):
            db.upsert_finance_entry({
                "id": str(uuid.uuid4()), "entry_date": str(ob_date),
                "transfer_amount": 0, "registration_fee": 0,
                "sales_amount": 0, "bv_amount": 0, "po_amount": 0,
                "stock_value": ob_stock,
                "adjustment": ob_overpaid - ob_owed,
                "notes": "ยอดยกมา",
            })
            st.success("✅ บันทึกยอดยกมาแล้ว")
            st.rerun()

    with st.expander("➕ กรอกข้อมูลประจำวัน", expanded=True):
        fin_date = st.date_input("วันที่", value=date.today(), key="fin_date")
        _ex = db.get_finance_entry(str(fin_date)) or {}
        if _ex:
            st.info("📋 มีข้อมูลวันนี้แล้ว — แก้ไขแล้วกด บันทึก เพื่ออัปเดต")
        fc1, fc2 = st.columns(2)
        with fc1:
            fin_transfer = st.number_input("ยอดโอนให้บริษัท (฿)", min_value=0.0, step=100.0, value=float(_ex.get("transfer_amount", 0)), key=f"fin_transfer_{fin_date}")
            fin_sales    = st.number_input("ยอดขาย รวม VAT (฿)",   min_value=0.0, step=100.0, value=float(_ex.get("sales_amount", 0)), key=f"fin_sales_{fin_date}")
            fin_po       = st.number_input("PO สั่งของ ไม่รวม VAT (฿)", min_value=0.0, step=100.0, value=float(_ex.get("po_amount", 0)), key=f"fin_po_{fin_date}")
        with fc2:
            fin_reg      = st.number_input("ค่าสมัคร (฿)",    min_value=0.0, step=100.0, value=float(_ex.get("registration_fee", 0)), key=f"fin_reg_{fin_date}")
            fin_bv       = st.number_input("BV (หักยอดค้าง) (฿)", min_value=0.0, step=100.0, value=float(_ex.get("bv_amount", 0)), key=f"fin_bv_{fin_date}")
        fin_notes = st.text_input("หมายเหตุ", value=_ex.get("notes", "") or "", key=f"fin_notes_{fin_date}")

        if st.button("💾 บันทึก", type="primary", use_container_width=True, key="fin_save"):
            db.upsert_finance_entry({
                "id":               str(uuid.uuid4()),
                "entry_date":       str(fin_date),
                "transfer_amount":  fin_transfer,
                "registration_fee": fin_reg,
                "sales_amount":     fin_sales,
                "bv_amount":        fin_bv,
                "po_amount":        fin_po,
                "stock_value":      0,
                "adjustment":       0,
                "notes":            fin_notes,
            })
            st.success("✅ บันทึกแล้ว")
            st.rerun()

    st.divider()

    fin_df = db.get_finance_df()
    if fin_df.empty:
        st.info("ยังไม่มีข้อมูล — กรอกข้อมูลด้านบนก่อนครับ")
    else:
        display_fin = fin_df[[
            "entry_date", "transfer_amount", "bv_amount", "registration_fee",
            "sales_amount", "po_amount",
            "auto_stock", "ยอดค้างโอน", "เงินโอนเกิน", "สิทธิ์สั่งของ",
        ]].copy()
        display_fin.columns = [
            "วันที่", "โอน", "BV", "สมัคร", "ขาย", "PO",
            "สต๊อก", "ค้างโอน", "โอนเกิน", "สิทธิ์สั่งของ",
        ]
        st.dataframe(
            display_fin.sort_values("วันที่", ascending=False).style.format({
                "โอน": "{:,.2f}", "BV": "{:,.2f}", "สมัคร": "{:,.2f}", "ขาย": "{:,.2f}",
                "PO": "{:,.2f}", "สต๊อก": "{:,.2f}",
                "ค้างโอน": "{:,.2f}", "โอนเกิน": "{:,.2f}", "สิทธิ์สั่งของ": "{:,.2f}",
            }).map(lambda v: "background-color:#6b1a1a;color:white" if isinstance(v, float) and v > 0.01 else "",
                  subset=["ค้างโอน"])
            .map(lambda v: "background-color:#6b1a1a;color:white" if isinstance(v, float) and v < -0.01 else "",
                  subset=["สิทธิ์สั่งของ"]),
            use_container_width=True,
            hide_index=True,
        )

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            display_fin.to_excel(writer, index=False, sheet_name="การเงิน")
        st.download_button(
            "📥 Export Excel",
            data=buf.getvalue(),
            file_name=f"finance_{date.today()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
