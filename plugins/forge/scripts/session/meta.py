"""session.yaml の浅い進行状態を管理する。

writer script から共通利用される session meta 更新 API を提供する。
"""

import sys
from pathlib import Path

from monitor.notify import notify_session_update
from session.yaml_utils import atomic_write_text, now_iso, read_yaml, yaml_scalar

# session.yaml の共通フィールド（この順序で出力）
COMMON_FIELDS = ["skill", "started_at", "last_updated", "status", "resume_policy"]

# session.yaml の粗い進行状態フィールド（この順序で共通フィールドの後に出力）
SESSION_META_FIELDS = [
    "phase",
    "phase_status",
    "focus",
    "waiting_type",
    "waiting_reason",
    "active_artifact",
]

SESSION_FIELD_ORDER = COMMON_FIELDS + SESSION_META_FIELDS

VALID_PHASE_STATUSES = {"pending", "in_progress", "completed", "failed"}
VALID_WAITING_TYPES = {"none", "user_input", "agent", "command"}


def _one_line(value):
    """CLI 入力の改行を空白に潰し、session.yaml を flat に保つ。"""
    return " ".join(str(value).splitlines())


def _build_flat_yaml_text(data, field_order=None):
    """write_flat_yaml と同じ順序規則で YAML テキストを構築する。"""
    lines = []
    if field_order:
        ordered = [k for k in field_order if k in data]
        remaining = sorted(k for k in data if k not in field_order)
        ordered += remaining
    else:
        ordered = sorted(data.keys())
    for key in ordered:
        lines.append(f"{key}: {yaml_scalar(data[key])}")
    return "\n".join(lines) + "\n"


def _atomic_write_flat_yaml(path, data, field_order=None):
    """同一ディレクトリ内の一時ファイル経由で flat YAML を原子的に書く。"""
    text = _build_flat_yaml_text(data, field_order=field_order)
    atomic_write_text(path, text)


def _validate_meta_updates(updates):
    phase_status = updates.get("phase_status")
    if phase_status is not None and phase_status not in VALID_PHASE_STATUSES:
        raise ValueError(
            f"不正な phase_status です: {phase_status}"
            f"（許容値: {sorted(VALID_PHASE_STATUSES)}）"
        )

    waiting_type = updates.get("waiting_type")
    if waiting_type is not None and waiting_type not in VALID_WAITING_TYPES:
        raise ValueError(
            f"不正な waiting_type です: {waiting_type}"
            f"（許容値: {sorted(VALID_WAITING_TYPES)}）"
        )


def update_session_meta(session_dir, updates, *, notify=True):
    """session.yaml の浅い進行状態を更新する。

    Args:
        session_dir: セッションディレクトリ
        updates: phase / focus 等の更新 dict
        notify: True の場合 monitor に通知する

    Returns:
        dict: status / session_dir / session_path / updated

    Raises:
        FileNotFoundError: session_dir または session.yaml が存在しない
        ValueError: enum 値が不正
    """
    session_path = Path(session_dir)
    if not session_path.is_dir():
        raise FileNotFoundError(f"ディレクトリが存在しません: {session_dir}")

    yaml_path = session_path / "session.yaml"
    if not yaml_path.is_file():
        raise FileNotFoundError(f"session.yaml が見つかりません: {yaml_path}")

    clean_updates = {}
    for key in SESSION_META_FIELDS:
        if key not in updates or updates[key] is None:
            continue
        value = updates[key]
        if key in {"focus", "waiting_reason"}:
            value = _one_line(value)
        clean_updates[key] = value

    _validate_meta_updates(clean_updates)

    data = read_yaml(str(yaml_path))
    updated = []
    for key, value in clean_updates.items():
        if data.get(key) != value:
            data[key] = value
            updated.append(key)

    if data.get("waiting_type") == "none" and data.get("waiting_reason") != "":
        data["waiting_reason"] = ""
        if "waiting_reason" not in updated:
            updated.append("waiting_reason")

    if data.get("phase") == "completed" and data.get("phase_status") == "completed":
        if data.get("status") != "completed":
            data["status"] = "completed"
            updated.append("status")

    data["last_updated"] = now_iso()
    if "last_updated" not in updated:
        updated.append("last_updated")

    _atomic_write_flat_yaml(str(yaml_path), data, field_order=SESSION_FIELD_ORDER)

    if notify:
        notify_session_update(str(session_path), str(yaml_path))

    return {
        "status": "ok",
        "session_dir": str(session_dir),
        "session_path": str(yaml_path),
        "updated": updated,
    }


def update_session_meta_warning(session_dir, updates, *, notify=True):
    """session meta 更新を試み、失敗しても警告だけにする。

    writer script が成果物保存に成功した後、monitor 表示用の粗い状態更新だけで
    主処理を失敗させないための helper。
    """
    try:
        return update_session_meta(session_dir, updates, notify=notify)
    except FileNotFoundError as e:
        if "session.yaml" in str(e):
            return {"status": "skipped", "error": str(e)}
        print(f"[forge session] warning: update-meta failed: {e}", file=sys.stderr)
        return {"status": "warning", "error": str(e)}
    except Exception as e:  # noqa: BLE001 - writer 本体を壊さない
        print(f"[forge session] warning: update-meta failed: {e}", file=sys.stderr)
        return {"status": "warning", "error": str(e)}
