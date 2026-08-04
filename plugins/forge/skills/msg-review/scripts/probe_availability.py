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

## 副作用を持たない [MANDATORY]

3 つの判定はいずれも読み取りのみである。依頼を送らず、起床（`cmux send` /
`send-key` によるテキスト注入）も行わない。本体は複数候補を順に検査するため、
検査自体が相手の状態を変えてはならない（forge:ADR-067 §2.1）。

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
    """
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"{Path(args[1]).name} の実行に失敗しました: {type(exc).__name__}"
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()
        reason = f"{Path(args[1]).name} が非ゼロ終了しました"
        return None, f"{reason}: {detail}" if detail else reason
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, f"{Path(args[1]).name} の出力が JSON として解析できません"
    if not isinstance(payload, dict):
        return None, f"{Path(args[1]).name} の出力が mapping ではありません"
    return payload, None


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


def _evaluate_setup(project_root, run_json) -> tuple[dict | None, list]:
    """軸 `setup` を評価する。戻り値は `(missing 要素 | None, warnings)`。"""
    payload, error = run_json(
        [sys.executable, str(CHECK_SETUP_SCRIPT), "--project-root", str(project_root)]
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
    return (
        {
            "axis": AXIS_SETUP,
            "detail": "msg-sys の設定が不足しています — " + " / ".join(failed)
            if failed
            else "msg-sys の設定が不足しています",
            "remedy": (
                "forge プラグインの再インストール、または .codex/hooks.json の"
                "登録状態を確認してください"
            ),
        },
        warnings,
    )


# --- 集約 ----------------------------------------------------------------------


def probe(project_root, *, run_json=_run_json) -> dict:
    """3 軸を評価し、可用性検査の結果を返す。

    `run_json` はテストの差し替え境界。既定は本番実装（subprocess 実行）。
    """
    missing = []
    for entry in (
        _evaluate_wake(project_root, run_json),
        _evaluate_peer(project_root, run_json),
    ):
        if entry is not None:
            missing.append(entry)

    setup_missing, warnings = _evaluate_setup(project_root, run_json)
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
