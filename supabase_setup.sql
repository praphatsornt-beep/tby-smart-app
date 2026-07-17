-- รันใน Supabase dashboard → SQL Editor → New query
--
-- อัปเดต 2026-07-15 ให้ตรงกับ schema จริงในโปรดักชัน (introspect จาก
-- information_schema.columns จริง ไม่ใช่อนุมานจากโค้ดเหมือนก่อนหน้านี้) — ตารางอื่น
-- ที่ไม่อยู่ในไฟล์นี้: box_presets (box_presets_setup.sql), commission_records/
-- company_info (commission_setup.sql + commission_receipt_migration.sql)
--
-- ⚠️ พบระหว่าง introspect: ecommerce_shops / ecommerce_sales / ecommerce_product_map
-- ที่ database.py และ ecom_ui.py อ้างถึง **ไม่มีอยู่จริงในโปรดักชัน** (query ตรงๆ
-- ได้ PGRST205 "Could not find the table") — แปลว่าแท็บ 🛒 E-commerce จะ error ทันที
-- ถ้ามีคนกดใช้งานจริง ทั้งที่โค้ดดูเหมือนต่อครบแล้ว ยังไม่ได้สร้างตารางเหล่านี้ต้อง
-- ตัดสินใจว่าจะสร้างจริง (ต้องดูโค้ด ecom_ui.py/database.py เพื่อ derive schema ที่
-- ต้องการ) หรือถือว่าฟีเจอร์นี้ยังไม่ใช้งานจริงตอนนี้

CREATE TABLE products (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price NUMERIC(10,2) NOT NULL,
    points_per_unit NUMERIC(10,2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    bv_per_unit NUMERIC(10,2) DEFAULT 0,        -- BV (business volume) — คู่ขนานกับ points_per_unit
    weight_grams NUMERIC(10,2) DEFAULT 0,       -- น้ำหนักสินค้า/หน่วย ใช้คำนวณค่าส่ง
    image_url TEXT,                             -- รูปสินค้า สำหรับ LIFF catalog
    show_in_liff BOOLEAN DEFAULT FALSE,         -- โชว์สินค้านี้ใน LIFF หรือไม่
    name_mm TEXT,                               -- ชื่อสินค้าภาษาพม่า (LIFF/LINE OA)
    max_units_per_box INTEGER                   -- จำกัดจำนวนชิ้น/กล่อง (NULL = ไม่จำกัด,
                                                 -- ใช้น้ำหนักอย่างเดียว) — add_max_units_per_box.sql
);

CREATE TABLE customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    -- ที่อยู่ "หลัก"/ล่าสุดของลูกค้า เก็บตรงนี้แยกจาก customer_addresses (ที่เก็บได้
    -- หลายที่อยู่ต่อลูกค้า) — update_customer_address() เขียนทับฟิลด์พวกนี้ตรงๆ
    recipient_name TEXT,
    address TEXT,
    address_line TEXT,
    district TEXT,
    amphure TEXT,
    province TEXT,
    postal_code TEXT,
    line_user_id TEXT,  -- ผูกจาก LINE OA "สมัคร <เบอร์โทร>" (gas_line_webhook.js)
    group_id TEXT       -- LINE group ผูกด้วยคำสั่ง "groupid" (ถ้าอยากแจ้งเตือนเข้ากลุ่มแทน 1:1)
);

-- กันเบอร์ซ้ำ — แต่ลูกค้าที่ยังไม่มีเบอร์เก็บเป็น '' (empty string) ไม่ใช่ NULL
-- (เช็คจริงกับข้อมูลจริง 2026-07-15: 61 คน มีเบอร์จริง 5 คน ไม่ซ้ำกันเลย, อีก 56 คน
-- phone='') ต้องใช้ partial unique index ไม่ใช่ UNIQUE เฉยๆ ไม่งั้นแถว '' 56 แถวชนกันเอง
-- ทันทีตอนสร้าง constraint — รันแล้วในโปรดักชัน 2026-07-15 ยืนยันด้วย live test ว่า
-- บล็อกเบอร์ซ้ำจริงและไม่กระทบแถว '' ที่มีอยู่
CREATE UNIQUE INDEX customers_phone_unique_idx ON customers (phone) WHERE phone <> '';

