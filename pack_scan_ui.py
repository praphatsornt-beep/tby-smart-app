"""UI for 📷 แพคของ — ถ่ายรูปบาร์โค้ด/QR บนใบปะหน้าพัสดุ (Shopee/Lazada/iship) เพื่อบันทึก
เวลาแพคของแต่ละชิ้น (เพิ่ม 2026-10-25 ตามคำขอ) บันทึกแยกเป็นประวัติการแพค ไม่ผูกกับออเดอร์
โดยตรง (ยืนยันกับ user แล้ว — Shopee/Lazada ไม่เคยเก็บเลข tracking ไว้ที่ไหนเลย มีแค่
order_sn เท่านั้น ไม่มีอะไรให้ join) ยกเว้นออเดอร์ iship ที่ shipments.tracking_no มีอยู่แล้ว
จะ match ชื่อลูกค้า/ขนส่งให้อัตโนมัติตอนสแกน — ส่วน "มาจากระบบไหน" (Shopee/Lazada/iship)
เดาแยก 3 ทางด้วย `_guess_source()`: iship รู้แน่นอนจาก match, Lazada เดาจากคำนำหน้าเลข
tracking "LEX" (ขนส่งในเครือ Lazada เอง ไม่มีใน carrier list ของ iship เลย), ที่เหลือเดาเป็น
Shopee (ดีที่สุดเท่าที่ทำได้ — ไม่ใช่ข้อเท็จจริง 100%)

เดิมใช้ st.camera_input() (ถ่ายรูปทีละใบ ต้องกดถ่ายเอง) → เปลี่ยนเป็น live-scan ต่อเนื่องด้วย
`streamlit-camera-input-live` 2026-10-28 (user: "ใช้ในมือถือไม่สะดวก พอเป็นแบบถ่ายรูปมันช้า")
→ **เปลี่ยนอีกรอบ 2026-11-08** มาเป็น custom component ที่เขียนเอง (`qr_scanner_component/`,
ห่อ `html5-qrcode` JS library) หลัง user แจ้งปัญหาที่ตัวเดิมแก้ไม่ได้จริงๆ: "ช่องเล็ก กล้องไม่
โฟกัส QR หรือ barcode" — root cause คือ `streamlit-camera-input-live` ไม่เปิดให้ปรับ video
constraints เลยจาก Python (มีแค่ key/debounce/show_controls/width/height) และกลไก "สแน็ปช็อต
ทีละเฟรมส่งมาถอดรหัสฝั่ง Python" ไม่ได้ให้เวลากล้องโฟกัสต่อเนื่องเท่าการเปิด <video> stream
ค้างไว้จริงๆ แบบที่ html5-qrcode ทำ — เห็นตัวอย่างใช้งานจริงบนมือถือสำเร็จแล้วใน LIFF ของ
โปรเจกต์อื่น (`waka tournament/liff/app.html`) เลยเอาวิธีเดียวกันมาใช้ที่นี่ แทนที่จะหา Python
wrapper package สำเร็จรูป (เช็คแล้ว `streamlit-qrcode-scanner` บน PyPI มีแค่ ~11 ดาว ไม่ยืนยัน
ว่ารองรับ Code128 ด้วยหรือเปล่า เสี่ยงเกินไปเทียบกับเขียน component เองที่คุมพฤติกรรมได้เต็มที่)

`qr_scanner_component/index.html` เป็น **static component แบบ no-build** (ไม่มี React/Webpack)
— เขียน Streamlit component postMessage protocol เองตรงๆ (`streamlit:componentReady`/
`streamlit:render`/`streamlit:setComponentValue`/`streamlit:setFrameHeight`, ทุกข้อความมี
`isStreamlitMessage:true` กำกับ) แทนที่จะพึ่ง `streamlit-component-lib` (เป็น npm package
สำหรับ build pipeline ปกติ ไม่เหมาะกับไฟล์ HTML เดี่ยวๆ แบบนี้) ฝั่ง JS สแกนต่อเนื่องด้วย
`Html5Qrcode.start()` จำกัด `formatsToSupport:[0,5]` (QR_CODE, CODE_128 เท่านั้น — ตรงกับที่
ใบปะหน้าจริงใช้ และ decode ไวขึ้นเพราะไม่ต้องลองทุก format) ส่งค่ากลับ Python ทุกครั้งที่เจอโค้ด
ผ่าน `setComponentValue({code, ts})` — ฝั่ง JS throttle การส่งค่าเองไว้ที่ ~600ms/โค้ดเดิม (กัน
ยิง rerun รัวเกินไปตอนโค้ดเดิมค้างอยู่ในเฟรม เทียบเท่ากับ debounce=700 ของตัวเดิมที่เคยใช้)
ไม่ได้ย้าย business logic (คัดเลข order_sn ของ Shopee, cooldown กันบันทึกซ้ำ) ไปไว้ฝั่ง JS เลย
— ยังคงทำทั้งหมดฝั่ง Python เหมือนเดิมทุกจุด มีแค่ชั้นถอดรหัสภาพที่เปลี่ยน

**พฤติกรรมที่ต้องรักษาไว้ให้เหมือนเดิม**: ใบปะหน้าบางแบบ (เช่น SPX) มีทั้งบาร์โค้ด tracking
และ QR เส้นทางภายในที่ไม่ใช่เลข tracking ปนอยู่ในใบเดียว — ของเดิมถอดรหัสทั้งภาพทีเดียวเห็น
ทุกโค้ดพร้อมกัน เลยรู้ได้ว่า "เจอ 2 โค้ด ให้เลือกเอง" แต่ `Html5Qrcode.start()`'s callback ส่ง
กลับมาทีละโค้ดต่อครั้งที่เจอ ไม่ใช่ทุกโค้ดในเฟรมพร้อมกัน — จำลองพฤติกรรมเดิมด้วย "rolling
window" ฝั่ง Python แทน (`_PACK_QR_WINDOW_SEC`): เก็บโค้ดทุกตัวที่เพิ่งเห็นภายในช่วงเวลาสั้นๆ
ไว้ใน session_state ถ้ามีมากกว่า 1 โค้ดที่ไม่ใช่ order_sn ปรากฏพร้อมกันในหน้าต่างเวลานี้ ก็ยัง
ถามผู้ใช้เลือกเหมือนเดิม — ไม่ได้แปลว่าต้องเห็นพร้อมกันในเฟรมเป๊ะๆ แต่ในทางปฏิบัติกล้องจะส่าย
เจอสลับไปมาระหว่าง 2 โค้ดในช่วง 1-2 วินาทีที่ส่องค้างอยู่อยู่ดี เลยยังจับคู่ได้เหมือนเดิม

import `streamlit.components.v1` ตรงนี้เลย (ไม่ lazy เหมือน `zxingcpp`/`camera_input_live`
เดิม) เพราะเป็นส่วนหนึ่งของ Streamlit เองอยู่แล้ว ไม่ใช่ third-party wheel ที่เสี่ยง build พัง
"""
import os
import re
import time
from datetime import date, datetime, timezone

