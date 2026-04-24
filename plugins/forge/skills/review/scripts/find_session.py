#!/usr/bin/env python3
"""review の残存セッションを検索する薄いラッパー。

session_manager.py find --skill review を subprocess で呼び出し、
exit code / stdout / stderr をそのまま透過する（DES-024 §2.1.1 共通原則）。
"""
import subprocess
import sys
from pathlib import Path

LOW_LEVEL = Path(__file__).resolve().parents[3] / "scripts" / "session_manager.py"
SKILL = "review"


def main() -> int:
    result = subprocess.run(
        [sys.executable, str(LOW_LEVEL), "find", "--skill", SKILL],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
