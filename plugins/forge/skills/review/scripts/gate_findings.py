#!/usr/bin/env python3
"""review: 介入軸（--auto-critical/--auto）による所見の振り分け CLI。

バックエンドが共通 parser 契約に従って返した所見（severity 別）を、指定された介入軸の
モードに応じて「自動修正する（auto_fix）」「対象外として報告する（excluded）」
に振り分ける。決定表は DES-046 §3.2 参照。

`--interactive`（既定）・介入軸未指定時は、現在の本体契約に従い `auto` として
本スクリプトを呼ぶ。

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


def _has_unknown_location(finding: dict) -> bool:
    """位置を特定できていない所見か（明示の `位置未確定` と位置表記の欠落の両方）。"""
    location = finding.get("location")
    return not isinstance(location, dict) or bool(location.get("unknown"))


def gate_findings(findings: list[dict], mode: str) -> dict:
    """findings を mode の決定表に従って auto_fix / excluded に振り分ける。

    severity が既知の値（critical/major/minor）以外の finding が混入した場合は、
    防御的に excluded とする。通常、重大度欠落はバックエンドの共通 parser が
    failure とするため本スクリプトへ到達しない。

    **位置を特定できていない所見は severity によらず excluded とする [MANDATORY]**。
    自動修正は「どこを直すか」が確定していて初めて安全に行える。位置の無い所見を
    auto_fix に含めると、修正対象を推測で決めることになり、allowlist 検証も
    「意図した変更か」を判定できない。人間の確認へ回す。
    """
    auto_fix_set = AUTO_FIX_SEVERITIES.get(mode, set())
    auto_fix: list[dict] = []
    excluded: list[dict] = []

    for finding in findings:
        if finding.get("severity") in auto_fix_set and not _has_unknown_location(finding):
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
