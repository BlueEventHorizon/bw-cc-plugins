#!/usr/bin/env python3
"""forge monitor 用 session adapter。

session_dir 内の YAML / Markdown を読み、既存 /session レスポンス互換の
JSON 構造へ正規化する。monitor/server.py は HTTP / SSE に集中し、
ファイル読み取りと派生情報生成はこの module に閉じる。
"""

import os
import sys
from pathlib import Path

_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from session.yaml_utils import parse_yaml  # noqa: E402


SESSION_FILES = [
    "session.yaml",
    "plan.yaml",
    "review.md",
    "requirements.md",
    "design.md",
]

REFS_FILES = [
    "specs.yaml",
    "rules.yaml",
    "code.yaml",
]

REVIEW_STATUSES = ["pending", "in_progress", "fixed", "skipped", "needs_review"]


def _missing_entry():
    return {"exists": False, "content": None}


def _error_entry(error):
    return {"exists": True, "content": None, "error": str(error)}


def _read_text(path):
    return Path(path).read_text(encoding="utf-8")


def read_yaml_file(filepath):
    """YAML ファイルを dict として読む。存在しない場合は None。"""
    if not os.path.isfile(filepath):
        return None
    content = _read_text(filepath)
    if not content.strip():
        return {}
    return parse_yaml(content)


def read_markdown_file(filepath):
    """Markdown ファイルを文字列として読む。存在しない場合は None。"""
    if not os.path.isfile(filepath):
        return None
    return _read_text(filepath)


def read_session_file(session_dir, name):
    """session_dir 直下の既知ファイルを /session entry 形式で読む。"""
    filepath = os.path.join(session_dir, name)
    if not os.path.isfile(filepath):
        return _missing_entry()
    try:
        if name.endswith(".md"):
            return {"exists": True, "content": read_markdown_file(filepath)}
        return {"exists": True, "content": read_yaml_file(filepath)}
    except (OSError, UnicodeDecodeError, ValueError) as e:
        print(f"警告: session file 読み込み失敗: {filepath}: {e}", file=sys.stderr)
        return _error_entry(e)


def read_refs_file(session_dir, name):
    """refs/ 配下の YAML ファイルを /session entry 形式で読む。"""
    filepath = os.path.join(session_dir, "refs", name)
    if not os.path.isfile(filepath):
        return _missing_entry()
    try:
        return {"exists": True, "content": read_yaml_file(filepath)}
    except (OSError, UnicodeDecodeError, ValueError) as e:
        print(f"警告: refs file 読み込み失敗: {filepath}: {e}", file=sys.stderr)
        return _error_entry(e)


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
    result = {
        "session_dir": session_dir,
        "skill": skill or "",
        "files": {},
        "refs": {},
        "refs_yaml": _missing_entry(),
    }

    for filename in SESSION_FILES:
        result["files"][filename] = read_session_file(session_dir, filename)

    for filename in REFS_FILES:
        result["refs"][filename] = read_refs_file(session_dir, filename)

    result["refs_yaml"] = read_session_file(session_dir, "refs.yaml")

    session = _content_dict(result["files"].get("session.yaml"))
    if not result["skill"]:
        result["skill"] = session.get("skill", "")
    result["derived"] = build_derived(result, result["skill"])

    return result
