"""Put one question to a panel of different vendors, then compare what each seat cost.

    uv run python run_panel_demo.py "Should we do X or Y?"

The point of the trailing table is not the dollar figure - it is the ratio. A seat that
costs an order of magnitude less and lands in the same place as the expensive one is a
seat you can afford to run on everything.
"""

import sys
import time
from collections import defaultdict

from runtime.sdk import run_workflow

DEFAULT_QUESTION = (
    "We gate fleet-mutating agent tools behind an environment variable, closed by default, "
    "so an agent cannot dispatch other agents without a human opening it. Is an env-var gate "
    "the right control here, or is it security theatre that will be switched on permanently "
    "and forgotten?"
)

# Public per-MTok pricing, input/output. Rough by design - ratios are what matter,
# and a stale absolute is less misleading than an invented precise one.
PRICES = {
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o": (2.50, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
}


def cost(model: str, tokens_in: int, tokens_out: int) -> float | None:
    price = PRICES.get(model)
    if not price:
        return None
    return tokens_in / 1e6 * price[0] + tokens_out / 1e6 * price[1]


def main() -> int:
    question = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUESTION
    started = time.monotonic()
    result = run_workflow(yaml_file="yaml_instance/crew_panel.yaml", task_prompt=question)
    elapsed = time.monotonic() - started

    print("=" * 72)
    print("CHAIR:")
    print(result.final_message.text_content() if result.final_message else "(none)")

    usage = getattr(result.meta_info, "token_usage", None) or {}
    history = usage.get("call_history") or []
    if not history:
        print(f"\n(no token history recorded; wall clock {elapsed:.0f}s)")
        return 0

    seats: dict[str, dict] = defaultdict(lambda: {"in": 0, "out": 0, "calls": 0, "model": "", "provider": ""})
    for call in history:
        seat = seats[call.get("node_id", "?")]
        seat["in"] += call.get("input_tokens", 0)
        seat["out"] += call.get("output_tokens", 0)
        seat["calls"] += 1
        seat["model"] = call.get("model_name", "")
        seat["provider"] = call.get("provider", "")

    print("\n" + "=" * 72)
    print(f"PANEL COST — wall clock {elapsed:.0f}s\n")
    print(f"{'seat':<16}{'provider':<11}{'model':<20}{'in':>9}{'out':>8}{'cost':>10}")
    print("-" * 72)
    total = 0.0
    unpriced = []
    for name, s in sorted(seats.items(), key=lambda kv: -(kv[1]["in"] + kv[1]["out"])):
        c = cost(s["model"], s["in"], s["out"])
        if c is None:
            unpriced.append(s["model"])
            shown = "unpriced"
        else:
            total += c
            shown = f"${c:.4f}"
        print(f"{name:<16}{s['provider']:<11}{s['model']:<20}{s['in']:>9,}{s['out']:>8,}{shown:>10}")
    print("-" * 72)
    print(f"{'total':<56}{'$' + format(total, '.4f'):>16}")
    if unpriced:
        print(f"\nNot in the price table, excluded from the total: {', '.join(sorted(set(unpriced)))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
