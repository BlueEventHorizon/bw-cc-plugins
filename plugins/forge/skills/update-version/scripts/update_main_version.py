#!/usr/bin/env python3
"""主要バージョンファイルを更新する薄いラッパー。

update_version_files.py {file} {cur} {new} --version-path {version_path} を
subprocess で呼び出し、exit code / stdout / stderr をそのまま透過する
（DES-024 §2.1.1 共通原則）。

位置引数: {file} {current_version} {new_version} {version_path}
"""
import subprocess
import sys
from pathlib import Path

LOW_LEVEL = Path(__file__).resolve().parent / "update_version_files.py"


def main() -> int:
    file_, cur, new, version_path = (
        sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    )
    result = subprocess.run(
        [sys.executable, str(LOW_LEVEL),
         file_, cur, new,
         "--version-path", version_path],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
