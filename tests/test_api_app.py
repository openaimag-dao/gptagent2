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
    "/api/probability",
    "/api/patterns",
    "/api/knowledge",
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
    for prefix in ("/api/history", "/api/probability", "/api/patterns", "/api/knowledge"):
        assert f"{prefix}/{{symbol}}" in paths


def test_openapi_schema_builds_without_error():
    schema = app.openapi()
    assert schema["info"]["title"] == "AI Market Intelligence Bot"
    assert len(schema["paths"]) >= len(EXPECTED_PREFIXES)
