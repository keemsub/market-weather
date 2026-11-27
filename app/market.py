"""시세 가져오기 + 등락률을 '날씨'로 바꾸기.

- 업종과 종목 목록은 아래 SECTORS에 직접 적어 두었어요. 추가·수정하기 쉬워요.
- 시세는 NaverQuotes(키 필요 없음)로 가져오고, 실패하면 DemoQuotes(연습용)로 바꿔요.
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

import httpx

log = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# 업종과 종목 (code, 이름, 데모용 기준가)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Stock:
    code: str
    name: str
    base_price: float  # 데모 시세의 출발점 (실제 시세와 다를 수 있어요)


@dataclass(frozen=True)
class Sector:
    id: str
    name: str
    icon: str
    stocks: tuple[Stock, ...]
    market: str = "KR"  # KR 국내 / US 미국


KR_SECTORS: tuple[Sector, ...] = (
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

US_SECTORS: tuple[Sector, ...] = tuple(
    Sector(sid, name, icon, tuple(Stock(c, n, p) for c, n, p in stocks), "US")
    for sid, name, icon, stocks in (
        (
            "us-bigtech",
            "빅테크",
            "💻",
            (
                ("AAPL", "애플", 230),
                ("MSFT", "마이크로소프트", 420),
                ("GOOGL", "알파벳(구글)", 175),
                ("AMZN", "아마존", 200),
                ("META", "메타", 580),
            ),
        ),
        (
            "us-semi",
            "반도체",
            "💾",
            (
                ("NVDA", "엔비디아", 140),
                ("AMD", "AMD", 150),
                ("AVGO", "브로드컴", 170),
                ("TSM", "TSMC", 190),
            ),
        ),
        (
            "us-ev",
            "전기차·모빌리티",
            "🚗",
            (
                ("TSLA", "테슬라", 300),
                ("RIVN", "리비안", 12),
                ("UBER", "우버", 75),
            ),
        ),
        (
            "us-finance",
            "금융",
            "🏦",
            (
                ("JPM", "JP모건", 230),
                ("BAC", "뱅크오브아메리카", 45),
                ("GS", "골드만삭스", 550),
                ("V", "비자", 300),
            ),
        ),
        (
            "us-health",
            "헬스케어",
            "💊",
            (
                ("LLY", "일라이릴리", 800),
                ("JNJ", "존슨앤드존슨", 155),
                ("UNH", "유나이티드헬스", 550),
                ("PFE", "화이자", 26),
            ),
        ),
        (
            "us-consumer",
            "소비재",
            "🛒",
            (
                ("KO", "코카콜라", 65),
                ("COST", "코스트코", 900),
                ("WMT", "월마트", 85),
                ("MCD", "맥도날드", 290),
            ),
        ),
        (
            "us-energy",
            "에너지",
            "🛢️",
            (
                ("XOM", "엑슨모빌", 115),
                ("CVX", "셰브론", 150),
            ),
        ),
        (
            "us-media",
            "엔터·미디어",
            "🎬",
            (
                ("NFLX", "넷플릭스", 800),
                ("DIS", "디즈니", 110),
                ("SPOT", "스포티파이", 450),
            ),
        ),
    )
)

SECTORS: tuple[Sector, ...] = KR_SECTORS + US_SECTORS

# (코드, 이름, 데모용 기준값, 시장)
INDICES = (
    ("KOSPI", "코스피", 2600.0, "KR"),
    ("KOSDAQ", "코스닥", 750.0, "KR"),
    ("^GSPC", "S&P 500", 5900.0, "US"),
    ("^IXIC", "나스닥", 19000.0, "US"),
    ("^DJI", "다우존스", 44000.0, "US"),
)
MARKETS = {"KR": "국내", "US": "미국"}
FX_CODE = "KRW=X"  # 1달러 = 몇 원
DEMO_FX = 1400.0

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
    price: float  # 그 나라 돈 기준 (국내 원, 미국 달러)
    change: float  # 전일 대비 (원·달러 / 포인트)
    change_pct: float  # 전일 대비 (%)
    currency: str = "KRW"
    price_krw: float = 0.0  # 원화로 바꾼 1주 가격 (모의투자 계산용)

    def __post_init__(self) -> None:
        if not self.price_krw and self.currency == "KRW":
            self.price_krw = self.price


class QuoteProvider(Protocol):
    name: str

    def stocks(self, codes: list[str]) -> dict[str, Quote]: ...
    def indices(self, codes: list[str]) -> dict[str, Quote]: ...


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
    """국내 시세: 네이버 증권 (공식 API는 아니라서 형식이 바뀌면 연습용 시세로 바뀌어요)."""

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

    def indices(self, codes: list[str]) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        for code in codes:
            q = self._get("index", [code]).get(code)
            if q:
                out[code] = q
        return out


def parse_yahoo_chart(payload: dict) -> Quote:
    """야후 파이낸스 chart API 응답에서 현재가와 전일 종가를 꺼내요."""
    meta = payload["chart"]["result"][0]["meta"]
    code = meta["symbol"]
    price = float(meta["regularMarketPrice"])
    prev = float(meta.get("chartPreviousClose") or meta.get("previousClose") or price)
    change = price - prev
    pct = round(change / prev * 100, 2) if prev else 0.0
    name = STOCKS[code].name if code in STOCKS else meta.get("shortName", code)
    return Quote(code, name, price, round(change, 4), pct, meta.get("currency", "USD"))


class YahooQuotes:
    """미국 시세와 환율: 야후 파이낸스 (키 필요 없음, 공식 API 아님, 15분 이내 지연 가능)."""

    name = "yahoo"
    BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            timeout=6.0, headers={"User-Agent": "Mozilla/5.0 (market-weather)"}
        )

    def _one(self, code: str) -> Quote:
        r = self.client.get(self.BASE + code, params={"range": "1d", "interval": "1d"})
        r.raise_for_status()
        return parse_yahoo_chart(r.json())

    def _many(self, codes: list[str]) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            for code, q in zip(codes, pool.map(self._safe, codes), strict=True):
                if q:
                    out[code] = q
        if not out:
            raise ValueError(f"야후 응답 없음 ({self.last_error or '?'})")
        return out

    last_error = ""

    def _safe(self, code: str) -> Quote | None:
        try:
            return self._one(code)
        except Exception as e:
            self.last_error = str(e)[:120]
            return None

    def stocks(self, codes: list[str]) -> dict[str, Quote]:
        return self._many(codes)

    def indices(self, codes: list[str]) -> dict[str, Quote]:
        return self._many(codes)

    def fx(self) -> float:
        return self._one(FX_CODE).price


# 네이버 해외주식 코드: 나스닥 .O / 뉴욕증권거래소 .N (거래소를 옮기면 다른 쪽도 시도해요)
NAVER_US_CODES = {
    "AAPL": "AAPL.O",
    "MSFT": "MSFT.O",
    "GOOGL": "GOOGL.O",
    "AMZN": "AMZN.O",
    "META": "META.O",
    "NVDA": "NVDA.O",
    "AMD": "AMD.O",
    "AVGO": "AVGO.O",
    "TSM": "TSM.N",
    "TSLA": "TSLA.O",
    "RIVN": "RIVN.O",
    "UBER": "UBER.N",
    "JPM": "JPM.N",
    "BAC": "BAC.N",
    "GS": "GS.N",
    "V": "V.N",
    "LLY": "LLY.N",
    "JNJ": "JNJ.N",
    "UNH": "UNH.N",
    "PFE": "PFE.N",
    "KO": "KO.N",
    "COST": "COST.O",
    "WMT": "WMT.O",
    "MCD": "MCD.N",
    "XOM": "XOM.N",
    "CVX": "CVX.N",
    "NFLX": "NFLX.O",
    "DIS": "DIS.N",
    "SPOT": "SPOT.N",
}
NAVER_US_INDEX = {"^GSPC": ".INX", "^IXIC": ".IXIC", "^DJI": ".DJI"}


def _other_exchange(reuters: str) -> str:
    base, _, ex = reuters.rpartition(".")
    return f"{base}.{'N' if ex == 'O' else 'O'}"


class NaverWorldQuotes:
    """미국 시세: 네이버 해외주식 (키 필요 없음, 공식 API 아님)."""

    name = "naver"
    BASE = "https://polling.finance.naver.com/api/realtime/worldstock"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            timeout=6.0, headers={"User-Agent": "Mozilla/5.0 (market-weather)"}
        )

    def _get(self, kind: str, reuters: str) -> dict | None:
        r = self.client.get(f"{self.BASE}/{kind}/{reuters}")
        if r.status_code != 200:
            return None
        datas = (r.json() or {}).get("datas") or []
        return datas[0] if datas else None

    def _quote(self, code: str, d: dict, currency: str) -> Quote:
        q = parse_naver({"datas": [{**d, "itemCode": code}]})[code]
        q.currency = currency
        q.price_krw = 0.0
        return q

    def _one_stock(self, code: str) -> Quote | None:
        reuters = NAVER_US_CODES.get(code, f"{code}.O")
        try:
            d = self._get("stock", reuters) or self._get("stock", _other_exchange(reuters))
        except Exception:
            return None
        return self._quote(code, d, "USD") if d else None

    def stocks(self, codes: list[str]) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            for code, q in zip(codes, pool.map(self._one_stock, codes), strict=True):
                if q and q.price > 0:
                    q.name = STOCKS[code].name if code in STOCKS else q.name
                    out[code] = q
        if not out:
            raise ValueError("네이버 해외주식 응답 없음")
        return out

    def indices(self, codes: list[str]) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        for code in codes:
            try:
                d = self._get("index", NAVER_US_INDEX.get(code, code))
            except Exception:
                d = None
            if d:
                out[code] = self._quote(code, d, "USD")
        return out

    def fx(self) -> float:
        r = self.client.get(
            "https://m.stock.naver.com/front-api/marketIndex/productDetail",
            params={"category": "exchange", "reutersCode": "FX_USDKRW"},
        )
        r.raise_for_status()
        return _num((r.json().get("result") or {}).get("closePrice"))


class ChainQuotes:
    """앞의 출처가 안 되면 다음 출처로. 성공한 출처 이름을 name에 남겨요."""

    def __init__(self, *providers: QuoteProvider) -> None:
        self.providers = providers
        self.name = providers[0].name
        self.errors: list[str] = []

    def _try(self, method: str, codes: list[str]) -> dict[str, Quote]:
        self.errors = []
        for p in self.providers:
            try:
                out = getattr(p, method)(codes)
                if method == "stocks" and len(out) < len(codes) // 2:
                    raise ValueError(f"{len(out)}/{len(codes)}개만 받음")
                self.name = p.name
                return out
            except Exception as e:
                self.errors.append(f"{p.name}: {str(e)[:120]}")
        raise ValueError("; ".join(self.errors))

    def stocks(self, codes: list[str]) -> dict[str, Quote]:
        return self._try("stocks", codes)

    def indices(self, codes: list[str]) -> dict[str, Quote]:
        for p in self.providers:  # 종목을 받은 출처의 지수를 먼저
            if p.name == self.name:
                try:
                    out = p.indices(codes)
                    if out:
                        return out
                except Exception:
                    pass
        return self._try("indices", codes)


class DemoQuotes:
    """연습용 가짜 시세. 날짜마다 다른 '날씨'가 나오고, 10분마다 조금씩 움직여요."""

    name = "demo"

    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self.now = now or (lambda: datetime.now(KST))

    @staticmethod
    def _rng(*parts: str) -> random.Random:
        seed = int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16)
        return random.Random(seed)

    def _pct(self, key: str, sector_key: str) -> float:
        now = self.now()
        day = now.strftime("%Y-%m-%d")
        market = self._rng(day, "market", sector_key[:3]).gauss(0, 0.9)
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
            sec = SECTOR_OF[code]
            pct = self._pct(code, sec.id)
            prev = st.base_price
            if sec.market == "KR":
                price = max(1.0, round(prev * (1 + pct / 100) / 10) * 10)
                out[code] = Quote(
                    code, st.name, price, price - prev, round((price / prev - 1) * 100, 2)
                )
            else:
                price = round(prev * (1 + pct / 100), 2)
                out[code] = Quote(
                    code,
                    st.name,
                    price,
                    round(price - prev, 2),
                    round((price / prev - 1) * 100, 2),
                    "USD",
                )
        return out

    def indices(self, codes: list[str]) -> dict[str, Quote]:
        out = {}
        for code, name, base, market in INDICES:
            if code not in codes:
                continue
            pct = round(self._pct(code, ("us-" if market == "US" else "") + "index") * 0.6, 2)
            price = round(base * (1 + pct / 100), 2)
            out[code] = Quote(code, name, price, round(price - base, 2), pct)
        return out

    def fx(self) -> float:
        return round(
            DEMO_FX * (1 + self._rng(self.now().strftime("%Y-%m-%d"), "fx").gauss(0, 0.004)), 2
        )


def codes_of(market: str) -> tuple[list[str], list[str]]:
    stocks = [s.code for sec in SECTORS if sec.market == market for s in sec.stocks]
    indices = [c for c, _, _, m in INDICES if m == market]
    return stocks, indices


class MarketData:
    """시장별 시세 공급자 + 짧은 캐시 + 실패하면 그 시장만 연습용 시세로 대체."""

    def __init__(
        self,
        providers: dict[str, QuoteProvider],
        cache_seconds: int = 60,
        fx_provider: object | None = None,
    ) -> None:
        self.providers = providers
        self.fx_providers = (
            list(fx_provider)
            if isinstance(fx_provider, list | tuple)
            else ([fx_provider] if fx_provider is not None else [])
        )
        self.demo = DemoQuotes()
        self.cache_seconds = cache_seconds
        self._cache: tuple[float, dict] | None = None
        self.errors: dict[str, str] = {}

    def _market(self, market: str) -> tuple[str, dict[str, Quote], dict[str, Quote]]:
        stock_codes, index_codes = codes_of(market)
        provider = self.providers.get(market) or self.demo
        try:
            stocks = provider.stocks(stock_codes)
            indices = provider.indices(index_codes)
            if len(stocks) < len(stock_codes) // 2:
                raise ValueError(f"{len(stocks)}/{len(stock_codes)}개만 받음")
            self.errors.pop(market, None)
            return provider.name, stocks, indices
        except Exception as e:
            self.errors[market] = str(e)[:300]
            log.warning("%s 시세 실패, 연습용으로 대체: %s", market, e)
            return "demo", self.demo.stocks(stock_codes), self.demo.indices(index_codes)

    def _fx(self) -> tuple[float, str]:
        for p in self.fx_providers:
            try:
                rate = p.fx()
                if 500 < rate < 5000:
                    return rate, p.name
            except Exception as e:
                log.info("환율 %s 실패: %s", p.name, e)
        return self.demo.fx(), "demo"

    def snapshot(self) -> dict:
        """모든 지수·종목 시세를 한 번에. {'sources', 'fx', 'indices', 'stocks', 'updated_at'}"""
        if self._cache and time.monotonic() - self._cache[0] < self.cache_seconds:
            return self._cache[1]
        sources: dict[str, str] = {}
        stocks: dict[str, Quote] = {}
        indices: dict[str, Quote] = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = {m: pool.submit(self._market, m) for m in MARKETS}
            fx_job = pool.submit(self._fx)
            for m, job in jobs.items():
                sources[m], st, ix = job.result()
                stocks.update(st)
                indices.update(ix)
            fx, fx_source = fx_job.result()
        for q in stocks.values():
            if q.currency == "USD":
                q.price_krw = round(q.price * fx, 2)
        for code, name, _, _ in INDICES:
            if code in indices:
                indices[code].name = name
        snap = {
            "sources": sources,
            "errors": dict(self.errors),
            "fx": {"usdkrw": fx, "source": fx_source},
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
def forecast(snap: dict, market: str = "KR") -> dict:
    stocks: dict[str, Quote] = snap["stocks"]
    indices = []
    for code, _, _, m in INDICES:
        q = snap["indices"].get(code)
        if q and m == market:
            indices.append({**asdict(q), "weather": asdict(weather_for(q.change_pct))})

    sectors = []
    for sec in SECTORS:
        if sec.market != market:
            continue
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
        "market": market,
        "source": snap["sources"].get(market, "demo"),
        "fx": snap["fx"],
        "updated_at": snap["updated_at"],
        "indices": indices,
        "sectors": sectors,
    }
