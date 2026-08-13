#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""review: 段階的提示の仕分けファイルを作成・更新する。

段階的提示は所見を 1 件ずつ人間へ提示して採否を得る。この提示は**設計上ターンをまたぐ**
ため、所見・AI の評価・利用者の判断をコンテキストだけで保持すると、圧縮で失われたときに
再レビューからやり直しになる。失われたこと自体も検知できない。このファイルはその保険で
あり、同時にコンソールより読みやすい提示媒体でもある。

## 入口は 1 つだけである [MANDATORY]

作成も更新も本スクリプトが行う。**「作り直す」経路を持たない。**

かつては作成専用のスクリプトがあり、既存を上書きしていた。その結果、レビューの途中で
所見の集合が変わるたびに作り直され、**書き込んだ決着が消えた**。しかも消えたことは
誰にも見えなかった（ファイルは常にそれらしい姿で存在するため）。守りたかったものを
消す仕組みを、保険と呼んでいたことになる。

途中で起きる変化はすべて更新操作で表せる。決着した、取り下げを差し戻した、議論の中で
新しい所見が出た——いずれも既存の行を書き換えるか、行を足すかである。作り直す理由は
無い。

## 増殖しない [MANDATORY]

追加は**位置 + 本文**を同一性として冪等に扱う。同じ所見をもう一度 `--add-json` へ
渡しても、既存の行を数えて何もしない（`skipped` として報告する）。再実行で消えるのを
避けた代わりに再実行で増えるのでは、失敗の向きが変わっただけである。

識別子は既存の最大 + 1 で振り、**既存の識別子は動かさない**。利用者が会話で指した
番号が別の所見を指すようになると、対話とファイルの対応が切れる。

## 状態は 1 つの語彙で表す

位置未確定の所見も取り下げた所見も、判断が要る所見と同じ 1 つの表に載せ、`状態` で
区別する。語彙は consult 提示原則が定めるものを使う。

| 状態     | 意味                                             |
| -------- | ------------------------------------------------ |
| `未着手` | まだ提示していない                               |
| `進行中` | 提示して議論している                             |
| `決着`   | 採否が決まった                                   |
| `保留`   | 判断を先送りした                                 |
| `取り下げ` | 指摘が誤りだったので取り消した（AI の判断）    |
| `対象外` | 最初から範囲外（位置未確定で修正対象を特定できない） |

**別々の節へ隔離しない**。隔離すると、利用者は「全部で何件あり、どれが残っているか」を
複数の表から数え直すことになる。1 つの表に状態を並べれば、残件は目で追える。

## 判定は AI が渡す [MANDATORY]

本スクリプトは対象のコードも文書も読まない。**所見が妥当か・修正を任せられるかは判断
しない。** 判断は AI が `confidence` と `fix_confident` として渡し、本スクリプトは
それを記号へ写すだけである。

アジェンダ表へ入れる要約（`summary`）も AI が渡す。**機械的に切り詰めない**——切り詰めは
文の途中で切るため、背景の書き出しだけが残ることがある。consult 提示原則が求めているのは
「表には課題の所在を書く」ことであって「短く切る」ことではない。

## 依存

Python 標準ライブラリのみ。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from split_by_location import _has_unknown_location  # noqa: E402

#: 仕分けファイルの置き場（プロジェクトルート相対）
TRIAGE_DIR = Path(".claude") / ".temp" / "review"

#: 仕分けファイルの名前。
#:
#: **常に 1 つに保つ。** 名前を review_id で分けると複数になり、「どれを開くのか」
#: という問題が生まれて探す仕組みが要る。1 つに限定すれば探す必要が無く、置き場を見れば
#: それが対象である。前回の残りは依頼の開始時に利用者へ確認して片付ける。
TRIAGE_FILENAME = "triage.md"

#: 重大度の表示順（提示順の材料。採否の可否は決めない）
SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}

#: 重大度の表示記号
SEVERITY_MARK = {
    "critical": "🔴 critical",
    "major": "🟡 major",
    "minor": "🟢 minor",
}

#: 「指摘は正しいと確信している」ことを示す記号。
CONFIRMED_MARK = "☑️"

