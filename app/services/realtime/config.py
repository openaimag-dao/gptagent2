"""Parses the comma-separated realtime settings (app.config.settings) into
usable lists -- kept as pure functions so both the collector and the
/api/realtime/status endpoint parse identically without duplicating
`.split(",")` logic."""


def parse_watchlist(raw: str) -> list[str]:
    return [symbol.strip().upper() for symbol in raw.split(",") if symbol.strip()]


def parse_backoff_seconds(raw: str) -> list[float]:
    return [float(value.strip()) for value in raw.split(",") if value.strip()]
