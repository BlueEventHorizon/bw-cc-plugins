#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PR の CI チェック状態を検査する read-only CLI。

`/anvil:create-pr` の Phase 6 が、CI の結果をどう扱うかを決めるために使う。

## なぜ script にするか

`gh pr checks` の終了コードは 3 つの異なる状態を同じ値へ畳み込む。

| 実際の状態                   | `gh pr checks` の終了コード |
| ---------------------------- | --------------------------- |
| 全チェック成功               | 0                           |
| 1 件以上失敗                 | 1                           |
| **チェックが未登録**         | **1**（`no checks reported`）|
| 実行中                       | 8                           |

push 直後は GitHub 側でチェックが登録される前に問い合わせが届くため、**未登録は必ず通る状態**である。
終了コードだけで分岐すると、これを「CI 失敗」として報告してしまう（実際に起きた: PR 作成直後の
問い合わせが `no checks reported` を返し、CI は後から成功したのに「未発火」と誤報告した）。

終了コードは 1 つの整数に状態を詰め込む器であり、状態を増やす余地がない。したがって本 script は
**状態を語で返す**。呼び出し側は語で分岐でき、新しい状態が増えても既存の分岐は壊れない。

## 出力

終了コードは、検査が成立した場合は常に 0（CI が失敗していることは script の異常ではない）。
標準出力に単一 JSON。

```json
{
  "status": "succeeded",
  "counts": {"total": 2, "pass": 2, "fail": 0, "pending": 0, "skipping": 0, "cancel": 0},
  "checks": [
    {"name": "test", "bucket": "pass", "state": "SUCCESS", "link": "https://..."}
  ],
  "failed_checks": [],
  "gh_exit_code": 0,
  "gh_stderr": ""
}
```

### `status` の値域

| 値             | 条件                                                  |
| -------------- | ----------------------------------------------------- |
| `succeeded`    | チェックが 1 件以上あり、すべて `pass` または `skipping` |
| `failed`       | 1 件以上が `fail`                                     |
| `cancelled`    | `fail` が無く、1 件以上が `cancel`                    |
| `pending`      | `fail` / `cancel` が無く、1 件以上が `pending`        |
| `not_reported` | チェックが 0 件                                       |

**`failed` は `pending` より優先する。** 失敗は確定した情報であり、残りを待っても覆らない。まだ
走っているチェックがあることは `counts.pending` で見える。

**`cancelled` を `failed` と別の語にする。** キャンセルは誰かが止めたことであってコードの欠陥では
なく、同じ語にすると利用者が「テストが落ちた」と読む。呼び出し側の行動（提示して確認）は同じでよい。

**`skipping` は `succeeded` に含める。** workflow の条件分岐で実行されなかったチェックは失敗ではない。
内訳は `counts.skipping` で見える。

### 待機はしない

`--watch` は使わず、**問い合わせた時点の状態だけ**を返す。`status: pending` / `not_reported` を受けて
待つか打ち切るかは呼び出し側（SKILL）が決める。進行の管理は決定論的に作れないため実行系へ移さない
（forge の `deterministic_generation_spec.md` §6「適用しない場面」）。

## 終了コードを判定に使わない

判定は stdout の JSON だけで行う。`gh pr checks` の終了コードの値域は `--json` を併用したときの挙動が
実測できていないため、判定の根拠にしない。追跡のため `gh_exit_code` と `gh_stderr` は出力に含める
（判定に使わないが、握りつぶさない）。

## 未実測の境界

**チェックが未登録のとき、`--json` 併用時の stdout が空文字列になるのか `[]` になるのかは未実測である。**
PR にチェックが登録される前の状態を再現できなかった。どちらか一方に決め打つと、外れた側で JSON の
パースに失敗して検査そのものが落ちる。したがって**両方を `not_reported` として受け付ける**。

## 未知の bucket はエラーにする

`gh` が返す bucket が既知の 5 値（`pass` / `fail` / `pending` / `skipping` / `cancel`）以外だった場合、
例外を投げて非ゼロ終了する。黙って捨てると、未知の状態を持つチェックが集計から消え、残りが全て
`pass` なら `succeeded` を返してしまう（`deterministic_generation_spec.md` §8 が
「許可リストに無い入力を、エラーを返さず黙って捨てる」を最も重い違反としている）。

