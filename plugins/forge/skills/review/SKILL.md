---
name: review
description: |
  コード・文書を🔴🟡🟢重大度付きでレビューし、修正提案を提示する。
  --auto でレビュー+修正を N サイクル自動実行。5種別（code/requirement/design/plan/generic）に対応。
  トリガー: "レビュー", "review", "レビューして", "確認して"
user-invocable: true
---

# /forge:review Skill

レビューパイプラインのオーケストレーター。
実際のレビュー・吟味・修正は専用の AI 専用スキルに委譲する。

## コマンド構文

```
/forge:review <種別> [対象] [--エンジン] [--auto [N]] [--auto-critical]

種別: requirement | design | code | plan | generic
対象: ファイルパス(複数可) | Feature名 | ディレクトリ | 省略(=対話で決定)
エンジン: --codex(デフォルト) | --claude
モード: --auto [N]（レビュー+修正を N サイクル実行。省略時 N=1）
        --auto-critical（🔴致命的のみを自動修正）
        省略時: 対話モード（人間が判定者）
```

### 使用例

```bash
/forge:review code src/                        # 対話モード
/forge:review code src/ --auto                 # 自動修正 1サイクル
/forge:review code src/ --auto 3               # 自動修正 3サイクル
/forge:review code src/ --auto-critical        # 🔴致命的のみ自動修正
/forge:review requirement login                # Feature 名で要件定義書
/forge:review design specs/login/design/login_design.md
/forge:review code src/ --claude               # Claude エンジンを使用
/forge:review generic README.md                # 任意の文書
```

---

## ワークフロー

### Phase 1: 引数解析

`$ARGUMENTS` を解析:

- 最初の単語 → 種別（`requirement` | `design` | `code` | `plan` | `generic`）
- `--codex` または `--claude` → エンジン指定
- `--auto` 単独 → `auto_count = 1`
- `--auto N`（N は整数）→ `auto_count = N`
- `--auto-critical` → `auto_count = 1`、修正対象を 🔴致命的のみに限定
- 残り → 対象（ファイルパス(複数可) / Feature名 / ディレクトリ）

解析完了後、以下を出力する:

```
### ✅ 引数解析完了

| 項目 | 値 |
|------|-----|
| 種別 | `{種別}` |
| エンジン | `{codex / claude}` |
| モード | `{対話モード}` または `--auto {N}（{N}サイクル自動修正）` |

**対象**
- `{対象パス or Feature名}`
```

### Phase 2: target_files 解決 + 参考文書収集

#### Step 1: .doc_structure.yaml の存在確認 [MANDATORY]

`.doc_structure.yaml` がプロジェクトルートに存在するか確認する。

- **存在しない** → `/forge:setup-doc-structure` を起動して作成を促す
  - 作成されなかった → エラー終了

#### Step 2: target_files の解決

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/resolve_review_context.py [対象1] [対象2] ...
```

- `status: "resolved"` → `target_files` を確定し Step 3 へ
- `status: "needs_input"` → `questions` を AskUserQuestion を使用して確認し、回答を得てから再実行
- `status: "error"` → `/forge:setup-doc-structure` を起動し `.doc_structure.yaml` の作成を促す

解決完了後、以下を出力する（6件以上は先頭3件 + `... 他N件`）:

```
**target_files (N件)**
- `path/to/file1`
- `path/to/file2`
```

#### Step 3: 関連コード探索 [MANDATORY]

レビュー・修正の参考にするため、target_files に関連する既存実装を探索する。
general-purpose subagent を起動して探索を委譲する。

> **Note**: 将来的には `/code-advisor` Skill に置き換え予定。現状は subagent が探索を担う。

```
subagent_type: general-purpose
prompt: |
  以下のファイルに関連する既存コード・実装例を探してください。

  ## 対象ファイル
  {target_files のパス一覧}

  ## 探索内容
  - 対象ファイルと同一ディレクトリのファイル
  - 対象ファイルを import / 参照しているファイル
  - 対象ファイルと類似した命名・構造を持つファイル（同種機能の別実装例）
  - 対象ファイルのテストファイル

  ## 指示
  - ファイルを Read して内容を確認し、実際に関連する実装であることを確認すること
  - 見つかったファイルのパスを一覧で返すこと
  - 関連性の理由を各ファイルについて 1 行で説明すること
  - 上限 10 ファイル程度

  ## 出力形式
  ### 関連コード一覧
  - {path}: {関連性の理由}
