---
name: review
description: |
  コード・文書をレビューし、品質問題の発見から修正まで自動化できる。重大度 🔴🟡🟢 で分類。
  --auto で修正まで一貫実行。code/requirement/design/plan/generic の5種別に対応。
  トリガー: "レビュー", "review", "レビューして", "確認して"
user-invocable: true
hooks:
  Stop:
    - hooks:
        - type: command
          command: "ls .claude/.temp/review-*/session.yaml 2>/dev/null && echo '{\"ok\": false, \"reason\": \"review セッション進行中。フロー継続 [MANDATORY] に従い次の Phase に進んでください\"}' || echo '{\"ok\": true}'"
---

# /forge:review Skill

レビューパイプラインのオーケストレーター。
実際のレビュー・吟味・修正は専用の AI 専用スキルに委譲する。

## コマンド構文

```
/forge:review <種別> [対象] [--エンジン] [--auto [N]] [--auto-critical]

種別: requirement | design | code | plan | uxui | generic
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

## フロー継続 [MANDATORY]

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ AskUserQuestion で確認する。

---

## ワークフロー

### Phase 1: 引数解析

`$ARGUMENTS` を AI が直接解釈して以下の値を確定する:

| 項目 | 確定方法 |
|------|---------|
| `review_type` | `requirement` / `design` / `code` / `plan` / `uxui` / `generic` のいずれか。自然言語から判断可。不明時は AskUserQuestion |
| `targets` | ファイルパス / ディレクトリ / Feature 名。自然言語の説明（「先ほど作成したファイル」等）は文脈から解決する |
| `engine` | `--codex`（デフォルト） / `--claude`。明示指定がなければ codex |
| `auto_count` | `--auto` 指定時のサイクル数（省略時 1）。`--auto` なしは 0（対話モード） |
| `auto_critical` | `--auto-critical` 指定時のみ `true` |

> **設計判断**: スクリプトではなく AI が解析する。ユーザー入力には自然言語が混在するため、リジッドなトークンパーサーでは対応できない。

#### ブランチ確認 [MANDATORY]

対象にブランチ差分・ブランチ名・「このブランチ」等のブランチ関連の表現が含まれる場合、`git branch --show-current` で現在のブランチを確認し、ユーザーの意図するブランチと一致しているか検証する。不一致の場合は AskUserQuestion で確認する。

解析完了後、以下を出力する:

```
### ✅ 引数解析完了

| 項目 | 値 |
|------|-----|
| 種別 | `{種別}` |
| エンジン | `{codex / claude}` |
| モード | `{対話モード}` または `--auto {N}（{N}サイクル自動修正）` または `--auto-critical（🔴致命的のみ自動修正）` |
| ブランチ | `{ブランチ名}`（ブランチ関連の対象がある場合のみ表示） |

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

#### Step 4: perspectives 収集 [MANDATORY]

レビュー観点を perspectives 配列として構成する。`review_criteria_path`（単一パス）の概念は廃止済み。

##### 4-a: review_criteria ファイルの特定

レビュー種別に対応する criteria ファイルを特定する:

```
${CLAUDE_SKILL_DIR}/docs/review_criteria_{type}.md
```

（例: `review_criteria_code.md`, `review_criteria_requirement.md`, `review_criteria_generic.md`）

##### 4-b: perspectives 配列の構成

criteria ファイルを Read し、`## Perspective:` セクションを抽出して perspectives 配列を構成する。

**Perspective 見出しフォーマット**:

```
## Perspective: {name} — {表示名}
```

- `{name}`: 英小文字の識別子（例: `logic`, `resilience`）
- `{表示名}`: 人間向けの表示名（例: `正確性 (Logic)`）

各セクションから以下の構造を生成する:

```yaml
perspectives:
  - name: logic
    criteria_path: "review/docs/review_criteria_code.md"
    section: "正確性 (Logic)"
    output_path: review_logic.md
  - name: resilience
    criteria_path: "review/docs/review_criteria_code.md"
    section: "堅牢性 (Resilience)"
    output_path: review_resilience.md
```

