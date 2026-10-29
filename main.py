"""
Hệ thống Quản lý Chi tiêu Cá nhân tích hợp AI
Backend FastAPI + MySQL/SQLite
- JWT auth, phân quyền user/admin
- Admin chỉ xem metadata & tổng hợp, KHÔNG xem giao dịch chi tiết user
- AI: mock local hoặc gọi API ngoài (OpenAI/Gemini) qua AI_API_KEY
"""
import os
import logging
import io
import hashlib
import secrets
from datetime import datetime, date, timedelta
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, status, Query, Request, Response, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field, field_validator
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session
from sqlalchemy import func, inspect, text
from dotenv import load_dotenv
from urllib.parse import quote

from database import engine, get_db, Base, DATABASE_URL
from models import (
    User, Category, Transaction, Budget, SavingGoal,
    AILog, AIGeneration, AIReport, SystemLog, DefaultCategory, ChatConversation, ChatMessage, Notification, ChatFeedback, PasswordResetToken
)
from services.chat_service import answer_chat
from services.gemini_service import GeminiServiceError
from services.password_reset_email import (
    PasswordResetEmailConfigurationError,
    ensure_password_reset_email_configured,
    send_password_reset_email,
)

load_dotenv()

logger = logging.getLogger(__name__)

# ---------- Config ----------
SECRET_KEY = os.getenv("SECRET_KEY") or "dev-secret-key-change-me-in-production-32chars"
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_PROVIDER = os.getenv("AI_PROVIDER", "mock").strip().lower()
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@gmail.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD") or "admin123"
ADMIN_NAME = os.getenv("ADMIN_NAME", "Quản trị viên")
MAX_CHAT_MESSAGES = int(os.getenv("MAX_CHAT_MESSAGES", "100"))
MAX_CHAT_TOKENS = int(os.getenv("MAX_CHAT_TOKENS", "50000"))
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()


def validate_security_config() -> None:
    if APP_ENV not in ("prod", "production"):
        return

    secret_key = os.getenv("SECRET_KEY", "").strip()
    if len(secret_key) < 32 or secret_key in {
        "dev-secret-key-change-me-in-production-32chars",
        "thay-bang-chuoi-bi-mat-dai-va-ngau-nhien",
        "thay-thanh-chuoi-bi-mat-dai-va-ngau-nhien",
        "replace-with-a-unique-random-secret-at-least-32-characters",
    }:
        raise RuntimeError("Production requires a unique SECRET_KEY of at least 32 characters.")

    admin_password = os.getenv("ADMIN_PASSWORD", "")
    if (
        len(admin_password) < 12
        or admin_password in (
            "admin123",
            "replace-with-a-unique-password-12-characters-or-more",
        )
        or not any(char.isalpha() for char in admin_password)
        or not any(char.isdigit() for char in admin_password)
    ):
        raise RuntimeError(
            "Production requires a unique ADMIN_PASSWORD of at least 12 characters, including letters and numbers."
        )


def validate_ai_provider() -> None:
    if AI_PROVIDER not in ("mock", "gemini", "openai"):
        raise RuntimeError("AI_PROVIDER must be one of: mock, gemini, openai.")


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

app = FastAPI(title="Chi tiêu AI API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    messages = []
    for error in exc.errors():
        field = error.get("loc", [""])[-1]
        if field == "email":
            messages.append("Vui lòng nhập đúng địa chỉ email.")
        elif field == "password":
            messages.append("Mật khẩu phải có ít nhất 6 ký tự, gồm chữ và số, tối đa 72 byte UTF-8.")
        elif field == "new_password":
            messages.append("Mật khẩu mới phải có ít nhất 8 ký tự, gồm chữ và số, tối đa 72 byte UTF-8.")
        else:
            messages.append("Dữ liệu nhập chưa hợp lệ.")
    return JSONResponse(status_code=422, content={"detail": " ".join(dict.fromkeys(messages))})

# ---------- Schemas ----------
class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    full_name: str
    email: str


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    full_name: str = Field(..., min_length=2, max_length=150)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return value.strip().lower()

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Họ tên phải có ít nhất 2 ký tự")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Mật khẩu không được vượt quá 72 byte UTF-8")
        if not any(char.isalpha() for char in value) or not any(char.isdigit() for char in value):
            raise ValueError("Mật khẩu phải gồm cả chữ và số")
        return value


