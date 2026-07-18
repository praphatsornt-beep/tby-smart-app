"""UI สำหรับแท็บ 🛒 E-commerce (Shopee + Lazada) — แยกจาก app.py

เดิมใช้ Shopee Open API (OAuth) แต่ Shopee เปิด Open API ให้เฉพาะร้านระดับ
Managed Seller เท่านั้น (ร้านทั่วไปสมัครไม่ได้ ยืนยันแล้ว 2026-07-15) จึงเปลี่ยน
มาใช้การอัปโหลดรายงาน export จาก Shopee Seller Centre แทน (ดู shopee_import.py):
- "Order.all" (คำสั่งซื้อ > Export) — รายการสินค้าต่อออเดอร์ + สถานะ + เลขพัสดุ
- "Income" (การเงิน > รายได้ของฉัน > Export) — ยอดโอนสุทธิจริงต่อออเดอร์

Lazada (เพิ่ม 2026-07-18) ใช้วิธีอัปโหลดรายงานแบบเดียวกัน แต่ไฟล์เดียวจบ (ดู
lazada_import.py) — "Income Overview" (การเงิน > ใบแจ้งยอดรายได้ > Export) มีทั้ง
รายการสินค้าและยอดเงินสุทธิในไฟล์เดียว ไม่ต้องแยก Order.all/Income เหมือน Shopee
แต่ไม่มีข้อมูลค่าจัดส่งเลย (ฟีเจอร์ "ตรวจสอบค่าส่งเกิน" จึงใช้ได้เฉพาะ Shopee)
`database.py` ทุกฟังก์ชัน E-commerce มีพารามิเตอร์ platform อยู่แล้วรองรับหลาย
แพลตฟอร์มโดยไม่ต้องแก้ schema — ไฟล์นี้แค่ต้อง thread platform ผ่าน UI ให้ครบ"""
import uuid

import streamlit as st
import pandas as pd
from datetime import date

import database as db
import shopee_import
import lazada_import


_ECOM_TABS = ["⚙️ ตั้งค่า/นำเข้าข้อมูล", "💰 ยอดขาย/กำไร", "🔍 ตรวจสอบปัญหา"]
_PLATFORMS = {"shopee": "Shopee", "lazada": "Lazada"}


def render():
    try:
        _ecom_active = st.pills(" ", _ECOM_TABS, key="_ecom_active_sub", default=_ECOM_TABS[0], label_visibility="collapsed") or _ECOM_TABS[0]
    except AttributeError:
        _ecom_active = st.radio(" ", _ECOM_TABS, horizontal=True, key="_ecom_active_sub", label_visibility="collapsed")

    if _ecom_active == _ECOM_TABS[0]:
        _render_setup()
    elif _ecom_active == _ECOM_TABS[1]:
        _render_sales_profit()
    elif _ecom_active == _ECOM_TABS[2]:
        _render_issues()


