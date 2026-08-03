from app.database.models import (
    AssetClass,
    AssetPrice,
    BreakoutEvent,
    Correlation,
    GlobalMarketScore,
    HistoricalEvent,
    MarketRegimeSnapshot,
    NewsItem,
    PatternSignal,
    ProbabilitySnapshot,
    Report,
    ScenarioSnapshot,
    SentimentSnapshot,
    SignalSnapshot,
)
from app.services.common.ai_insight import format_ai_insight_lines
from app.services.common.navigation import nav_pointer
from app.services.consensus.engine import ConsensusResult
from app.services.shocks.detectors import regime_direction_bucket

_CLASS_LABELS: dict[AssetClass, str] = {
    AssetClass.CRYPTO: "Crypto",
    AssetClass.INDEX: "Indices",
    AssetClass.STOCK: "Stocks",
    AssetClass.MACRO: "Macro",
}

_CLASS_ORDER: tuple[AssetClass, ...] = (
    AssetClass.CRYPTO,
    AssetClass.INDEX,
    AssetClass.STOCK,
    AssetClass.MACRO,
)


def _price_line(asset: AssetPrice) -> str:
    change = f"{asset.change_pct_24h:+.2f}%" if asset.change_pct_24h is not None else "n/a"
    return f"{asset.symbol}: {float(asset.price):,.2f} ({change} 24h)"


def format_market_summary(assets: list[AssetPrice]) -> str:
    if not assets:
        return "No market data collected yet -- check back shortly."

    by_class: dict[AssetClass, list[AssetPrice]] = {}
    for asset in assets:
        by_class.setdefault(asset.asset_class, []).append(asset)

    lines = ["*MARKET SUMMARY*", ""]
    for asset_class in _CLASS_ORDER:
        items = by_class.get(asset_class)
        if not items:
            continue
        lines.append(f"*{_CLASS_LABELS[asset_class]}*")
        lines.extend(_price_line(a) for a in sorted(items, key=lambda a: a.symbol))
        lines.append("")
    return "\n".join(lines).strip()


def format_asset_class(assets: list[AssetPrice], asset_class: AssetClass, title: str) -> str:
    items = [a for a in assets if a.asset_class == asset_class]
    if not items:
        return f"No {title.lower()} data collected yet -- check back shortly."
    lines = [f"*{title}*", ""]
    lines.extend(_price_line(a) for a in sorted(items, key=lambda a: a.symbol))
    return "\n".join(lines)


def format_single_asset(symbol: str, asset: AssetPrice | None) -> str:
    if asset is None:
        return f"No data available yet for {symbol.upper()}."

    change = f"{asset.change_pct_24h:+.2f}%" if asset.change_pct_24h is not None else "n/a"
    lines = [
        f"*{asset.name} ({asset.symbol})*",
        f"Price: {float(asset.price):,.2f}",
        f"24h change: {change}",
    ]
    if asset.market_cap is not None:
        lines.append(f"Market cap: {float(asset.market_cap):,.0f}")
    if asset.volume_24h is not None:
        lines.append(f"24h volume: {float(asset.volume_24h):,.0f}")
    return "\n".join(lines)


def format_news(items: list[NewsItem], limit: int = 8) -> str:
    if not items:
        return "No news collected yet -- check back shortly."
    lines = ["*LATEST NEWS*", ""]
    for item in items[:limit]:
        lines.append(f"[{item.category.value}] ({item.sentiment.value}) {item.title}")
        lines.append(item.url)
        lines.append("")
    return "\n".join(lines).strip()


def format_signal(snapshot: SignalSnapshot | None) -> str:
    if snapshot is None:
        return "No signal has been computed yet -- check back shortly."
    lines = [
        "*BULL/BEAR SIGNAL*",
        "",
        f"Bull score: {snapshot.bull_score}",
        f"Bear score: {snapshot.bear_score}",
        f"Net score: {snapshot.net_score}",
        f"Confidence: {snapshot.confidence_pct}%",
        "",
        "*Factors*",
    ]
    for name, data in snapshot.factors.items():
        if data["triggered"] is True:
            state = "triggered"
        elif data["triggered"] is False:
            state = "not triggered"
        else:
            state = "no data"
        label = name.replace("_", " ").capitalize()
        lines.append(f"- {label} ({data['points']:+d}): {state}")
    return "\n".join(lines)


def format_regime(snapshot: MarketRegimeSnapshot | None) -> str:
    if snapshot is None:
        return "No regime has been detected yet -- check back shortly."
    return f"*MARKET REGIME*\n\n{snapshot.regime.value.replace('_', ' ').title()}"


def format_correlations(correlations: list[Correlation]) -> str:
    if not correlations:
        return "No correlation data available yet -- check back shortly."
    lines = ["*CORRELATIONS*", ""]
    for c in correlations:
        lines.append(f"{c.symbol_a}/{c.symbol_b} ({c.window_days}d): {float(c.correlation):+.2f}")
    return "\n".join(lines)


def format_report(report: Report | None, institutional_report: dict | None = None) -> str:
    """v8.0: renders the institutional-research structure (Executive
    Summary, Biggest Opportunity, Biggest Risk, Market Drivers, Sector
    Rotation, Historical Comparison, AI Conclusion, What to Watch Next) when
    `institutional_report` (from build_institutional_report()) is supplied,
    falling back to the underlying analysis fields directly if not."""
    if report is None:
        return (
            "No AI report has been generated yet. Generate one with /report once market "
            "data, regime detection and signals have run at least once."
        )

    analysis = report.analysis
    ir = institutional_report or {}
    lines = [
        "*AI MARKET ANALYSIS*",
        "",
        f"Market Regime: {report.regime.replace('_', ' ').title()}",
        f"Risk Level: {report.risk_level.title()}",
        f"Bull Score: {report.bull_score} | Bear Score: {report.bear_score}",
        f"Confidence: {report.confidence_pct}%",
        "",
        "*Executive Summary*",
        ir.get("executive_summary") or analysis.get("what_changed", "n/a"),
        "",
        "*Main Opportunity*",
        ir.get("biggest_opportunity", "n/a"),
        "",
        "*Main Risk*",
        ir.get("biggest_risk", "n/a"),
    ]
    if ir.get("risk_detail"):
        lines.append(f"Risk Detail: {ir['risk_detail']}")
    if ir.get("watchdog_note"):
        lines.append(ir["watchdog_note"])
    if analysis.get("main_risks"):
        lines.append(f"Also: {analysis['main_risks']}")
    lines.extend(
        [
            "",
            "*Market Drivers*",
            ir.get("market_drivers") or analysis.get("who_is_driving", "n/a"),
            "",
            "*Institutional Interpretation*",
            analysis.get("institutional_behavior", "n/a"),
            "",
            "*Sector Rotation*",
            ir.get("sector_rotation", "n/a"),
            "",
            "*Historical Comparison*",
            analysis.get("historical_comparison", "n/a"),
            "",
            "*AI Conclusion*",
            ir.get("ai_conclusion") or analysis.get("actionable_insights", "n/a"),
            "",
            "*What To Watch Next*",
            ir.get("what_to_watch_next") or analysis.get("key_events_today", "n/a"),
            "",
            "*Today's Probability*",
            (
                f"Bullish {analysis.get('probability_bullish_pct', 0)}% | "
                f"Bearish {analysis.get('probability_bearish_pct', 0)}% | "
                f"Neutral {analysis.get('probability_neutral_pct', 0)}%"
            ),
            "",
            f"_Generated at {report.generated_at.isoformat()}_",
        ]
    )
    return "\n".join(lines)


def format_history(symbol: str, timeframe: str, rows: list, limit: int = 10) -> str:
    if not rows:
        return f"No {symbol} history synced yet for {timeframe} -- run sync_history.py."
    lines = [f"*{symbol} history ({timeframe})*", ""]
    for row in rows[-limit:]:
        rsi = f"{float(row.rsi):.1f}" if row.rsi is not None else "n/a"
        change = f"{float(row.return_pct) * 100:+.2f}%" if row.return_pct is not None else "n/a"
        date_str = row.timestamp.date().isoformat()
        lines.append(f"{date_str}: {float(row.close):,.2f} ({change}) RSI {rsi}")
    return "\n".join(lines)


def format_events(events: list[HistoricalEvent]) -> str:
    if not events:
        return "No historical events seeded yet -- run sync_history.py --seed-events."
    lines = ["*HISTORICAL EVENTS*", ""]
    for event in events:
        symbols = ", ".join(event.symbols_affected) if event.symbols_affected else "n/a"
        lines.append(f"{event.event_date.date().isoformat()} -- {event.title} ({symbols})")
    return "\n".join(lines)


