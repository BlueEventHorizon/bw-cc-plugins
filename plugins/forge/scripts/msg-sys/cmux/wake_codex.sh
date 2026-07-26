#!/bin/bash
# review: 常駐 Codex セッションの push 型起床（DES-045 §3.8、cmux 環境限定）。
# 呼び出し元（review/talk-to-codex SKILL.md）にとって本スクリプトの呼び出し自体は
# MANDATORY。人間が対話しない専用の常駐 Codex セッションでは、本スクリプトを呼ばない限り
# Codex のターンが自然に終わる契機自体が存在しない。
#
# 常駐 Codex の Stop hook（check_inbox.py）は Codex 自身のターン終了時にしか発火しない
# （pull 型）。send.py でメッセージを DB に書き込むだけでは Codex 側に何のイベントも
# 発生しないため、Codex がたまたま別の理由でターンを終えるまで配信されない
# （実測で約7時間かかった事例あり。専用常駐セッションでは再現性のない僥倖に過ぎない）。
#
# 対象プロジェクトが cmux 上で動いており、その cwd で稼働している常駐 Codex セッション
# の pane が一意に見つかった場合のみ、そのペインへ短い指示を送り込んでターンを起こし、
# Stop hook を即座に発火させる。
#
# 対象ペインの発見は毎回その場で行い、結果をファイルにキャッシュしない
# （設定ファイル方式は以前存在したが、cmux がプロジェクトと同じ pane を維持したまま
# workspace ID だけを再発行することがあり、キャッシュされた workspace ID が stale化
# して push 起床が恒久的に機能しなくなる事故が実際に起きた。発見自体のコストは
# 数回の cmux subprocess 呼び出しで軽く、依頼往復ごとに高々1回しか呼ばれないため、
# 毎回発見し直す方が単純かつ頑健である。ユーザー指摘）。
#
# cmux が無い環境・対象ペインが見つからない環境では何もせず終了する（既存の
# wait_for_reply.py によるパッシブなポーリング待機のみで進む。これは
# フォールバックではなく、push 起床が最初から「無い」環境として振る舞う
# だけである。呼び出し元はこの結果を確定情報として扱い、待機予算内に
# 完了しなかった場合は Step 7 の確定タイムアウト報告に進む）。
#
# 使い方:
#   wake_codex.sh <project_root>
#
# 標準出力（単一 JSON）: {"status": "sent"|"skipped"|"failed", "reason": "..."}
# 終了コードは常に 0（push 起床の成否は依頼モードの完了判定に影響しない。
# あくまで wait_for_reply.py の待機時間を短縮する最適化でしかないため）。

set -uo pipefail

PROJECT_ROOT="${1:?usage: wake_codex.sh <project_root>}"
WAKE_TEXT="（自動チェック）msg-sys の inbox に新着メッセージがあれば確認してください。無ければ何もしないでください。"

_result() {
  # $1=status $2=reason
  # $1/$2 を Python コード文字列へ直接埋め込まず argv 経由で渡す（reason にシングル
  # クォートが含まれる場合の構文エラーを避けるため。Codex レビューで発見）。
  python3 -c "
import json, sys
print(json.dumps({'status': sys.argv[1], 'reason': sys.argv[2]}, ensure_ascii=False))
" "$1" "$2"
}

# `cmux read-screen` はプレーンテキストのみを返し、入力欄と履歴上のテキストを構造的に
# 区別する手段がない。`›` で始まる行が複数見つかった場合、末尾の1行だけを機械的に採用
# すると、履歴上の引用文やアシスタント出力（markdown の引用等、たまたま `›` で始まる
# 行を含みうる）を入力欄と取り違える恐れがある（実 Codex レビューで発見）。候補が
# ちょうど1件の場合のみ「その行が入力欄である」と確認できたとみなし、0件・複数件は
# 確認不能として扱う（呼び出し元が skipped にする）。
_find_unique_prompt_content() {
  screen_text="$1"
  matches="$(echo "$screen_text" | grep -E '^[[:space:]]*›')"
  if [ -z "$matches" ]; then
    return 1
  fi
  match_count="$(echo "$matches" | wc -l | tr -d '[:space:]')"
  if [ "$match_count" -ne 1 ]; then
    return 1
  fi
  echo "$matches" | sed -E 's/^[[:space:]]*›[[:space:]]?//; s/^[[:space:]]+//; s/[[:space:]]+$//'
  return 0
}

