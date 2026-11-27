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
  } catch (e) {
    $("#order-error").textContent = e.message;
    hideCoach();
  } finally {
    btn.disabled = false;
  }
});

// ---------- 코치 ----------
const SRC = { gemini: "AI · Gemini", openai: "AI", rule: "기본 코치" };
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
  $("#w-cash").textContent = `${won(p.cash)}원`;
  $("#w-stock").textContent = `${won(p.stock_value)}원`;

  $("#holdings").innerHTML = p.holdings.length
    ? p.holdings.map((h) => `
      <button class="item" data-code="${h.code}">
        <div class="ic">${findQuote(h.code)?.weather.emoji || "📈"}</div>
        <div class="main"><div class="t1">${h.market === "US" ? "🇺🇸 " : ""}${h.name}</div><div class="t2">${won(h.qty)}주 · 평균 ${won(h.avg_price)}원${h.currency === "USD" && h.native_price ? ` · 지금 ${usd(h.native_price)}` : ""}</div></div>
        <div class="right">
          <div class="p1">${won(h.value)}원</div>
          <div class="p2 ${tone(h.pnl)}">${h.pnl >= 0 ? "+" : ""}${won(h.pnl)} (${sign(h.pnl_pct)}%)</div>
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
setMarket(state.market);
loadWeather(state.market === "KR" ? "US" : "KR");
loadPortfolio();
setInterval(() => loadWeather(state.market), 60_000);
