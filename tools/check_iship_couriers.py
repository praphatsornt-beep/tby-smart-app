"""
รัน: uv run tools/check_iship_couriers.py
หรือ: python tools/check_iship_couriers.py

ดึง courier options ทั้งหมดจากหน้าสร้างออเดอร์ของ iShip
"""
import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

import iship_api

sess, msg = iship_api._web_session()
if not sess:
    print(f"Login ไม่สำเร็จ: {msg}")
    sys.exit(1)

print(f"✅ {msg}\n")

r = sess.get("https://app.iship.cloud/shipment/create", timeout=15)
html = r.text

# หา <option value="...">ชื่อขนส่ง</option> ใน courier select
options = re.findall(r'<option[^>]+value="([^"]*)"[^>]*>\s*([^<]+)\s*</option>', html)
print("=== Courier options จาก <select> ===")
for val, label in options:
    if val and label.strip():
        print(f'  "{label.strip()}": "{val}"')

# หา radio buttons หรือ data-courier
radios = re.findall(r'data-courier[_-]?code["\s]*[:=]["\s]*([A-Za-z0-9_]+)', html)
if radios:
    print("\n=== data-courier-code ===")
    for r_ in set(radios):
        print(f"  {r_}")

# หา courier_code ใน JSON / JS
js_codes = re.findall(r'courier_code["\s]*:["\s]*([A-Za-z0-9_]+)', html)
if js_codes:
    print("\n=== courier_code ใน JS/JSON ===")
    for c in set(js_codes):
        print(f"  {c}")

# dump html ไว้ดูเอง
with open("iship_create_page.html", "w", encoding="utf-8") as f:
    f.write(html)
print("\n📄 บันทึก iship_create_page.html แล้ว (เปิดใน browser ดูเพิ่มเติมได้)")
