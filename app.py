from datetime import date

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
from ui_helpers import _extract_tracking, _extract_iship_order_id, _build_success_info, get_bulky_presets

thai_address._load_db()  # pre-warm cache

st.set_page_config(page_title="TBY SMART APP", page_icon="🛍️", layout="wide")

# ── Shopee OAuth callback ────────────────────────────────────────────────────
_qp = st.query_params
if "code" in _qp and "shop_id" in _qp:
    _code    = _qp["code"]
    _shop_id = int(_qp["shop_id"])
    _cb_state      = _qp.get("state", "")
    _expected_state = st.session_state.get("_shopee_oauth_state", "")
    if _expected_state and _cb_state != _expected_state:
        st.error("❌ OAuth state ไม่ตรง — request อาจถูก CSRF โจมตี กรุณาลองใหม่")
    else:
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
                st.session_state.pop("_shopee_oauth_state", None)
                st.success(f"✅ เชื่อมต่อร้าน shop_id={_shop_id} สำเร็จ")
            else:
                st.error(f"❌ ได้รับ code แต่ token ผิดพลาด: {_tok.get('message','')}")
        except Exception as _e:
            st.error(f"❌ OAuth error: {_e}")
    st.query_params.clear()

st.markdown(
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link href="https://fonts.googleapis.com/css2?family=Kanit:wght@500;600;700&family=Sarabun:wght@400;500;600;700&display=swap" rel="stylesheet">',
    unsafe_allow_html=True,
)

