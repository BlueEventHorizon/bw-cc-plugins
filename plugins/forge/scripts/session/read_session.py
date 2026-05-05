#!/usr/bin/env python3
"""セッションディレクトリ内の全ファイルを読み込み JSON で出力する。

Usage:
    python3 read_session.py <session_dir> [--files file1.yaml file2.yaml ...]

出力:
    stdout: JSON — files / refs をキーとした辞書
"""

import argparse
import json
import sys
from pathlib import Path

# 同パッケージから import（CLI 実行時は sys.path 調整）
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR.parent))

from session.reader import (  # noqa: E402
    REFS_FILES,
    SESSION_FILES,
    read_entry as read_file_entry,
    read_session_files,
)


def main():
    parser = argparse.ArgumentParser(
        description="セッションディレクトリの YAML/MD ファイルを JSON 出力する"
    )
    parser.add_argument("session_dir", help="セッションディレクトリパス")
    parser.add_argument(
        "--files", nargs="*", default=None,
        help="読み込み対象ファイル名（省略時は全件）"
    )
    args = parser.parse_args()

    session_path = Path(args.session_dir)
    if not session_path.is_dir():
        json.dump(
            {"status": "error", "error": f"ディレクトリが存在しません: {args.session_dir}"},
            sys.stderr,
        )
        sys.exit(1)

    result = read_session_files(args.session_dir, args.files)
    result["status"] = "ok"
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
