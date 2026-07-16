-- เพิ่มเติมจาก shopee_margin_setup.sql — กันแถวซ้ำตอนอัปโหลดไฟล์ Order.all ซ้ำ
-- (เช่น อัปโหลดไฟล์เดิมซ้ำ หรือช่วงวันที่ export ทับกัน) ให้ upsert ทับแทนที่จะซ้ำ
ALTER TABLE ecommerce_sales
  ADD CONSTRAINT ecommerce_sales_order_item_uniq UNIQUE (platform, order_sn, item_id_platform);
