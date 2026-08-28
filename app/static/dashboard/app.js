// Vanilla JS dashboard -- every number on this page comes from a real JSON
// API response. No mock data, no client-side fabrication: an endpoint that
// 404s or reports "unavailable" renders that fact, not a placeholder.

function el(tag, attrs = {}, children = []) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "style") e.setAttribute("style", v);
    else e.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    e.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(c) : c);
  }
  return e;
}

async function fetchJSON(path, opts) {
  const res = await fetch(path, opts);
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error((body && body.detail) || res.statusText);
    err.status = res.status;
    throw err;
  }
  return body;
}

// A handful of state-mutating/LLM-cost endpoints (portfolio positions,
// alert rules, research note generation) require the same X-Admin-Key
// this deployment already uses for /api/admin/* -- prompted once and
// cached in localStorage rather than baked into the page, since this is
// a static file served to anyone who loads the dashboard URL.
function getAdminKey() {
  let key = localStorage.getItem("admin_key");
  if (!key) {
    key = window.prompt(
      "This action requires the admin key configured on the server (ADMIN_API_KEY)."
    );
    if (key) localStorage.setItem("admin_key", key);
  }
  return key;
}

async function fetchJSONWithAdminKey(path, opts = {}) {
  const key = getAdminKey();
  const headers = { ...(opts.headers || {}), "X-Admin-Key": key || "" };
  try {
    return await fetchJSON(path, { ...opts, headers });
  } catch (err) {
    if (err.status === 401) {
      localStorage.removeItem("admin_key");
      alert("Invalid or missing admin key -- please try again.");
    }
    throw err;
  }
}

function changeClass(v) {
  if (v == null) return "neutral";
  return v > 0 ? "up" : v < 0 ? "down" : "neutral";
}

function fmtPct(v, digits = 2) {
  if (v == null) return "n/a";
  const n = Number(v);
  return (n > 0 ? "+" : "") + n.toFixed(digits) + "%";
}

function fmtNum(v, digits = 2) {
  if (v == null) return "n/a";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
}

// `ci` is a compute_wilson_interval()-shaped {lower_pct, upper_pct, sample_count}
// dict, or null when there's nothing to bound. Renders "" (not "n/a") when
// absent so callers can append it directly after a point-estimate string.
function fmtCI(ci) {
  if (ci == null) return "";
  return ` (95% CI: ${ci.lower_pct}-${ci.upper_pct})`;
}

function card(label, value, sub, cls, id) {
  return el("div", { class: "card" }, [
    el("div", { class: "label" }, label),
    el("div", { class: `value ${cls || ""}`, ...(id ? { id } : {}) }, String(value)),
    sub ? el("div", { class: "sub" }, sub) : null,
  ]);
}

function scoreBar(label, value) {
  const v = value == null ? 0 : Math.max(0, Math.min(100, value));
  return el("div", { class: "card" }, [
    el("div", { class: "label" }, label),
    el("div", { class: "value" }, String(value ?? "n/a")),
    el("div", { class: "bar-track" }, [el("div", { class: "bar-fill", style: `width:${v}%` })]),
  ]);
}

function quoteGrid(quotes) {
  const grid = el("div", { class: "grid" });
  for (const q of quotes) {
    const c = card(q.symbol, fmtNum(q.price), fmtPct(q.change_pct_24h), changeClass(q.change_pct_24h));
    c.classList.add("card-clickable");
    c.addEventListener("click", () => navigate("assetdetail", new URLSearchParams({ symbol: q.symbol })));
    grid.appendChild(c);
  }
  return grid;
}

function pill(available) {
  return el("span", { class: `pill ${available ? "available" : "unavailable"}` }, available ? "available" : "unavailable");
}

function errorBox(err) {
  return el("p", { class: "error" }, `Error: ${err.message}`);
}

// Wrapped in a scrollable container (not a bare <table>) so a wide table
// scrolls horizontally instead of overflowing the page on a narrow/mobile
// viewport -- every call site just appends/returns this as one node, so
// the wrapper is transparent to callers.
function table(headers, rows) {
  const t = el("table");
  t.appendChild(el("tr", {}, headers.map((h) => el("th", {}, h))));
  for (const row of rows) t.appendChild(el("tr", {}, row.map((c) => el("td", {}, c))));
  return el("div", { class: "table-wrap" }, [t]);
}

// ---- Live Dashboard Upgrade: realtime price components -------------------
// All read from the single shared RealtimeStore (realtime.js) -- never a
// per-component EventSource/WebSocket connection.

function fmtAge(ageSeconds) {
  if (ageSeconds == null) return "";
  if (ageSeconds < 60) return `${Math.round(ageSeconds)}s`;
  return `${Math.round(ageSeconds / 60)}m`;
}

// Sibling to fmtAge() above rather than an extension of it: fmtAge is
// tuned for realtime-price-tick ages (sub-minute/minute scale, and every
// existing call site relies on that), while an official daily forecast's
// age spans up to ~24h+ and reads much better as "Xh Ym" than "1439m".
function fmtAgeLong(ageSeconds) {
  if (ageSeconds == null) return "n/a";
  const s = Math.max(0, Math.round(ageSeconds));
  if (s < 60) return `${s}s`;
  const minutes = Math.round(s / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  return `${hours}h ${remMinutes}m`;
}

function dataFreshnessBadge(freshness, ageSeconds) {
  if (!freshness) return el("span", { class: "freshness-badge freshness-unknown" }, "...");
  const label = freshness.toUpperCase();
  const text = freshness === "offline" ? "OFFLINE" : `${label} · ${fmtAge(ageSeconds)}`;
  return el("span", { class: `freshness-badge freshness-${freshness}` }, text);
}

function tickerItem(symbol, fallbackQuote) {
  const entry = RealtimeStore.get(symbol);
  const price = entry ? entry.price : fallbackQuote ? fallbackQuote.price : null;
  const changePct = entry ? entry.changePercent24h : fallbackQuote ? fallbackQuote.change_pct_24h : null;
  // /api/market already computes real freshness/age_seconds per quote
  // (from the batch's actual collected_at) -- reuse it rather than
  // guessing a label before the first realtime tick arrives.
  const badge = entry
    ? dataFreshnessBadge(entry.freshness, entry.ageSeconds)
    : fallbackQuote
      ? dataFreshnessBadge(fallbackQuote.freshness, fallbackQuote.age_seconds)
      : dataFreshnessBadge(null, null);
  const item = el("div", { class: "ticker-item card-clickable", "data-symbol": symbol }, [
    el("div", { class: "ticker-symbol" }, symbol),
    el("div", { class: "ticker-price" }, price != null ? fmtNum(price) : "n/a"),
    el("div", { class: `ticker-change ${changeClass(changePct)}` }, fmtPct(changePct)),
    badge,
  ]);
  item.addEventListener("click", () => navigate("assetdetail", new URLSearchParams({ symbol })));
  return item;
}

// `fallbackQuotes` is the already-fetched /api/market snapshot for this
// cycle -- used only to paint an honest, real price before the first
// realtime tick has arrived for a symbol, never a fabricated value.
function liveTicker(symbols, fallbackQuotes) {
  const bySymbol = new Map((fallbackQuotes || []).map((q) => [q.symbol, q]));
  const wrap = el(
    "div",
    { class: "ticker", id: "live-ticker" },
    symbols.map((s) => tickerItem(s, bySymbol.get(s)))
  );
  RealtimeStore.mount({
    onTick: (dirtySymbols) => {
      for (const symbol of dirtySymbols) updateTickerCell(symbol);
    },
    onStatus: updateConnectionIndicator,
  });
  return wrap;
}

// Patches only the one changed symbol's DOM node -- a BTC tick never
// touches ETH's card or re-renders the rest of Overview.
function updateTickerCell(symbol) {
  const container = document.getElementById("live-ticker");
  if (!container) return;
  const node = container.querySelector(`[data-symbol="${symbol}"]`);
  if (!node) return;
  const entry = RealtimeStore.get(symbol);
  if (!entry) return;

  const priceEl = node.querySelector(".ticker-price");
  const changeEl = node.querySelector(".ticker-change");
  const badgeEl = node.querySelector(".freshness-badge");

  const prevPrice = Number(priceEl.dataset.rawPrice || entry.previousPrice);
  priceEl.textContent = fmtNum(entry.price);
  priceEl.dataset.rawPrice = String(entry.price);
  changeEl.textContent = fmtPct(entry.changePercent24h);
  changeEl.className = `ticker-change ${changeClass(entry.changePercent24h)}`;
  if (badgeEl) badgeEl.replaceWith(dataFreshnessBadge(entry.freshness, entry.ageSeconds));

  if (Number.isFinite(prevPrice) && entry.price !== prevPrice) {
    const flashClass = entry.price > prevPrice ? "flash-up" : "flash-down";
    priceEl.classList.remove("flash-up", "flash-down");
    void priceEl.offsetWidth; // restart the CSS animation on repeated ticks
    priceEl.classList.add(flashClass);
  }
}

// Forecast Center's "Current Price"/"Expected Change" must never go stale
// while the live price keeps moving (the target price is a fixed $ figure
// computed once server-side; only "how far away is it from here" changes).
// Patches the two DOM nodes in place -- never refetches the forecast
// itself just because the price ticked, and never recomputes anything
// beyond simple arithmetic against the server's own target_price.
let forecastLiveUnsubscribe = null;

function updateForecastLivePrice(payload) {
  const entry = RealtimeStore.get(payload.symbol);
  if (!entry || entry.price == null) return;

  const priceNode = document.getElementById("forecast-current-price");
  if (priceNode) {
    priceNode.textContent = fmtNum(entry.price);
    const badgeHost = priceNode.parentElement;
    const oldBadge = badgeHost ? badgeHost.querySelector(".freshness-badge") : null;
    if (oldBadge) oldBadge.replaceWith(dataFreshnessBadge(entry.freshness, entry.ageSeconds));
  }

  if (payload.target_price != null && entry.price !== 0) {
    const upsidePct = ((payload.target_price - entry.price) / entry.price) * 100;
    const changeNode = document.getElementById("forecast-expected-change");
    if (changeNode) {
      changeNode.textContent = fmtPct(upsidePct);
      changeNode.className = `value ${changeClass(upsidePct)}`;
    }
  }
}

function mountForecastLivePrice(payload) {
  if (forecastLiveUnsubscribe) {
    forecastLiveUnsubscribe();
    forecastLiveUnsubscribe = null;
  }
  forecastLiveUnsubscribe = RealtimeStore.subscribe((dirtySymbols) => {
    if (dirtySymbols.has(payload.symbol)) updateForecastLivePrice(payload);
  });
  updateForecastLivePrice(payload);
}

const _CONNECTION_STATUS_LABELS = {
  connected: "LIVE",
  connecting: "CONNECTING",
  reconnecting: "RECONNECTING",
  offline: "OFFLINE",
};

function updateConnectionIndicator(status, latencyMs) {
  const node = document.getElementById("connection-indicator");
  if (!node) return;
  const label = _CONNECTION_STATUS_LABELS[status] || status.toUpperCase();
  const suffix = status === "connected" && latencyMs != null ? ` ${(latencyMs / 1000).toFixed(1)}s` : "";
  node.textContent = `● ${label}${suffix}`;
  node.className = `connection-indicator status-${status}`;
}

// v10.0 "Smart Navigation" -- one pointer per screen to the related
// intelligence a trader would naturally check next. Mirrors
// app/services/common/navigation.py's NAV_POINTERS wording; purely a link
// to an already-existing page, no new endpoint.
const NAV_POINTERS = {
  replay: { label: "See current Committee opinion", page: "committee" },
  committee: { label: "Compare with historical Replay", page: "replay" },
  consensus: { label: "See Committee's structured verdict", page: "committee" },
  scanner: { label: "View latest Watchdog events", page: "watchdog" },
  watchdog: { label: "Open historical comparison", page: "replay" },
};

function navPointer(screen) {
  const p = NAV_POINTERS[screen];
  if (!p) return null;
  return el("p", { class: "sub nav-pointer" }, ["Related: ", el("a", { href: `#${p.page}` }, p.label)]);
}

// v12.0 P1 -- dashboard counterpart of app.services.common.ai_insight's
// format_ai_insight_lines(): renders whichever fields of a build_ai_insight()
// dict are populated, in the same spec order, under the same labels Telegram
// already uses. Returns [] (no section) when nothing is populated.
const AI_INSIGHT_FIELD_LABELS = [
  ["current_status", "Current Status"],
  ["ai_conclusion", "AI Conclusion"],
  ["why", "Why"],
  ["committee_opinion", "Committee Opinion"],
  ["consensus", "Consensus"],
  ["historical_similarity", "Historical Similarity"],
  ["main_opportunity", "Main Opportunity"],
  ["main_risk", "Main Risk"],
  ["expected_scenario", "Expected Scenario"],
  ["what_to_watch_next", "What To Watch Next"],
];

function renderAiInsight(insight) {
  if (!insight) return [];
  const hasContent =
    AI_INSIGHT_FIELD_LABELS.some(([key]) => insight[key]) ||
    (insight.supporting_evidence && insight.supporting_evidence.length) ||
    insight.confidence != null;
  if (!hasContent) return [];
  const nodes = [el("h2", {}, "AI Insight")];
  for (const [key, label] of AI_INSIGHT_FIELD_LABELS) {
    if (insight[key]) nodes.push(el("p", {}, [el("strong", {}, `${label}: `), insight[key]]));
  }
  if (insight.supporting_evidence && insight.supporting_evidence.length) {
    nodes.push(el("p", {}, el("strong", {}, "Supporting Evidence:")));
    nodes.push(el("ul", {}, insight.supporting_evidence.map((e) => el("li", {}, e))));
  }
  if (insight.confidence != null) {
    nodes.push(el("p", {}, [el("strong", {}, "Confidence: "), `${insight.confidence}%`]));
  }
  return nodes;
}

const SVG_NS = "http://www.w3.org/2000/svg";

function svgLineChart(values, { width = 600, height = 160 } = {}) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("class", "chart");
  const nums = values.filter((v) => v != null);
  if (!nums.length) return svg;
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const range = max - min || 1;
  const stepX = values.length > 1 ? width / (values.length - 1) : 0;
  const points = values
    .map((v, i) =>
      v == null ? null : `${(i * stepX).toFixed(1)},${(height - ((v - min) / range) * height).toFixed(1)}`
    )
    .filter(Boolean)
    .join(" ");
  const polyline = document.createElementNS(SVG_NS, "polyline");
  polyline.setAttribute("points", points);
  svg.appendChild(polyline);
  return svg;
}

const CANDLE_CHART_GEOM = { w: 900, h: 440, padL: 6, padR: 64, padT: 10, priceH: 300, gap: 12, indH: 84 };
let _candleClipCounter = 0;

function _candleGeom() {
  const g = CANDLE_CHART_GEOM;
  const plotW = g.w - g.padL - g.padR;
  const priceTop = g.padT;
  const priceBot = priceTop + g.priceH;
  const indTop = priceBot + g.gap;
  const indBot = indTop + g.indH;
  return { ...g, plotW, priceTop, priceBot, indTop, indBot };
}

function fmtChartAxisTime(iso, timeframe) {
  const d = new Date(iso);
  const p2 = (x) => String(x).padStart(2, "0");
  if (timeframe === "1d" || timeframe === "4d") return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
  if (timeframe === "4h" || timeframe === "1h") return `${p2(d.getUTCDate())} ${p2(d.getUTCHours())}:00`;
  return `${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`;
}

// Binance/TradingView-style candlestick chart with SMA overlays and an RSI
// sub-panel -- raw SVG DOM construction like svgLineChart/svgRadarChart
// above, no charting library (this dashboard has no build step). `candles`
// is /api/history's `candles` array (oldest first). CoinGecko's price-
// history endpoint returns one price point per period, not true OHLC (see
// app/services/history/providers/coingecko.py's own docstring) -- so 1d/1h
// candles from that source are flat (open=high=low=close). Rather than draw
// fake wicks, this detects that case and falls back to a close-price line +
// SMA overlays + RSI, with a visible caption naming the reason: an honest
// degrade, never a fabricated candle body.
function candleChart(candles, { timeframe = "1d", indicatorKind = "rsi" } = {}) {
  const geom = _candleGeom();
  const wrap = el("div", { class: "candle-chart-wrap" });

  if (!candles || !candles.length) {
    wrap.appendChild(el("p", { class: "sub" }, "No chart data available."));
    return wrap;
  }

  const isFlat = candles.every((c) => c.high === c.low);
  if (isFlat) {
    wrap.appendChild(
      el(
        "p",
        { class: "sub" },
        "CoinGecko's price-history endpoint returns one price point per period -- no true OHLC for this timeframe, showing close-price line instead."
      )
    );
  }

  let lo = Infinity;
  let hi = -Infinity;
  for (const c of candles) {
    if (c.low != null) lo = Math.min(lo, c.low);
    if (c.high != null) hi = Math.max(hi, c.high);
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) {
    wrap.appendChild(el("p", { class: "sub" }, "No chart data available."));
    return wrap;
  }
  const padV = (hi - lo) * 0.06 || Math.abs(hi) * 0.01 || 1;
  lo -= padV;
  hi += padV;
  const span = hi - lo || 1;
  const yPrice = (v) => geom.priceBot - ((v - lo) / span) * geom.priceH;

  const n = candles.length;
  const slot = geom.plotW / n;
  const bodyW = Math.max(1, slot * 0.62);
  const cx = (i) => geom.padL + slot * i + slot / 2;
  const bodyX = (i) => cx(i) - bodyW / 2;

  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${geom.w} ${geom.h}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  svg.setAttribute("class", "candle-chart");

  // Price gridlines + axis labels
  const gGrid = document.createElementNS(SVG_NS, "g");
  const TICKS = 4;
  for (let t = 0; t <= TICKS; t++) {
    const v = lo + (span * t) / TICKS;
    const y = yPrice(v);
    const line = document.createElementNS(SVG_NS, "line");
    line.setAttribute("x1", geom.padL);
    line.setAttribute("x2", geom.w - geom.padR);
    line.setAttribute("y1", y.toFixed(2));
    line.setAttribute("y2", y.toFixed(2));
    line.setAttribute("class", "chart-grid");
    gGrid.appendChild(line);
    const label = document.createElementNS(SVG_NS, "text");
    label.setAttribute("x", geom.w - geom.padR + 6);
    label.setAttribute("y", y.toFixed(2));
    label.setAttribute("class", "chart-axis-label");
    label.setAttribute("dominant-baseline", "middle");
    label.textContent = fmtNum(v);
    gGrid.appendChild(label);
  }
  svg.appendChild(gGrid);

  // Candle bodies + wicks (or a close-price line for the flat/degenerate case)
  const gCandles = document.createElementNS(SVG_NS, "g");
  if (isFlat) {
    const points = candles.map((c, i) => `${cx(i).toFixed(2)},${yPrice(c.close).toFixed(2)}`).join(" ");
    const line = document.createElementNS(SVG_NS, "polyline");
    line.setAttribute("points", points);
    line.setAttribute("class", "candle-close-line");
    gCandles.appendChild(line);
  } else {
    for (let i = 0; i < n; i++) {
      const c = candles[i];
      const cls = c.close >= c.open ? "candle-up" : "candle-down";
      const wick = document.createElementNS(SVG_NS, "line");
      wick.setAttribute("x1", cx(i).toFixed(2));
      wick.setAttribute("x2", cx(i).toFixed(2));
      wick.setAttribute("y1", yPrice(c.high).toFixed(2));
      wick.setAttribute("y2", yPrice(c.low).toFixed(2));
      wick.setAttribute("class", `candle-wick ${cls}`);
      gCandles.appendChild(wick);

      const yTop = yPrice(Math.max(c.open, c.close));
      const yBot = yPrice(Math.min(c.open, c.close));
      const rect = document.createElementNS(SVG_NS, "rect");
      rect.setAttribute("x", bodyX(i).toFixed(2));
      rect.setAttribute("y", yTop.toFixed(2));
      rect.setAttribute("width", bodyW.toFixed(2));
      rect.setAttribute("height", Math.max(1, yBot - yTop).toFixed(2));
      rect.setAttribute("class", `candle-body ${cls}`);
      gCandles.appendChild(rect);
    }
  }
  svg.appendChild(gCandles);

  // SMA overlays, clipped to the price panel so an out-of-range SMA-200
  // doesn't distort the y-scale for the candles themselves.
  const clipId = `candle-clip-${_candleClipCounter++}`;
  const defs = document.createElementNS(SVG_NS, "defs");
  const clipPath = document.createElementNS(SVG_NS, "clipPath");
  clipPath.setAttribute("id", clipId);
  const clipRect = document.createElementNS(SVG_NS, "rect");
  clipRect.setAttribute("x", geom.padL);
  clipRect.setAttribute("y", geom.priceTop);
  clipRect.setAttribute("width", geom.plotW);
  clipRect.setAttribute("height", geom.priceH);
  clipPath.appendChild(clipRect);
  defs.appendChild(clipPath);
  svg.appendChild(defs);

  const gOverlays = document.createElementNS(SVG_NS, "g");
  gOverlays.setAttribute("clip-path", `url(#${clipId})`);
  function smaPolyline(key, cssClass) {
    const pts = [];
    candles.forEach((c, i) => {
      const v = c[key];
      if (v == null) return;
      pts.push(`${cx(i).toFixed(2)},${yPrice(v).toFixed(2)}`);
    });
    if (pts.length < 2) return null;
    const p = document.createElementNS(SVG_NS, "polyline");
    p.setAttribute("points", pts.join(" "));
    p.setAttribute("class", `sma-line ${cssClass}`);
    return p;
  }
  for (const [key, cls] of [
    ["sma_20", "sma-line-20"],
    ["sma_50", "sma-line-50"],
    ["sma_200", "sma-line-200"],
  ]) {
    const line = smaPolyline(key, cls);
    if (line) gOverlays.appendChild(line);
  }
  svg.appendChild(gOverlays);

  // Last-price marker
  const last = candles[n - 1];
  if (last && last.close != null) {
    const y = yPrice(last.close);
    const lastCls = last.close >= last.open ? "candle-up" : "candle-down";
    const lastLine = document.createElementNS(SVG_NS, "line");
    lastLine.setAttribute("x1", geom.padL);
    lastLine.setAttribute("x2", geom.w - geom.padR);
    lastLine.setAttribute("y1", y.toFixed(2));
    lastLine.setAttribute("y2", y.toFixed(2));
    lastLine.setAttribute("class", `last-price-line ${lastCls}`);
    svg.appendChild(lastLine);
    const chip = document.createElementNS(SVG_NS, "text");
    chip.setAttribute("x", geom.w - geom.padR + 6);
    chip.setAttribute("y", y.toFixed(2));
    chip.setAttribute("class", `last-price-chip ${lastCls}`);
    chip.setAttribute("dominant-baseline", "middle");
    chip.textContent = fmtNum(last.close);
    svg.appendChild(chip);
  }

  // Time axis
  const gTime = document.createElementNS(SVG_NS, "g");
  const timeTicks = Math.min(6, n);
  for (let t = 0; t < timeTicks; t++) {
    const i = Math.round((t * (n - 1)) / Math.max(1, timeTicks - 1));
    const label = document.createElementNS(SVG_NS, "text");
    label.setAttribute("x", cx(i).toFixed(2));
    label.setAttribute("y", geom.indBot + 18);
    label.setAttribute("class", "chart-axis-label");
    label.setAttribute("text-anchor", "middle");
    label.textContent = fmtChartAxisTime(candles[i].timestamp, timeframe);
    gTime.appendChild(label);
  }
  svg.appendChild(gTime);

  const indicatorG = indicatorPanelGroup(candles, geom, cx, indicatorKind);
  if (indicatorG) svg.appendChild(indicatorG);

  attachCrosshair(svg, geom, candles, cx, yPrice, indicatorKind);

  wrap.appendChild(svg);
  return wrap;
}

// RSI sub-panel: fixed 0-100 domain (unlike price, needs no per-symbol
// scaling), 70/30 overbought/oversold bands + a 50 midline. Chosen over
// MACD for this first indicator panel -- MACD's magnitude varies by orders
// of magnitude between symbols and needs its own normalization, while RSI's
// Wilder-14 warm-up (14 bars) lights up ~2.5x sooner than MACD's 12/26/9
// warm-up (~34 bars), which matters once 5m candles start from zero
// history. `has_rsi` is checked per-call since older/short series may not
// have any yet -- the panel is simply omitted rather than drawn empty.
function rsiPanelGroup(candles, geom, cx) {
  if (!candles.some((c) => c.rsi != null)) return null;
  const g = document.createElementNS(SVG_NS, "g");
  const yRsi = (v) => geom.indBot - (v / 100) * geom.indH;

  const zone = document.createElementNS(SVG_NS, "rect");
  zone.setAttribute("x", geom.padL);
  zone.setAttribute("y", yRsi(70).toFixed(2));
  zone.setAttribute("width", geom.plotW);
  zone.setAttribute("height", (yRsi(30) - yRsi(70)).toFixed(2));
  zone.setAttribute("class", "rsi-zone");
  g.appendChild(zone);

  for (const [level, cls] of [
    [70, "rsi-band"],
    [30, "rsi-band"],
    [50, "rsi-mid"],
  ]) {
    const line = document.createElementNS(SVG_NS, "line");
    line.setAttribute("x1", geom.padL);
    line.setAttribute("x2", geom.w - geom.padR);
    line.setAttribute("y1", yRsi(level).toFixed(2));
    line.setAttribute("y2", yRsi(level).toFixed(2));
    line.setAttribute("class", cls);
    g.appendChild(line);
    const label = document.createElementNS(SVG_NS, "text");
    label.setAttribute("x", geom.w - geom.padR + 6);
    label.setAttribute("y", yRsi(level).toFixed(2));
    label.setAttribute("class", "chart-axis-label");
    label.setAttribute("dominant-baseline", "middle");
    label.textContent = String(level);
    g.appendChild(label);
  }

  const pts = [];
  candles.forEach((c, i) => {
    if (c.rsi == null) return;
    pts.push(`${cx(i).toFixed(2)},${yRsi(c.rsi).toFixed(2)}`);
  });
  if (pts.length >= 2) {
    const line = document.createElementNS(SVG_NS, "polyline");
    line.setAttribute("points", pts.join(" "));
    line.setAttribute("class", "rsi-line");
    g.appendChild(line);
  }

  return g;
}

// MACD sub-panel -- the second indicator kind, toggled via indicatorKindTabs.
// Unlike RSI's fixed 0-100 domain, MACD's line/signal/histogram vary by
// symbol and price magnitude, so the panel scales to the visible series'
// own min/max, symmetric around zero (a MACD panel with no visible zero
// line would be unreadable -- crossovers are the whole point).
function macdPanelGroup(candles, geom, cx) {
  if (!candles.some((c) => c.macd != null)) return null;
  const g = document.createElementNS(SVG_NS, "g");

  let absMax = 0;
  for (const c of candles) {
    for (const v of [c.macd, c.macd_signal, c.macd_histogram]) {
      if (v != null) absMax = Math.max(absMax, Math.abs(v));
    }
  }
  if (absMax === 0) absMax = 1;
  absMax *= 1.15; // headroom so the extremes aren't flush against the panel edges

  const yMacd = (v) => geom.indBot - ((v + absMax) / (2 * absMax)) * geom.indH;

  const zero = document.createElementNS(SVG_NS, "line");
  zero.setAttribute("x1", geom.padL);
  zero.setAttribute("x2", geom.w - geom.padR);
  zero.setAttribute("y1", yMacd(0).toFixed(2));
  zero.setAttribute("y2", yMacd(0).toFixed(2));
  zero.setAttribute("class", "macd-zero-line");
  g.appendChild(zero);
  const zeroLabel = document.createElementNS(SVG_NS, "text");
  zeroLabel.setAttribute("x", geom.w - geom.padR + 6);
  zeroLabel.setAttribute("y", yMacd(0).toFixed(2));
  zeroLabel.setAttribute("class", "chart-axis-label");
  zeroLabel.setAttribute("dominant-baseline", "middle");
  zeroLabel.textContent = "0";
  g.appendChild(zeroLabel);

  const n = candles.length;
  const slot = geom.plotW / n;
  const barW = Math.max(1, slot * 0.62);
  candles.forEach((c, i) => {
    if (c.macd_histogram == null) return;
    const y0 = yMacd(0);
    const y1 = yMacd(c.macd_histogram);
    const rect = document.createElementNS(SVG_NS, "rect");
    rect.setAttribute("x", (cx(i) - barW / 2).toFixed(2));
    rect.setAttribute("y", Math.min(y0, y1).toFixed(2));
    rect.setAttribute("width", barW.toFixed(2));
    rect.setAttribute("height", Math.max(1, Math.abs(y1 - y0)).toFixed(2));
    rect.setAttribute("class", c.macd_histogram >= 0 ? "macd-hist-bar-up" : "macd-hist-bar-down");
    g.appendChild(rect);
  });

  function macdPolyline(key, cls) {
    const pts = [];
    candles.forEach((c, i) => {
      const v = c[key];
      if (v == null) return;
      pts.push(`${cx(i).toFixed(2)},${yMacd(v).toFixed(2)}`);
    });
    if (pts.length < 2) return null;
    const p = document.createElementNS(SVG_NS, "polyline");
    p.setAttribute("points", pts.join(" "));
    p.setAttribute("class", cls);
    return p;
  }
  const macdLine = macdPolyline("macd", "macd-line");
  if (macdLine) g.appendChild(macdLine);
  const signalLine = macdPolyline("macd_signal", "macd-signal-line");
  if (signalLine) g.appendChild(signalLine);

  return g;
}

// Dispatches to whichever indicator sub-panel is currently selected --
// both read fields already present on each candle from GET /api/history,
// no extra fetch needed to switch.
function indicatorPanelGroup(candles, geom, cx, kind) {
  return kind === "macd" ? macdPanelGroup(candles, geom, cx) : rsiPanelGroup(candles, geom, cx);
}

const INDICATOR_KINDS = ["rsi", "macd"];
const INDICATOR_KIND_LABELS = { rsi: "RSI", macd: "MACD" };
const INDICATOR_KIND_STORAGE_KEY = "futures_chart_indicator";

function indicatorKindTabs(current, onSelect) {
  const row = el("div", { class: "forecast-tabs" });
  for (const kind of INDICATOR_KINDS) {
    const btn = el(
      "button",
      { class: `forecast-tab${kind === current ? " active" : ""}` },
      INDICATOR_KIND_LABELS[kind]
    );
    btn.addEventListener("click", () => onSelect(kind));
    row.appendChild(btn);
  }
  return row;
}

// Crosshair + OHLC/indicator tooltip on hover. Pure SVG (a transparent hit
// rect over the plot area + a hidden-until-hover <g>), not an HTML overlay
// -- getScreenCTM()/matrixTransform() convert the mouse's client coords
// into the same viewBox coordinate space everything else in this chart
// already uses, so no separate pixel-position math is needed to keep the
// tooltip aligned as the SVG scales to its container width.
function attachCrosshair(svg, geom, candles, cx, yPrice, indicatorKind) {
  const n = candles.length;
  const slot = geom.plotW / n;

  const crosshairG = document.createElementNS(SVG_NS, "g");
  crosshairG.setAttribute("class", "chart-crosshair-group");
  crosshairG.style.display = "none";

  const vLine = document.createElementNS(SVG_NS, "line");
  vLine.setAttribute("class", "chart-crosshair-line");
  vLine.setAttribute("y1", geom.priceTop);
  vLine.setAttribute("y2", geom.indBot);
  crosshairG.appendChild(vLine);

  const dot = document.createElementNS(SVG_NS, "circle");
  dot.setAttribute("r", 3);
  dot.setAttribute("class", "chart-crosshair-dot");
  crosshairG.appendChild(dot);

  const tooltipG = document.createElementNS(SVG_NS, "g");
  const TOOLTIP_W = 168;
  const LINES = 5;
  const tooltipBg = document.createElementNS(SVG_NS, "rect");
  tooltipBg.setAttribute("class", "chart-tooltip-bg");
  tooltipBg.setAttribute("rx", 4);
  tooltipBg.setAttribute("width", TOOLTIP_W);
  tooltipBg.setAttribute("height", LINES * 15 + 8);
  tooltipG.appendChild(tooltipBg);
  const textNodes = [];
  for (let i = 0; i < LINES; i++) {
    const t = document.createElementNS(SVG_NS, "text");
    t.setAttribute("class", "chart-tooltip-text");
    t.setAttribute("x", 8);
    t.setAttribute("y", 15 + i * 15);
    tooltipG.appendChild(t);
    textNodes.push(t);
  }
  crosshairG.appendChild(tooltipG);
  svg.appendChild(crosshairG);

  const hoverTarget = document.createElementNS(SVG_NS, "rect");
  hoverTarget.setAttribute("x", geom.padL);
  hoverTarget.setAttribute("y", geom.priceTop);
  hoverTarget.setAttribute("width", geom.plotW);
  hoverTarget.setAttribute("height", geom.indBot - geom.priceTop);
  hoverTarget.setAttribute("class", "chart-hover-target");
  svg.appendChild(hoverTarget);

  function svgPoint(evt) {
    const ctm = svg.getScreenCTM();
    if (!ctm) return null;
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX;
    pt.y = evt.clientY;
    return pt.matrixTransform(ctm.inverse());
  }

  hoverTarget.addEventListener("mousemove", (evt) => {
    const p = svgPoint(evt);
    if (!p) return;
    let i = Math.round((p.x - geom.padL - slot / 2) / slot);
    i = Math.max(0, Math.min(n - 1, i));
    const c = candles[i];
    const x = cx(i);

    vLine.setAttribute("x1", x.toFixed(2));
    vLine.setAttribute("x2", x.toFixed(2));
    if (c.close != null) {
      dot.setAttribute("cx", x.toFixed(2));
      dot.setAttribute("cy", yPrice(c.close).toFixed(2));
      dot.style.display = "";
    } else {
      dot.style.display = "none";
    }

    const lines = [
      new Date(c.timestamp).toLocaleString(),
      `O ${fmtNum(c.open)}   H ${fmtNum(c.high)}`,
      `L ${fmtNum(c.low)}   C ${fmtNum(c.close)}`,
      c.volume != null ? `Vol ${fmtNum(c.volume)}` : "Vol n/a",
      indicatorKind === "macd"
        ? c.macd != null
          ? `MACD ${fmtNum(c.macd, 3)}  Sig ${fmtNum(c.macd_signal, 3)}`
          : "MACD n/a"
        : c.rsi != null
          ? `RSI ${fmtNum(c.rsi)}`
          : "RSI n/a",
    ];
    lines.forEach((text, idx) => {
      textNodes[idx].textContent = text;
      textNodes[idx].setAttribute("class", idx === 0 ? "chart-tooltip-text muted" : "chart-tooltip-text");
    });

    // Flip the tooltip to the left of the crosshair once there isn't room
    // to its right, so it never overflows past the price-axis gutter.
    const flip = x + 10 + TOOLTIP_W > geom.w - geom.padR;
    const tx = flip ? x - 10 - TOOLTIP_W : x + 10;
    tooltipG.setAttribute("transform", `translate(${tx.toFixed(2)}, ${geom.priceTop + 6})`);

    crosshairG.style.display = "";
  });
  hoverTarget.addEventListener("mouseleave", () => {
    crosshairG.style.display = "none";
  });
}

