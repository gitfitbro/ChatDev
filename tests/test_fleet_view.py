"""Tests for the fleet view - the model's truthfulness and the transition feed.

The transition feed cannot be exercised by waiting: it only speaks when a real agent
appears or vanishes between two polls. So it is tested directly, which is also the only
way to check the case that matters - a crewmate disappearing without anyone noticing.
"""

import pytest

from fleet_view import model, server


def worktree(repo="mvp", name="room", agents=(), live=0, pty=False, pr=None):
    return {
        "repo": repo, "displayName": name, "worktreeId": f"{repo}::{name}",
        "path": f"/w/{repo}/{name}", "branch": f"refs/heads/{name}",
        "agents": list(agents), "liveTerminalCount": live, "hasAttachedPty": pty,
        "linkedPR": pr, "lastActivityAt": 0, "isMainWorktree": False, "unread": False,
    }


def agent(kind="claude", state="done", prompt="", said="", tool=None):
    return {"agentType": kind, "state": state, "prompt": prompt,
            "lastAssistantMessage": said, "toolName": tool, "toolInput": "x"}


@pytest.fixture(autouse=True)
def _reset_transition_state():
    server._prev_souls = None
    server._prev_prs = {}
    server._events[:] = []
    yield


# --- the model ------------------------------------------------------------


def test_an_agent_with_no_terminal_is_a_ghost():
    """A session whose terminal closed still has an agent record. It haunts the room."""
    people = model._occupants(worktree(agents=[agent()], live=0))
    assert people[0]["presence"] == "ghost"


def test_an_agent_with_a_live_terminal_is_embodied():
    people = model._occupants(worktree(agents=[agent()], live=2))
    assert people[0]["presence"] == "embodied"


def test_a_finished_agent_is_idle_even_with_a_live_terminal():
    """`status: active` describes the worktree, not whether anyone is working."""
    assert model._room_state(worktree(agents=[agent(state="done")], live=3, pty=True), set()) == model.IDLE


def test_a_working_agent_makes_the_room_working():
    assert model._room_state(worktree(agents=[agent(state="working")], live=1), set()) == model.WORKING


def test_a_room_with_no_agents_is_empty():
    assert model._room_state(worktree(agents=[]), set()) == model.EMPTY


def test_a_stalled_handle_beats_whatever_the_agent_claims():
    wt = worktree(agents=[agent(state="working")], live=1)
    assert model._room_state(wt, {wt["worktreeId"]}) == model.STALLED


def test_only_artifacts_that_exist_are_reported(tmp_path):
    """An agent naming a file it never wrote is the confabulation to guard against."""
    real = tmp_path / "REPORT.md"
    real.write_text("findings")
    said = f"Report at {real}. Also wrote {tmp_path}/IMAGINARY.md"

    arts = model._occupants(worktree(agents=[agent(said=said)]))[0]["artifacts"]

    assert [a["name"] for a in arts] == ["REPORT.md"]
    assert arts[0]["bytes"] == len("findings")


def test_the_task_id_and_brief_are_lifted_out_of_the_prompt():
    p = "Your task ID is: task_3e4d79a10248 === TASK === [fix-ni-bypass-paths] ship: do it"
    person = model._occupants(worktree(agents=[agent(prompt=p)]))[0]

    assert person["task"] == "task_3e4d79a10248"
    assert person["brief"] == "fix-ni-bypass-paths"


# --- the transition feed --------------------------------------------------


def fleet_with(*people_per_room, board=()):
    rooms = [{"id": f"r{i}", "name": f"room{i}", "occupants": list(ppl)}
             for i, ppl in enumerate(people_per_room)]
    return {"buildings": [{"repo": "mvp", "rooms": rooms}], "board": list(board)}


def test_the_first_poll_reports_nothing():
    """With no previous snapshot, every soul would look new. Say nothing instead."""
    server._diff(fleet_with([{"kind": "claude", "presence": "embodied"}]))

    assert server._events == []


def test_a_crewmate_that_disappears_is_reported():
    """The event no single snapshot can ever show."""
    server._diff(fleet_with([{"kind": "claude", "presence": "embodied"}]))
    server._diff(fleet_with([]))

    assert [e["type"] for e in server._events] == ["vanished"]
    assert server._events[0]["kind"] == "claude"


def test_losing_a_terminal_is_ghosting_not_vanishing():
    server._diff(fleet_with([{"kind": "codex", "presence": "embodied"}]))
    server._diff(fleet_with([{"kind": "codex", "presence": "ghost"}]))

    assert [e["type"] for e in server._events] == ["ghosted"]


def test_reattaching_a_terminal_brings_them_back():
    server._diff(fleet_with([{"kind": "codex", "presence": "ghost"}]))
    server._diff(fleet_with([{"kind": "codex", "presence": "embodied"}]))

    assert [e["type"] for e in server._events] == ["returned"]


def test_a_new_crewmate_is_reported():
    server._diff(fleet_with([]))
    server._diff(fleet_with([{"kind": "grok", "presence": "embodied"}]))

    assert [e["type"] for e in server._events] == ["appeared"]


def test_a_steady_fleet_produces_no_events():
    same = [{"kind": "claude", "presence": "embodied"}]
    server._diff(fleet_with(same))
    server._diff(fleet_with(same))

    assert server._events == []


def test_a_pr_crossing_into_merged_is_a_thing_getting_built():
    opened = ({"repo": "mvp", "number": 7, "state": "open", "room": "a"},)
    merged = ({"repo": "mvp", "number": 7, "state": "merged", "room": "a"},)
    server._diff(fleet_with([], board=opened))
    server._diff(fleet_with([], board=merged))

    assert [e["type"] for e in server._events] == ["shipped"]


def test_a_pr_first_seen_already_merged_is_not_news():
    merged = ({"repo": "mvp", "number": 7, "state": "merged", "room": "a"},)
    server._diff(fleet_with([], board=merged))
    server._diff(fleet_with([], board=merged))

    assert server._events == []


def test_events_expire_so_the_feed_cannot_grow_forever(monkeypatch):
    server._diff(fleet_with([{"kind": "claude", "presence": "embodied"}]))
    server._diff(fleet_with([]))
    assert len(server._events) == 1

    # Age the event past its TTL; the next diff should sweep it.
    server._events[0]["at"] -= server._EVENT_TTL_SECONDS + 1
    server._diff(fleet_with([]))

    assert server._events == []