if ! command -v cmux &>/dev/null; then
  _result "skipped" "cmux コマンドが見つかりません"
  exit 0
fi

# 対象ペインの発見（毎回その場で行う。ファイルへのキャッシュはしない）: `find_codex_pane.py`
# （read-only、副作用なし）に委譲する。DES-048（未実装）の Step 1.6・`check_codex_liveness.py`
# も同じ発見ロジックを再利用できるよう、独立スクリプトに切り出してある（実 Codex レビューで
# 発見: 発見ロジックを本スクリプトの inline Python に閉じ込めると、他の呼び出し元が「同型だが
# 別実装」を重複して持つことになり、修正の反映漏れ・liveness 判定と push 起床対象のずれを
# 招く）。候補が0件・複数件の場合はいずれも安全側に倒し、注入せず見送る（複数件の場合、
# 以前は人間に確認を求めて .codex/cmux_target.json へ書き込む設計だったが、キャッシュを
# 廃止した今はその場で決め打ちできないため、best-effort の見送りとして扱う）。
discover_result="$(python3 "$(dirname "${BASH_SOURCE[0]}")/find_codex_pane.py" "$PROJECT_ROOT")"
discover_status=$?
if [ "$discover_status" -ne 0 ]; then
  discover_kind="$(echo "$discover_result" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)"
  discover_reason="$(echo "$discover_result" | python3 -c "import json,sys; print(json.load(sys.stdin).get('reason',''))" 2>/dev/null)"
  case "$discover_kind" in
    not_found|ambiguous)
      _result "skipped" "対象ペインを発見できませんでした: ${discover_reason}"
      ;;
    error)
      # workspace/list-panels の失敗は「対象が無い」ことを意味しない。ここを skipped に
      # 畳み込むと、送信されなかった起床通知が単なる安全上の見送りとして隠れてしまう。
      _result "failed" "対象ペインの探索に失敗しました: ${discover_reason}"
      ;;
    *)
      _result "failed" "対象ペイン探索の結果を解析できませんでした"
      ;;
  esac
  exit 0
fi
workspace="$(echo "$discover_result" | python3 -c "import json,sys; print(json.load(sys.stdin)['workspace'])")"
surface="$(echo "$discover_result" | python3 -c "import json,sys; print(json.load(sys.stdin)['surface'])")"

if ! screen="$(cmux read-screen --workspace "$workspace" --surface "$surface" --lines 8 2>/dev/null)"; then
  # read-screen の非ゼロ終了は、対象 pane が無いことを確認できた状態ではない。探索時の
  # workspace/list-panels 失敗と同様に、push 起床が実行できなかった障害として可視化する。
  _result "failed" "対象ペインの状態取得に失敗しました（read-screen が非ゼロ終了しました）"
  exit 0
fi
if [ -z "$screen" ]; then
  # 対象ペインが既に閉じている・cmux が状態を返せない等。設定が stale な場合を含め、
  # 安全側に倒してテキスト注入は行わない（Codex レビューで発見: 検証なしの注入は
  # 別タスクへの誤投入・未送信入力の破壊のリスクがある）。
  _result "skipped" "対象ペインの状態を確認できません（read-screen が空を返しました）"
  exit 0
fi

if echo "$screen" | grep -q "esc to interrupt"; then
  # 対象ペインが作業中（Codex 自身が別のターンを実行中）。ここでテキストを注入すると
  # 進行中の作業に割り込むおそれがあるため見送る。
  _result "skipped" "対象ペインが作業中のため見送りました"
  exit 0
fi

# 送信前に入力欄の内容（空か否か・既知プレースホルダーか否か）は確認しない
# [設計方針・ユーザー指摘]: 以前は「入力欄が既知のプレースホルダーと完全一致する
# ときだけ空扱いし、それ以外の内容が残っていれば下書き破壊を避けて見送る」実装
# だったが、実機で常駐 Codex ペインを確認したところ、履歴の巻き戻り（上下キー）等に
# よる残留テキストが入力欄に残っているのが定常状態であり、これは「見送るべき疑わしい
# 下書き」ではなく無害な残骸である。この誤区別により、この安全ゲートは実運用で
# ほぼ常に成立し、push 起床が恒久的に機能しなくなっていた（ユーザー指摘・実機確認済み）。
# `cmux send` は入力欄を上書きする（追記ではない）ため、busy でないと確認できた
# 時点でそのまま送信してよい（busy チェックのみが Codex 自身のターン状態を反映する
# 唯一の確定情報であり、入力欄の残留テキストの意味を screen-scraping で正しく解釈する
# 手段は無いと判断した）。

