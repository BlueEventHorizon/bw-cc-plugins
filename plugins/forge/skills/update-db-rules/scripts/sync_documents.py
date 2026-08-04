#!/usr/bin/env python3
"""update-db-rules の doc-db desired-state 同期を駆動する薄いラッパー。

低レベル CLI sync_docdb.py を category=rules 固定で subprocess 呼び出しし、
残りの引数（--start / --status <job_id> 等）・stdout・stderr・exit code を
そのまま透過する。投入（--start）と状態取得（--status）の両操作を透過する。

引数: 低レベル CLI へそのまま渡す（category はラッパー内にハードコード）
"""
import subprocess
import sys
from pathlib import Path

LOW_LEVEL = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "doc_backend"
    / "sync_docdb.py"
)
CATEGORY = "rules"


def main() -> int:
    result = subprocess.run(
        [sys.executable, str(LOW_LEVEL), CATEGORY, *sys.argv[1:]],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
