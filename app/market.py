"""시세 가져오기 + 등락률을 '날씨'로 바꾸기.

- 업종과 종목 목록은 아래 SECTORS에 직접 적어 두었어요. 추가·수정하기 쉬워요.
- 시세는 NaverQuotes(키 필요 없음)로 가져오고, 실패하면 DemoQuotes(연습용)로 바꿔요.
"""

from __future__ import annotations

import hashlib
import random
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

import httpx

KST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# 업종과 종목 (code, 이름, 데모용 기준가)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Stock:
    code: str
    name: str
    base_price: int  # 데모 시세의 출발점 (실제 시세와 다를 수 있어요)


@dataclass(frozen=True)
class Sector:
    id: str
    name: str
    icon: str
    stocks: tuple[Stock, ...]


SECTORS: tuple[Sector, ...] = (
    Sector(
        "semi",
        "반도체",
        "💾",
        (
            Stock("005930", "삼성전자", 70000),
            Stock("000660", "SK하이닉스", 200000),
            Stock("042700", "한미반도체", 90000),
            Stock("000990", "DB하이텍", 40000),
        ),
    ),
    Sector(
        "battery",
        "2차전지",
        "🔋",
        (
            Stock("373220", "LG에너지솔루션", 350000),
            Stock("006400", "삼성SDI", 250000),
            Stock("003670", "포스코퓨처엠", 150000),
            Stock("247540", "에코프로비엠", 120000),
        ),
    ),
    Sector(
        "auto",
        "자동차",
        "🚗",
        (
            Stock("005380", "현대차", 210000),
            Stock("000270", "기아", 95000),
            Stock("012330", "현대모비스", 240000),
        ),
    ),
    Sector(
        "internet",
        "인터넷·게임",
        "🎮",
        (
            Stock("035420", "NAVER", 200000),
            Stock("035720", "카카오", 40000),
            Stock("259960", "크래프톤", 300000),
            Stock("036570", "엔씨소프트", 180000),
        ),
    ),
    Sector(
        "bio",
        "바이오",
        "🧬",
        (
            Stock("207940", "삼성바이오로직스", 1000000),
            Stock("068270", "셀트리온", 180000),
            Stock("196170", "알테오젠", 350000),
            Stock("000100", "유한양행", 110000),
        ),
    ),
    Sector(
        "finance",
        "금융",
        "🏦",
        (
            Stock("105560", "KB금융", 90000),
            Stock("055550", "신한지주", 55000),
            Stock("086790", "하나금융지주", 65000),
            Stock("323410", "카카오뱅크", 22000),
        ),
    ),
    Sector(
        "ship",
        "조선·방산",
        "🚢",
        (
            Stock("329180", "HD현대중공업", 300000),
            Stock("042660", "한화오션", 70000),
            Stock("012450", "한화에어로스페이스", 800000),
            Stock("079550", "LIG넥스원", 350000),
        ),
    ),
    Sector(
        "consumer",
        "엔터·소비재",
        "🎤",
        (
            Stock("352820", "하이브", 230000),
            Stock("041510", "에스엠", 90000),
            Stock("090430", "아모레퍼시픽", 120000),
            Stock("097950", "CJ제일제당", 250000),
        ),
    ),
)

INDICES = (("KOSPI", "코스피", 2600.0), ("KOSDAQ", "코스닥", 750.0))

STOCKS: dict[str, Stock] = {s.code: s for sec in SECTORS for s in sec.stocks}
SECTOR_OF: dict[str, Sector] = {s.code: sec for sec in SECTORS for s in sec.stocks}


# ---------------------------------------------------------------------------
# 날씨 규칙: 등락률(%) → 날씨
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Weather:
    key: str
    emoji: str
    label: str
    line: str  # 한 줄 예보


