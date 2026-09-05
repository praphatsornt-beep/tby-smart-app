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
import tiktok_affiliate_import
import tiktok_income_import
import tiktok_order_status_import
from ui_helpers import _to_excel_bytes


_ECOM_TABS = ["📥 นำเข้าข้อมูล", "💰 ยอดขาย/กำไร", "🎯 TikTok Affiliate", "⚠️ ตรวจสอบปัญหา", "⚙️ ตั้งค่า"]
_PLATFORMS = {"shopee": "Shopee", "lazada": "Lazada", "tiktok": "TikTok"}


def _pills(options: list[str], key: str) -> str:
    """st.pills ถ้ามี (Streamlit ใหม่) ไม่งั้น fallback เป็น st.radio (Streamlit เก่า)."""
    try:
        return st.pills(" ", options, key=key, default=options[0], label_visibility="collapsed") or options[0]
    except AttributeError:
        return st.radio(" ", options, horizontal=True, key=key, label_visibility="collapsed")


def _set_flash(key: str, kind: str, msg: str):
    """เก็บข้อความ success/warning ไว้ใน session_state ให้โผล่หลัง st.rerun() รอบถัดไป
    (ปุ่มที่กด rerun ทันทีจะ render ข้อความไม่ทันถ้าเรียก st.success/st.warning ตรงๆ ก่อน rerun)."""
    st.session_state[key] = (kind, msg)


def _show_flash(key: str):
    _msg = st.session_state.pop(key, None)
    if _msg:
        getattr(st, _msg[0])(_msg[1])


def _date_range_inputs(key_prefix: str, n_cols: int = 2, from_label: str = "จาก", to_label: str = "ถึง"):
    """คู่ date_input จาก/ถึง (default = ต้นเดือนนี้ → วันนี้) — n_cols>2 เผื่อ column
    เพิ่มให้ widget อื่นวางในแถวเดียวกัน (เช่น number_input เกณฑ์เตือน) คืน columns
    ที่เหลือให้ผู้เรียกใช้เอง"""
    cols = st.columns(n_cols)
    date_from = cols[0].date_input(from_label, value=date.today().replace(day=1), key=f"{key_prefix}_from")
    date_to = cols[1].date_input(to_label, value=date.today(), key=f"{key_prefix}_to")
    return date_from, date_to, cols[2:]


def _map_products_and_upsert(rows_per_file: list[list[dict]], platform: str) -> int:
    """ใส่ product_id ให้แต่ละแถวขาย (map จาก platform_item_id) แล้ว upsert เข้า
    ecommerce_sales — ทีละไฟล์ ไม่รวมทุกไฟล์เป็น batch เดียว (ดูเหตุผลที่จุดเรียกใช้ของ
    Shopee: _dedupe_by_key ใน upsert_ecommerce_sales จะ "บวก" qty ผิดถ้าออเดอร์เดียวกัน
    ซ้ำข้ามไฟล์อยู่ใน batch เดียวกัน) คืนจำนวนแถวที่ upsert ทั้งหมด"""
    prod_map = db.get_ecommerce_product_map()
    total = 0
    for _rows in rows_per_file:
        for r in _rows:
            _m = prod_map.get((platform, r["item_id_platform"]))
            r["product_id"] = _m["product_id"] if _m else None
        db.upsert_ecommerce_sales(_rows)
        total += len(_rows)
    return total


def render():
    _ecom_active = _pills(_ECOM_TABS, "_ecom_active_sub")

    if _ecom_active == _ECOM_TABS[0]:
        _render_import()
    elif _ecom_active == _ECOM_TABS[1]:
        _render_sales_profit()
    elif _ecom_active == _ECOM_TABS[2]:
        _render_tiktok_affiliate()
    elif _ecom_active == _ECOM_TABS[3]:
        _render_issues()
    elif _ecom_active == _ECOM_TABS[4]:
        _render_config()


def _render_import():
    shops = db.get_ecommerce_shops()
    if not shops:
        st.info("ยังไม่มีร้านค้า — ไปเพิ่มร้านที่แท็บ '⚙️ ตั้งค่า' ก่อนครับ")
        return

    _tt_pending_all = db.get_tiktok_pending_sync_count()
    if _tt_pending_all:
        st.warning(f"⚠️ TikTok มี {_tt_pending_all} ออเดอร์ค้างซิงค์เข้าระบบกำไรสินค้า (ทุกร้านรวมกัน) — เลือกแพลตฟอร์ม TikTok ด้านล่างแล้วกดซิงค์")

    _plat_with_shops = sorted({s["platform"] for s in shops}, key=list(_PLATFORMS.keys()).index)
    _upload_platform = st.radio(
        "แพลตฟอร์ม", _plat_with_shops, format_func=lambda p: _PLATFORMS.get(p, p),
        horizontal=True, key="ecom_upload_platform",
    )
    _plat_shop_names = [s["shop_name"] for s in shops if s["platform"] == _upload_platform]
    if _upload_platform == "shopee":
        _render_shopee_upload(_plat_shop_names)
    elif _upload_platform == "lazada":
        _render_lazada_upload(_plat_shop_names)
    else:
        _render_tiktok_upload(_plat_shop_names)


def _render_config():
    # ── ร้านค้า ────────────────────────────────────────────────────────
    st.subheader("ร้านค้า")
    shops = db.get_ecommerce_shops()
    with st.expander("➕ เพิ่มร้านใหม่", expanded=not shops):
        _new_plat = st.selectbox("แพลตฟอร์ม", list(_PLATFORMS.keys()), format_func=lambda p: _PLATFORMS[p], key="ecom_new_shop_platform")
        _new_shop = st.text_input("ชื่อร้าน", key="ecom_new_shop_name", placeholder="เช่น Shopee ร้าน 1")
        if st.button("บันทึกร้าน", key="ecom_add_shop") and _new_shop.strip():
            _same_plat_names = [s["shop_name"] for s in shops if s["platform"] == _new_plat]
            if _new_shop.strip() in _same_plat_names:
                st.warning(f"⚠️ มีร้านชื่อ {_new_shop.strip()} อยู่แล้วใน {_PLATFORMS[_new_plat]} ไม่เพิ่มซ้ำ")
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
        _show_flash("_ecom_order_import_msg")
        _order_shop = st.selectbox("ร้าน", shop_names, key="ecom_order_shop")
        _pending = st.session_state.get("_ecom_order_pending_import")
        if _pending:
            _mismatch = _pending["mismatches"]
            _examples = ", ".join(f"{sn} (เดิม: {nm})" for sn, nm in list(_mismatch.items())[:5])
            st.warning(
                f"⚠️ พบ {len(_mismatch)} ออเดอร์ในไฟล์ที่เคยถูกบันทึกเป็น**ร้านอื่น**มาก่อน "
                f"แต่ตอนนี้กำลังจะนำเข้าเป็นร้าน **{_pending['shop_name']}** — เช่น {_examples}"
                f"{' ...' if len(_mismatch) > 5 else ''}\n\n"
                "แน่ใจว่าเลือกร้านถูกต้องแล้ว หรือไฟล์นี้เป็นไฟล์ผิดร้าน?"
            )
            _pc1, _pc2 = st.columns(2)
            if _pc1.button("✅ ยืนยันนำเข้าต่อ (ร้านถูกต้องแล้ว)", key="ecom_confirm_order_mismatch"):
                _total = _map_products_and_upsert(_pending["rows_per_file"], "shopee")
                _n_updated = db.allocate_ecommerce_order_income()
                _set_flash("_ecom_order_import_msg", "success", f"✅ นำเข้า {_total} รายการ (แบ่งยอดเงินสุทธิให้ {_n_updated} รายการ)")
                del st.session_state["_ecom_order_pending_import"]
                st.session_state["_ecom_order_file_ver"] = _order_ver + 1
                st.rerun()
            if _pc2.button("❌ ยกเลิก (ไฟล์/ร้านผิด)", key="ecom_cancel_order_mismatch"):
                del st.session_state["_ecom_order_pending_import"]
                st.session_state["_ecom_order_file_ver"] = _order_ver + 1
                st.rerun()
        else:
            _order_files = st.file_uploader(
                "ไฟล์ Order.all...xlsx (เลือกได้หลายไฟล์พร้อมกัน)", type=["xlsx"],
                accept_multiple_files=True, key=f"ecom_order_file_{_order_ver}")
            if _order_files and st.button("นำเข้ารายงานคำสั่งซื้อ", key="ecom_import_orders", type="primary"):
                with st.spinner(f"กำลังอ่านไฟล์... ({len(_order_files)} ไฟล์)"):
                    rows_per_file = [shopee_import.parse_order_export(f, _order_shop) for f in _order_files]
                    all_rows = [r for _rows in rows_per_file for r in _rows]
                    if not all_rows:
                        _set_flash("_ecom_order_import_msg", "warning", "⚠️ ไม่พบข้อมูลในไฟล์")
                        st.session_state["_ecom_order_file_ver"] = _order_ver + 1
                    else:
                        _order_sns = list({r["order_sn"] for r in all_rows})
                        _mismatch = db.check_ecommerce_shop_mismatch(_order_sns, _order_shop)
                        if _mismatch:
                            st.session_state["_ecom_order_pending_import"] = {
                                "rows_per_file": rows_per_file, "mismatches": _mismatch, "shop_name": _order_shop,
                            }
                        else:
                            _map_products_and_upsert(rows_per_file, "shopee")
                            _n_updated = db.allocate_ecommerce_order_income()
                            _set_flash("_ecom_order_import_msg", "success",
                                       f"✅ นำเข้า {len(all_rows)} รายการ จาก {len(_order_files)} ไฟล์ (แบ่งยอดเงินสุทธิให้ {_n_updated} รายการ)")
                            st.session_state["_ecom_order_file_ver"] = _order_ver + 1
                st.rerun()

    with oc2:
        st.markdown("**💰 รายงานรายได้** (การเงิน → รายได้ของฉัน → Export)")
        _show_flash("_ecom_income_import_msg")
        _income_file = st.file_uploader("ไฟล์ Income...xlsx", type=["xlsx"], key=f"ecom_income_file_{_income_ver}")
        if _income_file and st.button("นำเข้ารายงานรายได้", key="ecom_import_income", type="primary"):
            with st.spinner("กำลังอ่านไฟล์..."):
                rows, _detected_shop = shopee_import.parse_income_export(_income_file)
                if rows:
                    db.upsert_ecommerce_order_income(rows)
                    _n_updated = db.allocate_ecommerce_order_income()
                    _set_flash("_ecom_income_import_msg", "success",
                               f"✅ นำเข้า {len(rows)} ออเดอร์ (ร้าน {_detected_shop}) — แบ่งยอดเงินสุทธิให้ {_n_updated} รายการ")
                else:
                    _set_flash("_ecom_income_import_msg", "warning", "⚠️ ไม่พบข้อมูลในไฟล์")
            st.session_state["_ecom_income_file_ver"] = _income_ver + 1
            st.rerun()


