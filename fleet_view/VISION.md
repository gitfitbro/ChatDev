# fleet_view — what this is trying to be

Source: recorded working session, 2026-08-26/27 (Otter transcript, ~1h06m, Sirrele +
Albert). This file is the durable form of that conversation. It is a record of intent,
not a plan of record — nothing here is committed to a schedule.

Ordered roughly by how load-bearing it is, not by how it came up.

---

## 0. The premise

> "I wanted to be more than just, hey, we can just watch the AI do stuff... I wanted to
> portray as close as possible of the actual work being done."

And the reason a dashboard will not do:

> "I'm tired of seeing dashboards... I just want to see my niggas running around."

The whole thing rests on one property: **what is on the screen is real.** An office
picture that invents a character is worse than no picture, because you stop checking it.
Everything below inherits that constraint.

## 1. Granularity — show the work, not the state  *(the biggest gap today)*

Today a character stands in a room and the room has a state. The ask is to show the
**action**:

- Calling a tool has a design *per tool*. Searching the web -> the character walks to a
  computer and searches. Writing -> sits at a desk and writes.
- **Skills become new actions.** Users add skills; each skill can carry its own
  animation. Possibly AI-generated animations for user-supplied skills.
- Connecting to an MCP server gets its own animation.

Status: `fx-events` (task_70ae65c70561) is building the event layer this needs.

## 2. The event catalogue

> "can you have it start documenting like every little event? But just like the unique
> ones... a UI for each different event, you know, or maybe even sprites."

One row per **distinct kind** of event, accumulated from what actually happens, so a
designer has a finite list to draw against. Built: `fleet_view/catalog.py`.

## 3. Artifacts, held up

A character finishes a document and **holds it up** — "your spec is ready" — and you can
click it and read the spec. Plus:

- a task board showing what agents are working on (Asana-like)
- a whiteboard of open PRs: "waiting for review"

Status: partially live. Artifacts, task board and PR whiteboard already render; the
"held up, click to read" interaction is the missing half.

## 4. The environment is generated from the repo

> "scan the repo. What is this repo about? What is the architecture around it. What are
> the features... then start building the visual around the architecture and the layout
> of the repo."

The building is **derived**, not hand-drawn. This is the environment layer, and it is a
different thing from the agents that walk around inside it.

Status: `fx-environment` (task_a60869a63fa4), sourced from conduit.

## 5. Zoom levels — a world, not a floor

> "a world world view of like these are all the projects running... if it's an org with
> like five repos, it's like a bigger structure. If it's just a single repo, it could
> just be like a little house."

Globe -> city -> building -> floor -> desk. Size and form denote scale. Explicitly framed
as **a graph of levels**, and as "an out of the world perspective".

## 6. Adjacency must be earned, not assumed

The correction that matters most:

> "the only reason I would want like cross repo access is just because you're working
> simultaneously, and they're in conjunction with each other... if it's a completely
> another project, like let's say conduit, then I don't visually want that anywhere near
> there. If anything, it's a whole separate ecosystem. Unless we bring in conduit, then
> it starts coming into the environment and starts attaching."

**Grouping by git-remote org is a proxy and is wrong.** Two repos belong near each other
because work crosses between them, not because they share an owner. This is an edge
problem; conduit already holds edges.

Status: org grouping shipped (f1d6ac9) as the cheap version. The real version is open.

## 7. Life and death

Already built, and worth keeping exactly as-is:
- kill the session -> the character **dies**
- close the terminal, session still alive -> a **ghost** wanders
- death is not silent: a **reaper** comes for it — "look, it's your time"

Plus: when a feature ships, you **see something get constructed**. (Shipped: PR #2.)

## 8. Public worlds

Deploy to a site. Little businesses you can walk into and watch. Visit each other. A
globe/map placing builders by real or simulated location. Private by default — you can
**knock on the door**, be let in, and get a limited "through the window" view rather
than full visibility into what the AI is doing.

> "we're building a whole community, a whole ecosystem where people are building shit,
> and we build a visual map for the world to see. These are all the builders."

## 9. Why 8-bit, specifically

Albert raised needing a game engine (Unreal, three.js). The answer was no:

> "Why would we need all that? It's just 8 bit... literal minimal graphics that are kind
> of blocky, kind of like old school Mario... in order to do animation, you just create
> different variations of that 8 bit character in different motions, and you just play
> them."

The stated reason is **iteration speed with Claude** — 8-bit is cheap to generate and
cheap to change. Build the logic first; the UI can be reworked later.

## 10. The bar

> "I want the same level of functionality that I [have in] Orca."

This is not a toy view next to the real tool. It has to be as functional as Orca, which
also means Orca itself has to expose more than it does today.

## 11. Distribution

- Run it on a second monitor all day while working.
- Stream it in OBS while coding — the entertainment is watching the agents build the
  company in real time.
- Open-source it.

---

## Named but unresolved
- A physical desk companion (hardware) acting as the CEO you talk to, orchestrating the
  world.
- "Carl" as the person who might do the real UI pass.
- Whether org view and cross-repo view are one screen or separate screens — asked in the
  session, never settled.

## What is true today (2026-08-27)
19 orgs, 64 repos, 105 rooms. Live: rooms, souls, states, ghosts, artifacts, task board,
PR whiteboard, districts by org, transition events, pixel sprites (PR #3), construction
on ship (PR #2). Not live: any of section 1, 3 (interaction), 4, 5, 6, 8.
