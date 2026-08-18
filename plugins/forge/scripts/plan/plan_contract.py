#!/usr/bin/env python3
"""計画書（`{feature}_plan.json`）の読み書き・スキーマ検証を担う共有コアモジュール。

`start-plan`（生成）・`start-implement`（タスク選択・依存判定・ステータス更新）の
複数 SKILL から再利用される（REQ-003 FNC-006: 複数 SKILL が再利用する実体ロジックは
プラグイン共通の低レベル script に置く）。SKILL ローカルの操作入口はこのモジュールを
import し、当該 SKILL が必要とする操作だけを公開する。
"""

import json
import re
from pathlib import Path


TOP_LEVEL_KEYS = {
    "requirements_traceability",
    "design_traceability",
    "tasks",
    "revision_history",
}

TASK_REQUIRED_FIELDS = {
    "task_id",
    "title",
    "priority",
    "status",
    "design_id",
    "depends_on",
    "group_id",
    "build_check",
    "description",
    "acceptance_criteria",
    "required_reading",
}

TASK_STATUS_VALUES = {"pending", "in_progress", "completed"}
BUILD_CHECK_VALUES = {"per_task", "skip", "on_group_complete"}
REQUIREMENT_STATUS_VALUES = {"pending", "completed"}

_GROUP_KEY_RE = re.compile(r"^(.*?)\s*\(")


class PlanContractError(Exception):
    """計画書の読み込み・検証に失敗した場合に送出する。"""


def load_plan(plan_path):
    """計画書 JSON を読み込んで dict を返す。読み込めない場合は PlanContractError。"""
    path = Path(plan_path)
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanContractError(f"計画書を読み込めません: {exc}") from exc


def save_plan(plan_path, data):
    """計画書 JSON を書き込む。親ディレクトリが無ければ作成する。"""
    path = Path(plan_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=False)
        handle.write("\n")


def validate_plan_schema(data):
    """計画書の構造的妥当性を検証し、errors のリストを返す（空なら妥当）。"""
    errors = []
    if not isinstance(data, dict):
        return ["計画書は object である必要があります"]

    actual_keys = set(data)
    missing = sorted(TOP_LEVEL_KEYS - actual_keys)
    unknown = sorted(actual_keys - TOP_LEVEL_KEYS)
    if missing:
        errors.append(f"必須の top-level キーがありません: {missing}")
    if unknown:
        errors.append(f"未知の top-level キーがあります: {unknown}")

    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        errors.append("tasks は配列である必要があります")
    else:
        for index, task in enumerate(tasks):
            errors.extend(_validate_task(index, task))

    requirements = data.get("requirements_traceability")
    if requirements is not None and not isinstance(requirements, list):
        errors.append("requirements_traceability は配列である必要があります")
    elif isinstance(requirements, list):
        for index, entry in enumerate(requirements):
            if not isinstance(entry, dict):
                errors.append(f"requirements_traceability[{index}] は object である必要があります")
                continue
            status = entry.get("status")
            if status not in REQUIREMENT_STATUS_VALUES:
                errors.append(
                    f"requirements_traceability[{index}].status は "
                    f"{sorted(REQUIREMENT_STATUS_VALUES)} のいずれかです（実際: {status!r}）"
                )

    return errors


def _validate_task(index, task):
    label = f"tasks[{index}]"
    if not isinstance(task, dict):
        return [f"{label} は object である必要があります"]

    errors = []
    actual = set(task)
    missing = sorted(TASK_REQUIRED_FIELDS - actual)
    unknown = sorted(actual - TASK_REQUIRED_FIELDS)
    if missing:
        errors.append(f"{label} に必須フィールドがありません: {missing}")
    if unknown:
        errors.append(f"{label} に未知フィールドがあります: {unknown}")

    if task.get("status") not in TASK_STATUS_VALUES:
        errors.append(
            f"{label}.status は {sorted(TASK_STATUS_VALUES)} のいずれかです"
            f"（実際: {task.get('status')!r}）"
        )
    if task.get("build_check") not in BUILD_CHECK_VALUES:
        errors.append(
            f"{label}.build_check は {sorted(BUILD_CHECK_VALUES)} のいずれかです"
            f"（実際: {task.get('build_check')!r}）"
        )
    if not isinstance(task.get("depends_on"), list):
        errors.append(f"{label}.depends_on は配列である必要があります")
    if not isinstance(task.get("required_reading"), list):
        errors.append(f"{label}.required_reading は配列である必要があります")
    if task.get("design_id") is not None and not isinstance(task.get("design_id"), str):
        errors.append(f"{label}.design_id は文字列か null である必要があります")

    return errors


def read_and_consume_candidate_input(input_file):
    """候補 JSON を `.claude/.temp/` 配下から読み込み、成否に関わらず入力ファイルを削除する。

    `write_plan.py`（start-plan）と `build_task_context.py`（start-implement）の双方が
    「AI が組み立てた候補 JSON を一時ファイル経由で受け取り、消費後に削除する」という
    同一の入出力契約を必要とするため、本モジュールへ集約する。
    """
    path = Path(input_file)
    if path.is_absolute() or ".." in path.parts or path.parts[:2] != (".claude", ".temp"):
        return None, [
            "input-file は .claude/.temp/ 配下のプロジェクトルート相対パスである必要があります"
        ]
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle), []
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, [f"入力を JSON object として解析できません: {exc}"]
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def normalize_group_key(group_id):
    """通し番号付き group_id ("GROUP-001 (1/7)") からグループキー ("GROUP-001") を抽出する。

    括弧を含まない場合はそのまま返す（フォーマットの揺れに対する保守的なフォールバック）。
    `group_review_batch.py` と `select_tasks.py` の双方が同一のグループ正規化を要求する
    ため（`start-implement/SKILL.md` Phase 2.1 参照）、本モジュールへ集約する。
    """
    if group_id is None:
        return None
    match = _GROUP_KEY_RE.match(group_id)
    if match:
        key = match.group(1).strip()
        return key if key else group_id
    return group_id
