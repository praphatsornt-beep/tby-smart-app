"""UI สำหรับ sub-tab 📮 COD ของ 🗂️ รายละเอียดบิล — ตารางแยกดูยอด COD ทั้งหมด
(รอรับโอน + รับโอนแล้ว) พร้อมสถานะเปิดบิล แยกจาก Shopee/Lazada. ตั้งใจไม่พึ่ง
ตาราง shipments เลย (pay_status/bill_status อยู่ใน transactions โดยตรงอยู่แล้ว)
— เพิ่มหลังเหตุการณ์ตาราง shipments โดนรันสคริปต์ผิดจนข้อมูลหาย 2026-07-21
ผู้ใช้เลยอยากมีมุมมอง COD ที่ไม่ต้องพึ่งตารางนั้น รวมถึงเปิดบิลได้ตรงนี้เลย"""
import streamlit as st

import database as db

_DISP_COLS = ["วันที่", "ลูกค้า", "รหัส", "สินค้า", "สั่ง", "ยอดรวม", "เลขที่บิล", "สถานะจ่าย"]


def render():
    st.subheader("📮 COD")
    cod_df = db.get_cod_orders_df()
    if cod_df.empty:
        st.info("ไม่มีรายการ COD")
        return

    _pending_df = cod_df[cod_df["สถานะจ่าย"] == "COD"]
    _paid_df    = cod_df[cod_df["สถานะจ่าย"] == "COD จ่ายแล้ว"]
    m1, m2, m3 = st.columns(3)
    m1.metric("รอรับโอน", f"{len(_pending_df)} รายการ", f"{_pending_df['ยอดรวม'].sum():,.0f} ฿")
    m2.metric("รับโอนแล้ว", f"{len(_paid_df)} รายการ", f"{_paid_df['ยอดรวม'].sum():,.0f} ฿")
    m3.metric("รวมทั้งหมด", f"{len(cod_df)} รายการ", f"{cod_df['ยอดรวม'].sum():,.0f} ฿")

    only_pending = st.checkbox("แสดงเฉพาะที่ยังไม่รับโอน", key="cod_only_pending")
    show_df = _pending_df if only_pending else cod_df

    _unbilled_df = show_df[show_df["สถานะบิล"] == "ยังไม่เปิดบิล"].reset_index(drop=True)
    _billed_df   = show_df[show_df["สถานะบิล"] == "เปิดบิลแล้ว"].reset_index(drop=True)

    if not _unbilled_df.empty:
        st.markdown(f"**ยังไม่เปิดบิล ({len(_unbilled_df)} รายการ)** — ติ๊กแล้วกดปุ่มด้านล่างเพื่อเปิดบิล")
        _edit_df = _unbilled_df[["id"] + _DISP_COLS].copy()
        _edit_df.insert(1, "เปิดบิล", False)
        _edited = st.data_editor(
            _edit_df, hide_index=True, width="stretch", key="cod_open_bill_editor",
            column_order=["เปิดบิล"] + _DISP_COLS,
            disabled=_DISP_COLS,
            column_config={
                "เปิดบิล": st.column_config.CheckboxColumn("✅ เปิดบิล", default=False),
                "ยอดรวม": st.column_config.NumberColumn(format="%.2f ฿"),
            },
        )
        _to_open = _edited[_edited["เปิดบิล"]]
        if not _to_open.empty and st.button(f"📄 เปิดบิล {len(_to_open)} รายการที่เลือก", type="primary", key="cod_open_bill_btn"):
            for _, _row in _to_open.iterrows():
                db.open_bill_partial(_row["id"], int(_row["สั่ง"]))
            st.success(f"✅ เปิดบิลแล้ว {len(_to_open)} รายการ")
            st.rerun()
        st.divider()

    if not _billed_df.empty:
        st.markdown(f"**เปิดบิลแล้ว ({len(_billed_df)} รายการ)**")
        st.dataframe(
            _billed_df[_DISP_COLS].style.format({"ยอดรวม": "{:,.2f}"}),
            hide_index=True, width="stretch",
        )
