#!/usr/bin/env python3
"""AI が決定した計画内容（候補 JSON）を検証し、計画書（`{feature}_plan.json`）へ書き出す。

`/forge:start-plan` Phase 4 のローカル操作入口。AI はタスクの意味内容（title・description・
acceptance_criteria 等）を決定するが、計画書ファイルへの書き込みと構造検証は本 script が担う
（REQ-020 FNC-002）。
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "plan"))
from plan_contract import save_plan, validate_plan_schema  # noqa: E402


def _read_and_consume_input(input_file):
    """候補 JSON を読み込み、成否に関わらず入力ファイルを削除する。"""
    path = Path(input_file)
    if path.is_absolute() or ".." in path.parts or path.parts[:2] != (".claude", ".temp"):
        return None, [
            "input-file は .claude/.temp/ 配下のプロジェクトルート相対パスである必要があります"
        ]
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle), []
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, [f"入力を JSON object として解析できません: {exc}"]
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _emit(payload):
    json.dump(payload, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


def run_cli(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--output-path", required=True)
    args = parser.parse_args(argv)

    raw, errors = _read_and_consume_input(args.input_file)
    if errors:
        _emit({"status": "error", "errors": errors})
        return 20

    errors = validate_plan_schema(raw)
    if errors:
        _emit({"status": "error", "errors": errors})
        return 20

    save_plan(args.output_path, raw)
    _emit({"status": "ok", "output_path": args.output_path})
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
