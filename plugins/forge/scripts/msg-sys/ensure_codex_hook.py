#!/usr/bin/env python3
"""review: Codex 側 Stop フックの自己修復 CLI。

Codex は Claude Code のようなプラグイン自動登録機構を持たず（`.codex/hooks.json` は
Codex CLI 自身が固定のプロジェクトルート直下でのみ探すプロジェクトローカル設定であり、
`${CLAUDE_PLUGIN_ROOT}` に相当する変数はプラグインとして正式登録された場合にしか
渡されない）、`.codex/hooks.json` の登録コマンドが指すスクリプトパスは常に静的な
文字列でしかない。このパスが実在しないまま Codex の Stop フックが発火すると、
コマンド自体が実行に失敗し、Codex はそれを「ブロック」として扱い続け、応答終了の
たびに同じ失敗を繰り返す無限ループに陥る（実インシデントで確認済み）。

本スクリプトは、review 依頼モードの実行のたびに以下3点を確認・自己修復する:

1. `<project_root>/.gitignore` に `.codex/msg-sys/scripts` が含まれるか確認し、無ければ
   追記する（このスクリプトが生成する symlink はマシン固有の絶対パスを含むため、
   誤ってコミットされるとチェックアウトごとに壊れる。自分が生成する副作用の後始末は
   自分で完結させる）。
2. `<project_root>/.codex/msg-sys/scripts` を、現在ロードされている forge プラグイン
   自身の `scripts/msg-sys/`（`--plugin-msg-sys-dir` で渡される、Claude Code が
   `${CLAUDE_PLUGIN_ROOT}` を解決した実パス）への symlink にする。**コピーではなく
   symlink**なので、プラグインが更新されても再インストール作業なしで常に最新版を
   参照する。
3. `<project_root>/.codex/hooks.json` の Stop フックに、この symlink 経由の
   git-root-relative パス（`$(git rev-parse --show-toplevel)/.codex/msg-sys/scripts/
   hooks/check_inbox.py`。Codex 公式ドキュメントが「サブディレクトリ起動でも安定する」
   として推奨する形）を指すエントリが存在するか確認し、無ければ追加、古ければ
   その1エントリだけを更新する（既存の無関係な Stop フックは変更しない）。

Usage:
    python3 ensure_codex_hook.py --project-root <path> --plugin-msg-sys-dir <path> \
        [--max-round-trips 20]

出力（標準出力に単一 JSON）:
    {
      "gitignore": {"status": "added"|"already_present", "path": "..."},
      "symlink": {"status": "created"|"unchanged"|"repaired"|"conflict", "path": "...", "target": "..."},
      "hooks_json": {"status": "created"|"unchanged"|"repaired"|"appended"|"error"|"skipped_due_to_symlink_conflict", "path": "...", "reason": "..."}
    }

`symlink.status` が `"conflict"` の場合、`hooks_json` は変更されず `"skipped_due_to_symlink_conflict"`
になる（symlink が正しく用意できていない状態で hooks.json だけ書き換えると、conflict した
実ディレクトリ内にたまたま古い check_inbox.py が存在する場合、現在ロード中の forge 実装では
ないコードを Codex が起動してしまうため。実 Codex レビューで発見）。
"""

import argparse
import json
from pathlib import Path

DEFAULT_MAX_ROUND_TRIPS = 20
_CODEX_AGENT_MARKER = "FORGE_MSG_AGENT_NAME=codex"


def _desired_command(max_round_trips: int) -> str:
    return (
        f"FORGE_MSG_MAX_ROUND_TRIPS={max_round_trips} FORGE_MSG_AGENT_NAME=codex "
        'FORGE_MSG_PROJECT_ROOT="$(git rev-parse --show-toplevel)" '
        'python3 "$(git rev-parse --show-toplevel)/.codex/msg-sys/scripts/hooks/check_inbox.py"'
    )


