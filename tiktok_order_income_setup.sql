-- ตารางเก็บยอดขายสุทธิระดับออเดอร์ของ TikTok Shop — นำเข้าจากไฟล์ "income_*.xlsx"
-- (ชีต "รายละเอียดคำสั่งซื้อ") export จาก TikTok Shop Seller Center (การเงิน > รายได้)
-- เทียบเท่า Shopee "Income" / Lazada "Income Overview" แต่เป็นระดับออเดอร์ล้วนๆ
-- (ไม่มีราคาต่อ SKU ในไฟล์นี้ เลยแบ่งยอดลงแต่ละสินค้าแบบ Shopee/Lazada ไม่ได้ — ดู
-- คอลัมน์ product_summary เป็นแค่ข้อความอ้างอิงดิบ "SKU_ID * จำนวน;" ไม่ใช่ข้อมูลโครงสร้าง)

CREATE TABLE IF NOT EXISTS tiktok_order_income (
  id                            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  shop_name                     TEXT NOT NULL DEFAULT 'zhulian.shop',
  order_id                      TEXT NOT NULL UNIQUE,  -- "หมายเลขคำสั่งซื้อ/การปรับ" — ใช้เป็น on_conflict ตอน upsert
  transaction_type              TEXT,                   -- ประเภทธุรกรรม (เช่น "คำสั่งซื้อ")
  order_created_at              DATE,
  order_paid_at                 DATE,
  currency                      TEXT,
  net_settlement                NUMERIC DEFAULT 0,  -- "จำนวนเงินที่ชำระทั้งหมด" = ยอดสุทธิที่ร้านได้รับจริง
                                                       -- (ยืนยันจากข้อมูลจริงแล้วว่า = gross_revenue + total_fees)
  gross_revenue                 NUMERIC DEFAULT 0,  -- รายได้รวม (ก่อนหักค่าธรรมเนียม)
  product_subtotal_after_disc   NUMERIC DEFAULT 0,  -- ยอดรวมค่าสินค้าหลังหักส่วนลดจากผู้ขาย
  total_fees                    NUMERIC DEFAULT 0,  -- ค่าธรรมเนียมทั้งหมด (เป็นค่าลบ)
  tiktok_commission             NUMERIC DEFAULT 0,  -- ค่าคอมมิชชั่น TikTok Shop
  affiliate_commission          NUMERIC DEFAULT 0,  -- ค่าคอมมิชชั่นแอฟฟิลิเอต (อ้างอิงเทียบกับ tiktok_affiliate_orders ได้)
  shipping_fee_paid_by_shop     NUMERIC DEFAULT 0,  -- ยอดรวมค่าจัดส่งที่ร้านค้าจ่ายจริง
  product_summary               TEXT,                -- "รายละเอียดสินค้าที่ขายได้" ดิบๆ ("SKU_ID * qty;") — อ้างอิงเท่านั้น ไม่ parse
  created_at                    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tiktok_order_income_date ON tiktok_order_income (order_created_at);

-- ตารางนี้สร้างผ่าน SQL Editor โดยไม่มี auth ผู้ใช้ต่อคน (แอปใช้ SUPABASE_KEY ตัวเดียว)
-- ต้องปิด RLS เหมือนตาราง TikTok/E-commerce อื่นๆ ไม่งั้น insert จะถูกบล็อก
ALTER TABLE tiktok_order_income DISABLE ROW LEVEL SECURITY;
