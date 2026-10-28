"""
Kết nối MySQL / SQLite qua SQLAlchemy.
Đọc DATABASE_URL từ file .env
"""
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./chi_tieu_ai.db"  # fallback khi chưa cấu hình MySQL
)

# MySQL cần pool_pre_ping; SQLite cần check_same_thread
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args=connect_args,
    echo=False,
)

# SQLite does not enforce declared foreign keys unless this is enabled for every
# connection.  This does not alter the schema or existing records.
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency FastAPI: mỗi request 1 session, đóng khi xong."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
