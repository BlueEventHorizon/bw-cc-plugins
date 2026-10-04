---
name: start-design
description: |
  要件定義書から設計書を作成する。要件だけで上流の設計→既存の実装・設計パターンとの照合と再設計→詳細設計→整合性の確認→レビュー→commit を一貫実行。
  トリガー: "設計書作成", "設計開始", "start design"
user-invocable: true
argument-hint: "<feature>"
allowed-tools: Bash, Read, Write, Glob, Grep, Agent, Skill, AskUserQuestion
---

# /forge:start-design

要件定義書から設計書を作成する。

## Goal

要件定義書だけを使って上流の設計を作り、既存の実装・設計パターンと照合して再設計し、詳細設計・整合性の確認・レビュー・commit・完了案内まで完走すること。

## フロー継続

Phase 完了後は立ち止まらず次の Phase に自動で進む。立ち止まるのは、設計手法が求める人の承認（Phase 2・Phase 3・Phase 6）と、不明点を AskUserQuestion で確認するときだけである。

---

## コマンド構文

```
/forge:start-design [feature]
```

| 引数    | 内容                             |
| ------- | -------------------------------- |
| feature | Feature 名（省略時は対話で確定） |

差分開発かどうかは引数で指定しない。入力の要件定義書を出発点に判定し（Phase 1.4）、設計の後に既存の仕様と突き合わせて確かめる（Phase 3）。

---

## 事前準備

### Feature の確定

対象 Feature を確定する。Feature が決まらないと、入力（どの要件定義書を設計するか）も出力先も決まらない。

**フィーチャー概念の把握**: 以下を Read し、フィーチャーとは何か・名前空間の原則を把握する。

- `${CLAUDE_PLUGIN_ROOT}/docs/additive_development_spec.md` §0 — フィーチャーの概念定義

`${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/SKILL.md` の「出力先ディレクトリの解決」手順に従い、
doc_type `design`（feature 未指定）で既存ファイルの有無を確認し、以下の3分岐で確定する:

- **引数あり** → **変更せずそのまま使用**（AI による置き換え禁止）
- **引数なし・既存ファイルが存在しない**（初回立ち上げ）→ フィーチャー名不要。同手順の対象ディレクトリに
  直接配置する（`additive_development_spec.md` §0 参照）
- **引数なし・既存ファイルが存在する** → AskUserQuestion で対象 Feature を確認する

### 出力先の解決

設計書の出力先ディレクトリを特定する。入力文書（要件定義書）は Phase 1 で agent が特定する。

`${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/SKILL.md` の「出力先ディレクトリの解決」手順に従い、
doc_type `design`、feature `{feature}` で出力先ディレクトリを求める。

エントリが無い場合の扱いは同手順が定める（本スキルは既定パスを持たず、出力先を独自に尋ねない）。

### モード判定

出力先ディレクトリの設計書ファイルを Glob で確認し、モードを決定:

| 状況               | モード                           |
| ------------------ | -------------------------------- |
| 設計書が存在しない | **新規作成モード** → Phase 1 へ  |
| 設計書が存在する   | AskUserQuestion でユーザーに確認 |

既存設計書がある場合、AskUserQuestion を使用して確認する:

- 新たな設計書ファイルを追加作成する → Phase 1 へ
- レビューのみ行う → Skill ツールで `/forge:review design --files {既存設計書パス}` を起動して終了

### プラグイン文書の読み込み

以下のプラグイン文書を**常に**読み込む:

- **`${CLAUDE_PLUGIN_ROOT}/docs/design_method.md`** — 設計の手順と成果物（Phase 2〜5 はこれに従う）
- **`${CLAUDE_PLUGIN_ROOT}/docs/design_principles_spec.md`** — 設計書の判断基準・禁止事項・重大度
- **`${CLAUDE_PLUGIN_ROOT}/docs/strategy_principles_spec.md`** — 実装戦略書の原則。既存の実装の扱いは設計ではなく実装戦略書の責務であることを把握する
- **`${CLAUDE_PLUGIN_ROOT}/docs/spec_design_boundary_spec.md`** — 要件・設計の境界ガイド
- **`${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md`** — 要件・設計で優先する価値観（構造品質の定量化禁止など）
- **`${CLAUDE_PLUGIN_ROOT}/docs/document_style_guide.md`** — 文書スタイル指針（タグ・見出し・参照記法）

