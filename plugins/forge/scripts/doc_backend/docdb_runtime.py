#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc-db の利用可否を確定させる runtime 層（接続 probe → on-demand 起動 → 再接続）。

呼び出し側（低レベル CLI）はこのモジュールの `ensure_available()` を 1 回呼び、
返った `Availability` の `status` だけで次を決める。

| `status`      | 意味                                     | 呼び出し側の動作                       |
| ------------- | ---------------------------------------- | -------------------------------------- |
| `available`   | MCP session が確立済み（`client` を同梱）| その client で operation を実行する    |
| `unavailable` | 接続不能で起動でも復帰しなかった         | 別 backend の利用可否確認へ進む        |

## 利用可否は「プロセスの生死」ではなく「MCP 接続の成否」で判定する [MANDATORY]

判定の唯一の根拠は `initialize` の成功である。プロセス一覧・PID・port の LISTEN 状態は見ない。
複数の wrapper が同時に doc-db を起動しようとした場合、後から起動したプロセスは
「既に稼働中」として自ら終了しうる。この状況でプロセスの生死を根拠にすると、
実際には（先行プロセスによって）接続できる doc-db を利用不能と誤判定する。
そのため本モジュールは、自分が起動したプロセスが終了していても、接続できれば利用可能とする。

## 起動は on-demand に限る

起動は「今回の wrapper 実行を完了させるため」だけに行う。
OS ログイン時の自動起動、サービス登録、停止、再起動監視は行わない。

## 標準入出力の切り離しとログ [MANDATORY]

起動するプロセスは新規セッション（`start_new_session=True`）で、
標準入力・標準出力・標準エラーをすべて `DEVNULL` へ落とす。理由は 3 つある。

1. 新規セッションにしないと、呼び出し元のプロセスグループへ送られる SIGINT / SIGHUP を
   doc-db も受け取り、wrapper の終了に引きずられてサーバが落ちる。
2. 標準出力・標準エラーを親と共有すると、サーバの起動ログが wrapper の出力へ混入し、
   決定論的に構築するべき検索結果の出力を汚す。
3. **forge 側でログファイルを作らない。** サーバログの出力先は doc-db 自身の設定に委ねる。
   forge がログファイルを開くと、その置き場・世代管理・権限を forge が負うことになり、
   doc-db のログ設定と二重管理になる。

`DEVNULL` へ落とすため、起動失敗の詳細はサーバ自身のログ（doc-db の設定先）で確認する。
forge が観測して報告するのは「接続できたか」「プロセスが早期終了したか（exit code）」だけである。

## 期限付き再試行は「起動直後は接続できない」ことへの正しいリカバリー

`Popen` から復帰した時点でサーバはまだ listen していない。起動直後の 1 回の接続失敗で
利用不能と決めると、正常に起動した doc-db を取りこぼす。したがって再試行の対象は
**起動直後の未 listen 状態だけ**であり、期限（既定 10 秒）を超えたら諦めて理由コードを返す。
無期限の再試行や、接続確立後の operation 失敗の再試行は行わない
（後者は成否が確定しており、再試行しても結果は変わらない）。

再試行の待機は `sleep` / `now` の注入で差し替えられるため、テストは実時間に依存しない。

## 情報保護 [MANDATORY]

本モジュールは **認証情報を読む処理も出力する処理も持たない**。
環境変数を読まず、doc-db の設定ファイル本文も読まない（port の解決は `docdb_client` に委ね、
得るのは整数の port だけである）。`Availability.detail` に載せてよいのは URL、port、
HTTP status、exit code、失敗の分類（例外クラス名）、および固定の reason code に限る。

**例外メッセージの生文字列を detail に載せてはならない**。HTTP エラーの例外メッセージには
サーバ応答の body がそのまま含まれ、doc-db や前段の proxy が認証エラー時に body へ
設定値・資格情報・接続文字列を載せた場合、それが利用者向け出力へ流出する。
detail の組み立ては `_failure_detail()` に閉じ、そこを通らない経路を作らない。

## テスト境界

`which` / `spawn` / `sleep` / `now` / `client_factory` はすべて引数で差し替えられる。
既定値は実環境の実装（`shutil.which` / `subprocess.Popen` / `time`）だが、
テストはこれらを注入し、実行ファイル・実プロセス・実サーバ・実時間に依存しない。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import docdb_client  # noqa: E402

# --- 定数 ---------------------------------------------------------------------
# 通信定数（probe timeout / 起動待ち期限 / 再試行間隔 / 既定 port）は `docdb_client`
# が単一の定義元である。ここでは再定義せず、既定引数として参照する。

#: `shutil.which` で解決する doc-db 実行ファイル名
DOCDB_EXECUTABLE = "doc-db"

#: `ensure_available()` が返す status
STATUS_AVAILABLE = "available"
STATUS_UNAVAILABLE = "unavailable"

