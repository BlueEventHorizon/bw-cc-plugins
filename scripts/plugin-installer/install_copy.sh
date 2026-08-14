#!/usr/bin/env bash
# plugin-installer-template-version: 3
# plugin-installer-creator により生成 — 再生成: このプラグインプロジェクトで /meta:plugin-installer-creator を実行
#
# renewal copy mode (DES-007 / FNC-009): プラグインルート配下を以下の規則で
# 種別 A (Claude Code プロジェクト) の <target>/.claude/ 配下に commit-safe に配置する。
#
#   skills/<skill>/      → <target>/.claude/skills/<skill>/         (公式 §2.1 flat)
#   agents/<rel>/<n>.md  → <target>/.claude/agents/<rel>/<n>.md     (公式 §2.2 再帰可)
#   commands/<cmd>.md    → <target>/.claude/commands/<cmd>.md       (公式 §2.3 flat)
#   その他 top-level     → <target>/.claude/.<plugin>/<top>         (§3.3 catch-all 名前空間)
#
# 除外: /.claude-plugin/ /.git/ /hooks/ (root anchor) と __pycache__ *.pyc .DS_Store (tree-wide)
# placeholder: ${CLAUDE_PLUGIN_ROOT} 参照 (直後の第一階層で分類) を .claude/... へ inline Python で静的置換 (bare は保持)
#
set -euo pipefail

# --- reinstall leaf swap の rollback state ---
# execute_plan の reinstall 経路は、旧 leaf を削除する前に新 leaf を sibling staging に
# 完成させ、mv (rename) 2 回でスワップする。途中で中断 (SIGINT/SIGTERM やコピー失敗) した
# 場合に dest が消えたままにならないよう、backup から自動復元する。
# _CURRENT_STAGING は「staging へのコピーがまだ完了/破棄されていない」区間だけ非空になる
# (copy_leaf 呼び出し直前に設定し、swap 完了直後または install action の完了時にクリアする)。
# コピー自体が失敗して script が異常終了した場合、中途半端な staging ディレクトリが
# 残らないようここで削除する。
_SWAP_BACKUP=""
_SWAP_DEST=""
_CURRENT_STAGING=""
_cleanup_swap() {
  if [ -n "$_SWAP_BACKUP" ] && [ -e "$_SWAP_BACKUP" ] && [ ! -e "$_SWAP_DEST" ]; then
    echo "Warning: interrupted mid-swap; restoring $_SWAP_DEST from backup" >&2
    mv -- "$_SWAP_BACKUP" "$_SWAP_DEST"
    _SWAP_BACKUP=""
  fi
  if [ -n "$_CURRENT_STAGING" ] && [ -e "$_CURRENT_STAGING" ]; then
    rm -rf -- "$_CURRENT_STAGING"
    _CURRENT_STAGING=""
  fi
}
trap _cleanup_swap EXIT INT TERM

# === parse_args =====================================================
# 本スクリプト自体が Claude project copy 専用。
YES=0
FORCE=0
ARGS=()

parse_args() {
  for arg in "$@"; do
    case "$arg" in
      --yes)   YES=1 ;;
      --force) FORCE=1 ;;
      --*)
        echo "Error: unknown option: $arg" >&2
        exit 1
        ;;
      *) ARGS+=("$arg") ;;
    esac
  done
}
parse_args "$@"

if [ "${#ARGS[@]}" -lt 1 ]; then
  echo "Usage: $0 [--yes] [--force] <plugin_name> [target_dir]" >&2
  echo "  copy mode (renewal): commit-safe にプラグインルート配下を <target>/.claude/ へ配置する" >&2
  echo "  --yes:   既存配置先がある場合に確認なしで reinstall (上書き) する" >&2
  echo "  --force: --yes と同等 (互換のため受理)" >&2
  exit 1
fi

PLUGIN_NAME="${ARGS[0]}"
TARGET_DIR="${ARGS[1]:-}"
TARGET_DIR="${TARGET_DIR:-.}"
# ~ / ~/... 展開 (make 経由で literal "~/path" が渡された場合の救済、issue #6 と同じ理由)
TARGET_DIR="${TARGET_DIR/#\~/$HOME}"

