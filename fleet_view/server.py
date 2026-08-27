"""Serve the live fleet as JSON, and the office that renders it.

    uv run python -m fleet_view.server          # http://localhost:6500

Deliberately stdlib-only and standalone: it reads the same orca bridge the workflows
use, but shares no port, no process, and no lifecycle with the ChatDev console. One
screen you can leave open while everything else restarts around it.

The renderer is swappable. It consumes GET /api/fleet and nothing else; replacing
index.html with a different look requires no change here or in model.py.

GET /api/catalog is for whoever is drawing the sprites rather than for the floor: one
row per distinct kind of event this machine has ever emitted. See catalog.py.
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

from fleet_view import catalog
from fleet_view.model import build_fleet

HERE = Path(__file__).parent
DEFAULT_PORT = 6500

# Polling the CLI is not free - several subprocesses per build. Serve a shared snapshot
# so ten open tabs cost the same as one.
_CACHE_SECONDS = 4
_lock = threading.Lock()
_snapshot: Optional[Dict[str, Any]] = None
_taken_at = 0.0

# The model answers "what is true now". Only something holding two snapshots can answer
# "what just changed", and a crewmate that vanished between polls is precisely the thing
# no single snapshot can ever show.
#
# POLLING IS LOSSY, AND THIS IS NOT A BUG WE CAN FIX HERE. We compare two snapshots taken
# ~_CACHE_SECONDS apart. An agent that calls Bash, Read, Grep, Read, Edit between two
# polls shows us exactly one tool - whichever it happened to be holding when we looked.
# Every event below is therefore something we OBSERVED, and the stream is a sample of the
# truth, never the whole of it. Nothing here interpolates, back-fills, or guesses at the
# calls it missed: an event we did not see is an event that does not exist. A complete
# stream would need the agent to push its calls to us rather than us pulling its state.
_EVENT_TTL_SECONDS = 45
_prev_souls: Optional[Dict[str, Dict[str, Any]]] = None
_prev_rooms: Optional[Dict[str, Dict[str, Any]]] = None
_prev_prs: Dict[str, str] = {}
_events: list[Dict[str, Any]] = []
_event_seq = 0

# The catalogue writes to disk the moment it sees a kind it has never seen, which is the
# case worth a write. Counts are worth keeping too, but not at one fsync per Bash call.
_CATALOG_FLUSH_SECONDS = 120
_last_flush = 0.0


def _split_doing(doing: Optional[str]) -> tuple[Optional[str], str]:
    """`doing` is the model's rendered "Bash: cd /tmp && ls" line; recover its two halves.

    model.py composes this as f"{tool}: {target}" and does not surface `toolName` on its
    own, so the split is the only way to name the tool from out here. Tool names have no
    ": " in them - Bash, WebSearch, mcp__conduit__brain_chat - so the first separator is
    always the right one. A `tool` field on the occupant would be cleaner; that is a
    model.py change, which this PR does not own.
    """
    if not doing:
        return None, ""
    tool, _, target = doing.partition(": ")
    return (tool.strip() or None), target.strip()


def _soul_index(fleet: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Stable identity per occupant, matching the renderer's own id scheme."""
    index: Dict[str, Dict[str, Any]] = {}
    for building in fleet.get("buildings") or []:
        for room in building.get("rooms") or []:
            for i, person in enumerate(room.get("occupants") or []):
                tool, target = _split_doing(person.get("doing"))
                index[f"{room.get('id')}:{i}:{person.get('kind')}"] = {
                    "kind": person.get("kind"),
                    "presence": person.get("presence"),
                    "room": room.get("name"),
                    "repo": building.get("repo"),
                    # Carried for the diff, stripped before the event goes out.
                    "_doing": person.get("doing"),
                    "_tool": tool,
                    "_target": target,
                    "_artifacts": {a["path"]: a for a in (person.get("artifacts") or [])
                                   if a.get("path")},
                }
    return index


