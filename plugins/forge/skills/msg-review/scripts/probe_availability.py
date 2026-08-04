#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""msg-review: 可用性検査の集約 CLI（DES-045 §3.5.2 / REQ-012 FNC-003）。

本バックエンドが利用可能かと、**不足している前提を個別に**返す。本体
（`/forge:review`、継承型 SKILL）がラウンド実行より前に候補バックエンドを選ぶ際、
本バックエンドを Skill ツールで起動し、その中から Bash subprocess として呼ばれる
（forge:REQ-013 FNC-1318 の解決順）。

## 判定は持たない [MANDATORY]

本 CLI は判定を**しない**。軸ごとの判定スクリプトを呼び、結果を契約の形へ
まとめるだけである。判定を軸ごとに独立させる理由は ADR-068 §2.1 にある——
現時点では往復の成立に起床手段と常駐の両方が必要だが、将来 cmux を必要としない
起床経路が成立すれば常駐だけで足りるようになる。そのとき変えるのは本 CLI の
集約条件だけであり、判定ロジックには手を入れない。

| 軸        | 判定スクリプト                          | 判定内容                             |
| --------- | --------------------------------------- | ------------------------------------ |
| `wake`    | `cmux/check_cmux_available.py`          | 起床手段（cmux）が使えるか           |
| `peer`    | `cmux/find_codex_pane.py`               | 相手セッションが常駐しているか       |
| `setup`   | `check_setup.py`                        | msg-sys 側の設定が健全か             |

## 初期化を済ませてから検査する [MANDATORY]

本 CLI は 3 軸の判定より**前に**、本バックエンドの初期化（イニシャルセットアップ）
`ensure_codex_hook.py` を実行する。初期化は Codex 側 Stop フックの登録
（`.codex/hooks.json`）と、そのコマンドが指す実体への symlink
（`.codex/msg-sys/scripts` → 現在ロード中のプラグインの `scripts/msg-sys/`）を用意する。
symlink はマシン固有の絶対パスを含むため非追跡であり、**新規クローン・新規 git
worktree・プラグイン実体パスの変更後には必ず不在**である——壊れているのではなく、
そのチェックアウトでまだ作られていない。冪等なので、済んでいれば何もしない。

**未初期化の状態を検査してはならない**。初期化前に検査すると、初期化すれば使える環境を
「使えない」と判定し、本体が fail closed して初期化に到達しなくなる（初期化する唯一の
経路が、初期化されていないことを理由に封じられる）。それは前提の可否を測っているのでは
なく、初期化していないことを測っているだけである。実際にこの順序で `/forge:review` が
新規環境で恒久的に使えなくなる不具合が起きた。

初期化を散文の手順として本 SKILL.md 側に置かず本 CLI の内側に置くのは、**順序を構造で
保証する**ためである（同 SKILL では、散文にしか無い必須手順である起床・待機が実際に
忘れられ、`send_and_await_reply.py` へ畳んで解決した前例がある）。

初期化を完了できなかった場合（symlink であるべき場所に人間由来の実体がある等）は、
その理由を軸 `setup` の不足へ添える。初期化の失敗を検査結果として隠さない。

## 相手に作用しない [MANDATORY]

依頼を送らず、起床（`cmux send` / `send-key` によるテキスト注入）も行わない。本体は
複数候補を順に検査するため、**検査が相手（レビュアー）の状態を変えてはならない**
（forge:ADR-067 §2.1 / ADR-068 §2.3）。

自分の設定の初期化はこの禁止に含まれない。初期化は検査対象を成立させる前準備であり、
相手のセッションにも他候補のバックエンドにも作用しない（`.codex/` は Codex 向け設定で
あり、本バックエンド自身の持ち物である）。また人間由来のファイルを上書きせず、
競合は報告のみに留める（`ensure_codex_hook.py`）。

## 画面の読み取りを行わない [MANDATORY]

