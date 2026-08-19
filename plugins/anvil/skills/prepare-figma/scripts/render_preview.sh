#!/usr/bin/env bash
# デザイン仕様書 (.md) から preview JSON を抽出し、HTML を経由して PNG を生成する.
#
# Usage:
#   ./render_preview.sh <spec.md> <out_dir> [<base_name>]
#
#   spec.md       : デザイン仕様書（preview JSON ブロックを含む）
#   out_dir       : 出力先ディレクトリ
#   base_name     : 出力ファイル基本名（既定: spec ファイル名 stem + "_preview"）
#
# 出力:
#   <out_dir>/<base_name>.json   抽出した JSON
#   <out_dir>/<base_name>.html   変換後の HTML
#   <out_dir>/<base_name>.png    Chromium で撮影した PNG
#
# 依存:
#   - python3（標準ライブラリのみ。JSON→HTML 変換に使用）
#   - Pillow 入りの Python ランタイム（uv 推奨。PNG トリミングに使用）
#   - Google Chrome / Chromium（macOS では /Applications/Google Chrome.app があれば自動検出）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEC_MD="${1:-}"
OUT_DIR="${2:-}"
BASE_NAME="${3:-}"

if [[ -z "${SPEC_MD}" || -z "${OUT_DIR}" ]]; then
  echo "Usage: $0 <spec.md> <out_dir> [<base_name>]" >&2
  exit 1
fi

if [[ ! -f "${SPEC_MD}" ]]; then
  echo "spec.md not found: ${SPEC_MD}" >&2
  exit 1
fi

if [[ -z "${BASE_NAME}" ]]; then
  fname="$(basename "${SPEC_MD}")"
  stem="${fname%.*}"
  BASE_NAME="${stem}_preview"
fi

mkdir -p "${OUT_DIR}"
JSON_PATH="${OUT_DIR}/${BASE_NAME}.json"
HTML_PATH="${OUT_DIR}/${BASE_NAME}.html"
PNG_PATH="${OUT_DIR}/${BASE_NAME}.png"

# Chrome 実行ファイルの解決
resolve_chrome() {
  if [[ -n "${CHROME_BIN:-}" && -x "${CHROME_BIN}" ]]; then
    echo "${CHROME_BIN}"; return
  fi
  if command -v google-chrome >/dev/null 2>&1; then
    command -v google-chrome; return
  fi
  if command -v chromium >/dev/null 2>&1; then
    command -v chromium; return
  fi
  if [[ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]]; then
    echo "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; return
  fi
  if [[ -x "/Applications/Chromium.app/Contents/MacOS/Chromium" ]]; then
    echo "/Applications/Chromium.app/Contents/MacOS/Chromium"; return
  fi
  echo ""
}

CHROME_PATH="$(resolve_chrome)"
if [[ -z "${CHROME_PATH}" ]]; then
  cat >&2 <<'EOM'
[render_preview.sh] Chrome/Chromium が見つかりません。以下のいずれかで対応してください:
  - macOS: Google Chrome をインストール
  - Linux: apt install chromium 等
  - 環境変数 CHROME_BIN に実行ファイルパスを指定
EOM
  exit 2
fi

# json_to_html.py / extract_preview_json.py は標準ライブラリのみで動作するため
# uv/依存チェックは不要。本 SKILL は他の箇所（Step 5 の python3 -c 呼び出し等）でも
# 素の python3 を前提にしており、python3 の存在チェックはスコープ外とする。
PY_RUNNER="python3"

# trim_screenshot.py は Pillow に依存するため、Pillow が使えるランタイムを解決する。
PILLOW_RUNNER=""
if command -v uv >/dev/null 2>&1; then
  PILLOW_RUNNER="uv run --quiet --script"
elif python3 -c "import PIL" >/dev/null 2>&1; then
  PILLOW_RUNNER="python3"
else
  cat >&2 <<'EOM'
[render_preview.sh] Pillow 入りの Python ランタイムが見つかりません。以下のいずれかで対応してください:
  - uv をインストール（推奨）: brew install uv
  - もしくはシステム Python に Pillow を導入: pip install pillow
EOM
  exit 2
fi

SPEC_LOWER="$(echo "${SPEC_MD}" | tr '[:upper:]' '[:lower:]')"
case "${SPEC_LOWER}" in
  *.json)
    echo "[render_preview.sh] Input is JSON; skipping extraction..."
    cp "${SPEC_MD}" "${JSON_PATH}"
    ;;
  *)
    echo "[render_preview.sh] Extracting preview JSON from ${SPEC_MD}..."
    ${PY_RUNNER} "${SCRIPT_DIR}/extract_preview_json.py" "${SPEC_MD}" "${JSON_PATH}"
    ;;
