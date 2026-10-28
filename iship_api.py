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
    "Flash Thunder":       "FlashExpressA",
    "Flash Pro DD":        "FlashExpressD",
    "Flash Pro OK":        "FlashLive",
    "Flash 100CM":         "FlashExpressC",
    "Flash Pro DD Bulky":  "FlashExpressDBulky",
    # ยืนยัน 2026-10-28: user สร้างออเดอร์ทดสอบจริงเลือก "Flash Pro OK Bulky" บนเว็บ iShip
    # เช็คจาก Network tab (request payload ตอนกดสร้างรายการ) ได้ courier_code นี้มาตรงๆ ตรง
    # pattern ที่เดาไว้ (Flash Pro OK ธรรมดา = "FlashLive" จึงเป็น "FlashLive"+"Bulky")
    "Flash Pro OK Bulky":  "FlashLiveBulky",
    "SPX Express":         "ShopeeExpress",
    "KEX Express":         "KerryExpress",
    # เดิมชื่อ "KEX Bulky" — แก้เป็น "KEX Jumbo" 2026-08-14 (ตารางราคา/เงื่อนไขที่ผูกกับ
    # code นี้เป็นของ Jumbo จริง ไม่ใช่ Bulky — ดูคอมเมนต์ที่ carriers.py _CARRIER_DEFS)
    # code "KexBulky" ยืนยันแล้วว่าถูกต้อง (2026-08-14) — เช็คจาก Network tab บน iShip
    # จริง: ออเดอร์ที่ courier_code="KexBulky" หน้าเว็บ iShip เองแสดงป้าย "KEX JUMBO"
    # ติดอยู่ (iShip ใช้ชื่อ code ภายในว่า Bulky แทนสินค้าที่แบรนด์จริงชื่อ Jumbo)
    "KEX Jumbo":           "KexBulky",
    # ยืนยัน 2026-08-14: user สร้างออเดอร์ทดสอบเลือก "KEX Bulky" ตัวจริงบน iShip (tracking
    # ISX292047QRMD) ได้ code นี้ — pattern: KexBulky = Jumbo (เฉยๆ), KexBulky01 = Bulky จริง
    "KEX Bulky":           "KexBulky01",
    "DHL eCommerce":       "DHL",
    "DHL Next Day":        "DHLND",
    "ไปรษณีย์ EMS":        "THP_eParcelX",
    "ไปรษณีย์ EMS Bulky":  "THP_eParcelZ",
    "J&T Express":         "JntExpress",
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


_WEB_SESSION_TTL_S = 480  # 8 minutes — iShip "remember=1" sessions live much longer

def _get_cached_web_session():
    """Return (session, debug_msg). Reuses authenticated session for up to 8 min.
    Saves 2 HTTP round-trips (GET csrf + POST login) on every iShip web call."""
    _now = _dt.datetime.now().timestamp()
    _cached = st.session_state.get("_iship_web_sess")
    if _cached:
        _s, _ts = _cached
        if _now - _ts < _WEB_SESSION_TTL_S:
            return _s, "session cache hit"
    # Stale or missing — login fresh
    _s, _msg = _web_session()
    if _s:
        st.session_state["_iship_web_sess"] = (_s, _now)
    return _s, _msg


def _src() -> dict:
    return {k: (os.environ.get(k) or st.secrets.get(k, "")) for k in _SRC_KEYS}


def is_configured() -> bool:
    return bool(_token())


