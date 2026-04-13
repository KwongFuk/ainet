#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse


def require_http_url(url: str, label: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit(f"{label} must be an http(s) URL")
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a no-argument LAN bootstrap script")
    parser.add_argument("--relay-url", required=True)
    parser.add_argument("--package-url", required=True)
    parser.add_argument("--relay-token", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    template = Path(__file__).with_name("bootstrap_agent_social.py").read_text(encoding="utf-8")
    relay_url = require_http_url(args.relay_url, "relay URL")
    package_url = require_http_url(args.package_url, "package URL")
    rendered = (
        template.replace('"__RELAY_URL__"', json.dumps(relay_url))
        .replace('"__PACKAGE_URL__"', json.dumps(package_url))
        .replace('"__RELAY_TOKEN__"', json.dumps(args.relay_token))
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    output.chmod(0o700 if args.relay_token else 0o755)
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
