#!/usr/bin/env python3
"""review.md から指摘事項を抽出し plan.yaml を生成する。

review.md の 🔴🟡🟢 マーカー付きセクションをパースし、
session_format.md のスキーマに準拠した plan.yaml を出力する。

Usage:
    python3 extract_review_findings.py <session_dir>
        session_dir モード: review_*.md を glob で収集し統合
        出力: {session_dir}/plan.yaml + {session_dir}/review.md

    python3 extract_review_findings.py <session_dir> --review-only
        --review-only モード: plan.yaml を書き換えず review.md のみ再生成
        evaluator が review_{perspective}.md を書き換えた後、
        判定情報を保持したまま統合 review.md を再生成するのに使う

    python3 extract_review_findings.py <review_md_path> <output_plan_yaml_path>
        旧モード（後方互換）: 単一ファイルを処理

出力:
    stdout: JSON サマリー {"status": "ok", "total": N, "critical": N, "major": N, "minor": N}
    ファイル: plan.yaml + review.md（session_dir モード）または plan.yaml のみ（旧モード）
"""

import glob
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

# severity の優先順位（重複除去時に最高を採用）
SEVERITY_PRIORITY = {'critical': 3, 'major': 2, 'minor': 1}

# 指摘事項の番号付きパターン（例: "1. **[問題名]**: 説明" or "1. **問題名**: 説明"）
FINDING_PATTERN = re.compile(r'^\d+\.\s+\*\*(?:\[)?(.+?)(?:\])?\*\*\s*[:：]\s*(.*)')

# 箇所行のパターン（例: "   - 箇所: path/to/file.py:42"）
LOCATION_PATTERN = re.compile(r'^\s+-\s+箇所\s*[:：]\s*(.*)')


def extract_findings(content):
    """review.md から指摘事項を抽出する。

    各 finding には `body` キーも含める。
    body は「その指摘の開始行から次の指摘/セクション直前まで」の原文で、
    重複項目の各 perspective 内容を併記する際に使う。

    Args:
        content: review.md の内容（文字列）

    Returns:
        list[dict]: 指摘事項リスト。各要素は {id, severity, title, location, body, ...} を含む
    """
    findings = []
    current_severity = None
    finding_id = 0
    body_lines = []  # 現在の指摘事項の本文行(原文)

    def flush_body():
        # 同じ finding を 2 度閉じない(severity 切り替え後の余分な本文行が
        # 前の finding の body を上書きするのを防ぐ)。
        # 2 回目以降の flush は no-op。
        if not findings or findings[-1].get('_body_closed'):
            return
        trimmed = list(body_lines)
        while trimmed and trimmed[-1].strip() == '':
            trimmed.pop()
        if trimmed:
            findings[-1]['body'] = '\n'.join(trimmed)
        findings[-1]['_body_closed'] = True

    def start_finding(title, line):
        nonlocal finding_id, body_lines
        flush_body()
        finding_id += 1
        findings.append({
            'id': finding_id,
            'severity': current_severity,
            'title': title,
            'location': '',
            'status': 'pending',
            'fixed_at': '',
            'files_modified': [],
            'skip_reason': '',
            'body': '',
        })
        body_lines = [line]

    for line in content.split('\n'):
        stripped = line.strip()

        # セクション見出しの検出（### 🔴致命的問題 等）
        if stripped.startswith('#'):
            severity_switched = False
            for marker, severity in SECTION_MARKERS.items():
                if marker in stripped:
                    flush_body()
                    body_lines = []
                    current_severity = severity
                    severity_switched = True
                    break
            if not severity_switched:
                # マーカーのないヘッダー
                if '### ' in stripped and current_severity:
                    lower = stripped.lower()
                    if 'サマリー' in lower or 'summary' in lower:
                        flush_body()
                        body_lines = []
                        current_severity = None

            # # 行でも FINDING_PATTERN を試行（### 1. **問題名** 形式への対応）
            if current_severity:
                heading_text = stripped.lstrip('#').strip()
                match = FINDING_PATTERN.match(heading_text)
                if match:
                    start_finding(match.group(1).strip(), line)
            continue

        if current_severity is None:
            continue

        # 箇所行の検出（直前の finding に location を設定）
        # LOCATION_PATTERN は先頭スペースを含むため、strip 前の line を使用
        loc_match = LOCATION_PATTERN.match(line)
        if loc_match and findings:
            findings[-1]['location'] = loc_match.group(1).strip()
            body_lines.append(line)
            continue

        # 指摘事項の検出
        match = FINDING_PATTERN.match(stripped)
        if match:
            start_finding(match.group(1).strip(), line)
            continue

        # 通常の本文行(現在の finding の body に蓄積)
        # _body_closed 済みの finding には追加しない(severity 切替後の
        # 余分行がぶら下がって上書きするのを防ぐ)。
        if findings and not findings[-1].get('_body_closed'):
            body_lines.append(line)

    flush_body()
    # 内部フラグを除去(呼び出し元には見せない)
    for f in findings:
        f.pop('_body_closed', None)
    return findings


