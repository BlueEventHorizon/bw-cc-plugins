#!/usr/bin/env python3
"""実在するものの索引を作る（REQ-023 FNC-003・DES-081 §3.2・§3.3）。

**索引が実在として数えるのは、検査時点で git の追跡下にあるファイルだけである。**
git 履歴・他ブランチ・削除済みファイル・未追跡ファイルはいずれも含めない。
履歴と他ブランチを除くのは FNC-003 の要求であり、未追跡を除くのは設計判断
（DES-081 §3.2。含めると手元では通り CI では落ちる検査になる）。

照合はこの索引に対して行い、ファイルシステムに対しては行わない
（DES-081 §3.3c。大文字小文字を区別しないファイルシステムで、表記が実体と
異なる参照を検出できる）。

**符号表は永続化しない**（DES-081 §3.3b）。検査のたびに構築する。

未実装:

- **語頭符号による解決**（DES-081 §3.3a）。現状は文書 ID の完全一致のみを持つ。
  文書名の一意な接頭辞による一致・trie による曖昧化の検出は未実装
"""

from __future__ import annotations

import re
import subprocess
from pathlib import PurePosixPath

# ファイル名の先頭にある文書 ID（`COMMON-DES-001` のような名前空間付きを含む）
_CODE = re.compile(r"((?:[A-Z]+-)*[A-Z]+-\d+)")


class IndexError_(Exception):
    """索引の構築に失敗した場合に送出する（REQ-023 NFR-004: 通過を返さない）。"""


def tracked_files(project_root: str | None = None) -> list:
    """追跡下のファイル一覧を返す。失敗時は既定値で補わず送出する（NFR-004）。"""
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    if completed.returncode != 0:
        raise IndexError_(f"git ls-files に失敗しました: {completed.stderr.strip()}")
    return [p for p in completed.stdout.split("\0") if p]


def build_file_index(paths) -> set:
    """パス集合を返す（相対パス参照の突合に使う）。"""
    return set(paths)


def build_code_index(paths, include_pattern: str) -> dict:
    """文書 ID から実ファイルへの対応を作る。

    Args:
        paths: 追跡下のパス一覧
        include_pattern: 索引へ入れる文書を選ぶ正規表現（呼び出し側が渡す。
            何を文書集合とみなすかは用途ごとに異なるため機構は決めない。
            DES-081 §2「検査対象パスの決定は本機構の外にある」）

    Returns:
        dict: 文書 ID → パス。同じ ID が複数のパスに現れた場合は
        `ambiguous` 側へ入れ、実在として扱わない（NFR-001: 一意に決まらない
        ものを決まったことにしない）
    """
    include = re.compile(include_pattern)
    found: dict = {}
    ambiguous: dict = {}
    for path in paths:
        if not include.search(path):
            continue
        m = _CODE.match(PurePosixPath(path).name)
        if not m:
            continue
        code = m.group(1)
        if code in found and found[code] != path:
            ambiguous.setdefault(code, {found[code]}).add(path)
            continue
        found[code] = path
    for code in ambiguous:
        found.pop(code, None)
    return {"codes": found, "ambiguous": {k: sorted(v) for k, v in ambiguous.items()}}
