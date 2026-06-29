#!/usr/bin/env python3
"""target_files の dprint check ベースラインを取得する。

refs.yaml の target_files に対して `dprint check` を実行し、
pre-existing な format 違反の有無を {session_dir}/baseline_violations.json に保存する。
fixer は修正後の構文検証で baseline=true のファイルでは
「pre-existing 違反あり」と判定して構文検証をスキップする (rollback しない)。

これにより fixer が自身の修正と無関係な既存違反を毎回判別する責任から解放される。

Usage:
    python3 check_baseline_violations.py <session_dir>

出力 (stdout JSON):
    {
      "status": "ok",
      "session_dir": "...",
      "checked": N,
      "pre_existing_count": N,
      "baseline_path": "<session_dir>/baseline_violations.json"
    }

baseline_violations.json の schema:
    {
      "tool": "dprint",           // 検出器 (dprint 不在時は null)
      "tool_version": "0.54.0",   // 検出器バージョン
      "files": {
        "<target_file_path>": {
          "has_violations": true | false,
          "exit_code": 0 | 20 | null    // dprint 不在時は null
        },
        ...
      }
    }

設計判断:
- 違反の具体的な行番号は記録しない (dprint の出力形式は不安定、過剰精度より単純さ優先)
- fixer は「baseline で違反あり / なし」のフラグだけで判断する
- dprint 不在環境では全ファイル has_violations=false の空 baseline を返す (fail-safe)
- 既存 baseline_violations.json は無条件で上書きする (session ライフサイクル内で再取得しない前提)
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR.parent))

from session.yaml_utils import read_yaml  # noqa: E402


def _dprint_available():
    """dprint コマンドが PATH 上にあるか確認する。"""
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


def _check_file(file_path):
    """単一ファイルに対する dprint check の結果を取得する。

    dprint の exit code 解釈:
      0  → 違反なし (ok)
      14 → ファイルが dprint.jsonc の includes パターンに含まれず、対象外
            ("no files found to format")。違反ではなく単に検査範囲外なので false 扱い
      20 → format 違反あり (has_violations=true)
      その他 → エラー扱い (環境依存の問題等)。安全側に倒し「違反なし」とする
              (fixer 側で確実に format させたい場合は別途検証する設計)

    Returns:
        dict: {"has_violations": bool, "exit_code": int | null}
    """
    try:
        proc = subprocess.run(
            ["dprint", "check", file_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # 「pre-existing 違反あり」は dprint 公式の violation exit code (20) に限定する
        # exit 14 (no files found) は「検査対象外」なので違反ではない
        return {
            "has_violations": proc.returncode == 20,
            "exit_code": proc.returncode,
        }
    except (OSError, subprocess.TimeoutExpired):
        return {"has_violations": False, "exit_code": None}


def _load_target_files(session_dir):
    """refs.yaml から target_files を読む。"""
    refs_path = Path(session_dir) / "refs.yaml"
    if not refs_path.is_file():
        return []
    try:
        data = read_yaml(str(refs_path))
    except (OSError, ValueError):
        return []
    targets = data.get("target_files") if isinstance(data, dict) else None
    if not isinstance(targets, list):
        return []
    return [t for t in targets if isinstance(t, str) and t]


def run(session_dir):
    session_path = Path(session_dir)
    if not session_path.is_dir():
        return {
            "status": "error",
            "error": f"session dir not found: {session_dir}",
        }

    target_files = _load_target_files(session_dir)

    if not _dprint_available():
        baseline = {
            "tool": None,
            "tool_version": None,
            "files": {
                f: {"has_violations": False, "exit_code": None}
                for f in target_files
            },
        }
        (session_path / "baseline_violations.json").write_text(
            json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {
            "status": "ok",
            "session_dir": session_dir,
            "checked": 0,
            "pre_existing_count": 0,
            "baseline_path": str(session_path / "baseline_violations.json"),
            "note": "dprint not available; empty baseline written",
        }

    files_result = {}
    pre_existing_count = 0
    for f in target_files:
        result = _check_file(f)
        files_result[f] = result
        if result["has_violations"]:
            pre_existing_count += 1

    baseline = {
        "tool": "dprint",
        "tool_version": _dprint_version(),
        "files": files_result,
    }
    (session_path / "baseline_violations.json").write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "status": "ok",
        "session_dir": session_dir,
        "checked": len(target_files),
        "pre_existing_count": pre_existing_count,
        "baseline_path": str(session_path / "baseline_violations.json"),
    }


def main():
    if len(sys.argv) != 2:
        json.dump(
            {
                "status": "error",
                "error": "Usage: check_baseline_violations.py <session_dir>",
            },
            sys.stderr,
        )
        sys.stderr.write("\n")
        sys.exit(1)

    result = run(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
