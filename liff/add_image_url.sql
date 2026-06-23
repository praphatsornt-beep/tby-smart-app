-- เพิ่มคอลัมน์สำหรับ LIFF ในตาราง products
alter table products add column if not exists image_url text;
alter table products add column if not exists show_in_liff boolean default false;
alter table products add column if not exists name_mm text;
