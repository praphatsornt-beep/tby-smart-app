"""UI สำหรับ sub-tab 📮 COD ของ 🗂️ รายละเอียดบิล — ตารางแยกดูยอด COD ทั้งหมด
(รอรับโอน + รับโอนแล้ว) พร้อมสถานะเปิดบิล แยกจาก tuple:sale (Shopee/Lazada
อยู่คนละที่). ตั้งใจไม่พึ่งตาราง shipments เลย (pay_status/bill_status อยู่ใน
transactions โดยตรงอยู่แล้ว) — เพิ่มหลังเหตุการณ์ตาราง shipments โดนรันสคริปต์
ผิดจนข้อมูลหาย 2026-07-21 ผู้ใช้เลยอยากมีมุมมอง COD ที่ไม่ต้องพึ่งตารางนั้น"""
import streamlit as st

import database as db


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

    _show_cols = ["วันที่", "ลูกค้า", "รหัส", "สินค้า", "สั่ง", "ยอดรวม",
                  "เลขที่บิล", "สถานะบิล", "สถานะจ่าย"]
    st.dataframe(
        show_df[_show_cols].style.format({"ยอดรวม": "{:,.2f}"}),
        hide_index=True, width="stretch",
        column_config={
            "สถานะบิล": st.column_config.TextColumn("สถานะเปิดบิล"),
        },
    )