#: 起動の試行結果（低レベル CLI の JSON contract の `startup` に載る値）
#:
#: - `not_attempted`: 初回接続に成功したため起動を試みていない
#: - `succeeded`: 起動を経て MCP 接続が確立した
#: - `failed`: 起動による復帰に失敗した（実行ファイル不在で試みられなかった場合も含む）
STARTUP_NOT_ATTEMPTED = "not_attempted"
STARTUP_SUCCEEDED = "succeeded"
STARTUP_FAILED = "failed"

#: 利用不能の理由コード。4 つの異常系はそれぞれ固有のコードで区別する
REASON_EXECUTABLE_MISSING = "docdb_executable_missing"
REASON_SPAWN_FAILED = "docdb_spawn_failed"
REASON_EXITED_EARLY = "docdb_exited_early"
REASON_RECONNECT_FAILED = "docdb_reconnect_failed"


# --- 結果 ---------------------------------------------------------------------


class Availability:
    """doc-db の利用可否の確定結果。

    `status` が `available` のときだけ `client` に MCP session 確立済みの
    `docdb_client.Client` が入る。`reason_code` / `detail` は `unavailable` のときだけ入る。

    `dataclass` を使わないのは、本モジュールが `importlib` で単体ロードされた場合
    （`sys.modules` に登録されない読み込み方。テストや他 script が採りうる）に
    `dataclass` が annotation 解決で失敗するためである。
    """

    def __init__(self, status, startup, port, url, reason_code=None, detail=None, client=None):
        self.status = status
        self.startup = startup
        self.port = port
        self.url = url
        self.reason_code = reason_code
        self.detail = detail
        self.client = client

    @property
    def available(self) -> bool:
        return self.status == STATUS_AVAILABLE

    def __repr__(self) -> str:
        return (
            f"Availability(status={self.status!r}, startup={self.startup!r}, "
            f"port={self.port!r}, reason_code={self.reason_code!r})"
        )


# --- 差し替え可能な境界 -------------------------------------------------------


