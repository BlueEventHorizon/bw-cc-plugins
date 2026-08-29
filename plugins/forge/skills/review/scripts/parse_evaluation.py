#!/usr/bin/env python3
"""review: evaluator 応答の共通契約解釈 CLI。

evaluator（`forge:evaluator` カスタム Agent）は、reviewer が返した所見配列に対する
評価を厳密な JSON で返す。この JSON は自由記述ではなく決定論的にスクリプトが
検証・消費するデータであるため、応答全体を 1 つの JSON オブジェクトとして要求する
（`parse_findings.py` が扱う自由記述 markdown とは対照的な契約）。

期待する応答形状:
    {
      "evaluations": [
        {"index": 0, "disposition": "valid", "severity": "major", "reason": "...",
         "confidence": "confirmed", "fix_confident": true},
        {"index": 1, "disposition": "invalid", "severity": "minor", "reason": "..."}
      ]
    }

severity は reviewer の申告をそのまま転記したものではなく、evaluator が規範文書の重大度
カタログに照らして確認・訂正した値である（review_priorities_spec.md §2.2）。disposition の
値によらず必須。

disposition:
    - "valid": 妥当な指摘（到達目標の範囲外であっても、設計書・仕様書との乖離を
      指摘している場合を含む）。この場合のみ confidence / fix_confident が必須
    - "invalid": 不要な指摘
    - "misunderstanding": レビュアーの勘違いに基づく指摘
    - "out_of_scope": 到達目標で宣言した範囲外の「実装漏れ」として報告している指摘

confidence が "confirmed" でなければ fix_confident は真であってはならない
（review/SKILL.md Step 7 手順 1 の MANDATORY 制約と同じ）。

使い方:
    python3 parse_evaluation.py --findings-count <N> --response-file <path>
"""

import argparse
import json
import re
from pathlib import Path

VALID_DISPOSITIONS = {"valid", "invalid", "misunderstanding", "out_of_scope"}
VALID_CONFIDENCE = {"confirmed", "inferred", "unverified"}
VALID_SEVERITY = {"critical", "major", "minor"}

FENCE_RE = re.compile(r"```(?:json)?\s*\n(?P<body>.*?)\n```", re.DOTALL)


def _extract_json_text(raw: str) -> str:
    """応答本文から JSON 本体を取り出す。

    evaluator.md は最終応答を JSON オブジェクト 1 つだけにするよう指示しているが、
    実測では前置きの説明文が残ったまま JSON が続く応答が返ることがある（コード
    フェンスの有無を問わず）。指示の強化だけでは解消しないことを確認済みのため、
    抽出側を寛容にする。抽出した文字列の妥当性はこの関数の外（json.loads と
    後続の契約検証）が厳密に検査するため、抽出を寛容にしても契約の強さは落ちない
    ——誤って抽出した範囲は単に JSON として parse できず fail closed になるだけである。

    優先順位:
    1. ```json フェンス（本文中のどこにあってもよい）があれば、最後のブロックを使う
       （説明の途中に例示コードブロックを挟んだ場合でも、最終的な結論は末尾に来る）
    2. フェンスが無ければ、最初の `{` から最後の `}` までを候補にする
    3. どちらも見つからなければ、元の文字列全体をそのまま返す（従来どおり全体を
       JSON として parse を試み、失敗すれば contract violation として報告する）
    """
    stripped = raw.strip()
    fence_matches = list(FENCE_RE.finditer(stripped))
    if fence_matches:
        return fence_matches[-1].group("body")

    first = stripped.find("{")
    last = stripped.rfind("}")
    if first != -1 and last != -1 and last > first:
        return stripped[first : last + 1]

    return stripped


def interpret_evaluation(raw: str, findings_count: int) -> dict:
    """evaluator の応答本文を検証し、正規化した evaluations 配列を返す。

    契約違反は fail closed とする（曖昧な推測で欠損を埋めない）。呼び出し側は
    `status: "error"` を、evaluator への再依頼、または当該ラウンドの評価不能
    （人間の確認へ回す）として扱う。
    """
    text = _extract_json_text(raw)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"status": "error", "error": f"JSON parse error: {exc}"}

    if not isinstance(parsed, dict) or "evaluations" not in parsed:
        return {
            "status": "error",
            "error": "応答は evaluations キーを持つオブジェクトである必要があります",
        }

    evaluations = parsed["evaluations"]
    if not isinstance(evaluations, list):
        return {"status": "error", "error": "evaluations は配列である必要があります"}

    if len(evaluations) != findings_count:
        return {
            "status": "error",
            "error": (
                f"evaluations の件数（{len(evaluations)}）が"
                f"所見数（{findings_count}）と一致しません"
            ),
        }

    seen_indices: set[int] = set()
    for entry in evaluations:
        if not isinstance(entry, dict):
            return {
                "status": "error",
                "error": "evaluations の各要素はオブジェクトである必要があります",
            }

        index = entry.get("index")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index in seen_indices
            or not (0 <= index < findings_count)
        ):
            return {"status": "error", "error": f"index が不正または重複しています: {index!r}"}
        seen_indices.add(index)

        disposition = entry.get("disposition")
        if disposition not in VALID_DISPOSITIONS:
            return {
                "status": "error",
                "error": f"disposition が不正です（index={index}）: {disposition!r}",
            }

        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return {"status": "error", "error": f"reason が空です（index={index}）"}

        severity = entry.get("severity")
        if severity not in VALID_SEVERITY:
            return {
                "status": "error",
                "error": f"severity が不正です（index={index}）: {severity!r}",
            }

        if disposition == "valid":
            confidence = entry.get("confidence")
            fix_confident = entry.get("fix_confident")
            if confidence not in VALID_CONFIDENCE:
                return {
                    "status": "error",
                    "error": f"confidence が不正です（index={index}）: {confidence!r}",
                }
            if not isinstance(fix_confident, bool):
                return {
                    "status": "error",
                    "error": f"fix_confident が真偽値ではありません（index={index}）",
                }
            if fix_confident and confidence != "confirmed":
                return {
                    "status": "error",
                    "error": (
                        f"confidence が confirmed でないのに fix_confident が真です"
                        f"（index={index}）"
                    ),
                }

    evaluations_sorted = sorted(evaluations, key=lambda e: e["index"])
    return {"status": "ok", "evaluations": evaluations_sorted}


def main() -> int:
    parser = argparse.ArgumentParser(description="evaluator 応答の共通契約解釈 CLI")
    parser.add_argument(
        "--findings-count",
        required=True,
        type=int,
        help="reviewer から受け取った所見の件数",
    )
    parser.add_argument("--response-file", required=True, help="evaluator 最終応答本文のファイルパス")
    args = parser.parse_args()

    raw = Path(args.response_file).read_text(encoding="utf-8")
    print(json.dumps(interpret_evaluation(raw, args.findings_count), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
