import logging
from collections.abc import Awaitable, Callable

import anthropic
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

_openai_client: AsyncOpenAI | None = None
_anthropic_client: anthropic.AsyncAnthropic | None = None
_gemini_client: genai.Client | None = None

_ANTHROPIC_MAX_TOKENS = 8192


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


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=get_settings().gemini_api_key)
    return _gemini_client


async def _gemini_completion(
    system_prompt: str, user_prompt: str, *, json_mode: bool = True
) -> str:
    settings = get_settings()
    client = _get_gemini_client()
    config = genai_types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.3,
        # Gemini, like OpenAI's response_format=json_object, can force a bare
        # JSON response with no markdown fence -- unlike Anthropic, which has
        # no equivalent and routinely wraps JSON answers in ```json fences
        # (see strip_json_fence() in app/services/analysis/report.py).
        response_mime_type="application/json" if json_mode else None,
    )
    response = await client.aio.models.generate_content(
        model=settings.gemini_model, contents=user_prompt, config=config
    )
    try:
        text = response.text or ""
    except (ValueError, IndexError, AttributeError):
        text = ""
    finish_reason = response.candidates[0].finish_reason if response.candidates else None
    logger.info("Gemini response: finish_reason=%s, text_len=%d", finish_reason, len(text))
    if not text.strip():
        # A 200 response with no usable text (e.g. blocked by a safety
        # filter, or truncated before emitting anything) is just as
        # unusable as an API error -- raise so the caller falls back to the
        # next provider instead of handing an empty string to json.loads()
        # three layers up.
        raise RuntimeError(f"Gemini returned no text content (finish_reason={finish_reason})")
    return text


async def _anthropic_completion(
    system_prompt: str, user_prompt: str, *, json_mode: bool = True
) -> str:
    # json_mode is accepted (not used) purely so this shares a call signature
    # with _gemini_completion/_openai_completion for _generate_with_fallback's
    # uniform dispatch -- Anthropic has no forced-JSON response mode; see
    # strip_json_fence() in app/services/analysis/report.py for how the
    # resulting markdown-fenced JSON is handled instead.
    del json_mode
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
    logger.info(
        "Anthropic response: %d content block(s) (%s), stop_reason=%s, text_len=%d",
        len(response.content),
        ",".join(sorted({block.type for block in response.content})) or "none",
        response.stop_reason,
        len(text),
    )
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
    choice = response.choices[0]
    text = choice.message.content or ""
    logger.info("OpenAI response: finish_reason=%s, text_len=%d", choice.finish_reason, len(text))
    if not text.strip():
        # A 200 response with no message content (e.g. the model hit its
        # token budget before emitting anything under forced JSON mode) is
        # just as unusable as an API error -- raise so the caller sees a
        # clear reason instead of handing an empty string to json.loads()
        # three layers up.
        raise RuntimeError(
            f"OpenAI returned no message content (finish_reason={choice.finish_reason})"
        )
    return text


_PROVIDER_ERRORS = (genai_errors.APIError, anthropic.APIError, RuntimeError)
_CompletionFn = Callable[..., Awaitable[str]]


async def _generate_with_fallback(
    system_prompt: str, user_prompt: str, *, json_mode: bool, purpose: str
) -> str:
    """Shared Gemini > Anthropic > OpenAI provider selection for both
    generate_analysis_json and generate_text -- only whether the JSON
    response mode is forced differs between the two callers. Gemini is
    preferred because it has a genuine ongoing free tier, unlike
    Anthropic/OpenAI (pay-per-token, one-time trial credit only); each
    provider is only tried if configured, and a failure falls through to
    the next configured one rather than failing the whole call."""
    settings = get_settings()
    candidates: list[tuple[str, bool, _CompletionFn]] = [
        ("Gemini", bool(settings.gemini_api_key), _gemini_completion),
        ("Anthropic", bool(settings.anthropic_api_key), _anthropic_completion),
        ("OpenAI", bool(settings.openai_api_key), _openai_completion),
    ]
    configured = [(name, fn) for name, is_configured, fn in candidates if is_configured]
    if not configured:
        raise RuntimeError(
            "None of GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY is configured; "
            f"{purpose} is unavailable"
        )

    for i, (name, completion_fn) in enumerate(configured):
        try:
            return await completion_fn(system_prompt, user_prompt, json_mode=json_mode)
        except _PROVIDER_ERRORS as exc:
            if i == len(configured) - 1:
                raise RuntimeError(f"{name} {purpose} failed: {exc}") from exc
            next_name = configured[i + 1][0]
            logger.warning("%s %s failed, falling back to %s: %s", name, purpose, next_name, exc)

    raise AssertionError("unreachable: configured is non-empty and every branch returns or raises")


async def generate_analysis_json(system_prompt: str, user_prompt: str) -> str:
    """Runs the report-generation completion and returns the raw JSON text.

    Gemini is preferred when GEMINI_API_KEY is configured, then Anthropic,
    then OpenAI -- each only tried if configured, falling through to the
    next on failure. All providers get the exact same prompts; only the
    transport differs, so the caller's JSON parsing and validation stays
    provider-agnostic.
    """
    return await _generate_with_fallback(
        system_prompt, user_prompt, json_mode=True, purpose="report generation"
    )


async def generate_text(system_prompt: str, user_prompt: str) -> str:
    """Same Gemini > Anthropic > OpenAI selection as generate_analysis_json,
    but without forcing a JSON response -- for free-text narrative
    generation (e.g. the AI Researcher's daily note) rather than a report
    that must parse as a fixed JSON schema.
    """
    return await _generate_with_fallback(
        system_prompt, user_prompt, json_mode=False, purpose="text generation"
    )