// 8-axis radar/spider chart over real 0-100 scores -- purely a second
// visualization of numbers already computed elsewhere (GlobalMarketScore +
// ExecutiveSummaryEngine's market_health), no new scoring. `axes` is
// [{label, value}]; a null value renders at the center (0), never guessed.
function svgRadarChart(axes, { size = 320 } = {}) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
  svg.setAttribute("class", "radar-chart");
  const center = size / 2;
  const maxRadius = size / 2 - 44;
  const n = axes.length;
  const angleFor = (i) => (Math.PI * 2 * i) / n - Math.PI / 2;
  const point = (r, i) => {
    const a = angleFor(i);
    return [center + r * Math.cos(a), center + r * Math.sin(a)];
  };

  for (const pct of [25, 50, 75, 100]) {
    const r = (pct / 100) * maxRadius;
    const points = axes.map((_, i) => point(r, i).map((v) => v.toFixed(1)).join(",")).join(" ");
    const ring = document.createElementNS(SVG_NS, "polygon");
    ring.setAttribute("points", points);
    ring.setAttribute("class", "radar-grid");
    svg.appendChild(ring);
  }

  axes.forEach((axis, i) => {
    const [x2, y2] = point(maxRadius, i);
    const line = document.createElementNS(SVG_NS, "line");
    line.setAttribute("x1", center);
    line.setAttribute("y1", center);
    line.setAttribute("x2", x2.toFixed(1));
    line.setAttribute("y2", y2.toFixed(1));
    line.setAttribute("class", "radar-axis");
    svg.appendChild(line);

    const [lx, ly] = point(maxRadius + 20, i);
    const text = document.createElementNS(SVG_NS, "text");
    text.setAttribute("x", lx.toFixed(1));
    text.setAttribute("y", ly.toFixed(1));
    text.setAttribute("class", "radar-label");
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("dominant-baseline", "middle");
    text.textContent = axis.label;
    svg.appendChild(text);
  });

  const valuePoints = axes
    .map((axis, i) => {
      const value = axis.value == null ? 0 : Math.max(0, Math.min(100, axis.value));
      return point((value / 100) * maxRadius, i)
        .map((v) => v.toFixed(1))
        .join(",");
    })
    .join(" ");
  const poly = document.createElementNS(SVG_NS, "polygon");
  poly.setAttribute("points", valuePoints);
  poly.setAttribute("class", "radar-value");
  svg.appendChild(poly);

  return svg;
}

// AI Radar section for the Overview page. Axes reuse real already-computed
// scores: Momentum/Macro/Liquidity/Risk from GlobalMarketScore (`score`),
// News/Sentiment/Volatility from ExecutiveSummaryEngine's own market_health,
// and Whales from GlobalMarketScore's institutional_activity_score (the
// closest real "big money" proxy this project computes -- there is no
// dedicated whale-specific 0-100 score to reuse instead).
function renderAiRadar(score, execSummary) {
  const marketHealth = execSummary ? execSummary.market_health : null;
  const axes = [
    { label: "Momentum", value: score ? score.trend_strength_score : null },
    { label: "News", value: marketHealth ? marketHealth.news_quality : null },
    { label: "Sentiment", value: marketHealth ? marketHealth.sentiment : null },
    { label: "Whales", value: score ? score.institutional_activity_score : null },
    { label: "Macro", value: score ? score.macro_pressure_score : null },
    { label: "Liquidity", value: score ? score.liquidity_score : null },
    { label: "Volatility", value: marketHealth ? marketHealth.volatility : null },
    { label: "Risk", value: score ? score.risk_score : null },
  ];
  if (!axes.some((a) => a.value != null)) {
    return el("p", { class: "sub" }, "AI Radar: not enough data yet.");
  }
  return el("div", { class: "ai-radar-wrap" }, [
    svgRadarChart(axes),
    el(
      "div",
      { class: "grid" },
      axes.map((a) => card(a.label, a.value != null ? `${Math.round(a.value)}/100` : "n/a"))
    ),
  ]);
}

// Renders an arbitrary JSON value (nested dicts/lists included) as a
// readable definition list instead of a raw JSON.stringify() blob -- used
// wherever an API response's shape isn't flat/stable enough for a fixed
// table (e.g. report.institutional_summary).
function renderStructured(value) {
  if (value == null) return document.createTextNode("n/a");
  if (Array.isArray(value)) {
    if (!value.length) return document.createTextNode("none");
    const ul = el("ul", { class: "structured-list" });
    for (const v of value) ul.appendChild(el("li", {}, [renderStructured(v)]));
    return ul;
  }
  if (typeof value === "object") {
    const entries = Object.entries(value);
    if (!entries.length) return document.createTextNode("none");
    const dl = el("dl", { class: "structured" });
    for (const [k, v] of entries) {
      dl.appendChild(el("dt", {}, k.replace(/_/g, " ")));
      dl.appendChild(el("dd", {}, [renderStructured(v)]));
    }
    return dl;
  }
  return document.createTextNode(String(value));
}

// Correlation-style heatmap cell: background intensity scales with |value|
// (assumed roughly in [-1, 1]), color follows the existing up/down convention.
function heatCell(value, text) {
  const v = Math.max(-1, Math.min(1, value ?? 0));
  const alpha = Math.abs(v) * 0.55;
  const bg = v > 0 ? `rgba(63, 185, 80, ${alpha})` : v < 0 ? `rgba(248, 81, 73, ${alpha})` : "transparent";
  return el("span", { class: "heat-cell", style: `background:${bg}` }, text);
}

const content = document.getElementById("content");

async function render(fn) {
  content.innerHTML = "";
  content.appendChild(el("p", { class: "loading" }, "Loading..."));
  try {
    const nodes = await fn();
    content.innerHTML = "";
    for (const n of [].concat(nodes)) content.appendChild(n);
  } catch (err) {
    content.innerHTML = "";
    content.appendChild(errorBox(err));
  }
}

async function safe(path) {
  try {
    return await fetchJSON(path);
  } catch {
    return null;
  }
}

// ---- page renderers ----

// AI Forecast Center -- the Overview page's hero card. Fully self-contained:
// owns its own horizon-tab state and re-fetches only its own subtree on tab
// switch (rather than re-invoking the whole-page render()), and ticks its
// own "next AI update" countdown off next_refresh_at, the same real
// APScheduler timestamp Watchdog's "Next Scan" card already uses -- never a
// fabricated countdown. The tick function checks `el.isConnected` each
// second and self-clears once the page navigates away, since render()
// replaces #content wholesale with no per-page teardown hook to attach to.
const FORECAST_HORIZON_HOURS = { "24h": 24, "3d": 72, "7d": 168, "30d": 720 };
const FORECAST_TIER_LABELS = {
  Weak: "Low", Medium: "Medium", Strong: "High", "Very Strong": "High", Institutional: "High",
};
const FORECAST_DIRECTION_STYLE = {
  "Strong Bullish": { arrow: "↑", emoji: "🟢", cls: "up" },
  Bullish: { arrow: "↑", emoji: "🟢", cls: "up" },
  Neutral: { arrow: "→", emoji: "⚪", cls: "neutral" },
  Bearish: { arrow: "↓", emoji: "🔴", cls: "down" },
  "Strong Bearish": { arrow: "↓", emoji: "🔴", cls: "down" },
};

function forecastPricePath(payload) {
  const hours = FORECAST_HORIZON_HOURS[payload.horizon] || 24;
  const rows = [["Now", payload.current_price, null]].concat(
    (payload.price_path || []).map((p) => [
      `${Math.round(hours * p.fraction)}h`,
      p.price,
      p.change_pct,
    ])
  );
  return el(
    "div",
    { class: "forecast-path" },
    rows.map(([label, price, changePct]) =>
      el("div", { class: "forecast-path-point" }, [
        el("div", { class: "forecast-path-label" }, label),
        el("div", { class: "forecast-path-price" }, fmtNum(price)),
        changePct != null ? el("div", { class: `sub ${changeClass(changePct)}` }, fmtPct(changePct)) : null,
      ])
    )
  );
}

function forecastConsensusSection(consensus) {
  if (!consensus) return el("p", { class: "sub" }, "AI Consensus: not yet computed.");
  const rows = [];
  for (const agent of consensus.bullish_agents || []) rows.push([agent, "Bullish", "up"]);
  for (const agent of consensus.bearish_agents || []) rows.push([agent, "Bearish", "down"]);
  for (const agent of consensus.neutral_agents || []) rows.push([agent, "Neutral", "neutral"]);
  for (const agent of consensus.unavailable_agents || []) rows.push([agent, "No data", "neutral"]);
  const dominant = ["bullish_pct", "bearish_pct", "neutral_pct"].reduce((a, b) =>
    consensus[a] >= consensus[b] ? a : b
  );
  const dominantLabel = { bullish_pct: "Bullish", bearish_pct: "Bearish", neutral_pct: "Neutral" }[dominant];
  return el("div", {}, [
    el(
      "div",
      { class: "grid" },
      rows.map(([agent, label, cls]) =>
        el("div", { class: "card" }, [
          el("div", { class: "label" }, agent.replace(/_/g, " ")),
          el("div", { class: `value ${cls}` }, label),
        ])
      )
    ),
    el("p", {}, [
      el("strong", {}, "Final Consensus: "),
      `${dominantLabel} (${consensus.agreement_score}% agreement)`,
    ]),
    consensus.raw_agreement_score != null && consensus.raw_agreement_score !== consensus.agreement_score
      ? el(
          "p",
          { class: "sub" },
          `Before correlation adjustment: ${consensus.raw_agreement_score}% agreement -- ` +
            `redundant/correlated agents discounted this to ${consensus.agreement_score}%.`
        )
      : null,
  ]);
}

const FORECAST_CASE_LABELS = { bull_case: "Bull Case", base_case: "Base Case", bear_case: "Bear Case" };
const FORECAST_CASE_CLASS = { bull_case: "up", base_case: "neutral", bear_case: "down" };

function forecastScenarioCases(scenarioCases) {
  if (!scenarioCases) return el("p", { class: "sub" }, "Scenario cases need ATR data, not yet available.");
  return el(
    "div",
    { class: "grid" },
    ["bull_case", "base_case", "bear_case"].map((key) => {
      const c = scenarioCases[key];
      return el("div", { class: "card" }, [
        el("div", { class: "label" }, FORECAST_CASE_LABELS[key]),
        el("div", { class: `value ${FORECAST_CASE_CLASS[key]}` }, fmtNum(c.target_price)),
        el("div", { class: "sub" }, `Probability ${c.probability_pct}%`),
        el("div", { class: `sub ${changeClass(c.expected_return_pct)}` }, `Return ${fmtPct(c.expected_return_pct)}`),
        el("div", { class: "sub" }, `Confidence ${c.confidence_pct != null ? c.confidence_pct + "%" : "n/a"}`),
      ]);
    })
  );
}

function forecastAiExplanation(aiExplanation) {
  if (!aiExplanation || !(aiExplanation.engine_breakdown || []).length) {
    return [el("p", { class: "sub" }, "AI Explanation not yet available.")];
  }
  const nodes = [
    table(
      ["Engine", "Signal", "Weight", "Confidence", "Reason"],
      aiExplanation.engine_breakdown.map((row) => [
        row.name,
        row.signal || "n/a",
        row.weight != null ? `${row.weight}%` : "n/a",
        row.confidence != null ? `${row.confidence}%` : "unavailable",
        row.explanation || "n/a",
      ])
    ),
  ];
  const fp = aiExplanation.final_prediction;
  if (fp) {
    nodes.push(
      el("p", { class: "sub" }, [
        el("strong", {}, "Final Consensus Bias: "),
        `${fp.bias || "n/a"}${fp.agreement_score != null ? ` (${fp.agreement_score}% agreement)` : ""}`,
      ])
    );
  }
  return nodes;
}

// V9 Increment 10: reads the most recent history row for the currently
// selected horizon (history covers every horizon, mixed together) rather
// than the live `payload` -- a freshly computed forecast is always
// "ACTIVE" by construction (invalidation is decided by the separate
// check_and_invalidate_forecasts scheduler job against the PERSISTED row,
// which can flip a forecast to INVALIDATED well after it was computed).
function forecastInvalidationBadge(history, horizon) {
  if (!history || !history.forecasts) return null;
  const latest = history.forecasts.find((f) => f.horizon === horizon);
  if (!latest) return null;
  const invalidated = latest.forecast_status === "INVALIDATED";
  const parts = [
    el(
      "span",
      { class: invalidated ? "down" : "up" },
      invalidated ? "⚠ INVALIDATED" : "✓ ACTIVE"
    ),
  ];
  if (latest.forecast_version) parts.push(el("span", { class: "sub" }, ` · v${latest.forecast_version}`));
  if (invalidated && latest.invalidation_reason) {
    parts.push(el("span", { class: "sub" }, ` -- ${latest.invalidation_reason}`));
  }
  return el("div", { class: "forecast-status-line" }, parts);
}

// V9 Increment 1's empirical forward-return distribution (p10-p90 across
// the same RSI[+regime]-bucketed historical sample ProbabilityEngine
// already computes) -- a real measured spread, not the price-target card's
// own normal-approximation bands above.
function forecastQuantileBands(payload) {
  const q = payload.forward_return_quantiles;
  if (!q || q.p10_pct == null) {
    return el(
      "p",
      { class: "sub" },
      "Forward-return distribution needs more historical samples for this bucket."
    );
  }
  const nodes = [
    el("div", { class: "grid" }, [
      card("P10", fmtPct(q.p10_pct)),
      card("P25", fmtPct(q.p25_pct)),
      card("P50 (Median)", fmtPct(q.p50_pct)),
      card("P75", fmtPct(q.p75_pct)),
      card("P90", fmtPct(q.p90_pct)),
    ]),
  ];
  nodes.push(
    el(
      "p",
      { class: "sub" },
      payload.regime_conditioned
        ? `Conditioned on the current market regime (${payload.reference_regime || "n/a"}).`
        : "Not regime-conditioned this cycle -- too few same-regime samples, using the full history instead."
    )
  );
  nodes.push(
    el(
      "p",
      { class: "sub" },
      payload.volatility_conditioned
        ? "Also conditioned on similarly-volatile historical periods."
        : "Not volatility-conditioned this cycle -- too few similarly-volatile samples."
    )
  );
  return nodes;
}

function forecastKeyLevels(levels) {
  if (!levels) return null;
  return el("div", { class: "grid" }, [
    card("Support 1", fmtNum(levels.support_1)),
    card("Support 2", fmtNum(levels.support_2)),
    card("Resistance 1", fmtNum(levels.resistance_1)),
    card("Resistance 2", fmtNum(levels.resistance_2)),
    card("Invalidation Level", fmtNum(levels.invalidation_level)),
    card("Breakout Level", fmtNum(levels.breakout_level)),
  ]);
}

function forecastHorizonConsistency(consistency) {
  if (!consistency) {
    return el("p", { class: "sub" }, "Multi-horizon consistency: not enough horizons computed yet.");
  }
  const groupCards = ["short_term", "medium_term", "long_term"]
    .filter((key) => consistency[key] != null)
    .map((key) => {
      const style = FORECAST_DIRECTION_STYLE[consistency[key]] || FORECAST_DIRECTION_STYLE.Neutral;
      const label = { short_term: "Short-term (24h)", medium_term: "Medium-term (3d-7d)", long_term: "Long-term (30d)" }[key];
      return el("div", { class: "card" }, [
        el("div", { class: "label" }, label),
        el("div", { class: `value ${style.cls}` }, `${style.emoji} ${consistency[key]}`),
      ]);
    });
  return el("div", {}, [
    el("div", { class: "grid" }, groupCards),
    el("p", {}, consistency.explanation),
  ]);
}

// Win Rate: % of this symbol/horizon's own graded forecasts whose
// direction call matched the real outcome (direction_correct), excluding
// Neutral calls which have no direction to grade -- see
// ForecastEngine.summarize_forecast_accuracy's own docstring. Every
// forecast this engine persists is automatically graded once its horizon
// elapses (grade_forecasts_job, scheduled), so this is a real recorded
// track record, never a fabricated number.
function winRateFragment(trackRecord) {
  if (trackRecord.win_rate_pct == null) return "";
  return ` -- win rate ${trackRecord.win_rate_pct}% (${trackRecord.win_rate_sample_size} directional calls)`;
}

function forecastTrackRecordLine(trackRecord) {
  if (!trackRecord || trackRecord.evaluated_count === 0) {
    return el(
      "p",
      { class: "sub" },
      "Track record: not enough graded forecasts yet for this symbol/horizon."
    );
  }
  if (trackRecord.quality_multiplier == null) {
    return el(
      "p",
      { class: "sub" },
      `Track record: ${trackRecord.evaluated_count} graded (avg error ${trackRecord.avg_abs_error_pct}%)${winRateFragment(trackRecord)} -- not yet enough to adjust confidence.`
    );
  }
  return el(
    "p",
    { class: "sub" },
    `Track record: ${trackRecord.evaluated_count} graded, avg error ${trackRecord.avg_abs_error_pct}%${winRateFragment(trackRecord)} -- ` +
      `self-learning discount x${trackRecord.quality_multiplier} (adjusted confidence ${trackRecord.adjusted_confidence_pct}%)`
  );
}

function forecastHistorySection(history) {
  const nodes = [el("h3", {}, "Prediction History & Self-Learning")];
  if (!history) {
    nodes.push(el("p", { class: "sub" }, "History not yet available."));
    return nodes;
  }

  nodes.push(
    el(
      "div",
      { class: "grid" },
      Object.entries(history.accuracy_by_horizon || {}).flatMap(([horizon, summary]) => [
        card(
          `${horizon} Accuracy`,
          summary.evaluated_count > 0 ? `${summary.avg_abs_error_pct}% avg error` : "n/a",
          summary.evaluated_count > 0 ? `${summary.evaluated_count} graded` : "not enough history yet"
        ),
        card(
          `${horizon} Win Rate`,
          summary.win_rate_pct != null ? `${summary.win_rate_pct}%` : "n/a",
          summary.win_rate_pct != null
            ? `${summary.win_rate_sample_size} directional calls`
            : "no graded directional calls yet",
          summary.win_rate_pct != null ? changeClass(summary.win_rate_pct - 50) : null
        ),
      ])
    )
  );

  if (!history.forecasts || !history.forecasts.length) {
    nodes.push(el("p", { class: "sub" }, "No forecasts stored yet."));
    return nodes;
  }

  nodes.push(
    table(
      ["Horizon", "Computed At", "Predicted", "Actual", "Error %", "Confidence"],
      history.forecasts.map((f) => [
        f.horizon,
        new Date(f.computed_at).toLocaleString(),
        fmtNum(f.target_price),
        f.realized_price != null ? fmtNum(f.realized_price) : "pending",
        f.error_pct != null ? fmtPct(f.error_pct) : "pending",
        f.confidence_tier || "n/a",
      ])
    )
  );
  return nodes;
}

function buildForecastCard(payload, onHorizonChange, historyNodes, history) {
  const style = FORECAST_DIRECTION_STYLE[payload.direction] || FORECAST_DIRECTION_STYLE.Neutral;
  const tier = payload.confidence ? payload.confidence.tier : null;
  const confidenceLabel = tier ? `${FORECAST_TIER_LABELS[tier] || tier} (${tier})` : "n/a";

  const root = el("div", { class: "forecast-center" });

  const statusBadge = forecastInvalidationBadge(history, payload.horizon);
  const header = el("div", { class: "forecast-header" }, [
    el("div", {}, [
      el("div", { class: "forecast-eyebrow" }, "AI FORECAST CENTER"),
      el("div", { class: "forecast-symbol" }, `${payload.symbol} · ${payload.horizon}`),
      statusBadge,
    ]),
    el(
      "div",
      { class: "forecast-tabs" },
      Object.keys(FORECAST_HORIZON_HOURS).map((h) => {
        const btn = el(
          "button",
          { class: `forecast-tab${h === payload.horizon ? " active" : ""}` },
          h
        );
        btn.addEventListener("click", () => onHorizonChange(h));
        return btn;
      })
    ),
  ]);

  const liveCurrent = RealtimeStore.get(payload.symbol);
  const hero = el("div", { class: "forecast-hero" }, [
    el("div", { class: "forecast-hero-block" }, [
      el("div", { class: "forecast-stat-label" }, "Current Price"),
      el(
        "div",
        { class: "forecast-price", id: "forecast-current-price" },
        fmtNum(liveCurrent ? liveCurrent.price : payload.current_price)
      ),
      liveCurrent
        ? dataFreshnessBadge(liveCurrent.freshness, liveCurrent.ageSeconds)
        : dataFreshnessBadge(null, null),
    ]),
    el("div", { class: `forecast-arrow ${style.cls}` }, style.arrow),
    el("div", { class: "forecast-hero-block" }, [
      el("div", { class: "forecast-stat-label" }, `AI Forecast (${payload.horizon})`),
      el("div", { class: "forecast-price" }, fmtNum(payload.target_price)),
      el("div", { class: `forecast-direction ${style.cls}` }, `${style.emoji} ${payload.direction}`),
    ]),
  ]);

  const heroStats = el("div", { class: "grid" }, [
    card(
      "Expected Change",
      fmtPct(payload.expected_change_pct),
      null,
      changeClass(payload.expected_change_pct),
      "forecast-expected-change"
    ),
    card("Probability", `${payload.probability_pct}%`),
    card("Confidence", confidenceLabel),
    card("Expected Range", payload.expected_range ? `${fmtNum(payload.expected_range.low)} - ${fmtNum(payload.expected_range.high)}` : "n/a"),
    card("Expected Volatility", payload.expected_volatility_pct != null ? `${payload.expected_volatility_pct}%` : "n/a"),
    card("Expected Max Drawdown", payload.expected_max_drawdown_pct != null ? `${payload.expected_max_drawdown_pct}%` : "n/a"),
    card("Trend Strength", payload.trend_strength != null ? payload.trend_strength.toFixed(1) : "n/a"),
    card("Momentum Score", payload.momentum_score != null ? payload.momentum_score.toFixed(0) : "n/a"),
    card("Market Regime", payload.regime || "n/a"),
    card("Risk Level", payload.risk_meter || "n/a"),
    card(
      "Prediction Range",
      payload.prediction_range
        ? `${fmtNum(payload.prediction_range.lower_bound)} - ${fmtNum(payload.prediction_range.upper_bound)}`
        : "n/a"
    ),
  ]);

  const trackRecord = forecastTrackRecordLine(payload.track_record);

  const reasons = (payload.reasons || []).length
    ? el(
        "ul",
        { class: "structured-list" },
        payload.reasons.map((r) =>
          el("li", {}, `${r.name.replace(/_/g, " ")} (score ${r.points ?? "n/a"})`)
        )
      )
    : el("p", { class: "sub" }, "No triggered indicators this cycle.");

  const confidenceBreakdown = el(
    "div",
    { class: "grid" },
    (payload.confidence_breakdown || []).map((row) =>
      card(row.name, row.confidence_pct != null ? `${row.confidence_pct}%` : "unavailable")
    )
  );

  const distribution = (payload.probability_distribution || []).length
    ? el(
        "div",
        { class: "grid" },
        payload.probability_distribution.map((b) => card(b.label, `${b.probability_pct}%`))
      )
    : el("p", { class: "sub" }, "Probability distribution needs ATR data, not yet available.");

  const whatCanChange = (payload.what_can_change || []).length
    ? el("ul", { class: "structured-list" }, payload.what_can_change.map((item) => el("li", {}, item)))
    : el("p", { class: "sub" }, "No dynamic risk events flagged this cycle.");

  const countdown = el("div", { class: "forecast-countdown sub" }, "");
  const footer = el("div", { class: "forecast-footer" }, [
    el("span", {}, `Last AI update: ${new Date(payload.computed_at).toLocaleTimeString()}`),
    countdown,
  ]);
  if (payload.next_refresh_at) {
    const nextRefresh = new Date(payload.next_refresh_at).getTime();
    // Renders immediately regardless of DOM attachment (this element isn't
    // appended to the page until after this function returns), then only
    // keeps ticking -- and self-clears -- once it's actually connected.
    const tick = () => {
      const remaining = Math.max(0, Math.round((nextRefresh - Date.now()) / 1000));
      countdown.textContent = `Next AI update in ${remaining}s`;
      if (countdown.isConnected) setTimeout(tick, 1000);
    };
    tick();
  }

  root.appendChild(header);
  root.appendChild(hero);
  root.appendChild(heroStats);
  root.appendChild(trackRecord);
  root.appendChild(el("h3", {}, "Bull / Base / Bear Case"));
  root.appendChild(forecastScenarioCases(payload.scenario_cases));
  root.appendChild(el("h3", {}, "Price Path"));
  root.appendChild(forecastPricePath(payload));
  root.appendChild(el("h3", {}, "Why AI Thinks This"));
  root.appendChild(reasons);
  root.appendChild(el("h3", {}, "Confidence Breakdown"));
  root.appendChild(confidenceBreakdown);
  root.appendChild(el("h3", {}, "Probability Distribution"));
  root.appendChild(distribution);
  root.appendChild(el("h3", {}, "Empirical Forward-Return Distribution"));
  for (const node of [].concat(forecastQuantileBands(payload))) root.appendChild(node);
  root.appendChild(el("h3", {}, "AI Consensus"));
  root.appendChild(forecastConsensusSection(payload.consensus));
  root.appendChild(el("h3", {}, "AI Explanation"));
  for (const node of forecastAiExplanation(payload.ai_explanation)) root.appendChild(node);
  root.appendChild(el("h3", {}, "Key Levels"));
  const keyLevels = forecastKeyLevels(payload.key_levels);
  if (keyLevels) root.appendChild(keyLevels);
  root.appendChild(el("h3", {}, "Multi-Horizon Consistency"));
  root.appendChild(forecastHorizonConsistency(payload.horizon_consistency));
  root.appendChild(el("h3", {}, "What Can Change The Forecast"));
  root.appendChild(whatCanChange);
  for (const node of historyNodes || []) root.appendChild(node);
  root.appendChild(footer);
  return root;
}

async function renderForecastCenter() {
  const container = el("div", { class: "forecast-center-wrap" });
  // Fetched once (not per horizon-tab switch): the history table already
  // covers every horizon, and re-fetching it on every tab click would be
  // wasted work for data that doesn't depend on which tab is selected.
  const history = await safe("/api/forecast/BTC/history");

  async function load(horizon) {
    const payload = await safe(`/api/forecast/BTC?horizon=${horizon}`);
    container.innerHTML = "";
    if (!payload) {
      container.appendChild(
        el("p", { class: "error" }, "AI Forecast Center: not enough data yet for BTC.")
      );
      return;
    }
    container.appendChild(buildForecastCard(payload, load, forecastHistorySection(history), history));
    mountForecastLivePrice(payload);
  }

  await load("24h");
  return container;
}

// Executive Market Summary -- the Overview page's second hero panel,
// directly below the AI Forecast Center. Bias/score/factors/action all come
// from a single /api/executive-summary/BTC read; no client-side scoring.
const EXEC_BIAS_STYLE = {
  "Strong Bullish": "up",
  Bullish: "up",
  Neutral: "neutral",
  Bearish: "down",
  "Strong Bearish": "down",
};

const EXEC_MARKET_HEALTH_FIELDS = [
  ["Liquidity", "liquidity"],
  ["Volatility", "volatility"],
  ["Momentum", "momentum"],
  ["Trend Strength", "trend_strength"],
  ["Sentiment", "sentiment"],
  ["Institutional Activity", "institutional_activity"],
  ["On-chain Activity", "onchain_activity"],
  ["News Quality", "news_quality"],
  ["Correlation Strength", "correlation_strength"],
];

const EXEC_ACTION_STYLE = {
  "Strong Buy": "up",
  Buy: "up",
  Accumulate: "up",
  Hold: "neutral",
  "Reduce Risk": "down",
  "Take Profit": "down",
  Sell: "down",
  "No Trade": "neutral",
};

function buildExecutiveSummaryCard(payload) {
  const biasCls = EXEC_BIAS_STYLE[payload.bias] || "neutral";
  const actionCls = EXEC_ACTION_STYLE[payload.action] || "neutral";

  const root = el("div", { class: "exec-summary" });

  root.appendChild(
    el("div", { class: "exec-summary-header" }, [
      el("div", { class: "forecast-eyebrow" }, "EXECUTIVE MARKET SUMMARY"),
      el("div", { class: "forecast-symbol" }, payload.symbol),
    ])
  );

  root.appendChild(
    el("div", { class: "exec-summary-hero" }, [
      el("div", { class: "forecast-hero-block" }, [
        el("div", { class: "forecast-stat-label" }, "Overall Market Score"),
        el("div", { class: "forecast-price" }, payload.overall_score != null ? `${payload.overall_score}/100` : "n/a"),
      ]),
      el("div", { class: "forecast-hero-block" }, [
        el("div", { class: "forecast-stat-label" }, "Current Bias"),
        el("div", { class: `forecast-direction ${biasCls}` }, payload.bias),
      ]),
    ])
  );

  root.appendChild(el("p", {}, payload.summary));

  root.appendChild(
    el("div", { class: "exec-summary-factors" }, [
      el("div", {}, [
        el("h3", {}, "Bullish Factors"),
        payload.bullish_factors && payload.bullish_factors.length
          ? el("ul", { class: "structured-list" }, payload.bullish_factors.map((f) => el("li", { class: "up" }, `✓ ${f}`)))
          : el("p", { class: "sub" }, "No bullish factors flagged this cycle."),
      ]),
      el("div", {}, [
        el("h3", {}, "Bearish Factors"),
        payload.bearish_factors && payload.bearish_factors.length
          ? el("ul", { class: "structured-list" }, payload.bearish_factors.map((f) => el("li", { class: "down" }, `⚠ ${f}`)))
          : el("p", { class: "sub" }, "No bearish factors flagged this cycle."),
      ]),
    ])
  );

  root.appendChild(el("h3", {}, "Market Health"));
  root.appendChild(
    el(
      "div",
      { class: "grid" },
      EXEC_MARKET_HEALTH_FIELDS.map(([label, key]) => scoreBar(label, payload.market_health[key]))
    )
  );

  root.appendChild(el("h3", {}, "AI Action"));
  root.appendChild(
    el("div", { class: "exec-summary-action" }, [
      el("span", { class: `exec-action-badge ${actionCls}` }, payload.action),
      el("span", { class: "sub" }, payload.action_reason),
    ])
  );

  root.appendChild(
    el(
      "div",
      { class: "forecast-footer" },
      `Last analysis cycle: ${new Date(payload.watchdog_computed_at).toLocaleString()}`
    )
  );

  return root;
}

async function renderExecutiveSummary() {
  const payload = await safe("/api/executive-summary/BTC");
  if (!payload) {
    return el(
      "p",
      { class: "error exec-summary-wrap" },
      "Executive Market Summary: not enough data yet (Market Watchdog hasn't completed a cycle)."
    );
  }
  const wrap = el("div", { class: "exec-summary-wrap" });
  wrap.appendChild(buildExecutiveSummaryCard(payload));
  return wrap;
}

function renderMarketMovers(breadth) {
  if (!breadth || (!breadth.top_gainers.length && !breadth.top_losers.length)) return [];
  const nodes = [el("h2", {}, "Market Movers")];
  const grid = el("div", { class: "grid-2col" });
  const moversTable = (title, rows, extraHeader) => {
    const wrap = el("div");
    wrap.appendChild(el("h3", {}, title));
    const headers = extraHeader ? ["Symbol", "Price", "24h %", extraHeader] : ["Symbol", "Price", "24h %"];
    wrap.appendChild(
      table(
        headers,
        rows.slice(0, 5).map((r) => {
          const row = [
            r.symbol,
            fmtNum(r.price, 6),
            el("span", { class: changeClass(r.change_pct_24h) }, fmtPct(r.change_pct_24h)),
          ];
          if (extraHeader) row.push(fmtPct(r.volume_change_pct));
          return row;
        })
      )
    );
    return wrap;
  };
  grid.appendChild(moversTable("Top Gainers", breadth.top_gainers));
  grid.appendChild(moversTable("Top Losers", breadth.top_losers));
  nodes.push(grid);
  if (breadth.top_volume_increase.length) {
    nodes.push(moversTable("Volume Surge", breadth.top_volume_increase, "Volume Change"));
  }
  nodes.push(
    el("p", { class: "sub nav-pointer" }, [
      "Related: ",
      el("a", { href: "#scanner" }, "Full Market Scanner (breadth, sectors, detections)"),
    ])
  );
  return nodes;
}

// Section 18 "Whale Activity" -- WhaleIntelligenceEngine has no
// per-transaction/inflow data source anywhere in this codebase (honestly
// documented in its own module), only aggregate derivatives positioning
// (funding rate, open interest, liquidations, long/short ratio). Rendered
// as-is rather than inventing per-transaction rows; renders nothing when
// the derivatives provider is unavailable this cycle.
function renderWhalePositioning(data) {
  if (!data || !data.available) return [];
  const nodes = [el("h2", {}, "Whale Positioning")];
  nodes.push(
    el("div", { class: "grid" }, [
      card("Classification", (data.classification || "n/a").replace(/_/g, " ")),
      card("Funding Rate", data.funding_rate != null ? `${(data.funding_rate * 100).toFixed(4)}%` : "n/a"),
      card("Long/Short Ratio", data.long_short_ratio != null ? data.long_short_ratio.toFixed(2) : "n/a"),
      card("Open Interest", data.open_interest != null ? fmtNum(data.open_interest, 0) : "n/a"),
      card("Liquidations 24h", data.liquidations_24h != null ? fmtNum(data.liquidations_24h, 0) : "n/a"),
    ])
  );
  return nodes;
}

// V9 Increment 9/10: real, graded hit-rate over past alerts -- never a
// simulated number. Renders nothing (not an empty-state block) until at
// least one alert has actually been graded, matching how
// renderWhalePositioning/renderTopOpportunities above stay silent rather
// than showing a placeholder for data that just hasn't arrived yet.
function renderAlertPerformance(summary, byType) {
  if (!summary || summary.graded_count === 0) return [];
  const nodes = [el("h2", {}, "Alert Performance")];
  nodes.push(
    el("div", { class: "grid" }, [
      card("Graded Alerts", summary.graded_count),
      card("Significant-Move Rate", `${summary.significant_move_rate_pct}%`),
      card(
        "Direction-Continued Rate",
        summary.direction_continued_rate_pct != null ? `${summary.direction_continued_rate_pct}%` : "n/a",
        summary.directional_alerts_count ? `of ${summary.directional_alerts_count} directional alerts` : null
      ),
      card("Avg Absolute Move", `${summary.avg_abs_realized_move_pct}%`),
    ])
  );
  if (byType && byType.length) {
    nodes.push(
      table(
        ["Alert Type", "Graded", "Significant %", "Direction-Continued %"],
        byType
          .slice(0, 10)
          .map((row) => [
            row.alert_type,
            row.graded_count,
            `${row.significant_move_rate_pct}%`,
            row.direction_continued_rate_pct != null ? `${row.direction_continued_rate_pct}%` : "n/a",
          ])
      )
    );
  }
  return nodes;
}

function renderTopOpportunities(data) {
  if (!data || !data.opportunities || !data.opportunities.length) return [];
  const nodes = [el("h2", {}, "Top Opportunities")];
  nodes.push(
    el(
      "p",
      { class: "sub" },
      "Ranked by risk-adjusted score -- Breakout Intelligence's confirmation-weighted probability discounted by how close price sits to the breakout level."
    )
  );
  nodes.push(
    table(
      ["Asset", "Price", "Trend", "Probability", "Confidence", "Risk", "AI Rating", "Reason"],
      data.opportunities.map((o) => [
        o.symbol,
        fmtNum(o.price, o.price < 10 ? 4 : 2),
        el("span", { class: changeClass(o.direction === "bullish" ? 1 : -1) }, o.direction),
        o.probability_pct != null ? `${o.probability_pct.toFixed(1)}%` : "n/a",
        `${o.confidence_pct}%`,
        o.risk_score != null ? `${o.risk_score.toFixed(0)}/100` : "n/a",
        decisionPill(o.rating, recommendationTone(o.rating)),
        o.expected_continuation,
      ])
    )
  );
  return nodes;
}

// Market Regime card (Overview): the regime label alone ("risk_on") told a
// user nothing about how confident that read is, how long it's held, or
// why detect_regime() picked it -- all three were already computed and
// stored (MarketRegimeSnapshot.confidence_pct, RegimeDetector.get_regime_streak(),
// describe_regime()) but never surfaced. This composes them into one
// prominent block instead of the bare card that used to sit in the top grid.
function regimeConfidenceTone(label) {
  if (label === "high") return "good";
  if (label === "low") return "bad";
  return "neutral";
}

