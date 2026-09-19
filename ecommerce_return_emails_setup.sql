-- ตารางเก็บ "พัสดุตีคืน/จัดส่งไม่สำเร็จ" ที่แกะมาจากอีเมลแจ้งเตือนอัตโนมัติของ Shopee
-- (info@mail.shopee.co.th) — เชื่อม Shopee API ตรงๆ ไม่ได้ (ไม่ใช่ Managed/Mall Seller)
-- อีเมลจึงเป็นทางเดียวที่รู้ว่าออเดอร์ไหนถูกตีกลับ ยืนยันด้วยอีเมลจริง 2026-09-19: Lazada/TikTok
-- ไม่มีอีเมลแจ้งเตือนอัตโนมัติแบบนี้ (Lazada มีแต่เคสร้องเรียนแมนนวลเก่า, TikTok ไม่มีเลย) —
-- ตารางนี้จึงรองรับ Shopee เป็นหลัก แต่เผื่อ platform อื่นในอนาคตไว้เป็นคอลัมน์
CREATE TABLE IF NOT EXISTS ecommerce_return_emails (
  id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  platform       TEXT NOT NULL DEFAULT 'shopee',
  order_sn       TEXT NOT NULL,
  carrier_name   TEXT,
  tracking_no    TEXT,
  notice_subject TEXT,       -- หัวเรื่องอีเมลล่าสุดที่เจอ (บอกสถานะ: กำลังส่งคืน / ส่งคืนไม่สำเร็จ)
  notice_count   INT NOT NULL DEFAULT 1,   -- Shopee ส่งซ้ำเป็น "แจ้งครั้งที่ 2/3" ถ้ายังส่งคืนไม่สำเร็จ
  first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (platform, order_sn)
);

-- ใช้ SUPABASE_KEY ตัวเดียวจากแอป/สคริปต์ ไม่มี auth ต่อผู้ใช้ ต้องปิด RLS เหมือนตารางอื่น
-- ในกลุ่มนี้ (ดู ecommerce_setup.sql) ไม่งั้น insert/upsert จะโดนบล็อก (error 42501)
ALTER TABLE ecommerce_return_emails DISABLE ROW LEVEL SECURITY;
