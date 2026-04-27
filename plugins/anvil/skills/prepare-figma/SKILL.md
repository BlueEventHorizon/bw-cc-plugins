---
name: prepare-figma
description: Figma デザインからデザイン仕様書を作成する subagent スキル。PAT で対象フレームを特定し、MCP で詳細取得、PAT で精度補完。画面設計書の nodeId を信頼せず Figma で検証する。/anvil:impl-issue の Phase 7 から呼び出される。
user-invocable: false
allowed-tools: Bash(curl *), Bash(echo *), Bash(jq *), Bash(python3 *), Bash(mkdir *), Read, Write, Edit, Glob, Grep, AskUserQuestion, Skill, mcp__figma-dev-mode-mcp-server__get_design_context, mcp__figma-dev-mode-mcp-server__get_metadata, mcp__figma-dev-mode-mcp-server__get_screenshot, mcp__figma-dev-mode-mcp-server__get_variable_defs
---

# prepare-figma

Figma デザインからデザイン仕様書（What: 何を作るか）を作成する subagent スキル。

**作成するもの**: デザイン仕様書（`specs/design/{id}_デザイン仕様書.md`）
**作成しないもの**: 実装設計書（How: どう作るか）— ルール文書・類似PR・既存コードの調査後に作成するため

## 入力

オーケストレータ（`/anvil:impl-issue` Phase 7）から以下を受け取る：

- **画面 ID**（例: `ei-gum_ホームタブ画面_LIMITED ITEMSタブ`）
- **画面設計書パス** — オーケストレータが Phase 2 で特定・読み込み済みのファイルパス
- **確認・調整事項パス**（任意）— 存在する場合のファイルパス
- **Figma URL** — 画面設計書に記載されていた Figma URL

## 出力

- `specs/design/{id}_デザイン仕様書.md` — 永続成果物
- `specs/design/images/{id}_{画面名}.png` — スクリーンショット

## Figma データ取得方針

**PAT で特定 → MCP で詳細取得 → PAT で補完** の 3 段階。

### ローカル Figma が使える場合の優先順

ユーザーが「Figma Desktop を開いている」「対象フレームを選択した」と明示した場合は、
**Desktop MCP の現在選択ノード取得を先に試す**。

推奨順序:

1. MCP を nodeId なしで呼び出し、現在選択中ノードの `get_screenshot` / `get_design_context` を確認
2. Desktop MCP で取得できた場合は、その結果を一次情報として採用
3. 取得できない場合のみ、PAT + URL / nodeId 指定でフォールバック

Desktop MCP が失敗した場合でも、失敗理由（未選択 / Dev Mode 権限不足 / resource inaccessible）を記録すること。

### Step A: PAT（REST API）で対象デザインを特定

`resolve-figma-node` スキルを使用。画面設計書の nodeId を信頼せず Figma 側で検証する。
結果として nodeId、Figma URL、フレーム名、サイズを確定する。

### Step B: MCP で詳細デザイン情報を取得（メイン）

| ツール               | 用途                                            | 実行順序        |
| -------------------- | ----------------------------------------------- | --------------- |
| `get_design_context` | レイアウト・スタイル情報（React+Tailwind 形式） | 1. 最初         |
| `get_metadata`       | ノード構造概要（マスク/クリッピング確認）       | 2. 個別要素確認 |
| `get_screenshot`     | スクリーンショット（視覚確認）                  | 3. 目視確認     |
| `get_variable_defs`  | デザイントークン（色・spacing・typography）     | 4. 必要時       |

### MCP vs REST API の使い分け

| 用途                            | 推奨         | 理由                         |
| ------------------------------- | ------------ | ---------------------------- |
| デザイン情報取得                | **MCP**      | 構造化された情報を取得可能   |
| 変数・スタイル取得              | **MCP**      | `get_variable_defs` が便利   |
| スクリーンショット              | **MCP**      | `get_screenshot` で直接取得  |
| アセットダウンロード（SVG/PNG） | **REST API** | MCP にはエクスポート機能なし |
| 大規模な一括取得                | **REST API** | 複数ノードを一度に指定可能   |

### Step C: PAT（REST API）で精度補完（必要時）

- マスク/クリッピングの正確な幾何学情報
- MCP が Tailwind 変換した色・サイズの元の正確な値（RGB, px）
- 画像アセットの SVG/PNG ダウンロード
- 数値として取得できても、**見た目のレイアウト確定には必ずスクリーンショットを併用**する

**重要**:

