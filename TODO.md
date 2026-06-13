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
- [x] ~~ปรับ UI ส่วนคำนวณยอด~~ — แยก checkbox "จัดส่ง" (กรอกรหัสไปรษณีย์) และ "COD" ออกจากช่องข้อความ (commit `6997c2e`)

## 🔧 โครงสร้าง/Maintenance

- [x] ~~ตรวจ data consistency ระหว่าง app.py กับ gas_line_webhook.js~~ — พบ 3 ประเด็น: (1) cache ของ app.py (ยอดค้าง/บัตรลูกค้า) อาจไม่ทันเห็นรายการที่ลูกค้าจ่าย/รับของผ่าน LINE ทันที → เพิ่มปุ่ม "🔄 รีเฟรชยอด" ใน ยอดค้าง/บัตรลูกค้า + ลด ttl เหลือ 20 วิ (2) `event_type` ของ partial_events ไม่ตรงกัน (`"จ่าย"`/`"รับของจากบิลเก่า"` vs `"จ่ายเงิน"`/`"รับของ"`) → normalize ให้ตรงกับ GAS แล้ว (3) bill_no อาจชนกันได้ถ้า app.py กับ GAS สร้างบิลพร้อมกันพอดี (race condition, ความน่าจะเป็นต่ำมาก) — ยังไม่แก้ ต้องใช้ atomic counter ถ้าจะแก้จริง
- [x] ~~app.py ใหญ่กว่าที่ CLAUDE.md ระบุ~~ — อัปเดตจำนวนบรรทัดใน CLAUDE.md แล้ว (แยกโมดูลยังไม่ทำ)
- [x] ~~`except Exception:` เงียบ ~17 จุด~~ — ตรวจครบแล้ว: ส่วนใหญ่เป็น fallback ที่ตั้งใจ (parse/lookup ที่อยู่, ตาราง DB ที่ยังไม่มี) ปล่อยไว้ตามเดิม ส่วนที่เสี่ยงข้อมูลไม่ตรง (สร้าง shipment record หลังส่ง iShip สำเร็จ ×2, mark_cod_transferred/mark_cod_paid, delete_shipment) เพิ่ม st.warning/st.error ให้ผู้ใช้เห็นแล้ว
- [ ] shopee_api.py/tab_ecom ยังไม่ wired ครบ — ตัดสินใจทำต่อหรือลบ
- [ ] mutation functions ยังไม่มี `_retry`
- [x] ~~ไม่มี automated test~~ — เพิ่ม `tests/` (unittest, รัน `py -m unittest discover -s tests`) ครอบคลุม parse คำสั่งคำนวณ, ค่าธรรมเนียม COD, bin packing แบ่งกล่อง, ตารางค่าส่ง/โซนพื้นที่พิเศษ — แยก logic ส่วนนี้ไป `calc_logic.py` เพื่อให้ test ได้โดยไม่ต้องรัน Streamlit

## ⏳ รอ Deploy

- [x] ~~`gas_line_webhook.js` — มีการเปลี่ยนแปลงหลายอย่างในไฟล์ local (คู่มือ, จ่ายบางส่วน, เก่าเมนู, เบิกจ่าย+จ่ายบางส่วน, ปุ่มยกเลิก, tourist_island fix ฯลฯ)~~ — copy ไป Apps Script editor + deploy แล้ว
- [ ] `gas_line_webhook.js` — แก้ `SH-kg รหัสไปรษณีย์` ให้รองรับเว้นวรรค (commit `ee90e22`) — ยังไม่ deploy
