# デザイン仕様書テンプレート

以下のテンプレートに従ってデザイン仕様書を作成する。

## ディレクトリ構成（必須）

1 画面 = 1 ディレクトリ。複数画面で混在しないように **画面 ID をディレクトリ名** にし、配下に仕様書・画像・プレビューをまとめる。

```
specs/design/
└── {id}/                    # 画面 ID（例: fh-ccu）
    ├── デザイン仕様書.md
    ├── images/              # Figma SS
    │   ├── 全体.png         # メイン SS（固定名）
    │   └── {用途}.png       # 補足画像（任意）
    └── previews/            # AI 理解プレビュー
        ├── preview.png
        ├── preview.yaml     # gitignore 推奨
        └── preview.html     # gitignore 推奨
```

- ディレクトリ名: 画面 ID のみ。長くしない。
- 仕様書ファイル名: **`デザイン仕様書.md` 固定**（接頭辞なし）。
- メイン SS: **`images/全体.png` 固定**。補足画像は `images/{用途}.png`。
- プレビュー: **`previews/preview.*` 固定**。
- 仕様書内のパスは **すべて相対パス**（`./images/全体.png` など）。

## 構成方針

デザイン仕様書は **4 種類の情報** で構成される：

| 種類                       | 形式              | 役割                                                                     |
| -------------------------- | ----------------- | ------------------------------------------------------------------------ |
| ① Figma スクリーンショット | PNG               | あるべき姿（グラウンドトゥルース）                                       |
| ② AI 生成プレビュー        | PNG               | AI が YAML から解釈した姿（誤り検出用、`render_preview.sh` で自動生成）  |
| ③ レイアウト定義           | YAML（MD 内埋込） | AI が読み取った構造化レイアウト（プレビュー生成元）                      |
| ④ 仕様テーブル群           | Markdown テーブル | パーツ一覧、カラー、フォント、アクション、状態バリエーション、アセット等 |

**重要原則**:

- **アスキーアートは廃止**。配置構造は ③ YAML が単一の真実
- ② プレビューは ③ YAML から自動生成。手で書かない
- ① と ② を**並べて目視比較**することで、AI の理解違いを発見する
- **Figma node の存在だけで YAML に書かない**: コンポーネント流用で `visible=false` の未使用パーツが残る。`get_screenshot` に写っているものだけを YAML・仕様に含める

## テンプレート

```markdown
# {画面名} デザイン仕様書

## 概要

| 項目          | 内容                          |
| ------------- | ----------------------------- |
| 画面ID        | {id}                          |
| 日本語名      | {名前}                        |
| 英語名        | {EnglishName}                 |
| Figma URL     | [{node-id}]({Figma URL})      |
| Figma node-id | {node-id}                     |
| 画面設計書    | [{ファイル名}]({パス})        |
| 調整事項      | [{ファイル名}]({パス})        |
| 接続先API     | {API ID + 名称}（必要な場合） |

## 視覚比較（必ず並べてレビュー）

レビュー時は **左右を必ず見比べて差異を洗い出す**。差異があれば YAML を修正して再生成する。

| Figma（正）                                           | AI 理解（プレビュー）                                        |
| ----------------------------------------------------- | ------------------------------------------------------------ |
| <img src="./images/全体.png" alt="Figma" width="320"> | <img src="./previews/preview.png" alt="Preview" width="320"> |

> プレビュー再生成: `bash "${CLAUDE_PLUGIN_ROOT}/skills/prepare-figma/scripts/render_preview.sh" specs/design/{id}/デザイン仕様書.md specs/design/{id}/previews preview`

### 参考画像（任意）

スクロール挙動・状態バリエーション・仕様注釈等の補足画像がある場合、ここに **縦に並べて** 各 320px 幅で貼る。テーブルにすると説明列が押し縮められて読みづらいため避ける。

#### {補足画像のタイトル}

<img src="./images/{用途}.png" alt="{用途}" width="320">

- 補足説明 1
- 補足説明 2

## 画面の目的・用途

（画面設計書から読み取った内容）

## 未解決の調整事項

（調整事項ファイルから未回答の項目を抽出。なければ「なし」と記載）

| 項目ID | 項目名 | 質問内容 | 影響範囲 |
| ------ | ------ | -------- | -------- |

## レイアウト仕様

### レイアウト定義（YAML）

下記 YAML がプレビュー画像の生成元。AI はこれを唯一の構造定義として書き、テキストとして個別のパーツ説明は不要。

スキーマ詳細は `/anvil:prepare-figma` SKILL の `references/preview-yaml-schema.md` を参照。

```yaml
preview:
  meta:
    title: "{画面名}"
    viewport:
      width: 390
    background: "#f7f7f7"

  root:
    layout: vertical
    children:
      - id: {パーツ名1}
        # ... プロパティ
        children:
          - id: {子パーツ}
            # ... プロパティ
