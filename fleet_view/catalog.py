"""Every distinct kind of event the fleet has produced, remembered across restarts.

Nobody can draw a sprite for an event they have never seen. The renderer does not need
the stream of events - it needs the *set*: which tools get called, what kinds of
artifact get held up, which way a soul left the floor. That set is small, it grows
slowly, and it is the actual input to sprite work.

So: watch the stream, keep one row per distinct kind, write it down.

    uv run python -m fleet_view.catalog        # print the catalogue

Seeded by nothing. A row exists here because it happened on this machine, which is the
only claim this file makes - the same rule the floor itself runs on.

Signatures, not types. `tool` is one event type but forty different sprites, so the
catalogue keys on `tool:Bash`, `tool:WebSearch`, `tool:mcp__conduit__brain_chat` - the
granularity a designer actually needs. `vanished` has no such axis, so it stays one row.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

CATALOG_PATH = Path(__file__).parent / "data" / "events.catalog.json"

# `FLEET_CATALOG_PATH` names a catalogue of one's own. Two servers sharing this file
# would each flush their whole in-memory copy over the other's counts, so a second one
# should point somewhere else rather than fight over the operator's.
_PATH_ENV = "FLEET_CATALOG_PATH"


def _path() -> Path:
    """Resolved per call, so pointing this elsewhere needs no reimport."""
    return Path(os.environ.get(_PATH_ENV) or CATALOG_PATH)


def _inert() -> bool:
    """Whether to write nothing at all.

    A fixture event did not happen on this machine. The one claim this file makes is
    that every row is something the fleet really did, so a test suite building a fake
    worktree out of dicts must not leave `appeared repo='mvp' room='room0'` behind for
    a designer to draw a sprite against. Under pytest we go quiet - unless the run named
    a catalogue of its own, in which case it plainly means to exercise this code.

    Checked per call rather than at import: pytest sets its marker per test, not on
    collection, so an import-time read would see nothing and write anyway.
    """
    return "PYTEST_CURRENT_TEST" in os.environ and not os.environ.get(_PATH_ENV)


# Fields that differ on every single occurrence. Keeping them would make the stored
# sample a random event rather than an illustration of its kind.
_VOLATILE = {"id", "at", "soul"}

_lock = threading.Lock()
_catalog: Dict[str, Dict[str, Any]] = {}
_loaded = False


def signature(event: Dict[str, Any]) -> str:
    """The identity a sprite would be drawn against, not the wire type."""
    kind = event.get("type") or "unknown"
    if kind == "tool":
        return f"tool:{event.get('tool') or 'unknown'}"
    if kind == "artifact":
        return f"artifact:{event.get('ext') or 'none'}"
    if kind == "state":
        return f"state:{event.get('from') or '?'}->{event.get('to') or '?'}"
    return str(kind)


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        stored = json.loads(_path().read_text())
        for row in stored.get("events") or []:
            if row.get("signature"):
                _catalog[row["signature"]] = row
    except (OSError, ValueError):
        pass  # a missing or corrupt catalogue is an empty one, never a crash


def _save() -> None:
    """Write the catalogue. Best effort: losing a row must never cost a frame."""
    try:
        target = _path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(
            {"updated_at": int(time.time()), "count": len(_catalog),
             "events": sorted(_catalog.values(), key=lambda r: r["signature"])},
            indent=2, sort_keys=True) + "\n")
    except OSError:
        pass


def record(event: Dict[str, Any]) -> None:
    """Note that this kind of event happened. Cheap on the hot path, durable off it."""
    if _inert():
        return
    sig = signature(event)
    with _lock:
        _load()
        row = _catalog.get(sig)
        now = int(time.time())
        if row is None:
            _catalog[sig] = {
                "signature": sig,
                "type": event.get("type"),
                "first_seen": now,
                "last_seen": now,
                "count": 1,
                # What a sprite can key off. Stored once, from the first occurrence.
                "sample": {k: v for k, v in event.items() if k not in _VOLATILE},
                "sprite": None,       # filled in by whoever designs one
            }
            _save()                   # a NEW kind is the only thing worth a write
            return
        row["count"] += 1
        row["last_seen"] = now


def flush() -> None:
    """Persist counts. Called on a slow cadence, not per event."""
    if _inert():
        return
    with _lock:
        _load()
        if _catalog:
            _save()


def all_events() -> List[Dict[str, Any]]:
    with _lock:
        _load()
        return sorted(_catalog.values(), key=lambda r: (r["type"] or "", r["signature"]))


def main() -> int:
    rows = all_events()
    if not rows:
        print("no events catalogued yet - run the server and leave it open")
        print(f"(catalogue lives at {_path()})")
        return 0

    width = max(len(r["signature"]) for r in rows)
    print(f"{len(rows)} distinct events   {_path()}\n")
    print(f"{'SIGNATURE'.ljust(width)}  {'SEEN':>6}  SPRITE")
    for row in rows:
        print(f"{row['signature'].ljust(width)}  {row['count']:>6}  {row['sprite'] or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