`cmux capture-pane` / `read-screen` を呼ばない。軸 `peer` は稼働中の Codex
プロセスを直接確認する一次情報に基づくため、画面表示からの推測は前提の判定材料を
追加しない。推測を根拠に利用不可を返すと、実際には応答できた相手の機会を奪う
（ADR-068 §2.1 / §2.2）。

なお起床の直前に画面を読む処理は別に存在する（`wake_codex.sh`）。あちらは
「注入して相手の作業を壊さないための安全ゲート」であり目的が異なる。本 CLI が
持たないのは**前提の判定に画面を使うこと**である。

## 「使えません」に畳み込まない [MANDATORY]

不足は軸ごとに 1 件として `missing` に並べる。利用者が何を用意すれば解消するかを
判断できるよう、各件に `detail`（何が不足しているか）と `remedy`（対処）を持たせる。

**`available` と `missing` は同義である**。`available: true` のとき `missing` は
必ず空であり、逆も成り立つ。両者が食い違う出力は作らない。

## 相手の常駐を「不在」と断定しない

軸 `peer` の判定は `find_codex_pane.py` の 4 状態を区別して扱う。とくに
`error`（cmux への問い合わせ自体が失敗）を「常駐していない」と報告しない——
判定できなかったことと、判定して不在だったことは、利用者の対処が異なる。

## exit code / JSON 契約

終了コードは常に 0 である（利用不可は異常ではなく検査結果であり、`available` で
表す）。判定スクリプトの呼び出しに失敗した場合も、その軸の不足として `missing` に
載せて 0 を返す（検査自体が失敗したことを、検査結果として返す）。

```json
{
  "available": false,
  "missing": [{"axis": "wake", "detail": "...", "remedy": "..."}],
  "warnings": ["..."]
}
```

`warnings` は `check_setup.py` が返す機械検査不能項目をそのまま通す（本 CLI は
msg-sys の警告文を書き換えない）。

## 依存

Python 標準ライブラリのみ。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# --- スクリプトの所在 ---------------------------------------------------------

#: 本ファイルは `plugins/forge/skills/msg-review/scripts/` に置かれているため、
#: 4 階層上が forge プラグインルート（`plugins/forge/`）になる。
_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_MSG_SYS_DIR = _PLUGIN_ROOT / "scripts" / "msg-sys"
_CMUX_DIR = _MSG_SYS_DIR / "cmux"

CHECK_CMUX_SCRIPT = _CMUX_DIR / "check_cmux_available.py"
FIND_PANE_SCRIPT = _CMUX_DIR / "find_codex_pane.py"
CHECK_SETUP_SCRIPT = _MSG_SYS_DIR / "check_setup.py"

#: 初期化（イニシャルセットアップ）。3 軸の判定より前に必ず実行する
ENSURE_HOOK_SCRIPT = _MSG_SYS_DIR / "ensure_codex_hook.py"

# --- 軸の識別子 ---------------------------------------------------------------

AXIS_WAKE = "wake"
AXIS_PEER = "peer"
AXIS_SETUP = "setup"

#: 判定タイムアウト（秒）。可用性検査は安価でなければならないため短く取る
_TIMEOUT_SECONDS = 30


# --- 判定スクリプトの呼び出し ---------------------------------------------------


def _run_json(args: list[str]) -> tuple[dict | None, str | None]:
    """判定スクリプトを実行し、パース済み JSON か失敗理由を返す。

    戻り値は `(payload, error)`。`error` が非 None のときは判定できなかった。

    **判定の答えは JSON の `status` であり、exit code では分岐しない [MANDATORY]**。
    `find_codex_pane.py` は `found` 以外で exit 1 を返す（`wake_codex.sh` が
    「注入対象が確定したか」を exit code で判定するため、そちらの契約は変えられない）。
    exit code で先に切ると、`not_found` / `ambiguous` という**判定できた結果**が
    「判定できなかった」に畳み込まれ、軸ごとに用意した detail・remedy が本番では
    一切使われない（常駐していないだけの利用者に「cmux の動作を確認してください」と
    誤った対処を示す状態になっていた）。したがって stdout が mapping として読めれば
    それを採用し、読めない場合に限って失敗として扱う。
    """
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"{Path(args[1]).name} の実行に失敗しました: {type(exc).__name__}"
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return payload, None

    name = Path(args[1]).name
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()
        reason = f"{name} が判定結果を出力せず非ゼロ終了しました"
        return None, f"{reason}: {detail}" if detail else reason
    if payload is None:
        return None, f"{name} の出力が JSON として解析できません"
    return None, f"{name} の出力が mapping ではありません"


