#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""変更パスを「生成された検索インデックス（ToC）」とそれ以外へ分類する read-only CLI。

`/anvil:commit` の Phase 3 が、ToC の差分を一括ステージ（`git add -u`）に巻き込まないために使う。
ToC は git 管理下の生成物であり、保護ブランチ以外で commit すると並行作業の再生成結果と衝突して
merge 時に破棄される。含めるかどうかは利用者が commit 確認の場で決める。

## なぜ script にするか

パスの分類は決定論的な処理である。SKILL.md 側で AI にパターン照合させると、`git status --porcelain`
の quote 表記（空白・非 ASCII を含むパス）や rename の `->` 表記で取り違える。
`git status --porcelain -z` を使い、NUL 区切りで確実に分解する。

## 分類の基準

生成インデックスの所在は `.claude/.doc-advisor/toc/` である。この 1 定数だけを判定に使う。

**この定数が anvil にあることについて**: ToC を生成するのは doc-advisor（外部プラグイン）であり、
その配置を anvil が知るのは本来の責務分担ではない。しかし「commit 対象に含めるか」を決められるのは
commit の場だけであり、他に置き場がない。所在が変わったときは本定数の更新が必要になる。

## 出力

終了コードは常に 0（分類は判定であり異常ではない）。標準出力に単一 JSON。

```json
{
  "branch": "feature/x",
  "toc_paths": [".claude/.doc-advisor/toc/rules-abc/toc.yaml"],
  "other_paths": ["docs/rules/foo.md"],
  "untracked_paths": ["docs/new.md"],
  "stale_staged_paths": ["README.md"]
}
```

`toc_paths` / `other_paths` は**追跡済みの変更**（ステージ済み・未ステージの両方）を対象とする。
未追跡は `untracked_paths` へ分け、`git add -u` の対象外であることを呼び出し側が区別できるようにする。

`stale_staged_paths` は **index に載っている内容が作業ツリーと食い違うパス**（porcelain の 2 列が
ともに非空白。例 `MM`）である。この状態で「ステージ済みがあるからそのまま commit する」と、
**作業ツリーの最新ではなく古い内容が commit される**。差分は commit した後にしか現れないため、
気付くのは常に手遅れになる。呼び出し側はステージし直すかどうかを利用者に確認する。

## 依存

Python 標準ライブラリのみ。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

#: 生成された検索インデックスの所在（project root 相対）
TOC_PATH_PREFIX = ".claude/.doc-advisor/toc/"


def _run(args: list[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} が失敗しました: {proc.stderr.strip()}")
    return proc.stdout


def current_branch() -> str:
    """現在のブランチ名を返す。detached HEAD では空文字列。"""
    try:
        return _run(["git", "branch", "--show-current"]).strip()
    except RuntimeError:
        return ""


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


def classify(stdout: str) -> dict:
    """porcelain 出力を ToC / その他 / 未追跡へ分類し、古いステージも検出する。"""
    toc_paths, other_paths, untracked_paths, stale_staged_paths = [], [], [], []
    for status, path in _iter_porcelain_entries(stdout):
        if status == "??":
            untracked_paths.append(path)
        elif path.startswith(TOC_PATH_PREFIX):
            toc_paths.append(path)
        else:
            other_paths.append(path)
        if _is_stale_staged(status):
            stale_staged_paths.append(path)
    return {
        "toc_paths": sorted(toc_paths),
        "other_paths": sorted(other_paths),
        "untracked_paths": sorted(untracked_paths),
        "stale_staged_paths": sorted(stale_staged_paths),
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "変更パスを生成インデックス（ToC）とそれ以外へ分類し JSON で出力する（read-only）"
        )
    )
    parser.parse_args(argv)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parse_args(argv)
    result = classify(_run(["git", "status", "--porcelain", "-z"]))
    result["branch"] = current_branch()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
