---
name: prepare-figma
description: Figma デザインからデザイン仕様書を作成する subagent スキル。PAT で対象フレームを特定し、MCP で詳細取得、PAT で精度補完。画面設計書の nodeId を信頼せず Figma で検証する。YAML レイアウト定義から AI 理解プレビューを自動生成し、Figma SS と並べて検証する。impl-issue の Phase 6 から呼び出される。
user-invocable: false
allowed-tools: Bash(curl *), Bash(echo *), Bash(jq *), Bash(python3 *), Bash(uv *), Bash(bash *), Bash(mkdir *), Bash(command *), Bash(which *), Bash(brew *), Read, Write, Edit, Glob, Grep, AskUserQuestion, Skill(resolve-figma-node), Skill(figma-mcp-guide), mcp__figma-dev-mode-mcp-server__get_design_context, mcp__figma-dev-mode-mcp-server__get_metadata, mcp__figma-dev-mode-mcp-server__get_screenshot, mcp__figma-dev-mode-mcp-server__get_variable_defs
---

# prepare-figma

Figma デザインからデザイン仕様書（What: 何を作るか）を作成する subagent スキル。

**作成するもの**: デザイン仕様書（`specs/design/{id}/デザイン仕様書.md`）
**作成しないもの**: 実装設計書（How: どう作るか）— ルール文書・類似PR・既存コードの調査後に作成するため

## 入力

オーケストレータ（impl-issue Phase 6）から以下を受け取る：

- **画面 ID**（例: `ei-gum_ホームタブ画面_LIMITED ITEMSタブ`）
- **画面設計書パス** — オーケストレータが Phase 2 で特定・読み込み済みのファイルパス
- **確認・調整事項パス**（任意）— 存在する場合のファイルパス
- **Figma URL** — 画面設計書に記載されていた Figma URL

## 出力

**重要**: 1 画面につき 1 ディレクトリ。画面 ID をディレクトリ名にして、配下に仕様書・画像・プレビューをまとめる。複数画面を扱う Issue でファイルが混ざらないようにするため。

```
specs/design/
└── {id}/                      # 画面 ID（例: fh-ccu）
    ├── デザイン仕様書.md       # 永続成果物（YAML レイアウト定義を含む）
    ├── images/                # Figma スクリーンショット類
    │   ├── 全体.png           # メイン SS（正）
    │   ├── 仕様注釈.png       # 補足画像（任意、用途名で識別）
    │   ├── スクロール時.png   # 補足画像（状態バリエーション等）
    │   └── ...
    └── previews/              # AI 理解プレビュー類（誤り検出用）
        ├── preview.png        # 撮影 PNG
        ├── preview.yaml       # 抽出された YAML（中間生成物、gitignore 推奨）
        └── preview.html       # レンダリング用 HTML（中間生成物、gitignore 推奨）
```

**命名規則**:

- ディレクトリ名は **画面 ID のみ**（`{id}_{画面名}` のように長くしない）。画面 ID で一意性が担保される。
- 仕様書ファイル名は **`デザイン仕様書.md` 固定**。ディレクトリ名で画面が特定されるため接頭辞は不要。
- メイン SS は **`images/全体.png` 固定**。補足画像は `images/{用途}.png`（仕様注釈、スクロール時、空状態など、用途を端的に表す名前）。
- プレビュー関連は **`previews/preview.*` 固定**。

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

curl -s -o specs/design/{id}/images/全体.png "$EXPORT_URL"
```

## ワークフロー

### Step 0: 前提条件チェック（必須・最初に実行）

prepare-figma が呼ばれた = Figma からの取り込みが必要、なので **このスキルに入った直後** に依存ツールの有無を確認する。
**AI は勝手にインストールしない**。不足があればユーザーに判断を仰ぐ。

#### チェック対象

| ツール                                 | 必須度 | 用途                            | チェックコマンド                                                                                          |
| -------------------------------------- | ------ | ------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Google Chrome / Chromium               | 必須   | プレビュー PNG 撮影             | `command -v google-chrome \|\| command -v chromium \|\| ls "/Applications/Google Chrome.app" 2>/dev/null` |
| `uv`（推奨）または PyYAML 入り Python3 | 必須   | YAML→HTML 変換 / PNG トリミング | `command -v uv \|\| python3 -c "import yaml, PIL" 2>/dev/null`                                            |

#### `uv` が無い場合

**自動インストールはしない**。以下を `AskUserQuestion` でユーザーに尋ねる：

```
プレビュー生成に `uv`（Python script runner）が必要ですが、見つかりませんでした。
どうしますか？

