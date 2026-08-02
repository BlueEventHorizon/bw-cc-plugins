#!/usr/bin/env python3
"""query-db-specs の doc-advisor 索引入力準備を行う薄いラッパー。

低レベル CLI prepare_advisor_index.py を category=specs 固定で subprocess
呼び出しし、残りの引数・stdout・stderr・exit code をそのまま透過する。

引数: 低レベル CLI へそのまま渡す（category はラッパー内にハードコード）
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
CATEGORY = "specs"


def main() -> int:
    result = subprocess.run(
        [sys.executable, str(LOW_LEVEL), CATEGORY, *sys.argv[1:]],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
