"""The drafting model behind a small interface, so tests run with no network.

AnthropicDraftModel uses the official Anthropic SDK. Model and key come from settings (env); the
call has a 20 s timeout and no retries, so 20 s is the real limit. Every failure (timeout,
network, API error, refusal, truncated or non-JSON output) becomes DraftUnavailableError, and
the nurse writes the note as normal.
"""

from dataclasses import dataclass
from typing import Any, Protocol

import anthropic

from app.core.config import get_settings

MAX_TOKENS = 8000  # adaptive thinking counts against this; the draft itself is short


class DraftUnavailableError(Exception):
    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail = kind, detail


@dataclass(frozen=True)
class ModelReply:
    text: str
    model: str
    request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class DraftModel(Protocol):
    name: str

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> ModelReply: ...


class AnthropicDraftModel:
    def __init__(
        self,
        model: str,
        timeout: float,
        api_key: str | None = None,
        http_client: anthropic.DefaultHttpxClient | None = None,
    ) -> None:
        self.name = model
        self.client = anthropic.Anthropic(
            api_key=api_key, timeout=timeout, max_retries=0, http_client=http_client
        )

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> ModelReply:
        try:
            response = self.client.beta.messages.create(
                model=self.name,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": schema},
                },
                # On a safety decline the API re-runs the request on a fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APITimeoutError as exc:
            raise DraftUnavailableError("timeout", str(exc)) from exc
        except anthropic.APIConnectionError as exc:
            raise DraftUnavailableError("connection", str(exc)) from exc
        except anthropic.RateLimitError as exc:
            raise DraftUnavailableError("rate_limited", str(exc)) from exc
        except anthropic.APIStatusError as exc:
            raise DraftUnavailableError(f"api_error_{exc.status_code}", exc.message) from exc
        except TypeError as exc:  # the SDK found no API key or credential profile
            if "authentication" not in str(exc):
                raise
            raise DraftUnavailableError("not_configured", str(exc)) from exc

        if response.stop_reason == "refusal":
            raise DraftUnavailableError("refusal", "the model declined to draft this call")
        if response.stop_reason == "max_tokens":
            raise DraftUnavailableError("truncated", "the draft hit the token limit")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise DraftUnavailableError("invalid_output", "no text in the response")
        return ModelReply(
            text=text,
            model=response.model,
            request_id=response._request_id,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )


class SimulatedTimeoutModel:
    """Demo operator toggle "Make the AI draft time out": behaves as a call that hit 20 s."""

    def __init__(self, name: str) -> None:
        self.name = name

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> ModelReply:
        raise DraftUnavailableError("timeout", "simulated by the demo operator panel")


def get_draft_model() -> DraftModel:
    settings = get_settings()
    if settings.demo_mode:
        from app.demo.state import load_state  # demo only

        if load_state(settings).ai_timeout:
            return SimulatedTimeoutModel(settings.ai_draft_model)
    key = settings.anthropic_api_key
    return AnthropicDraftModel(
        settings.ai_draft_model,
        settings.ai_draft_timeout_seconds,
        api_key=(key.get_secret_value() or None) if key else None,
    )
