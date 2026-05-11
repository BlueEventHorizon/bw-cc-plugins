#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""main ブランチと現在ブランチのバージョン比較スクリプト。

.version-config.yaml に定義された各 target について、
main ブランチと現在ブランチのバージョンを取得して比較する。

Usage:
    python3 get_version_status.py [--base-branch <branch>]

Options:
    --base-branch   比較基準ブランチ（デフォルト: main）

Output (JSON):
    {
      "current_branch": "feature/embedding-doc-advisor",
      "base_branch": "main",
      "targets": [
        {
          "name": "marketplace",
          "base": "0.1.0",
          "current": "0.1.1",
          "changed": true,
          "bump_type": "patch"
        },
        ...
      ],
      "summary": {
        "changed": ["marketplace", "doc-advisor"],
        "unchanged": ["forge", "anvil", "xcode"],
        "plugins_changed_on_base": ["doc-advisor"]
      }
    }

Run from: プロジェクトルート
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def find_project_root():
    """プロジェクトルートを探す。

    CLAUDE_PROJECT_DIR 環境変数 → .git ディレクトリを辿る順で探索する。
    """
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)

    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return current


def load_version_config(project_root):
    """version-config.yaml を読み込む。

    Returns:
        dict: 設定内容

    Raises:
        FileNotFoundError: ファイルが存在しない場合
        ValueError: YAML パースに失敗した場合
    """
    config_path = project_root / ".version-config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(
            f".version-config.yaml が見つかりません: {config_path}\n"
            "先に setup-version-config を実行してください。"
        )

    # 標準ライブラリのみで最小限の YAML パース（単純な key: value 形式）
    content = config_path.read_text(encoding="utf-8")
    return _parse_version_config_yaml(content)


def _parse_version_config_yaml(content):
    """version-config.yaml の最小限パーサー。

    PyYAML 非依存で .version-config.yaml の構造を解析する。
    targets リストと changelog/git セクションのみ対象。
    """
    targets = []
    changelog = {}
    git_config = {}

    lines = content.splitlines()
    i = 0
    current_target = None
    current_sync = None
    in_targets = False
    in_changelog = False
    in_git = False
    in_sync_files = False

    while i < len(lines):
        line = lines[i]
        indent = len(line) - len(line.lstrip())
        content = line.strip()  # 先頭・末尾の空白を除去した内容

        # コメント・空行スキップ
        if not content or content.startswith("#"):
            i += 1
            continue

        # トップレベルセクション検出
        if indent == 0:
            if content == "targets:":
                in_targets = True
                in_changelog = False
                in_git = False
                current_target = None
            elif content == "changelog:":
                in_targets = False
                in_changelog = True
                in_git = False
            elif content == "git:":
                in_targets = False
                in_changelog = False
                in_git = True
            i += 1
            continue

        # targets セクション内
        if in_targets:
            if indent == 2 and content.startswith("- name:"):
                current_target = {
                    "name": content.split(":", 1)[1].strip(),
                    "sync_files": [],
                }
                targets.append(current_target)
                in_sync_files = False
            elif indent == 4 and current_target is not None:
                if content == "sync_files:":
                    in_sync_files = True
                elif not in_sync_files:
                    key, _, val = content.partition(":")
                    current_target[key.strip()] = val.strip()
            elif indent == 6 and in_sync_files and content.startswith("- path:"):
                current_sync = {"path": content.split(":", 1)[1].strip()}
                if current_target:
                    current_target["sync_files"].append(current_sync)
            elif indent == 8 and current_sync is not None and in_sync_files:
                key, _, val = content.partition(":")
                current_sync[key.strip()] = val.strip()

        elif in_changelog:
            key, _, val = content.partition(":")
            changelog[key.strip()] = val.strip()

        elif in_git:
            key, _, val = content.partition(":")
            git_config[key.strip()] = val.strip()

        i += 1

    return {
        "targets": targets,
        "changelog": changelog,
        "git": git_config,
    }