```

subagent が返した `related_code`（パスと関連性の説明）を以降の全 agent に渡す。

探索完了後、以下を出力する（6件以上は先頭3件 + `... 他N件`）:

```
**related_code (N件)**
- `path/to/related.swift` — 関連性の説明
```

#### Step 4: レビュー観点の探索 [MANDATORY]

以下の優先順で検索し、最初に見つかったものを `{review_criteria_path}` として確定する:

1. **`/query-rules` Skill**（DocAdvisor）に「レビュー観点の文書」を問い合わせ
   - 利用可否: `.claude/skills/query-rules/SKILL.md` の存在で判断
2. **`.claude/review-config.yaml`** に保存済みのパスがあれば使用
3. **`${CLAUDE_PLUGIN_ROOT}/docs/review_criteria_spec.md`**（プラグインデフォルト）

#### Step 5: 参考文書収集 [MANDATORY]

##### generic 種別の場合

`/query-rules` / `/query-specs` は**使用しない**。参考文書は最小限:

- `{review_criteria_path}` の「5. 汎用文書レビュー観点」

##### generic 以外の種別

DocAdvisor（`.claude/skills/query-rules/SKILL.md`）が利用可能な場合:

- `/query-rules` Skill → レビュー種別に関連するルール文書を特定
- `/query-specs` Skill → 関連する要件定義書・設計書を特定
- `{review_criteria_path}` の該当セクション参照

DocAdvisor が利用不可の場合 → 「.doc_structure.yaml からの参考文書収集手順」参照

収集完了後、以下を出力する（6件以上は先頭3件 + `... 他N件`）:

```
**reference_docs (N件)**
- `rules/coding.md`
- `specs/design.md`
```

#### Step 6: エンジン確認

- `--claude` 指定 → Claude を使用
- `--codex` 指定または省略 → `which codex` を実行
  - 存在する → Codex を使用
  - 存在しない → Claude にフォールバック、「Codex が見つからないため Claude で実行します」と通知

---

## セッション管理 [MANDATORY]

### 残存セッション検出

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py find --skill review
```

- `status: "none"` → セッション作成へ
- `status: "found"` → AskUserQuestion:「前回の未完了セッションがあります。再開しますか？」
  - **再開する** → 既存 `session_dir` を使用。refs.yaml / review.md / plan.yaml が存在すれば Phase 3（または Phase 4）から続行
  - **破棄する** → `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py cleanup {sessions[0].path}` で削除後、新規作成へ

### セッション作成

収集した情報を session_dir に保存する。

1. セッションディレクトリを作成:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py init \
     --skill review \
     --review-type "{種別}" \
     --engine "{エンジン}" \
     --auto-count {auto_count} \
     --current-cycle 0
   ```
   JSON 出力の `session_dir` をコンテキストに保持する。

2. `{session_dir}/refs.yaml` を Write する
   （フォーマット: `${CLAUDE_PLUGIN_ROOT}/docs/session_format.md` の「refs.yaml」参照）

作成完了後、以下を出力する:

```
**session_dir**
- `.claude/.temp/{session_dir_name}`
```

---

### Phase 3: reviewer を呼び出す

呼び出し前に以下を出力する:

```
## 🔄 Phase 3: レビュー実行

| 項目 | 値 |
|------|-----|
| 種別 | `{種別}` |
| エンジン | `{エンジン}` |
| review_criteria | `{review_criteria_path}` |

{target_files / reference_docs / related_code を上記フォーマットで列挙}