st.markdown("""
<style>
/* ===== TBY SMART APP — design system ported from the "Back Office App"
   reference mockup: oklch palette, Kanit (headings/numbers) + Sarabun
   (body) fonts, flat bordered cards (no drop shadows), pill badges. ===== */
:root {
    --tby-bg:            oklch(0.975 0.012 95);
    --tby-text:          oklch(0.24 0.02 155);
    --tby-sidebar-1:     oklch(0.30 0.06 155);
    --tby-sidebar-2:     oklch(0.20 0.045 160);
    --tby-sidebar-inact: oklch(0.88 0.02 155);
    --tby-sidebar-cap:   oklch(0.85 0.02 155);
    --tby-accent:        oklch(0.68 0.17 45);
    --tby-accent-hover:  oklch(0.60 0.17 45);
    --tby-green:         oklch(0.55 0.13 155);
    --tby-green-dark:    oklch(0.4 0.1 155);
    --tby-border:        oklch(0.93 0.012 100);
    --tby-row-border:    oklch(0.96 0.008 100);
    --tby-table-head-bg: oklch(0.98 0.008 100);
    --tby-input-border:  oklch(0.88 0.012 100);
    --tby-muted:         oklch(0.55 0.02 150);
    --tby-muted2:        oklch(0.5 0.02 150);
    --tby-badge-good-bg: oklch(0.94 0.03 155);
    --tby-badge-good-fg: oklch(0.4 0.1 155);
    --tby-badge-warn-bg: oklch(0.94 0.04 55);
    --tby-badge-warn-fg: oklch(0.5 0.14 50);
    --tby-badge-bad-bg:  oklch(0.94 0.03 25);
    --tby-badge-bad-fg:  oklch(0.5 0.15 25);
}

/* ── App canvas ── */
.stApp {
    background: var(--tby-bg);
    font-family: 'Sarabun', sans-serif;
}

/* ── Streamlit's own header bar — transparent so it doesn't show as a
   separate dark strip above the topbar, matching the reference layout ── */
header[data-testid="stHeader"] {
    background: transparent;
}

/* ── Headings — Kanit, flat (no decorative underline/shadow) ── */
h1, h2, h3 {
    font-family: 'Kanit', sans-serif !important;
    color: var(--tby-text) !important;
}
h1 { font-weight: 700 !important; margin-bottom: 0.6rem !important; }
h2 { font-weight: 600 !important; }
h3 { font-weight: 600 !important; margin: 0 0 0.3rem 0 !important; }

/* ── Global top bar (page title + date), rendered once per page in app.py ──
   Flush with the page (no card/border) — sticky so it (and the sidebar)
   stay put while only the page content below scrolls. ── */
.tby-topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #ffffff;
    border: none;
    border-bottom: 1px solid var(--tby-border);
    padding: 18px 8px;
    margin: -1.5rem -2rem 20px -2rem;
    width: calc(100% + 4rem);
    position: sticky;
    /* Streamlit's own native header (hamburger/menu bar) is fixed at the very
       top of the viewport with a very high z-index of its own — sticking to
       top:0 would tuck this bar underneath it. Stick just below it instead,
       matching the gap this bar already sits at before it starts scrolling. */
    top: 52px;
    z-index: 100;
}
.tby-topbar-title {
    font-family: 'Kanit', sans-serif;
    font-weight: 700;
    font-size: 2rem;
    color: var(--tby-text);
    padding-left: 1.5rem;
}
.tby-topbar-right {
    display: flex;
    align-items: center;
    gap: 16px;
    padding-right: 1.5rem;
}
.tby-topbar-date {
    font-family: 'Sarabun', sans-serif;
    font-weight: 500;
    font-size: 0.95rem;
    color: var(--tby-muted);
}
/* Streamlit wraps every st.markdown() output in a chain of wrapper divs
   that tightly hug its own content (stElementContainer > stMarkdown >
   stMarkdownContainer). That makes those wrappers the sticky element's
   "containing block", so it only had ~20px of slack to stay stuck before
   unsticking. Collapsing just this chain (via :has, so no other element
   is affected) makes the topbar's effective containing block the full
   page-height block instead, so it can stay pinned for the whole scroll. */
[data-testid="stElementContainer"]:has(.tby-topbar),
[data-testid="stElementContainer"]:has(.tby-topbar) div:has(.tby-topbar) {
    display: contents;
}

/* ── Sidebar — main nav lives here as a dark vertical menu.
   Pinned in place (its own scroll) so it never moves when the page
   content scrolls. ── */
[data-testid="stSidebar"] {
    background: linear-gradient(190deg, var(--tby-sidebar-1) 0%, var(--tby-sidebar-2) 100%) !important;
    position: sticky !important;
    top: 0;
    height: 100vh;
    overflow-y: auto;
}
[data-testid="stSidebar"] h3 {
    color: #ffffff !important;
}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
    color: var(--tby-sidebar-cap) !important;
}
[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.15) !important;
}
/* main nav = one plain st.button per row (flat list, no nesting) — stacks
   vertically automatically since each is its own Streamlit element. Every
   nav button gets type="primary" (active page) or type="secondary"
   (inactive). */
[data-testid="stSidebar"] [data-testid="stElementContainer"] button {
    width: 100% !important;
    justify-content: flex-start !important;
    text-align: left !important;
    border-radius: 10px !important;
    padding: 12px 14px !important;
    font-size: 1.08rem !important;
    font-family: 'Sarabun', sans-serif !important;
}
/* force left-align all the way down — Streamlit centers button labels by
   default via inner wrapper divs/p, which otherwise wins over the button's
   own text-align when the label wraps to 2 lines */
[data-testid="stSidebar"] [data-testid="stElementContainer"] button div {
    justify-content: flex-start !important;
    text-align: left !important;
}
[data-testid="stSidebar"] [data-testid="stElementContainer"] button p {
    font-size: 1.08rem !important;
    color: inherit !important;
    font-weight: inherit !important;
    text-align: left !important;
}
[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"],
[data-testid="stSidebar"] button[data-testid="baseButton-secondary"],
[data-testid="stSidebar"] button[kind="secondary"] {
    background: transparent !important;
    border: none !important;
    color: var(--tby-sidebar-inact) !important;
    box-shadow: none !important;
    font-weight: 500 !important;
}
[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"]:hover,
[data-testid="stSidebar"] button[data-testid="baseButton-secondary"]:hover,
[data-testid="stSidebar"] button[kind="secondary"]:hover {
    background: rgba(255,255,255,0.1) !important;
    border: none !important;
    color: #ffffff !important;
}
[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"],
[data-testid="stSidebar"] button[data-testid="baseButton-primary"],
[data-testid="stSidebar"] button[kind="primary"] {
    background: var(--tby-accent) !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    box-shadow: none !important;
}

/* ── In-page sub-nav (st.pills, used at the top of most pages) — same flat
   underline treatment as st.tabs below, for one consistent "sub tabs" look
   site-wide instead of two different widgets looking different. NOTE:
   Streamlit's st.pills DOM/testid scheme differs by version (older:
   "stPills" + aria-checked; newer: "stButtonGroup" + stBaseButton-
   pillsActive) — every selector duplicated for both so this holds
   regardless of which one is actually deployed. ── */
[data-testid="stButtonGroup"],
[data-testid="stPills"] {
    background: transparent;
    border: none;
    border-bottom: 2px solid var(--tby-border);
    border-radius: 0;
    padding: 0;
    box-shadow: none;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 0 !important;
    margin-bottom: 1.25rem !important;
}
[data-testid="stButtonGroup"] button,
[data-testid="stPills"] button {
    background: transparent !important;
    color: var(--tby-muted) !important;
    border: none !important;
    border-bottom: 3px solid transparent !important;
    border-radius: 0 !important;
    font-family: 'Sarabun', sans-serif !important;
    font-size: 1.02rem !important;
    font-weight: 500 !important;
    padding: 12px 18px 10px !important;
    white-space: nowrap;
    box-shadow: none !important;
    transition: color 0.18s, border-color 0.18s !important;
}
button[data-testid="stBaseButton-pillsActive"],
button[aria-checked="true"],
button[kind="pillsActive"] {
    color: var(--tby-accent) !important;
    font-weight: 600 !important;
    background: transparent !important;
    border-bottom: 3px solid var(--tby-accent) !important;
    box-shadow: none !important;
}
[data-testid="stButtonGroup"] button[data-testid="stBaseButton-pills"]:hover,
[data-testid="stPills"] button:hover {
    color: var(--tby-text) !important;
    background: transparent !important;
}

/* ── Sub-tabs inside each page (st.tabs) — flat underline, matching pills ── */
.stTabs [data-baseweb="tab-list"] {
    background: transparent;
    border-bottom: 2px solid var(--tby-border);
    border-radius: 0;
    padding: 0;
    gap: 4px;
    box-shadow: none;
}
.stTabs [data-baseweb="tab"] {
    color: var(--tby-muted) !important;
    background: transparent !important;
    border-radius: 0 !important;
    font-family: 'Sarabun', sans-serif;
    font-weight: 500;
    font-size: 0.92rem;
    padding: 14px 18px 12px !important;
    border: none !important;
    transition: color 0.18s;
    white-space: nowrap;
}
.stTabs [data-baseweb="tab"]:hover {
    color: var(--tby-text) !important;
    background: transparent !important;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    color: var(--tby-accent) !important;
    font-weight: 600 !important;
    background: transparent !important;
}
.stTabs [data-baseweb="tab-highlight"] {
    background-color: var(--tby-accent) !important;
    height: 3px !important;
    border-radius: 0;
}
.stTabs [data-baseweb="tab-border"] { display: none !important; }

/* ── Primary buttons — flat accent-orange (no gradient/shadow), matching
   the mockup's checkout/CTA button style ── */
button[data-testid="stBaseButton-primary"],
button[data-testid="baseButton-primary"],
button[kind="primary"] {
    background: var(--tby-accent) !important;
    color: #fff !important;
    border: none !important;
    border-radius: 10px !important;
    font-family: 'Kanit', sans-serif !important;
    font-weight: 600 !important;
    box-shadow: none !important;
    transition: background 0.15s !important;
}
button[data-testid="stBaseButton-primary"]:hover,
button[data-testid="baseButton-primary"]:hover,
button[kind="primary"]:hover {
    background: var(--tby-accent-hover) !important;
}

/* ── Secondary buttons — plain bordered ── */
button[data-testid="stBaseButton-secondary"],
button[data-testid="baseButton-secondary"],
button[kind="secondary"] {
    border: 1.5px solid var(--tby-green) !important;
    color: var(--tby-green) !important;
    border-radius: 10px !important;
    font-weight: 500 !important;
    background: white !important;
    box-shadow: none !important;
    transition: background 0.15s !important;
}
button[data-testid="stBaseButton-secondary"]:hover,
button[data-testid="baseButton-secondary"]:hover,
button[kind="secondary"]:hover {
    background: var(--tby-badge-good-bg) !important;
    border-color: var(--tby-green-dark) !important;
    color: var(--tby-green-dark) !important;
}

/* ── Metrics — flat bordered stat cards, no shadow/accent bar ── */
[data-testid="stMetric"] {
    background: white;
    border-radius: 14px;
    padding: 20px !important;
    border: 1px solid var(--tby-border);
    box-shadow: none;
}
[data-testid="stMetricValue"] {
    font-family: 'Kanit', sans-serif !important;
    font-size: 2.3rem !important;
    font-weight: 700 !important;
    color: var(--tby-text) !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.9rem !important;
    font-weight: 500 !important;
    color: var(--tby-muted) !important;
}

/* ── Expanders — flat bordered cards ── */
[data-testid="stExpander"] {
    border: 1px solid var(--tby-border) !important;
    border-radius: 14px !important;
    overflow: hidden;
    box-shadow: none;
}
[data-testid="stExpander"] summary {
    background: var(--tby-table-head-bg) !important;
    color: var(--tby-text) !important;
    font-weight: 600 !important;
    padding: 0.6rem 1rem !important;
}
[data-testid="stExpander"] summary:hover {
    background: var(--tby-border) !important;
}

/* ── Text/Number inputs — roomy, flat, plain white background ── */
.stTextInput input,
.stNumberInput input,
.stTextArea textarea {
    background-color: #ffffff !important;
    border-radius: 9px !important;
    border: 1.5px solid var(--tby-input-border) !important;
    padding: 10px 14px !important;
    min-height: 44px;
    font-family: 'Sarabun', sans-serif !important;
    transition: border-color 0.18s, box-shadow 0.18s !important;
}
.stTextArea textarea {
    min-height: 90px;
}
.stTextInput input:focus,
.stNumberInput input:focus,
.stTextArea textarea:focus {
    border-color: var(--tby-accent) !important;
    box-shadow: 0 0 0 3px oklch(0.68 0.17 45 / 0.2) !important;
}

/* ── Select boxes — same roomy treatment + white background ── */
[data-baseweb="select"] > div:first-child {
    background-color: #ffffff !important;
    border-radius: 9px !important;
    border: 1.5px solid var(--tby-input-border) !important;
    min-height: 44px;
    transition: border-color 0.18s !important;
}
[data-baseweb="select"] > div:first-child:focus-within {
    border-color: var(--tby-accent) !important;
    box-shadow: 0 0 0 3px oklch(0.68 0.17 45 / 0.2) !important;
}

/* ── Radio groups → segmented control, accent-orange selected state ── */
[data-testid="stRadio"] {
    background: #ffffff;
    border: 1px solid var(--tby-border);
    border-radius: 14px;
    padding: 10px 14px 12px !important;
    box-shadow: none;
}
[data-testid="stRadio"] > div[role="radiogroup"] {
    display: flex !important;
    gap: 0 !important;
    flex-wrap: wrap;
    background: var(--tby-table-head-bg);
    border: 1.5px solid var(--tby-border) !important;
    border-radius: 10px;
    padding: 3px;
    overflow: hidden;
}
[data-testid="stRadio"] label > div:first-child {
    display: none !important;
}
[data-testid="stRadio"] label {
    background: transparent !important;
    border: none !important;
    border-radius: 8px !important;
    padding: 7px 16px !important;
    margin: 0 !important;
    flex: 1 1 auto;
    justify-content: center;
    cursor: pointer;
    transition: background 0.18s !important;
}
[data-testid="stRadio"] label:not(:has(input:checked)):hover {
    background: var(--tby-border) !important;
}
[data-testid="stRadio"] label:has(input:checked) {
    background: var(--tby-accent) !important;
    box-shadow: none !important;
}
[data-testid="stRadio"] label:has(input:checked) p,
[data-testid="stRadio"] label:has(input:checked) div {
    color: #ffffff !important;
    font-weight: 600 !important;
}

/* ── Bordered containers (st.container(border=True)) — flat card ── */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: #ffffff;
    border: 1px solid var(--tby-border) !important;
    border-radius: 14px !important;
    box-shadow: none;
}
/* Radio group nested inside a bordered container: drop the double box,
   read as one section of the card instead of a separate floating card */
[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stRadio"] {
    background: transparent;
    border: none;
    padding: 4px 0 !important;
}

/* ── DataFrame / Data editor — flat card, muted header row ── */
[data-testid="stDataFrame"],
[data-testid="stDataEditor"] {
    border-radius: 14px !important;
    overflow: hidden;
    border: 1px solid var(--tby-border);
    box-shadow: none;
}
[data-testid="stDataFrame"] thead tr,
[data-testid="stDataEditor"] thead tr,
[data-testid="stDataFrame"] [role="columnheader"],
[data-testid="stDataEditor"] [role="columnheader"] {
    background: var(--tby-table-head-bg) !important;
    color: var(--tby-muted) !important;
    font-weight: 600 !important;
}

/* ── Block container padding — tighter side gutters so pages use full width,
   matching the reference layout ── */
.block-container {
    padding-top: 1.5rem !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    max-width: 100% !important;
}

/* ── Dividers ── */
hr {
    border-color: var(--tby-border) !important;
    margin: 0.75rem 0 !important;
}

/* ── Typography / Readability ── */
html { font-size: 16px; }

/* Body text & markdown */
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stText"] p {
    font-family: 'Sarabun', sans-serif !important;
    font-size: 0.98rem !important;
    line-height: 1.65 !important;
    color: var(--tby-text) !important;
}

/* Widget labels */
label,
[data-testid="stWidgetLabel"] p {
    font-family: 'Sarabun', sans-serif !important;
    font-size: 0.92rem !important;
    font-weight: 600 !important;
    color: var(--tby-text) !important;
    letter-spacing: 0.01em;
    line-height: 1.5 !important;
}

/* Input / textarea text */
.stTextInput input,
.stNumberInput input,
.stTextArea textarea {
    font-size: 0.98rem !important;
    color: var(--tby-text) !important;
}

/* Selectbox value text */
[data-baseweb="select"] span,
[data-baseweb="select"] div[class*="placeholder"] {
    font-size: 0.96rem !important;
    color: var(--tby-text) !important;
}

/* st.info / st.success / st.warning / st.error */
[data-testid="stAlert"] p {
    font-size: 0.92rem !important;
    line-height: 1.6 !important;
    color: var(--tby-text) !important;
}

/* Caption / small text */
[data-testid="stCaptionContainer"] p {
    font-size: 0.79rem !important;
    color: var(--tby-muted) !important;
    line-height: 1.6 !important;
}

/* Dataframe cells */
[data-testid="stDataFrame"] td,
[data-testid="stDataFrame"] th,
[data-testid="stDataEditor"] td,
[data-testid="stDataEditor"] th {
    font-size: 0.87rem !important;
    line-height: 1.5 !important;
}
</style>
""", unsafe_allow_html=True)

