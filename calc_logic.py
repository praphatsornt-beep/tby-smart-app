"""Pure calculation helpers shared by the คำนวณยอด tab and LINE OA order parsing."""
import random
import re
from math import ceil


_CUSTOMER_TYPO_RE = re.compile(
    r"([A-Za-z](?:\s?[A-Za-z]){0,3})\s*[-.]{0,2}\s*(\d{4})(?:\s*[-.=]{1,2}\s*|\s+)(\d+(?:\.\d+)?)"
)


def _normalize_customer_codes(text: str) -> str:
    """ลูกค้าพิมพ์รหัสสินค้าเองมักไม่ตรงรูปแบบ CODE-QTY มาตรฐาน — เจอจริงเช่น
    'Ty -2010=1' (เว้นวรรค+ขีดนำหน้าตัวเลข), 'TF--2581=1' (ขีดคู่ + ใช้ '=' คั่นจำนวนแทน '-'),
    'TU..2315.2'/'TU.3601.1' (จุดแทนขีด ทั้งคั่นหน้าเลขและคั่นจำนวน บางทีจุดคู่),
    'TF2581 2' (เว้นวรรคเฉยๆ ไม่มีสัญลักษณ์เลย ทั้งหน้าเลขและหน้าจำนวน),
    'T F 2581 . 1' (เว้นวรรคแทรกกลางตัวอักษรนำหน้าด้วย — เจอจริง 2026-08-29 ทำให้
    parse เพี้ยนเป็น 'F2581' ที่ไม่มีในระบบ แล้วบอทเงียบไม่ตอบอะไรเลย) — normalize เป็น
    'TY2010-1'/'TF2581-1'/'TU2315-2'/'TU3601-1'/'TF2581-2' (รูปแบบมาตรฐาน) ก่อนเข้า
    tokenizer ปกติเสมอ เพราะรหัสสินค้าจริงในระบบเป็น LETTERS+4DIGITS ล้วน ไม่มีขีด/จุด/
    เว้นวรรคคั่นเอง (ตรวจสอบแล้วครบ 98/98 ตัวในระบบ 2026-08-28) — จำกัดตัวเลข 4 หลักเป๊ะ
    กันชนกับรหัสไปรษณีย์ 5 หลักใน SH-kgXXXXX และเบอร์โทรลูกค้า (ไม่มีตัวอักษรนำหน้า)
    โดยไม่ตั้งใจ — ตัวคั่นก่อนจำนวน (group 3) ยอมรับทั้ง .-= อย่างน้อย 1 ตัว หรือเว้นวรรค
    ล้วนๆ ก็ได้ (ไม่บังคับต้องมีสัญลักษณ์) ตัวอักษรนำหน้า (group 1) เว้นวรรคคั่นแต่ละตัวได้
    เช่นกัน (สูงสุด 4 ตัว) แล้วเอาช่องว่างออกก่อนต่อกลับเป็นรหัส"""
    return _CUSTOMER_TYPO_RE.sub(
        lambda m: f"{m.group(1).replace(' ', '')}{m.group(2)}-{m.group(3)}", text
    )


def parse_calc_order(text: str, products: list) -> dict:
    """แปลงข้อความรหัสสินค้าแบบ LINE OA เป็นรายการสินค้า/รหัสไปรษณีย์/COD

    ตัวอย่าง: "TF2581-2 RB2306-1 SH-kg 12170 COD"
    รองรับทั้ง "SH-kg12170" (ติดกัน) และ "SH-kg 12170" (เว้นวรรค)
    ก่อน tokenize จะ normalize รูปแบบที่ลูกค้าพิมพ์เพี้ยนบ่อยๆ ก่อนเสมอ (ดู
    _normalize_customer_codes) เช่น "Ty -2010=1"/"TF--2581=1"/"TU..2315.2" →
    "TY2010-1"/"TF2581-1"/"TU2315-2"
    """
    text = _normalize_customer_codes(text)
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
                    errors.append(f"ค่าส่งไม่ถูกต้อง: {token}")
        elif not any(c.isalpha() for c in code):
            # รหัสสินค้าจริงเป็น LETTERS+4DIGITS เสมอ (ไม่มีตัวอักษรเลยไม่ใช่รหัสสินค้าแน่ๆ)
            # — token แบบนี้เจอจริงตอนลูกค้า/พนักงานพิมพ์เลขคำนวณเอง เช่น "3900-5.5=21450"
            # (ราคา-จำนวน=ยอดรวม) ซึ่งบังเอิญมีขีดคั่นเหมือนรูปแบบ CODE-QTY พอดี ข้ามเงียบๆ
            # แทนที่จะ error "ไม่พบรหัส 3900" หรือ "จำนวนไม่ถูกต้อง" ให้งงเปล่าๆ
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
                errors.append(f"จำนวนไม่ถูกต้อง: {token}")
        i += 1
    return {"items": items, "ship_zip": ship_zip,
            "manual_ship": manual_ship, "is_cod": is_cod, "errors": errors}


