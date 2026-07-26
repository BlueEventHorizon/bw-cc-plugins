#!/usr/bin/env bash
# ToC 生成前に dprint fmt を実行する共有スクリプト。
# dprint.jsonc/dprint.json が存在し dprint コマンドが利用可能な場合のみ実行する
# (anvil:commit Phase 0 と同一条件・同一コマンド)。
#
# anvil プラグインの plugins/anvil/skills/commit/scripts/run_dprint_fmt.sh と同一内容。
# ${CLAUDE_PLUGIN_ROOT} はプラグインごとに解決されるためプラグイン間でスクリプトを
# 共有できず、各プラグインが自身の複製を保持する（Issue #202）。

set -euo pipefail

if [ -f dprint.jsonc ] || [ -f dprint.json ]; then
  if command -v dprint >/dev/null 2>&1; then
    dprint fmt
  else
    echo "warning: dprint 設定ファイルがあるが dprint コマンドが見つかりません。format スキップ" >&2
  fi
fi
