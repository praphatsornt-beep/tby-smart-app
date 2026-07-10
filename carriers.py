"""Carrier rate cards and multi-carrier shipping comparison."""
from math import ceil
from flash_zones import lookup_zone, zone_surcharge_by_weight, spx_surcharge, thai_post_special_surcharge, dhl_remote_surcharge
import calc_logic

# ── Bangkok zone detection ────────────────────────────────────────────────────
_BKK_SET = {str(i).zfill(5) for i in range(10000, 11000)}  # กรุงเทพฯ + สมุทรปราการ
_BKK_SET |= {str(i).zfill(5) for i in range(11000, 11200)}  # นนทบุรี
_BKK_SET |= {str(i).zfill(5) for i in range(12000, 12200)}  # ปทุมธานี

def _is_bkk(pc: str) -> bool:
    return str(pc).strip() in _BKK_SET


# ── Rate tables: {ceil_weight_kg: (bkk, province)} or {int: flat} ────────────

_FLASH_THUNDER = {
    1:(19,22),2:(24,26),3:(29,31),4:(48,58),5:(57,68),6:(67,79),7:(76,89),
    8:(90,104),9:(105,115),10:(122,134),11:(137,156),12:(152,167),13:(167,178),
    14:(182,189),15:(198,200),16:(213,217),17:(227,228),18:(242,240),
    19:(257,250),20:(272,262),21:(282,283),22:(293,294),23:(302,305),
    24:(313,316),25:(322,328),26:(333,338),27:(343,350),28:(352,360),
    29:(363,372),30:(378,383),31:(393,416),32:(408,427),33:(423,438),
    34:(439,449),35:(453,460),36:(468,471),37:(483,481),38:(498,493),
    39:(513,504),40:(528,515),41:(543,560),42:(558,570),43:(574,581),
    44:(589,593),45:(603,603),46:(619,615),47:(634,625),48:(649,637),
    49:(665,648),50:(679,659),
}

_SPX = {
    1:(17,28),2:(21,33),3:(24,35),4:(36,36),5:(44,39),6:(50,44),7:(55,50),
    8:(66,61),9:(77,72),10:(88,83),11:(99,94),12:(110,105),13:(121,110),
    14:(132,121),15:(143,132),16:(154,143),17:(165,154),18:(176,160),
    19:(187,171),20:(198,182),
}

_FLASH_PRO_DD = {
    1:(23,44),2:(27,50),3:(32,61),4:(48,68),5:(57,78),6:(67,89),7:(76,99),
    8:(90,114),9:(105,125),10:(122,144),11:(137,166),12:(152,177),
    13:(167,188),14:(182,199),15:(198,210),16:(213,227),17:(227,238),
    18:(242,250),19:(257,260),20:(272,272),21:(282,293),22:(293,304),
    23:(302,315),24:(313,326),25:(322,338),26:(333,348),27:(343,360),
    28:(352,370),29:(363,382),30:(378,393),31:(393,426),32:(408,437),
    33:(423,448),34:(439,459),35:(453,470),36:(468,481),37:(483,491),
    38:(498,503),39:(513,514),40:(528,525),41:(543,570),42:(558,580),
    43:(574,591),44:(589,603),45:(603,613),46:(619,625),47:(634,635),
    48:(649,647),49:(665,658),50:(679,669),
}

_FLASH_PRO_DD_BULKY = {  # flat rate everywhere
    1:50,2:50,3:50,4:50,5:50,6:50,7:58,8:66,9:74,10:82,11:90,12:98,
    13:106,14:114,15:122,16:130,17:138,18:146,19:154,20:162,21:170,
    22:178,23:186,24:194,25:202,26:210,27:218,28:226,29:234,30:242,
    31:250,32:258,33:266,34:274,35:282,36:290,37:298,38:306,39:314,
    40:322,41:330,42:338,43:346,44:354,45:362,46:370,47:378,48:386,
    49:394,50:402,51:410,52:418,53:426,54:434,55:442,56:450,57:458,
    58:466,59:474,60:482,61:490,62:498,63:506,64:514,65:522,66:530,
    67:538,68:546,69:554,70:562,71:570,72:578,73:586,74:594,75:602,
    76:610,77:618,78:626,79:634,80:642,81:650,82:658,83:666,84:674,
    85:682,86:690,87:698,88:706,89:714,90:722,91:730,92:738,93:746,
    94:754,95:762,96:770,97:778,98:786,99:794,100:802,
}

