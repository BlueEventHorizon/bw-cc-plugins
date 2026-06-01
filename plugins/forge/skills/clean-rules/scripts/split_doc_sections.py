#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""project rules と forge docs を ## 見出しでセクション分割し JSON 出力する。

重複検出そのものは行わない。両者のセクションを構造化（file / heading / text /
line）して返し、対応関係の判定は SKILL.md の指示に従い Claude（LLM）が担当する。

Embedding や外部 API は使用しない（標準ライブラリのみ）。

Usage:
    python3 split_doc_sections.py \
        --project-rules docs/rules/a.md docs/rules/b.md \
        --forge-docs plugins/forge/docs/x.md plugins/forge/docs/y.md
"""

import argparse
import json
import re
import sys
from pathlib import Path

# コードフェンス（``` または ~~~）の開始・終了行を検出する
_CODE_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")


# ---------------------------------------------------------------------------
# セクション分割
# ---------------------------------------------------------------------------

def split_sections(content, filepath=""):
    """Markdown ファイルを ## 見出しでセクション分割する。

    ## より上位の見出し（#）はファイルタイトルとして扱い、
    最初のセクションの先頭に含める。
    コードフェンス（``` / ~~~）内の ## は見出しとして扱わない。

    Args:
        content: ファイル内容（文字列）
        filepath: ログ用のファイルパス

    Returns:
        list[dict]: [{"heading": "## 見出し", "text": "本文", "line": 行番号}, ...]
        セクションが見つからない場合はファイル全体を1セクションとして返す。
    """
    lines = content.split("\n")
    sections = []
    current_heading = None
    current_lines = []
    current_line_num = 1
    in_code_fence = False

    for i, line in enumerate(lines, start=1):
        if _CODE_FENCE_RE.match(line):
            in_code_fence = not in_code_fence

        if not in_code_fence and re.match(r"^##\s+", line):
            if current_heading is not None or current_lines:
                text = "\n".join(current_lines).strip()
                if text:
                    heading = current_heading or f"(file header: {filepath})"
                    sections.append({
                        "heading": heading,
                        "text": text,
                        "line": current_line_num,
                    })
            current_heading = line.strip()
            current_lines = []
            current_line_num = i
        else:
            current_lines.append(line)

    if current_heading is not None or current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            heading = current_heading or f"(file header: {filepath})"
            sections.append({
                "heading": heading,
                "text": text,
                "line": current_line_num,
            })

    if not sections and content.strip():
        sections.append({
            "heading": f"(entire file: {filepath})",
            "text": content.strip(),
            "line": 1,
        })

    return sections


# ---------------------------------------------------------------------------
# ファイル読み込み + セクション収集
# ---------------------------------------------------------------------------

def collect_sections(file_paths, label=""):
    """複数ファイルからセクションを収集する。

    Args:
        file_paths: ファイルパスのリスト
        label: ログ用ラベル（"project" / "forge" 等）

    Returns:
        tuple[list[dict], list[dict]]:
            - sections: [{"file": path, "heading": ..., "text": ..., "line": ...}, ...]
            - warnings: [{"file": path, "error": str}, ...]  読み込み失敗したファイル
    """
    all_sections = []
    warnings = []
    for fpath in file_paths:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError) as e:
            _log(f"  Warning [{label}]: {fpath} を読み込めません: {e}")
            warnings.append({"file": str(fpath), "error": str(e)})
            continue

        sections = split_sections(content, filepath=fpath)
        for sec in sections:
            all_sections.append({
                "file": str(fpath),
                "heading": sec["heading"],
                "text": sec["text"],
                "line": sec["line"],
            })

    return all_sections, warnings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _log(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    print(*args, **kwargs)


def parse_args():
    parser = argparse.ArgumentParser(
        description="forge docs とプロジェクト rules を ## 見出しでセクション分割して JSON 出力する"
    )
    parser.add_argument(
        "--project-rules",
        nargs="+",
        required=True,
        help="プロジェクト rules のファイルパス",
    )
    parser.add_argument(
        "--forge-docs",
        nargs="+",
        required=True,
        help="forge docs のファイルパス",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    _log("セクション分割...")
    project_sections, project_warnings = collect_sections(args.project_rules, label="project")
    forge_sections, forge_warnings = collect_sections(args.forge_docs, label="forge")
    all_warnings = project_warnings + forge_warnings

    _log(f"  プロジェクト: {len(project_sections)} セクション")
    _log(f"  forge:       {len(forge_sections)} セクション")

    print(json.dumps({
        "status": "ok",
        "project_section_count": len(project_sections),
        "forge_section_count": len(forge_sections),
        "project_sections": project_sections,
        "forge_sections": forge_sections,
        "warnings": all_warnings,
    }, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
