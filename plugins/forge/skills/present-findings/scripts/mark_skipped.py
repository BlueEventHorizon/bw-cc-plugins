#!/usr/bin/env python3
"""mark_skipped — plan.yaml の対象項目を status=skipped に更新する薄いラッパー。

DES-024 §2.1.1 に従った透過ラッパー。位置引数を低レベル update_plan.py に
flag 変換して渡し、stdout/stderr/exit code を完全透過する。

位置引数: {session_dir} {id} {reason}
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LOW_LEVEL = Path(__file__).resolve().parents[3] / "scripts" / "session" / "update_plan.py"


def main() -> int:
    cmd = [
        sys.executable,
        str(LOW_LEVEL),
        sys.argv[1],
        "--id", sys.argv[2],
        "--status", "skipped",
        "--skip-reason", sys.argv[3],
    ]
    result = subprocess.run(cmd, check=False)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
