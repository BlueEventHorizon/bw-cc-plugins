#!/usr/bin/env bash
# capture.sh <screen_name> [out_dir] [platform]
# 接続中のデバイスから画面をキャプチャする。
#   例: ./capture.sh product_detail_jb_cyi
#   既定 out_dir: .figma_tmp/captures   既定 platform: android
# 出力: <out_dir>/<screen_name>.png（パスを標準出力に1行で返す）
set -euo pipefail

SCREEN="${1:?usage: capture.sh <screen_name> [out_dir] [platform]}"
OUT_DIR="${2:-.figma_tmp/captures}"
PLATFORM="${3:-android}"

mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/${SCREEN}.png"

case "$PLATFORM" in
  android)
    SERIAL="${ANDROID_SERIAL:-$(adb devices | awk 'NR>1 && $2=="device"{print $1; exit}')}"
    [ -n "$SERIAL" ] || { echo "ERROR: 接続中の Android デバイスがありません（adb devices）" >&2; exit 1; }
    # exec-out でバイナリをそのまま受け取る（CRLF 変換を避ける）
    adb -s "$SERIAL" exec-out screencap -p > "$OUT"
    ;;
  ios)
    # iOS は次フェーズ。simctl で実装予定。
    echo "ERROR: platform=ios は未実装（次フェーズ）" >&2
    exit 2
    ;;
  *)
    echo "ERROR: unknown platform: $PLATFORM" >&2
    exit 1
    ;;
esac

# 空ファイル/失敗の検知
[ -s "$OUT" ] || { echo "ERROR: キャプチャに失敗しました（$OUT が空）" >&2; exit 1; }
echo "$OUT"