def get_cod_transfers(days_back: int = 60) -> dict:
    """
    ดึงสถานะ COD transfer จาก iShip
    คืน: {"transfers": {track_no: {"wd_id","date","cod_amount","net","status"}}, "error": str|None}
    """
    sess, login_msg = _get_cached_web_session()
    if not sess:
        return {"transfers": {}, "error": login_msg}

    end_date   = _dt.date.today()
    start_date = end_date - _dt.timedelta(days=days_back)

    # โหลดหน้า withdraw ก่อนเพื่อให้ browser ได้ XSRF token ใหม่
    sess.get(f"{WEB_BASE}/report/withdraw", timeout=10)
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

    def _list_fetch_page(start, length):
        _list_params = {
            "draw": 1, "start": start, "length": length,
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
        r = sess.get(f"{WEB_BASE}/getdt-withdraw", headers=hdrs, timeout=15, params=_list_params)
        if r.status_code != 200 or not r.text.strip():
            raise RuntimeError(f"list HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json().get("data", [])
        except Exception:
            raise RuntimeError(f"JSON parse failed: {r.text[:300]}")

    try:
        # ── 1. list WD batches (วนทุกหน้า — ดู _fetch_all_dt_rows) ─────
        batches = _fetch_all_dt_rows(_list_fetch_page)

        # ── 2. detail แบบ parallel ──────────────────────────────────
        # สร้าง session ใหม่ต่อ thread (copy cookies+headers จาก session หลัก)
        def _make_sess():
            s = requests.Session()
            s.cookies.update(sess.cookies)
            s.headers.update(sess.headers)
            return s

        from concurrent.futures import ThreadPoolExecutor, as_completed

        _det_cols = ["created_at","pickedup_date","courier_code","track_no",
                     "dst_name","dst_phone","cod_amount","cod_fee",
                     "cod_balance","updated_at"]

        def _det_fetch_page(_s, hdrs2, txn_id, start, length):
            _p = {"draw": 1, "start": start, "length": length,
                  "order[0][column]": 0, "order[0][dir]": "desc",
                  "search[value]": "", "search[regex]": "false"}
            for _i, _c in enumerate(_det_cols):
                _p[f"columns[{_i}][data]"]          = _c
                _p[f"columns[{_i}][name]"]          = ""
                _p[f"columns[{_i}][searchable]"]    = "true"
                _p[f"columns[{_i}][orderable]"]     = "true"
                _p[f"columns[{_i}][search][value]"] = ""
                _p[f"columns[{_i}][search][regex]"] = "false"
            r = _s.get(f"{WEB_BASE}/getdt-report-cod/{txn_id}", headers=hdrs2, timeout=15, params=_p)
            if r.status_code != 200 or not r.text.strip():
                raise RuntimeError(f"status={r.status_code} empty={not r.text.strip()} url={r.url[:80]}")
            try:
                return r.json().get("data", [])
            except Exception:
                raise RuntimeError(f"JSON fail: {r.text[:200]}")

        def _fetch_detail(batch):
            txn_id  = batch.get("txn_id", "")
            wd_date = batch.get("datetime", "")[:10]
            net     = batch.get("net_total_amount", 0)
            if not txn_id:
                return {}
            _s = _make_sess()
            hdrs2 = {**hdrs, "Referer": f"{WEB_BASE}/report/withdraw/{txn_id}"}
            try:
                # แต่ละ withdrawal batch อาจมี tracking มากกว่า 1 หน้าได้เหมือนกันถ้า batch
                # นั้นครอบคลุม tracking จำนวนมาก (ดู _fetch_all_dt_rows) — วนให้ครบเหมือนกัน
                rows = _fetch_all_dt_rows(lambda start, length: _det_fetch_page(_s, hdrs2, txn_id, start, length))
            except Exception as ex:
                return {"_debug_det": str(ex)}
            result = {}
            for row in rows:
                tn = row.get("track_no", "")
                if tn:
                    result[tn] = {
                        "wd_id":      txn_id,
                        "date":       wd_date,
                        "cod_amount": row.get("cod_amount", ""),
                        "net":        row.get("cod_balance", net),
                        "status":     row.get("status_name", "ชำระเงินสำเร็จ"),
                    }
            return result

        transfers = {}
        det_debug = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_fetch_detail, b): b for b in batches}
            for fut in as_completed(futures):
                res = fut.result()
                if "_debug_det" in res:
                    det_debug.append(res["_debug_det"])
                else:
                    transfers.update(res)
        return {"transfers": transfers, "error": None,
                "_debug": {"batches": len(batches),
                           "det_errors": det_debug[:3],
                           "first_txn": batches[0].get("txn_id","") if batches else ""}}

    except Exception as e:
        return {"transfers": {}, "error": str(e)}