def _parse_target_list(raw: str) -> list[int]:
    """แกะ '2500 2500 1000' (หรือลัด '2500*2 1000' = เป้าหมาย 2500 สองบิล บวก 1000
    อีกหนึ่งบิล) เป็นลิสต์เป้าหมาย PV เรียงมากไปน้อย — ตัวช่วยกลางที่ parse_plan_targets()/
    parse_plan_target_list() เรียกใช้ร่วมกัน"""
    targets: list[int] = []
    for p in raw.strip().split():
        bits = p.split("*")
        try:
            target_pv = int(bits[0])
            count = int(bits[1]) if len(bits) > 1 else 1
        except ValueError:
            continue
        targets.extend([target_pv] * count)
    targets.sort(reverse=True)
    return targets


def parse_plan_targets(text: str) -> list[int]:
    """แกะ token 'plan 2500 2500 1000' (หรือลัด 'plan 2500*2 1000') จากข้อความสั่งของแบบ
    LINE OA เป็นลิสต์เป้าหมาย PV เรียงมากไปน้อย — พอร์ตมาจาก gas_line_webhook.js
    (planMatches) ให้ LINE OA กับ Streamlit ใช้กติกาเดียวกัน"""
    m = re.search(r"plan\s+([\d*\s]+)", text.lower())
    return _parse_target_list(m.group(1)) if m else []


def parse_plan_target_list(text: str) -> list[int]:
    """เหมือน parse_plan_targets() แต่ไม่ต้องมีคำว่า 'plan' นำหน้า — ใช้กับช่องกรอกแผน
    คะแนนแยกต่างหากใน UI (ผู้ใช้พิมพ์แค่ '2500 2500 1000' ตรงๆ ไม่ต้องพิมพ์เป็นโค้ดปนกับ
    รหัสสินค้า)"""
    return _parse_target_list(text)


def split_bills_by_pv(items: list, targets: list[int], tolerance: int = 25,
                       attempts: int = 1000, rng: random.Random | None = None) -> dict:
    """แบ่งสินค้าที่สั่ง (แต่ละชิ้นแยกจากกัน ไม่ใช่ทั้งบรรทัด) ออกเป็นหลายบิลย่อยตาม
    targets (เรียงมากไปน้อย) โดยแต่ละบิลพยายามให้ยอด PV ใกล้เคียง target ที่สุด (ไม่เกิน
    target+tolerance) — สุ่มลำดับสินค้าแล้วหยิบใส่บิลแบบ greedy ซ้ำ attempts ครั้ง เลือก
    ผลลัพธ์ที่ยอด PV ใกล้ target ที่สุดในแต่ละรอบ (พอร์ตจาก gas_line_webhook.js's 'plan'
    keyword ทุกประการ รวมพฤติกรรมสุ่ม — ผลลัพธ์จึงไม่ deterministic ข้ามการเรียกเว้นแต่จะ
    ส่ง rng ที่ seed ไว้)

    คืน {"bills": [{"target": int, "items": {code: qty}, "pv": float}, ...],
         "remaining": {"items": {code: qty}, "pv": float}}
    """
    rng = rng or random
    stock_pool = []
    for it in items:
        p = it["product"]
        code = p["id"].upper()
        pv = float(p.get("points_per_unit", 0))
        for _ in range(int(it["qty"])):
            stock_pool.append({"code": code, "pv": pv})

    bills = []
    for target in targets:
        if not stock_pool:
            break
        best_sum, best_indices, min_diff = 0.0, [], float("inf")
        for _ in range(attempts):
            temp_sum, temp_indices = 0.0, []
            order = list(range(len(stock_pool)))
            rng.shuffle(order)
            for idx in order:
                pv = stock_pool[idx]["pv"]
                if temp_sum + pv <= target + tolerance:
                    temp_sum += pv
                    temp_indices.append(idx)
                    diff = abs(target - temp_sum)
                    if diff < min_diff:
                        min_diff = diff
                        best_sum = temp_sum
                        best_indices = temp_indices.copy()
                    if temp_sum >= target:
                        break
        if best_indices:
            bill_items: dict = {}
            for idx in sorted(best_indices, reverse=True):
                itm = stock_pool.pop(idx)
                bill_items[itm["code"]] = bill_items.get(itm["code"], 0) + 1
            bills.append({"target": target, "items": bill_items, "pv": best_sum})

    remaining_items: dict = {}
    remaining_pv = 0.0
    for itm in stock_pool:
        remaining_items[itm["code"]] = remaining_items.get(itm["code"], 0) + 1
        remaining_pv += itm["pv"]

    return {"bills": bills, "remaining": {"items": remaining_items, "pv": remaining_pv}}


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