選択肢:
- A. 私（AI）が `brew install uv` を実行してインストールします
     → ユーザーがこれを選んだ場合のみ、AI は次のコマンドを Shell で実行する:
        brew install uv
- B. ユーザーが手動でインストールします（インストール後に「再開」と言ってください）
     → AI は待機。再開シグナルが来たら Step 0 から再チェック
- C. プレビュー生成をスキップして YAML だけ書きます
     → 視覚比較ループは行わない。仕様書末尾に「プレビュー未生成」と明記する
- D. 中断（このタスクを止める）
```

Linux ユーザーの場合、A の代替として `curl -LsSf https://astral.sh/uv/install.sh | sh` を提示する。

#### Chrome が無い場合

同様に `AskUserQuestion` で尋ねる（自動インストールはしない）：

```
プレビュー撮影に Chrome / Chromium が必要ですが見つかりませんでした。
どうしますか？

選択肢:
- A. ユーザーが手動でインストールします
- B. 環境変数 CHROME_BIN で別パスを指定する
- C. プレビュー生成をスキップ
- D. 中断
```

#### 既に揃っている場合

ログに「Step 0 OK: uv=found, chrome=found」と一行だけ出して即 Step 1 へ進む。

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
2. `packages/design_ui/res/assets/` の既存アセットを確認
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
- Figma スクリーンショット（`specs/design/{id}/images/全体.png` に保存して相対パスで参照）
- **レイアウト定義 YAML ブロック**（preview レンダリングの単一の真実）
  - スキーマは [references/preview-yaml-schema.md](references/preview-yaml-schema.md) を参照
  - **アスキーアート配置図は書かない**（廃止）
  - padding/gap/font 等のプロパティ詳細は YAML に集約し、テーブルとの重複を作らない

**出力先**: `specs/design/{id}/デザイン仕様書.md`

### Step 7: プレビュー生成（必須）

仕様書中の YAML から AI 理解プレビュー PNG を自動生成する。
**この PNG を Figma SS と並べて目視比較することで、AI の構造理解の誤りを早期発見する** のが目的。

```bash
mkdir -p specs/design/{id}/previews
bash "${CLAUDE_PLUGIN_ROOT}/skills/prepare-figma/scripts/render_preview.sh" \
  specs/design/{id}/デザイン仕様書.md \
  specs/design/{id}/previews \
  preview
```

成功すると以下の 3 ファイルが生成される:

- `specs/design/{id}/previews/preview.yaml` — 抽出された YAML
- `specs/design/{id}/previews/preview.html` — レンダリング用 HTML
- `specs/design/{id}/previews/preview.png` — 撮影された PNG

仕様書には PNG を相対パスで埋め込み、Figma SS と並べる（幅 320px で表示）:

```markdown
## 視覚比較

| Figma（正）                                           | AI 理解（プレビュー）                                        |
| ----------------------------------------------------- | ------------------------------------------------------------ |
| <img src="./images/全体.png" alt="Figma" width="320"> | <img src="./previews/preview.png" alt="Preview" width="320"> |
```

**前提条件**: Step 0 で確認済みの想定。
万一 Step 0 をスキップしていてここでエラーが出た場合は、**インストールを勝手に実行せず Step 0 に戻る**こと。
詳細は [scripts/README.md](scripts/README.md) 参照。

### Step 8: AI 自己検証ループ（必須）

**目的**: AI 自身が Figma SS と AI プレビュー PNG を見比べて構造的な誤りを発見し、YAML を直して再レンダリングすることを **構造差異がゼロになるまで繰り返す**。

このループの趣旨は単なるドキュメント比較ではなく、「AI が自分の理解を画像で外部化し、自分で答え合わせをする」自己検証。
ユーザーに渡す前に AI が必ず実行する。

#### ループの 1 イテレーション

1. **両画像を Read する**
   - Figma SS: `specs/design/{id}/images/全体.png`
   - AI プレビュー: `specs/design/{id}/previews/preview.png`

