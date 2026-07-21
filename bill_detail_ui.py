import re
import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
from math import floor
import uuid

import database as db
import line_api
import shipment_history_ui
import history_all_ui
import cod_tracking_ui
from ui_helpers import (
    _to_bkk, _to_excel_bytes,
    _style_status, _fmt_note, _guard_double_submit,
    _bills_from_df, _render_bill_panel, _ledger_to_txn_df,
    merge_bill_family_products,
)


_T5_TABS = ["💰 ยอดค้าง / จัดการบิล", "👤 บัตรลูกค้า", "📋 ประวัติทั้งหมด", "🚚 ประวัติการส่ง", "📮 COD"]

_PILL_GOOD = "background-color:oklch(0.94 0.03 155);color:oklch(0.4 0.1 155);"
_PILL_WARN = "background-color:oklch(0.94 0.04 55);color:oklch(0.5 0.14 50);"
_PILL_BAD  = "background-color:oklch(0.94 0.03 25);color:oklch(0.5 0.15 25);"
_BILL_OVERDUE_DAYS = 30  # ยังไม่มี due-date จริง ใช้อายุบิลค้างจ่ายแทน


def render(products, customers):
    try:
        _t5_active = st.pills(" ", _T5_TABS, key="_t5_active_sub", default=_T5_TABS[0], label_visibility="collapsed") or _T5_TABS[0]
    except AttributeError:
        _t5_active = st.radio(" ", _T5_TABS, horizontal=True, key="_t5_active_sub", label_visibility="collapsed")

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
                _bill_cust_names = {(r.get("customers") or {}).get("name", "—") for r in _bill_rows}
                _bill_no_collision = len(_bill_cust_names) > 1
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
                    st.dataframe(_preview_df, width="stretch", hide_index=True)
                    _grand = sum(r.get("total_amount") or 0 for r in _bill_rows)
                    st.markdown(f"**ยอดรวมทั้งบิล: {_grand:,.0f} บาท** ({len(_bill_rows)} รายการ)")
                    if _bill_no_collision:
                        st.error(
                            f"🚨 เลขที่บิล {_sel_bill} นี้ถูกใช้ซ้ำกันโดยหลายลูกค้า "
                            f"({', '.join(_bill_cust_names)}) — ลบตรงนี้จะลบของทุกคนที่ใช้เลขนี้ปนกันหมด "
                            "กรุณาแก้เลขบิลให้ไม่ซ้ำกันก่อน (ผ่าน 'ประวัติทั้งหมด' > แก้ไขรายการ) แล้วค่อยลบทีละบิล"
                        )
                    else:
                        st.warning(f"⚠️ จะลบบิล **{_sel_bill}** ({_bill_cust}) และทุกรายการข้างต้น — กู้คืนไม่ได้")
                st.divider()
                _del_chk_main = st.checkbox(
                    "ยืนยันการลบ", key="del_bill_confirm", disabled=_bill_no_collision)
                if st.button("🗑️ ลบบิลนี้", type="primary",
                             disabled=not _del_chk_main or _bill_no_collision, key="del_bill_btn"):
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
                except Exception as _as_e:
                    _all_ships = []
                    st.caption(f"⚠️ โหลดข้อมูลการส่งไม่สำเร็จ (อาจไม่เห็น tracking บางรายการ): {_as_e}")
                _ship_by_cust: dict = {}
                for _s in _all_ships:
                    _ship_by_cust.setdefault(_s.get("customer_id", ""), []).append(_s)

                for customer_name, grp in outstanding_df.groupby("ลูกค้า"):
                    _is_cod = grp["สถานะจ่าย"] == "COD"
                    owed     = grp.loc[~_is_cod, "ค้างจ่าย"].sum()
                    pending = int(grp["ค้างรับ"].sum())
                    txn_ids = grp["id"].tolist()
                    _luid   = _cust_line_map.get(customer_name, "")
                    _gid    = _cust_gid_map.get(customer_name, "")
                    _unbilled_pv = grp.loc[grp["สถานะบิล"] == "ยังไม่เปิดบิล", "PV รวม"].sum() if "PV รวม" in grp.columns else 0
                    # ── แถวเดียวต่อลูกค้า (ยอดรวมทุกบิล) — คลิกชื่อเพื่อดูรายละเอียดทีละบิล ──
                    _cust_bills = _bills_from_df(grp)
                    _bill_rows_info = []
                    for _, _cb in _cust_bills.iterrows():
                        _cb_bno   = _cb["เลขที่บิล"] if pd.notna(_cb["เลขที่บิล"]) and str(_cb["เลขที่บิล"]).strip() else "—"
                        _cb_total = float(_cb["ยอดรวม"])
                        _cb_owed  = float(_cb["ค้างจ่าย"])
                        if not _cb["is_billed"]:
                            _pill_txt, _pill_css = "ยังไม่เปิดบิล", _PILL_WARN
                        elif _cb["is_paid"]:
                            _pill_txt, _pill_css = "ชำระแล้ว", _PILL_GOOD
                        else:
                            _cb_date = pd.to_datetime(_cb["วันที่"], errors="coerce")
                            _overdue = pd.notna(_cb_date) and (pd.Timestamp.now() - _cb_date).days > _BILL_OVERDUE_DAYS
                            _pill_txt, _pill_css = ("เกินกำหนด", _PILL_BAD) if _overdue else ("ค้างชำระ", _PILL_WARN)
                        _bill_rows_info.append((_cb_bno, _cb_total, _cb_owed, _pill_txt, _pill_css))

                    _bill_count = len(_bill_rows_info)
                    _grp_total  = sum(r[1] for r in _bill_rows_info)
                    _pill_priority = {"เกินกำหนด": 3, "ยังไม่เปิดบิล": 2, "ค้างชำระ": 1, "ชำระแล้ว": 0}
                    _agg_txt, _agg_css = max(
                        ((r[3], r[4]) for r in _bill_rows_info),
                        key=lambda x: _pill_priority.get(x[0], 0),
                        default=("ชำระแล้ว", _PILL_GOOD),
                    )

                    _is_active_cust = single_cust or customer_name == _active_cust

                    with st.container(border=True):
                        _gc1, _gc2, _gc3, _gc4, _gc5 = st.columns([1.3, 2.8, 1.2, 1.3, 1.4])
                        _gc1.caption(f"{_bill_count} บิล")
                        if _gc2.button(
                            f"👤 {customer_name}",
                            key=f"custrow_{customer_name}",
                            width="stretch",
                            type=("primary" if _is_active_cust else "secondary"),
                        ):
                            st.session_state["_t5_out_active_cust"] = (
                                "" if customer_name == _active_cust else customer_name
                            )
                            st.rerun()
                        _gc3.markdown(f"฿{_grp_total:,.0f}")
                        _gc4.markdown(f"฿{owed:,.0f}" if owed > 0.01 else "—")
                        _gc5.markdown(
                            f'<span style="{_agg_css}border-radius:999px;padding:4px 12px;'
                            f'font-size:0.8rem;display:inline-block;">{_agg_txt}</span>',
                            unsafe_allow_html=True,
                        )

                    if _is_active_cust:
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
    body{{font-family:'Prompt',sans-serif;padding:16px;font-size:13px}}
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
                            st.iframe(_recv_html, height=430)
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
                            if _pr_c2.button("📨 แจ้ง LINE", key=f"pr_line_{customer_name}", type="primary", width="stretch"):
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
                        # ── บิลหลัก: รวมสินค้าที่แยกบิลบางส่วน (origin ≠ เลขที่บิล
                        # ปัจจุบัน) เป็นแถวเดียวต่อสินค้า พร้อมคอลัมน์เปิดบิลแล้ว/
                        # ยังไม่เปิด — ใช้ _all_txn_cache (ไม่ใช่ grp/outstanding_df)
                        # เพราะส่วนที่เปิดบิล+จ่าย/รับครบแล้วอาจหลุดจากยอดค้างไปแล้ว
                        # แต่ยังต้องรวมยอดสั่งทั้งหมดให้เห็นถูกต้อง
                        _grp_origin = grp["เลขอ้างอิงบิลหลัก"].reset_index(drop=True)
                        _grp_bno = grp["เลขที่บิล"].reset_index(drop=True).fillna("")
                        _has_family = (_grp_origin != "") & (_grp_origin != _grp_bno)
                        # หลายบิลเก่าที่เคยแยกไว้พร้อมกันจะทำให้บล็อกนี้เด้งซ้อนกันหลายอัน
                        # จนงง — เก็บไว้ใน expander ปิดไว้ก่อน (บิลใหม่จากนี้ไปไม่แยกแถว
                        # แล้ว บล็อกนี้จะโผล่เฉพาะข้อมูลเก่าก่อน 2026-07-17 เท่านั้น)
                        for _origin in _grp_origin[_has_family].unique().tolist():
                            _fam_full_df = _all_txn_cache[
                                (_all_txn_cache["ลูกค้า"] == customer_name)
                                & (_all_txn_cache["เลขอ้างอิงบิลหลัก"] == _origin)
                            ]
                            _fam_prod = merge_bill_family_products(_fam_full_df, _origin)
                            if _fam_prod.empty:
                                continue
                            with st.expander(f"🗂️ บิลหลัก {_origin} (เคยแยกเปิดบิลบางส่วน)"):
                                _om1, _om2, _om3, _om4 = st.columns(4)
                                _om1.metric("สั่งทั้งหมด", f"{_fam_prod['สั่ง'].sum():,.0f} ชิ้น")
                                _om2.metric("รับแล้ว", f"{_fam_prod['รับแล้ว'].sum():,.0f} ชิ้น")
                                _om3.metric("ค้างจ่ายรวม", f"{_fam_prod['ค้างจ่าย'].sum():,.0f} ฿")
                                _om4.metric("เหลือเปิดบิล", f"{_fam_prod['ยังไม่เปิด'].sum():,.0f} ชิ้น")
                                st.dataframe(
                                    _fam_prod[[
                                        "วันที่", "รหัส", "สินค้า", "สั่ง", "รับแล้ว", "ยอดรวม", "จ่ายแล้ว",
                                        "ค้างจ่าย", "ค้างรับ", "เปิดบิลแล้ว", "ยังไม่เปิด",
                                        "สถานะบิล", "สถานะจ่าย", "สถานะรับของ",
                                    ]].style.format({"ยอดรวม": "{:,.0f}", "จ่ายแล้ว": "{:,.0f}", "ค้างจ่าย": "{:,.0f}"}),
                                    width="stretch", hide_index=True,
                                )
                        if _has_family.any():
                            st.divider()

                        # ── Styled table + row selection ──────────────────────
                        _dcols  = ["เลขที่บิล", "วันที่", "รหัส", "สินค้า", "สั่ง", "ค้างรับ",
                                   "ยอดรวม", "ค้างจ่าย", "เปิดบิลแล้ว", "ยังไม่เปิด",
                                   "สถานะจ่าย", "สถานะบิล"]
                        _id_map = grp["id"].reset_index(drop=True)
                        # "เลขที่บิล" ในตารางนี้โชว์เลขอ้างอิงภายในที่คงที่เสมอ (origin_bill_no
                        # ถ้ามี ไม่งั้น bill_no ของแถวเอง) ไม่ใช่ bill_no ดิบๆ — เพราะแถวเก่าที่
                        # เคยเปิดบิลจริงไปแล้ว (ก่อน 2026-07-17) bill_no ของแถวจะเป็นเลขบิลจริง
                        # ไม่ใช่เลขอ้างอิง ถ้าโชว์ตรงๆ จะสลับความหมายกับแถวใหม่ที่ bill_no คงที่
                        # เสมอ — เลขบิลจริง (ถ้ามี) ย้ายไปโชว์ที่คอลัมน์ "เลขบิลจริง" แทน
                        _grp_disp = grp[_dcols].reset_index(drop=True).copy()
                        _grp_disp["เลขที่บิล"] = _grp_origin.where(_grp_origin != "", _grp_bno)
                        if _has_family.any():
                            _grp_disp.insert(1, "เลขบิลจริง", _grp_bno.where(_has_family, ""))
                        st.caption("คลิกแถวเพื่อเลือก (Ctrl/Shift สำหรับหลายแถว)")
                        _evt = st.dataframe(
                            _grp_disp.style
                                .format({"ยอดรวม": "{:,.0f}", "ค้างจ่าย": "{:,.0f}"})
                                .map(_style_status, subset=["สถานะบิล", "สถานะจ่าย"])
                                .map(lambda v: "background-color:#FDECEA;color:#C0392B;font-weight:600"
                                     if isinstance(v, (int, float)) and v > 0 else "",
                                     subset=["ค้างรับ", "ค้างจ่าย"]),
                            width="stretch",
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
                            # ลำดับ/ชื่อโหมดตรงกับตัวเลือกหลายรายการด้านล่าง (กำหนดเอง / ...
                            # อย่างเดียว) — กำหนดเองคือโหมดเดียวที่เปิดบิลพร้อมกับรับของ/จ่ายเงินได้
                            # ในคราวเดียว ส่วนโหมด "อย่างเดียว" ทำเฉพาะอย่างนั้นจริงๆ ไม่ผสม
                            radio_opts  = ["🛠️ กำหนดเอง", "💵 จ่ายเงินอย่างเดียว", "📦 รับของอย่างเดียว"] + (
                                ["📄 เปิดบิลอย่างเดียว"] if is_unbilled else ["↩️ ย้อนกลับเป็นยังไม่เปิดบิล"]
                            )
                            action = st.radio("บันทึก", radio_opts, horizontal=True, key=f"etype_{txn_id}")

                            if action == "↩️ ย้อนกลับเป็นยังไม่เปิดบิล":
                                st.caption(
                                    f"จะยกเลิกการเปิดบิลครั้งล่าสุดของรายการนี้ — bill_no "
                                    f"({txn.get('bill_no') or '—'}) ไม่เปลี่ยน เพราะเป็นแค่เลขอ้างอิงภายใน"
                                )
                                _revert_confirm = st.checkbox(
                                    "ยืนยันการย้อนกลับ", key=f"revert_open_chk_{txn_id}")
                                if st.button("↩️ ย้อนกลับ", type="secondary", disabled=not _revert_confirm,
                                             key=f"revert_open_btn_{txn_id}"):
                                    db.undo_last_bill_open_event(txn_id)
                                    st.success("✅ ย้อนกลับเป็นยังไม่เปิดบิลแล้ว")
                                    st.rerun()
                            elif action == "📄 เปิดบิลอย่างเดียว":
                                _remaining_to_open = int(sel_row["ยังไม่เปิด"]) if "ยังไม่เปิด" in sel_row else int(txn["qty"])
                                with st.form(f"bill_{txn_id}", clear_on_submit=True):
                                    bn1, bn2 = st.columns(2)
                                    new_bill_no   = bn1.text_input("เลขที่บิลจริง (ถ้ามี — ไม่บังคับ)")
                                    new_bill_date = bn2.date_input("วันที่เปิดบิล", value=date.today())
                                    bc1, bc2 = st.columns([3, 1])
                                    qty_to_open = bc1.number_input(
                                        "จำนวนที่เปิดบิล", min_value=1,
                                        max_value=_remaining_to_open, value=_remaining_to_open, step=1,
                                    )
                                    bc2.write("")
                                    submit_bill = bc2.form_submit_button(
                                        "📄 เปิดบิล", width="stretch", type="primary"
                                    )
                                if submit_bill:
                                    db.open_bill_partial(
                                        txn_id, qty_to_open,
                                        note=new_bill_no.strip() or None, date=str(new_bill_date))
                                    st.rerun()
                            else:
                                evt_map  = {
                                    "💵 จ่ายเงินอย่างเดียว": "จ่ายเงิน",
                                    "📦 รับของอย่างเดียว": "รับของ",
                                    "🛠️ กำหนดเอง": "ทั้งคู่",
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
                                    _open_bill_no   = ""
                                    _open_qty_input = None
                                    if is_unbilled and evt_type == "ทั้งคู่":
                                        _unopened_qty = int(sel_row["ยังไม่เปิด"]) if "ยังไม่เปิด" in sel_row else int(txn["qty"])
                                        # เช็คบ็อกซ์กับช่องจำนวนต้องโชว์พร้อมกันเสมอ (ไม่ซ่อนตามค่า
                                        # เช็คบ็อกซ์) เพราะอยู่ใน st.form — widget ข้างในฟอร์มไม่ rerun
                                        # ตอนคลิก จะ sync ค่าจริงตอนกด "บันทึก" ทีเดียว ถ้าซ่อนไว้ก่อน
                                        # ผู้ใช้จะกรอกจำนวนไม่ได้เลยในรอบเดียวกับที่ติ๊ก
                                        _oc1, _oc2 = st.columns([1, 1])
                                        _also_open_bill = _oc1.checkbox(
                                            "📄 เปิดบิลด้วย", value=False,
                                            key=f"also_open_{txn_id}",
                                        )
                                        _open_qty_input = _oc2.number_input(
                                            "เปิดบิลกี่ชิ้น", min_value=1, max_value=_unopened_qty,
                                            value=_unopened_qty, step=1, key=f"also_open_qty_{txn_id}",
                                        )
                                        _open_bill_no = st.text_input(
                                            "เลขที่บิลจริง (ถ้ามี — ไม่บังคับ)", key=f"also_open_bn_{txn_id}"
                                        )
                                    submit_evt  = st.form_submit_button(
                                        "💾 บันทึก", width="stretch", type="primary"
                                    )
                                if submit_evt:
                                    error = None
                                    if evt_type == "ทั้งคู่" and qty_received > 0:
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
                                            _open_qty = int(_open_qty_input) if _open_qty_input is not None else int(txn["qty"])
                                            db.open_bill_partial(
                                                txn_id, _open_qty,
                                                note=_open_bill_no.strip() or None, date=str(event_date))
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
                                        if (_luid or _gid) and line_api.is_configured() and (qty_received > 0 or amount_paid > 0.01):
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
                                    db.undo_last_bill_open_event(txn_id)
                                    st.rerun()

                            # ── ลบบิล ─────────────────────────────────────────
                            _del_bno_vals = grp.loc[grp["id"] == txn_id, "เลขที่บิล"].values
                            _del_bno = str(_del_bno_vals[0]) if len(_del_bno_vals) > 0 and _del_bno_vals[0] else ""
                            if _del_bno and _del_bno not in ("—", ""):
                                st.divider()
                                _del_bill_rows = grp.loc[grp["เลขที่บิล"] == _del_bno]
                                st.dataframe(_del_bill_rows[["สินค้า", "สั่ง", "ยอดรวม"]], width="stretch", hide_index=True)
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
                                        db.delete_bill(_del_bno, customer_id=_cust_map_all[customer_name]["id"])
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
                            # Multi: เลือกโหมดก่อน แล้วตารางปรับให้ตรงโหมด
                            sel_rows      = grp[grp["id"].isin(selected_ids)].copy()

                            _unbilled_mask = sel_rows["สถานะบิล"] == "ยังไม่เปิดบิล"
                            _any_unbilled  = _unbilled_mask.any()
                            _unbilled_cnt  = int(_unbilled_mask.sum())
                            _unbilled_pv   = sel_rows.loc[_unbilled_mask, "PV รวม"].sum() if "PV รวม" in sel_rows.columns else 0

                            _mc_mode_opts = ["🛠️ กำหนดเอง", "💵 จ่ายเงินอย่างเดียว", "📦 รับของอย่างเดียว"]
                            if _any_unbilled:
                                _mc_mode_opts.append("📄 เปิดบิลอย่างเดียว")
                            _mc_mode = st.radio("โหมด", _mc_mode_opts, horizontal=True,
                                                 key=f"multi_mode_{customer_name}", label_visibility="collapsed")

                            if _mc_mode == "📄 เปิดบิลอย่างเดียว":
                                _ob_pv_str = f", ⭐ {_unbilled_pv:,.0f} PV" if _unbilled_pv > 0 else ""
                                st.info(f"จะเปิดบิล {_unbilled_cnt} รายการที่ยังไม่เปิดบิล{_ob_pv_str}")
                                _ob_c1, _ob_c2 = st.columns(2)
                                _ob_bill_no   = _ob_c1.text_input("เลขที่บิลจริง (ถ้ามี — ไม่บังคับ)", key=f"multi_openonly_bn_{customer_name}")
                                _ob_bill_date = _ob_c2.date_input(
                                    "วันที่เปิดบิล", value=date.today(), key=f"multi_openonly_dt_{customer_name}")
                                if st.button("📄 เปิดบิล", type="primary",
                                             width="stretch", key=f"multi_openonly_{customer_name}") \
                                        and _guard_double_submit(f"multi_openonly_{customer_name}"):
                                    _ob_rows = sel_rows.loc[_unbilled_mask]
                                    for _, _obr in _ob_rows.iterrows():
                                        _obr_qty = int(_obr["ยังไม่เปิด"]) if "ยังไม่เปิด" in _obr else int(_obr["สั่ง"])
                                        if _obr_qty > 0:
                                            db.open_bill_partial(
                                                _obr["id"], _obr_qty,
                                                note=_ob_bill_no.strip() or None, date=str(_ob_bill_date))
                                    st.success(f"✅ เปิดบิลแล้ว {len(_ob_rows)} รายการ")
                                    for tid in txn_ids:
                                        st.session_state[f"chk_{tid}"] = False
                                    st.rerun()
                            else:
                                _recv_disabled = _mc_mode == "💵 จ่ายเงินอย่างเดียว"
                                _pay_disabled  = _mc_mode == "📦 รับของอย่างเดียว"

                                _combo_rows = [{
                                    "_id":       r["id"],
                                    "สินค้า":    r["สินค้า"],
                                    "รหัส":      r.get("รหัส", ""),
                                    "เลขที่บิล": r["เลขที่บิล"] or "—",
                                    "ค้างรับ":   int(r["ค้างรับ"]),
                                    "รับจริง":   0 if _recv_disabled else int(r["ค้างรับ"]),
                                    "ค้างจ่าย":  float(r["ค้างจ่าย"]),
                                    "จ่ายจริง":  0.0 if _pay_disabled else float(r["ค้างจ่าย"]),
                                    "สถานะบิล":  r["สถานะบิล"],
                                    "สั่ง":      int(r["สั่ง"]),
                                    "ยังไม่เปิด": int(r["ยังไม่เปิด"]) if "ยังไม่เปิด" in r and r["สถานะบิล"] == "ยังไม่เปิดบิล" else 0,
                                    "เปิดบิลกี่ชิ้น": (int(r["ยังไม่เปิด"]) if "ยังไม่เปิด" in r and r["สถานะบิล"] == "ยังไม่เปิดบิล" else 0),
                                } for _, r in sel_rows.iterrows()]
                                _combo_df = pd.DataFrame(_combo_rows)

                                _combo_cols = ["สินค้า","เลขที่บิล","ค้างรับ","รับจริง","ค้างจ่าย","จ่ายจริง","สถานะบิล"]
                                _combo_colcfg = {
                                    "สินค้า":    st.column_config.TextColumn(disabled=True),
                                    "เลขที่บิล": st.column_config.TextColumn(disabled=True),
                                    "ค้างรับ":   st.column_config.NumberColumn(disabled=True),
                                    "รับจริง":   st.column_config.NumberColumn("รับจริง ✏️", min_value=0, format="%d", disabled=_recv_disabled),
                                    "ค้างจ่าย":  st.column_config.NumberColumn(disabled=True, format="%.0f"),
                                    "จ่ายจริง":  st.column_config.NumberColumn("จ่ายจริง ✏️", min_value=0, format="%.0f", disabled=_pay_disabled),
                                    "สถานะบิล":  st.column_config.TextColumn(disabled=True),
                                }
                                if _any_unbilled:
                                    _ob_pv_str = f", ⭐ {_unbilled_pv:,.0f} PV" if _unbilled_pv > 0 else ""
                                    st.caption(f"📄 {_unbilled_cnt} รายการที่ยังไม่เปิดบิล{_ob_pv_str} — "
                                               "ใส่จำนวนที่จะเปิดบิลในคอลัมน์ \"เปิดบิลกี่ชิ้น\" ด้านล่าง "
                                               "(ลดจำนวนได้ถ้าจะเปิดบิลแค่บางส่วน ที่เหลือจะยังค้างไม่เปิดบิลต่อไป, "
                                               "0 = ไม่เปิดบิลตอนนี้)")
                                    _combo_cols = ["สินค้า","เลขที่บิล","ค้างรับ","รับจริง","ค้างจ่าย","จ่ายจริง","สถานะบิล","เปิดบิลกี่ชิ้น"]
                                    _combo_colcfg["เปิดบิลกี่ชิ้น"] = st.column_config.NumberColumn(
                                        "เปิดบิลกี่ชิ้น ✏️", min_value=0, format="%d",
                                        help="จำนวนที่จะเปิดบิลจากส่วนที่ยังไม่เปิด — ใส่น้อยกว่าเพื่อเปิดบิลบางส่วน "
                                                 "(ส่วนที่เหลือยังค้างไม่เปิดบิลต่อไปในแถวเดิม) ไม่มีผลกับรายการที่เปิดบิลแล้ว",
                                    )

                                _combo_edit = st.data_editor(
                                    _combo_df[_combo_cols],
                                    column_config=_combo_colcfg,
                                    hide_index=True, width="stretch",
                                    key=f"multi_combo_{customer_name}_{_mc_mode}",
                                )

                                _mc_c1, _mc_c2 = st.columns([2, 1])
                                mc_notes = _mc_c1.text_input("หมายเหตุ", key=f"mc_notes_{customer_name}")
                                mc_date  = _mc_c2.date_input("วันที่", value=date.today(), key=f"mc_date_{customer_name}")
                                _combo_bill_no = (
                                    st.text_input(
                                        "เลขที่บิลจริง (ถ้ามี — ไม่บังคับ, ใช้วันที่ด้านบนเป็นวันที่เปิดบิลด้วย)",
                                        key=f"mc_billno_{customer_name}")
                                    if _any_unbilled else ""
                                )

                                _mc_recv = int(_combo_edit["รับจริง"].sum())
                                _mc_pay  = float(_combo_edit["จ่ายจริง"].sum())
                                _ms1, _ms2 = st.columns(2)
                                if _mc_recv > 0:
                                    _ms1.metric("รับของรวม", f"{_mc_recv} ชิ้น")
                                if _mc_pay > 0.01:
                                    _ms2.metric("ยอดจ่ายรวม", f"{_mc_pay:,.0f} ฿")

                                if st.button("💾 บันทึกทั้งหมด", type="primary",
                                             width="stretch", key=f"multi_all_{customer_name}") \
                                        and _guard_double_submit(f"multi_all_{customer_name}"):
                                    _saved_r, _saved_p = 0, 0
                                    _mrp_received, _mrp_id_qty = [], {}
                                    _total_paid_actual = 0.0
                                    _pe_rows, _paid_full_ids = [], []
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
                                        _pe_rows.append({
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
                                                _paid_full_ids.append(row["_id"])
                                    db.insert_partial_events_batch(_pe_rows)
                                    db.update_transaction_statuses_batch(_paid_full_ids, pay_status="จ่ายแล้ว")
                                    # เปิดบิล — เปิดได้ทั้งเต็มจำนวนหรือบางส่วน (เลขบิลจริงเป็นแค่
                                    # โน้ต optional ไม่บังคับ ไม่เช็คซ้ำ) ไม่แยกแถวอีกต่อไป
                                    _opened_cnt = 0
                                    for i, row in _combo_df.iterrows():
                                        if row["สถานะบิล"] != "ยังไม่เปิดบิล":
                                            continue
                                        _bill_qty = (int(_combo_edit.iloc[i]["เปิดบิลกี่ชิ้น"])
                                                     if "เปิดบิลกี่ชิ้น" in _combo_edit.columns else 0)
                                        _remaining_qty = int(row["ยังไม่เปิด"]) if "ยังไม่เปิด" in row else int(row["สั่ง"])
                                        _bill_qty = max(0, min(_bill_qty, _remaining_qty))
                                        if _bill_qty <= 0:
                                            continue
                                        _opened_cnt += 1
                                        db.open_bill_partial(
                                            row["_id"], _bill_qty,
                                            note=_combo_bill_no.strip() or None, date=str(mc_date))
                                    _do_open_bill = _opened_cnt > 0
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
                                    if (_luid or _gid) and line_api.is_configured() and (_mrp_received or _total_paid_actual > 0.01):
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
                                        _parts.append(f"เปิดบิล {_opened_cnt} รายการ")
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
                                st.dataframe(_del_bills_rows[["เลขที่บิล", "สินค้า", "สั่ง", "ยอดรวม"]], width="stretch", hide_index=True)
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
                                        _del_cid = _cust_map_all[customer_name]["id"]
                                        _total_del = sum(db.delete_bill(b, customer_id=_del_cid) for b in _del_bnos)
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
                    _l_bill_opens = [r for r in _l_data if r["type"] == "เปิดบิล"]

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
                                    width="stretch", hide_index=True,
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
                                    width="stretch", hide_index=True,
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
                                    width="stretch", hide_index=True,
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
                    _bk_to_origin: dict = {}  # bill_no → เลขอ้างอิงบิลหลัก (origin_bill_no)

                    # Phase 1: orders → bill header (ยอดรวม/PV/qty ของทั้งบิล ไม่ว่าจะเปิดแล้วหรือยัง)
                    for _r in _l_orders:
                        _bk = _r["bill_no"] or "—"
                        _bk_to_origin[_bk] = _r.get("origin_bill_no") or _bk
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

                    # Phase 1b: เหตุการณ์ "เบิกของ" — วันที่สั่งซื้อ/เบิกของครั้งแรก โชว์เสมอ
                    # ไม่ว่าจะเปิดบิลไปแล้วหรือยัง (เปิดบิลบางส่วนได้แล้วในแถวเดิม แถวเดียวกัน
                    # จึงอาจมีทั้งเบิกของและเปิดบิลผสมกันในสถานะ "ยังไม่เปิดบิล" ได้)
                    _order_groups: dict = {}  # (bill_no, date) → {products, total, pv}
                    for _r in _l_orders:
                        _bk = _r["bill_no"] or "—"
                        _g = _order_groups.setdefault((_bk, _r["date"]), {"products": [], "total": 0.0, "pv": 0.0})
                        _g["products"].append(f"{_r['product']} ×{_r['qty_in']}")
                        _g["total"] += _r.get("total_amount", 0.0)
                        _g["pv"]    += _r.get("pv", 0.0)
                    for (_bk, _ed), _g in _order_groups.items():
                        if _bk not in _bills_tl:
                            continue
                        _bills_tl[_bk]["events"].append({
                            "date": _ed, "order": -1, "type": "เปิดบิล",
                            "detail": ",  ".join(_g["products"]),
                            "total": _g["total"], "pv": _g["pv"],
                            "bill_status": "ยังไม่เปิดบิล",
                        })

                    # Phase 1c: เหตุการณ์ "เปิดบิล" จริง — จาก bill_open_events (event-based,
                    # โน้ตเลขบิลจริงมาด้วย) จัดกลุ่มตาม (บิล, วันที่เปิดบิลจริง)
                    _bills_with_real_open_evt = {r["bill_no"] or "—" for r in _l_bill_opens}
                    _real_open_groups: dict = {}
                    for _r in _l_bill_opens:
                        _bk = _r["bill_no"] or "—"
                        _g = _real_open_groups.setdefault((_bk, _r["date"]), {"products": [], "total": 0.0, "pv": 0.0, "notes": []})
                        _g["products"].append(f"{_r['product']} ×{_r['qty_opened']}")
                        _g["total"] += _r.get("amount_opened", 0.0)
                        _g["pv"]    += _r.get("pv_opened", 0.0)
                        if _r.get("note"):
                            _g["notes"].append(_r["note"])
                    for (_bk, _ed), _g in _real_open_groups.items():
                        if _bk not in _bills_tl:
                            continue
                        _note_str = ", ".join(dict.fromkeys(_g["notes"]))
                        _bills_tl[_bk]["events"].append({
                            "date": _ed, "order": 0, "type": "เปิดบิล",
                            "detail": ",  ".join(_g["products"]),
                            "total": _g["total"], "pv": _g["pv"],
                            "bill_status": "เปิดบิลแล้ว",
                            "note": _note_str,
                        })

                    # Phase 1d: fallback สำหรับบิลเก่าที่เปิดผ่าน split_and_open_bill (ก่อนมี
                    # bill_open_events) — bill_status="เปิดบิลแล้ว" แต่ไม่มี event จริงผูกอยู่
                    # เลย ต้อง synthesize เหมือนเดิม กันประวัติหายไปจากตาราง
                    _legacy_open_groups: dict = {}
                    for _r in _l_orders:
                        _bk = _r["bill_no"] or "—"
                        if _bk in _bills_with_real_open_evt or _r.get("bill_status") != "เปิดบิลแล้ว":
                            continue
                        _ed = _r.get("bill_opened_at") or _r["date"]
                        _g = _legacy_open_groups.setdefault((_bk, _ed), {"products": [], "total": 0.0, "pv": 0.0})
                        _g["products"].append(f"{_r['product']} ×{_r['qty_in']}")
                        _g["total"] += _r.get("total_amount", 0.0)
                        _g["pv"]    += _r.get("pv", 0.0)
                    for (_bk, _ed), _g in _legacy_open_groups.items():
                        if _bk not in _bills_tl:
                            continue
                        _bills_tl[_bk]["events"].append({
                            "date": _ed, "order": 0, "type": "เปิดบิล",
                            "detail": ",  ".join(_g["products"]),
                            "total": _g["total"], "pv": _g["pv"],
                            "bill_status": "เปิดบิลแล้ว",
                        })

                    # delivery type heuristic per bill
                    _ship_dates_set = {_r["date"] for _r in _l_ships}
                    _recv_bill_set  = {_r["bill_no"] for _r in _l_receipts if _r["bill_no"]}
                    _initial_recv_by_bill: dict = {}
                    for _r in _l_orders:
                        _ibk = _r["bill_no"] or "—"
                        _initial_recv_by_bill[_ibk] = _initial_recv_by_bill.get(_ibk, 0) + _r.get("initial_received", 0)

                    for _bk, _bv in _bills_tl.items():
                        if _bv["date"] in _ship_dates_set:
                            _dlv = "🚚 ส่งพัสดุ"
                        elif _bk in _recv_bill_set:
                            _dlv = "🏪 รับหน้าร้าน"
                        elif _bv["qty"] > 0 and _initial_recv_by_bill.get(_bk, 0) >= _bv["qty"]:
                            # รับของครบตั้งแต่ตอนขาย (เลือก "รับแล้ว" ตอนบันทึกขาย) — ไม่มี
                            # ทั้ง shipment หรือ partial_events "รับของ" เพราะไม่จำเป็นต้องมี
                            # แต่ก็ไม่ใช่ของฝาก (ยังไม่ให้ลูกค้า) เหมือนที่ค่า default เดิมเข้าใจผิด
                            _dlv = "✅ รับแล้ว"
                        else:
                            _dlv = "📦 ฝากของ"
                        _bv["delivery"] = _dlv

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
                    def _render_event_line(_r, _tag=""):
                        _tagstr = f"{_tag} " if _tag else ""
                        if _r["type"] == "เปิดบิล":
                            _is_billed_evt = _r.get("bill_status") == "เปิดบิลแล้ว"
                            _evt_icon  = "📋" if _is_billed_evt else "📦"
                            _evt_label = "เปิดบิล" if _is_billed_evt else "เบิกของ (ยังไม่เปิดบิล)"
                            _note_str = f"  เลขบิลจริง: {_r['note']}" if _r.get("note") else ""
                            st.caption(
                                f"{_evt_icon} {_r['date']} {_tagstr}{_evt_label} — {_r['detail']}  "
                                f"(รวม {_r['total']:,.0f}฿"
                                + (f", {_r['pv']:.0f} PV" if _r['pv'] > 0 else "")
                                + ")" + _note_str
                            )
                        elif _r["type"] == "จ่ายเงิน":
                            _pay_details = _r.get("details", [])
                            if _pay_details:
                                _pd_str = " + ".join(f"{a:,.0f}" for a in _pay_details)
                                st.caption(
                                    f"💰 {_r['date']} {_tagstr}จ่ายเงิน {_r['amount']:,.0f}฿ "
                                    f"({_pd_str}) — คงค้าง {_r['remaining']:,.0f}฿"
                                )
                            else:
                                st.caption(
                                    f"💰 {_r['date']} {_tagstr}จ่ายเงิน {_r['amount']:,.0f}฿ "
                                    f"(คงค้าง {_r['remaining']:,.0f}฿)"
                                )
                        elif _r["type"] == "รับของ":
                            st.caption(
                                f"📦 {_r['date']} {_tagstr}รับของ {_r['detail']} "
                                f"(ค้างรับเหลือ {_r['remaining_qty']} ชิ้น)"
                            )
                        elif _r["type"] == "ส่งพัสดุ":
                            st.caption(f"🚚 {_r['date']} {_tagstr}ส่งพัสดุ {_r['detail']}  Tracking: {_r['tracking']}")

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

                    # ── บิลหลัก: กลุ่มบิลที่แยกมาจากเลขอ้างอิงเดียวกัน (เปิดบิล
                    # บางส่วนแล้วแยกเลขบิลจริงออกไป) — โชว์สรุปรวมทั้งกลุ่มก่อน
                    # แล้วค่อยแสดงบิลย่อยแต่ละใบ (expander) ตามปกติด้านล่าง
                    _families: dict = {}
                    for _bk in _bills_tl:
                        _families.setdefault(_bk_to_origin.get(_bk, _bk), []).append(_bk)
                    for _origin, _members in _families.items():
                        if len(_members) <= 1:
                            continue
                        _fam_qty = sum(_bills_tl[m]["qty"] for m in _members)
                        _fam_recv = sum(_recv_cumul.get(m, 0) for m in _members)
                        _fam_owed = sum(_owed_map.get(m, 0.0) for m in _members)
                        _fam_opened_qty = sum(
                            _bills_tl[m]["qty"] for m in _members if _bills_tl[m]["bill_status"] == "เปิดบิลแล้ว"
                        )
                        st.markdown(f"#### 🗂️ บิลหลัก {_origin}")
                        _fm1, _fm2, _fm3, _fm4 = st.columns(4)
                        _fm1.metric("สั่งทั้งหมด", f"{_fam_qty:,} ชิ้น")
                        _fm2.metric("รับแล้ว", f"{_fam_recv:,} ชิ้น")
                        _fm3.metric("ค้างจ่ายรวม", f"{_fam_owed:,.0f} ฿")
                        _fm4.metric("เหลือเปิดบิล", f"{max(0, _fam_qty - _fam_opened_qty):,} ชิ้น")

                        # ── ตารางรวมรายสินค้า: รวมแถวที่แยกจากการเปิดบิลบางส่วน
                        # (สินค้าเดียวกัน คนละบิลจริงคนละแถว) ให้เหลือแถวเดียวต่อสินค้า
                        # พร้อมคอลัมน์เปิดบิลแล้ว/ยังไม่เปิด แยกให้เห็นว่าส่วนไหนเปิดไปแล้ว
                        _fam_prod = merge_bill_family_products(_l_all_df, _origin)
                        st.dataframe(
                            _fam_prod[[
                                "วันที่", "รหัส", "สินค้า", "สั่ง", "รับแล้ว", "ยอดรวม", "จ่ายแล้ว",
                                "ค้างจ่าย", "ค้างรับ", "เปิดบิลแล้ว", "ยังไม่เปิด",
                                "สถานะบิล", "สถานะจ่าย", "สถานะรับของ", "หมายเหตุ",
                            ]].style.format({"ยอดรวม": "{:,.0f}", "จ่ายแล้ว": "{:,.0f}", "ค้างจ่าย": "{:,.0f}"}),
                            width="stretch", hide_index=True,
                        )

                        # ── ประวัติรวมทุกบิลย่อยในกลุ่มนี้ เรียงตามวันที่ mark เลขบิล ──
                        st.markdown("**📜 ประวัติ**")
                        _fam_events = []
                        for m in _members:
                            for _ev in _bills_tl[m]["events"]:
                                _fam_events.append({**_ev, "_bill": m})
                        _fam_events.sort(key=lambda e: (e["date"], e["order"]))
                        for _fev in _fam_events:
                            _render_event_line(_fev, _tag=f"[{_fev['_bill']}]")
                        st.divider()

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
                                .map(lambda v: "background-color:#FDECEA;color:#C0392B;font-weight:600"
                                     if isinstance(v, (int, float)) and v > 0 else "",
                                     subset=["ค้างรับ", "ค้างจ่าย"]),
                                width="stretch", hide_index=True,
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
                        # ถ้าเป็นสมาชิกของ "บิลหลัก" (โชว์ตารางรวม+ประวัติรวมไปแล้วด้านบน)
                        # ให้ย่อ expander นี้ไว้ก่อน — เปิดดูเพิ่มได้เมื่อต้องการ (ลบบิล/ส่ง LINE)
                        _in_family = len(_families.get(_bk_to_origin.get(_bk, _bk), [])) > 1
                        with st.expander(_exp_hdr, expanded=not _in_family):
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
                                _dlv_raw = _bv.get("delivery", "")
                                _disp["สถานะรับของ"] = _dlv_raw.split(" ", 1)[1] if " " in _dlv_raw else _dlv_raw
                                _disp = _disp[_l_table_cols_disp]
                                st.dataframe(
                                    _disp, hide_index=True, width="stretch",
                                    column_config={
                                        "ยอดรวม":   st.column_config.NumberColumn("ยอดรวม", format="%,.0f"),
                                        "จ่ายแล้ว": st.column_config.NumberColumn("จ่ายแล้ว", format="%,.0f"),
                                        "ค้างจ่าย": st.column_config.NumberColumn("ค้างจ่าย", format="%,.0f"),
                                    },
                                )

                            # ── ประวัติเหตุการณ์ของบิลนี้ เรียงตามวันที่ ──────────
                            st.markdown("**📜 ประวัติ**")
                            for _r in _bv["events"]:
                                _render_event_line(_r)

                            # ── ส่งสรุปบิล LINE ──────────────────────────────────
                            _bl_luid = _l_cust.get("line_user_id") or ""
                            _bl_gid  = _l_cust.get("group_id") or ""
                            if line_api.is_configured() and not _bill_rows.empty:
                                if st.button(
                                    "📨 ส่งสรุปบิล LINE" if (_bl_luid or _bl_gid) else "📨 ไม่มี LINE ID",
                                    key=f"ledger_bill_line_{_bk}_{_l_sel}",
                                    disabled=not (_bl_luid or _bl_gid),
                                ):
                                    _bl_items = [
                                        {"name": r["สินค้า"], "qty": int(r["สั่ง"]), "total": float(r["ยอดรวม"])}
                                        for _, r in _bill_rows.iterrows()
                                    ]
                                    _bl_total = float(_bill_rows["ยอดรวม"].sum())
                                    _bl_paid  = float(_bill_rows["จ่ายแล้ว"].sum())
                                    # โชว์เลขบิลจริง (โน้ตจาก event เปิดบิล) ถ้ามี ไม่งั้น fallback
                                    # เป็นเลขอ้างอิงภายใน (bill_no ไม่ถูกเขียนทับด้วยเลขจริงอีกแล้ว)
                                    _bl_notes = [e["note"] for e in _bv["events"] if e.get("type") == "เปิดบิล" and e.get("note")]
                                    _bl_bill_label = _bl_notes[-1] if _bl_notes else _bk
                                    _bl_res = line_api.push_bill_summary(
                                        _bl_luid, _l_sel, _bl_bill_label,
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
                                        _n = db.delete_bill(_bk, customer_id=_l_cust["id"])
                                        st.success(f"✅ ลบบิล {_bk} แล้ว ({_n} รายการ)")
                                        st.rerun()

                    # ── ลบ partial event ──────────────────────────────────────
                    _ldel_rows = [
                        (i, str(r.get("event_id") or ""))
                        for i, r in enumerate(_l_data) if r.get("event_id")
                    ]
                    # ── ยกเลิกเปิดบิล (undo) — คืน bill_status/bill_no กลับเป็นก่อน
                    # เปิดบิล เหมือน "ลบ" เหตุการณ์เปิดบิลออกจากประวัติ
                    _lopened_rows = [
                        (i, r["txn_id"]) for i, r in enumerate(_l_data)
                        if r.get("type") == "สั่งซื้อ" and r.get("bill_status") == "เปิดบิลแล้ว"
                    ]
                    if _ldel_rows or _lopened_rows:
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
                            for _loi, _ltid in _lopened_rows:
                                _llr = _l_data[_loi]
                                _lbno = _llr.get("bill_no") or ""
                                _llabel = f"{_llr['date'][:10]}  เปิดบิล {_lbno}  {_llr.get('product','') or ''}"
                                if st.button(f"🗑️ {_llabel}", key=f"lundo_open_{_loi}_{_l_sel}"):
                                    db.undo_last_bill_open_event(_ltid)
                                    st.rerun()
                else:
                    st.caption("ไม่มีประวัติ")

    elif _t5_active == _T5_TABS[2]:
        history_all_ui.render(customers)

    elif _t5_active == _T5_TABS[3]:
        shipment_history_ui.render(customers)

    elif _t5_active == _T5_TABS[4]:
        cod_tracking_ui.render()
