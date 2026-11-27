"""설정값을 환경 변수(또는 .env 파일)에서 읽어옵니다.

API 키 같은 비밀값은 코드에 직접 쓰지 말고 .env 파일에 넣으세요.
.env 파일은 .gitignore에 들어 있어서 GitHub에 올라가지 않습니다.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- 시세 데이터 ----
    # naver: 네이버 증권 시세(키 필요 없음, 약간 늦을 수 있음) / demo: 연습용 가짜 시세
    market_source: str = "naver"
    # 같은 시세를 몇 초 동안 재사용할지 (너무 자주 부르지 않도록)
    quote_cache_seconds: int = 60

    # ---- AI 코치 (LLM) ----
    # gemini: 구글 Gemini (무료 한도 있음) / openai: OpenAI 호환 주소(Groq, OpenRouter 등)
    llm_provider: str = "gemini"
    # 비워 두면 AI 대신 '규칙 코치'가 피드백을 줘요. (앱은 그대로 동작)
    llm_api_key: str = ""
    # 비워 두면 공급자별 기본 모델을 써요.
    llm_model: str = ""
    # openai 방식일 때만: 예) https://api.groq.com/openai/v1
    llm_base_url: str = ""

    # ---- 저장 ----
    # 익명 계정 쿠키 서명용 비밀값 (배포할 땐 Render가 자동 생성)
    secret_key: str = "dev-only-change-me"
    cookie_secure: bool = False
    # 데이터베이스 주소. 비우면 내 컴퓨터의 market_weather.db 파일(SQLite)을 써요.
    database_url: str = "sqlite:///./market_weather.db"

    # 처음 받는 가상 투자금 (원)
    starting_cash: int = 10_000_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
