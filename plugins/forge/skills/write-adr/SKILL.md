---
name: write-adr
description: |
  決定とその理由・棄却した代替案を、feature ごとの ADR（アーキテクチャ決定記録）ファイルへ記録・更新する。記録に値しない決定は棄却され、情報が足りなければ不足として返る。
  トリガー: "ADR を書いて", "決定を記録して", "ADR を更新して", "write adr"
user-invocable: true
argument-hint: "{approval-record|judgement|update} [feature] [--defer-finish]"
allowed-tools: Bash, Read, Write, Glob, Agent, Skill, AskUserQuestion
---

# /forge:write-adr

このスキルは ADR の作成の依頼のみを行う。親が依頼している他の作業を引き継いではならない。

## Goal

渡された内容を、カスタム Agent `forge:adr-writer` に吟味させ、判定（作成・棄却・不足）に応じて終えること。ADR の判断は、設計の途中経過から隔離した context で行われる。

## フロー継続

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ AskUserQuestion で確認する。

---

## コマンド構文

```
/forge:write-adr {approval-record|judgement|update} [feature] [--defer-finish]
```

| 引数             | 内容                                                                                   |
| ---------------- | -------------------------------------------------------------------------------------- |
| 類型             | `approval-record`（承認記録）/ `judgement`（判断記録）/ `update`（既存の決定の更新）   |
| feature          | 対象の feature 名（省略時は対話で確定する）。複数のコンポーネントに跨る決定は `common` |
| `--defer-finish` | 呼び出し元が完了処理を担うときに付ける。完了処理（Phase 6）を行わない                  |

引数の解釈は AI が行う。不足・曖昧な引数は AskUserQuestion で補う。

---

## 事前準備

### 出力先の解決

`${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/SKILL.md` の「出力先ディレクトリの解決」手順に従い、
doc_type `adr`、feature `{feature}` で ADR の出力先ディレクトリ（`{adr_dir}`）を求める。

エントリが無い場合の扱いは同手順が定める（本スキルは既定パスを持たず、出力先を独自に尋ねない）。

### 規範の読み込み

利用者へ判断を求める場面では、`${CLAUDE_PLUGIN_ROOT}/docs/consult_principles_spec.md` を Read し、背景と本質を先に述べてから提示する。

ADR の書式・規範は、ADR ライター（`forge:adr-writer`）が読む。本スキルは読まない。

---

## Phase 1: 内容の整理

呼び出し元の会話から、ADR にしたい内容を整理し、Write ツールで入力ファイルへ書く。ファイルは次のとおり。内容は、生成・要約・改変せず、会話にあるとおりに書く。

| 入力ファイル                                               | 内容                                               | 必要な類型                      |
| ---------------------------------------------------------- | -------------------------------------------------- | ------------------------------- |
| `.claude/.temp/adr-${CLAUDE_SESSION_ID}-decision.md`       | 決定の内容                                         | `approval-record` / `judgement` |
| `.claude/.temp/adr-${CLAUDE_SESSION_ID}-change.md`         | 対象の決定の節と、変更の内容と理由                 | `update`                        |
| `.claude/.temp/adr-${CLAUDE_SESSION_ID}-context.md`        | 文脈（背景・課題・制約）。要件へ戻せない理由を含む | 任意                            |
| `.claude/.temp/adr-${CLAUDE_SESSION_ID}-alternatives.md`   | 検討した代替案と、棄却理由                         | 任意                            |
| `.claude/.temp/adr-${CLAUDE_SESSION_ID}-approval-quote.md` | 利用者の承認の引用。**発言をそのまま**書く         | `approval-record`               |

会話に無い情報は、利用者に確認する。確認できない場合も、補って書かない（足りない情報は、ADR ライターが「不足」として返す）。

---

## Phase 2: 採番

`next-spec-id` の採番スクリプトで、次の番号を得る。

