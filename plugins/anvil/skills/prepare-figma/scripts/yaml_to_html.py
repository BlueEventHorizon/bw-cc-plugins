#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0"]
# ///
"""YAML 形式のレイアウト定義を HTML/CSS に変換するスクリプト.

入力: YAML ファイル（トップレベルが ``preview`` キーを持つ）
出力: HTML ファイル（chromium で screenshot するためのもの）

スキーマは ``../references/preview-yaml-schema.md`` を参照。

Usage:
    uv run yaml_to_html.py <input.yaml> <output.html>
    # または直接実行（shebang 経由）:
    ./yaml_to_html.py <input.yaml> <output.html>

Security notes:
    * **Path**: 本ツールは developer-only CLI。``sys.argv`` のファイルパスは
      開発者本人が指定するもので外部 untrusted input ではない。SAST が指摘する
      Path Traversal は信頼境界上成立しない。
    * **HTML 出力**: 生成 HTML は ``style`` 属性に YAML 由来の値を埋め込む。
      テキスト/ラベルは ``html.escape()`` で HTML エスケープしつつ、
      数値フィールドは ``_as_number()`` / ``_size_token()`` で int/float に
      限定して CSS injection の経路を塞いでいる。
      （生成 HTML はローカル Chromium での SS 撮影専用で Web 公開しない前提だが、
      防御的に型を絞っている。）
"""
from __future__ import annotations

import html
import sys
from pathlib import Path
from typing import Any

import yaml


SYSTEM_FONT = (
    "-apple-system, BlinkMacSystemFont, 'Hiragino Sans', "
    "'Hiragino Kaku Gothic ProN', 'Yu Gothic UI', Meiryo, sans-serif"
)
PLACEHOLDER_BG = "#e8e8e8"
PLACEHOLDER_BORDER = "#cccccc"


def _as_number(value: Any, *, field: str) -> float:
    """値が数値であることを保証する。不正値は ValueError。

    style 属性へ注入する数値は必ず int/float である必要があるため、
    bool や文字列を取り除いて CSS injection 経路を塞ぐ。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = f"{field} must be a number, got {type(value).__name__}: {value!r}"
        raise ValueError(msg)
    return value


def parse_padding(value: Any) -> str | None:
    """padding 値を CSS 文字列に変換する。

    数値（単一）または ``{top, right, bottom, left}`` の dict を受け付ける。
    数値以外が混入した場合は、CSS injection を防ぐため ``ValueError`` で停止する。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        msg = f"padding must be a number or dict, got bool: {value!r}"
        raise ValueError(msg)
    if isinstance(value, (int, float)):
        return f"{value}px"
    if isinstance(value, dict):
        t = _as_number(value.get("top", 0), field="padding.top")
        r = _as_number(value.get("right", 0), field="padding.right")
        b = _as_number(value.get("bottom", 0), field="padding.bottom")
        l = _as_number(value.get("left", 0), field="padding.left")
        return f"{t}px {r}px {b}px {l}px"
    return None


