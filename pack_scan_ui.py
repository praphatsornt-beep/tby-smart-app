"""UI for 📷 แพคของ — ถ่ายรูปบาร์โค้ด/QR บนใบปะหน้าพัสดุ (Shopee/Lazada/iship) เพื่อบันทึก
เวลาแพคของแต่ละชิ้น (เพิ่ม 2026-10-25 ตามคำขอ) บันทึกแยกเป็นประวัติการแพค ไม่ผูกกับออเดอร์
โดยตรง (ยืนยันกับ user แล้ว — Shopee/Lazada ไม่เคยเก็บเลข tracking ไว้ที่ไหนเลย มีแค่
order_sn เท่านั้น ไม่มีอะไรให้ join) ยกเว้นออเดอร์ iship ที่ shipments.tracking_no มีอยู่แล้ว
จะ match ชื่อลูกค้า/ขนส่งให้อัตโนมัติตอนสแกน — ส่วน "มาจากระบบไหน" (Shopee/Lazada/iship)
เดาแยก 3 ทางด้วย `_guess_source()`: iship รู้แน่นอนจาก match, Lazada เดาจากคำนำหน้าเลข
tracking "LEX" (ขนส่งในเครือ Lazada เอง ไม่มีใน carrier list ของ iship เลย), ที่เหลือเดาเป็น
Shopee (ดีที่สุดเท่าที่ทำได้ — ไม่ใช่ข้อเท็จจริง 100%)

เดิมใช้ st.camera_input() (ถ่ายรูปทีละใบ ต้องกดถ่ายเอง) — เปลี่ยนเป็น live-scan ต่อเนื่องแทน
2026-10-28 ตามคำขอ (user: "ใช้ในมือถือไม่สะดวก พอเป็นแบบถ่ายรูปมันช้า") ใช้
`streamlit-camera-input-live` (ไม่ใช่ streamlit-webrtc) — ส่งภาพสแน็ปช็อตเป็น base64 ผ่าน
ช่องทาง component เดิมของ Streamlit เอง ทุกๆ debounce ms ไม่ได้เปิด WebRTC peer connection
จริงๆ เลย จึงไม่มีความเสี่ยงเรื่อง TURN server ที่เคยกังวลไว้ตอนเลือก st.camera_input แต่แรก
(ดู good_version/segfault incident — โปรเจกต์นี้ระวังเรื่อง binary dependency เปราะบางบน
Cloud อยู่แล้ว เช็คแล้วว่า pure-Python wheel ไม่มี native dependency เพิ่ม) ถอดรหัสทุกเฟรมที่
ได้มาด้วย `_decode_codes()` (zxing-cpp) เหมือนเดิมทุกจุด — แค่เปลี่ยนตัวป้อนภาพจาก "ถ่าย 1
ครั้งต่อคลิก" เป็น "สตรีมภาพมาเรื่อยๆ ให้ถอดรหัสเอง" กันกดบันทึกซ้ำเลขเดิมถี่เกินไปตอนพัสดุยัง
ไม่ทันหยิบออกจากเฟรมด้วย cooldown สั้นๆ ดู `_PACK_SAVE_COOLDOWN_SEC` ด้านล่าง — import
`camera_input_live` แบบ lazy (ในฟังก์ชัน ไม่ใช่ตอน import โมดูลนี้) เหมือน `zxingcpp` ใน
`_decode_codes()` ด้วยเหตุผลเดียวกัน: กันแอปทั้งตัวพังตอน boot ถ้า package นี้มีปัญหาบน
Cloud ที่ไม่คาดคิด ให้พังเฉพาะตอนเปิดแท็บนี้จริงๆ แทน
"""
import re
import time
from datetime import date

import streamlit as st
from PIL import Image

import database as db

# กันบันทึกซ้ำเลข tracking เดิมถี่เกินไปตอน live-scan — พัสดุชิ้นเดียวอาจยังค้างอยู่ในเฟรม
# กล้องต่ออีกหลายวินาทีกว่าจะหยิบออก (ต่าง st.camera_input เดิมที่ต้องกดถ่ายใหม่ทุกครั้ง เลย
# ไม่มีปัญหานี้มาก่อน) ไม่บล็อกถาวร แค่เว้นช่วงพอให้ขยับพัสดุออกจากเฟรมทัน ถ้าสแกนเลขเดิมซ้ำ
# จริงๆ (เช่น แพคซ้ำจริง) หลังพ้น cooldown แล้วก็ยังบันทึกได้ตามปกติ — insert_pack_event เอง
# ก็ยัง append-only ไม่ dedup ที่ DB อยู่ดี (ดู docstring ของมันเอง)
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


def _decode_codes(image: Image.Image) -> list[str]:
    """ถอดรหัสบาร์โค้ด/QR ทั้งหมดที่เจอในภาพเดียว คืนลิสต์ข้อความไม่ซ้ำ เรียงตามลำดับที่เจอ —
    แยกเป็นฟังก์ชันล้วน (ไม่แตะ Streamlit) ให้เทสได้โดยไม่ต้องง้อกล้องจริง ใบปะหน้าบางแบบ
    (เช่น SPX) มีทั้งบาร์โค้ด tracking + QR เส้นทางภายในของขนส่งที่ไม่ใช่เลข tracking อยู่ใน
    ภาพเดียวกัน — ถ้าเจอมากกว่า 1 รหัส ให้ผู้เรียกถามผู้ใช้เลือกเอง ไม่เดาให้
    import zxingcpp แบบ lazy (ไม่ใช่ตอน import โมดูลนี้) กันแอปทั้งตัวพังตอน boot ถ้า wheel
    นี้มีปัญหาบนแพลตฟอร์มไหนที่ไม่คาดคิด — ให้พังเฉพาะตอนกดใช้ฟีเจอร์นี้จริงๆ แทน"""
    import zxingcpp
    results = zxingcpp.read_barcodes(image.convert("RGB"))
    codes = []
    for r in results:
        if r.text and r.text not in codes:
            codes.append(r.text)
    return codes


