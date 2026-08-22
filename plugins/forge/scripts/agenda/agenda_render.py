#!/usr/bin/env python3
"""agenda 機構の表示層。``agenda.json`` 相当の dict から表示物の文字列を生成する。

設計は agenda:DES-077（表示層設計書）が持つ。本モジュールが公開する 2 関数は、
どちらも「``agenda.json`` の内容を受け取って文字列を返す」だけの純粋関数であり、
``agenda.html`` / ``agenda_state.js`` の再生成タイミング判定（`content_version` の
増減に応じてどちらを再生成するか）は呼び出し側（``agenda_store.py``）が担う
（DES-077 §4.2）。本モジュールは ``agenda_store.py`` に依存せず、単体で直接
呼び出すこともできる（DES-075 §3.1）。

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


def _severity_badge_html(item: dict, severity_field: str | None) -> str:
    """severity バッジの HTML を返す。

    DES-077 §3.1a・agenda:REQ-019 FNC-009（中立性）: ``severity`` というキー名を
    本モジュールが決め打ちしてはならない。``config.severity_field`` が指すキー名
    を ``item.get("fields", {})`` から動的に取り出す。``severity_field`` が
    未指定（``None``）、または対応する値が存在しない場合はバッジ要素自体を
    出力しない（空文字列を返す）。空文字列も「値が存在しない」として扱う
    （`_summary_row_html` の「重要度」列が空文字列を `-` と表示する判定と
    揃える。同一の値に対しモジュール内で解釈が割れないようにする）。
    """
    if not severity_field:
        return ""
    fields = item.get("fields")
    if not isinstance(fields, dict):
        return ""
    value = fields.get(severity_field)
    if not value:
        return ""
    escaped = _escape(value)
    return f'<span class="severity-badge" data-severity="{escaped}">{escaped}</span>'


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
    """アジェンダ表の「結果・課題」列に表示する短い要約を返す。

    ``decision`` が記入済みなら outcome を、未記入なら「未着手」を意味する
    プレースホルダを返す（軽微な表示詳細。§3 のテンプレートは列の存在のみを
    定め、内容の導出方法は定めていないため、DES-075 §4 の既存フィールドから
    妥当な範囲で推測する）。
    """
    decision = item.get("decision")
    if isinstance(decision, dict) and decision.get("outcome"):
        reason = decision.get("reason")
        if reason:
            return _escape(f"{decision['outcome']}: {reason}")
        return _escape(decision["outcome"])
    return "-"


def _is_changed(item: dict) -> bool:
    """`last_changed_fields` が空でない項目かどうかを返す（DES-077 §3.1・§4.2）。"""
    last_changed_fields = item.get("last_changed_fields")
    return isinstance(last_changed_fields, list) and len(last_changed_fields) > 0


def _is_current(item: dict, current_item_id: Any) -> bool:
    """項目が対話中（`current_item_id` と一致）かどうかを返す（DES-077 §3.1）。"""
    return current_item_id is not None and item.get("id") == current_item_id


def _summary_row_html(item: dict, severity_field: str | None, current_item_id: Any) -> str:
    """`#agenda-summary` テーブルの 1 行分の HTML を返す（DES-077 §3 FNC-001）。"""
    item_id = _escape(item.get("id"))
    title = _escape(item.get("title"))
    status = _escape(item.get("status"))
    severity_value = ""
    if severity_field:
        fields = item.get("fields")
        if isinstance(fields, dict):
            severity_value = _escape(fields.get(severity_field))
    severity_cell = severity_value or "-"
    result_cell = _result_summary(item)
    return (
        "<tr>"
        f"<td>{item_id}</td>"
        f"<td>{title}</td>"
        f"<td>{severity_cell}</td>"
        f"<td>{status}</td>"
        f"<td>{result_cell}</td>"
        "</tr>"
    )


def _item_section_html(item: dict, severity_field: str | None, current_item_id: Any) -> str:
    """項目ごとの `<section>` の HTML を返す（DES-077 §3・§3.1・§3.1a）。"""
    item_id_raw = item.get("id")
    item_id = _escape(item_id_raw)
    title = _escape(item.get("title"))
    background = _escape(item.get("background"))
    essence = _escape(item.get("essence"))
    decision_text = _escape(_decision_text(item))
    changed = _is_changed(item)
    current = _is_current(item, current_item_id)
    severity_badge = _severity_badge_html(item, severity_field)

    return (
        f'<section id="item-{item_id}" '
        f'data-changed="{"true" if changed else "false"}" '
        f'data-current="{"true" if current else "false"}">\n'
        f'  <div class="gutter">'
        f'<span class="state-dot changed"></span>'
        f'<span class="state-dot current"></span>'
        f"</div>\n"
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
  section[data-current="true"] .state-dot.current { background: #7fb3e8; }
  .severity-badge {
    display: inline-block;
    font-size: 0.7em;
    padding: 2px 6px;
    border-radius: 4px;
    background: #eee;
    color: #555;
  }
"""

