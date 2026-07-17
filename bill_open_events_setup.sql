-- เปิดบิลบางส่วนแบบ event-based (ไม่แยกแถวอีกต่อไป) — แทนที่กลไก split_and_open_bill เดิม
-- ที่แยกแถว transactions เป็น 2 ฝั่งทุกครั้งที่เปิดบิลไม่เต็มจำนวน เลขบิลจริงจาก Zhulian
-- กลายเป็นแค่โน้ต optional (ไม่ validate/ไม่เช็คซ้ำ) เก็บไว้ที่ event ไม่ใช่ที่ transactions.bill_no
-- (bill_no ของแถว transactions จะไม่ถูกเขียนทับอีกต่อไป คงเป็นเลขอ้างอิงภายในตลอดอายุแถว)
CREATE TABLE IF NOT EXISTS bill_open_events (
    id TEXT PRIMARY KEY,
    date DATE NOT NULL,
    transaction_id TEXT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    qty_opened INTEGER NOT NULL,  -- ไม่มี CHECK >= 0 โดยตั้งใจ — event ยกเลิกเปิดบิล
                                   -- (undo_last_bill_open_event) ต้อง insert ค่าติดลบเป็น
                                   -- correction event แบบเดียวกับ partial_events.amount_paid
                                   -- (เคยมี CHECK >= 0 บน amount_paid มาก่อนแล้วต้อง DROP ทิ้ง
                                   -- 2026-07-15 เพราะชนกับ correction event จริงในโปรดักชัน
                                   -- ห้ามทำผิดซ้ำจุดเดิม)
    note TEXT,  -- optional — ปกติคือเลขที่บิลจริงจาก Zhulian ที่ staff พิมพ์เอง ไม่ validate/
                -- ไม่เช็คซ้ำข้ามลูกค้าอีกต่อไป (find_bill_no_conflict ถูกตัดออก)
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bill_open_events_transaction_id ON bill_open_events(transaction_id);

-- ตารางนี้สร้างผ่าน SQL โดยไม่มี auth ผู้ใช้ต่อคน (แอปใช้ SUPABASE_KEY ตัวเดียว) — ต้องปิด RLS
-- เหมือน commission_records/company_info/box_presets ไม่งั้น insert จะถูกบล็อก
ALTER TABLE bill_open_events DISABLE ROW LEVEL SECURITY;
