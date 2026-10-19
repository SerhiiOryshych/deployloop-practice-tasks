"""MCP-style wrapper around the internal ticket search API - STARTER.

The protocol shape (no SDK, plain dicts), modelled on MCP `tools/list` and
`tools/call`:

    tool.list_tools() -> {"tools": [{"name", "description", "inputSchema", "outputSchema"}]}

    await tool.call_tool(name, arguments, headers=None) -> result dict

  success: {"isError": False,
            "content": [{"type": "text", "text": "..."}],
            "structuredContent": {...matches outputSchema...}}
  failure: {"isError": True,
            "content": [{"type": "text", "text": "<same message>"}],
            "structuredContent": {"error": {"code", "message", "retryable", ...}}}

`headers` are the caller's HTTP headers. The tool forwards the credentials to the
upstream API; see README.md for the full brief. It works on a happy path today.
It is incomplete and has bugs. Make `pytest` pass without editing tests/ or
fake_ticket_api.py. Allowed dependency: jsonschema.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping

log = logging.getLogger("ticket_tool")

# TODO(candidate): make the input schema strict (bounds, enum, no extra keys, ...).
INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "status": {"type": "string"},
        "limit": {"type": "integer"},
    },
}

# TODO(candidate): describe the real output (see README for the shape).
OUTPUT_SCHEMA: dict[str, Any] = {"type": "object"}


class TicketSearchTool:
    def __init__(self, api, *, timeout_s: float = 2.0, max_output_chars: int = 6000, logger=None):
        self.api = api
        self.timeout_s = timeout_s
        self.max_output_chars = max_output_chars
        self.log = logger or log

    def list_tools(self) -> dict[str, Any]:
        return {
            "tools": [
                {
                    "name": "search_tickets",
                    "description": "Search support tickets by text.",
                    "inputSchema": INPUT_SCHEMA,
                    "outputSchema": OUTPUT_SCHEMA,
                }
            ]
        }

    async def call_tool(
        self, name: str, arguments: Any, headers: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        headers = dict(headers or {})
        self.log.info("call_tool name=%s arguments=%s headers=%s", name, arguments, headers)
        if name != "search_tickets":
            raise KeyError(name)  # TODO(candidate): structured error instead

        # TODO(candidate): strict validation against INPUT_SCHEMA; apply default limit=10.
        if "query" not in arguments:
            raise ValueError("query is required")
        params = {"q": arguments["query"], "limit": arguments.get("limit", 10)}
        if "status" in arguments:
            params["status"] = arguments["status"]

        # TODO(candidate): forward only the headers the upstream needs.
        # TODO(candidate): enforce self.timeout_s.
        try:
            resp = await self.api.request("GET", "/v1/tickets/search", params=params, headers=headers)
        except Exception as exc:
            self.log.error("upstream call failed: %s", exc)
            raise
        # TODO(candidate): map 401/403/429/5xx and bad payloads to structured tool errors.
        data = resp.json

        # TODO(candidate): cap size; treat ticket text as untrusted data.
        tickets = [
            {
                "id": t["id"],
                "title": t["title"],
                "status": t["status"],
                "priority": t["priority"],
                "updated_at": t["updated_at"],
                "snippet": t["body"],
            }
            for t in data["results"]
        ]
        structured = {"total_matches": data["total"], "returned": len(tickets), "truncated": False, "tickets": tickets}
        text = "\n".join(f"{t['id']} [{t['status']}] {t['title']}: {t['snippet']}" for t in tickets)
        return {"isError": False, "content": [{"type": "text", "text": text}], "structuredContent": structured}
