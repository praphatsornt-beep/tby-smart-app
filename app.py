import re
import streamlit as st
import pandas as pd

import database as db
import carriers as carr
import thai_address
import shopee_api
import line_api
import iship_api
import ecom_ui
import fin_ui
import dashboard_ui
import stock_ui
import master_data_ui
import record_ui
import bill_detail_ui
from ui_helpers import _extract_tracking, _extract_iship_order_id, _build_success_info

thai_address._load_db()  # pre-warm cache

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

st.markdown("""
<style>
/* ===== TBY SMART APP — THEME: FOREST GREEN + ORANGE ===== */

/* ── App header bar ── */
header[data-testid="stHeader"] {
    background: linear-gradient(90deg, #1B4332 0%, #2D6A4F 100%);
    box-shadow: 0 2px 8px rgba(27,67,50,0.25);
}

/* ── Page title ── */
h1 {
    color: #1B4332 !important;
    font-weight: 800 !important;
    letter-spacing: -0.5px;
    padding-bottom: 0.4rem;
    border-bottom: 3px solid #E07B39;
    margin-bottom: 1rem !important;
}
h2 { color: #2D6A4F !important; font-weight: 700 !important; }
h3 { color: #2D6A4F !important; font-weight: 600 !important; }

/* ── Main nav (st.pills) — looks identical to underline tabs ── */
[data-testid="stPills"] {
    background: #ffffff;
    border-bottom: 2px solid #D4E8DA;
    border-radius: 12px 12px 0 0;
    padding: 4px 8px 0;
    box-shadow: 0 2px 12px rgba(27,67,50,0.07);
    display: flex;
    flex-wrap: wrap;
    gap: 0;
    margin-bottom: 0 !important;
}
[data-testid="stPills"] button {
    background: transparent !important;
    color: #7A9E85 !important;
    border: none !important;
    border-radius: 8px 8px 0 0 !important;
    border-bottom: 3px solid transparent !important;
    font-size: 0.84rem !important;
    font-weight: 500 !important;
    padding: 8px 13px !important;
    margin-bottom: -2px;
    white-space: nowrap;
    box-shadow: none !important;
    transition: color 0.2s, background 0.2s !important;
}
[data-testid="stPills"] button[aria-checked="true"] {
    color: #1B4332 !important;
    font-weight: 700 !important;
    background: transparent !important;
    border-bottom: 3px solid #E07B39 !important;
    box-shadow: none !important;
}
[data-testid="stPills"] button:hover {
    color: #1B4332 !important;
    background: #F0F9F4 !important;
    border-bottom: 3px solid transparent !important;
}

/* ── Sub-tabs inside each page (st.tabs) — modern underline ── */
.stTabs [data-baseweb="tab-list"] {
    background: #ffffff;
    border-bottom: 2px solid #D4E8DA;
    border-radius: 12px 12px 0 0;
    padding: 0 6px;
    gap: 0;
    box-shadow: 0 2px 12px rgba(27,67,50,0.07);
}
.stTabs [data-baseweb="tab"] {
    color: #7A9E85 !important;
    background: transparent !important;
    border-radius: 8px 8px 0 0 !important;
    font-weight: 500;
    font-size: 0.85rem;
    padding: 10px 15px !important;
    border: none !important;
    transition: color 0.2s, background 0.2s;
    white-space: nowrap;
}
.stTabs [data-baseweb="tab"]:hover {
    color: #1B4332 !important;
    background: #F0F9F4 !important;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    color: #1B4332 !important;
    font-weight: 700 !important;
    background: transparent !important;
}
/* Animated orange underline indicator */
.stTabs [data-baseweb="tab-highlight"] {
    background-color: #E07B39 !important;
    height: 3px !important;
    border-radius: 3px 3px 0 0;
}
.stTabs [data-baseweb="tab-border"] { display: none !important; }

/* ── Primary buttons (orange) ── */
button[data-testid="baseButton-primary"] {
    background: linear-gradient(135deg, #E07B39 0%, #C86A2A 100%) !important;
    color: #fff !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    box-shadow: 0 2px 8px rgba(224,123,57,0.35) !important;
    transition: box-shadow 0.18s, transform 0.18s !important;
}
button[data-testid="baseButton-primary"]:hover {
    box-shadow: 0 4px 16px rgba(224,123,57,0.5) !important;
    transform: translateY(-1px) !important;
}
button[data-testid="baseButton-primary"]:active {
    transform: translateY(0) !important;
    box-shadow: 0 2px 6px rgba(224,123,57,0.3) !important;
}

/* ── Secondary buttons (green outline) ── */
button[data-testid="baseButton-secondary"] {
    border: 1.5px solid #2D6A4F !important;
    color: #2D6A4F !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
    background: white !important;
    transition: all 0.18s !important;
}
button[data-testid="baseButton-secondary"]:hover {
    background: #EAF2EC !important;
    border-color: #1B4332 !important;
    color: #1B4332 !important;
}

/* ── Metrics ── */
[data-testid="stMetric"] {
    background: white;
    border-radius: 12px;
    padding: 1rem 1.25rem !important;
    border-left: 4px solid #E07B39;
    box-shadow: 0 2px 10px rgba(27,67,50,0.08);
}
[data-testid="stMetricValue"] {
    font-size: 1.5rem !important;
    font-weight: 700 !important;
    color: #1B4332 !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    color: #2D6A4F !important;
    text-transform: uppercase;
    letter-spacing: 0.4px;
}

/* ── Expanders ── */
[data-testid="stExpander"] {
    border: 1px solid #C8DDD0 !important;
    border-radius: 10px !important;
    overflow: hidden;
    box-shadow: 0 1px 5px rgba(0,0,0,0.05);
}
[data-testid="stExpander"] summary {
    background: #EAF2EC !important;
    color: #1B4332 !important;
    font-weight: 600 !important;
    padding: 0.55rem 1rem !important;
}
[data-testid="stExpander"] summary:hover {
    background: #D8F3DC !important;
}

/* ── Text/Number inputs ── */
.stTextInput input,
.stNumberInput input,
.stTextArea textarea {
    border-radius: 8px !important;
    border: 1.5px solid #C8DDD0 !important;
    transition: border-color 0.18s, box-shadow 0.18s !important;
}
.stTextInput input:focus,
.stNumberInput input:focus,
.stTextArea textarea:focus {
    border-color: #40916C !important;
    box-shadow: 0 0 0 3px rgba(64,145,108,0.18) !important;
}

/* ── Select boxes ── */
[data-baseweb="select"] > div:first-child {
    border-radius: 8px !important;
    border: 1.5px solid #C8DDD0 !important;
    transition: border-color 0.18s !important;
}
[data-baseweb="select"] > div:first-child:focus-within {
    border-color: #40916C !important;
    box-shadow: 0 0 0 3px rgba(64,145,108,0.18) !important;
}

/* ── DataFrame / Data editor ── */
[data-testid="stDataFrame"],
[data-testid="stDataEditor"] {
    border-radius: 10px !important;
    overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}

/* ── Block container padding ── */
.block-container {
    padding-top: 1.5rem !important;
}

/* ── Dividers ── */
hr {
    border-color: #C8DDD0 !important;
    margin: 0.75rem 0 !important;
}

/* ── Typography / Readability ── */
html { font-size: 15.5px; }

/* Body text & markdown */
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stText"] p {
    font-size: 0.95rem !important;
    line-height: 1.7 !important;
    color: #111111 !important;
}

/* Widget labels */
label,
[data-testid="stWidgetLabel"] p {
    font-size: 0.88rem !important;
    font-weight: 600 !important;
    color: #111111 !important;
    letter-spacing: 0.01em;
    line-height: 1.5 !important;
}

/* Input / textarea text */
.stTextInput input,
.stNumberInput input,
.stTextArea textarea {
    font-size: 0.95rem !important;
    color: #111111 !important;
}

/* Selectbox value text */
[data-baseweb="select"] span,
[data-baseweb="select"] div[class*="placeholder"] {
    font-size: 0.93rem !important;
    color: #111111 !important;
}

/* st.info / st.success / st.warning / st.error */
[data-testid="stAlert"] p {
    font-size: 0.9rem !important;
    line-height: 1.65 !important;
    color: #111111 !important;
}

/* Caption / small text */
[data-testid="stCaptionContainer"] p {
    font-size: 0.8rem !important;
    color: #555 !important;
    line-height: 1.6 !important;
}

/* Dataframe cells */
[data-testid="stDataFrame"] td,
[data-testid="stDataFrame"] th,
[data-testid="stDataEditor"] td,
[data-testid="stDataEditor"] th {
    font-size: 0.88rem !important;
    line-height: 1.5 !important;
}
</style>
""", unsafe_allow_html=True)