# (이 값 이상이면, 날씨) — 위에서부터 차례로 확인해요.
WEATHER_SCALE: tuple[tuple[float, Weather], ...] = (
    (2.0, Weather("hot", "☀️", "쨍쨍", "햇볕이 뜨거워요. 너무 들뜨지 않게 조심!")),
    (0.7, Weather("sunny", "🌤️", "맑음", "기분 좋은 상승 바람이 불어요.")),
    (0.2, Weather("partly", "⛅", "구름 조금", "살짝 오르는 중, 대체로 포근해요.")),
    (-0.2, Weather("cloudy", "☁️", "흐림", "큰 움직임 없이 잔잔해요.")),
    (-0.7, Weather("shower", "🌦️", "소나기", "가볍게 내리는 중이에요. 우산 하나 챙기세요.")),
    (-2.0, Weather("rain", "🌧️", "비", "하락 비가 꽤 내려요.")),
    (float("-inf"), Weather("storm", "⛈️", "천둥번개", "큰 폭으로 떨어지는 중! 차분하게 지켜봐요.")),
)


def weather_for(change_pct: float) -> Weather:
    for threshold, w in WEATHER_SCALE:
        if change_pct >= threshold:
            return w
    return WEATHER_SCALE[-1][1]


# ---------------------------------------------------------------------------
# 시세
# ---------------------------------------------------------------------------
@dataclass
class Quote:
    code: str
    name: str
    price: float
    change: float  # 전일 대비 (원 / 포인트)
    change_pct: float  # 전일 대비 (%)


class QuoteProvider(Protocol):
    name: str

    def stocks(self, codes: list[str]) -> dict[str, Quote]: ...
    def indices(self) -> dict[str, Quote]: ...


def _num(value: object) -> float:
    """'71,000' / '-0.70' / 71000 같은 값을 숫자로."""
    if value is None:
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    text = str(value).replace(",", "").replace("%", "").replace("+", "").strip()
    return float(text) if text else 0.0


def parse_naver(payload: dict) -> dict[str, Quote]:
    """네이버 증권 실시간 API 응답(datas 목록)을 Quote로 바꿔요."""
    out: dict[str, Quote] = {}
    for d in payload.get("datas") or []:
        code = str(d.get("itemCode") or d.get("symbolCode") or "")
        if not code:
            continue
        price = _num(d.get("closePrice"))
        change = _num(d.get("compareToPreviousClosePrice"))
        pct = _num(d.get("fluctuationsRatio"))
        # 하락(코드 4·5)인데 부호가 빠져 있으면 음수로 맞춰요.
        direction = str((d.get("compareToPreviousPrice") or {}).get("code") or "")
        if direction in ("4", "5"):
            change, pct = -abs(change), -abs(pct)
        name = d.get("stockName") or STOCKS.get(code, Stock(code, code, 0)).name
        out[code] = Quote(code, name, price, change, pct)
    return out


class NaverQuotes:
    """네이버 증권 시세 (공식 API는 아니라서 형식이 바뀌면 데모 시세로 바뀌어요)."""

    name = "naver"
    BASE = "https://polling.finance.naver.com/api/realtime/domestic"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            timeout=6.0, headers={"User-Agent": "Mozilla/5.0 (market-weather)"}
        )

    def _get(self, kind: str, codes: list[str]) -> dict[str, Quote]:
        r = self.client.get(f"{self.BASE}/{kind}/{','.join(codes)}")
        r.raise_for_status()
        quotes = parse_naver(r.json())
        if not quotes:
            raise ValueError("empty quote response")
        return quotes

    def stocks(self, codes: list[str]) -> dict[str, Quote]:
        return self._get("stock", codes)

    def indices(self) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        for code, name, _ in INDICES:
            q = self._get("index", [code]).get(code)
            if q:
                q.name = name
                out[code] = q
        return out