**セクションがない場合**（generic 等）: ファイル全体を単一 perspective として扱い、`section: null` を設定する。

```yaml
perspectives:
  - name: generic
    criteria_path: "review/docs/review_criteria_generic.md"
    section: null
    output_path: review_generic.md
```

##### 4-c: DocAdvisor 追加 perspectives（generic 以外）

generic 以外の種別で DocAdvisor（`/doc-advisor:query-rules`）が利用可能な場合:

- `/doc-advisor:query-rules` Skill にレビュー種別に関連するルール文書を問い合わせる
- 返されたプロジェクト固有のルール文書を追加 perspective として扱う
- `section: null` でファイル全体を perspective に設定する

```yaml
  - name: project-rules
    criteria_path: "docs/rules/coding_standards.md"
    section: null
    output_path: review_project_rules.md
```

##### 4-d: perspectives 数の制限

**プラグインデフォルト + DocAdvisor 追加を合わせて最大 5 perspectives** をガイドラインとする。超過する場合は DocAdvisor 側を優先度順に絞り込む。

#### Step 5: 参考文書収集 [MANDATORY]

##### generic 種別の場合

`/doc-advisor:query-rules` / `/doc-advisor:query-specs` は**使用しない**。参考文書は perspectives に含まれる criteria ファイルのみ。

##### generic 以外の種別

DocAdvisor（`/doc-advisor:query-rules`）が利用可能な場合:

- `/doc-advisor:query-specs` Skill → 関連する要件定義書・設計書を特定
- （レビュー観点は Step 4 で perspectives として収集済み。ここでは参考文書のみ）

DocAdvisor が利用不可の場合 → 「.doc_structure.yaml からの参考文書収集手順」参照

収集完了後、以下を出力する（6件以上は先頭3件 + `... 他N件`）:

```
**reference_docs (N件)**
- `rules/coding.md`
- `specs/design.md`
```

#### Step 6: エンジン確認

- `--claude` 指定 → Claude を使用
- `--codex` 指定または省略 → Codex を使用（Codex 不在時は Phase 3 の exit code=2 ハンドリングで自動フォールバック）

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

2. refs.yaml をスクリプトで生成する:

   ```bash
   echo '<refs_json>' | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session/write_refs.py {session_dir}
   ```

   refs_json のフォーマット:
   ```json
   {
     "target_files": ["対象ファイルパス一覧"],
     "reference_docs": [{"path": "参考文書パス"}],
     "perspectives": [
       {"name": "logic", "criteria_path": "review/docs/review_criteria_code.md", "section": "正確性 (Logic)", "output_path": "review_logic.md"},
       {"name": "resilience", "criteria_path": "review/docs/review_criteria_code.md", "section": "堅牢性 (Resilience)", "output_path": "review_resilience.md"}
     ],
     "related_code": [{"path": "パス", "reason": "理由", "lines": "範囲"}]
   }
   ```

   > **Note**: `review_criteria_path` は廃止。代わりに `perspectives` 配列で観点ごとの入出力を管理する。

作成完了後、以下を出力する:

```
**session_dir**
- `.claude/.temp/{session_dir_name}`
```

### ブラウザ表示の起動（非ブロッキング）

セッション作成完了後、レビュー進捗をブラウザでリアルタイム表示するために show_browser.py を呼び出す。

```bash
timeout 6 python3 ${CLAUDE_PLUGIN_ROOT}/skills/show-browser/scripts/show_browser.py \
  --template review_list \
  --session-dir {session_dir}
```

- 出力（JSON）: `{"monitor_dir": "...", "port": 8765, "url": "..."}`
- ブラウザが自動で開き、以降 plan.yaml の更新が SSE 経由でリアルタイム反映される
- **起動失敗時（exit code が 0 以外）はレビューワークフローを続行する**（ブラウザ表示は補助機能であり、失敗してもレビュー自体には影響しない）
- session_dir 削除時にサーバーは自動停止するため、完了処理での明示的な停止は不要

