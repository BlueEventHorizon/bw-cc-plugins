# Preview JSON スキーマ

デザイン仕様書のレイアウトを JSON で表現するためのスキーマ定義。
この JSON は `json_to_html.py` で HTML に変換され、Chromium で PNG にレンダリングされる。
目的は **AI の理解を視覚化し、Figma スクリーンショットと並べて誤りを暴く** こと。

## 設計方針

- **Figma の Auto Layout 概念をそのまま素直にマッピングする**
  - `hug` / `fill` / `fixed` は Figma 用語をそのまま使う
  - HTML/CSS の Flexbox は Figma Auto Layout とほぼ等価なので、忠実に変換可能
- **ピクセル等価は目指さない**
  - フォントレンダリング、サブピクセルのずれは許容（用途は構造検証）
  - 色・余白・サイズの **大局** が合っていれば OK
- **状態バリエーションは別 JSON にしない**
  - 既定状態（デフォルト）のみプレビューを生成する
  - 状態差分は仕様書のテキストで表現する

## トップレベル構造

```json
{
  "preview": {
    "meta": {
      "title": "<画面名>",
      "viewport": { "width": 390 },
      "background": "#f7f7f7"
    },
    "root": {
      "layout": "vertical",
      "children": ["..."]
    }
  }
}
```

| フィールド            | 必須 | 説明                                 |
| --------------------- | ---- | ------------------------------------ |
| `meta.title`          | 任意 | ページタイトルに使う                 |
| `meta.viewport.width` | 任意 | ビューポート幅（px）。デフォルト 390 |
| `meta.background`     | 任意 | 画面背景色                           |
| `root`                | 必須 | 任意のパーツノード（後述）           |

## パーツノードの構造

```json
{
  "id": "<パーツ名>",
  "type": "container",

  "width": "<fill|hug|N>",
  "height": "<fill|hug|N>",

  "background": "#xxxxxx",
  "border": { "width": 1, "color": "#xxxxxx" },
  "border_bottom": { "width": 1, "color": "#xxxxxx" },
  "border_radius": 8,
  "shape": "rect",

  "layout": "vertical",
  "gap": 8,
  "padding": { "top": 8, "right": 16, "bottom": 8, "left": 16 },
  "align": "center",
  "justify": "space_between",
  "scroll": "vertical",

  "content": "<テキスト内容>",
  "label": "<プレースホルダー表示文字>",
  "font": {
    "size": 14,
    "weight": 600,
    "color": "#xxxxxx",
    "line_height": 20,
    "letter_spacing": 0
  },

  "children": [{ "id": "<子1>" }]
}
```

