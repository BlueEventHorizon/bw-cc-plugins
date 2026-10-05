#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""差分 feature の一時マーカー（frontmatter の `feature_type: temporary-feature`）の有無を判定する。

文書先頭の YAML frontmatter（`---` で囲まれたブロック）から `feature_type` の値を取り出し、
`temporary-feature` を持つ文書を「並行状態にある」と判定する。判定の契約は DES-074
「build_task_context.py の並行状態文書の分類契約」が定める。複数の SKILL
（start-implement / start-design）が再利用する汎用ロジックのため、共有低レベル script に置く。

標準ライブラリのみで実装する（PyYAML 禁止）。

使用例:
    python3 feature_marker.py --paths docs/specs/forge/requirements/REQ-001_x.md
    python3 feature_marker.py --dirs docs/specs/forge/

## 終了コード

| code | 意味                                                                 |
| ---- | -------------------------------------------------------------------- |
| 0    | すべての文書について判定できた（マーカーの有無は JSON の結果で示す） |
| 1    | 判定できない文書があった（理由は JSON の `errors`）                  |
| 2    | 引数を受理できない（`argparse`）                                     |
"""

import argparse
import json
import re
import sys
from pathlib import Path

_FRONTMATTER_DELIMITER = "---"
# インデントの無いトップレベルキーだけを拾う（`feature_note` 配下の行は拾わない）。
# キーの順序で結果が変わらないよう、frontmatter ブロック全体を走査してから判定する。
_FEATURE_TYPE_RE = re.compile(r"^feature_type:(.*)$")
PARALLEL_FEATURE_TYPE = "temporary-feature"


def classify_feature_marker(path):
    """`(並行状態にあるか, 解析失敗の理由)` を返す。理由が None でなければ判定不能。"""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"{path}: 並行状態を判定できません（読み取りに失敗: {exc.strerror or exc}）"
    except UnicodeDecodeError:
        return None, f"{path}: 並行状態を判定できません（UTF-8 として読めません）"

    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
        return False, None

    values = []
    closed = False
    for line in lines[1:]:
        if line.strip() == _FRONTMATTER_DELIMITER:
            closed = True
            break
        match = _FEATURE_TYPE_RE.match(line)
        if match:
            values.append(match.group(1).strip())

    if not closed:
        return None, f"{path}: 並行状態を判定できません（frontmatter の終端 '---' がありません）"
    if not values:
        return False, None
    if len(values) > 1:
        return None, (
            f"{path}: 並行状態を判定できません"
            f"（feature_type が {len(values)} 回現れ、値を一意に決められません）"
        )
    if values[0] != PARALLEL_FEATURE_TYPE:
        return None, (
            f"{path}: 並行状態を判定できません"
            f"（feature_type の値 {values[0]!r} は未定義です。"
            f"定義されている値は {PARALLEL_FEATURE_TYPE!r} のみ）"
        )
    return True, None


def classify_paths(paths):
    """複数の文書を判定する。`(結果の配列, エラーの配列)` を返す。"""
    results = []
    errors = []
    for path in paths:
        has_marker, error = classify_feature_marker(path)
        if error is not None:
            errors.append(error)
        else:
            results.append({"path": path, "has_marker": has_marker})
    return results, errors


def collect_markdown(dirs):
    """ディレクトリ配下の `*.md` を、パスの昇順で集める。ディレクトリが無ければ、その理由も返す。"""
    paths = []
    errors = []
    for directory in dirs:
        base = Path(directory)
        if not base.is_dir():
            errors.append(f"{directory}: ディレクトリが存在しません")
            continue
        paths.extend(str(p) for p in sorted(base.rglob("*.md")))
    return paths, errors


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="文書が差分 feature の一時マーカーを持つかを判定して JSON で出力する"
    )
    parser.add_argument("--paths", nargs="+", help="判定する文書のパス")
    parser.add_argument(
        "--dirs", nargs="+",
        help="配下の *.md をすべて判定するディレクトリ（マーカーを持つ文書のパスを返す）",
    )
    args = parser.parse_args(argv)
    if not args.paths and not args.dirs:
        parser.error("--paths か --dirs のいずれかが必要")
    return args


def main(argv=None):
    args = parse_args(argv)
    paths = list(args.paths or [])
    errors = []
    if args.dirs:
        found, dir_errors = collect_markdown(args.dirs)
        paths.extend(found)
        errors.extend(dir_errors)
    results, classify_errors = classify_paths(paths)
    errors.extend(classify_errors)
    marker_paths = [r["path"] for r in results if r["has_marker"]]
    output = {
        "status": "error" if errors else "ok",
        "any_marker": bool(marker_paths),
        "marker_paths": marker_paths,
        "checked_count": len(results),
    }
    if args.paths:
        output["results"] = [r for r in results if r["path"] in set(args.paths)]
    if errors:
        output["errors"] = errors
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
