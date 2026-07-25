from app.services.learning.engine import predicted_direction, realized_direction


def test_predicted_direction_picks_the_max():
    assert predicted_direction(60, 30, 10) == "up"
    assert predicted_direction(10, 70, 20) == "down"
    assert predicted_direction(20, 20, 60) == "flat"


def test_realized_direction_positive_is_up():
    assert realized_direction(1.5) == "up"


def test_realized_direction_negative_is_down():
    assert realized_direction(-0.3) == "down"


def test_realized_direction_zero_is_flat():
    assert realized_direction(0.0) == "flat"
