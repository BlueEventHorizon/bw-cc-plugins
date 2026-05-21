"""findings から review artifacts を生成する純粋 renderer。"""

# severity の表示順 (DES-028 §3.5 / §4.1: critical → major → minor)
SEVERITY_ORDER = ("critical", "major", "minor")

# priority の表示順 (DES-028 §4.1 / review_priorities_spec §1)
# P1 → P2 → P3、priority 不明 (None) は最後
PRIORITY_ORDER = ("P1", "P2", "P3", None)

# severity セクション見出し (温存。FNC-404 / FNC-407)
SEVERITY_LABELS = {
    "critical": "🔴致命的問題",
    "major": "🟡品質問題",
    "minor": "🟢改善提案",
}

# priority サブセクション見出し (DES-028 §3.5 / review_priorities_spec §1)
PRIORITY_LABELS = {
    "P1": "ルール合致",
    "P2": "矛盾・齟齬",
    "P3": "不要な複雑化",
}


def generate_plan_yaml(findings):
    """指摘事項リストから plan.yaml テキストを生成する。

    入力順を保持する (id 採番の連番性は呼び出し側 extract_review_findings の責務)。
    plan.yaml への severity / priority 二軸ソート反映は upstream で id を採番する段階で
    行う設計。renderer は受け取った id をそのまま使う。
    """
    lines = ["items:"]

    for f in findings:
        lines.append(f'  - id: {f["id"]}')
        lines.append(f'    severity: {f["severity"]}')
        title = f["title"]
        if (
            ":" in title
            or '"' in title
            or "'" in title
            or title.startswith("{")
            or title.startswith("[")
        ):
            title = '"' + title.replace("\\", "\\\\").replace('"', '\\"') + '"'
        else:
            title = '"' + title + '"'
        lines.append(f"    title: {title}")
        lines.append(f'    status: {f["status"]}')
        lines.append('    fixed_at: ""')
        lines.append("    files_modified: []")
        lines.append('    skip_reason: ""')
        if f.get("perspective"):
            lines.append(f'    perspective: {f["perspective"]}')
        if f.get("priority"):
            lines.append(f'    priority: {f["priority"]}')

    return "\n".join(lines) + "\n"


def _render_finding_lines(index, finding):
    """1 件の finding を review.md 用の行リストに変換する。"""
    lines = []
    persp = finding.get("perspective", "")
    persp_info = f" [{persp}]" if persp else ""
    lines.append(f'{index}. **{finding["title"]}**{persp_info}')
    if finding.get("location"):
        lines.append(f'   - 箇所: {finding["location"]}')
    lines.append("")
    return lines


def generate_review_md(findings):
    """統合済みの review.md テキストを生成する。

    出力構造 (DES-028 §3.5 / §4.1):
      - severity 見出し (🔴致命的 / 🟡品質問題 / 🟢改善提案) は温存
      - 各 severity セクション内で priority (P1 / P2 / P3) サブセクション見出しを描画
      - priority=None の finding は priority 区分なしで severity セクション末尾に配置
      - severity → priority の二段ソート (stable)
    """
    lines = ["# 統合レビュー結果", ""]

    # severity ごとにグルーピング (順序保持)
    by_severity = {sev: [] for sev in SEVERITY_ORDER}
    for f in findings:
        sev = f.get("severity", "minor")
        if sev in by_severity:
            by_severity[sev].append(f)

    # 連番カウンタ (severity セクションごとにリセット)
    for sev in SEVERITY_ORDER:
        items = by_severity[sev]
        lines.append(f"### {SEVERITY_LABELS[sev]}")
        lines.append("")
        if not items:
            lines.append("（なし）")
            lines.append("")
            continue

        # severity 内で priority ごとにサブグルーピング (PRIORITY_ORDER 順)
        by_priority = {pr: [] for pr in PRIORITY_ORDER}
        for f in items:
            pr = f.get("priority")
            if pr not in by_priority:
                # 未知 priority は None 扱い
                pr = None
            by_priority[pr].append(f)

        # severity セクション内通算カウンタ
        idx = 0
        for pr in PRIORITY_ORDER:
            group = by_priority[pr]
            if not group:
                continue
            if pr is not None:
                # priority サブセクション見出しを描画
                lines.append(f"#### {pr} ({PRIORITY_LABELS[pr]})")
                lines.append("")
            # priority=None の group は見出しなしで severity セクション末尾に出力
            for f in group:
                idx += 1
                lines.extend(_render_finding_lines(idx, f))

    lines.append("### サマリー")
    lines.append("")
    lines.append(f'- 🔴致命的: {len(by_severity["critical"])}件')
    lines.append(f'- 🟡品質: {len(by_severity["major"])}件')
    lines.append(f'- 🟢改善: {len(by_severity["minor"])}件')
    lines.append(f"- 合計: {len(findings)}件")
    lines.append("")

    return "\n".join(lines)


def summarize(findings):
    """指摘事項のサマリーを返す。"""
    counts = {"critical": 0, "major": 0, "minor": 0}
    for f in findings:
        if f["severity"] in counts:
            counts[f["severity"]] += 1

    return {
        "total": len(findings),
        "critical": counts["critical"],
        "major": counts["major"],
        "minor": counts["minor"],
    }