def format_learning(result: dict | None, symbol: str, timeframe: str) -> str:
    if result is None:
        return (
            f"No graded predictions yet for {symbol}/{timeframe} -- a prediction only "
            "counts once its horizon has actually elapsed in the stored history."
        )
    lines = [
        f"*{result['symbol']} SELF-LEARNING ACCURACY* ({result['timeframe']})",
        "",
        f"Evaluated predictions: {result['evaluated_predictions']}",
        f"Accuracy: {result['accuracy_pct']}%",
        "",
        "*Recent*",
    ]
    for entry in result["recent"]:
        mark = "correct" if entry["correct"] else "wrong"
        lines.append(
            f"{entry['reference_timestamp'].date().isoformat()}: predicted "
            f"{entry['predicted']}, realized {entry['realized']} "
            f"({entry['realized_return_pct']:+.2f}%) -- {mark}"
        )
    return "\n".join(lines)


def format_quality(result: dict | None, symbol: str, timeframe: str) -> str:
    if result is None:
        return (
            f"No graded predictions yet for {symbol}/{timeframe} -- a prediction only "
            "counts once its horizon has actually elapsed in the stored history."
        )
    pr = result["precision_recall"]
    lines = [
        f"*{result['symbol']} PREDICTION QUALITY LAB* ({result['timeframe']})",
        "",
        f"Evaluated predictions: {result['evaluated_predictions']}",
        f"Accuracy: {result['accuracy_pct']}%",
        f"Brier score: {result['brier_score']}",
        f"Average calibration error: {result['average_error_pct']}%",
        "",
        "*Precision / Recall*",
        f"Macro precision: {pr['macro_precision_pct']}% | Macro recall: {pr['macro_recall_pct']}%",
    ]
    for direction, stats in pr["per_class"].items():
        lines.append(
            f"- {direction}: precision {stats['precision_pct']}%, recall {stats['recall_pct']}% "
            f"(support {stats['support']})"
        )
    if result["calibration"]:
        lines.append("")
        lines.append("*Calibration*")
        for bucket in result["calibration"]:
            lines.append(
                f"- {bucket['confidence_bucket']} (n={bucket['count']}): predicted "
                f"{bucket['avg_predicted_confidence_pct']}%, observed "
                f"{bucket['observed_accuracy_pct']}%"
            )
    if result["time_horizon_accuracy"]:
        lines.append("")
        lines.append("*Accuracy by Horizon*")
        for row in result["time_horizon_accuracy"]:
            lines.append(
                f"- {row['horizon_periods']} period(s) (n={row['count']}): {row['accuracy_pct']}%"
            )
    return "\n".join(lines)


def format_probability(snapshot: ProbabilitySnapshot | None) -> str:
    if snapshot is None:
        return "Not enough synced history to compute a probability yet."
    header = (
        f"*{snapshot.symbol} PROBABILITY* ({snapshot.timeframe}, {snapshot.horizon_periods}-period)"
    )
    up_down_flat = (
        f"Up: {snapshot.prob_up_pct}% | "
        f"Down: {snapshot.prob_down_pct}% | "
        f"Flat: {snapshot.prob_flat_pct}%"
    )
    lines = [
        header,
        "",
        f"Reference RSI: {float(snapshot.reference_rsi):.1f}",
        f"Sample size: {snapshot.sample_size} similar historical episodes",
        up_down_flat,
        f"Avg forward return: {float(snapshot.avg_forward_return_pct):+.2f}%",
    ]
    return "\n".join(lines)


def format_patterns(symbol: str, patterns: list[PatternSignal]) -> str:
    if not patterns:
        return f"No patterns detected yet for {symbol}."
    lines = [f"*{symbol} PATTERNS*", ""]
    for pattern in patterns:
        date_str = pattern.timestamp.date().isoformat()
        lines.append(f"{date_str}: {pattern.pattern_name} ({pattern.direction.value})")
    return "\n".join(lines)


def format_breakout(symbol: str, event: BreakoutEvent | None) -> str:
    if event is None:
        return f"No breakout/breakdown detected yet for {symbol}."
    lines = [
        f"*{symbol} BREAKOUT INTELLIGENCE* ({event.timeframe})",
        "",
        (
            f"{event.event_type.replace('_', ' ').title()} ({event.direction}) at level "
            f"{float(event.level):.4f}, price {float(event.price):.4f}"
        ),
        (
            f"Probability: {event.probability_pct}%"
            if event.probability_pct is not None
            else "Probability: unavailable"
        )
        + f" | Confidence: {event.confidence_pct}%",
    ]
    if event.risk_score is not None:
        lines.append(f"Risk score: {event.risk_score}/100")
    lines.append(f"Expected: {event.expected_continuation}")
    lines.append("")
    lines.append(event.reasoning)
    return "\n".join(lines)


def format_knowledge(symbol: str, matches: list[dict]) -> str:
    """v12.0 P2 -- matches are now SimilarMarketEngine's own match shape
    (with `nearby_events` attached via `include_nearby_events=True`), not a
    separately-computed KnowledgeEngine analog list; the two engines ran
    the identical RSI/volatility search independently, so this now reuses
    the one search SimilarMarketEngine already runs."""
    if not matches:
        return f"No similar historical episodes found yet for {symbol}."
    lines = [f"*{symbol} HISTORICAL SIMILARITY*", ""]
    for match in matches:
        date_str = match["date"].date().isoformat()
        forward = match["forward_returns_pct"].get("7d")
        forward_str = f"{forward:+.2f}%" if forward is not None else "n/a"
        line = f"{date_str} (RSI {match['rsi']:.1f}): next move {forward_str}"
        nearby = match.get("nearby_events") or []
        if nearby:
            titles = ", ".join(e["title"] for e in nearby)
            line += f" -- {titles}"
        lines.append(line)
    return "\n".join(lines)


def format_global_score(row: GlobalMarketScore | None) -> str:
    if row is None:
        return "Not enough data yet -- regime detection and signal scoring need to run first."
    lines = [
        "*GLOBAL MARKET SCORE*",
        "",
        f"Global score: {row.global_score}/100",
        f"Risk-On {row.risk_on_score} / Risk-Off {row.risk_off_score}",
        f"Liquidity: {row.liquidity_score}",
        f"Fear {row.fear_score} / Greed {row.greed_score}",
        f"Macro pressure: {row.macro_pressure_score}",
        f"Institutional activity: {row.institutional_activity_score}",
        f"Crypto strength: {row.crypto_strength_score}",
        f"Stock strength: {row.stock_strength_score}",
        (
            f"Trend strength: {row.trend_strength_score}"
            if row.trend_strength_score is not None
            else "Trend strength: unavailable"
        ),
        f"Risk score: {row.risk_score}"
        if row.risk_score is not None
        else "Risk score: unavailable",
        (
            f"Confidence score: {row.confidence_score}"
            if row.confidence_score is not None
            else "Confidence score: unavailable"
        ),
    ]
    return "\n".join(lines)


def format_similar_periods(
    symbol: str, matches: list[dict], lesson: dict | None = None, limit: int = 5
) -> str:
    if not matches:
        return f"Not enough synced history for {symbol} to find similar periods yet."
    lines = [f"*{symbol} HISTORICAL SIMILARITY*", ""]
    if lesson is not None:
        lines.extend(
            [
                f"What happened: {lesson['what_happened']}",
                f"How similar: {lesson['how_similar_pct']}% avg match",
                f"Average outcome ({lesson['horizon_days']}d): "
                f"{lesson['average_outcome_pct']:+.2f}%",
                f"Probability: {lesson['probability_pct']}% moved the same direction",
                f"Typical duration: {lesson['typical_duration']}",
                f"Lesson: {lesson['main_lesson']}",
                "",
            ]
        )
    for m in matches[:limit]:
        date_str = m["date"].date().isoformat()
        regime = m["market_regime"] or "unknown"
        forward_1d = m["forward_returns_pct"]["1d"]
        forward_30d = m["forward_returns_pct"]["30d"]
        f1 = f"{forward_1d:+.2f}%" if forward_1d is not None else "n/a"
        f30 = f"{forward_30d:+.2f}%" if forward_30d is not None else "n/a"
        lines.append(
            f"{date_str} (similarity {m['similarity']}, regime {regime}): 1d {f1} | 30d {f30}"
        )
    return "\n".join(lines)


def format_etf_proxy(data: dict) -> str:
    if not data.get("available"):
        return f"ETF flow proxy unavailable: {data.get('reason', 'no data')}"
    return "\n".join(
        [
            "*ETF FLOW PROXY* (news-sentiment based, not confirmed dollar flows)",
            "",
            f"Classification: {data['classification']}",
            (
                f"{data['bullish_items']} bullish / {data['bearish_items']} bearish / "
                f"{data['neutral_items']} neutral items ({data['window_hours']}h window)"
            ),
        ]
    )


def format_whale_snapshot(data: dict) -> str:
    if not data.get("available"):
        return f"Whale Intelligence unavailable: {data.get('reason', 'no data')}"
    lines = ["*WHALE ACTIVITY*", ""]
    lines.extend(f"{k}: {v}" for k, v in data.items() if k not in ("available", "symbol"))
    return "\n".join(lines)


