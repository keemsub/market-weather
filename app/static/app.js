// 시장 날씨 — 화면 동작
const $ = (s) => document.querySelector(s);
const won = (n) => Math.round(n).toLocaleString("ko-KR");
const sign = (n) => (n > 0 ? "+" : "") + n.toFixed(2);
const tone = (n) => (n > 0 ? "up" : n < 0 ? "down" : "flat");
const TONE_COLOR = {
  hot: "#ff9a3c", sunny: "#3d9be9", partly: "#7cc0f0", cloudy: "#a3b1c2",
  shower: "#7f93ad", rain: "#4f6280", storm: "#2b3449",
};

const state = { weathers: {}, market: "KR", portfolio: null, order: null, side: "buy" };
try { if (localStorage.getItem("mkt") === "US") state.market = "US"; } catch (e) {}
const usd = (n) => "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const px = (q) => (q.currency === "USD" ? usd(q.price) : `${won(q.price)}원`);

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "잠시 뒤 다시 시도해 주세요.");
  return data;
}

// ---------- 하늘 연출 ----------
function paintSky(key) {
  const sky = $("#sky");
  sky.dataset.weather = key;
  const fx = sky.querySelector(".sky-fx");
  fx.innerHTML = "";
  const add = (cls, style) => {
    const el = document.createElement("div");
    el.className = cls;
    Object.assign(el.style, style);
    fx.appendChild(el);
  };
  if (["hot", "sunny", "partly"].includes(key)) add("sun", {});
  const clouds = { hot: 0, sunny: 1, partly: 3, cloudy: 5, shower: 4, rain: 5, storm: 6 }[key] || 0;
  for (let i = 0; i < clouds; i++) {
    add("cloud", {
      top: `${10 + Math.random() * 45}%`,
      animationDuration: `${28 + Math.random() * 30}s`,
      animationDelay: `${-Math.random() * 50}s`,
      transform: `scale(${0.6 + Math.random() * 0.7})`,
    });
  }
  const drops = { shower: 25, rain: 60, storm: 90 }[key] || 0;
  for (let i = 0; i < drops; i++) {
    add("drop", {
      left: `${Math.random() * 110}%`,
      animationDuration: `${0.6 + Math.random() * 0.6}s`,
      animationDelay: `${-Math.random() * 2}s`,
      opacity: 0.4 + Math.random() * 0.6,
    });
  }
  if (key === "storm") add("flash", {});
}

// ---------- 날씨 화면 ----------
async function loadWeather(m = state.market) {
  try {
    const w = await api(`/api/weather?m=${m}`);
    state.weathers[m] = w;
    if (m === state.market) renderWeather(w);
    if (state.portfolio) renderWallet();
  } catch (e) {
    if (m === state.market) $("#updated").textContent = "날씨를 못 불러왔어요";
  }
}

function setMarket(m) {
  state.market = m;
  try { localStorage.setItem("mkt", m); } catch (e) {}
  document.querySelectorAll("#mkt button").forEach((b) => b.classList.toggle("active", b.dataset.m === m));
  if (state.weathers[m]) renderWeather(state.weathers[m]);
  loadWeather(m);
}
$("#mkt").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) setMarket(b.dataset.m);
});