function fmtRegimeDuration(hours, isLowerBound) {
  if (hours == null) return null;
  const text = hours >= 24 ? `${(hours / 24).toFixed(1)}d` : `${hours.toFixed(1)}h`;
  return isLowerBound ? `at least ${text}` : text;
}

function renderMarketRegimeCard(regime) {
  if (!regime) return null;
  const confidenceLabel = regime.confidence_label || "unavailable";
  const duration = fmtRegimeDuration(regime.duration_hours, regime.duration_is_lower_bound);
  return el("div", { class: "card regime-card" }, [
    el("div", { class: "regime-card-head" }, [
      el("div", {}, [
        el("div", { class: "label" }, "Market Regime"),
        el("div", { class: "value" }, regime.regime.replace(/_/g, " ")),
      ]),
      decisionPill(`${confidenceLabel.toUpperCase()} CONFIDENCE`, regimeConfidenceTone(confidenceLabel)),
    ]),
    duration ? el("div", { class: "sub" }, `In this regime for ${duration}`) : null,
    regime.explanation ? el("div", { class: "sub regime-explanation" }, regime.explanation) : null,
  ]);
}

// Live Alerts feed (Overview): the same alert-history entries Watchdog Hub's
// own "Alert History" table already shows (WatchdogEngine.get_alert_history(),
// the Memory Engine's "alerts" category over AlertLog) -- just the most
// recent handful, surfaced on Overview so a user doesn't have to leave the
// landing page to see what's fired lately. No new data source, no new query.
function renderLiveAlertsFeed(data) {
  if (!data || !data.entries || !data.entries.length) return [];
  const nodes = [el("h2", {}, "Live Alerts")];
  nodes.push(
    table(
      ["Time", "Alert Type", "Tier", "Message"],
      data.entries.map((e) => [
        e.timestamp.slice(0, 16).replace("T", " "),
        e.summary.alert_type,
        e.summary.conviction_tier,
        e.summary.message,
      ])
    )
  );
  nodes.push(
    el("p", { class: "sub nav-pointer" }, [
      "See also: ",
      el("a", { href: "#watchdog" }, "Watchdog Hub"),
    ])
  );
  return nodes;
}

// Compact multi-asset complement to the single-symbol AI Forecast Center
// hero card above it: the same official daily forecasts Forecasting 2.0
// already computes and shows one-card-per-asset (BTC/SOL/LINK/UNI by
// default) -- reused here as one glanceable row per asset instead of
// requiring a page switch. No new computation, no extra DB write: this
// is a pure GET against the already-cached-by-the-daily-job rows.
function renderForecastSnapshotMatrix(daily) {
  if (!daily || !daily.forecasts || !daily.forecasts.length) return [];
  const available = daily.forecasts.filter((f) => f.available);
  if (!available.length) return [];
  const nodes = [el("h2", {}, "AI Forecast Snapshot")];
  nodes.push(
    el(
      "p",
      { class: "sub" },
      "Today's official 24h call per asset -- see Forecasting 2.0 for full history and grading."
    )
  );
  nodes.push(
    table(
      ["Asset", "Direction", "Price", "Target", "Expected Change", "Probability", "Confidence"],
      available.map((f) => {
        const d = (f.direction || "").toLowerCase();
        const directionCls = d.includes("bullish") ? "up" : d.includes("bearish") ? "down" : "neutral";
        return [
          el("a", { href: `#assetdetail?symbol=${f.symbol}` }, f.symbol),
          el("span", { class: directionCls }, f.direction),
          fmtNum(f.current_price),
          fmtNum(f.target_price),
          el("span", { class: changeClass(f.expected_change_pct) }, fmtPct(f.expected_change_pct)),
          `${f.probability_pct}%`,
          f.confidence_tier,
        ];
      })
    )
  );
  nodes.push(
    el("p", { class: "sub nav-pointer" }, ["See also: ", el("a", { href: "#forecast2" }, "Forecasting 2.0")])
  );
  return nodes;
}

// Task: open positions visible on the main page, not just inside the
// Futures Simulator's own Positions tab. Always renders the section, even
// with zero open positions -- an honest "No open demo positions." rather
// than hiding the widget, so its presence itself isn't a signal.
function renderOverviewOpenPositions(data) {
  const positions = data ? data.positions : [];
  const nodes = [el("h2", {}, "Open Positions")];
  if (!positions || !positions.length) {
    nodes.push(el("p", { class: "sub" }, "No open demo positions."));
    return nodes;
  }
  nodes.push(
    table(
      ["Symbol", "Side", "Qty", "Entry", "Mark", "Notional", "Unrealized PnL", "ROI"],
      positions.map((p) => [
        p.symbol,
        el("span", { class: p.side === "LONG" ? "up" : "down" }, p.side),
        String(p.quantity),
        fmtNum(p.entry_price),
        fmtNum(p.mark_price),
        `$${fmtNum(p.quantity * p.mark_price)}`,
        el("span", { class: changeClass(p.unrealized_pnl) }, fmtNum(p.unrealized_pnl)),
        el("span", { class: changeClass(p.roi_pct) }, fmtPct(p.roi_pct)),
      ])
    )
  );
  nodes.push(
    el("p", { class: "sub nav-pointer" }, [
      "Manage in ",
      el("a", { href: "#futures?tab=positions" }, "Futures Simulator"),
    ])
  );
  return nodes;
}

async function renderOverview() {
  const [
    forecastCenter,
    execSummary,
    market,
    realtimeStatus,
    regime,
    signals,
    score,
    execSummaryData,
    opportunities,
    marketMovers,
    whales,
    alertPerformance,
    alertPerformanceByType,
    liveAlerts,
    forecastDaily,
    openPositionsData,
  ] = await Promise.all([
    renderForecastCenter(),
    renderExecutiveSummary(),
    safe("/api/market"),
    safe("/api/realtime/status"),
    safe("/api/regime"),
    safe("/api/signals"),
    safe("/api/global-score"),
    safe("/api/executive-summary/BTC"),
    safe("/api/opportunities"),
    safe("/api/scanner/movers"),
    safe("/api/whales"),
    safe("/api/alert-performance"),
    safe("/api/alert-performance/by-type"),
    safe("/api/watchdog/events?limit=5"),
    safe("/api/forecast/official/daily"),
    safe(`/api/simulator/positions?name=${encodeURIComponent(futuresAccountName())}&status=OPEN`),
  ]);

  const nodes = [];
  if (realtimeStatus && realtimeStatus.watchlist && realtimeStatus.watchlist.length) {
    nodes.push(liveTicker(realtimeStatus.watchlist, market ? market.quotes : null));
  }
  nodes.push(...renderOverviewOpenPositions(openPositionsData));
  nodes.push(forecastCenter);
  nodes.push(...renderForecastSnapshotMatrix(forecastDaily));
  nodes.push(execSummary, el("h2", {}, "Overview"));
  const regimeCard = renderMarketRegimeCard(regime);
  if (regimeCard) nodes.push(regimeCard);
  const top = el("div", { class: "grid" });
  if (signals) top.appendChild(card("Bull / Bear", `${signals.bull_score} / ${signals.bear_score}`, `net ${signals.net_score}, ${signals.confidence_pct}% confidence`));
  if (score) top.appendChild(card("Global Score", `${score.global_score}/100`));
  nodes.push(top);

  if (score) {
    nodes.push(el("h2", {}, "Global Market Score"));
    const scoreGrid = el("div", { class: "grid" });
    [
      ["Risk-On", "risk_on_score"], ["Risk-Off", "risk_off_score"], ["Liquidity", "liquidity_score"],
      ["Fear", "fear_score"], ["Greed", "greed_score"], ["Macro Pressure", "macro_pressure_score"],
      ["Institutional", "institutional_activity_score"], ["Crypto Strength", "crypto_strength_score"],
      ["Stock Strength", "stock_strength_score"], ["Trend Strength", "trend_strength_score"],
      ["Risk Score", "risk_score"], ["Confidence", "confidence_score"],
    ].forEach(([label, key]) => scoreGrid.appendChild(scoreBar(label, score[key])));
    nodes.push(scoreGrid);
  }

  nodes.push(el("h2", {}, "AI Radar"));
  nodes.push(renderAiRadar(score, execSummaryData));

  if (market && market.quotes) {
    nodes.push(el("h2", {}, "Market Snapshot"));
    nodes.push(quoteGrid(market.quotes));
  } else {
    nodes.push(el("p", { class: "error" }, "No market data collected yet."));
  }

  nodes.push(...renderMarketMovers(marketMovers));
  nodes.push(...renderWhalePositioning(whales));
  nodes.push(...renderTopOpportunities(opportunities));
  nodes.push(...renderLiveAlertsFeed(liveAlerts));
  nodes.push(...renderAlertPerformance(alertPerformance, alertPerformanceByType));

  return nodes;
}

// ---- Watchlist -------------------------------------------------------
// User-managed list, persisted client-side (no backend watchlist concept
// exists -- same localStorage pattern already used for the admin key).
// Prices reuse the same RealtimeStore/fallback-quote pattern as Overview's
// live ticker so this page updates without polling.

const _WATCHLIST_STORAGE_KEY = "dashboard_watchlist_symbols";