# === validate_inputs ================================================
validate_inputs() {
  # rm -rf 安全のため、plugin_name は英数字 + ハイフン + アンダースコアのみ
  if ! echo "$PLUGIN_NAME" | grep -qE '^[a-zA-Z0-9_-]+$'; then
    echo "Error: plugin_name must contain only alphanumeric characters, hyphens, and underscores." >&2
    exit 1
  fi
}
validate_inputs

# === resolve_paths ==================================================
# スクリプト位置から REPO_ROOT を逆算 (scripts/plugin-installer/ から 2 階層上)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PLUGIN_SRC="$REPO_ROOT/plugins/$PLUGIN_NAME"

if [ ! -d "$PLUGIN_SRC" ]; then
  echo "Error: Plugin source not found: $PLUGIN_SRC" >&2
  exit 1
fi

LINK_BASE="$TARGET_DIR/.claude"

# python3 不在チェック + フォールバック (NFR-001: 書き込み前に早期エラー)
PYTHON3_FALLBACK="${PYTHON3_FALLBACK:-/opt/homebrew/bin/python3}"
PYTHON3=$(command -v python3 2>/dev/null || true)
if [ -z "$PYTHON3" ] || [ ! -x "$PYTHON3" ]; then
  if [ -x "$PYTHON3_FALLBACK" ]; then
    PYTHON3="$PYTHON3_FALLBACK"
  else
    echo "Error: python3 not found. Install python3 before running this installer." >&2
    echo "  macOS: brew install python  (or download from https://www.python.org/)" >&2
    echo "  Linux: apt-get install python3  /  yum install python3" >&2
    exit 1
  fi
fi

# === enumerate_leaves + classify_leaf + build_copy_plan ==============
# leaf 単位の配置計画 PLAN_* を構築する (DES-007 §5.1 / §3.2)。
# 4 つの並列配列で各 leaf の状態を保持する:
#   PLAN_SRCS[i]       : ソース絶対パス
#   PLAN_DESTS[i]      : 配置先絶対パス
#   PLAN_CATEGORIES[i] : "skill" | "agent" | "command" | "catch-all"
#   PLAN_ACTIONS[i]    : "install" | "reinstall" | "skip" | "error" (preflight が決定)
declare -a PLAN_SRCS=()
declare -a PLAN_DESTS=()
declare -a PLAN_CATEGORIES=()
declare -a PLAN_ACTIONS=()

# 公式 3 カテゴリ + 除外対象。catch-all はこれら以外の top-level エントリ。
EXCLUDE_TOPLEVEL=(.claude-plugin .git hooks)
OFFICIAL_TOPLEVEL=(skills agents commands)

# classify_leaf に相当: category と dest を計算する純関数
# 引数: $1=category $2=src_path → stdout に dest_path
compute_dest_for_leaf() {
  local category="$1" src="$2"
  case "$category" in
    skill)
      # src は <PLUGIN_SRC>/skills/<skill>/ (dir)
      printf '%s/.claude/skills/%s' "$TARGET_DIR" "$(basename "$src")"
      ;;
    agent)
      # src は <PLUGIN_SRC>/agents/<rel>/<name>.md。<rel> 階層を保持する
      local rel="${src#$PLUGIN_SRC/agents/}"
      printf '%s/.claude/agents/%s' "$TARGET_DIR" "$rel"
      ;;
    command)
      # src は <PLUGIN_SRC>/commands/<cmd>.md (flat)
      printf '%s/.claude/commands/%s' "$TARGET_DIR" "$(basename "$src")"
      ;;
    catch-all)
      # src は <PLUGIN_SRC>/<top> (dir or file)
      # 名前空間はドット付き (.{plugin}) — 公式可視名前空間 (skills/agents/commands/hooks 等) との
      # 衝突・誤認を避けるための意図的な意匠 (Issue #9 S1、FNC-009 §3.3)。
      printf '%s/.claude/.%s/%s' "$TARGET_DIR" "$PLUGIN_NAME" "$(basename "$src")"
      ;;
  esac
}