# --- 初期化（イニシャルセットアップ） -------------------------------------------


def _initialize(project_root, run_json) -> str | None:
    """本バックエンドの初期化を実行し、完了できなかった理由を返す（完了なら None）。

    3 軸の判定より前に呼ぶ。冪等であり、済んでいれば何も変更しない。
    戻り値は軸 `setup` の不足へ添える診断文であり、これ自体を不足として数えない
    （初期化の成否は `check_setup.py` が実際の状態として判定する）。
    """
    payload, error = run_json(
        [
            sys.executable,
            str(ENSURE_HOOK_SCRIPT),
            "--project-root",
            str(project_root),
            "--plugin-msg-sys-dir",
            str(_MSG_SYS_DIR),
        ]
    )
    if error is not None:
        return f"初期化を実行できませんでした（{error}）"

    reasons = []
    symlink = payload.get("symlink")
    if isinstance(symlink, dict) and symlink.get("status") == "conflict":
        reasons.append(
            f"{symlink.get('path')} に人間由来の実体があるため symlink を作成できませんでした"
        )
    hooks_json = payload.get("hooks_json")
    if isinstance(hooks_json, dict) and hooks_json.get("status") in (
        "error",
        "skipped_due_to_symlink_conflict",
    ):
        reasons.append(
            ".codex/hooks.json を更新できませんでした"
            f"（{hooks_json.get('reason') or hooks_json.get('status')}）"
        )
    return " / ".join(reasons) if reasons else None


# --- 軸ごとの評価 ---------------------------------------------------------------


def _evaluate_wake(project_root, run_json) -> dict | None:
    """軸 `wake` を評価する。不足なら missing 要素、満たしていれば None。"""
    payload, error = run_json([sys.executable, str(CHECK_CMUX_SCRIPT)])
    if error is not None:
        return {
            "axis": AXIS_WAKE,
            "detail": f"起床手段の可用性を判定できませんでした（{error}）",
            "remedy": "forge プラグインの導入状態を確認してください",
        }
    if payload.get("status") != "available":
        return {
            "axis": AXIS_WAKE,
            "detail": payload.get("reason") or "起床手段（cmux）が利用できません",
            "remedy": (
                "端末多重化ツール cmux を導入し PATH に含めるか、"
                "cmux を必要としない別のレビューバックエンドを選んでください"
            ),
        }
    return None


def _evaluate_peer(project_root, run_json) -> dict | None:
    """軸 `peer` を評価する。不足なら missing 要素、満たしていれば None。

    `find_codex_pane.py` の 4 状態を区別する。`error` は「判定できなかった」で
    あり「常駐していない」ではないため、detail・remedy を分ける。
    """
    payload, error = run_json(
        [sys.executable, str(FIND_PANE_SCRIPT), str(project_root)]
    )
    if error is not None:
        return {
            "axis": AXIS_PEER,
            "detail": f"相手セッションの常駐を判定できませんでした（{error}）",
            "remedy": "cmux が正常に動作しているかを確認してください",
        }

    status = payload.get("status")
    if status == "found":
        return None

    if status == "not_found":
        return {
            "axis": AXIS_PEER,
            "detail": (
                "このプロジェクトを作業ディレクトリとする常駐 Codex セッションが"
                "見つかりません"
            ),
            "remedy": (
                "プロジェクトルートで Codex セッションを常駐起動するか、"
                "別のレビューバックエンドを選んでください"
            ),
        }
    if status == "ambiguous":
        return {
            "axis": AXIS_PEER,
            "detail": (
                "常駐 Codex セッションの候補が複数見つかり、どれを相手とするか"
                "決められません"
            ),
            "remedy": "このプロジェクトに対する常駐 Codex セッションを 1 つに絞ってください",
        }
    # `error`、および将来 find_codex_pane が追加しうる未知の status。
    # いずれも「常駐していない」と断定せず、判定不能として返す。
    return {
        "axis": AXIS_PEER,
        "detail": (
            "相手セッションの常駐を判定できませんでした"
            f"（{payload.get('reason') or f'判定結果が {status} でした'}）"
        ),
        "remedy": "cmux が正常に動作しているかを確認してください",
    }