```bash
SCAN_SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/next-spec-id/scripts/scan_spec_ids.py"
python3 "$SCAN_SCRIPT" ADR --share-prefixes ADR,DES
```

JSON 出力の `next_id` を使う。ADR ファイルがまだ無いときだけ、ファイル名の番号に使われる（ADR ファイルがあるときは使われない）。`duplicates` が空でない場合は、利用者に提示する。手動での番号決定は行わない。

---

## Phase 3: 依頼の公開

```bash
SCRIPT="${CLAUDE_PLUGIN_ROOT}/scripts/adr/adr_exchange.py"

python3 "$SCRIPT" open --kind {kind} --feature "{feature}" --adr-dir "{adr_dir}" --adr-id "{next_id}" \
  {入力ファイルの引数}
```

`{入力ファイルの引数}` は、Phase 1 で書いたファイルを、次のオプションで渡す。

| 入力ファイル        | オプション              |
| ------------------- | ----------------------- |
| `decision.md`       | `--decision-file`       |
| `change.md`         | `--change-file`         |
| `context.md`        | `--context-file`        |
| `alternatives.md`   | `--alternatives-file`   |
| `approval-quote.md` | `--approval-quote-file` |

関連する文書があれば、`--related-doc "{絶対パス}"` を、1 件ごとに繰り返す。

標準出力の `request_id` を保持する。`open` が失敗した場合（終了コードが 0 以外）は、標準出力の `errors` を利用者へ報告して止める。終了コードが 2（引数を受理できない）のときは標準出力が空なので、標準エラーの内容を報告する。

---

## Phase 4: ADR ライターの起動

Agent ツールで、カスタム Agent `forge:adr-writer`（`${CLAUDE_PLUGIN_ROOT}/agents/adr-writer.md`）を起動する。prompt に書くのは識別値だけである。

```
Agent ツール起動: ADR の吟味と記載 (subagent_type: forge:adr-writer)
prompt:
  - adr_dir: {adr_dir}
  - request_id: {request_id}
```

必読文書、依頼の読み方、書いてよいのは記載先だけという制約、吟味の手順は agent 定義が持つ。**prompt で指示を重ねない。**

---

## Phase 5: 判定の取得と分岐

Agent の完了後、script で判定を取得する。return value の内容で判定しない。

```bash
python3 "$SCRIPT" check --adr-dir "{adr_dir}" --request-id "{request_id}"
```

`check` は、成否にかかわらず依頼と判定の記録を削除する。ADR ファイルは残す。

- `status: error` → Agent が最後まで終えられなかった。Agent の最終応答（何が起きたかの自然文）を添えて利用者へ報告し、AskUserQuestion で再実行か中止かを確認する。**再実行は Phase 1 からやり直す**（`check` が依頼を削除し、`open` が入力ファイルを削除しているため）
- `status: ok` → `verdict` の値で分岐する

| `verdict`      | 動作                                                                                                                             |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `created`      | 何も受け取らない。記載先は、出力先の ADR ファイル（`{adr_dir}` の `ADR-*.md`）である。`--defer-finish` が無ければ Phase 6 へ進む |
| `rejected`     | Agent の最終応答の理由を、利用者へ提示して終える。ADR ファイルには何も書かれていない                                             |
| `insufficient` | Agent の最終応答の理由（足りない情報）を、利用者に確認して補い、Phase 1 からやり直す                                             |

---

## Phase 6: 完了処理（`--defer-finish` が無いとき）

### レビュー

Skill ツールで `/forge:review --files {ADR ファイル} --auto` を起動する。対象は、このワークフローで作成・変更した ADR ファイルだけである。

### specs ToC 更新

`/forge:update-db-specs` が利用可能であれば実行する（利用不可の場合はスキップ）。

### commit/push 確認

commit/push の確認フローを担うスキル（例: `anvil:commit`）が available-skills にあれば呼び出す。無ければ `git add` → `git commit` の手順を案内する。

### 完了案内

ADR ファイルのパスを示す。