esac

echo "[render_preview.sh] Converting JSON to HTML..."
${PY_RUNNER} "${SCRIPT_DIR}/json_to_html.py" "${JSON_PATH}" "${HTML_PATH}"

# Chromium の screenshot は --window-size の幅と高さを使う。
# 高さは内容により可変なので、十分に大きく取って後でトリミングは省略する。
# ビューポート幅は JSON 内で 390px が既定なので、左右の余白を考慮して 430 を指定。
WINDOW_WIDTH="${PREVIEW_WINDOW_WIDTH:-430}"
WINDOW_HEIGHT="${PREVIEW_WINDOW_HEIGHT:-3000}"

resolve_abs_path() {
  local p="$1"
  if [[ "${p}" = /* ]]; then
    echo "${p}"
  else
    echo "$(cd "$(dirname "${p}")" && pwd)/$(basename "${p}")"
  fi
}

HTML_ABS="$(resolve_abs_path "${HTML_PATH}")"
PNG_ABS="$(resolve_abs_path "${PNG_PATH}")"

# 強制終了のためのタイムアウト（既定 60 秒）。
# 注: macOS の Chrome は ``--user-data-dir`` を指定するとハングする事例があるため、
# 通常はデフォルトプロファイルを使う。並列実行が必要な場合のみ
# ``PREVIEW_CHROME_USER_DATA_DIR=$(mktemp -d)`` を環境変数で渡す（自己責任）.
CHROME_TIMEOUT_SEC="${PREVIEW_CHROME_TIMEOUT_SEC:-60}"
EXTRA_USER_DATA=""
EXTRA_NO_FIRSTRUN=""
EXTRA_NO_DEFAULT=""
if [[ -n "${PREVIEW_CHROME_USER_DATA_DIR:-}" ]]; then
  EXTRA_USER_DATA="--user-data-dir=${PREVIEW_CHROME_USER_DATA_DIR}"
  EXTRA_NO_FIRSTRUN="--no-first-run"
  EXTRA_NO_DEFAULT="--no-default-browser-check"
fi

echo "[render_preview.sh] Capturing screenshot via Chrome (headless, timeout=${CHROME_TIMEOUT_SEC}s)..."
(
  "${CHROME_PATH}" \
    --headless \
    --disable-gpu \
    --no-sandbox \
    --hide-scrollbars \
    --force-device-scale-factor=2 \
    --window-size="${WINDOW_WIDTH},${WINDOW_HEIGHT}" \
    ${EXTRA_USER_DATA} ${EXTRA_NO_FIRSTRUN} ${EXTRA_NO_DEFAULT} \
    --screenshot="${PNG_ABS}" \
    "file://${HTML_ABS}" >/dev/null 2>&1
) &
CHROME_PID=$!

# シンプルなタイムアウト監視（gtimeout/coreutils に依存しない）
(
  sleep "${CHROME_TIMEOUT_SEC}"
  if kill -0 "${CHROME_PID}" 2>/dev/null; then
    kill -9 "${CHROME_PID}" 2>/dev/null || true
    echo "[render_preview.sh] Chrome timed out after ${CHROME_TIMEOUT_SEC}s; killed pid ${CHROME_PID}" >&2
  fi
) &
WATCHDOG_PID=$!

# set -e 下では wait が非ゼロを返した瞬間にスクリプトが終了してしまい、
# 後続の診断（CHROME_EXIT の捕捉・PNG 有無チェック）に到達しなくなる。
# watchdog による SIGKILL では wait は 137 を返すため、ここは必ず if で受ける。
if wait "${CHROME_PID}" 2>/dev/null; then
  CHROME_EXIT=0
else
  CHROME_EXIT=$?
fi
kill "${WATCHDOG_PID}" 2>/dev/null || true
wait "${WATCHDOG_PID}" 2>/dev/null || true

if [[ ! -s "${PNG_ABS}" ]]; then
  echo "[render_preview.sh] Chrome screenshot failed (exit=${CHROME_EXIT}, no PNG output)" >&2
  exit 3
fi

echo "[render_preview.sh] Trimming bottom padding..."
${PILLOW_RUNNER} "${SCRIPT_DIR}/trim_screenshot.py" "${PNG_ABS}" "${PNG_ABS}" --margin 32 || {
  echo "[render_preview.sh] Trim failed (continuing without trim)" >&2
}

echo "[render_preview.sh] Done."
echo "  JSON: ${JSON_PATH}"
echo "  HTML: ${HTML_PATH}"
echo "  PNG : ${PNG_PATH}"
