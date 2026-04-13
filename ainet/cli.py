from __future__ import annotations

import argparse
import getpass
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


def cmd_agent_create(args: argparse.Namespace, paths: Paths) -> int:
    config = load_config(paths)
    api_url, token = require_auth(config)
    payload = {
        "handle": normalize_handle(args.handle),
        "display_name": args.display_name,
        "runtime_type": args.runtime_type,
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
    agent_create.set_defaults(func=cmd_agent_create)

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
