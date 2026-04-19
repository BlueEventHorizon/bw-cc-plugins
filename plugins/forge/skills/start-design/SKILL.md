---
name: start-design
description: |
  要件定義書から設計書を作成する。コンテキスト収集→設計書執筆→レビュー+自動修正→commit を一貫実行。
  トリガー: "設計書作成", "設計開始", "start design"
user-invocable: true
argument-hint: "<feature>"
allowed-tools: Bash, Read, Write, Glob, Grep, Agent, AskUserQuestion
---

# /forge:start-design

要件定義書から設計書を作成する。

## フロー継続 [MANDATORY]

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ AskUserQuestion で確認する。

---

## コマンド構文

```
/forge:start-design [feature]
```

| 引数    | 内容                             |
| ------- | -------------------------------- |
| feature | Feature 名（省略時は対話で確定） |

---

## 事前準備 [MANDATORY]

### Feature の確定

対象 Feature を確定する。Feature が決まらないと、入力（どの要件定義書を設計するか）も出力先も決まらない。

- **引数あり** → その Feature を使用
- **引数なし** → AskUserQuestion で対象 Feature を確認

### .doc_structure.yaml の確認

`.doc_structure.yaml` がプロジェクトルートに存在するか確認する。

- **存在しない** → AskUserQuestion を使用して確認する:
  ```
  .doc_structure.yaml が見つかりません。
  /forge:setup-doc-structure を実行してプロジェクト構造を定義する必要があります。今すぐ /forge:setup-doc-structure を実行しますか？
  ```
  - **はい** → `/forge:setup-doc-structure` を呼び出し、完了後に次のステップへ進む
  - **いいえ** → 終了
- **存在する** → 次のステップへ

### 出力先の解決

設計書の出力先ディレクトリを特定する。入力文書（要件定義書）は Phase 1 で agent が特定する。

- `doc-structure` スキルのスクリプトで Feature を検索:
  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/scripts/resolve_doc_structure.py" --doc-type design
  ```
- 解決できない場合は AskUserQuestion で出力先を確認する

### モード判定 [MANDATORY]

出力先ディレクトリの設計書ファイルを Glob で確認し、モードを決定:

| 状況               | モード                           |
| ------------------ | -------------------------------- |
| 設計書が存在しない | **新規作成モード** → Phase 1 へ  |
| 設計書が存在する   | AskUserQuestion でユーザーに確認 |

既存設計書がある場合、AskUserQuestion を使用して確認する:

- 既存設計書に追記・修正する → Phase 1 へ
- 新たな設計書ファイルを追加作成する → Phase 1 へ
- レビューのみ行う → `/forge:review design {既存設計書パス}` を起動して終了

### プラグイン文書の読み込み [MANDATORY]

以下のプラグイン文書を**常に**読み込む:

- **`${CLAUDE_PLUGIN_ROOT}/docs/spec_format.md`** — ID分類カタログ（設計IDの体系を確認）
- **`${CLAUDE_PLUGIN_ROOT}/docs/design_format.md`** — 設計書テンプレート
- **`${CLAUDE_PLUGIN_ROOT}/docs/design_principles_spec.md`** — 設計原則・作成ガイドライン
- **`${CLAUDE_PLUGIN_ROOT}/docs/spec_design_boundary_spec.md`** — 要件・設計の境界ガイド

---

## セッション管理 [MANDATORY]

残存セッション検出:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py find --skill start-design
```

- `status: "none"` → セッション作成へ
- `status: "found"` → AskUserQuestion:「前回の未完了セッションがあります。削除しますか？」
  - **削除** → `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py cleanup {sessions[0].path}`
  - **残す** → 残存ディレクトリを無視して新規セッション作成へ

セッション作成:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py init \
  --skill start-design \
  --feature "{feature}" \
  --mode "{new|update}" \
  --output-dir "{出力先ディレクトリ}"
```

JSON 出力の `session_dir` をコンテキストに保持する。

### ブラウザ表示の起動

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/show-browser/scripts/show_browser.py \
  --template session_status \
  --session-dir {session_dir}
```

- 出力 JSON の `url` をユーザーに提示する
- 失敗時は続行する

---

## Phase 1: コンテキスト収集 [MANDATORY]

以下の3つの収集を **Agent ツールで並列起動** する。
各 agent がエラー終了した場合は該当カテゴリなしで後続工程に進む。

### 1.1 要件定義書の収集

Feature の要件定義書を検索・特定する agent を起動する。結果は `{session_dir}/refs/specs.yaml` に書き込まれる。

```yaml
session_dir: {session_dir}
spec: ${CLAUDE_PLUGIN_ROOT}/docs/context_gathering_spec.md
tasks:
  - 仕様書調査
feature: "{feature}"
skill_type: "設計書作成"
```

### 1.2 設計ルールの収集

プロジェクト固有の設計ルール・ワークフローを検索する agent を起動する。結果は `{session_dir}/refs/rules.yaml` に書き込まれる。

```yaml
session_dir: {session_dir}
spec: ${CLAUDE_PLUGIN_ROOT}/docs/context_gathering_spec.md
tasks:
  - 実装ルール調査
feature: "{feature}"
skill_type: "設計書作成"
```

### 1.3 既存実装の収集

既存実装資産（再利用候補）を検索する agent を起動する。結果は `{session_dir}/refs/code.yaml` に書き込まれる。

