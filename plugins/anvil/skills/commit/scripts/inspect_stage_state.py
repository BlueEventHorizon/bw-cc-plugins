#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""commit 前のステージ状態を検査する read-only CLI。

`/anvil:commit` の Phase 3 が、何をステージするかを利用者へ確認するために使う。

## なぜ script にするか

`git status --porcelain` の読み取りは決定論的な処理である。SKILL.md 側で AI に読ませると、
quote 表記（空白・非 ASCII を含むパス）や rename の `->` 表記で取り違える。
`git status --porcelain -z` を使い、NUL 区切りで確実に分解する。

とくに **index と作業ツリーの食い違い**（`MM` / `AM`）は 2 文字表記にしか現れず、
散文の手順で「ステージ済みがあるか」だけを見ると見落とす。見落とすと古い内容が commit され、
差分は commit した後にしか現れない。機械判定でなければ守れない。

## 出力

終了コードは常に 0（検査は判定であり異常ではない）。標準出力に単一 JSON。

```json
{
  "tracked_paths": ["docs/rules/foo.md"],
  "untracked_paths": ["docs/new.md"],
  "stale_staged_paths": ["README.md"]
}
```

ブランチ名は返さない。保護ブランチの判定は Phase 3.5 が独立に行うため、ここで返すと使われない値に
なる。

`tracked_paths` は**追跡済みの変更**（ステージ済み・未ステージの両方）である。未追跡は
`untracked_paths` へ分け、`git add -u` の対象外であることを呼び出し側が区別できるようにする。

`stale_staged_paths` は **index に載っている内容が作業ツリーと食い違うパス**（porcelain の 2 列が
ともに非空白。例 `MM`）である。この状態で「ステージ済みがあるからそのまま commit する」と、
**作業ツリーの最新ではなく古い内容が commit される**。`git add` し直せば解消する。

## 依存

Python 標準ライブラリのみ。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def _run(args: list[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} が失敗しました: {proc.stderr.strip()}")
    return proc.stdout


def _iter_porcelain_entries(stdout: str):
    """`git status --porcelain -z` の出力を (status, path) へ分解する。

    NUL 区切りで読む。rename / copy（`R` / `C`）は「元パス」が続く 1 エントリ分の
    追加フィールドを持つため、その分を読み飛ばして**新しいパス**を採用する。

    status は 2 列（`XY`。X = index、Y = 作業ツリー）である。**両列を検査する**——
    実測では porcelain v1 の rename 検出は index 側でのみ行われ（未ステージの rename は
    削除 + 未追跡として現れる）Y 列に `R` / `C` は出ないが、片方だけを見る実装は
    git の出力が変わったときに元パスをエントリと誤読してパスを壊す。両列を見ることの
    コストは無く、誤読は静かに起きるため広く取る。
    """
    fields = stdout.split("\0")
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if not entry:
            continue
        status, path = entry[:2], entry[3:]
        if "R" in status or "C" in status:
            # 次のフィールドが元パス。新しいパス（entry 側）を採用して読み飛ばす
            i += 1
        yield status, path


def _is_stale_staged(status: str) -> bool:
    """index の内容が作業ツリーと食い違うか（例 `MM` / `AM` / `RM`）。

    porcelain の 2 列は `XY`（X = index、Y = 作業ツリー）である。両方が非空白なら、
    ステージした後にさらに作業ツリーが変わっている。未追跡（`??`）と衝突（`U` を含む）は
    別の状態なので除く。
    """
    if status == "??" or "U" in status:
        return False
    index_col, worktree_col = status[0], status[1]
    return index_col != " " and worktree_col != " "


def inspect(stdout: str) -> dict:
    """porcelain 出力から、追跡済み・未追跡・古いステージを取り出す。"""
    tracked_paths, untracked_paths, stale_staged_paths = [], [], []
    for status, path in _iter_porcelain_entries(stdout):
        if status == "??":
            untracked_paths.append(path)
        else:
            tracked_paths.append(path)
        if _is_stale_staged(status):
            stale_staged_paths.append(path)
    return {
        "tracked_paths": sorted(tracked_paths),
        "untracked_paths": sorted(untracked_paths),
        "stale_staged_paths": sorted(stale_staged_paths),
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="commit 前のステージ状態を検査し JSON で出力する（read-only）"
    )
    parser.parse_args(argv)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parse_args(argv)
    result = inspect(_run(["git", "status", "--porcelain", "-z"]))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
