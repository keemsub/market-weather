from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.coach import Coach, GeminiClient, find_facts
from app.db import Trade
from app.market import (
    STOCKS,
    US_SECTORS,
    ChainQuotes,
    DemoQuotes,
    MarketData,
    NaverWorldQuotes,
    Quote,
    forecast,
    parse_naver,
    parse_yahoo_chart,
    weather_for,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("MARKET_SOURCE", "demo")
    monkeypatch.setenv("LLM_API_KEY", "")
    from app import config, db

    config.get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._sessionmaker.cache_clear()
    main.get_market.cache_clear()
    main.get_coach.cache_clear()
    return TestClient(main.app)


def test_weather_scale():
    assert weather_for(3).key == "hot"
    assert weather_for(1).key == "sunny"
    assert weather_for(0.3).key == "partly"
    assert weather_for(0).key == "cloudy"
    assert weather_for(-0.5).key == "shower"
    assert weather_for(-1.5).key == "rain"
    assert weather_for(-5).key == "storm"


def test_parse_naver_formats():
    payload = {
        "datas": [
            {
                "itemCode": "005930",
                "stockName": "삼성전자",
                "closePrice": "71,000",
                "compareToPreviousClosePrice": "500",
                "fluctuationsRatio": "0.70",
                "compareToPreviousPrice": {"code": "5", "name": "FALLING"},
            },
            {
                "itemCode": "KOSPI",
                "stockName": "코스피",
                "closePrice": "2,612.34",
                "compareToPreviousClosePrice": "12.30",
                "fluctuationsRatio": "0.47",
                "compareToPreviousPrice": {"code": "2", "name": "RISING"},
            },
        ]
    }
    q = parse_naver(payload)
    assert q["005930"].price == 71000
    assert q["005930"].change_pct == -0.70  # 하락 코드면 음수
    assert q["KOSPI"].price == 2612.34 and q["KOSPI"].change_pct == 0.47


def test_market_falls_back_to_demo():
    class Broken:
        name = "naver"

        def stocks(self, codes):
            raise RuntimeError("blocked")

        def indices(self, codes):
            raise RuntimeError("blocked")

    snap = MarketData({"KR": Broken(), "US": Broken()}).snapshot()
    assert snap["sources"] == {"KR": "demo", "US": "demo"}
    assert len(snap["stocks"]) == len(STOCKS)
    kr, us = forecast(snap, "KR"), forecast(snap, "US")
    assert len(kr["sectors"]) == 8 and len(kr["indices"]) == 2
    assert len(us["sectors"]) == 8 and len(us["indices"]) == 3
    aapl = snap["stocks"]["AAPL"]
    assert aapl.currency == "USD" and aapl.price_krw == round(aapl.price * snap["fx"]["usdkrw"], 2)


def test_parse_yahoo_chart():
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "AAPL",
                        "currency": "USD",
                        "regularMarketPrice": 202.0,
                        "chartPreviousClose": 200.0,
                    }
                }
            ]
        }
    }
    q = parse_yahoo_chart(payload)
    assert q.name == "애플" and q.price == 202.0 and q.change_pct == 1.0 and q.currency == "USD"


def test_demo_is_stable_within_day():
    t = datetime(2026, 11, 27, 10, 3)
    a = DemoQuotes(lambda: t).stocks(["005930"])
    b = DemoQuotes(lambda: t + timedelta(minutes=2)).stocks(["005930"])
    assert a["005930"].price == b["005930"].price


def test_trade_flow(client):
    w = client.get("/api/weather").json()
    assert w["source"] == "demo"
    p = client.get("/api/portfolio").json()
    assert p["cash"] == 10_000_000 and p["coach_mode"] == "rule"

    r = client.post("/api/trade", json={"code": "005930", "side": "buy", "qty": 10})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["coach"]["source"] == "rule" and body["coach"]["text"]
    assert body["portfolio"]["holdings"][0]["qty"] == 10

    # 가진 것보다 많이 팔기
    r = client.post("/api/trade", json={"code": "005930", "side": "sell", "qty": 11})
    assert r.status_code == 400 and "보유 10주" in r.json()["detail"]

    r = client.post("/api/trade", json={"code": "005930", "side": "sell", "qty": 10})
    assert r.status_code == 200
    assert r.json()["portfolio"]["holdings"] == []
    assert len(r.json()["portfolio"]["trades"]) == 2

    # 현금 부족
    r = client.post("/api/trade", json={"code": "207940", "side": "buy", "qty": 100000})
    assert r.status_code == 400 and "현금이 부족" in r.json()["detail"]

    # 미국 주식: 원화 계좌에서 환율로 계산
    us = client.get("/api/weather?m=US").json()
    assert us["market"] == "US" and us["fx"]["usdkrw"] > 1000
    r = client.post("/api/trade", json={"code": "AAPL", "side": "buy", "qty": 3})
    assert r.status_code == 200, r.text
    h = r.json()["portfolio"]["holdings"][0]
    assert h["currency"] == "USD" and h["market"] == "US" and h["price"] > h["native_price"]

    assert client.post("/api/reset").status_code == 200
    assert client.get("/api/portfolio").json()["trades"] == []