#: 「指摘が正しく、かつ修正も責任を持って実行できる」ことを示す記号。
#:
#: **`CONFIRMED_MARK` を含む [MANDATORY]**。指摘が正しいと確信できていないものを直す
#: ことはできないため、`☑️` でなければ `✅` はありえない。順序のある 1 つの尺度である。
#:
#: 2 つの記号が答える問いは別である。`☑️` は**所見**についての確信（レビュアーの指摘は
#: 正しいか）、`✅` は**対策**についての確信（その修正を責任を持って実行できるか）。
#: この区別が無いと「指摘は正しいが直し方が分からない」を表せない。
#:
#: **介入軸は条件に入らない [MANDATORY]**。`--auto` はこの条件を満たす所見を自動で直す
#: モードにすぎず、条件そのものは `--interactive` でも同じに成立する。
AUTO_FIX_MARK = "✅"

#: 状態の語彙（consult 提示原則）
STATE_PENDING = "未着手"
STATE_DROPPED = "取り下げ"
STATE_OUT_OF_SCOPE = "対象外"
STATES = (STATE_PENDING, "進行中", "決着", "保留", STATE_DROPPED, STATE_OUT_OF_SCOPE)

#: 節に置く欄。値は AI が書く。
FIELD_FINDING = "レビュアーの所見"
FIELD_ORDER = ("背景", "本質", "指摘は正しいか", "修正を任せられるか", "対応", "推奨", "決着")

#: 欄の初期値。**既に決まっているものは空欄にしない**（決まっている判断をもう一度
#: させることになり、2 回目の答えが 1 回目と食い違っても誰も気付かない）。
FIELD_PLACEHOLDER = {
    "背景": "<なぜこれが問題か>",
    "本質": "<判断を左右しているのはどこか>",
    # 解決策と、それを採るかどうかは別のものである。1 つの欄へ混ぜると
    # 「推奨: 採用する。〜を直す」のようになり、何を採否するのかが読めない。
    "対応": "<何をどう直すか。採用しないなら「なし」>",
    "推奨": "<採用する / 採用しない。理由を 1 行>",
    "決着": "<利用者の判断と理由。AI が決めた場合はその旨>",
}

#: 見出しの接頭辞。**`review_id` の置き場はここ 1 か所である**（別レビューの所見が
#: 混ざらないよう、追加時にこの値と照合する）。
TITLE_PREFIX = "# レビュー所見の仕分け: "

_AGENDA_HEADER = "| ID | 判定 | 重大度 | 状態 | 結果・課題 |"
_SECTION_RE = re.compile(r"^## \[(\d+)\] ", re.MULTILINE)


def _severity_key(entry: dict) -> int:
    return SEVERITY_ORDER.get(entry.get("severity"), len(SEVERITY_ORDER))


def _severity_label(entry: dict) -> str:
    severity = entry.get("severity")
    return SEVERITY_MARK.get(severity, str(severity))


def _location_label(finding: dict) -> str:
    """`パス:行` 形式。位置未確定・欠落はその旨を返す。

    **入力の所見（`location` は辞書）と、ファイルから読み戻したエントリ
    （`location` は表示済みの文字列）の両方を受ける [MANDATORY]**。片方しか
    扱えないと、同一性の突合（`_identity`）が常に食い違って追加が冪等でなくなる。
    """
    location = finding.get("location")
    if isinstance(location, str):
        return location
    if not isinstance(location, dict) or location.get("unknown"):
        return "位置未確定"
    path = location.get("path")
    if not path:
        return "位置未確定"
    line = location.get("line")
    return f"{path}:{line}" if line is not None else str(path)


def _cell(text: str) -> str:
    """表のセルへ入れる 1 行。改行とパイプだけを畳む。

    **長さで切らない。** 切り詰めは文の途中で切るため、課題の所在ではなく背景の
    書き出しだけが残ることがある。何を書くかは AI が `summary` として決める。
    """
    return " ".join(str(text).split()).replace("|", "\\|")


def _mark(entry: dict) -> str:
    """判定の記号。`✅` ⊃ `☑️` の順序を持つ 1 列。

    矛盾した入力は低い側へ倒す（`fix_confident` が真でも `confidence` が
    `confirmed` でなければ `✅` にしない）。高い側へ倒すと、確信の無い修正が
    確認なしに適用される。
    """
    confirmed = entry.get("confidence") == "confirmed"
    if confirmed and entry.get("fix_confident"):
        return AUTO_FIX_MARK
    return CONFIRMED_MARK if confirmed else ""


def _identity(entry: dict) -> tuple[str, str]:
    """所見の同一性。**位置 + 本文**で見る。

    同じ所見を二度足しても増えないようにするための鍵である。識別子は追加のたびに
    新しく振られるため同一性にならず、本文だけでは別の箇所への同じ指摘を潰す。
    """
    return (_location_label(entry), " ".join(str(entry.get("text", "")).split()))


