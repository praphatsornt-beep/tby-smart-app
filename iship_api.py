import os
import requests
import streamlit as st

BASE_URL = "https://app.iship.cloud/api"

COURIER_MAP = {
    "Flash Express": "FlashExpress",
    "SPX Express":   "ShopeeExpress",
}

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
        "label_address": src["ISHIP_LABEL_PHONE"],
        "label_zipcode": src["ISHIP_SRC_ZIPCODE"],
        "dst_name":      dst_name,
        "dst_phone":     dst_phone,
        "dst_address":   f"{address_line} {district} {amphure} {province}".strip(),
        "dst_district":  district,
        "dst_amphure":   amphure,
        "dst_province":  province,
        "dst_zipcode":   zipcode,
        "weight":        round(max(weight_kg, 0.01), 2),
        "cod_amount":    int(cod_amount),
        "remark":        remark,
    }
    r = requests.post(
        f"{BASE_URL}/create_order",
        json=payload,
        headers={"Authorization": f"Bearer {_token()}"},
        timeout=15,
    )
    return r.json()
