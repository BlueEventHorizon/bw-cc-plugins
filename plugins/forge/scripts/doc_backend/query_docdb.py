#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc-db query 低レベル CLI（series 指定検索・未整備検出・`Required documents:` 構築）。

query wrapper（`query_documents.py`）が category を固定して本 CLI を透過呼び出しする。
1 回の実行で 1 つの doc-db query operation を完結させ、機械判定可能な JSON と
exit code を返す。複数 operation の進行（未整備時の索引作成 → 再検索）は SKILL が
駆動し、本 CLI は他の CLI（`sync_docdb.py` 等）を呼び出さない。

## exit code / status 契約

| exit code | `status`          | 意味                                                 |
| --------- | ----------------- | ---------------------------------------------------- |
| 0         | `success`         | query が完了した（0 件・対象文書なしも成功）         |
| 10        | `unavailable`     | doc-db を利用できない（未導入・起動不能・接続不能） |
| 20        | `operation_error` | 障害。backend を切り替えてはならない                 |
| 30        | `index_missing`   | 当該 KEY / series が未整備。索引を作成して再試行する |

SKILL は exit code だけで経路を選択する。exit 10 は doc-db が所有する可用性判定の
失敗のみを意味し、この結果をどう使うかは選択者（SKILL）が順序リストから決める。

## 責務分離 [MANDATORY]

可用性判定は doc-db が所有し、選択順序は選択者（SKILL）だけが持つデータである。
本 CLI は設定（`.claude/.forge.yaml`）・優先 backend 指定・他方の backend・選択順序を
知らない。順序リストの解決は専用 CLI `resolve_backend_order.py` が担う。

## 判定順序 [MANDATORY]

1. 対象文書数を先に判定する。0 件なら索引に触れず「対象文書なし」の成功で終了する。
   索引側の状態からは「一度も同期していない series」と「同期済みだが対象 0 件」を
   区別できないため、この順序を崩してはならない。
2. 1 件以上ある場合に限り、`list_indexes` で当該 KEY / series の登録を確認する。
   未整備なら exit 30 を返す（索引作成は行わない。SKILL が駆動する）。
3. 未整備・0 件のいずれでも、series を外した横断検索へ切り替えない。
   当該 series はその branch の完全な現在状態であり、0 件は正しい結果である。

## error の判別（doc-db 0.3.3 の識別子契約）

KEY 不在・ゴミ箱状態は JSON-RPC error として届き、判別の正本は
`error.data.code`（`KEY_NOT_FOUND` / `KEY_TRASHED`）である。メッセージ文言・
数値 code では分岐しない。識別子を読み取れない error（`data` なし・未知の識別子・
isError 経路）はすべて障害（exit 20）として扱い、索引作成へ倒さない。

- `KEY_NOT_FOUND` → 未整備（exit 30）
- `KEY_TRASHED` → 未整備ではない。復活操作の案内を伴う明示エラー（exit 20）

## 出力構築

`results[].path` を順位どおりに抽出し、出力前に project root 起点で実在を確認して
実在しないものを除外する（除外件数は `notices` で通知する）。全件除外・0 件でも
operation は成功であり、空の `Required documents:` を返す。
`origin_signals` は出力しない。`warnings` は path リストとは別の診断情報として
payload の `warnings` に載せる。

## 情報保護 [MANDATORY]

エラー本文に載せてよいのは URL、port、reason code、doc-db が返した非機密メッセージ
に限る。環境変数値・設定本文を出力しない。

## テスト境界

`run()` は `ensure_available` / `resolve_documents` を差し替えられる。
HTTP は `docdb_client` の transport 境界へ注入するため、実サーバ・実 git・利用者の
home 設定に依存せずに全経路を検証できる。

## 依存

Python 標準ライブラリのみ。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(_SCRIPT_DIR.parent))
import docdb_client  # noqa: E402
import docdb_runtime  # noqa: E402
import project_documents  # noqa: E402

# --- 定数 ---------------------------------------------------------------------

#: 成功（0 件・対象文書なしを含む）
EXIT_SUCCESS = 0

#: doc-db 利用不能（可用性判定の失敗）。後続は選択者（SKILL）が順序リストから決める
EXIT_UNAVAILABLE = 10

