from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .cli import default_relay, read_json, write_json_atomic


def normalize_relay(relay: dict[str, Any]) -> dict[str, Any]:
    base = default_relay()
    for key, value in base.items():
        relay.setdefault(key, value)
    return relay


class RelayState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()

    def read(self) -> dict[str, Any]:
        with self.lock:
            return normalize_relay(read_json(self.path, default_relay()))

    def write(self, relay: dict[str, Any]) -> None:
        with self.lock:
            write_json_atomic(self.path, normalize_relay(relay))


def make_handler(state: RelayState) -> type[BaseHTTPRequestHandler]:
    class RelayHandler(BaseHTTPRequestHandler):
        server_version = "AgentSocialRelay/0.1"

        def log_message(self, fmt: str, *args: object) -> None:
            print(f"{self.address_string()} - {fmt % args}")

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any]:
            raw_length = self.headers.get("Content-Length", "0")
            length = int(raw_length)
            if length <= 0:
                return {}
            body = self.rfile.read(length)
            return json.loads(body.decode("utf-8"))

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(200, {"ok": True})
                return
            if self.path == "/relay":
                self._send_json(200, state.read())
                return
            self._send_json(404, {"error": "not found"})

        def do_PUT(self) -> None:
            if self.path != "/relay":
                self._send_json(404, {"error": "not found"})
                return
            try:
                relay = self._read_json()
                state.write(relay)
            except Exception as exc:  # pragma: no cover - diagnostic server path
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {"ok": True})

    return RelayHandler


def serve_relay(host: str, port: int, path: Path) -> None:
    state = RelayState(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        state.write(default_relay())
    server = ThreadingHTTPServer((host, port), make_handler(state))
    print(f"agent-social relay serving on http://{host}:{port}")
    print(f"relay state: {path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nrelay stopped")
    finally:
        server.server_close()
