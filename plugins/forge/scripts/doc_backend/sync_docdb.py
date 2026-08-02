#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc-db への desired-state 同期を駆動する低レベル CLI（投入と状態取得の 2 操作）。

update wrapper（および query 経路の未整備リカバリ）が呼ぶ script であり、
提供する操作は次の 2 つだけである。

| 操作                | 動作                                                            | 返す内容         |
| ------------------- | --------------------------------------------------------------- | ---------------- |
| `--start`           | 対象文書一覧を解決し `sync_documents` を投入して即時に返る      | `job_id`         |
| `--status <job_id>` | `get_sync_status` を 1 回呼び、その時点の進捗を返して即時に返る | job の状態と件数 |

## プロセス内にポーリングループを持たない [MANDATORY]

完了待ちのポーリングは SKILL が `--status` を間隔を空けて繰り返し呼ぶことで行う。
1 プロセス内で完了まで待つと、進捗が当該プロセスの標準エラー出力にしか現れず、
SKILL 経由の実行では利用者に届かない。索引作成は数分に及びうるため、
進捗が見えないまま利用者を待たせることになる。
したがって本 CLI は `time.sleep` も反復問い合わせも持たず、各操作は単発で完結する。

`--status` は job が未完了（`running`）でも exit code `0` を返す。
未完了は異常ではなく、その時点の正しい状態である。完了判定は SKILL 側のループが
JSON の job 進捗を読んで行う。

## desired-state 同期

`--start` は既存 `.doc_structure.yaml` の category 設定から対象 Markdown 一覧を解決し、
各 entry を `{path, local_path}` として一覧**全体**を `sync_documents` へ渡す。
一覧全体が desired state であるため、追加・変更・削除・リネームは同じ経路で収束する
（一覧に無い文書は doc-db 側で当該 series から切り離される）。
hash 一致文書の再計算要否は doc-db に委ねる。

**対象文書が 0 件の場合は同期しない。** 設定誤りで一覧が空になった状態で desired-state
同期を投入すると、当該 series の全文書が切り離される。空集合への意図的な同期は
wrapper の責務に含めないため、索引に触れる前に明示エラー（exit 20）で止める。

## 優先 backend 設定（`.claude/.forge.yaml` の `doc_backend` セクション）

入口で `forge_settings.py` を通じて優先 backend 設定を読む。
許容する形は mapping `{prefer: doc-db | doc-advisor}` のみである。

| `prefer` の値              | 本 CLI の挙動                                                              |
| -------------------------- | --------------------------------------------------------------------------- |
| 未指定・ファイル不在       | 従来どおり（doc-db の接続確認から始める）                                   |
| `doc-db`                   | 従来どおり（既定順序の明示に過ぎない）                                      |
| `doc-advisor`              | doc-db の probe・起動試行を行わず exit `10` / reason `advisor_preferred`    |
| 不正（許容する形に反する） | exit `20` / reason `settings_invalid`。**推測で既定順序に落ちない**         |

不正には、セクションが mapping でない・未知のキーを含む（綴り誤りを黙って無視すると
指定が効いていないことに気づけない）・`prefer` の値が 2 値以外、の全てを含む。
構文エラー（`SettingsError`）も同じく `settings_invalid` とする。
`--ignore-preference` は設定の読み取りだけを省く flag であり、他の挙動を変えない
（doc-advisor 優先が満たせなかったときの SKILL の復帰経路で使う）。

## exit code / status 契約

| exit code | `status`           | 意味                                                     |
| --------- | ------------------ | -------------------------------------------------------- |
| 0         | `success`          | 操作が完了した（`--status` は job 未完了でも成功）       |
| 10        | `advisor_fallback` | doc-db を試行しない/できない。doc-advisor の確認へ進む   |
| 20        | `operation_error`  | 明示エラー。backend を切り替えてはならない               |

exit code `30`（`index_missing`）は query 経路専用であり、本 CLI は返さない。
SKILL は exit code だけで経路を選択し、JSON は結果表示と診断情報の取得にだけ使う
（例外は exit `10` の `reason_code` が `advisor_preferred` かどうかの 1 値のみ）。

## 情報保護 [MANDATORY]

認証情報を読む処理も出力する処理も持たない。エラー本文に載せるのは URL、port、
reason code、および doc-db が返した非機密メッセージ（`ToolError.message`）に限る。
HTTP エラーはサーバ応答 body を含み得るため、status code と URL だけへ畳む。

## テスト境界

設定読み取り（`settings_section=`）、対象文書解決（`resolve=`）、doc-db 利用可否
（`ensure=`）はいずれも引数で差し替えられる。テストは実 doc-db・実 git・利用者の
home 設定に依存しない。

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
import forge_settings  # noqa: E402
import project_documents  # noqa: E402