2. **差異を分類しながらリスト化する**

   各領域について、以下の 3 つのいずれかに分類する：

   | 分類                    | 判定基準                                                                                                                     | 扱い          |
   | ----------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ------------- |
   | **🔴 構造誤り**         | パーツ自体の有無、配置、サイズ感、形状の違い                                                                                 | YAML 修正対象 |
   | **🟡 データなし許容**   | アバター画像、ステータスバー、タブコンテンツ、ボトムナビ等の「データを持たないので Preview が placeholder になっている」箇所 | 無視          |
   | **🟢 ダミーデータ許容** | 「山田太郎」vs「名前名前」、行数や文字数の違い、自己紹介の長さ違い等                                                         | 無視          |

   **構造誤りの典型例**（実際に発見されたパターン）:

   - **パーツ抜け**: 仕様書テーブルにはあるのに YAML に書き忘れた要素（例: おすすめスタッフカードの身長行）
   - **形状解釈ミス**: アイコンを 20×90 の placeholder ボックス全体としてしまい、実際は 20×20 が右上配置だった等
   - **入れ子の取り違え**: vertical で並べるべきところを horizontal にしている等
   - **要素の数違い**: タブが Figma で 3 つだが YAML に 2 つしかない等

   **構造誤りでない例**:
   - Figma のアバター実写真 vs Preview の灰色丸（→ データなし）
   - Figma の「FREAK'S STORE」vs Preview の「SHOP NAME」（→ ダミー）
   - Figma の自己紹介 4 行 vs Preview の 3 行（→ ダミーの文字数違い）
   - 色がわずかに違う（仕様書のカラー定義通りなら無視）

3. **🔴 構造誤りがあれば YAML を修正する**

   仕様書 MD 内の `preview:` YAML ブロックを直接 Edit する。
   修正例（実例）:

   ```yaml
   # Before（誤り: 20×90 全体がアイコン placeholder になる）
   - id: favorite_button
     width: 20
     height: 90
     type: icon
     label: "♥"

   # After（正: 20×90 の container に 20×20 アイコンを上端配置）
   - id: favorite_button_area
     width: 20
     height: 90
     layout: vertical
     align: start
     children:
       - id: heart_icon
         width: 20
         height: 20
         type: icon
         label: "♥"
   ```

4. **プレビューを再生成する**

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/skills/prepare-figma/scripts/render_preview.sh" \
     specs/design/{id}/デザイン仕様書.md \
     specs/design/{id}/previews \
     preview
   ```

5. **1 に戻る**

#### ループ終了条件

- すべての差異が **🟡 データなし** または **🟢 ダミーデータ** に分類された
- すなわち **🔴 構造誤りがゼロ** になった

この時点で初めて、ユーザーレビュー（impl-issue Phase 7）に進む資格を得る。

#### 進めない場合

- Figma SS / プレビュー PNG のどちらかが取得できない → 中断して報告
- 同じ修正を繰り返しても構造誤りが解消しない（無限ループ徴候）→ 3 イテレーション以上回って改善が止まったら中断して報告
- YAML スキーマで表現できない要素（例: 特殊なグラデーション、複雑なマスク）→ 仕様書本文に補記し、構造誤り扱いから除外

#### 三点突合（並行して）

視覚比較ループと並行して、**画面設計書** および **デザイン仕様書の他セクション**（カラー表、フォント表、アクション一覧 等）も整合性確認する。
矛盾があれば仕様書テキストを修正する。

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

### レイアウト定義は YAML で書く（アスキーアート廃止）

レイアウトは `preview:` YAML ブロックで構造化して記述する。
これがプレビュー画像生成の唯一の入力なので、YAML が正確であれば prevew も正確に出る。

- 親子関係を `children:` で表現
- `width: fill / hug / Npx` で Figma Auto Layout 制約を再現
- `layout: vertical | horizontal` で並び方向を指定（**Figma の `stack`（オーバーレイ配置）は現時点で未対応** — 子要素を重ねるレイアウトはプレビュー再現できない。詳細は [`references/preview-yaml-schema.md`](references/preview-yaml-schema.md) を参照）
- パーツ単位のプロパティ（padding/gap/font 等）は YAML 内に集約し、テーブルと重複させない

スキーマの詳細は [references/preview-yaml-schema.md](references/preview-yaml-schema.md) を参照。

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
8. **アスキーアート配置図を書いてしまう（廃止済み）** — レイアウトは YAML が単一の真実。アスキーアートは禁止
9. **プレビュー生成をスキップする** — `render_preview.sh` の実行は必須。生成された PNG を Figma SS と並べて見比べないと AI の理解違いが残る
10. **YAML とテーブルに同じプロパティを二重に書く** — padding/gap/font は YAML だけに書く。テーブルは Figma 参照と役割の説明のみ

## 参照

- [デザイン仕様書テンプレート](references/design-spec-template.md)
- [Preview YAML スキーマ](references/preview-yaml-schema.md)
- [プレビュー生成スクリプト](scripts/README.md)
- [figma-mcp-guide スキル](../figma-mcp-guide/SKILL.md) — Figma MCP ツール仕様
- [resolve-figma-node スキル](../resolve-figma-node/SKILL.md) — nodeId 発見・検証
