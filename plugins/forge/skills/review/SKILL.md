---
name: review
description: |
  コード・文書をレビューし、品質問題の発見から修正まで自動化できる。重大度 🔴🟡🟢 で分類。
  --auto で修正まで一貫実行。code/requirement/design/plan/uxui/generic の6種別に対応。
  トリガー: "レビュー", "review", "レビューして", "確認して"
user-invocable: true
argument-hint: "<種別> [--diff | --files a.md,b.md] [--interactive | --auto-critical | --auto] [--codex | --claude]"
allowed-tools: Read, Write, Bash, Grep, Glob, AskUserQuestion, Skill, Agent
hooks:
  Stop:
    - hooks:
        - type: command
          command: "ls .claude/.temp/review-*/session.yaml 2>/dev/null && echo '{\"ok\": false, \"reason\": \"review セッション進行中。フロー継続 [MANDATORY] に従い次の Phase に進んでください\"}' || echo '{\"ok\": true}'"
---

# /forge:review Skill

レビューパイプラインのオーケストレーター。
本 SKILL は **DES-028 §2.2 (CLI 構文)** と **REQ-004 FNC-412 (reviewer 1 起動原則)** に統一されている。
実際のレビュー・吟味・修正は reviewer / evaluator / present-findings / fixer の各 SKILL に委譲する。

---

## コマンド構文 [DES-028 §2.2]

```
/forge:review <種別> [--diff | --files a.md,b.md,...] [--interactive | --auto-critical | --auto] [--codex | --claude]
```

| 軸              | フラグ                                                          | 既定値          | 役割                                          |
| --------------- | --------------------------------------------------------------- | --------------- | --------------------------------------------- |
| 種別 (位置引数) | `code` / `design` / `requirement` / `plan` / `uxui` / `generic` | (必須)          | レビュー種別 (1 個のみ)                       |
| 対象軸          | `--diff` / `--files`                                            | `--diff`        | 現ブランチ未 commit 差分 / 指定ファイル群全文 |
| 介入軸          | `--interactive` / `--auto-critical` / `--auto`                  | `--interactive` | 段階的提示 / 🔴 のみ自動修正 / 全件自動修正   |
| エンジン軸      | `--codex` / `--claude`                                          | `--codex`       | reviewer 実行エンジン                         |

省略形と明示形は等価。例: `/forge:review code` と `/forge:review code --diff --interactive --codex` は同じ動作。

### 使用例

```bash
/forge:review code                                # 差分 × 段階的提示 (デフォルト)
/forge:review code --diff --interactive            # 上の明示形
/forge:review design --files specs/login_design.md # 指定ファイル全文 × 段階的提示
/forge:review code --auto-critical                 # 🔴致命的のみ自動修正
/forge:review code --files src/foo.py,src/bar.py --auto  # 指定ファイル全件自動修正
/forge:review requirement --files login_req.md --claude  # Claude エンジン
```

---

## フロー継続 [MANDATORY]

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ AskUserQuestion で確認する。

---

## 案内表示 [MANDATORY] — forge-review v0.2 破壊的変更の周知 [REQ-004 FNC-408]

forge-review v0.2 は **破壊的変更** を含むため、`/forge:review` の実行ごとにフラグファイルを確認し、**初回のみ** 案内を表示する。詳細は [`docs/readme/forge/migration_notes/forge_review_v0.2.md`](../../../../docs/readme/forge/migration_notes/forge_review_v0.2.md) を参照。

### Step 1: フラグファイル確認

```bash
test -f .claude/.temp/.forge_review_announce_shown && echo "shown" || echo "not_shown"
```

- 出力が `shown` → 案内表示を **スキップ** し、Phase 1 へ進む
- 出力が `not_shown` → Step 2 へ

### Step 2: 案内表示

`not_shown` の場合、以下を 1 回だけ出力する:

