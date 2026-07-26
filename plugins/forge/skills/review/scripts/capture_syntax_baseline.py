#!/usr/bin/env python3
"""review: 修正前 dprint check ベースライン取得 CLI。

`/forge:review` パイプラインの `check_baseline_violations.py` の dprint 判定ロジック
（exit code 0/14/20 の解釈、dprint 未インストール時の fail-safe）をそのまま踏襲するが、
`session_dir`/`refs.yaml` への結合を持たない（REQ-012 §2.2 により review は
session_dir ベースの review パイプラインと結合しないため）。プレーンなファイルパスの
リストを直接受け取り、結果を標準出力の JSON として返す（ファイルへの書き込みは行わない）。

Usage:
    python3 capture_syntax_baseline.py --files-json '["a.md", "b.py"]' [--project-root <path>]
"""

import argparse
import json
import shutil
import subprocess


def _dprint_available():
    return shutil.which("dprint") is not None


def _dprint_version():
    try:
        proc = subprocess.run(
            ["dprint", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _check_file(file_path, cwd):
    """単一ファイルに対する dprint check の結果を取得する。

    dprint の exit code 解釈（check_baseline_violations.py と同一）:
      0  → 違反なし
      14 → dprint.jsonc の includes 対象外（検査対象外であり違反ではない）
      20 → format 違反あり (has_violations=true)
      その他 → 環境依存の問題として安全側に倒し「違反なし」とする

    Returns:
        dict: {"has_violations": bool, "exit_code": int | None}
    """
    try:
        proc = subprocess.run(
            ["dprint", "check", file_path],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )
        return {
            "has_violations": proc.returncode == 20,
            "exit_code": proc.returncode,
        }
    except (OSError, subprocess.TimeoutExpired):
        return {"has_violations": False, "exit_code": None}


def capture_baseline(files: list[str], project_root: str | None = None) -> dict:
    if not _dprint_available():
        return {
            "status": "ok",
            "tool": None,
            "tool_version": None,
            "files": {f: {"has_violations": False, "exit_code": None} for f in files},
            "note": "dprint not available; empty baseline returned",
        }

    files_result = {}
    for f in files:
        files_result[f] = _check_file(f, project_root)

    return {
        "status": "ok",
        "tool": "dprint",
        "tool_version": _dprint_version(),
        "files": files_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="修正前 dprint check ベースライン取得 CLI",
    )
    parser.add_argument("--files-json", required=True, help="対象ファイルパスの JSON 配列")
    parser.add_argument("--project-root", default=None, help="dprint 実行時の作業ディレクトリ")
    args = parser.parse_args()

    try:
        files = json.loads(args.files_json)
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "error", "error": f"invalid --files-json: {exc}"}, ensure_ascii=False))
        return 1
    if not isinstance(files, list):
        print(json.dumps({"status": "error", "error": "--files-json must be a JSON array"}, ensure_ascii=False))
        return 1

    result = capture_baseline(files, args.project_root)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
