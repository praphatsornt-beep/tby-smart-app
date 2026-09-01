-- รันใน Supabase dashboard → SQL Editor → New query
--
-- แก้บั๊ก: upsert_customer_address() เดิม ลบแถว customer_addresses ที่มีเบอร์เดียวกันทิ้ง
-- ก่อน insert เสมอ (ไม่สนว่าเป็นคนละ customer_id) — ถ้าลูกค้า 2 คนใช้เบอร์ผู้รับเดียวกัน
-- (เช่น อยู่บ้านเดียวกัน) พอคนหนึ่งบันทึกที่อยู่ใหม่ ที่อยู่เดิมของอีกคนถูกลบทิ้งเงียบๆ
-- ทั้งที่ควรเก็บไว้ทั้งคู่ — แก้โดยเลิก dedupe ด้วยเบอร์ ให้ insert แถวใหม่ได้เสมอ (ดู
-- database.py upsert_customer_address) แต่ต้องมี created_at ไว้เรียง เพื่อให้
-- get_address_by_phone() (ใช้ autofill ตอนพิมพ์เบอร์ในหน้าส่งของ) เลือกแถว "ล่าสุด"
-- ของเบอร์นั้นได้แทนที่จะสุ่มเจอแถวเก่า

ALTER TABLE customer_addresses ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now();
