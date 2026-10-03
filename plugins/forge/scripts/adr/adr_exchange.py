#!/usr/bin/env python3
"""`/forge:write-adr` と `adr-writer` の間で、ADR の依頼と判定を受け渡す。

受け渡すのは識別値（出力先ディレクトリ `adr_dir` と `request_id`）だけであり、依頼の中身も
ADR の本文も prompt / return value に載せない。依頼は本 script が入力ファイルから組み立てて
置き、Agent は本 script からパスを得て直接読む。ADR は Agent が記載先のパスへ直接書き、
書き終えたら本 script で判定を記録する。判定は呼び出し元が本 script で取得する。

ADR は feature ごとに 1 つの ADR ファイルへ、すべて書く。記載先は ``open`` が決める。

- ``adr_dir`` に ADR ファイル（``ADR-*.md``）が 1 つある: そのファイル
- 無い: ``{adr_dir}/{adr_id}_{feature}.md``（``--adr-id`` が必須。feature 名の ``-`` は ``_`` に直す）
- 2 つ以上ある: 失敗する（どれに書くかを推測しない）

置き場は ADR の出力先ディレクトリ（``docs/specs/<feature>/adr/``）である。

- ``adr_request_{request_id}.json`` — 依頼（``open`` が書き、``check`` が消す）
- ``adr_result_{request_id}.json`` — 判定（``finish`` が書き、``check`` が消す）
- ADR ファイル — Agent が書く。本 script は消さない

判定は閉じた 3 値（``created`` / ``rejected`` / ``insufficient``）である。棄却と不足はエラーでは
なく、判定できる結果であり、終了コードは ``0`` である。判定が記録されていないこと（Agent が
最後まで終えられなかったこと）を異常とする。

## 終了コード

| code | 意味                                           |
| ---- | ---------------------------------------------- |
| 0    | 操作が完了した                                 |
| 1    | 区別のない失敗（標準出力の ``errors`` に理由） |
| 2    | 引数を受理できない（``argparse``）             |

Usage:
    python3 adr_exchange.py open --kind {approval-record|judgement|update} --feature NAME \\
        --adr-dir DIR [--adr-id ADR-NNN] \\
        (--decision-file PATH | --change-file PATH) \\
        [--context-file PATH] [--alternatives-file PATH] [--approval-quote-file PATH] \\
        [--related-doc PATH ...]
    python3 adr_exchange.py request-path --adr-dir DIR --request-id ID
    python3 adr_exchange.py finish --adr-dir DIR --request-id ID \\
        --verdict {created|rejected|insufficient}
    python3 adr_exchange.py check --adr-dir DIR --request-id ID
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path

EXIT_OK = "0"
KINDS = ("approval-record", "judgement", "update")
VERDICTS = ("created", "rejected", "insufficient")

_ADR_ID_RE = re.compile(r"^ADR-\d{3,}$")
_TOPIC_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
_REQUEST_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def _emit(payload):
    json.dump(payload, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


def _error(*messages):
    _emit({"status": "error", "errors": list(messages)})
    return 1


def _adr_id(value):
    if not _ADR_ID_RE.match(value):
        raise argparse.ArgumentTypeError(f"ADR-NNN の形ではない: {value!r}")
    return value


def _request_id(value):
    if not _REQUEST_ID_RE.match(value):
        raise argparse.ArgumentTypeError(f"生成された request_id の形ではない: {value!r}")
    return value


def _paths(adr_dir, request_id):
    base = Path(adr_dir).resolve()
    return {
        "dir": base,
        "request": base / f"adr_request_{request_id}.json",
        "result": base / f"adr_result_{request_id}.json",
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


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _remove_inputs(paths):
    """読み終えた入力ファイルを削除する。削除できなくても、依頼の成否には影響させない。"""
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError as exc:
            print(f"入力ファイルを削除できません: {p}: {exc}", file=sys.stderr)


def cmd_open(args):
    text_inputs = (
        ("decision", args.decision_file),
        ("context", args.context_file),
        ("alternatives", args.alternatives_file),
        ("approval_quote", args.approval_quote_file),
        ("change", args.change_file),
    )
    input_files = [path for _, path in text_inputs if path]
    try:
        return _open(args, text_inputs)
    finally:
        _remove_inputs(input_files)


def _decide_adr_path(adr_dir, adr_id, feature):
    """記載先を決める。(記載先, 既存の ADR ファイルの内容のハッシュ, エラーの理由) を返す。

    ADR ファイルが無ければハッシュは None。決められなければ記載先が None になる。
    """
    existing = sorted(adr_dir.glob("ADR-*.md")) if adr_dir.is_dir() else []
    if len(existing) > 1:
        names = ", ".join(p.name for p in existing)
        return None, None, (
            f"同じ feature の ADR ファイルが 2 つ以上ある（1 つのファイルに書く決定に反する）: {names}"
        )
    if existing:
        try:
            return existing[0], _sha256(existing[0]), None
        except OSError as exc:
            return None, None, f"ADR ファイルを読めません: {exc}"
    if not adr_id:
        return None, None, "ADR ファイルがまだ無いため、--adr-id が必要"
    topic = feature.lower().replace("-", "_")
    if not _TOPIC_RE.match(topic):
        return None, None, f"feature 名からファイル名を作れない: {feature!r}"
    return adr_dir / f"{adr_id}_{topic}.md", None, None


def _open(args, text_inputs):
    adr_dir = Path(args.adr_dir).resolve()

    texts = {}
    for field, path in text_inputs:
        if path is None:
            texts[field] = None
            continue
        try:
            texts[field] = Path(path).read_text(encoding="utf-8")
        except (OSError, ValueError) as exc:
            return _error(f"入力ファイルを読めません: {path}: {exc}")

    adr_path, baseline, reason = _decide_adr_path(adr_dir, args.adr_id, args.feature)
    if adr_path is None:
        return _error(reason)

    request_id = uuid.uuid4().hex[:12]
    request = {
        "request_id": request_id,
        "kind": args.kind,
        "feature": args.feature,
        "adr_dir": str(adr_dir),
        "adr_path": str(adr_path),
        "baseline_sha256": baseline,
        "related_docs": [str(Path(p).resolve()) for p in args.related_doc or []],
        **texts,
    }
    try:
        adr_dir.mkdir(parents=True, exist_ok=True)
        _publish_json(adr_dir / f"adr_request_{request_id}.json", request)
    except OSError as exc:
        return _error(f"ファイルを操作できません: {exc}")
    _emit({"status": "ok", "request_id": request_id})
    return 0


def cmd_request_path(args):
    paths = _paths(args.adr_dir, args.request_id)
    if not paths["request"].is_file():
        return _error(f"依頼が公開されていません: {paths['request']}")
    _emit({"status": "ok", "path": str(paths["request"])})
    return 0


def _state_errors(request, verdict):
    """判定と ADR ファイルの状態が対応しているかを検査する。対応しなければ理由の一覧を返す。

    2 つの結果（Agent が記録する判定と、Agent が書いた ADR ファイル）の間の対応関係であり、
    script が組み立てても自動的には満たされないため、ここで検査する。
    """
    adr_path = Path(request["adr_path"])
    baseline = request["baseline_sha256"]

    if baseline is None:
        # open 時点で ADR ファイルが無かった
        if verdict == "created":
            if not (adr_path.is_file() and adr_path.stat().st_size > 0):
                return [f"判定が created だが、記載先に ADR ファイルが書かれていない: {adr_path}"]
        elif adr_path.exists():
            return [f"判定が {verdict} だが、記載先に ADR ファイルが存在する: {adr_path}"]
        return []

    try:
        changed = _sha256(adr_path) != baseline
    except OSError as exc:
        return [f"ADR ファイルを読めません: {exc}"]
    if verdict == "created" and not changed:
        return ["判定が created だが、ADR ファイルの内容が依頼時から変わっていない"]
    if verdict != "created" and changed:
        return [f"判定が {verdict} だが、ADR ファイルの内容が依頼時から変わっている"]
    return []


def cmd_finish(args):
    paths = _paths(args.adr_dir, args.request_id)
    if not paths["request"].is_file():
        return _error(f"依頼が公開されていません: {paths['request']}")
    try:
        request = _load_json(paths["request"])
    except (OSError, ValueError) as exc:
        return _error(f"依頼を読めません: {exc}")
    if paths["result"].exists():
        return _error(f"判定は既に記録されています: {paths['result']}")

    errors = _state_errors(request, args.verdict)
    if errors:
        return _error(*errors)
    try:
        _publish_json(paths["result"], {"exit": EXIT_OK, "verdict": args.verdict})
    except OSError as exc:
        return _error(f"ファイルを操作できません: {exc}")
    _emit({"status": "ok"})
    return 0


def _read_result(path):
    """判定ファイルから (exit, verdict) を返す。取れない・壊れている場合は None。"""
    if not path.is_file():
        return None
    try:
        data = _load_json(path)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data.get("exit"), data.get("verdict")


def cmd_check(args):
    paths = _paths(args.adr_dir, args.request_id)
    result = _read_result(paths["result"])

    # 成否にかかわらず、この受け渡しのために置いたものを片付ける。ADR ファイルは残す
    try:
        paths["request"].unlink(missing_ok=True)
        paths["result"].unlink(missing_ok=True)
    except OSError as exc:
        return _error(f"ファイルを操作できません: {exc}")

    if result is None or result[0] != EXIT_OK or result[1] not in VERDICTS:
        return _error("adr-writer が正常に判定を記録していない（判定が記録されていない）")
    _emit({"status": "ok", "verdict": result[1]})
    return 0


def _add_identity(sub):
    sub.add_argument("--adr-dir", required=True)
    sub.add_argument("--request-id", required=True, type=_request_id)


def build_parser():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="command", required=True)

    p_open = subs.add_parser("open")
    p_open.add_argument("--kind", required=True, choices=KINDS)
    p_open.add_argument("--feature", required=True)
    p_open.add_argument("--adr-dir", required=True)
    p_open.add_argument("--adr-id", type=_adr_id)
    p_open.add_argument("--decision-file")
    p_open.add_argument("--context-file")
    p_open.add_argument("--alternatives-file")
    p_open.add_argument("--approval-quote-file")
    p_open.add_argument("--change-file")
    p_open.add_argument("--related-doc", action="append")
    p_open.set_defaults(func=cmd_open)

    p_request_path = subs.add_parser("request-path")
    _add_identity(p_request_path)
    p_request_path.set_defaults(func=cmd_request_path)

    p_finish = subs.add_parser("finish")
    _add_identity(p_finish)
    p_finish.add_argument("--verdict", required=True, choices=VERDICTS)
    p_finish.set_defaults(func=cmd_finish)

    p_check = subs.add_parser("check")
    _add_identity(p_check)
    p_check.set_defaults(func=cmd_check)
    return parser


def _validate_open(parser, args):
    """類型ごとに必須の入力ファイルが揃っているかを検査する（引数の形の検査）。"""
    if args.kind == "update":
        name, value = "--change-file", args.change_file
    else:
        name, value = "--decision-file", args.decision_file
    if not value:
        parser.error(f"kind={args.kind} には {name} が必要")


def run_cli(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "open":
        _validate_open(parser, args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(run_cli())
