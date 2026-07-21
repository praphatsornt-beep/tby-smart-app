-- ตารางเก็บออเดอร์ TikTok Shop ที่มาจากนายหน้า/ครีเอเตอร์ (affiliate) — นำเข้าจากไฟล์
-- "affiliate_orders_*.xlsx" ที่ export จาก TikTok Shop Seller Center (Affiliate Marketing
-- > Orders). ใช้แท็บ 🛒 E-commerce → 🎥 ค่าคอมนายหน้า TikTok ในแอป

CREATE TABLE IF NOT EXISTS tiktok_affiliate_orders (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  shop_name                 TEXT NOT NULL DEFAULT 'zhulian.shop',
  order_id                  TEXT NOT NULL,
  sku_id                    TEXT NOT NULL,
  product_code              TEXT,
  item_name                 TEXT,
  price                     NUMERIC DEFAULT 0,
  payment_amount            NUMERIC DEFAULT 0,
  currency                  TEXT,
  qty                       NUMERIC DEFAULT 0,
  is_returned               TEXT,
  payment_method            TEXT,
  order_status              TEXT,
  creator_username          TEXT,
  content_type              TEXT,
  content_id                TEXT,
  commission_model          TEXT,
  standard_commission_rate  TEXT,
  commission_base_actual    NUMERIC DEFAULT 0,
  commission_payable_actual NUMERIC DEFAULT 0,   -- ยอดนายหน้า (เงินที่ครีเอเตอร์ได้)
  net_amount                NUMERIC DEFAULT 0,   -- ประมาณการ "ยอดที่เราได้" = payment_amount - commission_payable_actual
                                                   -- (ไม่รวมค่าธรรมเนียม/ค่าคอมโฆษณาอื่นๆ ของ TikTok เอง
                                                   -- เพราะไฟล์นี้ไม่มีข้อมูลนั้น — ใช้ประมาณการคร่าวๆ เท่านั้น)
  order_created_at          TIMESTAMPTZ,
  payment_time              TIMESTAMPTZ,
  delivery_time             TIMESTAMPTZ,
  commission_paid_time      TIMESTAMPTZ,
  billed_in_system          BOOLEAN NOT NULL DEFAULT false,  -- เปิดบิลในระบบซูเลียนแล้วหรือยัง — แก้ได้จาก UI
                                                                -- ไม่ถูก reset ตอนอัปโหลดไฟล์ซ้ำ (ดู
                                                                -- db.upsert_tiktok_affiliate_orders — ไม่ส่งคอลัมน์นี้
                                                                -- ไปตอน upsert เลยไม่ทับค่าที่ผู้ใช้ติ๊กไว้)
  created_at                TIMESTAMPTZ DEFAULT now(),
  UNIQUE (order_id, sku_id)  -- กันซ้ำตอนอัปโหลดไฟล์ที่ช่วงวันทับกัน — ใช้เป็น on_conflict ตอน upsert
);
CREATE INDEX IF NOT EXISTS idx_tiktok_affiliate_orders_creator ON tiktok_affiliate_orders (creator_username);
CREATE INDEX IF NOT EXISTS idx_tiktok_affiliate_orders_date ON tiktok_affiliate_orders (order_created_at);

-- ตารางนี้สร้างผ่าน SQL Editor โดยไม่มี auth ผู้ใช้ต่อคน (แอปใช้ SUPABASE_KEY ตัวเดียว)
-- ต้องปิด RLS เหมือน commission_records/box_presets/ecommerce_* ไม่งั้น insert จะถูกบล็อก
ALTER TABLE tiktok_affiliate_orders DISABLE ROW LEVEL SECURITY;
