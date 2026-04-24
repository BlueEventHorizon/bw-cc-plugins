#!/usr/bin/env python3
"""batch_update — plan.yaml を stdin JSON で一括更新する薄いラッパー。

DES-024 §2.1.1 / §3.4 に従った透過ラッパー。位置引数を低レベル
update_plan.py --batch に渡し、stdin は親プロセスから subprocess に継承させる
（subprocess.run に stdin/input を指定しない）。stdout/stderr/exit code も完全透過。

位置引数: {session_dir}
stdin: {"updates": [...]} 形式の JSON（低レベル側が parse する）
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
        "--batch",
    ]
    result = subprocess.run(cmd, check=False)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