def _ensure_gitignore_entry(project_root: Path, entry: str, comment: str) -> dict:
    """`.gitignore` に `entry` が無ければ追記する（冪等・追記のみ、既存内容は書き換えない）。

    symlink はマシン固有の絶対パスを含むため、誤ってコミットされるとチェックアウトごとに
    壊れる。このスクリプトが生成する symlink 自体の後始末は、このスクリプト自身が完結させる。
    """
    if not project_root.is_dir():
        # project_root 自体が実在しない（テスト・誤った呼び出し等）場合は何もしない。
        # 本来 project_root は常に実在するディレクトリのはずだが、無いディレクトリへの
        # 書き込みで例外を起こすよりは安全側で欠落を報告するだけにとどめる。
        return {"status": "skipped", "path": str(project_root / ".gitignore")}
    gitignore_path = project_root / ".gitignore"
    content = gitignore_path.read_text(encoding="utf-8") if gitignore_path.is_file() else ""
    if any(line.strip() == entry for line in content.splitlines()):
        return {"status": "already_present", "path": str(gitignore_path)}
    prefix = "\n" if content and not content.endswith("\n") else ""
    with gitignore_path.open("a", encoding="utf-8") as f:
        f.write(f"{prefix}# {comment}\n{entry}\n")
    return {"status": "added", "path": str(gitignore_path)}


def _ensure_symlink(project_root: Path, plugin_msg_sys_dir: Path) -> dict:
    msg_sys_dir = project_root / ".codex" / "msg-sys"
    msg_sys_dir.mkdir(parents=True, exist_ok=True)
    scripts_link = msg_sys_dir / "scripts"
    target = str(Path(plugin_msg_sys_dir).resolve())
    # symlink は絶対パスで作成する（相対パスを試みたが撤回。ユーザー指摘で再検討した結果）。
    # forge がマーケットプレイス経由でインストールされる通常のケースでは、
    # CLAUDE_PLUGIN_ROOT はプロジェクトの場所と無関係な固定位置
    # （`~/.claude/plugins/cache/.../forge/<version>/`）になる。この場合、絶対パスなら
    # プロジェクトディレクトリ単体を移動・リネームしてもプラグインキャッシュの絶対パスは
    # 不変なため symlink は追随するが、相対パスだとプロジェクトから見たキャッシュまでの
    # 相対位置が変わり symlink が壊れる（相対パスが有利なのは、プロジェクトとプラグインを
    # 同じ相対関係を保ったまま環境ごと移行する dev monorepo 特有の構成に限られ、
    # 一般的な利用パターンでは相対パスの方が壊れやすい）。

    if scripts_link.is_symlink():
        # dangling symlink（target が既に存在しない）でも resolve() は例外を投げない
        # （strict=False が既定）。理論上の解決結果同士を単純比較する。
        current = str(scripts_link.resolve())
        if current == target:
            return {"status": "unchanged", "path": str(scripts_link), "target": target}
        scripts_link.unlink()
        scripts_link.symlink_to(target, target_is_directory=True)
        return {"status": "repaired", "path": str(scripts_link), "target": target}

    if scripts_link.exists():
        # symlink ではない実体（何らかの理由で実ディレクトリ・ファイルが存在する）。
        # 誤って人間のデータを削除しないよう、上書きせず conflict として報告するのみに
        # とどめる（DES-047 §2.1 と同じ「疑わしきは書き換えない」原則）。
        return {"status": "conflict", "path": str(scripts_link)}

    scripts_link.symlink_to(target, target_is_directory=True)
    return {"status": "created", "path": str(scripts_link), "target": target}


def _find_codex_command_container(data: dict) -> dict | None:
    """`hooks.Stop[].hooks[]` の中から codex 向け check_inbox.py 登録を探す。

    check_setup.py の `_match_registration_target` ほど厳密な字句解析はしない
    （本スクリプトの責務は「既存の同種エントリを上書き修復するか、無ければ
    追加するか」の判定であり、`FORGE_MSG_AGENT_NAME=codex` と `check_inbox.py` を
    両方含むかどうかの単純な判定で十分。厳密な検証は check_setup.py 側の責務）。
    """
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return None
    stop_entries = hooks.get("Stop")
    if not isinstance(stop_entries, list):
        return None
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
            if isinstance(command, str) and _CODEX_AGENT_MARKER in command and "check_inbox.py" in command:
                return hook
    return None


