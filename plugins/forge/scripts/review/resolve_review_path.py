#!/usr/bin/env python3
"""読み出せる状態かを判定し、JSON の絶対パスを返す。JSON 本文は返さない。

agent は返されたパスのファイルを直接読む。成否の判定は本 script が行い、AI に判定させない。
標準出力は ``{"path": 絶対パス}`` の JSON object 1 つである（``inputs`` を除く）。``project_root``
は解決してから使うので、作業ディレクトリを変えても同じ絶対パスが得られる。

現在受け付ける ``--kind`` は次の 4 つである。

- ``request`` — 依頼。``<review_id>/`` と ``<round_number>/`` が実在し、``review_request.json``
  が公開されているときだけパスを返す。公開前の依頼のパスは返さない
- ``findings`` — reviewer の所見の結果。``review_result.json`` の状態を判定する
- ``evaluations`` — evaluator の評価の結果。``evaluate_result.json`` の状態を、所見の結果と
  同じ表で判定する
- ``inputs`` — evaluator の入力。``request`` と ``findings`` の両方を判定し、標準出力は
  ``{"request": 絶対パス, "findings": 絶対パス}`` である。片方でも失敗すれば失敗し、``errors`` に
  両方の理由を入れる

結果（``findings`` / ``evaluations``）の判定は次の表のとおりである。

  | 結果 | ``exit``   | 動作                                           |
  | ---- | ---------- | ---------------------------------------------- |
  | ある | ``"0"``    | パスを返す                                     |
  | ある | エラー値   | 失敗する。``errors`` にエラー値を入れる        |
  | ある | 無い       | 失敗する。``errors`` に封緘されていない旨      |
  | 無い | —          | 失敗する。``errors`` に結果が無い旨            |

本 script は REQ-029 の FNC-302・311 の実装（DES-084 §6.5、DES-083 §6.4）である。

## 終了コード

| code | 意味                                                  |
| ---- | ----------------------------------------------------- |
| 0    | 読み出せる（標準出力に ``path``。``inputs`` は ``request`` と ``findings``） |
| 1    | 読み出せない（標準出力の ``errors`` に理由）          |
| 2    | 引数を受理できない（``argparse``）                    |

Usage:
    python3 resolve_review_path.py PROJECT_ROOT REVIEW_ID ROUND_NUMBER \\
        --kind {request,findings,evaluations,inputs}
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_common  # noqa: E402


def _missing_round(args):
    """ラウンドの置き場が実在しないときの理由を返す。実在すれば ``None``。"""
    return review_common.missing_round(args.project_root, args.review_id, args.round_number)


def _request(args):
    """依頼のパスと、返せないときの理由を ``(path, reason)`` で返す。"""
    reason = _missing_round(args)
    if reason:
        return None, reason
    path = review_common.review_dir(args.project_root, args.review_id) / review_common.REQUEST_FILE
    if not path.is_file():
        return None, f"依頼が公開されていません: review_id={args.review_id}"
    return path, None


def _result(args, file_name, label):
    """結果のパスと、返せないときの理由を ``(path, reason)`` で返す。"""
    reason = _missing_round(args)
    if reason:
        return None, reason
    round_path = review_common.round_dir(args.project_root, args.review_id, args.round_number)
    reason = review_common.result_problem(round_path, file_name, label, args.round_number)
    if reason:
        return None, reason
    return round_path / file_name, None


def _findings(args):
    return _result(args, review_common.RESULT_FILE, "所見の結果")


def _evaluations(args):
    return _result(args, review_common.EVALUATION_FILE, "評価の結果")


def _single(resolve):
    """1 つのパスを返す ``--kind`` の実装を作る。"""

    def command(args):
        path, reason = resolve(args)
        if reason:
            return review_common.error(reason)
        review_common.emit({"path": str(path)})
        return 0

    return command


def cmd_resolve_inputs(args):
    """依頼と所見の両方を判定する。片方でも失敗すれば、両方の理由を返す。"""
    request, request_reason = _request(args)
    findings, findings_reason = _findings(args)
    reasons = [r for r in (request_reason, findings_reason) if r]
    if reasons:
        # ラウンドの置き場が無いときは両方が同じ理由になるので、重複は 1 つにする
        return review_common.error(*dict.fromkeys(reasons))
    review_common.emit({"request": str(request), "findings": str(findings)})
    return 0


# --kind ごとの判定。種類を足すときはここへ足し、build_parser の choices は表から導く
RESOLVERS = {
    "request": _single(_request),
    "findings": _single(_findings),
    "evaluations": _single(_evaluations),
    "inputs": cmd_resolve_inputs,
}


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root")
    parser.add_argument("review_id")
    parser.add_argument("round_number", type=int)
    parser.add_argument("--kind", required=True, choices=list(RESOLVERS))
    return parser


def run_cli(argv=None):
    args = build_parser().parse_args(argv)
    return RESOLVERS[args.kind](args)


if __name__ == "__main__":
    raise SystemExit(run_cli())