# --- 定数 ---------------------------------------------------------------------

#: 成功
EXIT_SUCCESS = 0

#: doc-advisor の利用可否確認へ進んでよい（doc-db を試行しない/できない）
EXIT_ADVISOR_FALLBACK = 10

#: 明示エラー。backend を切り替えてはならない
EXIT_OPERATION_ERROR = 20

#: JSON contract の `status` 値
STATUS_SUCCESS = "success"
STATUS_ADVISOR_FALLBACK = "advisor_fallback"
STATUS_OPERATION_ERROR = "operation_error"

#: JSON contract の `backend` / `operation` 値
BACKEND = "doc-db"
OPERATION_SYNC_START = "sync_start"
OPERATION_SYNC_STATUS = "sync_status"

#: 優先 backend 設定のセクションとスキーマ（DES-057 が所有）
SETTINGS_SECTION_NAME = "doc_backend"
SETTINGS_PREFER_KEY = "prefer"
PREFER_DOC_DB = "doc-db"
PREFER_DOC_ADVISOR = "doc-advisor"
ALLOWED_PREFER_VALUES = (PREFER_DOC_DB, PREFER_DOC_ADVISOR)

#: reason code
REASON_ADVISOR_PREFERRED = "advisor_preferred"
REASON_SETTINGS_INVALID = "settings_invalid"
REASON_INVALID_INPUT = "invalid_input"
REASON_DOCUMENTS_UNRESOLVED = "documents_unresolved"
REASON_NO_DOCUMENTS = "no_documents"
REASON_SYNC_START_FAILED = "sync_start_failed"
REASON_SYNC_STATUS_FAILED = "sync_status_failed"


# --- 例外 ---------------------------------------------------------------------


class SyncDocDbError(Exception):
    """本 CLI の非成功結果（exit code / status / reason code を運ぶ）。

    `startup` は doc-db 起動試行の結果（`docdb_runtime` の 3 値）。
    doc-db に触れる前の失敗は `not_attempted` のまま。
    """

    def __init__(
        self,
        exit_code: int,
        status: str,
        reason_code: str,
        message: str,
        startup: str = docdb_runtime.STARTUP_NOT_ATTEMPTED,
    ):
        super().__init__(message)
        self.exit_code = exit_code
        self.status = status
        self.reason_code = reason_code
        self.startup = startup

    def payload(self, operation: str) -> dict:
        return {
            "status": self.status,
            "backend": BACKEND,
            "operation": operation,
            "startup": self.startup,
            "reason_code": self.reason_code,
            "message": str(self),
        }


# --- 優先 backend 設定 ----------------------------------------------------------


def enforce_backend_preference(
    project_root,
    ignore_preference: bool = False,
    settings_section=forge_settings.section,
) -> None:
    """優先 backend 設定を読み、doc-db 経路を続行してよいかを確定する。

    続行してよい場合は何もせず返る。doc-advisor 優先指定は exit 10 /
    `advisor_preferred`、設定不正は exit 20 / `settings_invalid` の
    `SyncDocDbError` として送出する。

    `ignore_preference` が真の場合は設定を**読まない**（読んで無視するのではない。
    解析不能なファイルがあっても復帰経路を止めないための仕様である）。

    不正値・解析不能の設定を黙って無視して既定順序で動くことはしない。
    利用者が意図した backend と異なる側で静かに動き続けることになるためである。
    """
    if ignore_preference:
        return

    try:
        section = settings_section(project_root, SETTINGS_SECTION_NAME)
    except forge_settings.SettingsError as exc:
        raise SyncDocDbError(
            EXIT_OPERATION_ERROR, STATUS_OPERATION_ERROR, REASON_SETTINGS_INVALID, str(exc)
        ) from exc

    if not section:
        # セクション不在・ファイル不在は既定順序（doc-db 優先）
        return

    unknown_keys = sorted(k for k in section if k != SETTINGS_PREFER_KEY)
    if unknown_keys:
        raise SyncDocDbError(
            EXIT_OPERATION_ERROR,
            STATUS_OPERATION_ERROR,
            REASON_SETTINGS_INVALID,
            f"'{SETTINGS_SECTION_NAME}' セクションに未知のキーがあります: "
            f"{', '.join(unknown_keys)}（許容するキーは '{SETTINGS_PREFER_KEY}' のみ）",
        )

    prefer = section.get(SETTINGS_PREFER_KEY)
    if prefer not in ALLOWED_PREFER_VALUES:
        raise SyncDocDbError(
            EXIT_OPERATION_ERROR,
            STATUS_OPERATION_ERROR,
            REASON_SETTINGS_INVALID,
            f"'{SETTINGS_SECTION_NAME}.{SETTINGS_PREFER_KEY}' の値が不正です: {prefer!r}"
            f"（{' / '.join(ALLOWED_PREFER_VALUES)} のみ）",
        )

    if prefer == PREFER_DOC_ADVISOR:
        raise SyncDocDbError(
            EXIT_ADVISOR_FALLBACK,
            STATUS_ADVISOR_FALLBACK,
            REASON_ADVISOR_PREFERRED,
            "設定（.claude/.forge.yaml）で doc-advisor が優先指定されています。"
            "doc-db の接続確認・起動試行は行っていません",
        )