def _fetch_all_dt_rows(fetch_page, page_size: int = 200, max_pages: int = 25):
    """วน fetch endpoint สไตล์ DataTables ของ iShip (start/length) จนกว่าหน้าจะมาไม่เต็มแล้ว
    หยุด — กันกรณีมีมากกว่า 1 หน้าแต่โค้ดเดิมดึงแค่หน้าแรกเสมอ (เจอจริง 2026-10-25:
    get_shipment_statuses() เดิม fetch แค่หน้าแรก length=200 เรียงใหม่สุดก่อนเสมอ พอจำนวน
    shipments ในช่วง days_back เกิน 200 แถว (ร้านนี้มี 451 แถวใน 90 วัน) แถวที่เลยลำดับที่
    200 ไปเงียบๆ ไม่ถูกเช็คสถานะอีกเลยไม่ว่าจะรัน sync กี่ครั้ง/กี่เช้าก็ตาม — ยืนยันจากข้อมูล
    จริง พบแถวค้างสถานะ "ชำระเงินสำเร็จ" ตั้งแต่ก.ย. ไม่เคยอัปเดตเลยทั้งที่รันทุกเช้ามาตลอด)
    fetch_page(start, length) คืน list ของแถวดิบ (ไม่ใช่ response ทั้งก้อน) หรือ raise Exception
    ถ้าหน้าแรกพังให้ปล่อย exception ขึ้นไปตามเดิม (คงพฤติกรรม error-reporting เดิม) แต่ถ้าหน้า
    ถัดๆไปพังกลางทาง ให้หยุดเงียบๆ แล้วคืนเท่าที่ได้มา (ดีกว่าทิ้งทุกอย่างที่ดึงมาแล้วทั้งหมด)"""
    rows = []
    start = 0
    for i in range(max_pages):
        try:
            page_rows = fetch_page(start, page_size)
        except Exception:
            if i == 0:
                raise
            break
        if not page_rows:
            break
        rows += page_rows
        if len(page_rows) < page_size:
            break
        start += page_size
    return rows


def get_shipment_statuses(days_back: int = 60) -> dict:
    """
    ดึงสถานะการจัดส่งจาก iShip (วนทุกหน้าถ้ามีเกิน 1 หน้า — ดู _fetch_all_dt_rows)
    คืน: {"statuses": {track_no: status_text}, "error": str|None}
    """
    sess, login_msg = _get_cached_web_session()
    if not sess:
        return {"statuses": {}, "error": login_msg}

    end_date   = _dt.date.today()
    start_date = end_date - _dt.timedelta(days=days_back)

    sess.get(f"{WEB_BASE}/shipment", timeout=10)
    xsrf = unquote(sess.cookies.get("XSRF-TOKEN", ""))
    hdrs = {
        "X-Requested-With": "XMLHttpRequest",
        "Accept":           "application/json, text/javascript, */*; q=0.01",
        "Referer":          f"{WEB_BASE}/shipment",
        "X-XSRF-TOKEN":     xsrf,
    }

    _cols = [
        ("checkbox",        "",                          False, False),
        ("order_date",      "orders.created_at",         True,  True),
        ("track_no",        "shippings.track_no",        True,  True),
        ("custom_order_id", "shippings.custom_order_id", True,  True),
        ("status_btn",      "status_btn",                False, False),
        ("name",            "",                          True,  True),
        ("dst_name",        "",                          True,  True),
        ("dst_phone",       "",                          True,  True),
        ("dst_address",     "",                          True,  True),
        ("print_btn",       "print_count",               False, False),
        ("cod_amount",      "",                          True,  True),
        ("remark",          "",                          True,  True),
        ("cancel_btn",      "",                          True,  True),
        ("detail_btn",      "",                          True,  True),
    ]

    def _fetch_page(start, length):
        params = {
            "draw": 1, "start": start, "length": length,
            "order[0][column]": 1, "order[0][dir]": "desc",
            "search[value]": "", "search[regex]": "false",
            "status_id": "", "start_date": str(start_date), "end_date": str(end_date),
            "order_print": 3, "courier_filter": "all",
        }
        for i, (data, name, searchable, orderable) in enumerate(_cols):
            params[f"columns[{i}][data]"]          = data
            params[f"columns[{i}][name]"]          = name
            params[f"columns[{i}][searchable]"]    = "true" if searchable else "false"
            params[f"columns[{i}][orderable]"]     = "true" if orderable else "false"
            params[f"columns[{i}][search][value]"] = ""
            params[f"columns[{i}][search][regex]"] = "false"
        r = sess.get(f"{WEB_BASE}/getdt-new-shipment", headers=hdrs, params=params, timeout=15)
        if r.status_code != 200 or not r.text.strip():
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json().get("data", [])
        except Exception:
            raise RuntimeError(f"JSON parse failed: {r.text[:300]}")

    try:
        rows = _fetch_all_dt_rows(_fetch_page)
        statuses = {}
        for row in rows:
            track_html   = row.get("track_no", "") or ""
            status_html  = row.get("status_btn", "") or ""
            # track_no เป็น HTML — แกะ tracking number จาก href หรือ link text
            m_tn = re.search(r'track=([A-Z0-9]+)', track_html)
            if not m_tn:
                m_tn = re.search(r'>([A-Z0-9]{8,})<', track_html)
            tn = m_tn.group(1).strip() if m_tn else track_html.strip()
            # status_btn เป็น HTML button — แกะข้อความสถานะ
            m_st = re.search(r'>([^<>]+)</', status_html)
            status_text = m_st.group(1).strip() if m_st else status_html.strip()
            if tn and status_text:
                statuses[tn] = status_text
        return {"statuses": statuses, "error": None, "_debug": {"rows": len(rows)}}
    except Exception as e:
        return {"statuses": {}, "error": str(e)}


