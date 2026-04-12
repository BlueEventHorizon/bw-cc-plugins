---
name: clean-rules
description: |
  ルール文書を分析し、forge 内蔵 docs との重複を検出・削除し、taxonomy に基づいて再構築する。
  トリガー: "rules を整理", "重複ルールを削除", "clean rules", "ルールの掃除"
user-invocable: true
argument-hint: "[--delete] [--rebuild]"
---

# /forge:clean-rules

プロジェクトの rules/ を開発文書の分類学（Taxonomy）に基づいて分析する。
forge 内蔵 docs との重複を Embedding 類似度で検出し、モードに応じて削除・再構築を実行する。

## コマンド構文

```
/forge:clean-rules [--delete] [--rebuild]

--delete   forge 内蔵 docs と重複するセクションを削除（forge 優先）
--rebuild  taxonomy に基づきファイルの分割・統合を実行
省略時     分析レポートのみ出力（ドライラン）
```

### 使用例

```bash
/forge:clean-rules                     # 何を削除/再構築すべきか分析
/forge:clean-rules --delete            # forge 重複を削除
/forge:clean-rules --rebuild           # taxonomy に基づく再構築
/forge:clean-rules --delete --rebuild  # 削除してから再構築
```

---

## 設計原則

| 原則 | 説明 |
|------|------|
| **forge 優先** | forge 内蔵 docs でカバーされる内容はプロジェクト rules/ から削除する。二重管理しない |
| **Project-defined を保護** | プロジェクト固有の取り決めは絶対に削除しない |
| **安全性** | 破壊的操作の前に `git stash` で退避。ロールバック可能 |
| **段階的実行** | デフォルトは分析のみ。`--delete` / `--rebuild` で明示的に操作を指定 |
| **分割は控えめに** | Content Type 3 種以上混在 AND 100 行超の場合のみ分割推奨 |

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

#### Step 3: forge 内蔵 docs のパス取得

`${CLAUDE_PLUGIN_ROOT}/toc/rules/rules_toc.yaml` を Read し、`docs:` セクションの全キー（ファイルパス）を取得する。

パスは `plugins/forge/...` 形式。Read 時は `${CLAUDE_PLUGIN_ROOT}` 起点で解決する
（例: `plugins/forge/docs/design_format.md` → `${CLAUDE_PLUGIN_ROOT}/docs/design_format.md`）。

#### Step 4: Embedding ベースの重複検出

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/detect_forge_overlap.py" \
  --project-rules {Step 2 のファイル一覧} \
  --forge-docs {Step 3 のファイル一覧（絶対パスに解決済み）} \
  --threshold 0.5
```

- `status: "ok"` → `overlaps` リストを Phase 2 に渡す
- `status: "error"` → エラー内容を報告。`OPENAI_API_KEY` 未設定の場合はユーザーに設定を案内

#### Step 5: 分類学定義の読み込み [MANDATORY]

```
${CLAUDE_SKILL_DIR}/docs/taxonomy.md
```

を Read し、分類基準を把握する。以降の分析はこの分類学に厳密に従う。

#### Step 6: 全文書の読み込み

- ルール文書（プロジェクト側）を全て Read
- forge docs（Step 3 で取得したパスのうち、Step 4 の `overlaps` に登場するもの）を Read

情報収集完了後、以下を出力する:

```
### ✅ Phase 1 完了

| 項目 | 値 |
|------|-----|
| ルール文書 | N 件 |
| forge docs（比較対象） | N 件 |
| Embedding 重複候補 | N 件 |

**ルール文書**
- `rules/file1.md`
- `rules/file2.md`
```

---

### Phase 2: 分類・分析（AI） [MANDATORY]

`taxonomy.md` の分類学と `detect_forge_overlap.py` の重複スコアに基づき、
各ルール文書の**セクション（## 見出し）単位**で以下を判定する:

| 判定項目 | 内容 |
|---------|------|
| **A. Content Type** | Constraint / Convention / Format / Process / Decision / Reference のどれか |
| **B. Authority Source** | Tool-provided（forge）/ Project-defined / External standard |
| **C. forge 対応** | Tool-provided と判定したセクションが forge のどの内蔵 docs に対応するか（Embedding スコアを参照） |
| **D. モード別推奨** | `--delete` で削除すべきか / `--rebuild` で分割・統合すべきか |

分析結果を以下の形式で出力する:

```
## 📊 Phase 2: 分類・分析結果

### rules/coding_standards.md

