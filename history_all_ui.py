import uuid
import streamlit as st
import pandas as pd
from datetime import date, timedelta

import database as db
from ui_helpers import _fmt_note, _to_excel_bytes


def render(customers):
    st.subheader("รายละเอียดบิล")

    try:
        _hist_cids_with_txn = db.get_customer_ids_with_transactions()
    except Exception:
        _hist_cids_with_txn = None  # ดึงไม่ได้ — แสดงลูกค้าทั้งหมดแทน
    customers_h = (
        [c for c in customers if c["id"] in _hist_cids_with_txn]
        if _hist_cids_with_txn is not None else customers
    )
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
            ["ทั้งหมด", "ค้างจ่าย", "ค้างรับของ", "ยังไม่เปิดบิล", "เคลียร์แล้ว"],
            key="hist_status",
        )

    h_all_time = st.checkbox(
        "ดูทั้งหมดตั้งแต่เปิดร้าน (อาจโหลดช้าถ้าข้อมูลเยอะ)",
        key="hist_all_time",
    )
    h_date_from = h_date_to = None
    if not h_all_time:
        h_col3, h_col4 = st.columns(2)
        h_date_from = h_col3.date_input("ตั้งแต่วันที่", value=date.today() - timedelta(days=90), key="hist_date_from")
        h_date_to   = h_col4.date_input("ถึงวันที่", value=date.today(), key="hist_date_to")

    h_cid = None
    if h_filter_cust != "ทั้งหมด":
        h_cid = next(c["id"] for c in customers_h if c["name"] == h_filter_cust)

    all_df = db.get_all_transactions_df(
        customer_id=h_cid,
        date_from=str(h_date_from) if h_date_from else None,
        date_to=str(h_date_to) if h_date_to else None,
    )

    if not all_df.empty:
        if h_filter_status == "ค้างจ่าย":
            all_df = all_df[all_df["ค้างจ่าย"] > 0]
        elif h_filter_status == "ค้างรับของ":
            all_df = all_df[all_df["ค้างรับ"] > 0]
        elif h_filter_status == "ยังไม่เปิดบิล":
            all_df = all_df[all_df["สถานะบิล"] == "ยังไม่เปิดบิล"]
        elif h_filter_status == "เคลียร์แล้ว":
            all_df = all_df[all_df["เคลียร์แล้ว"]]

    if all_df.empty:
        st.info("ไม่มีข้อมูล")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("รายการทั้งหมด", len(all_df))
        m2.metric("เคลียร์แล้ว", int(all_df["เคลียร์แล้ว"].sum()))
        m3.metric("ยังค้างอยู่", int((~all_df["เคลียร์แล้ว"]).sum()))

        display_cols_h = ["เลขที่บิล", "วันที่", "ลูกค้า", "รหัส", "สินค้า", "สั่ง", "รับแล้ว",
                          "ยอดรวม", "จ่ายแล้ว", "ค้างจ่าย", "ค้างรับ",
                          "สถานะบิล", "สถานะจ่าย", "หมายเหตุ"]
        show_df = all_df[display_cols_h].reset_index(drop=True)
        show_df["หมายเหตุ"] = show_df["หมายเหตุ"].fillna("").apply(_fmt_note)
        id_map  = all_df["id"].reset_index(drop=True)

        st.download_button(
            "⬇ Export Excel",
            _to_excel_bytes(show_df, "ประวัติ"),
            file_name=f"ประวัติ_{date.today().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_hist",
        )

        chk_df = show_df.copy()
        chk_df.insert(0, "🗑️", False)
        _cleared_mask = all_df["เคลียร์แล้ว"].reset_index(drop=True)
        chk_df.insert(1, "สถานะ", _cleared_mask.map({True: "✅ เคลียร์", False: ""}))

        # โชว์ "บิลหลัก" เฉพาะแถวที่เคยถูกแยกบิล (origin ≠ เลขที่บิลปัจจุบัน) กันตาราง
        # รกด้วยค่าซ้ำเดิมทุกแถวตอนไม่มีการแยกบิล
        _origin_h = all_df["เลขอ้างอิงบิลหลัก"].reset_index(drop=True)
        _bno_h = chk_df["เลขที่บิล"].fillna("")
        _has_family_h = (_origin_h != "") & (_origin_h != _bno_h)
        if _has_family_h.any():
            chk_df.insert(chk_df.columns.get_loc("เลขที่บิล") + 1, "บิลหลัก", _origin_h.where(_has_family_h, ""))

        _is_dup_bill = chk_df["เลขที่บิล"].ne("") & (chk_df["เลขที่บิล"] == chk_df["เลขที่บิล"].shift(1).fillna(""))
        for _col in ("เลขที่บิล", "วันที่", "ลูกค้า"):
            chk_df[_col] = chk_df[_col].where(~_is_dup_bill, "")

        # ── placeholder สำหรับปุ่มบันทึกเหนือตาราง (fill หลัง data_editor)
        _save_placeholder = st.empty()

        _editable = ("🗑️", "รับแล้ว", "สั่ง", "ยอดรวม", "จ่ายแล้ว", "ลูกค้า", "สถานะบิล", "สถานะจ่าย")
        _cust_names_h = [c["name"] for c in customers_h]
        _cust_id_map_h = {c["name"]: c["id"] for c in customers_h}
        edited_h = st.data_editor(
            chk_df,
            width="stretch",
            hide_index=True,
            column_config={
                "🗑️":       st.column_config.CheckboxColumn("🗑️", default=False, width="small"),
                "สถานะ":    st.column_config.TextColumn("สถานะ", width="small"),
                "สั่ง":     st.column_config.NumberColumn("สั่ง", min_value=1, step=1, width="small"),
                "รับแล้ว":  st.column_config.NumberColumn("รับแล้ว", min_value=0, step=1, width="small"),
                "ยอดรวม":   st.column_config.NumberColumn("ยอดรวม", format="%,.0f"),
                "จ่ายแล้ว": st.column_config.NumberColumn("จ่ายแล้ว", format="%,.0f"),
                "ค้างจ่าย": st.column_config.NumberColumn("ค้างจ่าย", format="%,.0f"),
                "ลูกค้า":    st.column_config.SelectboxColumn("ลูกค้า",
                    options=_cust_names_h, width="medium"),
                "สถานะบิล": st.column_config.SelectboxColumn("สถานะบิล",
                    options=["เปิดบิลแล้ว", "ยังไม่เปิดบิล"], width="medium"),
                "สถานะจ่าย": st.column_config.SelectboxColumn("สถานะจ่าย",
                    options=["จ่ายแล้ว", "ค้างจ่าย", "COD"], width="medium"),
            },
            disabled=[c for c in chk_df.columns if c not in _editable],
            key="hist_table",
        )

        to_del_idx = edited_h[edited_h["🗑️"]].index.tolist()

        if len(to_del_idx) == 1 and to_del_idx[0] < len(id_map):
            _auto_tid = id_map.iloc[to_del_idx[0]]
            _auto_rows = all_df[all_df["id"] == _auto_tid]
            if not _auto_rows.empty:
                _ar = _auto_rows.iloc[0]
                _auto_label = f"{_ar['วันที่']}  {_ar['ลูกค้า']}  {_ar['สินค้า']} ×{int(_ar['สั่ง'])}"
                if st.session_state.get("edit_sel") != _auto_label:
                    st.session_state["edit_sel"] = _auto_label

        if to_del_idx:
            d1, d2 = st.columns([2, 1])
            d1.warning(f"เลือก {len(to_del_idx)} รายการ")
            if d2.button("🗑️ ลบรายการที่เลือก", type="secondary", width="stretch", key="hist_del_chk_btn"):
                db.delete_transactions_batch([id_map.iloc[i] for i in to_del_idx])
                st.success(f"✅ ลบ {len(to_del_idx)} รายการแล้ว")
                st.session_state.pop("hist_table", None)
                st.rerun()

            _sel_unbilled = [i for i in to_del_idx
                             if i < len(all_df)
                             and all_df.iloc[i]["สถานะบิล"] == "ยังไม่เปิดบิล"]
            if _sel_unbilled:
                ob1, ob2 = st.columns([2, 1])
                ob1.info(f"📄 {len(_sel_unbilled)} รายการยังไม่เปิดบิล")
                if ob2.button(f"📄 เปิดบิล {len(_sel_unbilled)} รายการ",
                               type="primary", width="stretch",
                               key="hist_open_bill_btn"):
                    for i in _sel_unbilled:
                        _row = all_df.iloc[i]
                        _remaining = int(_row["ยังไม่เปิด"]) if "ยังไม่เปิด" in _row else int(_row["สั่ง"])
                        if _remaining > 0:
                            db.open_bill_partial(id_map.iloc[i], _remaining)
                    st.success(f"✅ เปิดบิล {len(_sel_unbilled)} รายการแล้ว")
                    st.session_state.pop("hist_table", None)
                    st.rerun()

        # ตรวจหาการแก้ไขทุกประเภท (เทียบกับ show_df ที่ไม่ blank)
        _any_changes = []
        for _i in range(len(show_df)):
            if _i >= len(id_map): break
            _orig = show_df.iloc[_i]
            _edit = edited_h.iloc[_i + 0]
            _tid  = id_map.iloc[_i]
            _ch   = {}
            # รับแล้ว → partial_event qty
            _old_recv = int(_orig["รับแล้ว"])
            _new_recv = int(float(_edit["รับแล้ว"] or 0))
            if _old_recv != _new_recv:
                _ch["recv"] = (_old_recv, _new_recv)
            # จ่ายแล้ว → partial_event amount
            _old_paid = float(_orig["จ่ายแล้ว"])
            _new_paid = float(_edit["จ่ายแล้ว"] or 0)
            if abs(_old_paid - _new_paid) > 0.01:
                _ch["paid"] = (_old_paid, _new_paid)
            # สั่ง
            if int(_orig["สั่ง"]) != int(_edit["สั่ง"] or 1):
                _ch["qty"] = int(_edit["สั่ง"] or 1)
            # ยอดรวม
            if abs(float(_orig["ยอดรวม"]) - float(_edit["ยอดรวม"] or 0)) > 0.01:
                _ch["total"] = float(_edit["ยอดรวม"] or 0)
            # ถ้าแก้ สั่ง แต่ไม่ได้แก้ ยอดรวม → คำนวณ ยอดรวมใหม่ อัตโนมัติ
            if "qty" in _ch and "total" not in _ch:
                _orig_qty = int(_orig["สั่ง"])
                if _orig_qty > 0:
                    _price_per = float(_orig["ยอดรวม"]) / _orig_qty
                    _ch["total"] = _price_per * _ch["qty"]
            # ลูกค้า
            _new_cust = str(_edit["ลูกค้า"] or "")
            if _new_cust and _new_cust != str(_orig["ลูกค้า"]) and _new_cust in _cust_id_map_h:
                _ch["customer_id"] = _cust_id_map_h[_new_cust]
            # สถานะบิล
            if str(_orig["สถานะบิล"]) != str(_edit["สถานะบิล"] or ""):
                _ch["bill_status"] = str(_edit["สถานะบิล"])
            # สถานะจ่าย
            if str(_orig["สถานะจ่าย"]) != str(_edit["สถานะจ่าย"] or ""):
                _ch["pay_status"] = str(_edit["สถานะจ่าย"])
            if _ch:
                _any_changes.append((_i, _tid, _ch))

        if _any_changes:
            with _save_placeholder.container():
                _sp1, _sp2 = st.columns([3, 1])
                _sp1.warning(f"⚠️ มีการแก้ไข {len(_any_changes)} รายการ — ยังไม่ได้บันทึก")
                _top_save = _sp2.button("💾 บันทึกแก้ไข", type="primary",
                                        width="stretch", key="save_all_fix_top")
            _sc1, _sc2 = st.columns([3, 1])
            _sc1.info(f"แก้ไข {len(_any_changes)} รายการ")
            _bottom_save = _sc2.button("💾 บันทึกแก้ไข", type="primary",
                                       width="stretch", key="save_all_fix")
            if _top_save or _bottom_save:
                for _i, _tid, _ch in _any_changes:
                    if "recv" in _ch:
                        _old_r, _new_r = _ch["recv"]
                        _max_r = int(show_df.iloc[_i]["สั่ง"])
                        _new_r = max(0, min(_new_r, _max_r))
                        _delta = _new_r - _old_r
                        if _delta != 0:
                            db.insert_partial_event({
                                "id":             str(uuid.uuid4()),
                                "date":           str(date.today()),
                                "transaction_id": _tid,
                                "qty_received":   _delta,
                                "amount_paid":    0.0,
                                "event_type":     "รับของ",
                            })
                    if "paid" in _ch:
                        _old_p, _new_p = _ch["paid"]
                        _delta_p = _new_p - _old_p
                        _txn_total = float(show_df.iloc[_i]["ยอดรวม"])
                        if "pay_status" not in _ch:
                            if _new_p <= 0.01:
                                _ch["pay_status"] = "ค้างจ่าย"
                            elif abs(_new_p - _txn_total) < 0.01:
                                _ch["pay_status"] = "จ่ายแล้ว"
                        if _new_p <= 0.01:
                            db.delete_payment_events(_tid)
                        elif _delta_p > 0.01 and "pay_status" not in _ch:
                            db.insert_partial_event({
                                "id":             str(uuid.uuid4()),
                                "date":           str(date.today()),
                                "transaction_id": _tid,
                                "qty_received":   0,
                                "amount_paid":    _delta_p,
                                "event_type":     "จ่ายเงิน",
                            })
                    _txn_upd = {}
                    if "qty"         in _ch: _txn_upd["qty"]          = _ch["qty"]
                    if "total"       in _ch: _txn_upd["total_amount"]  = _ch["total"]
                    if "customer_id" in _ch: _txn_upd["customer_id"]   = _ch["customer_id"]
                    if _txn_upd:
                        db.update_transaction(_tid, _txn_upd)
                    if "bill_status" in _ch or "pay_status" in _ch:
                        _old_bstatus = str(show_df.iloc[_i]["สถานะบิล"])
                        _new_bstatus = _ch.get("bill_status")
                        if _new_bstatus == "ยังไม่เปิดบิล" and _old_bstatus == "เปิดบิลแล้ว":
                            # ย้อนเปิดบิล (ยกเลิก event เปิดบิลล่าสุด — bill_no ไม่ถูกแตะ
                            # เพราะเป็นแค่เลขอ้างอิงภายในตลอดอายุแถวอยู่แล้ว)
                            db.undo_last_bill_open_event(_tid)
                            if _ch.get("pay_status"):
                                db.update_transaction_status(_tid, pay_status=_ch.get("pay_status"))
                        elif _new_bstatus == "เปิดบิลแล้ว" and _old_bstatus == "ยังไม่เปิดบิล":
                            # ตารางนี้ไม่มีช่องกรอกเลขที่บิลจริง — เปิดแบบไม่มีโน้ต (ใส่
                            # เลขบิลจริงเพิ่มทีหลังได้ที่ ยอดค้าง/จัดการบิล ถ้าต้องการ)
                            _row = all_df.iloc[_i]
                            _remaining = int(_row["ยังไม่เปิด"]) if "ยังไม่เปิด" in _row else int(_row["สั่ง"])
                            if _remaining > 0:
                                db.open_bill_partial(_tid, _remaining)
                            if _ch.get("pay_status"):
                                db.update_transaction_status(_tid, pay_status=_ch.get("pay_status"))
                        else:
                            db.update_transaction_status(_tid, pay_status=_ch.get("pay_status"))
                st.success("✅ บันทึกแล้ว")
                st.session_state.pop("hist_table", None)
                st.rerun()

        cleared_ids = all_df[all_df["เคลียร์แล้ว"]]["id"].tolist()
        if cleared_ids:
            bc1, bc2 = st.columns([3, 1])
            bc1.caption(f"มี {len(cleared_ids)} รายการที่เคลียร์แล้ว (จ่ายและรับครบ)")
            h_confirm_bulk = bc1.checkbox("ยืนยันลบทั้งหมดที่เคลียร์แล้ว", key="hist_bulk_chk")
            if bc2.button(f"🗑️ ลบเคลียร์แล้วทั้งหมด ({len(cleared_ids)})",
                          disabled=not h_confirm_bulk, width="stretch", key="hist_bulk_del"):
                db.delete_transactions_batch(cleared_ids)
                st.success(f"✅ ลบ {len(cleared_ids)} รายการแล้ว")
                st.rerun()

        st.divider()
        with st.expander("✏️ แก้ไขรายการ"):
            all_products_e = db.get_products()
            all_customers_e = customers
            product_map_e = {p["name"]: p for p in all_products_e}
            customer_map_e = {c["name"]: c for c in all_customers_e}

            edit_opts = {
                f"{r['วันที่']}  {r['ลูกค้า']}  {r['สินค้า']} ×{r['สั่ง']}": r["id"]
                for _, r in all_df.iterrows()
            }
            edit_sel = st.selectbox("เลือกรายการที่จะแก้ไข", list(edit_opts.keys()), key="edit_sel")
            edit_txn_id = edit_opts[edit_sel]

            edit_balance = db.get_transaction_balance(edit_txn_id)
            if not edit_balance:
                st.warning("ไม่พบรายการนี้ในฐานข้อมูล (อาจถูกลบไปแล้ว)")
                st.stop()
            et = edit_balance["transaction"]

            prod_names = list(product_map_e.keys())
            cust_names = list(customer_map_e.keys())
            _tgt_prod = next((p["name"] for p in all_products_e if p["id"] == et["product_id"]), "")
            _tgt_cust = next((c["name"] for c in all_customers_e if c["id"] == et["customer_id"]), "")
            cur_prod_idx = prod_names.index(_tgt_prod) if _tgt_prod in prod_names else 0
            cur_cust_idx = cust_names.index(_tgt_cust) if _tgt_cust in cust_names else 0
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

                if st.form_submit_button("💾 บันทึกการแก้ไข", width="stretch", type="primary"):
                    if e_bill == "เปิดบิลแล้ว" and et["bill_status"] == "ยังไม่เปิดบิล":
                        # ช่องนี้ไม่มีที่กรอกเลขที่บิลจริง — ห้ามเปิดบิลผ่านจุดนี้ กัน
                        # เปิดบิลลอยๆ ไม่มีเลขบิลจริงผูกอยู่
                        st.error(
                            "❌ เปลี่ยนเป็น \"เปิดบิลแล้ว\" ผ่านช่องนี้ไม่ได้ — ต้องกรอกเลขที่บิลจริง "
                            "ผ่านปุ่ม \"📄 เปิดบิล\" ในแท็บ ยอดค้าง/จัดการบิล แทน"
                        )
                    else:
                        e_receive_now = e_receipt == "รับของแล้ว"
                        e_initial_qty = int(e_qty) if e_receive_now else 0
                        e_txn_type = "เบิกของก่อน" if e_bill == "ยังไม่เปิดบิล" and e_receive_now else "ขายปกติ"
                        _e_upd = {
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
                        }
                        _e_reverting_bill = e_bill == "ยังไม่เปิดบิล" and et["bill_status"] == "เปิดบิลแล้ว"
                        if _e_reverting_bill:
                            # ย้อนเปิดบิล — ใช้ undo_last_bill_open_event เดียวกับจุดอื่น
                            # (insert correction event แทนการเซ็ต bill_status ตรงๆ)
                            del _e_upd["bill_status"]
                        db.update_transaction(edit_txn_id, _e_upd)
                        if _e_reverting_bill:
                            db.undo_last_bill_open_event(edit_txn_id)
                        st.success("✅ แก้ไขแล้ว")
                        st.rerun()

    st.divider()
    with st.expander("📦 ประวัติการส่งของ", expanded=False):
        _hist_ships = db.get_shipments(customer_id=h_cid)
        if not _hist_ships:
            st.caption("ไม่มีข้อมูลการส่งของ")
        else:
            _ship_rows_h = []
            for _s in _hist_ships:
                _items_str_h = ", ".join(
                    f"{it.get('name','?')}×{it.get('qty',0)}"
                    for it in (_s.get("items") or [])[:3]
                )
                _src_h = _s.get("source") or "ship"
                _ship_rows_h.append({
                    "วันที่":    (_s.get("created_at") or "")[:10],
                    "แหล่ง":    "📦 ส่งของ" if _src_h == "ship" else "💰 บันทึกขาย",
                    "ลูกค้า":   (_s.get("customers") or {}).get("name", ""),
                    "ขนส่ง":    _s.get("carrier", ""),
                    "Tracking": _s.get("tracking_no", ""),
                    "สินค้า":   _items_str_h,
                })
            _ship_df_h = pd.DataFrame(_ship_rows_h)
            st.dataframe(_ship_df_h, hide_index=True, width="stretch")
