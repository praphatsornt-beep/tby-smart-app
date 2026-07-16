-- แก้แนวคิด "ค่าส่งเกิน" ใหม่ — ไม่ใช้น้ำหนักสินค้าเทียบเอง (ข้อมูลน้ำหนักในระบบ
-- อาจไม่แม่นตามจริง ทำให้ false positive) แต่เทียบตัวเลขที่ Shopee รายงานมาเอง:
-- ค่าส่งที่ Shopee ประเมินไว้ล่วงหน้า (ผู้ซื้อจ่าย + Shopee ออกให้) เทียบกับค่าส่ง
-- ที่ขนส่งเรียกเก็บจริงตอนชั่งพัสดุ ถ้าแพงกว่าที่ประเมิน ส่วนต่างจะถูกหักจากร้านเงียบๆ
ALTER TABLE ecommerce_order_income ADD COLUMN IF NOT EXISTS buyer_paid_shipping NUMERIC DEFAULT 0;
ALTER TABLE ecommerce_order_income ADD COLUMN IF NOT EXISTS shopee_subsidized_shipping NUMERIC DEFAULT 0;