def pack_boxes_grouped(items: list, max_kg: float, even_distribute: bool = False) -> list:
    """จัดกล่องแบบเก็บสินค้าเดียวกันไว้ด้วยกันก่อน — เหมาะกับขนส่งที่คิดราคาเป็นช่วงน้ำหนัก
    (เช่น Inter, J&T) ที่อยากลดการปนสินค้าหลายชนิดในกล่องเดียวโดยไม่จำเป็น

    แบ่งแต่ละสินค้าเป็น "ก้อน" (chunk) ตาม max_units_per_box (จำนวนชิ้นสูงสุดต่อกล่องทางกายภาพ
    ถ้าตั้งไว้) หรือน้ำหนักกล่อง max_kg แล้วแต่ค่าไหนถึงก่อน (กันไม่ให้เกินน้ำหนักเสมอ)

    even_distribute=False (ค่าเริ่มต้น): อัดเต็ม cap ทุกก้อน เหลือเศษไว้ก้อนสุดท้ายก้อนเดียว —
    บางครั้งก้อนเศษที่เบากว่าจะหลุดไปอยู่ช่วงราคาที่ถูกกว่าได้
    even_distribute=True: กระจายจำนวนให้เท่าๆ กันในทุกก้อน ทำให้ทุกก้อนมีที่ว่างเหลือใกล้เคียงกัน
    ช่วยให้จับคู่รวมกับสินค้าอื่นได้ทั่วถึงกว่า (แต่บางครั้งก้อนที่กระจายเท่าๆ กันอาจหนักพอที่จะ
    ตกช่วงราคาแพงกว่าทั้งหมด) — สองแบบนี้ไม่มีใครดีกว่าเสมอ ผู้เรียกควรลองทั้งคู่แล้วเทียบราคาเอา
    (ดู carriers.plan_boxes() ที่ลองทั้งสองแบบให้ทุกจุดตัดราคาอยู่แล้ว)

    ไม่ว่าโหมดไหน ก้อนทั้งหมดจากทุกสินค้าจะเอามาทำ First-Fit Decreasing ตามน้ำหนักก้อนรวมกัน —
    ก้อนของสินค้าเดียวกันจะไม่ยัดรวมกล่องเดียวกันเอง (คงข้อจำกัดต่อกล่องไว้เสมอ) แต่ก้อนจากสินค้า
    คนละตัวที่มีน้ำหนักเหลือพอ จะถูกจับรวมกล่องเดียวกันได้ ไม่ปล่อยให้กล่องน้ำหนักน้อยค้างเดี่ยวๆ

    Returns list of boxes [{weight_kg, items:{code:qty}}] — shape เดียวกับ pack_boxes()
    """
    by_code: dict = {}
    for it in items:
        p    = it["product"]
        code = p["id"].upper()
        w    = p.get("weight_grams", 0) / 1000
        max_units = p.get("max_units_per_box") or None
        entry = by_code.setdefault(code, {"weight": w, "max_units": max_units, "qty": 0})
        entry["qty"] += int(it["qty"])

    chunks: list[tuple] = []  # (code, qty_in_chunk, weight_kg)
    for code, info in by_code.items():
        w, max_units, qty = info["weight"], info["max_units"], info["qty"]
        if qty <= 0:
            continue
        weight_cap = int(max_kg / w) if w > 0 else qty
        cap = min(max_units, weight_cap) if max_units else weight_cap
        cap = max(1, min(cap, qty))
        if even_distribute:
            n_boxes = -(-qty // cap)  # ceil division
            base, extra = divmod(qty, n_boxes)
            for i in range(n_boxes):
                take = base + (1 if i < extra else 0)
                chunks.append((code, take, round(take * w, 6)))
        else:
            remaining = qty
            while remaining > 0:
                take = min(cap, remaining)
                chunks.append((code, take, round(take * w, 6)))
                remaining -= take

    chunks.sort(key=lambda c: -c[2])
    boxes: list[dict] = []
    for code, qty, weight in chunks:
        placed = False
        for box in boxes:
            if code in box["items"]:
                continue  # ไม่ยัดสินค้าเดียวกันซ้ำกล่องที่มีอยู่แล้ว (คงข้อจำกัดต่อกล่องไว้)
            if box["weight_kg"] + weight <= max_kg + 1e-9:
                box["weight_kg"] += weight
                box["items"][code] = box["items"].get(code, 0) + qty
                placed = True
                break
        if not placed:
            boxes.append({"weight_kg": weight, "items": {code: qty}})
    return boxes
