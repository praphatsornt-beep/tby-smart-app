import re
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from datetime import date
from math import floor
import uuid

import database as db
import line_api
import iship_api
from ui_helpers import (
    _to_bkk, _to_excel_bytes, BOX_WEIGHT_G,
    _style_status, _fmt_note, _extract_staff_tag,
    _bills_from_df, _render_bill_panel, _ledger_to_txn_df,
)
import carriers as carr


_T5_TABS = ["💰 ยอดค้าง / จัดการบิล", "👤 บัตรลูกค้า", "📋 ประวัติทั้งหมด", "🚚 ประวัติการส่ง"]


def render(products, customers):
    try:
        _t5_active = st.pills("", _T5_TABS, key="_t5_active_sub", label_visibility="collapsed") or _T5_TABS[0]
    except AttributeError:
        _t5_active = st.radio("", _T5_TABS, horizontal=True, key="_t5_active_sub", label_visibility="collapsed")

    if _t5_active == _T5_TABS[0]:
        _out_h1, _out_h2 = st.columns([5, 1])
        _out_h1.subheader("ยอดค้างลูกค้า")
        if _out_h2.button("🔄 รีเฟรชยอด", key="t5_out_refresh", help="กดก่อนบันทึกรับเงิน/รับของ เผื่อลูกค้าจ่าย/รับของผ่าน LINE มาแล้ว"):
            db._clear_transaction_caches()
            st.rerun()

        with st.expander("🗑️ ลบบิล", expanded=False):
            st.caption("เลือกเลขที่บิลที่ต้องการลบ — จะลบทุกรายการในบิลนั้น")
            _bill_list = db.get_bill_list()
            if _bill_list:
                _sel_bill = st.selectbox("เลขที่บิล", _bill_list, key="del_bill_sel")
                _bill_rows = db.get_bill_details(_sel_bill)
                if _bill_rows:
                    _bill_date = (_bill_rows[0].get("date") or "")[:10]
                    _bill_cust = (_bill_rows[0].get("customers") or {}).get("name", "—")
                    _bill_status = _bill_rows[0].get("bill_status", "")
                    st.markdown(f"**วันที่:** {_bill_date} &nbsp;|&nbsp; **ลูกค้า:** {_bill_cust} &nbsp;|&nbsp; **สถานะ:** {_bill_status}")
                    _preview_df = pd.DataFrame([{
                        "สินค้า":      r.get("product_name", ""),
                        "จำนวน":      r.get("qty", 0),
                        "ราคา/หน่วย": r.get("price_per_unit", 0),
                        "ยอดรวม":     r.get("total_amount", 0),
                    } for r in _bill_rows])
                    st.dataframe(_preview_df, use_container_width=True, hide_index=True)
                    _grand = sum(r.get("total_amount") or 0 for r in _bill_rows)
                    st.markdown(f"**ยอดรวมทั้งบิล: {_grand:,.0f} บาท** ({len(_bill_rows)} รายการ)")
                    st.warning(f"⚠️ จะลบบิล **{_sel_bill}** ({_bill_cust}) และทุกรายการข้างต้น — กู้คืนไม่ได้")
                st.divider()
                _del_chk_main = st.checkbox("ยืนยันการลบ", key="del_bill_confirm")
                if st.button("🗑️ ลบบิลนี้", type="primary", disabled=not _del_chk_main, key="del_bill_btn"):
                    _n = db.delete_bill(_sel_bill)
                    st.success(f"✅ ลบบิล {_sel_bill} แล้ว ({_n} รายการ)")
                    st.rerun()
            else:
                st.info("ไม่มีบิลในระบบ")
        st.divider()

        if not customers:
            st.info("ยังไม่มีข้อมูล")
        else:
            # ── Summary metrics ────────────────────────────────────────────────
            unbilled     = db.get_unbilled_pv_summary()
            outstanding_df = db.get_outstanding_df()
            if not outstanding_df.empty:
                sm1, sm2, sm3 = st.columns(3)
                sm1.metric("ค้างจ่ายรวม",   f"{outstanding_df['ค้างจ่าย'].sum():,.0f} ฿")
                sm2.metric("ค้างรับรวม",    f"{int(outstanding_df['ค้างรับ'].sum())} ชิ้น")
                sm3.metric("PV รอเปิดบิล", f"{unbilled['total_pv']:,.0f}")
                st.divider()

            # ── Filter ────────────────────────────────────────────────────────
            fc1, fc2, fc3 = st.columns([2, 2, 3])
            _t2_search      = fc1.text_input("🔍 ลูกค้า", placeholder="พิมพ์ชื่อ...", key="tab2_search")
            _t2_bill_search = fc2.text_input("🔍 เลขที่บิล", placeholder="เช่น 260427", key="tab2_bill_search")
            filter_bill = fc3.radio("สถานะบิล", ["ค้างอยู่ทั้งหมด", "ยังไม่เปิดบิล", "เปิดบิลแล้ว"],
                                    horizontal=True, key="tab2_filter_bill")
            if filter_bill == "ยังไม่เปิดบิล":
                outstanding_df = outstanding_df[outstanding_df["สถานะบิล"] == "ยังไม่เปิดบิล"]
            elif filter_bill == "เปิดบิลแล้ว":
                outstanding_df = outstanding_df[outstanding_df["สถานะบิล"] == "เปิดบิลแล้ว"]
            if _t2_search.strip():
                outstanding_df = outstanding_df[
                    outstanding_df["ลูกค้า"].str.contains(_t2_search.strip(), case=False, na=False)
                ]
            if _t2_bill_search.strip():
                outstanding_df = outstanding_df[
                    outstanding_df["เลขที่บิล"].fillna("").str.contains(_t2_bill_search.strip(), case=False)
                ]

            # ── ค้นด้วยเลขที่บิล: เปิดบิลตรง ๆ พร้อมพิมพ์/จัดการ ────────────────
            _bp_bill_q = _t2_bill_search.strip()
            if re.match(r'^\d{6}-\d+$', _bp_bill_q):
                _cust_map_all_g = {c["name"]: c for c in customers}
                with st.expander(f"📄 บิล {_bp_bill_q}", expanded=True):
                    _render_bill_panel(
                        None, _cust_map_all_g, None, customers,
                        key_prefix="bp_search", preselected_bill=_bp_bill_q,
                    )
                st.divider()

            _exp_cols2 = ["เลขที่บิล", "วันที่", "ลูกค้า", "รหัส", "สินค้า", "สั่ง",
                          "ค้างรับ", "ยอดรวม", "ค้างจ่าย", "สถานะบิล"]
            _avail_cols2 = [c for c in _exp_cols2 if c in outstanding_df.columns]
            _exp_df2 = outstanding_df[_avail_cols2]
            st.download_button(
                "⬇ Export Excel",
                _to_excel_bytes(_exp_df2, "ยอดค้าง"),
                file_name=f"ยอดค้าง_{date.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_outs",
            )

            if outstanding_df.empty:
                st.success("✅ ไม่มียอดค้าง")
            else:
                # โหลด line_user_id ของลูกค้าทั้งหมด
                _cust_line_map = {c["name"]: c.get("line_user_id") or "" for c in customers}
                _cust_gid_map  = {c["name"]: c.get("group_id") or "" for c in customers}
                _cust_map_all  = {c["name"]: c for c in customers}
                _all_txn_cache = db.get_all_transactions_df()

                single_cust = (_t2_search.strip() != "" or _t2_bill_search.strip() != "") and outstanding_df["ลูกค้า"].nunique() == 1
                _active_cust = st.session_state.get("_t5_out_active_cust", "")
                # pre-fetch shipments ครั้งเดียวแทนการเรียงใน loop (N+1 fix)
                try:
                    _all_ships = db.get_shipments()
                except Exception:
                    _all_ships = []
                _ship_by_cust: dict = {}
                for _s in _all_ships:
                    _ship_by_cust.setdefault(_s.get("customer_id", ""), []).append(_s)

                for customer_name, grp in outstanding_df.groupby("ลูกค้า"):
                    _is_cod = grp["สถานะจ่าย"] == "COD"
                    owed     = grp.loc[~_is_cod, "ค้างจ่าย"].sum()
                    owed_cod = grp.loc[_is_cod, "ค้างจ่าย"].sum()
                    pending = int(grp["ค้างรับ"].sum())
                    txn_ids = grp["id"].tolist()
                    _luid   = _cust_line_map.get(customer_name, "")
                    _gid    = _cust_gid_map.get(customer_name, "")
                    _unbilled_pv = grp.loc[grp["สถานะบิล"] == "ยังไม่เปิดบิล", "PV รวม"].sum() if "PV รวม" in grp.columns else 0
                    exp_label = (f"**{customer_name}** — ค้างจ่าย {owed:,.0f}฿"
                                 + (f" | 🟡 COD {owed_cod:,.0f}฿" if owed_cod > 0 else "")
                                 + f" | ค้างรับ {pending} ชิ้น"
                                 + (f" | ⭐ PV ค้างเปิดบิล {_unbilled_pv:,.0f}" if _unbilled_pv > 0 else ""))

                    with st.expander(exp_label, expanded=(single_cust or customer_name == _active_cust)):
                        # ── 🖨️ พิมพ์ / จัดการบิล ───────────────────────────────
                        with st.expander("🖨️ พิมพ์ / จัดการบิล"):
                            _cust_obj_bp = _cust_map_all.get(customer_name)
                            _bp_id = _cust_obj_bp["id"] if _cust_obj_bp else customer_name
                            _render_bill_panel(
                                customer_name, _cust_map_all, _all_txn_cache, customers,
                                key_prefix=f"bp_{_bp_id}",
                            )
                        st.divider()

                        # ── ใบรับของ popup ───────────────────────────────────
                        _rp = st.session_state.get("_recv_popup")
                        if _rp and _rp.get("customer_name") == customer_name:
                            def _prod_label(it):
                                code = it.get("product_code", "")
                                return f"[{code}] {it['product']}" if code else it["product"]
                            _recv_rows_html = "".join(
                                f"<tr><td>{_prod_label(it)}</td><td style='text-align:center'>{it['qty']}</td></tr>"
                                for it in _rp["received"]
                            )
                            _pend_rows_html = "".join(
                                f"<tr><td>{_prod_label(it)}</td><td style='text-align:center'>{it['qty']}</td></tr>"
                                for it in _rp["pending"]
                            ) or "<tr><td colspan='2' style='color:#888'>ไม่มีค้างรับ</td></tr>"
                            _recv_html = f"""<!DOCTYPE html><html><head><meta charset='UTF-8'>
    <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    html,body{{background:#fff!important;color:#000!important}}
    body{{font-family:'Sarabun',sans-serif;padding:16px;font-size:13px}}
    .header{{border-bottom:2px solid #000;padding-bottom:8px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:flex-start}}
    .header h1{{font-size:16px;font-weight:700}}
    .header h2{{font-size:14px;font-weight:600;margin-top:2px}}
    .header-right{{text-align:right;font-size:13px;font-weight:600}}
    .section{{margin:10px 0}}
    .section b{{font-size:13px}}
    table{{width:100%;border-collapse:collapse;margin:6px 0;border:1px solid #000}}
    th{{background:#000;color:#fff;padding:5px 6px;font-size:12px;text-align:left;border:1px solid #000}}
    td{{padding:4px 6px;border:1px solid #aaa;font-size:12px;color:#000}}
    tr:nth-child(even) td{{background:#f0f0f0}}
    .sig{{margin-top:32px;border-top:1px solid #000;padding-top:4px;min-width:200px;display:inline-block;text-align:center;font-size:12px}}
    .btn{{display:block;margin:0 0 12px;padding:6px 22px;background:#c0392b;color:#fff;border:none;cursor:pointer;border-radius:5px;font-size:13px}}
    @media print{{.btn{{display:none}}@page{{size:A5 portrait;margin:10mm}}*{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}th{{background:#000!important;color:#fff!important}}tr:nth-child(even) td{{background:#eee!important}}}}
    </style></head><body>
    <button class='btn' onclick='window.print()'>🖨️ พิมพ์ใบรับของ</button>
    <div class='header'>
      <div><h1>ใบรับของ ZHULIAN TBY</h1><h2>ลูกค้า: {_rp['customer_name']}</h2></div>
      <div class='header-right'>วันที่: {_rp['date']}</div>
    </div>
    <div class='section'><b>รายการที่รับวันนี้:</b>
    <table><tr><th>รหัส / สินค้า</th><th style='text-align:center;width:80px'>จำนวนรับ</th></tr>{_recv_rows_html}</table></div>
    <div class='section' style='margin-top:14px'><b>ยังค้างรับ:</b>
    <table><tr><th>รหัส / สินค้า</th><th style='text-align:center;width:80px'>ค้างรับ</th></tr>{_pend_rows_html}</table></div>
    <div style='margin-top:24px'><div class='sig'>ลายเซ็นผู้รับ</div></div>
    </body></html>"""
                            components.html(_recv_html, height=430, scrolling=False)
                            if st.button("✕ ปิดใบรับของ", key=f"close_recv_{customer_name}"):
                                del st.session_state["_recv_popup"]
                                st.rerun()
                            st.divider()

                        # ── ปุ่มแจ้ง LINE รับของ/จ่ายเงินบางส่วน ──────────────
                        _pr = st.session_state.get("_partial_recv_line")
                        if _pr and _pr.get("customer_name") == customer_name:
                            _pr_c1, _pr_c2 = st.columns([3, 1])
                            _pr_items = _pr.get("items")
                            if _pr_items:
                                _pr_summary = " + ".join(
                                    (f"[{it['product_code']}] " if it.get("product_code") else "")
                                    + it.get("product_name", "")
                                    + (f" ×{it['qty_received']}" if it.get("qty_received", 0) > 0 else "")
                                    for it in _pr_items
                                )
                            else:
                                _pr_summary = (f"📦 {_pr['product_name']}" if _pr.get("product_name") else "")
                                if _pr.get("qty_received", 0) > 0:
                                    _pr_summary += f" ×{int(_pr['qty_received'])}"
                            _pr_c1.info(
                                _pr_summary
                                + (f" · จ่าย {_pr['amount_paid']:,.0f} ฿" if _pr.get("amount_paid", 0) > 0.01 else "")
                            )
                            if _pr_c2.button("📨 แจ้ง LINE", key=f"pr_line_{customer_name}", type="primary", use_container_width=True):
                                _pr_res = line_api.push_partial_receipt(
                                    _pr["line_user_id"], _pr.get("product_name", ""),
                                    _pr.get("qty_received", 0), _pr["amount_paid"],
                                    _pr["remaining_qty"], _pr["remaining_amount"],
                                    product_code=_pr.get("product_code", ""),
                                    group_id=_pr.get("group_id", ""),
                                    items=_pr_items,
                                )
                                if _pr_res.get("ok"):
                                    st.success("✅ ส่ง LINE แล้ว")
                                    del st.session_state["_partial_recv_line"]
                                else:
                                    st.error(f"❌ {_pr_res.get('error')}")
                            st.divider()

                        # ── LINE แจ้งยอดค้าง ─────────────────────────────────
                        if line_api.is_configured():
                            _line_items = [
                                {"bill_no": r["เลขที่บิล"],
                                 "product": f"[{r['รหัส']}] {r['สินค้า']}" if r.get("รหัส") else r["สินค้า"],
                                 "amount": 0.0 if r["สถานะจ่าย"] == "COD" else float(r["ค้างจ่าย"]),
                                 "qty": int(r["ค้างรับ"])}
                                for _, r in grp.iterrows()
                                if float(r["ค้างจ่าย"]) > 0 or int(r["ค้างรับ"]) > 0
                            ]
                            # COD ที่โอนแล้วรอเปิดบิล
                            _cust_obj  = next((c for c in customers if c["name"] == customer_name), None)
                            _cod_done  = []
                            if _cust_obj:
                                _sh_list = _ship_by_cust.get(_cust_obj["id"], [])
                                _cod_done = [
                                        {"tracking_no": s.get("tracking_no",""), "cod_amount": float(s.get("cod_amount") or 0)}
                                        for s in _sh_list
                                        if s.get("cod_transferred_at") and float(s.get("cod_amount") or 0) > 0
                                    ]
                            if st.button(
                                "📨 แจ้ง LINE" if _luid else "📨 ไม่มี LINE ID",
                                key=f"line_out_{customer_name}",
                                disabled=not _luid,
                                help=None if _luid else "ยังไม่มี line_user_id ของลูกค้านี้",
                            ):
                                _r = line_api.push_outstanding(
                                    _luid, customer_name, owed, pending, _line_items, _cod_done,
                                    group_id=_gid,
                                )
                                if _r.get("ok"):
                                    st.success("✅ ส่ง LINE แล้ว")
                                else:
                                    st.error(f"❌ {_r.get('error')}")
                        # ── Styled table + row selection ──────────────────────
                        _dcols  = ["เลขที่บิล", "วันที่", "รหัส", "สินค้า", "สั่ง", "ค้างรับ",
                                   "ยอดรวม", "ค้างจ่าย", "สถานะจ่าย", "สถานะบิล"]
                        _id_map = grp["id"].reset_index(drop=True)
                        st.caption("คลิกแถวเพื่อเลือก (Ctrl/Shift สำหรับหลายแถว)")
                        _evt = st.dataframe(
                            grp[_dcols].reset_index(drop=True).style
                                .format({"ยอดรวม": "{:,.0f}", "ค้างจ่าย": "{:,.0f}"})
                                .map(_style_status, subset=["สถานะบิล", "สถานะจ่าย"])
                                .map(lambda v: "background-color:#6b1a1a;color:white"
                                     if isinstance(v, (int, float)) and v > 0 else "",
                                     subset=["ค้างรับ", "ค้างจ่าย"]),
                            use_container_width=True,
                            hide_index=True,
                            selection_mode="multi-row",
                            on_select="rerun",
                            key=f"sel_tbl_{customer_name}",
                        )
                        _sel_idx  = _evt.selection.rows if hasattr(_evt, "selection") else []
                        selected_ids = [_id_map.iloc[i] for i in _sel_idx if i < len(_id_map)]

                        if selected_ids:
                            # จำไว้ว่ากำลังจัดการลูกค้าคนนี้อยู่ เพื่อให้แผงนี้เปิดค้างไว้หลัง rerun (เช่นกดบันทึก)
                            st.session_state["_t5_out_active_cust"] = customer_name
                            sel_rows       = grp[grp["id"].isin(selected_ids)]
                            total_selected = sel_rows["ค้างจ่าย"].sum()
                            _sel_pv = sel_rows["PV รวม"].sum() if "PV รวม" in sel_rows.columns else 0
                            _pv_str = f"  |  ⭐ PV รวม **{_sel_pv:,.0f}**" if _sel_pv > 0 else ""
                            st.info(f"เลือก {len(selected_ids)} รายการ — ค้างจ่ายรวม **{total_selected:,.0f} บาท**{_pv_str}")

                        st.divider()

                        # ── Action panel ──────────────────────────────────────
                        if len(selected_ids) == 0:
                            st.info("☝️ เลือกรายการด้านบนเพื่อดำเนินการ")

                        elif len(selected_ids) == 1:
                            txn_id  = selected_ids[0]
                            balance = db.get_transaction_balance(txn_id)
                            if not balance:
                                st.warning("ไม่พบรายการนี้ในฐานข้อมูล")
                                st.stop()
                            txn     = balance["transaction"]
                            sel_row = grp[grp["id"] == txn_id].iloc[0]

                            _owed_label = "🟡 COD" if txn["pay_status"] == "COD" else "ค้างจ่าย"
                            st.caption(
                                f"📅 {sel_row['วันที่']}  ·  "
                                f"ราคา {float(txn['price_per_unit']):,.0f} ฿/ชิ้น  ·  "
                                f"รวม {float(txn['total_amount']):,.0f} ฿  ·  "
                                f"จ่ายแล้ว {balance['total_paid']:,.0f} ฿  ·  "
                                f"{_owed_label} **{balance['outstanding_amount']:,.0f} ฿**  ·  "
                                f"รับแล้ว {balance['total_received']} ชิ้น  ·  "
                                f"ค้างรับ {balance['outstanding_qty']} ชิ้น"
                            )

                            is_unbilled = txn["bill_status"] == "ยังไม่เปิดบิล"
                            radio_opts  = (["📄 เปิดบิล"] if is_unbilled else []) + [
                                "💵 จ่ายเงิน", "📦 รับของ", "💵+📦 จ่ายเงิน + รับของ"
                            ]
                            action = st.radio("บันทึก", radio_opts, horizontal=True, key=f"etype_{txn_id}")

                            if action == "📄 เปิดบิล":
                                with st.form(f"bill_{txn_id}", clear_on_submit=True):
                                    bc1, bc2 = st.columns([3, 1])
                                    qty_to_open = bc1.number_input(
                                        "จำนวนที่เปิดบิล", min_value=1,
                                        max_value=int(txn["qty"]), value=int(txn["qty"]), step=1,
                                    )
                                    bc2.write("")
                                    submit_bill = bc2.form_submit_button(
                                        "📄 เปิดบิล", use_container_width=True, type="primary"
                                    )
                                if submit_bill:
                                    if qty_to_open == int(txn["qty"]):
                                        db.update_transaction_status(txn_id, bill_status="เปิดบิลแล้ว")
                                    else:
                                        db.split_and_open_bill(txn_id, qty_to_open)
                                    st.rerun()
                            else:
                                evt_map  = {
                                    "💵 จ่ายเงิน": "จ่ายเงิน",
                                    "📦 รับของ": "รับของ",
                                    "💵+📦 จ่ายเงิน + รับของ": "ทั้งคู่",
                                }
                                evt_type = evt_map[action]
                                _price   = float(txn["price_per_unit"])
                                _outs_q  = int(balance["outstanding_qty"])
                                _hint    = f"ราคา/ชิ้น: {_price:,.0f} ฿"
                                for _n in range(1, min(_outs_q, 5) + 1):
                                    _hint += f"  ·  {_n} ชิ้น = {_n * _price:,.0f} ฿"
                                st.caption(_hint)
                                _def_amt = max(0.0, float(balance["outstanding_amount"])) if evt_type != "รับของ" else 0.0
                                _def_qty = _outs_q if evt_type != "จ่ายเงิน" else 0
                                with st.form(f"evt_{txn_id}", clear_on_submit=True):
                                    fc1, fc2, fc3 = st.columns([2, 2, 1])
                                    amount_paid  = fc1.number_input(
                                        "เงินที่จ่าย (บาท)", min_value=0.0, step=100.0,
                                        value=_def_amt,
                                        disabled=(evt_type == "รับของ"),
                                    )
                                    qty_received = fc2.number_input(
                                        "จำนวนที่รับ (ชิ้น)", min_value=0, step=1,
                                        value=_def_qty,
                                        disabled=(evt_type == "จ่ายเงิน"),
                                    )
                                    event_date  = fc3.date_input("วันที่", value=date.today())
                                    event_notes = st.text_input("หมายเหตุ", key=f"enotes_{txn_id}")
                                    _also_open_bill = False
                                    if is_unbilled:
                                        _also_open_bill = st.checkbox(
                                            "📄 เปิดบิลด้วย", value=False,
                                            key=f"also_open_{txn_id}",
                                        )
                                    submit_evt  = st.form_submit_button(
                                        "💾 บันทึก", use_container_width=True, type="primary"
                                    )
                                if submit_evt:
                                    error = None
                                    if evt_type == "จ่ายเงิน + รับของ" and qty_received > 0:
                                        new_paid = balance["total_paid"] + amount_paid
                                        price    = float(txn["price_per_unit"])
                                        max_ok   = floor(new_paid / price) if price > 0 else 0
                                        if balance["total_received"] + qty_received > max_ok:
                                            can   = max(0, max_ok - balance["total_received"])
                                            error = f"❌ รับได้สูงสุด {can} ชิ้น (จ่ายแล้ว {new_paid:,.0f} บาท)"
                                    elif evt_type == "รับของ" and qty_received > balance["outstanding_qty"]:
                                        error = f"❌ รับได้สูงสุด {balance['outstanding_qty']} ชิ้น (ค้างรับอยู่)"
                                    if error:
                                        st.error(error)
                                    else:
                                        try:
                                            db.insert_partial_event({
                                                "id":             str(uuid.uuid4()),
                                                "date":           str(event_date),
                                                "transaction_id": txn_id,
                                                "qty_received":   int(qty_received),
                                                "amount_paid":    float(amount_paid),
                                                "event_type":     evt_type,
                                                "notes":          event_notes,
                                            })
                                        except Exception as _pe:
                                            st.error(f"❌ DB error: {_pe}")
                                            st.stop()
                                        if _also_open_bill:
                                            db.update_transaction_status(txn_id, bill_status="เปิดบิลแล้ว")
                                        if amount_paid > 0:
                                            _new_total_paid = balance["total_paid"] + amount_paid
                                            if _new_total_paid >= float(txn["total_amount"]) - 0.01:
                                                db.update_transaction_status(txn_id, pay_status="จ่ายแล้ว")
                                        db.get_all_transactions_df.clear()
                                        if int(qty_received) > 0:
                                            _rp_pending = []
                                            for _, _rr in grp.iterrows():
                                                _pq = int(_rr["ค้างรับ"])
                                                if _rr["id"] == txn_id:
                                                    _pq = max(0, _pq - int(qty_received))
                                                if _pq > 0:
                                                    _rp_pending.append({"product": _rr["สินค้า"], "qty": _pq, "product_code": _rr.get("รหัส", "")})
                                            st.session_state["_recv_popup"] = {
                                                "customer_name": customer_name,
                                                "date": str(event_date),
                                                "received": [{"product": txn["product_name"], "qty": int(qty_received), "product_code": txn.get("product_id", "")}],
                                                "pending": _rp_pending,
                                            }
                                        if _luid and line_api.is_configured() and (qty_received > 0 or amount_paid > 0.01):
                                            _new_recv_qty = balance["total_received"] + int(qty_received)
                                            _new_paid_amt = balance["total_paid"] + amount_paid
                                            _rem_qty = max(0, int(txn["qty"]) - _new_recv_qty)
                                            _rem_amt = max(0.0, float(txn["total_amount"]) - _new_paid_amt)
                                            st.session_state["_partial_recv_line"] = {
                                                "customer_name": customer_name,
                                                "line_user_id":  _luid,
                                                "group_id":      _gid,
                                                "product_name":  txn["product_name"],
                                                "product_code":  txn.get("product_id", ""),
                                                "qty_received":  qty_received,
                                                "amount_paid":   amount_paid,
                                                "remaining_qty": _rem_qty,
                                                "remaining_amount": _rem_amt,
                                            }
                                        st.success("✅ บันทึกแล้ว")
                                        st.rerun()

                            if not is_unbilled:
                                st.divider()
                                if st.button("↩️ ยกเลิกบิล", key=f"cancel_{txn_id}"):
                                    db.update_transaction_status(txn_id, bill_status="ยังไม่เปิดบิล")
                                    st.rerun()

                            # ── ลบบิล ─────────────────────────────────────────
                            _del_bno_vals = grp.loc[grp["id"] == txn_id, "เลขที่บิล"].values
                            _del_bno = str(_del_bno_vals[0]) if len(_del_bno_vals) > 0 and _del_bno_vals[0] else ""
                            if _del_bno and _del_bno not in ("—", ""):
                                st.divider()
                                _del_bill_rows = grp.loc[grp["เลขที่บิล"] == _del_bno]
                                st.dataframe(_del_bill_rows[["สินค้า", "สั่ง", "ยอดรวม"]], use_container_width=True, hide_index=True)
                                st.warning(f"⚠️ จะลบบิล **{_del_bno}** ({_del_bill_rows['ยอดรวม'].sum():,.0f} ฿) และทุกรายการข้างต้น — กู้คืนไม่ได้")
                                _del_chk = st.checkbox(
                                    f"ยืนยันลบบิล {_del_bno}",
                                    key=f"del_bill_chk_{txn_id}",
                                )
                                if _del_chk:
                                    if st.button(
                                        f"🗑️ ลบบิล {_del_bno}", type="primary",
                                        key=f"del_bill_now_{txn_id}",
                                    ):
                                        db.delete_bill(_del_bno)
                                        st.success(f"✅ ลบบิล {_del_bno} แล้ว")
                                        st.rerun()

                            # ── ลบรายการนี้ (เฉพาะแถวนี้) ─────────────────────
                            st.divider()
                            _del_row_chk = st.checkbox(
                                f"🗑️ ลบเฉพาะรายการ **{sel_row['สินค้า']}** แถวนี้ (ไม่กระทบรายการอื่นในบิล)",
                                key=f"del_row_chk_{txn_id}",
                            )
                            if _del_row_chk:
                                if st.button(
                                    f"🗑️ ยืนยันลบรายการ {sel_row['สินค้า']}", type="primary",
                                    key=f"del_row_now_{txn_id}",
                                ):
                                    db.delete_transaction(txn_id)
                                    st.success("✅ ลบรายการแล้ว")
                                    st.rerun()

                        else:
                            # Multi: ทำทุกอย่างพร้อมกันในตารางเดียว
                            sel_rows      = grp[grp["id"].isin(selected_ids)].copy()
                            total_owed    = float(sel_rows["ค้างจ่าย"].sum())
                            _combo_rows = [{
                                "_id":       r["id"],
                                "สินค้า":    r["สินค้า"],
                                "เลขที่บิล": r["เลขที่บิล"] or "—",
                                "ค้างรับ":   int(r["ค้างรับ"]),
                                "รับจริง":   int(r["ค้างรับ"]),
                                "ค้างจ่าย":  float(r["ค้างจ่าย"]),
                                "จ่ายจริง":  float(r["ค้างจ่าย"]),
                                "สถานะบิล":  r["สถานะบิล"],
                            } for _, r in sel_rows.iterrows()]
                            _combo_df = pd.DataFrame(_combo_rows)

                            _combo_edit = st.data_editor(
                                _combo_df[["สินค้า","เลขที่บิล","ค้างรับ","รับจริง","ค้างจ่าย","จ่ายจริง","สถานะบิล"]],
                                column_config={
                                    "สินค้า":    st.column_config.TextColumn(disabled=True),
                                    "เลขที่บิล": st.column_config.TextColumn(disabled=True),
                                    "ค้างรับ":   st.column_config.NumberColumn(disabled=True),
                                    "รับจริง":   st.column_config.NumberColumn("รับจริง ✏️", min_value=0, format="%d"),
                                    "ค้างจ่าย":  st.column_config.NumberColumn(disabled=True, format="%.0f"),
                                    "จ่ายจริง":  st.column_config.NumberColumn("จ่ายจริง ✏️", min_value=0, format="%.0f"),
                                    "สถานะบิล":  st.column_config.TextColumn(disabled=True),
                                },
                                hide_index=True, use_container_width=True,
                                key=f"multi_combo_{customer_name}",
                            )

                            _unbilled_mask = sel_rows["สถานะบิล"] == "ยังไม่เปิดบิล"
                            _any_unbilled  = _unbilled_mask.any()
                            _unbilled_cnt  = int(_unbilled_mask.sum())
                            _unbilled_pv   = sel_rows.loc[_unbilled_mask, "PV รวม"].sum() if "PV รวม" in sel_rows.columns else 0
                            _do_open_bill  = False
                            if _any_unbilled:
                                _ob_pv_str = f", ⭐ {_unbilled_pv:,.0f} PV" if _unbilled_pv > 0 else ""
                                st.markdown(
                                    "<style>[data-testid='stCheckbox'] > label > div:last-child "
                                    "{ font-size: 1.15rem; font-weight: 700; }</style>",
                                    unsafe_allow_html=True,
                                )
                                _do_open_bill = st.checkbox(
                                    f"📄 เปิดบิลด้วย ({_unbilled_cnt} รายการที่ยังไม่เปิดบิล{_ob_pv_str})",
                                    key=f"multi_open_chk_{customer_name}",
                                )

                            _mc_c1, _mc_c2 = st.columns([2, 1])
                            mc_notes = _mc_c1.text_input("หมายเหตุ", key=f"mc_notes_{customer_name}")
                            mc_date  = _mc_c2.date_input("วันที่", value=date.today(), key=f"mc_date_{customer_name}")

                            _mc_recv = int(_combo_edit["รับจริง"].sum())
                            _mc_pay  = float(_combo_edit["จ่ายจริง"].sum())
                            _ms1, _ms2 = st.columns(2)
                            if _mc_recv > 0:
                                _ms1.metric("รับของรวม", f"{_mc_recv} ชิ้น")
                            if _mc_pay > 0.01:
                                _ms2.metric("ยอดจ่ายรวม", f"{_mc_pay:,.0f} ฿")

                            if st.button("💾 บันทึกทั้งหมด", type="primary",
                                         use_container_width=True, key=f"multi_all_{customer_name}"):
                                _saved_r, _saved_p = 0, 0
                                _mrp_received, _mrp_id_qty = [], {}
                                _total_paid_actual = 0.0
                                for i, row in _combo_df.iterrows():
                                    _qty   = int(_combo_edit.iloc[i]["รับจริง"])
                                    _amt   = float(_combo_edit.iloc[i]["จ่ายจริง"])
                                    _owed  = float(row["ค้างจ่าย"])
                                    _cap_r = int(row["ค้างรับ"])
                                    _actual_qty = min(_qty, _cap_r) if _qty > 0 else 0
                                    _actual_amt = min(_amt, _owed) if _amt > 0.01 else 0.0
                                    if _actual_qty <= 0 and _actual_amt <= 0.01:
                                        continue
                                    _etype = (
                                        "ทั้งคู่"   if _actual_qty > 0 and _actual_amt > 0.01
                                        else ("รับของ" if _actual_qty > 0 else "จ่ายเงิน")
                                    )
                                    db.insert_partial_event({
                                        "id":             str(uuid.uuid4()),
                                        "date":           str(mc_date),
                                        "transaction_id": row["_id"],
                                        "qty_received":   _actual_qty,
                                        "amount_paid":    round(_actual_amt, 2),
                                        "event_type":     _etype,
                                        "notes":          mc_notes,
                                    })
                                    if _actual_qty > 0:
                                        _saved_r += 1
                                        _mrp_received.append({"product": row["สินค้า"], "qty": _actual_qty, "product_code": row.get("รหัส", "")})
                                        _mrp_id_qty[row["_id"]] = _actual_qty
                                    if _actual_amt > 0.01:
                                        _total_paid_actual += _actual_amt
                                        _saved_p += 1
                                        if _actual_amt >= _owed - 0.01:
                                            db.update_transaction_status(row["_id"], pay_status="จ่ายแล้ว")
                                if _do_open_bill:
                                    for i, row in _combo_df.iterrows():
                                        if row["สถานะบิล"] == "ยังไม่เปิดบิล":
                                            db.update_transaction_status(row["_id"], bill_status="เปิดบิลแล้ว")
                                # popup รับของ + LINE notification
                                _mrp_pending = []
                                for _, _rr in grp.iterrows():
                                    _pq = int(_rr["ค้างรับ"])
                                    if _rr["id"] in _mrp_id_qty:
                                        _pq = max(0, _pq - _mrp_id_qty[_rr["id"]])
                                    if _pq > 0:
                                        _mrp_pending.append({"product": _rr["สินค้า"], "qty": _pq, "product_code": _rr.get("รหัส", "")})
                                if _mrp_received:
                                    st.session_state["_recv_popup"] = {
                                        "customer_name": customer_name,
                                        "date":          str(mc_date),
                                        "received":      _mrp_received,
                                        "pending":       _mrp_pending,
                                    }
                                if _luid and line_api.is_configured() and (_mrp_received or _total_paid_actual > 0.01):
                                    _rem_qty_all = sum(_pq for _, _rr in grp.iterrows()
                                                       for _pq in [max(0, int(_rr["ค้างรับ"]) - _mrp_id_qty.get(_rr["id"], 0))])
                                    _rem_amt_all = max(0.0, float(grp["ค้างจ่าย"].sum()) - _total_paid_actual)
                                    st.session_state["_partial_recv_line"] = {
                                        "customer_name":    customer_name,
                                        "line_user_id":     _luid,
                                        "group_id":         _gid,
                                        "product_name":     "",
                                        "product_code":     "",
                                        "qty_received":     sum(it["qty"] for it in _mrp_received),
                                        "amount_paid":      _total_paid_actual,
                                        "remaining_qty":    _rem_qty_all,
                                        "remaining_amount": _rem_amt_all,
                                        "items": [
                                            {"product_name": it["product"], "product_code": it.get("product_code", ""), "qty_received": it["qty"]}
                                            for it in _mrp_received
                                        ],
                                    }
                                _parts = []
                                if _saved_r:
                                    _parts.append(f"รับของ {_saved_r} รายการ")
                                if _saved_p:
                                    _parts.append(f"จ่าย ฿{_mc_pay:,.0f}")
                                if _do_open_bill:
                                    _parts.append(f"เปิดบิล {len(selected_ids)} รายการ")
                                if _parts:
                                    st.success("✅ บันทึก: " + " + ".join(_parts))
                                    for tid in txn_ids:
                                        st.session_state[f"chk_{tid}"] = False
                                    st.rerun()
                                else:
                                    st.warning("ไม่มีรายการที่ต้องบันทึก (ทุกช่องเป็น 0)")

                            # ── ลบบิล (multi) ────────────────────────────────
                            _del_bnos = sorted({
                                str(b) for b in sel_rows["เลขที่บิล"].dropna()
                                if b and str(b) not in ("—", "")
                            })
                            if _del_bnos:
                                st.divider()
                                _del_bills_rows = grp.loc[grp["เลขที่บิล"].isin(_del_bnos)]
                                st.dataframe(_del_bills_rows[["เลขที่บิล", "สินค้า", "สั่ง", "ยอดรวม"]], use_container_width=True, hide_index=True)
                                st.warning(f"⚠️ จะลบบิล **{', '.join(_del_bnos)}** ({_del_bills_rows['ยอดรวม'].sum():,.0f} ฿) และทุกรายการข้างต้น — กู้คืนไม่ได้")
                                _del_chk_m = st.checkbox(
                                    f"ยืนยันลบ {len(_del_bnos)} บิล",
                                    key=f"del_bill_chk_multi_{customer_name}",
                                )
                                if _del_chk_m:
                                    if st.button(
                                        f"🗑️ ลบ {len(_del_bnos)} บิล", type="primary",
                                        key=f"del_bill_now_multi_{customer_name}",
                                    ):
                                        _total_del = sum(db.delete_bill(b) for b in _del_bnos)
                                        st.success(f"✅ ลบแล้ว {len(_del_bnos)} บิล ({_total_del} รายการ)")
                                        st.rerun()

                            # ── ลบเฉพาะรายการที่เลือก (multi, ไม่ลบทั้งบิล) ────
                            st.divider()
                            _del_items_chk = st.checkbox(
                                f"🗑️ ลบเฉพาะ {len(selected_ids)} รายการที่เลือก (ไม่กระทบรายการอื่นในบิล)",
                                key=f"del_items_chk_multi_{customer_name}",
                            )
                            if _del_items_chk:
                                if st.button(
                                    f"🗑️ ยืนยันลบ {len(selected_ids)} รายการ", type="primary",
                                    key=f"del_items_now_multi_{customer_name}",
                                ):
                                    db.delete_transactions_batch(selected_ids)
                                    st.success(f"✅ ลบแล้ว {len(selected_ids)} รายการ")
                                    st.rerun()


    elif _t5_active == _T5_TABS[1]:
        _led_h1, _led_h2 = st.columns([5, 1])
        _led_h1.subheader("บัตรลูกค้า")
        if _led_h2.button("🔄 รีเฟรชยอด", key="t5_ledger_refresh", help="กดก่อนบันทึกรับเงิน/รับของ เผื่อลูกค้าจ่าย/รับของผ่าน LINE มาแล้ว"):
            db._clear_transaction_caches()
            st.rerun()
        _l_customers = customers
        _l_all_names_df = db.get_all_transactions_df()
        _l_cust_with_txn = set(_l_all_names_df["ลูกค้า"].dropna().unique()) if not _l_all_names_df.empty else set()
        _l_opts = ["— เลือกลูกค้า —"] + sorted(
            [c["name"] for c in _l_customers if c["name"] in _l_cust_with_txn],
            key=str.casefold,
        )
        _lx1, _lx2 = st.columns([3, 2])
        _l_sel = _lx1.selectbox("👤 ลูกค้า", _l_opts, key="t5_ledger_cust")
        if _l_sel != "— เลือกลูกค้า —":
            _l_cust = next((c for c in _l_customers if c["name"] == _l_sel), None)
            if _l_cust:
                _l_data = db.get_customer_ledger(_l_cust["id"])
                if _l_data:
                    # ── แยกประเภท ────────────────────────────────────────────
                    _l_orders   = [r for r in _l_data if r["type"] == "สั่งซื้อ"]
                    _l_payments = [r for r in _l_data if r["type"] == "จ่ายเงิน"]
                    _l_receipts = [r for r in _l_data if r["type"] in ("รับของ", "แก้ไขรับ")]
                    _l_ships    = [r for r in _l_data if "ส่งของ" in r["type"]]

                    # ── summary metrics ──────────────────────────────────────
                    _l_ord_qty  = sum(r["qty_in"]  for r in _l_orders)
                    _l_recv_qty = sum(r["qty_out"] for r in _l_receipts) + sum(r.get("initial_received", 0) for r in _l_orders)
                    _l_paid_tot = (
                        sum(r.get("total_amount", 0) for r in _l_orders if r.get("pay_status") == "จ่ายแล้ว")
                        + sum(r["amount"] for r in _l_payments)
                    )
                    _sm1, _sm2, _sm3, _sm4 = st.columns(4)
                    _sm1.metric("สั่งซื้อ",  f"{_l_ord_qty:,} ชิ้น")
                    _sm2.metric("รับแล้ว",   f"{_l_recv_qty:,} ชิ้น")
                    _sm3.metric("ค้างรับ",   f"{max(0, _l_ord_qty - _l_recv_qty):,} ชิ้น")
                    _sm4.metric("จ่ายแล้ว",  f"{_l_paid_tot:,.0f} ฿")

                    # ── สรุปรายสินค้า ────────────────────────────────────────
                    _l_all_df = _ledger_to_txn_df(_l_data)
                    with st.expander("📊 สรุปรายสินค้า", expanded=False):
                        _l_txn_df = _l_all_df
                        if not _l_txn_df.empty:
                            _billed_df = _l_txn_df[_l_txn_df["สถานะบิล"] == "เปิดบิลแล้ว"]
                            _unbilled_df = _l_txn_df[_l_txn_df["สถานะบิล"] == "ยังไม่เปิดบิล"]
                            _unbilled_paid = _unbilled_df[_unbilled_df["สถานะจ่าย"].isin(["จ่ายแล้ว", "COD จ่ายแล้ว"])]
                            _unbilled_unpaid = _unbilled_df[~_unbilled_df["สถานะจ่าย"].isin(["จ่ายแล้ว", "COD จ่ายแล้ว"])]

                            # ── ตาราง 1: สรุปบิล (เปิดบิลค้างจ่าย vs จ่ายล่วงหน้า) ──
                            st.markdown("**📋 สรุปบิล**")
                            _ps_billed_qty = _billed_df.groupby("รหัส")["สั่ง"].sum().rename("เปิดบิล")
                            _ps_billed_owed = _billed_df.groupby("รหัส")["ค้างจ่าย"].sum().rename("ค้างจ่ายบิล")
                            _ps_prepaid_qty = _unbilled_paid.groupby("รหัส")["สั่ง"].sum().rename("จ่ายแล้ว(ชิ้น)")
                            _ps_prepaid_amt = _unbilled_paid.groupby("รหัส")["จ่ายแล้ว"].sum().rename("จ่ายล่วงหน้า")
                            _all_products = _l_txn_df.groupby("รหัส").agg(สินค้า=("สินค้า","first")).reset_index()
                            _bill_sum = (_all_products.set_index("รหัส")
                                         .join(_ps_billed_qty).join(_ps_billed_owed)
                                         .join(_ps_prepaid_qty).join(_ps_prepaid_amt)
                                         .fillna(0).reset_index())
                            _bill_sum["เปิดบิล"] = _bill_sum["เปิดบิล"].astype(int)
                            _bill_sum["จ่ายแล้ว(ชิ้น)"] = _bill_sum["จ่ายแล้ว(ชิ้น)"].astype(int)
                            _bill_sum["ค้างสุทธิ"] = (_bill_sum["ค้างจ่ายบิล"] - _bill_sum["จ่ายล่วงหน้า"]).clip(lower=0)
                            _bill_sum["เครดิตเหลือ"] = (_bill_sum["จ่ายล่วงหน้า"] - _bill_sum["ค้างจ่ายบิล"]).clip(lower=0)
                            _bill_owed = _bill_sum[_bill_sum["ค้างสุทธิ"] > 0.01]
                            _bill_credit = _bill_sum[_bill_sum["เครดิตเหลือ"] > 0.01]

                            if not _bill_owed.empty:
                                st.dataframe(
                                    _bill_owed[["รหัส","สินค้า","เปิดบิล","ค้างจ่ายบิล","จ่ายแล้ว(ชิ้น)","จ่ายล่วงหน้า","ค้างสุทธิ"]]
                                    .style.format({"ค้างจ่ายบิล":"{:,.0f}","จ่ายล่วงหน้า":"{:,.0f}","ค้างสุทธิ":"{:,.0f}"}),
                                    use_container_width=True, hide_index=True,
                                )
                                _net = _bill_owed["ค้างสุทธิ"].sum()
                                _pre = _bill_owed["จ่ายล่วงหน้า"].sum()
                                st.caption(
                                    f"ค้างจ่ายบิล {_bill_owed['ค้างจ่ายบิล'].sum():,.0f} ฿"
                                    + (f" − จ่ายล่วงหน้า {_pre:,.0f} ฿" if _pre > 0 else "")
                                    + f" = **ค้างสุทธิ {_net:,.0f} ฿**"
                                )

                            if not _bill_credit.empty:
                                _price_map = {p["id"]: float(p.get("price") or 0) for p in products}
                                _pv_map    = {p["id"]: float(p.get("points_per_unit") or 0) for p in products}
                                _cr_rows = []
                                for _, _cr in _bill_credit.iterrows():
                                    _cr_amt = _cr["เครดิตเหลือ"]
                                    _pr = _price_map.get(_cr["รหัส"], 0)
                                    _cr_qty = int(_cr_amt // _pr) if _pr > 0 else 0
                                    _cr_pv = _cr_qty * _pv_map.get(_cr["รหัส"], 0)
                                    _cr_rows.append({
                                        "รหัส": _cr["รหัส"], "สินค้า": _cr["สินค้า"],
                                        "เครดิตเหลือ": _cr_amt, "เปิดบิลเพิ่มได้": _cr_qty,
                                        "PV": _cr_pv,
                                    })
                                _cr_df = pd.DataFrame(_cr_rows)
                                st.markdown("**💚 เครดิตเหลือ**")
                                st.dataframe(
                                    _cr_df.style.format({"เครดิตเหลือ": "{:,.0f}", "PV": "{:,.0f}"}),
                                    use_container_width=True, hide_index=True,
                                )
                                st.caption(f"รวม PV ที่เปิดบิลได้: **{_cr_df['PV'].sum():,.0f}**")

                            if _bill_owed.empty and _bill_credit.empty:
                                st.info("ไม่มีค้างจ่ายบิล / เครดิตเหลือ")

                            # ── ตาราง 2: เบิกของ (ยังไม่เปิดบิล ยังไม่จ่าย) ──
                            if not _unbilled_unpaid.empty:
                                st.divider()
                                st.markdown("**📦 เบิกของ** (ยังไม่เปิดบิล · ยังไม่จ่าย)")
                                _bw_aggcols = {"สินค้า":"first","สั่ง":"sum","ยอดรวม":"sum"}
                                _bw_outcols = ["รหัส","สินค้า","จำนวน","ยอด"]
                                _has_pv = "PV รวม" in _unbilled_unpaid.columns
                                if _has_pv:
                                    _bw_aggcols["PV รวม"] = "sum"
                                    _bw_outcols.append("PV")
                                _bw = _unbilled_unpaid.groupby("รหัส").agg(_bw_aggcols).reset_index()
                                _bw.columns = _bw_outcols
                                _bw_fmt = {"ยอด":"{:,.0f}"}
                                if _has_pv:
                                    _bw_fmt["PV"] = "{:,.0f}"
                                st.dataframe(
                                    _bw.style.format(_bw_fmt),
                                    use_container_width=True, hide_index=True,
                                )
                                _bw_cap = f"รวม: {int(_bw['จำนวน'].sum())} ชิ้น | {_bw['ยอด'].sum():,.0f} ฿"
                                if _has_pv:
                                    _bw_cap += f" | ⭐ {_bw['PV'].sum():,.0f} PV"
                                st.caption(_bw_cap)
                            else:
                                st.info("ไม่มีรายการค้าง")
                        else:
                            st.info("ไม่มีข้อมูล")

                    # ── สร้าง timeline per bill ──────────────────────────────
                    _bills_tl: dict = {}  # bill_no → {date, total, pv, qty, events[]}

                    # Phase 1: orders → bill header
                    for _r in _l_orders:
                        _bk = _r["bill_no"] or "—"
                        if _bk not in _bills_tl:
                            _bills_tl[_bk] = {
                                "date": _r["date"], "total": 0.0, "pv": 0.0,
                                "qty": 0, "bill_status": "ยังไม่เปิดบิล", "products": [], "events": [],
                            }
                        _bills_tl[_bk]["products"].append(f"{_r['product']} ×{_r['qty_in']}")
                        _bills_tl[_bk]["total"] += _r.get("total_amount", 0.0)
                        _bills_tl[_bk]["pv"]    += _r.get("pv", 0.0)
                        _bills_tl[_bk]["qty"]   += _r["qty_in"]
                        if _r.get("bill_status") == "เปิดบิลแล้ว":
                            _bills_tl[_bk]["bill_status"] = "เปิดบิลแล้ว"

                    # delivery type heuristic per bill
                    _ship_dates_set = {_r["date"] for _r in _l_ships}
                    _recv_bill_set  = {_r["bill_no"] for _r in _l_receipts if _r["bill_no"]}

                    for _bk, _bv in _bills_tl.items():
                        if _bv["date"] in _ship_dates_set:
                            _dlv = "🚚 ส่งพัสดุ"
                        elif _bk in _recv_bill_set:
                            _dlv = "🏪 รับหน้าร้าน"
                        else:
                            _dlv = "📦 ฝากของ"
                        _bv["events"].append({
                            "date": _bv["date"], "order": 0, "type": "เปิดบิล",
                            "detail": ",  ".join(_bv["products"]),
                            "total": _bv["total"], "pv": _bv["pv"],
                            "bill_status": _bv["bill_status"], "delivery": _dlv,
                        })

                    # Phase 2: payment events grouped by (bill, date)
                    _pay_groups: dict = {}
                    for _r in sorted(_l_payments, key=lambda x: x["date"]):
                        _bk = _r["bill_no"] or "—"
                        _pay_groups.setdefault((_bk, _r["date"]), []).append(_r["amount"])
                    _pay_cumul: dict = {}
                    for (_bk, _pd), _amounts in sorted(_pay_groups.items(), key=lambda x: x[0][1]):
                        _batch_total = sum(_amounts)
                        _pay_cumul[_bk] = _pay_cumul.get(_bk, 0.0) + _batch_total
                        _rem_pay = max(0.0, _bills_tl.get(_bk, {}).get("total", 0.0) - _pay_cumul[_bk])
                        if _bk in _bills_tl:
                            _bills_tl[_bk]["events"].append({
                                "date": _pd, "order": 2, "type": "จ่ายเงิน",
                                "amount": _batch_total, "remaining": _rem_pay,
                                "details": _amounts if len(_amounts) > 1 else [],
                            })

                    # Phase 3: receipt events grouped by (bill, date)
                    _recv_groups: dict = {}
                    for _r in _l_receipts:
                        _bk = _r["bill_no"] or "—"
                        _recv_groups.setdefault((_bk, _r["date"]), []).append(
                            (_r["product"], int(_r["qty_out"]))
                        )
                    _recv_cumul: dict = {}
                    for _r in _l_orders:
                        _bk = _r["bill_no"] or "—"
                        _recv_cumul[_bk] = _recv_cumul.get(_bk, 0) + _r.get("initial_received", 0)
                    for (_bk, _rd), _items in sorted(_recv_groups.items(), key=lambda x: x[0][1]):
                        _batch_qty = sum(q for _, q in _items)
                        _recv_cumul[_bk] = _recv_cumul.get(_bk, 0) + _batch_qty
                        _rem_recv = max(0, _bills_tl.get(_bk, {}).get("qty", 0) - _recv_cumul[_bk])
                        if _bk in _bills_tl:
                            _bills_tl[_bk]["events"].append({
                                "date": _rd, "order": 1, "type": "รับของ",
                                "detail": ",  ".join(f"{p} ×{q}" for p, q in _items),
                                "remaining_qty": _rem_recv,
                            })

                    # sort events within each bill
                    for _bv in _bills_tl.values():
                        _bv["events"].sort(key=lambda e: (e["date"], e["order"]))

                    # ── render expanders ──────────────────────────────────────
                    _l_table_cols = ["วันที่", "รหัส", "สินค้า", "สั่ง", "รับแล้ว", "ยอดรวม",
                                     "จ่ายแล้ว", "ค้างจ่าย", "ค้างรับ", "สถานะบิล", "สถานะจ่าย", "หมายเหตุ"]
                    _l_table_cols_disp = ["วันที่", "รหัส", "สินค้า", "สั่ง", "รับแล้ว", "ยอดรวม",
                                           "จ่ายแล้ว", "ค้างจ่าย", "ค้างรับ", "สถานะบิล", "สถานะจ่าย",
                                           "สถานะรับของ", "หมายเหตุ"]
                    _l_bills_owed = _bills_from_df(_l_all_df)
                    _owed_map = dict(zip(
                        _l_bills_owed["เลขที่บิล"].replace("", "—"),
                        _l_bills_owed["ค้างจ่าย"],
                    ))

                    # ── ตารางสรุปทุกบิล (เห็นรวดเดียวไม่ต้องเปิดทีละบิล) ──────
                    if len(_bills_tl) > 1:
                        with st.expander("📑 สรุปยอดทุกบิล", expanded=False):
                            _bl_rows = []
                            for _bbk, _bbv in sorted(_bills_tl.items(), key=lambda x: x[1]["date"], reverse=True):
                                _bb_recv = _recv_cumul.get(_bbk, 0)
                                _bl_rows.append({
                                    "เลขที่บิล": _bbk,
                                    "วันที่": _bbv["date"],
                                    "ยอดรวม": _bbv["total"],
                                    "ค้างรับ": max(0, _bbv["qty"] - _bb_recv),
                                    "ค้างจ่าย": _owed_map.get(_bbk, 0.0),
                                    "สถานะบิล": _bbv["bill_status"],
                                })
                            _bl_df = pd.DataFrame(_bl_rows)
                            st.dataframe(
                                _bl_df.style.format({"ยอดรวม": "{:,.0f}", "ค้างจ่าย": "{:,.0f}"})
                                .map(lambda v: "background-color:#6b1a1a;color:white"
                                     if isinstance(v, (int, float)) and v > 0 else "",
                                     subset=["ค้างรับ", "ค้างจ่าย"]),
                                use_container_width=True, hide_index=True,
                            )

                    for _bk, _bv in sorted(
                        _bills_tl.items(), key=lambda x: x[1]["date"], reverse=True
                    ):
                        _b_owed  = _owed_map.get(_bk, 0.0)
                        _b_recv  = _recv_cumul.get(_bk, 0)
                        _b_pend  = max(0, _bv["qty"] - _b_recv)
                        _pay_ico = "✅" if _b_owed <= 0.01 else "🔴"
                        _recv_lbl = f" &nbsp;|&nbsp; 📦 ค้างรับ **{_b_pend} ชิ้น**" if _b_pend > 0 else ""
                        _pv_lbl   = (f" &nbsp;|&nbsp; ⭐ **{_bv['pv']:.0f} PV**"
                                     if _bv["pv"] > 0 and _bv["bill_status"] == "ยังไม่เปิดบิล" else "")
                        _exp_hdr  = (
                            f"📋 **{_bk}** &nbsp; {_bv['date']} &nbsp;|&nbsp; "
                            f"{_pay_ico} ค้างจ่าย **{_b_owed:,.0f}฿**{_recv_lbl}{_pv_lbl}"
                        )
                        with st.expander(_exp_hdr, expanded=True):
                            _pv_unbilled = _bv["pv"] if _bv["bill_status"] == "ยังไม่เปิดบิล" else 0.0
                            st.caption(
                                f"📦 ค้างรับ {_b_pend} ชิ้น  |  "
                                f"💰 ค้างจ่าย {_b_owed:,.0f}฿  |  "
                                f"⭐ PV ค้างเปิดบิล {_pv_unbilled:,.0f}"
                            )
                            _bill_filter = "" if _bk == "—" else _bk
                            _bill_rows = _l_all_df[_l_all_df["เลขที่บิล"].fillna("") == _bill_filter].copy()
                            if _bill_rows.empty:
                                st.caption("ไม่มีรายการ")
                            else:
                                _bill_rows["_dt"] = pd.to_datetime(_bill_rows["วันที่"], dayfirst=True, errors="coerce")
                                _bill_rows = _bill_rows.sort_values("_dt")
                                _disp = _bill_rows[_l_table_cols].reset_index(drop=True)
                                _disp["หมายเหตุ"] = _disp["หมายเหตุ"].fillna("").apply(_fmt_note)
                                _dlv_raw = next((e.get("delivery","") for e in _bv["events"] if e.get("delivery")), "")
                                _disp["สถานะรับของ"] = _dlv_raw.split(" ", 1)[1] if " " in _dlv_raw else _dlv_raw
                                _disp = _disp[_l_table_cols_disp]
                                st.dataframe(
                                    _disp, hide_index=True, use_container_width=True,
                                    column_config={
                                        "ยอดรวม":   st.column_config.NumberColumn("ยอดรวม", format="%,.0f"),
                                        "จ่ายแล้ว": st.column_config.NumberColumn("จ่ายแล้ว", format="%,.0f"),
                                        "ค้างจ่าย": st.column_config.NumberColumn("ค้างจ่าย", format="%,.0f"),
                                    },
                                )

                            # ── ประวัติเหตุการณ์ของบิลนี้ เรียงตามวันที่ ──────────
                            st.markdown("**📜 ประวัติ**")
                            for _r in _bv["events"]:
                                if _r["type"] == "เปิดบิล":
                                    st.caption(
                                        f"📋 {_r['date']}  เปิดบิล — {_r['detail']}  "
                                        f"(รวม {_r['total']:,.0f}฿"
                                        + (f", {_r['pv']:.0f} PV" if _r['pv'] > 0 else "")
                                        + ")"
                                    )
                                elif _r["type"] == "จ่ายเงิน":
                                    _pay_details = _r.get("details", [])
                                    if _pay_details:
                                        _pd_str = " + ".join(f"{a:,.0f}" for a in _pay_details)
                                        st.caption(
                                            f"💰 {_r['date']}  จ่ายเงิน {_r['amount']:,.0f}฿ "
                                            f"({_pd_str}) — คงค้าง {_r['remaining']:,.0f}฿"
                                        )
                                    else:
                                        st.caption(
                                            f"💰 {_r['date']}  จ่ายเงิน {_r['amount']:,.0f}฿ "
                                            f"(คงค้าง {_r['remaining']:,.0f}฿)"
                                        )
                                elif _r["type"] == "รับของ":
                                    st.caption(
                                        f"📦 {_r['date']}  รับของ {_r['detail']} "
                                        f"(ค้างรับเหลือ {_r['remaining_qty']} ชิ้น)"
                                    )
                                elif _r["type"] == "ส่งพัสดุ":
                                    st.caption(f"🚚 {_r['date']}  ส่งพัสดุ {_r['detail']}  Tracking: {_r['tracking']}")

                            # ── ส่งสรุปบิล LINE ──────────────────────────────────
                            _bl_luid = _l_cust.get("line_user_id") or ""
                            _bl_gid  = _l_cust.get("group_id") or ""
                            if line_api.is_configured() and not _bill_rows.empty:
                                if st.button(
                                    "📨 ส่งสรุปบิล LINE" if _bl_luid else "📨 ไม่มี LINE ID",
                                    key=f"ledger_bill_line_{_bk}_{_l_sel}",
                                    disabled=not _bl_luid,
                                ):
                                    _bl_items = [
                                        {"name": r["สินค้า"], "qty": int(r["สั่ง"]), "total": float(r["ยอดรวม"])}
                                        for _, r in _bill_rows.iterrows()
                                    ]
                                    _bl_total = float(_bill_rows["ยอดรวม"].sum())
                                    _bl_paid  = float(_bill_rows["จ่ายแล้ว"].sum())
                                    _bl_res = line_api.push_bill_summary(
                                        _bl_luid, _l_sel, _bk,
                                        _bl_items, _bl_total, _bv["bill_status"],
                                        paid_amount=_bl_paid, outstanding_amount=_b_owed,
                                        group_id=_bl_gid,
                                    )
                                    if _bl_res.get("ok"):
                                        st.success("✅ ส่ง LINE แล้ว")
                                    else:
                                        st.error(f"❌ {_bl_res.get('error')}")

                            # ── ลบบิลนี้ ────────────────────────────────────────
                            if _bk != "—":
                                with st.expander("🗑️ ลบบิลนี้"):
                                    _ldel_total = float(_bill_rows["ยอดรวม"].sum())
                                    st.warning(
                                        f"⚠️ จะลบบิล **{_bk}** ({_l_sel}, {_ldel_total:,.0f}฿, "
                                        f"{len(_bill_rows)} รายการ — ดูรายละเอียดในตารางด้านบน) — กู้คืนไม่ได้"
                                    )
                                    _ldel_bill_chk = st.checkbox(
                                        "ยืนยันการลบ", key=f"ldel_bill_confirm_{_bk}_{_l_sel}"
                                    )
                                    if st.button("🗑️ ลบบิล", disabled=not _ldel_bill_chk,
                                                  type="secondary", key=f"ldel_bill_btn_{_bk}_{_l_sel}"):
                                        _n = db.delete_bill(_bk)
                                        st.success(f"✅ ลบบิล {_bk} แล้ว ({_n} รายการ)")
                                        st.rerun()

                    # ── ลบ partial event ──────────────────────────────────────
                    _ldel_rows = [
                        (i, str(r.get("event_id") or ""))
                        for i, r in enumerate(_l_data) if r.get("event_id")
                    ]
                    if _ldel_rows:
                        with st.expander("🗑️ ลบรายการ"):
                            for _ldi, _leid in _ldel_rows:
                                _llr = _l_data[_ldi]
                                _leid_real = _leid.removesuffix("-r").removesuffix("-p")
                                _lamt_str = f"฿{_llr['amount']:,.0f}" if _llr['amount'] else ""
                                _llabel = (f"{_llr['date'][:10]}  {_llr['type']}  "
                                           f"{_llr.get('product','') or ''}  {_lamt_str}")
                                if st.button(f"🗑️ {_llabel}", key=f"ldel_{_ldi}_{_l_sel}"):
                                    db.delete_partial_event(_leid_real)
                                    st.rerun()
                else:
                    st.caption("ไม่มีประวัติ")

    elif _t5_active == _T5_TABS[2]:
        st.subheader("รายละเอียดบิล")

        customers_h = customers
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

        h_cid = None
        if h_filter_cust != "ทั้งหมด":
            h_cid = next(c["id"] for c in customers_h if c["name"] == h_filter_cust)

        all_df = db.get_all_transactions_df(customer_id=h_cid)

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
                use_container_width=True,
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
                if d2.button("🗑️ ลบรายการที่เลือก", type="secondary", use_container_width=True, key="hist_del_chk_btn"):
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
                                   type="primary", use_container_width=True,
                                   key="hist_open_bill_btn"):
                        for i in _sel_unbilled:
                            db.update_transaction_status(id_map.iloc[i], bill_status="เปิดบิลแล้ว")
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
                                            use_container_width=True, key="save_all_fix_top")
                _sc1, _sc2 = st.columns([3, 1])
                _sc1.info(f"แก้ไข {len(_any_changes)} รายการ")
                _bottom_save = _sc2.button("💾 บันทึกแก้ไข", type="primary",
                                           use_container_width=True, key="save_all_fix")
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
                            db.update_transaction_status(
                                _tid,
                                bill_status=_ch.get("bill_status"),
                                pay_status=_ch.get("pay_status"),
                            )
                    st.success("✅ บันทึกแล้ว")
                    st.session_state.pop("hist_table", None)
                    st.rerun()

            cleared_ids = all_df[all_df["เคลียร์แล้ว"]]["id"].tolist()
            if cleared_ids:
                bc1, bc2 = st.columns([3, 1])
                bc1.caption(f"มี {len(cleared_ids)} รายการที่เคลียร์แล้ว (จ่ายและรับครบ)")
                h_confirm_bulk = bc1.checkbox("ยืนยันลบทั้งหมดที่เคลียร์แล้ว", key="hist_bulk_chk")
                if bc2.button(f"🗑️ ลบเคลียร์แล้วทั้งหมด ({len(cleared_ids)})",
                              disabled=not h_confirm_bulk, use_container_width=True, key="hist_bulk_del"):
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
                st.dataframe(_ship_df_h, hide_index=True, use_container_width=True)


    elif _t5_active == _T5_TABS[3]:
        st.subheader("ประวัติการส่งของ")

        _sh_cod_col, _sh_status_col, _sh_sync_col = st.columns([4, 2, 2])
        if _sh_status_col.button("🚚 สถานะส่ง", key="sh_status_sync", use_container_width=True):
            _pending_tn = db.get_pending_delivery_tracking()
            if not _pending_tn:
                st.info("ทุก tracking จัดส่งสำเร็จแล้ว")
            else:
                with st.spinner(f"ดึงสถานะ {len(_pending_tn)} tracking..."):
                    _sr = iship_api.get_shipment_statuses(days_back=90)
                if _sr.get("error"):
                    st.error(f"❌ {_sr['error']}")
                else:
                    _to_update = {tn: st for tn, st in _sr["statuses"].items() if tn in set(_pending_tn)}
                    if _to_update:
                        db.update_delivery_statuses(_to_update)
                        st.success(f"✅ อัปเดต {len(_to_update)} tracking")
                        st.rerun()
                    else:
                        st.info("ไม่มีสถานะใหม่")
                        if st.secrets.get("DEBUG_MODE"):
                            with st.expander("🔍 debug"):
                                st.write(f"iShip คืนมา {len(_sr['statuses'])} tracking: {list(_sr['statuses'].keys())[:5]}")
                                st.write(f"pending ในระบบ {len(_pending_tn)}: {_pending_tn[:5]}")
                                st.write(f"debug: {_sr.get('_debug')}")
        if _sh_sync_col.button("🔄 ตรวจสอบ COD", key="sh_cod_sync", use_container_width=True):
            try:
                _pending = db.get_pending_cod_tracking()
            except Exception:
                _pending = None  # column ยังไม่มี — ดึงทั้งหมด
            if _pending is not None and len(_pending) == 0:
                st.info("✅ COD ทุกรายการโอนแล้ว ไม่ต้องดึงข้อมูลใหม่")
            else:
                with st.spinner("กำลังดึงข้อมูลจาก iShip..."):
                    _r = iship_api.get_cod_transfers(days_back=90)
                if _r.get("error"):
                    st.error(f"❌ {_r['error']}")
                else:
                    _cod_transfers = _r.get("transfers", {})
                    st.session_state["_sh_cod_map"] = _cod_transfers
                    if _cod_transfers:
                        try:
                            db.mark_cod_transferred(list(_cod_transfers.keys()))
                        except Exception as _mct_e:
                            st.warning(f"⚠️ บันทึกสถานะ COD โอนแล้วไม่สำเร็จ: {_mct_e}")
                        try:
                            _pending_set = set(_pending or [])
                            _newly = {tn: info.get("date", "")
                                      for tn, info in _cod_transfers.items()
                                      if tn in _pending_set}
                            _n_marked = db.mark_cod_paid(_newly)
                            if _n_marked:
                                st.success(f"✅ บันทึก COD จ่ายแล้ว {_n_marked} รายการ")
                        except Exception as _mcp_e:
                            st.error(f"❌ อัปเดตสถานะจ่าย COD ไม่สำเร็จ: {_mcp_e}")
                        st.rerun()
                    else:
                        st.info("ยังไม่มี COD ที่โอนแล้วในช่วง 90 วัน")
        _sh_cod_map = st.session_state.get("_sh_cod_map", {})
        # โหลดสถานะที่บันทึกใน DB ด้วย
        try:
            _db_transferred = set(
                r["tracking_no"] for r in
                db.get_supabase().table("shipments")
                    .select("tracking_no").not_.is_("cod_transferred_at","null")
                    .not_.is_("tracking_no","null").execute().data
                if r.get("tracking_no")
            )
            _sh_cod_map = {**{tn: {} for tn in _db_transferred}, **_sh_cod_map}
        except Exception as _cod_db_e:
            st.caption(f"⚠️ ดึงสถานะ COD จาก DB ไม่สำเร็จ: {_cod_db_e}")
        if _sh_cod_map:
            _sh_cod_col.caption(f"✅ COD โอนแล้ว {len(_sh_cod_map)} tracking")

        # ── filter ลูกค้า ─────────────────────────────────────────────────
        _sh_customers = customers
        _sh_cust_map  = {c["name"]: c["id"] for c in _sh_customers}
        _sh_cust_opts = ["— ทั้งหมด —"] + sorted(_sh_cust_map.keys(), key=str.casefold)
        _sh_cust_sel  = st.selectbox("ลูกค้า", _sh_cust_opts, key="sh_cust_filter",
                                     label_visibility="collapsed")
        _sh_filter_cid = _sh_cust_map.get(_sh_cust_sel) if _sh_cust_sel != "— ทั้งหมด —" else None

        try:
            _sh_all = db.get_shipments(customer_id=_sh_filter_cid)
        except Exception:
            st.warning("⚙️ ยังไม่ได้สร้าง table shipments")
            _sh_all = []

        if _sh_all:
            def _items_str(items):
                if not items:
                    return ""
                return ", ".join(f"{it.get('product_id','')} ×{it.get('qty',0)}" for it in items)

            _sh_ids  = [r["id"] for r in _sh_all]
            def _cod_status(r):
                tn  = r.get("tracking_no", "") or ""
                cod = float(r.get("cod_amount") or 0)
                if cod <= 0:
                    return ""
                if tn and tn in _sh_cod_map:
                    return "✅"
                return "⏳"

            def _delivery_icon(status: str) -> str:
                if not status:
                    return ""
                if "จัดส่งแล้ว" in status or "ชำระเงินสำเร็จ" in status:
                    return "✅"
                if "ตีกลับ" in status or "ยกเลิก" in status:
                    return "❌"
                if "รอเข้ารับ" in status:
                    return "⏳"
                if "อยู่ระหว่าง" in status or "กำลังจัดส่ง" in status:
                    return "🚚"
                return "📦"

            def _src_icon(r):
                s = r.get("source", "")
                if s == "sale": return "💰"
                if s == "ship": return "📦"
                return "—"

            _sh_df   = pd.DataFrame([{
                "ลบ":              False,
                "📤":              False,
                "แหล่ง":           _src_icon(r),
                "วันที่/เวลา":     _to_bkk(r.get("created_at") or ""),
                "ลูกค้า":          (r.get("customers") or {}).get("name", ""),
                "COD":             float(r.get("cod_amount") or 0),
                "💸":              _cod_status(r),
                "สถานะส่ง":        (_delivery_icon(r.get("delivery_status") or "") + " " +
                                    (r.get("delivery_status") or "")).strip(),
                "ผู้รับ":           r.get("recipient_name", ""),
                "เบอร์":            r.get("phone", ""),
                "รายการ":          _items_str(r.get("items")),
                "ขนส่ง":           r.get("carrier", ""),
                "Tracking":        r.get("tracking_no", "") or "",
                "🔗":              (f"https://app.iship.cloud/tracking?track={r['tracking_no']}"
                                   if r.get("tracking_no") else ""),
                "บ้านเลขที่/ถนน":  r.get("address_line", ""),
                "ตำบล":            r.get("district", ""),
                "อำเภอ":           r.get("amphure", ""),
                "จังหวัด":         r.get("province", ""),
                "รหัสปณ.":         r.get("postal_code", ""),
                "หมายเหตุ":        r.get("notes", ""),
            } for r in _sh_all])

            _sh_edit = st.data_editor(
                _sh_df,
                hide_index=True, use_container_width=False, key="sh_hist_tbl",
                disabled=["แหล่ง","วันที่/เวลา","ลูกค้า","ผู้รับ","เบอร์",
                          "บ้านเลขที่/ถนน","ตำบล","อำเภอ","จังหวัด","รหัสปณ.",
                          "รายการ","ขนส่ง","COD","💸","สถานะส่ง","🔗","หมายเหตุ"],
                column_config={
                    "ลบ":       st.column_config.CheckboxColumn("ลบ", default=False, width="small"),
                    "📤":       st.column_config.CheckboxColumn("📤", default=False, width="small",
                                    help="เลือกเพื่อส่ง iShip ใหม่"),
                    "แหล่ง":    st.column_config.TextColumn("แหล่ง", width="small",
                                    help="🛒 = บันทึกขาย  📦 = ส่งของ"),
                    "COD":      st.column_config.NumberColumn("COD", format="%,.0f", width="small"),
                    "💸":       st.column_config.TextColumn("💸", width="small"),
                    "สถานะส่ง": st.column_config.TextColumn("สถานะส่ง", width="medium"),
                    "Tracking": st.column_config.TextColumn("Tracking", width="small"),
                    "🔗":       st.column_config.LinkColumn("🔗", width="small", display_text="🔗"),
                },
            )

            # บันทึก Tracking ที่แก้ไข
            for _si, _srow in _sh_edit.iterrows():
                _orig_tn = _sh_df.at[_si, "Tracking"]
                _new_tn  = (_srow["Tracking"] or "").strip()
                if _new_tn != _orig_tn:
                    db.update_shipment_tracking(_sh_ids[_si], _new_tn)
                    st.session_state.pop("sh_hist_tbl", None)
                    st.rerun()

            _sh_to_del = [_sh_ids[i] for i, v in enumerate(_sh_edit["ลบ"]) if v]

            if _sh_to_del:
                if st.button(f"🗑️ ลบที่เลือก ({len(_sh_to_del)} รายการ)", type="primary", key="sh_del_btn"):
                    _sh_del_errs = []
                    for _did in _sh_to_del:
                        try:
                            db.delete_shipment(_did)
                        except Exception as _sd_e:
                            _sh_del_errs.append(str(_sd_e))
                    st.session_state.pop("sh_hist_tbl", None)
                    if _sh_del_errs:
                        st.error(f"❌ ลบไม่สำเร็จ {len(_sh_del_errs)} รายการ: {_sh_del_errs[0]}")
                    else:
                        st.rerun()

            # ── ปริ้นใบปะหน้า ──────────────────────────────────────────
            if iship_api.is_configured():
                _pr_tracking_opts = [r.get("tracking_no","") for r in _sh_all if r.get("tracking_no")]
                if _pr_tracking_opts:
                    with st.expander("🖨️ ปริ้นใบปะหน้า"):
                        _pr_sel = st.selectbox("เลือก Tracking", _pr_tracking_opts, key="sh_print_sel")
                        if st.button("🖨️ ปริ้น", key="sh_print_label", type="primary"):
                            with st.spinner("กำลังหา order ID จาก iShip..."):
                                _pr_result = iship_api.get_label_url(_pr_sel)
                            if _pr_result.get("url"):
                                import streamlit.components.v1 as _comp
                                _comp.html(
                                    f'<a id="_lbl" href="{_pr_result["url"]}" target="_blank" '
                                    f'style="display:inline-block;padding:8px 24px;background:#00A86B;color:#fff;'
                                    f'border-radius:8px;text-decoration:none;font-size:16px">'
                                    f'🖨️ กดที่นี่เพื่อปริ้น</a>'
                                    f'<script>document.getElementById("_lbl").click()</script>',
                                    height=50,
                                )
                            else:
                                st.warning(f"⚠️ {_pr_result.get('error','หา order ไม่ได้')}")

            _sh_to_resend = [i for i, v in enumerate(_sh_edit["📤"]) if v]
            if len(_sh_to_resend) > 1:
                st.warning("เลือกได้ทีละ 1 รายการสำหรับส่ง iShip ใหม่")
            elif len(_sh_to_resend) == 1:
                _rs_i        = _sh_to_resend[0]
                _rs_row      = _sh_all[_rs_i]
                _rs_prod_map = {p["id"]: p for p in db.get_products()}
                _rs_items    = _rs_row.get("items") or []
                _rs_total_g  = sum(
                    float(_rs_prod_map.get(it.get("product_id", ""), {}).get("weight_grams") or 0) * it.get("qty", 0)
                    for it in _rs_items
                )
                _rs_w_def = max(0.5, round((_rs_total_g + BOX_WEIGHT_G) / 1000, 2))
                _rs_w   = st.number_input("น้ำหนักรวมกล่อง (kg)", 0.1, 100.0, _rs_w_def, 0.1, key=f"sh_resend_w_{_rs_i}")
                if st.button("📤 ส่ง iShip ใหม่", type="primary", key="sh_resend_btn"):
                    _old_tn = (_rs_row.get("tracking_no") or "").strip()
                    st.session_state.pop("_cs_carrier_sel", None)
                    st.session_state["_iship_carrier_select"] = {
                        "tab":           "ship",
                        "postcode":      _rs_row.get("postal_code", ""),
                        "weight_kg":     _rs_w,
                        "cod_amount":    float(_rs_row.get("cod_amount") or 0),
                        "customer_name": (_rs_row.get("customers") or {}).get("name", ""),
                        "customer_id":   _rs_row.get("customer_id", ""),
                        "dst_name":      _rs_row.get("recipient_name", ""),
                        "dst_phone":     _rs_row.get("phone", ""),
                        "address_line":  _rs_row.get("address_line", ""),
                        "district":      _rs_row.get("district", ""),
                        "amphure":       _rs_row.get("amphure", ""),
                        "province":      _rs_row.get("province", ""),
                        "items":         _rs_row.get("items") or [],
                        "shipment_id":   _rs_row["id"],
                        "remark":        _rs_row.get("notes", ""),
                    }
                    if _old_tn:
                        st.session_state["_change_carrier_old_track"] = _old_tn
                    st.session_state.pop("sh_hist_tbl", None)
                    st.rerun()
        else:
            st.info("ยังไม่มีประวัติการส่งของ")

        # ── เคลียร์ประวัติ ──────────────────────────────────────────────────────
        st.divider()
        with st.expander("🗑️ เคลียร์ประวัติจัดส่งสำเร็จ"):
            st.caption("ลบรายการที่ **จัดส่งสำเร็จ** ทั้งหมดในช่วงวันที่ที่เลือก (ไม่กระทบข้อมูลบิล/ยอดค้าง)")
            _cl_c1, _cl_c2 = st.columns(2)
            _cl_from = _cl_c1.date_input("ตั้งแต่วันที่", value=date(2026, 1, 1), key="sh_clear_from")
            _cl_to   = _cl_c2.date_input("ถึงวันที่",     value=date.today(),      key="sh_clear_to")

            if _cl_from and _cl_to:
                if _cl_from > _cl_to:
                    st.warning("วันเริ่มต้นต้องไม่เกินวันสิ้นสุด")
                else:
                    _cl_count = db.count_shipped_by_date_range(str(_cl_from), str(_cl_to))
                    if _cl_count == 0:
                        st.info("ไม่มีรายการจัดส่งสำเร็จในช่วงนี้")
                    else:
                        st.warning(
                            f"⚠️ จะลบ **{_cl_count} รายการ** ที่จัดส่งสำเร็จแล้วระหว่าง "
                            f"{_cl_from.strftime('%d/%m/%Y')} – {_cl_to.strftime('%d/%m/%Y')}"
                        )
                        if st.button(f"🗑️ ลบ {_cl_count} รายการ", type="primary",
                                     key="sh_clear_btn"):
                            _deleted = db.delete_shipped_by_date_range(str(_cl_from), str(_cl_to))
                            st.success(f"✅ ลบแล้ว {_deleted} รายการ")
                            st.session_state.pop("sh_hist_tbl", None)
                            st.rerun()

