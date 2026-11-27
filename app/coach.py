"""AI 코치: 매매할 때마다 한마디.

1) 규칙으로 '사실'을 먼저 찾고 (예: 오늘 많이 오른 종목을 샀다, 한 종목에 몰빵했다)
2) LLM이 있으면 그 사실을 바탕으로 친근한 말투로 바꿔 주고,
3) LLM 키가 없거나 실패하면 규칙 문장을 그대로 보여줘요. (앱은 항상 동작)

LLM 공급자를 바꾸고 싶으면 LLMClient 모양(complete 함수 하나)만 맞추면 돼요.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx

from app.config import Settings
from app.db import Trade
from app.market import SECTOR_OF, Quote, weather_for
from app.portfolio import holdings_from

log = logging.getLogger(__name__)


@dataclass
class Fact:
    key: str
    text: str  # 규칙 코치가 그대로 말할 문장
    weight: int = 1  # 클수록 먼저 말해요


def find_facts(
    trade: Trade,
    history: list[Trade],
    quotes: dict[str, Quote],
    cash: float,
    sector_pct: float | None,
) -> list[Fact]:
    """방금 한 매매(trade)와 지금까지의 기록(history, trade 포함)에서 눈에 띄는 점을 찾아요."""
    facts: list[Fact] = []
    pct = trade.change_pct
    sector = SECTOR_OF.get(trade.code)
    sec_name = sector.name if sector else "이 업종"
    before = [t for t in history if t.id != trade.id]

    if not before:
        facts.append(
            Fact("first", "첫 매매를 축하해요! 이제 시장 날씨를 직접 느껴 볼 차례예요.", 1)
        )

    if trade.side == "buy":
        if pct >= 5:
            facts.append(
                Fact(
                    "chase",
                    f"오늘 이미 {pct:+.1f}% 오른 종목을 샀어요. 급등 뒤 따라 사는 '추격 매수'는 "
                    "꼭대기에서 사기 쉬워요. 왜 샀는지 한 줄 메모해 두면 좋아요.",
                    5,
                )
            )
        elif pct <= -5:
            facts.append(
                Fact(
                    "knife",
                    f"오늘 {pct:+.1f}% 떨어진 종목을 샀어요. 싸 보여도 이유가 있을 수 있으니 "
                    "나눠서 사는 것도 방법이에요.",
                    4,
                )
            )
        if sector_pct is not None:
            w = weather_for(sector_pct)
            if w.key in ("rain", "storm"):
                facts.append(
                    Fact(
                        "against",
                        f"{sec_name} 하늘은 지금 {w.emoji} {w.label} 상태예요. "
                        "비 오는 날 우산 없이 나가는 역발상 매수네요. "
                        "버틸 계획이 있는지 생각해 봐요.",
                        3,
                    )
                )
            elif w.key == "hot":
                facts.append(
                    Fact(
                        "hot",
                        f"{sec_name} 업종은 오늘 {w.emoji} {w.label}! "
                        "다들 몰려든 날이라 들뜨기 쉬워요.",
                        2,
                    )
                )
    else:
        held_before = holdings_from(before).get(trade.code)
        if held_before and held_before.qty:
            avg = held_before.avg_price
            gain = (trade.price / avg - 1) * 100 if avg else 0
            if gain <= -3:
                facts.append(
                    Fact(
                        "stoploss",
                        f"평균 매입가보다 {gain:.1f}% 낮게 팔았어요. "
                        "손실을 끊어 내는 것도 용기예요. "
                        "다음엔 미리 '여기까지 내리면 판다'는 선을 정해 두면 덜 흔들려요.",
                        4,
                    )
                )
            elif gain >= 3:
                facts.append(
                    Fact(
                        "takeprofit",
                        f"평균 매입가보다 {gain:+.1f}% 높게 팔아 수익을 챙겼어요. 잘했어요! "
                        "더 오를까 아쉬워하지 않는 게 포인트예요.",
                        3,
                    )
                )
            last_buy = next(
                (t for t in reversed(before) if t.code == trade.code and t.side == "buy"), None
            )
            if last_buy and _aware(trade.created_at) - _aware(last_buy.created_at) < timedelta(
                minutes=10
            ):
                facts.append(
                    Fact(
                        "flip",
                        "산 지 10분도 안 돼서 팔았어요. 짧은 매매는 수수료와 세금이 쌓여요.",
                        3,
                    )
                )

    # 지난 1시간 매매 횟수
    recent = [
        t for t in history if _aware(trade.created_at) - _aware(t.created_at) < timedelta(hours=1)
    ]
    if len(recent) >= 6:
        facts.append(
            Fact(
                "overtrade",
                f"1시간 동안 {len(recent)}번 매매했어요. 잠깐 쉬면서 하늘을 한번 올려다봐요.",
                4,
            )
        )

    # 쏠림 (매매 직후 기준)
    holds = holdings_from(history)
    values = {
        c: h.qty * (quotes[c].price_krw if c in quotes else h.avg_price) for c, h in holds.items()
    }
    total = cash + sum(values.values())
    if total > 0 and values:
        top_code, top_val = max(values.items(), key=lambda kv: kv[1])
        share = top_val / total * 100
        if share >= 40 and trade.side == "buy":
            facts.append(
                Fact(
                    "concentration",
                    f"전체 자산의 {share:.0f}%가 {holds[top_code].name} 한 종목에 있어요. "
                    "한 바구니에 달걀을 너무 많이 담았을 수도 있어요.",
                    4,
                )
            )
        if cash / total < 0.05 and trade.side == "buy":
            facts.append(
                Fact(
                    "allin",
                    "현금이 거의 남지 않았어요. "
                    "기회가 왔을 때 쓸 여유 현금도 조금 남겨 두면 좋아요.",
                    3,
                )
            )

    if not facts or (len(facts) == 1 and facts[0].key == "first"):
        facts.append(
            Fact(
                "calm",
                "무리 없는 매매예요. 산 이유와 팔 기준을 미리 정해 두면 다음 결정이 쉬워져요.",
                1,
            )
        )
    facts.sort(key=lambda f: -f.weight)
    return facts


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def rule_comment(facts: list[Fact]) -> str:
    return " ".join(f.text for f in facts[:2])


# ---------------------------------------------------------------------------
# LLM 공급자
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "당신은 주식 모의투자 앱의 코치 '구름이'예요. 시장을 날씨에 빗대어 말해요. "
    "초보 투자자가 방금 한 매매에 대해, 주어진 '관찰한 사실'만 근거로 "
    "2~3문장의 짧고 다정한 피드백을 해요. 존댓말을 쓰고, 이모지는 1개까지만 써요. "
    "특정 종목을 사라·팔라고 권하거나 가격을 예측하지 말고, 습관과 생각하는 방법에 집중해요. "
    "사실에 없는 숫자나 뉴스를 지어내지 마세요."
)


class LLMClient(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...


class GeminiClient:
    """구글 Gemini (Google AI Studio 무료 키로 쓸 수 있어요).

    구글이 모델 이름을 자주 바꿔서, 고른 모델이 없다고(404) 하면
    내 키로 쓸 수 있는 모델 목록을 받아 가장 알맞은 flash 모델로 바꿔 다시 불러요.
    """

    name = "gemini"
    DEFAULT_MODEL = "gemini-flash-latest"  # 구글이 최신 flash 모델로 이어 주는 별칭
    BASE = "https://generativelanguage.googleapis.com/v1beta"
    SKIP = ("image", "tts", "audio", "live", "embed", "vision", "thinking", "exp", "learnlm")

    def __init__(self, api_key: str, model: str = "", http: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.model = (model or self.DEFAULT_MODEL).removeprefix("models/")
        self.http = http or httpx.Client(timeout=12.0)

    def _generate(self, model: str, system: str, user: str) -> httpx.Response:
        return self.http.post(
            f"{self.BASE}/models/{model}:generateContent",
            headers={"x-goog-api-key": self.api_key},
            json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0.8, "maxOutputTokens": 2048},
            },
        )

    def available_models(self) -> list[str]:
        r = self.http.get(
            f"{self.BASE}/models",
            headers={"x-goog-api-key": self.api_key},
            params={"pageSize": 1000},
        )
        r.raise_for_status()
        return [
            m["name"].removeprefix("models/")
            for m in r.json().get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]

    @classmethod
    def pick_model(cls, names: list[str]) -> str | None:
        """목록에서 고르기: flash > flash-lite, 정식 > preview, 버전 숫자가 클수록 먼저."""

        def version(n: str) -> float:
            m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
            return float(m.group(1)) if m else 0.0

        flash = [n for n in names if "flash" in n and not any(k in n for k in cls.SKIP)]
        if not flash:
            return None
        flash.sort(
            key=lambda n: (
                n.endswith("-latest") and "lite" not in n,  # gemini-flash-latest
                "lite" not in n,
                "preview" not in n,
                version(n),
                -len(n),
            ),
            reverse=True,
        )
        return flash[0]

    def complete(self, system: str, user: str) -> str:
        r = self._generate(self.model, system, user)
        if r.status_code == 404:
            better = self.pick_model(self.available_models())
            if better and better != self.model:
                log.warning("Gemini 모델 %s 없음 → %s 로 바꿔요", self.model, better)
                self.model = better
                r = self._generate(self.model, system, user)
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"].get("parts", [])
        return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()


class OpenAICompatibleClient:
    """OpenAI 형식(/chat/completions)을 쓰는 곳: Groq(무료 한도), OpenRouter 등."""

    name = "openai"
    DEFAULT_BASE = "https://api.groq.com/openai/v1"
    DEFAULT_MODEL = "llama-3.3-70b-versatile"

    def __init__(
        self, api_key: str, model: str = "", base_url: str = "", http: httpx.Client | None = None
    ) -> None:
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.base_url = (base_url or self.DEFAULT_BASE).rstrip("/")
        self.http = http or httpx.Client(timeout=12.0)

    def complete(self, system: str, user: str) -> str:
        r = self.http.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": 0.8,
                "max_tokens": 800,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        r.raise_for_status()
        return (r.json()["choices"][0]["message"]["content"] or "").strip()


def make_llm(settings: Settings) -> LLMClient | None:
    if not settings.llm_api_key:
        return None
    provider = settings.llm_provider.lower().strip()
    if provider == "gemini":
        return GeminiClient(settings.llm_api_key, settings.llm_model)
    if provider in ("openai", "groq", "openrouter"):
        return OpenAICompatibleClient(
            settings.llm_api_key, settings.llm_model, settings.llm_base_url
        )
    log.warning("알 수 없는 LLM_PROVIDER=%s, 규칙 코치를 써요", provider)
    return None


class Coach:
    def __init__(self, llm: LLMClient | None) -> None:
        self.llm = llm

    def comment(self, trade: Trade, facts: list[Fact], portfolio_line: str) -> tuple[str, str]:
        """(문장, 출처) — 출처는 'gemini' / 'openai' / 'rule'."""
        fallback = rule_comment(facts)
        if not self.llm:
            return fallback, "rule"
        side = "매수" if trade.side == "buy" else "매도"
        user = (
            f"방금 한 매매: {trade.name} {trade.qty:,}주 {side} "
            f"(1주 {trade.price:,.0f}원, 오늘 등락 {trade.change_pct:+.2f}%)\n"
            f"계좌 상태: {portfolio_line}\n"
            "관찰한 사실:\n" + "\n".join(f"- {f.text}" for f in facts[:3])
        )
        return self.say(SYSTEM_PROMPT, user, fallback, limit=600)

    def say(self, system: str, user: str, fallback: str, limit: int = 1200) -> tuple[str, str]:
        """LLM에게 물어보고, 키가 없거나 실패하면 fallback 문장을 돌려줘요."""
        if not self.llm:
            return fallback, "rule"
        try:
            text = self.llm.complete(system, user)
            if text:
                return text[:limit], self.llm.name
        except Exception as e:  # 한도 초과, 네트워크 오류 등
            log.warning("LLM 실패, 규칙 문장으로 대체: %s", e)
        return fallback, "rule"
