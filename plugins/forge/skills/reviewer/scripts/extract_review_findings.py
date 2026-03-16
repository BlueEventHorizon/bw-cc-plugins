#!/usr/bin/env python3
"""review.md から指摘事項を抽出し plan.yaml を生成する。

review.md の 🔴🟡🟢 マーカー付きセクションをパースし、
session_format.md のスキーマに準拠した plan.yaml を出力する。

Usage:
    python3 extract_review_findings.py <review_md_path> <output_plan_yaml_path>

出力:
    stdout: JSON サマリー {"status": "ok", "total": N, "critical": N, "major": N, "minor": N}
    ファイル: <output_plan_yaml_path> に plan.yaml を書き出し
"""

import json
import re
import sys
from pathlib import Path

# セクションマーカーと severity のマッピング
SECTION_MARKERS = {
    '🔴': 'critical',
    '🟡': 'major',
    '🟢': 'minor',
}

# 指摘事項の番号付きパターン（例: "1. **[問題名]**: 説明" or "1. **問題名**: 説明"）
FINDING_PATTERN = re.compile(r'^\d+\.\s+\*\*(?:\[)?(.+?)(?:\])?\*\*\s*[:：]\s*(.*)')

# 箇所行のパターン（例: "   - 箇所: path/to/file.py:42"）
LOCATION_PATTERN = re.compile(r'^\s+-\s+箇所\s*[:：]\s*(.*)')


def extract_findings(content):
    """review.md から指摘事項を抽出する。

    Args:
        content: review.md の内容（文字列）

    Returns:
        list[dict]: 指摘事項リスト。各要素は {id, severity, title} を含む
    """
    findings = []
    current_severity = None
    finding_id = 0

    for line in content.split('\n'):
        stripped = line.strip()

        # セクション見出しの検出（### 🔴致命的問題 等）
        if stripped.startswith('#'):
            for marker, severity in SECTION_MARKERS.items():
                if marker in stripped:
                    current_severity = severity
                    break
            else:
                # マーカーのないヘッダーは severity をリセットしない
                # （サマリーセクション等）
                if '### ' in stripped and current_severity:
                    # サマリーセクションに入ったらリセット
                    lower = stripped.lower()
                    if 'サマリー' in lower or 'summary' in lower:
                        current_severity = None

            # # 行でも FINDING_PATTERN を試行（### 1. **問題名** 形式への対応）
            if current_severity:
                heading_text = stripped.lstrip('#').strip()
                match = FINDING_PATTERN.match(heading_text)
                if match:
                    finding_id += 1
                    title = match.group(1).strip()
                    findings.append({
                        'id': finding_id,
                        'severity': current_severity,
                        'title': title,
                        'status': 'pending',
                        'fixed_at': '',
                        'files_modified': [],
                        'skip_reason': '',
                    })
            continue

        if current_severity is None:
            continue

        # 指摘事項の検出
        match = FINDING_PATTERN.match(stripped)
        if match:
            finding_id += 1
            title = match.group(1).strip()
            findings.append({
                'id': finding_id,
                'severity': current_severity,
                'title': title,
                'status': 'pending',
                'fixed_at': '',
                'files_modified': [],
                'skip_reason': '',
            })

    return findings


def generate_plan_yaml(findings):
    """指摘事項リストから plan.yaml テキストを生成する。

    session_format.md のスキーマに準拠。標準ライブラリのみ使用（NFR-02）。

    Args:
        findings: extract_findings() の戻り値

    Returns:
        str: plan.yaml のテキスト
    """
    lines = ['items:']

    for f in findings:
        lines.append(f'  - id: {f["id"]}')
        lines.append(f'    severity: {f["severity"]}')
        # title にコロンや特殊文字が含まれる場合はクォートする
        title = f['title']
        if ':' in title or '"' in title or "'" in title or title.startswith('{') or title.startswith('['):
            title = '"' + title.replace('\\', '\\\\').replace('"', '\\"') + '"'
        else:
            title = '"' + title + '"'
        lines.append(f'    title: {title}')
        lines.append(f'    status: {f["status"]}')
        lines.append(f'    fixed_at: ""')
        lines.append(f'    files_modified: []')
        lines.append(f'    skip_reason: ""')

    return '\n'.join(lines) + '\n'


def summarize(findings):
    """指摘事項のサマリーを返す。"""
    counts = {'critical': 0, 'major': 0, 'minor': 0}
    for f in findings:
        if f['severity'] in counts:
            counts[f['severity']] += 1

    return {
        'total': len(findings),
        'critical': counts['critical'],
        'major': counts['major'],
        'minor': counts['minor'],
    }


def main():
    if len(sys.argv) != 3:
        print("Usage: extract_review_findings.py <review_md_path> <output_plan_yaml_path>", file=sys.stderr)
        sys.exit(1)

    review_md_path = sys.argv[1]
    output_path = sys.argv[2]

    try:
        content = Path(review_md_path).read_text(encoding='utf-8')
    except FileNotFoundError:
        error = {"status": "error", "error": f"File not found: {review_md_path}"}
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)

    findings = extract_findings(content)
    plan_yaml = generate_plan_yaml(findings)

    # plan.yaml を書き出し
    Path(output_path).write_text(plan_yaml, encoding='utf-8')

    # サマリーを stdout に出力
    result = summarize(findings)
    result["status"] = "ok"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == '__main__':
    main()