# ── Login guard ──────────────────────────────────────────────────────────────
# (branding — 🛍️ TBY SMART APP — only shown here on the login screen; once
# authenticated the sidebar header is the single place it appears)
_APP_PASSWORD = st.secrets.get("APP_PASSWORD", "")
_DEBUG_MODE   = bool(st.secrets.get("DEBUG_MODE", False))
if _APP_PASSWORD and not st.session_state.get("_authenticated"):
    st.title("🛍️ TBY SMART APP")
    _lc1, _lc2, _lc3 = st.columns([1, 2, 1])
    with _lc2:
        st.markdown("### 🔐 เข้าสู่ระบบ")
        with st.form("_login_form"):
            _pw_input = st.text_input("รหัสผ่าน", type="password", placeholder="กรอกรหัสผ่าน")
            _login_btn = st.form_submit_button("เข้าสู่ระบบ", type="primary", use_container_width=True)
        if _login_btn:
            if _pw_input == _APP_PASSWORD:
                st.session_state["_authenticated"] = True
                st.rerun()
            else:
                st.error("❌ รหัสผ่านไม่ถูกต้อง")
    st.stop()


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

            # ── preset กล่อง (จัดการที่แท็บ ⚙️ จัดการข้อมูล → 📐 ขนาดกล่อง) ──────
            _bulky_presets = get_bulky_presets()
            if not _bulky_presets:
                st.caption("ℹ️ ยังไม่มี preset ขนาดกล่อง — ไปเพิ่มได้ที่แท็บ ⚙️ จัดการข้อมูล → 📐 ขนาดกล่อง")

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
                if _DEBUG_MODE:
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
        if _dbg_resp and _DEBUG_MODE:
            with st.expander("🔍 iShip response (หา order_id)"):
                st.json(_dbg_resp)

    _dluid = info.get("line_user_id", "")
    _dlgid = info.get("group_id", "")
    if (_dluid or _dlgid) and line_api.is_configured():
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