def _classify_and_save(tracking_no: str, order_sn: str | None = None) -> dict:
    """เช็คว่า tracking_no นี้ตรงกับ shipments (ออเดอร์ iship ของร้านเอง) ไหม แล้วบันทึกลง
    pack_events — คืน dict สรุปผลให้ render() เอาไปแสดง (query แค่ครั้งเดียว ไม่ query ซ้ำ)
    order_sn (ถ้ามี — มาจากบาร์โค้ดเลขที่ออเดอร์ Shopee แยกที่สแกนเจอในภาพเดียวกัน) ทำให้รู้
    แน่นอนว่าเป็น Shopee เลย ไม่ต้องพึ่ง _guess_source แบบเดาที่เหลือทั้งหมดอีกต่อไป"""
    shipment = db.find_shipment_by_tracking_no(tracking_no)
    last_event = db.get_last_pack_event(tracking_no)
    if shipment:
        source = "iship"
    elif order_sn:
        source = "shopee"
    else:
        source = _guess_source(tracking_no, shipment)
    if shipment:
        customer_name = (shipment.get("customers") or {}).get("name")
        carrier = shipment.get("carrier")
    else:
        customer_name = None
        carrier = None
    db.insert_pack_event(tracking_no, source, customer_name, carrier, order_sn)
    return {
        "tracking_no": tracking_no,
        "source": source,
        "order_sn": order_sn,
        "customer_name": customer_name,
        "carrier": carrier,
        "already_scanned_before": last_event is not None,
        "last_scanned_at": last_event.get("packed_at") if last_event else None,
    }


def _show_result(result: dict) -> None:
    _label = _SOURCE_LABELS.get(result["source"], result["source"])
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

    # key คงที่ ไม่ versioned แบบ st.camera_input เดิม — component นี้ไม่ใช่ "ถ่ายแล้วค้างรูปไว้"
    # แต่สตรีมเฟรมใหม่มาเรื่อยๆ เองอยู่แล้ว ไม่ต้อง force-reset widget ทุกครั้งที่บันทึกสำเร็จ
    # (ถ้า bump key ทุกครั้ง จะรีสตาร์ท component ใหม่ ผู้ใช้ต้องกด "Start capturing" ซ้ำทุกครั้ง
    # ที่บันทึกของชิ้นนึงเสร็จ — เสียจุดประสงค์ "ไม่ต้องกดอะไรเลย" ไปเลย)
    try:
        from camera_input_live import camera_input_live
    except Exception as e:
        st.error(f"❌ โหลดกล้องไม่สำเร็จ: {e}")
        st.divider()
        _render_today_log()
        return
    frame = camera_input_live(key="_pack_cam_live", debounce=700, show_controls=True)

    if frame is not None:
        try:
            codes = _decode_codes(Image.open(frame))
        except Exception:
            codes = []

        # แยกรหัสที่ "หน้าตาเหมือนเลขที่ออเดอร์ Shopee" ออกมาต่างหากก่อน (ถ้ามี) — ที่เหลือถึง
        # ไปตีความเป็น "เลข tracking" ตามปกติ กันกรณีใบ Shopee มีทั้ง 2 บาร์โค้ดอยู่ในภาพเดียว
        # (ยืนยันจากใบจริง) ไม่ให้ผู้ใช้ต้องมานั่งเลือกเองว่าอันไหนคือ tracking อันไหนคือเลขออเดอร์
        _order_sn = next((c for c in codes if _looks_like_shopee_order_sn(c)), None)
        _tracking_candidates = [c for c in codes if c != _order_sn]

        if not codes:
            # เฟรมเปล่า/ยังไม่เจอโค้ด — เรื่องปกติของ live-scan (ยังไม่ได้ส่องตรงโค้ด หรือ
            # กำลังขยับกล้อง) ไม่ต้องขึ้น error ทุกเฟรมเหมือนตอนเป็นถ่ายทีละรูป แค่บอกเฉยๆ ว่า
            # กำลังหาอยู่ กันข้อความ error กระพริบถี่จนรำคาญ
            st.caption("👀 กำลังหาบาร์โค้ด/QR...")
        elif len(_tracking_candidates) == 1:
            if _try_save(_tracking_candidates[0], _order_sn):
                st.rerun()
        elif not _tracking_candidates and _order_sn:
            # เจอแต่เลขที่ออเดอร์ ไม่มีบาร์โค้ด tracking ติดมาด้วยเลย (เช่น มุมกล้องเห็นไม่ครบใบ) —
            # ใช้เลขออเดอร์เป็น tracking_no ไปก่อน ยังดีกว่าไม่บันทึกอะไรเลย
            if _try_save(_order_sn, _order_sn):
                st.rerun()
        else:
            st.warning(f"พบ {len(_tracking_candidates)} รหัสที่อาจเป็นเลข tracking — เลือกอันที่ถูก:")
            for c in _tracking_candidates:
                if st.button(f"✅ {c}", key=f"_pack_pick_{c}", width="stretch"):
                    if _try_save(c, _order_sn):
                        st.rerun()

    st.divider()
    _render_today_log()


def _render_today_log() -> None:
    st.markdown("**📋 ประวัติแพควันนี้**")
    _today = date.today().isoformat()
    df = db.get_pack_events_df(date_from=_today, date_to=_today)
    if df.empty:
        st.caption("ยังไม่มีการสแกนวันนี้")
        return
    st.caption(f"แพคไปแล้ว {len(df)} ชิ้นวันนี้")
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