function renderWeather(w) {
  const main = w.indices[0];
  if (main) {
    paintSky(main.weather.key);
    $("#hero").innerHTML = `
      <div class="hero-emoji">${main.weather.emoji}</div>
      <div class="hero-text">
        <div class="hero-title">오늘 ${main.name} 하늘</div>
        <div class="hero-big">${main.weather.label}</div>
        <div class="hero-line">${main.weather.line}</div>
      </div>`;
  }
  $("#indices").style.gridTemplateColumns = `repeat(${w.indices.length}, 1fr)`;
  $("#indices").innerHTML = w.indices.map((i) => `
    <div class="index-card">
      <div class="nm"><span>${i.name}</span><span>${i.weather.emoji}</span></div>
      <div class="px">${i.price.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
      <div class="ch ${tone(i.change_pct)}">${w.indices.length > 2 ? "" : Math.abs(i.change).toFixed(2) + " "}(${sign(i.change_pct)}%)</div>
    </div>`).join("");
  const t = new Date(w.updated_at);
  $("#updated").textContent = `${t.getHours()}:${String(t.getMinutes()).padStart(2, "0")} 기준${w.source === "demo" ? " · 연습용" : ""}`;
  $("#demo-banner").classList.toggle("hidden", w.source !== "demo");

  $("#sectors").innerHTML = w.sectors.map((s) => `
    <button class="tile" data-sector="${s.id}" style="--tone:${TONE_COLOR[s.weather.key]}">
      <div class="row1"><span class="sec">${s.icon} ${s.name}</span><span class="wx">${s.weather.emoji}</span></div>
      <div class="label">${s.weather.label}</div>
      <div class="meta"><b class="${tone(s.change_pct)}">${sign(s.change_pct)}%</b><span>강수확률 ${s.rain_chance}%</span></div>
    </button>`).join("");
  $("#legend").innerHTML = "☀️ 쨍쨍 · 🌤️ 맑음 · ⛅ 구름 조금 · ☁️ 흐림 · 🌦️ 소나기 · 🌧️ 비 · ⛈️ 천둥번개<br>강수확률 = 그 업종에서 오늘 내린 종목 비율";
  $("#fx-note").innerHTML = w.market === "US"
    ? `환율 1달러 = ${won(w.fx.usdkrw)}원${w.fx.source === "demo" ? " (연습용)" : ""} · 내 지갑은 원화로 계산해요<br>미국 장은 한국 시간 밤 11:30 ~ 새벽 6시 (서머타임엔 1시간 빨라요)`
    : "국내 장은 오전 9시 ~ 오후 3시 30분이에요";
  if (state.openSector) renderSector(state.openSector);
}

$("#sectors").addEventListener("click", (e) => {
  const tile = e.target.closest(".tile");
  if (!tile) return;
  state.openSector = tile.dataset.sector;
  renderSector(state.openSector);
  $("#sector-sheet").classList.remove("hidden");
});

function renderSector(id) {
  const s = state.weathers[state.market]?.sectors.find((x) => x.id === id);
  if (!s) return;
  $("#sector-head").innerHTML = `
    <div class="big">${s.weather.emoji}</div>
    <div><h3>${s.icon} ${s.name} · ${s.weather.label}</h3><p>${s.weather.line}</p></div>`;
  $("#sector-stocks").innerHTML = s.stocks.map((q) => `
    <button class="item" data-code="${q.code}">
      <div class="ic">${q.weather.emoji}</div>
      <div class="main"><div class="t1">${q.name}</div><div class="t2">${q.code}</div></div>
      <div class="right">
        <div class="p1">${px(q)}</div>
        <div class="p2 ${tone(q.change_pct)}">${sign(q.change_pct)}%</div>
        ${q.currency === "USD" ? `<div class="krw">≈ ${won(q.price_krw)}원</div>` : ""}
      </div>
    </button>`).join("");
}

$("#sector-stocks").addEventListener("click", (e) => {
  const it = e.target.closest(".item");
  if (it) openOrder(it.dataset.code, "buy");
});

// ---------- 주문 ----------
function findQuote(code) {
  for (const w of Object.values(state.weathers)) {
    for (const s of w.sectors) {
      const q = s.stocks.find((x) => x.code === code);
      if (q) return q;
    }
  }
  return null;
}
const held = (code) => state.portfolio?.holdings.find((h) => h.code === code);

function openOrder(code, side) {
  const q = findQuote(code);
  if (!q) return;
  state.order = q;
  setSide(side);
  $("#qty").value = 1;
  $("#order-error").textContent = "";
  $("#order-sheet").classList.remove("hidden");
}

