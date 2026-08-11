#!/usr/bin/env python3
"""review: 所見を「修正できるもの / できないもの」へ分ける CLI。

バックエンドが共通 parser 契約に従って返した所見を 2 群へ分ける。契約は
forge:DES-066 §3.10 参照。

| 出力キー   | 意味                                             |
| ---------- | ------------------------------------------------ |
| `auto_fix` | 自動修正できる所見（位置が確定している）         |
| `excluded` | 自動修正できない所見（位置が確定していない）     |

## 介入軸も重大度も見ない

**分けているのは所見の性質だけである。** 直せるかどうかを決めるのは位置が確定して
いるかだけで、介入軸（`--interactive` / `--auto`）にも重大度にも依存しない。

- **重大度は提示順の材料であり、修正の可否を決めない**（REQ-013 FNC-1304）。
  🔴 でも直し方に確信が無ければ直すべきでなく、🟢 でも確信があれば直してよい
- **確認なしに直してよいかを決めるのは本体の確信度**であり、所見の中身を読んで初めて
  決まる。決定論的な処理ではないため本スクリプトは扱わない
- したがって本スクリプトは介入軸を受け取らない。同じ入力には常に同じ出力を返す

使い方:
    python3 gate_findings.py --findings-json '<parse_findings.py の出力の findings 配列>'
"""

import argparse
import json


def _has_unknown_location(finding: dict) -> bool:
    """位置を特定できていない所見か（明示の `位置未確定` と位置表記の欠落の両方）。"""
    location = finding.get("location")
    return not isinstance(location, dict) or bool(location.get("unknown"))


def gate_findings(findings: list[dict]) -> dict:
    """findings を auto_fix（修正できる） / excluded（修正できない）へ分ける。

    **位置を特定できていない所見は修正の対象にできない [MANDATORY]**。修正は
    「どこを直すか」が確定していて初めて成立する。位置の無い所見を修正対象に含めると、
    どこを直すかを推測で決めることになり、修正後の allowlist 検証も「意図した変更か」
    を判定できない。

    人間が「修正する」と判断しても、修正対象を確定できない点は変わらない。位置の特定
    自体を人間に依頼することはできるが、それは採否の判断ではなく調査の依頼であり、
    本スクリプトの振り分けの外にある。
    """
    auto_fix: list[dict] = []
    excluded: list[dict] = []

    for finding in findings:
        if _has_unknown_location(finding):
            excluded.append(finding)
        else:
            auto_fix.append(finding)

    return {"auto_fix": auto_fix, "excluded": excluded}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="所見を修正できるもの / できないものへ分ける CLI",
    )
    parser.add_argument(
        "--findings-json",
        required=True,
        help="parse_findings.py の findings 配列（JSON 文字列）",
    )
    args = parser.parse_args()

    findings = json.loads(args.findings_json)
    print(json.dumps(gate_findings(findings), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
