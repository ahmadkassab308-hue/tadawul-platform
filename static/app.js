"use strict";
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (x, d = 2) => (x === null || x === undefined || isNaN(x)) ? "—" : Number(x).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (x) => (x === null || x === undefined) ? "—" : Math.round(x * 100) + "%";
const VB = { BUY: "شراء", SELL: "بيع", HOLD: "احتفاظ" };
const MK_TAPE = {
  SA: [["TADAWUL:TASI","تاسي"],["TADAWUL:2222","أرامكو"],["TADAWUL:1120","الراجحي"],["TADAWUL:1180","الأهلي"],["TADAWUL:2010","سابك"],["TADAWUL:7010","stc"],["TADAWUL:1211","معادن"],["TADAWUL:2082","أكوا"]],
  US: [["SP:SPX","S&P 500"],["NASDAQ:NDX","Nasdaq 100"],["NASDAQ:AAPL","Apple"],["NASDAQ:NVDA","Nvidia"],["NASDAQ:MSFT","Microsoft"],["NASDAQ:TSLA","Tesla"],["NASDAQ:AMZN","Amazon"]],
  EU: [["TVC:SX5E","Euro Stoxx 50"],["EURONEXT:ASML","ASML"],["XETR:SAP","SAP"],["EURONEXT:MC","LVMH"],["LSE:AZN","AstraZeneca"],["SIX:NESN","Nestlé"]],
  GULF: [["DFM:EMAAR","إعمار"],["DFM:EMIRATESNBD","الإمارات دبي الوطني"],["QSE:QNBK","QNB"],["KSE:NBK","الوطني الكويتي"],["KSE:KFH","بيتك"]],
  ASIA: [["TVC:NI225","Nikkei 225"],["TVC:HSI","Hang Seng"],["TSE:7203","Toyota"],["HKEX:700","Tencent"],["TWSE:2330","TSMC"],["NSE:RELIANCE","Reliance"]],
  EG: [["EGX:COMI","CIB"],["EGX:TMGH","طلعت مصطفى"],["EGX:EAST","الشرقية للدخان"],["EGX:SWDY","السويدي"]],
  CRYPTO: [["BITSTAMP:BTCUSD","Bitcoin"],["BITSTAMP:ETHUSD","Ethereum"],["COMEX:GC1!","الذهب"],["NYMEX:CL1!","النفط WTI"]],
};
const S = { cfg: null, market: localStorage.getItem("mkt") || "SA", symbol: null, quote: null, analysis: null, chart: null, series: null, timers: [], chartMode: "own", tf: "1Y" };

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (r.status === 401) { document.body.innerHTML = "<h2 style='text-align:center;margin-top:30vh'>🔒 افتح الرابط الكامل مع مفتاح الدخول</h2>"; throw new Error("401"); }
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch (e) {} throw new Error(m); }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}
function clearTimers() { S.timers.forEach((t) => { clearInterval(t); clearTimeout(t); }); S.timers = []; }

/* ---------- TradingView official widgets (s3.tradingview.com embed scripts) ---------- */
function tvWidget(el, name, cfg) {
  el.innerHTML = "";
  const wrap = document.createElement("div"); wrap.className = "tradingview-widget-container"; wrap.style.height = "100%";
  const inner = document.createElement("div"); inner.className = "tradingview-widget-container__widget"; inner.style.height = "100%";
  wrap.appendChild(inner);
  const sc = document.createElement("script"); sc.type = "text/javascript"; sc.async = true;
  sc.src = `https://s3.tradingview.com/external-embedding/embed-widget-${name}.js`;
  sc.innerHTML = JSON.stringify(cfg);
  wrap.appendChild(sc); el.appendChild(wrap);
}
function tape(market) {
  const syms = (MK_TAPE[market] || MK_TAPE.SA).map(([p, t]) => ({ proName: p, title: t }));
  tvWidget($("#tape"), "ticker-tape", { symbols: syms, showSymbolLogo: true, colorTheme: "dark", isTransparent: true, displayMode: "adaptive", locale: "ar_AE" });
}
const tvLink = (tvs) => `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tvs)}`;

/* ---------- search ---------- */
let sT = null;
$("#search").addEventListener("input", (e) => {
  clearTimeout(sT); const q = e.target.value.trim();
  if (!q) { $("#results").classList.add("hidden"); return; }
  sT = setTimeout(async () => {
    $("#results").innerHTML = `<div style="padding:12px"><span class="spinner"></span></div>`; $("#results").classList.remove("hidden");
    try {
      let { results } = await api("/api/search?q=" + encodeURIComponent(q));
      if (/^\d{4}$/.test(q) && !results.some((r) => r.symbol === q + ".SR")) results.unshift({ symbol: q + ".SR", name: "تداول " + q, exchange: "Saudi", market: "SA" });
      $("#results").innerHTML = results.length ? results.map((r) => `<a href="#/s/${encodeURIComponent(r.symbol)}"><span><b class="ltr">${esc(r.symbol)}</b> · ${esc(r.name)}</span><span class="muted small">${esc(r.exchange || "")} ${esc(r.type || "")}</span></a>`).join("") : `<div style="padding:12px" class="muted">NOT FOUND — لا نتائج</div>`;
    } catch (err) { $("#results").innerHTML = `<div style="padding:12px" class="dn">${esc(err.message)}</div>`; }
  }, 280);
});
$("#search").addEventListener("keydown", (e) => { if (e.key === "Enter") { const a = $("#results a"); if (a) location.hash = a.getAttribute("href"); else if (e.target.value.trim()) location.hash = "#/s/" + encodeURIComponent(e.target.value.trim().toUpperCase()); } });
document.addEventListener("click", (e) => { if (!e.target.closest(".searchwrap")) $("#results").classList.add("hidden"); });
window.addEventListener("hashchange", () => { $("#results").classList.add("hidden"); $("#search").value = ""; route(); });

