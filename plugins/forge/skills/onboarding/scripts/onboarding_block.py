#!/usr/bin/env python3
"""onboarding が利用プロジェクトの CLAUDE.md へ転記する規範ブロックを生成・更新する。

転記元は copy_block.md 専用ファイルで、その全文をコピーする。SKILL.md に置かない理由は、
SKILL.md が起動時に全文コンテキストへ注入されるためである。転記済み（fresh）のとき、
転記範囲は CLAUDE.md に一字一句同じ形で既にあるため、SKILL.md 側の複製は必ず二重読みになる。
専用ファイルなら script だけが読む。

コピーは原文のままで、書き換えは一切行わない。転記先での見出し重複を避けるための `forge`
接頭辞は copy_block.md 側で付けておく規約とし、その遵守はテストで検証する（script 側で
変換すると、変換が効かなかったときに衝突が黙って戻る）。

status の判定、次に取る行動、承認を求める文言は、いずれも status から一意に決まる。
決定論的な写像を AI に解釈させないため、--check の出力に載せる（AI は承認を求めることと、
返された command を実行することだけを担う）。

使い方:
    onboarding_block.py --check [--target CLAUDE.md] [--source copy_block.md]
    onboarding_block.py --write [--target CLAUDE.md] [--source copy_block.md]

--check は JSON を返すだけでファイルを変更しない。status は次のいずれか:
    absent  マーカーが無い（初回。転記元の内容はまだ CLAUDE.md 経由で文脈に入らない）
    stale   マーカーはあるがブロックが期待値と一致しない（転記元が更新された）
    fresh   転記済みで最新
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
from pathlib import Path

# 転記元。このスクリプトは skills/onboarding/scripts/ に置かれる
SOURCE = Path(__file__).resolve().parent.parent / "copy_block.md"

# 転記先（CLAUDE.md）側のマーカー
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

# 承認を求める文言。ハッシュ・マーカー名・引数といった内部の詳細を含めない
# （毎セッション読まされる文章になり、承認の判断にも必要でない）
ASK_ABSENT_EXISTING = "forge の規範を CLAUDE.md に追記してよいですか（既存の記述は変えません）"
ASK_ABSENT_MISSING = "このプロジェクトには CLAUDE.md がありません。作成してよいですか"
ASK_STALE = "forge の規範が更新されました。CLAUDE.md の該当箇所を更新してよいですか"


class BlockError(RuntimeError):
    """マーカーが壊れている等、書き込みを中止すべき状態。"""


def read_region(source_text: str) -> str:
    """転記元の全文を原文のまま返す。"""
    region = source_text.strip("\n")
    if not region.strip():
        raise BlockError("転記元が空である。copy_block.md を確認する")
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
    いる限り最新と誤判定する（最も起こりやすいドリフト）。ブロック全体を期待値と
    突き合わせる。
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


def ask_for(status: str, target_exists: bool) -> str | None:
    """status から承認文言を一意に決める。fresh は承認を要さない。"""
    if status == "fresh":
        return None
    if status == "stale":
        return ASK_STALE
    return ASK_ABSENT_EXISTING if target_exists else ASK_ABSENT_MISSING


def unsubstituted_placeholder(path: str) -> bool:
    """`${CLAUDE_PROJECT_DIR}` 等が実パスへ置換されずに渡されたか。

    置換されないまま通すと、実在しないパスを対象と判定し「CLAUDE.md がありません。
    作成してよいですか」と尋ねてしまう。承認する側からは正常な初回セットアップと
    区別できないため、黙って別の場所へ作る経路になる。中止に変える。
    """
    return "${" in path


def build_command(mode: str, target: str, source: str, defaults: dict[str, str]) -> str:
    """既定値と異なる引数だけを載せた実行コマンドを組む。

    返した文字列は呼び出し側がそのまま実行する。**argv 由来の値だけで組むこと**
    （ファイル内容由来の値を混ぜると、返り値をそのまま実行する前提が壊れる）。
    """
    argv = ["python3", str(Path(__file__).resolve()), mode]
    if target != defaults["target"]:
        argv += ["--target", target]
    if source != defaults["source"]:
        argv += ["--source", source]
    return shlex.join(argv)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="状態と次の行動を返すだけ。書き込まない")
    mode.add_argument("--write", action="store_true", help="ブロックを生成・更新する")
    ap.add_argument("--target", default="CLAUDE.md", help="対象 CLAUDE.md（既定: カレントの CLAUDE.md）")
    ap.add_argument("--source", default=str(SOURCE), help="転記元 copy_block.md（試験用）")
    args = ap.parse_args(argv)
    defaults = {"target": "CLAUDE.md", "source": str(SOURCE)}

    if unsubstituted_placeholder(args.target):
        print(
            json.dumps(
                {
                    "error": (
                        f"対象パスに未置換のプレースホルダが残っている: {args.target}"
                        "（SKILL.md の ${CLAUDE_PROJECT_DIR} が実パスへ置換されていない）。"
                        "置換される文脈から実行する"
                    )
                },
                ensure_ascii=False,
            )
        )
        return 3

    source_path = Path(args.source)
    if not source_path.is_file():
        print(json.dumps({"error": f"転記元が見つからない: {source_path}"}, ensure_ascii=False))
        return 2

    try:
        region = read_region(source_path.read_text(encoding="utf-8"))
    except BlockError as exc:
        print(json.dumps({"error": str(exc), "source": str(source_path)}, ensure_ascii=False))
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

    result: dict[str, object] = {
        "status": status,
        "hash": digest,
        "target": str(target),
        "target_exists": exists,
    }

    if args.check:
        ask = ask_for(status, exists)
        if ask is None:
            result["action"] = "none"
            result["next"] = "転記済みで最新。ここで終了する"
        else:
            # 規範本文を返すのは、転記がそれを実行したセッションには効かないため。
            # CLAUDE.md は起動時に instruction として注入され、途中の書き換えは反映されない。
            # absent なら開始時にブロックが無く、stale なら古いブロックのまま走り切る。
            # 読むことに承認は要らない（書き込むことに要る）ので、ask の可否と無関係に返す。
            result["action"] = "propose"
            result["block_body"] = region
            result["ask"] = ask
            result["next"] = (
                "block_body が forge の規範の正本。セッション開始時に読んだ転記ブロックは失効している"
                "ので、以後は block_body に従う（承認の可否とは無関係に適用する）。"
                "そのうえで ask をそのまま一行で尋ね、承認されたら on_approve を実行する"
            )
            result["on_approve"] = build_command("--write", args.target, args.source, defaults)
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if status == "fresh":
        result["action"] = "none"
        print(json.dumps(result, ensure_ascii=False))
        return 0

    text = new_file_text(block) if not exists else splice(current, block)
    target.write_text(text, encoding="utf-8")
    result["action"] = "created" if not exists else ("updated" if status == "stale" else "appended")
    # 書き込み直後の一致確認は script 内で完結させる（AI に再実行させる手順を 1 つ減らす）。
    # verify を回すのは、フォーマッタがブロックを書き換えうる場合だけ
    result["written_status"] = evaluate(target.read_text(encoding="utf-8"), block)
    if result["written_status"] != "fresh":
        result["next"] = "書き込み直後に一致しなかった。報告して中止する"
    else:
        result["next"] = (
            "書き込みは完了し、一致を確認済み。プロジェクトがフォーマッタを使っている場合は適用し、"
            "verify が fresh を返すことを確認する。使っていなければここで終了する"
        )
        result["verify"] = build_command("--check", args.target, args.source, defaults)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
