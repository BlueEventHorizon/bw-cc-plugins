#!/usr/bin/env python3
"""review: target ブランチの分岐元候補を解析する CLI。

`--branch` の base ブランチを決めるための材料を返す。**採用は決めない**。
候補を根拠つきで並べるところまでが本スクリプトの責務であり、どれを base と
するかは SKILL が利用者に確認して決める（REQ-013 FNC-1312）。

既知ブランチ名の優先順位（`develop` → `main` → `master`）だけで黙って採用すると、
feature から派生したブランチを誤って `develop` 起点と判定する。実際の分岐点を
`git merge-base` で測り、**分岐点が新しい順**に並べることで、最も直近に分かれた
親を先頭に置く。

出力（単一 JSON）:
    {
      "status": "ok" | "error",
      "target_branch": "feature/work",
      "configured_base": "develop" | null,   # .git_information.yaml の設定値（参考情報）
      "candidates": [
        {
          "branch": "develop",               # 表示名
          "ref": "develop" | "origin/develop",  # git に渡す ref
          "merge_base": "<sha>",
          "ahead": 5,                        # 分岐点から HEAD 側に積まれたコミット数
          "behind": 12,                      # 分岐点から候補側に積まれたコミット数
          "is_configured": true
        }, ...
      ],
      "error": "..."                          # status == error のときのみ
    }

`candidates` は分岐点が新しい順（ahead の少ない順）に並ぶ。空配列は候補なし。
標準ライブラリのみ使用する。

Usage:
    python3 analyze_branch_point.py [--project-root <path>]
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# 分岐元になりうる典型的なブランチ名。候補の探索起点であり、優先順位ではない。
COMMON_BASE_NAMES = ("develop", "main", "master", "trunk")

_DEFAULT_BASE_BRANCH_RE = re.compile(r"^\s*default_base_branch\s*:\s*(.+?)\s*$")


def _run_git(args, project_root: Path):
    """git コマンドを実行し (returncode, stdout, stderr) を返す。"""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return 1, "", f"git 実行に失敗しました: {exc}"
    return result.returncode, result.stdout, result.stderr


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def read_configured_base_branch(project_root: Path) -> str | None:
    """`.git_information.yaml` の `default_base_branch` を読む（標準ライブラリのみ）。

    返す値は **参考情報** であり、採用を決める権限を持たない（REQ-013 FNC-1312）。
    PyYAML を使わず、対象行を正規表現で直接抽出する最小限のパースに留める。
    """
    config_path = project_root / ".git_information.yaml"
    if not config_path.is_file():
        return None
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return None

    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _DEFAULT_BASE_BRANCH_RE.match(line)
        if match:
            value = _strip_quotes(match.group(1))
            value = value.split("#", 1)[0].strip()
            if value:
                return value
    return None


def _current_branch(project_root: Path) -> str | None:
    code, stdout, _ = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], project_root)
    if code != 0:
        return None
    name = stdout.strip()
    # detached HEAD では "HEAD" が返る
    return name if name and name != "HEAD" else None


def _resolve_ref(branch: str, project_root: Path) -> str | None:
    """branch をローカル → リモート追跡の順で解決し、git に渡せる ref を返す。"""
    code, _, _ = _run_git(
        ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], project_root
    )
    if code == 0:
        return branch

    code, _, _ = _run_git(
        ["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], project_root
    )
    if code == 0:
        return f"origin/{branch}"

    return None


def _candidate_names(project_root: Path, target_branch: str | None) -> list[str]:
    """候補にするブランチ名を集める。

    典型名（develop / main / master / trunk）に加え、リポジトリに実在する
    ローカルブランチも候補にする。feature から派生したケースを拾うため、
    典型名だけに限定しない。
    """
    names: list[str] = list(COMMON_BASE_NAMES)

    code, stdout, _ = _run_git(
        ["for-each-ref", "--format=%(refname:short)", "refs/heads/"], project_root
    )
    if code == 0:
        for line in stdout.splitlines():
            name = line.strip()
            if name and name not in names:
                names.append(name)

    if target_branch is not None:
        names = [n for n in names if n != target_branch]
    return names


def _count_range(rev_range: str, project_root: Path) -> int | None:
    code, stdout, _ = _run_git(["rev-list", "--count", rev_range], project_root)
    if code != 0:
        return None
    value = stdout.strip()
    return int(value) if value.isdigit() else None


def analyze(project_root: Path) -> dict:
    code, _, stderr = _run_git(["rev-parse", "--is-inside-work-tree"], project_root)
    if code != 0:
        return {
            "status": "error",
            "error": f"git リポジトリではありません: {stderr.strip()}",
        }

    target_branch = _current_branch(project_root)
    configured = read_configured_base_branch(project_root)

    candidates = []
    seen_refs: set[str] = set()
    for name in _candidate_names(project_root, target_branch):
        ref = _resolve_ref(name, project_root)
        if ref is None or ref in seen_refs:
            continue

        code, stdout, _ = _run_git(["merge-base", ref, "HEAD"], project_root)
        if code != 0:
            continue
        merge_base = stdout.strip()
        if not merge_base:
            continue

        # 分岐点が HEAD 自身なら、その候補は HEAD の祖先を共有しているだけで
        # 分岐元とは言えない（HEAD が候補に完全に含まれる）。ahead = 0 で表れる。
        ahead = _count_range(f"{merge_base}..HEAD", project_root)
        behind = _count_range(f"{merge_base}..{ref}", project_root)
        if ahead is None or behind is None:
            continue

        seen_refs.add(ref)
        candidates.append({
            "branch": name,
            "ref": ref,
            "merge_base": merge_base,
            "ahead": ahead,
            "behind": behind,
            "is_configured": name == configured,
        })

    # 分岐点が新しい順 = HEAD 側に積まれたコミットが少ない順。
    # 分岐点が同一のブランチは ahead / behind が並ぶため（まだ分かれていない）、
    # 同点時は設定値（configured_base）を優先し、それでも決まらなければ名前順で安定させる。
    # configured_base は同点の判断材料としてのみ使い、順位を飛び越える力は持たない。
    candidates.sort(
        key=lambda c: (c["ahead"], c["behind"], not c["is_configured"], c["branch"])
    )

    return {
        "status": "ok",
        "target_branch": target_branch,
        "configured_base": configured,
        "candidates": candidates,
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="target ブランチの分岐元候補を解析する CLI",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="プロジェクトルート（省略時は cwd を使う）",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root) if args.project_root else Path.cwd()
    print(json.dumps(analyze(project_root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
