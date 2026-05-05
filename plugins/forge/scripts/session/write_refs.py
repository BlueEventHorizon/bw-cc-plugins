#!/usr/bin/env python3
"""refs.yaml を生成する。

review スキルの Phase 2 で呼び出され、session_format.md 準拠の refs.yaml を書き出す。

Usage:
    echo '<json>' | python3 write_refs.py <session_dir>

stdin JSON:
    {
        "target_files": ["path/to/file1"],
        "reference_docs": [{"path": "docs/rules.md"}],
        "perspectives": [
            {"name": "logic", "criteria_path": "review/docs/review_criteria_code.md",
             "section": "正確性 (Logic)", "output_path": "review_logic.md"}
        ],
        "related_code": [{"path": "src/foo.py", "reason": "関連", "lines": "1-50"}]
    }

出力:
    stdout: {"status": "ok", "path": "..."}
"""

import json
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR.parent))

from session.yaml_utils import write_nested_yaml
from monitor.notify import notify_session_update
from session_manager import update_session_meta_warning

# perspectives[].name の許容パターン（英小文字・数字・アンダースコア・ハイフンのみ）
_PERSPECTIVE_NAME_RE = re.compile(r"^[a-z0-9_-]+$")


def validate_refs_data(data):
    """入力データをバリデーションする。

    Args:
        data: stdin から受け取った dict

    Raises:
        ValueError: バリデーション失敗
    """
    if not isinstance(data.get("target_files"), list) or not data["target_files"]:
        raise ValueError("target_files は非空の配列が必須です")

    if not isinstance(data.get("reference_docs"), list):
        raise ValueError("reference_docs は配列が必須です")

    # perspectives: 必須・非空配列
    perspectives = data.get("perspectives")
    if not isinstance(perspectives, list) or not perspectives:
        raise ValueError("perspectives は非空の配列が必須です")

    for i, p in enumerate(perspectives):
        # name: 必須、パターン検証
        name = p.get("name")
        if not name:
            raise ValueError(f"perspectives[{i}].name は必須です")
        if not _PERSPECTIVE_NAME_RE.match(name):
            raise ValueError(
                f"perspectives[{i}].name は ^[a-z0-9_-]+$ に限定されます: {name!r}"
            )

        # criteria_path: 必須
        if not p.get("criteria_path"):
            raise ValueError(f"perspectives[{i}].criteria_path は必須です")

        # output_path: 必須、../ 禁止、絶対パス禁止
        output_path = p.get("output_path")
        if not output_path:
            raise ValueError(f"perspectives[{i}].output_path は必須です")
        if ".." in output_path.split("/"):
            raise ValueError(
                f"perspectives[{i}].output_path に ../ は使用できません: {output_path!r}"
            )
        if output_path.startswith("/"):
            raise ValueError(
                f"perspectives[{i}].output_path に絶対パスは使用できません: {output_path!r}"
            )

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
        ("perspectives", data["perspectives"]),
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
    notify_session_update(session_dir, str(output_path))
    update_session_meta_warning(session_dir, {
        "phase": "context_ready",
        "phase_status": "completed",
        "active_artifact": "refs.yaml",
    })
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
