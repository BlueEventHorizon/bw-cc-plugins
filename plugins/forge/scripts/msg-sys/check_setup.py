#!/usr/bin/env python3
"""msg-sys セットアップの自己診断 CLI。

依頼送信前の前提検査として、以下 5 項目を機械検査し `{"status", "checks",
"warnings"}` の単一 JSON を標準出力へ返す:

    1. git リポジトリルートの解決（`git rev-parse --show-toplevel`）
    2. DB パスの導出可能性（`lib/mailbox.py` の `resolve_db_path()` を共有・再利用）
    3. forge プラグイン同梱の `hooks/hooks.json` への `check_inbox.py`
       （FORGE_MSG_AGENT_NAME=claude）登録（Claude Code のプラグイン hooks 自動登録
       機構により、プラグイン導入だけで有効化される。プロジェクト固有の
       `.claude/settings.json` 手動編集は不要。実 Codex レビューで発見の改善）
    4. `.codex/hooks.json` への `check_inbox.py`（FORGE_MSG_AGENT_NAME=codex）登録
       （Codex CLI 自体の設定であり、プラグイン機構の対象外。引き続きプロジェクト
       ごとの手動登録が必要）
    5. 上記2つの登録エントリの `FORGE_MSG_MAX_ROUND_TRIPS` 設定有無

機械検査できない項目（Codex 側 trust 登録の完了）は `warnings` に文字列として
明示する（fail-open）。5 検査項目のいずれかが不成立なら `status` を `error` にする。

**相手セッションの常駐は本 CLI の検査対象でも警告対象でもない**。かつては
「機械検査できない」項目として警告に挙げていたが、これは事実ではなかった——
稼働中のプロセスを直接確認すれば判定できる。常駐の判定は、それを前提として
必要とする側（レビューバックエンドの可用性検査）が行う。本 CLI は msg-sys 自身の
設定・健全性だけを扱い、msg-sys を使う個々の応用が何を前提とするかを知らない
（cmux 前提の常駐という概念自体が msg-sys の関心ではない）。

使い方:
    python3 check_setup.py [--project-root <path>]
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import mailbox  # noqa: E402

UNVERIFIABLE_WARNINGS = [
    "Codex 側 trust 登録（/hooks コマンドでの明示的信頼登録）の完了有無は機械検査できません"
    "（git worktree / チェックアウトごとに個別に必要です）",
]


def check_git_root(project_root: Path) -> dict:
    """git リポジトリルートの解決を検査する。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return {"name": "git_root_resolution", "ok": False, "detail": f"git 実行に失敗: {exc}"}

    if result.returncode != 0:
        return {
            "name": "git_root_resolution",
            "ok": False,
            "detail": f"git rev-parse --show-toplevel が失敗しました: {result.stderr.strip()}",
        }

    toplevel = result.stdout.strip()
    if not toplevel:
        return {
            "name": "git_root_resolution",
            "ok": False,
            "detail": "git rev-parse --show-toplevel が空文字列を返しました",
        }

    return {"name": "git_root_resolution", "ok": True, "detail": toplevel}


def check_db_path_resolution(project_root: Path) -> dict:
    """DB パスの導出可能性を検査する（`lib/mailbox.py` の `resolve_db_path()` を再利用）。

    検査対象の `project_root` を一時的に `FORGE_MSG_PROJECT_ROOT` へ設定してから
    `resolve_db_path(None)` を呼ぶ。これにより `--project-root`／cwd 由来の
    project_root が、既存の環境変数設定の有無に関わらず常に実際の DB パス導出結果に
    反映される。診断後は元の環境変数の状態（未設定・空文字列を
    含む値のいずれも）を finally で復元する。
    """
    original = os.environ.get("FORGE_MSG_PROJECT_ROOT")
    os.environ["FORGE_MSG_PROJECT_ROOT"] = str(project_root)
    try:
        db_path = mailbox.resolve_db_path(None)
    except RuntimeError as exc:
        return {"name": "db_path_resolution", "ok": False, "detail": str(exc)}
    finally:
        if original is None:
            del os.environ["FORGE_MSG_PROJECT_ROOT"]
        else:
            os.environ["FORGE_MSG_PROJECT_ROOT"] = original

    return {"name": "db_path_resolution", "ok": True, "detail": str(db_path)}


def _load_json(path: Path):
    """JSON ファイルを読み込む。存在しない・パース不能なら (None, エラー文言) を返す。"""
    if not path.is_file():
        return None, f"{path} が存在しません"
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{path} の読み込みに失敗しました: {exc}"
    return data, None


