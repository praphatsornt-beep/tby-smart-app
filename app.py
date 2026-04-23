import streamlit as st
import pandas as pd
from datetime import date
from math import floor
import uuid

import database as db

st.set_page_config(page_title="TBY SMART APP", page_icon="🛍️", layout="wide")

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
th {
    background-color: #1e1e1e !important;
    color: white !important;
    text-align: center !important;
    font-weight: 700 !important;
    opacity: 1 !important;
}
thead tr th {
    background-color: #1e1e1e !important;
    opacity: 1 !important;
}
</style>
""", unsafe_allow_html=True)

st.title("🛍️ TBY SMART APP")

tab1, tab2, tab3, tab5, tab6, tab4 = st.tabs([
    "📋 บันทึกรายการ",
    "💰 จัดการออเดอร์",
    "📊 ยอดค้าง",
    "🗂️ ประวัติทั้งหมด",
    "📦 สต๊อก",
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
            st.dataframe(
                pd.DataFrame(customers)[["id", "name", "phone"]],
                use_container_width=True,
                hide_index=True,
            )
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

        st.write("**เพิ่ม / แก้ไขลูกค้า**")
        with st.form("add_customer", clear_on_submit=True):
            c1, c2 = st.columns(2)
            c_name = c1.text_input("ชื่อลูกค้า")
            next_cid = f"C-{len(customers)+1:03d}"
            c_id = c2.text_input("รหัสลูกค้า (แก้ไขได้)", value=next_cid)
            c_phone = st.text_input("เบอร์โทร")

            if st.form_submit_button("💾 บันทึก", use_container_width=True):
                if c_id.strip() and c_name.strip():
                    db.upsert_customer({
                        "id": c_id.strip(), "name": c_name.strip(), "phone": c_phone.strip(),
                    })
                    st.success(f"✅ บันทึก {c_name} แล้ว")
                    st.rerun()
                else:
                    st.error("กรุณากรอก รหัส และ ชื่อลูกค้า")


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

        def _style_hist_row(row):
            if row["ค้างจ่าย"] <= 0.01 and row["ค้างรับ"] <= 0 and row["สถานะบิล"] == "เปิดบิลแล้ว":
                return ["background-color:#0d2b1a"] * len(row)
            if row["ค้างรับ"] > 0 and row["สถานะบิล"] == "เปิดบิลแล้ว":
                return ["background-color:#2b1e00"] * len(row)
            return [""] * len(row)

        st.dataframe(
            show_df.style
                .format({"ยอดรวม": "{:,.0f}", "จ่ายแล้ว": "{:,.0f}", "ค้างจ่าย": "{:,.0f}"})
                .apply(_style_hist_row, axis=1)
                .map(_style_status, subset=["สถานะบิล", "สถานะจ่าย"]),
            use_container_width=True,
            hide_index=True,
        )
        st.caption("🟢 เคลียร์แล้ว (จ่ายและรับครบ)  |  🟠 มีของฝาก (เปิดบิลแล้วยังไม่รับของ)")

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

        # Build table — คอม/นับจริง แก้ได้, คอลัมน์คำนวณ read-only
        stock_rows = []
        for p in products:
            pid             = p["id"]
            count           = latest_counts.get(pid, {})
            qty_system      = int(count.get("qty_system",   0) or 0)
            qty_physical    = int(count.get("qty_physical", 0) or 0)
            qty_unbilled    = unbilled_qty.get(pid, 0)
            qty_billed_wait = billed_not_rcv.get(pid, 0)
            diff = qty_system - qty_physical + qty_billed_wait - qty_unbilled
            stock_rows.append({
                "_pid":                pid,
                "สินค้า":              p["name"],
                "คอม":                 qty_system,
                "นับจริง":             qty_physical,
                "เบิกไปไม่มีบิล":      qty_unbilled,
                "เปิดบิลยังไม่รับของ": qty_billed_wait,
                "ส่วนต่าง":            diff,
                "สถานะ":               "🔴 เกิน" if diff > 0 else ("🟡 ขาด" if diff < 0 else "✅ ตรง"),
                "วันนับล่าสุด":        count.get("count_date", "—"),
            })

        stock_df = pd.DataFrame(stock_rows)
        original_df = stock_df[["_pid", "คอม", "นับจริง"]].copy()

        cnt_date = st.date_input("วันที่นับ", value=date.today(), key="stock_cnt_date")

        edited_stock = st.data_editor(
            stock_df,
            use_container_width=True,
            hide_index=True,
            disabled=["สินค้า", "เบิกไปไม่มีบิล", "เปิดบิลยังไม่รับของ", "ส่วนต่าง", "สถานะ", "วันนับล่าสุด"],
            column_config={
                "_pid":                None,
                "คอม":                 st.column_config.NumberColumn("คอม", min_value=0, step=1, format="%d"),
                "นับจริง":             st.column_config.NumberColumn("นับจริง", min_value=0, step=1, format="%d"),
                "เบิกไปไม่มีบิล":      st.column_config.NumberColumn("เบิกไปไม่มีบิล", format="%d"),
                "เปิดบิลยังไม่รับของ": st.column_config.NumberColumn("เปิดบิลยังไม่รับของ", format="%d"),
                "ส่วนต่าง":            st.column_config.NumberColumn("ส่วนต่าง", format="%d"),
            },
            key="stock_editor",
        )
        st.caption("ส่วนต่าง = คอม − นับจริง + เปิดบิลยังไม่รับของ − เบิกไปไม่มีบิล")

        if st.button("💾 บันทึกการนับสต๊อก", use_container_width=True, type="primary", key="save_stock"):
            saved = 0
            for i, row in edited_stock.iterrows():
                orig = original_df.iloc[i]
                new_sys  = int(row["คอม"]     or 0)
                new_phys = int(row["นับจริง"] or 0)
                if new_sys != int(orig["คอม"]) or new_phys != int(orig["นับจริง"]):
                    db.insert_stock_count({
                        "id":           str(uuid.uuid4()),
                        "product_id":   row["_pid"],
                        "count_date":   str(cnt_date),
                        "qty_system":   new_sys,
                        "qty_physical": new_phys,
                        "notes":        "",
                    })
                    saved += 1
            if saved:
                st.success(f"✅ บันทึก {saved} รายการแล้ว")
                st.rerun()
            else:
                st.info("ไม่มีข้อมูลที่เปลี่ยนแปลง")