# --- 操作: --start --------------------------------------------------------------


def start_sync(
    category: str,
    project_root,
    *,
    resolve=project_documents.resolve,
    ensure=docdb_runtime.ensure_available,
) -> dict:
    """対象文書一覧を desired state として `sync_documents` へ投入し、即時に返る。

    完了待ちは行わない（`job_id` を返した時点で本操作は完了である）。
    """
    _validate_category(category)

    # 対象文書の解決と 0 件防御は doc-db に触れる前に行う
    # （0 件は設定誤りによる全 series 切り離しを防ぐための明示エラー）。
    try:
        documents = resolve(category, project_root)
    except project_documents.ProjectDocumentsError as exc:
        raise SyncDocDbError(
            EXIT_OPERATION_ERROR,
            STATUS_OPERATION_ERROR,
            REASON_DOCUMENTS_UNRESOLVED,
            str(exc),
        ) from exc

    if documents.is_empty:
        raise SyncDocDbError(
            EXIT_OPERATION_ERROR,
            STATUS_OPERATION_ERROR,
            REASON_NO_DOCUMENTS,
            f"category '{category}' の対象文書が 0 件のため同期しません。"
            "空の一覧を desired state として投入すると当該 series の全文書が"
            "切り離されるため、設定（.doc_structure.yaml）を確認してください",
        )

    availability = ensure()
    if not availability.available:
        raise SyncDocDbError(
            EXIT_ADVISOR_FALLBACK,
            STATUS_ADVISOR_FALLBACK,
            availability.reason_code,
            availability.detail or "doc-db を利用できません",
            startup=availability.startup,
        )

    try:
        result = availability.client.sync_documents(
            documents.key, documents.series, documents.entries
        )
    except docdb_client.DocDbClientError as exc:
        raise SyncDocDbError(
            EXIT_OPERATION_ERROR,
            STATUS_OPERATION_ERROR,
            REASON_SYNC_START_FAILED,
            f"sync_documents の投入に失敗しました: {_client_error_detail(exc)}",
            startup=availability.startup,
        ) from exc

    job_id = result.get("job_id")
    if not job_id:
        # 応答に job_id が無い場合は operation 失敗（DES 依拠スナップショットの契約）
        raise SyncDocDbError(
            EXIT_OPERATION_ERROR,
            STATUS_OPERATION_ERROR,
            REASON_SYNC_START_FAILED,
            "sync_documents の応答に job_id が含まれていません",
            startup=availability.startup,
        )

    return {
        "status": STATUS_SUCCESS,
        "backend": BACKEND,
        "operation": OPERATION_SYNC_START,
        "startup": availability.startup,
        "reason_code": None,
        "category": category,
        "key": documents.key,
        "series": documents.series,
        "count": documents.count,
        "job_id": job_id,
    }


# --- 操作: --status --------------------------------------------------------------

#: `get_sync_status` 応答契約（DES-057 §4.5）の許容 status 値
_JOB_STATUS_VALUES = ("running", "done", "failed")

#: 同契約で SKILL が進捗報告・完了判定に使う件数 field（int であること）
_JOB_COUNT_FIELDS = ("processed", "skipped", "failed", "deleted_paths_marked")


def _validate_job_progress(job, *, startup) -> None:
    """`get_sync_status` 応答が DES-057 §4.5 の契約を満たすか検証する。

    SKILL は `job.status` でポーリングの終了・失敗を判定するため、未知の status や
    field 欠落を無検証で success として返すと、上限まで誤って待つ・失敗を成功扱いに
    する誤動作につながる（BL-004: 接続確立後の応答の不正は明示エラー）。
    メッセージには field 名と期待だけを載せ、応答本文の値は載せない。
    `startup` は起動試行結果の通知（FNC-004）を保つためエラーへそのまま載せる。
    """

    def _invalid(reason: str):
        return SyncDocDbError(
            EXIT_OPERATION_ERROR,
            STATUS_OPERATION_ERROR,
            REASON_SYNC_STATUS_FAILED,
            f"get_sync_status の応答が契約に適合しません: {reason}",
            startup=startup,
        )

    if not isinstance(job, dict):
        raise _invalid("応答が object ではありません")
    if job.get("status") not in _JOB_STATUS_VALUES:
        raise _invalid(
            "status が running / done / failed のいずれでもありません"
        )
    for field in _JOB_COUNT_FIELDS:
        if not isinstance(job.get(field), int) or isinstance(job.get(field), bool):
            raise _invalid(f"{field} が整数ではありません（または欠落）")
    if not isinstance(job.get("errors"), list):
        raise _invalid("errors がリストではありません（または欠落）")


