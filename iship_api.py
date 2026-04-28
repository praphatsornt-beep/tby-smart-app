import os
import re
import json
import datetime as _dt
import requests
import streamlit as st
from urllib.parse import unquote

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


def get_cod_transfers(days_back: int = 60) -> dict:
    """
    ดึงสถานะ COD transfer จาก iShip
    คืน: {"transfers": {track_no: {"wd_id","date","cod_amount","net","status"}}, "error": str|None}
    """
    sess, login_msg = _web_session()
    if not sess:
        return {"transfers": {}, "error": login_msg}

    end_date   = _dt.date.today()
    start_date = end_date - _dt.timedelta(days=days_back)
    xsrf = unquote(sess.cookies.get("XSRF-TOKEN", ""))
    hdrs = {
        "X-Requested-With": "XMLHttpRequest",
        "Accept":           "application/json, text/javascript, */*; q=0.01",
        "Referer":          f"{WEB_BASE}/report/withdraw",
        "X-XSRF-TOKEN":     xsrf,
    }

    # full column list ตาม browser (required ทุก column)
    _cols = ["datetime","txn_id","withdraw_type","bank_name","bank_account_name",
             "bank_account_number","amount","non_vat","vat","fee","service_fee",
             "transfer_fee","net_total_amount","wd_remark","txn_id"]
    _list_params = {
        "draw": 1, "start": 0, "length": 200,
        "start_date": str(start_date), "end_date": str(end_date),
        "order[0][column]": 0, "order[0][dir]": "desc",
        "search[value]": "", "search[regex]": "false",
    }
    for i, col in enumerate(_cols):
        _list_params[f"columns[{i}][data]"]            = col
        _list_params[f"columns[{i}][name]"]            = ""
        _list_params[f"columns[{i}][searchable]"]      = "true"
        _list_params[f"columns[{i}][orderable]"]       = "true"
        _list_params[f"columns[{i}][search][value]"]   = ""
        _list_params[f"columns[{i}][search][regex]"]   = "false"

    try:
        # ── 1. list WD batches ───────────────────────────────────────
        r_list = sess.get(f"{WEB_BASE}/getdt-withdraw", headers=hdrs,
                          timeout=15, params=_list_params)
        if r_list.status_code != 200:
            return {"transfers": {}, "error": f"list HTTP {r_list.status_code}"}
        batches = r_list.json().get("data", [])

        # ── 2. detail ของแต่ละ batch → track_no ─────────────────────
        transfers = {}
        for batch in batches:
            txn_id   = batch.get("txn_id", "")
            wd_date  = batch.get("datetime", "")[:10]
            net      = batch.get("net_total_amount", 0)
            if not txn_id:
                continue
            hdrs2 = {**hdrs, "Referer": f"{WEB_BASE}/report/withdraw/{txn_id}"}
            r_det = sess.get(f"{WEB_BASE}/report/withdraw/{txn_id}", headers=hdrs2, timeout=15, params={
                "draw": 1, "start": 0, "length": 200,
                "columns[0][data]": "created_at",
                "columns[1][data]": "track_no",
                "columns[2][data]": "cod_amount",
                "columns[3][data]": "cod_balance",
                "columns[4][data]": "status_name",
                "order[0][column]": 0, "order[0][dir]": "desc",
            })
            if r_det.status_code != 200:
                continue
            for row in r_det.json().get("data", []):
                tn = row.get("track_no", "")
                if not tn:
                    continue
                transfers[tn] = {
                    "wd_id":      txn_id,
                    "date":       wd_date,
                    "cod_amount": row.get("cod_amount", ""),
                    "net":        row.get("cod_balance", net),
                    "status":     row.get("status_name", "ชำระเงินสำเร็จ"),
                }
        return {"transfers": transfers, "error": None}

    except Exception as e:
        return {"transfers": {}, "error": str(e)}


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