```
================================================================
ℹ️  forge-review v0.2 への移行のお知らせ (FNC-408 / 初回のみ表示)
================================================================

本バージョンには **破壊的変更** が含まれます。主な変更点:

1. 固有 perspective (--perspective logic 等) を廃止
   → 種別ベースの review_criteria_<種別>.md のみで動作 (FNC-402)

2. CLI 引数体系を統一 (FNC-410)
   - --diff は「現ブランチ未 commit 差分のみ」に確定 (TBD-401 解消、base 指定なし)
   - --files でファイル全文レビューをバイパス指定
   - --section / --scope / --depth / --auto N は DROP 済み
   - 介入軸は --interactive / --auto-critical / --auto の 3 モードに限定

3. デフォルト挙動の変更
   - 旧: 観点並列起動 / 多軸混在
   - 新: /forge:review <種別> ≡ --diff --interactive (FNC-407)

4. reviewer は 1 起動原則 (FNC-412)
   - 観点軸も対象ファイル軸も例外なく分割起動しない

5. recommendation に create_issue 追加 (FNC-406)
   - ルール抜け落ち発見時に Issue 化フローへ誘導

6. severity の SoT 移管 (FNC-411)
   - severity は principles 側の重大度カタログから取得
   - finding に severity_source フィールド追加

7. 出力ファイル名規約
   - 旧: review_<perspective>.md (perspective ベース命名)
   - 新: review_<種別>.md (例: review_code.md)

詳細・移行手順:
  docs/readme/forge/migration_notes/forge_review_v0.2.md

(この案内は初回のみ表示されます)
================================================================
```

### Step 3: フラグファイル作成

案内表示後、再表示を抑制するためにフラグファイルを作成する:

```bash
mkdir -p .claude/.temp
date -u +"%Y-%m-%dT%H:%M:%SZ" > .claude/.temp/.forge_review_announce_shown
```

> **フラグファイル仕様**: 空でも可だが、タイムスタンプを書き込むことで「いつ案内を表示したか」を後追いできる。`.claude/.temp/` は揮発領域として運用されているため、temp クリーンアップ後は再度案内が表示される (これは仕様)。

---

## Phase 1: 引数解析 + early validation

### Step 1: $ARGUMENTS の解釈

`$ARGUMENTS` を AI が直接解釈し、以下の内部状態を確定する:

| 項目          | 確定方法                                                                                                                |
| ------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `review_type` | 位置引数の 1 個目。`code` / `design` / `requirement` / `plan` / `uxui` / `generic` のいずれか。不明時は AskUserQuestion |
| `target_mode` | `--diff` (デフォルト) / `--files` のいずれか                                                                            |
| `files`       | `--files` 指定時のカンマ区切り値を配列化。`--diff` 時は空配列                                                           |
| `interaction` | `--interactive` (デフォルト) / `--auto-critical` / `--auto` のいずれか                                                  |
| `engine`      | `--codex` (デフォルト) / `--claude` のいずれか                                                                          |

> **設計判断**: スクリプトではなく AI が解析する。ユーザー入力には自然言語が混在するため、リジッドなトークンパーサーでは対応できない。

#### Feature 名 / ディレクトリ / 曖昧入力の扱い [REQ-004 FNC-403]

CLI の位置引数は **種別 1 個のみ**。Feature 名・ディレクトリ・「最近編集した設計書」等の自由入力が含まれていた場合、SKILL レベルで以下のフローで対応する:

1. AI が `.doc_structure.yaml` / git status / `--diff` 候補ファイル等から **対象ファイル群を推測**
2. **AskUserQuestion で対象ファイル群を確認** (推測結果を提示し、追加・削除・置換の選択肢を出す)
3. 確認結果を `--files` 相当として内部展開し、Phase 2 入力解決に進む

### Step 2: early validation [REQ-004 FNC-410]

以下のいずれかに該当する場合は **即座にエラー終了**し、利用者に修正を促す:

| エラー条件                                                                           | メッセージ                                                                                   |
| ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| **対象軸の二重指定**: `--diff` と `--files` を同時指定                               | `--diff と --files は排他です。どちらか一方のみ指定してください`                             |
| **介入軸の二重指定**: `--interactive` / `--auto-critical` / `--auto` のうち 2 つ以上 | `介入軸 (--interactive / --auto-critical / --auto) は相互排他です。1 つのみ指定してください` |
| **エンジン軸の二重指定**: `--codex` と `--claude` を同時指定                         | `--codex と --claude は排他です。1 つのみ指定してください`                                   |
| **DROP 済みフラグ**: `--section` / `--scope` / `--depth` / `--auto N` (件数指定)     | `<flag> は DROP 済みのフラグです。DES-028 §2.2 / REQ-004 FNC-410 を参照してください`         |
| **未知の種別**: 位置引数が 6 種別 (code/design/requirement/plan/uxui/generic) 以外   | `不明な種別です。code/design/requirement/plan/uxui/generic から選んでください`               |