st.title("🛍️ TBY SMART APP")

@st.dialog("🚚 เลือกขนส่ง", width="large")
def _show_carrier_select():
    info = st.session_state.get("_iship_carrier_select", {})
    if not info:
        return
    tab       = info.get("tab", "ship")
    postcode  = info.get("postcode", "")
    weight_kg = info.get("weight_kg", 0.5)
    cod_amt   = float(info.get("cod_amount", 0))

    _old_track = st.session_state.pop("_change_carrier_old_track", None)
    if _old_track:
        st.warning(f"⚠️ กรุณายกเลิก tracking **{_old_track}** ใน iShip ด้วยตนเองก่อน แล้วค่อยส่งใหม่")

    if info.get("customer_name"):
        st.markdown(f"**ลูกค้า:** {info['customer_name']}")
    st.markdown(f"**ผู้รับ:** {info.get('dst_name','')}  {info.get('dst_phone','')}")
    st.caption(f"{info.get('address_line','')} {info.get('district','')} {info.get('amphure','')} {info.get('province','')} {postcode}")
    _items_disp = info.get("items", [])
    if _items_disp:
        st.markdown("**สินค้า:** " + "  ·  ".join(
            f"{it.get('name', it.get('product_name','?'))} ×{it.get('qty',0)}"
            for it in _items_disp
        ))
    st.caption(f"⚖️ {weight_kg:.2f} kg" + (f"  |  COD: {int(cod_amt):,} ฿" if cod_amt else ""))
    st.divider()

    opts     = carr.get_shipping_options(weight_kg, postcode, cod_amt > 0, cod_amt)
    opts_ok  = [o for o in opts if not o["exceeds_max"]]
    opts_exc = [o for o in opts if o["exceeds_max"]]

    if opts_ok:
        _cmp = []
        for _ci, o in enumerate(opts_ok):
            _sur_txt  = f"+{o['surcharge']} ({o['sur_label']})" if o["surcharge"] else "-"
            _fuel_txt = f"+{o['fuel']}" if o["fuel"] else "-"
            _cod_txt  = f"+{o['cod_fee']:,}" if o["cod_fee"] else "-"
            _size_txt = f"≤{o['max_cm']}cm" if o.get("max_cm") else "-"
            _cmp.append({"ขนส่ง": ("🥇 " if _ci == 0 else "") + o["name"],
                         "ค่าส่ง": o["base"], "พื้นที่พิเศษ": _sur_txt,
                         "น้ำมัน": _fuel_txt, "รวม (฿)": o["total"], "📐": _size_txt, "COD": _cod_txt})
        st.dataframe(pd.DataFrame(_cmp), hide_index=True, use_container_width=True,
                     column_config={"รวม (฿)": st.column_config.NumberColumn("รวม (฿)", format="%d ฿")})

        _cs_carrier = st.selectbox("เลือกขนส่ง", [o["name"] for o in opts_ok],
                                   index=0, key="_cs_carrier_sel")
        _cs_code    = iship_api.COURIER_MAP.get(_cs_carrier, "")
        _cs_sel_opt = next((o for o in opts_ok if o["name"] == _cs_carrier), {})
        _cs_total   = _cs_sel_opt.get("total", 0)
        _cs_max_cm  = _cs_sel_opt.get("max_cm", 0)
        st.caption(f"iShip code: `{_cs_code}` | ราคาจริง: {_cs_total:,} ฿")
        if _cs_max_cm:
            st.warning(f"📐 {_cs_carrier} — กว้าง+ยาว+สูง รวมไม่เกิน **{_cs_max_cm} cm** (ถึงกล่องเบอร์ {'2B' if _cs_max_cm <= 60 else 'G' if _cs_max_cm <= 100 else '?'})")
        if not _cs_code:
            st.warning(f"⚠️ ไม่พบ iShip code สำหรับ '{_cs_carrier}'")

        _cs_is_bulky = "Bulky" in _cs_carrier
        _cs_len = _cs_wid = _cs_hgt = 0
        if _cs_is_bulky:
            st.markdown("**📐 ขนาดกล่อง (จำเป็นสำหรับ Bulky)**")

            # ── preset กล่อง ──────────────────────────────────────────────
            _BULKY_DEFAULT = (
                "ผงเล็ก: 55×33×28\n"
                "ผงใหญ่: 40×45×23\n"
                "กาแฟใหญ่: 60×43×25\n"
                "pana: 23×35×16\n"
                "โปรตีน: 33×22×20\n"
                "สระผม: 24×30×20\n"
                "อาบน้ำ: 32×26×25\n"
                "XTRA: 30×42×26\n"
                "น้ำผลไม้: 44×28×29"
            )
            if "_bulky_presets_txt" not in st.session_state:
                st.session_state["_bulky_presets_txt"] = _BULKY_DEFAULT
            with st.expander("⚙️ ตั้งค่า preset กล่อง"):
                st.text_area(
                    "ชื่อ: ยาว×กว้าง×สูง — บรรทัดละ 1 ขนาด",
                    height=160, key="_bulky_presets_txt",
                )

            # parse
            _bulky_presets: list[dict] = []
            for _ln in st.session_state["_bulky_presets_txt"].splitlines():
                if ":" not in _ln:
                    continue
                _pn, _pd = _ln.split(":", 1)
                _pd_parts = re.split(r"[×xX*]", _pd.strip())
                if len(_pd_parts) == 3:
                    try:
                        _bulky_presets.append({
                            "name": _pn.strip(),
                            "l": int(_pd_parts[0]), "w": int(_pd_parts[1]), "h": int(_pd_parts[2]),
                        })
                    except ValueError:
                        pass

            # dropdown เลือกขนาด
            _preset_opts = ["-- เลือกขนาดกล่อง --"] + [p["name"] for p in _bulky_presets] + ["กรอกเอง"]
            _preset_sel  = st.selectbox("ขนาดกล่อง", _preset_opts, key="_cs_bulky_preset")
            _pm = next((p for p in _bulky_presets if p["name"] == _preset_sel), None)
            _def_l, _def_w, _def_h = (_pm["l"], _pm["w"], _pm["h"]) if _pm else (30, 30, 20)

            _b1, _b2, _b3 = st.columns(3)
            _cs_len = _b1.number_input("ยาว (cm)", 1, 300, _def_l, key=f"_cs_len_{_preset_sel}")
            _cs_wid = _b2.number_input("กว้าง (cm)", 1, 300, _def_w, key=f"_cs_wid_{_preset_sel}")
            _cs_hgt = _b3.number_input("สูง (cm)", 1, 300, _def_h, key=f"_cs_hgt_{_preset_sel}")

        st.divider()
        _btn1, _btn2, _btn3 = st.columns(3)
        if _btn3.button("⬅️ ย้อนกลับแก้ไข", use_container_width=True, key="_cs_back"):
            st.session_state.pop("_iship_carrier_select", None)
            st.rerun()
        if _btn1.button("📦 ส่ง iShip", type="primary", use_container_width=True, key="_cs_send"):
            _cs_items       = info.get("items", [])
            _cs_item_codes  = " ".join(
                f"{(it.get('product_id') or it.get('name','')).upper()}-{it.get('qty',0)}"
                for it in _cs_items if it.get('qty',0) > 0
            )
            _cs_item_detail = _cs_item_codes
            _cs_products    = [{"name": it.get("name",""), "qty": it.get("qty",0), "price": 0} for it in _cs_items]
            _cs_remark      = " ".join(filter(None, [info.get("customer_name",""), _cs_item_codes or info.get("remark","")])).strip()
            with st.spinner("กำลังสร้างรายการใน iShip..."):
                _cs_resp = iship_api.create_order(
                    dst_name     = info.get("dst_name", ""),
                    dst_phone    = info.get("dst_phone", ""),
                    address_line = info.get("address_line", ""),
                    district     = info.get("district", ""),
                    amphure      = info.get("amphure", ""),
                    province     = info.get("province", ""),
                    zipcode      = postcode,
                    weight_kg    = weight_kg,
                    cod_amount   = cod_amt,
                    carrier      = _cs_carrier,
                    remark       = _cs_remark,
                    item_detail  = _cs_item_detail,
                    products     = _cs_products,
                    length_cm    = int(_cs_len),
                    width_cm     = int(_cs_wid),
                    height_cm    = int(_cs_hgt),
                )
            if _cs_resp.get("status"):
                _cs_track    = _extract_tracking(_cs_resp)
                _cs_order_id = _extract_iship_order_id(_cs_resp)
                st.session_state["_iship_debug_resp"] = _cs_resp
                if tab == "ship" and info.get("shipment_id") and _cs_track:
                    db.update_shipment_tracking(info["shipment_id"], _cs_track)
                if tab in ("sale", "pending"):
                    try:
                        db.create_shipment({
                            "customer_id":    info.get("customer_id") or None,
                            "recipient_name": info.get("dst_name", ""),
                            "phone":          info.get("dst_phone", ""),
                            "address_line":   info.get("address_line", ""),
                            "district":       info.get("district", ""),
                            "amphure":        info.get("amphure", ""),
                            "province":       info.get("province", ""),
                            "postal_code":    postcode,
                            "carrier":        _cs_carrier,
                            "items":          info.get("items", []),
                            "tracking_no":    _cs_track,
                            "cod_amount":     int(cod_amt),
                            "notes":          "",
                            "source":         "sale",
                        })
                    except Exception as _cs_e:
                        st.warning(f"⚠️ ส่ง iShip สำเร็จ (tracking {_cs_track}) แต่บันทึกประวัติการส่งไม่สำเร็จ: {_cs_e}")
                _cs_luid, _cs_gid = db.get_customer_line_ids(info.get("customer_id","")) if info.get("customer_id") else ("", "")
                st.session_state["_iship_success_info"] = _build_success_info(
                    tracking=_cs_track, tab=tab,
                    customer=info.get("customer_name", ""),
                    dst_name=info.get("dst_name", ""),
                    dst_phone=info.get("dst_phone", ""),
                    address=f"{info.get('address_line','')} {info.get('district','')} {info.get('amphure','')} {info.get('province','')} {postcode}".strip(),
                    carrier=_cs_carrier, weight_kg=weight_kg,
                    cod_amount=int(cod_amt),
                    items=info.get("items", []),
                    line_user_id=_cs_luid,
                    shipment_id=info.get("shipment_id", ""),
                    group_id=_cs_gid,
                    iship_order_id=_cs_order_id,
                    _carrier_select_info=info,
                )
                st.session_state.pop("_iship_carrier_select", None)
                st.rerun()
            else:
                st.error(f"❌ {_cs_resp.get('message', str(_cs_resp))}")
                with st.expander("🔍 debug"):
                    st.json(_cs_resp)

        if _btn2.button("ข้าม (ไม่ส่ง iShip)", use_container_width=True, key="_cs_skip"):
            st.session_state.pop("_iship_carrier_select", None)
            st.session_state["_do_clear_after_iship"] = tab
            st.rerun()

        if opts_exc:
            with st.expander(f"⚠️ เกินน้ำหนักสูงสุด ({len(opts_exc)} ขนส่ง)"):
                for o in opts_exc:
                    st.caption(f"❌ {o['name']} รับได้สูงสุด {o['max_kg']} kg")
    else:
        st.warning("ไม่มีขนส่งที่รองรับน้ำหนักนี้")
        _bc1, _bc2 = st.columns(2)
        if _bc1.button("⬅️ ย้อนกลับแก้ไข", use_container_width=True, key="_cs_back2"):
            st.session_state.pop("_iship_carrier_select", None)
            st.rerun()
        if _bc2.button("ข้าม", use_container_width=True, key="_cs_close"):
            st.session_state.pop("_iship_carrier_select", None)
            st.session_state["_do_clear_after_iship"] = tab
            st.rerun()