import streamlit as st
import streamlit.components.v1 as components

import database as db

_QR_COMPONENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qr_scanner_component")
_qr_scanner = components.declare_component("qr_scanner", path=_QR_COMPONENT_DIR)

# หน้าต่างเวลา (วินาที) ที่ถือว่าโค้ดที่เพิ่งสแกนเจอ "ยังอยู่ในรอบเดียวกัน" — ถ้ามีมากกว่า 1 โค้ด
# (ไม่นับ order_sn) ปรากฏภายในช่วงนี้ ถือว่าใบเดียวกันมีหลายโค้ดปนกัน ต้องถามผู้ใช้เลือก (ดู
# คำอธิบายยาวด้านบน) — สั้นไปจะพลาดจับคู่ 2 โค้ดที่ส่ายกล้องเจอห่างกันหน่อย ยาวไปจะค้างโค้ดเก่าที่
# เลื่อนพ้นเฟรมไปแล้วให้ดูเหมือนยังอยู่
_PACK_QR_WINDOW_SEC = 1.8

# กันบันทึกซ้ำเลข tracking เดิมถี่เกินไปตอน live-scan — พัสดุชิ้นเดียวอาจยังค้างอยู่ในเฟรม
# กล้องต่ออีกหลายวินาทีกว่าจะหยิบออก (ต่าง st.camera_input เดิมที่ต้องกดถ่ายใหม่ทุกครั้ง เลย
# ไม่มีปัญหานี้มาก่อน) ไม่บล็อกถาวร แค่เว้นช่วงพอให้ขยับพัสดุออกจากเฟรมทัน ถ้าสแกนเลขเดิมซ้ำ
# จริงๆ (เช่น แพคซ้ำจริง) หลังพ้น cooldown แล้วก็ยังบันทึกได้ตามปกติ — insert_pack_event เอง
# ก็ยัง append-only ไม่ dedup ที่ DB อยู่ดี (ดู docstring ของมันเอง)
#
# **บั๊กจริงพบ 2026-11-08** (user report: สแกนโค้ดเดิมค้างในเฟรม ได้แถวซ้ำ 4 แถว เวลาเดียวกัน
# เป๊ะ) — cooldown ด้านบนเดิมเช็คจาก `st.session_state` อย่างเดียว (in-memory ของ session นั้นๆ)
# ซึ่งรีเซ็ตได้ทุกครั้งที่ WebSocket ของมือถือหลุด/reconnect (สลับแอป, จอดับ, เน็ตสะดุด — พบบ่อย
# ระหว่างส่องกล้องค้างไว้นานๆ) ทำให้ cooldown ถูกลืมและบันทึกซ้ำได้ทันทีทุกครั้งที่ reconnect แม้
# โค้ดจะยังเป็นอันเดิมอยู่ในเฟรมก็ตาม — เสริมด้วยเช็คจาก DB จริง (`get_last_pack_event`, ดู
# `_classify_and_save`) เป็นด่านสุดท้ายที่ session reset เอาชนะไม่ได้ ใน-memory check ด้านบนยัง
# เก็บไว้เป็นด่านแรก (เร็วกว่า ไม่ query DB ทุกครั้งที่เจอโค้ดเดิมในเฟรมเดียวกัน)
_PACK_SAVE_COOLDOWN_SEC = 6

