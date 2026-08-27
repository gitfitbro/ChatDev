# Local extensions to ChatDev 2.0 (DevAll)

Four additions on top of upstream `main`, built 2026-08-26. Nothing upstream was modified
except two dependency files and the provider registry.

## 1. Anthropic provider

`runtime/node/agent/providers/anthropic_provider.py` — Claude via the official Anthropic SDK,
registered as `provider: anthropic` alongside the shipped `openai` and `gemini` providers.

Conversation mapping (DevAll → Messages API):

| DevAll role | Anthropic |
|---|---|
| `SYSTEM` | top-level `system` parameter, all system turns concatenated |
| `USER` | user message with text / image / document blocks |
| `ASSISTANT` | assistant message; `tool_calls` become `tool_use` blocks |
| `TOOL` | user message with `tool_result` blocks, consecutive ones merged into one turn |

Things it handles that a naive port gets wrong:

- **Thinking replay.** The raw response blocks are stashed in `message.metadata.anthropic_content`
  and replayed verbatim on the next turn, so a `thinking` block preceding a `tool_use` survives
  the round trip instead of being reconstructed from text and rejected.
- **Sampling params.** `temperature` / `top_p` / `top_k` are dropped for models that removed them
  (Opus 5, Opus 4.8/4.7, Sonnet 5, Fable 5) — a workflow YAML carrying `temperature: 0.7` from an
  OpenAI node would otherwise 400.
- **Foreign base URLs.** `.env` ships one `BASE_URL` shared by every provider. If it points at
  `api.openai.com` or Google, the provider ignores it and uses the SDK default rather than sending
  Claude traffic to OpenAI. Set `ANTHROPIC_BASE_URL` for a genuine override.
- **Parallel tool results** land in a single user turn, per the Messages API contract.
- **Streaming** kicks in automatically above `max_tokens > 8192` to avoid HTTP timeouts.
- **Prompt caching** is on by default (`params.cache: false` to disable) — the role prompt and
  replayed history stay warm across a workflow's many turns.

Extra `params` keys pass straight through: `max_tokens`, `effort` (nested into `output_config`),
`thinking`, `stream`, `cache`.

Tests: `tests/test_anthropic_provider.py` — 17 cases, no network.

```bash
uv run pytest tests/test_anthropic_provider.py -q
```

Requires `ANTHROPIC_API_KEY` in `.env`.

## 2. `yaml_instance/crew.yaml` — CrewCo

The Orca crew model as a DevAll workflow, running on Claude:

```
Captain → First Mate → { Scout, Crew Deck → { Ship A, Ship B } } → Reviewer → Quartermaster
                                    ↑                                  │
                                    └──── Rework Loop Counter ←─────────┘  (no <APPROVED>)
```

- **Captain** sets the objective and DONE WHEN criteria. No implementation, no assignments.
- **First Mate** splits it into one scout brief and two non-overlapping ship briefs.
- **Scout** is report-only — given read/search tools and *no* write tools, deliberately.
- **Ship Crewmates A/B** deliver files and run them. Full file + code-execution tools.
- **Reviewer** is the supervision gate: verifies by reading and running, emits `<APPROVED>` or
  a numbered REWORK addressed to a named crewmate.
- **Rework Loop Counter** bounds the loop at 2 iterations.
- **Quartermaster** writes the crew log (OUTCOME / LANDED / CREW / GAPS / NEXT BEARING).

**Crew Deck** is a `passthrough` that exists for a graph-engine reason: a cycle must have exactly
one triggered entry node, and both ships entering the rework loop directly is two. It is the single
door into the loop.

Agents write into `WareHouse/<run_id>/code_workspace/`, not the repo root.

## 3. Orca bridge

`functions/function_calling/orca.py` — tool namespace that shells out to the real `orca` CLI, so a
workflow can reason about crewmates that actually exist.

Read tools (always available): `orca_fleet_status`, `orca_task_list`, `orca_worker_list`,
`orca_task_show`, `orca_run_list`, `orca_inbox`, `orca_dispatch_preview`.

Run-scoped commands (`task-list`, `worker-list`, `check`) fail with `run_required` when no run is
bound to the shell — and a workflow agent has no shell to bind. Those tools resolve the newest run
via `run-list` and retry once, reporting the run they used as `run_id_resolved`.

Write tools (**refused unless `ORCA_BRIDGE_ALLOW_WRITES=1`**): `orca_task_create`, `orca_dispatch`,
`orca_task_update`. An agent that can dispatch crewmates spends real compute in real repositories,
so the gate is off by default and the refusal is explicit rather than silent.

`yaml_instance/crew_fleet.yaml` uses the read tools: **Lookout** inventories the fleet →
**Navigator** finds ghost tasks, orphaned terminals, and stalls → **Bearings** writes the report.

List tools cap their output (`limit=25` by default, `limit=0` for none) and **always report the
cap** under `result.truncated` — a fleet of 83 workers otherwise fills a node's context and reads
as though it were the whole picture. Filter with `status` / `terminal_state` before raising it.