function _loadWatchlistSymbols(defaults) {
  try {
    const raw = localStorage.getItem(_WATCHLIST_STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch (e) {
    // Corrupted localStorage value -- fall through to defaults.
  }
  return [...defaults];
}

function _saveWatchlistSymbols(symbols) {
  localStorage.setItem(_WATCHLIST_STORAGE_KEY, JSON.stringify(symbols));
}

function _watchlistCurrentQuote(symbol, marketBySymbol) {
  const entry = RealtimeStore.get(symbol);
  const fallback = marketBySymbol.get(symbol);
  return {
    price: entry ? entry.price : fallback ? fallback.price : null,
    changePct: entry ? entry.changePercent24h : fallback ? fallback.change_pct_24h : null,
    volume: entry ? entry.volume24h : fallback ? fallback.volume_24h : null,
    freshness: entry ? entry.freshness : fallback ? fallback.freshness : null,
    ageSeconds: entry ? entry.ageSeconds : fallback ? fallback.age_seconds : null,
  };
}

function _watchlistForecastCell(forecast) {
  if (!forecast || !forecast.direction) return "n/a";
  const d = forecast.direction.toLowerCase();
  const arrow = d.includes("bullish") ? "↑" : d.includes("bearish") ? "↓" : "→";
  const cls = d.includes("bullish") ? "up" : d.includes("bearish") ? "down" : "neutral";
  return el("span", { class: cls }, `${arrow} ${forecast.probability_pct}%`);
}

async function renderWatchlist() {
  const nodes = [
    el("h2", {}, "Watchlist"),
    el(
      "p",
      { class: "sub" },
      "Prices update in realtime for symbols on the live feed (see the header indicator); " +
        "others fall back to the last collected snapshot with an honest freshness label."
    ),
  ];

  const [market, realtimeStatus] = await Promise.all([
    safe("/api/market"),
    safe("/api/realtime/status"),
  ]);
  const marketBySymbol = new Map((market ? market.quotes : []).map((q) => [q.symbol, q]));
  const defaultWatchlist =
    realtimeStatus && realtimeStatus.watchlist ? realtimeStatus.watchlist : ["BTC", "ETH", "SOL"];
  let symbols = _loadWatchlistSymbols(defaultWatchlist);

  // .table-wrap (not a bare div) -- this table builds its own <table> for
  // sortable headers rather than going through the shared table() helper,
  // which was the one thing that made it miss table()'s built-in overflow-x
  // scroll container. Without it the Symbol/Price/24H/Volume/Freshness/
  // Forecast/remove-button row is wider than a phone screen and the page
  // itself scrolls horizontally instead of just this table.
  const tableWrap = el("div", { class: "table-wrap" });
  nodes.push(tableWrap);

  let sortKey = null;
  let sortDir = 1;

  function sortValue(symbol) {
    const q = _watchlistCurrentQuote(symbol, marketBySymbol);
    if (sortKey === "price") return q.price ?? -Infinity;
    if (sortKey === "change") return q.changePct ?? -Infinity;
    if (sortKey === "volume") return q.volume ?? -Infinity;
    return symbol;
  }

  function sortHeader(label, key) {
    const th = el(
      "th",
      { style: "cursor:pointer" },
      label + (sortKey === key ? (sortDir === 1 ? " ▲" : " ▼") : "")
    );
    th.addEventListener("click", () => {
      sortDir = sortKey === key ? -sortDir : 1;
      sortKey = key;
      draw();
    });
    return th;
  }

  async function draw() {
    tableWrap.innerHTML = "";
    if (!symbols.length) {
      tableWrap.appendChild(el("p", { class: "sub" }, "Watchlist is empty -- add a symbol below."));
      return;
    }

    const forecasts = await Promise.all(symbols.map((s) => safe(`/api/forecast/${s}?horizon=24h`)));
    const forecastBySymbol = new Map(symbols.map((s, i) => [s, forecasts[i]]));

    const ordered = [...symbols];
    if (sortKey) {
      ordered.sort((a, b) => {
        const av = sortValue(a);
        const bv = sortValue(b);
        if (av < bv) return -1 * sortDir;
        if (av > bv) return 1 * sortDir;
        return 0;
      });
    }

    const t = el("table");
    t.appendChild(
      el("tr", {}, [
        el("th", {}, "Symbol"),
        sortHeader("Price", "price"),
        sortHeader("24H", "change"),
        sortHeader("Volume", "volume"),
        el("th", {}, "Freshness"),
        el("th", {}, "Forecast (24h)"),
        el("th", {}, ""),
      ])
    );
    for (const symbol of ordered) {
      const q = _watchlistCurrentQuote(symbol, marketBySymbol);
      const removeBtn = el("button", {}, "Remove");
      removeBtn.addEventListener("click", () => {
        symbols = symbols.filter((s) => s !== symbol);
        _saveWatchlistSymbols(symbols);
        draw();
      });
      t.appendChild(
        el("tr", { "data-symbol": symbol }, [
          el("td", {}, symbol),
          el("td", { class: "wl-price" }, q.price != null ? fmtNum(q.price) : "n/a"),
          el("td", { class: `wl-change ${changeClass(q.changePct)}` }, fmtPct(q.changePct)),
          el("td", { class: "wl-volume" }, q.volume != null ? fmtNum(q.volume, 0) : "n/a"),
          el("td", { class: "wl-freshness" }, dataFreshnessBadge(q.freshness, q.ageSeconds)),
          el("td", {}, _watchlistForecastCell(forecastBySymbol.get(symbol))),
          el("td", {}, removeBtn),
        ])
      );
    }
    tableWrap.appendChild(t);

    // Patches only the changed symbol's price/change/freshness cells --
    // the same pattern as Overview's liveTicker, just table rows instead
    // of cards. Re-mounted on every draw() (sort/add/remove) so it always
    // targets the DOM nodes actually on screen.
    RealtimeStore.mount({
      onTick: (dirtySymbols) => {
        for (const symbol of dirtySymbols) {
          const row = tableWrap.querySelector(`tr[data-symbol="${symbol}"]`);
          if (!row) continue;
          const q = _watchlistCurrentQuote(symbol, marketBySymbol);
          row.querySelector(".wl-price").textContent = q.price != null ? fmtNum(q.price) : "n/a";
          const changeEl = row.querySelector(".wl-change");
          changeEl.textContent = fmtPct(q.changePct);
          changeEl.className = `wl-change ${changeClass(q.changePct)}`;
          row.querySelector(".wl-volume").textContent = q.volume != null ? fmtNum(q.volume, 0) : "n/a";
          const freshnessBadge = row.querySelector(".wl-freshness .freshness-badge");
          if (freshnessBadge) freshnessBadge.replaceWith(dataFreshnessBadge(q.freshness, q.ageSeconds));
        }
      },
    });
  }
  await draw();

  const addInput = el("input", { type: "text", placeholder: "Add symbol (e.g. AAPL)" });
  const addBtn = el("button", {}, "Add to watchlist");
  const addError = el("span", { class: "error" }, "");
  addBtn.addEventListener("click", () => {
    const symbol = addInput.value.trim().toUpperCase();
    addError.textContent = "";
    if (!symbol) return;
    if (symbols.includes(symbol)) {
      addError.textContent = "Already in watchlist.";
      return;
    }
    symbols = [...symbols, symbol];
    _saveWatchlistSymbols(symbols);
    addInput.value = "";
    draw();
  });
  nodes.push(el("div", { class: "controls" }, [addInput, addBtn, addError]));

  return nodes;
}

// ---- Forecasting 2.0 --------------------------------------------------
// Deliberately visually distinct from Scanner/Watchlist: one official 24h
// forecast per asset per UTC day (app/services/forecast/engine.py's
// is_official_daily), immutable once created, automatically graded
// against real outcomes. Every number here comes straight from
// /api/forecast/official/daily and /api/forecast/{symbol}/official/history
// -- a symbol with no row yet is shown as honestly unavailable, never a
// placeholder forecast.

function forecastOutcomeLabel(f) {
  if (f.evaluated_at == null) return "PENDING";
  if (f.direction_correct == null) return "NEUTRAL";
  return f.direction_correct ? "CORRECT" : "WRONG";
}

function forecastOutcomeTone(label) {
  if (label === "CORRECT") return "good";
  if (label === "WRONG") return "bad";
  return "neutral";
}

// Root-cause fix for the "24H Forecast looks stale" bug report: this card
// used to show no computed-at/freshness signal at all, so a working
// once-per-UTC-day forecast (frozen by design, see is_official_daily's
// docstring) was visually indistinguishable from a genuinely broken/frozen
// one. `age_seconds`/`freshness`/`is_stale` come from the API's
// _with_official_freshness (same classify_freshness() the realtime price
// path uses, just with an official-forecast-scaled threshold config) --
// labels remapped here since "LIVE" would misleadingly imply a
// continuously-updating price rather than a deliberately frozen forecast.
const OFFICIAL_FRESHNESS_LABEL = {
  live: "FRESH",
  recent: "RECENT",
  delayed: "AGING",
  stale: "STALE",
  offline: "EXPIRED",
};

function officialFreshnessBadge(freshness, ageSeconds) {
  if (!freshness) return null;
  const label = OFFICIAL_FRESHNESS_LABEL[freshness] || freshness.toUpperCase();
  return el("span", { class: `freshness-badge freshness-${freshness}` }, `${label} · ${fmtAgeLong(ageSeconds)}`);
}

function forecastDailyCard(f) {
  if (!f.available) {
    return el("div", { class: "card" }, [
      el("div", { class: "label" }, f.symbol),
      el("div", { class: "value sub" }, "No official forecast yet"),
    ]);
  }
  const d = (f.direction || "").toLowerCase();
  const cls = d.includes("bullish") ? "up" : d.includes("bearish") ? "down" : "neutral";
  const isActive = !f.forecast_status || f.forecast_status.toLowerCase() === "active";
  return el("div", { class: "card" }, [
    el("div", { class: "label" }, [
      el("a", { href: `#forecast2detail?id=${f.id}` }, f.symbol),
      ` (ID ${f.id})`,
    ]),
    el("div", { class: `value ${cls}` }, `${f.direction} ${f.probability_pct}%`),
    el(
      "div",
      { class: "sub" },
      `${fmtNum(f.current_price)} -> ${fmtNum(f.target_price)} (${fmtPct(f.expected_change_pct)})`
    ),
    el("div", { class: "sub" }, [
      `Computed ${fmtAgeLong(f.age_seconds)} ago`,
      " ",
      officialFreshnessBadge(f.freshness, f.age_seconds),
    ]),
    f.calibrated_confidence_pct != null
      ? el(
          "div",
          { class: "sub" },
          `Calibrated confidence: ${f.calibrated_confidence_pct}%` +
            (f.data_quality_score != null ? ` (data quality ${f.data_quality_score}/100)` : "")
        )
      : null,
    isActive ? null : el("div", { class: "sub error" }, `Status: ${f.forecast_status}`),
  ]);
}

async function renderForecast2() {
  const nodes = [
    el("h1", {}, "Forecasting 2.0"),
    el(
      "p",
      { class: "sub" },
      "One official 24h forecast per asset per UTC day, frozen at creation and " +
        "automatically graded against real outcomes -- distinct from the intraday " +
        "AI Forecast Center on Overview."
    ),
  ];

  const daily = await safe("/api/forecast/official/daily");
  nodes.push(el("h2", {}, `Daily Forecast -- ${daily ? daily.date : "..."}`));
  if (daily && daily.next_refresh_at) {
    nodes.push(
      el(
        "p",
        { class: "sub" },
        `Next official forecast run: ${new Date(daily.next_refresh_at).toLocaleString()}`
      )
    );
  }
  if (daily && daily.forecasts.length) {
    const grid = el("div", { class: "grid" });
    for (const f of daily.forecasts) grid.appendChild(forecastDailyCard(f));
    nodes.push(grid);
  } else {
    nodes.push(el("p", { class: "error" }, "Official daily forecasts not available yet."));
  }

  nodes.push(el("h2", {}, "Forecast Table"));
  const symbols = daily ? daily.forecasts.map((f) => f.symbol) : [];
  const histories = await Promise.all(
    symbols.map((s) => safe(`/api/forecast/${s}/official/history?limit=30`))
  );
  const rows = histories
    .filter(Boolean)
    .flatMap((h) => h.forecasts)
    .sort((a, b) => (b.official_forecast_date || "").localeCompare(a.official_forecast_date || ""));

  if (rows.length) {
    nodes.push(
      table(
        ["Date", "Asset", "Price", "Direction", "Probability", "Target", "Actual", "Result"],
        rows.map((f) => [
          el("a", { href: `#forecast2detail?id=${f.id}` }, f.official_forecast_date || "n/a"),
          f.symbol,
          fmtNum(f.current_price),
          f.direction,
          `${f.probability_pct}%`,
          fmtNum(f.target_price),
          f.realized_price != null ? fmtNum(f.realized_price) : "pending",
          (() => {
            const label = forecastOutcomeLabel(f);
            return decisionPill(label, forecastOutcomeTone(label));
          })(),
        ])
      )
    );
  } else {
    nodes.push(el("p", { class: "sub" }, "No official forecasts recorded yet."));
  }

  nodes.push(
    el("p", { class: "sub nav-pointer" }, [
      "See also: ",
      el("a", { href: "#forecast2performance" }, "Performance"),
      " · ",
      el("a", { href: "#forecast2agents" }, "Agent Performance"),
      " · ",
      el("a", { href: "#forecast2errors" }, "Error Lab"),
      " · ",
      el("a", { href: "#forecast2learning" }, "Learning Center"),
    ])
  );

  return nodes;
}

// ---- Forecasting 2.0: Forecast Details (Page 3) -------------------------
// Drill-down for ONE official daily forecast, reached by clicking its date
// in the Forecast Table above: the full input snapshot (checkpoints,
// distribution, key levels, which history candle it was computed from) and
// every AgentForecast row regardless of outcome -- unlike Error Lab, which
// only shows agent evidence for calls that graded wrong.

async function renderForecastDetail(params) {
  const id = params && params.get("id");
  const nodes = [
    el("h1", {}, "Forecast Details"),
    el("p", { class: "sub nav-pointer" }, [el("a", { href: "#forecast2" }, "<- Back to Forecast Table")]),
  ];

  if (!id) {
    nodes.push(el("p", { class: "error" }, "No forecast selected."));
    return nodes;
  }

  const data = await safe(`/api/forecast/official/detail/${id}`);
  if (!data) {
    nodes.push(el("p", { class: "error" }, "That forecast could not be found."));
    return nodes;
  }

  const f = data.forecast;
  const label = forecastOutcomeLabel(f);
  nodes.push(el("h2", {}, `${f.symbol} -- ${f.official_forecast_date || "n/a"}`));
  nodes.push(el("p", { class: "sub" }, `Prediction ID: ${f.id}`));
  nodes.push(
    el("div", { class: "grid" }, [
      el("div", { class: "card" }, [
        el("div", { class: "label" }, "Call"),
        el("div", { class: "value" }, `${f.direction} ${f.probability_pct}%`),
        el("div", { class: "sub" }, decisionPill(label, forecastOutcomeTone(label))),
      ]),
      el("div", { class: "card" }, [
        el("div", { class: "label" }, "Price"),
        el("div", { class: "value" }, `${fmtNum(f.current_price)} -> ${fmtNum(f.target_price)}`),
        el(
          "div",
          { class: "sub" },
          `Actual: ${f.realized_price != null ? fmtNum(f.realized_price) : "pending"}`
        ),
      ]),
      el("div", { class: "card" }, [
        el("div", { class: "label" }, "Error / Excursions"),
        el(
          "div",
          { class: "value" },
          f.error_pct != null ? fmtPct(f.error_pct) : "pending"
        ),
        el(
          "div",
          { class: "sub" },
          `MFE ${f.max_favorable_excursion_pct != null ? fmtPct(f.max_favorable_excursion_pct) : "n/a"} ` +
            `/ MAE ${f.max_adverse_excursion_pct != null ? fmtPct(f.max_adverse_excursion_pct) : "n/a"}`
        ),
      ]),
      el("div", { class: "card" }, [
        el("div", { class: "label" }, "Regime / Status"),
        el("div", { class: "value" }, f.regime_at_forecast || "n/a"),
        el("div", { class: "sub" }, `${f.forecast_status}${f.error_type ? ` -- ${f.error_type}` : ""}`),
      ]),
      el("div", { class: "card" }, [
        el("div", { class: "label" }, "Calibrated Confidence"),
        el(
          "div",
          { class: "value" },
          f.calibrated_confidence_pct != null ? `${f.calibrated_confidence_pct}%` : "n/a"
        ),
        el(
          "div",
          { class: "sub" },
          `Data quality: ${f.data_quality_score != null ? `${f.data_quality_score}/100` : "n/a"} ` +
            `(stated ${f.confidence_tier || "n/a"})`
        ),
      ]),
      el("div", { class: "card" }, [
        el("div", { class: "label" }, "CRPS"),
        el("div", { class: "value" }, f.crps_pct != null ? fmtPct(f.crps_pct) : "n/a"),
        el(
          "div",
          { class: "sub" },
          "Proper scoring rule over the full P10-P90 distribution, not just the point error"
        ),
      ]),
    ])
  );

  const q = f.forward_return_quantiles;
  if (q && q.p50_pct != null) {
    nodes.push(el("h2", {}, "Forecast Distribution (P10-P90)"));
    nodes.push(
      el("div", { class: "grid" }, [
        card("P10", fmtPct(q.p10_pct)),
        card("P25", fmtPct(q.p25_pct)),
        card("P50 (Median)", fmtPct(q.p50_pct)),
        card("P75", fmtPct(q.p75_pct)),
        card("P90", fmtPct(q.p90_pct)),
      ])
    );
  }

  nodes.push(el("h2", {}, "Input Snapshot"));
  nodes.push(
    el("ul", { class: "structured-list" }, [
      el("li", {}, `Reference candle: ${f.reference_timestamp || "n/a"}`),
      el("li", {}, `Computed at: ${f.computed_at}`),
      el("li", {}, `Forecast version: ${f.forecast_version}`),
      el("li", {}, `Model version: ${f.model_version || "n/a (predates model_version tracking)"}`),
      el(
        "li",
        {},
        `Key levels: ${
          f.key_levels && Object.keys(f.key_levels).length
            ? Object.entries(f.key_levels)
                .map(([k, v]) => `${k}=${v}`)
                .join(", ")
            : "n/a"
        }`
      ),
      el(
        "li",
        {},
        `Checkpoints: ${
          f.checkpoints && f.checkpoints.length
            ? f.checkpoints.map((c) => JSON.stringify(c)).join(" | ")
            : "n/a"
        }`
      ),
      el(
        "li",
        {},
        `Distribution: ${
          f.distribution && f.distribution.length
            ? f.distribution.map((c) => JSON.stringify(c)).join(" | ")
            : "n/a"
        }`
      ),
    ])
  );

  if (f.invalidation_reason) {
    nodes.push(el("h2", {}, "Invalidation"));
    nodes.push(
      el(
        "p",
        { class: "sub" },
        `${f.invalidation_reason} (at ${f.invalidated_at || "n/a"})`
      )
    );
  }

  nodes.push(el("h2", {}, "Baseline Comparisons"));
  nodes.push(
    el("ul", { class: "structured-list" }, [
      el(
        "li",
        {},
        `Momentum baseline (naive "last move continues"): ${
          f.momentum_baseline_correct == null ? "not graded yet" : f.momentum_baseline_correct ? "correct" : "wrong"
        }`
      ),
      el(
        "li",
        {},
        `Historical-mean baseline error: ${
          f.historical_mean_baseline_error_pct != null
            ? fmtPct(f.historical_mean_baseline_error_pct)
            : "not graded yet"
        }`
      ),
      el(
        "li",
        {},
        `Zero-return baseline (naive "assume no change") error: ${
          f.zero_return_baseline_error_pct != null
            ? fmtPct(f.zero_return_baseline_error_pct)
            : "not graded yet"
        }`
      ),
      el(
        "li",
        {},
        `Regime-mean baseline (naive "same regime, historical average") error: ${
          f.regime_mean_baseline_error_pct != null
            ? fmtPct(f.regime_mean_baseline_error_pct)
            : "not graded yet"
        }`
      ),
    ])
  );

  nodes.push(el("h2", {}, "Per-Agent Evidence"));
  if (data.agents.length) {
    nodes.push(
      table(
        ["Agent", "Direction", "Confidence"],
        data.agents.map((a) => [
          a.agent_name,
          a.direction || "n/a",
          a.confidence_pct != null ? `${a.confidence_pct}%` : "n/a",
        ])
      )
    );
  } else {
    nodes.push(el("p", { class: "sub" }, "No per-agent evidence recorded for this forecast."));
  }

  return nodes;
}

// ---- Forecasting 2.0: Performance (Page 4) -------------------------------
// The overall (not per-agent) scorecard: summary stats, a probability-
// calibration curve, and accuracy by regime, across every graded official
// daily forecast. Every bucket/group below its own configured minimum
// sample size is shown as INSUFFICIENT SAMPLE rather than a number -- same
// rule as Agent Performance/Learning Center, applied to a coarser grouping.

function forecastPerformanceSummaryCards(s) {
  return el("div", { class: "grid" }, [
    el("div", { class: "card" }, [
      el("div", { class: "label" }, "Graded Forecasts"),
      el("div", { class: "value" }, String(s.graded_count)),
    ]),
    el("div", { class: "card" }, [
      el("div", { class: "label" }, "Direction Accuracy"),
      el(
        "div",
        { class: `value ${changeClass(s.direction_accuracy_pct - 50)}` },
        `${s.direction_accuracy_pct}%${fmtCI(s.direction_accuracy_ci)}`
      ),
    ]),
    el("div", { class: "card" }, [
      el("div", { class: "label" }, "Avg |Error| (MAE)"),
      el("div", { class: "value" }, s.avg_abs_error_pct != null ? fmtPct(s.avg_abs_error_pct) : "n/a"),
    ]),
    el("div", { class: "card" }, [
      el("div", { class: "label" }, "RMSE"),
      el("div", { class: "value" }, s.rmse_pct != null ? fmtPct(s.rmse_pct) : "n/a"),
    ]),
    el("div", { class: "card" }, [
      el("div", { class: "label" }, "Target Reached Rate"),
      el(
        "div",
        { class: "value" },
        s.target_reached_rate_pct != null ? `${s.target_reached_rate_pct}%` : "n/a"
      ),
    ]),
  ]);
}

async function renderForecastPerformance() {
  const nodes = [
    el("h1", {}, "Performance"),
    el(
      "p",
      { class: "sub" },
      "Overall accuracy and calibration across every graded official daily forecast -- " +
        "the top-level scorecard, distinct from the per-agent breakdown on Agent Performance."
    ),
  ];

  const windowLabels = { "7d": "7D", "30d": "30D", "90d": "90D", all: "ALL" };
  const windowRow = el("div", { class: "forecast-tabs" });
  nodes.push(windowRow);
  const results = el("div");
  nodes.push(results);

  async function load(window) {
    windowRow.innerHTML = "";
    Object.entries(windowLabels).forEach(([key, label]) => {
      const btn = el("button", { class: `forecast-tab${key === window ? " active" : ""}` }, label);
      btn.addEventListener("click", () => load(key));
      windowRow.appendChild(btn);
    });
    results.innerHTML = "";
    const data = await safe(`/api/forecast/official/performance?window=${window}`);
    if (!data || !data.summary || data.summary.graded_count === 0) {
      results.appendChild(
        el(
          "p",
          { class: "sub" },
          "No graded official daily forecasts yet in this window -- this page fills in as forecasts resolve."
        )
      );
      return;
    }

    results.appendChild(el("h2", {}, "Overall"));
    results.appendChild(forecastPerformanceSummaryCards(data.summary));

    const bySymbol = data.by_symbol || {};
    const symbols = Object.keys(bySymbol).sort();
    if (symbols.length) {
      results.appendChild(el("h2", {}, "By Asset"));
      for (const symbol of symbols) {
        const s = bySymbol[symbol];
        if (s.graded_count === 0) continue;
        results.appendChild(el("h3", {}, symbol));
        results.appendChild(forecastPerformanceSummaryCards(s));
      }
    }

    results.appendChild(el("h2", {}, "Calibration Curve"));
    if (data.calibration.length) {
      results.appendChild(
        table(
          ["Stated Probability", "Count", "Avg Stated", "Observed Accuracy", "Gap", "Sufficiency"],
          data.calibration.map((b) => [
            b.probability_bucket,
            String(b.count),
            `${b.avg_stated_probability_pct}%`,
            `${b.observed_accuracy_pct}%`,
            fmtPct(b.calibration_gap_pct),
            decisionPill(
              b.sample_sufficiency.toUpperCase(),
              b.sample_sufficiency === "reliable" ? "good" : b.sample_sufficiency === "usable" ? "neutral" : "bad"
            ),
          ])
        )
      );
    } else {
      results.appendChild(el("p", { class: "sub" }, "No calibration buckets yet."));
    }

    results.appendChild(el("h2", {}, "Accuracy By Regime"));
    if (data.regime_breakdown.length) {
      results.appendChild(
        table(
          ["Regime", "Sample Size", "Accuracy"],
          data.regime_breakdown.map((r) => [
            r.regime,
            String(r.sample_size),
            r.insufficient_sample
              ? decisionPill("INSUFFICIENT SAMPLE", "neutral")
              : el(
                  "span",
                  { class: changeClass(r.accuracy_pct - 50) },
                  `${r.accuracy_pct}%${fmtCI(r.accuracy_ci)}`
                ),
          ])
        )
      );
    } else {
      results.appendChild(el("p", { class: "sub" }, "No regime-tagged graded forecasts yet."));
    }

    results.appendChild(el("h2", {}, "Quantile Coverage Validation"));
    results.appendChild(
      el(
        "p",
        { class: "sub" },
        "Does the realized return actually fall inside the forecast's own stated band as often as the band's width implies it should?"
      )
    );
    const coverage = data.quantile_coverage;
    if (coverage && (coverage.p10_p90.sample_size > 0 || coverage.p25_p75.sample_size > 0)) {
      results.appendChild(
        table(
          ["Band", "Expected Coverage", "Sample Size", "Observed Coverage", "Gap", "Sufficiency"],
          [
            ["P10-P90", coverage.p10_p90],
            ["P25-P75", coverage.p25_p75],
          ].map(([label, c]) => [
            label,
            `${c.expected_coverage_pct}%`,
            String(c.sample_size),
            c.observed_coverage_pct != null ? `${c.observed_coverage_pct}%` : "n/a",
            c.coverage_gap_pct != null ? fmtPct(c.coverage_gap_pct) : "n/a",
            decisionPill(
              c.sample_sufficiency.toUpperCase(),
              c.sample_sufficiency === "reliable" ? "good" : c.sample_sufficiency === "usable" ? "neutral" : "bad"
            ),
          ])
        )
      );
    } else {
      results.appendChild(el("p", { class: "sub" }, "No graded forecasts with a persisted quantile band yet."));
    }
  }

  await load("all");
  return nodes;
}

// ---- Forecasting 2.0: Agent Performance (Part 26 / Page 5) -------------
// Direction accuracy per (agent, symbol), conditioned on the agent
// actually having real data on a graded official daily forecast -- every
// AgentForecast row mirrors its parent's own direction (there is no
// independent per-agent direction call in this data model), so this is
// "how often was the roster's call right when this source had data,"
// not a claim the agent alone drove the outcome. Groups below the
// server's own configured minimum sample size are shown as
// INSUFFICIENT SAMPLE, never a number.

async function renderForecastAgents() {
  const nodes = [
    el("h1", {}, "Agent Performance"),
    el(
      "p",
      { class: "sub" },
      "Direction accuracy per data source, conditioned on that source actually " +
        "having real data on a graded official daily forecast."
    ),
  ];

  const data = await safe("/api/forecast/official/agent-performance");
  if (data && data.rows.length) {
    nodes.push(
      table(
        ["Agent", "Asset", "Sample Size", "Accuracy"],
        data.rows.map((r) => [
          r.agent_name,
          r.symbol,
          String(r.sample_size),
          r.insufficient_sample
            ? decisionPill(`INSUFFICIENT SAMPLE (min ${data.min_sample_size})`, "neutral")
            : el("span", { class: changeClass(r.accuracy_pct - 50) }, `${r.accuracy_pct}%`),
        ])
      )
    );
  } else {
    nodes.push(
      el(
        "p",
        { class: "sub" },
        "No graded official daily forecasts yet -- accuracy accumulates as forecasts resolve."
      )
    );
  }

  return nodes;
}

// ---- Forecasting 2.0: Error Lab (Part 27/28 / Page 6) -------------------
// The most recent official daily forecasts that graded WRONG, each with
// its linked per-agent evidence -- "what each source said when we got
// this wrong." error_type is a coarse, honestly-derivable classification
// (see classify_error_type's own docstring), never a fabricated root
// cause beyond what the graded fields can actually support.

function errorLabEntryCard(entry) {
  const f = entry.forecast;
  const agentRows = entry.agents.length
    ? el(
        "ul",
        { class: "structured-list" },
        entry.agents.map((a) =>
          el(
            "li",
            {},
            `${a.agent_name}: ${a.confidence_pct != null ? a.confidence_pct + "%" : "n/a"}`
          )
        )
      )
    : el("p", { class: "sub" }, "No per-agent evidence recorded for this forecast.");

  return el("div", { class: "card" }, [
    el(
      "div",
      { class: "label" },
      el("a", { href: `#forecast2detail?id=${f.id}` }, `${f.symbol} -- ${f.official_forecast_date || "n/a"}`)
    ),
    el(
      "div",
      { class: "value down" },
      `${f.direction} ${f.probability_pct}% -> actual ${
        f.realized_price != null ? fmtNum(f.realized_price) : "pending"
      }`
    ),
    el(
      "div",
      { class: "sub" },
      `Error: ${f.error_pct != null ? fmtPct(f.error_pct) : "n/a"} | ` +
        `MFE: ${f.max_favorable_excursion_pct != null ? fmtPct(f.max_favorable_excursion_pct) : "n/a"} | ` +
        `MAE: ${f.max_adverse_excursion_pct != null ? fmtPct(f.max_adverse_excursion_pct) : "n/a"}`
    ),
    decisionPill(f.error_type || "UNCLASSIFIED", "bad"),
    el("div", { class: "sub" }, "Agent evidence at forecast time:"),
    agentRows,
  ]);
}

async function renderForecastErrorLab() {
  const nodes = [
    el("h1", {}, "Error Lab"),
    el(
      "p",
      { class: "sub" },
      "The most recent official daily forecasts that graded wrong, with the real " +
        "per-agent evidence recorded at the moment each forecast was made."
    ),
  ];

  const data = await safe("/api/forecast/official/error-lab?limit=20");
  if (data && data.entries.length) {
    const grid = el("div", { class: "grid" });
    for (const entry of data.entries) grid.appendChild(errorLabEntryCard(entry));
    nodes.push(grid);
  } else {
    nodes.push(
      el("p", { class: "sub" }, "No wrong official daily forecasts recorded yet.")
    );
  }

  return nodes;
}

// ---- Forecasting 2.0: Learning Center (Part 33 / Page 7) ----------------
// The one insight this data model can honestly support: does an agent's
// realized accuracy differ between two market regimes it's actually been
// graded in? Every statement here is a plain description of two observed
// rates (correlational, never causal) and only appears once both regimes
// clear the server's own configured sample-size floor -- see
// derive_learning_insights's docstring. No LLM narrative, no invented
// insight: a symbol with nothing to show says so honestly.

async function renderForecastLearningCenter() {
  const nodes = [
    el("h1", {}, "Learning Center"),
    el(
      "p",
      { class: "sub" },
      "What the system has learned so far, based only on accumulated statistics -- " +
        "an insight only appears once both regimes being compared have enough graded " +
        "forecasts, never a guess."
    ),
  ];

  const data = await safe("/api/forecast/official/learning-center");
  const symbols = data ? Object.keys(data.by_symbol).sort() : [];
  if (symbols.length) {
    for (const symbol of symbols) {
      nodes.push(el("h2", {}, symbol));
      nodes.push(
        el(
          "ul",
          { class: "structured-list" },
          data.by_symbol[symbol].map((i) => el("li", {}, i.statement))
        )
      );
    }
  } else {
    const minSample = data ? data.min_sample_size : "?";
    const minGap = data ? data.min_gap_pct : "?";
    nodes.push(
      el(
        "p",
        { class: "sub" },
        `Not enough graded official forecasts yet across at least two regimes ` +
          `(needs >= ${minSample} graded forecasts in each regime and a >= ${minGap} ` +
          `percentage-point accuracy gap between them before anything is shown here).`
      )
    );
  }

  return nodes;
}

async function renderConsensus() {
  const data = await safe("/api/consensus");
  const nodes = [el("h2", {}, "Consensus")];
  if (!data) {
    nodes.push(
      el("p", { class: "error" }, "No agent reported a direction this cycle -- nothing to tally yet.")
    );
    return nodes;
  }
  nodes.push(
    el("div", { class: "grid" }, [
      card("Bullish", `${data.bullish_pct}%`, null, "up"),
      card("Bearish", `${data.bearish_pct}%`, null, "down"),
      card("Neutral", `${data.neutral_pct}%`),
    ])
  );
  nodes.push(
    el("div", { class: "grid" }, [
      scoreBar("Agreement", data.agreement_score),
      scoreBar("Conflict", data.conflict_pct),
    ])
  );
  if (data.strongest_agent) {
    const weight = data.agent_weights[data.strongest_agent];
    nodes.push(
      el("p", { class: "sub" }, `Strongest influence: ${data.strongest_agent} (${weight}% of vote weight)`)
    );
  }
  if (data.confidence_evolution) {
    nodes.push(el("p", { class: "sub" }, `Confidence evolution: ${data.confidence_evolution.summary}`));
  }
  nodes.push(
    table(
      ["Direction", "Agents"],
      [
        ["Bullish", el("span", { class: "up" }, data.bullish_agents.join(", ") || "none")],
        ["Bearish", el("span", { class: "down" }, data.bearish_agents.join(", ") || "none")],
        ["Neutral", data.neutral_agents.join(", ") || "none"],
      ]
    )
  );
  if (data.unavailable_agents.length) {
    nodes.push(el("p", { class: "sub" }, `No data this cycle: ${data.unavailable_agents.join(", ")}`));
  }
  if (data.invalidation_risk) {
    nodes.push(el("h2", {}, "Invalidation Risk"));
    nodes.push(el("p", {}, data.invalidation_risk));
  }
  nodes.push(navPointer("consensus"));
  return nodes;
}

async function renderCommittee() {
  const data = await safe("/api/committee");
  const nodes = [el("h2", {}, "AI Investment Committee")];
  if (!data) {
    nodes.push(
      el("p", { class: "error" }, "No agent reported a direction this cycle -- the committee has nothing to vote on.")
    );
    return nodes;
  }
  nodes.push(
    el("div", { class: "grid" }, [
      card("Final Recommendation", data.final_recommendation),
      card("Majority", `${data.majority_decision} (${data.majority_pct}%)`),
      card("Dissent", `${data.dissent_pct}%`),
      card("Confidence", `${data.confidence_pct}%`),
    ])
  );
  nodes.push(decisionPill(data.final_recommendation, recommendationTone(data.final_recommendation)));
  nodes.push(el("p", {}, data.reasoning));
  if (data.most_influential_agent) {
    nodes.push(el("p", { class: "sub" }, `Final influence: ${data.most_influential_agent}`));
  }
  if (data.supporting_evidence.length) {
    nodes.push(el("h2", {}, "Supporting Evidence"));
    nodes.push(
      table(
        ["Agent", "Confidence", "Weight", "Evidence"],
        data.supporting_evidence.map((e) => [
          e.agent,
          e.confidence != null ? `${e.confidence}%` : "n/a",
          e.weight != null ? `${e.weight}%` : "n/a",
          e.evidence,
        ])
      )
    );
  }
  if (data.opposing_evidence.length) {
    nodes.push(el("h2", {}, "Opposing Evidence (Minority)"));
    nodes.push(
      table(
        ["Agent", "Confidence", "Weight", "Evidence"],
        data.opposing_evidence.map((e) => [
          e.agent,
          e.confidence != null ? `${e.confidence}%` : "n/a",
          e.weight != null ? `${e.weight}%` : "n/a",
          e.evidence,
        ])
      )
    );
  }
  if (data.invalidation_risk) {
    nodes.push(el("h2", {}, "Invalidation Risk"));
    nodes.push(el("p", {}, data.invalidation_risk));
  }
  nodes.push(navPointer("committee"));
  return nodes;
}

async function renderTerminal() {
  const nodes = [el("h2", {}, "Terminal Brief")];
  const data = await safe("/api/terminal/brief");
  if (!data) {
    nodes.push(el("p", { class: "error" }, "Not enough data yet to assemble a brief."));
  } else {
    nodes.push(
      el("div", { class: "grid" }, [
        card("Regime", (data.regime || "unknown").replace(/_/g, " ")),
        card("Health", data.health_score ?? "n/a"),
        data.risk ? card("Risk-off", `${data.risk.risk_off_score}/100`) : card("Risk-off", "n/a"),
        data.risk ? card("Liquidity", `${data.risk.liquidity_score}/100`) : card("Liquidity", "n/a"),
      ])
    );
    if (data.committee) {
      nodes.push(el("h2", {}, "Committee"));
      nodes.push(
        card(
          data.committee.final_recommendation,
          `Majority ${data.committee.majority_decision} (${data.committee.majority_pct}%) | Dissent ${data.committee.dissent_pct}%`,
          data.committee.reasoning
        )
      );
    }
    if (data.top_opportunities.length) {
      nodes.push(el("h2", {}, "Top Opportunities"));
      nodes.push(
        table(
          ["Symbol", "Classification", "Score"],
          data.top_opportunities.map((o) => [
            o.symbol,
            el("span", { class: o.classification === "bullish" ? "up" : o.classification === "bearish" ? "down" : "neutral" }, o.classification),
            `${o.opportunity_score}/100`,
          ])
        )
      );
    }
    nodes.push(el("h2", {}, "Portfolio"));
    nodes.push(
      el("p", { class: "sub" }, data.portfolio.empty ? "No positions held." : `Health ${data.portfolio.health_score}/100, value ${Number(data.portfolio.total_value).toLocaleString()}`)
    );

    if (data.consensus) {
      nodes.push(el("h2", {}, "Consensus"));
      nodes.push(
        el(
          "p",
          { class: "sub" },
          `Bullish ${data.consensus.bullish_pct}% / Bearish ${data.consensus.bearish_pct}% / ` +
            `Neutral ${data.consensus.neutral_pct}% (conflict ${data.consensus.conflict_pct}%)`
        )
      );
    }

    if (data.watchdog) {
      nodes.push(el("h2", {}, "Watchdog"));
      const sub = [
        data.watchdog.highest_risk ? `Highest risk: ${data.watchdog.highest_risk}` : null,
        data.watchdog.biggest_opportunity ? `Biggest opportunity: ${data.watchdog.biggest_opportunity}` : null,
      ]
        .filter(Boolean)
        .join(" | ");
      nodes.push(card("Market Health", data.watchdog.market_health || "unknown", sub));
    }

    if (data.scanner && data.scanner.breadth) {
      nodes.push(el("h2", {}, "Scanner"));
      nodes.push(
        el("div", { class: "grid" }, [
          card("Rising", data.scanner.breadth.rising_count),
          card("Falling", data.scanner.breadth.falling_count),
          card("Scanned", data.scanner.breadth.total_scanned),
          card("Active Alerts", data.scanner.active_alerts_count),
        ])
      );
    }

    if (data.historical_intelligence) {
      const h = data.historical_intelligence.summary;
      nodes.push(el("h2", {}, "Historical Intelligence"));
      nodes.push(
        el("p", { class: "sub" }, `Most similar setup: ${h.symbol} (${h.similarity_score}% similar)`)
      );
    }
  }

  nodes.push(el("h2", {}, "Historical Comparison"));
  const daysInput = el("input", { type: "number", value: "7", min: "1", style: "width:80px" });
  const historyBtn = el("button", {}, "Compare");
  nodes.push(el("div", { class: "controls" }, [daysInput, historyBtn]));
  const historyResults = el("div");
  nodes.push(historyResults);
  historyBtn.addEventListener("click", async () => {
    historyResults.innerHTML = "";
    try {
      const cmp = await fetchJSON(`/api/terminal/history?days=${encodeURIComponent(daysInput.value)}`);
      historyResults.appendChild(renderStructured(cmp.diff));
    } catch (err) {
      historyResults.appendChild(errorBox(err));
    }
  });

  nodes.push(el("h2", {}, "Weekly / Monthly Performance"));
  const weeklyBtn = el("button", {}, "Weekly Review");
  const monthlyBtn = el("button", {}, "Monthly Performance");
  nodes.push(el("div", { class: "controls" }, [weeklyBtn, monthlyBtn]));
  const periodResults = el("div");
  nodes.push(periodResults);
  async function loadPeriod(path) {
    periodResults.innerHTML = "";
    try {
      const result = await fetchJSON(path);
      periodResults.appendChild(
        el("div", { class: "grid" }, [
          card("Evaluated predictions", result.evaluated_predictions),
          card("Accuracy", result.accuracy_pct !== null ? `${result.accuracy_pct}%` : "n/a"),
          card("Alerts logged", result.alerts_count),
        ])
      );
      if (result.historical_comparison) {
        periodResults.appendChild(renderStructured(result.historical_comparison.diff));
      }
    } catch (err) {
      periodResults.appendChild(errorBox(err));
    }
  }
  weeklyBtn.addEventListener("click", () => loadPeriod("/api/terminal/weekly"));
  monthlyBtn.addEventListener("click", () => loadPeriod("/api/terminal/monthly"));

  return nodes;
}

async function renderMacro() {
  const [agents, market, sentiment] = await Promise.all([
    safe("/api/agents"),
    safe("/api/market"),
    safe("/api/sentiment"),
  ]);
  const nodes = [el("h2", {}, "Macro")];
  if (!agents || !agents.macro) {
    nodes.push(el("p", { class: "error" }, "Macro agent unavailable."));
    return nodes;
  }

  // Cross-references MacroAgent's own DXY/Gold/Silver/Oil/VIX/US10Y/US30Y/
  // FedRate reads with equity indices and BTC dominance already collected
  // by the market aggregator, and Fear & Greed already computed by
  // SentimentEngine -- no new computation, just one combined table instead
  // of three separate page visits.
  const quotesBySymbol = {};
  for (const q of (market && market.quotes) || []) quotesBySymbol[q.symbol] = q;

  const rows = [];
  for (const [symbol, a] of Object.entries(agents.macro.data.assets || {})) {
    if (a) {
      rows.push([
        symbol,
        fmtNum(a.price),
        el("span", { class: changeClass(a.change_pct_24h) }, fmtPct(a.change_pct_24h)),
      ]);
    }
  }
  for (const symbol of ["SPX", "NASDAQ", "DJI"]) {
    const q = quotesBySymbol[symbol];
    if (q) {
      rows.push([
        symbol,
        fmtNum(q.price),
        el("span", { class: changeClass(q.change_pct_24h) }, fmtPct(q.change_pct_24h)),
      ]);
    }
  }
  const btcDominance = quotesBySymbol["BTC.D"];
  if (btcDominance) {
    rows.push(["BTC Dominance", `${fmtNum(btcDominance.price)}%`, "--"]);
  }
  if (sentiment && sentiment.fear_greed_classification) {
    rows.push([
      "Fear & Greed",
      sentiment.fear_greed_value != null ? String(sentiment.fear_greed_value) : "n/a",
      sentiment.fear_greed_classification,
    ]);
  }
  if (rows.length) {
    nodes.push(table(["Instrument", "Value", "24h % / Reading"], rows));
  }

  nodes.push(el("h3", {}, "AI Interpretation"));
  nodes.push(el("p", {}, agents.macro.data.liquidity_analysis));
  nodes.push(el("p", {}, agents.macro.data.risk_assessment));
  nodes.push(el("p", { class: "sub" }, agents.macro.data.note));
  return nodes;
}

async function renderCrypto() {
  const agents = await safe("/api/agents");
  const nodes = [el("h2", {}, "Crypto")];
  if (agents && agents.crypto) {
    nodes.push(el("pre", { class: "summary" }, agents.crypto.summary));
  } else {
    nodes.push(el("p", { class: "error" }, "Crypto agent unavailable."));
  }
  return nodes;
}

async function renderStocks() {
  const agents = await safe("/api/agents");
  const nodes = [el("h2", {}, "Stocks")];
  if (agents && agents.equity) {
    nodes.push(el("pre", { class: "summary" }, agents.equity.summary));
    nodes.push(el("p", { class: "sub" }, agents.equity.data.unavailable_reason));
  } else {
    nodes.push(el("p", { class: "error" }, "Equity agent unavailable."));
  }
  return nodes;
}

async function renderCorrelations() {
  const data = await safe("/api/correlations");
  const nodes = [el("h2", {}, "Correlations")];
  if (!data || !data.correlations.length) {
    nodes.push(el("p", { class: "error" }, "No correlation data available yet."));
    return nodes;
  }
  nodes.push(
    table(
      ["Pair", "Window", "Correlation", "Data points"],
      data.correlations.map((c) => [
        `${c.symbol_a}/${c.symbol_b}`,
        `${c.window_days}d`,
        heatCell(c.correlation, c.correlation.toFixed(2)),
        String(c.data_points),
      ])
    )
  );
  return nodes;
}

async function renderNews() {
  const nodes = [el("h2", {}, "News")];
  const data = await safe("/api/news?limit=30");
  if (!data || !data.items.length) {
    nodes.push(el("p", { class: "error" }, "No news collected yet."));
    return nodes;
  }
  nodes.push(
    table(
      ["Time", "Category", "Sentiment", "Impact", "Title", "Source"],
      data.items.map((n) => [
        n.published_at ? n.published_at.slice(0, 16).replace("T", " ") : "n/a",
        n.category,
        el(
          "span",
          { class: n.sentiment === "bullish" ? "up" : n.sentiment === "bearish" ? "down" : "neutral" },
          n.sentiment
        ),
        decisionPill(n.impact, n.impact === "high" ? "bad" : n.impact === "medium" ? "neutral" : "good"),
        el("a", { href: n.url, target: "_blank", rel: "noopener" }, n.title),
        n.source,
      ])
    )
  );
  return nodes;
}

async function renderHistory(params) {
  const nodes = [el("h2", {}, "History")];
  const symbolInput = el("input", {
    type: "text",
    value: (params && params.get("symbol")) || "BTC",
    placeholder: "Symbol",
  });
  const tfSelect = el("select", {}, ["1d", "4h", "1h"].map((t) => el("option", { value: t }, t)));
  const btn = el("button", {}, "Load");
  nodes.push(el("div", { class: "controls" }, [symbolInput, tfSelect, btn]));
  const results = el("div");
  nodes.push(results);

  async function load() {
    results.innerHTML = "";
    results.appendChild(el("p", { class: "loading" }, "Loading..."));
    try {
      const data = await fetchJSON(
        `/api/history/${encodeURIComponent(symbolInput.value)}?timeframe=${tfSelect.value}&limit=120`
      );
      results.innerHTML = "";
      results.appendChild(svgLineChart(data.candles.map((c) => c.close)));
      results.appendChild(
        table(
          ["Date", "Close", "Change", "RSI", "SMA 50", "SMA 200"],
          data.candles
            .slice(-20)
            .reverse()
            .map((c) => [
              c.timestamp.slice(0, 10),
              fmtNum(c.close),
              el(
                "span",
                { class: changeClass(c.return_pct) },
                fmtPct(c.return_pct != null ? c.return_pct * 100 : null)
              ),
              c.rsi != null ? c.rsi.toFixed(1) : "n/a",
              c.sma_50 != null ? fmtNum(c.sma_50) : "n/a",
              c.sma_200 != null ? fmtNum(c.sma_200) : "n/a",
            ])
        )
      );
    } catch (err) {
      results.innerHTML = "";
      results.appendChild(errorBox(err));
    }
  }
  btn.addEventListener("click", load);
  load();
  return nodes;
}

async function renderEvents() {
  const nodes = [el("h2", {}, "Historical Events")];
  const data = await safe("/api/events");
  if (data && data.events.length) {
    nodes.push(
      table(
        ["Date", "Title", "Category", "Symbols"],
        data.events.map((e) => [
          e.event_date.slice(0, 10),
          e.title,
          e.category,
          (e.symbols_affected || []).join(", ") || "n/a",
        ])
      )
    );
  } else {
    nodes.push(el("p", { class: "error" }, "No historical events seeded yet."));
  }

  nodes.push(el("h2", {}, "Event Impact"));
  const catInput = el("input", { type: "text", value: "cpi", placeholder: "Event category" });
  const symInput = el("input", { type: "text", value: "BTC", placeholder: "Symbol" });
  const btn = el("button", {}, "Measure");
  nodes.push(el("div", { class: "controls" }, [catInput, symInput, btn]));
  const results = el("div");
  nodes.push(results);
  btn.addEventListener("click", async () => {
    results.innerHTML = "";
    try {
      const r = await fetchJSON(
        `/api/events/impact?category=${encodeURIComponent(catInput.value)}&symbol=${encodeURIComponent(symInput.value)}`
      );
      results.appendChild(
        table(
          ["Event date", "Immediate", "24h", "7d", "30d"],
          r.events.map((ev) => [
            ev.event_date.slice(0, 10),
            fmtPct(ev.immediate_pct != null ? ev.immediate_pct * 100 : null),
            fmtPct(ev.return_24h_pct != null ? ev.return_24h_pct * 100 : null),
            fmtPct(ev.return_7d_pct != null ? ev.return_7d_pct * 100 : null),
            fmtPct(ev.return_30d_pct != null ? ev.return_30d_pct * 100 : null),
          ])
        )
      );
    } catch (err) {
      results.appendChild(errorBox(err));
    }
  });
  return nodes;
}

async function renderPatterns() {
  const nodes = [el("h2", {}, "Patterns")];
  const symbolInput = el("input", { type: "text", value: "BTC", placeholder: "Symbol" });
  const tfSelect = el("select", {}, ["1d", "4h", "1h"].map((t) => el("option", { value: t }, t)));
  const btn = el("button", {}, "Load");
  nodes.push(el("div", { class: "controls" }, [symbolInput, tfSelect, btn]));
  const results = el("div");
  nodes.push(results);

  async function load() {
    results.innerHTML = "";
    try {
      const data = await fetchJSON(
        `/api/patterns/${encodeURIComponent(symbolInput.value)}?timeframe=${tfSelect.value}&limit=20`
      );
      results.innerHTML = "";
      if (!data.patterns.length) {
        results.appendChild(el("p", { class: "error" }, `No patterns detected yet for ${data.symbol}.`));
        return;
      }
      results.appendChild(
        table(
          ["Date", "Pattern", "Direction"],
          data.patterns.map((p) => [
            p.timestamp.slice(0, 10),
            p.pattern_name.replace(/_/g, " "),
            el(
              "span",
              { class: p.direction === "bullish" ? "up" : p.direction === "bearish" ? "down" : "neutral" },
              p.direction
            ),
          ])
        )
      );
    } catch (err) {
      results.innerHTML = "";
      results.appendChild(errorBox(err));
    }
  }
  btn.addEventListener("click", load);
  load();
  return nodes;
}

async function renderLiquidity() {
  const data = await safe("/api/liquidity");
  const nodes = [el("h2", {}, "Liquidity")];
  if (!data) {
    nodes.push(
      el("p", { class: "error" }, "Not enough data yet -- run regime detection and signal scoring first.")
    );
    return nodes;
  }
  nodes.push(
    el("div", { class: "grid" }, [
      scoreBar("Liquidity", data.liquidity_score),
      scoreBar("Macro Pressure", data.macro_pressure_score),
      scoreBar("Risk-On", data.risk_on_score),
      scoreBar("Risk-Off", data.risk_off_score),
    ])
  );
  nodes.push(el("h2", {}, "Inputs"));
  nodes.push(
    table(
      ["Input", "Value"],
      Object.entries(data.inputs).map(([k, v]) => [k.replace(/_/g, " "), v != null ? fmtNum(v, 4) : "n/a"])
    )
  );
  return nodes;
}

async function renderRisk() {
  const data = await safe("/api/risk");
  const nodes = [el("h2", {}, "Risk")];
  if (!data) {
    nodes.push(el("p", { class: "error" }, "Not enough data yet."));
    return nodes;
  }
  if (data.risk_level) {
    nodes.push(
      el("p", {}, [
        "Risk level: ",
        decisionPill(data.risk_level.toUpperCase(), riskLevelTone(data.risk_level)),
        el("span", { class: "sub" }, " -- from the detected market regime"),
      ])
    );
  }
  if (data.global_score) {
    nodes.push(
      el("div", { class: "grid" }, [
        scoreBar("Risk-Off", data.global_score.risk_off_score),
        scoreBar("Risk-On", data.global_score.risk_on_score),
        scoreBar("Fear", data.global_score.fear_score),
        scoreBar("Macro Pressure", data.global_score.macro_pressure_score),
        scoreBar("Risk Score", data.global_score.risk_score),
        scoreBar("Confidence", data.global_score.confidence_score),
      ])
    );
  } else {
    nodes.push(el("p", { class: "sub" }, "Global Score not computed yet -- run /score first."));
  }
  nodes.push(el("h2", {}, "Signal Conviction"));
  if (data.signal_conviction) {
    const sc = data.signal_conviction;
    nodes.push(
      el("div", { class: "grid" }, [
        card("Tier", sc.tier),
        card("Effective confidence", `${sc.effective_confidence_pct}%`),
      ])
    );
  } else {
    nodes.push(el("p", { class: "sub" }, "Unavailable -- no signal computed yet."));
  }
  return nodes;
}

async function renderStatus() {
  const data = await safe("/api/status");
  const nodes = [el("h2", {}, "System Status")];
  if (!data) {
    nodes.push(el("p", { class: "error" }, "Unable to load status."));
    return nodes;
  }
  nodes.push(
    table(
      ["Engine", "Last computed"],
      [
        ["Signal", data.signal_computed_at || "never computed"],
        ["Regime", data.regime_computed_at || "never computed"],
        ["Global Score", data.global_score_computed_at || "never computed"],
      ]
    )
  );
  return nodes;
}

function healthClass(label) {
  if (label === "Healthy") return "up";
  if (label === "Stressed") return "down";
  return "neutral";
}

function healthPill(healthy) {
  return el("span", { class: `pill ${healthy ? "available" : "unavailable"}` }, healthy ? "healthy" : "unhealthy");
}

// v9.0 visual indicator: a color-coded status badge for any already-computed
// good/warning/bad classification (BUY/SELL/HOLD, risk level, health label)
// -- reuses the existing .pill color system rather than inventing a new one.
function decisionPill(text, tone) {
  const cls = tone === "good" ? "available" : tone === "bad" ? "unavailable" : "warning";
  return el("span", { class: `pill ${cls}` }, text);
}

function recommendationTone(text) {
  if (!text) return "neutral";
  const upper = text.toUpperCase();
  if (upper.includes("BUY")) return "good";
  if (upper.includes("SELL")) return "bad";
  return "neutral";
}

function riskLevelTone(level) {
  if (!level) return "neutral";
  const lower = level.toLowerCase();
  if (lower === "low") return "good";
  if (lower === "high") return "bad";
  return "neutral";
}

// v5.4 Next Generation Market Watchdog -- the central Market Monitoring Hub.
// Extends (never replaces) the original Watchdog: Alert History below is the
// exact same AlertLog/MemoryEngine data the page always showed, now embedded
// alongside Current Market Status/Market Overview/Crypto+Macro Overview/
// On-Chain Overview/AI Status/What Changed/Provider Status -- one combined
// /api/watchdog fetch, matching "reuse existing engine outputs, refresh only
// changed sections" (no per-section polling loop; every number here is real,
// never fabricated -- "unavailable" renders as unavailable).
async function renderWatchdog() {
  const nodes = [el("h2", {}, "Market Watchdog -- Market Monitoring Hub")];
  const d = await safe("/api/watchdog");
  if (!d) {
    nodes.push(el("p", { class: "error" }, "Watchdog dashboard unavailable."));
    return nodes;
  }

  // v8.0 "Market Control Center" -- composed from the same sections below
  // (Current Status / AI Status / What Changed), shown first so a reader
  // gets direct verdicts before the raw data.
  const mb = d.market_brief;
  if (mb) {
    nodes.push(el("h2", {}, "Market Control Center"));
    const healthWord = mb.is_market_healthy === true ? "Yes" : mb.is_market_healthy === false ? "No" : "Mixed";
    nodes.push(
      el("div", { class: "grid" }, [
        card("Is the market healthy?", `${healthWord} (${mb.market_health_label})`),
        card("Is risk increasing?", mb.risk_direction, mb.risk_reason),
        card("Did AI change its opinion?", mb.ai_opinion_changed ? "Yes" : "No", mb.ai_opinion_reason),
      ])
    );
    nodes.push(el("h2", {}, "Today's Biggest Changes"));
    if (mb.biggest_changes_today.length) {
      nodes.push(el("ul", {}, mb.biggest_changes_today.map((m) => el("li", {}, m))));
    } else {
      nodes.push(el("p", { class: "sub" }, "None since the last cycle."));
    }
    nodes.push(el("h2", {}, "Needs Attention Now"));
    nodes.push(el("ul", {}, mb.needs_attention.map((m) => el("li", {}, m))));
  }

  const cs = d.current_status;
  nodes.push(el("h2", {}, "Current Market Status"));
  nodes.push(
    el("div", { class: "grid" }, [
      card("Market Health", cs.market_health, null, healthClass(cs.market_health)),
      card("Last Update", (cs.last_update || "never").slice(0, 16).replace("T", " ")),
      card("Next Scan", (cs.next_scan || "unknown").slice(0, 16).replace("T", " ")),
      card("Scan Duration", cs.scan_duration_ms != null ? `${cs.scan_duration_ms}ms` : "n/a"),
      card("Brain", cs.brain_status),
      card("Replay", cs.replay_status),
      card("Committee", cs.committee_status),
      card("Consensus", cs.consensus_status),
    ])
  );

  const mo = d.market_overview;
  nodes.push(el("h2", {}, "Market Overview"));
  nodes.push(
    el("div", { class: "grid" }, [
      card("Regime", (mo.regime || "unknown").replace(/_/g, " "), mo.trend ? `Trend: ${mo.trend}` : null),
      card("Trend Strength", fmtNum(mo.trend_strength, 0)),
      card("Momentum", fmtNum(mo.momentum, 1)),
      card("Volatility", fmtNum(mo.volatility, 0)),
      card("Confidence", fmtNum(mo.confidence, 0)),
      card("Risk Score", fmtNum(mo.risk_score, 0)),
      card("Liquidity Score", fmtNum(mo.liquidity_score, 0)),
      card("Market Intelligence Score", fmtNum(mo.market_intelligence_score, 0)),
    ])
  );

  nodes.push(el("h2", {}, "Crypto Overview"));
  nodes.push(
    table(
      ["Symbol", "Price", "24h %", "1h %", "15m %", "Trend", "Volume", "Momentum", "AI Bias"],
      d.crypto_overview.map((r) =>
        r.available
          ? [
              r.symbol,
              fmtNum(r.price),
              el("span", { class: changeClass(r.change_pct_24h) }, fmtPct(r.change_pct_24h)),
              el("span", { class: changeClass(r.change_pct_1h) }, fmtPct(r.change_pct_1h)),
              el("span", { class: changeClass(r.change_pct_15m) }, fmtPct(r.change_pct_15m)),
              r.trend || "n/a",
              r.volume_24h != null ? fmtNum(r.volume_24h, 0) : "n/a",
              r.momentum != null ? fmtNum(r.momentum, 1) : "n/a",
              r.ai_bias || "n/a",
            ]
          : [r.symbol, el("span", { class: "sub" }, "unavailable"), "", "", "", "", "", "", ""]
      )
    )
  );

  nodes.push(el("h2", {}, "Macro Overview"));
  nodes.push(
    table(
      ["Symbol", "Price", "Direction", "Daily %", "Trend", "Impact on Crypto"],
      d.macro_overview.map((r) =>
        r.available
          ? [
              r.name,
              fmtNum(r.price),
              r.direction || "n/a",
              el("span", { class: changeClass(r.daily_pct) }, fmtPct(r.daily_pct)),
              r.trend || "n/a",
              r.impact_on_crypto || "n/a",
            ]
          : [r.name, el("span", { class: "sub" }, "unavailable"), "", "", "", ""]
      )
    )
  );

  const oc = d.onchain_overview;
  nodes.push(el("h2", {}, "On-Chain Overview"));
  if (!oc.available) {
    nodes.push(el("p", { class: "sub" }, `Unavailable${oc.reason ? " -- " + oc.reason : ""}`));
  } else {
    nodes.push(
      el("div", { class: "grid" }, [
        card("Whale Positioning", (oc.whales && oc.whales.classification) || "unknown"),
        card("Funding", oc.funding != null ? oc.funding : "n/a"),
        card("Open Interest", oc.open_interest != null ? fmtNum(oc.open_interest, 0) : "n/a"),
        card("Exchange Flows", "unavailable"),
        card("Stablecoin Flow", "unavailable"),
        card("TVL", "unavailable"),
      ])
    );
  }

  const ai = d.ai_status;
  nodes.push(el("h2", {}, "AI Status"));
  if (ai.computed_at == null) {
    nodes.push(el("p", { class: "sub" }, "No Watchdog cycle has run yet -- check back shortly."));
  } else {
    nodes.push(
      el("div", { class: "grid" }, [
        card("Committee Opinion", ai.committee_opinion || "n/a"),
        card("Confidence", fmtNum(ai.prediction_confidence, 0)),
        card(
          "Expected Scenario",
          ai.expected_scenario ? `${ai.expected_scenario} (${ai.expected_scenario_pct}%)` : "n/a"
        ),
      ])
    );
    if (ai.consensus) {
      nodes.push(
        el(
          "p",
          { class: "sub" },
          `Consensus: bullish ${ai.consensus.bullish_pct}% / bearish ${ai.consensus.bearish_pct}% / ` +
            `neutral ${ai.consensus.neutral_pct}%`
        )
      );
    }
    if (ai.highest_risk) nodes.push(el("p", {}, `Main Risk: ${ai.highest_risk}`));
    if (ai.biggest_opportunity) nodes.push(el("p", {}, `Main Opportunity: ${ai.biggest_opportunity}`));
  }

  const wc = d.what_changed;
  nodes.push(el("h2", {}, "What Changed"));
  if (!wc.available || (!wc.fields.length && !wc.events.length)) {
    nodes.push(el("p", { class: "sub" }, "No significant changes since the last cycle."));
  } else {
    if (wc.fields.length) {
      nodes.push(
        table(
          ["Field", "Previous", "Current"],
          wc.fields.map((f) => [f.label, String(f.prev), String(f.curr)])
        )
      );
    }
    if (wc.events.length) {
      nodes.push(el("ul", {}, wc.events.map((e) => el("li", {}, e.message))));
    }
  }

  nodes.push(el("h2", {}, "Provider Status"));
  nodes.push(
    table(
      ["Provider", "Status", "Latency", "Reconnects", "Last Update"],
      d.provider_status.map((p) => [
        p.name,
        p.configured ? healthPill(p.healthy) : el("span", { class: "sub" }, "not configured"),
        p.latency_ms != null ? `${p.latency_ms}ms` : "n/a",
        p.reconnect_count != null ? String(p.reconnect_count) : "n/a",
        p.last_successful_update ? p.last_successful_update.slice(0, 16).replace("T", " ") : "never",
      ])
    )
  );

  nodes.push(el("h2", {}, "Alert History"));
  if (!d.alert_history.length) {
    nodes.push(el("p", { class: "sub" }, "No detections logged yet."));
  } else {
    nodes.push(
      table(
        ["Time", "Alert type", "Tier", "State", "Message"],
        d.alert_history.map((e) => [
          e.timestamp.slice(0, 16).replace("T", " "),
          e.summary.alert_type,
          e.summary.conviction_tier,
          e.summary.broadcast
            ? el("span", { class: "up" }, "sent")
            : el("span", { class: "sub" }, "suppressed"),
          e.summary.message,
        ])
      )
    );
  }

  nodes.push(navPointer("watchdog"));
  return nodes;
}

async function renderShocks() {
  const nodes = [el("h2", {}, "Critical Alerts (v5.1)")];
  nodes.push(
    el(
      "p",
      { class: "sub" },
      "Autonomous Critical Alert System -- a second, independent alert layer. No " +
        "configuration: the AI decides what's significant enough to notify Telegram."
    )
  );

  const active = await safe("/api/shocks/active");
  nodes.push(el("h2", {}, "Active Episodes"));
  if (!active || !active.active.length) {
    nodes.push(el("p", { class: "sub" }, "No active critical alerts right now."));
  } else {
    nodes.push(
      table(
        ["Tier", "Category", "Symbols", "Since", "Last updated"],
        active.active.map((a) => [
          el("span", { class: a.tier === "critical" || a.tier === "high" ? "down" : "neutral" }, a.tier.toUpperCase()),
          a.category.replace(/_/g, " "),
          a.symbols.join(", "),
          a.first_triggered_at.slice(0, 16).replace("T", " "),
          a.last_updated_at.slice(0, 16).replace("T", " "),
        ])
      )
    );
  }

  const history = await safe("/api/shocks/history?limit=20");
  nodes.push(el("h2", {}, "Recent History"));
  if (!history || !history.history.length) {
    nodes.push(el("p", { class: "sub" }, "No critical alerts logged yet."));
  } else {
    nodes.push(
      table(
        ["Tier", "Category", "Symbols", "Active", "Last updated"],
        history.history.map((h) => [
          h.tier.toUpperCase(),
          h.category.replace(/_/g, " "),
          h.symbols.join(", "),
          h.active ? "yes" : "no",
          h.last_updated_at.slice(0, 16).replace("T", " "),
        ])
      )
    );
  }

  return nodes;
}

async function renderTechnical() {
  const nodes = [el("h2", {}, "Technical Analysis (v5.3)")];
  nodes.push(
    el(
      "p",
      { class: "sub" },
      "TradingView MCP -- Institutional Technical Analysis Provider. Multi-timeframe " +
        "AI-interpreted read only: raw indicator values (RSI, MACD, ...) are never shown here."
    )
  );
  const input = el("input", { type: "text", value: "BTC", placeholder: "Symbol" });
  const btn = el("button", {}, "Load");
  nodes.push(el("div", { class: "controls" }, [input, btn]));
  const results = el("div");
  nodes.push(results);

  async function load() {
    results.innerHTML = "";
    try {
      const d = await fetchJSON(`/api/technical/${encodeURIComponent(input.value)}`);
      results.appendChild(
        el("div", { class: "grid" }, [
          card("Bullish Score", d.bullish_score != null ? d.bullish_score.toFixed(0) : "n/a"),
          card("Bearish Score", d.bearish_score != null ? d.bearish_score.toFixed(0) : "n/a"),
          card("Trend Strength", d.trend_strength != null ? d.trend_strength.toFixed(0) : "n/a"),
          card("Momentum", d.momentum != null ? d.momentum.toFixed(1) : "n/a"),
          card("Volatility", d.volatility != null ? d.volatility.toFixed(0) : "n/a"),
          card("Confidence", d.confidence != null ? `${d.confidence.toFixed(0)}%` : "n/a"),
          card("Breakout Probability", d.breakout_probability != null ? `${d.breakout_probability.toFixed(0)}%` : "n/a"),
          card("Breakdown Probability", d.breakdown_probability != null ? `${d.breakdown_probability.toFixed(0)}%` : "n/a"),
          card("Support", d.support != null ? fmtNum(d.support) : "n/a"),
          card("Resistance", d.resistance != null ? fmtNum(d.resistance) : "n/a"),
        ])
      );
      results.appendChild(el("p", { class: "sub" }, `Source: ${d.source} -- timeframes: ${(d.timeframes_covered || []).join(", ") || "n/a"}`));
      if (d.active_signals && d.active_signals.length) {
        results.appendChild(el("h2", {}, "Active Signals"));
        results.appendChild(el("p", {}, d.active_signals.join(", ")));
      }
    } catch (err) {
      results.appendChild(errorBox(err));
    }
  }
  btn.addEventListener("click", load);
  load();
  return nodes;
}

// v5.5 Autonomous Market Scanner -- top ~500 cryptocurrencies by market
// cap, scanned every scanner_interval_minutes. Never sends Telegram
// directly (see app.services.scanner.engine's module docstring); this
// page is a read-only view of the same /api/scanner data the Telegram
// /scanner command and the notifier both draw from.
async function renderScanner() {
  const nodes = [el("h2", {}, "Market Scanner")];
  const d = await safe("/api/scanner");
  if (!d) {
    nodes.push(el("p", { class: "error" }, "Market Scanner dashboard unavailable."));
    return nodes;
  }

  const breadth = d.top_movers;
  nodes.push(el("h2", {}, "Current Scans"));
  if (breadth && breadth.total_scanned) {
    nodes.push(
      el("div", { class: "grid" }, [
        card("Scanned", breadth.total_scanned),
        card("Rising", breadth.rising_count, null, "up"),
        card("Falling", breadth.falling_count, null, "down"),
        card("Unchanged", breadth.unchanged_count, null, "neutral"),
        card("Pending Alerts", d.pending_alerts.length),
        card("Suppressed (last 50)", d.suppressed_alerts.length),
      ])
    );
  } else {
    nodes.push(el("p", { class: "sub" }, "No scan data yet -- check back after the next cycle."));
  }

  // Composed from the same WatchdogSnapshot the scanner's AI filter
  // already reads every cycle (regime/risk/confidence/committee/consensus
  // + Scenario Engine's expected scenario) -- not a new calculation, and
  // previously only ever visible inside a fired HIGH/CRITICAL alert.
  const ctx = d.market_context;
  nodes.push(el("h2", {}, "Market Context"));
  if (ctx && ctx.regime) {
    nodes.push(
      el("div", { class: "grid" }, [
        card("Regime", ctx.regime.replace(/_/g, " ")),
        card("Risk", ctx.risk_score != null ? `${ctx.risk_score}/100` : "n/a"),
        card("Confidence", ctx.confidence_score != null ? `${ctx.confidence_score}/100` : "n/a"),
        card(
          "Committee",
          ctx.committee_decision
            ? `${ctx.committee_decision}${ctx.committee_majority_pct != null ? ` (${ctx.committee_majority_pct}%)` : ""}`
            : "n/a"
        ),
        card(
          "Expected Scenario",
          ctx.expected_scenario
            ? `${ctx.expected_scenario}${ctx.expected_scenario_pct != null ? ` (${ctx.expected_scenario_pct}%)` : ""}`
            : "n/a"
        ),
      ])
    );
    const insight = ctx.ai_insight || {};
    if (insight.consensus) {
      nodes.push(el("p", { class: "sub" }, `Consensus: ${insight.consensus}`));
    }
    if (ctx.highest_risk || ctx.biggest_opportunity) {
      nodes.push(
        el("p", { class: "sub" }, [
          ctx.biggest_opportunity ? `Main Opportunity: ${ctx.biggest_opportunity}. ` : "",
          ctx.highest_risk ? `Main Risk: ${ctx.highest_risk}.` : "",
        ].join(""))
      );
    }
  } else {
    nodes.push(el("p", { class: "sub" }, "No Watchdog cycle has run yet -- check back shortly."));
  }

  nodes.push(el("h2", {}, "Top Movers"));
  if (breadth && (breadth.top_gainers.length || breadth.top_losers.length)) {
    nodes.push(el("h2", {}, "Top Gainers"));
    nodes.push(
      table(
        ["Symbol", "Price", "24h %"],
        breadth.top_gainers.map((r) => [
          r.symbol,
          fmtNum(r.price, 6),
          el("span", { class: changeClass(r.change_pct_24h) }, fmtPct(r.change_pct_24h)),
        ])
      )
    );
    nodes.push(el("h2", {}, "Top Losers"));
    nodes.push(
      table(
        ["Symbol", "Price", "24h %"],
        breadth.top_losers.map((r) => [
          r.symbol,
          fmtNum(r.price, 6),
          el("span", { class: changeClass(r.change_pct_24h) }, fmtPct(r.change_pct_24h)),
        ])
      )
    );
  } else {
    nodes.push(el("p", { class: "sub" }, "No mover data yet."));
  }

  nodes.push(el("h2", {}, "Sector Leaders"));
  if (d.sector_leaders.length) {
    nodes.push(
      table(
        ["Sector", "Avg 24h %", "Coins", "Top Mover"],
        d.sector_leaders.map((s) => [
          s.sector,
          el("span", { class: changeClass(s.avg_change_pct_24h) }, fmtPct(s.avg_change_pct_24h)),
          s.coin_count,
          s.top_mover ? `${s.top_mover} (${fmtPct(s.top_mover_change_pct_24h)})` : "n/a",
        ])
      )
    );
  } else {
    nodes.push(el("p", { class: "sub" }, "No sector data yet."));
  }

  nodes.push(el("h2", {}, "Latest Detections"));
  if (d.latest_detections.length) {
    nodes.push(
      table(
        ["Time", "Tier", "Category", "Assets", "State", "Message"],
        d.latest_detections.map((a) => [
          a.last_updated_at.slice(0, 16).replace("T", " "),
          el("span", { class: a.tier === "critical" || a.tier === "high" ? "down" : "neutral" }, a.tier.toUpperCase()),
          a.category.replace(/_/g, " "),
          a.symbols.join(", "),
          a.active ? el("span", { class: "up" }, "active") : el("span", { class: "sub" }, "resolved"),
          a.message,
        ])
      )
    );
  } else {
    nodes.push(el("p", { class: "sub" }, "No detections logged yet."));
  }

  nodes.push(el("h2", {}, "Pending Alerts"));
  if (d.pending_alerts.length) {
    nodes.push(
      table(
        ["Tier", "Category", "Assets", "Since", "Message"],
        d.pending_alerts.map((a) => [
          a.tier.toUpperCase(),
          a.category.replace(/_/g, " "),
          a.symbols.join(", "),
          a.first_triggered_at.slice(0, 16).replace("T", " "),
          a.message,
        ])
      )
    );
  } else {
    nodes.push(el("p", { class: "sub" }, "No active scanner episodes right now."));
  }

  nodes.push(el("h2", {}, "Suppressed Alerts"));
  if (d.suppressed_alerts.length) {
    nodes.push(
      table(
        ["Time", "Tier", "Type", "Message"],
        d.suppressed_alerts.map((a) => [
          a.triggered_at.slice(0, 16).replace("T", " "),
          a.conviction_tier,
          a.alert_type,
          a.message,
        ])
      )
    );
  } else {
    nodes.push(el("p", { class: "sub" }, "No suppressed detections in the last 50."));
  }

  nodes.push(navPointer("scanner"));
  return nodes;
}

// "Why AI Thinks This" -- per-engine Signal/Confidence/Weight/Explanation
// breakdown, so the final prediction is fully traceable back to the real
// numbers behind it. `d.engine_breakdown`/`d.final_prediction` come from
// ExplainabilityEngine (app/services/explainability/engine.py); everything
// below that in this page is the pre-existing flat evidence pack this page
// already showed, kept as supplementary detail.
const WHY_SIGNAL_CLASS = { Bullish: "up", Bearish: "down", Neutral: "neutral" };

function whyFinalPrediction(finalPrediction) {
  if (!finalPrediction || !finalPrediction.bias) {
    return el("p", { class: "sub" }, "Final prediction not yet computed this cycle.");
  }
  const cls = WHY_SIGNAL_CLASS[finalPrediction.bias] || "neutral";
  const parts = [el("span", { class: `final-prediction-bias ${cls}` }, finalPrediction.bias)];
  if (finalPrediction.agreement_score != null) {
    parts.push(` (${finalPrediction.agreement_score}% agent agreement)`);
  }
  if (finalPrediction.committee_recommendation) {
    parts.push(el("div", { class: "sub" }, `Committee: ${finalPrediction.committee_recommendation}`));
  }
  return el("div", {}, parts);
}

function whyEngineBreakdown(rows) {
  if (!rows || !rows.length) return el("p", { class: "sub" }, "Engine breakdown not yet available.");
  return table(
    ["Engine", "Signal", "Confidence", "Weight", "Explanation"],
    rows.map((r) => [
      r.name,
      r.signal ? el("span", { class: WHY_SIGNAL_CLASS[r.signal] || "neutral" }, r.signal) : "unavailable",
      r.confidence != null ? `${r.confidence}%` : "unavailable",
      r.weight != null ? `${r.weight}%` : "n/a",
      r.explanation || "n/a",
    ])
  );
}

async function renderExplanation() {
  const nodes = [el("h2", {}, "Why AI Thinks This")];
  const input = el("input", { type: "text", value: "BTC", placeholder: "Symbol" });
  const btn = el("button", {}, "Load");
  nodes.push(el("div", { class: "controls" }, [input, btn]));
  const results = el("div");
  nodes.push(results);

  async function load() {
    results.innerHTML = "";
    try {
      const d = await fetchJSON(`/api/explanation/${encodeURIComponent(input.value)}`);
      results.appendChild(el("h2", {}, "Final Prediction"));
      results.appendChild(whyFinalPrediction(d.final_prediction));
      results.appendChild(el("h2", {}, "Engine Breakdown"));
      results.appendChild(whyEngineBreakdown(d.engine_breakdown));
      if (d.indicators.length) {
        results.appendChild(el("h2", {}, "Triggered indicators"));
        results.appendChild(
          table(
            ["Indicator", "Points"],
            d.indicators.map((i) => [i.name.replace(/_/g, " "), `${i.points > 0 ? "+" : ""}${i.points}`])
          )
        );
      }
      if (Object.keys(d.macro_drivers).length) {
        results.appendChild(el("h2", {}, "Macro drivers"));
        results.appendChild(
          table(
            ["Driver", "Value"],
            Object.entries(d.macro_drivers).map(([k, v]) => [
              k.replace(/_/g, " "),
              v == null || (typeof v === "object" && Object.keys(v).length === 0)
                ? "n/a"
                : typeof v === "object"
                  ? JSON.stringify(v)
                  : String(v),
            ])
          )
        );
      }
      if (d.supporting_news.length) {
        results.appendChild(el("h2", {}, "Supporting news"));
        results.appendChild(
          table(
            ["Sentiment", "Title"],
            d.supporting_news.map((n) => [n.sentiment, n.title])
          )
        );
      }
      if (d.historical_examples.length) {
        results.appendChild(el("h2", {}, "Historical examples"));
        results.appendChild(
          table(
            ["Date", "Similarity", "Regime", "7d forward"],
            d.historical_examples.map((h) => [
              h.match_timestamp.slice(0, 10),
              `${h.similarity_score.toFixed(0)}%`,
              h.regime || "unknown",
              fmtPct(h.forward_return_7d_pct),
            ])
          )
        );
      }
      if (d.risk_factors) {
        results.appendChild(el("h2", {}, "Risk factors"));
        results.appendChild(
          el("div", { class: "grid" }, [
            card("Fear", d.risk_factors.fear_score),
            card("Macro Pressure", d.risk_factors.macro_pressure_score),
            card("Risk-Off", d.risk_factors.risk_off_score),
            card("Risk Score", d.risk_factors.risk_score),
            card("Confidence", d.risk_factors.confidence_score),
          ])
        );
      }
      if (d.alternative_view) {
        results.appendChild(el("h2", {}, "Alternative view"));
        results.appendChild(
          card(d.alternative_view.name, `${d.alternative_view.probability_pct}%`, d.alternative_view.rationale)
        );
      }
    } catch (err) {
      results.appendChild(errorBox(err));
    }
  }
  btn.addEventListener("click", load);
  load();
  return nodes;
}

async function renderSentiment() {
  const data = await safe("/api/sentiment");
  const nodes = [el("h2", {}, "Sentiment")];
  if (!data) {
    nodes.push(el("p", { class: "error" }, "Sentiment unavailable."));
    return nodes;
  }
  nodes.push(
    el("div", { class: "grid" }, [
      card(
        "Fear & Greed",
        data.fear_greed_value != null ? `${data.fear_greed_value}/100` : "n/a",
        data.fear_greed_classification
      ),
      card(
        "News Sentiment",
        data.news_sentiment_score != null ? `${data.news_sentiment_score}/100` : "n/a",
        `${data.news_items_analyzed} items analyzed`
      ),
      card("Global Sentiment", data.global_sentiment_score != null ? `${data.global_sentiment_score}/100` : "n/a"),
    ])
  );
  nodes.push(
    el(
      "p",
      { class: "sub" },
      data.social_sentiment_available ? "Social sentiment available." : data.social_sentiment_reason
    )
  );
  return nodes;
}

async function renderCalendar() {
  const data = await safe("/api/calendar");
  const nodes = [el("h2", {}, "Economic Calendar")];
  if (!data) {
    nodes.push(el("p", { class: "error" }, "Calendar unavailable."));
    return nodes;
  }
  nodes.push(el("h2", {}, "Upcoming"));
  nodes.push(
    data.upcoming.length
      ? table(
          ["Date", "Country", "Title", "Importance", "Category"],
          data.upcoming.map((e) => [e.event_date.slice(0, 10), e.country, e.title, e.importance, e.category])
        )
      : el("p", { class: "sub" }, "No upcoming events.")
  );
  nodes.push(el("h2", {}, "Recent"));
  nodes.push(
    data.recent.length
      ? table(
          ["Date", "Country", "Title", "Importance", "Category"],
          data.recent.map((e) => [e.event_date.slice(0, 10), e.country, e.title, e.importance, e.category])
        )
      : el("p", { class: "sub" }, "No recent events.")
  );
  return nodes;
}

async function renderSimilarity() {
  const nodes = [el("h2", {}, "Historical Similarity")];
  const input = el("input", { type: "text", value: "BTC", placeholder: "Symbol" });
  const btn = el("button", {}, "Search");
  nodes.push(el("div", { class: "controls" }, [input, btn]));
  const results = el("div", { id: "similarity-results" });
  nodes.push(results);

  async function search() {
    results.innerHTML = "";
    results.appendChild(el("p", { class: "loading" }, "Loading..."));
    try {
      const [similar, knowledge] = await Promise.all([
        fetchJSON(`/api/similar/${encodeURIComponent(input.value)}`),
        fetchJSON(`/api/knowledge/${encodeURIComponent(input.value)}`),
      ]);
      results.innerHTML = "";
      if (similar.lesson) {
        const lesson = similar.lesson;
        results.appendChild(el("h2", {}, "Historical Lesson"));
        results.appendChild(el("p", {}, lesson.what_happened));
        const lessonGrid = el("div", { class: "grid" }, [
          card("How Similar", `${lesson.how_similar_pct}%`, "avg match"),
          card(
            `Average Outcome (${lesson.horizon_days}d)`,
            fmtPct(lesson.average_outcome_pct),
            null,
            changeClass(lesson.average_outcome_pct)
          ),
          card("Probability", `${lesson.probability_pct}%`, "moved the same direction"),
          card("Typical Duration", lesson.typical_duration.match(/\d+/)?.[0] ?? "n/a", "days, in similar cases"),
        ]);
        results.appendChild(lessonGrid);
        results.appendChild(el("p", { class: "sub" }, lesson.main_lesson));
      }
      results.appendChild(el("h2", {}, `${similar.symbol}: 25 Most Similar Periods`));
      results.appendChild(
        table(
          ["Date", "Similarity", "Regime", "1d", "3d", "7d", "30d"],
          similar.matches.slice(0, 10).map((m) => [
            m.date.slice(0, 10),
            String(m.similarity),
            m.market_regime || "unknown",
            fmtPct(m.forward_returns_pct["1d"]),
            fmtPct(m.forward_returns_pct["3d"]),
            fmtPct(m.forward_returns_pct["7d"]),
            fmtPct(m.forward_returns_pct["30d"]),
          ])
        )
      );
      results.appendChild(el("h2", {}, "Nearest Historical Analogs"));
      results.appendChild(
        table(
          ["Date", "RSI", "Forward return (7d)", "Nearby event(s)"],
          knowledge.analogs.map((a) => [
            a.timestamp.slice(0, 10),
            a.rsi.toFixed(1),
            fmtPct(a.forward_returns_pct["7d"]),
            a.nearby_events.length ? a.nearby_events.map((e) => e.title).join(", ") : "-",
          ])
        )
      );
    } catch (err) {
      results.innerHTML = "";
      results.appendChild(errorBox(err));
    }
  }
  btn.addEventListener("click", search);
  search();
  return nodes;
}

async function renderBrain() {
  const report = await safe("/api/brain");
  const nodes = [el("h2", {}, "AI Brain")];
  if (!report) {
    nodes.push(el("p", { class: "error" }, "No report generated yet. Requires OPENAI_API_KEY."));
    return nodes;
  }
  const a = report.analysis;
  const sections = [
    ["What Changed", "what_changed"], ["Why", "why"], ["Who Is Driving The Market", "who_is_driving"],
    ["Institutional Behavior", "institutional_behavior"], ["Macro Explanation", "macro_explanation"],
    ["Historical Comparison", "historical_comparison"], ["Liquidity & Risk", "liquidity_and_risk"],
    ["Main Risks", "main_risks"], ["Scenarios", "scenarios"], ["Actionable Insights", "actionable_insights"],
  ];
  nodes.push(
    el("div", { class: "grid" }, [
      card("Regime", report.regime), card("Risk Level", report.risk_level),
      card("Bull / Bear", `${report.bull_score} / ${report.bear_score}`),
      card("Bullish Probability", `${a.probability_bullish_pct}%`),
    ])
  );
  nodes.push(decisionPill(report.risk_level, riskLevelTone(report.risk_level)));
  for (const [label, key] of sections) {
    nodes.push(el("h2", {}, label));
    nodes.push(el("pre", { class: "summary" }, a[key] || "n/a"));
  }
  return nodes;
}

async function renderResearch() {
  const nodes = [el("h2", {}, "Research Lab")];

  nodes.push(el("h2", {}, "Daily Research Note"));
  const noteBox = el("div");
  const genBtn = el("button", {}, "Generate now");

  async function loadNote() {
    noteBox.innerHTML = "";
    const note = await safe("/api/research/notes/latest");
    if (!note) {
      noteBox.appendChild(el("p", { class: "error" }, "No research note generated yet."));
      return;
    }
    noteBox.appendChild(el("pre", { class: "summary" }, note.note));
    noteBox.appendChild(
      el(
        "p",
        { class: "sub" },
        `${note.discovery_count} discoveries -- ${note.generated_at.slice(0, 19).replace("T", " ")}`
      )
    );
  }
  genBtn.addEventListener("click", async () => {
    noteBox.innerHTML = "";
    noteBox.appendChild(el("p", { class: "loading" }, "Generating..."));
    try {
      await fetchJSONWithAdminKey("/api/research/notes/generate", { method: "POST" });
      await loadNote();
    } catch (err) {
      noteBox.innerHTML = "";
      noteBox.appendChild(errorBox(err));
    }
  });
  nodes.push(noteBox, el("div", { class: "controls" }, [genBtn]));
  await loadNote();

  nodes.push(el("h2", {}, "Factor Ranking"));
  const ranking = await safe("/api/ranking?symbol=BTC");
  if (ranking) {
    nodes.push(
      table(
        ["Rank", "Factor", "Current edge", "Historical edge", "Confidence"],
        ranking.rankings.map((r) => [
          String(r.rank),
          r.factor.replace(/_/g, " "),
          r.current_importance_pct != null ? `${r.current_importance_pct}%` : "n/a",
          r.historical_importance_pct != null ? `${r.historical_importance_pct}%` : "n/a",
          String(r.confidence),
        ])
      )
    );
  } else {
    nodes.push(el("p", { class: "sub" }, "No ranking computed yet."));
  }

  nodes.push(el("h2", {}, "Hypotheses"));
  const hypResults = el("div");
  async function loadHypotheses() {
    hypResults.innerHTML = "";
    const data = await safe("/api/hypothesis?limit=10");
    if (!data || !data.hypotheses.length) {
      hypResults.appendChild(el("p", { class: "sub" }, "No hypotheses tested yet."));
      return;
    }
    hypResults.appendChild(
      table(
        ["Statement", "Verdict", "Reason"],
        data.hypotheses.map((h) => [h.statement, h.verdict, h.reason])
      )
    );
  }
  await loadHypotheses();
  nodes.push(hypResults);

  const hSymbol = el("input", { type: "text", placeholder: "Symbol (e.g. BTC)" });
  const hEventA = el("input", { type: "text", placeholder: "Event A (e.g. fomc)" });
  const hEventB = el("input", { type: "text", placeholder: "Event B (e.g. cpi)" });
  const hBtn = el("button", {}, "Test hypothesis");
  hBtn.addEventListener("click", async () => {
    try {
      await fetchJSONWithAdminKey("/api/hypothesis/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: hSymbol.value, event_a: hEventA.value, event_b: hEventB.value }),
      });
      await loadHypotheses();
    } catch (err) {
      hypResults.prepend(errorBox(err));
    }
  });
  nodes.push(el("div", { class: "controls" }, [hSymbol, hEventA, hEventB, hBtn]));

  nodes.push(el("h2", {}, "Event Research"));
  const rSymbol = el("input", { type: "text", value: "BTC", placeholder: "Symbol" });
  const rEvent = el("input", { type: "text", value: "cpi", placeholder: "Event category" });
  const rBtn = el("button", {}, "Run");
  const rResults = el("div");
  rBtn.addEventListener("click", async () => {
    rResults.innerHTML = "";
    try {
      const r = await fetchJSON(
        `/api/research?symbol=${encodeURIComponent(rSymbol.value)}&event=${encodeURIComponent(rEvent.value)}`
      );
      rResults.appendChild(
        el("div", { class: "grid" }, [
          card("Occurrences", r.occurrences),
          card("Win rate", `${r.win_rate_pct}%`),
          card("Avg return", fmtPct(r.avg_return_pct)),
          card("Sharpe", r.sharpe_ratio ?? "n/a"),
        ])
      );
    } catch (err) {
      rResults.appendChild(errorBox(err));
    }
  });
  nodes.push(el("div", { class: "controls" }, [rSymbol, rEvent, rBtn]), rResults);

  return nodes;
}

// A fixed, small DSL over app.services.backtest.conditions.Condition --
// see that module's own docstring ("deliberately not a free-text/NLP
// parser"). Listed here once rather than free-text parsing (unlike the
// older Strategies page's SYMBOL:field:op:value input) since the backend
// only ever accepts exactly these fields/operators.
const _BACKTEST_FIELDS = [
  "close", "return_pct", "volatility", "atr", "rsi", "macd", "macd_signal",
  "macd_histogram", "sma_20", "sma_50", "sma_200", "volume_change_pct",
];
const _BACKTEST_OPERATORS = ["gt", "lt", "gte", "lte"];

function _backtestConditionRow(defaults = {}) {
  const symbol = el("input", { type: "text", value: defaults.symbol || "BTC", placeholder: "Symbol" });
  const field = el("select", {}, _BACKTEST_FIELDS.map((f) => el("option", { value: f }, f)));
  field.value = defaults.field || "rsi";
  const operator = el("select", {}, _BACKTEST_OPERATORS.map((o) => el("option", { value: o }, o)));
  operator.value = defaults.operator || "lt";
  const value = el("input", { type: "text", value: defaults.value ?? "30", placeholder: "Value" });
  const removeBtn = el("button", {}, "Remove");
  const row = el("div", { class: "controls" }, [symbol, field, operator, value, removeBtn]);
  removeBtn.addEventListener("click", () => row.remove());
  row._read = () => ({
    symbol: symbol.value.trim().toUpperCase(),
    field: field.value,
    operator: operator.value,
    value: parseFloat(value.value),
  });
  return row;
}

async function renderBacktest() {
  const nodes = [
    el("h2", {}, "Backtest"),
    el(
      "p",
      { class: "sub" },
      "Tests a structured rule (AND of conditions) against a symbol's full stored history -- " +
        "every historical date the rule fired, the target's forward return becomes one trade. " +
        "Includes a 1-bar fill lag and round-trip fee/slippage costs, so results aren't an " +
        "unrealistic same-bar zero-cost fill."
    ),
  ];

  const targetInput = el("input", { type: "text", value: "BTC", placeholder: "Target symbol" });
  const timeframeSelect = el("select", {}, ["1d", "4h", "1h"].map((t) => el("option", { value: t }, t)));
  const horizonInput = el("input", { type: "text", value: "5", placeholder: "Horizon (periods)" });
  nodes.push(el("div", { class: "controls" }, [targetInput, timeframeSelect, horizonInput]));

  const conditionsWrap = el("div");
  nodes.push(conditionsWrap);
  conditionsWrap.appendChild(_backtestConditionRow());
  const addConditionBtn = el("button", {}, "+ Add condition");
  addConditionBtn.addEventListener("click", () => conditionsWrap.appendChild(_backtestConditionRow()));

  const runBtn = el("button", {}, "Run backtest");
  nodes.push(el("div", { class: "controls" }, [addConditionBtn, runBtn]));

  const results = el("div");
  nodes.push(results);

  runBtn.addEventListener("click", async () => {
    results.innerHTML = "";
    const conditions = [...conditionsWrap.children].map((row) => row._read());
    if (conditions.some((c) => !c.symbol || Number.isNaN(c.value))) {
      results.appendChild(el("p", { class: "error" }, "Every condition needs a symbol and a numeric value."));
      return;
    }
    results.appendChild(el("p", { class: "loading" }, "Running..."));
    try {
      const r = await fetchJSON("/api/backtest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_symbol: targetInput.value.trim().toUpperCase(),
          conditions,
          timeframe: timeframeSelect.value,
          horizon: parseInt(horizonInput.value, 10) || 1,
        }),
      });
      results.innerHTML = "";
      results.appendChild(
        el("div", { class: "grid" }, [
          card("Occurrences", r.occurrences),
          card("Win rate", `${r.win_rate_pct}%`, null, changeClass(r.win_rate_pct - 50)),
          card("Avg return", fmtPct(r.avg_return_pct), null, changeClass(r.avg_return_pct)),
          card("Expectancy", fmtPct(r.expectancy_pct), null, changeClass(r.expectancy_pct)),
          card("Max drawdown", `${r.max_drawdown_pct}%`, null, "down"),
          card("Profit factor", r.profit_factor ?? "n/a"),
          card("Sharpe ratio", r.sharpe_ratio ?? "n/a"),
          card("Sortino ratio", r.sortino_ratio ?? "n/a"),
          card("Calmar ratio", r.calmar_ratio ?? "n/a"),
          card("CAGR", fmtPct(r.cagr_pct)),
          card("Avg win", fmtPct(r.avg_win_pct), null, "up"),
          // avg_loss_pct/var_95_pct/cvar_95_pct are all magnitudes (always
          // >= 0 by backend contract, see compute_backtest_metrics) -- not
          // signed returns, so fmtPct()'s "+" gain framing would misread
          // as a profit next to the "down" styling.
          card("Avg loss", `${r.avg_loss_pct}%`, null, "down"),
          card("VaR 95%", `${r.var_95_pct}%`, null, "down"),
          card("CVaR 95%", `${r.cvar_95_pct}%`, null, "down"),
        ])
      );
      results.appendChild(
        el(
          "p",
          { class: "sub" },
          `${r.target_symbol} · ${r.timeframe} · horizon ${r.horizon_periods} · fill lag ${r.fill_lag_periods} bar(s) · ` +
            `fee ${r.fee_pct}% + slippage ${r.slippage_pct}% per round trip`
        )
      );
      if (r.universe_caveat) {
        results.appendChild(el("p", { class: "error" }, r.universe_caveat));
      }
    } catch (err) {
      results.innerHTML = "";
      results.appendChild(errorBox(err));
    }
  });

  return nodes;
}