# เลข tracking ที่ขึ้นต้นด้วยคำนำหน้าพวกนี้ = ขนส่งในเครือ Lazada เอง (Lazada eLogistics/"LEX")
# ยืนยันจากรูปใบปะหน้า Lazada จริง 2026-10-25 (LEXDO0189817323) — ไม่มีอยู่ในลิสต์ขนส่งของ
# iship เลยสักตัว (ดู carriers.py's _CARRIER_DEFS: Flash/SPX/KEX/DHL/EMS/Inter/J&T เท่านั้น
# ไม่มี LEX) ฉะนั้นเจอคำนำหน้านี้ = มั่นใจได้ว่าไม่ใช่ออเดอร์ iship ของร้านเองแน่ๆ และน่าจะเป็น
# Lazada เกือบชัวร์ (ต่างจาก SPX/Flash ที่ทั้ง iship และ Shopee ใช้ร่วมกัน เลขคำนำหน้าแบบนั้น
# แยกไม่ได้จริงๆ ว่าใครส่ง ต้อง match กับ shipments เท่านั้นถึงจะมั่นใจ)
_LAZADA_TRACKING_PREFIXES = ("LEX",)

# รูปแบบเลขที่ออเดอร์ Shopee — YYMMDD (6 หลัก) + 8 ตัวอักษร/ตัวเลข เช่น "261024F2DR9DEW"
# (ยืนยันจากใบปะหน้า Shopee จริง 2026-10-25 — มีบาร์โค้ดเลขออเดอร์แยกต่างหากจากบาร์โค้ด
# tracking หลักบนใบเดียวกัน) เจอรหัสนี้ตอนสแกน = รู้แน่นอนว่าเป็น Shopee ไม่ใช่แค่เดาแล้ว
# (ต่างจาก _guess_source ด้านล่างที่เดา Shopee แบบ "ที่เหลือทั้งหมด") — ไม่ชนกับ tracking
# number ของขนส่งไหนเลย (ทุกเจ้าขึ้นต้นด้วยตัวอักษรเสมอ ไม่ใช่ตัวเลขล้วน 6 หลักแบบนี้) และ
# ไม่ชนกับเลขที่ออเดอร์ Lazada (ยาว 16 หลักตัวเลขล้วน ไม่มีตัวอักษรปน)
_SHOPEE_ORDER_SN_RE = re.compile(r"^\d{6}[A-Za-z0-9]{8}$")


