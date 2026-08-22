// Cmd+K command palette (Live Dashboard Upgrade Phase 2). A global
// jump-to-anything box: fuzzy-matches the 46 existing page nav buttons
// (read live from the DOM, not a second hardcoded list, so it can never
// drift out of sync with index.html/PAGES) plus every symbol /api/market
// already returns, and falls back to letting you jump straight to any
// typed symbol's Asset Detail page even if it's not in that list (forex,
// stocks, macro tickers -- anything find_symbol_config() knows about).
// Loaded after app.js: `el`, `navigate`, `fetchJSON` are already defined
// top-level functions/consts in that file by the time this runs.

(function () {
  let symbolsCache = null; // populated lazily on first open, cached after
  let selectedIndex = 0;
  let currentResults = [];

  const overlay = el("div", { class: "cmdk-overlay", id: "cmdk-overlay" });
  const panel = el("div", { class: "cmdk-panel" });
  const input = el("input", {
    type: "text",
    class: "cmdk-input",
    placeholder: "Jump to a page or symbol... (Esc to close)",
    autocomplete: "off",
    spellcheck: "false",
  });
  const resultsList = el("div", { class: "cmdk-results" });
  panel.appendChild(input);
  panel.appendChild(resultsList);
  overlay.appendChild(panel);
  document.body.appendChild(overlay);

  function pageEntries() {
    return [...document.querySelectorAll("nav button[data-page]")].map((btn) => ({
      type: "page",
      key: btn.dataset.page,
      label: btn.textContent,
    }));
  }

  async function ensureSymbols() {
    if (symbolsCache) return symbolsCache;
    const data = await fetchJSON("/api/market").catch(() => null);
    symbolsCache = data && data.quotes ? data.quotes.map((q) => q.symbol) : [];
    return symbolsCache;
  }

  function matchResults(query) {
    const q = query.trim().toUpperCase();
    const pages = pageEntries();
    if (!q) {
      return pages.slice(0, 8);
    }
    const qLower = q.toLowerCase();
    const pageMatches = pages.filter((p) => p.label.toLowerCase().includes(qLower) || p.key.includes(qLower));
    const symbolMatches = (symbolsCache || [])
      .filter((s) => s.includes(q))
      .map((s) => ({ type: "symbol", key: s, label: `${s} -- Asset Detail` }));

    const results = [...pageMatches, ...symbolMatches];

    // Always offer a direct jump for whatever was typed, even if it isn't
    // in the /api/market watchlist (e.g. a forex pair or macro ticker) --
    // the Asset Detail page itself honestly reports "not available" for
    // anything find_symbol_config() doesn't know, same as every other
    // symbol-driven page already does.
    const looksLikeSymbol = /^[A-Z0-9.^]{1,10}$/.test(q);
    const alreadyOffered = results.some((r) => r.type === "symbol" && r.key === q);
    if (looksLikeSymbol && !alreadyOffered) {
      results.push({ type: "symbol", key: q, label: `Go to "${q}" Asset Detail` });
    }
    return results.slice(0, 12);
  }

  function renderResults() {
    resultsList.innerHTML = "";
    if (!currentResults.length) {
      resultsList.appendChild(el("div", { class: "cmdk-empty" }, "No matches."));
      return;
    }
    currentResults.forEach((r, i) => {
      const row = el(
        "div",
        { class: `cmdk-item${i === selectedIndex ? " active" : ""}` },
        [
          el("span", { class: "cmdk-item-label" }, r.label),
          el("span", { class: "cmdk-item-type" }, r.type === "page" ? "page" : "symbol"),
        ]
      );
      row.addEventListener("mouseenter", () => {
        selectedIndex = i;
        renderResults();
      });
      row.addEventListener("click", () => activate(r));
      resultsList.appendChild(row);
    });
  }

  function activate(result) {
    if (!result) return;
    if (result.type === "page") {
      navigate(result.key);
    } else {
      navigate("assetdetail", new URLSearchParams({ symbol: result.key }));
    }
    closePalette();
  }

  function runSearch() {
    currentResults = matchResults(input.value);
    selectedIndex = 0;
    renderResults();
  }

  input.addEventListener("input", runSearch);
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      selectedIndex = Math.min(selectedIndex + 1, currentResults.length - 1);
      renderResults();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      selectedIndex = Math.max(selectedIndex - 1, 0);
      renderResults();
    } else if (e.key === "Enter") {
      e.preventDefault();
      activate(currentResults[selectedIndex]);
    } else if (e.key === "Escape") {
      closePalette();
    }
  });

  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closePalette();
  });

  function openPalette() {
    overlay.classList.add("open");
    input.value = "";
    runSearch();
    input.focus();
    ensureSymbols().then(runSearch);
  }

  function closePalette() {
    overlay.classList.remove("open");
    input.blur();
  }

  function isOpen() {
    return overlay.classList.contains("open");
  }

  document.addEventListener("keydown", (e) => {
    const key = e.key.toLowerCase();
    if ((e.metaKey || e.ctrlKey) && key === "k") {
      e.preventDefault();
      isOpen() ? closePalette() : openPalette();
      return;
    }
    if (key === "escape" && isOpen()) {
      closePalette();
    }
  });

  const hint = document.getElementById("cmdk-hint");
  if (hint) hint.addEventListener("click", openPalette);
})();
