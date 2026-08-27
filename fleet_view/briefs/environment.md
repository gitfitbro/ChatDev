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

# Task: an environment layer, sourced from conduit

You own **`fleet_view/environment.py`** (new file). Nothing else. Do NOT edit
`server.py`, `model.py`, or anything under `fx/` — other crewmates hold those. The
first mate wires your module in afterwards; your job is to make it correct and provable
standalone.

## Why
The floor currently derives everything from the orca CLI: who is alive, what room they
are in. That is the *live* layer and it is trustworthy — orca says a terminal is live,
so the character is alive.

What is missing is the *environment*: what a repo actually is, what its architecture
looks like, and which repos are genuinely related. Today the floor groups repos by
the org in their git remote, which is a cheap proxy — it puts two unrelated repos
together because they share an owner, and separates two repos whose work crosses over
daily.

Conduit already holds the better answer. Verified numbers in the `fyx` brain:
2,188 atoms, 1,606 entities, 1,605 edges, 1,941 source documents — including
`linked_repo:repo_file` (1,604 sources).

## Truth grade — the most important paragraph in this brief
Conduit's graph is LLM-derived. The orca layer is not. **These two must never be
presented as the same kind of fact.** Everything you return is scenery: it may be
wrong, and being wrong about scenery is survivable. Nothing you return may ever be
used to claim a crewmate is alive, working, or dead.

Mark it in the data. Every value you emit carries its provenance and a confidence you
can defend.

## The interface (contract — do not change it)
```python
def build_environment(repos: list[str], brain: str = "fyx") -> dict:
    """Never raises. On failure returns the SAME schema with ok=False and the reason
    in warnings - never a bare {}."""
```
A caller must be able to tell "conduit says these repos are unrelated" from "conduit
could not be reached". A bare `{}` collapses those into one value, which is the silent
false claim this whole project exists to prevent. The renderer branches on `ok` and on
emptiness, never on shape.

- conduit binary missing -> `ok: False`, `warnings: ["conduit CLI not found on PATH"]`
- binary present, brain unreachable -> `ok: False` with that reason
- brain reachable but no evidence for any edge -> **`ok: True`**, `edges: []`, plus a
  warning that the graph carried no repo-to-repo evidence. This is a SUCCESSFUL answer,
  not a failure, and keeping it distinct from the failures is the point of the task.

returning:
```python
{
  "ok": bool,
  "source": "conduit",
  "brain": "fyx",
  "generated_at": <epoch int>,
  "repos": {                       # keyed by the repo name the fleet model uses
     "<repo>": {"summary": str|None, "themes": [str], "confidence": float,
                "evidence": [str]},   # evidence = conduit ids you can point at
  },
  "edges": [                       # why two repos belong near each other
     {"a": "<repo>", "b": "<repo>", "weight": float, "why": str, "evidence": [str]},
  ],
  "warnings": [str],
}
```

## How to reach conduit
Use the **`conduit` CLI** (`~/.local/bin/conduit`) — `conduit brains`, `conduit
sources`, `conduit insights`, `conduit --help`. It is the dependable surface. Do not
require an MCP server to be running, and do not add a Python dependency on conduit —
shell out, parse JSON, and degrade to `{}` if the binary is missing.

**Read-only. You must not ingest, write, mutate, or run any pipeline that alters a
brain.** If a useful command would write, describe it in the PR instead of running it.

## The real question to answer
Can conduit actually tell you that repo A and repo B are related, from evidence — not
from sharing an owner? Find out. If the honest answer is "not yet, the graph does not
carry that", then **say so and return no edges**. A correct empty result is the
deliverable; invented adjacency is worse than the org grouping it replaces.

## Verify
- `python -m fleet_view.environment` prints the JSON for the operator's real repos.
- In the PR, show the actual output, and state plainly which fields are evidence-backed
  and which are empty because the data is not there.
