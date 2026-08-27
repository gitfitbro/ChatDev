import sys
from runtime.sdk import run_workflow

task = sys.argv[1] if len(sys.argv) > 1 else (
    "Scout task only: inventory which of my Orca worktrees have open PRs that are already "
    "merged, so the terminals can be reclaimed. Scope: read-only, ~/orca/workspaces. One crewmate."
)
r = run_workflow(yaml_file="yaml_instance/crew_dispatch.yaml", task_prompt=task)
print("=" * 70)
print("FINAL MESSAGE:")
print(r.final_message.text_content() if r.final_message else "(none)")
