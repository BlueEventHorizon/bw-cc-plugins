#!/usr/bin/env python3
"""参照を索引と突き合わせ、参照切れを報告する（REQ-023 FNC-006・DES-081 §3.1）。

報告の種別は対処が異なるものを分ける（FNC-009）。

| 種別              | 意味                                             | 対処                     |
| ----------------- | ------------------------------------------------ | ------------------------ |
| `broken_link`     | リンクの参照先ファイルが実在しない               | 参照の修正               |
| `missing_doc`     | 文書 ID に対応する文書が実在しない               | 参照の修正・除外の見直し |
| `missing_section` | 文書は実在するが、指した節が実在しない           | 参照の修正               |
| `missing_label`   | 参照リンクのラベルに定義行が無い                 | 定義行の追加             |
| `ambiguous`       | 参照が一意に決まらない                           | 参照の表記を長くする     |
| `out_of_scope`    | 抽出が対応していない形（判定していない）         | 人が確認する             |

`out_of_scope` を黙って落とさないことが NFR-001 の要求である。

未実装:

- **除外類型**（CHANGELOG 等の履歴の記録・生成物・外部リポジトリの ID）。
  現状は呼び出し側が対象パスを絞ることで代替する（DES-081 §2）
- **CI での `out_of_scope` の扱い**（通過とするか失敗とするか）は未決
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "doc_structure"))

import ref_extract  # noqa: E402
import ref_index  # noqa: E402

# glob 展開と exclude 判定は既存の doc_structure 資産を使う（再実装しない）
from resolve_doc_structure import expand_globs, is_excluded  # noqa: E402

# 参照先として突合しないもの（実在性の対象は文書集合であり、ネットワークを叩かない）
_NON_LOCAL = ("http://", "https://", "${", "#")
# プレースホルダを示すメタ文字（DES-081 §3.3c）
_META = "<>*{"


def _is_path_shaped(dest: str) -> bool:
    return "/" in dest or dest.endswith(".md")


def check_file(path: str, text: str, file_index: set, code_index: dict, section_cache: dict,
               *, is_markdown: bool) -> list:
    """1 ファイル分の所見を返す。

    **リンク記法の抽出は Markdown にのみ適用する。** リンク記法は Markdown の構文で
    あり、実装コードへ適用すると添字アクセス（`d["a"]["b"]`）が参照リンクの使用に
    見える（実測で 387 件の誤検出を出した）。実装コード・テストが持つのは文書 ID の
    節参照であり、そちらは種別を問わず抽出する（REQ-023 FNC-005）。
    """
    findings: list = []
    honor_fences = is_markdown
    res = (ref_extract.extract_links(text, honor_fences=honor_fences)
           if is_markdown else {"inline": [], "ref_defs": [], "ref_uses": [], "skipped": []})

    for lineno, kind, raw in res["skipped"]:
        findings.append({"kind": "out_of_scope", "file": path, "line": lineno,
                         "ref": raw, "reason": kind})

    for lineno, dest in res["inline"]:
        if not dest or dest.startswith(_NON_LOCAL):
            continue
        target = dest.split("#", 1)[0]
        if not target or any(c in target for c in _META) or not _is_path_shaped(target):
            continue
        resolved = str(PurePosixPath(PurePosixPath(path).parent / target))
        resolved = _normpath(resolved)
        if resolved not in file_index:
            findings.append({"kind": "broken_link", "file": path, "line": lineno,
                             "ref": dest, "reason": f"{resolved} は実在しない"})

    labels = {label for _, label, _ in res["ref_defs"]}
    for lineno, label, dest in res["ref_defs"]:
        if dest.startswith(_NON_LOCAL):
            continue
        resolved = _normpath(str(PurePosixPath(PurePosixPath(path).parent / dest.split("#", 1)[0])))
        if resolved not in file_index:
            findings.append({"kind": "broken_link", "file": path, "line": lineno,
                             "ref": f"[{label}]: {dest}", "reason": f"{resolved} は実在しない"})
    for lineno, label in res["ref_uses"]:
        if label not in labels:
            findings.append({"kind": "missing_label", "file": path, "line": lineno,
                             "ref": f"[{label}]", "reason": "同一文書に定義行が無い"})

    for lineno, code, section in ref_extract.find_spec_refs(text, honor_fences=honor_fences):
        if code in code_index["ambiguous"]:
            findings.append({"kind": "ambiguous", "file": path, "line": lineno,
                             "ref": f"{code} §{section}", "reason": "同じ ID の文書が複数ある"})
            continue
        target = code_index["codes"].get(code)
        if target is None:
            findings.append({"kind": "missing_doc", "file": path, "line": lineno,
                             "ref": f"{code} §{section}", "reason": f"{code} の文書が実在しない"})
            continue
        if target not in section_cache:
            section_cache[target] = ref_extract.heading_section_numbers(
                Path(target).read_text(encoding="utf-8", errors="ignore"))
        if section not in section_cache[target]:
            findings.append({"kind": "missing_section", "file": path, "line": lineno,
                             "ref": f"{code} §{section}",
                             "reason": f"{target} に §{section} は無い"})
    return findings


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

    走査対象・索引対象の決定は本機構の外にある（DES-081 §2）。ここで受けるのは
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

    file_index = ref_index.build_file_index(paths)
    code_index = ref_index.build_code_index(index_paths, r".*")
    section_cache: dict = {}
    findings: list = []
    for path in scan_paths:
        try:
            text = (Path(root) / path).read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            return {"status": "error", "message": f"{path} を読めません: {exc}"}
        findings.extend(check_file(path, text, file_index, code_index, section_cache,
                                   is_markdown=path.endswith(".md")))
    summary: dict = {}
    for f in findings:
        summary[f["kind"]] = summary.get(f["kind"], 0) + 1
    return {"status": "ok", "indexed": len(index_paths), "scanned": len(scan_paths),
            "summary": summary, "findings": findings}


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
