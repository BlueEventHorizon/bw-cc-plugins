#!/usr/bin/env python3
"""そのレビューの保持物を、依頼・所見・評価ともにすべて削除する。

``<project_root>/.temp/review/<review_id>/`` をディレクトリごと削除する。置き場が無くても成功する。
削除できないときは失敗する（エラーを握りつぶさない）。``review_id`` はディレクトリ名 1 つでなければ
ならない。パス区切りや ``.`` / ``..`` を含み ``.temp/review/`` の外を指しうる値は、何も削除せず拒む
（既存の script は ``review_id`` を検証しないが、本 script は削除を行うため拒む）。

本 script は REQ-029 の FNC-302・318 の実装（DES-083 §6.7）である。

## 終了コード

| code | 意味                                                                          |
| ---- | ----------------------------------------------------------------------------- |
| 0    | 削除した、または置き場が無かった（標準出力は ``{}``）                         |
| 1    | 区別のない失敗（標準出力の ``errors`` に理由。削除できない、review_id が不正） |
| 2    | 引数を受理できない（``argparse``）                                            |

Usage:
    python3 delete_review.py PROJECT_ROOT REVIEW_ID
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_common  # noqa: E402


def _invalid_review_id(review_id):
    """review_id がディレクトリ名 1 つでないときの理由を返す。正しければ ``None``。"""
    if review_id in ("", ".", "..") or "/" in review_id or "\\" in review_id or "\0" in review_id:
        return f"review_id が不正です（ディレクトリ名 1 つでなければなりません）: review_id={review_id!r}"
    return None


def cmd_delete(args):
    reason = _invalid_review_id(args.review_id)
    if reason:
        return review_common.error(reason)
    path = review_common.review_dir(args.project_root, args.review_id)
    if path.is_symlink():
        return review_common.error(f"review_id の置き場がシンボリックリンクです: review_id={args.review_id}")
    try:
        if path.exists():
            shutil.rmtree(path)
    except OSError as exc:
        return review_common.error(f"保持物を削除できません: {exc}")
    review_common.emit({})
    return 0


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root")
    parser.add_argument("review_id")
    return parser


def run_cli(argv=None):
    return cmd_delete(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(run_cli())
