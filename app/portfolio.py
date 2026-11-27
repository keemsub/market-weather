"""모의투자 계산: 보유 종목, 평가금액, 수익률, 매수·매도."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Account, Trade
from app.market import SECTOR_OF, Quote

FEE_RATE = 0.00015  # 증권사 수수료 흉내 (0.015%)
TAX_RATE = 0.0018  # 매도할 때 세금 흉내 (0.18%)


class TradeError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 매매 오류."""


@dataclass
class Holding:
    code: str
    name: str
    qty: int = 0
    cost: float = 0.0  # 남은 수량의 총 매입금액

    @property
    def avg_price(self) -> float:
        return self.cost / self.qty if self.qty else 0.0


def trades_of(db: Session, account: Account) -> list[Trade]:
    return list(db.scalars(select(Trade).where(Trade.account_id == account.id).order_by(Trade.id)))


def holdings_from(trades: list[Trade]) -> dict[str, Holding]:
    h: dict[str, Holding] = {}
    for t in trades:
        cur = h.setdefault(t.code, Holding(t.code, t.name))
        if t.side == "buy":
            cur.qty += t.qty
            cur.cost += t.qty * t.price
        else:
            avg = cur.avg_price
            cur.qty -= t.qty
            cur.cost -= t.qty * avg
        if cur.qty <= 0:
            h.pop(t.code)
    return h


def summary(account: Account, trades: list[Trade], quotes: dict[str, Quote], start: int) -> dict:
    rows = []
    stock_value = 0.0
    for hd in holdings_from(trades).values():
        q = quotes.get(hd.code)
        price = q.price if q else hd.avg_price
        value = price * hd.qty
        stock_value += value
        sec = SECTOR_OF.get(hd.code)
        rows.append(
            {
                "code": hd.code,
                "name": hd.name,
                "sector": sec.name if sec else "",
                "qty": hd.qty,
                "avg_price": round(hd.avg_price, 2),
                "price": price,
                "today_pct": q.change_pct if q else 0.0,
                "value": round(value),
                "pnl": round(value - hd.cost),
                "pnl_pct": round((value / hd.cost - 1) * 100, 2) if hd.cost else 0.0,
            }
        )
    rows.sort(key=lambda r: -r["value"])
    total = account.cash + stock_value
    return {
        "cash": round(account.cash),
        "stock_value": round(stock_value),
        "total": round(total),
        "start": start,
        "return_pct": round((total / start - 1) * 100, 2),
        "holdings": rows,
        "trades": [
            {
                "id": t.id,
                "code": t.code,
                "name": t.name,
                "side": t.side,
                "qty": t.qty,
                "price": t.price,
                "coach": t.coach,
                "coach_source": t.coach_source,
                "created_at": t.created_at.isoformat(timespec="seconds"),
            }
            for t in reversed(trades[-30:])
        ],
    }


def execute(db: Session, account: Account, quote: Quote, side: str, qty: int) -> Trade:
    """현재가로 바로 체결해요. 실패하면 TradeError."""
    if side not in ("buy", "sell"):
        raise TradeError("매수 또는 매도만 할 수 있어요.")
    if qty <= 0:
        raise TradeError("수량은 1주 이상이어야 해요.")
    if quote.price <= 0:
        raise TradeError("지금은 가격을 알 수 없어요. 잠시 뒤 다시 해 주세요.")

    amount = quote.price * qty
    if side == "buy":
        need = amount * (1 + FEE_RATE)
        if need > account.cash + 1e-6:
            can = int(account.cash // (quote.price * (1 + FEE_RATE)))
            raise TradeError(f"현금이 부족해요. 지금은 최대 {can:,}주까지 살 수 있어요.")
        account.cash -= need
    else:
        held = holdings_from(trades_of(db, account)).get(quote.code)
        have = held.qty if held else 0
        if qty > have:
            raise TradeError(f"가진 주식보다 많이 팔 수 없어요. (보유 {have:,}주)")
        account.cash += amount * (1 - FEE_RATE - TAX_RATE)

    trade = Trade(
        account_id=account.id,
        code=quote.code,
        name=quote.name,
        side=side,
        qty=qty,
        price=quote.price,
        change_pct=quote.change_pct,
    )
    db.add(trade)
    db.flush()
    return trade
