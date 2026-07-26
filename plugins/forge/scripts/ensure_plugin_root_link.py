#!/usr/bin/env python3
"""SessionStart フック用: `${CLAUDE_PLUGIN_ROOT}` 配下の特定パスへの symlink を自己修復する。

`${CLAUDE_PLUGIN_ROOT}` はプラグインの hooks.json コマンド文字列・SKILL.md 本文中でのみ
解決されるプレースホルダーで、AI が静的にファイルを読む場面（Read ツール等）では解決され
ない生の文字列のまま残る。marketplace 経由でインストールされた環境では実体が
`~/.claude/plugins/cache/.../forge/...` のような非決定的なキャッシュパスになり、AI は
都度プロセス起動引数の逆引き等で実パスを推測する必要がある。

本スクリプトはセッション開始のたびに `<project_root>/.claude/<link_name>` を、渡された
`--plugin-root`（通常は `${CLAUDE_PLUGIN_ROOT}` 配下の特定サブパス。例: `.../forge/docs`）
実体への symlink として作成・修復する。プラグイン全体ではなく必要な範囲（例: docs/ のみ）
に絞ることで、無用に広い実体開示を避ける（scope_proportionality_spec.md の比例性原則）。
以降 AI はこの固定パスを読むだけで実体にアクセスでき、都度の実体確認が不要になる。

設計は `plugins/forge/scripts/msg-sys/ensure_codex_hook.py`の
symlink 自己修復パターンを踏襲する。

Usage:
    python3 ensure_plugin_root_link.py --project-root <path> --plugin-root <path> \
        --link-name <name>

出力（標準出力に単一 JSON）:
    {
      "gitignore": {"status": "added"|"already_present", "path": "..."},
      "symlink": {"status": "created"|"unchanged"|"repaired"|"conflict", "path": "...", "target": "..."}
    }
"""

import argparse
import json
from pathlib import Path


def _ensure_gitignore_entry(project_root: Path, entry: str, comment: str) -> dict:
    """`.gitignore` に `entry` が無ければ追記する（冪等・追記のみ、既存内容は書き換えない）。

    symlink はマシン固有の絶対パスを含むため、誤ってコミットされるとチェックアウトごとに
    壊れる（`ensure_codex_hook.py` と同根の事故を未然に防ぐ）。
    """
    if not project_root.is_dir():
        return {"status": "skipped", "path": str(project_root / ".gitignore")}
    gitignore_path = project_root / ".gitignore"
    content = gitignore_path.read_text(encoding="utf-8") if gitignore_path.is_file() else ""
    if any(line.strip() == entry for line in content.splitlines()):
        return {"status": "already_present", "path": str(gitignore_path)}
    prefix = "\n" if content and not content.endswith("\n") else ""
    with gitignore_path.open("a", encoding="utf-8") as f:
        f.write(f"{prefix}# {comment}\n{entry}\n")
    return {"status": "added", "path": str(gitignore_path)}


def _ensure_symlink(project_root: Path, plugin_root: Path, link_name: str) -> dict:
    claude_dir = project_root / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    link = claude_dir / link_name
    target = str(Path(plugin_root).resolve())

    if link.is_symlink():
        # dangling symlink（target が既に存在しない）でも resolve() は例外を投げない
        # （strict=False が既定）。理論上の解決結果同士を単純比較する。
        current = str(link.resolve())
        if current == target:
            return {"status": "unchanged", "path": str(link), "target": target}
        link.unlink()
        link.symlink_to(target, target_is_directory=True)
        return {"status": "repaired", "path": str(link), "target": target}

    if link.exists():
        # symlink ではない実体が既にある。誤って人間のデータを削除しないよう、
        # 上書きせず conflict として報告するのみにとどめる。
        return {"status": "conflict", "path": str(link)}

    link.symlink_to(target, target_is_directory=True)
    return {"status": "created", "path": str(link), "target": target}


def ensure(project_root: str, plugin_root: str, link_name: str) -> dict:
    project_root_path = Path(project_root)
    gitignore_result = _ensure_gitignore_entry(
        project_root_path,
        f".claude/{link_name}",
        f"セッション開始時に自動生成される ${{CLAUDE_PLUGIN_ROOT}} 実体への symlink "
        "（マシン固有の絶対パスを含むため非追跡、ensure_plugin_root_link.py）",
    )
    symlink_result = _ensure_symlink(project_root_path, Path(plugin_root), link_name)
    return {"gitignore": gitignore_result, "symlink": symlink_result}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SessionStart フック用: ${CLAUDE_PLUGIN_ROOT} 実体への symlink を自己修復する",
    )
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--plugin-root", required=True)
    parser.add_argument("--link-name", required=True)
    args = parser.parse_args()

    try:
        result = ensure(args.project_root, args.plugin_root, args.link_name)
    except OSError as exc:
        # symlink 作成に失敗しても SessionStart 自体をブロックしない（利便性機能のため
        # fail-open とする）。エラー内容は JSON で報告し、終了コードは常に 0。
        result = {"status": "error", "reason": str(exc)}

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
