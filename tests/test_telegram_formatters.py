from datetime import UTC, datetime
from types import SimpleNamespace

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
    format_active_shocks,
    format_advice,
    format_alert_history,
    format_alert_rule_created,
    format_alert_rules,
    format_asset_class,
    format_breakout,
    format_brief,
    format_committee,
    format_consensus,
    format_critical_alert,
    format_explanation,
    format_global_score,
    format_historical_comparison,
    format_learning,
    format_market_summary,
    format_monthly_performance,
    format_onchain,
    format_opportunities,
    format_quality,
    format_regime,
    format_replay,
    format_risk,
    format_scanner_alert,
    format_scanner_dashboard,
    format_scanner_detections,
    format_scanner_movers,
    format_scanner_sectors,
    format_signal,
    format_single_asset,
    format_status,
    format_technical,
    format_watchdog,
    format_watchdog_brief,
    format_weekly_review,
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
        agent_weights={"news": 40.0, "equity": 30.0, "macro": 30.0},
        agent_evidence={"news": "Headlines skew risk-on.", "macro": "DXY strength weighs."},
    )
    text = format_consensus(result)
    assert "Bullish 70.0%" in text
    assert "news" in text
    assert "equity" in text
    assert "macro" in text
    assert "Strongest influence: news" in text
    assert "Headlines skew risk-on." in text


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


def test_format_watchdog_brief_answers_the_control_center_questions():
    brief = {
        "is_market_healthy": False,
        "market_health_label": "Stressed",
        "risk_direction": "increasing",
        "risk_reason": "Risk score rose from 30 to 60.",
        "ai_opinion_changed": True,
        "ai_opinion_reason": "AI Investment Committee decision changed: HOLD -> SELL.",
        "biggest_changes_today": ["Risk score rose from 30 to 60.", "Committee changed to SELL."],
        "needs_attention": ["Risk score rose from 30 to 60."],
    }
    text = format_watchdog_brief(brief)
    assert "MARKET CONTROL CENTER" in text
    assert "Is the market healthy? No (Stressed)" in text
    assert "Is risk increasing? Increasing" in text
    assert "Did AI change its opinion? Yes" in text
    assert "HOLD -> SELL" in text
    assert "Committee changed to SELL." in text
    assert "Needs attention now:" in text


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
        "supporting_evidence": [
            {"agent": "macro", "confidence": 80.0, "evidence": "Bullish backdrop."}
        ],
        "opposing_evidence": [
            {"agent": "equity", "confidence": 55.0, "evidence": "Weak breadth."}
        ],
        "minority_opinion": "equity (bearish): Weak breadth.",
        "final_recommendation": "BUY (high conviction)",
        "reasoning": "Majority decision: BUY with 70.0% of weighted committee votes (macro).",
        "invalidation_risk": "macro contributes the least weight to the BUY majority (70.0%).",
    }
    text = format_committee(verdict)
    assert "AI INVESTMENT COMMITTEE" in text
    assert "BUY (high conviction)" in text
    assert "Dissent: 30.0%" in text
    assert "Supporting evidence" in text
    assert "80.0% confidence" in text
    assert "Opposing evidence (minority)" in text
    assert "Weak breadth." in text
    assert "Invalidation risk:" in text


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


def test_format_opportunities_empty():
    assert "No opportunities computed" in format_opportunities([])


def test_format_opportunities_present():
    opportunities = [
        {
            "symbol": "BTC",
            "classification": "bullish",
            "opportunity_score": 78.0,
            "probability_edge_pct": 40.0,
            "breakout": {"event_type": "breakout", "direction": "bullish", "probability_pct": 70.0},
            "advisor_recommendation": "BUY",
        }
    ]
    text = format_opportunities(opportunities)
    assert "BTC" in text
    assert "bullish (78.0/100)" in text
    assert "probability edge +40.0%" in text
    assert "advisor: BUY" in text


def test_format_brief_no_committee_no_opportunities():
    brief = {
        "committee": None,
        "risk": None,
        "top_opportunities": [],
        "portfolio": {"empty": True, "positions": []},
        "regime": "bull",
        "health_score": 60,
    }
    text = format_brief(brief)
    assert "DAILY TERMINAL BRIEF" in text
    assert "no agent reported a direction" in text
    assert "none computed this cycle" in text
    assert "no positions held" in text


def test_format_brief_full():
    brief = {
        "committee": {
            "final_recommendation": "BUY (high conviction)",
            "majority_decision": "BUY",
            "majority_pct": 80.0,
            "dissent_pct": 20.0,
        },
        "risk": {"risk_off_score": 30, "liquidity_score": 65},
        "top_opportunities": [
            {"symbol": "BTC", "classification": "bullish", "opportunity_score": 78.0}
        ],
        "portfolio": {"empty": False, "health_score": 72, "total_value": 10000.0},
        "regime": "bull",
        "health_score": 65,
    }
    text = format_brief(brief)
    assert "Committee*: BUY (high conviction)" in text
    assert "Risk-off: 30/100" in text
    assert "BTC: bullish (78.0/100)" in text
    assert "health 72/100" in text


