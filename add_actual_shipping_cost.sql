-- เพิ่มคอลัมน์ actual_shipping_cost ให้ตาราง shipments
-- เก็บยอดที่ iShip คิดจริง (หลังชั่งน้ำหนักจริงที่คลัง — จาก get_shipping_report/"เทียบยอดจริง")
-- แยกจาก shipping_cost เดิมซึ่งเป็นยอดที่ "ประเมิน"/คิดลูกค้าไว้ตอนสร้างรายการ
-- ก่อนหน้านี้ยอดจริงเก็บไว้แค่ใน session_state (_sh_billing_map) เท่านั้น หายทุกครั้งที่
-- เปิด session ใหม่ ทำให้ต้องกดปุ่ม "เทียบยอดจริง" ซ้ำทุกครั้งเพื่อเทียบ — ย้ายมาบันทึกถาวร
alter table shipments add column if not exists actual_shipping_cost numeric(10,2);
