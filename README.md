# He thong quan ly chi tieu ca nhan co tich hop AI

Ung dung web quan ly thu chi ca nhan, ngan sach va muc tieu tiet kiem. He thong co khu vuc nguoi dung va quan tri vien; chatbot co the dung Gemini, OpenAI-compatible API hoac che do xu ly noi bo. Khi goi AI ben ngoai, he thong gui cau hoi va context tai chinh can thiet cua tai khoan den provider da cau hinh.

## Muc tieu

- Ghi nhan va theo doi thu nhap, chi tieu theo danh muc.
- Quan sat tinh hinh tai chinh thang tren dashboard.
- Quan ly ngan sach theo danh muc va nhan canh bao khi chi tieu cao.
- Theo doi muc tieu tiet kiem, nap tien, nhan thong bao tien do/hoan thanh.
- Ho tro phan tich tai chinh, goi y ngan sach va hoi dap bang chatbot.
- Phan quyen ro rang giua nguoi dung va quan tri vien.

## Cong nghe su dung

| Thanh phan | Cong nghe trong source |
| --- | --- |
| Backend | Python, FastAPI, Uvicorn |
| ORM va database | SQLAlchemy; SQLite hoac MySQL qua PyMySQL |
| Xac thuc | JWT (`python-jose`), OAuth2 password flow, Passlib/bcrypt |
| AI chatbot | Google Gen AI SDK (`google-genai`), Gemini API va OpenAI-compatible API |
| HTTP client | httpx |
| Validation/cau hinh | Pydantic, python-dotenv |
| Frontend | HTML, CSS, JavaScript vani, Chart.js, Font Awesome |
| Xuat phan hoi chat | TXT hoac PDF qua ReportLab |

## Yeu cau moi truong

- Python **3.10 tro len**; khuyen nghi Python 3.12 cho bo dependency hien tai. Ma nguon dung cu phap type union `str | None`.
- `pip` va virtual environment.
- SQLite khong can cai dat them; MySQL 8+ la tuy chon.
- Ket noi Internet de tai cac tai nguyen giao dien tu CDN (Bootstrap, Chart.js, Font Awesome, Google Fonts va Confetti); API key chi can neu chon Gemini/OpenAI.

Thu vien duoc khai bao trong [requirements.txt](requirements.txt):

```text
fastapi, uvicorn[standard], sqlalchemy, pymysql, cryptography,
python-jose[cryptography], passlib[bcrypt], bcrypt, python-multipart,
python-dotenv, httpx, pydantic, pydantic-settings, email-validator,
google-genai, tzdata, reportlab
```

## Cai dat va chay

### 1. Lay source va tao moi truong ao

```powershell
git clone https://github.com/dtc245200886-dotcom/HeThongQuanLyChiTieu.git
cd HeThongQuanLyChiTieu
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Tren macOS/Linux, dung cac lenh tuong duong:

```bash
git clone https://github.com/dtc245200886-dotcom/HeThongQuanLyChiTieu.git
cd HeThongQuanLyChiTieu
python3.12 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

Neu doi phien ban Python hoac chuyen thu muc du an sang may khac, hay tao lai `venv`; virtual environment khong nen sao chep/tai su dung giua cac phien ban Python.

Neu dung VS Code, cai extension **Python** cua Microsoft, mo Command Palette (`Ctrl+Shift+P`), chon **Python: Select Interpreter**, roi chon `.\venv\Scripts\python.exe`.

### 2. Cau hinh `.env`

Tao file `.env` tu mau:

```powershell
Copy-Item .env.example .env
```

Tren macOS/Linux, dung `cp .env.example .env`.

Khong commit `.env`. File nay chua database URL, JWT secret, mat khau admin va API key.

Cau hinh SQLite de chay nhanh:

```dotenv
DATABASE_URL=sqlite:///./chi_tieu_ai.db
SECRET_KEY=replace-with-a-unique-random-secret-at-least-32-characters
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

AI_PROVIDER=mock

ADMIN_EMAIL=admin@gmail.com
ADMIN_PASSWORD=replace-with-a-unique-password-12-characters-or-more
ADMIN_NAME=Quan tri vien
```

