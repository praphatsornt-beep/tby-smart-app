-- เพิ่มเติมจาก shopee_margin_setup.sql/2 — เก็บชื่อสินค้าจาก Shopee ไว้ด้วย
-- (ไม่ใช่แค่เลข SKU ดิบๆ) ให้หน้า Map สินค้า (ecom_ui.py ข้อ 6) โชว์ชื่อ
-- ประกอบให้ผู้ใช้ map ได้ง่ายขึ้น ไม่ต้องเดาว่าเลขไหนคือสินค้าอะไร
ALTER TABLE ecommerce_sales ADD COLUMN IF NOT EXISTS item_name TEXT;