class PasswordChangeIn(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Mật khẩu không được vượt quá 72 byte UTF-8")
        if not any(char.isalpha() for char in value) or not any(char.isdigit() for char in value):
            raise ValueError("Mật khẩu mới phải gồm cả chữ và số")
        return value


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str = Field(..., min_length=32, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Mật khẩu không được vượt quá 72 byte UTF-8")
        if not any(char.isalpha() for char in value) or not any(char.isdigit() for char in value):
            raise ValueError("Mật khẩu phải gồm cả chữ và số")
        return value


class ProfileUpdateIn(BaseModel):
    full_name: Optional[str] = Field(None, min_length=2, max_length=150)
    avatar: Optional[str] = Field(None, max_length=500)


class CategoryIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: str  # income | expense
    icon: str = Field("📁", max_length=20)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Tên danh mục không được để trống")
        return value

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value not in ("income", "expense"):
            raise ValueError("type phải là income hoặc expense")
        return value


class CategoryOut(BaseModel):
    id: int
    name: str
    type: str
    icon: str

    class Config:
        from_attributes = True


class TransactionIn(BaseModel):
    amount: float = Field(..., gt=0)
    type: str
    category_id: Optional[int] = None
    txn_date: date
    note: str = Field("", max_length=500)

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value not in ("income", "expense"):
            raise ValueError("type phải là income hoặc expense")
        return value


class TransactionOut(BaseModel):
    id: int
    amount: float
    type: str
    category_id: Optional[int]
    category_name: Optional[str] = None
    category_icon: Optional[str] = None
    txn_date: date
    note: str
    alert: Optional[dict] = None

    class Config:
        from_attributes = True


class TransactionListOut(BaseModel):
    items: List[TransactionOut]
    page: int
    limit: int
    total: int
    total_pages: int


class BudgetIn(BaseModel):
    category_id: int
    month: int = Field(..., ge=1, le=12)
    year: int = Field(..., ge=2000, le=2100)
    limit_amount: float = Field(..., gt=0)


class BudgetOut(BaseModel):
    id: int
    category_id: int
    category_name: Optional[str] = None
    category_icon: Optional[str] = None
    month: int
    year: int
    limit_amount: float
    spent: float = 0
    remaining: float = 0
    percent: float = 0
    alert_level: str = "normal"
    budget_amount: float = 0
    spent_amount: float = 0
    percent_used: float = 0
    warning_level: str = "normal"
    over_amount: float = 0

    class Config:
        from_attributes = True


class GoalIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    target_amount: float = Field(..., gt=0)
    current_amount: float = Field(0, ge=0)
    deadline: Optional[date] = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Tên mục tiêu không được để trống")
        return value


class GoalOut(BaseModel):
    id: int
    name: str
    target_amount: float
    current_amount: float
    deadline: Optional[date]
    status: str
    percent: float = 0
    remaining_amount: float = 0

    class Config:
        from_attributes = True


class GoalAddMoneyIn(BaseModel):
    amount: float = Field(..., gt=0)


class GoalAddMoneyOut(GoalOut):
    just_completed: bool = False
    new_notifications: list[dict] = Field(default_factory=list)


class AIChatIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)


class ChatConversationOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ChatMessageIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class ChatFeedbackIn(BaseModel):
    feedback_type: str

    @field_validator("feedback_type")
    @classmethod
    def validate_feedback_type(cls, value: str) -> str:
        if value not in ("helpful", "not_helpful"):
            raise ValueError("Loại đánh giá không hợp lệ")
        return value


class NotificationOut(BaseModel):
    id: int
    kind: str
    type: str
    title: str
    message: str
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AIReportIn(BaseModel):
    month: int = Field(..., ge=1, le=12)
    year: int = Field(..., ge=2000, le=2100)


class UserAdminOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    status: str
    is_active: bool
    locked_until: Optional[datetime] = None
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class StatusUpdateIn(BaseModel):
    status: str  # active | locked


class RoleUpdateIn(BaseModel):
    role: str  # user | admin


# ---------- Auth helpers ----------
def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Mật khẩu không được vượt quá 72 byte UTF-8")
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    if len(plain.encode("utf-8")) > 72:
        return False
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Không thể xác thực",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except (JWTError, TypeError, ValueError):
        raise credentials_exception
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise credentials_exception
    if user.status == "locked":
        raise HTTPException(status_code=403, detail="Tài khoản đã bị khóa")
    if user.role not in ("user", "admin"):
        raise HTTPException(status_code=403, detail="Vai trò tài khoản không hợp lệ")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Chỉ admin được phép")
    return user


def sync_temporary_lock(user: User, now: Optional[datetime] = None) -> str:
    now = now or datetime.utcnow()
    if user.status == "locked":
        return "disabled"
    if user.locked_until and user.locked_until > now:
        return "temporary_locked"
    if user.locked_until and user.locked_until <= now:
        user.locked_until = None
        user.failed_login_count = 0
    return "active"


def seed_default_categories(db: Session, user_id: int):
    defaults = db.query(DefaultCategory).all()
    if not defaults:
        defaults_data = [
            ("Lương", "income", "💰"), ("Thưởng", "income", "🎁"),
            ("Ăn uống", "expense", "🍔"), ("Mua sắm", "expense", "🛒"),
            ("Di chuyển", "expense", "🚗"), ("Giải trí", "expense", "🎬"),
            ("Hóa đơn", "expense", "📄"), ("Sức khỏe", "expense", "🏥"),
            ("Giáo dục", "expense", "📚"), ("Khác", "expense", "📦"),
        ]
        for name, typ, icon in defaults_data:
            db.add(DefaultCategory(name=name, type=typ, icon=icon))
        db.commit()
        defaults = db.query(DefaultCategory).all()
    existing_keys = {
        (category.name, category.type)
        for category in db.query(Category).filter(Category.user_id == user_id).all()
    }
    for d in defaults:
        key = (d.name, d.type)
        if key not in existing_keys:
            exists = db.query(Category).filter(
                Category.user_id == user_id,
                Category.name == d.name,
                Category.type == d.type,
            ).first()
            if exists:
                existing_keys.add(key)
                continue
            db.add(Category(user_id=user_id, name=d.name, type=d.type, icon=d.icon))
            db.flush()
            existing_keys.add(key)
    db.commit()


def log_system(db: Session, message: str, level: str = "error", source: str = None):
    db.add(SystemLog(level=level, source=source, message=message))
    db.commit()


def log_ai(db: Session, user_id: int, kind: str, success: bool = True, error: str = None, question: str = None, response_type: str = None):
    db.add(AILog(user_id=user_id, kind=kind, success=success, error_message=error, question=question, response_type=response_type, status="success" if success else "failed"))
    db.commit()


def get_owned_category(db: Session, category_id: Optional[int], user_id: int, required_type: Optional[str] = None) -> Optional[Category]:
    """Resolve a category safely. Categories are copied to each user at registration."""
    if category_id is None:
        return None
    category = db.query(Category).filter(
        Category.id == category_id, Category.user_id == user_id
    ).first()
    if not category:
        raise HTTPException(400, "Danh mục không tồn tại hoặc không thuộc về bạn")
    if required_type and category.type != required_type:
        raise HTTPException(400, "Loại danh mục phải phù hợp với loại giao dịch")
    return category


def transaction_out(transaction: Transaction) -> dict:
    category = transaction.category
    return {
        "id": transaction.id, "amount": float(transaction.amount), "type": transaction.type,
        "category_id": transaction.category_id,
        "category_name": category.name if category else None,
        "category_icon": category.icon if category else None,
        "txn_date": transaction.txn_date, "note": transaction.note or "",
    }


def budget_warning_level(percent: float) -> str:
    if percent > 100:
        return "exceeded"
    if percent >= 90:
        return "danger"
    if percent >= 80:
        return "warning"
    return "normal"


def create_budget_notification(db: Session, user_id: int, category_name: str, alert: dict) -> Notification:
    level = alert["level"]
    percent = alert["percent_used"]
    if level == "exceeded":
        title = "Vượt ngân sách"
        message = f"🚨 Đã vượt ngân sách {category_name} {alert['over_amount']:,.0f}đ ({percent:.1f}%)."
    elif level == "danger":
        title = "Cảnh báo ngân sách cao"
        message = f"⚠️ Đã sử dụng {percent:.1f}% ngân sách {category_name}."
    else:
        title = "Cảnh báo ngân sách"
        message = f"⚠️ Đã sử dụng {percent:.1f}% ngân sách {category_name}."
    notification = Notification(
        user_id=user_id,
        kind="budget",
        type="budget",
        title=title,
        message=message,
    )
    db.add(notification)
    return notification


def transaction_budget_alert(db: Session, transaction: Transaction) -> Optional[dict]:
    if transaction.type != "expense" or transaction.category_id is None:
        return None

    budget = db.query(Budget).filter(
        Budget.user_id == transaction.user_id,
        Budget.category_id == transaction.category_id,
        Budget.month == transaction.txn_date.month,
        Budget.year == transaction.txn_date.year,
    ).first()
    if not budget:
        return None

    spent = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.user_id == transaction.user_id,
        Transaction.type == "expense",
        Transaction.category_id == transaction.category_id,
        func.extract("month", Transaction.txn_date) == transaction.txn_date.month,
        func.extract("year", Transaction.txn_date) == transaction.txn_date.year,
    ).scalar() or 0
    percent = float(spent) / float(budget.limit_amount) * 100 if budget.limit_amount else 0
    level = budget_warning_level(percent)
    if level == "normal":
        return None

    alert = {
        "level": level,
        "spent": float(spent),
        "limit": float(budget.limit_amount),
        "percent_used": round(percent, 1),
        "exceeded_amount": max(0, float(spent) - float(budget.limit_amount)),
        "over_amount": max(0, float(spent) - float(budget.limit_amount)),
    }
    category_name = budget.category.name if budget.category else "danh mục này"
    create_budget_notification(db, transaction.user_id, category_name, alert)
    return alert


def create_goal_notification(db: Session, user_id: int, goal: SavingGoal, over_amount: float) -> Notification:
    title = "Hoàn thành mục tiêu tiết kiệm"
    current_amount = float(goal.current_amount or 0)
    target_amount = float(goal.target_amount or 0)
    if over_amount > 0:
        message = (
            f"🎉 Chúc mừng! Bạn đã hoàn thành xuất sắc mục tiêu {goal.name} "
            f"với số tiền {current_amount:,.0f}/{target_amount:,.0f}đ! "
            f"Bạn đã vượt {over_amount:,.0f}đ."
        )
    else:
        message = (
            f"🎉 Chúc mừng! Bạn đã hoàn thành xuất sắc mục tiêu {goal.name} "
            f"với số tiền {current_amount:,.0f}/{target_amount:,.0f}đ!"
        )
    notification = Notification(user_id=user_id, kind="goal", type="goal", title=title, message=message)
    db.add(notification)
    return notification


def budget_out(db: Session, budget: Budget, user_id: int) -> dict:
    spent = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.user_id == user_id, Transaction.type == "expense",
        Transaction.category_id == budget.category_id,
        func.extract("month", Transaction.txn_date) == budget.month,
        func.extract("year", Transaction.txn_date) == budget.year,
    ).scalar() or 0
    spent = float(spent)
    percent = round(spent / budget.limit_amount * 100, 1) if budget.limit_amount else 0
    warning_level = budget_warning_level(percent)
    alert_level = "exceeded" if warning_level == "exceeded" else "reached" if percent >= 100 else "warning" if warning_level != "normal" else "normal"
    category = budget.category
    return {
        "id": budget.id, "category_id": budget.category_id,
        "category_name": category.name if category else None,
        "category_icon": category.icon if category else None,
        "month": budget.month, "year": budget.year,
        "limit_amount": float(budget.limit_amount), "spent": spent,
        "remaining": max(0, float(budget.limit_amount) - spent),
        "percent": max(0, round(percent, 1)), "alert_level": alert_level,
        "budget_amount": float(budget.limit_amount),
        "spent_amount": spent,
        "percent_used": max(0, round(percent, 1)),
        "warning_level": warning_level,
        "over_amount": max(0, round(spent - float(budget.limit_amount), 2)),
    }


def goal_out(goal: SavingGoal) -> dict:
    current = float(goal.current_amount or 0)
    target = float(goal.target_amount)
    if current >= target:
        status = "done"
    elif goal.deadline and goal.deadline < date.today():
        status = "overdue"
    else:
        status = "active"
    progress_percent = round(current / target * 100, 1) if target else 0
    over_amount = max(0, current - target)
    is_completed = current >= target
    return {
        "id": goal.id, "name": goal.name, "target_amount": target,
        "current_amount": current, "deadline": goal.deadline,
        "status": status, "percent": progress_percent,
        "progress_percent": progress_percent,
        "remaining_amount": max(0, target - current),
        "over_amount": over_amount,
        "is_completed": is_completed,
        "message": f"🎉 Bạn đã vượt mục tiêu {over_amount:,.0f} đồng." if over_amount else "🎉 Hoàn thành mục tiêu" if is_completed else "",
        "congratulated": bool(goal.congratulated),
    }


