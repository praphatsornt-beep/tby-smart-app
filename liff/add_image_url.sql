-- เพิ่มคอลัมน์ image_url ในตาราง products
alter table products add column if not exists image_url text;