---

## Phase 1: 入力の収集

以下の 2 つを **Agent ツールで並列起動** し、各 agent の **return value** を main AI コンテキストに直接保持する。各 agent は markdown bullet list で返却し、エラー時は該当カテゴリなしで後続工程に進む。

既存の実装・設計パターンは、ここでは集めない。設計は要件だけから組み立て、既存との照合は設計の後（Phase 3）に行う。

### 1.1 要件定義書の収集

```
Agent ツール起動: 要件定義書収集
prompt:
  Feature "{feature}" に関連する要件定義書を検索する。

  `/forge:query-db-specs {feature}` を呼ぶ。

  各文書のタイトル行を Read で確認し、関連性を判断する。最大 10 件。
  return value として以下の markdown 形式で返す:

  ## 仕様書 (N 件)
  - `path/to/spec.md` — 関連理由を 1 行で
```

### 1.2 プロジェクトのルールの収集

```
Agent ツール起動: 設計ルール収集
prompt:
  Feature "{feature}" の設計書作成に適用するプロジェクト固有ルール・規約を検索する。

  `/forge:query-db-rules {feature} 設計` を呼ぶ。

  return value として以下の markdown 形式で返す:

  ## 設計ルール (N 件)
  - `path/to/rule.md` — 関連理由を 1 行で
```

### 1.3 収集結果の確認

全 agent 完了後、2 つの return value をそのままユーザーに表示する。5 件以下は全件表示、6 件以上は先頭 3 件 + `... 他 N 件` で省略。

**要件定義書 return value が空 (0 件) の場合** → AskUserQuestion:

- 要件定義書のパスを手動で指定する
- 中止する（要件定義書は `/forge:start-requirements` で作成する）

本スキルは要件定義書を入力にする。要件定義書なしでは設計しない。

### 1.4 差分開発かどうかの確認

入力の要件定義書が `feature_type: temporary-feature` frontmatter を持つかを、判定の出発点にする。要件の上では既存と重ならなくても、設計してみると既存の設計書を変える・重なることがあるため、Phase 3 で設計書について確かめ直す。

- **持つ（差分開発）**: 以下を Read し、旧仕様の置き換え・merge 手順を把握したうえで後続 Phase に進む。設計書にも同じ frontmatter を付ける（2.2）
  - `${CLAUDE_PLUGIN_ROOT}/docs/additive_development_spec.md` — 追加開発ワークフロー仕様（§2「設計は要件から組み立てる」を含む）
  - `${CLAUDE_PLUGIN_ROOT}/docs/frontmatter_format.md` の §1.2 — `feature_type: temporary-feature` 定義
- **持たない**: ここでは設計書に frontmatter を付けない。Phase 3 で差分開発と分かった場合に付ける

---

## Phase 2: 上流の設計（要件だけで）

### 2.1 設計の手順

要件定義書とプロジェクトのルールだけを使い、`design_method.md` の Step 0〜4 に従って上流の設計を作る。既存の実装・設計パターンは、この Phase では見ない（`additive_development_spec.md` §2「設計は要件から組み立てる」）。詳細設計（Step 5）は、既存との照合の後の Phase 4 で行う。

設計書の章立てについてプロジェクト固有のルール（Phase 1 の設計ルール return value）があれば、それに従って成果物を並べる。

手法が求める人の承認は、次のように行う。

- **Step 1 の終わり**（シナリオ表と入力への質問）: AskUserQuestion で承認を得る。入力への質問の答えは、「要件定義書に無い設計が必要になった場合」と同じ手続き（追記内容を提示し、承認を得てから要件定義書に追記する）で要件定義書に反映し、反映してから先へ進む。質問が多く、要件定義書がまだ設計に使える状態にないときは、中止して `/forge:start-requirements` で要件定義書を補うよう案内する
- **Step 4 の終わり**（上流の設計）: AskUserQuestion で承認を得る