_KEX = {
    1:(25,25),2:(30,35),3:(35,40),4:(45,50),5:(60,65),6:(70,75),7:(75,85),
    8:(86,95),9:(98,105),10:(106,115),11:(119,128),12:(133,141),13:(145,153),
    14:(158,167),15:(171,180),16:(188,197),17:(205,214),18:(222,232),
    19:(240,249),20:(257,266),21:(271,280),22:(285,294),23:(298,308),
    24:(312,321),25:(326,335),26:(340,349),27:(354,363),28:(367,377),
    29:(381,390),30:(395,404),
}

_KEX_BULKY = {  # flat rate everywhere, min 30kg use
    1:255,2:255,3:255,4:255,5:255,6:255,7:255,8:255,9:255,10:255,
    11:255,12:255,13:255,14:255,15:255,16:255,17:255,18:255,19:255,
    20:255,21:255,22:255,23:255,24:255,25:255,26:255,27:255,28:255,
    29:255,30:255,31:255,32:262,33:272,34:279,35:287,36:296,37:304,
    38:311,39:321,40:328,41:336,42:345,43:353,44:360,45:370,46:377,
    47:385,48:394,49:402,50:411,51:419,52:426,53:436,54:443,55:451,
    56:460,57:468,58:475,59:485,60:492,
}

_DHL = {
    1:(25,25),2:(30,41),3:(35,45),4:(40,50),5:(45,53),6:(72,93),7:(78,98),
    8:(84,104),9:(90,111),10:(98,122),11:(102,135),12:(110,140),13:(116,147),
    14:(122,156),15:(128,165),16:(147,190),17:(165,196),18:(184,202),
    19:(202,209),20:(221,227),21:(246,251),22:(272,276),23:(296,302),
    24:(321,327),25:(346,351),26:(376,383),27:(407,413),28:(438,444),
    29:(470,476),30:(500,507),31:(536,543),32:(572,579),33:(608,615),
    34:(644,651),35:(680,687),
}

_THAI_POST_EMS = {  # flat everywhere
    1:24,2:34,3:44,4:55,5:65,6:84,7:96,8:108,9:120,10:133,
    11:157,12:170,13:183,14:196,15:209,16:222,17:235,18:248,19:261,20:274,
}

_THAI_POST_EMS_BULKY = {  # flat everywhere
    1:45,2:45,3:45,4:45,5:50,6:55,7:65,8:75,9:110,10:120,
    11:130,12:140,13:150,14:160,15:170,16:180,17:190,18:200,19:210,20:220,
    21:240,22:260,23:280,24:300,25:320,26:340,27:360,28:370,29:380,30:390,
}

_FLASH_PRO_OK = {
    1:(20,22),2:(24,26),3:(29,31),4:(43,48),5:(53,57),6:(67,67),7:(76,76),
    8:(91,91),9:(100,100),10:(117,117),11:(137,137),12:(148,148),13:(157,157),
    14:(168,168),15:(177,177),16:(192,192),17:(203,203),18:(213,213),
    19:(223,223),20:(233,233),21:(253,253),22:(264,264),23:(273,273),
    24:(284,284),25:(294,294),26:(304,304),27:(314,314),28:(323,323),
    29:(334,334),30:(344,344),31:(375,375),32:(384,384),33:(395,395),
    34:(404,404),35:(415,415),36:(430,425),37:(445,435),38:(460,445),
    39:(475,456),40:(491,465),41:(506,506),42:(521,515),43:(536,526),
    44:(551,536),45:(566,546),46:(581,556),47:(596,566),48:(611,576),
    49:(627,587),50:(642,596),
}

