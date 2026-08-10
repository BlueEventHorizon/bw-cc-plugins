#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc-advisor `index-docs` の入力（dirs / exclude）を準備する低レベル CLI。

query / update wrapper が doc-advisor 経路へ切り替えるとき、`index-docs` を呼ぶ前に
本 CLI を 1 回実行する。責務は次の 2 つだけである。

1. 既存 dprint runner（`scripts/doc_structure/run_dprint_fmt.sh`）を実行し、
   索引対象の Markdown を索引作成前にフォーマットする。
2. `.doc_structure.yaml` から当該 category の `root_dirs` / `patterns.exclude` を
   解決し、`index-docs` へ渡す入力として JSON で返す。

ファイル一覧への展開は行わない。展開は doc-advisor 側に委ね、doc-db sync 用の
`project_documents.py` は使用しない。索引母集団の決定経路が backend ごとに異なる
ことは設計上の許容事項である。

## exit code / status 契約

| exit code | `status`          | 意味                                             |
| --------- | ----------------- | ------------------------------------------------ |
| 0         | `success`         | dprint 適用と dirs / exclude 解決が完了した      |
| 20        | `operation_error` | dprint、設定解決、入力検証のいずれかが失敗した   |

SKILL は exit code だけで `index-docs` の実行可否を選択し、準備失敗時は
`index-docs` を呼ばない。JSON は結果表示と診断情報の取得にだけ使用する。

## 設定の解釈は既存 resolver を import して再利用する [MANDATORY]

`.doc_structure.yaml` の解釈（バージョン検証・構造検証を含む）は既存の
`scripts/doc_structure/resolve_doc_structure.py` が持つ。本 CLI は **YAML パーサを
二重実装しない**。二重実装すると同じ設定から backend ごとに異なる母集団が導かれる。

委譲の方式は `project_documents.py`（subprocess 委譲）と異なり **importlib による
import** を採る。理由は次のとおり。

1. resolver の CLI（`--type`）が返すのは展開済みのファイル一覧であり、本 CLI が
   必要とする展開前の `root_dirs` / `patterns.exclude` を公開していない。
2. import で使う `load_doc_structure()` / `validate_doc_structure()` は例外と戻り値
   だけで失敗を表現し、`sys.exit()` を呼ばない（`sys.exit()` は `main()` に閉じて
   いる）。subprocess を選ぶ理由だった「エラー経路の歪み」がこの範囲では生じない。

## テスト境界

外部コマンド（dprint runner）の実行は `run_command()` の 1 関数に閉じる。
resolver モジュールは `resolver_script=` でパス差し替えできる。これにより、実 dprint と
実在の `.doc_structure.yaml` に依存せずに検証できる。

## 依存

Python 標準ライブラリのみ。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

# --- 定数 ---------------------------------------------------------------------

#: wrapper が固定する category
CATEGORIES = ("rules", "specs")

#: 成功
EXIT_SUCCESS = 0

#: dprint / 設定解決 / 入力検証の失敗（doc-advisor へ進んではならない）
EXIT_OPERATION_ERROR = 20

#: JSON contract の `status` 値
STATUS_SUCCESS = "success"
STATUS_OPERATION_ERROR = "operation_error"

#: 本 CLI は doc-db に触れないため、`startup` は常に未試行
STARTUP_NOT_ATTEMPTED = "not_attempted"

#: JSON contract の `backend` / `operation` 値
BACKEND = "doc-advisor"
OPERATION = "prepare_index"

#: 失敗の reason code
REASON_INVALID_INPUT = "invalid_input"
REASON_DPRINT_FAILED = "dprint_failed"
REASON_DOC_STRUCTURE_INVALID = "doc_structure_invalid"

#: 索引作成前フォーマットに使う既存 dprint runner
DPRINT_SCRIPT = (
    Path(__file__).resolve().parent.parent / "doc_structure" / "run_dprint_fmt.sh"
)

#: 設定解釈を委譲する既存 resolver
RESOLVER_SCRIPT = (
    Path(__file__).resolve().parent.parent / "doc_structure" / "resolve_doc_structure.py"
)

#: dprint runner の timeout（秒）。リポジトリ全体のフォーマットを含むため長めに取る
DPRINT_TIMEOUT_SECONDS = 120

#: 外部コマンドを実行できなかった場合に `run_command()` が返す returncode
COMMAND_UNAVAILABLE_RETURNCODE = -1

