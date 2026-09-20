-- สรุปคำสั่งซื้อ+สินค้า/จำนวน ต่อร้าน แบบเรียลไทม์จากอีเมลแจ้งเตือนออเดอร์ของ Shopee
-- (info@mail.shopee.co.th) — ดู ecom_calc.parse_shopee_order_notice_email() และ
-- tools/email_daily_digest.py — คนละตารางกับ ecommerce_return_emails (อันนั้นคือพัสดุตีกลับ)
CREATE TABLE IF NOT EXISTS ecommerce_order_notices (
  id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  platform       TEXT NOT NULL DEFAULT 'shopee',
  shop_name      TEXT,
  order_sn       TEXT NOT NULL,
  order_type     TEXT,                                -- 'cod' | 'transfer'
  status         TEXT NOT NULL DEFAULT 'ยืนยันแล้ว',   -- 'ยืนยันแล้ว' | 'ยกเลิก'
  buyer_name     TEXT,
  order_date     TEXT,                                -- ข้อความดิบจากอีเมล (รูปแบบวันที่ไม่คงที่ ไม่ parse เป็น timestamp)
  total_amount   NUMERIC,
  shipping_fee   NUMERIC,
  items          JSONB,                               -- [{name, variant, qty, price}]
  notice_subject TEXT,
  first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (platform, order_sn)
);

ALTER TABLE ecommerce_order_notices DISABLE ROW LEVEL SECURITY;
