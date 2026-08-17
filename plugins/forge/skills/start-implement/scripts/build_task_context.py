#!/usr/bin/env python3
"""plan.json の該当タスクと候補 JSON をマージし、tasks/{task_id}.json を生成する。

`/forge:start-implement` Phase 4.3 のローカル操作入口。単一 SKILL が所有する決定論的な
実体ロジック（DES-024 §6.1「SKILL ローカル実体」）であり、他 SKILL へ再利用される共有
低レベル script ではない。
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "plan"))
from plan_contract import load_plan, PlanContractError  # noqa: E402


TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent / "templates" / "task_context_input.json"
)
with TEMPLATE_PATH.open(encoding="utf-8") as _template_file:
    CANDIDATE_TEMPLATE = json.load(_template_file)

TOP_LEVEL_FIELDS = set(CANDIDATE_TEMPLATE)
REQUIRED_READING_FIELDS = set(CANDIDATE_TEMPLATE["required_reading"])
VERIFICATION_FIELDS = set(CANDIDATE_TEMPLATE["verification"])
BUILD_STATES = {"required", "skipped"}
TESTS_STATES = {"required", "optional", "skipped"}

# 見出し行・コードフェンス開始行を fail-fast で拒否する（構造侵入対策）。
# group_review_batch.py の _STRUCTURE_LINE_RE と同じ考え方。
_STRUCTURE_LINE_RE = re.compile(r"^ {0,3}(?:#{1,6}(?:\s|$)|```|~~~)")


def _field_set_errors(label, value, expected):
    if not isinstance(value, dict):
        return [f"{label} は object である必要があります"]
    actual = set(value)
    errors = []
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        errors.append(f"{label} に必須フィールドがありません: {missing}")
    if unknown:
        errors.append(f"{label} に未知フィールドがあります: {unknown}")
    return errors


def _normalize_nonempty_string(label, value, errors):
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} は空でない文字列である必要があります")
        return ""
    return value.strip()


def _normalize_single_line(label, value, errors):
    text = _normalize_nonempty_string(label, value, errors)
    if not text:
        return ""
    if "\n" in text or "\r" in text:
        errors.append(f"{label} は単一行である必要があります")
        return ""
    if _STRUCTURE_LINE_RE.match(text):
        errors.append(f"{label} は見出し・コードフェンスで始められません")
        return ""
    return text


def _normalize_string_list(label, value, errors):
    if not isinstance(value, list):
        errors.append(f"{label} は配列である必要があります")
        return []
    normalized = []
    for index, item in enumerate(value):
        text = _normalize_nonempty_string(f"{label}[{index}]", item, errors)
        if text:
            normalized.append(text)
    return normalized


def _normalize_scope_out(value, errors):
    if not isinstance(value, list):
        errors.append("scope_out は配列である必要があります")
        return []
    normalized = []
    for index, entry in enumerate(value):
        label = f"scope_out[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} は object である必要があります")
            continue
        entry_errors = _field_set_errors(label, entry, {"item", "owner_task_id", "reason"})
        errors.extend(entry_errors)
        if entry_errors:
            continue
        normalized.append(
            {
                "item": _normalize_single_line(f"{label}.item", entry.get("item"), errors),
                "owner_task_id": _normalize_single_line(
                    f"{label}.owner_task_id", entry.get("owner_task_id"), errors
                ),
                "reason": _normalize_single_line(
                    f"{label}.reason", entry.get("reason"), errors
                ),
            }
        )
    return normalized


def _normalize_required_reading(value, errors):
    errors.extend(_field_set_errors("required_reading", value, REQUIRED_READING_FIELDS))
    if not isinstance(value, dict):
        return {
            "design_docs": [],
            "requirement_docs": [],
            "strategy_doc": None,
            "rule_docs": [],
            "reference_code": [],
            "additional": [],
        }
    strategy_doc = value.get("strategy_doc")
    if strategy_doc is not None:
        strategy_doc = _normalize_nonempty_string(
            "required_reading.strategy_doc", strategy_doc, errors
        )
    normalized = {"strategy_doc": strategy_doc or None}
    for name in ("design_docs", "requirement_docs", "rule_docs", "reference_code", "additional"):
        normalized[name] = _normalize_string_list(
            f"required_reading.{name}", value.get(name), errors
        )
    return normalized


def _normalize_verification(value, errors):
    errors.extend(_field_set_errors("verification", value, VERIFICATION_FIELDS))
    if not isinstance(value, dict):
        return {
            "build": "required",
            "build_reason": None,
            "tests": "required",
            "tests_reason": None,
        }
    normalized = {}
    for name, states in (("build", BUILD_STATES), ("tests", TESTS_STATES)):
        state = value.get(name)
        reason_name = f"{name}_reason"
        reason = value.get(reason_name)
        if not isinstance(state, str) or state not in states:
            errors.append(f"verification.{name} は {sorted(states)} のいずれかです")
            normalized[name] = "required"
        else:
            normalized[name] = state
        if normalized[name] == "required":
            if reason is not None:
                errors.append(f"verification.{reason_name} は required 時は null です")
            normalized[reason_name] = None
        else:
            normalized[reason_name] = _normalize_nonempty_string(
                f"verification.{reason_name}", reason, errors
            )
    return normalized


def validate_candidate(raw, expected_task_id):
    """候補 JSON を検証し、(normalized candidate | None, errors) を返す。"""
    errors = _field_set_errors("candidate", raw, TOP_LEVEL_FIELDS)
    if not isinstance(raw, dict):
        return None, errors

    task_id = _normalize_nonempty_string("task_id", raw.get("task_id"), errors)
    if task_id and task_id != expected_task_id:
        errors.append(
            f"task_id が起動対象と一致しません: expected={expected_task_id!r}, actual={task_id!r}"
        )

    normalized = {
        "task_id": expected_task_id,
        "scope_in": _normalize_single_line("scope_in", raw.get("scope_in"), errors),
        "scope_out": _normalize_scope_out(raw.get("scope_out"), errors),
        "required_reading": _normalize_required_reading(raw.get("required_reading"), errors),
        "implementation_instructions": _normalize_nonempty_string(
            "implementation_instructions", raw.get("implementation_instructions"), errors
        ),
        "verification": _normalize_verification(raw.get("verification"), errors),
    }
    return (None if errors else normalized), errors


def _read_and_consume_input(input_file):
    """候補 JSON を読み込み、成否に関わらず入力ファイルを削除する。"""
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


def _find_task(plan_path, task_id, errors):
    try:
        plan = load_plan(plan_path)
    except PlanContractError as exc:
        errors.append(str(exc))
        return None
    tasks = (plan or {}).get("tasks")
    if not isinstance(tasks, list):
        errors.append("plan.json に tasks 配列がありません")
        return None
    for task in tasks:
        if isinstance(task, dict) and task.get("task_id") == task_id:
            return dict(task)
    errors.append(f"plan.json に task_id={task_id!r} が見つかりません")
    return None


def build_task_context(plan_path, task_id, candidate_raw):
    """(merged context | None, errors) を返す。"""
    errors = []
    task = _find_task(plan_path, task_id, errors)
    normalized_candidate, candidate_errors = validate_candidate(candidate_raw, task_id)
    errors.extend(candidate_errors)
    if task is None or normalized_candidate is None:
        return None, errors
    merged = dict(task)
    merged.update(normalized_candidate)
    return merged, errors


def _emit(payload):
    json.dump(payload, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


def run_cli(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-path", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--output-path", required=True)
    args = parser.parse_args(argv)

    raw, errors = _read_and_consume_input(args.input_file)
    if errors:
        _emit({"status": "error", "errors": errors})
        return 20

    merged, errors = build_task_context(args.plan_path, args.task_id, raw)
    if errors:
        _emit({"status": "error", "errors": errors})
        return 20

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(merged, handle, ensure_ascii=False, indent=2, sort_keys=False)
        handle.write("\n")

    _emit({"status": "ok", "output_path": str(output_path)})
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
