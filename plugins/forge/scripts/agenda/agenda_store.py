"""agenda.json の読み書き・状態遷移の検証・表示層への再描画委譲を行う CLI ツール。

start/record/next/pending/finish の5サブコマンドを持つ（DES-075 §6）。AI（consult）から
本ツールへの入力は常に `--input-file` による候補JSON方式であり、値をシェルコマンド書式
（`--set key=value` 等）に組み立てる経路は持たない（DES-075 §6・agenda:REQ-019 FNC-005）。

JSON 書き込み成功直後に `agenda_render.py` の `render_agenda_html()` を呼び出し、
`agenda.html` を再生成する（DES-075 §8.1）。再描画が失敗しても記録側の状態遷移は
成立させ、`{"status": "partial", ...}` として呼び出し側へ失敗を明示する
（記録の正しさを表示の失敗で道連れにしない。DES-075 §8.1）。

保存形式は ADR-076 の決定に従い、標準ライブラリ `json` のみを使用する
（PyYAML 等の外部依存を使わない）。
"""

from __future__ import annotations

import argparse
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


def _read_input_file(input_file: str) -> tuple[dict | None, str | None]:
    """`--input-file` の内容を候補JSON（object）として読み込む。

    AI が Write ツールで書いた一時ファイルのパスを受け取るだけであり（DES-075 §6.1）、
    値をシェルコマンド書式へ組み立てる経路は持たない。
    """
    try:
        with Path(input_file).open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, f"--input-file を JSON として読み込めません: {exc}"
    if not isinstance(data, dict):
        return None, "--input-file の内容は object である必要があります"
    return data, None


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _unknown_keys_error(label: str, raw: dict, allowed: set) -> str | None:
    """`raw` のトップレベルキーのうち `allowed` に含まれないものを検出する（超過拒否）。"""
    unknown = sorted(set(raw) - allowed)
    if unknown:
        return f"{label} に未知フィールドがあります: {unknown}"
    return None


# ---------------------------------------------------------------------------
# 表示層への再描画委譲（DES-075 §8.1）
# ---------------------------------------------------------------------------


