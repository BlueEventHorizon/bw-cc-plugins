#!/usr/bin/env python3
"""依存ファイル（必須・filter あり）のバージョンを更新する薄いラッパー。

update_version_files.py {file} {cur} {new} --filter {filter} を
subprocess で呼び出し、exit code / stdout / stderr をそのまま透過する
（DES-024 §2.1.1 共通原則）。

位置引数: {file} {current_version} {new_version} {filter}
"""
import subprocess
import sys
from pathlib import Path

LOW_LEVEL = Path(__file__).resolve().parent / "update_version_files.py"


def main() -> int:
    file_, cur, new, filter_ = (
        sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    )
    result = subprocess.run(
        [sys.executable, str(LOW_LEVEL), file_, cur, new, "--filter", filter_],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