def get_status(
    category: str,
    job_id: str,
    project_root,
    *,
    ensure=docdb_runtime.ensure_available,
) -> dict:
    """`get_sync_status` を 1 回だけ呼び、その時点の job 進捗を返して即時に返る。

    job が未完了（`running`）でも本操作は成功である（exit 0）。
    完了判定・打ち切り判定は SKILL 側のループが JSON の `job` を読んで行う。
    """
    _validate_category(category)

    availability = ensure()
    if not availability.available:
        raise SyncDocDbError(
            EXIT_ADVISOR_FALLBACK,
            STATUS_ADVISOR_FALLBACK,
            availability.reason_code,
            availability.detail or "doc-db を利用できません",
            startup=availability.startup,
        )

    try:
        job = availability.client.get_sync_status(job_id)
    except docdb_client.DocDbClientError as exc:
        raise SyncDocDbError(
            EXIT_OPERATION_ERROR,
            STATUS_OPERATION_ERROR,
            REASON_SYNC_STATUS_FAILED,
            f"get_sync_status に失敗しました: {_client_error_detail(exc)}",
            startup=availability.startup,
        ) from exc

    _validate_job_progress(job, startup=availability.startup)

    return {
        "status": STATUS_SUCCESS,
        "backend": BACKEND,
        "operation": OPERATION_SYNC_STATUS,
        "startup": availability.startup,
        "reason_code": None,
        "category": category,
        "job_id": job_id,
        "job": job,
    }


# --- CLI ----------------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "doc-db への desired-state 同期の投入（--start）と"
            "単発の状態取得（--status <job_id>）を行い JSON で出力する"
        )
    )
    # category の値検証は argparse の choices ではなく操作側で行う。
    # choices に任せると不正値が exit 2 になり、exit 20 の契約から外れる。
    parser.add_argument("category", help="rules または specs")
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument(
        "--start",
        action="store_true",
        help="対象文書一覧を desired state として投入し job_id を即時返す",
    )
    operation.add_argument(
        "--status",
        metavar="JOB_ID",
        help="job の状態を 1 回だけ取得して即時返す（未完了でも成功）",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="プロジェクトルートのパス（省略時: カレントディレクトリ）",
    )
    parser.add_argument(
        "--ignore-preference",
        action="store_true",
        help="優先 backend 設定（.claude/.forge.yaml）を読まない",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    project_root = Path(args.project_root) if args.project_root else Path.cwd()
    operation = OPERATION_SYNC_START if args.start else OPERATION_SYNC_STATUS

    try:
        enforce_backend_preference(project_root, ignore_preference=args.ignore_preference)
        if args.start:
            payload = start_sync(args.category, project_root)
        else:
            payload = get_status(args.category, args.status, project_root)
    except SyncDocDbError as exc:
        print(json.dumps(exc.payload(operation), indent=2, ensure_ascii=False))
        return exc.exit_code

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return EXIT_SUCCESS


# --- 内部 ---------------------------------------------------------------------


def _validate_category(category: str) -> None:
    if category not in project_documents.CATEGORIES:
        raise SyncDocDbError(
            EXIT_OPERATION_ERROR,
            STATUS_OPERATION_ERROR,
            REASON_INVALID_INPUT,
            f"category は {' / '.join(project_documents.CATEGORIES)} のいずれかです:"
            f" {category!r}",
        )


def _client_error_detail(exc) -> str:
    """client 例外を、秘密値を含み得ない要素だけの診断文字列へ畳む。

    - `ToolError`: doc-db が返した非機密メッセージ（載せてよい契約）
    - `HttpError`: 応答 body を含み得るため status code と URL だけへ畳む
    - その他: 例外クラス名 + メッセージ（URL / port / 失敗分類のみで構成される）
    """
    if isinstance(exc, docdb_client.ToolError):
        return exc.message
    if isinstance(exc, docdb_client.HttpError):
        return f"{type(exc).__name__}: HTTP {exc.status} ({exc.url})"
    return f"{type(exc).__name__}: {exc}"


if __name__ == "__main__":
    sys.exit(main())
