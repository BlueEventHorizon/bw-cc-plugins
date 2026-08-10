#!/usr/bin/env python3
"""実装完了タスクを、レビュー単位（個別 / グループ合算）に振り分ける。

`group_id` は通し番号付き ("GROUP-001 (1/7)" 等) で記録されるため、単純な文字列一致では
同一グループの各タスクが別グループとして扱われてしまう。本スクリプトは通し番号を除去した
グループキーで正規化したうえで、以下を決定論的に判定する:

- グループの全メンバーが今回の実行結果 (`results`) に揃っており、かつ全て SUCCESS の場合
  → 1 回のグループ合算レビュー対象 (`kind: "group"`)
- グループの一部メンバーしか今回の結果に含まれない場合（過去の別起動で分割実行された等）
  → 揃っていない分は個別レビュー対象として扱う (`kind: "individual"`)。グループとして
    集約するのは「同一起動で全メンバーが success した」場合に限る
- グループの全メンバーが揃っているが 1 件以上 FAILURE の場合
  → グループ全体を保留 (`held_groups`)。中間状態の壊れたグループを合算レビューしたり、
    成功した一部メンバーだけを完了扱いにしたりしない
- `group_id: null`（独立タスク）→ 常に個別レビュー対象

Usage:
    echo '<input_json>' | python3 group_review_batch.py

レビュー依頼へ渡す「到達目標と意図的な未実装」(`/forge:review --scope`) の合算も本スクリプトが
行う。グループ合算レビューは N タスクを 1 回に束ねるため、各メンバーのスコープ境界を単純に
連結すると **同じグループの他メンバーが今回実装した項目まで「意図的な未実装」として宣言して
しまう**（TASK-A の範囲外項目が TASK-B の範囲内であることがグループ化の理由そのもの）。
合算規則は「全メンバーの範囲外項目の和集合 − 同じバッチのメンバーが担当する項目」である。

Usage:
    echo '<input_json>' | python3 group_review_batch.py

Input JSON:
    {
      "tasks": [
        {
          "task_id": "TASK-001",
          "group_id": "GROUP-001 (1/7)",
          "scope_in": "fm_to_pending.py の新規作成とテストまで",   # 任意・単一行
          "scope_out": [                                            # 任意
            {"item": "_meta.extracted_by の追加", "owner_task_id": "TASK-011",
             "reason": "4 ファイル同時変更が必要なため分離"}
          ]
        }, ...
      ],
      "results": [{"task_id": "TASK-001", "status": "SUCCESS", "files_modified": [...]}, ...]
    }

Output JSON:
    {
      "status": "ok",
      "review_batches": [
        {"kind": "individual", "task_ids": ["TASK-010"], "files": [...], "scope_text": "..."},
        {"kind": "group", "group_key": "GROUP-001", "task_ids": [...], "files": [...],
         "scope_text": "..."}
      ],
      "held_groups": [
        {"group_key": "GROUP-002", "task_ids": [...], "failed_task_ids": [...], "reason": "partial_failure"}
      ],
      "scope_missing_task_ids": ["TASK-012"]
    }

`scope_text` はレビュー依頼の `--scope` へそのまま渡せる本文（複数行）。バッチのどのメンバーも
スコープ情報を持たない場合のみ `null` になる。

`scope_missing_task_ids` は `scope_in` が未導出のまま**レビュー対象になった** task_id を、
**task 単位で**列挙する（`scope_text` が非 `null` かどうかとは独立に判定する）。グループの一部
メンバーにだけ `scope_in` がある場合、合算本文は非 `null` になるが残りのメンバーの範囲は不明で
あり、しかも範囲外 0 件の本文は「最終形に到達する」と断言してしまうため、バッチ単位の判定では
誤った断定をレビュアーへ渡すことになる。`scope_out` が空であることは欠落ではない（この範囲で
最終形に到達するという正当な状態）。
"""

import json
import re
import sys

_GROUP_KEY_RE = re.compile(r"^(.*?)\s*\(")

# `scope_text` が review 側の注入検証（`build_review_request.py` の構造行拒否）を通ることを
# 生成側でも保証する。受け取る側は生成元の保証を検証できないため、両側で独立に検査する。
_STRUCTURE_LINE_RE = re.compile(r"^ {0,3}(?:#{1,6}(?:\s|$)|```|~~~)")
_PROTOCOL_LINE_PREFIXES = ("REVIEW_RESULT:", "[msg-review]")

_OUT_OF_SCOPE_HEADING = "以下は今回の範囲外である。担当タスクで実装される。"
_NO_OUT_OF_SCOPE = "範囲外の項目はない（今回の対象はこの範囲で最終形に到達する）。"


def normalize_group_key(group_id):
    """通し番号付き group_id ("GROUP-001 (1/7)") からグループキー ("GROUP-001") を抽出する。

    括弧を含まない場合はそのまま返す（フォーマットの揺れに対する保守的なフォールバック）。
    """
    if group_id is None:
        return None
    match = _GROUP_KEY_RE.match(group_id)
    if match:
        key = match.group(1).strip()
        return key if key else group_id
    return group_id


