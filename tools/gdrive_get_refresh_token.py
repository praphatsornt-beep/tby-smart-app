"""
รัน "ครั้งเดียว" บนเครื่องตัวเอง (ไม่ใช่ GitHub Actions) เพื่อขอ Google OAuth refresh
token ให้ tools/backup_to_drive.py ใช้อัปโหลดไฟล์เข้า Google Drive ของตัวเองอัตโนมัติ
ได้โดยไม่ต้องมีใครนั่งกดยืนยันทุกวัน

pip install google-auth-oauthlib   (ติดตั้งแค่เครื่องตัวเอง ไม่ต้องอยู่ใน requirements
                                     ใด ๆ ของโปรเจกต์ — ใช้ครั้งเดียวจบ)

ขั้นตอนก่อนรันไฟล์นี้:
  1. ไปที่ https://console.cloud.google.com สร้างโปรเจกต์ใหม่ (หรือใช้โปรเจกต์เดิม)
  2. เปิดใช้งาน "Google Drive API": เมนู APIs & Services > Library > ค้นหา
     "Google Drive API" > Enable
  3. ไปที่ APIs & Services > OAuth consent screen — เลือก "External", กรอกชื่อแอป
     อะไรก็ได้ (เช่น "TBY Backup"), อีเมลตัวเอง, บันทึกไปเรื่อย ๆ จนเสร็จ (ไม่ต้อง
     submit for verification เพราะใช้เอง — เพิ่มอีเมลตัวเองใน "Test users" ก็พอ)
  4. ไปที่ APIs & Services > Credentials > Create Credentials > OAuth client ID
     เลือกประเภท "Desktop app" ตั้งชื่ออะไรก็ได้ > Create
  5. คัดลอก Client ID กับ Client Secret ที่ได้ ไปใส่ในไฟล์ .env (ดู .env.example
     ตัวแปร GDRIVE_CLIENT_ID / GDRIVE_CLIENT_SECRET)
  6. สร้างโฟลเดอร์ใน Google Drive ของตัวเองสำหรับเก็บ backup (เช่น "TBY Backups")
     เปิดโฟลเดอร์นั้น คัดลอก ID จาก URL (ส่วนท้ายสุดของ
     drive.google.com/drive/folders/<ID นี้>) ใส่ .env เป็น GDRIVE_FOLDER_ID
  7. รันไฟล์นี้ — เบราว์เซอร์จะเปิดขึ้นมาให้ล็อกอิน Google แล้วกด "อนุญาต"
     (จะมีคำเตือน "Google hasn't verified this app" เพราะเป็นแอปที่เราสร้างเอง
     ไม่ได้ยื่น verify — กด Advanced > Go to (ชื่อแอป) ได้ตามปกติ)
  8. คัดลอก refresh_token ที่พิมพ์ออกมา ไปตั้งเป็น GitHub Secret ชื่อ
     GDRIVE_REFRESH_TOKEN (repo Settings > Secrets and variables > Actions >
     New repository secret) — พร้อมกับ GDRIVE_CLIENT_ID/GDRIVE_CLIENT_SECRET/
     GDRIVE_FOLDER_ID/SUPABASE_URL/SUPABASE_KEY (ค่าเดียวกับใน .env)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main():
    client_config = {
        "installed": {
            "client_id":     os.environ["GDRIVE_CLIENT_ID"],
            "client_secret": os.environ["GDRIVE_CLIENT_SECRET"],
            "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
            "token_uri":     "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)

    if not creds.refresh_token:
        print("\n⚠️ ไม่ได้ refresh_token กลับมา — มักเกิดถ้าเคยอนุญาตแอปนี้ไปแล้วก่อนหน้า "
              "ลองไปที่ myaccount.google.com/permissions เอาแอปนี้ออกก่อน แล้วรันใหม่")
        return

    print("\n✅ ได้ refresh token แล้ว — คัดลอกค่านี้ไปตั้งเป็น GitHub Secret ชื่อ GDRIVE_REFRESH_TOKEN:\n")
    print(creds.refresh_token)
    print()


if __name__ == "__main__":
    main()