# PLAN_* に 1 leaf を追加するヘルパー
plan_append() {
  local category="$1" src="$2"
  local dest
  dest="$(compute_dest_for_leaf "$category" "$src")"
  PLAN_SRCS+=("$src")
  PLAN_DESTS+=("$dest")
  PLAN_CATEGORIES+=("$category")
  PLAN_ACTIONS+=("")  # preflight で確定
}

enumerate_leaves() {
  # skills/<skill>/  (公式 §2.1: skill ディレクトリ単位、flat)
  if [ -d "$PLUGIN_SRC/skills" ]; then
    while IFS= read -r -d '' d; do
      plan_append "skill" "$d"
    done < <(find "$PLUGIN_SRC/skills" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)
  fi

  # agents/<rel>/<name>.md  (公式 §2.2: name frontmatter で識別、再帰スキャン可)
  if [ -d "$PLUGIN_SRC/agents" ]; then
    while IFS= read -r -d '' f; do
      plan_append "agent" "$f"
    done < <(find "$PLUGIN_SRC/agents" -type f -name '*.md' -print0 | sort -z)
  fi

  # commands/<cmd>.md  (公式 §2.3: flat 運用推奨)
  if [ -d "$PLUGIN_SRC/commands" ]; then
    # サブフォルダ検出時の warning (公式仕様にサブフォルダ再帰の記述なし)
    if find "$PLUGIN_SRC/commands" -mindepth 1 -type d 2>/dev/null | grep -q .; then
      echo "Warning: subfolders under commands/ are not part of the official discovery contract." >&2
      echo "  Files in subfolders may not be recognized by Claude Code. Consider flattening." >&2
    fi
    while IFS= read -r -d '' f; do
      plan_append "command" "$f"
    done < <(find "$PLUGIN_SRC/commands" -mindepth 1 -maxdepth 1 -type f -name '*.md' -print0 | sort -z)
  fi

  # catch-all: top-level の skills/agents/commands/除外対象以外
  while IFS= read -r -d '' entry; do
    local name
    name="$(basename "$entry")"
    # 公式 3 カテゴリと除外対象をスキップ
    local skip=0
    local off
    for off in "${OFFICIAL_TOPLEVEL[@]}"; do
      [ "$name" = "$off" ] && { skip=1; break; }
    done
    if [ "$skip" -eq 0 ]; then
      local ex
      for ex in "${EXCLUDE_TOPLEVEL[@]}"; do
        [ "$name" = "$ex" ] && { skip=1; break; }
      done
    fi
    [ "$skip" -eq 1 ] && continue
    plan_append "catch-all" "$entry"
  done < <(find "$PLUGIN_SRC" -mindepth 1 -maxdepth 1 -print0 | sort -z)
}
enumerate_leaves

if [ "${#PLAN_SRCS[@]}" -eq 0 ]; then
  echo "Warning: no leaves to install for plugin '$PLUGIN_NAME' (nothing under skills/, agents/, commands/, or catch-all)." >&2
  exit 0
fi

# === detect_legacy_namespace (Issue #9 S5) ==========================
# catch-all 名前空間をドットなし (.claude/<plugin>/) からドット付き (.claude/.<plugin>/)
# へ変更したことに伴い、旧パスの残骸を検出する。abort はしない (警告のみ、DES-007 §5.4.5)。
detect_legacy_namespace() {
  local legacy_path="$TARGET_DIR/.claude/$PLUGIN_NAME"
  if [ -e "$legacy_path" ]; then
    echo "Warning: legacy namespace detected: $legacy_path/" >&2
    echo "  New copy mode places catch-all content under $TARGET_DIR/.claude/.$PLUGIN_NAME/ instead." >&2
    echo "  This directory is not touched automatically. Remove it manually if it is stale:" >&2
    echo "    git rm -r $legacy_path" >&2
  fi
}
detect_legacy_namespace

