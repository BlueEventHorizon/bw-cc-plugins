#!/usr/bin/env python3
"""review 対象解決 CLI。

`/forge:review` の対象軸（diff / branch / files / dirs）ごとに対象ファイルを
列挙し、`{"status", "mode", "base_branch", "files", "dirs", "warnings"}` の単一
JSON を標準出力へ返す。標準ライブラリのみ使用する（`git` は subprocess で呼ぶ）。

使い方:
    python3 resolve_targets.py --mode <diff|branch|files|dirs> \
        [--files a,b,...] [--dirs d1,d2,...] [--base-branch <name>] \
        [--project-root <path>]

モードの挙動:
    diff:   HEAD に対する未 commit 変更（staged + unstaged）+ 未追跡ファイル
    branch: base ブランチとの merge-base 以降の全変更
            （commit 済み + 未 commit + 未追跡）。base ブランチは
            `--base-branch` で明示的に受け取る。省略時に限り
            `.git_information.yaml` の `default_base_branch` → `develop` →
            `main` → `master` の優先順位で自前解決する
    files:  指定ファイル（--files a,b,c のカンマ区切り）の存在検証のみ
    dirs:   指定ディレクトリ（--dirs d1,d2 のカンマ区切り）の存在検証と、
            配下ファイルの列挙

`dirs` は `files` と異なり**範囲指定**である。返す `files`（配下ファイル）は
修正フェーズの allowlist としてのみ使い、レビュアーへは `dirs` をそのまま渡す
（REQ-013 FNC-1312。allowlist はレビュアーへ渡さないため同要件の対象外）。

`branch` モードで `--base-branch` を受け取るのは、base を利用者への確認で確定する
という REQ-013 の要求に allowlist 側も従わせるためである。呼び出し側が確定した base を
渡せないと、依頼本文の差分範囲と allowlist が別々の base を起点にして食い違い、
範囲内のファイルへの修正が allowlist 逸脱として上がる。

対象 0 件・不在パスは status: error を返す。パスはすべて
プロジェクトルート相対で返す。
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_BASE_CANDIDATES = ["develop", "main", "master"]

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


def _read_configured_base_branch(project_root: Path) -> str | None:
    """`.git_information.yaml` の `default_base_branch` を読む（標準ライブラリのみ）。

    PyYAML を使わず、対象行を正規表現で直接抽出する最小限のパースに留める
    （このファイルで必要なのは単一のスカラー値のみのため）。
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
            # インラインコメント（`develop # comment`）を除去
            value = value.split("#", 1)[0].strip()
            if value:
                return value
    return None