```

### パーツ一覧

YAML 内の各パーツに対応する Figma nodeId 参照テーブル。

| パーツ名     | 役割   | サイズ    | Figma nodeId            |
| ------------ | ------ | --------- | ----------------------- |
| {PartsName1} | {役割} | {W}×{H}px | [{nodeId}]({Figma URL}) |
| {PartsName2} | {役割} | {W}×{H}px | [{nodeId}]({Figma URL}) |

**注**: パーツのプロパティ詳細（padding/gap/font 等）は YAML が正。本テーブルは Figma 参照と役割の説明のみ。

## カラーパレット

| 用途       | Figma 変数名 | 値          |
| ---------- | ------------ | ----------- |
| 背景       | {変数名}     | `#{xxxxxx}` |
| テキスト   | {変数名}     | `#{xxxxxx}` |
| ボタン背景 | {変数名}     | `#{xxxxxx}` |

## フォントスタイル

Figma のテキストスタイルは JP（日本語）と EN（英語）で分離定義されています。

| 用途   | 言語 | サイズ   | ウェイト | 行高   | letter-spacing |
| ------ | ---- | -------- | -------- | ------ | -------------- |
| {用途} | JP   | {size}px | {weight} | {lh}px | {ls}           |
| {用途} | EN   | {size}px | {weight} | {lh}px | {ls}           |

**注記**: 実装時はシステムフォントを使用。フォントファミリーは記載しない。

## 動作・インタラクション

### アクション一覧

| アクション | トリガー  | 結果     |
| ---------- | --------- | -------- |
| {action}   | {trigger} | {result} |

### 状態バリエーション

プレビューは既定状態のみ生成する。他状態は本テーブルで記述する。

| 状態       | 変化内容 | Figma nodeId      |
| ---------- | -------- | ----------------- |
| デフォルト | —        | [{nodeId}]({URL}) |
| 選択時     | {変化}   | [{nodeId}]({URL}) |
| 無効時     | {変化}   | [{nodeId}]({URL}) |

## 必要なアセット

| アセット   | 用途   | 状態                  | nodeId   |
| ---------- | ------ | --------------------- | -------- |
| {icon.svg} | {用途} | 既存 / 要ダウンロード | {nodeId} |

## 特殊な描画（Figma から取得）

（グラデーション等、YAML では表現できないスタイルがある場合のみ記載）

## 備考

（その他の注意事項）
```

## 記載ルール

1. **Figma URL を必ず記載** — 概要テーブルに画面全体の URL、パーツ一覧に各パーツの URL
2. **パーツ名は画面固有の具体名** — 「Title」ではなく「LimitedItemsHeader」等
3. **フォントファミリーは書かない** — ウェイト・サイズ・line-height のみ
4. **JP/EN テキストスタイルを区別** — 同じサイズでもウェイトが異なる場合がある
5. **コンポーネント名・コードは書かない** — デザイン仕様書は「何を作るか」の文書
6. **hug / fill / fixed を区別** — Figma のオートレイアウト制約を YAML に正確に反映
7. **アスキーアートは書かない** — 配置構造は YAML が単一の真実
8. **YAML とパーツ別仕様の重複を避ける** — padding/gap 等は YAML だけに書く。テーブルは Figma nodeId 参照と役割の説明のみ
9. **画像は必ず `<img width="320">` で幅指定する** — `![alt](src)` だとオリジナルサイズで表示され、テーブル内で押し縮められたり巨大になったりして読めない。モバイル UI のスクリーンショットは 320px 幅が読みやすい（必要なら 400px まで許容）

## YAML スキーマの最小例

```yaml
preview:
  meta:
    title: "サンプル画面"
    viewport: { width: 390 }
    background: "#f7f7f7"
  root:
    layout: vertical
    children:
      - id: header
        height: 56
        padding: 16
        background: "#ffffff"
        layout: horizontal
        align: center
        children:
          - id: title
            type: text
            content: "タイトル"
            font: { size: 16, weight: 600, color: "#222222", line_height: 24 }
      - id: body
        padding: 16
        layout: vertical
        gap: 12
        children:
          - id: card
            padding: 16
            background: "#ffffff"
            border_radius: 8
            border: { width: 1, color: "#e5e5e5" }
            children:
              - id: card_text
                type: text
                content: "カードの内容"
                font: {
                  size: 14,
                  weight: 400,
                  color: "#222222",
                  line_height: 20,
                }
```

詳細は [preview-yaml-schema.md](preview-yaml-schema.md) 参照。