def get_file_content_from_branch(branch, file_path):
    """指定ブランチのファイル内容を git show で取得する。

    Args:
        branch: ブランチ名（例: "main"）
        file_path: プロジェクトルートからの相対パス

    Returns:
        str or None: ファイル内容。ブランチに存在しない場合は None
    """
    try:
        result = subprocess.run(
            ["git", "show", f"{branch}:{file_path}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except Exception:
        return None


def get_current_branch():
    """現在のブランチ名を取得する。"""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip() or "HEAD (detached)"
        return "unknown"
    except Exception:
        return "unknown"


def resolve_version_path(data, version_path):
    """JSON データから version_path で指定されたフィールドを取得する。

    Args:
        data: JSON パース済み dict
        version_path: ドット区切りパス（例: "version", "metadata.version"）

    Returns:
        str or None: バージョン文字列
    """
    keys = version_path.split(".")
    current = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return str(current) if current is not None else None


def get_version_from_json_content(content, version_path):
    """JSON 文字列から指定パスのバージョンを取得する。

    Args:
        content: JSON 文字列
        version_path: ドット区切りパス

    Returns:
        str or None: バージョン文字列
    """
    try:
        data = json.loads(content)
        return resolve_version_path(data, version_path)
    except (json.JSONDecodeError, ValueError):
        return None


SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def classify_bump(base_ver, current_ver):
    """バンプ種別を判定する（patch / minor / major / downgrade / same）。"""
    bm = SEMVER_RE.match(base_ver or "")
    cm = SEMVER_RE.match(current_ver or "")
    if not bm or not cm:
        return "unknown"
    b = tuple(int(x) for x in bm.groups())
    c = tuple(int(x) for x in cm.groups())
    if c == b:
        return "same"
    if c < b:
        return "downgrade"
    if c[0] > b[0]:
        return "major"
    if c[1] > b[1]:
        return "minor"
    return "patch"


def main():
    parser = argparse.ArgumentParser(
        description="main ブランチと現在ブランチのバージョンを比較する"
    )
    parser.add_argument(
        "--base-branch",
        default="main",
        help="比較基準ブランチ（デフォルト: main）",
    )
    args = parser.parse_args()

    project_root = find_project_root()

    try:
        config = load_version_config(project_root)
    except FileNotFoundError as e:
        print(json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False))
        sys.exit(1)

    base_branch = args.base_branch
    current_branch = get_current_branch()

    results = []
    for target in config.get("targets", []):
        name = target.get("name", "")
        version_file = target.get("version_file", "")
        version_path = target.get("version_path", "version")

        # base ブランチのバージョン取得
        base_content = get_file_content_from_branch(base_branch, version_file)
        base_ver = get_version_from_json_content(base_content, version_path) if base_content else None

        # 現在ブランチのバージョン取得
        local_path = project_root / version_file
        current_ver = None
        if local_path.exists():
            try:
                current_ver = get_version_from_json_content(
                    local_path.read_text(encoding="utf-8"), version_path
                )
            except Exception:
                pass

        bump = classify_bump(base_ver, current_ver)
        changed = bump not in ("same", "unknown") and base_ver is not None

        entry = {
            "name": name,
            "version_file": version_file,
            "base": base_ver,
            "current": current_ver,
            "changed": changed,
        }
        if changed:
            entry["bump_type"] = bump
        if base_ver is None:
            entry["note"] = f"{base_branch} ブランチに {version_file} が存在しない（新規追加）"

        results.append(entry)

    changed_names = [r["name"] for r in results if r["changed"]]
    unchanged_names = [r["name"] for r in results if not r["changed"]]

    # marketplace 以外で変更されたプラグインのうち、marketplace バンプが必要かを判定
    # ルール: marketplace 以外の target が変更されているが marketplace が変わっていない = 要バンプ
    non_marketplace_changed = [n for n in changed_names if n != "marketplace"]
    marketplace_entry = next((r for r in results if r["name"] == "marketplace"), None)
    marketplace_bumped = marketplace_entry["changed"] if marketplace_entry else False
    marketplace_needs_bump = bool(non_marketplace_changed) and not marketplace_bumped

    output = {
        "status": "ok",
        "current_branch": current_branch,
        "base_branch": base_branch,
        "targets": results,
        "summary": {
            "changed": changed_names,
            "unchanged": unchanged_names,
            "marketplace_bumped": marketplace_bumped,
            "marketplace_needs_bump": marketplace_needs_bump,
        },
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