### 2.2 設計IDの採番と設計書ファイルの作成

Step 1 の承認後、設計書ファイルを作り、以降の成果物はこのファイルに書く。

設計 ID はプロジェクトのルールに従う（ルールがない場合は `DES-XXX` 形式を推奨）。必ず以下のスクリプトで次の連番を取得する。手動での番号決定は禁止:

```bash
SCAN_SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/next-spec-id/scripts/scan_spec_ids.py"
python3 "$SCAN_SCRIPT" DES --share-prefixes ADR,DES
```

JSON 出力の `next_id` をファイル名・設計 ID として使用する。`duplicates` が空でない場合は警告を表示する（`duplicates` には「異なるファイルが同じ ID / 共有番号を主張している」実際の衝突のみが報告される。同一履歴由来の複数ブランチ出現はノイズとして除外済みのため、空でなければ必ずユーザーに提示する）。

- **作成場所**: 事前準備「出力先の解決」で確定した出力先ディレクトリ
- **フォーマット**: Markdown (.md) ファイル
- **ファイル名**: `{設計ID}_{対象名}_design.md`（例: `DES-001_session_expiry_design.md`）。`{対象名}` は英語のスネークケースで、**その設計が扱う対象を表す名前**とする。一覧を見た人が中身を推測できること。`impl` `detail` 等の内容を示さない名前を使わない
- **差分開発の場合（1.4 で要件定義書が frontmatter を持つ、または Phase 3 で設計書が差分開発と分かった）**: `${CLAUDE_PLUGIN_ROOT}/docs/frontmatter_format.md` §1.2 が定義する `feature_type: temporary-feature` frontmatter を文書先頭（`# {設計ID} ...` 見出しより前）に付与する。feature_note は本設計書が対象範囲における現在の設計であることを述べ、対応する追加 feature 要件定義書（REQ-xxx）と食い違う場合は要件定義書に従うと添える。どちらにも当たらない場合は付与しない。

**禁止事項・よくある失敗パターン**: `design_principles_spec.md`「記載してはいけない内容」「よくある失敗パターン」節に従う（事前準備で読み込み済み）。

---

## Phase 3: 既存の実装・設計パターンとの照合と再設計

Phase 2 でできた上流の設計の観点から、既存の実装と設計パターンを読み、使えるものがあれば設計に戻って直す。

1. **探す**: 上流の設計の責務・契約・共有データを手がかりに、既存の実装と、同種の機能で確立された設計パターンを、複数のキーワード・ツール（`Grep` / `Glob` 等）で探す
2. **判断する**: 修正せずにそのまま使える実装、または採るべき設計パターンがあるかを判断する。既存の実装を修正する前提で使うものは、ここでは対象にしない（既存の実装の扱いは実装戦略書が決める）
3. **再設計する**: 採るべき設計パターンで構造が変わるなら、`design_method.md` に従って Step 2〜4 から上流の設計を直す。修正せずに使える実装は、Phase 4（詳細設計）で手段として使うために覚えておく
4. **繰り返す**: 新しく使えるものが見つからなくなるまで 1〜3 を繰り返す。完全新規の機能では、通常は何も見つからずに次へ進む

- 再設計で上流の設計（Step 2〜4 の成果物）が変わった場合は、上流の設計をもう一度 AskUserQuestion で承認にかける

### 既存の仕様との重なりの確認

照合が終わったら、設計が触れる範囲の既存の要件定義書・設計書を `/forge:query-db-specs` で探し、新しい設計と突き合わせる。