- PAT で色・サイズ・padding・Auto Layout などの数値は取得できる
- ただし、実際の見た目の重なり順、中央寄せの成立方法、選択状態の視覚表現、オーバーレイの見え方は数値だけだと誤読しやすい
- そのため、**数値は PAT / MCP、見た目は screenshot** で確認し、両者が一致して初めて仕様として採用する

```bash
# 画像エクスポート（単体）
curl -s -H "X-Figma-Token: $FIGMA_PAT" \
  "https://api.figma.com/v1/images/{fileKey}?ids={nodeId}&format=svg"

# 複数アセットの一括ダウンロード（レート制限の節約に有効）
curl -s -H "X-Figma-Token: $FIGMA_PAT" \
  "https://api.figma.com/v1/images/{fileKey}?ids={id1},{id2},{id3}&format=svg"
```

### スクリーンショットの REST API 保存（MCP 代替）

MCP の `get_screenshot` が使えない場合の代替手段:

```bash
FILE_KEY="{Figma URL から抽出}"
NODE_ID="{node-id、ハイフンをそのまま使用}"

EXPORT_URL=$(curl -s -H "X-Figma-Token: $FIGMA_PAT" \
  "https://api.figma.com/v1/images/${FILE_KEY}?ids=${NODE_ID}&format=png&scale=2" \
  | python3 -c "import sys, json; d=json.load(sys.stdin); print(list(d['images'].values())[0])")

curl -s -o specs/design/images/{id}_{画面名}.png "$EXPORT_URL"
```

## ワークフロー

### Step 1: 画面設計書の読み込み

オーケストレータから受け取ったファイルパスで画面設計書を Read で読み込む。

**読み込むファイル**（パスはオーケストレータから受け取り済み）:

- `{id}_{画面名}.md` — メインの画面設計書
- `{id}_{画面名}_確認・調整事項.md` — 補足資料（存在する場合）

**読み込む内容**:

- 概要（画面ID、日本語名、英語名）
- Figma URL（node-id を含む）
- 項目一覧・アクション一覧・表示パターン
- 接続先 API
- 確認・調整事項（回答済み/未回答）

### Step 2: Figma 対象フレームの特定・検証

`resolve-figma-node` スキルを呼び出す:

- オーケストレータから受け取った Figma URL から nodeId を抽出
- PAT で Figma 側のフレーム名と照合
- 検証 OK → nodeId と Figma URL を確定
- 検証 NG → 名前ベースで検索、候補をユーザーに提示

### Step 3: MCP でデザイン情報取得

Desktop で対象が選択済みと分かっている場合は、まず nodeId なしで試す。
失敗した場合のみ nodeId 指定に切り替える。

1. `get_design_context(nodeId)` — レイアウト・スタイル情報
2. `get_metadata(nodeId)` — 大規模デザインの場合、ノード構造概要
3. `get_screenshot(nodeId)` — スクリーンショット（**必ず取得し目視確認**）
4. **個別要素のノードタイプ確認（必須）**:
   - `get_design_context` はマスク/クリッピング情報を正確に反映しない場合がある
   - 画像、アイコン、ボタンなど形状が重要な要素は `get_metadata` で個別確認
   - `ellipse` = 円形、`rectangle` = 四角形
5. 必要に応じて `get_variable_defs(nodeId)` — デザイントークン確認

**スクリーンショット確認で特に見るもの**:

- 視覚的な選択状態 / 非選択状態
- 要素の重なり順・オーバーレイ
- 中央揃えや左右対称が spacer / opacity / absolute 配置で実現されていないか
- コンポーネント名と実際の見た目が一致しているか

### Step 4: PAT で精度補完（必要時）

MCP の出力が不正確・不十分な場合:

- 正確な RGB 値、px 値が必要な場合
- アセット（SVG/PNG）のダウンロードが必要な場合
- MCP エラー時の代替手段

### Step 5: アセット確認

1. Figma デザインで使用されているアイコン・画像をリストアップ
2. プロジェクトのアセットディレクトリを確認する（CLAUDE.md またはプロジェクト規約から配置先を確認）
3. 不足アセットをリストアップし、必要に応じてダウンロード

```bash
# SVG ダウンロード
curl -s -H "X-Figma-Token: $FIGMA_PAT" \
  "https://api.figma.com/v1/images/{fileKey}?ids={nodeId}&format=svg" \
  | jq -r '.images["{nodeId}"]'
# → URL を取得して curl -o でダウンロード

# PNG（2x）ダウンロード
curl -s -H "X-Figma-Token: $FIGMA_PAT" \
  "https://api.figma.com/v1/images/{fileKey}?ids={nodeId}&format=png&scale=2"
```

### Step 6: デザイン仕様書作成