async function renderStrategies() {
  const nodes = [el("h2", {}, "Strategies")];
  const symbolInput = el("input", { type: "text", value: "BTC", placeholder: "Target symbol" });
  const condInput = el("input", {
    type: "text",
    value: "BTC:rsi:lt:30",
    placeholder: "Condition SYMBOL:field:op:value",
  });
  const horizonInput = el("input", { type: "text", value: "5", placeholder: "Horizon" });
  const slInput = el("input", { type: "text", placeholder: "Stop loss (e.g. 0.05)" });
  const tpInput = el("input", { type: "text", placeholder: "Take profit (e.g. 0.1)" });
  const modeSelect = el(
    "select",
    {},
    ["run", "walk_forward", "monte_carlo"].map((m) => el("option", { value: m }, m))
  );
  const runBtn = el("button", {}, "Run");
  nodes.push(
    el("div", { class: "controls" }, [
      symbolInput,
      condInput,
      horizonInput,
      slInput,
      tpInput,
      modeSelect,
      runBtn,
    ])
  );
  const results = el("div");
  nodes.push(results);

  function parseCondition(text) {
    const parts = text.split(":");
    if (parts.length !== 4) return null;
    return { symbol: parts[0], field: parts[1], operator: parts[2], value: parseFloat(parts[3]) };
  }

  runBtn.addEventListener("click", async () => {
    results.innerHTML = "";
    const condition = parseCondition(condInput.value);
    if (!condition) {
      results.appendChild(el("p", { class: "error" }, "Condition must look like SYMBOL:field:op:value"));
      return;
    }
    try {
      const body = {
        target_symbol: symbolInput.value,
        conditions: [condition],
        horizon: parseInt(horizonInput.value, 10) || 1,
        stop_loss_pct: slInput.value ? parseFloat(slInput.value) : null,
        take_profit_pct: tpInput.value ? parseFloat(tpInput.value) : null,
        mode: modeSelect.value,
      };
      const r = await fetchJSON("/api/strategy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (modeSelect.value === "walk_forward") {
        results.appendChild(
          table(
            ["Fold", "Start", "End", "Occurrences", "Win rate"],
            r.folds.map((f) => [
              String(f.fold),
              f.start_date.slice(0, 10),
              f.end_date.slice(0, 10),
              f.metrics ? String(f.metrics.occurrences) : "0",
              f.metrics ? `${f.metrics.win_rate_pct}%` : "n/a",
            ])
          )
        );
      } else if (modeSelect.value === "monte_carlo") {
        results.appendChild(
          el("div", { class: "grid" }, [
            card("Total return p5", fmtPct(r.total_return_p5_pct)),
            card("Total return p50", fmtPct(r.total_return_p50_pct)),
            card("Total return p95", fmtPct(r.total_return_p95_pct)),
            card("Max drawdown p50", `${r.max_drawdown_p50_pct}%`),
            card("Max drawdown p95", `${r.max_drawdown_p95_pct}%`),
            card("Probability of Profit", `${r.probability_of_profit_pct}%`),
            card("Probability of Loss", `${r.probability_of_loss_pct}%`),
            card(`Probability of Ruin (>${r.ruin_drawdown_pct}% DD)`, `${r.probability_of_ruin_pct}%`),
          ])
        );
      } else {
        results.appendChild(
          el("div", { class: "grid" }, [
            card("Occurrences", r.occurrences),
            card("Win rate", `${r.win_rate_pct}%`),
            card("Avg return", fmtPct(r.avg_return_pct)),
            card("Max drawdown", `${r.max_drawdown_pct}%`),
            card("Profit factor", r.profit_factor ?? "n/a"),
            card("Sharpe", r.sharpe_ratio ?? "n/a"),
          ])
        );
      }
    } catch (err) {
      results.appendChild(errorBox(err));
    }
  });

  return nodes;
}

