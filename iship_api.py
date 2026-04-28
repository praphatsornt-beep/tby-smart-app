import os
import re
import json
import requests
import streamlit as st

BASE_URL  = "https://app.iship.cloud/api"
WEB_BASE  = "https://app.iship.cloud"

COURIER_MAP = {
    "Flash Express": "FlashExpressA",  # Flash Thunder
    "SPX Express":   "ShopeeExpress",
}

_PROVINCE_MAP = {
    "กรุงเทพ": "กรุงเทพมหานคร",
    "กทม":     "กรุงเทพมหานคร",
    "bangkok":  "กรุงเทพมหานคร",
    "Bangkok":  "กรุงเทพมหานคร",
}

def _norm_province(p: str) -> str:
    return _PROVINCE_MAP.get(p.strip(), p.strip())


_SRC_KEYS = [
    "ISHIP_SRC_NAME", "ISHIP_SRC_PHONE", "ISHIP_SRC_ADDRESS",
    "ISHIP_SRC_DISTRICT", "ISHIP_SRC_AMPHURE", "ISHIP_SRC_PROVINCE",
    "ISHIP_SRC_ZIPCODE", "ISHIP_LABEL_NAME", "ISHIP_LABEL_PHONE",
]


def _token() -> str:
    return os.environ.get("ISHIP_TOKEN") or st.secrets.get("ISHIP_TOKEN", "")


def _web_session():
    """Login to iShip web and return (session, debug_msg).
    iShip ใช้ phone number (ไม่ใช่ email) ในการ login"""
    phone    = os.environ.get("ISHIP_PHONE")    or st.secrets.get("ISHIP_PHONE", "")
    password = os.environ.get("ISHIP_PASSWORD") or st.secrets.get("ISHIP_PASSWORD", "")
    if not phone or not password:
        return None, "ไม่มี ISHIP_PHONE/ISHIP_PASSWORD ใน secrets"
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "th,en-US;q=0.9,en;q=0.8",
    })
    try:
        r = s.get(f"{WEB_BASE}/login", timeout=10)
        m = re.search(r'<input[^>]+name="_token"[^>]+value="([^"]+)"', r.text)
        if not m:
            return None, f"หาไม่เจอ _token ใน login page (status={r.status_code})"
        r2 = s.post(f"{WEB_BASE}/login", data={
            "_token":   m.group(1),
            "phone":    phone,
            "password": password,
            "remember": "1",
        }, headers={
            "Referer": f"{WEB_BASE}/login",
            "Origin":  WEB_BASE,
            "Content-Type": "application/x-www-form-urlencoded",
        }, timeout=10, allow_redirects=True)
        if "login" in r2.url:
            _err = re.search(r'text-danger[^>]*>([^<]+)<', r2.text)
            _msg = _err.group(1).strip() if _err else r2.text[:200]
            return None, f"Login ไม่สำเร็จ: {_msg}"
        return s, f"Login OK → {r2.url}"
    except Exception as e:
        return None, f"Exception: {e}"


def _src() -> dict:
    return {k: (os.environ.get(k) or st.secrets.get(k, "")) for k in _SRC_KEYS}


def is_configured() -> bool:
    return bool(_token())


def get_cod_transfers(max_batches: int = 30) -> dict:
    """
    ดึงสถานะ COD transfer จาก iShip API
    คืน: {"transfers": {tracking: {...}}, "debug": {...}}
    """
    sess, login_msg = _web_session()
    if not sess:
        return {"transfers": {}, "error": login_msg}

    debug = {}
    json_headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}

    try:
        tok = _token()
        bearer = {"Authorization": f"Bearer {tok}"} if tok else {}

        # ── ลอง /api/tracking ด้วย tracking number ──────────────────
        # ดึง tracking ล่าสุดจาก shipments ใน Supabase
        import database as _db
        _ships = _db.get_supabase().table("shipments").select("tracking_no,cod_amount") \
                     .gt("cod_amount", 0).order("created_at", desc=True).limit(3).execute().data
        debug["sample_shipments"] = _ships

        probe = {}
        for _s in _ships[:2]:
            tn = _s.get("tracking_no", "")
            if not tn:
                continue
            for url, params in [
                (f"{BASE_URL}/tracking",         {"tracking_no": tn}),
                (f"{BASE_URL}/tracking",         {"no": tn}),
                (f"{BASE_URL}/tracking/{tn}",    {}),
                (f"{BASE_URL}/shipment/{tn}",    {}),
                (f"{WEB_BASE}/api/tracking/{tn}", {}),
            ]:
                key = f"{url}?{list(params.values())}" if params else url
                try:
                    r = requests.get(url, params=params,
                                     headers={**json_headers, **bearer}, timeout=10)
                    probe[key] = {"status": r.status_code, "preview": r.text[:400]}
                except Exception as ex:
                    probe[key] = {"error": str(ex)}

        debug["probe"] = probe
        return {"transfers": {}, "debug": debug, "note": "probe round 3 — tracking with real numbers"}

    except Exception as e:
        debug["exception"] = str(e)
        return {"transfers": {}, "debug": debug, "error": str(e)}


