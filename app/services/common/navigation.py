"""v10.0 "Smart Navigation" -- a one-line pointer from a screen to the
related intelligence a trader would naturally check next (e.g. Replay ->
"See current Committee opinion"). Purely presentational: names the existing
Telegram command that already serves that related screen. No new data
fetch, no new computation, no new command -- every screen already has
everything it needs, this just says where to look next.
"""

NAV_POINTERS: dict[str, str] = {
    "replay": "Related: See current Committee opinion -- /committee",
    "committee": "Related: Compare with historical Replay -- /replay",
    "consensus": "Related: See Committee's structured verdict -- /committee",
    "scanner": "Related: View latest Watchdog events -- /watchdog events",
    "watchdog": "Related: Open historical comparison -- /replay",
    "brief": "Related: Compare with historical Replay -- /replay",
}


def nav_pointer(screen: str) -> str | None:
    """Returns the standard pointer line for `screen`, or None for a screen
    that doesn't have one yet -- callers should skip appending it rather
    than fabricate a placeholder."""
    return NAV_POINTERS.get(screen)
