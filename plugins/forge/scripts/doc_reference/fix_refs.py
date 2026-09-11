#!/usr/bin/env python3
"""索引で移動先が決まる参照切れを、記録された位置で差し替えて書き戻す（REQ-023 FNC-013）。

**決定から書き戻しまでを本モジュールが完結させる**（DES-081 §2）。置換先は決定論的に決まり、
置換する位置も前処理が保存しているため、ここに人・AI の判断が入る余地は無い。置換先を文字列
として外へ渡し、呼び出し側に `Edit` で当てさせてはならない——参照先のパスは同一ファイル内で
別の参照の部分文字列になりうるため、文字列一致は一意でないキーによる探索であり、参照切れより
有害な誤接続を作る。

**置換先も完全一致で導く。探索しない**（DES-081 §3.3.1）。索引が完全一致で答えられる類型は
1 つだけである。

| 種別              | 索引が完全一致で答えるもの             | 決まるか            |
| ----------------- | -------------------------------------- | ------------------- |
| `moved_link`      | `names`（ファイル名 → 実在パス一覧）   | 候補 1 件なら決まる |
| `missing_anchor`  | 見出し集合（完全一致は既に外れている） | 決まらない          |
| `missing_section` | 現在の節番号（旧→新の対応は無い）      | 決まらない          |

`missing_anchor` と `missing_section` を決めないのは、**書かれたキーが索引に完全一致しなかった
という事実そのものが所見だから**である。索引に無いキーは「無い」で終端する。そこから別のキーを
探すのは推定であり、当たっても正しさの根拠を持たない。

**同名の衝突は対応範囲外である。** 同じ文書 ID が複数パスに現れた場合、`build_code_index()`
が索引の構築時点で `ambiguous` へ落とすため、ここへは届かない（DES-081 §3.3a）。
"""

from __future__ import annotations

import argparse
import json
import posixpath
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_refs  # noqa: E402

#: 移動先が索引で決まる唯一の種別
DETERMINABLE_KINDS = ("moved_link",)


def determine_moved_link(referrer: str, ref: str, candidates) -> str | None:
    """`moved_link` の新しい destination を返す。決まらなければ `None`。

    Args:
        referrer: 参照を書いているファイルのパス（プロジェクトルート基準）
        ref: 書かれた destination（アンカーを含みうる）
        candidates: `names` 索引が返した、同じ basename を持つ実在パスの一覧

    **候補が 1 件でなければ決めない。** 2 件以上あるとき、どれが正しいかは参照元の意図に
    依存し、決定論的に決まらない（NFR-001）。0 件は名前ごと実在しない状態（`broken_link`）
    であり、移動ではない。

    **位置指定は保存する。** アンカーは参照元が何を指したいかの表明であり、パスの修正で
    落としてよいものではない。
    """
    if len(candidates) != 1:
        return None
    target, sep, anchor = ref.partition("#")
    new_path = posixpath.relpath(candidates[0], posixpath.dirname(referrer))
    return new_path + sep + anchor


def determine_rewrite(finding: dict) -> dict | None:
    """所見 1 件に対する書き換えを返す。決まらなければ `None`。

    置換先を返すのは `moved_link` だけである。`missing_anchor` の `slugs` と
    `missing_section` の節番号は、**利用者へ候補を示すための材料**であって置換の根拠では
    ない（本モジュールの冒頭）。

    **置換するのは、原本のその範囲の文字列が `dest` と一致する所見だけである。** 一致は
    抽出側が `replaceable` として判定している。一致しない形（バックスラッシュエスケープを
    含む destination 等）を置換するには表記の付け直しが要り、何を正しい表記とするかは文書
    規約の問題であって本機構は判定しない（REQ-023 §3.2）。位置を持たない所見も同様に置換
    しない——範囲が決まらなければ文字列を探すことになり、探索は禁じられている。

    Returns:
        dict: `file` / `line` / `col_start` / `col_end` / `old` / `new`
    """
    if finding.get("kind") != "moved_link":
        return None
    old = finding.get("dest")
    col_start, col_end = finding.get("col_start"), finding.get("col_end")
    if old is None or col_start is None or col_end is None:
        return None
    if not finding.get("replaceable"):
        return None
    new = determine_moved_link(finding["file"], old, finding.get("candidates") or [])
    if new is None or new == old:
        return None
    return {
        "file": finding["file"],
        "line": finding["line"],
        "col_start": col_start,
        "col_end": col_end,
        "old": old,
        "new": new,
    }