def create_order(
    dst_name: str, dst_phone: str,
    address_line: str, district: str, amphure: str, province: str, zipcode: str,
    weight_kg: float, cod_amount: float, carrier: str, remark: str = "",
    item_detail: str = "",
    products: list = None,
) -> dict:
    src = _src()
    is_cod = cod_amount > 0
    payload = {
        "courier_code": COURIER_MAP.get(carrier, "FlashExpress"),
        "src_name":     src["ISHIP_SRC_NAME"],
        "src_phone":    src["ISHIP_SRC_PHONE"],
        "src_address":  src["ISHIP_SRC_ADDRESS"],
        "src_district": src["ISHIP_SRC_DISTRICT"],
        "src_amphure":  src["ISHIP_SRC_AMPHURE"],
        "src_province": src["ISHIP_SRC_PROVINCE"],
        "src_zipcode":  src["ISHIP_SRC_ZIPCODE"],
        "dst_name":     dst_name,
        "dst_phone":    dst_phone,
        "dst_address":  address_line.strip(),
        "dst_district": district,
        "dst_amphure":  amphure,
        "dst_province": _norm_province(province),
        "dst_zipcode":  zipcode,
        "weight":       1,
        "cod_amount":   int(cod_amount),
        "remark":       remark,
    }
    if not is_cod:
        payload["use_onlabel"]   = "1"
        payload["label_name"]    = src["ISHIP_LABEL_NAME"]
        payload["label_phone"]   = src["ISHIP_LABEL_PHONE"]
        payload["label_address"] = src["ISHIP_SRC_ADDRESS"]
        payload["label_zipcode"] = src["ISHIP_SRC_ZIPCODE"]
    if is_cod:
        _prod_list = [{
            "product_name":   "สินค้าซูเลียน",
            "product_qty":    "1",
            "product_length": "10",
            "product_width":  "10",
            "product_height": "5",
            "product_weight": "1",
            "product_color":  "น้ำตาล",
            "product_price":  "2000",
            "product_remark": "",
        }]
        payload.update({
            "use_onlabel":       "1",
            "label_name":        src["ISHIP_LABEL_NAME"],
            "label_phone":       src["ISHIP_LABEL_PHONE"],
            "label_address":     src["ISHIP_SRC_ADDRESS"],
            "label_zipcode":     src["ISHIP_SRC_ZIPCODE"],
            "create_mode":       "add",
            "order_type":        "1",
            "is_optional":       "0",
            "category_id":       "2",
            "save_dst_address":  "0",
            "product_value":     "",
            "weight":            "1",
            "width":             "",
            "length":            "",
            "height":            "",
        })
        form_data = {k: str(v) for k, v in payload.items()}
        form_data["product_lists"] = json.dumps(_prod_list, ensure_ascii=False)
        _sess, _login_msg = _web_session()
        if _sess:
            r_csrf = _sess.get(f"{WEB_BASE}/shipment/create", timeout=10)
            _m = re.search(r'<input[^>]+name="_token"[^>]+value="([^"]+)"', r_csrf.text)
            if _m:
                form_data["_token"] = _m.group(1)
            r = _sess.post(
                f"{WEB_BASE}/shipment",
                data=form_data,
                headers={"X-Requested-With": "XMLHttpRequest"},
                timeout=15,
            )
        else:
            return {"status": False, "message": f"Login failed: {_login_msg}",
                    "code": 0, "data": None}
    else:
        r = requests.post(
            f"{BASE_URL}/create_order",
            json=payload,
            headers={"Authorization": f"Bearer {_token()}"},
            timeout=15,
        )
    try:
        result = r.json()
    except Exception:
        result = {"status": False, "message": f"HTTP {r.status_code}: {r.text[:300]}"}
    _excl = {"src_name","src_phone","src_address","src_district",
             "src_amphure","src_province","src_zipcode",
             "label_name","label_phone","label_address","label_zipcode"}
    if not result.get("status"):
        _src_data = form_data if is_cod else payload
        result["_debug_payload"] = {k: v for k, v in _src_data.items() if k not in _excl}
    return result
