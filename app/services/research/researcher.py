"""AI Researcher (V3 Phase 7): a daily note over the Smart Alert Engine's
real detections. Discovery and ranking are entirely deterministic -- this
engine does not run its own anomaly/correlation/regime-change detection,
it reuses AlertLog rows the Smart Alert Engine (app/services/alerts/) has
already computed and persisted, ranked by their already-computed
confidence_pct. The LLM (app.llm.client.generate_text) only turns that
ranked list into readable prose; it never discovers or judges anything
itself, keeping the fabrication risk where every other LLM use in this
project keeps it -- narration over real numbers, not invention of them.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import AlertLog, ResearchNote
from app.llm.client import generate_text

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW_HOURS = 24

SYSTEM_PROMPT = """You are a quantitative research analyst writing a short daily research \
note. You are given a ranked list of real, already-detected market events (regime changes, \
correlation breaks, derivatives-positioning swings, ETF sentiment shifts, liquidity swings, \
upcoming macro events) for the last 24 hours, each with a confidence score that was already \
computed deterministically -- you are not detecting anything yourself, only synthesizing \
what's given into a coherent narrative.

Write 2-4 short paragraphs: what stands out most (highest confidence first), whether any of \
the detections are thematically related, and what a reader should watch next. Do not invent \
any event, number, or detection not present in the list below. If the list is empty, say \
plainly that nothing notable was detected -- do not manufacture a finding to fill space."""


def _format_discoveries(discoveries: list[AlertLog]) -> str:
    if not discoveries:
        return "No detections in this window."
    return "\n".join(
        f"- [{d.conviction_tier}, {d.confidence_pct}% confidence] {d.alert_type}: {d.message}"
        for d in discoveries
    )


class AIResearcherEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def rank_discoveries(self, window_hours: int = _DEFAULT_WINDOW_HOURS) -> list[AlertLog]:
        since = datetime.now(UTC) - timedelta(hours=window_hours)
        async with self._session_factory() as session:
            return list(
                await session.scalars(
                    select(AlertLog)
                    .where(AlertLog.triggered_at >= since)
                    .order_by(AlertLog.confidence_pct.desc())
                )
            )

    async def generate_daily_note(self, window_hours: int = _DEFAULT_WINDOW_HOURS) -> ResearchNote:
        discoveries = await self.rank_discoveries(window_hours)
        discovery_payload = [
            {
                "alert_type": d.alert_type,
                "message": d.message,
                "confidence_pct": d.confidence_pct,
                "conviction_tier": d.conviction_tier,
                "triggered_at": d.triggered_at.isoformat(),
            }
            for d in discoveries
        ]

        if not discoveries:
            note_text = (
                f"No notable anomalies, correlation breaks or regime changes were "
                f"detected in the last {window_hours}h."
            )
        else:
            user_prompt = (
                f"RANKED DETECTIONS (last {window_hours}h, highest confidence first)\n\n"
                + _format_discoveries(discoveries)
            )
            try:
                note_text = await generate_text(SYSTEM_PROMPT, user_prompt)
            except RuntimeError as exc:
                logger.warning("AI Researcher note generation unavailable: %s", exc)
                note_text = (
                    f"{len(discoveries)} detection(s) in the last {window_hours}h "
                    f"(no LLM configured for narrative write-up):\n\n"
                    + _format_discoveries(discoveries)
                )

        row = ResearchNote(
            note=note_text,
            discoveries=discovery_payload,
            discovery_count=len(discoveries),
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    async def get_latest(self) -> ResearchNote | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(ResearchNote).order_by(ResearchNote.generated_at.desc()).limit(1)
            )
