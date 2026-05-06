#!/usr/bin/env python3
"""forge monitor 用 session adapter。

session_dir 内の YAML / Markdown を読み、既存 /session レスポンス互換の
JSON 構造へ正規化する。monitor/server.py は HTTP / SSE に集中し、
ファイル読み取りと派生情報生成はこの module に閉じる。
"""

import os
import sys

_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from session.reader import (  # noqa: E402
    MONITOR_SESSION_FILES as SESSION_FILES,
    REFS_FILES,
    read_entry,
    read_session_files,
)


REVIEW_STATUSES = ["pending", "in_progress", "fixed", "skipped", "needs_review"]


def read_session_file(session_dir, name):
    """session_dir 直下の既知ファイルを /session entry 形式で読む。"""
    return read_entry(os.path.join(session_dir, name))


def read_refs_file(session_dir, name):
    """refs/ 配下の YAML ファイルを /session entry 形式で読む。"""
    return read_entry(os.path.join(session_dir, "refs", name))


def _content_dict(entry):
    if not entry or not entry.get("exists"):
        return {}
    content = entry.get("content")
    return content if isinstance(content, dict) else {}


def _build_review_counts(plan):
    counts = {"total": 0}
    for status in REVIEW_STATUSES:
        counts[status] = 0

    items = plan.get("items")
    if not isinstance(items, list):
        return counts

    counts["total"] = len(items)
    for item in items:
        if not isinstance(item, dict):
            continue
        status = item.get("status")
        if status in counts:
            counts[status] += 1
    return counts


def build_derived(data, skill):
    """monitor 表示用の派生情報を構築する。正規状態ではない。"""
    session = _content_dict(data.get("files", {}).get("session.yaml"))
    plan = _content_dict(data.get("files", {}).get("plan.yaml"))
    waiting_type = session.get("waiting_type") or "none"
    waiting_reason = session.get("waiting_reason") or ""
    if waiting_type == "none":
        waiting_reason = ""

    phase_status = (
        session.get("phase_status")
        or session.get("status")
        or "in_progress"
    )

    return {
        "phase": session.get("phase") or "created",
        "phase_status": phase_status,
        "focus": session.get("focus") or "",
        "waiting": {
            "type": waiting_type,
            "reason": waiting_reason,
        },
        "active_artifact": session.get("active_artifact") or "",
        "review_counts": _build_review_counts(plan),
    }


def build_monitor_session(session_dir, skill=""):
    """session_dir を読み、既存 /session レスポンス互換の dict を返す。"""
    result = read_session_files(
        session_dir,
        session_files=SESSION_FILES,
        refs_files=REFS_FILES,
    )
    result["skill"] = skill or ""
    # refs.yaml は session/refs どちらのリストにも含めず、既存 /session レスポンスの
    # refs_yaml キーとして個別に読み込む（互換性のため）
    result["refs_yaml"] = read_session_file(session_dir, "refs.yaml")

    session = _content_dict(result["files"].get("session.yaml"))
    if not result["skill"]:
        result["skill"] = session.get("skill", "")
    result["derived"] = build_derived(result, result["skill"])

    return result