def _trade(id, side, qty, price, pct, minutes_ago=0, code="005930"):
    return Trade(
        id=id,
        account_id=1,
        code=code,
        name="삼성전자",
        side=side,
        qty=qty,
        price=price,
        change_pct=pct,
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


def test_facts_chase_and_concentration():
    t = _trade(1, "buy", 100, 70000, 6.0)
    quotes = {"005930": Quote("005930", "삼성전자", 70000, 0, 6.0)}
    keys = {f.key for f in find_facts(t, [t], quotes, cash=3_000_000, sector_pct=1.0)}
    assert {"chase", "concentration", "first"} <= keys


def test_facts_stoploss_and_flip():
    b = _trade(1, "buy", 10, 70000, 0, minutes_ago=3)
    s = _trade(2, "sell", 10, 66000, -2)
    keys = {f.key for f in find_facts(s, [b, s], {}, cash=10_000_000, sector_pct=-1)}
    assert {"stoploss", "flip"} <= keys


def test_coach_falls_back_when_llm_fails():
    class Bad:
        name = "gemini"

        def complete(self, system, user):
            raise RuntimeError("quota")

    t = _trade(1, "buy", 1, 70000, 0)
    facts = find_facts(t, [t], {}, 10_000_000, 0)
    text, src = Coach(Bad()).comment(t, facts, "")
    assert src == "rule" and text


def test_gemini_request_shape():
    import httpx

    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["key"] = req.headers.get("x-goog-api-key")
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "좋아요"}]}}]}
        )

    c = GeminiClient("k", http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert c.complete("sys", "hi") == "좋아요"
    assert "gemini-flash-latest:generateContent" in seen["url"] and seen["key"] == "k"


def test_find_stocks():
    from app.insights import find_stocks

    assert find_stocks("삼성전자 왜 떨어졌어?") == ["005930"]
    assert "NVDA" in find_stocks("엔비디아랑 tsla 어때")
    assert "TSLA" in find_stocks("엔비디아랑 tsla 어때")
    assert find_stocks("오늘 시장 어때?") == []
    assert "GOOGL" in find_stocks("구글 주가")


def test_ask_and_report(client):
    r = client.post("/api/ask", json={"question": "삼성전자 왜 떨어졌어?"})
    assert r.status_code == 200 and r.json()["source"] == "rule"
    assert "삼성전자" in r.json()["text"]

    r = client.post(
        "/api/ask",
        json={
            "question": "오늘 시장 어때?",
            "history": [{"role": "user", "text": "안녕"}, {"role": "coach", "text": "안녕하세요"}],
        },
    )
    assert r.status_code == 200 and r.json()["text"]
    assert client.post("/api/ask", json={"question": ""}).status_code == 422

    empty = client.get("/api/report").json()
    assert empty["stats"]["trades"] == 0 and empty["text"]

    client.post("/api/trade", json={"code": "005930", "side": "buy", "qty": 10})
    client.post("/api/trade", json={"code": "005930", "side": "sell", "qty": 5})
    rep = client.get("/api/report").json()
    st = rep["stats"]
    assert st["trades"] == 2 and st["buys"] == 1 and st["sells"] == 1
    assert st["quick_flips"] == 1  # 바로 팔았으니 10분 단타
    assert rep["weather"]["emoji"] and rep["source"] == "rule"


def test_weekly_stats_realized():
    from app.insights import weekly_stats

    b = _trade(1, "buy", 10, 1000, 0, minutes_ago=60 * 24 * 3)
    s = _trade(2, "sell", 4, 1200, 0, minutes_ago=60)
    old = _trade(3, "buy", 1, 1000, 9, minutes_ago=60 * 24 * 30)
    pf = {"holdings": [], "total": 10_000_000, "cash": 10_000_000, "return_pct": 0.0}
    st = weekly_stats([old, b, s], pf)
    assert st["trades"] == 2 and st["realized"] == 800 and st["win_rate"] == 100
    assert st["chase_buys"] == 0  # 한 달 전 추격 매수는 이번 주에 안 들어가요


def test_ask_rule_uses_only_this_question(client):
    h = [{"role": "user", "text": "삼성전자 어때?"}, {"role": "coach", "text": "삼성전자는..."}]
    r = client.post("/api/ask", json={"question": "내 지갑 어때?", "history": h}).json()
    assert "총자산" in r["text"]
    r = client.post("/api/ask", json={"question": "분산 투자가 뭐야?"}).json()
    assert "바구니" in r["text"]


def test_gemini_switches_model_on_404():
    import httpx

    calls = []

    def handler(req):
        calls.append(str(req.url))
        if req.method == "GET":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-3.0-flash-lite",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                        {
                            "name": "models/gemini-3.0-flash",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                        {
                            "name": "models/gemini-3.0-flash-image",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                        {
                            "name": "models/gemini-3.0-pro",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                        {
                            "name": "models/text-embedding-9",
                            "supportedGenerationMethods": ["embedContent"],
                        },
                    ]
                },
            )
        if "gemini-2.5-flash:" in str(req.url):
            return httpx.Response(404, json={"error": {"code": 404}})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    c = GeminiClient(
        "k", "gemini-2.5-flash", http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert c.complete("s", "u") == "ok"
    assert c.model == "gemini-3.0-flash"
    assert c.complete("s", "u") == "ok"  # 다음부터는 바뀐 모델로 바로
    assert sum("gemini-2.5-flash:" in u for u in calls) == 1


def test_gemini_pick_model():
    pick = GeminiClient.pick_model
    assert (
        pick(["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-flash-preview-05"])
        == "gemini-2.5-flash"
    )
    assert pick(["gemini-flash-latest", "gemini-9-flash"]) == "gemini-flash-latest"
    assert pick(["gemini-2.5-flash-lite"]) == "gemini-2.5-flash-lite"
    assert pick(["gemini-2.5-pro"]) is None


def test_gemini_empty_text_raises_with_reason():
    with pytest.raises(ValueError, match="MAX_TOKENS"):
        GeminiClient.extract_text(
            {"candidates": [{"content": {"role": "model"}, "finishReason": "MAX_TOKENS"}]}
        )
    with pytest.raises(ValueError, match="SAFETY"):
        GeminiClient.extract_text({"promptFeedback": {"blockReason": "SAFETY"}})
    assert (
        GeminiClient.extract_text(
            {
                "candidates": [
                    {"content": {"parts": [{"text": "생각", "thought": True}, {"text": "답"}]}}
                ]
            }
        )
        == "답"
    )


def test_report_uses_llm_and_caches(client, monkeypatch):
    calls = []

    class Fake:
        name = "gemini"

        def complete(self, system, user):
            calls.append(user)
            return "☀️ 맑은 한 주\n잘한 점..."

    monkeypatch.setattr(main.get_coach(), "llm", Fake())
    r1 = client.get("/api/report").json()
    r2 = client.get("/api/report").json()
    assert r1["source"] == "gemini" and r2["text"] == r1["text"] and len(calls) == 1
    client.post(
        "/api/trade", json={"code": "005930", "side": "buy", "qty": 1}
    )  # 코치 한마디도 LLM 호출
    client.get("/api/report")
    assert len(calls) == 2  # 매매 자체는 LLM 없이, 매매가 생기면 리포트를 새로 써요


def test_sell_returns_cash_and_wallet_numbers(client):
    p0 = client.get("/api/portfolio").json()
    b = client.post("/api/trade", json={"code": "005930", "side": "buy", "qty": 10}).json()
    price = b["trade"]["price"]
    pb = b["portfolio"]
    assert pb["cash"] < p0["cash"] and pb["invested"] == round(price * 10)
    assert pb["stock_value"] == round(price * 10) and pb["unrealized"] == 0
    s = client.post("/api/trade", json={"code": "005930", "side": "sell", "qty": 4}).json()
    ps = s["portfolio"]
    proceeds = price * 4 * (1 - 0.00015 - 0.0018)
    assert abs(ps["cash"] - (pb["cash"] + proceeds)) <= 1  # 판 돈이 현금으로 들어와요
    assert ps["holdings"][0]["qty"] == 6 and ps["invested"] == round(price * 6)
    assert ps["realized"] == round(proceeds - price * 4)
    # 다시 불러도 그대로 (저장됨)
    assert abs(client.get("/api/portfolio").json()["cash"] - ps["cash"]) <= 1


def test_trade_coach_endpoint(client, monkeypatch):
    t = client.post("/api/trade", json={"code": "005930", "side": "buy", "qty": 1}).json()
    assert t["coach"]["source"] == "rule"
    tid = t["trade"]["id"]

    class Fake:
        name = "gemini"

        def complete(self, system, user):
            return "AI 한마디"

    monkeypatch.setattr(main.get_coach(), "llm", Fake())
    c = client.post(f"/api/trade/{tid}/coach").json()
    assert c == {"text": "AI 한마디", "source": "gemini"}
    j = client.get("/api/portfolio").json()["trades"][0]
    assert j["coach"] == "AI 한마디"
    assert client.post("/api/trade/9999/coach").status_code == 404


def _naver_world_client(missing=()):
    """가짜 네이버 해외주식 서버: AAPL은 .O, JPM은 .N, WMT는 .N이 없고 .O에만 있어요."""

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if "marketIndex" in path:
            return httpx.Response(200, json={"result": {"closePrice": "1,385.50"}})
        reuters = path.rsplit("/", 1)[-1]
        if reuters in missing:
            return httpx.Response(404, json={})
        down = reuters == ".IXIC"
        item = {
            "closePrice": "1,234.50",
            "compareToPreviousClosePrice": "12.30" if not down else "50.00",
            "fluctuationsRatio": "1.01" if not down else "0.30",
            "compareToPreviousPrice": {"code": "2" if not down else "5"},
            "stockName": "x",
        }
        return httpx.Response(200, json={"datas": [item]})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_naver_world_quotes():
    nw = NaverWorldQuotes(_naver_world_client(missing={"WMT.O"}))
    out = nw.stocks(["AAPL", "WMT", "JPM"])
    assert set(out) == {"AAPL", "WMT", "JPM"}  # WMT는 .N으로 다시 시도해서 받음
    assert out["AAPL"].price == 1234.5 and out["AAPL"].currency == "USD"
    assert out["AAPL"].name == STOCKS["AAPL"].name
    ix = nw.indices(["^GSPC", "^IXIC"])
    assert ix["^IXIC"].change_pct == -0.3 and ix["^GSPC"].change == 12.3
    assert nw.fx() == 1385.5


def test_us_chain_falls_back_and_reports_errors():
    class Blocked:
        name = "yahoo"

        def stocks(self, codes):
            raise RuntimeError("429 Too Many Requests")

        indices = stocks

        def fx(self):
            raise RuntimeError("429")

    naver_world = NaverWorldQuotes(_naver_world_client())
    chain = ChainQuotes(Blocked(), naver_world)
    snap = MarketData(
        {"KR": DemoQuotes(), "US": chain}, fx_provider=[Blocked(), naver_world]
    ).snapshot()
    assert snap["sources"]["US"] == "naver"
    assert snap["fx"] == {"usdkrw": 1385.5, "source": "naver"}
    assert snap["stocks"]["AAPL"].price_krw == round(1234.5 * 1385.5, 2)
    assert "US" not in snap["errors"]

    dead = NaverWorldQuotes(
        _naver_world_client(
            missing=set(
                [f"{s.code}.O" for sec in US_SECTORS for s in sec.stocks]
                + [f"{s.code}.N" for sec in US_SECTORS for s in sec.stocks]
            )
        )
    )
    snap = MarketData({"KR": DemoQuotes(), "US": ChainQuotes(dead, Blocked())}).snapshot()
    assert snap["sources"]["US"] == "demo"
    assert "429" in snap["errors"]["US"] and "naver" in snap["errors"]["US"]


def test_health_data(client):
    body = client.get("/health/data").json()
    assert body["sources"] == {"KR": "demo", "US": "demo"} and body["errors"] == {}