def _looks_like_shopee_order_sn(code: str) -> bool:
    return bool(_SHOPEE_ORDER_SN_RE.match(code))


def _guess_source(tracking_no: str, shipment: dict | None) -> str:
    """เดาว่า tracking_no นี้มาจากระบบไหน (เพิ่ม 2026-10-25 ตามคำถาม "พออ่านแล้วจะทราบมั้ยว่า
    เป็นการบันทึกจากระบบ shopee lazada หรือ iship") — มีแค่กรณี iship เท่านั้นที่ "รู้แน่นอน"
    (match ตรงกับ shipments.tracking_no ของร้านเอง) ส่วน Lazada เดาจากคำนำหน้า LEX (ดูเหตุผล
    ที่ _LAZADA_TRACKING_PREFIXES ด้านบน) ที่เหลือ (ไม่ match iship และไม่ใช่คำนำหน้า Lazada)
    เดาเป็น Shopee เพราะเป็นแพลตฟอร์มที่เหลือที่ใช้งานจริงตอนนี้ — แต่เป็นแค่การเดาที่ดีที่สุด
    เท่าที่ทำได้ ไม่ใช่ข้อเท็จจริง 100% (เช่น ถ้าวันหลังมีออเดอร์ TikTok มาสแกนด้วย จะโดนเดา
    เป็น Shopee ผิดไปด้วย — ยังไม่มีเคสจริงให้เช็คตอนนี้)"""
    if shipment:
        return "iship"
    if tracking_no.upper().startswith(_LAZADA_TRACKING_PREFIXES):
        return "lazada"
    return "shopee"


_SOURCE_LABELS = {
    "iship": "iship (ของร้านเอง — ยืนยันแล้ว)",
    "lazada": "Lazada (เดาจากเลข LEX)",
    "shopee": "Shopee (เดา)",
}


def _last_event_within_cooldown(last_event: dict | None) -> bool:
    """เช็คจากเวลาจริงใน DB (ไม่ใช่ session_state) ว่า tracking_no นี้เพิ่งถูกบันทึกไปเมื่อครู่นี้
    เอง — ด่านสุดท้ายกัน insert ซ้ำตอน session_state cooldown ใน `_try_save` โดนลืมไปเพราะ
    WebSocket reconnect (ดูคอมเมนต์ยาวที่ `_PACK_SAVE_COOLDOWN_SEC` ด้านบน)"""
    if not last_event or not last_event.get("packed_at"):
        return False
    try:
        _ts = str(last_event["packed_at"]).replace("Z", "+00:00")
        _last_dt = datetime.fromisoformat(_ts)
        if _last_dt.tzinfo is None:
            _last_dt = _last_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    return (datetime.now(timezone.utc) - _last_dt).total_seconds() < _PACK_SAVE_COOLDOWN_SEC