@st.dialog("✅ ส่ง iShip สำเร็จ", width="large")
def _show_iship_success_dialog():
    info = st.session_state.get("_iship_success_info", {})
    st.success(f"🚚 Tracking: **{info.get('tracking', '')}**")
    c1, c2 = st.columns(2)
    if info.get("customer"):
        c1.markdown(f"**ลูกค้า:** {info['customer']}")
    c1.markdown(f"**ผู้รับ:** {info.get('dst_name','')}  {info.get('dst_phone','')}")
    c1.markdown(f"**ที่อยู่:** {info.get('address','')}")
    c2.markdown(f"**ขนส่ง:** {info.get('carrier','')}")
    c2.markdown(f"**น้ำหนัก:** {info.get('weight_kg',0):.2f} kg  |  COD: {info.get('cod_amount',0):,} ฿")
    if info.get("items"):
        st.markdown("**รายการ:**  " + "  ·  ".join(
            f"{it.get('name','')} ×{it.get('qty',0)}" for it in info["items"]
        ))
    st.divider()
    _track = info.get("tracking", "")
    _iship_oid = info.get("iship_order_id", "")
    if _track:
        if _iship_oid:
            _print_url = f"https://app.iship.cloud/print/a6?order={_iship_oid}"
            st.link_button("🖨️ ปริ้นใบปะหน้า", _print_url, use_container_width=True)
        elif iship_api.is_configured():
            if st.button("🖨️ ปริ้นใบปะหน้า", use_container_width=True):
                with st.spinner("กำลังหา order ID..."):
                    _label = iship_api.get_label_url(_track)
                if _label.get("url"):
                    st.link_button("🔗 เปิดหน้าปริ้น", _label["url"], use_container_width=True)
                else:
                    st.warning(f"⚠️ {_label.get('error','')}")
        _dbg_resp = st.session_state.get("_iship_debug_resp")
        if _dbg_resp:
            with st.expander("🔍 iShip response (หา order_id)"):
                st.json(_dbg_resp)

    _dluid = info.get("line_user_id", "")
    _dlgid = info.get("group_id", "")
    if _dluid and line_api.is_configured():
        if st.button("📨 ส่งแจ้งลูกค้าทาง LINE", use_container_width=True):
            _dlr = line_api.push_tracking(
                _dluid,
                info.get("dst_name", ""),
                info.get("tracking", ""),
                info.get("carrier", ""),
                float(info.get("cod_amount", 0)),
                group_id=_dlgid,
            )
            if _dlr.get("ok"):
                st.success("✅ ส่ง LINE แล้ว")
                if info.get("shipment_id"):
                    db.mark_line_notified(info["shipment_id"])
            else:
                st.error(f"❌ {_dlr.get('error','')}")
    if st.button("✅ ตกลง / เริ่มออเดอร์ใหม่", type="primary", use_container_width=True):
        _tab = info.get("tab", "sale")
        st.session_state.pop("_iship_success_info", None)
        st.session_state["_do_clear_after_iship"] = _tab
        st.rerun()


