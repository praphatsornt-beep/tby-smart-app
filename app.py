import re
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from datetime import date, datetime, timezone, timedelta

_BKK = timezone(timedelta(hours=7))

def _to_bkk(ts: str) -> str:
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(_BKK).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts[:16].replace("T", " ")
from math import floor
import uuid
import io

import database as db
import thai_address

thai_address._load_db()  # pre-warm cache ตอน app โหลด

_PROVINCES = [
    "กรุงเทพมหานคร","กระบี่","กาญจนบุรี","กาฬสินธุ์","กำแพงเพชร","ขอนแก่น",
    "จันทบุรี","ฉะเชิงเทรา","ชลบุรี","ชัยนาท","ชัยภูมิ","ชุมพร",
    "ตรัง","ตราด","ตาก","นครนายก","นครปฐม","นครพนม","นครราชสีมา",
    "นครศรีธรรมราช","นครสวรรค์","นนทบุรี","นราธิวาส","น่าน","บึงกาฬ",
    "บุรีรัมย์","ปทุมธานี","ประจวบคีรีขันธ์","ปราจีนบุรี","ปัตตานี",
    "พระนครศรีอยุธยา","พะเยา","พังงา","พัทลุง","พิจิตร","พิษณุโลก",
    "ภูเก็ต","มหาสารคาม","มุกดาหาร","ยะลา","ยโสธร","ระนอง","ระยอง",
    "ราชบุรี","ร้อยเอ็ด","ลพบุรี","ลำปาง","ลำพูน","ศรีสะเกษ","สกลนคร",
    "สงขลา","สตูล","สมุทรปราการ","สมุทรสงคราม","สมุทรสาคร","สระบุรี",
    "สระแก้ว","สิงห์บุรี","สุพรรณบุรี","สุราษฎร์ธานี","สุรินทร์","สุโขทัย",
    "หนองคาย","หนองบัวลำภู","อำนาจเจริญ","อุดรธานี","อุตรดิตถ์",
    "อุทัยธานี","อุบลราชธานี","อ่างทอง","เชียงราย","เชียงใหม่",
    "เพชรบุรี","เพชรบูรณ์","เลย","แพร่","แม่ฮ่องสอน",
]
import shopee_api
import iship_api
from math import ceil
from flash_zones import lookup_zone, zone_surcharge, ZONE_LABELS, carrier_fees

BOX_WEIGHT_G = 500  # น้ำหนักกล่อง 0.5 kg (ไม่แสดงในระบบ)

def calc_shipping(weight_grams: float, postcode: str = "") -> float:
    """ค่าส่ง Flash Express: 5 kg แรก 39 บาท, ทุก kg ถัดไป +10 บาท + ค่าพื้นที่"""
    kg  = (weight_grams + BOX_WEIGHT_G) / 1000
    fee = 39 + max(0, ceil(kg - 5)) * 10
    return fee + zone_surcharge(postcode)

st.set_page_config(page_title="TBY SMART APP", page_icon="🛍️", layout="wide")

# ── Shopee OAuth callback ────────────────────────────────────────────────────
_qp = st.query_params
if "code" in _qp and "shop_id" in _qp:
    _code    = _qp["code"]
    _shop_id = int(_qp["shop_id"])
    try:
        _tok = shopee_api.exchange_token(_shop_id, _code)
        if "access_token" in _tok:
            import datetime as _dt
            expiry = _dt.datetime.utcnow() + _dt.timedelta(seconds=_tok.get("expire_in", 14400))
            db.upsert_ecommerce_shop({
                "id":            str(_shop_id),
                "platform":      "shopee",
                "shop_name":     f"Shopee-{_shop_id}",
                "shop_id":       _shop_id,
                "access_token":  _tok["access_token"],
                "refresh_token": _tok["refresh_token"],
                "token_expiry":  expiry.isoformat(),
            })
            st.success(f"✅ เชื่อมต่อร้าน shop_id={_shop_id} สำเร็จ")
        else:
            st.error(f"❌ ได้รับ code แต่ token ผิดพลาด: {_tok.get('message','')}")
    except Exception as _e:
        st.error(f"❌ OAuth error: {_e}")
    st.query_params.clear()

def _style_status(val):
    colors = {
        "เปิดบิลแล้ว":   "background-color:#1a5c2e;color:white",
        "ยังไม่เปิดบิล": "background-color:#7c4a00;color:white",
        "จ่ายแล้ว":      "background-color:#1a5c2e;color:white",
        "ค้างจ่าย":      "background-color:#6b1a1a;color:white",
    }
    return colors.get(val, "")


def _fmt_note(note: str) -> str:
    """แปลง raw tag → label กระชับ เช่น 'ส่งพัสดุ COD'"""
    import re as _re
    labels = []
    if "[ส่งพัสดุ|" in note:
        labels.append("ส่งพัสดุ")
    if "[COD|" in note:
        labels.append("COD")
    free = _re.sub(r"\[[^\]]+\]", "", note).strip()
    if free:
        labels.append(free)
    return " ".join(labels)


def _parse_iship_address(text: str) -> dict:
    """Parse 3 formats:
    1. iShip LINE bilingual: ตำบล/ English + Receiver: ชื่อ
    2. Thai standard: ชื่อ บ้านเลขที่ ต.ตำบล อ.อำเภอ จ.จังหวัด รหัสปณ.
    3. iShip compact: {phone}  {name}    {address}\\n{district} {amphure} {province} {zipcode}
    """
    import re as _re
    r = {"dst_name": "", "dst_phone": "", "address_line": "",
         "district": "", "amphure": "", "province": "", "zipcode": ""}

    # Phone (shared)
    m = _re.search(r'0[6-9]\d{8}', text)
    if m:
        r["dst_phone"] = m.group()

    # Zipcode standalone (shared)
    m_zip = _re.search(r'(?<!\d)([1-9]\d{4})(?!\d)', text)
    if m_zip:
        r["zipcode"] = m_zip.group(1)

    _lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

    # ── Format 3: iShip compact LINE format ─────────────────────────────
    # L1: {phone}  {name}    {address}   (2+ spaces separate name from address)
    # Ln: {district} {amphure} {province} {zipcode} [extra]
    _m3_l1 = (_re.match(r'^(0[6-9]\d{8})\s+(.+?)\s{2,}(\S.+)$', _lines[0])
               if _lines else None)
    _m3_ln = (_re.match(r'^([^\d\s]+)\s+([^\d\s]+)\s+([^\d\s]+)\s+(\d{5})', _lines[-1])
               if len(_lines) >= 2 else None)
    if _m3_l1 and _m3_ln:
        r["dst_phone"]    = _m3_l1.group(1)
        r["dst_name"]     = _m3_l1.group(2).strip()
        r["address_line"] = _m3_l1.group(3).strip()
        r["district"]     = _m3_ln.group(1)
        r["amphure"]      = _m3_ln.group(2)
        r["province"]     = _m3_ln.group(3)
        r["zipcode"]      = _m3_ln.group(4)

    elif _re.search(r'[฀-๿]+/\s*[A-Za-z]', text):
        # ── Format 1: iShip LINE format ──────────────────────────────────
        m = _re.search(r'(?<!\d)([1-9]\d{4})(?!\d)\s+(.+?)(?=\s*\.\s*[฀-๿]|[\r\n]|$)',
                       text, _re.DOTALL)
        if m:
            addr_raw = m.group(2).strip()
            if r["dst_phone"] and r["dst_phone"] in addr_raw:
                addr_raw = addr_raw.replace(r["dst_phone"], "").strip()
            r["address_line"] = addr_raw

        parts = _re.findall(r'([฀-๿][฀-๿\s]*?)\s*/\s*[A-Za-z]', text)
        seen, unique = set(), []
        for p in parts:
            p = p.strip()
            if p and p not in seen:
                seen.add(p); unique.append(p)
        if len(unique) >= 1: r["district"] = unique[0]
        if len(unique) == 2: r["province"] = unique[1]
        elif len(unique) >= 3: r["amphure"] = unique[1]; r["province"] = unique[2]

        m = _re.search(r'Receiver:\s*([^(\n]+)', text, _re.IGNORECASE)
        if m:
            r["dst_name"] = m.group(1).strip()

    elif _re.search(r'[ตอจ]\.\s*\S', text):
        # ── Format 2: Thai standard format (ต./อ./จ.) ────────────────────
        _dt = _re.search(r'ต\.\s*([^\s,]+)', text)
        _am = _re.search(r'อ\.\s*([^\s,]+)', text)
        _pv = _re.search(r'จ\.\s*([^\s,\d]+)', text)
        if _dt: r["district"] = _dt.group(1).strip()
        if _am: r["amphure"]  = _am.group(1).strip()
        if _pv: r["province"] = _pv.group(1).strip()

        # ชื่อ + บ้านเลขที่ จากบรรทัดแรก
        first_line = text.strip().splitlines()[0].strip()
        clean = _re.sub(r'(?<!\d)[1-9]\d{4}(?!\d)', '', first_line)  # ลบรหัสปณ.
        clean = _re.sub(r'\s*[ตอจ]\.\s*[^\s,]+', '', clean).strip()  # ลบ ต./อ./จ.
        nm = _re.match(r'^([^\d]+?)\s{1,}(\d.+)$', clean.strip())
        if nm:
            r["dst_name"]    = nm.group(1).strip()
            r["address_line"] = nm.group(2).strip()
        else:
            r["dst_name"] = clean.strip()

    elif _re.search(r'0[6-9]\d{8}', text):
        # ── Format 4: single line, name first ────────────────────────────
        # {name}  {phone}   {address} {amphure} {province} {zipcode}
        _all_f4 = ' '.join(_lines)
        _m4 = _re.match(r'^(.+?)\s+(0[6-9]\d{8})\s+(.+)$', _all_f4.strip())
        if _m4:
            r["dst_name"]  = _m4.group(1).strip()
            r["dst_phone"] = _m4.group(2)
            _rest4 = _m4.group(3).strip()
            _m4z = _re.search(r'(?<!\d)([1-9]\d{4})(?!\d)', _rest4)
            if _m4z:
                r["zipcode"] = _m4z.group(1)
                _wz = _rest4[:_m4z.start()].strip().split()
                # last 2 Thai words before zipcode = amphure + province
                if len(_wz) >= 2:
                    r["province"]     = _wz[-1]
                    r["amphure"]      = _wz[-2]
                    r["address_line"] = ' '.join(_wz[:-2])
                elif len(_wz) == 1:
                    r["province"]     = _wz[0]
                else:
                    r["address_line"] = _rest4[:_m4z.start()].strip()
            else:
                r["address_line"] = _rest4

    # lookup เขต/อำเภอ จากฐานข้อมูล (shared)
    from bangkok_addresses import lookup_khet, lookup_from_zipcode
    if r["district"] and r["zipcode"] and not r["amphure"]:
        khet = lookup_khet(r["district"], r["zipcode"])
        if khet: r["amphure"] = khet
    if r["zipcode"] and not r["amphure"]:
        prov, amph = lookup_from_zipcode(r["zipcode"])
        if amph: r["amphure"] = amph
        if prov and not r["province"]: r["province"] = prov

    return r


