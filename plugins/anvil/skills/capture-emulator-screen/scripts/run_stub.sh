#!/usr/bin/env bash
# run_stub.sh — FIFO stdin 付きで stub フレーバーを flutter run 起動する。
# これにより hot_reload.sh から `r`(ホットリロード)/`R`(ホットリスタート) を送れる。
#
#   使い方（バックグラウンド起動推奨）:
#     scripts/run_stub.sh        # 初回はフルビルド（数分）。Flutter run key commands が出れば準備完了
#   以降のコード反映:
#     scripts/hot_reload.sh      # = printf 'r' > FIFO（数秒で反映）
#
# 環境変数:
#   FLUTTER_FIFO     既定 /tmp/dp_flutter_in
#   APP_DIR          既定 apps/app
#   DEVICE           デバイス指定の最優先。明示されたらこれを使う
#   ANDROID_SERIAL   simulator-capture.md の選択フローが設定する値。DEVICE 未指定時に流用する
#                    （hot reload と adb キャプチャを同一デバイスに固定するため）
#   既定（DEVICE / ANDROID_SERIAL 共に未設定の場合）は emulator-5554
set -euo pipefail

FIFO="${FLUTTER_FIFO:-/tmp/dp_flutter_in}"
APP_DIR="${APP_DIR:-apps/app}"
DEVICE="${DEVICE:-${ANDROID_SERIAL:-emulator-5554}}"

# FIFO を作り直し、書き込み端を保持して EOF を防ぐ（これが無いと flutter の stdin が即閉じる）
rm -f "$FIFO"
mkfifo "$FIFO"
tail -f /dev/null > "$FIFO" &

cd "$APP_DIR"
exec flutter run -d "$DEVICE" \
  --dart-define-from-file=flavor/stub.json \
  --dart-define-from-file=flavor/stub.local.json \
  -t lib/main.dart < "$FIFO"