def get_shipping_report(days_back: int = 60) -> dict:
    """
    ดึงยอดที่ iShip คิดจริง (หลังชั่งน้ำหนักจริงที่คลัง) ต่อ tracking — ใช้เทียบกับ
    ราคาที่เราประเมินไว้ตอนสร้างรายการ (shipments.shipping_cost) เพื่อจับความผิดปกติ
    คืน: {"report": {track_no: {"discount_price","actual_weight","status_name"}}, "error": str|None}
    หมายเหตุ: discount_price/actual_weight เป็น 0 จนกว่าขนส่งจะเข้ารับและชั่งน้ำหนักจริง
    (ไม่ใช่ค่าเริ่มต้นที่หมายถึง "ฟรี") — ฝั่งเรียกใช้ต้องเช็คสถานะก่อนตีความว่าผิดปกติ
    """
    sess, login_msg = _get_cached_web_session()
    if not sess:
        return {"report": {}, "error": login_msg}

    end_date   = _dt.date.today()
    start_date = end_date - _dt.timedelta(days=days_back)

    sess.get(f"{WEB_BASE}/report/shipping", timeout=10)
    xsrf = unquote(sess.cookies.get("XSRF-TOKEN", ""))
    hdrs = {
        "X-Requested-With": "XMLHttpRequest",
        "Accept":           "application/json, text/javascript, */*; q=0.01",
        "Referer":          f"{WEB_BASE}/report/shipping",
        "X-XSRF-TOKEN":     xsrf,
    }

    _cols = ["created_at", "pickedup_date", "delivered_at", "courier_code", "track_no",
             "custom_order_id", "dst_name", "dst_address", "cod_amount", "size", "box",
             "actual_weight", "discount_price", "status_name", "remark"]

    def _fetch_page(start, length):
        params = {
            "draw": 1, "start": start, "length": length,
            "order[0][column]": 0, "order[0][dir]": "desc",
            "search[value]": "", "search[regex]": "false",
            "status_id": "", "start_date": str(start_date), "end_date": str(end_date),
            "pickedup_date": "",
        }
        for i, c in enumerate(_cols):
            params[f"columns[{i}][data]"]          = c
            params[f"columns[{i}][name]"]          = c
            params[f"columns[{i}][searchable]"]    = "true"
            params[f"columns[{i}][orderable]"]     = "true"
            params[f"columns[{i}][search][value]"] = ""
            params[f"columns[{i}][search][regex]"] = "false"
        r = sess.get(f"{WEB_BASE}/getdt-shipping-report", headers=hdrs, params=params, timeout=15)
        if r.status_code != 200 or not r.text.strip():
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json().get("data", [])
        except Exception:
            raise RuntimeError(f"JSON parse failed: {r.text[:300]}")

    try:
        # 1000/page เดิมเผื่อไว้มากแล้ว แต่ยังวนหน้าต่อให้ด้วยเผื่อโตเกินในอนาคต (ดู
        # _fetch_all_dt_rows — เจอบั๊กคล้ายกันจริงใน get_shipment_statuses() ที่ length=200)
        rows = _fetch_all_dt_rows(_fetch_page, page_size=1000)
        report = {}
        for row in rows:
            tn = (row.get("track_no") or "").strip()
            if not tn:
                continue
            report[tn] = {
                "discount_price": float(row.get("discount_price") or 0),
                "actual_weight":  float(row.get("actual_weight") or 0),
                "status_name":    row.get("status_name", "") or "",
            }
        return {"report": report, "error": None, "_debug": {"rows": len(rows)}}
    except Exception as e:
        return {"report": {}, "error": str(e)}