```yaml
session_dir: {session_dir}
spec: ${CLAUDE_PLUGIN_ROOT}/docs/context_gathering_spec.md
tasks:
  - 既存コード調査
feature: "{feature}"
skill_type: "設計書作成"
```

### 1.4 収集結果の確認

全 agent 完了後、`{session_dir}/refs/` 内のファイルを Read し表示する。5件以下は全件表示、6件以上は先頭3件+省略。

---

## Phase 2: 要件定義書の分析 [MANDATORY]

### 2.1 収集済み文書の読み込み

`{session_dir}/refs/` 内の全ファイルを Read する:

- **refs/specs.yaml** → 要件定義書を Read
- **refs/rules.yaml** → プロジェクト固有の設計ルール・フォーマットを把握（プラグイン文書より優先）
- **refs/code.yaml** → 既存実装資産を確認（再利用可能性を判断）

いずれかが存在しない場合（agent 失敗）→ 該当カテゴリなしで続行。
ただし **要件定義書が取得できない場合** → AskUserQuestion:
  - 要件定義書のパスを手動で指定する
  - 要件定義書なしで設計を進める（リスクを理解した上で）

### 2.2 要件定義書の徹底確認

取得した要件定義書を Read して以下を確認する:

- 機能要件の完全性
- 非機能要件の明確性
- 制約条件と前提条件
- 用語定義と業務ルール

### 2.3 不明点の整理

要件に曖昧な点・矛盾がある場合は、質問リストを作成して AskUserQuestion を使用してユーザーに確認する。

仕様変更が発生した場合は、要件定義書を即座に更新すること（設計作業の前に不明点を解消すること）。

### 2.4 既存実装資産の確認

refs/code.yaml に記載された既存実装を確認し、再利用可能性を判断する。

存在する場合は必ず再利用（新規作成禁止）。再利用したコンポーネントは Phase 3 で設計書に明記すること。

---

## Phase 3: 設計書の作成 [MANDATORY]

### 3.1 設計書フォーマットの適用

フォーマットの優先順位:

1. **プロジェクト固有ルール**: refs/rules.yaml に含まれるフォーマット定義
2. **プラグイン文書**: `${CLAUDE_PLUGIN_ROOT}/docs/design_format.md`

設計書に必須記載する項目:

- **使用する既存コンポーネント**: 再利用する既存実装のファイルパス
- 再利用しない判断をした場合はその理由

### 3.2 設計ID体系の確認・採番 [MANDATORY]

プロジェクトのルールに従う（ルールがない場合は `DES-XXX` 形式を推奨）。

設計 ID を付与する際は、必ず以下のスクリプトで次の連番を取得する。手動での番号決定は禁止:

```bash
SCAN_SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/next-spec-id/scripts/scan_spec_ids.py"
python3 "$SCAN_SCRIPT" DES
```

JSON 出力の `next_id` をファイル名・設計 ID として使用する。`duplicates` が空でない場合は警告を表示する。

### 3.3 設計書の作成

- **作成場所**: session.yaml の `output_dir`
- **フォーマット**: Markdown (.md) ファイル
- **ユーザーレビューは AI レビュー（Phase 4）の後に実施する** — AI レビューで品質問題を修正してからユーザー確認を行う方が効率的

**禁止事項**:

- ❌ ソースコードの大量記載（説明用の小規模例は許容）
- ❌ 技術選択の理由を記載せずにフレームワークを指定
- ❌ 要件にない機能の追加
- ❌ レビュー未完了での次工程着手
- ❌ 設計IDの重複や欠番

**よくある失敗パターン（注意）**:

- 既存資産を1パターンの検索で諦め、重複実装してしまう → 複数キーワード・複数ツールで網羅的に検索
- プロジェクトの定数定義を無視して値をハードコードしてしまう → 定数定義・デザイントークンを必ず参照
- 同種の機能・画面の既存実装を確認せず独自設計してしまう → 既存の類似パターンを必ず確認
- 設計判断の根拠を記載しない → 技術選択の理由・代替案を設計書に文書化すること

---

## Phase 4: AIレビュー

作成した設計書に対して `/forge:review` を `--auto` モードで実行する:

```
/forge:review design {作成ファイルパス} --auto
```

対象はこのワークフローで作成・変更したファイル（差分）のみ。

AI レビュー完了後、AskUserQuestion を使用して設計書のユーザーレビューを実施する。

---

## Phase 5: 品質保証

### 5.1 完全性チェック

設計書作成後、以下を確認する:

- [ ] 全要件が設計に反映されているか
- [ ] 設計IDが一意で適切に付与されているか
- [ ] 既存資産の活用が検討されているか
- [ ] 使用する既存コンポーネントが明記されているか

### 5.2 specs ToC 更新

設計書の作成・更新後、`/doc-advisor:create-specs-toc` が利用可能であれば実行すること（利用不可の場合はスキップ）。

---

## 完了処理

### commit/push 確認

`/anvil:commit` を実行して commit/push を確認する。

### セッション削除

セッションディレクトリを削除する:

```bash
rm -rf {session_dir}
```

### 完了案内

作成したファイルパスとともに次のステップを案内する:

```
設計書を作成しました:
  → {作成ファイルパス}

次のステップ:
  /forge:start-plan {feature}    # 計画書作成へ進む
```