> **注意**: `--auto N` (件数指定) は REQ-004 FNC-404 で **仕様 DROP** された。介入モードは「対話 / 🔴 のみ / 全件」の 3 つに限定する。

#### ブランチ確認 [MANDATORY]

`--diff` モードの場合、または対象に「このブランチ」等のブランチ関連の表現が含まれる場合、`git branch --show-current` で現在のブランチを確認し、ユーザーの意図と一致しているか検証する。不一致の場合は AskUserQuestion で確認する。

### Step 3: パース結果の出力

解析完了後、以下を **整合性のあるテーブル** で出力する:

```
### ✅ Phase 1 完了 — 引数解析

| 項目     | 値                                                                                              |
|----------|-------------------------------------------------------------------------------------------------|
| 種別     | `{review_type}`                                                                                 |
| 対象軸   | `--diff` または `--files (N 件)`                                                                |
| 介入軸   | `--interactive` / `--auto-critical` / `--auto` のいずれか                                       |
| エンジン | `--codex` / `--claude` のいずれか                                                               |
| ブランチ | `{branch}` (--diff モード時のみ)                                                                |

**files (--files 指定時のみ、N 件)**
- `path/to/file1`
- `path/to/file2`
```

---

## Phase 2: 入力解決 (target_files / reference_docs / related_code)

### Step 1: .doc_structure.yaml の存在確認 [MANDATORY]

`.doc_structure.yaml` がプロジェクトルートに存在するか確認する。

- **存在しない** → `/forge:setup-doc-structure` を起動して作成を促す
- 作成されなかった → エラー終了

### Step 2: target_files の解決

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/resolve_review_context.py [対象1] [対象2] ...
```

- `--files` 明示時 → パス解決をバイパスし、指定ファイル群をそのまま target_files として使用
- `--diff` (明示 or デフォルト) 時 → **現ブランチ未 commit 差分のみ** (HEAD ステージ + working tree) を対象に解決 [REQ-004 FNC-403]
- `status: "resolved"` → `target_files` を確定し Step 3 へ
- `status: "needs_input"` → `questions` を AskUserQuestion を使用して確認し、回答を得てから再実行
- `status: "error"` → `/forge:setup-doc-structure` を起動し `.doc_structure.yaml` の作成を促す

### Step 3: target_files 過多時の絞り込み [REQ-004 FNC-412 / DES-028 §2.3 補足]

target_files の実用上限は **3〜5 件** (reviewer 1 起動の原則から)。target_files が 50 件超 (極端なケース) または実用上限を大きく超える場合、**reviewer を分割起動せず**、以下を実行する:

- AskUserQuestion で「ファイル数 N が上限を超えています。`--files` を絞り込みますか? (推奨: 種別ごと・関心領域ごとに分割実行)」と提示する
- 絞り込み結果を `--files` 相当として再展開する

> **重要 [FNC-412]**: 対象ファイル軸でも reviewer は分割起動しない (例外なし)。target_files は 1 つの reviewer にまとめて渡す。

解決完了後、以下を出力する (6 件以上は先頭 3 件 + `... 他 N 件`):

```
**target_files (N 件)**
- `path/to/file1`
- `path/to/file2`
```

### Step 4: 関連コード探索 [MANDATORY]

レビュー・修正の参考にするため、target_files に関連する既存実装を探索する。general-purpose subagent を起動して探索を委譲する。

```
subagent_type: general-purpose
prompt: |
  以下のファイルに関連する既存コード・実装例を探してください。

  ## 対象ファイル
  {target_files のパス一覧}

  ## 探索内容
  - 対象ファイルと同一ディレクトリのファイル
  - 対象ファイルを import / 参照しているファイル
  - 対象ファイルと類似した命名・構造を持つファイル
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

探索結果 (`related_code`) を以降の reviewer に渡す。

### Step 5: reference_docs 収集

`/forge:query-db-specs` Skill を呼び出して関連する要件定義書・設計書を特定する (generic 種別は使用しない)。
収集した文書は `reference_docs` として保存する。

> **観点 (perspectives) の概念は本 SKILL では一切扱わない (旧体系 DES-021 は完全撤廃済み)**。レビュー観点 (P1/P2/P3) は Phase 3 の review_packet で表現する。

