"""セッション成果物の安全な書き込み API。

artifact 書き込み、monitor 通知、session meta 更新の順序を集約する。
"""

import os
from pathlib import Path

from monitor.notify import notify_session_update
from session.meta import update_session_meta_warning
from session.yaml_utils import atomic_write_text, build_nested_yaml_text


class SessionStore:
    """単一 session_dir 配下の成果物を書き込む薄い facade。"""

    def __init__(self, session_dir):
        self.session_dir = Path(session_dir)

    def write_text(self, relative_path, content, notify=True, meta=None, atomic=True):
        """セッション配下へテキストを書き込む。

        書き込み成功後に artifact 通知を行い、その後 meta が指定されていれば
        session.yaml を更新する。meta 更新失敗は artifact 書き込みを失敗させない。
        """
        target = self._resolve_relative_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if atomic:
            atomic_write_text(target, content)
        else:
            target.write_text(content, encoding="utf-8")

        if notify:
            notify_session_update(str(self.session_dir), str(target))

        if meta:
            self.update_meta(meta, notify=True)

        return target

    def write_nested_yaml(self, relative_path, sections, meta=None):
        """ネスト YAML をセッション配下へ書き込む。"""
        return self.write_text(
            relative_path,
            build_nested_yaml_text(sections),
            notify=True,
            meta=meta,
            atomic=True,
        )

    def update_meta(self, updates, notify=True):
        """session.yaml の meta を更新する。失敗時は warning/skipped を返す。"""
        return update_session_meta_warning(
            str(self.session_dir), updates, notify=notify
        )

    def _resolve_relative_path(self, relative_path):
        rel = Path(relative_path)
        if rel.is_absolute():
            raise ValueError(f"absolute path is not allowed: {relative_path}")
        if ".." in rel.parts:
            raise ValueError(f"path traversal is not allowed: {relative_path}")

        base = self.session_dir.resolve()
        target = self.session_dir / rel
        resolved = target.resolve(strict=False)
        if resolved != base and not str(resolved).startswith(str(base) + os.sep):
            raise ValueError(f"path escapes session_dir: {relative_path}")
        return target
