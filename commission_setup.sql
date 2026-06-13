-- ตารางสำหรับฟีเจอร์ ค่าคอมมิชชั่น / ใบหัก ณ ที่จ่าย (50 ทวิ) / เคลม VAT
-- รันใน Supabase SQL editor (ไม่ได้รวมไว้ใน supabase_setup.sql)

-- 1 แถวต่อเดือน (period = 'YYYY-MM')
create table if not exists commission_records (
    period                     text primary key,
    commission_amount          numeric not null default 0,
    wht_rate                    numeric not null default 3,
    wht_amount                  numeric not null default 0,
    net_amount                  numeric not null default 0,
    wht_doc_no                  text,
    wht_issued                  boolean not null default false,
    wht_issue_date              date,
    commission_received         boolean not null default false,
    commission_received_date    date,
    vat_claim_amount             numeric not null default 0,
    vat_claim_doc_issued         boolean not null default false,
    vat_claim_doc_date            date,
    vat_claim_received           boolean not null default false,
    vat_claim_received_date       date,
    notes                       text
);

-- ข้อมูลบริษัท (เรา = ผู้จ่าย/ผู้มีหน้าที่หักภาษี, สำนักงานใหญ่ = ผู้ถูกหักภาษี) — มีแถวเดียว id=1
create table if not exists company_info (
    id            int primary key default 1,
    our_name      text,
    our_tax_id    text,
    our_address   text,
    hq_name       text,
    hq_tax_id     text,
    hq_address    text
);
