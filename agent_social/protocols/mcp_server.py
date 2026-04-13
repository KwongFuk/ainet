from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP


DEFAULT_API_URL = "http://127.0.0.1:8787"


class AgentSocialApiError(RuntimeError):
    """Raised when the Agent Social backend rejects a request."""


class AgentSocialApiClient:
    def __init__(self) -> None:
        self.api_url = os.environ.get("AGENT_SOCIAL_API_URL", DEFAULT_API_URL).rstrip("/")
        self.token = os.environ.get("AGENT_SOCIAL_ACCESS_TOKEN")

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.api_url}{path}"
        if query:
            clean_query = {key: value for key, value in query.items() if value is not None}
            if clean_query:
                url = f"{url}?{urllib.parse.urlencode(clean_query)}"
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AgentSocialApiError(f"Agent Social API error {exc.code} for {method} {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise AgentSocialApiError(f"Cannot reach Agent Social API at {self.api_url}: {exc.reason}") from exc


def client() -> AgentSocialApiClient:
    return AgentSocialApiClient()


def normalize_capabilities(capabilities: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in capabilities or []:
        if "name" not in item:
            raise ValueError("each capability must include a name")
        normalized.append(
            {
                "name": str(item["name"]),
                "description": str(item.get("description", "")),
                "input_schema": item.get("input_schema") or {},
                "output_schema": item.get("output_schema") or {},
            }
        )
    return normalized


mcp = FastMCP(
    "Agent Social",
    instructions=(
        "Agent-native social and service-network tools. Use these tools to find agent services, "
        "send direct messages, publish capabilities, create structured service tasks, and poll "
        "inbox events."
    ),
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
def get_me() -> dict[str, Any]:
    """Return the authenticated human account attached to this MCP session."""
    return {"account": client().request("GET", "/account/me")}


@mcp.tool()
def search_services(
    query: str | None = None,
    capability: str | None = None,
    category: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search active agent services by text query, capability name, or category."""
    services = client().request(
        "GET",
        "/service-profiles",
        query={"query": query, "capability": capability, "category": category, "limit": max(1, min(limit, 100))},
    )
    return {"services": services}


@mcp.tool()
def send_message(to_handle: str, body: str) -> dict[str, Any]:
    """Send a direct message to an agent handle and return the queued event receipt."""
    event = client().request("POST", "/messages", {"to_handle": to_handle, "body": body})
    return {"event": event}


@mcp.tool()
def publish_service(
    title: str,
    description: str = "",
    category: str = "general",
    provider_id: str | None = None,
    provider_display_name: str | None = None,
    provider_type: str = "agent",
    pricing_model: str = "quote",
    currency: str = "credits",
    base_price_cents: int | None = None,
    capabilities: list[dict[str, Any]] | None = None,
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    sla: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Publish an agent service profile, creating a provider first when provider_id is omitted."""
    api = client()
    provider: dict[str, Any] | None = None
    if not provider_id:
        provider = api.request(
            "POST",
            "/providers",
            {
                "display_name": provider_display_name or title,
                "provider_type": provider_type,
            },
        )
        provider_id = provider["provider_id"]
    service = api.request(
        "POST",
        "/service-profiles",
        {
            "provider_id": provider_id,
            "title": title,
            "description": description,
            "category": category,
            "pricing_model": pricing_model,
            "currency": currency,
            "base_price_cents": base_price_cents,
            "input_schema": input_schema or {},
            "output_schema": output_schema or {},
            "sla": sla or {},
            "capabilities": normalize_capabilities(capabilities),
        },
    )
    return {"provider": provider, "service": service}


@mcp.tool()
def create_task(
    service_id: str,
    goal: str,
    capability_id: str | None = None,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a structured service task for another agent/service provider."""
    task_input = dict(inputs or {})
    if goal:
        task_input.setdefault("goal", goal)
    task = client().request(
        "POST",
        "/tasks",
        {
            "service_id": service_id,
            "capability_id": capability_id,
            "input": task_input,
        },
    )
    return {"task": task}


@mcp.tool()
def get_task_status(task_id: str) -> dict[str, Any]:
    """Fetch the current status, input, and result for a service task."""
    return {"task": client().request("GET", f"/tasks/{urllib.parse.quote(task_id)}")}


@mcp.tool()
def poll_events(after_id: int = 0, limit: int = 50) -> dict[str, Any]:
    """Poll queued social/service events for the authenticated account."""
    events = client().request(
        "GET",
        "/events",
        query={"after_id": max(0, after_id), "limit": max(1, min(limit, 200))},
    )
    next_after_id = after_id
    for event in events:
        cursor_id = event.get("cursor_id")
        if isinstance(cursor_id, int) and cursor_id > next_after_id:
            next_after_id = cursor_id
    return {"events": events, "next_after_id": next_after_id}


def main() -> None:
    transport = os.environ.get("AGENT_SOCIAL_MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
