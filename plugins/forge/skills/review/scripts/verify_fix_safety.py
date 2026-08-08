#!/usr/bin/env python3
"""review: 修正安全検証 CLI。

`confirmed_fix` の所見を1件適用した直後に呼ぶ、**検出・報告専用**（ファイルを一切変更しない）
スクリプト。allowlist（target_files）逸脱の検出と、修正後ファイルの構文検証を行い、結果を
JSON で返す。ロールバックの実行判断・実施は本スクリプトの責務外であり、呼び出し側が
この結果を見て判断する（DES-047 §2 見直し: allowlist/構文エラーは「常に間違い」とは限らず、
レビュー基準に照らして正当な波及修正がありうるため、スクリプトが自動でファイルを書き戻す
設計は採らない）。

Usage:
    python3 verify_fix_safety.py \
        --allowed-files-json '["a.md", "b.py"]' \
        --modified-files-json '["a.md", "c.py"]' \
        --baseline-json '<capture_syntax_baseline.py の出力全体>' \
        [--project-root <path>]
"""

import argparse
import json
import subprocess
from pathlib import Path

# dprint（このリポジトリの dprint.jsonc スコープ: JSON/TOML/Markdown/YAML）でカバーされる
# 拡張子は baseline-aware（修正前から存在した format 違反は新規エラー扱いしない）。
# py_compile / bash -n は「ファイル全体の文法エラー」を返すコマンドであり、pre-existing
# 違反と新規違反の区別が無意味なため baseline を参照しない（fixer.md §3.5.4 と同じ判断）。
_DPRINT_EXTENSIONS = (".md", ".json", ".yaml", ".yml", ".toml")


def _ext(path: str) -> str:
    idx = path.rfind(".")
    return path[idx:].lower() if idx != -1 else ""


def _file_exists(path: str, project_root: str | None) -> bool:
    base = Path(project_root) if project_root else Path.cwd()
    return (base / path).is_file()


def _run(cmd: list[str], cwd: str | None) -> tuple[int | None, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=cwd)
        return proc.returncode, (proc.stderr or proc.stdout).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)


def _check_dprint(path: str, baseline_files: dict, project_root: str | None) -> tuple[str, str | None]:
    """dprint check を実行し、(bucket, message) を返す。

    bucket: "ok" | "skipped_preexisting" | "error"
    """
    returncode, message = _run(["dprint", "check", path], project_root)
    if returncode == 0:
        return "ok", None
    if returncode == 14:
        # dprint の検査対象外（includes パターン不一致）。違反ではない。
        return "ok", None
    if returncode != 20:
        # 環境依存の問題等。安全側に倒し「違反なし」とする（capture_syntax_baseline.py と同一方針）。
        return "ok", None

    baseline_entry = baseline_files.get(path)
    if baseline_entry is not None and baseline_entry.get("has_violations"):
        return "skipped_preexisting", None
    return "error", f"dprint check 違反{'（baseline外）' if baseline_entry is not None else '（baseline未取得）'}: {message}"


# py_compile.compile() は cfile 未指定時に __pycache__/*.pyc へ常に書き込む（インタプリタの
# -B フラグは sys.dont_write_bytecode を経由する暗黙のインポート時キャッシュにのみ作用し、
# py_compile モジュールの明示的な compile() 呼び出しには効かない）。本スクリプトは
# 「ファイルを一切書き換えない」検出専用スクリプトであり（§2.1）、py_compile ではこの契約を
# 満たせないため、ファイルを一切生成しない ast.parse による構文検査を使う
# （実レビューで py_compile 由来の __pycache__ 残留を発見）。
_PY_SYNTAX_CHECK_SCRIPT = (
    "import ast, sys\n"
    "with open(sys.argv[1], encoding='utf-8') as f:\n"
    "    ast.parse(f.read(), filename=sys.argv[1])\n"
)


def _check_python_syntax(path: str, project_root: str | None) -> tuple[str, str | None]:
    returncode, message = _run(["python3", "-c", _PY_SYNTAX_CHECK_SCRIPT, path], project_root)
    if returncode == 0:
        return "ok", None
    return "error", f"構文エラー (ast.parse): {message}"


def _check_bash(path: str, project_root: str | None) -> tuple[str, str | None]:
    returncode, message = _run(["bash", "-n", path], project_root)
    if returncode == 0:
        return "ok", None
    return "error", f"bash -n 失敗: {message}"


def verify(
    allowed_files: list[str],
    modified_files: list[str],
    baseline: dict,
    project_root: str | None = None,
) -> dict:
    allowed_set = set(allowed_files)
    baseline_files = baseline.get("files", {}) if isinstance(baseline, dict) else {}

    allowlist_violations = [f for f in modified_files if f not in allowed_set]

    syntax_ok: list[str] = []
    syntax_errors: dict[str, str] = {}
    syntax_skipped_preexisting: list[str] = []
    syntax_skipped_unsupported: list[str] = []
    syntax_skipped_deleted: list[str] = []

    for path in modified_files:
        ext = _ext(path)
        if ext not in _DPRINT_EXTENSIONS and ext not in (".py", ".sh"):
            syntax_skipped_unsupported.append(path)
            continue
        if not _file_exists(path, project_root):
            # 削除された正当なファイル（`modified_files` は変更・削除・rename後の現在パスを
            # 区別せず一律で渡ってくる。DES-047 §3.5）。存在しないファイルに構文検証コマンドを
            # 実行すると「ファイルがない」という無関係なエラーになり、正当な削除を伴う修正が
            # 不当に構文エラー扱いされる（実レビューで発見）。allowlist 検証は
            # 通常どおり行い（削除であっても allowlist 外なら逸脱として検出する）、
            # 構文検証のみスキップする。
            syntax_skipped_deleted.append(path)
            continue
        if ext in _DPRINT_EXTENSIONS:
            bucket, message = _check_dprint(path, baseline_files, project_root)
        elif ext == ".py":
            bucket, message = _check_python_syntax(path, project_root)
        else:
            bucket, message = _check_bash(path, project_root)

        if bucket == "ok":
            syntax_ok.append(path)
        elif bucket == "skipped_preexisting":
            syntax_skipped_preexisting.append(path)
        else:
            syntax_errors[path] = message

    status = "violations" if (allowlist_violations or syntax_errors) else "ok"

    return {
        "status": status,
        "allowlist_violations": allowlist_violations,
        "syntax_errors": syntax_errors,
        "syntax_skipped_preexisting": syntax_skipped_preexisting,
        "syntax_skipped_unsupported": syntax_skipped_unsupported,
        "syntax_skipped_deleted": syntax_skipped_deleted,
        "syntax_ok": syntax_ok,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="修正安全検証（allowlist・構文検証、検出専用）CLI",
    )
    parser.add_argument("--allowed-files-json", required=True)
    parser.add_argument("--modified-files-json", required=True)
    parser.add_argument("--baseline-json", required=True)
    parser.add_argument("--project-root", default=None)
    args = parser.parse_args()

    try:
        allowed_files = json.loads(args.allowed_files_json)
        modified_files = json.loads(args.modified_files_json)
        baseline = json.loads(args.baseline_json)
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "error", "error": f"invalid JSON argument: {exc}"}, ensure_ascii=False))
        return 1

    if not isinstance(allowed_files, list) or not isinstance(modified_files, list):
        print(json.dumps(
            {"status": "error", "error": "--allowed-files-json / --modified-files-json must be JSON arrays"},
            ensure_ascii=False,
        ))
        return 1

    result = verify(allowed_files, modified_files, baseline, args.project_root)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