class DemoQuotes:
    """연습용 가짜 시세. 날짜마다 다른 '날씨'가 나오고, 10분마다 조금씩 움직여요."""

    name = "demo"

    def __init__(self, now: callable | None = None) -> None:  # type: ignore[valid-type]
        self.now = now or (lambda: datetime.now(KST))

    @staticmethod
    def _rng(*parts: str) -> random.Random:
        seed = int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16)
        return random.Random(seed)

    def _pct(self, key: str, sector_key: str) -> float:
        now = self.now()
        day = now.strftime("%Y-%m-%d")
        market = self._rng(day, "market").gauss(0, 0.9)
        sector = self._rng(day, sector_key).gauss(0, 1.2)
        own = self._rng(day, key).gauss(0, 1.0)
        tick = self._rng(day, key, str(now.hour * 6 + now.minute // 10)).gauss(0, 0.25)
        return max(-29.0, min(29.0, round(market + sector + own + tick, 2)))

    def stocks(self, codes: list[str]) -> dict[str, Quote]:
        out = {}
        for code in codes:
            st = STOCKS.get(code)
            if not st:
                continue
            pct = self._pct(code, SECTOR_OF[code].id)
            prev = st.base_price
            price = max(1.0, round(prev * (1 + pct / 100) / 10) * 10)
            out[code] = Quote(
                code, st.name, price, price - prev, round((price / prev - 1) * 100, 2)
            )
        return out

    def indices(self) -> dict[str, Quote]:
        out = {}
        for code, name, base in INDICES:
            pct = round(self._pct(code, "index") * 0.6, 2)
            price = round(base * (1 + pct / 100), 2)
            out[code] = Quote(code, name, price, round(price - base, 2), pct)
        return out


class MarketData:
    """시세 공급자 + 짧은 캐시 + 실패 시 데모로 대체."""

    def __init__(self, primary: QuoteProvider, cache_seconds: int = 60) -> None:
        self.primary = primary
        self.demo = DemoQuotes()
        self.cache_seconds = cache_seconds
        self._cache: tuple[float, dict] | None = None

    def snapshot(self) -> dict:
        """모든 지수·종목 시세를 한 번에. {'source', 'indices', 'stocks', 'updated_at'}"""
        if self._cache and time.monotonic() - self._cache[0] < self.cache_seconds:
            return self._cache[1]
        codes = list(STOCKS)
        source = self.primary.name
        try:
            stocks = self.primary.stocks(codes)
            indices = self.primary.indices()
            if len(stocks) < len(codes) // 2:
                raise ValueError("too few quotes")
        except Exception:
            source = "demo"
            stocks = self.demo.stocks(codes)
            indices = self.demo.indices()
        snap = {
            "source": source,
            "indices": indices,
            "stocks": stocks,
            "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
        }
        self._cache = (time.monotonic(), snap)
        return snap

    def quote(self, code: str) -> Quote | None:
        return self.snapshot()["stocks"].get(code)


# ---------------------------------------------------------------------------
# 메인 화면용 '시장 날씨 예보'
# ---------------------------------------------------------------------------
def forecast(snap: dict) -> dict:
    stocks: dict[str, Quote] = snap["stocks"]
    indices = []
    for code, _, _ in INDICES:
        q = snap["indices"].get(code)
        if q:
            indices.append({**asdict(q), "weather": asdict(weather_for(q.change_pct))})

    sectors = []
    for sec in SECTORS:
        qs = [stocks[s.code] for s in sec.stocks if s.code in stocks]
        if not qs:
            continue
        avg = round(sum(q.change_pct for q in qs) / len(qs), 2)
        falling = sum(1 for q in qs if q.change_pct < 0)
        sectors.append(
            {
                "id": sec.id,
                "name": sec.name,
                "icon": sec.icon,
                "change_pct": avg,
                "rain_chance": round(falling / len(qs) * 100),  # 강수확률 = 내린 종목 비율
                "weather": asdict(weather_for(avg)),
                "stocks": [
                    {**asdict(q), "weather": asdict(weather_for(q.change_pct))}
                    for q in sorted(qs, key=lambda q: -q.change_pct)
                ],
            }
        )

    return {
        "source": snap["source"],
        "updated_at": snap["updated_at"],
        "indices": indices,
        "sectors": sectors,
    }