def _classify_and_save(tracking_no: str, order_sn: str | None = None) -> dict:
    """เช็คว่า tracking_no นี้ตรงกับ shipments (ออเดอร์ iship ของร้านเอง) ไหม แล้วบันทึกลง
    pack_events — คืน dict สรุปผลให้ render() เอาไปแสดง (query แค่ครั้งเดียว ไม่ query ซ้ำ)
    order_sn (ถ้ามี — มาจากบาร์โค้ดเลขที่ออเดอร์ Shopee แยกที่สแกนเจอในภาพเดียวกัน) ทำให้รู้
    แน่นอนว่าเป็น Shopee เลย ไม่ต้องพึ่ง _guess_source แบบเดาที่เหลือทั้งหมดอีกต่อไป

    ข้าม insert ถ้า `get_last_pack_event` บอกว่าเพิ่งบันทึกเลขนี้ไปเมื่อครู่นี้เอง (ภายใน
    `_PACK_SAVE_COOLDOWN_SEC`) — ด่าน DB-backed กันซ้ำ ไม่พึ่ง session_state อย่างเดียว (ดู
    คอมเมนต์ที่ `_PACK_SAVE_COOLDOWN_SEC`)"""
    shipment = db.find_shipment_by_tracking_no(tracking_no)
    last_event = db.get_last_pack_event(tracking_no)
    _skip_dup = _last_event_within_cooldown(last_event)
    if shipment:
        source = "iship"
    elif order_sn:
        source = "shopee"
    elif _skip_dup:
        source = last_event.get("source") or "shopee"
    else:
        source = _guess_source(tracking_no, shipment)
    if shipment:
        customer_name = (shipment.get("customers") or {}).get("name")
        carrier = shipment.get("carrier")
    elif _skip_dup:
        customer_name = last_event.get("matched_customer_name")
        carrier = last_event.get("matched_carrier")
    else:
        customer_name = None
        carrier = None
    if not _skip_dup:
        db.insert_pack_event(tracking_no, source, customer_name, carrier, order_sn)
    return {
        "tracking_no": tracking_no,
        "source": source,
        "order_sn": order_sn or ((last_event or {}).get("order_sn") if _skip_dup else None),
        "customer_name": customer_name,
        "carrier": carrier,
        "already_scanned_before": last_event is not None,
        "last_scanned_at": last_event.get("packed_at") if last_event else None,
        "skipped_duplicate": _skip_dup,
    }


def _show_result(result: dict) -> None:
    _label = _SOURCE_LABELS.get(result["source"], result["source"])
    if result.get("skipped_duplicate"):
        st.info(
            f"ℹ️ เพิ่งบันทึกเลข **{result['tracking_no']}** ไปแล้วเมื่อครู่นี้เอง — ข้ามไม่บันทึกซ้ำ "
            "(ขยับพัสดุออกจากกล้องก่อนสแกนชิ้นถัดไป)"
        )
        return
    if result["source"] == "iship" and result["customer_name"]:
        st.success(
            f"✅ บันทึกแพคแล้ว: **{result['tracking_no']}** "
            f"({result['carrier'] or '-'}) — คุณ{result['customer_name']}"
        )
    elif result.get("order_sn"):
        st.success(
            f"✅ บันทึกแพคแล้ว: **{result['tracking_no']}** — {_label} "
            f"(ออเดอร์ {result['order_sn']})"
        )
    else:
        st.success(f"✅ บันทึกแพคแล้ว: **{result['tracking_no']}** — {_label}")
    if result["already_scanned_before"]:
        st.warning(
            f"⚠️ เคยสแกนเลขนี้มาก่อนแล้ว (ล่าสุด {result['last_scanned_at']}) — "
            "เช็คหน่อยว่าไม่ได้แพคซ้ำนะคะ"
        )


