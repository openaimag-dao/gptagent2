from datetime import UTC, datetime

from app.database.models import (
    AssetClass,
    AssetPrice,
    BreakoutEvent,
    GlobalMarketScore,
    MarketRegimeSnapshot,
    SignalSnapshot,
)
from app.services.analysis.regime import MarketRegime
from app.services.consensus.engine import ConsensusResult
from app.telegram.formatters import (
    format_advice,
    format_asset_class,
    format_breakout,
    format_committee,
    format_consensus,
    format_explanation,
    format_global_score,
    format_learning,
    format_market_summary,
    format_onchain,
    format_quality,
    format_regime,
    format_replay,
    format_risk,
    format_signal,
    format_single_asset,
    format_status,
    format_watchdog,
    format_whatif,
)


def _asset(
    symbol: str,
    asset_class: AssetClass,
    price: float,
    change_pct_24h: float | None = None,
) -> AssetPrice:
    return AssetPrice(
        symbol=symbol,
        name=symbol,
        asset_class=asset_class,
        price=price,
        change_pct_24h=change_pct_24h,
        source="test",
    )


def test_format_market_summary_empty():
    assert "No market data" in format_market_summary([])


def test_format_market_summary_groups_by_class():
    assets = [
        _asset("BTC", AssetClass.CRYPTO, 65000.0, 1.5),
        _asset("NASDAQ", AssetClass.INDEX, 18000.0, -0.5),
    ]

    text = format_market_summary(assets)

    assert "Crypto" in text
    assert "Indices" in text
    assert "BTC: 65,000.00" in text
    assert "NASDAQ: 18,000.00" in text


def test_format_asset_class_filters_correctly():
    assets = [
        _asset("BTC", AssetClass.CRYPTO, 65000.0, 1.5),
        _asset("NASDAQ", AssetClass.INDEX, 18000.0, -0.5),
    ]

    text = format_asset_class(assets, AssetClass.CRYPTO, "Crypto Market")

    assert "BTC" in text
    assert "NASDAQ" not in text


def test_format_single_asset_missing():
    assert "No data available" in format_single_asset("BTC", None)


def test_format_single_asset_present():
    asset = _asset("BTC", AssetClass.CRYPTO, 65000.0, 1.5)
    text = format_single_asset("BTC", asset)
    assert "65,000.00" in text
    assert "+1.50%" in text


def test_format_signal_missing():
    assert "No signal has been computed" in format_signal(None)


def test_format_signal_present():
    snapshot = SignalSnapshot(
        bull_score=5,
        bear_score=2,
        net_score=3,
        confidence_pct=60,
        factors={"nasdaq_up": {"points": 2, "triggered": True}},
    )
    text = format_signal(snapshot)
    assert "Bull score: 5" in text
    assert "Nasdaq up" in text
    assert "_" not in text


def test_format_regime_present():
    snapshot = MarketRegimeSnapshot(regime=MarketRegime.RISK_ON, inputs={})
    assert "Risk On" in format_regime(snapshot)


def test_format_consensus_none():
    assert "nothing to tally" in format_consensus(None)


def test_format_consensus_present():
    result = ConsensusResult(
        bullish_pct=70.0,
        bearish_pct=30.0,
        neutral_pct=0.0,
        agreement_score=70.0,
        bullish_agents=["news", "equity"],
        bearish_agents=["macro"],
    )
    text = format_consensus(result)
    assert "Bullish 70.0%" in text
    assert "news, equity" in text
    assert "macro" in text


def test_format_learning_none():
    text = format_learning(None, "BTC", "1d")
    assert "No graded predictions" in text
    assert "BTC/1d" in text


def test_format_learning_present():
    result = {
        "symbol": "BTC",
        "timeframe": "1d",
        "evaluated_predictions": 2,
        "accuracy_pct": 50.0,
        "recent": [
            {
                "reference_timestamp": datetime(2026, 1, 1, tzinfo=UTC),
                "predicted": "up",
                "realized": "up",
                "correct": True,
                "realized_return_pct": 1.5,
            },
            {
                "reference_timestamp": datetime(2026, 1, 2, tzinfo=UTC),
                "predicted": "up",
                "realized": "down",
                "correct": False,
                "realized_return_pct": -0.8,
            },
        ],
    }
    text = format_learning(result, "BTC", "1d")
    assert "Accuracy: 50.0%" in text
    assert "correct" in text
    assert "wrong" in text


