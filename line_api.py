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


def _fmt_pv_lines(pv_rows: list, max_dates: int = 15) -> tuple[list, float]:
    """บรรทัด "คะแนนรอเปิดบิล" ต่อวัน/สินค้า — แยกออกมาจาก push_outstanding 2026-11-07
    ให้ push_unbilled_pv (ปุ่มส่งเฉพาะหัวข้อนี้) ใช้ร่วมกันได้โดยไม่ต้องเขียนซ้ำ"""
    lines, grand = [], 0.0
    for row in pv_rows[:max_dates]:
        lines.append(f"📅 {row['date']}")
        for it in row["items"]:
            _label = f"[{it['code']}] {it['product']}" if it.get("code") else it["product"]
            lines.append(f"  • {_label} ×{int(it['qty'])} = {it['points']:,.0f} คะแนน")
        lines.append(f"  (รวม {row['day_total']:,.0f} คะแนน)")
        lines.append("")  # เว้นบรรทัดระหว่างแต่ละวัน ให้อ่านง่ายขึ้น (เพิ่ม 2026-11-08 ตามคำขอ)
        grand += row["day_total"]
    if len(pv_rows) > max_dates:
        lines.append(f"...และอีก {len(pv_rows) - max_dates} วัน")
        # วันที่เกินลิสต์ไม่ได้รวมในยอดข้างบนแล้ว — รวมยอดจริงทั้งหมดแยกต่างหาก
        grand = sum(r["day_total"] for r in pv_rows)
    return lines, grand


def _fmt_loan_lines(loans: list, max_loans: int = 15) -> tuple[list, float]:
    """บรรทัด "ยืมคะแนนค้างคืน" ต่อก้อน — ใช้ร่วมกันระหว่าง push_outstanding (ส่วนสรุป
    รวมทั้งหมด) และ push_pv_loan_status (ปุ่มส่งเฉพาะหัวข้อนี้) — loans คือ dict จาก
    db.get_pv_loans_df() ที่กรองเหลือเฉพาะ is_settled=False แล้วจากฝั่งเรียก"""
    lines, grand = [], 0.0
    for ln in loans[:max_loans]:
        remaining = float(ln.get("pv_remaining") or 0)
        lines.append(
            f"🎁 ยืม {float(ln.get('pv_lent') or 0):,.0f} PV ({ln.get('lend_date','')}) "
            f"— ค้างคืนอีก {remaining:,.0f} PV"
        )
        grand += remaining
    if len(loans) > max_loans:
        lines.append(f"...และอีก {len(loans) - max_loans} รายการ")
        grand = sum(float(l.get("pv_remaining") or 0) for l in loans)
    return lines, grand


def build_outstanding_text(customer_name: str, outstanding_amount: float, pending_qty: int,
                           items: list, cod_transferred: list = None,
                           pv_rows: list = None, loan_rows: list = None) -> str:
    """สร้างข้อความ "สรุปรวมทั้งหมด" เดียวกับที่ push_outstanding ส่งทาง LINE เป๊ะๆ แต่คืนเป็น
    text เฉยๆ ไม่ส่ง — แยกออกมา 2026-11-08 ให้ bill_detail_ui.py เอาไปใช้พิมพ์/แคปจอได้ด้วย
    สำหรับลูกค้าที่ยังไม่มี LINE ID (กดส่ง LINE ไม่ได้เลย แต่ยังอยากได้สรุปเดียวกันนี้ไปส่งเอง
    ทางอื่น) — เนื้อหาต้องตรงกับที่ลูกค้าคนอื่นที่มี LINE ID ได้รับเป๊ะ ไม่ใช่สรุปคนละแบบ"""
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
        _pv_lines, _grand_pv = _fmt_pv_lines(pv_rows)
        lines.extend(_pv_lines)
        lines.append(f"⭐ รวมคะแนนที่ยังไม่ได้เปิดบิลทั้งหมด: {_grand_pv:,.0f} คะแนน")
    if loan_rows:
        lines.append("")
        lines.append("💳 ยืมคะแนนค้างคืน:")
        _loan_lines, _grand_loan = _fmt_loan_lines(loan_rows)
        lines.extend(_loan_lines)
        lines.append(f"💳 รวมค้างคืนทั้งหมด: {_grand_loan:,.0f} PV")
    if cod_transferred:
        lines.append("")
        lines.append("✅ COD รับยอดแล้ว — กรุณาติดต่อเปิดบิล:")
        for c in cod_transferred[:5]:
            tn  = c.get("tracking_no", "")
            amt = float(c.get("cod_amount") or 0)
            lines.append(f"• {tn}  {amt:,.0f}฿")
    return "\n".join(lines)