---

### Phase 3: perspectives 並列レビュー

呼び出し前に以下を出力する:

```
## 🔄 Phase 3: レビュー実行（{perspectives の数} perspectives 並列）

| 項目 | 値 |
|------|-----|
| 種別 | `{種別}` |
| エンジン | `{エンジン}` |
| perspectives | {perspectives の name 一覧} |

{target_files / reference_docs / related_code を上記フォーマットで列挙}

→ {perspectives の数} 個の reviewer を並列起動します
```

#### Codex エンジンの場合

perspectives の数だけ `run_review_engine.sh` をバックグラウンド起動する。各プロセスに perspective 固有の output_path と prompt（criteria_path + section を含む指示）を渡す。

```bash
# 並列起動
pids=()
for perspective in perspectives; do
    ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/run_review_engine.sh \
        "${session_dir}/${perspective.output_path}" \
        "$project_dir" \
        "$prompt" &
    pids+=($!)
done

# 全プロセスの完了を待機
failed=0
codex_missing=0
for pid in "${pids[@]}"; do
    wait "$pid"
    rc=$?
    if [ $rc -eq 2 ]; then
        codex_missing=$((codex_missing + 1))
    elif [ $rc -ne 0 ]; then
        failed=$((failed + 1))
    fi
done
```

- **部分失敗**: 失敗した perspective のレビュー結果は欠損として扱い、成功した perspective の結果のみで続行する
- **全 perspective 失敗（成功 0 件）**: hard fail — エラーメッセージを出力して終了する。全 perspective が失敗した場合を「問題なし」と誤認させない
- **Codex 不在（exit code=2）**: 当該 perspective を即時 Claude フォールバックに切り替える。全 perspective が code=2 の場合は Claude エンジンに一括切替して全 perspective を再実行する

#### Claude エンジンの場合

perspectives の数だけ Agent ツール（`subagent_type` 指定なし = general-purpose）で**並列起動**する。各 subagent の prompt に以下を含める:

**[MANDATORY]** subagent の prompt の冒頭に必ず以下を含めること:
```
あなたは /forge:reviewer として動作します。
まず `plugins/forge/skills/reviewer/SKILL.md` を Read し、そこに記述されたワークフローと出力フォーマットに厳密に従ってください。
```

加えて、以下の情報を渡す:

- `session_dir`
- 種別
- エンジン: `claude`
- `perspective_name`（例: `logic`）
- `criteria_path`（例: `review/docs/review_criteria_code.md`）
- `section`（例: `正確性 (Logic)`、generic の場合は `null`）
- `output_path`（例: `review_logic.md`）

（target_files / reference_docs / related_code は reviewer が refs.yaml から読む）

各 `/forge:reviewer` は指定された perspective のレビューを実行し、結果を `{session_dir}/{output_path}` に Write する。

> **なぜ reviewer SKILL.md を読ませるか**: reviewer SKILL.md には出力フォーマットの厳密な仕様（`1. **[問題名]**: 説明` 形式）が定義されており、このフォーマットに従わないと後続の `extract_review_findings.py` がパースに失敗して指摘事項が 0 件になる。general-purpose agent は SKILL.md を自動ロードしないため、明示的に読ませる必要がある。

- **部分失敗**: Codex エンジンと同様、失敗した perspective は欠損として扱い、成功分のみで続行する
- **全 perspective 失敗（成功 0 件）**: hard fail — エラーメッセージを出力して終了する

#### レビュー結果の統合

全 perspective のレビューが完了したら、`extract_review_findings.py` を session_dir モードで呼び出して結果を統合する:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/reviewer/scripts/extract_review_findings.py {session_dir}
```

このスクリプトは session_dir 内の `review_*.md` を glob で収集し、重複除去・統合を行い、`plan.yaml` と `review.md` を生成する。

保存完了後、以下を出力する:

```
### ✅ Phase 3 完了（レビュー結果）

