#!/usr/bin/env python3
"""clean-rules のルール文書ディレクトリを解決する薄いラッパー。

resolve_doc_structure.py --type rules を subprocess で呼び出し、
exit code / stdout / stderr をそのまま透過する。

引数: なし（--type rules はラッパー内にハードコード）
"""
import subprocess
import sys
from pathlib import Path

LOW_LEVEL = (
    Path(__file__).resolve().parents[3]

    / "scripts"
    / "doc_structure"
    / "resolve_doc_structure.py"
)
TYPE = "rules"


def main() -> int:
    if len(sys.argv) != 1:
        print("usage: resolve_rules.py", file=sys.stderr)
        return 20
    result = subprocess.run(
        [sys.executable, str(LOW_LEVEL), "--type", TYPE],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
