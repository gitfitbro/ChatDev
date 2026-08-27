# Effects

One file per effect, loaded by `world.html` if it exists. Nothing else imports them and
they do not import each other, so several can be built at once without conflicting.

`world.html` tries to load exactly these, and silently skips any that are missing:

| file | effect |
|---|---|
| `fx/reaper.js` | a figure that comes for a crewmate that vanished |
| `fx/build.js` | something gets constructed when a PR crosses into merged |
| `fx/ceo.js` | the coordinator on the floor, and crewmates walking out to their rooms |
| `fx/sprites.js` | real character art in place of the canvas primitives |

## The contract

```js
window.FleetFX.register({
  name: "reaper",                       // used in error messages

  onFleet(world) {},                    // after every poll (~5s)
  onEvent(event, world) {},             // once per transition, never repeated
  drawUnder(world) {},                  // before characters — floor decals, sites
  drawOver(world) {},                   // after characters — anything above them
});
```

Every hook is optional. A hook that throws is logged and skipped; one broken effect must
never stop the floor.

### `world`

Read-only by convention. Mutating a soul works until the next poll overwrites it.

| | |
|---|---|
| `world.ctx` | the 2D context, already scaled for DPR — draw in CSS pixels |
| `world.w` / `world.h` | canvas size in CSS pixels |
| `world.frame` | monotonic frame counter; use it for animation phase |
| `world.rooms` | `{id,name,repo,x,y,w,h,state,pr,pr_state,occupants}` |
| `world.souls` | `{id,kind,state,presence,x,y,room,artifacts,doing,said,task,brief}` |
| `world.fleet` | the raw `/api/fleet` payload |
| `world.palette` | `{kind:{claude,codex,grok,agent}, state:{working,idle,stalled,empty}}` |
| `world.soul(id)` / `world.room(id)` | lookup |
| `world.openArtifact(a)` | open the reader on an artifact |

### `event`

From the server's snapshot diff. Each is delivered **once**, and only after a baseline
exists — the first poll of a session is deliberately silent.

| `type` | when |
|---|---|
| `vanished` | a crewmate was there last poll and is gone now |
| `appeared` | a new crewmate |
| `ghosted` | its terminal closed; the session is still alive |
| `returned` | a terminal reattached to a ghost |
| `shipped` | a PR crossed into `merged` |

Fields: `id`, `type`, `at` (epoch seconds), `soul` (the id `world.soul()` takes, absent
for `shipped`), `kind`, `room`, `repo`.

**A vanished soul is no longer in `world.souls`.** Capture the position you need from
`world.soul(event.soul)` *during* `onEvent` — by the next frame it is gone.

## Rules

- **Draw only what is true.** Every character on this floor is a real agent; an effect
  that invents one costs the screen its only real asset, which is that you can trust it.
- **Degrade quietly.** No effect may throw, block, fetch, or depend on another effect.
- **Own your file.** Do not edit `world.html`, `model.py`, or another effect.
- **Animate from `world.frame`**, not wall-clock, so the floor stays in step.