# ---------- Startup ----------
@app.on_event("startup")
def on_startup():
    validate_security_config()
    validate_ai_provider()
    Base.metadata.create_all(bind=engine)
    connection = engine.connect()
    try:
        existing = inspect(engine)
        migration_columns = {
            "ai_generations": (("period_start", "DATE NULL"), ("period_end", "DATE NULL")),
            "ai_reports": (("period_start", "DATE NULL"), ("period_end", "DATE NULL")),
            "users": (("failed_login_count", "INTEGER NOT NULL DEFAULT 0"), ("locked_until", "DATETIME NULL")),
            "saving_goals": (("congratulated", "BOOLEAN NOT NULL DEFAULT 0"),),
            "notifications": (("type", "VARCHAR(30) NOT NULL DEFAULT 'budget'"),),
            "ai_logs": (("question", "TEXT NULL"), ("response_type", "VARCHAR(20) NULL"), ("status", "VARCHAR(20) NULL")),
        }
        for table, table_columns in migration_columns.items():
            columns = {column["name"] for column in existing.get_columns(table)} if existing.has_table(table) else set()
            for column, definition in table_columns:
                if column not in columns:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
        connection.commit()
    finally:
        connection.close()
    db = next(get_db())
    try:
        # Seed admin
        admin = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        if not admin:
            admin = User(
                email=ADMIN_EMAIL,
                password_hash=hash_password(ADMIN_PASSWORD),
                full_name=ADMIN_NAME,
                role="admin",
                status="active",
            )
            db.add(admin)
            db.commit()
        # Seed default categories master
        if db.query(DefaultCategory).count() == 0:
            for name, typ, icon in [
                ("Lương", "income", "💰"), ("Thưởng", "income", "🎁"),
                ("Ăn uống", "expense", "🍔"), ("Mua sắm", "expense", "🛒"),
                ("Di chuyển", "expense", "🚗"), ("Giải trí", "expense", "🎬"),
                ("Hóa đơn", "expense", "📄"), ("Sức khỏe", "expense", "🏥"),
                ("Giáo dục", "expense", "📚"), ("Khác", "expense", "📦"),
            ]:
                db.add(DefaultCategory(name=name, type=typ, icon=icon))
            db.commit()
    finally:
        db.close()


# ========== AUTH ==========
@app.post("/api/auth/register", response_model=TokenOut)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email.lower()).first():
        raise HTTPException(400, "Email đã được sử dụng")
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role="user",
        status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    seed_default_categories(db, user.id)
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return TokenOut(
        access_token=token, role=user.role,
        full_name=user.full_name, email=user.email
    )


@app.post("/api/auth/login", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form.username.lower()).first()
    if not user:
        raise HTTPException(401, "Email hoặc mật khẩu không chính xác")
    if user.status == "locked":
        raise HTTPException(403, "Tài khoản đã bị khóa. Liên hệ quản trị viên.")
    now = datetime.utcnow()
    if user.locked_until and user.locked_until > now:
        raise HTTPException(423, "Tài khoản tạm thời bị khóa trong 5 phút do nhập sai mật khẩu quá nhiều lần.")
    if user.locked_until and user.locked_until <= now:
        user.locked_until = None
        user.failed_login_count = 0
        db.commit()
    if not verify_password(form.password, user.password_hash):
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= 5:
            user.locked_until = now + timedelta(minutes=5)
            db.commit()
            raise HTTPException(423, "Tài khoản tạm thời bị khóa trong 5 phút do nhập sai mật khẩu quá nhiều lần.")
        db.commit()
        remaining = 5 - user.failed_login_count
        if user.failed_login_count >= 3:
            raise HTTPException(401, f"Bạn còn {remaining} lần thử trước khi tài khoản bị khóa.")
        raise HTTPException(401, "Email hoặc mật khẩu không chính xác")
    token = create_access_token({"sub": str(user.id), "role": user.role})
    user.failed_login_count = 0
    user.locked_until = None
    db.commit()
    return TokenOut(
        access_token=token, role=user.role,
        full_name=user.full_name, email=user.email
    )


@app.post("/api/auth/forgot-password")
def forgot_password(body: ForgotPasswordIn, db: Session = Depends(get_db)):
    try:
        ensure_password_reset_email_configured()
    except PasswordResetEmailConfigurationError as exc:
        raise HTTPException(503, "Chức năng đặt lại mật khẩu chưa được cấu hình email.") from exc

    user = db.query(User).filter(User.email == body.email.lower()).first()
    message = "Nếu email tồn tại, hướng dẫn đặt lại mật khẩu sẽ được gửi đến hộp thư của bạn."
    if not user:
        return {"ok": True, "message": message}

    raw_token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)
    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=now + timedelta(minutes=15),
    )
    db.add(reset_token)
    db.commit()
    reset_url = f"{os.getenv('APP_BASE_URL', '').rstrip('/')}/login#reset_token={quote(raw_token, safe='')}"
    try:
        send_password_reset_email(user.email, reset_url)
    except Exception:
        reset_token.used_at = datetime.utcnow()
        db.commit()
        logger.exception("Password reset email delivery failed for user_id=%s", user.id)
    return {"ok": True, "message": message}


@app.post("/api/auth/reset-password")
def reset_password(body: ResetPasswordIn, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    reset = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.expires_at > datetime.utcnow(),
    ).first()
    if not reset:
        raise HTTPException(400, "Mã đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.")
    if not any(char.isalpha() for char in body.new_password) or not any(char.isdigit() for char in body.new_password):
        raise HTTPException(422, "Mật khẩu phải gồm cả chữ và số.")
    reset.user.password_hash = hash_password(body.new_password)
    reset.user.failed_login_count = 0
    reset.user.locked_until = None
    reset.used_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "message": "Đặt lại mật khẩu thành công. Vui lòng đăng nhập."}


@app.get("/api/auth/me")
def me(user: User = Depends(get_current_user)):
    return {
        "id": user.id, "email": user.email, "full_name": user.full_name,
        "avatar": user.avatar, "role": user.role, "status": user.status,
        "created_at": user.created_at,
    }


