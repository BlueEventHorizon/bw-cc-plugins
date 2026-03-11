#!/bin/sh
# フックの存在確認。worktree 対応（.git がファイルでも正しく解決する）
# Usage: check_hook.sh <hook-name>
# Exit: 0 = hook exists and executable, 1 = not found
HOOK_PATH=$(git rev-parse --git-path "hooks/${1}")
[ -x "$HOOK_PATH" ]
