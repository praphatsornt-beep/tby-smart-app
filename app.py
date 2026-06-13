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
import zipfile

import database as db
import carriers as carr
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
import line_api
import iship_api
from math import ceil
from flash_zones import lookup_zone, zone_surcharge, ZONE_LABELS, carrier_fees

BOX_WEIGHT_G = 500  # น้ำหนักกล่อง 0.5 kg (ไม่แสดงในระบบ)

def _to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Sheet1") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return buf.getvalue()


@st.cache_data
def _tambon_select_options() -> list:
    """[{tambon, amphure, province, zipcode}, ...] เรียงตามชื่อตำบล"""
    return sorted(thai_address._load_tambon_index(), key=lambda r: r["tambon"])


@st.cache_data
def _tambon_by_postcode(pc: str) -> list:
    """[{tambon, amphure, province, zipcode}, ...] ที่ตรงกับรหัสไปรษณีย์นี้"""
    return [o for o in _tambon_select_options() if o["zipcode"] == pc]


def _tambon_option_label(opt) -> str:
    return f"{opt['tambon']} / {opt['amphure']} / {opt['province']} ({opt['zipcode']})"


_TAMBON_PREFIXES   = ["ตำบล", "ต.", "แขวง"]
_PROVINCE_PREFIXES = ["จังหวัด", "จ."]


def _strip_admin_prefix(s: str, prefixes: list) -> str:
    s = (s or "").strip()
    for p in prefixes:
        if s.startswith(p):
            return s[len(p):].strip()
    return s


def _tambon_selectbox(value_key: str, am_key: str, pv_key: str, pc_key: str,
                       selectbox_key: str, label: str = "ตำบล/แขวง"):
    """ช่อง ตำบล/แขวง แบบ dropdown ค้นหา (st.selectbox มาตรฐาน — พิมพ์กรองรายการได้ทันที)
    เลือกแล้ว auto-fill อำเภอ/จังหวัด/รหัสไปรษณีย์ ให้ด้วย ถ้ายังไม่เลือก จะแสดงเป็นช่องว่างพร้อม placeholder
    """
    options = _tambon_select_options()

    cur_val = st.session_state.get(value_key, "")
    cur_am  = st.session_state.get(am_key, "")
    cur_pv  = st.session_state.get(pv_key, "")
    cur_pc  = st.session_state.get(pc_key, "")
    cur_sig = (cur_val, cur_pv)

    _sig_key = f"_{selectbox_key}_sig"
    if st.session_state.get(_sig_key) != cur_sig:
        st.session_state.pop(selectbox_key, None)
        st.session_state[_sig_key] = cur_sig

    _norm_val = _strip_admin_prefix(cur_val, _TAMBON_PREFIXES)
    _norm_pv  = _strip_admin_prefix(cur_pv, _PROVINCE_PREFIXES)

    match_idx = None
    if _norm_val:
        for i, opt in enumerate(options):
            if opt["tambon"] == _norm_val and (not _norm_pv or opt["province"] == _norm_pv):
                match_idx = i
                break

    # ถ้าค่าที่บันทึกไว้ไม่ตรงกับรายชื่อตำบลในฐานข้อมูล (เช่น สะกดต่างกัน)
    # ให้แสดงค่าเดิมเป็นตัวเลือกแรกไว้ก่อน เพื่อไม่ให้ช่องว่างเปล่า
    if cur_val and match_idx is None:
        options = [{"tambon": cur_val, "amphure": cur_am, "province": cur_pv, "zipcode": cur_pc}] + options
        match_idx = 0

    idx_options = list(range(len(options)))
    _short_label = lambda opt: f"{opt['tambon']} ({opt['zipcode']})"
    label_map = {_short_label(opt): i for i, opt in enumerate(options)}

    def _on_change():
        raw = st.session_state.get(selectbox_key)
        i = raw if isinstance(raw, int) else label_map.get(raw)
        if i is not None:
            sel = options[i]
            st.session_state[value_key] = sel["tambon"]
            st.session_state[am_key]    = sel["amphure"]
            st.session_state[pv_key]    = sel["province"]
            st.session_state[pc_key]    = sel["zipcode"]
            st.session_state[_sig_key]  = (sel["tambon"], sel["province"])

    st.selectbox(
        label, idx_options, index=match_idx, placeholder="พิมพ์ค้นหาตำบล",
        format_func=lambda i: _short_label(options[i]),
        key=selectbox_key, on_change=_on_change,
    )

    return st.session_state.get(value_key, cur_val)


def _postcode_suggest(pc: str, value_key: str, am_key: str, pv_key: str,
                       searchbox_key: str, suggest_key: str):
    """ถ้ารหัสไปรษณีย์ตรงกับ ต./อ./จ. มากกว่า 1 รายการ และค่าปัจจุบันยังไม่ตรง
    ให้แสดง selectbox ให้เลือก ต./อ./จ. ตามรหัสไปรษณีย์นั้น"""
    pc = (pc or "").strip()
    if len(pc) != 5:
        return
    opts = _tambon_by_postcode(pc)
    if not opts:
        return
    cur = (st.session_state.get(value_key, ""), st.session_state.get(am_key, ""), st.session_state.get(pv_key, ""))
    if cur in [(o["tambon"], o["amphure"], o["province"]) for o in opts]:
        return

    idx_options = list(range(len(opts)))
    _suggest_label = lambda i: f"{opts[i]['tambon']} / {opts[i]['amphure']} / {opts[i]['province']}"
    label_map = {_suggest_label(i): i for i in idx_options}

    def _on_pick():
        raw = st.session_state.get(suggest_key)
        i = raw if isinstance(raw, int) else label_map.get(raw)
        if i is not None:
            sel = opts[i]
            st.session_state[value_key] = sel["tambon"]
            st.session_state[am_key]    = sel["amphure"]
            st.session_state[pv_key]    = sel["province"]
            st.session_state.pop(searchbox_key, None)
            st.session_state.pop(f"_{searchbox_key}_sig", None)

    st.selectbox(
        f"📍 ตำบล/อำเภอ/จังหวัด สำหรับรหัส {pc}", idx_options, index=None,
        placeholder="เลือกที่อยู่ตามรหัสไปรษณีย์",
        format_func=_suggest_label,
        key=suggest_key, on_change=_on_pick,
    )


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
        "COD":          "background-color:#7a5c00;color:white",
        "COD จ่ายแล้ว":  "background-color:#1a5c2e;color:white",
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


def _render_bill_panel(sel_p, cust_map_p, all_txn_cache, customers_p, key_prefix, preselected_bill=None):
    """แสดงส่วนเลือกบิล / พิมพ์บิล / จัดการบิล สำหรับลูกค้า sel_p
    preselected_bill: ถ้าระบุ ข้ามตัวเลือกบิล แสดงบิลนี้ตรง ๆ (ใช้กับค้นด้วยเลขที่บิล)
    key_prefix: prefix สำหรับ widget key / session_state กันชนกันเมื่อเรียกซ้ำหลายลูกค้า
    """
    if preselected_bill:
        all_df_p = all_txn_cache[all_txn_cache["เลขที่บิล"] == preselected_bill]
        if all_df_p.empty:
            st.warning(f"ไม่พบบิล {preselected_bill}")
            return
        sel_p = all_df_p["ลูกค้า"].iloc[0]
        _bill_picked = preselected_bill
    else:
        all_df_p = all_txn_cache[all_txn_cache["ลูกค้า"] == sel_p]

        _ck = f"_{key_prefix}_bill_cust"
        _pk = f"_{key_prefix}_bill_picked"
        if st.session_state.get(_ck) != sel_p:
            st.session_state.pop(_pk, None)
            st.session_state[_ck] = sel_p

        _bill_picked = st.session_state.get(_pk, "")

        if not _bill_picked:
            if all_df_p.empty:
                st.info("ไม่มีรายการ")
                return

            _bills = (all_df_p.groupby("เลขที่บิล", dropna=False)
                      .agg(วันที่=("วันที่", "max"),
                           ยอดรวม=("ยอดรวม", "sum"),
                           ค้างจ่าย=("ค้างจ่าย", "sum"),
                           ค้างรับ=("ค้างรับ", "sum"))
                      .reset_index()
                      .sort_values("วันที่", ascending=False))
            _pv_col = "PV รวม" if "PV รวม" in all_df_p.columns else None
            _pv_unbilled_map = {}
            if _pv_col:
                _pv_unbilled_map = (
                    all_df_p[all_df_p.get("สถานะบิล", pd.Series(dtype=str)) == "ยังไม่เปิดบิล"]
                    .groupby("เลขที่บิล")[_pv_col].sum()
                    .to_dict()
                )

            if len(_bills) == 1:
                st.session_state[_pk] = _bills.iloc[0]["เลขที่บิล"] or "—"
                st.rerun()
            st.caption("เลือกบิลที่ต้องการพิมพ์")
            _total_owed    = _bills["ค้างจ่าย"].sum()
            _total_pending = int(_bills["ค้างรับ"].sum())
            _total_pv_unbilled = sum(_pv_unbilled_map.values())
            _all_color    = "🔴" if _total_owed > 0.01 else "✅"
            _all_pv_str   = f" &nbsp; ⭐ {_total_pv_unbilled:,.0f} PV" if _total_pv_unbilled > 0 else ""
            _all_recv_str = f" &nbsp; 📦 ยังไม่รับของ {_total_pending} ชิ้น" if _total_pending > 0 else ""
            if st.button(
                f"📋 **รวมทุกบิล** &nbsp; {_all_color} ค้างจ่ายรวม {_total_owed:,.0f} บาท{_all_recv_str}{_all_pv_str}",
                key=f"{key_prefix}_pbill_ALL", use_container_width=True):
                st.session_state[_pk] = "__ALL__"
                st.rerun()
            st.divider()
            for _, _br in _bills.iterrows():
                _bno      = _br["เลขที่บิล"] or "—"
                _owing    = _br["ค้างจ่าย"]
                _pending  = int(_br["ค้างรับ"])
                _color    = "🔴" if _owing > 0.01 else "✅"
                _pv_un    = _pv_unbilled_map.get(_bno, 0)
                _pv_str   = f" &nbsp; ⭐ {_pv_un:,.0f} PV" if _pv_un > 0 else ""
                _recv_str = f" &nbsp; 📦 ยังไม่รับของ {_pending} ชิ้น" if _pending > 0 else ""
                _lbl = (f"📄 **{_bno}** &nbsp; {_br['วันที่']} &nbsp; "
                        f"{_color} ค้างจ่าย {_owing:,.0f} บาท{_recv_str}{_pv_str}")
                if st.button(_lbl, key=f"{key_prefix}_pbill_{_bno}", use_container_width=True):
                    st.session_state[_pk] = _bno
                    st.rerun()
            return
        else:
            _bx1, _bx2 = st.columns([6, 1])
            _lbl_picked = "รวมทุกบิล" if _bill_picked == "__ALL__" else f"บิล {_bill_picked}"
            _bx1.markdown(f"📄 **{_lbl_picked}**")
            if _bx2.button("✕ เปลี่ยน", key=f"{key_prefix}_bill_clear"):
                st.session_state.pop(_pk, None)
                st.rerun()
            if _bill_picked != "__ALL__":
                if _bill_picked == "—":
                    all_df_p = all_df_p[all_df_p["เลขที่บิล"].replace("", "—") == "—"]
                else:
                    all_df_p = all_df_p[all_df_p["เลขที่บิล"] == _bill_picked]

    if all_df_p.empty:
        return

    show_p = all_df_p.copy()

    if show_p.empty:
        st.success(f"✅ {sel_p} ไม่มียอดค้าง")
        return

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
    filter_label      = "รายการทั้งหมด"
    bill_nos          = show_p["เลขที่บิล"].dropna().unique().tolist() if "เลขที่บิล" in show_p.columns else []
    bill_nos_str      = ", ".join(b for b in bill_nos if b) or ""
    _last_paid_raw    = show_p["last_payment_date"].replace("", None).max() if "last_payment_date" in show_p.columns else None
    try:
        _paid_date_str = pd.to_datetime(_last_paid_raw).strftime("%d/%m/%Y") if _last_paid_raw else "—"
    except Exception:
        _paid_date_str = "—"

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
    <div style="font-size:14px;font-weight:600;margin-top:4px">วันที่รับเงิน: {_paid_date_str}</div>
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
    <tr><td>⭐ PV รวม (ยังไม่เปิดบิล)</td><td><b style="color:#b8860b">{unbilled_pv:.0f}</b></td></tr>
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

    _body = f"""<div class="two-col">
  <div class="copy">{_bill_body("สำหรับลูกค้า")}</div>
  <div class="vcut"></div>
  <div class="copy">{_bill_body("สำหรับร้าน")}</div>
</div>"""
    _height = 750

    bill_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{_css}</style></head><body>
