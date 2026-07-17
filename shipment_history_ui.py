import re
import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta, timezone

import database as db
import iship_api
from ui_helpers import _to_bkk, BOX_WEIGHT_G


def render(customers):
    st.subheader("ประวัติการส่งของ")

    _sh_cod_col, _sh_status_col, _sh_sync_col, _sh_bill_col = st.columns([2, 2, 2, 2])
    if _sh_status_col.button("🚚 สถานะส่ง", key="sh_status_sync", width="stretch"):
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
    if _sh_sync_col.button("🔄 ตรวจสอบ COD", key="sh_cod_sync", width="stretch"):
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
    if _sh_bill_col.button("💰 เทียบยอดจริง", key="sh_billing_sync", width="stretch"):
        with st.spinner("กำลังดึงข้อมูลจาก iShip..."):
            _br = iship_api.get_shipping_report(days_back=90)
        if _br.get("error"):
            st.error(f"❌ {_br['error']}")
        else:
            st.session_state["_sh_billing_map"] = _br.get("report", {})
            st.success(f"✅ ดึงข้อมูล {len(_br.get('report', {}))} tracking")
            st.rerun()
    _sh_cod_map = st.session_state.get("_sh_cod_map", {})
    _sh_billing_map = st.session_state.get("_sh_billing_map", {})
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

    # ── filter แสดงเฉพาะที่ต้องดำเนินการ ─────────────────────────────
    _TERMINAL_STATUSES = {"จัดส่งแล้ว", "ตีกลับ", "ยกเลิก"}
    _delay_cutoff = datetime.now(timezone.utc) - timedelta(days=3)

    def _is_delayed(r):
        if not r.get("tracking_no") or (r.get("delivery_status") or "") in _TERMINAL_STATUSES:
            return False
        try:
            _sdt = datetime.fromisoformat(str(r.get("created_at") or "").replace("Z", "+00:00"))
        except Exception:
            return False
        if _sdt.tzinfo is None:
            _sdt = _sdt.replace(tzinfo=timezone.utc)
        return _sdt < _delay_cutoff

    def _is_cod_pending(r):
        return float(r.get("cod_amount") or 0) > 0 and not r.get("cod_transferred_at")

    def _is_billing_anomaly(r):
        tn = r.get("tracking_no", "") or ""
        if not tn or tn not in _sh_billing_map:
            return False
        actual = float(_sh_billing_map[tn].get("discount_price") or 0)
        est    = float(r.get("shipping_cost") or 0)
        return actual > 0 and est > 0 and abs(actual - est) > 2

    _f1, _f2, _f3 = st.columns(3)
    _filter_delayed = _f1.checkbox("🚚 ล่าช้า (>3 วัน)", key="sh_filter_delayed")
    _filter_cod     = _f2.checkbox("💸 COD ค้างโอน", key="sh_filter_cod")
    _filter_billing = _f3.checkbox("⚠️ ยอดผิดปกติ", key="sh_filter_billing")
    if _filter_delayed or _filter_cod or _filter_billing:
        _sh_all = [r for r in _sh_all if
                   (_filter_delayed and _is_delayed(r)) or
                   (_filter_cod and _is_cod_pending(r)) or
                   (_filter_billing and _is_billing_anomaly(r))]

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
            if s == "manual": return "🖨️"
            return "—"

        def _billing_check(r):
            tn = r.get("tracking_no", "") or ""
            if not tn or tn not in _sh_billing_map:
                return "-"
            actual = float(_sh_billing_map[tn].get("discount_price") or 0)
            if actual <= 0:
                return "⏳ รอตีราคา"
            est = float(r.get("shipping_cost") or 0)
            if est <= 0:
                return "?"
            diff = actual - est  # + = จริงแพงกว่าประเมิน (คิดลูกค้าขาด/ขาดทุน), - = จริงถูกกว่า (คิดลูกค้าเกิน/กำไร)
            if abs(diff) <= 2:
                return f"✅ {actual:,.0f}฿"
            if diff < 0:
                return f"+{abs(diff):,.0f}฿"
            return f"❗-{diff:,.0f}฿"

        _sh_df   = pd.DataFrame([{
            "ลบ":              False,
            "📤":              False,
            "แหล่ง":           _src_icon(r),
            "วันที่/เวลา":     _to_bkk(r.get("created_at") or ""),
            "ลูกค้า":          (r.get("customers") or {}).get("name", ""),
            "COD":             float(r.get("cod_amount") or 0),
            "💸":              _cod_status(r),
            "💰 เทียบยอด":     _billing_check(r),
            "สถานะส่ง":        (_delivery_icon(r.get("delivery_status") or "") + " " +
                                (r.get("delivery_status") or "")).strip(),
            "🔗":              (f"https://app.iship.cloud/tracking?track={r['tracking_no']}"
                               if r.get("tracking_no") else ""),
            "ผู้รับ":           r.get("recipient_name", ""),
            "เบอร์":            r.get("phone", ""),
            "รายการ":          _items_str(r.get("items")),
            "ขนส่ง":           r.get("carrier", ""),
            "Tracking":        r.get("tracking_no", "") or "",
            "หมายเหตุ":        r.get("notes", ""),
            "บ้านเลขที่/ถนน":  r.get("address_line", ""),
            "ตำบล":            r.get("district", ""),
            "อำเภอ":           r.get("amphure", ""),
            "จังหวัด":         r.get("province", ""),
            "รหัสปณ.":         r.get("postal_code", ""),
        } for r in _sh_all])

        _sh_edit = st.data_editor(
            _sh_df,
            hide_index=True, width="content", key="sh_hist_tbl",
            disabled=["แหล่ง","วันที่/เวลา","ลูกค้า","ผู้รับ","เบอร์",
                      "บ้านเลขที่/ถนน","ตำบล","อำเภอ","จังหวัด","รหัสปณ.",
                      "รายการ","ขนส่ง","COD","💸","💰 เทียบยอด","สถานะส่ง","🔗","หมายเหตุ"],
            column_config={
                "ลบ":       st.column_config.CheckboxColumn("ลบ", default=False, width=45),
                "📤":       st.column_config.CheckboxColumn("📤", default=False, width=45,
                                help="เลือกเพื่อส่ง iShip ใหม่"),
                "แหล่ง":    st.column_config.TextColumn("แหล่ง", width=50,
                                help="🛒 = บันทึกขาย  📦 = ส่งของ"),
                "COD":      st.column_config.NumberColumn("COD", format="%,.0f", width=75),
                "💸":       st.column_config.TextColumn("💸", width=45),
                "💰 เทียบยอด": st.column_config.TextColumn("💰 เทียบยอด", width=90,
                                help="เทียบยอดที่ขนส่งหักจริงกับราคาที่เราประเมินไว้ (=ราคาที่คิดลูกค้าด้วย "
                                     "เพราะบันทึกขาย/ส่งของคิดลูกค้าตามราคาขนส่งจริงตรงๆ ไม่มีบวกเพิ่ม) "
                                     "? = ไม่มีราคาประเมินไว้ให้เทียบ  ⏳ = iShip ยังไม่ตีราคาจริงมา  "
                                     "+ = เก็บลูกค้าไว้มากกว่าที่ขนส่งคิดจริง (กำไร)  "
                                     "❗- = เก็บลูกค้าไม่พอ ขนส่งคิดแพงกว่า (ขาดทุนค่าส่ง)"),
                "สถานะส่ง": st.column_config.TextColumn("สถานะส่ง", width=130),
                "Tracking": st.column_config.TextColumn("Tracking", width=110),
                "🔗":       st.column_config.LinkColumn("🔗", width=40, display_text="🔗"),
                "บ้านเลขที่/ถนน": st.column_config.TextColumn("บ้านเลขที่/ถนน", width=140),
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
                            st.iframe(
                                f'<a id="_lbl" href="{_pr_result["url"]}" target="_blank" '
                                f'style="display:inline-block;padding:8px 24px;background:#00A86B;color:#fff;'
                                f'border-radius:8px;text-decoration:none;font-size:16px">'
                                f'🖨️ กดที่นี่เพื่อปริ้น</a>'
                                f'<script>document.getElementById("_lbl").click()</script>',
                                height=50,
                            )
                        else:
                            st.warning(f"⚠️ {_pr_result.get('error','หา order ไม่ได้')}")

        # ── ปริ้นใบปะหน้าซ้ำ (รายการที่บันทึกแบบ manual — ไม่ผ่าน iShip) ──
        _pr_manual_rows = [r for r in _sh_all if r.get("source") == "manual"]
        if _pr_manual_rows:
            with st.expander("🖨️ ปริ้นใบปะหน้าซ้ำ (ขนส่งที่ไม่ผ่าน iShip)"):
                _pr_m_labels = [
                    f"{_to_bkk(r.get('created_at') or '')} · {r.get('recipient_name','')} · {r.get('carrier','')}"
                    for r in _pr_manual_rows
                ]
                _pr_m_sel = st.selectbox("เลือกรายการ", _pr_m_labels, key="sh_print_manual_sel")
                if st.button("🖨️ ปริ้นซ้ำ", key="sh_print_manual_btn", type="primary"):
                    _pr_m_row = _pr_manual_rows[_pr_m_labels.index(_pr_m_sel)]
                    _src   = iship_api._src()
                    _notes = _pr_m_row.get("notes") or ""
                    _box_rows = []
                    _bm = re.search(r"\[กล่อง:\s*(.*?)\]", _notes)
                    if _bm:
                        for _part in _bm.group(1).split(";"):
                            _pm = re.match(r"\s*(\d+)x(\d+)x(\d+)cm\s+([\d.]+)kg\s+x(\d+)", _part)
                            if _pm:
                                _l, _w, _h, _wt, _qty = _pm.groups()
                                _box_rows.append({"l": int(_l), "w": int(_w), "h": int(_h),
                                                   "weight_kg": float(_wt), "qty": int(_qty)})
                    _extra_notes = _notes.split("]", 1)[1].strip() if "]" in _notes else ""
                    _total_boxes = sum(r["qty"] for r in _box_rows)
                    _box_rows_html = "".join(
                        f"<tr><td>{r['l']}×{r['w']}×{r['h']} ซม.</td>"
                        f"<td style='text-align:center'>{r['weight_kg']:.2f} kg</td>"
                        f"<td style='text-align:center'>{r['qty']}</td></tr>"
                        for r in _box_rows
                    )
                    _cod_amt  = float(_pr_m_row.get("cod_amount") or 0)
                    _cod_line = f"&nbsp;|&nbsp; <b>COD:</b> {_cod_amt:,.0f} ฿" if _cod_amt > 0 else ""
                    _notes_line = f'<div class="section"><b>หมายเหตุ:</b> {_extra_notes}</div>' if _extra_notes else ""
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
    <div><h1>ใบปะหน้า — {_pr_m_row.get('carrier','')}</h1></div>
    <div class="header-right">วันที่: {date.today().strftime('%d/%m/%Y')}</div>
</div>
<div class="section"><b>ผู้ส่ง:</b> {_src.get('ISHIP_SRC_NAME','')} · โทร. {_src.get('ISHIP_SRC_PHONE','')}<br>
{_src.get('ISHIP_SRC_ADDRESS','')} {_src.get('ISHIP_SRC_DISTRICT','')} {_src.get('ISHIP_SRC_AMPHURE','')} {_src.get('ISHIP_SRC_PROVINCE','')} {_src.get('ISHIP_SRC_ZIPCODE','')}</div>
<div class="section"><b>ผู้รับ:</b> {_pr_m_row.get('recipient_name','')} · โทร. {_pr_m_row.get('phone','')}<br>
{_pr_m_row.get('address_line','')} {_pr_m_row.get('district','')} {_pr_m_row.get('amphure','')} {_pr_m_row.get('province','')} {_pr_m_row.get('postal_code','')}</div>
<div class="section"><b>รายการกล่อง:</b>
<table><tr><th>ขนาด</th><th>น้ำหนัก/กล่อง</th><th>จำนวน</th></tr>{_box_rows_html}</table>
รวม {_total_boxes} กล่อง {_cod_line}</div>
{_notes_line}
</body></html>"""
                    st.iframe(_label_html, height=600)

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
            _rs_w_max = max(100.0, _rs_w_def)
            _rs_w   = st.number_input("น้ำหนักรวมกล่อง (kg)", 0.1, _rs_w_max, _rs_w_def, 0.1, key=f"sh_resend_w_{_rs_i}")
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
