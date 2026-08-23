"""agenda.json の読み込み・保存、状態遷移の検証、表示層への再描画委譲を行う CLI ツール。

JSON 書き込み成功直後に `agenda_render.py` を呼び出し、表示を再生成する
（DES-075 §8.1）。再描画が失敗しても記録側の状態遷移は成立させ、
`{"status": "partial", ...}` として呼び出し側へ失敗を明示する
（記録の正しさを表示の失敗で道連れにしない。DES-075 §8.1）。

保存形式は ADR-076 の決定に従い、標準ライブラリ `json` のみを使用する
（PyYAML 等の外部依存を使わない）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# 同一ディレクトリの agenda_schema.py / agenda_render.py をインポートする
# （`plugins/forge/scripts/doc_structure/check_doc_structure.py` と同型の
# sys.path 経由の兄弟モジュール参照パターンに倣う）。
sys.path.insert(0, str(Path(__file__).resolve().parent))

import agenda_render  # noqa: E402
import agenda_schema  # noqa: E402

OWNER = "consult"


class AgendaStoreError(Exception):
    """agenda.json の読み込み・書き込みに失敗した場合に送出する（NFR-006）。"""


# ---------------------------------------------------------------------------
# JSON 読み書き（plan_contract.py の load_plan/save_plan と同型のパターンだが、
# 異なるドメインのモジュールであるため agenda_store.py 内に個別に実装する）
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


def build_init_record(
    *,
    identity: str,
    status_vocabulary: list,
    terminal_statuses: list,
    active_statuses: list,
    item_fields: list,
    severity_field: str | None,
) -> dict:
    """新規 agenda.json の初期状態を組み立てる（DES-075 §4）。"""
    return {
        "owner": OWNER,
        "created_at": datetime.now().isoformat(),
        "content_version": 1,
        "current_item_id": None,
        "config": {
            "identity": identity,
            "status_vocabulary": status_vocabulary,
            "terminal_statuses": terminal_statuses,
            "active_statuses": active_statuses,
            "item_fields": item_fields,
            "severity_field": severity_field,
        },
        "structural_judgment": {"recorded": False, "note": None, "recorded_at": None},
        "items": [],
    }


def _non_empty_string(value: Any) -> bool:
    """値が非空の文字列であるかどうかを判定する。

    真偽値判定（`not value`）は文字列以外の truthy な値（数値・list・dict 等）を
    「欠落していない有効な id/title」として素通りさせてしまう（`id`/`title` は
    仕様上文字列型を前提とするため、型を明示的に検証する）。
    """
    return isinstance(value, str) and value != ""


def _find_item_index(items: list, item_id: Any) -> int | None:
    for index, item in enumerate(items):
        if isinstance(item, dict) and item.get("id") == item_id:
            return index
    return None


def upsert_item(record: dict, item_patch: dict) -> dict:
    """差分パッチ `item_patch` を `record["items"]` へ適用する（DES-075 §6.1）。

    既存項目なら渡されたキーだけを既存値へマージし、存在しなければ新規追加する。
    戻り値は状態確認用の `{"ok": bool, ...}` 形式（record 全体のコピーではない）
    であり、`ok: False` の場合は呼び出し側（`handle_update`）が書き込みを行わない
    （拒否時は本関数の呼び出し前に record を退避しておくか、拒否後に
    save しない運用で整合を保つ。現在の `handle_update` は拒否時に
    `save_agenda` を呼ばないため、拒否された変更がファイルへ永続化されない）。
    `record["items"]` を in-place に書き換える。
    """
    if not isinstance(item_patch, dict) or not _non_empty_string(item_patch.get("id")):
        return {"ok": False, "missing_fields": ["id"]}
    items = record.get("items")
    if not isinstance(items, list):
        items = []
    record["items"] = items
    item_id = item_patch["id"]
    index = _find_item_index(items, item_id)
    is_new = index is None
    if is_new:
        missing_new_fields = []
        if not _non_empty_string(item_patch.get("title")):
            missing_new_fields.append("title")
        if not _non_empty_string(item_patch.get("status")):
            # status 未設定の項目は config.active_statuses にも config.terminal_statuses にも
            # 属さない「第三の状態」になり、next_item_id()/pending_item_ids() から永久に見えなくなる
            # うえ、§7 の削除条件（全項目の status が active_statuses に含まれなくなった時点）を
            # 満たしてしまい、未処理の項目が残ったまま記録が削除されうる。新規追加時に必須とする
            # ことで、この「第三の状態」が生まれる経路自体を塞ぐ（DES-075 §6.1）。
            missing_new_fields.append("status")
        if missing_new_fields:
            return {"ok": False, "missing_fields": missing_new_fields}
    existing = items[index] if not is_new else {}
    merged = dict(existing)
    merged.update(item_patch)
    if "status" in item_patch:
        target_status = item_patch["status"]
        config = dict(record.get("config")) if isinstance(record.get("config"), dict) else {}
        config["structural_judgment"] = record.get("structural_judgment")
        result = agenda_schema.validate(merged, target_status, config)
        if not result["ok"]:
            return {"ok": False, "missing_fields": result["missing_fields"]}

    # last_changed_fields は今回渡されたキーの集合を記録する（DES-075 §6.1・§4）。
    # id は項目を識別する固定キーであり、CLI の --item-id 由来で常に item_patch に
    # 含まれるが、値そのものが「変わった」わけではないため対象から除く
    # （DES-075 §4 のスキーマ例が id を含めていないことに合わせる）。
    merged["last_changed_fields"] = sorted(key for key in item_patch.keys() if key != "id")

    if is_new:
        items.append(merged)
    else:
        items[index] = merged
    return {"ok": True, "item": merged}


def _require_active_statuses(record: dict) -> list:
    """`config.active_statuses` を取り出す。list でない場合は既定値で補わず例外を送出する
    （NFR-006・agenda_schema.py の fail-closed 方針と対称にする。壊れた config を
    「対象項目なし」と誤判定させない）。
    """
    config = record.get("config")
    active_statuses = config.get("active_statuses") if isinstance(config, dict) else None
    if not isinstance(active_statuses, list):
        raise AgendaStoreError("config.active_statuses が不正です（list ではありません）")
    return active_statuses


def next_item_id(record: dict) -> Any | None:
    """`config.active_statuses` に含まれる最初の項目の id を返す（実装指示 (3) next）。"""
    active_statuses = _require_active_statuses(record)
    items = record.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("status") in active_statuses:
            return item.get("id")
    return None


def pending_item_ids(record: dict) -> list:
    """`config.active_statuses` に含まれる全項目の id を返す（実装指示 (4) pending）。

    `remaining_count` は `len()` で導出可能なため別コマンド化しない（DES-075 §5.1）。
    """
    active_statuses = _require_active_statuses(record)
    items = record.get("items")
    if not isinstance(items, list):
        return []
    return [
        item.get("id")
        for item in items
        if isinstance(item, dict) and item.get("status") in active_statuses
    ]


# ---------------------------------------------------------------------------
# 表示層への再描画委譲（DES-075 §8.1）
# ---------------------------------------------------------------------------


def _render(path: str | Path, record: dict, *, include_html: bool) -> list:
    """書き込み成功後に表示を再生成する。失敗しても例外を伝播させず、エラー文字列のリストを返す。

    `content_version` が増える操作（init/update/record-structural-judgment）は
    `include_html=True` で agenda.html と agenda_state.js の両方を再生成し、
    増えない操作（set-current）は `include_html=False` で agenda_state.js のみを
    再生成する（DES-075 §8.1・§3.2）。表示層は `agenda_store.py` に依存しない
    独立モジュールであり、内部で何が起きても記録側の状態遷移を巻き戻さない
    （DES-075 §8.1「記録の正しさを表示の失敗で道連れにしない」）。
    """
    out_dir = Path(path).parent
    errors: list = []

    try:
        state_js = agenda_render.render_agenda_state_js(record)
        (out_dir / "agenda_state.js").write_text(state_js, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - DES-075 §8.1: 再描画失敗は記録を巻き戻さない
        errors.append(f"agenda_state.js: {exc}")

    if include_html:
        try:
            html_str = agenda_render.render_agenda_html(record)
            (out_dir / "agenda.html").write_text(html_str, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - 同上
            errors.append(f"agenda.html: {exc}")

    return errors


def _finalize_write(path: str | Path, record: dict, *, include_html: bool) -> dict:
    """書き込み成功後の共通処理: 再描画を行い、結果 dict を組み立てる（DES-075 §8.1）。"""
    render_errors = _render(path, record, include_html=include_html)
    result = {"status": "ok", "content_version": record.get("content_version")}
    if render_errors:
        result["status"] = "partial"
        result["message"] = "記録は更新されたが再描画に失敗した: " + "; ".join(render_errors)
    return result


# ---------------------------------------------------------------------------
# サブコマンド本体（argparse から分離。テストは parse_args() を経由せず直接呼べる）
# ---------------------------------------------------------------------------


def handle_init(args: argparse.Namespace) -> dict:
    try:
        status_vocabulary = json.loads(args.status_vocabulary)
        terminal_statuses = json.loads(args.terminal_statuses)
        active_statuses = json.loads(args.active_statuses)
        item_fields = json.loads(args.item_fields)
    except json.JSONDecodeError as exc:
        return {"status": "error", "message": f"引数を JSON として解析できません: {exc}"}

    record = build_init_record(
        identity=args.identity,
        status_vocabulary=status_vocabulary,
        terminal_statuses=terminal_statuses,
        active_statuses=active_statuses,
        item_fields=item_fields,
        severity_field=args.severity_field,
    )

    try:
        save_agenda(args.path, record)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}

    return _finalize_write(args.path, record, include_html=True)


def _parse_set_flags(pairs: list) -> dict:
    """`--set key=value` の繰り返し指定を差分パッチ dict へ変換する。

    値は常に argparse 由来の文字列であり、AI が JSON 構文を直接組み立てる経路を持たない
    （`id` を数値で書き間違える等の型混入が構造的に起こらない）。`key` に `.` を含む場合、
    `top.sub` の 1 階層ネストとして `{top: {sub: value}}` を組み立てる（DES-075 §6.1 の
    「fields 等の入れ子はトップレベルキー単位で丸ごと置換」と同じ粒度）。
    """
    patch: dict = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"--set は key=value 形式である必要があります: {pair!r}")
        key, value = pair.split("=", 1)
        if not key:
            raise ValueError(f"--set のキーが空です: {pair!r}")
        if "." in key:
            top, _, sub = key.partition(".")
            if not top or not sub or "." in sub:
                raise ValueError(f"--set は 'top.sub' の1階層ネストのみ対応します: {pair!r}")
            existing = patch.setdefault(top, {})
            if not isinstance(existing, dict):
                raise ValueError(f"--set のキーが競合しています: {key!r}")
            existing[sub] = value
        else:
            if isinstance(patch.get(key), dict):
                raise ValueError(f"--set のキーが競合しています: {key!r}")
            patch[key] = value
    return patch


def handle_update(args: argparse.Namespace) -> dict:
    if not isinstance(args.item_id, str) or args.item_id == "":
        return {"status": "error", "message": "--item-id は空でない文字列である必要があります"}
    try:
        item_patch = _parse_set_flags(args.set)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    if "id" in item_patch:
        return {"status": "error", "message": "id は --item-id で指定してください（--set id=... は使用できません）"}
    item_patch["id"] = args.item_id

    try:
        record = load_agenda(args.path)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}

    upsert_result = upsert_item(record, item_patch)
    if not upsert_result["ok"]:
        return {
            "status": "error",
            "ok": False,
            "missing_fields": upsert_result["missing_fields"],
        }

    record["content_version"] = record.get("content_version", 0) + 1
    try:
        save_agenda(args.path, record)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}

    return _finalize_write(args.path, record, include_html=True)


def handle_next(args: argparse.Namespace) -> dict:
    try:
        record = load_agenda(args.path)
        result = next_item_id(record)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}
    return {"status": "ok", "next_item_id": result}


def handle_pending(args: argparse.Namespace) -> dict:
    try:
        record = load_agenda(args.path)
        pending = pending_item_ids(record)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}
    return {"status": "ok", "pending_item_ids": pending, "remaining_count": len(pending)}


def handle_record_structural_judgment(args: argparse.Namespace) -> dict:
    if not isinstance(args.note, str) or not args.note.strip():
        return {
            "status": "error",
            "message": "--note は空でない文字列である必要があります（FNC-012: 判断の根拠を記録すること）",
        }

    try:
        record = load_agenda(args.path)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}

    record["structural_judgment"] = {
        "recorded": True,
        "note": args.note,
        "recorded_at": datetime.now().isoformat(),
    }
    record["content_version"] = record.get("content_version", 0) + 1

    try:
        save_agenda(args.path, record)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}

    return _finalize_write(args.path, record, include_html=True)


def handle_set_current(args: argparse.Namespace) -> dict:
    try:
        record = load_agenda(args.path)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}

    record["current_item_id"] = args.item_id

    try:
        save_agenda(args.path, record)
    except AgendaStoreError as exc:
        return {"status": "error", "message": str(exc)}

    return _finalize_write(args.path, record, include_html=False)


# ---------------------------------------------------------------------------
# CLI エントリポイント
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agenda_store.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_init = subparsers.add_parser("init", help="agenda.json の新規作成")
    p_init.add_argument("--identity", required=True)
    p_init.add_argument("--status-vocabulary", required=True)
    p_init.add_argument("--terminal-statuses", required=True)
    p_init.add_argument("--active-statuses", required=True)
    p_init.add_argument("--item-fields", required=True)
    p_init.add_argument("--severity-field", default=None)
    p_init.add_argument("--path", required=True)

    p_update = subparsers.add_parser("update", help="1 項目の差分パッチ適用")
    p_update.add_argument("--path", required=True)
    p_update.add_argument("--item-id", required=True)
    p_update.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="変更するフィールドを key=value で指定する（複数指定可）。"
        "'verification.action=adopt' のように 1 階層のネストを dot で表せる",
    )

    p_next = subparsers.add_parser("next", help="次に扱う項目の id")
    p_next.add_argument("--path", required=True)

    p_pending = subparsers.add_parser("pending", help="未対応項目の id 一覧")
    p_pending.add_argument("--path", required=True)

    p_rsj = subparsers.add_parser("record-structural-judgment", help="構造判定の記録")
    p_rsj.add_argument("--path", required=True)
    p_rsj.add_argument("--note", required=True)

    p_set_current = subparsers.add_parser("set-current", help="対話中の項目を示す")
    p_set_current.add_argument("--path", required=True)
    p_set_current.add_argument("--item-id", required=True)

    return parser


_HANDLERS = {
    "init": handle_init,
    "update": handle_update,
    "next": handle_next,
    "pending": handle_pending,
    "record-structural-judgment": handle_record_structural_judgment,
    "set-current": handle_set_current,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = _HANDLERS[args.command](args)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") in ("ok", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
