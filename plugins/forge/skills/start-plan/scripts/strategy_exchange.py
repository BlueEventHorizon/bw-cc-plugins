#!/usr/bin/env python3
"""`/forge:start-plan` と `plan-strategist` の間で、実装戦略の依頼と終了の値を受け渡す。

受け渡すのは識別値（出力先ディレクトリと feature 名）だけであり、依頼の中身も戦略書の本文も
prompt / return value に載せない。依頼は本 script が組み立てて置き、Agent は本 script から
パスを得て直接読む。戦略書は Agent が所定のパスへ直接書き、書き終えたら本 script で終了の値を
記録する。成否は呼び出し元が本 script で判定する。

置き場は計画書と同じディレクトリである。

- ``{feature}_strategy_request.json`` — 依頼（``open`` が書き、``check`` が消す）
- ``{feature}_strategy.md`` — 戦略書（Agent が書く。本 script は消さない）
- ``{feature}_strategy_result.json`` — 終了の値（``finish`` が書き、``check`` が消す）

終了の値は正常時の ``"0"`` だけであり、エラー値は持たない。``"0"`` が取れないことを異常とする。

## 終了コード

| code | 意味                             |
| ---- | -------------------------------- |
| 0    | 操作が完了した                   |
| 1    | 区別のない失敗（標準出力の ``errors`` に理由） |
| 2    | 引数を受理できない（``argparse``） |

Usage:
    python3 strategy_exchange.py open --output-dir DIR --feature NAME \\
        --design-doc PATH [...] [--requirement-doc PATH ...] [--rules-doc PATH ...]
    python3 strategy_exchange.py request-path --output-dir DIR --feature NAME
    python3 strategy_exchange.py finish --output-dir DIR --feature NAME
    python3 strategy_exchange.py check --output-dir DIR --feature NAME
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

EXIT_OK = "0"


def _emit(payload):
    json.dump(payload, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


def _paths(output_dir, feature):
    base = Path(output_dir).resolve()
    return {
        "dir": base,
        "request": base / f"{feature}_strategy_request.json",
        "strategy": base / f"{feature}_strategy.md",
        "result": base / f"{feature}_strategy_result.json",
    }


def _publish_json(path, payload):
    """同じディレクトリの一時ファイルへ書いてから置き換え、1 回の操作で公開する。"""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _absolute(paths):
    return [str(Path(p).resolve()) for p in paths]


def _file_error(exc):
    """ファイル操作の失敗を、終了コード 1 と標準出力の ``errors`` で返す。"""
    _emit({"status": "error", "errors": [f"ファイルを操作できません: {exc}"]})
    return 1


def cmd_open(args):
    paths = _paths(args.output_dir, args.feature)
    existing = paths["strategy"] if paths["strategy"].is_file() else None
    request = {
        "feature": args.feature,
        "requirement_docs": _absolute(args.requirement_doc or []),
        "design_docs": _absolute(args.design_doc),
        "rules_docs": _absolute(args.rules_doc or []),
        "existing_strategy": str(existing) if existing else None,
        "strategy_path": str(paths["strategy"]),
    }
    try:
        paths["dir"].mkdir(parents=True, exist_ok=True)
        # 前回の終了の値が残っていると、今回の策定が終わる前に check が成功と判定してしまう
        paths["result"].unlink(missing_ok=True)
        _publish_json(paths["request"], request)
    except OSError as exc:
        return _file_error(exc)
    _emit({"status": "ok"})
    return 0


def cmd_request_path(args):
    paths = _paths(args.output_dir, args.feature)
    if not paths["request"].is_file():
        _emit({"status": "error", "errors": [f"依頼が公開されていません: {paths['request']}"]})
        return 1
    _emit({"status": "ok", "path": str(paths["request"])})
    return 0


def cmd_finish(args):
    paths = _paths(args.output_dir, args.feature)
    strategy = paths["strategy"]
    if not strategy.is_file() or strategy.stat().st_size == 0:
        _emit({"status": "error", "errors": [f"戦略書が書かれていません: {strategy}"]})
        return 1
    if paths["result"].exists():
        _emit({"status": "error", "errors": [f"終了の値は既に記録されています: {paths['result']}"]})
        return 1
    try:
        _publish_json(paths["result"], {"exit": EXIT_OK})
    except OSError as exc:
        return _file_error(exc)
    _emit({"status": "ok"})
    return 0


def _read_exit(result_path):
    try:
        with open(result_path, encoding="utf-8") as fh:
            return json.load(fh).get("exit")
    except (OSError, ValueError, AttributeError):
        return None


def cmd_check(args):
    paths = _paths(args.output_dir, args.feature)
    exit_value = _read_exit(paths["result"]) if paths["result"].is_file() else None

    # 成否にかかわらず、この受け渡しのために置いたものを片付ける。戦略書は残す
    try:
        paths["request"].unlink(missing_ok=True)
        paths["result"].unlink(missing_ok=True)
    except OSError as exc:
        return _file_error(exc)

    if exit_value != EXIT_OK:
        _emit({
            "status": "error",
            "errors": ["plan-strategist が正常に書き終えていません（終了の値が記録されていない）"],
        })
        return 1
    _emit({"status": "ok", "strategy_path": str(paths["strategy"])})
    return 0


def _add_identity(sub):
    sub.add_argument("--output-dir", required=True)
    sub.add_argument("--feature", required=True)


def build_parser():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="command", required=True)

    p_open = subs.add_parser("open")
    _add_identity(p_open)
    # 要件定義書を持たないプロジェクトがあるため任意。設計書は戦略の前提であり必須
    p_open.add_argument("--requirement-doc", action="append")
    p_open.add_argument("--design-doc", action="append", required=True)
    p_open.add_argument("--rules-doc", action="append")
    p_open.set_defaults(func=cmd_open)

    for name, func in (
        ("request-path", cmd_request_path),
        ("finish", cmd_finish),
        ("check", cmd_check),
    ):
        sub = subs.add_parser(name)
        _add_identity(sub)
        sub.set_defaults(func=func)
    return parser


def run_cli(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(run_cli())