def _render_lazada_upload(shop_names: list[str]):
    st.caption(
        "ไฟล์เดียวจบ — ไม่ต้องแยก Order/Income เหมือน Shopee (แต่ไม่มีข้อมูลค่าจัดส่ง "
        "ให้เช็ค \"ค่าส่งเกิน\" เหมือน Shopee — Lazada ไม่รายงานค่าส่งมาในไฟล์นี้)"
    )
    _laz_ver = st.session_state.get("_ecom_lazada_file_ver", 0)
    st.markdown("**📊 รายงาน Income Overview** (รายรับของฉัน → รายละเอียดรายรับ → เลือกวันที่ → ดาวน์โหลด)")
    _show_flash("_ecom_lazada_import_msg")
    _laz_shop = st.selectbox("ร้าน", shop_names, key="ecom_lazada_shop")
    _laz_file = st.file_uploader("ไฟล์ Income Overview...xlsx", type=["xlsx"], key=f"ecom_lazada_file_{_laz_ver}")
    if _laz_file and st.button("นำเข้ารายงาน Lazada", key="ecom_import_lazada", type="primary"):
        with st.spinner("กำลังอ่านไฟล์..."):
            sales_rows, income_rows = lazada_import.parse_income_overview(_laz_file, _laz_shop)
            if not sales_rows:
                _set_flash("_ecom_lazada_import_msg", "warning", "⚠️ ไม่พบข้อมูลในไฟล์")
            else:
                _map_products_and_upsert([sales_rows], "lazada")
                db.upsert_ecommerce_order_income(income_rows)
                _n_updated = db.allocate_ecommerce_order_income("lazada")
                _set_flash("_ecom_lazada_import_msg", "success",
                           f"✅ นำเข้า {len(sales_rows)} รายการ ({len(income_rows)} ออเดอร์) — แบ่งยอดเงินสุทธิให้ {_n_updated} รายการ")
            st.session_state["_ecom_lazada_file_ver"] = _laz_ver + 1
        st.rerun()


