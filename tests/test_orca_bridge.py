"""Tests for the Orca bridge - especially the write gate, which is a safety control."""

import json

import pytest

from functions.function_calling import orca


@pytest.fixture(autouse=True)
def _closed_gate(monkeypatch):
    """Default every test to a closed write gate, as a fresh environment has."""
    monkeypatch.delenv(orca._WRITE_ENV_FLAG, raising=False)


@pytest.fixture
def open_gate(monkeypatch):
    monkeypatch.setenv(orca._WRITE_ENV_FLAG, "1")


def _fake_run(recorder, result):
    def runner(args, **kwargs):
        recorder.append(list(args))
        return dict(result) if isinstance(result, dict) else result

    return runner


@pytest.mark.parametrize(
    "call",
    [
        lambda: orca.orca_dispatch("task_1", "term_1"),
        lambda: orca.orca_task_create("do the thing"),
        lambda: orca.orca_task_update("task_1", "completed"),
    ],
)
def test_write_tools_refuse_while_the_gate_is_closed(call, monkeypatch):
    calls = []
    monkeypatch.setattr(orca, "_run", _fake_run(calls, {"ok": True}))

    result = call()

    assert result["ok"] is False
    assert result["error"] == "write_not_permitted"
    # The refusal must happen before the CLI is touched at all.
    assert calls == []


def test_write_tools_run_once_the_gate_is_open(open_gate, monkeypatch):
    calls = []
    monkeypatch.setattr(orca, "_run", _fake_run(calls, {"ok": True}))

    result = orca.orca_dispatch("task_1", "term_1")

    assert result["ok"] is True
    assert calls == [
        ["orchestration", "dispatch", "--task", "task_1", "--to", "term_1", "--json", "--inject"]
    ]


@pytest.mark.parametrize("value", ["0", "false", "no", "", "  "])
def test_only_affirmative_flag_values_open_the_gate(value, monkeypatch):
    monkeypatch.setenv(orca._WRITE_ENV_FLAG, value)
    monkeypatch.setattr(orca, "_run", _fake_run([], {"ok": True}))

    assert orca.orca_dispatch("task_1", "term_1")["error"] == "write_not_permitted"


def test_dispatch_preview_is_allowed_while_the_gate_is_closed(monkeypatch):
    calls = []
    monkeypatch.setattr(orca, "_run", _fake_run(calls, {"ok": True}))

    result = orca.orca_dispatch_preview("task_1", "term_1")

    assert result["ok"] is True
    assert "--dry-run" in calls[0]
    assert "--inject" not in calls[0]


def test_run_scoped_command_retries_against_the_newest_run(monkeypatch):
    calls = []

    def runner(args, **kwargs):
        calls.append(list(args))
        if args[:2] == ["orchestration", "run-list"]:
            return {"ok": True, "data": {"result": {"runs": [{"runId": "run_abc"}]}}}
        if "--run" in args:
            return {"ok": True, "data": {"tasks": []}}
        return {"ok": False, "error": "orca_failed", "stderr": "run_required"}

    monkeypatch.setattr(orca, "_run", runner)

    result = orca.orca_task_list()

    assert result["ok"] is True
    assert result["run_id_resolved"] == "run_abc"
    assert calls[-1][-2:] == ["--run", "run_abc"]


def test_an_explicit_run_id_is_not_second_guessed(monkeypatch):
    calls = []
    monkeypatch.setattr(
        orca, "_run", _fake_run(calls, {"ok": False, "error": "orca_failed", "stderr": "run_required"})
    )

    orca.orca_task_list(run_id="run_mine")

    # One attempt only: no run-list lookup, no retry.
    assert len(calls) == 1
    assert calls[0][-2:] == ["--run", "run_mine"]


def test_unrelated_failures_are_not_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(
        orca, "_run", _fake_run(calls, {"ok": False, "error": "orca_failed", "stderr": "boom"})
    )

    result = orca.orca_task_list()

    assert result["ok"] is False
    assert len(calls) == 1


def test_missing_arguments_are_rejected_before_the_gate(monkeypatch, open_gate):
    calls = []
    monkeypatch.setattr(orca, "_run", _fake_run(calls, {"ok": True}))

    assert orca.orca_dispatch("", "term_1")["error"] == "missing_task_or_handle"
    assert orca.orca_task_create("   ")["error"] == "empty_spec"
    assert orca.orca_task_show("")["error"] == "missing_task_id"
    assert calls == []


def test_missing_binary_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(orca, "_orca_binary", lambda: None)

    result = orca._run(["worktree", "ps"])

    assert result == {
        "ok": False,
        "error": "orca_not_found",
        "detail": "The orca CLI is not on PATH.",
    }


def test_non_json_output_is_preserved_as_text(monkeypatch):
    class Completed:
        returncode = 0
        stdout = "not json at all"
        stderr = ""

    monkeypatch.setattr(orca, "_orca_binary", lambda: "/usr/local/bin/orca")
    monkeypatch.setattr(orca.subprocess, "run", lambda *a, **k: Completed())

    result = orca._run(["worktree", "ps"])

    assert result["ok"] is True
    assert result["output"] == "not json at all"
    assert "data" not in result


