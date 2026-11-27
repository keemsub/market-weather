"""서버의 시작점. `uv run uvicorn app.main:app --reload` 로 실행합니다."""

import time
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

from app.coach import Coach, find_facts, make_llm, rule_comment
from app.config import get_settings
from app.db import Account, Trade, get_db
from app.insights import ask, weekly_report
from app.market import (
    MARKETS,
    SECTOR_OF,
    ChainQuotes,
    DemoQuotes,
    MarketData,
    NaverQuotes,
    NaverWorldQuotes,
    YahooQuotes,
    forecast,
)
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
    if s.market_source == "demo":
        return MarketData({"KR": DemoQuotes(), "US": DemoQuotes()}, s.quote_cache_seconds)
    # 미국: 네이버 해외주식 → 안 되면 야후 → 그래도 안 되면 연습용
    naver_world, yahoo = NaverWorldQuotes(), YahooQuotes()
    return MarketData(
        {"KR": NaverQuotes(), "US": ChainQuotes(naver_world, yahoo)},
        s.quote_cache_seconds,
        fx_provider=[naver_world, yahoo],
    )


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


@app.get("/health/data")
def health_data(market: Market):
    """시세 출처 상태: 어느 시장이 연습용인지, 왜 실패했는지."""
    snap = market.snapshot()
    return {"sources": snap["sources"], "fx": snap["fx"], "errors": snap["errors"]}


@app.get("/api/weather")
def weather(market: Market, m: str = "KR"):
    return forecast(market.snapshot(), m if m in MARKETS else "KR")


@app.get("/api/portfolio")
def portfolio(db: DB, me: Me, market: Market):
    snap = market.snapshot()
    data = summary(me, trades_of(db, me), snap["stocks"], get_settings().starting_cash)
    data["coach_mode"] = get_coach().llm.name if get_coach().llm else "rule"
    return data


class TradeIn(BaseModel):
    code: str = Field(min_length=1, max_length=12)
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

    # 매매와 현금 변화는 바로 저장해요. (AI 코치를 기다리다 실패해도 매매는 남도록)
    facts, line = _coach_inputs(t, db, me, snap)
    t.coach, t.coach_source = rule_comment(facts), "rule"
    db.commit()

    data = summary(me, trades_of(db, me), snap["stocks"], get_settings().starting_cash)
    data["coach_mode"] = get_coach().llm.name if get_coach().llm else "rule"
    return {
        "trade": {"id": t.id, "name": t.name, "side": t.side, "qty": t.qty, "price": t.price},
        "fx": snap["fx"],
        "coach": {"text": t.coach, "source": t.coach_source},
        "portfolio": data,
    }


def _coach_inputs(t: Trade, db: Session, me: Account, snap: dict) -> tuple[list, str]:
    history = [x for x in trades_of(db, me) if x.id <= t.id]
    sector = SECTOR_OF.get(t.code)
    fc = forecast(snap, sector.market if sector else "KR")
    sector_pct = next(
        (s["change_pct"] for s in fc["sectors"] if sector and s["id"] == sector.id), None
    )
    facts = find_facts(t, history, snap["stocks"], me.cash, sector_pct)
    pf = summary(me, history, snap["stocks"], get_settings().starting_cash)
    line = (
        f"총자산 {pf['total']:,}원 (수익률 {pf['return_pct']:+.2f}%), "
        f"현금 {pf['cash']:,}원, 보유 {len(pf['holdings'])}종목"
    )
    return facts, line


@app.post("/api/trade/{trade_id}/coach")
def trade_coach(trade_id: int, db: DB, me: Me, market: Market):
    """매매 직후 AI 코치 한마디 (따로 불러서, 느려도 매매에는 영향이 없어요)."""
    t = db.get(Trade, trade_id)
    if t is None or t.account_id != me.id:
        raise HTTPException(404, "매매 기록을 찾을 수 없어요.")
    if t.coach_source != "rule" or get_coach().llm is None:
        return {"text": t.coach, "source": t.coach_source}
    facts, line = _coach_inputs(t, db, me, market.snapshot())
    text, source = get_coach().comment(t, facts, line)
    if source != "rule":
        t.coach, t.coach_source = text, source
        db.commit()
    return {"text": t.coach, "source": t.coach_source}


class ChatTurn(BaseModel):
    role: Literal["user", "coach"]
    text: str = Field(max_length=1200)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)


@app.post("/api/ask")
def ask_coach(body: AskIn, db: DB, me: Me, market: Market):
    snap = market.snapshot()
    pf = summary(me, trades_of(db, me), snap["stocks"], get_settings().starting_cash)
    history = [h.model_dump() for h in body.history]
    text, source = ask(get_coach(), body.question.strip(), history, snap, pf)
    return {"text": text, "source": source}


@app.get("/api/report")
def report(db: DB, me: Me, market: Market):
    snap = market.snapshot()
    trades = trades_of(db, me)
    key = (me.id, len(trades), trades[-1].id if trades else 0)
    cached = _report_cache.get(me.id)
    if cached and cached[0] == key and time.monotonic() - cached[1] < 1800:
        return cached[2]
    pf = summary(me, trades, snap["stocks"], get_settings().starting_cash)
    data = weekly_report(get_coach(), trades, pf)
    if data["source"] != "rule":  # AI 리포트는 매매가 없으면 30분 동안 재사용 (무료 한도 아끼기)
        _report_cache[me.id] = (key, time.monotonic(), data)
    return data


_report_cache: dict[int, tuple[tuple, float, dict]] = {}


@app.post("/api/reset")
def reset(db: DB, me: Me):
    db.query(Trade).filter(Trade.account_id == me.id).delete()
    me.cash = get_settings().starting_cash
    db.commit()
    return {"ok": True}
