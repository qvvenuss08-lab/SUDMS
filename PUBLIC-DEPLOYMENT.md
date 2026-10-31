# เปิด SUDMS บนอินเทอร์เน็ตแบบถาวร

ชุดนี้เตรียมสำหรับ Render Web Service แบบ Docker พร้อม Persistent Disk (ต้องมีบัญชี GitHub และ Render และตรวจสอบค่าใช้จ่ายก่อนสร้างบริการ) ยังไม่มีการสร้างเซิร์ฟเวอร์หรือคิดค่าบริการจากไฟล์นี้

## สิ่งที่จะได้
- ลิงก์ HTTPS ภายใต้ onrender.com เปิดได้จากคอมพิวเตอร์ Android และ iPhone ไม่ต้องเปิดเครื่องคอมพิวเตอร์นี้ทิ้งไว้
- แอดมินเข้าสู่ระบบเดิมที่ /login และจัดการหลังบ้าน /admin ได้
- โค้ดแก้ผ่าน GitHub แล้วสั่ง Deploy ใน Render ด้วยตนเอง (ปิด Auto Deploy ไว้)
- SQLite ไฟล์โครงการ ไฟล์เอกสาร และบันทึกจองห้อง เก็บที่ /var/data/sudms บนดิสก์ถาวร แยกจากโค้ด

## ขั้นตอนนำขึ้นจริง
1. สร้าง repository ส่วนตัวใน GitHub และอัปโหลดเฉพาะ source จาก SUDMS-source.zip ไม่อัปโหลด instance, .env, .venv หรือข้อมูลสำรอง
2. ลงชื่อเข้า Render และเลือก New > Blueprint เชื่อม repository นี้ ตรวจ render.yaml
3. ตรวจราคา Web Service Starter และดิสก์ 2 GB ในหน้าสรุปก่อนยืนยัน ระบบต้องมีดิสก์ถาวร ห้ามใช้ Free Web Service แทนโดยไม่มีการเปลี่ยนการเก็บข้อมูล
4. เมื่อ deploy สำเร็จ Render จะแสดง HTTPS URL ของเว็บ ใช้ /login, /admin และหน้าอื่น ๆ ได้จากทุกเครือข่าย
5. เซิร์ฟเวอร์ใหม่จะยังไม่มีข้อมูลผู้ใช้เดิม ต้องเลือกย้ายข้อมูลเดิมแบบส่วนตัว หรือสร้างแอดมินด้วย Render Shell: python -m flask --app app init-admin ห้ามเปิดฐานข้อมูลหรือไฟล์ SMTP ให้ดาวน์โหลดสาธารณะ
6. ตั้ง SMTP ใน Environment ของ Render ด้วยชื่อ SUDMS_SMTP_HOST, SUDMS_SMTP_PORT, SUDMS_SMTP_USERNAME, SUDMS_SMTP_PASSWORD, SUDMS_SMTP_FROM, SUDMS_SMTP_SECURITY ตามบริการส่งเมลจริง ไม่ใส่ความลับใน GitHub

## ย้ายข้อมูลเดิม
ฐานข้อมูลและไฟล์ instance ต้องย้ายเป็นชุดเดียวกัน ได้แก่ sudms.db, uploads/, project_uploads/, room_booking_uploads/ หยุดรับการแก้ข้อมูลชั่วคราวและสำรอง SQLite ก่อนย้าย การตั้ง SUDMS_SECRET_KEY ใหม่ทำให้ผู้ใช้ต้องเข้าสู่ระบบใหม่ ซึ่งไม่เปลี่ยนรหัสผ่านผู้ใช้ ต้องตรวจจำนวนบัญชี เอกสาร โครงการ และไฟล์ก่อนเปิดใช้งานจริง ข้อมูลเดิมยังไม่ได้ส่งไปที่บริการภายนอก

## เปิดใช้ในเครือข่ายเดียวกัน
เปิด START-SUDMS-NETWORK.cmd หรือ .venv\Scripts\python.exe serve.py --host 0.0.0.0 --port 5057 ระบบจะแสดง IP สำหรับมือถือ ต้องใช้ Wi-Fi/LAN เดียวกันและ Windows Firewall อนุญาตพอร์ต TCP 5057 เครื่องอาจแยกเครือข่ายผู้ใช้ใน Wi-Fi องค์กร

## ไฟล์สำคัญ
serve.py ใช้ Waitress โดยไม่เปิด debugger, Dockerfile เตรียม Python 3.12, render.yaml กำหนดบริการและดิสก์, .dockerignore กันข้อมูลส่วนตัวออกจาก image, SUDMS_INSTANCE_PATH กำหนดที่เก็บข้อมูล, /healthz ตรวจการเชื่อมฐานข้อมูล
