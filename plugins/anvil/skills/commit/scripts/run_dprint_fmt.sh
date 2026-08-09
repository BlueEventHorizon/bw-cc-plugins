#!/usr/bin/env bash
# commit 前に dprint fmt を実行する共有スクリプト。
# dprint.jsonc/dprint.json が存在し dprint コマンドが利用可能な場合のみ実行する。
#
# forge プラグインの plugins/forge/scripts/doc_structure/run_dprint_fmt.sh と同一の処理を行う。
# ${CLAUDE_PLUGIN_ROOT} はプラグインごとに解決されるためプラグイン間でスクリプトを
# 共有できず、各プラグインが自身の複製を保持する。

set -euo pipefail

if [ -f dprint.jsonc ] || [ -f dprint.json ]; then
  if command -v dprint >/dev/null 2>&1; then
    dprint fmt
  else
    echo "warning: dprint 設定ファイルがあるが dprint コマンドが見つかりません。format スキップ" >&2
  fi
fi
