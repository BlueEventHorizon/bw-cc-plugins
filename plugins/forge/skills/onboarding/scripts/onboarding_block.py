#!/usr/bin/env python3
"""onboarding が利用プロジェクトの CLAUDE.md へ転記する規範ブロックを生成・更新する。

転記元は onboarding 自身の SKILL.md で、`FORGE_ONBOARDING_COPY_START` / `_END` で
囲まれた範囲をコピーする。見出し名には依存しない（見出しに依存すると、節の改名や
タグ追加で転記範囲が黙って変わる）。

コピーは原文のままで、書き換えは一切行わない。転記先での見出し重複を避けるための `forge`
接頭辞は転記元の SKILL.md 側で付けておく規約とし、その遵守はテストで検証する（script 側で
変換すると、変換が効かなかったときに衝突が黙って戻る）。
抽出・ハッシュ計算・差し込みは決定論的処理なので全てこのスクリプトが行い、
AI は起動と承認提示だけを担う（内容の取捨をここで行うと冪等性が壊れる）。

使い方:
    onboarding_block.py --check [--target CLAUDE.md]
    onboarding_block.py --write [--target CLAUDE.md]

--check は JSON を返すだけでファイルを変更しない。status は次のいずれか:
    absent  マーカーが無い（初回。転記元の内容はまだ CLAUDE.md 経由で文脈に入らない）
    stale   マーカーはあるがハッシュ不一致（転記元が更新された）
    fresh   マーカーがありハッシュ一致（転記済みで最新）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# 転記元。このスクリプトは skills/onboarding/scripts/ に置かれる
SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"

# 転記元（SKILL.md）側のマーカー。転記先（CLAUDE.md）側とは別名にする
COPY_START = "<!-- FORGE_ONBOARDING_COPY_START -->"
COPY_END = "<!-- FORGE_ONBOARDING_COPY_END -->"

MARKER_START_RE = re.compile(
    r"^<!--\s*FORGE_ONBOARDING_START(?:\s+hash=([0-9a-f]+))?\s*-->[ \t]*$",
    re.MULTILINE,
)
MARKER_END = "<!-- FORGE_ONBOARDING_END -->"

# BR-001: スラッシュコマンド形式はプラグインモード専用で解決できないため、スキルは名前で指す
CHROME = (
    "> このブロックは forge の onboarding スキルが生成する。手で編集しない（次回実行で上書きされる）。\n"
    "> `${CLAUDE_PLUGIN_ROOT}` は forge プラグインの配置先を指すプレースホルダであり、"
    "この文脈では実パスに解決されない。実体を読むには onboarding スキルを起動する。\n"
    "> forge はこのブロックの範囲だけ CLAUDE.md を利用している。ブロックの外側はプロジェクトの"
    "所有物。"
)


class BlockError(RuntimeError):
    """マーカーが壊れている等、書き込みを中止すべき状態。"""


def extract_copy_region(skill_md_text: str) -> str:
    """転記元マーカーで囲まれた範囲を原文のまま返す。見出し名には依存しない。"""
    n_start = skill_md_text.count(COPY_START)
    n_end = skill_md_text.count(COPY_END)
    if n_start != 1 or n_end != 1:
        raise BlockError(
            f"転記元マーカーが対になっていない（COPY_START={n_start} 個 / COPY_END={n_end} 個）。"
            "SKILL.md を修復してから再実行する"
        )
    i = skill_md_text.index(COPY_START) + len(COPY_START)
    j = skill_md_text.index(COPY_END)
    if j < i:
        raise BlockError("COPY_END が COPY_START より前にある。SKILL.md を修復してから再実行する")
    region = skill_md_text[i:j].strip("\n")
    if not region.strip():
        raise BlockError("転記範囲が空である。SKILL.md を確認する")
    return region


def render_body(region: str) -> str:
    return f"{CHROME}\n\n{region}"


def compute_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def render_block(body: str) -> str:
    digest = compute_hash(body)
    return f"<!-- FORGE_ONBOARDING_START hash={digest} -->\n\n{body}\n\n{MARKER_END}"


def locate_block(target_text: str) -> tuple[int, int, str | None] | None:
    """(開始位置, 終了位置, 記録されたハッシュ) を返す。マーカーが無ければ None。"""
    starts = list(MARKER_START_RE.finditer(target_text))
    ends = [m.start() for m in re.finditer(re.escape(MARKER_END), target_text)]
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1:
        raise BlockError(
            f"マーカーが対になっていない（START={len(starts)} 個 / END={len(ends)} 個）。手で修復してから再実行する"
        )
    start = starts[0]
    end = ends[0]
    if end < start.start():
        raise BlockError("FORGE_ONBOARDING_END が START より前にある。手で修復してから再実行する")
    return start.start(), end + len(MARKER_END), start.group(1)


def evaluate(target_text: str, expected_block: str) -> str:
    """`fresh` は「ブロックが今生成するものと完全一致」を意味する。

    マーカーに記録されたハッシュ値だけを比べると、本文を手で書き換えても数字が残って
    いる限り最新と誤判定する（最も起こりやすいドリフトを見逃す）。ブロック全体を
    期待値と突き合わせる。
    """
    found = locate_block(target_text)
    if found is None:
        return "absent"
    start, end, _recorded = found
    return "fresh" if target_text[start:end] == expected_block else "stale"


def splice(target_text: str, block: str) -> str:
    found = locate_block(target_text)
    if found is None:
        base = target_text.rstrip()
        return f"{base}\n\n{block}\n" if base else f"{block}\n"
    start, end, _ = found
    return target_text[:start] + block + target_text[end:]


def new_file_text(block: str) -> str:
    return f"# CLAUDE.md\n\n{block}\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="状態を返すだけ。書き込まない")
    mode.add_argument("--write", action="store_true", help="ブロックを生成・更新する")
    ap.add_argument("--target", default="CLAUDE.md", help="対象 CLAUDE.md（既定: カレントの CLAUDE.md）")
    ap.add_argument("--skill-md", default=str(SKILL_MD), help="転記元 SKILL.md（試験用）")
    args = ap.parse_args(argv)

    skill_path = Path(args.skill_md)
    if not skill_path.is_file():
        print(json.dumps({"error": f"転記元が見つからない: {skill_path}"}, ensure_ascii=False))
        return 2

    try:
        region = extract_copy_region(skill_path.read_text(encoding="utf-8"))
    except BlockError as exc:
        print(json.dumps({"error": str(exc), "skill_md": str(skill_path)}, ensure_ascii=False))
        return 3

    body = render_body(region)
    digest = compute_hash(body)
    block = render_block(body)

    target = Path(args.target)
    exists = target.is_file()
    current = target.read_text(encoding="utf-8") if exists else ""

    try:
        status = evaluate(current, block) if exists else "absent"
    except BlockError as exc:
        print(json.dumps({"error": str(exc), "target": str(target)}, ensure_ascii=False))
        return 3

    result = {
        "status": status,
        "hash": digest,
        "target": str(target),
        "target_exists": exists,
        # 参考情報。転記範囲の判定には使わない
        "headings": [ln for ln in region.splitlines() if ln.startswith("## ")],
    }

    if args.check:
        result["block"] = block
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if status == "fresh":
        result["action"] = "none"
        print(json.dumps(result, ensure_ascii=False))
        return 0

    text = new_file_text(block) if not exists else splice(current, block)
    target.write_text(text, encoding="utf-8")
    result["action"] = "created" if not exists else ("updated" if status == "stale" else "appended")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