_JT_EXPRESS = {  # (กรุงเทพ, ต่างจังหวัด) — ตารางที่ให้มามีถึง 40kg เท่านั้น (จริงรองรับถึง 100kg)
    1:(25,25),2:(29,29),3:(32,32),4:(46,51),5:(57,60),6:(71,71),7:(80,80),
    8:(113,113),9:(125,125),10:(136,136),11:(145,145),12:(156,156),13:(165,165),
    14:(176,176),15:(186,186),16:(202,202),17:(213,213),18:(223,223),19:(234,234),
    20:(242,242),21:(261,261),22:(279,279),23:(297,297),24:(315,315),25:(334,334),
    26:(351,351),27:(370,370),28:(388,388),29:(406,406),30:(424,424),31:(443,443),
    32:(460,460),33:(479,479),34:(497,497),35:(515,515),36:(533,533),37:(552,552),
    38:(569,569),39:(588,588),40:(605,605),
}

_INTER_EXPRESS = {  # เหมาตามขนาดกล่อง (A1/A2/B1/B2) เรทเดียวทั่วประเทศ ไม่รับ COD
    1:110,2:110,3:110,4:110,5:110,6:110,7:110,8:110,9:110,10:110,
    11:110,12:110,13:110,14:110,15:110,   # กล่อง A1 ≤15kg
    16:130,17:130,18:130,19:130,20:130,   # กล่อง A2 ≤20kg
    21:150,22:150,23:150,24:150,25:150,   # กล่อง B1 ≤25kg
    26:170,27:170,28:170,29:170,30:170,   # กล่อง B2 ≤30kg
}

_FLASH_100CM = {
    1:(22,24),2:(26,28),3:(31,33),4:(45,50),5:(55,59),6:(72,72),7:(81,81),
    8:(96,96),9:(105,105),10:(122,122),11:(142,142),12:(153,153),
    13:(162,162),14:(173,173),15:(182,182),16:(197,197),17:(208,208),
    18:(218,218),19:(228,228),20:(238,238),21:(258,258),22:(269,269),
    23:(278,278),24:(289,289),25:(299,299),26:(309,309),27:(319,319),
    28:(328,328),29:(339,339),30:(349,349),31:(380,380),32:(389,389),
    33:(400,400),34:(409,409),35:(420,420),36:(435,430),37:(450,440),
    38:(465,450),39:(480,461),40:(496,470),41:(511,511),42:(526,520),
    43:(541,531),44:(556,541),45:(571,551),46:(586,561),47:(601,571),
    48:(616,581),49:(632,592),50:(647,601),
}


# ── Surcharge helpers ─────────────────────────────────────────────────────────

def _flash_sur(pc: str, kg: float) -> tuple[int, str]:
    zone = lookup_zone(pc)
    sur  = zone_surcharge_by_weight(pc, kg)
    label = {"remote": "ห่างไกล", "tourist": "ท่องเที่ยว",
              "tourist_island": "เกาะ"}.get(zone, "")
    return sur, label

def _flash_pro_dd_sur(pc: str, kg: float) -> tuple[int, str]:
    """Pro DD: ฟรี remote, คิด tourist เหมือนปกติ"""
    zone = lookup_zone(pc)
    if zone == "remote":
        return 0, ""
    return _flash_sur(pc, kg)

def _flash_pro_dd_bulky_sur(pc: str, kg: float) -> tuple[int, str]:
    """Pro DD Bulky: remote weight-tiered, tourist เหมือนปกติ"""
    zone = lookup_zone(pc)
    if zone == "remote":
        if kg <= 50: sur = 50
        elif kg <= 70: sur = 100
        else: sur = 200
        return sur, "ห่างไกล"
    return _flash_sur(pc, kg)

def _spx_sur(pc: str, _kg: float) -> tuple[int, str]:
    sur = spx_surcharge(pc)
    return sur, ("ห่างไกล" if sur else "")

def _kex_bulky_sur(pc: str, _kg: float) -> tuple[int, str]:
    sur = 50 if lookup_zone(pc) == "remote" else 0
    return sur, ("ห่างไกล" if sur else "")

def _dhl_sur(pc: str, _kg: float) -> tuple[int, str]:
    sur = dhl_remote_surcharge(pc)
    return sur, ("ห่างไกล" if sur else "")

