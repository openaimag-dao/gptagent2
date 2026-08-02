from app.services.common.navigation import NAV_POINTERS, nav_pointer


def test_nav_pointer_returns_none_for_unknown_screen():
    assert nav_pointer("nonexistent_screen") is None


def test_nav_pointer_returns_the_configured_line_for_known_screens():
    for screen, expected in NAV_POINTERS.items():
        assert nav_pointer(screen) == expected


def test_replay_points_to_committee():
    assert "/committee" in nav_pointer("replay")


def test_committee_points_to_replay():
    assert "/replay" in nav_pointer("committee")


def test_scanner_points_to_watchdog():
    assert "/watchdog" in nav_pointer("scanner")


def test_watchdog_points_to_replay():
    assert "/replay" in nav_pointer("watchdog")