def spawn_server(executable: str) -> subprocess.Popen:
    """doc-db を新規セッションで起動し、標準入出力を切り離す。

    引数なしの `doc-db` が MCP HTTP サーバを前面で起動する（port は doc-db 自身の設定に従う）。
    forge は起動引数で port やログ先を上書きしない。上書きすると、直後に接続する port が
    doc-db の設定と食い違い、利用者の設定を forge が黙って変えることになる。

    標準入出力を `DEVNULL` にする理由と、ログファイルを作らない理由は module docstring 参照。
    """
    return subprocess.Popen(
        [executable],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def make_client_factory(port: int, transport=None, config_path=None):
    """`timeout` を受けて `Client` を返す factory を作る。

    probe と operation で timeout が異なるため（probe は 1 秒、operation は 600 秒）、
    Client の生成を factory に包んで timeout だけを呼び出し側から差し替えられるようにする。
    """

    def factory(timeout):
        kwargs = {"port": port, "timeout": timeout, "config_path": config_path}
        if transport is not None:
            kwargs["transport"] = transport
        return docdb_client.Client(**kwargs)

    return factory


# --- 接続 probe ---------------------------------------------------------------


def _failure_detail(exc):
    """probe 失敗の理由を、秘密値を含み得ない要素だけで組み立てる。

    **例外メッセージの生文字列を利用者向け出力へ載せてはならない。**
    HTTP エラーの例外メッセージにはサーバ応答の body がそのまま含まれる。
    doc-db や前段の proxy が認証エラー時に body へ設定値・資格情報・接続文字列を
    載せた場合、それが wrapper の利用者向け出力へ流出する。

    そのため detail には次だけを載せる: 失敗の分類（例外クラス名）と、
    HTTP エラーの場合の status code・URL。URL は localhost と port のみで、
    認証情報を含まない（port は設定ファイルから読む整数値のみ）。
    """
    if isinstance(exc, docdb_client.HttpError):
        return f"{type(exc).__name__}: HTTP {exc.status} ({exc.url})"
    return type(exc).__name__


def probe(client_factory, timeout=docdb_client.PROBE_TIMEOUT_SECONDS):
    """MCP `initialize` を 1 回試み、`(Client または None, 失敗理由の文字列 または None)` を返す。

    `initialize` が成功した Client をそのまま返すのは、同一 operation 内で session を
    使い回すためである（probe 用に確立した session を捨てて再接続すると、
    initialize が 2 回走り、その間にサーバが落ちる隙も増える）。

    `docdb_client` の例外はすべて「接続できなかった」として畳む。
    HTTP エラーや protocol エラーは接続そのものは成立しているが、MCP session を
    確立できていない点は transport エラーと同じであり、この段階では区別しても
    後続処理が変わらない（利用可否の根拠は `initialize` の成功だけである）。

    失敗理由は `_failure_detail()` が組み立てた要素のみを返す（例外メッセージの
    生文字列は返さない。理由は同関数の docstring を参照）。
    """
    client = client_factory(timeout)
    try:
        client.initialize()
    except docdb_client.DocDbClientError as exc:
        return None, _failure_detail(exc)
    return client, None


# --- 利用可否の確定 -----------------------------------------------------------


def ensure_available(
    *,
    port: int | None = None,
    config_path=None,
    transport=None,
    client_factory=None,
    which=shutil.which,
    spawn=spawn_server,
    sleep=time.sleep,
    now=time.monotonic,
    probe_timeout=docdb_client.PROBE_TIMEOUT_SECONDS,
    deadline=docdb_client.STARTUP_DEADLINE_SECONDS,
    retry_interval=docdb_client.STARTUP_RETRY_INTERVAL_SECONDS,
) -> Availability:
    """接続 probe → 実行ファイル解決 → on-demand 起動 → 期限付き再接続を順に行う。

    `client_factory` を注入する場合は `port` も渡すこと（結果に載せる port / URL の
    解決に使う。渡さなければ doc-db の設定ファイルから port を読む）。
    """
    resolved_port = docdb_client.read_port(config_path) if port is None else int(port)
    url = docdb_client.endpoint_url(resolved_port)
    factory = client_factory or make_client_factory(
        resolved_port, transport=transport, config_path=config_path
    )

    def _available(startup, client):
        return Availability(
            status=STATUS_AVAILABLE, startup=startup, port=resolved_port, url=url, client=client
        )

    def _unavailable(reason_code, detail):
        return Availability(
            status=STATUS_UNAVAILABLE,
            startup=STARTUP_FAILED,
            port=resolved_port,
            url=url,
            reason_code=reason_code,
            detail=detail,
        )

    client, detail = probe(factory, probe_timeout)
    if client is not None:
        return _available(STARTUP_NOT_ATTEMPTED, client)

    executable = which(DOCDB_EXECUTABLE)
    if not executable:
        return _unavailable(
            REASON_EXECUTABLE_MISSING,
            f"{DOCDB_EXECUTABLE} 実行ファイルが PATH 上に見つかりません（接続も失敗: {detail}）",
        )

    try:
        process = spawn(executable)
    except OSError as exc:
        return _unavailable(
            REASON_SPAWN_FAILED, f"{DOCDB_EXECUTABLE} の起動に失敗しました: {exc}"
        )

    return _reconnect_after_startup(
        process,
        factory,
        available=_available,
        unavailable=_unavailable,
        sleep=sleep,
        now=now,
        probe_timeout=probe_timeout,
        deadline=deadline,
        retry_interval=retry_interval,
    )


def _reconnect_after_startup(
    process,
    factory,
    *,
    available,
    unavailable,
    sleep,
    now,
    probe_timeout,
    deadline,
    retry_interval,
) -> Availability:
    """起動したプロセスに対し、期限内で MCP 接続を繰り返し試みる。

    停止条件は 3 つある。

    1. 接続成功 → 利用可能（`startup=succeeded`）
    2. プロセスが終了していた → 猶予 1 回の再試行のみ行い、それでも接続できなければ
       `docdb_exited_early`
    3. 期限切れ → `docdb_reconnect_failed`

    2 の猶予 1 回は「別 wrapper が先に doc-db を起動しており、こちらのプロセスが
    重複起動として自ら終了した」場合のためである。この場合、接続先は先行プロセスであり、
    そちらが listen を開始するまで僅かに遅れることがある。ただし自分のプロセスが
    既に無いことは確定しているため、期限いっぱい待つ意味はない（待っても自分の
    プロセスが listen し始めることはない）。よって猶予は 1 回に限る。
    """
    start = now()
    while True:
        client, detail = probe(factory, probe_timeout)
        if client is not None:
            return available(STARTUP_SUCCEEDED, client)

        exit_code = process.poll()
        remaining = deadline - (now() - start)

        if exit_code is not None:
            if remaining > 0:
                sleep(min(retry_interval, remaining))
            client, detail = probe(factory, probe_timeout)
            if client is not None:
                return available(STARTUP_SUCCEEDED, client)
            return unavailable(
                REASON_EXITED_EARLY,
                f"{DOCDB_EXECUTABLE} プロセスが接続確立前に終了しました"
                f"（exit code {exit_code}、接続失敗: {detail}）",
            )

        if remaining <= 0:
            return unavailable(
                REASON_RECONNECT_FAILED,
                f"{DOCDB_EXECUTABLE} を起動しましたが {deadline} 秒以内に接続できませんでした"
                f"（接続失敗: {detail}）",
            )

        sleep(min(retry_interval, remaining))
