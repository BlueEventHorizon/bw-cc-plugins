---
name: create-requirements-from-plan-mode
description: |
  Claude Code plan mode で書いた **Markdown plan** から、要件定義書を作成する。plan の内容は詳細設計も含めてすべて要件定義書に取り込む。
  本 skill が入力にするのは **Claude Code plan mode の Markdown plan** であり、
  forge の実装計画書 `{feature}_plan.json`（JSON、`/forge:start-plan` が作成）とは別物。
  Markdown plan を起点に feature の仕様化を始めたいときに使う。設計書は作らない（続けて `/forge:start-design` を使う）。
  トリガー: "plan mode から要件作成", "markdown plan から要件定義", "create requirements from plan mode"
user-invocable: true
argument-hint: "[plan-file-path]"
allowed-tools: Bash, Read, Skill, AskUserQuestion, Glob
---

# /forge:create-requirements-from-plan-mode

Claude Code の plan mode で生成された **Markdown plan** を入口に、要件定義書を作成する薄いオーケストレーション skill。

- 入力: **Markdown plan**（`~/.claude/plans/*.md` 形式を想定。任意のパスも可）
- 出力: 要件定義書（`forge:start-requirements` の出力）。設計書は作らない
- 対象外: forge の実装計画書 `{feature}_plan.json`（JSON 構造の計画書） — こちらは `/forge:start-plan` が作成・更新する

> ⚠️ **「plan」の語の使い分け** [MANDATORY]
>
> | 用語                                       | 形式     | 作成元                                         | 本 skill との関係     |
> | ------------------------------------------ | -------- | ---------------------------------------------- | --------------------- |
> | **Markdown plan**                          | Markdown | Claude Code plan mode (`~/.claude/plans/*.md`) | **本 skill の入力**   |
> | **forge 実装計画書 `{feature}_plan.json`** | JSON     | `/forge:start-plan`                            | **本 skill の対象外** |
>
> 本文書で単に「plan」と呼ぶときは **Markdown plan** を指す。
> forge 実装計画書のことを指すときは必ず `{feature}_plan.json` と明示する。

## フロー継続

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ AskUserQuestion で確認する。

---

## コマンド構文

使い方:

```
/forge:create-requirements-from-plan-mode [plan-file-path]
```

| 引数           | 内容                                                                               |
| -------------- | ---------------------------------------------------------------------------------- |
| plan-file-path | **Markdown plan** のパス（省略時は `~/.claude/plans/` から直近を提示して確認する） |

---

## Phase 1: plan ファイルの特定

### 1.1 引数あり

引数 `plan-file-path` が与えられている → そのパスを使用。Read で実在を確認し、存在しなければ AskUserQuestion で再入力を求める。

### 1.2 引数なし → 直近候補の提示

