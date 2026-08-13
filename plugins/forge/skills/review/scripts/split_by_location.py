#!/usr/bin/env python3
"""review: 所見を「位置が確定しているもの / いないもの」へ分ける CLI。

バックエンドが共通 parser 契約に従って返した所見を 2 群へ分ける。契約は
forge:DES-066 §3.10 参照。

| 出力キー    | 意味                             |
| ----------- | -------------------------------- |
| `located`   | 位置が確定している所見           |
| `unlocated` | 位置が確定していない所見         |

## 判断はしない。データの欠損を見るだけである [MANDATORY]

本スクリプトは対象のコードも文書も読まない。見るのは**所見が位置情報を持っているか**
だけである。したがって「修正できるか」「修正してよいか」のいずれも決めていない。

かつてこの出力キーは `auto_fix` / `excluded` という名前だった。前者は「自動修正できる」
と読めるが実際には位置の有無しか見ておらず、**機械が修正の可否を判定しているかのような
誤解**を生んだ。後者は「何から除外されたのか」が名前から分からず、介入軸による除外と
位置未確定による除外が同じ語に混在したまま残骸が別の文書へ流出した。名前が実態と
一致していれば、どちらも起きなかった。

修正できるか・確認なしに直してよいかは、**所見と対象を読んだうえで AI が判断する**
（review 本体の手順 1）。その判断はこのスクリプトの外にある。

- **重大度は提示順の材料であり、修正の可否を決めない**（REQ-013 FNC-1304）
- **介入軸も受け取らない**。同じ入力には常に同じ出力を返す

使い方:
    python3 split_by_location.py --findings-json '<parse_findings.py の出力の findings 配列>'
"""

import argparse
import json


def _has_unknown_location(finding: dict) -> bool:
    """位置を特定できていない所見か（明示の `位置未確定` と位置表記の欠落の両方）。"""
    location = finding.get("location")
    return not isinstance(location, dict) or bool(location.get("unknown"))


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
        if _has_unknown_location(finding):
            unlocated.append(finding)
        else:
            located.append(finding)

    return {"located": located, "unlocated": unlocated}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="所見を位置が確定しているもの / いないものへ分ける CLI",
    )
    parser.add_argument(
        "--findings-json",
        required=True,
        help="parse_findings.py の findings 配列（JSON 文字列）",
    )
    args = parser.parse_args()

    findings = json.loads(args.findings_json)
    print(json.dumps(split_by_location(findings), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
