"""Thai address lookup — by postcode or tambon name."""
import json
import os
import streamlit as st

_DB_PATH = os.path.join(os.path.dirname(__file__), "thai_postcodes.json")


@st.cache_data
def _load_db() -> dict[str, list[dict]]:
    """postcode → [{tambon, amphure, province}]"""
    with open(_DB_PATH, encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def _load_tambon_index() -> list[dict]:
    """flat list of {tambon, amphure, province, zipcode} สำหรับ search by tambon"""
    db = _load_db()
    rows = []
    for zipcode, entries in db.items():
        for e in entries:
            rows.append({
                "tambon":   e["tambon"],
                "amphure":  e["amphure"],
                "province": e["province"],
                "zipcode":  zipcode,
            })
    return rows


def lookup(zipcode: str) -> list[dict]:
    """คืน [{tambon, amphure, province}] จาก zipcode"""
    if not zipcode or len(zipcode) != 5:
        return []
    try:
        return _load_db().get(zipcode, [])
    except Exception:
        return []


def lookup_by_tambon(text: str, limit: int = 8) -> list[dict]:
    """คืน [{tambon, amphure, province, zipcode}] ที่ชื่อตำบลมี text นั้น"""
    if not text or len(text) < 2:
        return []
    try:
        rows = _load_tambon_index()
    except Exception:
        return []
    text_lower = text.lower()
    return [r for r in rows if text_lower in r["tambon"].lower()][:limit]