def format_onchain(snapshot: dict) -> str:
    lines = [f"*{snapshot['symbol']} ON-CHAIN INTELLIGENCE*", "", snapshot["reason"]]
    if snapshot.get("solana_note"):
        lines.append("")
        lines.append(snapshot["solana_note"])
    lines.append("")
    lines.append("Tracked metrics (all unavailable): " + ", ".join(snapshot["metrics"]))
    return "\n".join(lines)


def format_agent_outputs(outputs: dict) -> str:
    return "\n\n".join(output.summary for output in outputs.values())


def format_consensus(
    result: ConsensusResult | None, confidence_evolution: dict | None = None
) -> str:
    if result is None:
        return "No agent reported a direction this cycle -- nothing to tally yet."
    lines = [
        "*CONSENSUS*",
        "",
        f"Bullish {result.bullish_pct}% | Bearish {result.bearish_pct}% | "
        f"Neutral {result.neutral_pct}%",
        f"Agreement: {result.agreement_score}% | Conflict: {result.conflict_pct}%",
    ]
    if result.strongest_agent:
        lines.append(
            f"Strongest influence: {result.strongest_agent} "
            f"({result.agent_weights[result.strongest_agent]}% of vote weight)"
        )
    if confidence_evolution is not None:
        lines.append(f"Confidence evolution: {confidence_evolution['summary']}")
    lines.append("")

    def _bucket_lines(label: str, agents: list[str]) -> list[str]:
        if not agents:
            return []
        out = [f"{label}:"]
        for a in agents:
            evidence = result.agent_evidence.get(a)
            out.append(f"- {a}: {evidence}" if evidence else f"- {a}")
        return out

    lines.extend(_bucket_lines("Bullish", result.bullish_agents))
    lines.extend(_bucket_lines("Bearish", result.bearish_agents))
    if result.neutral_agents:
        lines.append(f"Neutral: {', '.join(result.neutral_agents)}")
    if result.unavailable_agents:
        lines.append(f"No data this cycle: {', '.join(result.unavailable_agents)}")
    if result.invalidation_risk:
        lines.append("")
        lines.append(f"Invalidation risk: {result.invalidation_risk}")
    lines.append("")
    lines.append(nav_pointer("consensus"))
    return "\n".join(lines)


def _committee_evidence_line(e: dict) -> str:
    parts = []
    if e.get("confidence") is not None:
        parts.append(f"{e['confidence']}% confidence")
    if e.get("weight") is not None:
        parts.append(f"{e['weight']}% vote weight")
    prefix = f" ({', '.join(parts)})" if parts else ""
    return f"- {e['agent']}{prefix}: {e['evidence']}"


def format_committee(verdict: dict | None) -> str:
    if verdict is None:
        return "No agent reported a direction this cycle -- the committee has nothing to vote on."
    lines = [
        "*AI INVESTMENT COMMITTEE*",
        "",
        f"Final recommendation: {verdict['final_recommendation']}",
        (
            f"Majority: {verdict['majority_decision']} ({verdict['majority_pct']}%) | "
            f"Dissent: {verdict['dissent_pct']}% | Confidence: {verdict['confidence_pct']}%"
        ),
        "",
        verdict["reasoning"],
    ]
    if verdict["supporting_evidence"]:
        lines.append("")
        lines.append("Supporting evidence:")
        lines.extend(_committee_evidence_line(e) for e in verdict["supporting_evidence"])
    if verdict["opposing_evidence"]:
        lines.append("")
        lines.append("Opposing evidence (minority):")
        lines.extend(_committee_evidence_line(e) for e in verdict["opposing_evidence"])
    if verdict.get("most_influential_agent"):
        lines.append("")
        lines.append(f"Final influence: {verdict['most_influential_agent']}")
    if verdict.get("invalidation_risk"):
        lines.append("")
        lines.append(f"Invalidation risk: {verdict['invalidation_risk']}")
    lines.append("")
    lines.append(nav_pointer("committee"))
    return "\n".join(lines)


def format_scenarios(row: ScenarioSnapshot | None) -> str:
    if row is None:
        return "Not enough data yet -- regime detection and signal scoring need to run first."
    lines = ["*SCENARIOS*", ""]
    for scenario in sorted(row.scenarios, key=lambda s: s["probability_pct"], reverse=True):
        lines.append(f"*{scenario['name']}* -- {scenario['probability_pct']}%")
        lines.append(scenario["rationale"])
        lines.append("")
    return "\n".join(lines).strip()


def format_whatif(result: dict | None) -> str:
    if result is None:
        return "Unknown scenario. Use /whatif with no arguments to list available scenarios."
    lines = [
        f"*WHAT IF: {result['scenario_label'].upper()}*",
        "",
        result["description"],
        f"Data source: {result['data_source'].replace('_', ' ')}",
        "",
    ]
    for symbol, data in result["impact"].items():
        if "expected_return_7d_pct" in data:
            value = data["expected_return_7d_pct"]
            value_str = f"{value:+.2f}% (7d)" if value is not None else "no data"
            sample = data.get("sample_size")
            suffix = f" [{sample} historical occurrences]" if sample else ""
            lines.append(f"{symbol}: {value_str}{suffix}")
        elif "direction" in data:
            direction = data["direction"] or "unclear"
            corr = data.get("correlation_30d")
            corr_str = f" (correlation {corr})" if corr is not None else ""
            lines.append(f"{symbol}: {direction}{corr_str}")
    lines.append("")
    lines.append(
        f"Regime: {result['current_regime'] or 'unknown'} -> likely shift toward "
        f"{result['likely_regime_shift_toward'].replace('_', ' ')}"
    )
    lines.append(f"Risk: {result['risk_direction']} | Liquidity: {result['liquidity_direction']}")
    lines.append("")
    lines.append(result["reasoning"])
    return "\n".join(lines)


def format_sentiment(row: SentimentSnapshot) -> str:
    lines = ["*SENTIMENT*", ""]
    if row.fear_greed_value is not None:
        lines.append(
            f"Fear & Greed Index: {row.fear_greed_value}/100 ({row.fear_greed_classification})"
        )
    else:
        lines.append("Fear & Greed Index: unavailable this cycle.")
    if row.news_sentiment_score is not None:
        lines.append(f"News sentiment: {row.news_sentiment_score}/100")
    lines.append(f"Social/options sentiment: {row.social_sentiment_reason}")
    if row.global_sentiment_score is not None:
        lines.append("")
        lines.append(f"Global Sentiment Score: {row.global_sentiment_score}/100")
    return "\n".join(lines)


def format_conviction(data: dict) -> str:
    lines = ["*CONVICTION*", ""]
    signal = data.get("signal")
    if signal is None:
        lines.append("Signal: not yet computed.")
    else:
        lines.append(
            f"Signal: {signal['tier']} ({signal['effective_confidence_pct']}% effective confidence)"
        )
    probability = data.get("probability")
    if probability is None:
        lines.append("Probability: not yet computed.")
    else:
        lines.append(
            f"{probability['symbol']} probability: {probability['tier']} "
            f"({probability['effective_confidence_pct']}% effective confidence, "
            f"sample size {probability['sample_size']})"
        )
    return "\n".join(lines)


def format_liquidity(data: dict) -> str:
    return "\n".join(
        [
            "*LIQUIDITY*",
            "",
            f"Liquidity: {data['liquidity_score']}/100",
            f"Macro pressure: {data['macro_pressure_score']}/100",
            f"Risk-On {data['risk_on_score']} / Risk-Off {data['risk_off_score']}",
        ]
    )


def format_portfolio(health: dict) -> str:
    if health.get("empty"):
        return "Portfolio is empty. Add a position via POST /api/portfolio/positions."
    lines = [
        "*PORTFOLIO*",
        "",
        f"Total value: {health['total_value']:,.2f}",
        f"Health score: {health['health_score']}/100"
        if health["health_score"] is not None
        else "Health score: unavailable",
        "",
        "*Positions*",
    ]
    for p in health["positions"]:
        if not p.get("priced"):
            lines.append(f"- {p['symbol']}: {p['quantity']} (no live price)")
            continue
        pnl = f" ({p['unrealized_pnl_pct']:+.2f}%)" if p["unrealized_pnl_pct"] is not None else ""
        lines.append(
            f"- {p['symbol']}: {p['quantity']} @ {p['price']:,.2f} = {p['value']:,.2f}{pnl}"
        )
    lines.append("")
    lines.append("*Exposure*")
    for asset_class, pct in health["exposure_pct_by_class"].items():
        lines.append(f"- {asset_class}: {pct}%")
    if health.get("max_drawdown_pct") is not None:
        lines.append(f"\nMax drawdown: {health['max_drawdown_pct']}%")
    else:
        lines.append(f"\n{health.get('drawdown_note', 'Drawdown unavailable.')}")
    return "\n".join(lines)


