---
name: start-requirements
description: |
  要件定義書を作成する。3モード対応: 対話形式でゼロから/既存コード解析で逆算/Figma デザインから抽出。
  完了後にレビュー+自動修正→ToC更新→commit の完了フローを実行する。
  トリガー: "要件定義", "要件定義書作成", "ソースから要件抽出", "Figma から要件"
user-invocable: true
argument-hint: "[feature-name] [--mode interactive|reverse-engineering|from-figma] [--new|--add]"
---

# /forge:start-requirements

要件定義書を作成する。3つのモードに対応:

- **interactive**: ゼロから対話しながら要件を固める
- **reverse-engineering**: 既存アプリのソースコードから要件を抽出
- **from-figma**: Figma デザインファイルから要件とデザイントークンを作成

## フロー継続 [MANDATORY]

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ AskUserQuestion で確認する。

## コマンド構文

```
/forge:start-requirements [feature] [--mode interactive|reverse-engineering|from-figma] [--new|--add]
```

| 引数    | 内容                             |
| ------- | -------------------------------- |
| feature | Feature 名（省略時は対話で確定） |
| --mode  | モード指定（省略時は選択肢提示） |
| --new   | 新規アプリ                       |
| --add   | 既存アプリへの機能追加           |

---

## 前提確認 [MANDATORY]

### Step 1: .doc_structure.yaml の確認

`.doc_structure.yaml` がプロジェクトルートに存在するか確認する。

- **存在しない** → AskUserQuestion を使用して確認する:
  ```
  .doc_structure.yaml が見つかりません。
  /forge:setup-doc-structure を実行してプロジェクト構造を定義する必要があります。今すぐ /forge:setup-doc-structure を実行しますか？
  ```
  - **はい** → `/forge:setup-doc-structure` を呼び出し、完了後に Step 2 へ進む
  - **いいえ** → 終了
- **存在する** → Step 2 へ

### Step 2: モード選択

`--mode` 未指定時、AskUserQuestion を使用して選択肢を提示する:

```
どの方法で要件定義を開始しますか？
1. interactive         — ゼロから対話しながら要件を固める
2. reverse-engineering — 既存アプリのソースコードを解析して要件を抽出
3. from-figma          — Figma デザインファイルから要件とデザイントークンを作成
```

---

## Phase 0: 事前確認（全モード共通）

1. **新規/追加の確認**:
   - `--new` 指定 → 新規アプリとして処理
   - `--add` 指定 → 既存アプリへの機能追加として処理
   - 未指定 → AskUserQuestion を使用して確認する

2. **Feature 名の確定**:
   - 引数で指定済み → そのまま使用
   - 未指定 → AskUserQuestion を使用して入力を求める

3. **出力先ディレクトリの解決**:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/scripts/resolve_doc_structure.py" --doc-type requirement
   ```

   - 結果あり → そのパスを使用（例: `specs/requirements/`）
   - 結果なし → `specs/{feature}/requirements/` をデフォルトとして使用

---

## セッション管理 [MANDATORY]

残存セッション検出:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py find --skill start-requirements
```

- `status: "none"` → セッション作成へ
- `status: "found"` → AskUserQuestion:「前回の未完了セッションがあります。削除しますか？」
  - **削除** → `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py cleanup {sessions[0].path}`
  - **残す** → 残存ディレクトリを無視して新規セッション作成へ

セッション作成:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py init \
  --skill start-requirements \
  --feature "{feature}" \
  --mode "{interactive|reverse-engineering|from-figma}" \
  --output-dir "{出力先ディレクトリ}"
```

JSON 出力の `session_dir` をコンテキストに保持する。

### ブラウザ表示の起動（非ブロッキング）

セッション作成完了後、要件定義書作成の進捗をブラウザでリアルタイム表示するために show_browser.py を呼び出す。

```bash
timeout 6 python3 ${CLAUDE_PLUGIN_ROOT}/skills/show-browser/scripts/show_browser.py \
  --template session_status \
  --session-dir {session_dir}
```

- 出力（JSON）: `{"monitor_dir": "...", "port": 8765, "url": "..."}`
- ブラウザが自動で開き、以降セッション状態の更新が SSE 経由でリアルタイム反映される
- **起動失敗時（exit code が 0 以外）は要件定義書作成ワークフローを続行する**（ブラウザ表示は補助機能であり、失敗しても要件定義書作成自体には影響しない）
- session_dir 削除時にサーバーは自動停止するため、完了処理での明示的な停止は不要

---

## ワークフローの実行 [MANDATORY]

モード確定後、該当するワークフローファイルを **Read** し、そのファイルの指示に従って作業を実行する。

| モード | ファイルパス |
|--------|-------------|
| interactive | `${CLAUDE_PLUGIN_ROOT}/skills/start-requirements/docs/requirements_interactive_workflow.md` |
| reverse-engineering | `${CLAUDE_PLUGIN_ROOT}/skills/start-requirements/docs/requirements_reverse_engineering_workflow.md` |
| from-figma | `${CLAUDE_PLUGIN_ROOT}/skills/start-requirements/docs/requirements_from_figma_workflow.md` |

Read 後、ワークフローファイルの Phase 1 から開始する。各ワークフローは完了処理（AI レビュー・ToC 更新・commit 確認・セッション削除）まで自己完結している。SKILL.md に戻る必要はない。