def _collect_stop_commands(data) -> list[str]:
    """`hooks.Stop[].hooks[].command` に含まれるコマンド文字列を収集する。"""
    commands: list[str] = []
    if not isinstance(data, dict):
        return commands
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return commands
    stop_entries = hooks.get("Stop")
    if not isinstance(stop_entries, list):
        return commands
    for entry in stop_entries:
        if not isinstance(entry, dict):
            continue
        entry_hooks = entry.get("hooks")
        if not isinstance(entry_hooks, list):
            continue
        for hook in entry_hooks:
            if not isinstance(hook, dict):
                continue
            command = hook.get("command")
            if isinstance(command, str):
                commands.append(command)
    return commands


_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _is_python_executable(token: str) -> bool:
    """トークンが python / python3 実行ファイル（フルパス含む）かどうかを判定する。"""
    return Path(token).name in ("python", "python3")


def _match_registration_target(command: str, agent_name: str) -> str | None:
    """単一の command 文字列を検査し、登録済みなら exec_target（スクリプトパス

    トークン、シェル置換未評価の生文字列）を返す。登録済みでなければ None。

    command 文字列をシェルトークンに分解し、(1) python/python3 実行ファイルが
    存在する、(2) その手前のトークンが全て `KEY=VALUE` 形式の環境変数代入で
    `FORGE_MSG_AGENT_NAME=<agent_name>` を含む、(3) python 実行直後の最初の
    非フラグ引数（`-m`/`-c` の指定先ではなく実際に実行されるスクリプトファイル）
    が `check_inbox.py` で終わる、の3条件を満たす場合のみ登録済みと判定する
    （DES-034 §3.1）。`echo check_inbox.py FORGE_MSG_AGENT_NAME=...` のような
    見せかけの文字列一致は python 実行トークンが無いため誤検知せず、
    `-m module /x/check_inbox.py` のように check_inbox.py が実行対象でない
    後続引数に過ぎない場合も誤検知しない。
    """
    marker = f"FORGE_MSG_AGENT_NAME={agent_name}"
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None

    python_idx = None
    for idx, token in enumerate(tokens):
        if _is_python_executable(token):
            python_idx = idx
            break
    if python_idx is None:
        return None

    prefix_tokens = tokens[:python_idx]
    if not prefix_tokens or not all(_ENV_ASSIGN_RE.match(t) for t in prefix_tokens):
        return None
    if marker not in prefix_tokens:
        return None

    script_tokens = tokens[python_idx + 1:]
    exec_target = None
    for token in script_tokens:
        if token in ("-m", "-c"):
            # -m/-c はモジュール名・インラインコード指定であり、
            # 実行対象はスクリプトファイルではないため非該当とする。
            exec_target = None
            break
        if token.startswith("-"):
            continue
        exec_target = token
        break
    if exec_target is None or not exec_target.endswith("check_inbox.py"):
        return None

    return exec_target


def _find_registration_with_target(commands: list[str], agent_name: str) -> tuple[str | None, str | None]:
    """登録済みコマンドとその exec_target（スクリプトパストークン）を両方返す。"""
    for command in commands:
        exec_target = _match_registration_target(command, agent_name)
        if exec_target is not None:
            return command, exec_target
    return None, None


def _plugin_hooks_path() -> Path:
    """forge プラグイン自身が同梱する `hooks/hooks.json` への絶対パスを返す。

    本ファイル（`check_setup.py`）は `plugins/forge/scripts/msg-sys/` に配置されている
    ため、2階層上がプラグインルート（`plugins/forge/`）になる。プロジェクトごとの
    `.claude/settings.json` とは独立に、プラグイン同梱のこの静的ファイルを検査する
    （Claude 側の Stop フックはプラグイン導入だけで自動登録されるため）。
    """
    return Path(__file__).resolve().parents[2] / "hooks" / "hooks.json"


def _plugin_check_inbox_path() -> Path:
    """forge プラグイン自身が同梱する `hooks/check_inbox.py` への絶対パスを返す。

    `_plugin_hooks_path()` と同じ相対関係（本ファイルの1階層上が msg-sys ディレクトリ）
    を使う。Claude 側の登録コマンドは `${CLAUDE_PLUGIN_ROOT}` というシェル変数を含む
    文字列であり、これをシェル評価するには実行時環境に依存する（`CLAUDE_PLUGIN_ROOT`
    がプロセス環境に無い文脈で実行すると偽陽性の失敗になる）。プラグイン自身の
    ファイルレイアウトは実行時環境に依存せず一意に決まるため、シェル評価を経由せず
    直接パスを組み立てて実在確認する。
    """
    return Path(__file__).resolve().parent / "hooks" / "check_inbox.py"