def test_format_advice_none():
    text = format_advice(None, "BTC", "1d")
    assert "Not enough data yet" in text
    assert "BTC/1d" in text


def test_format_advice_buy_with_levels():
    advice = {
        "symbol": "BTC",
        "timeframe": "1d",
        "recommendation": "BUY",
        "reasoning": (
            "Signal Engine net score 3 (bullish) agrees with the empirical probability read."
        ),
        "signal_net_score": 3,
        "probability": {"up": 60, "down": 20, "flat": 20},
        "entry_reference_price": 100.0,
        "atr": 5.0,
        "stop_loss_price": 90.0,
        "take_profit_price": 120.0,
        "risk_reward_ratio": 2.0,
        "position_size_quantity": 10.0,
        "position_size_note": (
            "Sized to risk 1.0% of portfolio equity (100.00) if stopped out at 90.0."
        ),
    }
    text = format_advice(advice, "BTC", "1d")
    assert "BTC ADVICE" in text
    assert "BUY" in text
    assert "Stop-loss: 90.00" in text
    assert "Take-profit: 120.00" in text
    assert "Position size: 10.0" in text


def test_format_advice_hold_no_levels():
    advice = {
        "symbol": "BTC",
        "timeframe": "1d",
        "recommendation": "HOLD",
        "reasoning": (
            "Signal Engine net score 3 (bullish) disagrees with the empirical probability read."
        ),
        "signal_net_score": 3,
        "probability": {"up": 20, "down": 60, "flat": 20},
        "entry_reference_price": 100.0,
        "atr": 5.0,
        "stop_loss_price": None,
        "take_profit_price": None,
        "risk_reward_ratio": None,
        "position_size_quantity": None,
        "position_size_note": None,
    }
    text = format_advice(advice, "BTC", "1d")
    assert "HOLD" in text
    assert "Stop-loss" not in text
    assert "Position size" not in text


def test_format_explanation_empty():
    data = {
        "symbol": "BTC",
        "indicators": [],
        "macro_drivers": {},
        "historical_examples": [],
        "supporting_news": [],
        "risk_factors": None,
        "alternative_view": None,
    }
    text = format_explanation(data)
    assert "WHY -- BTC" in text
    assert "Not enough data" in text


def test_format_explanation_full():
    data = {
        "symbol": "BTC",
        "indicators": [{"name": "rsi_oversold", "points": 3, "triggered": True}],
        "macro_drivers": {"dxy_trend": "down"},
        "historical_examples": [
            {
                "match_timestamp": "2024-01-05T00:00:00",
                "similarity_score": 82.0,
                "regime": "bull",
                "forward_return_7d_pct": 4.2,
            }
        ],
        "supporting_news": [{"title": "ETF inflows surge", "sentiment": "bullish", "url": "x"}],
        "risk_factors": {"fear_score": 30, "macro_pressure_score": 40, "risk_off_score": 20},
        "alternative_view": {
            "name": "Bear case",
            "probability_pct": 25,
            "rationale": "DXY strength",
        },
    }
    text = format_explanation(data)
    assert "rsi oversold" in text
    assert "dxy trend: down" in text
    assert "ETF inflows surge" in text
    assert "82% similar" in text
    assert "Fear 30" in text
    assert "Bear case (25%)" in text


def test_format_status():
    text = format_status({"Signal": datetime(2026, 1, 1, tzinfo=UTC), "Regime": None})
    assert "Signal: 2026-01-01T00:00:00+00:00" in text
    assert "Regime: never computed" in text


def test_format_risk_with_data():
    text = format_risk(
        {
            "global_score": {
                "risk_off_score": 60,
                "risk_on_score": 40,
                "fear_score": 55,
                "macro_pressure_score": 45,
            },
            "signal_conviction": {"tier": "Strong", "effective_confidence_pct": 72},
        }
    )
    assert "Risk-off: 60/100" in text
    assert "Strong (72%)" in text


def test_format_risk_without_data():
    text = format_risk({"global_score": None, "signal_conviction": None})
    assert "not computed yet" in text
    assert "unavailable" in text


