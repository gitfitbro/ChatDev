"""Run crew_dispatch with the human gate answered by a supervisor, not a blind pipe.

Piping `APPROVE` into the gate approves a plan nobody read - which defeats the point of
having a gate. This runner instead hands the gate a callback: the plan is written to a file,
the run blocks, and an approver decides from the plan text.

    python run_dispatch_supervised.py "<task>" [--auto-approve-if-dry-run]

By default it refuses at the gate and prints the plan, so you can read it and then re-run
with an explicit decision. `--approve-file PATH` reads the decision from a file, which lets
a supervisor drop `APPROVE` (or `APPROVE task_x`) in only after reading the plan.
"""

import argparse
import os
import pathlib
import sys
import time

from entity.messages import MessageBlock
from utils.human_prompt import PromptResult
from runtime.sdk import run_workflow
import workflow.graph as graph_module


PLAN_PATH = pathlib.Path("dispatch_plan.txt")
DEFAULT_TASK = (
    "Scout task only: inventory which of my Orca worktrees have open PRs that are already "
    "merged, so the terminals can be reclaimed. Scope: read-only, ~/orca/workspaces. One crewmate."
)


class SupervisedGate:
    """A prompt channel that writes the plan out and waits for a decision file."""

    def __init__(self, approve_file: pathlib.Path | None, timeout_seconds: int, poll_seconds: int = 5):
        self.approve_file = approve_file
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds

    def request(self, *, node_id, task, inputs=None, metadata=None):
        PLAN_PATH.write_text(inputs or "")
        print(f"\n[gate] {node_id} is waiting. Plan written to {PLAN_PATH.resolve()}", flush=True)

        if self.approve_file is None:
            print("[gate] No --approve-file given; standing down without dispatching.", flush=True)
            return self._reply("STAND DOWN - no supervisor decision was supplied.")

        print(f"[gate] Waiting up to {self.timeout_seconds}s for a decision in {self.approve_file}", flush=True)
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            if self.approve_file.exists():
                decision = self.approve_file.read_text().strip()
                if decision:
                    print(f"[gate] Decision received: {decision[:120]}", flush=True)
                    return self._reply(decision)
            time.sleep(self.poll_seconds)

        print("[gate] Timed out waiting for a decision; standing down.", flush=True)
        return self._reply("STAND DOWN - the supervisor did not decide within the timeout.")

    @staticmethod
    def _reply(text: str) -> PromptResult:
        return PromptResult(text=text, blocks=[MessageBlock.text_block(text)])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", nargs="?", default=DEFAULT_TASK)
    parser.add_argument("--approve-file", type=pathlib.Path, default=None)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    if args.approve_file and args.approve_file.exists():
        args.approve_file.unlink()  # never reuse a stale decision

    gate = SupervisedGate(args.approve_file, args.timeout)

    # The graph builds its own prompt service; install ours before it does.
    original = graph_module.GraphExecutor._ensure_human_prompt_service

    def _patched(self):
        service = original(self)
        service._channel = gate
        return service

    graph_module.GraphExecutor._ensure_human_prompt_service = _patched

    writes = os.environ.get("ORCA_BRIDGE_ALLOW_WRITES", "")
    print(f"[run] write gate: {'OPEN - real dispatches will fire' if writes in {'1','true','yes'} else 'closed (dry run)'}")
    print(f"[run] task: {args.task}\n")

    result = run_workflow(yaml_file="yaml_instance/crew_dispatch.yaml", task_prompt=args.task)

    print("=" * 70)
    print("FINAL MESSAGE:")
    print(result.final_message.text_content() if result.final_message else "(none)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