def _room_index(fleet: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Room id -> the state it is in, so a transition between polls can be named."""
    index: Dict[str, Dict[str, Any]] = {}
    for building in fleet.get("buildings") or []:
        for room in building.get("rooms") or []:
            if room.get("id"):
                index[room["id"]] = {"state": room.get("state"),
                                     "room": room.get("name"),
                                     "repo": building.get("repo")}
    return index


def _where(soul: Dict[str, Any]) -> Dict[str, Any]:
    """The public half of a soul record - the underscored fields are diff bookkeeping."""
    return {k: v for k, v in soul.items() if not k.startswith("_")}


def _diff_tools(sid: str, was: Optional[Dict[str, Any]], is_now: Dict[str, Any]) -> None:
    """Emit when the tool line changed, which is the closest we get to "a call happened".

    We compare the whole `doing` line, not just the tool name, so a run of Bash calls
    reads as several events rather than one long one. What we cannot see is a repeat of
    the *identical* call, or any call that began and ended inside one poll interval -
    see the note at the top of this file. We emit what we saw and nothing else.
    """
    tool = is_now.get("_tool")
    if not tool or (was is not None and was.get("_doing") == is_now.get("_doing")):
        return
    _emit("tool", sid, {**_where(is_now), "tool": tool, "target": is_now.get("_target") or ""})


def _diff_artifacts(sid: str, was: Optional[Dict[str, Any]], is_now: Dict[str, Any]) -> None:
    """Emit for each verified file a soul is holding up that it was not holding before.

    model.py has already checked these exist on disk, so an artifact event is a claim
    about a real file, never about an agent's account of one.
    """
    had = set((was or {}).get("_artifacts") or {})
    for path, art in (is_now.get("_artifacts") or {}).items():
        if path in had:
            continue
        _emit("artifact", sid, {**_where(is_now), "path": path,
                                "name": art.get("name") or Path(path).name,
                                "ext": Path(path).suffix.lstrip(".").lower() or "none",
                                "bytes": art.get("bytes")})


def _diff(fleet: Dict[str, Any]) -> None:
    """Record what changed since the previous snapshot."""
    global _prev_souls, _prev_rooms, _prev_prs, _event_seq

    now = time.time()
    souls = _soul_index(fleet)
    rooms = _room_index(fleet)

    if _prev_souls is not None:
        for sid, was in _prev_souls.items():
            is_now = souls.get(sid)
            if is_now is None:
                _emit("vanished", sid, _where(was))  # the reaper comes for this one
            elif was["presence"] == "embodied" and is_now["presence"] == "ghost":
                _emit("ghosted", sid, _where(is_now))
            elif was["presence"] == "ghost" and is_now["presence"] == "embodied":
                _emit("returned", sid, _where(is_now))
        for sid, is_now in souls.items():
            was = _prev_souls.get(sid)
            if was is None:
                _emit("appeared", sid, _where(is_now))
            # A soul we have only just met still counts: the tool it is holding and the
            # files it is carrying are things this process observed arrive on the floor.
            _diff_tools(sid, was, is_now)
            _diff_artifacts(sid, was, is_now)

    # A room changing state is the coarsest signal on the screen and the one a viewer
    # feels: a desk going from working to stalled is the whole point of watching.
    if _prev_rooms is not None:
        for rid, is_now in rooms.items():
            was = _prev_rooms.get(rid)
            if was is None or was.get("state") == is_now.get("state"):
                continue  # a room we have not seen before has no transition, only a state
            _emit("state", rid, {"from": was.get("state"), "to": is_now.get("state"),
                                 "room": is_now.get("room"), "repo": is_now.get("repo")})

    # A PR crossing into merged is a thing getting built.
    prs = {f"{p['repo']}#{p['number']}": p.get("state") for p in fleet.get("board") or []}
    for key, state in prs.items():
        if _prev_prs.get(key) and _prev_prs[key] != "merged" and state == "merged":
            repo, number = key.split("#")
            _emit("shipped", key, {"repo": repo, "room": f"#{number}", "kind": "pr"})
    _prev_prs = prs

    _prev_souls = souls
    _prev_rooms = rooms
    _events[:] = [e for e in _events if now - e["at"] < _EVENT_TTL_SECONDS]


def _emit(kind: str, subject: str, info: Dict[str, Any]) -> None:
    global _event_seq
    _event_seq += 1
    event = {"id": _event_seq, "type": kind, "soul": subject, "at": time.time(), **info}
    _events.append(event)
    try:
        catalog.record(event)
    except Exception:
        pass  # the catalogue is a notebook, not a dependency - never cost a frame for it


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
            try:
                _diff(_snapshot)
            except Exception:
                pass  # a bad diff must never cost you the snapshot
            _flush_catalog()
            _snapshot = {**_snapshot, "events": list(_events)}
        return _snapshot


def _flush_catalog() -> None:
    """Persist the catalogue's running counts, well off the hot path."""
    global _last_flush
    now = time.time()
    if now - _last_flush < _CATALOG_FLUSH_SECONDS:
        return
    _last_flush = now
    try:
        catalog.flush()
    except Exception:
        pass  # a full disk is not a reason to stop rendering the fleet


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/fleet"):
            payload = json.dumps(current_fleet()).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", payload)
            return

        if self.path.startswith("/api/catalog"):
            # Every distinct kind of event this machine has ever produced - the input to
            # sprite work, as opposed to /api/fleet's events, which are the last 45s.
            try:
                rows = catalog.all_events()
            except Exception:
                rows = []
            self._send(200, "application/json; charset=utf-8",
                       json.dumps({"count": len(rows), "events": rows}).encode("utf-8"))
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
