#!/usr/bin/env bash
# plugin-installer-template-version: 1
# plugin-installer-creator により生成 — 再生成: このプラグインプロジェクトで /meta:plugin-installer-creator を実行
#
# Codex プロジェクト向け copy mode (FNC-010 / DES-008): プラグインルート配下を以下の規則で
# Codex プロジェクトの <target>/.agents/ ・ <target>/.codex/ 配下に commit-safe に配置する。
#
#   skills/<skill>/       → <target>/.agents/skills/<skill>/           (公式: Codex は cwd→repo root で .agents/skills を走査)
#   agents/**/<name>.md   → <target>/.codex/agents/<name>.toml         (basename へ flat 変換)
#   agents/**/<name>.codex.toml → 対応する変換結果へ merge
#   codex-agents/**/<name>.toml → <target>/.codex/agents/<name>.toml   (standalone TOML を直接 copy)
#   commands/<cmd>.md     → 非対応。列挙時に警告してスキップ (Codex の Custom Prompts はユーザーローカル専用で repo 共有不可のため代替なし)
#   その他 top-level      → <target>/.agents/<plugin>/<top>             (catch-all 名前空間)
#
# 除外: /.claude-plugin/ /.git/ /hooks/ (root anchor) と __pycache__ *.pyc .DS_Store (tree-wide)
# placeholder: ${CLAUDE_PLUGIN_ROOT} / ${CLAUDE_SKILL_DIR} の両方を .agents|.codex/... へ inline Python で静的置換 (bare は保持)
#   (Claude Code 版 install_copy.sh と異なり、Codex にはプレースホルダのランタイム展開機能が無いため
#   ${CLAUDE_SKILL_DIR} も静的置換が必要。公式ドキュメント・公式サンプル実装のいずれにも該当する
#   自動展開の記述がなく、サンプルは全て相対パスで自スキルのファイルを参照している)
#
set -euo pipefail

# --- reinstall leaf swap の rollback state ---
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
# 本スクリプト自体が Codex project copy 専用。
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
  echo "  copy mode (Codex project): commit-safe にプラグインルート配下を <target>/.agents/ + <target>/.codex/ へ配置する" >&2
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
# leaf 単位の配置計画 PLAN_* を構築する。
#   PLAN_SRCS[i]       : ソース絶対パス
#   PLAN_DESTS[i]      : 配置先絶対パス
#   PLAN_CATEGORIES[i] : "skill" | "agent" | "direct-agent" | "catch-all"
#   PLAN_ACTIONS[i]    : "install" | "reinstall" | "skip" | "error" (preflight が決定)
declare -a PLAN_SRCS=()
declare -a PLAN_DESTS=()
declare -a PLAN_CATEGORIES=()
declare -a PLAN_ACTIONS=()

EXCLUDE_TOPLEVEL=(.claude-plugin .git hooks)
OFFICIAL_TOPLEVEL=(skills agents codex-agents commands)

