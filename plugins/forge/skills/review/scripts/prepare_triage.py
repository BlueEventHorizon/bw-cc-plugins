#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""review: 段階的提示の仕分けファイルを用意する。

`--interactive` は所見を 1 件ずつ人間へ提示して採否を得る。この提示は**設計上ターンを
またぐ**ため、所見・AI の評価・利用者の判断をコンテキストだけで保持すると、圧縮で失われた
ときに再レビューからやり直しになる。失われたこと自体も検知できない。

本スクリプトは、受領した所見配列を振り分け、仕分けファイルの骨格（アジェンダ表と所見ごとの
節）を組み立て、置き場へ書き出すところまでを一続きで行う。**振り分け結果の取り出し・列挙・
転記・置き場の組み立ては決定論的な処理であり、AI が手で行うと件数の取り違え・位置の写し
違いが静かに起きる。**

## ファイルは常に 1 つ

置き場に置くのは `TRIAGE_FILENAME` の 1 ファイルだけで、既存があれば上書きする。
review_id やラウンドで名前を分けると複数になり、「どれを開くのか」を解くための探索・
列挙・寿命管理が芋づる式に要る。1 つに保てばそれらは丸ごと不要になる。

前回の残りは依頼の開始時に利用者へ確認して片付ける（消すか、続きから進めるか）。
これはレビューの副産物を差分に混入させない後始末でもあり、再開の入口でもある。

## なぜ骨格だけか

背景・本質・推奨は AI の評価であり、機械的に決まらない。本スクリプトが埋めるのは所見が
運んできた事実（ID・重大度・位置・本文）だけで、評価欄は空のまま出す。AI が対話の中で
埋め、決着ごとに更新する。

## 振り分けの委譲

位置による振り分け（修正できる / できない）は `gate_findings.py` が持つ。本スクリプトは
同じ関数を呼ぶだけで、判定を複製しない。subprocess ではなく import で呼ぶのは、
`gate_findings()` が副作用を持たない純粋関数であり、プロセス分離で得られるものが
無いためである。

## 出力

書き出したパスと件数を JSON で標準出力へ書く。終了コードは 0。入力が不正な場合のみ
非ゼロで終了する。

## 依存

Python 標準ライブラリのみ。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gate_findings import gate_findings  # noqa: E402

#: 仕分けファイルの置き場（プロジェクトルート相対）
TRIAGE_DIR = Path(".claude") / ".temp" / "review"

#: 仕分けファイルの名前。
#:
#: **常に 1 つに保つ。** 名前を review_id やラウンドで分けると複数になり、「どれを開くのか」
#: という問題が生まれて探す仕組みが要る。1 つに限定すれば探す必要が無く、置き場を見れば
#: それが対象である。前回の残りは依頼の開始時に利用者へ確認して片付ける。
TRIAGE_FILENAME = "triage.md"

#: アジェンダ表のセルへ入れる要約の上限文字数（超過分は切り詰める）
SUMMARY_CELL_LIMIT = 80

#: 重大度の表示順（提示順の材料。採否の可否は決めない）
SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}

#: 重大度の表示記号
SEVERITY_MARK = {
    "critical": "🔴 critical",
    "major": "🟡 major",
    "minor": "🟢 minor",
}


def _severity_key(finding: dict) -> int:
    """重大度順（critical → major → minor）。未知の重大度は末尾へ置く。

    同じ重大度どうしの順序は入力順のまま（`sorted` が安定であるため）。
    """
    return SEVERITY_ORDER.get(finding.get("severity"), len(SEVERITY_ORDER))


def _severity_label(finding: dict) -> str:
    severity = finding.get("severity")
    return SEVERITY_MARK.get(severity, str(severity))


def _location_label(finding: dict) -> str:
    """`パス:行` 形式。位置未確定・欠落はその旨を返す。"""
    location = finding.get("location")
    if not isinstance(location, dict) or location.get("unknown"):
        return "位置未確定"
    path = location.get("path")
    if not path:
        return "位置未確定"
    line = location.get("line")
    return f"{path}:{line}" if line is not None else str(path)


def _summary_cell(text: str) -> str:
    """表のセルへ入れる要約。改行とパイプを畳み、長さを切り詰める。

    畳むだけでは足りない。所見の本文は数百字になることがあり、そのまま入れると
    アジェンダ表に背景まで流れ込んで表が読めなくなる（consult 提示原則が禁じる）。
    切り落とした全文は所見ごとの節にあるため、情報は失われない。
    """
    collapsed = " ".join(str(text).split()).replace("|", "\\|")
    if len(collapsed) <= SUMMARY_CELL_LIMIT:
        return collapsed
    return collapsed[:SUMMARY_CELL_LIMIT].rstrip() + "…"


def _assign_ids(findings: list[dict]) -> list[tuple[str, dict]]:
    """提示順に 01, 02, … の識別子を振る。

    識別子は利用者が所見を指す手段になるため、**採否が決まっても振り直さない**。
    並べ替えはここで一度だけ行う。
    """
    ordered = sorted(findings, key=_severity_key)
    return [(f"{i:02d}", finding) for i, finding in enumerate(ordered, start=1)]