#: 診断メッセージへ載せる外部コマンド出力の最大長
_MAX_OUTPUT_EXCERPT = 400


# --- 例外 ---------------------------------------------------------------------


class PrepareAdvisorIndexError(Exception):
    """索引入力の準備を完了できなかった（exit 20 / `status=operation_error`）。"""

    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


# --- 外部コマンド境界 ---------------------------------------------------------


def run_command(args, cwd: Path, timeout: float):
    """外部コマンドを実行し `(returncode, stdout, stderr)` を返す。

    **本関数が唯一の外部コマンド実行境界である。** テストはここを差し替える。
    実行不能（コマンド不在・cwd 不正・timeout）は例外にせず
    `COMMAND_UNAVAILABLE_RETURNCODE` と理由を stderr として返す。
    """
    try:
        result = subprocess.run(
            list(args),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return COMMAND_UNAVAILABLE_RETURNCODE, "", f"コマンドが {timeout} 秒で終了しませんでした"
    except OSError as exc:
        return COMMAND_UNAVAILABLE_RETURNCODE, "", f"コマンドを実行できません: {exc}"
    return result.returncode, result.stdout, result.stderr


# --- dprint -------------------------------------------------------------------


def run_dprint(
    project_root: Path,
    runner=run_command,
    dprint_script: Path = DPRINT_SCRIPT,
) -> None:
    """既存 dprint runner を project root で実行する。失敗は例外として伝播する。

    runner script 自身が「dprint 設定なし」「dprint コマンド不在」を正常スキップと
    して扱うため、非ゼロ終了は実際のフォーマット失敗だけである。失敗を握りつぶして
    索引作成へ進むと、未フォーマットの文書が索引され母集団の再現性が崩れるため、
    ここで確定的に失敗させる。
    """
    returncode, stdout, stderr = runner(
        ["bash", str(dprint_script)], Path(project_root), DPRINT_TIMEOUT_SECONDS
    )
    if returncode != 0:
        raise PrepareAdvisorIndexError(
            REASON_DPRINT_FAILED,
            f"dprint の実行に失敗しました（exit={returncode}）: {_excerpt(stderr, stdout)}",
        )


# --- 設定解決 -----------------------------------------------------------------


def load_resolver_module(resolver_script: Path = RESOLVER_SCRIPT):
    """既存 resolver をモジュールとしてロードする（YAML 解釈の二重実装防止）。"""
    spec = importlib.util.spec_from_file_location(
        "forge_doc_structure_resolver", str(resolver_script)
    )
    if spec is None or spec.loader is None:
        raise PrepareAdvisorIndexError(
            REASON_DOC_STRUCTURE_INVALID,
            f"resolver をロードできません: {resolver_script}",
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_index_inputs(
    category: str,
    project_root: Path,
    resolver_script: Path = RESOLVER_SCRIPT,
) -> dict:
    """`.doc_structure.yaml` から category の `root_dirs` / `exclude` を解決する。

    Returns:
        dict: `{"root_dirs": [...], "exclude": [...]}`（いずれも設定記載順）

    Raises:
        PrepareAdvisorIndexError: 設定ファイル不在・構造不正・当該 category の
            `root_dirs` 欠落のいずれか（`reason_code=doc_structure_invalid`）
    """
    resolver = load_resolver_module(resolver_script)
    try:
        config, raw_content = resolver.load_doc_structure(str(project_root))
    except FileNotFoundError as exc:
        raise PrepareAdvisorIndexError(REASON_DOC_STRUCTURE_INVALID, str(exc)) from exc
    except (OSError, UnicodeDecodeError) as exc:
        # 権限不備・非 UTF-8 等の読取失敗も設定解決の失敗として正規化する。
        # 未捕捉のまま漏らすと JSON + exit 20 の契約（§4.4）を破って traceback になる
        raise PrepareAdvisorIndexError(
            REASON_DOC_STRUCTURE_INVALID,
            f".doc_structure.yaml を読み取れません（{type(exc).__name__}）",
        ) from exc

    validation = resolver.validate_doc_structure(config, raw_content)
    if not validation.get("valid"):
        message = validation.get("error", ".doc_structure.yaml の検証に失敗しました")
        suggestion = validation.get("suggestion")
        if suggestion:
            message = f"{message} / {suggestion}"
        raise PrepareAdvisorIndexError(REASON_DOC_STRUCTURE_INVALID, message)

    section = config.get(category)
    if not isinstance(section, dict):
        raise PrepareAdvisorIndexError(
            REASON_DOC_STRUCTURE_INVALID,
            f".doc_structure.yaml に '{category}' セクションがありません",
        )

    root_dirs = section.get("root_dirs")
    if not isinstance(root_dirs, list) or not root_dirs:
        raise PrepareAdvisorIndexError(
            REASON_DOC_STRUCTURE_INVALID,
            f".doc_structure.yaml の '{category}' に root_dirs が定義されていません",
        )

    patterns = section.get("patterns", {})
    exclude = patterns.get("exclude", []) if isinstance(patterns, dict) else []
    if not isinstance(exclude, list):
        raise PrepareAdvisorIndexError(
            REASON_DOC_STRUCTURE_INVALID,
            f".doc_structure.yaml の '{category}' の patterns.exclude がリストではありません",
        )

    return {
        "root_dirs": [str(item) for item in root_dirs],
        "exclude": [str(item) for item in exclude],
    }


# --- 準備の本体 ---------------------------------------------------------------


def prepare(
    category: str,
    project_root: Path,
    runner=run_command,
    dprint_script: Path = DPRINT_SCRIPT,
    resolver_script: Path = RESOLVER_SCRIPT,
) -> dict:
    """dprint 適用と dirs / exclude 解決をこの順で行い、成功 payload を返す。

    順序は設計上の規定（dprint → 設定解決）に従う。失敗は
    `PrepareAdvisorIndexError` として伝播し、呼び出し側（`main()`）が
    exit 20 / `status=operation_error` へ変換する。
    """
    _validate_category(category)
    project_root = Path(project_root).resolve()
    if not project_root.is_dir():
        raise PrepareAdvisorIndexError(
            REASON_INVALID_INPUT,
            f"project root がディレクトリではありません: {project_root}",
        )

    run_dprint(project_root, runner=runner, dprint_script=dprint_script)
    inputs = resolve_index_inputs(
        category, project_root, resolver_script=resolver_script
    )

    return {
        "status": STATUS_SUCCESS,
        "backend": BACKEND,
        "operation": OPERATION,
        "startup": STARTUP_NOT_ATTEMPTED,
        "reason_code": None,
        "category": category,
        "project_root": str(project_root),
        "root_dirs": inputs["root_dirs"],
        "exclude": inputs["exclude"],
    }


# --- CLI ----------------------------------------------------------------------


def _error_payload(reason_code: str, message: str) -> dict:
    return {
        "status": STATUS_OPERATION_ERROR,
        "backend": BACKEND,
        "operation": OPERATION,
        "startup": STARTUP_NOT_ATTEMPTED,
        "reason_code": reason_code,
        "message": message,
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "doc-advisor index-docs の入力（dprint 適用と root_dirs / exclude 解決）"
            "を準備して JSON で出力する"
        )
    )
    # category の値検証は argparse の choices ではなく prepare() 側で行う。
    # choices に任せると不正値が exit 2 になり、exit 20 の契約から外れる。
    parser.add_argument("category", help="rules または specs")
    parser.add_argument(
        "--project-root",
        default=None,
        help="プロジェクトルートのパス（省略時: カレントディレクトリ）",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    project_root = Path(args.project_root) if args.project_root else Path.cwd()

    try:
        payload = prepare(args.category, project_root)
    except PrepareAdvisorIndexError as exc:
        print(
            json.dumps(
                _error_payload(exc.reason_code, str(exc)),
                indent=2,
                ensure_ascii=False,
            )
        )
        return EXIT_OPERATION_ERROR

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return EXIT_SUCCESS


# --- 内部 ---------------------------------------------------------------------


def _validate_category(category: str) -> None:
    if category not in CATEGORIES:
        raise PrepareAdvisorIndexError(
            REASON_INVALID_INPUT,
            f"category は {' / '.join(CATEGORIES)} のいずれかです: {category!r}",
        )


def _excerpt(*outputs: str) -> str:
    """診断メッセージへ載せる出力の抜粋を作る。"""
    for output in outputs:
        text = (output or "").strip()
        if text:
            if len(text) > _MAX_OUTPUT_EXCERPT:
                return text[:_MAX_OUTPUT_EXCERPT] + "…"
            return text
    return "（出力なし）"


if __name__ == "__main__":
    sys.exit(main())
