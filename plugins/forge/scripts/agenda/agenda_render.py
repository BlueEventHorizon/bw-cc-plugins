#!/usr/bin/env python3
"""agenda 機構の表示層。``agenda.json`` 相当の dict から表示物の文字列を生成する。

設計は agenda:DES-077（表示層設計書）が持つ。公開関数は 2 つで、いずれも
入力から表示物の文字列を返すだけの純粋関数である:

- ``render_agenda_html()``: ``agenda.json`` の内容から ``agenda.html`` 文字列を返す。
  生成物には自動追従スクリプト（DES-077 §4.2）が含まれ、開いているタブは
  ``agenda_state.js`` の世代番号（``content_version``）の変化を検知したときだけ
  ``location.reload()`` で全体を再読み込みする（スクロール位置は保持。§4.3）
- ``render_agenda_state_js()``: 世代番号だけを持つ ``agenda_state.js`` 文字列を返す

呼び出し側（``agenda_store.py``）は書き込み成功のたびに両関数を呼び、2 ファイルを
毎回まるごと再生成する。本モジュールは ``agenda_store.py`` に依存せず、単体で
直接呼び出すこともできる（DES-075 §3.1）。

HTML エスケープパターンは ``plugins/anvil/skills/prepare-figma/scripts/json_to_html.py``
の ``html.escape()`` 使用パターンを踏襲する。
"""

from __future__ import annotations

import html
import json
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
        f'<td><span class="status-pill" data-status="{status}">{status}</span></td>'
        f"<td>{result_cell}</td>"
        "</tr>"
    )


def _decision_dd_html(item: dict) -> str:
    """項目節の「決着」の `<dd>` 内容を返す。未定は控えめな表示にする（DES-077 §3）。"""
    text = _decision_text(item)
    if text == "(未定)":
        return '<span class="undecided">(未定)</span>'
    return _escape(text)


def _item_section_html(item: dict, severity_field: str | None) -> str:
    """項目ごとの `<section>` の HTML を返す（DES-077 §3・§3.1・§3.1a）。

    問題（`problem`）と推奨（`recommendation`）は任意フィールドであり、
    記入があるときだけ行を出す（空のラベルチップを並べない。DES-077 §3）。
    """
    item_id_raw = item.get("id")
    item_id = _escape(item_id_raw)
    title = _escape(item.get("title"))
    background = _escape(item.get("background"))
    essence = _escape(item.get("essence"))
    decision_dd = _decision_dd_html(item)
    changed = _is_changed(item)
    severity_badge = _severity_badge_html(item, severity_field)

    rows: list = []
    problem = item.get("problem")
    if problem:
        rows.append(f"    <dt>問題</dt><dd>{_escape(problem)}</dd>")
    rows.append(f"    <dt>背景</dt><dd>{background}</dd>")
    rows.append(f"    <dt>本質</dt><dd>{essence}</dd>")
    recommendation = item.get("recommendation")
    if recommendation:
        rows.append(
            f'    <dt class="label-recommend">推奨</dt><dd>{_escape(recommendation)}</dd>'
        )
    rows.append(f'    <dt class="label-decision">決着</dt><dd>{decision_dd}</dd>')
    rows_html = "\n".join(rows)

    return (
        f'<section id="item-{item_id}" '
        f'data-changed="{"true" if changed else "false"}">\n'
        f'  <div class="gutter"><span class="state-dot changed"></span></div>\n'
        f'  <h2><span class="item-no">[{item_id}]</span>{title} {severity_badge}</h2>\n'
        "  <dl>\n"
        f"{rows_html}\n"
        "  </dl>\n"
        "</section>"
    )


