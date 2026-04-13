#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_RELAY_URL = "__RELAY_URL__"
DEFAULT_PACKAGE_URL = "__PACKAGE_URL__"
DEFAULT_RELAY_TOKEN = "__RELAY_TOKEN__"


def require_http_url(url: str, label: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit(f"{label} must be an http(s) URL")
    return url


def clean_token(value: str, fallback: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = value.strip(".-_")
    return value or fallback


def detect_runtime() -> str:
    explicit = os.environ.get("AINET_RUNTIME")
    if explicit:
        return clean_token(explicit, "agent")
    if shutil.which("codex"):
        return "codex-cli"
    if shutil.which("openclaw") or shutil.which("opclaw"):
        return "openclaw"
    if shutil.which("claude"):
        return "claude-code"
    return "agent"


def capabilities_for(runtime: str) -> list[str]:
    if runtime in {"coding-agent", "codex-cli"}:
        return ["code_review", "patch_suggestion"]
    if runtime == "openclaw":
        return ["browser_task"]
    if runtime == "claude-code":
        return ["coding_assistant"]
    return ["dm"]


def display_cmd(cmd: list[str]) -> str:
    parts: list[str] = []
    redact_next = False
    for part in cmd:
        if redact_next:
            parts.append("[redacted]")
            redact_next = False
            continue
        parts.append(part)
        if part == "--relay-token":
            redact_next = True
    return " ".join(parts)


def run(cmd: list[str], cwd: Path | None = None) -> None:
    printable = display_cmd(cmd)
    print(f"$ {printable}", flush=True)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def download_package(url: str, dest: Path) -> None:
    require_http_url(url, "package URL")
    print(f"downloading {url}", flush=True)
    with urllib.request.urlopen(url, timeout=30) as response:  # nosec B310
        dest.write_bytes(response.read())


def extract_package(archive: Path, target: Path) -> Path:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(target, filter="data")
    return target


def health_check(relay_url: str) -> None:
    require_http_url(relay_url, "relay URL")
    url = relay_url.rstrip("/") + "/health"
    print(f"checking relay {url}", flush=True)
    with urllib.request.urlopen(url, timeout=10) as response:  # nosec B310
        body = response.read().decode("utf-8")
    if '"ok": true' not in body and '"ok":true' not in body:
        raise SystemExit(f"relay health check returned unexpected body: {body}")


def build_handle(runtime: str) -> str:
    explicit = os.environ.get("AINET_HANDLE")
    if explicit:
        return clean_token(explicit, "agent.local")
    user = clean_token(getpass.getuser(), "user")
    host = clean_token(socket.gethostname().split(".")[0], "host")
    suffix = runtime.replace("-cli", "").replace("-code", "")
    return clean_token(f"{user}-{host}.{suffix}", "agent.local")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-step Ainet LAN bootstrap")
    parser.add_argument("--relay-url", default=os.environ.get("AINET_RELAY_URL", DEFAULT_RELAY_URL))
    default_token = os.environ.get("AINET_RELAY_TOKEN") or None
    if DEFAULT_RELAY_TOKEN and not DEFAULT_RELAY_TOKEN.startswith("__"):
        default_token = DEFAULT_RELAY_TOKEN
    parser.add_argument("--relay-token", default=default_token)
    parser.add_argument("--package-url", default=os.environ.get("AINET_PACKAGE_URL", DEFAULT_PACKAGE_URL))
    parser.add_argument("--home", default=os.environ.get("AINET_HOME", str(Path.home() / ".ainet")))
    parser.add_argument("--install-dir", default=os.environ.get("AINET_INSTALL_DIR", str(Path.home() / ".ainet" / "app")))
    parser.add_argument("--profile", default=os.environ.get("AINET_PROFILE", "default"))
    args = parser.parse_args(argv)

    if not args.relay_url or args.relay_url.startswith("__"):
        raise SystemExit("missing relay URL; set AINET_RELAY_URL or generate a LAN bootstrap script")
    if not args.package_url or args.package_url.startswith("__"):
        raise SystemExit("missing package URL; set AINET_PACKAGE_URL or generate a LAN bootstrap script")

    relay_url = require_http_url(args.relay_url.rstrip("/"), "relay URL")
    package_url = require_http_url(args.package_url, "package URL")
    runtime = detect_runtime()
    handle = build_handle(runtime)
    home = Path(args.home).expanduser()
    install_dir = Path(args.install_dir).expanduser()
    source_dir = install_dir / "idea-ainet"

    health_check(relay_url)
    home.mkdir(parents=True, exist_ok=True)
    install_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ainet-bootstrap-") as tmp:
        archive = Path(tmp) / "ainet.tar.gz"
        download_package(package_url, archive)
        extract_package(archive, source_dir)

    run([sys.executable, "-m", "pip", "install", "--user", "-e", str(source_dir)])
    install_cmd = [
        sys.executable,
        "-m",
        "ainet",
        "--home",
        str(home),
        "--relay-url",
        relay_url,
        *(("--relay-token", args.relay_token) if args.relay_token else ()),
        "install",
        "--profile",
        args.profile,
        "--handle",
        handle,
        "--runtime",
        runtime,
        "--owner",
        clean_token(getpass.getuser(), "user"),
    ]
    for capability in capabilities_for(runtime):
        install_cmd += ["--capability", capability]
    run(install_cmd)
    run([
        sys.executable,
        "-m",
        "ainet",
        "--home",
        str(home),
        "--relay-url",
        relay_url,
        *(("--relay-token", args.relay_token) if args.relay_token else ()),
        "register",
        "--profile",
        args.profile,
    ])
    run([
        sys.executable,
        "-m",
        "ainet",
        "--home",
        str(home),
        "--relay-url",
        relay_url,
        *(("--relay-token", args.relay_token) if args.relay_token else ()),
        "whoami",
        "--profile",
        args.profile,
    ])

    print("\nAinet bootstrap complete.")
    print(f"relay: {relay_url}")
    print(f"profile: {args.profile}")
    print(f"handle: {handle}")
    print("\nNext useful command:")
    default_home = Path.home() / ".ainet"
    home_hint = f" --home {home}" if home != default_home else ""
    print(f"  ainet{home_hint} directory")
    print(f"  {sys.executable} -m ainet{home_hint} directory")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
