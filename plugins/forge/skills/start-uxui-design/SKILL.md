---
name: start-uxui-design
description: |
  デザイン画像や Figma からデザイントークンと UI コンポーネント一覧を抽出する。
  Apple HIG / Nielsen / Gestalt の哲学的知見に基づく UX 評価付き。iOS / macOS 対応。
  トリガー: "UXUIデザイン分析", "デザイントークン抽出", "start uxui design"
user-invocable: true
argument-hint: "[feature-name] [--platform ios|macos]"
---

# /forge:start-uxui-design

デザイン入力（画像 / Figma / URL）からデザイントークンと UI コンポーネント一覧を抽出する。Apple HIG・Nielsen ヒューリスティクス・ゲシュタルト原則の知識ベースに基づき、UX 観点の評価コメント付きで出力する。

## フロー継続 [MANDATORY]

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ AskUserQuestion で確認する。

## コマンド構文

```
/forge:start-uxui-design [feature] [--platform ios|macos]
```

| 引数 | 内容 |
| --- | --- |
| feature | Feature 名（省略時は対話で確定） |
| --platform | 対象プラットフォーム（省略時は選択肢提示） |

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

### Step 2: プラットフォーム選択

`--platform` 未指定時、AskUserQuestion を使用して選択肢を提示する:

```
対象プラットフォームを選択してください:
1. iOS     — iPhone / iPad アプリのデザイン分析
2. macOS   — Mac アプリのデザイン分析
```

### Step 3: Feature 名の確定

- 引数で指定済み → そのまま使用
- 未指定 → AskUserQuestion を使用して入力を求める

### Step 4: 出力先ディレクトリの解決

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/scripts/resolve_doc_structure.py" --doc-type requirement
```

- 結果あり → そのパスを使用
- 結果なし → `specs/{feature}/requirements/` をデフォルトとして使用

---

## セッション管理 [MANDATORY]

残存セッション検出:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py find --skill start-uxui-design
```

- `status: "none"` → セッション作成へ
- `status: "found"` → AskUserQuestion:「前回の未完了セッションがあります。削除しますか？」
  - **削除** → `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py cleanup {sessions[0].path}`
  - **残す** → 残存ディレクトリを無視して新規セッション作成へ

セッション作成:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py init \
  --skill start-uxui-design \
  --feature "{feature}" \
  --mode "{ios|macos}" \
  --output-dir "{出力先ディレクトリ}"
```

JSON 出力の `session_dir` をコンテキストに保持する。

---

## 知識ベースの読み込み [MANDATORY]

以下の知識ベースを **必ず** Read する:

1. **共通原則**（常に読み込む）:
   - `${CLAUDE_PLUGIN_ROOT}/skills/start-uxui-design/docs/apple_design_principles.md`

2. **プラットフォーム固有ガイド**（選択に応じて1つ読み込む）:
   - iOS → `${CLAUDE_PLUGIN_ROOT}/skills/start-uxui-design/docs/ios_platform_guide.md`
   - macOS → `${CLAUDE_PLUGIN_ROOT}/skills/start-uxui-design/docs/macos_platform_guide.md`

---

## ワークフローの実行 [MANDATORY]

知識ベースの読み込み後、ワークフローファイルを **Read** し、そのファイルの指示に従って作業を実行する:

```
${CLAUDE_PLUGIN_ROOT}/skills/start-uxui-design/docs/uxui_analysis_workflow.md
```

Read 後、ワークフローファイルの Phase 1 から開始する。ワークフローは完了処理（AI レビュー・ToC 更新・commit 確認・セッション削除）まで自己完結している。SKILL.md に戻る必要はない。
