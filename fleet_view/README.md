# Fleet view

One screen showing every agent across every repo, live.

```bash
uv run python -m fleet_view.server        # http://localhost:6500
```

## What is on it

- **Rooms** — one per worktree, grouped by repo. Border colour is state.
- **Occupants** — the agents inside, by kind (claude / codex / grok), each with its own
  state, one line of what it is doing right now, or what it last said.
- **Artifacts** — files an agent announced having written, that actually exist. Click to
  read the real file.
- **Waiting on review** — the PRs Orca is tracking, open first.
- **Task board** — the orchestration queue, live work first.
- **present** — bigger type, chrome hidden. For a second monitor or an OBS capture.

## Three rules it is built on

**Trust the agent, not the worktree.** A worktree stays `status: active` while the agent
inside it reports `done`. Room state comes from the occupants.

**Only artifacts that exist.** An agent naming a file it never wrote is exactly the
confabulation this codebase keeps tripping over, so every path is stat'd before it appears.

**A capped view must say so.** If the fleet exceeds the limit, a banner reports how much is
missing rather than letting a partial view read as complete.

## Swapping the visuals

`index.html` consumes `GET /api/fleet` and nothing else. Replace it wholesale without
touching `model.py` or `server.py`. The model already carries what a richer renderer needs:
`kind` picks a character, `state` picks an animation, `doing`/`said` fill a speech bubble,
`artifacts` are the thing a character holds up.

## Endpoints

| Route | Purpose |
|---|---|
| `GET /api/fleet` | the whole model as JSON |
| `GET /api/artifact?path=…` | one artifact's contents |

`/api/artifact` serves a file **only** if the current model surfaced it. The allowlist is
the fleet itself, so this cannot become a read-anything endpoint, and it shrinks again when
an agent moves on.

## Known gap

PR state comes from Orca's `linkedPR` cache, which lags. A PR merged minutes ago can still
read `open` here. Cross-check with `gh pr list` before acting on the whiteboard.