def _render_setup():
    # ── ร้านค้า ────────────────────────────────────────────────────────
    st.subheader("ร้านค้า")
    shops = db.get_ecommerce_shops()
    shop_names = [s["shop_name"] for s in shops]
    with st.expander("➕ เพิ่มร้านใหม่", expanded=not shops):
        _new_plat = st.selectbox("แพลตฟอร์ม", list(_PLATFORMS.keys()), format_func=lambda p: _PLATFORMS[p], key="ecom_new_shop_platform")
        _new_shop = st.text_input("ชื่อร้าน", key="ecom_new_shop_name", placeholder="เช่น Shopee ร้าน 1")
        if st.button("บันทึกร้าน", key="ecom_add_shop") and _new_shop.strip():
            if _new_shop.strip() in shop_names:
                st.warning(f"⚠️ มีร้านชื่อ {_new_shop.strip()} อยู่แล้ว ไม่เพิ่มซ้ำ")
            else:
                db.upsert_ecommerce_shop({
                    "id": str(uuid.uuid4()), "platform": _new_plat,
                    "shop_name": _new_shop.strip(), "shop_id": 0,
                })
                st.success(f"✅ เพิ่มร้าน {_new_shop.strip()} ({_PLATFORMS[_new_plat]}) แล้ว")
                st.rerun()
    if shops:
        for _s in shops:
            _sc1, _sc2 = st.columns([5, 1])
            _sc1.write(f"{_s['shop_name']}  ·  {_PLATFORMS.get(_s['platform'], _s['platform'])}")
            if _sc2.button("🗑️ ลบ", key=f"ecom_del_shop_{_s['id']}"):
                st.session_state["_ecom_confirm_del_shop"] = _s["id"]
                st.rerun()
        _del_id = st.session_state.get("_ecom_confirm_del_shop")
        if _del_id:
            _del_shop = next((s for s in shops if s["id"] == _del_id), None)
            if _del_shop:
                _has_data = db.shop_has_ecommerce_data(_del_shop["shop_name"], _del_shop["platform"])
                st.warning(
                    f"⚠️ ยืนยันลบร้าน **{_del_shop['shop_name']}**"
                    + (" — ร้านนี้มีข้อมูลขาย/รายได้ผูกอยู่แล้ว ข้อมูลจะยังอยู่ในระบบแต่จะไม่มีชื่อร้านนี้ให้เลือกอัปโหลดเพิ่ม"
                       if _has_data else " (ยังไม่มีข้อมูลขาย/รายได้ผูกอยู่)")
                )
                _cc1, _cc2 = st.columns(2)
                if _cc1.button("✅ ยืนยันลบ", key="ecom_confirm_del_shop_yes"):
                    db.delete_ecommerce_shop(_del_id)
                    del st.session_state["_ecom_confirm_del_shop"]
                    st.success(f"ลบร้าน {_del_shop['shop_name']} แล้ว")
                    st.rerun()
                if _cc2.button("ยกเลิก", key="ecom_confirm_del_shop_no"):
                    del st.session_state["_ecom_confirm_del_shop"]
                    st.rerun()

    st.divider()

    # ── อัปโหลดรายงาน ─────────────────────────────────────────────────
    st.subheader("อัปโหลดรายงาน")
    if not shops:
        st.info("เพิ่มร้านก่อนครับ (ด้านบน)")
    else:
        _plat_with_shops = sorted({s["platform"] for s in shops}, key=list(_PLATFORMS.keys()).index)
        _upload_platform = st.radio(
            "แพลตฟอร์ม", _plat_with_shops, format_func=lambda p: _PLATFORMS.get(p, p),
            horizontal=True, key="ecom_upload_platform",
        )
        _plat_shop_names = [s["shop_name"] for s in shops if s["platform"] == _upload_platform]
        if _upload_platform == "shopee":
            _render_shopee_upload(_plat_shop_names)
        else:
            _render_lazada_upload(_plat_shop_names)

    st.divider()

    # ── Map สินค้า → ระบบ ─────────────────────────────────────────────
    st.subheader("Map สินค้า → ระบบ")
    _map_plat_opts = sorted({s["platform"] for s in shops}, key=list(_PLATFORMS.keys()).index) if shops else ["shopee"]
    _map_platform = st.radio(
        "แพลตฟอร์ม", _map_plat_opts, format_func=lambda p: _PLATFORMS.get(p, p),
        horizontal=True, key="ecom_map_platform",
    )
    unmapped_rows = db.get_unmapped_ecommerce_items(_map_platform)

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
            sel = mc2.selectbox("สินค้าในระบบ", list(prod_opts.keys()), key=f"map_{_map_platform}_{i}")
            sold_qty = mc3.number_input(
                "ขายจริงกี่หน่วย/ออเดอร์", min_value=1, value=1, step=1, key=f"map_sold_{_map_platform}_{i}",
                help="เช่น ยาสีฟัน 3 หลอด ใส่ 3, แบ่งขาย 30 ซอง ใส่ 30, ปกติ (1 ต่อ 1) ใส่ 1",
            )
            pack_size = mc4.number_input(
                "1 หน่วยสต็อกในระบบ = กี่หน่วย", min_value=1, value=1, step=1, key=f"map_pack_{_map_platform}_{i}",
                help="ดูจากชื่อสินค้าที่เลือก เช่น 'บียางค์ 180' ใส่ 180, ถ้าสินค้าปกติ (ไม่แบ่งขาย) ใส่ 1",
            )
            ratio = sold_qty / pack_size
            if ratio != 1:
                mc1.caption(f"→ เทียบเท่า {ratio:.4f} หน่วยสต็อก/ออเดอร์")
            if prod_opts[sel]:
                map_rows.append({
                    "id": str(uuid.uuid4()),
                    "platform": _map_platform,
                    "platform_item_id": row["item_id"],
                    "product_id": prod_opts[sel],
                    "platform_product_name": row["item_name"] or row["item_id"],
                    "units_per_pack": ratio,
                })
        if map_rows and st.button("💾 บันทึก Mapping", type="primary", key=f"ecom_map_save_{_map_platform}"):
            db.upsert_ecommerce_product_map(map_rows)
            db.apply_ecommerce_product_map(map_rows, _map_platform)
            st.success(f"✅ Map แล้ว {len(map_rows)} รายการ")
            st.rerun()
    else:
        st.success("✅ สินค้าทุกรายการ map แล้ว")