_STYLE = """
  * { box-sizing: border-box; }
  :root {
    --bg: #f6f7f9;
    --card: #ffffff;
    --ink: #1f2430;
    --ink-muted: #6b7280;
    --line: #e5e8ee;
    --accent: #4a6fa5;
    --changed: #f0c36d;
  }
  body {
    margin: 0;
    padding: 32px 24px 64px;
    font-family: -apple-system, BlinkMacSystemFont, 'Hiragino Sans',
      'Hiragino Kaku Gothic ProN', 'Yu Gothic UI', Meiryo, sans-serif;
    line-height: 1.75;
    background: var(--bg);
    color: var(--ink);
    font-feature-settings: "palt";
  }
  main { max-width: 860px; margin: 0 auto; }

  header { margin-bottom: 20px; }
  h1 {
    font-size: 1.45em;
    margin: 0 0 2px;
    letter-spacing: 0.01em;
  }
  h1::before {
    content: "アジェンダ";
    display: block;
    font-size: 0.55em;
    font-weight: 600;
    color: var(--accent);
    letter-spacing: 0.12em;
  }
  .generated-notice {
    font-size: 0.78em;
    color: var(--ink-muted);
    margin: 4px 0 0;
  }

  #agenda-summary {
    border-collapse: separate;
    border-spacing: 0;
    width: 100%;
    margin: 20px 0 36px;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 10px;
    overflow: hidden;
    font-size: 0.92em;
    box-shadow: 0 1px 2px rgba(31, 36, 48, 0.04);
  }
  #agenda-summary th {
    background: #eef1f5;
    color: #3d4657;
    font-weight: 600;
    font-size: 0.85em;
    letter-spacing: 0.06em;
  }
  #agenda-summary th, #agenda-summary td {
    padding: 9px 14px;
    text-align: left;
    border-bottom: 1px solid var(--line);
  }
  #agenda-summary tr:last-child td { border-bottom: none; }
  #agenda-summary tbody tr:hover { background: #f6f9fd; }
  #agenda-summary td:first-child, #agenda-summary th:first-child {
    text-align: center; width: 3em; color: var(--ink-muted);
    font-variant-numeric: tabular-nums;
  }
  .status-pill {
    display: inline-block;
    font-size: 0.82em;
    padding: 1px 10px;
    border-radius: 999px;
    border: 1px solid var(--line);
    background: #f2f4f7;
    color: #4b5563;
    white-space: nowrap;
  }
  .status-pill[data-status="進行中"] { background: #e8f0fb; border-color: #c9daf1; color: #33567f; }
  .status-pill[data-status="決着"], .status-pill[data-status="adopt"] { background: #e6f2e4; border-color: #cbe3c8; color: #2f6b3a; }

  section {
    position: relative;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 18px 22px 14px;
    margin: 0 0 16px;
    box-shadow: 0 1px 2px rgba(31, 36, 48, 0.04);
  }
  .gutter { position: absolute; left: -18px; top: 22px; }
  .state-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: transparent;
  }
  section[data-changed="true"] .state-dot.changed { background: var(--changed); }

  h2 {
    font-size: 1.08em;
    margin: 0 0 10px;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--line);
  }
  h2 .item-no {
    color: var(--ink-muted);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    margin-right: 6px;
  }

  dl { margin: 0; display: grid; grid-template-columns: max-content 1fr; row-gap: 8px; column-gap: 14px; }
  dt {
    align-self: start;
    margin-top: 0.3em;
    font-size: 0.72em;
    font-weight: 600;
    line-height: 1;
    padding: 5px 10px;
    border-radius: 4px;
    background: #8494ab;
    color: #fff;
    letter-spacing: 0.1em;
    white-space: nowrap;
  }
  dt.label-recommend { background: var(--accent); }
  dt.label-decision { background: #5d7a5f; }
  dd { margin: 0; }
  dd .undecided { color: var(--ink-muted); }

  .severity-badge {
    display: inline-block;
    font-size: 0.68em;
    padding: 2px 8px;
    border-radius: 999px;
    background: #eee;
    color: #555;
    vertical-align: 2px;
    letter-spacing: 0.05em;
  }
  .severity-badge[data-severity="critical"] { background: #fbdada; color: #8a2c2c; }
  .severity-badge[data-severity="major"] { background: #fdeec2; color: #8a6d1f; }
  .severity-badge[data-severity="minor"] { background: #dcf0da; color: #2f6b3a; }
"""

