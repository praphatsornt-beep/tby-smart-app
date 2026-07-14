import re
import streamlit as st
import pandas as pd
from datetime import date, datetime, timezone, timedelta
import uuid
import io

import database as db
import thai_address
import line_api
from flash_zones import zone_surcharge, flash_base_fee

# ── Constants ────────────────────────────────────────────────────────────────

_BKK = timezone(timedelta(hours=7))

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

BOX_WEIGHT_G = 500  # น้ำหนักกล่อง 0.5 kg (ไม่แสดงในระบบ)

_TAMBON_PREFIXES = ["ตำบล", "ต.", "แขวง"]


def get_bulky_presets() -> list[dict]:
    """preset ขนาดกล่อง (ยาว×กว้าง×สูง ซม.) — จัดการที่แท็บ ⚙️ จัดการข้อมูล → 📐 ขนาดกล่อง
    (เก็บถาวรใน Supabase table `box_presets`) ใช้ร่วมกันทั้งหน้าเลือกขนส่ง iShip (bulky)
    และหน้าปริ้นใบปะหน้า manual — จุดอื่นดึงมาอ่านอย่างเดียว ไม่มีการแก้ไข preset ณ จุดใช้งาน

    คืนลิสต์ว่างถ้าตาราง box_presets ยังไม่ถูกสร้าง (รัน box_presets_setup.sql ก่อน)
    แทนที่จะโยน exception ทำให้ทั้งหน้าล่ม — จุดที่ต้องแจ้งเตือนให้รัน SQL คือ
    master_data_ui.py (เรียก db.get_box_presets() ตรงๆ) อยู่แล้ว
    """
    try:
        _rows = db.get_box_presets()
    except Exception:
        return []
    return [{"name": p["name"], "l": int(p["length_cm"]), "w": int(p["width_cm"]), "h": int(p["height_cm"])}
            for p in _rows]


# ── Functions ────────────────────────────────────────────────────────────────

def _to_bkk(ts: str) -> str:
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(_BKK).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts[:16].replace("T", " ")


def _to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Sheet1") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return buf.getvalue()


def _guard_double_submit(key: str, cooldown_sec: float = 2.0) -> bool:
    """กันกดปุ่มบันทึกซ้ำ (เน็ตช้า/ใจร้อนกดซ้ำก่อนเห็นผลลัพธ์ครั้งแรก) — เรียกทันที
    หลัง st.button(...) คืน True และก่อนเริ่ม insert จริงเสมอ คืน True ถ้าควร
    ดำเนินการบันทึกจริง, False ถ้าเป็นการกดซ้ำภายใน cooldown_sec วินาทีล่าสุด
    (ปุ่มเดียวกัน — key ต้องไม่ซ้ำกับปุ่มอื่น) เป็น pattern เดียวกับ _submit_token
    ที่ใช้กันส่ง iShip order ซ้ำใน app.py แค่ generalize มาใช้กับปุ่มบันทึกทั่วไป
    ที่ไม่ได้อยู่ใน @st.dialog"""
    import time as _time
    _now = _time.time()
    _last = st.session_state.get(f"_dbl_submit_{key}", 0.0)
    st.session_state[f"_dbl_submit_{key}"] = _now
    return (_now - _last) > cooldown_sec


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


def _strip_admin_prefix(s: str, prefixes: list) -> str:
    s = (s or "").strip()
    for p in prefixes:
        if s.startswith(p):
            return s[len(p):].strip()
    return s


def _tambon_search(query: str, limit: int = 40) -> list:
    """ค้นหาตำบลที่ชื่อมีคำนี้เป็นส่วนหนึ่ง (case-insensitive) จำกัดจำนวนผลลัพธ์
    เพื่อไม่ให้ selectbox ต้องขึ้น dropdown ตำบลทั้งประเทศ (~7,500 รายการ) ซึ่งทำให้เบราว์เซอร์หน่วงมาก
    """
    q = _strip_admin_prefix(query, _TAMBON_PREFIXES).strip().lower()
    if len(q) < 2:
        return []
    return [o for o in _tambon_select_options() if q in o["tambon"].lower()][:limit]


def _tambon_selectbox(value_key: str, am_key: str, pv_key: str, pc_key: str,
                       selectbox_key: str, label: str = "ตำบล/แขวง"):
    """ช่อง ตำบล/แขวง แบบพิมพ์ค้นหา — พิมพ์อย่างน้อย 2 ตัวอักษรแล้วเลือกจากรายการที่กรองไว้
    (กรองฝั่งเซิร์ฟเวอร์ก่อนแสดง selectbox เพื่อไม่ให้เบราว์เซอร์ต้องแสดงตำบลทั้งประเทศทีเดียว)
    เลือกแล้ว auto-fill อำเภอ/จังหวัด/รหัสไปรษณีย์ ให้ด้วย
    """
    cur_val = st.session_state.get(value_key, "")
    # ใช้ session_state seeding ตรงๆ แทน value= — ในบริบทซ้อน column/expander
    # ลึกๆ พบว่า value= เฉยๆ ไม่ sync กับ widget จริงเสมอไป (ค่าใน
    # session_state ถูกต้องแต่กล่อง input ยังโชว์ว่างอยู่)
    if selectbox_key not in st.session_state:
        st.session_state[selectbox_key] = cur_val

    query = st.text_input(label, key=selectbox_key, placeholder="พิมพ์ชื่อตำบล เช่น บางรัก")

    if not query.strip() or query.strip() == cur_val.strip():
        return cur_val

    matches = _tambon_search(query)
    if not matches:
        if len(query.strip()) >= 2:
            st.caption("ไม่พบตำบลที่ตรงกับคำค้นหา")
        return cur_val

    if len(matches) == 1:
        # ตรงกันรายการเดียว → เติมให้อัตโนมัติเลย ไม่ต้องกดเลือกซ้ำ
        sel = matches[0]
        st.session_state[value_key] = sel["tambon"]
        st.session_state[am_key]    = sel["amphure"]
        st.session_state[pv_key]    = sel["province"]
        st.session_state[pc_key]    = sel["zipcode"]
        st.session_state.pop(selectbox_key, None)
        st.rerun()

    pick_key = f"_{selectbox_key}_pick"
    idx_options = list(range(len(matches)))
    _label = lambda i: f"{matches[i]['tambon']} / {matches[i]['amphure']} / {matches[i]['province']} ({matches[i]['zipcode']})"

    def _on_pick():
        i = st.session_state.get(pick_key)
        if i is not None:
            sel = matches[i]
            st.session_state[value_key] = sel["tambon"]
            st.session_state[am_key]    = sel["amphure"]
            st.session_state[pv_key]    = sel["province"]
            st.session_state[pc_key]    = sel["zipcode"]
            st.session_state.pop(selectbox_key, None)
            st.session_state.pop(pick_key, None)

    st.selectbox(
        "ผลการค้นหา — เลือกตำบล", idx_options, index=None,
        format_func=_label, key=pick_key, on_change=_on_pick,
    )

    return cur_val


