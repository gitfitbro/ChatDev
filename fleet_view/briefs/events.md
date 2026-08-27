## Repo and branch
Repo: ChatDev (fork `gitfitbro/ChatDev`, remote is named `fork`, NOT `origin` —
`origin` is upstream OpenBMB and you must never push there).
Branch from `crew-extensions`. Open your PR against `crew-extensions`, NOT main.
Feature branch -> PR -> review. Never merge.

## Push auth — resolved 2026-08-27
The operator's active `gh` account is `gitfitbro`, which HAS push access to
`gitfitbro/ChatDev`. Push normally.

- Do NOT run `gh auth switch`, `gh auth login`, or change any git/gh global config.
  If a push ever fails on auth, report it in your `worker_done` and stop — the first
  mate or the operator resolves it, never you.
- Commit in clean commits as you go, so work survives a blocked push.

## Read first
- `fleet_view/model.py` — the fleet model. Rooms, occupants, states, districts.
- `fleet_view/server.py` — the snapshot cache, the diff that emits events, the HTTP API.
- `fleet_view/catalog.py` — the event catalogue (committed, currently inert).

## Run it
    uv run python -m fleet_view.server --port 6501    # 6500 is the operator's

Do not kill a server you did not start.

## Hard rules
1. **You own the files your brief names, and nothing else.** Another crewmate is
   working in this repo right now. If you need a change outside your files, describe
   it in your PR description instead of making it.
2. **Draw only what is true.** This whole screen is worth having only because what it
   shows is real. Never invent an event, a state, or a relationship. If a source is
   unavailable, degrade and say so in `warnings` — never fabricate a plausible value.
3. **Never crash the snapshot.** Every new code path wraps its failure. A dashboard
   that dies shows nothing, which is worse than a dashboard that shows less.
4. Stdlib only in `server.py`/`model.py`'s import path. No new pip dependencies.
5. `uv run pytest tests/ -q` must still pass.

## Lifecycle
Send `heartbeat` on phase changes and `worker_done` when finished, per your dispatch
preamble. If you are blocked on something only the operator can decide, send an `ask`
rather than guessing.

# Task: wire the event catalogue, and emit the events that matter

You own **`fleet_view/server.py`** and **`fleet_view/catalog.py`**. Nothing else.

## Why
`fleet_view/catalog.py` exists and is inert — nothing calls `record()`. Its job is to
accumulate one row per *distinct kind* of event, so that a designer can draw a sprite
per row. Read its module docstring; the signature scheme is the point.

Today `server.py::_diff` emits exactly five types: `appeared`, `vanished`, `ghosted`,
`returned`, `shipped`. That is a catalogue of five, and the interesting granularity is
missing.

## What to build

**1. Wire the catalogue.** Every emitted event goes through `catalog.record()`. Call
`catalog.flush()` on a slow cadence (counts are worth persisting, but not per event —
`record()` already writes immediately when it sees a NEW kind, which is the case that
matters).

**2. Emit tool events.** `model.py::_occupants` already reads `agent["toolName"]` into
the `doing` field but nothing diffs it. When an occupant's tool changes between
snapshots, emit `{"type": "tool", "tool": <toolName>, ...}`. This is the single
highest-value addition: it is what turns "a character is at a desk" into "a character
is searching the web".

**3. Emit artifact events.** `_occupants` collects verified artifacts (files that
actually exist). When a soul gains one it did not have, emit
`{"type": "artifact", "ext": <suffix without dot>, "path": ..., "name": ...}`.

**4. Emit state transitions.** When a room changes state (`working`/`stalled`/`idle`/
`empty`), emit `{"type": "state", "from": ..., "to": ...}`.

**5. Serve it.** `GET /api/catalog` returns `catalog.all_events()`.

## The things that will catch you out
- **Polling is lossy.** The snapshot refreshes every ~4s; an agent may call five tools
  between polls and you will see one. That is a real limitation — do NOT pretend
  otherwise. Note it in the PR and in a code comment. Never interpolate events you did
  not observe.
- `_soul_index` currently keys on `f"{room_id}:{i}:{kind}"` — the positional `i` means
  a soul's identity shifts if occupant order changes, which would read as a vanish plus
  an appear. Look at whether this is a real bug in practice. If it is, say so; fixing it
  correctly may be worth its own PR rather than a rushed change inside this one.
- The catalogue is written to disk. Do not let a disk error take down a frame.

## Verify
- Run the server against the live fleet, leave it up long enough to catch real tool
  calls, then show `uv run python -m fleet_view.catalog` output in the PR.
- State exactly which event kinds you observed for real, and which you could not
  trigger. An uncatalogued kind is fine; a fabricated one is not.