# classify_leaf に相当: category と dest を計算する純関数
# 引数: $1=category $2=src_path → stdout に dest_path
compute_dest_for_leaf() {
  local category="$1" src="$2"
  case "$category" in
    skill)
      # src は <PLUGIN_SRC>/skills/<skill>/ (dir)
      # Codex は cwd から repo root まで各階層の .agents/skills を走査する (公式仕様)。
      printf '%s/.agents/skills/%s' "$TARGET_DIR" "$(basename "$src")"
      ;;
    agent)
      printf '%s/.codex/agents/%s.toml' "$TARGET_DIR" "$(basename "${src%.md}")"
      ;;
    direct-agent)
      printf '%s/.codex/agents/%s' "$TARGET_DIR" "$(basename "$src")"
      ;;
    catch-all)
      printf '%s/.agents/%s/%s' "$TARGET_DIR" "$PLUGIN_NAME" "$(basename "$src")"
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
  # skills/<skill>/  (skill ディレクトリ単位、flat)
  if [ -d "$PLUGIN_SRC/skills" ]; then
    while IFS= read -r -d '' d; do
      plan_append "skill" "$d"
    done < <(find "$PLUGIN_SRC/skills" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)
  fi

  # agents/**/<name>.md (basename へ flat 変換)
  if [ -d "$PLUGIN_SRC/agents" ]; then
    while IFS= read -r -d '' f; do
      plan_append "agent" "$f"
    done < <(find "$PLUGIN_SRC/agents" -type f -name '*.md' -print0 | sort -z)

    # companion は対応する Markdown agent が正本。単独 companion を黙って捨てない。
    local orphan_companions=0
    while IFS= read -r -d '' f; do
      local md_source="${f%.codex.toml}.md"
      if [ ! -f "$md_source" ]; then
        echo "Error: orphan Codex companion has no matching Markdown agent: $f" >&2
        echo "  Expected: $md_source" >&2
        orphan_companions=$((orphan_companions + 1))
      fi
    done < <(find "$PLUGIN_SRC/agents" -type f -name '*.codex.toml' -print0 | sort -z)
    if [ "$orphan_companions" -gt 0 ]; then
      echo "Aborting: $orphan_companions orphan companion file(s). No files were written." >&2
      exit 1
    fi
  fi

  # codex-agents/**/<name>.toml (standalone TOML を basename へ flat copy)
  if [ -d "$PLUGIN_SRC/codex-agents" ]; then
    while IFS= read -r -d '' f; do
      plan_append "direct-agent" "$f"
    done < <(find "$PLUGIN_SRC/codex-agents" -type f -name '*.toml' -print0 | sort -z)
  fi

  # commands/<cmd>.md  非対応。Codex の Custom Prompts はユーザーローカル専用
  # (~/.codex/prompts/) で repo 共有できないため、代替なしで警告のみ行いスキップする。
  if [ -d "$PLUGIN_SRC/commands" ]; then
    if find "$PLUGIN_SRC/commands" -mindepth 1 -maxdepth 1 -type f -name '*.md' 2>/dev/null | grep -q .; then
      echo "Warning: commands/ has no Codex equivalent that can be shared via the repository" >&2
      echo "  (Codex Custom Prompts are deprecated and user-local only). Skipping commands/." >&2
    fi
  fi

  # catch-all: top-level の skills/agents/codex-agents/commands/除外対象以外
  while IFS= read -r -d '' entry; do
    local name
    name="$(basename "$entry")"
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
  echo "Warning: no leaves to install for plugin '$PLUGIN_NAME' (nothing under skills/, agents/, or catch-all)." >&2
  exit 0
fi

# === preflight (Pass 1) =============================================
# leaf ごとに既存配置先を確認し action を決定する。
# 衝突を 1 件でも検出 (非対話 + --yes なし) すると、書き込み前に全件 abort。
validate_agent_source() {
  local src="$1"
  "$PYTHON3" - "$src" <<'PYEOF'
import pathlib, re, sys
try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

src = pathlib.Path(sys.argv[1])
text = src.read_text(encoding='utf-8', errors='surrogateescape')
m = re.match(r'^---\n(.*?)\n---\n?(.*)$', text, re.DOTALL)
if not m:
    raise SystemExit(f"Error: {src}: no YAML frontmatter found (expected '---' delimited block).")

fm_text, body = m.group(1), m.group(2)
fm = {}
lines = fm_text.splitlines()
i = 0
while i < len(lines):
    line = lines[i]
    i += 1
    if not line.strip() or line.lstrip().startswith('#') or ':' not in line:
        continue
    key, value = line.split(':', 1)
    key, value = key.strip(), value.strip()
    if value in {'|', '>', '|-', '>-', '|+', '>+'}:
        chunks = []
        while i < len(lines) and (not lines[i].strip() or lines[i][:1].isspace()):
            chunks.append(lines[i].strip())
            i += 1
        value = ('\n' if value.startswith('|') else ' ').join(chunks).strip()
    fm[key] = value.strip('"\'')

if not fm.get('name') or not fm.get('description'):
    raise SystemExit(f"Error: {src}: 'name' and 'description' are required frontmatter fields.")
if '"""' in body.strip('\n'):
    raise SystemExit(f'Error: {src}: body contains a literal \'"""\' which cannot be embedded in TOML.')

companion = src.with_suffix('.codex.toml')
if companion.exists() and tomllib is not None:
    try:
        tomllib.loads(companion.read_text(encoding='utf-8'))
    except Exception as exc:
        raise SystemExit(f"Error: {companion}: invalid TOML: {exc}")
PYEOF
}