def format_explanation(data: dict) -> str:
    lines = [f"*WHY -- {data['symbol']}*", ""]

    if data["indicators"]:
        lines.append("*Triggered indicators*")
        for ind in data["indicators"]:
            lines.append(f"- {ind['name'].replace('_', ' ')} ({ind['points']:+d})")
        lines.append("")

    if data["macro_drivers"]:
        lines.append("*Macro drivers*")
        for name, value in data["macro_drivers"].items():
            lines.append(f"- {name.replace('_', ' ')}: {value}")
        lines.append("")

    if data["supporting_news"]:
        lines.append("*Supporting news*")
        for item in data["supporting_news"]:
            lines.append(f"- [{item['sentiment']}] {item['title']}")
        lines.append("")

    if data["historical_examples"]:
        lines.append("*Historical Similarity*")
        for ex in data["historical_examples"]:
            forward = (
                f"{ex['forward_return_7d_pct']:+.2f}%"
                if ex["forward_return_7d_pct"] is not None
                else "n/a"
            )
            lines.append(
                f"- {ex['match_timestamp'][:10]} ({ex['similarity_score']:.0f}% similar, "
                f"{ex['regime'] or 'regime unknown'}): 7d forward {forward}"
            )
        lines.append("")

    if data["risk_factors"]:
        rf = data["risk_factors"]
        lines.append("*Risk factors*")
        lines.append(
            f"Fear {rf['fear_score']} | Macro pressure {rf['macro_pressure_score']} | "
            f"Risk-off {rf['risk_off_score']}"
        )
        if rf.get("risk_score") is not None or rf.get("confidence_score") is not None:
            lines.append(
                f"Risk score {rf.get('risk_score', 'n/a')} | "
                f"Confidence {rf.get('confidence_score', 'n/a')}"
            )
        lines.append("")

    if data["alternative_view"]:
        av = data["alternative_view"]
        lines.append("*Alternative view*")
        lines.append(f"{av['name']} ({av['probability_pct']}%): {av['rationale']}")

    if len(lines) <= 2:
        lines.append("Not enough data computed yet to explain this read.")

    return "\n".join(lines).strip()


def format_status(snapshots: dict) -> str:
    lines = ["*SYSTEM STATUS*", ""]
    for label, timestamp in snapshots.items():
        value = timestamp.isoformat() if timestamp is not None else "never computed"
        lines.append(f"{label}: {value}")
    return "\n".join(lines)


def format_risk(data: dict) -> str:
    lines = ["*RISK*", ""]
    if data["global_score"] is not None:
        gs = data["global_score"]
        lines.append(f"Risk-off: {gs['risk_off_score']}/100 | Risk-on: {gs['risk_on_score']}/100")
        lines.append(
            f"Fear: {gs['fear_score']}/100 | Macro pressure: {gs['macro_pressure_score']}/100"
        )
        if gs.get("risk_score") is not None or gs.get("confidence_score") is not None:
            lines.append(
                f"Risk score: {gs.get('risk_score', 'n/a')}/100 | "
                f"Confidence: {gs.get('confidence_score', 'n/a')}/100"
            )
    else:
        lines.append("Global Score not computed yet -- run /score first.")
    lines.append("")
    if data["signal_conviction"] is not None:
        sc = data["signal_conviction"]
        lines.append(f"Signal conviction: {sc['tier']} ({sc['effective_confidence_pct']}%)")
    else:
        lines.append("Signal conviction: unavailable -- no signal computed yet.")
    return "\n".join(lines)


def format_watchdog(entries: list[dict]) -> str:
    if not entries:
        return "*MARKET WATCHDOG*\n\nNo detections logged yet."
    lines = ["*MARKET WATCHDOG*", ""]
    for entry in entries:
        s = entry["summary"]
        state = "sent" if s["broadcast"] else "suppressed (gated/cooldown)"
        confidence = s.get("confidence_pct")
        confidence_str = f" ({confidence}% AI confidence)" if confidence is not None else ""
        lines.append(
            f"{entry['timestamp'][:16]} [{s['alert_type']}] {s['conviction_tier']} -- "
            f"{state}{confidence_str}"
        )
        lines.append(s["message"])
        lines.append("")
    return "\n".join(lines).strip()


def _fmt_pct(value: float | None) -> str:
    return f"{value:+.2f}%" if value is not None else "n/a"


def _fmt_num(value, digits: int = 0) -> str:
    return f"{value:.{digits}f}" if value is not None else "n/a"


def format_watchdog_current_status(status: dict) -> str:
    lines = [
        "*CURRENT MARKET STATUS*",
        "",
        f"Time: {status['current_time'][:16].replace('T', ' ')}",
        f"Last Update: {(status['last_update'] or 'never')[:16].replace('T', ' ')}",
        f"Next Scan: {(status.get('next_scan') or 'unknown')[:16].replace('T', ' ')}",
        f"Scan Duration: {_fmt_num(status['scan_duration_ms'], 0)}ms",
        f"Market Health: {status['market_health']}",
        f"Brain: {status['brain_status']} | Replay: {status['replay_status']} | "
        f"Committee: {status['committee_status']} | Consensus: {status['consensus_status']}",
    ]
    return "\n".join(lines)


def format_watchdog_market(
    market_overview: dict, crypto_overview: list[dict], macro_overview: list[dict]
) -> str:
    lines = ["*MARKET OVERVIEW*", ""]
    m = market_overview
    regime_label = (m["regime"] or "unknown").replace("_", " ").title()
    # v9.0 noise pass: "Trend" is a pure 3-bucket derivation of "Regime"
    # (regime_direction_bucket()) -- merged into one line as a parenthetical
    # instead of a separate fact, matching format_scanner_dashboard's
    # existing "Regime: X (bucket)" pattern.
    trend_suffix = f" ({m['trend']})" if m["trend"] else ""
    lines.append(f"Regime: {regime_label}{trend_suffix}")
    lines.append(
        f"Trend Strength: {_fmt_num(m['trend_strength'])} | "
        f"Momentum: {_fmt_num(m['momentum'], 1)} | Volatility: {_fmt_num(m['volatility'])}"
    )
    market_score = _fmt_num(m["market_intelligence_score"])
    lines.append(
        f"Confidence: {_fmt_num(m['confidence'])} | Risk: {_fmt_num(m['risk_score'])} | "
        f"Liquidity: {_fmt_num(m['liquidity_score'])} | Market Score: {market_score}"
    )

    lines.append("")
    lines.append("*Crypto Overview*")
    for row in crypto_overview:
        if not row.get("available"):
            lines.append(f"{row['symbol']}: unavailable")
            continue
        lines.append(
            f"{row['symbol']} {row['price']:,.2f} ({_fmt_pct(row['change_pct_24h'])} 24h / "
            f"{_fmt_pct(row['change_pct_1h'])} 1h) {row['ai_bias'] or ''}".rstrip()
        )

    lines.append("")
    lines.append("*Macro Overview*")
    for row in macro_overview:
        if not row.get("available"):
            lines.append(f"{row['name']}: unavailable")
            continue
        impact = f" -- {row['impact_on_crypto']} for crypto" if row["impact_on_crypto"] else ""
        lines.append(f"{row['name']} {row['price']:,.2f} ({_fmt_pct(row['daily_pct'])}){impact}")

    return "\n".join(lines)


def format_watchdog_onchain(onchain: dict) -> str:
    lines = ["*ON-CHAIN OVERVIEW*", ""]
    if not onchain.get("available"):
        lines.append("Unavailable" + (f" -- {onchain['reason']}" if onchain.get("reason") else ""))
        return "\n".join(lines)
    whales = onchain["whales"]
    lines.append(f"Whale positioning: {whales.get('classification', 'unknown')}")
    if onchain.get("funding") is not None:
        lines.append(f"Funding rate: {onchain['funding']}")
    if onchain.get("open_interest") is not None:
        lines.append(f"Open interest: {onchain['open_interest']}")
    lines.append("Exchange flows / stablecoin flow / TVL: unavailable (no on-chain provider wired)")
    return "\n".join(lines)


def format_watchdog_ai(ai_status: dict) -> str:
    if ai_status.get("computed_at") is None:
        return "*AI STATUS*\n\nNo Watchdog cycle has run yet -- check back shortly."
    lines = [
        "*AI STATUS*",
        "",
        f"Committee Opinion: {ai_status['committee_opinion'] or 'n/a'}",
    ]
    consensus = ai_status.get("consensus")
    if consensus:
        lines.append(
            f"Consensus: bullish {consensus['bullish_pct']}% / bearish {consensus['bearish_pct']}% "
            f"/ neutral {consensus['neutral_pct']}%"
        )
    lines.append(f"Confidence: {_fmt_num(ai_status['prediction_confidence'])}%")
    if ai_status.get("expected_scenario"):
        lines.append(
            f"Expected Scenario: {ai_status['expected_scenario']} "
            f"({ai_status['expected_scenario_pct']}%)"
        )
    if ai_status.get("highest_risk"):
        lines.append(f"Main Risk: {ai_status['highest_risk']}")
    if ai_status.get("biggest_opportunity"):
        lines.append(f"Main Opportunity: {ai_status['biggest_opportunity']}")
    return "\n".join(lines)


