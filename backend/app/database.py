from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        url = settings.database_url.get_secret_value()
        if not url:
            raise RuntimeError(
                "DATABASE_URL is not configured. See backend/README-I1.md."
            )
        if not url.startswith("mysql+pymysql://"):
            raise RuntimeError(
                "DATABASE_URL must use the mysql+pymysql dialect."
            )
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def get_sessionlocal():
    global _SessionLocal
    if _SessionLocal is None:
        url = settings.database_url.get_secret_value()
        if url:
            get_engine()
            _SessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                expire_on_commit=False,
                bind=_engine,
            )
        else:
            # Defer the database error until an actual query is executed so
            # that middleware and validation layers can still respond first.
            _SessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                expire_on_commit=False,
            )
    return _SessionLocal


def get_db():
    SessionLocal = get_sessionlocal()
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
