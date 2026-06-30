#!/usr/bin/env python3
"""Issue 化済みとして plan.yaml の項目を更新する薄いラッパー。

DES-024 §2.1.1 / §2.4 #1 (SKILL 固有値の hardcode)。位置引数のみ受ける。
低レベル `update_plan.py` に以下を透過する (DES-028 §4 / Issue #99 の
Issue 化済み記録形式):

    --status skipped
    --recommendation create_issue
    --skip-reason "Issue 化済み: #{issue_number}"

Usage:
    python3 mark_issued.py <session_dir> <id> <issue_number>

低レベル script の exit code / stdout / stderr を完全透過する。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LOW_LEVEL = (
    Path(__file__).resolve().parents[3] / "scripts" / "session" / "update_plan.py"
)


def main() -> int:
    if len(sys.argv) != 4:
        print("Usage: mark_issued.py <session_dir> <id> <issue_number>", file=sys.stderr)
        return 2

    session_dir = sys.argv[1]
    item_id = sys.argv[2]
    issue_number = sys.argv[3]

    skip_reason = f"Issue 化済み: #{issue_number}"
    cmd = [
        sys.executable,
        str(LOW_LEVEL),
        session_dir,
        "--id", item_id,
        "--status", "skipped",
        "--recommendation", "create_issue",
        "--skip-reason", skip_reason,
    ]
    result = subprocess.run(cmd, check=False)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
