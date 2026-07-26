#!/usr/bin/env python3
"""msg-sys Stop フック本体。

msg-sys既存 CLI を subprocess 経由で呼び出し、未読メッセージに
返信ヒントを付加して差し戻す。Claude/Codex 双方から
FORGE_MSG_AGENT_NAME を切り替えて共有される単一スクリプト。

DES-034 §4.2 処理順序1〜8（FORGE_MSG_AGENT_NAME検証・db_path解決・inbox.py --next呼び出し・
返却JSON検証・往復上限比較・decision:block構築・ack・出力）と catch-all を実装する。
"""

import json
import os
import shlex
import subprocess
import sys

VALID_AGENT_NAMES = ("claude", "codex")


def _msg_sys_dir():
    # symlink 経由で起動された場合、abspath は __file__ のリンク側パスをそのまま
    # 返すため、".." での相対移動先を誤解決する（Issue #226）。realpath でリンクを
    # 解決してから相対移動することで、実体パス直接起動時と同じ結果になる。
    here = os.path.dirname(os.path.realpath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "msg-sys"))


def _continue_true():
    print(json.dumps({"continue": True}))


def resolve_agent_name():
    """FORGE_MSG_AGENT_NAME を検証する（既定値なし、fail-closed。DES-034 §4.2 順序1）。"""
    name = os.environ.get("FORGE_MSG_AGENT_NAME", "")
    if name not in VALID_AGENT_NAMES:
        return None
    return name


def resolve_db_path():
    """db_path を解決する（DES-034 §4.2 順序2）。

    FORGE_MSG_PROJECT_ROOT 未設定時は cwd 等へフォールバックせず解決失敗として扱う
    （§4.3 順序2）。cwd がプロジェクトルートと一致する保証はないため。
    """
    project_root = os.environ.get("FORGE_MSG_PROJECT_ROOT")
    if not project_root:
        return None
    return os.path.join(project_root, ".claude", ".temp", "msg-sys", "messages.db")


def fetch_next(agent_name, db_path, msg_sys_dir):
    """inbox.py --next を呼ぶ（DES-034 §4.2 順序3）。戻り値: (payload, ok)。"""
    inbox_py = os.path.join(msg_sys_dir, "inbox.py")
    try:
        result = subprocess.run(
            [sys.executable, inbox_py, agent_name, "--next", "--db-path", db_path],
            capture_output=True,
            text=True,
        )
    except OSError:
        return None, False
    if result.returncode != 0:
        return None, False
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, False
    return payload, True


def validate_message(payload, agent_name):
    """返却 JSON を検証する（DES-034 §4.2 順序4）。不正なら None を返す。"""
    if not isinstance(payload, dict):
        return None
    msg_id = payload.get("id")
    sender = payload.get("sender")
    body = payload.get("body")
    chain_length = payload.get("chain_length")
    if not isinstance(msg_id, str) or not msg_id:
        return None
    if not isinstance(body, str):
        return None
    # sender は FORGE_MSG_AGENT_NAME の相手側1値のみ許容する。
    # これにより自己宛メッセージ（sender == agent_name）も同時に排除する。
    expected_sender = "codex" if agent_name == "claude" else "claude"
    if sender != expected_sender:
        return None
    # bool は int のサブクラスのため isinstance では true/false を誤って受理する。
    if type(chain_length) is not int:
        return None
    return {"id": msg_id, "sender": sender, "body": body, "chain_length": chain_length}