def _postcode_suggest(pc: str, value_key: str, am_key: str, pv_key: str,
                       searchbox_key: str, suggest_key: str,
                       stage_dt: str = "", stage_am: str = "", stage_pv: str = ""):
    """ถ้ารหัสไปรษณีย์ตรงกับ ต./อ./จ. → auto-fill (1 ตำบล) หรือ selectbox (หลายตำบล)"""
    pc = (pc or "").strip()
    if len(pc) != 5:
        return

    def _stage(dt="", am="", pv=""):
        if dt:
            st.session_state[stage_dt or value_key] = dt
            # เคลียร์ searchbox ของตำบลด้วยเสมอ — ถ้า key นี้เคยมีอยู่แล้ว Streamlit
            # จะไม่ยอมอัปเดตค่าที่แสดง (value= ถูกมองข้ามเมื่อ key มีอยู่แล้วใน session_state)
            st.session_state.pop(searchbox_key, None)
        if am: st.session_state[stage_am or am_key] = am
        if pv: st.session_state[stage_pv or pv_key] = pv
        if stage_dt or stage_am or stage_pv:
            st.rerun()

    opts = _tambon_by_postcode(pc)
    if not opts:
        from bangkok_addresses import lookup_from_zipcode
        prov, amph = lookup_from_zipcode(pc)
        if amph and not st.session_state.get(am_key):
            _stage(am=amph, pv=prov)
        return
    cur = (st.session_state.get(value_key, ""), st.session_state.get(am_key, ""), st.session_state.get(pv_key, ""))
    if cur in [(o["tambon"], o["amphure"], o["province"]) for o in opts]:
        return

    if len(opts) == 1:
        _stage(dt=opts[0]["tambon"], am=opts[0]["amphure"], pv=opts[0]["province"])
        if not (stage_dt or stage_am or stage_pv):
            st.rerun()
        return

    _fill_am = ""
    _fill_pv = ""
    _all_provinces = {o["province"] for o in opts}
    if len(_all_provinces) == 1 and not st.session_state.get(pv_key):
        _fill_pv = next(iter(_all_provinces))
    _all_amphures = {o["amphure"] for o in opts}
    if len(_all_amphures) == 1 and not st.session_state.get(am_key):
        _fill_am = next(iter(_all_amphures))
    if _fill_am or _fill_pv:
        _stage(am=_fill_am, pv=_fill_pv)

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


def _extract_tracking(resp: dict) -> str:
    """Extract tracking code from iShip API response (checks data sub-dict then top-level)."""
    _d = resp.get("data") or {}
    return (_d.get("tracking_code") or _d.get("tracking_number")
            or resp.get("tracking_code") or resp.get("tracking_number") or "")


def _extract_iship_order_id(resp: dict) -> str:
    """Extract iShip order ID from create_order response."""
    _d = resp.get("data") or {}
    return str(_d.get("id") or _d.get("order_id") or resp.get("id") or resp.get("order_id") or "")


def _build_success_info(tracking, tab, customer, dst_name, dst_phone, address,
                        carrier, weight_kg, cod_amount, items, line_user_id,
                        shipment_id, group_id="", **extra) -> dict:
    """Build the _iship_success_info dict for storing in session state."""
    d = {
        "tracking":     tracking,
        "tab":          tab,
        "customer":     customer,
        "dst_name":     dst_name,
        "dst_phone":    dst_phone,
        "address":      address,
        "carrier":      carrier,
        "weight_kg":    weight_kg,
        "cod_amount":   cod_amount,
        "items":        items,
        "line_user_id": line_user_id,
        "shipment_id":  shipment_id,
        "group_id":     group_id,
    }
    d.update(extra)
    return d


def _process_old_items_receipt(rx_edit, rx_df, rx_pay_map, pending_rx,
                               event_date: str,
                               collect_ship_items: bool = False) -> tuple:
    """Process receive-old-items loop.

    Returns (saved_count, total_pay, ship_items).
    ship_items is populated only when *collect_ship_items* is True.
    """
    saved_count = 0
    total_pay   = 0.0
    ship_items  = []
    _pe_rows, _paid_full_ids = [], []
    for _ri, _rrow in rx_edit.iterrows():
        _delta      = int(_rrow["รับวันนี้"] or 0)
        _owed_this  = float(rx_df.iloc[_ri]["_owed"])
        _cap        = int(rx_df.iloc[_ri]["_max"])
        _actual_qty = min(max(_delta, 0), _cap)
        if _actual_qty <= 0:
            continue
        _custom_pay = rx_pay_map.get(rx_df.iloc[_ri]["_tid"], 0.0)
        if _custom_pay > 0:
            _apply_pay = round(min(_custom_pay, _owed_this), 2)
        else:
            _apply_pay = round(_owed_this * _actual_qty / _cap, 2) if _owed_this > 0.01 and _cap > 0 else 0.0
        _etype = "ทั้งคู่" if _apply_pay > 0.01 else "รับของ"
        _pe_rows.append({
            "id":             str(uuid.uuid4()),
            "date":           event_date,
            "transaction_id": rx_df.iloc[_ri]["_tid"],
            "qty_received":   _actual_qty,
            "amount_paid":    _apply_pay,
            "event_type":     _etype,
        })
        saved_count += 1
        total_pay   += _apply_pay
        if _apply_pay > 0.01 and _apply_pay >= _owed_this - 0.01:
            _paid_full_ids.append(rx_df.iloc[_ri]["_tid"])
        if collect_ship_items:
            ship_items.append({
                "product_id": pending_rx[_ri]["product_id"],
                "name":       str(_rrow["สินค้า"]),
                "qty":        _actual_qty,
            })
    db.insert_partial_events_batch(_pe_rows)
    db.update_transaction_statuses_batch(_paid_full_ids, pay_status="จ่ายแล้ว")
    return saved_count, total_pay, ship_items


def _quick_add_customer(key_prefix: str):
    """Inline quick-add customer form.

    *key_prefix* differentiates widget keys across tabs (e.g. "" for sale, "sp_" for ship).
    Returns the new customer name (str) when a customer was just created, else None.
    """
    _btn_key   = f"{key_prefix}cust_add_btn"
    _state_key = f"_{key_prefix}adding_cust"
    _form_key  = f"{key_prefix}add_cust_quick"
    _picked_key = f"_{key_prefix}cust_picked"

    if st.button("➕ เพิ่มลูกค้าใหม่", key=_btn_key, width="content"):
        st.session_state[_state_key] = ""
    if _state_key in st.session_state:
        with st.form(_form_key):
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
                st.session_state[_picked_key] = _fn.strip()
                st.session_state.pop(_state_key, None)
                st.rerun()
            if _fc2.form_submit_button("ยกเลิก"):
                st.session_state.pop(_state_key, None)
                st.rerun()
    return None


