#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""レビューバックエンドの解決順を設定から決める専用 CLI（DES-066 §2.1 / §2.2）。

本体（`/forge:review`）は最初に本 CLI で「明示指定があるか」「無ければどの順で
候補を試すか」を決め、その順に各バックエンドの可用性検査を呼ぶ。可用性の判定は
各バックエンドが所有し、**順序だけを本体が名前として持つ**（forge:REQ-013
FNC-1318「バックエンド固有の事情を本体に持ち込まない」）。

## 解決の手順（DES-066 §2.1）

| 順 | 条件                       | 本 CLI が返すもの                                     |
| -- | -------------------------- | ----------------------------------------------------- |
| 1  | `--backend X` が指定された | `mode=explicit`、`order=[X]`（source=argument）        |
| 2  | `.forge.yaml` の `backend` | `mode=explicit`、`order=[X]`（source=setting）         |
| 3  | どちらも無い               | `mode=order`、`order=DEFAULT_ORDER`（source=default）  |

`mode` は可用性検査が不可だったときの本体の動作を分ける。`explicit` は
**fail closed**（代替を選ばない。利用者・プロジェクトが選んだ以上、満たせない
なら失敗させる）、`order` は次候補へ進み、全滅で fail closed とする。

**本 CLI は可用性検査を行わない。** 検査は各バックエンドの責務であり、本 CLI が
返すのは「どれをどの順に検査するか」だけである。

## 既定の候補順

明示指定が無いときの順序は本モジュールの `DEFAULT_ORDER` 1 箇所で定義する。
外部依存を持たない `agent-review` を第一候補、常駐セッションと通信基盤を使う
`msg-review` を第二候補とする。

## 設定（`.claude/.forge.yaml` の `review` セクション）

**許容キーは `backend`（文字列）のみである。** 設定ファイルは既定の挙動を 1 点だけ
矯正する手段であり（DES-061 §2.1 のとおりファイルは任意で、無くても全機能が既定で
動く）、機能の一翼を担わせない。候補順を設定から差し替えるキーは置かない——それは
選択ではなく解決アルゴリズムの定義であり、設定ファイルへ出す対象ではない。

| 設定の状態                 | 出力                                                    |
| -------------------------- | ------------------------------------------------------- |
| 未指定・ファイル不在       | `mode=order` / 既定の候補順（`source=default`）          |
| `backend: X`               | `mode=explicit` / `[X]`（`source=setting`）              |
| 不正（許容する形に反する） | exit 20 / `settings_invalid`。**推測で既定値に落ちない** |

不正には、セクションが mapping でない・未知のキーを含む（綴り誤りを黙って無視すると
指定が効いていないことに気づけない）・値が空でない文字列でない・解析不能
（`SettingsError`）を含む。

## exit code / JSON 契約

| exit code | `status`          | 意味                                      |
| --------- | ----------------- | ----------------------------------------- |
| 0         | `success`         | 解決した（`mode` / `order` / `source`）    |
| 20        | `operation_error` | 設定不正（`reason_code=settings_invalid`） |

不正時の `mode` / `order` / `source` は null であり、既定値を入れない（読めない
設定を黙って無視して既定で動くと、利用者が意図した実行主体と異なる側で静かに
レビューが走る）。

## 情報保護

エラーメッセージに設定値そのものを載せない。診断にはキー名のみを載せる
（キー名は構造であり、綴り誤りの発見に必要）。

## テスト境界

`run()` は `settings` を差し替えられる。既定は本番実装（`forge_settings`）。

## 依存

Python 標準ライブラリのみ。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

#: 本ファイルは `plugins/forge/skills/review/scripts/` に置かれているため、
#: 4 階層上が forge プラグインルート（`plugins/forge/`）になる。
_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))
import forge_settings  # noqa: E402

# --- 定数 ---------------------------------------------------------------------

EXIT_SUCCESS = 0
EXIT_OPERATION_ERROR = 20

STATUS_SUCCESS = "success"
STATUS_OPERATION_ERROR = "operation_error"

OPERATION = "resolve_review_backend"

REASON_SETTINGS_INVALID = "settings_invalid"

#: 解決の形。`explicit` は不可なら fail closed、`order` は次候補へ進む
MODE_EXPLICIT = "explicit"
MODE_ORDER = "order"

#: `order` の由来
SOURCE_ARGUMENT = "argument"
SOURCE_SETTING = "setting"
SOURCE_DEFAULT = "default"

#: 既定の候補順。**既定値の定義点はこの 1 箇所のみ**（DES-066 §2.1）
DEFAULT_ORDER = ("agent-review", "msg-review")

