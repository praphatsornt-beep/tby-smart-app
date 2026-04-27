"""Thai address lookup by postal code — fetches data from public CDN once, then caches."""
import streamlit as st
import requests

_URLS = [
    "https://raw.githubusercontent.com/earthchie/jquery-Thailand-address/master/jquery.Thailand.js/database/db.json",
    "https://raw.githubusercontent.com/earthchie/jquery-Thailand-address/main/jquery.Thailand.js/database/db.json",
]


@st.cache_data(ttl=86400)
def _load_db() -> dict[str, list[dict]]:
    """โหลด Thai address DB → {zipcode: [{tambon, amphure, province}]}
    ถ้าล้มเหลว raise RuntimeError เพื่อไม่ให้ Streamlit cache ผลว่าง"""
    raw = None
    for url in _URLS:
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            raw = r.json()
            if raw:
                break
        except Exception:
            continue

    if not raw:
        raise RuntimeError("ไม่สามารถโหลดข้อมูลรหัสไปรษณีย์ได้")

    result: dict[str, list[dict]] = {}
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) < 4:
            continue
        tambon   = str(row[0])
        amphure  = str(row[1])
        province = str(row[2])
        zipcode  = str(int(row[3])).zfill(5) if row[3] else ""
        if not zipcode or zipcode == "0":
            continue
        result.setdefault(zipcode, []).append({
            "tambon":   tambon,
            "amphure":  amphure,
            "province": province,
        })
    return result


def lookup(zipcode: str) -> list[dict]:
    """คืน list of {tambon, amphure, province} สำหรับ zipcode ที่กำหนด"""
    if not zipcode or len(zipcode) != 5:
        return []
    try:
        db = _load_db()
    except Exception:
        return []
    return db.get(zipcode, [])
