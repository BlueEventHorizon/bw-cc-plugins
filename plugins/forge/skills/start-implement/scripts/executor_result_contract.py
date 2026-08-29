#!/usr/bin/env python3
"""executor return value のテンプレート読込・検証・正規化を担う内部モジュール。"""

import argparse
import json
import sys
from pathlib import Path, PurePosixPath


TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent / "templates" / "executor_result.json"
)
with TEMPLATE_PATH.open(encoding="utf-8") as _template_file:
    EXECUTOR_RESULT_TEMPLATE = json.load(_template_file)

TOP_LEVEL_FIELDS = set(EXECUTOR_RESULT_TEMPLATE)
VERIFICATION_FIELDS = set(EXECUTOR_RESULT_TEMPLATE["verification"])
PRE_MORTEM_FIELDS = set(EXECUTOR_RESULT_TEMPLATE["pre_mortem"])
VERIFICATION_STATES = {"success", "skipped", "failed"}


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


def _normalize_paths(value, errors):
    paths = _normalize_string_list("files_modified", value, errors)
    normalized = []
    seen = set()
    for path in paths:
        posix = PurePosixPath(path)
        if (
            posix.is_absolute()
            or ".." in posix.parts
            or path in {".", ".."}
        ):
            errors.append(
                f"files_modified はプロジェクトルート相対パスである必要があります: {path!r}"
            )
            continue
        if "\n" in path or "\r" in path:
            errors.append(f"files_modified に改行を含められません: {path!r}")
            continue
        if "\0" in path:
            errors.append(f"files_modified に NUL 文字を含められません: {path!r}")
            continue
        normalized_path = posix.as_posix()
        if normalized_path in seen:
            errors.append(f"files_modified に重複があります: {normalized_path!r}")
            continue
        seen.add(normalized_path)
        normalized.append(normalized_path)
    return normalized


def _normalize_verification(raw, errors):
    errors.extend(_field_set_errors("verification", raw, VERIFICATION_FIELDS))
    if not isinstance(raw, dict):
        return {
            "build": "failed",
            "build_reason": "verification schema invalid",
            "tests": "failed",
            "tests_reason": "verification schema invalid",
        }

    normalized = {}
    for name in ("build", "tests"):
        state = raw.get(name)
        reason_name = f"{name}_reason"
        reason = raw.get(reason_name)
        if not isinstance(state, str) or state not in VERIFICATION_STATES:
            errors.append(
                f"verification.{name} は success / skipped / failed のいずれかです"
            )
            normalized[name] = "failed"
        else:
            normalized[name] = state

        if state == "success":
            if reason is not None:
                errors.append(f"verification.{reason_name} は success 時は null です")
            normalized[reason_name] = None
        else:
            normalized[reason_name] = _normalize_nonempty_string(
                f"verification.{reason_name}", reason, errors
            )
    return normalized


def _normalize_pre_mortem(raw, errors):
    errors.extend(_field_set_errors("pre_mortem", raw, PRE_MORTEM_FIELDS))
    if not isinstance(raw, dict):
        return {"actualized_risks": [], "implementation_adjustments": []}
    normalized = {
        "actualized_risks": _normalize_string_list(
            "pre_mortem.actualized_risks",
            raw.get("actualized_risks"),
            errors,
        ),
        "implementation_adjustments": _normalize_string_list(
            "pre_mortem.implementation_adjustments",
            raw.get("implementation_adjustments"),
            errors,
        ),
    }
    for name, values in normalized.items():
        if len(values) > 5:
            errors.append(f"pre_mortem.{name} は最大 5 件です")
    return normalized


