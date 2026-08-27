from runtime.sdk import run_workflow
r = run_workflow(yaml_file="yaml_instance/crew_fleet.yaml",
                 task_prompt="Give me bearings on the fleet. I've been away.")
print("=" * 70)
print("FINAL MESSAGE:")
print(r.final_message.text_content() if r.final_message else "(none)")
