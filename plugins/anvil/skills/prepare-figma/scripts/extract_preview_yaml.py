#!/usr/bin/env python3
"""デザイン仕様書 Markdown から preview YAML ブロックを抽出する.

仕様書中の ``` ```yaml``` フェンス内に、トップレベルキー ``preview:`` を持つ
YAML ブロックが 1 つ存在することを前提とする.

Usage:
    python3 extract_preview_yaml.py <spec.md> <output.yaml>

Security note:
    This is a developer-only CLI tool. ``sys.argv`` で渡されるファイルパスは
    開発者本人が指定するものであり、外部 untrusted input ではない。
    SAST が指摘する Path Traversal は、本ツールの信頼境界では成立しない。
    （実行者と入力提供者が同一人物。Web 経由で起動されることはない。）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


YAML_FENCE_RE = re.compile(
    r"```ya?ml\s*\n(?P<body>.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)


def extract_preview_block(md_text: str) -> str | None:
    """``preview:`` をトップレベルキーに持つ YAML ブロックを返す."""
    for match in YAML_FENCE_RE.finditer(md_text):
        body = match.group("body")
        # 行頭インデントなしで preview: が現れる最初のブロックを採用
        for line in body.splitlines():
            stripped = line.rstrip()
            if not stripped:
                continue
            if stripped.startswith("preview:"):
                return body
            break
    return None


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "Usage: extract_preview_yaml.py <spec.md> <output.yaml>",
            file=sys.stderr,
        )
        return 1

    in_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])

    md_text = in_path.read_text(encoding="utf-8")
    body = extract_preview_block(md_text)
    if body is None:
        print(
            f"No preview YAML block found in {in_path}. "
            "Expected a ```yaml fenced block whose top-level key is `preview:`.",
            file=sys.stderr,
        )
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
