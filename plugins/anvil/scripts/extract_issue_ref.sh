#!/bin/sh
# ブランチ名から issue 参照を抽出して stdout に出力する。
# worktree・detached HEAD 対応。
# 出力: issue 参照文字列（例: "456", "fix-login"）。該当なしは空文字。

BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null) || exit 0

# 最初の数字列を抽出
ISSUE_REF=$(echo "$BRANCH" | grep -oE '[0-9]+' | head -1)

if [ -z "$ISSUE_REF" ]; then
  # 数字なし → スラッシュで分割して第2セグメント（なければ第1セグメント）
  FIRST=$(echo "$BRANCH" | cut -d'/' -f1)
  SECOND=$(echo "$BRANCH" | cut -d'/' -f2)
  if [ "$FIRST" = "$SECOND" ]; then
    ISSUE_REF="$FIRST"
  else
    ISSUE_REF="$SECOND"
  fi
fi

printf '%s' "$ISSUE_REF"