| セクション | Content Type | Authority | forge 対応 | --delete | --rebuild |
|-----------|-------------|-----------|-----------|----------|-----------|
| §1 命名規則 | Convention | Project-defined | — | keep | keep |
| §2 設計書フォーマット | Format | Tool-provided | design_format.md (0.82) | delete | n/a |
| §3 レビュー観点 | Constraint | Tool-provided | review_criteria_code.md (0.75) | delete | n/a |
| §4 エラーハンドリング | Convention | Project-defined | — | keep | keep |

**判定**: §2, §3 は forge でカバー済み → --delete で除去可能
```

#### デフォルトモード（引数なし）の場合

ここで終了し、分析レポートを出力する:

```
## 📋 分析レポート（ドライラン）

### --delete で削除される見込み
| ファイル | セクション | forge 対応 | 類似度 |
|---------|-----------|-----------|--------|
| rules/coding_standards.md | §2 設計書フォーマット | design_format.md | 0.82 |

### --rebuild で再構築される見込み
| ファイル | 推奨操作 | 理由 |
|---------|---------|------|
| rules/large_mixed.md | 分割 | Convention + Process + Constraint が混在、150 行 |

→ 実行するには `--delete` または `--rebuild` を指定してください
```

`--delete` または `--rebuild` が指定されている場合 → Phase 3 へ。

---

### Phase 3: 安全確保 [MANDATORY]

#### Step 1: git stash で退避

```bash
git stash push -m "clean-rules: before changes"
```

stash 成功を確認する。失敗した場合はユーザーに報告し続行の可否を確認する。

#### Step 2: 変更計画の承認

AskUserQuestion でカテゴリ単位で承認を取得する。

`--delete` が指定されている場合:

```
forge 重複の削除対象（N セクション / M ファイル）:
- rules/coding_standards.md §2 → forge design_format.md でカバー
- rules/coding_standards.md §3 → forge review_criteria_code.md でカバー
- ...

削除を実行しますか？
→ はい / いいえ
```

`--rebuild` が指定されている場合:

```
再構築対象（N 操作）:
- rules/large_mixed.md → 3ファイルに分割
- rules/naming_a.md + rules/naming_b.md → 1ファイルに統合

再構築を実行しますか？
→ はい / いいえ
```

「いいえ」の場合 → `git stash pop` で復元し、終了。

---

### Phase 4-D: 削除実行（--delete）

Phase 2 の分析結果に基づき、Tool-provided と判定されたセクションを削除する。

#### 削除ロジック

- **ファイル全セクションが削除対象** → ファイルを削除
- **一部セクションのみ削除対象** → 該当セクション（`##` 見出しから次の `##` 見出しの直前まで）を除去し、残りを保存

#### 相互参照の検出と更新 [MANDATORY]

削除したファイル/セクションを参照している他文書を検索する:

1. 削除したファイル名で `grep -r` を実行（rules/ および docs/ 配下）
2. markdown リンク `[text](deleted_file.md)` や `deleted_file.md` への言及を検出
3. 検出された参照を除去または更新

---

### Phase 4-R: 再構築実行（--rebuild）

Phase 2 の分析結果に基づき、taxonomy の原則に従ってファイルを再構築する。

#### 分割

以下の**両方**を満たすファイルのみ分割する:

- Content Type が 3 種以上混在している
- ファイルが 100 行を超えている

分割時は Content Type ごとに新しいファイルを作成する。ファイル名は
元ファイル名 + Content Type サフィックスとする（例: `coding_standards_conventions.md`）。

#### 統合

同一 Content Type + 同一関心事の小ファイル群（それぞれ 30 行未満）がある場合、
1 ファイルにまとめる。

#### markdown 構文チェック

各操作後に以下を確認する:

- `#` / `##` / `###` の見出し階層が崩れていないか
- 孤立したリスト項目やコードブロックの閉じ忘れがないか

---

### Phase 5: 完了処理

#### 結果サマリー

```
## 🎉 clean-rules 完了

| 操作 | 件数 |
|------|------|
| forge 重複の削除 | X セクション（Y ファイル） |
| ファイル分割 | X 件 |
| ファイル統合 | X 件 |
| 相互参照の更新 | X 箇所 |
| 変更なし | X ファイル |
```

#### .doc_structure.yaml の更新

rules/ のディレクトリ構造に変更があった場合、`.doc_structure.yaml` の `root_dirs` を確認し、
必要に応じて更新する。

#### DocAdvisor ToC の更新

`/doc-advisor:create-rules-toc` Skill が利用可能であれば呼び出す。

#### commit 確認

変更が 1 件以上実行された場合、AskUserQuestion を使用して commit を確認する:

```
変更をコミットしますか？
→ はい / いいえ
```

「はい」の場合 → `/anvil:commit` を呼び出す。

#### ロールバック手段の提示

```
💡 問題があれば `git stash pop` で変更前の状態に戻せます。
```
