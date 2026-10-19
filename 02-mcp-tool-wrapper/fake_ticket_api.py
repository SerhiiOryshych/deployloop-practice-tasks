"""In-process fake of an internal "ticket search" HTTP API. Do not edit.

It mimics one endpoint:  GET /v1/tickets/search?q=...&status=...&limit=...
    200 {"total": int, "results": [ticket, ...]}
    401 when the Authorization header is not `Bearer <VALID_TOKEN>`

Failure modes are switched on with constructor arguments. A call looks like an
HTTP client call: `await api.request("GET", path, params=..., headers=...)`.
Every call is recorded in `api.calls`.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

VALID_TOKEN = "tok_test_example_0000"  # fake value used only by the tests
VALID_AUTH = f"Bearer {VALID_TOKEN}"


@dataclass
class ApiResponse:
    status: int
    json: Any = None
    headers: dict[str, str] = field(default_factory=dict)


def make_ticket(i: int, **over: Any) -> dict[str, Any]:
    t = {
        "id": f"T-{1000 + i}",
        "title": f"Printer {i} jams on tray 2",
        "status": ["open", "pending", "closed"][i % 3],
        "priority": ["low", "normal", "high"][i % 3],
        "assignee": "dana@example.test",
        "updated_at": "2026-03-01T10:00:00Z",
        "body": f"User reports that printer {i} jams when printing double sided. Steps tried: restart.",
    }
    t.update(over)
    return t


class FakeTicketAPI:
    def __init__(
        self,
        tickets: list[dict[str, Any]] | None = None,
        *,
        delay: float = 0.0,
        force_status: int | None = None,  # answer every call with this status
        force_headers: dict[str, str] | None = None,
        force_body: Any = None,  # body used with force_status, or a bad 200 payload
        network_error: bool = False,
    ) -> None:
        self.tickets = tickets if tickets is not None else [make_ticket(i) for i in range(5)]
        self.delay = delay
        self.force_status = force_status
        self.force_headers = force_headers or {}
        self.force_body = force_body
        self.network_error = network_error
        self.calls: list[dict[str, Any]] = []

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> ApiResponse:
        headers = dict(headers or {})
        self.calls.append({"method": method, "path": path, "params": dict(params or {}), "headers": headers})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.network_error:
            # Real HTTP clients often put request details in the error text.
            raise ConnectionError(f"connection reset during {method} {path}; request headers={headers}")
        if self.force_status is not None:
            return ApiResponse(self.force_status, self.force_body, self.force_headers)
        if self.force_body is not None:
            return ApiResponse(200, self.force_body)
        auth = next((v for k, v in headers.items() if k.lower() == "authorization"), None)
        if auth != VALID_AUTH:
            return ApiResponse(401, {"error": "bad token"})
        p = params or {}
        q = str(p.get("q", "")).lower()
        hits = [
            t
            for t in self.tickets
            if (q in t["title"].lower() or q in t["body"].lower())
            and ("status" not in p or t["status"] == p["status"])
        ]
        limit = int(p.get("limit", 10))
        return ApiResponse(200, {"total": len(hits), "results": hits[:limit]})