st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 1.4rem; }
[data-testid="stMetricLabel"] { font-size: 0.8rem; }
</style>
""", unsafe_allow_html=True)

st.title("🛍️ TBY SMART APP")


tab1, tab2, tab5, tab6, tab7, tab_fin, tab_ecom, tab4 = st.tabs([
    "📋 บันทึกรายการ",
    "💰 ยอดค้าง",
    "🗂️ ประวัติทั้งหมด",
    "📦 สต๊อก",
    "🖨️ พิมพ์บิล",
    "💵 การเงิน",
    "🛒 E-commerce",
    "⚙️ จัดการข้อมูล",
])



# ─────────────────────────────────────────────────────────────────────────────
# Tab 1: บันทึกรายการขาย
# ─────────────────────────────────────────────────────────────────────────────
def _parse_quick_order(text: str, products: list) -> tuple:
    product_by_id = {p["id"].upper(): p for p in products}
    found, unknown = [], []
    for token in text.strip().split():
        parts = token.rsplit("-", 1)
        if len(parts) == 2:
            code, qty_str = parts[0].upper(), parts[1]
            if qty_str.isdigit() and int(qty_str) > 0:
                p = product_by_id.get(code)
                if p:
                    found.append({"product": p, "qty": int(qty_str)})
                else:
                    unknown.append(code)
    return found, unknown


def _pick_carrier(pc: str, kg: float = 0) -> str:
    is_metro = pc[:2] in {"10", "11", "12"}
    return "Flash Express" if (kg <= 3 and not is_metro) else "SPX Express"




with tab1:
    _sub_sale, _sub_ship, _sub_shiphist = st.tabs(["📝 บันทึกขาย", "📦 ส่งของ", "📋 ประวัติการส่ง"])

    with _sub_sale:
        _sale_keys = ["_cust_picked","m_cust_search","_adding_cust",
                      "m_bill","m_pay","m_delivery","m_cod",
                      "m_cart","_cart_base","m_postcode","m_carrier","m_zone",
                      "r_name","r_phone","r_al","r_dt","r_am","r_pv",
                      "_carrier_sig","_prev_pc","_prev_pay","_prev_shipping_cid","_last_rph_fill",
                      "_r_last_dt","_r_last_pc","_fr_dt","_fr_am","_fr_pv"]

        if st.session_state.get("_print_popup"):
            _pd = st.session_state["_print_popup"]
            _grand = _pd.get("collect", _pd["total_amt"])
            _items_txt = ", ".join(f"{it['name']} ×{it['qty']}" for it in _pd.get("items", []))
            with st.container(border=True):
                _pb1, _pb2, _pb3 = st.columns([4, 3, 1])
                _pb1.markdown(
                    f"✅ **{_pd['customer_name']}** — บิล `{_pd['bill_no']}` | {_pd['bill_date']}"
                    f"\n\n_{_items_txt}_"
                )
                _pb2.markdown(
                    f"💰 **{_grand:,.0f} ฿** &nbsp;&nbsp; ⭐ PV {_pd['total_pv']:.0f}"
                )
                if _pb3.button("✕ ปิด", key="popup_close", use_container_width=True):
                    del st.session_state["_print_popup"]
                    st.rerun()

        _sale_h1, _sale_h2 = st.columns([6, 1])
        _sale_h1.subheader("บันทึกรายการขาย")
        if _sale_h2.button("🗑️ ล้าง", key="sale_clear_form", use_container_width=True):
            for _k in _sale_keys:
                st.session_state.pop(_k, None)
            st.rerun()

        products = db.get_products()
        customers = db.get_customers()

        if not products:
            st.warning("⚠️ ยังไม่มีข้อมูลสินค้า กรุณาเพิ่มสินค้าใน Tab ⚙️ ก่อน")
        elif not customers:
            st.warning("⚠️ ยังไม่มีข้อมูลลูกค้า กรุณาเพิ่มลูกค้าใน Tab ⚙️ ก่อน")
        else:
            product_map = {p["name"]: p for p in products}
            customer_map = {c["name"]: c for c in customers}

            # ── iShip pending (แสดงหลัง save ส่งพัสดุ) ──────────────────────
            if st.session_state.get("_iship_pending"):
                _p = st.session_state["_iship_pending"]
                addr_full = f"{_p['address_line']} {_p['district']} {_p['amphure']} {_p['province']} {_p['zipcode']}".strip()
                _sender_name = _p.get("sender_name", "")
                st.info(
                    f"{'👤 ลูกค้า: **' + _sender_name + '**  →  ' if _sender_name else ''}"
                    f"📦 **{_p['dst_name']}**  {_p['dst_phone']}\n\n"
                    f"{addr_full}\n\n"
                    f"น้ำหนัก {_p['weight_kg']:.2f} kg  |  COD {_p['cod_amount']:,} ฿"
                )
                # เลือกขนส่งก่อนส่ง
                _carrier_choice = st.radio("ขนส่ง", ["Flash Express", "SPX Express"],
                                           index=0 if _p["carrier"] == "Flash Express" else 1,
                                           horizontal=True, key="iship_carrier_pick")
                _p["carrier"] = _carrier_choice

                col_s1, col_s2 = st.columns([3, 1])
                if col_s1.button("🚚 ส่ง iShip", type="primary", use_container_width=True, key="do_iship"):
                    if iship_api.is_configured():
                        _api_keys = {"dst_name","dst_phone","address_line","district",
                                     "amphure","province","zipcode","weight_kg",
                                     "cod_amount","carrier","remark","item_detail","products"}
                        _call = {k: v for k, v in _p.items() if k in _api_keys}
                        with st.spinner("กำลังสร้างรายการใน iShip..."):
                            resp = iship_api.create_order(**_call)
                        if resp.get("status"):
                            tracking = (resp.get("data") or {}).get("tracking_code", "")
                            st.success(f"✅ สร้างรายการสำเร็จ — Tracking: **{tracking}**")
                            # บันทึก shipment record จาก บันทึกขาย
                            try:
                                db.create_shipment({
                                    "customer_id":    _p.get("_customer_id") or None,
                                    "recipient_name": _p.get("dst_name",""),
                                    "phone":          _p.get("dst_phone",""),
                                    "address_line":   _p.get("address_line",""),
                                    "district":       _p.get("district",""),
                                    "amphure":        _p.get("amphure",""),
                                    "province":       _p.get("province",""),
                                    "postal_code":    _p.get("zipcode",""),
                                    "carrier":        _p.get("carrier",""),
                                    "items":          _p.get("_items",[]),
                                    "tracking_no":    tracking,
                                    "notes":          "",
                                })
                            except Exception:
                                pass
                            del st.session_state["_iship_pending"]
                        else:
                            _err_msg = resp.get("message") or resp.get("msg") or str(resp)
                            if "NotSupportAddress" in _err_msg:
                                st.error("❌ ที่อยู่ไม่ถูกต้อง — ตำบล / อำเภอ / จังหวัด ต้องตรงกับฐานข้อมูล iShip")
                                with st.expander("🔍 ดู response จาก iShip"):
                                    st.json(resp)
                                    st.write("ที่ส่งไป →", {
                                        "district": _call.get("district"),
                                        "amphure":  _call.get("amphure"),
                                        "province": _call.get("province"),
                                        "zipcode":  _call.get("zipcode"),
                                    })
                            else:
                                st.error(f"❌ iShip Error: {_err_msg}")
                                with st.expander("🔍 raw response"):
                                    st.json(resp)
                    else:
                        st.warning("⚙️ ยังไม่ได้ตั้งค่า ISHIP_TOKEN ใน secrets")
                if col_s2.button("ปิด", key="cancel_iship", use_container_width=True):
                    del st.session_state["_iship_pending"]
                    st.rerun()
                st.divider()

            # ── วางรหัสสินค้าลงตาราง ─────────────────────────────────────────
            with st.expander("⚡ วางรหัสสินค้า", expanded=False):
                q_text = st.text_area(
                    "รหัส-จำนวน คั่นด้วยเว้นวรรค",
                    placeholder="เช่น: tf2581-38 ty2006-1 rb2306-1 tu3315-1",
                    height=80, key="q_text",
                )
                if st.button("📋 ใส่ลงตาราง", key="q_to_cart", type="primary", use_container_width=True):
                    _qf, _qu = _parse_quick_order(q_text or "", products)
                    if _qu:
                        st.error(f"❌ รหัสไม่พบ: {', '.join(_qu)}")
                    if _qf:
                        st.session_state["_quick_cart_items"] = _qf
                        st.session_state.pop("m_cart", None)
                        st.session_state.pop("_cart_base", None)
                        st.rerun()

            st.divider()
            # ── บันทึกหลายรายการพร้อมกัน ────────────────────────────────────

            # ── ค้นหาลูกค้าจากเบอร์โทร ─────────────────────────────────────
            mc1, mc2 = st.columns([3, 1])
            with mc1:
                _cust_picked = st.session_state.get("_cust_picked", "")
                if _cust_picked:
                    cp1, cp2 = st.columns([5, 1])
                    cp1.markdown(f"👤 **{_cust_picked}**")
                    _r_preview = " · ".join(filter(None, [
                        st.session_state.get("r_name", ""),
                        st.session_state.get("r_al", ""),
                        st.session_state.get("r_am", ""),
                        st.session_state.get("r_pv", ""),
                        st.session_state.get("m_postcode", ""),
                    ]))
                    if _r_preview:
                        cp1.caption(_r_preview)
                    if cp2.button("✕", key="cust_clear", help="เลือกลูกค้าใหม่"):
                        st.session_state.pop("_cust_picked", None)
                        st.session_state.pop("_prev_shipping_cid", None)
                        st.rerun()
                    m_customer = _cust_picked
                else:
                    cust_search = st.text_input("ลูกค้า", placeholder="พิมพ์ชื่อเพื่อค้นหา...",
                                                 key="m_cust_search")
                    m_customer = "— เลือกลูกค้า —"
                    if cust_search.strip():
                        _matches = [n for n in customer_map if cust_search.upper() in n.upper()][:6]
                        for _mn in _matches:
                            if st.button(f"👤 {_mn}", key=f"cp_{_mn}", use_container_width=True):
                                st.session_state["_cust_picked"] = _mn
                                st.rerun()
                        if cust_search.upper() not in [n.upper() for n in _matches]:
                            if st.button(f"➕ เพิ่ม '{cust_search}'", key="cust_add_btn",
                                          use_container_width=True):
                                st.session_state["_adding_cust"] = cust_search
                    if st.session_state.get("_adding_cust"):
                        _new_cust_name = st.session_state["_adding_cust"]
                        with st.form("add_cust_quick"):
                            _fn = st.text_input("ชื่อลูกค้า", value=_new_cust_name)
                            _fp = st.text_input("เบอร์โทร (ถ้ามี)")
                            _fc1, _fc2 = st.columns(2)
                            if _fc1.form_submit_button("💾 บันทึก", type="primary"):
                                _all_cids = [c["id"] for c in db.get_customers()]
                                _cmax = max((int(re.match(r'C-(\d+)', x).group(1))
                                             for x in _all_cids if re.match(r'C-(\d+)', x)), default=0)
                                _new_cid = f"C-{_cmax + 1:03d}"
                                db.upsert_customer({"id": _new_cid,
                                                    "name": _fn.strip(), "phone": _fp.strip()})
                                st.session_state["_cust_picked"] = _fn.strip()
                                st.session_state.pop("_adding_cust", None)
                                st.rerun()
                            if _fc2.form_submit_button("ยกเลิก"):
                                st.session_state.pop("_adding_cust", None)
                                st.rerun()
            m_date = mc2.date_input("วันที่", value=date.today(), key="m_date")

            # ── Reset recipient fields when customer changes ─────────────────────
            if m_customer != "— เลือกลูกค้า —":
                if m_customer not in customer_map:
                    st.rerun()  # รอ customers reload หลังเพิ่งเพิ่มใหม่
                _cid_detect = customer_map[m_customer]["id"]
                if st.session_state.get("_prev_shipping_cid") != _cid_detect:
                    st.session_state["_prev_shipping_cid"] = _cid_detect
                    _ca_d = customer_map[m_customer]
                    for _k, _v in [
                        ("r_name",  _ca_d.get("name", "")),
                        ("r_phone", ""),
                        ("r_al",    ""),
                        ("r_dt",    ""),
                        ("r_am",    ""),
                        ("r_pv",    ""),
                    ]:
                        st.session_state[_k] = _v
                    st.session_state["_staged_pc"] = ""

            # ── รายการสินค้า ─────────────────────────────────────────────────
            product_display = {f"{p['id']} — {p['name']}": p for p in products}
            product_display_keys = list(product_display.keys())
            # cart_df ต้องคงที่ระหว่าง reruns เพราะ data_editor เก็บแค่ edit diff
            if "m_cart" not in st.session_state:
                # first render หรือหลัง clear — ตั้ง base ใหม่
                if "_quick_cart_items" in st.session_state:
                    _qi = st.session_state.pop("_quick_cart_items")
                    cart_df = pd.DataFrame({
                        "สินค้า": [f"{it['product']['id']} — {it['product']['name']}" for it in _qi],
                        "จำนวน":  pd.array([it["qty"] for it in _qi], dtype="int64"),
                    })
                else:
                    cart_df = pd.DataFrame({
                        "สินค้า": pd.Series([""] * 3, dtype="object"),
                        "จำนวน":  pd.Series([0]  * 3, dtype="int64"),
                    })
                st.session_state["_cart_base"] = cart_df
            else:
                # rerun กลาง session — ใช้ base เดิมเสมอ
                cart_df = st.session_state.get("_cart_base", pd.DataFrame({
                    "สินค้า": pd.Series([""] * 3, dtype="object"),
                    "จำนวน":  pd.Series([0]  * 3, dtype="int64"),
                }))
            edited_cart = st.data_editor(
                cart_df,
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                column_config={
                    "สินค้า": st.column_config.SelectboxColumn("สินค้า (รหัส — ชื่อ)", options=product_display_keys, required=False),
                    "จำนวน": st.column_config.NumberColumn("จำนวน", min_value=0, step=1, width="small"),
                },
                key="m_cart",
            )

            valid_items = [
                (product_display[row["สินค้า"]], int(row["จำนวน"] or 0), "")
                for _, row in edited_cart.iterrows()
                if str(row.get("สินค้า", "")) in product_display and int(row.get("จำนวน") or 0) > 0
            ]

            # ── สถานะ + การจัดส่ง ────────────────────────────────────────────
            # auto-set COD ก่อน render
            _cur_pay = st.session_state.get("m_pay", "ค้างจ่าย")
            if _cur_pay == "COD" and st.session_state.get("_prev_pay") != "COD":
                st.session_state["m_bill"]     = "ยังไม่เปิดบิล"
                st.session_state["m_delivery"] = "ส่งพัสดุ"
                st.session_state["_prev_pay"]  = "COD"
            elif _cur_pay != "COD":
                st.session_state["_prev_pay"] = _cur_pay
            ms1, ms2, ms3 = st.columns(3)
            _delivery_opts = ["ส่งพัสดุ", "ฝากของ", "รับแล้ว"]
            m_delivery = ms1.radio("การรับ / สถานะของ", _delivery_opts, horizontal=True, key="m_delivery")
            m_pay  = ms2.radio("สถานะจ่าย", ["ค้างจ่าย", "จ่ายแล้ว", "COD"], horizontal=True, key="m_pay")
            m_bill = ms3.radio("สถานะบิล", ["ยังไม่เปิดบิล", "เปิดบิลแล้ว"], horizontal=True, key="m_bill")
            m_cod     = (m_pay == "COD")
            m_receipt = "ฝากของ" if m_delivery == "ฝากของ" else "รับของแล้ว"
            m_postcode = ""
            m_zone     = "normal"
            m_carrier  = "Flash Express"

            if m_delivery == "ส่งพัสดุ":
                if "_staged_pc" in st.session_state:
                    st.session_state["m_postcode"] = st.session_state.pop("_staged_pc")
                m_postcode = st.session_state.get("m_postcode", "")



                fees = carrier_fees(0, m_postcode.strip()) if len(m_postcode.strip()) == 5 else None
                f_sur  = fees["Flash Express"]["surcharge"] if fees else 0
                s_sur  = fees["SPX Express"]["surcharge"]   if fees else 0
                f_zone = fees["Flash Express"]["zone"]      if fees else "—"
                s_zone = fees["SPX Express"]["zone"]        if fees else "—"
                fc_col, sc_col, car_col = st.columns(3)
                fc_col.caption(f"Flash Express: {f_zone or 'ปกติ'} | +{f_sur} ฿")
                sc_col.caption(f"SPX Express: {s_zone or 'ปกติ'} | +{s_sur} ฿")
                if fees and m_postcode != st.session_state.get("_prev_pc", ""):
                    st.session_state["m_carrier"] = _pick_carrier(m_postcode)
                    st.session_state["_prev_pc"]  = m_postcode
                if "_staged_carrier" in st.session_state:
                    st.session_state["m_carrier"] = st.session_state.pop("_staged_carrier")
                m_carrier = car_col.radio("เลือกขนส่ง", ["Flash Express", "SPX Express"], key="m_carrier")

                # ── ที่อยู่ผู้รับ ─────────────────────────────────────────────
                _cid = customer_map[m_customer]["id"] if m_customer != "— เลือกลูกค้า —" else "no_cust"
                with st.expander("📦 ที่อยู่ผู้รับ", expanded=True):
                        # ── quick-select ที่อยู่เดิมของลูกค้า ──────────────────
                        if m_customer != "— เลือกลูกค้า —":
                            try:
                                _saved_addrs = db.get_customer_addresses(customer_id=_cid)
                            except Exception:
                                _saved_addrs = []
                            if _saved_addrs:
                                st.caption("⚡ เลือกที่อยู่เดิม")
                                for _sa in _saved_addrs:
                                    _sa_label = f"{_sa.get('recipient_name','')} · {_sa.get('phone','')} · {_sa.get('address_line','')} {_sa.get('district','')} {_sa.get('postal_code','')}"
                                    if st.button(_sa_label, key=f"qa_{_sa['id']}", use_container_width=True):
                                        st.session_state["r_name"]  = _sa.get("recipient_name", "")
                                        st.session_state["r_phone"] = _sa.get("phone", "")
                                        st.session_state["r_al"]    = _sa.get("address_line", "")
                                        st.session_state["r_dt"]    = _sa.get("district", "")
                                        st.session_state["r_am"]    = _sa.get("amphure", "")
                                        st.session_state["r_pv"]    = _sa.get("province", "")
                                        st.session_state["_staged_pc"] = _sa.get("postal_code", "")
                                        st.session_state["_last_rph_fill"] = _sa.get("phone", "")
                                        st.rerun()
                                st.divider()
                        _parse_key = f"_show_paste_{_cid}"
                        if st.button("📍 แยกที่อยู่อัตโนมัติ", key=f"parse_open_{_cid}"):
                            st.session_state[_parse_key] = not st.session_state.get(_parse_key, False)
                        if st.session_state.get(_parse_key):
                            paste_txt = st.text_area(
                                "วางที่อยู่จาก LINE (iShip format)",
                                key=f"paste_{_cid}", height=100, placeholder=
                                "Boo Mee\nสวนหลวง/ Suan Luang,\nกรุงเทพมหานคร/ Bangkok,\n10250  14 Rama IX Soi 41\n0617490976"
                            )
                            _pc1, _pc2 = st.columns([1, 1])
                            if _pc1.button("✅ ตกลง", key=f"parse_btn_{_cid}", type="primary"):
                                _parsed = _parse_iship_address(paste_txt)
                                for _sk in ["r_name", "r_phone", "r_al", "r_dt", "r_am", "r_pv"]:
                                    st.session_state[_sk] = ""
                                st.session_state["_staged_pc"] = ""
                                if _parsed["dst_name"]:     st.session_state["r_name"]  = _parsed["dst_name"]
                                if _parsed["dst_phone"]:    st.session_state["r_phone"] = _parsed["dst_phone"]
                                if _parsed["address_line"]: st.session_state["r_al"]    = _parsed["address_line"]
                                if _parsed["district"]:     st.session_state["r_dt"]    = _parsed["district"]
                                if _parsed["amphure"]:      st.session_state["r_am"]    = _parsed["amphure"]
                                if _parsed["province"]:     st.session_state["r_pv"]    = _parsed["province"]
                                if _parsed["zipcode"]:      st.session_state["_staged_pc"] = _parsed["zipcode"]
                                st.session_state[_parse_key] = False
                                st.rerun()
                            if _pc2.button("ยกเลิก", key=f"parse_cancel_{_cid}"):
                                st.session_state[_parse_key] = False
                                st.rerun()
                        st.divider()
                        _cur_rph = st.session_state.get("r_phone", "")
                        if len(_cur_rph.strip()) == 10 and st.session_state.get("_last_rph_fill") != _cur_rph.strip():
                            try:
                                _rph_addr = db.get_address_by_phone(_cur_rph.strip())
                            except Exception:
                                _rph_addr = None
                            st.session_state["_last_rph_fill"] = _cur_rph.strip()
                            if _rph_addr:
                                for _k, _v in [
                                    ("r_name", _rph_addr.get("recipient_name") or ""),
                                    ("r_al",   _rph_addr.get("address_line") or ""),
                                    ("r_dt",   _rph_addr.get("district") or ""),
                                    ("r_am",   _rph_addr.get("amphure") or ""),
                                    ("r_pv",   _rph_addr.get("province") or ""),
                                ]:
                                    if _v: st.session_state[_k] = _v
                                if _rph_addr.get("postal_code"):
                                    st.session_state["m_postcode"] = _rph_addr["postal_code"]
                                _rph_cust = (_rph_addr.get("customers") or {}).get("name", "")
                                if _rph_cust and not st.session_state.get("_cust_picked"):
                                    st.session_state["_cust_picked"] = _rph_cust
                                    st.session_state["_prev_shipping_cid"] = _rph_addr.get("customer_id", "")
                        col_a, col_b = st.columns(2)
                        r_name      = col_a.text_input("ชื่อผู้รับ",   key="r_name")
                        r_phone     = col_b.text_input("เบอร์โทร",     key="r_phone")
                        r_addr_line = st.text_input("บ้านเลขที่/ถนน", key="r_al")
                        col_c, col_d, col_e = st.columns(3)
                        # apply staged address fill ก่อน render
                        for _fk, _wk in [("_fr_dt","r_dt"),("_fr_am","r_am"),("_fr_pv","r_pv")]:
                            if _fk in st.session_state:
                                st.session_state[_wk] = st.session_state.pop(_fk)
                        r_district  = col_c.text_input("ตำบล/แขวง",   key="r_dt")
                        r_amphure   = col_d.text_input("อำเภอ/เขต",    key="r_am")
                        r_province  = col_e.selectbox("จังหวัด", [""] + _PROVINCES, key="r_pv")
                        _r_last_dt = st.session_state.get("_r_last_dt", "")
                        if len((r_district or "").strip()) >= 2 and r_district.strip() != _r_last_dt:
                            _rdt_opts = thai_address.lookup_by_tambon(r_district.strip())
                            for _o in _rdt_opts:
                                _lbl = f"{_o['tambon']} » {_o['amphure']} » {_o['province']} ({_o['zipcode']})"
                                if st.button(_lbl, key=f"rdt_fill_{_o['tambon']}_{_o['zipcode']}", use_container_width=True):
                                    st.session_state["_fr_dt"] = _o["tambon"]
                                    st.session_state["_fr_am"] = _o["amphure"]
                                    st.session_state["_fr_pv"] = _o["province"]
                                    st.session_state["_staged_pc"] = _o["zipcode"]
                                    st.session_state["_r_last_dt"] = _o["tambon"]
                                    st.session_state["_r_last_pc"] = _o["zipcode"]
                                    st.rerun()
                        if "_staged_pc" in st.session_state:
                            st.session_state["m_postcode"] = st.session_state.pop("_staged_pc")
                        m_postcode  = st.text_input("รหัสไปรษณีย์", max_chars=5,
                                                    key="m_postcode", placeholder="เช่น 10400")
                        _r_last_pc = st.session_state.get("_r_last_pc", "")
                        if len((m_postcode or "").strip()) == 5 and m_postcode.strip() != _r_last_pc:
                            _pc_opts = thai_address.lookup(m_postcode.strip())
                            if _pc_opts:
                                for _o in _pc_opts[:8]:
                                    _lbl = f"{_o['tambon']} » {_o['amphure']} » {_o['province']}"
                                    if st.button(_lbl, key=f"pc_fill_{_o['tambon']}_{m_postcode}", use_container_width=True):
                                        st.session_state["_fr_dt"] = _o["tambon"]
                                        st.session_state["_fr_am"] = _o["amphure"]
                                        st.session_state["_fr_pv"] = _o["province"]
                                        st.session_state["_r_last_dt"] = _o["tambon"]
                                        st.session_state["_r_last_pc"] = m_postcode.strip()
                                        st.rerun()
                        if m_customer != "— เลือกลูกค้า —":
                            if st.button("💾 บันทึกที่อยู่นี้", key="save_addr_btn"):
                                db.upsert_customer_address({
                                    "id":             str(uuid.uuid4()),
                                    "customer_id":    _cid,
                                    "recipient_name": r_name,
                                    "phone":          r_phone,
                                    "address_line":   r_addr_line,
                                    "district":       r_district,
                                    "amphure":        r_amphure,
                                    "province":       r_province,
                                    "postal_code":    m_postcode,
                                })
                                st.success("✅ บันทึกแล้ว — ค้นหาจากเบอร์ได้เลยครั้งถัดไป")
            else:
                r_name = r_phone = r_addr_line = r_district = r_amphure = r_province = ""

            # auto-select carrier จาก weight + location (รันทุกครั้งที่ items หรือ postcode เปลี่ยน)
            if m_delivery == "ส่งพัสดุ" and len(m_postcode.strip()) == 5:
                _w_kg = (sum(float(p.get("weight_grams") or 0) * q
                             for p, q, _ in valid_items) + 500) / 1000
                _optimal = _pick_carrier(m_postcode.strip(), _w_kg)
                _sig = (m_postcode.strip(), round(_w_kg, 2))
                if _sig != st.session_state.get("_carrier_sig"):
                    st.session_state["_carrier_sig"]    = _sig
                    st.session_state["_staged_carrier"] = _optimal
                    st.rerun()

            COD_FEE_RATE = 0.0321  # 3.21%

            if valid_items:
                total_amt    = sum(float(p["price"]) * q for p, q, _ in valid_items)
                total_pv     = sum(float(p["points_per_unit"]) * q for p, q, _ in valid_items)
                total_weight = sum(float(p.get("weight_grams") or 0) * q for p, q, _ in valid_items)
                if m_delivery == "ส่งพัสดุ":
                    fees_all  = carrier_fees(total_weight, m_postcode)
                    ship_fee  = fees_all[m_carrier]["total"] if m_postcode else calc_shipping(total_weight, m_postcode)
                    _base     = total_amt + ship_fee
                    cod_fee   = round(_base * COD_FEE_RATE, 2) if m_cod else 0
                    collect   = _base + cod_fee if m_cod else _base
                    net_recv  = _base
                    if m_cod:
                        vm1, vm2, vm3, vm4, vm5, vm6, vm7 = st.columns(7)
                        vm1.metric("ยอดสินค้า",       f"{total_amt:,.0f} ฿")
                        vm2.metric(f"🚚 {m_carrier}",  f"{ship_fee:.0f} ฿")
                        vm3.metric("💰 ยอดเก็บ",       f"{collect:,.0f} ฿")
                        vm4.metric("💸 ค่า COD",       f"{cod_fee:,.2f} ฿")
                        vm5.metric("✅ ได้รับจริง",    f"{net_recv:,.2f} ฿")
                        vm6.metric("⚖️ น้ำหนัก",      f"{(total_weight/1000):.2f} kg")
                        vm7.metric("PV รวม",           f"{total_pv:.0f}")
                    else:
                        vm1, vm2, vm3, vm4, vm5 = st.columns(5)
                        vm1.metric("ยอดสินค้า",        f"{total_amt:,.0f} ฿")
                        vm2.metric(f"🚚 {m_carrier}",  f"{ship_fee:.0f} ฿")
                        vm3.metric("💰 ยอดรวม",        f"{collect:,.0f} ฿")
                        vm4.metric("⚖️ น้ำหนัก",      f"{(total_weight/1000):.2f} kg")
                        vm5.metric("PV รวม",           f"{total_pv:.0f}")
                else:
                    ship_fee = cod_fee = 0
                    collect  = total_amt
                    net_recv = total_amt
                    vm1, vm2, vm3 = st.columns(3)
                    vm1.metric("ยอดรวม",   f"{total_amt:,.0f} ฿")
                    vm2.metric("PV รวม",   f"{total_pv:.0f}")
                    vm3.metric("รายการ",   f"{len(valid_items)} สินค้า")

            m_errors = []
            if m_customer == "— เลือกลูกค้า —": m_errors.append("เลือกลูกค้าก่อน")
            if m_bill is None:     m_errors.append("เลือกสถานะบิล")
            if m_pay is None:      m_errors.append("เลือกสถานะจ่าย")
            if m_delivery is None: m_errors.append("เลือกการรับสินค้า")
            if not valid_items:    m_errors.append("กรอกสินค้าและจำนวนอย่างน้อย 1 รายการ")

            if st.button("💾 บันทึกทั้งหมด", type="primary", use_container_width=True, key="m_submit",
                         disabled=bool(m_errors)):
                customer     = customer_map[m_customer]
                actual_pay  = "COD" if m_cod else m_pay
                # m_receipt ถูก map จาก m_delivery แล้ว (ฝากของ/รับของแล้ว)
                receive_now = m_receipt == "รับของแล้ว"
                is_shipping    = m_delivery == "ส่งพัสดุ"
                total_w_g      = sum(float(p.get("weight_grams") or 0) * q for p, q, _ in valid_items)
                if is_shipping:
                    fees_save = carrier_fees(total_w_g, m_postcode)
                    ship_fee  = fees_save[m_carrier]["total"]
                    zone_name = fees_save[m_carrier]["zone"]
                    zone_tag  = f"|{zone_name}" if zone_name else ""
                    delivery_tag = f"[ส่งพัสดุ|{m_carrier}|{m_postcode}|น้ำหนัก={total_w_g/1000:.2f}kg|ค่าส่ง={ship_fee:.0f}{zone_tag}]"
                else:
                    ship_fee = 0
                    delivery_tag = ""
                if m_cod:
                    _base_cod  = sum(float(p["price"]) * q for p, q, _ in valid_items) + ship_fee
                    cod_amount = round(_base_cod * COD_FEE_RATE, 2)
                    collect    = _base_cod + cod_amount
                    cod_tag    = f"[COD|ยอดเก็บ={collect:.0f}฿|ค่าธรรมเนียม={cod_amount:.2f}฿|ยอดรับจริง={_base_cod:.2f}฿]"
                else:
                    cod_tag = ""
                bill_no = db.get_next_bill_no(str(m_date))
                _m_batch = [{
                    "id":                   str(uuid.uuid4()),
                    "date":                 str(m_date),
                    "customer_id":          customer["id"],
                    "product_id":           p["id"],
                    "product_name":         p["name"],
                    "qty":                  qty,
                    "price_per_unit":       float(p["price"]),
                    "points_per_unit":      float(p["points_per_unit"]),
                    "total_amount":         float(p["price"]) * qty,
                    "initial_qty_received": qty if receive_now else 0,
                    "transaction_type":     "เบิกของก่อน" if m_bill == "ยังไม่เปิดบิล" and receive_now else "ขายปกติ",
                    "bill_status":          m_bill,
                    "pay_status":           actual_pay,
                    "notes":                " ".join(filter(None, [delivery_tag, cod_tag, note])).strip(),
                    "bill_no":              bill_no,
                } for p, qty, note in valid_items]
                try:
                    db.insert_transactions_batch(_m_batch)
                except Exception as _e:
                    st.error(f"❌ Error: {_e}")
                    st.json(_m_batch)
                    st.stop()
                msg = f"✅ บันทึก {len(valid_items)} รายการ"
                if is_shipping: msg += f" | 🚚 ค่าส่ง {ship_fee:.0f} ฿"
                if m_cod:       msg += f" | 💸 ค่า COD {cod_amount:.2f} ฿"
                # สร้าง iship text สำหรับวางใน iship.com
                if is_shipping and r_addr_line:
                    product_line = ", ".join(f"{p['name']} ×{qty}" for p, qty, _ in valid_items)
                    _prod_codes  = " ".join(f"{p['id'].upper()}-{qty}" for p, qty, _ in valid_items)
                    st.session_state["_iship_pending"] = {
                        "dst_name":    r_name or customer["name"],
                        "dst_phone":   r_phone,
                        "address_line": r_addr_line,
                        "district":    r_district,
                        "amphure":     r_amphure,
                        "province":    r_province,
                        "zipcode":     m_postcode,
                        "weight_kg":   (total_w_g + 500) / 1000,  # +500g กล่อง
                        "cod_amount":  ceil(collect) if m_cod else 0,
                        "carrier":      m_carrier,
                        "remark":       f"{customer['name']} {_prod_codes}",
                        "item_detail":  ", ".join(f"{p['name']} x{qty}" for p, qty, _ in valid_items),
                        "products":     [{"name": p["name"], "qty": qty, "price": float(p["price"])}
                                         for p, qty, _ in valid_items],
                        "sender_name":  customer["name"],
                        "_items": [{"product_id": p["id"], "name": p["name"], "qty": qty}
                                   for p, qty, _ in valid_items],
                        "_customer_id": customer["id"],
                    }
                # เก็บข้อมูลสำหรับ popup พิมพ์บิล
                st.session_state["_print_popup"] = {
                    "customer_name": customer["name"],
                    "bill_date":     str(m_date),
                    "bill_no":       bill_no,
                    "items": [{"name": p["name"], "qty": qty,
                               "price": float(p["price"]),
                               "total": float(p["price"]) * qty,
                               "pv":    float(p["points_per_unit"]) * qty}
                              for p, qty, _ in valid_items],
                    "ship_fee":    ship_fee,
                    "carrier":     m_carrier if is_shipping else "",
                    "is_cod":      m_cod,
                    "cod_fee":     cod_amount if m_cod else 0,
                    "collect":     ceil(collect) if m_cod else (total_amt + (ship_fee if is_shipping else 0)),
                    "total_amt":   total_amt,
                    "total_pv":    total_pv,
                    "bill_status": m_bill,
                    "pay_status":  actual_pay,
                }
                # ล้างฟอร์มสำหรับลูกค้าถัดไป
                for _k in ["_cust_picked", "m_cust_search", "_adding_cust",
                           "m_bill", "m_pay", "m_delivery", "m_cod",
                           "m_cart", "_cart_base", "m_postcode", "m_carrier", "m_zone",
                           "r_name", "r_phone", "r_al", "r_dt", "r_am", "r_pv",
                           "_carrier_sig", "_prev_pc", "_prev_pay",
                           "_prev_shipping_cid", "_last_rph_fill"]:
                    st.session_state.pop(_k, None)
                st.rerun()
            elif m_errors and any(e != "กรอกสินค้าและจำนวนอย่างน้อย 1 รายการ" for e in m_errors):
                st.caption("⚠️ " + " | ".join(m_errors))


    # ─────────────────────────────────────────────────────────────────────────────

    with _sub_ship:
        _sp_keys = ["sp_rname","sp_rphone","sp_al","sp_dt","sp_am","sp_pv","sp_pc",
                    "sp_track","sp_notes","sp_cart","_sp_cust_picked","sp_cust_search",
                    "_sp_last_dt","_sp_last_pc","_fsp_dt","_fsp_am","_fsp_pv","_fsp_pc"]

        _sc1, _sc2 = st.columns([6, 1])
        _sc1.subheader("บันทึกการส่งของ")
        if _sc2.button("🗑️ ล้าง", key="sp_clear_form", use_container_width=True):
            for _k in _sp_keys:
                st.session_state.pop(_k, None)
            st.rerun()

        # ── แสดง tracking ล่าสุด ─────────────────────────────────────────
        if st.session_state.get("_sp_last_tracking"):
            _lt = st.session_state["_sp_last_tracking"]
            _ltc1, _ltc2 = st.columns([5, 1])
            _ltc1.success(f"✅ iShip สำเร็จ — Tracking: **{_lt}**")
            if _ltc2.button("✕", key="sp_clear_tracking", use_container_width=True):
                del st.session_state["_sp_last_tracking"]
                st.rerun()

        # ── iShip pending (แสดงหลัง save) ────────────────────────────────
        if st.session_state.get("_sp_iship_pending"):
            _spp = st.session_state["_sp_iship_pending"]
            _spp_addr  = f"{_spp.get('address_line','')} {_spp.get('district','')} {_spp.get('amphure','')} {_spp.get('province','')} {_spp.get('zipcode','')}".strip()
            _spp_items = ", ".join(f"{it.get('product_id','')} {it.get('name','')} ×{it.get('qty',0)}" for it in (_spp.get("_items") or []))
            st.info(f"📦 **{_spp['dst_name']}** | ☎ {_spp.get('dst_phone','')}  \n{_spp_addr}  \n🛍️ {_spp_items}" if _spp_items else f"📦 **{_spp['dst_name']}** | ☎ {_spp.get('dst_phone','')}  \n{_spp_addr}")
            _si1, _si2 = st.columns([3, 1])
            _sp_car_pick = _si1.radio("ขนส่ง", ["Flash Express", "SPX Express"],
                                      index=0 if _spp["carrier"] == "Flash Express" else 1,
                                      horizontal=True, key="sp_iship_carrier")
            _spp["carrier"] = _sp_car_pick
            if _si1.button("🚚 ส่ง iShip", type="primary", use_container_width=True, key="sp_do_iship"):
                if iship_api.is_configured():
                    _sp_call = {k: _spp[k] for k in
                                {"dst_name","dst_phone","address_line","district",
                                 "amphure","province","zipcode","weight_kg",
                                 "cod_amount","carrier","remark","item_detail","products"} if k in _spp}
                    with st.spinner("กำลังสร้างรายการใน iShip..."):
                        _sp_resp = iship_api.create_order(**_sp_call)
                    if _sp_resp.get("status"):
                        _sp_tracking = (_sp_resp.get("data") or {}).get("tracking_code", "")
                        if _spp.get("_shipment_id") and _sp_tracking:
                            db.update_shipment_tracking(_spp["_shipment_id"], _sp_tracking)
                        st.session_state["_sp_last_tracking"] = _sp_tracking
                        del st.session_state["_sp_iship_pending"]
                        st.rerun()
                    else:
                        _sp_err = _sp_resp.get("message") or str(_sp_resp)
                        if "NotSupportAddress" in _sp_err:
                            st.error("❌ ที่อยู่ไม่ถูกต้อง — ตำบล / อำเภอ / จังหวัด ต้องตรงกับฐานข้อมูล iShip")
                        elif "500" in _sp_err or "DOCTYPE" in _sp_err:
                            st.warning("⚠️ iShip API ไม่รองรับ COD อัตโนมัติ — กรุณาสร้างใน iShip เอง")
                            _spp2 = st.session_state.get("_sp_iship_pending", {})
                            st.code(
                                f"ผู้รับ: {_spp2.get('dst_name','')} | {_spp2.get('dst_phone','')}\n"
                                f"ที่อยู่: {_spp2.get('address_line','')} {_spp2.get('district','')} {_spp2.get('amphure','')} {_spp2.get('province','')} {_spp2.get('zipcode','')}\n"
                                f"ขนส่ง: {_spp2.get('carrier','')} | COD: {_spp2.get('cod_amount',0):,} ฿\n"
                                f"หมายเหตุ: {_spp2.get('remark','')}",
                                language=None
                            )
                        else:
                            st.error(f"❌ iShip Error: {_sp_err}")
                else:
                    st.warning("⚙️ ยังไม่ได้ตั้งค่า ISHIP_TOKEN ใน secrets")
            if _si2.button("ปิด", key="sp_cancel_iship", use_container_width=True):
                del st.session_state["_sp_iship_pending"]
                st.rerun()
            st.divider()

        _sp = db.get_products()
        _sc = db.get_customers()
        _sc_map = {c["name"]: c for c in _sc}

        # ── เลือกลูกค้า + วันที่ ─────────────────────────────────────────
        _sp_c1, _sp_c2 = st.columns([3, 1])
        with _sp_c1:
            _sp_picked = st.session_state.get("_sp_cust_picked", "")
            if _sp_picked:
                _spx, _spy = st.columns([5, 1])
                _spx.markdown(f"👤 **{_sp_picked}**")
                if _spy.button("✕", key="sp_cust_clear"):
                    st.session_state.pop("_sp_cust_picked", None)
                    st.rerun()
                _sp_cust = _sp_picked
            else:
                _sp_search = st.text_input("ลูกค้า", placeholder="พิมพ์ชื่อ...", key="sp_cust_search")
                _sp_cust = "— เลือกลูกค้า —"
                if _sp_search.strip():
                    _sp_matches = [n for n in _sc_map if _sp_search.upper() in n.upper()][:6]
                    for _sm in _sp_matches:
                        if st.button(f"👤 {_sm}", key=f"sp_pick_{_sm}", use_container_width=True):
                            st.session_state["_sp_cust_picked"] = _sm
                            st.rerun()
        _sp_date = _sp_c2.date_input("วันที่", value=date.today(), key="sp_date")
        _sp_cid  = _sc_map[_sp_cust]["id"] if _sp_cust != "— เลือกลูกค้า —" else ""

        # ── ที่อยู่ผู้รับ ─────────────────────────────────────────────────
        with st.expander("📦 ที่อยู่ผู้รับ", expanded=True):
            # quick-select จากที่อยู่เดิมของลูกค้า
            if _sp_cid:
                try:
                    _sp_saved = db.get_customer_addresses(customer_id=_sp_cid)
                except Exception:
                    _sp_saved = []
                if _sp_saved:
                    st.caption("⚡ เลือกที่อยู่เดิม")
                    for _sa in _sp_saved:
                        _lbl = f"{_sa.get('recipient_name','')} · {_sa.get('phone','')} · {_sa.get('address_line','')} {_sa.get('district','')} {_sa.get('postal_code','')}"
                        if st.button(_lbl, key=f"qa_ship_{_sa['id']}", use_container_width=True):
                            for _k, _fld in [("sp_rname", "recipient_name"), ("sp_rphone", "phone"),
                                             ("sp_al", "address_line"), ("sp_dt", "district"),
                                             ("sp_am", "amphure"), ("sp_pv", "province")]:
                                st.session_state[_k] = _sa.get(_fld, "")
                            st.session_state["sp_pc"] = _sa.get("postal_code", "")
                            st.rerun()
                    st.divider()

            # apply staged address fill ก่อน render widgets
            for _fk, _wk in [("_fsp_dt","sp_dt"),("_fsp_am","sp_am"),
                              ("_fsp_pv","sp_pv"),("_fsp_pc","sp_pc")]:
                if _fk in st.session_state:
                    st.session_state[_wk] = st.session_state.pop(_fk)

            _sa1, _sa2 = st.columns(2)
            _sp_rname  = _sa1.text_input("ชื่อผู้รับ",    key="sp_rname")
            _sp_rphone = _sa2.text_input("เบอร์โทร",      key="sp_rphone")
            _sp_al     = st.text_input("บ้านเลขที่/ถนน",  key="sp_al")
            _sb1, _sb2, _sb3 = st.columns(3)
            _sp_dt = _sb1.text_input("ตำบล/แขวง",  key="sp_dt")
            _sp_am = _sb2.text_input("อำเภอ/เขต",   key="sp_am")
            _sp_pv = _sb3.selectbox("จังหวัด", [""] + _PROVINCES, key="sp_pv")
            _sp_last_dt = st.session_state.get("_sp_last_dt", "")
            if len((_sp_dt or "").strip()) >= 2 and _sp_dt.strip() != _sp_last_dt:
                _dt_opts = thai_address.lookup_by_tambon(_sp_dt.strip())
                for _o in _dt_opts:
                    _lbl = f"{_o['tambon']} » {_o['amphure']} » {_o['province']} ({_o['zipcode']})"
                    if st.button(_lbl, key=f"sp_dt_fill_{_o['tambon']}_{_o['zipcode']}", use_container_width=True):
                        st.session_state["_fsp_dt"] = _o["tambon"]
                        st.session_state["_fsp_am"] = _o["amphure"]
                        st.session_state["_fsp_pv"] = _o["province"]
                        st.session_state["_fsp_pc"] = _o["zipcode"]
                        st.session_state["_sp_last_dt"] = _o["tambon"]
                        st.session_state["_sp_last_pc"] = _o["zipcode"]
                        st.rerun()
            _sp_pc = st.text_input("รหัสไปรษณีย์", max_chars=5, key="sp_pc", placeholder="เช่น 10400")
            _sp_last_pc = st.session_state.get("_sp_last_pc", "")
            if len((_sp_pc or "").strip()) == 5 and _sp_pc.strip() != _sp_last_pc:
                _sp_pc_opts = thai_address.lookup(_sp_pc.strip())
                if _sp_pc_opts:
                    for _o in _sp_pc_opts[:8]:
                        _lbl = f"{_o['tambon']} » {_o['amphure']} » {_o['province']}"
                        if st.button(_lbl, key=f"sp_pc_fill_{_o['tambon']}_{_sp_pc}", use_container_width=True):
                            st.session_state["_fsp_dt"] = _o["tambon"]
                            st.session_state["_fsp_am"] = _o["amphure"]
                            st.session_state["_fsp_pv"] = _o["province"]
                            st.session_state["_sp_last_dt"] = _o["tambon"]
                            st.session_state["_sp_last_pc"] = _sp_pc.strip()
                            st.rerun()
            if _sp_cid and st.button("💾 บันทึกที่อยู่นี้", key="sp_save_addr"):
                db.upsert_customer_address({
                    "id":             str(uuid.uuid4()),
                    "customer_id":    _sp_cid,
                    "recipient_name": st.session_state.get("sp_rname", ""),
                    "phone":          st.session_state.get("sp_rphone", ""),
                    "address_line":   st.session_state.get("sp_al", ""),
                    "district":       st.session_state.get("sp_dt", ""),
                    "amphure":        st.session_state.get("sp_am", ""),
                    "province":       st.session_state.get("sp_pv", ""),
                    "postal_code":    st.session_state.get("sp_pc", ""),
                })
                st.success("✅ บันทึกที่อยู่แล้ว")

        # ── รายการสินค้าที่ส่ง ───────────────────────────────────────────
        st.caption("รายการสินค้าที่ส่ง (ไม่ตัด stock)")
        _sp_prod_keys = [f"{p['id']} — {p['name']}" for p in _sp]
        _sp_prod_map  = {f"{p['id']} — {p['name']}": p for p in _sp}
        _sp_cart_df   = pd.DataFrame({"สินค้า": pd.Series([""] * 3, dtype="object"),
                                      "จำนวน": pd.Series([0] * 3, dtype="int64")})
        _sp_cart_edit = st.data_editor(
            _sp_cart_df, num_rows="dynamic", hide_index=True, use_container_width=True,
            key="sp_cart",
            column_config={
                "สินค้า": st.column_config.SelectboxColumn("สินค้า", options=_sp_prod_keys),
                "จำนวน": st.column_config.NumberColumn("จำนวน", min_value=0, step=1, width="small"),
            },
        )
        _sp_items = [
            {"product_id": _sp_prod_map[r["สินค้า"]]["id"],
             "name": _sp_prod_map[r["สินค้า"]]["name"],
             "qty": int(r["จำนวน"] or 0)}
            for _, r in _sp_cart_edit.iterrows()
            if str(r.get("สินค้า","")) in _sp_prod_map and int(r.get("จำนวน") or 0) > 0
        ]

        # ── ขนส่ง + ค่าส่ง ───────────────────────────────────────────────
        _sp_fc1, _sp_fc2, _sp_fc3 = st.columns(3)
        _sp_fees = carrier_fees(0, _sp_pc.strip()) if len((_sp_pc or "").strip()) == 5 else None
        if _sp_fees:
            _sp_fc1.caption(f"Flash: {_sp_fees['Flash Express']['zone'] or 'ปกติ'} | +{_sp_fees['Flash Express']['surcharge']} ฿")
            _sp_fc2.caption(f"SPX:   {_sp_fees['SPX Express']['zone']   or 'ปกติ'} | +{_sp_fees['SPX Express']['surcharge']} ฿")
            _auto_car = _pick_carrier(_sp_pc.strip())
            if st.session_state.get("_sp_prev_pc") != _sp_pc:
                st.session_state["sp_carrier"] = _auto_car
                st.session_state["_sp_prev_pc"] = _sp_pc
        _sp_carrier = _sp_fc3.radio("ขนส่ง", ["Flash Express", "SPX Express"], key="sp_carrier")
        _sp_ship_base = {"Flash Express": 50, "SPX Express": 55}.get(_sp_carrier, 50)
        _sp_sur = (_sp_fees[_sp_carrier]["surcharge"] if _sp_fees else 0)
        _sp_cost = _sp_ship_base + _sp_sur
        st.caption(f"ค่าส่งประมาณ: **{_sp_cost} บาท** ({_sp_carrier})")

        # ── tracking + หมายเหตุ ───────────────────────────────────────────
        _sp_track = st.text_input("เลข tracking (กรอกทีหลังได้)", key="sp_track", placeholder="TH123456789")
        _sp_notes = st.text_input("หมายเหตุ", key="sp_notes")

        # ── บันทึก ────────────────────────────────────────────────────────
        if st.button("💾 บันทึกการส่งของ", type="primary", use_container_width=True, key="sp_save"):
            if not _sp_rname.strip():
                st.error("กรุณากรอกชื่อผู้รับ")
            elif not _sp_pc.strip():
                st.error("กรุณากรอกรหัสไปรษณีย์")
            else:
                _sp_new_id = str(uuid.uuid4())
                _sp_wt = sum(
                    float(_sp_prod_map.get(r["สินค้า"], {}).get("weight_grams") or 0) * int(r["จำนวน"] or 0)
                    for _, r in _sp_cart_edit.iterrows()
                    if str(r.get("สินค้า","")) in _sp_prod_map
                ) / 1000
                try:
                    db.create_shipment({
                        "id":             _sp_new_id,
                        "customer_id":    _sp_cid or None,
                        "recipient_name": _sp_rname.strip(),
                        "phone":          _sp_rphone.strip(),
                        "address_line":   _sp_al.strip(),
                        "district":       _sp_dt.strip(),
                        "amphure":        _sp_am.strip(),
                        "province":       _sp_pv.strip(),
                        "postal_code":    _sp_pc.strip(),
                        "carrier":        _sp_carrier,
                        "shipping_cost":  _sp_cost,
                        "items":          _sp_items,
                        "tracking_no":    _sp_track.strip(),
                        "notes":          _sp_notes.strip(),
                    })
                except Exception:
                    st.error("❌ ยังไม่ได้สร้าง table shipments — รัน SQL ใน supabase_setup.sql ก่อน")
                    st.stop()
                # ตั้ง iShip pending เพื่อส่งขนส่ง
                _sp_item_codes = " ".join(f"{it['product_id']}-{it['qty']}" for it in _sp_items)
                _sp_remark = " ".join(filter(None, [
                    _sp_cust if _sp_cust != "— เลือกลูกค้า —" else "",
                    _sp_item_codes,
                    _sp_notes.strip(),
                ]))
                st.session_state["_sp_iship_pending"] = {
                    "dst_name":     _sp_rname.strip(),
                    "dst_phone":    _sp_rphone.strip(),
                    "address_line": _sp_al.strip(),
                    "district":     _sp_dt.strip(),
                    "amphure":      _sp_am.strip(),
                    "province":     _sp_pv.strip(),
                    "zipcode":      _sp_pc.strip(),
                    "weight_kg":    max(0.5, _sp_wt),
                    "cod_amount":   0,
                    "carrier":      _sp_carrier,
                    "remark":       _sp_remark,
                    "item_detail":  ", ".join(f"{it['name']} x{it['qty']}" for it in _sp_items) or _sp_remark,
                    "products":     [{"name": it["name"], "qty": it["qty"], "price": 0} for it in _sp_items],
                    "_items":       _sp_items,
                    "_shipment_id": _sp_new_id,
                }
                for _k in ["sp_rname","sp_rphone","sp_al","sp_dt","sp_am","sp_pv","sp_pc","sp_track","sp_notes",
                           "_sp_cust_picked","sp_cust_search"]:
                    st.session_state.pop(_k, None)
                st.session_state.pop("sp_cart", None)
                st.rerun()

        st.caption("กรอกข้อมูลด้านบนแล้วกด 💾 บันทึกการส่งของ — tracking จะบันทึกอัตโนมัติหลังส่ง iShip")

    with _sub_shiphist:
        st.subheader("ประวัติการส่งของ")
        try:
            _sh_all = db.get_shipments()
        except Exception:
            st.warning("⚙️ ยังไม่ได้สร้าง table shipments")
            _sh_all = []

        if _sh_all:
            def _items_str(items):
                if not items:
                    return ""
                return ", ".join(f"{it.get('product_id','')} ×{it.get('qty',0)}" for it in items)

            _sh_ids  = [r["id"] for r in _sh_all]
            _sh_df   = pd.DataFrame([{
                "วันที่/เวลา":     _to_bkk(r.get("created_at") or ""),
                "ลูกค้า":          (r.get("customers") or {}).get("name", ""),
                "ผู้รับ":           r.get("recipient_name", ""),
                "เบอร์":            r.get("phone", ""),
                "บ้านเลขที่/ถนน":  r.get("address_line", ""),
                "ตำบล":            r.get("district", ""),
                "อำเภอ":           r.get("amphure", ""),
                "จังหวัด":         r.get("province", ""),
                "รหัสปณ.":         r.get("postal_code", ""),
                "รายการ":          _items_str(r.get("items")),
                "ขนส่ง":           r.get("carrier", ""),
                "หมายเหตุ":        r.get("notes", ""),
                "ลบ":              False,
            } for r in _sh_all])

            _sh_edit = st.data_editor(
                _sh_df,
                hide_index=True, use_container_width=True, key="sh_hist_tbl",
                disabled=["วันที่/เวลา","ลูกค้า","ผู้รับ","เบอร์",
                          "บ้านเลขที่/ถนน","ตำบล","อำเภอ","จังหวัด","รหัสปณ.",
                          "รายการ","ขนส่ง","หมายเหตุ"],
                column_config={
                    "ลบ": st.column_config.CheckboxColumn("ลบ", default=False, width="small"),
                },
            )

            _sh_to_del = [_sh_ids[i] for i, v in enumerate(_sh_edit["ลบ"]) if v]

            if _sh_to_del:
                if st.button(f"🗑️ ลบที่เลือก ({len(_sh_to_del)} รายการ)", type="primary", key="sh_del_btn"):
                    for _did in _sh_to_del:
                        try:
                            db.delete_shipment(_did)
                        except Exception:
                            pass
                    st.session_state.pop("sh_hist_tbl", None)
                    st.rerun()
        else:
            st.info("ยังไม่มีประวัติการส่งของ")

# Tab 2: ยอดค้าง + จัดการออเดอร์ (รวม Tab 2+3 เดิม)
# ─────────────────────────────────────────────────────────────────────────────
with tab2:
    st.subheader("ยอดค้างลูกค้า")

    customers = db.get_customers()
    if not customers:
        st.info("ยังไม่มีข้อมูล")
    else:
        # ── Summary metrics ────────────────────────────────────────────────
        unbilled     = db.get_unbilled_pv_summary()
        _outs_all    = db.get_outstanding_df()
        if not _outs_all.empty:
            sm1, sm2, sm3 = st.columns(3)
            sm1.metric("ค้างจ่ายรวม",   f"{_outs_all['ค้างจ่าย'].sum():,.0f} ฿")
            sm2.metric("ค้างรับรวม",    f"{int(_outs_all['ค้างรับ'].sum())} ชิ้น")
            sm3.metric("PV รอเปิดบิล", f"{unbilled['total_pv']:,.0f}")
            st.divider()

        # ── Filter ────────────────────────────────────────────────────────
        fc1, fc2, fc3 = st.columns([2, 2, 3])
        _t2_search      = fc1.text_input("🔍 ลูกค้า", placeholder="พิมพ์ชื่อ...", key="tab2_search")
        _t2_bill_search = fc2.text_input("🔍 เลขที่บิล", placeholder="เช่น 260427", key="tab2_bill_search")
        filter_bill = fc3.radio("สถานะบิล", ["ค้างอยู่ทั้งหมด", "ยังไม่เปิดบิล", "เปิดบิลแล้ว"],
                                horizontal=True, key="tab2_filter_bill")

        outstanding_df = db.get_outstanding_df()
        if filter_bill == "ยังไม่เปิดบิล":
            outstanding_df = outstanding_df[outstanding_df["สถานะบิล"] == "ยังไม่เปิดบิล"]
        elif filter_bill == "เปิดบิลแล้ว":
            outstanding_df = outstanding_df[outstanding_df["สถานะบิล"] == "เปิดบิลแล้ว"]
        if _t2_search.strip():
            outstanding_df = outstanding_df[
                outstanding_df["ลูกค้า"].str.contains(_t2_search.strip(), case=False, na=False)
            ]
        if _t2_bill_search.strip():
            outstanding_df = outstanding_df[
                outstanding_df["เลขที่บิล"].fillna("").str.contains(_t2_bill_search.strip(), case=False)
            ]

        if outstanding_df.empty:
            st.success("✅ ไม่มียอดค้าง")
        else:
            single_cust = (_t2_search.strip() != "" or _t2_bill_search.strip() != "") and outstanding_df["ลูกค้า"].nunique() == 1
            for customer_name, grp in outstanding_df.groupby("ลูกค้า"):
                owed    = grp["ค้างจ่าย"].sum()
                pending = int(grp["ค้างรับ"].sum())
                txn_ids = grp["id"].tolist()
                exp_label = f"**{customer_name}** — ค้างจ่าย {owed:,.0f}฿ | ค้างรับ {pending} ชิ้น"

                with st.expander(exp_label, expanded=single_cust):
                    # ── Styled table + row selection ──────────────────────
                    _dcols  = ["เลขที่บิล", "วันที่", "รหัส", "สินค้า", "สั่ง", "ค้างรับ",
                               "ยอดรวม", "ค้างจ่าย", "สถานะบิล"]
                    _id_map = grp["id"].reset_index(drop=True)
                    st.caption("คลิกแถวเพื่อเลือก (Ctrl/Shift สำหรับหลายแถว)")
                    _evt = st.dataframe(
                        grp[_dcols].reset_index(drop=True).style
                            .format({"ยอดรวม": "{:,.0f}", "ค้างจ่าย": "{:,.0f}"})
                            .map(_style_status, subset=["สถานะบิล"])
                            .map(lambda v: "background-color:#6b1a1a;color:white"
                                 if isinstance(v, (int, float)) and v > 0 else "",
                                 subset=["ค้างรับ", "ค้างจ่าย"]),
                        use_container_width=True,
                        hide_index=True,
                        selection_mode="multi-row",
                        on_select="rerun",
                        key=f"sel_tbl_{customer_name}",
                    )
                    _sel_idx  = _evt.selection.rows if hasattr(_evt, "selection") else []
                    selected_ids = [_id_map.iloc[i] for i in _sel_idx]

                    if selected_ids:
                        sel_rows       = grp[grp["id"].isin(selected_ids)]
                        total_selected = sel_rows["ค้างจ่าย"].sum()
                        st.info(f"เลือก {len(selected_ids)} รายการ — ค้างจ่ายรวม **{total_selected:,.0f} บาท**")

                    st.divider()

                    # ── Action panel ──────────────────────────────────────
                    if len(selected_ids) == 0:
                        st.info("☝️ เลือกรายการด้านบนเพื่อดำเนินการ")

                    elif len(selected_ids) == 1:
                        txn_id  = selected_ids[0]
                        balance = db.get_transaction_balance(txn_id)
                        txn     = balance["transaction"]
                        sel_row = grp[grp["id"] == txn_id].iloc[0]

                        st.caption(
                            f"📅 {sel_row['วันที่']}  ·  "
                            f"ราคา {float(txn['price_per_unit']):,.0f} ฿/ชิ้น  ·  "
                            f"รวม {float(txn['total_amount']):,.0f} ฿  ·  "
                            f"จ่ายแล้ว {balance['total_paid']:,.0f} ฿  ·  "
                            f"ค้างจ่าย **{balance['outstanding_amount']:,.0f} ฿**  ·  "
                            f"รับแล้ว {balance['total_received']} ชิ้น  ·  "
                            f"ค้างรับ {balance['outstanding_qty']} ชิ้น"
                        )

                        is_unbilled = txn["bill_status"] == "ยังไม่เปิดบิล"
                        radio_opts  = (["📄 เปิดบิล"] if is_unbilled else []) + [
                            "💵 จ่ายเงิน", "📦 รับของ", "💵+📦 จ่ายเงิน + รับของ"
                        ]
                        action = st.radio("บันทึก", radio_opts, horizontal=True, key=f"etype_{txn_id}")

                        if action == "📄 เปิดบิล":
                            with st.form(f"bill_{txn_id}", clear_on_submit=True):
                                bc1, bc2 = st.columns([3, 1])
                                qty_to_open = bc1.number_input(
                                    "จำนวนที่เปิดบิล", min_value=1,
                                    max_value=int(txn["qty"]), value=int(txn["qty"]), step=1,
                                )
                                bc2.write("")
                                submit_bill = bc2.form_submit_button(
                                    "📄 เปิดบิล", use_container_width=True, type="primary"
                                )
                            if submit_bill:
                                if qty_to_open == int(txn["qty"]):
                                    db.update_transaction_status(txn_id, bill_status="เปิดบิลแล้ว")
                                else:
                                    db.split_and_open_bill(txn_id, qty_to_open)
                                st.rerun()
                        else:
                            evt_map  = {
                                "💵 จ่ายเงิน": "จ่ายเงิน",
                                "📦 รับของ": "รับของ",
                                "💵+📦 จ่ายเงิน + รับของ": "จ่ายเงิน + รับของ",
                            }
                            evt_type = evt_map[action]
                            _price   = float(txn["price_per_unit"])
                            _outs_q  = int(balance["outstanding_qty"])
                            _hint    = f"ราคา/ชิ้น: {_price:,.0f} ฿"
                            for _n in range(1, min(_outs_q, 5) + 1):
                                _hint += f"  ·  {_n} ชิ้น = {_n * _price:,.0f} ฿"
                            st.caption(_hint)
                            _def_amt = float(balance["outstanding_amount"]) if evt_type != "รับของ" else 0.0
                            _def_qty = _outs_q if evt_type != "จ่ายเงิน" else 0
                            with st.form(f"evt_{txn_id}", clear_on_submit=True):
                                fc1, fc2, fc3 = st.columns([2, 2, 1])
                                amount_paid  = fc1.number_input(
                                    "เงินที่จ่าย (บาท)", min_value=0.0, step=100.0,
                                    value=_def_amt,
                                    disabled=(evt_type == "รับของ"),
                                )
                                qty_received = fc2.number_input(
                                    "จำนวนที่รับ (ชิ้น)", min_value=0, step=1,
                                    value=_def_qty,
                                    disabled=(evt_type == "จ่ายเงิน"),
                                )
                                event_date  = fc3.date_input("วันที่", value=date.today())
                                event_notes = st.text_input("หมายเหตุ", key=f"enotes_{txn_id}")
                                submit_evt  = st.form_submit_button(
                                    "💾 บันทึก", use_container_width=True, type="primary"
                                )
                            if submit_evt:
                                error = None
                                if evt_type in ("รับของ", "จ่ายเงิน + รับของ") and qty_received > 0:
                                    new_paid = balance["total_paid"] + amount_paid
                                    price    = float(txn["price_per_unit"])
                                    max_ok   = floor(new_paid / price) if price > 0 else 0
                                    if balance["total_received"] + qty_received > max_ok:
                                        can   = max(0, max_ok - balance["total_received"])
                                        error = f"❌ รับได้สูงสุด {can} ชิ้น (จ่ายแล้ว {new_paid:,.0f} บาท)"
                                if error:
                                    st.error(error)
                                else:
                                    db.insert_partial_event({
                                        "id":             str(uuid.uuid4()),
                                        "date":           str(event_date),
                                        "transaction_id": txn_id,
                                        "qty_received":   int(qty_received),
                                        "amount_paid":    float(amount_paid),
                                        "event_type":     evt_type,
                                        "notes":          event_notes,
                                    })
                                    st.success("✅ บันทึกแล้ว")
                                    st.rerun()

                        if not is_unbilled:
                            st.divider()
                            if st.button("↩️ ยกเลิกบิล", key=f"cancel_{txn_id}"):
                                db.update_transaction_status(txn_id, bill_status="ยังไม่เปิดบิล")
                                st.rerun()

                    else:
                        # Multi: เปิดบิล หรือ จ่ายเงิน
                        sel_rows      = grp[grp["id"].isin(selected_ids)]
                        total_owed    = sel_rows["ค้างจ่าย"].sum()
                        _all_unbilled = (sel_rows["สถานะบิล"] == "ยังไม่เปิดบิล").all()
                        st.write(f"**เลือก {len(selected_ids)} รายการ — ยอดค้างรวม {total_owed:,.0f} บาท**")
                        st.dataframe(
                            sel_rows[["สินค้า", "สั่ง", "ค้างจ่าย", "สถานะบิล"]].style.format(
                                {"ค้างจ่าย": "{:,.0f}"}
                            ),
                            use_container_width=True, hide_index=True,
                        )
                        _m_opts = (["📄 เปิดบิล"] if _all_unbilled else []) + ["📦 รับของ", "💵 จ่ายเงิน"]
                        _m_act  = st.radio("บันทึก", _m_opts, horizontal=True,
                                           key=f"multi_act_{customer_name}")

                        if _m_act == "📄 เปิดบิล":
                            if st.button(f"📄 เปิดบิลทั้งหมด {len(selected_ids)} รายการ",
                                         type="primary", use_container_width=True,
                                         key=f"multi_open_{customer_name}"):
                                for _sid in selected_ids:
                                    db.update_transaction_status(_sid, bill_status="เปิดบิลแล้ว")
                                st.success(f"✅ เปิดบิล {len(selected_ids)} รายการแล้ว")
                                st.rerun()
                        elif _m_act == "📦 รับของ":
                            _pending_recv = sel_rows[sel_rows["ค้างรับ"] > 0]
                            if _pending_recv.empty:
                                st.info("ไม่มีรายการที่ค้างรับ")
                            else:
                                _recv_rows = [{"_id": r["id"], "สินค้า": r["สินค้า"],
                                               "ค้างรับ": int(r["ค้างรับ"]),
                                               "รับจริง": int(r["ค้างรับ"])}
                                              for _, r in _pending_recv.iterrows()]
                                _recv_df = pd.DataFrame(_recv_rows)
                                _edited_recv = st.data_editor(
                                    _recv_df[["สินค้า","ค้างรับ","รับจริง"]],
                                    column_config={
                                        "สินค้า":  st.column_config.TextColumn(disabled=True),
                                        "ค้างรับ": st.column_config.NumberColumn(disabled=True),
                                        "รับจริง": st.column_config.NumberColumn("รับจริง ✏️", min_value=0, format="%d"),
                                    },
                                    hide_index=True, use_container_width=True,
                                    key=f"multi_recv_tbl_{customer_name}",
                                )
                                mr1, mr2 = st.columns([2, 1])
                                mp_notes_r = mr1.text_input("หมายเหตุ", key=f"mp_notes_r_{customer_name}")
                                mp_date_r  = mr2.date_input("วันที่รับ", value=date.today(), key=f"mp_date_r_{customer_name}")
                                if st.button(f"📦 บันทึกรับของ", type="primary",
                                             use_container_width=True, key=f"multi_recv_{customer_name}"):
                                    for i, _rrow in _recv_df.iterrows():
                                        _qty = int(_edited_recv.iloc[i]["รับจริง"])
                                        if _qty > 0:
                                            db.insert_partial_event({
                                                "id":             str(uuid.uuid4()),
                                                "date":           str(mp_date_r),
                                                "transaction_id": _rrow["_id"],
                                                "qty_received":   _qty,
                                                "amount_paid":    0.0,
                                                "event_type":     "รับของ",
                                                "notes":          mp_notes_r,
                                            })
                                    st.success("✅ บันทึกรับของแล้ว")
                                    st.rerun()
                        else:
                            # ตารางแก้ยอดจ่ายได้ทีละแถว
                            _pay_rows = [{"_id": r["id"], "สินค้า": r["สินค้า"],
                                          "สั่ง": r["สั่ง"], "ค้างจ่าย": r["ค้างจ่าย"],
                                          "จ่ายจริง": r["ค้างจ่าย"]}
                                         for _, r in sel_rows.iterrows()]
                            _pay_df = pd.DataFrame(_pay_rows)
                            _edited = st.data_editor(
                                _pay_df[["สินค้า", "สั่ง", "ค้างจ่าย", "จ่ายจริง"]],
                                column_config={
                                    "สินค้า":   st.column_config.TextColumn(disabled=True),
                                    "สั่ง":     st.column_config.NumberColumn(disabled=True),
                                    "ค้างจ่าย": st.column_config.NumberColumn(disabled=True, format="%.0f"),
                                    "จ่ายจริง": st.column_config.NumberColumn("จ่ายจริง ✏️", min_value=0, format="%.0f"),
                                },
                                hide_index=True, use_container_width=True,
                                key=f"multi_pay_tbl_{customer_name}",
                            )
                            _total_pay = float(_edited["จ่ายจริง"].sum())
                            st.metric("ยอดจ่ายรวม", f"{_total_pay:,.0f} บาท")
                            mp2, mp3 = st.columns([2, 1])
                            mp_notes = mp2.text_input("หมายเหตุ", key=f"mp_notes_{customer_name}")
                            mp_date  = mp3.date_input("วันที่", value=date.today(), key=f"mp_date_{customer_name}")
                            if st.button("💾 บันทึกการจ่ายเงิน", type="primary",
                                         use_container_width=True, key=f"multi_save_{customer_name}"):
                                for i, row in _pay_df.iterrows():
                                    _amt = float(_edited.iloc[i]["จ่ายจริง"])
                                    if _amt > 0:
                                        db.insert_partial_event({
                                            "id":             str(uuid.uuid4()),
                                            "date":           str(mp_date),
                                            "transaction_id": row["_id"],
                                            "qty_received":   0,
                                            "amount_paid":    _amt,
                                            "event_type":     "จ่ายเงิน",
                                            "notes":          mp_notes,
                                        })
                                st.success(f"✅ บันทึกการจ่าย {_total_pay:,.0f} บาท ครอบ {len(selected_ids)} รายการแล้ว")
                                for tid in txn_ids:
                                    st.session_state[f"chk_{tid}"] = False
                                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Tab 4: จัดการข้อมูลหลัก
# ─────────────────────────────────────────────────────────────────────────────
with tab4:
    st.subheader("จัดการข้อมูลหลัก")

    sub1, sub2, sub3, sub4 = st.tabs(["🏷️ สินค้า", "👤 ลูกค้า", "📍 ที่อยู่", "🗑️ ลบบิล"])

    # ── iShip API debug ─────────────────────────────────────────────────────
    with st.expander("🔧 ทดสอบ iShip API"):
        import requests as _rq, os as _os, iship_api as _ia
        _tok   = _os.environ.get("ISHIP_TOKEN") or st.secrets.get("ISHIP_TOKEN", "")
        _email = _os.environ.get("ISHIP_EMAIL") or st.secrets.get("ISHIP_EMAIL", "")
        _pw    = _os.environ.get("ISHIP_PASSWORD") or st.secrets.get("ISHIP_PASSWORD", "")

        # Test 1: Bearer token กับ web endpoint
        if st.button("1) GET /shipment/create + Bearer Token", key="iship_t1"):
            try:
                r = _rq.get("https://app.iship.cloud/shipment/create",
                            headers={"Authorization": f"Bearer {_tok}", "Accept": "application/json"},
                            timeout=10)
                st.write(f"status {r.status_code} | url: {r.url}")
                try: st.json(r.json())
                except: st.code(r.text[:300])
            except Exception as e:
                st.error(str(e))

        # Test 2: /api/create_order + product_lists เป็น JSON array จริง
        if st.button("2) /api/create_order (product_lists=array, COD=100)", key="iship_t2"):
            _src = _ia._src()
            _p = {
                "courier_code": "FlashExpressA",
                "src_name": _src["ISHIP_SRC_NAME"], "src_phone": _src["ISHIP_SRC_PHONE"],
                "src_address": _src["ISHIP_SRC_ADDRESS"], "src_district": _src["ISHIP_SRC_DISTRICT"],
                "src_amphure": _src["ISHIP_SRC_AMPHURE"], "src_province": _src["ISHIP_SRC_PROVINCE"],
                "src_zipcode": _src["ISHIP_SRC_ZIPCODE"],
                "dst_name": "ทดสอบ", "dst_phone": "0800000000",
                "dst_address": "1/1", "dst_district": "ลาดยาว",
                "dst_amphure": "จตุจักร", "dst_province": "กรุงเทพมหานคร", "dst_zipcode": "10900",
                "weight": 1, "cod_amount": 100, "remark": "test",
                "use_onlabel": "1", "label_name": _src["ISHIP_LABEL_NAME"],
                "label_phone": _src["ISHIP_LABEL_PHONE"],
                "label_address": _src["ISHIP_SRC_ADDRESS"], "label_zipcode": _src["ISHIP_SRC_ZIPCODE"],
                "create_mode": "add", "order_type": "1", "category_id": "2",
                "product_lists": [{"product_name":"สินค้าซูเลียน","product_qty":"1",
                                   "product_length":"10","product_width":"10","product_height":"5",
                                   "product_weight":"1","product_color":"น้ำตาล",
                                   "product_price":"100","product_remark":""}],
            }
            try:
                r = _rq.post("https://app.iship.cloud/api/create_order", json=_p,
                             headers={"Authorization": f"Bearer {_tok}", "Accept": "application/json"},
                             timeout=15)
                st.write(f"status {r.status_code}")
                try: st.json(r.json())
                except: st.code(r.text[:500])
            except Exception as e:
                st.error(str(e))

        # Test 3: Web login แบบ browser จริง
        if st.button("3) Web Login (Chrome headers)", key="iship_t3"):
            if not _email:
                st.error("ไม่มี ISHIP_EMAIL ใน secrets")
            else:
                s = _rq.Session()
                s.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept-Language": "th,en-US;q=0.9,en;q=0.8",
                })
                r1 = s.get("https://app.iship.cloud/login", timeout=10)
                import re as _re
                m = _re.search(r'<input[^>]+name="_token"[^>]+value="([^"]+)"', r1.text)
                if not m:
                    st.error(f"หา _token ไม่เจอ (status={r1.status_code})")
                else:
                    r2 = s.post("https://app.iship.cloud/login", data={
                        "_token": m.group(1), "email": _email, "password": _pw, "remember": "1",
                    }, headers={"Referer": "https://app.iship.cloud/login",
                                "Origin": "https://app.iship.cloud"},
                    timeout=10, allow_redirects=True)
                    st.write(f"status {r2.status_code} | URL: {r2.url}")
                    st.write(f"Cookies: {dict(s.cookies)}")

        # Test 4: ดู login form fields ทั้งหมด
        if st.button("4) ดู Login Form Fields", key="iship_t4"):
            import re as _re2
            r = _rq.get("https://app.iship.cloud/login", timeout=10)
            st.write(f"status {r.status_code}")
            for f in _re2.findall(r'<input[^>]+>', r.text):
                st.code(f)

        # Test 5: Login แล้วดู error message
        if st.button("5) Login + ดู Error Message", key="iship_t5"):
            if not _email:
                st.error("ไม่มี ISHIP_EMAIL")
            else:
                import re as _re2
                s2 = _rq.Session()
                s2.headers.update({"User-Agent": "Mozilla/5.0 Chrome/120"})
                r1 = s2.get("https://app.iship.cloud/login", timeout=10)
                m = _re2.search(r'<input[^>]+name="_token"[^>]+value="([^"]+)"', r1.text)
                if not m:
                    st.error("หา _token ไม่เจอ")
                else:
                    r2 = s2.post("https://app.iship.cloud/login", data={
                        "_token": m.group(1), "email": _email, "password": _pw, "remember": "1",
                    }, headers={"Referer": "https://app.iship.cloud/login",
                                "Origin": "https://app.iship.cloud"},
                    timeout=10, allow_redirects=True)
                    st.write(f"URL: {r2.url}")
                    err  = _re2.search(r'class="[^"]*alert[^"]*"[^>]*>(.*?)</div>', r2.text, _re2.DOTALL)
                    err2 = _re2.search(r'"errors"\s*:\s*(\{[^}]+\})', r2.text)
                    st.code(err.group(1).strip() if err else "ไม่พบ alert")
                    st.code(err2.group(1) if err2 else "ไม่พบ errors JSON")
                    for f in _re2.findall(r'<input[^>]+name="[^"]*"[^>]*>', r2.text)[:10]:
                        st.code(f)

    with sub1:
        products = db.get_products()

        prod_cols = ["id", "name", "price", "points_per_unit", "bv_per_unit", "weight_grams"]
        col_rename = {
            "id": "รหัส", "name": "ชื่อสินค้า", "price": "ราคา (บาท)",
            "points_per_unit": "PV/หน่วย", "bv_per_unit": "BV/หน่วย", "weight_grams": "น้ำหนัก (g)",
        }
        if products:
            prod_df = pd.DataFrame(products)[prod_cols].rename(columns=col_rename)
        else:
            prod_df = pd.DataFrame(columns=list(col_rename.values()))

        st.write("**แก้ไขหรือเพิ่มสินค้า** — แก้ในตารางได้โดยตรง กด `+` ที่มุมล่างขวาเพื่อเพิ่มแถวใหม่")
        edited_prod_df = st.data_editor(
            prod_df,
            num_rows="dynamic",
            use_container_width=True,
            key="prod_editor",
            column_config={
                "รหัส":        st.column_config.TextColumn("รหัส", required=True),
                "ชื่อสินค้า":  st.column_config.TextColumn("ชื่อสินค้า", required=True),
                "ราคา (บาท)":  st.column_config.NumberColumn("ราคา (บาท)", min_value=0, step=10.0, format="%.2f"),
                "PV/หน่วย":    st.column_config.NumberColumn("PV/หน่วย",   min_value=0, step=1.0,  format="%.2f"),
                "BV/หน่วย":    st.column_config.NumberColumn("BV/หน่วย",   min_value=0, step=1.0,  format="%.2f"),
                "น้ำหนัก (g)": st.column_config.NumberColumn("น้ำหนัก (g)", min_value=0, step=10.0, format="%.0f"),
            },
        )
        if st.button("💾 บันทึกทั้งหมด", key="save_prod_editor", use_container_width=True, type="primary"):
            valid = edited_prod_df.dropna(subset=["รหัส", "ชื่อสินค้า"])
            valid = valid[valid["รหัส"].astype(str).str.strip() != ""]
            if valid.empty:
                st.error("ไม่มีข้อมูลที่จะบันทึก")
            else:
                for _, row in valid.iterrows():
                    db.upsert_product({
                        "id":              str(row["รหัส"]).strip(),
                        "name":            str(row["ชื่อสินค้า"]).strip(),
                        "price":           float(row["ราคา (บาท)"]  or 0),
                        "points_per_unit": float(row["PV/หน่วย"]    or 0),
                        "bv_per_unit":     float(row["BV/หน่วย"]    or 0),
                        "weight_grams":    float(row["น้ำหนัก (g)"] or 0),
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

    with sub2:
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
            use_container_width=True,
            key="cust_editor",
            column_config={
                "รหัส":       st.column_config.TextColumn("รหัส", help="เว้นว่างให้ระบบออกรหัสอัตโนมัติ"),
                "ชื่อลูกค้า": st.column_config.TextColumn("ชื่อลูกค้า", required=True),
                "เบอร์โทร":   st.column_config.TextColumn("เบอร์โทร"),
            },
        )
        if st.button("💾 บันทึกทั้งหมด", key="save_cust_editor", use_container_width=True, type="primary"):
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

    with sub3:
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
                use_container_width=True,
                key="addr_tbl",
            )
            _to_delete = [_addr_ids[i] for i, v in enumerate(_edited_addr["ลบ"]) if v]
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
                if st.form_submit_button("💾 บันทึก", type="primary", use_container_width=True):
                    _cur_cust = st.session_state.get("ea3c_cust", "— เลือกลูกค้า —")
                    _ea_cust_id = next((c["id"] for c in all_custs if c["name"] == _cur_cust), "")
                    if not _ea_cust_id:
                        st.error("กรุณาเลือกลูกค้าก่อนบันทึก")
                        st.stop()
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
                    st.success("✅ บันทึกแล้ว")
                    st.rerun()

    with sub4:
        st.caption("เลือกเลขที่บิลที่ต้องการลบ — จะลบทุกรายการในบิลนั้น")
        _bill_list = db.get_bill_list()
        if _bill_list:
            _sel_bill = st.selectbox("เลขที่บิล", _bill_list, key="del_bill_sel")

            _bill_rows = db.get_bill_details(_sel_bill)
            if _bill_rows:
                _bill_date = (_bill_rows[0].get("date") or "")[:10]
                _bill_cust = (_bill_rows[0].get("customers") or {}).get("name", "—")
                _bill_status = _bill_rows[0].get("bill_status", "")
                st.markdown(f"**วันที่:** {_bill_date} &nbsp;|&nbsp; **ลูกค้า:** {_bill_cust} &nbsp;|&nbsp; **สถานะ:** {_bill_status}")
                _preview_df = pd.DataFrame([{
                    "สินค้า":      r.get("product_name", ""),
                    "จำนวน":      r.get("qty", 0),
                    "ราคา/หน่วย": r.get("price_per_unit", 0),
                    "ยอดรวม":     r.get("total_amount", 0),
                } for r in _bill_rows])
                st.dataframe(_preview_df, use_container_width=True, hide_index=True)
                _grand = sum(r.get("total_amount") or 0 for r in _bill_rows)
                st.markdown(f"**ยอดรวมทั้งบิล: {_grand:,.0f} บาท** ({len(_bill_rows)} รายการ)")

            st.divider()
            if st.button("🗑️ ลบบิลนี้", type="primary", key="del_bill_btn"):
                _n = db.delete_bill(_sel_bill)
                st.success(f"✅ ลบบิล {_sel_bill} แล้ว ({_n} รายการ)")
                st.rerun()
        else:
            st.info("ไม่มีบิลในระบบ")


# ─────────────────────────────────────────────────────────────────────────────
# Tab 5: ประวัติทั้งหมด
# ─────────────────────────────────────────────────────────────────────────────
with tab5:
    st.subheader("ประวัติรายการทั้งหมด")

    customers_h = db.get_customers()
    h_col1, h_col2 = st.columns(2)
    with h_col1:
        h_filter_cust = st.selectbox(
            "กรองตามลูกค้า",
            ["ทั้งหมด"] + [c["name"] for c in customers_h],
            key="hist_cust",
        )
    with h_col2:
        h_filter_status = st.selectbox(
            "กรองตามสถานะ",
            ["ทั้งหมด", "ค้างจ่าย", "ค้างรับของ", "ยังไม่เปิดบิล", "เคลียร์แล้ว"],
            key="hist_status",
        )

    h_cid = None
    if h_filter_cust != "ทั้งหมด":
        h_cid = next(c["id"] for c in customers_h if c["name"] == h_filter_cust)

    all_df = db.get_all_transactions_df(customer_id=h_cid)

    if not all_df.empty:
        if h_filter_status == "ค้างจ่าย":
            all_df = all_df[all_df["ค้างจ่าย"] > 0]
        elif h_filter_status == "ค้างรับของ":
            all_df = all_df[all_df["ค้างรับ"] > 0]
        elif h_filter_status == "ยังไม่เปิดบิล":
            all_df = all_df[all_df["สถานะบิล"] == "ยังไม่เปิดบิล"]
        elif h_filter_status == "เคลียร์แล้ว":
            all_df = all_df[all_df["เคลียร์แล้ว"]]

    if all_df.empty:
        st.info("ไม่มีข้อมูล")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("รายการทั้งหมด", len(all_df))
        m2.metric("เคลียร์แล้ว", int(all_df["เคลียร์แล้ว"].sum()))
        m3.metric("ยังค้างอยู่", int((~all_df["เคลียร์แล้ว"]).sum()))

        display_cols_h = ["เลขที่บิล", "วันที่", "ลูกค้า", "รหัส", "สินค้า", "สั่ง", "รับแล้ว",
                          "ยอดรวม", "จ่ายแล้ว", "ค้างจ่าย", "ค้างรับ",
                          "สถานะบิล", "สถานะจ่าย", "หมายเหตุ"]
        show_df = all_df[display_cols_h].reset_index(drop=True)
        show_df["หมายเหตุ"] = show_df["หมายเหตุ"].fillna("").apply(_fmt_note)
        id_map  = all_df["id"].reset_index(drop=True)

        chk_df = show_df.copy()
        chk_df.insert(0, "🗑️", False)

        edited_h = st.data_editor(
            chk_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "🗑️":      st.column_config.CheckboxColumn("🗑️", default=False, width="small"),
                "ยอดรวม":  st.column_config.NumberColumn("ยอดรวม",  format="%,.0f"),
                "จ่ายแล้ว": st.column_config.NumberColumn("จ่ายแล้ว", format="%,.0f"),
                "ค้างจ่าย": st.column_config.NumberColumn("ค้างจ่าย", format="%,.0f"),
            },
            disabled=[c for c in chk_df.columns if c != "🗑️"],
            key="hist_table",
        )

        to_del_idx = edited_h[edited_h["🗑️"]].index.tolist()
        if to_del_idx:
            d1, d2 = st.columns([2, 1])
            d1.warning(f"เลือก {len(to_del_idx)} รายการ")
            if d2.button("🗑️ ลบรายการที่เลือก", type="secondary", use_container_width=True, key="hist_del_chk_btn"):
                for i in to_del_idx:
                    db.delete_transaction(id_map.iloc[i])
                st.success(f"✅ ลบ {len(to_del_idx)} รายการแล้ว")
                st.session_state.pop("hist_table", None)
                st.rerun()

        st.divider()
        with st.expander("✏️ แก้ไขรายการ"):
            all_products_e = db.get_products()
            all_customers_e = db.get_customers()
            product_map_e = {p["name"]: p for p in all_products_e}
            customer_map_e = {c["name"]: c for c in all_customers_e}

            edit_opts = {
                f"{r['วันที่']}  {r['ลูกค้า']}  {r['สินค้า']} ×{r['สั่ง']}": r["id"]
                for _, r in all_df.iterrows()
            }
            edit_sel = st.selectbox("เลือกรายการที่จะแก้ไข", list(edit_opts.keys()), key="edit_sel")
            edit_txn_id = edit_opts[edit_sel]

            edit_balance = db.get_transaction_balance(edit_txn_id)
            et = edit_balance["transaction"]

            prod_names = list(product_map_e.keys())
            cust_names = list(customer_map_e.keys())
            _tgt_prod = next((p["name"] for p in all_products_e if p["id"] == et["product_id"]), "")
            _tgt_cust = next((c["name"] for c in all_customers_e if c["id"] == et["customer_id"]), "")
            cur_prod_idx = prod_names.index(_tgt_prod) if _tgt_prod in prod_names else 0
            cur_cust_idx = cust_names.index(_tgt_cust) if _tgt_cust in cust_names else 0
            cur_bill_idx = 0 if et["bill_status"] == "เปิดบิลแล้ว" else 1
            cur_pay_idx = 0 if et["pay_status"] == "จ่ายแล้ว" else 1
            cur_receipt_idx = 0 if et["initial_qty_received"] > 0 else 1

            with st.form("edit_transaction"):
                ec1, ec2, ec3 = st.columns([2, 2, 1])
                with ec1:
                    e_customer = st.selectbox("ลูกค้า", cust_names, index=cur_cust_idx)
                with ec2:
                    e_product = st.selectbox("สินค้า", prod_names, index=cur_prod_idx)
                with ec3:
                    e_qty = st.number_input("จำนวน", min_value=1, value=int(et["qty"]), step=1)

                e_sel_prod = product_map_e[e_product]
                e_total = float(e_sel_prod["price"]) * e_qty
                e_total_pts = float(e_sel_prod["points_per_unit"]) * e_qty

                em1, em2, em3 = st.columns(3)
                em1.metric("ราคา/ชิ้น", f"{float(e_sel_prod['price']):,.0f} บาท")
                em2.metric("ยอดรวม", f"{e_total:,.0f} บาท")
                em3.metric("PV รวม", f"{e_total_pts:.0f}")

                es1, es2, es3 = st.columns(3)
                with es1:
                    e_bill = st.radio("สถานะบิล", ["เปิดบิลแล้ว", "ยังไม่เปิดบิล"], index=cur_bill_idx, horizontal=True)
                with es2:
                    e_pay = st.radio("สถานะจ่าย", ["จ่ายแล้ว", "ค้างจ่าย"], index=cur_pay_idx, horizontal=True)
                with es3:
                    e_receipt = st.radio("สถานะของ", ["รับของแล้ว", "ฝากของ"], index=cur_receipt_idx, horizontal=True)

                ed1, ed2 = st.columns([3, 1])
                with ed1:
                    e_notes = st.text_input("หมายเหตุ", value=et.get("notes") or "")
                with ed2:
                    e_date = st.date_input("วันที่", value=pd.to_datetime(et["date"]).date())

                if edit_balance["total_received"] > 0 or edit_balance["total_paid"] > 0:
                    st.warning(
                        f"⚠️ รายการนี้มีการรับของ/จ่ายเงินไปแล้ว "
                        f"({edit_balance['total_received']} ชิ้น / {edit_balance['total_paid']:,.0f} บาท) "
                        f"— แก้จำนวนหรือราคาอาจทำให้ยอดไม่ตรง"
                    )

                if st.form_submit_button("💾 บันทึกการแก้ไข", use_container_width=True, type="primary"):
                    e_receive_now = e_receipt == "รับของแล้ว"
                    e_initial_qty = int(e_qty) if e_receive_now else 0
                    e_txn_type = "เบิกของก่อน" if e_bill == "ยังไม่เปิดบิล" and e_receive_now else "ขายปกติ"
                    db.update_transaction(edit_txn_id, {
                        "date": str(e_date),
                        "customer_id": customer_map_e[e_customer]["id"],
                        "product_id": e_sel_prod["id"],
                        "product_name": e_sel_prod["name"],
                        "qty": int(e_qty),
                        "price_per_unit": float(e_sel_prod["price"]),
                        "points_per_unit": float(e_sel_prod["points_per_unit"]),
                        "total_amount": e_total,
                        "initial_qty_received": e_initial_qty,
                        "transaction_type": e_txn_type,
                        "bill_status": e_bill,
                        "pay_status": e_pay,
                        "notes": e_notes,
                    })
                    st.success("✅ แก้ไขแล้ว")
                    st.rerun()

        # ── ลบที่เคลียร์แล้วทั้งหมด ──────────────────────────────────────────
        cleared_ids = all_df[all_df["เคลียร์แล้ว"]]["id"].tolist()
        if cleared_ids:
            st.divider()
            bc1, bc2 = st.columns([3, 1])
            bc1.caption(f"มี {len(cleared_ids)} รายการที่เคลียร์แล้ว (จ่ายและรับครบ)")
            h_confirm_bulk = bc1.checkbox(f"ยืนยันลบทั้งหมดที่เคลียร์แล้ว", key="hist_bulk_chk")
            if bc2.button(f"🗑️ ลบเคลียร์แล้วทั้งหมด ({len(cleared_ids)})",
                          disabled=not h_confirm_bulk, use_container_width=True, key="hist_del_bulk"):
                for tid in cleared_ids:
                    db.delete_transaction(tid)
                st.success(f"✅ ลบ {len(cleared_ids)} รายการแล้ว")
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Tab 6: สต๊อก
# ─────────────────────────────────────────────────────────────────────────────
with tab6:
    st.subheader("สรุปสต๊อก")

    products = db.get_products()
    if not products:
        st.warning("⚠️ ยังไม่มีข้อมูลสินค้า")
    else:
        latest_counts   = db.get_latest_stock_counts()
        unbilled_qty    = db.get_unbilled_received_qty_by_product()
        billed_not_rcv  = db.get_billed_not_received_qty_by_product()

        # เก็บ product_ids แยก เพื่อใช้ตอน save (ไม่พึ่ง hidden column)
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
                "สินค้า":   p["name"],
                "คอม":      qty_system,
                "นับจริง":  qty_physical,
                "เบิก":     qty_unbilled,
                "ฝาก":      qty_billed_wait,
                "ส่วนต่าง": diff,
                "สถานะ":   "🔴 เกิน" if diff > 0 else ("🟡 ขาด" if diff < 0 else "✅ ตรง"),
            })

        stock_df = pd.DataFrame(stock_rows)
        cnt_date = st.date_input("วันที่นับ", value=date.today(), key="stock_cnt_date")

        edited_stock = st.data_editor(
            stock_df,
            use_container_width=True,
            hide_index=True,
            disabled=["สินค้า", "เบิก", "ฝาก", "ส่วนต่าง", "สถานะ"],
            column_config={
                "คอม":      st.column_config.NumberColumn("คอม",     min_value=0, step=1, format="%d"),
                "นับจริง":  st.column_config.NumberColumn("นับจริง", min_value=0, step=1, format="%d"),
                "เบิก":     st.column_config.NumberColumn("เบิก",    format="%d"),
                "ฝาก":      st.column_config.NumberColumn("ฝาก",     format="%d"),
                "ส่วนต่าง": st.column_config.NumberColumn("ส่วนต่าง", format="%d"),
            },
            key="stock_editor",
        )
        # ── สรุปยอดรวม ──────────────────────────────────────────────────────
        price_by_name = {p["name"]: float(p.get("price") or 0) for p in products}
        pv_by_name    = {p["name"]: float(p.get("points_per_unit") or 0) for p in products}
        total_kom_amt  = sum(int(row["คอม"])     * price_by_name.get(row["สินค้า"], 0) for _, row in stock_df.iterrows())
        total_real_amt = sum(int(row["นับจริง"]) * price_by_name.get(row["สินค้า"], 0) for _, row in stock_df.iterrows())
        total_pv       = sum(int(row["ส่วนต่าง"]) * pv_by_name.get(row["สินค้า"], 0)   for _, row in stock_df.iterrows())
        diff_amt       = total_kom_amt - total_real_amt
        sm1, sm2, sm3, sm4 = st.columns(4)
        sm1.metric("📦 ยอดในคอม (฿)", f"{total_kom_amt:,.0f}")
        sm2.metric("🔍 ยอดจริง (฿)",  f"{total_real_amt:,.0f}")
        sm3.metric("⚖️ ส่วนต่าง (฿)", f"{diff_amt:,.0f}", delta=f"{diff_amt:,.0f}" if diff_amt != 0 else None)
        sm4.metric("⭐ คะแนนที่คีย์ได้", f"{total_pv:,.0f} PV")
        st.divider()

        st.caption("เบิก = เบิกของไปยังไม่มีบิล  |  ฝาก = เปิดบิลแล้วยังไม่รับของ  |  ส่วนต่าง = คอม − นับจริง + ฝาก − เบิก  |  ส่วนต่างอัปเดตหลังกด บันทึก")

        if st.button("💾 บันทึกการนับสต๊อก", use_container_width=True, type="primary", key="save_stock"):
            saved = 0
            errors = []
            debug_lines = []
            for pid, (_, row) in zip(product_ids, edited_stock.iterrows()):
                new_sys  = int(row["คอม"])     if pd.notna(row["คอม"])     else 0
                new_phys = int(row["นับจริง"]) if pd.notna(row["นับจริง"]) else 0
                debug_lines.append(f"{row['สินค้า']}: คอม={new_sys}, นับจริง={new_phys}, pid={pid}")
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


# ─────────────────────────────────────────────────────────────────────────────
# Tab 7: พิมพ์บิล
# ─────────────────────────────────────────────────────────────────────────────
with tab7:
    st.subheader("พิมพ์บิล")

    customers_p = db.get_customers()
    if not customers_p:
        st.info("ยังไม่มีข้อมูลลูกค้า")
    else:
        cust_map_p = {c["name"]: c for c in customers_p}

        _p_q = st.text_input("🔍 ชื่อลูกค้า หรือ เลขที่บิล",
                              placeholder="เช่น KONAING  หรือ  260427-001",
                              key="print_search")
        _is_bill = bool(re.match(r'\d{6}-\d+', (_p_q or "").strip()))

        if _is_bill:
            _sel_bill_no = _p_q.strip()
            sel_p = "—"
        else:
            _sel_bill_no = None
            _p_picked = st.session_state.get("_print_cust_picked", "")
            if _p_q.strip() and not _p_picked:
                # ล้าง picked ถ้า user เริ่มพิมพ์ใหม่
                pass
            if _p_picked and not _p_q.strip():
                # ล้าง picked ถ้า user ลบ search
                st.session_state.pop("_print_cust_picked", None)
                _p_picked = ""
            if _p_picked:
                _ppx, _ppy = st.columns([5, 1])
                _ppx.markdown(f"👤 **{_p_picked}**")
                if _ppy.button("✕", key="print_cust_clear"):
                    st.session_state.pop("_print_cust_picked", None)
                    st.rerun()
                sel_p = _p_picked
            else:
                sel_p = "— เลือก —"
                if _p_q.strip():
                    _p_matches = [n for n in cust_map_p if _p_q.strip().upper() in n.upper()][:8]
                    for _pm in _p_matches:
                        if st.button(f"👤 {_pm}", key=f"pp_{_pm}", use_container_width=True):
                            st.session_state["_print_cust_picked"] = _pm
                            st.rerun()

        filter_p = "ทั้งหมด"
        date_from_p = date_to_p = None

        _ready = _is_bill or sel_p != "— เลือก —"

        if _ready:
            if _is_bill:
                all_df_p = db.get_all_transactions_df(bill_no=_sel_bill_no)
                sel_p    = all_df_p["ลูกค้า"].iloc[0] if not all_df_p.empty else "—"
            else:
                customer_p  = cust_map_p[sel_p]
                all_df_p    = db.get_all_transactions_df(customer_id=customer_p["id"])

            if all_df_p.empty:
                st.info("ไม่มีรายการ")
            else:
                show_p = all_df_p[~all_df_p["เคลียร์แล้ว"]].copy() if filter_p == "ค้างอยู่" else all_df_p.copy()

                if date_from_p or date_to_p:
                    _dates = pd.to_datetime(show_p["วันที่"], dayfirst=True, errors="coerce").dt.date
                    if date_from_p:
                        show_p = show_p[_dates >= date_from_p]
                    if date_to_p:
                        show_p = show_p[_dates <= date_to_p]

                if show_p.empty:
                    st.success(f"✅ {sel_p} ไม่มียอดค้าง")
                else:
                    rows_html = ""
                    for _, r in show_p.iterrows():
                        bill_color  = "#b8860b" if r["สถานะบิล"] == "ยังไม่เปิดบิล" else "#1a7a3a"
                        owed_color  = "#c0392b" if r["ค้างจ่าย"] > 0.01 else "#1a7a3a"
                        rows_html += f"""
                        <tr>
                          <td>{r['วันที่']}</td>
                          <td style="font-size:11px;color:#666">{r.get('รหัส','')}</td>
                          <td>{r['สินค้า']}</td>
                          <td style="text-align:center">{int(r['สั่ง'])}</td>
                          <td style="text-align:center">{int(r['รับแล้ว'])}</td>
                          <td style="text-align:right">{r['ยอดรวม']:,.0f}</td>
                          <td style="text-align:right">{r['จ่ายแล้ว']:,.0f}</td>
                          <td style="text-align:right;color:{owed_color};font-weight:600">{r['ค้างจ่าย']:,.0f}</td>
                          <td style="text-align:center;color:{bill_color}">{r['สถานะบิล']}</td>
                          <td>{_fmt_note(r.get('หมายเหตุ','') or '')}</td>
                        </tr>"""

                    total_amount      = show_p["ยอดรวม"].sum()
                    total_paid        = show_p["จ่ายแล้ว"].sum()
                    total_outstanding = show_p["ค้างจ่าย"].sum()
                    total_pv          = show_p["PV รวม"].sum() if "PV รวม" in show_p.columns else 0
                    unbilled_pv       = show_p.loc[show_p["สถานะบิล"] == "ยังไม่เปิดบิล", "PV รวม"].sum() if "PV รวม" in show_p.columns else 0
                    today_str         = date.today().strftime("%d/%m/%Y")
                    filter_label      = "รายการค้างอยู่" if filter_p == "ค้างอยู่" else "รายการทั้งหมด"
                    bill_nos          = show_p["เลขที่บิล"].dropna().unique().tolist() if "เลขที่บิล" in show_p.columns else []
                    bill_nos_str      = ", ".join(b for b in bill_nos if b) or ""

                    # ตรวจสอบว่ามี tag ส่งพัสดุจาก notes ของรายการแรก
                    first_note = str(show_p.iloc[0].get("หมายเหตุ", "") or "")
                    is_ship_bill = "[ส่งพัสดุ|" in first_note
                    ship_weight_str, ship_fee_str, ship_remote = "", "", False
                    ship_carrier = ship_postcode = ship_weight_str = ship_fee_str = ship_remote = ""
                    if is_ship_bill:
                        import re as _re
                        _m = _re.search(
                            r"\[ส่งพัสดุ\|([^|]+)?\|?(\d{5})?\|?น้ำหนัก=([\d.]+)kg\|ค่าส่ง=(\d+)([^\]]*)\]",
                            first_note
                        )
                        if _m:
                            ship_carrier    = _m.group(1) or ""
                            ship_postcode   = _m.group(2) or ""
                            ship_weight_str = _m.group(3) or ""
                            ship_fee_str    = _m.group(4) or ""
                            ship_remote     = _m.group(5).strip("|") if _m.group(5) else ""

                    bm1, bm2 = st.columns(2)
                    bm1.metric("💸 ยอดค้างจ่ายรวม",  f"{total_outstanding:,.0f} บาท")
                    bm2.metric("⭐ PV ยังไม่เปิดบิล", f"{unbilled_pv:,.0f}")

                    _print_copies = st.radio("จำนวนชุด", ["1 ชุด", "2 ชุด (ลูกค้า + ร้าน)"],
                                             horizontal=True, key="print_copies")

                    _ship_row_html = (
                        f"<tr><td>⚖️ น้ำหนัก {ship_weight_str} kg &nbsp; 🚚 ค่าส่ง</td>"
                        f"<td><b style='color:#1a5c8e'>{ship_fee_str} บาท</b></td></tr>"
                    ) if is_ship_bill and ship_fee_str else ""

                    def _bill_body(label: str) -> str:
                        _lbl = f"<div style='font-size:11px;color:#888;margin-bottom:4px'>{label}</div>" if label else ""
                        return f"""{_lbl}