# === preflight (Pass 1) =============================================
# DES-007 §5.4.1: leaf ごとに既存配置先を確認し action を決定する。
# 衝突を 1 件でも検出 (非対話 + --yes なし) すると、書き込み前に全件 abort。
preflight() {
  local errors=0
  local i n
  n="${#PLAN_SRCS[@]}"
  for ((i = 0; i < n; i++)); do
    local dest="${PLAN_DESTS[$i]}"
    local cat="${PLAN_CATEGORIES[$i]}"
    if [ "$cat" = "catch-all" ]; then
      # 自プラグイン名前空間配下 → 存在しても自プラグイン過去 install と推定し無確認上書き
      if [ -e "$dest" ]; then
        PLAN_ACTIONS[$i]="reinstall"
      else
        PLAN_ACTIONS[$i]="install"
      fi
      continue
    fi
    # 公式 flat 配置 (skill/agent/command) の leaf 単位衝突判定
    if [ ! -e "$dest" ]; then
      PLAN_ACTIONS[$i]="install"
    elif [ "$YES" -eq 1 ] || [ "$FORCE" -eq 1 ]; then
      PLAN_ACTIONS[$i]="reinstall"
    elif [ ! -t 0 ]; then
      echo "Error: $dest already exists. Use --yes (reinstall) in non-interactive mode." >&2
      PLAN_ACTIONS[$i]="error"
      errors=$((errors + 1))
    else
      printf "Reinstall (overwrite) existing %s? [y/N] " "$dest"
      local answer=""
      read -r answer || answer=""
      if [[ "$answer" =~ ^[Yy]$ ]]; then
        PLAN_ACTIONS[$i]="reinstall"
      else
        PLAN_ACTIONS[$i]="skip"
      fi
    fi
  done
  if [ "$errors" -gt 0 ]; then
    echo "Aborting: $errors conflict(s) detected. No files were written." >&2
    exit 1
  fi
}
preflight

# === copy_leaf ======================================================
# DES-007 §5.2: rsync で root anchor 付き exclude を適用。rsync 不在時は cp -r fallback。
# 引数: $1=src $2=dest $3=category
copy_leaf() {
  local src="$1" dest="$2" category="$3"
  mkdir -p "$(dirname "$dest")"

  if [ "$category" = "agent" ] || [ "$category" = "command" ]; then
    # 単一ファイルは rsync ではなく cp で運ぶ (rsync の単一ファイルコピーは挙動が紛らわしい)
    cp -f "$src" "$dest"
    return
  fi

  # catch-all: top-level エントリがファイルの場合は単一ファイルコピー
  # (catch-all は dir / file の両方を取りうる、§5.1.2 の例: scripts/ ディレクトリ / README.md ファイル)
  if [ "$category" = "catch-all" ] && [ -f "$src" ]; then
    cp -f "$src" "$dest"
    return
  fi

  # skill / catch-all (ディレクトリ単位)
  # 注: root anchor exclude (/.claude-plugin/ /.git/ /hooks/) は enumerate_leaves が
  # プラグインルート直下で既に除外している (leaf として列挙されない)。よってここでの
  # rsync ではこれらを exclude しない (skill 内部の同名サブディレクトリを誤って削除しないため、§5.2 設計意図)。
  # ツリー全体 exclude (__pycache__/ *.pyc .DS_Store) のみ適用する。
  if [ -z "${INSTALL_COPY_DISABLE_RSYNC:-}" ] && command -v rsync &>/dev/null; then
    rsync -a \
      --exclude='__pycache__/' \
      --exclude='*.pyc' \
      --exclude='.DS_Store' \
      "$src/" "$dest/"
  else
    # cp -r fallback: ツリー全体 exclude のみを後処理で削除 (root anchor exclude は enumerate 側で済)
    # 前提: ここに到達した時点で "$dest" は必ず非存在
    #   - install action: 配置先は新規パス (preflight が確認済み)
    #   - reinstall action: execute_plan が先に `rm -rf "$dest"` を実行済み (§5.4.2)
    # `cp -r src dest` (dest 非存在) は src を dest という名前でコピーする POSIX 挙動。
    cp -r "$src" "$dest"
    find "$dest" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
    find "$dest" -name '*.pyc' -delete 2>/dev/null || true
    find "$dest" -name '.DS_Store' -delete 2>/dev/null || true
  fi
}

