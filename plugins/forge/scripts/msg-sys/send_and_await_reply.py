#!/usr/bin/env python3
"""msg-sys: 返信を期待する送信の複合 CLI（送信 → push型起床 → ブロッキング待機）。

**この 3 手順を 1 回の呼び出しに畳んであることが本スクリプトの存在理由である [MANDATORY]**。
返信を期待して送るとき、3 手順は常に揃って必要であり、どれ 1 つでも欠けると往復が止まる。

    1. 送信（`mailbox.send`）——これが無ければ何も起きない
    2. push型起床（`cmux/wake_codex.sh`）——常駐 Codex の Stop hook は Codex 自身の
       ターン終了時にしか発火しない（pull型）。送信側から起こさない限り、専用常駐
       セッションでは Codex のターンが終わる契機自体が存在せず、依頼は配信されない
    3. ブロッキング待機（`wait_for_reply`）——Claude 側 Stop hook（`check_inbox.py`）は
       **Claude 自身のターン終了時**にしか発火しない。送信してターンを終えると、
       hook は「まだ返信が無い」時点で空振りし、その後 Codex が返信しても引き取る
       契機が無くなる（Claude のターンが走っていない）

**なぜ SKILL.md の散文ではなくスクリプトで束ねるのか**: 2 と 3 はいずれも、SKILL.md に
手順として並べていた時期に実際に落ちた。2 は依頼モードにしか書かれておらず往復 2 ラウンド目
以降が必ず止まり（実運用の 1 レビューで 4 回の手動起床を要した）、`[MANDATORY]` を付けた後も
呼び忘れが起きた。3 は受信モードに存在すらせず、「送信してターンを終える（次の受信は Stop
フック起点）」という**事実に反する記述**が残っていた（Stop フックは Codex の返信では発火せず、
Claude のターン終了で発火する）。同じ欠陥が同じ場所で 2 度起きたのは、必須手順が散文にしか
無かったからである。守られることを期待する契約から、破れない構造へ移した——複数手順を
覚える必要が無くなり、呼び忘れれば「送信されない」という即座に露見する形で失敗する
（沈黙して滞留しない）。

**DB パスは `--project-root` から解決する**: `FORGE_MSG_PROJECT_ROOT` のシェル前置を
呼び出し側に要求しない。前置は呼び出し側の記憶に依存し、実運用で繰り返し忘れられた
（`RuntimeError: DB path could not be resolved`）。`--db-path` の明示指定も引き続き可能。

**DB と相手セッションは独立した軸ではない [MANDATORY]**: 往復の同一性を決めるものは
プロジェクト 1 つであり、「どの DB を使うか」と「どの常駐セッションを起こすか」はその
同じ同一性の 2 つの見え方にすぎない。相手側エージェントは自分の Stop hook で **project root
から解決した DB** を読むため、`--db-path` がそれと食い違う DB を指した状態では、送っても
相手はそのメッセージを見られず、**返信は原理的に成立しない**（送信は別 DB へ入り、起床した
相手は自分の DB を見て何も見つけられず、待機は別 DB を待機予算いっぱいポーリングする）。

したがって両者が食い違う指定は受け付けず、**送信前にエラー終了する**（fail closed）。
成立しない組み合わせを許して 10 分後にタイムアウトさせるより、起動直後に理由を示して
失敗する方が原因が見える。`--files` と `--dirs` の同時指定をエラーにするのと同じ理屈であり、
「どちらを優先するか」を推定しない。

標準ライブラリのみ使用する。

使い方:
    python3 send_and_await_reply.py <sender> <recipient> --body-file <path> \
        --header-regex "<正規表現>" --thread-id <id> \
        [--in-reply-to <id>] [--project-root <path>] [--db-path <path>] \
        [--max-seconds <秒>] [--progress-interval <秒>] [--no-wake]

本文は**必ずファイルから読む**（`--body-file`）。シェル経由（heredoc / echo / printf）で
本文を組み立てる経路を持たせないため、標準入力からは受け取らない。

標準出力: 進捗行（`経過N秒、まだ返信なし`）に続けて、最終行に単一 JSON。
終了コード: 返信を得たら 0、それ以外（送信失敗・タイムアウト）は 1。
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))
sys.path.insert(0, str(_HERE))
import mailbox  # noqa: E402
import wait_for_reply as waiter  # noqa: E402

WAKE_SCRIPT = _HERE / "cmux" / "wake_codex.sh"


def do_send(
    sender: str,
    recipient: str,
    body: str,
    *,
    db_path: Path,
    in_reply_to: str | None,
) -> str:
    """メッセージを 1 件送信し message id を返す。`send.py` と同じ `mailbox.send` を使う。"""
    return mailbox.send(
        sender, recipient, body, db_path=db_path, in_reply_to=in_reply_to
    )


def do_wake(project_root: str | None, *, runner=subprocess.run) -> dict:
    """push型起床を試みる。**失敗しても中断しない（best-effort）**。

    起床の成否は待機の正しさに影響しない（起床は待機時間を短縮する手段であり、
    起床できなくても待機自体は成立する）。ただし結果は最終 JSON に残す——安全ゲートを
    全て通過したうえでの `failed` は「cmux 環境が整っているのに push 起床が構造的に
    壊れている」という診断情報であり、タイムアウトの原因切り分けに必要になる。

    `project_root` が無い場合（`--db-path` のみ指定）は起床対象を特定できないため
    `skipped` を返す。`wake_codex.sh` は project_root を引数に取り、その cwd で稼働する
    Codex ペインを探す設計であるため、代替の推測はしない。
    """
    if not project_root:
        return {
            "status": "skipped",
            "reason": "--project-root が無いため起床対象を特定できません",
        }
    if not WAKE_SCRIPT.is_file():
        return {"status": "skipped", "reason": f"起床スクリプトがありません: {WAKE_SCRIPT}"}

    try:
        result = runner(
            ["bash", str(WAKE_SCRIPT), project_root],
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return {"status": "failed", "reason": f"起床スクリプトの実行に失敗しました: {exc}"}

    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        # 出力を解析できないことは「起床が不要だった」ことを意味しない。skipped に
        # 畳み込むと、実行できなかった起床が意図的な見送りとして隠れる。
        return {
            "status": "failed",
            "reason": "起床スクリプトの出力を解析できませんでした",
        }


def derived_db_path(project_root: str) -> Path:
    """project root から DB パスを導出する（`mailbox.resolve_db_path` の (2) と同じ規則）。"""
    return Path(project_root) / ".claude" / ".temp" / "msg-sys" / "messages.db"


def resolve_consistent_db_path(project_root: str | None, db_path: str | None) -> Path:
    """DB パスを解決し、`--project-root` と食い違う `--db-path` を拒否する [MANDATORY]。

    両者は独立した軸ではない（モジュール docstring 参照）。相手側エージェントは project root
    から DB を解決するため、食い違った DB を指したままでは返信が成立しない。この矛盾は
    「どちらを優先するか」を推定して解決できるものではないため、`ValueError` を送出する。

    一致している場合（同じことを明示しているだけ）は許容する。
    """
    if project_root and db_path:
        derived = derived_db_path(project_root)
        if Path(db_path).resolve() != derived.resolve():
            raise ValueError(
                "--db-path と --project-root が指す DB が一致しません。相手側エージェントは "
                "project root から DB を解決するため、この組み合わせでは返信が届きません"
                f"（--db-path: {db_path} / --project-root から導出: {derived}）。"
                "どちらか一方だけを指定してください"
            )
        return derived

    if db_path:
        return Path(db_path)

    if project_root:
        return derived_db_path(project_root)

    # どちらも無い場合は msg-sys 共通の fail-closed 解決に委ねる
    # （`FORGE_MSG_PROJECT_ROOT` があればそれを使い、無ければ RuntimeError）。
    return mailbox.resolve_db_path(None)


def compile_header_regex(pattern: str) -> re.Pattern[str]:
    """ヘッダ正規表現を compile し、thread_id の capture group の存在まで検証する。

    capture group が無い正規表現は compile 自体は成功するため、検証しないと待機側の
    `match.group(1)` が IndexError で落ちる（`wait_for_reply.py` と同じ契約）。
    """
    compiled = re.compile(pattern)
    if compiled.groups < 1:
        raise ValueError(
            "--header-regex には thread_id を取り出す capture group が"
            "少なくとも1つ必要です（例: '(\\S+)'）"
        )
    return compiled


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="返信を期待する送信（送信 → push型起床 → ブロッキング待機）",
    )
    parser.add_argument("sender")
    parser.add_argument("recipient")
    parser.add_argument(
        "--body-file",
        required=True,
        help="送信本文のファイルパス（シェル経由で本文を組み立てないため必須）",
    )
    parser.add_argument(
        "--header-regex",
        required=True,
        help="body 先頭行から thread_id を抽出する正規表現（capture group 1 が thread_id）",
    )
    parser.add_argument("--thread-id", required=True)
    parser.add_argument(
        "--in-reply-to",
        default=None,
        help=(
            "直前に受信した相手発メッセージの id。スレッド連鎖の判定に使うため、"
            "初回（スレッドの起点）以外の送信では必ず指定する"
        ),
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help=(
            "プロジェクトルート。DB パスの解決と push型起床の対象特定に使う"
            "（両者は同じ同一性の 2 つの見え方であり、独立した軸ではない）"
        ),
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help=(
            "messages.db のパス。`--project-root` と併用する場合は、そこから導出される "
            "DB と一致していなければエラー終了する（食い違うと相手が読む DB と別になり "
            "返信が成立しないため）。起床を止めたい場合は `--no-wake` を使う"
        ),
    )
    parser.add_argument(
        "--max-seconds", type=float, default=waiter.DEFAULT_MAX_SECONDS
    )
    parser.add_argument(
        "--progress-interval",
        type=float,
        default=waiter.DEFAULT_PROGRESS_INTERVAL,
    )
    parser.add_argument(
        "--initial-interval",
        type=float,
        default=waiter.DEFAULT_INITIAL_INTERVAL,
    )
    parser.add_argument(
        "--backoff-factor",
        type=float,
        default=waiter.DEFAULT_BACKOFF_FACTOR,
    )
    parser.add_argument(
        "--max-interval", type=float, default=waiter.DEFAULT_MAX_INTERVAL
    )
    parser.add_argument(
        "--no-wake",
        action="store_true",
        help="push型起床を行わない（cmux 非依存の検証用。通常運用では指定しない）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(sys.argv[1:] if argv is None else argv)

    try:
        header_regex = compile_header_regex(args.header_regex)
    except (re.error, ValueError) as exc:
        print(f"--header-regex が不正です: {exc}", file=sys.stderr)
        return 1

    body_path = Path(args.body_file)
    if not body_path.is_file():
        print(f"本文ファイルが見つかりません: {body_path}", file=sys.stderr)
        return 1
    body = body_path.read_text(encoding="utf-8")

    # DB パスの解決を送信より先に行う（解決できないまま送信・起床を走らせない）。
    # `--project-root` があれば env 前置なしで導出し、`--db-path` との食い違いを拒否する。
    try:
        db_path = resolve_consistent_db_path(args.project_root, args.db_path)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        message_id = do_send(
            args.sender,
            args.recipient,
            body,
            db_path=db_path,
            in_reply_to=args.in_reply_to,
        )
    except Exception as exc:  # noqa: BLE001 — 送信失敗は理由を問わず fail closed
        print(f"送信に失敗しました: {exc}", file=sys.stderr)
        print(
            json.dumps(
                {"status": "send_failed", "error": str(exc)}, ensure_ascii=False
            )
        )
        return 1

    # 送信が成功して初めて起床・待機に進む（送信できていないのに待つと、
    # 来るはずのない返信を待機予算いっぱい待つことになる）。
    wake = (
        {"status": "skipped", "reason": "--no-wake が指定されました"}
        if args.no_wake
        else do_wake(args.project_root)
    )

    try:
        result = waiter.wait_for_reply(
            args.sender,
            args.recipient,
            header_regex,
            args.thread_id,
            max_seconds=args.max_seconds,
            progress_interval=args.progress_interval,
            initial_interval=args.initial_interval,
            backoff_factor=args.backoff_factor,
            max_interval=args.max_interval,
            db_path=str(db_path),
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        print(
            json.dumps(
                {
                    "status": "wait_failed",
                    "sent_message_id": message_id,
                    "wake": wake,
                    "error": str(exc),
                },
                ensure_ascii=False,
            )
        )
        return 1

    # 待機結果を最上位へ展開し（`status` / `messages` / `delivered_ids` は
    # `wait_for_reply.py` 単体呼び出しと同じ位置に置く）、送信・起床の結果を併記する。
    payload = {**result, "sent_message_id": message_id, "wake": wake}
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if result.get("status") == "replied" else 1


if __name__ == "__main__":
    raise SystemExit(main())