def _render_shopee_upload(shop_names: list[str]):
    coverage_df = db.get_ecommerce_import_coverage_df("shopee")
    if not coverage_df.empty:
        st.caption("ข้อมูลที่นำเข้าแล้วครอบคลุมช่วงวันไหนบ้าง (เช็คก่อนอัปโหลดเพิ่ม กันช่วงขาด/ซ้ำ)")
        st.dataframe(coverage_df, width="stretch", hide_index=True)
        _gap_shops = coverage_df.loc[coverage_df["ช่วงที่ Order.all ยังไม่ครอบคลุม"] != "-", "ร้าน"].tolist()
        if _gap_shops:
            st.warning(
                f"⚠️ ร้าน {', '.join(_gap_shops)} มีรายงานรายได้ (Income) ครอบคลุมช่วงที่ยังไม่ได้อัปโหลด "
                "Order.all — ดูคอลัมน์ \"ช่วงที่ Order.all ยังไม่ครอบคลุม\" แล้วอัปโหลด Order.all "
                "เพิ่มให้ครบช่วงนั้น ไม่งั้นออเดอร์กลุ่มนี้จะไม่ถูกนับกำไรต่อสินค้า (ดูแท็บ '💰 ยอดขาย/กำไร')"
            )
    _order_ver = st.session_state.get("_ecom_order_file_ver", 0)
    _income_ver = st.session_state.get("_ecom_income_file_ver", 0)
    oc1, oc2 = st.columns(2)
    with oc1:
        st.markdown("**📦 รายงานคำสั่งซื้อ** (คำสั่งซื้อ → Export)")
        _order_msg = st.session_state.pop("_ecom_order_import_msg", None)
        if _order_msg:
            getattr(st, _order_msg[0])(_order_msg[1])
        _order_shop = st.selectbox("ร้าน", shop_names, key="ecom_order_shop")
        _pending = st.session_state.get("_ecom_order_pending_import")
        if _pending:
            _mismatch = _pending["mismatches"]
            _examples = ", ".join(f"{sn} (เดิม: {nm})" for sn, nm in list(_mismatch.items())[:5])
            st.warning(
                f"⚠️ พบ {len(_mismatch)} ออเดอร์ในไฟล์นี้ที่เคยถูกบันทึกเป็น**ร้านอื่น**มาก่อน "
                f"แต่ตอนนี้กำลังจะนำเข้าเป็นร้าน **{_pending['shop_name']}** — เช่น {_examples}"
                f"{' ...' if len(_mismatch) > 5 else ''}\n\n"
                "แน่ใจว่าเลือกร้านถูกต้องแล้ว หรือไฟล์นี้เป็นไฟล์ผิดร้าน?"
            )
            _pc1, _pc2 = st.columns(2)
            if _pc1.button("✅ ยืนยันนำเข้าต่อ (ร้านถูกต้องแล้ว)", key="ecom_confirm_order_mismatch"):
                _rows = _pending["rows"]
                prod_map = db.get_ecommerce_product_map()
                for r in _rows:
                    _m = prod_map.get(("shopee", r["item_id_platform"]))
                    r["product_id"] = _m["product_id"] if _m else None
                db.upsert_ecommerce_sales(_rows)
                _n_updated = db.allocate_ecommerce_order_income()
                st.session_state["_ecom_order_import_msg"] = (
                    "success", f"✅ นำเข้า {len(_rows)} รายการ (แบ่งยอดเงินสุทธิให้ {_n_updated} รายการ)")
                del st.session_state["_ecom_order_pending_import"]
                st.session_state["_ecom_order_file_ver"] = _order_ver + 1
                st.rerun()
            if _pc2.button("❌ ยกเลิก (ไฟล์/ร้านผิด)", key="ecom_cancel_order_mismatch"):
                del st.session_state["_ecom_order_pending_import"]
                st.session_state["_ecom_order_file_ver"] = _order_ver + 1
                st.rerun()
        else:
            _order_file = st.file_uploader("ไฟล์ Order.all...xlsx", type=["xlsx"], key=f"ecom_order_file_{_order_ver}")
            if _order_file and st.button("นำเข้ารายงานคำสั่งซื้อ", key="ecom_import_orders", type="primary"):
                with st.spinner("กำลังอ่านไฟล์..."):
                    rows = shopee_import.parse_order_export(_order_file, _order_shop)
                    if not rows:
                        st.session_state["_ecom_order_import_msg"] = ("warning", "⚠️ ไม่พบข้อมูลในไฟล์")
                        st.session_state["_ecom_order_file_ver"] = _order_ver + 1
                    else:
                        _order_sns = list({r["order_sn"] for r in rows})
                        _mismatch = db.check_ecommerce_shop_mismatch(_order_sns, _order_shop)
                        if _mismatch:
                            st.session_state["_ecom_order_pending_import"] = {
                                "rows": rows, "mismatches": _mismatch, "shop_name": _order_shop,
                            }
                        else:
                            prod_map = db.get_ecommerce_product_map()
                            for r in rows:
                                _m = prod_map.get(("shopee", r["item_id_platform"]))
                                r["product_id"] = _m["product_id"] if _m else None
                            db.upsert_ecommerce_sales(rows)
                            _n_updated = db.allocate_ecommerce_order_income()
                            st.session_state["_ecom_order_import_msg"] = (
                                "success", f"✅ นำเข้า {len(rows)} รายการ (แบ่งยอดเงินสุทธิให้ {_n_updated} รายการ)")
                            st.session_state["_ecom_order_file_ver"] = _order_ver + 1
                st.rerun()

    with oc2:
        st.markdown("**💰 รายงานรายได้** (การเงิน → รายได้ของฉัน → Export)")
        _income_msg = st.session_state.pop("_ecom_income_import_msg", None)
        if _income_msg:
            getattr(st, _income_msg[0])(_income_msg[1])
        _income_file = st.file_uploader("ไฟล์ Income...xlsx", type=["xlsx"], key=f"ecom_income_file_{_income_ver}")
        if _income_file and st.button("นำเข้ารายงานรายได้", key="ecom_import_income", type="primary"):
            with st.spinner("กำลังอ่านไฟล์..."):
                rows, _detected_shop = shopee_import.parse_income_export(_income_file)
                if rows:
                    db.upsert_ecommerce_order_income(rows)
                    _n_updated = db.allocate_ecommerce_order_income()
                    st.session_state["_ecom_income_import_msg"] = (
                        "success",
                        f"✅ นำเข้า {len(rows)} ออเดอร์ (ร้าน {_detected_shop}) — แบ่งยอดเงินสุทธิให้ {_n_updated} รายการ")
                else:
                    st.session_state["_ecom_income_import_msg"] = ("warning", "⚠️ ไม่พบข้อมูลในไฟล์")
            st.session_state["_ecom_income_file_ver"] = _income_ver + 1
            st.rerun()