[references/design-spec-template.md](references/design-spec-template.md) のテンプレートに従って作成。

**必須記載事項**:

- 画面全体の **Figma URL**（ユーザーがブラウザで直接確認可能）
- 主要パーツごとの **nodeId と Figma URL**（個別確認用）
- スクリーンショット（`specs/design/images/` に保存して相対パスで参照）

**出力先**: `specs/design/{id}_デザイン仕様書.md`

### Step 7: 三点突合（必須レビュー）

以下の 3 つを突き合わせてレビュー:

1. **デザイン仕様書**（作成物）
2. **画面設計書**（入力）
3. **Figma**（get_screenshot で取得したスクリーンショット）

差異がある場合は修正し、再度突合する。
いずれかが取得できない場合は、その旨を報告して中断する。

## 重要な原則

### フォントはシステムフォント

- Figma のフォント（ヒラギノ等）は使用しない
- ウェイト・サイズ・line-height のみ記載
- JP/EN テキストスタイルを区別して記載

### パーツ名称は画面固有の具体名

- ❌ 一般的な名前: 「Title」「List」「Footer」
- ✅ 画面固有の名前: 「FilterSheetHeader」「YearSelectionList」

### コンポーネント名・コードは書かない

デザイン仕様書は「何を作るか」の文書。Flutter のクラス名やコードは書かない。

### レイアウト配置図を含める

アスキーアートで px 単位の正確な配置を表現。配置図だけで Figma を見なくてもレイアウトが再現できること。

### Figma のオートレイアウトを理解する

- Figma で「140px」と表示されていても、それは **結果としての幅** の場合がある
- 実装では **制約（hug / fill / fixed）** を再現すれば、幅は自動的に決まる
- デザイン仕様書には以下を区別して記載する:
  - `hug contents`: 内容に応じた幅（intrinsic width）
  - `fill`: 残りの幅を埋める（Expanded）
  - `fixed {n}px`: 固定幅
- パディングとギャップは正確に記載する（これがオートレイアウトの本質）

### 特殊な描画コードの記載例外

以下の条件を **両方満たす場合** に限り、Figma から取得したコードをデザイン仕様書に記載してよい:

1. **パーツレベルで手動実装が困難** — グラデーション、複雑なシャドウ、複雑なパス・シェイプ等
2. **Figma MCP からコードとして取得可能** — `get_design_context` の CSS/スタイル定義、SVG パスデータ等

通常のスタイル（単色、標準的なパディング等）は数値で記載し、コードは書かない。

### 推測で進めない

Figma MCP エラー時:

1. PAT でリトライを試みる
2. PAT でも失敗 → ユーザーに報告して中断
3. 不確かな情報でドキュメントを作成しない

PAT / MCP で数値が取れていても、スクリーンショットで見た目を確認していないレイアウトは「確定」とみなさない。

### 完全一致という表現の基準

以下をすべて満たした場合のみ「Figma と完全一致確認済み」と表現してよい:

1. Figma screenshot を取得済み
2. 実装後の画面 screenshot / 実機表示を確認済み
3. 主要要素（余白、色、タイポ、選択状態、重なり順）を突き合わせ済み

上記のいずれかが未実施の場合は、
「Figma を確認して仕様化済み」「仕様に沿って実装済み」「完全一致は未確認」
のように分けて報告する。

## よくある失敗パターン

1. **調整事項ファイルを読み込まない** — 未解決の質問があると実装が止まる。必ず両方のファイルを読み込む
2. **画面設計書に「WFなし」と書いてあると Figma MCP を試さない** — 実際にはデザインが存在する場合がある
3. **画面設計書の node-id をそのまま使用する** — node-id は古い可能性がある。`resolve-figma-node` で必ず検証する
4. **Figma MCP エラーを報告しない** — エラーを隠して進めると不正確なドキュメントになる
5. **デザイン仕様書にコンポーネント名を書いてしまう** — デザイン仕様書は「何を作るか」。Flutter のクラス名は実装設計書に記載する
6. **MCP ツールの実行順序を間違える** — 公式推奨: `get_design_context` → `get_metadata`（必要時）→ `get_screenshot`
7. **`get_design_context` の生成コードを鵜呑みにする** — マスク/クリッピング情報を正確に反映しない場合がある。形状が重要な要素は個別に `get_metadata` で確認必須

## 参照

- [デザイン仕様書テンプレート](references/design-spec-template.md)
- [figma-mcp-guide スキル](../figma-mcp-guide/SKILL.md) — Figma MCP ツール仕様
- [resolve-figma-node スキル](../resolve-figma-node/SKILL.md) — nodeId 発見・検証
