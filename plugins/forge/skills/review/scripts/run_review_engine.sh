#!/bin/bash
# Codex でレビューを実行し、結果を指定ファイルに書き出す。
# Codex が存在しない場合は終了コード 2 で終了（Claude フォールバック用）。
#
# Usage:
#   run_review_engine.sh <output_file> <project_dir> "<prompt>"
#
# Exit codes:
#   0: 成功（output_file にレビュー結果が書き出された）
#   1: Codex 実行エラー(または空出力でレビュー失敗扱い)
#   2: Codex が見つからない（Claude フォールバック必要）
#
# 実装上の設計判断:
#   codex exec -o は「最終メッセージ」で出力先を上書きする仕様のため、
#   reviewer が apply_patch で <output_file> に書き込んだ本文が、codex 終了時に
#   短い終了メッセージ(250〜480 byte 程度)で上書きされる事故が発生する。
#   これを避けるため、以下の 2 点を実施する:
#     1. -o の出力先を <output_file>.codex_lastmsg.txt に分離する
#     2. stdout を <output_file>.stdout にリダイレクトして会話全体を受け取り、
#        extract_codex_output.py で Markdown 本文を抽出して <output_file> に書く
#   加えて --full-auto を外し --sandbox read-only のみとすることで、reviewer が
#   誤って apply_patch でファイルを書き換える経路自体を塞ぐ(二重防御)。

set -euo pipefail

if [ "$#" -lt 3 ]; then
  echo "Usage: run_review_engine.sh <output_file> <project_dir> <prompt>" >&2
  exit 1
fi

OUTPUT_FILE="$1"
PROJECT_DIR="$2"
PROMPT="$3"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Codex の存在確認
if ! command -v codex &> /dev/null; then
  echo '{"status": "not_found", "engine": "codex"}' >&2
  exit 2
fi

# 中間ファイル(codex 出力用)
LASTMSG_FILE="${OUTPUT_FILE}.codex_lastmsg.txt"
STDOUT_FILE="${OUTPUT_FILE}.stdout"

# Codex 実行
# - --sandbox read-only のみ: reviewer は文書を Read して指摘を出すだけで
#   書き込み系 tool は不要。apply_patch による OUTPUT_FILE 上書き事故も防ぐ
# - -o は分離した中間ファイルに最終メッセージを書く
# - stdout をファイルにリダイレクトして会話全体を受け取る
# - stdin を /dev/null に閉じる: 非 TTY な stdin だと codex が追加入力を待って hang する
# set -e を一時的に外して rc を捕捉する(codex が非 0 でも後処理を続けるため)
rc=0
set +e
codex exec \
  --sandbox read-only \
  --cd "$PROJECT_DIR" \
  -o "$LASTMSG_FILE" \
  "$PROMPT" < /dev/null > "$STDOUT_FILE"
rc=$?
set -e

# codex の出力から Markdown 本文を抽出して OUTPUT_FILE に書く
# (codex が rc != 0 でも部分出力が得られていれば抽出を試みる)
python3 "${SCRIPT_DIR}/extract_codex_output.py" \
  --stdout "$STDOUT_FILE" \
  --lastmsg "$LASTMSG_FILE" \
  --output "$OUTPUT_FILE" || true

# 空出力は perspective 欠損扱い(ユーザー決定事項)
if [ ! -s "$OUTPUT_FILE" ]; then
  echo '{"status": "error", "error": "codex produced empty output"}' >&2
  rc=1
fi

# 中間ファイル掃除
rm -f "$LASTMSG_FILE" "$STDOUT_FILE"

if [ "$rc" -ne 0 ]; then
  exit "$rc"
fi

echo '{"status": "ok", "engine": "codex", "output": "'"$OUTPUT_FILE"'"}' >&2
exit 0
