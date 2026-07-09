-- ตาราง preset ขนาดกล่อง — จัดการที่แท็บ ⚙️ จัดการข้อมูล → 📐 ขนาดกล่อง
-- แทนที่ preset ที่เคยเก็บใน session state (หายทุกครั้งที่ปิดแอป) ด้วยตารางถาวรใน Supabase

CREATE TABLE IF NOT EXISTS box_presets (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name       TEXT NOT NULL,
  length_cm  NUMERIC NOT NULL,
  width_cm   NUMERIC NOT NULL,
  height_cm  NUMERIC NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ตารางนี้สร้างผ่าน Table Editor/SQL โดยไม่มี auth ผู้ใช้ต่อคน (แอปใช้ SUPABASE_KEY ตัวเดียว)
-- ต้องปิด RLS เหมือน commission_records/company_info ไม่งั้น insert จะถูกบล็อก
ALTER TABLE box_presets DISABLE ROW LEVEL SECURITY;

-- seed ด้วยขนาดกล่องเดิมที่เคยตั้งไว้เป็นค่า default ในโค้ด (BULKY_BOX_PRESETS_DEFAULT)
-- รันครั้งเดียวตอน migrate — ถ้าตารางมีข้อมูลอยู่แล้วข้ามได้เลย
INSERT INTO box_presets (name, length_cm, width_cm, height_cm) VALUES
  ('ผงเล็ก',   55, 33, 28),
  ('ผงใหญ่',   40, 45, 23),
  ('กาแฟใหญ่', 60, 43, 25),
  ('pana',     23, 35, 16),
  ('โปรตีน',   33, 22, 20),
  ('สระผม',    24, 30, 20),
  ('อาบน้ำ',   32, 26, 25),
  ('XTRA',     30, 42, 26),
  ('น้ำผลไม้', 44, 28, 29);
