-- ตารางติดตาม "ยืมคะแนน" — ลูกค้าให้ร้านเปิดบิล (สินค้าอะไรก็ได้) ไปก่อนเพื่อนับ PV/BV
-- ให้ลูกค้าทันที แล้วลูกค้าจะ "คืนคะแนน" ทีหลังด้วยการซื้อของจริงอีกบิลหนึ่ง — เก็บยอด
-- ฿/PV/BV ที่เสียไปตอนยืม เทียบกับยอดที่ได้คืนจริง เพื่อรู้ว่าร้านขาดทุนหรือไม่ตอนปิดยอด
-- จัดการที่แท็บ 🗂️ รายละเอียดบิล → 💳 ยืมคะแนน (pv_loan_ui.py)
--
-- pv_lent/bv_lent/baht_lent เป็น snapshot ที่คำนวณจาก transactions ของ lend_bill_no
-- ตอนบันทึกครั้งเดียว (ไม่ join สดทุกครั้งที่อ่าน) กันพลาดถ้าสินค้า/ราคาถูกแก้ทีหลัง

CREATE TABLE IF NOT EXISTS pv_loans (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id   TEXT NOT NULL REFERENCES customers(id),
  lend_date     DATE NOT NULL,
  lend_bill_no  TEXT NOT NULL,
  pv_lent       NUMERIC(10,2) NOT NULL DEFAULT 0,
  bv_lent       NUMERIC(10,2) NOT NULL DEFAULT 0,
  baht_lent     NUMERIC(10,2) NOT NULL DEFAULT 0,
  notes         TEXT,
  created_at    TIMESTAMPTZ DEFAULT now()
);

-- บันทึกการคืนคะแนนแต่ละครั้ง (append-only — คืนบางส่วนได้หลายครั้งต่อ 1 ยืม เหมือน
-- partial_events ของ transactions ปกติ ไม่ทับยอดเดิม)
CREATE TABLE IF NOT EXISTS pv_loan_repayments (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  loan_id        UUID NOT NULL REFERENCES pv_loans(id) ON DELETE CASCADE,
  repay_date     DATE NOT NULL,
  repay_bill_no  TEXT NOT NULL,
  pv_repaid      NUMERIC(10,2) NOT NULL DEFAULT 0,
  bv_repaid      NUMERIC(10,2) NOT NULL DEFAULT 0,
  baht_repaid    NUMERIC(10,2) NOT NULL DEFAULT 0,
  notes          TEXT,
  created_at     TIMESTAMPTZ DEFAULT now()
);

-- ตารางนี้สร้างผ่าน Table Editor/SQL โดยไม่มี auth ผู้ใช้ต่อคน (แอปใช้ SUPABASE_KEY ตัวเดียว)
-- ต้องปิด RLS เหมือน expense_records/box_presets/commission_records ไม่งั้น insert จะถูกบล็อก
ALTER TABLE pv_loans DISABLE ROW LEVEL SECURITY;
ALTER TABLE pv_loan_repayments DISABLE ROW LEVEL SECURITY;