def create_order(
    dst_name: str, dst_phone: str,
    address_line: str, district: str, amphure: str, province: str, zipcode: str,
    weight_kg: float, cod_amount: float, carrier: str, remark: str = "",
    item_detail: str = "",
    products: list = None,
    length_cm: int = 0, width_cm: int = 0, height_cm: int = 0,
) -> dict:
    from math import ceil as _ceil
    _courier_code = COURIER_MAP.get(carrier)
    if not _courier_code:
        # เดิมตรงนี้ fallback เงียบๆ เป็น "FlashExpressA" (Flash Thunder) ถ้าหา carrier ไม่เจอ
        # ใน COURIER_MAP เลย — อันตรายมาก เพราะ carriers.py โชว์ตัวเลือกในตารางเทียบราคาได้
        # โดยไม่ต้องมี courier_code ยืนยันแล้วก็ได้ (เช่น "Flash Pro OK Bulky" เพิ่ม 2026-10-28
        # ที่ยังไม่รู้ code จริง) ถ้าไม่กันตรงนี้ไว้ จะยิงออเดอร์จริงไปเป็น Thunder แบบเงียบๆ
        # โดยที่ติดป้าย/คิดราคาเป็นขนส่งคนละตัวเลย (เหมือนบั๊ก Pro DD Bulky↔Pro OK Bulky ที่
        # เพิ่งเจอ แต่แย่กว่าเพราะผิดขนส่งไปเลย ไม่ใช่แค่ผิดราคา) — คืน error แทนเรียก API เลย
        return {"status": False, "message": f"ไม่พบ iShip courier_code สำหรับ '{carrier}' — ยังไม่ได้ยืนยัน ติดต่อแอดมินก่อนใช้งานขนส่งนี้",
                "code": 0, "data": None}
    src = _src()
    is_cod = cod_amount > 0
    _weight_int = max(1, _ceil(weight_kg))
    payload = {
        "courier_code": _courier_code,
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
        "weight":       _weight_int,
        "cod_amount":   int(cod_amount),
        "remark":       remark,
    }
    if length_cm: payload["length"] = length_cm
    if width_cm:  payload["width"]  = width_cm
    if height_cm: payload["height"] = height_cm
    if not is_cod:
        payload["use_onlabel"]   = "1"
        payload["label_name"]    = src["ISHIP_LABEL_NAME"]
        payload["label_phone"]   = src["ISHIP_LABEL_PHONE"]
        payload["label_address"] = src["ISHIP_SRC_ADDRESS"]
        payload["label_zipcode"] = src["ISHIP_SRC_ZIPCODE"]
        # บันทึกที่อยู่ผู้รับเข้าสมุดที่อยู่ของ iShip ด้วย (ค้นจากเบอร์โทรบนเว็บ iShip ได้
        # ครั้งหน้า) — เดิม REST API /create_order ไม่มีฟิลด์นี้เลย ทำให้ลูกค้าที่ส่งแบบ
        # โอนเงิน (ไม่ใช่ COD) ไม่ถูกบันทึกที่อยู่ใน iship เหมือนกัน (ยืนยันจากผู้ใช้
        # 2026-10-23) เพิ่มให้ตรงกับฝั่ง COD ข้างล่าง — ไม่มีเอกสาร API ยืนยันชื่อฟิลด์นี้
        # ตรงกับฟอร์มเว็บ ต้องทดสอบของจริงอีกครั้งว่า iShip รับฟิลด์นี้ผ่าน REST API จริง
        payload["save_dst_address"] = "1"
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
            # "1" = ติ๊ก checkbox "บันทึกที่อยู่" (ค่า default ของฟอร์มเว็บจริงคือติ๊กไว้
            # เสมอ — ยืนยันจากสกรีนช็อตฟอร์มจริง 2026-10-23) เดิมเป็น "0" มาตั้งแต่ commit
            # ที่ copy payload เต็มจากฟอร์มเว็บจริงมาตอนแรก (76047008) — ตอน capture ฟอร์ม
            # นั้นบังเอิญไม่ได้ติ๊กไว้ ไม่ใช่ค่าที่ตั้งใจปิดไว้ ทำให้ที่อยู่ลูกค้าที่ส่งผ่าน
            # COD ไม่เคยถูกบันทึกเข้าสมุดที่อยู่ของ iShip เองเลย (ค้นจากเบอร์โทรบนเว็บ
            # iShip ไม่เจอ) แก้เป็น "1" ให้ตรงกับพฤติกรรม default จริง
            "save_dst_address":  "1",
            "product_value":     "",
            "weight":            str(_weight_int),
            "width":             str(width_cm) if width_cm else "",
            "length":            str(length_cm) if length_cm else "",
            "height":            str(height_cm) if height_cm else "",
        })
        form_data = {k: str(v) for k, v in payload.items()}
        form_data["product_lists"] = json.dumps(_prod_list, ensure_ascii=False)
        _sess, _login_msg = _get_cached_web_session()
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