def format_watchdog_changes(changes: dict) -> str:
    if not changes.get("available"):
        return (
            "*WHAT CHANGED*\n\nNot enough Watchdog history yet -- check back after the next cycle."
        )
    lines = ["*WHAT CHANGED*", ""]
    if not changes["fields"] and not changes["events"]:
        lines.append("No significant changes since the last cycle.")
        return "\n".join(lines)
    for field in changes["fields"]:
        lines.append(f"{field['label']}: {field['prev']} -> {field['curr']}")
    if changes["events"]:
        lines.append("")
        for event in changes["events"]:
            lines.append(f"- {event['message']}")
    return "\n".join(lines)


def format_watchdog_brief(brief: dict) -> str:
    """v8.0 "Market Control Center" -- direct verdicts composed from the
    same data /watchdog ai and /watchdog changes already show, so a reader
    doesn't have to cross-reference sections themselves."""
    health_word = {True: "Yes", False: "No", None: "Mixed"}[brief["is_market_healthy"]]
    lines = [
        "*MARKET CONTROL CENTER*",
        "",
        f"Is the market healthy? {health_word} ({brief['market_health_label']})",
        f"Is risk increasing? {brief['risk_direction'].capitalize()} -- {brief['risk_reason']}",
        f"Did AI change its opinion? {'Yes' if brief['ai_opinion_changed'] else 'No'} -- "
        f"{brief['ai_opinion_reason']}",
    ]
    lines.append("")
    lines.append("Today's biggest changes:")
    if brief["biggest_changes_today"]:
        lines.extend(f"- {m}" for m in brief["biggest_changes_today"])
    else:
        lines.append("- None since the last cycle.")
    lines.append("")
    lines.append("Needs attention now:")
    lines.extend(f"- {m}" for m in brief["needs_attention"])
    return "\n".join(lines)


def format_watchdog_providers(providers: list[dict]) -> str:
    lines = ["*PROVIDER STATUS*", ""]
    for p in providers:
        if not p["configured"]:
            reason = f" -- {p['reason']}" if p.get("reason") else ""
            lines.append(f"{p['name']}: not configured{reason}")
            continue
        state = "healthy" if p["healthy"] else "unhealthy"
        extra = []
        if p.get("latency_ms") is not None:
            extra.append(f"{p['latency_ms']}ms")
        if p.get("reconnect_count") is not None:
            extra.append(f"{p['reconnect_count']} failure(s)")
        if p.get("last_successful_update"):
            extra.append(f"last update {p['last_successful_update'][:16].replace('T', ' ')}")
        suffix = f" ({', '.join(extra)})" if extra else ""
        lines.append(f"{p['name']}: {state}{suffix}")
    return "\n".join(lines)


def format_watchdog_performance(status: dict) -> str:
    lines = [
        "*WATCHDOG PERFORMANCE*",
        "",
        f"Last cycle duration: {_fmt_num(status.get('scan_duration_ms'), 0)}ms",
        f"Last update: {(status.get('last_update') or 'never')[:16].replace('T', ' ')}",
        f"Next scan: {(status.get('next_scan') or 'unknown')[:16].replace('T', ' ')}",
    ]
    if status.get("memory_mb") is not None:
        lines.append(f"Memory: {status['memory_mb']} MB")
    if status.get("cpu_load_avg") is not None:
        lines.append(f"CPU load avg (1/5/15m): {status['cpu_load_avg']}")
    if status.get("scheduled_job_count") is not None:
        lines.append(f"Scheduled jobs (queue): {status['scheduled_job_count']}")
    return "\n".join(lines)


def format_watchdog_dashboard(dashboard: dict) -> str:
    """The Watchdog hub's "Complete dashboard" -- /watchdog with no
    arguments. A condensed version of every section (Current Market
    Status/Market Overview/Crypto+Macro Overview/AI Status/What Changed/
    Provider Status); the per-section subcommands (/watchdog market,
    /watchdog ai, ...) give the fuller read of each."""
    sections = [
        format_watchdog_brief(dashboard["market_brief"]),
        "",
        format_watchdog_current_status(dashboard["current_status"]),
        "",
        format_watchdog_market(
            dashboard["market_overview"],
            dashboard["crypto_overview"],
            dashboard["macro_overview"],
        ),
        "",
        format_watchdog_ai(dashboard["ai_status"]),
        "",
        format_watchdog_changes(dashboard["what_changed"]),
        "",
        "Use /watchdog events | providers | market | ai | changes | performance for more detail.",
        nav_pointer("watchdog"),
    ]
    return "\n".join(sections)


def format_replay(snapshot: dict | None, insight: dict | None = None) -> str:
    """v10.0: when `insight` (from build_replay_insight()) is supplied,
    renders the shared AI Insight block -- committee decision at that time,
    consensus, BTC-proxy historical similarity -- in place of the raw
    consensus dict dump, so /replay stops being the platform's least-
    enriched screen. Falls back to the old inline consensus line when no
    insight is available (e.g. a snapshot predating agent/consensus
    tracking)."""
    if snapshot is None:
        return "No market snapshot has been taken yet -- check back shortly."
    lines = [
        f"*MARKET REPLAY* ({snapshot['computed_at']})",
        "",
        f"Regime: {(snapshot['regime'] or 'unknown').replace('_', ' ').title()}",
        (
            f"Health {snapshot['health_score']}/100 | "
            f"Trend Strength {snapshot['trend_strength_score']}/100 | "
            f"Risk {snapshot['risk_score']}/100 | Confidence {snapshot['confidence_score']}/100"
        ),
    ]
    if snapshot["portfolio_advice"]:
        pa = snapshot["portfolio_advice"]
        lines.append(f"Portfolio advice ({pa['symbol']}): {pa['recommendation']}")
    if snapshot["alerts"]:
        lines.append(f"Alerts since previous snapshot: {len(snapshot['alerts'])}")

    if insight:
        lines.append("")
        lines.append("*AI Insight*")
        lines.extend(format_ai_insight_lines(insight))
    elif snapshot["consensus"]:
        c = snapshot["consensus"]
        lines.append(
            f"Consensus: bullish {c['bullish_pct']}% / bearish {c['bearish_pct']}% / "
            f"neutral {c['neutral_pct']}% (conflict {c['conflict_pct']}%)"
        )
    lines.append("")
    lines.append(nav_pointer("replay"))
    return "\n".join(lines)


def format_advice(advice: dict | None, symbol: str, timeframe_arg: str) -> str:
    if advice is None:
        return (
            f"Not enough data yet for {symbol}/{timeframe_arg} -- needs synced history "
            "(run sync_history.py), a computed Signal snapshot and a computed "
            "Probability snapshot."
        )
    probs = advice["probability"]
    lines = [
        f"*{advice['symbol']} ADVICE* ({advice['timeframe']}) -- {advice['recommendation']}",
        "",
        advice["reasoning"],
        "",
        f"Reference price: {advice['entry_reference_price']:,.2f}",
        f"ATR: {advice['atr']:.4f}" if advice["atr"] is not None else "ATR: unavailable",
        f"Probability -- up: {probs['up']}% | down: {probs['down']}% | flat: {probs['flat']}%",
    ]
    if advice["stop_loss_price"] is not None:
        lines.append("")
        lines.append(f"Stop-loss: {advice['stop_loss_price']:,.2f}")
        lines.append(f"Take-profit: {advice['take_profit_price']:,.2f}")
        lines.append(f"Risk:reward: 1:{advice['risk_reward_ratio']:.1f}")
    if advice["position_size_note"]:
        lines.append(
            f"Position size: {advice['position_size_quantity']} -- {advice['position_size_note']}"
        )
    return "\n".join(lines)


def format_research_result(result: dict | None) -> str:
    if result is None:
        return "No usable result -- unknown event category, no recorded events, or no history."
    return "\n".join(
        [
            f"*RESEARCH: {result['target_symbol']} after {result['event_category'].upper()}* "
            f"({result['timeframe']}, {result['horizon_periods']}-period horizon)",
            "",
            f"Occurrences: {result['occurrences']}",
            f"Win rate: {result['win_rate_pct']}%",
            f"Avg return: {result['avg_return_pct']}%",
            f"Max drawdown: {result['max_drawdown_pct']}%",
            f"Profit factor: {result['profit_factor']}",
            f"Sharpe ratio: {result['sharpe_ratio']}",
        ]
    )


def format_strategy_result(result: dict | None) -> str:
    if result is None:
        return "No historical occurrences of this rule found."
    lines = [
        f"*STRATEGY: {result['target_symbol']}* ({result['timeframe']}, "
        f"{result['horizon_periods']}-period horizon)",
        "",
        f"Occurrences: {result['occurrences']}",
        f"Win rate: {result['win_rate_pct']}%",
        f"Avg return: {result['avg_return_pct']}%",
        f"Max drawdown: {result['max_drawdown_pct']}%",
        f"Profit factor: {result['profit_factor']}",
        f"Sharpe ratio: {result['sharpe_ratio']}",
    ]
    if result.get("stop_loss_pct") is not None:
        lines.append(f"Stop loss: {result['stop_loss_pct']:.2%}")
    if result.get("take_profit_pct") is not None:
        lines.append(f"Take profit: {result['take_profit_pct']:.2%}")
    if result.get("position_size_pct") is not None:
        lines.append(f"Position size: {result['position_size_pct']:.0%}")
    return "\n".join(lines)