# `.codex/hooks.json` から取り出した exec_target は設定ファイル由来の外部入力であり、
# 任意のシェル構文（`` ` ``・`;`・`|`・リダイレクト等）を含みうる。これを `bash -c` へ
# 直接連結して評価するとコマンドインジェクションになる（実 Codex レビューで発見。
# 「実在確認のために設定由来の任意コマンドを評価するのは不要かつ危険」との指摘）。
#
# `ensure_codex_hook.py` が生成する唯一の正当な値は固定のこの1文字列のみである
# （プロジェクトルート相対部分に `..` 等の揺らぎを許す必要はない。以前の実装は
# 緩い正規表現で相対パスを許容しており、`..` で任意の場所へエスケープできてしまう
# 欠陥があった。実 Codex レビューで発見）。EXACT MATCH のみを受理する。
_EXPECTED_CODEX_HOOK_SUFFIX = "/.codex/msg-sys/scripts/hooks/check_inbox.py"
_EXPECTED_CODEX_HOOK_TOKEN = f"$(git rev-parse --show-toplevel){_EXPECTED_CODEX_HOOK_SUFFIX}"


def _resolve_codex_hook_path(token: str, cwd: Path) -> str | None:
    """Codex 側 hooks.json の exec_target を検証・解決する（fail closed）。

    以下をすべて満たす場合のみ実パスを返す。1つでも満たさなければ None を返し、
    シェル実行は一切行わない（`git rev-parse --show-toplevel` 自体は固定 argv で
    実行し、token の内容をシェル文字列へ連結することはない）:

    1. token が `ensure_codex_hook.py` が生成する唯一の正当な文字列
       `$(git rev-parse --show-toplevel)/.codex/msg-sys/scripts/hooks/check_inbox.py`
       と厳密に一致する（`..` を含む変種等は一切受理しない）
    2. `<project_root>/.codex/msg-sys/scripts` が実際に symlink であり、その解決先が
       現在ロード中の forge プラグイン自身の `scripts/msg-sys/`（本ファイルの1階層上）
       と一致する（実 Codex レビューで発見: symlink が conflict で人間由来の実
       ディレクトリに置き換わっていても、その中にたまたま古い check_inbox.py が
       存在すれば、ファイルの実在確認だけでは検出できない）
    """
    if token.strip('"') != _EXPECTED_CODEX_HOOK_TOKEN:
        return None

    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    toplevel = proc.stdout.strip()
    if not toplevel:
        return None

    scripts_symlink = Path(toplevel) / ".codex" / "msg-sys" / "scripts"
    current_plugin_msg_sys_dir = Path(__file__).resolve().parent
    if not scripts_symlink.is_symlink():
        return None
    try:
        if scripts_symlink.resolve() != current_plugin_msg_sys_dir:
            return None
    except OSError:
        return None

    return toplevel + _EXPECTED_CODEX_HOOK_SUFFIX


def check_agent_registration(
    project_root: Path,
    path_or_rel_path: str | Path,
    agent_name: str,
    check_name: str,
    resolve_script_path: Callable[[str, Path], str | None] | None = None,
) -> tuple[dict, str | None]:
    """settings.json / hooks.json への check_inbox.py 登録を検査する。

    `path_or_rel_path` に絶対パスを渡した場合、`project_root` は無視される
    （`pathlib` の `/` 演算子は右辺が絶対パスだと左辺を無視する挙動を利用する。
    forge プラグイン同梱の `hooks/hooks.json`（`_plugin_hooks_path()`）のような
    project_root 非依存のファイルを検査する場合に使う）。

    `resolve_script_path` を渡した場合、登録コマンドの exec_target をこの関数で
    実パスへ解決し、そのファイルが実在するかまで検証する（fail-closed。実際に
    「.codex/hooks.json 上は登録されているように見えるが、参照先スクリプトが
    存在しない」ことが原因で Codex の Stop フックが無限にブロックし続ける事故が
    起きたため、文字列パターン一致だけでは不十分と判明した）。渡さない場合は
    従来どおり文字列パターン一致のみで判定する。

    戻り値: (check dict, マッチした command 文字列（見つからなければ None）)
    """
    path = project_root / path_or_rel_path
    data, load_error = _load_json(path)
    if load_error is not None:
        return {"name": check_name, "ok": False, "detail": load_error}, None

    commands = _collect_stop_commands(data)
    matched, exec_target = _find_registration_with_target(commands, agent_name)
    if matched is None:
        return (
            {
                "name": check_name,
                "ok": False,
                "detail": f"{path} に check_inbox.py の Stop フック登録"
                f"（FORGE_MSG_AGENT_NAME={agent_name} 付き）が見つかりません",
            },
            None,
        )

    if resolve_script_path is not None:
        resolved = resolve_script_path(exec_target, project_root)
        if resolved is None or not Path(resolved).is_file():
            return (
                {
                    "name": check_name,
                    "ok": False,
                    "detail": f"{path} の登録コマンドが参照するスクリプト"
                    f"（{exec_target}"
                    + (f" → {resolved}" if resolved else "")
                    + f"）が実在しません",
                },
                None,
            )

    return {"name": check_name, "ok": True, "detail": f"{path} に登録済み"}, matched