def _initial_state(finding: dict) -> str:
    """追加時の状態。**生成時点で決まっているものは決着済みとして出す。**

    `未着手` で出してから書き換える形にはしない。書き換え前のファイルを読んだ
    利用者に未決着として見え、書き換えを忘れれば恒久的に誤った状態が残る。
    """
    if _has_unknown_location(finding):
        return STATE_OUT_OF_SCOPE
    if str(finding.get("drop_reason", "")).strip():
        return STATE_DROPPED
    return STATE_PENDING


def _settled_note(finding: dict, state: str) -> str:
    if state == STATE_DROPPED:
        return str(finding.get("drop_reason", "")).strip() or "（理由未記入）"
    if state == STATE_OUT_OF_SCOPE:
        return "位置が確定していないため修正対象を特定できない。人間が直接内容を確認する必要がある"
    return ""


def make_entry(finding: dict, entry_id: str) -> dict:
    state = _initial_state(finding)
    settled = _settled_note(finding, state)
    if state == STATE_PENDING and not str(finding.get("summary", "")).strip():
        # 所見本文を表へ流し込まない。数百字の散文が入ると表が読めなくなり、
        # consult 提示原則（表には課題の所在を書く）に反する。切り詰めて誤魔化さず、
        # 「何が問題か」の 1 行を AI に書かせる。
        raise ValueError(
            f"summary が要ります（課題の所在を 1 行で）: {_location_label(finding)}"
        )
    fields = dict(FIELD_PLACEHOLDER)
    fields["指摘は正しいか"] = (
        f"{CONFIRMED_MARK} 確信あり" if finding.get("confidence") == "confirmed" else "確信なし"
    )
    fields["修正を任せられるか"] = (
        f"{AUTO_FIX_MARK} 責任を持って実行できる"
        if _mark(finding) == AUTO_FIX_MARK
        else "直し方に確信が無い"
    )
    if settled:
        fields["決着"] = settled
    return {
        "id": entry_id,
        "severity": finding.get("severity"),
        "location": _location_label(finding),
        "text": str(finding.get("text", "")).strip(),
        "state": state,
        "result": _cell(finding.get("summary") or settled or finding.get("text", "")),
        "confidence": finding.get("confidence"),
        "fix_confident": bool(finding.get("fix_confident")),
        "fields": fields,
    }


def agenda_table(entries: list[dict]) -> str:
    """アジェンダ表の Markdown。**ファイルと CLI 出力で同じものを使う [MANDATORY]**。

    利用者へ提示する表を AI が手で書き起こすと、ファイルと食い違う。実際に、
    決着させていない所見をコンソールだけ `進行中` と書いた事故が起きた。更新の
    たびに更新後の表を返し、AI はそれをそのまま貼る。
    """
    lines = [_AGENDA_HEADER, "| --- | --- | --- | --- | --- |"]
    for entry in entries:
        lines.append(
            f"| {entry['id']} | {_mark(entry)} | {_severity_label(entry)} "
            f"| {entry['state']} | {_cell(entry['result'])} |"
        )
    if not entries:
        lines.append("| — | — | — | — | 所見はありません |")
    return "\n".join(lines)


def render(meta: dict, entries: list[dict]) -> str:
    """ファイルの体裁はここだけが決める。

    **見出しとアジェンダと節しか置かない [MANDATORY]**。かつては冒頭にメタ表があり、
    `review_id`（見出しと重複）・ラウンド番号・バックエンド名・件数を並べていた。
    件数はアジェンダを見れば分かり、CLI の出力にも載る。バックエンド名は依頼時の
    出力と要約報告に出る。**同じ値を 2 か所に置くと、片方だけが古くなる。**

    ラウンド番号を持たないのは、**それが所見の扱いを何ひとつ決めないため**である。
    ラウンドはレビュアーとの往復回数であり、どの所見をどう扱うかとは無関係である。
    持たせると「ラウンドが上がったとき既存の行をどうするか」「所見ごとにラウンドを
    持たせるか」という問いが生まれるが、いずれもこのフィールドが存在するからだけで
    生まれる問いである。
    """
    lines: list[str] = []
    review_id = meta.get("review_id", "")

    lines.append(f"{TITLE_PREFIX}{review_id}")
    lines.append("")

    lines.append("## アジェンダ")
    lines.append("")
    lines.append(
        f"`{AUTO_FIX_MARK}` は指摘が正しく、**修正も責任を持って実行できる**こと。"
        f"`{CONFIRMED_MARK}` は**指摘は正しいが、直し方に確信が無い**こと。"
        "無印は指摘そのものの妥当性に確信が無いこと。介入軸によらず立つ。"
    )
    lines.append("")
    lines.append(agenda_table(entries))
    lines.append("")

    for entry in entries:
        mark = _mark(entry)
        heading_mark = f"{mark} " if mark else ""
        lines.append(
            f"## [{entry['id']}] {heading_mark}{_severity_label(entry)} `{entry['location']}`"
        )
        lines.append("")
        lines.append(f"**{FIELD_FINDING}**:")
        lines.append("")
        lines.append(entry["text"])
        lines.append("")
        for name in FIELD_ORDER:
            lines.append(f"**{name}**: {entry['fields'].get(name, '')}")
            lines.append("")

    return "\n".join(lines) + "\n"