def _warn_duplicate_phone(phone: str, current_cid: str):
    """ถ้าเบอร์นี้มีที่อยู่ของลูกค้าคนอื่นอยู่แล้ว ให้เตือน (บันทึกที่อยู่จะลบของเดิมทิ้ง)"""
    phone = (phone or "").strip()
    if len(phone) != 10:
        return
    try:
        addr = db.get_address_by_phone(phone)
    except Exception as _e:
        st.caption(f"⚠️ ตรวจสอบเบอร์ซ้ำไม่สำเร็จ ({_e}) — บันทึกที่อยู่ด้วยความระมัดระวัง")
        return
    if addr and addr.get("customer_id") and addr.get("customer_id") != current_cid:
        other_name = (addr.get("customers") or {}).get("name", "")
        other_addr = f"{addr.get('address_line','')} {addr.get('district','')} {addr.get('amphure','')} {addr.get('province','')}".strip()
        st.warning(f"⚠️ เบอร์นี้มีที่อยู่ของคุณ{other_name} อยู่แล้ว ({other_addr}) — ถ้าบันทึกที่อยู่นี้ จะลบที่อยู่เดิมของคุณ{other_name}")


def calc_shipping(weight_grams: float, postcode: str = "") -> float:
    """ค่าส่ง Flash Express: 5 kg แรก 39 บาท, ทุก kg ถัดไป +10 บาท + ค่าพื้นที่"""
    kg = (weight_grams + BOX_WEIGHT_G) / 1000
    return flash_base_fee(kg) + zone_surcharge(postcode)


def raw_weight_g(items, extra_g: float = 0) -> float:
    """รวมน้ำหนักสินค้า (กรัม) จาก [(product, qty, note), ...] — ไม่รวมน้ำหนักกล่อง

    ค่านี้ส่งเข้า calc_shipping()/carrier_fees() ได้โดยตรง — ฟังก์ชันทั้งสองบวก
    BOX_WEIGHT_G ให้เองแล้ว ห้ามบวก BOX_WEIGHT_G ซ้ำก่อนส่งเข้าไป
    """
    return sum(float(p.get("weight_grams") or 0) * q for p, q, _ in items) + extra_g


def _cart_add_items(cart_key: str, items: list) -> None:
    """เพิ่มรายการเข้าตะกร้า (list-based, เก็บใน session_state[cart_key])
    items: [{"product": product_dict, "qty": int}, ...] — ถ้าสินค้าซ้ำ กับที่มีอยู่แล้ว จะรวมจำนวนกัน
    """
    cart = st.session_state.setdefault(cart_key, [])
    for it in items:
        _pid = it["product"]["id"]
        for _row in cart:
            if _row["product_id"] == _pid:
                _row["qty"] += int(it["qty"])
                _row["_qv"] = _row.get("_qv", 0) + 1
                break
        else:
            cart.append({"product_id": _pid, "qty": int(it["qty"]), "_qv": 0})