def check_max_round_trips(claude_command: str | None, codex_command: str | None) -> dict:
    """登録エントリの FORGE_MSG_MAX_ROUND_TRIPS 設定有無を検査する。"""
    if claude_command is None or codex_command is None:
        missing = []
        if claude_command is None:
            missing.append("forge プラグイン hooks/hooks.json 側の登録エントリ")
        if codex_command is None:
            missing.append(".codex/hooks.json 側の登録エントリ")
        return {
            "name": "max_round_trips_configured",
            "ok": False,
            "detail": "登録エントリが見つからないため検査できません: " + " / ".join(missing),
        }

    marker = "FORGE_MSG_MAX_ROUND_TRIPS="
    claude_has = marker in claude_command
    codex_has = marker in codex_command
    if claude_has and codex_has:
        return {
            "name": "max_round_trips_configured",
            "ok": True,
            "detail": "両登録エントリに FORGE_MSG_MAX_ROUND_TRIPS が設定されています",
        }

    missing = []
    if not claude_has:
        missing.append("forge プラグイン hooks/hooks.json 側")
    if not codex_has:
        missing.append(".codex/hooks.json 側")
    return {
        "name": "max_round_trips_configured",
        "ok": False,
        "detail": "FORGE_MSG_MAX_ROUND_TRIPS が未設定です: " + " / ".join(missing),
    }


def run_checks(project_root: Path) -> dict:
    checks = []

    git_check = check_git_root(project_root)
    checks.append(git_check)

    # git_root_resolution が成功した場合、その canonical な toplevel を以後の検査に使う。
    # `project_root` にサブディレクトリを指定して実行しても（`git rev-parse --show-toplevel`
    # 自体はサブディレクトリからでも正しく解決できるため）、DB パス・`.codex/hooks.json`
    # の検査がそのサブディレクトリ配下を誤って探しにいかないようにする
    # （実 Codex レビューで発見: `--project-root plugins` 実行時に正しく設定済みのリポジトリを
    # error と誤診断していた）。git_root_resolution が失敗した場合は従来どおり
    # `project_root` をそのまま使う（後続の検査も同じ理由で failure になる）。
    canonical_root = Path(git_check["detail"]) if git_check["ok"] else project_root

    checks.append(check_db_path_resolution(canonical_root))

    claude_check, claude_command = check_agent_registration(
        canonical_root,
        _plugin_hooks_path(),
        "claude",
        "claude_plugin_hook_registration",
        resolve_script_path=lambda _exec_target, _root: str(_plugin_check_inbox_path()),
    )
    checks.append(claude_check)

    codex_check, codex_command = check_agent_registration(
        canonical_root,
        ".codex/hooks.json",
        "codex",
        "codex_hooks_registration",
        resolve_script_path=_resolve_codex_hook_path,
    )
    checks.append(codex_check)

    checks.append(check_max_round_trips(claude_command, codex_command))

    status = "ok" if all(check["ok"] for check in checks) else "error"

    return {
        "status": status,
        "checks": checks,
        "warnings": list(UNVERIFIABLE_WARNINGS),
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="msg-sys セットアップの自己診断 CLI",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="プロジェクトルート（省略時は cwd を使う）",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root) if args.project_root else Path(os.getcwd())

    result = run_checks(project_root)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
