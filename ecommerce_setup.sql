-- ตารางสำหรับแท็บ 🛒 E-commerce (Shopee) — ยังไม่มีในโปรดักชันมาก่อน (พบตอน audit 2026-07-15,
-- ดู PGRST205 "Could not find the table" ตอน query ตรงๆ) โค้ดใน database.py/ecom_ui.py/app.py
-- (OAuth callback) อ้างอิงชื่อคอลัมน์พวกนี้อยู่แล้ว ตารางด้านล่างทำตามให้ตรงเป๊ะ

-- 1) ร้านค้าที่เชื่อมต่อ (ผูก OAuth token ต่อร้าน รองรับหลายร้าน/หลายแพลตฟอร์ม)
CREATE TABLE IF NOT EXISTS ecommerce_shops (
  id            TEXT PRIMARY KEY,        -- str(shop_id) จาก Shopee — ดู app.py OAuth callback
  platform      TEXT NOT NULL DEFAULT 'shopee',
  shop_name     TEXT NOT NULL,
  shop_id       BIGINT NOT NULL,
  access_token  TEXT,
  refresh_token TEXT,
  token_expiry  TIMESTAMPTZ,
  created_at    TIMESTAMPTZ DEFAULT now()
);

-- 2) รายการขายที่ sync มาจาก order/item ของแต่ละร้าน
CREATE TABLE IF NOT EXISTS ecommerce_sales (
  id               UUID PRIMARY KEY,
  platform         TEXT NOT NULL DEFAULT 'shopee',
  shop_name        TEXT NOT NULL,
  order_sn         TEXT,
  sale_date        DATE NOT NULL,
  product_id       TEXT REFERENCES products(id) ON DELETE SET NULL,
  item_id_platform TEXT NOT NULL,
  qty              NUMERIC NOT NULL DEFAULT 0,
  item_price       NUMERIC NOT NULL DEFAULT 0,
  created_at       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ecommerce_sales_date ON ecommerce_sales (sale_date);
CREATE INDEX IF NOT EXISTS idx_ecommerce_sales_unmapped ON ecommerce_sales (platform, product_id) WHERE product_id IS NULL;

-- 3) Mapping รหัสสินค้าแพลตฟอร์ม (Shopee item_id) → รหัสสินค้าในระบบ
CREATE TABLE IF NOT EXISTS ecommerce_product_map (
  id                     UUID PRIMARY KEY,
  platform               TEXT NOT NULL DEFAULT 'shopee',
  platform_item_id       TEXT NOT NULL,
  product_id             TEXT REFERENCES products(id) ON DELETE CASCADE,
  platform_product_name  TEXT,
  created_at             TIMESTAMPTZ DEFAULT now(),
  UNIQUE (platform, platform_item_id)  -- ใช้เป็น on_conflict ใน db.upsert_ecommerce_product_map
);

-- ตารางกลุ่มนี้ใช้ SUPABASE_KEY ตัวเดียวจากแอป ไม่มี auth ต่อผู้ใช้ ต้องปิด RLS
-- เหมือน box_presets/commission_records/company_info ไม่งั้น insert จะโดนบล็อก (error 42501)
ALTER TABLE ecommerce_shops DISABLE ROW LEVEL SECURITY;
ALTER TABLE ecommerce_sales DISABLE ROW LEVEL SECURITY;
ALTER TABLE ecommerce_product_map DISABLE ROW LEVEL SECURITY;