def test_format_watchdog_empty():
    assert "No detections logged yet" in format_watchdog([])


def test_format_watchdog_shows_sent_and_suppressed():
    entries = [
        {
            "category": "alerts",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "summary": {
                "alert_type": "flash_crash",
                "message": "BTC crashed -10.00% in 24h.",
                "conviction_tier": "Strong",
                "broadcast": True,
            },
        },
        {
            "category": "alerts",
            "timestamp": "2026-01-01T00:05:00+00:00",
            "summary": {
                "alert_type": "funding_shift",
                "message": "Funding-rate momentum rising.",
                "conviction_tier": "Medium",
                "broadcast": False,
            },
        },
    ]
    text = format_watchdog(entries)
    assert "flash_crash" in text
    assert "sent" in text
    assert "suppressed" in text


def _global_score(**overrides) -> GlobalMarketScore:
    defaults = dict(
        risk_on_score=50,
        risk_off_score=50,
        liquidity_score=50,
        fear_score=50,
        greed_score=50,
        macro_pressure_score=50,
        institutional_activity_score=50,
        crypto_strength_score=50,
        stock_strength_score=50,
        global_score=50,
        trend_strength_score=None,
        risk_score=None,
        confidence_score=None,
    )
    defaults.update(overrides)
    return GlobalMarketScore(**defaults)


def test_format_global_score_shows_unavailable_for_missing_new_subscores():
    text = format_global_score(_global_score())
    assert "Trend strength: unavailable" in text
    assert "Risk score: unavailable" in text
    assert "Confidence score: unavailable" in text


def test_format_global_score_shows_new_subscores_when_present():
    text = format_global_score(
        _global_score(trend_strength_score=72, risk_score=60, confidence_score=85)
    )
    assert "Trend strength: 72" in text
    assert "Risk score: 60" in text
    assert "Confidence score: 85" in text


def test_format_breakout_none():
    assert "No breakout/breakdown detected" in format_breakout("BTC", None)


def test_format_breakout_present():
    event = BreakoutEvent(
        symbol="BTC",
        timeframe="1d",
        event_type="breakout",
        direction="bullish",
        level=60000.0,
        price=61500.0,
        probability_pct=72.5,
        confidence_pct=83,
        risk_score=65.0,
        expected_continuation="likely to continue",
        reasoning="Breakout (bullish). Confirmed by: volume, market regime.",
    )
    text = format_breakout("BTC", event)
    assert "BTC BREAKOUT INTELLIGENCE" in text
    assert "Breakout (bullish)" in text
    assert "Probability: 72.5%" in text
    assert "Confidence: 83%" in text
    assert "Risk score: 65.0/100" in text
    assert "likely to continue" in text


def test_format_onchain_reports_unavailable_metrics():
    snapshot = {
        "symbol": "BTC",
        "available": False,
        "reason": "No on-chain data provider configured.",
        "metrics": {"sopr": None, "mvrv": None},
    }
    text = format_onchain(snapshot)
    assert "BTC ON-CHAIN INTELLIGENCE" in text
    assert "No on-chain data provider configured." in text
    assert "sopr" in text
    assert "mvrv" in text


def test_format_onchain_includes_solana_note():
    snapshot = {
        "symbol": "SOL",
        "available": False,
        "reason": "No on-chain data provider configured.",
        "metrics": {"dex_volume": None},
        "solana_note": "Solana-specific coverage needs Helius.",
    }
    text = format_onchain(snapshot)
    assert "Solana-specific coverage needs Helius." in text


def test_format_committee_none():
    assert "nothing to vote on" in format_committee(None)


def test_format_committee_present():
    verdict = {
        "majority_decision": "BUY",
        "majority_pct": 70.0,
        "dissent_pct": 30.0,
        "confidence_pct": 70.0,
        "supporting_evidence": [{"agent": "macro", "evidence": "Bullish backdrop."}],
        "opposing_evidence": [{"agent": "equity", "evidence": "Weak breadth."}],
        "minority_opinion": "equity (bearish): Weak breadth.",
        "final_recommendation": "BUY (high conviction)",
        "reasoning": "Majority decision: BUY with 70.0% of weighted committee votes (macro).",
    }
    text = format_committee(verdict)
    assert "AI INVESTMENT COMMITTEE" in text
    assert "BUY (high conviction)" in text
    assert "Dissent: 30.0%" in text
    assert "Supporting evidence" in text
    assert "Opposing evidence (minority)" in text
    assert "Weak breadth." in text


