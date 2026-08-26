from runtime.sdk import run_workflow

result = run_workflow(
    yaml_file="yaml_instance/crew.yaml",
    task_prompt=(
        "Build a small Python module `bearing.py` exposing "
        "`degrees_to_cardinal(deg: float) -> str` that converts a compass bearing to one of "
        "the 8 points (N, NE, E, SE, S, SW, W, NW), plus a pytest file `test_bearing.py` that "
        "proves it for all 8 points and for the wraparound at 350 and 370 degrees. "
        "Keep it to those two files."
    ),
)
print("=" * 70)
print("FINAL MESSAGE:")
print(result.final_message.text_content() if result.final_message else "(no final message)")
