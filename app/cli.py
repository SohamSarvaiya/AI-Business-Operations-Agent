"""python -m app.cli "Prepare a sales report for this month..." [--provider openai]"""
import argparse
import json

from app.agent.service import AgentService
from app.db import init_db


def main() -> None:
    p = argparse.ArgumentParser(description="Run the business operations agent")
    p.add_argument("request")
    p.add_argument("--provider", default=None, help="mock | openai | anthropic | gemini")
    p.add_argument("--json", action="store_true", help="print raw JSON instead of markdown")
    a = p.parse_args()

    init_db()
    svc = AgentService()
    run = svc.start_run(a.request, a.provider)
    while run["status"] == "awaiting_approval":
        print("\n[HUMAN APPROVAL REQUIRED]")
        for p_ in run["pending_approvals"]:
            print(f"  {p_['tool']}({json.dumps(p_['arguments'])})")
        run = svc.resume_run(run["run_id"], input("Approve? [y/N] ").strip().lower() == "y")

    if a.json:
        print(json.dumps(run, indent=2, default=str))
        return
    print(f"\nrun_id={run['run_id']} status={run['status']} provider={run['provider']}/{run['model']}\n")
    print(run["report_markdown"] or f"FAILED: {run['error']}")
    print("\n--- Tool execution log ---")
    for log in run["tool_logs"]:
        print(f"{log['status']:<9} {log['tool']:<26} {log.get('duration_ms', 0):>8.1f} ms  {json.dumps(log['arguments'])[:80]}")


if __name__ == "__main__":
    main()