# ここまでの安全ゲート（cmux 有無・発見・作業中）を全て通過している。
# この状態での cmux send/send-key の失敗は、安全上の意図的な見送り（skipped）とは異なり、
# 送信して問題ない状況が整っているのに機械的な理由（cmux デーモンの一時的な不調等）で
# 失敗しているだけの可能性が高い。ユーザー指摘により、この場合のみ短い間隔で数回
# リトライする。
WAKE_SEND_MAX_ATTEMPTS=3
# cmux デーモンの一時的な不調（再起動中等）からの回復を待つ間隔。1秒では短すぎて
# 回復前に全リトライを使い切る恐れがあるため 10 秒とする（ユーザー指摘）。テストで
# 本番同様の待ち時間を強いられないよう環境変数で上書き可能にする。
WAKE_SEND_RETRY_INTERVAL_SECONDS="${WAKE_SEND_RETRY_INTERVAL_SECONDS:-10}"
attempt=1
# `cmux send` が成功済み（入力欄に自分の WAKE_TEXT が入っている）かどうかを追跡する。
# send がまだ成功していない間は、入力欄に何も書き込んでいないとみなせるため、安全ゲートの
# 再チェックなしでそのままリトライしてよい（元の設計を維持。実害のある変化が起きうるのは
# 「自分が何かを書き込んだ後」の区間のみ）。
send_confirmed_in_field=0
while [ "$attempt" -le "$WAKE_SEND_MAX_ATTEMPTS" ]; do
  if [ "$send_confirmed_in_field" -eq 0 ]; then
    if ! cmux send --workspace "$workspace" --surface "$surface" "$WAKE_TEXT" &>/dev/null; then
      attempt=$((attempt + 1))
      [ "$attempt" -le "$WAKE_SEND_MAX_ATTEMPTS" ] && sleep "$WAKE_SEND_RETRY_INTERVAL_SECONDS"
      continue
    fi
    send_confirmed_in_field=1
  fi
  if cmux send-key --workspace "$workspace" --surface "$surface" "enter" &>/dev/null; then
    # cmux send はテキストを入力欄に入れるだけで、そのままでは Codex に送信されない
    # （Enter が押されるまで入力待ちの状態で止まる）。send-key で確定させて初めて
    # Codex 側のターンが始まる。
    _result "sent" ""
    exit 0
  fi
  # `cmux send` は成功したが `send-key` だけ失敗した場合（実 Codex レビューで発見）:
  # 次のリトライで無条件に `cmux send` を再実行すると、待機している間に利用者が入力欄へ
  # 書き込んだ内容を無条件に上書きしてしまう恐れがある（「空欄か」を再チェックすると、
  # 自分がさっき書き込んだ WAKE_TEXT 自体が「空でも既知プレースホルダーでもない」ため
  # 常に疑わしいと誤判定してしまいリトライ自体が機能しなくなる。ユーザー指摘）。そこで
  # 「空欄か」ではなく「自分が送った文字列のままか」だけを確認し、一致する場合のみ
  # send-key だけ再試行する（テキストは再送しない）。一致しない場合は誰か/何かが
  # 入力欄を変更したとみなし、それ以上の注入をやめる。
  attempt=$((attempt + 1))
  if [ "$attempt" -gt "$WAKE_SEND_MAX_ATTEMPTS" ]; then
    break
  fi
  sleep "$WAKE_SEND_RETRY_INTERVAL_SECONDS"
  retry_screen="$(cmux read-screen --workspace "$workspace" --surface "$surface" --lines 8 2>/dev/null)"
  retry_prompt_content="$(_find_unique_prompt_content "$retry_screen")"
  # prompt 行が一意に確認できない（見つからない・複数候補）場合も、自分が送った文字列
  # のままだと確認できなかった場合と同様に扱い、これ以上の注入をやめる（実 Codex
  # レビューで発見: 複数候補を tail -1 で機械的に選ぶと履歴上のテキストと混同しうる）。
  if [ $? -ne 0 ] || [ "$retry_prompt_content" != "$WAKE_TEXT" ]; then
    _result "skipped" "send-key 失敗後の再確認で入力欄の状態を確認できなかったため、これ以上の注入を見送りました"
    exit 0
  fi
done
_result "failed" "cmux send / send-key が ${WAKE_SEND_MAX_ATTEMPTS} 回とも失敗しました（安全ゲートは全て通過済み）"
exit 0
