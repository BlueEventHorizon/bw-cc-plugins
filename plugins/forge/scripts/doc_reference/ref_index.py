#!/usr/bin/env python3
"""実在するものの索引を作る（REQ-023 FNC-003・DES-081 §3.2・§3.3）。

**索引が実在として数えるのは、検査時点で git の追跡下にあるファイルだけである。**
git 履歴・他ブランチ・削除済みファイル・未追跡ファイルはいずれも含めない。
履歴と他ブランチを除くのは FNC-003 の要求であり、未追跡を除くのは設計判断
（DES-081 §3.2。含めると手元では通り CI では落ちる検査になる）。

照合はこの索引に対して行い、ファイルシステムに対しては行わない
（DES-081 §3.3c。大文字小文字を区別しないファイルシステムで、表記が実体と
異なる参照を検出できる）。

**索引は永続化しない。** 検査のたびに、その時点の文書集合から構築する。保存した索引と
現在の文書集合がずれた状態は、本機構が検出しようとしている「記述と実体の乖離」と同じ形を
しており、検査機構自身がその欠陥を持つことになる。

パスを伴わない参照（文書 ID の表記）の解決は**完全一致**で行う（DES-081 §3.3a）。
名前の一部を符号として解決する機構は持たない——検査対象の 4 形（REQ-023 FNC-002）のうち
パスを伴わないのは文書 ID の表記だけであり、地の文の裸のファイル名は検査対象ではない。
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


def build_name_index(paths) -> dict:
    """ファイル名から実在するパスの一覧への対応を作る（DES-081 §3.3）。

    ファイル索引（パスの集合）とは別に持つ。「パスとして解決しなかった参照が、
    名前としては実在するか」を答えるためであり、FNC-011 が要求する 2 状態
    （名前の不在 / 配置の不一致）の区別にはこの向きが必要である。

    Returns:
        dict: ファイル名 → パスの一覧（昇順）。同名が複数あればすべて保持する
        （どれが正しいかは参照元の意図に依存し、決定論的に決まらない）
    """
    index: dict = {}
    for path in paths:
        index.setdefault(PurePosixPath(path).name, []).append(path)
    return {name: sorted(v) for name, v in index.items()}


def build_code_index(paths) -> dict:
    """文書 ID から実ファイルへの対応を作る。

    Args:
        paths: 索引へ入れる文書のパス一覧。**どれを文書集合とみなすかは呼び出し側が
            絞り込んで渡す**（DES-081 §2「検査対象パスの決定は本機構の外にある」）。
            ここで重ねて絞り込む引数は持たない——絞り込みの責務が 2 箇所に分かれる

    Returns:
        dict: 文書 ID → パス。同じ ID が複数のパスに現れた場合は
        `ambiguous` 側へ入れ、実在として扱わない（NFR-001: 一意に決まらない
        ものを決まったことにしない）
    """
    found: dict = {}
    ambiguous: dict = {}
    for path in paths:
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