→ reviewer を起動してレビューを実行します
```

`/forge:reviewer` を呼び出し、以下を渡す:

- session_dir
- 種別
- エンジン

（target_files / reference_docs / related_code / review_criteria_path は reviewer が refs.yaml から読む）

`/forge:reviewer` が返すもの:

- レビュー結果（🔴🟡🟢 指摘事項リスト）

保存完了後、以下を出力する:

```
### ✅ Phase 3 完了（レビュー結果）

| 重大度 | 件数 |
|--------|------|
| 🔴 致命的 | X件 |
| 🟡 品質問題 | X件 |
| 🟢 改善提案 | X件 |

→ `{session_dir}/review.md` と `{session_dir}/plan.yaml` に保存しました
```

#### show-report の呼び出し

Phase 3 完了後、`/forge:show-report {session_dir}` を呼び出して HTML レポートを初期生成しブラウザに表示する。

### Phase 4: モードによる分岐

#### 対話モード（--auto なし）

##### Step 1: evaluator を呼び出す（AI推奨判定）

`/forge:evaluator` を呼び出し、以下を渡す:

- session_dir
- レビュー種別
- 修正対象フラグ: `--interactive`（全件 AI が推奨判定を行い evaluation.yaml に記録し、plan.yaml を推奨に基づき更新する）

evaluator 完了後、以下を出力する:

```
### Phase 4: AI推奨判定完了

| 推奨 | 件数 |
|------|------|
| 修正推奨 | X件 |
| 却下推奨 | X件 |
| 要確認 | X件 |
```

##### Step 2: present-findings を呼び出す

`/forge:present-findings {session_dir}` を呼び出す。
present-findings が plan.yaml / evaluation.yaml を読み、人間の判定を仲介する。

全件完了後 → Phase 5 へ。

#### 自動修正モード（--auto N）

`cycle = 0` から開始し、`cycle < auto_count` の間繰り返す。各サイクルの開始時に以下を出力する:

```
## 🔄 Phase 4: 自動修正 Cycle {N+1}/{auto_count}
```

##### Step 1: evaluator を呼び出す

`/forge:evaluator` を呼び出し、以下を渡す:

- session_dir
- レビュー種別
- 修正対象フラグ（`--auto`: 🔴+🟡 / `--auto-critical`: 🔴のみ）

evaluator が返すもの:

- 吟味結果（修正する / スキップ / 要確認 リスト）
- `should_continue`: 継続判定

evaluator 完了後、以下を出力する:

```
### Cycle {N} — 吟味結果

| 判定 | 件数 |
|------|------|
| 修正する | X件 |
| スキップ | X件 |
| 要確認 | X件 |
```

`should_continue: false`（修正対象0件）→ `break`

##### Step 2: fixer を呼び出す

`/forge:fixer --batch` を呼び出し、以下を渡す:

- session_dir
- レビュー種別
- モード: `--batch`

fixer 完了後、以下を出力する（ファイル6件以上は先頭3件 + `... 他N件`）:

```
### Cycle {N} — 修正完了

| ファイル | 修正内容 |
|----------|---------|
| `src/foo.swift` | {修正内容 1行} |
```

##### Step 3: 単独修正レビュー [MANDATORY]

fixer が修正した変更差分のみを対象に `/forge:reviewer` を呼び出す:

- session_dir
- 種別
- エンジン
- `--diff-only {fixer が修正したファイル一覧}`（target_files 全体の再レビューではない）

修正起因の問題が見つかった場合:

1. fixer を再度呼び出して修正起因の問題を修正
2. 再度単独修正レビューを実施
3. 問題がなくなるまで繰り返す（上限: 3回）

単独修正レビュー完了後、以下を出力する:

```
### Cycle {N} — 単独修正レビュー