def _find_overlap(items):
    """同一行で範囲が重なる 2 件を返す。重なりが無ければ `None`。"""
    by_line: dict = {}
    for rw in items:
        by_line.setdefault(rw["line"], []).append(rw)
    for line_items in by_line.values():
        ordered = sorted(line_items, key=lambda r: r["col_start"])
        for a, b in zip(ordered, ordered[1:]):
            if b["col_start"] < a["col_end"]:
                return a, b
    return None


def apply_rewrites(rewrites, *, project_root: str = ".") -> dict:
    """書き換えを原本へ適用する（DES-081 §4.3.2）。

    **位置の大きいものから順に当てる**（行の降順、同一行では桁の降順）。前から当てると、
    1 件目の差し替えで長さが変わった分だけ 2 件目以降の桁がずれ、参照の途中を切って別の
    文字列を作る。**位置を取り直して当て直さない**——取り直しは再走査であり、走査のたびに
    結果が変わりうる操作を書き込みの途中へ挟むことになる。

    書き戻しは**ファイル単位で 1 回**とする。1 件ごとに読み書きすると、同じファイルを複数回
    開くうちに外部から変更される余地が生まれる。

    Returns:
        dict: `applied`（適用した書き換え）/ `errors`（適用できなかったものと理由）
    """
    root = Path(project_root)
    by_file: dict = {}
    for rw in rewrites:
        by_file.setdefault(rw["file"], []).append(rw)

    applied: list = []
    errors: list = []
    for rel, items in sorted(by_file.items()):
        # **範囲が重なる書き換えは当てない。** これがテキスト編集の不変条件であり、
        # 順序（後ろから当てる）はそれを満たす手段にすぎない。重なったまま当てると、
        # 1 件目の差し替えが 2 件目の範囲を壊す。1 つの destination から 1 件の書き換えが
        # 出る限り重ならないが、検査していないことが穴である。
        overlap = _find_overlap(items)
        if overlap is not None:
            a, b = overlap
            errors.append({"file": rel, "line": a["line"],
                           "reason": f"書き換えの範囲が重なっています"
                                     f"（{a['line']}:{a['col_start']}-{a['col_end']} と "
                                     f"{b['line']}:{b['col_start']}-{b['col_end']}）"})
            continue
        target = root / rel
        try:
            # `newline=""` で読む。既定の universal newlines は読み込み時に CRLF を LF へ
            # 落とすため、書き戻しで**置換範囲と無関係な全行の行末が変わる**（実測で確認した）。
            # 置換は記録された範囲だけを差し替えるものであり、行末は範囲の外である。
            with target.open(encoding="utf-8", newline="") as fp:
                original = fp.read()
        except OSError as exc:
            errors.append({"file": rel, "reason": f"読めません: {exc}"})
            continue
        # 行の区切りをそのまま保つ（末尾改行の有無・CRLF・CR・混在を変えない）。
        # 行番号は `check_refs` 側（universal newlines + splitlines）と一致する
        # ——LF / CRLF / CR / 混在 / 末尾改行なしの 5 通りで確認済み。
        lines = original.splitlines(keepends=True)
        done: list = []
        failed = False
        for rw in sorted(items, key=lambda r: (r["line"], r["col_start"]), reverse=True):
            idx = rw["line"] - 1
            if idx < 0 or idx >= len(lines):
                errors.append({"file": rel, "line": rw["line"], "reason": "行が存在しません"})
                failed = True
                break
            line = lines[idx]
            s, e = rw["col_start"], rw["col_end"]
            if e > len(line) or line[s:e] != rw["old"]:
                # 記録された範囲に記録された文字列が無い。表記の判定は抽出側が済ませて
                # いるため（`replaceable`）、ここで外れるのは検査後にファイルが変わった
                # 場合だけである。位置を探し直さない（探索は禁じられている）。
                #
                # **この照合は文書の同一性の証明ではない。** 変更後に偶然同じ位置へ同じ
                # 文字列が来れば通る。検査と置換は `run()` が一続きに行うため実経路では
                # 窓が無く、版や内容 hash を持ち回る必要は生じていない。外から報告を渡す
                # 経路を作るなら、そのとき同一性を運ばせる。
                errors.append({"file": rel, "line": rw["line"],
                               "reason": f"記録された位置の内容が変わっています"
                                         f"（期待 {rw['old']!r}、実際 {line[s:e]!r}）"})
                failed = True
                break
            lines[idx] = line[:s] + rw["new"] + line[e:]
            done.append(rw)
        if failed or not done:
            continue
        try:
            # 読みと同じく `newline=""`。既定では行末の LF が環境の改行へ変換される
            with target.open("w", encoding="utf-8", newline="") as fp:
                fp.write("".join(lines))
        except OSError as exc:
            errors.append({"file": rel, "reason": f"書き戻せません: {exc}"})
            continue
        applied.extend(done)
    return {"applied": applied, "errors": errors}


