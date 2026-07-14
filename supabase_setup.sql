-- รันใน Supabase dashboard → SQL Editor → New query

CREATE TABLE products (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price NUMERIC(10,2) NOT NULL,
    points_per_unit NUMERIC(10,2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT,
    line_user_id TEXT,  -- ผูกจาก LINE OA "สมัคร <เบอร์โทร>" (gas_line_webhook.js)
    group_id TEXT,      -- LINE group ผูกด้วยคำสั่ง "groupid" (ถ้าอยากแจ้งเตือนเข้ากลุ่มแทน 1:1)
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 1 แถว = 1 สินค้าใน 1 รายการ
CREATE TABLE transactions (
    id TEXT PRIMARY KEY,
    date DATE NOT NULL,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    product_id TEXT NOT NULL REFERENCES products(id),
    product_name TEXT NOT NULL,
    qty INTEGER NOT NULL CHECK (qty > 0),
    price_per_unit NUMERIC(10,2) NOT NULL,
    points_per_unit NUMERIC(10,2) NOT NULL DEFAULT 0,
    total_amount NUMERIC(10,2) NOT NULL,
    initial_qty_received INTEGER NOT NULL DEFAULT 0,
    transaction_type TEXT NOT NULL CHECK (transaction_type IN ('ขายปกติ', 'เบิกของก่อน')),
    bill_status TEXT NOT NULL CHECK (bill_status IN ('เปิดบิลแล้ว', 'ยังไม่เปิดบิล')),
    -- 'COD จ่ายแล้ว' = COD ที่โอนเงินเข้าระบบแล้ว (mark_cod_paid) แยกจาก 'COD'
    -- เฉยๆ ที่แปลว่ายังไม่ได้โอน — ค่านี้เคย missing จากไฟล์นี้มาก่อน (ALTER TABLE
    -- เพิ่มเข้าไปตรงๆ ในโปรดักชันโดยไม่ได้ backport กลับมาที่นี่)
    pay_status TEXT NOT NULL CHECK (pay_status IN ('จ่ายแล้ว', 'ค้างจ่าย', 'COD', 'COD จ่ายแล้ว')),
    notes TEXT,
    bill_no TEXT,  -- เลขที่บิล YYMMDD-NNN (get_next_bill_no) — เพิ่มทีหลังผ่าน ALTER TABLE เช่นกัน
    bill_opened_at DATE,  -- วันที่ "เปิดบิล" จริง (แยกจาก date = วันที่เบิกของ/สั่งซื้อ)
                          -- ยังไม่มีในโปรดักชัน ณ ตอนที่เพิ่มโค้ดนี้ — ต้องรัน
                          -- ALTER TABLE transactions ADD COLUMN bill_opened_at DATE; เอง
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- บันทึกทุกครั้งที่รับของหรือจ่ายเงินบางส่วน
CREATE TABLE partial_events (
    id TEXT PRIMARY KEY,
    date DATE NOT NULL,
    transaction_id TEXT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    qty_received INTEGER NOT NULL DEFAULT 0 CHECK (qty_received >= 0),
    -- amount_paid ไม่มี CHECK >= 0 โดยตั้งใจ — database.py:split_and_open_bill()
    -- insert แถวติดลบตรงๆ เป็น correction event ตอนแยกเปิดบิลบางส่วน (โอนยอดจ่าย
    -- เกินไปให้รายการที่แยก) เคยมี CHECK (amount_paid >= 0) มาก่อนแล้วชนกับโค้ด
    -- จุดนี้จริงในโปรดักชัน (verify แล้ว 2026-07-15 เจอ constraint
    -- partial_events_amount_paid_check บังคับใช้อยู่จริง) จึง DROP constraint นั้น
    -- ทิ้งแล้ว — ฝั่ง UI (record_ui.py/bill_detail_ui.py) ยังกัน negative จากผู้ใช้
    -- ด้วย number_input(min_value=0.0) อยู่แล้วทุกจุด จึงไม่มีช่องให้ค่าติดลบหลุด
    -- เข้ามาจากที่อื่นนอกจาก correction ที่ตั้งใจนี้จุดเดียว
    amount_paid NUMERIC(10,2) NOT NULL DEFAULT 0,
    event_type TEXT NOT NULL CHECK (event_type IN ('รับของ', 'จ่ายเงิน', 'ทั้งคู่')),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shipments (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at    DATE DEFAULT CURRENT_DATE,
    customer_id   TEXT REFERENCES customers(id),
    recipient_name TEXT,
    phone         TEXT,
    address_line  TEXT,
    district      TEXT,
    amphure       TEXT,
    province      TEXT,
    postal_code   TEXT,
    carrier       TEXT,
    shipping_cost NUMERIC(10,2) DEFAULT 0,
    items         JSONB,
    tracking_no   TEXT DEFAULT '',
    notes         TEXT DEFAULT '',
    cod_amount          NUMERIC(10,2) DEFAULT 0,
    source              TEXT DEFAULT 'ship',  -- 'sale' | 'ship' | 'manual' — จุดที่สร้าง shipment นี้
    delivery_status     TEXT,                 -- sync จาก iShip (get_shipment_statuses)
    cod_transferred_at  TIMESTAMPTZ,          -- mark_cod_transferred() — วันที่ COD โอนเข้าระบบ
    line_notified_at    TIMESTAMPTZ           -- mark_line_notified() — กันแจ้งซ้ำ
);
