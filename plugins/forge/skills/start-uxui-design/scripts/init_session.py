#!/usr/bin/env python3
"""start-uxui-design のセッションを初期化する薄いラッパー。

session_manager.py init を subprocess で呼び出し、exit code / stdout / stderr を
そのまま透過する（DES-024 §2.1.1 共通原則、§3.2 配置表）。

位置引数: {feature} {mode} {output_dir}
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LOW_LEVEL = Path(__file__).resolve().parents[3] / "scripts" / "session_manager.py"
SKILL = "start-uxui-design"


def main() -> int:
    feature, mode, output_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    cmd = [
        sys.executable,
        str(LOW_LEVEL),
        "init",
        "--skill", SKILL,
        "--feature", feature,
        "--mode", mode,
        "--output-dir", output_dir,
    ]
    result = subprocess.run(cmd, check=False)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
