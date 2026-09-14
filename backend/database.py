from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import StaticPool
from config import DATABASE_URL

from sqlalchemy import event

engine_options = {
    "connect_args": {"check_same_thread": False, "timeout": 60.0} if "sqlite" in DATABASE_URL else {},
    "echo": False,
}
if DATABASE_URL in {"sqlite://", "sqlite:///:memory:"}:
    engine_options["poolclass"] = StaticPool
elif "sqlite" in DATABASE_URL:
    # A single SQLite file plus a rich, polling SPA and an in-process job
    # worker can easily hold more than the default 5+10 pooled connections
    # at once; undersizing this just turns into spurious request timeouts.
    engine_options["pool_size"] = 20
    engine_options["max_overflow"] = 40
    engine_options["pool_timeout"] = 60

engine = create_engine(DATABASE_URL, **engine_options)

if "sqlite" in DATABASE_URL:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=60000")
            cursor.close()
        except Exception:
            pass

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields a DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Call once at startup."""
    import models  # noqa: F401 — registers models with Base
    import app.persistence.models  # noqa: F401 — local/test schema registration
    Base.metadata.create_all(bind=engine)
