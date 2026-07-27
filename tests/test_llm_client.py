from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from anthropic import APIError
from google.genai import errors as genai_errors

from app.llm.client import (
    _anthropic_completion,
    _gemini_completion,
    _openai_completion,
    generate_analysis_json,
    generate_text,
)


def _settings(
    gemini_api_key: str | None = None,
    anthropic_api_key: str | None = None,
    openai_api_key: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        gemini_api_key=gemini_api_key,
        gemini_model="gemini-2.5-flash",
        anthropic_api_key=anthropic_api_key,
        anthropic_model="claude-sonnet-4-5-20250929",
        openai_api_key=openai_api_key,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
    )


def _api_error(message: str = "boom") -> APIError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return APIError(message, request, body=None)


def _genai_error(message: str = "boom") -> genai_errors.APIError:
    return genai_errors.ClientError(429, {"error": {"message": message}})


async def test_raises_when_no_provider_configured():
    with patch("app.llm.client.get_settings", return_value=_settings()):
        with pytest.raises(
            RuntimeError, match="None of GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY"
        ):
            await generate_analysis_json("system", "user")


async def test_generate_text_raises_when_no_provider_configured():
    with patch("app.llm.client.get_settings", return_value=_settings()):
        with pytest.raises(
            RuntimeError, match="None of GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY"
        ):
            await generate_text("system", "user")


async def test_uses_gemini_when_configured():
    with (
        patch(
            "app.llm.client.get_settings",
            return_value=_settings(gemini_api_key="gm-key", anthropic_api_key="claude-key"),
        ),
        patch(
            "app.llm.client._gemini_completion", new=AsyncMock(return_value='{"a": 1}')
        ) as gemini_call,
        patch("app.llm.client._anthropic_completion", new=AsyncMock()) as anthropic_call,
    ):
        result = await generate_analysis_json("system", "user")

    assert result == '{"a": 1}'
    gemini_call.assert_awaited_once_with("system", "user", json_mode=True)
    anthropic_call.assert_not_called()


async def test_uses_gemini_when_configured_for_text():
    with (
        patch("app.llm.client.get_settings", return_value=_settings(gemini_api_key="gm-key")),
        patch(
            "app.llm.client._gemini_completion", new=AsyncMock(return_value="hello")
        ) as gemini_call,
    ):
        result = await generate_text("system", "user")

    assert result == "hello"
    gemini_call.assert_awaited_once_with("system", "user", json_mode=False)


async def test_falls_back_to_anthropic_when_gemini_not_configured():
    with (
        patch(
            "app.llm.client.get_settings",
            return_value=_settings(anthropic_api_key="claude-key", openai_api_key="sk-openai"),
        ),
        patch(
            "app.llm.client._anthropic_completion", new=AsyncMock(return_value='{"b": 2}')
        ) as anthropic_call,
        patch("app.llm.client._openai_completion", new=AsyncMock()) as openai_call,
    ):
        result = await generate_analysis_json("system", "user")

    assert result == '{"b": 2}'
    anthropic_call.assert_awaited_once_with("system", "user", json_mode=True)
    openai_call.assert_not_called()


async def test_falls_back_to_openai_when_gemini_and_anthropic_not_configured():
    with (
        patch("app.llm.client.get_settings", return_value=_settings(openai_api_key="sk-openai")),
        patch(
            "app.llm.client._openai_completion", new=AsyncMock(return_value='{"c": 3}')
        ) as openai_call,
    ):
        result = await generate_analysis_json("system", "user")

    assert result == '{"c": 3}'
    openai_call.assert_awaited_once_with("system", "user", json_mode=True)


async def test_falls_back_to_anthropic_when_gemini_fails():
    with (
        patch(
            "app.llm.client.get_settings",
            return_value=_settings(gemini_api_key="gm-key", anthropic_api_key="claude-key"),
        ),
        patch("app.llm.client._gemini_completion", new=AsyncMock(side_effect=_genai_error())),
        patch(
            "app.llm.client._anthropic_completion", new=AsyncMock(return_value='{"fallback": 1}')
        ) as anthropic_call,
    ):
        result = await generate_analysis_json("system", "user")

    assert result == '{"fallback": 1}'
    anthropic_call.assert_awaited_once_with("system", "user", json_mode=True)


