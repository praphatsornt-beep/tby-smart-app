"""UI for 📷 แพคของ — ถ่ายรูปบาร์โค้ด/QR บนใบปะหน้าพัสดุ (Shopee/Lazada/iship) เพื่อบันทึก
เวลาแพคของแต่ละชิ้น (เพิ่ม 2026-10-25 ตามคำขอ) บันทึกแยกเป็นประวัติการแพค ไม่ผูกกับออเดอร์
โดยตรง (ยืนยันกับ user แล้ว — Shopee/Lazada ไม่เคยเก็บเลข tracking ไว้ที่ไหนเลย มีแค่
order_sn เท่านั้น ไม่มีอะไรให้ join) ยกเว้นออเดอร์ iship ที่ shipments.tracking_no มีอยู่แล้ว
จะ match ชื่อลูกค้า/ขนส่งให้อัตโนมัติตอนสแกน

ใช้ st.camera_input() (ถ่ายรูปทีละใบ) แทน live-scan ผ่านกล้องต่อเนื่อง (เช่น streamlit-webrtc)
โดยตั้งใจ — ไม่มี TURN server ตั้งไว้สำหรับ Streamlit Community Cloud เลย ความเสี่ยงเรื่อง
WebRTC เชื่อมต่อไม่ติดสำหรับผู้ใช้หลังบ้าน NAT สูงกว่าความเร็วที่ได้มา (ดู good_version/
segfault incident ในอดีต — โปรเจกต์นี้ระวังเรื่อง binary dependency เปราะบางบน Cloud อยู่แล้ว)
"""
from datetime import date

import streamlit as st
from PIL import Image

import database as db


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


def _classify_and_save(tracking_no: str) -> dict:
    """เช็คว่า tracking_no นี้ตรงกับ shipments (ออเดอร์ iship ของร้านเอง) ไหม แล้วบันทึกลง
    pack_events — คืน dict สรุปผลให้ render() เอาไปแสดง (query แค่ครั้งเดียว ไม่ query ซ้ำ)"""
    shipment = db.find_shipment_by_tracking_no(tracking_no)
    last_event = db.get_last_pack_event(tracking_no)
    if shipment:
        source = "iship"
        customer_name = (shipment.get("customers") or {}).get("name")
        carrier = shipment.get("carrier")
    else:
        source = "other"
        customer_name = None
        carrier = None
    db.insert_pack_event(tracking_no, source, customer_name, carrier)
    return {
        "tracking_no": tracking_no,
        "source": source,
        "customer_name": customer_name,
        "carrier": carrier,
        "already_scanned_before": last_event is not None,
        "last_scanned_at": last_event.get("packed_at") if last_event else None,
    }


def _show_result(result: dict) -> None:
    if result["source"] == "iship" and result["customer_name"]:
        st.success(
            f"✅ บันทึกแพคแล้ว: **{result['tracking_no']}** "
            f"({result['carrier'] or '-'}) — คุณ{result['customer_name']}"
        )
    else:
        st.success(f"✅ บันทึกแพคแล้ว: **{result['tracking_no']}**")
    if result["already_scanned_before"]:
        st.warning(
            f"⚠️ เคยสแกนเลขนี้มาก่อนแล้ว (ล่าสุด {result['last_scanned_at']}) — "
            "เช็คหน่อยว่าไม่ได้แพคซ้ำนะคะ"
        )


def render():
    st.subheader("📷 แพคของ")
    st.caption(
        "ถ่ายรูปบาร์โค้ด/QR บนใบปะหน้าพัสดุ เพื่อบันทึกเวลาแพค — รองรับ Shopee/Lazada/iship "
        "ทั้งหมด (ของ Shopee/Lazada บันทึกเป็นประวัติการแพคเฉยๆ ไม่ผูกกับออเดอร์)"
    )

    _last = st.session_state.get("_pack_last_result")
    if _last:
        _show_result(_last)

    _ver = st.session_state.get("_pack_cam_ver", 0)
    photo = st.camera_input("📸 ถ่ายรูปบาร์โค้ด/QR บนใบปะหน้า", key=f"_pack_cam_{_ver}")

    if photo is not None:
        try:
            codes = _decode_codes(Image.open(photo))
        except Exception as e:
            st.error(f"❌ ถอดรหัสไม่สำเร็จ: {e}")
            codes = []

        if not codes:
            st.error("❌ อ่านไม่ออก — ลองถ่ายใหม่ให้บาร์โค้ด/QR อยู่กลางภาพ คมชัด และไม่สะท้อนแสง")
        elif len(codes) == 1:
            st.session_state["_pack_last_result"] = _classify_and_save(codes[0])
            st.session_state["_pack_cam_ver"] = _ver + 1
            st.rerun()
        else:
            st.warning(f"พบ {len(codes)} รหัสในภาพเดียว — เลือกรหัสที่เป็นเลข tracking:")
            for i, c in enumerate(codes):
                if st.button(f"✅ {c}", key=f"_pack_pick_{_ver}_{i}", width="stretch"):
                    st.session_state["_pack_last_result"] = _classify_and_save(c)
                    st.session_state["_pack_cam_ver"] = _ver + 1
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
    _cols = ["packed_at", "tracking_no", "source", "matched_customer_name", "matched_carrier"]
    st.dataframe(
        df[_cols].rename(columns={
            "packed_at": "เวลา", "tracking_no": "Tracking", "source": "ที่มา",
            "matched_customer_name": "ลูกค้า (iship)", "matched_carrier": "ขนส่ง (iship)",
        }),
        width="stretch", hide_index=True,
    )
