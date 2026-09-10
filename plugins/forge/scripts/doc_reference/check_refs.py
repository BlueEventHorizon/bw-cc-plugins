#!/usr/bin/env python3
"""参照を索引と突き合わせ、参照切れを報告する（REQ-023 FNC-006・DES-081 §3.1）。

**層 2（その参照先を解決できるか）を担う**（DES-081 §1.3）。何が参照かの判別は
層 1（`ref_extract`）が済ませており、ここでは解決の可否だけを決める。

報告の種別は**対処が異なるもの**ごとに分ける（DES-081 §3.5・FNC-009・FNC-011）。

| 種別              | 状態                                                 | 対処                     |
| ----------------- | ---------------------------------------------------- | ------------------------ |
| `broken_link`     | パスとして解決せず、その名前を持つ文書も実在しない   | 参照の削除・差し替え     |
| `moved_link`      | パスとして解決しないが、その名前を持つ文書は実在する | 位置の修正（候補を添える） |
| `missing_anchor`  | 参照先の文書は実在するが、そのアンカーが実在しない   | アンカーの修正           |
| `missing_label`   | 参照リンクのラベルに定義行が無い                     | 定義行の追加             |
| `missing_doc`     | その文書 ID を持つ文書が実在しない                   | 参照の削除・差し替え     |
| `missing_section` | 文書は実在するが、その節番号が実在しない             | 節番号の修正             |
| `ambiguous`       | 参照が複数の文書に当たり一意に決まらない             | 参照の表記を長くする     |
| `undecidable`     | 解決規則を持たない、または索引が無く判定できない     | 人が確認する             |

**解決の対象外とした参照は所見ではない。** 件数と種別を所見とは別の欄
（`out_of_scope`）で報告する（FNC-012）。所見の配列へ混ぜると、対処すべきものと
対処不要のものが同じ列に並ぶ。

**分類のいずれにも当たらないものを黙って捨てない**（DES-081 §1.2）。捨てた参照は
誰にも見えないまま「検査を通った」に含まれる。

未実装:

- **除外類型**（CHANGELOG 等の履歴の記録・生成物・外部リポジトリの ID）。
  現状は呼び出し側が対象パスを絞ることで代替する（DES-081 §2）
- **CI での `undecidable` の扱い**（通過とするか失敗とするか）は未決
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "doc_structure"))

import ref_extract  # noqa: E402
import ref_index  # noqa: E402

# glob 展開と exclude 判定は既存の doc_structure 資産を使う（再実装しない）
from resolve_doc_structure import expand_globs, is_excluded  # noqa: E402

# 外部の資源を指す scheme（実在性の対象は文書集合であり、ネットワークを叩かない）
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
# 解決規則を持たない形（変数展開形・プレースホルダ）。DES-081 §3.3c
_PLACEHOLDER = ("${", "*", "?", "{", "}")


def _classify(dest: str):
    """destination を §1.2 の分類へ振り分ける。

    Returns:
        `("out_of_scope", 理由)` / `("undecidable", 理由)` /
        `("resolve", (パス部, アンカー部))`
    """
    if not dest:
        return "undecidable", "destination が空である"
    if _SCHEME.match(dest):
        return "out_of_scope", "external"
    if any(t in dest for t in _PLACEHOLDER):
        return "undecidable", "変数展開形・プレースホルダを含み、参照先が一意に決まらない"
    if dest.startswith("/"):
        return "undecidable", "絶対パスの起点が決まらない"
    target, _, anchor = dest.partition("#")
    return "resolve", (target, anchor)


def _anchor_state(target: str, own_text, caches: dict):
    """`(アンカー集合, 列挙範囲外の形があるか)` を返す。引けない場合は `None`。"""
    cache = caches.setdefault("headings", {})
    if target in cache:
        return cache[target]
    if own_text is not None:
        state = (ref_extract.heading_slugs(own_text),
                 ref_extract.has_unenumerated_heading_forms(own_text))
    else:
        state = caches["heading_lookup"](target)
    cache[target] = state
    return state


def _check_anchor(path, lineno, ref, anchor, target, own_text, caches, findings):
    """アンカーの実在を判定する。

    **アンカーが実在しないことと、見出しを列挙できていないことを分ける**
    （DES-081 §3.3c.1）。列挙範囲が未決である以上、参照先に範囲外の見出しの形が
    あれば不在を断定できない。
    """
    state = _anchor_state(target, own_text, caches)
    if state is None:
        findings.append({"kind": "undecidable", "file": path, "line": lineno, "ref": ref,
                         "reason": f"{target} は走査範囲外であり見出し索引を持たない"})
        return
    slugs, unenumerated = state
    if unquote(anchor).lower() in slugs:
        return
    if unenumerated:
        findings.append({"kind": "undecidable", "file": path, "line": lineno, "ref": ref,
                         "reason": f"{target} に列挙範囲外の見出しの形があり、アンカーの不在を断定できない"})
        return
    # 参照先の見出し集合を所見へ載せる。`moved_link` の `candidates` と同じ役割で、
    # 置換先を導く材料を報告の側に持たせる（FNC-011 / FNC-013）。報告を受けた側が
    # 参照先をもう一度読み直さずに済み、判定と同じ入力から置換先が導ける。
    findings.append({"kind": "missing_anchor", "file": path, "line": lineno, "ref": ref,
                     "target": target, "slugs": sorted(slugs),
                     "reason": f"{target} に #{anchor} は無い"})


def _check_dest(path, lineno, dest, ref, own_text, indexes, caches, findings, out_of_scope):
    """1 つの destination を分類し、解決できるものは解決する（DES-081 §1.2）。"""
    kind, info = _classify(dest)
    if kind == "out_of_scope":
        out_of_scope.append({"file": path, "line": lineno, "ref": dest, "reason": info})
        return
    if kind == "undecidable":
        findings.append({"kind": "undecidable", "file": path, "line": lineno,
                         "ref": ref, "reason": info})
        return
    target, anchor = info
    if not target:
        _check_anchor(path, lineno, ref, anchor, path, own_text, caches, findings)
        return
    resolved = _normpath(str(PurePosixPath(PurePosixPath(path).parent / unquote(target))))
    if resolved not in indexes["files"]:
        # パスが解決しなければアンカーは見に行かない（参照切れはパスの問題である）
        name = PurePosixPath(resolved).name
        candidates = indexes["names"].get(name)
        if candidates:
            findings.append({"kind": "moved_link", "file": path, "line": lineno, "ref": ref,
                             "candidates": candidates,
                             "reason": f"{resolved} は実在しないが、{name} は他の位置に実在する"})
        else:
            findings.append({"kind": "broken_link", "file": path, "line": lineno, "ref": ref,
                             "reason": f"{resolved} は実在しない"})
        return
    if anchor:
        _check_anchor(path, lineno, ref, anchor, resolved, None, caches, findings)


def check_file(path: str, text: str, indexes: dict, caches: dict,
               *, is_markdown: bool) -> dict:
    """1 ファイル分の所見と、対象外として扱った参照を返す。

    **リンク記法の抽出は Markdown にのみ適用する。** リンク記法は Markdown の構文で
    あり、実装コードへ適用すると添字アクセス（`d["a"]["b"]`）が参照リンクの使用に
    見える（実測で 387 件の誤検出を出した）。実装コード・テストが持つのは文書 ID の
    節参照であり、そちらは種別を問わず抽出する（REQ-023 FNC-005）。

    Args:
        indexes: `files`（パス集合）/ `names`（名前 → パス一覧）/ `codes` と
            `ambiguous`（`build_code_index` の返り値）
        caches: `sections`（節番号）/ `heading_lookup`（走査範囲内の文書の
            `(アンカー集合, 列挙範囲外の形があるか)` を返す。範囲外なら `None`）/
            `root`（節参照の突合でファイルを読む起点）

    Returns:
        dict: `findings`（所見）/ `out_of_scope`（対象外として扱った参照。FNC-012）
    """
    findings: list = []
    out_of_scope: list = []
    honor_fences = is_markdown
    res = (ref_extract.extract_links(text, honor_fences=honor_fences)
           if is_markdown else {"inline": [], "ref_defs": [], "ref_uses": [], "skipped": []})

    for lineno, kind, raw in res["skipped"]:
        findings.append({"kind": "undecidable", "file": path, "line": lineno,
                         "ref": raw, "reason": kind})

    for lineno, dest in res["inline"]:
        _check_dest(path, lineno, dest, dest, text, indexes, caches, findings, out_of_scope)

    labels = {label for _, label, _ in res["ref_defs"]}
    for lineno, label, dest in res["ref_defs"]:
        _check_dest(path, lineno, dest, f"[{label}]: {dest}", text,
                    indexes, caches, findings, out_of_scope)
    for lineno, label in res["ref_uses"]:
        if label not in labels:
            findings.append({"kind": "missing_label", "file": path, "line": lineno,
                             "ref": f"[{label}]", "reason": "同一文書に定義行が無い"})

    section_cache = caches["sections"]
    root = caches.get("root", ".")
    for lineno, code, section in ref_extract.find_spec_refs(text, honor_fences=honor_fences):
        if code in indexes["codes"]["ambiguous"]:
            findings.append({"kind": "ambiguous", "file": path, "line": lineno,
                             "ref": f"{code} §{section}", "reason": "同じ ID の文書が複数ある"})
            continue
        target = indexes["codes"]["codes"].get(code)
        if target is None:
            findings.append({"kind": "missing_doc", "file": path, "line": lineno,
                             "ref": f"{code} §{section}", "reason": f"{code} の文書が実在しない"})
            continue
        if target not in section_cache:
            # プロジェクトルート基準で読む（cwd に依存させない。NFR-004）
            try:
                body = (Path(root) / target).read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:
                findings.append({"kind": "undecidable", "file": path, "line": lineno,
                                 "ref": f"{code} §{section}",
                                 "reason": f"{target} を読めないため節を判定できない: {exc}"})
                continue
            section_cache[target] = ref_extract.heading_section_numbers(body)
        if section not in section_cache[target]:
            findings.append({"kind": "missing_section", "file": path, "line": lineno,
                             "ref": f"{code} §{section}",
                             "reason": f"{target} に §{section} は無い"})
    return {"findings": findings, "out_of_scope": out_of_scope}


def _normpath(path: str) -> str:
    parts: list = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts and parts[-1] != "..":
                parts.pop()
            else:
                parts.append(part)
            continue
        parts.append(part)
    return "/".join(parts)


def _select(paths, dirs, exclude, project_root):
    """`dirs`（glob 可）配下の追跡ファイルのうち、`exclude` に該当しないものを返す。

    glob 展開と exclude 判定は `doc_structure` の既存関数を使う（DES-081 §5）。
    """
    expanded = [d.rstrip("/") + "/" for d in expand_globs(dirs, project_root)] if dirs else []
    root_path = Path(project_root)
    selected = []
    for path in paths:
        if not any(path.startswith(d) for d in expanded):
            continue
        # is_excluded は Path を受け、project_root 基準の相対パスで判定する
        # （collect_md_files と同じ使い方）
        if exclude and is_excluded(root_path / path, root_path, exclude):
            continue
        selected.append(path)
    return selected


def run(scan_dirs, index_dirs, *, scan_exclude=None, index_exclude=None,
        project_root: str | None = None) -> dict:
    """参照元（`scan_dirs`）を走査し、索引（`index_dirs`）と突き合わせる。

    どこを対象とするかの決定は本機構の外にあり、受け取ったディレクトリ列の展開は
    本機構が行う（DES-081 §2）。ここで受けるのは
    ディレクトリの列と除外の列だけであり、`.doc_structure.yaml` の解決は
    呼び出し側（SKILL）が既存スクリプトへ委ねる。
    """
    root = project_root or "."
    try:
        paths = ref_index.tracked_files(project_root)
    except ref_index.IndexError_ as exc:
        return {"status": "error", "message": str(exc)}

    index_paths = _select(paths, index_dirs, index_exclude, root)
    if not index_paths:
        return {"status": "error",
                "message": "索引対象の文書が 0 件です（--index-dirs-json の指定を確認してください）"}
    scan_paths = _select(paths, scan_dirs, scan_exclude, root)
    if not scan_paths:
        return {"status": "error",
                "message": "走査対象が 0 件です（未 commit のファイルは対象になりません）"}

    indexes = {
        "files": ref_index.build_file_index(paths),
        "names": ref_index.build_name_index(paths),
        "codes": ref_index.build_code_index(index_paths),
    }
    scan_set = set(scan_paths)

    def heading_lookup(target: str):
        """走査範囲内の文書だけ見出しを引ける（DES-081 §3.3c）。"""
        if target not in scan_set:
            return None
        try:
            body = (Path(root) / target).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
        return (ref_extract.heading_slugs(body),
                ref_extract.has_unenumerated_heading_forms(body))

    caches = {"sections": {}, "heading_lookup": heading_lookup, "root": root}
    findings: list = []
    out_of_scope: list = []
    for path in scan_paths:
        try:
            text = (Path(root) / path).read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            return {"status": "error", "message": f"{path} を読めません: {exc}"}
        res = check_file(path, text, indexes, caches, is_markdown=path.endswith(".md"))
        findings.extend(res["findings"])
        out_of_scope.extend(res["out_of_scope"])
    summary: dict = {}
    for f in findings:
        summary[f["kind"]] = summary.get(f["kind"], 0) + 1
    # 対象外は所見と混ぜず、種別ごとの件数で報告する（FNC-012）
    out_of_scope_summary: dict = {}
    for o in out_of_scope:
        out_of_scope_summary[o["reason"]] = out_of_scope_summary.get(o["reason"], 0) + 1
    return {"status": "ok", "indexed": len(index_paths), "scanned": len(scan_paths),
            "summary": summary, "findings": findings,
            "out_of_scope_summary": out_of_scope_summary}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="check_refs.py")
    parser.add_argument("--scan-dirs-json", required=True,
                        help="参照元として走査するディレクトリの JSON 配列（glob 可）")
    parser.add_argument("--index-dirs-json", required=True,
                        help="索引へ入れる文書のディレクトリの JSON 配列（glob 可）")
    parser.add_argument("--scan-exclude-json", default="[]",
                        help="走査対象から除くパターンの JSON 配列")
    parser.add_argument("--index-exclude-json", default="[]",
                        help="索引から除くパターンの JSON 配列")
    parser.add_argument("--project-root", default=None)
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
                 index_exclude=index_exclude, project_root=args.project_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "ok":
        return 2
    return 1 if result.get("findings") else 0


if __name__ == "__main__":
    sys.exit(main())