async function renderProbability() {
  const nodes = [el("h2", {}, "Probability")];
  const input = el("input", { type: "text", value: "BTC", placeholder: "Symbol" });
  const btn = el("button", {}, "Load");
  nodes.push(el("div", { class: "controls" }, [input, btn]));
  const results = el("div");
  nodes.push(results);

  async function load() {
    results.innerHTML = "";
    try {
      const p = await fetchJSON(`/api/probability/${encodeURIComponent(input.value)}`);
      results.appendChild(
        el("div", { class: "grid" }, [
          card("Bullish", `${p.prob_up_pct}%`, null, "up"),
          card("Bearish", `${p.prob_down_pct}%`, null, "down"),
          card("Neutral", `${p.prob_flat_pct}%`),
          card("Sample size", p.sample_size),
        ])
      );
      results.appendChild(el("p", { class: "sub" }, `Reference RSI ${p.reference_rsi.toFixed(1)}, avg forward return ${fmtPct(p.avg_forward_return_pct, 4)}`));
      results.appendChild(
        el(
          "p",
          { class: "sub" },
          p.regime_conditioned
            ? `Conditioned on the current market regime (${p.reference_regime || "n/a"}).`
            : "Not regime-conditioned this cycle -- too few same-regime samples."
        )
      );
      results.appendChild(
        el(
          "p",
          { class: "sub" },
          p.volatility_conditioned
            ? "Also conditioned on similarly-volatile historical periods."
            : "Not volatility-conditioned this cycle -- too few similarly-volatile samples."
        )
      );
    } catch (err) {
      results.appendChild(errorBox(err));
    }
  }
  btn.addEventListener("click", load);
  load();
  return nodes;
}

async function renderLearning() {
  const nodes = [el("h2", {}, "Self-Learning Accuracy")];
  const symbolInput = el("input", { type: "text", value: "BTC", placeholder: "Symbol" });
  const tfSelect = el("select", {}, ["1d", "4h", "1h"].map((t) => el("option", { value: t }, t)));
  const btn = el("button", {}, "Load");
  nodes.push(el("div", { class: "controls" }, [symbolInput, tfSelect, btn]));
  const results = el("div");
  nodes.push(results);

  async function load() {
    results.innerHTML = "";
    try {
      const r = await fetchJSON(
        `/api/learning/${encodeURIComponent(symbolInput.value)}?timeframe=${tfSelect.value}`
      );
      results.appendChild(
        el("div", { class: "grid" }, [
          card("Evaluated predictions", r.evaluated_predictions),
          card("Accuracy", `${r.accuracy_pct}%`),
        ])
      );
      results.appendChild(
        table(
          ["Date", "Predicted", "Realized", "Return", "Result"],
          r.recent
            .slice()
            .reverse()
            .map((e) => [
              e.reference_timestamp.slice(0, 10),
              e.predicted,
              e.realized,
              fmtPct(e.realized_return_pct),
              el("span", { class: e.correct ? "up" : "down" }, e.correct ? "correct" : "wrong"),
            ])
        )
      );
    } catch (err) {
      results.appendChild(errorBox(err));
    }
  }
  btn.addEventListener("click", load);
  load();
  return nodes;
}

async function renderQuality() {
  const nodes = [el("h2", {}, "Prediction Quality Lab")];
  const symbolInput = el("input", { type: "text", value: "BTC", placeholder: "Symbol" });
  const tfSelect = el("select", {}, ["1d", "4h", "1h"].map((t) => el("option", { value: t }, t)));
  const btn = el("button", {}, "Load");
  nodes.push(el("div", { class: "controls" }, [symbolInput, tfSelect, btn]));
  const results = el("div");
  nodes.push(results);

  async function load() {
    results.innerHTML = "";
    try {
      const r = await fetchJSON(
        `/api/quality/${encodeURIComponent(symbolInput.value)}?timeframe=${tfSelect.value}`
      );
      results.appendChild(
        el("div", { class: "grid" }, [
          card("Evaluated predictions", r.evaluated_predictions),
          card("Accuracy", `${r.accuracy_pct}%`),
          card("Brier score", r.brier_score),
          card("Log Loss", r.log_loss),
          card("Avg calibration error", `${r.average_error_pct}%`),
          card("Expected Calibration Error (ECE)", r.expected_calibration_error),
        ])
      );
      results.appendChild(el("h2", {}, "Precision / Recall"));
      results.appendChild(
        el("p", { class: "sub" }, `Macro precision ${r.precision_recall.macro_precision_pct}% | Macro recall ${r.precision_recall.macro_recall_pct}%`)
      );
      results.appendChild(
        table(
          ["Class", "Precision", "Recall", "Support"],
          Object.entries(r.precision_recall.per_class).map(([cls, stats]) => [
            cls,
            stats.precision_pct !== null ? `${stats.precision_pct}%` : "n/a",
            stats.recall_pct !== null ? `${stats.recall_pct}%` : "n/a",
            stats.support,
          ])
        )
      );
      if (r.calibration.length) {
        results.appendChild(el("h2", {}, "Calibration"));
        results.appendChild(
          table(
            ["Confidence Bucket", "Count", "Predicted", "Observed", "Gap"],
            r.calibration.map((b) => [
              b.confidence_bucket,
              b.count,
              `${b.avg_predicted_confidence_pct}%`,
              `${b.observed_accuracy_pct}%`,
              `${b.calibration_gap_pct}%`,
            ])
          )
        );
      }
      if (r.time_horizon_accuracy.length) {
        results.appendChild(el("h2", {}, "Accuracy by Horizon"));
        results.appendChild(
          table(
            ["Horizon (periods)", "Count", "Accuracy"],
            r.time_horizon_accuracy.map((h) => [h.horizon_periods, h.count, `${h.accuracy_pct}%`])
          )
        );
      }
      if (r.calibration_by_regime_horizon && r.calibration_by_regime_horizon.length) {
        results.appendChild(el("h2", {}, "Calibration by Regime × Horizon"));
        results.appendChild(
          table(
            ["Regime", "Horizon (periods)", "Count", "ECE"],
            r.calibration_by_regime_horizon.map((row) => [
              row.regime || "n/a",
              row.horizon_periods ?? "n/a",
              row.count,
              row.expected_calibration_error != null ? row.expected_calibration_error : "n/a",
            ])
          )
        );
      }
    } catch (err) {
      results.appendChild(errorBox(err));
    }
  }
  btn.addEventListener("click", load);
  load();
  return nodes;
}

// Prediction Accuracy -- every graded prediction (already computed by
// app.services.forecast.engine.grade_price_forecasts()), aggregated into
// Daily/Weekly/Monthly/Asset views via /api/accuracy. No new grading here,
// only display of what the grading job already persisted.
function accuracyStatCards(stats) {
  return el("div", { class: "grid" }, [
    card("Evaluated", stats.evaluated_count),
    card("Direction Accuracy", stats.direction_accuracy_pct != null ? `${stats.direction_accuracy_pct}%` : "n/a"),
    card("Avg Abs Error", stats.avg_abs_error_pct != null ? `${stats.avg_abs_error_pct}%` : "n/a"),
    card("Avg CRPS", stats.avg_crps_pct != null ? `${stats.avg_crps_pct}%` : "n/a"),
    card("Confidence Accuracy", stats.confidence_accuracy_pct != null ? `${stats.confidence_accuracy_pct}%` : "n/a"),
    card("Target Hit Rate", stats.target_hit_rate_pct != null ? `${stats.target_hit_rate_pct}%` : "n/a"),
  ]);
}

function accuracyPeriodTable(buckets) {
  if (!buckets.length) return el("p", { class: "sub" }, "No graded predictions in this window yet.");
  return table(
    ["Period", "Count", "Direction Accuracy", "Avg Abs Error", "Confidence Accuracy"],
    buckets.map((b) => [
      b.period,
      b.evaluated_count,
      b.direction_accuracy_pct != null ? `${b.direction_accuracy_pct}%` : "n/a",
      b.avg_abs_error_pct != null ? `${b.avg_abs_error_pct}%` : "n/a",
      b.confidence_accuracy_pct != null ? `${b.confidence_accuracy_pct}%` : "n/a",
    ])
  );
}

async function renderAccuracy() {
  const nodes = [el("h2", {}, "Prediction Accuracy")];
  const data = await safe("/api/accuracy");
  if (!data || data.overall.evaluated_count === 0) {
    nodes.push(
      el(
        "p",
        { class: "error" },
        "No graded predictions yet -- forecasts are graded once their horizon has actually elapsed in stored history."
      )
    );
    return nodes;
  }

  nodes.push(el("h2", {}, "Overall"));
  nodes.push(accuracyStatCards(data.overall));

  if (data.daily.length > 1) {
    nodes.push(el("h2", {}, "Avg Abs Error % Trend (Daily)"));
    nodes.push(svgLineChart(data.daily.map((b) => b.avg_abs_error_pct)));
    nodes.push(el("h2", {}, "Direction Accuracy % Trend (Daily)"));
    nodes.push(svgLineChart(data.daily.map((b) => b.direction_accuracy_pct)));
  }

  nodes.push(el("h2", {}, "Daily Accuracy"));
  nodes.push(accuracyPeriodTable(data.daily));
  nodes.push(el("h2", {}, "Weekly Accuracy"));
  nodes.push(accuracyPeriodTable(data.weekly));
  nodes.push(el("h2", {}, "Monthly Accuracy"));
  nodes.push(accuracyPeriodTable(data.monthly));

  nodes.push(el("h2", {}, "Asset Accuracy"));
  if (!data.by_asset.length) {
    nodes.push(el("p", { class: "sub" }, "No graded predictions yet for any asset."));
  } else {
    nodes.push(
      table(
        ["Symbol", "Count", "Direction Accuracy", "Avg Abs Error", "Confidence Accuracy"],
        data.by_asset.map((a) => [
          a.symbol,
          a.evaluated_count,
          a.direction_accuracy_pct != null ? `${a.direction_accuracy_pct}%` : "n/a",
          a.avg_abs_error_pct != null ? `${a.avg_abs_error_pct}%` : "n/a",
          a.confidence_accuracy_pct != null ? `${a.confidence_accuracy_pct}%` : "n/a",
        ])
      )
    );
  }

  nodes.push(el("h2", {}, "Regime × Horizon Accuracy"));
  if (!data.by_regime_horizon.length) {
    nodes.push(el("p", { class: "sub" }, "No graded predictions yet with a recorded regime."));
  } else {
    nodes.push(
      table(
        ["Regime", "Horizon", "Count", "Direction Accuracy", "Avg Abs Error", "Beats Momentum Baseline"],
        data.by_regime_horizon.map((c) => [
          c.regime,
          c.horizon,
          c.evaluated_count,
          c.direction_accuracy_pct != null ? `${c.direction_accuracy_pct}%` : "n/a",
          c.avg_abs_error_pct != null ? `${c.avg_abs_error_pct}%` : "n/a",
          c.beats_momentum_baseline == null
            ? "n/a"
            : el("span", { class: c.beats_momentum_baseline ? "up" : "down" }, c.beats_momentum_baseline ? "Yes" : "No"),
        ])
      )
    );
  }

  nodes.push(el("h2", {}, "Recent Graded Predictions"));
  if (!data.recent.length) {
    nodes.push(el("p", { class: "sub" }, "Nothing graded yet."));
  } else {
    nodes.push(
      table(
        ["Symbol", "Horizon", "Evaluated At", "Predicted", "Actual", "Error %", "Direction", "Target Touched", "Confidence", "Tier"],
        data.recent.map((r) => [
          r.symbol,
          r.horizon,
          new Date(r.evaluated_at).toLocaleString(),
          fmtNum(r.target_price),
          r.realized_price != null ? fmtNum(r.realized_price) : "n/a",
          r.error_pct != null ? fmtPct(r.error_pct) : "n/a",
          r.direction_correct == null
            ? "n/a"
            : el("span", { class: r.direction_correct ? "up" : "down" }, r.direction_correct ? "Correct" : "Wrong"),
          r.target_reached == null
            ? "n/a"
            : el("span", { class: r.target_reached ? "up" : "down" }, r.target_reached ? "Yes" : "No"),
          r.confidence_correct == null
            ? "n/a"
            : el("span", { class: r.confidence_correct ? "up" : "down" }, r.confidence_correct ? "Correct" : "Wrong"),
          r.confidence_tier || "n/a",
        ])
      )
    );
  }

  return nodes;
}

async function renderAdvice() {
  const nodes = [el("h2", {}, "Portfolio Advice")];
  const symbolInput = el("input", { type: "text", value: "BTC", placeholder: "Symbol" });
  const tfSelect = el("select", {}, ["1d", "4h", "1h"].map((t) => el("option", { value: t }, t)));
  const btn = el("button", {}, "Load");
  nodes.push(el("div", { class: "controls" }, [symbolInput, tfSelect, btn]));
  const results = el("div");
  nodes.push(results);

  async function load() {
    results.innerHTML = "";
    try {
      const a = await fetchJSON(
        `/api/portfolio/advice/${encodeURIComponent(symbolInput.value)}?timeframe=${tfSelect.value}`
      );
      results.appendChild(
        el("div", { class: "grid" }, [
          card("Recommendation", a.recommendation, null, a.recommendation === "BUY" ? "up" : a.recommendation === "SELL" ? "down" : "neutral"),
          card("Reference price", fmtNum(a.entry_reference_price)),
          card("ATR", a.atr != null ? fmtNum(a.atr, 4) : "unavailable"),
        ])
      );
      results.appendChild(el("p", {}, a.reasoning));
      results.appendChild(
        el("div", { class: "grid" }, [
          card("Up", `${a.probability.up}%`, null, "up"),
          card("Down", `${a.probability.down}%`, null, "down"),
          card("Flat", `${a.probability.flat}%`),
        ])
      );
      if (a.stop_loss_price != null) {
        results.appendChild(
          el("div", { class: "grid" }, [
            card("Stop-loss", fmtNum(a.stop_loss_price)),
            card("Take-profit", fmtNum(a.take_profit_price)),
            card("Risk:reward", `1:${a.risk_reward_ratio}`),
          ])
        );
      }
      if (a.position_size_note) {
        results.appendChild(
          el("p", { class: "sub" }, `Position size: ${a.position_size_quantity} -- ${a.position_size_note}`)
        );
      }
      if (a.ranking_note) {
        results.appendChild(el("p", { class: "sub" }, a.ranking_note));
      }
    } catch (err) {
      results.appendChild(errorBox(err));
    }
  }
  btn.addEventListener("click", load);
  load();
  return nodes;
}

function threatClass(level) {
  if (level === "Severe" || level === "Elevated") return "down";
  if (level === "Moderate") return "neutral";
  return "up";
}

async function renderScenarios() {
  const data = await safe("/api/scenarios");
  const nodes = [el("h2", {}, "Scenarios")];
  if (!data) {
    nodes.push(el("p", { class: "error" }, "Not enough data yet."));
    return nodes;
  }
  if (data.threat_level) {
    nodes.push(
      el("div", { class: "grid" }, [
        card("Threat Level", data.threat_level, "Combined Risk Off + Black Swan weight", threatClass(data.threat_level)),
      ])
    );
  }
  if (data.highest_risk) nodes.push(el("p", { class: "sub" }, `Highest risk: ${data.highest_risk}`));
  if (data.biggest_opportunity) nodes.push(el("p", { class: "sub" }, `Biggest opportunity: ${data.biggest_opportunity}`));
  for (const s of [...data.scenarios].sort((a, b) => b.probability_pct - a.probability_pct)) {
    nodes.push(
      card(s.name, `${s.probability_pct}%`, s.rationale)
    );
  }
  return nodes;
}

async function renderWhatif() {
  const nodes = [el("h2", {}, "What-If Scenario Simulator")];
  const list = await safe("/api/whatif");
  const select = el(
    "select",
    {},
    (list ? list.scenarios : []).map((s) => el("option", { value: s.key }, s.label))
  );
  const btn = el("button", {}, "Simulate");
  nodes.push(el("div", { class: "controls" }, [select, btn]));
  const results = el("div");
  nodes.push(results);

  async function load() {
    if (!select.value) return;
    results.innerHTML = "";
    try {
      const data = await fetchJSON(`/api/whatif/${encodeURIComponent(select.value)}`);
      results.innerHTML = "";
      results.appendChild(el("p", {}, data.description));
      results.appendChild(el("p", { class: "sub" }, `Data source: ${data.data_source.replace(/_/g, " ")}`));
      const impactRows = Object.entries(data.impact).map(([symbol, info]) => {
        if ("expected_return_7d_pct" in info) {
          const value = info.expected_return_7d_pct;
          return [
            symbol,
            value !== null ? `${value.toFixed(2)}% (7d)` : "no data",
            info.sample_size ? `${info.sample_size} occurrences` : (info.note || ""),
          ];
        }
        return [
          symbol,
          el("span", { class: info.direction === "bullish" ? "up" : info.direction === "bearish" ? "down" : "neutral" }, info.direction || "unclear"),
          info.correlation_30d !== null && info.correlation_30d !== undefined ? `correlation ${info.correlation_30d}` : (info.note || ""),
        ];
      });
      if (impactRows.length) {
        results.appendChild(table(["Symbol", "Impact", "Detail"], impactRows));
      }
      results.appendChild(
        el("div", { class: "grid" }, [
          card("Regime", `${data.current_regime || "unknown"} -> ${data.likely_regime_shift_toward.replace(/_/g, " ")}`),
          card("Risk", data.risk_direction),
          card("Liquidity", data.liquidity_direction),
        ])
      );
      results.appendChild(el("p", {}, data.reasoning));
    } catch (err) {
      results.innerHTML = "";
      results.appendChild(errorBox(err));
    }
  }
  btn.addEventListener("click", load);
  if (list && list.scenarios.length) load();
  return nodes;
}

async function renderWhales() {
  const data = await safe("/api/whales");
  const nodes = [el("h2", {}, "Whale Intelligence")];
  if (!data) return nodes;
  nodes.push(el("p", {}, [pill(data.available), " ", data.symbol]));
  if (data.available) {
    nodes.push(
      table(
        ["Field", "Value"],
        Object.entries(data)
          .filter(([k]) => k !== "available" && k !== "symbol")
          .map(([k, v]) => [
            k.replace(/_/g, " "),
            v == null ? "n/a" : typeof v === "number" ? v.toLocaleString() : String(v),
          ])
      )
    );
  } else {
    nodes.push(el("p", { class: "sub" }, data.reason));
    nodes.push(el("p", { class: "sub" }, `Would return: ${(data.would_return || []).join(", ")}`));
  }
  return nodes;
}

async function renderEtf() {
  const data = await safe("/api/etf");
  const nodes = [el("h2", {}, "ETF Flow Proxy")];
  if (!data) return nodes;
  nodes.push(el("p", {}, [pill(data.available)]));
  if (data.available) {
    nodes.push(
      el("div", { class: "grid" }, [
        card("Classification", data.classification),
        card("Bullish items", data.bullish_items),
        card("Bearish items", data.bearish_items),
        card("Neutral items", data.neutral_items),
      ])
    );
    nodes.push(el("p", { class: "sub" }, data.note));
  } else {
    nodes.push(el("p", { class: "sub" }, data.reason));
  }
  return nodes;
}

async function renderSignals() {
  const [signals, conviction] = await Promise.all([safe("/api/signals"), safe("/api/conviction")]);
  const nodes = [el("h2", {}, "Signals")];
  if (signals) {
    nodes.push(
      el("div", { class: "grid" }, [
        card("Bull score", signals.bull_score, null, "up"),
        card("Bear score", signals.bear_score, null, "down"),
        card("Net score", signals.net_score),
        card("Confidence", `${signals.confidence_pct}%`),
      ])
    );
    nodes.push(el("h2", {}, "Factors"));
    nodes.push(
      table(
        ["Factor", "Points", "Triggered"],
        Object.entries(signals.factors).map(([name, f]) => [
          name.replace(/_/g, " "),
          String(f.points),
          f.triggered == null ? "no data" : f.triggered ? "yes" : "no",
        ])
      )
    );
  } else {
    nodes.push(el("p", { class: "error" }, "No signal computed yet."));
  }
  if (conviction) {
    nodes.push(el("h2", {}, "Conviction"));
    nodes.push(
      el("p", {}, conviction.signal ? `Signal: ${conviction.signal.tier} (${conviction.signal.effective_confidence_pct}%)` : "n/a")
    );
    if (conviction.probability) {
      const p = conviction.probability;
      nodes.push(
        el("p", {}, `${p.symbol} probability: ${p.tier} (${p.effective_confidence_pct}%, sample size ${p.sample_size})`)
      );
      if (p.quality_multiplier != null) {
        nodes.push(
          el(
            "p",
            { class: "sub" },
            `Track record discount: x${p.quality_multiplier} (Prediction Quality Lab's own Brier score for this symbol/timeframe)`
          )
        );
      }
    }
  }
  return nodes;
}

async function renderReports() {
  const report = await safe("/api/report");
  const nodes = [el("h2", {}, "Reports")];
  if (!report) {
    nodes.push(el("p", { class: "error" }, "No report generated yet."));
    return nodes;
  }
  nodes.push(
    el("div", { class: "grid" }, [
      card("Type", report.report_type),
      card("Regime", report.regime),
      card("Risk Level", report.risk_level),
      card("Confidence", `${report.confidence_pct}%`),
      card("Generated", report.generated_at.slice(0, 19).replace("T", " ")),
    ])
  );
  nodes.push(decisionPill(report.risk_level, riskLevelTone(report.risk_level)));

  const ir = report.institutional_report;
  if (ir) {
    const section = (title, text) => [el("h2", {}, title), el("p", {}, text)];
    nodes.push(...section("Executive Summary", ir.executive_summary));
    nodes.push(el("p", { class: "up" }, `Main Opportunity: ${ir.biggest_opportunity}`));
    nodes.push(el("p", { class: "down" }, `Main Risk: ${ir.biggest_risk}`));
    if (ir.risk_detail) {
      nodes.push(el("p", { class: "sub" }, `Risk Detail: ${ir.risk_detail}`));
    }
    if (ir.watchdog_note) {
      nodes.push(el("p", { class: "sub" }, ir.watchdog_note));
    }
    if (ir.data_quality_note) {
      nodes.push(el("p", { class: "sub" }, ir.data_quality_note));
    }
    nodes.push(...section("Market Drivers", ir.market_drivers));
    nodes.push(...section("Sector Rotation", ir.sector_rotation));
    nodes.push(...section("Historical Comparison", ir.historical_comparison));
    nodes.push(...section("AI Conclusion", ir.ai_conclusion));
    nodes.push(...section("What to Watch Next", ir.what_to_watch_next));
  }

  nodes.push(el("h2", {}, "Institutional Summary"));
  nodes.push(renderStructured(report.institutional_summary));
  return nodes;
}

async function renderBreakout() {
  const nodes = [el("h2", {}, "Breakout Intelligence")];
  const symbolInput = el("input", { type: "text", value: "BTC", placeholder: "Symbol" });
  const tfSelect = el("select", {}, ["1d", "4h", "1h"].map((t) => el("option", { value: t }, t)));
  const btn = el("button", {}, "Load");
  nodes.push(el("div", { class: "controls" }, [symbolInput, tfSelect, btn]));
  const results = el("div");
  nodes.push(results);

  async function load() {
    results.innerHTML = "";
    try {
      const data = await fetchJSON(
        `/api/breakout/${encodeURIComponent(symbolInput.value)}?timeframe=${tfSelect.value}&limit=20`
      );
      results.innerHTML = "";
      if (!data.events.length) {
        results.appendChild(
          el("p", { class: "error" }, `No breakout/breakdown detected yet for ${data.symbol}.`)
        );
        return;
      }
      const latest = data.events[0];
      results.appendChild(
        el("div", { class: "grid" }, [
          card("Event", latest.event_type.replace(/_/g, " "), null, latest.direction === "bullish" ? "up" : "down"),
          card("Level", fmtNum(latest.level)),
          card("Price", fmtNum(latest.price)),
          card(
            "Probability",
            latest.probability_pct !== null ? `${latest.probability_pct}%` : "unavailable"
          ),
          card("Confidence", `${latest.confidence_pct}%`),
          card("Risk", latest.risk_score !== null ? `${latest.risk_score}/100` : "n/a"),
        ])
      );
      results.appendChild(el("p", { class: "sub" }, latest.expected_continuation));
      results.appendChild(el("p", {}, latest.reasoning));
      results.appendChild(el("h2", {}, "History"));
      results.appendChild(
        table(
          ["Time", "Event", "Direction", "Probability", "Confidence"],
          data.events.map((e) => [
            e.computed_at.slice(0, 16).replace("T", " "),
            e.event_type.replace(/_/g, " "),
            el("span", { class: e.direction === "bullish" ? "up" : "down" }, e.direction),
            e.probability_pct !== null ? `${e.probability_pct}%` : "n/a",
            `${e.confidence_pct}%`,
          ])
        )
      );
    } catch (err) {
      results.innerHTML = "";
      results.appendChild(errorBox(err));
    }
  }
  btn.addEventListener("click", load);
  load();
  return nodes;
}

async function renderFeatures() {
  const nodes = [el("h2", {}, "Feature Signals")];
  nodes.push(
    el(
      "p",
      { class: "sub" },
      "Beta, cointegration, market breadth, multi-window momentum and funding-rate/open-interest " +
        "momentum -- everything Feature Engine computes on every scheduled cycle that no other " +
        "screen shows."
    )
  );
  const symbolInput = el("input", { type: "text", value: "BTC", placeholder: "Symbol" });
  const btn = el("button", {}, "Load");
  nodes.push(el("div", { class: "controls" }, [symbolInput, btn]));
  const results = el("div");
  nodes.push(results);

  async function load() {
    results.innerHTML = "";
    try {
      const data = await fetchJSON(
        `/api/features/${encodeURIComponent(symbolInput.value)}?compute=true`
      );
      results.innerHTML = "";
      const f = data.features;
      if (!f || !Object.keys(f).length) {
        results.appendChild(
          el("p", { class: "error" }, `No feature data available for ${data.symbol} yet.`)
        );
        return;
      }
      const cards = [];
      for (const [key, value] of Object.entries(f)) {
        if (key.startsWith("momentum_")) {
          const window = key.slice("momentum_".length, -"d_pct".length);
          cards.push(card(`Momentum ${window}d`, fmtPct(value), null, changeClass(value)));
        } else if (key.startsWith("beta_vs_")) {
          cards.push(card(`Beta vs ${key.slice("beta_vs_".length).toUpperCase()}`, fmtNum(value)));
        } else if (key === "market_breadth_mag7_pct") {
          cards.push(card("Mag 7 Breadth", fmtPct(value), null, changeClass(value)));
        } else if (key === "funding_rate_momentum_pct") {
          cards.push(card("Funding Rate Momentum", fmtPct(value), null, changeClass(value)));
        } else if (key === "open_interest_change_pct") {
          cards.push(card("Open Interest Change", fmtPct(value), null, changeClass(value)));
        }
      }
      results.appendChild(el("div", { class: "grid" }, cards));
      for (const [key, value] of Object.entries(f)) {
        if (key.startsWith("cointegration_vs_")) {
          const benchmark = key.slice("cointegration_vs_".length).toUpperCase();
          const stationary = value.is_stationary ? "cointegrated" : "not cointegrated";
          results.appendChild(
            el(
              "p",
              { class: "sub" },
              `Cointegration vs ${benchmark}: hedge ratio ${value.hedge_ratio.toFixed(3)}, ` +
                `${stationary} (stat ${value.statistic.toFixed(2)})`
            )
          );
        }
      }
      results.appendChild(
        el("p", { class: "sub" }, `Computed at ${data.computed_at.slice(0, 16).replace("T", " ")}`)
      );
    } catch (err) {
      results.innerHTML = "";
      results.appendChild(errorBox(err));
    }
  }
  btn.addEventListener("click", load);
  await load();
  return nodes;
}

async function renderOnchain() {
  const nodes = [el("h2", {}, "On-Chain Intelligence")];
  const symbolInput = el("input", { type: "text", value: "BTC", placeholder: "Symbol" });
  const btn = el("button", {}, "Load");
  nodes.push(el("div", { class: "controls" }, [symbolInput, btn]));
  const results = el("div");
  nodes.push(results);

  async function load() {
    results.innerHTML = "";
    try {
      const data = await fetchJSON(`/api/onchain/${encodeURIComponent(symbolInput.value)}`);
      results.innerHTML = "";
      results.appendChild(el("p", {}, [pill(data.available), " ", data.symbol]));
      results.appendChild(el("p", { class: "sub" }, data.reason));
      if (data.solana_note) {
        results.appendChild(el("p", { class: "sub" }, data.solana_note));
      }
      results.appendChild(
        table(
          ["Metric", "Value"],
          Object.entries(data.metrics).map(([k, v]) => [
            k.replace(/_/g, " "),
            v == null ? "unavailable" : typeof v === "number" ? v.toLocaleString() : String(v),
          ])
        )
      );
    } catch (err) {
      results.innerHTML = "";
      results.appendChild(errorBox(err));
    }
  }
  btn.addEventListener("click", load);
  load();
  return nodes;
}

async function renderReplay() {
  const nodes = [el("h2", {}, "Market Replay")];
  const [data, insight] = await Promise.all([safe("/api/replay?limit=20"), safe("/api/replay/insight")]);
  if (!data || !data.snapshots.length) {
    nodes.push(el("p", { class: "error" }, "No market snapshot has been taken yet."));
    return nodes;
  }
  const latest = data.snapshots[0];
  nodes.push(
    el("div", { class: "grid" }, [
      card("Regime", (latest.regime || "unknown").replace(/_/g, " ")),
      card("Health", latest.health_score ?? "n/a"),
      card("Trend Strength", latest.trend_strength_score ?? "n/a"),
      card("Risk", latest.risk_score ?? "n/a"),
      card("Confidence", latest.confidence_score ?? "n/a"),
    ])
  );
  nodes.push(...renderAiInsight(insight));
  if (latest.consensus) {
    nodes.push(el("h2", {}, "Consensus"));
    nodes.push(
      el("div", { class: "grid" }, [
        card("Bullish", `${latest.consensus.bullish_pct}%`, null, "up"),
        card("Bearish", `${latest.consensus.bearish_pct}%`, null, "down"),
        card("Conflict", `${latest.consensus.conflict_pct}%`),
      ])
    );
  }
  if (latest.portfolio_advice) {
    nodes.push(el("h2", {}, "Portfolio Advice"));
    nodes.push(
      card(latest.portfolio_advice.symbol, latest.portfolio_advice.recommendation, latest.portfolio_advice.reasoning)
    );
  }
  nodes.push(el("h2", {}, "Alerts since previous snapshot"));
  nodes.push(el("p", { class: "sub" }, `${latest.alerts.length} detection(s)`));

  nodes.push(el("h2", {}, "Recent Snapshots"));
  nodes.push(
    table(
      ["Time", "Regime", "Health", "Risk"],
      data.snapshots.map((s) => [
        s.computed_at.slice(0, 16).replace("T", " "),
        (s.regime || "unknown").replace(/_/g, " "),
        s.health_score ?? "n/a",
        s.risk_score ?? "n/a",
      ])
    )
  );

  nodes.push(el("h2", {}, "Compare Two Snapshots"));
  const t1 = el("input", { type: "text", placeholder: "t1 (ISO timestamp)" });
  const t2 = el("input", { type: "text", placeholder: "t2 (ISO timestamp)" });
  const btn = el("button", {}, "Compare");
  nodes.push(el("div", { class: "controls" }, [t1, t2, btn]));
  const results = el("div");
  nodes.push(results);
  btn.addEventListener("click", async () => {
    results.innerHTML = "";
    try {
      const diff = await fetchJSON(
        `/api/replay/compare?t1=${encodeURIComponent(t1.value)}&t2=${encodeURIComponent(t2.value)}`
      );
      results.appendChild(renderStructured(diff));
    } catch (err) {
      results.appendChild(errorBox(err));
    }
  });
  nodes.push(navPointer("replay"));
  return nodes;
}

async function renderPortfolio() {
  const nodes = [el("h2", {}, "Portfolio")];
  const health = await safe("/api/portfolio");
  const results = el("div");
  nodes.push(results);

  function draw(health) {
    results.innerHTML = "";
    if (!health || health.empty) {
      results.appendChild(el("p", { class: "error" }, "Portfolio is empty."));
      return;
    }
    results.appendChild(
      el("div", { class: "grid" }, [
        card("Total value", fmtNum(health.total_value)),
        card("Health score", health.health_score != null ? `${health.health_score}/100` : "n/a"),
        card("Diversification", health.diversification_score != null ? `${health.diversification_score}/100` : "n/a"),
        card("Max drawdown", health.max_drawdown_pct != null ? `${health.max_drawdown_pct}%` : "unavailable"),
      ])
    );
    results.appendChild(
      table(
        ["Symbol", "Qty", "Price", "Value", "P&L"],
        health.positions.map((p) =>
          p.priced
            ? [p.symbol, String(p.quantity), fmtNum(p.price), fmtNum(p.value), fmtPct(p.unrealized_pnl_pct)]
            : [p.symbol, String(p.quantity), "n/a", "n/a", "n/a"]
        )
      )
    );
  }
  draw(health);

  const symbolInput = el("input", { type: "text", placeholder: "Symbol" });
  const qtyInput = el("input", { type: "text", placeholder: "Quantity" });
  const priceInput = el("input", { type: "text", placeholder: "Entry price (optional)" });
  const addBtn = el("button", {}, "Add position");
  addBtn.addEventListener("click", async () => {
    try {
      await fetchJSONWithAdminKey("/api/portfolio/positions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: symbolInput.value,
          quantity: parseFloat(qtyInput.value),
          entry_price: priceInput.value ? parseFloat(priceInput.value) : null,
        }),
      });
      draw(await fetchJSON("/api/portfolio"));
    } catch (err) {
      results.prepend(errorBox(err));
    }
  });
  nodes.push(el("h2", {}, "Add Position"));
  nodes.push(el("div", { class: "controls" }, [symbolInput, qtyInput, priceInput, addBtn]));
  return nodes;
}