#: 障害。backend を切り替えてはならない
EXIT_OPERATION_ERROR = 20

#: 当該 KEY / series が未整備。SKILL が索引を作成して再試行する
EXIT_INDEX_MISSING = 30

#: JSON contract の `status` 値（exit code と 1 対 1 で対応する）
STATUS_SUCCESS = "success"
STATUS_UNAVAILABLE = "unavailable"
STATUS_OPERATION_ERROR = "operation_error"
STATUS_INDEX_MISSING = "index_missing"

#: JSON contract の `backend` / `operation` 値
BACKEND = "doc-db"
OPERATION = "query"

#: reason code
REASON_INVALID_INPUT = "invalid_input"
REASON_DOCUMENTS_UNRESOLVED = "documents_unresolved"
REASON_KEY_NOT_FOUND = "key_not_found"
REASON_SERIES_NOT_REGISTERED = "series_not_registered"
REASON_KEY_TRASHED = "key_trashed"
REASON_TOOL_ERROR = "docdb_tool_error"
REASON_INVALID_RESPONSE = "docdb_invalid_response"

#: doc-db の error 識別子（公開契約。`error.data.code` が判別の正本）
IDENTIFIER_KEY_NOT_FOUND = "KEY_NOT_FOUND"
IDENTIFIER_KEY_TRASHED = "KEY_TRASHED"

#: 既存契約の検索結果ヘッダ
REQUIRED_DOCUMENTS_HEADER = "Required documents:"


# --- 内部例外 -------------------------------------------------------------------


class _InvalidResponse(Exception):
    """doc-db の応答が §4.5 の契約を満たさない（exit 20 / 障害）。"""


# --- 応答の解釈 -------------------------------------------------------------------


def series_of_key(listing: dict, key: str):
    """`list_indexes` 応答から当該 KEY の登録 series 一覧を取り出す。

    Returns:
        list | None: KEY が登録済みならその series 一覧（`null` は空集合として
        扱う。doc-db 側の契約で `null` は空配列と同義）。KEY 不在なら None。

    Raises:
        _InvalidResponse: `indexes[]` が契約の形をしていない。
    """
    indexes = listing.get("indexes")
    if not isinstance(indexes, list):
        raise _InvalidResponse("list_indexes の応答に indexes[] がありません")
    for entry in indexes:
        if isinstance(entry, dict) and entry.get("key") == key:
            series = entry.get("series")
            if series is None:
                return []
            if isinstance(series, list):
                return [str(item) for item in series]
            raise _InvalidResponse("list_indexes の series が配列でも null でもありません")
    return None


def extract_paths(response: dict) -> list:
    """query 応答の `results[].path` を順位どおりに抽出する。

    本文 field（`text` / `score` 等）は使用しない。forge の出力契約は path のみ。

    Raises:
        _InvalidResponse: `results[]` が無い、または path を持たない要素がある。
    """
    results = response.get("results")
    if not isinstance(results, list):
        raise _InvalidResponse("query の応答に results[] がありません")
    paths = []
    for entry in results:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not entry["path"]:
            raise _InvalidResponse("query の results[] に path を持たない要素があります")
        paths.append(entry["path"])
    return paths


def build_required_documents(paths) -> str:
    """既存契約の `Required documents:` 文字列を決定論的に構築する。

    各項目には path だけを出力する。0 件（全件除外を含む）は空のヘッダのみ。
    """
    paths = list(paths)
    if not paths:
        return REQUIRED_DOCUMENTS_HEADER + "\n"
    lines = "\n".join(f"- {path}" for path in paths)
    return f"{REQUIRED_DOCUMENTS_HEADER}\n\n{lines}\n"


def _exists_within_root(path_text, project_root) -> bool:
    """path が現在の worktree 内に実在するか判定する（BL-005）。

    索引はバックエンド側の状態であり、応答の path は信頼境界の外にある。
    絶対パス・`../` を経由するパス・symlink 解決で root の外へ出るパスは、
    実在していても「現在の worktree に存在する文書」ではないため除外する。
    """
    candidate = Path(str(path_text))
    if candidate.is_absolute():
        return False
    root = Path(project_root).resolve()
    try:
        resolved = (root / candidate).resolve()
    except OSError:
        return False
    if root not in resolved.parents:
        # root 自身（`.`）も文書ではないため除外する
        return False
    return resolved.exists()


