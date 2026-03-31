---
name: clean-rules
description: |
  ルール文書を分析し、重複や散在を解消して見つけやすくする。
  トリガー: "rules を整理", "重複ルールを削除", "clean rules", "ルールの掃除"
user-invocable: true
argument-hint: ""
---

# /forge:clean-rules

プロジェクトの rules/ を開発文書の分類学（Taxonomy）に基づいて分析し、
forge 内蔵知識も含めてプロジェクト内で読める形に体系的に再構築する。

## 設計原則

| 原則 | 説明 |
|------|------|
| **分類学に基づく判定** | `taxonomy.md` の 3 次元分類（Content Type / Authority Source / Scope）で体系的に分類する |
| **forge 知識の可視化** | forge 内蔵 docs はユーザーに不可視。プロジェクトの rules/ に読める形で組み込む |
| **削除より再編成** | forge カバー部分も削除しない。プロジェクト固有部分を最優先で保護する |
| **冪等** | 何度実行しても同じ分類結果に収束する。追跡マーキングは不要 |
| **1 ファイル 1 関心事** | Content Type が異なるセクションは別ファイルに分離する |

---

## フロー継続 [MANDATORY]

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ AskUserQuestion で確認する。

---

## ワークフロー

### Phase 1: 情報収集

#### Step 1: .doc_structure.yaml の存在確認 [MANDATORY]

`.doc_structure.yaml` がプロジェクトルートに存在するか確認する。

- **存在しない** → `/forge:setup-doc-structure` を起動して作成を促す。作成されなかったらエラー終了。

#### Step 2: ルール文書一覧の取得

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/scripts/resolve_doc_structure.py" --type rules
```

- `status: "ok"` → `rules` キーからファイル一覧を取得し Step 3 へ
- 0 件 → 「rules 文書が見つかりません」で正常終了
- `status: "error"` → エラー報告して終了

#### Step 3: forge 内蔵 docs の取得

`/forge:query-forge-rules` を呼び出し、タスク「プロジェクト rules との比較対象となる
forge 内蔵知識の一覧」で検索する。返されたパスリストが比較対象の forge docs。

#### Step 4: 分類学定義の読み込み [MANDATORY]

```
${CLAUDE_SKILL_DIR}/docs/taxonomy.md
```

を Read し、分類基準を把握する。以降の分析はこの分類学に厳密に従う。

#### Step 5: 全文書の読み込み

- ルール文書（ターゲットプロジェクト側）を全て Read
- forge docs（Step 3 で取得したパスリスト）を全て Read

情報収集完了後、以下を出力する:

```
### ✅ Phase 1 完了

| 項目 | 値 |
|------|-----|
| ルール文書 | N 件 |
| forge docs（比較対象） | N 件 |

**ルール文書**
- `rules/file1.md`
- `rules/file2.md`
```

---

### Phase 2: 分類・分析（AI） [MANDATORY]

`taxonomy.md` の分類学に基づき、各ルール文書の**セクション（## 見出し）単位**で以下を判定する:

| 判定項目 | 内容 |
|---------|------|
| **A. Content Type** | Constraint / Convention / Format / Process / Decision / Reference のどれか |
| **B. Authority Source** | Tool-provided（forge）/ Project-defined / External standard |
| **C. forge 対応** | Tool-provided と判定したセクションが forge のどの内蔵 docs に対応するか |
| **D. プロジェクト固有部分** | Project-defined のセクション。forge と重複する記述がないかも確認 |

分析結果を以下の形式で出力する:

```
## 📊 Phase 2: 分類・分析結果

### rules/coding_standards.md

| セクション | Content Type | Authority | forge 対応 |
|-----------|-------------|-----------|-----------|
| §1 命名規則 | Convention | Project-defined | — |
| §2 設計書フォーマット | Format | Tool-provided | design_format.md |
| §3 レビュー観点 | Constraint | Tool-provided | review_criteria_code.md |
| §4 エラーハンドリング | Convention | Project-defined | — |

**判定**: Convention + Format + Constraint が混在 → 分割推奨
```

---

### Phase 3: 再構築案の提示と承認 [MANDATORY]

分析結果に基づき、再構築案を以下の 4 カテゴリで提示する:

#### 1. forge 知識の組み込み

プロジェクトに存在しないが、forge が内蔵している有用なルール。
forge docs から抽出してプロジェクトの rules/ に読める形で配置する。

```
| 新ファイル | forge 元 docs | Content Type | 説明 |
|-----------|-------------|-------------|------|
| rules/review_criteria.md | review_criteria_code.md | Constraint | レビュー観点 |
```

#### 2. 既存ルールの再編成

混在していた関心事を Content Type / 関心事ごとに分離する。

```
| 新ファイル | 元のファイル・セクション | Content Type |
|-----------|---------------------|-------------|
| rules/naming_conventions.md | coding_standards.md §1 | Convention |
```

#### 3. 統合

プロジェクト既存ルールと forge 知識が同じ関心事をカバーしている場合、
forge の内容をベースにプロジェクト固有の追記を統合した 1 ファイルにする。

#### 4. 変更なし

プロジェクト固有で forge カバーなし。そのまま維持。

AskUserQuestion で承認を取得する:

```
再構築案を承認しますか？
- 承認（全て実行）
- 部分承認（個別に選択）
- キャンセル
```

「部分承認」の場合は各項目について個別に AskUserQuestion で確認する。

---

### Phase 4: 実行

承認に基づき以下を実行する:

- forge docs からの抽出・配置（forge 知識の組み込み）
- 既存ファイルの分割（Content Type / 関心事ごと）
- 重複部分の統合（forge ベース + プロジェクト追記）
- マーキングやメタデータコメントは付与しない

---

### Phase 5: 完了処理

#### 結果サマリー

```
## 🎉 ルール再構築完了

| 操作 | 件数 |
|------|------|
| forge 知識の組み込み | X 件 |
| 既存ルールの再編成 | X 件 |
| 統合 | X 件 |
| 変更なし | X 件 |
```

#### .doc_structure.yaml の確認

rules/ のディレクトリ構造に変更があった場合、`.doc_structure.yaml` の更新が必要か確認する。

#### DocAdvisor index の更新

`/doc-advisor:create-rules-index` Skill が利用可能であれば呼び出す。

#### commit 確認

変更が 1 件以上実行された場合、AskUserQuestion を使用して commit を確認する:

```
変更をコミットしますか？
→ はい / いいえ
```

「はい」の場合 → `/anvil:commit` を呼び出す。
