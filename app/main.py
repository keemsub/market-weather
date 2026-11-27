"""서버의 시작점. `uv run uvicorn app.main:app --reload` 로 실행합니다."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.coach import Coach, find_facts, make_llm
from app.config import get_settings
from app.db import Account, Trade, get_db
from app.market import SECTOR_OF, DemoQuotes, MarketData, NaverQuotes, forecast
from app.portfolio import TradeError, execute, summary, trades_of

BASE_DIR = Path(__file__).parent

app = FastAPI(title="시장 날씨")
settings = get_settings()
# 익명 계정 번호를 서명된 쿠키에 저장해요 (1년 유지). 로그인 없이 바로 시작!
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    https_only=settings.cookie_secure,
    same_site="lax",
    max_age=60 * 60 * 24 * 365,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@lru_cache
def get_market() -> MarketData:
    s = get_settings()
    primary = DemoQuotes() if s.market_source == "demo" else NaverQuotes()
    return MarketData(primary, cache_seconds=s.quote_cache_seconds)


@lru_cache
def get_coach() -> Coach:
    return Coach(make_llm(get_settings()))


DB = Annotated[Session, Depends(get_db)]
Market = Annotated[MarketData, Depends(get_market)]


def current_account(request: Request, db: DB) -> Account:
    acc_id = request.session.get("account_id")
    acc = db.get(Account, acc_id) if acc_id else None
    if acc is None:
        acc = Account(cash=get_settings().starting_cash)
        db.add(acc)
        db.commit()
        request.session["account_id"] = acc.id
    return acc


Me = Annotated[Account, Depends(current_account)]


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/weather")
def weather(market: Market):
    return forecast(market.snapshot())


@app.get("/api/portfolio")
def portfolio(db: DB, me: Me, market: Market):
    snap = market.snapshot()
    data = summary(me, trades_of(db, me), snap["stocks"], get_settings().starting_cash)
    data["coach_mode"] = get_coach().llm.name if get_coach().llm else "rule"
    return data


class TradeIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)
    side: Literal["buy", "sell"]
    qty: int = Field(gt=0, le=1_000_000)


@app.post("/api/trade")
def trade(body: TradeIn, db: DB, me: Me, market: Market):
    snap = market.snapshot()
    quote = snap["stocks"].get(body.code)
    if quote is None:
        raise HTTPException(404, "모르는 종목이에요.")
    try:
        t = execute(db, me, quote, body.side, body.qty)
    except TradeError as e:
        db.rollback()
        raise HTTPException(400, str(e)) from e

    history = trades_of(db, me)
    fc = forecast(snap)
    sector = SECTOR_OF.get(body.code)
    sector_pct = next(
        (s["change_pct"] for s in fc["sectors"] if sector and s["id"] == sector.id), None
    )
    facts = find_facts(t, history, snap["stocks"], me.cash, sector_pct)
    before = summary(me, history, snap["stocks"], get_settings().starting_cash)
    line = (
        f"총자산 {before['total']:,}원 (수익률 {before['return_pct']:+.2f}%), "
        f"현금 {before['cash']:,}원, 보유 {len(before['holdings'])}종목"
    )
    t.coach, t.coach_source = get_coach().comment(t, facts, line)
    db.commit()

    data = summary(me, trades_of(db, me), snap["stocks"], get_settings().starting_cash)
    return {
        "trade": {"id": t.id, "name": t.name, "side": t.side, "qty": t.qty, "price": t.price},
        "coach": {"text": t.coach, "source": t.coach_source},
        "portfolio": data,
    }


@app.post("/api/reset")
def reset(db: DB, me: Me):
    db.query(Trade).filter(Trade.account_id == me.id).delete()
    me.cash = get_settings().starting_cash
    db.commit()
    return {"ok": True}
