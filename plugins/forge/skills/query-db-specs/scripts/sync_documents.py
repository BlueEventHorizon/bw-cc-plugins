#!/usr/bin/env python3
"""query-db-specs の doc-db desired-state 同期を駆動する薄いラッパー。

低レベル CLI sync_docdb.py を category=specs 固定で subprocess 呼び出しし、
投入（--start）と状態取得（--status <job_id>）だけを公開し、stdout・stderr・
exit code をそのまま透過する。
KEY / series 未整備（query の exit 30）からの索引作成に SKILL が使用する。

引数: --start または --status <job_id>（category はラッパー内にハードコード）
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
CATEGORY = "specs"


def build_command(args: list[str]) -> list[str] | None:
    if args == ["--start"]:
        return [sys.executable, str(LOW_LEVEL), CATEGORY, "--start"]
    if (
        len(args) == 2
        and args[0] == "--status"
        and args[1]
        and args[1] == args[1].strip()
    ):
        return [
            sys.executable,
            str(LOW_LEVEL),
            CATEGORY,
            "--status",
            args[1],
        ]
    return None


def main() -> int:
    command = build_command(sys.argv[1:])
    if command is None:
        print(
            "usage: sync_documents.py --start | --status <job_id>",
            file=sys.stderr,
        )
        return 20
    result = subprocess.run(
        command,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
