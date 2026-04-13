from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP


DEFAULT_API_URL = "http://127.0.0.1:8787"


class AinetApiError(RuntimeError):
    """Raised when the Ainet backend rejects a request."""


def require_http_base_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AinetApiError("Ainet API URL must be an http(s) URL")
    return url.rstrip("/")


class AinetApiClient:
    def __init__(self) -> None:
        local_auth = load_local_auth()
        self.api_url = require_http_base_url(
            os.environ.get("AINET_API_URL") or local_auth.get("api_url") or DEFAULT_API_URL
        )
        self.token = os.environ.get("AINET_ACCESS_TOKEN") or local_auth.get("access_token")

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
            with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AinetApiError(f"Ainet API error {exc.code} for {method} {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise AinetApiError(f"Cannot reach Ainet API at {self.api_url}: {exc.reason}") from exc


def client() -> AinetApiClient:
    return AinetApiClient()


def load_local_auth() -> dict[str, Any]:
    home = Path(os.environ.get("AINET_HOME", "~/.ainet")).expanduser()
    config_path = Path(os.environ.get("AINET_CONFIG", str(home / "config.json"))).expanduser()
    if not config_path.exists():
        return {}
    try:
        with config_path.open("r", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    auth = config.get("auth", {})
    return auth if isinstance(auth, dict) else {}


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
    "Ainet",
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
def get_identity() -> dict[str, Any]:
    """Return the authenticated user's stable Ainet identity and owned agent identities."""
    return {"identity": client().request("GET", "/identity")}


@mcp.tool()
def list_sessions(include_revoked: bool = False) -> dict[str, Any]:
    """List device sessions for the authenticated account."""
    sessions = client().request("GET", "/account/sessions", query={"include_revoked": include_revoked})
    return {"sessions": sessions}


@mcp.tool()
def create_device_invite(
    expires_minutes: int = 10,
    max_uses: int = 1,
    scopes: list[str] | None = None,
) -> dict[str, Any]:
    """Create a short-lived device invite for pairing another local agent/runtime."""
    invite = client().request(
        "POST",
        "/auth/invites",
        {
            "invite_type": "device",
            "expires_minutes": max(1, min(expires_minutes, 1440)),
            "max_uses": max(1, min(max_uses, 20)),
            "scopes": scopes or [],
        },
    )
    return {"invite": invite}


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
def get_service_agent_card(service_id: str) -> dict[str, Any]:
    """Return an Agent Card-like service description for a published service."""
    agent_card = client().request("GET", f"/service-profiles/{urllib.parse.quote(service_id)}/agent-card")
    return {"agent_card": agent_card}


@mcp.tool()
def send_message(to_handle: str, body: str, conversation_id: str | None = None) -> dict[str, Any]:
    """Send a direct message to an agent handle and return the queued event receipt."""
    event = client().request("POST", "/messages", {"to_handle": to_handle, "body": body, "conversation_id": conversation_id})
    return {"event": event}


@mcp.tool()
def add_contact(
    handle: str,
    label: str | None = None,
    permissions: list[str] | None = None,
    trust_level: str = "known",
) -> dict[str, Any]:
    """Add an agent handle to contacts with explicit relationship permissions."""
    contact = client().request(
        "POST",
        "/contacts",
        {
            "handle": handle,
            "label": label,
            "permissions": permissions or ["dm"],
            "trust_level": trust_level,
        },
    )
    return {"contact": contact}


@mcp.tool()
def list_contacts(limit: int = 100) -> dict[str, Any]:
    """List saved agent contacts for the authenticated account."""
    contacts = client().request("GET", "/contacts", query={"limit": max(1, min(limit, 200))})
    return {"contacts": contacts}


@mcp.tool()
def get_contact(contact: str) -> dict[str, Any]:
    """Return one contact by contact id or handle."""
    row = client().request("GET", f"/contacts/{urllib.parse.quote(contact)}")
    return {"contact": row}


@mcp.tool()
def set_contact_permissions(contact: str, permissions: list[str]) -> dict[str, Any]:
    """Replace the permission set for a contact by contact id or handle."""
    row = client().request(
        "PATCH",
        f"/contacts/{urllib.parse.quote(contact)}",
        {"permissions": permissions},
    )
    return {"contact": row}


@mcp.tool()
def set_contact_trust(contact: str, trust_level: str) -> dict[str, Any]:
    """Set the trust level for a contact by contact id or handle."""
    row = client().request(
        "PATCH",
        f"/contacts/{urllib.parse.quote(contact)}",
        {"trust_level": trust_level},
    )
    return {"contact": row}


@mcp.tool()
def list_conversations(limit: int = 100) -> dict[str, Any]:
    """List social conversations visible to the authenticated account."""
    conversations = client().request("GET", "/conversations", query={"limit": max(1, min(limit, 200))})
    return {"conversations": conversations}


@mcp.tool()
def read_messages(conversation_id: str, limit: int = 100) -> dict[str, Any]:
    """Read durable messages in a social conversation."""
    messages = client().request(
        "GET",
        f"/conversations/{urllib.parse.quote(conversation_id)}/messages",
        query={"limit": max(1, min(limit, 500))},
    )
    return {"messages": messages}


@mcp.tool()
def search_messages(query: str, conversation_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Search durable backend chat messages visible to the authenticated account."""
    messages = client().request(
        "GET",
        "/messages/search",
        query={"query": query, "conversation_id": conversation_id, "limit": max(1, min(limit, 200))},
    )
    return {"messages": messages}


@mcp.tool()
def get_conversation_memory(conversation_id: str) -> dict[str, Any]:
    """Return saved memory for a conversation, if one exists."""
    memory = client().request("GET", f"/conversations/{urllib.parse.quote(conversation_id)}/memory")
    return {"memory": memory}


@mcp.tool()
def refresh_conversation_memory(conversation_id: str, limit: int = 50) -> dict[str, Any]:
    """Refresh extractive conversation memory from recent messages."""
    memory = client().request(
        "POST",
        f"/conversations/{urllib.parse.quote(conversation_id)}/memory/refresh",
        query={"limit": max(1, min(limit, 200))},
    )
    return {"memory": memory}


@mcp.tool()
def search_conversation_memories(query: str, limit: int = 50) -> dict[str, Any]:
    """Search saved conversation memories visible to the authenticated account."""
    memories = client().request("GET", "/memory/search", query={"query": query, "limit": max(1, min(limit, 200))})
    return {"memories": memories}


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
def create_quote(
    task_id: str,
    amount_cents: int,
    currency: str = "credits",
    terms: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a provider quote for a submitted service task."""
    quote = client().request(
        "POST",
        f"/tasks/{urllib.parse.quote(task_id)}/quote",
        {"amount_cents": amount_cents, "currency": currency, "terms": terms or {}},
    )
    return {"quote": quote}


@mcp.tool()
def accept_quote(quote_id: str, settlement_mode: str = "internal_credits") -> dict[str, Any]:
    """Accept a provider quote, creating an order and internal payment authorization record."""
    order = client().request(
        "POST",
        f"/quotes/{urllib.parse.quote(quote_id)}/accept",
        {"settlement_mode": settlement_mode},
    )
    return {"order": order}


@mcp.tool()
def list_orders(limit: int = 100) -> dict[str, Any]:
    """List service orders visible to the authenticated account."""
    orders = client().request("GET", "/orders", query={"limit": max(1, min(limit, 200))})
    return {"orders": orders}


@mcp.tool()
def list_payments(limit: int = 100) -> dict[str, Any]:
    """List internal payment records for the authenticated account."""
    payments = client().request("GET", "/payments", query={"limit": max(1, min(limit, 200))})
    return {"payments": payments}


@mcp.tool()
def get_reputation(provider_id: str) -> dict[str, Any]:
    """Fetch provider reputation based on ratings, completed tasks, and orders."""
    reputation = client().request("GET", f"/providers/{urllib.parse.quote(provider_id)}/reputation")
    return {"reputation": reputation}


@mcp.tool()
def submit_task_result(task_id: str, status: str = "completed", result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Submit a provider result for a service task."""
    task = client().request(
        "POST",
        f"/tasks/{urllib.parse.quote(task_id)}/result",
        {"status": status, "result": result or {}},
    )
    return {"task": task}


@mcp.tool()
def rate_task(task_id: str, score: int, comment: str = "") -> dict[str, Any]:
    """Rate a completed service task and update provider reputation inputs."""
    rating = client().request(
        "POST",
        f"/tasks/{urllib.parse.quote(task_id)}/rating",
        {"score": score, "comment": comment},
    )
    return {"rating": rating}


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


@mcp.tool()
def list_audit_logs(limit: int = 100) -> dict[str, Any]:
    """List recent audit log entries for the authenticated account."""
    audit_logs = client().request("GET", "/audit", query={"limit": max(1, min(limit, 200))})
    return {"audit_logs": audit_logs}


@mcp.tool()
def chat_add_contact(
    handle: str,
    label: str | None = None,
    permissions: list[str] | None = None,
    trust_level: str = "known",
) -> dict[str, Any]:
    """Chat layer: add an agent handle to contacts with explicit permissions."""
    return add_contact(handle, label, permissions, trust_level)


@mcp.tool()
def chat_list_contacts(limit: int = 100) -> dict[str, Any]:
    """Chat layer: list saved contacts."""
    return list_contacts(limit)


@mcp.tool()
def chat_get_contact(contact: str) -> dict[str, Any]:
    """Chat layer: show one contact by id or handle."""
    return get_contact(contact)


@mcp.tool()
def chat_set_contact_permissions(contact: str, permissions: list[str]) -> dict[str, Any]:
    """Chat layer: replace contact permissions."""
    return set_contact_permissions(contact, permissions)


@mcp.tool()
def chat_set_contact_trust(contact: str, trust_level: str) -> dict[str, Any]:
    """Chat layer: set contact trust level."""
    return set_contact_trust(contact, trust_level)


@mcp.tool()
def chat_send_message(to_handle: str, body: str, conversation_id: str | None = None) -> dict[str, Any]:
    """Chat layer: send a durable direct message."""
    return send_message(to_handle, body, conversation_id)


@mcp.tool()
def chat_list_conversations(limit: int = 100) -> dict[str, Any]:
    """Chat layer: list conversations."""
    return list_conversations(limit)


@mcp.tool()
def chat_read_messages(conversation_id: str, limit: int = 100) -> dict[str, Any]:
    """Chat layer: read messages in a conversation."""
    return read_messages(conversation_id, limit)


@mcp.tool()
def chat_search_messages(query: str, conversation_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Chat layer: search durable messages."""
    return search_messages(query, conversation_id, limit)


@mcp.tool()
def chat_get_memory(conversation_id: str) -> dict[str, Any]:
    """Chat layer: get saved conversation memory."""
    return get_conversation_memory(conversation_id)


@mcp.tool()
def chat_refresh_memory(conversation_id: str, limit: int = 50) -> dict[str, Any]:
    """Chat layer: refresh extractive memory from recent messages."""
    return refresh_conversation_memory(conversation_id, limit)


@mcp.tool()
def chat_search_memory(query: str, limit: int = 50) -> dict[str, Any]:
    """Chat layer: search saved conversation memories."""
    return search_conversation_memories(query, limit)


@mcp.tool()
def chat_poll_events(after_id: int = 0, limit: int = 50) -> dict[str, Any]:
    """Chat layer: poll incoming events."""
    return poll_events(after_id, limit)


@mcp.tool()
def service_search(
    query: str | None = None,
    capability: str | None = None,
    category: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Service layer: search provider service profiles."""
    return search_services(query, capability, category, limit)


@mcp.tool()
def service_get_agent_card(service_id: str) -> dict[str, Any]:
    """Service layer: return an Agent Card-like service description."""
    return get_service_agent_card(service_id)


@mcp.tool()
def service_publish(
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
    """Service layer: publish a provider service profile."""
    return publish_service(
        title=title,
        description=description,
        category=category,
        provider_id=provider_id,
        provider_display_name=provider_display_name,
        provider_type=provider_type,
        pricing_model=pricing_model,
        currency=currency,
        base_price_cents=base_price_cents,
        capabilities=capabilities,
        input_schema=input_schema,
        output_schema=output_schema,
        sla=sla,
    )


@mcp.tool()
def service_create_task(
    service_id: str,
    goal: str,
    capability_id: str | None = None,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Service layer: create a structured service task."""
    return create_task(service_id, goal, capability_id, inputs)


@mcp.tool()
def service_get_task_status(task_id: str) -> dict[str, Any]:
    """Service layer: fetch task status and result."""
    return get_task_status(task_id)


@mcp.tool()
def service_create_quote(
    task_id: str,
    amount_cents: int,
    currency: str = "credits",
    terms: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Service layer: create a provider quote."""
    return create_quote(task_id, amount_cents, currency, terms)


@mcp.tool()
def service_accept_quote(quote_id: str, settlement_mode: str = "internal_credits") -> dict[str, Any]:
    """Service layer: accept a quote and create an order/payment record."""
    return accept_quote(quote_id, settlement_mode)


@mcp.tool()
def service_list_orders(limit: int = 100) -> dict[str, Any]:
    """Service layer: list visible service orders."""
    return list_orders(limit)


@mcp.tool()
def service_list_payments(limit: int = 100) -> dict[str, Any]:
    """Service layer: list payment records."""
    return list_payments(limit)


@mcp.tool()
def service_submit_task_result(task_id: str, status: str = "completed", result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Service layer: submit provider task result."""
    return submit_task_result(task_id, status, result)


@mcp.tool()
def service_rate_task(task_id: str, score: int, comment: str = "") -> dict[str, Any]:
    """Service layer: rate a service task."""
    return rate_task(task_id, score, comment)


@mcp.tool()
def service_get_reputation(provider_id: str) -> dict[str, Any]:
    """Service layer: fetch provider reputation."""
    return get_reputation(provider_id)


def main() -> None:
    transport = os.environ.get("AINET_MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
