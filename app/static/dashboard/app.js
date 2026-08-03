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

function card(label, value, sub, cls) {
  return el("div", { class: "card" }, [
    el("div", { class: "label" }, label),
    el("div", { class: `value ${cls || ""}` }, String(value)),
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
    grid.appendChild(card(q.symbol, fmtNum(q.price), fmtPct(q.change_pct_24h), changeClass(q.change_pct_24h)));
  }
  return grid;
}

function pill(available) {
  return el("span", { class: `pill ${available ? "available" : "unavailable"}` }, available ? "available" : "unavailable");
}

function errorBox(err) {
  return el("p", { class: "error" }, `Error: ${err.message}`);
}

function table(headers, rows) {
  const t = el("table");
  t.appendChild(el("tr", {}, headers.map((h) => el("th", {}, h))));
  for (const row of rows) t.appendChild(el("tr", {}, row.map((c) => el("td", {}, c))));
  return t;
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

async function renderOverview() {
  const [market, regime, signals, score] = await Promise.all([
    safe("/api/market"),
    safe("/api/regime"),
    safe("/api/signals"),
    safe("/api/global-score"),
  ]);

  const nodes = [el("h2", {}, "Overview")];
  const top = el("div", { class: "grid" });
  if (regime) top.appendChild(card("Regime", regime.regime.replace(/_/g, " ")));
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

  if (market && market.quotes) {
    nodes.push(el("h2", {}, "Market Snapshot"));
    nodes.push(quoteGrid(market.quotes));
  } else {
    nodes.push(el("p", { class: "error" }, "No market data collected yet."));
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
  const agents = await safe("/api/agents");
  const nodes = [el("h2", {}, "Macro")];
  if (agents && agents.macro) {
    nodes.push(el("pre", { class: "summary" }, agents.macro.summary));
    nodes.push(el("p", { class: "sub" }, agents.macro.data.note));
  } else {
    nodes.push(el("p", { class: "error" }, "Macro agent unavailable."));
  }
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
      ["Time", "Category", "Sentiment", "Title", "Source"],
      data.items.map((n) => [
        n.published_at ? n.published_at.slice(0, 16).replace("T", " ") : "n/a",
        n.category,
        el(
          "span",
          { class: n.sentiment === "bullish" ? "up" : n.sentiment === "bearish" ? "down" : "neutral" },
          n.sentiment
        ),
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
          card("Support", d.support != null ? d.support.toLocaleString() : "n/a"),
          card("Resistance", d.resistance != null ? d.resistance.toLocaleString() : "n/a"),
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

async function renderExplanation() {
  const nodes = [el("h2", {}, "Why")];
  const input = el("input", { type: "text", value: "BTC", placeholder: "Symbol" });
  const btn = el("button", {}, "Load");
  nodes.push(el("div", { class: "controls" }, [input, btn]));
  const results = el("div");
  nodes.push(results);

  async function load() {
    results.innerHTML = "";
    try {
      const d = await fetchJSON(`/api/explanation/${encodeURIComponent(input.value)}`);
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
            Object.entries(d.macro_drivers).map(([k, v]) => [k.replace(/_/g, " "), v == null ? "n/a" : String(v)])
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
      if (!results.children.length) {
        results.appendChild(el("p", { class: "sub" }, "Not enough data computed yet to explain this read."));
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
      await fetchJSON("/api/research/notes/generate", { method: "POST" });
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
      await fetchJSON("/api/hypothesis/test", {
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
          card("Avg calibration error", `${r.average_error_pct}%`),
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
    } catch (err) {
      results.appendChild(errorBox(err));
    }
  }
  btn.addEventListener("click", load);
  load();
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
          .map(([k, v]) => [k.replace(/_/g, " "), v == null ? "n/a" : String(v)])
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
          card("Level", latest.level.toFixed(4)),
          card("Price", latest.price.toFixed(4)),
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
          Object.entries(data.metrics).map(([k, v]) => [k.replace(/_/g, " "), v == null ? "unavailable" : String(v)])
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
      await fetchJSON("/api/portfolio/positions", {
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
                  await fetchJSON(
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
    ["price", "probability_edge", "breakout_probability", "risk_off_score", "liquidity_score"].map(
      (m) => el("option", { value: m }, m)
    )
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
      await fetchJSON("/api/alerts/rules", {
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

  return nodes;
}

const PAGES = {
  overview: renderOverview, consensus: renderConsensus, committee: renderCommittee, terminal: renderTerminal, macro: renderMacro, crypto: renderCrypto,
  stocks: renderStocks,
  correlations: renderCorrelations, news: renderNews, history: renderHistory, events: renderEvents,
  patterns: renderPatterns, breakout: renderBreakout, liquidity: renderLiquidity, sentiment: renderSentiment,
  calendar: renderCalendar, similarity: renderSimilarity, brain: renderBrain,
  research: renderResearch, strategies: renderStrategies,
  probability: renderProbability, learning: renderLearning, quality: renderQuality,
  scenarios: renderScenarios,
  whatif: renderWhatif,
  whales: renderWhales, etf: renderEtf, onchain: renderOnchain,
  signals: renderSignals, reports: renderReports, portfolio: renderPortfolio, advice: renderAdvice,
  alerts: renderAlerts,
  risk: renderRisk, why: renderExplanation, watchdog: renderWatchdog, status: renderStatus,
  replay: renderReplay, shocks: renderShocks, technical: renderTechnical, scanner: renderScanner,
  memory: renderMemory,
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
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("active", b.dataset.page === page));
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

document.querySelectorAll("nav button").forEach((btn) => {
  btn.addEventListener("click", () => navigate(btn.dataset.page));
});

document.getElementById("nav-toggle").addEventListener("click", () => {
  document.getElementById("nav").classList.toggle("open");
});

const symbolSearch = document.getElementById("symbol-search");
symbolSearch.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !symbolSearch.value.trim()) return;
  navigate("history", new URLSearchParams({ symbol: symbolSearch.value.trim().toUpperCase() }));
  symbolSearch.value = "";
});

{
  const { page, params } = parseHash();
  activate(page, params);
}
