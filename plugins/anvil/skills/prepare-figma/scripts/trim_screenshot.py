#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow>=10.0"]
# ///
"""PNG スクリーンショットの下部にある余白を自動トリミングする.

Chromium の ``--screenshot`` は ``--window-size`` で指定した領域をそのまま出力するため、
コンテンツが短い場合は下部に大量の余白が残る。
このスクリプトは下から走査して連続する単色（背景色）領域を削除する.

Usage:
    trim_screenshot.py <input.png> <output.png> [--margin <N>]

Security note:
    This is a developer-only CLI tool. ``sys.argv`` で渡されるファイルパスは
    開発者本人が指定するものであり、外部 untrusted input ではない。
    SAST が指摘する Path Traversal は、本ツールの信頼境界では成立しない。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def trim_bottom_padding(img: Image.Image, margin: int = 24) -> Image.Image:
    """背景色（左下ピクセル相当）と一致する下部行を削除する.

    Args:
        img: 入力画像
        margin: トリム後に残す下部マージン（px）

    Returns:
        トリム後の画像
    """
    rgb = img.convert("RGB")
    width, height = rgb.size
    bg = rgb.getpixel((0, height - 1))

    # 下から上に走査し、bg と異なる pixel が見つかった行を「コンテンツ末端」とする
    content_bottom = height - 1
    for y in range(height - 1, -1, -1):
        row_uniform = True
        for x in range(0, width, max(1, width // 32)):  # 32 サンプル/行
            if rgb.getpixel((x, y)) != bg:
                row_uniform = False
                break
        if not row_uniform:
            content_bottom = y
            break

    new_height = min(height, content_bottom + 1 + margin)
    return img.crop((0, 0, width, new_height))


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "Usage: trim_screenshot.py <input.png> <output.png> [--margin <N>]",
            file=sys.stderr,
        )
        return 1

    in_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    margin = 24
    if "--margin" in sys.argv:
        idx = sys.argv.index("--margin")
        try:
            margin = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            print("--margin requires an integer value", file=sys.stderr)
            return 1

    img = Image.open(in_path)
    trimmed = trim_bottom_padding(img, margin=margin)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    trimmed.save(out_path, "PNG")
    return 0


if __name__ == "__main__":
    sys.exit(main())