Che do `mock` khong can API key va dung du lieu noi bo. De bat Gemini, dat `AI_PROVIDER=gemini`, `GEMINI_API_KEY` va tuy chon `GEMINI_MODEL`; de bat OpenAI-compatible API, dat `AI_PROVIDER=openai`, `OPENAI_API_KEY` va tuy chon `OPENAI_MODEL`/`OPENAI_BASE_URL`.

Truoc khi deploy, dat `APP_ENV=production`, `APP_BASE_URL` bang URL HTTPS cong khai, tao `SECRET_KEY` rieng dai it nhat 32 ky tu va dat mat khau admin rieng dai it nhat 12 ky tu, gom chu va so. Ung dung se tu choi khoi dong neu `SECRET_KEY`/`ADMIN_PASSWORD` thieu, qua yeu hoac dung mot so gia tri mau/mac dinh da biet. CORS trong source hien tai cho phep moi origin; khong nen dua len production cong khai truoc khi gioi han CORS theo domain thuc te.

Cau hinh MySQL thay cho SQLite:

```sql
CREATE DATABASE chi_tieu_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

```dotenv
DATABASE_URL=mysql+pymysql://DB_USER:DB_PASSWORD@127.0.0.1:3306/chi_tieu_ai?charset=utf8mb4
```

Thay `DB_USER` va `DB_PASSWORD` bang thong tin MySQL; neu mat khau co ky tu dac biet trong URL, hay URL-encode truoc khi dat vao `DATABASE_URL`.

Khi khoi dong, ung dung tu tao cac bang SQLAlchemy, bo sung mot so cot qua runtime migration va seed admin/danh muc mac dinh neu can. Cac file SQL trong `migrations/` la script MySQL de tham khao/ap dung thu cong; ung dung khong tu dong chay cac file nay.

### 3. Chay ung dung

```powershell
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

| Dia chi | Noi dung |
| --- | --- |
| `http://127.0.0.1:8000/login` | Dang nhap va dang ky |
| `http://127.0.0.1:8000/` | Ung dung nguoi dung |
| `http://127.0.0.1:8000/admin` | Trang quan tri |
| `http://127.0.0.1:8000/docs` | Swagger UI cua FastAPI |

Khong mo truc tiep cac file HTML bang `file://`; frontend can duoc phuc vu boi FastAPI de goi API cung origin.

## Tai khoan mac dinh

Tai khoan admin mac dinh duoc tao khi khoi dong neu email trong `ADMIN_EMAIL` chua ton tai:

| Vai tro | Email mac dinh | Mat khau mac dinh |
| --- | --- | --- |
| Admin | `admin@gmail.com` | `admin123` |

Bang tren chi ap dung khi khong dat `ADMIN_EMAIL`/`ADMIN_PASSWORD` trong `.env`. Neu dung `.env.example`, hay thay cac gia tri mau truoc khi chay. Hay doi mat khau truoc khi deploy. Neu email da ton tai trong database duoi vai tro user, ung dung khong tu dong nang quyen tai khoan do thanh admin. Mat khau trong `.env` chi duoc dung khi tao admin lan dau; thay bien nay khong doi mat khau cua tai khoan da ton tai. Source khong seed tai khoan user mau; nguoi dung thuong tu dang ky tai `/login`.

## Chuc nang hien co

### Tai khoan va bao mat

- Dang ky tai khoan user voi mat khau toi thieu 6 ky tu, gom chu va so, toi da 72 byte UTF-8; he thong seed danh muc mac dinh cho user moi.
- Dang nhap JWT; cap nhat ho ten/avatar URL; doi mat khau. Mat khau khi doi hoac dat lai can toi thieu 8 ky tu, gom chu va so, toi da 72 byte UTF-8.
- Dat lai mat khau bang lien ket mot lan, het han sau 15 phut; email duoc gui qua SMTP, database chi luu SHA-256 hash cua token va token khong duoc tra trong response API.
- Chon 5 lan dang nhap sai se khoa tam thoi 5 phut; admin co the khoa/mo khoa tai khoan.

De bat chuc nang quen mat khau, cau hinh `APP_BASE_URL`, `SMTP_HOST`, `SMTP_FROM_EMAIL` va thong tin SMTP trong `.env`. Mac dinh su dung STARTTLS tren cong 587; co the bat `SMTP_USE_SSL=true` cho SMTP SSL va tat `SMTP_USE_TLS`. Neu dung SMTP authentication, phai dat ca `SMTP_USERNAME` va `SMTP_PASSWORD`, dong thoi bat TLS hoac SSL. Production bat buoc dung `APP_BASE_URL` HTTPS. Khi cau hinh SMTP con thieu/khong hop le, API tra loi 503 truoc khi tao token reset; neu gui email that bai, token vua tao bi vo hieu hoa.

