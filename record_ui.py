import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from datetime import date
from math import ceil, floor
import uuid

import database as db
import calc_logic
import line_api
import iship_api
from flash_zones import carrier_fees
from ui_helpers import (
    _PROVINCES, BOX_WEIGHT_G, _tambon_selectbox, _postcode_suggest,
    _warn_duplicate_phone, calc_shipping, raw_weight_g, _parse_iship_address,
    _quick_add_customer, _extract_tracking, _build_success_info,
    _process_old_items_receipt, _pick_carrier, _parse_quick_order,
    get_bulky_presets, _render_cart_card, _cart_add_items,
)
import carriers as carr


_T1_TABS = ["📝 บันทึกขาย", "📦 ส่งของ", "🔢 คำนวณยอด"]


def render(tab1, products, customers, customer_map):
    """Render tab1: บันทึกรายการ (sub_calc, sub_ship, sub_sale)."""
    with tab1:
        try:
            _sub_active = st.pills("", _T1_TABS, key="_t1_active_sub", label_visibility="collapsed") or _T1_TABS[0]
        except AttributeError:
            _sub_active = st.radio("", _T1_TABS, horizontal=True, key="_t1_active_sub", label_visibility="collapsed")

        if _sub_active == "📝 บันทึกขาย":
            _sale_keys = ["_cust_picked","m_cust_search","_adding_cust",
                          "m_bill","m_pay","m_delivery","m_cod","m_partial_amount",
                          "_cart_base","m_postcode","m_carrier","m_zone","m_iship_note",
                          "r_name","r_phone","r_al","r_dt","r_am","r_pv",
                          "_carrier_sig","_prev_pc","_prev_pay","_prev_shipping_cid","_last_rph_fill",
                          "_r_last_dt","_r_last_pc","_fr_dt","_fr_am","_fr_pv",
                          "_fr_rname","_fr_rphone","_fr_al",
                          "r_dt_searchbox","_r_dt_searchbox_sig",
                          "_prev_cust_search"]
            _cart_ver = st.session_state.get("_cart_version", 0)
            _cart_key = f"m_cart_{_cart_ver}"

            _sale_h1, _sale_h2 = st.columns([6, 1])
            _sale_h1.subheader("บันทึกรายการขาย")
            if st.session_state.get("_do_clear_after_iship") == "sale":
                st.session_state.pop("_do_clear_after_iship", None)
                st.session_state.pop("_iship_carrier_select", None)
                st.session_state.pop("_iship_success_info", None)
                for _k in _sale_keys:
                    st.session_state.pop(_k, None)
                for _k in ["r_name","r_phone","r_al","r_dt","r_am","r_pv","m_postcode","m_iship_note"]:
                    st.session_state[_k] = ""
                st.session_state.pop("_sale_last_tracking", None)
                st.session_state.pop(_cart_key, None)
                st.session_state["_cart_version"] = _cart_ver + 1
                st.rerun()

            if _sale_h2.button("🗑️ ล้าง", key="sale_clear_form", use_container_width=True):
                for _k in _sale_keys:
                    st.session_state.pop(_k, None)
                st.session_state.pop(_cart_key, None)
                st.session_state["_cart_version"] = _cart_ver + 1
                st.rerun()

            if not products:
                st.warning("⚠️ ยังไม่มีข้อมูลสินค้า กรุณาเพิ่มสินค้าใน Tab ⚙️ ก่อน")
            elif not customers:
                st.warning("⚠️ ยังไม่มีข้อมูลลูกค้า กรุณาเพิ่มลูกค้าใน Tab ⚙️ ก่อน")
            else:
                product_map = {p["name"]: p for p in products}
                customer_map = {c["name"]: c for c in customers}

                # ── ค้นหาลูกค้าจากเบอร์โทร ─────────────────────────────────────
                mc1, mc2 = st.columns([3, 1])
                with mc1:
                    _cust_picked = st.session_state.get("_cust_picked", "")
                    if _cust_picked:
                        cp1, cp2 = st.columns([5, 1])
                        cp1.success(f"👤 **{_cust_picked}**")
                        _r_preview = " · ".join(filter(None, [
                            st.session_state.get("r_name", ""),
                            st.session_state.get("r_al", ""),
                            st.session_state.get("r_am", ""),
                            st.session_state.get("r_pv", ""),
                            st.session_state.get("m_postcode", ""),
                        ]))
                        if _r_preview:
                            cp1.caption(_r_preview)
                        if cp2.button("✕", key="cust_clear", help="เลือกลูกค้าใหม่"):
                            st.session_state.pop("_cust_picked", None)
                            st.session_state.pop("_prev_shipping_cid", None)
                            st.session_state.pop("m_cust_search", None)
                            st.rerun()
                        m_customer = _cust_picked
                    else:
                        _cust_options = ["— เลือกลูกค้า —"] + sorted(customer_map.keys(), key=str.casefold)
                        _cust_sel = st.selectbox("ลูกค้า", _cust_options, key="m_cust_search")
                        m_customer = "— เลือกลูกค้า —"
                        if _cust_sel != "— เลือกลูกค้า —":
                            st.session_state["_cust_picked"] = _cust_sel
                            st.rerun()
                        _quick_add_customer("")
                m_date = mc2.date_input("วันที่", value=date.today(), key="m_date")

                # ── รับของจากบิลเก่า ─────────────────────────────────────────────
                _rx_df = None
                _rx_edit = None
                _rx_pay_map = {}
                _rx_total_qty = 0
                _rx_total_pay = 0.0
                _rx_old_items = []
                _pending_rx = []
                _cur_delivery = st.session_state.get("m_delivery", "ฝากของ")
                if m_customer != "— เลือกลูกค้า —" and m_customer in customer_map:
                    _recv_cid = customer_map[m_customer]["id"]
                    _pending_rx = db.get_pending_receipts_for_customer(_recv_cid)
                    if _pending_rx:
                        _rx_label = ("📦 รับของจากบิลเก่า — จะรวมในพัสดุอัตโนมัติ"
                                     if _cur_delivery == "ส่งพัสดุ"
                                     else f"📦 รับของจากบิลเก่า ({sum(p['ค้างรับ'] for p in _pending_rx)} ชิ้นค้างรับ)")
                        with st.expander(_rx_label, expanded=(_cur_delivery == "ส่งพัสดุ")):
                            _prod_map_rx = {p["id"]: p["name"] for p in products}
                            _rx_df = pd.DataFrame([{
                                "สินค้า":     _prod_map_rx.get(p["product_id"], p["product_id"]),
                                "บิล":        p.get("bill_no") or "—",
                                "สถานะจ่าย":  ("จ่ายแล้ว ✅" if p.get("outstanding_amt", 0) <= 0.01
                                               else ("COD 💛" if p.get("pay_status") == "COD"
                                                     else f"ค้างจ่าย {p['outstanding_amt']:,.0f} ฿")),
                                "ค้างรับ":    p["ค้างรับ"],
                                "รับวันนี้":  0,
                                "_tid":       p["id"],
                                "_max":       p["ค้างรับ"],
                                "_owed":      p.get("outstanding_amt", 0.0),
                            } for p in _pending_rx])
                            _rx_edit = st.data_editor(
                                _rx_df[["สินค้า","บิล","สถานะจ่าย","ค้างรับ","รับวันนี้"]],
                                hide_index=True, use_container_width=True,
                                column_config={
                                    "รับวันนี้": st.column_config.NumberColumn("รับวันนี้", min_value=0, step=1, width="small"),
                                },
                                disabled=["สินค้า","บิล","สถานะจ่าย","ค้างรับ"],
                                key=f"sale_recv_old_{_recv_cid}",
                            )
                            _rx_recv_rows = []
                            for _ri, _rrow in _rx_edit.iterrows():
                                _qty = min(int(_rrow["รับวันนี้"] or 0), int(_rx_df.iloc[_ri]["_max"]))
                                if _qty > 0:
                                    _rx_recv_rows.append({
                                        "สินค้า":    _rx_df.iloc[_ri]["สินค้า"],
                                        "รับวันนี้": _qty,
                                        "จ่ายมา":    0.0,
                                        "_tid":      _rx_df.iloc[_ri]["_tid"],
                                    })
                            if _rx_recv_rows:
                                if st.checkbox("✏️ ระบุยอดจ่ายเอง (ถ้าลูกค้าจ่ายไม่ตรงสัดส่วน)", key=f"sale_recv_custom_chk_{_recv_cid}"):
                                    _rx_pay_df = pd.DataFrame(_rx_recv_rows)
                                    _rx_pay_edit = st.data_editor(
                                        _rx_pay_df[["สินค้า","รับวันนี้","จ่ายมา"]],
                                        hide_index=True, use_container_width=True,
                                        column_config={
                                            "จ่ายมา": st.column_config.NumberColumn(
                                                "จ่ายมา (฿)", min_value=0.0, step=1.0, width="small",
                                                help="ถ้าไม่กรอก ระบบจะคำนวณให้อัตโนมัติตามสัดส่วนที่รับ",
                                            ),
                                        },
                                        disabled=["สินค้า","รับวันนี้"],
                                        key=f"sale_recv_custom_{_recv_cid}",
                                    )
                                    for _pi, _prow in _rx_pay_edit.iterrows():
                                        _cp = float(_prow.get("จ่ายมา", 0) or 0)
                                        if _cp > 0:
                                            _rx_pay_map[_rx_pay_df.iloc[_pi]["_tid"]] = _cp
                            for _ri, _rrow in _rx_edit.iterrows():
                                _qty = min(int(_rrow["รับวันนี้"] or 0), int(_rx_df.iloc[_ri]["_max"]))
                                if _qty <= 0:
                                    continue
                                _owed_this  = float(_rx_df.iloc[_ri]["_owed"])
                                _cap        = int(_rx_df.iloc[_ri]["_max"])
                                _custom_pay = _rx_pay_map.get(_rx_df.iloc[_ri]["_tid"], 0.0)
                                if _custom_pay > 0:
                                    _pay = round(min(_custom_pay, _owed_this), 2)
                                else:
                                    _pay = round(_owed_this * _qty / _cap, 2) if _owed_this > 0.01 and _cap > 0 else 0.0
                                _rx_total_qty += _qty
                                _rx_total_pay += _pay
                                _rx_old_items.append({
                                    "product_id": _pending_rx[_ri]["product_id"],
                                    "name":       str(_rx_df.iloc[_ri]["สินค้า"]),
                                    "qty":        _qty,
                                    "amount":     _pay,
                                })
                            if _rx_total_qty > 0:
                                st.caption(f"📥 รับของเก่าวันนี้: {_rx_total_qty} ชิ้น · ยอดที่จะบันทึกว่าจ่าย {_rx_total_pay:,.0f} ฿")
                            if _cur_delivery == "ส่งพัสดุ":
                                st.caption("ของที่กรอก 'รับวันนี้' จะถูกรวมในพัสดุเมื่อกด บันทึกทั้งหมด · ยอดค้างจะถูกปรับตามสัดส่วน")
                            elif not _cur_delivery:
                                st.caption("⬆️ เลือก การรับของ ด้านบนก่อน")
                            elif _cur_delivery in ("ฝากของ", "รับแล้ว"):
                                if st.button("💾 บันทึกรับของจากบิลเก่า", key="sale_recv_old_btn", type="primary"):
                                    _saved_rx, _total_pay, _ = _process_old_items_receipt(
                                        _rx_edit, _rx_df, _rx_pay_map, _pending_rx,
                                        event_date=str(m_date),
                                    )
                                    if _saved_rx:
                                        _pay_note = f" · ปรับยอดค้าง ฿{_total_pay:,.0f}" if _total_pay > 0.01 else ""
                                        st.success(f"✅ บันทึกรับของ {_saved_rx} รายการ{_pay_note}")
                                        st.rerun()
                                    else:
                                        st.warning("ยังไม่ได้กรอกจำนวนรับ")

                # ── น้ำหนักจากของค้างที่กำลังรับ ─────────────────────────────────
                _prod_weight_map   = {p["id"]: float(p.get("weight_grams") or 0) for p in products}
                _rx_extra_weight_g = 0.0
                _has_rx_action     = False
                if _rx_df is not None and _rx_edit is not None:
                    for _ri, _rrow in _rx_edit.iterrows():
                        _qty_now = int(_rrow.get("รับวันนี้") or 0)
                        if _qty_now > 0:
                            _pid = _pending_rx[_ri]["product_id"]
                            _rx_extra_weight_g += _prod_weight_map.get(_pid, 0) * min(_qty_now, int(_rx_df.iloc[_ri]["_max"]))
                            _has_rx_action = True

                # ── Reset recipient fields when customer changes ─────────────────────
                if m_customer != "— เลือกลูกค้า —":
                    if m_customer not in customer_map:
                        st.rerun()  # รอ customers reload หลังเพิ่งเพิ่มใหม่
                    _cid_detect = customer_map[m_customer]["id"]
                    if st.session_state.get("_prev_shipping_cid") != _cid_detect:
                        st.session_state["_prev_shipping_cid"] = _cid_detect
                        _ca_d = customer_map[m_customer]
                        for _k, _v in [
                            ("r_name",  ""),
                            ("r_phone", ""),
                            ("r_al",    ""),
                            ("r_dt",    ""),
                            ("r_am",    ""),
                            ("r_pv",    ""),
                        ]:
                            st.session_state[_k] = _v
                        st.session_state["_staged_pc"] = ""

                # auto-set COD ก่อน render สถานะ
                _cur_pay = st.session_state.get("m_pay", "ค้างจ่าย")
                if _cur_pay == "COD" and st.session_state.get("_prev_pay") != "COD":
                    st.session_state["m_bill"]     = "ยังไม่เปิดบิล"
                    st.session_state["m_delivery"] = "ส่งพัสดุ"
                    st.session_state["_prev_pay"]  = "COD"
                elif _cur_pay != "COD":
                    st.session_state["_prev_pay"] = _cur_pay
                _delivery_opts = ["ส่งพัสดุ", "ฝากของ", "รับแล้ว"]

                # ── รายการสินค้า: เพิ่มสินค้า+สถานะ | ตะกร้า | สรุปยอด ──────────────
                with st.container(key="sale_status_cart_summary_row"):
                    _status_col, _cart_col, _summary_col = st.columns([1.0, 1.9, 1.0], gap="medium")

                with _status_col:
                    with st.container(key="sale_status_panel", border=True):
                        st.markdown("**สถานะรายการ**")
                        with st.container(key="sale_status_subrow"):
                            _sc1, _sc2 = st.columns(2)
                        m_delivery = _sc1.radio("การรับของ", _delivery_opts, key="m_delivery", index=None)
                        m_pay  = _sc2.radio("การจ่าย", ["ค้างจ่าย", "จ่ายแล้ว", "COD", "จ่ายบางส่วน"], key="m_pay", index=None)
                        st.divider()
                        with st.container(key="sale_status_bill_row"):
                            m_bill = st.radio("สถานะบิล", ["ยังไม่เปิดบิล", "เปิดบิลแล้ว"], horizontal=True, key="m_bill", index=None)

                with _cart_col:
                    _qtext_ver = st.session_state.get("_qtext_ver", 0)
                    _qtext_key = f"q_text_{_qtext_ver}"
                    with st.container(border=True):
                        st.markdown("**เพิ่มสินค้า**")
                        q_text = st.text_input(
                            "รหัสสินค้า",
                            placeholder="พิมพ์รหัสสินค้า (เต็มหรือบางส่วนก็ได้) เช่น tf2581 — Enter เพื่อเพิ่มเลย",
                            key=_qtext_key, label_visibility="collapsed",
                        )
                        _q_submit = st.button("📋 เพิ่ม", key=f"q_to_cart_{_qtext_ver}", type="primary", use_container_width=True)
                        if _q_submit or q_text.strip():
                            _qf, _qu = _parse_quick_order(q_text or "", products)
                            if _qf:
                                _cart_add_items(_cart_key, _qf)
                                st.session_state["_qtext_ver"] = _qtext_ver + 1
                                st.rerun()
                            elif _qu:
                                # ไม่เจอ/ไม่ชัดเจน — ไม่ rerun เพื่อให้ error ค้างให้เห็น
                                # (ไม่ bump version ด้วย เพื่อให้ข้อความเดิมยังอยู่ให้แก้ไขต่อได้)
                                st.error(f"❌ ไม่พบ/ไม่ชัดเจน: {', '.join(_qu)}")

                        # กด Enter แล้วเคอร์เซอร์หลุดโฟกัส (รีรันสร้าง input ใหม่ทุกครั้ง
                        # เพราะ key เป็น version-suffixed) — โฟกัสกลับให้อัตโนมัติ ไม่ต้องเอา
                        # เมาส์มาคลิกซ้ำเพื่อพิมพ์รหัสถัดไปต่อได้เลย
                        components.html(
                            """
                            <script>
                            (function() {
                                try { window.parent.focus(); } catch (e) {}
                                var tries = 0;
                                function tryFocus() {
                                    tries++;
                                    try {
                                        var doc = window.parent.document;
                                        var input = doc.querySelector('input[placeholder*="พิมพ์รหัสสินค้า"]');
                                        if (input && doc.activeElement !== input) {
                                            input.focus({preventScroll: true});
                                            input.click();
                                        }
                                    } catch (e) {}
                                    if (tries < 20) { setTimeout(tryFocus, 100); }
                                }
                                requestAnimationFrame(tryFocus);
                            })();
                            </script>
                            """,
                            height=0,
                        )

                    valid_items = _render_cart_card(_cart_key, products, title="บันทึกรายการขาย")

                    # ── ที่อยู่ผู้รับ (อยู่ใต้รายการสินค้าทันที เมื่อเลือกส่งพัสดุ) ──
                    if m_delivery == "ส่งพัสดุ":
                        _cid = customer_map[m_customer]["id"] if m_customer != "— เลือกลูกค้า —" else "no_cust"
                        with st.expander("📦 ที่อยู่ผู้รับ", expanded=True):
                            # ── quick-select ที่อยู่เดิมของลูกค้า ──────────────────
                            if m_customer != "— เลือกลูกค้า —":
                                try:
                                    _saved_addrs = db.get_customer_addresses(customer_id=_cid)
                                except Exception as _sa_load_e:
                                    _saved_addrs = []
                                    st.caption(f"⚠️ โหลดที่อยู่เดิมไม่สำเร็จ: {_sa_load_e}")
                                if _saved_addrs:
                                    with st.expander(f"⚡ เลือกที่อยู่เดิม ({len(_saved_addrs)})", expanded=False):
                                        for _sa in _saved_addrs:
                                            _sa_label = f"{_sa.get('recipient_name','')} · {_sa.get('phone','')} · {_sa.get('address_line','')} {_sa.get('district','')} {_sa.get('amphure','')} {_sa.get('province','')} {_sa.get('postal_code','')}"
                                            if st.button(_sa_label, key=f"qa_{_sa['id']}", use_container_width=True):
                                                _qa_dt = (_sa.get("district", "") or "").strip()
                                                _qa_pc = (_sa.get("postal_code", "") or "").strip()
                                                st.session_state["_fr_rname"] = _sa.get("recipient_name", "")
                                                st.session_state["_fr_rphone"]= _sa.get("phone", "")
                                                st.session_state["_fr_al"]  = _sa.get("address_line", "")
                                                st.session_state["_fr_dt"]  = _qa_dt
                                                st.session_state["_fr_am"]  = _sa.get("amphure", "")
                                                st.session_state["_fr_pv"]  = _sa.get("province", "")
                                                st.session_state["_staged_pc"]     = _qa_pc
                                                st.session_state["_r_last_dt"]     = _qa_dt
                                                st.session_state["_r_last_pc"]     = _qa_pc
                                                st.session_state["_last_rph_fill"] = _sa.get("phone", "")
                                                st.rerun()
                            _parse_key = f"_show_paste_{_cid}"
                            if st.button("📍 แยกที่อยู่อัตโนมัติ", key=f"parse_open_{_cid}"):
                                st.session_state[_parse_key] = not st.session_state.get(_parse_key, False)
                            if st.session_state.get(_parse_key):
                                paste_txt = st.text_area(
                                    "วางที่อยู่จาก LINE (iShip format)",
                                    key=f"paste_{_cid}", height=100, placeholder=
                                    "Boo Mee\nสวนหลวง/ Suan Luang,\nกรุงเทพมหานคร/ Bangkok,\n10250  14 Rama IX Soi 41\n0617490976"
                                )
                                _pc1, _pc2 = st.columns([1, 1])
                                if _pc1.button("✅ ตกลง", key=f"parse_btn_{_cid}", type="primary"):
                                    _parsed = _parse_iship_address(paste_txt)
                                    st.session_state["_fr_rname"]  = _parsed.get("dst_name", "")
                                    st.session_state["_fr_rphone"] = _parsed.get("dst_phone", "")
                                    st.session_state["_fr_al"]     = _parsed.get("address_line", "")
                                    st.session_state["_fr_dt"]     = _parsed.get("district", "")
                                    st.session_state["_fr_am"]     = _parsed.get("amphure", "")
                                    st.session_state["_fr_pv"]     = _parsed.get("province", "")
                                    st.session_state["_staged_pc"] = _parsed.get("zipcode", "")
                                    st.session_state[_parse_key] = False
                                    st.rerun()
                                if _pc2.button("ยกเลิก", key=f"parse_cancel_{_cid}"):
                                    st.session_state[_parse_key] = False
                                    st.rerun()
                            st.divider()
                            _cur_rph = st.session_state.get("r_phone", "")
                            if len(_cur_rph.strip()) == 10 and st.session_state.get("_last_rph_fill") != _cur_rph.strip():
                                try:
                                    _rph_addr = db.get_address_by_phone(_cur_rph.strip())
                                except Exception:
                                    _rph_addr = None
                                st.session_state["_last_rph_fill"] = _cur_rph.strip()
                                if _rph_addr:
                                    for _k, _v in [
                                        ("r_name", _rph_addr.get("recipient_name") or ""),
                                        ("r_al",   _rph_addr.get("address_line") or ""),
                                        ("r_dt",   _rph_addr.get("district") or ""),
                                        ("r_am",   _rph_addr.get("amphure") or ""),
                                        ("r_pv",   _rph_addr.get("province") or ""),
                                    ]:
                                        if _v: st.session_state[_k] = _v
                                    if _rph_addr.get("postal_code"):
                                        st.session_state["m_postcode"] = _rph_addr["postal_code"]
                                    _rph_cust = (_rph_addr.get("customers") or {}).get("name", "")
                                    if _rph_cust and not st.session_state.get("_cust_picked"):
                                        st.session_state["_cust_picked"] = _rph_cust
                                        st.session_state["_prev_shipping_cid"] = _rph_addr.get("customer_id", "")
                            # apply staged address fill ก่อน render ทุก widget
                            for _fk, _wk in [("_fr_rname","r_name"),("_fr_rphone","r_phone"),("_fr_al","r_al"),
                                              ("_fr_dt","r_dt"),("_fr_am","r_am"),("_fr_pv","r_pv")]:
                                if _fk in st.session_state:
                                    st.session_state[_wk] = st.session_state.pop(_fk)
                            col_a, col_b = st.columns(2)
                            r_name      = col_a.text_input("ชื่อผู้รับ",   key="r_name")
                            r_phone     = col_b.text_input("เบอร์โทร",     key="r_phone")
                            _warn_duplicate_phone(r_phone, _cid)
                            r_addr_line = st.text_input("บ้านเลขที่/ถนน", key="r_al")
                            col_c, col_d, col_e = st.columns(3)
                            with col_c:
                                r_district = _tambon_selectbox("r_dt", "r_am", "r_pv", "m_postcode", "r_dt_searchbox")
                            r_amphure   = col_d.text_input("อำเภอ/เขต",    key="r_am")
                            r_province  = col_e.selectbox("จังหวัด", [""] + _PROVINCES, key="r_pv")
                            m_postcode  = st.text_input("รหัสไปรษณีย์", max_chars=5,
                                                        key="m_postcode", placeholder="เช่น 10400")
                            _postcode_suggest(m_postcode, "r_dt", "r_am", "r_pv",
                                              "r_dt_searchbox", "r_pc_suggest",
                                              stage_dt="_fr_dt", stage_am="_fr_am", stage_pv="_fr_pv")
                            if m_customer != "— เลือกลูกค้า —":
                                if st.button("💾 บันทึกที่อยู่นี้", key="save_addr_btn"):
                                    try:
                                        db.upsert_customer_address({
                                            "id":             str(uuid.uuid4()),
                                            "customer_id":    _cid,
                                            "recipient_name": r_name,
                                            "phone":          r_phone,
                                            "address_line":   r_addr_line,
                                            "district":       r_district,
                                            "amphure":        r_amphure,
                                            "province":       r_province,
                                            "postal_code":    m_postcode,
                                        })
                                        st.success("✅ บันทึกแล้ว — ค้นหาจากเบอร์ได้เลยครั้งถัดไป")
                                    except Exception as _sa_e:
                                        st.error(f"❌ บันทึกที่อยู่ไม่สำเร็จ: {_sa_e}")
                    else:
                        r_name = r_phone = r_addr_line = r_district = r_amphure = r_province = ""

                def _sum_row(label, value, big=False, accent=False):
                    _val_fs = "1.5rem" if big else "0.95rem"
                    _val_fw = 800 if big else 700
                    _val_color = "#E07B39" if accent else "#111111"
                    st.markdown(
                        f"<div style='display:flex;justify-content:space-between;align-items:baseline;"
                        f"margin:{'12px' if big else '6px'} 0 2px'>"
                        f"<span style='font-size:0.9rem;color:oklch(0.55 0 0)'>{label}</span>"
                        f"<span style='font-size:{_val_fs};font-weight:{_val_fw};color:{_val_color}'>{value}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                with _summary_col:
                    _summary_box = st.container(border=True)

                with _summary_box:
                    _sum_total = sum(float(p.get("price") or 0) * q for p, q, _ in valid_items)
                    _sum_pv    = sum(float(p.get("points_per_unit") or 0) * q for p, q, _ in valid_items)
                    st.markdown("**สรุปยอด**")
                    if valid_items:
                        st.caption("🛒 " + "  |  ".join(f"{p['id']} ×{q}" for p, q, _ in valid_items))

                    _sum_qty = sum(q for _, q, _ in valid_items)
                    _sum_row("ยอดรวมสินค้า", f"฿{_sum_total:,.0f}")
                    _sum_row("จำนวนสินค้า", f"{_sum_qty} ชิ้น")
                    if m_delivery != "ส่งพัสดุ":
                        st.divider()
                        _sum_row("💰 ยอดรวม", f"฿{_sum_total:,.0f}", big=True, accent=True)
                        _sum_row("⭐ PV รวม", f"{_sum_pv:,.0f}", accent=True)

                if not valid_items and _has_rx_action:
                    st.caption("ℹ️ มีแต่รับของเก่า ไม่ต้องเลือกสถานะจ่าย/สถานะบิล — ใช้ปุ่ม '💾 บันทึกรับของจากบิลเก่า' ด้านบนแทน")

                m_partial_amount = 0.0
                if m_pay == "จ่ายบางส่วน" and valid_items:
                    _partial_base_amt = sum(float(p["price"]) * q for p, q, _ in valid_items)
                    m_partial_amount = st.number_input(
                        "💵 จำนวนเงินที่ลูกค้าจ่ายมาแล้ว (บาท)",
                        min_value=0.0, max_value=float(_partial_base_amt), step=1.0,
                        key="m_partial_amount",
                        help=f"ยอดสินค้ารวม {_partial_base_amt:,.0f} ฿",
                    )

                m_cod     = (m_pay == "COD")
                m_receipt = "ฝากของ" if m_delivery == "ฝากของ" else "รับของแล้ว"
                m_postcode = ""
                m_zone     = "normal"
                m_carrier  = "Flash Express"
                f_sur = s_sur = 0
                f_zone = s_zone = ""

                if m_delivery == "ส่งพัสดุ":
                    if "_staged_pc" in st.session_state:
                        st.session_state["m_postcode"] = st.session_state.pop("_staged_pc")
                    m_postcode = st.session_state.get("m_postcode", "")



                    fees = carrier_fees(0, m_postcode.strip()) if len(m_postcode.strip()) == 5 else None
                    f_sur  = fees["Flash Express"]["surcharge"] if fees else 0
                    s_sur  = fees["SPX Express"]["surcharge"]   if fees else 0
                    f_zone = fees["Flash Express"]["zone"]      if fees else ""
                    s_zone = fees["SPX Express"]["zone"]        if fees else ""
                    if fees and m_postcode != st.session_state.get("_prev_pc", ""):
                        st.session_state["m_carrier"] = _pick_carrier(m_postcode)
                        st.session_state["_prev_pc"]  = m_postcode
                    if "_staged_carrier" in st.session_state:
                        st.session_state["m_carrier"] = st.session_state.pop("_staged_carrier")
                    m_carrier = st.session_state.get("m_carrier", "Flash Express")
                    m_iship_note = st.text_input("📝 หมายเหตุ iShip (ไม่บังคับ)", placeholder="เช่น ฝากสินค้าเพิ่ม...", key="m_iship_note")

                # auto-select carrier จาก weight + location (รันทุกครั้งที่ items หรือ postcode เปลี่ยน)
                if m_delivery == "ส่งพัสดุ" and len(m_postcode.strip()) == 5:
                    _w_kg = (raw_weight_g(valid_items, _rx_extra_weight_g) + BOX_WEIGHT_G) / 1000
                    _optimal = _pick_carrier(m_postcode.strip(), _w_kg)
                    _sig = (m_postcode.strip(), round(_w_kg, 2))
                    if _sig != st.session_state.get("_carrier_sig"):
                        st.session_state["_carrier_sig"]    = _sig
                        st.session_state["_staged_carrier"] = _optimal
                        st.rerun()

                COD_FEE_RATE = 0.0321  # 3.21%

                if m_delivery == "ส่งพัสดุ" and (f_zone or s_zone):
                    _zone_label = f_zone or s_zone
                    st.warning(f"📍 {_zone_label} — มีค่าส่งเพิ่ม Flash Express +{f_sur}฿ / SPX Express +{s_sur}฿")

                total_amt = 0.0; total_pv = 0.0; ship_fee = 0.0; cod_fee = 0.0; collect = 0.0
                if valid_items or (_has_rx_action and m_delivery == "ส่งพัสดุ"):
                    total_amt    = sum(float(p["price"]) * q for p, q, _ in valid_items)
                    total_pv     = sum(float(p["points_per_unit"]) * q for p, q, _ in valid_items)
                    _raw_weight  = raw_weight_g(valid_items, _rx_extra_weight_g)
                    total_weight = _raw_weight + BOX_WEIGHT_G  # สำหรับแสดงผลเท่านั้น
                    if _rx_old_items and valid_items:
                        _old_label = "  +  ".join(f"{it['name']} ×{it['qty']}" for it in _rx_old_items)
                        st.info(f"📦 ของเก่า: {_old_label}  ·  ยอดค้างที่จะจ่าย **{_rx_total_pay:,.0f}฿**  ·  รวมยอดทั้งหมด **{total_amt + _rx_total_pay:,.0f}฿**")
                    if m_delivery == "ส่งพัสดุ":
                        fees_all  = carrier_fees(_raw_weight, m_postcode)
                        ship_fee  = fees_all[m_carrier]["total"] if m_postcode else calc_shipping(_raw_weight, m_postcode)
                        _base     = total_amt + ship_fee
                        cod_fee   = round(_base * COD_FEE_RATE, 2) if m_cod else 0
                        collect   = _base + cod_fee if m_cod else _base
                        net_recv  = _base
                        _amt_label = f"ยอดสินค้า (ใหม่ {total_amt:,.0f} + เก่า {_rx_total_pay:,.0f})" if _rx_total_pay > 0.01 else "ยอดสินค้า"
                        _grand_amt = total_amt + _rx_total_pay
                        _ship_surcharge = fees_all[m_carrier]["surcharge"] if m_postcode else 0
                        with _summary_box:
                            st.divider()
                            _sum_row(_amt_label, f"฿{_grand_amt:,.0f}")
                            _sum_row("🚚 ค่าส่ง", f"฿{ship_fee:,.0f}")
                            if _ship_surcharge > 0:
                                _sum_row("📍 พื้นที่ห่างไกล", f"฿{_ship_surcharge:,.0f}")
                            _sum_row("⚖️ น้ำหนัก", f"{(total_weight/1000):.2f} kg")
                        if m_cod:
                            with _summary_box:
                                _sum_row("💰 ยอดเก็บ (อัตโนมัติ)", f"฿{collect:,.0f}")
                                _sum_row("💸 ค่า COD", f"฿{cod_fee:,.2f}")
                            _cod_auto = int(ceil(collect))
                            _cod_custom = st.number_input(
                                "💰 ยอด COD ที่ต้องเก็บ (แก้ได้)",
                                min_value=0, value=_cod_auto, step=1,
                                key="m_cod_custom",
                                help="ค่า default = คำนวณอัตโนมัติ ปรับได้ถ้าต้องการเก็บยอดอื่น",
                            )
                            collect = float(_cod_custom)
                            with _summary_box:
                                st.divider()
                                _sum_row("✅ ได้รับจริง", f"฿{net_recv:,.2f}", big=True, accent=True)
                                _sum_row("⭐ PV รวม", f"{total_pv:,.0f}", accent=True)
                        else:
                            with _summary_box:
                                st.divider()
                                _sum_row("💰 ยอดรวม", f"฿{collect:,.0f}", big=True, accent=True)
                                _sum_row("⭐ PV รวม", f"{total_pv:,.0f}", accent=True)
                    else:
                        ship_fee = cod_fee = 0
                        collect  = total_amt
                        net_recv = total_amt

                if _rx_total_pay > 0:
                    _new_total_disp = total_amt + (ship_fee if m_delivery == "ส่งพัสดุ" else 0)
                    _ship_note = f" (รวมค่าส่ง {ship_fee:,.0f} ฿)" if (m_delivery == "ส่งพัสดุ" and ship_fee > 0) else ""
                    st.caption(
                        f"💰 ยอดรวมทั้งหมด (ส่งบิลลูกค้า): เก่า {_rx_total_pay:,.0f} ฿ "
                        f"+ ใหม่ {_new_total_disp:,.0f} ฿{_ship_note} = **{(_new_total_disp + _rx_total_pay):,.0f} ฿**"
                    )

                m_errors = []
                if m_customer == "— เลือกลูกค้า —": m_errors.append("⚠️ ยังไม่ได้เลือกลูกค้า")
                if not valid_items: m_errors.append("⚠️ ยังไม่ได้กรอกสินค้า")
                if m_pay == "จ่ายบางส่วน" and valid_items and m_partial_amount <= 0:
                    m_errors.append("⚠️ กรุณาระบุจำนวนเงินที่จ่ายมา (ต้องมากกว่า 0)")
                if m_delivery is None: m_errors.append("⚠️ ยังไม่ได้เลือก การรับของ")
                if valid_items:
                    if m_pay is None:  m_errors.append("⚠️ ยังไม่ได้เลือก การจ่าย")
                    if m_bill is None: m_errors.append("⚠️ ยังไม่ได้เลือก สถานะบิล")

                if m_errors:
                    st.markdown(
                        "<div style='color:oklch(0.5 0.14 50);font-size:0.95rem;line-height:1.9'>"
                        + "<br>".join(m_errors) + "</div>",
                        unsafe_allow_html=True,
                    )
                elif valid_items:
                    _pay_color   = {"ค้างจ่าย": "🔴", "จ่ายแล้ว": "🟢", "COD": "🟡", "จ่ายบางส่วน": "🟣"}.get(m_pay or "", "⚪")
                    _deliv_color = {"ส่งพัสดุ": "🚚", "ฝากของ": "📦", "รับแล้ว": "✅"}.get(m_delivery or "", "⚪")
                    _bill_color  = "🟠" if m_bill == "ยังไม่เปิดบิล" else "🟢"
                    _carrier_tag = f" · {m_carrier}" if m_delivery == "ส่งพัสดุ" else ""
                    _pay_tag     = f" · {_pay_color} {m_pay}" if m_pay else ""
                    _bill_tag    = f" · {_bill_color} {m_bill}" if m_bill else ""
                    st.markdown(
                        f"<div style='color:oklch(0.4 0.1 155);font-size:0.95rem'>"
                        f"📋 <b>{m_customer}</b> · {_deliv_color} {m_delivery}{_pay_tag}{_bill_tag}{_carrier_tag}</div>",
                        unsafe_allow_html=True,
                    )

                with _summary_box:
                    st.divider()
                    _submit_clicked = st.button("💾 บันทึกทั้งหมด", type="primary", use_container_width=True,
                                                 key="m_submit", disabled=bool(m_errors))

                if _submit_clicked:
                    customer     = customer_map[m_customer]
                    is_shipping  = m_delivery == "ส่งพัสดุ"
                    _raw_w_save  = raw_weight_g(valid_items, _rx_extra_weight_g)
                    total_w_g    = _raw_w_save + BOX_WEIGHT_G  # สำหรับแสดงผลเท่านั้น
                    if is_shipping:
                        fees_save = carrier_fees(_raw_w_save, m_postcode)
                        ship_fee  = fees_save[m_carrier]["total"]
                        zone_name = fees_save[m_carrier]["zone"]
                        zone_tag  = f"|{zone_name}" if zone_name else ""
                        delivery_tag = f"[ส่งพัสดุ|{m_carrier}|{m_postcode}|น้ำหนัก={total_w_g/1000:.2f}kg|ค่าส่ง={ship_fee:.0f}{zone_tag}]"
                    else:
                        ship_fee = 0
                        delivery_tag = ""
                    # ── บันทึกสินค้าใหม่ (ถ้ามี) ──────────────────────────────────
                    if valid_items:
                        actual_pay  = "COD" if m_cod else ("ค้างจ่าย" if m_pay == "จ่ายบางส่วน" else m_pay)
                        receive_now = m_receipt == "รับของแล้ว"
                        if m_cod:
                            _base_cod  = sum(float(p["price"]) * q for p, q, _ in valid_items) + ship_fee
                            cod_amount = round(_base_cod * COD_FEE_RATE, 2)
                            collect    = _base_cod + cod_amount
                            _cod_custom_val = st.session_state.get("m_cod_custom", 0)
                            if _cod_custom_val and int(_cod_custom_val) != int(ceil(collect)):
                                collect = float(_cod_custom_val)
                            cod_tag    = f"[COD|ยอดเก็บ={collect:.0f}฿|ค่าธรรมเนียม={cod_amount:.2f}฿|ยอดรับจริง={_base_cod:.2f}฿]"
                        else:
                            cod_amount = 0
                            collect    = total_amt + ship_fee
                            cod_tag    = ""
                        bill_no = db.get_next_bill_no(str(m_date))
                        _m_batch = [{
                            "id":                   str(uuid.uuid4()),
                            "date":                 str(m_date),
                            "customer_id":          customer["id"],
                            "product_id":           p["id"],
                            "product_name":         p["name"],
                            "qty":                  qty,
                            "price_per_unit":       float(p["price"]),
                            "points_per_unit":      float(p["points_per_unit"]),
                            "total_amount":         float(p["price"]) * qty,
                            "initial_qty_received": qty if receive_now else 0,
                            "transaction_type":     "เบิกของก่อน" if m_bill == "ยังไม่เปิดบิล" and receive_now else "ขายปกติ",
                            "bill_status":          m_bill,
                            "pay_status":           actual_pay,
                            "notes":                " ".join(filter(None, [delivery_tag, cod_tag, note])).strip(),
                            "bill_no":              bill_no,
                        } for p, qty, note in valid_items]
                        try:
                            db.insert_transactions_batch(_m_batch)
                        except Exception as _e:
                            st.error(f"❌ Error: {_e}")
                            st.json(_m_batch)
                            st.stop()
                        if m_pay == "จ่ายบางส่วน" and m_partial_amount > 0:
                            _alloc_left = m_partial_amount
                            _pe_rows, _paid_full_ids = [], []
                            for _i, _row in enumerate(_m_batch):
                                if _i == len(_m_batch) - 1:
                                    _alloc = round(_alloc_left, 2)
                                else:
                                    _alloc = round(m_partial_amount * _row["total_amount"] / total_amt, 2)
                                    _alloc_left -= _alloc
                                if _alloc > 0:
                                    _pe_rows.append({
                                        "id": str(uuid.uuid4()),
                                        "date": str(m_date),
                                        "transaction_id": _row["id"],
                                        "qty_received": 0,
                                        "amount_paid": _alloc,
                                        "event_type": "จ่ายเงิน",
                                    })
                                    if _alloc >= _row["total_amount"] - 0.01:
                                        _paid_full_ids.append(_row["id"])
                            db.insert_partial_events_batch(_pe_rows)
                            db.update_transaction_statuses_batch(_paid_full_ids, pay_status="จ่ายแล้ว")
                        msg = f"✅ บันทึก {len(valid_items)} รายการ"
                        if is_shipping: msg += f" | 🚚 ค่าส่ง {ship_fee:.0f} ฿"
                        if m_cod:       msg += f" | 💸 ค่า COD {cod_amount:.2f} ฿"
                        if m_pay == "จ่ายบางส่วน" and m_partial_amount > 0:
                            msg += f" | 💵 จ่ายมาแล้ว {m_partial_amount:,.0f} ฿ (ค้าง {total_amt - m_partial_amount:,.0f} ฿)"
                    else:
                        actual_pay = None
                        bill_no    = None
                        cod_amount = 0
                        collect    = ship_fee
                        msg        = "✅ ส่งของค้างเก่า"
                        if is_shipping: msg += f" | 🚚 ค่าส่ง {ship_fee:.0f} ฿"
                    # ── iShip + บันทึกรับของเก่า/จ่ายเงิน ─────────────────────────
                    if is_shipping and r_addr_line:
                        _old_ship_items = []
                        if _rx_df is not None and _rx_edit is not None:
                            _, _, _old_ship_items = _process_old_items_receipt(
                                _rx_edit, _rx_df, _rx_pay_map, _pending_rx,
                                event_date=str(m_date), collect_ship_items=True,
                            )
                        _new_items = [{"product_id": p["id"], "name": p["name"], "qty": qty}
                                      for p, qty, _ in valid_items]
                        _all_items = _new_items + _old_ship_items
                        _prod_codes  = " ".join(f"{p['id'].upper()}-{qty}" for p, qty, _ in valid_items)
                        _iship_args = {
                            "dst_name":    r_name or customer["name"],
                            "dst_phone":   r_phone,
                            "address_line": r_addr_line,
                            "district":    r_district,
                            "amphure":     r_amphure,
                            "province":    r_province,
                            "zipcode":     m_postcode,
                            "weight_kg":   total_w_g / 1000,
                            "cod_amount":  ceil(collect) if m_cod else 0,
                            "carrier":      m_carrier,
                            "remark":       " ".join(filter(None, [customer['name'], _prod_codes, st.session_state.get("m_iship_note","").strip()])),
                            "item_detail":  ", ".join(f"{it['name']} x{it['qty']}" for it in _all_items),
                            "products":     [{"name": it["name"], "qty": it["qty"],
                                              "price": float(next((p["price"] for p, q, _ in valid_items if p["id"] == it["product_id"]), 0))}
                                             for it in _all_items],
                            "sender_name":  customer["name"],
                            "_items":       _all_items,
                            "_customer_id": customer["id"],
                        }
                        if iship_api.is_configured():
                            st.session_state.pop("_cs_carrier_sel", None)
                            st.session_state["_iship_carrier_select"] = {
                                "tab":          "sale",
                                "postcode":     m_postcode,
                                "weight_kg":    total_w_g / 1000,
                                "dst_name":     r_name or customer["name"],
                                "dst_phone":    r_phone,
                                "address_line": r_addr_line,
                                "district":     r_district,
                                "amphure":      r_amphure,
                                "province":     r_province,
                                "cod_amount":   ceil(collect) if m_cod else 0,
                                "items":        _all_items,
                                "customer_id":  customer["id"],
                                "customer_name":customer["name"],
                                "shipment_id":  "",
                                "remark":       "",
                            }
                            pass  # _iship_carrier_select set above — dialog triggers automatically
                    elif not is_shipping and _rx_df is not None and _rx_edit is not None:
                        # บันทึกรับของเก่า สำหรับ รับแล้ว / ฝากของ (จ่ายอัตโนมัติตามสัดส่วน)
                        _process_old_items_receipt(
                            _rx_edit, _rx_df, _rx_pay_map, _pending_rx,
                            event_date=str(m_date),
                        )
                    # ── print popup (เฉพาะเมื่อมีสินค้าใหม่) ──────────────────────
                    if valid_items:
                        st.session_state["_print_popup"] = {
                            "customer_name": customer["name"],
                            "customer_id":   customer["id"],
                            "bill_date":     str(m_date),
                            "bill_no":       bill_no,
                            "items": [{"product_id": p["id"], "name": p["name"], "qty": qty,
                                       "price": float(p["price"]),
                                       "total": float(p["price"]) * qty,
                                       "pv":    float(p["points_per_unit"]) * qty}
                                      for p, qty, _ in valid_items],
                            "ship_fee":    ship_fee,
                            "carrier":     m_carrier if is_shipping else "",
                            "is_cod":      m_cod,
                            "cod_fee":     cod_amount if m_cod else 0,
                            "collect":     ceil(collect) if m_cod else (total_amt + (ship_fee if is_shipping else 0)),
                            "total_amt":   total_amt,
                            "total_pv":    total_pv,
                            "bill_status": m_bill,
                            "pay_status":  actual_pay,
                            "old_items":   _rx_old_items,
                            "old_total":   _rx_total_pay,
                            "grand_total": total_amt + _rx_total_pay,
                        }
                    # ล้างฟอร์มสำหรับลูกค้าถัดไป
                    for _k in _sale_keys:
                        st.session_state.pop(_k, None)
                    st.session_state.pop(_cart_key, None)
                    st.session_state["_cart_version"] = _cart_ver + 1
                    st.rerun()

                # ── ปุ่มรับแต่ของเก่า (เฉพาะ ส่งพัสดุ + ไม่มีสินค้าใหม่) ────────
                if (m_delivery == "ส่งพัสดุ" and not valid_items and _has_rx_action
                        and m_customer != "— เลือกลูกค้า —"):
                    st.divider()
                    _rxo_errors = []
                    if not r_addr_line: _rxo_errors.append("⚠️ ยังไม่ได้กรอกที่อยู่")
                    if not m_postcode:  _rxo_errors.append("⚠️ ยังไม่ได้กรอกรหัสไปรษณีย์")
                    if _rxo_errors:
                        st.warning("  \n".join(_rxo_errors))
                    if st.button("🚚 รับแต่ของเก่า", type="primary", use_container_width=True,
                                 key="m_rxonly_submit", disabled=bool(_rxo_errors)):
                        _rxo_customer   = customer_map[m_customer]
                        _rxo_weight_g   = _rx_extra_weight_g + BOX_WEIGHT_G  # สำหรับแสดงผลเท่านั้น
                        _rxo_fees       = carrier_fees(_rx_extra_weight_g, m_postcode)
                        _rxo_ship_fee   = _rxo_fees[m_carrier]["total"]
                        _rxo_zone       = _rxo_fees[m_carrier]["zone"]
                        _rxo_zone_tag   = f"|{_rxo_zone}" if _rxo_zone else ""
                        _, _, _rxo_items = _process_old_items_receipt(
                            _rx_edit, _rx_df, _rx_pay_map, _pending_rx,
                            event_date=str(m_date), collect_ship_items=True,
                        )
                        if iship_api.is_configured() and _rxo_items:
                            st.session_state.pop("_cs_carrier_sel", None)
                            st.session_state["_iship_carrier_select"] = {
                                "tab":          "sale",
                                "postcode":     m_postcode,
                                "weight_kg":    _rxo_weight_g / 1000,
                                "dst_name":     r_name or _rxo_customer["name"],
                                "dst_phone":    r_phone,
                                "address_line": r_addr_line,
                                "district":     r_district,
                                "amphure":      r_amphure,
                                "province":     r_province,
                                "cod_amount":   0,
                                "items":        _rxo_items,
                                "customer_id":  _rxo_customer["id"],
                                "customer_name":_rxo_customer["name"],
                                "shipment_id":  "",
                                "remark":       f"[ส่งพัสดุ|{m_carrier}|{m_postcode}|น้ำหนัก={_rxo_weight_g/1000:.2f}kg|ค่าส่ง={_rxo_ship_fee:.0f}{_rxo_zone_tag}]",
                            }
                        st.rerun()

                # ── ผลลัพธ์หลังบันทึก (popup + iShip) ─────────────────────────
                if st.session_state.get("_print_popup"):
                    _pd = st.session_state["_print_popup"]
                    _old_items  = _pd.get("old_items", [])
                    _old_total  = _pd.get("old_total", 0)
                    _grand = _pd.get("collect", _pd["total_amt"]) + _old_total
                    _items_txt = ", ".join(f"{it['product_id']} {it['name']} ×{it['qty']}" for it in _pd.get("items", []))
                    if _old_items:
                        _items_txt += "  ·  เก่า: " + ", ".join(f"{it['product_id']} {it['name']} ×{it['qty']}" for it in _old_items)
                    with st.container(border=True):
                        _pb1, _pb2, _pb3, _pb4, _pb5 = st.columns([4, 3, 1, 1, 1])
                        _pb1.markdown(
                            f"✅ **{_pd['customer_name']}** — บิล `{_pd['bill_no']}` | {_pd['bill_date']}"
                            f"\n\n_{_items_txt}_"
                        )
                        if _old_items:
                            _pb2.markdown(
                                f"💰 เก่า {_old_total:,.0f} + ใหม่ {_pd['total_amt']:,.0f} = **{_grand:,.0f} ฿**"
                                f" &nbsp;&nbsp; ⭐ PV {_pd['total_pv']:.0f}"
                            )
                        else:
                            _pb2.markdown(
                                f"💰 **{_grand:,.0f} ฿** &nbsp;&nbsp; ⭐ PV {_pd['total_pv']:.0f}"
                            )
                        _popup_line_uid, _popup_gid = db.get_customer_line_ids(_pd.get("customer_id", "")) if _pd.get("customer_id") else ("", "")
                        if _pb3.button("📨 LINE", key="popup_line_btn",
                                       disabled=not bool(_popup_line_uid or _popup_gid),
                                       use_container_width=True,
                                       help="ส่งสรุปบิลให้ลูกค้าใน LINE" if (_popup_line_uid or _popup_gid) else "ลูกค้าไม่มี LINE ID"):
                            _line_items = [{"name": f"{it['product_id']} {it['name']}", "qty": it["qty"], "total": it["total"]}
                                           for it in _pd.get("items", [])]
                            _line_items += [{"name": f"{it['product_id']} {it['name']} (เก่า)", "qty": it["qty"], "total": it["amount"]}
                                            for it in _old_items]
                            _pb_total = _pd["total_amt"] + _old_total
                            _pb_paid  = _pb_total if _pd["pay_status"] in ("จ่ายแล้ว", "COD จ่ายแล้ว") else 0.0
                            _res = line_api.push_bill_summary(
                                _popup_line_uid, _pd["customer_name"], _pd["bill_no"],
                                _line_items, _pb_total, _pd["pay_status"],
                                paid_amount=_pb_paid, outstanding_amount=_pb_total - _pb_paid,
                                group_id=_popup_gid,
                            )
                            if _res["ok"]:
                                st.toast("✅ ส่ง LINE แล้ว")
                            else:
                                st.error(f"LINE error: {_res['error']}")
                        if _pb4.button("🖨️ พิมพ์", key="popup_print_btn", use_container_width=True):
                            st.session_state["_popup_show_print"] = not st.session_state.get("_popup_show_print", False)
                        if _pb5.button("✕ ปิด", key="popup_close", use_container_width=True):
                            del st.session_state["_print_popup"]
                            st.session_state.pop("_popup_show_print", None)
                            st.rerun()

                    if st.session_state.get("_popup_show_print") and st.session_state.get("_print_popup"):
                        _pit = _pd.get("items", [])
                        _rows_html = "".join(
                            f"<tr><td><b>{it.get('product_id','')}</b></td>"
                            f"<td>{it['name']}</td><td style='text-align:center'><b>{it['qty']}</b></td>"
                            f"<td style='text-align:right'>{float(it['price']):,.0f}</td>"
                            f"<td style='text-align:right'><b>{float(it['total']):,.0f}</b></td></tr>"
                            for it in _pit
                        )
                        _old_rows_html = "".join(
                            f"<tr><td><b>{it['product_id']}</b></td>"
                            f"<td>{it['name']} (เก่า)</td><td style='text-align:center'><b>{it['qty']}</b></td>"
                            f"<td style='text-align:right'>{(float(it['amount'])/it['qty'] if it['qty'] else 0):,.0f}</td>"
                            f"<td style='text-align:right'><b>{float(it['amount']):,.0f}</b></td></tr>"
                            for it in _old_items
                        )
                        _ship_row = f"<tr><td></td><td>ค่าส่ง ({_pd.get('carrier','')})</td><td></td><td></td><td style='text-align:right'>{_pd['ship_fee']:,.0f}</td></tr>" if _pd.get("ship_fee", 0) > 0 else ""
                        _cod_row  = f"<tr><td></td><td>COD (3%)</td><td></td><td></td><td style='text-align:right'>{_pd['cod_fee']:,.0f}</td></tr>" if _pd.get("is_cod") else ""
                        _new_bill_total = _pd.get("collect", _pd["total_amt"])
                        if _old_total:
                            _total_html = (
                                f"<div class='subtotal'>ยอดบิลนี้ (ใหม่): {_new_bill_total:,.0f} ฿ "
                                f"&nbsp;|&nbsp; ยอดเก่า: {_old_total:,.0f} ฿</div>"
                                f"<div class='total'>ยอดรวมทั้งหมด: {_grand:,.0f} ฿</div>"
                                f"<div class='subtotal'>PV: {_pd['total_pv']:.0f}</div>"
                            )
                        else:
                            _total_html = f"<div class='total'>ยอดรวม: {_grand:,.0f} ฿ &nbsp;|&nbsp; PV: {_pd['total_pv']:.0f}</div>"
                        _bill_html_popup = f"""<!DOCTYPE html><html><head><meta charset='UTF-8'>
    <style>
    html,body{{background:#fff!important;color:#000!important;margin:0;padding:0}}
    body{{font-family:'Prompt',sans-serif;padding:20px;font-size:15px}}
    h3{{margin:0 0 6px;font-size:20px}}
    .info{{font-size:14px;margin-bottom:10px;color:#222}}
    table{{width:100%;border-collapse:collapse;margin:8px 0;font-size:14px}}
    th{{background:#333;color:#fff;padding:6px 8px;text-align:left;font-size:14px}}
    td{{padding:5px 8px;border-bottom:1px solid #ccc;color:#000}}
    .subtotal{{font-size:13px;color:#444;text-align:right;margin-top:6px}}
    .total{{font-weight:bold;font-size:24px;text-align:right;margin-top:4px}}
    .btn{{display:inline-block;margin:0 0 12px;padding:7px 20px;background:#333;color:#fff;border:none;cursor:pointer;border-radius:4px;font-size:14px}}
    @media print{{.btn{{display:none}}@page{{size:A5;margin:10mm}}}}
    </style></head><body style="background:#fff;color:#000">
    <button class='btn' onclick='window.print()'>🖨️ พิมพ์บิล</button>
    <h3>TBY — ใบเสร็จรับเงิน</h3>
    <div class='info'>บิล: <b>{_pd['bill_no']}</b> | วันที่: {_pd['bill_date']}<br>
    ลูกค้า: <b>{_pd['customer_name']}</b> | สถานะ: {_pd['pay_status']}</div>
    <table><tr><th>รหัส</th><th>สินค้า</th><th>จำนวน</th><th>ราคา/ชิ้น</th><th>รวม</th></tr>
    {_rows_html}{_old_rows_html}{_ship_row}{_cod_row}
    </table>
    {_total_html}
    </body></html>"""
                        components.html(_bill_html_popup, height=420, scrolling=True)

                if st.session_state.get("_sale_last_tracking"):
                    _slt = st.session_state["_sale_last_tracking"]
                    _stc1, _stc2 = st.columns([5, 1])
                    _stc1.success(f"✅ iShip สำเร็จ — Tracking: **{_slt}**")
                    if _stc2.button("✕", key="sale_clear_tracking", use_container_width=True):
                        del st.session_state["_sale_last_tracking"]
                        st.rerun()

                if st.session_state.get("_iship_pending"):
                    _p = st.session_state["_iship_pending"]
                    addr_full = f"{_p['address_line']} {_p['district']} {_p['amphure']} {_p['province']} {_p['zipcode']}".strip()
                    _sender_name = _p.get("sender_name", "")
                    if _p.get("_auto_error"):
                        st.error(f"❌ iShip ล้มเหลว: {_p['_auto_error']} — กรุณาลองใหม่")
                    st.info(
                        f"{'👤 ลูกค้า: **' + _sender_name + '**  →  ' if _sender_name else ''}"
                        f"📦 **{_p['dst_name']}**  {_p['dst_phone']}\n\n"
                        f"{addr_full}\n\n"
                        f"น้ำหนัก {_p['weight_kg']:.2f} kg  |  COD {_p['cod_amount']:,} ฿"
                    )
                    _carrier_choice = st.radio("ขนส่ง", ["Flash Express", "SPX Express"],
                                               index=0 if _p["carrier"] == "Flash Express" else 1,
                                               horizontal=True, key="iship_carrier_pick")
                    _p["carrier"] = _carrier_choice
                    col_s1, col_s2 = st.columns([3, 1])
                    if col_s1.button("🚚 ส่ง iShip", type="primary", use_container_width=True, key="do_iship"):
                        if iship_api.is_configured():
                            _api_keys = {"dst_name","dst_phone","address_line","district",
                                         "amphure","province","zipcode","weight_kg",
                                         "cod_amount","carrier","remark","item_detail","products"}
                            _call = {k: v for k, v in _p.items() if k in _api_keys}
                            with st.spinner("กำลังสร้างรายการใน iShip..."):
                                resp = iship_api.create_order(**_call)
                            if resp.get("status"):
                                tracking = _extract_tracking(resp)
                                try:
                                    db.create_shipment({
                                        "customer_id":    _p.get("_customer_id") or None,
                                        "recipient_name": _p.get("dst_name",""),
                                        "phone":          _p.get("dst_phone",""),
                                        "address_line":   _p.get("address_line",""),
                                        "district":       _p.get("district",""),
                                        "amphure":        _p.get("amphure",""),
                                        "province":       _p.get("province",""),
                                        "postal_code":    _p.get("zipcode",""),
                                        "carrier":        _p.get("carrier",""),
                                        "items":          _p.get("_items",[]),
                                        "tracking_no":    tracking,
                                        "cod_amount":     _p.get("cod_amount", 0),
                                        "notes":          "",
                                        "source":         "sale",
                                    })
                                except Exception as _cs2_e:
                                    st.warning(f"⚠️ ส่ง iShip สำเร็จ (tracking {tracking}) แต่บันทึกประวัติการส่งไม่สำเร็จ: {_cs2_e}")
                                _cid_s2 = _p.get("_customer_id", "")
                                _luid_s2, _gid_s2 = db.get_customer_line_ids(_cid_s2) if (tracking and _cid_s2) else ("", "")
                                del st.session_state["_iship_pending"]
                                st.session_state["_iship_success_info"] = _build_success_info(
                                    tracking=tracking, tab="sale",
                                    customer=_p.get("sender_name",""),
                                    dst_name=_p.get("dst_name",""),
                                    dst_phone=_p.get("dst_phone",""),
                                    address=addr_full,
                                    carrier=_carrier_choice,
                                    weight_kg=_p.get("weight_kg",0),
                                    cod_amount=_p.get("cod_amount",0),
                                    items=_p.get("_items",[]),
                                    line_user_id=_luid_s2,
                                    shipment_id="",
                                    group_id=_gid_s2,
                                )
                                # dialog จะเปิดอัตโนมัติจาก _iship_success_info
                                st.rerun()
                            else:
                                _err_msg = resp.get("message") or resp.get("msg") or str(resp)
                                if "NotSupportAddress" in _err_msg:
                                    st.error("❌ ที่อยู่ไม่ถูกต้อง — ตำบล / อำเภอ / จังหวัด ต้องตรงกับฐานข้อมูล iShip")
                                    with st.expander("🔍 ดู response จาก iShip"):
                                        st.json(resp)
                                        st.write("ที่ส่งไป →", {
                                            "district": _call.get("district"),
                                            "amphure":  _call.get("amphure"),
                                            "province": _call.get("province"),
                                            "zipcode":  _call.get("zipcode"),
                                        })
                                else:
                                    st.error(f"❌ iShip Error: {_err_msg}")
                                    with st.expander("🔍 raw response"):
                                        st.json(resp)
                        else:
                            st.warning("⚙️ ยังไม่ได้ตั้งค่า ISHIP_TOKEN ใน secrets")
                    if col_s2.button("ปิด", key="cancel_iship", use_container_width=True):
                        del st.session_state["_iship_pending"]
                        st.rerun()

        # ─────────────────────────────────────────────────────────────────────────────

        elif _sub_active == "📦 ส่งของ":
            _sp_av   = st.session_state.get("_sp_addr_ver", 0)
            _sp_keys = [f"sp_rname_v{_sp_av}",f"sp_rphone_v{_sp_av}",f"sp_al_v{_sp_av}",
                        f"sp_dt_v{_sp_av}",f"sp_am_v{_sp_av}",f"sp_pv_v{_sp_av}",
                        f"sp_dt_searchbox_v{_sp_av}",f"_sp_dt_searchbox_v{_sp_av}_sig",
                        f"sp_pc_v{_sp_av}",f"sp_track_v{_sp_av}",f"sp_notes_v{_sp_av}",
                        "_sp_cust_picked",f"sp_cust_search_v{_sp_av}",
                        "_sp_last_dt","_sp_last_pc","_fsp_dt","_fsp_am","_fsp_pv","_fsp_pc",
                        "_fsp_rname","_fsp_rphone","_fsp_al",
                        "_sp_prev_pc","sp_date",
                        "_sp_cart_ver","_sp_cart_base","_sp_quick_items","sp_q_text",
                        "_sp_last_rph_fill","_sp_parse_open",
                        "_sp_linked_bill_no","_sp_linked_bill_txns","sp_link_search",
                        "_sp_adding_cust","_sp_prev_cust_search"]
            _sp_cart_ver_now = st.session_state.get("_sp_cart_ver", 0)
            _sp_cart_key = f"sp_cart_{_sp_cart_ver_now}"

            _sc1, _sc2 = st.columns([6, 1])
            _sc1.subheader("บันทึกการส่งของ")
            if st.session_state.get("_do_clear_after_iship") == "ship":
                st.session_state.pop("_do_clear_after_iship", None)
                st.session_state.pop("_iship_carrier_select", None)
                st.session_state.pop("_iship_success_info", None)
                for _k in _sp_keys:
                    st.session_state.pop(_k, None)
                st.session_state["_sp_addr_ver"] = _sp_av + 1
                st.session_state.pop("_sp_last_tracking", None)
                st.session_state.pop(f"sp_cart_{_sp_cart_ver_now}", None)
                st.session_state["_sp_cart_ver"] = _sp_cart_ver_now + 1
                st.rerun()

            if _sc2.button("🗑️ ล้าง", key="sp_clear_form", use_container_width=True):
                for _k in _sp_keys:
                    st.session_state.pop(_k, None)
                st.session_state.pop("_sp_cart_base", None)
                st.session_state["_sp_addr_ver"] = _sp_av + 1
                st.session_state.pop(f"sp_cart_{_sp_cart_ver_now}", None)
                st.session_state["_sp_cart_ver"] = _sp_cart_ver_now + 1
                st.rerun()

            _sp = products
            _sc = customers
            _sc_map = {c["name"]: c for c in _sc}

            # ── เลือกลูกค้า + วันที่ ─────────────────────────────────────────
            _sp_c1, _sp_c2 = st.columns([3, 1])
            with _sp_c1:
                _sp_picked = st.session_state.get("_sp_cust_picked", "")
                if _sp_picked:
                    _spx, _spy = st.columns([5, 1])
                    _spx.success(f"👤 **{_sp_picked}**")
                    if _spy.button("✕ เปลี่ยน", key="sp_cust_clear"):
                        st.session_state.pop("_sp_cust_picked", None)
                        st.session_state.pop("sp_cust_search", None)
                        st.rerun()
                    _sp_cust = _sp_picked
                else:
                    _sp_options = ["— เลือกลูกค้า —"] + sorted(_sc_map.keys(), key=str.casefold)
                    _sp_sel = st.selectbox("ลูกค้า", _sp_options, key=f"sp_cust_search_v{_sp_av}")
                    _sp_cust = "— เลือกลูกค้า —"
                    if _sp_sel != "— เลือกลูกค้า —":
                        st.session_state["_sp_cust_picked"] = _sp_sel
                        st.rerun()
                    _quick_add_customer("sp_")
            _sp_date = _sp_c2.date_input("วันที่", value=date.today(), key="sp_date")
            _sp_cid  = _sc_map[_sp_cust]["id"] if _sp_cust != "— เลือกลูกค้า —" else ""

            # ── เพิ่มสินค้า (แสดงตลอด ไม่ซ่อนใน expander) ──────────────────
            _sp_qtext_ver = st.session_state.get("_sp_qtext_ver", 0)
            _sp_qtext_key = f"sp_q_text_{_sp_qtext_ver}"
            _sp_add_box = st.container(border=True)
            _sp_add_box.markdown("**เพิ่มสินค้า**")
            _sqc1, _sqc2 = _sp_add_box.columns([4, 1])
            _sp_q_text = _sqc1.text_input(
                "รหัสสินค้า",
                placeholder="พิมพ์รหัสสินค้า (เต็มหรือบางส่วนก็ได้) เช่น tf2581 — Enter เพื่อเพิ่มเลย",
                key=_sp_qtext_key, label_visibility="collapsed",
            )
            _sp_q_submit = _sqc2.button("📋 เพิ่ม", key=f"sp_q_to_cart_{_sp_qtext_ver}", type="primary", use_container_width=True)
            if _sp_q_submit or _sp_q_text.strip():
                _sp_qf, _sp_qu = _parse_quick_order(_sp_q_text or "", _sp)
                if _sp_qf:
                    _cart_add_items(_sp_cart_key, _sp_qf)
                    st.session_state["_sp_qtext_ver"] = _sp_qtext_ver + 1
                    st.rerun()
                elif _sp_qu:
                    st.error(f"❌ ไม่พบ/ไม่ชัดเจน: {', '.join(_sp_qu)}")

            st.divider()

            # ── รายการสินค้าที่ส่ง (ไม่ตัด stock) ───────────────────────────
            _sp_valid_items = _render_cart_card(_sp_cart_key, _sp, title="รายการที่ส่ง")
            _sp_items = [
                {"product_id": p["id"], "name": p["name"], "qty": qty}
                for p, qty, _ in _sp_valid_items
            ]
            _sp_raw_weight   = raw_weight_g(_sp_valid_items)
            _sp_total_weight = _sp_raw_weight + BOX_WEIGHT_G  # สำหรับแสดงผลเท่านั้น
            _sp_total_amt = sum(float(p.get("price") or 0) * qty for p, qty, _ in _sp_valid_items)

            # ── ที่อยู่เดิม (collapsed) ───────────────────────────────────────
            if _sp_cid:
                try:
                    _sp_saved = db.get_customer_addresses(customer_id=_sp_cid)
                except Exception as _sp_load_e:
                    _sp_saved = []
                    st.caption(f"⚠️ โหลดที่อยู่เดิมไม่สำเร็จ: {_sp_load_e}")
                if _sp_saved:
                    with st.expander(f"⚡ ที่อยู่เดิม ({len(_sp_saved)} รายการ)", expanded=False):
                        for _sa in _sp_saved:
                            _lbl = f"📍 {_sa.get('recipient_name','')}  {_sa.get('phone','')}  {_sa.get('address_line','')} {_sa.get('district','')} {_sa.get('amphure','')} {_sa.get('province','')} {_sa.get('postal_code','')}"
                            if st.button(_lbl, key=f"qa_ship_{_sa['id']}", use_container_width=False):
                                _sa_dt = (_sa.get("district", "") or "").strip()
                                _sa_pc = (_sa.get("postal_code", "") or "").strip()
                                st.session_state["_fsp_rname"] = _sa.get("recipient_name", "")
                                st.session_state["_fsp_rphone"]= _sa.get("phone", "")
                                st.session_state["_fsp_al"]   = _sa.get("address_line", "")
                                st.session_state["_fsp_dt"]   = _sa_dt
                                st.session_state["_fsp_am"]   = _sa.get("amphure", "")
                                st.session_state["_fsp_pv"]   = _sa.get("province", "")
                                st.session_state["_fsp_pc"]   = _sa_pc
                                st.session_state["_sp_last_dt"] = _sa_dt
                                st.session_state["_sp_last_pc"] = _sa_pc
                                st.rerun()

            # ── ที่อยู่ผู้รับ ─────────────────────────────────────────────────
            with st.expander("📦 ที่อยู่ผู้รับ", expanded=True):
                # paste-parse จาก LINE format
                _sp_parse_key = "_sp_parse_open"
                if st.button("📍 แยกที่อยู่อัตโนมัติ", key="sp_parse_open_btn"):
                    st.session_state[_sp_parse_key] = not st.session_state.get(_sp_parse_key, False)
                if st.session_state.get(_sp_parse_key):
                    _sp_paste = st.text_area("วางที่อยู่จาก LINE (iShip format)", key="sp_paste_addr",
                                              height=100,
                                              placeholder="Boo Mee\nสวนหลวง/ Suan Luang,\nกรุงเทพมหานคร/ Bangkok,\n10250  14 Rama IX Soi 41\n0617490976")
                    _spc1, _spc2 = st.columns([1, 1])
                    if _spc1.button("✅ ตกลง", key="sp_parse_btn", type="primary"):
                        _sp_parsed = _parse_iship_address(_sp_paste)
                        st.session_state["_fsp_rname"] = _sp_parsed.get("dst_name", "")
                        st.session_state["_fsp_rphone"]= _sp_parsed.get("dst_phone", "")
                        st.session_state["_fsp_al"]   = _sp_parsed.get("address_line", "")
                        st.session_state["_fsp_dt"]   = _sp_parsed.get("district", "")
                        st.session_state["_fsp_am"]   = _sp_parsed.get("amphure", "")
                        st.session_state["_fsp_pv"]   = _sp_parsed.get("province", "")
                        st.session_state["_fsp_pc"]   = _sp_parsed.get("zipcode", "")
                        if _sp_parsed.get("district"):  st.session_state["_sp_last_dt"] = _sp_parsed["district"]
                        if _sp_parsed.get("zipcode"):   st.session_state["_sp_last_pc"] = _sp_parsed["zipcode"]
                        st.session_state[_sp_parse_key] = False
                        st.rerun()
                    if _spc2.button("ยกเลิก", key="sp_parse_cancel"):
                        st.session_state[_sp_parse_key] = False
                        st.rerun()
                st.divider()

                # apply staged address fill ก่อน render widgets
                for _fk, _wk in [("_fsp_rname",f"sp_rname_v{_sp_av}"),("_fsp_rphone",f"sp_rphone_v{_sp_av}"),
                                  ("_fsp_al",f"sp_al_v{_sp_av}"),
                                  ("_fsp_dt",f"sp_dt_v{_sp_av}"),("_fsp_am",f"sp_am_v{_sp_av}"),
                                  ("_fsp_pv",f"sp_pv_v{_sp_av}"),("_fsp_pc",f"sp_pc_v{_sp_av}")]:
                    if _fk in st.session_state:
                        st.session_state[_wk] = st.session_state.pop(_fk)

                # phone lookup อัตโนมัติ
                _sp_cur_rph = st.session_state.get(f"sp_rphone_v{_sp_av}", "")
                if len(_sp_cur_rph.strip()) == 10 and st.session_state.get("_sp_last_rph_fill") != _sp_cur_rph.strip():
                    try:
                        _sp_rph_addr = db.get_address_by_phone(_sp_cur_rph.strip())
                    except Exception:
                        _sp_rph_addr = None
                    st.session_state["_sp_last_rph_fill"] = _sp_cur_rph.strip()
                    if _sp_rph_addr:
                        for _k, _v in [(f"sp_rname_v{_sp_av}", _sp_rph_addr.get("recipient_name") or ""),
                                       (f"sp_al_v{_sp_av}",    _sp_rph_addr.get("address_line") or ""),
                                       (f"sp_dt_v{_sp_av}",    _sp_rph_addr.get("district") or ""),
                                       (f"sp_am_v{_sp_av}",    _sp_rph_addr.get("amphure") or ""),
                                       (f"sp_pv_v{_sp_av}",    _sp_rph_addr.get("province") or "")]:
                            if _v: st.session_state[_k] = _v
                        if _sp_rph_addr.get("postal_code"):
                            _sp_rph_pc = _sp_rph_addr["postal_code"]
                            st.session_state[f"sp_pc_v{_sp_av}"] = _sp_rph_pc
                            st.session_state["_sp_last_pc"] = _sp_rph_pc
                        _sp_rph_cust = (_sp_rph_addr.get("customers") or {}).get("name", "")
                        if _sp_rph_cust and not st.session_state.get("_sp_cust_picked"):
                            st.session_state["_sp_cust_picked"] = _sp_rph_cust
                        st.rerun()

                _sa1, _sa2 = st.columns(2)
                _sp_rname  = _sa1.text_input("ชื่อผู้รับ",    key=f"sp_rname_v{_sp_av}")
                _sp_rphone = _sa2.text_input("เบอร์โทร",      key=f"sp_rphone_v{_sp_av}")
                _warn_duplicate_phone(_sp_rphone, _sp_cid)
                _sp_al     = st.text_input("บ้านเลขที่/ถนน",  key=f"sp_al_v{_sp_av}")
                _sb1, _sb2, _sb3 = st.columns(3)
                with _sb1:
                    _sp_dt = _tambon_selectbox(f"sp_dt_v{_sp_av}", f"sp_am_v{_sp_av}", f"sp_pv_v{_sp_av}",
                                                f"sp_pc_v{_sp_av}", f"sp_dt_searchbox_v{_sp_av}")
                _sp_am = _sb2.text_input("อำเภอ/เขต",   key=f"sp_am_v{_sp_av}")
                _sp_pv = _sb3.selectbox("จังหวัด", [""] + _PROVINCES, key=f"sp_pv_v{_sp_av}")
                _sp_pc = st.text_input("รหัสไปรษณีย์", max_chars=5, key=f"sp_pc_v{_sp_av}", placeholder="เช่น 10400")
                _postcode_suggest(_sp_pc, f"sp_dt_v{_sp_av}", f"sp_am_v{_sp_av}", f"sp_pv_v{_sp_av}",
                                  f"sp_dt_searchbox_v{_sp_av}", f"sp_pc_suggest_v{_sp_av}",
                                  stage_dt="_fsp_dt", stage_am="_fsp_am", stage_pv="_fsp_pv")
                if _sp_cid and st.button("💾 บันทึกที่อยู่นี้", key="sp_save_addr"):
                    db.upsert_customer_address({
                        "id":             str(uuid.uuid4()),
                        "customer_id":    _sp_cid,
                        "recipient_name": _sp_rname,
                        "phone":          _sp_rphone,
                        "address_line":   _sp_al,
                        "district":       _sp_dt,
                        "amphure":        _sp_am,
                        "province":       _sp_pv,
                        "postal_code":    _sp_pc,
                    })
                    st.success("✅ บันทึกที่อยู่แล้ว")

            # ── ค่าส่ง + metrics ─────────────────────────────────────────────
            _sp_fc1, _sp_fc2 = st.columns(2)
            _sp_fees = carrier_fees(_sp_raw_weight, _sp_pc.strip()) if len((_sp_pc or "").strip()) == 5 else None
            if _sp_fees:
                _sp_fc1.caption(f"Flash: {_sp_fees['Flash Express']['zone'] or 'ปกติ'} | +{_sp_fees['Flash Express']['surcharge']} ฿")
                _sp_fc2.caption(f"SPX:   {_sp_fees['SPX Express']['zone']   or 'ปกติ'} | +{_sp_fees['SPX Express']['surcharge']} ฿")
                _sp_f_tot = _sp_fees["Flash Express"]["total"]
                _sp_s_tot = _sp_fees["SPX Express"]["total"]
                if _sp_f_tot < _sp_s_tot:
                    _sp_carrier = "Flash Express"
                elif _sp_s_tot < _sp_f_tot:
                    _sp_carrier = "SPX Express"
                else:
                    _sp_carrier = _pick_carrier(_sp_pc.strip(), round(_sp_total_weight / 1000, 2))
            else:
                _sp_carrier = "Flash Express"
            _sp_cost = _sp_fees[_sp_carrier]["total"] if _sp_fees else 0
            if _sp_items:
                _sm1, _sm2, _sm3 = st.columns(3)
                _sm1.metric(f"🚚 {_sp_carrier}", f"{_sp_cost} ฿")
                _sm2.metric("⚖️ น้ำหนัก", f"{(_sp_total_weight/1000):.2f} kg")
                _sm3.metric("📦 รายการ", f"{len(_sp_items)} สินค้า")
                if _sp_total_amt > 0:
                    _sm4, _sm5 = st.columns(2)
                    _sm4.metric("💵 ยอดสินค้า", f"{_sp_total_amt:,.0f} ฿")
                    _sm5.metric("💰 ยอดรวม (รวมค่าส่ง)", f"{(_sp_total_amt + _sp_cost):,.0f} ฿")

            # ── tracking + หมายเหตุ ───────────────────────────────────────────
            _sp_track = st.text_input("เลข tracking (กรอกทีหลังได้)", key=f"sp_track_v{_sp_av}", placeholder="TH123456789")
            _sp_notes = st.text_input("หมายเหตุ", key=f"sp_notes_v{_sp_av}")
            _sp_iship_note = st.text_input("📝 หมายเหตุ iShip (ไม่บังคับ)", placeholder="เช่น ฝากสินค้าเพิ่ม...", key=f"sp_iship_note_v{_sp_av}")

            # ── บันทึก ────────────────────────────────────────────────────────
            if st.button("💾 บันทึกการส่งของ", type="primary", use_container_width=True, key="sp_save"):
                if not _sp_rname.strip():
                    st.error("กรุณากรอกชื่อผู้รับ")
                elif not _sp_pc.strip():
                    st.error("กรุณากรอกรหัสไปรษณีย์")
                else:
                    _sp_new_id = str(uuid.uuid4())
                    _sp_wt = _sp_total_weight / 1000
                    try:
                        db.create_shipment({
                            "id":             _sp_new_id,
                            "customer_id":    _sp_cid or None,
                            "recipient_name": _sp_rname.strip(),
                            "phone":          _sp_rphone.strip(),
                            "address_line":   _sp_al.strip(),
                            "district":       _sp_dt.strip(),
                            "amphure":        _sp_am.strip(),
                            "province":       _sp_pv.strip(),
                            "postal_code":    _sp_pc.strip(),
                            "carrier":        _sp_carrier,
                            "shipping_cost":  _sp_cost,
                            "items":          _sp_items,
                            "tracking_no":    _sp_track.strip(),
                            "cod_amount":     0,
                            "notes":          _sp_notes.strip(),
                            "source":         "ship",
                        })
                    except Exception as _e:
                        st.error(f"❌ บันทึกไม่สำเร็จ: {_e}")
                        st.stop()
                    # ตั้ง iShip pending เพื่อส่งขนส่ง
                    _sp_item_codes = " ".join(f"{it['product_id']}-{it['qty']}" for it in _sp_items)
                    _sp_remark = " ".join(filter(None, [
                        _sp_cust if _sp_cust != "— เลือกลูกค้า —" else "",
                        _sp_item_codes,
                        _sp_notes.strip(),
                        _sp_iship_note.strip(),
                    ]))
                    _sp_iship_args = {
                        "dst_name":     _sp_rname.strip(),
                        "dst_phone":    _sp_rphone.strip(),
                        "address_line": _sp_al.strip(),
                        "district":     _sp_dt.strip(),
                        "amphure":      _sp_am.strip(),
                        "province":     _sp_pv.strip(),
                        "zipcode":      _sp_pc.strip(),
                        "weight_kg":    max(0.5, _sp_wt),
                        "cod_amount":   0,
                        "carrier":      _sp_carrier,
                        "remark":       _sp_remark,
                        "item_detail":  ", ".join(f"{it['name']} x{it['qty']}" for it in _sp_items) or _sp_remark,
                        "products":     [{"name": it["name"], "qty": it["qty"], "price": 0} for it in _sp_items],
                        "_items":       _sp_items,
                        "_shipment_id":   _sp_new_id,
                        "_customer_id":   _sp_cid or "",
                        "_customer_name": _sp_cust if _sp_cust != "— เลือกลูกค้า —" else "",
                    }
                    if iship_api.is_configured():
                        st.session_state.pop("_cs_carrier_sel", None)
                        st.session_state["_iship_carrier_select"] = {
                            "tab":          "ship",
                            "postcode":     _sp_pc.strip(),
                            "weight_kg":    max(0.5, _sp_wt),
                            "dst_name":     _sp_rname.strip(),
                            "dst_phone":    _sp_rphone.strip(),
                            "address_line": _sp_al.strip(),
                            "district":     _sp_dt.strip(),
                            "amphure":      _sp_am.strip(),
                            "province":     _sp_pv.strip(),
                            "cod_amount":   0,
                            "items":        _sp_items,
                            "customer_id":  _sp_cid or "",
                            "customer_name":_sp_cust if _sp_cust != "— เลือกลูกค้า —" else "",
                            "shipment_id":  _sp_new_id,
                            "remark":       _sp_remark,
                        }
                        st.session_state["_open_carrier_select"] = True
                    for _k in _sp_keys:
                        st.session_state.pop(_k, None)
                    st.session_state["_sp_addr_ver"] = _sp_av + 1
                    _sp_cv = st.session_state.get("_sp_cart_ver", 0)
                    st.session_state.pop(f"sp_cart_{_sp_cv}", None)
                    st.session_state["_sp_cart_ver"] = _sp_cv + 1
                    st.rerun()

            st.caption("กรอกข้อมูลด้านบนแล้วกด 💾 บันทึกการส่งของ — tracking จะบันทึกอัตโนมัติหลังส่ง iShip")

            # ── ผลลัพธ์หลังบันทึก ─────────────────────────────────────────────
            if st.session_state.get("_sp_last_tracking"):
                _lt = st.session_state["_sp_last_tracking"]
                _ltc1, _ltc2 = st.columns([5, 1])
                _ltc1.success(f"✅ iShip สำเร็จ — Tracking: **{_lt}**")
                if _ltc2.button("✕", key="sp_clear_tracking", use_container_width=True):
                    del st.session_state["_sp_last_tracking"]
                    st.rerun()

            if st.session_state.get("_sp_iship_pending"):
                _spp = st.session_state["_sp_iship_pending"]
                _spp_addr  = f"{_spp.get('address_line','')} {_spp.get('district','')} {_spp.get('amphure','')} {_spp.get('province','')} {_spp.get('zipcode','')}".strip()
                _spp_items = ", ".join(f"{it.get('product_id','')} {it.get('name','')} ×{it.get('qty',0)}" for it in (_spp.get("_items") or []))
                _spp_cust  = _spp.get("_customer_name", "")
                _cust_line = f"🧑 ลูกค้า: **{_spp_cust}**  \n" if _spp_cust else ""
                _item_line = f"  \n🛍️ {_spp_items}" if _spp_items else ""
                if _spp.get("_auto_error"):
                    st.error(f"❌ iShip ล้มเหลว: {_spp['_auto_error']} — กรุณาลองใหม่")
                st.info(f"{_cust_line}📦 **{_spp['dst_name']}** | ☎ {_spp.get('dst_phone','')}  \n{_spp_addr}{_item_line}")
                _si1, _si2 = st.columns([3, 1])
                _sp_car_pick = _si1.radio("ขนส่ง", ["Flash Express", "SPX Express"],
                                          index=0 if _spp["carrier"] == "Flash Express" else 1,
                                          horizontal=True, key="sp_iship_carrier")
                _spp["carrier"] = _sp_car_pick
                if _si1.button("🚚 ส่ง iShip", type="primary", use_container_width=True, key="sp_do_iship"):
                    if iship_api.is_configured():
                        _sp_call = {k: _spp[k] for k in
                                    {"dst_name","dst_phone","address_line","district",
                                     "amphure","province","zipcode","weight_kg",
                                     "cod_amount","carrier","remark","item_detail","products"} if k in _spp}
                        with st.spinner("กำลังสร้างรายการใน iShip..."):
                            _sp_resp = iship_api.create_order(**_sp_call)
                        if _sp_resp.get("status"):
                            _sp_tracking = _extract_tracking(_sp_resp)
                            if _spp.get("_shipment_id") and _sp_tracking:
                                db.update_shipment_tracking(_spp["_shipment_id"], _sp_tracking)
                            _sp_cid2 = _spp.get("_customer_id", "")
                            _sp_luid_b, _sp_gid_b = db.get_customer_line_ids(_sp_cid2) if (_sp_tracking and _sp_cid2) else ("", "")
                            del st.session_state["_sp_iship_pending"]
                            _spp_addr = f"{_spp.get('address_line','')} {_spp.get('district','')} {_spp.get('amphure','')} {_spp.get('province','')} {_spp.get('zipcode','')}".strip()
                            st.session_state["_iship_success_info"] = _build_success_info(
                                tracking=_sp_tracking, tab="ship",
                                customer=_spp.get("_customer_name",""),
                                dst_name=_spp.get("dst_name",""),
                                dst_phone=_spp.get("dst_phone",""),
                                address=_spp_addr,
                                carrier=_spp.get("carrier",""),
                                weight_kg=_spp.get("weight_kg",0),
                                cod_amount=_spp.get("cod_amount",0),
                                items=_spp.get("_items",[]),
                                line_user_id=_sp_luid_b,
                                shipment_id=_spp.get("_shipment_id", ""),
                                group_id=_sp_gid_b,
                            )
                            st.session_state["_open_success_dialog"] = True
                            st.rerun()
                        else:
                            _sp_err = _sp_resp.get("message") or str(_sp_resp)
                            if "NotSupportAddress" in _sp_err:
                                st.error("❌ ที่อยู่ไม่ถูกต้อง — ตำบล / อำเภอ / จังหวัด ต้องตรงกับฐานข้อมูล iShip")
                            elif "500" in _sp_err or "DOCTYPE" in _sp_err:
                                st.warning("⚠️ iShip API ไม่รองรับ COD อัตโนมัติ — กรุณาสร้างใน iShip เอง")
                                _spp2 = st.session_state.get("_sp_iship_pending", {})
                                st.code(
                                    f"ผู้รับ: {_spp2.get('dst_name','')} | {_spp2.get('dst_phone','')}\n"
                                    f"ที่อยู่: {_spp2.get('address_line','')} {_spp2.get('district','')} {_spp2.get('amphure','')} {_spp2.get('province','')} {_spp2.get('zipcode','')}\n"
                                    f"ขนส่ง: {_spp2.get('carrier','')} | COD: {_spp2.get('cod_amount',0):,} ฿\n"
                                    f"หมายเหตุ: {_spp2.get('remark','')}",
                                    language=None
                                )
                            else:
                                st.error(f"❌ iShip Error: {_sp_err}")
                    else:
                        st.warning("⚙️ ยังไม่ได้ตั้งค่า ISHIP_TOKEN ใน secrets")
                if _si2.button("ปิด", key="sp_cancel_iship", use_container_width=True):
                    del st.session_state["_sp_iship_pending"]
                    st.rerun()

        elif _sub_active == "🔢 คำนวณยอด":
            st.subheader("คำนวณยอด")
            st.caption("พิมพ์รหัสสินค้าแบบ LINE OA แล้วกดคำนวณ เช่น `TF2581-2 RB2306-1 SH-kg12170 COD`")

            _parse_calc_order = calc_logic.parse_calc_order

            _calc_products  = products
            _calc_customers = customers
            _calc_cust_map  = {c["name"]: c for c in _calc_customers}

            _calc_ver = st.session_state.get("_calc_ver", 0)

            _calc_col1, _calc_col2 = st.columns([3, 2])
            with _calc_col1:
                _calc_text = st.text_area(
                    "รหัสสินค้า",
                    key=f"_calc_text_v{_calc_ver}",
                    height=100,
                    placeholder="TF2581-2 RB2306-1",
                )
                _ccb1, _ccb2, _ccb3 = st.columns([1, 2, 1])
                _calc_ship_chk = _ccb1.checkbox("📦 จัดส่ง", key=f"_calc_ship_chk_v{_calc_ver}")
                _calc_zip = ""
                if _calc_ship_chk:
                    _calc_zip = _ccb2.text_input(
                        "รหัสไปรษณีย์", key=f"_calc_zip_v{_calc_ver}", max_chars=5,
                        placeholder="12170",
                    )
                _calc_cod_chk = _ccb3.checkbox("COD", key=f"_calc_cod_chk_v{_calc_ver}")
            with _calc_col2:
                _calc_cust_opts = ["— ไม่ระบุ —"] + sorted(_calc_cust_map.keys(), key=str.casefold)
                _calc_cust_sel  = st.selectbox("ลูกค้า (ถ้าจะส่ง LINE)", _calc_cust_opts,
                                               key=f"_calc_cust_v{_calc_ver}")
                _line_btn_slot  = st.empty()

            _cbtn1, _cbtn2 = st.columns([1, 1])
            if _cbtn1.button("🔢 คำนวณ", type="primary", key="calc_btn", use_container_width=True):
                if not _calc_text.strip():
                    st.warning("กรุณากรอกรหัสสินค้าก่อน")
                else:
                    _cr = _parse_calc_order(_calc_text, _calc_products)
                    if _calc_ship_chk:
                        if len(_calc_zip) == 5:
                            _cr["ship_zip"] = _calc_zip
                        else:
                            _cr["ship_zip"] = ""
                            _cr["manual_ship"] = -2  # จัดส่งแต่ไม่ระบุรหัสไปรษณีย์ → คิดตามน้ำหนักล้วน
                    if _calc_cod_chk:
                        _cr["is_cod"] = True
                    st.session_state["_calc_result"] = _cr
            if _cbtn2.button("🗑️ ล้าง", key="calc_clear_btn", use_container_width=True):
                st.session_state.pop("_calc_result", None)
                st.session_state["_calc_ver"] = _calc_ver + 1
                st.rerun()

            _cr = st.session_state.get("_calc_result")
            if _cr:
                if _cr["errors"]:
                    for _e in _cr["errors"]:
                        st.error(f"⚠️ {_e}")

                if _cr["items"]:
                    st.divider()
                    _c_total_amt = 0.0
                    _c_total_pv  = 0.0
                    _c_total_w   = 0
                    _c_lines     = []
                    for _ci in _cr["items"]:
                        _cp  = _ci["product"]
                        _cq  = int(_ci["qty"])
                        _camt = float(_cp["price"]) * _cq
                        _cpv  = float(_cp.get("points_per_unit", 0)) * _cq
                        _cw   = int(_cp.get("weight_grams", 0)) * _cq
                        _c_total_amt += _camt
                        _c_total_pv  += _cpv
                        _c_total_w   += _cw
                        _line_str = f"📦 [{_cp['id'].upper()}] - {_cq} * {int(_cp['price']):,} = {int(_camt):,}"
                        st.markdown(_line_str)
                        _c_lines.append(_line_str)

                    _c_weight_kg = (_c_total_w + BOX_WEIGHT_G) / 1000
                    st.markdown(f"✨ {_c_total_pv:,.0f} PV | ⚖️ {_c_weight_kg:.2f} kg")
                    st.divider()

                    _cust_ship_fee = 0.0   # ราคาคิดลูกค้า (39+10/kg+พื้นที่)
                    _c_ship_fee    = 0.0   # ราคาจริงถูกสุดจากตารางขนส่ง
                    _c_ship_label  = ""
                    _opts = []
                    if _cr["ship_zip"]:
                        _cust_ship_fee = calc_shipping(_c_total_w, _cr["ship_zip"])
                        _opts = carr.get_shipping_options(
                            _c_weight_kg, _cr["ship_zip"], _cr["is_cod"], _c_total_amt
                        )
                        _opts_ok = [o for o in _opts if not o["exceeds_max"]]
                        if _opts_ok:
                            _best = _opts_ok[0]
                            _c_ship_fee  = float(_best["total"])
                            _c_ship_label = _best["name"]
                    elif _cr["manual_ship"] >= 0:
                        _cust_ship_fee = _cr["manual_ship"]
                        _c_ship_fee    = _cr["manual_ship"]
                        _c_ship_label  = "ระบุเอง"
                    elif _cr["manual_ship"] == -2:
                        # จัดส่งแต่ไม่ระบุรหัสไปรษณีย์ → คิดค่าส่งตามน้ำหนักล้วน (ไม่รวมค่าพื้นที่)
                        _cust_ship_fee = calc_shipping(_c_total_w, "")
                        _c_ship_fee    = _cust_ship_fee
                        _c_ship_label  = "ประมาณการตามน้ำหนัก (ยังไม่ระบุพื้นที่)"

                    _c_cod_fee   = calc_logic.cod_fee(_c_total_amt + _cust_ship_fee) if _cr["is_cod"] else 0
                    _c_grand     = _c_total_amt + _cust_ship_fee + _c_cod_fee

                    # ─── ส่วนลูกค้า (copy / ส่ง LINE) ────────────────────────
                    st.markdown(f"💵 สินค้า: ฿{_c_total_amt:,.0f}")
                    if _cust_ship_fee > 0:
                        st.markdown(f"🚚 ค่าส่ง: ฿{int(_cust_ship_fee):,}")
                    if _c_cod_fee > 0:
                        st.markdown(f"➕ COD 3.21%: ฿{int(_c_cod_fee):,}")
                    _parts_raw = [str(int(_c_total_amt))]
                    if _cust_ship_fee > 0: _parts_raw.append(str(int(_cust_ship_fee)))
                    if _c_cod_fee > 0:     _parts_raw.append(str(int(_c_cod_fee)))
                    st.markdown(f"{' + '.join(_parts_raw)} = {_c_grand:,.0f}")
                    st.markdown(f"**💰 ยอดโอนสุทธิ: ฿{_c_grand:,.0f}**")

                    # ─── ส่วนเจ้าของ (ราคาจริง + ตารางขนส่ง) ─────────────────
                    st.divider()
                    st.caption("ข้อมูลขนส่ง (สำหรับเจ้าของร้าน)")
                    if _c_ship_fee > 0 and _c_ship_label and _c_ship_label != "ระบุเอง":
                        st.markdown(f"### 🚛 ราคาจริง: {_c_ship_fee:,.0f} ฿ ({_c_ship_label})")

                    # ─── ทดลองส่ง iShip ──────────────────────────────────────
                    if _cr["ship_zip"] and _opts_ok and _calc_cust_sel != "— ไม่ระบุ —" and iship_api.is_configured():
                        _ic_cust = _calc_cust_map.get(_calc_cust_sel, {})
                        _ic_cid  = _ic_cust.get("id", "")
                        if _ic_cid:
                            _ic_addrs = db.get_customer_addresses(_ic_cid)
                            if _ic_addrs:
                                _ic_labels = [
                                    f"{a.get('recipient_name','')} · {a.get('phone','')} · "
                                    f"{a.get('address_line','')} {a.get('district','')} {a.get('amphure','')} {a.get('province','')} {a.get('postal_code','')}"
                                    for a in _ic_addrs
                                ]
                                _ic_sel  = st.selectbox("📍 เลือกที่อยู่ผู้รับ", _ic_labels, key="calc_iship_addr")
                                _ic_addr = _ic_addrs[_ic_labels.index(_ic_sel)]
                                _ic_cod  = _c_grand if _cr["is_cod"] else 0.0

                                # ── เลือก carrier (default = ถูกสุด) ──────────
                                _ic_carrier_opts = [o["name"] for o in _opts_ok]
                                _ic_carrier_sel  = st.selectbox(
                                    "🚚 เลือกขนส่ง",
                                    _ic_carrier_opts,
                                    index=0,
                                    key="calc_iship_carrier",
                                )
                                _ic_courier_code = iship_api.COURIER_MAP.get(_ic_carrier_sel, "")
                                _ic_chosen_total = next((o["total"] for o in _opts_ok if o["name"] == _ic_carrier_sel), _c_ship_fee)
                                if _ic_cod:
                                    st.caption(f"iShip code: `{_ic_courier_code}` | ราคาจริง: {_ic_chosen_total:,} ฿ | COD: {int(_ic_cod):,} ฿")
                                else:
                                    st.caption(f"iShip code: `{_ic_courier_code}` | ราคาจริง: {_ic_chosen_total:,} ฿")
                                if not _ic_courier_code:
                                    st.warning(f"⚠️ ไม่พบ iShip code สำหรับ '{_ic_carrier_sel}'")

                                # ── กรอกขนาด ถ้าเป็น Bulky carrier ───────────
                                _ic_is_bulky = "Bulky" in _ic_carrier_sel
                                _ic_len = _ic_wid = _ic_hgt = 0
                                if _ic_is_bulky:
                                    st.markdown("**📐 ขนาดกล่อง (จำเป็นสำหรับ Bulky)**")
                                    _bd1, _bd2, _bd3 = st.columns(3)
                                    _ic_len = _bd1.number_input("ยาว (cm)", min_value=1, max_value=300, value=30, step=1, key="calc_iship_len")
                                    _ic_wid = _bd2.number_input("กว้าง (cm)", min_value=1, max_value=300, value=30, step=1, key="calc_iship_wid")
                                    _ic_hgt = _bd3.number_input("สูง (cm)", min_value=1, max_value=300, value=20, step=1, key="calc_iship_hgt")

                                if st.button("📦 ส่ง iShip ด้วยขนส่งที่ถูกสุด", type="primary",
                                             key="calc_iship_btn", use_container_width=True):
                                    _ic_resp = iship_api.create_order(
                                        dst_name     = _ic_addr.get("recipient_name", ""),
                                        dst_phone    = _ic_addr.get("phone", ""),
                                        address_line = _ic_addr.get("address_line", ""),
                                        district     = _ic_addr.get("district", ""),
                                        amphure      = _ic_addr.get("amphure", ""),
                                        province     = _ic_addr.get("province", ""),
                                        zipcode      = _ic_addr.get("postal_code", ""),
                                        weight_kg    = _c_weight_kg,
                                        cod_amount   = _ic_cod,
                                        carrier      = _ic_carrier_sel,
                                        remark       = "",
                                        length_cm    = int(_ic_len),
                                        width_cm     = int(_ic_wid),
                                        height_cm    = int(_ic_hgt),
                                    )
                                    if _ic_resp.get("status"):
                                        _ic_track = ((_ic_resp.get("data") or {}).get("tracking_no")
                                                     or _ic_resp.get("tracking_no", ""))
                                        st.success(f"✅ ส่ง iShip สำเร็จ! Tracking: **{_ic_track}**")
                                    else:
                                        st.error(f"❌ {_ic_resp.get('message', str(_ic_resp))}")
                                        if st.secrets.get("DEBUG_MODE"):
                                            with st.expander("🔍 debug"):
                                                st.json(_ic_resp)
                            else:
                                st.caption("ยังไม่มีที่อยู่บันทึกสำหรับลูกค้านี้")

                    if _cr["ship_zip"] and _opts:
                        _rows_ok  = [o for o in _opts if not o["exceeds_max"]]
                        _rows_exc = [o for o in _opts if o["exceeds_max"]]
                        _cmp_data = []
                        for _ci, o in enumerate(_rows_ok):
                            _sur_txt  = f"+{o['surcharge']} ({o['sur_label']})" if o["surcharge"] else "-"
                            _fuel_txt = f"+{o['fuel']}" if o["fuel"] else "-"
                            _cod_txt  = f"+{o['cod_fee']:,}" if o["cod_fee"] else "-"
                            _badge    = "🥇 " if _ci == 0 else ""
                            _cmp_data.append({
                                "ขนส่ง":        _badge + o["name"],
                                "ค่าส่ง":       o["base"],
                                "พื้นที่พิเศษ": _sur_txt,
                                "น้ำมัน":       _fuel_txt,
                                "รวม (฿)":      o["total"],
                                "COD":          _cod_txt,
                            })
                        if _cmp_data:
                            _cmp_df = pd.DataFrame(_cmp_data)
                            st.dataframe(_cmp_df, hide_index=True, use_container_width=True,
                                         column_config={"รวม (฿)": st.column_config.NumberColumn("รวม (฿)", format="%d ฿")})
                        if _rows_exc:
                            with st.expander(f"⚠️ เกินน้ำหนักสูงสุด ({len(_rows_exc)} ขนส่ง)"):
                                for o in _rows_exc:
                                    st.caption(f"❌ {o['name']} รับได้สูงสุด {o['max_kg']} kg")

                    # ─── ปุ่มส่ง LINE (แสดงใน slot ข้างชื่อลูกค้า) ───────────
                    if _calc_cust_sel != "— ไม่ระบุ —" and line_api.is_configured():
                        _c_cust  = _calc_cust_map.get(_calc_cust_sel, {})
                        _c_luid, _c_gid  = db.get_customer_line_ids(_c_cust.get("id", "")) if _c_cust.get("id") else ("", "")
                        if _c_luid or _c_gid:
                            if _line_btn_slot.button(f"📨 ส่ง LINE ให้คุณ {_calc_cust_sel}", type="primary", key="calc_line_btn", use_container_width=True):
                                _c_msg_lines = ["📝 รายการสินค้า", ""]
                                _c_msg_lines += _c_lines
                                _c_msg_lines += ["",
                                                 f"✨ {_c_total_pv:,.0f} PV | ⚖️ {_c_weight_kg:.2f} kg",
                                                 "",
                                                 f"💵 สินค้า: ฿{_c_total_amt:,.0f}"]
                                if _cust_ship_fee > 0:
                                    _c_msg_lines.append(f"🚚 ค่าส่ง: ฿{_cust_ship_fee:,.0f}")
                                if _c_cod_fee > 0:
                                    _c_msg_lines.append(f"➕ COD: ฿{_c_cod_fee:,.0f}")
                                _parts = [str(int(_c_total_amt))]
                                if _cust_ship_fee > 0: _parts.append(str(int(_cust_ship_fee)))
                                if _c_cod_fee  > 0: _parts.append(str(int(_c_cod_fee)))
                                _formula = " + ".join(_parts)
                                _c_msg_lines.append(f"\n{_formula} = {int(_c_grand):,}")
                                _c_msg_lines.append(f"💰 ยอดโอนสุทธิ: ฿{int(_c_grand):,}")
                                _c_res = line_api.push_text(_c_luid, "\n".join(_c_msg_lines), group_id=_c_gid)
                                if _c_res["ok"]:
                                    st.success(f"✅ ส่ง LINE ให้ {_calc_cust_sel} แล้ว")
                                else:
                                    st.error(f"❌ {_c_res['error']}")
                        else:
                            _line_btn_slot.caption(f"👤 ยังไม่มี LINE ID")

            # ── แบ่งกล่อง ──────────────────────────────────────────────────────
            if st.button("📦 แบ่งกล่อง", key="toggle_boxcalc", use_container_width=True):
                st.session_state["_show_boxcalc"] = not st.session_state.get("_show_boxcalc", False)
            if st.session_state.get("_show_boxcalc"):
                st.subheader("📦 คำนวณการแบ่งกล่อง")
                st.caption("ดึงน้ำหนักจาก tab 🔢 คำนวณยอด — กดคำนวณที่นั่นก่อน "
                           "ระบบจะเก็บสินค้าเดียวกันไว้ด้วยกันก่อน แล้วหาเพดานน้ำหนัก/กล่องที่คุ้มสุด "
                           "ของแต่ละขนส่งให้เองอัตโนมัติ")

                _bx_cr = st.session_state.get("_calc_result")
                if not _bx_cr or not _bx_cr.get("items"):
                    st.info("กรุณาคำนวณยอดใน tab 🔢 คำนวณยอด ก่อน")
                else:
                    _bx_prod_kg  = sum(int(_ci["product"].get("weight_grams",0))*int(_ci["qty"]) for _ci in _bx_cr["items"]) / 1000
                    _bx_postcode = _bx_cr.get("ship_zip", "")
                    st.markdown(f"⚖️ น้ำหนักสินค้ารวม: **{_bx_prod_kg:.3f} kg**"
                                + (f"  |  📮 **{_bx_postcode}**" if _bx_postcode else ""))

                    if not _bx_postcode:
                        st.caption("ใส่รหัสไปรษณีย์ (SH-kgXXXXX) ใน tab คำนวณยอด เพื่อวางแผนกล่อง+เทียบค่าส่ง")
                    else:
                        _bx_plans = carr.plan_boxes(_bx_cr["items"], _bx_postcode)
                        if not _bx_plans:
                            st.warning("ไม่มีขนส่งไหนรองรับออร์เดอร์นี้ได้เลย")
                        else:
                            # ── สรุปทุกขนส่ง (เรียงถูกสุดก่อน) ────────────────────
                            _plan_rows = [{
                                "ขนส่ง":         ("⭐ " if i == 0 else "") + p["name"],
                                "จำนวนกล่อง":    p["box_count"],
                                "เพดานกล่อง":    f"{p['ceiling_used']} kg",
                                "ค่าส่งรวม (฿)":  p["total_cost"],
                            } for i, p in enumerate(_bx_plans)]
                            st.dataframe(pd.DataFrame(_plan_rows), hide_index=True, use_container_width=True,
                                         column_config={"ค่าส่งรวม (฿)": st.column_config.NumberColumn(format="%.0f ฿")})
                            st.caption("⭐ = ค่าส่งรวมถูกสุด — ระบบลองแพ็คที่จุดตัดราคาของแต่ละขนส่งให้เองแล้ว")

                            # ── รายละเอียด — เลือกขนส่ง ───────────────────────────
                            st.divider()
                            _bx_idx = st.selectbox(
                                "ดูรายละเอียด — เลือกขนส่ง",
                                list(range(len(_bx_plans))),
                                format_func=lambda i: _bx_plans[i]["name"],
                                key="_bx_sel_carrier",
                            )
                            _sel_plan = _bx_plans[_bx_idx]

                            st.markdown(f"**📦 การจัดสินค้า ({_sel_plan['box_count']} กล่อง — เพดาน {_sel_plan['ceiling_used']} kg)**")
                            for _bi, _box in enumerate(_sel_plan["boxes"], 1):
                                _items_str = "  ·  ".join(f"{code}×{qty}" for code, qty in _box["items"].items())
                                _bkg = _box["weight_kg"] + 0.5
                                _bprice = _box.get("price")
                                _price_str = f" &nbsp;·&nbsp; **{_bprice:.0f} ฿**" if _bprice is not None else ""
                                st.markdown(f"กล่อง {_bi}: {_items_str} &nbsp;`{_box['weight_kg']:.3f} kg สินค้า + 0.5 kg กล่อง = {_bkg:.3f} kg`{_price_str}")
                            st.markdown(f"**ค่าส่งรวม: {_sel_plan['total_cost']:.0f} ฿**")

                            # ── เทียบทุกจุดตัดที่ลอง (ให้เห็นว่าลองครบจริง ไม่ใช่แค่ค่าที่เลือก)
                            if len(_sel_plan.get("candidates", [])) > 1:
                                st.divider()
                                st.markdown("**⚖️ เทียบทุกเพดานที่ลองของขนส่งนี้**")
                                _cand_rows = [{
                                    "เพดาน":       ("✅ " if c["ceiling"] == _sel_plan["ceiling_used"] else "") + f"{c['ceiling']} kg",
                                    "จำนวนกล่อง":  c["box_count"] if c["box_count"] is not None else "—",
                                    "ค่าส่งรวม (฿)": c["total_cost"] if c["total_cost"] is not None else "เกินน้ำหนัก",
                                } for c in _sel_plan["candidates"]]
                                st.dataframe(pd.DataFrame(_cand_rows), hide_index=True, use_container_width=True)
                                st.caption("✅ = เพดานที่เลือกใช้ (ถูกสุดหรือเท่ากับตัวอื่น)")

                            # ── ปริ้นใบปะหน้า (manual — ไม่ผ่าน iShip เช่น Inter/J&T) ──────
                            st.divider()
                            if st.button("🖨️ ปริ้นใบปะหน้า", key="toggle_manual_label"):
                                st.session_state["_show_manual_label"] = not st.session_state.get("_show_manual_label", False)
                            if st.session_state.get("_show_manual_label"):
                                st.markdown("**🖨️ ปริ้นใบปะหน้า (แบบ manual — ไม่ผ่าน iShip)**")

                                # เติมค่าที่ staged ไว้ (เลือกที่อยู่เดิม / รหัสไปรษณีย์ auto-fill)
                                # ก่อน render widget เสมอ — ห้ามตั้งค่า session_state ของ widget
                                # ที่ render ไปแล้วในรอบเดียวกัน (Streamlit จะ error)
                                for _lfk, _lwk in [
                                    ("_lbl_fr_name", "_lbl_name"), ("_lbl_fr_phone", "_lbl_phone"),
                                    ("_lbl_fr_al", "_lbl_addr_line"), ("_lbl_fr_dt", "_lbl_district"),
                                    ("_lbl_fr_am", "_lbl_amphure"), ("_lbl_fr_pv", "_lbl_province"),
                                    ("_lbl_fr_zip", "_lbl_zip"),
                                ]:
                                    if _lfk in st.session_state:
                                        st.session_state[_lwk] = st.session_state.pop(_lfk)

                                _lbl_cust_opts = ["-- พิมพ์เอง --"] + sorted(customer_map.keys(), key=str.casefold)
                                _lbl_cust_sel  = st.selectbox("ลูกค้า/ผู้รับ", _lbl_cust_opts, key="_lbl_cust_sel")
                                _lbl_cust_id  = None
                                _lbl_addr_sig = None
                                _lbl_seed     = {}
                                if _lbl_cust_sel != "-- พิมพ์เอง --":
                                    _lbl_cust_obj = customer_map[_lbl_cust_sel]
                                    _lbl_cust_id  = _lbl_cust_obj["id"]
                                    _lbl_addrs = db.get_customer_addresses(_lbl_cust_id)
                                    if _lbl_addrs:
                                        _lbl_addr_labels = [
                                            f"{a.get('recipient_name','')} · {a.get('phone','')} · "
                                            f"{a.get('address_line','')} {a.get('district','')} {a.get('amphure','')} {a.get('province','')} {a.get('postal_code','')}"
                                            for a in _lbl_addrs
                                        ]
                                        _lbl_addr_sel = st.selectbox("ที่อยู่ที่บันทึกไว้", _lbl_addr_labels, key="_lbl_addr_sel")
                                        _lbl_seed     = _lbl_addrs[_lbl_addr_labels.index(_lbl_addr_sel)]
                                        _lbl_addr_sig = (_lbl_cust_id, _lbl_addr_sel)
                                    else:
                                        st.caption("ลูกค้านี้ยังไม่มีที่อยู่บันทึกไว้ — กรอกเองด้านล่าง")

                                # ที่อยู่ที่เลือกเปลี่ยนไปจากเดิม → stage แล้ว rerun เพื่อเติมให้ widget ด้านล่าง
                                if _lbl_addr_sig is not None and _lbl_addr_sig != st.session_state.get("_lbl_addr_applied"):
                                    st.session_state["_lbl_addr_applied"] = _lbl_addr_sig
                                    st.session_state["_lbl_fr_name"]  = _lbl_seed.get("recipient_name", "") or ""
                                    st.session_state["_lbl_fr_phone"] = _lbl_seed.get("phone", "") or ""
                                    st.session_state["_lbl_fr_al"]    = _lbl_seed.get("address_line", "") or ""
                                    st.session_state["_lbl_fr_dt"]    = _lbl_seed.get("district", "") or ""
                                    st.session_state["_lbl_fr_am"]    = _lbl_seed.get("amphure", "") or ""
                                    st.session_state["_lbl_fr_pv"]    = _lbl_seed.get("province", "") or ""
                                    st.session_state["_lbl_fr_zip"]   = _lbl_seed.get("postal_code", "") or ""
                                    # ตั้งค่า searchbox ของตำบลตรงๆ (ไม่ใช้ value= เฉยๆ เพราะถ้า
                                    # key นี้เคยมีอยู่แล้ว Streamlit จะไม่ยอมอัปเดตค่าที่แสดงให้)
                                    st.session_state["_lbl_dt_searchbox"] = _lbl_seed.get("district", "") or ""
                                    st.rerun()

                                _lc1, _lc2 = st.columns(2)
                                _lbl_name  = _lc1.text_input("ชื่อผู้รับ", key="_lbl_name")
                                _lbl_phone = _lc2.text_input("เบอร์โทร", key="_lbl_phone")
                                _lbl_addr_line = st.text_input("ที่อยู่ (บ้านเลขที่/ถนน)", key="_lbl_addr_line")
                                _la1, _la2, _la3, _la4 = st.columns(4)
                                with _la1:
                                    _lbl_district = _tambon_selectbox(
                                        "_lbl_district", "_lbl_amphure", "_lbl_province", "_lbl_zip",
                                        "_lbl_dt_searchbox",
                                    )
                                _lbl_amphure  = _la2.text_input("อำเภอ/เขต", key="_lbl_amphure")
                                _lbl_province = _la3.selectbox("จังหวัด", [""] + _PROVINCES, key="_lbl_province")
                                _lbl_zip      = _la4.text_input("รหัสไปรษณีย์", max_chars=5, key="_lbl_zip")
                                _postcode_suggest(_lbl_zip, "_lbl_district", "_lbl_amphure", "_lbl_province",
                                                  "_lbl_dt_searchbox", "_lbl_pc_suggest",
                                                  stage_dt="_lbl_fr_dt", stage_am="_lbl_fr_am", stage_pv="_lbl_fr_pv")

                                if _lbl_cust_id:
                                    if st.button("💾 บันทึกที่อยู่นี้", key="_lbl_save_addr_btn"):
                                        try:
                                            db.upsert_customer_address({
                                                "id":             str(uuid.uuid4()),
                                                "customer_id":    _lbl_cust_id,
                                                "recipient_name": _lbl_name,
                                                "phone":          _lbl_phone,
                                                "address_line":   _lbl_addr_line,
                                                "district":       _lbl_district,
                                                "amphure":        _lbl_amphure,
                                                "province":       _lbl_province,
                                                "postal_code":    _lbl_zip,
                                            })
                                            st.success("✅ บันทึกแล้ว — เลือกจากที่อยู่ที่บันทึกไว้ได้ครั้งถัดไป")
                                        except Exception as _lbl_sa_e:
                                            st.error(f"❌ บันทึกที่อยู่ไม่สำเร็จ: {_lbl_sa_e}")
                                else:
                                    st.caption("เลือกลูกค้าด้านบนก่อน จึงจะบันทึกที่อยู่นี้ไว้ใช้ครั้งถัดไปได้")

                                st.markdown("**ขนาดกล่อง — เพิ่มได้หลายขนาดในใบเดียว**")
                                if "_lbl_box_rows" not in st.session_state:
                                    st.session_state["_lbl_box_rows"] = []

                                _lbl_presets = get_bulky_presets()
                                _lbl_preset_opts = ["กรอกเอง"] + [p["name"] for p in _lbl_presets]
                                _lbl_preset_sel = st.selectbox(
                                    "เลือกขนาดกล่อง (จัดการ preset ได้ที่แท็บ ⚙️ จัดการข้อมูล → 📐 ขนาดกล่อง)",
                                    _lbl_preset_opts, key="_lbl_preset_sel",
                                )
                                _lbl_pm = next((p for p in _lbl_presets if p["name"] == _lbl_preset_sel), None)
                                _lbl_def_l, _lbl_def_w, _lbl_def_h = (_lbl_pm["l"], _lbl_pm["w"], _lbl_pm["h"]) if _lbl_pm else (30, 30, 20)
                                _lb1, _lb2, _lb3, _lb4, _lb5 = st.columns(5)
                                _lbl_len = _lb1.number_input("ยาว (cm)", 1, 300, _lbl_def_l, key=f"_lbl_len_{_lbl_preset_sel}")
                                _lbl_wid = _lb2.number_input("กว้าง (cm)", 1, 300, _lbl_def_w, key=f"_lbl_wid_{_lbl_preset_sel}")
                                _lbl_hgt = _lb3.number_input("สูง (cm)", 1, 300, _lbl_def_h, key=f"_lbl_hgt_{_lbl_preset_sel}")
                                _lbl_row_weight = _lb4.number_input("น้ำหนัก/กล่อง (kg)", 0.0, 200.0, 25.0, key="_lbl_row_weight")
                                _lbl_row_qty    = _lb5.number_input("จำนวน", 1, 100, 1, key="_lbl_row_qty")

                                if st.button("➕ เพิ่มกล่อง", key="_lbl_add_row_btn"):
                                    st.session_state["_lbl_box_rows"].append({
                                        "l": int(_lbl_len), "w": int(_lbl_wid), "h": int(_lbl_hgt),
                                        "weight_kg": float(_lbl_row_weight), "qty": int(_lbl_row_qty),
                                    })
                                    st.rerun()

                                _lbl_rows = st.session_state["_lbl_box_rows"]
                                if _lbl_rows:
                                    st.markdown("**รายการกล่องที่เพิ่มแล้ว**")
                                    _rows_df = pd.DataFrame([{
                                        "ขนาด (ซม.)":         f"{r['l']}×{r['w']}×{r['h']}",
                                        "น้ำหนัก/กล่อง (kg)": r["weight_kg"],
                                        "จำนวน":              r["qty"],
                                    } for r in _lbl_rows])
                                    st.dataframe(_rows_df, hide_index=True, use_container_width=True)
                                    _lbl_total_boxes  = sum(r["qty"] for r in _lbl_rows)
                                    _lbl_total_weight = sum(r["weight_kg"] * r["qty"] for r in _lbl_rows)
                                    st.caption(f"รวม {_lbl_total_boxes} กล่อง &nbsp;|&nbsp; น้ำหนักรวม {_lbl_total_weight:.2f} kg")
                                    if st.button("🗑️ ล้างรายการกล่องทั้งหมด", key="_lbl_clear_rows_btn"):
                                        st.session_state["_lbl_box_rows"] = []
                                        st.rerun()
                                else:
                                    st.caption("ยังไม่มีกล่องในรายการ — กด \"➕ เพิ่มกล่อง\" อย่างน้อย 1 ครั้งก่อนพิมพ์")

                                _lbl_cod_chk = st.checkbox("COD", key="_lbl_cod_chk")
                                _lbl_cod_amt = st.number_input("ยอดเก็บ COD (บาท)", min_value=0.0, step=1.0, key="_lbl_cod_amt") if _lbl_cod_chk else 0.0
                                _lbl_notes   = st.text_input("หมายเหตุ", key="_lbl_notes")

                                if st.button("🖨️ พิมพ์ใบปะหน้า + บันทึกประวัติ", type="primary", key="_lbl_print_btn"):
                                    if not _lbl_name or not _lbl_addr_line:
                                        st.error("กรุณากรอกชื่อผู้รับและที่อยู่ก่อน")
                                    elif not _lbl_rows:
                                        st.error("กรุณาเพิ่มกล่องอย่างน้อย 1 รายการก่อนพิมพ์")
                                    else:
                                        _src = iship_api._src()
                                        _label_items: dict = {}
                                        for _box in _sel_plan.get("boxes", []):
                                            for _code, _qty in _box["items"].items():
                                                _label_items[_code] = _label_items.get(_code, 0) + _qty

                                        _lbl_total_boxes = sum(r["qty"] for r in _lbl_rows)
                                        _box_rows_html = "".join(
                                            f"<tr><td>{r['l']}×{r['w']}×{r['h']} ซม.</td>"
                                            f"<td style='text-align:center'>{r['weight_kg']:.2f} kg</td>"
                                            f"<td style='text-align:center'>{r['qty']}</td></tr>"
                                            for r in _lbl_rows
                                        )
                                        _cod_line = f"&nbsp;|&nbsp; <b>COD:</b> {_lbl_cod_amt:,.0f} ฿" if _lbl_cod_chk else ""
                                        _notes_line = f'<div class="section"><b>หมายเหตุ:</b> {_lbl_notes}</div>' if _lbl_notes else ""
                                        _label_html = f"""<!DOCTYPE html><html><head><meta charset='UTF-8'>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{background:#fff!important;color:#000!important}}
body{{font-family:'Prompt',sans-serif;padding:16px;font-size:13px}}
.header{{border-bottom:2px solid #000;padding-bottom:8px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:flex-start}}
.header h1{{font-size:16px;font-weight:700}}
.header-right{{text-align:right;font-size:13px;font-weight:600}}
.section{{margin:10px 0;font-size:13px;line-height:1.6}}
table{{width:100%;border-collapse:collapse;margin:6px 0;border:1px solid #000}}
th{{background:#000;color:#fff;padding:5px 6px;font-size:12px;text-align:left;border:1px solid #000}}
td{{padding:4px 6px;border:1px solid #aaa;font-size:12px;color:#000}}
tr:nth-child(even) td{{background:#f0f0f0}}
.btn{{display:block;margin:0 0 12px;padding:6px 22px;background:#c0392b;color:#fff;border:none;cursor:pointer;border-radius:5px;font-size:13px}}
@media print{{.btn{{display:none}} @page{{size:A5 portrait;margin:10mm}} *{{-webkit-print-color-adjust:exact;print-color-adjust:exact}} th{{background:#000!important;color:#fff!important}} tr:nth-child(even) td{{background:#eee!important}}}}
</style></head><body>
<button class='btn' onclick='window.print()'>🖨️ พิมพ์ใบปะหน้า</button>
<div class="header">
    <div><h1>ใบปะหน้า — {_sel_plan['name']}</h1></div>
    <div class="header-right">วันที่: {date.today().strftime('%d/%m/%Y')}</div>
</div>
<div class="section"><b>ผู้ส่ง:</b> {_src.get('ISHIP_SRC_NAME','')} · โทร. {_src.get('ISHIP_SRC_PHONE','')}<br>
{_src.get('ISHIP_SRC_ADDRESS','')} {_src.get('ISHIP_SRC_DISTRICT','')} {_src.get('ISHIP_SRC_AMPHURE','')} {_src.get('ISHIP_SRC_PROVINCE','')} {_src.get('ISHIP_SRC_ZIPCODE','')}</div>
<div class="section"><b>ผู้รับ:</b> {_lbl_name} · โทร. {_lbl_phone}<br>
{_lbl_addr_line} {_lbl_district} {_lbl_amphure} {_lbl_province} {_lbl_zip}</div>
<div class="section"><b>รายการกล่อง:</b>
<table><tr><th>ขนาด</th><th>น้ำหนัก/กล่อง</th><th>จำนวน</th></tr>{_box_rows_html}</table>
รวม {_lbl_total_boxes} กล่อง {_cod_line}</div>
{_notes_line}
</body></html>"""
                                        components.html(_label_html, height=600, scrolling=True)

                                        _box_summary_txt = "; ".join(
                                            f"{r['l']}x{r['w']}x{r['h']}cm {r['weight_kg']:.1f}kg x{r['qty']}"
                                            for r in _lbl_rows
                                        )
                                        _full_notes = f"[กล่อง: {_box_summary_txt}]" + (f" {_lbl_notes}" if _lbl_notes else "")

                                        db.create_shipment({
                                            "id":            str(uuid.uuid4()),
                                            "customer_id":   _lbl_cust_id,
                                            "recipient_name": _lbl_name,
                                            "phone":         _lbl_phone,
                                            "address_line":  _lbl_addr_line,
                                            "district":      _lbl_district,
                                            "amphure":       _lbl_amphure,
                                            "province":      _lbl_province,
                                            "postal_code":   _lbl_zip,
                                            "carrier":       _sel_plan["name"],
                                            "shipping_cost": _sel_plan["total_cost"],
                                            "items":         [{"product_id": code, "name": code, "qty": qty}
                                                               for code, qty in _label_items.items()],
                                            "tracking_no":   "",
                                            "cod_amount":    _lbl_cod_amt,
                                            "notes":         _full_notes,
                                            "source":        "manual",
                                        })
                                        st.session_state["_lbl_box_rows"] = []
                                        st.success("✅ บันทึกประวัติการส่งแล้ว — ดูได้ที่แท็บ 🚚 ประวัติการส่ง")

