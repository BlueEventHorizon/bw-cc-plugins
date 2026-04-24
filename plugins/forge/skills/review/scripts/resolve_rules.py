#!/usr/bin/env python3
"""review のルール文書ディレクトリを解決する薄いラッパー。

resolve_doc_structure.py --type rules を subprocess で呼び出し、
exit code / stdout / stderr をそのまま透過する（DES-024 §2.1.1 共通原則）。

引数: なし（--type rules はラッパー内にハードコード）
"""
import subprocess
import sys
from pathlib import Path

LOW_LEVEL = (
    Path(__file__).resolve().parents[3]
    / "skills"
    / "doc-structure"
    / "scripts"
    / "resolve_doc_structure.py"
)
TYPE = "rules"


def main() -> int:
    result = subprocess.run(
        [sys.executable, str(LOW_LEVEL), "--type", TYPE],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