def parse(text: str) -> tuple[dict, list[dict]]:
    """自分が生成した書式を読み戻す。

    更新のたびに全体を組み立て直すため、**読み戻せない情報を作らない**。
    読めない場合は黙って捨てず、例外で止める。
    """
    meta: dict = {"review_id": ""}
    for line in text.splitlines():
        if line.startswith(TITLE_PREFIX):
            review_id = line[len(TITLE_PREFIX):].strip()
            if len(review_id.split()) > 1:
                # 見出しの残りを丸ごと取り込まない。書式を変えた前後のファイルが
                # 混ざると、`review_id` に余分な語が入ったまま再生成で固定される
                # （実際に旧見出しの `(round N)` を取り込んだ）。空白を含む値は
                # msg-review のワイヤヘッダ（`review_id=\S+`）も通らない。
                raise ValueError(
                    f"見出しの review_id に空白が含まれています: {review_id!r}\n"
                    "古い書式のファイルの可能性があります。削除して作り直してください"
                )
            meta["review_id"] = review_id
            break

    rows: dict[str, dict] = {}
    in_agenda = False
    for line in text.splitlines():
        if line == _AGENDA_HEADER:
            in_agenda = True
            continue
        if in_agenda:
            if not line.startswith("|"):
                in_agenda = False
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) != 5 or cells[0] in ("---", "—", "ID"):
                continue
            # 位置は節の見出しから読む。アジェンダ表には持たせない——全パスは長く、
            # 表の幅を占めるわりに行の選択には使われない（ファイル名だけへ縮めると
            # `SKILL.md` のように同名が多数あって曖昧になる）。
            rows[cells[0]] = {"id": cells[0], "state": cells[3], "result": cells[4]}

    entries: list[dict] = []
    parts = _SECTION_RE.split(text)
    # parts = [前置き, id, 本体, id, 本体, ...]
    for entry_id, body in zip(parts[1::2], parts[2::2]):
        row = rows.get(entry_id)
        if row is None:
            raise ValueError(f"アジェンダ表に無い節があります: [{entry_id}]")
        heading = body.split("\n", 1)[0]
        severity = None
        for key, mark in SEVERITY_MARK.items():
            if mark in heading:
                severity = key
                break
        location_match = re.search(r"`([^`]+)`", heading)
        if location_match is None:
            raise ValueError(f"節の見出しから位置を読めません: [{entry_id}] {heading!r}")
        fields: dict[str, str] = {}
        for name in FIELD_ORDER:
            m = re.search(rf"^\*\*{re.escape(name)}\*\*: (.*)$", body, re.MULTILINE)
            fields[name] = m.group(1).strip() if m else ""
        m = re.search(
            rf"\*\*{re.escape(FIELD_FINDING)}\*\*:\n\n(.*?)\n\n\*\*", body, re.DOTALL
        )
        entries.append({
            "id": entry_id,
            "severity": severity,
            "location": location_match.group(1),
            "text": m.group(1).strip() if m else "",
            "state": row["state"],
            "result": row["result"],
            "confidence": (
                "confirmed" if fields["指摘は正しいか"].startswith(CONFIRMED_MARK) else "unverified"
            ),
            "fix_confident": fields["修正を任せられるか"].startswith(AUTO_FIX_MARK),
            "fields": fields,
        })

    missing = set(rows) - {e["id"] for e in entries}
    if missing:
        raise ValueError(f"節の無い行があります: {sorted(missing)}")
    return meta, entries


def load(path: Path) -> tuple[dict, list[dict]]:
    if not path.exists():
        return {"review_id": ""}, []
    return parse(path.read_text(encoding="utf-8"))