| 重大度 | 件数 |
|--------|------|
| 🔴 致命的 | X件 |
| 🟡 品質問題 | X件 |
| 🟢 改善提案 | X件 |

**perspectives 結果**
| perspective | 状態 |
|-------------|------|
| logic | ✅ 成功 |
| resilience | ✅ 成功 |

→ `{session_dir}/review.md` と `{session_dir}/plan.yaml` に保存しました
```

### Phase 4: モードによる分岐 [MANDATORY]

> **注意**: Phase 4 の全ステップ（evaluator → present-findings）は**件数や重大度に関係なく必ず実行する**。
> 致命的問題が0件でも、品質問題のみでも省略しない。「軽微だから省略」は禁止。

#### 対話モード（--auto なし）

##### Step 1: evaluator を perspectives 並列起動（AI推奨判定）

perspectives の数だけ Agent ツール（general-purpose）で並列起動する。各 subagent の prompt に `/forge:evaluator` の役割と以下の情報を渡す:

- session_dir
- レビュー種別
- 修正対象フラグ: `--interactive`（全件 AI が推奨判定を行い、plan.yaml を推奨に基づき更新する）
- `perspective_name`（例: `logic`）

各 evaluator は自分の担当 `review_{perspective}.md` を読み、指摘を個別吟味して `{session_dir}/eval_{perspective_name}.json` に結果を Write する（plan.yaml には書き込まない）。

- **部分失敗**: 失敗した perspective の吟味結果は欠損として扱い、成功分のみで続行する
- **全 perspective 失敗（成功 0 件）**: hard fail

##### Step 1.5: evaluator 結果の一括マージ [MANDATORY]

全 evaluator 完了後、orchestrator が `eval_*.json` を収集し plan.yaml を1回だけ更新する:

1. `{session_dir}/eval_*.json` を glob で収集する
2. 全ファイルの `updates` 配列を結合する
3. `update_plan.py --batch` を1回だけ呼び出す:
   ```bash
   echo '<combined_updates>' | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session/update_plan.py {session_dir} --batch
   ```
4. `should_continue` を判定する: `recommendation: fix` が1件以上 → `true`

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
present-findings が plan.yaml を読み、人間の判定を仲介する。

全件完了後 → Phase 5 へ。

#### 自動修正モード（--auto N）

`cycle = 0` から開始し、`cycle < auto_count` の間繰り返す。各サイクルの開始時に以下を出力する:

```
## 🔄 Phase 4: 自動修正 Cycle {N+1}/{auto_count}
```

##### Step 1: evaluator を perspectives 並列起動

perspectives の数だけ Agent ツール（general-purpose）で並列起動する。各 subagent の prompt に `/forge:evaluator` の役割と以下の情報を渡す:

- session_dir
- レビュー種別
- 修正対象フラグ（`--auto`: 🔴+🟡 / `--auto-critical`: 🔴のみ）
- `perspective_name`（例: `logic`）

各 evaluator は自分の担当 `review_{perspective}.md` を読み、指摘を個別吟味して `{session_dir}/eval_{perspective_name}.json` に結果を Write する。

全 evaluator 完了後、orchestrator が `eval_*.json` を収集し `update_plan.py --batch` を1回だけ呼び出して plan.yaml を更新する（Step 1.5 と同じ手順）。

evaluator が返すもの:

- 吟味結果（修正する / スキップ / 要確認 リスト）
- `should_continue`: 継続判定

- **部分失敗**: 失敗した perspective の吟味結果は欠損として扱い、成功分のみで続行する
- **全 perspective 失敗（成功 0 件）**: hard fail

evaluator 完了後、以下を出力する:

```
### Cycle {N} — 吟味結果

