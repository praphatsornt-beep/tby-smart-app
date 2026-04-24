import hashlib
import hmac
import time
import requests
import os
import streamlit as st


BASE_URL = "https://partner.shopeemobile.com"


def _get_credentials():
    pid = os.environ.get("SHOPEE_PARTNER_ID") or st.secrets.get("SHOPEE_PARTNER_ID", "")
    key = os.environ.get("SHOPEE_PARTNER_KEY") or st.secrets.get("SHOPEE_PARTNER_KEY", "")
    return int(pid) if pid else None, key


def is_configured() -> bool:
    pid, key = _get_credentials()
    return bool(pid and key)


def _sign(path: str, timestamp: int, access_token: str = "", shop_id: int = 0) -> str:
    partner_id, partner_key = _get_credentials()
    base = f"{partner_id}{path}{timestamp}{access_token}{shop_id}"
    return hmac.new(partner_key.encode(), base.encode(), hashlib.sha256).hexdigest()


def get_auth_url(redirect_url: str) -> str:
    """URL สำหรับ redirect ให้ร้านค้า authorize (ไม่ต้องใส่ shop_id ล่วงหน้า)"""
    ts = int(time.time())
    partner_id, _ = _get_credentials()
    path = "/api/v2/shop/auth_partner"
    sign = _sign(path, ts)
    return (
        f"{BASE_URL}{path}"
        f"?partner_id={partner_id}&timestamp={ts}&sign={sign}"
        f"&redirect={redirect_url}"
    )


def exchange_token(shop_id: int, code: str) -> dict:
    """แลก authorization code → access_token + refresh_token"""
    ts = int(time.time())
    path = "/api/v2/auth/token/get"
    partner_id, _ = _get_credentials()
    sign = _sign(path, ts)
    body = {"code": code, "shop_id": shop_id, "partner_id": partner_id}
    r = requests.post(
        f"{BASE_URL}{path}?partner_id={partner_id}&timestamp={ts}&sign={sign}",
        json=body, timeout=15,
    )
    return r.json()


def do_refresh_token(shop_id: int, refresh_tok: str) -> dict:
    ts = int(time.time())
    path = "/api/v2/auth/access_token/get"
    partner_id, _ = _get_credentials()
    sign = _sign(path, ts)
    body = {"refresh_token": refresh_tok, "shop_id": shop_id, "partner_id": partner_id}
    r = requests.post(
        f"{BASE_URL}{path}?partner_id={partner_id}&timestamp={ts}&sign={sign}",
        json=body, timeout=15,
    )
    return r.json()


def get_orders(shop_id: int, access_token: str, from_ts: int, to_ts: int) -> list[dict]:
    """ดึง order list สถานะ COMPLETED ในช่วงเวลา (ทีละ 100)"""
    partner_id, _ = _get_credentials()
    all_orders = []
    cursor = ""
    while True:
        ts = int(time.time())
        path = "/api/v2/order/get_order_list"
        sign = _sign(path, ts, access_token, shop_id)
        params = {
            "partner_id": partner_id, "timestamp": ts, "sign": sign,
            "shop_id": shop_id, "access_token": access_token,
            "time_range_field": "create_time",
            "time_from": from_ts, "time_to": to_ts,
            "page_size": 100, "order_status": "COMPLETED",
            "cursor": cursor,
        }
        r = requests.get(f"{BASE_URL}{path}", params=params, timeout=15).json()
        resp = r.get("response", {})
        all_orders.extend(resp.get("order_list", []))
        if not resp.get("more", False):
            break
        cursor = resp.get("next_cursor", "")
    return all_orders


def get_order_details(shop_id: int, access_token: str, order_sn_list: list[str]) -> list[dict]:
    """ดึงรายละเอียด order พร้อม item_list (ทีละ 50)"""
    partner_id, _ = _get_credentials()
    results = []
    for i in range(0, len(order_sn_list), 50):
        chunk = order_sn_list[i:i + 50]
        ts = int(time.time())
        path = "/api/v2/order/get_order_detail"
        sign = _sign(path, ts, access_token, shop_id)
        params = {
            "partner_id": partner_id, "timestamp": ts, "sign": sign,
            "shop_id": shop_id, "access_token": access_token,
            "order_sn_list": ",".join(chunk),
            "response_optional_fields": "item_list",
        }
        r = requests.get(f"{BASE_URL}{path}", params=params, timeout=15).json()
        results.extend(r.get("response", {}).get("order_list", []))
    return results
