#!/usr/bin/env python3
"""refs.yaml を生成する。

review スキルの Phase 2 で呼び出され、session_format.md 準拠の refs.yaml を書き出す。

Usage:
    echo '<json>' | python3 write_refs.py <session_dir>

stdin JSON:
    {
        "target_files": ["path/to/file1"],
        "reference_docs": [{"path": "docs/rules.md"}],
        "review_criteria_path": "plugins/forge/docs/review_criteria_spec.md",
        "related_code": [{"path": "src/foo.py", "reason": "関連", "lines": "1-50"}]
    }

出力:
    stdout: {"status": "ok", "path": "..."}
"""

import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR.parent))

from session.yaml_utils import write_nested_yaml


def validate_refs_data(data):
    """入力データをバリデーションする。

    Args:
        data: stdin から受け取った dict

    Raises:
        ValueError: バリデーション失敗
    """
    if not isinstance(data.get("target_files"), list) or not data["target_files"]:
        raise ValueError("target_files は非空の配列が必須です")

    if not data.get("review_criteria_path"):
        raise ValueError("review_criteria_path は必須です")

    if not isinstance(data.get("reference_docs"), list):
        raise ValueError("reference_docs は配列が必須です")

    for i, doc in enumerate(data.get("reference_docs", [])):
        if not doc.get("path"):
            raise ValueError(f"reference_docs[{i}].path は必須です")

    for i, code in enumerate(data.get("related_code", [])):
        if not code.get("path"):
            raise ValueError(f"related_code[{i}].path は必須です")
        if not code.get("reason"):
            raise ValueError(f"related_code[{i}].reason は必須です")


def build_refs_sections(data):
    """入力データから write_nested_yaml 用の sections を組み立てる。

    Args:
        data: バリデーション済みの dict

    Returns:
        list[tuple]: sections リスト
    """
    sections = [
        ("target_files", data["target_files"]),
        ("reference_docs", data.get("reference_docs", [])),
        ("review_criteria_path", data["review_criteria_path"]),
    ]
    related = data.get("related_code")
    if related:
        sections.append(("related_code", related))
    return sections


def write_refs(session_dir, data):
    """refs.yaml を書き出す。

    Args:
        session_dir: セッションディレクトリパス
        data: バリデーション済みの入力データ

    Returns:
        str: 書き出したファイルのパス
    """
    sections = build_refs_sections(data)
    output_path = Path(session_dir) / "refs.yaml"
    write_nested_yaml(str(output_path), sections)
    return str(output_path)


def main():
    if len(sys.argv) != 2:
        json.dump(
            {"status": "error", "error": "Usage: echo '<json>' | python3 write_refs.py <session_dir>"},
            sys.stderr,
        )
        sys.exit(1)

    session_dir = sys.argv[1]

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        json.dump({"status": "error", "error": f"JSON パースエラー: {e}"}, sys.stderr)
        sys.exit(1)

    try:
        validate_refs_data(data)
    except ValueError as e:
        json.dump({"status": "error", "error": str(e)}, sys.stderr)
        sys.exit(1)

    path = write_refs(session_dir, data)
    json.dump({"status": "ok", "path": path}, sys.stdout, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
