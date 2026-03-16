#!/usr/bin/env python3
"""evaluation.yaml を生成する。

evaluator スキルの Step 3 で呼び出され、session_format.md 準拠の evaluation.yaml を書き出す。

Usage:
    echo '<json>' | python3 write_evaluation.py <session_dir>

stdin JSON:
    {
        "cycle": 1,
        "items": [
            {"id": 1, "severity": "critical", "title": "問題",
             "recommendation": "fix", "auto_fixable": true, "reason": "理由"}
        ]
    }

出力:
    stdout: {"status": "ok", "path": "...", "summary": {"fix": N, "skip": N, "needs_review": N}}
"""

import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR.parent))

from session.yaml_utils import write_nested_yaml

# evaluation.yaml の items オブジェクトの必須フィールド
REQUIRED_ITEM_FIELDS = {"id", "severity", "title", "recommendation", "reason"}
VALID_RECOMMENDATIONS = {"fix", "skip", "needs_review"}
VALID_SEVERITIES = {"critical", "major", "minor"}

# items 内のフィールド出力順序
ITEM_FIELD_ORDER = ["id", "severity", "title", "recommendation", "auto_fixable", "reason"]


def validate_evaluation_data(data):
    """入力データをバリデーションする。

    Args:
        data: stdin から受け取った dict

    Raises:
        ValueError: バリデーション失敗
    """
    if not isinstance(data.get("cycle"), int) or data["cycle"] < 1:
        raise ValueError("cycle は 1 以上の整数が必須です")

    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("items は非空の配列が必須です")

    for i, item in enumerate(items):
        missing = REQUIRED_ITEM_FIELDS - set(item.keys())
        if missing:
            raise ValueError(f"items[{i}] に必須フィールドがありません: {missing}")

        rec = item["recommendation"]
        if rec not in VALID_RECOMMENDATIONS:
            raise ValueError(
                f"items[{i}].recommendation は {VALID_RECOMMENDATIONS} のいずれかです: {rec}"
            )

        if item["severity"] not in VALID_SEVERITIES:
            raise ValueError(
                f"items[{i}].severity は {VALID_SEVERITIES} のいずれかです: {item['severity']}"
            )

        if rec == "fix" and "auto_fixable" not in item:
            raise ValueError(
                f"items[{i}]: recommendation=fix の場合 auto_fixable は必須です"
            )


def build_evaluation_sections(data):
    """入力データから write_nested_yaml 用の sections を組み立てる。

    Args:
        data: バリデーション済みの dict

    Returns:
        list[tuple]: sections リスト
    """
    # items のフィールド順序を揃える
    ordered_items = []
    for item in data["items"]:
        ordered = {}
        for key in ITEM_FIELD_ORDER:
            if key in item:
                ordered[key] = item[key]
        # 残りのフィールド（未知フィールド）
        for key in item:
            if key not in ordered:
                ordered[key] = item[key]
        ordered_items.append(ordered)

    return [
        ("cycle", data["cycle"]),
        ("items", ordered_items),
    ]


def summarize_evaluation(items):
    """recommendation の件数を集計する。

    Args:
        items: 指摘事項リスト

    Returns:
        dict: {"fix": N, "skip": N, "needs_review": N}
    """
    summary = {"fix": 0, "skip": 0, "needs_review": 0}
    for item in items:
        rec = item["recommendation"]
        if rec in summary:
            summary[rec] += 1
    return summary


def write_evaluation(session_dir, data):
    """evaluation.yaml を書き出す。

    Args:
        session_dir: セッションディレクトリパス
        data: バリデーション済みの入力データ

    Returns:
        str: 書き出したファイルのパス
    """
    sections = build_evaluation_sections(data)
    output_path = Path(session_dir) / "evaluation.yaml"
    write_nested_yaml(str(output_path), sections)
    return str(output_path)


def main():
    if len(sys.argv) != 2:
        json.dump(
            {"status": "error",
             "error": "Usage: echo '<json>' | python3 write_evaluation.py <session_dir>"},
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
        validate_evaluation_data(data)
    except ValueError as e:
        json.dump({"status": "error", "error": str(e)}, sys.stderr)
        sys.exit(1)

    path = write_evaluation(session_dir, data)
    summary = summarize_evaluation(data["items"])
    json.dump(
        {"status": "ok", "path": path, "summary": summary},
        sys.stdout, ensure_ascii=False,
    )
    print()


if __name__ == "__main__":
    main()
