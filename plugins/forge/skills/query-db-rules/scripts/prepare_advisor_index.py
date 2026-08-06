#!/usr/bin/env python3
"""query-db-rules の doc-advisor 索引入力準備を行う薄いラッパー。

低レベル CLI prepare_advisor_index.py を category=rules 固定で subprocess
呼び出しし、stdout・stderr・exit code をそのまま透過する。

引数: なし（category はラッパー内にハードコード）
"""
import subprocess
import sys
from pathlib import Path

LOW_LEVEL = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "doc_backend"
    / "prepare_advisor_index.py"
)
CATEGORY = "rules"


def main() -> int:
    if len(sys.argv) != 1:
        print("usage: prepare_advisor_index.py", file=sys.stderr)
        return 20
    result = subprocess.run(
        [sys.executable, str(LOW_LEVEL), CATEGORY],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
