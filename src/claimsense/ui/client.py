"""The case UI's client of the case API (routes and events: `src/claimsense/api/README.md`).

Server to server: the Streamlit process sends the reviewer's token, so the browser never holds
it. A refusal becomes `ApiError` with the API's own reason; a token is never part of one.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterable, Iterator
from typing import Any
from urllib.parse import quote

import httpx

Event = tuple[str, Any]
#: A run sends an event after each graph node; with real models one node can take minutes.
TIMEOUT = httpx.Timeout(10.0, read=300.0)


class ApiError(Exception):
    """The API refused a request (`status`, and its reason as `detail`), or was not reachable
    (`status` 0)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


def parse_sse(lines: Iterable[str]) -> Iterator[Event]:
    """(event, data) pairs from server-sent-event lines; comments and unnamed events are skipped."""
    name: str | None = None
    data: list[str] = []
    # Lazily, line by line, so each event shows as it arrives. The stream may end without the
    # blank line after its last event. Any other line (":" comments, keep-alives) carries nothing.
    for line in itertools.chain(lines, [""]):
        if not line:
            if name and data:
                yield name, json.loads("\n".join(data))
            name, data = None, []
        elif line.startswith("event:"):
            name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data.append(line[len("data:") :].removeprefix(" "))


class ApiClient:
    """One UI session's calls. `http` is any httpx client: `from_url` makes a real one; tests
    pass FastAPI's TestClient, which runs the API app in memory."""

    def __init__(self, http: httpx.Client) -> None:
        self.http = http

    @classmethod
    def from_url(cls, url: str) -> ApiClient:
        return cls(httpx.Client(base_url=url, timeout=TIMEOUT))

    @property
    def base_url(self) -> str:
        return str(self.http.base_url)

    def health(self) -> dict[str, Any]:
        return self._get("/health")

    def me(self, token: str) -> dict[str, str]:
        return self._get("/me", token)

    def demo_claims(self, token: str) -> list[dict[str, str]]:
        return self._get("/demo/claims", token)["claims"]

    def case(self, token: str, case_id: str) -> dict[str, Any]:
        return self._get(f"/claims/{quote(case_id, safe='')}", token)

    def metrics_text(self) -> str:
        return self._send("GET", "/metrics/").text

    def start_demo(self, token: str, claim_id: str, case_id: str | None = None) -> Iterator[Event]:
        path = f"/demo/claims/{quote(claim_id, safe='')}"
        return self._stream(path, token, params=_case(case_id))

    def start_packet(
        self, token: str, packet: dict[str, Any], case_id: str | None = None
    ) -> Iterator[Event]:
        return self._stream("/claims", token, json=packet, params=_case(case_id))

    def decide(self, token: str, case_id: str, body: dict[str, Any]) -> Iterator[Event]:
        return self._stream(f"/claims/{quote(case_id, safe='')}/decision", token, json=body)

    # ----------------------------------------------------------------------------- internals
    def _get(self, path: str, token: str | None = None) -> Any:
        return self._send("GET", path, token).json()

    def _send(self, method: str, path: str, token: str | None = None) -> httpx.Response:
        try:
            response = self.http.request(method, path, headers=_auth(token))
        except httpx.TransportError:
            raise ApiError(0, f"the API is not reachable at {self.base_url}") from None
        _check(response)
        return response

    def _stream(self, path: str, token: str, **kwargs: Any) -> Iterator[Event]:
        try:
            with self.http.stream("POST", path, headers=_auth(token), **kwargs) as response:
                if response.status_code >= 400:
                    response.read()
                    _check(response)
                yield from parse_sse(response.iter_lines())
        except httpx.TransportError:
            raise ApiError(0, f"the API is not reachable at {self.base_url}") from None


def _auth(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _case(case_id: str | None) -> dict[str, str] | None:
    return {"case_id": case_id} if case_id else None


def _check(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise ApiError(response.status_code, _detail(response))


def _detail(response: httpx.Response) -> str:
    """The API's reason in one line: FastAPI sends a string, or a list of validation errors."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return response.reason_phrase or "refused"
    if isinstance(detail, list):
        return "; ".join(
            str(item.get("msg", item)) if isinstance(item, dict) else str(item) for item in detail
        )
    return str(detail)