def _extract_warnings(response: dict) -> list:
    """query 応答の `warnings` を診断情報として取り出す（正常時は field 不在）。"""
    raw = response.get("warnings")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return [str(raw)]


# --- 本体 -------------------------------------------------------------------------


def run(
    category: str,
    task: str,
    project_root,
    *,
    ensure_available=None,
    resolve_documents=None,
):
    """1 回の doc-db query operation を実行し `(exit code, JSON payload)` を返す。

    `ensure_available` / `resolve_documents` はテストの差し替え境界。
    既定は本番実装（`docdb_runtime.ensure_available` / `project_documents.resolve`）。
    """
    ensure = ensure_available or docdb_runtime.ensure_available
    resolve = resolve_documents or project_documents.resolve
    project_root = Path(project_root)
    startup = docdb_runtime.STARTUP_NOT_ATTEMPTED

    def payload(status, reason_code=None, **extra):
        base = {
            "status": status,
            "backend": BACKEND,
            "operation": OPERATION,
            "startup": startup,
            "reason_code": reason_code,
        }
        base.update(extra)
        return base

    # 入力検証（category は wrapper が固定する 2 値のみ）
    if category not in project_documents.CATEGORIES:
        return EXIT_OPERATION_ERROR, payload(
            STATUS_OPERATION_ERROR,
            REASON_INVALID_INPUT,
            message=(
                f"category は {' / '.join(project_documents.CATEGORIES)} の"
                f"いずれかです: {category!r}"
            ),
        )

    # doc-db の利用可否を確定させる（probe → 必要時 on-demand 起動 → 再接続）
    availability = ensure()
    startup = availability.startup
    if not availability.available:
        return EXIT_UNAVAILABLE, payload(
            STATUS_UNAVAILABLE,
            availability.reason_code,
            message=availability.detail,
            port=availability.port,
            url=availability.url,
        )

    # KEY / series / 対象文書一覧の解決
    try:
        docs = resolve(category, project_root)
    except project_documents.ProjectDocumentsError as exc:
        return EXIT_OPERATION_ERROR, payload(
            STATUS_OPERATION_ERROR, REASON_DOCUMENTS_UNRESOLVED, message=str(exc)
        )

    identity = {"category": category, "key": docs.key, "series": docs.series}

    # 対象文書 0 件の判定は索引側の状態確認より先に行う [MANDATORY]
    if docs.is_empty:
        return EXIT_SUCCESS, payload(
            STATUS_SUCCESS,
            result=build_required_documents([]),
            document_count=0,
            paths=[],
            excluded_count=0,
            warnings=[],
            notices=["対象文書が 0 件のため検索を行いませんでした（対象文書なし）"],
            **identity,
        )

    client = availability.client

    # 当該 series の登録確認（未整備の検出は list_indexes に依拠する。
    # 未登録 series への query は 0 件成功で返るため query からは検出できない）
    try:
        listing = client.list_indexes()
    except docdb_client.DocDbClientError as exc:
        return EXIT_OPERATION_ERROR, payload(
            STATUS_OPERATION_ERROR, REASON_TOOL_ERROR,
            message=f"list_indexes が失敗しました: {exc}", **identity,
        )
    try:
        registered_series = series_of_key(listing, docs.key)
    except _InvalidResponse as exc:
        return EXIT_OPERATION_ERROR, payload(
            STATUS_OPERATION_ERROR, REASON_INVALID_RESPONSE, message=str(exc), **identity
        )

    if registered_series is None or docs.series not in registered_series:
        # 索引がまだ存在しない（KEY 未作成、または現在の branch に対応する series が未同期）。
        # これは doc-db の障害ではないため operation 失敗にせず exit 30 で返し、索引を作成せずに戻る。
        # 索引の作成は呼び出し側の SKILL が update 系 SKILL へ委譲して行い、その後 query を再試行する。
        # series を外した横断検索へも切り替えない。
        reason = (
            REASON_KEY_NOT_FOUND if registered_series is None
            else REASON_SERIES_NOT_REGISTERED
        )
        return EXIT_INDEX_MISSING, payload(
            STATUS_INDEX_MISSING,
            reason,
            message=(
                f"KEY {docs.key!r} の series {docs.series!r} が未整備です。"
                "索引を作成してから query を再実行してください"
            ),
            document_count=docs.count,
            **identity,
        )

    # series を明示指定した query（mode / top_n は client の既定 = 設計値）
    try:
        response = client.query(key=docs.key, series=docs.series, query=task)
    except docdb_client.ToolError as exc:
        # 判別は error.data.code の識別子にのみ依拠する（ADR-058）。
        # 文言・数値 code では分岐しない。識別子を読み取れない error は障害。
        code = exc.data.get("code") if isinstance(exc.data, dict) else None
        if code == IDENTIFIER_KEY_NOT_FOUND:
            return EXIT_INDEX_MISSING, payload(
                STATUS_INDEX_MISSING,
                REASON_KEY_NOT_FOUND,
                message=(
                    f"KEY {docs.key!r} が存在しません。"
                    "索引を作成してから query を再実行してください"
                ),
                document_count=docs.count,
                **identity,
            )
        if code == IDENTIFIER_KEY_TRASHED:
            return EXIT_OPERATION_ERROR, payload(
                STATUS_OPERATION_ERROR,
                REASON_KEY_TRASHED,
                message=(
                    f"KEY {docs.key!r} はゴミ箱状態です。索引の作成では解消できません。"
                    "doc-db 側で KEY の復活操作を行ってから再実行してください"
                ),
                **identity,
            )
        return EXIT_OPERATION_ERROR, payload(
            STATUS_OPERATION_ERROR, REASON_TOOL_ERROR,
            message=f"query が失敗しました: {exc}", **identity,
        )
    except docdb_client.DocDbClientError as exc:
        return EXIT_OPERATION_ERROR, payload(
            STATUS_OPERATION_ERROR, REASON_TOOL_ERROR,
            message=f"query が失敗しました: {exc}", **identity,
        )

    try:
        paths = extract_paths(response)
    except _InvalidResponse as exc:
        return EXIT_OPERATION_ERROR, payload(
            STATUS_OPERATION_ERROR, REASON_INVALID_RESPONSE, message=str(exc), **identity
        )

    # 出力前のパス実在確認。索引は最後の同期時点の状態であり、同期後に削除された
    # 文書が残るため、実在しないものを除外する。あわせて現在の worktree の外を指す
    # パス（絶対パス・`../` 経由・symlink 脱出）も除外する（BL-005: 返すのは現在の
    # worktree に存在する文書だけ）。全件除外でも operation は成功とする。
    # 順位は除外後も元の順序を保つ。
    existing = [
        path for path in paths if _exists_within_root(path, docs.project_root)
    ]
    excluded_count = len(paths) - len(existing)
    notices = []
    if excluded_count:
        notices.append(
            f"実在しないパス {excluded_count} 件を検索結果から除外しました"
        )

    return EXIT_SUCCESS, payload(
        STATUS_SUCCESS,
        result=build_required_documents(existing),
        document_count=docs.count,
        paths=existing,
        excluded_count=excluded_count,
        warnings=_extract_warnings(response),
        notices=notices,
        **identity,
    )


# --- CLI ----------------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "doc-db に対する series 指定 query を 1 回実行し、"
            "Required documents: 形式の結果を JSON で出力する"
        )
    )
    # category の値検証は argparse の choices ではなく run() 側で行う。
    # choices に任せると不正値が exit 2 になり、exit 20 の契約から外れる。
    parser.add_argument("category", help="rules または specs")
    parser.add_argument("task", help="検索したいタスクの説明（1 つの位置引数）")
    parser.add_argument(
        "--project-root",
        default=None,
        help="プロジェクトルートのパス（省略時: カレントディレクトリ）",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    project_root = Path(args.project_root) if args.project_root else Path.cwd()
    exit_code, payload = run(args.category, args.task, project_root)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