def _render_cart_card(cart_key: str, products: list, title: str = "บันทึกรายการขาย"):
    """ตะกร้าสไตล์การ์ด (ชื่อ+รหัส/ราคา, ตัวคุมจำนวน −/+, ยอดต่อแถว, ปุ่มลบ ✕)
    แทน st.data_editor เดิม — เก็บสถานะเป็น list ธรรมดาใน session_state[cart_key]
    (ไม่ผูกกับ widget เหมือน data_editor เดิม เลยไม่ต้องใช้กลไก version-bump
    เพื่อ "reset" — แค่ pop คีย์ทิ้งก็พอ เหมือนเดิม)

    คืนค่า valid_items ในรูปแบบเดิม [(product_dict, qty, ""), ...] ให้โค้ดเดิม
    (calc_shipping/cod_fee/iShip payload) ใช้ต่อได้โดยไม่ต้องแก้
    """
    cart = st.session_state.setdefault(cart_key, [])
    _prod_by_id = {p["id"]: p for p in products}

    st.markdown(
        """
        <style>
        [class*="st-key-stepper_"] button[data-testid="stBaseButton-secondary"],
        [class*="st-key-stepper_"] button[data-testid="baseButton-secondary"],
        [class*="st-key-stepper_"] button[kind="secondary"] {
            background: var(--tby-green) !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: 700 !important;
            font-size: 1.15rem !important;
            min-height: 40px !important;
        }
        [class*="st-key-stepper_"] button[data-testid="stBaseButton-secondary"] p,
        [class*="st-key-stepper_"] button[data-testid="baseButton-secondary"] p,
        [class*="st-key-stepper_"] button[kind="secondary"] p {
            color: #ffffff !important;
            font-weight: 700 !important;
            font-size: 1.15rem !important;
        }
        [class*="st-key-stepper_"] button[data-testid="stBaseButton-secondary"]:hover,
        [class*="st-key-stepper_"] button[data-testid="baseButton-secondary"]:hover,
        [class*="st-key-stepper_"] button[kind="secondary"]:hover {
            background: var(--tby-green-dark) !important;
        }
        [class*="st-key-remove_"] button[data-testid="stBaseButton-secondary"],
        [class*="st-key-remove_"] button[data-testid="baseButton-secondary"],
        [class*="st-key-remove_"] button[kind="secondary"] {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
        }
        [class*="st-key-remove_"] button[data-testid="stBaseButton-secondary"] p,
        [class*="st-key-remove_"] button[data-testid="baseButton-secondary"] p,
        [class*="st-key-remove_"] button[kind="secondary"] p {
            color: oklch(0.5 0.15 25) !important;
        }
        [class*="st-key-remove_"] button[data-testid="stBaseButton-secondary"]:hover,
        [class*="st-key-remove_"] button[data-testid="baseButton-secondary"]:hover,
        [class*="st-key-remove_"] button[kind="secondary"]:hover {
            background: oklch(0.94 0.03 25) !important;
        }
        [class*="st-key-remove_"] button[data-testid="stBaseButton-secondary"]:hover p,
        [class*="st-key-remove_"] button[data-testid="baseButton-secondary"]:hover p,
        [class*="st-key-remove_"] button[kind="secondary"]:hover p {
            color: oklch(0.45 0.18 25) !important;
        }
        /* จำนวน — พิมพ์แก้ตรง ๆ ได้ (แทนที่จะกด + ทีละ 1) ซ่อนปุ่ม +/- ของ
           native number_input ทิ้ง เหลือแต่ปุ่มเขียวคู่เดิมข้าง ๆ ไม่ให้ซ้ำกัน */
        [class*="st-key-qtybox_"] [data-testid="stNumberInputStepUp"],
        [class*="st-key-qtybox_"] [data-testid="stNumberInputStepDown"] {
            display: none !important;
        }
        [class*="st-key-qtybox_"] input {
            text-align: center !important;
            font-weight: 700 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.markdown(f"**{title}**")

        if not cart:
            st.caption("ยังไม่มีสินค้าในตะกร้า")
        else:
            _hdr_style = (
                "font-size:0.78rem;font-weight:700;color:oklch(0.55 0.02 150);"
                "padding-bottom:6px;margin-bottom:6px;border-bottom:1.5px solid var(--tby-border)"
            )
            _hh1, _hh2, _hh3, _hh4 = st.columns([3, 2, 1.3, 0.6])
            _hh1.markdown(f"<div style='{_hdr_style}'>สินค้า (รหัส — ชื่อ)</div>", unsafe_allow_html=True)
            _hh2.markdown(f"<div style='{_hdr_style};text-align:center'>จำนวน</div>", unsafe_allow_html=True)
            _hh3.markdown(f"<div style='{_hdr_style};text-align:right'>ยอดรวม</div>", unsafe_allow_html=True)
            _hh4.markdown(f"<div style='{_hdr_style}'>&nbsp;</div>", unsafe_allow_html=True)
            for _i, _row in enumerate(cart):
                _p = _prod_by_id.get(_row["product_id"])
                if not _p:
                    continue
                _qty = int(_row["qty"])
                _line_total = float(_p.get("price") or 0) * _qty
                _rc1, _rc2, _rc3, _rc4 = st.columns([3, 2, 1.3, 0.6])
                with _rc1:
                    st.markdown(f"<div style='font-weight:700;font-size:1.02rem'>{_p['name']}</div>", unsafe_allow_html=True)
                    st.caption(
                        f"{_p['id']} · ฿{float(_p.get('price') or 0):,.0f} · "
                        f"{float(_p.get('points_per_unit') or 0):,.0f} PV"
                    )
                with _rc2:
                    _qv = _row.get("_qv", 0)
                    _qc1, _qc2, _qc3 = st.columns([1, 1.4, 1])
                    with _qc1:
                        with st.container(key=f"stepper_{cart_key}_dec_{_i}"):
                            if st.button("−", key=f"{cart_key}_dec_{_i}", width="stretch"):
                                if _qty - 1 <= 0:
                                    cart.pop(_i)
                                else:
                                    cart[_i]["qty"] = _qty - 1
                                    cart[_i]["_qv"] = _qv + 1
                                st.rerun()
                    with _qc2:
                        with st.container(key=f"qtybox_{cart_key}_{_i}"):
                            _new_qty = st.number_input(
                                "จำนวน", min_value=1, step=1, value=_qty,
                                key=f"qtybox_{cart_key}_{_row['product_id']}_{_qv}",
                                label_visibility="collapsed",
                            )
                        if int(_new_qty) != _qty:
                            cart[_i]["qty"] = int(_new_qty)
                            st.rerun()
                    with _qc3:
                        with st.container(key=f"stepper_{cart_key}_inc_{_i}"):
                            if st.button("+", key=f"{cart_key}_inc_{_i}", width="stretch"):
                                cart[_i]["qty"] = _qty + 1
                                cart[_i]["_qv"] = _qv + 1
                                st.rerun()
                with _rc3:
                    st.markdown(f"<div style='padding-top:8px;font-weight:700;font-size:1rem;text-align:right'>฿{_line_total:,.0f}</div>", unsafe_allow_html=True)
                with _rc4:
                    with st.container(key=f"remove_{cart_key}_{_i}"):
                        if st.button("✕", key=f"{cart_key}_rm_{_i}", width="stretch"):
                            cart.pop(_i)
                            st.rerun()

            st.divider()
            _total = sum(float(_prod_by_id.get(r["product_id"], {}).get("price") or 0) * int(r["qty"]) for r in cart)
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;align-items:baseline'>"
                f"<span style='font-size:0.95rem;color:oklch(0.55 0 0)'>ยอดรวม</span>"
                f"<span style='font-size:1.4rem;font-weight:800;color:var(--tby-accent)'>฿{_total:,.0f}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    return [(_prod_by_id[r["product_id"]], int(r["qty"]), "") for r in cart if r["product_id"] in _prod_by_id]


def _style_status(val):
    """Pill-badge colors (light bg + dark text, matching the good/warn/bad
    badge language used across the reference design) instead of the old
    solid-dark-bg-white-text look.

    NOTE: hex, not oklch() — this feeds pandas Styler.map() for st.dataframe,
    which renders cells on a <canvas> (glide-data-grid). Canvas 2D fillStyle
    doesn't parse oklch() in this Streamlit/browser combo; the assignment
    silently fails and the PREVIOUS cell's fill color carries over, which
    shows up as random solid-color blocks that "stick" as you scroll/hover.
    oklch() is fine everywhere else in the app (real CSS via markdown/HTML),
    just not here. """
    _good = "background-color:#E6F4EA;color:#1E7B34;font-weight:600"
    _warn = "background-color:#FFF4E0;color:#B26A00;font-weight:600"
    _bad  = "background-color:#FDECEA;color:#C0392B;font-weight:600"
    colors = {
        "เปิดบิลแล้ว":   _good,
        "ยังไม่เปิดบิล": _warn,
        "จ่ายแล้ว":      _good,
        "ค้างจ่าย":      _bad,
        "COD":          _warn,
        "COD จ่ายแล้ว":  _good,
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
    free = _re.sub(r"#\w+", "", free).strip()
    if free:
        labels.append(free)
    return " ".join(labels)


def _extract_staff_tag(notes: list) -> str:
    """หา #tag (เช่น #milk) จาก notes ของรายการในบิล คืนชื่อไม่มี # หรือ '' ถ้าไม่เจอ"""
    import re as _re
    for note in notes:
        _m = _re.search(r"#(\w+)", str(note or ""))
        if _m:
            return _m.group(1)
    return ""


def _ledger_to_txn_df(ledger_data: list) -> pd.DataFrame:
    """แปลง get_customer_ledger() data → DataFrame เทียบเท่า get_all_transactions_df()
    โดยไม่ต้อง query Supabase ซ้ำ (ledger ดึงข้อมูล transactions+partial_events มาแล้ว)"""
    orders   = [r for r in ledger_data if r["type"] == "สั่งซื้อ"]
    payments = [r for r in ledger_data if r["type"] == "จ่ายเงิน"]
    receipts = [r for r in ledger_data if r["type"] in ("รับของ", "แก้ไขรับ")]
    if not orders:
        return pd.DataFrame()

    from collections import defaultdict
    paid_by_txn = defaultdict(float)
    for p in payments:
        paid_by_txn[p["txn_id"]] += p["amount"]
    recv_by_txn = defaultdict(int)
    for r in receipts:
        recv_by_txn[r["txn_id"]] += r["qty_out"]

    rows = []
    for o in orders:
        tid = o["txn_id"]
        total_amount = float(o.get("total_amount") or 0)
        pay_status   = o.get("pay_status") or ""
        _pseudo_txn = {
            "total_amount": total_amount, "pay_status": pay_status,
            "initial_qty_received": o.get("initial_received", 0), "qty": o["qty_in"],
        }
        bal = db._compute_balance(_pseudo_txn, paid_by_txn.get(tid, 0.0), recv_by_txn.get(tid, 0))
        total_paid = bal["total_paid"]
        total_received = bal["total_received"]
        outstanding_amount = bal["outstanding_amount"]
        outstanding_qty = bal["outstanding_qty"]
        cleared = outstanding_amount <= 0.01 and outstanding_qty <= 0 and o.get("bill_status") == "เปิดบิลแล้ว"
        rows.append({
            "id": tid, "วันที่": o["date"], "รหัส": o.get("product_id", ""),
            "สินค้า": o["product"], "สั่ง": o["qty_in"], "รับแล้ว": total_received,
            "ยอดรวม": total_amount, "จ่ายแล้ว": total_paid,
            "ค้างจ่าย": max(0.0, outstanding_amount), "ค้างรับ": max(0, outstanding_qty),
            "สถานะบิล": o.get("bill_status") or "ยังไม่เปิดบิล", "สถานะจ่าย": pay_status,
            "หมายเหตุ": o.get("notes", "") or "", "PV รวม": o.get("pv", 0.0),
            "เลขที่บิล": o.get("bill_no") or "", "เคลียร์แล้ว": cleared,
        })
    df = pd.DataFrame(rows)
    df.sort_values("วันที่", ascending=False, inplace=True)
    return df.reset_index(drop=True)


def _bills_from_df(df: pd.DataFrame) -> pd.DataFrame:
    """รวมรายการในแต่ละบิล (groupby เลขที่บิล) คืน DataFrame หนึ่งแถวต่อบิล:
    เลขที่บิล, วันที่, ยอดรวม, ค้างจ่าย, ค้างรับ, is_paid, is_billed, pv_unbilled
    """
    _cols = ["เลขที่บิล", "วันที่", "ยอดรวม", "ค้างจ่าย", "ค้างรับ", "is_paid", "is_billed", "pv_unbilled"]
    if df.empty:
        return pd.DataFrame(columns=_cols)

    _bills = (df.groupby("เลขที่บิล", dropna=False)
              .agg(วันที่=("วันที่", "max"),
                   ยอดรวม=("ยอดรวม", "sum"),
                   ค้างจ่าย=("ค้างจ่าย", "sum"),
                   ค้างรับ=("ค้างรับ", "sum"),
                   is_billed=("สถานะบิล", lambda x: (x == "เปิดบิลแล้ว").all()))
              .reset_index()
              .sort_values("วันที่", ascending=False))
    _bills["is_paid"] = _bills["ค้างจ่าย"] <= 0.01

    _pv_col = "PV รวม" if "PV รวม" in df.columns else None
    if _pv_col:
        _pv_map = (df[df.get("สถานะบิล", pd.Series(dtype=str)) == "ยังไม่เปิดบิล"]
                   .groupby("เลขที่บิล")[_pv_col].sum())
        _bills["pv_unbilled"] = _bills["เลขที่บิล"].map(_pv_map).fillna(0)
    else:
        _bills["pv_unbilled"] = 0

    return _bills


def _render_bill_panel(sel_p, cust_map_p, all_txn_cache, customers_p, key_prefix, preselected_bill=None):
    """แสดงส่วนเลือกบิล / พิมพ์บิล / จัดการบิล สำหรับลูกค้า sel_p
    preselected_bill: ถ้าระบุ ข้ามตัวเลือกบิล แสดงบิลนี้ตรง ๆ (ใช้กับค้นด้วยเลขที่บิล)
    key_prefix: prefix สำหรับ widget key / session_state กันชนกันเมื่อเรียกซ้ำหลายลูกค้า
    all_txn_cache: ถ้าเป็น None จะดึงเองตาม context (lazy load)
    """
    if all_txn_cache is None:
        if preselected_bill:
            all_txn_cache = db.get_all_transactions_df(bill_no=preselected_bill)
        else:
            _cust_obj = cust_map_p.get(sel_p)
            _cid = _cust_obj["id"] if _cust_obj else None
            all_txn_cache = db.get_all_transactions_df(customer_id=_cid)

    if preselected_bill:
        if all_txn_cache.empty or "เลขที่บิล" not in all_txn_cache.columns:
            st.warning(f"ไม่พบบิล {preselected_bill}")
            return
        all_df_p = all_txn_cache[all_txn_cache["เลขที่บิล"] == preselected_bill]
        if all_df_p.empty:
            st.warning(f"ไม่พบบิล {preselected_bill}")
            return
        _cust_names_p = all_df_p["ลูกค้า"].unique()
        if len(_cust_names_p) > 1:
            st.error(
                f"🚨 เลขที่บิล {preselected_bill} นี้ถูกใช้ซ้ำกันโดยหลายลูกค้า "
                f"({', '.join(_cust_names_p)}) — ไม่แสดงรายละเอียดบิลนี้จนกว่าจะแก้เลขบิลให้ไม่ซ้ำกันก่อน "
                "(ผ่าน 'ประวัติทั้งหมด' > แก้ไขรายการ)"
            )
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

            _bills = _bills_from_df(all_df_p)

            if len(_bills) == 1:
                st.session_state[_pk] = _bills.iloc[0]["เลขที่บิล"] or "—"
                st.rerun()
            st.caption("เลือกบิลที่ต้องการพิมพ์")
            _total_owed    = _bills["ค้างจ่าย"].sum()
            _total_pending = int(_bills["ค้างรับ"].sum())
            _total_pv_unbilled = _bills["pv_unbilled"].sum()
            _all_color    = "🔴" if _total_owed > 0.01 else "✅"
            _all_pv_str   = f" &nbsp; ⭐ {_total_pv_unbilled:,.0f} PV" if _total_pv_unbilled > 0 else ""
            _all_recv_str = f" &nbsp; 📦 ยังไม่รับของ {_total_pending} ชิ้น" if _total_pending > 0 else ""
            if st.button(
                f"📋 **รวมทุกบิล** &nbsp; {_all_color} ค้างจ่ายรวม {_total_owed:,.0f} บาท{_all_recv_str}{_all_pv_str}",
                key=f"{key_prefix}_pbill_ALL", width="stretch"):
                st.session_state[_pk] = "__ALL__"
                st.rerun()
            st.divider()
            for _, _br in _bills.iterrows():
                _bno      = _br["เลขที่บิล"] or "—"
                _owing    = _br["ค้างจ่าย"]
                _pending  = int(_br["ค้างรับ"])
                _color    = "🔴" if _owing > 0.01 else "✅"
                _pv_un    = _br["pv_unbilled"]
                _pv_str   = f" &nbsp; ⭐ {_pv_un:,.0f} PV" if _pv_un > 0 else ""
                _recv_str = f" &nbsp; 📦 ยังไม่รับของ {_pending} ชิ้น" if _pending > 0 else ""
                _lbl = (f"📄 **{_bno}** &nbsp; {_br['วันที่']} &nbsp; "
                        f"{_color} ค้างจ่าย {_owing:,.0f} บาท{_recv_str}{_pv_str}")
                if st.button(_lbl, key=f"{key_prefix}_pbill_{_bno}", width="stretch"):
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
          <td><b>{r.get('รหัส','')}</b></td>
          <td>{r['สินค้า']}</td>
          <td style="text-align:center"><b>{int(r['สั่ง'])}</b></td>
          <td style="text-align:center">{int(r['รับแล้ว'])}</td>
          <td style="text-align:right"><b>{r['ยอดรวม']:,.0f}</b></td>
          <td style="text-align:right">{r['จ่ายแล้ว']:,.0f}</td>
          <td style="text-align:right;color:{owed_color};font-weight:700">{r['ค้างจ่าย']:,.0f}</td>
          <td style="text-align:center;color:{bill_color}">{r['สถานะบิล']}</td>
          <td>{_fmt_note(r.get('หมายเหตุ','') or '')}</td>
        </tr>"""

    total_amount      = show_p["ยอดรวม"].sum()
    total_paid        = show_p["จ่ายแล้ว"].sum()
    total_outstanding = show_p["ค้างจ่าย"].sum()
    unbilled_pv       = show_p.loc[show_p["สถานะบิล"] == "ยังไม่เปิดบิล", "PV รวม"].sum() if "PV รวม" in show_p.columns else 0
    today_str         = date.today().strftime("%d/%m/%Y")
    filter_label      = "รายการทั้งหมด"
    bill_nos          = show_p["เลขที่บิล"].dropna().unique().tolist() if "เลขที่บิล" in show_p.columns else []
    bill_nos_str      = ", ".join(b for b in bill_nos if b) or ""
    staff_tag         = _extract_staff_tag(show_p.get("หมายเหตุ", pd.Series(dtype=str)).tolist())
    _last_paid_raw    = show_p["last_payment_date"].replace("", None).max() if "last_payment_date" in show_p.columns else None
    try:
        _paid_date_str = pd.to_datetime(_last_paid_raw).strftime("%d/%m/%Y") if _last_paid_raw else "—"
    except Exception:
        _paid_date_str = "—"

    # ตรวจสอบว่ามี tag ส่งพัสดุจาก notes ของรายการแรก
    first_note = str(show_p.iloc[0].get("หมายเหตุ", "") or "")
    is_ship_bill = "[ส่งพัสดุ|" in first_note
    ship_weight_str, ship_fee_str = "", ""
    if is_ship_bill:
        import re as _re
        _m = _re.search(
            r"\[ส่งพัสดุ\|([^|]+)?\|?(\d{5})?\|?น้ำหนัก=([\d.]+)kg\|ค่าส่ง=(\d+)([^\]]*)\]",
            first_note
        )
        if _m:
            ship_weight_str = _m.group(3) or ""
            ship_fee_str    = _m.group(4) or ""

    bm1, bm2 = st.columns(2)
    bm1.metric("💸 ยอดค้างจ่ายรวม",  f"{total_outstanding:,.0f} บาท")
    bm2.metric("⭐ PV ยังไม่เปิดบิล", f"{unbilled_pv:,.0f}")

    _ship_row_html = (
        f"<tr><td>⚖️ น้ำหนัก {ship_weight_str} kg &nbsp; 🚚 ค่าส่ง</td>"
        f"<td><b style='color:#1a5c8e'>{ship_fee_str} บาท</b></td></tr>"
    ) if is_ship_bill and ship_fee_str else ""

    _staff_row_html = (
        f"<tr><td>ผู้บันทึก</td><td>{staff_tag}</td></tr>"
    ) if staff_tag else ""

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
    {_staff_row_html}
  </table>
</div>"""

    _css = """
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Prompt',sans-serif;padding:16px;color:#111;background:#fff;font-size:13px}
  .header{border-bottom:2px solid #000;padding-bottom:8px;margin-bottom:12px}
  .header h1{font-size:16px;font-weight:700}
  .header h2{font-size:14px;font-weight:600;margin-top:2px}
  .info{color:#333;font-size:11px;margin-top:2px}
  table{width:100%;border-collapse:collapse;margin-top:5px;border:1px solid #000}
  th{background:#000;color:#fff;padding:5px 6px;text-align:left;font-size:12px;border:1px solid #000}
  td{padding:4px 6px;border:1px solid #aaa;font-size:12px}
  tr:nth-child(even) td{background:#f0f0f0}
  .summary{margin-top:12px;border-top:2px solid #000;padding-top:8px;text-align:right}
  .summary table{width:auto;margin-left:auto;border:none}
  .summary td{padding:3px 8px;border:none;font-size:13px}
  .big td{font-weight:900;font-size:15px;border-top:2px solid #000;padding-top:5px}
  .btn{display:block;margin:0 auto 14px;padding:7px 28px;background:#c0392b;color:#fff;
       border:none;border-radius:6px;font-size:13px;cursor:pointer}
  @media print{
    .btn{display:none}
    @page{size:A5;margin:8mm}
    *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
    body{color:#000!important;font-size:12px}
    th{background:#000!important;color:#fff!important;border:1px solid #000}
    td{border-bottom:1px solid #999!important;color:#000!important}
    tr:nth-child(even) td{background:#eee!important}
    .info{color:#333!important}
    b[style],span[style],[style*="color"]{color:#000!important}
    .summary .big td{font-weight:900}
  }"""

    _body = _bill_body("")
    _height = 550

    bill_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{_css}</style></head><body>
<button class="btn" onclick="window.print()">🖨️ พิมพ์</button>
{_body}
<br><button class="btn" onclick="window.print()">🖨️ พิมพ์</button>
</body></html>"""

    st.iframe(bill_html, height=_height)

    # ── ส่งสรุปบิล LINE ─────────────────────────────────────
    _t7_cust_name = show_p["ลูกค้า"].iloc[0] if not show_p.empty else sel_p
    _t7_cust_id   = cust_map_p.get(_t7_cust_name, {}).get("id", "")
    _t7_line_uid, _t7_gid = db.get_customer_line_ids(_t7_cust_id) if _t7_cust_id else ("", "")
    _t7_items = [{"name": r["สินค้า"], "qty": int(r["สั่ง"]),
                  "total": float(r["ยอดรวม"])} for _, r in show_p.iterrows()]
    _t7_pay = show_p.iloc[0].get("สถานะบิล", "") if not show_p.empty else ""
    _t7_col1, _t7_col2 = st.columns([1, 2])
    if _t7_col1.button("📨 ส่งสรุปบิล LINE", key=f"{key_prefix}_line_btn",
                       disabled=not bool(_t7_line_uid),
                       help="ส่งสรุปให้ลูกค้าใน LINE" if _t7_line_uid else "ลูกค้าไม่มี LINE ID"):
        _r7 = line_api.push_bill_summary(
            _t7_line_uid, _t7_cust_name, bill_nos_str,
            _t7_items, total_amount, _t7_pay,
            paid_amount=total_paid, outstanding_amount=total_outstanding,
            group_id=_t7_gid,
        )
        if _r7["ok"]:
            st.success("✅ ส่ง LINE แล้ว")
        else:
            st.error(f"LINE error: {_r7['error']}")

    # ── จัดการบิล ────────────────────────────────────────────
    _t7_tids = show_p["id"].tolist()
    _t7_single = len(bill_nos) == 1 and bill_nos[0]

    # ── ปุ่มแจ้ง LINE หลังบันทึกรับเงิน ─────────────────────────
    _pay_line = st.session_state.get(f"{key_prefix}_pay_line")
    if _pay_line and _t7_line_uid:
        _pl1, _pl2, _pl3 = st.columns([3, 1, 1])
        _pl1.info(f"💰 บันทึกรับเงิน {_pay_line['amount_paid']:,.0f} ฿ แล้ว")
        if _pl2.button("📨 แจ้ง LINE", key=f"{key_prefix}_pay_line_btn", type="primary", width="stretch"):
            _lr = line_api.push_partial_receipt(
                _t7_line_uid, "", 0, _pay_line["amount_paid"],
                0, _pay_line.get("remaining_amount", 0),
                group_id=_t7_gid,
                items=_pay_line.get("items"),
            )
            if _lr.get("ok"):
                del st.session_state[f"{key_prefix}_pay_line"]
                st.success("✅ ส่ง LINE แล้ว")
            else:
                st.error(_lr.get("error"))
        if _pl3.button("✕", key=f"{key_prefix}_pay_line_cls", width="stretch"):
            del st.session_state[f"{key_prefix}_pay_line"]
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
                         width="stretch"):
                _owed_rows = show_p[show_p["ค้างจ่าย"] > 0.01].reset_index(drop=True)
                _owed_ids  = _owed_rows["id"].tolist()
                _row_owed  = _owed_rows["ค้างจ่าย"].tolist()
                _total_row_owed = sum(_row_owed)
                _remaining = float(_t7_pay_amt)
                _pe_rows = []
                for _pi, (_tid_p, _row_o) in enumerate(zip(_owed_ids, _row_owed)):
                    if _remaining <= 0:
                        break
                    if _pi == len(_owed_ids) - 1:
                        _share = _remaining
                    else:
                        _share = round(_row_o / _total_row_owed * float(_t7_pay_amt), 2)
                        _share = min(_share, _remaining)
                    _pe_rows.append({
                        "id":             str(uuid.uuid4()),
                        "date":           str(_t7_pay_date),
                        "transaction_id": _tid_p,
                        "qty_received":   0,
                        "amount_paid":    _share,
                        "event_type":     "จ่ายเงิน",
                    })
                    _remaining -= _share
                db.insert_partial_events_batch(_pe_rows)
                if float(_t7_pay_amt) >= _t7_owed - 0.01:
                    db.update_transaction_statuses_batch(_t7_tids, pay_status="จ่ายแล้ว")
                if _t7_line_uid and line_api.is_configured():
                    _rem_after = max(0.0, _t7_owed - float(_t7_pay_amt))
                    st.session_state[f"{key_prefix}_pay_line"] = {
                        "amount_paid": float(_t7_pay_amt),
                        "remaining_amount": _rem_after,
                        "items": [{"product_name": r["สินค้า"], "product_code": r.get("รหัส", ""), "qty_received": 0}
                                  for _, r in show_p.iterrows()],
                    }
                st.success(f"✅ บันทึกรับเงิน {_t7_pay_amt:,.0f} ฿ แล้ว")
                st.rerun()

    if _t7_single:
        with st.expander("📦 บันทึกรับของ"):
            _recv_base = show_p[["สินค้า","สั่ง","รับแล้ว","ค้างรับ"]].copy().reset_index(drop=True)
            _recv_ids  = show_p["id"].reset_index(drop=True)
            _recv_base["รับเพิ่ม"] = pd.Series([0]*len(_recv_base), dtype="int64")
            _recv_edit = st.data_editor(
                _recv_base,
                hide_index=True, width="stretch",
                column_config={
                    "รับเพิ่ม": st.column_config.NumberColumn("รับเพิ่ม", min_value=0, step=1, width="small"),
                },
                disabled=["สินค้า","สั่ง","รับแล้ว","ค้างรับ"],
                key=f"{key_prefix}_recv_edit"
            )
            if st.button("💾 บันทึกรับของ", key=f"{key_prefix}_save_recv"):
                _saved_r = 0
                _pe_rows = []
                for _ri, _rrow in _recv_edit.iterrows():
                    _delta = int(_rrow["รับเพิ่ม"] or 0)
                    if _delta <= 0:
                        continue
                    _cap = int(_recv_base.iloc[_ri]["ค้างรับ"])
                    _delta = min(_delta, _cap)
                    _pe_rows.append({
                        "id":             str(uuid.uuid4()),
                        "date":           str(date.today()),
                        "transaction_id": _recv_ids.iloc[_ri],
                        "qty_received":   _delta,
                        "amount_paid":    0.0,
                        "event_type":     "รับของ",
                    })
                    _saved_r += 1
                db.insert_partial_events_batch(_pe_rows)
                if _saved_r:
                    st.success(f"✅ บันทึกรับของ {_saved_r} รายการ")
                    st.rerun()
                else:
                    st.warning("ไม่มีรายการที่เปลี่ยนแปลง")

    # ── แก้ไขเพิ่มเติม (เปลี่ยนลูกค้า / ลบบิล) ─────────────────
    with st.expander("⚙️ แก้ไขเพิ่มเติม"):
        st.markdown("**✏️ เปลี่ยนลูกค้าในบิลนี้**")
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
            st.divider()
            st.markdown("**🗑️ ลบบิล**")
            st.dataframe(show_p[["สินค้า", "สั่ง", "ยอดรวม"]], width="stretch", hide_index=True)
            st.warning(f"⚠️ จะลบบิล **{bill_nos[0]}** ({_t7_total_amt:,.0f} ฿) และรายการทั้งหมดข้างต้น ({len(show_p)} รายการ) — กู้คืนไม่ได้")
            _t7_del_chk = st.checkbox("ยืนยันการลบ", key=f"{key_prefix}_del_confirm")
            if st.button("🗑️ ลบบิล", disabled=not _t7_del_chk,
                         type="secondary", key=f"{key_prefix}_del_bill"):
                db.delete_bill(bill_nos[0])
                st.success("✅ ลบบิลแล้ว")
                if not preselected_bill:
                    st.session_state.pop(_pk, None)
                st.rerun()

    with st.expander("🗑️ ลบรายการ"):
        st.caption("เลือกรายการสินค้าที่ต้องการลบออก (ไม่ลบทั้งบิล) — เลือกได้หลายรายการ")
        _t7_item_opts = {
            f"{r['สินค้า']} — บิล {r['เลขที่บิล'] or '—'} (฿{r['ยอดรวม']:,.0f})": r["id"]
            for _, r in show_p.iterrows()
        }
        _t7_del_item_labels = st.multiselect(
            "รายการ", list(_t7_item_opts.keys()), key=f"{key_prefix}_del_item_sel"
        )
        _t7_del_item_chk = st.checkbox(
            f"ยืนยันการลบ {len(_t7_del_item_labels)} รายการนี้",
            key=f"{key_prefix}_del_item_confirm", disabled=not _t7_del_item_labels,
        )
        if st.button("🗑️ ลบรายการ", disabled=not (_t7_del_item_chk and _t7_del_item_labels),
                     type="secondary", key=f"{key_prefix}_del_item_btn"):
            db.delete_transactions_batch([_t7_item_opts[_lbl] for _lbl in _t7_del_item_labels])
            st.success(f"✅ ลบ {len(_t7_del_item_labels)} รายการแล้ว")
            if not preselected_bill:
                st.session_state.pop(_pk, None)
            st.rerun()

    # ── เคลียร์บิลหลายใบ ──────────────────────────────────────
    _t7_all_cust_df = all_txn_cache[all_txn_cache["ลูกค้า"] == _t7_cust_name]
    if not _t7_all_cust_df.empty:
        _t7_bill_grp = _bills_from_df(_t7_all_cust_df)
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
                    _clr_all_tids = _t7_all_cust_df[
                        _t7_all_cust_df["เลขที่บิล"].isin(_clr_sel)
                    ]["id"].tolist()
                    db.update_transaction_statuses_batch(
                        _clr_all_tids, pay_status="จ่ายแล้ว", bill_status="เปิดบิลแล้ว",
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

    # ── Format 0: multi-line (ชื่อ / เบอร์ / ที่อยู่) ───────────────────
    if (len(_lines) >= 3
        and not _re.search(r'0[6-9]\d{8}', _lines[0])
        and _re.fullmatch(r'0[6-9]\d{8}', _lines[1])):
        r["dst_name"]  = _lines[0].strip()
        r["dst_phone"] = _lines[1].strip()
        _addr_rest = " ".join(_lines[2:])
        _mz = _re.search(r'(?<!\d)([1-9]\d{4})(?!\d)', _addr_rest)
        if _mz:
            r["zipcode"] = _mz.group(1)
        _dt = _re.search(r'[ตแ](?:ำบล|ขวง)?\.\s*(\S+)', _addr_rest)
        _am = _re.search(r'[อเ](?:ำเภอ|ขต)?\.\s*(\S+)', _addr_rest)
        _pv = _re.search(r'จ(?:ังหวัด)?\.\s*(\S+)', _addr_rest)
        if _dt: r["district"] = _dt.group(1)
        if _am: r["amphure"]  = _am.group(1)
        if _pv: r["province"] = _pv.group(1)
        _clean = _addr_rest
        for _pat in [r'[ตแ](?:ำบล|ขวง)?\.\s*\S+', r'[อเ](?:ำเภอ|ขต)?\.\s*\S+',
                     r'จ(?:ังหวัด)?\.\s*\S+', r'(?<!\d)[1-9]\d{4}(?!\d)']:
            _clean = _re.sub(_pat, '', _clean)
        r["address_line"] = _re.sub(r'\s+', ' ', _clean).strip()
        return r

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


def _parse_quick_order(text: str, products: list) -> tuple:
    """แยกข้อความเป็น token คั่นด้วยเว้นวรรค แต่ละ token = รหัสสินค้า (เต็มหรือแค่บางส่วน
    ตรงไหนก็ได้ของรหัส ไม่ใช่แค่ขึ้นต้น — เช่น "2581" match "TF2581" ได้) ตามด้วย -จำนวน
    ได้ (ไม่ใส่ = 1 ชิ้น) หรือเว้นวรรคแล้วตามด้วยตัวเลขล้วนๆ ก็ได้เหมือนกัน เช่น "TF2581 3"
    (ใช้ได้เฉพาะตอนโค้ดก่อนหน้า match สินค้าได้ชัดเจนแล้วเท่านั้น กันไปกินโค้ดสินค้าจริงที่
    บังเอิญเป็นตัวเลขล้วน) ถ้าเจอมากกว่า 1 ตัวหรือไม่เจอเลย จะติด unknown พร้อมเหตุผล
    """
    product_by_id = {p["id"].upper(): p for p in products}
    tokens = text.strip().split()
    found, unknown = [], []
    i, n = 0, len(tokens)
    while i < n:
        token = tokens[i]
        qty = 1
        code_part = token
        parts = token.rsplit("-", 1)
        if len(parts) == 2 and parts[1].isdigit() and int(parts[1]) > 0:
            code_part, qty = parts[0], int(parts[1])
        code_up = code_part.upper()

        p = product_by_id.get(code_up)
        matches = [p] if p else [pr for pr in products if code_up in pr["id"].upper()]

        if qty == 1 and len(matches) == 1 and i + 1 < n and tokens[i + 1].isdigit() and int(tokens[i + 1]) > 0:
            qty = int(tokens[i + 1])
            i += 1

        if len(matches) == 1:
            found.append({"product": matches[0], "qty": qty})
        elif len(matches) > 1:
            unknown.append(f"{code_part} (พบ {len(matches)} รายการ ระบุให้ชัดเจนขึ้น)")
        else:
            unknown.append(code_part)
        i += 1
    return found, unknown


def _pick_carrier(pc: str, kg: float = 0) -> str:
    is_metro = pc[:2] in {"10", "11", "12"}
    return "Flash Express" if (kg <= 3 and not is_metro) else "SPX Express"