Vi du cau hinh SMTP (thay cac gia tri mau bang thong tin nha cung cap email):

```dotenv
APP_BASE_URL=http://127.0.0.1:8000
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=your_smtp_username
SMTP_PASSWORD=your_smtp_password
SMTP_FROM_EMAIL=no-reply@example.com
SMTP_USE_TLS=true
SMTP_USE_SSL=false
```

| Bien tuy chon | Mac dinh | Ghi chu |
| --- | --- | --- |
| `GEMINI_MODEL` / `OPENAI_MODEL` | `gemini-3.5-flash-lite` / `gpt-4o-mini` | Gia tri mac dinh trong source; can chon model con duoc provider ho tro. |
| `GEMINI_TIMEOUT_SECONDS` / `OPENAI_TIMEOUT_SECONDS` | `30` / `30` | Thoi gian cho request AI. |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1/chat/completions` | Endpoint OpenAI-compatible. |
| `SMTP_PORT` / `SMTP_TIMEOUT_SECONDS` | `587` / `10` | Port va timeout gui email; dung port cua nha cung cap SMTP. |
| `SMTP_USE_TLS` / `SMTP_USE_SSL` | `true` / `false` | Chi bat mot che do; tai khoan SMTP co mat khau bat buoc dung TLS/SSL. |
| `MAX_CHAT_MESSAGES` / `MAX_CHAT_TOKENS` | `100` / `50000` | Gioi han moi hoi thoai; token la uoc tinh tu do dai van ban (xap xi 4 ky tu/token), khong phai tokenizer cua model. |

### Du lieu tai chinh

- CRUD danh muc thu/chi; khong cho doi loai/xoa danh muc da co giao dich hoac ngan sach.
- CRUD giao dich, tim kiem ghi chu, loc theo loai/danh muc/khoang ngay, sap xep va phan trang.
- CRUD ngan sach theo danh muc, thang va nam.
- CRUD muc tieu tiet kiem, nap tien, tinh tien do, so tien con thieu va so tien vuot muc tieu.
- Dashboard thang: tong thu, tong chi, so du, ty le tiet kiem, bieu do theo danh muc va theo thang.
- So sanh chi tieu giua hai thang qua API `/api/stats/compare`.

So tien hien duoc luu bang kieu floating-point (`Float`), khong phai so thap phan chinh xac. Voi ung dung tai chinh can do chinh xac cao, nen lap ke hoach migration sang `Decimal`/`Numeric` truoc khi su dung du lieu cho doi soat ke toan.

### Thong bao

- Canh bao ngan sach tai nguong 80%, 90% va vuot ngan sach khi them hoac cap nhat giao dich chi.
- Moi lan nap tien vao muc tieu tao notification cap nhat; chi lan dau dat/vuot muc tieu moi tao thong bao hoan thanh, cac lan nap sau khong lap lai thong bao chuc mung.
- Notification luu trong bang `notifications`; timestamp notification moi dung gio Viet Nam (`Asia/Ho_Chi_Minh`) va UI hien thi `HH:mm:ss DD/MM/YYYY`. API chi hien thi toi da 100 thong bao moi nhat.
- Xem, danh dau da doc, danh dau tat ca da doc, xoa tung notification hoac xoa tat ca.

### Chuc nang AI va phan tich

- **Bao cao tai chinh:** tao bao cao thu/chi theo thang tu database; luu lich su generation va report.
- **Goi y ngan sach:** voi moi danh muc, lay tong chi chia cho so thang co bat ky giao dich chi nao, cong 10% du phong va dua ra canh bao ngan sach hien tai. Logic nay chay cuc bo tren du lieu database.
- **Du doan muc tieu:** tinh tien con thieu va, neu co deadline, so tien can nap theo ngay/thang. Logic nay hien tai chay cuc bo.
- **Chatbot:** luu hoi thoai; khi chon Gemini/OpenAI, gui cau hoi va context tai chinh can thiet den provider tuong ung. Che do `mock` xu ly noi bo. Chat ho tro text; phan tich anh JPG/PNG toi da 10 MB chi hoat dong voi Gemini. Moi hoi thoai gioi han mac dinh 100 tin nhan va 50.000 token uoc tinh (4 ky tu/token); chi 12 tin nhan truoc gan nhat duoc gui lam lich su cho model.
- **Quan ly chat:** xem/xoa hoi thoai, danh gia phan hoi, tai phan hoi dang TXT hoac PDF. PDF hien tai dung font co san va co the mat dau/thay ky tu khong ho tro; dung TXT neu can giu nguyen tieng Viet.

### Provider AI, fallback va quota

Chatbot dung `AI_PROVIDER=gemini` de goi Gemini qua `google-genai` va `GEMINI_MODEL`, hoac `AI_PROVIDER=openai` de goi OpenAI-compatible API voi `OPENAI_API_KEY` va `OPENAI_MODEL`. Co the dat `OPENAI_BASE_URL` de dung endpoint tuong thich Chat Completions khac; `AI_API_KEY` van duoc chap nhan lam ten key cu neu chua dat `OPENAI_API_KEY`. `AI_PROVIDER=mock` (mac dinh) xu ly noi bo, khong goi API ben ngoai. Endpoint `GET /api/ai/status` chi kiem tra cau hinh, khong goi nha cung cap AI va khong xac nhan ket noi/quota.

Khi provider AI ben ngoai tra loi thanh cong, response chat co `source: "AI"`. `AI_PROVIDER=mock` luon tra loi bang du lieu noi bo va co `source: "Fallback"` (day la hanh vi binh thuong, khong phai loi). Khi Gemini/OpenAI loi credential, model, mang, dich vu hoac quota, `services/chat_service.py` cung fallback sang du lieu tai chinh noi bo cua dung user va tra `source: "Fallback"`. Chat cua admin chi dung so lieu tong hop he thong; UI hien thi nguon AI hoac du lieu noi bo. Bao cao, goi y ngan sach va du doan muc tieu hien duoc tinh noi bo, response ghi `provider: "local"`.

Parser thoi gian trong chatbot chi nhan dien cac khoang `hom nay`, `tuan nay`, `nam nay`; cac cach hoi thoi gian khac mac dinh duoc tinh theo thang hien tai. `429 RESOURCE_EXHAUSTED` la loi quota/rate limit Gemini. Service phan loai loi nay la `quota_or_rate_limit`; chatbot se fallback thay vi dung toan bo luong. Kiem tra quota/billing cua project Gemini, doi model co quota phu hop, hoac thu lai sau thoi gian Google yeu cau. De thu ket noi that, chay lenh kiem tra Gemini trong [QUICKSTART.md](QUICKSTART.md); endpoint status khong tao request AI tinh phi. Fallback chi co du lieu tai chinh, nen cau hoi ngoai pham vi nhu phep tinh co the nhan tong thu/chi thay vi dap an tong quat khi Gemini khong san sang.

### Quan tri vien

- Xem tong hop user, giao dich, tong thu/chi, thong ke AI va loai database dang dung.
- Tim kiem user, khoa/mo khoa, thay doi vai tro, xoa user; khong the tu khoa, tu doi vai tro hoac tu xoa tai khoan dang dung, va he thong bao ve admin dang hoat dong cuoi cung.
- Xem danh muc mac dinh, system log va AI log metadata.
- Admin khong co endpoint xem chi tiet giao dich, ngan sach, muc tieu hay noi dung chat cua user khac.

## Huong dan su dung

### 1. Dang nhap

1. Mo `/login`.
2. Dang ky neu chua co tai khoan; hoac dang nhap bang tai khoan da co.
3. Dung tai khoan admin de vao `/admin`; user thuong vao dashboard.

### 2. Them giao dich

1. Mo **Giao dich**.
2. Chon them giao dich, chon danh muc phu hop voi loai thu/chi.
3. Nhap so tien, ngay va ghi chu, sau do luu.
4. Neu giao dich chi lam ngan sach dat 80% tro len, kiem tra chuong thong bao.

### 3. Tao ngan sach

1. Mo **Ngan sach**.
2. Chon danh muc chi, thang/nam va gioi han ngan sach.
3. Luu ngan sach, sau do ghi nhan giao dich chi vao dung danh muc de theo doi muc su dung.

### 4. Tao va nap tien cho muc tieu

1. Mo **Muc tieu**, tao muc tieu voi ten, so tien muc tieu, so tien hien co va deadline tuy chon.
2. Bam **Nap tien** tren muc tieu, nhap so tien cong them.
3. He thong tao notification cap nhat tien do. Khi dat/vuot muc tieu, thong bao hoan thanh hien tren chuong.

### 5. Xem dashboard

1. Mo **Dashboard**.
2. Xem so lieu thang hien tai, bieu do chi theo danh muc, bieu do thu/chi/tiet kiem theo thang, ngan sach va muc tieu.

### 6. Su dung chatbot AI

1. Mo **Hoi dap AI**.
2. Dat cau hoi ve thu chi, danh muc, ngan sach hoac muc tieu; co the dinh kem JPG/PNG.
3. Giao dien hien nhan `AI` neu provider tra loi; neu khong, hien `Du lieu noi bo`. API con tra `source: "System"` cho fallback trong chatbot admin.
4. Mo lich su hoi thoai de xem lai, danh gia phan hoi hoac tai TXT/PDF.

### 7. Xem bao cao va goi y

1. Mo **Bao cao AI**, chon thang/nam de tao bao cao tu du lieu giao dich.
2. Mo **Goi y ngan sach** de nhan de xuat dua tren lich su chi tieu.
3. Xem/xoa lich su bao cao va goi y da luu trong phan AI.

## Cau truc thu muc

Cay duoi day doi chieu theo thu muc source hien tai. Ten thu muc local la `Hệ thống quản lí chi tiêu`; khi clone repository bang lenh o tren, Git tao thu muc `chi-tieu-ai`. `.git/` la metadata cua Git nen khong hien trong cay. Cac muc danh dau **local** khong duoc commit va duoc `.gitignore` bo qua; tren may moi, `.env`, database va `.venv/` chi xuat hien sau khi duoc tao.

```text
Hệ thống quản lí chi tiêu/ (project root)
├── .venv/                    # local: Python virtual environment
├── migrations/
│   ├── 001_mysql_chat.sql
│   ├── 002_login_bruteforce.sql
│   ├── 003_password_reset.sql
│   ├── 004_notification_type.sql
│   └── 005_ai_logs_details.sql
├── repositories/
│   ├── __init__.py
│   └── chat_repository.py    # Truy cap du lieu hoi thoai
├── services/
│   ├── __init__.py
│   ├── ai_service.py         # Adapter REST Gemini legacy
│   ├── chat_service.py       # Context tai chinh, fallback, luu hoi thoai
│   ├── financial_analyzer.py # Tong hop facts tai chinh cho chat
│   ├── gemini_service.py     # Gemini text/vision, retry va phan loai loi
│   ├── openai_service.py     # Adapter OpenAI-compatible
│   ├── password_reset_email.py # Gui email reset mat khau qua SMTP
│   ├── prompt_builder.py     # Tao prompt chat
│   ├── question_parser.py    # Nhan dien khoang thoi gian cau hoi
│   └── response_validator.py # Kiem tra phan hoi AI
├── static/
│   ├── admin.html            # Giao dien admin
│   ├── app.js                # API helper, session va UI dung chung
│   ├── index.html            # Giao dien user
│   ├── login.html            # Dang nhap, dang ky, reset password
│   ├── style.css             # Style chinh
│   └── theme-overrides.css   # Tuy chinh giao dien
├── tests/
│   └── test_project_audit.py # Kiem thu cac luong va gioi han dau vao quan trong
├── .env                      # local: secret va cau hinh rieng
├── .env.example              # Mau bien moi truong, khong chua secret that
├── .gitignore                # Bo qua secrets, database va file tao tu dong
├── chi_tieu_ai.db            # local: SQLite database
├── database.py               # Engine/session SQLite hoac MySQL
├── main.py                   # FastAPI routes, auth, CRUD, stats, admin
├── models.py                 # SQLAlchemy models va timestamp notification VN
├── QUICKSTART.md             # Cac buoc khoi dong nhanh tren may local
├── README.md                 # Tai lieu chinh: cai dat, chuc nang va xu ly loi
├── requirements.txt          # Python dependencies
```

`.env`, `chi_tieu_ai.db`, `.venv/` va `__pycache__/` la cac tep/thu muc local,
duoc bo qua trong Git va co the chua/xuat hien khac nhau tren tung may. Khong xoa
`.env` hoac database neu dang su dung; database chua tai khoan va du lieu thu chi.

## Chay kiem thu

Tu thu muc goc, chay bo kiem thu bang Python co san:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Bo kiem thu dung SQLite tam va tu don dep sau khi chay.
Tren macOS/Linux, co the chay bang `python -m unittest discover -s tests -v`.

## Xu ly loi thuong gap

| Hien tuong | Nguyen nhan va cach xu ly |
| --- | --- |
| Khong co `.env` hoac app dung config mac dinh | Copy `.env.example` thanh `.env`, dien `DATABASE_URL`, `SECRET_KEY` va thong tin admin. Khoi dong lai Uvicorn sau khi sua bien moi truong. |
| Khong ket noi database | Kiem tra `DATABASE_URL`, MySQL co dang chay, user/password/database ton tai. Co the doi tam sang `sqlite:///./chi_tieu_ai.db`. |
| PowerShell khong cho kich hoat `.venv` | Trong cua so hien tai, chay `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, sau do kich hoat lai virtual environment. |
| `ModuleNotFoundError` | Kich hoat `.venv` va chay `python -m pip install -r requirements.txt`. |
| `No time zone found with key Asia/Ho_Chi_Minh` | Cai lai dependencies; `tzdata` da co trong requirements de ho tro Windows. |
| Gemini bao `401`/`403` | Kiem tra `GEMINI_API_KEY` la mot key hop le, khong co khoang trang/key noi chuoi; tao key moi neu key da bi thu hoi. |
| Gemini bao `404 NOT_FOUND` | Model trong `GEMINI_MODEL` khong kha dung cho tai khoan. Dung model ma Gemini API thong bao ho tro; `gemini-3.5-flash-lite` chi la gia tri mac dinh trong source, khong dam bao model con duoc provider cung cap. |
| Gemini bao `429 RESOURCE_EXHAUSTED` | Da cham quota/rate limit. Kiem tra quota/billing, doi model hoac doi cho Google cho phep retry; chatbot se tra fallback du lieu noi bo trong luc nay. |
| OpenAI-compatible API loi | Kiem tra `AI_PROVIDER=openai`, API key, model va `OPENAI_BASE_URL`; endpoint can ho tro dinh dang Chat Completions ma service su dung. |
| Quen mat khau khong gui email | Kiem tra `APP_BASE_URL`, `SMTP_HOST`, `SMTP_FROM_EMAIL`, cong SMTP, TLS/SSL va cap username/password. Xem log Uvicorn; email loi thi token reset bi vo hieu hoa. |
| Chatbot co `source=Fallback` | Neu `AI_PROVIDER=mock` thi day la hanh vi binh thuong. Neu dang chon Gemini/OpenAI, kiem tra log Uvicorn, API key va model, sau do goi `GET /api/ai/status` khi da dang nhap; status chi xac nhan cau hinh, khong kiem tra quota/ket noi that. |
| Trang khong mo duoc hoac API loi | Chay Uvicorn va mo `http://127.0.0.1:8000`, khong double-click HTML bang `file://`. |

## Bao mat khi dua len GitHub

- Khong commit `.env`, `chi_tieu_ai.db`, `.venv/` hoac `__pycache__/`.
- Thu hoi va thay API key neu key tung xuat hien trong commit, screenshot hoac log chia se.
- Dung secret manh cho `SECRET_KEY` va doi `ADMIN_PASSWORD` mac dinh truoc khi deploy.
- Gioi han CORS theo domain cua ung dung truoc khi public; source hien tai cho phep moi origin.
- Cau hinh reverse proxy/web server de gioi han kich thuoc request upload; gioi han 10 MB trong route chi ap dung khi request da den handler.

## Ket luan

He thong cung cap mot luong quan ly tai chinh ca nhan tu ghi nhan giao dich, ngan sach va muc tieu den dashboard, notification va khu vuc admin. Chatbot co the dung provider Gemini/OpenAI-compatible hoac xu ly noi bo; fallback du lieu tai chinh giup mot so cau hoi co ban van duoc ho tro khi provider ben ngoai khong san sang.