# 自動追従スクリプト（DES-077 §4.2・§4.3）。`file://` では fetch/XHR が CORS で
# ブロックされるため、`<script src>` の差し替えで agenda_state.js の世代番号を読み、
# 自ページに埋め込まれた世代番号と異なるときだけ全体を再読み込みする。
# __KNOWN_VERSION__ は render_agenda_html() が生成時点の content_version（無ければ
# null。null の場合は最初に読めた値を世代番号として採用する）へ置換する。
_FOLLOW_SCRIPT_TEMPLATE = """<script>
(function () {
  var known = __KNOWN_VERSION__;
  function apply(state) {
    if (!state || typeof state.contentVersion !== "number") return;
    if (known === null) { known = state.contentVersion; return; }
    if (state.contentVersion !== known) location.reload();
  }
  function poll() {
    var el = document.createElement("script");
    el.src = "agenda_state.js?t=" + Date.now();
    el.onload = function () { el.remove(); apply(window.AGENDA_STATE); };
    el.onerror = function () { el.remove(); };
    document.head.appendChild(el);
  }
  setInterval(poll, 2000);
  window.addEventListener("pagehide", function () {
    try { sessionStorage.setItem("agendaScrollY", String(window.scrollY)); } catch (e) {}
  });
  try {
    var y = sessionStorage.getItem("agendaScrollY");
    if (y !== null) window.scrollTo(0, parseInt(y, 10));
  } catch (e) {}
})();
</script>"""


def _follow_script_html(content_version: Any) -> str:
    """自動追従スクリプトの HTML を返す。世代番号は整数のみ埋め込む（それ以外は null）。"""
    known = content_version if isinstance(content_version, int) else None
    return _FOLLOW_SCRIPT_TEMPLATE.replace("__KNOWN_VERSION__", json.dumps(known))


def render_agenda_state_js(content_version: Any) -> str:
    """``agenda_state.js`` 文字列を生成する（DES-077 §4.2）。

    世代番号（``content_version``）だけを持つ軽量ファイル。``agenda.html`` 内の
    自動追従スクリプトが ``<script src>`` 差し替えで読み込み、埋め込まれた世代番号と
    比較する。
    """
    known = content_version if isinstance(content_version, int) else None
    return "window.AGENDA_STATE = " + json.dumps({"contentVersion": known}) + ";\n"


def render_agenda_html(agenda: dict, *, generated_at: str | None = None) -> str:
    """``agenda.json`` の内容から ``agenda.html`` 文字列を生成する（DES-077 §3・§4）。

    書き込みのたびに呼び出し側（``agenda_store.py``）が本関数を呼び、
    ``agenda.html`` を毎回まるごと再生成する前提の生成専用関数である。
    生成物には自動追従スクリプト（§4.2・§4.3。世代番号が変わったときだけ
    全体を再読み込みする）を埋め込む。部分更新（DOM の差し替え）は持たない。
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
    follow_script = _follow_script_html(agenda.get("content_version"))

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>アジェンダ: {identity}</title>
<style>{_STYLE}</style>
</head>
<body>
<main>
<header>
<h1>{identity}</h1>
<p class="generated-notice">この提示は agenda_render.py によって {_escape(generated_at_value)} に生成された。手編集しても保存されない。</p>
</header>
<table id="agenda-summary">
  <thead>
    <tr><th>ID</th><th>項目</th><th>重要度</th><th>状態</th><th>結果・課題</th></tr>
  </thead>
  <tbody>
{rows_html}
  </tbody>
</table>
{sections_html}
</main>
{follow_script}
</body>
</html>
"""
