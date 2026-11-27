"""데이터베이스: 익명 계정(Account)과 매매 기록(Trade).

내 컴퓨터에서는 SQLite 파일, 배포할 땐 DATABASE_URL(Postgres, 예: Neon 무료)을 써요.
처음 실행할 때 표가 없으면 자동으로 만들어요.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import ForeignKey, String, Text, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    cash: Mapped[float] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    code: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(60))
    side: Mapped[str] = mapped_column(String(4))  # buy / sell
    qty: Mapped[int] = mapped_column()
    price: Mapped[float] = mapped_column()
    change_pct: Mapped[float] = mapped_column(default=0)  # 매매 순간의 그날 등락률
    coach: Mapped[str] = mapped_column(Text, default="")
    coach_source: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)


def normalize_url(url: str) -> str:
    # Neon·Supabase가 주는 postgres:// 주소를 SQLAlchemy가 쓰는 형식으로 바꿔요.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


@lru_cache
def get_engine() -> Engine:
    url = normalize_url(get_settings().database_url)
    kwargs = (
        {"connect_args": {"check_same_thread": False}}
        if url.startswith("sqlite")
        else {"pool_pre_ping": True}
    )
    engine = create_engine(url, **kwargs)
    Base.metadata.create_all(engine)
    return engine


@lru_cache
def _sessionmaker() -> sessionmaker:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with _sessionmaker()() as db:
        yield db
