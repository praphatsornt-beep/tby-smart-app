import os
import requests
import streamlit as st

BASE_URL = "https://app.iship.cloud/api"

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


def _src() -> dict:
    return {k: (os.environ.get(k) or st.secrets.get(k, "")) for k in _SRC_KEYS}


def is_configured() -> bool:
    return bool(_token())


def create_order(
    dst_name: str, dst_phone: str,
    address_line: str, district: str, amphure: str, province: str, zipcode: str,
    weight_kg: float, cod_amount: float, carrier: str, remark: str = "",
    item_detail: str = "",
    products: list = None,
) -> dict:
    src = _src()
    payload = {
        "courier_code":  COURIER_MAP.get(carrier, "FlashExpress"),
        "src_name":      src["ISHIP_SRC_NAME"],
        "src_phone":     src["ISHIP_SRC_PHONE"],
        "src_address":   src["ISHIP_SRC_ADDRESS"],
        "src_district":  src["ISHIP_SRC_DISTRICT"],
        "src_amphure":   src["ISHIP_SRC_AMPHURE"],
        "src_province":  src["ISHIP_SRC_PROVINCE"],
        "src_zipcode":   src["ISHIP_SRC_ZIPCODE"],
        "use_onlabel":   "1",
        "label_name":    src["ISHIP_LABEL_NAME"],
        "label_phone":   src["ISHIP_LABEL_PHONE"],
        "label_address": src["ISHIP_SRC_ADDRESS"],
        "label_zipcode": src["ISHIP_SRC_ZIPCODE"],
        "dst_name":      dst_name,
        "dst_phone":     dst_phone,
        "dst_address":   f"{address_line} {district} {amphure} {province}".strip(),
        "dst_district":  district,
        "dst_amphure":   amphure,
        "dst_province":  _norm_province(province),
        "dst_zipcode":   zipcode,
        "weight":        max(1, round(weight_kg)),
        "cod_amount":    int(cod_amount),
        "remark":        remark,
    }
    if cod_amount > 0:
        payload["products"] = [{"name": "สินค้าซูเลียน", "qty": 1, "price": 2000}]
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
    if not result.get("status"):
        result["_debug_payload"] = {k: v for k, v in payload.items()
                                    if k not in ("src_name","src_phone","src_address","src_district",
                                                 "src_amphure","src_province","src_zipcode",
                                                 "label_name","label_phone","label_address","label_zipcode")}
    return result