async function renderAlerts() {
  const nodes = [el("h2", {}, "Configurable Alerts")];
  nodes.push(
    el(
      "p",
      { class: "sub" },
      "Custom threshold rules, scoped by Telegram chat ID -- there is no login on this " +
        "platform yet, so use the chat ID you created rules from (e.g. via /setalert)."
    )
  );

  const chatIdInput = el("input", { type: "text", placeholder: "Chat ID" });
  const loadBtn = el("button", {}, "Load");
  const results = el("div");
  nodes.push(el("div", { class: "controls" }, [chatIdInput, loadBtn]), results);

  async function draw() {
    const chatId = chatIdInput.value.trim();
    if (!chatId) return;
    results.innerHTML = "";
    try {
      const rulesData = await fetchJSON(`/api/alerts/rules?chat_id=${encodeURIComponent(chatId)}`);
      if (!rulesData.rules.length) {
        results.appendChild(el("p", { class: "error" }, "No rules for this chat ID yet."));
      } else {
        results.appendChild(
          table(
            ["ID", "Symbol", "Metric", "Operator", "Threshold", "Enabled", "Last triggered", ""],
            rulesData.rules.map((r) => {
              const delBtn = el("button", {}, "Delete");
              delBtn.addEventListener("click", async () => {
                try {
                  await fetchJSONWithAdminKey(
                    `/api/alerts/rules/${r.id}?chat_id=${encodeURIComponent(chatId)}`,
                    { method: "DELETE" }
                  );
                  draw();
                } catch (err) {
                  results.prepend(errorBox(err));
                }
              });
              return [
                String(r.id), r.symbol, r.metric, r.operator, String(r.threshold),
                r.enabled ? "yes" : "no", r.last_triggered_at || "never", delBtn,
              ];
            })
          )
        );
      }

      const historyData = await fetchJSON(
        `/api/alerts/history?chat_id=${encodeURIComponent(chatId)}&limit=20`
      );
      results.appendChild(el("h2", {}, "Recent Firings"));
      if (!historyData.history.length) {
        results.appendChild(el("p", { class: "sub" }, "No custom alerts have fired yet."));
      } else {
        results.appendChild(
          table(
            ["Symbol", "Metric", "Value", "Operator", "Threshold"],
            historyData.history.map((h) => [
              h.symbol, h.metric, String(h.value), h.operator, String(h.threshold),
            ])
          )
        );
      }
    } catch (err) {
      results.appendChild(errorBox(err));
    }
  }
  loadBtn.addEventListener("click", draw);

  nodes.push(el("h2", {}, "Create Rule"));
  const symbolInput = el("input", { type: "text", placeholder: "Symbol (e.g. BTC)" });
  const metricSelect = el(
    "select", {},
    [
      "price",
      "change_pct_24h",
      "probability_edge",
      "breakout_probability",
      "risk_off_score",
      "liquidity_score",
    ].map((m) => el("option", { value: m }, m))
  );
  const operatorSelect = el("select", {}, ["above", "below"].map((o) => el("option", { value: o }, o)));
  const thresholdInput = el("input", { type: "text", placeholder: "Threshold" });
  const cooldownInput = el("input", { type: "text", placeholder: "Cooldown minutes (60)" });
  const createBtn = el("button", {}, "Create rule");
  const createStatus = el("p", { class: "sub" });
  createBtn.addEventListener("click", async () => {
    const chatId = chatIdInput.value.trim();
    if (!chatId) {
      createStatus.textContent = "Enter a chat ID above first.";
      return;
    }
    try {
      await fetchJSONWithAdminKey("/api/alerts/rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: chatId,
          symbol: symbolInput.value,
          metric: metricSelect.value,
          operator: operatorSelect.value,
          threshold: parseFloat(thresholdInput.value),
          cooldown_minutes: cooldownInput.value ? parseInt(cooldownInput.value, 10) : 60,
        }),
      });
      createStatus.textContent = "Rule created.";
      draw();
    } catch (err) {
      createStatus.textContent = `Error: ${err.message}`;
    }
  });
  nodes.push(
    el("div", { class: "controls" }, [
      symbolInput, metricSelect, operatorSelect, thresholdInput, cooldownInput, createBtn,
    ]),
    createStatus
  );

  return nodes;
}

async function renderMemory() {
  const nodes = [el("h2", {}, "Market Memory")];
  nodes.push(
    el(
      "p",
      { class: "sub" },
      "A read-only timeline across every table this platform persists -- predictions, signals, " +
        "regime, correlations, patterns, similarity matches, knowledge rules, whale/ETF snapshots, " +
        "sentiment, macro events, news, alerts, reports, global score. Nothing here is recomputed, " +
        "only indexed."
    )
  );

  const meta = await safe("/api/memory?limit=1");
  const categories = meta ? meta.categories : [];

  const categorySelect = el(
    "select",
    {},
    [el("option", { value: "" }, "All categories"), ...categories.map((c) => el("option", { value: c }, c))]
  );
  const limitInput = el("input", { type: "text", value: "50", placeholder: "Limit", style: "width:80px" });
  const sinceInput = el("input", { type: "datetime-local" });
  const loadBtn = el("button", {}, "Load");
  nodes.push(el("div", { class: "controls" }, [categorySelect, limitInput, sinceInput, loadBtn]));

  const results = el("div");
  nodes.push(results);

  async function load() {
    results.innerHTML = "";
    results.appendChild(el("p", { class: "loading" }, "Loading..."));
    try {
      const params = new URLSearchParams();
      if (categorySelect.value) params.set("category", categorySelect.value);
      params.set("limit", limitInput.value || "50");
      if (sinceInput.value) params.set("since", new Date(sinceInput.value).toISOString());
      const data = await fetchJSON(`/api/memory?${params.toString()}`);
      results.innerHTML = "";
      if (!data.entries.length) {
        results.appendChild(el("p", { class: "error" }, "No entries recorded yet for this filter."));
        return;
      }
      results.appendChild(
        table(
          ["Time", "Category", "Summary"],
          data.entries.map((e) => [
            e.timestamp.slice(0, 19).replace("T", " "),
            e.category,
            Object.entries(e.summary)
              .map(([k, v]) => `${k}: ${v}`)
              .join(" | "),
          ])
        )
      );
    } catch (err) {
      results.innerHTML = "";
      results.appendChild(errorBox(err));
    }
  }
  loadBtn.addEventListener("click", load);
  await load();

  return nodes;
}

async function renderSettings() {
  const nodes = [el("h2", {}, "Settings")];
  nodes.push(
    el("p", { class: "sub" }, "Configuration lives in .env (see .env.example in the repository) -- no secrets are exposed through this dashboard.")
  );

  nodes.push(el("h2", {}, "Historical Data Sync"));
  nodes.push(
    el(
      "p",
      { class: "sub" },
      "Backfills the History/Events/Patterns pages' OHLCV data, curated events and economic " +
        "calendar. Runs in the background on this deployment; can take several minutes."
    )
  );
  const yearsInput = el("input", { type: "text", value: "10", placeholder: "Years" });
  const syncBtn = el("button", {}, "Sync now");
  const statusBox = el("p", { class: "sub" });
  nodes.push(el("div", { class: "controls" }, [yearsInput, syncBtn]), statusBox);

  async function pollStatus() {
    try {
      const s = await fetchJSON("/api/admin/sync-history");
      statusBox.textContent = `Status: ${s.state}` + (s.error ? ` (${s.error})` : "");
      if (s.state === "running") setTimeout(pollStatus, 5000);
    } catch (err) {
      statusBox.textContent = `Error checking status: ${err.message}`;
    }
  }
  syncBtn.addEventListener("click", async () => {
    try {
      const years = parseInt(yearsInput.value, 10) || 10;
      const s = await fetchJSON(`/api/admin/sync-history?years=${years}`, { method: "POST" });
      statusBox.textContent = `Status: ${s.state}`;
      pollStatus();
    } catch (err) {
      statusBox.textContent = `Error: ${err.message}`;
    }
  });
  await pollStatus();

  nodes.push(el("h2", {}, "Browser Notifications"));
  nodes.push(
    el(
      "p",
      { class: "sub" },
      "Native browser notifications for newly broadcast Watchdog alerts -- the same ones shown " +
        "in Live Alerts on Overview and Watchdog Hub's Alert History. Checked every 60s while " +
        "this tab is open, regardless of which page you're on."
    )
  );
  const notifStatus = el("p", { class: "sub" });
  const notifBtn = el("button", {}, "");
  function drawNotifState() {
    if (!NotificationWatcher.isSupported()) {
      notifStatus.textContent = "Not supported in this browser.";
      notifBtn.style.display = "none";
      return;
    }
    const perm = NotificationWatcher.permission();
    if (perm === "denied") {
      notifStatus.textContent =
        "Blocked at the browser level -- re-enable notifications for this site in your browser settings.";
      notifBtn.style.display = "none";
      return;
    }
    notifBtn.style.display = "";
    if (perm === "granted" && NotificationWatcher.isEnabled()) {
      notifStatus.textContent = "Enabled.";
      notifBtn.textContent = "Disable";
    } else {
      notifStatus.textContent =
        perm === "granted" ? "Permission granted, not enabled." : "Not enabled.";
      notifBtn.textContent = "Enable";
    }
  }
  notifBtn.addEventListener("click", async () => {
    if (NotificationWatcher.isEnabled()) {
      NotificationWatcher.setEnabled(false);
      drawNotifState();
      return;
    }
    const perm = await NotificationWatcher.requestPermission();
    if (perm === "granted") NotificationWatcher.setEnabled(true);
    drawNotifState();
  });
  drawNotifState();
  nodes.push(el("div", { class: "controls" }, [notifBtn]), notifStatus);

  return nodes;
}

// ---- Browser Notifications ------------------------------------------------
// Frontend-only: polls the same /api/watchdog/events feed Live Alerts
// (Overview) and Watchdog Hub's own Alert History table already show,
// independent of which page is currently open -- same "persists across
// navigation" pattern as RealtimeStore.subscribeStatus below. Only ever
// fires a native Notification for entries with summary.broadcast === true
// (the same "was this actually significant enough to send" flag the
// Watchdog Hub table already displays as sent/suppressed), so enabling this
// never turns into notification spam from suppressed low-tier detections.
// Silently does nothing if the Notification API isn't available or
// permission hasn't been granted -- Settings shows the real permission
// state, never a fake "enabled" toggle.

const _NOTIFICATIONS_ENABLED_KEY = "dashboard_notifications_enabled";
const _NOTIFICATIONS_LAST_SEEN_KEY = "dashboard_notifications_last_seen";
const _NOTIFICATIONS_POLL_MS = 60000;

const NotificationWatcher = (() => {
  let timer = null;

  function isSupported() {
    return typeof Notification !== "undefined";
  }

  function isEnabled() {
    return localStorage.getItem(_NOTIFICATIONS_ENABLED_KEY) === "1";
  }

  function setEnabled(value) {
    localStorage.setItem(_NOTIFICATIONS_ENABLED_KEY, value ? "1" : "0");
  }

  function permission() {
    return isSupported() ? Notification.permission : "unsupported";
  }

  async function requestPermission() {
    if (!isSupported()) return "unsupported";
    return Notification.requestPermission();
  }

  async function poll() {
    if (!isEnabled() || !isSupported() || Notification.permission !== "granted") return;
    const data = await safe("/api/watchdog/events?limit=10");
    if (!data || !data.entries || !data.entries.length) return;

    const seenBefore = localStorage.getItem(_NOTIFICATIONS_LAST_SEEN_KEY);
    if (!seenBefore) {
      // First time notifications have ever run -- establish the watermark
      // without notifying for everything already in history.
      localStorage.setItem(_NOTIFICATIONS_LAST_SEEN_KEY, data.entries[0].timestamp);
      return;
    }

    const newEntries = data.entries.filter((e) => e.summary.broadcast && e.timestamp > seenBefore);
    for (const entry of newEntries.slice(0, 3)) {
      new Notification(`${entry.summary.alert_type} (${entry.summary.conviction_tier})`, {
        body: entry.summary.message,
      });
    }
    localStorage.setItem(_NOTIFICATIONS_LAST_SEEN_KEY, data.entries[0].timestamp);
  }

  function start() {
    if (timer) return;
    poll();
    timer = setInterval(poll, _NOTIFICATIONS_POLL_MS);
  }

  return { isSupported, isEnabled, setEnabled, permission, requestPermission, start };
})();

// ---- Asset Detail (Live Dashboard Upgrade Phase 2) -----------------------
// One unified per-symbol page composed entirely from existing engines' own
// endpoints -- no new backend computation, no duplicated forecast/trade
// logic. Every section below is independently optional: a symbol with no
// on-chain/whale/pattern data for its asset class (e.g. a stock) simply
// omits that section instead of showing a fabricated placeholder, the same
// honesty convention every other page already follows.

const ASSET_DETAIL_HORIZONS = ["24h", "3d", "7d", "30d"];

function assetPriceHeader(symbol, quote) {
  return el("div", { class: "ticker" }, [tickerItem(symbol, quote)]);
}

function assetForecastCard(symbol, forecast, horizon) {
  if (!forecast) {
    return el(
      "p",
      { class: "error" },
      `AI Forecast: not enough data yet for ${symbol} (${horizon}).`
    );
  }
  const dirCls = changeClass(forecast.expected_change_pct);
  const nodes = [
    el("div", { class: "grid" }, [
      card("Current Price", fmtNum(forecast.current_price)),
      card("Target Price", fmtNum(forecast.target_price), fmtPct(forecast.expected_change_pct), dirCls),
      card("Direction", forecast.direction, `${forecast.probability_pct}% probability`, dirCls),
      card(
        "Conviction",
        forecast.confidence ? forecast.confidence.tier : "n/a",
        forecast.confidence ? `${forecast.confidence.effective_confidence_pct}% effective` : null
      ),
      card("Risk Meter", forecast.risk_meter || "n/a"),
      card(
        "Expected Range",
        forecast.expected_range && forecast.expected_range.low != null
          ? `${fmtNum(forecast.expected_range.low)} - ${fmtNum(forecast.expected_range.high)}`
          : "n/a"
      ),
    ]),
  ];
  if (forecast.key_levels) {
    const kl = forecast.key_levels;
    nodes.push(
      el("div", { class: "grid" }, [
        card("Support", kl.support_1 != null ? fmtNum(kl.support_1) : "n/a"),
        card("Resistance", kl.resistance_1 != null ? fmtNum(kl.resistance_1) : "n/a"),
        card("Invalidation", kl.invalidation_level != null ? fmtNum(kl.invalidation_level) : "n/a"),
        card("Breakout Level", kl.breakout_level != null ? fmtNum(kl.breakout_level) : "n/a"),
      ])
    );
  }
  nodes.push(forecastTrackRecordLine(forecast.track_record));
  if (forecast.ai_explanation) {
    nodes.push(el("h3", {}, "Why AI Thinks This"));
    nodes.push(whyFinalPrediction(forecast.ai_explanation.final_prediction));
    nodes.push(whyEngineBreakdown(forecast.ai_explanation.engine_breakdown));
  }
  return el("div", {}, nodes);
}

function assetTradeSetupCard(setup) {
  if (!setup) return null;
  if (setup.recommendation === "NO_TRADE") {
    const nodes = [el("p", {}, [pill(false), " ", el("strong", {}, "NO TRADE")])];
    if (setup.reasons && setup.reasons.length) {
      nodes.push(
        table(
          ["Reason", "Description"],
          setup.reasons.map((r) => [r.code.replace(/_/g, " "), r.description])
        )
      );
    }
    return el("div", {}, nodes);
  }
  const nodes = [
    el("p", {}, [
      pill(true),
      " ",
      el("strong", { class: setup.side === "BUY" ? "up" : "down" }, `${setup.side} setup`),
    ]),
    el("div", { class: "grid" }, [
      card("Entry", fmtNum(setup.entry_price)),
      card("Stop Loss", fmtNum(setup.stop_loss_price), null, "down"),
      card("Take Profit", fmtNum(setup.take_profit_price), null, "up"),
      card("Risk/Reward", setup.risk_reward_ratio != null ? setup.risk_reward_ratio.toFixed(2) : "n/a"),
      card("Conviction", setup.conviction_tier || "n/a"),
    ]),
  ];
  if (setup.trade_economics) {
    const te = setup.trade_economics;
    nodes.push(
      el(
        "p",
        { class: "sub" },
        `Historical expectancy (${te.sample_count} trades, ${te.sample_sufficiency}): ` +
          `win rate ${fmtPct(te.win_rate_pct)}, expectancy ${fmtPct(te.expectancy_pct)}`
      )
    );
  }
  return el("div", {}, nodes);
}

async function renderAssetDetail(params) {
  const symbol = ((params && params.get("symbol")) || "BTC").toUpperCase();
  const horizon = ASSET_DETAIL_HORIZONS.includes(params && params.get("horizon"))
    ? params.get("horizon")
    : "24h";

  const nodes = [el("h2", {}, `Asset Detail: ${symbol}`)];

  const symbolInput = el("input", { type: "text", value: symbol, placeholder: "Symbol" });
  const horizonSelect = el(
    "select",
    {},
    ASSET_DETAIL_HORIZONS.map((h) => el("option", { value: h, ...(h === horizon ? { selected: "selected" } : {}) }, h))
  );
  const loadBtn = el("button", {}, "Load");
  loadBtn.addEventListener("click", () => {
    const nextSymbol = symbolInput.value.trim().toUpperCase();
    if (!nextSymbol) return;
    navigate("assetdetail", new URLSearchParams({ symbol: nextSymbol, horizon: horizonSelect.value }));
  });
  nodes.push(el("div", { class: "controls" }, [symbolInput, horizonSelect, loadBtn]));

  const [
    market,
    forecast,
    tradeSetup,
    technical,
    probability,
    patterns,
    breakout,
    onchain,
    whales,
    similar,
    knowledge,
    quality,
    learning,
    correlations,
  ] = await Promise.all([
    safe("/api/market"),
    safe(`/api/forecast/${encodeURIComponent(symbol)}?horizon=${horizon}`),
    safe(`/api/trade-setup/${encodeURIComponent(symbol)}?horizon=${horizon}`),
    safe(`/api/technical/${encodeURIComponent(symbol)}`),
    safe(`/api/probability/${encodeURIComponent(symbol)}`),
    safe(`/api/patterns/${encodeURIComponent(symbol)}?timeframe=1d&limit=10`),
    safe(`/api/breakout/${encodeURIComponent(symbol)}?timeframe=1d&limit=5`),
    safe(`/api/onchain/${encodeURIComponent(symbol)}`),
    safe(`/api/whales?symbol=${encodeURIComponent(symbol)}`),
    safe(`/api/similar/${encodeURIComponent(symbol)}`),
    safe(`/api/knowledge/${encodeURIComponent(symbol)}`),
    safe(`/api/quality/${encodeURIComponent(symbol)}?timeframe=1d`),
    safe(`/api/learning/${encodeURIComponent(symbol)}?timeframe=1d`),
    safe("/api/correlations"),
  ]);

  const quote = market && market.quotes ? market.quotes.find((q) => q.symbol === symbol) : null;
  nodes.push(assetPriceHeader(symbol, quote));

  nodes.push(el("h2", {}, `AI Forecast (${horizon})`));
  nodes.push(assetForecastCard(symbol, forecast, horizon));

  const setupCard = assetTradeSetupCard(tradeSetup);
  if (setupCard) {
    nodes.push(el("h2", {}, "Trade Setup"));
    nodes.push(setupCard);
  }

  if (technical) {
    nodes.push(el("h2", {}, "Technical Snapshot"));
    nodes.push(
      el("div", { class: "grid" }, [
        card("Bullish Score", technical.bullish_score != null ? technical.bullish_score.toFixed(0) : "n/a"),
        card("Bearish Score", technical.bearish_score != null ? technical.bearish_score.toFixed(0) : "n/a"),
        card("Trend Strength", technical.trend_strength != null ? technical.trend_strength.toFixed(0) : "n/a"),
        card("Momentum", technical.momentum != null ? technical.momentum.toFixed(1) : "n/a"),
        card("Volatility", technical.volatility != null ? technical.volatility.toFixed(0) : "n/a"),
        card("Support", technical.support != null ? fmtNum(technical.support) : "n/a"),
        card("Resistance", technical.resistance != null ? fmtNum(technical.resistance) : "n/a"),
      ])
    );
  }

  if (probability) {
    nodes.push(el("h2", {}, "Probability"));
    nodes.push(
      el("div", { class: "grid" }, [
        card("Bullish", `${probability.prob_up_pct}%`, null, "up"),
        card("Bearish", `${probability.prob_down_pct}%`, null, "down"),
        card("Neutral", `${probability.prob_flat_pct}%`),
        card("Sample size", probability.sample_size),
      ])
    );
    nodes.push(
      el(
        "p",
        { class: "sub" },
        `Reference RSI ${probability.reference_rsi.toFixed(1)}, avg forward return ${fmtPct(probability.avg_forward_return_pct, 4)}`
      )
    );
  }

  if (patterns && patterns.patterns && patterns.patterns.length) {
    nodes.push(el("h2", {}, "Recent Patterns"));
    nodes.push(
      table(
        ["Date", "Pattern", "Direction"],
        patterns.patterns.slice(0, 8).map((p) => [
          p.timestamp.slice(0, 10),
          p.pattern_name.replace(/_/g, " "),
          el(
            "span",
            { class: p.direction === "bullish" ? "up" : p.direction === "bearish" ? "down" : "neutral" },
            p.direction
          ),
        ])
      )
    );
  }

  if (breakout && breakout.events && breakout.events.length) {
    const latest = breakout.events[0];
    nodes.push(el("h2", {}, "Breakout Intelligence"));
    nodes.push(
      el("div", { class: "grid" }, [
        card("Event", latest.event_type.replace(/_/g, " "), null, latest.direction === "bullish" ? "up" : "down"),
        card("Probability", latest.probability_pct !== null ? `${latest.probability_pct}%` : "unavailable"),
        card("Confidence", `${latest.confidence_pct}%`),
        card("Risk", latest.risk_score !== null ? `${latest.risk_score}/100` : "n/a"),
      ])
    );
    nodes.push(el("p", { class: "sub" }, latest.expected_continuation));
  }

  if (onchain && onchain.available) {
    nodes.push(el("h2", {}, "On-Chain Intelligence"));
    nodes.push(
      table(
        ["Metric", "Value"],
        Object.entries(onchain.metrics).map(([k, v]) => [
          k.replace(/_/g, " "),
          v == null ? "unavailable" : typeof v === "number" ? v.toLocaleString() : String(v),
        ])
      )
    );
  }

  if (whales && whales.available) {
    nodes.push(el("h2", {}, "Whale Intelligence"));
    nodes.push(
      table(
        ["Field", "Value"],
        Object.entries(whales)
          .filter(([k]) => k !== "available" && k !== "symbol")
          .map(([k, v]) => [
            k.replace(/_/g, " "),
            v == null ? "n/a" : typeof v === "number" ? v.toLocaleString() : String(v),
          ])
      )
    );
  }

  if (similar && similar.matches && similar.matches.length) {
    nodes.push(el("h2", {}, "Historical Similarity"));
    if (similar.lesson) {
      nodes.push(el("p", { class: "sub" }, similar.lesson.main_lesson));
    }
    nodes.push(
      table(
        ["Date", "Similarity", "Regime", "7d"],
        similar.matches.slice(0, 8).map((m) => [
          m.date.slice(0, 10),
          String(m.similarity),
          m.market_regime || "unknown",
          fmtPct(m.forward_returns_pct["7d"]),
        ])
      )
    );
  }
  if (knowledge && knowledge.analogs && knowledge.analogs.length) {
    nodes.push(el("h2", {}, "Nearest Historical Analogs"));
    nodes.push(
      table(
        ["Date", "RSI", "7d forward", "Nearby event(s)"],
        knowledge.analogs.slice(0, 8).map((a) => [
          a.timestamp.slice(0, 10),
          a.rsi.toFixed(1),
          fmtPct(a.forward_returns_pct["7d"]),
          a.nearby_events.length ? a.nearby_events.map((e) => e.title).join(", ") : "-",
        ])
      )
    );
  }

  if (quality && quality.evaluated_predictions) {
    nodes.push(el("h2", {}, "Prediction Quality"));
    nodes.push(
      el("div", { class: "grid" }, [
        card("Evaluated predictions", quality.evaluated_predictions),
        card("Accuracy", `${quality.accuracy_pct}%`),
        card("Brier score", quality.brier_score),
        card("Avg calibration error", `${quality.average_error_pct}%`),
      ])
    );
  }

  if (learning && learning.evaluated_predictions) {
    nodes.push(el("h2", {}, "Self-Learning Accuracy"));
    nodes.push(
      el("div", { class: "grid" }, [
        card("Evaluated predictions", learning.evaluated_predictions),
        card("Accuracy", `${learning.accuracy_pct}%`),
      ])
    );
  }

  if (correlations && correlations.correlations && correlations.correlations.length) {
    const related = correlations.correlations
      .filter((c) => c.symbol_a === symbol || c.symbol_b === symbol)
      .sort((a, b) => Math.abs(b.correlation) - Math.abs(a.correlation))
      .slice(0, 8);
    if (related.length) {
      nodes.push(el("h2", {}, "Correlations"));
      nodes.push(
        table(
          ["Pair", "Window", "Correlation"],
          related.map((c) => [`${c.symbol_a}/${c.symbol_b}`, `${c.window_days}d`, heatCell(c.correlation, c.correlation.toFixed(2))])
        )
      );
    }
  }

  return nodes;
}

// ---- Futures Simulator ----------------------------------------------------
// 100% demo/paper trading -- every number here comes from the real
// /api/simulator/* endpoints (real market data drives fills; only the
// account/position/order state is simulated). No real money, no real
// Binance orders, ever. See docs/FUTURES_SIMULATOR.md.

const FUTURES_ACCOUNT_NAME_KEY = "futures_sim_account_name";
function futuresAccountName() {
  return localStorage.getItem(FUTURES_ACCOUNT_NAME_KEY) || "default";
}

const FUTURES_TABS = [
  "trade",
  "positions",
  "orders",
  "order-history",
  "trade-history",
  "performance",
  "risk",
  "account-history",
  "settings",
];
const FUTURES_TAB_LABELS = {
  trade: "Trade",
  positions: "Positions",
  orders: "Open Orders",
  "order-history": "Order History",
  "trade-history": "Trade History",
  performance: "Performance",
  risk: "Risk",
  "account-history": "Account History",
  settings: "Settings",
};

const CHART_TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h", "1d", "4d"];
const CHART_TIMEFRAME_STORAGE_KEY = "futures_chart_tf";

function chartTimeframeTabs(current, onSelect) {
  const row = el("div", { class: "forecast-tabs" });
  for (const tf of CHART_TIMEFRAMES) {
    const btn = el("button", { class: `forecast-tab${tf === current ? " active" : ""}` }, tf);
    btn.addEventListener("click", () => onSelect(tf));
    row.appendChild(btn);
  }
  return row;
}

async function renderFuturesTradeTab() {
  const wrap = el("div", {});
  const symbolsData = await safe("/api/simulator/symbols");
  const symbols = symbolsData ? symbolsData.symbols : [];
  if (!symbols.length) {
    wrap.appendChild(el("p", { class: "error" }, "No symbols available."));
    return wrap;
  }

  const symbolSelect = el(
    "select",
    {},
    symbols.map((s) => el("option", { value: s.symbol }, s.symbol))
  );
  const leverageSelect = el("select", {});
  const marginModeSelect = el("select", {}, [
    el("option", { value: "ISOLATED" }, "ISOLATED"),
    el("option", { value: "CROSS" }, "CROSS"),
  ]);
  const orderTypeSelect = el("select", {}, [
    el("option", { value: "MARKET" }, "MARKET"),
    el("option", { value: "LIMIT" }, "LIMIT"),
    el("option", { value: "STOP_MARKET" }, "STOP_MARKET"),
    el("option", { value: "TAKE_PROFIT_MARKET" }, "TAKE_PROFIT_MARKET"),
  ]);
  const quantityInput = el("input", { type: "number", step: "any", placeholder: "Quantity", value: "0.01" });
  const priceInput = el("input", { type: "number", step: "any", placeholder: "Limit price" });
  const stopPriceInput = el("input", { type: "number", step: "any", placeholder: "Stop price" });
  const reduceOnlyInput = el("input", { type: "checkbox" });
  // Filled only by the "USE AI SIGNAL" button below, never automatically --
  // applied to the resulting position only if the user goes on to click
  // OPEN LONG/OPEN SHORT themselves (task: the AI forecast must never open
  // a demo position on its own).
  const aiSlInput = el("input", { type: "number", step: "any", placeholder: "AI-suggested SL" });
  const aiTpInput = el("input", { type: "number", step: "any", placeholder: "AI-suggested TP" });

  function refreshLeverageOptions() {
    const symbolRow = symbols.find((s) => s.symbol === symbolSelect.value);
    const options = symbolRow ? symbolRow.leverage_options : [1];
    leverageSelect.innerHTML = "";
    for (const lev of options) leverageSelect.appendChild(el("option", { value: String(lev) }, `${lev}x`));
  }
  symbolSelect.addEventListener("change", refreshLeverageOptions);
  refreshLeverageOptions();

  const priceField = el("div", { class: "order-field" }, [el("label", {}, "Limit Price"), priceInput]);
  const stopPriceField = el("div", { class: "order-field" }, [el("label", {}, "Stop Price"), stopPriceInput]);

  function refreshOrderTypeVisibility() {
    priceField.style.display = orderTypeSelect.value === "LIMIT" ? "" : "none";
    stopPriceField.style.display =
      orderTypeSelect.value === "STOP_MARKET" || orderTypeSelect.value === "TAKE_PROFIT_MARKET" ? "" : "none";
  }
  orderTypeSelect.addEventListener("change", refreshOrderTypeVisibility);
  refreshOrderTypeVisibility();

  const resultBox = el("p", { class: "sub" });
  const notionalNode = el("p", { class: "sub" });

  // Order-ticket header: symbol's live last price + 24h change, right next
  // to the symbol picker -- same RealtimeStore data updateNotional() below
  // already reads, just surfaced as a Binance-style pair header instead of
  // buried in the notional caption.
  const headerPriceNode = el("span", { class: "order-ticket-price" }, "—");
  const headerChangeNode = el("span", { class: "sub" }, "");
  function updateHeaderPrice() {
    const entry = RealtimeStore.get(symbolSelect.value);
    if (!entry || entry.price == null) {
      headerPriceNode.textContent = "—";
      headerChangeNode.textContent = "";
      headerChangeNode.className = "sub";
      return;
    }
    headerPriceNode.textContent = `$${fmtNum(entry.price)}`;
    headerChangeNode.textContent = fmtPct(entry.changePercent24h);
    headerChangeNode.className = changeClass(entry.changePercent24h);
  }

  // Task: show the order's USD value. Uses the live last price (RealtimeStore),
  // not the simulated mark price with slippage the engine actually fills at --
  // labeled with "~" and a caveat so it reads as an estimate, not a promise.
  function updateNotional() {
    const entry = RealtimeStore.get(symbolSelect.value);
    const qty = parseFloat(quantityInput.value);
    if (!entry || !Number.isFinite(qty)) {
      notionalNode.textContent = "Live price unavailable -- order value cannot be shown.";
      return;
    }
    const notional = qty * entry.price;
    const lev = parseInt(leverageSelect.value, 10) || 1;
    notionalNode.textContent =
      `~ $${fmtNum(notional)} notional · $${fmtNum(notional / lev)} initial margin @ ${lev}x · ` +
      `mark $${fmtNum(entry.price)} (estimate -- actual fill uses the simulated mark price with slippage)`;
  }
  quantityInput.addEventListener("input", updateNotional);
  leverageSelect.addEventListener("change", updateNotional);
  symbolSelect.addEventListener("change", () => {
    updateNotional();
    updateHeaderPrice();
  });
  const unsubscribeNotional = RealtimeStore.subscribe((dirtySymbols) => {
    if (!notionalNode.isConnected) {
      unsubscribeNotional();
      return;
    }
    if (dirtySymbols.has(symbolSelect.value)) {
      updateNotional();
      updateHeaderPrice();
    }
  });
  updateNotional();
  updateHeaderPrice();

  async function submitOrder(side) {
    resultBox.className = "sub";
    resultBox.textContent = "Placing order...";
    try {
      const body = {
        symbol: symbolSelect.value,
        side,
        order_type: orderTypeSelect.value,
        quantity: parseFloat(quantityInput.value),
        leverage: parseInt(leverageSelect.value, 10),
        margin_mode: marginModeSelect.value,
        reduce_only: reduceOnlyInput.checked,
        account_name: futuresAccountName(),
      };
      if (orderTypeSelect.value === "LIMIT") body.price = parseFloat(priceInput.value);
      if (orderTypeSelect.value === "STOP_MARKET" || orderTypeSelect.value === "TAKE_PROFIT_MARKET") {
        body.stop_price = parseFloat(stopPriceInput.value);
      }
      const result = await fetchJSONWithAdminKey("/api/simulator/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      resultBox.className = result.order.status === "REJECTED" ? "error" : "sub";
      resultBox.textContent =
        `Order ${result.order.status}` + (result.order.reject_reason ? `: ${result.order.reject_reason}` : "");

      // The user's own OPEN LONG/OPEN SHORT click is what confirms
      // whatever SL/TP the AI signal button (if used) pre-filled -- this
      // never fires on its own, only as a continuation of that same
      // explicit click, and only when the order actually opened a position.
      if (result.position && (aiSlInput.value !== "" || aiTpInput.value !== "")) {
        try {
          await fetchJSONWithAdminKey(`/api/simulator/positions/${result.position.position_id}/sl-tp`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              sl_price: aiSlInput.value !== "" ? parseFloat(aiSlInput.value) : null,
              tp_price: aiTpInput.value !== "" ? parseFloat(aiTpInput.value) : null,
              account_name: futuresAccountName(),
            }),
          });
          resultBox.textContent += " (AI-suggested SL/TP applied)";
        } catch (slTpErr) {
          resultBox.textContent += ` (position opened, but SL/TP failed: ${slTpErr.message})`;
        }
      }
    } catch (err) {
      resultBox.className = "error";
      resultBox.textContent = `Error: ${err.message}`;
    }
  }

  const openLongBtn = el("button", { class: "buy" }, "OPEN LONG");
  const openShortBtn = el("button", { class: "sell" }, "OPEN SHORT");
  openLongBtn.addEventListener("click", () => submitOrder("BUY"));
  openShortBtn.addEventListener("click", () => submitOrder("SELL"));

  // ---- Chart (left column) ---------------------------------------------
  const chartContainer = el("div", {});
  let chartTimeframe = localStorage.getItem(CHART_TIMEFRAME_STORAGE_KEY) || "1h";
  if (!CHART_TIMEFRAMES.includes(chartTimeframe)) chartTimeframe = "1h";
  let indicatorKind = localStorage.getItem(INDICATOR_KIND_STORAGE_KEY) || "rsi";
  if (!INDICATOR_KINDS.includes(indicatorKind)) indicatorKind = "rsi";

  async function loadChart() {
    chartContainer.innerHTML = "";
    chartContainer.appendChild(
      el("div", { class: "chart-controls-row" }, [
        chartTimeframeTabs(chartTimeframe, (tf) => {
          chartTimeframe = tf;
          localStorage.setItem(CHART_TIMEFRAME_STORAGE_KEY, tf);
          loadChart();
        }),
        indicatorKindTabs(indicatorKind, (kind) => {
          indicatorKind = kind;
          localStorage.setItem(INDICATOR_KIND_STORAGE_KEY, kind);
          loadChart();
        }),
      ])
    );

    const isRealtimeTimeframe = chartTimeframe === "5m" || chartTimeframe === "15m";
    const isNativeOhlcTimeframe = chartTimeframe === "30m" || chartTimeframe === "4d";
    const loadingMsg = el("p", { class: "loading" }, "Loading chart...");
    chartContainer.appendChild(loadingMsg);
    const data = await safe(
      `/api/history/${encodeURIComponent(symbolSelect.value)}?timeframe=${chartTimeframe}&limit=180`
    );
    chartContainer.removeChild(loadingMsg);
    if (!data || !data.candles || !data.candles.length) {
      chartContainer.appendChild(
        el(
          "p",
          { class: "sub" },
          isRealtimeTimeframe
            ? `Real ${chartTimeframe} candles are being recorded from the live price feed starting ` +
              "now -- check back soon as history accumulates."
            : "No chart data available for this symbol/timeframe yet."
        )
      );
      return;
    }
    if (isRealtimeTimeframe) {
      chartContainer.appendChild(
        el(
          "p",
          { class: "sub" },
          `Built from the live Coinbase feed, sampled about once a minute since ` +
            `${new Date(data.candles[0].timestamp).toLocaleString()} -- real prices, not a full ` +
            "trade tape. No volume data available."
        )
      );
    }
    if (isNativeOhlcTimeframe) {
      chartContainer.appendChild(
        el(
          "p",
          { class: "sub" },
          "Real OHLC candles from CoinGecko, refreshed roughly hourly. No volume data available for this timeframe."
        )
      );
    }
    chartContainer.appendChild(candleChart(data.candles, { timeframe: chartTimeframe, indicatorKind }));
  }
  symbolSelect.addEventListener("change", loadChart);

  // ---- Order panel (right column) ---------------------------------------
  const rightCol = el("div", {});
  const ticket = el("div", { class: "order-ticket" });

  ticket.appendChild(
    el("div", { class: "order-ticket-header" }, [
      el("div", { class: "order-field", style: "margin-bottom:0; min-width:130px;" }, [
        el("label", {}, "Symbol"),
        symbolSelect,
      ]),
      el("div", { class: "order-ticket-price-block" }, [headerPriceNode, headerChangeNode]),
    ])
  );
  ticket.appendChild(
    el("div", { class: "order-field-row" }, [
      el("div", { class: "order-field" }, [el("label", {}, "Leverage"), leverageSelect]),
      el("div", { class: "order-field" }, [el("label", {}, "Margin Mode"), marginModeSelect]),
    ])
  );
  ticket.appendChild(el("div", { class: "order-field" }, [el("label", {}, "Order Type"), orderTypeSelect]));
  ticket.appendChild(el("div", { class: "order-field" }, [el("label", {}, "Quantity"), quantityInput]));
  ticket.appendChild(priceField);
  ticket.appendChild(stopPriceField);
  ticket.appendChild(
    el("label", { class: "order-checkbox-row" }, [reduceOnlyInput, "Reduce Only"])
  );
  ticket.appendChild(notionalNode);
  ticket.appendChild(el("div", { class: "order-side-buttons" }, [openLongBtn, openShortBtn]));
  ticket.appendChild(resultBox);
  rightCol.appendChild(ticket);
  rightCol.appendChild(
    el(
      "p",
      { class: "sub" },
      "reduceOnly caps a close at the existing position's size rather than flipping into the opposite side."
    )
  );

  // ---- AI Forecast panel (task: show existing GPTAgent2 forecast, never
  // auto-trade -- USE AI SIGNAL only pre-fills fields, the user must still
  // click OPEN LONG/OPEN SHORT themselves) ------------------------------
  const aiPanel = el("div", { class: "card" });
  rightCol.appendChild(el("h3", {}, "AI Forecast"));
  rightCol.appendChild(aiPanel);

  async function loadAiForecast() {
    aiPanel.innerHTML = "";
    aiPanel.appendChild(el("p", { class: "loading" }, "Loading forecast..."));
    aiSlInput.value = "";
    aiTpInput.value = "";
    let forecast;
    try {
      forecast = await fetchJSON(`/api/forecast/${encodeURIComponent(symbolSelect.value)}?horizon=24h`);
    } catch {
      aiPanel.innerHTML = "";
      aiPanel.appendChild(el("p", { class: "sub" }, "No AI forecast available for this symbol yet."));
      return;
    }
    aiPanel.innerHTML = "";
    aiPanel.appendChild(
      el("div", { class: "grid" }, [
        card("Current Forecast", forecast.direction, null, changeClass(forecast.expected_change_pct)),
        card("Probability", forecast.probability_pct != null ? `${forecast.probability_pct}%` : "n/a"),
        card(
          "Confidence",
          forecast.confidence ? `${forecast.confidence.tier} (${forecast.confidence.effective_confidence_pct}%)` : "n/a"
        ),
        card("Regime", forecast.regime || "n/a"),
        card(
          "Expected Move",
          forecast.expected_change_pct != null ? fmtPct(forecast.expected_change_pct) : "n/a",
          null,
          changeClass(forecast.expected_change_pct)
        ),
        card(
          "Historical Edge",
          forecast.track_record && forecast.track_record.win_rate_pct != null
            ? `${forecast.track_record.win_rate_pct}% (n=${forecast.track_record.win_rate_sample_size})`
            : "n/a"
        ),
      ])
    );

    const bullish = forecast.direction === "Bullish" || forecast.direction === "Strong Bullish";
    const bearish = forecast.direction === "Bearish" || forecast.direction === "Strong Bearish";
    const useSignalBtn = el(
      "button",
      bullish || bearish ? {} : { disabled: "disabled" },
      "USE AI SIGNAL (prefill SL/TP)"
    );
    useSignalBtn.addEventListener("click", () => {
      const levels = forecast.key_levels || {};
      if (bullish) {
        aiSlInput.value = levels.support_1 ?? "";
        aiTpInput.value = forecast.target_price ?? levels.resistance_1 ?? "";
      } else if (bearish) {
        aiSlInput.value = levels.resistance_1 ?? "";
        aiTpInput.value = forecast.target_price ?? levels.support_1 ?? "";
      }
      resultBox.className = "sub";
      resultBox.textContent =
        `AI signal applied: suggested SL ${aiSlInput.value || "n/a"}, TP ${aiTpInput.value || "n/a"} -- ` +
        `click OPEN ${bullish ? "LONG" : "SHORT"} to confirm (not submitted automatically).`;
    });
    aiPanel.appendChild(
      el("div", { class: "controls" }, [useSignalBtn, aiSlInput, aiTpInput])
    );
    aiPanel.appendChild(
      el(
        "p",
        { class: "sub" },
        "The AI forecast never opens a position by itself -- this only pre-fills the SL/TP fields above; you still choose and click OPEN LONG or OPEN SHORT yourself."
      )
    );
  }
  symbolSelect.addEventListener("change", loadAiForecast);

  wrap.appendChild(el("div", { class: "trade-layout" }, [chartContainer, rightCol]));

  await Promise.all([loadChart(), loadAiForecast()]);

  return wrap;
}

