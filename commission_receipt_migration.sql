-- Migration: เปลี่ยนจาก "หนังสือรับรองหักภาษี ณ ที่จ่าย (50 ทวิ)" เป็น "ใบเสร็จรับเงิน/ใบกำกับภาษี"
-- รันใน Supabase SQL editor หลังจาก commission_setup.sql

-- เลขที่/เล่มที่ใบเสร็จ + วันที่ออกใบเสร็จ
alter table commission_records
  add column if not exists receipt_book_no text,
  add column if not exists receipt_seq integer,
  add column if not exists receipt_date date;

-- เลิกใช้ฟิลด์ใบหัก ณ ที่จ่าย (50 ทวิ) — เอกสารนี้ HQ เป็นผู้ออกให้เรา ไม่ใช่ที่แอปต้องสร้าง
alter table commission_records
  drop column if exists wht_doc_no,
  drop column if exists wht_issued,
  drop column if exists wht_issue_date;

-- เบอร์โทร/แฟกซ์ ของเรา สำหรับพิมพ์หัวใบเสร็จ
alter table company_info
  add column if not exists our_tel text;