def _render_lazada_upload(shop_names: list[str]):
    st.caption(
        "ไฟล์เดียวจบ — ไม่ต้องแยก Order/Income เหมือน Shopee (แต่ไม่มีข้อมูลค่าจัดส่ง "
        "ให้เช็ค \"ค่าส่งเกิน\" เหมือน Shopee — Lazada ไม่รายงานค่าส่งมาในไฟล์นี้)"
    )
    _laz_ver = st.session_state.get("_ecom_lazada_file_ver", 0)
    st.markdown("**📊 รายงาน Income Overview** (รายรับของฉัน → โอนเงินแล้ว → เลือกวันที่ → ดาวน์โหลด)")
    _laz_msg = st.session_state.pop("_ecom_lazada_import_msg", None)
    if _laz_msg:
        getattr(st, _laz_msg[0])(_laz_msg[1])
    _laz_shop = st.selectbox("ร้าน", shop_names, key="ecom_lazada_shop")
    _laz_file = st.file_uploader("ไฟล์ Income Overview...xlsx", type=["xlsx"], key=f"ecom_lazada_file_{_laz_ver}")
    if _laz_file and st.button("นำเข้ารายงาน Lazada", key="ecom_import_lazada", type="primary"):
        with st.spinner("กำลังอ่านไฟล์..."):
            sales_rows, income_rows = lazada_import.parse_income_overview(_laz_file, _laz_shop)
            if not sales_rows:
                st.session_state["_ecom_lazada_import_msg"] = ("warning", "⚠️ ไม่พบข้อมูลในไฟล์")
            else:
                prod_map = db.get_ecommerce_product_map()
                for r in sales_rows:
                    _m = prod_map.get(("lazada", r["item_id_platform"]))
                    r["product_id"] = _m["product_id"] if _m else None
                db.upsert_ecommerce_sales(sales_rows)
                db.upsert_ecommerce_order_income(income_rows)
                _n_updated = db.allocate_ecommerce_order_income("lazada")
                st.session_state["_ecom_lazada_import_msg"] = (
                    "success",
                    f"✅ นำเข้า {len(sales_rows)} รายการ ({len(income_rows)} ออเดอร์) — แบ่งยอดเงินสุทธิให้ {_n_updated} รายการ")
            st.session_state["_ecom_lazada_file_ver"] = _laz_ver + 1
        st.rerun()