完了後、以下を出力する (6 件以上は先頭 3 件 + `... 他 N 件`):

```
### ✅ Phase 2 完了 — 入力解決

**target_files (N 件)**
- `path/to/file1`

**related_code (N 件)**
- `path/to/related` — 関連性の説明

**reference_docs (N 件)**
- `docs/specs/foo.md`
```

---

## Phase 3: review_packet 構築 [DES-028 §3.4 / §3.4.1]

reviewer に渡す **review_packet** を構築する。**観点軸 (perspectives) の概念は使用しない**。reviewer 1 体に種別ベースの criteria + ssot_refs[] + check_order をまとめて渡す。

### Step 1: criteria_path の確定 (種別ベース)

レビュー種別に対応する `review_criteria_<種別>.md` を **1 つだけ** 採用する:

```
${CLAUDE_SKILL_DIR}/docs/review_criteria_<review_type>.md
```

例: `review_criteria_code.md` / `review_criteria_design.md` / `review_criteria_requirement.md` / `review_criteria_plan.md` / `review_criteria_uxui.md` / `review_criteria_generic.md`

### Step 2: ssot_refs[] の抽出 [DES-028 §3.4]

criteria の **§1 SSOT参照** 表を Read し、委譲先文書を `ssot_refs[]` に抽出する:

- 各文書に `priority: P1` を付与
- `doc_type`: `rules` / `principles` / `format` のいずれかに分類
- P2 / P3 固定文書を追加:
  - **P2**: `plugins/forge/docs/spec_priorities_spec.md` §1 (境界設定) — `priority: P2`, `doc_type: principles`
  - **P3**: `plugins/forge/docs/spec_priorities_spec.md` §3.4 / §4 (Yes/No 判定) — `priority: P3`, `doc_type: principles`

#### SSOT 文書数の上限 [DES-028 §2.3]

reviewer 1 体に渡す ssot_refs の文書数の **目安上限は 6〜8 文書** (コンテキスト過大化防止)。超過時の優先採用順 (§3.4.1):

1. **第 1 優先**: `doc_type: rules` (プロジェクト固有 rules)
2. **第 2 優先**: `doc_type: principles` (forge 内蔵 principles)
3. **第 3 優先**: `doc_type: format` (フォーマット規約)

枠から漏れた SSOT参照は **次回レビュー時の候補** として present-findings の出力に残す。

### Step 3: check_order の抽出

criteria の **§2 チェック順** から評価順序を抽出する (P1 → P2 → P3 が標準)。reviewer はこの順で対象ファイルを点検する。

### Step 4: refs.yaml への保存

`init_session.py` でセッションディレクトリを作成し、`write_refs.py` で refs.yaml に review_packet を保存する:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/init_session.py" "{review_type}" "{engine}" "{interaction}"
```

得られた `session_dir` に対して `write_refs.py` を呼び出す:

```bash
echo '<refs_json>' | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session/write_refs.py {session_dir}
```

refs.yaml の新スキーマ [DES-028 §2.3]:

```yaml
target_files:
  - <path>
reference_docs:
  - path: <path>
review_packet:
  criteria_path: <path>            # review_criteria_<種別>.md
  ssot_refs:
    - doc_path: <path>
      priority: "P1" | "P2" | "P3"
      doc_type: "rules" | "principles" | "format"
  check_order: ["P1", "P2", "P3"]
  severity_source: "principles"
  output_path: review_<種別>.md    # reviewer 出力ファイル名 (種別固定)
related_code:
  - path: <path>
    reason: <text>
```

完了後、以下を出力する:

```
### ✅ Phase 3 完了 — review_packet 構築

| 項目          | 値                                            |
|---------------|-----------------------------------------------|
| criteria_path | `review_criteria_<種別>.md`                   |
| ssot_refs     | N 件 (P1: X 件 / P2: Y 件 / P3: Z 件)         |
| check_order   | P1 → P2 → P3                                  |
| output_path   | `review_<種別>.md`                            |