def _render_tiktok_upload(shop_names: list[str]):
    # ใช้ทะเบียนร้านร่วมกับ Shopee/Lazada (db.get_ecommerce_shops()) แทน text input
    # อิสระ 2 จุดแบบเดิม (เคยพิมพ์ชื่อร้านไม่ตรงกันระหว่างฟอร์ม affiliate/income ได้โดย
    # ไม่รู้ตัว ไม่มีการ validate เลย) — เพิ่มร้านใหม่ที่แท็บ '⚙️ ตั้งค่า' ก่อนถ้ายังไม่มี
    _tt_shop = st.selectbox("ร้าน", shop_names, key="ecom_tiktok_shop")

    st.markdown("**🎥 ค่าคอมนายหน้า (Affiliate)**")
    st.caption(
        "รายงานเฉพาะออเดอร์ที่มาจากนายหน้า/ครีเอเตอร์ (TikTok Shop Seller Center → "
        "Affiliate Marketing → Orders → Export) ไม่ใช่ยอดขายทั้งหมดของร้าน "
        "\"ยอดที่เราได้โดยประมาณ\" หักแค่ค่าคอมนายหน้าออกจากยอดขาย ยังไม่รวมค่าธรรมเนียม "
        "อื่นๆ ของ TikTok เอง (ไฟล์นี้ไม่มีข้อมูลนั้น) — ดูผลที่แท็บ '🎯 TikTok Affiliate'"
    )
    _tt_ver = st.session_state.get("_ecom_tiktok_file_ver", 0)
    _show_flash("_ecom_tiktok_import_msg")
    _tt_file = st.file_uploader("ไฟล์ affiliate_orders...xlsx", type=["xlsx"], key=f"ecom_tiktok_file_{_tt_ver}")
    if _tt_file and st.button("นำเข้ารายงานนายหน้า TikTok", key="ecom_import_tiktok", type="primary"):
        with st.spinner("กำลังอ่านไฟล์..."):
            _tt_rows = tiktok_affiliate_import.parse_affiliate_orders(_tt_file, _tt_shop)
            if not _tt_rows:
                _set_flash("_ecom_tiktok_import_msg", "warning", "⚠️ ไม่พบข้อมูลในไฟล์")
            else:
                db.upsert_tiktok_affiliate_orders(_tt_rows)
                _msg = f"✅ นำเข้า {len(_tt_rows)} รายการแล้ว"
                # ซิงค์เข้าระบบกำไรสินค้าอัตโนมัติทันที (เดิมต้องกดปุ่มแยกด้านล่างเอง
                # ลืมกดได้ง่าย — ปุ่มด้านล่างยังอยู่ไว้เผื่อต้อง sync ซ้ำ)
                _sync_result = db.sync_tiktok_to_ecommerce(_tt_shop)
                if _sync_result["sales_rows"]:
                    _msg += f" · ซิงค์เข้าระบบกำไรสินค้าแล้ว {_sync_result['synced_orders']} ออเดอร์"
                if _sync_result.get("unmatched"):
                    _msg += f" · ⚠️ {len(_sync_result['unmatched'])} ออเดอร์แกะสินค้าไม่ได้ (ดูที่แท็บ '⚠️ ตรวจสอบปัญหา')"
                _set_flash("_ecom_tiktok_import_msg", "success", _msg)
            st.session_state["_ecom_tiktok_file_ver"] = _tt_ver + 1
        st.rerun()

    st.divider()

    st.markdown("**💰 ยอดขายสุทธิระดับออเดอร์ (Income)**")
    st.caption(
        "รายงานยอดขายสุทธิทั้งร้าน (TikTok Shop Seller Center → การเงิน → รายได้ → Export "
        "→ ชีต \"รายละเอียดคำสั่งซื้อ\") ครอบคลุมทุกออเดอร์ (ไม่ใช่แค่ที่มาจากนายหน้าเหมือน "
        "ด้านบน) เป็นยอดระดับออเดอร์ ไม่มีราคาต่อสินค้าในไฟล์นี้เอง — แต่เช็คข้อมูลจริงแล้วว่า "
        "ทุกออเดอร์ของร้านนี้มีแค่ 1 สินค้าต่อออเดอร์ ระบบเลยจับคู่ยอดสุทธิเข้ากับสินค้าแต่ละ "
        "SKU ให้อัตโนมัติได้ (ปุ่มด้านล่าง) แล้วดูกำไรจริงต่อสินค้าที่แท็บ '💰 ยอดขาย/กำไร' "
        "ได้เหมือน Shopee/Lazada"
    )
    _ti_ver = st.session_state.get("_ecom_tiktok_income_file_ver", 0)
    _show_flash("_ecom_tiktok_income_import_msg")
    _ti_file = st.file_uploader("ไฟล์ income...xlsx", type=["xlsx"], key=f"ecom_tiktok_income_file_{_ti_ver}")
    if _ti_file and st.button("นำเข้ารายงานยอดขายสุทธิ TikTok", key="ecom_import_tiktok_income", type="primary"):
        with st.spinner("กำลังอ่านไฟล์..."):
            _ti_rows = tiktok_income_import.parse_income_report(_ti_file, _tt_shop)
            if not _ti_rows:
                _set_flash("_ecom_tiktok_income_import_msg", "warning", "⚠️ ไม่พบข้อมูลในไฟล์")
            else:
                db.upsert_tiktok_order_income(_ti_rows)
                _msg = f"✅ นำเข้า {len(_ti_rows)} ออเดอร์แล้ว"
                # ซิงค์เข้าระบบกำไรสินค้าอัตโนมัติทันที (เดิมต้องกดปุ่มแยกด้านล่างเอง
                # ลืมกดได้ง่าย — ปุ่มด้านล่างยังอยู่ไว้เผื่อต้อง sync ซ้ำ)
                _sync_result = db.sync_tiktok_to_ecommerce(_tt_shop)
                if _sync_result["sales_rows"]:
                    _msg += f" · ซิงค์เข้าระบบกำไรสินค้าแล้ว {_sync_result['synced_orders']} ออเดอร์"
                if _sync_result.get("unmatched"):
                    _msg += f" · ⚠️ {len(_sync_result['unmatched'])} ออเดอร์แกะสินค้าไม่ได้ (ดูที่แท็บ '⚠️ ตรวจสอบปัญหา')"
                _set_flash("_ecom_tiktok_income_import_msg", "success", _msg)
            st.session_state["_ecom_tiktok_income_file_ver"] = _ti_ver + 1
        st.rerun()

    st.divider()

    st.markdown("**🚫 สถานะยกเลิก/คืนพัสดุ**")
    st.caption(
        "รายงาน \"คำสั่งซื้อ > ทั้งหมด > Export ทุกคอลัมน์\" (ชีต \"OrderSKUList\") — ใช้แค่ "
        "ตรวจว่าออเดอร์ไหนถูกยกเลิกจริง (พัสดุ COD ที่ลูกค้าปฏิเสธ/ถูกตีกลับ ฯลฯ) เพราะไฟล์ "
        "ค่าคอมนายหน้า/ยอดขายสุทธิด้านบนไม่มีคำว่า \"ยกเลิกแล้ว\" ตรงๆ เลย ทำให้ออเดอร์ที่ยกเลิก "
        "จริงเคยถูกนับเป็นขาดทุนเต็มต้นทุนมาตลอด (พบ 2026-09-05) — อัปโหลดไฟล์นี้ทุกครั้งหลัง "
        "อัปเดตค่าคอมนายหน้า/ยอดขายสุทธิด้านบน เพื่อแก้ยอดขาดทุนให้ตรงจริง"
    )
    _ts_ver = st.session_state.get("_ecom_tiktok_status_file_ver", 0)
    _show_flash("_ecom_tiktok_status_import_msg")
    _ts_file = st.file_uploader("ไฟล์ทั้งหมด คำสั่งซื้อ...xlsx", type=["xlsx"], key=f"ecom_tiktok_status_file_{_ts_ver}")
    if _ts_file and st.button("นำเข้าสถานะยกเลิก TikTok", key="ecom_import_tiktok_status", type="primary"):
        with st.spinner("กำลังอ่านไฟล์..."):
            _status_map = tiktok_order_status_import.parse_order_statuses(_ts_file)
            if not _status_map:
                _set_flash("_ecom_tiktok_status_import_msg", "warning", "⚠️ ไม่พบข้อมูลในไฟล์ (เช็คว่าเลือกชีต \"ทุกคอลัมน์\" ตอน Export)")
            else:
                _fix_result = db.reconcile_tiktok_cancelled_orders(_status_map, _tt_shop)
                _n_cancelled = sum(1 for s in _status_map.values() if s == "ยกเลิกแล้ว")
                _msg = f"✅ พบ {_n_cancelled} ออเดอร์ที่ยกเลิกแล้วในไฟล์ · แก้สถานะ {_fix_result['affiliate_fixed'] + _fix_result['income_fixed']} รายการในระบบ"
                _sync_result = db.sync_tiktok_to_ecommerce(_tt_shop)
                if _sync_result["sales_rows"]:
                    _msg += f" · ซิงค์กำไรใหม่แล้ว {_sync_result['synced_orders']} ออเดอร์"
                _set_flash("_ecom_tiktok_status_import_msg", "success", _msg)
            st.session_state["_ecom_tiktok_status_file_ver"] = _ts_ver + 1
        st.rerun()

    _ti_df = db.get_tiktok_order_income_df(_tt_shop)
    if not _ti_df.empty:
        st.caption(f"มีข้อมูลแล้ว {len(_ti_df):,} ออเดอร์")
        st.caption(
            "จับคู่ยอดสุทธิแต่ละออเดอร์เข้ากับสินค้า (SKU) — ใช้ข้อมูลนายหน้าด้านบนถ้ามี "
            "ไม่งั้นแกะจากคอลัมน์สินค้าที่อ้างอิงในไฟล์ (ใช้ได้เพราะทุกออเดอร์มีแค่ 1 สินค้า) "
            "ซิงค์อัตโนมัติทุกครั้งที่อัปโหลดไฟล์ด้านบนแล้ว — ไปจับคู่ SKU → สินค้าในระบบด้านบน "
            "(Map สินค้า → ระบบ) ก่อนดูกำไรที่แท็บ '💰 ยอดขาย/กำไร'"
        )
        _show_flash("_ecom_tiktok_sync_msg")
        _tt_pending = db.get_tiktok_pending_sync_count(_tt_shop)
        if _tt_pending:
            st.warning(f"⚠️ มี {_tt_pending} ออเดอร์ที่ยังไม่ได้ซิงค์เข้าระบบกำไรสินค้า — กดปุ่มด้านล่างเพื่อซิงค์")
        if st.button("🔗 ซิงค์ซ้ำทั้งหมด (ปกติไม่ต้องกด — ซิงค์อัตโนมัติแล้วตอนอัปโหลด)", key="ecom_tiktok_sync"):
            with st.spinner("กำลังซิงค์... (ประมวลผลประวัติทั้งหมดของร้านนี้ อาจใช้เวลาสักครู่ถ้ามีออเดอร์เยอะ)"):
                _sync_result = db.sync_tiktok_to_ecommerce(_tt_shop)
            _n_unmatched = len(_sync_result.get("unmatched") or [])
            if _sync_result["sales_rows"]:
                _msg = f"✅ ซิงค์แล้ว {_sync_result['synced_orders']} ออเดอร์ ({_sync_result['sales_rows']} รายการสินค้า)"
                _kind = "success"
            else:
                _msg = "⚠️ ไม่มีออเดอร์ที่ซิงค์ได้ — ยังไม่มีรายงานยอดขายสุทธิ (Income) ของร้านนี้"
                _kind = "warning"
            if _n_unmatched:
                _msg += (f"\n\n⚠️ มี {_n_unmatched} ออเดอร์ที่แกะสินค้าจาก product_summary "
                         "ไม่ได้ ข้ามไปไม่นับเข้าเลย — ดูรายการที่แท็บ '⚠️ ตรวจสอบปัญหา'")
                _kind = "warning"
            _set_flash("_ecom_tiktok_sync_msg", _kind, _msg)
            st.rerun()


def _render_tiktok_affiliate():
    st.subheader("🎥 ค่าคอมนายหน้า (Affiliate)")
    _tt_pending = db.get_tiktok_pending_sync_count()
    if _tt_pending:
        st.warning(
            f"⚠️ มี {_tt_pending} ออเดอร์ TikTok ที่ยังไม่ได้ซิงค์เข้าระบบกำไรสินค้า "
            "(ตัวเลขในแท็บ '💰 ยอดขาย/กำไร' ยังไม่รวมออเดอร์เหล่านี้) — ไปกดซิงค์ที่แท็บ "
            "'📥 นำเข้าข้อมูล' ก่อน"
        )
    _tt_df = db.get_tiktok_affiliate_orders_df()
    if _tt_df.empty:
        st.info("ยังไม่มีข้อมูล — อัปโหลดไฟล์ที่แท็บ '📥 นำเข้าข้อมูล' ก่อนครับ")
        return

    _tt_df["วันที่"] = pd.to_datetime(_tt_df["order_created_at"]).dt.strftime("%d/%m/%Y")

    # ตัดออเดอร์ "ไม่มีสิทธิ์" ออกทั้งหมด — สินค้าตีกลับ/คำสั่งซื้อไม่สมบูรณ์ ไม่ใช่ยอดขาย
    # จริง ไม่ควรโผล่ทั้งในตารางและยอดรวมทุกจุดของแท็บนี้
    _tt_df = _tt_df[_tt_df["order_status"] != "ไม่มีสิทธิ์"]
    if _tt_df.empty:
        st.info("ยังไม่มีออเดอร์ที่มีสิทธิ์ได้ค่าคอม")
        return

    # คะแนน (PV) ต่อแถว = จำนวน x units_per_pack x points_per_unit ของสินค้าที่ map ไว้แล้ว
    # จับคู่ผ่าน sku_id (ไม่ใช่ product_code — เช็คข้อมูลจริงแล้วว่า product_code ในตารางนี้
    # คือรหัส SKU ตัวเลขยาวของ TikTok เอง ไม่ตรงกับ products.id เลย ส่วน sku_id ตรงกับคีย์
    # platform_item_id ที่ตั้งไว้แล้วใน "Map สินค้า → ระบบ" ของแท็บ ⚙️ ตั้งค่า)
    _tt_prod_map = db.get_ecommerce_product_map()
    _tt_points_by_id = {p["id"]: float(p.get("points_per_unit") or 0) for p in db.get_products()}

    def _tt_row_points(sku_id, qty):
        _m = _tt_prod_map.get(("tiktok", sku_id))
        if not _m:
            return 0.0
        return _tt_points_by_id.get(_m["product_id"], 0.0) * float(_m.get("units_per_pack") or 1) * (qty or 0)

    _render_tiktok_creator_summary(_tt_df)
    st.divider()
    _render_tiktok_order_detail(_tt_df, _tt_row_points)
    st.divider()
    _render_tiktok_billed_today(_tt_df, _tt_row_points)


