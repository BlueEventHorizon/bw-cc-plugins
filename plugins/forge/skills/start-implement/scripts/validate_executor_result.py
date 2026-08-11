#!/usr/bin/env python3
"""producer が executor result を訂正可能な形で検証するローカル操作入口。"""

from executor_result_contract import run_cli


if __name__ == "__main__":
    raise SystemExit(run_cli(failure_on_error=False))