<button class="btn" onclick="window.print()">🖨️ พิมพ์</button>
{_body}
<br><button class="btn" onclick="window.print()">🖨️ พิมพ์</button>
</body></html>"""

    components.html(bill_html, height=_height, scrolling=True)

    # ── ส่งสรุปบิล LINE ─────────────────────────────────────
    _t7_cust_name = show_p["ลูกค้า"].iloc[0] if not show_p.empty else sel_p
    _t7_cust_id   = cust_map_p.get(_t7_cust_name, {}).get("id", "")
    _t7_line_uid  = db.get_customer_line_user_id(_t7_cust_id) if _t7_cust_id else ""
    _t7_items = [{"name": r["สินค้า"], "qty": int(r["สั่ง"]),
                  "total": float(r["ยอดรวม"])} for _, r in show_p.iterrows()]
    _t7_pay = show_p.iloc[0].get("สถานะบิล", "") if not show_p.empty else ""
    _t7_col1, _t7_col2 = st.columns([1, 2])
    if _t7_col1.button("📨 ส่งสรุปบิล LINE", key=f"{key_prefix}_line_btn",
                       disabled=not bool(_t7_line_uid),
                       help="ส่งสรุปให้ลูกค้าใน LINE" if _t7_line_uid else "ลูกค้าไม่มี LINE ID"):
        _r7 = line_api.push_bill_summary(
            _t7_line_uid, _t7_cust_name, bill_nos_str,
            _t7_items, total_amount, _t7_pay
        )
        if _r7["ok"]:
            st.success("✅ ส่ง LINE แล้ว")
        else:
            st.error(f"LINE error: {_r7['error']}")

    # ── จัดการบิล ────────────────────────────────────────────
    _t7_tids = show_p["id"].tolist()
    _t7_single = len(bill_nos) == 1 and bill_nos[0]

    with st.expander("📋 สถานะบิล"):
        _cur_bstat = show_p["สถานะบิล"].iloc[0]
        _t7_bstat = st.radio("สถานะ", ["เปิดบิลแล้ว", "ยังไม่เปิดบิล"],
                              index=0 if _cur_bstat == "เปิดบิลแล้ว" else 1,
                              horizontal=True, key=f"{key_prefix}_bstat")
        if st.button("💾 บันทึกสถานะบิล", key=f"{key_prefix}_save_bstat"):
            for _tid in _t7_tids:
                db.update_transaction_status(_tid, bill_status=_t7_bstat)
            st.success(f"✅ อัพเดต {len(_t7_tids)} รายการ → {_t7_bstat}")
            st.rerun()

    with st.expander("💳 สถานะการจ่าย"):
        _cur_pstat = show_p["สถานะจ่าย"].iloc[0]
        _t7_pstat = st.radio("สถานะ", ["จ่ายแล้ว", "ค้างจ่าย"],
                              index=0 if _cur_pstat == "จ่ายแล้ว" else 1,
                              horizontal=True, key=f"{key_prefix}_pstat")
        if st.button("💾 บันทึกสถานะจ่าย", key=f"{key_prefix}_save_pstat"):
            for _tid in _t7_tids:
                db.update_transaction_status(_tid, pay_status=_t7_pstat)
            st.success(f"✅ อัพเดต {len(_t7_tids)} รายการ → {_t7_pstat}")
            st.rerun()

    with st.expander("💰 บันทึกรับเงิน"):
        _t7_owed = float(show_p["ค้างจ่าย"].sum())
        _t7_paid_so_far = float(show_p["จ่ายแล้ว"].sum())
        _t7_total_amt   = float(show_p["ยอดรวม"].sum())
        pm1, pm2, pm3 = st.columns(3)
        pm1.metric("ยอดรวมบิล",  f"{_t7_total_amt:,.0f} ฿")
        pm2.metric("จ่ายแล้ว",    f"{_t7_paid_so_far:,.0f} ฿")
        pm3.metric("ค้างจ่าย",    f"{_t7_owed:,.0f} ฿")
        if _t7_owed <= 0.01:
            st.success("✅ ชำระครบแล้ว")
        else:
            _t7_pay_date = st.date_input("วันที่รับเงิน", value=date.today(), key=f"{key_prefix}_pay_date")
            _t7_pay_amt  = st.number_input(
                "จำนวนเงินที่รับ (บาท)",
                min_value=0.0, max_value=float(_t7_owed),
                value=float(_t7_owed), step=1.0, key=f"{key_prefix}_pay_amount",
            )
            if st.button("💾 บันทึกรับเงิน", key=f"{key_prefix}_save_pay", type="primary",
                         use_container_width=True):
                _owed_rows = show_p[show_p["ค้างจ่าย"] > 0.01].reset_index(drop=True)
                _owed_ids  = _owed_rows["id"].tolist()
                _row_owed  = _owed_rows["ค้างจ่าย"].tolist()
                _total_row_owed = sum(_row_owed)
                _remaining = float(_t7_pay_amt)
                for _pi, (_tid_p, _row_o) in enumerate(zip(_owed_ids, _row_owed)):
                    if _remaining <= 0:
                        break
                    if _pi == len(_owed_ids) - 1:
                        _share = _remaining
                    else:
                        _share = round(_row_o / _total_row_owed * float(_t7_pay_amt), 2)
                        _share = min(_share, _remaining)
                    db.insert_partial_event({
                        "id":             str(uuid.uuid4()),
                        "date":           str(_t7_pay_date),
                        "transaction_id": _tid_p,
                        "qty_received":   0,
                        "amount_paid":    _share,
                        "event_type":     "จ่าย",
                    })
                    _remaining -= _share
                if float(_t7_pay_amt) >= _t7_owed - 0.01:
                    for _tid in _t7_tids:
                        db.update_transaction_status(_tid, pay_status="จ่ายแล้ว")
                st.success(f"✅ บันทึกรับเงิน {_t7_pay_amt:,.0f} ฿ แล้ว")
                st.rerun()

    if _t7_single:
        with st.expander("📦 บันทึกรับของ"):
            _recv_base = show_p[["สินค้า","สั่ง","รับแล้ว","ค้างรับ"]].copy().reset_index(drop=True)
            _recv_ids  = show_p["id"].reset_index(drop=True)
            _recv_base["รับเพิ่ม"] = pd.Series([0]*len(_recv_base), dtype="int64")
            _recv_edit = st.data_editor(
                _recv_base,
                hide_index=True, use_container_width=True,
                column_config={
                    "รับเพิ่ม": st.column_config.NumberColumn("รับเพิ่ม", min_value=0, step=1, width="small"),
                },
                disabled=["สินค้า","สั่ง","รับแล้ว","ค้างรับ"],
                key=f"{key_prefix}_recv_edit"
            )
            if st.button("💾 บันทึกรับของ", key=f"{key_prefix}_save_recv"):
                _saved_r = 0
                for _ri, _rrow in _recv_edit.iterrows():
                    _delta = int(_rrow["รับเพิ่ม"] or 0)
                    if _delta <= 0:
                        continue
                    _cap = int(_recv_base.iloc[_ri]["ค้างรับ"])
                    _delta = min(_delta, _cap)
                    db.insert_partial_event({
                        "id":             str(uuid.uuid4()),
                        "date":           str(date.today()),
                        "transaction_id": _recv_ids.iloc[_ri],
                        "qty_received":   _delta,
                        "amount_paid":    0.0,
                        "event_type":     "รับของ",
                    })
                    _saved_r += 1
                if _saved_r:
                    st.success(f"✅ บันทึกรับของ {_saved_r} รายการ")
                    st.rerun()
                else:
                    st.warning("ไม่มีรายการที่เปลี่ยนแปลง")

    # ── เปลี่ยนลูกค้าในบิล ──────────────────────────────────
    with st.expander("✏️ เปลี่ยนลูกค้าในบิลนี้"):
        st.caption(f"บิลปัจจุบัน: {bill_nos_str} | ลูกค้า: {_t7_cust_name}")
        if bill_nos_str and db.bill_has_partial_events(bill_nos_str):
            st.warning("⚠️ บิลนี้มีการจ่าย/รับของแล้ว — เปลี่ยนได้แต่ยอดค้างอาจเปลี่ยน")
        _new_cust_name = st.selectbox(
            "เลือกลูกค้าใหม่",
            [c["name"] for c in customers_p],
            key=f"{key_prefix}_new_cust"
        )
        _new_cust_id = cust_map_p.get(_new_cust_name, {}).get("id")
        _confirm_cust = st.checkbox("ยืนยันการเปลี่ยนลูกค้า", key=f"{key_prefix}_confirm_cust")
        if st.button("💾 บันทึก", disabled=not (_confirm_cust and _new_cust_id and bill_nos_str),
                     key=f"{key_prefix}_save_cust"):
            db.update_bill_customer(bill_nos_str, _new_cust_id)
            st.success(f"✅ เปลี่ยนเป็น {_new_cust_name} แล้ว")
            st.rerun()

    if _t7_single:
        with st.expander("🗑️ ลบบิล"):
            st.warning(f"ลบบิล **{bill_nos[0]}** และรายการทั้งหมด ({len(show_p)} รายการ) — กู้คืนไม่ได้")
            _t7_del_chk = st.checkbox("ยืนยันการลบ", key=f"{key_prefix}_del_confirm")
            if st.button("🗑️ ลบบิล", disabled=not _t7_del_chk,
                         type="secondary", key=f"{key_prefix}_del_bill"):
                db.delete_bill(bill_nos[0])
                st.success("✅ ลบบิลแล้ว")
                if not preselected_bill:
                    st.session_state.pop(_pk, None)
                st.rerun()

    with st.expander("🗑️ ลบรายการ"):
        st.caption("เลือกรายการสินค้าที่ต้องการลบออก (ไม่ลบทั้งบิล)")
        _t7_item_opts = {
            f"{r['สินค้า']} — บิล {r['เลขที่บิล'] or '—'} (฿{r['ยอดรวม']:,.0f})": r["id"]
            for _, r in show_p.iterrows()
        }
        _t7_del_item_label = st.selectbox(
            "รายการ", list(_t7_item_opts.keys()), key=f"{key_prefix}_del_item_sel"
        )
        _t7_del_item_chk = st.checkbox("ยืนยันการลบรายการนี้", key=f"{key_prefix}_del_item_confirm")
        if st.button("🗑️ ลบรายการ", disabled=not _t7_del_item_chk,
                     type="secondary", key=f"{key_prefix}_del_item_btn"):
            db.delete_transaction(_t7_item_opts[_t7_del_item_label])
            st.success("✅ ลบรายการแล้ว")
            if not preselected_bill:
                st.session_state.pop(_pk, None)
            st.rerun()

    # ── เคลียร์บิลหลายใบ ──────────────────────────────────────
    _t7_all_cust_df = all_txn_cache[all_txn_cache["ลูกค้า"] == _t7_cust_name]
    if not _t7_all_cust_df.empty:
        _t7_bill_grp = (
            _t7_all_cust_df.groupby("เลขที่บิล", dropna=False)
            .agg(
                วันที่=("วันที่", "max"),
                ค้างจ่าย=("ค้างจ่าย", "sum"),
                is_paid=("สถานะจ่าย", lambda x: (x == "จ่ายแล้ว").all()),
                is_billed=("สถานะบิล", lambda x: (x == "เปิดบิลแล้ว").all()),
            )
            .reset_index()
            .sort_values("วันที่", ascending=False)
        )
        with st.expander("✅ เคลียร์บิล"):
            st.caption("ติ๊กบิลที่ต้องการ → เปลี่ยนเป็น จ่ายแล้ว + เปิดบิลแล้ว พร้อมกัน")
            _clr_sel = []
            for _, _clr_br in _t7_bill_grp.iterrows():
                _clr_bno = _clr_br["เลขที่บิล"] or "—"
                _clr_done = bool(_clr_br["is_paid"]) and bool(_clr_br["is_billed"])
                _clr_icon = "✅" if _clr_done else ("🔴" if _clr_br["ค้างจ่าย"] > 0.01 else "🟡")
                _clr_lbl = f"{_clr_icon} **{_clr_bno}** — {_clr_br['วันที่']} — ค้างจ่าย {_clr_br['ค้างจ่าย']:,.0f} ฿"
                _clr_ticked = st.checkbox(_clr_lbl, key=f"{key_prefix}_clr_{_clr_bno}",
                                          value=_clr_done, disabled=_clr_done)
                if _clr_ticked and not _clr_done:
                    _clr_sel.append(_clr_bno)
            if _clr_sel:
                if st.button(f"✅ เคลียร์ {len(_clr_sel)} บิล", type="primary", key=f"{key_prefix}_clear_bills"):
                    for _clr_bno in _clr_sel:
                        _clr_tids = _t7_all_cust_df[
                            _t7_all_cust_df["เลขที่บิล"] == _clr_bno
                        ]["id"].tolist()
                        for _clr_tid in _clr_tids:
                            db.update_transaction_status(
                                _clr_tid,
                                pay_status="จ่ายแล้ว",
                                bill_status="เปิดบิลแล้ว",
                            )
                    st.success(f"✅ เคลียร์ {len(_clr_sel)} บิลแล้ว")
                    st.rerun()


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
            _cmp.append({"ขนส่ง": ("🥇 " if _ci == 0 else "") + o["name"],
                         "ค่าส่ง": o["base"], "พื้นที่พิเศษ": _sur_txt,
                         "น้ำมัน": _fuel_txt, "รวม (฿)": o["total"], "COD": _cod_txt})
        st.dataframe(pd.DataFrame(_cmp), hide_index=True, use_container_width=True,
                     column_config={"รวม (฿)": st.column_config.NumberColumn("รวม (฿)", format="%d ฿")})

        _cs_carrier = st.selectbox("เลือกขนส่ง", [o["name"] for o in opts_ok],
                                   index=0, key="_cs_carrier_sel")
        _cs_code    = iship_api.COURIER_MAP.get(_cs_carrier, "")
        _cs_total   = next((o["total"] for o in opts_ok if o["name"] == _cs_carrier), 0)
        st.caption(f"iShip code: `{_cs_code}` | ราคาจริง: {_cs_total:,} ฿")
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
        _btn1, _btn2 = st.columns(2)
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
                _cs_d       = _cs_resp.get("data") or {}
                _cs_track   = (_cs_d.get("tracking_code") or _cs_d.get("tracking_number")
                               or _cs_resp.get("tracking_code") or _cs_resp.get("tracking_number") or "")
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
                    except Exception:
                        pass
                _cs_luid = db.get_customer_line_user_id(info.get("customer_id","")) if info.get("customer_id") else ""
                st.session_state["_iship_success_info"] = {
                    "tracking":             _cs_track,
                    "tab":                  tab,
                    "customer":             info.get("customer_name", ""),
                    "dst_name":             info.get("dst_name", ""),
                    "dst_phone":            info.get("dst_phone", ""),
                    "address":              f"{info.get('address_line','')} {info.get('district','')} {info.get('amphure','')} {info.get('province','')} {postcode}".strip(),
                    "carrier":              _cs_carrier,
                    "weight_kg":            weight_kg,
                    "cod_amount":           int(cod_amt),
                    "items":                info.get("items", []),
                    "line_user_id":         _cs_luid,
                    "shipment_id":          info.get("shipment_id", ""),
                    "_carrier_select_info": info,
                }
                st.session_state.pop("_iship_carrier_select", None)
                st.session_state["_open_success_dialog"] = True
                st.session_state["_do_clear_after_iship"] = tab
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
        if st.button("ปิด", key="_cs_close"):
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
    _dluid = info.get("line_user_id", "")
    if _dluid and line_api.is_configured():
        if st.button("📨 ส่งแจ้งลูกค้าทาง LINE", use_container_width=True):
            _dlr = line_api.push_tracking(
                _dluid,
                info.get("dst_name", ""),
                info.get("tracking", ""),
                info.get("carrier", ""),
                float(info.get("cod_amount", 0)),
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
# success dialog: pop-once (ไม่มี interactive widget ภายใน)
if st.session_state.pop("_open_success_dialog", False):
    _show_iship_success_dialog()


tab_dash, tab1, tab5, tab6, tab_fin, tab_ecom, tab4 = st.tabs([
    "🏠 หน้าแรก",
    "📋 บันทึกรายการ",
    "🗂️ รายละเอียดบิล",
    "📦 สต๊อก",
    "💵 การเงิน",
    "🛒 E-commerce",
    "⚙️ จัดการข้อมูล",
])

# sub-tabs ของ tab5 ต้องนิยามก่อนใช้ (with _t5_out: อยู่ก่อน with tab5: ในไฟล์)
with tab5:
    _t5_out, _t5_ledger, _t5_txn, _t5_ship = st.tabs([
        "💰 ยอดค้าง / จัดการบิล", "👤 บัตรลูกค้า", "📋 ประวัติทั้งหมด", "🚚 ประวัติการส่ง"
    ])



# ─────────────────────────────────────────────────────────────────────────────
# Tab Dashboard: หน้าแรก
# ─────────────────────────────────────────────────────────────────────────────
with tab_dash:
    _today = date.today()
    _today_str = _today.strftime("%Y-%m-%d")
    _thai_days = ["จันทร์","อังคาร","พุธ","พฤหัสบดี","ศุกร์","เสาร์","อาทิตย์"]
    _thai_months = ["","ม.ค.","ก.พ.","มี.ค.","เม.ย.","พ.ค.","มิ.ย.","ก.ค.","ส.ค.","ก.ย.","ต.ค.","พ.ย.","ธ.ค."]
    _day_name = _thai_days[_today.weekday()]
    st.caption(f"📅 วัน{_day_name} {_today.day} {_thai_months[_today.month]} {_today.year + 543}")

    # ── โหลด data (ทั้งหมด cached) ──────────────────────────────────────────
    try:
        _dash_txn   = db.get_all_transactions_df()
        _dash_outs  = db.get_outstanding_df()
        _dash_ships = db.get_shipments()
        _dash_pv    = db.get_unbilled_pv_summary()
        _dash_fin   = db.get_finance_summary()
    except Exception as _de:
        st.error(f"โหลดข้อมูลไม่ได้: {_de}")
        st.stop()

    # ── คำนวณ metrics ────────────────────────────────────────────────────────
    _today_txn = _dash_txn[_dash_txn["วันที่"] == _today_str] if not _dash_txn.empty else pd.DataFrame()
    _today_sales = _today_txn["ยอดรวม"].sum() if not _today_txn.empty else 0.0
    _today_count = len(_today_txn)

    _total_owed  = _dash_outs["ค้างจ่าย"].sum() if not _dash_outs.empty else 0.0
    _total_custs = _dash_outs["ลูกค้า"].nunique() if not _dash_outs.empty else 0

    _cod_pending = [s for s in _dash_ships
                    if float(s.get("cod_amount") or 0) > 0
                    and not s.get("cod_transferred_at")]
    _cod_count  = len(_cod_pending)
    _cod_amt    = sum(float(s.get("cod_amount") or 0) for s in _cod_pending)

    _pv_count = _dash_pv.get("count", 0)
    _pv_total = _dash_pv.get("total_pv", 0.0)

    # ── Metric cards ─────────────────────────────────────────────────────────
    _dc1, _dc2, _dc3, _dc4 = st.columns(4)
    _dc1.metric("💵 ยอดขายวันนี้",   f"{_today_sales:,.0f} ฿",
                delta=f"{_today_count} รายการ", delta_color="off")
    _dc2.metric("⚠️ ค้างจ่ายรวม",    f"{_total_owed:,.0f} ฿",
                delta=f"{_total_custs} ลูกค้า", delta_color="off")
    _dc3.metric("🚚 COD รอรับ",       f"{_cod_count} รายการ",
                delta=f"{_cod_amt:,.0f} ฿" if _cod_amt else "ไม่มี", delta_color="off")
    _dc4.metric("⭐ PV รอเปิดบิล",   f"{_pv_total:,.0f} PV",
                delta=f"{_pv_count} รายการ", delta_color="off")

    # แสดงสิทธิ์สั่งของถ้ามี finance data
    _credit = float(_dash_fin.get("credit", 0) or 0)
    if _credit > 0:
        st.info(f"💳 สิทธิ์สั่งของคงเหลือ: **{_credit:,.0f} ฿**")

    st.divider()

    # ── 2 คอลัมน์: รายการวันนี้ + ลูกค้าค้างสูงสุด ──────────────────────────
    _dl, _dr = st.columns([3, 2])

    with _dl:
        st.markdown("**📋 รายการที่บันทึกวันนี้**")
        if _today_txn.empty:
            st.caption("ยังไม่มีรายการวันนี้")
        else:
            _show_today = _today_txn[["เลขที่บิล","ลูกค้า","สินค้า","ยอดรวม","สถานะบิล"]].copy()
            _show_today = _show_today.rename(columns={"เลขที่บิล": "บิล", "ยอดรวม": "ยอด (฿)"})
            st.dataframe(
                _show_today.style.format({"ยอด (฿)": "{:,.0f}"}),
                use_container_width=True, hide_index=True,
                height=min(35 * len(_show_today) + 38, 320),
            )

    with _dr:
        st.markdown("**🔴 ลูกค้าค้างสูงสุด (Top 5)**")
        if _dash_outs.empty:
            st.caption("ไม่มียอดค้าง")
        else:
            _top5 = (_dash_outs.groupby("ลูกค้า")
                     .agg(ค้างจ่าย=("ค้างจ่าย","sum"), ค้างรับ=("ค้างรับ","sum"))
                     .sort_values("ค้างจ่าย", ascending=False)
                     .head(5)
                     .reset_index())
            st.dataframe(
                _top5.style.format({"ค้างจ่าย": "{:,.0f}", "ค้างรับ": "{:.0f}"}),
                use_container_width=True, hide_index=True,
            )

    # ── helper ───────────────────────────────────────────────────────────────
    def _parse_sdt(s_str):
        try:
            return datetime.fromisoformat(s_str.replace("Z", "+00:00"))
        except Exception:
            return None

    def _items_str(sh):
        its = sh.get("items") or []
        return ", ".join(
            f"{it.get('name') or it.get('product_id','')} ×{it.get('qty',1)}"
            for it in its
        ) if its else "—"

    if _dash_ships:
        _TERMINAL_S  = {"จัดส่งแล้ว", "ตีกลับ", "ยกเลิก"}
        _now_utc     = datetime.now(timezone.utc)
        _cutoff      = _now_utc - timedelta(days=3)

        # ลูกค้าที่มี COD + ยังไม่เปิดบิล
        _cod_unbilled_custs = set()
        if not _dash_txn.empty and "สถานะจ่าย" in _dash_txn.columns and "สถานะบิล" in _dash_txn.columns:
            _cmask = (_dash_txn["สถานะจ่าย"] == "COD") & (_dash_txn["สถานะบิล"] == "ยังไม่เปิดบิล")
            _cod_unbilled_custs = set(_dash_txn.loc[_cmask, "ลูกค้า"].unique())

        _slow_ships, _problem_ships, _cod_rows = [], [], []

        for _sh in _dash_ships:
            _cname = ((_sh.get("customers") or {}).get("name") or _sh.get("recipient_name", "—"))
            _sdt   = _parse_sdt(_sh.get("created_at", ""))
            _stat  = _sh.get("delivery_status") or "ไม่มีข้อมูล"
            _its   = _items_str(_sh)
            _date_str = _sdt.astimezone(_BKK).strftime("%d/%m/%y") if _sdt else "—"

            # ── COD ──────────────────────────────────────────────────────
            if float(_sh.get("cod_amount") or 0) > 0:
                _paid = bool(_sh.get("cod_transferred_at"))
                if not _paid:
                    _cod_rows.append({
                        "ลูกค้า":    _cname,
                        "สินค้า":    _its,
                        "COD (฿)":   int(_sh.get("cod_amount") or 0),
                        "Tracking":  _sh.get("tracking_no", "—"),
                        "ขนส่ง":     _sh.get("carrier", ""),
                        "วันที่ส่ง": _date_str,
                        "สถานะ":     "💛 รอรับ COD",
                    })
                elif _cname in _cod_unbilled_custs:
                    _cod_rows.append({
                        "ลูกค้า":    _cname,
                        "สินค้า":    _its,
                        "COD (฿)":   int(_sh.get("cod_amount") or 0),
                        "Tracking":  _sh.get("tracking_no", "—"),
                        "ขนส่ง":     _sh.get("carrier", ""),
                        "วันที่ส่ง": _date_str,
                        "สถานะ":     "✅ รับแล้ว — ยังไม่เปิดบิล",
                    })
                # else: COD รับแล้ว + เปิดบิลแล้ว → ไม่แสดง

            # ── พัสดุมีปัญหา ────────────────────────────────────────────
            if _sh.get("delivery_status") in {"ตีกลับ", "ยกเลิก"}:
                _problem_ships.append({
                    "ลูกค้า":    _cname,
                    "สินค้า":    _its,
                    "Tracking":  _sh.get("tracking_no", "—"),
                    "ขนส่ง":     _sh.get("carrier", ""),
                    "วันที่ส่ง": _date_str,
                    "สถานะ":     _stat,
                })

            # ── พัสดุเกิน 3 วัน (ไม่รวม COD — ติดตามใน section COD แล้ว) ──
            elif (float(_sh.get("cod_amount") or 0) == 0
                    and _sh.get("tracking_no")
                    and _sh.get("delivery_status") not in _TERMINAL_S
                    and _sdt and _sdt < _cutoff):
                _slow_ships.append({
                    "ลูกค้า":       _cname,
                    "สินค้า":       _its,
                    "Tracking":     _sh.get("tracking_no", ""),
                    "ขนส่ง":        _sh.get("carrier", ""),
                    "วันที่ส่ง":    _date_str,
                    "วัน":          (_now_utc - _sdt).days,
                    "สถานะ":        _stat,
                })

        # ── แสดง COD ─────────────────────────────────────────────────────
        if _cod_rows:
            st.divider()
            st.markdown(f"**💛 COD — ติดตามสถานะ ({len(_cod_rows)} รายการ)**")
            _cod_df = pd.DataFrame(_cod_rows)
            st.dataframe(_cod_df.style.format({"COD (฿)": "{:,.0f}"}),
                         use_container_width=True, hide_index=True,
                         height=min(35 * len(_cod_df) + 38, 280))

        # ── แสดงพัสดุล่าช้า ──────────────────────────────────────────────
        if _slow_ships:
            st.divider()
            st.markdown(f"**⏳ พัสดุเกิน 3 วัน ยังไม่ถึง ({len(_slow_ships)} รายการ)**")
            st.dataframe(pd.DataFrame(_slow_ships),
                         use_container_width=True, hide_index=True,
                         height=min(35 * len(_slow_ships) + 38, 300))

        # ── แสดงพัสดุมีปัญหา ─────────────────────────────────────────────
        if _problem_ships:
            st.divider()
            st.markdown(f"**⚠️ พัสดุที่มีปัญหา ตีกลับ/ยกเลิก ({len(_problem_ships)} รายการ)**")
            st.dataframe(pd.DataFrame(_problem_ships),
                         use_container_width=True, hide_index=True,
                         height=min(35 * len(_problem_ships) + 38, 300))

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
    _sub_calc, _sub_ship, _sub_sale = st.tabs(["🔢 คำนวณยอด", "📦 ส่งของ", "📝 บันทึกขาย"])

    with _sub_sale:
        _sale_keys = ["_cust_picked","m_cust_search","_adding_cust",
                      "m_bill","m_pay","m_delivery","m_cod","m_partial_amount",
                      "_cart_base","m_postcode","m_carrier","m_zone","m_iship_note",
                      "r_name","r_phone","r_al","r_dt","r_am","r_pv",
                      "_carrier_sig","_prev_pc","_prev_pay","_prev_shipping_cid","_last_rph_fill",
                      "_r_last_dt","_r_last_pc","_fr_dt","_fr_am","_fr_pv",
                      "_fr_rname","_fr_rphone","_fr_al",
                      "r_dt_searchbox","_r_dt_searchbox_sig",
                      "_prev_cust_search"]
        _cart_ver = st.session_state.get("_cart_version", 0)
        _cart_key = f"m_cart_{_cart_ver}"

        _sale_h1, _sale_h2 = st.columns([6, 1])
        _sale_h1.subheader("บันทึกรายการขาย")
        if st.session_state.get("_do_clear_after_iship") == "sale":
            st.session_state.pop("_do_clear_after_iship", None)
            st.session_state.pop("_iship_carrier_select", None)
            st.session_state.pop("_iship_success_info", None)
            for _k in _sale_keys:
                st.session_state.pop(_k, None)
            for _k in ["r_name","r_phone","r_al","r_dt","r_am","r_pv","m_postcode","m_iship_note"]:
                st.session_state[_k] = ""
            st.session_state.pop("_print_popup", None)
            st.session_state.pop("_popup_show_print", None)
            st.session_state.pop("_sale_last_tracking", None)
            st.session_state.pop(_cart_key, None)
            st.session_state["_cart_version"] = _cart_ver + 1
            st.rerun()

        if _sale_h2.button("🗑️ ล้าง", key="sale_clear_form", use_container_width=True):
            for _k in _sale_keys:
                st.session_state.pop(_k, None)
            st.session_state.pop(_cart_key, None)
            st.session_state["_cart_version"] = _cart_ver + 1
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

            # ── ค้นหาลูกค้าจากเบอร์โทร ─────────────────────────────────────
            mc1, mc2 = st.columns([3, 1])
            with mc1:
                _cust_picked = st.session_state.get("_cust_picked", "")
                if _cust_picked:
                    cp1, cp2 = st.columns([5, 1])
                    cp1.success(f"👤 **{_cust_picked}**")
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
                        st.session_state.pop("m_cust_search", None)
                        st.rerun()
                    m_customer = _cust_picked
                else:
                    _cust_options = ["— เลือกลูกค้า —"] + sorted(customer_map.keys(), key=str.casefold)
                    _cust_sel = st.selectbox("ลูกค้า", _cust_options, key="m_cust_search")
                    m_customer = "— เลือกลูกค้า —"
                    if _cust_sel != "— เลือกลูกค้า —":
                        st.session_state["_cust_picked"] = _cust_sel
                        st.rerun()
                    if st.button("➕ เพิ่มลูกค้าใหม่", key="cust_add_btn", use_container_width=False):
                        st.session_state["_adding_cust"] = ""
                    if st.session_state.get("_adding_cust") is not None and "_adding_cust" in st.session_state:
                        with st.form("add_cust_quick"):
                            _fn = st.text_input("ชื่อลูกค้า")
                            _fp = st.text_input("เบอร์โทร (ถ้ามี)")
                            _fc1, _fc2 = st.columns(2)
                            if _fc1.form_submit_button("💾 บันทึก", type="primary"):
                                _all_cids = [c["id"] for c in db.get_customers()]
                                _cmax = max((int(re.match(r'C-(\d+)', x).group(1))
                                             for x in _all_cids if re.match(r'C-(\d+)', x)), default=0)
                                _new_cid = f"C-{_cmax + 1:03d}"
                                db.upsert_customer({"id": _new_cid,
                                                    "name": _fn.strip(), "phone": _fp.strip()})
                                db.get_customers.clear()
                                st.session_state["_cust_picked"] = _fn.strip()
                                st.session_state.pop("_adding_cust", None)
                                st.rerun()
                            if _fc2.form_submit_button("ยกเลิก"):
                                st.session_state.pop("_adding_cust", None)
                                st.rerun()
            m_date = mc2.date_input("วันที่", value=date.today(), key="m_date")

            # ── รับของจากบิลเก่า ─────────────────────────────────────────────
            _rx_df = None
            _rx_edit = None
            _rx_pay_map = {}
            _rx_total_qty = 0
            _rx_total_pay = 0.0
            _rx_old_items = []
            _pending_rx = []
            _cur_delivery = st.session_state.get("m_delivery", "ฝากของ")
            if m_customer != "— เลือกลูกค้า —" and m_customer in customer_map:
                _recv_cid = customer_map[m_customer]["id"]
                _pending_rx = db.get_pending_receipts_for_customer(_recv_cid)
                if _pending_rx:
                    _rx_label = ("📦 รับของจากบิลเก่า — จะรวมในพัสดุอัตโนมัติ"
                                 if _cur_delivery == "ส่งพัสดุ"
                                 else f"📦 รับของจากบิลเก่า ({sum(p['ค้างรับ'] for p in _pending_rx)} ชิ้นค้างรับ)")
                    with st.expander(_rx_label, expanded=(_cur_delivery == "ส่งพัสดุ")):
                        _prod_map_rx = {p["id"]: p["name"] for p in products}
                        _rx_df = pd.DataFrame([{
                            "สินค้า":     _prod_map_rx.get(p["product_id"], p["product_id"]),
                            "บิล":        p.get("bill_no") or "—",
                            "สถานะจ่าย":  ("จ่ายแล้ว ✅" if p.get("outstanding_amt", 0) <= 0.01
                                           else ("COD 💛" if p.get("pay_status") == "COD"
                                                 else f"ค้างจ่าย {p['outstanding_amt']:,.0f} ฿")),
                            "ค้างรับ":    p["ค้างรับ"],
                            "รับวันนี้":  0,
                            "_tid":       p["id"],
                            "_max":       p["ค้างรับ"],
                            "_owed":      p.get("outstanding_amt", 0.0),
                        } for p in _pending_rx])
                        _rx_edit = st.data_editor(
                            _rx_df[["สินค้า","บิล","สถานะจ่าย","ค้างรับ","รับวันนี้"]],
                            hide_index=True, use_container_width=True,
                            column_config={
                                "รับวันนี้": st.column_config.NumberColumn("รับวันนี้", min_value=0, step=1, width="small"),
                            },
                            disabled=["สินค้า","บิล","สถานะจ่าย","ค้างรับ"],
                            key=f"sale_recv_old_{_recv_cid}",
                        )
                        _rx_recv_rows = []
                        for _ri, _rrow in _rx_edit.iterrows():
                            _qty = min(int(_rrow["รับวันนี้"] or 0), int(_rx_df.iloc[_ri]["_max"]))
                            if _qty > 0:
                                _rx_recv_rows.append({
                                    "สินค้า":    _rx_df.iloc[_ri]["สินค้า"],
                                    "รับวันนี้": _qty,
                                    "จ่ายมา":    0.0,
                                    "_tid":      _rx_df.iloc[_ri]["_tid"],
                                })
                        if _rx_recv_rows:
                            if st.checkbox("✏️ ระบุยอดจ่ายเอง (ถ้าลูกค้าจ่ายไม่ตรงสัดส่วน)", key=f"sale_recv_custom_chk_{_recv_cid}"):
                                _rx_pay_df = pd.DataFrame(_rx_recv_rows)
                                _rx_pay_edit = st.data_editor(
                                    _rx_pay_df[["สินค้า","รับวันนี้","จ่ายมา"]],
                                    hide_index=True, use_container_width=True,
                                    column_config={
                                        "จ่ายมา": st.column_config.NumberColumn(
                                            "จ่ายมา (฿)", min_value=0.0, step=1.0, width="small",
                                            help="ถ้าไม่กรอก ระบบจะคำนวณให้อัตโนมัติตามสัดส่วนที่รับ",
                                        ),
                                    },
                                    disabled=["สินค้า","รับวันนี้"],
                                    key=f"sale_recv_custom_{_recv_cid}",
                                )
                                for _pi, _prow in _rx_pay_edit.iterrows():
                                    _cp = float(_prow.get("จ่ายมา", 0) or 0)
                                    if _cp > 0:
                                        _rx_pay_map[_rx_pay_df.iloc[_pi]["_tid"]] = _cp
                        for _ri, _rrow in _rx_edit.iterrows():
                            _qty = min(int(_rrow["รับวันนี้"] or 0), int(_rx_df.iloc[_ri]["_max"]))
                            if _qty <= 0:
                                continue
                            _owed_this  = float(_rx_df.iloc[_ri]["_owed"])
                            _cap        = int(_rx_df.iloc[_ri]["_max"])
                            _custom_pay = _rx_pay_map.get(_rx_df.iloc[_ri]["_tid"], 0.0)
                            if _custom_pay > 0:
                                _pay = round(min(_custom_pay, _owed_this), 2)
                            else:
                                _pay = round(_owed_this * _qty / _cap, 2) if _owed_this > 0.01 and _cap > 0 else 0.0
                            _rx_total_qty += _qty
                            _rx_total_pay += _pay
                            _rx_old_items.append({
                                "product_id": _pending_rx[_ri]["product_id"],
                                "name":       str(_rx_df.iloc[_ri]["สินค้า"]),
                                "qty":        _qty,
                                "amount":     _pay,
                            })
                        if _rx_total_qty > 0:
                            st.caption(f"📥 รับของเก่าวันนี้: {_rx_total_qty} ชิ้น · ยอดที่จะบันทึกว่าจ่าย {_rx_total_pay:,.0f} ฿")
                        if _cur_delivery == "ส่งพัสดุ":
                            st.caption("ของที่กรอก 'รับวันนี้' จะถูกรวมในพัสดุเมื่อกด บันทึกทั้งหมด · ยอดค้างจะถูกปรับตามสัดส่วน")
                        elif not _cur_delivery:
                            st.caption("⬆️ เลือก การรับ/สถานะของ ด้านบนก่อน")
                        elif _cur_delivery in ("ฝากของ", "รับแล้ว"):
                            if st.button("💾 บันทึกรับของจากบิลเก่า", key="sale_recv_old_btn", type="primary"):
                                _saved_rx  = 0
                                _total_pay = 0.0
                                for _ri, _rrow in _rx_edit.iterrows():
                                    _delta      = int(_rrow["รับวันนี้"] or 0)
                                    _owed_this  = float(_rx_df.iloc[_ri]["_owed"])
                                    _cap        = int(_rx_df.iloc[_ri]["_max"])
                                    _actual_qty = min(_delta, _cap)
                                    if _actual_qty <= 0:
                                        continue
                                    _custom_pay = _rx_pay_map.get(_rx_df.iloc[_ri]["_tid"], 0.0)
                                    if _custom_pay > 0:
                                        _apply_pay = round(min(_custom_pay, _owed_this), 2)
                                    else:
                                        _apply_pay = round(_owed_this * _actual_qty / _cap, 2) if _owed_this > 0.01 and _cap > 0 else 0.0
                                    _etype = "ทั้งคู่" if _apply_pay > 0.01 else "รับของจากบิลเก่า"
                                    db.insert_partial_event({
                                        "id":             str(uuid.uuid4()),
                                        "date":           str(m_date),
                                        "transaction_id": _rx_df.iloc[_ri]["_tid"],
                                        "qty_received":   _actual_qty,
                                        "amount_paid":    _apply_pay,
                                        "event_type":     _etype,
                                    })
                                    _saved_rx += 1
                                    _total_pay += _apply_pay
                                    if _apply_pay > 0.01 and _apply_pay >= _owed_this - 0.01:
                                        db.update_transaction_status(
                                            _rx_df.iloc[_ri]["_tid"], pay_status="จ่ายแล้ว"
                                        )
                                if _saved_rx:
                                    _pay_note = f" · ปรับยอดค้าง ฿{_total_pay:,.0f}" if _total_pay > 0.01 else ""
                                    st.success(f"✅ บันทึกรับของ {_saved_rx} รายการ{_pay_note}")
                                    st.rerun()
                                else:
                                    st.warning("ยังไม่ได้กรอกจำนวนรับ")

            # ── น้ำหนักจากของค้างที่กำลังรับ ─────────────────────────────────
            _prod_weight_map   = {p["id"]: float(p.get("weight_grams") or 0) for p in products}
            _rx_extra_weight_g = 0.0
            _has_rx_action     = False
            if _rx_df is not None and _rx_edit is not None:
                for _ri, _rrow in _rx_edit.iterrows():
                    _qty_now = int(_rrow.get("รับวันนี้") or 0)
                    if _qty_now > 0:
                        _pid = _pending_rx[_ri]["product_id"]
                        _rx_extra_weight_g += _prod_weight_map.get(_pid, 0) * min(_qty_now, int(_rx_df.iloc[_ri]["_max"]))
                        _has_rx_action = True

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
                        st.session_state.pop(_cart_key, None)
                        st.session_state.pop("_cart_base", None)
                        st.rerun()

            st.divider()

            # ── Reset recipient fields when customer changes ─────────────────────
            if m_customer != "— เลือกลูกค้า —":
                if m_customer not in customer_map:
                    st.rerun()  # รอ customers reload หลังเพิ่งเพิ่มใหม่
                _cid_detect = customer_map[m_customer]["id"]
                if st.session_state.get("_prev_shipping_cid") != _cid_detect:
                    st.session_state["_prev_shipping_cid"] = _cid_detect
                    _ca_d = customer_map[m_customer]
                    for _k, _v in [
                        ("r_name",  ""),
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
            if _cart_key not in st.session_state:
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
                    "สินค้า": st.column_config.SelectboxColumn("สินค้า (รหัส — ชื่อ)", options=product_display_keys, required=False, width="large"),
                    "จำนวน": st.column_config.NumberColumn("จำนวน", min_value=0, step=1, width="small"),
                },
                key=_cart_key,
            )

            valid_items = [
                (product_display[row["สินค้า"]], int(row["จำนวน"]), "")
                for _, row in edited_cart.iterrows()
                if str(row.get("สินค้า", "")) in product_display
                and pd.notna(row.get("จำนวน"))
                and int(row.get("จำนวน")) > 0
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
            m_delivery = ms1.radio("การรับ / สถานะของ", _delivery_opts, horizontal=True, key="m_delivery", index=None)
            m_pay  = ms2.radio("สถานะจ่าย", ["ค้างจ่าย", "จ่ายแล้ว", "COD", "จ่ายบางส่วน"], horizontal=True, key="m_pay", index=None)
            m_bill = ms3.radio("สถานะบิล", ["ยังไม่เปิดบิล", "เปิดบิลแล้ว"], horizontal=True, key="m_bill", index=None)

            if not valid_items and _has_rx_action:
                st.caption("ℹ️ มีแต่รับของเก่า ไม่ต้องเลือกสถานะจ่าย/สถานะบิล — ใช้ปุ่ม '💾 บันทึกรับของจากบิลเก่า' ด้านบนแทน")

            m_partial_amount = 0.0
            if m_pay == "จ่ายบางส่วน" and valid_items:
                _partial_base_amt = sum(float(p["price"]) * q for p, q, _ in valid_items)
                m_partial_amount = st.number_input(
                    "💵 จำนวนเงินที่ลูกค้าจ่ายมาแล้ว (บาท)",
                    min_value=0.0, max_value=float(_partial_base_amt), step=1.0,
                    key="m_partial_amount",
                    help=f"ยอดสินค้ารวม {_partial_base_amt:,.0f} ฿",
                )

            m_cod     = (m_pay == "COD")
            m_receipt = "ฝากของ" if m_delivery == "ฝากของ" else "รับของแล้ว"
            m_postcode = ""
            m_zone     = "normal"
            m_carrier  = "Flash Express"
            f_sur = s_sur = 0
            f_zone = s_zone = ""

            if m_delivery == "ส่งพัสดุ":
                if "_staged_pc" in st.session_state:
                    st.session_state["m_postcode"] = st.session_state.pop("_staged_pc")
                m_postcode = st.session_state.get("m_postcode", "")



                fees = carrier_fees(0, m_postcode.strip()) if len(m_postcode.strip()) == 5 else None
                f_sur  = fees["Flash Express"]["surcharge"] if fees else 0
                s_sur  = fees["SPX Express"]["surcharge"]   if fees else 0
                f_zone = fees["Flash Express"]["zone"]      if fees else ""
                s_zone = fees["SPX Express"]["zone"]        if fees else ""
                if fees and m_postcode != st.session_state.get("_prev_pc", ""):
                    st.session_state["m_carrier"] = _pick_carrier(m_postcode)
                    st.session_state["_prev_pc"]  = m_postcode
                if "_staged_carrier" in st.session_state:
                    st.session_state["m_carrier"] = st.session_state.pop("_staged_carrier")
                m_carrier = st.session_state.get("m_carrier", "Flash Express")
                m_iship_note = st.text_input("📝 หมายเหตุ iShip (ไม่บังคับ)", placeholder="เช่น ฝากสินค้าเพิ่ม...", key="m_iship_note")

                # ── ที่อยู่ผู้รับ ─────────────────────────────────────────────
                _cid = customer_map[m_customer]["id"] if m_customer != "— เลือกลูกค้า —" else "no_cust"
                with st.expander("📦 ที่อยู่ผู้รับ", expanded=(m_delivery == "ส่งพัสดุ")):
                        # ── quick-select ที่อยู่เดิมของลูกค้า ──────────────────
                        if m_customer != "— เลือกลูกค้า —":
                            try:
                                _saved_addrs = db.get_customer_addresses(customer_id=_cid)
                            except Exception:
                                _saved_addrs = []
                            if _saved_addrs:
                                with st.expander(f"⚡ เลือกที่อยู่เดิม ({len(_saved_addrs)})", expanded=False):
                                    for _sa in _saved_addrs:
                                        _sa_label = f"{_sa.get('recipient_name','')} · {_sa.get('phone','')} · {_sa.get('address_line','')} {_sa.get('district','')} {_sa.get('amphure','')} {_sa.get('province','')} {_sa.get('postal_code','')}"
                                        if st.button(_sa_label, key=f"qa_{_sa['id']}", use_container_width=True):
                                            _qa_dt = (_sa.get("district", "") or "").strip()
                                            _qa_pc = (_sa.get("postal_code", "") or "").strip()
                                            st.session_state["_fr_rname"] = _sa.get("recipient_name", "")
                                            st.session_state["_fr_rphone"]= _sa.get("phone", "")
                                            st.session_state["_fr_al"]  = _sa.get("address_line", "")
                                            st.session_state["_fr_dt"]  = _qa_dt
                                            st.session_state["_fr_am"]  = _sa.get("amphure", "")
                                            st.session_state["_fr_pv"]  = _sa.get("province", "")
                                            st.session_state["_staged_pc"]     = _qa_pc
                                            st.session_state["_r_last_dt"]     = _qa_dt
                                            st.session_state["_r_last_pc"]     = _qa_pc
                                            st.session_state["_last_rph_fill"] = _sa.get("phone", "")
                                            st.rerun()
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
                                st.session_state["_fr_rname"]  = _parsed.get("dst_name", "")
                                st.session_state["_fr_rphone"] = _parsed.get("dst_phone", "")
                                st.session_state["_fr_al"]     = _parsed.get("address_line", "")
                                st.session_state["_fr_dt"]     = _parsed.get("district", "")
                                st.session_state["_fr_am"]     = _parsed.get("amphure", "")
                                st.session_state["_fr_pv"]     = _parsed.get("province", "")
                                st.session_state["_staged_pc"] = _parsed.get("zipcode", "")
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
                        # apply staged address fill ก่อน render ทุก widget
                        for _fk, _wk in [("_fr_rname","r_name"),("_fr_rphone","r_phone"),("_fr_al","r_al"),
                                          ("_fr_dt","r_dt"),("_fr_am","r_am"),("_fr_pv","r_pv")]:
                            if _fk in st.session_state:
                                st.session_state[_wk] = st.session_state.pop(_fk)
                        col_a, col_b = st.columns(2)
                        r_name      = col_a.text_input("ชื่อผู้รับ",   key="r_name")
                        r_phone     = col_b.text_input("เบอร์โทร",     key="r_phone")
                        r_addr_line = st.text_input("บ้านเลขที่/ถนน", key="r_al")
                        col_c, col_d, col_e = st.columns(3)
                        with col_c:
                            r_district = _tambon_selectbox("r_dt", "r_am", "r_pv", "m_postcode", "r_dt_searchbox")
                        r_amphure   = col_d.text_input("อำเภอ/เขต",    key="r_am")
                        r_province  = col_e.selectbox("จังหวัด", [""] + _PROVINCES, key="r_pv")
                        m_postcode  = st.text_input("รหัสไปรษณีย์", max_chars=5,
                                                    key="m_postcode", placeholder="เช่น 10400")
                        _postcode_suggest(m_postcode, "r_dt", "r_am", "r_pv",
                                          "r_dt_searchbox", "r_pc_suggest")
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
                             for p, q, _ in valid_items) + _rx_extra_weight_g + 500) / 1000
                _optimal = _pick_carrier(m_postcode.strip(), _w_kg)
                _sig = (m_postcode.strip(), round(_w_kg, 2))
                if _sig != st.session_state.get("_carrier_sig"):
                    st.session_state["_carrier_sig"]    = _sig
                    st.session_state["_staged_carrier"] = _optimal
                    st.rerun()

            COD_FEE_RATE = 0.0321  # 3.21%

            if m_delivery == "ส่งพัสดุ" and (f_zone or s_zone):
                _zone_label = f_zone or s_zone
                st.warning(f"📍 {_zone_label} — มีค่าส่งเพิ่ม Flash Express +{f_sur}฿ / SPX Express +{s_sur}฿")

            total_amt = 0.0; total_pv = 0.0; ship_fee = 0.0; cod_fee = 0.0; collect = 0.0
            if valid_items or (_has_rx_action and m_delivery == "ส่งพัสดุ"):
                total_amt    = sum(float(p["price"]) * q for p, q, _ in valid_items)
                total_pv     = sum(float(p["points_per_unit"]) * q for p, q, _ in valid_items)
                total_weight = sum(float(p.get("weight_grams") or 0) * q for p, q, _ in valid_items) + _rx_extra_weight_g
                if valid_items:
                    st.success("🛒 " + "  |  ".join(f"**{p['id']}** ×{q}" for p, q, _ in valid_items))
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
                        vm3.metric("💰 ยอดเก็บ (อัตโนมัติ)", f"{collect:,.0f} ฿")
                        vm4.metric("💸 ค่า COD",       f"{cod_fee:,.2f} ฿")
                        vm5.metric("✅ ได้รับจริง",    f"{net_recv:,.2f} ฿")
                        vm6.metric("⚖️ น้ำหนัก",      f"{(total_weight/1000):.2f} kg")
                        vm7.metric("PV รวม",           f"{total_pv:.0f}")
                        _cod_auto = int(ceil(collect))
                        _cod_custom = st.number_input(
                            "💰 ยอด COD ที่ต้องเก็บ (แก้ได้)",
                            min_value=0, value=_cod_auto, step=1,
                            key="m_cod_custom",
                            help="ค่า default = คำนวณอัตโนมัติ ปรับได้ถ้าต้องการเก็บยอดอื่น",
                        )
                        collect = float(_cod_custom)
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
                    if valid_items:
                        vm1, vm2, vm3 = st.columns(3)
                        vm1.metric("ยอดรวม",   f"{total_amt:,.0f} ฿")
                        vm2.metric("PV รวม",   f"{total_pv:.0f}")
                        vm3.metric("รายการ",   f"{len(valid_items)} สินค้า")

            if _rx_total_pay > 0:
                st.caption(
                    f"💰 ยอดรวมทั้งหมด (ส่งบิลลูกค้า): เก่า {_rx_total_pay:,.0f} ฿ "
                    f"+ ใหม่ {total_amt:,.0f} ฿ = **{(total_amt + _rx_total_pay):,.0f} ฿**"
                )

            m_errors = []
            if m_customer == "— เลือกลูกค้า —": m_errors.append("⚠️ ยังไม่ได้เลือกลูกค้า")
            if not valid_items: m_errors.append("⚠️ ยังไม่ได้กรอกสินค้า")
            if m_pay == "จ่ายบางส่วน" and valid_items and m_partial_amount <= 0:
                m_errors.append("⚠️ กรุณาระบุจำนวนเงินที่จ่ายมา (ต้องมากกว่า 0)")
            if m_delivery is None: m_errors.append("⚠️ ยังไม่ได้เลือก การรับ/สถานะของ")
            if valid_items:
                if m_pay is None:  m_errors.append("⚠️ ยังไม่ได้เลือก สถานะจ่าย")
                if m_bill is None: m_errors.append("⚠️ ยังไม่ได้เลือก สถานะบิล")
            if m_errors:
                st.warning("  \n".join(m_errors))

            if not m_errors and valid_items:
                _pay_color   = {"ค้างจ่าย": "🔴", "จ่ายแล้ว": "🟢", "COD": "🟡", "จ่ายบางส่วน": "🟣"}.get(m_pay or "", "⚪")
                _deliv_color = {"ส่งพัสดุ": "🚚", "ฝากของ": "📦", "รับแล้ว": "✅"}.get(m_delivery or "", "⚪")
                _bill_color  = "🟠" if m_bill == "ยังไม่เปิดบิล" else "🟢"
                _carrier_tag = f" · {m_carrier}" if m_delivery == "ส่งพัสดุ" else ""
                _pay_tag     = f" · {_pay_color} {m_pay}" if m_pay else ""
                _bill_tag    = f" · {_bill_color} {m_bill}" if m_bill else ""
                st.info(f"📋 **{m_customer}** · {_deliv_color} {m_delivery}{_pay_tag}{_bill_tag}{_carrier_tag}")

            if st.button("💾 บันทึกทั้งหมด", type="primary", use_container_width=True, key="m_submit",
                         disabled=bool(m_errors)):
                customer     = customer_map[m_customer]
                is_shipping  = m_delivery == "ส่งพัสดุ"
                total_w_g    = sum(float(p.get("weight_grams") or 0) * q for p, q, _ in valid_items) + _rx_extra_weight_g
                if is_shipping:
                    fees_save = carrier_fees(total_w_g, m_postcode)
                    ship_fee  = fees_save[m_carrier]["total"]
                    zone_name = fees_save[m_carrier]["zone"]
                    zone_tag  = f"|{zone_name}" if zone_name else ""
                    delivery_tag = f"[ส่งพัสดุ|{m_carrier}|{m_postcode}|น้ำหนัก={total_w_g/1000:.2f}kg|ค่าส่ง={ship_fee:.0f}{zone_tag}]"
                else:
                    ship_fee = 0
                    delivery_tag = ""
                # ── บันทึกสินค้าใหม่ (ถ้ามี) ──────────────────────────────────
                if valid_items:
                    actual_pay  = "COD" if m_cod else ("ค้างจ่าย" if m_pay == "จ่ายบางส่วน" else m_pay)
                    receive_now = m_receipt == "รับของแล้ว"
                    if m_cod:
                        _base_cod  = sum(float(p["price"]) * q for p, q, _ in valid_items) + ship_fee
                        cod_amount = round(_base_cod * COD_FEE_RATE, 2)
                        collect    = _base_cod + cod_amount
                        _cod_custom_val = st.session_state.get("m_cod_custom", 0)
                        if _cod_custom_val and int(_cod_custom_val) != int(ceil(collect)):
                            collect = float(_cod_custom_val)
                        cod_tag    = f"[COD|ยอดเก็บ={collect:.0f}฿|ค่าธรรมเนียม={cod_amount:.2f}฿|ยอดรับจริง={_base_cod:.2f}฿]"
                    else:
                        cod_amount = 0
                        collect    = total_amt + ship_fee
                        cod_tag    = ""
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
                    if m_pay == "จ่ายบางส่วน" and m_partial_amount > 0:
                        _alloc_left = m_partial_amount
                        for _i, _row in enumerate(_m_batch):
                            if _i == len(_m_batch) - 1:
                                _alloc = round(_alloc_left, 2)
                            else:
                                _alloc = round(m_partial_amount * _row["total_amount"] / total_amt, 2)
                                _alloc_left -= _alloc
                            if _alloc > 0:
                                db.insert_partial_event({
                                    "id": str(uuid.uuid4()),
                                    "date": str(m_date),
                                    "transaction_id": _row["id"],
                                    "qty_received": 0,
                                    "amount_paid": _alloc,
                                    "event_type": "จ่ายเงิน",
                                })
                    msg = f"✅ บันทึก {len(valid_items)} รายการ"
                    if is_shipping: msg += f" | 🚚 ค่าส่ง {ship_fee:.0f} ฿"
                    if m_cod:       msg += f" | 💸 ค่า COD {cod_amount:.2f} ฿"
                    if m_pay == "จ่ายบางส่วน" and m_partial_amount > 0:
                        msg += f" | 💵 จ่ายมาแล้ว {m_partial_amount:,.0f} ฿ (ค้าง {total_amt - m_partial_amount:,.0f} ฿)"
                else:
                    actual_pay = None
                    bill_no    = None
                    cod_amount = 0
                    collect    = ship_fee
                    msg        = "✅ ส่งของค้างเก่า"
                    if is_shipping: msg += f" | 🚚 ค่าส่ง {ship_fee:.0f} ฿"
                # ── iShip + บันทึกรับของเก่า/จ่ายเงิน ─────────────────────────
                if is_shipping and r_addr_line:
                    _old_ship_items = []
                    if _rx_df is not None and _rx_edit is not None:
                        for _ri, _rrow in _rx_edit.iterrows():
                            _delta     = int(_rrow["รับวันนี้"] or 0)
                            _owed_this = float(_rx_df.iloc[_ri]["_owed"])
                            _cap       = int(_rx_df.iloc[_ri]["_max"])
                            _recv      = min(max(_delta, 0), _cap)
                            _custom_pay = _rx_pay_map.get(_rx_df.iloc[_ri]["_tid"], 0.0)
                            if _custom_pay > 0:
                                _apply_pay = round(min(_custom_pay, _owed_this), 2)
                            else:
                                _apply_pay = round(_owed_this * _recv / _cap, 2) if _owed_this > 0.01 and _cap > 0 and _recv > 0 else 0.0
                            if _recv <= 0:
                                continue
                            _etype = "ทั้งคู่" if _apply_pay > 0.01 else "รับของ"
                            db.insert_partial_event({
                                "id":             str(uuid.uuid4()),
                                "date":           str(m_date),
                                "transaction_id": _rx_df.iloc[_ri]["_tid"],
                                "qty_received":   _recv,
                                "amount_paid":    _apply_pay,
                                "event_type":     _etype,
                            })
                            if _apply_pay > 0.01 and _apply_pay >= _owed_this - 0.01:
                                db.update_transaction_status(_rx_df.iloc[_ri]["_tid"], pay_status="จ่ายแล้ว")
                            _old_ship_items.append({
                                "product_id": _pending_rx[_ri]["product_id"],
                                "name":       str(_rrow["สินค้า"]),
                                "qty":        _recv,
                            })
                    _new_items = [{"product_id": p["id"], "name": p["name"], "qty": qty}
                                  for p, qty, _ in valid_items]
                    _all_items = _new_items + _old_ship_items
                    _prod_codes  = " ".join(f"{p['id'].upper()}-{qty}" for p, qty, _ in valid_items)
                    _iship_args = {
                        "dst_name":    r_name or customer["name"],
                        "dst_phone":   r_phone,
                        "address_line": r_addr_line,
                        "district":    r_district,
                        "amphure":     r_amphure,
                        "province":    r_province,
                        "zipcode":     m_postcode,
                        "weight_kg":   (total_w_g + 500) / 1000,
                        "cod_amount":  ceil(collect) if m_cod else 0,
                        "carrier":      m_carrier,
                        "remark":       " ".join(filter(None, [customer['name'], _prod_codes, st.session_state.get("m_iship_note","").strip()])),
                        "item_detail":  ", ".join(f"{it['name']} x{it['qty']}" for it in _all_items),
                        "products":     [{"name": it["name"], "qty": it["qty"],
                                          "price": float(next((p["price"] for p, q, _ in valid_items if p["id"] == it["product_id"]), 0))}
                                         for it in _all_items],
                        "sender_name":  customer["name"],
                        "_items":       _all_items,
                        "_customer_id": customer["id"],
                    }
                    if iship_api.is_configured():
                        st.session_state["_iship_carrier_select"] = {
                            "tab":          "sale",
                            "postcode":     m_postcode,
                            "weight_kg":    (total_w_g + 500) / 1000,
                            "dst_name":     r_name or customer["name"],
                            "dst_phone":    r_phone,
                            "address_line": r_addr_line,
                            "district":     r_district,
                            "amphure":      r_amphure,
                            "province":     r_province,
                            "cod_amount":   ceil(collect) if m_cod else 0,
                            "items":        _all_items,
                            "customer_id":  customer["id"],
                            "customer_name":customer["name"],
                            "shipment_id":  "",
                            "remark":       "",
                        }
                        pass  # _iship_carrier_select set above — dialog triggers automatically
                elif not is_shipping and _rx_df is not None and _rx_edit is not None:
                    # บันทึกรับของเก่า สำหรับ รับแล้ว / ฝากของ (จ่ายอัตโนมัติตามสัดส่วน)
                    for _ri, _rrow in _rx_edit.iterrows():
                        _delta      = int(_rrow["รับวันนี้"] or 0)
                        _owed_this  = float(_rx_df.iloc[_ri]["_owed"])
                        _cap        = int(_rx_df.iloc[_ri]["_max"])
                        _actual_qty = min(max(_delta, 0), _cap)
                        if _actual_qty <= 0:
                            continue
                        _custom_pay = _rx_pay_map.get(_rx_df.iloc[_ri]["_tid"], 0.0)
                        if _custom_pay > 0:
                            _apply_pay = round(min(_custom_pay, _owed_this), 2)
                        else:
                            _apply_pay = round(_owed_this * _actual_qty / _cap, 2) if _owed_this > 0.01 and _cap > 0 else 0.0
                        _etype = "ทั้งคู่" if _apply_pay > 0.01 else "รับของจากบิลเก่า"
                        db.insert_partial_event({
                            "id":             str(uuid.uuid4()),
                            "date":           str(m_date),
                            "transaction_id": _rx_df.iloc[_ri]["_tid"],
                            "qty_received":   _actual_qty,
                            "amount_paid":    _apply_pay,
                            "event_type":     _etype,
                        })
                        if _apply_pay > 0.01 and _apply_pay >= _owed_this - 0.01:
                            db.update_transaction_status(_rx_df.iloc[_ri]["_tid"], pay_status="จ่ายแล้ว")
                # ── print popup (เฉพาะเมื่อมีสินค้าใหม่) ──────────────────────
                if valid_items:
                    st.session_state["_print_popup"] = {
                        "customer_name": customer["name"],
                        "customer_id":   customer["id"],
                        "bill_date":     str(m_date),
                        "bill_no":       bill_no,
                        "items": [{"product_id": p["id"], "name": p["name"], "qty": qty,
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
                        "old_items":   _rx_old_items,
                        "old_total":   _rx_total_pay,
                        "grand_total": total_amt + _rx_total_pay,
                    }
                # ล้างฟอร์มสำหรับลูกค้าถัดไป
                for _k in _sale_keys:
                    st.session_state.pop(_k, None)
                st.session_state.pop(_cart_key, None)
                st.session_state["_cart_version"] = _cart_ver + 1
                st.rerun()
            elif m_errors and any(e != "กรอกสินค้าและจำนวนอย่างน้อย 1 รายการ" for e in m_errors):
                st.caption("⚠️ " + " | ".join(m_errors))

            # ── ปุ่มรับแต่ของเก่า (เฉพาะ ส่งพัสดุ + ไม่มีสินค้าใหม่) ────────
            if (m_delivery == "ส่งพัสดุ" and not valid_items and _has_rx_action
                    and m_customer != "— เลือกลูกค้า —"):
                st.divider()
                _rxo_errors = []
                if not r_addr_line: _rxo_errors.append("⚠️ ยังไม่ได้กรอกที่อยู่")
                if not m_postcode:  _rxo_errors.append("⚠️ ยังไม่ได้กรอกรหัสไปรษณีย์")
                if _rxo_errors:
                    st.warning("  \n".join(_rxo_errors))
                if st.button("🚚 รับแต่ของเก่า", type="primary", use_container_width=True,
                             key="m_rxonly_submit", disabled=bool(_rxo_errors)):
                    _rxo_customer   = customer_map[m_customer]
                    _rxo_weight_g   = _rx_extra_weight_g
                    _rxo_fees       = carrier_fees(_rxo_weight_g, m_postcode)
                    _rxo_ship_fee   = _rxo_fees[m_carrier]["total"]
                    _rxo_zone       = _rxo_fees[m_carrier]["zone"]
                    _rxo_zone_tag   = f"|{_rxo_zone}" if _rxo_zone else ""
                    _rxo_items      = []
                    for _ri, _rrow in _rx_edit.iterrows():
                        _delta     = int(_rrow["รับวันนี้"] or 0)
                        _owed_this = float(_rx_df.iloc[_ri]["_owed"])
                        _cap       = int(_rx_df.iloc[_ri]["_max"])
                        _recv      = min(max(_delta, 0), _cap)
                        if _recv <= 0:
                            continue
                        _custom_pay = _rx_pay_map.get(_rx_df.iloc[_ri]["_tid"], 0.0)
                        if _custom_pay > 0:
                            _apply_pay = round(min(_custom_pay, _owed_this), 2)
                        else:
                            _apply_pay = round(_owed_this * _recv / _cap, 2) if _owed_this > 0.01 and _cap > 0 else 0.0
                        _etype     = "ทั้งคู่" if _apply_pay > 0.01 else "รับของ"
                        db.insert_partial_event({
                            "id":             str(uuid.uuid4()),
                            "date":           str(m_date),
                            "transaction_id": _rx_df.iloc[_ri]["_tid"],
                            "qty_received":   _recv,
                            "amount_paid":    _apply_pay,
                            "event_type":     _etype,
                        })
                        if _apply_pay > 0.01 and _apply_pay >= _owed_this - 0.01:
                            db.update_transaction_status(_rx_df.iloc[_ri]["_tid"], pay_status="จ่ายแล้ว")
                        _rxo_items.append({
                            "product_id": _pending_rx[_ri]["product_id"],
                            "name":       str(_rrow["สินค้า"]),
                            "qty":        _recv,
                        })
                    if iship_api.is_configured() and _rxo_items:
                        st.session_state["_iship_carrier_select"] = {
                            "tab":          "sale",
                            "postcode":     m_postcode,
                            "weight_kg":    (_rxo_weight_g + 500) / 1000,
                            "dst_name":     r_name or _rxo_customer["name"],
                            "dst_phone":    r_phone,
                            "address_line": r_addr_line,
                            "district":     r_district,
                            "amphure":      r_amphure,
                            "province":     r_province,
                            "cod_amount":   0,
                            "items":        _rxo_items,
                            "customer_id":  _rxo_customer["id"],
                            "customer_name":_rxo_customer["name"],
                            "shipment_id":  "",
                            "remark":       f"[ส่งพัสดุ|{m_carrier}|{m_postcode}|น้ำหนัก={_rxo_weight_g/1000:.2f}kg|ค่าส่ง={_rxo_ship_fee:.0f}{_rxo_zone_tag}]",
                        }
                    st.rerun()

            # ── ผลลัพธ์หลังบันทึก (popup + iShip) ─────────────────────────
            if st.session_state.get("_print_popup"):
                _pd = st.session_state["_print_popup"]
                _old_items  = _pd.get("old_items", [])
                _old_total  = _pd.get("old_total", 0)
                _grand = _pd.get("collect", _pd["total_amt"]) + _old_total
                _items_txt = ", ".join(f"{it['product_id']} {it['name']} ×{it['qty']}" for it in _pd.get("items", []))
                if _old_items:
                    _items_txt += "  ·  เก่า: " + ", ".join(f"{it['product_id']} {it['name']} ×{it['qty']}" for it in _old_items)
                with st.container(border=True):
                    _pb1, _pb2, _pb3, _pb4, _pb5 = st.columns([4, 3, 1, 1, 1])
                    _pb1.markdown(
                        f"✅ **{_pd['customer_name']}** — บิล `{_pd['bill_no']}` | {_pd['bill_date']}"
                        f"\n\n_{_items_txt}_"
                    )
                    if _old_items:
                        _pb2.markdown(
                            f"💰 เก่า {_old_total:,.0f} + ใหม่ {_pd['total_amt']:,.0f} = **{_grand:,.0f} ฿**"
                            f" &nbsp;&nbsp; ⭐ PV {_pd['total_pv']:.0f}"
                        )
                    else:
                        _pb2.markdown(
                            f"💰 **{_grand:,.0f} ฿** &nbsp;&nbsp; ⭐ PV {_pd['total_pv']:.0f}"
                        )
                    _popup_line_uid = db.get_customer_line_user_id(_pd.get("customer_id", "")) if _pd.get("customer_id") else ""
                    if _pb3.button("📨 LINE", key="popup_line_btn",
                                   disabled=not bool(_popup_line_uid),
                                   use_container_width=True,
                                   help="ส่งสรุปบิลให้ลูกค้าใน LINE" if _popup_line_uid else "ลูกค้าไม่มี LINE ID"):
                        _line_items = [{"name": f"{it['product_id']} {it['name']}", "qty": it["qty"], "total": it["total"]}
                                       for it in _pd.get("items", [])]
                        _line_items += [{"name": f"{it['product_id']} {it['name']} (เก่า)", "qty": it["qty"], "total": it["amount"]}
                                        for it in _old_items]
                        _res = line_api.push_bill_summary(
                            _popup_line_uid, _pd["customer_name"], _pd["bill_no"],
                            _line_items, _pd["total_amt"] + _old_total, _pd["pay_status"]
                        )
                        if _res["ok"]:
                            st.toast("✅ ส่ง LINE แล้ว")
                        else:
                            st.error(f"LINE error: {_res['error']}")
                    if _pb4.button("🖨️ พิมพ์", key="popup_print_btn", use_container_width=True):
                        st.session_state["_popup_show_print"] = not st.session_state.get("_popup_show_print", False)
                    if _pb5.button("✕ ปิด", key="popup_close", use_container_width=True):
                        del st.session_state["_print_popup"]
                        st.session_state.pop("_popup_show_print", None)
                        st.rerun()

                if st.session_state.get("_popup_show_print") and st.session_state.get("_print_popup"):
                    _pit = _pd.get("items", [])
                    _rows_html = "".join(
                        f"<tr><td style='font-size:11px;color:#666'>{it.get('product_id','')}</td>"
                        f"<td>{it['name']}</td><td style='text-align:center'>{it['qty']}</td>"
                        f"<td style='text-align:right'>{float(it['price']):,.0f}</td>"
                        f"<td style='text-align:right'>{float(it['total']):,.0f}</td></tr>"
                        for it in _pit
                    )
                    _old_rows_html = "".join(
                        f"<tr><td style='font-size:11px;color:#666'>{it['product_id']}</td>"
                        f"<td>{it['name']} (เก่า)</td><td style='text-align:center'>{it['qty']}</td>"
                        f"<td></td><td style='text-align:right'>{float(it['amount']):,.0f}</td></tr>"
                        for it in _old_items
                    )
                    _ship_row = f"<tr><td></td><td>ค่าส่ง ({_pd.get('carrier','')})</td><td></td><td></td><td style='text-align:right'>{_pd['ship_fee']:,.0f}</td></tr>" if _pd.get("ship_fee", 0) > 0 else ""
                    _cod_row  = f"<tr><td></td><td>COD (3%)</td><td></td><td></td><td style='text-align:right'>{_pd['cod_fee']:,.0f}</td></tr>" if _pd.get("is_cod") else ""
                    _bill_html_popup = f"""<!DOCTYPE html><html><head><meta charset='UTF-8'>
