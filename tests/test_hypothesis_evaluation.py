from app.services.hypothesis.evaluation import evaluate_comparison
from app.services.hypothesis.templates import (
    DEFAULT_EVENT_PAIRS,
    DEFAULT_SYMBOLS,
    HypothesisTemplate,
    generate_hypotheses,
)


def _result(occurrences: int, avg_return_pct: float) -> dict:
    return {"occurrences": occurrences, "avg_return_pct": avg_return_pct}


def test_inconclusive_when_either_result_is_none():
    assert evaluate_comparison(None, _result(5, 1.0))[0] == "inconclusive"
    assert evaluate_comparison(_result(5, 1.0), None)[0] == "inconclusive"


def test_inconclusive_when_too_few_occurrences():
    verdict, reason = evaluate_comparison(_result(1, 5.0), _result(1, 0.1))
    assert verdict == "inconclusive"
    assert "Fewer than" in reason


def test_accepted_when_a_much_stronger():
    verdict, reason = evaluate_comparison(_result(10, 5.0), _result(10, 1.0))
    assert verdict == "accepted"
    assert "5.00%" in reason


def test_rejected_when_b_much_stronger():
    verdict, _ = evaluate_comparison(_result(10, 1.0), _result(10, 5.0))
    assert verdict == "rejected"


def test_inconclusive_when_magnitudes_are_close():
    verdict, _ = evaluate_comparison(_result(10, 2.0), _result(10, 2.1))
    assert verdict == "inconclusive"


def test_inconclusive_when_both_zero():
    verdict, _ = evaluate_comparison(_result(10, 0.0), _result(10, 0.0))
    assert verdict == "inconclusive"


def test_accepted_when_b_is_zero_and_a_is_not():
    verdict, _ = evaluate_comparison(_result(10, 2.0), _result(10, 0.0))
    assert verdict == "accepted"


def test_uses_absolute_magnitude_not_sign():
    # a is a strong negative reaction, b is a weak positive one -- a should
    # still "win" since magnitude, not direction, is what's compared.
    verdict, _ = evaluate_comparison(_result(10, -5.0), _result(10, 1.0))
    assert verdict == "accepted"


def test_generate_hypotheses_covers_every_symbol_and_pair():
    hyps = generate_hypotheses()
    assert len(hyps) == len(DEFAULT_SYMBOLS) * len(DEFAULT_EVENT_PAIRS)
    assert all(isinstance(h, HypothesisTemplate) for h in hyps)


def test_hypothesis_statement_is_readable():
    hyp = HypothesisTemplate(symbol="BTC", event_a="fomc", event_b="cpi")
    assert hyp.statement == "BTC reacts stronger to FOMC than to CPI"
