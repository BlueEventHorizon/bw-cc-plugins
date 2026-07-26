#!/usr/bin/env bash
# android-prepare.sh
# キャプチャ前の安定化：アニメーションを全オフ + stub アプリを前面起動。
#   例: ./android-prepare.sh
# 環境変数: APP_ID（既定 com.freaks.freaksstoreapp.dev）, ACTIVITY, ANDROID_SERIAL
set -euo pipefail

SERIAL="${ANDROID_SERIAL:-$(adb devices | awk 'NR>1 && $2=="device"{print $1; exit}')}"
[ -n "$SERIAL" ] || { echo "ERROR: 接続中の Android デバイスがありません" >&2; exit 1; }

# stub フレーバーの applicationId（appIdAndroid=com.freaks.freaksstoreapp + appIdSuffix=.dev）
APP_ID="${APP_ID:-com.freaks.freaksstoreapp.dev}"
ACTIVITY="${ACTIVITY:-com.freaks.freaksstoreapp.MainActivity}"

adbx() { adb -s "$SERIAL" "$@"; }

# アニメーション全オフ（遷移中・中間状態の撮影を防ぐ）
for s in window_animation_scale transition_animation_scale animator_duration_scale; do
  adbx shell settings put global "$s" 0
done

# 起動（既に起動済みなら前面化）
adbx shell am start -n "$APP_ID/$ACTIVITY" >/dev/null

echo "prepared: serial=$SERIAL app=$APP_ID activity=$ACTIVITY (animations=0)"
