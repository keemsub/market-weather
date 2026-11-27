# 시장 날씨 🌤️

오늘의 주식 시장을 **날씨**로 보여주는 모의투자 앱이에요.

- **메인 화면 = 시장 날씨 예보**: 코스피·코스닥과 업종 8개의 등락을 ☀️ 쨍쨍 ~ ⛈️ 천둥번개로 보여줘요.
- **업종 칸을 누르면** 그 업종 종목이 나오고, 가상 **1,000만 원**으로 바로 사고팔 수 있어요.
- **매매할 때마다 코치 '구름이'가 한마디**: 추격 매수, 한 종목 몰빵, 짧은 단타, 손절·익절 같은 습관을 짚어 줘요.
  - AI 키가 있으면 Gemini(무료 한도) 같은 LLM이 말을 다듬고, 없으면 규칙 코치가 대신 말해요. 앱은 키 없이도 다 동작해요.

> 모의투자예요. 실제 돈이 오가지 않고, 투자 권유가 아니에요.

## 내 컴퓨터에서 실행

```bash
uv sync
uv run uvicorn app.main:app --reload
```

브라우저에서 http://localhost:8000 을 열면 돼요.
AI 코치를 켜려면 `.env.example`을 `.env`로 복사하고 `LLM_API_KEY`를 넣으세요.
→ 키 받는 법과 무료 배포 방법은 [docs/setup-guide.md](docs/setup-guide.md)

## 테스트

```bash
uv run pytest
```

## 구조

| 파일 | 하는 일 |
| --- | --- |
| `app/market.py` | 업종·종목 목록, 시세 가져오기(네이버 → 실패하면 연습용), 등락률 → 날씨 규칙 |
| `app/portfolio.py` | 모의투자 계산 (보유 종목, 평균가, 수익률, 수수료·세금 흉내) |
| `app/coach.py` | 코치: 규칙으로 사실 찾기 → LLM으로 다듬기 (Gemini / OpenAI 호환) |
| `app/db.py` | 익명 계정과 매매 기록 저장 (SQLite, 배포 땐 Postgres) |
| `app/main.py` | 웹 서버와 API |
| `app/static/`, `app/templates/` | 화면 (HTML·CSS·JS) |

### 자주 바꿀 만한 곳

- **업종·종목 추가**: `app/market.py`의 `SECTORS`
- **날씨 기준(몇 % 이상이면 맑음)**: `app/market.py`의 `WEATHER_SCALE`
- **코치 말투**: `app/coach.py`의 `SYSTEM_PROMPT`, 규칙 문장은 `find_facts`
- **LLM 공급자 추가**: `app/coach.py`에 `complete(system, user)` 함수 하나 있는 클래스를 만들고 `make_llm`에 연결
