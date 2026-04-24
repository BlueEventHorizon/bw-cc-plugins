#!/usr/bin/env python3
"""review のセッションを初期化する薄いラッパー。

session_manager.py init を subprocess で呼び出し、exit code / stdout / stderr を
そのまま透過する（DES-024 §2.1.1 共通原則、§3.2 配置表）。

位置引数: {review_type} {engine} {auto_count}
--current-cycle は新規 init では常に 0 のためラッパー内でハードコード（DES-024 §3.2 補足）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LOW_LEVEL = Path(__file__).resolve().parents[3] / "scripts" / "session_manager.py"
SKILL = "review"


def main() -> int:
    review_type, engine, auto_count = sys.argv[1], sys.argv[2], sys.argv[3]
    cmd = [
        sys.executable,
        str(LOW_LEVEL),
        "init",
        "--skill", SKILL,
        "--review-type", review_type,
        "--engine", engine,
        "--auto-count", auto_count,
        "--current-cycle", "0",
    ]
    result = subprocess.run(cmd, check=False)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