# ── Sidebar navigation — flat main-section menu only; each page's own
#    sub-tabs stay at the top of its content area (unchanged). ─────────────
_TAB_NAMES = [
    "🏠 หน้าแรก", "📋 บันทึกรายการ", "🗂️ รายละเอียดบิล",
    "📦 สต๊อก", "💵 การเงิน", "🛒 E-commerce", "⚙️ จัดการข้อมูล",
]

if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = _TAB_NAMES[0]

with st.sidebar:
    st.markdown(
        """<div style="display:flex;align-items:center;gap:12px;padding:4px 0 12px;">
        <div style="width:44px;height:44px;border-radius:12px;background:var(--tby-accent);
        display:flex;align-items:center;justify-content:center;font-size:1.3rem;flex-shrink:0;">🛍️</div>
        <div>
        <div style="font-family:'Kanit',sans-serif;font-weight:700;font-size:1.05rem;color:#ffffff;line-height:1.3;">TBY SMART APP</div>
        <div style="font-family:'Sarabun',sans-serif;font-size:0.8rem;color:var(--tby-sidebar-cap);line-height:1.3;">ระบบจัดการร้าน</div>
        </div>
        </div>""",
        unsafe_allow_html=True,
    )
    st.divider()

    for _nav_i, _nav_label in enumerate(_TAB_NAMES):
        _nav_is_active = st.session_state["active_tab"] == _nav_label
        if st.button(
            _nav_label, key=f"_nav_top_{_nav_i}",
            use_container_width=True,
            type=("primary" if _nav_is_active else "secondary"),
        ):
            st.session_state["active_tab"] = _nav_label
            st.rerun()