def validate_result(
    raw,
    expected_task_id,
    expected_build="required",
    expected_tests="optional",
):
    """入力を検証し、(normalized result | None, errors) を返す。"""
    errors = _field_set_errors("result", raw, TOP_LEVEL_FIELDS)
    if not isinstance(raw, dict):
        return None, errors

    task_id = _normalize_nonempty_string("task_id", raw.get("task_id"), errors)
    if task_id and task_id != expected_task_id:
        errors.append(
            f"task_id が起動対象と一致しません: expected={expected_task_id!r}, actual={task_id!r}"
        )

    status = raw.get("status")
    if not isinstance(status, str) or status not in {"SUCCESS", "FAILURE"}:
        errors.append("status は SUCCESS / FAILURE のいずれかです")
        status = "FAILURE"

    error = raw.get("error")
    if status == "SUCCESS":
        if error is not None:
            errors.append("error は SUCCESS 時は null です")
        normalized_error = None
    else:
        normalized_error = _normalize_nonempty_string("error", error, errors)

    summary = _normalize_nonempty_string("summary", raw.get("summary"), errors)
    if summary and len(summary.splitlines()) > 2:
        errors.append("summary は 1〜2 行である必要があります")

    verification = _normalize_verification(raw.get("verification"), errors)
    if status == "SUCCESS" and (
        verification["build"] == "failed" or verification["tests"] == "failed"
    ):
        errors.append("status が SUCCESS の場合、verification を failed にできません")
    if expected_build == "skipped" and verification["build"] != "skipped":
        errors.append("スキップ指定の build 検証は skipped である必要があります")
    if expected_tests == "skipped" and verification["tests"] != "skipped":
        errors.append("スキップ指定の tests 検証は skipped である必要があります")
    if status == "SUCCESS":
        if expected_build == "required" and verification["build"] != "success":
            errors.append("必須の build 検証は SUCCESS 時に success である必要があります")
        if expected_tests == "required" and verification["tests"] != "success":
            errors.append("必須の tests 検証は SUCCESS 時に success である必要があります")

    normalized = {
        "task_id": expected_task_id,
        "status": status,
        "files_modified": _normalize_paths(raw.get("files_modified"), errors),
        "summary": summary,
        "verification": verification,
        "pre_mortem": _normalize_pre_mortem(raw.get("pre_mortem"), errors),
        "notes": _normalize_string_list("notes", raw.get("notes"), errors),
        "error": normalized_error,
    }
    return (None if errors else normalized), errors


def failure_result(
    task_id,
    errors,
    expected_build="required",
    expected_tests="optional",
):
    reason = "executor return value validation failed"
    build_state = "skipped" if expected_build == "skipped" else "failed"
    tests_state = "skipped" if expected_tests == "skipped" else "failed"
    return {
        "task_id": task_id,
        "status": "FAILURE",
        "files_modified": [],
        "summary": reason,
        "verification": {
            "build": build_state,
            "build_reason": reason,
            "tests": tests_state,
            "tests_reason": reason,
        },
        "pre_mortem": {
            "actualized_risks": [],
            "implementation_adjustments": [],
        },
        "notes": errors,
        "error": "; ".join(errors),
    }


def _emit(payload):
    json.dump(payload, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


def _read_and_consume_input(input_file):
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


def run_cli(failure_on_error, argv=None):
    """固定方針を wrapper から受け取り、入力消費から出力までを一括実行する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--expected-task-id", required=True)
    parser.add_argument("--expected-build", required=True, choices=("required", "skipped"))
    parser.add_argument(
        "--expected-tests",
        required=True,
        choices=("required", "optional", "skipped"),
    )
    args = parser.parse_args(argv)

    raw, errors = _read_and_consume_input(args.input_file)
    if errors:
        if failure_on_error:
            _emit(
                failure_result(
                    args.expected_task_id,
                    errors,
                    expected_build=args.expected_build,
                    expected_tests=args.expected_tests,
                )
            )
            return 0
        _emit({"status": "error", "errors": errors})
        return 20

    normalized, errors = validate_result(
        raw,
        args.expected_task_id,
        expected_build=args.expected_build,
        expected_tests=args.expected_tests,
    )
    if errors:
        if failure_on_error:
            _emit(
                failure_result(
                    args.expected_task_id,
                    errors,
                    expected_build=args.expected_build,
                    expected_tests=args.expected_tests,
                )
            )
            return 0
        _emit({"status": "error", "errors": errors})
        return 20

    _emit(normalized)
    return 0