<div class="header" style="display:flex;justify-content:space-between;align-items:flex-start">
  <div>
    <h1>ใบรับสินค้า ZHULIAN TBY</h1>
    <h2>ลูกค้า: {sel_p}{"&nbsp;&nbsp;🚚 ส่งพัสดุ" if is_ship_bill else ""}</h2>
  </div>
  <div style="text-align:right">
    <div style="font-size:14px;font-weight:600">เลขที่บิล: {bill_nos_str if bill_nos_str else "—"}</div>
    <div class="info" style="margin-top:4px">วันที่พิมพ์: {today_str}</div>
    <div class="info">{filter_label} ({len(show_p)} รายการ)</div>
  </div>
</div>
<table>
  <thead><tr>
    <th>วันที่</th><th>รหัส</th><th>สินค้า</th>
    <th style="text-align:center">สั่ง</th><th style="text-align:center">รับแล้ว</th>
    <th style="text-align:right">ยอดรวม</th><th style="text-align:right">จ่ายแล้ว</th>
    <th style="text-align:right">ค้างจ่าย</th><th style="text-align:center">สถานะบิล</th>
    <th>หมายเหตุ</th>
  </tr></thead>
  <tbody>{rows_html}</tbody>
</table>
<div class="summary">
  <table>
    <tr><td>ยอดสินค้า</td><td><b>{total_amount:,.0f} บาท</b></td></tr>
    {_ship_row_html}
    <tr><td>ยอดรวม (รวมค่าส่ง)</td><td><b>{total_amount + int(ship_fee_str or 0):,.0f} บาท</b></td></tr>
    <tr><td>จ่ายแล้ว</td><td><b style="color:#1a7a3a">{total_paid:,.0f} บาท</b></td></tr>
    <tr class="big"><td>ค้างจ่าย</td><td><b style="color:#c0392b">{total_outstanding:,.0f} บาท</b></td></tr>
    <tr><td>⭐ PV รวม</td><td><b style="color:#b8860b">{total_pv:.0f}</b></td></tr>
  </table>