def add(entries: list[dict], findings: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """所見を足す。同一のものは足さない（冪等）。

    識別子は既存の最大 + 1 から振る。**既存は動かさない。**
    """
    known = {_identity(e) for e in entries}
    next_id = max((int(e["id"]) for e in entries), default=0) + 1
    added: list[dict] = []
    skipped: list[dict] = []
    for finding in sorted(findings, key=_severity_key):
        if _identity(finding) in known:
            skipped.append(finding)
            continue
        known.add(_identity(finding))
        entry = make_entry(finding, f"{next_id:02d}")
        next_id += 1
        entries.append(entry)
        added.append(entry)
    return entries, added, skipped


def update(entries: list[dict], entry_id: str, state=None, result=None, fields=None) -> dict:
    """1 件を書き換える。**存在しない識別子はエラーにする。**

    打ち間違いを静かに無視すると、書いたつもりの決着がどこにも残らない。
    """
    for entry in entries:
        if entry["id"] == entry_id:
            break
    else:
        raise KeyError(f"存在しない ID です: {entry_id}")
    if state is not None:
        if state not in STATES:
            raise ValueError(f"未知の状態です: {state}（{'/'.join(STATES)}）")
        entry["state"] = state
    if result is not None:
        entry["result"] = result
    for name, value in (fields or {}).items():
        if name not in FIELD_ORDER:
            raise ValueError(f"未知の欄です: {name}（{'/'.join(FIELD_ORDER)}）")
        entry["fields"][name] = value
    return entry


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="段階的提示の仕分けファイルを作成・更新する（作り直す経路は持たない）"
    )
    parser.add_argument("--add-json", help="足す所見の配列（JSON 文字列）")
    parser.add_argument("--id", help="更新する所見の識別子")
    parser.add_argument("--state", help=f"更新後の状態（{'/'.join(STATES)}）")
    parser.add_argument("--result", help="アジェンダ表の「結果・課題」へ書く 1 行")
    parser.add_argument(
        "--field", action="append", default=[],
        help=f"節の欄を更新する（`名前=値`）。名前は {'/'.join(FIELD_ORDER)}",
    )
    parser.add_argument("--review-id", help="新規作成時に必須")
    parser.add_argument("--project-root", default=None)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    root = Path(args.project_root) if args.project_root else Path.cwd()
    path = root / TRIAGE_DIR / TRIAGE_FILENAME

    if not args.add_json and not args.id:
        print("--add-json か --id のどちらかが要ります", file=sys.stderr)
        return 1

    try:
        meta, entries = load(path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    created = not path.exists()
    if created:
        if not (args.review_id or "").strip():
            print("新規作成には --review-id が要ります", file=sys.stderr)
            return 1

    if args.review_id and args.review_id.strip() != meta["review_id"] and meta["review_id"]:
        # 別レビューの所見を同じファイルへ混ぜない [MANDATORY]。
        #
        # ファイル名は固定であり、どのレビューのものかを名前が持たない。照合せずに
        # 追記すると、前のセッションの残りが今回の所見と同じ表に並び、見出しの
        # review_id だけが新しい値へ置き換わる。そうなると「これは前回の残りか」を
        # 利用者も AI も判別できない。**名前ではなく中身で照合する**（名前に
        # review_id を入れると「どれを開くのか」という別の問題が戻る）。
        print(
            f"別のレビューの仕分けファイルが残っています: {path}\n"
            f"  既存: {meta['review_id']}\n"
            f"  今回: {args.review_id.strip()}\n"
            "削除して新しく始めるか、既存の続きから進めるかを利用者に確認してください"
            "（--review-id を既存の値にすれば続きから進められます）",
            file=sys.stderr,
        )
        return 1
    if args.review_id:
        meta["review_id"] = args.review_id.strip()

    added: list[dict] = []
    skipped: list[dict] = []
    try:
        if args.add_json:
            entries, added, skipped = add(entries, json.loads(args.add_json))
        if args.id:
            fields = {}
            for item in args.field:
                name, _, value = item.partition("=")
                fields[name.strip()] = value
            update(entries, args.id, args.state, args.result, fields)
    except (KeyError, ValueError) as exc:
        # 打ち間違いを traceback で返さない。利用者が直せる 1 行にする。
        print(str(exc).strip("'"), file=sys.stderr)
        return 1

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(meta, entries), encoding="utf-8")

    print(json.dumps({
        "triage_path": str(path.relative_to(root)),
        "absolute_path": str(path.resolve()),
        "created": created,
        "added_ids": [e["id"] for e in added],
        "skipped_count": len(skipped),
        "agenda": agenda_table(entries),
        "total_count": len(entries),
        "auto_fixable_count": len([e for e in entries if _mark(e) == AUTO_FIX_MARK]),
        "open_count": len([e for e in entries if e["state"] in (STATE_PENDING, "進行中")]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