def _size_token(value: Any) -> str | None:
    """サイズ値を内部トークンに変換する。

    許可するのは ``"fill"`` / ``"hug"`` / 数値（int/float）のみ。
    任意文字列を受け入れると CSS injection の経路になるため明示的に拒否する。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        msg = f"size must be a number or 'fill'/'hug', got bool: {value!r}"
        raise ValueError(msg)
    if value in ("fill", "hug"):
        return value
    if isinstance(value, (int, float)):
        return f"{value}px"
    msg = f"size must be a number or 'fill'/'hug', got {type(value).__name__}: {value!r}"
    raise ValueError(msg)


def _size_css(
    raw_value: Any,
    axis: str,
    parent_layout: str | None,
) -> list[str]:
    """サイズ値を CSS スタイル群に展開する.

    Figma の hug/fill/fixed セマンティクスを Flexbox にマッピングする際、
    親レイアウト方向によって挙動が変わるため、軸と親の状況を見て決定する.
    """
    token = _size_token(raw_value)
    if token is None:
        return []
    css_dim = "width" if axis == "width" else "height"

    if token == "fill":
        main_axis_match = (parent_layout == "horizontal" and axis == "width") or (
            parent_layout == "vertical" and axis == "height"
        )
        if main_axis_match:
            return ["flex: 1", f"min-{css_dim}: 0"]
        return [f"{css_dim}: 100%"]

    if token == "hug":
        return []

    return [f"{css_dim}: {token}", "flex-shrink: 0"]


def build_container_styles(
    part: dict[str, Any],
    parent_layout: str | None,
) -> str:
    """コンテナのスタイル文字列を生成する."""
    styles: list[str] = []

    layout = part.get("layout")
    if layout == "vertical":
        styles.append("display: flex")
        styles.append("flex-direction: column")
    elif layout == "horizontal":
        styles.append("display: flex")
        styles.append("flex-direction: row")
    elif layout == "stack":
        # stack（オーバーレイ配置）はスキーマ未対応。renderer 側でも未実装のため、
        # 中途半端な position: relative を付けず、警告を出して通常フローへフォールバックする。
        print(
            f"[yaml_to_html] warning: 'layout: stack' is not supported yet "
            f"(part id={part.get('id', '<unknown>')}); falling back to default flow.",
            file=sys.stderr,
        )

    gap = part.get("gap")
    if gap is not None:
        styles.append(f"gap: {gap}px")

    padding = parse_padding(part.get("padding"))
    if padding is not None:
        styles.append(f"padding: {padding}")

    styles.extend(_size_css(part.get("width"), "width", parent_layout))
    styles.extend(_size_css(part.get("height"), "height", parent_layout))

    bg = part.get("background")
    if bg:
        styles.append(f"background-color: {bg}")

    shape = part.get("shape")
    if shape == "circle":
        styles.append("border-radius: 50%")
        styles.append("overflow: hidden")

    border = part.get("border")
    if isinstance(border, dict):
        bw = border.get("width", 1)
        bc = border.get("color", "#000")
        styles.append(f"border: {bw}px solid {bc}")
    elif isinstance(border, str):
        styles.append(f"border: {border}")

    border_bottom = part.get("border_bottom")
    if isinstance(border_bottom, dict):
        bw = border_bottom.get("width", 1)
        bc = border_bottom.get("color", "#000")
        styles.append(f"border-bottom: {bw}px solid {bc}")

    border_radius = part.get("border_radius")
    if border_radius is not None:
        styles.append(f"border-radius: {border_radius}px")

    align = part.get("align")
    if align:
        align_value = {"start": "flex-start", "center": "center", "end": "flex-end"}.get(
            align, align,
        )
        styles.append(f"align-items: {align_value}")

    justify = part.get("justify")
    if justify:
        justify_value = {
            "start": "flex-start",
            "center": "center",
            "end": "flex-end",
            "space_between": "space-between",
        }.get(justify, justify)
        styles.append(f"justify-content: {justify_value}")

    scroll = part.get("scroll")
    if scroll == "horizontal":
        styles.append("overflow-x: auto")
    elif scroll == "vertical":
        styles.append("overflow-y: auto")

    styles.append("box-sizing: border-box")
    return "; ".join(styles)


def build_text_styles(font: dict[str, Any] | None) -> str:
    """フォント定義を CSS 文字列に変換する."""
    if not font:
        return ""
    styles: list[str] = []
    if "size" in font:
        styles.append(f"font-size: {font['size']}px")
    if "weight" in font:
        styles.append(f"font-weight: {font['weight']}")
    if "color" in font:
        styles.append(f"color: {font['color']}")
    if "line_height" in font:
        styles.append(f"line-height: {font['line_height']}px")
    if "letter_spacing" in font:
        styles.append(f"letter-spacing: {font['letter_spacing']}px")
    return "; ".join(styles)


def render_part(
    part: dict[str, Any],
    parent_layout: str | None = None,
    depth: int = 0,
) -> str:
    """単一パーツを HTML に変換する（再帰）."""
    indent = "  " * depth
    part_id = html.escape(str(part.get("id", "")))
    part_type = part.get("type", "container")
    container_style = build_container_styles(part, parent_layout)

    if part_type == "text":
        text_style = build_text_styles(part.get("font"))
        combined = "; ".join(s for s in [container_style, text_style] if s)
        combined += f"; font-family: {SYSTEM_FONT}"
        content = html.escape(str(part.get("content", "")))
        return (
            f'{indent}<div data-id="{part_id}" '
            f'data-kind="text" style="{combined}">{content}</div>'
        )

    if part_type in ("icon", "image"):
        label = html.escape(str(part.get("label", part_type)))
        placeholder_styles = [
            "background-color: " + str(part.get("background") or PLACEHOLDER_BG),
            f"outline: 1px dashed {PLACEHOLDER_BORDER}",
            "outline-offset: -1px",
            "display: flex",
            "align-items: center",
            "justify-content: center",
            "font-size: 10px",
            "color: #666",
            f"font-family: {SYSTEM_FONT}",
        ]
        combined = "; ".join(
            s for s in [container_style, "; ".join(placeholder_styles)] if s
        )
        return (
            f'{indent}<div data-id="{part_id}" '
            f'data-kind="{part_type}" style="{combined}">{label}</div>'
        )

    if part_type == "placeholder":
        label = html.escape(str(part.get("label", part.get("id", ""))))
        placeholder_styles = [
            "display: flex",
            "align-items: center",
            "justify-content: center",
            "font-size: 12px",
            "color: #999",
            "outline: 1px dashed #ccc",
            "outline-offset: -1px",
            f"font-family: {SYSTEM_FONT}",
        ]
        if not part.get("background"):
            placeholder_styles.append(f"background-color: {PLACEHOLDER_BG}")
        combined = "; ".join(
            s for s in [container_style, "; ".join(placeholder_styles)] if s
        )
        return (
            f'{indent}<div data-id="{part_id}" '
            f'data-kind="placeholder" style="{combined}">{label}</div>'
        )

    children = part.get("children", []) or []
    self_layout = part.get("layout")
    rendered_children = "\n".join(
        render_part(c, parent_layout=self_layout, depth=depth + 1) for c in children
    )
    open_tag = (
        f'{indent}<div data-id="{part_id}" '
        f'data-kind="container" style="{container_style}">'
    )
    close_tag = f"{indent}</div>"

    if children:
        return f"{open_tag}\n{rendered_children}\n{close_tag}"
    return f"{open_tag}{close_tag}"


def build_document(preview: dict[str, Any]) -> str:
    """preview ブロックから完成 HTML を生成する."""
    meta = preview.get("meta", {}) or {}
    viewport = meta.get("viewport", {}) or {}
    viewport_width = viewport.get("width", 390)
    bg = meta.get("background", "#f7f7f7")
    title = meta.get("title", "Preview")

    root = preview.get("root")
    if root is None:
        msg = "preview.root is required"
        raise ValueError(msg)

    root_html = render_part(root, parent_layout=None, depth=2)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>{html.escape(str(title))}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: {SYSTEM_FONT};
    background: {bg};
  }}
  .viewport {{
    width: {viewport_width}px;
    margin: 0 auto;
    background: #ffffff;
  }}
</style>
</head>
<body>
  <div class="viewport">
{root_html}
  </div>
</body>
</html>
"""


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: yaml_to_html.py <input.yaml> <output.html>", file=sys.stderr)
        return 1

    in_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])

    try:
        data = yaml.safe_load(in_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"YAML parse error: {exc}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        print("YAML root must be a mapping", file=sys.stderr)
        return 1

    preview = data.get("preview", data)
    try:
        doc = build_document(preview)
    except ValueError as exc:
        print(f"Schema error: {exc}", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