</div>"""

                    _css = """
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Sarabun',sans-serif;padding:16px;color:#111;background:#fff;font-size:12px}
  .header{border-bottom:2px solid #000;padding-bottom:8px;margin-bottom:12px}
  .header h1{font-size:15px;font-weight:700}
  .header h2{font-size:13px;font-weight:600;margin-top:2px}
  .info{color:#444;font-size:10px;margin-top:2px}
  table{width:100%;border-collapse:collapse;margin-top:5px;border:1px solid #000}
  th{background:#000;color:#fff;padding:5px 6px;text-align:left;font-size:11px;border:1px solid #000}
  td{padding:4px 6px;border:1px solid #aaa;font-size:11px}
  tr:nth-child(even) td{background:#f0f0f0}
  .summary{margin-top:12px;border-top:2px solid #000;padding-top:8px;text-align:right}
  .summary table{width:auto;margin-left:auto;border:none}
  .summary td{padding:2px 8px;border:none;font-size:12px}
  .big td{font-weight:900;font-size:14px;border-top:2px solid #000;padding-top:5px}
  .two-col{display:flex;gap:0;height:100%}
  .copy{width:50%;padding:16px;min-height:400px}
  .vcut{width:2px;background:repeating-linear-gradient(to bottom,#aaa 0,#aaa 6px,transparent 6px,transparent 12px);flex-shrink:0}
  .copy-lbl{font-size:10px;color:#999;margin-bottom:4px;font-style:italic}
  .btn{display:block;margin:0 auto 14px;padding:7px 28px;background:#c0392b;color:#fff;
       border:none;border-radius:6px;font-size:13px;cursor:pointer}
  @media print{
    .btn{display:none}
    @page{size:A4 landscape;margin:8mm}
    *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
    body{color:#000!important;font-size:11px}
    th{background:#000!important;color:#fff!important;border:1px solid #000}
    td{border-bottom:1px solid #999!important;color:#000!important}
    tr:nth-child(even) td{background:#eee!important}
    .info{color:#333!important}
    .copy-lbl{color:#333!important}
    .vcut{background:repeating-linear-gradient(to bottom,#000 0,#000 4px,transparent 4px,transparent 8px)!important}
    b[style],span[style],[style*="color"]{color:#000!important}
    .summary .big td{font-weight:900}
  }"""

                    if _print_copies == "2 ชุด (ลูกค้า + ร้าน)":
                        _body = f"""<div class="two-col">
  <div class="copy">{_bill_body("สำหรับลูกค้า")}</div>
  <div class="vcut"></div>
  <div class="copy">{_bill_body("สำหรับร้าน")}</div>
</div>"""
                        _height = 750
                    else:
                        _body = _bill_body("")
                        _height = 700

                    bill_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{_css}</style></head><body>
<button class="btn" onclick="window.print()">🖨️ พิมพ์</button>
{_body}
<br><button class="btn" onclick="window.print()">🖨️ พิมพ์</button>
</body></html>"""

                    components.html(bill_html, height=_height, scrolling=True)


# ─────────────────────────────────────────────────────────────────────────────
# Tab E-commerce: Shopee API sync
# ─────────────────────────────────────────────────────────────────────────────
with tab_ecom:
    st.subheader("🛒 E-commerce — Shopee")

    if not shopee_api.is_configured():
        st.warning("⚙️ ยังไม่ได้ตั้งค่า Shopee Partner ID/Key — กรอกใน `.streamlit/secrets.toml` ก่อนครับ")
        st.code('SHOPEE_PARTNER_ID = "12345"\nSHOPEE_PARTNER_KEY = "xxxxx"', language="toml")
    else:
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
            import datetime as _dt
            shop_options = {s["shop_name"]: s for s in shops}
            sel_shops = st.multiselect("เลือกร้าน", list(shop_options.keys()), default=list(shop_options.keys()), key="ecom_shops_sel")
            sc1, sc2 = st.columns(2)
            sync_from = sc1.date_input("วันที่เริ่ม", value=date.today().replace(day=1), key="sync_from")
            sync_to   = sc2.date_input("ถึง", value=date.today(), key="sync_to")

            if st.button("🔄 Sync Orders", type="primary", use_container_width=True, key="ecom_sync"):
                prod_map  = db.get_ecommerce_product_map()
                new_items  = []
                new_unmapped = []
                from_ts = int(_dt.datetime.combine(sync_from, _dt.time.min).timestamp())
                to_ts   = int(_dt.datetime.combine(sync_to,   _dt.time.max).timestamp())

                for shop_name in sel_shops:
                    shop = shop_options[shop_name]
                    with st.spinner(f"ดึง {shop_name}..."):
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
                            continue
                        order_sns = [o["order_sn"] for o in orders]
                        details   = shopee_api.get_order_details(shop["shop_id"], shop["access_token"], order_sns)

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

                if new_items:
                    db.insert_ecommerce_sales(new_items)
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


# ─────────────────────────────────────────────────────────────────────────────
# Tab การเงิน: บันทึกยอดรายวัน + วงเงินสั่งของ
# ─────────────────────────────────────────────────────────────────────────────
with tab_fin:
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
