from app.services.news.schemas import ClassifiedNewsItem, RawNewsItem, Sentiment

# A compact finance-news sentiment lexicon (in the spirit of the Loughran-McDonald
# word lists commonly used for financial text). Deterministic and free to run --
# Phase 6's LLM-driven "AI Analysis" builds richer narrative reasoning on top of
# this same classified feed; this pass only needs a fast, reliable first-order tag.
BULLISH_PHRASES: frozenset[str] = frozenset(
    {
        "surge", "surges", "surged", "surging",
        "rally", "rallies", "rallied", "rallying",
        "soar", "soars", "soared", "soaring",
        "gain", "gains", "gained",
        "jump", "jumps", "jumped",
        "record high", "all-time high", "all time high",
        "beat expectations", "beats expectations", "tops estimates",
        "outperform", "outperforms", "outperformed",
        "bullish", "bull market",
        "inflow", "inflows",
        "approval", "approved", "greenlights", "greenlit",
        "adoption", "expansion", "expands", "expanded",
        "dovish", "rate cut", "cuts rates", "cutting rates",
        "growth", "grows", "grew",
        "upgrade", "upgraded", "upgrades",
        "breakout", "recovery", "recovers", "recovered", "rebound", "rebounds",
        "boost", "boosts", "boosted",
        "optimism", "optimistic", "strong demand", "robust demand",
        "buyback", "buybacks", "raises guidance", "raised guidance",
    }
)

BEARISH_PHRASES: frozenset[str] = frozenset(
    {
        "plunge", "plunges", "plunged", "plunging",
        "crash", "crashes", "crashed", "crashing",
        "sell-off", "selloff", "sells off",
        "slump", "slumps", "slumped",
        "drop", "drops", "dropped",
        "tumble", "tumbles", "tumbled",
        "bearish", "bear market",
        "recession",
        "hike", "hikes", "hiking rates", "rate hike",
        "hawkish",
        "outflow", "outflows",
        "lawsuit", "sues", "sued", "fraud", "investigation", "probe", "subpoena",
        "default", "defaults", "crisis",
        "downgrade", "downgraded", "downgrades",
        "warning", "warns", "warned",
        "losses", "loss", "layoffs", "job cuts",
        "ban", "banned", "delist", "delisted", "delisting",
        "volatility spikes", "uncertainty", "concerns", "fears",
        "misses estimates", "missed expectations", "cuts guidance", "cut guidance",
    }
)


def classify(item: RawNewsItem) -> ClassifiedNewsItem:
    """Scores an item by counting bullish vs. bearish phrase hits in title + summary."""
    text = f"{item.title} {item.summary or ''}".lower()

    bullish_hits = sum(text.count(phrase) for phrase in BULLISH_PHRASES)
    bearish_hits = sum(text.count(phrase) for phrase in BEARISH_PHRASES)
    score = float(bullish_hits - bearish_hits)

    if score > 0:
        sentiment = Sentiment.BULLISH
    elif score < 0:
        sentiment = Sentiment.BEARISH
    else:
        sentiment = Sentiment.NEUTRAL

    return ClassifiedNewsItem(**item.model_dump(), sentiment=sentiment, sentiment_score=score)