def _render_tiktok_creator_summary(_tt_df):
    # ── สรุปยอดต่อนายหน้า ─────────────────────────────────────────────
    # นับเฉพาะออเดอร์ที่ยังไม่เปิดบิล — ที่เปิดบิลแล้วถือว่าจัดการเสร็จแล้ว ไม่ควรมาบวก
    # ค้างอยู่ในสรุปยอดที่ต้องตามนี้อีก
    st.subheader("สรุปยอดต่อนายหน้า")
    st.caption("นับเฉพาะออเดอร์ที่ยังไม่เปิดบิล — ที่เปิดบิลแล้วไม่รวมในสรุปนี้")
    _tt_unbilled_df = _tt_df[~_tt_df["billed_in_system"]]
    _tt_summary = _tt_unbilled_df.groupby("creator_username").agg(
        จำนวนออเดอร์=("order_id", "nunique"),
        ยอดขายรวม=("payment_amount", "sum"),
        ยอดนายหน้า=("commission_payable_actual", "sum"),
        ยอดที่เราได้โดยประมาณ=("net_amount", "sum"),
    ).reset_index().rename(columns={"creator_username": "นายหน้า"}).sort_values("ยอดนายหน้า", ascending=False)
    st.dataframe(
        _tt_summary.style.format({
            "ยอดขายรวม": "{:,.2f}", "ยอดนายหน้า": "{:,.2f}", "ยอดที่เราได้โดยประมาณ": "{:,.2f}",
        }),
        hide_index=True, width="stretch",
    )
    _tt_m1, _tt_m2, _tt_m3 = st.columns(3)
    with _tt_m1: _metric_card("ยอดขายรวม", f"{_tt_unbilled_df['payment_amount'].sum():,.0f} ฿")
    with _tt_m2: _metric_card("ยอดนายหน้ารวม", f"{_tt_unbilled_df['commission_payable_actual'].sum():,.2f} ฿")
    with _tt_m3: _metric_card("ยอดที่เราได้โดยประมาณ", f"{_tt_unbilled_df['net_amount'].sum():,.0f} ฿")


def _render_tiktok_order_detail(_tt_df, _tt_row_points):
    # ── รายละเอียดออเดอร์ + เปิดบิลแล้วหรือยัง ──────────────────────────
    # เปลี่ยนจากติ๊ก checkbox แล้วบันทึกทันที (เสี่ยงคลิกพลาด/auto-test แล้วเขียนข้อมูลจริง
    # โดยไม่ตั้งใจ — เกิดขึ้นจริงมาแล้ว) เป็นแบบ "เลือกแถว → ดูยอดรวม → กดยืนยัน" เหมือน
    # ตารางเลือกแถวใน ยอดค้าง/จัดการบิล (bill_detail_ui.py) — ไม่มีอะไรถูกบันทึกจนกว่าจะกดปุ่ม
    st.subheader("รายละเอียดออเดอร์")
    _tt_creators = ["ทั้งหมด"] + sorted(_tt_df["creator_username"].dropna().unique().tolist())
    _tt_creator_filter = st.selectbox("🔍 กรองตามนายหน้า", _tt_creators, key="ecom_tiktok_creator_filter")

    _tt_order_dates = pd.to_datetime(_tt_df["order_created_at"]).dt.date
    _tt_min_date, _tt_max_date = _tt_order_dates.min(), _tt_order_dates.max()
    _tt_dc1, _tt_dc2 = st.columns(2)
    _tt_date_from = _tt_dc1.date_input("📅 จาก (วันที่ออเดอร์)", value=_tt_min_date,
                                        min_value=_tt_min_date, max_value=_tt_max_date, key="ecom_tiktok_date_from")
    _tt_date_to = _tt_dc2.date_input("ถึง", value=_tt_max_date,
                                      min_value=_tt_min_date, max_value=_tt_max_date, key="ecom_tiktok_date_to")

    _tt_only_unbilled = st.checkbox("แสดงเฉพาะที่ยังไม่เปิดบิล", key="ecom_tiktok_only_unbilled")

    _tt_detail_df = _tt_df
    if _tt_creator_filter != "ทั้งหมด":
        _tt_detail_df = _tt_detail_df[_tt_detail_df["creator_username"] == _tt_creator_filter]
    _tt_detail_df = _tt_detail_df[
        (pd.to_datetime(_tt_detail_df["order_created_at"]).dt.date >= _tt_date_from)
        & (pd.to_datetime(_tt_detail_df["order_created_at"]).dt.date <= _tt_date_to)
    ]
    if _tt_only_unbilled:
        _tt_detail_df = _tt_detail_df[~_tt_detail_df["billed_in_system"]]
    _tt_detail_df = _tt_detail_df.sort_values("order_created_at", ascending=False).reset_index(drop=True)

    _tt_points_series = pd.Series(
        [_tt_row_points(sid, q) for sid, q in zip(_tt_detail_df["sku_id"], _tt_detail_df["qty"])],
        index=_tt_detail_df.index,
    )

    _tt_disp_cols = ["order_id", "sku_id", "วันที่", "item_name", "creator_username",
                      "payment_amount", "commission_payable_actual", "net_amount",
                      "order_status", "billed_in_system"]
    _tt_disp_df = _tt_detail_df[_tt_disp_cols].rename(columns={
        "order_id": "เลขที่ออเดอร์", "sku_id": "SKU", "item_name": "สินค้า",
        "creator_username": "นายหน้า", "payment_amount": "ยอดขาย",
        "commission_payable_actual": "ยอดนายหน้า", "net_amount": "ยอดที่เราได้โดยประมาณ",
        "order_status": "สถานะออเดอร์", "billed_in_system": "เปิดบิลแล้ว",
    }).reset_index(drop=True)

    # Streamlit ไม่รองรับปิดการเลือกเฉพาะบางแถวในตารางเดียวกัน (เลือกได้ทั้งตารางหรือไม่มีเลย)
    # เลยทำได้แค่ทำให้แถวที่เปิดบิลแล้วดูจางลง (เตือนสายตาว่าไม่ควรแตะอีก) ส่วนล็อกจริงๆ ทำ
    # ที่ปุ่ม "ยืนยันเปิดบิล" ด้านล่าง — ข้ามแถวที่เปิดบิลแล้วในสิ่งที่เลือกเสมอ ต่อให้ติ๊กไว้
    def _tt_dim_billed(row):
        _dim = "background-color:#f0f0ee;color:#b3b0a8"
        return [_dim] * len(row) if row["เปิดบิลแล้ว"] else [""] * len(row)

    st.caption('คลิกแถวเพื่อเลือก (Ctrl/Shift สำหรับหลายแถว) แล้วกด "ยืนยันเปิดบิล" ด้านล่าง — '
               'ยังไม่บันทึกจนกว่าจะกดยืนยัน (แถวจางๆ = เปิดบิลไปแล้ว แก้ไขอีกไม่ได้ผ่านปุ่มยืนยัน)')
    _tt_evt = st.dataframe(
        _tt_disp_df.style.format({
            "ยอดขาย": "{:,.2f}", "ยอดนายหน้า": "{:,.2f}", "ยอดที่เราได้โดยประมาณ": "{:,.2f}",
        }).apply(_tt_dim_billed, axis=1),
        hide_index=True, width="stretch",
        column_order=["เลขที่ออเดอร์", "วันที่", "สินค้า", "นายหน้า",
                      "ยอดขาย", "ยอดนายหน้า", "ยอดที่เราได้โดยประมาณ", "สถานะออเดอร์"],
        selection_mode="multi-row", on_select="rerun", key="ecom_tiktok_detail_select",
    )
    # clamp กัน index ค้างจากตารางรอบก่อนที่แถวเยอะกว่า (เช่นเพิ่งกดยืนยัน/ยกเลิกเปิดบิล
    # แล้วแถวหายไปเพราะเปิด "แสดงเฉพาะที่ยังไม่เปิดบิล" อยู่ — selection state ของ
    # st.dataframe ไม่ auto-clamp ตาม row count ใหม่ให้ ทำให้ .iloc[] เกินขอบเขตได้จริง)
    _tt_sel_idx = [i for i in (_tt_evt.selection.rows if hasattr(_tt_evt, "selection") else [])
                   if i < len(_tt_detail_df)]
    _tt_sel_rows = _tt_detail_df.iloc[_tt_sel_idx] if _tt_sel_idx else _tt_detail_df.iloc[0:0]
    _tt_sel_n = len(_tt_sel_idx)
    _tt_sel_points = _tt_points_series.iloc[_tt_sel_idx].sum() if _tt_sel_idx else 0.0

    st.markdown(f"**เลือกอยู่: {_tt_sel_n} รายการ**")
    _tt_s1, _tt_s2, _tt_s3 = st.columns(3)
    with _tt_s1: _metric_card("ยอดขายรวม", f"{_tt_sel_rows['payment_amount'].sum():,.0f} ฿")
    with _tt_s2: _metric_card("ยอดค่านายหน้ารวม", f"{_tt_sel_rows['commission_payable_actual'].sum():,.2f} ฿")
    with _tt_s3: _metric_card("คะแนนรวม", f"{_tt_sel_points:,.0f} PV")

    if _tt_sel_n > 0:
        # ใช้ชื่อ ASCII ตอน .agg() แล้วค่อย .rename() เป็นภาษาไทยทีหลัง — ห้ามใช้ข้อความไทย
        # เป็นชื่อ keyword argument ตรงๆ เพราะ Python normalize ชื่อ identifier (NFKC) แต่ไม่
        # normalize string literal ทำให้ "จำนวน" ที่มาจาก kwarg กับ "จำนวน" ที่พิมพ์เป็น
        # string literal ทีหลัง (เช่นใน sort_values/style.format) กลายเป็นคนละ string กันได้
        # แม้หน้าตาเหมือนกันทุกประการ — เจอจริงบน Streamlit Cloud (KeyError) ทั้งที่รันเทสต์
        # local ผ่านปกติ
        _tt_sel_by_product = _tt_sel_rows.groupby("item_name").agg(
            qty_sum=("qty", "sum"),
            sales_sum=("payment_amount", "sum"),
            comm_sum=("commission_payable_actual", "sum"),
        ).reset_index().rename(columns={
            "item_name": "สินค้า", "qty_sum": "จำนวน", "sales_sum": "ยอดขาย", "comm_sum": "ยอดนายหน้า",
        }).sort_values("จำนวน", ascending=False)
        st.dataframe(
            _tt_sel_by_product.style.format({"จำนวน": "{:,.0f}", "ยอดขาย": "{:,.2f}", "ยอดนายหน้า": "{:,.2f}"}),
            hide_index=True, width="stretch",
        )

    # แยกตามสถานะปัจจุบัน — ยืนยันเปิดบิล ทำงานเฉพาะแถวที่ยังไม่เปิดบิล (ข้ามที่เปิดแล้วเสมอ
    # แม้จะติ๊กไว้ในสิ่งที่เลือก), ยกเลิกเปิดบิล ทำงานเฉพาะแถวที่เปิดบิลแล้วเท่านั้น
    _tt_confirm_rows = _tt_sel_rows[~_tt_sel_rows["billed_in_system"]]
    _tt_undo_rows = _tt_sel_rows[_tt_sel_rows["billed_in_system"]]

    _tt_confirm_col, _tt_undo_col = st.columns(2)
    if _tt_confirm_col.button(f"✅ ยืนยันเปิดบิล ({len(_tt_confirm_rows)} รายการ)", type="primary", width="stretch",
                               disabled=len(_tt_confirm_rows) == 0, key="ecom_tiktok_confirm_bill"):
        for _, _tt_r in _tt_confirm_rows.iterrows():
            db.set_tiktok_affiliate_billed(_tt_r["order_id"], _tt_r["sku_id"], True)
        st.success(f"✅ เปิดบิลแล้ว {len(_tt_confirm_rows)} รายการ")
        st.rerun()
    if _tt_undo_col.button(f"↩️ ยกเลิกเปิดบิลที่เลือก ({len(_tt_undo_rows)} รายการ)", width="stretch",
                            disabled=len(_tt_undo_rows) == 0, key="ecom_tiktok_undo_bill"):
        for _, _tt_r in _tt_undo_rows.iterrows():
            db.set_tiktok_affiliate_billed(_tt_r["order_id"], _tt_r["sku_id"], False)
        st.success(f"↩️ ยกเลิกเปิดบิลแล้ว {len(_tt_undo_rows)} รายการ")
        st.rerun()


