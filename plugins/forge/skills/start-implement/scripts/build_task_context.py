#!/usr/bin/env python3
"""orchestrator が plan.yaml と候補 JSON から tasks/{task_id}.yaml を生成するローカル操作入口。"""

from task_context_contract import run_cli


if __name__ == "__main__":
    raise SystemExit(run_cli())
