"""Bridge tools that let a DevAll workflow see (and optionally drive) a real Orca fleet.

The `orca` CLI supervises crewmate agents running in isolated git worktrees. These tools
expose that fleet to workflow agents so a CrewCo graph can be driven by, and reason about,
crewmates that actually exist rather than simulated ones.

Read tools are always available. The tools that change fleet state - dispatching a task,
creating a task, stopping a worker - are refused unless ``ORCA_BRIDGE_ALLOW_WRITES=1`` is
set in the environment, because an agent that can dispatch crewmates can spend real compute
in real repositories.
"""

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_DEFAULT_TIMEOUT_SECONDS = 60
_WRITE_ENV_FLAG = "ORCA_BRIDGE_ALLOW_WRITES"


def _orca_binary() -> Optional[str]:
    return shutil.which(os.environ.get("ORCA_BIN", "orca"))


def _writes_allowed() -> bool:
    return os.environ.get(_WRITE_ENV_FLAG, "").strip() in {"1", "true", "yes"}

def _refuse_write(command: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": "write_not_permitted",
        "command": command,
        "detail": (
            f"Fleet-mutating commands are disabled. Set {_WRITE_ENV_FLAG}=1 in the "
            "environment to allow this workflow to change fleet state."
        ),
    }


def _run(args: List[str], *, timeout: int = _DEFAULT_TIMEOUT_SECONDS) -> Dict[str, Any]:
    """Run an orca subcommand and return a normalized result envelope."""
    binary = _orca_binary()
    if not binary:
        return {"ok": False, "error": "orca_not_found", "detail": "The orca CLI is not on PATH."}

    command = [binary, *args]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "command": " ".join(args), "timeout_seconds": timeout}

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()

    if completed.returncode != 0:
        return {
            "ok": False,
            "error": "orca_failed",
            "command": " ".join(args),
            "exit_code": completed.returncode,
            "stderr": stderr[:4000] or stdout[:4000],
        }

    result: Dict[str, Any] = {"ok": True, "command": " ".join(args)}
    if stdout:
        try:
            result["data"] = json.loads(stdout)
        except ValueError:
            result["output"] = stdout[:20000]
    else:
        result["output"] = ""
    return result


def _newest_run_id() -> Optional[str]:
    """Return the most recent orchestration run id, or None."""
    listed = _run(["orchestration", "run-list", "--limit", "1", "--json"])
    if not listed.get("ok"):
        return None
    data = listed.get("data")
    # The CLI wraps payloads as {"result": {...}}; runs may be a list under several keys.
    for container in (data, (data or {}).get("result") if isinstance(data, dict) else None):
        if not isinstance(container, dict):
            continue
        for key in ("runs", "items", "data"):
            runs = container.get(key)
            if isinstance(runs, list) and runs:
                first = runs[0]
                if isinstance(first, dict):
                    for id_key in ("run_id", "runId", "id"):
                        if first.get(id_key):
                            return str(first[id_key])
    return None


def _run_bound(args: List[str]) -> Dict[str, Any]:
    """Run a command that needs a bound run, retrying once against the newest run.

    Commands like task-list fail with `run_required` when no run is bound to the shell.
    A workflow agent has no shell to bind, so resolve the newest run and retry.
    """
    result = _run(args)
    if result.get("ok") or "--run" in args:
        return result
    if "run_required" not in json.dumps(result):
        return result

    run_id = _newest_run_id()
    if not run_id:
        return result
    retried = _run([*args, "--run", run_id])
    if retried.get("ok"):
        retried["run_id_resolved"] = run_id
    return retried


def _truncate(result: Dict[str, Any], key: str, limit: int) -> Dict[str, Any]:
    """Cap a list inside an orca payload, recording what was dropped.

    A large fleet returns 80+ worker records; handing all of them to a model wastes
    context and slows the node down. The cap is always reported - a silent truncation
    reads as "this is the whole fleet" when it is not.
    """
    if limit <= 0:
        return result
    payload = result.get("data")
    if not isinstance(payload, dict):
        return result
    inner = payload.get("result")
    if not isinstance(inner, dict):
        return result
    items = inner.get(key)
    if not isinstance(items, list) or len(items) <= limit:
        return result

    inner[key] = items[:limit]
    inner.setdefault("truncated", {})[key] = {
        "returned": limit,
        "total": len(items),
        "note": f"Showing {limit} of {len(items)} - raise the limit argument to see more.",
    }
    return result


