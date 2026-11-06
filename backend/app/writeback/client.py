from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx2 as httpx  # the HTTP client the Anthropic SDK and TestClient use too

from app.core.config import get_settings


class CmUnavailableError(RuntimeError):
    """The CM platform did not answer usefully (down, timeout, 5xx). Safe to retry."""


@dataclass(frozen=True)
class WriteResult:
    status: str  # created | duplicate | conflict
    version: int | None
    current: dict[str, Any] | None = None  # the CM record, on conflict


class CmClient:
    def __init__(self, http: httpx.Client) -> None:
        self.http = http

    def _call(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self.http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise CmUnavailableError(f"{type(exc).__name__}: {exc}") from exc
        if response.status_code >= 500:
            raise CmUnavailableError(f"CM platform returned {response.status_code}")
        return response

    def record_version(self, member_id: str) -> int:
        response = self._call("GET", f"/members/{member_id}/record")
        response.raise_for_status()
        version: int = response.json()["version"]
        return version

    def write(
        self, member_id: str, idempotency_key: str, payload: dict[str, Any], if_match: int | None
    ) -> WriteResult:
        headers = {"If-Match": str(if_match)} if if_match is not None else {}
        response = self._call(
            "PUT", f"/members/{member_id}/entries/{idempotency_key}", json=payload, headers=headers
        )
        body = response.json()
        if response.status_code == 409:
            return WriteResult("conflict", body["current"]["version"], body["current"])
        response.raise_for_status()
        return WriteResult(body["status"], body["version"])


INPROCESS = "inprocess"


@lru_cache
def _inprocess_mock_cm() -> httpx.Client:
    """The mock CM platform served inside this process (one serverless function, no second
    server). Its records live next to the demo database."""
    from fastapi.testclient import TestClient

    from mock_cm.app import create_app

    data_dir = get_settings().data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{(data_dir / 'mock_cm.db').as_posix()}"
    return TestClient(create_app(url), base_url="http://mock-cm.inprocess")


def get_cm_client() -> CmClient:
    """FastAPI dependency; tests override it with an in-process mock CM.

    MOCK_CM_URL=inprocess runs the mock CM platform inside the API process (Vercel deploys)."""
    url = get_settings().mock_cm_url
    if url == INPROCESS:
        return CmClient(_inprocess_mock_cm())
    return CmClient(httpx.Client(base_url=url, timeout=5.0))
