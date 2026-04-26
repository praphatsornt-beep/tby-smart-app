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
    pay_status TEXT NOT NULL CHECK (pay_status IN ('จ่ายแล้ว', 'ค้างจ่าย')),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- บันทึกทุกครั้งที่รับของหรือจ่ายเงินบางส่วน
CREATE TABLE partial_events (
    id TEXT PRIMARY KEY,
    date DATE NOT NULL,
    transaction_id TEXT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    qty_received INTEGER NOT NULL DEFAULT 0 CHECK (qty_received >= 0),
    amount_paid NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (amount_paid >= 0),
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
    notes         TEXT DEFAULT ''
);
