-- ตารางบันทึก "เวลาที่แพคของ" จากการสแกนบาร์โค้ด/QR บนใบปะหน้าพัสดุ (📷 แพคของ)
-- บันทึกแยกเป็น log การแพค ไม่ผูกกับออเดอร์ใดๆ โดยตรง (ยืนยันกับ user 2026-10-25) —
-- ของ Shopee/Lazada ตอนนี้ระบบไม่เคยเก็บเลข tracking ไว้เลย (มีแค่ order_sn) เลยไม่มีอะไรให้
-- join จริงๆ ส่วนของ iship (tracking_no มีอยู่แล้วใน shipments) จะ match ชื่อลูกค้า/ขนส่งแล้ว
-- เก็บแบบ denormalized ไว้ในแถวนี้เลยตอนสแกน (ไม่ query join ใหม่ตอนอ่านทีหลัง)

CREATE TABLE IF NOT EXISTS pack_events (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tracking_no            TEXT NOT NULL,
  -- 'iship' = match ตรงกับ shipments.tracking_no ของร้านเอง (รู้แน่นอน)
  -- 'lazada' = เดาจากคำนำหน้าเลข "LEX" (ขนส่งในเครือ Lazada เอง ไม่มีใน carrier list ของ
  --            iship เลย — ดู pack_scan_ui.py's _guess_source())
  -- 'shopee' = รู้แน่นอนถ้าเจอ order_sn ด้วย (ดูคอลัมน์ order_sn ด้านล่าง) ไม่งั้นเป็นแค่เดา
  --            ที่เหลือทั้งหมด (ดีที่สุดเท่าที่ทำได้ ไม่ใช่ข้อเท็จจริง 100%)
  source                 TEXT NOT NULL DEFAULT 'shopee',
  matched_customer_name  TEXT,  -- เติมเฉพาะ source='iship' ที่หาเจอใน shipments ตอนสแกน
  matched_carrier        TEXT,  -- เติมเฉพาะ source='iship' เช่นกัน
  -- เลขที่ออเดอร์ Shopee (รูปแบบ YYMMDD+8 ตัวอักษร/ตัวเลข เช่น 261024F2DR9DEW) ถ้าสแกนเจอ
  -- บาร์โค้ดที่ 2 บนใบปะหน้า Shopee (แยกจากบาร์โค้ด tracking หลัก) — ยืนยันกับ user 2026-10-25
  -- ว่าอยากบันทึกไว้ด้วยให้ชัวร์ขึ้นว่าเป็น Shopee จริง ไม่ใช่แค่เดา — ไม่มีของ Lazada/iship
  -- (Lazada ไม่มีบาร์โค้ดเลขออเดอร์แยกให้สแกนในรูปที่เช็ค, iship รู้จาก shipments อยู่แล้ว)
  order_sn               TEXT,
  packed_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pack_events_tracking_no ON pack_events (tracking_no);
CREATE INDEX IF NOT EXISTS idx_pack_events_packed_at ON pack_events (packed_at DESC);

-- ตารางนี้สร้างผ่าน Table Editor/SQL โดยไม่มี auth ผู้ใช้ต่อคน (แอปใช้ SUPABASE_KEY ตัวเดียว)
-- ต้องปิด RLS เหมือน box_presets/pv_loans/commission_records ไม่งั้น insert จะถูกบล็อก
ALTER TABLE pack_events DISABLE ROW LEVEL SECURITY;
