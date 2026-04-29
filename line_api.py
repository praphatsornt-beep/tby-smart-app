import os
import requests
import streamlit as st

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


def _token() -> str:
    return os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") or st.secrets.get("LINE_CHANNEL_ACCESS_TOKEN", "")


def is_configured() -> bool:
    return bool(_token())


def push_tracking(line_user_id: str, dst_name: str, tracking: str,
                  carrier: str, cod: float = 0) -> dict:
    """ส่งข้อความแจ้ง tracking ให้ลูกค้าใน LINE"""
    token = _token()
    if not token:
        return {"ok": False, "error": "ไม่มี LINE_CHANNEL_ACCESS_TOKEN ใน secrets"}
    if not line_user_id:
        return {"ok": False, "error": "ไม่มี line_user_id"}

    lines = [
        f"ส่งของให้คุณ {dst_name} แล้วนะคะ 📦",
        f"ขนส่ง: {carrier}",
        f"เลขพัสดุ: {tracking}",
        f"ติดตาม: https://app.iship.cloud/tracking?track={tracking}",
    ]
    if cod > 0:
        lines.append(f"เก็บเงินปลายทาง: {int(cod):,} บาท")

    body = {
        "to": line_user_id,
        "messages": [{"type": "text", "text": "\n".join(lines)}],
    }
    try:
        r = requests.post(
            LINE_PUSH_URL,
            json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            timeout=10,
        )
        if r.status_code == 200:
            return {"ok": True}
        return {"ok": False, "error": f"LINE API HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def push_outstanding(line_user_id: str, customer_name: str,
                     outstanding_amount: float, pending_qty: int,
                     items: list) -> dict:
    """ส่งสรุปยอดค้างให้ลูกค้าใน LINE
    items = [{"bill_no": str, "product": str, "amount": float, "qty": int}]
    """
    token = _token()
    if not token:
        return {"ok": False, "error": "ไม่มี LINE_CHANNEL_ACCESS_TOKEN ใน secrets"}
    if not line_user_id:
        return {"ok": False, "error": "ไม่มี line_user_id"}

    lines = [f"คุณ {customer_name} มียอดค้างดังนี้ค่ะ 🙏"]
    if outstanding_amount > 0:
        lines.append(f"💰 ค้างจ่าย: {outstanding_amount:,.0f} บาท")
    if pending_qty > 0:
        lines.append(f"📦 ค้างรับ: {pending_qty} ชิ้น")
    if items:
        lines.append("")
        for it in items[:8]:
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

    body = {
        "to": line_user_id,
        "messages": [{"type": "text", "text": "\n".join(lines)}],
    }
    try:
        r = requests.post(
            LINE_PUSH_URL, json=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=10,
        )
        if r.status_code == 200:
            return {"ok": True}
        return {"ok": False, "error": f"LINE API HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