| 判定 | 件数 |
|------|------|
| 修正する | X件 |
| スキップ | X件 |
| 要確認 | X件 |
```

`should_continue: false`（全 perspective で修正対象0件）→ `break`

##### Step 2: fixer を呼び出す

Agent ツール（general-purpose）で `/forge:fixer --batch` を起動し、以下を渡す:

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
3. 設計書を更新した場合 → `/doc-advisor:create-specs-toc` が利用可能であれば ToC も更新する

#### 変更差分レビュー

Phase 5 で設計書等を更新した場合、更新されたファイルに対して `/forge:reviewer` を `--diff-only` で呼び出し、変更差分のみをレビューする。fixer の「単独修正レビュー」と同じ subagent パターン。

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

`/doc-advisor:create-specs-toc` Skill が利用可能であれば呼び出す。利用不可の場合はスキップ。

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

#### 終了確認 [MANDATORY]

Phase 5 の他ステップ（テスト・設計書更新・変更差分レビュー・サマリー報告・ToC 更新・commit 確認・push 確認）がすべて完了した後、**レビューを終了できる状態か**を判定する。

**終了条件**: 全指摘が `fixed`（修正済み）または `skipped`（対応しないと決定）で決着していること。`pending` / `needs_review` が残っている状態は「未決着」であり、そのままレビューを終わらせない。

##### Step 1: 未処理指摘の集計

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session/summarize_plan.py {session_dir}
```

出力 JSON の `unprocessed_total` で分岐する。

##### Step 2a: 未処理 0 件 → 終了

全指摘が決着済み。session_dir を削除して終了する:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py cleanup {session_dir}
```

以下を出力する:

```
レビューを終了しました（全 X 件を決着: 修正 Y 件 / 対応しない Z 件）
セッションディレクトリを削除しました: {session_dir}
```

##### Step 2b: 未処理 1 件以上 → 決着が必要

未処理を可視化する（6件以上は先頭3件 + `... 他N件` に省略）:

```
### 未処理の指摘（X 件）

| 重大度 | 件数 |
|--------|------|
| 🔴 致命的 | X件 |
| 🟡 品質問題 | X件 |
| 🟢 改善提案 | X件 |

**内訳（status 別）**
- pending (fixer 失敗 / 未着手): X件
- needs_review (要確認): X件

**指摘（先頭10件）**
- `{title 1}`
- `{title 2}`
- ...
```

`AskUserQuestion` で決着方法を確認する（**「残す」という選択肢は提示しない**。既定は「個別に判定する」）:

- 質問: 「未処理の X 件を決着させてレビューを終了します。どうしますか？」
- 選択肢:
  - **「個別に判定する」**（既定・推奨）
    → `/forge:present-findings {session_dir}` を呼び出し、1 件ずつユーザー判断で決着させる。完了後に **Step 1 に戻る**（再度未処理を集計し、0 件になれば Step 2a で終了）
  - **「全件『対応しない』として終了」**
    → 未処理を一括で `skipped` に更新してから Step 2a で終了する:

      ```bash
      # summarize_plan.py の unprocessed_ids を使って updates を組み立てる
      echo '{"updates": [{"id": <id1>, "status": "skipped", "skip_reason": "ユーザー判断: 全件対応しない"}, {"id": <id2>, "status": "skipped", "skip_reason": "ユーザー判断: 全件対応しない"}, ...]}' \
        | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session/update_plan.py {session_dir} --batch

      python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py cleanup {session_dir}
      ```

> **なぜ「残す」を選択肢に入れないか**: 終了条件を満たさないまま意図的に session を残すと、「終わったのか終わっていないのか」が曖昧になる。クラッシュ等で未完のまま残った session は、次回 `/forge:review` 起動時の残存セッション検出（上記「残存セッション検出」セクション）で「再開 / 破棄」される。これが「中断された session」の正規処理経路であり、Phase 5 では意図的な放置を許さない。

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
