// Live Dashboard Upgrade -- one shared realtime price store for the whole
// dashboard. Loaded before app.js. Exactly one EventSource connection to
// /api/realtime/prices exists for the entire page, no matter how many
// price cards subscribe to it -- never one connection per card.
//
// Every value here comes from a real Binance tick relayed through the
// backend's SSE endpoint; there is no simulated/random price update path.

const RealtimeStore = (() => {
  const RECONNECT_BACKOFF_SECONDS = [1, 2, 5, 10, 30];
  const LOCAL_RECLASSIFY_INTERVAL_MS = 5000;

  const state = new Map(); // symbol -> tick-shaped object (see applyTick)
  const subscribers = new Set(); // fn(dirtySymbols: Set<string>)
  const statusSubscribers = new Set(); // fn(status, latencyMs)

  let thresholds = null; // fetched once from /api/realtime/status, never hardcoded

  // Two distinct connection states, kept separate on purpose: this
  // browser tab's own SSE link to *our* server can be perfectly healthy
  // while the backend collector's upstream Binance WebSocket is down (or
  // vice versa mid-reconnect) -- collapsing them into one flag would let
  // the header claim "LIVE" while prices are actually not live at all.
  let browserStatus = "connecting"; // this tab's EventSource connection
  let upstreamStatus = "connecting"; // backend collector's Binance connection
  let connectionStatus = "connecting"; // the honest, displayed combination of both
  let latencyMs = null;
  let eventSource = null;
  let backoffIndex = 0;
  let reconnectTimer = null;
  let dirty = new Set();
  let flushScheduled = false;
  let started = false;

  function scheduleFlush() {
    if (flushScheduled) return;
    flushScheduled = true;
    const raf = window.requestAnimationFrame || ((fn) => setTimeout(fn, 16));
    raf(() => {
      flushScheduled = false;
      const symbols = dirty;
      dirty = new Set();
      if (symbols.size === 0) return;
      for (const fn of subscribers) {
        try {
          fn(symbols);
        } catch (e) {
          console.error("RealtimeStore subscriber error", e);
        }
      }
    });
  }

  // The tab's own SSE link is a necessary but not sufficient condition for
  // "prices are live": if it's down, that's the honest thing to show
  // (RECONNECTING/OFFLINE to our server). If it's up, what actually
  // matters to the user is whether the backend's Binance link is up --
  // so the upstream state passes through unchanged in that case.
  function recomputeAndPublishStatus() {
    const next = browserStatus === "connected" ? upstreamStatus : browserStatus;
    if (next === connectionStatus) return;
    connectionStatus = next;
    for (const fn of statusSubscribers) {
      try {
        fn(connectionStatus, latencyMs);
      } catch (e) {
        console.error("RealtimeStore status subscriber error", e);
      }
    }
  }

  function setBrowserStatus(next) {
    browserStatus = next;
    recomputeAndPublishStatus();
  }

  function setUpstreamStatus(next) {
    upstreamStatus = next;
    recomputeAndPublishStatus();
  }

  function classifyFreshness(ageSeconds) {
    if (!thresholds) return "recent";
    if (ageSeconds < thresholds.live_seconds) return "live";
    if (ageSeconds < thresholds.recent_seconds) return "recent";
    if (ageSeconds < thresholds.delayed_seconds) return "delayed";
    if (ageSeconds < thresholds.stale_seconds) return "stale";
    return "offline";
  }

  function applyTick(tick) {
    const prev = state.get(tick.symbol);
    const receivedAtMs = Date.parse(tick.received_at);
    if (!Number.isNaN(receivedAtMs)) {
      latencyMs = Math.max(0, Date.now() - receivedAtMs);
    }
    state.set(tick.symbol, {
      symbol: tick.symbol,
      price: tick.price,
      previousPrice: prev ? prev.price : null,
      change24h: tick.change_24h,
      changePercent24h: tick.change_pct_24h,
      volume24h: tick.volume_24h,
      high24h: tick.high_24h,
      low24h: tick.low_24h,
      source: tick.source,
      timestamp: tick.event_timestamp,
      receivedAt: tick.received_at,
      freshness: tick.freshness || classifyFreshness(tick.age_seconds || 0),
      ageSeconds: tick.age_seconds || 0,
      status: connectionStatus,
    });
    dirty.add(tick.symbol);
    scheduleFlush();
  }

  function reclassifyLocally() {
    const now = Date.now();
    for (const [symbol, entry] of state.entries()) {
      const receivedAtMs = Date.parse(entry.receivedAt);
      if (Number.isNaN(receivedAtMs)) continue;
      const ageSeconds = (now - receivedAtMs) / 1000;
      const freshness = classifyFreshness(ageSeconds);
      if (freshness !== entry.freshness) {
        state.set(symbol, { ...entry, freshness, ageSeconds });
        dirty.add(symbol);
      } else {
        entry.ageSeconds = ageSeconds;
      }
    }
    scheduleFlush();
  }

  async function loadThresholds() {
    try {
      const res = await fetch("/api/realtime/status");
      const body = await res.json();
      thresholds = body.freshness_thresholds || null;
    } catch (e) {
      // Freshness badges fall back to a conservative "recent" label above
      // until this succeeds -- never fabricated as "live".
      console.error("Could not load realtime freshness thresholds", e);
    }
  }

  function scheduleReconnect() {
    const atLastStep = backoffIndex >= RECONNECT_BACKOFF_SECONDS.length - 1;
    setBrowserStatus(atLastStep ? "offline" : "reconnecting");
    const delaySeconds = RECONNECT_BACKOFF_SECONDS[Math.min(backoffIndex, RECONNECT_BACKOFF_SECONDS.length - 1)];
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(() => {
      backoffIndex += 1;
      connect();
    }, delaySeconds * 1000);
  }

  function connect() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    setBrowserStatus(backoffIndex === 0 ? "connecting" : "reconnecting");
    eventSource = new EventSource("/api/realtime/prices");

    eventSource.onopen = () => {
      backoffIndex = 0;
      setBrowserStatus("connected");
    };
    eventSource.onmessage = (ev) => {
      try {
        applyTick(JSON.parse(ev.data));
      } catch (e) {
        console.error("Bad realtime tick payload", e);
      }
    };
    // The backend collector's own Binance connection state -- this tab's
    // SSE link to *our* server can be healthy while Binance itself is
    // unreachable (e.g. network-restricted deployment), so the header
    // must reflect this, not just "is my browser talking to the backend."
    eventSource.addEventListener("status", (ev) => {
      try {
        const payload = JSON.parse(ev.data);
        if (payload && payload.status) setUpstreamStatus(payload.status);
      } catch (e) {
        console.error("Bad realtime status payload", e);
      }
    });
    // Replaces the browser's built-in fixed-interval EventSource retry
    // with the spec's 1/2/5/10/30s capped backoff -- close immediately so
    // the native retry never fires, then reconnect on our own schedule.
    eventSource.onerror = () => {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      scheduleReconnect();
    };
  }

  async function start() {
    if (started) return;
    started = true;
    await loadThresholds();
    connect();
    setInterval(reclassifyLocally, LOCAL_RECLASSIFY_INTERVAL_MS);
  }

  function subscribe(fn) {
    subscribers.add(fn);
    return () => subscribers.delete(fn);
  }

  function subscribeStatus(fn) {
    statusSubscribers.add(fn);
    fn(connectionStatus, latencyMs);
    return () => statusSubscribers.delete(fn);
  }

  function get(symbol) {
    return state.get(symbol) || null;
  }

  function getStatus() {
    return { status: connectionStatus, latencyMs };
  }

  // Only one ticker/price-grid section is ever visible at a time (whichever
  // page is currently rendered) -- mounting a new one always tears down the
  // previous mount's subscription first, so page navigation never leaks
  // subscribers bound to DOM nodes that were already discarded.
  let currentMountUnsubscribe = null;

  function mount(onUpdate) {
    if (currentMountUnsubscribe) currentMountUnsubscribe();
    const unsubData = subscribe(onUpdate.onTick || (() => {}));
    const unsubStatus = onUpdate.onStatus ? subscribeStatus(onUpdate.onStatus) : () => {};
    currentMountUnsubscribe = () => {
      unsubData();
      unsubStatus();
    };
    return currentMountUnsubscribe;
  }

  return { start, subscribe, subscribeStatus, get, getStatus, mount };
})();

RealtimeStore.start();
