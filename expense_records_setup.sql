-- ตารางเก็บใบเสร็จ/ค่าใช้จ่ายรายเดือน (ค่าน้ำมัน ค่าอาหาร ค่าซุปเปอร์ ค่าส่ง เงินเดือน
-- ค่าเช่า ค่าโฆษณา ฯลฯ) — จัดการที่แท็บ 💵 การเงิน → 🧾 ค่าใช้จ่าย
-- ใช้คำนวณ "กำไรโดยประมาณ" รายเดือน + ขยายภาษีซื้อในสรุปภาษีซื้อ/ภาษีขาย

CREATE TABLE IF NOT EXISTS expense_records (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  expense_date     DATE NOT NULL,
  category         TEXT NOT NULL,
  amount           NUMERIC(10,2) NOT NULL DEFAULT 0,   -- ยอดตามใบเสร็จ (รวม VAT ถ้ามี)
  vendor           TEXT,
  has_tax_invoice  BOOLEAN NOT NULL DEFAULT FALSE,      -- ใบกำกับภาษีเต็มรูป (เคลม VAT ซื้อได้)
  notes            TEXT,
  created_at       TIMESTAMPTZ DEFAULT now()
);

-- ตารางนี้สร้างผ่าน Table Editor/SQL โดยไม่มี auth ผู้ใช้ต่อคน (แอปใช้ SUPABASE_KEY ตัวเดียว)
-- ต้องปิด RLS เหมือน box_presets/commission_records/company_info ไม่งั้น insert จะถูกบล็อก
ALTER TABLE expense_records DISABLE ROW LEVEL SECURITY;