_active_tab = st.session_state["active_tab"]

# ── Global top bar — page title (left) + today's date (right), shown on
#    every page (mirrors the reference mockup's top bar; replaces the old
#    per-page "title + sub-tabs in one row" layout, since every page now
#    gets a title bar here regardless of whether it has sub-tabs) ─────────
_TB_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
_TB_MONTHS = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
              "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
_tb_today = date.today()
_tb_date_str = f"วัน{_TB_DAYS[_tb_today.weekday()]} {_tb_today.day} {_TB_MONTHS[_tb_today.month]} {_tb_today.year + 543}"
st.markdown(
    f"""<div class="tby-topbar">
    <div class="tby-topbar-title">{_active_tab}</div>
    <div class="tby-topbar-right">
        <div class="tby-topbar-date">{_tb_date_str}</div>
    </div>
    </div>""",
    unsafe_allow_html=True,
)

_products = db.get_products()
_customers = db.get_customers()

# ── Render only the active tab — ไม่รัน render() ของแท็บอื่น ─────────────────
if _active_tab == _TAB_NAMES[0]:
    dashboard_ui.render()
elif _active_tab == _TAB_NAMES[1]:
    record_ui.render(st.container(), _products, _customers, {c["name"]: c for c in _customers})
elif _active_tab == _TAB_NAMES[2]:
    bill_detail_ui.render(_products, _customers)
elif _active_tab == _TAB_NAMES[3]:
    stock_ui.render()
elif _active_tab == _TAB_NAMES[4]:
    fin_ui.render()
elif _active_tab == _TAB_NAMES[5]:
    ecom_ui.render()
elif _active_tab == _TAB_NAMES[6]:
    master_data_ui.render()