def _render_sales_profit():
    _shops = db.get_ecommerce_shops()
    _plat_opts = sorted({s["platform"] for s in _shops}, key=list(_PLATFORMS.keys()).index) if _shops else list(_PLATFORMS.keys())
    _platform = st.radio(
        "แพลตฟอร์ม", _plat_opts, format_func=lambda p: _PLATFORMS.get(p, p),
        horizontal=True, key="ecom_profit_platform",
    )
    _plat_label = _PLATFORMS.get(_platform, _platform)

    # ── กำไรจริงต่อสินค้า (เฉพาะที่ขายผ่านแพลตฟอร์มนี้) ──────────────────
    st.subheader("กำไรจริง (ต่อสินค้า)")
    st.caption(f"กำไร = ยอดเงินที่ {_plat_label} โอนเข้าจริง (หลังหักค่าธรรมเนียม/ค่าส่ง/ภาษีแล้ว) − ต้นทุน × จำนวนที่ขาย")

    _unmapped_n = len(db.get_unmapped_ecommerce_items(_platform))
    if _unmapped_n:
        st.warning(f"⚠️ มี {_unmapped_n} รายการสินค้าที่ยังไม่ได้ map — ยอดขาย/กำไรของรายการนี้ยังไม่ถูกนับ ไปที่แท็บ '⚙️ ตั้งค่า/นำเข้าข้อมูล' เพื่อ map สินค้า")

    _shop_opts = ["ทั้งหมด"] + [s["shop_name"] for s in _shops if s["platform"] == _platform]
    _sel_shop = st.selectbox("ร้าน", _shop_opts, key=f"ecom_profit_shop_filter_{_platform}")
    _shop_filter = None if _sel_shop == "ทั้งหมด" else _sel_shop

    with st.expander("📅 สรุปยอดขาย/กำไรรายเดือน"):
        monthly_df = db.get_ecommerce_monthly_summary(platform=_platform, shop_name=_shop_filter)
        if monthly_df.empty:
            st.info("ยังไม่มีข้อมูล")
        else:
            st.dataframe(
                monthly_df.style.format({
                    "ยอดขาย": "{:,.2f}", "กำไรรวม": "{:,.2f}", "ขาดทุนรวม": "{:,.2f}", "สุทธิ": "{:,.2f}",
                }),
                width="stretch", hide_index=True,
            )
            st.caption("กำไร/ขาดทุนคำนวณแบบรายออเดอร์ต่อเดือน (สูตรเดียวกับตัวเลขสรุปด้านล่าง) — เดือนที่ยังไม่มีรายงาน Income มายืนยันครบ ตัวเลขกำไรของเดือนนั้นอาจยังไม่นิ่ง")

    mc1, mc2, mc3 = st.columns([1, 1, 1])
    margin_from = mc1.date_input("จาก", value=date.today().replace(day=1), key="ecom_margin_from")
    margin_to   = mc2.date_input("ถึง",  value=date.today(), key="ecom_margin_to")
    margin_warn_pct = mc3.number_input("เตือนถ้ากำไร < กี่ % ของยอดโอน", min_value=0, max_value=100, value=10, key="ecom_margin_warn_pct")

    margin_df, pending_qty = db.get_ecommerce_product_margin_df(str(margin_from), str(margin_to), platform=_platform, shop_name=_shop_filter)
    if pending_qty:
        st.info(f"ℹ️ มี {pending_qty:,} ชิ้น ที่ขายแล้วแต่ยังไม่มีรายงานยอดโอน (Income) มายืนยัน — ยังไม่รวมในตารางนี้ (อัปโหลดรายงาน Income ของช่วงที่ครอบคลุมออเดอร์เหล่านี้เพิ่มเพื่อให้เห็นครบ)")
    if margin_df.empty:
        st.info("ยังไม่มีข้อมูล หรือยังไม่ได้ map สินค้า (แท็บ '⚙️ ตั้งค่า/นำเข้าข้อมูล' → Map สินค้า)")
    else:
        margin_df = margin_df.rename(columns={"ขายผ่าน Shopee (ชิ้น)": f"ขายผ่าน {_plat_label} (ชิ้น)"})
        # กำไรรวม/ขาดทุนรวม/สุทธิ จัด class เป็นรายออเดอร์ (ไม่ใช่ net รายสินค้าทั้งช่วง)
        # เพื่อให้บวกกันตรงๆ ข้ามช่วงเวลาได้ (เดือน 6 + เดือน 7 = ช่วงรวม 6-7 พอดี) — ดู
        # get_ecommerce_order_profit_summary
        _profit_summary = db.get_ecommerce_order_profit_summary(str(margin_from), str(margin_to), platform=_platform, shop_name=_shop_filter)
        _total_profit = _profit_summary["total_profit"]
        _total_loss   = _profit_summary["total_loss"]
        _net_total    = _profit_summary["net"]
        _total_qty    = margin_df[f"ขายผ่าน {_plat_label} (ชิ้น)"].sum()
        _total_pv     = margin_df["PV"].sum()
        _sm1, _sm2, _sm3, _sm4, _sm5 = st.columns(5)
        _sm1.metric("กำไรรวม", f"{_total_profit:,.0f} ฿")
        _sm2.metric("ขาดทุนรวม", f"{_total_loss:,.0f} ฿")
        _sm3.metric("สุทธิ", f"{_net_total:,.0f} ฿")
        _sm4.metric("ขายรวม", f"{_total_qty:,.0f} ชิ้น")
        _sm5.metric("PV รวม", f"{_total_pv:,.0f}")
        st.caption(
            "กำไรรวม/ขาดทุนรวม จัดเป็นรายออเดอร์ (บวกกันตรงๆ ข้ามช่วงเวลาได้) — ต่างจากตาราง "
            "ด้านล่างที่สรุปสุทธิรายสินค้าตลอดทั้งช่วง สินค้าที่กำไรเดือนหนึ่งแต่ขาดทุนอีกเดือน "
            "อาจทำให้ผลรวมในตารางไม่เท่ากับเอาแต่ละเดือนมาบวกกันตรงๆ"
        )

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
                "ราคาขายสุทธิที่ควรได้ต่อชิ้น (คุ้มทุน)": "{:,.2f}",
            }),
            width="stretch", hide_index=True,
        )
        _n_loss = (margin_df["กำไรรวม"] < 0).sum()
        if _n_loss:
            st.warning(f"⚠️ มี {_n_loss} สินค้าที่ขาดทุนในช่วงนี้ — คอลัมน์ \"ราคาขายสุทธิที่ควรได้ต่อชิ้น (คุ้มทุน)\" คือราคาขายจริงเฉลี่ยหลังหักโค้ดส่วนลด/โปรโมชัน (ไม่ใช่ราคาที่ตั้งในหน้าสินค้า) ที่ต้องได้อย่างน้อยเท่านี้ถึงจะไม่ขาดทุน — ถ้ามักมีโค้ดส่วนลดมาหักอีก ราคาหน้าสินค้าอาจต้องตั้งสูงกว่านี้")

    st.divider()

    # ── ยอดขาย E-commerce (รายการดิบ) ────────────────────────────────────
    with st.expander("ดูยอดขาย E-commerce (รายการดิบ)", expanded=True):
        ev1, ev2 = st.columns(2)
        view_from = ev1.date_input("จาก", value=date.today().replace(day=1), key="ecom_vfrom")
        view_to   = ev2.date_input("ถึง",  value=date.today(), key="ecom_vto")
        ecom_df   = db.get_ecommerce_sales_df(str(view_from), str(view_to), platform=_platform, shop_name=_shop_filter)
        if ecom_df.empty:
            st.info("ยังไม่มีข้อมูล — อัปโหลดรายงานคำสั่งซื้อก่อนครับ (แท็บ '⚙️ ตั้งค่า/นำเข้าข้อมูล')")
        else:
            st.dataframe(
                ecom_df.style.format({"ยอด": "{:,.2f}", "ยอดเงินที่ได้รับจริง": "{:,.2f}"}, na_rep="รอยืนยัน"),
                width="stretch", hide_index=True,
            )
            _net_received = ecom_df["ยอดเงินที่ได้รับจริง"].sum()
            st.caption(
                f"รวม {ecom_df['จำนวน'].sum():,} ชิ้น | ยอด (ก่อนหักค่าธรรมเนียม) {ecom_df['ยอด'].sum():,.2f} บาท "
                f"| ยอดเงินที่ได้รับจริง (เฉพาะออเดอร์ที่โอนแล้ว) {_net_received:,.2f} บาท"
            )