def _thai_post_sur(pc: str, _kg: float) -> tuple[int, str]:
    sur = thai_post_special_surcharge(pc)
    return sur, ("เกาะ/พิเศษ" if sur else "")

def _no_sur(_pc: str, _kg: float) -> tuple[int, str]:
    return 0, ""

def _jt_sur(pc: str, kg: float) -> tuple[int, str]:
    """J&T: ห่างไกล 0.1-50kg=50, 50.1-70kg=100, >70kg=200 | ท่องเที่ยว(รวมเกาะ) 0.1-7kg=30, >7kg=100"""
    zone = lookup_zone(pc)
    if zone == "remote":
        if kg <= 50: return 50, "ห่างไกล"
        if kg <= 70: return 100, "ห่างไกล"
        return 200, "ห่างไกล"
    if zone in ("tourist", "tourist_island"):
        sur = 30 if kg <= 7 else 100
        return sur, ("เกาะ" if zone == "tourist_island" else "ท่องเที่ยว")
    return 0, ""


# ── Base price lookup ─────────────────────────────────────────────────────────

def _lookup(table: dict, kg: float, bkk: bool) -> int | None:
    w = max(1, ceil(kg))
    entry = table.get(w)
    if entry is None:
        return None  # exceeds table
    return entry[0] if (isinstance(entry, tuple) and bkk) else (entry[1] if isinstance(entry, tuple) else entry)


# ── Carrier definitions ───────────────────────────────────────────────────────
# (id, display_name, table, max_kg, sur_fn, fuel, cod_pct, return_free, min_kg, max_cm, supports_cod, max_cod_amt)
# max_cm: กว้าง+ยาว+สูง รวมต้องไม่เกินค่านี้ (0 = ไม่จำกัด) | max_cod_amt: วงเงิน COD สูงสุด (0 = ไม่จำกัด)
_CARRIER_DEFS = [
    ("flash_thunder",     "Flash Thunder",      _FLASH_THUNDER,       50,  _flash_sur,              3, 2.14, True,  0,    60, True,  0),
    ("flash_pro_dd",      "Flash Pro DD",       _FLASH_PRO_DD,        50,  _flash_pro_dd_sur,       3, 2.14, True,  0,    60, True,  0),
    ("flash_pro_ok",      "Flash Pro OK",       _FLASH_PRO_OK,        50,  _flash_sur,              3, 2.14, True,  0,    60, True,  0),
    ("flash_100cm",       "Flash 100CM",        _FLASH_100CM,         50,  _flash_sur,              3, 2.14, True,  0,   100, True,  0),
    ("flash_pro_dd_bulky","Flash Pro DD Bulky", _FLASH_PRO_DD_BULKY, 100,  _flash_pro_dd_bulky_sur, 3, 2.14, False, 5.01,  0, True,  0),
    ("spx",               "SPX Express",        _SPX,                 20,  _spx_sur,                2, 3.21, True,  0,     0, True,  0),
    ("kex",               "KEX Express",        _KEX,                 30,  _no_sur,                 3, 2.675,False, 0,     0, True,  0),
    ("kex_bulky",         "KEX Bulky",          _KEX_BULKY,           60,  _kex_bulky_sur,          3, 2.675,False, 0,     0, True,  0),
    ("dhl",               "DHL eCommerce",      _DHL,                 35,  _dhl_sur,                0, 3.21, False, 0,     0, True,  0),
    ("thai_post_ems",     "ไปรษณีย์ EMS",        _THAI_POST_EMS,       20,  _thai_post_sur,          0, 3.21, True,  0,     0, True,  0),
    ("thai_post_bulky",   "ไปรษณีย์ EMS Bulky",  _THAI_POST_EMS_BULKY, 30,  _thai_post_sur,          0, 3.21, True,  0,     0, True,  0),
    ("inter_express",     "Inter Express",      _INTER_EXPRESS,       30,  _no_sur,                 0, 0,    False, 0,     0, False, 0),
    ("jt_express",        "J&T Express",        _JT_EXPRESS,          40,  _jt_sur,                 0, 2.675,False, 0,   600, True,  10000),
]


# ── Main comparison function ──────────────────────────────────────────────────