class InvalidInputError(Exception):
    """入力の整合性検証に失敗した場合に送出する（呼び出し元は status: error として扱う）"""


def validate_results(tasks, results):
    """results の task_id が一意であり、かつ全て tasks（計画書）に存在することを検証する。

    重複 task_id を許すと同一タスクを複数回レビューする不具合につながり、未知 task_id を
    許すと計画書に存在しないタスクが誤ってレビュー対象に紛れ込む。いずれも fail-fast する。
    """
    known_task_ids = {t["task_id"] for t in tasks}
    seen = set()
    duplicates = set()
    unknown = set()
    for r in results:
        task_id = r["task_id"]
        if task_id in seen:
            duplicates.add(task_id)
        seen.add(task_id)
        if task_id not in known_task_ids:
            unknown.add(task_id)

    if duplicates:
        raise InvalidInputError(
            f"results に重複した task_id が含まれています: {sorted(duplicates)}"
        )
    if unknown:
        raise InvalidInputError(
            f"results に計画書に存在しない task_id が含まれています: {sorted(unknown)}"
        )


def _validate_scope_field(label, value):
    """スコープ用の文字列が単一行であり、構造行に見えないことを検証する。

    レビュー依頼本文へ埋め込まれる値であり、改行や見出し行を含むと本文の節構造・返信形式
    契約を偽装できてしまう（`build_review_request.py` が同種の検証を持つ）。生成側でも
    独立に検証することで、拒否される本文を組み立ててから気付く事態を避ける。
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidInputError(f"{label} は文字列である必要があります: {value!r}")
    stripped = value.strip()
    if not stripped:
        return None
    if "\n" in value or "\r" in value:
        raise InvalidInputError(f"{label} に改行を含む値は指定できません: {value!r}")
    if _STRUCTURE_LINE_RE.match(stripped):
        raise InvalidInputError(
            f"{label} が見出し行・コードフェンス行に見えます（節の偽装を防ぐため拒否）: {value!r}"
        )
    for prefix in _PROTOCOL_LINE_PREFIXES:
        if stripped.startswith(prefix):
            raise InvalidInputError(
                f"{label} が契約行（{prefix}）で始まっています（偽装を防ぐため拒否）: {value!r}"
            )
    return stripped


def _normalize_scope_out(task_id, raw):
    """1 タスクの `scope_out` を検証済みのレコード列へ正規化する。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise InvalidInputError(f"{task_id} の scope_out は配列である必要があります")
    records = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise InvalidInputError(
                f"{task_id} の scope_out[{index}] はオブジェクトである必要があります"
            )
        item = _validate_scope_field(f"{task_id} の scope_out[{index}].item", entry.get("item"))
        if item is None:
            raise InvalidInputError(f"{task_id} の scope_out[{index}].item は必須です")
        records.append({
            "item": item,
            "owner_task_id": _validate_scope_field(
                f"{task_id} の scope_out[{index}].owner_task_id", entry.get("owner_task_id")
            ),
            "reason": _validate_scope_field(
                f"{task_id} の scope_out[{index}].reason", entry.get("reason")
            ),
        })
    return records


def _render_scope_text(batch_task_ids, scope_in_by_task, scope_out_by_task):
    """バッチ 1 件分の `--scope` 本文を組み立てる。

    範囲外は「全メンバーの和集合 − 同じバッチのメンバーが担当する項目」。`owner_task_id` が
    同じバッチに含まれる項目は、今回この束の中で実装されているため範囲外ではない。
    """
    batch_members = set(batch_task_ids)

    in_lines = []
    for task_id in batch_task_ids:
        text = scope_in_by_task.get(task_id)
        if text:
            in_lines.append(f"- {task_id}: {text}" if len(batch_task_ids) > 1 else text)

    out_lines = []
    seen = set()
    for task_id in batch_task_ids:
        for record in scope_out_by_task.get(task_id, []):
            owner = record["owner_task_id"]
            if owner is not None and owner in batch_members:
                continue  # 同じバッチの別メンバーが今回実装した → 範囲外ではない
            dedup_key = (record["item"], owner)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            suffix = ""
            if owner:
                suffix += f" — {owner}"
            if record["reason"]:
                suffix += f"（{record['reason']}）"
            out_lines.append(f"- {record['item']}{suffix}")

    if not in_lines and not out_lines:
        return None

    sections = []
    if in_lines:
        sections.append("\n".join(in_lines))
    if out_lines:
        sections.append(_OUT_OF_SCOPE_HEADING + "\n\n" + "\n".join(out_lines))
    else:
        sections.append(_NO_OUT_OF_SCOPE)
    return "\n\n".join(sections)


