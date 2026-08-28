#!/usr/bin/env python3
"""review: reviewer 所見と evaluator 判定を機械的に結合する CLI（forge:DES-066 §3.10a / REQ-013 FNC-1322）。

reviewer の所見配列（`parse_findings.py` が生成した実体）と evaluator の判定配列
（`parse_evaluation.py` が検証済みの `evaluations`。`index`/`disposition`/`severity`/
`confidence`/`fix_confident` 等）は別々の配列として届く。両者は `index` で対応するが、
この対応付けを記憶に頼って結合すると、件数の不一致や `index` の欠落・重複を検証しない
まま結合してしまう危険がある。本スクリプトはこの結合を機械的に行う。

検証:
    1. 両配列の長さが一致すること
    2. evaluations 側の `index` の集合が `{0, ..., len(findings) - 1}` と完全一致すること
       （欠落・重複の検出）
いずれか不成立なら結合せずエラーを返す（呼び出し元はそのラウンドを
`halted_with_open_findings` として終端処理へ回す）。

結合: `index` が一致する finding と evaluation を 1 件ずつ、キーを 1 つの dict へ統合して
組にする。キー衝突が無いことを前提とするが、衝突した場合は evaluation 側の値を優先する。

使い方:
    python3 combine_findings_and_evaluations.py --findings-json '<findings 配列>' \\
        --evaluations-json '<evaluations 配列>'
"""

import argparse
import json


def combine_findings_and_evaluations(findings: list[dict], evaluations: list[dict]) -> dict:
    """findings と evaluations を `index` で対応させて 1 件ずつ結合する。

    検証を通らない場合は例外を投げず `{"status": "error", "message": ...}` を返す
    （呼び出し元がそのラウンドを未解決のまま終端処理へ回せる形にするため）。
    """
    if len(findings) != len(evaluations):
        return {
            "status": "error",
            "message": (
                f"findings の件数（{len(findings)}）と evaluations の件数"
                f"（{len(evaluations)}）が一致しません"
            ),
        }

    expected_indices = set(range(len(findings)))
    actual_indices = [entry.get("index") for entry in evaluations]
    if set(actual_indices) != expected_indices or len(actual_indices) != len(
        set(actual_indices)
    ):
        return {
            "status": "error",
            "message": (
                "evaluations の index 集合が {0, ..., "
                f"{len(findings) - 1}}} と一致しません（欠落または重複があります）: "
                f"{actual_indices!r}"
            ),
        }

    evaluations_by_index = {entry["index"]: entry for entry in evaluations}
    combined = [
        {**findings[index], **evaluations_by_index[index]}
        for index in range(len(findings))
    ]
    return {"status": "ok", "combined": combined}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="reviewer 所見と evaluator 判定を index で機械的に結合する CLI",
    )
    parser.add_argument(
        "--findings-json",
        required=True,
        help="parse_findings.py の findings 配列（JSON 文字列）",
    )
    parser.add_argument(
        "--evaluations-json",
        required=True,
        help="parse_evaluation.py の evaluations 配列（JSON 文字列）",
    )
    args = parser.parse_args()

    findings = json.loads(args.findings_json)
    evaluations = json.loads(args.evaluations_json)
    print(
        json.dumps(
            combine_findings_and_evaluations(findings, evaluations), ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
