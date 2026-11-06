"""AnthropicDraftModel through the real SDK, with a mock HTTP transport: no network."""

import json
from collections.abc import Callable, Iterator
from typing import Any

import anthropic
import httpx2
import pytest

from app.ai_draft import prompt
from app.ai_draft.client import AnthropicDraftModel, DraftUnavailableError, get_draft_model
from app.core.config import get_settings
from tests.ai_draft.helpers import RAYMOND_DRAFT

Handler = Callable[[httpx2.Request], httpx2.Response]


def message(text: str, stop_reason: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 900, "output_tokens": 250},
    }


def model_with(handler: Handler) -> AnthropicDraftModel:
    transport = httpx2.MockTransport(handler)
    return AnthropicDraftModel(
        "claude-opus-5-5",
        20.0,
        api_key="test-key-not-real",
        http_client=anthropic.DefaultHttpxClient(transport=transport),
    )


def complete(model: AnthropicDraftModel) -> Any:
    return model.complete(
        prompt.SYSTEM_PROMPT, "<transcript>...</transcript>", prompt.OUTPUT_SCHEMA
    )


def test_valid_json_comes_back_with_the_request_shaped_for_structured_output() -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json=message(json.dumps(RAYMOND_DRAFT)))

    reply = complete(model_with(handler))

    assert json.loads(reply.text) == RAYMOND_DRAFT
    assert (reply.input_tokens, reply.output_tokens) == (900, 250)
    (body,) = sent  # no retries
    assert body["model"] == "claude-opus-5-5"
    assert body["system"] == prompt.SYSTEM_PROMPT
    assert body["output_config"]["format"] == {
        "type": "json_schema",
        "schema": prompt.OUTPUT_SCHEMA,
    }


def test_a_timeout_is_a_graceful_unavailable_not_a_crash() -> None:
    calls = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        raise httpx2.ReadTimeout("model took longer than 20 s", request=request)

    with pytest.raises(DraftUnavailableError) as info:
        complete(model_with(handler))

    assert info.value.kind == "timeout"
    assert len(calls) == 1  # max_retries=0: 20 s is the real limit, not 20 s x 3


def test_client_timeout_is_twenty_seconds_without_retries() -> None:
    model = model_with(lambda r: httpx2.Response(200, json=message("{}")))
    assert model.client.timeout == 20.0 and model.client.max_retries == 0


def error(status: int, kind: str) -> httpx2.Response:
    return httpx2.Response(status, json={"type": "error", "error": {"type": kind, "message": "x"}})


@pytest.mark.parametrize(
    ("response", "kind"),
    [
        (error(500, "api_error"), "api_error_500"),
        (error(429, "rate_limit_error"), "rate_limited"),
        (httpx2.Response(200, json=message("", stop_reason="refusal")), "refusal"),
        (httpx2.Response(200, json=message('{"summary', stop_reason="max_tokens")), "truncated"),
    ],
)
def test_api_errors_refusals_and_truncation_are_unavailable(
    response: httpx2.Response, kind: str
) -> None:
    with pytest.raises(DraftUnavailableError) as info:
        complete(model_with(lambda r: response))
    assert info.value.kind == kind


@pytest.fixture
def env_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def test_model_and_timeout_come_from_the_environment(env_settings: pytest.MonkeyPatch) -> None:
    env_settings.setenv("AI_DRAFT_MODEL", "claude-sonnet-5-5")
    env_settings.setenv("ANTHROPIC_API_KEY", "test-key-from-env")

    model = get_draft_model()

    assert isinstance(model, AnthropicDraftModel)
    assert model.name == "claude-sonnet-5-5"
    assert model.client.api_key == "test-key-from-env" and model.client.timeout == 20.0
