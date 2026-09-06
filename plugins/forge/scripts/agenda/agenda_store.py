"""agenda.json の読み書き・状態遷移の検証・表示層への再描画委譲を行うモジュール。

`start` / `record` は**関数呼び出し専用**であり CLI を持たない（DES-080 §6）。
入力を受理する経路は `agenda_wrapper.py` の 1 つに保ち、AI が JSON・ファイル名・
置き場を組み立てる経路を無くす（DES-080 §1.1・§2.1）。`pending` / `next` /
`finish` は AI が書く文章を受け取らないため CLI を残す。

agenda は受け取ったデータの形式を検査しない（DES-080 §2.3）。渡された項目は
そのまま保存し、agenda が読むキーのうち欠けているものだけを既定値で補う
（§2.5）。残るのは状態遷移の必要条件（§2.6 の受理条件・存在しない `item_id` の
拒否）だけであり、これは形式検査ではない。

`record` は 1 回の呼び出しで 1 つの値だけを受け取る（§2.6）。3 形をそれぞれ
別の関数として持つ:

- `record_structural_judgment()`: 構造判断をレコード直下へ記す
- `record_item_value()`: 既存項目へ値を 1 つ加える（値の名前と本文）
- `record_new_item()`: 構造判断を伴って新規項目を足し、採番した `id` を返す

JSON 書き込み成功直後に `agenda_render.py` を呼び出し、`agenda.html` と
`agenda_state.js`（自動追従用の世代番号）を再生成する（DES-075 §8.1・DES-077 §4.2）。
再描画が失敗しても記録側の状態遷移は
成立させ、`{"status": "partial", ...}` として呼び出し側へ失敗を明示する
（記録の正しさを表示の失敗で道連れにしない。DES-075 §8.1）。

保存形式は ADR-076 の決定に従い、標準ライブラリ `json` のみを使用する
（PyYAML 等の外部依存を使わない）。
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

# 同一ディレクトリの agenda_schema.py / agenda_render.py をインポートする
# （`plugins/forge/scripts/doc_structure/check_doc_structure.py` と同型の
# sys.path 経由の兄弟モジュール参照パターンに倣う）。
sys.path.insert(0, str(Path(__file__).resolve().parent))

import agenda_render  # noqa: E402
import agenda_schema  # noqa: E402


class AgendaStoreError(Exception):
    """agenda.json の読み込み・書き込みに失敗した場合に送出する（NFR-006）。"""


# 値の名前として受け付けないキー（DES-080 §2.6）。agenda が自ら書くキー（`id` /
# `last_changed_fields`）と、agenda が構造を持つオブジェクトとして読むキーそのもの
# （`fields` / `decision`）。受け付けると識別子が書き換わり §3 と両立しない。
_RESERVED_VALUE_NAMES = frozenset({"id", "last_changed_fields", "fields", "decision"})

# 上記のうち agenda が自ら書くキー。入れ子表記（`id.x` 等）でも書き換えを許さない。
# `fields` / `decision` は agenda が構造を持つものとして読むだけなので、その配下
# （`fields.severity` / `decision.by`）は値の名前として受け付ける（DES-080 §2.6）。
_AGENDA_OWNED_KEYS = frozenset({"id", "last_changed_fields"})

# DES-080 §2.5: agenda が読むキーのうち、欠けていれば補う既定値。
_ITEM_DEFAULTS = {
    "problem": "",
    "background": "",
    "essence": "",
    "recommendation": "",
    "fields": {},
    "decision": None,
    "last_changed_fields": [],
}


# ---------------------------------------------------------------------------
# JSON 読み書き
# ---------------------------------------------------------------------------


def load_agenda(path: str | Path) -> dict:
    """agenda.json を読み込む。失敗時は既定値で補わず AgendaStoreError を送出する（NFR-006）。"""
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise AgendaStoreError(f"agenda.json を読み込めません: {exc}") from exc


def save_agenda(path: str | Path, record: dict) -> None:
    """agenda.json を書き込む。失敗時は既定値で補わず AgendaStoreError を送出する（NFR-006）。"""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
    except OSError as exc:
        raise AgendaStoreError(f"agenda.json を書き込めません: {exc}") from exc


# ---------------------------------------------------------------------------
# 表示層への再描画委譲（DES-075 §8.1）
# ---------------------------------------------------------------------------


def _render(path: str | Path, record: dict) -> list:
    """書き込み成功後に `agenda.html` と `agenda_state.js`（自動追従用の世代番号
    ファイル。DES-077 §4.2）を再生成する。失敗しても例外を伝播させず、
    エラー文字列のリストを返す（表示層は agenda_store.py に依存しない独立モジュール
    であり、内部で何が起きても記録側の状態遷移を巻き戻さない。DES-075 §8.1）。
    """
    out_dir = Path(path).parent
    errors: list = []
    try:
        html_str = agenda_render.render_agenda_html(record)
        (out_dir / "agenda.html").write_text(html_str, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - DES-075 §8.1: 再描画失敗は記録を巻き戻さない
        errors.append(f"agenda.html: {exc}")
    try:
        state_js = agenda_render.render_agenda_state_js(record.get("content_version"))
        (out_dir / "agenda_state.js").write_text(state_js, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - 同上
        errors.append(f"agenda_state.js: {exc}")
    return errors


def _finalize_write(path: str | Path, record: dict) -> dict:
    """書き込み成功後の共通処理: 再描画を行い、結果 dict を組み立てる（DES-075 §8.1）。"""
    render_errors = _render(path, record)
    result = {"status": "ok", "content_version": record.get("content_version")}
    if render_errors:
        result["status"] = "partial"
        result["message"] = "記録は更新されたが再描画に失敗した: " + "; ".join(render_errors)
    return result


# ---------------------------------------------------------------------------
# 項目の正規化と採番（DES-080 §2.5・§3）
# ---------------------------------------------------------------------------


def _normalize_item(item: dict) -> dict:
    """渡された項目をそのまま保持し、欠けている既定値だけを補う（DES-080 §2.5）。

    既に値があるキーは上書きしない。`title` は必須にしない（表示層は `title` が
    空のとき `id` を用いる。§4.2）。agenda が知らないキーもそのまま残す（§2.3）。
    """
    normalized = dict(item)
    for key, default in _ITEM_DEFAULTS.items():
        if key not in normalized:
            normalized[key] = copy.deepcopy(default)
    return normalized


def _allocate_item_id(existing_ids: set) -> str:
    """既存の `id` と衝突しないゼロ埋め 2 桁の連番を返す（DES-080 §3）。

    既存項目の `id` がこの形でない場合も、衝突しない値を選ぶ。
    """
    number = 1
    while True:
        candidate = f"{number:02d}"
        if candidate not in existing_ids:
            return candidate
        number += 1


def _existing_item_ids(items: list) -> set:
    return {
        str(item.get("id"))
        for item in items
        if isinstance(item, dict) and item.get("id")
    }


def _find_item_index(items: list, item_id: Any) -> int | None:
    for index, item in enumerate(items):
        if isinstance(item, dict) and item.get("id") == item_id:
            return index
    return None


def _set_nested_value(item: dict, name: str, value: Any) -> None:
    """ドット区切りの名前を入れ子として解釈し、入れ子のキー単位でマージする（DES-080 §2.6）。

    `decision.by` は `decision` の中の `by` を指し、`decision` の他の値を消さない。
    """
    parts = name.split(".")
    target = item
    for part in parts[:-1]:
        child = target.get(part)
        if not isinstance(child, dict):
            child = {}
            target[part] = child
        target = child
    target[parts[-1]] = value


# ---------------------------------------------------------------------------
# start（DES-080 §2.1・§2.5・§3）
# ---------------------------------------------------------------------------


def start(path: str | Path, *, config: dict, items: list) -> dict:
    """記録を新規に作る（関数呼び出し専用。DES-080 §2.1・§6）。

    `config` と `items` は `agenda_wrapper.py` が組み立てて渡す。項目は §2.5 の
    正規化のみを行い、`id` の無い項目には §3 の採番を行う。構造判断は `start` では
    受け取らず、続く `record` の 1 回で受ける（§2.1）。そのため記録は
    `structural_judgment.recorded: False` で始まり、構造判断が記録されるまで
    項目へ値を加える呼び出しはすべて拒否される（§2.6）。

    既存ファイルの有無を問わず無条件に新規開始として上書きする。「削除して新しく
    始めるか・続きから進めるか」の判断は呼び出し側が `start` を呼ぶ前に済ませる
    ものであり、ここで二重にガードしない（agenda:REQ-019 FNC-010: 放置された記録が
    start を恒久的にブロックしない）。
    """
    path = Path(path)

    normalized_items: list = []
    for item in items:
        normalized_items.append(_normalize_item(item))
    assigned_ids = _existing_item_ids(normalized_items)
    for item in normalized_items:
        if not item.get("id"):
            new_id = _allocate_item_id(assigned_ids)
            item["id"] = new_id
            assigned_ids.add(new_id)

    record_config = dict(config)
    record_config["identity"] = path.parent.name

    record = {
        "content_version": 1,
        "config": record_config,
        "structural_judgment": {"recorded": False, "note": None},
        "items": normalized_items,
    }

    try:
        save_agenda(path, record)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}

    result = _finalize_write(path, record)
    result["path"] = str(path)
    return result


# ---------------------------------------------------------------------------
# record（3 形。DES-080 §2.6）
# ---------------------------------------------------------------------------


def _load_items(path: str | Path) -> tuple[dict | None, list | None, dict | None]:
    """記録と `items` を読み出す。読めない場合は `(None, None, エラー結果)` を返す。"""
    try:
        record = load_agenda(path)
    except AgendaStoreError as exc:
        return None, None, {"status": "error", "message": str(exc)}
    items = record.get("items")
    if not isinstance(items, list):
        return (
            None,
            None,
            {"status": "error", "message": "agenda.json の items が不正です（list ではありません）"},
        )
    return record, items, None


def record_structural_judgment(path: str | Path, note: str) -> dict:
    """構造判断をレコード直下へ記す（DES-080 §2.6 の 1 形目）。

    項目へは値を加えないため、`last_changed_fields` は変わらない（§2.6）。
    """
    if not agenda_schema.is_non_empty(note):
        return {
            "status": "error",
            "message": "構造判断の記述が空です（DES-075 §4: `recorded` は非空の記述を伴う呼び出しでのみ立つ）",
        }

    try:
        record = load_agenda(path)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}

    record["structural_judgment"] = {"recorded": True, "note": note}
    record["content_version"] = record.get("content_version", 0) + 1

    try:
        save_agenda(path, record)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}

    return _finalize_write(path, record)


def record_item_value(path: str | Path, item_id: Any, name: str, value: Any) -> dict:
    """既存項目へ値を 1 つ加える（DES-080 §2.6 の 2 形目）。

    `name` はドット区切りで入れ子を指してよく、入れ子のキー単位でマージする
    （`decision.by` を 1 つずつ積んでも先の値が消えない）。`id` /
    `last_changed_fields` / `fields` / `decision` そのものは名前として受け付けない。
    存在しない `item_id` は拒否する（新規項目が生まれるのは `record_new_item()`
    だけである。§2.6）。
    """
    if name in _RESERVED_VALUE_NAMES or name.split(".", 1)[0] in _AGENDA_OWNED_KEYS:
        return {
            "status": "error",
            "message": f"{name} は値の名前として指定できません（DES-080 §2.6）",
        }

    record, items, error = _load_items(path)
    if error:
        return error

    index = _find_item_index(items, item_id)
    if index is None:
        return {"status": "error", "message": f"item_id が見つかりません: {item_id!r}"}

    merged_item = copy.deepcopy(items[index])
    _set_nested_value(merged_item, name, value)

    config_for_schema = dict(record.get("config")) if isinstance(record.get("config"), dict) else {}
    config_for_schema["structural_judgment"] = record.get("structural_judgment")
    validation = agenda_schema.validate(merged_item, {name}, config_for_schema)
    if not validation["ok"]:
        return {"status": "error", "ok": False, "missing_fields": validation["missing_fields"]}

    # 渡された名前そのまま（例: `decision.by`）を記録する（§2.6「その呼び出しで
    # 加えたキー」）。
    merged_item["last_changed_fields"] = [name]
    items[index] = merged_item
    record["items"] = items
    record["content_version"] = record.get("content_version", 0) + 1

    try:
        save_agenda(path, record)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}

    return _finalize_write(path, record)


def record_new_item(path: str | Path, note: str) -> dict:
    """構造判断を伴って新規項目を足し、採番した `id` を応答に含める（DES-080 §2.6 の 3 形目）。

    新規項目の追加に構造判断（追加後の再判断）を伴わせるのは DES-075 §5.1a の
    要求であり、この呼び出しが受け取る 1 値がそれに当たる。項目はここで生成・
    採番され、以後この項目へ値を加える呼び出しは返された `id` を使う。
    """
    if not agenda_schema.is_non_empty(note):
        return {
            "status": "error",
            "message": "構造判断の記述が空です（DES-075 §5.1a: 伴わなければ項目・判定ともに保存しない）",
        }

    record, items, error = _load_items(path)
    if error:
        return error

    new_item = _normalize_item({})
    new_item["id"] = _allocate_item_id(_existing_item_ids(items))
    items.append(new_item)
    record["items"] = items
    record["structural_judgment"] = {"recorded": True, "note": note}
    record["content_version"] = record.get("content_version", 0) + 1

    try:
        save_agenda(path, record)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}

    result = _finalize_write(path, record)
    result["item_id"] = new_item["id"]
    return result


# ---------------------------------------------------------------------------
# next / pending（決着は `decision` の 3 値そろい。DES-080 §2.6・§4.4）
# ---------------------------------------------------------------------------


def _is_pending(item: dict) -> bool:
    return not agenda_schema.is_settled(item)


def next_item_id(record: dict) -> Any | None:
    items = record.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and _is_pending(item):
            return item.get("id")
    return None


def pending_item_ids(record: dict) -> list:
    """決着していない（`decision` の 3 値が揃っていない）全項目の id を返す。

    `remaining_count` は呼び出し元が `len()` で導出する（DES-075 §5.1）。
    """
    items = record.get("items")
    if not isinstance(items, list):
        return []
    return [
        item.get("id")
        for item in items
        if isinstance(item, dict) and _is_pending(item)
    ]


def handle_next(args: argparse.Namespace) -> dict:
    try:
        record = load_agenda(args.path)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}
    return {"status": "ok", "item_id": next_item_id(record)}


def handle_pending(args: argparse.Namespace) -> dict:
    try:
        record = load_agenda(args.path)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}
    pending = pending_item_ids(record)
    return {"status": "ok", "pending_item_ids": pending, "remaining_count": len(pending)}


# ---------------------------------------------------------------------------
# finish（DES-075 §7）
# ---------------------------------------------------------------------------


def handle_finish(args: argparse.Namespace) -> dict:
    try:
        record = load_agenda(args.path)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}

    pending_ids = pending_item_ids(record)
    if pending_ids:
        return {
            "status": "ok",
            "deleted": False,
            "remaining_count": len(pending_ids),
            "pending_item_ids": pending_ids,
        }

    path = Path(args.path)
    try:
        path.unlink(missing_ok=True)
        (path.parent / "agenda.html").unlink(missing_ok=True)
        (path.parent / "agenda_state.js").unlink(missing_ok=True)
    except OSError as exc:
        return {
            "status": "error",
            "message": f"agenda.json/agenda.html/agenda_state.js を削除できません: {exc}",
        }

    return {"status": "ok", "deleted": True}


# ---------------------------------------------------------------------------
# CLI エントリポイント（`start` / `record` は持たない。DES-080 §6）
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agenda_store.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_next = subparsers.add_parser("next", help="次に扱う項目の id")
    p_next.add_argument("--path", required=True)

    p_pending = subparsers.add_parser("pending", help="未対応項目の id 一覧")
    p_pending.add_argument("--path", required=True)

    p_finish = subparsers.add_parser("finish", help="全項目決着していれば記録を削除")
    p_finish.add_argument("--path", required=True)

    return parser


_HANDLERS = {
    "next": handle_next,
    "pending": handle_pending,
    "finish": handle_finish,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = _HANDLERS[args.command](args)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") in ("ok", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