- **新しい設計が、既存の設計書の記述を変える、または既存の設計書の範囲と重なる**: 設計書を差分開発として扱う。1.4 の差分開発の規範文書を読み、設計書に一時 frontmatter を付ける（2.2）。要件定義書には付けない
- **既存の要件定義書の内容まで変える必要がある**: 要件の問題であるため、設計を止めて要件定義に戻す（「要件定義書に無い設計が必要になった場合」と同じ扱い）
- **どちらにも当たらない**: そのまま Phase 4 へ進む

---

## Phase 4: 詳細設計

`design_method.md` の Step 5 に従い、上流の設計を実装できる厳密さまで詰める。

- Phase 3 で覚えておいた、修正せずに使える既存の実装を手段として使い、そのパスを設計書に書く。使えるのに使わない場合は、その理由を書く
- 詳細化の中で、新しく探すべき既存（手段の候補・設計パターン）が出たら、Phase 3 に戻る

---

## Phase 5: 整合性の確認

`design_method.md` の Step 6 に従い、追跡表を作り、チェック項目を全て満たすまで設計を直す。Step 6 が求める「別のエージェントによる確認」と「人の承認」は Phase 6 が担う。

---

## Phase 6: AI レビューとユーザーレビュー

### 6.1 自分でのレビュー

`/forge:review` の前に、作成・変更した設計書（作成した ADR を含む）を最初から最後まで自分で読み、誤りが無いかを確かめる。見出しや変更した箇所だけで済ませない。要件定義書と照らして、誤り・矛盾・抜け・用語の揺れを見つけたら直す。直し終えてから 6.2 へ進む。

### 6.2 AI レビューとユーザーレビュー

作成した設計書に対して Skill ツールで `/forge:review` を `--auto` モードで実行する:

```
# Skill ツールで起動する
/forge:review design --files {作成ファイルパス} --auto
```

対象はこのワークフローで作成・変更したファイル（差分）のみ。

AI レビュー完了後、AskUserQuestion を使用して設計書のユーザーレビュー（設計全体の承認）を実施する。AI レビューで品質問題を修正してからユーザー確認を行う方が効率的なため、この順で行う。

---

## 要件定義書に無い設計が必要になった場合（全 Phase 共通）

設計中に要件定義書に無い必要が判明したら、**設計を止めて、すべてユーザーに報告する**。報告するのは、何が必要になったかと、それがどこから生じたかである。要件へ戻すか設計書に書くかを AI が判定しない。要件定義書にも設計書にも、AI が独断で書かない。

その後はユーザーの判断に従う。

- **要件定義書へ追記する場合**: 追記内容をユーザーに提示し、**承認を得てから**追記する。追加開発なら `${CLAUDE_PLUGIN_ROOT}/docs/additive_development_spec.md` §1 の判定を行い、差分 feature に該当するなら差分側の要件定義書へ書く
- **設計書に書く場合**: 設計書に書き、**承認を ADR に記録して設計書の当該節からリンクする**

記録の無い承認は承認として扱われない（`${CLAUDE_PLUGIN_ROOT}/docs/spec_design_boundary_spec.md` §6）。

ADR の作成は、Skill ツールで `/forge:write-adr approval-record {feature} --defer-finish` を起動して依頼する。渡す内容は、決定の内容、要件へ戻さず設計書に書く理由、ユーザーの承認の発言（そのまま）である。ADR の書式・採番・記載先は ADR ライターが担うため、本スキルは扱わない。作成された ADR ファイルのパス（出力先の ADR ファイル）を、設計書の当該節からリンクする。ADR ファイルは Phase 6 のレビュー対象に含める。

---

## 完了処理

### specs ToC 更新

設計書の作成・更新後、`/forge:update-db-specs` が利用可能であれば実行すること（利用不可の場合はスキップ）。

### commit/push 確認

commit/push の確認フローを担うスキル（例: `anvil:commit`）が available-skills にあれば呼び出す。無ければ `git add` → `git commit` の手順を案内する。

### 完了案内

作成したファイルパスとともに次のステップを案内する:

```
設計書を作成しました:
  → {作成ファイルパス}

次のステップ:
  /forge:start-plan {feature}    # 計画書作成へ進む
```