# === expand_placeholders ============================================
# DES-007 §5.3 (Issue #9 S2/S3/S4): 配置先のファイルツリーに対し ${CLAUDE_PLUGIN_ROOT} 参照を
# project-relative パスに静的置換する。
#
# 注: ${CLAUDE_SKILL_DIR} はここでは置換しない。Claude Code ランタイムが SKILL.md 本文中の
# ${CLAUDE_SKILL_DIR} を実行時に自動展開する (v2.1.129+、公式 skills doc)。plugin.json の
# 有無に関係なく SKILL.md が置かれたディレクトリだけで決まるスキルレベルの変数であり、
# install_copy.sh は種別 A (Claude Code プロジェクト) 専用のため、常にランタイム解決の
# 対象になる。静的置換すると project-relative パス (.claude/skills/<skill>) になり、
# ランタイムの絶対パス解決より cwd 依存で脆弱になるため、あえて置換しない。
#
# S2: ${CLAUDE_PLUGIN_ROOT} の直後のセグメントは配置ロジックと同じ分類 (OFFICIAL_TOPLEVEL か、
#     実際に配置した catch-all top-level 名か) で第一階層ごとにケース分けする。単一値
#     置換では skill/agent 間の相互参照が catch-all 名前空間に誤って解決されてしまう。
# S3: 未知セグメント・未解決参照を検出した場合、警告で流さず非ゼロ exit で fail させる。
# S4: 走査対象は今回配置 (install/reinstall) した leaf の dest 配下のみに限定する
#     (他プラグインの残存 placeholder を誤って書き換えないため、P3 修正)。
# bare トークン (直後に / なし) は説明文として保持する (lookahead `(?=/)`)。
# 対象拡張子: .md .yaml .sh .toml
expand_placeholders() {
  local plugin_ns="$1"

  local -a scan_dests=()
  local -a catchall_tops=()
  local i n
  n="${#PLAN_SRCS[@]}"
  for ((i = 0; i < n; i++)); do
    local cat="${PLAN_CATEGORIES[$i]}"
    local action="${PLAN_ACTIONS[$i]}"
    if [ "$cat" = "catch-all" ]; then
      catchall_tops+=("$(basename "${PLAN_SRCS[$i]}")")
    fi
    if [ "$action" = "install" ] || [ "$action" = "reinstall" ]; then
      scan_dests+=("${PLAN_DESTS[$i]}")
    fi
  done

  if [ "${#scan_dests[@]}" -eq 0 ]; then
    return 0
  fi

  # python3 の `-` はコード自体を stdin から読むため、データをパイプ/heredoc で同時に
  # stdin へ渡すことはできない (heredoc がコードとして stdin を占有し、パイプ側は届かない)。
  # データは一時ファイル経由で渡す。
  local data_file
  data_file="$(mktemp)"
  # bash 3.2 (macOS 既定) は set -u 下で空配列の "${arr[@]}" 展開を
  # unbound variable エラーにする既知の挙動があるため、要素数 0 の配列は printf を呼ばずスキップする。
  {
    printf '%s\n' "${#scan_dests[@]}"
    [ "${#scan_dests[@]}" -gt 0 ] && printf '%s\n' "${scan_dests[@]}"
    printf '%s\n' "${#catchall_tops[@]}"
    [ "${#catchall_tops[@]}" -gt 0 ] && printf '%s\n' "${catchall_tops[@]}"
  } > "$data_file"

  local py_exit=0
  "$PYTHON3" - "$plugin_ns" "$data_file" <<'PYEOF' || py_exit=$?
import sys, pathlib, re

plugin_ns = sys.argv[1]
data_file = pathlib.Path(sys.argv[2])

lines = data_file.read_text(encoding='utf-8').split('\n')
idx = 0
n_dest = int(lines[idx]); idx += 1
scan_dests = lines[idx:idx + n_dest]; idx += n_dest
n_cat = int(lines[idx]); idx += 1
catchall_tops = set(lines[idx:idx + n_cat]) if n_cat > 0 else set()
idx += n_cat

OFFICIAL_TOPLEVEL = {'skills', 'agents', 'commands'}
target_suffixes = {'.md', '.yaml', '.sh', '.toml'}

# ${CLAUDE_PLUGIN_ROOT} 本体のみを置換対象にする (lookahead で直後に / がある場合のみ)。
# 置換先は「直後のセグメント名」を分類して決定する (S2)。
#
# 注: トークン文字列は '$' (chr(36)) を分割して構築する。install_copy.sh 自身がこの
# 置換ロジックの説明・実装として "$CLAUDE_PLUGIN_ROOT" 等の文字列をソース中に持つため、
# 連続した literal トークンをそのままパターンに書くと、本ファイルが catch-all として
# 自分自身にインストールされる際に自己言及的にマッチしてしまう (dogfooding で実際に検出)。
_D = chr(36)  # '$'
ROOT_BRACE_RE  = re.compile(re.escape(_D + '{CLAUDE_PLUGIN_ROOT}') + r'(?=/)')
ROOT_BARE_RE   = re.compile(re.escape(_D + 'CLAUDE_PLUGIN_ROOT') + r'(?=/)')
SEG_RE = re.compile(r'/([^/]+)')

errors = []  # (kind, file, detail)

def resolve_seg(seg):
    # マッチ対象は ${CLAUDE_PLUGIN_ROOT} 本体のみ (lookahead `(?=/)` のため `/<seg>/...` は
    # マッチに含まれず、置換後もそのまま残る)。よって置換先には <seg> を含めない
    # (含めると `.claude/.meta/docs` + `/docs/...` のように <seg> が重複する)。
    if seg in OFFICIAL_TOPLEVEL:
        return '.claude'
    if seg in catchall_tops:
        return f'.claude/.{plugin_ns}'
    return None

def make_root_sub(fpath):
    def _sub(m):
        rest = m.string[m.end():]
        seg_match = SEG_RE.match(rest)
        seg = seg_match.group(1) if seg_match else ''
        resolved = resolve_seg(seg)
        if resolved is None:
            errors.append(('unknown-segment', str(fpath), seg))
            return m.group(0)  # 置換しない (未解決のまま残し、後続の再検証で検出させる)
        return resolved
    return _sub

files_to_process = []
for d in scan_dests:
    dp = pathlib.Path(d)
    if dp.is_dir():
        files_to_process.extend(f for f in dp.rglob('*') if f.is_file())
    elif dp.is_file():
        files_to_process.append(dp)

changed = 0
for fpath in files_to_process:
    if fpath.suffix not in target_suffixes:
        continue

    text = fpath.read_text(encoding='utf-8', errors='surrogateescape')
    t = text

    root_sub = make_root_sub(fpath)
    t = ROOT_BRACE_RE.sub(root_sub, t)
    t = ROOT_BARE_RE.sub(root_sub, t)

    if t != text:
        fpath.write_text(t, encoding='utf-8', errors='surrogateescape')
        changed += 1

# S3: 置換後に未解決参照が残存していないか再検査 (unknown-segment 記録と独立の保険的チェック)
LEAK_RE = re.compile(
    re.escape(_D + '{CLAUDE_PLUGIN_ROOT}') + '/|' + re.escape(_D + 'CLAUDE_PLUGIN_ROOT') + '/'
)
for fpath in files_to_process:
    if fpath.suffix not in target_suffixes:
        continue
    text = fpath.read_text(encoding='utf-8', errors='surrogateescape')
    for m in LEAK_RE.finditer(text):
        line_no = text.count('\n', 0, m.start()) + 1
        errors.append(('unresolved-reference', str(fpath), f'line {line_no}'))

if errors:
    print("Error: placeholder resolution failed for the following reference(s):", file=sys.stderr)
    for kind, fpath, detail in errors:
        print(f"  [{kind}] {fpath}: {detail}", file=sys.stderr)
    print("  Unknown segments must match an official category (skills/agents/commands) or an actually", file=sys.stderr)
    print("  placed catch-all top-level name. Fix the plugin source reference, or the source tree layout.", file=sys.stderr)
    sys.exit(1)

# stdout は静粛 (orchestrator がログ整形する)
PYEOF

  rm -f "$data_file"
  if [ "$py_exit" -ne 0 ]; then
    exit "$py_exit"
  fi
}