def test_format_historical_comparison_none():
    assert "Not enough Market Replay history" in format_historical_comparison(None)


def test_format_historical_comparison_present():
    result = {
        "days_ago": 7,
        "diff": {
            "regime": {"from": "bull", "to": "bear", "changed": True},
            "health_score": {"from": 60, "to": 40, "delta": -20},
            "trend_strength_score": {"from": None, "to": None, "delta": None},
            "risk_score": {"from": 30, "to": 50, "delta": 20},
            "confidence_score": {"from": None, "to": None, "delta": None},
        },
    }
    text = format_historical_comparison(result)
    assert "7 days ago" in text
    assert "bull -> bear (changed)" in text
    assert "Health Score: 60 -> 40 (-20)" in text
    assert "Risk Score: 30 -> 50 (+20)" in text


def test_format_weekly_review():
    result = {
        "evaluated_predictions": 5,
        "accuracy_pct": 60.0,
        "alerts_count": 3,
        "historical_comparison": None,
    }
    text = format_weekly_review(result)
    assert "WEEKLY REVIEW" in text
    assert "Accuracy: 60.0%" in text
    assert "Alerts logged: 3" in text


def test_format_monthly_performance():
    result = {
        "evaluated_predictions": 20,
        "accuracy_pct": 55.0,
        "alerts_count": 12,
        "historical_comparison": None,
    }
    text = format_monthly_performance(result)
    assert "MONTHLY PERFORMANCE" in text
    assert "Accuracy: 55.0%" in text
    assert "Alerts logged: 12" in text


