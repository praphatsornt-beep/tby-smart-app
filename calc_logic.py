"""Pure calculation helpers shared by the คำนวณยอด tab and LINE OA order parsing."""
from math import ceil


def parse_calc_order(text: str, products: list) -> dict:
    """แปลงข้อความรหัสสินค้าแบบ LINE OA เป็นรายการสินค้า/รหัสไปรษณีย์/COD

    ตัวอย่าง: "TF2581-2 RB2306-1 SH-kg 12170 COD"
    รองรับทั้ง "SH-kg12170" (ติดกัน) และ "SH-kg 12170" (เว้นวรรค)
    """
    product_map = {p["id"].upper(): p for p in products}
    tokens = text.strip().upper().split()
    items, ship_zip, manual_ship, is_cod, errors = [], "", -1, False, []
    n = len(tokens)
    i = 0
    while i < n:
        token = tokens[i]
        if token == "COD":
            is_cod = True
            i += 1
            continue
        if "-" not in token:
            i += 1
            continue
        parts = token.split("-", 1)
        code, val = parts[0], parts[1]
        if code == "SH":
            if val.startswith("KG"):
                z = val[2:]
                if len(z) != 5 and i + 1 < n and tokens[i + 1].isdigit() and len(tokens[i + 1]) == 5:
                    # รองรับ "SH-KG 12170" (เว้นวรรค) เช่นเดียวกับ "SH-KG12170"
                    z = tokens[i + 1]
                    i += 1
                if len(z) == 5:
                    ship_zip = z
            else:
                try:
                    manual_ship = float(val)
                except Exception:
                    pass
        else:
            try:
                qty = float(val)
                if qty > 0:
                    if code in product_map:
                        items.append({"product": product_map[code], "qty": qty})
                    else:
                        errors.append(f"ไม่พบรหัส {code}")
            except Exception:
                pass
        i += 1
    return {"items": items, "ship_zip": ship_zip,
            "manual_ship": manual_ship, "is_cod": is_cod, "errors": errors}


def cod_fee(amount: float, pct: float = 0.0321) -> int:
    """ค่าธรรมเนียม COD = ceil((ยอดสินค้า + ค่าส่ง) * 3.21%)"""
    return ceil(amount * pct)


def pack_boxes(items: list, max_kg: float) -> list:
    """First-Fit Decreasing bin packing. Returns list of boxes [{weight_kg, items:{code:qty}}]"""
    units = []
    for it in items:
        w = it["product"].get("weight_grams", 0) / 1000
        code = it["product"]["id"].upper()
        for _ in range(int(it["qty"])):
            units.append((code, w))
    units.sort(key=lambda x: -x[1])
    boxes: list[dict] = []
    for code, w in units:
        placed = False
        for box in boxes:
            if box["weight_kg"] + w <= max_kg + 1e-9:
                box["weight_kg"] += w
                box["items"][code] = box["items"].get(code, 0) + 1
                placed = True
                break
        if not placed:
            boxes.append({"weight_kg": w, "items": {code: 1}})
    return boxes
