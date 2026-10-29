
# Quickstart

Tai lieu nay huong dan khoi dong he thong tren may local. Xem [README.md](README.md) de biet day du chuc nang, cau truc va xu ly loi.

## 1. Yeu cau

- Python 3.10 tro len; khuyen nghi Python 3.12 cho bo dependency hien tai.
- `pip` va quyen tao virtual environment.
- MySQL la tuy chon; du an chay duoc voi SQLite.
- Gemini API key la tuy chon; che do `mock` chay chatbot bang du lieu noi bo.

## 2. Tao moi truong va cai thu vien

Mo PowerShell tai thu muc source:

```powershell
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Tren macOS/Linux, tao va kich hoat moi truong `venv` bang cac lenh:

```bash
python3.12 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

Neu doi phien ban Python hoac chuyen thu muc du an sang may khac, hay tao lai `venv`; virtual environment khong nen sao chep/tai su dung giua cac phien ban Python.

Neu PowerShell chan script, chay lenh nay trong cua so PowerShell hien tai, sau do kich hoat lai virtual environment:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 3. Tao va cau hinh `.env`

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env } else { Write-Host ".env da ton tai; giu nguyen cau hinh hien tai." }
```

Dung SQLite de chay local nhanh:

```dotenv
DATABASE_URL=sqlite:///./chi_tieu_ai.db
SECRET_KEY=replace-with-a-unique-random-secret-at-least-32-characters
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

AI_PROVIDER=mock

ADMIN_EMAIL=admin@gmail.com
ADMIN_PASSWORD=replace-with-a-unique-password-12-characters-or-more
ADMIN_NAME=Quan tri vien

# Email dat lai mat khau (bat buoc neu dung quen mat khau)
APP_BASE_URL=http://127.0.0.1:8000
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=your_smtp_username
SMTP_PASSWORD=your_smtp_password
SMTP_FROM_EMAIL=no-reply@example.com
SMTP_USE_TLS=true
SMTP_USE_SSL=false
```

De bat Gemini, doi `AI_PROVIDER=gemini` va dat `GEMINI_API_KEY` (co the tuy chon `GEMINI_MODEL`). Che do `mock` khong can API key va khong goi dich vu ben ngoai.

Neu dung Gmail, dung App Password thay cho mat khau dang nhap thong thuong. `APP_BASE_URL` phai la dia chi web ma nguoi dung truy cap duoc; khi deploy, dung HTTPS. SMTP chua cau hinh thi API quen mat khau tra ve 503.

Truoc khi deploy, dat `APP_ENV=production`, tao `SECRET_KEY` ngau nhien rieng (it nhat 32 ky tu) va dat mat khau admin rieng (it nhat 12 ky tu, gom chu va so). Ung dung se tu choi khoi dong neu cac gia tri production nay bi thieu hoac van dung gia tri mac dinh.

De dung MySQL, tao database truoc:

```sql
CREATE DATABASE chi_tieu_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Sau do dat `DATABASE_URL` trong `.env`:

```dotenv
DATABASE_URL=mysql+pymysql://DB_USER:DB_PASSWORD@127.0.0.1:3306/chi_tieu_ai?charset=utf8mb4
```

Khong commit `.env`, vi file nay chua secret va thong tin ket noi database.

## 4. Chay server

```powershell
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Lan khoi dong dau tien se tao bang database, bo sung cac cot migration runtime, seed admin va danh muc mac dinh he thong.

Mo cac dia chi sau tren trinh duyet:

| Dia chi | Noi dung |
| --- | --- |
| `http://127.0.0.1:8000/login` | Dang nhap, dang ky, reset password |
| `http://127.0.0.1:8000/` | Giao dien user |
| `http://127.0.0.1:8000/admin` | Giao dien admin |
| `http://127.0.0.1:8000/docs` | Swagger API |

Khong double-click cac file HTML va khong dung URL `file://`; phai truy cap qua Uvicorn.

Chay kiem thu tu thu muc goc:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 5. Tai khoan mac dinh

Neu chua ton tai email admin trong database, server tao tai khoan theo `ADMIN_EMAIL` va `ADMIN_PASSWORD` trong `.env`. Neu giu cau hinh mau mac dinh, thong tin la:

```text
Email: admin@gmail.com
Mat khau: admin123
```

Doi mat khau mau truoc khi deploy. Thay `ADMIN_PASSWORD` sau khi tai khoan da duoc tao khong tu dong doi mat khau luu trong database.

## 6. Kiem tra Gemini

Sau khi dat API key va khoi dong lai Uvicorn, dang nhap roi goi:

```text
GET /api/ai/status
```

Endpoint nay chi cho biet provider va API key da duoc cau hinh; no khong goi Gemini va khong kiem tra quota.

Hoac kiem tra tu terminal:

```powershell
py -c "from services.gemini_service import ask_gemini; print(ask_gemini('Reply with OK only.'))"
```

- Neu tra `OK`, Gemini da ket noi.
- `401`/`403`: API key khong hop le hoac khong co quyen.
- `404`: model khong kha dung cho tai khoan; kiem tra `GEMINI_MODEL`.
- `429 RESOURCE_EXHAUSTED`: da het quota/rate limit. Chatbot se chuyen sang fallback du lieu tai chinh noi bo.

## 7. Loi thuong gap

| Hien tuong | Cach xu ly |
| --- | --- |
| `ModuleNotFoundError` | Kich hoat `venv`, chay lai `py -m pip install -r requirements.txt`. |
| Khong ket noi MySQL | Kiem tra server MySQL, database da tao va `DATABASE_URL`; co the chuyen sang SQLite. |
| `No time zone found with key Asia/Ho_Chi_Minh` | Cai lai dependencies de cai `tzdata`. |
| `127.0.0.1 refused to connect` | Chay lai lenh Uvicorn va giu terminal dang chay. |
| Chat co `source=Fallback` | Xem log Uvicorn va `/api/ai/status`; kiem tra API key, model va quota Gemini. |