**Stall detection.** `orca_stalled_workers` joins `task-list` to each task's `dispatch-show`
heartbeat and reports `heartbeat_age_seconds` + a `stalled` flag. A task sits in `dispatched`
forever after its agent dies — status is a *claim*, the heartbeat is the *evidence*. An
unparseable heartbeat yields `stalled: null` (unknown), never `false`, because "unknown" must
not read as "healthy".

**Ack semantics.** `orca_inbox` uses `--peek`, so reading a crewmate's messages never marks them
read and never replays heartbeats at you. Acknowledging is a state change and stays behind the
write gate — there is deliberately no un-gated ack tool.

Tests: `tests/test_orca_bridge.py` — 34 cases, no CLI calls. The write gate is a safety control,
so it is tested directly: every write tool refuses *before* the CLI is touched, only affirmative
flag values open it, and `dispatch_preview` stays available while it is closed.

## 4. `yaml_instance/crew_dispatch.yaml` — the canvas drives the real fleet

Where `crew.yaml` simulates crewmates and `crew_fleet.yaml` watches real ones, this dispatches them:

```
Captain → Berth Scout → First Mate → [ Captain's Gate ] → Dispatcher → Supervisor
                                            │
                                            └── (no APPROVE) → Stand Down
```

- **Captain** sets the objective and a restrictive SCOPE — paths not named are out of bounds.
- **Berth Scout** reads the live fleet for FREE BERTHS, OCCUPIED handles, and COLLISIONS against
  that scope. A dispatch into a busy berth, or into files another crewmate is already editing,
  is caught here rather than at merge time.
- **First Mate** writes real task specs, calls `orca_task_create`, and previews each dispatch with
  `orca_dispatch_preview`. It never dispatches.
- **Captain's Gate** is a `human` node. Nothing reaches a real crewmate without a reply containing
  `APPROVE`; `APPROVE <task ids>` dispatches only those.
- **Dispatcher** fires the approved tasks, retries a failed `--inject` exactly once, and reports
  refusals and failures verbatim.
- **Stand Down** records a withheld approval, so a non-approval ends with a reason rather than
  silence — and notes that created tasks still exist and can be dispatched later.
- **Supervisor** reports where the dispatched crewmates actually stand.

The `Captain's Gate → Dispatcher` edge carries only the approval, so the plan and berth report
reach the Dispatcher, Stand Down, and Supervisor over `trigger: false, carry_data: true` edges:
the data flows to them, but only the gate decides *when* they run. Without those, the Dispatcher
sees the bare word `APPROVE` and has no task ids — it refuses, correctly, rather than guessing.

**With the write gate closed the whole graph still runs**, degrading to a dry run: `task_create`
and `dispatch` return `write_not_permitted`, the First Mate reports `MODE: DRY RUN`, and the
Dispatcher reports the refusals. That is the safe way to read a plan before opening the gate.

```bash
uv run python run_dispatch_demo.py "<task>"                 # dry run
ORCA_BRIDGE_ALLOW_WRITES=1 uv run python run_dispatch_demo.py "<task>"   # spawns real crewmates
```

The human gate falls back to a stdin channel headlessly; in the console it pauses on the Launch tab.

```bash
uv run python run_fleet_demo.py    # bearings on the live fleet
uv run python run_crew_demo.py     # CrewCo on a sample task
```

## Verification discipline

These workflows are built around one rule: **an agent's report is a claim, not evidence.**

- **Evidence grading.** Every report node must tag each factual claim `[VERIFIED: <tool call or
  file:line>]`, `[INFERRED: <what from>]`, or `[UNVERIFIED]`, and collect the UNVERIFIED ones at
  the top. Two failure modes are called out explicitly in the prompt because they already
  happened here: a tool returning `ok=false` proves nothing, and truncated output is not the
  whole picture.
- **Reported caps, never silent ones.** Bridge list tools cap output and say so. A cap that
  doesn't announce itself reads as "this is the whole fleet" — which is how a Navigator once
  described 19 of 104 worktrees as the fleet.
- **The gate reads before it approves.** `run_dispatch_supervised.py` writes the plan to a file
  and blocks on a decision file, instead of piping `APPROVE` at a plan nobody read. That caught a
  plan where the First Mate had correctly *withheld* the berth — auto-approving would have
  dispatched a scout into the wrong repo.
- **Heartbeats over status.** See stall detection above.

## Known rough edges

- ~~Quartermaster reported files "at repo root" when they were in `WareHouse/<run>/code_workspace/`~~
  — fixed: it must now quote an absolute path a tool returned, or write "path unconfirmed".
- ~~The crew renamed a function from the spec without flagging it~~ — fixed: the Reviewer now
  treats a silent rename of a specified name as a REWORK.
- ~~`orca_task_show` on a large fleet generates a long tool loop~~ — partly addressed: list tools
  now cap and report. The Navigator can still chase many suspects; cap that in its prompt if it
  becomes a problem.
- The Berth Scout takes ~90s on a 100-worktree fleet — three tool calls over large payloads. The
  cap helps; a `--status`-filtered first pass would help more.