# ── clean up stale iShip keys จาก version ก่อนหน้า ──────────────────────────
for _stale in ("_iship_pending", "_sp_iship_pending"):
    st.session_state.pop(_stale, None)

# carrier select: persistent (ต้องเรียกทุก rerun เพื่อให้ interactive widget ทำงานได้)
if st.session_state.get("_iship_carrier_select"):
    _show_carrier_select()
# success dialog: คงอยู่จนกว่าจะกดปิด (มีปุ่ม LINE ข้างใน)
if st.session_state.get("_iship_success_info"):
    _show_iship_success_dialog()


# ── Lazy tab navigation ──────────────────────────────────────────────────────
_TAB_NAMES = [
    "🏠 หน้าแรก", "📋 บันทึกรายการ", "🗂️ รายละเอียดบิล",
    "📦 สต๊อก", "💵 การเงิน", "🛒 E-commerce", "⚙️ จัดการข้อมูล",
]
if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = _TAB_NAMES[0]

try:
    # st.pills (Streamlit ≥ 1.36) — looks like tabs, single-select
    _active_tab = st.pills(
        "เมนู", _TAB_NAMES,
        key="active_tab",
        label_visibility="collapsed",
    ) or _TAB_NAMES[0]
except AttributeError:
    _active_tab = st.radio(
        "เมนู", _TAB_NAMES,
        horizontal=True,
        key="active_tab",
        label_visibility="collapsed",
    )

_products = db.get_products()
_customers = db.get_customers()

# ── Render only the active tab — ไม่รัน render() ของแท็บอื่น ─────────────────
if _active_tab == _TAB_NAMES[0]:
    dashboard_ui.render()
elif _active_tab == _TAB_NAMES[1]:
    record_ui.render(st.container(), _products, _customers, {c["name"]: c for c in _customers})
elif _active_tab == _TAB_NAMES[2]:
    bill_detail_ui.render(st.container(), _products, _customers)
elif _active_tab == _TAB_NAMES[3]:
    stock_ui.render()
elif _active_tab == _TAB_NAMES[4]:
    fin_ui.render()
elif _active_tab == _TAB_NAMES[5]:
    ecom_ui.render()
elif _active_tab == _TAB_NAMES[6]:
    master_data_ui.render()
