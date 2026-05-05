"""findings から review artifacts を生成する純粋 renderer。"""


def generate_plan_yaml(findings):
    """指摘事項リストから plan.yaml テキストを生成する。"""
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

    return "\n".join(lines) + "\n"


def generate_review_md(findings):
    """統合済みの review.md テキストを生成する。"""
    lines = ["# 統合レビュー結果", ""]

    by_severity = {"critical": [], "major": [], "minor": []}
    for f in findings:
        sev = f.get("severity", "minor")
        if sev in by_severity:
            by_severity[sev].append(f)

    severity_labels = {
        "critical": "🔴致命的問題",
        "major": "🟡品質問題",
        "minor": "🟢改善提案",
    }

    for sev in ("critical", "major", "minor"):
        items = by_severity[sev]
        lines.append(f"### {severity_labels[sev]}")
        lines.append("")
        if not items:
            lines.append("（なし）")
            lines.append("")
            continue
        for i, f in enumerate(items, 1):
            persp = f.get("perspective", "")
            persp_info = f" [{persp}]" if persp else ""
            lines.append(f'{i}. **{f["title"]}**{persp_info}')
            if f.get("location"):
                lines.append(f'   - 箇所: {f["location"]}')
            lines.append("")

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
