"""UI สำหรับแท็บการเงิน — แยกจาก app.py"""
import io
import uuid

import streamlit as st
import pandas as pd
from datetime import date

import database as db
import iship_api


def render():
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

    # ── สรุปภาษีซื้อ / ภาษีขาย ───────────────────────────────────────────────
    with st.expander("🧾 สรุปภาษีซื้อ / ภาษีขาย", expanded=False):
        _tax_df = db.get_finance_df()
        if _tax_df.empty:
            st.info("ยังไม่มีข้อมูล")
        else:
            _tax_df["entry_date"] = pd.to_datetime(_tax_df["entry_date"])
            _min_m = _tax_df["entry_date"].dt.to_period("M").min()
            _max_m = _tax_df["entry_date"].dt.to_period("M").max()
            _months = pd.period_range(_min_m, _max_m, freq="M")
            _month_labels = [str(m) for m in _months]
            tc1, tc2 = st.columns(2)
            _sel_from = tc1.selectbox("ตั้งแต่เดือน", _month_labels, index=len(_month_labels)-1, key="tax_from")
            _sel_to   = tc2.selectbox("ถึงเดือน",     _month_labels, index=len(_month_labels)-1, key="tax_to")

            _mask = (
                (_tax_df["entry_date"].dt.to_period("M") >= pd.Period(_sel_from, "M")) &
                (_tax_df["entry_date"].dt.to_period("M") <= pd.Period(_sel_to, "M"))
            )
            _tdf = _tax_df[_mask]

            _sales_vat    = float(_tdf["sales_amount"].sum())
            _sales_ex_vat = _sales_vat / 1.07
            _output_vat   = _sales_vat - _sales_ex_vat
            _po_ex_vat    = float(_tdf["po_amount"].sum())
            _input_vat    = _po_ex_vat * 0.07
            _net_vat      = _output_vat - _input_vat

            tv1, tv2 = st.columns(2)
            with tv1:
                st.markdown("**📤 ภาษีขาย (Output VAT)**")
                st.metric("ยอดขาย รวม VAT",    f"{_sales_vat:,.2f} ฿")
                st.metric("ยอดขาย ไม่รวม VAT", f"{_sales_ex_vat:,.2f} ฿")
                st.metric("ภาษีขาย 7%",        f"{_output_vat:,.2f} ฿")
            with tv2:
                st.markdown("**📥 ภาษีซื้อ (Input VAT)**")
                st.metric("ยอดซื้อ ไม่รวม VAT", f"{_po_ex_vat:,.2f} ฿")
                st.metric("ภาษีซื้อ 7%",        f"{_input_vat:,.2f} ฿")
                _color = "normal" if _net_vat >= 0 else "inverse"
                st.metric("VAT ต้องชำระสุทธิ",
                           f"{abs(_net_vat):,.2f} ฿",
                           delta="ต้องจ่าย" if _net_vat >= 0 else "ขอคืนได้",
                           delta_color=_color)

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

    st.divider()

    # ── ตรวจสอบสถานะ COD Transfer ────────────────────────────────────────────
    with st.expander("🔍 ตรวจสอบสถานะ COD (iShip)", expanded=False):
        st.caption("ดึงข้อมูลจาก iShip แล้ว match กับ tracking ใน shipments table")
        if st.button("🔄 ดึงข้อมูล COD Transfer", key="cod_fetch"):
            with st.spinner("กำลัง login และดึงข้อมูล..."):
                _cod_result = iship_api.get_cod_transfers(days_back=60)
            if _cod_result.get("error"):
                st.error(f"❌ {_cod_result['error']}")
            _cod_map = _cod_result.get("transfers", {})
            if _cod_map:
                st.success(f"✅ พบ {len(_cod_map)} tracking ที่โอนแล้ว")
                _cod_df = pd.DataFrame([
                    {"tracking": tn, "วันที่โอน": v["date"], "ยอด COD": v["cod_amount"],
                     "ยอดสุทธิ": v["net"], "สถานะ": v["status"], "WD": v["wd_id"]}
                    for tn, v in _cod_map.items()
                ])
                st.dataframe(_cod_df, use_container_width=True, hide_index=True)
            elif not _cod_result.get("error"):
                st.info("ไม่พบรายการ COD ใน 60 วันที่ผ่านมา")
                st.json(_cod_result.get("_debug", {}))