def format_walk_forward(folds: list[dict]) -> str:
    if not folds:
        return "Not enough stored history for walk-forward testing."
    lines = ["*WALK-FORWARD TEST*", ""]
    for fold in folds:
        metrics = fold["metrics"]
        lines.append(f"Fold {fold['fold']} ({fold['start_date'][:10]} to {fold['end_date'][:10]}):")
        if metrics is None:
            lines.append("  No occurrences in this window.")
        else:
            lines.append(
                f"  {metrics['occurrences']} trades, {metrics['win_rate_pct']}% win rate, "
                f"{metrics['avg_return_pct']}% avg return"
            )
    return "\n".join(lines)


def format_monte_carlo(result: dict | None) -> str:
    if result is None:
        return "Not enough historical trades to run a Monte Carlo simulation (need at least 2)."
    return "\n".join(
        [
            f"*MONTE CARLO: {result['target_symbol']}* "
            f"({result['n_simulations']} simulations, {result['trades_per_sim']} trades each)",
            "",
            f"Total return: {result['total_return_p5_pct']}% (p5) / "
            f"{result['total_return_p50_pct']}% (p50) / {result['total_return_p95_pct']}% (p95)",
            f"Max drawdown: {result['max_drawdown_p50_pct']}% (p50) / "
            f"{result['max_drawdown_p95_pct']}% (p95)",
        ]
    )


def format_hypothesis(row) -> str:
    lines = [
        f"*HYPOTHESIS: {row.statement}*",
        "",
        f"Verdict: {row.verdict.value.upper()}",
        row.reason,
    ]
    return "\n".join(lines)


def format_hypothesis_list(rows: list) -> str:
    if not rows:
        return "No hypotheses tested yet."
    lines = ["*RECENT HYPOTHESES*", ""]
    for row in rows:
        lines.append(f"- [{row.verdict.value.upper()}] {row.statement}")
    return "\n".join(lines)


def format_ranking(row) -> str:
    if row is None:
        return "No ranking computed yet."
    lines = [f"*FACTOR RANKING vs {row.target_symbol}*", ""]
    for entry in row.rankings:
        current = entry.get("current_importance_pct")
        historical = entry.get("historical_importance_pct")
        current_str = f"{current}%" if current is not None else "n/a"
        historical_str = f"{historical}%" if historical is not None else "n/a"
        lines.append(
            f"{entry['rank']}. {entry['factor']} -- current edge {current_str}, "
            f"historical edge {historical_str}, confidence (n={entry['confidence']})"
        )
    return "\n".join(lines)


def format_backtest_result(result: dict | None) -> str:
    if result is None:
        return "No historical occurrences of this rule found."
    return "\n".join(
        [
            f"*BACKTEST: {result['target_symbol']}* ({result['timeframe']}, "
            f"{result['horizon_periods']}-period horizon)",
            "",
            f"Occurrences: {result['occurrences']}",
            f"Win rate: {result['win_rate_pct']}%",
            f"Avg return: {result['avg_return_pct']}%",
            f"Max drawdown: {result['max_drawdown_pct']}%",
            f"Profit factor: {result['profit_factor']}",
            f"Sharpe ratio: {result['sharpe_ratio']}",
        ]
    )


def format_opportunities(opportunities: list[dict], top_factors: list[dict] | None = None) -> str:
    if not opportunities:
        return (
            "No opportunities computed this cycle -- no signal has reported for any "
            "tracked symbol yet."
        )
    lines = ["*TOP OPPORTUNITIES*", ""]
    for opp in opportunities:
        lines.append(f"*{opp['symbol']}*: {opp['classification']} ({opp['opportunity_score']}/100)")
        details = []
        if opp["probability_edge_pct"] is not None:
            details.append(f"probability edge {opp['probability_edge_pct']:+.1f}%")
        if opp["breakout"] is not None:
            details.append(
                f"{opp['breakout']['event_type'].replace('_', ' ')} "
                f"({opp['breakout']['direction']}, {opp['breakout']['probability_pct']}%)"
            )
        if opp["advisor_recommendation"] is not None:
            details.append(f"advisor: {opp['advisor_recommendation']}")
        if details:
            lines.append("  " + " | ".join(details))
        lines.append("")
    if top_factors:
        # v12.0 P1 -- RankingEngine's measured factor edge (walk-forward
        # backtest, not opinion), so a reader can see whether the signals
        # behind these calls currently have real predictive power.
        lines.append("*Factor Context*")
        for f in top_factors:
            edge = f.get("current_importance_pct")
            edge_str = f"{edge:+.1f}% edge" if edge is not None else "edge unavailable"
            lines.append(f"{f['factor'].replace('_', ' ')}: {edge_str}")
        lines.append("")
    return "\n".join(lines).strip()


def format_brief(brief: dict) -> str:
    lines = ["*DAILY TERMINAL BRIEF*", ""]
    lines.append(f"Regime: {(brief['regime'] or 'unknown').replace('_', ' ').title()}")
    if brief["health_score"] is not None:
        lines.append(f"Market health: {brief['health_score']}/100")
    if brief["risk"] is not None:
        lines.append(
            f"Risk-off: {brief['risk']['risk_off_score']}/100 | "
            f"Liquidity: {brief['risk']['liquidity_score']}/100"
        )
    lines.append("")

    if brief["committee"] is not None:
        c = brief["committee"]
        lines.append(f"*Committee*: {c['final_recommendation']}")
        lines.append(
            f"Majority {c['majority_decision']} ({c['majority_pct']}%) | "
            f"Dissent {c['dissent_pct']}%"
        )
    else:
        lines.append("*Committee*: no agent reported a direction this cycle.")
    lines.append("")

    if brief["top_opportunities"]:
        lines.append("*Top Opportunities*")
        for opp in brief["top_opportunities"][:3]:
            lines.append(
                f"- {opp['symbol']}: {opp['classification']} ({opp['opportunity_score']}/100)"
            )
    else:
        lines.append("*Top Opportunities*: none computed this cycle.")
    lines.append("")

    portfolio = brief["portfolio"]
    if portfolio.get("empty"):
        lines.append("*Portfolio*: no positions held.")
    else:
        lines.append(
            f"*Portfolio*: health {portfolio['health_score']}/100, "
            f"value {portfolio['total_value']:,.2f}"
        )
    lines.append("")

    if brief["consensus"]:
        c = brief["consensus"]
        lines.append(
            f"*Consensus*: bullish {c['bullish_pct']}% / bearish {c['bearish_pct']}% / "
            f"neutral {c['neutral_pct']}% (conflict {c['conflict_pct']}%)"
        )
        lines.append("")

    if brief["watchdog"]:
        w = brief["watchdog"]
        lines.append(f"*Watchdog*: {w['market_health'] or 'unknown'}")
        if w["highest_risk"]:
            lines.append(f"Highest risk: {w['highest_risk']}")
        if w["biggest_opportunity"]:
            lines.append(f"Biggest opportunity: {w['biggest_opportunity']}")
        lines.append("")

    scanner = brief["scanner"]
    if scanner["breadth"]:
        b = scanner["breadth"]
        lines.append(
            f"*Scanner*: {b['rising_count']} rising / {b['falling_count']} falling "
            f"of {b['total_scanned']} scanned -- {scanner['active_alerts_count']} active alert(s)"
        )
        lines.append("")

    if brief["historical_intelligence"]:
        h = brief["historical_intelligence"]["summary"]
        lines.append(
            f"*Historical Intelligence*: most similar setup {h['symbol']} "
            f"({h['similarity_score']}% similar)"
        )
        lines.append("")

    lines.append(nav_pointer("brief"))
    return "\n".join(lines)


def format_historical_comparison(result: dict | None) -> str:
    if result is None:
        return "Not enough Market Replay history yet to compare against that far back."
    diff = result["diff"]
    lines = [
        f"*HISTORICAL COMPARISON* ({result['days_ago']} days ago vs now)",
        "",
        f"Regime: {diff['regime']['from']} -> {diff['regime']['to']}"
        + (" (changed)" if diff["regime"]["changed"] else ""),
    ]
    for field in ("health_score", "trend_strength_score", "risk_score", "confidence_score"):
        entry = diff[field]
        if entry["delta"] is not None:
            label = field.replace("_", " ").title()
            lines.append(f"{label}: {entry['from']} -> {entry['to']} ({entry['delta']:+d})")
    if diff.get("consensus_evolution") is not None:
        lines.append(f"Consensus: {diff['consensus_evolution']['summary']}")
    return "\n".join(lines)


def format_weekly_review(result: dict) -> str:
    lines = [
        "*WEEKLY REVIEW*",
        "",
        f"Graded predictions this week: {result['evaluated_predictions']}",
    ]
    if result["accuracy_pct"] is not None:
        lines.append(f"Accuracy: {result['accuracy_pct']}%")
    lines.append(f"Alerts logged: {result['alerts_count']}")
    lines.append("")
    lines.append(format_historical_comparison(result["historical_comparison"]))
    return "\n".join(lines)


