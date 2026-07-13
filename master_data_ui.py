"""UI สำหรับแท็บ ⚙️ จัดการข้อมูล — แยกจาก app.py"""
import re
import io
import zipfile
import uuid

import streamlit as st
import pandas as pd
from datetime import date

import database as db

_MD_TABS = ["🏷️ สินค้า", "👤 ลูกค้า", "📍 ที่อยู่", "📐 ขนาดกล่อง"]


def render():
    try:
        _md_active = st.pills(" ", _MD_TABS, key="_md_active_sub", default=_MD_TABS[0], label_visibility="collapsed") or _MD_TABS[0]
    except AttributeError:
        _md_active = st.radio(" ", _MD_TABS, horizontal=True, key="_md_active_sub", label_visibility="collapsed")

    # ── Backup ──────────────────────────────────────────────────────────────
    with st.expander("💾 Backup ข้อมูล", expanded=False):
        st.caption("ดาวน์โหลดข้อมูลทั้งหมดเป็นไฟล์ ZIP (แนะนำทำทุกสิ้นเดือน)")
        if st.button("📦 สร้าง Backup ZIP", type="primary", key="backup_zip_btn"):
            _tables = {
                "customers":         db.get_supabase().table("customers").select("*").execute().data,
                "transactions":      db.get_supabase().table("transactions").select("*").execute().data,
                "partial_events":    db.get_supabase().table("partial_events").select("*").execute().data,
                "shipments":         db.get_supabase().table("shipments").select("*").execute().data,
                "products":          db.get_supabase().table("products").select("*").execute().data,
                "customer_addresses":db.get_supabase().table("customer_addresses").select("*").execute().data,
            }
            _zip_buf = io.BytesIO()
            with zipfile.ZipFile(_zip_buf, "w", zipfile.ZIP_DEFLATED) as _zf:
                for _tname, _rows in _tables.items():
                    _csv = pd.DataFrame(_rows).to_csv(index=False)
                    _zf.writestr(f"{_tname}.csv", _csv)
            _zip_buf.seek(0)
            _fname = f"backup_{date.today().strftime('%Y%m%d')}.zip"
            st.download_button(
                label=f"⬇️ ดาวน์โหลด {_fname}",
                data=_zip_buf.getvalue(),
                file_name=_fname,
                mime="application/zip",
                type="primary",
                width="stretch",
                key="backup_zip_dl",
            )

    with st.expander("📊 Export ยอดขายประจำเดือน", expanded=False):
        st.caption("export รายการขายทั้งหมดของเดือนที่เลือก พร้อมยอดชำระและยอดค้าง")
        _exp_col1, _exp_col2 = st.columns(2)
        _exp_year  = _exp_col1.number_input("ปี (พ.ศ.)", min_value=2567, max_value=2580,
                                             value=date.today().year + 543, step=1, key="exp_year")
        _exp_month = _exp_col2.selectbox("เดือน", list(range(1, 13)),
                                          format_func=lambda m: ["ม.ค.","ก.พ.","มี.ค.","เม.ย.","พ.ค.","มิ.ย.",
                                                                  "ก.ค.","ส.ค.","ก.ย.","ต.ค.","พ.ย.","ธ.ค."][m-1],
                                          index=date.today().month - 1, key="exp_month")
        _exp_year_ad = _exp_year - 543
        if st.button("📋 สร้าง Export", type="primary", key="exp_sales_btn"):
            _all_df = db.get_all_transactions_df()
            if _all_df.empty:
                st.warning("ไม่มีข้อมูล")
            else:
                _all_df["_dt"] = pd.to_datetime(_all_df["วันที่"], errors="coerce")
                _monthly = _all_df[
                    (_all_df["_dt"].dt.year  == _exp_year_ad) &
                    (_all_df["_dt"].dt.month == _exp_month)
                ].drop(columns=["_dt", "id", "เคลียร์แล้ว", "last_payment_date"], errors="ignore")
                if _monthly.empty:
                    st.warning(f"ไม่มีข้อมูลเดือน {_exp_month}/{_exp_year_ad}")
                else:
                    _exp_fname = f"sales_{_exp_year_ad}{_exp_month:02d}.csv"
                    st.download_button(
                        label=f"⬇️ ดาวน์โหลด {_exp_fname} ({len(_monthly)} รายการ)",
                        data=_monthly.to_csv(index=False).encode("utf-8-sig"),
                        file_name=_exp_fname,
                        mime="text/csv",
                        type="primary",
                        width="stretch",
                        key="exp_sales_dl",
                    )
    st.divider()

    if _md_active == _MD_TABS[0]:
        products = db.get_products()

        prod_cols = ["id", "name", "price", "points_per_unit", "bv_per_unit", "weight_grams", "max_units_per_box"]
        col_rename = {
            "id": "รหัส", "name": "ชื่อสินค้า", "price": "ราคา (บาท)",
            "points_per_unit": "PV/หน่วย", "bv_per_unit": "BV/หน่วย", "weight_grams": "น้ำหนัก (g)",
            "max_units_per_box": "จำนวนสูงสุด/กล่อง",
        }
        if products:
            prod_df = pd.DataFrame(products)
            for _c in prod_cols:
                if _c not in prod_df.columns:
                    prod_df[_c] = None
            prod_df = prod_df[prod_cols].rename(columns=col_rename)
        else:
            prod_df = pd.DataFrame(columns=list(col_rename.values()))

        st.write("**แก้ไขหรือเพิ่มสินค้า** — แก้ในตารางได้โดยตรง กด `+` ที่มุมล่างขวาเพื่อเพิ่มแถวใหม่")
        edited_prod_df = st.data_editor(
            prod_df,
            num_rows="dynamic",
            width="stretch",
            key="prod_editor",
            column_config={
                "รหัส":        st.column_config.TextColumn("รหัส", required=True),
                "ชื่อสินค้า":  st.column_config.TextColumn("ชื่อสินค้า", required=True),
                "ราคา (บาท)":  st.column_config.NumberColumn("ราคา (บาท)", min_value=0, step=10.0, format="%.2f"),
                "PV/หน่วย":    st.column_config.NumberColumn("PV/หน่วย",   min_value=0, step=1.0,  format="%.2f"),
                "BV/หน่วย":    st.column_config.NumberColumn("BV/หน่วย",   min_value=0, step=1.0,  format="%.2f"),
                "น้ำหนัก (g)": st.column_config.NumberColumn("น้ำหนัก (g)", min_value=0, step=10.0, format="%.0f"),
                "จำนวนสูงสุด/กล่อง": st.column_config.NumberColumn(
                    "จำนวนสูงสุด/กล่อง", min_value=0, step=1, format="%d",
                    help="จำนวนชิ้นสูงสุดต่อกล่อง (ทางกายภาพ) — เว้นว่าง = ไม่จำกัด ใช้น้ำหนักกล่องเป็นตัวจำกัดแทน",
                ),
            },
        )
        if st.button("💾 บันทึกทั้งหมด", key="save_prod_editor", width="stretch", type="primary"):
            valid = edited_prod_df.dropna(subset=["รหัส", "ชื่อสินค้า"])
            valid = valid[valid["รหัส"].astype(str).str.strip() != ""]
            if valid.empty:
                st.error("ไม่มีข้อมูลที่จะบันทึก")
            else:
                for _, row in valid.iterrows():
                    _max_units = row["จำนวนสูงสุด/กล่อง"]
                    db.upsert_product({
                        "id":                str(row["รหัส"]).strip(),
                        "name":              str(row["ชื่อสินค้า"]).strip(),
                        "price":             float(row["ราคา (บาท)"]  or 0),
                        "points_per_unit":   float(row["PV/หน่วย"]    or 0),
                        "bv_per_unit":       float(row["BV/หน่วย"]    or 0),
                        "weight_grams":      float(row["น้ำหนัก (g)"] or 0),
                        "max_units_per_box": (int(_max_units) if pd.notna(_max_units) and float(_max_units) > 0 else None),
                    })
                st.success(f"✅ บันทึก {len(valid)} รายการแล้ว")
                st.rerun()

        if products:
            with st.expander("🗑️ ลบสินค้า"):
                prod_opts = {f"{p['id']} — {p['name']}": p["id"] for p in products}
                pc1, pc2, pc3 = st.columns([4, 1, 1])
                with pc1:
                    del_prod = st.selectbox("เลือกสินค้า", list(prod_opts.keys()), key="delsel_prod")
                with pc2:
                    st.write("")
                    confirm_prod = st.checkbox("ยืนยัน", key="delchk_prod")
                with pc3:
                    st.write("")
                    if st.button("🗑️ ลบ", key="delbtn_prod", disabled=not confirm_prod, type="secondary"):
                        try:
                            db.delete_product(prod_opts[del_prod])
                            st.success("✅ ลบแล้ว")
                            st.rerun()
                        except Exception:
                            st.error("❌ ลบไม่ได้ — สินค้านี้มีรายการขายอยู่")

    elif _md_active == _MD_TABS[1]:
        customers = db.get_customers()
        if customers:
            cust_df = pd.DataFrame(customers)[["id", "name", "phone"]].rename(
                columns={"id": "รหัส", "name": "ชื่อลูกค้า", "phone": "เบอร์โทร"}
            )
        else:
            cust_df = pd.DataFrame(columns=["รหัส", "ชื่อลูกค้า", "เบอร์โทร"])

        # ── เรียงลำดับ ────────────────────────────────────────────────────
        _sort_by = st.radio("เรียงตาม", ["รหัส", "ชื่อลูกค้า"], horizontal=True, key="cust_sort")
        if not cust_df.empty:
            cust_df = cust_df.sort_values(_sort_by, ignore_index=True)

        st.write("**แก้ไขหรือเพิ่มลูกค้า** — แก้ในตารางได้โดยตรง กด `+` เพื่อเพิ่มแถวใหม่ (ไม่ต้องพิมพ์รหัส ระบบจะออกให้อัตโนมัติ)")
        edited_cust_df = st.data_editor(
            cust_df,
            num_rows="dynamic",
            width="stretch",
            key="cust_editor",
            column_config={
                "รหัส":       st.column_config.TextColumn("รหัส", help="เว้นว่างให้ระบบออกรหัสอัตโนมัติ"),
                "ชื่อลูกค้า": st.column_config.TextColumn("ชื่อลูกค้า", required=True),
                "เบอร์โทร":   st.column_config.TextColumn("เบอร์โทร"),
            },
        )
        if st.button("💾 บันทึกทั้งหมด", key="save_cust_editor", width="stretch", type="primary"):
            valid = edited_cust_df.dropna(subset=["ชื่อลูกค้า"]).copy()
            valid = valid[valid["ชื่อลูกค้า"].astype(str).str.strip() != ""]
            if valid.empty:
                st.error("ไม่มีข้อมูลที่จะบันทึก")
            else:
                # auto-generate รหัส C-XXX สำหรับแถวที่ไม่มีรหัส
                _all_ids = [c["id"] for c in db.get_customers()]
                _max_num = 0
                for _cid in _all_ids:
                    _m = re.match(r'C-(\d+)', str(_cid))
                    if _m:
                        _max_num = max(_max_num, int(_m.group(1)))
                for _i, _row in valid.iterrows():
                    _rid = str(_row.get("รหัส", "") or "").strip()
                    if not _rid or _rid == "nan":
                        _max_num += 1
                        valid.at[_i, "รหัส"] = f"C-{_max_num:03d}"
                for _, row in valid.iterrows():
                    db.upsert_customer({
                        "id":    str(row["รหัส"]).strip(),
                        "name":  str(row["ชื่อลูกค้า"]).strip(),
                        "phone": str(row["เบอร์โทร"]).strip() if pd.notna(row["เบอร์โทร"]) else "",
                    })
                st.success(f"✅ บันทึก {len(valid)} รายการแล้ว")
                st.rerun()

        if customers:
            with st.expander("🗑️ ลบลูกค้า"):
                cust_opts = {f"{c['id']} — {c['name']}": c["id"] for c in customers}
                cc1, cc2, cc3 = st.columns([4, 1, 1])
                with cc1:
                    del_cust = st.selectbox("เลือกลูกค้า", list(cust_opts.keys()), key="delsel_cust")
                with cc2:
                    st.write("")
                    confirm_cust = st.checkbox("ยืนยัน", key="delchk_cust")
                with cc3:
                    st.write("")
                    if st.button("🗑️ ลบ", key="delbtn_cust", disabled=not confirm_cust, type="secondary"):
                        try:
                            db.delete_customer(cust_opts[del_cust])
                            st.success("✅ ลบแล้ว")
                            st.rerun()
                        except Exception:
                            st.error("❌ ลบไม่ได้ — ลูกค้านี้มีรายการขายอยู่")

    elif _md_active == _MD_TABS[2]:
        # ── ค้นหาจากเบอร์ ──────────────────────────────────────────────────
        sa_ph, sa_btn = st.columns([3, 1])
        sa_phone = sa_ph.text_input("🔍 ค้นหาจากเบอร์โทร", max_chars=10,
                                    key="addr3_ph", placeholder="0XXXXXXXXX")
        try:
            all_addr = db.get_customer_addresses()
        except Exception:
            st.warning("⚙️ ยังไม่ได้สร้าง table customer_addresses ใน Supabase — รัน SQL ด้านล่างก่อน")
            st.code("""CREATE TABLE IF NOT EXISTS customer_addresses (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id   TEXT REFERENCES customers(id),
  recipient_name TEXT, phone TEXT,
  address_line  TEXT, district TEXT,
  amphure TEXT, province TEXT, postal_code TEXT
);""", language="sql")
            all_addr = []

        # กรองตามเบอร์ถ้ากรอก
        if sa_phone.strip():
            show_addr = [a for a in all_addr if sa_phone.strip() in (a.get("phone") or "")]
        else:
            show_addr = all_addr

        # ── ตาราง + checkbox ลบ ───────────────────────────────────────────
        if show_addr:
            _addr_ids = [a["id"] for a in show_addr]
            _addr_df = pd.DataFrame([{
                "ลบ":         False,
                "เบอร์":      a.get("phone", ""),
                "ชื่อผู้รับ": a.get("recipient_name", ""),
                "ที่อยู่":    f"{a.get('address_line','')} {a.get('district','')} {a.get('amphure','')} {a.get('province','')} {a.get('postal_code','')}".strip(),
                "ลูกค้า":    (a.get("customers") or {}).get("name", ""),
            } for a in show_addr])
            _edited_addr = st.data_editor(
                _addr_df,
                column_config={
                    "ลบ": st.column_config.CheckboxColumn("ลบ", default=False, width="small"),
                },
                disabled=["เบอร์", "ชื่อผู้รับ", "ที่อยู่", "ลูกค้า"],
                hide_index=True,
                width="stretch",
                key="addr_tbl",
            )
            _to_delete = [_addr_ids[i] for i, v in enumerate(_edited_addr["ลบ"]) if v]
            _checked_idx = [i for i, v in enumerate(_edited_addr["ลบ"]) if v]
            if len(_checked_idx) == 1:
                _sel_a = show_addr[_checked_idx[0]]
                _auto_key = f"{_sel_a.get('phone','')} — {_sel_a.get('recipient_name','')}"
                if st.session_state.get("addr3_edit_sel") != _auto_key:
                    st.session_state["addr3_edit_sel"] = _auto_key
                    st.rerun()
            if _to_delete:
                if st.button(f"🗑️ ลบที่เลือก ({len(_to_delete)} รายการ)", type="primary", key="del_checked_btn"):
                    for _did in _to_delete:
                        db.delete_customer_address(_did)
                    st.session_state.pop("addr_tbl", None)
                    st.rerun()
        else:
            st.info("ยังไม่มีที่อยู่" if not sa_phone.strip() else "ไม่พบเบอร์นี้")

        # ── แก้ไข / เพิ่ม ─────────────────────────────────────────────────
        all_custs = db.get_customers()
        with st.expander("✏️ เพิ่ม / แก้ไขที่อยู่"):
            addr_opts = {"— เพิ่มใหม่ —": None} | {
                f"{a.get('phone','')} — {a.get('recipient_name','')}": a
                for a in show_addr
            }
            sel_addr = st.selectbox("เลือกที่อยู่เพื่อแก้ไข หรือ เพิ่มใหม่",
                                    list(addr_opts.keys()), key="addr3_edit_sel")
            _ea = addr_opts[sel_addr] or {}
            cust_names3 = ["— เลือกลูกค้า —"] + [c["name"] for c in all_custs]
            _ea_cust_name = (_ea.get("customers") or {}).get("name", "")
            _ea_cust_idx  = cust_names3.index(_ea_cust_name) if _ea_cust_name in cust_names3 else 0
            # selectbox ลูกค้าอยู่นอก form เพื่อ reset ได้ถูกต้อง
            if st.session_state.get("_prev_addr_edit_sel") != sel_addr:
                st.session_state["_prev_addr_edit_sel"] = sel_addr
                st.session_state["ea3c_cust"] = cust_names3[_ea_cust_idx]
            ea3_cust = st.selectbox("ลูกค้า (ผู้ส่ง)", cust_names3, key="ea3c_cust")
            # form key เปลี่ยนตาม sel_addr เพื่อ reset field ข้างใน
            _form_key = f"addr3_edit_form_{sel_addr[:30]}"
            with st.form(_form_key):
                a1, a2 = st.columns(2)
                ea3_rn = a1.text_input("ชื่อผู้รับ",    value=_ea.get("recipient_name", ""))
                ea3_rp = a2.text_input("เบอร์โทร",      value=_ea.get("phone", ""))
                ea3_al = st.text_input("บ้านเลขที่/ถนน", value=_ea.get("address_line", ""))
                b1, b2, b3 = st.columns(3)
                ea3_dt = b1.text_input("ตำบล/แขวง",    value=_ea.get("district", ""))
                ea3_am = b2.text_input("อำเภอ/เขต",     value=_ea.get("amphure", ""))
                ea3_pv = b3.text_input("จังหวัด",        value=_ea.get("province", ""))
                ea3_pc = st.text_input("รหัสไปรษณีย์",   value=_ea.get("postal_code", ""), max_chars=5)
                if st.form_submit_button("💾 บันทึก", type="primary", width="stretch"):
                    _cur_cust = st.session_state.get("ea3c_cust", "— เลือกลูกค้า —")
                    _ea_cust_id = next((c["id"] for c in all_custs if c["name"] == _cur_cust), "")
                    if not _ea_cust_id:
                        st.error("กรุณาเลือกลูกค้าก่อนบันทึก")
                        st.stop()
                    try:
                        db.upsert_customer_address({
                            "id":             _ea.get("id") or str(uuid.uuid4()),
                            "customer_id":    _ea_cust_id,
                            "recipient_name": ea3_rn,
                            "phone":          ea3_rp,
                            "address_line":   ea3_al,
                            "district":       ea3_dt,
                            "amphure":        ea3_am,
                            "province":       ea3_pv,
                            "postal_code":    ea3_pc,
                        })
                    except Exception as _ea_e:
                        st.error(f"❌ บันทึกที่อยู่ไม่สำเร็จ: {_ea_e}")
                        st.stop()
                    st.success("✅ บันทึกแล้ว")
                    st.rerun()

    elif _md_active == _MD_TABS[3]:
        st.write("**preset ขนาดกล่อง** — ใช้ตอนเลือกขนส่งแบบ Bulky และหน้าปริ้นใบปะหน้า manual "
                 "แก้ในตารางได้โดยตรง กด `+` ที่มุมล่างขวาเพื่อเพิ่มแถวใหม่ แล้วกด **บันทึกทั้งหมด** "
                 "ค่าที่บันทึกจะเก็บถาวรและใช้ได้ทุกครั้งที่เปิดแอป")
        try:
            box_presets = db.get_box_presets()
        except Exception:
            st.warning("⚙️ ยังไม่ได้สร้างตาราง `box_presets` ใน Supabase — รัน SQL นี้ก่อน")
            st.code("""CREATE TABLE IF NOT EXISTS box_presets (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name       TEXT NOT NULL,
  length_cm  NUMERIC NOT NULL,
  width_cm   NUMERIC NOT NULL,
  height_cm  NUMERIC NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE box_presets DISABLE ROW LEVEL SECURITY;""", language="sql")
            box_presets = []

        _box_cols = ["name", "length_cm", "width_cm", "height_cm"]
        _box_rename = {"name": "ชื่อกล่อง", "length_cm": "ยาว (ซม.)", "width_cm": "กว้าง (ซม.)", "height_cm": "สูง (ซม.)"}
        if box_presets:
            box_df = pd.DataFrame(box_presets)[_box_cols].rename(columns=_box_rename)
        else:
            box_df = pd.DataFrame(columns=list(_box_rename.values()))

        edited_box_df = st.data_editor(
            box_df,
            num_rows="dynamic",
            width="stretch",
            hide_index=True,
            key="box_preset_editor",
            column_config={
                "ชื่อกล่อง":  st.column_config.TextColumn("ชื่อกล่อง", required=True),
                "ยาว (ซม.)":  st.column_config.NumberColumn("ยาว (ซม.)",  min_value=1, step=1, format="%d"),
                "กว้าง (ซม.)": st.column_config.NumberColumn("กว้าง (ซม.)", min_value=1, step=1, format="%d"),
                "สูง (ซม.)":  st.column_config.NumberColumn("สูง (ซม.)",  min_value=1, step=1, format="%d"),
            },
        )
        if st.button("💾 บันทึกทั้งหมด", key="save_box_preset_editor", width="stretch", type="primary"):
            valid = edited_box_df.dropna(subset=["ชื่อกล่อง", "ยาว (ซม.)", "กว้าง (ซม.)", "สูง (ซม.)"])
            valid = valid[valid["ชื่อกล่อง"].astype(str).str.strip() != ""]
            _new_presets = [{
                "name":      str(row["ชื่อกล่อง"]).strip(),
                "length_cm": float(row["ยาว (ซม.)"]),
                "width_cm":  float(row["กว้าง (ซม.)"]),
                "height_cm": float(row["สูง (ซม.)"]),
            } for _, row in valid.iterrows()]
            try:
                db.replace_box_presets(_new_presets)
                st.success(f"✅ บันทึก {len(_new_presets)} ขนาดกล่องแล้ว")
                st.rerun()
            except Exception as _box_e:
                st.error(f"❌ บันทึกไม่สำเร็จ: {_box_e}")
