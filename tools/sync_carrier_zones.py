"""
รัน: uv run tools/sync_carrier_zones.py
หรือ: python tools/sync_carrier_zones.py

Push โซนพื้นที่พิเศษ/ห่างไกลจาก flash_zones.py (source of truth) เข้าตาราง
carrier_zones ใน Supabase — ให้ gas_line_webhook.js query สดๆ แทนการ hardcode
ลิสต์แยกต่างหาก (root cause ของบั๊ก drift เดิม 2026-07-12)

รันสคริปต์นี้ทุกครั้งที่แก้ FLASH_ZONES/SPX_REMOTE/THAI_POST_SPECIAL/DHL_REMOTE/
KEX_BULKY_REMOTE ใน flash_zones.py — ไม่งั้น gas_line_webhook.js จะเห็นข้อมูลเก่า
ต้องรัน shipping_zones_reference.sql (สร้างตาราง carrier_zones) ใน Supabase ก่อนครั้งแรก
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

import database as db
import flash_zones as fz

rows = []
for pc, zt in fz.FLASH_ZONES.items():
    rows.append({"carrier": "flash", "postcode": pc, "zone_type": zt})
for pc in fz.SPX_REMOTE:
    rows.append({"carrier": "spx", "postcode": pc, "zone_type": "remote"})
for pc in fz.THAI_POST_SPECIAL:
    rows.append({"carrier": "thai_post", "postcode": pc, "zone_type": "special"})
for pc in fz.DHL_REMOTE:
    rows.append({"carrier": "dhl", "postcode": pc, "zone_type": "remote"})
for pc in fz.KEX_BULKY_REMOTE:
    rows.append({"carrier": "kex_bulky", "postcode": pc, "zone_type": "remote"})

print(f"กำลัง sync {len(rows)} แถวจาก flash_zones.py เข้า carrier_zones...")
n = db.sync_carrier_zones(rows)
print(f"✅ sync แล้ว {n} แถว")
