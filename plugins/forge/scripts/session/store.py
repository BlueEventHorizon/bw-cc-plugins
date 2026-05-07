"""セッション成果物の安全な書き込み API。"""

import os
from pathlib import Path

from session.yaml_utils import atomic_write_text, build_nested_yaml_text


class SessionStore:
    """単一 session_dir 配下の成果物を書き込む薄い facade。"""

    def __init__(self, session_dir):
        self.session_dir = Path(session_dir)

    def write_text(self, relative_path, content, atomic=True):
        """セッション配下へテキストを書き込む。"""
        target = self._resolve_relative_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if atomic:
            atomic_write_text(target, content)
        else:
            target.write_text(content, encoding="utf-8")

        return target

    def write_nested_yaml(self, relative_path, sections):
        """ネスト YAML をセッション配下へ書き込む。"""
        return self.write_text(
            relative_path,
            build_nested_yaml_text(sections),
            atomic=True,
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
