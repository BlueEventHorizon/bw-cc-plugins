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

## Goal

選択モード（interactive / reverse-engineering / from-figma）に応じて要件定義書を作成し、レビュー+自動修正・ToC更新・commit まで完走すること。

## フロー継続 [MANDATORY]

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ AskUserQuestion で確認する。

## 議論モードの基本原則 [MANDATORY]

ユーザーの「叩き台を作って」「全面改訂してレビューしよう」「議論しよう」「壁打ち」は **議論起点** であり、決定フローではない。詳細は `requirements_interactive_workflow.md` § 対話の基本原則 8-11 を参照。

要点のみ:

- 叩き台を書いたら一度止まる。連続 AskUserQuestion で詰めない
- 検討中の暫定案を改訂履歴に書かない (確定段階で 1 エントリにまとめる)
- 大規模 rewrite 後は grep で stale 文言を必ず検査
- システム的 feature は「用語 → アーキテクチャ → 状態 → データモデル → 要件」の順で積み上げる
- 「批判的にレビュー」依頼には A/B/C 比較 + 1 推奨案 + 決定は委ねる、のフォーマットで返す

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

**フィーチャー概念の把握 [MANDATORY]**: フラグ問わず以下を Read し、フィーチャーとは何か・名前空間の原則を把握する。

- `${CLAUDE_PLUGIN_ROOT}/docs/additive_development_spec.md` §0 — フィーチャーの概念定義

1. **新規/追加の確認**:
   - `--new` 指定 → 新規アプリとして処理
   - `--add` 指定 → 既存アプリへの機能追加として処理
   - 未指定 → AskUserQuestion を使用して確認する

   **`--add`（追加開発）の場合 [MANDATORY]**: 以下を Read し、判定基準・矛盾時の優先度・merge 手順を把握したうえで後続 Phase に進む。
   - `${CLAUDE_PLUGIN_ROOT}/docs/additive_development_spec.md` §1 適用条件・対象外、§6 frontmatter 定義一覧
   - `${CLAUDE_PLUGIN_ROOT}/docs/requirement_format.md` の「追加 feature 用 frontmatter」節 — `type: temporary-feature-requirement` 定義

2. **Feature 名の確定**:

   `.doc_structure.yaml` が定義する requirements ディレクトリ（Step 3 の `resolve_doc.py` が返すパス）を Glob して既存要件定義書の有無を確認し、以下の3分岐で確定する:

   - 引数で指定済み → **変更せずそのまま使用**（AI による置き換え禁止）
   - 未指定かつ既存要件定義書が存在しない（初回立ち上げ）→ フィーチャー名不要。`resolve_doc.py` が返すパスに直接配置する（`additive_development_spec.md` §0 参照）
   - 未指定かつ既存要件定義書が存在する → AskUserQuestion でフィーチャー名を確認する

3. **出力先ディレクトリの解決**:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_doc.py"
   ```

   - 結果あり → そのパスを使用（例: `specs/requirements/`）
   - 結果なし → `specs/{feature}/requirements/` をデフォルトとして使用

---

## セッション管理 [MANDATORY]

### 自スキル残骸の検出

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/find_session.py
```

- `status: "none"` → 「他スキル残骸の通告」へ
- `status: "found"` の場合、`sessions[]` を以下のルールで処理する:
  - **`status: "completed"`** → 正常完了したのに cleanup されなかった残骸として AskUserQuestion なしで自動回収する:
    ```bash
    python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py cleanup {completed_session_path}
    ```
  - **`status: "in_progress"`** が残る場合 → AskUserQuestion:「前回の未完了セッションがあります。削除しますか？」
    - **削除** → `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py cleanup {sessions[0].path}`
    - **残す** → 残存ディレクトリを無視して新規セッション作成へ

### 他スキル残骸の通告

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/find_session.py --all-skills
```

返却された `sessions[]` から自スキル分（既に処理済み）を除外し、`status: "completed"` は自動 cleanup する。残った `status: "in_progress"` が存在する場合は AskUserQuestion:「他スキルの残骸が N 件あります。今クリーンアップしますか？」

- **はい** → 各セッションを cleanup
- **いいえ** → そのまま新規セッション作成へ進む

### Phase 切替時の touch [MANDATORY]

各 Phase（または各ワークフローの主要ステップ）の開始時に session.yaml の `last_updated` を更新する。これにより `cleanup-stale` の時間基準が「最後に活動があった時刻」を正しく反映し、長時間タスクが誤削除されることを防ぐ。

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py touch {session_dir}
```

### セッション作成

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/init_session.py" "{feature}" "{interactive|reverse-engineering|from-figma}" "{出力先ディレクトリ}"
```

JSON 出力の `session_dir` をコンテキストに保持する。

---

## ワークフローの実行 [MANDATORY]

モード確定後、該当するワークフローファイルを **Read** し、そのファイルの指示に従って作業を実行する。

| モード              | ファイルパス                                                                                        |
| ------------------- | --------------------------------------------------------------------------------------------------- |
| interactive         | `${CLAUDE_PLUGIN_ROOT}/skills/start-requirements/docs/requirements_interactive_workflow.md`         |
| reverse-engineering | `${CLAUDE_PLUGIN_ROOT}/skills/start-requirements/docs/requirements_reverse_engineering_workflow.md` |
| from-figma          | `${CLAUDE_PLUGIN_ROOT}/skills/start-requirements/docs/requirements_from_figma_workflow.md`          |

Read 後、ワークフローファイルの Phase 1 から開始する。各ワークフローは完了処理（AI レビュー・ToC 更新・commit 確認・セッション削除）まで自己完結している。SKILL.md に戻る必要はない。