# ----------------------------------------------------------------------
# Read tools
# ----------------------------------------------------------------------


def orca_fleet_status(limit: int = 20) -> dict:
    """
    Show the current Orca fleet: which worktrees exist and what is running in each.

    This is the "bearings" view - use it first to find out what the crew is already doing
    before dispatching anything new.

    Args:
        limit: Maximum number of worktrees to report.
    """
    return _run(["worktree", "ps", "--limit", str(limit), "--json"])


def orca_task_list(status: str = "", ready_only: bool = False, run_id: str = "", limit: int = 25) -> dict:
    """
    List orchestration tasks in the Orca fleet.

    Args:
        status: Filter to a single task status (e.g. "pending", "running", "completed").
                Leave empty for all statuses.
        ready_only: When True, list only tasks whose dependencies are satisfied.
        run_id: Restrict to one orchestration run. Leave empty for the bound run.
        limit: Maximum tasks to return. Any cap is reported under result.truncated.
               Pass 0 for no cap. Filter with status before raising this.
    """
    args = ["orchestration", "task-list", "--brief", "--json"]
    if status:
        args += ["--status", status]
    if ready_only:
        args.append("--ready")
    if run_id:
        args += ["--run", run_id]
    return _truncate(_run_bound(args), "tasks", limit)


def orca_worker_list(run_id: str = "", terminal_state: str = "", limit: int = 25) -> dict:
    """
    List supervised crewmate terminals and their resource accounting.

    Terminal state is process accounting, reported separately from task status: a completed
    task can still own a live terminal.

    Args:
        run_id: Restrict to one orchestration run. Leave empty for the bound run.
        terminal_state: One of active, reclaimable, retained, release_pending,
                        release_unknown, released. Leave empty for all.
        limit: Maximum workers to return. Any cap is reported under result.truncated.
               Pass 0 for no cap. Filter with terminal_state before raising this.
    """
    args = ["orchestration", "worker-list", "--json"]
    if run_id:
        args += ["--run", run_id]
    if terminal_state:
        args += ["--terminal-state", terminal_state]
    return _truncate(_run_bound(args), "workers", limit)


def orca_task_show(task_id: str) -> dict:
    """
    Show the full record for one orchestration task, including its spec and current status.

    Args:
        task_id: The task identifier, as reported by orca_task_list.
    """
    if not task_id:
        return {"ok": False, "error": "missing_task_id"}
    return _run(["orchestration", "dispatch-show", "--task", task_id, "--json"])


def orca_run_list(limit: int = 10) -> dict:
    """
    List recent orchestration runs, newest first.

    Args:
        limit: Maximum number of runs to return.
    """
    return _run(["orchestration", "run-list", "--limit", str(limit), "--json"])


def orca_inbox(terminal: str = "") -> dict:
    """
    Read pending crewmate messages without acknowledging them.

    Use this to see what crewmates have reported back before deciding what to do next.

    Args:
        terminal: Terminal handle to read for. Leave empty for the bound terminal.
    """
    args = ["orchestration", "check", "--peek", "--json"]
    if terminal:
        args += ["--terminal", terminal]
    return _run_bound(args)


def _heartbeat_age_seconds(stamp: Any) -> Optional[int]:
    """Seconds since an ISO-8601 heartbeat, or None if it cannot be parsed."""
    if not isinstance(stamp, str) or not stamp.strip():
        return None
    text = stamp.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        # Orca also emits "YYYY-MM-DD HH:MM:SS" without a zone.
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int((datetime.now(timezone.utc) - parsed).total_seconds())


