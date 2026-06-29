#!/usr/bin/env python3
"""refs.yaml を生成する (ADR-032 path schema unification 後)。

review スキルの Phase 3 で呼び出され、新スキーマ (review_packet) の refs.yaml を書き出す。

スキーマ契約は DES-028 §2.3 + ADR-032 「path schema unification」に従う。
- target_files: [{path: ...}] dict 配列 (ADR-032 で string[] から移行)
- ssot_refs[].path: path に統一 (ADR-032 で Issue #99 の doc_path 改名を覆す)
- review_packet.output_filename: sandbox 内ファイル名 (ADR-032 で output_path から改名)
- 旧 perspectives[] スキーマは完全撤廃 (FNC-412)
- 旧キー名 (doc_path / output_path / target_files の string array) は明示的 reject

Usage:
    echo '<json>' | python3 write_refs.py <session_dir>

stdin JSON:
    {
        "target_files": [{"path": "path/to/file1"}],
        "reference_docs": [{"path": "docs/rules.md"}],
        "review_packet": {
            "criteria_path": "review/docs/review_criteria_code.md",
            "ssot_refs": [
                {"path": "docs/rules/implementation_guidelines.md",
                 "priority": "P1", "doc_type": "rules"}
            ],
            "check_order": ["P1", "P2", "P3"],
            "severity_source": "plugins/forge/docs/review_priorities_spec.md",
            "output_filename": "review_code.md"
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
# review_packet.output_filename のフォーマット: review_<種別>.md
_OUTPUT_FILENAME_RE = re.compile(r"^review_[a-z0-9_-]+\.md$")


def validate_review_packet(data):
    """入力データをバリデーションする (ADR-032 新スキーマ)。

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

    # target_files: 非空の dict 配列 (ADR-032 で string[] から移行)
    if not isinstance(data.get("target_files"), list) or not data["target_files"]:
        raise ValueError("target_files は非空の配列が必須です")

    for i, item in enumerate(data["target_files"]):
        if not isinstance(item, dict):
            raise ValueError(
                f"target_files[{i}] は dict が必須です ({{'path': '...'}} 形式、"
                f"ADR-032 で string 配列から dict 配列に移行): {item!r}"
            )
        path = item.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError(
                f"target_files[{i}].path は非空文字列が必須です: {item!r}"
            )

    if not isinstance(data.get("reference_docs"), list):
        raise ValueError("reference_docs は配列が必須です")

    for i, doc in enumerate(data.get("reference_docs", [])):
        if not isinstance(doc, dict):
            raise ValueError(
                f"reference_docs[{i}] は dict が必須です ({{'path': '...'}} 形式): {doc!r}"
            )
        if not doc.get("path"):
            raise ValueError(f"reference_docs[{i}].path は必須です")

    for i, code in enumerate(data.get("related_code", [])):
        if not isinstance(code, dict):
            raise ValueError(
                f"related_code[{i}] は dict が必須です "
                f"({{'path': '...', 'reason': '...'}} 形式): {code!r}"
            )
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

    # ssot_refs: 必須非空配列 (ADR-032 で doc_path → path に統一)
    ssot_refs = packet.get("ssot_refs")
    if not isinstance(ssot_refs, list) or not ssot_refs:
        raise ValueError("review_packet.ssot_refs は非空の配列が必須です")

    for i, ref in enumerate(ssot_refs):
        if not isinstance(ref, dict):
            raise ValueError(f"review_packet.ssot_refs[{i}] は dict が必須です")
        path = ref.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError(
                f"review_packet.ssot_refs[{i}].path は必須です "
                "(ADR-032: 旧 `doc_path` キーは path に統一)"
            )
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

    # output_filename: 必須、フォーマット検証、../ 禁止、絶対パス禁止
    # (ADR-032 で output_path から改名)
    output_filename = packet.get("output_filename")
    if not isinstance(output_filename, str) or not output_filename:
        raise ValueError(
            "review_packet.output_filename は必須です "
            "(ADR-032: 旧 `output_path` キーは output_filename に改名)"
        )
    if ".." in output_filename.split("/"):
        raise ValueError(
            f"review_packet.output_filename に ../ は使用できません: {output_filename!r}"
        )
    if output_filename.startswith("/"):
        raise ValueError(
            f"review_packet.output_filename に絶対パスは使用できません: {output_filename!r}"
        )
    if not _OUTPUT_FILENAME_RE.match(output_filename):
        raise ValueError(
            "review_packet.output_filename は ^review_[a-z0-9_-]+\\.md$ 形式が必須です: "
            f"{output_filename!r}"
        )


def build_refs_text(data):
    """入力データから refs.yaml のテキストを構築する (ADR-032 新スキーマ)。

    トップレベル順序: target_files / reference_docs / review_packet / related_code

    Args:
        data: バリデーション済みの dict

    Returns:
        str: refs.yaml のテキスト
    """
    lines = []

    # target_files (ADR-032: dict 配列)
    lines.append("target_files:")
    _append_object_list(lines, data["target_files"], indent="  ")
    lines.append("")

    # reference_docs (空なら出力しない)
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
    lines.append("  check_order:")
    for step in packet["check_order"]:
        lines.append(f"    - {yaml_scalar(step)}")
    lines.append(f"  severity_source: {yaml_scalar(packet['severity_source'])}")
    lines.append(
        f"  output_filename: {yaml_scalar(packet['output_filename'])}"
    )
    lines.append("")

    # related_code (任意)
    related = data.get("related_code")
    if related:
        lines.append("related_code:")
        _append_object_list(lines, related, indent="  ")
        lines.append("")

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
    """refs.yaml を書き出す。"""
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