def _try_save(tracking_no: str, order_sn: str | None) -> bool:
    """บันทึกถ้าไม่ติด cooldown ของเลขเดิม — คืน True ถ้าบันทึกจริง (ให้ caller rerun ต่อ)"""
    _now = time.monotonic()
    _last_code = st.session_state.get("_pack_live_last_code")
    _last_at = st.session_state.get("_pack_live_last_saved_at", 0.0)
    if tracking_no == _last_code and (_now - _last_at) < _PACK_SAVE_COOLDOWN_SEC:
        return False
    st.session_state["_pack_last_result"] = _classify_and_save(tracking_no, order_sn=order_sn)
    st.session_state["_pack_live_last_code"] = tracking_no
    st.session_state["_pack_live_last_saved_at"] = _now
    return True


def render():
    st.subheader("📷 แพคของ")
    st.caption(
        "ส่องกล้องไปที่บาร์โค้ด/QR บนใบปะหน้าพัสดุ — อ่านต่อเนื่องอัตโนมัติ ไม่ต้องกดถ่ายรูป "
        "รองรับ Shopee/Lazada/iship ทั้งหมด (ของ Shopee/Lazada บันทึกเป็นประวัติการแพคเฉยๆ "
        "ไม่ผูกกับออเดอร์)"
    )

    _last = st.session_state.get("_pack_last_result")
    if _last:
        _show_result(_last)

    try:
        result = _qr_scanner(key="_pack_qr_scanner")
    except Exception as e:
        st.error(f"❌ โหลดกล้องไม่สำเร็จ: {e}")
        st.divider()
        _render_history_log()
        return

    # component ส่งค่าใหม่ทุกครั้งที่ JS เจอโค้ด (throttle เองฝั่ง JS ไว้แล้ว ~600ms/โค้ดเดิม) —
    # เช็ค ts กันประมวลผลค่าเดิมซ้ำตอน rerun ด้วยสาเหตุอื่นที่ไม่ใช่โค้ดใหม่จริง (เช่น กดปุ่ม
    # เลือกโค้ดด้านล่าง ก็ทำให้ render() รันใหม่ทั้งฟังก์ชัน ค่าจาก component จะเป็นค่าเดิมค้างอยู่)
    if result and result.get("code") and result.get("ts") != st.session_state.get("_pack_qr_last_ts"):
        st.session_state["_pack_qr_last_ts"] = result["ts"]
        _now = time.monotonic()
        _recent = {c: t for c, t in st.session_state.get("_pack_qr_recent", {}).items()
                   if _now - t < _PACK_QR_WINDOW_SEC}
        _recent[result["code"]] = _now
        st.session_state["_pack_qr_recent"] = _recent

    _now = time.monotonic()
    _recent = {c: t for c, t in st.session_state.get("_pack_qr_recent", {}).items()
               if _now - t < _PACK_QR_WINDOW_SEC}
    st.session_state["_pack_qr_recent"] = _recent
    codes = list(_recent.keys())

    # แยกรหัสที่ "หน้าตาเหมือนเลขที่ออเดอร์ Shopee" ออกมาต่างหากก่อน (ถ้ามี) — ที่เหลือถึง
    # ไปตีความเป็น "เลข tracking" ตามปกติ กันกรณีใบ Shopee มีทั้ง 2 บาร์โค้ดอยู่ในภาพเดียว
    # (ยืนยันจากใบจริง) ไม่ให้ผู้ใช้ต้องมานั่งเลือกเองว่าอันไหนคือ tracking อันไหนคือเลขออเดอร์
    _order_sn = next((c for c in codes if _looks_like_shopee_order_sn(c)), None)
    _tracking_candidates = [c for c in codes if c != _order_sn]

    if not codes:
        # ยังไม่เจอโค้ดเลย/โค้ดที่เคยเห็นหลุดพ้นหน้าต่างเวลาไปแล้ว — เรื่องปกติของ live-scan
        # ไม่ต้องขึ้น error ทุกครั้งเหมือนตอนเป็นถ่ายทีละรูป แค่บอกเฉยๆ ว่ากำลังหาอยู่
        st.caption("👀 กำลังหาบาร์โค้ด/QR...")
    elif len(_tracking_candidates) == 1:
        if _try_save(_tracking_candidates[0], _order_sn):
            st.session_state.pop("_pack_qr_recent", None)
            st.rerun()
    elif not _tracking_candidates and _order_sn:
        # เจอแต่เลขที่ออเดอร์ ไม่มีบาร์โค้ด tracking ติดมาด้วยเลย (เช่น มุมกล้องเห็นไม่ครบใบ) —
        # ใช้เลขออเดอร์เป็น tracking_no ไปก่อน ยังดีกว่าไม่บันทึกอะไรเลย
        if _try_save(_order_sn, _order_sn):
            st.session_state.pop("_pack_qr_recent", None)
            st.rerun()
    else:
        st.warning(f"พบ {len(_tracking_candidates)} รหัสที่อาจเป็นเลข tracking — เลือกอันที่ถูก:")
        for c in _tracking_candidates:
            if st.button(f"✅ {c}", key=f"_pack_pick_{c}", width="stretch"):
                if _try_save(c, _order_sn):
                    st.session_state.pop("_pack_qr_recent", None)
                    st.rerun()

    st.divider()
    _render_history_log()