@app.put("/api/auth/profile")
def update_profile(body: ProfileUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.full_name is not None:
        full_name = " ".join(body.full_name.split())
        if len(full_name) < 2:
            raise HTTPException(400, "Họ tên phải có ít nhất 2 ký tự")
        user.full_name = full_name
    if body.avatar is not None:
        user.avatar = body.avatar or None
    db.commit()
    return {"ok": True, "full_name": user.full_name, "avatar": user.avatar}


@app.put("/api/auth/change-password")
def change_password(body: PasswordChangeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(400, "Mật khẩu hiện tại không đúng")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True, "message": "Đã đổi mật khẩu"}


# ========== CATEGORIES (User) ==========
@app.get("/api/categories", response_model=List[CategoryOut])
def list_categories(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Category).filter(Category.user_id == user.id).all()


@app.post("/api/categories", response_model=CategoryOut)
def create_category(body: CategoryIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    exists = db.query(Category).filter(
        Category.user_id == user.id, Category.name == body.name, Category.type == body.type
    ).first()
    if exists:
        raise HTTPException(400, "Danh mục đã tồn tại")
    cat = Category(user_id=user.id, name=body.name, type=body.type, icon=body.icon or "📁")
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@app.put("/api/categories/{cat_id}", response_model=CategoryOut)
def update_category(cat_id: int, body: CategoryIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == cat_id, Category.user_id == user.id).first()
    if not cat:
        raise HTTPException(404, "Không tìm thấy danh mục")
    duplicate = db.query(Category).filter(
        Category.user_id == user.id, Category.name == body.name,
        Category.type == body.type, Category.id != cat.id
    ).first()
    if duplicate:
        raise HTTPException(400, "Danh mục đã tồn tại")
    if body.type != cat.type:
        has_transactions = db.query(Transaction.id).filter(Transaction.category_id == cat.id).first()
        has_budgets = db.query(Budget.id).filter(Budget.category_id == cat.id).first()
        if has_transactions or has_budgets:
            raise HTTPException(409, "Không thể đổi loại danh mục đang có giao dịch hoặc ngân sách")
    cat.name = body.name
    cat.type = body.type
    cat.icon = body.icon or cat.icon
    db.commit()
    db.refresh(cat)
    return cat


@app.delete("/api/categories/{cat_id}")
def delete_category(cat_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == cat_id, Category.user_id == user.id).first()
    if not cat:
        raise HTTPException(404, "Không tìm thấy danh mục")
    # Preserve historical transactions and budgets. The user must move or delete
    # dependent records explicitly before removing a category.
    has_transactions = db.query(Transaction.id).filter(Transaction.category_id == cat.id).first()
    has_budgets = db.query(Budget.id).filter(Budget.category_id == cat.id).first()
    if has_transactions or has_budgets:
        raise HTTPException(409, "Không thể xóa danh mục đang có giao dịch hoặc ngân sách")
    db.delete(cat)
    db.commit()
    return {"ok": True}


# ========== TRANSACTIONS (User) ==========
@app.get("/api/transactions", response_model=TransactionListOut)
def list_transactions(
    q: Optional[str] = None,
    type: Optional[str] = None,
    category_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    # Backward-compatible aliases for the existing web client.
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    sort: str = "date",
    order: str = "desc",
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Transaction).filter(Transaction.user_id == user.id)
    if q:
        query = query.filter(Transaction.note.ilike(f"%{q}%"))
    if type and type not in ("income", "expense"):
        raise HTTPException(400, "type phải là income hoặc expense")
    if type:
        query = query.filter(Transaction.type == type)
    if category_id is not None:
        get_owned_category(db, category_id, user.id)
        query = query.filter(Transaction.category_id == category_id)
    start_date = start_date or date_from
    end_date = end_date or date_to
    if start_date and end_date and start_date > end_date:
        raise HTTPException(400, "Ngày bắt đầu phải trước hoặc bằng ngày kết thúc")
    if start_date:
        query = query.filter(Transaction.txn_date >= start_date)
    if end_date:
        query = query.filter(Transaction.txn_date <= end_date)
    legacy_sort = {"date_asc": ("date", "asc"), "date_desc": ("date", "desc"), "amount_asc": ("amount", "asc"), "amount_desc": ("amount", "desc")}
    sort, order = legacy_sort.get(sort, (sort, order))
    if sort not in ("date", "amount") or order not in ("asc", "desc"):
        raise HTTPException(400, "sort phải là date hoặc amount; order là asc hoặc desc")
    column = Transaction.txn_date if sort == "date" else Transaction.amount
    query = query.order_by(column.asc() if order == "asc" else column.desc(), Transaction.id.desc())
    total = query.count()
    rows = query.offset((page - 1) * limit).limit(limit).all()
    return {"items": [transaction_out(row) for row in rows], "page": page, "limit": limit,
            "total": total, "total_pages": (total + limit - 1) // limit}


@app.get("/api/transactions/{tx_id}", response_model=TransactionOut)
def get_transaction(tx_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    transaction = db.query(Transaction).filter(Transaction.id == tx_id, Transaction.user_id == user.id).first()
    if not transaction:
        raise HTTPException(404, "Không tìm thấy giao dịch")
    return transaction_out(transaction)


@app.post("/api/transactions", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def create_transaction(body: TransactionIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_owned_category(db, body.category_id, user.id, body.type)
    t = Transaction(
        user_id=user.id, category_id=body.category_id,
        amount=body.amount, type=body.type,
        txn_date=body.txn_date, note=body.note or "",
    )
    db.add(t)
    db.flush()
    alert = transaction_budget_alert(db, t)
    db.commit()
    db.refresh(t)
    result = transaction_out(t)
    # Kept as an additive field for the existing frontend's warning toast.
    result["alert"] = alert
    return result


@app.get("/api/notifications", response_model=List[NotificationOut])
def list_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Notification).filter(
        Notification.user_id == user.id
    ).order_by(Notification.created_at.desc(), Notification.id.desc()).limit(100).all()


@app.get("/api/notifications/unread-count")
def unread_notification_count(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == user.id,
        Notification.is_read == False,
    ).scalar() or 0
    return {"unread_count": count}


@app.put("/api/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user.id,
    ).first()
    if not notification:
        raise HTTPException(404, "Không tìm thấy thông báo")
    notification.is_read = True
    db.commit()
    return {"ok": True}


@app.put("/api/notifications/read-all")
def mark_all_notifications_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).update({"is_read": True}, synchronize_session=False)
    db.commit()
    return {"ok": True}


@app.delete("/api/notifications/{notification_id}")
def delete_notification(notification_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user.id,
    ).first()
    if not notification:
        raise HTTPException(404, "Không tìm thấy thông báo")
    db.delete(notification)
    db.commit()
    return {"ok": True}


@app.delete("/api/notifications")
def delete_all_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(Notification).filter(Notification.user_id == user.id).delete(synchronize_session=False)
    db.commit()
    return {"ok": True}


@app.put("/api/transactions/{tx_id}", response_model=TransactionOut)
def update_transaction(tx_id: int, body: TransactionIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = db.query(Transaction).filter(Transaction.id == tx_id, Transaction.user_id == user.id).first()
    if not t:
        raise HTTPException(404, "Không tìm thấy giao dịch")
    get_owned_category(db, body.category_id, user.id, body.type)
    t.amount = body.amount
    t.type = body.type
    t.category_id = body.category_id
    t.txn_date = body.txn_date
    t.note = body.note or ""
    db.flush()
    alert = transaction_budget_alert(db, t)
    db.commit()
    db.refresh(t)
    result = transaction_out(t)
    result["alert"] = alert
    return result


@app.delete("/api/transactions/{tx_id}")
def delete_transaction(tx_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = db.query(Transaction).filter(Transaction.id == tx_id, Transaction.user_id == user.id).first()
    if not t:
        raise HTTPException(404, "Không tìm thấy giao dịch")
    db.delete(t)
    db.commit()
    return {"ok": True}


# ========== BUDGETS ==========
@app.get("/api/budgets", response_model=List[BudgetOut])
def list_budgets(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    category_id: Optional[int] = None,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    query = db.query(Budget).filter(Budget.user_id == user.id)
    if month is not None:
        query = query.filter(Budget.month == month)
    if year is not None:
        query = query.filter(Budget.year == year)
    if category_id is not None:
        get_owned_category(db, category_id, user.id, "expense")
        query = query.filter(Budget.category_id == category_id)
    budgets = query.order_by(Budget.year.desc(), Budget.month.desc(), Budget.id.desc()).all()
    return [budget_out(db, budget, user.id) for budget in budgets]


@app.get("/api/budgets/{budget_id}", response_model=BudgetOut)
def get_budget(budget_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    budget = db.query(Budget).filter(Budget.id == budget_id, Budget.user_id == user.id).first()
    if not budget:
        raise HTTPException(404, "Không tìm thấy ngân sách")
    return budget_out(db, budget, user.id)


@app.post("/api/budgets", response_model=BudgetOut, status_code=status.HTTP_201_CREATED)
def create_budget(body: BudgetIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_owned_category(db, body.category_id, user.id, "expense")
    exists = db.query(Budget).filter(
        Budget.user_id == user.id, Budget.category_id == body.category_id,
        Budget.month == body.month, Budget.year == body.year
    ).first()
    if exists:
        raise HTTPException(400, "Đã có ngân sách cho danh mục này trong tháng")
    b = Budget(
        user_id=user.id, category_id=body.category_id,
        month=body.month, year=body.year, limit_amount=body.limit_amount
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return budget_out(db, b, user.id)


@app.put("/api/budgets/{budget_id}", response_model=BudgetOut)
def update_budget(budget_id: int, body: BudgetIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    b = db.query(Budget).filter(Budget.id == budget_id, Budget.user_id == user.id).first()
    if not b:
        raise HTTPException(404, "Không tìm thấy ngân sách")
    get_owned_category(db, body.category_id, user.id, "expense")
    duplicate = db.query(Budget).filter(
        Budget.user_id == user.id, Budget.category_id == body.category_id,
        Budget.month == body.month, Budget.year == body.year, Budget.id != b.id
    ).first()
    if duplicate:
        raise HTTPException(400, "Đã có ngân sách cho danh mục này trong tháng")
    b.category_id = body.category_id
    b.month = body.month
    b.year = body.year
    b.limit_amount = body.limit_amount
    db.commit()
    db.refresh(b)
    return budget_out(db, b, user.id)


@app.delete("/api/budgets/{budget_id}")
def delete_budget(budget_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    b = db.query(Budget).filter(Budget.id == budget_id, Budget.user_id == user.id).first()
    if not b:
        raise HTTPException(404, "Không tìm thấy ngân sách")
    db.delete(b)
    db.commit()
    return {"ok": True}


# ========== GOALS ==========
@app.get("/api/goals", response_model=List[GoalOut])
def list_goals(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    goals = db.query(SavingGoal).filter(SavingGoal.user_id == user.id).order_by(SavingGoal.created_at.desc()).all()
    return [goal_out(goal) for goal in goals]


@app.get("/api/goals/{goal_id}", response_model=GoalOut)
def get_goal(goal_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    goal = db.query(SavingGoal).filter(SavingGoal.id == goal_id, SavingGoal.user_id == user.id).first()
    if not goal:
        raise HTTPException(404, "Không tìm thấy mục tiêu")
    return goal_out(goal)


@app.post("/api/goals", response_model=GoalOut, status_code=status.HTTP_201_CREATED)
def create_goal(body: GoalIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    g = SavingGoal(
        user_id=user.id, name=body.name,
        target_amount=body.target_amount,
        current_amount=body.current_amount or 0,
        deadline=body.deadline,
        status="done" if (body.current_amount or 0) >= body.target_amount else "active",
        congratulated=False,
    )
    db.add(g)
    if g.current_amount >= g.target_amount:
        g.congratulated = True
        create_goal_notification(db, user.id, g, max(0, float(g.current_amount) - float(g.target_amount)))
    db.commit()
    db.refresh(g)
    return goal_out(g)


@app.put("/api/goals/{goal_id}", response_model=GoalOut)
def update_goal(goal_id: int, body: GoalIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    goal = db.query(SavingGoal).filter(SavingGoal.id == goal_id, SavingGoal.user_id == user.id).first()
    if not goal:
        raise HTTPException(404, "Không tìm thấy mục tiêu")
    was_done = (goal.current_amount or 0) >= goal.target_amount
    goal.name = body.name
    goal.target_amount = body.target_amount
    goal.current_amount = body.current_amount
    goal.deadline = body.deadline
    goal.status = "done" if body.current_amount >= body.target_amount else "overdue" if body.deadline and body.deadline < date.today() else "active"
    if not goal.congratulated and not was_done and body.current_amount >= body.target_amount:
        goal.congratulated = True
        create_goal_notification(db, user.id, goal, max(0, float(body.current_amount) - float(body.target_amount)))
    db.commit()
    db.refresh(goal)
    return goal_out(goal)


@app.post("/api/goals/{goal_id}/add-money", response_model=GoalAddMoneyOut)
def add_goal_money(goal_id: int, body: GoalAddMoneyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    g = db.query(SavingGoal).filter(SavingGoal.id == goal_id, SavingGoal.user_id == user.id).first()
    if not g:
        raise HTTPException(404, "Không tìm thấy mục tiêu")
    previous_amount = float(g.current_amount or 0)
    new_amount = previous_amount + body.amount
    was_done = g.status == "done" or (g.current_amount or 0) >= g.target_amount
    g.current_amount = new_amount
    if g.current_amount >= g.target_amount:
        g.status = "done"
    is_completed = g.current_amount >= g.target_amount
    just_completed = not was_done and is_completed
    if just_completed and not g.congratulated:
        g.congratulated = True
        notification = create_goal_notification(
            db,
            user.id,
            g,
            max(0, float(g.current_amount) - float(g.target_amount)),
        )
    else:
        message = (
            f"💰 Bạn đã nạp thành công {body.amount:,.0f}đ vào mục tiêu {g.name}."
            if not is_completed
            else f"💰 Bạn đã nạp thêm {body.amount:,.0f}đ vào mục tiêu {g.name} đã hoàn thành."
        )
        notification = Notification(
            user_id=user.id,
            kind="goal",
            type="goal",
            title="Cập nhật mục tiêu tiết kiệm",
            message=message,
        )
        db.add(notification)
    db.commit()
    db.refresh(notification)
    result = goal_out(g)
    result["just_completed"] = just_completed
    result["show_congratulations"] = just_completed
    result["new_notifications"] = [{
        "id": notification.id,
        "kind": notification.kind,
        "type": notification.type,
        "title": notification.title,
        "message": notification.message,
        "is_read": notification.is_read,
        "created_at": notification.created_at,
    }]
    return result


@app.delete("/api/goals/{goal_id}")
def delete_goal(goal_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    g = db.query(SavingGoal).filter(SavingGoal.id == goal_id, SavingGoal.user_id == user.id).first()
    if not g:
        raise HTTPException(404, "Không tìm thấy mục tiêu")
    db.delete(g)
    db.commit()
    return {"ok": True}


# ========== STATS (User) ==========
@app.get("/api/stats/summary")
def stats_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = date.today()
    txs = db.query(Transaction).filter(
        Transaction.user_id == user.id,
        func.extract("month", Transaction.txn_date) == now.month,
        func.extract("year", Transaction.txn_date) == now.year,
    ).all()
    income = sum(t.amount for t in txs if t.type == "income")
    expense = sum(t.amount for t in txs if t.type == "expense")
    by_cat = {}
    for t in txs:
        if t.type != "expense":
            continue
        name = t.category.name if t.category else "Khác"
        icon = t.category.icon if t.category else "📦"
        key = f"{icon} {name}"
        by_cat[key] = by_cat.get(key, 0) + t.amount

    # by month this year
    months = []
    for m in range(1, 13):
        m_txs = db.query(Transaction).filter(
            Transaction.user_id == user.id,
            func.extract("month", Transaction.txn_date) == m,
            func.extract("year", Transaction.txn_date) == now.year,
        ).all()
        months.append({
            "month": m,
            "income": sum(t.amount for t in m_txs if t.type == "income"),
            "expense": sum(t.amount for t in m_txs if t.type == "expense"),
        })
    current_budgets = db.query(Budget).filter(
        Budget.user_id == user.id,
        Budget.month == now.month,
        Budget.year == now.year,
    ).all()
    exceeded_amount = 0.0
    for budget in current_budgets:
        spent = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.user_id == user.id,
            Transaction.type == "expense",
            Transaction.category_id == budget.category_id,
            func.extract("month", Transaction.txn_date) == now.month,
            func.extract("year", Transaction.txn_date) == now.year,
        ).scalar() or 0
        exceeded_amount += max(0.0, float(spent) - float(budget.limit_amount))
    budget_status = [budget_out(db, budget, user.id) for budget in current_budgets]
    current_goals = db.query(SavingGoal).filter(SavingGoal.user_id == user.id).order_by(SavingGoal.created_at.desc()).all()
    exceeded_budgets = [
        {
            "category_name": item["category_name"],
            "budget_amount": item["budget_amount"],
            "spent_amount": item["spent_amount"],
            "percent_used": item["percent_used"],
            "over_amount": item["over_amount"],
            "warning_level": item["warning_level"],
        }
        for item in budget_status
        if item["warning_level"] == "exceeded"
    ]
    return {
        "income": income, "expense": expense,
        "balance": income - expense,
        "save_rate": round((income - expense) / income * 100, 1) if income else 0,
        "by_category": by_cat,
        "by_month": months,
        "budget_exceeded_amount": round(exceeded_amount, 2),
        "budgets": budget_status,
        "exceeded_budgets": exceeded_budgets,
        "goals": [goal_out(goal) for goal in current_goals],
    }


@app.get("/api/stats/compare")
def stats_compare(
    m1: int = Query(..., ge=1, le=12),
    y1: int = Query(..., ge=2000, le=2100),
    m2: int = Query(..., ge=1, le=12),
    y2: int = Query(..., ge=2000, le=2100),
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    def sum_by_cat(m, y):
        txs = db.query(Transaction).filter(
            Transaction.user_id == user.id, Transaction.type == "expense",
            func.extract("month", Transaction.txn_date) == m,
            func.extract("year", Transaction.txn_date) == y,
        ).all()
        d = {}
        for t in txs:
            n = t.category.name if t.category else "Khác"
            d[n] = d.get(n, 0) + t.amount
        return d
    a, b = sum_by_cat(m1, y1), sum_by_cat(m2, y2)
    names = sorted(set(list(a.keys()) + list(b.keys())))
    rows = []
    for n in names:
        v1, v2 = a.get(n, 0), b.get(n, 0)
        diff = v2 - v1
        pct = round(diff / v1 * 100, 1) if v1 else (100 if v2 else 0)
        rows.append({"name": n, "m1": v1, "m2": v2, "diff": diff, "pct": pct})
    return {
        "m1": m1, "y1": y1, "m2": m2, "y2": y2,
        "rows": rows,
        "total1": sum(a.values()), "total2": sum(b.values()),
    }


# ========== AI (User) — mock hoặc API key ==========
def ai_mock_report(db: Session, user_id: int, month: int, year: int) -> str:
    txs = db.query(Transaction).filter(
        Transaction.user_id == user_id,
        func.extract("month", Transaction.txn_date) == month,
        func.extract("year", Transaction.txn_date) == year,
    ).all()
    income = sum(t.amount for t in txs if t.type == "income")
    expense = sum(t.amount for t in txs if t.type == "expense")
    by_cat = {}
    for t in txs:
        if t.type != "expense":
            continue
        n = t.category.name if t.category else "Khác"
        by_cat[n] = by_cat.get(n, 0) + t.amount
    top = sorted(by_cat.items(), key=lambda x: -x[1])[:3]
    msg = f"📊 Báo cáo chi tiêu tháng {month}/{year}\n\n"
    msg += f"1. Tóm tắt:\n   • Tổng thu: {income:,.0f}đ\n   • Tổng chi: {expense:,.0f}đ\n   • Số dư: {income-expense:,.0f}đ\n"
    if not txs:
        msg += "\n⚠️ Chưa có dữ liệu trong tháng này."
    else:
        msg += "\n2. Điểm nổi bật:\n"
        for i, (n, v) in enumerate(top, 1):
            pct = round(v / expense * 100) if expense else 0
            msg += f"   {i}. {n}: {v:,.0f}đ ({pct}%)\n"
        msg += "\n3. Gợi ý:\n"
        if expense > income:
            msg += "   • Chi đang vượt thu — nên cắt giảm khoản không cần thiết.\n"
        else:
            msg += "   • Chi tiêu trong tầm kiểm soát. Tiếp tục duy trì!\n"
        if top:
            msg += f"   • Khoản \"{top[0][0]}\" chiếm nhiều nhất — xem xét điều chỉnh ngân sách.\n"
    return msg


def ai_mock_chat(db: Session, user_id: int, question: str, history: Optional[List[ChatMessage]] = None) -> str:
    q = question.lower()
    now = date.today()
    txs = db.query(Transaction).filter(
        Transaction.user_id == user_id,
        func.extract("month", Transaction.txn_date) == now.month,
        func.extract("year", Transaction.txn_date) == now.year,
    ).all()
    income = sum(t.amount for t in txs if t.type == "income")
    expense = sum(t.amount for t in txs if t.type == "expense")
    by_cat = {}
    for t in txs:
        if t.type != "expense":
            continue
        n = t.category.name if t.category else "Khác"
        by_cat[n] = by_cat.get(n, 0) + t.amount
    ranked = sorted(by_cat.items(), key=lambda x: -x[1])

    if "nhiều nhất" in q or "top 1" in q:
        if ranked:
            n, v = ranked[0]
            pct = round(v / expense * 100) if expense else 0
            return f"Tháng này bạn chi nhiều nhất vào **{n}** với {v:,.0f}đ ({pct}% tổng chi)."
        return "Chưa có dữ liệu chi tiêu tháng này."
    if "tổng chi" in q or "tiêu hết" in q or "chi bao nhiêu" in q:
        return f"Tháng này bạn đã chi **{expense:,.0f}đ** ({len([t for t in txs if t.type=='expense'])} giao dịch)."
    if "thu nhập" in q or "tổng thu" in q:
        return f"Tháng này tổng thu nhập là **{income:,.0f}đ**."
    if "số dư" in q:
        return f"Số dư tháng này: **{income-expense:,.0f}đ** (Thu {income:,.0f} − Chi {expense:,.0f})."
    if "vượt" in q or "ngân sách" in q:
        budgets = db.query(Budget).filter(
            Budget.user_id == user_id, Budget.month == now.month, Budget.year == now.year
        ).all()
        overs = []
        for b in budgets:
            spent = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                Transaction.user_id == user_id, Transaction.type == "expense",
                Transaction.category_id == b.category_id,
                func.extract("month", Transaction.txn_date) == now.month,
                func.extract("year", Transaction.txn_date) == now.year,
            ).scalar() or 0
            if spent > b.limit_amount:
                name = b.category.name if b.category else "?"
                overs.append(f"• {name}: chi {spent:,.0f} / {b.limit_amount:,.0f} (vượt {spent-b.limit_amount:,.0f})")
        if overs:
            return "⚠️ Đang vượt ngân sách:\n" + "\n".join(overs)
        return "Hiện không có danh mục nào vượt ngân sách tháng này. 👍"

    # fallback
    ans = f"Dựa trên dữ liệu tháng này:\n• Thu: {income:,.0f}đ\n• Chi: {expense:,.0f}đ\n• Số dư: {income-expense:,.0f}đ\n"
    if ranked:
        ans += "\nTop chi tiêu:\n"
        for i, (n, v) in enumerate(ranked[:5], 1):
            ans += f"  {i}. {n}: {v:,.0f}đ\n"
    ans += "\n💡 Hỏi cụ thể hơn: \"chi nhiều nhất vào đâu?\", \"tổng chi tháng này?\", \"có vượt ngân sách không?\""
    return ans


def ai_mock_suggest(db: Session, user_id: int) -> str:
    txs = db.query(Transaction).filter(Transaction.user_id == user_id, Transaction.type == "expense").all()
    by_cat = {}
    months = set()
    for t in txs:
        n = t.category.name if t.category else "Khác"
        by_cat[n] = by_cat.get(n, 0) + t.amount
        months.add((t.txn_date.year, t.txn_date.month))
    n_months = max(1, len(months))
    msg = "💡 Gợi ý ngân sách tham khảo (kèm giải thích)\n\n"
    if not by_cat:
        return msg + "Chưa có đủ dữ liệu chi tiêu. Hãy ghi nhận giao dịch trước."
    for n, total in sorted(by_cat.items(), key=lambda x: -x[1]):
        avg = round(total / n_months / 1000) * 1000
        suggest = round(avg * 1.1 / 1000) * 1000
        msg += f"• {n}: {suggest:,.0f}đ\n  → TB {avg:,.0f}đ/tháng + 10% dự phòng ({n_months} tháng dữ liệu)\n"
    now = date.today()
    budgets = db.query(Budget).filter(
        Budget.user_id == user_id, Budget.month == now.month, Budget.year == now.year
    ).all()
    alerts = []
    for budget in budgets:
        spent = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.user_id == user_id,
            Transaction.type == "expense",
            Transaction.category_id == budget.category_id,
            func.extract("month", Transaction.txn_date) == now.month,
            func.extract("year", Transaction.txn_date) == now.year,
        ).scalar() or 0
        percent = (float(spent) / budget.limit_amount * 100) if budget.limit_amount else 0
        threshold = 100 if percent >= 100 else 90 if percent >= 90 else 80 if percent >= 80 else 0
        if threshold:
            category = budget.category.name if budget.category else "Khác"
            alerts.append(f"• {category}: {percent:.1f}% ngân sách ({float(spent):,.0f}đ / {budget.limit_amount:,.0f}đ) — đạt ngưỡng {threshold}%" + (" và đã vượt ngân sách." if percent > 100 else "."))
    if alerts:
        msg += "\n⚠️ Cảnh báo ngân sách tháng này:\n" + "\n".join(alerts)
    else:
        msg += "\n✅ Chưa có danh mục nào đạt 80% ngân sách tháng này."
    msg += "\n*Gợi ý tham khảo — điều chỉnh theo kế hoạch thực tế.*"
    return msg


@app.post("/api/ai/report")
def ai_report(body: AIReportIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        # Có thể mở rộng gọi OpenAI/Gemini khi AI_API_KEY có
        text = ai_mock_report(db, user.id, body.month, body.year)
        scope_key = f"{body.year:04d}-{body.month:02d}"
        created_at = datetime.utcnow()
        title = f"Báo cáo {body.month}/{body.year}"
        period_start = date(body.year, body.month, 1)
        period_end = date(body.year + (body.month == 12), 1 if body.month == 12 else body.month + 1, 1) - timedelta(days=1)
        db.add(AIGeneration(user_id=user.id, kind="report", scope_key=f"{scope_key}-{created_at.strftime('%Y%m%d%H%M%S%f')}", title=title, content=text, period_start=period_start, period_end=period_end, created_at=created_at, updated_at=created_at))
        db.add(AIReport(user_id=user.id, title=title, content=text, report_type="report", period_start=period_start, period_end=period_end, created_at=created_at))
        db.commit()
        log_ai(db, user.id, "report", True)
        return {"content": text, "provider": "local", "scope_key": scope_key}
    except Exception as e:
        logger.exception("AI report failed for user_id=%s", user.id)
        log_ai(db, user.id, "report", False, str(e))
        log_system(db, f"AI report error: {e}", "error", "ai")
        raise HTTPException(503, "Không thể tạo báo cáo AI lúc này.") from e


@app.post("/api/ai/chat")
def ai_chat(body: AIChatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        text = ai_mock_chat(db, user.id, body.question)
        log_ai(db, user.id, "chat", True)
        return {"answer": text, "provider": "local"}
    except Exception as e:
        logger.exception("Legacy AI chat failed for user_id=%s", user.id)
        log_ai(db, user.id, "chat", False, str(e))
        log_system(db, f"AI chat error: {e}", "error", "ai")
        raise HTTPException(503, "Không thể xử lý câu hỏi AI lúc này.") from e


@app.get("/api/ai/status")
def ai_status(user: User = Depends(get_current_user)):
    if AI_PROVIDER == "gemini":
        configured = bool(os.getenv("GEMINI_API_KEY", "").strip())
        return {
            "status": "configured" if configured else "offline",
            "provider": "gemini",
            "model": os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            "message": "Gemini API key configured" if configured else "Chưa cấu hình GEMINI_API_KEY",
        }
    if AI_PROVIDER == "openai":
        configured = bool(os.getenv("OPENAI_API_KEY") or AI_API_KEY)
        return {
            "status": "configured" if configured else "offline",
            "provider": "openai",
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "message": "OpenAI API key configured" if configured else "Chưa cấu hình OPENAI_API_KEY",
        }
    return {"status": "local", "provider": "mock", "message": "Đang dùng xử lý dữ liệu nội bộ."}


@app.get("/api/ai/generations")
def list_ai_generations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(AIGeneration).filter(AIGeneration.user_id == user.id).order_by(AIGeneration.updated_at.desc(), AIGeneration.id.desc()).all()
    return [{"id": row.id, "kind": row.kind, "scope_key": row.scope_key, "title": row.title, "content": row.content, "period_start": row.period_start, "period_end": row.period_end, "created_at": row.created_at, "updated_at": row.updated_at} for row in rows]


@app.delete("/api/ai/generations/{generation_id}")
def delete_ai_generation(generation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    generation = db.query(AIGeneration).filter(
        AIGeneration.id == generation_id,
        AIGeneration.user_id == user.id,
        AIGeneration.kind.in_(("report", "suggest")),
    ).first()
    if not generation:
        raise HTTPException(404, "Không tìm thấy lịch sử AI")
    report = db.query(AIReport).filter(
        AIReport.user_id == user.id,
        AIReport.title == generation.title,
        AIReport.content == generation.content,
    ).order_by(AIReport.created_at.desc()).first()
    if report:
        db.delete(report)
    db.delete(generation)
    db.commit()
    return {"ok": True}


def get_owned_conversation(db: Session, conversation_id: int, user_id: int) -> ChatConversation:
    conversation = db.query(ChatConversation).filter(
        ChatConversation.id == conversation_id,
        ChatConversation.user_id == user_id,
    ).first()
    if not conversation:
        raise HTTPException(404, "Không tìm thấy cuộc trò chuyện")
    return conversation


def conversation_out(db: Session, conversation: ChatConversation) -> dict:
    message_count = db.query(func.count(ChatMessage.id)).filter(
        ChatMessage.conversation_id == conversation.id
    ).scalar() or 0
    return {
        "id": conversation.id,
        "title": conversation.title,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at or conversation.created_at,
        "message_count": message_count,
    }


def chat_title_from_question(question: str) -> str:
    title = " ".join(question.split()).strip(" .!?;:")
    return title[:57] + "..." if len(title) > 60 else title


def chat_limit_error() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail="Cuộc trò chuyện đã quá dài, vui lòng tạo cuộc trò chuyện mới.",
    )


@app.get("/api/chat/conversations", response_model=List[ChatConversationOut])
def list_chat_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversations = db.query(ChatConversation).filter(
        ChatConversation.user_id == user.id,
        ChatConversation.messages.any()
    ).order_by(ChatConversation.updated_at.desc(), ChatConversation.id.desc()).all()
    return [conversation_out(db, conversation) for conversation in conversations]


@app.post("/api/chat/conversations", response_model=ChatConversationOut, status_code=status.HTTP_201_CREATED)
def create_chat_conversation(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    raise HTTPException(405, "Conversation được lưu cùng tin nhắn đầu tiên")


@app.get("/api/chat/conversations/{conversation_id}/messages", response_model=List[ChatMessageOut])
def list_chat_messages(conversation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversation = get_owned_conversation(db, conversation_id, user.id)
    return db.query(ChatMessage).filter(
        ChatMessage.conversation_id == conversation.id
    ).order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc()).all()


def get_owned_assistant_message(message_id: int, user: User, db: Session) -> ChatMessage:
    message = db.query(ChatMessage).join(ChatConversation).filter(
        ChatMessage.id == message_id,
        ChatMessage.role == "assistant",
        ChatConversation.user_id == user.id,
    ).first()
    if not message:
        raise HTTPException(404, "Không tìm thấy phản hồi AI")
    return message


@app.post("/api/chat/messages/{message_id}/feedback")
def save_chat_feedback(message_id: int, body: ChatFeedbackIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    message = get_owned_assistant_message(message_id, user, db)
    feedback = db.query(ChatFeedback).filter(
        ChatFeedback.message_id == message.id,
        ChatFeedback.user_id == user.id,
    ).first()
    if feedback:
        feedback.feedback_type = body.feedback_type
        feedback.created_at = datetime.utcnow()
    else:
        db.add(ChatFeedback(message_id=message.id, user_id=user.id, feedback_type=body.feedback_type))
    db.commit()
    return {"ok": True, "feedback_type": body.feedback_type}


@app.get("/api/chat/messages/{message_id}/download")
def download_chat_message(message_id: int, format: str = Query("txt", pattern="^(txt|pdf)$"), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    message = get_owned_assistant_message(message_id, user, db)
    filename = f"phan-hoi-ai-{message.id}.{format}"
    if format == "txt":
        return Response(content=message.content, media_type="text/plain; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfgen import canvas
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        font_name = "Helvetica"
        pdf.setFont(font_name, 11)
        y = height - 48
        for line in message.content.splitlines() or [""]:
            if y < 48:
                pdf.showPage()
                pdf.setFont(font_name, 11)
                y = height - 48
            pdf.drawString(42, y, line.encode("latin-1", "replace").decode("latin-1"))
            y -= 16
        pdf.save()
        return Response(content=buffer.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    except Exception as exc:
        logger.exception("PDF export failed for message_id=%s", message.id)
        raise HTTPException(503, "Không thể tạo file PDF.") from exc


@app.post("/api/chat/conversations/{conversation_id}/messages")
def send_chat_message(conversation_id: int, body: ChatMessageIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        result = answer_chat(db, user.id, conversation_id, body.content, is_admin=user.role == "admin")
        log_ai(db, user.id, "chat", True, response_type=result.get("source", "AI"))
        return {
            "conversation_id": result["conversation_id"],
            "title": result["title"],
            "user_message": {"id": result["user_message"].id, "role": result["user_message"].role, "content": result["user_message"].content, "created_at": result["user_message"].created_at},
            "assistant_message": {"id": result["assistant_message"].id, "role": result["assistant_message"].role, "content": result["assistant_message"].content, "created_at": result["assistant_message"].created_at},
            "provider": result.get("provider", "local-fallback"),
            "source": result.get("source", "AI"),
        }
    except OverflowError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc))
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc))
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Conversation chat failed for user_id=%s", user.id)
        log_ai(db, user.id, "chat", False, str(e))
        log_system(db, f"AI chat error: {e}", "error", "ai")
        raise HTTPException(503, "Không thể xử lý câu hỏi AI lúc này.") from e


@app.post("/api/chat/conversations/{conversation_id}/messages/with-image")
async def send_chat_message_with_image(
    conversation_id: int,
    file: UploadFile = File(...),
    content: str = Form("", max_length=4000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    allowed_types = {"image/jpeg", "image/png"}
    if file.content_type not in allowed_types:
        raise HTTPException(415, "Chỉ hỗ trợ ảnh JPG, JPEG hoặc PNG.")
    image_bytes = await file.read(10 * 1024 * 1024 + 1)
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(413, "Ảnh không được lớn hơn 10MB.")
    valid_signature = (
        image_bytes.startswith(b"\xff\xd8\xff")
        if file.content_type == "image/jpeg"
        else image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    )
    if not valid_signature:
        raise HTTPException(415, "Nội dung tệp không khớp với định dạng ảnh đã chọn.")
    try:
        result = answer_chat(
            db,
            user.id,
            conversation_id,
            content,
            is_admin=user.role == "admin",
            image_bytes=image_bytes,
            image_mime_type=file.content_type,
        )
        log_ai(db, user.id, "chat", True, response_type=result.get("source", "AI"))
        return {
            "conversation_id": result["conversation_id"],
            "title": result["title"],
            "user_message": {"id": result["user_message"].id, "role": result["user_message"].role, "content": result["user_message"].content, "created_at": result["user_message"].created_at},
            "assistant_message": {"id": result["assistant_message"].id, "role": result["assistant_message"].role, "content": result["assistant_message"].content, "created_at": result["assistant_message"].created_at},
            "provider": result.get("provider", "local-fallback"),
            "source": result.get("source", "AI"),
        }
    except (OverflowError, ValueError, LookupError) as exc:
        db.rollback()
        status_code = 409 if isinstance(exc, OverflowError) else 422 if isinstance(exc, ValueError) else 404
        raise HTTPException(status_code, str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Image chat failed for user_id=%s", user.id)
        log_ai(db, user.id, "chat", False, str(exc))
        if isinstance(exc, GeminiServiceError):
            raise HTTPException(503, f"Gemini tạm thời không thể xử lý ảnh ({exc.category}).") from exc
        raise HTTPException(503, "Không thể xử lý ảnh lúc này.") from exc


@app.delete("/api/chat/conversations/{conversation_id}")
def delete_chat_conversation(conversation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversation = get_owned_conversation(db, conversation_id, user.id)
    db.delete(conversation)
    db.commit()
    return {"ok": True}


@app.post("/api/ai/suggest-budget")
def ai_suggest(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        text = ai_mock_suggest(db, user.id)
        created_at = datetime.utcnow()
        scope_key = f"budget-suggest-{created_at.strftime('%Y%m%d%H%M%S%f')}"
        db.add(AIGeneration(user_id=user.id, kind="suggest", scope_key=scope_key, title="Gợi ý ngân sách", content=text, created_at=created_at, updated_at=created_at))
        db.commit()
        log_ai(db, user.id, "suggest", True)
        return {"content": text, "provider": "local", "scope_key": scope_key}
    except Exception as e:
        logger.exception("Budget suggestion failed for user_id=%s", user.id)
        log_ai(db, user.id, "suggest", False, str(e))
        raise HTTPException(503, "Không thể tạo gợi ý ngân sách lúc này.") from e


@app.post("/api/ai/predict-goal/{goal_id}")
def ai_predict_goal(goal_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    g = db.query(SavingGoal).filter(SavingGoal.id == goal_id, SavingGoal.user_id == user.id).first()
    if not g:
        raise HTTPException(404, "Không tìm thấy mục tiêu")
    remain = max(0, g.target_amount - g.current_amount)
    pct = round(g.current_amount / g.target_amount * 100) if g.target_amount else 0
    msg = f"🎯 Dự đoán mục tiêu \"{g.name}\"\n\n• Tiến độ: {pct}% ({g.current_amount:,.0f} / {g.target_amount:,.0f}đ)\n• Còn thiếu: {remain:,.0f}đ\n"
    if pct >= 100:
        msg += "\n✅ Đã hoàn thành mục tiêu!"
    elif g.deadline:
        days = max(1, (g.deadline - date.today()).days)
        msg += f"• Còn {days} ngày đến hạn\n"
        msg += f"• Cần khoảng {remain/days:,.0f}đ/ngày hoặc {remain/(days/30):,.0f}đ/tháng\n"
    log_ai(db, user.id, "predict", True)
    return {"content": msg}


# ========== ADMIN ==========
@app.get("/api/admin/stats")
def admin_stats(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Chỉ tổng hợp — không lộ chi tiết giao dịch từng user."""
    users = db.query(User).filter(User.role != "admin").all()
    total_users = len(users)
    active_users = sum(1 for u in users if u.status == "active")
    locked = sum(1 for u in users if u.status == "locked")
    total_tx = db.query(func.count(Transaction.id)).scalar() or 0
    total_income = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.type == "income"
    ).scalar() or 0
    total_expense = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.type == "expense"
    ).scalar() or 0
    ai_chat = db.query(func.count(AILog.id)).filter(AILog.kind == "chat").scalar() or 0
    ai_report = db.query(func.count(AIGeneration.id)).filter(AIGeneration.kind == "report").scalar() or 0
    ai_suggest = db.query(func.count(AIGeneration.id)).filter(AIGeneration.kind == "suggest").scalar() or 0
    ai_usage = db.query(func.count(AILog.id)).scalar() or 0
    ai_fail = db.query(func.count(AILog.id)).filter(AILog.success == False).scalar() or 0
    today = date.today()
    month_points = []
    for offset in range(11, -1, -1):
        month_index = today.year * 12 + today.month - 1 - offset
        year, month_zero = divmod(month_index, 12)
        month = month_zero + 1
        month_points.append({
            "label": f"T{month}/{year}",
            "users": db.query(func.count(User.id)).filter(
                User.role != "admin", func.extract("month", User.created_at) == month,
                func.extract("year", User.created_at) == year
            ).scalar() or 0,
            "transactions": db.query(func.count(Transaction.id)).filter(
                func.extract("month", Transaction.created_at) == month,
                func.extract("year", Transaction.created_at) == year
            ).scalar() or 0,
            "income": float(db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                Transaction.type == "income", func.extract("month", Transaction.created_at) == month,
                func.extract("year", Transaction.created_at) == year
            ).scalar() or 0),
            "expense": float(db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                Transaction.type == "expense", func.extract("month", Transaction.created_at) == month,
                func.extract("year", Transaction.created_at) == year
            ).scalar() or 0),
            "ai_usage": db.query(func.count(AILog.id)).filter(
                func.extract("month", AILog.created_at) == month,
                func.extract("year", AILog.created_at) == year
            ).scalar() or 0,
        })
    return {
        "total_users": total_users,
        "active_users": active_users,
        "locked_users": locked,
        "total_transactions": total_tx,
        "total_income": float(total_income),
        "total_expense": float(total_expense),
        "ai_chat_count": ai_chat,
        "ai_report_count": ai_report,
        "ai_suggest_count": ai_suggest,
        "ai_usage_count": ai_usage,
        "ai_fail_count": ai_fail,
        "ai_status": (
            "Mock cục bộ"
            if AI_PROVIDER == "mock"
            else "Đã cấu hình"
            if (
                (AI_PROVIDER == "gemini" and os.getenv("GEMINI_API_KEY"))
                or (AI_PROVIDER == "openai" and (os.getenv("OPENAI_API_KEY") or AI_API_KEY))
            )
            else "Chưa cấu hình API key"
        ),
        "ai_provider": AI_PROVIDER,
        "by_month": month_points,
        "database_type": "SQLite" if DATABASE_URL.startswith("sqlite") else "MySQL" if DATABASE_URL.startswith("mysql") else DATABASE_URL.split(":", 1)[0].upper(),
    }


@app.get("/api/admin/users", response_model=List[UserAdminOut])
def admin_list_users(
    q: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    if q:
        query = query.filter(
            (User.email.ilike(f"%{q}%")) | (User.full_name.ilike(f"%{q}%"))
        )
    users = query.order_by(User.created_at.desc()).all()
    now = datetime.utcnow()
    changed = False
    result = []
    for user in users:
        previous_locked_until = user.locked_until
        previous_failed_count = user.failed_login_count
        effective_status = sync_temporary_lock(user, now)
        changed = changed or previous_locked_until != user.locked_until or previous_failed_count != user.failed_login_count
        if status_filter == "locked" and effective_status not in ("disabled", "temporary_locked"):
            continue
        if status_filter == "active" and effective_status != "active":
            continue
        result.append({
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "status": effective_status,
            "is_active": effective_status == "active",
            "locked_until": user.locked_until,
            "created_at": user.created_at,
        })
    if changed:
        db.commit()
    return result


@app.put("/api/admin/users/{user_id}/status")
def admin_set_status(user_id: int, body: StatusUpdateIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.status not in ("active", "locked"):
        raise HTTPException(400, "status phải là active hoặc locked")
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "Không tìm thấy user")
    if u.id == admin.id:
        raise HTTPException(400, "Không thể khóa hoặc mở khóa chính tài khoản của bạn")
    if u.role == "admin" and body.status == "locked":
        active_admins = db.query(User).filter(User.role == "admin", User.status == "active").count()
        if active_admins <= 1:
            raise HTTPException(400, "Hệ thống phải luôn có ít nhất một admin đang hoạt động")
    u.status = body.status
    if body.status == "active":
        u.locked_until = None
        u.failed_login_count = 0
    db.commit()
    return {"ok": True, "status": u.status}


@app.put("/api/admin/users/{user_id}/role")
def admin_set_role(user_id: int, body: RoleUpdateIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.role not in ("user", "admin"):
        raise HTTPException(400, "role phải là user hoặc admin")
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "Không tìm thấy user")
    if u.id == admin.id:
        raise HTTPException(400, "Không thể tự thay đổi quyền của chính bạn")
    if u.role == "admin" and body.role == "user" and u.status == "active":
        active_admins = db.query(User).filter(User.role == "admin", User.status == "active").count()
        if active_admins <= 1:
            raise HTTPException(400, "Hệ thống phải luôn có ít nhất một admin đang hoạt động")
    u.role = body.role
    db.commit()
    return {"ok": True, "role": u.role}


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "Không tìm thấy user")
    if u.id == admin.id:
        raise HTTPException(400, "Không thể tự xóa chính tài khoản của bạn")
    if u.role == "admin" and u.status == "active":
        active_admins = db.query(User).filter(User.role == "admin", User.status == "active").count()
        if active_admins <= 1:
            raise HTTPException(400, "Hệ thống phải luôn có ít nhất một admin đang hoạt động")
    db.delete(u)  # cascade xóa categories, transactions...
    db.commit()
    return {"ok": True}


@app.get("/api/admin/default-categories")
def admin_default_cats(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(DefaultCategory).all()


@app.get("/api/admin/logs")
def admin_logs(limit: int = 50, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    logs = db.query(SystemLog).order_by(SystemLog.created_at.desc()).limit(limit).all()
    return [
        {"id": l.id, "level": l.level, "source": l.source, "message": l.message,
         "created_at": l.created_at.isoformat() if l.created_at else None}
        for l in logs
    ]


@app.get("/api/admin/ai-logs")
def admin_ai_logs(limit: int = 50, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Chỉ metadata — không có nội dung chat/report."""
    logs = db.query(AILog).order_by(AILog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": l.id, "user_id": l.user_id, "kind": l.kind,
            "success": l.success, "error_message": l.error_message,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]


# ---------- Serve frontend ----------
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root():
    index = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index):
        return FileResponse(index, headers={"Cache-Control": "no-store"})
    return {"message": "Chi tiêu AI API", "docs": "/docs"}


@app.get("/admin")
def admin_page():
    path = os.path.join(STATIC_DIR, "admin.html")
    if os.path.isfile(path):
        return FileResponse(path, headers={"Cache-Control": "no-store"})
    return {"message": "Đặt admin.html vào static/"}


@app.get("/login")
def login_page():
    path = os.path.join(STATIC_DIR, "login.html")
    if os.path.isfile(path):
        return FileResponse(path, headers={"Cache-Control": "no-store"})
    return {"message": "Đặt login.html vào static/"}
