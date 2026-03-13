---
name: create-requirements
description: |
  対話・既存ソース解析・Figma の3モードで構造化要件定義書（SCR/FNC/BL 形式）を作成する。
  完了後は /forge:review でレビュー+修正推奨。
user-invocable: true
argument-hint: "[feature-name] [--mode interactive|reverse-engineering|from-figma] [--new|--add]"
---

# /forge:create-requirements

要件定義書を作成する。3つのモードに対応:

- **interactive**: ゼロから対話しながら要件を固める
- **reverse-engineering**: 既存アプリのソースコードから要件を抽出
- **from-figma**: Figmaデザインファイルから要件とデザイントークンを作成

## コマンド構文

```
/forge:create-requirements [feature] [--mode interactive|reverse-engineering|from-figma] [--new|--add]
```

| 引数    | 内容                             |
| ------- | -------------------------------- |
| feature | Feature 名（省略時は対話で確定） |
| --mode  | モード指定（省略時は選択肢提示） |
| --new   | 新規アプリ                       |
| --add   | 既存アプリへの機能追加           |

---

## 前提確認フェーズ [MANDATORY]（全モード共通）

### Step 1: .doc_structure.yaml の確認

`.doc_structure.yaml` がプロジェクトルートに存在するか確認する。

- **存在しない** → `/forge:setup` を起動を促してエラー終了:
  ```
  Error: .doc_structure.yaml が見つかりません。
  /forge:setup を実行してから再試行してください。
  ```
- **存在する** → Step 2 へ

### Step 2: 出力先ディレクトリの解決

`.doc_structure.yaml` の `specs.requirement.paths` から出力先ディレクトリを取得する。

- 設定あり → そのパスを使用（例: `specs/requirements/`）
- 設定なし → `specs/{feature}/requirements/` をデフォルトとして使用

### Step 3: プロジェクト固有情報の取得 [MANDATORY]

以下の defaults を**常に**読み込む（ベースライン）:

- **`${CLAUDE_PLUGIN_ROOT}/defaults/spec_format.md`** — ID分類カタログ（使用するIDをここから選択）
- **`${CLAUDE_PLUGIN_ROOT}/defaults/requirement_format.md`** — 要件定義書テンプレート
- **`${CLAUDE_PLUGIN_ROOT}/defaults/spec_design_boundary_guide.md`** — 要件・設計の境界ガイド（What/How の判断基準）

---

## モード選択

`--mode` 未指定時、AskUserQuestion を使用して3択を提示する:

```
どの方法で要件定義を開始しますか？
1. interactive         — ゼロから対話しながら要件を固める
2. reverse-engineering — 既存アプリのソースコードを解析して要件を抽出
3. from-figma          — Figmaデザインファイルから要件とデザイントークンを作成（Figma MCP 必須）
```

`from-figma` 選択時: Figma MCP の利用可否を確認する（利用可能なツール一覧に `mcp__figma` 等が存在するか）。
未インストール時はエラーで終了:

```
Error: Figma MCP が必要です。
interactive または reverse-engineering を使用してください。
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

---

## 残存セッション検出 [MANDATORY]

`.claude/.temp/` 内に `skill: create-requirements` の `session.yaml` を持つディレクトリを検索する。

```bash
grep -rl "^skill: create-requirements" .claude/.temp/*/session.yaml 2>/dev/null
```

- **見つからない** → セッション作成フェーズへ
- **見つかった** → AskUserQuestion:「前回の未完了セッションがあります。削除しますか？」
  - **削除** → `rm -rf {session_dir}` して新規セッション作成へ
  - **残す** → 残存ディレクトリを無視して新規セッション作成へ

---

## セッション作成フェーズ [MANDATORY]

```bash
SESSION_NAME=$(date +%Y%m%d-%H%M%S)-$(openssl rand -hex 3)
SESSION_DIR=".claude/.temp/${SESSION_NAME}"
mkdir -p "${SESSION_DIR}/refs"
```

`session.yaml` を初期化:

```yaml
skill: create-requirements
feature: "{feature}"
mode: "{interactive|reverse-engineering|from-figma}"
started_at: "{ISO 8601}"
last_updated: "{ISO 8601}"
status: in_progress
resume_policy: none
output_dir: "{出力先ディレクトリ}"
```

---

## コンテキスト収集フェーズ [MANDATORY]

モードに応じた agent を **Agent ツールで並列起動** し、コンテキストを収集する。
各 agent には `${CLAUDE_PLUGIN_ROOT}/docs/context_gathering_guide.md` のパスと `session_dir` を渡す。

### モード別起動マトリクス

| agent | interactive (新規) | interactive (--add) | reverse-engineering | from-figma |
|-------|--------------------|---------------------|---------------------|------------|
| rules agent | ○ | ○ | ○ | ○ |
| specs agent | - | ○ | - | - |
| code agent | - | - | ○ | - |

### 各 agent への指示

```
session_dir: {session_dir}
guide: ${CLAUDE_PLUGIN_ROOT}/docs/context_gathering_guide.md
steps: {モードに応じた steps}
feature: "{feature}"
skill_type: "要件定義書作成"
```

| agent | steps |
|-------|-------|
| rules agent | `[3]` |
| specs agent | `[1, 2]` |
| code agent | `[1, 5]` |

### 失敗時の扱い

- agent がエラー終了 → 該当カテゴリの refs/ ファイルなしで後続工程に進む
- agent が空結果 → 正常扱い
- 失敗した agent がある場合、refs/ 統合表示でその旨を報告する

---

## refs/ 統合・表示 [MANDATORY]

全 agent 完了後、`{session_dir}/refs/` 内のファイルを Read し表示する:

```
### ✅ コンテキスト収集完了

**rules (N件)**
- `rules/requirement_format.md` — 要件書フォーマット

**specs (N件)**（--add 時のみ）
- `specs/{feature}/requirements/xxx.md` — 既存要件定義書

**code (N件)**（reverse-engineering 時のみ）
- `src/xxx/YYY.swift` — ソースコード
```

5件以下は全件表示、6件以上は先頭3件+省略。

---

## Mode: interactive（対話型）

**対象**: Figma・既存ソースなし、アイデアベースで要件を固める場合。

### 対話の基本原則 [MANDATORY]

1. **選択肢ファースト**: 「A / B / C のどれが近いですか？」形式で提示
2. **視覚的確認**: ASCII 図や Mermaid 図で画面・フロー確認
3. **小さく確認**: フェーズ終了時だけでなく都度確認
4. **未確定の許容**: TBD-001 形式で未確定事項を登録・管理
5. **What に集中**: How（技術実装）は記載しない（「ユーザーマニュアルに書くか？」で判断）
6. **段階的な文書提示**: APP-001 承認後に詳細文書へ進む
7. **スコープ管理**: 必須 / あると良い / 将来 の3段階で分類

### アンチパターン [MANDATORY]

| パターン           | 問題         | 対策                                   |
| ------------------ | ------------ | -------------------------------------- |
| 質問攻め           | ユーザー疲弊 | 選択肢提示、1回3〜5問以内              |
| 曖昧な合意         | 後で認識ズレ | 図表で視覚的確認                       |
| How 混入           | 設計領域侵食 | 「ユーザーマニュアルに書くか？」で判断 |
| 完璧主義           | 進まない     | TBD を許容                             |
| 一気に全部         | 漏れ・矛盾   | フェーズごとに確定                     |
| 既存無視（追加時） | 整合性崩壊   | 既存資産を必ず確認                     |
| スコープ膨張       | 終わらない   | 3段階分類                              |

### Phase 1: ビジョン・価値の明確化

- **新規**: APP-001 ドラフト（解決する課題、提供価値、主要機能）を作成
- **追加**: APP-001 参照のみ、機能の目的と既存機能との関係を確認

### Phase 2: 体験フロー・画面構成

- 主要シナリオ確認（トリガー、操作フロー、完了条件）
- 画面一覧のドラフト作成・過不足確認
- ナビゲーション構造確認

### Phase 3: 詳細仕様

- グロッサリー作成（用語定義・共有）[MANDATORY]
- 画面要件 SCR-xxx: 目的、表示要素、操作、空状態、エラー
- 機能要件 FNC-xxx: トリガー、入力、出力、制約
- ビジネスロジック BL-xxx: 計算ルール、バリデーション
- データ要件 DM-xxx: 保存内容、保存場所

### Phase 4: 統合・品質確認

- フォーマットに従い整形
- 未確定事項の整理（TBD リスト化）

---

## Mode: reverse-engineering（既存アプリのリバースエンジニアリング）

**対象**: 既存のソースコードから要件を抽出・再構築する場合。

### 事前確認

- ソースコードのパスを確認
- 基本方針確認: **機能保持のみ** / **機能もデザインも刷新**

### Phase 1: ソースコード解析 [MANDATORY]

`{session_dir}/refs/code.yaml` を Read し、収集済みのソースコード一覧を起点に解析する:

- refs/code.yaml に記載されたファイルを Read して全体構造を把握
- プロジェクト構造の把握（ディレクトリ構成）
- 画面・コンポーネントの列挙（View/画面クラスを特定）
- ナビゲーション構造の特定
- 必要に応じて追加の Grep/Glob 探索で補完

### Phase 2: 要件抽出 [MANDATORY]

- ユーザーアクションの特定（ボタン操作、ジェスチャー等）
- 条件分岐の要件化（分岐ロジックを What として記述）
- データ永続化の特定（保存先・内容）
- エラーハンドリング抽出

### Phase 3: 要件定義書作成

- 解析結果から APP-001 → 画面要件（SCR-xxx）の順に作成
- デザイン刷新時はデザイン要素を切り離し機能要件のみ記載

### Phase 4: 品質確認

- 全画面の SCR-xxx 存在確認
- 主要機能の FNC-xxx 存在確認

---

## Mode: from-figma（Figmaデザイン取り込み）

**事前条件**: Figma MCP が利用可能であること（未インストール時は前提確認フェーズでエラー終了）。

### Phase 1: Figmaアクセス確認

- Figmaファイルへのアクセス権限確認
- デザインが最終版であることを確認

### Phase 2: デザインシステム構築

- カラー・タイポグラフィ・スペーシング・シャドウの抽出
- 2層構造: 原子的トークン → 意味的定義
- 再利用可能コンポーネントの特定

### Phase 3: 要件定義書作成

- 出力先ディレクトリ構造の準備
- 各画面の SCR-xxx 作成（ASCII レイアウト図を含む）
- UIコンポーネント CMP-xxx の作成
- 機能要件 FNC-xxx の作成

### Phase 4: 静的アセット管理

- アイコン・イラスト・ロゴ・背景画像の洗い出し
- アセット管理方針の記載

### Phase 5: 品質確認

- デザイントークン完全性検証
- 要件定義書の全画面対応確認

---

## 完了処理

### セッション削除

全フェーズ正常完了後、セッションディレクトリを削除する:

```bash
rm -rf {session_dir}
```

### 完了案内

作成したファイルパスとともに次のステップを案内する:

```
要件定義書を作成しました:
  → {作成ファイルパス}

次のステップ:
  /forge:review requirement {作成ファイルパス} --auto     # レビュー+修正（推奨）
  /forge:review requirement {作成ファイルパス} --auto 3   # 3サイクル徹底修正
  /forge:review requirement {作成ファイルパス}            # 対話モードでレビュー
```