/* ---------- router ---------- */
function route() {
  clearTimers(); if (S.chart) { try { S.chart.remove(); } catch (e) {} S.chart = null; }
  const h = location.hash || "#/";
  if (h.startsWith("#/s/")) return stockPage(decodeURIComponent(h.slice(4)));
  if (h.startsWith("#/tv")) return tvHelp();
  S.symbol = null; S.analysis = null; chatCtx(); return homePage();
}

/* ---------- home ---------- */
async function homePage(refresh) {
  clearTimers();
  const v = $("#view"); if (!refresh) tape(S.market);
  const tabs = S.cfg.markets.map((m) => `<button class="tab ${m.id === S.market ? "on" : ""}" data-m="${m.id}">${esc(m.short)}</button>`).join("");
  if (!refresh || !$("#home")) v.innerHTML = `<div class="tabs">${tabs}</div><div id="home"><span class="spinner"></span></div>`;
  v.querySelectorAll(".tab").forEach((b) => b.onclick = () => { S.market = b.dataset.m; localStorage.setItem("mkt", S.market); homePage(); });
  const [d, bt, al] = await Promise.all([api("/api/home?market=" + S.market), api("/api/backtest"), api("/api/alerts")]);
  const m = d.info; const sc = d.scan; const st = d.scanner;
  const scanLine = sc ? `آخر مسح: <b>${esc(sc.scanned_at)}</b> (توقيت الرياض) · ${sc.n}/${sc.universe_size} سهم · يتجدد كل ${sc.every_h} ساعات · مدة ${Math.round(sc.duration_s / 60)} د${sc.errors.length ? ` · تعذر ${sc.errors.length}` : ""}` :
    (d.universe.length && S.market !== "CRYPTO" ? "لم يكتمل أول مسح لهذا السوق بعد." : "هذا القسم بلا مسح آلي — ابحث عن الرمز وحلّله مباشرة.");
  const running = st.running ? ` · <span class="spinner"></span> جاري مسح ${esc(st.running)} (${st.progress}/${st.total})` : "";
  const cand = d.candidates.length ? `<div class="grid">${d.candidates.map(candCard).join("")}</div>` :
    `<div class="card muted">${sc ? "لا توجد توصيات «شراء» في آخر مسح لهذا السوق — اللجنة لا تختلق فرصاً. أعلى الأسهم ترتيباً:" : "بانتظار المسح…"}</div>${d.top_ranked.length ? `<div class="grid" style="margin-top:10px">${d.top_ranked.map(candCard).join("")}</div>` : ""}`;
  const pop = S.market === "CRYPTO" ? `<div class="btns">${(S.cfg.popular.CRYPTO || []).map((s) => `<a class="btn" href="#/s/${s}">${s}</a>`).join("")}</div>` : "";
  $("#home").innerHTML = `
   <div class="row"><h2 style="margin-top:4px">${esc(m.name_ar)}</h2></div>
   <div class="note">${scanLine}${running}</div>${pop}
   <h2>⭐ الأسهم المرشحة <span class="muted small">(حكم اللجنة «شراء» من الماسح الآلي)</span></h2>${cand}
   <h2>🏆 الصفقات الرابحة <span class="muted small">— إشارات ورقية (محاكاة) من المحرك، تُتابَع بأسعار لاحقة</span></h2>${paperBlock(d.paper)}
   <h2>📊 إعدادات رابحة من الاختبار الخلفي <span class="muted small">— اختبار خلفي وليس صفقات</span></h2>${btBlock(bt)}
   <h2>🔔 تنبيهات TradingView</h2>${alertsBlock(al.alerts)}`;
  if (st.running) S.timers.push(setTimeout(() => { if (!S.symbol && (location.hash || "#/") === "#/") homePage(true); }, 90000));
}
function badge(en, ar) { return `<span class="badge b-${en || "HOLD"}">${esc(ar || VB[en] || "احتفاظ")}</span>`; }
function candCard(r) {
  return `<a class="card cand" href="#/s/${encodeURIComponent(r.ticker)}">
   <div class="row"><div><b>${esc(r.name_ar || r.name || r.ticker)}</b><div class="muted small ltr">${esc(r.ticker)}</div></div>${badge(r.verdict_en, r.verdict_ar)}</div>
   <div class="row"><span class="big ltr">${fmt(r.price)}</span><span class="small muted">${esc(r.currency || "")} · إغلاق ${esc(r.last_bar_date)}</span></div>
   <div class="row small"><span>ثقة ${pct(r.confidence)}</span><span class="ltr">درجة ${r.score >= 0 ? "+" : ""}${fmt(r.score)}</span><span>${r.n_found}/${r.n_total} صوّتوا</span></div>
   <div class="bar"><i style="width:${Math.round((r.confidence || 0) * 100)}%"></i></div>
   <div class="small">دخول <b class="ltr">${fmt(r.entry_low)}–${fmt(r.entry_high)}</b> · وقف <b class="dn ltr">${fmt(r.stop)}</b> · هدف <b class="up ltr">${fmt(r.t1)}</b></div>
   <div class="small muted">${esc((r.top_reason || "").slice(0, 140))}</div>
   <div>${(r.patterns || []).map((p) => `<span class="chip">🕯️ ${esc(p)}</span>`).join("")}</div></a>`;
}
function paperBlock(p) {
  const row = (t, cls) => `<tr class="click" onclick="location.hash='#/s/${encodeURIComponent(t.ticker)}'"><td><b>${esc(t.name || t.ticker)}</b> <span class="muted ltr">${esc(t.ticker)}</span></td><td>${esc(t.signal_date)}</td><td class="ltr">${fmt(t.entry)}</td><td class="ltr">${fmt(t.stop)}</td><td class="ltr">${fmt(t.t1)} / ${fmt(t.t2)} / ${fmt(t.t3)}</td><td>${statusAr(t)}</td><td class="${cls} ltr"><b>${t.pnl_pct >= 0 ? "+" : ""}${fmt(t.pnl_pct)}%</b></td><td class="muted small">${esc(t.source)}</td></tr>`;
  const head = `<tr><th>السهم</th><th>تاريخ الإشارة</th><th>الدخول</th><th>الوقف</th><th>الأهداف</th><th>الحالة</th><th>النتيجة</th><th>المصدر</th></tr>`;
  const wr = p.win_rate == null ? "لا توجد صفقات مغلقة بعد" : `نسبة النجاح ${p.win_rate}% من ${p.closed} صفقة مغلقة`;
  let h = `<div class="card"><div class="note">${p.total} إشارة شراء مسجّلة · ${wr} · الدخول = إغلاق يوم الإشارة · بعد الهدف الأول يُرفع الوقف لسعر الدخول · لمس الوقف والهدف في نفس اليوم يُحسب وقفاً.</div>`;
  if (p.winners.length) h += `<h3 style="margin-top:10px" class="up">رابحة (بلغت الهدف الأول)</h3><div class="tbl"><table>${head}${p.winners.map((t) => row(t, "up")).join("")}</table></div>`;
  else h += `<p class="muted">لا توجد صفقة ورقية بلغت هدفها بعد — السجل جديد. لن نعرض أرباحاً لم تحدث.</p>`;
  if (p.open.length) h += `<h3 style="margin-top:10px">مفتوحة (${p.open.length})</h3><div class="tbl"><table>${head}${p.open.map((t) => row(t, t.pnl_pct >= 0 ? "up" : "dn")).join("")}</table></div>`;
  if (p.stopped.length) h += `<h3 style="margin-top:10px" class="dn">ضُرب وقفها (${p.stopped.length})</h3><div class="tbl"><table>${head}${p.stopped.map((t) => row(t, "dn")).join("")}</table></div>`;
  return h + "</div>";
}
function statusAr(t) {
  const m = { open: "مفتوحة", stopped: "ضُرب الوقف", closed_breakeven: "خرجت على التعادل بعد الهدف", target1: "بلغت T1", target2: "بلغت T2", target3: "بلغت T3 (أُغلقت)" };
  return (m[t.status] || t.status) + (t.running ? " · مستمرة" : "") + (t.bars_after != null ? ` <span class="muted small">(${t.bars_after} جلسة)</span>` : "");
}
function btBlock(bt) {
  if (!bt.rows.length) return `<div class="card muted">NOT FOUND</div>`;
  return `<div class="card"><div class="note">المصدر: ${esc(bt.source)} · ${bt.n_tickers} سهماً سعودياً · ${esc(bt.span || bt.period || "")}. «إصابة» = تحرك السعر في اتجاه النمط بعد 10 جلسات، قبل العمولات، وليست ربحاً مضموناً. تُعرض الإعدادات التي تفوقت على خط الأساس بـ5 نقاط أو أكثر وبعينة ≥20.</div>
  <div class="tbl"><table><tr><th>النمط</th><th>الاتجاه</th><th>الإعداد</th><th>العينة</th><th>إصابة 10 جلسات</th><th>خط الأساس</th><th>التفوق</th></tr>
  ${bt.rows.map((r) => r.setups.map((s, i) => `<tr><td>${i ? "" : "🕯️ " + esc(r.name_ar)}</td><td>${i ? "" : (r.dir > 0 ? '<span class="up">صاعد</span>' : '<span class="dn">هابط</span>')}</td><td>${esc(s.setup)}</td><td>${s.n}</td><td><b>${s.hit10}%</b></td><td>${r.base10}%</td><td class="up">+${s.edge}</td></tr>`).join("")).join("")}</table></div></div>`;
}
function alertsBlock(a) {
  if (!a.length) return `<div class="card muted">لا تنبيهات بعد. اربط تنبيهات TradingView من صفحة <a class="up" href="#/tv">ربط TradingView</a>.</div>`;
  return `<div class="card tbl"><table><tr><th>الوقت</th><th>الرمز</th><th>رسالة التنبيه</th><th>حكم اللجنة</th><th>السعر</th><th>Grok Bot</th></tr>${a.map((x) => `<tr class="click" onclick="location.hash='#/s/${encodeURIComponent(x.yahoo || "")}'"><td>${esc(x.received_at)}</td><td class="ltr">${esc(x.tv_exchange ? x.tv_exchange + ":" : "")}${esc(x.tv_ticker)} → ${esc(x.yahoo)}</td><td>${esc(x.message)}</td><td>${x.status === "done" ? badge(x.verdict_en, x.verdict_ar) + " " + pct(x.confidence) : x.status === "error" ? '<span class="dn">' + esc(x.error || "خطأ") + "</span>" : '<span class="spinner"></span>'}</td><td class="ltr">${fmt(x.price)}</td><td class="small muted">${esc(x.forward || "—")}</td></tr>`).join("")}</table></div>`;
}