def _render_issues():
    _shops = db.get_ecommerce_shops()
    _plat_opts = sorted({s["platform"] for s in _shops}, key=list(_PLATFORMS.keys()).index) if _shops else list(_PLATFORMS.keys())
    _platform = st.radio(
        "แพลตฟอร์ม", _plat_opts, format_func=lambda p: _PLATFORMS.get(p, p),
        horizontal=True, key="ecom_issues_platform",
    )
    _shop_opts = ["ทั้งหมด"] + [s["shop_name"] for s in _shops if s["platform"] == _platform]
    _sel_shop = st.selectbox("ร้าน", _shop_opts, key=f"ecom_issues_shop_filter_{_platform}")
    _shop_filter = None if _sel_shop == "ทั้งหมด" else _sel_shop

    # ── ออเดอร์ที่กำไรผิดปกติ (พร้อมเลขที่ออเดอร์) ───────────────────────
    st.subheader("ออเดอร์ที่กำไรผิดปกติ")
    st.caption("รายออเดอร์ (ไม่ใช่สรุปรวมสินค้า) — ใช้ไล่เช็คว่าออเดอร์ไหนกันแน่ที่ขาดทุน/กำไรต่ำ")
    ac1, ac2, ac3 = st.columns([1, 1, 1])
    anomaly_from = ac1.date_input("จาก", value=date.today().replace(day=1), key="ecom_anomaly_from")
    anomaly_to   = ac2.date_input("ถึง",  value=date.today(), key="ecom_anomaly_to")
    anomaly_warn_pct = ac3.number_input("เตือนถ้ากำไร < กี่ % ของยอดโอน", min_value=0, max_value=100, value=10, key="ecom_anomaly_warn_pct")
    anomaly_df = db.get_ecommerce_order_anomaly_df(str(anomaly_from), str(anomaly_to), platform=_platform, warn_pct=anomaly_warn_pct, shop_name=_shop_filter)
    if anomaly_df.empty:
        st.success("✅ ไม่พบออเดอร์ที่กำไรผิดปกติในช่วงนี้")
    else:
        st.warning(f"⚠️ พบ {len(anomaly_df)} ออเดอร์ที่กำไรผิดปกติ")
        st.dataframe(
            anomaly_df.style.format({
                "ต้นทุนรวม": "{:,.2f}", "ยอดเงินที่ได้รับจริง": "{:,.2f}", "กำไร": "{:,.2f}",
            }),
            width="stretch", hide_index=True,
        )

    st.divider()

    # ── ออเดอร์คืนสินค้า/ยกเลิก + tracking ────────────────────────────────
    st.subheader("ออเดอร์คืนสินค้า/ยกเลิก + ติดตามพัสดุ")
    problem_df = db.get_ecommerce_problem_orders_df(platform=_platform, shop_name=_shop_filter)
    if problem_df.empty:
        st.success("✅ ไม่มีออเดอร์คืนสินค้า/ยกเลิกที่บันทึกไว้")
    else:
        st.dataframe(problem_df, width="stretch", hide_index=True)

    if _platform == "shopee":
        st.divider()

        # ── ตรวจสอบค่าส่งเกิน (เฉพาะ Shopee — Lazada ไม่รายงานค่าส่งมาในไฟล์) ──
        st.subheader("ตรวจสอบค่าส่งเกิน")
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
        overcharge_df = db.get_ecommerce_shipping_overcharge_df(str(ship_from), str(ship_to), platform="shopee", overcharge_threshold=ship_threshold, shop_name=_shop_filter)
        if overcharge_df.empty:
            st.success("✅ ไม่พบออเดอร์ที่ค่าส่งเกินเกณฑ์ในช่วงนี้")
        else:
            st.warning(f"⚠️ พบ {len(overcharge_df)} ออเดอร์ที่ค่าส่งเกินเกณฑ์")
            st.dataframe(overcharge_df, width="stretch", hide_index=True)
