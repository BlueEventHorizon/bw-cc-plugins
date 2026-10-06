#!/usr/bin/env python3
"""review の受け渡し script が共通で使う部品。

JSON の出力、失敗の返し方、一時ファイルを経由した公開、絶対パスの検査、結果の置き場の解決と
読み込み・封緘判定、ラッパーの共通の動作を持つ。各 script が同じディレクトリから import する（直接実行はしない）。

置くのは、使い手が確定した部品だけである。後続の script が必要とする部品は、必要になった
ときにここへ足す。
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


def emit(payload):
    """成功の結果を、JSON object 1 つとして標準出力へ出す。"""
    json.dump(payload, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


def error(*messages):
    """失敗を、終了コード 1 と標準出力の ``errors`` で返す。戻り値を終了コードとして返すこと。"""
    emit({"errors": list(messages)})
    return 1


def publish_json(path, payload):
    """同じディレクトリの一時ファイルへ書いてから置き換え、1 回の操作で公開する。"""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def non_absolute(values):
    """絶対パスでない値を、渡された順に返す。"""
    return [v for v in values if not Path(v).is_absolute()]


REQUEST_FILE = "review_request.json"
RESULT_FILE = "review_result.json"
EVALUATION_FILE = "evaluate_result.json"

# 結果が正常に終えたことを表す終了の値（REQ-029 FNC-311）
NORMAL_EXIT = "0"


def review_dir(project_root, review_id):
    """``<project_root>/.temp/review/<review_id>/`` を返す（実在は確かめない）。"""
    return Path(project_root).resolve() / ".temp" / "review" / review_id


def round_dir(project_root, review_id, round_number):
    """ラウンドの置き場 ``<review_id>/<round_number>/`` を返す（実在は確かめない）。"""
    return review_dir(project_root, review_id) / str(round_number)


# 結果ファイルごとの、要素を収める配列の名前
RESULT_ARRAYS = {RESULT_FILE: "findings", EVALUATION_FILE: "evaluations"}


def load_result(round_path, file_name=RESULT_FILE):
    """ラウンドの結果を読む（既定は所見の結果。評価の結果は ``EVALUATION_FILE``）。まだ無ければ ``None``。

    JSON として読めない、または JSON object でない、要素の配列（``findings`` / ``evaluations``）を
    持たない結果は ``ValueError`` にする（呼び出し側が、読めない結果として ``errors`` で返せるようにする）。
    """
    path = round_path / file_name
    if not path.is_file():
        return None
    result = json.loads(path.read_text(encoding="utf-8"))
    array = RESULT_ARRAYS[file_name]
    if not isinstance(result, dict) or not isinstance(result.get(array), list):
        raise ValueError(f"{file_name} は配列 {array} を持つ JSON object ではありません")
    return result


def is_sealed(result):
    """結果が封緘済み（``exit`` を持つ）か。"""
    return "exit" in result


def result_problem(round_path, file_name, label, round_number):
    """結果が正常に終えた状態かを DES-084 §5.4 の表で判定し、正常でなければ理由を返す。正常なら ``None``。

    結果の有無と ``exit`` の組（正常 / エラー値 / ``exit`` が無い / 結果が無い）を判定する。
    ``label`` は理由に載せる結果の呼び名（例: ``所見の結果``）である。
    """
    try:
        result = load_result(round_path, file_name)
    except (OSError, ValueError) as exc:
        return f"{label}を読めません: {exc}"
    if result is None:
        return f"{label}がありません（書き出されないまま終えました）: round_number={round_number}"
    if not is_sealed(result):
        return f"{label}が封緘されていません（書き出しの途中で終えました）: round_number={round_number}"
    if result["exit"] != NORMAL_EXIT:
        return f"{label}がエラーで終えています: {json.dumps(result['exit'], ensure_ascii=False)}"
    return None


def _passed_argv(args, passed_options):
    """ラッパーが受け取った ``passed_options`` を、基本の script へ渡す引数の列に戻す。"""
    argv = []
    for flag, spec in passed_options:
        value = getattr(args, flag.lstrip("-").replace("-", "_"))
        if spec.get("action") == "store_true":
            if value:
                argv.append(flag)
        elif spec.get("nargs"):
            if value:
                argv += [flag, *[str(v) for v in value]]
        elif value is not None:
            argv += [flag, str(value)]
    return argv


def run_wrapper(base_run_cli, fixed_options, argv=None, takes_location=False, passed_options=()):
    """基本の script を、固定したオプションつきで呼ぶ（ラッパーの共通の動作）。

    ラッパーが受け取るのは ``<project_root> <review_id> <round_number>``（と、``takes_location``
    のとき ``--location``、``passed_options`` に挙げたオプション）だけである。固定するオプションは
    受け取らず、呼び出し側が ``--kind`` などを上書きする口を作らない。基本の script の標準出力と
    終了コードをそのまま返す。標準入力は基本の script がそのまま読む。

    ``passed_options`` は ``(フラグ, add_argument の引数)`` の組の列で、基本の script がそのまま
    受け取るオプションを、ラッパーも同じ形で受け取って渡す（値の検査は基本の script が行う）。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root")
    parser.add_argument("review_id")
    parser.add_argument("round_number", type=int)
    if takes_location:
        parser.add_argument("--location", nargs="+", action="extend", required=True)
    for flag, spec in passed_options:
        parser.add_argument(flag, **spec)
    args = parser.parse_args(argv)

    base_argv = [args.project_root, args.review_id, str(args.round_number), *fixed_options]
    if takes_location:
        base_argv += ["--location", *args.location]
    base_argv += _passed_argv(args, passed_options)
    return base_run_cli(base_argv)


def missing_round(project_root, review_id, round_number):
    """ラウンドの置き場が実在しないときの理由を返す。実在すれば ``None``。"""
    if not review_dir(project_root, review_id).is_dir():
        return f"review_id が保持されていません: review_id={review_id}"
    if not round_dir(project_root, review_id, round_number).is_dir():
        return f"ラウンドの置き場がありません: review_id={review_id} round_number={round_number}"
    return None
