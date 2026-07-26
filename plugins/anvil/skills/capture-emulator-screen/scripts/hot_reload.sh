#!/usr/bin/env bash
# hot_reload.sh [r|R]   r=ホットリロード(既定) / R=ホットリスタート
# run_stub.sh で FIFO stdin 起動した flutter run へコマンドを送り、コード変更を反映する。
#
#   scripts/hot_reload.sh       # ホットリロード（build メソッド内の変更: 色/余白/行高/文字 等）
#   scripts/hot_reload.sh R     # ホットリスタート（状態/main/Provider 初期化の変更）
#
# 注意:
#   - アセット追加 / slang(l10n) 生成 / pubspec / ネイティブ変更は反映されない → run_stub.sh で再起動（フル再ビルド）。
#   - 送信後、reassemble 完了まで 3〜6 秒待ってからキャプチャすること。
#   - 反映の確証として、capture 後に「変更が出るはずの箇所」を必ず確認する（編集前ビルドで裏取りしない）。
set -euo pipefail

FIFO="${FLUTTER_FIFO:-/tmp/dp_flutter_in}"
CMD="${1:-r}"

[ -p "$FIFO" ] || { echo "ERROR: FIFO $FIFO がありません。run_stub.sh で起動してください" >&2; exit 1; }
printf '%s' "$CMD" > "$FIFO"
echo "sent '$CMD' to flutter run ($FIFO)。reassemble 完了まで数秒待ってから capture してください"
