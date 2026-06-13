# TODO — TBY SMART APP

## 🟡 ยังค้างอยู่ (refactor/bug)

- [ ] **รวม logic คำนวณยอดต่อบิล** (บัตรลูกค้า vs จัดการบิล) ให้เป็น helper เดียว `_bills_from_df()`
- [ ] **tab พิมพ์บิล — breakdown เก่า/ใหม่/รวม** (ต้อง ALTER TABLE `partial_events` ก่อน)
- [ ] **Bug: แยกที่อยู่อัตโนมัติ** (postcode → ตำบล/อำเภอ) บางเคสไม่เติมให้ (`thai_address.py`, `bangkok_addresses.py`)
- [ ] **iShip COD** — ยังต้องสร้าง manual ใน dashboard (ตัดสินใจว่าจะ integrate หรือแจ้ง user)
- [x] ~~GAS: tourist_island weight tiers + remote postcodes 50270, 55220 ตกหล่น~~ (commit `38a470c`)

## 📋 Wishlist (ยังไม่ตัดสินใจ priority)

- [ ] สรุป PV ค้างเปิดบิลทั้งหมดของลูกค้า
- [ ] เบิกของเก่าค้างรับ/ค้างจ่าย ผ่าน LINE (ส่วน "เก่า"/"จ่าย" ทำไปแล้ว — เหลือดูว่าครบไหม)
- [ ] bulk actions ในจัดการบิล/ยอดค้าง
- [ ] เตือนเบอร์ซ้ำตอนส่งของ
- [ ] ส่งของเก่า+ใหม่พร้อมกัน แยกยอด
- [ ] ปรับ UI ส่วนคำนวณยอด

## 🔧 โครงสร้าง/Maintenance

- [ ] app.py ใหญ่กว่าที่ CLAUDE.md ระบุ (5,340 บรรทัด) — ควรอัปเดตเอกสาร/แยกโมดูล
- [ ] `except Exception:` เงียบ ~17 จุด — ควร log/แจ้ง user
- [ ] shopee_api.py/tab_ecom ยังไม่ wired ครบ — ตัดสินใจทำต่อหรือลบ
- [ ] mutation functions ยังไม่มี `_retry`
- [ ] ไม่มี automated test

## ⏳ รอ Deploy

- [ ] `gas_line_webhook.js` — มีการเปลี่ยนแปลงหลายอย่างในไฟล์ local แล้ว (คู่มือ, จ่ายบางส่วน, เก่าเมนู, tourist_island fix ฯลฯ) ยังไม่ได้ copy ไป Apps Script editor + deploy
