-- รองรับ map SKU ที่เป็น "แพ็ครวม" (เช่น ยาสีฟัน 3 หลอด, กาแฟ 10 ห่อ) — 1 ออเดอร์
-- จริงคือสินค้าเดี่ยวหลายชิ้น ต้องคูณจำนวนตอนคำนวณต้นทุน/สต็อก ไม่ใช่นับเป็น 1 ชิ้น
ALTER TABLE ecommerce_product_map ADD COLUMN IF NOT EXISTS units_per_pack NUMERIC DEFAULT 1;
