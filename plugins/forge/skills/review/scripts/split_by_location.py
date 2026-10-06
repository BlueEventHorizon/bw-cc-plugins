#!/usr/bin/env python3
"""review: 所見を「位置が確定しているもの / いないもの」へ分ける CLI。

reviewer が書いた所見の結果（`findings` の配列を持つ JSON）を読み、所見を 2 群へ分ける。
所見の位置は文字列の配列で、特定できないときは `位置未確定` だけを要素とする。

| 出力キー    | 意味                             |
| ----------- | -------------------------------- |
| `located`   | 位置が確定している所見           |
| `unlocated` | 位置が確定していない所見         |

## 判断はしない。データの欠損を見るだけである [MANDATORY]

本スクリプトは対象のコードも文書も読まない。見るのは**所見が位置を持っているか**
だけである。したがって「修正できるか」「修正してよいか」のいずれも決めていない。

修正できるか・確認なしに直してよいかは、**所見と対象を読んだうえで本体が判断する**
（review 本体の吟味）。その判断はこのスクリプトの外にある。

- **重大度は提示順の材料であり、修正の可否を決めない**。所見は重大度を持たない
- **介入軸も受け取らない**。同じ入力には常に同じ出力を返す

## 位置が確定していない所見

次のいずれかに当たる所見は、位置が確定していない（`unlocated`）。それ以外は `located` である。

- `location` が配列でない、または無い（不正な入力を安全側に倒す）
- `location` が空の配列（空の配列に「未確定」の意味を持たせない。位置の確定とは見なさない）
- `location` の要素がすべて `位置未確定` である（要素が文字列でない値、空文字列、空白だけの文字列も、確定した位置とは見なさない）

`位置未確定` と確定した位置が混在する配列は、確定した位置を持つので `located` である。

## 使い方

    python3 split_by_location.py --findings-file <所見の結果の JSON のパス>

所見の結果のパスは、所見の結果を読み出す script が返した絶対パスである。所見の本文は
自由記述であり、引用符や改行を含むので、JSON 文字列として引数へ埋め込まない。

## 終了コード

| code | 意味                                                                   |
| ---- | ---------------------------------------------------------------------- |
| 0    | 振り分けが完了した（`unlocated` が空でも、所見が 0 件でも 0 である）   |
| 1    | 所見の結果を読めない、または `findings` が配列でない（`errors` を返す） |
| 2    | 引数を受理できない（`argparse`）                                       |
"""

import argparse
import json
from pathlib import Path

#: 位置を特定できないときに、reviewer が `location` の唯一の要素として渡す値
UNKNOWN_LOCATION = "位置未確定"


def _has_confirmed_location(finding: dict) -> bool:
    """確定した位置を 1 つ以上持つ所見か。"""
    location = finding.get("location") if isinstance(finding, dict) else None
    if not isinstance(location, list):
        return False
    return any(
        isinstance(entry, str) and entry.strip() and entry != UNKNOWN_LOCATION
        for entry in location
    )


def split_by_location(findings: list[dict]) -> dict:
    """findings を located（位置が確定） / unlocated（確定していない）へ分ける。

    **位置を特定できていない所見は修正の対象にできない [MANDATORY]**。修正は
    「どこを直すか」が確定していて初めて成立する。位置の無い所見を修正対象に含めると、
    どこを直すかを推測で決めることになり、修正後の allowlist 検証も「意図した変更か」
    を判定できない。

    人間が「修正する」と判断しても、修正対象を確定できない点は変わらない。位置の特定
    自体を人間に依頼することはできるが、それは採否の判断ではなく調査の依頼であり、
    本スクリプトの振り分けの外にある。
    """
    located: list[dict] = []
    unlocated: list[dict] = []

    for finding in findings:
        if _has_confirmed_location(finding):
            located.append(finding)
        else:
            unlocated.append(finding)

    return {"located": located, "unlocated": unlocated}


def _fail(*messages: str) -> int:
    print(json.dumps({"errors": list(messages)}, ensure_ascii=False))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="所見を位置が確定しているもの / いないものへ分ける CLI",
    )
    parser.add_argument(
        "--findings-file",
        required=True,
        help="所見の結果（`findings` の配列を持つ JSON）のパス",
    )
    args = parser.parse_args()

    try:
        result = json.loads(Path(args.findings_file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _fail(f"所見の結果を読めません: {exc}")

    findings = result.get("findings") if isinstance(result, dict) else None
    if not isinstance(findings, list):
        return _fail("所見の結果が `findings` の配列を持っていません")

    print(json.dumps(split_by_location(findings), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
