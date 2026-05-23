#!/usr/bin/env python3
"""start-implement の残存セッションを検索する薄いラッパー。

session_manager.py find を subprocess で呼び出し、
exit code / stdout / stderr をそのまま透過する（DES-024 §2.1.1 共通原則）。

引数なし: 自スキル (start-implement) のセッションのみを検索する。
--all-skills: スキル種別を問わず横断検出する（他スキル残骸の通告用、#83）。
"""
import subprocess
import sys
from pathlib import Path

LOW_LEVEL = Path(__file__).resolve().parents[3] / "scripts" / "session_manager.py"
SKILL = "start-implement"


def main() -> int:
    if "--all-skills" in sys.argv[1:]:
        cli_args = ["find", "--all-skills"]
    else:
        cli_args = ["find", "--skill", SKILL]
    result = subprocess.run(
        [sys.executable, str(LOW_LEVEL)] + cli_args,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
