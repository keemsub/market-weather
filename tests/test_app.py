from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main
from app.coach import Coach, GeminiClient, find_facts
from app.db import Trade
from app.market import (
    STOCKS,
    DemoQuotes,
    MarketData,
    Quote,
    forecast,
    parse_naver,
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

        def indices(self):
            raise RuntimeError("blocked")

    snap = MarketData(Broken()).snapshot()
    assert snap["source"] == "demo"
    assert len(snap["stocks"]) == len(STOCKS)
    fc = forecast(snap)
    assert len(fc["sectors"]) == 8 and len(fc["indices"]) == 2


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
    assert "gemini-2.5-flash:generateContent" in seen["url"] and seen["key"] == "k"
