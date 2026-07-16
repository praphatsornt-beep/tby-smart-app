-- เก็บค่าจัดส่งที่ Shopee หักจริงต่อออเดอร์ (จากไฟล์ Income คอลัมน์ "ค่าจัดส่ง
-- ที่ Shopee ชำระโดยชื่อของคุณ") ไว้เทียบกับค่าส่งที่ควรจะเป็นตามน้ำหนักสินค้า
ALTER TABLE ecommerce_order_income ADD COLUMN IF NOT EXISTS shipping_fee_charged NUMERIC DEFAULT 0;
