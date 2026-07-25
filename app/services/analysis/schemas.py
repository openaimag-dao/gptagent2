from pydantic import BaseModel, Field


class AIAnalysisContent(BaseModel):
    """The LLM-authored narrative sections of a report.

    Every field is grounded in the real, already-computed data handed to the
    model in the prompt (market snapshot, news, correlations, regime,
    signal score) -- the LLM's job is synthesis and explanation, not
    invention.
    """

    what_changed: str
    why: str
    who_is_driving: str
    institutional_behavior: str
    macro_explanation: str
    historical_comparison: str
    liquidity_and_risk: str
    main_risks: str
    key_events_today: str
    scenarios: str
    actionable_insights: str
    probability_bullish_pct: int = Field(ge=0, le=100)
    probability_bearish_pct: int = Field(ge=0, le=100)
    probability_neutral_pct: int = Field(ge=0, le=100)
