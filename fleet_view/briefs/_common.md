## Repo and branch
Repo: ChatDev (fork `gitfitbro/ChatDev`, remote is named `fork`, NOT `origin` —
`origin` is upstream OpenBMB and you must never push there).
Branch from `crew-extensions`. Open your PR against `crew-extensions`, NOT main.
Feature branch -> PR -> review. Never merge.

## KNOWN BLOCKER — read before you start
The operator's active `gh` account is `wrobl`, which does NOT have push access to
`gitfitbro/ChatDev`. Your `git push` WILL fail with 403. This is known and is the
operator's to fix, not yours.

- Do NOT run `gh auth switch`, `gh auth login`, or change any git/gh global config.
- Commit your work locally anyway, in clean commits.
- If the push fails, say so in your `worker_done` and stop. Your commits are safe in
  the worktree and the first mate will push them once auth is resolved.

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
