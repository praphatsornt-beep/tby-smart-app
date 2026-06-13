# TODO — TBY SMART APP

## 🟡 ยังค้างอยู่ (refactor/bug)

- [x] ~~รวม logic คำนวณยอดต่อบิล (บัตรลูกค้า vs จัดการบิล) ให้เป็น helper เดียว `_bills_from_df()`~~
- [x] ~~Bug: ช่องตำบลไม่แสดงค่าตอนเลือก "ที่อยู่เดิม"~~ (commit `8b15520` — บังคับ session_state ของ selectbox ตรงๆ)
- [x] ~~**iShip COD**~~ — ตัดสินใจแล้ว: ยอมรับความเสี่ยง scraping (`_web_session` ใน `iship_api.py`) ต่อไป ไม่ต้องเปลี่ยนเป็น manual
- [x] ~~GAS: tourist_island weight tiers + remote postcodes 50270, 55220 ตกหล่น~~ (commit `38a470c`)

## 📋 Wishlist (ยังไม่ตัดสินใจ priority)

- [x] ~~สรุป PV ค้างเปิดบิลทั้งหมดของลูกค้า~~ — แสดงในป้าย expander ยอดค้าง + `_render_bill_panel` ("⭐ PV รวม/ค้างเปิดบิล")
- [x] ~~เบิกของเก่าค้างรับ/ค้างจ่าย ผ่าน LINE~~ — ลูกค้าพิมพ์ "ยอด"/"สรุปยอด" เอง (`sendCustomerSummary`/`buildAndSendSummary`) ครบทั้งค้างรับและค้างจ่าย ทำและ deploy แล้ว
- [x] ~~bulk actions ในจัดการบิล/ยอดค้าง~~ — ลบหลายรายการพร้อมกัน (ไม่ลบทั้งบิล) ทั้งใน ยอดค้าง (multi-select) และ จัดการบิล (multiselect)
- [x] ~~เตือนเบอร์ซ้ำตอนส่งของ~~
- [ ] ปรับ UI ส่วนคำนวณยอด

## 🔧 โครงสร้าง/Maintenance

- [x] ~~app.py ใหญ่กว่าที่ CLAUDE.md ระบุ~~ — อัปเดตจำนวนบรรทัดใน CLAUDE.md แล้ว (แยกโมดูลยังไม่ทำ)
- [ ] `except Exception:` เงียบ ~17 จุด — ควร log/แจ้ง user
- [ ] shopee_api.py/tab_ecom ยังไม่ wired ครบ — ตัดสินใจทำต่อหรือลบ
- [ ] mutation functions ยังไม่มี `_retry`
- [ ] ไม่มี automated test

## ⏳ รอ Deploy

- [x] ~~`gas_line_webhook.js` — มีการเปลี่ยนแปลงหลายอย่างในไฟล์ local (คู่มือ, จ่ายบางส่วน, เก่าเมนู, เบิกจ่าย+จ่ายบางส่วน, ปุ่มยกเลิก, tourist_island fix ฯลฯ)~~ — copy ไป Apps Script editor + deploy แล้ว