def _render_tiktok_billed_today(_tt_df, _tt_row_points):
    # ── สรุปเปิดบิลไปแล้ววันนี้ — อิง billed_at จริงจาก DB (ไม่ใช่ session_state) เลย
    # ยืนอยู่ได้แม้รีเฟรช/ปิดหน้าไปแล้วเปิดใหม่ ต้องรัน tiktok_affiliate_billed_at_setup.sql
    # ใน Supabase ก่อนคอลัมน์ billed_at ถึงจะมี — ถ้ายังไม่มีคอลัมน์นี้ ส่วนนี้จะไม่โชว์อะไรเลย
    if "billed_at" in _tt_df.columns:
        _tt_today_str = date.today().isoformat()
        _tt_billed_today = _tt_df[_tt_df["billed_at"].astype(str).str.startswith(_tt_today_str, na=False)]
        if not _tt_billed_today.empty:
            _tt_bt_points = sum(_tt_row_points(sid, q) for sid, q in
                                 zip(_tt_billed_today["sku_id"], _tt_billed_today["qty"]))
            st.markdown(f"**📅 เปิดบิลไปแล้ววันนี้: {len(_tt_billed_today)} รายการ**")
            _tt_bt1, _tt_bt2, _tt_bt3 = st.columns(3)
            with _tt_bt1: _metric_card("ยอดขายรวม", f"{_tt_billed_today['payment_amount'].sum():,.0f} ฿")
            with _tt_bt2: _metric_card("ยอดค่านายหน้ารวม", f"{_tt_billed_today['commission_payable_actual'].sum():,.2f} ฿")
            with _tt_bt3: _metric_card("คะแนนรวม", f"{_tt_bt_points:,.0f} PV")


_PROFIT_GREEN = "#14874e"   # ตรงกับ --tby-green ใน app.py
_LOSS_RED     = "#a83634"   # ตรงกับ --tby-badge-bad-fg ใน app.py
_PLATFORM_BRAND = {"shopee": ("#ee4d2d", "#fff"), "lazada": ("#0f156d", "#fff"), "tiktok": ("#111418", "#fff")}


def _metric_card(label: str, value: str, value_color: str = "var(--tby-text)", sub: str = "", sub_color: str = "var(--tby-muted)"):
    st.markdown(f"""
    <div style="background:#fff;border:1px solid var(--tby-border);border-radius:11px;padding:15px 17px;margin-bottom:10px">
      <div style="font:600 12.5px 'Sarabun',sans-serif;color:var(--tby-muted)">{label}</div>
      <div style="font:700 24px 'Prompt',sans-serif;margin-top:5px;color:{value_color};white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{value}</div>
      <div style="font:600 12px 'Sarabun',sans-serif;margin-top:4px;color:{sub_color}">{sub}</div>
    </div>
    """, unsafe_allow_html=True)


def _render_platform_totals_banner(date_from: str, date_to: str):
    _plat_totals = db.get_ecommerce_platform_totals_df(date_from, date_to)
    if _plat_totals.empty:
        return
    st.markdown("**ยอดขายแต่ละช่องทาง**")
    _total_sales_all = _plat_totals["ยอดขาย"].sum() or 1
    _rows = _plat_totals.sort_values("ยอดขาย", ascending=False).to_dict("records")
    _cols = st.columns(len(_rows))
    for _col, _r in zip(_cols, _rows):
        _bg, _fg = _PLATFORM_BRAND.get(_r["platform"], ("var(--tby-muted)", "#fff"))
        _pct = _r["ยอดขาย"] / _total_sales_all * 100
        _label = _PLATFORMS.get(_r["platform"], _r["platform"])
        with _col:
            st.markdown(f"""
            <div style="border-radius:10px;padding:16px 18px;background:{_bg};color:{_fg};text-align:center">
              <div style="font:700 15px 'Sarabun',sans-serif">{_label} · {_pct:.0f}%</div>
              <div style="font:600 13px 'Sarabun',sans-serif;opacity:0.9;margin-top:4px">฿{_r['ยอดขาย']:,.0f} · {_r['จำนวนชิ้น']:,.0f} ชิ้น</div>
            </div>
            """, unsafe_allow_html=True)


