-- เพิ่มคอลัมน์ระบุที่มาของ partial_events ประเภท "รับของ" — แยกว่ามาจากการส่งพัสดุจริง
-- ตอนบันทึกขาย (source='ship', มี recipient_name แนบมาด้วย) หรือมาจากบันทึกรับของธรรมดา
-- ที่หน้ายอดค้าง/ประวัติทั้งหมด (source เป็น NULL) — ใช้แยกไอคอน/ข้อความในไทม์ไลน์บัตรลูกค้า
-- แทนการเดาจากวันที่ชนกับ shipment (ไม่แม่นถ้าลูกค้ามีของเก่าที่ไม่เกี่ยวข้องพอดีวันเดียวกัน)
ALTER TABLE partial_events ADD COLUMN IF NOT EXISTS source TEXT;
ALTER TABLE partial_events ADD COLUMN IF NOT EXISTS recipient_name TEXT;
