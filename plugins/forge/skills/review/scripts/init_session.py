#!/usr/bin/env python3
"""review のセッションを初期化する薄いラッパー。

session_manager.py init を subprocess で呼び出し、exit code / stdout / stderr を
そのまま透過する（DES-024 §2.3 共通原則）。

位置引数: {review_type} {engine} {auto_count}
オプション:
  --files <path1> <path2> ...   レビュー対象ファイル群 (省略可、複数可)
  --files <path1,path2,...>     カンマ区切りでも受け付ける

--files は常に session_manager に透過する（保存責務は session_manager 側。
session.yaml への files 書き込みは session_manager が行う。DES-028 §4.1）。
未指定時も空の --files を渡し、session_manager が ``files: []`` を記録する
（常に存在することで読み手の場合分けを単純化）。

--current-cycle は新規 init では常に 0 のためラッパー内でハードコードする。

--section は DES-028 §2.7 (TBD) で不採用。argparse から未定義のため、指定された
場合は "unrecognized arguments" として exit code 2 で異常終了する。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

LOW_LEVEL = Path(__file__).resolve().parents[3] / "scripts" / "session_manager.py"
SKILL = "review"


def _parse_args(argv):
    """位置引数 + --files のみ受け取る。--section は意図的に未定義で reject する。"""
    parser = argparse.ArgumentParser(
        prog="init_session.py",
        description="review session を初期化する (DES-028 §4.1)",
    )
    parser.add_argument("review_type", help="code | design | requirement | plan | uxui | generic")
    parser.add_argument("engine", help="レビューエンジン名 (例: codex)")
    parser.add_argument("auto_count", help="auto 件数 (現状は文字列で透過)")
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="レビュー対象ファイル群 (空白またはカンマ区切り)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    cmd = [
        sys.executable,
        str(LOW_LEVEL),
        "init",
        "--skill", SKILL,
        "--review-type", args.review_type,
        "--engine", args.engine,
        "--auto-count", args.auto_count,
        "--current-cycle", "0",
    ]
    # --files は常に末尾で透過する（未指定時も空の --files を渡し files: [] を記録）。
    # session_manager の extract_files は「次の --xxx まで」を値とするため末尾配置が安全。
    cmd.append("--files")
    if args.files:
        cmd.extend(args.files)

    result = subprocess.run(cmd, check=False)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