def _render_combined_summary(date_from: str, date_to: str):
    """ภาพรวมกำไร/ขาดทุน/PV รวมทุกแพลตฟอร์ม (Shopee/Lazada/TikTok ทุกร้าน) ในช่วงเวลาเดียว —
    ตอบคำถาม "ทั้งหมดขาดทุนหรือเปล่า / มีคะแนนรวมเท่าไหร่" โดยไม่ต้องสลับแพลตฟอร์มเอง
    (radio ด้านล่างยังกรองทีละแพลตฟอร์มเหมือนเดิมสำหรับดูรายละเอียด)"""
    summary = db.get_ecommerce_combined_summary(date_from, date_to)
    if not summary["total_profit"] and not summary["total_loss"] and not summary["total_pv"]:
        return

    st.markdown("**ภาพรวมทุกช่องทางรวมกัน**")
    _cols = st.columns(4)
    with _cols[0]: _metric_card("กำไรรวม (ทุกช่องทาง)", f"฿{summary['total_profit']:,.0f}", _PROFIT_GREEN)
    with _cols[1]: _metric_card("ขาดทุนรวม (ทุกช่องทาง)", f"฿{summary['total_loss']:,.0f}", _LOSS_RED)
    with _cols[2]: _metric_card("สุทธิ", f"฿{summary['net']:,.0f}", _PROFIT_GREEN if summary["net"] >= 0 else _LOSS_RED)
    with _cols[3]: _metric_card("คะแนนรวม (PV)", f"{summary['total_pv']:,.0f} PV")

    if summary["pending_qty"]:
        _since = summary.get("pending_since")
        _since_txt = f" (ค้างมาตั้งแต่ {pd.to_datetime(_since).strftime('%d/%m/%Y')})" if _since else ""
        st.caption(f"ℹ️ มี {summary['pending_qty']:,} ชิ้น ที่ขายแล้วแต่ยังไม่มีรายงาน Income มายืนยัน{_since_txt} — ยังไม่รวมในตัวเลขข้างบน (ปกติออเดอร์จะส่งมาก่อน แล้ว Income จะตามมาทีหลังหลายอาทิตย์)")

    _loss_products = summary["loss_products_df"]
    _loss_orders = summary["loss_orders_df"]

    if _loss_products.empty and _loss_orders.empty:
        st.success("✅ ไม่พบสินค้า/ออเดอร์ที่ขาดทุนในช่วงนี้ (ทุกช่องทาง)")
        return

    # การ์ดใหญ่ต่อสินค้า อ่านง่ายกว่าตารางดิบ — ดูปุ๊บรู้เลยว่าสินค้าไหนขาดทุน
    # ขาดทุนเท่าไหร่/ชิ้น ต้องขายเท่าไหร่ถึงคุ้มทุน โดยไม่ต้องไล่เลขออเดอร์ทีละแถว
    if not _loss_products.empty:
        st.markdown("**⚠️ สินค้าที่ขาดทุนสะสม (รวมทุกช่องทาง)**")
        _pc = st.columns(min(len(_loss_products), 3))
        for _i, (_, _r) in enumerate(_loss_products.iterrows()):
            with _pc[_i % len(_pc)]:
                _breakeven = _r.get("ราคาขายสุทธิที่ควรได้ต่อชิ้น (คุ้มทุน)") or 0
                st.markdown(f"""
                <div style="background:var(--tby-badge-bad-bg);border:1px solid {_LOSS_RED};border-radius:12px;padding:16px 18px;margin-bottom:10px">
                  <div style="display:flex;justify-content:space-between;gap:10px">
                    <span style="font:700 15px 'Sarabun',sans-serif">{_r['ชื่อสินค้า']}</span>
                    <span style="font:600 11px 'Sarabun',sans-serif;color:var(--tby-muted)">{_r['แพลตฟอร์ม']}</span>
                  </div>
                  <div style="margin-top:8px"><span style="font:700 26px 'Prompt',sans-serif;color:{_LOSS_RED}">฿{_r['กำไร/ชิ้น']:,.1f}</span> <span style="font:600 13px 'Sarabun',sans-serif;color:var(--tby-muted)">/ ชิ้น</span></div>
                  <div style="font:500 12.5px 'Sarabun',sans-serif;color:var(--tby-muted);margin-top:6px">ขาย {_r['ขาย (ชิ้น)']:,.0f} ชิ้น · ขาดทุนรวม ฿{abs(_r['กำไรรวม']):,.0f} · คุ้มทุนที่ ฿{_breakeven:,.1f}</div>
                </div>
                """, unsafe_allow_html=True)

    if not _loss_orders.empty:
        with st.expander(f"ดูรายละเอียดทุกออเดอร์ที่ขาดทุน ({len(_loss_orders)} ออเดอร์)"):
            st.caption("รายออเดอร์ (ไม่ใช่สรุปรวมสินค้าด้านบน) — ใช้ไล่เช็คว่าออเดอร์ไหนกันแน่ที่ขาดทุน")
            st.dataframe(
                _loss_orders.style.format({"ต้นทุนรวม": "{:,.2f}", "ยอดเงินที่ได้รับจริง": "{:,.2f}", "กำไร": "{:,.2f}"}),
                width="stretch", hide_index=True,
            )


def _render_sales_profit():
    margin_from, margin_to, (mc3,) = _date_range_inputs("ecom_margin", n_cols=3)
    margin_warn_pct = mc3.number_input("เตือนถ้ากำไร < กี่ % ของยอดโอน", min_value=0, max_value=100, value=10, key="ecom_margin_warn_pct")

    _render_combined_summary(str(margin_from), str(margin_to))
    st.divider()

    _render_platform_totals_banner(str(margin_from), str(margin_to))
    st.divider()

    # ช่องทาง: ตัวกรองเดียว "ทั้งหมด" + รายร้าน (ไม่ใช่แท็บแยกแพลตฟอร์มเหมือนเดิม — เดิม
    # ต้องสลับแพลตฟอร์มทีละอันเพื่อดู ทำให้ต้องเห็นสรุป/การ์ดขาดทุนซ้ำกับด้านบนสุดของหน้า
    # ทุกครั้ง เลือก "ทั้งหมด" แล้วดูตารางเดียวรวมทุกช่องทางแทน ไม่ต้องเทียบเคียงข้างกัน)
    _shops = db.get_ecommerce_shops()
    _scope_opts = ["🌐 ทั้งหมด (ทุกช่องทาง)"] + [f"{_PLATFORMS.get(s['platform'], s['platform'])} — {s['shop_name']}" for s in _shops]
    _scope_map = {opt: (s["platform"], s["shop_name"]) for opt, s in zip(_scope_opts[1:], _shops)}
    _sel_scope = st.selectbox("ช่องทาง", _scope_opts, key="ecom_profit_scope")
    _platform, _shop_filter = _scope_map.get(_sel_scope, (None, None))

    if _platform is not None:
        _unmapped_n = len(db.get_unmapped_ecommerce_items(_platform))
        if _unmapped_n:
            st.warning(f"⚠️ มี {_unmapped_n} รายการสินค้าที่ยังไม่ได้ map — ยอดขาย/กำไรของรายการนี้ยังไม่ถูกนับ ไปที่แท็บ '⚙️ ตั้งค่า' เพื่อ map สินค้า")

        if _platform == "tiktok":
            _tt_pending = db.get_tiktok_pending_sync_count()
            if _tt_pending:
                st.warning(f"⚠️ มี {_tt_pending} ออเดอร์ TikTok ค้างซิงค์ — ตัวเลขด้านล่างยังไม่รวมออเดอร์เหล่านี้ (ไปกดซิงค์ที่แท็บ '📥 นำเข้าข้อมูล')")

    # "ค่าส่งเกิน" มีเฉพาะ Shopee (แพลตฟอร์มเดียวที่ไฟล์ export มีข้อมูลค่าส่ง) — ไม่ใส่ตัวเลือก
    # นี้ตอนเลือก "ทั้งหมด"/แพลตฟอร์มอื่น กันไม่ให้กดแล้วเจอหน้าว่างเปล่า
    _view_opts = ["💰 กำไรต่อสินค้า", "📦 จำนวนที่ขาย"]
    if _platform == "shopee":
        _view_opts.append("🚚 ค่าส่งเกิน")
    _view = _pills(_view_opts, f"ecom_profit_view_{_platform or 'all'}")

    st.divider()

    if _view == "🚚 ค่าส่งเกิน":
        _render_ecom_shipping_view(_platform, _shop_filter)
    else:
        if _platform is None:
            margin_df, pending_qty, pending_since = db.get_ecommerce_product_margin_df_all(str(margin_from), str(margin_to))
        else:
            margin_df, pending_qty, pending_since = db.get_ecommerce_product_margin_df(str(margin_from), str(margin_to), platform=_platform, shop_name=_shop_filter)
            # db.get_ecommerce_product_margin_df() ตั้งชื่อคอลัมน์ตามแพลตฟอร์มจริง
            # (เช่น "ขายผ่าน Lazada (ชิ้น)") — เปลี่ยนเป็นชื่อกลางให้ใช้ร่วมกันทุก view
            margin_df = margin_df.rename(columns={f"ขายผ่าน {_PLATFORMS.get(_platform, _platform)} (ชิ้น)": "ขาย (ชิ้น)"})
        # เลือก "ทั้งหมด" ข้อความค้างโอนซ้ำกับ _render_combined_summary ด้านบนสุดของหน้าแล้ว
        # (ตัวเลขเดียวกัน) — โชว์แค่ตอนดูเฉพาะช่องทางเดียวเพื่อไม่ให้ซ้ำ
        if pending_qty and _platform is not None:
            _since_txt = f" (ค้างมาตั้งแต่ {pd.to_datetime(pending_since).strftime('%d/%m/%Y')})" if pending_since else ""
            st.info(f"ℹ️ มี {pending_qty:,} ชิ้น ที่ขายแล้วแต่ยังไม่มีรายงานยอดโอน (Income) มายืนยัน{_since_txt} — ยังไม่รวมในตารางด้านล่าง (ปกติออเดอร์จะส่งมาก่อน แล้ว Income จะตามมาทีหลังหลายอาทิตย์ — อัปโหลดรายงาน Income ของช่วงที่ครอบคลุมออเดอร์เหล่านี้เพิ่มเพื่อให้เห็นครบ)")
        if margin_df.empty:
            st.info("ยังไม่มีข้อมูล หรือยังไม่ได้ map สินค้า (แท็บ '⚙️ ตั้งค่า' → Map สินค้า)")
        else:
            if _view == "💰 กำไรต่อสินค้า":
                _render_ecom_profit_view(margin_df, margin_warn_pct, _platform, margin_from, margin_to, _shop_filter)
            else:
                _render_ecom_units_view(margin_df, _platform, margin_from, margin_to, _shop_filter)

    st.divider()

    # ── ยอดขาย E-commerce (รายการดิบ) ────────────────────────────────────
    with st.expander("ดูยอดขาย E-commerce (รายการดิบ)"):
        view_from, view_to, _ = _date_range_inputs("ecom_v")
        ecom_df = db.get_ecommerce_sales_df(str(view_from), str(view_to), platform=_platform, shop_name=_shop_filter)
        if ecom_df.empty:
            st.info("ยังไม่มีข้อมูล — อัปโหลดรายงานคำสั่งซื้อก่อนครับ (แท็บ '📥 นำเข้าข้อมูล')")
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


