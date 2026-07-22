-- แก้ปัญหา "new row violates row-level security policy for table shipments"
-- ตารางนี้ถูกเปิด RLS ไว้ (ค่า default ตอนสร้างผ่าน Table Editor) แต่ไม่มี policy ให้สิทธิ์เลย
-- ปิด RLS ให้เหมือนตารางอื่น ๆ ในระบบ (แอปนี้ใช้ SUPABASE_KEY ตัวเดียว ไม่มีระบบ auth ผู้ใช้)

alter table shipments disable row level security;