_SHOCK_TIER_EMOJI = {"info": "i", "important": "⚠️", "high": "\U0001f6a8", "critical": "\U0001f198"}
_SHOCK_CATEGORY_TITLE = {"price_shock": "MOMENTUM ALERT", "multi_asset_shock": "MARKET SHOCK"}
_SHOCK_QUALITY_LABELS: dict[str, str] = {
    "volume": "elevated volume",
    "volatility": "elevated volatility",
    "regime_alignment": "consistent with the current market regime",
    "trend_strength": "strong prevailing trend",
    "consensus_alignment": "agent consensus agrees",
    "committee_alignment": "AI committee agrees",
    "historical_similarity": "similar historical episodes moved the same way",
    "risk_score": "elevated risk conditions",
    "confidence_score": "high signal confidence",
}


def _shock_recommendation(direction: str, tier: str) -> str:
    intensity = "Extreme" if tier == "critical" else "High" if tier == "high" else "Moderate"
    if direction == "down":
        return (
            f"{intensity} downside volatility. Avoid aggressive entries until stabilization; "
            "consider tightening stops on existing longs."
        )
    return (
        f"{intensity} upside momentum. Confirm with volume/follow-through before chasing; "
        "avoid FOMO entries at the extreme."
    )


def format_critical_alert(
    envelope: dict,
    tier: str,
    quality_score: float | None,
    previous_tier: str | None = None,
) -> str:
    """Renders one Autonomous Critical Alert System detection (v5.1) --
    a SECOND, independent alert layer from the Smart Alert Engine's
    format_watchdog()/broadcast messages and Configurable Alerts'
    format_alert_*() above.

    v8.0: also states what changed since the previous alert of this key
    (`previous_tier`, passed only on an escalation of an already-active
    alert) and how unusual the move is historically, via the same
    historical_similarity_score() already folded into quality_components
    for the "Reasons" line below -- surfaced here as an explicit
    percentage instead of a bare >=60 threshold check."""
    category = envelope["category"]
    direction = envelope["direction"]
    emoji = _SHOCK_TIER_EMOJI.get(tier, "")
    title = _SHOCK_CATEGORY_TITLE.get(category, "ALERT")
    lines = [f"{emoji} *{title}* ({tier.upper()})", ""]
    if previous_tier is not None and previous_tier != tier:
        lines.append(f"What Changed: escalated from {previous_tier.upper()} to {tier.upper()}.")
        lines.append("")

    for reading in envelope["readings"]:
        current = reading["current_value"]
        current_str = f"{current:,.2f}" if current is not None else "n/a"
        lines.append(
            f"*{reading['symbol']}*: {reading['pct_change']:+.2f}% ({reading['window']}) "
            f"-- now {current_str}"
        )
    lines.append("")

    ctx = envelope["context"]
    if ctx["regime"] is not None:
        lines.append(f"Market Regime: {ctx['regime'].replace('_', ' ').title()}")
    if ctx["trend_strength_score"] is not None:
        lines.append(f"Trend Strength: {ctx['trend_strength_score']}/100")
    if ctx["risk_score"] is not None:
        lines.append(f"Risk Score: {ctx['risk_score']}/100")
    if quality_score is not None:
        lines.append(f"Confidence: {round(quality_score)}%")
    lines.append("")

    if ctx["committee"] is not None:
        lines.append(f"Committee Opinion: {ctx['committee']['final_recommendation']}")
        lines.append("")

    historical_similarity = envelope["quality_components"].get("historical_similarity")
    if historical_similarity is not None:
        lines.append(
            f"How Unusual: {historical_similarity}% of similar historical moves continued "
            f"{direction} afterward -- what AI expects next."
        )
        lines.append("")

    reasons = [
        label
        for key, label in _SHOCK_QUALITY_LABELS.items()
        if (envelope["quality_components"].get(key) or 0) >= 60
    ]
    if reasons:
        lines.append("Reasons: " + "; ".join(reasons))
        lines.append("")

    lines.append("Recommendation:")
    lines.append(_shock_recommendation(direction, tier))

    if ctx["scenarios"]:
        lines.append("")
        lines.append("Expected Scenarios:")
        for scenario in ctx["scenarios"][:3]:
            name = scenario.get("name", "Scenario")
            probability = scenario.get("probability_pct")
            prob_str = f" ({probability}%)" if probability is not None else ""
            lines.append(f"- {name}{prob_str}")

    if len(envelope["readings"]) > 1:
        lines.append("")
        lines.append("Related Markets: " + ", ".join(r["symbol"] for r in envelope["readings"]))

    return "\n".join(lines)


def format_scanner_alert(detection: dict) -> str:
    """v5.5/v8.0 Market Scanner Telegram alert -- the mission's required
    field list: Title, Asset, Current Price, Price Change, Volume Change,
    Market Regime, Trend, Risk, Confidence, Committee Opinion, Explanation,
    Recommendation, plus v8.0's Main Opportunity/Main Threat/Expected
    Scenario (from the same WatchdogSnapshot-derived context already
    carrying regime/risk/committee -- MarketScannerEngine.get_market_context(),
    not a new calculation). `detection` is one MarketScannerEngine.run_cycle()
    processed-detection dict; only ever called for tier in (high,
    critical), per the mission's "Only HIGH and CRITICAL events should
    notify users"."""
    tier = detection["tier"]
    emoji = _SHOCK_TIER_EMOJI.get(tier, "")
    title = detection.get("title") or detection["category"].replace("_", " ").upper()
    lines = [f"{emoji} *{title}* ({tier.upper()})", ""]

    lines.append("Asset: " + ", ".join(detection["symbols"]))

    readings = detection.get("readings") or []
    if detection["category"] == "price_event" and readings:
        r = readings[0]
        lines.append(f"Current Price: {r['price']:,.6f}")
        change = r.get("change_pct_24h")
        lines.append(
            f"Price Change: {change:+.2f}% (24h)" if change is not None else "Price Change: n/a"
        )
        volume = r.get("volume_24h")
        lines.append(
            f"Volume Change: {volume:,.0f} (24h volume)"
            if volume is not None
            else "Volume Change: n/a"
        )
    elif readings:
        for r in readings:
            window = r.get("window", "24h")
            lines.append(f"{r['symbol']}: {r['pct_change']:+.2f}% ({window})")
    lines.append("")

    ctx = detection.get("context") or {}
    if ctx.get("regime"):
        # v9.0 noise pass: Trend is a pure 3-bucket derivation of Regime --
        # merged into one line rather than shown as a separate fact.
        regime_title = ctx["regime"].replace("_", " ").title()
        trend_title = regime_direction_bucket(ctx["regime"]).title()
        lines.append(f"Market Regime: {regime_title} ({trend_title})")
    if ctx.get("risk_score") is not None:
        lines.append(f"Risk: {ctx['risk_score']}/100")
    if ctx.get("confidence_score") is not None:
        lines.append(f"Confidence: {ctx['confidence_score']}/100")
    if ctx.get("committee_decision"):
        majority = ctx.get("committee_majority_pct")
        majority_str = f" ({majority}%)" if majority is not None else ""
        lines.append(f"Committee Opinion: {ctx['committee_decision']}{majority_str}")
    if ctx.get("expected_scenario"):
        pct = ctx.get("expected_scenario_pct")
        pct_str = f" ({pct}%)" if pct is not None else ""
        lines.append(f"Expected Scenario: {ctx['expected_scenario']}{pct_str}")
    if ctx.get("biggest_opportunity"):
        lines.append(f"Main Opportunity: {ctx['biggest_opportunity']}")
    if ctx.get("highest_risk"):
        lines.append(f"Main Risk: {ctx['highest_risk']}")
    lines.append("")

    lines.append("Explanation:")
    lines.append(detection["message"])
    lines.append("")

    lines.append("Recommendation:")
    lines.append(_shock_recommendation(detection.get("direction") or "up", tier))

    return "\n".join(lines)