def _render_history_log() -> None:
    """ประวัติการแพค — ย้อนดูช่วงวันที่ก่อนหน้าได้ด้วย (เพิ่ม 2026-11-08 ตามคำขอ; เดิมโชว์แค่
    วันนี้วันเดียว ไม่มีทางย้อนดูวันก่อนหน้าเลย)"""
    st.markdown("**📋 ประวัติแพค**")
    _today = date.today()
    _range_key = "_pack_hist_range"
    if _range_key not in st.session_state:
        st.session_state[_range_key] = (_today, _today)
    _range = st.date_input(
        "ช่วงวันที่", value=st.session_state[_range_key], key=_range_key, format="DD/MM/YYYY",
    )
    # st.date_input คืนค่าเป็น tuple 2 ตัวเฉพาะตอนเลือกครบ "ถึงวันที่" แล้ว — ระหว่างเลือกวันแรก
    # วันเดียวจะคืนเป็น tuple 1 ตัว ต้องกันพังตรงนี้ไม่งั้น unpack ไม่ได้
    if isinstance(_range, tuple) and len(_range) == 2:
        _date_from, _date_to = _range
    elif isinstance(_range, tuple) and len(_range) == 1:
        _date_from = _date_to = _range[0]
    else:
        _date_from = _date_to = _range

    df = db.get_pack_events_df(date_from=_date_from.isoformat(), date_to=_date_to.isoformat())
    if df.empty:
        st.caption("ไม่มีการสแกนในช่วงที่เลือก")
        return
    _range_label = (
        "วันนี้" if (_date_from == _today and _date_to == _today)
        else f"{_date_from.strftime('%d/%m/%Y')} - {_date_to.strftime('%d/%m/%Y')}"
    )
    st.caption(f"แพคไปแล้ว {len(df)} ชิ้น ({_range_label})")
    df = df.copy()
    df["source"] = df["source"].map(lambda s: _SOURCE_LABELS.get(s, s))
    _cols = ["packed_at", "tracking_no", "source", "order_sn", "matched_customer_name", "matched_carrier"]
    _cols = [c for c in _cols if c in df.columns]
    st.dataframe(
        df[_cols].rename(columns={
            "packed_at": "เวลา", "tracking_no": "Tracking", "source": "ที่มา",
            "order_sn": "เลขออเดอร์ (Shopee)",
            "matched_customer_name": "ลูกค้า (iship)", "matched_carrier": "ขนส่ง (iship)",
        }),
        width="stretch", hide_index=True,
    )
