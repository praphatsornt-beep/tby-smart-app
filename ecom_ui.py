"""UI สำหรับแท็บ E-commerce (Shopee) — แยกจาก app.py"""
import datetime as _dt
import uuid

import streamlit as st
import pandas as pd
from datetime import date

import database as db
import shopee_api


def render():
    st.subheader("🛒 E-commerce — Shopee")

    if not shopee_api.is_configured():
        st.warning("⚙️ ยังไม่ได้ตั้งค่า Shopee Partner ID/Key — กรอกใน `.streamlit/secrets.toml` ก่อนครับ")
        st.code('SHOPEE_PARTNER_ID = "12345"\nSHOPEE_PARTNER_KEY = "xxxxx"', language="toml")
        return

    # ── Section 1: เชื่อมต่อร้าน ────────────────────────────────────────
    st.markdown("### 1. เชื่อมต่อร้าน Shopee")
    redirect_url = st.text_input(
        "Redirect URL (URL ของแอปนี้)", value="https://your-app.streamlit.app",
        key="ecom_redirect", help="ต้องตรงกับที่ลงทะเบียนใน Shopee Open Platform"
    )
    auth_url = shopee_api.get_auth_url(redirect_url)
    st.link_button("🔗 Authorize ร้านใหม่", url=auth_url)
    st.caption("กดปุ่มด้านบน → เข้า Shopee → เลือกร้าน → ระบบจะ redirect กลับมาพร้อม token อัตโนมัติ")

    shops = db.get_ecommerce_shops()
    if shops:
        st.divider()
        shops_df = pd.DataFrame([{
            "ชื่อร้าน": s["shop_name"], "Shop ID": s["shop_id"],
            "Token หมดอายุ": (s.get("token_expiry") or "")[:16],
        } for s in shops])
        st.dataframe(shops_df, use_container_width=True, hide_index=True)

        # rename shop
        with st.expander("✏️ เปลี่ยนชื่อร้าน"):
            for s in shops:
                new_name = st.text_input(f"Shop ID {s['shop_id']}", value=s["shop_name"], key=f"sname_{s['id']}")
                if new_name != s["shop_name"] and st.button("บันทึก", key=f"sname_btn_{s['id']}"):
                    s["shop_name"] = new_name
                    db.upsert_ecommerce_shop(s)
                    st.rerun()

    st.divider()

    # ── Section 2: Sync orders ────────────────────────────────────────────
    st.markdown("### 2. ดึงยอดขาย (Sync)")
    if not shops:
        st.info("เพิ่มร้านก่อนครับ")
    else:
        shop_options = {s["shop_name"]: s for s in shops}
        sel_shops = st.multiselect("เลือกร้าน", list(shop_options.keys()), default=list(shop_options.keys()), key="ecom_shops_sel")
        sc1, sc2 = st.columns(2)
        sync_from = sc1.date_input("วันที่เริ่ม", value=date.today().replace(day=1), key="sync_from")
        sync_to   = sc2.date_input("ถึง", value=date.today(), key="sync_to")

        if st.button("🔄 Sync Orders", type="primary", use_container_width=True, key="ecom_sync"):
            prod_map     = db.get_ecommerce_product_map()
            new_items    = []
            new_unmapped = []
            from_ts = int(_dt.datetime.combine(sync_from, _dt.time.min).timestamp())
            to_ts   = int(_dt.datetime.combine(sync_to,   _dt.time.max).timestamp())
            total   = len(sel_shops)

            _prog = st.progress(0, text=f"เตรียม sync {total} ร้าน...")
            with st.status(f"กำลัง sync {total} ร้าน...", expanded=True) as _sync_status:
                for idx, shop_name in enumerate(sel_shops):
                    _prog.progress(idx / total, text=f"กำลังดึง {shop_name} ({idx+1}/{total})...")
                    st.write(f"⏳ **{shop_name}** ({idx+1}/{total})...")
                    shop = shop_options[shop_name]

                    # refresh token ถ้าใกล้หมดอายุ
                    if shop.get("token_expiry"):
                        exp = _dt.datetime.fromisoformat(shop["token_expiry"].replace("Z", ""))
                        if exp - _dt.datetime.utcnow() < _dt.timedelta(hours=1):
                            r = shopee_api.do_refresh_token(shop["shop_id"], shop["refresh_token"])
                            if "access_token" in r:
                                shop["access_token"]  = r["access_token"]
                                shop["refresh_token"] = r["refresh_token"]
                                new_exp = _dt.datetime.utcnow() + _dt.timedelta(seconds=r.get("expire_in", 14400))
                                shop["token_expiry"] = new_exp.isoformat()
                                db.upsert_ecommerce_shop(shop)

                    orders = shopee_api.get_orders(shop["shop_id"], shop["access_token"], from_ts, to_ts)
                    if not orders:
                        st.write(f"⚪ **{shop_name}**: ไม่มี order ในช่วงนี้")
                        _prog.progress((idx + 1) / total, text=f"ดึง {shop_name} เสร็จ ({idx+1}/{total})")
                        continue

                    order_sns = [o["order_sn"] for o in orders]
                    details   = shopee_api.get_order_details(shop["shop_id"], shop["access_token"], order_sns)
                    shop_count = 0

                    for order in details:
                        order_date = str(_dt.date.fromtimestamp(order.get("create_time", 0)))
                        for item in order.get("item_list", []):
                            item_id = str(item.get("item_id", ""))
                            qty     = item.get("model_quantity_purchased", 0)
                            price   = float(item.get("item_price", 0))
                            mapped_pid = prod_map.get(("shopee", item_id))
                            new_items.append({
                                "id":               str(uuid.uuid4()),
                                "platform":         "shopee",
                                "shop_name":        shop_name,
                                "order_sn":         order["order_sn"],
                                "sale_date":        order_date,
                                "product_id":       mapped_pid,
                                "item_id_platform": item_id,
                                "qty":              qty,
                                "item_price":       price,
                            })
                            if not mapped_pid:
                                new_unmapped.append((item_id, item.get("item_name", ""), shop_name))
                            shop_count += 1

                    st.write(f"✅ **{shop_name}**: {len(orders)} orders / {shop_count} items")
                    _prog.progress((idx + 1) / total, text=f"ดึง {shop_name} เสร็จ ({idx+1}/{total})")

                if new_items:
                    db.insert_ecommerce_sales(new_items)
                _prog.progress(1.0, text="✅ Sync เสร็จสิ้น")
                _final = f"✅ Sync เสร็จสิ้น — {len(new_items)} รายการ" if new_items else "ℹ️ Sync เสร็จสิ้น — ไม่มี order ใหม่"
                _sync_status.update(label=_final, state="complete", expanded=False)

            if new_items:
                st.success(f"✅ Sync แล้ว {len(new_items)} รายการ")
            else:
                st.info("ไม่มี order ใหม่ในช่วงเวลานี้")
            if new_unmapped:
                st.warning(f"⚠️ {len(set(i[0] for i in new_unmapped))} สินค้ายังไม่ได้ map — ไปที่ Section 4")
            st.rerun()

    st.divider()

    # ── Section 3: ยอดขาย ────────────────────────────────────────────────
    st.markdown("### 3. ยอดขาย E-commerce")
    ev1, ev2 = st.columns(2)
    view_from = ev1.date_input("จาก", value=date.today().replace(day=1), key="ecom_vfrom")
    view_to   = ev2.date_input("ถึง",  value=date.today(), key="ecom_vto")
    ecom_df   = db.get_ecommerce_sales_df(str(view_from), str(view_to))
    if ecom_df.empty:
        st.info("ยังไม่มีข้อมูล — กด Sync ก่อนครับ")
    else:
        st.dataframe(ecom_df.style.format({"ยอด": "{:,.2f}"}), use_container_width=True, hide_index=True)
        st.caption(f"รวม {ecom_df['จำนวน'].sum():,} ชิ้น | ยอดรวม {ecom_df['ยอด'].sum():,.2f} บาท")
        st.dataframe(
            ecom_df.groupby("สินค้า")[["จำนวน", "ยอด"]].sum().reset_index()
                .sort_values("จำนวน", ascending=False),
            use_container_width=True, hide_index=True,
        )

    st.divider()

    # ── Section 4: Map สินค้า ─────────────────────────────────────────────
    st.markdown("### 4. Map สินค้า Shopee → ระบบ")
    unmapped_rows = db.get_unmapped_ecommerce_items("shopee") if shops else []

    if unmapped_rows:
        st.warning(f"มี {len(unmapped_rows)} รายการที่ยังไม่ได้ map")
        all_products = db.get_products()
        prod_opts    = {"— ยังไม่ map —": None} | {p["name"]: p["id"] for p in all_products}
        map_rows     = []
        for i, row in enumerate(unmapped_rows):
            mc1, mc2 = st.columns([2, 3])
            mc1.write(f"`{row['item_id']}` ({row['shop_name']})")
            sel = mc2.selectbox("สินค้าในระบบ", list(prod_opts.keys()), key=f"map_{i}")
            if prod_opts[sel]:
                map_rows.append({
                    "id": str(uuid.uuid4()),
                    "platform": "shopee",
                    "platform_item_id": row["item_id"],
                    "product_id": prod_opts[sel],
                    "platform_product_name": row["item_id"],
                })
        if map_rows and st.button("💾 บันทึก Mapping", type="primary", key="ecom_map_save"):
            db.upsert_ecommerce_product_map(map_rows)
            st.success(f"✅ Map แล้ว {len(map_rows)} รายการ")
            st.rerun()
    else:
        st.success("✅ สินค้าทุกรายการ map แล้ว")