def run(scan_dirs, index_dirs, *, scan_exclude=None, index_exclude=None,
        project_root: str | None = None, dry_run: bool = False) -> dict:
    """検査を行い、索引から導ける参照切れを置換する。

    **検査が失敗したら 1 バイトも書き換えない**（NFR-004）。
    """
    report = check_refs.run(scan_dirs, index_dirs, scan_exclude=scan_exclude,
                            index_exclude=index_exclude, project_root=project_root)
    if report.get("status") != "ok":
        return report

    rewrites: list = []
    remaining: list = []
    for finding in report["findings"]:
        rw = determine_rewrite(finding)
        if rw is None:
            remaining.append(finding)
            continue
        rewrites.append(rw)

    result = {"status": "ok", "indexed": report["indexed"], "scanned": report["scanned"],
              "determined": rewrites, "remaining": remaining,
              "out_of_scope_summary": report["out_of_scope_summary"]}
    if dry_run:
        result["applied"] = []
        result["errors"] = []
        return result
    outcome = apply_rewrites(rewrites, project_root=project_root or ".")
    result["applied"] = outcome["applied"]
    result["errors"] = outcome["errors"]
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fix_refs.py")
    parser.add_argument("--scan-dirs-json", required=True,
                        help="参照元として走査するディレクトリの JSON 配列（glob 可）")
    parser.add_argument("--index-dirs-json", required=True,
                        help="実在の判定に使う文書のディレクトリの JSON 配列（glob 可）")
    parser.add_argument("--scan-exclude-json", default="[]",
                        help="走査から除くパターンの JSON 配列")
    parser.add_argument("--index-exclude-json", default="[]",
                        help="索引から除くパターンの JSON 配列")
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="置換先を決めるだけで書き戻さない")
    return parser


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        scan_dirs = json.loads(args.scan_dirs_json)
        index_dirs = json.loads(args.index_dirs_json)
        scan_exclude = json.loads(args.scan_exclude_json)
        index_exclude = json.loads(args.index_exclude_json)
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "error", "message": f"JSON を解釈できません: {exc}"},
                         ensure_ascii=False))
        return 2
    result = run(scan_dirs, index_dirs, scan_exclude=scan_exclude,
                 index_exclude=index_exclude, project_root=args.project_root,
                 dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "ok" or result.get("errors"):
        return 2
    return 1 if result.get("remaining") else 0


if __name__ == "__main__":
    sys.exit(main())
