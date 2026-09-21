-- เพิ่มคอลัมน์ให้บันทึกว่าตรวจรับพัสดุตีกลับ/ยกเลิกคืนจริงแล้ว (ปุ่ม "✅ รับของตีกลับแล้ว" ที่หน้าแรก)
-- NULL = ยังไม่ยืนยัน (ยังโชว์ค้างในการ์ด "พัสดุที่มีปัญหา ตีกลับ/ยกเลิก")
-- รันครั้งเดียวใน Supabase SQL Editor ก่อนใช้ปุ่มนี้
ALTER TABLE shipments ADD COLUMN IF NOT EXISTS return_confirmed_at TIMESTAMPTZ;