# === execute_plan (Pass 2) ==========================================
# DES-007 §5.4.2: leaf ごとに action を適用。
# reinstall は「新 leaf を staging に完成させてから旧 leaf と swap」の順で行う
# (旧: 先に rm -rf してからコピーしていたため、コピー失敗/中断時に leaf が消えたまま
# 残る破壊的経路があった)。staging へのコピーが失敗すれば旧 dest は無傷のまま。
execute_plan() {
  local installed=0 reinstalled=0 skipped=0
  local i n
  n="${#PLAN_SRCS[@]}"
  for ((i = 0; i < n; i++)); do
    local src="${PLAN_SRCS[$i]}"
    local dest="${PLAN_DESTS[$i]}"
    local cat="${PLAN_CATEGORIES[$i]}"
    local action="${PLAN_ACTIONS[$i]}"

    case "$action" in
      skip)
        echo "Skipped: $dest"
        skipped=$((skipped + 1))
        continue
        ;;
      reinstall)
        local staging="${dest}.new.$$"
        local backup="${dest}.old.$$"
        rm -rf -- "$staging"
        _CURRENT_STAGING="$staging"
        copy_leaf "$src" "$staging" "$cat"
        _CURRENT_STAGING=""
        _SWAP_DEST="$dest"
        _SWAP_BACKUP="$backup"
        mv -- "$dest" "$backup"
        mv -- "$staging" "$dest"
        rm -rf -- "$backup"
        _SWAP_BACKUP=""
        _SWAP_DEST=""
        echo "Reinstalled: $src → $dest"
        reinstalled=$((reinstalled + 1))
        continue
        ;;
      install)
        # 新規 leaf は dest に直接書く (旧 dest が無いので swap は不要)。
        # 失敗時に半端な dest を残さないよう _CURRENT_STAGING で追跡する。
        _CURRENT_STAGING="$dest"
        copy_leaf "$src" "$dest" "$cat"
        _CURRENT_STAGING=""
        echo "Copied: $src → $dest"
        installed=$((installed + 1))
        continue
        ;;
    esac
  done

  # 全 leaf 配置後に一括で placeholder 静的置換 (今回配置した dest のみが走査対象、S4)
  expand_placeholders "$PLUGIN_NAME"

  echo ""
  echo "Copy install complete for plugin '$PLUGIN_NAME' (Claude Code project)"
  echo "  installed=$installed reinstalled=$reinstalled skipped=$skipped"
}
execute_plan

# === print_summary ==================================================
# DES-007 §5.5: copy mode は自動 uninstall を提供しない。
# 配置先一覧と削除手順を案内する (実 rm は行わない)。
print_summary() {
  echo ""
  echo "Placed leaves under: $LINK_BASE/"
  echo ""
  echo "Note: These are real files (commit recommended for self-contained / version-pinned distribution)."
  local link_rel
  link_rel="${LINK_BASE#"$TARGET_DIR"/}"
  echo "  git add $link_rel"
  echo ""
  echo "Uninstall is not provided automatically (renewal §3.10). To remove, run:"
  echo "  git rm -r $link_rel/skills/<skill that this plugin distributed>"
  echo "  git rm -r $link_rel/agents/<agent that this plugin distributed>"
  echo "  git rm -r $link_rel/commands/<command that this plugin distributed>"
  echo "  git rm -r $link_rel/.$PLUGIN_NAME/   # catch-all namespace"
}
print_summary