def resolve_round_trip_limit():
    """FORGE_MSG_MAX_ROUND_TRIPS を解決する（正の整数以外は None、DES-034 §4.3 順序5）。"""
    raw = os.environ.get("FORGE_MSG_MAX_ROUND_TRIPS", "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def notify_human(agent_name, db_path, message, msg_sys_dir):
    """上限到達・上限値不正時の人間通知経路を呼ぶ。"""
    notify_py = os.path.join(msg_sys_dir, "lib", "notify.py")
    ack_hint = "inbox.py {} --ack {} --db-path {}".format(
        agent_name, message["id"], db_path
    )
    try:
        result = subprocess.run(
            [
                sys.executable,
                notify_py,
                "--recipient", agent_name,
                "--message-id", message["id"],
                "--sender", message["sender"],
                "--body", message["body"],
                "--ack-hint", ack_hint,
            ],
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return result.returncode == 0


def mark_notified(agent_name, db_path, message_id, msg_sys_dir):
    """notify.py 成功時のみ呼ぶ。失敗しても出力契約（continue:true）は壊さない。"""
    inbox_py = os.path.join(msg_sys_dir, "inbox.py")
    try:
        subprocess.run(
            [sys.executable, inbox_py, agent_name, "--mark-notified", message_id, "--db-path", db_path],
            capture_output=True,
            text=True,
        )
    except OSError:
        pass


def build_reply_hint(agent_name, message, db_path, msg_sys_dir):
    """返信ヒントを構築する（DES-034 §4.2「返信ヒントの実行可能性契約」）。

    引数列（python3/send.py/宛先/送信者/--in-reply-to/--db-path）は shlex.join() で
    引用し、リダイレクト演算子 `<` と一時ファイルパスはこの引用対象に含めない
    （`<` を引数として渡すとリダイレクトとして機能しないため、文字列連結で分離する）。
    一時ファイルパスはメッセージ id を組み込み、配信元メッセージごとに一意にする。
    """
    send_py = os.path.join(msg_sys_dir, "send.py")
    tmp_path = "/tmp/forge_msg_reply_{}.txt".format(message["id"])
    # sender=agent_name（この hook 自身の宛先）、recipient=配信元メッセージの sender（返信先）。
    argv = [
        sys.executable,
        send_py,
        agent_name,
        message["sender"],
        "-",
        "--in-reply-to", message["id"],
        "--db-path", db_path,
    ]
    command = shlex.join(argv) + " < " + shlex.quote(tmp_path)
    return (
        "返信する場合:\n"
        "1. 返信本文を、シェルコマンドを経由せず（heredoc・echo・printf 等を使わず）"
        "ファイル書き込み機能で一時ファイル {tmp} に書き出す\n"
        "2. 次のコマンドを実行する:\n"
        "   {cmd}\n"
        "3. 送信成功後、一時ファイル {tmp} を削除する"
    ).format(tmp=tmp_path, cmd=command)


def build_decision_block(agent_name, message, db_path, msg_sys_dir):
    """decision:block の完全な出力 JSON 文字列を構築する（DES-034 §4.2 順序6）。"""
    reply_hint = build_reply_hint(agent_name, message, db_path, msg_sys_dir)
    reason = "[id:{}] [from {}] {}\n\n{}".format(
        message["id"], message["sender"], message["body"], reply_hint
    )
    return json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False)


def ack_message(agent_name, message_id, db_path, msg_sys_dir):
    """inbox.py --ack を呼ぶ（DES-034 §4.2 順序7）。"""
    inbox_py = os.path.join(msg_sys_dir, "inbox.py")
    try:
        result = subprocess.run(
            [sys.executable, inbox_py, agent_name, "--ack", message_id, "--db-path", db_path],
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return result.returncode == 0


def write_decision_block(text):
    """構築済み文字列を UTF-8 で標準出力へ書き出す（DES-034 §4.2 順序8）。

    呼び出し元でこの関数を最上位 catch-all の外に置くこと。ack 成功後の書き込み失敗
    （BrokenPipeError/UnicodeEncodeError 等）は再送・fallback を一切行わない
    （§4.3 順序8、消失を許容する設計判断）。
    """
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)


def _process():
    """順序1〜7を実行する。順序8で出力すべき文字列を返すか、None（continue:true出力済み）。"""
    agent_name = resolve_agent_name()
    if agent_name is None:
        _continue_true()
        return None

    db_path = resolve_db_path()
    if db_path is None:
        _continue_true()
        return None

    msg_sys_dir = _msg_sys_dir()

    payload, ok = fetch_next(agent_name, db_path, msg_sys_dir)
    if not ok:
        _continue_true()
        return None

    if payload is None:
        _continue_true()
        return None

    message = validate_message(payload, agent_name)
    if message is None:
        _continue_true()
        return None

    limit = resolve_round_trip_limit()
    if limit is None or message["chain_length"] >= limit:
        # notify.py が非ゼロ終了/失敗した場合は --mark-notified を呼ばない
        # （次回 hook 実行でも再度未読として検知され、通知が再試行される）。
        if notify_human(agent_name, db_path, message, msg_sys_dir):
            mark_notified(agent_name, db_path, message["id"], msg_sys_dir)
        _continue_true()
        return None

    try:
        decision_json = build_decision_block(agent_name, message, db_path, msg_sys_dir)
    except Exception:
        # 構築失敗時は ack を行わない（メッセージは未読のまま。DES-034 §4.3 順序6）。
        _continue_true()
        return None

    if not ack_message(agent_name, message["id"], db_path, msg_sys_dir):
        _continue_true()
        return None

    return decision_json


def main():
    # 最上位 catch-all。適用範囲は --ack 成功前（_process() 内部）まで。
    # Exception のみを対象とし、BaseException（SystemExit/KeyboardInterrupt を含む）は
    # 対象外とする（テスト起因の SystemExit や意図的な Ctrl-C 中断を握りつぶさない）。
    try:
        decision_json = _process()
    except Exception:
        _continue_true()
        return

    if decision_json is None:
        return

    # 順序8: ack 成功後の出力。catch-all の対象外（呼び出しをtry/exceptの外に置く）。
    write_decision_block(decision_json)


if __name__ == "__main__":
    main()
