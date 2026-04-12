#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a no-argument LAN bootstrap script")
    parser.add_argument("--relay-url", required=True)
    parser.add_argument("--package-url", required=True)
    parser.add_argument("--relay-token", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    template = Path(__file__).with_name("bootstrap_agent_social.py").read_text(encoding="utf-8")
    rendered = (
        template.replace("__RELAY_URL__", args.relay_url)
        .replace("__PACKAGE_URL__", args.package_url)
        .replace("__RELAY_TOKEN__", args.relay_token)
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    output.chmod(0o755)
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
