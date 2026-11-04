import os
import requests
import streamlit as st
from datetime import date

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


def _token() -> str:
    return os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") or st.secrets.get("LINE_CHANNEL_ACCESS_TOKEN", "")


def is_configured() -> bool:
    return bool(_token())


def _push(to_id: str, text: str, group_id: str = "") -> dict:
    """ส่งข้อความไปยัง to_id และ group_id (ถ้ามี)"""
    token = _token()
    if not token:
        return {"ok": False, "error": "ไม่มี LINE_CHANNEL_ACCESS_TOKEN ใน secrets"}
    if not to_id and not group_id:
        return {"ok": False, "error": "ไม่มี line_user_id หรือ group_id"}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    targets = [group_id] if group_id else [to_id]
    last_err = ""
    for tid in targets:
        try:
            r = requests.post(LINE_PUSH_URL, json={"to": tid, "messages": [{"type": "text", "text": text}]},
                              headers=headers, timeout=10)
            if r.status_code != 200:
                last_err = f"LINE API HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            last_err = str(e)
    return {"ok": not last_err, "error": last_err} if last_err else {"ok": True}


def push_tracking(line_user_id: str, dst_name: str, tracking: str,
                  carrier: str, cod: float = 0, group_id: str = "") -> dict:
    """ส่งข้อความแจ้ง tracking ให้ลูกค้าใน LINE"""
    lines = [
        f"ส่งของให้คุณ {dst_name} แล้วนะคะ 📦",
        f"ขนส่ง: {carrier}",
        f"เลขพัสดุ: {tracking}",
        f"ติดตาม: https://app.iship.cloud/tracking?track={tracking}",
    ]
    if cod > 0:
        lines.append(f"เก็บเงินปลายทาง: {int(cod):,} บาท")
    return _push(line_user_id, "\n".join(lines), group_id)


def push_outstanding(line_user_id: str, customer_name: str,
                     outstanding_amount: float, pending_qty: int,
                     items: list, cod_transferred: list = None,
                     group_id: str = "", pv_rows: list = None) -> dict:
    """ส่งสรุปยอดค้างให้ลูกค้าใน LINE

    pv_rows (เพิ่ม 2026-11-04 ตามคำขอ user "ตรงส่วนสรุปให้ลูกค้าทางไลน์ด้วย" ต่อจาก
    📅 รายการค้างเปิดบิล (PV) ที่เพิ่งเพิ่มในแอปเอง) — list จาก
    `ui_helpers.unbilled_pv_breakdown_rows()` ตรงๆ (`[{"date","items":[{"product","qty",
    "points"}],"day_total"}]`) แสดงเป็นหมวดแยกต่างหาก เพราะรายการที่จ่ายและรับครบแล้ว
    (เหลือแค่รอเปิดบิลเพื่อเก็บ PV) จะไม่โผล่ใน `items` เดิมเลย (ฟิลเตอร์ของ `items` คือ
    ค้างจ่าย>0 หรือค้างรับ>0 เท่านั้น ไม่เกี่ยวกับสถานะบิล) — ไม่งั้นลูกค้าจะไม่เห็นอะไร
    เลยถ้าทุกอย่างจ่าย/รับครบแล้วเหลือแค่รอเปิดบิล ทั้งที่ควรรู้ว่ายังมี PV ค้างสะสมอยู่"""
    lines = [f"คุณ {customer_name} มียอดค้างดังนี้ค่ะ 🙏"]
    if outstanding_amount > 0:
        lines.append(f"💰 ค้างจ่าย: {outstanding_amount:,.0f} บาท")
    if pending_qty > 0:
        lines.append(f"📦 ค้างรับ: {pending_qty} ชิ้น")
    if items:
        lines.append("")
        _max_items = 30
        for it in items[:_max_items]:
            bill = it.get("bill_no", "")
            prod = it.get("product", "")
            amt  = float(it.get("amount") or 0)
            qty  = int(it.get("qty") or 0)
            line = f"• บิล {bill}: {prod}"
            if qty > 0:
                line += f" ×{qty}"
            if amt > 0:
                line += f" {amt:,.0f}฿"
            lines.append(line)
        if len(items) > _max_items:
            lines.append(f"...และอีก {len(items) - _max_items} รายการ")
    if pv_rows:
        lines.append("")
        lines.append("⭐ คะแนนรอเปิดบิล:")
        _max_pv_dates = 15  # กันข้อความยาวเกินถ้าค้างเปิดบิลสะสมมานาน (เดือน/ปี)
        _grand_pv = 0.0
        for _pv_row in pv_rows[:_max_pv_dates]:
            lines.append(f"📅 {_pv_row['date']}")
            for _it in _pv_row["items"]:
                lines.append(f"  • {_it['product']} ×{int(_it['qty'])} = {_it['points']:,.0f} คะแนน")
            lines.append(f"  (รวมวันนี้ {_pv_row['day_total']:,.0f} คะแนน)")
            _grand_pv += _pv_row["day_total"]
        if len(pv_rows) > _max_pv_dates:
            lines.append(f"...และอีก {len(pv_rows) - _max_pv_dates} วัน")
            # วันที่เกินลิสต์ไม่ได้รวมในยอดข้างบนแล้ว — รวมยอดจริงทั้งหมดแยกต่างหาก
            # กันยอดรวมที่โชว์ไม่ตรงกับผลรวมของบรรทัดที่เห็นจริง
            _grand_pv = sum(r["day_total"] for r in pv_rows)
        lines.append(f"⭐ รวมคะแนนที่ยังไม่ได้เปิดบิลทั้งหมด: {_grand_pv:,.0f} คะแนน")
    if cod_transferred:
        lines.append("")
        lines.append("✅ COD รับยอดแล้ว — กรุณาติดต่อเปิดบิล:")
        for c in cod_transferred[:5]:
            tn  = c.get("tracking_no", "")
            amt = float(c.get("cod_amount") or 0)
            lines.append(f"• {tn}  {amt:,.0f}฿")
    return _push(line_user_id, "\n".join(lines), group_id)