def _render_ecom_profit_view(margin_df, margin_warn_pct, platform, date_from, date_to, shop_filter):
    _all_channels = platform is None
    if _all_channels:
        # "ทั้งหมด" ไม่โชว์การ์ดสรุป/สินค้าที่ต้องรีบแก้ซ้ำอีกรอบ — ตัวเลขเดียวกันเป๊ะกับ
        # การ์ด "ภาพรวมทุกช่องทางรวมกัน" ด้านบนสุดของหน้าแล้ว ข้ามไปที่ตารางรายละเอียดเลย
        st.caption("กำไร = ยอดเงินที่แต่ละแพลตฟอร์มโอนเข้าจริง (หลังหักค่าธรรมเนียม/ค่าส่ง/ภาษีแล้ว) − ต้นทุน × จำนวนที่ขาย — ดูตัวเลขสรุปรวมทุกช่องทางได้จากการ์ดด้านบนสุดของหน้า")
    else:
        st.caption(f"กำไร = ยอดเงินที่ {_PLATFORMS.get(platform, platform)} โอนเข้าจริง (หลังหักค่าธรรมเนียม/ค่าส่ง/ภาษีแล้ว) − ต้นทุน × จำนวนที่ขาย")

        _profit_summary = db.get_ecommerce_order_profit_summary(str(date_from), str(date_to), platform=platform, shop_name=shop_filter)
        _total_profit = _profit_summary["total_profit"]
        _total_loss   = _profit_summary["total_loss"]
        _net_total    = _profit_summary["net"]
        _total_qty    = margin_df["ขาย (ชิ้น)"].sum()
        _total_pv     = margin_df["PV"].sum()

        _cols = st.columns(5)
        with _cols[0]: _metric_card("กำไรรวม", f"฿{_total_profit:,.0f}", _PROFIT_GREEN)
        with _cols[1]: _metric_card("ขาดทุนรวม", f"฿{_total_loss:,.0f}", _LOSS_RED)
        with _cols[2]: _metric_card("สุทธิ", f"฿{_net_total:,.0f}", _PROFIT_GREEN if _net_total >= 0 else _LOSS_RED)
        with _cols[3]: _metric_card("ขายรวม", f"{_total_qty:,.0f} ชิ้น")
        with _cols[4]: _metric_card("PV รวม", f"{_total_pv:,.0f}")
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
        return "✅ ปกติ"
    margin_df = margin_df.copy()
    margin_df.insert(0, "สถานะ", margin_df.apply(_flag, axis=1))

    if not _all_channels:
        _loss_df = margin_df[margin_df["สถานะ"] == "🔴 ขาดทุน"]
        if not _loss_df.empty:
            st.markdown("**⚠️ สินค้าที่ต้องรีบแก้**")
            _pc = st.columns(min(len(_loss_df), 3))
            for _i, (_, _r) in enumerate(_loss_df.iterrows()):
                with _pc[_i % len(_pc)]:
                    _breakeven = _r.get("ราคาขายสุทธิที่ควรได้ต่อชิ้น (คุ้มทุน)") or 0
                    st.markdown(f"""
                    <div style="background:var(--tby-badge-bad-bg);border:1px solid {_LOSS_RED};border-radius:12px;padding:16px 18px;margin-bottom:10px">
                      <div style="display:flex;justify-content:space-between;gap:10px">
                        <span style="font:700 15px 'Sarabun',sans-serif">{_r['ชื่อสินค้า']}</span>
                        <span style="font:500 12px monospace;color:var(--tby-muted)">{_r['รหัสสินค้า']}</span>
                      </div>
                      <div style="margin-top:8px"><span style="font:700 26px 'Prompt',sans-serif;color:{_LOSS_RED}">฿{_r['กำไร/ชิ้น']:,.1f}</span> <span style="font:600 13px 'Sarabun',sans-serif;color:var(--tby-muted)">/ ชิ้น</span></div>
                      <div style="font:500 12.5px 'Sarabun',sans-serif;color:var(--tby-muted);margin-top:6px">ขาย {_r['ขาย (ชิ้น)']:,.0f} ชิ้น · ขาดทุนรวม ฿{abs(_r['กำไรรวม']):,.0f} · คุ้มทุนที่ ฿{_breakeven:,.1f}</div>
                    </div>
                    """, unsafe_allow_html=True)

    _seg_opts = [f"ทั้งหมด ({len(margin_df)})", f"🔴 ขาดทุน ({(margin_df['สถานะ'] == '🔴 ขาดทุน').sum()})",
                 f"🟡 กำไรต่ำ ({(margin_df['สถานะ'] == '🟡 กำไรต่ำ').sum()})", f"✅ ปกติ ({(margin_df['สถานะ'] == '✅ ปกติ').sum()})"]
    _status_map = {_seg_opts[1]: "🔴 ขาดทุน", _seg_opts[2]: "🟡 กำไรต่ำ", _seg_opts[3]: "✅ ปกติ"}
    st.markdown("**รายละเอียดกำไรต่อสินค้า**")
    _seg = _pills(_seg_opts, "ecom_profit_seg")
    _table_df = margin_df if _seg == _seg_opts[0] else margin_df[margin_df["สถานะ"] == _status_map.get(_seg, "")]

    st.dataframe(
        _table_df, width="stretch", hide_index=True,
        column_config={
            "ต้นทุน/ชิ้น": st.column_config.NumberColumn(format="%.2f ฿"),
            "ขาย (ชิ้น)": st.column_config.ProgressColumn(format="%d", min_value=0, max_value=int(margin_df["ขาย (ชิ้น)"].max() or 1)),
            "PV": st.column_config.NumberColumn(format="%.2f"),
            "ยอดเงินที่ได้รับจริง": st.column_config.NumberColumn(format="%.2f ฿"),
            "กำไรรวม": st.column_config.NumberColumn(format="%.2f ฿"),
            "กำไร/ชิ้น": st.column_config.NumberColumn(format="%.2f ฿"),
            "ราคาขายสุทธิที่ควรได้ต่อชิ้น (คุ้มทุน)": st.column_config.NumberColumn(format="%.2f ฿"),
        },
    )
    _n_loss = (margin_df["สถานะ"] == "🔴 ขาดทุน").sum()
    if _n_loss:
        st.warning(f"⚠️ มี {_n_loss} สินค้าที่ขาดทุนในช่วงนี้ — คอลัมน์ \"ราคาขายสุทธิที่ควรได้ต่อชิ้น (คุ้มทุน)\" คือราคาขายจริงเฉลี่ยหลังหักโค้ดส่วนลด/โปรโมชัน (ไม่ใช่ราคาที่ตั้งในหน้าสินค้า) ที่ต้องได้อย่างน้อยเท่านี้ถึงจะไม่ขาดทุน — ถ้ามักมีโค้ดส่วนลดมาหักอีก ราคาหน้าสินค้าอาจต้องตั้งสูงกว่านี้")

    if _all_channels:
        st.caption("ℹ️ เลือกช่องทางใดช่องทางหนึ่งด้านบน เพื่อดูสรุปยอดขาย/กำไรรายเดือนของช่องทางนั้น")
    else:
        with st.expander("📅 สรุปยอดขาย/กำไรรายเดือน"):
            monthly_df = db.get_ecommerce_monthly_summary(platform=platform, shop_name=shop_filter)
            if monthly_df.empty:
                st.info("ยังไม่มีข้อมูล")
            else:
                _max_net = float(monthly_df["สุทธิ"].abs().max() or 1)
                st.dataframe(
                    monthly_df, width="stretch", hide_index=True,
                    column_config={
                        "ยอดขาย": st.column_config.NumberColumn(format="%.2f ฿"),
                        "กำไรรวม": st.column_config.NumberColumn(format="%.2f ฿"),
                        "ขาดทุนรวม": st.column_config.NumberColumn(format="%.2f ฿"),
                        "สุทธิ": st.column_config.ProgressColumn(format="%.0f ฿", min_value=0.0, max_value=_max_net),
                    },
                )
                st.caption("กำไร/ขาดทุนคำนวณแบบรายออเดอร์ต่อเดือน (สูตรเดียวกับตัวเลขสรุปด้านบน) — เดือนที่ยังไม่มีรายงาน Income มายืนยันครบ ตัวเลขกำไรของเดือนนั้นอาจยังไม่นิ่ง")


