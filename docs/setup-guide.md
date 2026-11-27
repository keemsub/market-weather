# 키 발급과 무료 배포 안내

필요한 건 딱 두 가지예요. 둘 다 무료예요.

1. **AI 코치 키** (선택, 없어도 앱은 동작)
2. **Render에 올리기** (뽀모도로랑 같은 방법)

---

## 1. AI 코치 키 받기 (Google Gemini, 무료)

1. https://aistudio.google.com 에 구글 계정으로 들어가요.
2. 왼쪽 메뉴의 **Get API key** → **API 키 만들기(Create API key)** 를 눌러요.
3. 나온 키(`AIza...`로 시작)를 복사해요. 카드 등록은 필요 없어요.
4. 이 키를 아래 Render 설정의 `LLM_API_KEY`에 넣으면 끝!

알아 두면 좋은 점

- 무료 한도(분당·하루 요청 수)가 있어요. 한도를 넘거나 오류가 나면 앱이 알아서 **규칙 코치**로 바꿔서 말해요. 화면의 코치 이름 옆에 `AI · Gemini` 또는 `기본 코치`로 표시돼요.
- 무료 등급에서는 구글이 입력 내용을 서비스 개선에 쓸 수 있어요. 코치에게는 매매 내용(종목, 수량, 가격)만 보내고 개인정보는 보내지 않아요.
- 모델을 바꾸고 싶으면 `LLM_MODEL`에 이름을 넣어요 (기본값 `gemini-2.5-flash`). 구글이 모델 이름을 바꾸면 여기만 고치면 돼요.

### 다른 무료 모델을 쓰고 싶다면 (Groq)

1. https://console.groq.com 가입 → **API Keys** → **Create API Key**
2. Render 환경 변수를 이렇게 바꿔요.
   - `LLM_PROVIDER` = `openai`
   - `LLM_BASE_URL` = `https://api.groq.com/openai/v1`
   - `LLM_MODEL` = `llama-3.3-70b-versatile`
   - `LLM_API_KEY` = 방금 받은 키

OpenAI 형식을 쓰는 다른 곳(OpenRouter 등)도 같은 방법으로 바꿀 수 있어요.

---

## 2. Render에 무료로 올리기

1. https://dashboard.render.com 에 들어가요 (뽀모도로 때 쓴 계정 그대로).
2. 오른쪽 위 **New** → **Blueprint** 를 눌러요.
3. 저장소 목록에서 **market-weather** 를 골라요. (안 보이면 *Configure account* 에서 이 저장소 접근을 허용해 주세요.)
4. `render.yaml`을 읽어서 설정 화면이 나와요. `LLM_API_KEY` 칸에 1번에서 받은 키를 붙여 넣어요. (비워 둬도 돼요)
5. **Apply** 를 누르면 몇 분 뒤 `https://market-weather-xxxx.onrender.com` 주소가 생겨요.

알아 두면 좋은 점

- 무료 서버는 15분 동안 아무도 안 쓰면 잠들어요. 다시 열 때 30초~1분 정도 걸려요.
- 무료 서버는 다시 시작하면 파일이 지워져서 **매매 기록이 초기화**돼요. 기록을 남기려면 아래 3번을 해 주세요.
- 시세는 국내는 네이버 증권, 미국과 환율은 야후 파이낸스에서 가져와요(둘 다 키 필요 없음). 서버는 같은 시세를 60초 동안 재사용하고, 화면은 1분마다 새로 불러와요. 서버에서 시세를 못 가져오면 화면 위에 "연습용 시세" 안내가 뜨고 가짜 시세로 동작해요. 국내·미국 각각 따로 바뀌어요. 그럴 땐 알려 주세요, 다른 시세 출처로 바꿔 드릴게요.

## 3. (선택) 기록이 안 사라지게: Neon 무료 데이터베이스

1. https://neon.tech 가입 → 새 프로젝트 만들기 (지역은 Singapore 추천)
2. **Connection string** (`postgresql://...`로 시작)을 복사해요.
3. Render → market-weather → **Environment** → `DATABASE_URL` 에 붙여 넣고 저장해요.

뽀모도로에서 이미 Neon을 쓰고 있다면, 같은 Neon 계정에 프로젝트를 하나 더 만들면 돼요.
