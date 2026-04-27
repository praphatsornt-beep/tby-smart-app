"""Thai address lookup by postal code — fetches data from public CDN once, then caches."""
import streamlit as st
import requests

_DATA_URL = "https://raw.githubusercontent.com/earthchie/jquery-Thailand-address/master/jquery.Thailand.js/database/db.json"


@st.cache_data(ttl=86400)
def _load_db() -> dict[str, list[dict]]:
    """โหลด Thai address DB จาก GitHub CDN → {zipcode: [{tambon, amphure, province}]}"""
    try:
        r = requests.get(_DATA_URL, timeout=15)
        raw = r.json()
    except Exception:
        return {}

    result: dict[str, list[dict]] = {}
    for row in raw:
        # format: [tambon, amphure, province, zipcode]  (array per row)
        if not isinstance(row, (list, tuple)) or len(row) < 4:
            continue
        tambon, amphure, province, zipcode = str(row[0]), str(row[1]), str(row[2]), str(row[3])
        if not zipcode or zipcode == "None":
            continue
        result.setdefault(zipcode, []).append({
            "tambon": tambon,
            "amphure": amphure,
            "province": province,
        })
    return result


def lookup(zipcode: str) -> list[dict]:
    """คืน list of {tambon, amphure, province} สำหรับ zipcode ที่กำหนด"""
    if not zipcode or len(zipcode) != 5:
        return []
    db = _load_db()
    return db.get(zipcode, [])
