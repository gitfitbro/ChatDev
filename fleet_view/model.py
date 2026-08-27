"""A normalized, renderer-agnostic model of the live Orca fleet.

The office picture is a renderer. This is the thing it renders, and it is the half that
has to be true: one screen claiming a crewmate is working when it died an hour ago is
worse than no screen, because you stop checking.

The contract deliberately says nothing about pixels. Rooms, occupants, and a state
enum - swap the visuals without touching this.

    from fleet_view.model import build_fleet
    fleet = build_fleet()          # -> dict, JSON-serializable
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from functions.function_calling import orca

# How long without a heartbeat before a crewmate counts as stalled rather than working.
STALL_AFTER_SECONDS = 900

# Occupant states, in the order a human triages them.
WORKING = "working"      # live terminal, recent heartbeat
STALLED = "stalled"      # claims a task, heartbeat aged out - the one you act on
IDLE = "idle"            # agent present, nothing assigned
EMPTY = "empty"          # no agent; the room exists but nobody is in it


def _ms_age_seconds(stamp: Any) -> Optional[int]:
    """Age in seconds from an epoch-millis timestamp, or None."""
    if not isinstance(stamp, (int, float)) or stamp <= 0:
        return None
    return max(0, int(time.time() - stamp / 1000.0))


_TASK_RE = re.compile(r"task_[0-9a-f]{8,}")
# Agents announce what they produced by naming its path. That sentence is the
# difference between watching agents and watching work.
# Any absolute path with a document-ish extension. Not just /Users: crew briefs live
# under /tmp, and an artifact the fleet cannot see is an artifact nobody reads.
_ARTIFACT_RE = re.compile(r"(/[\w.\-/]+\.(?:md|json|txt|patch|diff|csv|png|svg))")
_BRIEF_RE = re.compile(r"\[([^\]]+)\]\s*(ship|scout)\b")


def _occupants(worktree: Dict[str, Any]) -> List[Dict[str, Any]]:  # noqa: C901
    """Who is in the room, what they are holding, and what they last said.

    Each agent reports its own state, which is finer than the worktree's: a worktree
    stays `active` while the agent inside it is `done`. Trust the agent.
    """
    people: List[Dict[str, Any]] = []
    live_terminals = (worktree.get("liveTerminalCount") or 0) > 0
    for agent in worktree.get("agents") or []:
        if isinstance(agent, str):
            people.append({"kind": agent, "state": "unknown", "doing": None, "artifacts": [],
                           "presence": "embodied" if live_terminals else "ghost",
                           "said": None, "task": None, "brief": None})
            continue
        if not isinstance(agent, dict):
            continue

        prompt = agent.get("prompt") or ""
        task = _TASK_RE.search(prompt)
        brief = _BRIEF_RE.search(prompt)
        tool = agent.get("toolName")
        target = (agent.get("toolInput") or "").strip().replace("\n", " ")

        # Only artifacts that exist. An agent claiming a file it never wrote is
        # exactly the confabulation this whole project keeps tripping over.
        artifacts = []
        for path in dict.fromkeys(_ARTIFACT_RE.findall(agent.get("lastAssistantMessage") or "")):
            try:
                f = Path(path)
                if f.is_file():
                    artifacts.append({"path": path, "name": f.name,
                                      "bytes": f.stat().st_size,
                                      "age_seconds": max(0, int(time.time() - f.stat().st_mtime))})
            except OSError:
                pass

        # A session with nobody attached to it. The agent record is still there, the
        # terminal is not - so it haunts the room rather than working in it.
        people.append({
            "artifacts": artifacts,
            "presence": "embodied" if live_terminals else "ghost",
            "kind": (agent.get("agentType") or "agent").lower(),
            "state": (agent.get("state") or "unknown").lower(),
            # What they are doing right now - the single most useful line on the screen.
            "doing": f"{tool}: {target[:70]}" if tool else None,
            "said": (agent.get("lastAssistantMessage") or "").strip()[:160] or None,
            "task": task.group(0) if task else None,
            "brief": brief.group(1) if brief else agent.get("taskTitle"),
        })
    return people


def _room_state(worktree: Dict[str, Any], stalled_handles: set[str]) -> str:
    """Derive one state from the several fields that half-describe it.

    `status: active` means the worktree is live, not that anyone is working: a
    reclaimable terminal whose agent finished is still 'active'. Presence of an agent
    plus a live terminal is what working actually means.
    """
    people = _occupants(worktree)
    if not people:
        return EMPTY
    if worktree.get("worktreeId") in stalled_handles:
        return STALLED

    states = {p["state"] for p in people}
    # An agent that finished is not working, however alive its terminal looks.
    if states & {"working", "running", "busy", "thinking"}:
        return WORKING
    if (worktree.get("liveTerminalCount") or 0) > 0 and not states <= {"done", "idle", "stopped"}:
        return WORKING
    return IDLE


def build_fleet(limit: int = 200, stall_after_seconds: int = STALL_AFTER_SECONDS) -> Dict[str, Any]:
    """Build the fleet model. Never raises: a dashboard that crashes shows nothing."""
    errors: List[str] = []

    status = orca.orca_fleet_status(limit=limit)
    if not status.get("ok"):
        return {
            "ok": False,
            "error": status.get("error"),
            "detail": status.get("stderr") or status.get("detail"),
            "buildings": [],
            "totals": {},
        }

    inner = ((status.get("data") or {}).get("result")) or {}
    worktrees = inner.get("worktrees") or []
    truncated = inner.get("truncated") or {}

    # Stalled crewmates are a derived signal; if it fails, say so rather than
    # rendering everything as healthy.
    stalled_handles: set[str] = set()
    stalls = orca.orca_stalled_workers(stall_after_seconds=stall_after_seconds)
    if stalls.get("ok"):
        for worker in stalls.get("workers") or []:
            if worker.get("stalled") and worker.get("assignee_handle"):
                stalled_handles.add(worker["assignee_handle"])
    else:
        errors.append("stall detection unavailable - rooms may show working when quiet")

    buildings: Dict[str, Dict[str, Any]] = {}
    for wt in worktrees:
        repo = wt.get("repo") or wt.get("workspaceKind") or "unknown"
        room = {
            "id": wt.get("worktreeId"),
            "name": wt.get("displayName") or (wt.get("path") or "").rsplit("/", 1)[-1],
            "path": wt.get("path"),
            "branch": (wt.get("branch") or "").replace("refs/heads/", ""),
            "state": _room_state(wt, stalled_handles),
            "occupants": _occupants(wt),
            "live_terminals": wt.get("liveTerminalCount") or 0,
            "attached": bool(wt.get("hasAttachedPty")),
            "unread": bool(wt.get("unread")),
            "idle_seconds": _ms_age_seconds(wt.get("lastActivityAt")),
            "pr": (wt.get("linkedPR") or {}).get("number"),
            "pr_state": (wt.get("linkedPR") or {}).get("state"),
            "is_main": bool(wt.get("isMainWorktree")),
            "artifacts": [a for p in _occupants(wt) for a in p["artifacts"]],
        }
        buildings.setdefault(repo, {"repo": repo, "rooms": []})["rooms"].append(room)

    # Busiest repos first, and within a repo the rooms that need attention first.
    order = {STALLED: 0, WORKING: 1, IDLE: 2, EMPTY: 3}
    for b in buildings.values():
        b["rooms"].sort(key=lambda r: (order.get(r["state"], 4), r["name"]))
        b["counts"] = {s: sum(1 for r in b["rooms"] if r["state"] == s)
                       for s in (WORKING, STALLED, IDLE, EMPTY)}

    # Attention first, then anywhere a crewmate actually is, then the empty estate.
    # 63 repos of which most are empty must not push the busy one off the screen.
    ordered = sorted(
        buildings.values(),
        key=lambda b: (
            -b["counts"][STALLED],
            -b["counts"][WORKING],
            -b["counts"][IDLE],
            -len(b["rooms"]),
            b["repo"].lower(),
        ),
    )

    rooms = [r for b in ordered for r in b["rooms"]]

    # WHITEBOARD: what is waiting on a human. Built from the PRs Orca already tracks,
    # so it costs nothing extra and cannot disagree with the rooms beside it.
    seen_pr = set()
    board = []
    for b in ordered:
        for r in b["rooms"]:
            if r["pr"] and (b["repo"], r["pr"]) not in seen_pr:
                seen_pr.add((b["repo"], r["pr"]))
                board.append({"repo": b["repo"], "number": r["pr"],
                              "state": r["pr_state"], "room": r["name"]})
    board.sort(key=lambda p: (p["state"] != "open", p["repo"], -p["number"]))

    # TASK BOARD: the queue, by status, with who holds it.
    tasks = []
    listed = orca.orca_task_list(limit=0)
    if listed.get("ok"):
        for t in (((listed.get("data") or {}).get("result")) or {}).get("tasks") or []:
            title = (t.get("task_title") or t.get("spec") or "").strip()
            tasks.append({"id": t.get("id"), "status": t.get("status"),
                          "title": (title[:90] or t.get("id"))})
    else:
        errors.append("task board unavailable")

    artifacts = [a for r in rooms for a in r["artifacts"]]
    artifacts.sort(key=lambda a: a["age_seconds"])

    return {
        "board": board,
        "tasks": tasks,
        "artifacts": artifacts,
        "ok": True,
        "generated_at": int(time.time()),
        "buildings": ordered,
        "totals": {
            "prs_open": sum(1 for p in board if p["state"] == "open"),
            "tasks_live": sum(1 for t in tasks if t["status"] in ("dispatched", "running", "ready")),
            "artifacts": len(artifacts),
            "repos": len(ordered),
            "rooms": len(rooms),
            "ghosts": sum(1 for r in rooms for p in r["occupants"] if p.get("presence") == "ghost"),
            "souls": sum(len(r["occupants"]) for r in rooms),
            WORKING: sum(1 for r in rooms if r["state"] == WORKING),
            STALLED: sum(1 for r in rooms if r["state"] == STALLED),
            IDLE: sum(1 for r in rooms if r["state"] == IDLE),
            EMPTY: sum(1 for r in rooms if r["state"] == EMPTY),
        },
        # Never present a capped view as the whole fleet.
        "truncated": truncated.get("worktrees"),
        "warnings": errors,
    }
