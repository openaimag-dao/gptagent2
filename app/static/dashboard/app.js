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
      ["Stock Strength", "stock_strength_score"],
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
        el("span", { class: changeClass(c.correlation) }, c.correlation.toFixed(2)),
        String(c.data_points),
      ])
    )
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
          ["Date", "RSI", "Forward return"],
          knowledge.analogs.map((a) => [a.timestamp.slice(0, 10), a.rsi.toFixed(1), fmtPct(a.forward_return_pct)])
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
  for (const [label, key] of sections) {
    nodes.push(el("h2", {}, label));
    nodes.push(el("pre", { class: "summary" }, a[key] || "n/a"));
  }
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

async function renderScenarios() {
  const data = await safe("/api/scenarios");
  const nodes = [el("h2", {}, "Scenarios")];
  if (!data) {
    nodes.push(el("p", { class: "error" }, "Not enough data yet."));
    return nodes;
  }
  for (const s of [...data.scenarios].sort((a, b) => b.probability_pct - a.probability_pct)) {
    nodes.push(
      card(s.name, `${s.probability_pct}%`, s.rationale)
    );
  }
  return nodes;
}

async function renderWhales() {
  const data = await safe("/api/whales");
  const nodes = [el("h2", {}, "Whale Intelligence")];
  if (!data) return nodes;
  nodes.push(el("p", {}, [pill(data.available), " ", data.symbol]));
  if (data.available) {
    nodes.push(el("pre", { class: "summary" }, JSON.stringify(data, null, 2)));
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
      card("Generated", report.generated_at.slice(0, 19).replace("T", " ")),
    ])
  );
  nodes.push(el("h2", {}, "Institutional Summary"));
  nodes.push(el("pre", { class: "summary" }, JSON.stringify(report.institutional_summary, null, 2)));
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

async function renderSettings() {
  const nodes = [el("h2", {}, "Settings")];
  nodes.push(
    el("p", { class: "sub" }, "Configuration lives in .env (see .env.example in the repository) -- no secrets are exposed through this dashboard.")
  );
  const memory = await safe("/api/memory?limit=1");
  if (memory) {
    nodes.push(el("h2", {}, "Available Memory Categories"));
    nodes.push(el("p", { class: "sub" }, memory.categories.join(", ")));
  }
  return nodes;
}

const PAGES = {
  overview: renderOverview, macro: renderMacro, crypto: renderCrypto, stocks: renderStocks,
  correlations: renderCorrelations, similarity: renderSimilarity, brain: renderBrain,
  probability: renderProbability, scenarios: renderScenarios, whales: renderWhales, etf: renderEtf,
  signals: renderSignals, reports: renderReports, portfolio: renderPortfolio, settings: renderSettings,
};

document.querySelectorAll("nav button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("nav button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    render(PAGES[btn.dataset.page]);
  });
});

render(renderOverview);