#: 設定のセクション名とスキーマ（スキーマの所有は DES-066 §2.2）
#:
#: **許容キーは `backend` だけである [MANDATORY]**。候補順を設定から書き替えるキー
#: （かつて存在した `backend_order`）は置かない。設定ファイルは既定の挙動を 1 点
#: 矯正する手段であり、解決アルゴリズムの定義を持つ場所ではない。順序は本モジュールの
#: `DEFAULT_ORDER` と DES-066 §2.1 が持つ。ここへキーを足すと、順序を決めた理由
#: （前提が重いものから先に試す）が設計書に残ったまま結果だけが外部化される。
SETTINGS_SECTION = "review"
SETTINGS_BACKEND_KEY = "backend"
_ALLOWED_KEYS = (SETTINGS_BACKEND_KEY,)

_DISPLAY_NAME = ".claude/.forge.yaml"


# --- 内部例外 -------------------------------------------------------------------


class _SettingsInvalid(Exception):
    """設定が許容する形に反していた（exit 20 / `settings_invalid`）。"""


# --- 設定の読み取り ---------------------------------------------------------------


def _read_section(project_root, settings) -> dict:
    try:
        return settings.section(project_root, SETTINGS_SECTION)
    except settings.SettingsError as exc:
        # 構文エラー・読取失敗・非 mapping セクションはいずれもここへ届く
        raise _SettingsInvalid(str(exc)) from exc


def _validate_keys(section) -> None:
    unknown = sorted(key for key in section if key not in _ALLOWED_KEYS)
    if unknown:
        raise _SettingsInvalid(
            f"{_DISPLAY_NAME} の {SETTINGS_SECTION} セクションに未知のキーがあります: "
            f"{', '.join(unknown)}（許容キーは {' / '.join(_ALLOWED_KEYS)}）"
        )


def _read_backend(section) -> str | None:
    if SETTINGS_BACKEND_KEY not in section:
        return None
    value = section[SETTINGS_BACKEND_KEY]
    if not isinstance(value, str) or not value.strip():
        raise _SettingsInvalid(
            f"{_DISPLAY_NAME} の {SETTINGS_SECTION}.{SETTINGS_BACKEND_KEY} が"
            "空でない文字列ではありません"
        )
    return value.strip()


# --- 解決 ----------------------------------------------------------------------


def run(project_root, *, backend_argument=None, settings=forge_settings):
    """解決結果を `(exit code, JSON payload)` で返す。

    `backend_argument` は `--backend` の値（未指定なら None）。
    `settings` はテストの差し替え境界。既定は本番実装（`forge_settings`）。
    """
    # 起動時の明示指定は設定より強い。設定が壊れていても指定どおり動かせるよう、
    # 設定を読む前に確定させる（利用者が今まさに与えた指定を、無関係な設定不正で
    # 妨げない）
    if backend_argument is not None:
        name = backend_argument.strip()
        if not name:
            return EXIT_OPERATION_ERROR, _error_payload(
                "--backend に空の値が指定されました"
            )
        return EXIT_SUCCESS, _success_payload(MODE_EXPLICIT, [name], SOURCE_ARGUMENT)

    try:
        section = _read_section(project_root, settings)
        _validate_keys(section)
        backend = _read_backend(section)
    except _SettingsInvalid as exc:
        return EXIT_OPERATION_ERROR, _error_payload(str(exc))

    if backend is not None:
        # 明示指定が候補順に勝つ（DES-066 §2.2）
        return EXIT_SUCCESS, _success_payload(MODE_EXPLICIT, [backend], SOURCE_SETTING)
    return EXIT_SUCCESS, _success_payload(
        MODE_ORDER, list(DEFAULT_ORDER), SOURCE_DEFAULT
    )


def _success_payload(mode: str, order: list, source: str) -> dict:
    return {
        "status": STATUS_SUCCESS,
        "operation": OPERATION,
        "reason_code": None,
        "mode": mode,
        "order": list(order),
        "source": source,
    }


def _error_payload(message: str) -> dict:
    return {
        "status": STATUS_OPERATION_ERROR,
        "operation": OPERATION,
        "reason_code": REASON_SETTINGS_INVALID,
        "mode": None,
        "order": None,
        "source": None,
        "message": message,
    }


# --- CLI ----------------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "レビューバックエンドの解決順（明示指定または候補順）を決め JSON で出力する。"
            "可用性検査は行わない"
        )
    )
    parser.add_argument(
        "--backend",
        default=None,
        help="起動時に明示指定された backend 名（未指定時は設定・既定の候補順に従う）",
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
    exit_code, payload = run(project_root, backend_argument=args.backend)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