def _price_one_box(carrier_def: tuple, weight_kg: float, postcode: str,
                    is_cod: bool = False, cod_amount: float = 0) -> dict | None:
    """คิดราคา 1 ขนส่ง (tuple จาก _CARRIER_DEFS) สำหรับน้ำหนัก/รหัสไปรษณีย์ที่กำหนด
    คืน None ถ้าขนส่งนี้ใช้ไม่ได้เลย (ต่ำกว่าขั้นต่ำ, ไม่รับ COD, เกินวงเงิน COD, หรือหาราคาไม่เจอ)
    """
    cid, name, table, max_kg, sur_fn, fuel, cod_pct, return_free, min_kg, max_cm, supports_cod, max_cod_amt = carrier_def
    if weight_kg < min_kg:
        return None  # ไม่แสดงถ้าน้ำหนักต่ำกว่าขั้นต่ำ (เช่น Flash Pro DD Bulky ต้อง >5kg)
    if is_cod and not supports_cod:
        return None  # ขนส่งนี้ไม่รับ COD
    if is_cod and max_cod_amt and cod_amount > max_cod_amt:
        return None  # เกินวงเงิน COD สูงสุดของขนส่งนี้

    pc  = str(postcode).strip()
    bkk = _is_bkk(pc)
    exceeds = weight_kg > max_kg
    lookup_kg = min(weight_kg, max_kg) if exceeds else weight_kg
    base = _lookup(table, lookup_kg, bkk)
    if base is None:
        return None
    sur, sur_label = sur_fn(pc, weight_kg)
    subtotal = base + sur + fuel
    cod_fee = ceil(max(subtotal, cod_amount) * cod_pct / 100) if is_cod else 0
    return {
        "id":            cid,
        "name":          name,
        "base":          base,
        "surcharge":     sur,
        "sur_label":     sur_label,
        "fuel":          fuel,
        "total":         subtotal,
        "cod_fee":       cod_fee,
        "cod_pct":       cod_pct,
        "exceeds_max":   exceeds,
        "max_kg":        max_kg,
        "min_kg":        min_kg,
        "return_free":   return_free,
        "max_cm":        max_cm,
        "max_cod_amt":   max_cod_amt,
    }


def get_shipping_options(weight_kg: float, postcode: str,
                         is_cod: bool = False, cod_amount: float = 0) -> list[dict]:
    """
    คำนวณค่าส่งทุกขนส่งสำหรับน้ำหนักและรหัสไปรษณีย์ที่กำหนด
    คืน list ของ dict เรียงจากถูกไปแพง (เกินน้ำหนักสูงสุดอยู่ท้าย)
    """
    results = []
    for carrier_def in _CARRIER_DEFS:
        r = _price_one_box(carrier_def, weight_kg, postcode, is_cod, cod_amount)
        if r is not None:
            results.append(r)
    results.sort(key=lambda x: (x["exceeds_max"], x["total"]))
    return results


# ── Bracket-aware auto box planning ───────────────────────────────────────────

def _bracket_breakpoints(table: dict, max_kg: int, threshold: int = 8) -> list[int]:
    """คืนน้ำหนัก (kg) ที่เป็นจุดตัดราคาของตารางนี้ (kg สุดท้ายก่อนราคาจะเปลี่ยน)

    ถ้าจุดตัดที่เจอมากกว่า threshold จุด (ราคาไหลลื่นเกือบทุก kg แบบ Flash/J&T ไม่ใช่ราคาเหมา
    เป็นช่วงแบบ Inter) คืน [max_kg] ค่าเดียวพอ เพราะยิ่งแพ็คเต็มยิ่งคุ้มอยู่แล้วสำหรับราคาที่ไหลลื่น
    ไม่มีประโยชน์ที่จะลองหลายจุด
    """
    def _val(w):
        entry = table.get(w)
        if entry is None:
            return None
        return entry[0] if isinstance(entry, tuple) else entry

    points = []
    for w in range(1, int(max_kg) + 1):
        if w == max_kg or _val(w) != _val(w + 1):
            points.append(w)
    if not points or len(points) > threshold:
        return [int(max_kg)]
    return points


