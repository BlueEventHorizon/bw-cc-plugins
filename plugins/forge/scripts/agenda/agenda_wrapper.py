#!/usr/bin/env python3
"""agenda への唯一の入力経路。記録の置き場と `config` を解決し、呼び出し側が渡す値から
入れ物（`config` / `items`）を組み立てて `agenda_store.py` の関数へメモリ上で渡す
（DES-075 §6）。

呼び出し側（review 起点の SKILL を実行する AI）が渡すのは、サブコマンドと、
標準入力に流し込む値だけである。記録の置き場（DES-075 §7）・`config` の値・
JSON の入れ物・ファイル名は、いずれも呼び出し側の事情ではなく agenda 側の事情であり、
本モジュールが組み立てる（DES-075 §6「AI はファイルを書かず、JSON を組み立てない」）。

- **起点は review だけ**（DES-075 §7）。直接起動（consult 起点）は停止した
- **置き場は絶対パスで解決する**（DES-075 §7）。`git rev-parse --show-toplevel` を基準に
  するため、呼び出し元の作業ディレクトリが変わっても記録は 1 箇所に定まる。
  git 管理下でない場所からの呼び出しは、既定の場所へ落とさずエラーで停止する
- **AI が書く文章はすべて標準入力から受け取る**（DES-075 §6・§6.1）。引数へ載せると
  引用符・記号でシェルの構文が壊れる。値を書き込むのは agenda 側だけであり、
  呼び出し側が候補 JSON や一時ファイルを書く経路は持たない

`start` は所見と評価を結合する script の標準出力（`combined` 配列）をそのまま
標準入力から読み、各要素の `text` を `problem` にも置いてから `items` にする
（DES-078 §2.2。「問題」欄は `problem` から出るが、review 起点の所見本文は `text` という
名前で来る。起点の事情は本モジュールに閉じる）。

`pending` はファイル不在を失敗として扱わない（`{"status": "ok", "exists": false}` を
返す）。呼び出し元にとって「まだ記録が無い」は正常系（新規に始める）であり、
`test -f` のような存在確認を呼び出し元に強いない。

Usage:
    python3 agenda_wrapper.py --origin review pending
    python3 agenda_wrapper.py --origin review start < <結合 script の出力>
    python3 agenda_wrapper.py --origin review record --structural < <構造判断の記述>
    python3 agenda_wrapper.py --origin review record --item-id 01 --field background < <本文>
    python3 agenda_wrapper.py --origin review record --new < <構造判断の記述>
    python3 agenda_wrapper.py --origin review next
    python3 agenda_wrapper.py --origin review finish
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agenda_store  # noqa: E402

_REVIEW_RELATIVE_PATH = ".claude/.temp/review/agenda.json"

# DES-075 §3.2: 重大度は項目の直下に来るため `items[].fields` へ入れる属性は無い。
# 表示層が重大度を引くキー名（`severity_field`）は保つ。
_REVIEW_CONFIG = {"item_fields": [], "severity_field": "severity"}


def project_root() -> tuple[str | None, str | None]:
    """`(プロジェクトルートの絶対パス, エラー)` を返す（DES-075 §7）。

    `__file__` から辿る方式は採らない。plugin は利用者環境のキャッシュへ配置される
    ため、辿り着くのは plugin のディレクトリであってプロジェクトではない。
    """
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None, (
            "プロジェクトルートを特定できません（git 管理下から呼び出してください）: "
            + completed.stderr.strip()
        )
    return completed.stdout.strip(), None


def resolve_agenda_path() -> tuple[str | None, str | None]:
    """`(記録の絶対パス, エラー)` を返す。置き場そのものは DES-075 §7 のまま。"""
    root, error = project_root()
    if error:
        return None, error
    return str(Path(root) / _REVIEW_RELATIVE_PATH), None


def _read_body(stdin) -> str:
    """標準入力から本文を読む。

    末尾の改行だけを落とす。値の内容ではなく、シェルが行末に付ける改行を
    記録へ持ち込まないための処理である（本文中の改行はそのまま保つ）。
    """
    return stdin.read().rstrip("\n")


def _handle_pending(path: str) -> dict:
    if not Path(path).is_file():
        return {"status": "ok", "exists": False, "pending_item_ids": [], "remaining_count": 0}
    result = agenda_store.handle_pending(argparse.Namespace(path=path))
    result["exists"] = True
    return result


def _handle_start(path: str, stdin) -> dict:
    """結合 script の出力（`combined` 配列）から入れ物を組み立てて `start` へ渡す。

    中間ファイルは書かない（DES-075 §6・DES-078 §2.2）。
    """
    try:
        payload = json.load(stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"status": "error", "message": f"標準入力を JSON として読み込めません: {exc}"}

    combined = payload.get("combined") if isinstance(payload, dict) else None
    if not isinstance(combined, list):
        return {
            "status": "error",
            "message": "標準入力に結合 script の出力（combined 配列）がありません",
        }

    items = []
    for entry in combined:
        item = dict(entry)
        if "text" in item:
            item["problem"] = item["text"]
        items.append(item)

    return agenda_store.start(path, config=dict(_REVIEW_CONFIG), items=items)


def _handle_record(path: str, args: argparse.Namespace, stdin) -> dict:
    """DES-075 §6.1 の 3 形。本文はいずれも標準入力から読む。"""
    if args.structural or args.new:
        # --field はこの 2 形では使わない。黙って捨てると、指定が効いたと誤認される。
        if args.field:
            return {
                "status": "error",
                "message": "--field は --item-id と組で使う（--structural / --new では指定できない）",
            }
    if args.structural:
        return agenda_store.record_structural_judgment(path, _read_body(stdin))
    if args.new:
        result = agenda_store.record_new_item(path, _read_body(stdin))
        if "item_id" in result:
            result["id"] = result.pop("item_id")
        return result
    if not args.field:
        return {"status": "error", "message": "--item-id には --field が必要です"}
    return agenda_store.record_item_value(path, args.item_id, args.field, _read_body(stdin))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agenda_wrapper.py")
    # DES-075 §7: 受け付ける起点は review だけ。停止した起点はここで拒否される。
    parser.add_argument("--origin", required=True, choices=["review"])
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("pending")
    subparsers.add_parser("next")
    subparsers.add_parser("finish")
    subparsers.add_parser("start")

    p_record = subparsers.add_parser("record")
    form = p_record.add_mutually_exclusive_group(required=True)
    form.add_argument("--structural", action="store_true", help="構造判断を記す")
    form.add_argument("--new", action="store_true", help="新規項目を足す")
    form.add_argument("--item-id", help="値を加える既存項目の id")
    p_record.add_argument("--field", help="加える値の名前（ドット区切りで入れ子を指す）")

    return parser


def run(args: argparse.Namespace, stdin=None) -> dict:
    path, error = resolve_agenda_path()
    if error:
        return {"status": "error", "message": error}

    if args.command == "pending":
        result = _handle_pending(path)
    elif args.command == "start":
        result = _handle_start(path, stdin)
    elif args.command == "record":
        result = _handle_record(path, args, stdin)
    elif args.command == "next":
        result = agenda_store.handle_next(argparse.Namespace(path=path))
    else:
        result = agenda_store.handle_finish(argparse.Namespace(path=path))

    # 呼び出し元は自分では置き場を組み立てないため、以降（表示物を開く等）で使えるよう
    # 解決済みの絶対パスを結果へ含める（DES-075 §7）。
    result.setdefault("path", path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run(args, sys.stdin)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") in ("ok", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
