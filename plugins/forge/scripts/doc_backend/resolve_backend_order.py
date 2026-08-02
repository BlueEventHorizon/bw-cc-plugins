#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backend 順序リストを設定から解決する専用 CLI。

選択者（SKILL）は最初に本 CLI で順序リストを解決し、先位から各 backend が所有する
可用性判定を呼ぶ。可用性判定は各 backend が所有し、選択順序は選択者だけが持つ
データである（責務分離）。doc-db の低レベル CLI（`query_docdb.py` / `sync_docdb.py`）
は設定・優先指定・他方の backend を知らないため、設定を読むのは本 CLI だけである。

## 設定と既定値

`.claude/.forge.yaml`（入れ物の規約は `forge_settings.py` に一元化）の
`doc_backend` セクションを読む。許容する形は mapping `{prefer: doc-db | doc-advisor}`
のみである。**既定値（doc-advisor 先位）の定義点は本モジュールの `DEFAULT_ORDER`
1 箇所である。**

| 設定の状態                 | 出力                                                        |
| -------------------------- | ----------------------------------------------------------- |
| 未指定・ファイル不在       | 既定値の順序 `["doc-advisor", "doc-db"]`（`source=default`） |
| `prefer: doc-advisor`      | `["doc-advisor", "doc-db"]`（`source=setting`）              |
| `prefer: doc-db`           | `["doc-db", "doc-advisor"]`（`source=setting`）              |
| 不正（許容する形に反する） | exit 20 / `settings_invalid`。**推測で既定値に落ちない**     |

不正には、セクションが mapping でない・未知のキーを含む（綴り誤りを黙って無視すると
指定が効いていないことに気づけない）・`prefer` の値が 2 値以外・解析不能
（`SettingsError` = 構文エラー・読取失敗）の全てを含む。

## exit code / JSON 契約

| exit code | `status`          | 意味                                             |
| --------- | ----------------- | ------------------------------------------------ |
| 0         | `success`         | 順序リストを解決した（`order` / `source` を含む） |
| 20        | `operation_error` | 設定不正（`reason_code=settings_invalid`）       |

JSON は常に `status` / `operation` / `reason_code` / `order` / `source` を持つ。
本 CLI は backend 選択より前に実行され特定 backend に属さないため、doc-db 低レベル
CLI の共通 field のうち `backend`（特定 backend の識別）と `startup`（doc-db 起動
試行の結果）は持たない（設計判断）。不正時の `order` / `source` は null であり、
既定値の順序を入れない（読めない設定を黙って無視して既定値で動くと、利用者が意図
した backend と異なる側で静かに動き続けるためである）。

## 情報保護 [MANDATORY]

エラーメッセージに設定本文（`prefer` の実際の値を含む）を載せない。
設定不正の診断にはキー名のみを載せる（キー名は構造であり、綴り誤りの発見に必要）。

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

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR.parent))
import forge_settings  # noqa: E402

# --- 定数 ---------------------------------------------------------------------

#: 成功
EXIT_SUCCESS = 0

#: 設定不正。既定値へ落ちず明示エラーとする
EXIT_OPERATION_ERROR = 20

#: JSON contract の `status` 値
STATUS_SUCCESS = "success"
STATUS_OPERATION_ERROR = "operation_error"

#: JSON contract の `operation` 値
OPERATION = "resolve_backend_order"

#: reason code
REASON_SETTINGS_INVALID = "settings_invalid"

#: backend 名（順序リストの要素であり `prefer` の値域でもある）
BACKEND_DOC_DB = "doc-db"
BACKEND_DOC_ADVISOR = "doc-advisor"

#: 既定値の順序（doc-advisor 先位）。**既定値の定義点はこの 1 箇所のみ**
DEFAULT_ORDER = (BACKEND_DOC_ADVISOR, BACKEND_DOC_DB)

#: `order` の由来: 既定値 / 設定の明示指定
SOURCE_DEFAULT = "default"
SOURCE_SETTING = "setting"

#: 設定のセクション名とスキーマ（スキーマの所有は backend 選択設計）
SETTINGS_SECTION = "doc_backend"
SETTINGS_PREFER_KEY = "prefer"
ALLOWED_PREFER_VALUES = (BACKEND_DOC_DB, BACKEND_DOC_ADVISOR)


# --- 内部例外 -------------------------------------------------------------------


class _SettingsInvalid(Exception):
    """設定が許容する形に反していた（exit 20 / `settings_invalid`）。"""


# --- 順序の解決 -------------------------------------------------------------------


def _read_preference(project_root, settings) -> str | None:
    """`doc_backend.prefer` を読む。未指定は None。

    Raises:
        _SettingsInvalid: 解析不能・読取失敗・非 mapping・未知キー・値域外の
            いずれか。不正な設定を黙って無視して既定値で動くことはしない。
    """
    try:
        section = settings.section(project_root, SETTINGS_SECTION)
    except settings.SettingsError as exc:
        # 構文エラー・読取失敗・非 mapping セクションはいずれもここへ届く
        raise _SettingsInvalid(str(exc)) from exc

    unknown = sorted(key for key in section if key != SETTINGS_PREFER_KEY)
    if unknown:
        raise _SettingsInvalid(
            f".claude/.forge.yaml の {SETTINGS_SECTION} セクションに未知のキーがあります: "
            f"{', '.join(unknown)}（許容キーは {SETTINGS_PREFER_KEY} のみ）"
        )

    if SETTINGS_PREFER_KEY not in section:
        return None

    prefer = section[SETTINGS_PREFER_KEY]
    if prefer not in ALLOWED_PREFER_VALUES:
        # 設定本文（値そのもの）はエラー経路へ流さない
        raise _SettingsInvalid(
            f".claude/.forge.yaml の {SETTINGS_SECTION}.{SETTINGS_PREFER_KEY} が"
            f"許容値（{' / '.join(ALLOWED_PREFER_VALUES)}）ではありません"
        )
    return prefer


def resolve_order(prefer: str | None) -> tuple:
    """優先 backend 指定から順序リストを組み立てる。

    指定は「指定された backend を先頭とする順序」を意味する。未指定は既定値。
    """
    if prefer is None:
        return DEFAULT_ORDER
    return (prefer,) + tuple(b for b in DEFAULT_ORDER if b != prefer)


def run(project_root, *, settings=forge_settings):
    """順序リストを解決し `(exit code, JSON payload)` を返す。

    `settings` はテストの差し替え境界。既定は本番実装（`forge_settings`）。
    """
    try:
        prefer = _read_preference(project_root, settings)
    except _SettingsInvalid as exc:
        return EXIT_OPERATION_ERROR, {
            "status": STATUS_OPERATION_ERROR,
            "operation": OPERATION,
            "reason_code": REASON_SETTINGS_INVALID,
            "order": None,
            "source": None,
            "message": str(exc),
        }

    return EXIT_SUCCESS, {
        "status": STATUS_SUCCESS,
        "operation": OPERATION,
        "reason_code": None,
        "order": list(resolve_order(prefer)),
        "source": SOURCE_DEFAULT if prefer is None else SOURCE_SETTING,
    }


# --- CLI ----------------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "設定（.claude/.forge.yaml の doc_backend セクション）から"
            " backend の順序リストを解決し JSON で出力する"
        )
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="プロジェクトルートのパス（省略時: カレントディレクトリ）",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    project_root = Path(args.project_root) if args.project_root else Path.cwd()
    exit_code, payload = run(project_root)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