def _render(path: str | Path, record: dict) -> list:
    """書き込み成功後に `agenda.html` を再生成する。失敗しても例外を伝播させず、
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
# start（DES-075 §6・§6.2）
# ---------------------------------------------------------------------------

_START_ALLOWED_KEYS = {"structural_judgment", "config", "items"}
_START_STRUCTURAL_JUDGMENT_ALLOWED_KEYS = {"note"}
_START_CONFIG_ALLOWED_KEYS = {"item_fields", "severity_field"}
_START_ITEM_ALLOWED_KEYS = {"id", "title", "fields"}


def _validate_start_candidate(raw: dict) -> tuple[dict | None, list]:
    """`start` の候補JSONを検証し、`(normalized | None, errors)` を返す。

    トップレベル許可キーは固定・超過拒否（DES-075 §6の実装指示）。
    `config.identity` は候補JSONから受け付けない（--path の親ディレクトリ名から導出する）。
    """
    errors: list = []
    unknown = _unknown_keys_error("candidate", raw, _START_ALLOWED_KEYS)
    if unknown:
        errors.append(unknown)

    structural_judgment = raw.get("structural_judgment")
    note = None
    if isinstance(structural_judgment, dict):
        sj_unknown = _unknown_keys_error(
            "structural_judgment", structural_judgment, _START_STRUCTURAL_JUDGMENT_ALLOWED_KEYS
        )
        if sj_unknown:
            errors.append(sj_unknown)
        note = structural_judgment.get("note")
    else:
        errors.append("structural_judgment は object である必要があります")
    if not _non_empty_string(note):
        errors.append("structural_judgment.note は空でない文字列である必要があります")

    config = raw.get("config")
    item_fields: list = []
    severity_field = None
    if isinstance(config, dict):
        config_unknown = _unknown_keys_error("config", config, _START_CONFIG_ALLOWED_KEYS)
        if config_unknown:
            errors.append(config_unknown)
        if "identity" in config:
            errors.append(
                "config.identity は候補JSONから受け付けません"
                "（--path の親ディレクトリ名から自動導出します）"
            )
        item_fields = config.get("item_fields")
        if not isinstance(item_fields, list) or not all(
            isinstance(value, str) and value for value in item_fields
        ):
            errors.append("config.item_fields は空でない文字列の配列である必要があります")
            item_fields = []
        severity_field = config.get("severity_field")
        if severity_field is not None and not isinstance(severity_field, str):
            errors.append("config.severity_field は文字列または null である必要があります")
    else:
        errors.append("config は object である必要があります")

    items_raw = raw.get("items")
    items: list = []
    if isinstance(items_raw, list):
        seen_ids: set = set()
        for index, item in enumerate(items_raw):
            label = f"items[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{label} は object である必要があります")
                continue
            item_unknown = _unknown_keys_error(label, item, _START_ITEM_ALLOWED_KEYS)
            if item_unknown:
                errors.append(item_unknown)
            item_id = item.get("id")
            title = item.get("title")
            if not _non_empty_string(item_id):
                errors.append(f"{label}.id は空でない文字列である必要があります")
            elif item_id in seen_ids:
                errors.append(f"{label}.id が重複しています: {item_id!r}")
            else:
                seen_ids.add(item_id)
            if not _non_empty_string(title):
                errors.append(f"{label}.title は空でない文字列である必要があります")
            fields = item.get("fields", {})
            if fields is not None and not isinstance(fields, dict):
                errors.append(f"{label}.fields は object である必要があります")
                fields = {}
            new_item = {
                "id": item_id,
                "title": title,
                "fields": fields if isinstance(fields, dict) else {},
                "background": "",
                "essence": "",
                "decision": None,
                "last_changed_fields": [],
            }
            items.append(new_item)
    else:
        errors.append("items は配列である必要があります")

    if errors:
        return None, errors

    return (
        {
            "note": note,
            "item_fields": item_fields,
            "severity_field": severity_field,
            "items": items,
        },
        [],
    )


def handle_start(args: argparse.Namespace) -> dict:
    raw, read_error = _read_input_file(args.input_file)
    if read_error:
        return {"status": "error", "message": read_error}

    normalized, errors = _validate_start_candidate(raw)
    if errors:
        return {"status": "error", "message": "; ".join(errors)}

    path = Path(args.path)
    # 既存ファイルの有無を問わず無条件に新規開始として上書きする。「削除して新しく
    # 始めるか・続きから進めるか」の判断は呼び出し側（consult SKILL.md Phase 2.1が
    # 実装済み）が start を呼ぶ前に済ませるべきものであり、agenda_store.py 側で
    # 二重にガードしない（agenda:REQ-019 FNC-010: 放置された記録が start を
    # 恒久的にブロックしない）。

    record = {
        "content_version": 1,
        "config": {
            "identity": path.parent.name,
            "item_fields": normalized["item_fields"],
            "severity_field": normalized["severity_field"],
        },
        "structural_judgment": {
            "recorded": True,
            "note": normalized["note"],
        },
        "items": normalized["items"],
    }

    try:
        save_agenda(path, record)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}

    return _finalize_write(path, record)


# ---------------------------------------------------------------------------
# record（差分パッチ。DES-075 §6.1・§5.1a）
# ---------------------------------------------------------------------------

_RECORD_ALLOWED_KEYS = {
    "title",
    "background",
    "essence",
    "decision",
    "fields",
    "structural_judgment",
}
_RECORD_STRUCTURAL_JUDGMENT_ALLOWED_KEYS = {"note"}
_RECORD_ITEM_PATCH_STRING_KEYS = ("title", "background", "essence")
_RECORD_ITEM_PATCH_DICT_KEYS = ("fields", "decision")


def _validate_record_candidate(raw: dict) -> tuple[dict | None, str | None, list]:
    """`record` の候補JSONを検証し、`(item_patch | None, structural_judgment_note, errors)`
    を返す（DES-075 §6.1: `structural_judgment` キーとそれ以外の項目パッチキーの2経路）。
    """
    errors: list = []
    unknown = _unknown_keys_error("candidate", raw, _RECORD_ALLOWED_KEYS)
    if unknown:
        errors.append(unknown)
    if "id" in raw:
        errors.append("id は --item-id で指定してください（候補JSONに含めることはできません）")

    structural_judgment_note = None
    if "structural_judgment" in raw:
        sj = raw.get("structural_judgment")
        if not isinstance(sj, dict):
            errors.append("structural_judgment は object である必要があります")
        else:
            sj_unknown = _unknown_keys_error(
                "structural_judgment", sj, _RECORD_STRUCTURAL_JUDGMENT_ALLOWED_KEYS
            )
            if sj_unknown:
                errors.append(sj_unknown)
            note = sj.get("note")
            if not _non_empty_string(note):
                errors.append("structural_judgment.note は空でない文字列である必要があります")
            else:
                structural_judgment_note = note

    item_patch: dict = {}
    for key in _RECORD_ITEM_PATCH_STRING_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, str):
            errors.append(f"{key} は文字列である必要があります")
            continue
        item_patch[key] = value
    for key in _RECORD_ITEM_PATCH_DICT_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, dict):
            errors.append(f"{key} は object である必要があります")
            continue
        item_patch[key] = value

    if errors:
        return None, None, errors
    return item_patch, structural_judgment_note, []


def _find_item_index(items: list, item_id: Any) -> int | None:
    for index, item in enumerate(items):
        if isinstance(item, dict) and item.get("id") == item_id:
            return index
    return None


def upsert_item(items: list, item_id: Any, item_patch: dict) -> tuple[dict, bool]:
    """既存項目があれば差分パッチをマージし、無ければ新規項目を組み立てる（DES-075 §3.2・§5.1）。

    戻り値は `(マージ後の項目全体, 新規追加かどうか)`。`items` への反映（追加/置換）・
    検証・保存は呼び出し側（`handle_record`）が構造判定を経てから行う（本関数は
    純粋関数であり `items` を変更しない）。
    """
    index = _find_item_index(items, item_id)
    is_new = index is None
    if is_new:
        existing: dict = {"id": item_id, "fields": {}, "background": "", "essence": "", "decision": None}
    else:
        existing = dict(items[index])
    merged_item = dict(existing)
    merged_item.update(item_patch)
    merged_item["id"] = item_id
    return merged_item, is_new


def handle_record(args: argparse.Namespace) -> dict:
    if not _non_empty_string(args.item_id):
        return {"status": "error", "message": "--item-id は空でない文字列である必要があります"}

    raw, read_error = _read_input_file(args.input_file)
    if read_error:
        return {"status": "error", "message": read_error}

    item_patch, structural_judgment_note, errors = _validate_record_candidate(raw)
    if errors:
        return {"status": "error", "message": "; ".join(errors)}

    try:
        record = load_agenda(args.path)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}

    items = record.get("items")
    if not isinstance(items, list):
        return {"status": "error", "message": "agenda.json の items が不正です（list ではありません）"}

    index = _find_item_index(items, args.item_id)
    is_new = index is None

    # §5.1a: 新規追加の場合、集合全体への再判定（structural_judgment.note）と
    # Item スキーマが要求する title を、この record 呼び出し全体で伴わなければ拒否する
    # （中間状態を永続化しない。項目・判定ともに保存しない）。
    missing_precondition: list = []
    if is_new:
        if structural_judgment_note is None:
            missing_precondition.append("structural_judgment.note")
        if not _non_empty_string(item_patch.get("title")):
            missing_precondition.append("title")
    if missing_precondition:
        return {"status": "error", "ok": False, "missing_fields": missing_precondition}

    merged_item, _ = upsert_item(items, args.item_id, item_patch)

    # レコード直下 structural_judgment を先に確定させる。新規追加でこの呼び出し内に
    # note が伴う場合、直後の decision トリガー判定（下記）は更新後の判定状態を参照する
    # 必要があるため（§5.1a「中間状態を永続化しない」）、save 前にこの時点で計算する。
    structural_judgment = record.get("structural_judgment")
    if not isinstance(structural_judgment, dict):
        structural_judgment = {"recorded": False, "note": None}
    if structural_judgment_note is not None:
        structural_judgment = {
            "recorded": True,
            "note": structural_judgment_note,
        }

    patch_keys = set(item_patch.keys())
    config_for_schema = (
        dict(record.get("config")) if isinstance(record.get("config"), dict) else {}
    )
    config_for_schema["structural_judgment"] = structural_judgment
    validation = agenda_schema.validate(merged_item, patch_keys, config_for_schema)
    if not validation["ok"]:
        return {"status": "error", "ok": False, "missing_fields": validation["missing_fields"]}

    item_changed = bool(item_patch) or is_new
    if item_changed:
        merged_item["last_changed_fields"] = sorted(patch_keys)
        if is_new:
            items.append(merged_item)
        else:
            items[index] = merged_item
        record["items"] = items

    if structural_judgment_note is not None:
        record["structural_judgment"] = structural_judgment
    record["content_version"] = record.get("content_version", 0) + 1

    try:
        save_agenda(args.path, record)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}

    return _finalize_write(args.path, record)


# ---------------------------------------------------------------------------
# next / pending（FNC-006。decision が dict 型で outcome が非空かという値ベースで判定。DES-075 §4「状態の表現」）
# ---------------------------------------------------------------------------


def _is_pending(item: dict) -> bool:
    decision = item.get("decision")
    if not isinstance(decision, dict):
        return True
    return not _non_empty_string(decision.get("outcome"))


def next_item_id(record: dict) -> Any | None:
    items = record.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and _is_pending(item):
            return item.get("id")
    return None


def pending_item_ids(record: dict) -> list:
    """`decision` キーを持たない、または `decision.outcome` が空の全項目の id を返す。

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

    items = record.get("items")
    if not isinstance(items, list):
        return {"status": "error", "message": "agenda.json の items が不正です（list ではありません）"}

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
    except OSError as exc:
        return {"status": "error", "message": f"agenda.json/agenda.html を削除できません: {exc}"}

    return {"status": "ok", "deleted": True}


# ---------------------------------------------------------------------------
# CLI エントリポイント
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agenda_store.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_start = subparsers.add_parser("start", help="agenda.json の新規作成")
    p_start.add_argument("--path", required=True)
    p_start.add_argument("--input-file", required=True)

    p_record = subparsers.add_parser("record", help="1項目への判断の記録（差分パッチ）")
    p_record.add_argument("--path", required=True)
    p_record.add_argument("--item-id", required=True)
    p_record.add_argument("--input-file", required=True)

    p_next = subparsers.add_parser("next", help="次に扱う項目の id")
    p_next.add_argument("--path", required=True)

    p_pending = subparsers.add_parser("pending", help="未対応項目の id 一覧")
    p_pending.add_argument("--path", required=True)

    p_finish = subparsers.add_parser("finish", help="全項目決着していれば記録を削除")
    p_finish.add_argument("--path", required=True)

    return parser


_HANDLERS = {
    "start": handle_start,
    "record": handle_record,
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