def test_refusal_payload_is_json_serializable():
    """Tool results are handed to the model, so they must survive serialization."""
    payload = orca.orca_dispatch("task_1", "term_1")

    assert json.loads(json.dumps(payload))["error"] == "write_not_permitted"


def _payload(key, count):
    return {"ok": True, "data": {"result": {key: [{"id": i} for i in range(count)]}}}


def test_long_lists_are_capped_and_the_cap_is_reported(monkeypatch):
    monkeypatch.setattr(orca, "_run", _fake_run([], _payload("workers", 83)))

    result = orca.orca_worker_list(limit=25)
    inner = result["data"]["result"]

    assert len(inner["workers"]) == 25
    assert inner["truncated"]["workers"] == {
        "returned": 25,
        "total": 83,
        "note": "Showing 25 of 83 - raise the limit argument to see more.",
    }


def test_a_zero_limit_means_no_cap(monkeypatch):
    monkeypatch.setattr(orca, "_run", _fake_run([], _payload("workers", 83)))

    inner = orca.orca_worker_list(limit=0)["data"]["result"]

    assert len(inner["workers"]) == 83
    assert "truncated" not in inner


def test_a_short_list_is_left_alone(monkeypatch):
    monkeypatch.setattr(orca, "_run", _fake_run([], _payload("tasks", 3)))

    inner = orca.orca_task_list(limit=25)["data"]["result"]

    assert len(inner["tasks"]) == 3
    assert "truncated" not in inner


def test_truncation_survives_an_unexpected_payload_shape(monkeypatch):
    monkeypatch.setattr(orca, "_run", _fake_run([], {"ok": True, "output": "plain text"}))

    assert orca.orca_task_list(limit=5)["output"] == "plain text"


# --- stall detection -------------------------------------------------------


@pytest.mark.parametrize(
    "stamp",
    ["", None, "not a date", "2026-13-45T99:99:99Z", 12345],
)
def test_unparseable_heartbeats_return_none_not_zero(stamp):
    """None means unknown. Returning 0 would read as 'just beat' - healthy - which is worse."""
    assert orca._heartbeat_age_seconds(stamp) is None


@pytest.mark.parametrize(
    "stamp",
    ["2026-08-26T11:30:52Z", "2026-08-26 11:30:52", "2026-08-26T11:30:52+00:00"],
)
def test_the_heartbeat_formats_orca_actually_emits_all_parse(stamp):
    assert isinstance(orca._heartbeat_age_seconds(stamp), int)


def _stall_env(monkeypatch, heartbeat, statuses=("dispatched",)):
    tasks = [{"id": f"task_{i}", "status": s, "task_title": f"t{i}"} for i, s in enumerate(statuses)]

    def runner(args, **kwargs):
        if args[:2] == ["orchestration", "task-list"]:
            return {"ok": True, "data": {"result": {"tasks": tasks}}}
        if args[:2] == ["orchestration", "dispatch-show"]:
            return {
                "ok": True,
                "data": {"result": {"dispatch": {"last_heartbeat_at": heartbeat,
                                                 "assignee_handle": "term_x"}}},
            }
        return {"ok": True, "data": {}}

    monkeypatch.setattr(orca, "_run", runner)


def test_a_quiet_crewmate_is_reported_stalled(monkeypatch):
    _stall_env(monkeypatch, "2020-01-01T00:00:00Z")

    result = orca.orca_stalled_workers(stall_after_seconds=900)

    assert result["stalled_count"] == 1
    assert result["workers"][0]["stalled"] is True


def test_a_recent_heartbeat_is_not_stalled(monkeypatch):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _stall_env(monkeypatch, now)

    result = orca.orca_stalled_workers(stall_after_seconds=900)

    assert result["stalled_count"] == 0
    assert result["workers"][0]["stalled"] is False


def test_an_unreadable_heartbeat_is_unknown_not_healthy(monkeypatch):
    _stall_env(monkeypatch, "garbage")

    result = orca.orca_stalled_workers()

    assert result["unknown_heartbeat_count"] == 1
    assert result["stalled_count"] == 0
    assert result["workers"][0]["stalled"] is None


def test_only_live_tasks_are_inspected(monkeypatch):
    _stall_env(monkeypatch, "2020-01-01T00:00:00Z",
               statuses=("dispatched", "completed", "failed", "running"))

    result = orca.orca_stalled_workers()

    assert result["live_tasks"] == 2  # dispatched + running only


def test_inspection_cap_is_reported_not_silent(monkeypatch):
    _stall_env(monkeypatch, "2020-01-01T00:00:00Z", statuses=("dispatched",) * 10)

    result = orca.orca_stalled_workers(limit=3)

    assert result["inspected"] == 3
    assert result["not_inspected"] == 7
