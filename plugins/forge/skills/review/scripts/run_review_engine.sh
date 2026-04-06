#!/bin/bash
# Codex でレビューを実行し、結果を指定ファイルに書き出す。
# Codex が存在しない場合は終了コード 2 で終了（Claude フォールバック用）。
#
# Usage:
#   run_review_engine.sh <output_file> <project_dir> "<prompt>"
#
# Exit codes:
#   0: 成功（output_file にレビュー結果が書き出された）
#   1: Codex 実行エラー
#   2: Codex が見つからない（Claude フォールバック必要）

set -euo pipefail

if [ "$#" -lt 3 ]; then
  echo "Usage: run_review_engine.sh <output_file> <project_dir> <prompt>" >&2
  exit 1
fi

OUTPUT_FILE="$1"
PROJECT_DIR="$2"
PROMPT="$3"

# Codex の存在確認
if ! command -v codex &> /dev/null; then
  echo '{"status": "not_found", "engine": "codex"}' >&2
  exit 2
fi

# Codex 実行（-o で最終メッセージのみファイルに書き出し）
codex exec \
  --full-auto \
  --sandbox read-only \
  --cd "$PROJECT_DIR" \
  -o "$OUTPUT_FILE" \
  "$PROMPT"

# 出力ファイルの存在確認
if [ ! -f "$OUTPUT_FILE" ]; then
  echo '{"status": "error", "error": "output file not created"}' >&2
  exit 1
fi

echo '{"status": "ok", "engine": "codex", "output": "'"$OUTPUT_FILE"'"}' >&2
exit 0
