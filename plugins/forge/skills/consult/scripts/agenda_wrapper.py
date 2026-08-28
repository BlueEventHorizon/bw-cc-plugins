#!/usr/bin/env python3
"""consult: 起点（review/consult）から agenda.json の置き場・config を解決し、
`agenda_store.py` への委譲までを 1 回の呼び出しに包む CLI ラッパー。

consult（呼び出し元 SKILL）が渡すのは起点名（と consult 起点の場合はセッション ID）・
サブコマンド・そのサブコマンド固有の内容（`start` の items・structural_judgment、
`record` の item-id・パッチ）だけである。記録の置き場（[agenda:DES-075](
../../../../../docs/specs/consult/agenda/design/DES-075_agenda_mechanism_design.md) §7）・
`config.item_fields`/`config.severity_field` の起点別対応は consult 自身の事情であり、
`agenda_store.py`（起点を知らない汎用機構。agenda:REQ-019 FNC-009）には渡さない値である。
この対応を SKILL.md の本文（散文・表・JSON 例）へ複製すると、`agenda_store.py` 側の
スキーマ変更に追随できず陳腐化する（実例: `config.requires_verification` 撤回時、
複数箇所の複製を手で直す事故が起きた）。対応は本ラッパー 1 箇所へ持ち、SKILL.md は
本ラッパーを呼ぶだけで置き場・config の値に一切触れない。

`pending` はファイル不在を失敗として扱わない（`{"status": "ok", "exists": false}` を
返す）。呼び出し元にとって「まだ記録が無い」は正常系（新規に始める）であり、
`test -f` のような存在確認を呼び出し元に強いない。

Usage:
    python3 agenda_wrapper.py --origin review pending
    python3 agenda_wrapper.py --origin review start --input-file <candidate.json>
    python3 agenda_wrapper.py --origin review record --item-id 01 --input-file <patch.json>
    python3 agenda_wrapper.py --origin review next
    python3 agenda_wrapper.py --origin review finish
    python3 agenda_wrapper.py --origin consult --session-id <id> <同上のサブコマンド>
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

_AGENDA_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts" / "agenda"
sys.path.insert(0, str(_AGENDA_SCRIPTS_DIR))

import agenda_store  # noqa: E402

_REVIEW_PATH = ".claude/.temp/review/agenda.json"
_REVIEW_CONFIG = {"item_fields": ["severity"], "severity_field": "severity"}
_CONSULT_CONFIG = {"item_fields": [], "severity_field": None}


def resolve_target(origin: str, session_id: str | None):
    """`(path, config, error)` を返す。エラー時は `path`/`config` が `None`。"""
    if origin == "review":
        return _REVIEW_PATH, _REVIEW_CONFIG, None
    if origin == "consult":
        if not session_id:
            return None, None, "--origin consult には --session-id が必要です"
        return f".claude/.temp/consult/{session_id}/agenda.json", _CONSULT_CONFIG, None
    return None, None, f"未知の --origin です: {origin!r}"


def _handle_pending(path: str) -> dict:
    if not Path(path).is_file():
        return {"status": "ok", "exists": False, "pending_item_ids": [], "remaining_count": 0}
    result = agenda_store.handle_pending(argparse.Namespace(path=path))
    result["exists"] = True
    return result


def _handle_start(path: str, config: dict, input_file: str) -> dict:
    """呼び出し元の候補 JSON（`structural_judgment`・`items` のみでよい）へ
    起点解決済みの `config` を注入してから `agenda_store.py` の `start` へ委譲する。
    呼び出し元が `config` を含めていた場合も、起点から解決した値で上書きする
    （置き場と同様、config も呼び出し元が自分で組み立てる値ではないため）。
    """
    try:
        with Path(input_file).open(encoding="utf-8") as handle:
            candidate = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"status": "error", "message": f"--input-file を JSON として読み込めません: {exc}"}
    if not isinstance(candidate, dict):
        return {"status": "error", "message": "--input-file の内容は object である必要があります"}

    candidate["config"] = dict(config)

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        json.dump(candidate, tmp, ensure_ascii=False)
        tmp_path = tmp.name
    try:
        return agenda_store.handle_start(argparse.Namespace(path=path, input_file=tmp_path))
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _handle_record(path: str, item_id: str, input_file: str) -> dict:
    return agenda_store.handle_record(
        argparse.Namespace(path=path, item_id=item_id, input_file=input_file)
    )


def _handle_next(path: str) -> dict:
    return agenda_store.handle_next(argparse.Namespace(path=path))


def _handle_finish(path: str) -> dict:
    return agenda_store.handle_finish(argparse.Namespace(path=path))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agenda_wrapper.py")
    parser.add_argument("--origin", required=True, choices=["review", "consult"])
    parser.add_argument("--session-id", default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("pending")
    subparsers.add_parser("next")
    subparsers.add_parser("finish")

    p_start = subparsers.add_parser("start")
    p_start.add_argument("--input-file", required=True)

    p_record = subparsers.add_parser("record")
    p_record.add_argument("--item-id", required=True)
    p_record.add_argument("--input-file", required=True)

    return parser


def run(args: argparse.Namespace) -> dict:
    path, config, error = resolve_target(args.origin, args.session_id)
    if error:
        return {"status": "error", "message": error}

    if args.command == "pending":
        result = _handle_pending(path)
    elif args.command == "start":
        result = _handle_start(path, config, args.input_file)
    elif args.command == "record":
        result = _handle_record(path, args.item_id, args.input_file)
    elif args.command == "next":
        result = _handle_next(path)
    elif args.command == "finish":
        result = _handle_finish(path)
    else:
        return {"status": "error", "message": f"未知のコマンドです: {args.command!r}"}

    # 呼び出し元（consult）は自分では置き場を組み立てないため、以降（表示物を開く等）で
    # 使えるよう解決済みの path を結果へ含める。
    result.setdefault("path", path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run(args)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") in ("ok", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
