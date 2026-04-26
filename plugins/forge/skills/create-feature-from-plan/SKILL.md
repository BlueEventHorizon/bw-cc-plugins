---
name: create-feature-from-plan
description: |
  Claude Code の plan mode が保存する plan ファイル (`~/.claude/plans/*.md`) を入口に、要件定義書 → 設計書を一気通貫で作成する。
  forge:start-requirements → forge:start-design を順次起動し、plan を context として注入する。plan の YAML 構造（forge の plan.yaml）は対象外。
  トリガー: "plan から feature 作成", "plan から要件作成", "create feature from plan"
user-invocable: true
argument-hint: "[plan-file-path]"
allowed-tools: Bash, Read, Skill, AskUserQuestion, Glob
---

# /forge:create-feature-from-plan

Claude Code の plan mode で生成された plan markdown を入口に、要件定義書と設計書を一気通貫で作成する薄いオーケストレーション skill。

- 入力: plan markdown（`~/.claude/plans/*.md` 形式を想定。任意のパスも可）
- 出力: 要件定義書 + 設計書（`forge:start-requirements` / `forge:start-design` の出力）
- 対象外: forge の `plan.yaml`（YAML 構造の計画書）— こちらは `/forge:start-plan` を使うこと

## フロー継続 [MANDATORY]

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ AskUserQuestion で確認する。

---

## コマンド構文

```
/forge:create-feature-from-plan [plan-file-path]
```

| 引数           | 内容                                                                           |
| -------------- | ------------------------------------------------------------------------------ |
| plan-file-path | plan markdown のパス（省略時は `~/.claude/plans/` から直近を提示して確認する） |

---

## Phase 1: plan ファイルの特定 [MANDATORY]

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

## Phase 2: 対象 plugin（namespace）の確認 [MANDATORY]

`docs/specs/` 配下の名前空間（プラグイン名 / `common`）から、要件定義書の格納先を決める。

### 2.1 候補の列挙

```bash
ls -1 docs/specs/ 2>/dev/null
```

### 2.2 plan からの推定

plan の内容（タイトル・本文の語彙）から最有力候補を 1 つ推定する。例: plan に「GitHub Issue」「PR 作成」が頻出 → `anvil`、「ドキュメント検索」「ToC」 → `doc-advisor`。

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

## Phase 3: feature 名の確定 [MANDATORY]

plan のタイトル（先頭 H1）または冒頭の説明から feature 名を推定する。命名規則は kebab-case（例: `issue-driven-flow`）。

AskUserQuestion で確認する:

```
feature 名を確定してください
- {推定値}  (Recommended)
- 別の名前を入力（Other）
```

確定した feature 名は後続 Phase で `${feature}` として使用する。

---

## Phase 4: `--new` / `--add` モードの判定 [MANDATORY]

`forge:start-requirements` の `--new` / `--add` は **アプリ単位の判定** であり、ファイル衝突チェックではない:

- `--new`: 新規アプリ全体をゼロから立ち上げる（APP-001 から作成）
- `--add`: 既存アプリへの機能追加（`type: temporary-feature-requirement` frontmatter を付与する分岐に入る）

> **重要**: `--add` を指定しないと `${CLAUDE_PLUGIN_ROOT}/docs/requirement_format.md` の追加 feature frontmatter が付与されない。plan 由来 feature の大半は既存 plugin への追加であり、デフォルトは `--add` とする。

### 4.1 自動判定

| 条件                                                                                                | モード  |
| --------------------------------------------------------------------------------------------------- | ------- |
| Phase 2 で確定した namespace が `docs/specs/` 配下に既存（anvil/forge/doc-advisor/xcode/common 等） | `--add` |
| Phase 2 で「Other」入力された新規 namespace、または `docs/specs/{namespace}/` が不在                | `--new` |

### 4.2 ユーザー確認

自動判定結果を AskUserQuestion で確認する（推定値を先頭に "(Recommended)"）:

```
モードを確定してください
- {自動判定結果}  (Recommended)
- もう一方のモード
```

### 4.3 ファイル衝突チェックは委譲

同 feature の既存 requirements ファイル有無のチェックは **`forge:start-requirements` 内部に委譲する**（`.doc_structure.yaml` 解決と一貫性を保つため）。本 skill では事前 Glob を行わない。

---

## Phase 5: 要件定義書の作成（forge:start-requirements 呼び出し）[MANDATORY]

### 5.1 plan を context として明示

実行前に以下をユーザーに表示する（**省略不可**。後続 skill が plan を参照する根拠を明示するため）:

```
plan: {plan-path}
namespace: {namespace}
feature: {feature}
mode: {Phase 4 で確定した --new または --add}
これから plan を context として要件定義書を作成します。
```

### 5.2 forge:start-requirements の起動

Skill ツールで `/forge:start-requirements` を起動する:

- skill: `forge:start-requirements`
- args: `{feature} --mode interactive {--new または --add}`（Phase 4 の確定値を使用）

### 5.3 interactive_workflow の Q&A 自動充填手順 [MANDATORY]

`/forge:start-requirements` は内部で `requirements_interactive_workflow.md` を Read し、Phase 0.1 〜 Phase 4 まで多数の Q&A を [MANDATORY] で実行する。これらは plan を読み込まずに対話する設計のため、本 skill 起動時には **plan の内容で各 Q&A を自動充填し、ユーザーには一括確認のみ求める** ように振る舞いを変更する。

#### 5.3.1 自動充填の手順

| workflow の Phase           | 既定の対応                                                                                                        |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Phase 0.1（新規/追加判定）  | **スキップ** — Phase 4 で確定した `--new`/`--add` を引数で渡しているため再質問不要                                |
| Phase 0.2（新規アプリ Q&A） | `--new` のときのみ実行。アプリ概要 / 対象ユーザー / 必須機能 / スコープ外 / 制約 を **plan から抽出して充填**     |
| Phase 0.3（機能追加 Q&A）   | `--add` のときのみ実行。追加機能の概要 / 関連既存機能 / 新規要素の要否 / 影響範囲 を **plan から抽出して充填**    |
| Phase 0.5（ルール文書）     | workflow の指示通りに `/doc-advisor:query-rules` 等を実行（plan で代替不可）                                      |
| Phase 1（ビジョン・価値）   | 解決する課題 / 提供価値 / 成功の定義 / 主要機能 を **plan から抽出して充填**                                      |
| Phase 2（体験フロー・構成） | 主要シナリオ / 画面・インターフェース一覧 を **plan から抽出して充填**（plan に記載がない場合のみユーザーに質問） |
| Phase 3（詳細仕様）         | 各画面の表示要素 / 操作要件 / エラーケース を **plan から抽出して充填**                                           |
| Phase 4（統合・品質確認）   | workflow の指示通りに実行                                                                                         |

#### 5.3.2 一括確認の方法

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

#### 5.3.3 plan に記載がない項目の扱い

plan に該当情報がない場合のみ、workflow の元の Q&A をユーザーに提示する。「plan に記載がないため確認させてください」と前置きする。

### 5.4 完了

`/forge:start-requirements` の自己完結フロー（AI レビュー・ToC 更新・commit 確認）に従って完了まで進める。完了後は **必ず** Phase 6 に進み、その合図として以下を出力する:

```
### ✅ 要件定義書フェーズ完了 → Phase 6（設計書作成）へ進みます
```

---

## Phase 6: 設計書の作成（forge:start-design 呼び出し）[MANDATORY]

### 6.1 引き継ぎ表示

要件定義書作成完了後、以下を表示してから設計書フェーズへ進む:

```
要件定義書: {作成された REQ ファイルパス}
plan: {plan-path}
これから plan + 要件定義書を context として設計書を作成します。
```

### 6.2 forge:start-design の起動

Skill ツールで `/forge:start-design` を起動する:

- skill: `forge:start-design`
- args: `{feature}`

`/forge:start-design` の自己完結フロー（コンテキスト収集・AI レビュー・commit 確認）に従って完了まで進める。設計書の各設計判断は **要件定義書を一次情報、plan を補足情報** として位置づける（plan の内容と要件が矛盾する場合は要件定義書を優先）。

---

## 完了処理

### 完了案内

作成されたファイルを表示し、次のステップを案内する:

```
plan から feature を作成しました:
  plan:  {plan-path}
  REQ:   {要件定義書パス}
  DES:   {設計書パス}

次のステップ:
  /forge:start-plan {feature}    # 計画書（plan.yaml）作成へ進む
```

---

## 制約事項

- **plan.yaml は対象外**: forge の YAML 計画書は `/forge:start-plan` で扱う。本 skill は markdown plan のみを入力とする
- **既存テンプレートを尊重**: 要件定義書は `${CLAUDE_PLUGIN_ROOT}/docs/requirement_format.md`、設計書は `${CLAUDE_PLUGIN_ROOT}/docs/design_format.md` をそのまま使用する。本 skill は独自テンプレートを持たない
- **forge:start-requirements / forge:start-design を改変しない**: 本 skill は薄いオーケストレーション層であり、各 skill の品質保証フロー（AI レビュー・ToC 更新・commit）はそのまま流用する
