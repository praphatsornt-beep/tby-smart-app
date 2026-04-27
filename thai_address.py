"""Thai address lookup by postal code — uses local static database."""
import json
import os
import streamlit as st

_DB_PATH = os.path.join(os.path.dirname(__file__), "thai_postcodes.json")


@st.cache_data
def _load_db() -> dict[str, list[dict]]:
    with open(_DB_PATH, encoding="utf-8") as f:
        return json.load(f)


def lookup(zipcode: str) -> list[dict]:
    if not zipcode or len(zipcode) != 5:
        return []
    try:
        return _load_db().get(zipcode, [])
    except Exception:
        return []
