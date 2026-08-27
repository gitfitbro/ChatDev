## Repo and branch
Repo: ChatDev (fork gitfitbro/ChatDev). Branch from `crew-extensions` at 91704df.
Open your PR against `crew-extensions`, NOT main. Feature branch -> PR -> review.
Never merge. Never run `gh auth switch` or change global config; if a push fails on
auth, report it and stop.

## Read first
- `fleet_view/fx/README.md` — the effect contract. This is your API; follow it exactly.
- `fleet_view/world.html` — how hooks are called (FX.emit) and how characters are drawn.
- `fleet_view/model.py` — the shape of rooms, souls and events.

## Run it
    uv run python -m fleet_view.server      # http://localhost:6500/world.html
Port 6500 may already be in use by the operator's instance — use `--port 6501` and open
that instead. Do not kill a server you did not start.

## Hard rules
1. **You own exactly one new file.** Do not edit world.html, model.py, server.py, the
   README, or another fx/ file. If you believe the contract is missing something, say so
   in your PR description rather than changing it — another crewmate is working in there.
2. **Draw only what is true.** Every character on this floor is one real agent. An effect
   that invents a character, a state, or an event destroys the only thing this screen has
   going for it, which is that you can trust what you see.
3. **Never throw, never block, never fetch.** Degrade to drawing nothing.
4. Animate from `world.frame`, not wall-clock.
5. Canvas primitives only — no external assets, no libraries, no network.

## Acceptance
- Your file loads and runs with the real server against the operator's live fleet.
- Screenshot in the PR description showing the effect on screen.
- Nothing else on the floor changes visually when your effect is idle.
- `uv run pytest tests/ -q` still passes (your file is not covered by tests; do not break others).