-- ที่อยู่จัดส่งของลูกค้า (หลายที่อยู่ต่อ 1 ลูกค้า) — แยกจากที่อยู่ "หลัก" ใน customers
-- เอง เพิ่งพบว่าไม่เคยมีไฟล์ setup ที่ไหนเลยตอน introspect 2026-07-15 (สร้างผ่าน Table
-- Editor ตรงๆ ในอดีต)
CREATE TABLE customer_addresses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id TEXT REFERENCES customers(id),
    recipient_name TEXT,
    phone TEXT,
    address_line TEXT,
    district TEXT,
    amphure TEXT,
    province TEXT,
    postal_code TEXT
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
    -- 'COD จ่ายแล้ว' = COD ที่โอนเงินเข้าระบบแล้ว (mark_cod_paid) แยกจาก 'COD' เฉยๆ
    -- ที่แปลว่ายังไม่ได้โอน
    pay_status TEXT NOT NULL CHECK (pay_status IN ('จ่ายแล้ว', 'ค้างจ่าย', 'COD', 'COD จ่ายแล้ว')),
    notes TEXT,
    bill_no TEXT,  -- เลขอ้างอิงภายในอัตโนมัติ (get_next_bill_no, YYMMDD-NNN) — ไม่ถูกเขียนทับ
                   -- อีกต่อไป คงค่าเดิมตลอดอายุแถว เลขบิลจริงจาก Zhulian (ถ้ามี) เก็บเป็น
                   -- โน้ต optional ที่ bill_open_events.note แทน ดู database.py:open_bill_partial()
    bill_opened_at DATE,  -- วันที่เปิดบิลครบเต็มจำนวนล่าสุด (bill_status ขยับเป็น "เปิดบิลแล้ว")
                          -- แยกจาก date (วันที่เบิกของ/สั่งซื้อ) — เปิดบิลบางส่วนดูละเอียดได้ที่
                          -- bill_open_events แทน (ไม่แยกแถวแล้วเหมือนกลไกเดิม)
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- บันทึกทุกครั้งที่รับของหรือจ่ายเงินบางส่วน
CREATE TABLE partial_events (
    id TEXT PRIMARY KEY,
    date DATE NOT NULL,
    transaction_id TEXT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    qty_received INTEGER NOT NULL DEFAULT 0 CHECK (qty_received >= 0),
    -- amount_paid ไม่มี CHECK >= 0 โดยตั้งใจ — database.py:split_and_open_bill() insert
    -- แถวติดลบตรงๆ เป็น correction event ตอนแยกเปิดบิลบางส่วน (โอนยอดจ่ายเกินไปให้
    -- รายการที่แยก) เคยมี CHECK (amount_paid >= 0) มาก่อนแล้วชนกับโค้ดจุดนี้จริงใน
    -- โปรดักชัน (พบ+แก้แล้ว 2026-07-15 — DROP constraint นั้นทิ้ง) ฝั่ง UI ยังกัน
    -- negative จากผู้ใช้ด้วย number_input(min_value=0.0) ทุกจุดอยู่แล้ว
    amount_paid NUMERIC(10,2) NOT NULL DEFAULT 0,
    event_type TEXT NOT NULL CHECK (event_type IN ('รับของ', 'จ่ายเงิน', 'ทั้งคู่')),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shipments (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at    TIMESTAMPTZ DEFAULT NOW(),
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

-- การเงินรายวัน (โอนบริษัท/ยอดขาย/PO/BV/สต๊อกยกมา) — 1 แถวต่อวัน (upsert = delete+insert)
-- ไม่เคยมีไฟล์ setup ที่ไหนเลยตอน introspect 2026-07-15
CREATE TABLE finance_daily (
    id TEXT PRIMARY KEY,
    entry_date DATE NOT NULL,
    transfer_amount NUMERIC(10,2) DEFAULT 0,   -- โอนให้บริษัท
    registration_fee NUMERIC(10,2) DEFAULT 0,
    sales_amount NUMERIC(10,2) DEFAULT 0,      -- ยอดขาย รวม VAT
    bv_amount NUMERIC(10,2) DEFAULT 0,
    po_amount NUMERIC(10,2) DEFAULT 0,         -- PO สั่งของ ไม่รวม VAT
    stock_value NUMERIC(10,2) DEFAULT 0,       -- สต๊อกยกมา (เปิดเดือนใหม่ตั้งครั้งเดียว)
    adjustment NUMERIC(10,2) DEFAULT 0,        -- ยอดปรับ carry-forward
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ผลนับสต๊อกต่อสินค้าต่อวัน — ไม่เคยมีไฟล์ setup ที่ไหนเลยตอน introspect 2026-07-15
CREATE TABLE stock_counts (
    id TEXT PRIMARY KEY,
    product_id TEXT REFERENCES products(id),
    count_date DATE NOT NULL,
    qty_system INTEGER DEFAULT 0,    -- ยอดคอมพิวเตอร์ (keyed-in)
    qty_physical INTEGER DEFAULT 0,  -- ยอดนับจริง
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ของฝาก (สินค้าที่บิลแล้วแต่ลูกค้ายังไม่มารับ) — ไม่เคยมีไฟล์ setup ที่ไหนเลยตอน
-- introspect 2026-07-15
CREATE TABLE stock_deposits (
    id TEXT PRIMARY KEY,
    product_id TEXT REFERENCES products(id),
    customer_name TEXT,
    qty INTEGER NOT NULL DEFAULT 0,
    deposit_date DATE,
    is_returned BOOLEAN DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
