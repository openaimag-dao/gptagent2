import logging

import anthropic
from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

_openai_client: AsyncOpenAI | None = None
_anthropic_client: anthropic.AsyncAnthropic | None = None

_ANTHROPIC_MAX_TOKENS = 4096


def _get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not configured; AI analysis/report generation is unavailable"
            )
        _openai_client = AsyncOpenAI(
            api_key=settings.openai_api_key, base_url=settings.openai_base_url
        )
    return _openai_client


def get_llm_client() -> AsyncOpenAI:
    """Returns a cached AsyncOpenAI client pointed at the configured (OpenAI-compatible) endpoint.

    Raises a clear error if no key is configured, rather than silently
    returning a client that will fail on first use.
    """
    return _get_openai_client()


def _get_anthropic_client() -> anthropic.AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _anthropic_client


async def _anthropic_completion(system_prompt: str, user_prompt: str) -> str:
    settings = get_settings()
    client = _get_anthropic_client()
    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=_ANTHROPIC_MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        temperature=0.3,
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    if not text.strip():
        # A 200 response with no text block (all content non-text, or the
        # model stopped before emitting any) is not a raised APIError, but
        # it's just as unusable -- treat it as a failure so the caller falls
        # back to OpenAI instead of handing an empty string to json.loads()
        # three layers up.
        raise RuntimeError(
            f"Anthropic returned no text content (stop_reason={response.stop_reason})"
        )
    return text


async def _openai_completion(
    system_prompt: str, user_prompt: str, *, json_mode: bool = True
) -> str:
    settings = get_settings()
    client = _get_openai_client()
    extra = {"response_format": {"type": "json_object"}} if json_mode else {}
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        **extra,
    )
    return response.choices[0].message.content or ""


async def _generate_with_fallback(
    system_prompt: str, user_prompt: str, *, json_mode: bool, purpose: str
) -> str:
    """Shared Anthropic-preferred/OpenAI-fallback provider selection for
    both generate_analysis_json and generate_text -- only whether OpenAI's
    JSON response mode is forced differs between the two callers."""
    settings = get_settings()
    if not settings.anthropic_api_key and not settings.openai_api_key:
        raise RuntimeError(
            f"Neither ANTHROPIC_API_KEY nor OPENAI_API_KEY is configured; {purpose} is unavailable"
        )

    if settings.anthropic_api_key:
        try:
            return await _anthropic_completion(system_prompt, user_prompt)
        except (anthropic.APIError, RuntimeError) as exc:
            if not settings.openai_api_key:
                raise RuntimeError(f"Anthropic {purpose} failed: {exc}") from exc
            logger.warning("Anthropic %s failed, falling back to OpenAI: %s", purpose, exc)

    return await _openai_completion(system_prompt, user_prompt, json_mode=json_mode)


async def generate_analysis_json(system_prompt: str, user_prompt: str) -> str:
    """Runs the report-generation completion and returns the raw JSON text.

    Anthropic (Claude) is preferred when ANTHROPIC_API_KEY is configured --
    falling back to the OpenAI-compatible client if the Anthropic call fails
    and OpenAI is also configured. Both providers get the exact same
    prompts; only the transport differs, so the caller's JSON parsing and
    validation stays provider-agnostic.
    """
    return await _generate_with_fallback(
        system_prompt, user_prompt, json_mode=True, purpose="report generation"
    )


async def generate_text(system_prompt: str, user_prompt: str) -> str:
    """Same Anthropic-preferred/OpenAI-fallback selection as
    generate_analysis_json, but without forcing OpenAI's JSON response mode
    -- for free-text narrative generation (e.g. the AI Researcher's daily
    note) rather than a report that must parse as a fixed JSON schema.
    """
    return await _generate_with_fallback(
        system_prompt, user_prompt, json_mode=False, purpose="text generation"
    )