validate_direct_agent_source() {
  "$PYTHON3" - "$1" <<'PYEOF'
import pathlib, sys
try:
    import tomllib
except ModuleNotFoundError:
    raise SystemExit(0)
src = pathlib.Path(sys.argv[1])
try:
    tomllib.loads(src.read_text(encoding='utf-8'))
except Exception as exc:
    raise SystemExit(f"Error: {src}: invalid TOML: {exc}")
PYEOF
}

preflight() {
  local errors=0
  local i n
  n="${#PLAN_SRCS[@]}"

  # source-side validation and destination collision detection precede every write.
  for ((i = 0; i < n; i++)); do
    local cat="${PLAN_CATEGORIES[$i]}"
    if [ "$cat" = "agent" ]; then
      validate_agent_source "${PLAN_SRCS[$i]}" || errors=$((errors + 1))
    elif [ "$cat" = "direct-agent" ]; then
      validate_direct_agent_source "${PLAN_SRCS[$i]}" || errors=$((errors + 1))
    fi
    local j
    for ((j = 0; j < i; j++)); do
      if [ "${PLAN_DESTS[$i]}" = "${PLAN_DESTS[$j]}" ]; then
        echo "Error: multiple sources target ${PLAN_DESTS[$i]}:" >&2
        echo "  ${PLAN_SRCS[$j]}" >&2
        echo "  ${PLAN_SRCS[$i]}" >&2
        errors=$((errors + 1))
      fi
    done
  done
  if [ "$errors" -gt 0 ]; then
    echo "Aborting: $errors source or destination conflict(s) detected. No files were written." >&2
    exit 1
  fi

  for ((i = 0; i < n; i++)); do
    local dest="${PLAN_DESTS[$i]}"
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

# === convert_agent_to_toml ============================================
# Claude Code の agents/<name>.md (YAML frontmatter + Markdown 本文) を
# Codex subagent の TOML (name, description, developer_instructions) へ変換する。
# name / description / 本文 (→ developer_instructions) のみ安全に変換可能。
# tools / model / permissionMode 等は Codex 側に対応するフィールドが無いか、
# 値の体系が全く異なる (例: Claude Code のモデル名と Codex のモデル名は別物) ため、
# 変換せず警告のうえ破棄する (誤変換によるツール権限の意図しない緩和を避ける)。
convert_agent_to_toml() {
  local src="$1" dest="$2"
  "$PYTHON3" - "$src" "$dest" <<'PYEOF'
import sys, re, pathlib
try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

src = pathlib.Path(sys.argv[1])
dest = pathlib.Path(sys.argv[2])
text = src.read_text(encoding='utf-8', errors='surrogateescape')

m = re.match(r'^---\n(.*?)\n---\n?(.*)$', text, re.DOTALL)
if not m:
    print(f"Error: {src}: no YAML frontmatter found (expected '---' delimited block).", file=sys.stderr)
    sys.exit(1)

fm_text, body = m.group(1), m.group(2)
fm = {}
fm_lines = fm_text.splitlines()
i = 0
while i < len(fm_lines):
    line = fm_lines[i]
    i += 1
    if not line.strip() or line.lstrip().startswith('#') or ':' not in line:
        continue
    k, v = line.split(':', 1)
    k, v = k.strip(), v.strip()
    if v in {'|', '>', '|-', '>-', '|+', '>+'}:
        chunks = []
        while i < len(fm_lines) and (not fm_lines[i].strip() or fm_lines[i][:1].isspace()):
            chunks.append(fm_lines[i].strip())
            i += 1
        v = ('\n' if v.startswith('|') else ' ').join(chunks).strip()
    fm[k] = v.strip('"\'')

name = fm.get('name', '')
description = fm.get('description', '')
if not name or not description:
    print(f"Error: {src}: 'name' and 'description' are required frontmatter fields.", file=sys.stderr)
    sys.exit(1)

KNOWN_KEYS = {'name', 'description'}
dropped = sorted(k for k in fm if k not in KNOWN_KEYS)
if dropped:
    print(f"Warning: {src.name}: frontmatter field(s) not convertible to Codex TOML, dropped: {', '.join(dropped)}", file=sys.stderr)

def toml_escape_basic(s):
    return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')

lines = []
lines.append(f'name = "{toml_escape_basic(name)}"')
lines.append(f'description = "{toml_escape_basic(description)}"')
# developer_instructions は triple-quoted string。本文中の '"""' との衝突を避けるため確認する。
body_stripped = body.strip('\n')
if '"""' in body_stripped:
    print(f"Error: {src}: body contains a literal '\"\"\"' which cannot be embedded in a TOML triple-quoted string.", file=sys.stderr)
    sys.exit(1)
lines.append('developer_instructions = """')
lines.append(body_stripped.replace('\\', '\\\\'))
lines.append('"""')

companion = src.with_suffix('.codex.toml')
if companion.exists():
    companion_text = companion.read_text(encoding='utf-8')
    # Preserve comments, unknown fields, and sections verbatim. Only the three
    # generated top-level keys are removed; the Markdown source is authoritative.
    kept = []
    in_section = False
    skipping_multiline = None
    for line in companion_text.splitlines(keepends=True):
        stripped = line.lstrip()
        if skipping_multiline:
            if skipping_multiline in line and line.count(skipping_multiline) % 2 == 1:
                skipping_multiline = None
            continue
        if stripped.startswith('['):
            in_section = True
        match = None if in_section else re.match(
            r'^(name|description|developer_instructions)\s*=\s*(.*)$',
            stripped.rstrip('\r\n'),
        )
        if match:
            value = match.group(2)
            for marker in ('"""', "'''"):
                if marker in value and value.count(marker) % 2 == 1:
                    skipping_multiline = marker
                    break
            continue
        kept.append(line)
    if skipping_multiline:
        print(f"Error: {companion}: unterminated multiline value.", file=sys.stderr)
        sys.exit(1)
    lines.extend(['', '# Merged from companion config', ''.join(kept).rstrip('\n')])

rendered = '\n'.join(lines).rstrip() + '\n'
if tomllib is not None:
    try:
        tomllib.loads(rendered)
    except Exception as exc:
        print(f"Error: {src}: merged agent TOML is invalid: {exc}", file=sys.stderr)
        sys.exit(1)

dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(rendered, encoding='utf-8', errors='surrogateescape')
PYEOF
}

# === copy_leaf ======================================================
# 引数: $1=src $2=dest $3=category
copy_leaf() {
  local src="$1" dest="$2" category="$3"
  mkdir -p "$(dirname "$dest")"

  if [ "$category" = "agent" ]; then
    convert_agent_to_toml "$src" "$dest"
    return
  fi

  # direct agent / file catch-all は単一ファイルコピー
  if [ "$category" = "direct-agent" ] || { [ "$category" = "catch-all" ] && [ -f "$src" ]; }; then
    cp -f "$src" "$dest"
    return
  fi

  # skill / catch-all (ディレクトリ単位)
  # root anchor exclude (/.claude-plugin/ /.git/ /hooks/) は enumerate_leaves が
  # プラグインルート直下で既に除外している (leaf として列挙されない)。よってここでの
  # rsync ではこれらを exclude しない (skill 内部の同名サブディレクトリを誤って削除しないため)。
  if [ -z "${INSTALL_COPY_DISABLE_RSYNC:-}" ] && command -v rsync &>/dev/null; then
    rsync -a \
      --exclude='__pycache__/' \
      --exclude='*.pyc' \
      --exclude='.DS_Store' \
      "$src/" "$dest/"
  else
    cp -r "$src" "$dest"
    find "$dest" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
    find "$dest" -name '*.pyc' -delete 2>/dev/null || true
    find "$dest" -name '.DS_Store' -delete 2>/dev/null || true
  fi
}

# === expand_placeholders ============================================
# 配置先のファイルツリーに対し ${CLAUDE_PLUGIN_ROOT} / ${CLAUDE_SKILL_DIR} の両方を
# project-relative パスへ静的置換する。
#
# 注: Claude Code 版 install_copy.sh とは異なり、${CLAUDE_SKILL_DIR} も置換対象にする。
# Codex にはこの変数を実行時に自動展開するランタイム機能が無く、公式ドキュメント・
# 公式サンプル実装のいずれも「スキル自身のディレクトリを起点とした相対パス」で
# スクリプト・参照ファイルを指す設計になっているため、静的置換が必須となる。
#
# ${CLAUDE_PLUGIN_ROOT} の直後のセグメント (`<seg>/...`) は第一階層で場合分けして解決する
# (skills/agents はフラット、それ以外は catch-all 名前空間)。${CLAUDE_SKILL_DIR} の
# 直後のパス (`/...`) は実際に配置した skill leaf の SKILL.md 直下のみ解決する。
# bare トークン (直後に / なし) は説明文として保持する (lookahead `(?=/)`)。
# 対象拡張子: .md .yaml .sh .toml
expand_placeholders() {
  local plugin_ns="$1"

  local -a scan_dests=()
  local -a catchall_tops=()
  local -a skill_dests=()
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
      if [ "$cat" = "skill" ]; then
        skill_dests+=("${PLAN_DESTS[$i]}")
      fi
    fi
  done

  if [ "${#scan_dests[@]}" -eq 0 ]; then
    return 0
  fi

  local data_file
  data_file="$(mktemp)"
  {
    printf '%s\n' "${#scan_dests[@]}"
    [ "${#scan_dests[@]}" -gt 0 ] && printf '%s\n' "${scan_dests[@]}"
    printf '%s\n' "${#catchall_tops[@]}"
    [ "${#catchall_tops[@]}" -gt 0 ] && printf '%s\n' "${catchall_tops[@]}"
    printf '%s\n' "${#skill_dests[@]}"
    [ "${#skill_dests[@]}" -gt 0 ] && printf '%s\n' "${skill_dests[@]}"
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
n_skill = int(lines[idx]); idx += 1
skill_dest_paths = lines[idx:idx + n_skill] if n_skill > 0 else []
# ${CLAUDE_SKILL_DIR} 解決の対象は「実際に配置した skill leaf の SKILL.md」のみに厳密一致させる
# (fpath.parent が skill leaf の dest 絶対パスと一致する場合のみ)。
skill_dest_set = {pathlib.Path(p).resolve() for p in skill_dest_paths}

OFFICIAL_TOPLEVEL = {'skills', 'agents', 'codex-agents'}
target_suffixes = {'.md', '.yaml', '.sh', '.toml'}

_D = chr(36)  # '$' (自己言及マッチ回避、install_copy.sh と同じ理由)
ROOT_BRACE_RE  = re.compile(re.escape(_D + '{CLAUDE_PLUGIN_ROOT}') + r'(?=/)')
ROOT_BARE_RE   = re.compile(re.escape(_D + 'CLAUDE_PLUGIN_ROOT') + r'(?=/)')
SKILL_BRACE_RE = re.compile(re.escape(_D + '{CLAUDE_SKILL_DIR}') + r'(?=/)')
SKILL_BARE_RE  = re.compile(re.escape(_D + 'CLAUDE_SKILL_DIR') + r'(?=/)')
AGENT_REF_RE = re.compile(
    r'(?:' + re.escape(_D + '{CLAUDE_PLUGIN_ROOT}') + '|' + re.escape(_D + 'CLAUDE_PLUGIN_ROOT')
    + r')/(?:agents/(?:[^/\s]+/)*([^/\s]+)\.md|codex-agents/(?:[^/\s]+/)*([^/\s]+)\.toml)'
)
CODEX_AGENTS_ROOT_RE = re.compile(
    r'(?:' + re.escape(_D + '{CLAUDE_PLUGIN_ROOT}') + '|' + re.escape(_D + 'CLAUDE_PLUGIN_ROOT')
    + r')/codex-agents(?=/|$)'
)
SEG_RE = re.compile(r'/([^/]+)')

errors = []  # (kind, file, detail)

def resolve_seg(seg):
    if seg == 'skills':
        return '.agents'
    if seg in {'agents', 'codex-agents'}:
        return '.codex'
    if seg in catchall_tops:
        return f'.agents/{plugin_ns}'
    return None

def make_root_sub(fpath):
    def _sub(m):
        rest = m.string[m.end():]
        seg_match = SEG_RE.match(rest)
        seg = seg_match.group(1) if seg_match else ''
        resolved = resolve_seg(seg)
        if resolved is None:
            errors.append(('unknown-segment', str(fpath), seg))
            return m.group(0)
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
    # SKILL.md と同じ skill root 直下の locale companion (SKILL.ja.md 等) は、
    # どちらも同じ CLAUDE_SKILL_DIR を基準に機能的参照を解決する。
    is_skill_doc = (
        re.fullmatch(r'SKILL(?:\.[^.]+)?\.md', fpath.name) is not None
        and fpath.parent.resolve() in skill_dest_set
    )
    skill_name = fpath.parent.name if is_skill_doc else None

    text = fpath.read_text(encoding='utf-8', errors='surrogateescape')
    t = text

    t = AGENT_REF_RE.sub(lambda m: f'.codex/agents/{m.group(1) or m.group(2)}.toml', t)
    t = CODEX_AGENTS_ROOT_RE.sub('.codex/agents', t)
    root_sub = make_root_sub(fpath)
    t = ROOT_BRACE_RE.sub(root_sub, t)
    t = ROOT_BARE_RE.sub(root_sub, t)
    if is_skill_doc and skill_name:
        skill_rel = f'.agents/skills/{skill_name}'
        t = SKILL_BRACE_RE.sub(skill_rel, t)
        t = SKILL_BARE_RE.sub(skill_rel, t)

    if t != text:
        fpath.write_text(t, encoding='utf-8', errors='surrogateescape')
        changed += 1

LEAK_RE = re.compile(
    re.escape(_D + '{CLAUDE_PLUGIN_ROOT}') + '/|' + re.escape(_D + 'CLAUDE_PLUGIN_ROOT') + '/|'
    + re.escape(_D + '{CLAUDE_SKILL_DIR}') + '/|' + re.escape(_D + 'CLAUDE_SKILL_DIR') + '/'
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
    print("  Unknown segments must match an official category (skills/agents/codex-agents) or an actually", file=sys.stderr)
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
# leaf ごとに action を適用。reinstall は「新 leaf を staging に完成させてから旧 leaf と
# swap」の順で行う (staging へのコピーが失敗すれば旧 dest は無傷のまま)。
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
        _CURRENT_STAGING="$dest"
        copy_leaf "$src" "$dest" "$cat"
        _CURRENT_STAGING=""
        echo "Copied: $src → $dest"
        installed=$((installed + 1))
        continue
        ;;
    esac
  done

  # 全 leaf 配置後に一括で placeholder 静的置換 (今回配置した dest のみが走査対象)
  expand_placeholders "$PLUGIN_NAME"

  echo ""
  echo "Copy install complete for plugin '$PLUGIN_NAME' (Codex project)"
  echo "  installed=$installed reinstalled=$reinstalled skipped=$skipped"
}
execute_plan

# === print_summary ==================================================
# copy mode は自動 uninstall を提供しない。配置先一覧と削除手順を案内する (実 rm は行わない)。
print_summary() {
  echo ""
  echo "Placed leaves under: $TARGET_DIR/.agents/ and $TARGET_DIR/.codex/"
  echo ""
  echo "Note: These are real files (commit recommended for self-contained / version-pinned distribution)."
  echo "  git add $TARGET_DIR/.agents/skills $TARGET_DIR/.agents/$PLUGIN_NAME $TARGET_DIR/.codex/agents"
  echo ""
  echo "Uninstall is not provided automatically. To remove, run:"
  echo "  git rm -r .agents/skills/<skill that this plugin distributed>"
  echo "  git rm -r .codex/agents/<agent that this plugin distributed>.toml"
  echo "  git rm -r .agents/$PLUGIN_NAME/   # catch-all namespace"
}
print_summary