def push_outstanding(line_user_id: str, customer_name: str,
                     outstanding_amount: float, pending_qty: int,
                     items: list, cod_transferred: list = None,
                     group_id: str = "", pv_rows: list = None, loan_rows: list = None) -> dict:
    """ส่งสรุปยอดค้างให้ลูกค้าใน LINE — เนื้อหาสร้างจาก build_outstanding_text() ด้านบน
    (แยกออกมาเป็นฟังก์ชันเดียวเพื่อให้ปุ่มพิมพ์สำหรับลูกค้าที่ไม่มี LINE ID ใช้ข้อความ
    เดียวกันเป๊ะได้ ดูคำอธิบาย pv_rows/loan_rows ที่ build_outstanding_text())"""
    text = build_outstanding_text(
        customer_name, outstanding_amount, pending_qty, items,
        cod_transferred=cod_transferred, pv_rows=pv_rows, loan_rows=loan_rows,
    )
    return _push(line_user_id, text, group_id)


# ─── ปุ่มส่งสรุปแยกหัวข้อ (เพิ่ม 2026-11-07) ──────────────────────────────
# user: "ถ้าจะสรุปยอดแค่ ส่วนที่ยังไม่เปิดบิล หรือ ยืมคะแนน คงเหลือ เท่าไหร่ ยังไม่มี
# ตรงไหนกดส่งให้ลูกค้าได้ ตอนนี้กดที ส่งไปยาวเหยียด งง ไปหมด" — push_outstanding เดิม
# (ด้านบน) มัดรวม ค้างจ่าย+ค้างรับ+PV+COD เข้าข้อความเดียวจนยาว ตอบคำถามเดียวของลูกค้า
# ("ของค้างอยู่กี่ชิ้น" / "ยืมคะแนนเหลือเท่าไหร่") ได้ยาก ฟังก์ชันด้านล่างแยกส่งเฉพาะ
# หัวข้อเดียวตามที่ถูกถาม ใช้คู่กับปุ่มใน 👤 บัตรลูกค้า (bill_detail_ui.py)


def push_pending_receipt(line_user_id: str, customer_name: str, items: list, group_id: str = "") -> dict:
    """ค้างรับของอย่างเดียว — items: [{"bill_no","product","qty"}] (qty = ค้างรับ คือ
    จำนวนที่ยังไม่ได้เอาไปจริงๆ ต่อรายการ ไม่ใช่จำนวนที่สั่งทั้งหมด — ตรงตามที่ user ขอ
    "อยากให้แสดงว่า สินค้ารายการนั้น คงเหลือเท่าไหร่ที่ยังไม่ได้เอาไป")"""
    lines = [f"คุณ {customer_name} มีสินค้าค้างรับดังนี้ค่ะ 🙏", ""]
    total_qty = 0
    for it in items:
        qty = int(it.get("qty") or 0)
        if qty <= 0:
            continue
        total_qty += qty
        lines.append(f"📦 {it.get('product','')} — ค้างรับ {qty:,} ชิ้น (บิล {it.get('bill_no','')})")
    lines.append("")
    lines.append(f"รวมค้างรับทั้งหมด: {total_qty:,} ชิ้น")
    return _push(line_user_id, "\n".join(lines), group_id)


def push_pending_payment(line_user_id: str, customer_name: str, items: list, group_id: str = "") -> dict:
    """ค้างจ่ายอย่างเดียว — items: [{"bill_no","product","amount"}] (ไม่รวมรายการ COD —
    เก็บเงินตอนส่งของ ไม่ใช่ยอดค้างแบบนี้ เหมือน push_outstanding เดิม)"""
    lines = [f"คุณ {customer_name} มียอดค้างจ่ายดังนี้ค่ะ 🙏", ""]
    total_amt = 0.0
    for it in items:
        amt = float(it.get("amount") or 0)
        if amt <= 0:
            continue
        total_amt += amt
        lines.append(f"💰 บิล {it.get('bill_no','')}: {it.get('product','')} {amt:,.0f}฿")
    lines.append("")
    lines.append(f"รวมค้างจ่ายทั้งหมด: {total_amt:,.0f} บาท")
    return _push(line_user_id, "\n".join(lines), group_id)