## 依存

Python 標準ライブラリのみ。外部コマンドとして `gh` を呼ぶ。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

# `gh pr checks --json bucket` が返す値域。gh の実装（pkg/cmd/pr/checks）に対応する。
# ここに無い値が来たら、gh 側の値域が変わったということであり、集計から落とさずエラーにする。
_KNOWN_BUCKETS = ("pass", "fail", "pending", "skipping", "cancel")

# `gh pr checks --json` で要求するフィールド。link は失敗時に利用者へ示すために要る。
_JSON_FIELDS = "name,state,bucket,link"


class UnknownBucketError(RuntimeError):
    """`gh` が既知でない bucket を返した。集計に含められないためエラーにする。"""


def _run_gh(pr: str, repo: str) -> tuple[str, str, int]:
    """`gh pr checks` を実行し、(stdout, stderr, returncode) を返す。

    非ゼロ終了でも例外にしない。未登録（`no checks reported`）が非ゼロで返るため、
    終了コードを失敗の判定に使えない（module docstring 参照）。
    """
    proc = subprocess.run(
        ["gh", "pr", "checks", pr, "--repo", repo, "--json", _JSON_FIELDS],
        capture_output=True,
        text=True,
    )
    return proc.stdout, proc.stderr, proc.returncode


def parse_checks(stdout: str) -> list[dict]:
    """`gh pr checks --json` の stdout をチェックの配列へ変換する。

    空文字列は空配列として扱う。未登録のとき stdout が空になるか `[]` になるかは未実測であり、
    どちらでも同じ結果（チェック 0 件）へ落ちる必要があるため（module docstring 参照）。
    """
    text = stdout.strip()
    if not text:
        return []
    payload = json.loads(text)
    if not isinstance(payload, list):
        raise ValueError(
            f"gh pr checks --json が配列でない値を返しました: {type(payload).__name__}"
        )
    return payload


def count_buckets(checks: list[dict]) -> dict[str, int]:
    """bucket ごとの件数を数える。未知の bucket があれば例外を投げる。"""
    counts = {bucket: 0 for bucket in _KNOWN_BUCKETS}
    unknown = []
    for check in checks:
        bucket = check.get("bucket")
        if bucket in counts:
            counts[bucket] += 1
        else:
            unknown.append({"name": check.get("name"), "bucket": bucket})
    if unknown:
        raise UnknownBucketError(
            "gh pr checks が既知でない bucket を返しました: "
            f"{json.dumps(unknown, ensure_ascii=False)}. "
            f"既知の値域: {', '.join(_KNOWN_BUCKETS)}"
        )
    counts["total"] = len(checks)
    return counts


def decide_status(counts: dict[str, int]) -> str:
    """bucket の件数から状態語を決める。

    優先順位は failed > cancelled > pending > succeeded。確定した結果を、まだ確定していない
    ものより先に見る（module docstring「`status` の値域」参照）。
    """
    if counts["total"] == 0:
        return "not_reported"
    if counts["fail"] > 0:
        return "failed"
    if counts["cancel"] > 0:
        return "cancelled"
    if counts["pending"] > 0:
        return "pending"
    return "succeeded"


def inspect(stdout: str, stderr: str, returncode: int) -> dict:
    """`gh` の出力から状態語と内訳を組み立てる。"""
    checks = parse_checks(stdout)
    counts = count_buckets(checks)
    normalized = [
        {
            "name": check.get("name"),
            "bucket": check.get("bucket"),
            "state": check.get("state"),
            "link": check.get("link"),
        }
        for check in checks
    ]
    return {
        "status": decide_status(counts),
        "counts": counts,
        "checks": normalized,
        "failed_checks": [c for c in normalized if c["bucket"] in ("fail", "cancel")],
        "gh_exit_code": returncode,
        "gh_stderr": stderr.strip(),
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="PR の CI チェック状態を検査し、状態語を JSON で出力する（read-only）"
    )
    parser.add_argument("--pr", required=True, help="PR 番号")
    parser.add_argument("--repo", required=True, help="対象リポジトリ（OWNER/REPO）")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    stdout, stderr, returncode = _run_gh(args.pr, args.repo)
    result = inspect(stdout, stderr, returncode)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
