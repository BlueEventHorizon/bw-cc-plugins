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

from session.yaml_utils import read_yaml

# セッション直下のファイル（検出対象）
SESSION_FILES = [
    "session.yaml",
    "refs.yaml",
    "review.md",
    "plan.yaml",
    "evaluation.yaml",
]

# refs/ サブディレクトリのファイル
REFS_FILES = [
    "specs.yaml",
    "rules.yaml",
    "code.yaml",
]


def read_file_entry(filepath):
    """単一ファイルを読み込み {exists, content} を返す。

    Args:
        filepath: ファイルパス（Path）

    Returns:
        dict: {"exists": bool, "content": ...}
    """
    if not filepath.exists():
        return {"exists": False, "content": None}

    if filepath.suffix == ".md":
        content = filepath.read_text(encoding="utf-8")
        return {"exists": True, "content": content}

    if filepath.suffix == ".yaml":
        try:
            content = read_yaml(str(filepath))
            return {"exists": True, "content": content}
        except Exception as e:
            return {"exists": True, "content": None,
                    "error": str(e)}

    return {"exists": False, "content": None}


def read_session_files(session_dir, file_filter=None):
    """セッションディレクトリ内のファイルを読み込む。

    Args:
        session_dir: セッションディレクトリパス
        file_filter: 読み込み対象ファイル名リスト（None で全件）

    Returns:
        dict: 読み込み結果
    """
    session_path = Path(session_dir)
    result = {
        "session_dir": str(session_dir),
        "files": {},
        "refs": {},
    }

    # セッション直下ファイル
    targets = file_filter if file_filter else SESSION_FILES
    for name in targets:
        if name in SESSION_FILES:
            result["files"][name] = read_file_entry(session_path / name)

    # refs/ サブディレクトリ
    ref_targets = file_filter if file_filter else REFS_FILES
    refs_dir = session_path / "refs"
    for name in ref_targets:
        if name in REFS_FILES:
            result["refs"][name] = read_file_entry(refs_dir / name)

    return result


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
