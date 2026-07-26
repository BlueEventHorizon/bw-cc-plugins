#!/usr/bin/env python3
"""review: 介入軸（--auto-critical/--auto）による所見の振り分け CLI。

`parse_findings.py` が抽出した所見（severity 別）を、指定された介入軸の
モードに応じて「自動修正する（auto_fix）」「対象外として報告する（excluded）」
に振り分ける。決定表は DES-046 §3.2 参照。

`--interactive`（既定）・介入軸未指定時は本スクリプトを呼ばない（DES-046 §3.3。
Claude が全件を直接評価・修正する既存の受信モードフローのまま）。

使い方:
    python3 gate_findings.py --findings-json '<parse_findings.py の出力の findings 配列>' \
        --mode <auto-critical|auto>
"""

import argparse
import json

# 決定表。auto-critical は critical のみ自動修正、
# auto は critical + major を自動修正する。minor はどちらのモードでも対象外。
AUTO_FIX_SEVERITIES = {
    "auto-critical": {"critical"},
    "auto": {"critical", "major"},
}


def gate_findings(findings: list[dict], mode: str) -> dict:
    """findings を mode の決定表に従って auto_fix / excluded に振り分ける。

    severity が既知の値（critical/major/minor）以外、または重大度不明
    （parse_findings.py がマーカー無し逸脱で空リストを返した場合はここに
    到達しないが、個別の finding に不正な severity が混入した場合）は、
    安全側に倒して excluded とする（自動修正しない）。
    """
    auto_fix_set = AUTO_FIX_SEVERITIES.get(mode, set())
    auto_fix: list[dict] = []
    excluded: list[dict] = []

    for finding in findings:
        if finding.get("severity") in auto_fix_set:
            auto_fix.append(finding)
        else:
            excluded.append(finding)

    return {"auto_fix": auto_fix, "excluded": excluded}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="介入軸（--auto-critical/--auto）による所見の振り分け CLI",
    )
    parser.add_argument("--findings-json", required=True, help="parse_findings.py の findings 配列（JSON文字列）")
    parser.add_argument("--mode", required=True, choices=["auto-critical", "auto"])
    args = parser.parse_args()

    findings = json.loads(args.findings_json)
    result = gate_findings(findings, args.mode)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