def format_scanner_dashboard(dashboard: dict) -> str:
    lines = ["*MARKET SCANNER*", ""]
    breadth = dashboard.get("top_movers")
    if breadth and breadth.get("total_scanned"):
        lines.append(
            f"Scanned {breadth['total_scanned']} symbols -- "
            f"{breadth['rising_count']} rising / {breadth['falling_count']} falling"
        )
    else:
        lines.append("No scan data yet -- check back after the next cycle.")
    pending = dashboard.get("pending_alerts") or []
    suppressed = dashboard.get("suppressed_alerts") or []
    lines.append(f"Pending alerts: {len(pending)} | Suppressed (last 50): {len(suppressed)}")
    lines.append("")

    # Same WatchdogSnapshot already read by the AI filter every cycle --
    # composed here rather than recomputed, so this is visible even when
    # nothing has fired a HIGH/CRITICAL alert this cycle.
    ctx = dashboard.get("market_context") or {}
    if ctx.get("regime"):
        lines.append("*Market Context*")
        lines.append(
            f"Regime: {ctx['regime'].replace('_', ' ').title()} "
            f"({regime_direction_bucket(ctx['regime']).title()})"
        )
        if ctx.get("risk_score") is not None:
            lines.append(f"Risk: {ctx['risk_score']}/100")
        if ctx.get("confidence_score") is not None:
            lines.append(f"Confidence: {ctx['confidence_score']}/100")
        if ctx.get("committee_decision"):
            majority = ctx.get("committee_majority_pct")
            majority_str = f" ({majority}%)" if majority is not None else ""
            lines.append(f"Committee: {ctx['committee_decision']}{majority_str}")
        if ctx.get("expected_scenario"):
            pct = ctx.get("expected_scenario_pct")
            pct_str = f" ({pct}%)" if pct is not None else ""
            lines.append(f"Expected Scenario: {ctx['expected_scenario']}{pct_str}")
        insight = ctx.get("ai_insight") or {}
        if insight.get("consensus"):
            lines.append(f"Consensus: {insight['consensus']}")
        if insight.get("main_opportunity"):
            lines.append(f"Main Opportunity: {insight['main_opportunity']}")
        if insight.get("main_risk"):
            lines.append(f"Main Risk: {insight['main_risk']}")
        lines.append("")

    if breadth and breadth.get("top_gainers"):
        lines.append("*Top Gainers*")
        for r in breadth["top_gainers"][:5]:
            lines.append(f"{r['symbol']}: {r['change_pct_24h']:+.2f}%")
        lines.append("")
    if breadth and breadth.get("top_losers"):
        lines.append("*Top Losers*")
        for r in breadth["top_losers"][:5]:
            lines.append(f"{r['symbol']}: {r['change_pct_24h']:+.2f}%")
        lines.append("")

    sectors = dashboard.get("sector_leaders") or []
    if sectors:
        lines.append("*Sector Leaders*")
        for s in sectors[:5]:
            lines.append(
                f"{s['sector']}: {s['avg_change_pct_24h']:+.2f}% ({s['coin_count']} coins)"
            )
        lines.append("")

    lines.append("Use /scanner movers | sectors | detections | pending for more detail.")
    lines.append(nav_pointer("scanner"))
    return "\n".join(lines)


def format_scanner_movers(breadth: dict | None) -> str:
    if not breadth or not breadth.get("total_scanned"):
        return "*TOP MOVERS*\n\nNo scan data yet -- check back after the next cycle."
    lines = [
        "*TOP MOVERS*",
        "",
        f"Scanned {breadth['total_scanned']} symbols -- {breadth['rising_count']} rising / "
        f"{breadth['falling_count']} falling / {breadth['unchanged_count']} unchanged",
        "",
        "*Top Gainers*",
    ]
    for r in breadth["top_gainers"][:20]:
        lines.append(f"{r['symbol']}: {r['change_pct_24h']:+.2f}% -- {r['price']:,.4f}")
    lines.append("")
    lines.append("*Top Losers*")
    for r in breadth["top_losers"][:20]:
        lines.append(f"{r['symbol']}: {r['change_pct_24h']:+.2f}% -- {r['price']:,.4f}")
    return "\n".join(lines)


def format_scanner_sectors(sectors: list[dict]) -> str:
    if not sectors:
        return "*SECTOR LEADERS*\n\nNo sector data yet -- check back after the next cycle."
    lines = ["*SECTOR LEADERS*", ""]
    for s in sectors:
        top_mover = (
            f" (top: {s['top_mover']} {s['top_mover_change_pct_24h']:+.2f}%)"
            if s.get("top_mover")
            else ""
        )
        avg_change = s["avg_change_pct_24h"]
        lines.append(f"{s['sector']}: {avg_change:+.2f}% avg, {s['coin_count']} coins{top_mover}")
    return "\n".join(lines)


def format_scanner_detections(detections: list[dict]) -> str:
    if not detections:
        return "*LATEST DETECTIONS*\n\nNo detections logged yet."
    lines = ["*LATEST DETECTIONS*", ""]
    for d in detections[:20]:
        state = "active" if d["active"] else "resolved"
        lines.append(
            f"{d['last_updated_at'][:16].replace('T', ' ')} [{d['tier'].upper()}] "
            f"{', '.join(d['symbols'])} ({state})"
        )
        lines.append(d["message"])
        lines.append("")
    return "\n".join(lines).strip()


def format_active_shocks(rows: list) -> str:
    if not rows:
        return "No active critical alerts right now."
    lines = ["*ACTIVE CRITICAL ALERTS*", ""]
    for row in rows:
        lines.append(
            f"[{row.tier.upper()}] {', '.join(row.symbols)} -- "
            f"since {row.first_triggered_at.strftime('%Y-%m-%d %H:%M UTC')}"
        )
    return "\n".join(lines)


def format_technical(symbol: str, result: dict | None) -> str:
    """AI-interpreted technical read only -- bullish/bearish score, trend
    strength, momentum, volatility, breakout/breakdown probability,
    confidence, support/resistance and active signal names. Never shows raw
    indicator values (RSI/MACD/...), matching the mission's "AI Brain must
    interpret them" constraint. `result` is the dict shape produced by
    TechnicalAnalysisEngine.analyze() (or the equivalent serialized
    snapshot from GET /api/technical)."""
    if result is None:
        return (
            f"No technical analysis available for {symbol} -- not in the synced history "
            "registry and TradingView MCP is not configured."
        )

    lines = [f"*TECHNICAL ANALYSIS -- {symbol}*", f"Source: {result.get('source', 'unknown')}", ""]

    bullish = result.get("bullish_score")
    bearish = result.get("bearish_score")
    if bullish is not None and bearish is not None:
        lines.append(f"Bullish {bullish:.0f} / Bearish {bearish:.0f}")

    trend = result.get("trend_strength")
    momentum = result.get("momentum")
    volatility = result.get("volatility")
    if trend is not None:
        lines.append(f"Trend Strength: {trend:.0f}")
    if momentum is not None:
        lines.append(f"Momentum: {momentum:.1f}")
    if volatility is not None:
        lines.append(f"Volatility: {volatility:.0f}")

    breakout = result.get("breakout_probability")
    breakdown = result.get("breakdown_probability")
    if breakout is not None and breakdown is not None:
        lines.append(
            f"Breakout Probability: {breakout:.0f}% / Breakdown Probability: {breakdown:.0f}%"
        )

    confidence = result.get("confidence")
    if confidence is not None:
        lines.append(f"Confidence: {confidence:.0f}%")

    support = result.get("support")
    resistance = result.get("resistance")
    if support is not None or resistance is not None:
        support_str = f"{support:,.2f}" if support is not None else "n/a"
        resistance_str = f"{resistance:,.2f}" if resistance is not None else "n/a"
        lines.append(f"Support: {support_str} | Resistance: {resistance_str}")

    timeframes = result.get("timeframes_covered")
    if timeframes:
        lines.append(f"Timeframes: {', '.join(timeframes)}")

    signals = result.get("active_signals")
    if signals:
        lines.append("")
        lines.append("Active Signals: " + ", ".join(signals))

    alignment = result.get("high_confidence_alignment")
    if alignment:
        lines.append("")
        signal_label = alignment["signal"].replace("_", " ")
        lines.append(f"*{signal_label}*: " + "; ".join(alignment["reasons"]))

    return "\n".join(lines)


def format_alert_rule_created(rule) -> str:
    return (
        f"*Alert rule #{rule.id} created*\n"
        f"{rule.symbol} {rule.metric.replace('_', ' ')} {rule.operator} "
        f"{float(rule.threshold):.2f} (cooldown {rule.cooldown_minutes}m)"
    )


def format_alert_rules(rules: list) -> str:
    if not rules:
        return "You have no alert rules yet. Create one with /setalert."
    lines = ["*YOUR ALERT RULES*", ""]
    for rule in rules:
        status = "" if rule.enabled else " (disabled)"
        lines.append(
            f"#{rule.id}: {rule.symbol} {rule.metric.replace('_', ' ')} {rule.operator} "
            f"{float(rule.threshold):.2f}{status}"
        )
    return "\n".join(lines)


def format_alert_history(history: list[dict]) -> str:
    if not history:
        return "No custom alerts have fired for you yet."
    lines = ["*YOUR RECENT ALERTS*", ""]
    for entry in history:
        lines.append(
            f"{entry['symbol']} {entry['metric'].replace('_', ' ')}: {entry['value']:.2f} "
            f"{entry['operator']} {entry['threshold']:.2f}"
        )
    return "\n".join(lines)


def format_monthly_performance(result: dict) -> str:
    lines = [
        "*MONTHLY PERFORMANCE*",
        "",
        f"Graded predictions this month: {result['evaluated_predictions']}",
    ]
    if result["accuracy_pct"] is not None:
        lines.append(f"Accuracy: {result['accuracy_pct']}%")
    lines.append(f"Alerts logged: {result['alerts_count']}")
    lines.append("")
    lines.append(format_historical_comparison(result["historical_comparison"]))
    return "\n".join(lines)