def render(
    review_id: str,
    needs_decision: list[dict],
    excluded: list[dict],
    backend: str = "",
    round_number: int = 1,
) -> str:
    """仕分けファイルの Markdown を組み立てる。"""
    numbered = _assign_ids(needs_decision)
    lines: list[str] = []

    lines.append(f"# レビュー所見の仕分け: {review_id} (round {round_number})")
    lines.append("")
    lines.append("| 項目 | 値 |")
    lines.append("| --- | --- |")
    lines.append(f"| review_id | `{review_id}` |")
    lines.append(f"| ラウンド | {round_number} |")
    lines.append(f"| バックエンド | {backend or '（未記録）'} |")
    lines.append(f"| 判断が要る所見 | {len(numbered)} 件 |")
    lines.append(f"| 対象外の所見 | {len(excluded)} 件 |")
    lines.append("")

    lines.append("## アジェンダ")
    lines.append("")
    lines.append("| ID | 重大度 | 位置 | 状態 | 結果・課題 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for entry_id, finding in numbered:
        # 未決着の行は空にしない。ID と位置だけでは何が指摘されているのか分からず、
        # アジェンダが残件の一覧として機能しなくなる。決着したら結論で上書きする。
        lines.append(
            f"| {entry_id} | {_severity_label(finding)} | `{_location_label(finding)}` "
            f"| 未着手 | {_summary_cell(finding.get('text', ''))} |"
        )
    if not numbered:
        lines.append("| — | — | — | — | 判断が要る所見はありません |")
    lines.append("")

    for entry_id, finding in numbered:
        lines.append(f"## [{entry_id}] {_severity_label(finding)} `{_location_label(finding)}`")
        lines.append("")
        lines.append("**レビュアーの所見**:")
        lines.append("")
        lines.append(str(finding.get("text", "")).strip())
        lines.append("")
        lines.append("**背景**: <なぜこれが問題か>")
        lines.append("")
        lines.append("**本質**: <判断を左右しているのはどこか>")
        lines.append("")
        lines.append("**確信度**: <☑️ 確認済み / 🤔 推論 / 無印 未検証>")
        lines.append("")
        lines.append("**推奨**: <採用する / 採用しない。理由を 1 行>")
        lines.append("")
        lines.append("**決着**: <利用者の判断と理由。AI が決めた場合はその旨>")
        lines.append("")

    if excluded:
        lines.append("## 対象外の所見")
        lines.append("")
        lines.append("位置が確定していないため、採用しても修正対象を確定できない所見。")
        lines.append("**人間が直接内容を確認する必要がある。**")
        lines.append("")
        lines.append("| 重大度 | 位置 | 所見 |")
        lines.append("| --- | --- | --- |")
        for finding in sorted(excluded, key=_severity_key):
            lines.append(
                f"| {_severity_label(finding)} | {_location_label(finding)} "
                f"| {_summary_cell(finding.get('text', ''))} |"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


def prepare(
    review_id: str,
    findings: list[dict],
    round_number: int,
    backend: str = "",
    project_root: Path | None = None,
) -> dict:
    """所見を振り分け、仕分けファイルを書き出して結果を返す。

    置き場もファイル名も呼び出し側に選ばせない。SKILL は同じ場面で常に同じ場所へ書くため、
    パスを引数にすると AI がその都度組み立てることになる。

    **既存があれば上書きする。** このファイルは進行中のラウンドを保持する作業ファイルで
    あって、決着の保管庫ではない。決着した内容は修正そのものと次ラウンドの対応表に出る。
    前回の残りは、依頼の開始時に利用者へ確認して片付ける（そこで残すと決めた場合は、
    そのファイルが再開の対象であり、本関数は呼ばれない）。
    """
    root = Path.cwd() if project_root is None else project_root
    triage_dir = root / TRIAGE_DIR
    triage_path = triage_dir / TRIAGE_FILENAME

    gated = gate_findings(findings)
    needs_decision = gated["auto_fix"]
    excluded = gated["excluded"]

    triage_dir.mkdir(parents=True, exist_ok=True)
    triage_path.write_text(
        render(review_id, needs_decision, excluded, backend, round_number),
        encoding="utf-8",
    )

    return {
        "triage_path": str(triage_path.relative_to(root)),
        "absolute_path": str(triage_path.resolve()),
        "needs_decision_count": len(needs_decision),
        "excluded_count": len(excluded),
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="段階的提示の仕分けファイルを用意する（振り分け・組み立て・書き出し）"
    )
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--round", required=True, type=int, help="ラウンド番号（1 以上）")
    parser.add_argument(
        "--findings-json",
        required=True,
        help="バックエンドが返した所見配列（JSON 文字列）",
    )
    parser.add_argument("--backend", default="", help="採用したバックエンド名")
    parser.add_argument(
        "--project-root",
        default=None,
        help="プロジェクトルート（省略時は cwd）。置き場はこの直下に固定される",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    root = Path(args.project_root) if args.project_root else None

    review_id = args.review_id.strip()
    if not review_id:
        print("review_id が空です", file=sys.stderr)
        return 1
    if args.round < 1:
        print(f"ラウンド番号は 1 以上です: {args.round}", file=sys.stderr)
        return 1
    findings = json.loads(args.findings_json)
    result = prepare(review_id, findings, args.round, args.backend, root)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
