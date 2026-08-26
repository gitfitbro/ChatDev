"""Run the adversarial review panel against a repo and a diff target.

    uv run python run_review_demo.py <repo_path> "<what to review>"

Defaults to this repo and the current branch.
"""

import sys
from runtime.sdk import run_workflow

repo = sys.argv[1] if len(sys.argv) > 1 else "/Users/sirrelesteinfeld_1/projects/ChatDev"
target = sys.argv[2] if len(sys.argv) > 2 else "the current branch against origin/main"

prompt = (
    f"Review {target}.\n"
    f"Repository root: {repo}\n"
    f"Run every git command with `git -C {repo} ...` so you never review the wrong tree. "
    f"Confirm `git -C {repo} rev-parse --show-toplevel` matches that path before you review "
    f"anything, and stop if it does not."
)

result = run_workflow(yaml_file="yaml_instance/crew_review.yaml", task_prompt=prompt)
print("=" * 72)
print("VERDICT:")
print(result.final_message.text_content() if result.final_message else "(none)")