**session_dir**
- `.claude/.temp/{session_dir_name}`
```

---

## Phase 4: reviewer 1 起動 [REQ-004 FNC-412 / DES-028 §2.3]

### 1 起動原則 [MANDATORY]

**reviewer 1 起動 [FNC-412]**: 1 回の `/forge:review` 実行につき reviewer agent は **厳密に 1 体のみ** 起動する。**観点軸も対象ファイル軸も例外なく分割しない**。

| 軸                | 規定                                                                                    |
| ----------------- | --------------------------------------------------------------------------------------- |
| 観点軸 (P1/P2/P3) | **同一 reviewer 内で順次評価する**。観点ごとの並列起動は採用しない                      |
| 対象ファイル軸    | **target_files は 1 つの reviewer にまとめて渡す**。ファイルごとの並列起動は採用しない  |
| SSOT 文書         | criteria + ssot_refs[] を **1 つの review_packet** にまとめて渡す                       |
| finding の分類    | finding に `priority: P1 \| P2 \| P3` ラベルを付与。観点軸の分離は **ラベル**で表現する |

**禁止事項** (Issue #68 複雑性再発防止):

- 観点ごとに reviewer agent を分割起動すること
- SSOT 文書ごとに reviewer agent を分割起動すること
- 対象ファイルごとに reviewer agent を分割起動すること
- 1 回の `/forge:review` 実行で reviewer agent を 2 体以上起動すること (例外なし)

### Step 1: 残存セッション確認

#### 1-1. 自スキル残骸の検出

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/find_session.py
```

- `status: "none"` → 「1-2. 他スキル残骸の通告」へ
- `status: "found"` の場合、`sessions[]` を以下のルールで処理する:
  - **`status: "completed"`** → 正常完了したのに cleanup されなかった残骸として AskUserQuestion なしで自動 cleanup する:
    ```bash
    python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py cleanup {completed_session_path}
    ```
  - **`status: "in_progress"`** が残る場合 → AskUserQuestion で「前回の未完了セッションがあります。再開しますか?」を確認
    - **再開する** → 既存 `session_dir` を使用
    - **破棄する** → `session_manager.py cleanup` で削除後、Step 2 で新規作成

#### 1-2. 他スキル残骸の通告

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/find_session.py --all-skills
```

返却された `sessions[]` から自スキル分（既に処理済み）を除外し、`status: "completed"` は自動 cleanup する。残った `status: "in_progress"` が存在する場合は AskUserQuestion:「他スキルの残骸が N 件あります。今クリーンアップしますか？」

- **はい** → 各セッションを cleanup
- **いいえ** → そのまま Step 2 へ進む

#### 1-3. Phase 切替時の touch [MANDATORY]

Phase 4 以降の各段階（reviewer 起動前 / evaluator 起動前 / fixer 起動前 / 終了処理前）の冒頭で session.yaml の `last_updated` を更新する。これにより長時間 reviewer が走っている間も `cleanup-stale` が誤削除しない。

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py touch {session_dir}
```

### Step 2: reviewer 起動 (Codex / Claude いずれも 1 プロセスのみ)

Phase 3 で確定した review_packet と session_dir を `/forge:reviewer` に渡す。

呼び出し前に以下を出力する:

```
## 🔄 Phase 4: reviewer 1 起動 (FNC-412)

| 項目          | 値                                            |
|---------------|-----------------------------------------------|
| 種別          | `{review_type}`                               |
| エンジン      | `{engine}`                                    |
| target_files  | N 件 (1 起動で全件レビュー)                   |
| ssot_refs     | M 件 (1 起動で全件参照)                       |

→ reviewer 1 体を起動します (観点軸・対象ファイル軸ともに分割しません)
```

#### Codex エンジン

`run_review_engine.sh` を **1 プロセスのみ** 起動する。target_files / ssot_refs を 1 つの review_packet として渡す。

```bash
${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/run_review_engine.sh \
    "${session_dir}/review_<種別>.md" \
    "$project_dir" \
    "$prompt"
```

- **Codex 不在 (exit code=2)**: Claude エンジンへフォールバックして 1 起動でリトライ
- **失敗 (exit code=1 等)**: hard fail (エラーメッセージを出力して終了)

#### Claude エンジン

Agent ツール (general-purpose) で **1 体のみ** 起動する。subagent prompt の冒頭に必ず以下を含める:

```
あなたは /forge:reviewer として動作します。
まず `plugins/forge/skills/reviewer/SKILL.md` を Read し、そこに記述されたワークフローと出力フォーマットに厳密に従ってください。
```

加えて、以下の情報を渡す:

- `session_dir`
- レビュー種別 (`code` / `design` / ...)
- review_packet (criteria_path + ssot_refs[] + check_order + target_files[])
- `output_path: review_<種別>.md`

> **なぜ reviewer SKILL.md を読ませるか**: reviewer SKILL.md には出力フォーマットの厳密な仕様 (`1. **[問題名]**: 説明` 形式、`priority: P1/P2/P3` ラベル) が定義されており、このフォーマットに従わないと後続の `extract_review_findings.py` がパースに失敗して指摘事項が 0 件になる。

### Step 3: レビュー結果の統合

reviewer 完了後、`extract_review_findings.py` を呼び出して結果を統合する:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/extract_review_findings.py {session_dir}
```

このスクリプトは `review_<種別>.md` を読み、統合済みの `plan.yaml` と `review.md` を生成する。
**結果は `review_<種別>.md` 1 ファイル + `plan.yaml` 統合済み** (perspective 単位の出力ファイルは存在しない)。

完了後、以下を出力する:

```
### ✅ Phase 4 完了 — レビュー結果

| 重大度    | 件数 |
|-----------|------|
| 🔴 致命的 | X 件 |
| 🟡 品質   | X 件 |
| 🟢 改善   | X 件 |

| 優先度 | 件数 |
|--------|------|
| P1     | X 件 |
| P2     | X 件 |
| P3     | X 件 |

→ `{session_dir}/review_<種別>.md` と `{session_dir}/plan.yaml` に保存しました
```

---

## Phase 5: 介入軸分岐 + 終了サマリ

### 介入軸による分岐 [DES-028 §2.2 / REQ-004 FNC-404]

| 介入軸            | 動作                                                 |
| ----------------- | ---------------------------------------------------- |
| `--interactive`   | evaluator → present-findings (段階的提示・人間判断)  |
| `--auto-critical` | evaluator → fixer (🔴 critical のみ自動修正)         |
| `--auto`          | evaluator → fixer (全件自動修正・高リスク警告を表示) |

### Step 1: evaluator 起動 (1 体のみ)

evaluator も **1 起動**で動作する。Agent ツール (general-purpose) で 1 体起動し、以下を渡す:

- `session_dir`
- レビュー種別
- 介入軸フラグ (`--interactive` / `--auto-critical` / `--auto`)

evaluator は以下を必ず実行する:

1. `review_<種別>.md` を Read し、findings を 5 観点で精査
2. `eval_<種別>.json` に判定メタ情報 (recommendation: `fix` / `skip` / `create_issue`) を Write
3. `write_interpretation.py` 経由で `review_<種別>.md` を全面書き換え (整形済み)
   - 原文は `review_<種別>.raw.md` に自動バックアップされる

完了後、orchestrator が以下を実行する:

```bash
# 統合 review.md を evaluator 整形済み内容で再生成 (plan.yaml は書き換えない)
python3 ${CLAUDE_SKILL_DIR}/scripts/extract_review_findings.py {session_dir} --review-only

# evaluator 判定を plan.yaml にマージ (priority ベース)
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session/merge_evals.py {session_dir}
```

### Step 2: 介入軸ごとの処理

#### `--interactive` (デフォルト)

`/forge:present-findings {session_dir}` を呼び出す。present-findings が plan.yaml を読み、findings を **severity 順 (🔴 → 🟡 → 🟢)** で 1 件ずつ提示し、人間判断 (修正する / スキップ / Issue 化) を仲介する。

各セクション内では priority 順 (P1 → P2 → P3) でソートする [DES-028 §4.4]。

#### `--auto-critical`

`/forge:fixer --batch` を Agent ツール (general-purpose) で起動し、`severity: critical` AND `recommendation: fix` の指摘のみを自動修正する。

#### `--auto`

`/forge:fixer --batch` を起動し、`recommendation: fix` の全件を自動修正する。**高リスク・明示警告を表示**してから実行する:

```
⚠️ --auto は全件自動修正モードです。修正範囲が広いため、十分な動作確認を推奨します。
```

### Step 3: 単独修正レビュー (--auto / --auto-critical のみ)

fixer が修正した変更差分のみを対象に `/forge:reviewer` を **1 体のみ** 起動して再レビューする (`--diff-only` モード)。

- 修正起因の問題が見つかった場合 → fixer を再起動して修正 (上限 3 回)
- 問題なし → Step 4 へ

### Step 4: 終了処理

#### テスト実行

修正が 1 件以上実行された場合、テストが存在するか確認して実行する:

1. プロジェクトルートに `tests/` ディレクトリまたはテストファイルが存在するか確認
2. 存在する場合 → テストを実行し、結果を報告する
3. テストが失敗した場合 → AskUserQuestion で次アクション (`失敗を確認して終了` / `修正を継続する` / `テストを再実行する`) を確認する

#### 終了サマリ [MANDATORY]

severity × priority の **二軸表示** で結果を提示する:

```
## 🎉 レビュー完了 — 終了サマリ

