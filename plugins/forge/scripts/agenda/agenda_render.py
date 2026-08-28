#!/usr/bin/env python3
"""agenda 機構の表示層。``agenda.json`` 相当の dict から表示物の文字列を生成する。

設計は agenda:DES-077（表示層設計書）が持つ。本モジュールが公開する唯一の関数
``render_agenda_html()`` は、``agenda.json`` の内容を受け取って ``agenda.html``
文字列を返すだけの純粋関数である。自動追従の仕組み（ポーリング・部分更新・
スクロール位置保持）は持たない（DES-077 §4）。呼び出し側（``agenda_store.py``）
は書き込み成功のたびに本関数を呼び、``agenda.html`` を毎回まるごと再生成する。
本モジュールは ``agenda_store.py`` に依存せず、単体で直接呼び出すこともできる
（DES-075 §3.1）。

HTML エスケープパターンは ``plugins/anvil/skills/prepare-figma/scripts/json_to_html.py``
の ``html.escape()`` 使用パターンを踏襲する。
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any


def _escape(value: Any) -> str:
    """任意値を文字列化した上で HTML エスケープする。

    DES-077 §3「出力値は html.escape() を通す」を一箇所に集約するためのヘルパー。
    None は空文字列として扱う（AI が生成した dict のフィールド欠落を落とさず
    そのまま提示する。既定値で補って意味を作らない）。
    """
    if value is None:
        return ""
    return html.escape(str(value))


def _severity_value(item: dict, severity_field: str | None) -> str:
    """`config.severity_field` が指すキーの生の値を `item["fields"]` から取り出す。

    DES-077 §3.1a・agenda:REQ-019 FNC-009（中立性）: ``severity`` というキー名を
    本モジュールが決め打ちしてはならない。``severity_field`` が未指定、または
    対応する値が存在しない場合は空文字列を返す。エスケープ・フォールバック
    表示（`-` 等）は呼び出し側の責務とする（表示先ごとに異なるため。
    `_severity_badge_html` はバッジ非表示、`_summary_row_html` は `-` 表示）。
    """
    if not severity_field:
        return ""
    fields = item.get("fields")
    if not isinstance(fields, dict):
        return ""
    value = fields.get(severity_field)
    return str(value) if value else ""


def _severity_badge_html(item: dict, severity_field: str | None) -> str:
    """severity バッジの HTML を返す。

    値が存在しない場合はバッジ要素自体を出力しない（空文字列を返す）。
    """
    value = _severity_value(item, severity_field)
    if not value:
        return ""
    escaped = _escape(value)
    return f'<span class="severity-badge" data-severity="{escaped}">{escaped}</span>'


def _derive_status_label(item: dict) -> str:
    """項目の状態表示文言を、独立フィールドではなく記入有無から導出する。

    DES-077 §3.3 のstateDiagram-v2・判定条件表のとおり、``decision``・
    ``background``・``essence`` の記入有無だけを見る（独立した状態フィールドは
    持たない）:

    - ``decision`` が存在する → 「決着または棄却」。``decision.outcome`` の
      内容をそのまま表示する（呼び出し側の自由記述。agenda 機構は意味を
      解釈しない）
    - ``decision`` が無く、``background``・``essence`` のいずれかが非空 →
      「進行中」
    - 両方空 → 「未着手」
    """
    decision = item.get("decision")
    if isinstance(decision, dict):
        outcome = decision.get("outcome")
        return outcome if outcome else "(未定)"
    if item.get("background") or item.get("essence"):
        return "進行中"
    return "未着手"


def _decision_text(item: dict) -> str:
    """項目節の「決着」行に表示するテキストを返す。

    ``decision``（DES-075 §4 の ``items[].decision``）が記入されていれば
    「結論（理由）」の形にまとめる。未記入（``None``）の場合は決着していない
    ことが分かる文言を返す（軽微な表示詳細。DES-077 §3 のテンプレートは
    「決着: ...」という記入欄であることのみを示し、未記入時の具体的な文言は
    定めていないため、ここで推測して補う）。
    """
    decision = item.get("decision")
    if not isinstance(decision, dict):
        return "(未定)"
    outcome = decision.get("outcome")
    reason = decision.get("reason")
    if not outcome and not reason:
        return "(未定)"
    parts = [p for p in (outcome, reason) if p]
    return "（".join(parts) + "）" if len(parts) > 1 else (parts[0] if parts else "(未定)")


def _result_summary(item: dict) -> str:
    """アジェンダ表の「結果・課題」列に表示する短い要約を、raw のまま返す。

    ``decision`` が記入済みなら outcome を、未記入なら「未着手」を意味する
    プレースホルダを返す（軽微な表示詳細。§3 のテンプレートは列の存在のみを
    定め、内容の導出方法は定めていないため、DES-075 §4 の既存フィールドから
    妥当な範囲で推測する）。**エスケープしない**——他の導出ヘルパー
    （`_derive_status_label`/`_decision_text`）と契約を揃え、エスケープは
    呼び出し側（`_summary_row_html`）が一律に行う。
    """
    decision = item.get("decision")
    if isinstance(decision, dict) and decision.get("outcome"):
        reason = decision.get("reason")
        if reason:
            return f"{decision['outcome']}: {reason}"
        return decision["outcome"]
    return "-"


def _is_changed(item: dict) -> bool:
    """`last_changed_fields` が空でない項目かどうかを返す（DES-077 §3.1）。"""
    last_changed_fields = item.get("last_changed_fields")
    return isinstance(last_changed_fields, list) and len(last_changed_fields) > 0


def _summary_row_html(item: dict, severity_field: str | None) -> str:
    """`#agenda-summary` テーブルの 1 行分の HTML を返す（DES-077 §3 FNC-001）。"""
    item_id = _escape(item.get("id"))
    title = _escape(item.get("title"))
    status = _escape(_derive_status_label(item))
    severity_value = _escape(_severity_value(item, severity_field))
    severity_cell = severity_value or "-"
    result_cell = _escape(_result_summary(item))
    return (
        "<tr>"
        f"<td>{item_id}</td>"
        f"<td>{title}</td>"
        f"<td>{severity_cell}</td>"
        f"<td>{status}</td>"
        f"<td>{result_cell}</td>"
        "</tr>"
    )


def _item_section_html(item: dict, severity_field: str | None) -> str:
    """項目ごとの `<section>` の HTML を返す（DES-077 §3・§3.1・§3.1a）。"""
    item_id_raw = item.get("id")
    item_id = _escape(item_id_raw)
    title = _escape(item.get("title"))
    background = _escape(item.get("background"))
    essence = _escape(item.get("essence"))
    decision_text = _escape(_decision_text(item))
    changed = _is_changed(item)
    severity_badge = _severity_badge_html(item, severity_field)

    return (
        f'<section id="item-{item_id}" '
        f'data-changed="{"true" if changed else "false"}">\n'
        f'  <div class="gutter"><span class="state-dot changed"></span></div>\n'
        f"  <h2>[{item_id}] {title} {severity_badge}</h2>\n"
        f"  <p>背景: {background}</p>\n"
        f"  <p>本質: {essence}</p>\n"
        f"  <p>決着: {decision_text}</p>\n"
        "</section>"
    )


_STYLE = """
  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 24px;
    font-family: -apple-system, BlinkMacSystemFont, 'Hiragino Sans',
      'Hiragino Kaku Gothic ProN', 'Yu Gothic UI', Meiryo, sans-serif;
    line-height: 1.6;
    background: #fafafa;
    color: #222;
  }
  h1 { font-size: 1.6em; }
  h2 { font-size: 1.2em; }
  .generated-notice {
    font-size: 0.8em;
    color: #888;
  }
  #agenda-summary {
    border-collapse: collapse;
    width: 100%;
    margin-bottom: 24px;
  }
  #agenda-summary th, #agenda-summary td {
    border: 1px solid #ddd;
    padding: 6px 10px;
    text-align: left;
  }
  section {
    border-bottom: 1px solid #e0e0e0;
    padding: 12px 0;
    position: relative;
  }
  .gutter {
    position: absolute;
    left: -18px;
    top: 14px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .state-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: transparent;
  }
  section[data-changed="true"] .state-dot.changed { background: #f0c36d; }
  .severity-badge {
    display: inline-block;
    font-size: 0.7em;
    padding: 2px 6px;
    border-radius: 4px;
    background: #eee;
    color: #555;
  }
  .severity-badge[data-severity="critical"] { background: #fbdada; color: #8a2c2c; }
  .severity-badge[data-severity="major"] { background: #fdeec2; color: #8a6d1f; }
  .severity-badge[data-severity="minor"] { background: #dcf0da; color: #2f6b3a; }
"""


def render_agenda_html(agenda: dict, *, generated_at: str | None = None) -> str:
    """``agenda.json`` の内容から ``agenda.html`` 文字列を生成する（DES-077 §3・§4）。

    自動追従の仕組み（ポーリング・部分更新・スクロール位置保持）は持たない。
    書き込みのたびに呼び出し側（``agenda_store.py``）が本関数を呼び、
    ``agenda.html`` を毎回まるごと再生成する前提の単純な生成専用関数である。
    """
    config = agenda.get("config")
    if not isinstance(config, dict):
        raise ValueError(
            f"agenda['config'] は dict である必要があります（実際の型: {type(config).__name__}）。"
            "record が破損している可能性があります（agenda:REQ-019 NFR-006: 既定値で補って進行しない）"
        )
    severity_field = config.get("severity_field")
    identity = _escape(config.get("identity"))
    items = agenda.get("items")
    if not isinstance(items, list):
        raise ValueError(
            f"agenda['items'] は list である必要があります（実際の型: {type(items).__name__}）。"
            "record が破損している可能性があります（agenda:REQ-019 NFR-006: 既定値で補って進行しない）"
        )
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(
                f"agenda['items'][{index}] は dict である必要があります"
                f"（実際の型: {type(item).__name__}）。"
                "record が破損している可能性があります（agenda:REQ-019 NFR-006: 既定値で補って進行しない）"
            )

    generated_at_value = generated_at or datetime.now().isoformat()

    rows_html = "\n".join(_summary_row_html(item, severity_field) for item in items)
    sections_html = "\n".join(_item_section_html(item, severity_field) for item in items)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>アジェンダ: {identity}</title>
<style>{_STYLE}</style>
</head>
<body>
<h1>アジェンダ: {identity}</h1>
<p class="generated-notice">この提示は agenda_render.py によって {_escape(generated_at_value)} に生成された。手編集しても保存されない。</p>
<table id="agenda-summary">
  <thead>
    <tr><th>ID</th><th>項目</th><th>重要度</th><th>状態</th><th>結果・課題</th></tr>
  </thead>
  <tbody>
{rows_html}
  </tbody>
</table>
{sections_html}
</body>
</html>
"""