def _branch_ref_if_exists(branch: str, project_root: Path) -> str | None:
    """branch がローカル、またはリモート追跡ブランチ（origin/<branch>）として
    実際に存在するかを確認し、`merge-base` / `diff` に使える ref 文字列を返す。

    ローカルブランチを優先する。どちらにも存在しなければ None を返す。
    """
    code, _, _ = _run_git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], project_root)
    if code == 0:
        return branch

    code, _, _ = _run_git(
        ["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], project_root
    )
    if code == 0:
        return f"origin/{branch}"

    return None


def resolve_base_branch(project_root: Path):
    """base ブランチ解決の優先順位を適用する。

    優先順位: `.git_information.yaml` の `default_base_branch` → `develop` →
    `main` → `master`。実際にリポジトリに存在する（ローカル or
    リモート追跡）ブランチのうち、最初に見つかったものを採用する。

    戻り値: (表示用ブランチ名, git コマンドに渡す ref) のタプル。
    どの候補も存在しなければ (None, None) を返す。
    """
    candidates = []
    configured = _read_configured_base_branch(project_root)
    if configured:
        candidates.append(configured)
    for name in DEFAULT_BASE_CANDIDATES:
        if name not in candidates:
            candidates.append(name)

    for name in candidates:
        ref = _branch_ref_if_exists(name, project_root)
        if ref is not None:
            return name, ref

    return None, None


def _parse_porcelain_status_z(stdout: str) -> list[str]:
    """`git status --porcelain=v1 -z --untracked-files=all` の出力をファイル一覧へ変換する。

    staged / unstaged / 未追跡ファイルを列挙する。完全削除（`D`）は
    レビュー時に Read できないため対象から除外する。rename/copy はリネーム後の
    パスを採用する。NUL 区切り (`-z`) を使うことで、非 ASCII ファイル名の
    C-style クォート化（例: 日本語ファイル名が `"\346\227..."` と出力される事象）
    を回避し、rename の ` -> ` 文字列パースの曖昧性も解消する（rename/copy は
    新パスの後続 NUL フィールドに旧パスが別エントリとして続く）。
    """
    files: list[str] = []
    seen: set[str] = set()

    entries = stdout.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if not entry or len(entry) < 3:
            continue
        xy = entry[:2]
        path = entry[3:]

        # rename/copy (先頭が R または C) は新パスの直後に旧パスが別 NUL エントリで続く
        if xy[0] in ("R", "C"):
            i += 1

        # 完全削除（staged / unstaged いずれかで D）はレビュー対象外
        if "D" in xy:
            continue

        if path in seen:
            continue
        seen.add(path)
        files.append(path)

    return sorted(files)


def get_diff_targets(project_root: Path):
    """diff モード: 未 commit 変更（staged + unstaged）+ 未追跡ファイルを列挙する。"""
    code, stdout, stderr = _run_git(
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"], project_root
    )
    if code != 0:
        raise RuntimeError(f"git status の実行に失敗しました: {stderr.strip()}")
    return _parse_porcelain_status_z(stdout)


def get_branch_targets(project_root: Path, base_ref: str):
    """branch モード: base ブランチとの merge-base 以降の全変更を列挙する。

    commit 済みの変更（merge-base...HEAD）+ 未 commit 変更 + 未追跡ファイルを
    合わせて返す。
    """
    code, stdout, stderr = _run_git(["merge-base", base_ref, "HEAD"], project_root)
    if code != 0:
        raise RuntimeError(f"git merge-base の実行に失敗しました: {stderr.strip()}")
    merge_base = stdout.strip()
    if not merge_base:
        raise RuntimeError("git merge-base が空の結果を返しました")

    code, stdout, stderr = _run_git(
        ["diff", "--name-only", f"{merge_base}...HEAD"], project_root
    )
    if code != 0:
        raise RuntimeError(f"git diff の実行に失敗しました: {stderr.strip()}")
    committed_files = [line.strip() for line in stdout.splitlines() if line.strip()]

    uncommitted_files = get_diff_targets(project_root)

    combined = set(committed_files) | set(uncommitted_files)
    # 削除済みでワークツリーに存在しないファイルはレビュー（Read）できないため除外する
    existing = [f for f in combined if (project_root / f).is_file()]
    return sorted(existing)


def get_dir_targets(project_root: Path, dirs: list[str]):
    """dirs モード: 指定ディレクトリ配下のファイルを列挙する（allowlist 用）。

    `git ls-files` を使い、追跡済みファイルと未追跡ファイルの両方を対象にしつつ
    `.gitignore` を尊重する（`scan_secrets.py` と同じ手法）。`os.walk` で自前に歩くと
    `.git/` や `.gitignore` 対象の除外条件を独自に持つことになり、git の解釈との
    乖離がそのまま allowlist の誤りになる。
    """
    code, stdout, stderr = _run_git(
        ["ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *dirs],
        project_root,
    )
    if code != 0:
        raise RuntimeError(f"git ls-files の実行に失敗しました: {stderr.strip()}")

    candidates = {entry for entry in stdout.split("\0") if entry}
    # 削除済みでワークツリーに存在しないファイルはレビュー（Read）できないため除外する
    existing = [f for f in candidates if (project_root / f).is_file()]
    return sorted(existing)


def _split_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [token.strip() for token in raw.split(",") if token.strip()]


def _classify_paths(candidates: list[str], project_root: Path, expect_dir: bool):
    """指定パス群を (ルート外, 不在) に分類する。

    `expect_dir` が True ならディレクトリとして、False ならファイルとして実在を判定する。
    `files` モードと `dirs` モードでルート外判定・symlink 経由の脱出判定を共有するため
    分離した（片方だけ緩いと、対象軸によって安全性が変わってしまう）。
    """
    project_root_resolved = project_root.resolve()

    outside = [p for p in candidates if Path(p).is_absolute() or ".." in Path(p).parts]
    if outside:
        return outside, []

    missing = []
    for p in candidates:
        resolved = (project_root / p).resolve()
        try:
            resolved.relative_to(project_root_resolved)
        except ValueError:
            # symlink 経由でルート外へ抜けるケース。不在として扱う
            missing.append(p)
            continue
        if not (resolved.is_dir() if expect_dir else resolved.is_file()):
            missing.append(p)
    return [], missing


def _result(status, mode, base_branch, files, dirs=None, warnings=None, error=None):
    payload = {
        "status": status,
        "mode": mode,
        "base_branch": base_branch,
        "files": files,
        "dirs": dirs or [],
        "warnings": warnings or [],
    }
    if error is not None:
        payload["error"] = error
    return payload


def resolve_targets(
    mode: str,
    project_root: Path,
    files_arg: str | None,
    dirs_arg: str | None = None,
    base_branch_arg: str | None = None,
):
    if base_branch_arg is not None and mode != "branch":
        return _result(
            "error", mode, None, [],
            error=f"--base-branch は branch モードでのみ指定できます（指定モード: {mode}）",
        )

    # 空文字・空白のみを「省略」と同義にしない。省略と同義にすると、呼び出し側が
    # 空の値を渡した場合に自前解決へ落ち、確定した base を渡していない事実が
    # 出力から見えなくなる（非 branch モードでは error にしているため非対称にもなる）
    if base_branch_arg is not None and not base_branch_arg.strip():
        return _result(
            "error", mode, None, [],
            error="--base-branch に空の値は指定できません（省略する場合は引数自体を渡さないでください）",
        )

    if mode == "files":
        candidates = _split_csv(files_arg)
        if not candidates:
            return _result(
                "error", mode, None, [],
                error="--files モードには --files でファイルパスを1つ以上指定してください",
            )

        outside, missing = _classify_paths(candidates, project_root, expect_dir=False)
        if outside:
            return _result(
                "error", mode, None, [],
                error=f"プロジェクトルート外を指すパスは指定できません: {', '.join(outside)}",
            )
        if missing:
            return _result(
                "error", mode, None, [],
                error=f"指定されたファイルが見つかりません: {', '.join(missing)}",
                warnings=[f"不在ファイル: {f}" for f in missing],
            )

        return _result("ok", mode, None, sorted(candidates))

    if mode == "dirs":
        candidates = _split_csv(dirs_arg)
        if not candidates:
            return _result(
                "error", mode, None, [],
                error="--dirs モードには --dirs でディレクトリパスを1つ以上指定してください",
            )

        outside, missing = _classify_paths(candidates, project_root, expect_dir=True)
        if outside:
            return _result(
                "error", mode, None, [],
                error=f"プロジェクトルート外を指すパスは指定できません: {', '.join(outside)}",
            )
        if missing:
            return _result(
                "error", mode, None, [],
                error=f"指定されたディレクトリが見つかりません: {', '.join(missing)}",
                warnings=[f"不在ディレクトリ: {d}" for d in missing],
            )

        normalized = sorted(d.rstrip("/") for d in candidates)
        try:
            files = get_dir_targets(project_root, normalized)
        except RuntimeError as exc:
            return _result("error", mode, None, [], dirs=normalized, error=str(exc))

        if not files:
            return _result(
                "error", mode, None, [], dirs=normalized,
                error=(
                    "指定されたディレクトリ配下にレビュー対象ファイルがありません: "
                    f"{', '.join(normalized)}"
                ),
            )

        return _result("ok", mode, None, files, dirs=normalized)

    if mode == "diff":
        try:
            files = get_diff_targets(project_root)
        except RuntimeError as exc:
            return _result("error", mode, None, [], error=str(exc))

        if not files:
            return _result("error", mode, None, [], error="レビュー対象がありません")

        return _result("ok", mode, None, files)

    if mode == "branch":
        if base_branch_arg is not None:
            # 明示指定された base が存在しなければ fail closed とする。自前解決へ
            # 落とすと、利用者が確定した base とは別の起点で allowlist が作られ、
            # その食い違いが出力からは見えない
            base_branch = base_branch_arg
            base_ref = _branch_ref_if_exists(base_branch, project_root)
            if base_ref is None:
                return _result(
                    "error", mode, base_branch, [],
                    error=(
                        f"指定された base ブランチが見つかりません: {base_branch}"
                        "（ローカル・origin のいずれにも存在しません）"
                    ),
                )
        else:
            base_branch, base_ref = resolve_base_branch(project_root)
            if base_branch is None:
                return _result(
                    "error", mode, None, [],
                    error=(
                        "base ブランチを解決できません（.git_information.yaml の "
                        "default_base_branch / develop / main / master のいずれも"
                        "リポジトリに存在しません）"
                    ),
                )

        try:
            files = get_branch_targets(project_root, base_ref)
        except RuntimeError as exc:
            return _result("error", mode, base_branch, [], error=str(exc))

        if not files:
            return _result(
                "error", mode, base_branch, [], error="レビュー対象がありません"
            )

        return _result("ok", mode, base_branch, files)

    # argparse の choices で防いでいるが、念のため防御的に処理する
    return _result("error", mode, None, [], error=f"不明なモードです: {mode}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="review 対象解決 CLI",
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["diff", "branch", "files", "dirs"],
        help="対象モード（diff|branch|files|dirs）",
    )
    parser.add_argument(
        "--files",
        default=None,
        help="files モード用のカンマ区切りファイルパス（例: a.md,b.py）",
    )
    parser.add_argument(
        "--dirs",
        default=None,
        help="dirs モード用のカンマ区切りディレクトリパス（例: docs/specs/,src/）",
    )
    parser.add_argument(
        "--base-branch",
        default=None,
        help=(
            "branch モードの base ブランチ名（呼び出し側が利用者への確認で確定した値）。"
            "省略時のみ .git_information.yaml / develop / main / master から自前解決する"
        ),
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="プロジェクトルート（省略時は cwd を使う）",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root) if args.project_root else Path.cwd()

    result = resolve_targets(
        args.mode, project_root, args.files, args.dirs, args.base_branch
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
