"""UI สำหรับแท็บ 🛒 E-commerce (Shopee) — แยกจาก app.py

เดิมใช้ Shopee Open API (OAuth) แต่ Shopee เปิด Open API ให้เฉพาะร้านระดับ
Managed Seller เท่านั้น (ร้านทั่วไปสมัครไม่ได้ ยืนยันแล้ว 2026-07-15) จึงเปลี่ยน
มาใช้การอัปโหลดรายงาน export จาก Shopee Seller Centre แทน (ดู shopee_import.py):
- "Order.all" (คำสั่งซื้อ > Export) — รายการสินค้าต่อออเดอร์ + สถานะ + เลขพัสดุ
- "Income" (การเงิน > รายได้ของฉัน > Export) — ยอดโอนสุทธิจริงต่อออเดอร์
"""
import uuid

import streamlit as st
import pandas as pd
from datetime import date

import database as db
import shopee_import


def render():
    # ── Section 1: จัดการรายชื่อร้าน ────────────────────────────────────
    st.markdown("### 1. ร้านค้า")
    shops = db.get_ecommerce_shops()
    shop_names = [s["shop_name"] for s in shops]
    with st.expander("➕ เพิ่มร้านใหม่", expanded=not shops):
        _new_shop = st.text_input("ชื่อร้าน", key="ecom_new_shop_name", placeholder="เช่น Shopee ร้าน 1")
        if st.button("บันทึกร้าน", key="ecom_add_shop") and _new_shop.strip():
            db.upsert_ecommerce_shop({
                "id": str(uuid.uuid4()), "platform": "shopee",
                "shop_name": _new_shop.strip(), "shop_id": 0,
            })
            st.success(f"✅ เพิ่มร้าน {_new_shop.strip()} แล้ว")
            st.rerun()
    if shops:
        st.dataframe(pd.DataFrame([{"ชื่อร้าน": s["shop_name"]} for s in shops]),
                      width="stretch", hide_index=True)

    st.divider()

    # ── Section 2: อัปโหลดรายงาน ─────────────────────────────────────────
    st.markdown("### 2. อัปโหลดรายงานจาก Shopee Seller Centre")
    if not shops:
        st.info("เพิ่มร้านก่อนครับ (ข้อ 1)")
    else:
        coverage_df = db.get_ecommerce_import_coverage_df()
        if not coverage_df.empty:
            st.caption("ข้อมูลที่นำเข้าแล้วครอบคลุมช่วงวันไหนบ้าง (เช็คก่อนอัปโหลดเพิ่ม กันช่วงขาด/ซ้ำ)")
            st.dataframe(coverage_df, width="stretch", hide_index=True)
        oc1, oc2 = st.columns(2)
        with oc1:
            st.markdown("**📦 รายงานคำสั่งซื้อ** (คำสั่งซื้อ → Export)")
            _order_shop = st.selectbox("ร้าน", shop_names, key="ecom_order_shop")
            _order_file = st.file_uploader("ไฟล์ Order.all...xlsx", type=["xlsx"], key="ecom_order_file")
            if _order_file and st.button("นำเข้ารายงานคำสั่งซื้อ", key="ecom_import_orders", type="primary"):
                with st.spinner("กำลังอ่านไฟล์..."):
                    rows = shopee_import.parse_order_export(_order_file, _order_shop)
                    if rows:
                        prod_map = db.get_ecommerce_product_map()
                        for r in rows:
                            _m = prod_map.get(("shopee", r["item_id_platform"]))
                            r["product_id"] = _m["product_id"] if _m else None
                        db.upsert_ecommerce_sales(rows)
                        _n_updated = db.allocate_ecommerce_order_income()
                        st.success(f"✅ นำเข้า {len(rows)} รายการ (แบ่งยอดเงินสุทธิให้ {_n_updated} รายการ)")
                    else:
                        st.warning("ไม่พบข้อมูลในไฟล์")
                st.rerun()

        with oc2:
            st.markdown("**💰 รายงานรายได้** (การเงิน → รายได้ของฉัน → Export)")
            _income_file = st.file_uploader("ไฟล์ Income...xlsx", type=["xlsx"], key="ecom_income_file")
            if _income_file and st.button("นำเข้ารายงานรายได้", key="ecom_import_income", type="primary"):
                with st.spinner("กำลังอ่านไฟล์..."):
                    rows, _detected_shop = shopee_import.parse_income_export(_income_file)
                    if rows:
                        db.upsert_ecommerce_order_income(rows)
                        _n_updated = db.allocate_ecommerce_order_income()
                        st.success(f"✅ นำเข้า {len(rows)} ออเดอร์ (ร้าน {_detected_shop}) — แบ่งยอดเงินสุทธิให้ {_n_updated} รายการ")
                    else:
                        st.warning("ไม่พบข้อมูลในไฟล์")
                st.rerun()

    st.divider()

    # ── Section 3: ยอดขาย E-commerce (รายการดิบ) ───────────────────────
    st.markdown("### 3. ยอดขาย E-commerce")
    ev1, ev2 = st.columns(2)
    view_from = ev1.date_input("จาก", value=date.today().replace(day=1), key="ecom_vfrom")
    view_to   = ev2.date_input("ถึง",  value=date.today(), key="ecom_vto")
    ecom_df   = db.get_ecommerce_sales_df(str(view_from), str(view_to))
    if ecom_df.empty:
        st.info("ยังไม่มีข้อมูล — อัปโหลดรายงานคำสั่งซื้อก่อนครับ (ข้อ 2)")
    else:
        st.dataframe(ecom_df.style.format({"ยอด": "{:,.2f}"}), width="stretch", hide_index=True)
        st.caption(f"รวม {ecom_df['จำนวน'].sum():,} ชิ้น | ยอดรวม {ecom_df['ยอด'].sum():,.2f} บาท")

    st.divider()

    # ── Section 4: กำไรจริงต่อสินค้า (เฉพาะที่ขายผ่าน Shopee) ──────────
    st.markdown("### 4. กำไรจริง (ต่อสินค้า)")
    st.caption("กำไร = ยอดเงินที่ Shopee โอนเข้าจริง (หลังหักค่าธรรมเนียม/ค่าส่ง/ภาษีแล้ว) − ต้นทุน × จำนวนที่ขาย")
    mc1, mc2, mc3 = st.columns([1, 1, 1])
    margin_from = mc1.date_input("จาก", value=date.today().replace(day=1), key="ecom_margin_from")
    margin_to   = mc2.date_input("ถึง",  value=date.today(), key="ecom_margin_to")
    margin_warn_pct = mc3.number_input("เตือนถ้ากำไร < กี่ % ของยอดโอน", min_value=0, max_value=100, value=10, key="ecom_margin_warn_pct")

    margin_df, pending_qty = db.get_ecommerce_product_margin_df(str(margin_from), str(margin_to))
    if pending_qty:
        st.info(f"ℹ️ มี {pending_qty:,} ชิ้น ที่ขายแล้วแต่ยังไม่มีรายงานยอดโอน (Income) มายืนยัน — ยังไม่รวมในตารางนี้ (อัปโหลดรายงาน Income ของช่วงที่ครอบคลุมออเดอร์เหล่านี้เพิ่มเพื่อให้เห็นครบ)")
    if margin_df.empty:
        st.info("ยังไม่มีข้อมูล หรือยังไม่ได้ map สินค้า (ดูข้อ 6)")
    else:
        _total_profit = margin_df.loc[margin_df["กำไรรวม"] > 0, "กำไรรวม"].sum()
        _total_loss   = margin_df.loc[margin_df["กำไรรวม"] < 0, "กำไรรวม"].sum()
        _net_total    = margin_df["กำไรรวม"].sum()
        _total_qty    = margin_df["ขายผ่าน Shopee (ชิ้น)"].sum()
        _total_pv     = margin_df["PV"].sum()
        _sm1, _sm2, _sm3, _sm4, _sm5 = st.columns(5)
        _sm1.metric("กำไรรวม", f"{_total_profit:,.0f} ฿")
        _sm2.metric("ขาดทุนรวม", f"{_total_loss:,.0f} ฿")
        _sm3.metric("สุทธิ", f"{_net_total:,.0f} ฿")
        _sm4.metric("ขายรวม", f"{_total_qty:,.0f} ชิ้น")
        _sm5.metric("PV รวม", f"{_total_pv:,.0f}")

        def _flag(row):
            if row["กำไรรวม"] < 0:
                return "🔴 ขาดทุน"
            if row["ยอดเงินที่ได้รับจริง"] > 0 and row["กำไรรวม"] / row["ยอดเงินที่ได้รับจริง"] * 100 < margin_warn_pct:
                return "🟡 กำไรต่ำ"
            return "✅"
        margin_df.insert(0, "สถานะ", margin_df.apply(_flag, axis=1))
        st.dataframe(
            margin_df.style.format({
                "ต้นทุน/ชิ้น": "{:,.2f}", "ยอดเงินที่ได้รับจริง": "{:,.2f}",
                "กำไรรวม": "{:,.2f}", "กำไร/ชิ้น": "{:,.2f}", "PV": "{:,.2f}",
                "ราคาตั้งขายที่ควรตั้ง (คุ้มทุน)": "{:,.2f}",
            }),
            width="stretch", hide_index=True,
        )
        _n_loss = (margin_df["กำไรรวม"] < 0).sum()
        if _n_loss:
            st.warning(f"⚠️ มี {_n_loss} สินค้าที่ขาดทุนในช่วงนี้ — ดูคอลัมน์ \"ราคาตั้งขายที่ควรตั้ง (คุ้มทุน)\" เพื่อดูว่าควรปรับราคาขายเท่าไหร่ถึงจะไม่ขาดทุน (คำนวณจากอัตราหักค่าธรรมเนียม Shopee เฉลี่ยของสินค้านั้น)")

    st.divider()

    # ── Section 5: ออเดอร์ที่กำไรผิดปกติ (พร้อมเลขที่ออเดอร์) ──────────
    st.markdown("### 5. ออเดอร์ที่กำไรผิดปกติ")
    st.caption("รายออเดอร์ (ไม่ใช่สรุปรวมสินค้า) — ใช้ไล่เช็คว่าออเดอร์ไหนกันแน่ที่ขาดทุน/กำไรต่ำ")
    ac1, ac2, ac3 = st.columns([1, 1, 1])
    anomaly_from = ac1.date_input("จาก", value=date.today().replace(day=1), key="ecom_anomaly_from")
    anomaly_to   = ac2.date_input("ถึง",  value=date.today(), key="ecom_anomaly_to")
    anomaly_warn_pct = ac3.number_input("เตือนถ้ากำไร < กี่ % ของยอดโอน", min_value=0, max_value=100, value=10, key="ecom_anomaly_warn_pct")
    anomaly_df = db.get_ecommerce_order_anomaly_df(str(anomaly_from), str(anomaly_to), warn_pct=anomaly_warn_pct)
    if anomaly_df.empty:
        st.success("✅ ไม่พบออเดอร์ที่กำไรผิดปกติในช่วงนี้")
    else:
        st.warning(f"⚠️ พบ {len(anomaly_df)} ออเดอร์ที่กำไรผิดปกติ")
        st.dataframe(
            anomaly_df.style.format({
                "ต้นทุนรวม": "{:,.2f}", "ยอดเงินที่ได้รับจริง": "{:,.2f}",
                "กำไร": "{:,.2f}", "กำไร %": "{:,.1f}",
            }),
            width="stretch", hide_index=True,
        )

    st.divider()

    # ── Section 6: ออเดอร์คืนสินค้า/ยกเลิก + tracking ───────────────────
    st.markdown("### 6. ออเดอร์คืนสินค้า/ยกเลิก + ติดตามพัสดุ")
    problem_df = db.get_ecommerce_problem_orders_df()
    if problem_df.empty:
        st.success("✅ ไม่มีออเดอร์คืนสินค้า/ยกเลิกที่บันทึกไว้")
    else:
        st.dataframe(problem_df, width="stretch", hide_index=True)

    st.divider()

    # ── Section 7: ตรวจสอบค่าส่งเกิน ────────────────────────────────────
    st.markdown("### 7. ตรวจสอบค่าส่งเกิน")
    st.caption(
        "Shopee ประเมินค่าส่ง (ผู้ซื้อจ่าย + Shopee ออกให้) ไว้ล่วงหน้าตอนสั่งซื้อ "
        "แต่พอขนส่งชั่งพัสดุจริงแล้วแพงกว่าที่ประเมิน ส่วนต่างจะถูกหักเพิ่มจากร้าน "
        "เงียบๆ — ใช้ตัวเลขที่ Shopee รายงานมาโดยตรง ไม่ได้เทียบกับน้ำหนักสินค้าที่ "
        "คำนวณเอง (ช่วงวันที่ = วันที่โอนเงิน ไม่ใช่วันที่สั่งซื้อ)"
    )
    sc1, sc2, sc3 = st.columns(3)
    ship_from = sc1.date_input("จาก", value=date.today().replace(day=1), key="ecom_ship_from")
    ship_to   = sc2.date_input("ถึง",  value=date.today(), key="ecom_ship_to")
    ship_threshold = sc3.number_input("เกณฑ์ส่วนต่าง (บาท)", min_value=0.0, value=0.0, step=5.0, key="ecom_ship_threshold")
    overcharge_df = db.get_ecommerce_shipping_overcharge_df(str(ship_from), str(ship_to), overcharge_threshold=ship_threshold)
    if overcharge_df.empty:
        st.success("✅ ไม่พบออเดอร์ที่ค่าส่งเกินเกณฑ์ในช่วงนี้")
    else:
        st.warning(f"⚠️ พบ {len(overcharge_df)} ออเดอร์ที่ค่าส่งเกินเกณฑ์")
        st.dataframe(overcharge_df, width="stretch", hide_index=True)

    st.divider()

    # ── Section 8: Map สินค้า Shopee → ระบบ ────────────────────────────
    st.markdown("### 8. Map สินค้า Shopee → ระบบ")
    unmapped_rows = db.get_unmapped_ecommerce_items("shopee")

    if unmapped_rows:
        st.warning(f"มี {len(unmapped_rows)} รายการที่ยังไม่ได้ map")
        all_products = db.get_products()
        prod_opts    = {"— ยังไม่ map —": None} | {p["name"]: p["id"] for p in all_products}
        st.caption(
            "สินค้าบางตัวขายไม่เท่ากับ 1 หน่วยสต็อกในระบบ เช่น ขายเป็นแพ็ครวม "
            "(ยาสีฟัน 3 หลอด) หรือแบ่งขายจากแพ็คใหญ่ (แบ่งขาย 30 ซอง จากแพ็ค 180 ซอง) "
            "— กรอก 2 ช่องขวาให้ตรงความจริง ระบบจะคำนวณสัดส่วนให้เอง"
        )
        map_rows     = []
        for i, row in enumerate(unmapped_rows):
            mc1, mc2, mc3, mc4 = st.columns([2, 2, 1, 1])
            _label = row["item_name"] or row["item_id"]
            mc1.write(f"**{_label}**\n\n`{row['item_id']}` ({row['shop_name']})")
            sel = mc2.selectbox("สินค้าในระบบ", list(prod_opts.keys()), key=f"map_{i}")
            sold_qty = mc3.number_input(
                "ขายจริงกี่หน่วย/ออเดอร์", min_value=1, value=1, step=1, key=f"map_sold_{i}",
                help="เช่น ยาสีฟัน 3 หลอด ใส่ 3, แบ่งขาย 30 ซอง ใส่ 30, ปกติ (1 ต่อ 1) ใส่ 1",
            )
            pack_size = mc4.number_input(
                "1 หน่วยสต็อกในระบบ = กี่หน่วย", min_value=1, value=1, step=1, key=f"map_pack_{i}",
                help="ดูจากชื่อสินค้าที่เลือก เช่น 'บียางค์ 180' ใส่ 180, ถ้าสินค้าปกติ (ไม่แบ่งขาย) ใส่ 1",
            )
            ratio = sold_qty / pack_size
            if ratio != 1:
                mc1.caption(f"→ เทียบเท่า {ratio:.4f} หน่วยสต็อก/ออเดอร์")
            if prod_opts[sel]:
                map_rows.append({
                    "id": str(uuid.uuid4()),
                    "platform": "shopee",
                    "platform_item_id": row["item_id"],
                    "product_id": prod_opts[sel],
                    "platform_product_name": row["item_name"] or row["item_id"],
                    "units_per_pack": ratio,
                })
        if map_rows and st.button("💾 บันทึก Mapping", type="primary", key="ecom_map_save"):
            db.upsert_ecommerce_product_map(map_rows)
            db.apply_ecommerce_product_map(map_rows)
            st.success(f"✅ Map แล้ว {len(map_rows)} รายการ")
            st.rerun()
    else:
        st.success("✅ สินค้าทุกรายการ map แล้ว")
