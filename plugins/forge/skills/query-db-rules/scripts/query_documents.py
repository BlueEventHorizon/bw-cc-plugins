#!/usr/bin/env python3
"""query-db-rules の doc-db 検索を駆動する薄いラッパー。

低レベル CLI query_docdb.py を category=rules 固定で subprocess 呼び出しし、
残りの引数（検索タスクの説明 1 つの位置引数）・stdout・stderr・exit code を
そのまま透過する（exit 30 index_missing を含む全 exit code）。

引数: 低レベル CLI へそのまま渡す（category はラッパー内にハードコード）
"""
import subprocess
import sys
from pathlib import Path

LOW_LEVEL = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "doc_backend"
    / "query_docdb.py"
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
