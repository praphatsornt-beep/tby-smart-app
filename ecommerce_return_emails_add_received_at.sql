-- เพิ่มคอลัมน์ received_back_at ให้ตาราง ecommerce_return_emails — ใช้บันทึกว่าร้านเช็ค
-- ของจริงแล้วว่าพัสดุตีกลับกลับมาถึงจริง (กดปุ่ม "ได้รับของแล้ว" ที่หน้าแรก) ก่อนหน้านี้ตาราง
-- มีแค่ notice_count/last_seen_at ซึ่งมาจากอีเมลอัตโนมัติของ Shopee เท่านั้น ไม่มีทางรู้ว่า
-- คนที่ร้านตรวจสอบของจริงหรือยัง — NULL แปลว่ายังไม่ได้กดยืนยัน
alter table ecommerce_return_emails add column if not exists received_back_at timestamptz;
