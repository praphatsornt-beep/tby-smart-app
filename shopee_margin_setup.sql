-- เฟส 4: Shopee margin จริง + มูลค่าเงินจมในสต็อก
-- ต่อยอดจาก ecommerce_setup.sql เดิม (ตาราง ecommerce_sales ยังว่างอยู่ไม่มีข้อมูลจริง
-- แก้ schema เพิ่มได้อย่างปลอดภัย ไม่กระทบข้อมูล)

-- 1) ต้นทุนสินค้า — ใช้คำนวณกำไรทั้งฝั่งหน้าร้านและ Shopee ในอนาคต
ALTER TABLE products ADD COLUMN IF NOT EXISTS cost_price NUMERIC DEFAULT 0;

-- 2) คอลัมน์เพิ่มเติมระดับรายการสินค้า มาจากรายงาน "Order.all" export ของ Shopee
--    (สถานะออเดอร์/คืนสินค้า, เลขพัสดุ+ขนส่ง, ส่วนแบ่งยอดโอนสุทธิที่เฉลี่ยมาจาก
--    รายงาน Income ตามสัดส่วนราคาขายในออเดอร์เดียวกัน)
ALTER TABLE ecommerce_sales ADD COLUMN IF NOT EXISTS order_status TEXT;
ALTER TABLE ecommerce_sales ADD COLUMN IF NOT EXISTS return_status TEXT;
ALTER TABLE ecommerce_sales ADD COLUMN IF NOT EXISTS returned_qty NUMERIC DEFAULT 0;
ALTER TABLE ecommerce_sales ADD COLUMN IF NOT EXISTS tracking_no TEXT;
ALTER TABLE ecommerce_sales ADD COLUMN IF NOT EXISTS carrier_name TEXT;
ALTER TABLE ecommerce_sales ADD COLUMN IF NOT EXISTS net_amount NUMERIC DEFAULT 0;

-- 3) ยอดเงินโอนสุทธิต่อออเดอร์ — มาจากรายงาน "Income" export ของ Shopee (คนละไฟล์
--    กับ Order.all ไม่มี SKU/สินค้า มีแค่ยอดสุทธิหลังหักค่าธรรมเนียม/ค่าส่ง/ภาษีทั้งหมดแล้ว)
CREATE TABLE IF NOT EXISTS ecommerce_order_income (
  order_sn      TEXT PRIMARY KEY,
  platform      TEXT NOT NULL DEFAULT 'shopee',
  shop_name     TEXT NOT NULL,
  net_amount    NUMERIC NOT NULL DEFAULT 0,
  transfer_date DATE,
  created_at    TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE ecommerce_order_income DISABLE ROW LEVEL SECURITY;
