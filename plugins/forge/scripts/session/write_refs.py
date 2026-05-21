#!/usr/bin/env python3
"""refs.yaml を生成する。

review スキルの Phase 2 で呼び出され、新スキーマ (review_packet) の refs.yaml を書き出す。

スキーマ契約は DES-028 §2.3 「refs.yaml の新スキーマ契約」に従う。
旧 perspectives[] スキーマは本 feature で完全撤廃 (FNC-412)。

Usage:
    echo '<json>' | python3 write_refs.py <session_dir>

stdin JSON:
    {
        "target_files": ["path/to/file1"],
        "reference_docs": [{"path": "docs/rules.md"}],
        "review_packet": {
            "criteria_path": "review/docs/review_criteria_code.md",
            "ssot_refs": [
                {"path": "docs/rules/implementation_guidelines.md",
                 "priority": "P1", "doc_type": "rules"}
            ],
            "check_order": ["P1", "P2", "P3"],
            "severity_source": "principles",
            "output_path": "review_code.md"
        },
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

from session.store import SessionStore
from session.yaml_utils import yaml_scalar

# review_packet.ssot_refs[].priority の許容値
_ALLOWED_PRIORITIES = frozenset({"P1", "P2", "P3"})
# review_packet.ssot_refs[].doc_type の許容値
_ALLOWED_DOC_TYPES = frozenset({"rules", "principles", "format"})
# review_packet.output_path のフォーマット: review_<種別>.md
_OUTPUT_PATH_RE = re.compile(r"^review_[a-z0-9_-]+\.md$")


def validate_review_packet(data):
    """入力データをバリデーションする (新スキーマ: review_packet)。

    Args:
        data: stdin から受け取った dict

    Raises:
        ValueError: バリデーション失敗
    """
    # 旧 perspectives[] スキーマの拒否 (回帰防止)
    if "perspectives" in data:
        raise ValueError(
            "perspectives[] スキーマは撤廃されました (DES-028 §2.3 / FNC-412)。"
            " review_packet を使ってください"
        )

    if not isinstance(data.get("target_files"), list) or not data["target_files"]:
        raise ValueError("target_files は非空の配列が必須です")

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

    packet = data.get("review_packet")
    if not isinstance(packet, dict):
        raise ValueError("review_packet は dict が必須です")

    # criteria_path: 必須
    criteria_path = packet.get("criteria_path")
    if not isinstance(criteria_path, str) or not criteria_path:
        raise ValueError("review_packet.criteria_path は必須です")

    # ssot_refs: 必須非空配列
    ssot_refs = packet.get("ssot_refs")
    if not isinstance(ssot_refs, list) or not ssot_refs:
        raise ValueError("review_packet.ssot_refs は非空の配列が必須です")

    for i, ref in enumerate(ssot_refs):
        if not isinstance(ref, dict):
            raise ValueError(f"review_packet.ssot_refs[{i}] は dict が必須です")
        path = ref.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError(f"review_packet.ssot_refs[{i}].path は必須です")
        priority = ref.get("priority")
        if priority not in _ALLOWED_PRIORITIES:
            raise ValueError(
                f"review_packet.ssot_refs[{i}].priority は P1/P2/P3 のいずれかが必須です: {priority!r}"
            )
        doc_type = ref.get("doc_type")
        if doc_type not in _ALLOWED_DOC_TYPES:
            raise ValueError(
                f"review_packet.ssot_refs[{i}].doc_type は rules/principles/format のいずれかが必須です: {doc_type!r}"
            )

    # check_order: 必須非空配列 (str の順序リスト)
    check_order = packet.get("check_order")
    if not isinstance(check_order, list) or not check_order:
        raise ValueError("review_packet.check_order は非空の配列が必須です")
    for i, step in enumerate(check_order):
        if not isinstance(step, str) or not step:
            raise ValueError(f"review_packet.check_order[{i}] は非空文字列が必須です")

    # severity_source: 必須 str
    severity_source = packet.get("severity_source")
    if not isinstance(severity_source, str) or not severity_source:
        raise ValueError("review_packet.severity_source は必須です")

    # output_path: 必須、フォーマット検証、../ 禁止、絶対パス禁止
    output_path = packet.get("output_path")
    if not isinstance(output_path, str) or not output_path:
        raise ValueError("review_packet.output_path は必須です")
    if ".." in output_path.split("/"):
        raise ValueError(
            f"review_packet.output_path に ../ は使用できません: {output_path!r}"
        )
    if output_path.startswith("/"):
        raise ValueError(
            f"review_packet.output_path に絶対パスは使用できません: {output_path!r}"
        )
    if not _OUTPUT_PATH_RE.match(output_path):
        raise ValueError(
            "review_packet.output_path は ^review_[a-z0-9_-]+\\.md$ 形式が必須です: "
            f"{output_path!r}"
        )


def build_refs_text(data):
    """入力データから refs.yaml のテキストを構築する。

    トップレベル順序: target_files / reference_docs / review_packet / related_code

    Args:
        data: バリデーション済みの dict

    Returns:
        str: refs.yaml のテキスト
    """
    lines = []

    # target_files
    lines.append("target_files:")
    for item in data["target_files"]:
        lines.append(f"  - {yaml_scalar(item)}")
    lines.append("")

    # reference_docs (空でも明示出力するが、現実装は空なら出力しない)
    reference_docs = data.get("reference_docs", [])
    if reference_docs:
        lines.append("reference_docs:")
        _append_object_list(lines, reference_docs, indent="  ")
        lines.append("")

    # review_packet (ネスト構造)
    packet = data["review_packet"]
    lines.append("review_packet:")
    lines.append(f"  criteria_path: {yaml_scalar(packet['criteria_path'])}")
    lines.append("  ssot_refs:")
    _append_object_list(lines, packet["ssot_refs"], indent="    ")
    # check_order: ブロックリストで出力 (parse_yaml がネスト dict 配下の
    # インライン配列を扱えないため、ラウンドトリップ可能なブロック形式を採用)
    lines.append("  check_order:")
    for step in packet["check_order"]:
        lines.append(f"    - {yaml_scalar(step)}")
    lines.append(f"  severity_source: {yaml_scalar(packet['severity_source'])}")
    lines.append(f"  output_path: {yaml_scalar(packet['output_path'])}")
    lines.append("")

    # related_code (任意)
    related = data.get("related_code")
    if related:
        lines.append("related_code:")
        _append_object_list(lines, related, indent="  ")
        lines.append("")

    # 末尾の余分な空行を除去
    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines) + "\n"


def _append_object_list(lines, items, indent="  "):
    """オブジェクトリストを ``  - key: val`` 形式で追加する (インデント可変)。"""
    for item in items:
        first = True
        for k, v in item.items():
            if v is None or (isinstance(v, (list, str)) and not v):
                continue
            prefix = f"{indent}- " if first else f"{indent}  "
            if isinstance(v, list):
                inline = "[" + ", ".join(yaml_scalar(x) for x in v) + "]"
                lines.append(f"{prefix}{k}: {inline}")
            else:
                lines.append(f"{prefix}{k}: {yaml_scalar(v)}")
            first = False


def write_refs(session_dir, data):
    """refs.yaml を書き出す。

    Args:
        session_dir: セッションディレクトリパス
        data: バリデーション済みの入力データ

    Returns:
        str: 書き出したファイルのパス
    """
    text = build_refs_text(data)
    output_path = SessionStore(session_dir).write_text("refs.yaml", text)
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
        validate_review_packet(data)
    except ValueError as e:
        json.dump({"status": "error", "error": str(e)}, sys.stderr)
        sys.exit(1)

    path = write_refs(session_dir, data)
    json.dump({"status": "ok", "path": path}, sys.stdout, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
