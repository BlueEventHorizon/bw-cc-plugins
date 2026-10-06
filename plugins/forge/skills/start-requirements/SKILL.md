---
name: start-requirements
description: |
  要件定義書を作成する。3モード対応: 対話形式でゼロから/既存コード解析で逆算/Figma デザインから抽出。
  完了後にレビュー+自動修正→ToC更新→commit の完了フローを実行する。
  トリガー: "要件定義", "要件定義書作成", "ソースから要件抽出", "Figma から要件"
user-invocable: true
argument-hint: "[feature-name] [--mode interactive|reverse-engineering|from-figma]"
---

# /forge:start-requirements

要件定義書を作成する。3つのモードに対応:

- **interactive**: ゼロから対話しながら要件を固める
- **reverse-engineering**: 既存アプリのソースコードから要件を抽出
- **from-figma**: Figma デザインファイルから要件とデザイントークンを作成

## Goal

選択モード（interactive / reverse-engineering / from-figma）に応じて要件定義書を作成し、レビュー+自動修正・ToC更新・commit まで完走すること。

## フロー継続

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ AskUserQuestion で確認する。

## 議論モードの基本原則

ユーザーの「叩き台を作って」「全面改訂してレビューしよう」「議論しよう」「壁打ち」は **議論起点** であり、決定フローではない。詳細は `requirements_interactive_workflow.md` § 対話の基本原則 8-11 を参照。

要点のみ:

- 叩き台を書いたら一度止まる。連続 AskUserQuestion で詰めない
- 改訂履歴セクションを作らない (履歴は CHANGELOG.md、設計判断の変更は ADR へ)
- 大規模 rewrite 後は grep で stale 文言を必ず検査
- システム的 feature は「用語 → アーキテクチャ → 状態 → データモデル → 要件」の順で積み上げる
- 「批判的にレビュー」依頼には A/B/C 比較 + 1 推奨案 + 決定は委ねる、のフォーマットで返す

## コマンド構文

```
/forge:start-requirements [feature] [--mode interactive|reverse-engineering|from-figma]
```

| 引数    | 内容                                                   |
| ------- | ------------------------------------------------------ |
| feature | Feature 名（省略時は、要件定義書を書く直前に確定する） |
| --mode  | モード指定（省略時は選択肢提示）                       |

新規か既存への追加か、差分開発かどうかは引数で指定しない。差分開発かどうかは、interactive のときだけ、既存の要件定義書との関係から判定する（下記「要件定義書を書く直前の決定」）。

---

## 前提確認

### Step 1: モード選択

`--mode` 未指定時、AskUserQuestion を使用して選択肢を提示する:

```
どの方法で要件定義を開始しますか？
1. interactive         — ゼロから対話しながら要件を固める
2. reverse-engineering — 既存アプリのソースコードを解析して要件を抽出
3. from-figma          — Figma デザインファイルから要件とデザイントークンを作成
```

---

## Phase 0: 事前確認（全モード共通）

**フィーチャー概念の把握**: 以下を Read し、フィーチャーとは何か・名前空間の原則を把握する。

- `${CLAUDE_PLUGIN_ROOT}/docs/additive_development_spec.md` §0 — フィーチャーの概念定義

feature・出力先・ファイル名は、ここでは決めない。要件定義書のファイルを書く直前に、次の「要件定義書を書く直前の決定」で決める。ファイル名の `{name}` は、書く内容が固まってからでないと決められないためである。

---

## 要件定義書を書く直前の決定（全モード共通）

各ワークフローは、要件定義書のファイルを書く直前（要件 ID の採番の直前）に、次の順で決める。決定を行う位置は、各ワークフローが指定する。

### 1. 完全新規かどうか

`${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/SKILL.md` の「出力先ディレクトリの解決」手順に従い、doc_type `requirement` で、feature を指定せずに、既存の要件定義書の有無を求める。既存の要件定義書が 1 件も無ければ完全新規である（`additive_development_spec.md` §0）。interactive は、既存資産の確認の要否を決めるために、この判定を Phase 0 で先に行い、結果を使う。

### 2. 差分開発かどうかの判定（interactive のみ）

完全新規でない場合、interactive は、純粋追加型か差分開発型かを判定し、ユーザーの承認を得る。手順は `requirements_interactive_workflow.md` が定める。reverse-engineering と from-figma は、既存のコード・Figma から要件を起こすため、判定しない。

### 3. feature の決定

`${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/SKILL.md` の「feature の決定」手順に従い、doc_type `requirement` で決める。引数で feature が指定されていれば `--feature` に渡す（変更せずそのまま使用。AI による置き換え禁止）。`decision` の扱いは同手順が定める（決められなければ AskUserQuestion でフィーチャー名を確認する）。

差分開発型のときは、旧仕様と分離して管理するため、差分 feature を使う（`additive_development_spec.md` §0）。決定した feature が既存の feature を指す場合は、AskUserQuestion で確認する。

### 4. 出力先ディレクトリの解決

`${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/SKILL.md` の「出力先ディレクトリの解決」手順に従い、doc_type `requirement`、feature `{feature}` で出力先ディレクトリを求める。

エントリが無い場合の扱いは同手順が定める（本スキルは既定パスを持たない）。

### 5. ファイル名の決定

ファイル名は `{要件ID}_{name}_spec.md`（例: `SCR-001_login_screen_spec.md`）とする。要件 ID は、各ワークフローの採番手順で取る。

`{name}` は英語のスネークケースで、**その要件が扱う機能を表す名前**とする。一覧を見た人が中身を推測できること。`spec` / `detail` 等、内容を示さない名前を使わない。

---

## ワークフローの実行

モード確定後、該当するワークフローファイルを **Read** し、そのファイルの指示に従って作業を実行する。

| モード              | ファイルパス                                                                                        |
| ------------------- | --------------------------------------------------------------------------------------------------- |
| interactive         | `${CLAUDE_PLUGIN_ROOT}/skills/start-requirements/docs/requirements_interactive_workflow.md`         |
| reverse-engineering | `${CLAUDE_PLUGIN_ROOT}/skills/start-requirements/docs/requirements_reverse_engineering_workflow.md` |
| from-figma          | `${CLAUDE_PLUGIN_ROOT}/skills/start-requirements/docs/requirements_from_figma_workflow.md`          |

Read 後、ワークフローファイルの最初の Phase から開始する。各ワークフローは完了処理（AI レビュー・ToC 更新・commit 確認）まで自己完結している。SKILL.md に戻る必要はない。
