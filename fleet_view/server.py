"""Serve the live fleet as JSON, and the office that renders it.

    uv run python -m fleet_view.server          # http://localhost:6500

Deliberately stdlib-only and standalone: it reads the same orca bridge the workflows
use, but shares no port, no process, and no lifecycle with the ChatDev console. One
screen you can leave open while everything else restarts around it.

The renderer is swappable. It consumes GET /api/fleet and nothing else; replacing
index.html with a different look requires no change here or in model.py.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Any, Dict, Optional

from fleet_view.model import build_fleet

HERE = Path(__file__).parent
DEFAULT_PORT = 6500

# Polling the CLI is not free - several subprocesses per build. Serve a shared snapshot
# so ten open tabs cost the same as one.
_CACHE_SECONDS = 4
_lock = threading.Lock()
_snapshot: Optional[Dict[str, Any]] = None
_taken_at = 0.0


def current_fleet(max_age: float = _CACHE_SECONDS) -> Dict[str, Any]:
    global _snapshot, _taken_at
    with _lock:
        if _snapshot is None or (time.time() - _taken_at) > max_age:
            try:
                _snapshot = build_fleet()
            except Exception as exc:  # a dashboard that dies shows nothing
                _snapshot = {"ok": False, "error": "build_failed", "detail": str(exc),
                             "buildings": [], "totals": {}, "warnings": []}
            _taken_at = time.time()
        return _snapshot


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/fleet"):
            payload = json.dumps(current_fleet()).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", payload)
            return

        if self.path.startswith("/api/artifact"):
            self._serve_artifact()
            return

        name = "index.html" if self.path in ("/", "") else self.path.lstrip("/").split("?")[0]
        target = (HERE / name).resolve()
        # Never serve outside this directory.
        if HERE.resolve() not in target.parents or not target.is_file():
            self._send(404, "text/plain; charset=utf-8", b"not found")
            return

        types = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}
        self._send(200, types.get(target.suffix, "application/octet-stream"), target.read_bytes())

    def _serve_artifact(self) -> None:
        """Serve a file ONLY if the current fleet model surfaced it.

        The allowlist is the model itself: an agent said it wrote this, and the file
        exists. That keeps a dashboard from becoming a read-anything endpoint - the
        set of readable paths is whatever the fleet is currently holding up, nothing
        more, and it shrinks again when the agent moves on.
        """
        query = parse_qs(urlparse(self.path).query)
        wanted = (query.get("path") or [""])[0]

        allowed = {a["path"] for a in (current_fleet().get("artifacts") or [])}
        if wanted not in allowed:
            self._send(403, "text/plain; charset=utf-8",
                       b"not an artifact the fleet is currently holding")
            return
        try:
            body = Path(wanted).read_bytes()[:400_000]
        except OSError as exc:
            self._send(404, "text/plain; charset=utf-8", str(exc).encode())
            return
        self._send(200, "text/plain; charset=utf-8", body)

    def _send(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass  # a request log per poll is noise


def main() -> int:
    port = DEFAULT_PORT
    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])

    fleet = current_fleet(max_age=0)
    totals = fleet.get("totals") or {}
    print(f"fleet view  ->  http://localhost:{port}")
    if fleet.get("ok"):
        print(f"  {totals.get('repos', 0)} repos, {totals.get('rooms', 0)} rooms, "
              f"{totals.get('working', 0)} working, {totals.get('stalled', 0)} stalled")
    else:
        print(f"  WARNING: fleet unavailable - {fleet.get('error')}: {fleet.get('detail')}")

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