def test_format_whatif_none():
    assert "Unknown scenario" in format_whatif(None)


def test_format_whatif_historical_event_study():
    result = {
        "scenario_key": "fed_cuts_rates",
        "scenario_label": "Fed Cuts Rates",
        "description": "The Federal Reserve cuts its target rate.",
        "data_source": "historical_event_study",
        "impact": {
            "BTC": {"expected_return_7d_pct": 5.0, "sample_size": 8},
            "altcoins": {"expected_return_7d_pct": 8.0, "sample_size": None},
        },
        "current_regime": "accumulation",
        "likely_regime_shift_toward": "liquidity_expansion",
        "risk_direction": "down",
        "liquidity_direction": "up",
        "reasoning": "Rate cuts historically ease financial conditions.",
    }
    text = format_whatif(result)
    assert "FED CUTS RATES" in text
    assert "historical event study" in text
    assert "BTC: +5.00% (7d) [8 historical occurrences]" in text
    assert "accumulation -> likely shift toward liquidity expansion" in text
    assert "Risk: down | Liquidity: up" in text


def test_format_whatif_correlation_direction():
    result = {
        "scenario_key": "dxy_drops",
        "scenario_label": "DXY Drops",
        "description": "The US Dollar Index falls.",
        "data_source": "correlation_direction",
        "impact": {"BTC": {"direction": "bullish", "correlation_30d": -0.4}},
        "current_regime": None,
        "likely_regime_shift_toward": "risk_on",
        "risk_direction": "down",
        "liquidity_direction": "up",
        "reasoning": "Direction derived from the real stored correlation.",
    }
    text = format_whatif(result)
    assert "BTC: bullish (correlation -0.4)" in text


def test_format_quality_none():
    text = format_quality(None, "BTC", "1d")
    assert "No graded predictions" in text
    assert "BTC/1d" in text


def test_format_quality_present():
    result = {
        "symbol": "BTC",
        "timeframe": "1d",
        "evaluated_predictions": 10,
        "accuracy_pct": 70.0,
        "brier_score": 0.25,
        "average_error_pct": 20.0,
        "precision_recall": {
            "macro_precision_pct": 75.0,
            "macro_recall_pct": 72.0,
            "per_class": {
                "up": {"precision_pct": 80.0, "recall_pct": 75.0, "support": 4},
                "down": {"precision_pct": 70.0, "recall_pct": 69.0, "support": 4},
                "flat": {"precision_pct": None, "recall_pct": None, "support": 0},
            },
        },
        "calibration": [
            {
                "confidence_bucket": "60-80%",
                "count": 5,
                "avg_predicted_confidence_pct": 65.0,
                "observed_accuracy_pct": 60.0,
                "calibration_gap_pct": 5.0,
            }
        ],
        "time_horizon_accuracy": [{"horizon_periods": 1, "count": 10, "accuracy_pct": 70.0}],
    }
    text = format_quality(result, "BTC", "1d")
    assert "BTC PREDICTION QUALITY LAB" in text
    assert "Brier score: 0.25" in text
    assert "Macro precision: 75.0% | Macro recall: 72.0%" in text
    assert "60-80%" in text
    assert "1 period(s)" in text


def test_format_replay_none():
    assert "No market snapshot" in format_replay(None)


def test_format_replay_present():
    snapshot = {
        "computed_at": "2026-01-01T00:00:00+00:00",
        "regime": "bull",
        "health_score": 70,
        "trend_strength_score": 55,
        "risk_score": 40,
        "confidence_score": 60,
        "consensus": {
            "bullish_pct": 60.0,
            "bearish_pct": 30.0,
            "neutral_pct": 10.0,
            "conflict_pct": 40.0,
        },
        "portfolio_advice": {"symbol": "BTC", "recommendation": "BUY"},
        "alerts": [{"alert_type": "flash_rally"}],
    }
    text = format_replay(snapshot)
    assert "Bull" in text
    assert "bullish 60.0%" in text
    assert "Portfolio advice (BTC): BUY" in text
    assert "Alerts since previous snapshot: 1" in text
