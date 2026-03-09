---
name: review
description: |
  コード・文書を🔴🟡🟢重大度付きでレビューし、修正提案を提示する。
  --auto でレビュー+修正を N サイクル自動実行。5種別（code/requirement/design/plan/generic）に対応。
  トリガー: "レビュー", "review", "レビューして", "確認して"
---

# /forge:review Skill

レビューパイプラインのオーケストレーター。
実際のレビュー・吟味・修正は専用の AI 専用スキルに委譲する。

## コマンド構文

```
/forge:review <種別> [対象] [--エンジン] [--auto [N]]

種別: requirement | design | code | plan | generic
対象: ファイルパス(複数可) | Feature名 | ディレクトリ | 省略(=対話で決定)
エンジン: --codex(デフォルト) | --claude
モード: --auto [N]（レビュー+修正を N サイクル実行。省略時 N=1）
        省略時: 対話モード（人間が判定者）
```

### 使用例

```bash
/forge:review code src/                        # 対話モード
/forge:review code src/ --auto                 # 自動修正 1サイクル
/forge:review code src/ --auto 3               # 自動修正 3サイクル
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
- 残り → 対象（ファイルパス(複数可) / Feature名 / ディレクトリ）

### Phase 1.5: target_files 解決 + 参考文書収集

★ ここで収集した情報は以降の全 agent（reviewer / evaluator / fixer）に渡す。再収集不要。

#### Step 1: .doc_structure.yaml の存在確認 [MANDATORY]

`.doc_structure.yaml` がプロジェクトルートに存在するか確認する。

- **存在しない** → `/forge:setup` を起動して作成を促す
  - 作成されなかった → エラー終了

#### Step 2: target_files の解決

```bash
PYTHON=$(/usr/bin/which python3 2>/dev/null || echo "python3")
"$PYTHON" ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/resolve_review_context.py [対象1] [対象2] ...
```

- `status: "resolved"` → `target_files` を確定し Step 3 へ
- `status: "needs_input"` → `questions` をユーザーに提示し、回答を得てから再実行
- `status: "error"` → `/forge:setup` を起動し `.doc_structure.yaml` の作成を促す

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

#### Step 4: レビュー観点の探索 [MANDATORY]

以下の優先順で検索し、最初に見つかったものを `{review_criteria_path}` として確定する:

1. **`/query-rules` Skill**（DocAdvisor）に「レビュー観点の文書」を問い合わせ
   - 利用可否: `.claude/skills/query-rules/SKILL.md` の存在で判断
2. **`.claude/review-config.yaml`** に保存済みのパスがあれば使用
3. **`${CLAUDE_PLUGIN_ROOT}/defaults/review_criteria.md`**（プラグインデフォルト）

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

#### Step 6: エンジン確認

- `--claude` 指定 → Claude を使用
- `--codex` 指定または省略 → `which codex` を実行
  - 存在する → Codex を使用
  - 存在しない → Claude にフォールバック、「Codex が見つからないため Claude で実行します」と通知

### Phase 2: reviewer を呼び出す

`/forge:reviewer` を呼び出し、以下を渡す:
- 種別・target_files・エンジン・reference_docs・review_criteria_path・related_code

`/forge:reviewer` が返すもの:
- レビュー結果（🔴🟡🟢 指摘事項リスト）

レビュー結果を受け取ったら、以下の frontmatter + Markdown 形式で temp ファイルに保存する:

```markdown
---
review_type: {種別}
engine: {エンジン}
target_files:
  - {ファイルパス1}
reference_docs:
  - {参考文書パス1}
related_code:
  - path: {関連コードパス1}
    reason: {関連性の説明}
timestamp: "{ISO8601形式}"
---

{reviewer が返したレビュー結果テキスト}
```

保存先: `.claude/.temp/review-result-{YYYYMMDD-HHmmss}.md`（ディレクトリがなければ作成）

### Phase 3: モードによる分岐

#### 対話モード（--auto なし）

`/forge:present-findings` を呼び出す:

```
/forge:present-findings .claude/.temp/review-result-{timestamp}.md
```

`present-findings` が人間の判定を仲介し、承認された指摘を `/forge:fixer` に渡す。
reference_docs・related_code はファイルの frontmatter から取得するため、再収集不要。

全件完了後 → Phase 4 へ。

#### 自動修正モード（--auto N）

`cycle = 0` から開始し、`cycle < auto_count` の間繰り返す:

##### Step 1: evaluator を呼び出す

`/forge:evaluator` を呼び出し、以下を渡す:
- レビュー結果
- reference_docs
- target_files
- related_code
- レビュー種別
- 修正対象フラグ（`--auto`: 🔴+🟡）

evaluator が返すもの:
- 吟味結果（修正する / スキップ / 要確認 リスト）
- `should_continue`: 継続判定

`should_continue: false`（修正対象0件）→ `break`

##### Step 2: fixer を呼び出す

`/forge:fixer --batch` を呼び出し、以下を渡す:
- 吟味結果の「修正する」リスト
- target_files
- レビュー種別
- reference_docs
- related_code

##### Step 3: 再レビュー

`/forge:reviewer` を再度呼び出す:
- 前回と同じ 種別・target_files・エンジン・reference_docs・review_criteria_path・related_code

`cycle += 1` して次サイクルへ。

ループ終了後 → Phase 4 へ。

---

### Phase 4: 完了処理

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
## AIレビュー結果（auto: N サイクル実施 / M サイクル完了）
- 🔴致命的: X件（修正済み: Y件）
- 🟡品質: X件（修正済み: Y件）
- 🟢改善: X件
```

evaluator のスキップ・要確認件数も報告:

```
- スキップ: N件（false positive / 設計意図等）
- 要確認: N件（手動対応が必要）
```

#### ToC 更新

`/create-specs-toc` Skill が利用可能か確認する（`.claude/skills/create-specs-toc/SKILL.md` の存在）。
利用可能な場合は呼び出す。利用不可の場合はスキップ。

#### commit 確認

修正が1件以上実行された場合、ユーザーに commit を確認する:

```
変更をコミットしますか？
→ はい / いいえ
```

「はい」の場合 → `/anvil:commit` を呼び出す。

#### push 確認

commit が完了した場合、ユーザーに push を確認する:

```
リモートにプッシュしますか？
→ はい / いいえ
```

「はい」の場合 → `git push` を実行する。

---

## .doc_structure.yaml からの参考文書収集手順

DocAdvisor 利用不可時、`.doc_structure.yaml` を直接読み込んで参考文書を収集する。

### Step A: .doc_structure.yaml を Read

プロジェクトルートの `.doc_structure.yaml` を Read ツールで読み込む。

### Step B: パスの解決（glob 展開 + exclude 適用）

各 category（`specs`, `rules`）の各 doc_type について:

1. `paths` 配列の各エントリを確認
2. `*` を含むパスは Glob ツールで展開
3. `exclude` がある場合、パスコンポーネントに exclude 名を含むものを除外

### Step C: 参考文書の Glob 探索

- `rules` カテゴリの解決済みパスから `**/*.md` で探索
- `specs` カテゴリからレビュー種別に関連する仕様書を探索
- 見つからないファイルはスキップ（エラーにしない）

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
