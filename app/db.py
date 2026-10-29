"""Database setup. Read tools run inside a READ ONLY transaction (PostgreSQL)."""
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


_engine = None
_factory = None


def make_engine(url: str):
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
        return create_engine(url, **kwargs)
    return create_engine(url, pool_pre_ping=True)


def set_engine(engine) -> None:
    global _engine, _factory
    _engine = engine
    _factory = sessionmaker(bind=engine, expire_on_commit=False) if engine is not None else None


def get_engine():
    if _engine is None:
        from app.config import get_settings

        set_engine(make_engine(get_settings().database_url))
    return _engine


def init_db() -> None:
    from app import models  # noqa: F401  (register tables)

    Base.metadata.create_all(get_engine())


@contextmanager
def readonly_session():
    get_engine()
    session = _factory()
    try:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION READ ONLY"))
        yield session
    finally:
        session.rollback()
        session.close()


@contextmanager
def write_session():
    get_engine()
    session = _factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
