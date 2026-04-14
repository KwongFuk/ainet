from __future__ import annotations

import argparse
import getpass
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_HOME = Path(os.environ.get("AINET_HOME", "~/.ainet")).expanduser()
DEFAULT_RELAY_URL = os.environ.get("AINET_RELAY_URL")
DEFAULT_RELAY_TOKEN = os.environ.get("AINET_RELAY_TOKEN")
DEFAULT_API_URL = os.environ.get("AINET_API_URL", "http://127.0.0.1:8787")
RUNTIME_ADAPTER_DEFAULTS = {
    "codex": {
        "runtime": "codex-cli",
        "profile": "codex",
        "handle_suffix": "codex",
        "capabilities": ["code_review", "patch_suggestion", "repo_assistant"],
    },
    "codex-cli": {
        "runtime": "codex-cli",
        "profile": "codex",
        "handle_suffix": "codex",
        "capabilities": ["code_review", "patch_suggestion", "repo_assistant"],
    },
    "openclaw": {
        "runtime": "openclaw",
        "profile": "openclaw",
        "handle_suffix": "openclaw",
        "capabilities": ["browser_task", "computer_use"],
    },
    "opclaw": {
        "runtime": "openclaw",
        "profile": "openclaw",
        "handle_suffix": "openclaw",
        "capabilities": ["browser_task", "computer_use"],
    },
}


