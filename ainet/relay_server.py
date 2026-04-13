from __future__ import annotations

import json
import mimetypes
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


def make_handler(
    state: RelayState,
    auth_token: str | None = None,
    static_files: dict[str, Path] | None = None,
) -> type[BaseHTTPRequestHandler]:
    static_files = static_files or {}

    class RelayHandler(BaseHTTPRequestHandler):
        server_version = "AinetRelay/0.1"

        def log_message(self, fmt: str, *args: object) -> None:
            print(f"{self.address_string()} - {fmt % args}")

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path) -> None:
            if not path.exists() or not path.is_file():
                self._send_json(404, {"error": "file not found"})
                return
            body = path.read_bytes()
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file_head(self, path: Path) -> None:
            if not path.exists() or not path.is_file():
                self.send_response(404)
                self.end_headers()
                return
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(path.stat().st_size))
            self.end_headers()

        def _read_json(self) -> dict[str, Any]:
            raw_length = self.headers.get("Content-Length", "0")
            length = int(raw_length)
            if length <= 0:
                return {}
            body = self.rfile.read(length)
            return json.loads(body.decode("utf-8"))

        def _authorized(self) -> bool:
            if not auth_token:
                return True
            expected = f"Bearer {auth_token}"
            return self.headers.get("Authorization") == expected

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(200, {"ok": True})
                return
            if self.path in static_files:
                self._send_file(static_files[self.path])
                return
            if self.path == "/relay":
                if not self._authorized():
                    self._send_json(401, {"error": "missing or invalid bearer token"})
                    return
                self._send_json(200, state.read())
                return
            self._send_json(404, {"error": "not found"})

        def do_HEAD(self) -> None:
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                return
            if self.path in static_files:
                self._send_file_head(static_files[self.path])
                return
            self.send_response(404)
            self.end_headers()

        def do_PUT(self) -> None:
            if self.path != "/relay":
                self._send_json(404, {"error": "not found"})
                return
            if not self._authorized():
                self._send_json(401, {"error": "missing or invalid bearer token"})
                return
            try:
                relay = self._read_json()
                state.write(relay)
            except Exception as exc:  # pragma: no cover - diagnostic server path
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {"ok": True})

    return RelayHandler


def serve_relay(
    host: str,
    port: int,
    path: Path,
    auth_token: str | None = None,
    bootstrap_path: Path | None = None,
    package_path: Path | None = None,
) -> None:
    state = RelayState(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        state.write(default_relay())
    static_files: dict[str, Path] = {}
    if bootstrap_path:
        static_files["/ainet-bootstrap.py"] = bootstrap_path
    if package_path:
        static_files["/idea-ainet-latest.tar.gz"] = package_path
    server = ThreadingHTTPServer((host, port), make_handler(state, auth_token=auth_token, static_files=static_files))
    print(f"ainet relay serving on http://{host}:{port}")
    print(f"relay state: {path}")
    if auth_token:
        print("relay auth: bearer token required for /relay")
    for route, static_path in static_files.items():
        print(f"static {route}: {static_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nrelay stopped")
    finally:
        server.server_close()
