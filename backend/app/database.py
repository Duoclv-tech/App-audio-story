from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings
from loguru import logger

SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL
_is_sqlite = SQLALCHEMY_DATABASE_URL.startswith("sqlite")

logger.info(f"Connecting to database: {SQLALCHEMY_DATABASE_URL}")

if _is_sqlite:
    # Desktop/default mode: single-file SQLite.
    # - check_same_thread=False: FastAPI touches the DB from background tasks
    #   and the video worker's daemon thread, not just the request thread.
    # - keep the default QueuePool (one connection per thread) so a long video
    #   write doesn't serialize every other query (StaticPool would).
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
        echo=settings.DEBUG,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")     # concurrent read while writing
        cur.execute("PRAGMA foreign_keys=ON")      # SQLite defaults OFF -> enable cascade delete
        cur.execute("PRAGMA busy_timeout=5000")    # wait instead of instantly erroring on lock
        cur.execute("PRAGMA synchronous=NORMAL")   # safe with WAL, much faster
        cur.close()
else:
    # Legacy MySQL mode (kept for anyone overriding DATABASE_URL via .env).
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        echo=settings.DEBUG,
        pool_recycle=3600,
    )

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()

# Dependency for FastAPI
def get_db():
    """Database session dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Initialize database (create tables if not exist)"""
    logger.info("Initializing database...")
    # Import models so every table is registered on Base.metadata before create_all.
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized successfully")

def test_connection():
    """Test database connection"""
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        logger.info("Database connection successful")
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False
