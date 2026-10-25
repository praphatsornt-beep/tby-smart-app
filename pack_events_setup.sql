-- ตารางบันทึก "เวลาที่แพคของ" จากการสแกนบาร์โค้ด/QR บนใบปะหน้าพัสดุ (📷 แพคของ)
-- บันทึกแยกเป็น log การแพค ไม่ผูกกับออเดอร์ใดๆ โดยตรง (ยืนยันกับ user 2026-10-25) —
-- ของ Shopee/Lazada ตอนนี้ระบบไม่เคยเก็บเลข tracking ไว้เลย (มีแค่ order_sn) เลยไม่มีอะไรให้
-- join จริงๆ ส่วนของ iship (tracking_no มีอยู่แล้วใน shipments) จะ match ชื่อลูกค้า/ขนส่งแล้ว
-- เก็บแบบ denormalized ไว้ในแถวนี้เลยตอนสแกน (ไม่ query join ใหม่ตอนอ่านทีหลัง)

CREATE TABLE IF NOT EXISTS pack_events (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tracking_no            TEXT NOT NULL,
  source                 TEXT NOT NULL DEFAULT 'other',  -- 'iship' | 'other' (Shopee/Lazada/ไม่รู้จัก)
  matched_customer_name  TEXT,  -- เติมเฉพาะ source='iship' ที่หาเจอใน shipments ตอนสแกน
  matched_carrier        TEXT,  -- เติมเฉพาะ source='iship' เช่นกัน
  packed_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pack_events_tracking_no ON pack_events (tracking_no);
CREATE INDEX IF NOT EXISTS idx_pack_events_packed_at ON pack_events (packed_at DESC);

-- ตารางนี้สร้างผ่าน Table Editor/SQL โดยไม่มี auth ผู้ใช้ต่อคน (แอปใช้ SUPABASE_KEY ตัวเดียว)
-- ต้องปิด RLS เหมือน box_presets/pv_loans/commission_records ไม่งั้น insert จะถูกบล็อก
ALTER TABLE pack_events DISABLE ROW LEVEL SECURITY;
