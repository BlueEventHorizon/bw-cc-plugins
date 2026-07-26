#!/bin/bash
# Claude 用 Stop フック: msg-sys mailbox の未読を確認し、あれば block して本文を差し戻す。
#
# 出力プロトコル（brew-lgtm-stop.sh の実例で確認済み）:
#   継続してよい: {"continue": true}
#   ターン終了を止めて指示を差し戻す: {"decision": "block", "reason": "<text>"}
#
# 処理対象メッセージの選定・reply_chain_length（往復回数）の算出は inbox.py --next
# （lib/mailbox.py の select_next_actionable、テスト可能な Python 関数）に一元化する。
# bash 側は chain_length と環境変数 FORGE_MSG_MAX_ROUND_TRIPS の単純な整数比較のみを行い、
# 判断ロジックを bash 側に漏らさない（DES-034 §4.2）。

set -euo pipefail

EXPERIMENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RECIPIENT="${FORGE_MSG_AGENT_NAME:-claude}"

# DB パスは冒頭で一度だけ構築し、以降の --next/--ack/--mark-notified 呼び出し
# すべてに渡す（DES-034 §7 のフック境界）。フック登録コマンド（.claude/settings.json）
# 側で git rev-parse --show-toplevel によりリポジトリルートを動的解決し
# FORGE_MSG_PROJECT_ROOT へ渡す（session cwd がプロジェクトルートと一致する
# 保証は無いため、cwd をそのまま採用しない）。未設定時（単体実行・テスト時等）
# のみ $(pwd) にフォールバックする。
FORGE_MSG_PROJECT_ROOT="${FORGE_MSG_PROJECT_ROOT:-$(pwd)}"
db_path="${FORGE_MSG_PROJECT_ROOT}/.claude/.temp/msg-sys/messages.db"
db_path_args=(--db-path "$db_path")

next_json="$(python3 "${EXPERIMENT_DIR}/inbox.py" "$RECIPIENT" --next "${db_path_args[@]+"${db_path_args[@]}"}")"

# 処理対象が無ければ null が返る
if [ "$next_json" = "null" ]; then
  printf '%s\n' '{"continue": true}'
  exit 0
fi

id="$(python3 -c "import json, sys; print(json.loads(sys.argv[1])['id'])" "$next_json")"
sender="$(python3 -c "import json, sys; print(json.loads(sys.argv[1])['sender'])" "$next_json")"
# body はコマンド置換の対象にすると Bash の仕様で末尾改行が無条件に除去される。
# 末尾に非改行のセンチネルを付与して取得し、除去対象をセンチネルにすり替える
# ことで body 本来の末尾改行（mailbox 保存本文との一致）を保持する。
body_sentinel="__FORGE_MSG_BODY_END_$$__"
body_raw="$(python3 -c "import json, sys; sys.stdout.write(json.loads(sys.argv[1])['body'] + sys.argv[2])" "$next_json" "$body_sentinel")"
body="${body_raw%"$body_sentinel"}"
chain_length="$(python3 -c "import json, sys; print(json.loads(sys.argv[1])['chain_length'])" "$next_json")"

# 上限値は FORGE_MSG_MAX_ROUND_TRIPS のみで判定する。未設定の場合は自動往復を
# 開始せず、無条件に上限到達扱い（人間通知）にフェイルセーフする（DES-034 §8）。
max_round_trips="${FORGE_MSG_MAX_ROUND_TRIPS:-}"

if [ -n "$max_round_trips" ] && [ "$chain_length" -lt "$max_round_trips" ]; then
  # 上限未到達: 先に ack（配信成功の確定点）。成功した場合にのみ block を出力する。
  if ! python3 "${EXPERIMENT_DIR}/inbox.py" "$RECIPIENT" --ack "$id" "${db_path_args[@]+"${db_path_args[@]}"}"; then
    # ack 失敗（DB ロック等）: 配信未成立のため continue にフォールバックし、
    # hook プロセス自体は必ず正常終了させる（set -euo pipefail の影響を受けない）。
    printf '%s\n' '{"continue": true}'
    exit 0
  fi

  reason="[id:${id}] [from ${sender}] ${body}"
  python3 -c "
import json
print(json.dumps({'decision': 'block', 'reason': __import__('sys').argv[1]}, ensure_ascii=False))
" "$reason"
  exit 0
fi

# 上限到達（または FORGE_MSG_MAX_ROUND_TRIPS 未設定）: 既読化せず人間へ通知する。
# 通知が成功した場合にのみ mark-notified で limit_notified_at を設定する
# （通知失敗時は設定せず、次回の hook 起動で再度通知を試みる）。
ack_hint="inbox.py ${RECIPIENT} --ack ${id} --db-path ${db_path}"

if python3 "${EXPERIMENT_DIR}/lib/notify.py" \
  --recipient "$RECIPIENT" \
  --message-id "$id" \
  --sender "$sender" \
  --body "$body" \
  --ack-hint "$ack_hint"; then
  python3 "${EXPERIMENT_DIR}/inbox.py" "$RECIPIENT" --mark-notified "$id" "${db_path_args[@]+"${db_path_args[@]}"}" || true
fi

printf '%s\n' '{"continue": true}'