def _ensure_hooks_json(project_root: Path, max_round_trips: int) -> dict:
    hooks_path = project_root / ".codex" / "hooks.json"
    desired_command = _desired_command(max_round_trips)

    if not hooks_path.is_file():
        hooks_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": desired_command}]}]}}
        hooks_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"status": "created", "path": str(hooks_path)}

    try:
        data = json.loads(hooks_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # 壊れた既存ファイルを勝手に上書きしない（人間が調査できるよう fail closed で報告する）。
        return {"status": "error", "path": str(hooks_path), "reason": f"読み込みに失敗しました: {exc}"}

    if not isinstance(data, dict):
        return {"status": "error", "path": str(hooks_path), "reason": "トップレベルがオブジェクトではありません"}

    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return {"status": "error", "path": str(hooks_path), "reason": "'hooks' がオブジェクトではありません"}

    stop_entries = hooks.setdefault("Stop", [])
    if not isinstance(stop_entries, list):
        return {"status": "error", "path": str(hooks_path), "reason": "'hooks.Stop' が配列ではありません"}

    container = _find_codex_command_container(data)
    if container is not None:
        if container.get("command") == desired_command:
            return {"status": "unchanged", "path": str(hooks_path)}
        container["command"] = desired_command
        hooks_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"status": "repaired", "path": str(hooks_path)}

    # 既存の他の Stop エントリ（無関係な hooks）は変更せず、新規エントリとして追加する。
    stop_entries.append({"hooks": [{"type": "command", "command": desired_command}]})
    hooks_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "appended", "path": str(hooks_path)}


_SYMLINK_OK_STATUSES = ("created", "unchanged", "repaired")


def ensure(project_root: str, plugin_msg_sys_dir: str, max_round_trips: int = DEFAULT_MAX_ROUND_TRIPS) -> dict:
    project_root_path = Path(project_root)
    gitignore_result = _ensure_gitignore_entry(
        project_root_path,
        ".codex/msg-sys/scripts",
        "ensure_codex_hook.py が各環境で生成するsymlink（プラグイン実体への絶対パスを含むためマシン固有・非追跡）",
    )
    symlink_result = _ensure_symlink(project_root_path, Path(plugin_msg_sys_dir))

    if symlink_result["status"] not in _SYMLINK_OK_STATUSES:
        # symlink が正しく用意できていない（conflict: 人間由来の実体が既に存在する）
        # 状態で hooks.json を書き換えると、そこに古い/別実装の check_inbox.py が
        # たまたま存在する場合、実在確認は通過するが現在ロード中の forge 実装では
        # ないコードを Codex が起動してしまう（実 Codex レビューで発見）。symlink が
        # 確実に正しい場合にのみ hooks.json を触る。
        return {
            "gitignore": gitignore_result,
            "symlink": symlink_result,
            "hooks_json": {
                "status": "skipped_due_to_symlink_conflict",
                "reason": "symlink が正しく用意できなかったため hooks.json は変更しませんでした",
            },
        }

    return {
        "gitignore": gitignore_result,
        "symlink": symlink_result,
        "hooks_json": _ensure_hooks_json(project_root_path, max_round_trips),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Codex 側 Stop フックの symlink・hooks.json 登録を確認・自己修復する",
    )
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--plugin-msg-sys-dir", required=True)
    parser.add_argument("--max-round-trips", type=int, default=DEFAULT_MAX_ROUND_TRIPS)
    args = parser.parse_args()

    result = ensure(args.project_root, args.plugin_msg_sys_dir, args.max_round_trips)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