def push_unbilled_pv(line_user_id: str, customer_name: str, pv_rows: list, group_id: str = "") -> dict:
    """คะแนนรอเปิดบิลอย่างเดียว — pv_rows จาก ui_helpers.unbilled_pv_breakdown_rows() ตรงๆ
    เหมือนที่ push_outstanding ใช้ (รูปแบบ `_fmt_pv_lines` เดียวกัน ข้อความตรงกันเป๊ะ)"""
    lines = [f"คุณ {customer_name} มีคะแนนรอเปิดบิลดังนี้ค่ะ 🙏", ""]
    pv_lines, grand = _fmt_pv_lines(pv_rows)
    lines.extend(pv_lines)
    lines.append(f"⭐ รวมคะแนนที่ยังไม่ได้เปิดบิลทั้งหมด: {grand:,.0f} คะแนน")
    return _push(line_user_id, "\n".join(lines), group_id)


def push_pv_loan_status(line_user_id: str, customer_name: str, loans: list, group_id: str = "") -> dict:
    """ยืมคะแนนคงเหลืออย่างเดียว — loans ต้องกรองเหลือเฉพาะที่ยังไม่ settle แล้วจากฝั่งเรียก
    (`db.get_pv_loans_df()` filtered เหมือนปุ่มอื่นๆ ที่เกี่ยวกับ PV loan)"""
    if not loans:
        return _push(line_user_id, f"คุณ {customer_name} ไม่มียืมคะแนนค้างคืนแล้วค่ะ 🎉", group_id)
    lines = [f"คุณ {customer_name} มียืมคะแนนค้างคืนดังนี้ค่ะ 🙏", ""]
    loan_lines, grand = _fmt_loan_lines(loans)
    lines.extend(loan_lines)
    lines.append(f"💳 รวมค้างคืนทั้งหมด: {grand:,.0f} PV")
    return _push(line_user_id, "\n".join(lines), group_id)


def push_pv_loan_repayments(line_user_id: str, customer_name: str, repayments: list, group_id: str = "") -> dict:
    """ประวัติคืนคะแนนอย่างเดียว — repayments: [{"repay_date","repay_bill_no","pv_repaid",
    "lend_date"}] ข้ามทุกก้อนที่เคยยืมของลูกค้าคนนี้ (ไม่ใช่แค่ก้อนเดียว) เรียงใหม่สุดก่อน"""
    if not repayments:
        return _push(line_user_id, f"คุณ {customer_name} ยังไม่มีประวัติคืนคะแนนเลยค่ะ", group_id)
    lines = [f"คุณ {customer_name} มีประวัติคืนคะแนนดังนี้ค่ะ", ""]
    total = 0.0
    _max = 20
    for rp in repayments[:_max]:
        pv = float(rp.get("pv_repaid") or 0)
        total += pv
        lines.append(
            f"💰 {rp.get('repay_date','')} บิล {rp.get('repay_bill_no','')}: "
            f"คืน {pv:,.0f} PV (จากยืม {rp.get('lend_date','')})"
        )
    if len(repayments) > _max:
        lines.append(f"...และอีก {len(repayments) - _max} รายการ")
        total = sum(float(r.get("pv_repaid") or 0) for r in repayments)
    lines.append(f"รวมคืนแล้วทั้งหมด: {total:,.0f} PV")
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
    """ส่งสรุปบิลให้ลูกค้าใน LINE — items[i]["remaining"] (ถ้ามี) คือจำนวนที่ยัง
    ไม่ได้รับจริงต่อรายการ (ค้างรับ) แยกจาก qty (จำนวนที่สั่งทั้งหมด) ใส่ต่อท้ายบรรทัด
    เมื่อ > 0 ไม่งั้นข้อความนี้จะดูเหมือนบิลปิดครบแล้วทั้งที่ยังมีของค้างส่งมอบอยู่
    (user report 2026-11-08: ใช้ตอนลูกค้ามารับของเก่า แต่สรุปไม่บอกว่าค้างรับเท่าไหร่)"""
    lines = [f"📋 สรุปบิล {bill_no}", f"คุณ {customer_name}", ""]
    total_remaining = 0
    for it in items[:10]:
        remaining = int(it.get("remaining") or 0)
        line = f"• {it['name']} ×{it['qty']} = {float(it['total']):,.0f}฿"
        if remaining > 0:
            total_remaining += remaining
            line += f" (ค้างรับ {remaining:,} ชิ้น)"
        lines.append(line)
    lines += ["", f"💰 รวม: {total_amount:,.0f} บาท"]
    if paid_amount is not None and outstanding_amount is not None and outstanding_amount > 0.01:
        lines.append(f"✅ จ่ายแล้ว: {paid_amount:,.0f} บาท")
        lines.append(f"⏳ ค้างจ่าย: {outstanding_amount:,.0f} บาท")
    else:
        lines.append(f"สถานะ: {pay_status}")
    if total_remaining > 0:
        lines.append(f"📦 รวมค้างรับ: {total_remaining:,} ชิ้น")
    return _push(line_user_id, "\n".join(lines), group_id)
