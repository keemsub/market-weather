"""구름이에게 질문하기 + 주간 투자 리포트.

둘 다 '규칙으로 사실 모으기 → LLM이 말로 풀기 → 안 되면 규칙 문장' 순서예요.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from app.coach import Coach
from app.db import Trade
from app.market import MARKETS, SECTOR_OF, STOCKS, Quote, forecast, weather_for

# ---------------------------------------------------------------------------
# 공통: 시세·지갑을 짧은 글로
# ---------------------------------------------------------------------------


def _fmt_price(q: Quote) -> str:
    return f"${q.price:,.2f}" if q.currency == "USD" else f"{q.price:,.0f}원"


def market_brief(snap: dict) -> str:
    lines = []
    for m, label in MARKETS.items():
        fc = forecast(snap, m)
        idx = ", ".join(
            f"{i['name']} {i['price']:,.2f} ({i['change_pct']:+.2f}%, {i['weather']['label']})"
            for i in fc["indices"]
        )
        secs = ", ".join(
            f"{s['name']} {s['change_pct']:+.2f}% {s['weather']['label']}" for s in fc["sectors"]
        )
        src = " (연습용 가짜 시세)" if fc["source"] == "demo" else ""
        lines.append(f"[{label}{src}] 지수: {idx}\n업종: {secs}")
    lines.append(f"환율: 1달러 = {snap['fx']['usdkrw']:,.1f}원")
    return "\n".join(lines)


def portfolio_brief(pf: dict) -> str:
    head = (
        f"총자산 {pf['total']:,}원 (시작 {pf['start']:,}원 대비 {pf['return_pct']:+.2f}%), "
        f"현금 {pf['cash']:,}원"
    )
    if not pf["holdings"]:
        return head + ", 보유 종목 없음"
    rows = "; ".join(
        f"{h['name']} {h['qty']}주 평가 {h['value']:,}원 "
        f"({h['pnl_pct']:+.2f}%, 오늘 {h['today_pct']:+.2f}%)"
        for h in pf["holdings"]
    )
    return f"{head}\n보유: {rows}"


def find_stocks(text: str) -> list[str]:
    """질문에 나온 종목 코드들 (한글 이름, 국내 종목 번호, 미국 티커로 찾아요)."""
    low = text.lower()
    found = []
    for code, st in STOCKS.items():
        names = {st.name.lower()} | {n.lower() for n in re.split(r"[()·]", st.name) if len(n) >= 2}
        hit = any(n in low for n in names)
        if not hit and code.isdigit():
            hit = code in low
        if not hit and code.isalpha() and len(code) >= 2:
            hit = re.search(rf"(?<![a-z]){code.lower()}(?![a-z])", low) is not None
        if hit:
            found.append(code)
    return found[:5]


def stock_brief(code: str, snap: dict, pf: dict) -> str:
    q: Quote | None = snap["stocks"].get(code)
    if not q:
        return ""
    sec = SECTOR_OF[code]
    fc = forecast(snap, sec.market)
    sec_info = next((s for s in fc["sectors"] if s["id"] == sec.id), None)
    w = weather_for(q.change_pct)
    held = next((h for h in pf["holdings"] if h["code"] == code), None)
    parts = [
        f"{q.name}({code}, {MARKETS[sec.market]} {sec.name}): 지금 {_fmt_price(q)}, "
        f"오늘 {q.change_pct:+.2f}% ({w.emoji} {w.label})"
    ]
    if sec_info:
        parts.append(
            f"같은 업종 평균 {sec_info['change_pct']:+.2f}% ({sec_info['weather']['label']}, "
            f"강수확률 {sec_info['rain_chance']}%)"
        )
    parts.append(
        f"내 보유: {held['qty']}주, 수익률 {held['pnl_pct']:+.2f}%" if held else "내 보유: 없음"
    )
    return " / ".join(parts)


# ---------------------------------------------------------------------------
# 구름이에게 질문하기
# ---------------------------------------------------------------------------
ASK_SYSTEM = (
    "당신은 주식 모의투자 앱의 코치 '구름이'예요. 시장을 날씨에 빗대어 쉽게 설명해요. "
    "아래 '지금 시장', '내 지갑', '물어본 종목' 자료만 근거로 초보자에게 3~5문장으로 답해요. "
    "존댓말, 이모지는 1개까지. 자료에 뉴스나 공시는 없으니, 오르내린 '이유'를 물으면 "
    "업종 전체 흐름인지 그 종목만의 움직임인지 자료로 구분해 주고, 정확한 이유는 뉴스·공시를 "
    "확인해 보라고 안내해요. 숫자나 뉴스를 지어내지 말고, "
    "사라·팔라는 권유나 가격 예측은 하지 마세요. "
    "투자 공부와 습관에 대한 일반 질문에는 쉬운 예를 들어 답해요."
)


GLOSSARY: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("분산",),
        "분산 투자는 달걀을 여러 바구니에 나눠 담는 거예요. 🧺 한 업종에 비가 와도 다른 업종이 "
        "맑으면 전체 지갑은 덜 젖어요. 업종이 다른 종목 3~5개로 나눠 보는 것부터 시작해 보세요.",
    ),
    (
        ("손절",),
        "손절은 '여기까지 내리면 판다'는 선을 미리 정해 두고 지키는 거예요. 사기 전에 "
        "예를 들어 -7% 같은 선을 적어 두면, 비가 쏟아질 때 덜 흔들려요.",
    ),
    (
        ("추격",),
        "추격 매수는 이미 많이 오른 종목을 뒤늦게 따라 사는 거예요. 쨍쨍한 날 뒤엔 소나기가 "
        "오기도 해서, 꼭대기에서 사기 쉬워요. 왜 사는지 한 줄 적어 보고 사면 좋아요.",
    ),
    (
        ("수수료", "세금"),
        "이 앱은 실제처럼 살 때 수수료 0.015%, 팔 때 수수료와 세금 0.195%를 떼요. "
        "자주 사고팔수록 이게 쌓여서 수익을 갉아먹어요.",
    ),
)


def rule_answer(question: str, codes: list[str], snap: dict, pf: dict) -> str:
    if codes:
        out = []
        for code in codes[:2]:
            q = snap["stocks"][code]
            sec = SECTOR_OF[code]
            fc = forecast(snap, sec.market)
            s = next(x for x in fc["sectors"] if x["id"] == sec.id)
            w = weather_for(q.change_pct)
            same_way = (q.change_pct >= 0) == (s["change_pct"] >= 0)
            why = (
                f"{sec.name} 업종 전체가 {s['weather']['label']}({s['change_pct']:+.2f}%)이라 "
                "업종 흐름을 같이 탄 것 같아요."
                if same_way
                else f"{sec.name} 업종은 {s['weather']['label']}({s['change_pct']:+.2f}%)인데 "
                "혼자 반대로 움직였어요. 이 종목만의 소식이 있었을 수 있어요."
            )
            out.append(f"{q.name}은 오늘 {q.change_pct:+.2f}%로 {w.emoji} {w.label}이에요. {why}")
        out.append("정확한 이유는 뉴스나 공시에서 확인해 보세요.")
        return " ".join(out)
    for keys, answer in GLOSSARY:
        if any(k in question for k in keys):
            return answer
    if any(k in question for k in ("내 ", "지갑", "포트폴리오", "수익", "보유")):
        tail = f" 가장 큰 종목은 {pf['holdings'][0]['name']}이에요." if pf["holdings"] else ""
        return (
            f"지금 총자산은 {pf['total']:,}원, 수익률은 {pf['return_pct']:+.2f}%예요. "
            f"현금은 {pf['cash']:,}원 남아 있어요.{tail}"
        )
    kr = forecast(snap, "KR")["indices"][0]
    us = forecast(snap, "US")["indices"][0]
    return (
        f"오늘 {kr['name']}는 {kr['weather']['emoji']} {kr['weather']['label']}"
        f"({kr['change_pct']:+.2f}%), {us['name']}는 {us['weather']['emoji']} "
        f"{us['weather']['label']}({us['change_pct']:+.2f}%)예요. "
        "종목 이름을 넣어 물어보면 그 종목 날씨를 자세히 알려 드릴게요. "
        "(지금은 AI 키가 없어 간단한 답만 할 수 있어요)"
    )


def ask(coach: Coach, question: str, history: list[dict], snap: dict, pf: dict) -> tuple[str, str]:
    asked = find_stocks(question)
    # 앞선 대화에 나온 종목도 LLM에게 자료로 줘요 ("그럼 그 종목은?" 같은 질문용)
    recent = find_stocks(" ".join(h.get("text", "") for h in history[-2:]))
    codes = list(dict.fromkeys(asked + recent))[:5]
    stock_lines = "\n".join(filter(None, (stock_brief(c, snap, pf) for c in codes)))
    convo = "\n".join(
        f"{'나' if h.get('role') == 'user' else '구름이'}: {h.get('text', '')[:300]}"
        for h in history[-6:]
    )
    user = (
        f"[지금 시장]\n{market_brief(snap)}\n\n[내 지갑]\n{portfolio_brief(pf)}\n\n"
        f"[물어본 종목]\n{stock_lines or '없음'}\n\n"
        + (f"[앞선 대화]\n{convo}\n\n" if convo else "")
        + f"[질문]\n{question}"
    )
    return coach.say(ASK_SYSTEM, user, rule_answer(question, asked, snap, pf))


# ---------------------------------------------------------------------------
# 주간 투자 리포트
# ---------------------------------------------------------------------------
REPORT_SYSTEM = (
    "당신은 주식 모의투자 앱의 코치 '구름이'예요. 아래 '이번 주 기록'만 근거로 초보 투자자에게 "
    "주간 리포트 한마디를 써요. 형식: 첫 줄에 이번 주를 날씨 한 단어로 요약한 제목, "
    "이어서 잘한 점 1개, 고칠 점 1개, 다음 주에 해 볼 작은 약속 1개를 각각 한두 문장으로. "
    "존댓말, 따뜻하게, 숫자는 자료에 있는 것만 쓰고, 종목 매수·매도 권유나 가격 예측은 하지 마세요."
)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def weekly_stats(trades: list[Trade], pf: dict, now: datetime | None = None, days: int = 7) -> dict:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    realized = 0.0
    wins = losses = 0
    chase = flips = 0
    per_day: Counter[str] = Counter()
    names: Counter[str] = Counter()
    sectors: Counter[str] = Counter()
    pos: dict[str, list[float]] = {}  # code -> [qty, cost]
    last_buy: dict[str, datetime] = {}
    week: list[Trade] = []

    for t in trades:  # 오래된 것부터
        at = _aware(t.created_at)
        in_week = at >= since
        qty_cost = pos.setdefault(t.code, [0, 0.0])
        if t.side == "buy":
            qty_cost[0] += t.qty
            qty_cost[1] += t.qty * t.price
            last_buy[t.code] = at
            if in_week and t.change_pct >= 5:
                chase += 1
        else:
            avg = qty_cost[1] / qty_cost[0] if qty_cost[0] else t.price
            qty_cost[0] -= t.qty
            qty_cost[1] -= t.qty * avg
            if in_week:
                gain = (t.price - avg) * t.qty
                realized += gain
                wins += gain > 0
                losses += gain < 0
                lb = last_buy.get(t.code)
                if lb and at - lb < timedelta(minutes=10):
                    flips += 1
        if in_week:
            week.append(t)
            per_day[at.date().isoformat()] += 1
            names[t.name] += 1
            sec = SECTOR_OF.get(t.code)
            if sec:
                sectors[f"{MARKETS[sec.market]} {sec.name}"] += 1

    top_share = 0.0
    if pf["holdings"] and pf["total"]:
        top_share = round(pf["holdings"][0]["value"] / pf["total"] * 100, 1)
    sells = wins + losses
    return {
        "days": days,
        "trades": len(week),
        "buys": sum(1 for t in week if t.side == "buy"),
        "sells": sum(1 for t in week if t.side == "sell"),
        "realized": round(realized),
        "win_rate": round(wins / sells * 100) if sells else None,
        "chase_buys": chase,
        "quick_flips": flips,
        "busiest_day": max(per_day.values()) if per_day else 0,
        "top_stocks": [n for n, _ in names.most_common(3)],
        "top_sectors": [n for n, _ in sectors.most_common(3)],
        "total": pf["total"],
        "return_pct": pf["return_pct"],
        "cash_pct": round(pf["cash"] / pf["total"] * 100, 1) if pf["total"] else 100.0,
        "top_holding": pf["holdings"][0]["name"] if pf["holdings"] else None,
        "top_holding_pct": top_share,
        "holdings": len(pf["holdings"]),
    }


def report_weather(st: dict) -> dict:
    """이번 주를 날씨 하나로: 수익률 + 습관 점수."""
    score = st["return_pct"]
    score -= 0.5 * st["chase_buys"] + 0.5 * st["quick_flips"]
    if st["busiest_day"] >= 10:
        score -= 1
    return asdict(weather_for(score))


def rule_report(st: dict) -> str:
    if st["trades"] == 0:
        return (
            "이번 주는 조용히 하늘만 바라본 한 주였어요. ☁️ "
            "관심 업종 하나를 골라 날씨를 매일 확인해 보는 것부터 시작해 봐요."
        )
    good, fix = [], []
    if st["win_rate"] is not None and st["win_rate"] >= 50:
        good.append(f"판 매매 중 {st['win_rate']}%가 수익이었어요")
    if st["chase_buys"] == 0:
        good.append("급등한 종목을 쫓아 사지 않았어요")
    if st["cash_pct"] >= 20:
        good.append(f"현금을 {st['cash_pct']:.0f}% 남겨 여유가 있어요")
    if st["chase_buys"]:
        fix.append(f"이미 많이 오른 종목을 {st['chase_buys']}번 따라 샀어요")
    if st["quick_flips"]:
        fix.append(f"10분 안에 사고판 단타가 {st['quick_flips']}번 있었어요")
    if st["top_holding_pct"] >= 40:
        fix.append(f"{st['top_holding']}에 자산의 {st['top_holding_pct']:.0f}%가 몰려 있어요")
    if st["busiest_day"] >= 10:
        fix.append(f"하루에 {st['busiest_day']}번 매매한 날이 있었어요")
    g = good[0] if good else "꾸준히 시장을 들여다봤어요"
    f = fix[0] if fix else "특별히 고칠 점은 없어요. 지금 리듬을 유지해요"
    return (
        f"👍 잘한 점: {g}.\n🔧 고칠 점: {f}.\n"
        "🤙 다음 주 약속: 사기 전에 '왜 사는지' 한 줄 메모를 남겨 봐요."
    )


def weekly_report(coach: Coach, trades: list[Trade], pf: dict) -> dict:
    st = weekly_stats(trades, pf)
    facts = (
        f"기간 최근 {st['days']}일, 매매 {st['trades']}번(매수 {st['buys']}, 매도 {st['sells']}), "
        f"실현 손익 {st['realized']:,}원, 매도 승률 "
        f"{'없음' if st['win_rate'] is None else str(st['win_rate']) + '%'}, "
        f"추격 매수 {st['chase_buys']}번, 10분 단타 {st['quick_flips']}번, "
        f"하루 최다 매매 {st['busiest_day']}번, "
        f"많이 거래한 종목 {', '.join(st['top_stocks']) or '없음'}, "
        f"많이 거래한 업종 {', '.join(st['top_sectors']) or '없음'}, "
        f"총자산 {st['total']:,}원(시작 대비 {st['return_pct']:+.2f}%), "
        f"현금 비중 {st['cash_pct']}%, "
        f"가장 큰 보유 {st['top_holding'] or '없음'} {st['top_holding_pct']}%"
    )
    text, source = coach.say(REPORT_SYSTEM, f"[이번 주 기록]\n{facts}", rule_report(st))
    return {"stats": st, "weather": report_weather(st), "text": text, "source": source}
