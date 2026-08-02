#!/usr/bin/env python3
"""review: レビューの終端判定と終了通知の要否を決める単一の出口 CLI。

レビューが終わる経路は複数ある（承認・未対応所見を残した打ち切り・失敗の確定・
利用者の中止）。そのすべてで本スクリプトを通し、返る `notify_backend` に従って
終了通知を発行する。経路ごとに散文で発行を指示する形は採らない。

理由: 終了通知の発行漏れは、資源を持たないバックエンド（msg-review）では何も
起きず、資源を自前で持つバックエンドを接続して初めてリークとして現れる。露見が
遅れる失敗であるため、守られることを期待する契約ではなく単一の出口へ集約する
（同型の失敗を 2 度起こした送信・起床・待機を `send_and_await_reply.py` へ
畳んだのと同じ扱い。ADR-066 §2.4）。

判定（`--judgment`）の値のうち `approved` / `findings` / `failure` は
バックエンドが返す契約上の判定であり、`interrupted` は利用者の中止を本体が
表現するための本体由来の値である（バックエンドは返さない）。

使い方:
    python3 finalize_review.py --judgment approved --review-id <id> --backend <name>
    python3 finalize_review.py --judgment findings --confirmed-fix-count 0 \
        --review-id <id> --backend <name>
"""

import argparse
import json

# 本体が受け取りうる終端の判定と、それが対応する終了経路。
# findings のみ confirmed_fix の件数で終端かどうかが決まるため、ここには含めない。
TERMINAL_PATHS = {
    "approved": "approved",
    "failure": "failure",
    "interrupted": "interrupted",
}

# findings を受けたとき、今回実施する修正が 1 件も無ければ再依頼せず終える
# （対応しない所見を残したまま再レビューを求めると、同じ所見を指摘され続けて
# 往復上限まで収束しないため）。承認とは別の終端として区別する。
HALTED_PATH = "halted_with_open_findings"

CONTINUE_PATH = "continue"


def decide(judgment: str, review_id: str, backend: str, confirmed_fix_count: int | None) -> dict:
    """終端かどうかと、終了通知の宛先を決める。

    findings で `confirmed_fix_count` が省略された場合は判定できないため
    ValueError を送出する（既定値を置くと、渡し忘れが「終端」または「継続」の
    どちらかへ黙って倒れる）。
    """
    if judgment == "findings":
        if confirmed_fix_count is None:
            raise ValueError("--judgment findings では --confirmed-fix-count が必須です")
        if confirmed_fix_count < 0:
            raise ValueError("--confirmed-fix-count に負の値は指定できません")
        path = CONTINUE_PATH if confirmed_fix_count > 0 else HALTED_PATH
    else:
        path = TERMINAL_PATHS[judgment]

    terminal = path != CONTINUE_PATH

    # 終端なら経路を問わず通知する。資源を持たないバックエンドは無視してよい
    # 契約であり（ADR-065）、発行側で「通知が要る経路か」を選別しない。
    notify = {"backend": backend, "review_id": review_id} if terminal else None

    return {"terminal": terminal, "path": path, "notify_backend": notify}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="レビューの終端判定と終了通知の要否を決める単一の出口 CLI",
    )
    parser.add_argument(
        "--judgment",
        required=True,
        choices=["approved", "findings", "failure", "interrupted"],
    )
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--backend", required=True)
    parser.add_argument(
        "--confirmed-fix-count",
        type=int,
        default=None,
        help="今回実施すると確定した修正の件数（--judgment findings で必須）",
    )
    args = parser.parse_args()

    try:
        result = decide(args.judgment, args.review_id, args.backend, args.confirmed_fix_count)
    except ValueError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