def get_label_url(tracking_no: str) -> dict:
    """หา order ID จาก tracking number แล้วคืน URL สำหรับปริ้นใบปะหน้า
    คืน: {"url": str|None, "order_id": str|None, "error": str|None}
    """
    sess, login_msg = _get_cached_web_session()
    if not sess:
        return {"url": None, "error": f"Login failed: {login_msg}"}

    try:
        sess.get(f"{WEB_BASE}/shipment", timeout=10)
        xsrf = unquote(sess.cookies.get("XSRF-TOKEN", ""))
        hdrs = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": f"{WEB_BASE}/shipment",
            "X-XSRF-TOKEN": xsrf,
        }

        _cols = [
            ("checkbox", "", False, False),
            ("order_date", "orders.created_at", True, True),
            ("track_no", "shippings.track_no", True, True),
            ("custom_order_id", "shippings.custom_order_id", True, True),
            ("status_btn", "status_btn", False, False),
            ("name", "", True, True),
            ("dst_name", "", True, True),
            ("dst_phone", "", True, True),
            ("dst_address", "", True, True),
            ("print_btn", "print_count", False, False),
            ("cod_amount", "", True, True),
            ("remark", "", True, True),
            ("cancel_btn", "", True, True),
            ("detail_btn", "", True, True),
        ]
        _end = _dt.date.today()
        _start = _end - _dt.timedelta(days=90)
        params = {
            "draw": 1, "start": 0, "length": 20,
            "order[0][column]": 1, "order[0][dir]": "desc",
            "search[value]": tracking_no, "search[regex]": "false",
            "status_id": "", "order_print": 3, "courier_filter": "all",
            "start_date": str(_start), "end_date": str(_end),
        }
        for i, (data, name, searchable, orderable) in enumerate(_cols):
            params[f"columns[{i}][data]"] = data
            params[f"columns[{i}][name]"] = name
            params[f"columns[{i}][searchable]"] = "true" if searchable else "false"
            params[f"columns[{i}][orderable]"] = "true" if orderable else "false"
            params[f"columns[{i}][search][value]"] = ""
            params[f"columns[{i}][search][regex]"] = "false"

        r = sess.get(f"{WEB_BASE}/getdt-new-shipment", headers=hdrs,
                     params=params, timeout=15)
        if r.status_code != 200:
            return {"url": None, "error": f"search HTTP {r.status_code}"}

        rows = r.json().get("data", [])
        if not rows:
            return {"url": None, "error": f"ไม่พบ tracking {tracking_no} ใน iShip"}

        row = rows[0]
        order_id = None
        for field in ("checkbox", "print_btn", "detail_btn"):
            html = row.get(field, "") or ""
            m = re.search(r'(\d{6,})', html)
            if m:
                order_id = m.group(1)
                break

        if not order_id:
            return {"url": None, "error": "หา order ID ไม่เจอ",
                    "_debug": {k: str(v)[:200] for k, v in row.items()}}

        return {"url": f"{WEB_BASE}/print/a6?order={order_id}",
                "order_id": order_id, "error": None}
    except Exception as e:
        return {"url": None, "error": str(e)}
