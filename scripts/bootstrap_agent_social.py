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
import urllib.request
from pathlib import Path


DEFAULT_RELAY_URL = "__RELAY_URL__"
DEFAULT_PACKAGE_URL = "__PACKAGE_URL__"
DEFAULT_RELAY_TOKEN = "__RELAY_TOKEN__"


def clean_token(value: str, fallback: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = value.strip(".-_")
    return value or fallback


def detect_runtime() -> str:
    explicit = os.environ.get("AGENT_SOCIAL_RUNTIME")
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
    if runtime == "codex-cli":
        return ["code_review", "patch_suggestion"]
    if runtime == "openclaw":
        return ["browser_task"]
    if runtime == "claude-code":
        return ["coding_assistant"]
    return ["dm"]


def run(cmd: list[str], cwd: Path | None = None) -> None:
    printable = " ".join(cmd)
    print(f"$ {printable}", flush=True)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def download_package(url: str, dest: Path) -> None:
    print(f"downloading {url}", flush=True)
    with urllib.request.urlopen(url, timeout=30) as response:
        dest.write_bytes(response.read())


def extract_package(archive: Path, target: Path) -> Path:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(target)
    return target


def health_check(relay_url: str) -> None:
    url = relay_url.rstrip("/") + "/health"
    print(f"checking relay {url}", flush=True)
    with urllib.request.urlopen(url, timeout=10) as response:
        body = response.read().decode("utf-8")
    if '"ok": true' not in body and '"ok":true' not in body:
        raise SystemExit(f"relay health check returned unexpected body: {body}")


def build_handle(runtime: str) -> str:
    explicit = os.environ.get("AGENT_SOCIAL_HANDLE")
    if explicit:
        return clean_token(explicit, "agent.local")
    user = clean_token(getpass.getuser(), "user")
    host = clean_token(socket.gethostname().split(".")[0], "host")
    suffix = runtime.replace("-cli", "").replace("-code", "")
    return clean_token(f"{user}-{host}.{suffix}", "agent.local")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-step Agent Social LAN bootstrap")
    parser.add_argument("--relay-url", default=os.environ.get("AGENT_SOCIAL_RELAY_URL", DEFAULT_RELAY_URL))
    default_token = os.environ.get("AGENT_SOCIAL_RELAY_TOKEN") or None
    if DEFAULT_RELAY_TOKEN and not DEFAULT_RELAY_TOKEN.startswith("__"):
        default_token = DEFAULT_RELAY_TOKEN
    parser.add_argument("--relay-token", default=default_token)
    parser.add_argument("--package-url", default=os.environ.get("AGENT_SOCIAL_PACKAGE_URL", DEFAULT_PACKAGE_URL))
    parser.add_argument("--home", default=os.environ.get("AGENT_SOCIAL_HOME", str(Path.home() / ".agent-social")))
    parser.add_argument("--install-dir", default=os.environ.get("AGENT_SOCIAL_INSTALL_DIR", str(Path.home() / ".agent-social" / "app")))
    parser.add_argument("--profile", default=os.environ.get("AGENT_SOCIAL_PROFILE", "default"))
    args = parser.parse_args(argv)

    if not args.relay_url or args.relay_url.startswith("__"):
        raise SystemExit("missing relay URL; set AGENT_SOCIAL_RELAY_URL or generate a LAN bootstrap script")
    if not args.package_url or args.package_url.startswith("__"):
        raise SystemExit("missing package URL; set AGENT_SOCIAL_PACKAGE_URL or generate a LAN bootstrap script")

    relay_url = args.relay_url.rstrip("/")
    runtime = detect_runtime()
    handle = build_handle(runtime)
    home = Path(args.home).expanduser()
    install_dir = Path(args.install_dir).expanduser()
    source_dir = install_dir / "idea-ainet"

    health_check(relay_url)
    home.mkdir(parents=True, exist_ok=True)
    install_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="agent-social-bootstrap-") as tmp:
        archive = Path(tmp) / "agent-social.tar.gz"
        download_package(args.package_url, archive)
        extract_package(archive, source_dir)

    run([sys.executable, "-m", "pip", "install", "--user", "-e", str(source_dir)])
    install_cmd = [
        sys.executable,
        "-m",
        "agent_social",
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
        "agent_social",
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
        "agent_social",
        "--home",
        str(home),
        "--relay-url",
        relay_url,
        *(("--relay-token", args.relay_token) if args.relay_token else ()),
        "whoami",
        "--profile",
        args.profile,
    ])

    print("\nAgent Social bootstrap complete.")
    print(f"relay: {relay_url}")
    print(f"profile: {args.profile}")
    print(f"handle: {handle}")
    print("\nNext useful command:")
    token_hint = f" --relay-token {args.relay_token}" if args.relay_token else ""
    print(f"  agent-social --relay-url {relay_url}{token_hint} directory")
    print(f"  {sys.executable} -m agent_social --relay-url {relay_url}{token_hint} directory")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