<style>
html,body{{background:#fff!important;color:#000!important;margin:0;padding:0}}
body{{font-family:'Sarabun',sans-serif;padding:14px;font-size:13px}}
h3{{margin:0 0 4px;font-size:15px}}
.info{{font-size:12px;margin-bottom:8px;color:#333}}
table{{width:100%;border-collapse:collapse;margin:6px 0;font-size:12px}}
th{{background:#333;color:#fff;padding:4px 6px;text-align:left}}
td{{padding:3px 6px;border-bottom:1px solid #ddd;color:#000}}
.total{{font-weight:bold;font-size:14px;text-align:right;margin-top:6px}}
.btn{{display:inline-block;margin:0 0 10px;padding:5px 16px;background:#333;color:#fff;border:none;cursor:pointer;border-radius:4px;font-size:12px}}
@media print{{.btn{{display:none}}@page{{size:A5;margin:8mm}}}}
</style></head><body style="background:#fff;color:#000">
<button class='btn' onclick='window.print()'>🖨️ พิมพ์บิล</button>
<h3>TBY — ใบเสร็จรับเงิน</h3>
<div class='info'>บิล: <b>{_pd['bill_no']}</b> | วันที่: {_pd['bill_date']}<br>
ลูกค้า: <b>{_pd['customer_name']}</b> | สถานะ: {_pd['pay_status']}</div>
<table><tr><th>รหัส</th><th>สินค้า</th><th>จำนวน</th><th>ราคา/ชิ้น</th><th>รวม</th></tr>
{_rows_html}{_old_rows_html}{_ship_row}{_cod_row}
</table>
<div class='total'>ยอดรวม: {_grand:,.0f} ฿ &nbsp;|&nbsp; PV: {_pd['total_pv']:.0f}</div>
</body></html>"""
                    components.html(_bill_html_popup, height=420, scrolling=True)

            if st.session_state.get("_sale_last_tracking"):
                _slt = st.session_state["_sale_last_tracking"]
                _stc1, _stc2 = st.columns([5, 1])
                _stc1.success(f"✅ iShip สำเร็จ — Tracking: **{_slt}**")
                if _stc2.button("✕", key="sale_clear_tracking", use_container_width=True):
                    del st.session_state["_sale_last_tracking"]
                    st.rerun()

            if st.session_state.get("_iship_pending"):
                _p = st.session_state["_iship_pending"]
                addr_full = f"{_p['address_line']} {_p['district']} {_p['amphure']} {_p['province']} {_p['zipcode']}".strip()
                _sender_name = _p.get("sender_name", "")
                if _p.get("_auto_error"):
                    st.error(f"❌ iShip ล้มเหลว: {_p['_auto_error']} — กรุณาลองใหม่")
                st.info(
                    f"{'👤 ลูกค้า: **' + _sender_name + '**  →  ' if _sender_name else ''}"
                    f"📦 **{_p['dst_name']}**  {_p['dst_phone']}\n\n"
                    f"{addr_full}\n\n"
                    f"น้ำหนัก {_p['weight_kg']:.2f} kg  |  COD {_p['cod_amount']:,} ฿"
                )
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
                            _rd = resp.get("data") or {}
                            tracking = (_rd.get("tracking_code") or _rd.get("tracking_number")
                                        or resp.get("tracking_code") or resp.get("tracking_number") or "")
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
                                    "cod_amount":     _p.get("cod_amount", 0),
                                    "notes":          "",
                                    "source":         "sale",
                                })
                            except Exception:
                                pass
                            _cid_s2 = _p.get("_customer_id", "")
                            _luid_s2 = db.get_customer_line_user_id(_cid_s2) if (tracking and _cid_s2) else ""
                            del st.session_state["_iship_pending"]
                            st.session_state["_iship_success_info"] = {
                                "tracking":      tracking,
                                "tab":           "sale",
                                "customer":      _p.get("sender_name",""),
                                "dst_name":      _p.get("dst_name",""),
                                "dst_phone":     _p.get("dst_phone",""),
                                "address":       addr_full,
                                "carrier":       _carrier_choice,
                                "weight_kg":     _p.get("weight_kg",0),
                                "cod_amount":    _p.get("cod_amount",0),
                                "items":         _p.get("_items",[]),
                                "line_user_id":  _luid_s2,
                                "shipment_id":   "",
                            }
                            st.session_state["_open_success_dialog"] = True
                            st.rerun()
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

    # ─────────────────────────────────────────────────────────────────────────────

    with _sub_ship:
        _sp_av   = st.session_state.get("_sp_addr_ver", 0)
        _sp_keys = [f"sp_rname_v{_sp_av}",f"sp_rphone_v{_sp_av}",f"sp_al_v{_sp_av}",
                    f"sp_dt_v{_sp_av}",f"sp_am_v{_sp_av}",f"sp_pv_v{_sp_av}",
                    f"sp_dt_searchbox_v{_sp_av}",f"_sp_dt_searchbox_v{_sp_av}_sig",
                    f"sp_pc_v{_sp_av}",f"sp_track_v{_sp_av}",f"sp_notes_v{_sp_av}",
                    "_sp_cust_picked",f"sp_cust_search_v{_sp_av}",
                    "_sp_last_dt","_sp_last_pc","_fsp_dt","_fsp_am","_fsp_pv","_fsp_pc",
                    "_fsp_rname","_fsp_rphone","_fsp_al",
                    "sp_carrier","_sp_prev_pc","_sp_staged_carrier","sp_date",
                    "_sp_cart_ver","_sp_cart_base","_sp_quick_items","sp_q_text",
                    "_sp_last_rph_fill","_sp_parse_open","_sp_carrier_sig",
                    "_sp_linked_bill_no","_sp_linked_bill_txns","sp_link_search",
                    "_sp_adding_cust","_sp_prev_cust_search"]
        _sp_cart_ver_now = st.session_state.get("_sp_cart_ver", 0)

        _sc1, _sc2 = st.columns([6, 1])
        _sc1.subheader("บันทึกการส่งของ")
        if st.session_state.get("_do_clear_after_iship") == "ship":
            st.session_state.pop("_do_clear_after_iship", None)
            st.session_state.pop("_iship_carrier_select", None)
            st.session_state.pop("_iship_success_info", None)
            for _k in _sp_keys:
                st.session_state.pop(_k, None)
            st.session_state["_sp_addr_ver"] = _sp_av + 1
            st.session_state.pop("_sp_last_tracking", None)
            st.session_state.pop(f"sp_cart_{_sp_cart_ver_now}", None)
            st.session_state["_sp_cart_ver"] = _sp_cart_ver_now + 1
            st.rerun()

        if _sc2.button("🗑️ ล้าง", key="sp_clear_form", use_container_width=True):
            for _k in _sp_keys:
                st.session_state.pop(_k, None)
            st.session_state.pop("_sp_cart_base", None)
            st.session_state["_sp_addr_ver"] = _sp_av + 1
            st.session_state.pop(f"sp_cart_{_sp_cart_ver_now}", None)
            st.session_state["_sp_cart_ver"] = _sp_cart_ver_now + 1
            st.rerun()

        _sp = db.get_products()
        _sc = db.get_customers()
        _sc_map = {c["name"]: c for c in _sc}

        # ── เลือกลูกค้า + วันที่ ─────────────────────────────────────────
        _sp_c1, _sp_c2 = st.columns([3, 1])
        with _sp_c1:
            _sp_picked = st.session_state.get("_sp_cust_picked", "")
            if _sp_picked:
                _spx, _spy = st.columns([5, 1])
                _spx.success(f"👤 **{_sp_picked}**")
                if _spy.button("✕ เปลี่ยน", key="sp_cust_clear"):
                    st.session_state.pop("_sp_cust_picked", None)
                    st.session_state.pop("sp_cust_search", None)
                    st.rerun()
                _sp_cust = _sp_picked
            else:
                _sp_options = ["— เลือกลูกค้า —"] + sorted(_sc_map.keys(), key=str.casefold)
                _sp_sel = st.selectbox("ลูกค้า", _sp_options, key=f"sp_cust_search_v{_sp_av}")
                _sp_cust = "— เลือกลูกค้า —"
                if _sp_sel != "— เลือกลูกค้า —":
                    st.session_state["_sp_cust_picked"] = _sp_sel
                    st.rerun()
                if st.button("➕ เพิ่มลูกค้าใหม่", key="sp_cust_add_btn", use_container_width=False):
                    st.session_state["_sp_adding_cust"] = ""
                if "_sp_adding_cust" in st.session_state:
                    with st.form("sp_add_cust_quick"):
                        _spf_n = st.text_input("ชื่อลูกค้า")
                        _spf_p = st.text_input("เบอร์โทร (ถ้ามี)")
                        _spfc1, _spfc2 = st.columns(2)
                        if _spfc1.form_submit_button("💾 บันทึก", type="primary"):
                            _all_cids_sp = [c["id"] for c in db.get_customers()]
                            _cmax_sp = max((int(re.match(r'C-(\d+)', x).group(1))
                                            for x in _all_cids_sp if re.match(r'C-(\d+)', x)), default=0)
                            _new_cid_sp = f"C-{_cmax_sp + 1:03d}"
                            db.upsert_customer({"id": _new_cid_sp,
                                                "name": _spf_n.strip(), "phone": _spf_p.strip()})
                            db.get_customers.clear()
                            st.session_state["_sp_cust_picked"] = _spf_n.strip()
                            st.session_state.pop("_sp_adding_cust", None)
                            st.rerun()
                        if _spfc2.form_submit_button("ยกเลิก"):
                            st.session_state.pop("_sp_adding_cust", None)
                            st.rerun()
        _sp_date = _sp_c2.date_input("วันที่", value=date.today(), key="sp_date")
        _sp_cid  = _sc_map[_sp_cust]["id"] if _sp_cust != "— เลือกลูกค้า —" else ""

        # ── ⚡ วางรหัสสินค้า ──────────────────────────────────────────────
        with st.expander("⚡ วางรหัสสินค้า", expanded=False):
            _sp_q_text = st.text_area(
                "รหัส-จำนวน คั่นด้วยเว้นวรรค",
                placeholder="เช่น: tf2581-2 rb2306-1 tu3315-1",
                height=80, key="sp_q_text",
            )
            if st.button("📋 ใส่ลงตาราง", key="sp_q_to_cart", type="primary", use_container_width=True):
                _sp_qf, _sp_qu = _parse_quick_order(_sp_q_text or "", _sp)
                if _sp_qu:
                    st.error(f"❌ รหัสไม่พบ: {', '.join(_sp_qu)}")
                if _sp_qf:
                    st.session_state["_sp_quick_items"] = _sp_qf
                    _new_ver = st.session_state.get("_sp_cart_ver", 0) + 1
                    st.session_state["_sp_cart_ver"] = _new_ver
                    st.session_state.pop(f"sp_cart_{_new_ver - 1}", None)
                    st.session_state.pop("_sp_cart_base", None)
                    st.rerun()

        st.divider()

        # ── รายการสินค้าที่ส่ง (ไม่ตัด stock) ───────────────────────────
        _sp_prod_keys = [f"{p['id']} — {p['name']}" for p in _sp]
        _sp_prod_map  = {f"{p['id']} — {p['name']}": p for p in _sp}
        _sp_cart_ver  = st.session_state.get("_sp_cart_ver", 0)
        _sp_cart_key  = f"sp_cart_{_sp_cart_ver}"
        if _sp_cart_key not in st.session_state:
            if "_sp_quick_items" in st.session_state:
                _sp_qi = st.session_state.pop("_sp_quick_items")
                _sp_cart_df = pd.DataFrame({
                    "สินค้า": [f"{it['product']['id']} — {it['product']['name']}" for it in _sp_qi],
                    "จำนวน":  pd.array([it["qty"] for it in _sp_qi], dtype="int64"),
                })
            else:
                _sp_cart_df = pd.DataFrame({"สินค้า": pd.Series([""] * 3, dtype="object"),
                                             "จำนวน":  pd.Series([0] * 3, dtype="int64")})
            st.session_state["_sp_cart_base"] = _sp_cart_df
        else:
            _sp_cart_df = st.session_state.get("_sp_cart_base", pd.DataFrame({
                "สินค้า": pd.Series([""] * 3, dtype="object"),
                "จำนวน":  pd.Series([0] * 3, dtype="int64"),
            }))
        _sp_cart_edit = st.data_editor(
            _sp_cart_df, num_rows="dynamic", hide_index=True, use_container_width=True,
            key=_sp_cart_key,
            column_config={
                "สินค้า": st.column_config.SelectboxColumn("สินค้า (รหัส — ชื่อ)", options=_sp_prod_keys, required=False, width="large"),
                "จำนวน": st.column_config.NumberColumn("จำนวน", min_value=0, step=1, width="small"),
            },
        )
        _sp_items = [
            {"product_id": _sp_prod_map[r["สินค้า"]]["id"],
             "name":       _sp_prod_map[r["สินค้า"]]["name"],
             "qty":        int(r["จำนวน"] or 0)}
            for _, r in _sp_cart_edit.iterrows()
            if str(r.get("สินค้า","")) in _sp_prod_map and int(r.get("จำนวน") or 0) > 0
        ]
        _sp_total_weight = sum(
            float(_sp_prod_map.get(r["สินค้า"], {}).get("weight_grams") or 0) * int(r["จำนวน"] or 0)
            for _, r in _sp_cart_edit.iterrows()
            if str(r.get("สินค้า","")) in _sp_prod_map
        )
        _sp_total_amt = sum(
            float(_sp_prod_map.get(r["สินค้า"], {}).get("price") or 0) * int(r["จำนวน"] or 0)
            for _, r in _sp_cart_edit.iterrows()
            if str(r.get("สินค้า","")) in _sp_prod_map
        )

        # ── ที่อยู่เดิม (collapsed) ───────────────────────────────────────
        if _sp_cid:
            try:
                _sp_saved = db.get_customer_addresses(customer_id=_sp_cid)
            except Exception:
                _sp_saved = []
            if _sp_saved:
                with st.expander(f"⚡ ที่อยู่เดิม ({len(_sp_saved)} รายการ)", expanded=False):
                    for _sa in _sp_saved:
                        _lbl = f"📍 {_sa.get('recipient_name','')}  {_sa.get('phone','')}  {_sa.get('address_line','')} {_sa.get('district','')} {_sa.get('amphure','')} {_sa.get('province','')} {_sa.get('postal_code','')}"
                        if st.button(_lbl, key=f"qa_ship_{_sa['id']}", use_container_width=False):
                            _sa_dt = (_sa.get("district", "") or "").strip()
                            _sa_pc = (_sa.get("postal_code", "") or "").strip()
                            st.session_state["_fsp_rname"] = _sa.get("recipient_name", "")
                            st.session_state["_fsp_rphone"]= _sa.get("phone", "")
                            st.session_state["_fsp_al"]   = _sa.get("address_line", "")
                            st.session_state["_fsp_dt"]   = _sa_dt
                            st.session_state["_fsp_am"]   = _sa.get("amphure", "")
                            st.session_state["_fsp_pv"]   = _sa.get("province", "")
                            st.session_state["_fsp_pc"]   = _sa_pc
                            st.session_state["_sp_last_dt"] = _sa_dt
                            st.session_state["_sp_last_pc"] = _sa_pc
                            st.rerun()

        # ── ที่อยู่ผู้รับ ─────────────────────────────────────────────────
        with st.expander("📦 ที่อยู่ผู้รับ", expanded=True):
            # paste-parse จาก LINE format
            _sp_parse_key = "_sp_parse_open"
            if st.button("📍 แยกที่อยู่อัตโนมัติ", key="sp_parse_open_btn"):
                st.session_state[_sp_parse_key] = not st.session_state.get(_sp_parse_key, False)
            if st.session_state.get(_sp_parse_key):
                _sp_paste = st.text_area("วางที่อยู่จาก LINE (iShip format)", key="sp_paste_addr",
                                          height=100,
                                          placeholder="Boo Mee\nสวนหลวง/ Suan Luang,\nกรุงเทพมหานคร/ Bangkok,\n10250  14 Rama IX Soi 41\n0617490976")
                _spc1, _spc2 = st.columns([1, 1])
                if _spc1.button("✅ ตกลง", key="sp_parse_btn", type="primary"):
                    _sp_parsed = _parse_iship_address(_sp_paste)
                    st.session_state["_fsp_rname"] = _sp_parsed.get("dst_name", "")
                    st.session_state["_fsp_rphone"]= _sp_parsed.get("dst_phone", "")
                    st.session_state["_fsp_al"]   = _sp_parsed.get("address_line", "")
                    st.session_state["_fsp_dt"]   = _sp_parsed.get("district", "")
                    st.session_state["_fsp_am"]   = _sp_parsed.get("amphure", "")
                    st.session_state["_fsp_pv"]   = _sp_parsed.get("province", "")
                    st.session_state["_fsp_pc"]   = _sp_parsed.get("zipcode", "")
                    if _sp_parsed.get("district"):  st.session_state["_sp_last_dt"] = _sp_parsed["district"]
                    if _sp_parsed.get("zipcode"):   st.session_state["_sp_last_pc"] = _sp_parsed["zipcode"]
                    st.session_state[_sp_parse_key] = False
                    st.rerun()
                if _spc2.button("ยกเลิก", key="sp_parse_cancel"):
                    st.session_state[_sp_parse_key] = False
                    st.rerun()
            st.divider()

            # apply staged address fill ก่อน render widgets
            for _fk, _wk in [("_fsp_rname",f"sp_rname_v{_sp_av}"),("_fsp_rphone",f"sp_rphone_v{_sp_av}"),
                              ("_fsp_al",f"sp_al_v{_sp_av}"),
                              ("_fsp_dt",f"sp_dt_v{_sp_av}"),("_fsp_am",f"sp_am_v{_sp_av}"),
                              ("_fsp_pv",f"sp_pv_v{_sp_av}"),("_fsp_pc",f"sp_pc_v{_sp_av}")]:
                if _fk in st.session_state:
                    st.session_state[_wk] = st.session_state.pop(_fk)

            # phone lookup อัตโนมัติ
            _sp_cur_rph = st.session_state.get(f"sp_rphone_v{_sp_av}", "")
            if len(_sp_cur_rph.strip()) == 10 and st.session_state.get("_sp_last_rph_fill") != _sp_cur_rph.strip():
                try:
                    _sp_rph_addr = db.get_address_by_phone(_sp_cur_rph.strip())
                except Exception:
                    _sp_rph_addr = None
                st.session_state["_sp_last_rph_fill"] = _sp_cur_rph.strip()
                if _sp_rph_addr:
                    for _k, _v in [(f"sp_rname_v{_sp_av}", _sp_rph_addr.get("recipient_name") or ""),
                                   (f"sp_al_v{_sp_av}",    _sp_rph_addr.get("address_line") or ""),
                                   (f"sp_dt_v{_sp_av}",    _sp_rph_addr.get("district") or ""),
                                   (f"sp_am_v{_sp_av}",    _sp_rph_addr.get("amphure") or ""),
                                   (f"sp_pv_v{_sp_av}",    _sp_rph_addr.get("province") or "")]:
                        if _v: st.session_state[_k] = _v
                    if _sp_rph_addr.get("postal_code"):
                        _sp_rph_pc = _sp_rph_addr["postal_code"]
                        st.session_state[f"sp_pc_v{_sp_av}"] = _sp_rph_pc
                        st.session_state["_sp_last_pc"] = _sp_rph_pc
                    _sp_rph_cust = (_sp_rph_addr.get("customers") or {}).get("name", "")
                    if _sp_rph_cust and not st.session_state.get("_sp_cust_picked"):
                        st.session_state["_sp_cust_picked"] = _sp_rph_cust
                    st.rerun()

            _sa1, _sa2 = st.columns(2)
            _sp_rname  = _sa1.text_input("ชื่อผู้รับ",    key=f"sp_rname_v{_sp_av}")
            _sp_rphone = _sa2.text_input("เบอร์โทร",      key=f"sp_rphone_v{_sp_av}")
            _sp_al     = st.text_input("บ้านเลขที่/ถนน",  key=f"sp_al_v{_sp_av}")
            _sb1, _sb2, _sb3 = st.columns(3)
            with _sb1:
                _sp_dt = _tambon_selectbox(f"sp_dt_v{_sp_av}", f"sp_am_v{_sp_av}", f"sp_pv_v{_sp_av}",
                                            f"sp_pc_v{_sp_av}", f"sp_dt_searchbox_v{_sp_av}")
            _sp_am = _sb2.text_input("อำเภอ/เขต",   key=f"sp_am_v{_sp_av}")
            _sp_pv = _sb3.selectbox("จังหวัด", [""] + _PROVINCES, key=f"sp_pv_v{_sp_av}")
            _sp_pc = st.text_input("รหัสไปรษณีย์", max_chars=5, key=f"sp_pc_v{_sp_av}", placeholder="เช่น 10400")
            _postcode_suggest(_sp_pc, f"sp_dt_v{_sp_av}", f"sp_am_v{_sp_av}", f"sp_pv_v{_sp_av}",
                              f"sp_dt_searchbox_v{_sp_av}", f"sp_pc_suggest_v{_sp_av}")
            if _sp_cid and st.button("💾 บันทึกที่อยู่นี้", key="sp_save_addr"):
                db.upsert_customer_address({
                    "id":             str(uuid.uuid4()),
                    "customer_id":    _sp_cid,
                    "recipient_name": _sp_rname,
                    "phone":          _sp_rphone,
                    "address_line":   _sp_al,
                    "district":       _sp_dt,
                    "amphure":        _sp_am,
                    "province":       _sp_pv,
                    "postal_code":    _sp_pc,
                })
                st.success("✅ บันทึกที่อยู่แล้ว")

        # ── ขนส่ง + ค่าส่ง + metrics ─────────────────────────────────────
        _sp_fc1, _sp_fc2, _sp_fc3 = st.columns(3)
        _sp_fees = carrier_fees(_sp_total_weight, _sp_pc.strip()) if len((_sp_pc or "").strip()) == 5 else None
        if _sp_fees:
            _sp_fc1.caption(f"Flash: {_sp_fees['Flash Express']['zone'] or 'ปกติ'} | +{_sp_fees['Flash Express']['surcharge']} ฿")
            _sp_fc2.caption(f"SPX:   {_sp_fees['SPX Express']['zone']   or 'ปกติ'} | +{_sp_fees['SPX Express']['surcharge']} ฿")
            _sp_f_tot = _sp_fees["Flash Express"]["total"]
            _sp_s_tot = _sp_fees["SPX Express"]["total"]
            if _sp_f_tot < _sp_s_tot:
                _sp_auto = "Flash Express"
            elif _sp_s_tot < _sp_f_tot:
                _sp_auto = "SPX Express"
            else:
                _sp_auto = _pick_carrier(_sp_pc.strip(), round(_sp_total_weight / 1000, 2))
            _sp_sig = (_sp_pc.strip(), round(_sp_total_weight / 1000, 2))
            if _sp_sig != st.session_state.get("_sp_carrier_sig"):
                st.session_state["_sp_carrier_sig"]    = _sp_sig
                st.session_state["_sp_staged_carrier"] = _sp_auto
                st.rerun()
        if "_sp_staged_carrier" in st.session_state:
            st.session_state["sp_carrier"] = st.session_state.pop("_sp_staged_carrier")
        _sp_carrier = _sp_fc3.radio("ขนส่ง", ["Flash Express", "SPX Express"], key="sp_carrier")
        _sp_cost = _sp_fees[_sp_carrier]["total"] if _sp_fees else 0
        if _sp_items:
            _sm1, _sm2, _sm3 = st.columns(3)
            _sm1.metric(f"🚚 {_sp_carrier}", f"{_sp_cost} ฿")
            _sm2.metric("⚖️ น้ำหนัก", f"{(_sp_total_weight/1000):.2f} kg")
            _sm3.metric("📦 รายการ", f"{len(_sp_items)} สินค้า")
            if _sp_total_amt > 0:
                _sm4, _sm5 = st.columns(2)
                _sm4.metric("💵 ยอดสินค้า", f"{_sp_total_amt:,.0f} ฿")
                _sm5.metric("💰 ยอดรวม (รวมค่าส่ง)", f"{(_sp_total_amt + _sp_cost):,.0f} ฿")

        # ── tracking + หมายเหตุ ───────────────────────────────────────────
        _sp_track = st.text_input("เลข tracking (กรอกทีหลังได้)", key=f"sp_track_v{_sp_av}", placeholder="TH123456789")
        _sp_notes = st.text_input("หมายเหตุ", key=f"sp_notes_v{_sp_av}")

        # ── บันทึก ────────────────────────────────────────────────────────
        if st.button("💾 บันทึกการส่งของ", type="primary", use_container_width=True, key="sp_save"):
            if not _sp_rname.strip():
                st.error("กรุณากรอกชื่อผู้รับ")
            elif not _sp_pc.strip():
                st.error("กรุณากรอกรหัสไปรษณีย์")
            else:
                _sp_new_id = str(uuid.uuid4())
                _sp_wt = _sp_total_weight / 1000
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
                        "cod_amount":     0,
                        "notes":          _sp_notes.strip(),
                        "source":         "ship",
                    })
                except Exception as _e:
                    st.error(f"❌ บันทึกไม่สำเร็จ: {_e}")
                    st.stop()
                # ตั้ง iShip pending เพื่อส่งขนส่ง
                _sp_item_codes = " ".join(f"{it['product_id']}-{it['qty']}" for it in _sp_items)
                _sp_remark = " ".join(filter(None, [
                    _sp_cust if _sp_cust != "— เลือกลูกค้า —" else "",
                    _sp_item_codes,
                    _sp_notes.strip(),
                ]))
                _sp_iship_args = {
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
                    "_shipment_id":   _sp_new_id,
                    "_customer_id":   _sp_cid or "",
                    "_customer_name": _sp_cust if _sp_cust != "— เลือกลูกค้า —" else "",
                }
                if iship_api.is_configured():
                    st.session_state["_iship_carrier_select"] = {
                        "tab":          "ship",
                        "postcode":     _sp_pc.strip(),
                        "weight_kg":    max(0.5, _sp_wt),
                        "dst_name":     _sp_rname.strip(),
                        "dst_phone":    _sp_rphone.strip(),
                        "address_line": _sp_al.strip(),
                        "district":     _sp_dt.strip(),
                        "amphure":      _sp_am.strip(),
                        "province":     _sp_pv.strip(),
                        "cod_amount":   0,
                        "items":        _sp_items,
                        "customer_id":  _sp_cid or "",
                        "customer_name":_sp_cust if _sp_cust != "— เลือกลูกค้า —" else "",
                        "shipment_id":  _sp_new_id,
                        "remark":       _sp_remark,
                    }
                    st.session_state["_open_carrier_select"] = True
                for _k in _sp_keys:
                    st.session_state.pop(_k, None)
                st.session_state["_sp_addr_ver"] = _sp_av + 1
                _sp_cv = st.session_state.get("_sp_cart_ver", 0)
                st.session_state.pop(f"sp_cart_{_sp_cv}", None)
                st.session_state["_sp_cart_ver"] = _sp_cv + 1
                st.rerun()

        st.caption("กรอกข้อมูลด้านบนแล้วกด 💾 บันทึกการส่งของ — tracking จะบันทึกอัตโนมัติหลังส่ง iShip")

        # ── ผลลัพธ์หลังบันทึก ─────────────────────────────────────────────
        if st.session_state.get("_sp_last_tracking"):
            _lt = st.session_state["_sp_last_tracking"]
            _ltc1, _ltc2 = st.columns([5, 1])
            _ltc1.success(f"✅ iShip สำเร็จ — Tracking: **{_lt}**")
            if _ltc2.button("✕", key="sp_clear_tracking", use_container_width=True):
                del st.session_state["_sp_last_tracking"]
                st.rerun()

        if st.session_state.get("_sp_iship_pending"):
            _spp = st.session_state["_sp_iship_pending"]
            _spp_addr  = f"{_spp.get('address_line','')} {_spp.get('district','')} {_spp.get('amphure','')} {_spp.get('province','')} {_spp.get('zipcode','')}".strip()
            _spp_items = ", ".join(f"{it.get('product_id','')} {it.get('name','')} ×{it.get('qty',0)}" for it in (_spp.get("_items") or []))
            _spp_cust  = _spp.get("_customer_name", "")
            _cust_line = f"🧑 ลูกค้า: **{_spp_cust}**  \n" if _spp_cust else ""
            _item_line = f"  \n🛍️ {_spp_items}" if _spp_items else ""
            if _spp.get("_auto_error"):
                st.error(f"❌ iShip ล้มเหลว: {_spp['_auto_error']} — กรุณาลองใหม่")
            st.info(f"{_cust_line}📦 **{_spp['dst_name']}** | ☎ {_spp.get('dst_phone','')}  \n{_spp_addr}{_item_line}")
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
                        _d = _sp_resp.get("data") or {}
                        _sp_tracking = (_d.get("tracking_code") or _d.get("tracking_number")
                                        or _sp_resp.get("tracking_code") or _sp_resp.get("tracking_number") or "")
                        if _spp.get("_shipment_id") and _sp_tracking:
                            db.update_shipment_tracking(_spp["_shipment_id"], _sp_tracking)
                        _sp_cid2 = _spp.get("_customer_id", "")
                        _sp_luid_b = db.get_customer_line_user_id(_sp_cid2) if (_sp_tracking and _sp_cid2) else ""
                        del st.session_state["_sp_iship_pending"]
                        _spp_addr = f"{_spp.get('address_line','')} {_spp.get('district','')} {_spp.get('amphure','')} {_spp.get('province','')} {_spp.get('zipcode','')}".strip()
                        st.session_state["_iship_success_info"] = {
                            "tracking":      _sp_tracking,
                            "tab":           "ship",
                            "customer":      _spp.get("_customer_name",""),
                            "dst_name":      _spp.get("dst_name",""),
                            "dst_phone":     _spp.get("dst_phone",""),
                            "address":       _spp_addr,
                            "carrier":       _spp.get("carrier",""),
                            "weight_kg":     _spp.get("weight_kg",0),
                            "cod_amount":    _spp.get("cod_amount",0),
                            "items":         _spp.get("_items",[]),
                            "line_user_id":  _sp_luid_b,
                            "shipment_id":   _spp.get("_shipment_id", ""),
                        }
                        st.session_state["_open_success_dialog"] = True
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

    with _sub_calc:
        st.subheader("คำนวณยอด")
        st.caption("พิมพ์รหัสสินค้าแบบ LINE OA แล้วกดคำนวณ เช่น `TF2581-2 RB2306-1 SH-kg12170 COD`")

        def _parse_calc_order(text: str, products: list) -> dict:
            product_map = {p["id"].upper(): p for p in products}
            tokens = text.strip().upper().split()
            items, ship_zip, manual_ship, is_cod, errors = [], "", -1, False, []
            for token in tokens:
                if token == "COD":
                    is_cod = True
                    continue
                if "-" not in token:
                    continue
                parts = token.split("-", 1)
                code, val = parts[0], parts[1]
                if code == "SH":
                    if val.startswith("KG"):
                        z = val[2:]
                        if len(z) == 5:
                            ship_zip = z
                    else:
                        try:
                            manual_ship = float(val)
                        except Exception:
                            pass
                else:
                    try:
                        qty = float(val)
                        if qty > 0:
                            if code in product_map:
                                items.append({"product": product_map[code], "qty": qty})
                            else:
                                errors.append(f"ไม่พบรหัส {code}")
                    except Exception:
                        pass
            return {"items": items, "ship_zip": ship_zip,
                    "manual_ship": manual_ship, "is_cod": is_cod, "errors": errors}

        _calc_products  = db.get_products()
        _calc_customers = db.get_customers()
        _calc_cust_map  = {c["name"]: c for c in _calc_customers}

        _calc_ver = st.session_state.get("_calc_ver", 0)

        _calc_col1, _calc_col2 = st.columns([3, 2])
        with _calc_col1:
            _calc_text = st.text_area(
                "รหัสสินค้า",
                key=f"_calc_text_v{_calc_ver}",
                height=100,
                placeholder="TF2581-2 RB2306-1 SH-kg12170 COD",
            )
        with _calc_col2:
            _calc_cust_opts = ["— ไม่ระบุ —"] + sorted(_calc_cust_map.keys(), key=str.casefold)
            _calc_cust_sel  = st.selectbox("ลูกค้า (ถ้าจะส่ง LINE)", _calc_cust_opts,
                                           key=f"_calc_cust_v{_calc_ver}")
            _line_btn_slot  = st.empty()

        _cbtn1, _cbtn2 = st.columns([1, 1])
        if _cbtn1.button("🔢 คำนวณ", type="primary", key="calc_btn", use_container_width=True):
            if not _calc_text.strip():
                st.warning("กรุณากรอกรหัสสินค้าก่อน")
            else:
                _cr = _parse_calc_order(_calc_text, _calc_products)
                st.session_state["_calc_result"] = _cr
        if _cbtn2.button("🗑️ ล้าง", key="calc_clear_btn", use_container_width=True):
            st.session_state.pop("_calc_result", None)
            st.session_state["_calc_ver"] = _calc_ver + 1
            st.rerun()

        _cr = st.session_state.get("_calc_result")
        if _cr:
            if _cr["errors"]:
                for _e in _cr["errors"]:
                    st.error(f"⚠️ {_e}")

            if _cr["items"]:
                st.divider()
                _c_total_amt = 0.0
                _c_total_pv  = 0.0
                _c_total_w   = 0
                _c_lines     = []
                for _ci in _cr["items"]:
                    _cp  = _ci["product"]
                    _cq  = int(_ci["qty"])
                    _camt = float(_cp["price"]) * _cq
                    _cpv  = float(_cp.get("points_per_unit", 0)) * _cq
                    _cw   = int(_cp.get("weight_grams", 0)) * _cq
                    _c_total_amt += _camt
                    _c_total_pv  += _cpv
                    _c_total_w   += _cw
                    _line_str = f"📦 [{_cp['id'].upper()}] - {_cq} * {int(_cp['price']):,} = {int(_camt):,}"
                    st.markdown(_line_str)
                    _c_lines.append(_line_str)

                _c_weight_kg = (_c_total_w + 500) / 1000
                st.markdown(f"✨ {_c_total_pv:,.0f} PV | ⚖️ {_c_weight_kg:.2f} kg")
                st.divider()

                _cust_ship_fee = 0.0   # ราคาคิดลูกค้า (39+10/kg+พื้นที่)
                _c_ship_fee    = 0.0   # ราคาจริงถูกสุดจากตารางขนส่ง
                _c_ship_label  = ""
                _opts = []
                if _cr["ship_zip"]:
                    _cust_ship_fee = calc_shipping(_c_total_w, _cr["ship_zip"])
                    _opts = carr.get_shipping_options(
                        _c_weight_kg, _cr["ship_zip"], _cr["is_cod"], _c_total_amt
                    )
                    _opts_ok = [o for o in _opts if not o["exceeds_max"]]
                    if _opts_ok:
                        _best = _opts_ok[0]
                        _c_ship_fee  = float(_best["total"])
                        _c_ship_label = _best["name"]
                elif _cr["manual_ship"] >= 0:
                    _cust_ship_fee = _cr["manual_ship"]
                    _c_ship_fee    = _cr["manual_ship"]
                    _c_ship_label  = "ระบุเอง"

                _c_cod_fee   = ceil((_c_total_amt + _cust_ship_fee) * 0.0321) if _cr["is_cod"] else 0
                _c_grand     = _c_total_amt + _cust_ship_fee + _c_cod_fee

                # ─── ส่วนลูกค้า (copy / ส่ง LINE) ────────────────────────
                st.markdown(f"💵 สินค้า: ฿{_c_total_amt:,.0f}")
                if _cust_ship_fee > 0:
                    st.markdown(f"🚚 ค่าส่ง: ฿{int(_cust_ship_fee):,}")
                if _c_cod_fee > 0:
                    st.markdown(f"➕ COD 3.21%: ฿{int(_c_cod_fee):,}")
                _parts_raw = [str(int(_c_total_amt))]
                if _cust_ship_fee > 0: _parts_raw.append(str(int(_cust_ship_fee)))
                if _c_cod_fee > 0:     _parts_raw.append(str(int(_c_cod_fee)))
                st.markdown(f"{' + '.join(_parts_raw)} = {_c_grand:,.0f}")
                st.markdown(f"**💰 ยอดโอนสุทธิ: ฿{_c_grand:,.0f}**")

                # ─── ส่วนเจ้าของ (ราคาจริง + ตารางขนส่ง) ─────────────────
                st.divider()
                st.caption("ข้อมูลขนส่ง (สำหรับเจ้าของร้าน)")
                if _c_ship_fee > 0 and _c_ship_label and _c_ship_label != "ระบุเอง":
                    st.markdown(f"### 🚛 ราคาจริง: {_c_ship_fee:,.0f} ฿ ({_c_ship_label})")

                # ─── ทดลองส่ง iShip ──────────────────────────────────────
                if _cr["ship_zip"] and _opts_ok and _calc_cust_sel != "— ไม่ระบุ —" and iship_api.is_configured():
                    _ic_cust = _calc_cust_map.get(_calc_cust_sel, {})
                    _ic_cid  = _ic_cust.get("id", "")
                    if _ic_cid:
                        _ic_addrs = db.get_customer_addresses(_ic_cid)
                        if _ic_addrs:
                            _ic_labels = [
                                f"{a.get('recipient_name','')} · {a.get('phone','')} · "
                                f"{a.get('address_line','')} {a.get('district','')} {a.get('amphure','')} {a.get('province','')} {a.get('postal_code','')}"
                                for a in _ic_addrs
                            ]
                            _ic_sel  = st.selectbox("📍 เลือกที่อยู่ผู้รับ", _ic_labels, key="calc_iship_addr")
                            _ic_addr = _ic_addrs[_ic_labels.index(_ic_sel)]
                            _ic_cod  = _c_grand if _cr["is_cod"] else 0.0

                            # ── เลือก carrier (default = ถูกสุด) ──────────
                            _ic_carrier_opts = [o["name"] for o in _opts_ok]
                            _ic_carrier_sel  = st.selectbox(
                                "🚚 เลือกขนส่ง",
                                _ic_carrier_opts,
                                index=0,
                                key="calc_iship_carrier",
                            )
                            _ic_courier_code = iship_api.COURIER_MAP.get(_ic_carrier_sel, "")
                            _ic_chosen_total = next((o["total"] for o in _opts_ok if o["name"] == _ic_carrier_sel), _c_ship_fee)
                            if _ic_cod:
                                st.caption(f"iShip code: `{_ic_courier_code}` | ราคาจริง: {_ic_chosen_total:,} ฿ | COD: {int(_ic_cod):,} ฿")
                            else:
                                st.caption(f"iShip code: `{_ic_courier_code}` | ราคาจริง: {_ic_chosen_total:,} ฿")
                            if not _ic_courier_code:
                                st.warning(f"⚠️ ไม่พบ iShip code สำหรับ '{_ic_carrier_sel}'")

                            # ── กรอกขนาด ถ้าเป็น Bulky carrier ───────────
                            _ic_is_bulky = "Bulky" in _ic_carrier_sel
                            _ic_len = _ic_wid = _ic_hgt = 0
                            if _ic_is_bulky:
                                st.markdown("**📐 ขนาดกล่อง (จำเป็นสำหรับ Bulky)**")
                                _bd1, _bd2, _bd3 = st.columns(3)
                                _ic_len = _bd1.number_input("ยาว (cm)", min_value=1, max_value=300, value=30, step=1, key="calc_iship_len")
                                _ic_wid = _bd2.number_input("กว้าง (cm)", min_value=1, max_value=300, value=30, step=1, key="calc_iship_wid")
                                _ic_hgt = _bd3.number_input("สูง (cm)", min_value=1, max_value=300, value=20, step=1, key="calc_iship_hgt")

                            if st.button("📦 ส่ง iShip ด้วยขนส่งที่ถูกสุด", type="primary",
                                         key="calc_iship_btn", use_container_width=True):
                                _ic_resp = iship_api.create_order(
                                    dst_name     = _ic_addr.get("recipient_name", ""),
                                    dst_phone    = _ic_addr.get("phone", ""),
                                    address_line = _ic_addr.get("address_line", ""),
                                    district     = _ic_addr.get("district", ""),
                                    amphure      = _ic_addr.get("amphure", ""),
                                    province     = _ic_addr.get("province", ""),
                                    zipcode      = _ic_addr.get("postal_code", ""),
                                    weight_kg    = _c_weight_kg,
                                    cod_amount   = _ic_cod,
                                    carrier      = _ic_carrier_sel,
                                    remark       = "",
                                    length_cm    = int(_ic_len),
                                    width_cm     = int(_ic_wid),
                                    height_cm    = int(_ic_hgt),
                                )
                                if _ic_resp.get("status"):
                                    _ic_track = ((_ic_resp.get("data") or {}).get("tracking_no")
                                                 or _ic_resp.get("tracking_no", ""))
                                    st.success(f"✅ ส่ง iShip สำเร็จ! Tracking: **{_ic_track}**")
                                else:
                                    st.error(f"❌ {_ic_resp.get('message', str(_ic_resp))}")
                                    with st.expander("🔍 debug"):
                                        st.json(_ic_resp)
                        else:
                            st.caption("ยังไม่มีที่อยู่บันทึกสำหรับลูกค้านี้")

                if _cr["ship_zip"] and _opts:
                    _rows_ok  = [o for o in _opts if not o["exceeds_max"]]
                    _rows_exc = [o for o in _opts if o["exceeds_max"]]
                    _cmp_data = []
                    for _ci, o in enumerate(_rows_ok):
                        _sur_txt  = f"+{o['surcharge']} ({o['sur_label']})" if o["surcharge"] else "-"
                        _fuel_txt = f"+{o['fuel']}" if o["fuel"] else "-"
                        _cod_txt  = f"+{o['cod_fee']:,}" if o["cod_fee"] else "-"
                        _badge    = "🥇 " if _ci == 0 else ""
                        _cmp_data.append({
                            "ขนส่ง":        _badge + o["name"],
                            "ค่าส่ง":       o["base"],
                            "พื้นที่พิเศษ": _sur_txt,
                            "น้ำมัน":       _fuel_txt,
                            "รวม (฿)":      o["total"],
                            "COD":          _cod_txt,
                        })
                    if _cmp_data:
                        _cmp_df = pd.DataFrame(_cmp_data)
                        st.dataframe(_cmp_df, hide_index=True, use_container_width=True,
                                     column_config={"รวม (฿)": st.column_config.NumberColumn("รวม (฿)", format="%d ฿")})
                    if _rows_exc:
                        with st.expander(f"⚠️ เกินน้ำหนักสูงสุด ({len(_rows_exc)} ขนส่ง)"):
                            for o in _rows_exc:
                                st.caption(f"❌ {o['name']} รับได้สูงสุด {o['max_kg']} kg")

                # ─── ปุ่มส่ง LINE (แสดงใน slot ข้างชื่อลูกค้า) ───────────
                if _calc_cust_sel != "— ไม่ระบุ —" and line_api.is_configured():
                    _c_cust  = _calc_cust_map.get(_calc_cust_sel, {})
                    _c_luid  = db.get_customer_line_user_id(_c_cust.get("id", "")) if _c_cust.get("id") else ""
                    if _c_luid:
                        if _line_btn_slot.button(f"📨 ส่ง LINE ให้คุณ {_calc_cust_sel}", type="primary", key="calc_line_btn", use_container_width=True):
                            _c_msg_lines = ["📝 รายการสินค้า", ""]
                            _c_msg_lines += _c_lines
                            _c_msg_lines += ["",
                                             f"✨ {_c_total_pv:,.0f} PV | ⚖️ {_c_weight_kg:.2f} kg",
                                             "",
                                             f"💵 สินค้า: ฿{_c_total_amt:,.0f}"]
                            if _cust_ship_fee > 0:
                                _c_msg_lines.append(f"🚚 ค่าส่ง: ฿{_cust_ship_fee:,.0f}")
                            if _c_cod_fee > 0:
                                _c_msg_lines.append(f"➕ COD: ฿{_c_cod_fee:,.0f}")
                            _parts = [str(int(_c_total_amt))]
                            if _cust_ship_fee > 0: _parts.append(str(int(_cust_ship_fee)))
                            if _c_cod_fee  > 0: _parts.append(str(int(_c_cod_fee)))
                            _formula = " + ".join(_parts)
                            _c_msg_lines.append(f"\n{_formula} = {int(_c_grand):,}")
                            _c_msg_lines.append(f"💰 ยอดโอนสุทธิ: ฿{int(_c_grand):,}")
                            _c_res = line_api.push_text(_c_luid, "\n".join(_c_msg_lines))
                            if _c_res["ok"]:
                                st.success(f"✅ ส่ง LINE ให้ {_calc_cust_sel} แล้ว")
                            else:
                                st.error(f"❌ {_c_res['error']}")
                    else:
                        _line_btn_slot.caption(f"👤 ยังไม่มี LINE ID")

        # ── แบ่งกล่อง ──────────────────────────────────────────────────────
        if st.button("📦 แบ่งกล่อง", key="toggle_boxcalc", use_container_width=True):
            st.session_state["_show_boxcalc"] = not st.session_state.get("_show_boxcalc", False)
        if st.session_state.get("_show_boxcalc"):
            st.subheader("📦 คำนวณการแบ่งกล่อง")
            st.caption("ดึงน้ำหนักจาก tab 🔢 คำนวณยอด — กดคำนวณที่นั่นก่อน")

            # ── ตั้งค่า preset กล่อง ──────────────────────────────────────────
            with st.expander("⚙️ ตั้งค่าขนาดกล่อง", expanded=False):
                _box_str_input = st.text_input(
                    "น้ำหนักสูงสุดต่อกล่อง (kg) คั่นด้วยลูกน้ำ",
                    value=st.session_state.get("_box_presets_str", "5, 10, 20"),
                    key="_box_presets_input",
                )
                st.session_state["_box_presets_str"] = _box_str_input
            _box_str = st.session_state.get("_box_presets_str", "5, 10, 20")

            def _safe_float_box(s: str) -> float:
                try: return float(s.strip())
                except: return 0.0

            def _pack_boxes(items: list, max_kg: float) -> list:
                """First-Fit Decreasing bin packing. Returns list of boxes [{weight_kg, items:{code:qty}}]"""
                units = []
                for it in items:
                    w = it["product"].get("weight_grams", 0) / 1000
                    code = it["product"]["id"].upper()
                    for _ in range(int(it["qty"])):
                        units.append((code, w))
                units.sort(key=lambda x: -x[1])
                boxes: list[dict] = []
                for code, w in units:
                    placed = False
                    for box in boxes:
                        if box["weight_kg"] + w <= max_kg + 1e-9:
                            box["weight_kg"] += w
                            box["items"][code] = box["items"].get(code, 0) + 1
                            placed = True
                            break
                    if not placed:
                        boxes.append({"weight_kg": w, "items": {code: 1}})
                return boxes

            _box_sizes = sorted({v for s in _box_str.split(",") if (v := _safe_float_box(s)) > 0})

            # ── ดึงข้อมูลจาก calc result ──────────────────────────────────────
            _bx_cr = st.session_state.get("_calc_result")
            if not _bx_cr or not _bx_cr.get("items"):
                st.info("กรุณาคำนวณยอดใน tab 🔢 คำนวณยอด ก่อน")
            else:
                _bx_prod_kg  = sum(int(_ci["product"].get("weight_grams",0))*int(_ci["qty"]) for _ci in _bx_cr["items"]) / 1000
                _bx_postcode = _bx_cr.get("ship_zip", "")
                st.markdown(f"⚖️ น้ำหนักสินค้ารวม: **{_bx_prod_kg:.3f} kg**"
                            + (f"  |  📮 **{_bx_postcode}**" if _bx_postcode else ""))

                if not _box_sizes:
                    st.warning("กรุณาตั้งค่าขนาดกล่องก่อน")
                else:
                    # ── สรุปทุก config (เปรียบเทียบ) ──────────────────────────
                    _summary_rows = []
                    _config_data  = {}   # bmax → {boxes, carrier_totals}
                    _all_carrier_names = []

                    for _bmax in _box_sizes:
                        _boxes = _pack_boxes(_bx_cr["items"], _bmax)
                        _n     = len(_boxes)
                        _total_ship_kg = _bx_prod_kg + _n * 0.5

                        # ค่าส่งทุกขนส่ง — ต้องรองรับทุกกล่อง จึงจะแสดง
                        _carrier_totals: dict[str, int] = {}
                        _carrier_ok: dict[str, bool] = {}
                        if _bx_postcode:
                            for _box in _boxes:
                                _bopts = carr.get_shipping_options(_box["weight_kg"] + 0.5, _bx_postcode)
                                for _o in _bopts:
                                    _cn = _o["name"]
                                    if _o["exceeds_max"]:
                                        _carrier_ok[_cn] = False
                                    else:
                                        if _cn not in _carrier_ok:
                                            _carrier_ok[_cn] = True
                                        if _carrier_ok.get(_cn):
                                            _carrier_totals[_cn] = _carrier_totals.get(_cn, 0) + _o["total"]
                                        if _cn not in _all_carrier_names:
                                            _all_carrier_names.append(_cn)
                            # ลบขนส่งที่รองรับไม่ครบทุกกล่อง
                            _carrier_totals = {k: v for k, v in _carrier_totals.items() if _carrier_ok.get(k)}

                        _cheapest_cost = min(_carrier_totals.values()) if _carrier_totals else None
                        _cheapest_name = next((k for k,v in _carrier_totals.items() if v == _cheapest_cost), "-") if _cheapest_cost else "-"

                        _config_data[_bmax] = {"boxes": _boxes, "carrier_totals": _carrier_totals}
                        _row = {"กล่อง max": f"{_bmax:.0f} kg", "จำนวนกล่อง": _n,
                                "น้ำหนักส่งรวม (kg)": f"{_total_ship_kg:.2f}",
                                "ขนส่งถูกสุด": _cheapest_name}
                        if _cheapest_cost:
                            _row["ค่าส่งรวม (฿)"] = _cheapest_cost
                        _summary_rows.append(_row)

                    _sum_df = pd.DataFrame(_summary_rows)
                    if "ค่าส่งรวม (฿)" in _sum_df.columns:
                        _ci_min = _sum_df["ค่าส่งรวม (฿)"].idxmin()
                        _sum_df["กล่อง max"] = _sum_df.apply(
                            lambda r: ("⭐ " if r.name == _ci_min else "") + r["กล่อง max"], axis=1)
                        st.dataframe(_sum_df, hide_index=True, use_container_width=True,
                                     column_config={"ค่าส่งรวม (฿)": st.column_config.NumberColumn(format="%d ฿")})
                        st.caption("⭐ = ค่าส่งรวมถูกสุด")
                    else:
                        st.dataframe(_sum_df, hide_index=True, use_container_width=True)

                    # ── รายละเอียด config ที่เลือก ─────────────────────────────
                    st.divider()
                    _sel_label = st.selectbox(
                        "ดูรายละเอียด — เลือก config กล่อง",
                        [f"{b:.0f} kg" for b in _box_sizes],
                        key="_bx_sel_config",
                    )
                    _sel_bmax  = next((b for b in _box_sizes if f"{b:.0f} kg" == _sel_label), _box_sizes[0])
                    _sel_data  = _config_data[_sel_bmax]
                    _sel_boxes = _sel_data["boxes"]

                    # ① สินค้าในแต่ละกล่อง
                    st.markdown(f"**📦 การจัดสินค้า ({len(_sel_boxes)} กล่อง)**")
                    for _bi, _box in enumerate(_sel_boxes, 1):
                        _items_str = "  ·  ".join(f"{code}×{qty}" for code, qty in _box["items"].items())
                        _bkg = _box["weight_kg"] + 0.5
                        st.markdown(f"กล่อง {_bi}: {_items_str} &nbsp;`{_box['weight_kg']:.3f} kg สินค้า + 0.5 kg กล่อง = {_bkg:.3f} kg`")

                    # ② ตารางเปรียบเทียบทุกขนส่ง
                    if _bx_postcode and _sel_data["carrier_totals"]:
                        st.divider()
                        st.markdown("**🚚 เปรียบเทียบค่าส่งทุกขนส่ง**")
                        _ct = _sel_data["carrier_totals"]
                        _ct_min = min(_ct.values())
                        _ct_rows = [{"ขนส่ง": ("🥇 " if v == _ct_min else "") + k, "ค่าส่งรวม (฿)": v}
                                    for k, v in sorted(_ct.items(), key=lambda x: x[1])]
                        st.dataframe(pd.DataFrame(_ct_rows), hide_index=True, use_container_width=True,
                                     column_config={"ค่าส่งรวม (฿)": st.column_config.NumberColumn(format="%d ฿")})
                    elif not _bx_postcode:
                        st.caption("ใส่รหัสไปรษณีย์ (SH-kgXXXXX) ใน tab คำนวณยอด เพื่อดูค่าส่งเปรียบเทียบ")

# Sub-tab: ยอดค้างลูกค้า  (rendered inside tab5 → _t5_out)
# ─────────────────────────────────────────────────────────────────────────────
with _t5_out:
    st.subheader("ยอดค้างลูกค้า")

    with st.expander("🗑️ ลบบิล", expanded=False):
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
    st.divider()

    customers = db.get_customers()
    if not customers:
        st.info("ยังไม่มีข้อมูล")
    else:
        # ── Summary metrics ────────────────────────────────────────────────
        unbilled     = db.get_unbilled_pv_summary()
        outstanding_df = db.get_outstanding_df()
        if not outstanding_df.empty:
            sm1, sm2, sm3 = st.columns(3)
            sm1.metric("ค้างจ่ายรวม",   f"{outstanding_df['ค้างจ่าย'].sum():,.0f} ฿")
            sm2.metric("ค้างรับรวม",    f"{int(outstanding_df['ค้างรับ'].sum())} ชิ้น")
            sm3.metric("PV รอเปิดบิล", f"{unbilled['total_pv']:,.0f}")
            st.divider()

        # ── Filter ────────────────────────────────────────────────────────
        fc1, fc2, fc3 = st.columns([2, 2, 3])
        _t2_search      = fc1.text_input("🔍 ลูกค้า", placeholder="พิมพ์ชื่อ...", key="tab2_search")
        _t2_bill_search = fc2.text_input("🔍 เลขที่บิล", placeholder="เช่น 260427", key="tab2_bill_search")
        filter_bill = fc3.radio("สถานะบิล", ["ค้างอยู่ทั้งหมด", "ยังไม่เปิดบิล", "เปิดบิลแล้ว"],
                                horizontal=True, key="tab2_filter_bill")
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

        # ── ค้นด้วยเลขที่บิล: เปิดบิลตรง ๆ พร้อมพิมพ์/จัดการ ────────────────
        _bp_bill_q = _t2_bill_search.strip()
        if re.match(r'^\d{6}-\d+$', _bp_bill_q):
            _cust_map_all_g = {c["name"]: c for c in customers}
            _all_txn_cache_g = db.get_all_transactions_df()
            with st.expander(f"📄 บิล {_bp_bill_q}", expanded=True):
                _render_bill_panel(
                    None, _cust_map_all_g, _all_txn_cache_g, customers,
                    key_prefix="bp_search", preselected_bill=_bp_bill_q,
                )
            st.divider()

        _exp_cols2 = ["เลขที่บิล", "วันที่", "ลูกค้า", "รหัส", "สินค้า", "สั่ง",
                      "ค้างรับ", "ยอดรวม", "ค้างจ่าย", "สถานะบิล"]
        _avail_cols2 = [c for c in _exp_cols2 if c in outstanding_df.columns]
        _exp_df2 = outstanding_df[_avail_cols2]
        st.download_button(
            "⬇ Export Excel",
            _to_excel_bytes(_exp_df2, "ยอดค้าง"),
            file_name=f"ยอดค้าง_{date.today().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_outs",
        )

        if outstanding_df.empty:
            st.success("✅ ไม่มียอดค้าง")
        else:
            # โหลด line_user_id ของลูกค้าทั้งหมด
            _cust_line_map = {c["name"]: c.get("line_user_id") or "" for c in customers}
            _cust_map_all  = {c["name"]: c for c in customers}
            _all_txn_cache = db.get_all_transactions_df()

            single_cust = (_t2_search.strip() != "" or _t2_bill_search.strip() != "") and outstanding_df["ลูกค้า"].nunique() == 1
            # pre-fetch shipments ครั้งเดียวแทนการเรียงใน loop (N+1 fix)
            try:
                _all_ships = db.get_shipments()
            except Exception:
                _all_ships = []
            _ship_by_cust: dict = {}
            for _s in _all_ships:
                _ship_by_cust.setdefault(_s.get("customer_id", ""), []).append(_s)

            for customer_name, grp in outstanding_df.groupby("ลูกค้า"):
                _is_cod = grp["สถานะจ่าย"] == "COD"
                owed     = grp.loc[~_is_cod, "ค้างจ่าย"].sum()
                owed_cod = grp.loc[_is_cod, "ค้างจ่าย"].sum()
                pending = int(grp["ค้างรับ"].sum())
                txn_ids = grp["id"].tolist()
                _luid   = _cust_line_map.get(customer_name, "")
                _unbilled_pv = grp.loc[grp["สถานะบิล"] == "ยังไม่เปิดบิล", "PV รวม"].sum() if "PV รวม" in grp.columns else 0
                exp_label = (f"**{customer_name}** — ค้างจ่าย {owed:,.0f}฿"
                             + (f" | 🟡 COD {owed_cod:,.0f}฿" if owed_cod > 0 else "")
                             + f" | ค้างรับ {pending} ชิ้น"
                             + (f" | ⭐ PV ค้างเปิดบิล {_unbilled_pv:,.0f}" if _unbilled_pv > 0 else ""))

                with st.expander(exp_label, expanded=single_cust):
                    # ── 🖨️ พิมพ์ / จัดการบิล ───────────────────────────────
                    with st.expander("🖨️ พิมพ์ / จัดการบิล"):
                        _cust_obj_bp = _cust_map_all.get(customer_name)
                        _bp_id = _cust_obj_bp["id"] if _cust_obj_bp else customer_name
                        _render_bill_panel(
                            customer_name, _cust_map_all, _all_txn_cache, customers,
                            key_prefix=f"bp_{_bp_id}",
                        )
                    st.divider()

                    # ── ใบรับของ popup ───────────────────────────────────
                    _rp = st.session_state.get("_recv_popup")
                    if _rp and _rp.get("customer_name") == customer_name:
                        _recv_rows_html = "".join(
                            f"<tr><td>{it['product']}</td><td style='text-align:center'>{it['qty']}</td></tr>"
                            for it in _rp["received"]
                        )
                        _pend_rows_html = "".join(
                            f"<tr><td>{it['product']}</td><td style='text-align:center'>{it['qty']}</td></tr>"
                            for it in _rp["pending"]
                        ) or "<tr><td colspan='2' style='color:#888'>ไม่มีค้างรับ</td></tr>"
                        _recv_html = f"""<!DOCTYPE html><html><head><meta charset='UTF-8'>
<style>
html,body{{background:#fff!important;color:#000!important}}
body{{font-family:'Sarabun',sans-serif;padding:12px 16px;font-size:13px}}
h3{{margin:0 0 6px;font-size:15px;color:#000}}
.info{{margin-bottom:10px;font-size:13px;color:#000}}
b{{color:#000}}
table{{width:100%;border-collapse:collapse;margin:6px 0}}
th{{background:#333;color:#fff;padding:4px 8px;font-size:12px;text-align:left}}
td{{padding:4px 8px;border-bottom:1px solid #ccc;color:#000}}
.section{{margin:10px 0}}
.sig{{margin-top:28px;display:inline-block;border-top:1px solid #000;padding-top:4px;min-width:180px;text-align:center;font-size:12px;color:#000}}
.btn{{display:block;margin:0 0 10px;padding:5px 18px;background:#333;color:#fff;border:none;cursor:pointer;border-radius:4px;font-size:12px}}
@media print{{.btn{{display:none}}@page{{size:A6 portrait;margin:8mm}}}}
</style></head><body style="background:#fff;color:#000">
<button class='btn' onclick='window.print()'>🖨️ พิมพ์ใบรับของ</button>
<h3>ใบรับของ</h3>
<div class='info'>วันที่: {_rp['date']}<br>ลูกค้า: <b>{_rp['customer_name']}</b></div>
<div class='section'><b>รายการที่รับวันนี้:</b>
<table><tr><th>สินค้า</th><th>จำนวนรับ</th></tr>{_recv_rows_html}</table></div>
<div class='section'><b>ยังค้างรับ:</b>
<table><tr><th>สินค้า</th><th>ค้างรับ</th></tr>{_pend_rows_html}</table></div>
<div class='sig'>ลายเซ็นผู้รับ</div>
</body></html>"""
                        components.html(_recv_html, height=360, scrolling=False)
                        if st.button("✕ ปิดใบรับของ", key=f"close_recv_{customer_name}"):
                            del st.session_state["_recv_popup"]
                            st.rerun()
                        st.divider()

                    # ── LINE แจ้งยอดค้าง ─────────────────────────────────
                    if line_api.is_configured():
                        _line_items = [
                            {"bill_no": r["เลขที่บิล"], "product": r["สินค้า"],
                             "amount": 0.0 if r["สถานะจ่าย"] == "COD" else float(r["ค้างจ่าย"]),
                             "qty": int(r["ค้างรับ"])}
                            for _, r in grp.iterrows()
                            if float(r["ค้างจ่าย"]) > 0 or int(r["ค้างรับ"]) > 0
                        ]
                        # COD ที่โอนแล้วรอเปิดบิล
                        _cust_obj  = next((c for c in customers if c["name"] == customer_name), None)
                        _cod_done  = []
                        if _cust_obj:
                            _sh_list = _ship_by_cust.get(_cust_obj["id"], [])
                            _cod_done = [
                                    {"tracking_no": s.get("tracking_no",""), "cod_amount": float(s.get("cod_amount") or 0)}
                                    for s in _sh_list
                                    if s.get("cod_transferred_at") and float(s.get("cod_amount") or 0) > 0
                                ]
                        if st.button(
                            "📨 แจ้ง LINE" if _luid else "📨 ไม่มี LINE ID",
                            key=f"line_out_{customer_name}",
                            disabled=not _luid,
                            help=None if _luid else "ยังไม่มี line_user_id ของลูกค้านี้",
                        ):
                            _r = line_api.push_outstanding(
                                _luid, customer_name, owed, pending, _line_items, _cod_done
                            )
                            if _r.get("ok"):
                                st.success("✅ ส่ง LINE แล้ว")
                            else:
                                st.error(f"❌ {_r.get('error')}")
                    # ── Styled table + row selection ──────────────────────
                    _dcols  = ["เลขที่บิล", "วันที่", "รหัส", "สินค้า", "สั่ง", "ค้างรับ",
                               "ยอดรวม", "ค้างจ่าย", "สถานะจ่าย", "สถานะบิล"]
                    _id_map = grp["id"].reset_index(drop=True)
                    st.caption("คลิกแถวเพื่อเลือก (Ctrl/Shift สำหรับหลายแถว)")
                    _evt = st.dataframe(
                        grp[_dcols].reset_index(drop=True).style
                            .format({"ยอดรวม": "{:,.0f}", "ค้างจ่าย": "{:,.0f}"})
                            .map(_style_status, subset=["สถานะบิล", "สถานะจ่าย"])
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
                    selected_ids = [_id_map.iloc[i] for i in _sel_idx if i < len(_id_map)]

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
                        if not balance:
                            st.warning("ไม่พบรายการนี้ในฐานข้อมูล")
                            st.stop()
                        txn     = balance["transaction"]
                        sel_row = grp[grp["id"] == txn_id].iloc[0]

                        _owed_label = "🟡 COD" if txn["pay_status"] == "COD" else "ค้างจ่าย"
                        st.caption(
                            f"📅 {sel_row['วันที่']}  ·  "
                            f"ราคา {float(txn['price_per_unit']):,.0f} ฿/ชิ้น  ·  "
                            f"รวม {float(txn['total_amount']):,.0f} ฿  ·  "
                            f"จ่ายแล้ว {balance['total_paid']:,.0f} ฿  ·  "
                            f"{_owed_label} **{balance['outstanding_amount']:,.0f} ฿**  ·  "
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
                                "💵+📦 จ่ายเงิน + รับของ": "ทั้งคู่",
                            }
                            evt_type = evt_map[action]
                            _price   = float(txn["price_per_unit"])
                            _outs_q  = int(balance["outstanding_qty"])
                            _hint    = f"ราคา/ชิ้น: {_price:,.0f} ฿"
                            for _n in range(1, min(_outs_q, 5) + 1):
                                _hint += f"  ·  {_n} ชิ้น = {_n * _price:,.0f} ฿"
                            st.caption(_hint)
                            _def_amt = max(0.0, float(balance["outstanding_amount"])) if evt_type != "รับของ" else 0.0
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
                                _also_open_bill = False
                                if is_unbilled:
                                    _also_open_bill = st.checkbox(
                                        "📄 เปิดบิลด้วย", value=False,
                                        key=f"also_open_{txn_id}",
                                    )
                                submit_evt  = st.form_submit_button(
                                    "💾 บันทึก", use_container_width=True, type="primary"
                                )
                            if submit_evt:
                                error = None
                                if evt_type == "จ่ายเงิน + รับของ" and qty_received > 0:
                                    new_paid = balance["total_paid"] + amount_paid
                                    price    = float(txn["price_per_unit"])
                                    max_ok   = floor(new_paid / price) if price > 0 else 0
                                    if balance["total_received"] + qty_received > max_ok:
                                        can   = max(0, max_ok - balance["total_received"])
                                        error = f"❌ รับได้สูงสุด {can} ชิ้น (จ่ายแล้ว {new_paid:,.0f} บาท)"
                                elif evt_type == "รับของ" and qty_received > balance["outstanding_qty"]:
                                    error = f"❌ รับได้สูงสุด {balance['outstanding_qty']} ชิ้น (ค้างรับอยู่)"
                                if error:
                                    st.error(error)
                                else:
                                    try:
                                        db.insert_partial_event({
                                            "id":             str(uuid.uuid4()),
                                            "date":           str(event_date),
                                            "transaction_id": txn_id,
                                            "qty_received":   int(qty_received),
                                            "amount_paid":    float(amount_paid),
                                            "event_type":     evt_type,
                                            "notes":          event_notes,
                                        })
                                    except Exception as _pe:
                                        st.error(f"❌ DB error: {_pe}")
                                        st.stop()
                                    if _also_open_bill:
                                        db.update_transaction_status(txn_id, bill_status="เปิดบิลแล้ว")
                                    db.get_all_transactions_df.clear()
                                    if int(qty_received) > 0:
                                        _rp_pending = []
                                        for _, _rr in grp.iterrows():
                                            _pq = int(_rr["ค้างรับ"])
                                            if _rr["id"] == txn_id:
                                                _pq = max(0, _pq - int(qty_received))
                                            if _pq > 0:
                                                _rp_pending.append({"product": _rr["สินค้า"], "qty": _pq})
                                        st.session_state["_recv_popup"] = {
                                            "customer_name": customer_name,
                                            "date": str(event_date),
                                            "received": [{"product": txn["product_name"], "qty": int(qty_received)}],
                                            "pending": _rp_pending,
                                        }
                                    st.success("✅ บันทึกแล้ว")
                                    st.rerun()

                        if not is_unbilled:
                            st.divider()
                            if st.button("↩️ ยกเลิกบิล", key=f"cancel_{txn_id}"):
                                db.update_transaction_status(txn_id, bill_status="ยังไม่เปิดบิล")
                                st.rerun()

                        # ── ลบบิล ─────────────────────────────────────────
                        _del_bno_vals = grp.loc[grp["id"] == txn_id, "เลขที่บิล"].values
                        _del_bno = str(_del_bno_vals[0]) if len(_del_bno_vals) > 0 and _del_bno_vals[0] else ""
                        if _del_bno and _del_bno not in ("—", ""):
                            st.divider()
                            _del_chk = st.checkbox(
                                f"🗑️ ลบบิล **{_del_bno}** และทุกรายการในบิลนี้",
                                key=f"del_bill_chk_{txn_id}",
                            )
                            if _del_chk:
                                if st.button(
                                    f"🗑️ ยืนยันลบบิล {_del_bno}", type="primary",
                                    key=f"del_bill_now_{txn_id}",
                                ):
                                    db.delete_bill(_del_bno)
                                    st.success(f"✅ ลบบิล {_del_bno} แล้ว")
                                    st.rerun()

                        # ── ลบรายการนี้ (เฉพาะแถวนี้) ─────────────────────
                        st.divider()
                        _del_row_chk = st.checkbox(
                            f"🗑️ ลบเฉพาะรายการ **{sel_row['สินค้า']}** แถวนี้ (ไม่กระทบรายการอื่นในบิล)",
                            key=f"del_row_chk_{txn_id}",
                        )
                        if _del_row_chk:
                            if st.button(
                                f"🗑️ ยืนยันลบรายการ {sel_row['สินค้า']}", type="primary",
                                key=f"del_row_now_{txn_id}",
                            ):
                                db.delete_transaction(txn_id)
                                st.success("✅ ลบรายการแล้ว")
                                st.rerun()

                    else:
                        # Multi: ทำทุกอย่างพร้อมกันในตารางเดียว
                        sel_rows      = grp[grp["id"].isin(selected_ids)].copy()
                        total_owed    = float(sel_rows["ค้างจ่าย"].sum())
                        _combo_rows = [{
                            "_id":       r["id"],
                            "สินค้า":    r["สินค้า"],
                            "เลขที่บิล": r["เลขที่บิล"] or "—",
                            "ค้างรับ":   int(r["ค้างรับ"]),
                            "รับจริง":   int(r["ค้างรับ"]),
                            "ค้างจ่าย":  float(r["ค้างจ่าย"]),
                            "จ่ายจริง":  float(r["ค้างจ่าย"]),
                            "สถานะบิล":  r["สถานะบิล"],
                        } for _, r in sel_rows.iterrows()]
                        _combo_df = pd.DataFrame(_combo_rows)

                        _combo_edit = st.data_editor(
                            _combo_df[["สินค้า","เลขที่บิล","ค้างรับ","รับจริง","ค้างจ่าย","จ่ายจริง","สถานะบิล"]],
                            column_config={
                                "สินค้า":    st.column_config.TextColumn(disabled=True),
                                "เลขที่บิล": st.column_config.TextColumn(disabled=True),
                                "ค้างรับ":   st.column_config.NumberColumn(disabled=True),
                                "รับจริง":   st.column_config.NumberColumn("รับจริง ✏️", min_value=0, format="%d"),
                                "ค้างจ่าย":  st.column_config.NumberColumn(disabled=True, format="%.0f"),
                                "จ่ายจริง":  st.column_config.NumberColumn("จ่ายจริง ✏️", min_value=0, format="%.0f"),
                                "สถานะบิล":  st.column_config.TextColumn(disabled=True),
                            },
                            hide_index=True, use_container_width=True,
                            key=f"multi_combo_{customer_name}",
                        )

                        _any_unbilled  = (sel_rows["สถานะบิล"] == "ยังไม่เปิดบิล").any()
                        _unbilled_cnt  = int((sel_rows["สถานะบิล"] == "ยังไม่เปิดบิล").sum())
                        _do_open_bill  = False
                        if _any_unbilled:
                            _do_open_bill = st.checkbox(
                                f"📄 เปิดบิลด้วย ({_unbilled_cnt} รายการที่ยังไม่เปิดบิล)",
                                key=f"multi_open_chk_{customer_name}",
                            )

                        _mc_c1, _mc_c2 = st.columns([2, 1])
                        mc_notes = _mc_c1.text_input("หมายเหตุ", key=f"mc_notes_{customer_name}")
                        mc_date  = _mc_c2.date_input("วันที่", value=date.today(), key=f"mc_date_{customer_name}")

                        _mc_recv = int(_combo_edit["รับจริง"].sum())
                        _mc_pay  = float(_combo_edit["จ่ายจริง"].sum())
                        _ms1, _ms2 = st.columns(2)
                        if _mc_recv > 0:
                            _ms1.metric("รับของรวม", f"{_mc_recv} ชิ้น")
                        if _mc_pay > 0.01:
                            _ms2.metric("ยอดจ่ายรวม", f"{_mc_pay:,.0f} ฿")

                        if st.button("💾 บันทึกทั้งหมด", type="primary",
                                     use_container_width=True, key=f"multi_all_{customer_name}"):
                            _saved_r, _saved_p = 0, 0
                            _mrp_received, _mrp_id_qty = [], {}
                            for i, row in _combo_df.iterrows():
                                _qty   = int(_combo_edit.iloc[i]["รับจริง"])
                                _amt   = float(_combo_edit.iloc[i]["จ่ายจริง"])
                                _owed  = float(row["ค้างจ่าย"])
                                _cap_r = int(row["ค้างรับ"])
                                _actual_qty = min(_qty, _cap_r) if _qty > 0 else 0
                                _actual_amt = min(_amt, _owed) if _amt > 0.01 else 0.0
                                if _actual_qty <= 0 and _actual_amt <= 0.01:
                                    continue
                                _etype = (
                                    "ทั้งคู่"   if _actual_qty > 0 and _actual_amt > 0.01
                                    else ("รับของ" if _actual_qty > 0 else "จ่ายเงิน")
                                )
                                db.insert_partial_event({
                                    "id":             str(uuid.uuid4()),
                                    "date":           str(mc_date),
                                    "transaction_id": row["_id"],
                                    "qty_received":   _actual_qty,
                                    "amount_paid":    round(_actual_amt, 2),
                                    "event_type":     _etype,
                                    "notes":          mc_notes,
                                })
                                if _actual_qty > 0:
                                    _saved_r += 1
                                    _mrp_received.append({"product": row["สินค้า"], "qty": _actual_qty})
                                    _mrp_id_qty[row["_id"]] = _actual_qty
                                if _actual_amt > 0.01:
                                    _saved_p += 1
                                    if _actual_amt >= _owed - 0.01:
                                        db.update_transaction_status(row["_id"], pay_status="จ่ายแล้ว")
                            if _do_open_bill:
                                for i, row in _combo_df.iterrows():
                                    if row["สถานะบิล"] == "ยังไม่เปิดบิล":
                                        db.update_transaction_status(row["_id"], bill_status="เปิดบิลแล้ว")
                            # popup รับของ
                            if _mrp_received:
                                _mrp_pending = []
                                for _, _rr in grp.iterrows():
                                    _pq = int(_rr["ค้างรับ"])
                                    if _rr["id"] in _mrp_id_qty:
                                        _pq = max(0, _pq - _mrp_id_qty[_rr["id"]])
                                    if _pq > 0:
                                        _mrp_pending.append({"product": _rr["สินค้า"], "qty": _pq})
                                st.session_state["_recv_popup"] = {
                                    "customer_name": customer_name,
                                    "date":          str(mc_date),
                                    "received":      _mrp_received,
                                    "pending":       _mrp_pending,
                                }
                            _parts = []
                            if _saved_r:
                                _parts.append(f"รับของ {_saved_r} รายการ")
                            if _saved_p:
                                _parts.append(f"จ่าย ฿{_mc_pay:,.0f}")
                            if _do_open_bill:
                                _parts.append(f"เปิดบิล {len(selected_ids)} รายการ")
                            if _parts:
                                st.success("✅ บันทึก: " + " + ".join(_parts))
                                for tid in txn_ids:
                                    st.session_state[f"chk_{tid}"] = False
                                st.rerun()
                            else:
                                st.warning("ไม่มีรายการที่ต้องบันทึก (ทุกช่องเป็น 0)")

                        # ── ลบบิล (multi) ────────────────────────────────
                        _del_bnos = sorted({
                            str(b) for b in sel_rows["เลขที่บิล"].dropna()
                            if b and str(b) not in ("—", "")
                        })
                        if _del_bnos:
                            st.divider()
                            _del_chk_m = st.checkbox(
                                f"🗑️ ลบบิล **{', '.join(_del_bnos)}** และทุกรายการในบิลเหล่านี้",
                                key=f"del_bill_chk_multi_{customer_name}",
                            )
                            if _del_chk_m:
                                if st.button(
                                    f"🗑️ ยืนยันลบ {len(_del_bnos)} บิล", type="primary",
                                    key=f"del_bill_now_multi_{customer_name}",
                                ):
                                    _total_del = sum(db.delete_bill(b) for b in _del_bnos)
                                    st.success(f"✅ ลบแล้ว {len(_del_bnos)} บิล ({_total_del} รายการ)")
                                    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Sub-tab: บัตรลูกค้า  (rendered inside tab5 → _t5_ledger)
# ─────────────────────────────────────────────────────────────────────────────
with _t5_ledger:
    st.subheader("บัตรลูกค้า")
    _l_customers = db.get_customers()
    _l_opts = ["— เลือกลูกค้า —"] + sorted([c["name"] for c in _l_customers], key=str.casefold)
    _lx1, _lx2 = st.columns([3, 2])
    _l_sel = _lx1.selectbox("👤 ลูกค้า", _l_opts, key="t5_ledger_cust")
    if _l_sel != "— เลือกลูกค้า —":
        _l_cust = next((c for c in _l_customers if c["name"] == _l_sel), None)
        if _l_cust:
            _l_data = db.get_customer_ledger(_l_cust["id"])
            if _l_data:
                # ── แยกประเภท ────────────────────────────────────────────
                _l_orders   = [r for r in _l_data if r["type"] == "สั่งซื้อ"]
                _l_payments = [r for r in _l_data if r["type"] == "จ่ายเงิน"]
                _l_receipts = [r for r in _l_data if r["type"] in ("รับของ", "แก้ไขรับ")]
                _l_ships    = [r for r in _l_data if "ส่งของ" in r["type"]]

                # ── summary metrics ──────────────────────────────────────
                _l_ord_qty  = sum(r["qty_in"]  for r in _l_orders)
                _l_recv_qty = sum(r["qty_out"] for r in _l_receipts)
                _l_paid_tot = sum(r["amount"]  for r in _l_payments)
                _sm1, _sm2, _sm3, _sm4 = st.columns(4)
                _sm1.metric("สั่งซื้อ",  f"{_l_ord_qty:,} ชิ้น")
                _sm2.metric("รับแล้ว",   f"{_l_recv_qty:,} ชิ้น")
                _sm3.metric("ค้างรับ",   f"{max(0, _l_ord_qty - _l_recv_qty):,} ชิ้น")
                _sm4.metric("จ่ายแล้ว",  f"{_l_paid_tot:,.0f} ฿")

                # ── สร้าง timeline per bill ──────────────────────────────
                _bills_tl: dict = {}  # bill_no → {date, total, pv, qty, events[]}

                # Phase 1: orders → bill header
                for _r in _l_orders:
                    _bk = _r["bill_no"] or "—"
                    if _bk not in _bills_tl:
                        _bills_tl[_bk] = {
                            "date": _r["date"], "total": 0.0, "pv": 0.0,
                            "qty": 0, "bill_status": "ยังไม่เปิดบิล", "products": [], "events": [],
                        }
                    _bills_tl[_bk]["products"].append(f"{_r['product']} ×{_r['qty_in']}")
                    _bills_tl[_bk]["total"] += _r.get("total_amount", 0.0)
                    _bills_tl[_bk]["pv"]    += _r.get("pv", 0.0)
                    _bills_tl[_bk]["qty"]   += _r["qty_in"]
                    if _r.get("bill_status") == "เปิดบิลแล้ว":
                        _bills_tl[_bk]["bill_status"] = "เปิดบิลแล้ว"

                # delivery type heuristic per bill
                _ship_dates_set = {_r["date"] for _r in _l_ships}
                _recv_bill_set  = {_r["bill_no"] for _r in _l_receipts if _r["bill_no"]}

                for _bk, _bv in _bills_tl.items():
                    if _bv["date"] in _ship_dates_set:
                        _dlv = "🚚 ส่งพัสดุ"
                    elif _bk in _recv_bill_set:
                        _dlv = "🏪 รับหน้าร้าน"
                    else:
                        _dlv = "📦 ฝากของ"
                    _bv["events"].append({
                        "date": _bv["date"], "order": 0, "type": "เปิดบิล",
                        "detail": ",  ".join(_bv["products"]),
                        "total": _bv["total"], "pv": _bv["pv"],
                        "bill_status": _bv["bill_status"], "delivery": _dlv,
                    })

                # Phase 2: payment events (running balance)
                _pay_cumul: dict = {}
                for _r in sorted(_l_payments, key=lambda x: x["date"]):
                    _bk = _r["bill_no"] or "—"
                    _pay_cumul[_bk] = _pay_cumul.get(_bk, 0.0) + _r["amount"]
                    _rem_pay = max(0.0, _bills_tl.get(_bk, {}).get("total", 0.0) - _pay_cumul[_bk])
                    if _bk in _bills_tl:
                        _bills_tl[_bk]["events"].append({
                            "date": _r["date"], "order": 2, "type": "จ่ายเงิน",
                            "amount": _r["amount"], "remaining": _rem_pay,
                        })

                # Phase 3: receipt events grouped by (bill, date)
                _recv_groups: dict = {}
                for _r in _l_receipts:
                    _bk = _r["bill_no"] or "—"
                    _recv_groups.setdefault((_bk, _r["date"]), []).append(
                        (_r["product"], int(_r["qty_out"]))
                    )
                _recv_cumul: dict = {}
                for (_bk, _rd), _items in sorted(_recv_groups.items(), key=lambda x: x[0][1]):
                    _batch_qty = sum(q for _, q in _items)
                    _recv_cumul[_bk] = _recv_cumul.get(_bk, 0) + _batch_qty
                    _rem_recv = max(0, _bills_tl.get(_bk, {}).get("qty", 0) - _recv_cumul[_bk])
                    if _bk in _bills_tl:
                        _bills_tl[_bk]["events"].append({
                            "date": _rd, "order": 1, "type": "รับของ",
                            "detail": ",  ".join(f"{p} ×{q}" for p, q in _items),
                            "remaining_qty": _rem_recv,
                        })

                # Phase 4: shipment events (match by bill date)
                for _r in _l_ships:
                    for _bk, _bv in _bills_tl.items():
                        if _bv["date"] == _r["date"]:
                            _bv["events"].append({
                                "date": _r["date"], "order": 1, "type": "ส่งพัสดุ",
                                "detail": _r["product"], "tracking": _r["bill_no"],
                            })
                            break

                # sort events within each bill
                for _bv in _bills_tl.values():
                    _bv["events"].sort(key=lambda e: (e["date"], e["order"]))

                # ── render expanders ──────────────────────────────────────
                _l_all_df = db.get_all_transactions_df(customer_id=_l_cust["id"])
                _l_table_cols = ["วันที่", "รหัส", "สินค้า", "สั่ง", "รับแล้ว", "ยอดรวม",
                                 "จ่ายแล้ว", "ค้างจ่าย", "ค้างรับ", "สถานะบิล", "สถานะจ่าย", "หมายเหตุ"]
                _l_table_cols_disp = ["วันที่", "รหัส", "สินค้า", "สั่ง", "รับแล้ว", "ยอดรวม",
                                       "จ่ายแล้ว", "ค้างจ่าย", "ค้างรับ", "สถานะบิล", "สถานะจ่าย",
                                       "สถานะรับของ", "หมายเหตุ"]
                for _bk, _bv in sorted(
                    _bills_tl.items(), key=lambda x: x[1]["date"], reverse=True
                ):
                    _b_paid  = _pay_cumul.get(_bk, 0.0)
                    _b_owed  = max(0.0, _bv["total"] - _b_paid)
                    _b_recv  = _recv_cumul.get(_bk, 0)
                    _b_pend  = max(0, _bv["qty"] - _b_recv)
                    _pay_ico = "✅" if _b_owed <= 0.01 else "🔴"
                    _recv_lbl = f" &nbsp;|&nbsp; 📦 ค้างรับ **{_b_pend} ชิ้น**" if _b_pend > 0 else ""
                    _pv_lbl   = (f" &nbsp;|&nbsp; ⭐ **{_bv['pv']:.0f} PV**"
                                 if _bv["pv"] > 0 and _bv["bill_status"] == "ยังไม่เปิดบิล" else "")
                    _exp_hdr  = (
                        f"📋 **{_bk}** &nbsp; {_bv['date']} &nbsp;|&nbsp; "
                        f"{_pay_ico} ค้างจ่าย **{_b_owed:,.0f}฿**{_recv_lbl}{_pv_lbl}"
                    )
                    with st.expander(_exp_hdr, expanded=True):
                        _pv_unbilled = _bv["pv"] if _bv["bill_status"] == "ยังไม่เปิดบิล" else 0.0
                        st.caption(
                            f"📦 ค้างรับ {_b_pend} ชิ้น  |  "
                            f"💰 ค้างจ่าย {_b_owed:,.0f}฿  |  "
                            f"⭐ PV ค้างเปิดบิล {_pv_unbilled:,.0f}"
                        )
                        _bill_filter = "" if _bk == "—" else _bk
                        _bill_rows = _l_all_df[_l_all_df["เลขที่บิล"].fillna("") == _bill_filter].copy()
                        if _bill_rows.empty:
                            st.caption("ไม่มีรายการ")
                        else:
                            _bill_rows["_dt"] = pd.to_datetime(_bill_rows["วันที่"], dayfirst=True, errors="coerce")
                            _bill_rows = _bill_rows.sort_values("_dt")
                            _disp = _bill_rows[_l_table_cols].reset_index(drop=True)
                            _disp["หมายเหตุ"] = _disp["หมายเหตุ"].fillna("").apply(_fmt_note)
                            _disp["สถานะรับของ"] = _bv["events"][0]["delivery"].split(" ", 1)[1]
                            _disp = _disp[_l_table_cols_disp]
                            st.dataframe(
                                _disp, hide_index=True, use_container_width=True,
                                column_config={
                                    "ยอดรวม":   st.column_config.NumberColumn("ยอดรวม", format="%,.0f"),
                                    "จ่ายแล้ว": st.column_config.NumberColumn("จ่ายแล้ว", format="%,.0f"),
                                    "ค้างจ่าย": st.column_config.NumberColumn("ค้างจ่าย", format="%,.0f"),
                                },
                            )

                        # ── ประวัติเหตุการณ์ของบิลนี้ เรียงตามวันที่ ──────────
                        st.markdown("**📜 ประวัติ**")
                        for _r in _bv["events"]:
                            if _r["type"] == "เปิดบิล":
                                st.caption(
                                    f"📋 {_r['date']}  เปิดบิล — {_r['detail']}  "
                                    f"(รวม {_r['total']:,.0f}฿"
                                    + (f", {_r['pv']:.0f} PV" if _r['pv'] > 0 else "")
                                    + ")"
                                )
                            elif _r["type"] == "จ่ายเงิน":
                                st.caption(
                                    f"💰 {_r['date']}  จ่ายเงิน {_r['amount']:,.0f}฿ "
                                    f"(คงค้าง {_r['remaining']:,.0f}฿)"
                                )
                            elif _r["type"] == "รับของ":
                                st.caption(
                                    f"📦 {_r['date']}  รับของ {_r['detail']} "
                                    f"(ค้างรับเหลือ {_r['remaining_qty']} ชิ้น)"
                                )
                            elif _r["type"] == "ส่งพัสดุ":
                                st.caption(f"🚚 {_r['date']}  ส่งพัสดุ {_r['detail']}  Tracking: {_r['tracking']}")

                        # ── ลบบิลนี้ ────────────────────────────────────────
                        if _bk != "—":
                            with st.expander("🗑️ ลบบิลนี้"):
                                st.warning(f"ลบบิล **{_bk}** และทุกรายการในบิลนี้ — กู้คืนไม่ได้")
                                _ldel_bill_chk = st.checkbox(
                                    "ยืนยันการลบ", key=f"ldel_bill_confirm_{_bk}_{_l_sel}"
                                )
                                if st.button("🗑️ ลบบิล", disabled=not _ldel_bill_chk,
                                              type="secondary", key=f"ldel_bill_btn_{_bk}_{_l_sel}"):
                                    _n = db.delete_bill(_bk)
                                    st.success(f"✅ ลบบิล {_bk} แล้ว ({_n} รายการ)")
                                    st.rerun()

                # ── ลบ partial event ──────────────────────────────────────
                _ldel_rows = [
                    (i, str(r.get("event_id") or ""))
                    for i, r in enumerate(_l_data) if r.get("event_id")
                ]
                if _ldel_rows:
                    with st.expander("🗑️ ลบรายการ"):
                        for _ldi, _leid in _ldel_rows:
                            _llr = _l_data[_ldi]
                            _leid_real = _leid.removesuffix("-r").removesuffix("-p")
                            _lamt_str = f"฿{_llr['amount']:,.0f}" if _llr['amount'] else ""
                            _llabel = (f"{_llr['date'][:10]}  {_llr['type']}  "
                                       f"{_llr.get('product','') or ''}  {_lamt_str}")
                            if st.button(f"🗑️ {_llabel}", key=f"ldel_{_ldi}_{_l_sel}"):
                                db.delete_partial_event(_leid_real)
                                st.rerun()
            else:
                st.caption("ไม่มีประวัติ")


# ─────────────────────────────────────────────────────────────────────────────
# Tab 4: จัดการข้อมูลหลัก
# ─────────────────────────────────────────────────────────────────────────────
with tab4:
    st.subheader("จัดการข้อมูลหลัก")

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
                use_container_width=True,
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
                        use_container_width=True,
                        key="exp_sales_dl",
                    )
    st.divider()

    sub1, sub2, sub3 = st.tabs(["🏷️ สินค้า", "👤 ลูกค้า", "📍 ที่อยู่"])


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



# ─────────────────────────────────────────────────────────────────────────────
# Tab 5: รายละเอียดบิล  (sub-tabs created at top of file)
# ─────────────────────────────────────────────────────────────────────────────

with _t5_txn:
    st.subheader("รายละเอียดบิล")

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

        st.download_button(
            "⬇ Export Excel",
            _to_excel_bytes(show_df, "ประวัติ"),
            file_name=f"ประวัติ_{date.today().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_hist",
        )

        display_cols_h = ["เลขที่บิล", "วันที่", "ลูกค้า", "รหัส", "สินค้า", "สั่ง", "รับแล้ว",
                          "ยอดรวม", "จ่ายแล้ว", "ค้างจ่าย", "ค้างรับ",
                          "สถานะบิล", "สถานะจ่าย", "หมายเหตุ"]
        show_df = all_df[display_cols_h].reset_index(drop=True)
        show_df["หมายเหตุ"] = show_df["หมายเหตุ"].fillna("").apply(_fmt_note)
        id_map  = all_df["id"].reset_index(drop=True)

        chk_df = show_df.copy()
        chk_df.insert(0, "🗑️", False)
        _cleared_mask = all_df["เคลียร์แล้ว"].reset_index(drop=True)
        chk_df.insert(1, "สถานะ", _cleared_mask.map({True: "✅ เคลียร์", False: ""}))

        _is_dup_bill = chk_df["เลขที่บิล"].ne("") & (chk_df["เลขที่บิล"] == chk_df["เลขที่บิล"].shift(1).fillna(""))
        for _col in ("เลขที่บิล", "วันที่", "ลูกค้า"):
            chk_df[_col] = chk_df[_col].where(~_is_dup_bill, "")

        # ── placeholder สำหรับปุ่มบันทึกเหนือตาราง (fill หลัง data_editor)
        _save_placeholder = st.empty()

        _editable = ("🗑️", "รับแล้ว", "สั่ง", "ยอดรวม", "จ่ายแล้ว", "ลูกค้า", "สถานะบิล", "สถานะจ่าย")
        _cust_names_h = [c["name"] for c in customers_h]
        _cust_id_map_h = {c["name"]: c["id"] for c in customers_h}
        edited_h = st.data_editor(
            chk_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "🗑️":       st.column_config.CheckboxColumn("🗑️", default=False, width="small"),
                "สถานะ":    st.column_config.TextColumn("สถานะ", width="small"),
                "สั่ง":     st.column_config.NumberColumn("สั่ง", min_value=1, step=1, width="small"),
                "รับแล้ว":  st.column_config.NumberColumn("รับแล้ว", min_value=0, step=1, width="small"),
                "ยอดรวม":   st.column_config.NumberColumn("ยอดรวม", format="%,.0f"),
                "จ่ายแล้ว": st.column_config.NumberColumn("จ่ายแล้ว", format="%,.0f"),
                "ค้างจ่าย": st.column_config.NumberColumn("ค้างจ่าย", format="%,.0f"),
                "ลูกค้า":    st.column_config.SelectboxColumn("ลูกค้า",
                    options=_cust_names_h, width="medium"),
                "สถานะบิล": st.column_config.SelectboxColumn("สถานะบิล",
                    options=["เปิดบิลแล้ว", "ยังไม่เปิดบิล"], width="medium"),
                "สถานะจ่าย": st.column_config.SelectboxColumn("สถานะจ่าย",
                    options=["จ่ายแล้ว", "ค้างจ่าย", "COD"], width="medium"),
            },
            disabled=[c for c in chk_df.columns if c not in _editable],
            key="hist_table",
        )

        to_del_idx = edited_h[edited_h["🗑️"]].index.tolist()

        if len(to_del_idx) == 1 and to_del_idx[0] < len(id_map):
            _auto_tid = id_map.iloc[to_del_idx[0]]
            _auto_rows = all_df[all_df["id"] == _auto_tid]
            if not _auto_rows.empty:
                _ar = _auto_rows.iloc[0]
                _auto_label = f"{_ar['วันที่']}  {_ar['ลูกค้า']}  {_ar['สินค้า']} ×{int(_ar['สั่ง'])}"
                if st.session_state.get("edit_sel") != _auto_label:
                    st.session_state["edit_sel"] = _auto_label

        if to_del_idx:
            d1, d2 = st.columns([2, 1])
            d1.warning(f"เลือก {len(to_del_idx)} รายการ")
            if d2.button("🗑️ ลบรายการที่เลือก", type="secondary", use_container_width=True, key="hist_del_chk_btn"):
                for i in to_del_idx:
                    db.delete_transaction(id_map.iloc[i])
                st.success(f"✅ ลบ {len(to_del_idx)} รายการแล้ว")
                st.session_state.pop("hist_table", None)
                st.rerun()

            _sel_unbilled = [i for i in to_del_idx
                             if i < len(all_df)
                             and all_df.iloc[i]["สถานะบิล"] == "ยังไม่เปิดบิล"]
            if _sel_unbilled:
                ob1, ob2 = st.columns([2, 1])
                ob1.info(f"📄 {len(_sel_unbilled)} รายการยังไม่เปิดบิล")
                if ob2.button(f"📄 เปิดบิล {len(_sel_unbilled)} รายการ",
                               type="primary", use_container_width=True,
                               key="hist_open_bill_btn"):
                    for i in _sel_unbilled:
                        db.update_transaction_status(id_map.iloc[i], bill_status="เปิดบิลแล้ว")
                    st.success(f"✅ เปิดบิล {len(_sel_unbilled)} รายการแล้ว")
                    st.session_state.pop("hist_table", None)
                    st.rerun()

        # ตรวจหาการแก้ไขทุกประเภท (เทียบกับ show_df ที่ไม่ blank)
        _any_changes = []
        for _i in range(len(show_df)):
            if _i >= len(id_map): break
            _orig = show_df.iloc[_i]
            _edit = edited_h.iloc[_i]
            _tid  = id_map.iloc[_i]
            _ch   = {}
            # รับแล้ว → partial_event qty
            _old_recv = int(_orig["รับแล้ว"])
            _new_recv = int(_edit["รับแล้ว"] or 0)
            if _old_recv != _new_recv:
                _ch["recv"] = (_old_recv, _new_recv)
            # จ่ายแล้ว → partial_event amount
            _old_paid = float(_orig["จ่ายแล้ว"])
            _new_paid = float(_edit["จ่ายแล้ว"] or 0)
            if abs(_old_paid - _new_paid) > 0.01:
                _ch["paid"] = (_old_paid, _new_paid)
            # สั่ง
            if int(_orig["สั่ง"]) != int(_edit["สั่ง"] or 1):
                _ch["qty"] = int(_edit["สั่ง"] or 1)
            # ยอดรวม
            if abs(float(_orig["ยอดรวม"]) - float(_edit["ยอดรวม"] or 0)) > 0.01:
                _ch["total"] = float(_edit["ยอดรวม"] or 0)
            # ถ้าแก้ สั่ง แต่ไม่ได้แก้ ยอดรวม → คำนวณ ยอดรวมใหม่ อัตโนมัติ
            if "qty" in _ch and "total" not in _ch:
                _orig_qty = int(_orig["สั่ง"])
                if _orig_qty > 0:
                    _price_per = float(_orig["ยอดรวม"]) / _orig_qty
                    _ch["total"] = _price_per * _ch["qty"]
            # ลูกค้า
            _new_cust = str(_edit["ลูกค้า"] or "")
            if _new_cust and _new_cust != str(_orig["ลูกค้า"]) and _new_cust in _cust_id_map_h:
                _ch["customer_id"] = _cust_id_map_h[_new_cust]
            # สถานะบิล
            if str(_orig["สถานะบิล"]) != str(_edit["สถานะบิล"] or ""):
                _ch["bill_status"] = str(_edit["สถานะบิล"])
            # สถานะจ่าย
            if str(_orig["สถานะจ่าย"]) != str(_edit["สถานะจ่าย"] or ""):
                _ch["pay_status"] = str(_edit["สถานะจ่าย"])
            if _ch:
                _any_changes.append((_i, _tid, _ch))

        if _any_changes:
            with _save_placeholder.container():
                _sp1, _sp2 = st.columns([3, 1])
                _sp1.warning(f"⚠️ มีการแก้ไข {len(_any_changes)} รายการ — ยังไม่ได้บันทึก")
                _top_save = _sp2.button("💾 บันทึกแก้ไข", type="primary",
                                        use_container_width=True, key="save_all_fix_top")
            _sc1, _sc2 = st.columns([3, 1])
            _sc1.info(f"แก้ไข {len(_any_changes)} รายการ")
            _bottom_save = _sc2.button("💾 บันทึกแก้ไข", type="primary",
                                       use_container_width=True, key="save_all_fix")
            if _top_save or _bottom_save:
                for _i, _tid, _ch in _any_changes:
                    if "recv" in _ch:
                        _old_r, _new_r = _ch["recv"]
                        _max_r = int(show_df.iloc[_i]["สั่ง"])
                        _new_r = max(0, min(_new_r, _max_r))
                        _delta = _new_r - _old_r
                        if _delta != 0:
                            db.insert_partial_event({
                                "id":             str(uuid.uuid4()),
                                "date":           str(date.today()),
                                "transaction_id": _tid,
                                "qty_received":   _delta,
                                "amount_paid":    0.0,
                                "event_type":     "รับของ",
                            })
                    if "paid" in _ch:
                        _old_p, _new_p = _ch["paid"]
                        _delta_p = _new_p - _old_p
                        if abs(_delta_p) > 0.01:
                            db.insert_partial_event({
                                "id":             str(uuid.uuid4()),
                                "date":           str(date.today()),
                                "transaction_id": _tid,
                                "qty_received":   0,
                                "amount_paid":    _delta_p,
                                "event_type":     "จ่าย",
                            })
                    _txn_upd = {}
                    if "qty"         in _ch: _txn_upd["qty"]          = _ch["qty"]
                    if "total"       in _ch: _txn_upd["total_amount"]  = _ch["total"]
                    if "customer_id" in _ch: _txn_upd["customer_id"]   = _ch["customer_id"]
                    if _txn_upd:
                        db.update_transaction(_tid, _txn_upd)
                    if "bill_status" in _ch or "pay_status" in _ch:
                        db.update_transaction_status(
                            _tid,
                            bill_status=_ch.get("bill_status"),
                            pay_status=_ch.get("pay_status"),
                        )
                st.success("✅ บันทึกแล้ว")
                st.session_state.pop("hist_table", None)
                st.rerun()

        cleared_ids = all_df[all_df["เคลียร์แล้ว"]]["id"].tolist()
        if cleared_ids:
            bc1, bc2 = st.columns([3, 1])
            bc1.caption(f"มี {len(cleared_ids)} รายการที่เคลียร์แล้ว (จ่ายและรับครบ)")
            h_confirm_bulk = bc1.checkbox("ยืนยันลบทั้งหมดที่เคลียร์แล้ว", key="hist_bulk_chk")
            if bc2.button(f"🗑️ ลบเคลียร์แล้วทั้งหมด ({len(cleared_ids)})",
                          disabled=not h_confirm_bulk, use_container_width=True, key="hist_bulk_del"):
                for tid in cleared_ids:
                    db.delete_transaction(tid)
                st.success(f"✅ ลบ {len(cleared_ids)} รายการแล้ว")
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
            if not edit_balance:
                st.warning("ไม่พบรายการนี้ในฐานข้อมูล (อาจถูกลบไปแล้ว)")
                st.stop()
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

    st.divider()
    with st.expander("📦 ประวัติการส่งของ", expanded=False):
        _hist_ships = db.get_shipments(customer_id=h_cid)
        if not _hist_ships:
            st.caption("ไม่มีข้อมูลการส่งของ")
        else:
            _ship_rows_h = []
            for _s in _hist_ships:
                _items_str_h = ", ".join(
                    f"{it.get('name','?')}×{it.get('qty',0)}"
                    for it in (_s.get("items") or [])[:3]
                )
                _src_h = _s.get("source") or "ship"
                _ship_rows_h.append({
                    "วันที่":    (_s.get("created_at") or "")[:10],
                    "แหล่ง":    "📦 ส่งของ" if _src_h == "ship" else "💰 บันทึกขาย",
                    "ลูกค้า":   (_s.get("customers") or {}).get("name", ""),
                    "ขนส่ง":    _s.get("carrier", ""),
                    "Tracking": _s.get("tracking_no", ""),
                    "สินค้า":   _items_str_h,
                })
            _ship_df_h = pd.DataFrame(_ship_rows_h)
            st.dataframe(_ship_df_h, hide_index=True, use_container_width=True)

with _t5_ship:
    st.subheader("ประวัติการส่งของ")

    _sh_cod_col, _sh_status_col, _sh_sync_col = st.columns([4, 2, 2])
    if _sh_status_col.button("🚚 สถานะส่ง", key="sh_status_sync", use_container_width=True):
        _pending_tn = db.get_pending_delivery_tracking()
        if not _pending_tn:
            st.info("ทุก tracking จัดส่งสำเร็จแล้ว")
        else:
            with st.spinner(f"ดึงสถานะ {len(_pending_tn)} tracking..."):
                _sr = iship_api.get_shipment_statuses(days_back=90)
            if _sr.get("error"):
                st.error(f"❌ {_sr['error']}")
            else:
                _to_update = {tn: st for tn, st in _sr["statuses"].items() if tn in set(_pending_tn)}
                if _to_update:
                    db.update_delivery_statuses(_to_update)
                    st.success(f"✅ อัปเดต {len(_to_update)} tracking")
                    st.rerun()
                else:
                    st.info("ไม่มีสถานะใหม่")
                    with st.expander("🔍 debug"):
                        st.write(f"iShip คืนมา {len(_sr['statuses'])} tracking: {list(_sr['statuses'].keys())[:5]}")
                        st.write(f"pending ในระบบ {len(_pending_tn)}: {_pending_tn[:5]}")
                        st.write(f"debug: {_sr.get('_debug')}")
    if _sh_sync_col.button("🔄 ตรวจสอบ COD", key="sh_cod_sync", use_container_width=True):
        try:
            _pending = db.get_pending_cod_tracking()
        except Exception:
            _pending = None  # column ยังไม่มี — ดึงทั้งหมด
        if _pending is not None and len(_pending) == 0:
            st.info("✅ COD ทุกรายการโอนแล้ว ไม่ต้องดึงข้อมูลใหม่")
        else:
            with st.spinner("กำลังดึงข้อมูลจาก iShip..."):
                _r = iship_api.get_cod_transfers(days_back=90)
            if _r.get("error"):
                st.error(f"❌ {_r['error']}")
            else:
                _cod_transfers = _r.get("transfers", {})
                st.session_state["_sh_cod_map"] = _cod_transfers
                if _cod_transfers:
                    try:
                        db.mark_cod_transferred(list(_cod_transfers.keys()))
                    except Exception:
                        pass
                    try:
                        _pending_set = set(_pending or [])
                        _newly = {tn: info.get("date", "")
                                  for tn, info in _cod_transfers.items()
                                  if tn in _pending_set}
                        _n_marked = db.mark_cod_paid(_newly)
                        if _n_marked:
                            st.success(f"✅ บันทึก COD จ่ายแล้ว {_n_marked} รายการ")
                    except Exception:
                        pass
                    st.rerun()
                else:
                    st.info("ยังไม่มี COD ที่โอนแล้วในช่วง 90 วัน")
    _sh_cod_map = st.session_state.get("_sh_cod_map", {})
    # โหลดสถานะที่บันทึกใน DB ด้วย
    try:
        _db_transferred = set(
            r["tracking_no"] for r in
            db.get_supabase().table("shipments")
                .select("tracking_no").not_.is_("cod_transferred_at","null")
                .not_.is_("tracking_no","null").execute().data
            if r.get("tracking_no")
        )
        _sh_cod_map = {**{tn: {} for tn in _db_transferred}, **_sh_cod_map}
    except Exception:
        pass
    if _sh_cod_map:
        _sh_cod_col.caption(f"✅ COD โอนแล้ว {len(_sh_cod_map)} tracking")

    # ── filter ลูกค้า ─────────────────────────────────────────────────
    _sh_customers = db.get_customers()
    _sh_cust_map  = {c["name"]: c["id"] for c in _sh_customers}
    _sh_cust_opts = ["— ทั้งหมด —"] + sorted(_sh_cust_map.keys(), key=str.casefold)
    _sh_cust_sel  = st.selectbox("ลูกค้า", _sh_cust_opts, key="sh_cust_filter",
                                 label_visibility="collapsed")
    _sh_filter_cid = _sh_cust_map.get(_sh_cust_sel) if _sh_cust_sel != "— ทั้งหมด —" else None

    try:
        _sh_all = db.get_shipments(customer_id=_sh_filter_cid)
    except Exception:
        st.warning("⚙️ ยังไม่ได้สร้าง table shipments")
        _sh_all = []

    if _sh_all:
        def _items_str(items):
            if not items:
                return ""
            return ", ".join(f"{it.get('product_id','')} ×{it.get('qty',0)}" for it in items)

        _sh_ids  = [r["id"] for r in _sh_all]
        def _cod_status(r):
            tn  = r.get("tracking_no", "") or ""
            cod = float(r.get("cod_amount") or 0)
            if cod <= 0:
                return ""
            if tn and tn in _sh_cod_map:
                return "✅"
            return "⏳"

        def _delivery_icon(status: str) -> str:
            if not status:
                return ""
            if "จัดส่งแล้ว" in status:
                return "✅"
            if "ตีกลับ" in status or "ยกเลิก" in status:
                return "❌"
            return "🚚"

        def _src_icon(r):
            s = r.get("source", "")
            if s == "sale": return "💰"
            if s == "ship": return "📦"
            return "—"

        _sh_df   = pd.DataFrame([{
            "ลบ":              False,
            "📤":              False,
            "แหล่ง":           _src_icon(r),
            "วันที่/เวลา":     _to_bkk(r.get("created_at") or ""),
            "ลูกค้า":          (r.get("customers") or {}).get("name", ""),
            "COD":             float(r.get("cod_amount") or 0),
            "💸":              _cod_status(r),
            "สถานะส่ง":        (_delivery_icon(r.get("delivery_status") or "") + " " +
                                (r.get("delivery_status") or "")).strip(),
            "ผู้รับ":           r.get("recipient_name", ""),
            "เบอร์":            r.get("phone", ""),
            "รายการ":          _items_str(r.get("items")),
            "ขนส่ง":           r.get("carrier", ""),
            "Tracking":        r.get("tracking_no", "") or "",
            "🔗":              (f"https://app.iship.cloud/tracking?track={r['tracking_no']}"
                               if r.get("tracking_no") else ""),
            "บ้านเลขที่/ถนน":  r.get("address_line", ""),
            "ตำบล":            r.get("district", ""),
            "อำเภอ":           r.get("amphure", ""),
            "จังหวัด":         r.get("province", ""),
            "รหัสปณ.":         r.get("postal_code", ""),
            "หมายเหตุ":        r.get("notes", ""),
        } for r in _sh_all])

        _sh_edit = st.data_editor(
            _sh_df,
            hide_index=True, use_container_width=False, key="sh_hist_tbl",
            disabled=["แหล่ง","วันที่/เวลา","ลูกค้า","ผู้รับ","เบอร์",
                      "บ้านเลขที่/ถนน","ตำบล","อำเภอ","จังหวัด","รหัสปณ.",
                      "รายการ","ขนส่ง","COD","💸","สถานะส่ง","🔗","หมายเหตุ"],
            column_config={
                "ลบ":       st.column_config.CheckboxColumn("ลบ", default=False, width="small"),
                "📤":       st.column_config.CheckboxColumn("📤", default=False, width="small",
                                help="เลือกเพื่อส่ง iShip ใหม่"),
                "แหล่ง":    st.column_config.TextColumn("แหล่ง", width="small",
                                help="🛒 = บันทึกขาย  📦 = ส่งของ"),
                "COD":      st.column_config.NumberColumn("COD", format="%,.0f", width="small"),
                "💸":       st.column_config.TextColumn("💸", width="small"),
                "สถานะส่ง": st.column_config.TextColumn("สถานะส่ง", width="medium"),
                "Tracking": st.column_config.TextColumn("Tracking", width="small"),
                "🔗":       st.column_config.LinkColumn("🔗", width="small", display_text="🔗"),
            },
        )

        # บันทึก Tracking ที่แก้ไข
        for _si, _srow in _sh_edit.iterrows():
            _orig_tn = _sh_df.at[_si, "Tracking"]
            _new_tn  = (_srow["Tracking"] or "").strip()
            if _new_tn != _orig_tn:
                db.update_shipment_tracking(_sh_ids[_si], _new_tn)
                st.session_state.pop("sh_hist_tbl", None)
                st.rerun()

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

        _sh_to_resend = [i for i, v in enumerate(_sh_edit["📤"]) if v]
        if len(_sh_to_resend) > 1:
            st.warning("เลือกได้ทีละ 1 รายการสำหรับส่ง iShip ใหม่")
        elif len(_sh_to_resend) == 1:
            _rs_i        = _sh_to_resend[0]
            _rs_row      = _sh_all[_rs_i]
            _rs_prod_map = {p["id"]: p for p in db.get_products()}
            _rs_items    = _rs_row.get("items") or []
            _rs_total_g  = sum(
                float(_rs_prod_map.get(it.get("product_id", ""), {}).get("weight_grams") or 0) * it.get("qty", 0)
                for it in _rs_items
            )
            _rs_w_def = max(0.5, round((_rs_total_g + BOX_WEIGHT_G) / 1000, 2))
            _rs_w   = st.number_input("น้ำหนักรวมกล่อง (kg)", 0.1, 100.0, _rs_w_def, 0.1, key=f"sh_resend_w_{_rs_i}")
            if st.button("📤 ส่ง iShip ใหม่", type="primary", key="sh_resend_btn"):
                _old_tn = (_rs_row.get("tracking_no") or "").strip()
                st.session_state["_iship_carrier_select"] = {
                    "tab":           "ship",
                    "postcode":      _rs_row.get("postal_code", ""),
                    "weight_kg":     _rs_w,
                    "cod_amount":    float(_rs_row.get("cod_amount") or 0),
                    "customer_name": (_rs_row.get("customers") or {}).get("name", ""),
                    "customer_id":   _rs_row.get("customer_id", ""),
                    "dst_name":      _rs_row.get("recipient_name", ""),
                    "dst_phone":     _rs_row.get("phone", ""),
                    "address_line":  _rs_row.get("address_line", ""),
                    "district":      _rs_row.get("district", ""),
                    "amphure":       _rs_row.get("amphure", ""),
                    "province":      _rs_row.get("province", ""),
                    "items":         _rs_row.get("items") or [],
                    "shipment_id":   _rs_row["id"],
                    "remark":        _rs_row.get("notes", ""),
                }
                if _old_tn:
                    st.session_state["_change_carrier_old_track"] = _old_tn
                st.session_state.pop("sh_hist_tbl", None)
                st.rerun()
    else:
        st.info("ยังไม่มีประวัติการส่งของ")

    # ── เคลียร์ประวัติ ──────────────────────────────────────────────────────
    st.divider()
    with st.expander("🗑️ เคลียร์ประวัติจัดส่งสำเร็จ"):
        st.caption("ลบรายการที่ **จัดส่งสำเร็จ** ทั้งหมดในช่วงวันที่ที่เลือก (ไม่กระทบข้อมูลบิล/ยอดค้าง)")
        _cl_c1, _cl_c2 = st.columns(2)
        _cl_from = _cl_c1.date_input("ตั้งแต่วันที่", value=date(2026, 1, 1), key="sh_clear_from")
        _cl_to   = _cl_c2.date_input("ถึงวันที่",     value=date.today(),      key="sh_clear_to")

        if _cl_from and _cl_to:
            if _cl_from > _cl_to:
                st.warning("วันเริ่มต้นต้องไม่เกินวันสิ้นสุด")
            else:
                _cl_count = db.count_shipped_by_date_range(str(_cl_from), str(_cl_to))
                if _cl_count == 0:
                    st.info("ไม่มีรายการจัดส่งสำเร็จในช่วงนี้")
                else:
                    st.warning(
                        f"⚠️ จะลบ **{_cl_count} รายการ** ที่จัดส่งสำเร็จแล้วระหว่าง "
                        f"{_cl_from.strftime('%d/%m/%Y')} – {_cl_to.strftime('%d/%m/%Y')}"
                    )
                    if st.button(f"🗑️ ลบ {_cl_count} รายการ", type="primary",
                                 key="sh_clear_btn"):
                        _deleted = db.delete_shipped_by_date_range(str(_cl_from), str(_cl_to))
                        st.success(f"✅ ลบแล้ว {_deleted} รายการ")
                        st.session_state.pop("sh_hist_tbl", None)
                        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Tab 6: สต๊อก
# ─────────────────────────────────────────────────────────────────────────────
with tab6:
    t6a, t6b = st.tabs(["📦 สต๊อก", "📋 ของฝาก"])

    with t6b:
        st.subheader("ของที่ลูกค้าฝากไว้")
        _dep_src = db.get_outstanding_df()
        if _dep_src.empty:
            st.info("ไม่มีรายการฝากของ")
        else:
            _dep_df = _dep_src[
                (_dep_src["สถานะบิล"] == "เปิดบิลแล้ว") &
                (_dep_src["ค้างรับ"] > 0)
            ]
            if _dep_df.empty:
                st.info("ไม่มีรายการฝากของ")
            else:
                _total_dep = int(_dep_df["ค้างรับ"].sum())
                _total_cust = _dep_df["ลูกค้า"].nunique()
                _total_prod = _dep_df["สินค้า"].nunique()
                dm1, dm2, dm3 = st.columns(3)
                dm1.metric("ค้างรับรวม", f"{_total_dep} ชิ้น")
                dm2.metric("จำนวนลูกค้า", f"{_total_cust} คน")
                dm3.metric("จำนวนสินค้า", f"{_total_prod} รายการ")
                st.divider()

                # สรุปต่อสินค้า
                _prod_sum = (_dep_df.groupby(["รหัส","สินค้า"], as_index=False)["ค้างรับ"]
                              .sum().rename(columns={"ค้างรับ": "ค้างรับรวม"})
                              .sort_values("ค้างรับรวม", ascending=False))
                st.markdown("**สรุปต่อสินค้า**")
                st.dataframe(_prod_sum, hide_index=True, use_container_width=True)
                st.divider()

                # รายละเอียดต่อลูกค้า แยกตามสินค้า
                st.markdown("**รายละเอียดต่อลูกค้า**")
                for _pname, _pgrp in _dep_df.groupby("สินค้า"):
                    _ptotal = int(_pgrp["ค้างรับ"].sum())
                    with st.expander(f"**{_pname}** — รวม {_ptotal} ชิ้น  ({_pgrp['ลูกค้า'].nunique()} คน)"):
                        _det = _pgrp[["ลูกค้า","เลขที่บิล","วันที่","ค้างรับ"]].reset_index(drop=True)
                        st.dataframe(_det, hide_index=True, use_container_width=True)

    with t6a:
        st.subheader("สรุปสต๊อก")

        products = db.get_products()
        if not products:
            st.warning("⚠️ ยังไม่มีข้อมูลสินค้า")
        else:
            latest_counts   = db.get_latest_stock_counts()
            unbilled_qty    = db.get_unbilled_received_qty_by_product()
            billed_not_rcv  = db.get_billed_not_received_qty_by_product()

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
                    "รหัส":     pid,
                    "สินค้า":   p["name"],
                    "คอม":      qty_system,
                    "นับจริง":  qty_physical,
                    "เบิก":     qty_unbilled,
                    "ฝาก":      qty_billed_wait,
                    "ส่วนต่าง": diff,
                    "สถานะ":   "🔴 เกิน" if diff > 0 else ("🟡 ขาด" if diff < 0 else "✅ ตรง"),
                })

            stock_df = pd.DataFrame(stock_rows)

            with st.form("stock_form"):
                cnt_date = st.date_input("วันที่นับ", value=date.today(), key="stock_cnt_date")
                edited_stock = st.data_editor(
                    stock_df,
                    use_container_width=True,
                    hide_index=True,
                    disabled=["รหัส", "สินค้า", "เบิก", "ฝาก", "ส่วนต่าง", "สถานะ"],
                    column_config={
                        "คอม":      st.column_config.NumberColumn("คอม",     min_value=0, step=1, format="%d"),
                        "นับจริง":  st.column_config.NumberColumn("นับจริง", min_value=0, step=1, format="%d"),
                        "เบิก":     st.column_config.NumberColumn("เบิก",    format="%d"),
                        "ฝาก":      st.column_config.NumberColumn("ฝาก",     format="%d"),
                        "ส่วนต่าง": st.column_config.NumberColumn("ส่วนต่าง", format="%d"),
                    },
                    key="stock_editor",
                )
                st.caption("เบิก = เบิกของไปยังไม่มีบิล  |  ฝาก = เปิดบิลแล้วยังไม่รับของ  |  ส่วนต่าง = คอม − นับจริง + ฝาก − เบิก")
                _stock_submitted = st.form_submit_button("💾 บันทึกการนับสต๊อก", use_container_width=True, type="primary")

            price_by_name = {p["name"]: float(p.get("price") or 0) for p in products}
            pv_by_name    = {p["name"]: float(p.get("points_per_unit") or 0) for p in products}
            _sp = stock_df["สินค้า"].map(price_by_name).fillna(0)
            _sv = stock_df["สินค้า"].map(pv_by_name).fillna(0)
            total_kom_amt  = (stock_df["คอม"].astype(float)      * _sp).sum()
            total_real_amt = (stock_df["นับจริง"].astype(float)  * _sp).sum()
            total_pv       = (stock_df["ส่วนต่าง"].astype(float) * _sv).sum()
            diff_amt       = total_kom_amt - total_real_amt
            sm1, sm2, sm3, sm4 = st.columns(4)
            sm1.metric("📦 ยอดในคอม (฿)", f"{total_kom_amt:,.0f}")
            sm2.metric("🔍 ยอดจริง (฿)",  f"{total_real_amt:,.0f}")
            sm3.metric("⚖️ ส่วนต่าง (฿)", f"{diff_amt:,.0f}", delta=f"{diff_amt:,.0f}" if diff_amt != 0 else None)
            sm4.metric("⭐ คะแนนที่คีย์ได้", f"{total_pv:,.0f} PV")
            st.divider()

            if _stock_submitted:
                saved = 0
                errors = []
                for pid, (_, row) in zip(product_ids, edited_stock.iterrows()):
                    new_sys  = int(row["คอม"])     if pd.notna(row["คอม"])     else 0
                    new_phys = int(row["นับจริง"]) if pd.notna(row["นับจริง"]) else 0
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

    st.divider()

    # ── ตรวจสอบสถานะ COD Transfer ────────────────────────────────────────────
    with st.expander("🔍 ตรวจสอบสถานะ COD (iShip)", expanded=False):
        st.caption("ดึงข้อมูลจาก iShip แล้ว match กับ tracking ใน shipments table")
        if st.button("🔄 ดึงข้อมูล COD Transfer", key="cod_fetch"):
            with st.spinner("กำลัง login และดึงข้อมูล..."):
                _cod_result = iship_api.get_cod_transfers(days_back=60)
            if _cod_result.get("error"):
                st.error(f"❌ {_cod_result['error']}")
            _cod_map = _cod_result.get("transfers", {})
            if _cod_map:
                st.success(f"✅ พบ {len(_cod_map)} tracking ที่โอนแล้ว")
                _cod_df = pd.DataFrame([
                    {"tracking": tn, "วันที่โอน": v["date"], "ยอด COD": v["cod_amount"],
                     "ยอดสุทธิ": v["net"], "สถานะ": v["status"], "WD": v["wd_id"]}
                    for tn, v in _cod_map.items()
                ])
                st.dataframe(_cod_df, use_container_width=True, hide_index=True)
            elif not _cod_result.get("error"):
                st.info("ไม่พบรายการ COD ใน 60 วันที่ผ่านมา")
                st.json(_cod_result.get("_debug", {}))
