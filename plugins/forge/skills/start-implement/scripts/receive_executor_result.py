#!/usr/bin/env python3
"""consumer が executor result を検証済み SUCCESS/FAILURE へ確定するローカル操作入口。"""

from executor_result_contract import run_cli


if __name__ == "__main__":
    raise SystemExit(run_cli(failure_on_error=True))
