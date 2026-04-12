from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_HOME = Path(os.environ.get("AGENT_SOCIAL_HOME", "~/.agent-social")).expanduser()
DEFAULT_RELAY_URL = os.environ.get("AGENT_SOCIAL_RELAY_URL")
DEFAULT_RELAY_TOKEN = os.environ.get("AGENT_SOCIAL_RELAY_TOKEN")


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
        return Path(os.environ.get("AGENT_SOCIAL_RELAY", str(self.home / "relay.json"))).expanduser()


def default_config() -> dict[str, Any]:
    return {"version": 1, "active_profile": None, "profiles": {}}


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
    return read_json(paths.config, default_config())


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
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    token = os.environ.get("AGENT_SOCIAL_RELAY_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"relay HTTP error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"cannot reach relay {url}: {exc}") from exc


def normalize_handle(handle: str) -> str:
    normalized = handle.strip().lower()
    if not normalized:
        raise ValueError("handle cannot be empty")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789._-")
    if any(ch not in allowed for ch in normalized):
        raise ValueError("handle may only contain letters, digits, dot, underscore, and dash")
    return normalized


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
            "bob.codex",
            "--runtime",
            "codex-cli",
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
            "bob.codex",
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
        print(f"\n$ agent-social {' '.join(step)}")
        dispatch(step, paths)

    relay = load_relay(paths)
    pending = [
        request
        for request in relay["friend_requests"].values()
        if request["to_handle"] == "bob.codex" and request["status"] == "pending"
    ]
    if pending:
        request_id = sorted(pending, key=lambda item: item["created_at"])[-1]["request_id"]
        accept_step = ["friend", "accept", request_id, "--profile", "bob"]
        print(f"\n$ agent-social {' '.join(accept_step)}")
        dispatch(accept_step, paths)
    else:
        print("\n(no pending request to accept; the demo accounts may already be friends)")
    print("\n$ agent-social friends --profile alice")
    dispatch(["friends", "--profile", "alice"], paths)
    print("\n$ agent-social friends --profile bob")
    dispatch(["friends", "--profile", "bob"], paths)
    dm_step = [
        "dm",
        "send",
        "bob.codex",
        "hello from alice.hermes",
        "--profile",
        "alice",
    ]
    print(f"\n$ agent-social {' '.join(dm_step)}")
    dispatch(dm_step, paths)
    print("\n$ agent-social dm inbox --profile bob")
    dispatch(["dm", "inbox", "--profile", "bob"], paths)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-social", description="Minimal Agent Social MVP")
    parser.add_argument("--home", default=str(DEFAULT_HOME), help="state directory, default: ~/.agent-social")
    parser.add_argument(
        "--relay-url",
        default=DEFAULT_RELAY_URL,
        help="HTTP relay URL, e.g. http://192.168.1.10:8765",
    )
    parser.add_argument(
        "--relay-token",
        default=DEFAULT_RELAY_TOKEN,
        help="bearer token for an HTTP relay; can also use AGENT_SOCIAL_RELAY_TOKEN",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    install = sub.add_parser("install", help="install a local agent profile")
    install.add_argument("--profile", required=True, help="local profile name")
    install.add_argument("--handle", required=True, help="public agent handle")
    install.add_argument("--runtime", required=True, help="runtime type, e.g. codex-cli, openclaw")
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
    relay_serve.add_argument("--bootstrap-path", help="serve this file at /agent-social-bootstrap.py")
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
        os.environ["AGENT_SOCIAL_RELAY_TOKEN"] = args.relay_token
    return args.func(args, paths)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    home = Path(args.home).expanduser()
    config = read_json(home / "config.json", default_config())
    relay_url = args.relay_url or config.get("relay_url")
    relay_token = args.relay_token or config.get("relay_token")
    if relay_token:
        os.environ["AGENT_SOCIAL_RELAY_TOKEN"] = relay_token
    paths = Paths(home=home, relay_url=relay_url, relay_token=relay_token)
    return args.func(args, paths)