def extract_perspective_from_filename(filename):
    """ファイル名 review_{name}.md から perspective 名を抽出する。

    Args:
        filename: ファイル名（例: "review_logic.md"）

    Returns:
        str: perspective 名（例: "logic"）。抽出できない場合は空文字列
    """
    match = re.match(r'^review_(.+)\.md$', filename)
    if match:
        return match.group(1)
    return ''


def deduplicate_findings(findings):
    """ベストエフォートの重複除去を行う。

    検出条件: タイトル文字列の完全一致 AND 箇所（location）文字列の完全一致
    統合ルール:
        - severity: 最高を採用（critical > major > minor）
        - perspectives: 統合元の perspective 名を全て記録
        - bodies_by_perspective: 重複項目は各 perspective の原文本文を保持
          (Claude が両 perspective の指摘内容を並列で確認できるよう残す)

    Args:
        findings: perspective 付きの指摘事項リスト

    Returns:
        list[dict]: 重複除去済みの指摘事項リスト（ID は振り直し済み）
    """
    # (title, location) をキーにして重複を検出
    seen = {}  # key -> index in result
    result = []

    for f in findings:
        key = (f['title'], f.get('location', ''))
        if key in seen:
            # 重複: 既存の finding を統合
            existing = result[seen[key]]
            # severity: 最高を採用
            if SEVERITY_PRIORITY.get(f['severity'], 0) > SEVERITY_PRIORITY.get(existing['severity'], 0):
                existing['severity'] = f['severity']
            # perspectives: 統合元を全て記録
            new_persp = f.get('perspective', '')
            if new_persp:
                if 'perspectives' not in existing:
                    # 初回統合: 既存の perspective を perspectives に変換
                    existing_persp = existing.pop('perspective', '')
                    existing['perspectives'] = [existing_persp] if existing_persp else []
                if new_persp not in existing['perspectives']:
                    existing['perspectives'].append(new_persp)
            # bodies_by_perspective: 各 perspective の原文本文を保持
            if 'bodies_by_perspective' not in existing:
                existing['bodies_by_perspective'] = {}
                # 既存 finding の body を初回統合時に登録
                first_persp = (
                    existing['perspectives'][0]
                    if existing.get('perspectives')
                    else existing.get('perspective', '')
                )
                if first_persp and existing.get('body'):
                    existing['bodies_by_perspective'][first_persp] = existing['body']
            if new_persp and f.get('body'):
                existing['bodies_by_perspective'][new_persp] = f['body']
        else:
            seen[key] = len(result)
            result.append(dict(f))  # コピーして追加

    # ID を振り直し
    for i, f in enumerate(result, 1):
        f['id'] = i

    return result


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
        # perspective / perspectives フィールド
        if 'perspectives' in f:
            persp_items = ', '.join(f['perspectives'])
            lines.append(f'    perspectives: [{persp_items}]')
        elif 'perspective' in f and f['perspective']:
            lines.append(f'    perspective: {f["perspective"]}')

    return '\n'.join(lines) + '\n'


def generate_review_md(findings):
    """統合済みの review.md テキストを生成する。

    Args:
        findings: 指摘事項リスト（重複除去済み）

    Returns:
        str: review.md のテキスト
    """
    lines = ['# 統合レビュー結果', '']

    # severity ごとにグループ化
    by_severity = {'critical': [], 'major': [], 'minor': []}
    for f in findings:
        sev = f.get('severity', 'minor')
        if sev in by_severity:
            by_severity[sev].append(f)

    severity_labels = {
        'critical': '🔴致命的問題',
        'major': '🟡品質問題',
        'minor': '🟢改善提案',
    }

    for sev in ('critical', 'major', 'minor'):
        items = by_severity[sev]
        lines.append(f'### {severity_labels[sev]}')
        lines.append('')
        if not items:
            lines.append('（なし）')
            lines.append('')
            continue
        for i, f in enumerate(items, 1):
            # perspective 情報の表示
            persp_info = ''
            if 'perspectives' in f:
                persp_info = f' [{", ".join(f["perspectives"])}]'
            elif 'perspective' in f and f['perspective']:
                persp_info = f' [{f["perspective"]}]'
            lines.append(f'{i}. **{f["title"]}**{persp_info}')
            if f.get('location'):
                lines.append(f'   - 箇所: {f["location"]}')

            # 重複項目の各 perspective 内容併記
            bodies = f.get('bodies_by_perspective')
            if bodies and len(bodies) > 1:
                lines.append('')
                for persp in f.get('perspectives', []):
                    body = bodies.get(persp)
                    if not body:
                        continue
                    lines.append(f'#### {persp} の視点')
                    lines.append('')
                    lines.append(body)
                    lines.append('')
            lines.append('')

    # サマリー
    lines.append('### サマリー')
    lines.append('')
    lines.append(f'- 🔴致命的: {len(by_severity["critical"])}件')
    lines.append(f'- 🟡品質: {len(by_severity["major"])}件')
    lines.append(f'- 🟢改善: {len(by_severity["minor"])}件')
    lines.append(f'- 合計: {len(findings)}件')
    lines.append('')

    return '\n'.join(lines)


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