### 指摘件数: severity × priority 二軸

|              | P1 (ルール合致) | P2 (矛盾) | P3 (複雑化) | 合計 |
|--------------|-----------------|-----------|-------------|------|
| 🔴 致命的    | X 件            | X 件      | X 件        | X 件 |
| 🟡 品質問題  | X 件            | X 件      | X 件        | X 件 |
| 🟢 改善提案  | X 件            | X 件      | X 件        | X 件 |
| **合計**     | X 件            | X 件      | X 件        | X 件 |

### 処理結果

| 状態                          | 件数 |
|-------------------------------|------|
| fixed (修正済み)              | X 件 |
| skipped (対応しない)          | X 件 |
| create_issue (Issue 化)       | X 件 |
| pending / needs_review (未決着) | X 件 |
```

#### commit / push 確認

修正が 1 件以上実行された場合、AskUserQuestion で commit を確認する:

- 「はい」 → `/anvil:commit` を呼び出す
- commit 完了後、AskUserQuestion で push を確認 → 「はい」なら `git push` を実行

#### 終了確認 [MANDATORY]

**終了条件**: 全指摘が `fixed` / `skipped` / `create_issue` で決着していること。

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session/summarize_plan.py {session_dir}
```

- `unprocessed_total: 0` → session_dir を削除して終了
- `unprocessed_total > 0` → AskUserQuestion で決着方法を確認 (`個別に判定する` / `全件「対応しない」として終了`)。「残す」選択肢は提示しない

正常完了処理は **complete → cleanup の 2 段** で行う:

```bash
# 未処理 0 件のクリーンアップ (complete → cleanup の 2 段)
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py complete {session_dir}
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py cleanup {session_dir}
```

`complete` で `session.yaml` を `status: completed` に遷移させてから `cleanup` する。`cleanup` 直前にクラッシュしても、次回 `/forge:review` 起動時または `cleanup-stale` が「完了済み残骸」として自動回収する。

> **なぜ「残す」を選択肢に入れないか**: 終了条件を満たさないまま意図的に session を残すと、「終わったのか終わっていないのか」が曖昧になる。クラッシュ等で未完のまま残った session は、次回 `/forge:review` 起動時の残存セッション検出で再開対象となる。

---

## Progress Reporting 規約

### ファイルリストの省略ルール [MANDATORY]

- 5 件以下 → 全件表示
- 6 件以上 → 先頭 3 件を表示し、残りは `... 他 N 件` で省略

### フォーマット規約 [MANDATORY]

スカラー値 (種別・エンジン等) はテーブルで、ファイルパスは箇条書きで表示する (長いパスがテーブルを崩壊させるため)。

```
| 項目     | 値        |
|----------|-----------|
| 種別     | `code`    |
| エンジン | `claude`  |

**target_files (N 件)**
- `path/to/file1.swift`
- `path/to/file2.swift`
- ... 他 N 件
```

---

## レビュー結果フォーマット (reviewer 出力)

reviewer は以下のフォーマットで `review_<種別>.md` を出力する。詳細は `plugins/forge/skills/reviewer/SKILL.md` を参照。

```markdown
## AIレビュー結果

### 🔴致命的問題

1. **[問題名]**: [具体的な説明]
   - priority: P1 | P2 | P3
   - 箇所: [ファイル名:行番号 / セクション名]
   - 参照: [関連ルール/要件定義書]
   - severity_source: [principles ファイルパス]
   - 修正案: [具体的な修正提案]

### 🟡品質問題

1. **[問題名]**: [具体的な説明]
   - priority: P1 | P2 | P3
   - 箇所: [ファイル名:行番号 / セクション名]

### 🟢改善提案

1. **[提案名]**: [具体的な説明]
   - priority: P1 | P2 | P3
```