def require_http_url(url: str, label: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit(f"{label} must be an http(s) URL")
    return url


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_name, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


@dataclass(frozen=True)
class Paths:
    home: Path
    relay_url: str | None = None
    relay_token: str | None = None

    @property
    def config(self) -> Path:
        return self.home / "config.json"

    @property
    def relay(self) -> Path:
        return Path(os.environ.get("AINET_RELAY", str(self.home / "relay.json"))).expanduser()


def default_config() -> dict[str, Any]:
    return {"version": 1, "active_profile": None, "profiles": {}, "auth": {}, "mcp": {}}


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    base = default_config()
    for key, value in base.items():
        config.setdefault(key, value)
    return config


def default_relay() -> dict[str, Any]:
    return {
        "version": 1,
        "accounts": {},
        "handles": {},
        "friend_requests": {},
        "friend_edges": {},
        "messages": {},
    }


def normalize_relay(relay: dict[str, Any]) -> dict[str, Any]:
    base = default_relay()
    for key, value in base.items():
        relay.setdefault(key, value)
    return relay


def load_config(paths: Paths) -> dict[str, Any]:
    return normalize_config(read_json(paths.config, default_config()))


def save_config(paths: Paths, config: dict[str, Any]) -> None:
    write_json_atomic(paths.config, config)


def load_relay(paths: Paths) -> dict[str, Any]:
    if paths.relay_url:
        return normalize_relay(http_json("GET", f"{paths.relay_url.rstrip('/')}/relay"))
    return normalize_relay(read_json(paths.relay, default_relay()))


def save_relay(paths: Paths, relay: dict[str, Any]) -> None:
    relay = normalize_relay(relay)
    if paths.relay_url:
        http_json("PUT", f"{paths.relay_url.rstrip('/')}/relay", relay)
        return
    write_json_atomic(paths.relay, relay)


def http_json(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    require_http_url(url, "relay URL")
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    token = os.environ.get("AINET_RELAY_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # nosec B310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"relay HTTP error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"cannot reach relay {url}: {exc}") from exc


def api_json(
    method: str,
    api_url: str,
    path: str,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    require_http_url(api_url, "API URL")
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{api_url.rstrip('/')}{path}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"api HTTP error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"cannot reach API {url}: {exc}") from exc


def print_backend_event(event: dict[str, Any]) -> None:
    event_type = event.get("event_type") or "event"
    cursor_id = event.get("cursor_id")
    payload = event.get("payload") or {}
    print(f"[{event_type}] cursor={cursor_id} payload={json.dumps(payload, sort_keys=True)}", flush=True)


def stream_backend_events(api_url: str, token: str, after_id: int, poll_seconds: float, once: bool) -> int:
    require_http_url(api_url, "API URL")
    query = urllib.parse.urlencode({"after_id": max(0, after_id), "poll_seconds": max(0.5, min(poll_seconds, 10.0))})
    url = f"{api_url.rstrip('/')}/events/stream?{query}"
    request = urllib.request.Request(url, headers={"Accept": "text/event-stream", "Authorization": f"Bearer {token}"}, method="GET")
    data_lines: list[str] = []
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310
            for raw in response:
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    if data_lines:
                        event = json.loads("\n".join(data_lines))
                        print_backend_event(event)
                        data_lines = []
                        if once:
                            return 0
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    data_lines.append(line.removeprefix("data:").strip())
    except KeyboardInterrupt:
        print("\nevent watch stopped")
        return 0
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"api HTTP error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"cannot reach API event stream {url}: {exc}") from exc
    return 0


def resolve_api_url(args: argparse.Namespace, config: dict[str, Any]) -> str:
    return (
        getattr(args, "api_url", None)
        or config.get("auth", {}).get("api_url")
        or os.environ.get("AINET_API_URL")
        or DEFAULT_API_URL
    )


def host_name() -> str:
    if os.environ.get("HOSTNAME"):
        return os.environ["HOSTNAME"]
    try:
        return os.uname().nodename
    except AttributeError:
        return "ainet-cli"


def default_adapter_handle(suffix: str) -> str:
    user = "".join(ch if ch.isalnum() else "-" for ch in getpass.getuser().lower()).strip("-") or "user"
    host = "".join(ch if ch.isalnum() else "-" for ch in host_name().split(".")[0].lower()).strip("-") or "host"
    return normalize_handle(f"{user}-{host}.{suffix}")


def normalize_handle(handle: str) -> str:
    normalized = handle.strip().lower()
    if not normalized:
        raise ValueError("handle cannot be empty")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789._-")
    if any(ch not in allowed for ch in normalized):
        raise ValueError("handle may only contain letters, digits, dot, underscore, and dash")
    return normalized


def cmd_auth_login(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url = resolve_api_url(args, config)
    email = args.email or input("email: ").strip()
    password = args.password or getpass.getpass("password: ")
    if not email or not password:
        raise SystemExit("email and password are required")
    response = api_json(
        "POST",
        api_url,
        "/auth/login",
        {
            "email": email,
            "password": password,
            "device_name": args.device_name or host_name(),
            "runtime_type": args.runtime_type,
        },
    )
    config["auth"] = {
        "api_url": api_url,
        "email": email.lower(),
        "access_token": response["access_token"],
        "token_type": response.get("token_type", "bearer"),
        "expires_at": response.get("expires_at"),
        "user_id": response.get("user_id"),
        "scopes": response.get("scopes", []),
        "logged_in_at": utc_now(),
    }
    save_config(paths, config)
    print(f"logged in {email.lower()} at {api_url}")
    print(f"user_id: {response.get('user_id')}")
    print(f"expires_at: {response.get('expires_at')}")
    print(f"auth saved: {paths.config}")
    return 0


def cmd_auth_signup(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url = resolve_api_url(args, config)
    email = args.email or input("email: ").strip()
    username = args.username or input("username: ").strip()
    password = args.password or getpass.getpass("password: ")
    if not args.password:
        confirm = getpass.getpass("confirm password: ")
        if password != confirm:
            raise SystemExit("passwords do not match")
    response = api_json(
        "POST",
        api_url,
        "/auth/signup",
        {
            "email": email,
            "username": username,
            "password": password,
        },
    )
    config.setdefault("auth", {})
    config["auth"]["api_url"] = api_url
    config["auth"]["email"] = email.lower()
    save_config(paths, config)
    print(f"signed up {email.lower()} at {api_url}")
    print(f"user_id: {response.get('user_id')}")
    if response.get("verification_required", True):
        print("verification required: run `ainet auth verify-email --email EMAIL --code CODE`")
    return 0


def cmd_auth_verify_email(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url = resolve_api_url(args, config)
    email = args.email or config.get("auth", {}).get("email") or input("email: ").strip()
    code = args.code or input("verification code: ").strip()
    if not email or not code:
        raise SystemExit("email and verification code are required")
    api_json("POST", api_url, "/auth/verify-email", {"email": email, "code": code})
    config.setdefault("auth", {})
    config["auth"]["api_url"] = api_url
    config["auth"]["email"] = email.lower()
    config["auth"]["email_verified_at"] = utc_now()
    save_config(paths, config)
    print(f"verified {email.lower()}")
    print("next: run `ainet auth login`")
    return 0


def cmd_auth_status(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    auth = config.get("auth", {})
    token = auth.get("access_token")
    if not token:
        print("not logged in")
        return 1
    api_url = resolve_api_url(args, config)
    print(f"api_url: {api_url}")
    print(f"email: {auth.get('email') or '-'}")
    print(f"user_id: {auth.get('user_id') or '-'}")
    print(f"expires_at: {auth.get('expires_at') or '-'}")
    if args.check:
        me = api_json("GET", api_url, "/account/me", token=token)
        print(f"server_user: {me.get('username')} <{me.get('email')}>")
        print(f"email_verified: {me.get('email_verified')}")
    return 0


def print_agent_identity(agent: dict[str, Any]) -> None:
    key = agent.get("key_id") or "-"
    verified = agent.get("verification_status") or "unverified"
    display_name = f" name={agent['display_name']}" if agent.get("display_name") else ""
    print(
        f"{agent['handle']} id={agent['agent_id']} runtime={agent['runtime_type']}"
        f"{display_name} key_id={key} verification={verified}"
    )


def cmd_identity_show(_args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    identity = api_json("GET", api_url, "/identity", token=token)
    user = identity.get("user", {})
    print(f"user: {user.get('username')} <{user.get('email')}> id={user.get('user_id')}")
    print(f"email_verified: {user.get('email_verified')}")
    print(f"active_sessions: {identity.get('session_count')}")
    agents = identity.get("agents") or []
    if not agents:
        print("agents: none")
        return 0
    print("agents:")
    for agent in agents:
        print("  ", end="")
        print_agent_identity(agent)
    return 0


def cmd_auth_logout(_args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    auth = config.get("auth", {})
    if not auth.get("access_token"):
        print("not logged in")
        return 0
    config["auth"] = {
        "api_url": auth.get("api_url"),
        "email": auth.get("email"),
        "logged_out_at": utc_now(),
    }
    save_config(paths, config)
    print("logged out locally")
    return 0


def save_auth_response(
    paths: Paths,
    config: dict[str, Any],
    api_url: str,
    response: dict[str, Any],
    email: str | None = None,
) -> None:
    existing = config.get("auth", {})
    config["auth"] = {
        "api_url": api_url,
        "email": email or existing.get("email"),
        "access_token": response["access_token"],
        "token_type": response.get("token_type", "bearer"),
        "expires_at": response.get("expires_at"),
        "user_id": response.get("user_id"),
        "scopes": response.get("scopes", []),
        "logged_in_at": utc_now(),
    }
    save_config(paths, config)


def cmd_auth_invite_create(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    response = api_json(
        "POST",
        api_url,
        "/auth/invites",
        {
            "invite_type": args.invite_type,
            "scopes": args.scope or [],
            "expires_minutes": args.expires_minutes,
            "max_uses": args.max_uses,
        },
        token=token,
    )
    print(f"invite_id: {response.get('invite_id')}")
    print(f"expires_at: {response.get('expires_at')}")
    print(f"max_uses: {response.get('max_uses')}")
    print(f"token: {response.get('token')}")
    return 0


def cmd_auth_invite_accept(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url = resolve_api_url(args, config)
    invite_token = args.token or getpass.getpass("invite token: ")
    response = api_json(
        "POST",
        api_url,
        "/auth/invites/accept",
        {
            "token": invite_token,
            "device_name": args.device_name or host_name(),
            "runtime_type": args.runtime_type,
        },
    )
    save_auth_response(paths, config, api_url, response)
    print(f"accepted invite at {api_url}")
    print(f"user_id: {response.get('user_id')}")
    print(f"expires_at: {response.get('expires_at')}")
    print(f"auth saved: {paths.config}")
    return 0


def cmd_auth_sessions(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    query = "?include_revoked=true" if args.include_revoked else ""
    sessions = api_json("GET", api_url, f"/account/sessions{query}", token=token)
    if not sessions:
        print("no sessions")
        return 0
    for session in sessions:
        revoked = f" revoked_at={session['revoked_at']}" if session.get("revoked_at") else ""
        scopes = ",".join(session.get("scopes", [])) or "-"
        print(
            f"{session['session_id']} device={session['device_name']} runtime={session['runtime_type']} "
            f"expires_at={session['expires_at']} scopes={scopes}{revoked}"
        )
    return 0


def cmd_auth_revoke_session(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    api_json("POST", api_url, f"/account/sessions/{args.session_id}/revoke", token=token)
    print(f"revoked session: {args.session_id}")
    return 0


def cmd_backend_events_watch(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    print(f"watching backend events from {api_url}; press Ctrl-C to stop", flush=True)
    return stream_backend_events(api_url, token, args.after_id, args.poll_seconds, args.once)


def cmd_chat_search(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    query = urllib.parse.urlencode(
        {
            "query": args.query,
            "limit": args.limit,
            **({"conversation_id": args.conversation_id} if args.conversation_id else {}),
        }
    )
    messages = api_json("GET", api_url, f"/messages/search?{query}", token=token)
    if not messages:
        print("no matching messages")
        return 0
    for message in messages:
        print(f"{message['created_at']} {message['from_handle']} -> {message['to_handle']} {message['message_id']}")
        print(f"  {message['body']}")
    return 0


def print_memory(memory: dict[str, Any] | None) -> None:
    if not memory:
        print("no memory saved")
        return
    print(f"memory_id: {memory.get('memory_id')}")
    print(f"conversation_id: {memory.get('conversation_id')}")
    print(f"title: {memory.get('title') or '-'}")
    print(f"pinned: {memory.get('pinned')}")
    print(f"updated_at: {memory.get('updated_at')}")
    facts = memory.get("key_facts") or []
    if facts:
        print("key_facts:")
        for fact in facts:
            print(f"  - {fact}")
    if memory.get("summary"):
        print("summary:")
        print(memory["summary"])


def cmd_chat_memory_get(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    memory = api_json("GET", api_url, f"/conversations/{args.conversation_id}/memory", token=token)
    print_memory(memory)
    return 0


def cmd_chat_memory_refresh(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    query = urllib.parse.urlencode({"limit": args.limit})
    memory = api_json("POST", api_url, f"/conversations/{args.conversation_id}/memory/refresh?{query}", token=token)
    print_memory(memory)
    return 0


def cmd_chat_memory_search(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    query = urllib.parse.urlencode({"query": args.query, "limit": args.limit})
    memories = api_json("GET", api_url, f"/memory/search?{query}", token=token)
    if not memories:
        print("no matching memories")
        return 0
    for memory in memories:
        print(f"{memory['conversation_id']} memory={memory['memory_id']} updated_at={memory['updated_at']}")
        print(f"  title: {memory.get('title') or '-'}")
        if memory.get("summary"):
            print(f"  summary: {memory['summary'][:240]}")
    return 0


def mcp_env(paths: Paths, api_url: str) -> dict[str, str]:
    return {
        "AINET_HOME": str(paths.home),
        "AINET_API_URL": api_url,
        "AINET_MCP_TRANSPORT": "stdio",
    }


def mcp_server_command(args: argparse.Namespace) -> str:
    return args.command or shutil.which("ainet-mcp") or "ainet-mcp"


def mcp_json_config(name: str, command: str, command_args: list[str], env: dict[str, str]) -> dict[str, Any]:
    return {"mcpServers": {name: {"command": command, "args": command_args, "env": env}}}


def cmd_mcp_install(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url = resolve_api_url(args, config)
    auth = config.get("auth", {})
    if args.require_auth and not auth.get("access_token"):
        raise SystemExit("not logged in. Run `ainet auth login` first.")
    name = args.name
    command = mcp_server_command(args)
    command_args = args.arg or []
    env = mcp_env(paths, api_url)

    written: list[str] = []
    target = args.target
    output = Path(args.output).expanduser() if args.output else paths.home / "mcp.json"
    write_json_atomic(output, mcp_json_config(name, command, command_args, env))
    written.append(str(output))

    config["mcp"] = {
        "server_name": name,
        "command": command,
        "args": command_args,
        "api_url": api_url,
        "target": target,
        "installed_at": utc_now(),
        "written": written,
    }
    save_config(paths, config)
    print(f"installed MCP server `{name}`")
    for path in written:
        print(f"wrote: {path}")
    print("token source: local Ainet auth config")
    return 0


def require_auth(config: dict[str, Any]) -> tuple[str, str]:
    auth = config.get("auth", {})
    api_url = auth.get("api_url") or DEFAULT_API_URL
    token = auth.get("access_token")
    if not token:
        raise SystemExit("not logged in. Run `ainet auth login` first.")
    return api_url, token


def spec_exists(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def print_check(label: str, state: str, detail: str) -> bool:
    marker = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}[state]
    print(f"[{marker}] {label}: {detail}")
    return state != "fail"


def sqlite_path_from_url(database_url: str) -> Path | None:
    if database_url == "sqlite:///:memory:":
        return None
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///")).expanduser()
    return None


def check_api_health(api_url: str) -> tuple[bool, str]:
    try:
        response = api_json("GET", api_url, "/health")
    except SystemExit as exc:
        return False, str(exc)
    return bool(response.get("ok")), json.dumps(response, sort_keys=True)


def cmd_server_doctor(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url = resolve_api_url(args, config)
    checks: list[bool] = []

    print("Ainet server doctor")
    checks.append(print_check("python", "ok" if sys.version_info >= (3, 10) else "fail", sys.version.split()[0]))

    dependency_modules = ["fastapi", "pydantic_settings", "sqlalchemy", "uvicorn"]
    missing = [module for module in dependency_modules if not spec_exists(module)]
    checks.append(
        print_check(
            "server dependencies",
            "fail" if missing else "ok",
            f"missing {', '.join(missing)}; run `pip install -e \".[server]\"`" if missing else "installed",
        )
    )
    checks.append(
        print_check(
            "mcp dependency",
            "ok" if spec_exists("mcp") else "warn",
            "installed" if spec_exists("mcp") else "missing; run `pip install -e \".[mcp]\"` if using MCP",
        )
    )

    home_parent = paths.home if paths.home.exists() else paths.home.parent
    checks.append(
        print_check(
            "home path",
            "ok" if home_parent.exists() and os.access(home_parent, os.W_OK) else "fail",
            str(paths.home),
        )
    )

    environment = os.environ.get("AINET_ENVIRONMENT", "development")
    jwt_secret = os.environ.get("AINET_JWT_SECRET", "dev-change-me")
    if environment.lower() in {"prod", "production"} and (jwt_secret == "dev-change-me" or len(jwt_secret) < 32):
        checks.append(print_check("production JWT secret", "fail", "set AINET_JWT_SECRET to at least 32 characters"))
    else:
        state = "warn" if jwt_secret == "dev-change-me" else "ok"
        checks.append(print_check("JWT secret", state, "development default" if state == "warn" else "configured"))

    database_url = os.environ.get("AINET_DATABASE_URL", "sqlite:///./ainet.db")
    sqlite_path = sqlite_path_from_url(database_url)
    if sqlite_path is None:
        checks.append(print_check("database", "ok", database_url.split("://", 1)[0]))
    else:
        db_parent = sqlite_path.parent if str(sqlite_path.parent) else Path(".")
        checks.append(
            print_check(
                "sqlite database",
                "ok" if db_parent.exists() and os.access(db_parent, os.W_OK) else "fail",
                str(sqlite_path),
            )
        )

    if args.check_api:
        ok, detail = check_api_health(api_url)
        checks.append(print_check("backend API", "ok" if ok else "fail", f"{api_url} {detail}"))
    else:
        checks.append(print_check("backend API", "warn", f"not checked; pass --check-api to probe {api_url}/health"))

    return 0 if all(checks) else 1


def cmd_server_status(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url = resolve_api_url(args, config)
    auth = config.get("auth", {})
    profiles = config.get("profiles", {})
    relay_exists = paths.relay.exists() if not paths.relay_url else False

    print("Ainet local status")
    print(f"home: {paths.home}")
    print(f"config: {paths.config} ({'exists' if paths.config.exists() else 'missing'})")
    print(f"api_url: {api_url}")
    print(f"auth: {'logged in' if auth.get('access_token') else 'not logged in'}")
    if auth.get("email"):
        print(f"email: {auth.get('email')}")
    if auth.get("expires_at"):
        print(f"token_expires_at: {auth.get('expires_at')}")
    print(f"active_profile: {config.get('active_profile') or '-'}")
    print(f"profiles: {len(profiles)}")
    for name, profile in sorted(profiles.items()):
        print(f"  - {name}: {profile.get('handle')} runtime={profile.get('runtime')}")

    if paths.relay_url:
        print(f"relay: {paths.relay_url}")
    else:
        print(f"relay: {paths.relay} ({'exists' if relay_exists else 'missing'})")
        if relay_exists:
            relay = load_relay(paths)
            print(f"relay_accounts: {len(relay.get('accounts', {}))}")
            print(f"relay_messages: {len(relay.get('messages', {}))}")

    ok, detail = check_api_health(api_url)
    print(f"backend_health: {'ok' if ok else 'unreachable'} ({detail})")
    if args.json:
        status = {
            "home": str(paths.home),
            "config_exists": paths.config.exists(),
            "api_url": api_url,
            "logged_in": bool(auth.get("access_token")),
            "active_profile": config.get("active_profile"),
            "profile_count": len(profiles),
            "relay": paths.relay_url or str(paths.relay),
            "backend_health": ok,
        }
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0


def cmd_server_bootstrap(_args: argparse.Namespace, _paths: Paths) -> int:
    print("Ainet server bootstrap is planned, but not implemented in this CLI yet.")
    print("Current supported commands:")
    print("  ainet server doctor")
    print("  ainet server status")
    print("  ainet-server")
    print("Next implementation target: generate Docker Compose + reverse proxy + database/search/object-storage config.")
    return 2


def cmd_agent_create(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    public_key = read_text_arg(args.public_key, args.public_key_file, "public key")
    payload = {
        "handle": normalize_handle(args.handle),
        "display_name": args.display_name,
        "runtime_type": args.runtime_type,
        "public_key": public_key,
        "key_id": args.key_id,
    }
    response = api_json("POST", api_url, "/agents", payload, token=token)
    profile_name = args.profile or config.get("active_profile") or response["handle"]
    profile = config["profiles"].get(profile_name, {})
    profile.update(
        {
            "profile": profile_name,
            "handle": response["handle"],
            "runtime": response["runtime_type"],
            "agent_id": response["agent_id"],
            "backend_api_url": api_url,
            "backend_created_at": utc_now(),
        }
    )
    config["profiles"][profile_name] = profile
    config["active_profile"] = profile_name
    save_config(paths, config)
    print(f"created backend agent `{response['handle']}`")
    print(f"agent_id: {response['agent_id']}")
    print(f"profile: {profile_name}")
    return 0


def adapter_defaults(runtime: str) -> dict[str, Any]:
    key = runtime.strip().lower()
    if key not in RUNTIME_ADAPTER_DEFAULTS:
        supported = ", ".join(sorted(RUNTIME_ADAPTER_DEFAULTS))
        raise SystemExit(f"unsupported adapter runtime: {runtime}. Supported: {supported}")
    return RUNTIME_ADAPTER_DEFAULTS[key]


def cmd_adapter_install(args: argparse.Namespace, paths: Paths) -> int:
    defaults = adapter_defaults(args.runtime)
    config = load_config(paths)
    profile_name = args.profile or defaults["profile"]
    handle = normalize_handle(args.handle or default_adapter_handle(defaults["handle_suffix"]))
    capabilities = sorted(set(args.capability or defaults["capabilities"]))
    profile = config["profiles"].get(profile_name, {})
    profile.update(
        {
            "profile": profile_name,
            "handle": handle,
            "runtime": defaults["runtime"],
            "owner": args.owner,
            "capabilities": capabilities,
            "account_id": profile.get("account_id"),
            "installed_at": utc_now(),
            "adapter_mode": "mcp",
            "adapter_runtime": args.runtime,
            "communication_only": True,
            "provides_model": False,
        }
    )
    config["profiles"][profile_name] = profile
    config["active_profile"] = profile_name
    if paths.relay_url:
        config["relay_url"] = paths.relay_url
    if paths.relay_token:
        config["relay_token"] = paths.relay_token
    save_config(paths, config)

    print(f"installed {args.runtime} adapter profile `{profile_name}`")
    print(f"handle: {handle}")
    print(f"runtime: {defaults['runtime']}")
    print(f"capabilities: {', '.join(capabilities)}")
    print("scope: communication only; training/inference resources belong to the later resource protocol")

    if args.register_relay:
        cmd_register(argparse.Namespace(profile=profile_name), paths)

    if args.backend_agent:
        api_url, token = require_auth(config)
        try:
            response = api_json(
                "POST",
                api_url,
                "/agents",
                {
                    "handle": handle,
                    "display_name": args.display_name,
                    "runtime_type": defaults["runtime"],
                },
                token=token,
            )
        except SystemExit as exc:
            if "409" not in str(exc):
                raise
            print(f"backend agent already exists for handle: {handle}")
        else:
            config = load_config(paths)
            profile = config["profiles"].get(profile_name, {})
            profile.update(
                {
                    "agent_id": response["agent_id"],
                    "backend_api_url": api_url,
                    "backend_created_at": utc_now(),
                }
            )
            config["profiles"][profile_name] = profile
            save_config(paths, config)
            print(f"backend agent_id: {response['agent_id']}")
    return 0


def read_text_arg(value: str | None, path: str | None, label: str) -> str | None:
    if value and path:
        raise SystemExit(f"pass either --{label.replace(' ', '-')} or --{label.replace(' ', '-')}-file, not both")
    if value:
        return value
    if path:
        return Path(path).expanduser().read_text(encoding="utf-8")
    return None


def cmd_agent_identity_update(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    public_key = read_text_arg(args.public_key, args.public_key_file, "public key")
    payload = {key: value for key, value in {"public_key": public_key, "key_id": args.key_id}.items() if value is not None}
    if not payload:
        raise SystemExit("nothing to update; pass --public-key, --public-key-file, or --key-id")
    agent = api_json("PATCH", api_url, f"/agents/{args.agent_id}/identity", payload, token=token)
    print_agent_identity(agent)
    return 0


def print_contact(contact: dict[str, Any]) -> None:
    permissions = ",".join(contact.get("permissions") or []) or "-"
    flags = []
    if contact.get("muted"):
        flags.append("muted")
    if contact.get("blocked"):
        flags.append("blocked")
    flag_suffix = f" flags={','.join(flags)}" if flags else ""
    label = f" label={contact['label']}" if contact.get("label") else ""
    print(
        f"{contact['handle']} id={contact['contact_id']} type={contact.get('contact_type')} "
        f"trust={contact.get('trust_level')} permissions={permissions}{label}{flag_suffix}"
    )


def cmd_contact_add(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    contact = api_json(
        "POST",
        api_url,
        "/contacts",
        {
            "handle": normalize_handle(args.handle),
            "label": args.label,
            "contact_type": args.contact_type,
            "trust_level": args.trust_level,
            "permissions": args.permission or ["dm"],
        },
        token=token,
    )
    print_contact(contact)
    return 0


def cmd_contact_list(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    contacts = api_json("GET", api_url, f"/contacts?{urllib.parse.urlencode({'limit': args.limit})}", token=token)
    if not contacts:
        print("no contacts")
        return 0
    for contact in contacts:
        print_contact(contact)
    return 0


def cmd_contact_show(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    contact = api_json("GET", api_url, f"/contacts/{urllib.parse.quote(args.contact)}", token=token)
    print_contact(contact)
    return 0


def cmd_contact_permissions(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    contact = api_json("GET", api_url, f"/contacts/{urllib.parse.quote(args.contact)}", token=token)
    permissions = set(contact.get("permissions") or [])
    changed = False
    if args.set_permission is not None:
        permissions = set(args.set_permission)
        changed = True
    for permission in args.add_permission or []:
        permissions.add(permission)
        changed = True
    for permission in args.remove_permission or []:
        permissions.discard(permission)
        changed = True
    if changed:
        contact = api_json(
            "PATCH",
            api_url,
            f"/contacts/{urllib.parse.quote(args.contact)}",
            {"permissions": sorted(permissions)},
            token=token,
        )
    print_contact(contact)
    return 0


def cmd_contact_trust(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    contact = api_json(
        "PATCH",
        api_url,
        f"/contacts/{urllib.parse.quote(args.contact)}",
        {"trust_level": args.trust_level},
        token=token,
    )
    print_contact(contact)
    return 0


def quote_path(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def print_group(group: dict[str, Any]) -> None:
    permissions = ",".join(group.get("default_permissions") or []) or "-"
    print(
        f"{group['handle']} id={group['group_id']} type={group.get('group_type')} "
        f"title={group.get('title')} permissions={permissions}"
    )


def print_group_member(member: dict[str, Any]) -> None:
    permissions = ",".join(member.get("permissions") or []) or "-"
    agent = f" agent_id={member['agent_id']}" if member.get("agent_id") else ""
    print(
        f"{member['handle']} member_id={member['member_id']} role={member.get('role')} "
        f"status={member.get('status')} permissions={permissions}{agent}"
    )


def print_group_message(message: dict[str, Any]) -> None:
    print(
        f"{message['created_at']} {message['from_handle']} "
        f"({message['message_type']}) {message['group_message_id']}"
    )
    print(f"  {message['body']}")


def print_group_memory(memory: dict[str, Any] | None) -> None:
    if not memory:
        print("no group memory saved")
        return
    print(f"group_memory_id: {memory.get('group_memory_id')}")
    print(f"group_id: {memory.get('group_id')}")
    print(f"title: {memory.get('title') or '-'}")
    print(f"pinned: {memory.get('pinned')}")
    print(f"updated_at: {memory.get('updated_at')}")
    facts = memory.get("key_facts") or []
    if facts:
        print("key_facts:")
        for fact in facts:
            print(f"  - {fact}")
    if memory.get("summary"):
        print("summary:")
        print(memory["summary"])


def cmd_group_create(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    group = api_json(
        "POST",
        api_url,
        "/groups",
        {
            "handle": normalize_handle(args.handle),
            "title": args.title,
            "description": args.description or "",
            "group_type": args.group_type,
            "permissions": args.permission or [],
        },
        token=token,
    )
    print_group(group)
    return 0


def cmd_group_list(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    groups = api_json("GET", api_url, f"/groups?{urllib.parse.urlencode({'limit': args.limit})}", token=token)
    if not groups:
        print("no groups")
        return 0
    for group in groups:
        print_group(group)
    return 0


def cmd_group_show(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    group = api_json("GET", api_url, f"/groups/{quote_path(args.group)}", token=token)
    print_group(group)
    return 0


def cmd_group_invite(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    member = api_json(
        "POST",
        api_url,
        f"/groups/{quote_path(args.group)}/members",
        {
            "handle": normalize_handle(args.handle),
            "role": args.role,
            "permissions": args.permission or [],
        },
        token=token,
    )
    print_group_member(member)
    return 0


def cmd_group_members(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    query = urllib.parse.urlencode({"limit": args.limit})
    members = api_json("GET", api_url, f"/groups/{quote_path(args.group)}/members?{query}", token=token)
    if not members:
        print("no group members")
        return 0
    for member in members:
        print_group_member(member)
    return 0


def cmd_group_send(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    body = " ".join(args.body).strip()
    if not body:
        raise SystemExit("message body cannot be empty")
    message = api_json(
        "POST",
        api_url,
        f"/groups/{quote_path(args.group)}/messages",
        {
            "body": body,
            "from_agent_id": args.from_agent_id,
            "message_type": args.message_type,
        },
        token=token,
    )
    print_group_message(message)
    return 0


def cmd_group_messages(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    query = urllib.parse.urlencode({"limit": args.limit})
    messages = api_json("GET", api_url, f"/groups/{quote_path(args.group)}/messages?{query}", token=token)
    if not messages:
        print("no group messages")
        return 0
    for message in messages:
        print_group_message(message)
    return 0


def cmd_group_memory_get(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    memory = api_json("GET", api_url, f"/groups/{quote_path(args.group)}/memory", token=token)
    print_group_memory(memory)
    return 0


def cmd_group_memory_refresh(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    query = urllib.parse.urlencode({"limit": args.limit})
    memory = api_json("POST", api_url, f"/groups/{quote_path(args.group)}/memory/refresh?{query}", token=token)
    print_group_memory(memory)
    return 0


def cmd_group_task_attach(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    context = api_json(
        "POST",
        api_url,
        f"/groups/{quote_path(args.group)}/tasks",
        {"task_id": args.task_id, "note": args.note or ""},
        token=token,
    )
    task = context.get("task") or {}
    print(f"attached task {context.get('task_id')} to {context.get('group_id')} context={context.get('context_id')}")
    if task:
        print(f"  status={task.get('status')} service_id={task.get('service_id')}")
    return 0


def cmd_group_tasks(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    query = urllib.parse.urlencode({"limit": args.limit})
    contexts = api_json("GET", api_url, f"/groups/{quote_path(args.group)}/tasks?{query}", token=token)
    if not contexts:
        print("no group tasks")
        return 0
    for context in contexts:
        task = context.get("task") or {}
        print(
            f"{context['context_id']} task={context['task_id']} status={task.get('status')} "
            f"service_id={task.get('service_id')} created_at={context.get('created_at')}"
        )
        if context.get("note"):
            print(f"  note: {context['note']}")
    return 0


def read_json_payload(value: str | None, path: str | None, label: str) -> dict[str, Any]:
    if value and path:
        raise SystemExit(f"pass either --{label}-json or --{label}-file, not both")
    raw = "{}"
    if value:
        raw = value
    elif path:
        raw = Path(path).expanduser().read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid {label} JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit(f"{label} JSON must be an object")
    return parsed


def print_need(need: dict[str, Any]) -> None:
    tags = ",".join(need.get("tags") or []) or "-"
    budget = "-"
    if need.get("budget_cents") is not None:
        budget = f"{need['budget_cents']} {need.get('currency') or 'credits'}"
    print(
        f"{need['need_id']} status={need.get('status')} visibility={need.get('visibility')} "
        f"category={need.get('category')} budget={budget}"
    )
    print(f"  title: {need.get('title')}")
    if need.get("summary"):
        print(f"  summary: {need['summary']}")
    print(f"  tags: {tags}")
    if need.get("selected_bid_id") or need.get("group_id") or need.get("task_id"):
        print(
            f"  selected_bid={need.get('selected_bid_id') or '-'} "
            f"group={need.get('group_id') or '-'} task={need.get('task_id') or '-'}"
        )


def print_need_comment(comment: dict[str, Any]) -> None:
    agent = f" agent_id={comment['author_agent_id']}" if comment.get("author_agent_id") else ""
    print(f"{comment['created_at']} {comment['comment_id']} author={comment['author_user_id']}{agent}")
    print(f"  {comment['body']}")


def print_need_bid(bid: dict[str, Any]) -> None:
    amount = "-"
    if bid.get("amount_cents") is not None:
        amount = f"{bid['amount_cents']} {bid.get('currency') or 'credits'}"
    provider = bid.get("provider") or {}
    service = bid.get("service") or {}
    agent = bid.get("agent") or {}
    print(
        f"{bid['bid_id']} status={bid.get('status')} need={bid.get('need_id')} "
        f"provider={bid.get('provider_id') or '-'} service={bid.get('service_id') or '-'} "
        f"agent={bid.get('agent_id') or '-'} amount={amount}"
    )
    if provider:
        rep = (
            f" rating={provider.get('average_score')}/{provider.get('rating_count')}"
            if provider.get("rating_count")
            else ""
        )
        print(
            f"  provider_card: {provider.get('display_name') or provider.get('provider_id')} "
            f"badge={provider.get('trust_badge')} verification={provider.get('verification_status')}{rep}"
        )
    if service:
        print(
            f"  service_card: {service.get('title') or service.get('service_id')} "
            f"category={service.get('category')} status={service.get('status')}"
        )
    if agent:
        print(
            f"  agent_card: {agent.get('handle') or agent.get('agent_id')} "
            f"runtime={agent.get('runtime_type')} verification={agent.get('verification_status')}"
        )
    if bid.get("estimated_delivery"):
        print(f"  eta: {bid['estimated_delivery']}")
    if bid.get("proposal"):
        print(f"  proposal: {bid['proposal']}")


def print_community_report(report: dict[str, Any]) -> None:
    print(
        f"{report['report_id']} status={report.get('status')} reporter={report.get('reporter_user_id')} "
        f"target={report.get('target_type')}:{report.get('target_id')} reason={report.get('reason')}"
    )
    if report.get("details"):
        print(f"  details: {report['details']}")


def cmd_community_need_create(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    description = read_text_arg(args.description, args.description_file, "description") or ""
    payload = {
        "title": args.title,
        "summary": args.summary or "",
        "description": description,
        "category": args.category,
        "visibility": args.visibility,
        "budget_cents": args.budget_cents,
        "currency": args.currency,
        "input": read_json_payload(args.input_json, args.input_file, "input"),
        "deliverables": read_json_payload(args.deliverables_json, args.deliverables_file, "deliverables"),
        "acceptance_criteria": read_json_payload(args.acceptance_json, args.acceptance_file, "acceptance"),
        "tags": args.tag or [],
    }
    need = api_json("POST", api_url, "/needs", payload, token=token)
    print_need(need)
    return 0


def cmd_community_need_list(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    query = urllib.parse.urlencode(
        {
            "limit": args.limit,
            "status": args.status,
            **({"query": args.query} if args.query else {}),
            **({"category": args.category} if args.category else {}),
        }
    )
    needs = api_json("GET", api_url, f"/needs?{query}", token=token)
    if not needs:
        print("no community needs")
        return 0
    for need in needs:
        print_need(need)
    return 0


def cmd_community_need_show(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    need = api_json("GET", api_url, f"/needs/{quote_path(args.need_id)}", token=token)
    print_need(need)
    if need.get("description"):
        print("description:")
        print(need["description"])
    if need.get("input"):
        print(f"input: {json.dumps(need['input'], sort_keys=True)}")
    if need.get("deliverables"):
        print(f"deliverables: {json.dumps(need['deliverables'], sort_keys=True)}")
    if need.get("acceptance_criteria"):
        print(f"acceptance: {json.dumps(need['acceptance_criteria'], sort_keys=True)}")
    return 0


def cmd_community_need_moderate(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    need = api_json(
        "POST",
        api_url,
        f"/needs/{quote_path(args.need_id)}/moderation",
        {"action": args.action, "note": args.note or ""},
        token=token,
    )
    print_need(need)
    return 0


def cmd_community_need_report(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    report = api_json(
        "POST",
        api_url,
        f"/needs/{quote_path(args.need_id)}/reports",
        {
            "reason": args.reason,
            "details": args.details or "",
            "metadata": read_json_payload(args.metadata_json, args.metadata_file, "metadata"),
        },
        token=token,
    )
    print_community_report(report)
    return 0


def cmd_community_need_discuss(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    body = " ".join(args.body).strip()
    if not body:
        raise SystemExit("discussion body cannot be empty")
    comment = api_json(
        "POST",
        api_url,
        f"/needs/{quote_path(args.need_id)}/discussion",
        {
            "body": body,
            "author_agent_id": args.author_agent_id,
            "metadata": read_json_payload(args.metadata_json, args.metadata_file, "metadata"),
        },
        token=token,
    )
    print_need_comment(comment)
    return 0


def cmd_community_need_comments(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    query = urllib.parse.urlencode({"limit": args.limit})
    comments = api_json("GET", api_url, f"/needs/{quote_path(args.need_id)}/discussion?{query}", token=token)
    if not comments:
        print("no discussion")
        return 0
    for comment in comments:
        print_need_comment(comment)
    return 0


def cmd_community_need_report_comment(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    report = api_json(
        "POST",
        api_url,
        f"/needs/{quote_path(args.need_id)}/discussion/{quote_path(args.comment_id)}/reports",
        {
            "reason": args.reason,
            "details": args.details or "",
            "metadata": read_json_payload(args.metadata_json, args.metadata_file, "metadata"),
        },
        token=token,
    )
    print_community_report(report)
    return 0


def cmd_community_need_bid(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    proposal = read_text_arg(args.proposal, args.proposal_file, "proposal") or ""
    bid = api_json(
        "POST",
        api_url,
        f"/needs/{quote_path(args.need_id)}/bids",
        {
            "provider_id": args.provider_id,
            "service_id": args.service_id,
            "agent_id": args.agent_id,
            "proposal": proposal,
            "amount_cents": args.amount_cents,
            "currency": args.currency,
            "estimated_delivery": args.estimated_delivery,
            "terms": read_json_payload(args.terms_json, args.terms_file, "terms"),
        },
        token=token,
    )
    print_need_bid(bid)
    return 0


def cmd_community_need_bids(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    query = urllib.parse.urlencode({"limit": args.limit})
    bids = api_json("GET", api_url, f"/needs/{quote_path(args.need_id)}/bids?{query}", token=token)
    if not bids:
        print("no bids")
        return 0
    for bid in bids:
        print_need_bid(bid)
    return 0


def cmd_community_need_report_bid(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    report = api_json(
        "POST",
        api_url,
        f"/needs/{quote_path(args.need_id)}/bids/{quote_path(args.bid_id)}/reports",
        {
            "reason": args.reason,
            "details": args.details or "",
            "metadata": read_json_payload(args.metadata_json, args.metadata_file, "metadata"),
        },
        token=token,
    )
    print_community_report(report)
    return 0


def cmd_community_need_accept_bid(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    response = api_json(
        "POST",
        api_url,
        f"/needs/{quote_path(args.need_id)}/bids/{quote_path(args.bid_id)}/accept",
        {
            "group_handle": args.group_handle,
            "group_title": args.group_title,
            "create_task": not args.no_task,
            "task_input": read_json_payload(args.task_input_json, args.task_input_file, "task-input"),
            "note": args.note or "",
        },
        token=token,
    )
    print_need(response["need"])
    print_need_bid(response["bid"])
    if response.get("group"):
        print("group:")
        print_group(response["group"])
    if response.get("task"):
        print("task:")
        print_task(response["task"])
    return 0


def print_task(task: dict[str, Any]) -> None:
    capability = f" capability_id={task['capability_id']}" if task.get("capability_id") else ""
    print(
        f"{task['task_id']} status={task.get('status')} service_id={task.get('service_id')} "
        f"provider_id={task.get('provider_id')}{capability}"
    )
    if task.get("input"):
        print(f"  input: {json.dumps(task['input'], sort_keys=True)}")
    if task.get("result"):
        print(f"  result: {json.dumps(task['result'], sort_keys=True)}")


def print_provider(provider: dict[str, Any]) -> None:
    print(
        f"{provider['provider_id']} display_name={provider.get('display_name')} "
        f"type={provider.get('provider_type')} verification={provider.get('verification_status')} "
        f"badge={provider.get('trust_badge')}"
    )
    if provider.get("agent_id"):
        print(f"  agent_id: {provider['agent_id']}")


def print_task_receipt(receipt: dict[str, Any]) -> None:
    artifacts = ",".join(receipt.get("artifact_ids") or []) or "-"
    print(
        f"{receipt['receipt_id']} task={receipt['task_id']} status={receipt.get('status')} "
        f"type={receipt.get('receipt_type')} artifacts={artifacts} created_at={receipt.get('created_at')}"
    )
    if receipt.get("summary"):
        print(f"  summary: {receipt['summary']}")
    if receipt.get("usage"):
        print(f"  usage: {json.dumps(receipt['usage'], sort_keys=True)}")


def print_verification(record: dict[str, Any]) -> None:
    evidence = ",".join(record.get("evidence_artifact_ids") or []) or "-"
    print(
        f"{record['verification_id']} task={record['task_id']} status={record.get('status')} "
        f"type={record.get('verification_type')} evidence={evidence} created_at={record.get('created_at')}"
    )
    if record.get("comment"):
        print(f"  comment: {record['comment']}")
    if record.get("result"):
        print(f"  result: {json.dumps(record['result'], sort_keys=True)}")


def cmd_service_task_status(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    task = api_json("GET", api_url, f"/tasks/{quote_path(args.task_id)}", token=token)
    print_task(task)
    return 0


def cmd_provider_verify_status(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    provider = api_json(
        "POST",
        api_url,
        f"/providers/{quote_path(args.provider_id)}/verification",
        {"verification_status": args.verification_status, "note": args.note or ""},
        token=token,
    )
    print_provider(provider)
    return 0


def cmd_service_task_accept(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    task = api_json(
        "POST",
        api_url,
        f"/tasks/{quote_path(args.task_id)}/accept",
        {"note": args.note or "", "accepted_by_agent_id": args.accepted_by_agent_id},
        token=token,
    )
    print_task(task)
    return 0


def cmd_service_task_set_status(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    task = api_json(
        "POST",
        api_url,
        f"/tasks/{quote_path(args.task_id)}/status",
        {"status": args.status, "note": args.note or ""},
        token=token,
    )
    print_task(task)
    return 0


def cmd_service_task_submit_result(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    result = read_json_payload(args.result_json, args.result_file, "result")
    usage = read_json_payload(args.usage_json, args.usage_file, "usage")
    task = api_json(
        "POST",
        api_url,
        f"/tasks/{quote_path(args.task_id)}/result",
        {
            "status": args.status,
            "result": result,
            "summary": args.summary or "",
            "artifact_ids": args.artifact_id or [],
            "usage": usage,
        },
        token=token,
    )
    print_task(task)
    print("receipt: run `ainet service task receipts TASK_ID` to inspect submission receipts")
    return 0


def cmd_service_task_receipts(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    query = urllib.parse.urlencode({"limit": args.limit})
    receipts = api_json("GET", api_url, f"/tasks/{quote_path(args.task_id)}/receipts?{query}", token=token)
    if not receipts:
        print("no task receipts")
        return 0
    for receipt in receipts:
        print_task_receipt(receipt)
    return 0


def cmd_service_task_verify(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    rubric = read_json_payload(args.rubric_json, args.rubric_file, "rubric")
    result = read_json_payload(args.result_json, args.result_file, "result")
    record = api_json(
        "POST",
        api_url,
        f"/tasks/{quote_path(args.task_id)}/verify",
        {
            "verification_type": args.verification_type,
            "status": args.status,
            "rubric": rubric,
            "result": result,
            "evidence_artifact_ids": args.evidence_artifact_id or [],
            "verifier_agent_id": args.verifier_agent_id,
            "comment": args.comment or "",
        },
        token=token,
    )
    print_verification(record)
    return 0


def cmd_service_task_reject(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    rubric = read_json_payload(args.rubric_json, args.rubric_file, "rubric")
    result = read_json_payload(args.result_json, args.result_file, "result")
    if args.reason:
        result.setdefault("reason", args.reason)
    record = api_json(
        "POST",
        api_url,
        f"/tasks/{quote_path(args.task_id)}/reject",
        {
            "verification_type": args.verification_type,
            "rubric": rubric,
            "result": result,
            "evidence_artifact_ids": args.evidence_artifact_id or [],
            "verifier_agent_id": args.verifier_agent_id,
            "comment": args.comment or args.reason or "",
        },
        token=token,
    )
    print_verification(record)
    return 0


def cmd_service_task_verifications(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    query = urllib.parse.urlencode({"limit": args.limit})
    records = api_json("GET", api_url, f"/tasks/{quote_path(args.task_id)}/verifications?{query}", token=token)
    if not records:
        print("no task verifications")
        return 0
    for record in records:
        print_verification(record)
    return 0


def get_profile(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profile = config["profiles"].get(profile_name)
    if not profile:
        raise SystemExit(f"profile not installed: {profile_name}. Run `install` first.")
    return profile


def resolve_profile_name(args: argparse.Namespace, config: dict[str, Any]) -> str:
    profile = getattr(args, "profile", None) or config.get("active_profile")
    if not profile:
        raise SystemExit("no profile selected. Pass `--profile NAME` or run `install` first.")
    return profile


def account_by_handle(relay: dict[str, Any], handle: str) -> tuple[str, dict[str, Any]]:
    handle = normalize_handle(handle)
    account_id = relay["handles"].get(handle)
    if not account_id:
        raise SystemExit(f"unknown account handle: {handle}")
    return account_id, relay["accounts"][account_id]


def cmd_install(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    profile_name = args.profile
    handle = normalize_handle(args.handle)
    capabilities = sorted(set(args.capability or []))
    config["profiles"][profile_name] = {
        "profile": profile_name,
        "handle": handle,
        "runtime": args.runtime,
        "owner": args.owner,
        "capabilities": capabilities,
        "account_id": config["profiles"].get(profile_name, {}).get("account_id"),
        "installed_at": utc_now(),
        "adapter_mode": args.adapter_mode,
    }
    config["active_profile"] = profile_name
    if paths.relay_url:
        config["relay_url"] = paths.relay_url
    if paths.relay_token:
        config["relay_token"] = paths.relay_token
    save_config(paths, config)
    print(f"installed profile `{profile_name}` for agent `{handle}`")
    print(f"runtime: {args.runtime}")
    print(f"home: {paths.home}")
    print("next: register this profile with `register`")
    return 0


def cmd_register(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    profile_name = resolve_profile_name(args, config)
    profile = get_profile(config, profile_name)
    relay = load_relay(paths)
    handle = normalize_handle(profile["handle"])
    existing_id = relay["handles"].get(handle)
    if existing_id and existing_id != profile.get("account_id"):
        raise SystemExit(f"handle already registered by another account: {handle}")

    account_id = profile.get("account_id") or existing_id or new_id("acct")
    account = relay["accounts"].get(account_id, {})
    account.update(
        {
            "account_id": account_id,
            "handle": handle,
            "kind": "agent",
            "runtime": profile["runtime"],
            "owner": profile.get("owner"),
            "capabilities": profile.get("capabilities", []),
            "adapter_mode": profile.get("adapter_mode", "sidecar"),
            "updated_at": utc_now(),
        }
    )
    account.setdefault("created_at", utc_now())
    relay["accounts"][account_id] = account
    relay["handles"][handle] = account_id
    profile["account_id"] = account_id
    config["profiles"][profile_name] = profile
    save_relay(paths, relay)
    save_config(paths, config)
    print(f"registered `{handle}` as {account_id}")
    print(f"relay: {paths.relay_url or paths.relay}")
    return 0


def cmd_whoami(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    profile_name = resolve_profile_name(args, config)
    profile = get_profile(config, profile_name)
    print(json.dumps(profile, indent=2, sort_keys=True))
    return 0


def cmd_directory(_args: argparse.Namespace, paths: Paths) -> int:
    relay = load_relay(paths)
    accounts = sorted(relay["accounts"].values(), key=lambda item: item["handle"])
    if not accounts:
        print("no accounts registered")
        return 0
    for account in accounts:
        caps = ", ".join(account.get("capabilities", [])) or "-"
        print(f"{account['handle']}  runtime={account.get('runtime')}  capabilities={caps}")
    return 0


def cmd_friend_add(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    profile_name = resolve_profile_name(args, config)
    profile = get_profile(config, profile_name)
    if not profile.get("account_id"):
        raise SystemExit("current profile is not registered. Run `register` first.")
    relay = load_relay(paths)
    from_id = profile["account_id"]
    from_account = relay["accounts"].get(from_id)
    if not from_account:
        raise SystemExit("registered account missing from relay. Run `register` again.")
    to_id, to_account = account_by_handle(relay, args.handle)
    if to_id == from_id:
        raise SystemExit("cannot add yourself as a friend")

    for edge in relay["friend_edges"].values():
        if {edge["from_account_id"], edge["to_account_id"]} == {from_id, to_id}:
            print(f"already friends: {from_account['handle']} <-> {to_account['handle']}")
            return 0

    for request in relay["friend_requests"].values():
        if (
            request["from_account_id"] == from_id
            and request["to_account_id"] == to_id
            and request["status"] == "pending"
        ):
            print(f"friend request already pending: {request['request_id']}")
            return 0

    request_id = new_id("fr")
    relay["friend_requests"][request_id] = {
        "request_id": request_id,
        "from_account_id": from_id,
        "from_handle": from_account["handle"],
        "to_account_id": to_id,
        "to_handle": to_account["handle"],
        "permissions": sorted(set(args.permission or ["human_dm", "agent_dm"])),
        "message": args.message,
        "status": "pending",
        "created_at": utc_now(),
    }
    save_relay(paths, relay)
    print(f"sent friend request {request_id}: {from_account['handle']} -> {to_account['handle']}")
    return 0


def cmd_friend_requests(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    profile_name = resolve_profile_name(args, config)
    profile = get_profile(config, profile_name)
    if not profile.get("account_id"):
        raise SystemExit("current profile is not registered. Run `register` first.")
    relay = load_relay(paths)
    account_id = profile["account_id"]
    found = False
    for request in sorted(relay["friend_requests"].values(), key=lambda item: item["created_at"]):
        if args.all or request["from_account_id"] == account_id or request["to_account_id"] == account_id:
            found = True
            direction = "incoming" if request["to_account_id"] == account_id else "outgoing"
            perms = ",".join(request.get("permissions", []))
            print(
                f"{request['request_id']}  {direction}  {request['from_handle']} -> "
                f"{request['to_handle']}  status={request['status']}  permissions={perms}"
            )
    if not found:
        print("no friend requests")
    return 0


def cmd_friend_accept(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    profile_name = resolve_profile_name(args, config)
    profile = get_profile(config, profile_name)
    if not profile.get("account_id"):
        raise SystemExit("current profile is not registered. Run `register` first.")
    relay = load_relay(paths)
    request = relay["friend_requests"].get(args.request_id)
    if not request:
        raise SystemExit(f"unknown friend request: {args.request_id}")
    if request["to_account_id"] != profile["account_id"]:
        raise SystemExit("only the receiving account can accept this friend request")
    if request["status"] != "pending":
        print(f"friend request already {request['status']}: {args.request_id}")
        return 0

    request["status"] = "accepted"
    request["accepted_at"] = utc_now()
    edge_id = new_id("edge")
    relay["friend_edges"][edge_id] = {
        "edge_id": edge_id,
        "from_account_id": request["from_account_id"],
        "from_handle": request["from_handle"],
        "to_account_id": request["to_account_id"],
        "to_handle": request["to_handle"],
        "permissions": request["permissions"],
        "created_from_request_id": args.request_id,
        "created_at": utc_now(),
    }
    save_relay(paths, relay)
    print(f"accepted {args.request_id}")
    print(f"created friendship {edge_id}: {request['from_handle']} <-> {request['to_handle']}")
    return 0


def cmd_friends(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    profile_name = resolve_profile_name(args, config)
    profile = get_profile(config, profile_name)
    if not profile.get("account_id"):
        raise SystemExit("current profile is not registered. Run `register` first.")
    relay = load_relay(paths)
    account_id = profile["account_id"]
    found = False
    for edge in sorted(relay["friend_edges"].values(), key=lambda item: item["created_at"]):
        if edge["from_account_id"] == account_id or edge["to_account_id"] == account_id:
            found = True
            other = edge["to_handle"] if edge["from_account_id"] == account_id else edge["from_handle"]
            perms = ",".join(edge.get("permissions", []))
            print(f"{other}  edge={edge['edge_id']}  permissions={perms}")
    if not found:
        print("no friends yet")
    return 0


def find_friend_edge(relay: dict[str, Any], from_id: str, to_id: str) -> dict[str, Any] | None:
    for edge in relay["friend_edges"].values():
        if {edge["from_account_id"], edge["to_account_id"]} == {from_id, to_id}:
            return edge
    return None


def cmd_dm_send(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    profile_name = resolve_profile_name(args, config)
    profile = get_profile(config, profile_name)
    if not profile.get("account_id"):
        raise SystemExit("current profile is not registered. Run `register` first.")
    relay = load_relay(paths)
    from_id = profile["account_id"]
    from_account = relay["accounts"].get(from_id)
    if not from_account:
        raise SystemExit("registered account missing from relay. Run `register` again.")
    to_id, to_account = account_by_handle(relay, args.handle)
    edge = find_friend_edge(relay, from_id, to_id)
    if not edge:
        raise SystemExit(f"not friends yet: {from_account['handle']} -> {to_account['handle']}")
    if not {"human_dm", "agent_dm", "dm"} & set(edge.get("permissions", [])):
        raise SystemExit("friend edge does not allow DM")
    body = " ".join(args.body).strip()
    if not body:
        raise SystemExit("message body cannot be empty")
    message_id = new_id("msg")
    relay["messages"][message_id] = {
        "message_id": message_id,
        "from_account_id": from_id,
        "from_handle": from_account["handle"],
        "to_account_id": to_id,
        "to_handle": to_account["handle"],
        "message_type": "dm",
        "body": body,
        "created_at": utc_now(),
    }
    save_relay(paths, relay)
    print(f"sent {message_id}: {from_account['handle']} -> {to_account['handle']}")
    return 0


def cmd_dm_inbox(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    profile_name = resolve_profile_name(args, config)
    profile = get_profile(config, profile_name)
    if not profile.get("account_id"):
        raise SystemExit("current profile is not registered. Run `register` first.")
    relay = load_relay(paths)
    account_id = profile["account_id"]
    messages = sorted(relay["messages"].values(), key=lambda item: item["created_at"])
    found = False
    for message in messages:
        incoming = message["to_account_id"] == account_id
        outgoing = message["from_account_id"] == account_id
        if incoming or (args.all and outgoing):
            found = True
            direction = "in" if incoming else "out"
            other = message["from_handle"] if incoming else message["to_handle"]
            print(f"{message['message_id']}  {direction}  {other}  {message['created_at']}")
            print(f"  {message['body']}")
    if not found:
        print("no messages")
    return 0


def watch_events(relay: dict[str, Any], account_id: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for request in relay["friend_requests"].values():
        if request["to_account_id"] == account_id and request["status"] == "pending":
            events.append(
                {
                    "event_id": f"friend_request:{request['request_id']}:pending",
                    "kind": "friend_request",
                    "timestamp": request.get("created_at", ""),
                    "line": (
                        f"[friend request] {request['from_handle']} -> {request['to_handle']} "
                        f"{request['request_id']}"
                    ),
                    "body": request.get("message", ""),
                }
            )
        if request["from_account_id"] == account_id and request["status"] == "accepted":
            events.append(
                {
                    "event_id": f"friend_request:{request['request_id']}:accepted",
                    "kind": "friend_accept",
                    "timestamp": request.get("accepted_at") or request.get("created_at", ""),
                    "line": (
                        f"[friend accepted] {request['to_handle']} accepted "
                        f"{request['request_id']}"
                    ),
                    "body": "",
                }
            )
    for message in relay["messages"].values():
        if message["to_account_id"] != account_id:
            continue
        events.append(
            {
                "event_id": f"message:{message['message_id']}",
                "kind": "message",
                "timestamp": message.get("created_at", ""),
                "line": (
                    f"[dm] {message['from_handle']} -> {message['to_handle']} "
                    f"{message['message_id']} {message.get('created_at', '')}"
                ),
                "body": message.get("body", ""),
            }
        )
    return sorted(events, key=lambda item: (item["timestamp"], item["event_id"]))


def print_watch_event(event: dict[str, str]) -> None:
    print(event["line"], flush=True)
    body = event.get("body")
    if body:
        print(f"  {body}", flush=True)


def cmd_watch(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    profile_name = resolve_profile_name(args, config)
    profile = get_profile(config, profile_name)
    if not profile.get("account_id"):
        raise SystemExit("current profile is not registered. Run `register` first.")
    account_id = profile["account_id"]
    print(f"watching `{profile['handle']}` every {args.interval:g}s; press Ctrl-C to stop", flush=True)
    seen: set[str] = set()
    first = True
    while True:
        relay = load_relay(paths)
        events = watch_events(relay, account_id)
        if first and not args.show_existing:
            seen.update(event["event_id"] for event in events)
        else:
            for event in events:
                if event["event_id"] in seen:
                    continue
                print_watch_event(event)
                seen.add(event["event_id"])
        first = False
        if args.once:
            return 0
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nwatch stopped")
            return 0


def cmd_relay_serve(args: argparse.Namespace, paths: Paths) -> int:
    from .relay_server import serve_relay

    path = Path(args.path).expanduser() if args.path else paths.relay
    bootstrap_path = Path(args.bootstrap_path).expanduser() if args.bootstrap_path else None
    package_path = Path(args.package_path).expanduser() if args.package_path else None
    serve_relay(
        args.host,
        args.port,
        path,
        auth_token=args.auth_token,
        bootstrap_path=bootstrap_path,
        package_path=package_path,
    )
    return 0


def cmd_demo(_args: argparse.Namespace, paths: Paths) -> int:
    steps = [
        [
            "install",
            "--profile",
            "alice",
            "--handle",
            "alice.hermes",
            "--runtime",
            "hermes",
            "--owner",
            "alice",
            "--capability",
            "personal_assistant",
        ],
        ["register", "--profile", "alice"],
        [
            "install",
            "--profile",
            "bob",
            "--handle",
            "bob.agent",
            "--runtime",
            "coding-agent",
            "--owner",
            "bob",
            "--capability",
            "code_review",
            "--capability",
            "patch_suggestion",
        ],
        ["register", "--profile", "bob"],
        [
            "friend",
            "add",
            "bob.agent",
            "--profile",
            "alice",
            "--permission",
            "agent_dm",
            "--permission",
            "service:code_review",
            "--message",
            "Can your agent review patches for my agent?",
        ],
    ]
    print(f"demo home: {paths.home}")
    for step in steps:
        print(f"\n$ ainet {' '.join(step)}")
        dispatch(step, paths)

    relay = load_relay(paths)
    pending = [
        request
        for request in relay["friend_requests"].values()
        if request["to_handle"] == "bob.agent" and request["status"] == "pending"
    ]
    if pending:
        request_id = sorted(pending, key=lambda item: item["created_at"])[-1]["request_id"]
        accept_step = ["friend", "accept", request_id, "--profile", "bob"]
        print(f"\n$ ainet {' '.join(accept_step)}")
        dispatch(accept_step, paths)
    else:
        print("\n(no pending request to accept; the demo accounts may already be friends)")
    print("\n$ ainet friends --profile alice")
    dispatch(["friends", "--profile", "alice"], paths)
    print("\n$ ainet friends --profile bob")
    dispatch(["friends", "--profile", "bob"], paths)
    dm_step = [
        "dm",
        "send",
        "bob.agent",
        "hello from alice.hermes",
        "--profile",
        "alice",
    ]
    print(f"\n$ ainet {' '.join(dm_step)}")
    dispatch(dm_step, paths)
    print("\n$ ainet dm inbox --profile bob")
    dispatch(["dm", "inbox", "--profile", "bob"], paths)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ainet", description="Minimal Ainet MVP")
    parser.add_argument("--home", default=str(DEFAULT_HOME), help="state directory, default: ~/.ainet")
    parser.add_argument(
        "--relay-url",
        default=DEFAULT_RELAY_URL,
        help="HTTP relay URL, e.g. http://192.168.1.10:8765",
    )
    parser.add_argument(
        "--relay-token",
        default=DEFAULT_RELAY_TOKEN,
        help="bearer token for an HTTP relay; can also use AINET_RELAY_TOKEN",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    auth = sub.add_parser("auth", help="enterprise backend authentication")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)

    auth_signup = auth_sub.add_parser("signup", help="create an account on the Ainet API")
    auth_signup.add_argument("--api-url", help="Ainet backend URL")
    auth_signup.add_argument("--email", help="account email")
    auth_signup.add_argument("--username", help="account username")
    auth_signup.add_argument("--password", help="account password; omit to prompt securely")
    auth_signup.set_defaults(func=cmd_auth_signup)

    auth_verify = auth_sub.add_parser("verify-email", help="verify an account email code")
    auth_verify.add_argument("--api-url", help="Ainet backend URL")
    auth_verify.add_argument("--email", help="account email")
    auth_verify.add_argument("--code", help="email verification code")
    auth_verify.set_defaults(func=cmd_auth_verify_email)

    auth_login = auth_sub.add_parser("login", help="login to the Ainet API and save a local token")
    auth_login.add_argument("--api-url", help="Ainet backend URL")
    auth_login.add_argument("--email", help="account email")
    auth_login.add_argument("--password", help="account password; omit to prompt securely")
    auth_login.add_argument("--device-name", help="device/session name")
    auth_login.add_argument("--runtime-type", default="agent-cli", help="runtime type for this session")
    auth_login.set_defaults(func=cmd_auth_login)

    auth_status = auth_sub.add_parser("status", help="show local login status")
    auth_status.add_argument("--api-url", help="Ainet backend URL")
    auth_status.add_argument("--check", action="store_true", help="check the token against the server")
    auth_status.set_defaults(func=cmd_auth_status)

    auth_invite = auth_sub.add_parser("invite", help="device invite operations")
    invite_sub = auth_invite.add_subparsers(dest="invite_command", required=True)
    invite_create = invite_sub.add_parser("create", help="create a short-lived device invite")
    invite_create.add_argument("--invite-type", default="device", help="invite type; currently only device is supported")
    invite_create.add_argument("--scope", action="append", help="scope to grant to the invited device")
    invite_create.add_argument("--expires-minutes", type=int, default=10, help="invite lifetime in minutes")
    invite_create.add_argument("--max-uses", type=int, default=1, help="maximum invite acceptances")
    invite_create.set_defaults(func=cmd_auth_invite_create)
    invite_accept = invite_sub.add_parser("accept", help="accept a device invite and save local auth")
    invite_accept.add_argument("token", nargs="?", help="invite token; omit to prompt")
    invite_accept.add_argument("--api-url", help="Ainet backend URL")
    invite_accept.add_argument("--device-name", help="device/session name")
    invite_accept.add_argument("--runtime-type", default="agent-cli", help="runtime type for this session")
    invite_accept.set_defaults(func=cmd_auth_invite_accept)

    auth_sessions = auth_sub.add_parser("sessions", help="list account device sessions")
    auth_sessions.add_argument("--include-revoked", action="store_true", help="include revoked sessions")
    auth_sessions.set_defaults(func=cmd_auth_sessions)

    auth_revoke_session = auth_sub.add_parser("revoke-session", help="revoke an account device session")
    auth_revoke_session.add_argument("session_id", help="session id to revoke")
    auth_revoke_session.set_defaults(func=cmd_auth_revoke_session)

    auth_logout = auth_sub.add_parser("logout", help="remove the local access token")
    auth_logout.set_defaults(func=cmd_auth_logout)

    identity = sub.add_parser("identity", help="show persistent Ainet identity")
    identity_sub = identity.add_subparsers(dest="identity_command", required=True)
    identity_show = identity_sub.add_parser("show", help="show current user and agent identities")
    identity_show.set_defaults(func=cmd_identity_show)

    mcp = sub.add_parser("mcp", help="MCP adapter operations")
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_install = mcp_sub.add_parser("install", help="write MCP client configuration for Ainet")
    mcp_install.add_argument("--target", choices=["json"], default="json", help="configuration target")
    mcp_install.add_argument("--name", default="ainet", help="MCP server name")
    mcp_install.add_argument("--api-url", help="Ainet backend URL")
    mcp_install.add_argument("--output", help="output path for --target json; defaults to ~/.ainet/mcp.json")
    mcp_install.add_argument("--command", help="MCP server command; defaults to ainet-mcp on PATH")
    mcp_install.add_argument("--arg", action="append", help="argument to pass to the MCP server command")
    mcp_install.add_argument("--require-auth", action="store_true", help="fail if auth login has not been saved")
    mcp_install.set_defaults(func=cmd_mcp_install)

    adapter = sub.add_parser("adapter", help="external agent runtime adapter profiles")
    adapter_sub = adapter.add_subparsers(dest="adapter_command", required=True)
    adapter_install = adapter_sub.add_parser("install", help="install a communication-only runtime adapter profile")
    adapter_install.add_argument("runtime", choices=sorted(RUNTIME_ADAPTER_DEFAULTS), help="external runtime to connect")
    adapter_install.add_argument("--profile", help="local profile name; defaults to runtime name")
    adapter_install.add_argument("--handle", help="Ainet agent handle; defaults to user-host.RUNTIME")
    adapter_install.add_argument("--owner", help="optional human owner label")
    adapter_install.add_argument("--display-name", help="optional backend display name")
    adapter_install.add_argument("--capability", action="append", help="capability to advertise; defaults by runtime")
    adapter_install.add_argument("--register-relay", action="store_true", help="register this profile with the local/LAN relay")
    adapter_install.add_argument("--backend-agent", action="store_true", help="also create a backend agent for the saved auth account")
    adapter_install.set_defaults(func=cmd_adapter_install)

    server = sub.add_parser("server", help="self-hosted server operations")
    server_sub = server.add_subparsers(dest="server_command", required=True)
    server_doctor = server_sub.add_parser("doctor", help="check local self-hosted server readiness")
    server_doctor.add_argument("--api-url", help="Ainet backend URL")
    server_doctor.add_argument("--check-api", action="store_true", help="probe /health on the configured backend API")
    server_doctor.set_defaults(func=cmd_server_doctor)
    server_status = server_sub.add_parser("status", help="show local Ainet config and backend status")
    server_status.add_argument("--api-url", help="Ainet backend URL")
    server_status.add_argument("--json", action="store_true", help="also print machine-readable JSON")
    server_status.set_defaults(func=cmd_server_status)
    server_bootstrap = server_sub.add_parser("bootstrap", help="planned self-hosted bootstrap entry point")
    server_bootstrap.add_argument("--domain", help="public homeserver domain")
    server_bootstrap.add_argument("--email", help="admin email")
    server_bootstrap.set_defaults(func=cmd_server_bootstrap)

    events = sub.add_parser("events", help="enterprise backend event operations")
    events_sub = events.add_subparsers(dest="events_command", required=True)
    events_watch = events_sub.add_parser("watch", help="watch backend events over SSE")
    events_watch.add_argument("--after-id", type=int, default=0, help="start after this event cursor")
    events_watch.add_argument("--poll-seconds", type=float, default=2.0, help="server polling interval for SSE")
    events_watch.add_argument("--once", action="store_true", help="print one event and exit")
    events_watch.set_defaults(func=cmd_backend_events_watch)

    chat = sub.add_parser("chat", help="enterprise backend chat operations")
    chat_sub = chat.add_subparsers(dest="chat_command", required=True)
    chat_search = chat_sub.add_parser("search", help="search durable backend chat messages")
    chat_search.add_argument("query", help="message search query")
    chat_search.add_argument("--conversation-id", help="limit search to one conversation")
    chat_search.add_argument("--limit", type=int, default=50, help="maximum result count")
    chat_search.set_defaults(func=cmd_chat_search)
    chat_memory = chat_sub.add_parser("memory", help="conversation memory operations")
    memory_sub = chat_memory.add_subparsers(dest="memory_command", required=True)
    memory_get = memory_sub.add_parser("get", help="show saved memory for a conversation")
    memory_get.add_argument("conversation_id")
    memory_get.set_defaults(func=cmd_chat_memory_get)
    memory_refresh = memory_sub.add_parser("refresh", help="refresh extractive memory from recent messages")
    memory_refresh.add_argument("conversation_id")
    memory_refresh.add_argument("--limit", type=int, default=50, help="recent message count")
    memory_refresh.set_defaults(func=cmd_chat_memory_refresh)
    memory_search = memory_sub.add_parser("search", help="search saved conversation memories")
    memory_search.add_argument("query")
    memory_search.add_argument("--limit", type=int, default=50, help="maximum result count")
    memory_search.set_defaults(func=cmd_chat_memory_search)

    agent = sub.add_parser("agent", help="enterprise backend agent account operations")
    agent_sub = agent.add_subparsers(dest="agent_command", required=True)
    agent_create = agent_sub.add_parser("create", help="create a backend agent handle for this account")
    agent_create.add_argument("--handle", required=True, help="agent handle, e.g. alice.agent")
    agent_create.add_argument("--display-name", help="optional display name")
    agent_create.add_argument("--runtime-type", default="agent-cli", help="runtime type, e.g. coding-agent")
    agent_create.add_argument("--profile", help="local profile name to update")
    agent_create.add_argument("--public-key", help="public key metadata for future signed agent cards")
    agent_create.add_argument("--public-key-file", help="read public key metadata from a file")
    agent_create.add_argument("--key-id", help="stable key identifier for future signing")
    agent_create.set_defaults(func=cmd_agent_create)
    agent_identity = agent_sub.add_parser("identity", help="update backend agent identity metadata")
    agent_identity.add_argument("agent_id", help="agent id to update")
    agent_identity.add_argument("--public-key", help="public key metadata for future signed agent cards")
    agent_identity.add_argument("--public-key-file", help="read public key metadata from a file")
    agent_identity.add_argument("--key-id", help="stable key identifier for future signing")
    agent_identity.set_defaults(func=cmd_agent_identity_update)

    contact = sub.add_parser("contact", help="backend contact trust and permission operations")
    contact_sub = contact.add_subparsers(dest="contact_command", required=True)
    contact_add = contact_sub.add_parser("add", help="add an agent contact with explicit permissions")
    contact_add.add_argument("handle", help="target agent handle")
    contact_add.add_argument("--label", help="optional local label")
    contact_add.add_argument("--contact-type", default="agent", help="contact type")
    contact_add.add_argument("--trust-level", default="known", help="unknown, known, trusted, privileged, or blocked")
    contact_add.add_argument("--permission", action="append", help="permission to grant; default: dm")
    contact_add.set_defaults(func=cmd_contact_add)
    contact_list = contact_sub.add_parser("list", help="list backend contacts")
    contact_list.add_argument("--limit", type=int, default=100, help="maximum result count")
    contact_list.set_defaults(func=cmd_contact_list)
    contact_show = contact_sub.add_parser("show", help="show one backend contact by id or handle")
    contact_show.add_argument("contact", help="contact id or handle")
    contact_show.set_defaults(func=cmd_contact_show)
    contact_permissions = contact_sub.add_parser("permissions", help="show or change contact permissions")
    contact_permissions.add_argument("contact", help="contact id or handle")
    contact_permissions.add_argument("--set", dest="set_permission", action="append", help="replace permissions with this value")
    contact_permissions.add_argument("--add", dest="add_permission", action="append", help="add a permission")
    contact_permissions.add_argument("--remove", dest="remove_permission", action="append", help="remove a permission")
    contact_permissions.set_defaults(func=cmd_contact_permissions)
    contact_trust = contact_sub.add_parser("trust", help="set contact trust level")
    contact_trust.add_argument("contact", help="contact id or handle")
    contact_trust.add_argument("trust_level", help="unknown, known, trusted, privileged, or blocked")
    contact_trust.set_defaults(func=cmd_contact_trust)

    group = sub.add_parser("group", help="backend group workspace operations")
    group_sub = group.add_subparsers(dest="group_command", required=True)
    group_create = group_sub.add_parser("create", help="create a group workspace")
    group_create.add_argument("--handle", required=True, help="group handle, e.g. lab.workspace")
    group_create.add_argument("--title", required=True, help="group title")
    group_create.add_argument("--description", help="optional group description")
    group_create.add_argument("--group-type", default="workspace", help="group type")
    group_create.add_argument("--permission", action="append", help="default member permission")
    group_create.set_defaults(func=cmd_group_create)

    group_list = group_sub.add_parser("list", help="list group workspaces visible to this account")
    group_list.add_argument("--limit", type=int, default=100, help="maximum result count")
    group_list.set_defaults(func=cmd_group_list)

    group_show = group_sub.add_parser("show", help="show one group workspace")
    group_show.add_argument("group", help="group id or handle")
    group_show.set_defaults(func=cmd_group_show)

    group_invite = group_sub.add_parser("invite", help="add an agent handle to a group workspace")
    group_invite.add_argument("group", help="group id or handle")
    group_invite.add_argument("handle", help="agent handle to add")
    group_invite.add_argument("--role", default="member", choices=["admin", "member"], help="group member role")
    group_invite.add_argument("--permission", action="append", help="member permission; defaults to group default")
    group_invite.set_defaults(func=cmd_group_invite)

    group_members = group_sub.add_parser("members", help="list group members")
    group_members.add_argument("group", help="group id or handle")
    group_members.add_argument("--limit", type=int, default=100, help="maximum result count")
    group_members.set_defaults(func=cmd_group_members)

    group_send = group_sub.add_parser("send", help="send a group workspace message")
    group_send.add_argument("group", help="group id or handle")
    group_send.add_argument("body", nargs="+", help="message body")
    group_send.add_argument("--from-agent-id", help="owned agent id to send as")
    group_send.add_argument("--message-type", default="text", help="message type")
    group_send.set_defaults(func=cmd_group_send)

    group_messages = group_sub.add_parser("messages", help="list group messages")
    group_messages.add_argument("group", help="group id or handle")
    group_messages.add_argument("--limit", type=int, default=100, help="maximum result count")
    group_messages.set_defaults(func=cmd_group_messages)

    group_memory = group_sub.add_parser("memory", help="group workspace memory operations")
    group_memory_sub = group_memory.add_subparsers(dest="group_memory_command", required=True)
    group_memory_get = group_memory_sub.add_parser("get", help="show saved group memory")
    group_memory_get.add_argument("group", help="group id or handle")
    group_memory_get.set_defaults(func=cmd_group_memory_get)
    group_memory_refresh = group_memory_sub.add_parser("refresh", help="refresh group memory from recent messages")
    group_memory_refresh.add_argument("group", help="group id or handle")
    group_memory_refresh.add_argument("--limit", type=int, default=50, help="recent message count")
    group_memory_refresh.set_defaults(func=cmd_group_memory_refresh)

    group_task = group_sub.add_parser("task", help="group task-context operations")
    group_task_sub = group_task.add_subparsers(dest="group_task_command", required=True)
    group_task_attach = group_task_sub.add_parser("attach", help="attach a visible service task to a group")
    group_task_attach.add_argument("group", help="group id or handle")
    group_task_attach.add_argument("task_id", help="task id")
    group_task_attach.add_argument("--note", help="optional task context note")
    group_task_attach.set_defaults(func=cmd_group_task_attach)
    group_task_list = group_task_sub.add_parser("list", help="list tasks attached to a group")
    group_task_list.add_argument("group", help="group id or handle")
    group_task_list.add_argument("--limit", type=int, default=100, help="maximum result count")
    group_task_list.set_defaults(func=cmd_group_tasks)

    community = sub.add_parser("community", help="public agent community operations")
    community_sub = community.add_subparsers(dest="community_command", required=True)
    community_need = community_sub.add_parser("need", help="publish, discuss, and accept structured work needs")
    community_need_sub = community_need.add_subparsers(dest="community_need_command", required=True)

    community_need_create = community_need_sub.add_parser("create", help="publish a structured community work need")
    community_need_create.add_argument("--title", required=True, help="need title")
    community_need_create.add_argument("--summary", help="short need summary")
    community_need_create.add_argument("--description", help="long need description")
    community_need_create.add_argument("--description-file", help="read long need description from a file")
    community_need_create.add_argument("--category", default="general", help="need category")
    community_need_create.add_argument("--visibility", default="public", choices=["public", "private"], help="need visibility")
    community_need_create.add_argument("--budget-cents", type=int, help="optional budget in the selected currency")
    community_need_create.add_argument("--currency", default="credits", help="budget currency")
    community_need_create.add_argument("--input-json", help="structured input JSON object")
    community_need_create.add_argument("--input-file", help="read structured input JSON object from a file")
    community_need_create.add_argument("--deliverables-json", help="deliverables JSON object")
    community_need_create.add_argument("--deliverables-file", help="read deliverables JSON object from a file")
    community_need_create.add_argument("--acceptance-json", help="acceptance criteria JSON object")
    community_need_create.add_argument("--acceptance-file", help="read acceptance criteria JSON object from a file")
    community_need_create.add_argument("--tag", action="append", help="community search tag")
    community_need_create.set_defaults(func=cmd_community_need_create)

    community_need_list = community_need_sub.add_parser("list", help="list visible community needs")
    community_need_list.add_argument("--query", help="search query")
    community_need_list.add_argument("--category", help="filter by category")
    community_need_list.add_argument(
        "--status",
        default="open",
        choices=["open", "assigned", "completed", "cancelled", "closed", "hidden", "any"],
        help="need status filter",
    )
    community_need_list.add_argument("--limit", type=int, default=50, help="maximum result count")
    community_need_list.set_defaults(func=cmd_community_need_list)

    community_need_show = community_need_sub.add_parser("show", help="show one community need")
    community_need_show.add_argument("need_id", help="need id")
    community_need_show.set_defaults(func=cmd_community_need_show)

    community_need_close = community_need_sub.add_parser("close", help="close your own community need")
    community_need_close.add_argument("need_id", help="need id")
    community_need_close.add_argument("--note", help="optional moderation note")
    community_need_close.set_defaults(func=cmd_community_need_moderate, action="close")

    community_need_hide = community_need_sub.add_parser("hide", help="hide your own community need from public discovery")
    community_need_hide.add_argument("need_id", help="need id")
    community_need_hide.add_argument("--note", help="optional moderation note")
    community_need_hide.set_defaults(func=cmd_community_need_moderate, action="hide")

    community_need_report = community_need_sub.add_parser("report", help="report a community need")
    community_need_report.add_argument("need_id", help="need id")
    community_need_report.add_argument("--reason", required=True, help="short report reason")
    community_need_report.add_argument("--details", help="optional report details")
    community_need_report.add_argument("--metadata-json", help="metadata JSON object")
    community_need_report.add_argument("--metadata-file", help="read metadata JSON object from a file")
    community_need_report.set_defaults(func=cmd_community_need_report)

    community_need_discuss = community_need_sub.add_parser("discuss", help="add a public discussion comment to a need")
    community_need_discuss.add_argument("need_id", help="need id")
    community_need_discuss.add_argument("body", nargs="+", help="discussion body")
    community_need_discuss.add_argument("--author-agent-id", help="owned agent id to post as")
    community_need_discuss.add_argument("--metadata-json", help="metadata JSON object")
    community_need_discuss.add_argument("--metadata-file", help="read metadata JSON object from a file")
    community_need_discuss.set_defaults(func=cmd_community_need_discuss)

    community_need_comments = community_need_sub.add_parser("comments", help="list need discussion comments")
    community_need_comments.add_argument("need_id", help="need id")
    community_need_comments.add_argument("--limit", type=int, default=100, help="maximum result count")
    community_need_comments.set_defaults(func=cmd_community_need_comments)

    community_need_report_comment = community_need_sub.add_parser("report-comment", help="report a discussion comment")
    community_need_report_comment.add_argument("need_id", help="need id")
    community_need_report_comment.add_argument("comment_id", help="comment id")
    community_need_report_comment.add_argument("--reason", required=True, help="short report reason")
    community_need_report_comment.add_argument("--details", help="optional report details")
    community_need_report_comment.add_argument("--metadata-json", help="metadata JSON object")
    community_need_report_comment.add_argument("--metadata-file", help="read metadata JSON object from a file")
    community_need_report_comment.set_defaults(func=cmd_community_need_report_comment)

    community_need_bid = community_need_sub.add_parser("bid", help="submit a service-provider bid for a need")
    community_need_bid.add_argument("need_id", help="need id")
    community_need_bid.add_argument("--provider-id", help="owned provider id")
    community_need_bid.add_argument("--service-id", help="owned service profile id")
    community_need_bid.add_argument("--agent-id", help="owned bidder agent id")
    community_need_bid.add_argument("--proposal", help="proposal text")
    community_need_bid.add_argument("--proposal-file", help="read proposal text from a file")
    community_need_bid.add_argument("--amount-cents", type=int, help="quoted amount in the selected currency")
    community_need_bid.add_argument("--currency", default="credits", help="quote currency")
    community_need_bid.add_argument("--estimated-delivery", help="estimated delivery note")
    community_need_bid.add_argument("--terms-json", help="terms JSON object")
    community_need_bid.add_argument("--terms-file", help="read terms JSON object from a file")
    community_need_bid.set_defaults(func=cmd_community_need_bid)

    community_need_bids = community_need_sub.add_parser("bids", help="list bids for a community need")
    community_need_bids.add_argument("need_id", help="need id")
    community_need_bids.add_argument("--limit", type=int, default=100, help="maximum result count")
    community_need_bids.set_defaults(func=cmd_community_need_bids)

    community_need_report_bid = community_need_sub.add_parser("report-bid", help="report a bid on a community need")
    community_need_report_bid.add_argument("need_id", help="need id")
    community_need_report_bid.add_argument("bid_id", help="bid id")
    community_need_report_bid.add_argument("--reason", required=True, help="short report reason")
    community_need_report_bid.add_argument("--details", help="optional report details")
    community_need_report_bid.add_argument("--metadata-json", help="metadata JSON object")
    community_need_report_bid.add_argument("--metadata-file", help="read metadata JSON object from a file")
    community_need_report_bid.set_defaults(func=cmd_community_need_report_bid)

    community_need_accept_bid = community_need_sub.add_parser("accept-bid", help="accept a bid and create a group/task")
    community_need_accept_bid.add_argument("need_id", help="need id")
    community_need_accept_bid.add_argument("bid_id", help="bid id")
    community_need_accept_bid.add_argument("--group-handle", help="explicit group handle for the created workspace")
    community_need_accept_bid.add_argument("--group-title", help="explicit group title for the created workspace")
    community_need_accept_bid.add_argument("--no-task", action="store_true", help="accept bid without creating a service task")
    community_need_accept_bid.add_argument("--task-input-json", help="override task input JSON object")
    community_need_accept_bid.add_argument("--task-input-file", help="read task input JSON object from a file")
    community_need_accept_bid.add_argument("--note", help="task context note")
    community_need_accept_bid.set_defaults(func=cmd_community_need_accept_bid)

    provider = sub.add_parser("provider", help="provider profile operations")
    provider_sub = provider.add_subparsers(dest="provider_command", required=True)
    provider_verify = provider_sub.add_parser("verify-status", help="update verification status for an owned provider")
    provider_verify.add_argument("provider_id", help="provider id")
    provider_verify.add_argument(
        "verification_status",
        choices=["unverified", "pending", "verified", "suspended"],
        help="new verification status",
    )
    provider_verify.add_argument("--note", help="optional audit note")
    provider_verify.set_defaults(func=cmd_provider_verify_status)

    service = sub.add_parser("service", help="backend service task operations")
    service_sub = service.add_subparsers(dest="service_command", required=True)
    service_task = service_sub.add_parser("task", help="verifiable service task lifecycle")
    service_task_sub = service_task.add_subparsers(dest="service_task_command", required=True)

    service_task_status = service_task_sub.add_parser("status", help="show task status and payloads")
    service_task_status.add_argument("task_id", help="task id")
    service_task_status.set_defaults(func=cmd_service_task_status)

    service_task_accept = service_task_sub.add_parser("accept", help="provider accepts a service task")
    service_task_accept.add_argument("task_id", help="task id")
    service_task_accept.add_argument("--note", help="optional acceptance note")
    service_task_accept.add_argument("--accepted-by-agent-id", help="owned provider agent id")
    service_task_accept.set_defaults(func=cmd_service_task_accept)

    service_task_set_status = service_task_sub.add_parser("set-status", help="update task execution status")
    service_task_set_status.add_argument("task_id", help="task id")
    service_task_set_status.add_argument(
        "status",
        choices=["accepted", "in_progress", "submitted", "verification_running", "failed", "cancelled", "completed"],
        help="new task status",
    )
    service_task_set_status.add_argument("--note", help="optional status note")
    service_task_set_status.set_defaults(func=cmd_service_task_set_status)

    service_task_submit = service_task_sub.add_parser("submit-result", help="provider submits task result and creates a receipt")
    service_task_submit.add_argument("task_id", help="task id")
    service_task_submit.add_argument("--status", default="submitted", choices=["submitted", "completed", "failed", "cancelled"])
    service_task_submit.add_argument("--summary", help="receipt summary")
    service_task_submit.add_argument("--artifact-id", action="append", help="artifact id included in the receipt")
    service_task_submit.add_argument("--result-json", help="result JSON object")
    service_task_submit.add_argument("--result-file", help="read result JSON object from file")
    service_task_submit.add_argument("--usage-json", help="usage JSON object")
    service_task_submit.add_argument("--usage-file", help="read usage JSON object from file")
    service_task_submit.set_defaults(func=cmd_service_task_submit_result)

    service_task_receipts = service_task_sub.add_parser("receipts", help="list task receipts")
    service_task_receipts.add_argument("task_id", help="task id")
    service_task_receipts.add_argument("--limit", type=int, default=100, help="maximum result count")
    service_task_receipts.set_defaults(func=cmd_service_task_receipts)

    service_task_verify = service_task_sub.add_parser("verify", help="requester verifies or rejects a submitted task")
    service_task_verify.add_argument("task_id", help="task id")
    service_task_verify.add_argument("--verification-type", default="human_approval", help="human_approval, checklist, command, peer_agent")
    service_task_verify.add_argument("--status", default="verified", choices=["verified", "rejected"], help="verification outcome")
    service_task_verify.add_argument("--rubric-json", help="rubric/check JSON object")
    service_task_verify.add_argument("--rubric-file", help="read rubric/check JSON object from file")
    service_task_verify.add_argument("--result-json", help="verification result JSON object")
    service_task_verify.add_argument("--result-file", help="read verification result JSON object from file")
    service_task_verify.add_argument("--evidence-artifact-id", action="append", help="evidence artifact id")
    service_task_verify.add_argument("--verifier-agent-id", help="owned verifier agent id")
    service_task_verify.add_argument("--comment", help="verification comment")
    service_task_verify.set_defaults(func=cmd_service_task_verify)

    service_task_reject = service_task_sub.add_parser("reject", help="requester rejects a submitted task")
    service_task_reject.add_argument("task_id", help="task id")
    service_task_reject.add_argument("--reason", help="rejection reason")
    service_task_reject.add_argument("--verification-type", default="human_approval", help="human_approval, checklist, command, peer_agent")
    service_task_reject.add_argument("--rubric-json", help="rubric/check JSON object")
    service_task_reject.add_argument("--rubric-file", help="read rubric/check JSON object from file")
    service_task_reject.add_argument("--result-json", help="verification result JSON object")
    service_task_reject.add_argument("--result-file", help="read verification result JSON object from file")
    service_task_reject.add_argument("--evidence-artifact-id", action="append", help="evidence artifact id")
    service_task_reject.add_argument("--verifier-agent-id", help="owned verifier agent id")
    service_task_reject.add_argument("--comment", help="verification comment")
    service_task_reject.set_defaults(func=cmd_service_task_reject)

    service_task_verifications = service_task_sub.add_parser("verifications", help="list task verification records")
    service_task_verifications.add_argument("task_id", help="task id")
    service_task_verifications.add_argument("--limit", type=int, default=100, help="maximum result count")
    service_task_verifications.set_defaults(func=cmd_service_task_verifications)

    install = sub.add_parser("install", help="install a local agent profile")
    install.add_argument("--profile", required=True, help="local profile name")
    install.add_argument("--handle", required=True, help="public agent handle")
    install.add_argument("--runtime", required=True, help="runtime type, e.g. coding-agent, openclaw")
    install.add_argument("--owner", default=None, help="human owner handle")
    install.add_argument("--capability", action="append", help="capability to publish")
    install.add_argument("--adapter-mode", default="sidecar", help="sidecar, wrapper, rpc, mcp, native")
    install.set_defaults(func=cmd_install)

    register = sub.add_parser("register", help="register installed profile in local relay")
    register.add_argument("--profile", help="local profile name")
    register.set_defaults(func=cmd_register)

    whoami = sub.add_parser("whoami", help="show local profile")
    whoami.add_argument("--profile", help="local profile name")
    whoami.set_defaults(func=cmd_whoami)

    directory = sub.add_parser("directory", help="list registered accounts")
    directory.set_defaults(func=cmd_directory)

    friend = sub.add_parser("friend", help="friend operations")
    friend_sub = friend.add_subparsers(dest="friend_command", required=True)
    friend_add = friend_sub.add_parser("add", help="send a friend request")
    friend_add.add_argument("handle", help="target account handle")
    friend_add.add_argument("--profile", help="local profile name")
    friend_add.add_argument("--permission", action="append", help="requested permission")
    friend_add.add_argument("--message", default="", help="request message")
    friend_add.set_defaults(func=cmd_friend_add)

    friend_requests = friend_sub.add_parser("requests", help="list friend requests")
    friend_requests.add_argument("--profile", help="local profile name")
    friend_requests.add_argument("--all", action="store_true", help="show all requests in relay")
    friend_requests.set_defaults(func=cmd_friend_requests)

    friend_accept = friend_sub.add_parser("accept", help="accept a friend request")
    friend_accept.add_argument("request_id", help="friend request id")
    friend_accept.add_argument("--profile", help="local profile name")
    friend_accept.set_defaults(func=cmd_friend_accept)

    friends = sub.add_parser("friends", help="list accepted friends for a profile")
    friends.add_argument("--profile", help="local profile name")
    friends.set_defaults(func=cmd_friends)

    dm = sub.add_parser("dm", help="direct messages")
    dm_sub = dm.add_subparsers(dest="dm_command", required=True)
    dm_send = dm_sub.add_parser("send", help="send a DM to a friend")
    dm_send.add_argument("handle", help="target account handle")
    dm_send.add_argument("body", nargs="+", help="message body")
    dm_send.add_argument("--profile", help="local profile name")
    dm_send.set_defaults(func=cmd_dm_send)

    dm_inbox = dm_sub.add_parser("inbox", help="list incoming DMs")
    dm_inbox.add_argument("--profile", help="local profile name")
    dm_inbox.add_argument("--all", action="store_true", help="include sent messages")
    dm_inbox.set_defaults(func=cmd_dm_inbox)

    watch = sub.add_parser("watch", help="print incoming messages and social events as they arrive")
    watch.add_argument("--profile", help="local profile name")
    watch.add_argument("--interval", type=float, default=2.0, help="poll interval in seconds")
    watch.add_argument("--show-existing", action="store_true", help="print currently unseen relay events immediately")
    watch.add_argument("--once", action="store_true", help="check once and exit")
    watch.set_defaults(func=cmd_watch)

    relay = sub.add_parser("relay", help="relay server operations")
    relay_sub = relay.add_subparsers(dest="relay_command", required=True)
    relay_serve = relay_sub.add_parser("serve", help="serve an HTTP relay")
    relay_serve.add_argument("--host", default="127.0.0.1", help="bind host")
    relay_serve.add_argument("--port", type=int, default=8765, help="bind port")
    relay_serve.add_argument("--path", help="relay JSON state path")
    relay_serve.add_argument(
        "--auth-token",
        default=DEFAULT_RELAY_TOKEN,
        help="require this bearer token for /relay; health stays public",
    )
    relay_serve.add_argument("--bootstrap-path", help="serve this file at /ainet-bootstrap.py")
    relay_serve.add_argument("--package-path", help="serve this file at /idea-ainet-latest.tar.gz")
    relay_serve.set_defaults(func=cmd_relay_serve)

    demo = sub.add_parser("demo", help="run a local install/register/friend demo")
    demo.set_defaults(func=cmd_demo)
    return parser


def dispatch(argv: list[str], paths: Paths) -> int:
    parser = build_parser()
    relay_args = ["--relay-url", paths.relay_url] if paths.relay_url else []
    token_args = ["--relay-token", paths.relay_token] if paths.relay_token else []
    args = parser.parse_args(["--home", str(paths.home), *relay_args, *token_args, *argv])
    if args.relay_token:
        os.environ["AINET_RELAY_TOKEN"] = args.relay_token
    return args.func(args, paths)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    home = Path(args.home).expanduser()
    config = read_json(home / "config.json", default_config())
    relay_url = args.relay_url or config.get("relay_url")
    relay_token = args.relay_token or config.get("relay_token")
    if relay_token:
        os.environ["AINET_RELAY_TOKEN"] = relay_token
    paths = Paths(home=home, relay_url=relay_url, relay_token=relay_token)
    return args.func(args, paths)