async def test_falls_back_to_openai_when_gemini_and_anthropic_both_fail():
    with (
        patch(
            "app.llm.client.get_settings",
            return_value=_settings(
                gemini_api_key="gm-key", anthropic_api_key="claude-key", openai_api_key="sk-openai"
            ),
        ),
        patch("app.llm.client._gemini_completion", new=AsyncMock(side_effect=_genai_error())),
        patch("app.llm.client._anthropic_completion", new=AsyncMock(side_effect=_api_error())),
        patch(
            "app.llm.client._openai_completion", new=AsyncMock(return_value='{"fallback": true}')
        ) as openai_call,
    ):
        result = await generate_analysis_json("system", "user")

    assert result == '{"fallback": true}'
    openai_call.assert_awaited_once_with("system", "user", json_mode=True)


async def test_raises_when_only_provider_fails():
    with (
        patch("app.llm.client.get_settings", return_value=_settings(gemini_api_key="gm-key")),
        patch(
            "app.llm.client._gemini_completion",
            new=AsyncMock(side_effect=_genai_error("rate limited")),
        ),
    ):
        with pytest.raises(RuntimeError, match="Gemini report generation failed"):
            await generate_analysis_json("system", "user")


async def test_raises_with_last_provider_name_when_all_configured_fail():
    with (
        patch(
            "app.llm.client.get_settings",
            return_value=_settings(
                gemini_api_key="gm-key", anthropic_api_key="claude-key", openai_api_key="sk-openai"
            ),
        ),
        patch("app.llm.client._gemini_completion", new=AsyncMock(side_effect=_genai_error())),
        patch("app.llm.client._anthropic_completion", new=AsyncMock(side_effect=_api_error())),
        patch(
            "app.llm.client._openai_completion",
            new=AsyncMock(side_effect=RuntimeError("insufficient_quota")),
        ),
    ):
        with pytest.raises(RuntimeError, match="OpenAI report generation failed"):
            await generate_analysis_json("system", "user")


async def test_generate_text_uses_openai_without_json_mode():
    with (
        patch("app.llm.client.get_settings", return_value=_settings(openai_api_key="sk-openai")),
        patch(
            "app.llm.client._openai_completion", new=AsyncMock(return_value="hello")
        ) as openai_call,
    ):
        result = await generate_text("system", "user")

    assert result == "hello"
    openai_call.assert_awaited_once_with("system", "user", json_mode=False)


async def test_anthropic_completion_raises_when_no_text_content():
    fake_response = SimpleNamespace(content=[], stop_reason="end_turn")
    fake_client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(return_value=fake_response))
    )
    with (
        patch(
            "app.llm.client.get_settings", return_value=_settings(anthropic_api_key="claude-key")
        ),
        patch("app.llm.client._get_anthropic_client", return_value=fake_client),
    ):
        with pytest.raises(RuntimeError, match="no text content.*end_turn"):
            await _anthropic_completion("system", "user")


def _fake_openai_response(content: str | None, finish_reason: str = "stop") -> SimpleNamespace:
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


async def test_openai_completion_raises_when_no_message_content():
    fake_response = _fake_openai_response(content=None, finish_reason="length")
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(return_value=fake_response))
        )
    )
    with (
        patch("app.llm.client.get_settings", return_value=_settings(openai_api_key="sk-openai")),
        patch("app.llm.client._get_openai_client", return_value=fake_client),
    ):
        with pytest.raises(RuntimeError, match="no message content.*length"):
            await _openai_completion("system", "user")


def _fake_gemini_response(text: str | None, finish_reason: str | None = "STOP") -> SimpleNamespace:
    candidate = SimpleNamespace(finish_reason=finish_reason)
    return SimpleNamespace(text=text, candidates=[candidate] if finish_reason else [])


async def test_gemini_completion_raises_when_no_text_content():
    fake_response = _fake_gemini_response(text="", finish_reason="MAX_TOKENS")
    fake_client = SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=AsyncMock(return_value=fake_response))
        )
    )
    with (
        patch("app.llm.client.get_settings", return_value=_settings(gemini_api_key="gm-key")),
        patch("app.llm.client._get_gemini_client", return_value=fake_client),
    ):
        with pytest.raises(RuntimeError, match="no text content.*MAX_TOKENS"):
            await _gemini_completion("system", "user")


async def test_gemini_completion_returns_text_when_present():
    fake_response = _fake_gemini_response(text="hello world")
    fake_client = SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=AsyncMock(return_value=fake_response))
        )
    )
    with (
        patch("app.llm.client.get_settings", return_value=_settings(gemini_api_key="gm-key")),
        patch("app.llm.client._get_gemini_client", return_value=fake_client),
    ):
        result = await _gemini_completion("system", "user")

    assert result == "hello world"