def push_partial_receipt(line_user_id: str, product_name: str,
                         qty_received: float, amount_paid: float,
                         remaining_qty: float, remaining_amount: float,
                         product_code: str = "", group_id: str = "",
                         items: list = None, unbilled_qty: int = 0) -> dict:
    """แจ้งลูกค้าเมื่อรับของ/จ่ายเงินบางส่วน
    items: [{"product_name", "product_code", "qty_received"}] สำหรับหลายรายการ
    remaining_qty/remaining_amount: ยอดค้างรับ/ค้างจ่ายรวมทั้งลูกค้า (ไม่ใช่แค่รายการนี้)
    unbilled_qty: ค้างคีย์บิล (ยังไม่เปิดบิล) รวมทั้งลูกค้า — แสดงเป็นบรรทัดเพิ่มถ้า > 0
    """
    _today = date.today().strftime("%d.%m.%Y")
    lines = [f"รายการวันนี้ {_today} 📦"]
    if items:
        for it in items:
            _pc = it.get("product_code", "")
            _pn = it.get("product_name", "")
            _lbl = f"[{_pc}] {_pn}" if _pc else _pn
            _qs = f" ×{int(it.get('qty_received', 0))}" if it.get("qty_received", 0) > 0 else ""
            if _lbl:
                lines.append(f"• {_lbl}{_qs}")
    else:
        _prod_label = f"[{product_code}] {product_name}" if product_code else product_name
        if _prod_label:
            _qty_suffix = f" ×{int(qty_received)}" if qty_received > 0 else ""
            lines.append(f"• {_prod_label}{_qty_suffix}")
    if amount_paid > 0.01:
        lines.append(f"💰 จ่ายวันนี้: {amount_paid:,.0f} บาท")
    lines.append("")
    lines.append("คงเหลือ:")
    if remaining_qty > 0:
        lines.append(f"📦 ค้างรับ: {int(remaining_qty)} ชิ้น")
    if remaining_amount > 0.01:
        lines.append(f"💰 ค้างจ่าย: {remaining_amount:,.0f} บาท")
    if unbilled_qty > 0:
        lines.append(f"🧾 ค้างคีย์บิล (ยังไม่เปิดบิล): {int(unbilled_qty)} ชิ้น")
    if remaining_qty <= 0 and remaining_amount <= 0.01 and unbilled_qty <= 0:
        lines.append("✅ รับครบ จ่ายครบแล้วค่ะ")
    return _push(line_user_id, "\n".join(lines), group_id)


def push_text(line_user_id: str, text: str, group_id: str = "") -> dict:
    """ส่งข้อความอิสระหา LINE user"""
    return _push(line_user_id, text, group_id)


def push_bill_summary(line_user_id: str, customer_name: str, bill_no: str,
                      items: list, total_amount: float, pay_status: str,
                      paid_amount: float = None, outstanding_amount: float = None,
                      group_id: str = "") -> dict:
    """ส่งสรุปบิลให้ลูกค้าใน LINE"""
    lines = [f"📋 สรุปบิล {bill_no}", f"คุณ {customer_name}", ""]
    for it in items[:10]:
        lines.append(f"• {it['name']} ×{it['qty']} = {float(it['total']):,.0f}฿")
    lines += ["", f"💰 รวม: {total_amount:,.0f} บาท"]
    if paid_amount is not None and outstanding_amount is not None and outstanding_amount > 0.01:
        lines.append(f"✅ จ่ายแล้ว: {paid_amount:,.0f} บาท")
        lines.append(f"⏳ ค้างจ่าย: {outstanding_amount:,.0f} บาท")
    else:
        lines.append(f"สถานะ: {pay_status}")
    return _push(line_user_id, "\n".join(lines), group_id)
