#!/usr/bin/env python3
"""review 本体が、レビューの依頼を組み立てて公開し、``review_id`` とラウンド 1 を作る。

受け渡すのは識別値（``review_id`` と ``round_number``）だけであり、依頼の本文は標準出力に
載せない。依頼（``review_request.json``）は本 script が組み立てて置き、reviewer は別の script
から得たパスの JSON を直接読む。依頼は任意項目を含む組み立てが終わるまで同じディレクトリの
下書きとして保持し、完成後に 1 回の操作（``os.replace``）で公開する。公開後は書き換えない。

置き場は ``<project_root>/.temp/review/<review_id>/`` である。

- ``review_request.json`` — 依頼。レビューに 1 つ
- ``1/`` — ラウンド 1 の置き場。所見の結果はここへ置かれる（本 script は空の置き場だけを作る）

``focus`` / ``scope`` は、本体が Write ツールで書いたファイル（``--focus-file`` /
``--scope-file``）から、内容を加工せずに取り込む。成功したらこの 2 つのファイルを削除する。
失敗したときは削除しない（作り直せるように残す）。

本 script は REQ-029 の FNC-302・303・305・317 と DM-301・304 の実装である。

## 終了コード

| code | 意味                                                         |
| ---- | ------------------------------------------------------------ |
| 0    | 依頼を公開した（標準出力に ``review_id`` と ``round_number``） |
| 1    | 区別のない失敗（標準出力の ``errors`` に理由）                |
| 2    | 引数を受理できない（``argparse``）                           |

Usage:
    python3 publish_request.py PROJECT_ROOT \\
        [--paths P [P ...]] [--base-branch B] [--diff] \\
        [--references R [R ...]] [--focus-file F] [--scope-file S]

    ``--paths`` / ``--base-branch`` / ``--diff`` は 1 つ以上を、渡した順に ``targets`` へ並べる。
"""

import argparse
import os
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_common  # noqa: E402

FIRST_ROUND = 1


class _TargetAction(argparse.Action):
    """``--paths`` / ``--base-branch`` / ``--diff`` を、渡された順に 1 つの配列へ積む。"""

    def __call__(self, parser, namespace, values, option_string=None):
        targets = list(getattr(namespace, self.dest, None) or [])
        if self.const == "paths":
            targets.append({"paths": list(values)})
        elif self.const == "base_branch":
            targets.append({"base_branch": values})
        else:
            targets.append({"diff": {}})
        setattr(namespace, self.dest, targets)


def _read_text_as_is(path):
    """改行を含め、ファイルの内容を加工せずに文字列として読む。"""
    return Path(path).read_bytes().decode("utf-8")


def _dedup_references(references):
    """正規化して重複を除く。最初に現れた順序を保つ。"""
    seen = {}
    for ref in references:
        seen.setdefault(os.path.normpath(ref), None)
    return list(seen)


def _validate(args):
    """入力の誤りを理由の一覧で返す。無ければ空配列。"""
    errors = []
    if not args.targets:
        errors.append("target が 1 つもありません（--paths / --base-branch / --diff のいずれかが必要）")
    for target in args.targets or []:
        bad = review_common.non_absolute(target.get("paths", []))
        if bad:
            errors.append(f"--paths は絶対パスで渡してください: {', '.join(bad)}")
    bad_refs = review_common.non_absolute(args.references or [])
    if bad_refs:
        errors.append(f"--references は絶対パスで渡してください: {', '.join(bad_refs)}")
    return errors


def _create_review_dir(base):
    """他のレビューと衝突しない ``review_id`` で、``<review_id>/`` を新規に作る。"""
    base.mkdir(parents=True, exist_ok=True)
    while True:
        review_id = uuid.uuid4().hex
        try:
            (base / review_id).mkdir()
        except FileExistsError:
            continue
        return review_id, base / review_id


def cmd_publish(args):
    errors = _validate(args)
    if errors:
        return review_common.error(*errors)

    project_root = Path(args.project_root).resolve()
    if not project_root.is_dir():
        return review_common.error(f"プロジェクトルートがディレクトリではありません: {project_root}")

    request = {"targets": args.targets}
    input_files = []
    for key, file_path in (("focus", args.focus_file), ("scope", args.scope_file)):
        if file_path is None:
            continue
        input_files.append(file_path)
        try:
            request[key] = _read_text_as_is(file_path)
        except (OSError, ValueError) as exc:
            return review_common.error(f"入力ファイルを読めません: {file_path}: {exc}")
    if args.references:
        request["references"] = _dedup_references(args.references)

    review_dir = None
    try:
        review_id, review_dir = _create_review_dir(project_root / ".temp" / "review")
        review_common.publish_json(review_dir / review_common.REQUEST_FILE, request)
        (review_dir / str(FIRST_ROUND)).mkdir()
    except OSError as exc:
        # 作りかけの <review_id>/ を残さない。入力ファイルは削除しない
        if review_dir is not None:
            shutil.rmtree(review_dir, ignore_errors=True)
        return review_common.error(f"ファイルを操作できません: {exc}")

    _remove_inputs(input_files)
    review_common.emit({"review_id": review_id, "round_number": FIRST_ROUND})
    return 0


def _remove_inputs(paths):
    """取り込み済みの入力ファイルを削除する。削除できなくても、公開済みの依頼の成否には影響させない。"""
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError as exc:
            print(f"入力ファイルを削除できません: {p}: {exc}", file=sys.stderr)


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root")
    parser.add_argument("--paths", nargs="+", action=_TargetAction, const="paths", dest="targets")
    parser.add_argument("--base-branch", action=_TargetAction, const="base_branch", dest="targets")
    parser.add_argument("--diff", nargs=0, action=_TargetAction, const="diff", dest="targets")
    parser.add_argument("--references", nargs="+", action="extend")
    parser.add_argument("--focus-file")
    parser.add_argument("--scope-file")
    return parser


def run_cli(argv=None):
    args = build_parser().parse_args(argv)
    return cmd_publish(args)


if __name__ == "__main__":
    raise SystemExit(run_cli())