async function renderFuturesPositionsTab() {
  const data = await safe(`/api/simulator/positions?name=${encodeURIComponent(futuresAccountName())}&status=OPEN`);
  const positions = data ? data.positions : [];
  const wrap = el("div", {});
  if (!positions.length) {
    wrap.appendChild(el("p", { class: "sub" }, "No open positions."));
    return wrap;
  }

  const rows = positions.map((p) => {
    const closeBtns = [25, 50, 75, 100].map((pct) => {
      const btn = el("button", {}, `${pct}%`);
      btn.addEventListener("click", async () => {
        if (!confirm(`Close ${pct}% of this ${p.symbol} ${p.side} position?`)) return;
        try {
          await fetchJSONWithAdminKey(`/api/simulator/positions/${p.position_id}/close`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ percent: pct, account_name: futuresAccountName() }),
          });
          navigate("futures", new URLSearchParams({ tab: "positions" }));
        } catch (err) {
          alert(`Error closing position: ${err.message}`);
        }
      });
      return btn;
    });

    const slInput = el("input", { type: "number", step: "any", placeholder: "SL", value: p.sl_price ?? "" });
    const tpInput = el("input", { type: "number", step: "any", placeholder: "TP", value: p.tp_price ?? "" });
    const setSlTpBtn = el("button", {}, "Set");
    setSlTpBtn.addEventListener("click", async () => {
      try {
        await fetchJSONWithAdminKey(`/api/simulator/positions/${p.position_id}/sl-tp`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sl_price: slInput.value !== "" ? parseFloat(slInput.value) : null,
            tp_price: tpInput.value !== "" ? parseFloat(tpInput.value) : null,
            account_name: futuresAccountName(),
          }),
        });
        navigate("futures", new URLSearchParams({ tab: "positions" }));
      } catch (err) {
        alert(`Error setting SL/TP: ${err.message}`);
      }
    });

    return [
      p.symbol,
      decisionPill(p.side, p.side === "LONG" ? "good" : "bad"),
      String(p.quantity),
      fmtNum(p.entry_price),
      fmtNum(p.mark_price),
      p.liquidation_price != null ? fmtNum(p.liquidation_price) : "n/a",
      `${p.leverage}x`,
      fmtNum(p.initial_margin),
      el("span", { class: changeClass(p.unrealized_pnl) }, fmtNum(p.unrealized_pnl)),
      p.roi_pct != null ? el("span", { class: changeClass(p.roi_pct) }, fmtPct(p.roi_pct)) : "n/a",
      el("div", { class: "controls" }, [slInput, tpInput, setSlTpBtn]),
      el("div", { class: "controls" }, closeBtns),
    ];
  });

  wrap.appendChild(
    table(
      ["Symbol", "Side", "Size", "Entry", "Mark", "Liq Price", "Leverage", "Margin", "PnL", "ROI", "SL / TP", "Close"],
      rows
    )
  );
  return wrap;
}

async function renderFuturesOpenOrdersTab() {
  const data = await safe(`/api/simulator/orders?name=${encodeURIComponent(futuresAccountName())}&limit=200`);
  const orders = (data ? data.orders : []).filter((o) => o.status === "NEW");
  const wrap = el("div", {});
  if (!orders.length) {
    wrap.appendChild(el("p", { class: "sub" }, "No open orders."));
    return wrap;
  }

  const rows = orders.map((o) => {
    const cancelBtn = el("button", {}, "Cancel");
    cancelBtn.addEventListener("click", async () => {
      if (!confirm(`Cancel this resting ${o.order_type} order?`)) return;
      try {
        await fetchJSONWithAdminKey(
          `/api/simulator/orders/${o.order_id}?account_name=${encodeURIComponent(futuresAccountName())}`,
          { method: "DELETE" }
        );
        navigate("futures", new URLSearchParams({ tab: "orders" }));
      } catch (err) {
        alert(`Error cancelling order: ${err.message}`);
      }
    });
    const triggerPrice = o.price != null ? fmtNum(o.price) : o.stop_price != null ? fmtNum(o.stop_price) : "market";
    return [
      o.symbol,
      decisionPill(o.side, o.side === "BUY" ? "good" : "bad"),
      o.order_type,
      String(o.quantity),
      triggerPrice,
      `${o.leverage}x`,
      o.reduce_only ? "yes" : "no",
      new Date(o.created_at).toLocaleString(),
      cancelBtn,
    ];
  });

  wrap.appendChild(
    table(["Symbol", "Side", "Type", "Qty", "Trigger Price", "Leverage", "Reduce Only", "Created", "Cancel"], rows)
  );
  return wrap;
}

function orderStatusTone(status) {
  if (status === "FILLED") return "good";
  if (status === "REJECTED") return "bad";
  return "neutral"; // NEW / CANCELLED
}

async function renderFuturesOrderHistoryTab() {
  const data = await safe(`/api/simulator/orders?name=${encodeURIComponent(futuresAccountName())}&limit=100`);
  const orders = data ? data.orders : [];
  const wrap = el("div", {});
  if (!orders.length) {
    wrap.appendChild(el("p", { class: "sub" }, "No orders yet."));
    return wrap;
  }
  wrap.appendChild(
    table(
      ["Symbol", "Side", "Type", "Qty", "Filled", "Fill Price", "Fee", "Status", "Created"],
      orders.map((o) => [
        o.symbol,
        decisionPill(o.side, o.side === "BUY" ? "good" : "bad"),
        o.order_type,
        String(o.quantity),
        String(o.filled_quantity),
        o.actual_fill_price != null ? fmtNum(o.actual_fill_price) : "n/a",
        o.fee_amount != null ? fmtNum(o.fee_amount, 4) : "n/a",
        el("span", {}, [
          decisionPill(o.status, orderStatusTone(o.status)),
          o.reject_reason ? ` ${o.reject_reason}` : "",
        ]),
        new Date(o.created_at).toLocaleString(),
      ])
    )
  );
  return wrap;
}

function futuresJournalSummary(trade) {
  const parts = [];
  if (trade.strategy_label) parts.push(trade.strategy_label);
  if (trade.self_assessment_tags && trade.self_assessment_tags.length) {
    parts.push(trade.self_assessment_tags.join(", "));
  }
  if (trade.note) parts.push(`"${trade.note}"`);
  return parts.length ? parts.join(" — ") : "—";
}

async function renderFuturesTradeHistoryTab() {
  const [tradesData, optionsData] = await Promise.all([
    safe(`/api/simulator/trades?name=${encodeURIComponent(futuresAccountName())}&limit=100`),
    safe("/api/simulator/journal-options"),
  ]);
  const trades = tradesData ? tradesData.trades : [];
  const strategyLabels = optionsData ? optionsData.strategy_labels : [];
  const selfAssessmentTags = optionsData ? optionsData.self_assessment_tags : [];
  const wrap = el("div", {});
  if (!trades.length) {
    wrap.appendChild(el("p", { class: "sub" }, "No closed trades yet."));
    return wrap;
  }

  // Task: optional Strategy Journal / Trade Review -- purely a note-taking
  // layer over already-closed trades, never touches PnL/fees/anything
  // financial. One shared edit panel below the table, populated for
  // whichever trade's Edit button was last clicked.
  const editPanel = el("div", { class: "controls", style: "display:none" });

  function closeEditPanel() {
    editPanel.style.display = "none";
    editPanel.innerHTML = "";
  }

  function openEditPanel(trade) {
    editPanel.innerHTML = "";
    editPanel.style.display = "";

    const labelSelect = el(
      "select",
      {},
      [el("option", { value: "" }, "-- no label --")].concat(
        strategyLabels.map((l) => el("option", { value: l }, l))
      )
    );
    labelSelect.value = trade.strategy_label || "";
    const noteInput = el("textarea", { placeholder: "Why did you enter/exit?", rows: "2" });
    noteInput.value = trade.note || "";

    const tagCheckboxes = selfAssessmentTags.map((tag) => {
      const cb = el("input", { type: "checkbox", value: tag });
      cb.checked = (trade.self_assessment_tags || []).includes(tag);
      return el("label", { class: "sub" }, [cb, ` ${tag} `]);
    });

    const statusMsg = el("p", { class: "sub" });
    const saveBtn = el("button", {}, "Save Journal");
    const cancelBtn = el("button", {}, "Cancel");
    cancelBtn.addEventListener("click", closeEditPanel);
    saveBtn.addEventListener("click", async () => {
      statusMsg.className = "sub";
      statusMsg.textContent = "Saving...";
      try {
        const checkedTags = tagCheckboxes
          .map((label) => label.querySelector("input"))
          .filter((cb) => cb.checked)
          .map((cb) => cb.value);
        const result = await fetchJSONWithAdminKey(`/api/simulator/trades/${trade.trade_id}/journal`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            strategy_label: labelSelect.value === "" ? null : labelSelect.value,
            note: noteInput.value,
            self_assessment_tags: checkedTags,
            account_name: futuresAccountName(),
          }),
        });
        trade.strategy_label = result.trade.strategy_label;
        trade.note = result.trade.note;
        trade.self_assessment_tags = result.trade.self_assessment_tags;
        navigate("futures", new URLSearchParams({ tab: "trade-history" }));
      } catch (err) {
        statusMsg.className = "error";
        statusMsg.textContent = `Error: ${err.message}`;
      }
    });

    editPanel.appendChild(el("h4", {}, `Journal -- ${trade.symbol} trade #${trade.trade_id}`));
    editPanel.appendChild(el("div", {}, [el("label", { class: "sub" }, "Strategy: "), labelSelect]));
    editPanel.appendChild(el("div", {}, tagCheckboxes));
    editPanel.appendChild(noteInput);
    editPanel.appendChild(el("div", { class: "controls" }, [saveBtn, cancelBtn]));
    editPanel.appendChild(statusMsg);
  }

  wrap.appendChild(
    table(
      ["Symbol", "Side", "Qty", "Entry", "Exit", "Net PnL", "ROI", "Fees", "Exit Reason", "Closed", "Journal", ""],
      trades.map((t) => {
        const editBtn = el("button", {}, "Edit");
        editBtn.addEventListener("click", () => openEditPanel(t));
        return [
          t.symbol,
          decisionPill(t.side, t.side === "LONG" ? "good" : "bad"),
          String(t.quantity),
          fmtNum(t.entry_price),
          fmtNum(t.exit_price),
          el("span", { class: changeClass(t.net_pnl) }, fmtNum(t.net_pnl)),
          el("span", { class: changeClass(t.roi_pct) }, fmtPct(t.roi_pct)),
          fmtNum(t.fees, 4),
          t.exit_reason,
          new Date(t.closed_at).toLocaleString(),
          futuresJournalSummary(t),
          editBtn,
        ];
      })
    )
  );
  wrap.appendChild(editPanel);
  return wrap;
}

function futuresPerformanceStatsGrid(stats) {
  return el("div", { class: "grid" }, [
    card("Total Trades", stats.total_trades),
    card("Win Rate", stats.win_rate_pct != null ? `${stats.win_rate_pct}%` : "n/a"),
    card("Profit Factor", stats.profit_factor ?? "n/a"),
    card(
      "Expectancy",
      stats.expectancy_pct != null ? fmtPct(stats.expectancy_pct) : "n/a",
      null,
      changeClass(stats.expectancy_pct)
    ),
    card("Total PnL", fmtNum(stats.total_pnl), null, changeClass(stats.total_pnl)),
    card("Total Fees", fmtNum(stats.total_fees)),
    card("Max Drawdown", stats.max_drawdown_pct != null ? `${stats.max_drawdown_pct}%` : "n/a", null, "down"),
    card("Sharpe", stats.sharpe_ratio ?? "n/a"),
    card("Sortino", stats.sortino_ratio ?? "n/a"),
    card("Liquidations", stats.liquidations),
  ]);
}

function futuresBreakdownTable(title, breakdown) {
  const keys = Object.keys(breakdown || {});
  if (!keys.length) return null;
  const section = el("div", {}, [el("h3", {}, title)]);
  section.appendChild(
    table(
      ["Group", "Trades", "Win Rate", "Total PnL", "Profit Factor"],
      keys.map((k) => [
        k,
        String(breakdown[k].total_trades),
        breakdown[k].win_rate_pct != null ? `${breakdown[k].win_rate_pct}%` : "n/a",
        el("span", { class: changeClass(breakdown[k].total_pnl) }, fmtNum(breakdown[k].total_pnl)),
        breakdown[k].profit_factor ?? "n/a",
      ])
    )
  );
  return section;
}

async function renderFuturesPerformanceTab() {
  const stats = await safe(`/api/simulator/performance?name=${encodeURIComponent(futuresAccountName())}`);
  const wrap = el("div", {});
  if (!stats) {
    wrap.appendChild(el("p", { class: "error" }, "Performance data unavailable."));
    return wrap;
  }
  wrap.appendChild(el("h3", {}, "Overall"));
  wrap.appendChild(futuresPerformanceStatsGrid(stats.overall));

  for (const [title, key] of [
    ["By Side", "by_side"],
    ["By Symbol", "by_symbol"],
    ["By Leverage", "by_leverage"],
    ["By Strategy", "by_strategy"],
  ]) {
    const section = futuresBreakdownTable(title, stats[key]);
    if (section) wrap.appendChild(section);
  }
  return wrap;
}

function futuresWarningTone(level) {
  if (level === "MARGIN_WARNING") return "warning";
  return "bad"; // HIGH_RISK / NEAR_LIQUIDATION
}

const RISK_SETTINGS_FIELDS = [
  ["high_margin_ratio_pct", "High Margin Ratio Warning (%)"],
  ["near_liquidation_pct", "Near-Liquidation Warning (%)"],
  ["margin_warning_available_pct", "Low Available Margin Warning (%)"],
  ["daily_loss_warning_pct", "Daily Loss Warning (%)"],
];

// Task: optional, per-account Max Risk Settings -- overrides for the four
// Risk Metrics warning thresholds. Never blocks trading, only changes
// when a warning fires (same permissive-by-default philosophy as the
// rest of the RISK tab).
function futuresMaxRiskSettingsSection(riskSettings) {
  const section = el("div", { class: "card", style: "margin-top:16px" }, [
    el("h3", { style: "margin-top:0" }, "Max Risk Settings"),
  ]);
  section.appendChild(
    el(
      "p",
      { class: "sub" },
      "Optional per-account overrides for the warning thresholds above. Leave a field blank to use the global default. These never block trading."
    )
  );

  const inputs = {};
  const rows = RISK_SETTINGS_FIELDS.map(([key, label]) => {
    const input = el("input", {
      type: "number",
      step: "any",
      placeholder: `default: ${riskSettings.defaults[key]}`,
    });
    if (riskSettings.overrides[key] != null) input.value = riskSettings.overrides[key];
    inputs[key] = input;
    return el("div", { class: "controls" }, [el("label", { class: "sub" }, `${label}: `), input]);
  });
  for (const row of rows) section.appendChild(row);

  const statusMsg = el("p", { class: "sub" });
  const saveBtn = el("button", {}, "Save Max Risk Settings");
  const resetBtn = el("button", {}, "Reset to Defaults");

  async function submit(body) {
    statusMsg.className = "sub";
    statusMsg.textContent = "Saving...";
    try {
      await fetchJSONWithAdminKey("/api/simulator/risk-settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, account_name: futuresAccountName() }),
      });
      navigate("futures", new URLSearchParams({ tab: "risk" }));
    } catch (err) {
      statusMsg.className = "error";
      statusMsg.textContent = `Error: ${err.message}`;
    }
  }

  saveBtn.addEventListener("click", () => {
    const body = {};
    for (const [key] of RISK_SETTINGS_FIELDS) {
      body[key] = inputs[key].value === "" ? null : parseFloat(inputs[key].value);
    }
    submit(body);
  });
  resetBtn.addEventListener("click", () => {
    const body = {};
    for (const [key] of RISK_SETTINGS_FIELDS) body[key] = null;
    submit(body);
  });

  section.appendChild(el("div", { class: "controls" }, [saveBtn, resetBtn]));
  section.appendChild(statusMsg);
  return section;
}

async function renderFuturesRiskTab() {
  const [risk, riskSettings] = await Promise.all([
    safe(`/api/simulator/risk?name=${encodeURIComponent(futuresAccountName())}`),
    safe(`/api/simulator/risk-settings?name=${encodeURIComponent(futuresAccountName())}`),
  ]);
  const wrap = el("div", {});
  if (!risk) {
    wrap.appendChild(el("p", { class: "error" }, "Risk data unavailable."));
    return wrap;
  }

  wrap.appendChild(
    el("div", { class: "grid" }, [
      card("Margin Ratio", risk.margin_ratio_pct != null ? `${risk.margin_ratio_pct}%` : "n/a"),
      card("Available Margin", risk.available_margin_pct != null ? `${risk.available_margin_pct}%` : "n/a"),
      card("Max Drawdown", risk.max_drawdown_pct != null ? `${risk.max_drawdown_pct}%` : "n/a", null, "down"),
      card("Daily PnL", fmtNum(risk.daily_pnl), null, changeClass(risk.daily_pnl)),
      card("Daily Loss", risk.daily_loss_pct != null ? `${risk.daily_loss_pct}%` : "n/a"),
      card("Total Exposure", fmtNum(risk.total_exposure)),
      card("Open Positions", risk.open_position_count),
      card("Largest Position", risk.largest_position ? risk.largest_position.symbol : "n/a"),
    ])
  );

  wrap.appendChild(el("h3", {}, "Warnings"));
  if (!risk.warnings.length) {
    wrap.appendChild(el("p", { class: "sub" }, "No active warnings. These never block trading -- they're informational only."));
  } else {
    const list = el("div", { class: "controls" });
    for (const w of risk.warnings) {
      list.appendChild(
        el("p", {}, [decisionPill(w.level, futuresWarningTone(w.level)), " ", w.message])
      );
    }
    wrap.appendChild(list);
  }

  wrap.appendChild(el("h3", {}, "Open Position Risk"));
  if (!risk.positions.length) {
    wrap.appendChild(el("p", { class: "sub" }, "No open positions."));
  } else {
    wrap.appendChild(
      table(
        ["Symbol", "Side", "Notional", "Concentration", "Distance to Liquidation"],
        risk.positions.map((p) => [
          p.symbol,
          decisionPill(p.side, p.side === "LONG" ? "good" : "bad"),
          fmtNum(p.notional),
          p.concentration_pct != null ? `${p.concentration_pct}%` : "n/a",
          p.distance_to_liquidation_pct != null ? `${p.distance_to_liquidation_pct}%` : "n/a",
        ])
      )
    );
  }

  if (riskSettings) wrap.appendChild(futuresMaxRiskSettingsSection(riskSettings));
  return wrap;
}

async function renderFuturesAccountHistoryTab() {
  const data = await safe(`/api/simulator/ledger?name=${encodeURIComponent(futuresAccountName())}&limit=200`);
  const entries = data ? data.ledger : [];
  const wrap = el("div", {});
  if (!entries.length) {
    wrap.appendChild(el("p", { class: "sub" }, "No ledger entries yet."));
    return wrap;
  }
  wrap.appendChild(
    table(
      ["Event", "Amount", "Balance After", "Description", "Time"],
      entries.map((e) => [
        el("span", { class: "pill neutral" }, e.event_type),
        el("span", { class: changeClass(e.amount) }, fmtNum(e.amount, 4)),
        fmtNum(e.balance_after),
        e.description,
        new Date(e.created_at).toLocaleString(),
      ])
    )
  );
  return wrap;
}

async function renderFuturesSettingsTab() {
  const wrap = el("div", {});

  const accountCard = el("div", { class: "card" }, [
    el("h3", { style: "margin-top:0" }, "Demo Account"),
    el(
      "p",
      { class: "sub" },
      "Switching the account name starts (or resumes) a separate demo account -- useful for comparing strategies side by side."
    ),
  ]);
  const nameInput = el("input", { type: "text", value: futuresAccountName(), placeholder: "Account name" });
  const switchBtn = el("button", {}, "Switch Account");
  switchBtn.addEventListener("click", () => {
    localStorage.setItem(FUTURES_ACCOUNT_NAME_KEY, nameInput.value.trim() || "default");
    navigate("futures", new URLSearchParams({ tab: "settings" }));
  });
  accountCard.appendChild(el("div", { class: "controls" }, [nameInput, switchBtn]));
  wrap.appendChild(accountCard);

  const resetCard = el("div", { class: "card", style: "margin-top:16px" }, [
    el("h3", { style: "margin-top:0" }, "Reset Demo Account"),
    el(
      "p",
      { class: "sub" },
      "Resets this account's balance back to the initial demo balance. The old session's full history (orders/trades/ledger) stays queryable forever -- nothing is deleted, only a fresh session starts."
    ),
  ]);
  const resetStatus = el("p", { class: "sub" });
  const resetBtn = el("button", { class: "sell" }, "Reset Demo Account");
  resetBtn.addEventListener("click", async () => {
    if (!confirm("Reset this demo account? Balance returns to the initial demo balance.")) return;
    try {
      await fetchJSONWithAdminKey(
        `/api/simulator/account/reset?name=${encodeURIComponent(futuresAccountName())}`,
        { method: "POST" }
      );
      navigate("futures", new URLSearchParams({ tab: "settings" }));
    } catch (err) {
      resetStatus.className = "error";
      resetStatus.textContent = `Error: ${err.message}`;
    }
  });
  resetCard.appendChild(el("div", { class: "controls" }, [resetBtn]));
  resetCard.appendChild(resetStatus);
  wrap.appendChild(resetCard);

  return wrap;
}

const FUTURES_TAB_RENDERERS = {
  trade: renderFuturesTradeTab,
  positions: renderFuturesPositionsTab,
  orders: renderFuturesOpenOrdersTab,
  "order-history": renderFuturesOrderHistoryTab,
  "trade-history": renderFuturesTradeHistoryTab,
  performance: renderFuturesPerformanceTab,
  risk: renderFuturesRiskTab,
  "account-history": renderFuturesAccountHistoryTab,
  settings: renderFuturesSettingsTab,
};

function futuresStat(label, value, cls) {
  return el("div", { class: "futures-stat" }, [
    el("div", { class: "label" }, label),
    el("div", { class: `value ${cls || ""}` }, String(value)),
  ]);
}

async function renderFuturesSimulator(params) {
  const root = el("div", { class: "futures-sim" });
  root.appendChild(
    el("div", { class: "futures-header" }, [
      el("h2", {}, "FUTURES SIMULATOR"),
      el("span", { class: "pill warning" }, "PAPER TRADING / DEMO — REAL FUNDS NOT USED"),
    ])
  );

  const accountState = await safe(`/api/simulator/account?name=${encodeURIComponent(futuresAccountName())}`);
  if (accountState) {
    root.appendChild(
      el("div", { class: "futures-stat-strip" }, [
        futuresStat("Demo Balance", fmtNum(accountState.wallet_balance)),
        futuresStat("Equity", fmtNum(accountState.equity)),
        futuresStat("Available", fmtNum(accountState.available_margin)),
        futuresStat("Unrealized PnL", fmtNum(accountState.unrealized_pnl), changeClass(accountState.unrealized_pnl)),
        futuresStat(
          "Realized PnL",
          fmtNum(accountState.realized_pnl_total),
          changeClass(accountState.realized_pnl_total)
        ),
        futuresStat("Margin Ratio", accountState.margin_ratio != null ? `${accountState.margin_ratio}%` : "n/a"),
      ])
    );
  } else {
    root.appendChild(el("p", { class: "error" }, "Futures Simulator account unavailable."));
  }

  const requestedTab = params.get("tab");
  const currentTab = FUTURES_TABS.includes(requestedTab) ? requestedTab : "trade";

  const tabsRow = el("div", { class: "forecast-tabs futures-tabs-row" });
  for (const tab of FUTURES_TABS) {
    const btn = el("button", { class: `forecast-tab${tab === currentTab ? " active" : ""}` }, FUTURES_TAB_LABELS[tab]);
    btn.addEventListener("click", () => navigate("futures", new URLSearchParams({ tab })));
    tabsRow.appendChild(btn);
  }
  root.appendChild(tabsRow);

  const body = await FUTURES_TAB_RENDERERS[currentTab]();
  root.appendChild(body);
  return root;
}

const PAGES = {
  overview: renderOverview, forecast2: renderForecast2, forecast2detail: renderForecastDetail, forecast2performance: renderForecastPerformance, forecast2agents: renderForecastAgents, forecast2errors: renderForecastErrorLab, forecast2learning: renderForecastLearningCenter, assetdetail: renderAssetDetail, watchlist: renderWatchlist, consensus: renderConsensus, committee: renderCommittee, terminal: renderTerminal, macro: renderMacro, crypto: renderCrypto,
  stocks: renderStocks,
  correlations: renderCorrelations, news: renderNews, history: renderHistory, events: renderEvents,
  patterns: renderPatterns, breakout: renderBreakout, features: renderFeatures, liquidity: renderLiquidity, sentiment: renderSentiment,
  calendar: renderCalendar, similarity: renderSimilarity, brain: renderBrain,
  research: renderResearch, strategies: renderStrategies, backtest: renderBacktest,
  probability: renderProbability, learning: renderLearning, quality: renderQuality, accuracy: renderAccuracy,
  scenarios: renderScenarios,
  whatif: renderWhatif,
  whales: renderWhales, etf: renderEtf, onchain: renderOnchain,
  signals: renderSignals, reports: renderReports, portfolio: renderPortfolio, advice: renderAdvice,
  alerts: renderAlerts,
  risk: renderRisk, why: renderExplanation, watchdog: renderWatchdog, status: renderStatus,
  replay: renderReplay, shocks: renderShocks, technical: renderTechnical, scanner: renderScanner,
  memory: renderMemory,
  futures: renderFuturesSimulator,
  settings: renderSettings,
};

// Pages made of nothing but read-only scores/summaries (no forms, no
// in-progress user input) are safe to silently re-render on a timer.
// Anything with inputs is excluded so a background refresh never wipes out
// what the user is typing.
const AUTO_REFRESH_PAGES = new Set([
  "overview",
  "consensus",
  "signals",
  "sentiment",
  "liquidity",
  "scenarios",
]);
const AUTO_REFRESH_MS = 60000;

const lastUpdatedEl = document.getElementById("last-updated");
let refreshTimer = null;

// Header connection indicator persists across page navigation -- one
// subscription for the life of the tab, independent of liveTicker()'s
// per-page mount (which only exists while Overview is the visible page).
RealtimeStore.subscribeStatus(updateConnectionIndicator);

// Task: a live scrolling ticker marquee across the top of every page.
// Lives in #topbar (outside #content, which render() replaces on every
// navigation) so it survives page changes without restarting its CSS
// scroll animation. Uses RealtimeStore.subscribe() directly, not .mount()
// -- .mount() tears down whichever component mounted previously, and
// liveTicker() on Overview already calls .mount(); using it here too would
// silently break one or the other depending on render order.
async function mountTickerMarquee() {
  const marqueeEl = document.getElementById("ticker-marquee");
  if (!marqueeEl) return;
  const status = await safe("/api/realtime/status");
  const symbols = status && status.watchlist ? status.watchlist : [];
  if (!symbols.length) return;

  function marqueeItemNodes() {
    return symbols.map((symbol) => {
      const entry = RealtimeStore.get(symbol);
      const item = el("span", { class: "marquee-item", "data-symbol": symbol }, [
        el("span", { class: "marquee-symbol" }, symbol),
        el("span", { class: "marquee-price" }, entry && entry.price != null ? fmtNum(entry.price) : "n/a"),
        el(
          "span",
          { class: `marquee-change ${entry ? changeClass(entry.changePercent24h) : ""}` },
          entry ? fmtPct(entry.changePercent24h) : ""
        ),
      ]);
      item.addEventListener("click", () => navigate("assetdetail", new URLSearchParams({ symbol })));
      return item;
    });
  }

  function render() {
    marqueeEl.innerHTML = "";
    const track = el("div", { class: "marquee-track" });
    // Rendered twice back-to-back -- the CSS -50% seamless-loop trick needs
    // two copies of the content in the same track.
    for (const node of [...marqueeItemNodes(), ...marqueeItemNodes()]) track.appendChild(node);
    marqueeEl.appendChild(track);
  }
  render();

  RealtimeStore.subscribe((dirtySymbols) => {
    for (const symbol of dirtySymbols) {
      if (!symbols.includes(symbol)) continue;
      const entry = RealtimeStore.get(symbol);
      if (!entry) continue;
      // Both copies of the item share the same data-symbol -- update all
      // matches, not just the first (querySelector would only hit one).
      marqueeEl.querySelectorAll(`[data-symbol="${symbol}"]`).forEach((item) => {
        item.querySelector(".marquee-price").textContent = entry.price != null ? fmtNum(entry.price) : "n/a";
        const changeEl = item.querySelector(".marquee-change");
        changeEl.className = `marquee-change ${changeClass(entry.changePercent24h)}`;
        changeEl.textContent = fmtPct(entry.changePercent24h);
      });
    }
  });
}
mountTickerMarquee();

// Always started (cheap no-op poll when disabled/not permitted) so
// enabling notifications from Settings takes effect immediately without
// a page reload -- same reasoning as RealtimeStore always connecting above.
NotificationWatcher.start();

function parseHash() {
  const raw = location.hash.replace(/^#/, "");
  const [page, query] = raw.split("?");
  return {
    page: PAGES[page] ? page : "overview",
    params: new URLSearchParams(query || ""),
  };
}

async function activate(page, params) {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
  document.querySelectorAll("nav button[data-page]").forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  const activeBtn = document.querySelector(`nav button[data-page="${page}"]`);
  const activeGroup = activeBtn ? activeBtn.closest(".nav-group") : null;
  if (activeGroup) activeGroup.open = true;
  document.getElementById("nav").classList.remove("open");

  const run = async () => {
    await render(() => PAGES[page](params));
    lastUpdatedEl.textContent = `Updated ${new Date().toLocaleTimeString()}`;
  };
  await run();

  if (AUTO_REFRESH_PAGES.has(page)) {
    refreshTimer = setInterval(run, AUTO_REFRESH_MS);
  }
}

function navigate(page, params = new URLSearchParams()) {
  const qs = [...params].length ? `?${params.toString()}` : "";
  const target = `${page}${qs}`;
  if (location.hash.replace(/^#/, "") === target) {
    activate(page, params); // same page: treat as a manual refresh
  } else {
    location.hash = target;
  }
}

window.addEventListener("hashchange", () => {
  const { page, params } = parseHash();
  activate(page, params);
});

document.querySelectorAll("nav button[data-page]").forEach((btn) => {
  btn.addEventListener("click", () => navigate(btn.dataset.page));
});

document.getElementById("nav-toggle").addEventListener("click", () => {
  document.getElementById("nav").classList.toggle("open");
});

const symbolSearch = document.getElementById("symbol-search");
symbolSearch.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !symbolSearch.value.trim()) return;
  navigate("assetdetail", new URLSearchParams({ symbol: symbolSearch.value.trim().toUpperCase() }));
  symbolSearch.value = "";
});

{
  const { page, params } = parseHash();
  activate(page, params);
}