| フィールド         | 許容値                                                      | 必須・任意                            | 説明                                                                                                                                                             |
| ------------------ | ----------------------------------------------------------- | ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`               | 文字列                                                      | 必須                                  | 仕様書のパーツ名と一致させる                                                                                                                                     |
| `type`             | `container` \| `text` \| `icon` \| `image` \| `placeholder` | 任意（省略時 `container`）            | パーツ種別                                                                                                                                                       |
| `width` / `height` | `fill` \| `hug` \| 数値（N）                                | 任意                                  | `fill`=残幅, `hug`=内容, N=N px                                                                                                                                  |
| `background`       | `"#xxxxxx"`                                                 | 任意                                  | 背景色                                                                                                                                                           |
| `border`           | `{ width, color }`                                          | 任意                                  | 枠線                                                                                                                                                             |
| `border_bottom`    | `{ width, color }`                                          | 任意                                  | 下枠線のみ                                                                                                                                                       |
| `border_radius`    | 数値                                                        | 任意                                  | 角丸半径（px）                                                                                                                                                   |
| `shape`            | `rect` \| `circle`                                          | 任意                                  | `circle` は `border-radius: 50%`                                                                                                                                 |
| `layout`           | `vertical` \| `horizontal`                                  | 任意                                  | 子要素の並べ方。Figma の `stack`（子要素を重ねるオーバーレイ配置）は現時点で未対応。必要になれば子要素側に absolute 配置 + top/left プロパティを追加して実装する |
| `gap`              | 数値                                                        | 任意                                  | 子要素間の隙間（px）                                                                                                                                             |
| `padding`          | 数値 または `{ top, right, bottom, left }`                  | 任意                                  | 内側余白                                                                                                                                                         |
| `align`            | `start` \| `center` \| `end`                                | 任意                                  | クロス軸の揃え方                                                                                                                                                 |
| `justify`          | `start` \| `center` \| `end` \| `space_between`             | 任意                                  | メイン軸の揃え方                                                                                                                                                 |
| `scroll`           | `horizontal` \| `vertical`                                  | 任意                                  | スクロール方向                                                                                                                                                   |
| `content`          | 文字列                                                      | `type: text` のとき                   | テキスト内容                                                                                                                                                     |
| `label`            | 文字列                                                      | `type: icon/image/placeholder` のとき | プレースホルダー表示文字                                                                                                                                         |
| `font`             | `{ size, weight, color, line_height, letter_spacing }`      | 任意                                  | フォントスタイル                                                                                                                                                 |
| `children`         | 配列（パーツノードの再帰）                                  | 任意                                  | 子要素                                                                                                                                                           |

## サイズの解釈

| 値         | 親レイアウト | CSS マッピング                          |
| ---------- | ------------ | --------------------------------------- |
| `fill`     | horizontal   | `flex: 1; min-width: 0`                 |
| `fill`     | vertical     | `width: 100%`（または `flex: 1` for h） |
| `hug`      | -            | サイズ指定なし（内容に応じる）          |
| `<N>` (px) | -            | `width/height: Npx; flex-shrink: 0`     |

**重要**: `width: fill` を horizontal レイアウトで使うときは、兄弟の `fill` がない場合のみフルに広がる。
複数の `fill` がある場合は等分される（Flexbox の挙動）。

## 主要パターン

### 縦並び（vertical stack）

```json
{
  "id": "container",
  "layout": "vertical",
  "gap": 8,
  "padding": 16,
  "children": [{ "id": "itemA" }, { "id": "itemB" }]
}
```

### 横並び（horizontal row）

```json
{
  "id": "row",
  "layout": "horizontal",
  "gap": 16,
  "align": "center",
  "children": [
    { "id": "left" },
    { "id": "right", "width": "hug" }
  ]
}
```

### 円形画像

```json
{
  "id": "avatar",
  "type": "image",
  "width": 88,
  "height": 88,
  "shape": "circle",
  "label": "img"
}
```

### テキスト

```json
{
  "id": "title",
  "type": "text",
  "content": "スタッフ名",
  "font": { "size": 14, "weight": 600, "color": "#222222", "line_height": 20 }
}
```

### スクロール領域

```json
{
  "id": "list",
  "height": 166,
  "layout": "horizontal",
  "gap": 8,
  "scroll": "horizontal",
  "children": [
    { "id": "card1", "width": 104 },
    { "id": "card2", "width": 104 }
  ]
}
```

## アンチパターン

### コンポーネント名やコードを書く

```json
{ "id": "LineButton", "type": "ElevatedButton" }
```

Flutter のコンポーネント名（`LineButton`）や `type` への実装クラス名（`ElevatedButton`）は書かない。
パーツ名は画面固有の論理名（`line_button`、`btn_area` など）にする。
コンポーネント名は実装設計書の責務。

### 状態バリエーションを 1 つの JSON に詰める

```json
{
  "id": "heart_button",
  "states": { "default": { "color": "#000" }, "active": { "color": "#e34234" } }
}
```

`states` はサポートしない。プレビューは既定状態のみ。状態差分は仕様書テキストで記述する。

### `hug` を使えばいいのに `<N>` で固定する

```json
{ "id": "badge", "width": 183 }
```

Figma で「結果として 183px」表示されただけの値をそのまま固定幅にしない。
オートレイアウトの本質である `hug` を優先して指定する。固定幅が必要なときだけ `<N>` を使う。

## 変換例（参考）

| JSON                                                            | HTML/CSS                                       |
| --------------------------------------------------------------- | ---------------------------------------------- |
| `"layout": "vertical", "gap": 8`                                | `display:flex; flex-direction:column; gap:8px` |
| `"width": "fill"`（horizontal 親内）                            | `flex:1; min-width:0`                          |
| `"padding": 16`                                                 | `padding: 16px`                                |
| `"padding": { "top": 8, "right": 16, "bottom": 8, "left": 16 }` | `padding: 8px 16px 8px 16px`                   |
| `"shape": "circle", "width": 88, "height": 88`                  | `border-radius:50%; width:88px; height:88px`   |
| `"border": { "width": 1, "color": "#e34234" }`                  | `border: 1px solid #e34234`                    |

詳細な変換ロジックは `scripts/json_to_html.py` を参照。
