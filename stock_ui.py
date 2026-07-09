"""UI สำหรับแท็บ 📦 สต๊อก — แยกจาก app.py"""
import uuid

import streamlit as st
import pandas as pd
from datetime import date

import database as db


_T6_TABS = ["📦 สต๊อก", "📋 ของฝาก"]


def render():
    _hdr_title, _hdr_tabs = st.columns([2, 5])
    with _hdr_title:
        st.markdown("### 📦 สต๊อก")
    with _hdr_tabs:
        try:
            _t6_active = st.pills("", _T6_TABS, key="_t6_active_sub", label_visibility="collapsed") or _T6_TABS[0]
        except AttributeError:
            _t6_active = st.radio("", _T6_TABS, horizontal=True, key="_t6_active_sub", label_visibility="collapsed")

    if _t6_active == "📋 ของฝาก":
        st.subheader("ของที่ลูกค้าฝากไว้")
        _dep_src = db.get_outstanding_df()
        if _dep_src.empty:
            st.info("ไม่มีรายการฝากของ")
        else:
            _dep_df = _dep_src[
                (_dep_src["สถานะบิล"] == "เปิดบิลแล้ว") &
                (_dep_src["ค้างรับ"] > 0)
            ]
            if _dep_df.empty:
                st.info("ไม่มีรายการฝากของ")
            else:
                _total_dep = int(_dep_df["ค้างรับ"].sum())
                _total_cust = _dep_df["ลูกค้า"].nunique()
                _total_prod = _dep_df["สินค้า"].nunique()
                dm1, dm2, dm3 = st.columns(3)
                dm1.metric("ค้างรับรวม", f"{_total_dep} ชิ้น")
                dm2.metric("จำนวนลูกค้า", f"{_total_cust} คน")
                dm3.metric("จำนวนสินค้า", f"{_total_prod} รายการ")
                st.divider()

                # สรุปต่อลูกค้า — ลูกค้าที่ยังรับของไม่ครบ
                _cust_sum = (_dep_df.groupby("ลูกค้า", as_index=False)
                              .agg(ค้างรับรวม=("ค้างรับ", "sum"),
                                   จำนวนสินค้า=("สินค้า", "nunique"),
                                   จำนวนบิล=("เลขที่บิล", "nunique"))
                              .sort_values("ค้างรับรวม", ascending=False))
                st.markdown("**สรุปต่อลูกค้า — ลูกค้าที่ยังรับของไม่ครบ**")
                st.dataframe(_cust_sum, hide_index=True, use_container_width=True)
                st.divider()

                # สรุปต่อสินค้า
                _prod_sum = (_dep_df.groupby(["รหัส","สินค้า"], as_index=False)["ค้างรับ"]
                              .sum().rename(columns={"ค้างรับ": "ค้างรับรวม"})
                              .sort_values("ค้างรับรวม", ascending=False))
                st.markdown("**สรุปต่อสินค้า**")
                st.dataframe(_prod_sum, hide_index=True, use_container_width=True)
                st.divider()

                # รายละเอียด — เลือกดูแยกตามลูกค้า หรือแยกตามสินค้า
                st.markdown("**รายละเอียด**")
                _dep_view = st.radio("แยกตาม", ["ลูกค้า", "สินค้า"], horizontal=True,
                                      key="_dep_detail_view", label_visibility="collapsed")
                if _dep_view == "ลูกค้า":
                    for _cname, _cgrp in _dep_df.groupby("ลูกค้า"):
                        _ctotal = int(_cgrp["ค้างรับ"].sum())
                        with st.expander(f"**{_cname}** — ค้างรับรวม {_ctotal} ชิ้น ({_cgrp['สินค้า'].nunique()} รายการสินค้า)"):
                            _det = _cgrp[["สินค้า","เลขที่บิล","วันที่","ค้างรับ"]].reset_index(drop=True)
                            st.dataframe(_det, hide_index=True, use_container_width=True)
                else:
                    for _pname, _pgrp in _dep_df.groupby("สินค้า"):
                        _ptotal = int(_pgrp["ค้างรับ"].sum())
                        with st.expander(f"**{_pname}** — รวม {_ptotal} ชิ้น  ({_pgrp['ลูกค้า'].nunique()} คน)"):
                            _det = _pgrp[["ลูกค้า","เลขที่บิล","วันที่","ค้างรับ"]].reset_index(drop=True)
                            st.dataframe(_det, hide_index=True, use_container_width=True)

    elif _t6_active == "📦 สต๊อก":
        st.subheader("สรุปสต๊อก")

        products = db.get_products()
        if not products:
            st.warning("⚠️ ยังไม่มีข้อมูลสินค้า")
        else:
            latest_counts   = db.get_latest_stock_counts()
            unbilled_qty    = db.get_unbilled_received_qty_by_product()
            billed_not_rcv  = db.get_billed_not_received_qty_by_product()

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
                    "รหัส":     pid,
                    "สินค้า":   p["name"],
                    "คอม":      qty_system,
                    "นับจริง":  qty_physical,
                    "เบิก":     qty_unbilled,
                    "ฝาก":      qty_billed_wait,
                    "ส่วนต่าง": diff,
                    "สถานะ":   "🔴 เกิน" if diff > 0 else ("🟡 ขาด" if diff < 0 else "✅ ตรง"),
                })

            stock_df = pd.DataFrame(stock_rows)

            with st.form("stock_form"):
                cnt_date = st.date_input("วันที่นับ", value=date.today(), key="stock_cnt_date")
                edited_stock = st.data_editor(
                    stock_df,
                    use_container_width=True,
                    hide_index=True,
                    disabled=["รหัส", "สินค้า", "เบิก", "ฝาก", "ส่วนต่าง", "สถานะ"],
                    column_config={
                        "คอม":      st.column_config.NumberColumn("คอม",     min_value=0, step=1, format="%d"),
                        "นับจริง":  st.column_config.NumberColumn("นับจริง", min_value=0, step=1, format="%d"),
                        "เบิก":     st.column_config.NumberColumn("เบิก",    format="%d"),
                        "ฝาก":      st.column_config.NumberColumn("ฝาก",     format="%d"),
                        "ส่วนต่าง": st.column_config.NumberColumn("ส่วนต่าง", format="%d"),
                    },
                    key="stock_editor",
                )
                st.caption("เบิก = เบิกของไปยังไม่มีบิล  |  ฝาก = เปิดบิลแล้วยังไม่รับของ  |  ส่วนต่าง = คอม − นับจริง + ฝาก − เบิก")
                _stock_submitted = st.form_submit_button("💾 บันทึกการนับสต๊อก", use_container_width=True, type="primary")

            price_by_name = {p["name"]: float(p.get("price") or 0) for p in products}
            pv_by_name    = {p["name"]: float(p.get("points_per_unit") or 0) for p in products}
            _sp = stock_df["สินค้า"].map(price_by_name).fillna(0)
            _sv = stock_df["สินค้า"].map(pv_by_name).fillna(0)
            total_kom_amt  = (stock_df["คอม"].astype(float)      * _sp).sum()
            total_real_amt = (stock_df["นับจริง"].astype(float)  * _sp).sum()
            total_pv       = (stock_df["ส่วนต่าง"].astype(float) * _sv).sum()
            diff_amt       = total_kom_amt - total_real_amt
            sm1, sm2, sm3, sm4 = st.columns(4)
            sm1.metric("📦 ยอดในคอม (฿)", f"{total_kom_amt:,.0f}")
            sm2.metric("🔍 ยอดจริง (฿)",  f"{total_real_amt:,.0f}")
            sm3.metric("⚖️ ส่วนต่าง (฿)", f"{diff_amt:,.0f}", delta=f"{diff_amt:,.0f}" if diff_amt != 0 else None)
            sm4.metric("⭐ คะแนนที่คีย์ได้", f"{total_pv:,.0f} PV")
            st.divider()

            if _stock_submitted:
                saved = 0
                errors = []
                for pid, (_, row) in zip(product_ids, edited_stock.iterrows()):
                    new_sys  = int(row["คอม"])     if pd.notna(row["คอม"])     else 0
                    new_phys = int(row["นับจริง"]) if pd.notna(row["นับจริง"]) else 0
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