def _pack_and_price(items: list, carrier_def: tuple, pack_cap: float, box_weight_kg: float,
                     postcode: str, is_cod: bool, cod_amount: float):
    """แพ็ค + คิดราคาที่ pack_cap หนึ่งค่า ลองทั้ง even_distribute=False/True แล้วคืนแบบที่ถูกกว่า
    (อัดเต็มแล้วเหลือเศษก้อนเดียว บางทีก้อนเบาหลุดไปเรทถูกกว่า — กระจายเท่าๆ กัน บางทีจับคู่กับ
    สินค้าอื่นได้ทั่วถึงกว่า — ไม่มีใครดีกว่าเสมอ เลยต้องลองทั้งคู่)
    คืน (boxes, total_cost, ok) — ok=False ถ้ามีกล่องไหนเกิน max_kg ของขนส่งนี้
    """
    best_result = None
    for even in (False, True):
        boxes = calc_logic.pack_boxes_grouped(items, pack_cap, even_distribute=even)
        if not boxes:
            continue
        total = 0.0
        ok = True
        for box in boxes:
            ship_kg = box["weight_kg"] + box_weight_kg
            priced = _price_one_box(carrier_def, ship_kg, postcode, is_cod, cod_amount)
            if priced is None or priced["exceeds_max"]:
                ok = False
                break
            box["price"] = priced["total"] + priced["cod_fee"]
            total += box["price"]
        if not ok:
            if best_result is None:
                best_result = (boxes, total, False)
            continue
        if best_result is None or not best_result[2] or total < best_result[1]:
            best_result = (boxes, total, True)
    return best_result if best_result is not None else ([], 0.0, False)


def plan_boxes(items: list, postcode: str, is_cod: bool = False, cod_amount: float = 0,
               box_weight_g: int = 500) -> list[dict]:
    """วางแผนกล่องที่คุ้มค่าส่งสุดสำหรับทุกขนส่ง — หาจุดตัดราคาของแต่ละขนส่งเอง (ไม่ต้องตั้งค่าเอง)
    แล้วแพ็คด้วย calc_logic.pack_boxes_grouped() ที่จุดตัดนั้นๆ (เก็บสินค้าเดียวกันไว้ด้วยกันก่อน
    ลองทั้งแบบอัดเต็ม/กระจายเท่าๆ กัน) เลือกจุดตัด+วิธีแพ็คที่รวมค่าส่งถูกสุดต่อขนส่ง

    Returns list เรียงถูกสุดก่อน: [{id, name, boxes, total_cost, ceiling_used, box_count,
    candidates: [{ceiling, total_cost, box_count} ...]}, ...] — candidates คือทุกจุดตัดที่ลอง
    (รวมที่ไม่ได้เลือก) ใช้โชว์เทียบให้เห็นว่าลองครบจริง ไม่ใช่แค่ค่าที่เลือก
    ข้ามขนส่งที่ใช้ไม่ได้เลย (ไม่รับ COD, มีกล่องเกิน max_kg ทุกจุดตัดที่ลอง ฯลฯ)
    """
    box_weight_kg = box_weight_g / 1000
    plans = []

    for carrier_def in _CARRIER_DEFS:
        cid, name, table, max_kg = carrier_def[0], carrier_def[1], carrier_def[2], carrier_def[3]
        best = None
        candidates = []
        for ceiling in _bracket_breakpoints(table, max_kg):
            pack_cap = max(0.1, ceiling - box_weight_kg)
            boxes, total, ok = _pack_and_price(items, carrier_def, pack_cap, box_weight_kg,
                                                postcode, is_cod, cod_amount)
            candidates.append({
                "ceiling": ceiling,
                "total_cost": total if ok else None,
                "box_count": len(boxes) if ok else None,
            })
            if not ok:
                continue
            if best is None or total < best["total_cost"]:
                best = {
                    "id": cid, "name": name, "boxes": boxes,
                    "total_cost": total, "ceiling_used": ceiling, "box_count": len(boxes),
                }
        if best is not None:
            best["candidates"] = candidates
            plans.append(best)

    plans.sort(key=lambda x: x["total_cost"])
    return plans