def orca_stalled_workers(stall_after_seconds: int = 900, limit: int = 25) -> dict:
    """
    Find crewmates that have gone quiet: live tasks whose heartbeat has aged out.

    A task's status says what it claimed last; the heartbeat says whether anyone is still
    home. Reading them together is how you tell a working crewmate from a stalled one -
    a task can sit in `dispatched` indefinitely after its agent has died.

    Args:
        stall_after_seconds: Heartbeat age past which a crewmate counts as stalled.
                             Default 900 (15 minutes).
        limit: Maximum live tasks to inspect.
    """
    listed = orca_task_list(limit=0)
    if not listed.get("ok"):
        return listed

    inner = (listed.get("data") or {}).get("result") or {}
    tasks = inner.get("tasks") or []
    live = [t for t in tasks if t.get("status") in {"dispatched", "running", "in_progress"}]

    report: List[Dict[str, Any]] = []
    inspected = live[:limit] if limit > 0 else live
    for task in inspected:
        detail = _run(["orchestration", "dispatch-show", "--task", task.get("id", ""), "--json"])
        dispatch = (((detail.get("data") or {}).get("result")) or {}).get("dispatch") or {}
        age = _heartbeat_age_seconds(dispatch.get("last_heartbeat_at"))
        report.append(
            {
                "task_id": task.get("id"),
                "title": (task.get("task_title") or task.get("spec") or "")[:120],
                "status": task.get("status"),
                "assignee_handle": dispatch.get("assignee_handle"),
                "last_heartbeat_at": dispatch.get("last_heartbeat_at"),
                "heartbeat_age_seconds": age,
                # None means the heartbeat was unreadable - unknown, not healthy.
                "stalled": None if age is None else age > stall_after_seconds,
                "failure_count": dispatch.get("failure_count"),
            }
        )

    stalled = [r for r in report if r["stalled"] is True]
    unknown = [r for r in report if r["stalled"] is None]
    return {
        "ok": True,
        "command": "derived: task-list + dispatch-show",
        "stall_after_seconds": stall_after_seconds,
        "live_tasks": len(live),
        "inspected": len(inspected),
        "not_inspected": max(0, len(live) - len(inspected)),
        "stalled_count": len(stalled),
        "unknown_heartbeat_count": len(unknown),
        "workers": report,
    }


# ----------------------------------------------------------------------
# Write tools - gated behind ORCA_BRIDGE_ALLOW_WRITES
# ----------------------------------------------------------------------


def orca_task_create(spec: str, title: str = "") -> dict:
    """
    Create a new orchestration task in the fleet. Requires ORCA_BRIDGE_ALLOW_WRITES=1.

    Args:
        spec: The task brief handed to the crewmate. Be specific about the deliverable.
        title: Optional short title for the task.
    """
    if not _writes_allowed():
        return _refuse_write("orchestration task-create")
    if not spec.strip():
        return {"ok": False, "error": "empty_spec"}

    args = ["orchestration", "task-create", "--spec", spec, "--json"]
    if title:
        # The CLI flag is --task-title; --title is rejected as an unknown flag.
        args += ["--task-title", title]
    return _run(args)


def orca_dispatch(task_id: str, to_handle: str, inject: bool = True) -> dict:
    """
    Dispatch an existing task to a crewmate terminal. Requires ORCA_BRIDGE_ALLOW_WRITES=1.

    Args:
        task_id: The task to dispatch, from orca_task_list.
        to_handle: The crewmate terminal handle to dispatch to.
        inject: Inject the dispatch provenance preamble into the agent's TUI. Injection
                fails until the agent TUI is up, so retry once after a short wait.
    """
    if not _writes_allowed():
        return _refuse_write("orchestration dispatch")
    if not task_id or not to_handle:
        return {"ok": False, "error": "missing_task_or_handle"}

    args = ["orchestration", "dispatch", "--task", task_id, "--to", to_handle, "--json"]
    if inject:
        args.append("--inject")
    return _run(args)


def orca_dispatch_preview(task_id: str, to_handle: str) -> dict:
    """
    Show exactly what a dispatch would send, without sending it. Always permitted.

    Args:
        task_id: The task that would be dispatched.
        to_handle: The crewmate terminal handle that would receive it.
    """
    if not task_id or not to_handle:
        return {"ok": False, "error": "missing_task_or_handle"}
    return _run(
        [
            "orchestration",
            "dispatch",
            "--task",
            task_id,
            "--to",
            to_handle,
            "--dry-run",
            "--return-preamble",
            "--json",
        ]
    )


def orca_task_update(task_id: str, status: str) -> dict:
    """
    Update the status of an orchestration task. Requires ORCA_BRIDGE_ALLOW_WRITES=1.

    Args:
        task_id: The task to update.
        status: The new status (e.g. "running", "completed", "blocked").
    """
    if not _writes_allowed():
        return _refuse_write("orchestration task-update")
    if not task_id or not status:
        return {"ok": False, "error": "missing_task_or_status"}
    # The CLI flag is --id; --task is rejected as an unknown flag.
    return _run(["orchestration", "task-update", "--id", task_id, "--status", status, "--json"])
