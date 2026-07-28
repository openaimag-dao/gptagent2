"""App-wiring smoke tests -- no database required.

Confirms every router imports cleanly and is actually mounted on the app.
This project's DB-touching endpoints are verified live against real
Postgres (see README), not via a test database fixture, so this file
intentionally stays DB-free: it catches import errors, missing
`app.include_router(...)` calls and route-path typos without needing infra.
"""

from app.main import app

EXPECTED_PREFIXES = {
    "/api/market",
    "/api/btc",
    "/api/news",
    "/api/correlations",
    "/api/regime",
    "/api/signals",
    "/api/report",
    "/api/history",
    "/api/events",
    "/api/calendar",
    "/api/features",
    "/api/research",
    "/api/strategy",
    "/api/hypothesis",
    "/api/ranking",
    "/api/probability",
    "/api/patterns",
    "/api/knowledge",
    "/api/brain",
    "/api/similar",
    "/api/backtest",
    "/api/etf",
    "/api/whales",
    "/api/global-score",
    "/api/agents",
    "/api/memory",
    "/api/scenarios",
    "/api/sentiment",
    "/api/conviction",
    "/api/portfolio",
    "/api/liquidity",
    "/api/admin",
    "/api/consensus",
    "/api/learning",
    "/api/explanation",
    "/api/status",
    "/api/risk",
    "/api/replay",
    "/api/breakout",
    "/api/onchain",
    "/api/committee",
    "/api/whatif",
    "/api/quality",
}


def _route_paths() -> set[str]:
    return {route.path for route in app.routes}


def test_health_route_registered():
    assert "/health" in _route_paths()


def test_every_expected_router_is_mounted():
    paths = _route_paths()
    for prefix in EXPECTED_PREFIXES:
        assert any(path.startswith(prefix) for path in paths), f"no route under {prefix}"


def test_history_and_probability_and_patterns_and_knowledge_take_a_symbol_path_param():
    paths = _route_paths()
    for prefix in (
        "/api/history",
        "/api/probability",
        "/api/patterns",
        "/api/knowledge",
        "/api/learning",
        "/api/explanation",
        "/api/breakout",
        "/api/onchain",
        "/api/quality",
    ):
        assert f"{prefix}/{{symbol}}" in paths


def test_openapi_schema_builds_without_error():
    schema = app.openapi()
    assert schema["info"]["title"] == "AI Market Intelligence Bot"
    assert len(schema["paths"]) >= len(EXPECTED_PREFIXES)


def test_knowledge_rules_routes_registered_before_symbol_catch_all():
    """/api/knowledge/rules must be declared before /api/knowledge/{symbol} --
    Starlette matches routes in registration order, so a wrong order would
    make "rules" get swallowed as a symbol name."""
    knowledge_routes = [
        r for r in app.routes if getattr(r, "path", "").startswith("/api/knowledge")
    ]
    paths_in_order = [r.path for r in knowledge_routes]
    rules_index = paths_in_order.index("/api/knowledge/rules")
    symbol_index = paths_in_order.index("/api/knowledge/{symbol}")
    assert rules_index < symbol_index


def test_backtest_route_is_post_only():
    methods = {
        method
        for route in app.routes
        if getattr(route, "path", "") == "/api/backtest"
        for method in getattr(route, "methods", set())
    }
    assert methods == {"POST"}