/* ---------- stock page ---------- */
async function stockPage(sym) {
  sym = sym.toUpperCase(); if (/^\d{4}$/.test(sym)) sym += ".SR";
  S.symbol = sym; S.analysis = null; chatCtx();
  const v = $("#view");
  v.innerHTML = `<div class="card" id="qcard"><span class="spinner"></span> ${esc(sym)}</div>
   <div class="card" style="margin-top:12px">
     <div class="row" style="flex-wrap:wrap;margin-bottom:8px">
       <div class="tabs" style="margin:0"><button class="tab on" data-mode="own">شارت المحللين</button><button class="tab" data-mode="tv">شارت TradingView</button></div>
       <div class="tf" id="tfs">${["1D", "1W", "1M", "1Y", "5Y"].map((t) => `<button data-tf="${t}" class="${t === S.tf ? "on" : ""}">${t}</button>`).join("")}</div>
     </div>
     <div id="chartBox"></div><div id="tvBox" class="hidden"></div>
     <div class="note" id="chartNote">الشارت من Yahoo Finance. بعد التحليل تظهر عليه منطقة الدخول والوقف والأهداف وأنماط الشموع.</div>
   </div>
   <div id="ana" style="margin-top:12px"><div class="card"><div class="row" style="flex-wrap:wrap"><div><h3>لجنة ${S.cfg.n_agents} محللاً</h3><div class="note">التحليل يستغرق 10–60 ثانية أول مرة، ويُحفظ مؤقتاً 15 دقيقة.</div></div><button class="btn pri" id="goAna">🧠 حلّل بـ${S.cfg.n_agents} محلل</button></div></div></div>
   <h2>بيانات TradingView</h2>
   <div class="two"><div class="card"><h3>الملخص الفني من TradingView</h3><div id="tvTA" class="tvw" style="height:430px"></div></div><div class="card"><h3>نبذة الشركة</h3><div id="tvProf" class="tvw" style="height:430px"></div></div></div>
   <div class="note">ويدجت TradingView رسمية ومجانية؛ قد لا تتوفر بيانات بعض الأسواق داخل الويدجت (قيود ترخيص البورصة) — عندها استخدم «افتح في TradingView» أو شارت المحللين.</div>`;
  v.querySelectorAll("[data-mode]").forEach((b) => b.onclick = () => setMode(b.dataset.mode));
  v.querySelectorAll("[data-tf]").forEach((b) => b.onclick = () => { S.tf = b.dataset.tf; v.querySelectorAll("[data-tf]").forEach((x) => x.classList.toggle("on", x === b)); loadChart(); });
  $("#goAna").onclick = () => runAnalysis(false);
  let q;
  try { q = await api("/api/quote?symbol=" + encodeURIComponent(sym)); } catch (e) { $("#qcard").innerHTML = `<b class="dn">NOT FOUND</b> — ${esc(e.message)}`; return; }
  S.quote = q; renderQuote(q);
  tvWidget($("#tvTA"), "technical-analysis", { interval: "1D", width: "100%", isTransparent: true, height: "100%", symbol: q.tv_symbol, showIntervalTabs: true, displayMode: "single", locale: "ar_AE", colorTheme: "dark" });
  tvWidget($("#tvProf"), "symbol-profile", { width: "100%", height: "100%", colorTheme: "dark", isTransparent: true, symbol: q.tv_symbol, locale: "ar_AE" });
  tape(q.market);
  loadChart();
  const cached = null; // analysis is on demand
  S.timers.push(setInterval(refreshQuote, 30000));
}
function renderQuote(q) {
  const up = (q.change || 0) >= 0;
  $("#qcard").innerHTML = `<div class="qhead">
   <div><div class="muted small"><span class="dot ${q.is_open ? "on" : "off"}"></span>${q.is_open ? "السوق مفتوح — تحديث كل 30 ثانية" : "السوق مغلق — آخر سعر"} · ${esc(q.exchange_name || q.exchange || "")} · <span class="ltr">${esc(q.tv_symbol)}</span></div>
     <h2 style="margin:4px 0">${esc(q.name)} <span class="muted ltr small">${esc(q.symbol)}</span></h2>
     <div><span class="big ltr">${fmt(q.price, q.price < 10 ? 3 : 2)}</span> <span class="muted">${esc(q.currency || "")}</span> <b class="${up ? "up" : "dn"} ltr">${up ? "+" : ""}${fmt(q.change)} (${up ? "+" : ""}${fmt(q.change_pct)}%)</b></div>
     <div class="small muted">اليوم <span class="ltr">${fmt(q.day_low)} – ${fmt(q.day_high)}</span> · 52 أسبوعاً <span class="ltr">${fmt(q.low52)} – ${fmt(q.high52)}</span> · الحجم <span class="ltr">${q.volume ? Number(q.volume).toLocaleString("en-US") : "—"}</span> · ${q.market_time ? new Date(q.market_time * 1000).toLocaleString("ar-SA", { timeZone: "Asia/Riyadh", hour12: false }) + " (توقيت الرياض)" : ""}</div></div>
   <div class="btns"><a class="btn" target="_blank" rel="noopener" href="${tvLink(q.tv_symbol)}">↗ افتح في TradingView</a><button class="btn" id="pineBtn">📜 سكربت Pine</button></div></div>`;
  $("#pineBtn").onclick = showPine;
}
async function refreshQuote() {
  if (!S.symbol) return;
  try {
    const q = await api("/api/quote?symbol=" + encodeURIComponent(S.symbol));
    S.quote = q; renderQuote(q);
    if (q.is_open && S.chartMode === "own" && (S.tf === "1D" || S.tf === "1W")) loadChart(true);
  } catch (e) {}
}
function setMode(mode) {
  S.chartMode = mode;
  document.querySelectorAll("[data-mode]").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
  $("#chartBox").classList.toggle("hidden", mode !== "own"); $("#tfs").classList.toggle("hidden", mode !== "own");
  $("#tvBox").classList.toggle("hidden", mode !== "tv");
  $("#chartNote").textContent = mode === "own" ? "الشارت من Yahoo Finance مع مستويات لجنة المحللين." : "شارت TradingView الرسمي (ويدجت مجانية). مستويات اللجنة تظهر في شارت المحللين أو عبر سكربت Pine.";
  if (mode === "tv" && !$("#tvBox").dataset.loaded && S.quote) {
    tvWidget($("#tvBox"), "advanced-chart", { autosize: true, symbol: S.quote.tv_symbol, interval: "D", timezone: "Asia/Riyadh", theme: "dark", style: "1", locale: "ar_AE", allow_symbol_change: true, withdateranges: true, hide_side_toolbar: false, details: true, calendar: false, support_host: "https://www.tradingview.com" });
    $("#tvBox").dataset.loaded = "1";
  }
}
async function loadChart(soft) {
  const box = $("#chartBox"); if (!box) return;
  let d;
  try { d = await api(`/api/chart?symbol=${encodeURIComponent(S.symbol)}&tf=${S.tf}`); } catch (e) { box.innerHTML = `<div class="muted" style="padding:20px">NOT FOUND — ${esc(e.message)}</div>`; return; }
  if (!soft || !S.chart) {
    if (S.chart) { try { S.chart.remove(); } catch (e) {} }
    box.innerHTML = "";
    S.chart = LightweightCharts.createChart(box, { autoSize: true, layout: { background: { color: "#121826" }, textColor: "#c9d1d9", fontFamily: "IBM Plex Sans Arabic" },
      grid: { vertLines: { color: "#1c2436" }, horzLines: { color: "#1c2436" } }, rightPriceScale: { borderColor: "#243049" },
      timeScale: { borderColor: "#243049", timeVisible: d.intraday, secondsVisible: false }, crosshair: { mode: 0 } });
    S.series = S.chart.addCandlestickSeries({ upColor: "#22c55e", downColor: "#ef4444", borderVisible: false, wickUpColor: "#22c55e", wickDownColor: "#ef4444" });
    S.vol = S.chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "", color: "#2f81f744" });
    S.vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    S.lines = [];
  }
  S.chartData = d;
  S.series.setData(d.bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
  S.vol.setData(d.bars.map((b) => ({ time: b.time, value: b.volume, color: b.close >= b.open ? "#22c55e44" : "#ef444444" })));
  if (!soft) S.chart.timeScale().fitContent();
  drawLevels();
}
function drawLevels() {
  const a = S.analysis; if (!a || !S.series) return;
  (S.lines || []).forEach((l) => { try { S.series.removePriceLine(l); } catch (e) {} }); S.lines = [];
  const add = (price, color, title, style = 0, w = 1) => { if (price != null) S.lines.push(S.series.createPriceLine({ price, color, lineWidth: w, lineStyle: style, axisLabelVisible: true, title })); };
  add(a.entry_high, "#2f81f7", "دخول ↑", 2); add(a.entry_low, "#2f81f7", "دخول ↓", 2);
  add(a.stop, "#ef4444", "وقف", 0, 2); add(a.t1, "#22c55e", "T1", 2); add(a.t2, "#22c55e", "T2", 2); add(a.t3, "#22c55e", "T3", 0, 2);
  // candlestick pattern markers (dates parsed from the analysts' cited reasons)
  const d = S.chartData; if (!d || d.intraday) { S.series.setMarkers([]); return; }
  const tz = d.tz || "UTC"; const f = new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" });
  const byDate = {}; d.bars.forEach((b) => { byDate[f.format(new Date(b.time * 1000))] = b.time; });
  const marks = [];
  (a.patterns || []).forEach((p) => {
    const m = (p.reason || "").match(/(\d{4}-\d{2}-\d{2})/); if (!m) return;
    let t = byDate[m[1]]; if (t == null && S.tf === "5Y") { const keys = Object.keys(byDate).filter((k) => k <= m[1]).sort(); t = keys.length ? byDate[keys[keys.length - 1]] : null; }
    if (t == null) return;
    const bull = p.signal > 0;
    marks.push({ time: t, position: bull ? "belowBar" : "aboveBar", color: bull ? "#22c55e" : "#ef4444", shape: bull ? "arrowUp" : "arrowDown", text: (p.reason.split("،")[0] || p.name).slice(0, 24) });
  });
  marks.sort((x, y) => x.time - y.time); S.series.setMarkers(marks);
}
async function runAnalysis(force) {
  const btn = $("#goAna"); if (btn) { btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> المحللون يعملون…`; }
  try {
    const a = await api(`/api/analyze?symbol=${encodeURIComponent(S.symbol)}${force ? "&force=1" : ""}`);
    S.analysis = a; renderAnalysis(a); drawLevels(); chatCtx();
  } catch (e) { $("#ana").innerHTML = `<div class="card warn"><b>NOT FOUND</b> — ${esc(e.message)}</div>`; }
}
function renderAnalysis(a) {
  const cur = a.currency || "";
  const gb = a.groups.filter((g) => g.group !== "committee").map((g) => {
    const tot = g.bull + g.bear + g.neutral + g.nf || 1;
    return `<div class="gbar"><span>${esc(g.name_ar)}</span><span class="track"><i style="width:${g.bull / tot * 100}%;background:#22c55e"></i><i style="width:${g.neutral / tot * 100}%;background:#64748b"></i><i style="width:${g.bear / tot * 100}%;background:#ef4444"></i><i style="width:${g.nf / tot * 100}%;background:#243049"></i></span><span class="ltr small">${g.avg == null ? "NF" : (g.avg >= 0 ? "+" : "") + fmt(g.avg)}</span></div>`;
  }).join("");
  const pats = a.patterns.length ? a.patterns.map((p) => `<li><b class="${p.signal > 0 ? "up" : "dn"}">${esc(p.name)}</b> (إشارة ${fmt(p.signal)}، ثقة ${pct(p.confidence)}) — ${esc(p.reason)}</li>`).join("") : `<li class="muted">لا نمط شموع صالح على آخر 3 شموع مكتملة (NOT FOUND).</li>`;
  const agents = a.agents.map((x) => `<tr data-g="${esc(x.group)}"><td>${esc(x.name)}</td><td class="ltr ${x.signal > 0.15 ? "up" : x.signal < -0.15 ? "dn" : ""}">${x.found ? fmt(x.signal) : "NF"}</td><td>${x.found ? pct(x.confidence) : "—"}</td><td class="small">${esc(x.reason)}<div class="muted small">المصدر: ${esc(x.source)}</div></td></tr>`).join("");
  $("#ana").innerHTML = `<div class="card">
   <div class="row" style="flex-wrap:wrap"><div class="verdict"><span class="vbig ${a.verdict_en === "BUY" ? "up" : a.verdict_en === "SELL" ? "dn" : ""}" style="${a.verdict_en === "HOLD" ? "color:var(--hold)" : ""}">${esc(a.verdict_ar)}</span>
     <div><div>ثقة <b>${pct(a.confidence)}</b> · درجة موزونة <b class="ltr">${a.score >= 0 ? "+" : ""}${fmt(a.score)}</b> (العتبة ±0.25)</div><div class="small muted">صوّت ${a.n_found} من ${a.n_total} · إغلاق ${esc(a.last_bar_date)} · ${esc(a.generated_at)} توقيت الرياض${a.cached ? " · من الذاكرة المؤقتة" : ""}</div></div></div>
     <div class="btns"><button class="btn" onclick="runAnalysis(true)">↻ أعد التحليل</button><button class="btn" onclick="showPine()">📜 Pine</button></div></div>
   <div class="lv" style="margin-top:12px"><div><span class="muted small">السعر</span><b>${fmt(a.price)}</b></div><div><span class="muted small">منطقة الدخول</span><b>${fmt(a.entry_low)}–${fmt(a.entry_high)}</b></div><div><span class="muted small">وقف الخسارة</span><b class="dn">${fmt(a.stop)}</b></div><div><span class="muted small">الهدف 1</span><b class="up">${fmt(a.t1)}</b></div><div><span class="muted small">الهدف 2</span><b class="up">${fmt(a.t2)}</b></div><div><span class="muted small">الهدف 3</span><b class="up">${fmt(a.t3)}</b></div></div>
   <div class="note" style="margin-top:6px">⚖️ ${esc(a.committee)} ${cur ? "· العملة " + esc(cur) : ""}</div></div>
  <div class="two" style="margin-top:12px">
   <div class="card"><h3>المجموعات <span class="muted small">(🟩 صاعد ⬜ محايد 🟥 هابط ⬛ NOT FOUND)</span></h3>${gb}</div>
   <div class="card"><h3>🕯️ أنماط الشموع النشطة</h3><ul class="clean">${pats}</ul></div></div>
  <div class="two" style="margin-top:12px">
   <div class="card"><h3 class="up">🐂 الثور — أبرز الأسباب</h3><p class="small">${esc(a.bull)}</p><ul class="clean">${a.top_reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>
   <div class="card"><h3 class="dn">🐻 الدب — المخاطر</h3><p class="small">${esc(a.bear)}</p><ul class="clean">${a.key_risks.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div></div>
  <div class="card" style="margin-top:12px"><details><summary>كل المحللين (${a.agents.length}) مع السبب والمصدر</summary><div class="tbl"><table><tr><th>المحلل</th><th>الإشارة</th><th>الثقة</th><th>السبب والمصدر</th></tr>${agents}</table></div></details>
   <details><summary>NOT FOUND — استُبعدوا من التصويت (${a.not_found.length})</summary><ul class="clean small">${a.not_found.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></details>
   <details><summary>قيود البيانات والمصادر</summary><ul class="clean small">${a.notes.map((x) => `<li>${esc(x)}</li>`).join("")}</ul><div class="small muted">${esc(a.source_note)}</div><div class="small muted">${esc(a.engine)}</div></details></div>`;
}
async function showPine() {
  if (!S.symbol) return;
  openModal("سكربت Pine v5 — الصقه في محرر Pine في TradingView", `<span class="spinner"></span> يُحضَّر من نتيجة اللجنة…`);
  try {
    const code = await api("/api/pine?symbol=" + encodeURIComponent(S.symbol));
    if (!S.analysis) { try { S.analysis = await api("/api/analyze?symbol=" + encodeURIComponent(S.symbol)); renderAnalysis(S.analysis); drawLevels(); } catch (e) {} }
    $("#modalBody").innerHTML = `<p class="small muted">في TradingView: افتح «Pine Editor» أسفل الشارت ← الصق ← «Add to chart». يرسم منطقة الدخول والوقف والأهداف وملصق الحكم، ويحذّرك إن فتحته على رمز مختلف.</p><textarea class="code" id="pineCode" readonly>${esc(code)}</textarea><div class="btns" style="margin-top:8px"><button class="btn pri" id="copyPine">نسخ</button><a class="btn" target="_blank" rel="noopener" href="${tvLink(S.quote ? S.quote.tv_symbol : S.symbol)}">↗ افتح الرمز في TradingView</a></div>`;
    $("#copyPine").onclick = async () => { const t = $("#pineCode"); t.select(); try { await navigator.clipboard.writeText(t.value); } catch (e) { document.execCommand("copy"); } $("#copyPine").textContent = "✓ نُسخ"; };
  } catch (e) { $("#modalBody").innerHTML = `<b class="dn">${esc(e.message)}</b>`; }
}
function openModal(t, body) { $("#modalTitle").textContent = t; $("#modalBody").innerHTML = body; $("#modal").classList.remove("hidden"); }
$("#modalClose").onclick = () => $("#modal").classList.add("hidden");
$("#modal").onclick = (e) => { if (e.target.id === "modal") $("#modal").classList.add("hidden"); };

/* ---------- TradingView help ---------- */
async function tvHelp() {
  S.symbol = null; chatCtx(); tape(S.market);
  const h = await api("/api/tvhelp");
  $("#view").innerHTML = `<h2>ربط TradingView</h2>
  <div class="card"><h3>1) الشارت والويدجت</h3><p class="small">كل صفحة سهم فيها شارت TradingView الرسمي (زر «شارت TradingView»)، والملخص الفني ونبذة الشركة من TradingView، وزر «افتح في TradingView» يفتح الرمز مباشرة. الرموز تُحوَّل تلقائياً: <span class="ltr">2222.SR → TADAWUL:2222</span>، <span class="ltr">AAPL → NASDAQ:AAPL</span>، <span class="ltr">EMAAR.AE → DFM:EMAAR</span>، <span class="ltr">0700.HK → HKEX:700</span>.</p></div>
  <div class="card" style="margin-top:12px"><h3>2) سكربت Pine</h3><p class="small">بعد تحليل أي سهم اضغط «📜 سكربت Pine» ← انسخ ← في TradingView افتح Pine Editor ← الصق ← Add to chart. يرسم منطقة الدخول والوقف والأهداف وحكم اللجنة، ويضيف شروط تنبيه (كسر الوقف، بلوغ الهدف، الدخول للمنطقة).</p></div>
  <div class="card" style="margin-top:12px"><h3>3) تنبيهات TradingView ← المنصة (Webhook)</h3>
   <p class="small warn card">⚠️ ميزة Webhook في تنبيهات TradingView تتطلب اشتراكاً مدفوعاً في TradingView، وتعمل على رابط https فقط. رابط المنصة الحالي مؤقت ويتغير إذا أُعيد تشغيل النفق — حدّث التنبيه عندها.</p>
   <ol class="small" style="line-height:2">
    <li>في TradingView أنشئ تنبيهاً (Alert) على السعر أو على سكربت Pine.</li>
    <li>في تبويب Notifications فعّل <b>Webhook URL</b> والصق هذا الرابط (سري — فيه مفتاحك):</li></ol>
   <pre class="code" id="wh">${esc(h.webhook_url)}</pre><button class="btn" onclick="navigator.clipboard.writeText($('#wh').textContent);this.textContent='✓ نُسخ'">نسخ الرابط</button>
   <ol class="small" start="3" style="line-height:2"><li>في خانة Message الصق هذا القالب حرفياً (TradingView يعوّض المتغيرات بين الأقواس):</li></ol>
   <pre class="code" id="tpl">${esc(h.template_simple)}</pre><button class="btn" onclick="navigator.clipboard.writeText($('#tpl').textContent);this.textContent='✓ نُسخ'">نسخ القالب</button>
   <p class="small">لتنبيهات الاستراتيجيات (Strategy) يمكن استخدام: <span class="ltr small">${esc(h.template)}</span></p>
   <p class="small">عند وصول التنبيه: تشغّل المنصة لجنة المحللين على الرمز، وتعرض النتيجة في «تنبيهات TradingView» بالصفحة الرئيسية، وتسجّل إشارة الشراء (إن وُجدت) كصفقة ورقية${S.cfg.forward_available ? "، وترسل ملخصاً لتداول في Grok Bot" : ""}.</p></div>`;
}

/* ---------- chat ---------- */
const CH = ["وش التوصية؟", "الدخول والوقف والأهداف", "أنماط الشموع", "المخاطر", "ليش؟", "الثور والدب", "السعر الآن"];
function chatCtx() { $("#chatCtx").textContent = S.symbol ? "· " + S.symbol : "· افتح سهماً"; }
function addMsg(t, who) { const d = document.createElement("div"); d.className = "msg " + who; d.textContent = t.replace(/\*\*/g, ""); $("#chatLog").appendChild(d); $("#chatLog").scrollTop = 1e9; return d; }
$("#chatBtn").onclick = () => { $("#chat").classList.remove("hidden"); $("#chatBtn").classList.add("hidden"); if (!$("#chatLog").children.length) addMsg("هلا! أنا بوت تداول. افتح أي سهم واسألني عن التوصية والمستويات والشموع والمخاطر. أجاوبك من نتائج لجنة المحللين مع المصادر.", "bot"); $("#chatIn").focus(); };
$("#chatClose").onclick = () => { $("#chat").classList.add("hidden"); $("#chatBtn").classList.remove("hidden"); };
$("#chatChips").innerHTML = CH.map((c) => `<button type="button">${c}</button>`).join("");
$("#chatChips").querySelectorAll("button").forEach((b) => b.onclick = () => sendChat(b.textContent));
$("#chatForm").onsubmit = (e) => { e.preventDefault(); const v = $("#chatIn").value.trim(); if (v) sendChat(v); $("#chatIn").value = ""; };
async function sendChat(text) {
  addMsg(text, "me"); const w = addMsg("…", "bot");
  if (S.symbol && !S.analysis) w.textContent = "⏳ أشغّل لجنة المحللين على " + S.symbol + " (قد يستغرق دقيقة)…";
  try {
    const r = await api("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: text, symbol: S.symbol, forward: $("#fwd").checked }) });
    w.textContent = r.reply.replace(/\*\*/g, "") + (r.forwarded ? `\n\n↗ Grok Bot: ${r.forwarded}` : "");
    if (S.symbol && !S.analysis && $("#ana")) { try { S.analysis = await api("/api/analyze?symbol=" + encodeURIComponent(S.symbol)); renderAnalysis(S.analysis); drawLevels(); } catch (e) {} }
  } catch (e) { w.textContent = "خطأ: " + e.message; }
}

/* ---------- boot ---------- */
(async () => {
  S.cfg = await api("/api/config");
  $("#nAgents").textContent = S.cfg.n_agents + " محللاً";
  if (S.cfg.forward_available) $("#fwdWrap").classList.remove("hidden");
  route();
})();