| 結果 | 内容 |
|------|------|
| 修正起因の問題 | X件（修正済み: Y件） |
```

##### Step 4: 次サイクル判定

未修正の指摘が残っている AND サイクル上限に達していない → `cycle += 1` して以下を実行:

1. `/forge:reviewer` を呼び出して target_files 全体を再レビュー（review.md / plan.yaml を更新）
2. Step 1（evaluator）へ戻る

それ以外 → Phase 5 へ。

---

### Phase 5: 完了処理

#### テスト実行

修正が1件以上実行された場合、テストが存在するか確認して実行する:

1. プロジェクトルートに `tests/` ディレクトリまたはテストファイルが存在するか確認
2. 存在する場合 → テストを実行し、結果を報告する
3. テストが失敗した場合 → 失敗内容をユーザーに報告し、対応を確認する

#### 設計書の更新

修正によって設計・アーキテクチャに変更が生じた場合、該当する設計書を更新する:

1. 修正内容が設計書に記載された仕様・フローと乖離していないか確認する
2. 乖離がある場合 → 設計書（`docs/specs/design/` 配下等）を更新する
3. 設計書を更新した場合 → `/create-specs-toc` が利用可能であれば ToC も更新する

#### サマリー報告

```
## 🎉 レビュー完了（{N}サイクル実施）

### 結果サマリー

| 指標 | 値 |
|------|----|
| 🔴 致命的（修正済み） | X/Y件 |
| 🟡 品質問題（修正済み）| X/Y件 |
| 🟢 改善提案 | X件 |
| スキップ | X件（false positive / 設計意図等）|
| 要確認 | X件（手動対応が必要）|
```

#### ToC 更新

`/create-specs-toc` Skill が利用可能か確認する（`.claude/skills/create-specs-toc/SKILL.md` の存在）。
利用可能な場合は呼び出す。利用不可の場合はスキップ。

#### commit 確認

修正が1件以上実行された場合、AskUserQuestion を使用して commit を確認する:

```
変更をコミットしますか？
→ はい / いいえ
```

「はい」の場合 → `/anvil:commit` を呼び出す。

#### push 確認

commit が完了した場合、AskUserQuestion を使用して push を確認する:

```
リモートにプッシュしますか？
→ はい / いいえ
```

「はい」の場合 → `git push` を実行する。

#### セッションディレクトリの削除

`{session_dir}` を削除する:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py cleanup {session_dir}
```

削除完了後、以下を出力する:

```
セッションディレクトリを削除しました: {session_dir}
```

---

## Progress Reporting 規約

各 Phase / Step の開始・終了時に進捗をユーザーに報告する。

### ファイルリストの省略ルール [MANDATORY]

- 5件以下 → 全件表示
- 6件以上 → 先頭3件を表示し、残りは `... 他 N件` で省略

### フォーマット: スカラー値はテーブル、ファイルリストは箇条書き [MANDATORY]

スカラー値（種別・エンジン等）はテーブルで、ファイルパスは箇条書きで表示する（長いパスがテーブルを崩壊させるため）。

```
| 項目 | 値 |
|------|-----|
| 種別 | `code` |
| エンジン | `claude` |

**target_files (N件)**
- `path/to/file1.swift`
- `path/to/file2.swift`
- ... 他 N件
```

---

## .doc_structure.yaml からの参考文書収集手順

DocAdvisor 利用不可時、`doc-structure` スキルのスクリプトを呼び出して参考文書を収集する。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/scripts/resolve_doc_structure.py" --type rules
python3 "${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/scripts/resolve_doc_structure.py" --type specs
```

JSON 出力の `rules` キーからルール文書パス一覧を、`specs` キーから仕様書パス一覧を取得して使用する。
`status: "error"` の場合は参考文書なしでレビューを続行する（エラーにしない）。

---

## レビュー結果フォーマット

```markdown
## AIレビュー結果

### 🔴致命的問題

1. **[問題名]**: [具体的な説明]
   - 箇所: [ファイル名:行番号 / セクション名]
   - 参照: [関連ルール/要件定義書]
   - 修正案: [具体的な修正提案]

### 🟡品質問題

1. **[問題名]**: [具体的な説明]
   - 箇所: [ファイル名:行番号 / セクション名]

### 🟢改善提案

1. **[提案名]**: [具体的な説明]

### サマリー

- 🔴致命的: X件（修正済み: Y件）
- 🟡品質: X件（修正済み: Y件）
- 🟢改善: X件
```