`~/.claude/plans/` から直近の plan を取得する:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/list_recent_plans.py" --limit 8
```

JSON 出力を読み、`status` で分岐:

| status      | 動作                                                                                                     |
| ----------- | -------------------------------------------------------------------------------------------------------- |
| `"found"`   | 直近 1 件 (`latest`) を AskUserQuestion で提示し「これを使う / 一覧から選ぶ / パスを直接指定」を選ばせる |
| `"empty"`   | AskUserQuestion で plan ファイルパスの直接入力を求める                                                   |
| `"missing"` | `plans_dir` が存在しない旨を表示し、AskUserQuestion で plan ファイルパスの直接入力を求める               |

### 1.3 一覧から選択

ユーザーが「一覧から選ぶ」を選んだ場合、`plans` 配列の各エントリ（title, mtime_iso, path）を表示し、AskUserQuestion で対象を選ばせる。選択肢は最大 4 件まで（先頭 3 件 + 「Other」で他を入力）。

### 1.4 plan の Read

確定した plan ファイルを Read で全文読み込む。**plan の内容を以降の Phase で参照するため、Read 結果はコンテキストに保持しておく**。`~/.claude/plans/` の plan は通常数十 KB 以内で context window に収まるため、無条件に全文を読む。

---

## Phase 2: 対象 plugin（namespace）の確認

`docs/specs/` 配下の名前空間（プラグイン名 / `common`）から、要件定義書の格納先を決める。

### 2.1 候補の列挙

```bash
ls -1 docs/specs/ 2>/dev/null
```

### 2.2 plan からの推定

plan の内容（タイトル・本文の語彙）から最有力候補を 1 つ推定する。例: plan に「GitHub Issue」「PR 作成」が頻出 → `anvil`、「レビュー」「要件・設計・計画」 → `forge`。

### 2.3 ユーザー確認

AskUserQuestion を使って対象を確定する。推定した最有力候補を先頭に置き、ラベル末尾に「(Recommended)」を付与する。`docs/specs/` の候補が 4 件を超える場合は推定上位 3 件 + 「その他（Other で入力）」とする。

```
要件定義書の格納先（namespace）を選んでください
- {推定先頭}  (Recommended)
- {その他}
- ...
```

ユーザーが「Other」で任意の文字列を入れた場合（例: 新規 plugin の追加）は、その値をそのまま namespace として使用する。

---

## Phase 3: feature 名の確定

plan のタイトル（先頭 H1）または冒頭の説明から feature 名を推定する。命名規則は kebab-case（例: `issue-driven-flow`）。

AskUserQuestion で確認する:

```
feature 名を確定してください
- {推定値}  (Recommended)
- 別の名前を入力（Other）
```

確定した feature 名は後続 Phase で `${feature}` として使用する。

---

## Phase 4: 要件定義書の作成（forge:start-requirements 呼び出し）

同 feature の既存 requirements ファイルの有無の確認と、新規か既存への追加か・差分開発かどうかの判定は、`forge:start-requirements` が行う。本 skill では事前 Glob も判定も行わない。

### 4.1 plan を context として明示

実行前に以下をユーザーに表示する（**省略不可**。後続 skill が plan を参照する根拠を明示するため）:

```
plan: {plan-path}
namespace: {namespace}
feature: {feature}
これから plan を context として要件定義書を作成します。
```

### 4.2 forge:start-requirements の起動

Skill ツールで `/forge:start-requirements` を起動する:

- skill: `forge:start-requirements`
- args: `{feature} --mode interactive`

### 4.3 interactive_workflow の Q&A 自動充填手順

Skill ツールで起動した `/forge:start-requirements` は内部で `requirements_interactive_workflow.md` を Read し、Phase 0 〜 Phase 4 まで多数の確認・対話を [MANDATORY] で実行する。これらは plan を読み込まずに対話する設計のため、本 skill 起動時には **plan を「壁打ちの内容」として扱い、plan の内容で各 Q&A を自動充填し、ユーザーには一括確認のみ求める** ように振る舞いを変更する。

#### 4.3.1 自動充填の手順

| workflow の Phase                                 | 既定の対応                                                                                                                                                                              |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Phase 0（事前確認）                               | 変更の概要を plan から抽出して提示し、確認する。**新規か既存への追加かの質問はスキップしない**（plan から推測して埋めず、ユーザーに聞く）。完全新規かどうかの判定は workflow どおり実行 |
| Phase 1（ルール・既存資産）                       | workflow の指示通りに Skill ツールで `/forge:query-db-rules` 等を実行（plan で代替不可）。既存資産の確認は、workflow が定めるとおり完全新規でないときだけ実行                           |
| Phase 2（ビジョン・価値・スコープ）               | 解決する課題 / 提供価値 / 成功の定義 / 主要機能 / スコープ外 / 制約（完全新規でないときは、関連する既存機能 / 新規要素の要否 / 影響範囲も）を **plan から抽出して充填**                 |
| Phase 3（型の判定と承認・置き場の決定・ドラフト） | workflow の指示通りに実行（型の判定と承認は省かない）。ドラフトには plan の内容を取り込む（4.3.4）                                                                                      |
| Phase 4（ドラフトを前提とした議論と仕上げ）       | 主要シナリオ / 画面・インターフェース一覧 / 各画面の表示要素・操作要件・エラーケースを **plan から抽出してドラフトに反映**（plan に記載がない項目だけユーザーに質問）                   |
| Phase 5（統合・品質確認・完了処理）               | workflow の指示通りに実行                                                                                                                                                               |

#### 4.3.2 一括確認の方法

各 Phase の充填が終わったら、ユーザーに**まとめて表示してから AskUserQuestion で確認**する:

```
## {Phase 名} の充填結果（plan より抽出）

| 項目 | 充填内容 |
|------|---------|
| ... | ... |

この内容で確定しますか?
- はい、このまま進む  (Recommended)
- 修正する（指摘箇所を入力）
```

#### 4.3.3 plan に記載がない項目の扱い

plan に該当情報がない場合のみ、workflow の元の Q&A をユーザーに提示する。「plan に記載がないため確認させてください」と前置きする。

#### 4.3.4 plan の内容はすべて取り込む

plan の内容は、詳細設計（実装の手順、既存ファイルの変更箇所、データ構造など）も含めて、すべて要件定義書（ドラフトを含む）に取り込む。workflow の Q&A に対応する項目が無い内容も落とさない。

### 4.4 完了

`/forge:start-requirements` の自己完結フロー（AI レビュー・ToC 更新・commit 確認）に従って完了まで進める。

---

## 完了処理

### 完了案内

作成されたファイルを表示し、ユーザーが次に実行するコマンド例を案内する:

```
Markdown plan から要件定義書を作成しました:
  Markdown plan: {plan-path}
  REQ:           {要件定義書パス}

次のステップ:
  /forge:start-design --requirement {要件定義書パス}    # 設計書の作成へ進む
```

---

## 制約事項

- **forge 実装計画書 `{feature}_plan.json` は対象外**: forge の JSON 計画書は `/forge:start-plan` が作成・更新する。本 skill は Markdown plan のみを入力とする
- **既存テンプレートを尊重**: 要件定義書は `${CLAUDE_PLUGIN_ROOT}/docs/requirement_format.md` に従う。本 skill は独自テンプレートを持たない
- **設計書は作らない**: 設計は `/forge:start-design` が要件定義書から行う
- **forge:start-requirements を改変しない**: 本 skill は薄いオーケストレーション層であり、start-requirements の品質保証フロー（AI レビュー・ToC 更新・commit）はそのまま流用する