def _evaluate_setup(project_root, run_json, init_note=None) -> tuple[dict | None, list]:
    """軸 `setup` を評価する。戻り値は `(missing 要素 | None, warnings)`。

    **初期化（`_initialize`）を済ませた状態に対して呼ぶ**。`init_note` は初期化を
    完了できなかった理由（完了時は None）で、不足を返す場合に添える。
    """
    payload, error = run_json(
        [
            sys.executable,
            str(CHECK_SETUP_SCRIPT),
            "--project-root",
            str(project_root),
        ]
    )
    if error is not None:
        return (
            {
                "axis": AXIS_SETUP,
                "detail": f"msg-sys の設定を判定できませんでした（{error}）",
                "remedy": "forge プラグインの導入状態を確認してください",
            },
            [],
        )

    warnings = payload.get("warnings")
    warnings = list(warnings) if isinstance(warnings, list) else []

    if payload.get("status") == "ok":
        return None, warnings

    checks = payload.get("checks")
    failed = []
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, dict) and not check.get("ok"):
                failed.append(f"{check.get('name')}: {check.get('detail')}")
    detail = (
        "msg-sys の設定が不足しています — " + " / ".join(failed)
        if failed
        else "msg-sys の設定が不足しています"
    )
    remedy = (
        "forge プラグインの再インストール、または .codex/hooks.json の"
        "登録状態を確認してください"
    )
    if init_note is not None:
        # 初期化が完了していれば起きないはずの不足である。初期化の失敗を隠すと、
        # 利用者は「なぜ用意されなかったのか」を知らずに設定の再確認へ誘導される
        detail = f"{detail}（初期化: {init_note}）"
        remedy = f"初期化を完了できていません。{init_note}。手動で解消してください"
    return ({"axis": AXIS_SETUP, "detail": detail, "remedy": remedy}, warnings)


# --- 集約 ----------------------------------------------------------------------


def probe(project_root, *, run_json=_run_json) -> dict:
    """初期化を済ませてから 3 軸を評価し、可用性検査の結果を返す。

    **初期化は 3 軸の判定より前に行う [MANDATORY]**（module docstring「初期化を
    済ませてから検査する」）。未初期化の状態を検査すると、初期化すれば使える環境を
    利用不可と判定し、初期化へ到達する経路そのものを封じる。

    `run_json` はテストの差し替え境界。既定は本番実装（subprocess 実行）。
    """
    init_note = _initialize(project_root, run_json)

    missing = []
    for entry in (
        _evaluate_wake(project_root, run_json),
        _evaluate_peer(project_root, run_json),
    ):
        if entry is not None:
            missing.append(entry)

    setup_missing, warnings = _evaluate_setup(project_root, run_json, init_note=init_note)
    if setup_missing is not None:
        missing.append(setup_missing)

    # `available` は missing が空であることそのものである（両者を独立に組み立てて
    # 食い違わせない）
    return {"available": not missing, "missing": missing, "warnings": warnings}


# --- CLI ----------------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "msg-review バックエンドの可用性を検査し、利用可否と不足している前提を"
            " JSON で出力する（read-only）"
        )
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="プロジェクトルートのパス（省略時: カレントディレクトリ）",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    project_root = Path(args.project_root) if args.project_root else Path.cwd()
    print(json.dumps(probe(project_root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
