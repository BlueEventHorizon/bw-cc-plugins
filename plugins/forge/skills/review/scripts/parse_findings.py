#!/usr/bin/env python3
"""review: Codex 返信本文の重大度別 finding 分解 CLI。

Codex の返信本文は自由記述markdown（DES-045 §3.4 の契約: 重大度マーカー
（🔴/🟡/🟢）+ `ファイルパス:行` を含む自由記述、厳密な JSON 構造ではない）。
本文を行単位に走査し、行頭（箇条書き記号・番号付けを除く）に severity マーカーが
ある行を「新しい finding の開始」とみなして、次の finding 開始行（または完了宣言行）
までをその finding の本文として束ねる。

使い方:
    python3 parse_findings.py --body-file <path>
"""

import argparse
import json
import re
from pathlib import Path

SEVERITY_MARKERS = {"🔴": "critical", "🟡": "major", "🟢": "minor"}
COMPLETION_LINES = ("REVIEW_RESULT: approved", "REVIEW_RESULT: findings")
HEADER_RE = re.compile(r"^\[msg-review\]\s")
FENCE_RE = re.compile(r"^(```|~~~)")

# 行頭（任意の箇条書き記号 `-`/`*` または番号付け `1.` を除いた直後）に severity
# マーカーがある行のみを finding の開始とみなす。文中・引用・コード例に偶然出現する
# マーカー（例:「概要: 🟡 major の基準を参照しました。」）を誤って finding として
# 抽出しないため（実 Codex レビューで発見）。
FINDING_START_RE = re.compile(r"^(?:[-*]|\d+\.)?\s*(🔴|🟡|🟢)")


def _is_indented_code_line(raw_line: str) -> bool:
    """CommonMark のインデントコードブロック（行頭4スペースまたはタブ）かどうかを判定する。

    fenced code block（\\`\\`\\`）だけでなく、Markdown のもう一つの標準的なコード
    ブロック記法も除外対象にする（実 Codex レビューで発見: `.lstrip()` によって
    インデントが失われ、インデントコードブロック内の例示マーカーが finding として
    誤抽出されていた）。
    """
    return raw_line.startswith("    ") or raw_line.startswith("\t")


def _finding_start_severity(raw_line: str) -> str | None:
    """行が finding の開始行かどうかを判定し、該当すれば severity を返す。

    fenced/インデントいずれのコードブロックとも無関係な、通常のテキスト行のみを
    対象にする（呼び出し側で `in_fence`/`_is_indented_code_line` を確認済みの
    行のみ渡すこと）。
    """
    match = FINDING_START_RE.match(raw_line.lstrip())
    if match is None:
        return None
    return SEVERITY_MARKERS[match.group(1)]


def parse_findings(body: str) -> list[dict]:
    """本文から severity 別の finding リストを抽出する。

    finding の開始行（行頭に severity マーカー）が現れるたびに新しい finding を
    開始し、次の開始行（または本文中で最後に出現する完了宣言行）までを束ねてその
    finding の本文とする。プロトコルヘッダ行（本文先頭の `[msg-review] ...`）・
    最後に出現した完了宣言行以降（Stop フックが付与する返信ヒント等）はどの finding
    の本文にも含めない。

    **形式違反への fail-closed 対応**: 完了宣言行が `REVIEW_RESULT: findings`
    （指摘ありの宣言）であるにもかかわらず finding 開始行が一つも見つからない場合、
    本文全体を `severity: "unclassified"` の単一 finding として返す（空リストを
    返して所見を黙って落とさない。実 Codex レビューで発見: マーカーを欠いた実所見が
    空リストになり、受信モードが「重大度不明として対象外に報告する」ことすら
    できず見落としていた）。`REVIEW_RESULT: approved`（指摘なしの宣言）の場合は
    この fallback を適用しない——承認宣言と矛盾するため、本文中のマーカー無し
    説明文（「所見はありません」等）を偽の finding として抽出してしまう
    （approved なのに finding が0件でないという矛盾）ことを避ける。
    `gate_findings.py` の決定表は `critical`/`major` のみを自動修正対象とするため、
    `unclassified` は常に対象外（`excluded`）に振り分けられ、人間の確認に委ねられる。
    finding 開始行が1件以上見つかった場合は、その前後にある非自明なマーカー無し
    テキスト（前置き・要約等）は finding として扱わない（既存所見の narrative の
    一部とみなす）。

    **fenced code block 内は finding 開始として扱わない**: 自由記述 Markdown では
    返信形式の例や既存所見の引用をコードブロック（\\`\\`\\` または ~~~ で囲まれた範囲）
    で示すことがあり、その中に severity マーカーが含まれていても実在しない finding
    として抽出してしまう（実 Codex レビューで発見）。フェンス行（\\`\\`\\` 始まりの行）を
    追跡し、フェンス内では finding の開始判定を行わない（既存 finding の本文継続、
    またはマーカー無しの fallback 扱いとする）。
    """
    lines = body.splitlines()

    # 採用する完了宣言行を先に確定する（本文中で最後に出現したもの。SKILL.md 受信モード
    # Step 1「完了宣言行の照合」と同じ「最後に出現した行を採用する」規則）。この行より
    # 後ろの行（Stop フックが付与する複数行の返信ヒント等）は finding の本文に一切
    # 含めない。`continue` で完了宣言行自体だけを読み飛ばすと、宣言後に連結される
    # 返信ヒントが直前の finding の本文へ混入する（実 Codex レビューで発見。本セッション
    # で実際に観測した Stop フックの返信ヒント連結と同型の回帰）。
    last_completion_index: int | None = None
    declared_findings = False
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if stripped in COMPLETION_LINES:
            last_completion_index = index
            declared_findings = stripped == "REVIEW_RESULT: findings"

    content_lines = lines if last_completion_index is None else lines[:last_completion_index]

    findings: list[dict] = []
    current_severity: str | None = None
    current_lines: list[str] = []
    any_marker_found = False
    fallback_lines: list[str] = []
    in_fence = False

    def flush() -> None:
        if current_severity is None:
            return
        text = "\n".join(current_lines).strip()
        if text:
            findings.append({"severity": current_severity, "text": text})

    for index, raw_line in enumerate(content_lines):
        stripped = raw_line.strip()
        if index == 0 and HEADER_RE.match(stripped):
            continue
        if stripped in COMPLETION_LINES:
            # 最後の宣言行より前に出現した別の宣言行（防御的なケース）。本文には含めない。
            continue

        if FENCE_RE.match(stripped):
            in_fence = not in_fence
            if current_severity is not None:
                current_lines.append(raw_line)
            elif stripped:
                fallback_lines.append(raw_line)
            continue

        if in_fence or _is_indented_code_line(raw_line):
            severity = None
        else:
            severity = _finding_start_severity(raw_line)
        if severity is not None:
            any_marker_found = True
            flush()
            current_severity = severity
            current_lines = [raw_line]
        elif current_severity is not None:
            current_lines.append(raw_line)
        elif stripped:
            fallback_lines.append(raw_line)

    flush()

    if not any_marker_found and declared_findings:
        fallback_text = "\n".join(fallback_lines).strip()
        if fallback_text:
            return [{"severity": "unclassified", "text": fallback_text}]

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Codex 返信本文の重大度別 finding 分解 CLI",
    )
    parser.add_argument("--body-file", required=True, help="Codex 返信本文が書かれたファイルのパス")
    args = parser.parse_args()

    body = Path(args.body_file).read_text(encoding="utf-8")
    findings = parse_findings(body)
    print(json.dumps({"findings": findings}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