def run_session_dir_mode(session_dir, review_only=False):
    """session_dir モード: review_*.md を glob で収集し統合する。

    Args:
        session_dir: セッションディレクトリのパス
        review_only: True のとき plan.yaml を書き換えず review.md のみ再生成

    Returns:
        int: 終了コード
    """
    session_path = Path(session_dir)
    if not session_path.is_dir():
        error = {"status": "error", "error": f"Directory not found: {session_dir}"}
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    # review_*.md を glob で収集（アルファベット順ソート）
    # .raw.md（reviewer 原文バックアップ）は除外する。
    # `review_*.md` パターンは shell glob として `review_logic.raw.md` にも
    # マッチするため、明示的に除外しないと evaluator 書き換え後の Phase 4
    # Step 1.5 で原文と最終系の両方が二重処理される。
    review_files = sorted(
        f for f in glob.glob(str(session_path / 'review_*.md'))
        if not Path(f).name.endswith('.raw.md')
    )

    if not review_files:
        error = {"status": "error", "error": f"No review_*.md files found in: {session_dir}"}
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    # 各ファイルから指摘事項を抽出（ファイル間通し番号）
    all_findings = []
    global_id = 0
    processed_files = []
    failed_files = []

    for review_file in review_files:
        review_path = Path(review_file)
        filename = review_path.name
        perspective = extract_perspective_from_filename(filename)

        try:
            content = review_path.read_text(encoding='utf-8')
        except (OSError, IOError, UnicodeDecodeError) as e:
            print(f"Warning: {filename}: {e}", file=sys.stderr)
            failed_files.append(filename)
            continue

        findings = extract_findings(content)
        if not findings and not content.strip():
            # 空ファイルはスキップ（partial-failure）
            failed_files.append(filename)
            continue

        processed_files.append(filename)

        # ID をファイル間通し番号に振り直し、perspective を付与
        for f in findings:
            global_id += 1
            f['id'] = global_id
            if perspective:
                f['perspective'] = perspective
            all_findings.append(f)

    if not all_findings and not processed_files:
        # 全ファイルが失敗 or 全ファイルが空
        error = {"status": "error", "error": "All review files failed or contained no findings"}
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    # ベストエフォート重複除去
    deduplicated = deduplicate_findings(all_findings)

    # plan.yaml を生成・書き出し（--review-only のときは判定情報を保護するためスキップ）
    if not review_only:
        plan_yaml = generate_plan_yaml(deduplicated)
        (session_path / 'plan.yaml').write_text(plan_yaml, encoding='utf-8')

    # review.md を生成・書き出し
    review_md = generate_review_md(deduplicated)
    (session_path / 'review.md').write_text(review_md, encoding='utf-8')

    # サマリーを stdout に出力
    result = summarize(deduplicated)
    result["status"] = "ok"
    result["files_processed"] = len(processed_files)
    result["files_failed"] = len(failed_files)
    result["duplicates_removed"] = len(all_findings) - len(deduplicated)
    result["review_only"] = review_only
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_legacy_mode(review_md_path, output_path):
    """旧モード（後方互換）: 単一ファイルを処理する。

    Args:
        review_md_path: review.md のパス
        output_path: 出力先 plan.yaml のパス

    Returns:
        int: 終了コード
    """
    try:
        content = Path(review_md_path).read_text(encoding='utf-8')
    except FileNotFoundError:
        error = {"status": "error", "error": f"File not found: {review_md_path}"}
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    findings = extract_findings(content)
    plan_yaml = generate_plan_yaml(findings)

    # plan.yaml を書き出し
    Path(output_path).write_text(plan_yaml, encoding='utf-8')

    # サマリーを stdout に出力
    result = summarize(findings)
    result["status"] = "ok"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main():
    args = sys.argv[1:]
    review_only = False
    if '--review-only' in args:
        review_only = True
        args = [a for a in args if a != '--review-only']

    if len(args) == 1:
        # session_dir モード
        sys.exit(run_session_dir_mode(args[0], review_only=review_only))
    elif len(args) == 2 and not review_only:
        # 旧モード（後方互換）
        sys.exit(run_legacy_mode(args[0], args[1]))
    else:
        print("Usage:", file=sys.stderr)
        print("  extract_review_findings.py <session_dir>                        # session_dir モード", file=sys.stderr)
        print("  extract_review_findings.py <session_dir> --review-only          # review.md のみ再生成", file=sys.stderr)
        print("  extract_review_findings.py <review_md_path> <output_plan_yaml>  # 旧モード", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
