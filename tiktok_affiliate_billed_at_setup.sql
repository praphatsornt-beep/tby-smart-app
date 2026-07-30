-- เพิ่มคอลัมน์ billed_at ให้ tiktok_affiliate_orders — บันทึกเวลาที่กดยืนยัน "เปิดบิล"
-- จริง (แทนที่จะรู้แค่ true/false เฉยๆ) ใช้ทำสรุป "เปิดบิลไปแล้ววันนี้" ที่ยืนอยู่ได้แม้
-- รีเฟรช/ปิดหน้าไป และเป็น audit trail กู้คืนได้ถ้ามีอะไรพลาดกดผิดในอนาคต
-- รันครั้งเดียวใน Supabase SQL Editor (โปรเจกต์ vpvpcdtpysfbatkugfzs เท่านั้น)

ALTER TABLE tiktok_affiliate_orders ADD COLUMN IF NOT EXISTS billed_at TIMESTAMPTZ;