def build_review_batches(payload):
    tasks = payload.get("tasks", [])
    results = payload.get("results", [])

    validate_results(tasks, results)

    # task_id -> group_id（計画書の全件から抽出済みの投影）
    task_group_id = {t["task_id"]: t.get("group_id") for t in tasks}

    # スコープ境界（Phase 4.2 で導出したもの）。検証は入力を受けた時点で fail-fast する。
    scope_in_by_task = {}
    scope_out_by_task = {}
    for t in tasks:
        task_id = t["task_id"]
        scope_in_by_task[task_id] = _validate_scope_field(
            f"{task_id} の scope_in", t.get("scope_in")
        )
        scope_out_by_task[task_id] = _normalize_scope_out(task_id, t.get("scope_out"))

    # グループキー -> そのグループに属する全 task_id（計画書順を維持）
    group_members = {}
    for t in tasks:
        key = normalize_group_key(t.get("group_id"))
        if key is None:
            continue
        group_members.setdefault(key, []).append(t["task_id"])

    # 今回の実行結果を task_id -> result にインデックス
    result_by_task = {r["task_id"]: r for r in results}

    # 今回の結果に現れたグループキーごとに、実行結果を集計
    groups_in_results = {}
    for r in results:
        task_id = r["task_id"]
        group_id = task_group_id.get(task_id)
        key = normalize_group_key(group_id)
        if key is None:
            continue
        groups_in_results.setdefault(key, []).append(r)

    handled_task_ids = set()
    review_batches = []
    held_groups = []

    # 計画書順を維持したまま、グループキーごとに完全性を判定する
    for key, member_task_ids in group_members.items():
        if key not in groups_in_results:
            continue  # 今回の実行に一切登場しないグループはスキップ

        present_results = groups_in_results[key]
        present_task_ids = {r["task_id"] for r in present_results}
        all_members_present = set(member_task_ids) <= present_task_ids

        if not all_members_present:
            # 部分実行（過去の別起動と分割されている等）→ 個別レビューへフォールバック
            continue

        failed_task_ids = [r["task_id"] for r in present_results if r["status"] != "SUCCESS"]
        if failed_task_ids:
            held_groups.append({
                "group_key": key,
                "task_ids": list(member_task_ids),
                "failed_task_ids": failed_task_ids,
                "reason": "partial_failure",
            })
            handled_task_ids.update(member_task_ids)
            continue

        # 全メンバーが今回の実行に揃い、かつ全て SUCCESS → グループ合算レビュー
        files = []
        seen = set()
        for task_id in member_task_ids:
            for f in result_by_task[task_id].get("files_modified", []):
                if f not in seen:
                    seen.add(f)
                    files.append(f)
        review_batches.append({
            "kind": "group",
            "group_key": key,
            "task_ids": list(member_task_ids),
            "files": files,
            "scope_text": _render_scope_text(
                member_task_ids, scope_in_by_task, scope_out_by_task
            ),
        })
        handled_task_ids.update(member_task_ids)

    # グループとして処理されなかった SUCCESS タスク（独立タスク・部分実行グループの残り）は個別レビュー
    for r in results:
        task_id = r["task_id"]
        if task_id in handled_task_ids:
            continue
        if r["status"] != "SUCCESS":
            continue
        review_batches.append({
            "kind": "individual",
            "task_ids": [task_id],
            "files": list(r.get("files_modified", [])),
            "scope_text": _render_scope_text(
                [task_id], scope_in_by_task, scope_out_by_task
            ),
        })

    # スコープ境界が未導出のままレビューへ回るタスクを可視化する。**判定はバッチ単位ではなく
    # task 単位で行う [MANDATORY]**。バッチ単位（`scope_text is None`）で判定すると、グループの
    # 一部メンバーにだけ `scope_in` がある場合に合算本文が非 None になり、残りのメンバーが
    # 欠落一覧から漏れる。そのうえ合算本文は範囲外 0 件を「最終形に到達する」と断言するため、
    # 沈黙ではなく誤った断定をレビュアーへ渡すことになる。
    #
    # `scope_in` の有無で判定する（4.2 が必須としているフィールド）。`scope_out` は 0 件が
    # 正当な状態（この範囲で最終形に到達する）であるため、空であることを欠落と見なさない。
    scope_missing_task_ids = [
        task_id
        for batch in review_batches
        for task_id in batch["task_ids"]
        if scope_in_by_task.get(task_id) is None
    ]

    return {
        "status": "ok",
        "review_batches": review_batches,
        "held_groups": held_groups,
        "scope_missing_task_ids": scope_missing_task_ids,
    }


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"status": "error", "message": f"invalid JSON input: {e}"}))
        sys.exit(1)

    if "tasks" not in payload or "results" not in payload:
        print(json.dumps({"status": "error", "message": "tasks / results は必須フィールドです"}))
        sys.exit(1)

    try:
        output = build_review_batches(payload)
    except InvalidInputError as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
        sys.exit(1)

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