def _alert_rule(**overrides):
    defaults = dict(
        id=1,
        symbol="BTC",
        metric="price",
        operator="above",
        threshold=70000.0,
        cooldown_minutes=60,
        enabled=True,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_format_alert_rule_created():
    text = format_alert_rule_created(_alert_rule())
    assert "Alert rule #1 created" in text
    assert "BTC price above 70000.00" in text


def test_format_alert_rules_empty():
    text = format_alert_rules([])
    assert "no alert rules yet" in text


def test_format_alert_rules_present():
    text = format_alert_rules([_alert_rule(), _alert_rule(id=2, enabled=False)])
    assert "#1: BTC price above 70000.00" in text
    assert "#2: BTC price above 70000.00 (disabled)" in text


def test_format_alert_history_empty():
    text = format_alert_history([])
    assert "No custom alerts" in text


def test_format_alert_history_present():
    history = [
        {
            "symbol": "BTC",
            "metric": "price",
            "value": 71000.0,
            "operator": "above",
            "threshold": 70000.0,
        }
    ]
    text = format_alert_history(history)
    assert "BTC price: 71000.00 above 70000.00" in text


def _shock_envelope(category="price_shock", readings=None, direction="down"):
    return {
        "category": category,
        "direction": direction,
        "readings": readings
        or [{"symbol": "BTC", "window": "15m", "pct_change": -9.5, "current_value": 60000.0}],
        "quality_components": {
            "volume": 80.0,
            "volatility": 70.0,
            "regime_alignment": 100.0,
            "trend_strength": 60.0,
            "consensus_alignment": 70.0,
            "committee_alignment": 70.0,
            "historical_similarity": None,
            "risk_score": 60.0,
            "confidence_score": 60.0,
        },
        "context": {
            "regime": "risk_off",
            "trend_strength_score": 60,
            "risk_score": 60,
            "confidence_score": 60,
            "committee": {"final_recommendation": "SELL (moderate conviction)"},
            "scenarios": [{"name": "Risk Off", "probability_pct": 40}],
        },
    }


def test_format_critical_alert_single_symbol():
    text = format_critical_alert(_shock_envelope(), "high", 82.0)
    assert "MOMENTUM ALERT" in text
    assert "HIGH" in text
    assert "BTC" in text
    assert "-9.50%" in text
    assert "Market Regime: Risk Off" in text
    assert "AI Confidence: 82%" in text
    assert "Committee Verdict: SELL (moderate conviction)" in text
    assert "Recommendation:" in text
    assert "Expected Scenarios:" in text
    assert "Risk Off (40%)" in text


def test_format_critical_alert_multi_asset_includes_related_markets():
    readings = [
        {"symbol": "BTC", "window": "15m", "pct_change": -6.0, "current_value": 60000.0},
        {"symbol": "ETH", "window": "15m", "pct_change": -7.0, "current_value": 2500.0},
        {"symbol": "SOL", "window": "15m", "pct_change": -9.0, "current_value": 100.0},
    ]
    text = format_critical_alert(
        _shock_envelope(category="multi_asset_shock", readings=readings), "critical", 90.0
    )
    assert "MARKET SHOCK" in text
    assert "Related Markets: BTC, ETH, SOL" in text


def test_format_critical_alert_low_quality_omits_reasons():
    envelope = _shock_envelope()
    envelope["quality_components"] = {k: None for k in envelope["quality_components"]}
    text = format_critical_alert(envelope, "important", None)
    assert "Reasons:" not in text


def test_format_active_shocks_empty():
    text = format_active_shocks([])
    assert "No active critical alerts" in text


def test_format_active_shocks_present():
    row = SimpleNamespace(
        tier="critical",
        category="multi_asset_shock",
        symbols=["BTC", "ETH"],
        first_triggered_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    text = format_active_shocks([row])
    assert "CRITICAL" in text
    assert "BTC, ETH" in text


def test_format_technical_none():
    text = format_technical("BTC", None)
    assert "No technical analysis available for BTC" in text


def test_format_technical_never_exposes_raw_indicators():
    result = {
        "source": "local",
        "bullish_score": 62.0,
        "bearish_score": 38.0,
        "trend_strength": 55.0,
        "momentum": 3.2,
        "volatility": 40.0,
        "breakout_probability": 65.0,
        "breakdown_probability": 20.0,
        "confidence": 70.0,
        "support": 60000.0,
        "resistance": 65000.0,
        "timeframes_covered": ["1h", "4h", "1d"],
        "active_signals": ["TechnicalBullish", "RSIOversold"],
        "high_confidence_alignment": None,
    }
    text = format_technical("BTC", result)
    assert "BTC" in text
    assert "Bullish 62" in text
    assert "TechnicalBullish" in text
    for raw_term in ("RSI:", "MACD:", "rsi=", "macd_line"):
        assert raw_term not in text


def test_format_technical_includes_high_confidence_alignment():
    result = {
        "source": "local",
        "bullish_score": 80.0,
        "bearish_score": 20.0,
        "trend_strength": 70.0,
        "momentum": 5.0,
        "volatility": 30.0,
        "breakout_probability": 75.0,
        "breakdown_probability": 10.0,
        "confidence": 85.0,
        "support": 60000.0,
        "resistance": 65000.0,
        "timeframes_covered": ["1d"],
        "active_signals": [],
        "high_confidence_alignment": {
            "signal": "HIGH_CONFIDENCE_BUY",
            "reasons": ["RSI oversold", "MACD bullish crossover"],
        },
    }
    text = format_technical("BTC", result)
    assert "HIGH CONFIDENCE BUY" in text
    assert "RSI oversold" in text


def _scanner_detection():
    return {
        "category": "price_event",
        "symbols": ["BTC"],
        "tier": "high",
        "title": "BTC SURGE",
        "direction": "up",
        "message": "BTC +9.00% (24h)",
        "readings": [
            {
                "symbol": "BTC",
                "price": 65000.123456,
                "change_pct_24h": 9.0,
                "volume_24h": 45_000_000.0,
            }
        ],
        "context": {
            "regime": "risk_on",
            "risk_score": 30,
            "confidence_score": 70,
            "committee_decision": "BUY",
            "committee_majority_pct": 80.0,
        },
    }


def test_format_scanner_alert_includes_mission_required_fields():
    text = format_scanner_alert(_scanner_detection())
    assert "BTC SURGE" in text
    assert "Asset: BTC" in text
    assert "Current Price:" in text
    assert "Price Change:" in text
    assert "Volume Change:" in text
    assert "Market Regime:" in text
    assert "Trend:" in text
    assert "Risk:" in text
    assert "Confidence:" in text
    assert "Committee Opinion: BUY (80.0%)" in text
    assert "Explanation:" in text
    assert "BTC +9.00% (24h)" in text
    assert "Recommendation:" in text


def test_format_scanner_alert_includes_scenario_opportunity_and_threat():
    detection = _scanner_detection()
    detection["context"].update(
        {
            "expected_scenario": "Soft Landing",
            "expected_scenario_pct": 40,
            "biggest_opportunity": "Soft Landing (40%) -- risk-on continuation.",
            "highest_risk": "Risk Off (25%) -- broad de-risking.",
        }
    )
    text = format_scanner_alert(detection)
    assert "Expected Scenario: Soft Landing (40%)" in text
    assert "Main Opportunity: Soft Landing (40%) -- risk-on continuation." in text
    assert "Main Threat: Risk Off (25%) -- broad de-risking." in text


def test_format_scanner_alert_multi_asset_shock_lists_all_symbols():
    detection = {
        "category": "crypto_market_shock",
        "symbols": ["BTC", "ETH", "SOL"],
        "tier": "critical",
        "title": "CRYPTO MARKET SHOCK",
        "direction": "down",
        "message": "3 major assets moved together.",
        "readings": [
            {"symbol": "BTC", "pct_change": -6.0, "window": "24h"},
            {"symbol": "ETH", "pct_change": -7.0, "window": "24h"},
            {"symbol": "SOL", "pct_change": -8.0, "window": "24h"},
        ],
        "context": {},
    }
    text = format_scanner_alert(detection)
    assert "CRYPTO MARKET SHOCK" in text
    assert "BTC: -6.00%" in text
    assert "ETH: -7.00%" in text
    assert "SOL: -8.00%" in text


def test_format_scanner_dashboard_empty():
    assert "No scan data yet" in format_scanner_dashboard({})


def test_format_scanner_dashboard_populated():
    dashboard = {
        "top_movers": {
            "total_scanned": 500,
            "rising_count": 300,
            "falling_count": 200,
            "top_gainers": [{"symbol": "PEPE", "change_pct_24h": 12.0}],
            "top_losers": [{"symbol": "XYZ", "change_pct_24h": -9.0}],
        },
        "sector_leaders": [{"sector": "AI", "avg_change_pct_24h": 6.5, "coin_count": 5}],
        "pending_alerts": [{"id": 1}],
        "suppressed_alerts": [],
    }
    text = format_scanner_dashboard(dashboard)
    assert "Scanned 500 symbols" in text
    assert "PEPE" in text
    assert "XYZ" in text
    assert "AI:" in text
    assert "Pending alerts: 1" in text


def test_format_scanner_dashboard_includes_market_context_from_watchdog():
    dashboard = {
        "top_movers": {
            "total_scanned": 500,
            "rising_count": 300,
            "falling_count": 200,
            "top_gainers": [],
            "top_losers": [],
        },
        "sector_leaders": [],
        "pending_alerts": [],
        "suppressed_alerts": [],
        "market_context": {
            "regime": "risk_off",
            "risk_score": 70,
            "confidence_score": 40,
            "committee_decision": "SELL",
            "committee_majority_pct": 75.0,
            "expected_scenario": "Deeper Correction",
            "expected_scenario_pct": 60,
        },
    }
    text = format_scanner_dashboard(dashboard)
    assert "Market Context" in text
    assert "Risk On" not in text
    assert "Risk: 70/100" in text
    assert "Confidence: 40/100" in text
    assert "Committee: SELL (75.0%)" in text
    assert "Expected Scenario: Deeper Correction (60%)" in text


def test_format_scanner_dashboard_omits_market_context_when_no_snapshot_yet():
    dashboard = {
        "top_movers": None,
        "sector_leaders": [],
        "pending_alerts": [],
        "suppressed_alerts": [],
    }
    text = format_scanner_dashboard(dashboard)
    assert "Market Context" not in text


def test_format_scanner_movers_empty():
    assert "No scan data yet" in format_scanner_movers(None)
    assert "No scan data yet" in format_scanner_movers({"total_scanned": 0})


def test_format_scanner_movers_populated():
    breadth = {
        "total_scanned": 500,
        "rising_count": 300,
        "falling_count": 190,
        "unchanged_count": 10,
        "top_gainers": [{"symbol": "PEPE", "change_pct_24h": 12.0, "price": 0.00001}],
        "top_losers": [{"symbol": "XYZ", "change_pct_24h": -9.0, "price": 1.5}],
    }
    text = format_scanner_movers(breadth)
    assert "TOP MOVERS" in text
    assert "PEPE" in text
    assert "XYZ" in text
    assert "300 rising" in text


def test_format_scanner_sectors_empty():
    assert "No sector data yet" in format_scanner_sectors([])


def test_format_scanner_sectors_populated():
    sectors = [
        {
            "sector": "AI",
            "avg_change_pct_24h": 6.5,
            "coin_count": 5,
            "top_mover": "FET",
            "top_mover_change_pct_24h": 9.0,
        }
    ]
    text = format_scanner_sectors(sectors)
    assert "SECTOR LEADERS" in text
    assert "AI: +6.50% avg, 5 coins (top: FET +9.00%)" in text


def test_format_scanner_detections_empty():
    assert "No detections logged yet" in format_scanner_detections([])


def test_format_scanner_detections_populated():
    detections = [
        {
            "last_updated_at": "2026-01-01T00:05:00+00:00",
            "tier": "high",
            "symbols": ["BTC"],
            "active": True,
            "message": "BTC +9.00% (24h)",
        }
    ]
    text = format_scanner_detections(detections)
    assert "LATEST DETECTIONS" in text
    assert "[HIGH]" in text
    assert "BTC" in text
    assert "active" in text
    assert "BTC +9.00% (24h)" in text
