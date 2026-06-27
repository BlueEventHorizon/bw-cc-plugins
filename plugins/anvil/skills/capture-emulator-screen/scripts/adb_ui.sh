#!/usr/bin/env bash
# adb_ui.sh <command> [args...]
# Android 実機操作（座標ベース）。Flutter 画面の操作フローを辿るための薄いヘルパー。
#
#   dump                      UI 階層 XML を標準出力に（座標特定用）
#   find "<文字列>"           text/content-desc/resource-id 部分一致でタップ中心座標を列挙
#   tap X Y                   座標タップ
#   swipe X1 Y1 X2 Y2 [ms]    スワイプ（既定 300ms）
#   text "<文字列>"           フォーカス中の入力欄へ文字入力
#   key <keyevent>            キーイベント（例: 4=BACK, 66=ENTER）
#   launch | stop             stub アプリの起動 / 強制停止
#   wait [sec]                指定秒スリープ（既定 1）
#
# 環境変数: APP_ID（既定 com.freaks.freaksstoreapp.dev）, ACTIVITY, ANDROID_SERIAL
#
# 注意: Flutter はキャンバス描画のため uiautomator の text/resource-id が取れないことがある
#       （アクセシビリティ Semantics 依存）。find が空なら座標ベース（tap X Y）にフォールバックする。
#       堅牢に辿るなら integration_test（Key 指定）を推奨（docs/simulator-capture.md 参照）。
set -euo pipefail

SERIAL="${ANDROID_SERIAL:-$(adb devices | awk 'NR>1 && $2=="device"{print $1; exit}')}"
[ -n "$SERIAL" ] || { echo "ERROR: 接続中の Android デバイスがありません" >&2; exit 1; }
APP_ID="${APP_ID:-com.freaks.freaksstoreapp.dev}"
ACTIVITY="${ACTIVITY:-com.freaks.freaksstoreapp.MainActivity}"
adbx() { adb -s "$SERIAL" "$@"; }

dump_ui() {
  adbx shell uiautomator dump /sdcard/ui.xml >/dev/null
  adbx pull /sdcard/ui.xml /tmp/adb_ui.xml >/dev/null
}

cmd="${1:?usage: adb_ui.sh <dump|find|tap|swipe|text|key|launch|stop|wait> ...}"; shift || true
case "$cmd" in
  dump)   dump_ui; cat /tmp/adb_ui.xml ;;
  tap)    adbx shell input tap "$1" "$2" ;;
  swipe)  adbx shell input swipe "$1" "$2" "$3" "$4" "${5:-300}" ;;
  text)   adbx shell input text "${1// /%s}" ;;
  key)    adbx shell input keyevent "$1" ;;
  launch) adbx shell am start -n "$APP_ID/$ACTIVITY" >/dev/null ;;
  stop)   adbx shell am force-stop "$APP_ID" ;;
  wait)   sleep "${1:-1}" ;;
  find)
    dump_ui
    python3 - "$1" <<'PY'
import sys, re, xml.etree.ElementTree as ET
q = sys.argv[1]
root = ET.parse('/tmp/adb_ui.xml').getroot()
hits = 0
for n in root.iter('node'):
    txt, desc, rid = n.get('text',''), n.get('content-desc',''), n.get('resource-id','')
    if q and (q in txt or q in desc or q in rid):
        m = re.findall(r'\d+', n.get('bounds',''))
        if len(m) == 4:
            cx, cy = (int(m[0])+int(m[2]))//2, (int(m[1])+int(m[3]))//2
            label = rid or desc or txt
            print(f"{cx} {cy}\t{label}\tbounds={n.get('bounds')}")
            hits += 1
if hits == 0:
    print("(no match — Flutter は Semantics 未公開のことあり。座標 tap か integration_test を使う)", file=sys.stderr)
PY
    ;;
  *) echo "ERROR: unknown command: $cmd" >&2; exit 1 ;;
esac