# ページ内 JS: agenda_state.js を 2 秒ごとに <script src> 差し替えで読み込む
# 部分更新機構（DES-077 §4.1・§4.2）。`file://` の CORS 制約を <script src> の
# 動的差し替えで回避する。contentVersion が不変なら DOM 属性のみ更新し、
# 変化した場合のみ location.reload() する。
_POLLING_SCRIPT = """
<script>
  window.__agendaLastVersion = %(content_version)s;
  function agendaApplyState(data) {
    var sections = document.querySelectorAll('section[id^="item-"]');
    sections.forEach(function (section) {
      var itemId = section.id.slice("item-".length);
      var isCurrent = data.currentItemId !== null && itemId === data.currentItemId;
      var isChanged = data.changedItemIds.indexOf(itemId) !== -1;
      section.setAttribute("data-current", isCurrent ? "true" : "false");
      section.setAttribute("data-changed", isChanged ? "true" : "false");
    });
  }
  function agendaPoll() {
    var script = document.createElement("script");
    script.src = "agenda_state.js?t=" + Date.now();
    script.onload = function () {
      var data = window.AGENDA_DATA;
      script.remove();
      if (!data) return;
      if (data.contentVersion !== window.__agendaLastVersion) {
        window.location.reload();
        return;
      }
      agendaApplyState(data);
    };
    document.body.appendChild(script);
  }
  setInterval(agendaPoll, 2000);
</script>
"""

# スクロール位置保持（DES-077 §4.3）。`location.reload()` によるスクロール位置の
# ロスを防ぐため、`pagehide` 時に sessionStorage へ保存し、読み込み後に復元する。
_SCROLL_PRESERVATION_SCRIPT = """
<script>
  window.addEventListener("pagehide", function () {
    sessionStorage.setItem("agendaScrollY", String(window.scrollY));
  });
  (function () {
    var y = sessionStorage.getItem("agendaScrollY");
    if (y !== null) window.scrollTo(0, parseInt(y, 10));
  })();
</script>
"""


def render_agenda_html(agenda: dict, *, generated_at: str | None = None) -> str:
    """``agenda.json`` の内容から ``agenda.html`` 文字列を生成する（DES-077 §3・§4）。

    再生成タイミング（`content_version` が増える操作のときのみ）の判定は
    呼び出し側（``agenda_store.py``。TASK-003）の責務であり、本関数は持たない。
    """
    config = agenda.get("config")
    if not isinstance(config, dict):
        config = {}
    severity_field = config.get("severity_field")
    identity = _escape(config.get("identity"))
    current_item_id = agenda.get("current_item_id")
    content_version = agenda.get("content_version")
    items = agenda.get("items")
    if not isinstance(items, list):
        items = []

    generated_at_value = generated_at or datetime.now().isoformat()

    rows_html = "\n".join(
        _summary_row_html(item, severity_field, current_item_id)
        for item in items
        if isinstance(item, dict)
    )
    sections_html = "\n".join(
        _item_section_html(item, severity_field, current_item_id)
        for item in items
        if isinstance(item, dict)
    )

    polling_script = _POLLING_SCRIPT % {
        "content_version": json.dumps(content_version),
    }

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
{polling_script}
{_SCROLL_PRESERVATION_SCRIPT}
</body>
</html>
"""


def render_agenda_state_js(agenda: dict, *, generated_at: str | None = None) -> str:
    """``agenda.json`` の内容から ``agenda_state.js`` 文字列を生成する（DES-077 §4.2）。

    ``{currentItemId, changedItemIds, contentVersion, updatedAt}`` のみを持つ
    軽量ファイル。各フィールドは ``agenda.json`` の既存フィールドの単純な転記・
    集約であり、AI が新たに考案する値ではない（DES-077 §4.2 の対応表）。
    """
    current_item_id = agenda.get("current_item_id")
    content_version = agenda.get("content_version")
    items = agenda.get("items")
    if not isinstance(items, list):
        items = []

    changed_item_ids = [
        item.get("id")
        for item in items
        if isinstance(item, dict) and _is_changed(item)
    ]

    updated_at = generated_at or datetime.now().isoformat()

    state = {
        "currentItemId": current_item_id,
        "changedItemIds": changed_item_ids,
        "contentVersion": content_version,
        "updatedAt": updated_at,
    }
    return f"window.AGENDA_DATA = {json.dumps(state, ensure_ascii=False)};\n"