def _render_ecom_units_view(margin_df, platform, date_from, date_to, shop_filter):
    _total_qty = margin_df["ขาย (ชิ้น)"].sum()
    _n_products = len(margin_df)
    _best = margin_df.loc[margin_df["ขาย (ชิ้น)"].idxmax()]

    _cols = st.columns(3)
    with _cols[0]: _metric_card("ขายรวม", f"{_total_qty:,.0f} ชิ้น")
    with _cols[1]: _metric_card("สินค้าที่ขายได้", f"{_n_products} รายการ")
    with _cols[2]: _metric_card("ขายดีสุด", _best["ชื่อสินค้า"], sub=f"{_best['ขาย (ชิ้น)']:,.0f} ชิ้น")

    st.markdown("**จำนวนที่ขาย ต่อสินค้า (เรียงมาก→น้อย)**")
    _unit_cols = ["ชื่อสินค้า", "รหัสสินค้า", "ขาย (ชิ้น)"]
    if "แพลตฟอร์ม" in margin_df.columns:
        _unit_cols.insert(0, "แพลตฟอร์ม")
    _units_df = margin_df[_unit_cols].sort_values("ขาย (ชิ้น)", ascending=False)
    st.dataframe(
        _units_df, width="stretch", hide_index=True,
        column_config={
            "ขาย (ชิ้น)": st.column_config.ProgressColumn(format="%d", min_value=0, max_value=int(_units_df["ขาย (ชิ้น)"].max() or 1)),
        },
    )

    if platform is None:
        st.caption("ℹ️ เลือกช่องทางใดช่องทางหนึ่งด้านบน เพื่อดูแนวโน้มจำนวนขายย้อนหลัง 6 เดือนของช่องทางนั้น")
    else:
        st.markdown("**แนวโน้มจำนวนที่ขาย (6 เดือนล่าสุด)**")
        _trend_df = db.get_ecommerce_units_trend_df(platform=platform, shop_name=shop_filter, months=6)
        if _trend_df.empty:
            st.info("ยังไม่มีข้อมูล")
        else:
            st.dataframe(_trend_df, width="stretch", hide_index=True)


def _render_ecom_shipping_view(platform, shop_filter):
    st.info("🚚 ตรวจเฉพาะช้อปปี้ — แพลตฟอร์มอื่นไม่มีข้อมูลค่าส่งในไฟล์ export")
    if platform != "shopee":
        # เผื่อไว้เฉยๆ — ตัวเลือก "ค่าส่งเกิน" ไม่โผล่ให้กดตั้งแต่แพลตฟอร์มอื่นแล้ว (ดูจุดเรียกใช้)
        return

    ship_from, ship_to, (sc3,) = _date_range_inputs("ecom_ship", n_cols=3, from_label="จาก (วันที่โอนเงิน)")
    ship_threshold = sc3.number_input("เกณฑ์ส่วนต่าง (บาท)", min_value=0.0, value=0.0, step=5.0, key="ecom_ship_threshold")

    overcharge_df = db.get_ecommerce_shipping_overcharge_df(
        str(ship_from), str(ship_to), platform="shopee", overcharge_threshold=ship_threshold, shop_name=shop_filter)
    if overcharge_df.empty:
        st.success("✅ ไม่พบออเดอร์ที่ค่าส่งเกินเกณฑ์ในช่วงนี้")
        return

    monthly_df = db.get_ecommerce_shipping_overcharge_monthly_df(
        str(ship_from), str(ship_to), platform="shopee", overcharge_threshold=ship_threshold, shop_name=shop_filter)

    _n = len(overcharge_df)
    _total_diff = overcharge_df["ส่วนต่างที่โดนหักเพิ่ม"].sum()
    _avg_diff = _total_diff / _n if _n else 0
    _worst_month = monthly_df.loc[monthly_df["ส่วนต่างรวม"].idxmax()] if not monthly_df.empty else None

    _cols = st.columns(4)
    with _cols[0]: _metric_card("ออเดอร์โดนหักเกิน", f"{_n:,}", _LOSS_RED, sub=f"เกณฑ์ ≥ ฿{ship_threshold:,.0f}")
    with _cols[1]: _metric_card("ส่วนต่างสะสม", f"฿{_total_diff:,.0f}", _LOSS_RED)
    with _cols[2]: _metric_card("เฉลี่ย/ออเดอร์", f"฿{_avg_diff:,.0f}")
    with _cols[3]:
        if _worst_month is not None:
            _metric_card("เดือนที่แย่สุด", str(_worst_month["เดือน"]), sub=f"฿{_worst_month['ส่วนต่างรวม']:,.0f} สะสม")

    if not monthly_df.empty:
        st.markdown("**ค่าส่งที่โดนหักเกิน รายเดือน**")
        st.dataframe(
            monthly_df, width="stretch", hide_index=True,
            column_config={"ส่วนต่างรวม": st.column_config.NumberColumn(format="%.0f ฿")},
        )

    st.markdown("**รายการที่โดนหักเกิน (เรียงมาก→น้อย)**")
    _max_diff = float(overcharge_df["ส่วนต่างที่โดนหักเพิ่ม"].max() or 1)
    st.dataframe(
        overcharge_df, width="stretch", hide_index=True,
        column_config={
            "ค่าส่งที่ประเมินไว้ (ผู้ซื้อ+Shopee)": st.column_config.NumberColumn(format="%.0f ฿"),
            "ค่าส่งที่หักจริง": st.column_config.NumberColumn(format="%.0f ฿"),
            "ส่วนต่างที่โดนหักเพิ่ม": st.column_config.ProgressColumn(format="฿%.0f", min_value=0.0, max_value=_max_diff),
        },
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

    # ── ออเดอร์ที่กำไรผิดปกติ (พร้อมเลขที่ออเดอร์) — หรือดูทุกออเดอร์ก็ได้ ──────
    st.subheader("ออเดอร์ที่กำไรผิดปกติ")
    st.caption("รายออเดอร์ (ไม่ใช่สรุปรวมสินค้า) — ใช้ไล่เช็คว่าออเดอร์ไหนกันแน่ที่ขาดทุน/กำไรต่ำ")
    anomaly_from, anomaly_to, (ac3,) = _date_range_inputs("ecom_anomaly", n_cols=3)
    anomaly_warn_pct = ac3.number_input("เตือนถ้ากำไร < กี่ % ของยอดโอน", min_value=0, max_value=100, value=10, key="ecom_anomaly_warn_pct")
    _show_all_orders = st.checkbox(
        "แสดงทุกออเดอร์ (ไม่ใช่แค่ที่ผิดปกติ) — เทียบราย ออเดอร์/สินค้า/ยอดที่ได้รับ/กำไร-ขาดทุน ทีละแถว",
        key="ecom_anomaly_show_all",
    )
    # ตั้ง warn_pct สูงพ้นช่วงจริง (margin % ไม่มีทางถึง) เพื่อให้ order_anomaly_rows
    # ไม่กรองออเดอร์ไหนออกเลย — ใช้ query เดิมซ้ำ ไม่ต้องเขียนฟังก์ชันใหม่
    _query_warn_pct = 1_000_000 if _show_all_orders else anomaly_warn_pct
    anomaly_df = db.get_ecommerce_order_anomaly_df(str(anomaly_from), str(anomaly_to), platform=_platform, warn_pct=_query_warn_pct, shop_name=_shop_filter)
    if anomaly_df.empty:
        st.success("✅ ไม่มีออเดอร์ในช่วงนี้" if _show_all_orders else "✅ ไม่พบออเดอร์ที่กำไรผิดปกติในช่วงนี้")
    else:
        if _show_all_orders:
            _n_loss = (anomaly_df["กำไร"] < 0).sum()
            st.info(f"ทั้งหมด {len(anomaly_df)} ออเดอร์ — ขาดทุน {_n_loss} · กำไร {len(anomaly_df) - _n_loss}")
        else:
            st.warning(f"⚠️ พบ {len(anomaly_df)} ออเดอร์ที่กำไรผิดปกติ")
        st.dataframe(
            anomaly_df.style.format({
                "ต้นทุนรวม": "{:,.2f}", "ยอดเงินที่ได้รับจริง": "{:,.2f}", "กำไร": "{:,.2f}",
            }),
            width="stretch", hide_index=True,
        )
        st.download_button(
            "⬇ Export Excel",
            _to_excel_bytes(anomaly_df, "ออเดอร์"),
            file_name=f"ecom_{_platform}_order_profit_{date.today().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="ecom_anomaly_export",
        )

    st.divider()

    # ── ออเดอร์คืนสินค้า/ยกเลิก + tracking ────────────────────────────────
    st.subheader("ออเดอร์คืนสินค้า/ยกเลิก + ติดตามพัสดุ")
    problem_df = db.get_ecommerce_problem_orders_df(platform=_platform, shop_name=_shop_filter)
    if problem_df.empty:
        st.success("✅ ไม่มีออเดอร์คืนสินค้า/ยกเลิกที่บันทึกไว้")
    else:
        st.dataframe(problem_df, width="stretch", hide_index=True)

    if _platform == "tiktok":
        st.divider()
        # ── TikTok organic ที่แกะสินค้าจาก product_summary ไม่ได้ ─────────
        st.subheader("TikTok: ออเดอร์ที่ยังไม่ถูกนับกำไร (แกะสินค้าไม่ได้)")
        st.caption(
            "ออเดอร์เหล่านี้มีข้อมูลยอดขายสุทธิ (income) แล้ว แต่ระบบแกะไม่ออกว่าเป็นสินค้าไหน "
            "จาก product_summary — กดปุ่มซิงค์ที่แท็บ '📥 นำเข้าข้อมูล' ไปก็จะยังไม่หาย "
            "ต้องเช็คไฟล์ income ต้นทางว่าคอลัมน์ 'รายละเอียดสินค้าที่ขายได้' ของออเดอร์นี้ ผิดปกติยังไง"
        )
        _tt_unmatched_df = db.get_tiktok_unmatched_organic_orders(_shop_filter)
        if _tt_unmatched_df.empty:
            st.success("✅ ไม่มีออเดอร์ที่แกะสินค้าไม่ได้")
        else:
            st.warning(f"⚠️ พบ {len(_tt_unmatched_df)} ออเดอร์")
            st.dataframe(_tt_unmatched_df, width="stretch", hide_index=True)