function setSide(side) {
  state.side = side;
  document.querySelectorAll(".seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.side === side));
  $("#order-btn").classList.toggle("sell", side === "sell");
  renderOrder();
}

function maxQty() {
  const q = state.order;
  if (!q) return 0;
  if (state.side === "buy") return Math.floor((state.portfolio?.cash || 0) / (q.price_krw * 1.00015));
  return held(q.code)?.qty || 0;
}

function renderOrder() {
  const q = state.order;
  if (!q) return;
  const h = held(q.code);
  $("#order-head").innerHTML = `
    <h3>${q.weather.emoji} ${q.name}</h3>
    <div class="px">${px(q)} <span class="${tone(q.change_pct)}" style="font-size:15px">${sign(q.change_pct)}%</span></div>
    ${q.currency === "USD" ? `<div class="hold">1주 ≈ ${won(q.price_krw)}원 (환율 적용)</div>` : ""}
    <div class="hold">${h ? `보유 ${won(h.qty)}주 · 평균 ${won(h.avg_price)}원` : "아직 갖고 있지 않아요"}</div>`;
  const qty = Math.max(0, parseInt($("#qty").value || "0", 10));
  const amount = qty * q.price_krw;
  $("#order-info").innerHTML = `
    주문 금액 <b>${won(amount)}원</b><br>
    ${state.side === "buy" ? `내 현금 <b>${won(state.portfolio?.cash || 0)}원</b>` : `팔 수 있는 수량 <b>${won(h?.qty || 0)}주</b>`}
    · 최대 <b>${won(maxQty())}주</b>`;
  $("#order-btn").textContent = `${won(qty)}주 ${state.side === "buy" ? "사기" : "팔기"}`;
}

document.querySelectorAll(".seg-btn").forEach((b) => b.addEventListener("click", () => setSide(b.dataset.side)));
document.querySelectorAll(".qty-btn").forEach((b) => b.addEventListener("click", () => {
  const v = Math.max(1, (parseInt($("#qty").value || "0", 10) || 0) + parseInt(b.dataset.d, 10));
  $("#qty").value = v;
  renderOrder();
}));
$("#quick-row").addEventListener("click", (e) => {
  const f = e.target.dataset.frac;
  if (!f) return;
  $("#qty").value = Math.max(1, Math.floor(maxQty() * parseFloat(f)));
  renderOrder();
});
$("#qty").addEventListener("input", renderOrder);

$("#order-btn").addEventListener("click", async () => {
  const qty = parseInt($("#qty").value || "0", 10);
  const btn = $("#order-btn");
  btn.disabled = true;
  $("#order-error").textContent = "";
  showCoach(null);
  try {
    const r = await api("/api/trade", {
      method: "POST",
      body: JSON.stringify({ code: state.order.code, side: state.side, qty }),
    });
    state.portfolio = r.portfolio;
    renderWallet();
    closeSheets();
    showCoach(r.coach);
    upgradeCoach(r.trade.id);
  } catch (e) {
    $("#order-error").textContent = e.message;
    hideCoach();
  } finally {
    btn.disabled = false;
  }
});

// ---------- 코치 ----------
const SRC = { gemini: "AI · Gemini", openai: "AI", rule: "기본 답변" };
function showCoach(c) {
  $("#coach").classList.remove("hidden");
  const t = $("#coach-text");
  if (!c) {
    t.textContent = "";
    t.classList.add("coach-typing");
    $("#coach-src").textContent = "";
    return;
  }
  t.classList.remove("coach-typing");
  t.textContent = c.text;
  $("#coach-src").textContent = SRC[c.source] || "";
}
function hideCoach() { $("#coach").classList.add("hidden"); }

// 매매는 바로 끝내고, AI 코치 한마디는 따로 받아서 바꿔 끼워요.
async function upgradeCoach(tradeId) {
  if (state.portfolio?.coach_mode === "rule") return;
  $("#coach-src").textContent = "AI가 다듬는 중…";
  try {
    const c = await api(`/api/trade/${tradeId}/coach`, { method: "POST" });
    if (!$("#coach").classList.contains("hidden")) showCoach(c);
    const t = state.portfolio?.trades.find((x) => x.id === tradeId);
    if (t) { t.coach = c.text; t.coach_source = c.source; renderWallet(); }
  } catch (e) {
    $("#coach-src").textContent = SRC.rule;
  }
}
$("#coach-close").addEventListener("click", hideCoach);

// ---------- 지갑 ----------
async function loadPortfolio() {
  try {
    state.portfolio = await api("/api/portfolio");
    renderWallet();
  } catch (e) { /* 다음에 다시 */ }
}

function renderWallet() {
  const p = state.portfolio;
  if (!p) return;
  $("#w-total").textContent = `${won(p.total)}원`;
  const diff = p.total - p.start;
  $("#w-return").textContent = `${diff >= 0 ? "+" : ""}${won(diff)}원 (${sign(p.return_pct)}%)`;
  $("#w-return").className = `wallet-return ${tone(diff)}`;
  $("#w-cash").textContent = `${won(p.cash)}원`;
  $("#w-stock").textContent = `${won(p.stock_value)}원`;
  $("#w-invested").textContent = `${won(p.invested)}원`;
  $("#w-unreal").innerHTML = `<span class="${tone(p.unrealized)}">${p.unrealized > 0 ? "+" : ""}${won(p.unrealized)}원 (${sign(p.unrealized_pct)}%)</span>`;
  $("#w-real").innerHTML = `<span class="${tone(p.realized)}">${p.realized > 0 ? "+" : ""}${won(p.realized)}원</span>`;
  const cashPct = p.total ? (p.cash / p.total) * 100 : 100;
  $("#w-bar-cash").style.width = `${cashPct}%`;
  $("#w-bar-stock").style.width = `${100 - cashPct}%`;
  $("#w-cash-pct").textContent = `${cashPct.toFixed(0)}%`;
  $("#w-stock-pct").textContent = `${(100 - cashPct).toFixed(0)}%`;
  const t = new Date();
  $("#w-live").textContent = `· ${t.getHours()}:${String(t.getMinutes()).padStart(2, "0")} 현재가 기준`;

  $("#holdings").innerHTML = p.holdings.length
    ? p.holdings.map((h) => `
      <button class="item holding" data-code="${h.code}">
        <div class="top">
          <div class="ic">${findQuote(h.code)?.weather.emoji || "📈"}</div>
          <div class="main"><div class="t1">${h.market === "US" ? "🇺🇸 " : ""}${h.name}</div><div class="t2">${won(h.qty)}주 · 오늘 <span class="${tone(h.today_pct)}">${sign(h.today_pct)}%</span></div></div>
          <div class="right">
            <div class="p1">${won(h.value)}원</div>
            <div class="p2 ${tone(h.pnl)}">${h.pnl > 0 ? "+" : ""}${won(h.pnl)} (${sign(h.pnl_pct)}%)</div>
          </div>
        </div>
        <div class="hold-grid">
          <span>평균 단가 <b>${won(h.avg_price)}원</b></span>
          <span>현재가 <b>${won(h.price)}원${h.currency === "USD" && h.native_price ? ` (${usd(h.native_price)})` : ""}</b></span>
          <span>매입금액 <b>${won(h.avg_price * h.qty)}원</b></span>
          <span>평가금액 <b>${won(h.value)}원</b></span>
        </div>
      </button>`).join("")
    : `<div class="empty">아직 산 주식이 없어요.<br>날씨 탭에서 업종을 눌러 첫 투자를 해 보세요 🌱</div>`;

  $("#journal").innerHTML = p.trades.length
    ? p.trades.map((t) => {
      const d = new Date(t.created_at.endsWith("Z") || t.created_at.includes("+") ? t.created_at : t.created_at + "Z");
      return `
      <div class="item journal">
        <div class="jt"><span><b class="${t.side}">${t.side === "buy" ? "매수" : "매도"}</b> ${t.name} ${won(t.qty)}주 · ${won(t.price)}원</span>
        <span class="flat">${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")}</span></div>
        ${t.coach ? `<div class="jc">${escapeHtml(t.coach)}</div>` : ""}
      </div>`;
    }).join("")
    : `<div class="empty">매매하면 코치 구름이가 한마디씩 남겨 줘요.</div>`;
}

$("#holdings").addEventListener("click", (e) => {
  const it = e.target.closest(".item");
  if (it) openOrder(it.dataset.code, "sell");
});
// 주문 시트는 지금 보고 있는 시장과 상관없이 열려요 (findQuote가 두 시장을 다 찾아요).

$("#reset-btn").addEventListener("click", async () => {
  if (!confirm("모든 기록을 지우고 1,000만 원으로 다시 시작할까요?")) return;
  await api("/api/reset", { method: "POST" });
  await loadPortfolio();
});

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- 탭 / 시트 ----------
document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === b));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${b.dataset.view}`));
  hideCoach();
  window.scrollTo(0, 0);
  if (b.dataset.view === "chat") renderChat();
  if (b.dataset.view === "wallet") loadPortfolio();
}));

function closeSheets() {
  document.querySelectorAll(".sheet-wrap").forEach((s) => s.classList.add("hidden"));
  state.openSector = null;
}
document.querySelectorAll(".sheet-wrap").forEach((w) => w.addEventListener("click", (e) => {
  if (e.target === w) {
    w.classList.add("hidden");
    if (w.id === "sector-sheet") state.openSector = null;
  }
}));

// ---------- 시작 ----------
// ---------- 구름이에게 질문하기 ----------
const CHAT_KEY = "chat";
state.chat = [];
try { state.chat = JSON.parse(localStorage.getItem(CHAT_KEY) || "[]"); } catch (e) {}
const saveChat = () => { try { localStorage.setItem(CHAT_KEY, JSON.stringify(state.chat.slice(-30))); } catch (e) {} };

function renderChat() {
  const list = $("#chat-list");
  const greet = { role: "coach", text: "안녕하세요, 구름이예요 ☁️\n오늘 시장 날씨, 궁금한 종목, 내 지갑 상태를 물어보세요. 시세와 내 매매 기록을 보고 답해 드릴게요." };
  list.innerHTML = [greet, ...state.chat].map((m) => `
    <div class="msg m-${m.role}">${escapeHtml(m.text)}${m.role === "coach" && m.source ? `<small>${SRC[m.source] || ""}</small>` : ""}</div>`).join("")
    + (state.asking ? `<div class="msg m-coach typing"></div>` : "");
  renderChips();
  window.scrollTo(0, document.body.scrollHeight);
}

function renderChips() {
  const w = state.weathers[state.market];
  const chips = ["오늘 시장 어때?"];
  if (w) {
    const all = w.sectors.flatMap((s) => s.stocks);
    const big = all.sort((a, b) => Math.abs(b.change_pct) - Math.abs(a.change_pct))[0];
    if (big) chips.push(`${big.name} 왜 ${big.change_pct >= 0 ? "올랐어" : "떨어졌어"}?`);
  }
  chips.push("내 지갑 어때?", "분산 투자가 뭐야?", "손절은 언제 해야 해?");
  $("#chips").innerHTML = chips.map((c) => `<button type="button">${escapeHtml(c)}</button>`).join("");
}
$("#chips").addEventListener("click", (e) => {
  if (e.target.tagName === "BUTTON") sendQuestion(e.target.textContent);
});

async function sendQuestion(q) {
  q = (q || "").trim();
  if (!q || state.asking) return;
  const history = state.chat.slice(-6).map(({ role, text }) => ({ role, text: text.slice(0, 1200) }));
  state.chat.push({ role: "user", text: q });
  state.asking = true;
  $("#chat-send").disabled = true;
  renderChat();
  try {
    const r = await api("/api/ask", { method: "POST", body: JSON.stringify({ question: q, history }) });
    state.chat.push({ role: "coach", text: r.text, source: r.source });
  } catch (e) {
    state.chat.push({ role: "coach", text: `앗, 답을 못 가져왔어요. ${e.message}` });
  } finally {
    state.asking = false;
    $("#chat-send").disabled = false;
    saveChat();
    renderChat();
  }
}
$("#chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("#chat-q").value;
  $("#chat-q").value = "";
  sendQuestion(q);
});
$("#chat-clear").addEventListener("click", () => { state.chat = []; saveChat(); renderChat(); });

// ---------- 주간 리포트 ----------
$("#report-btn").addEventListener("click", async () => {
  const body = $("#report-body");
  body.innerHTML = `<div class="rp-top"><div class="wx">☁️</div><h3>리포트를 쓰는 중…</h3><p>구름이가 이번 주 기록을 읽고 있어요</p></div>`;
  $("#report-sheet").classList.remove("hidden");
  try {
    const r = await api("/api/report");
    const st = r.stats;
    const money = (n) => `${n > 0 ? "+" : ""}${won(n)}원`;
    body.innerHTML = `
      <div class="rp-top"><div class="wx">${r.weather.emoji}</div><h3>이번 주는 ${r.weather.label}</h3><p>최근 ${st.days}일 기록 · 수익률과 매매 습관을 함께 봤어요</p></div>
      <div class="rp-grid">
        <div><span>매매</span><b>${st.trades}번</b></div>
        <div><span>실현 손익</span><b class="${tone(st.realized)}">${money(st.realized)}</b></div>
        <div><span>매도 승률</span><b>${st.win_rate == null ? "-" : st.win_rate + "%"}</b></div>
        <div><span>총 수익률</span><b class="${tone(st.return_pct)}">${sign(st.return_pct)}%</b></div>
        <div><span>추격 매수</span><b>${st.chase_buys}번</b></div>
        <div><span>10분 단타</span><b>${st.quick_flips}번</b></div>
      </div>
      <div class="rp-text">${escapeHtml(r.text)}<small>☁️ 코치 구름이 · ${SRC[r.source] || ""}</small></div>
      <div class="rp-tags">
        ${st.top_stocks.length ? `많이 거래한 종목: ${escapeHtml(st.top_stocks.join(", "))}<br>` : ""}
        ${st.top_sectors.length ? `많이 거래한 업종: ${escapeHtml(st.top_sectors.join(", "))}<br>` : ""}
        현금 비중 ${st.cash_pct}%${st.top_holding ? ` · 가장 큰 보유 ${escapeHtml(st.top_holding)} ${st.top_holding_pct}%` : ""}
      </div>`;
  } catch (e) {
    body.innerHTML = `<div class="rp-top"><div class="wx">🌧️</div><h3>리포트를 못 만들었어요</h3><p>${escapeHtml(e.message)}</p></div>`;
  }
});

// ---------- 첫 화면: 로딩 → 국내/해외 고르기 ----------
async function boot() {
  const t0 = Date.now();
  await Promise.all([loadWeather("KR"), loadWeather("US"), loadPortfolio()]);
  const wait = 1500 - (Date.now() - t0);
  if (wait > 0) await new Promise((r) => setTimeout(r, wait));
  for (const m of ["KR", "US"]) {
    const i = state.weathers[m]?.indices[0];
    if (i) {
      $(`#pick-${m}`).textContent = `${i.name} ${i.weather.label} · ${sign(i.change_pct)}%`;
      $(`#pickwx-${m}`).textContent = i.weather.emoji;
    }
  }
  $("#splash-load").classList.add("hidden");
  $("#splash-pick").classList.remove("hidden");
}
$("#splash-pick").addEventListener("click", (e) => {
  const b = e.target.closest(".pick");
  if (!b) return;
  setMarket(b.dataset.m);
  $("#splash").classList.add("out");
  setTimeout(() => $("#splash").remove(), 500);
});

boot();
// 1분마다 시세를 다시 받아 지갑 평가금액도 같이 바꿔요.
setInterval(() => { loadWeather(state.market); loadPortfolio(); }, 60_000);
