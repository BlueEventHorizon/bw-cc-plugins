# Preview YAML スキーマ

デザイン仕様書のレイアウトを YAML で表現するためのスキーマ定義。
この YAML は `yaml_to_html.py` で HTML に変換され、Chromium で PNG にレンダリングされる。
目的は **AI の理解を視覚化し、Figma スクリーンショットと並べて誤りを暴く** こと。

## 設計方針

- **Figma の Auto Layout 概念をそのまま素直にマッピングする**
  - `hug` / `fill` / `fixed` は Figma 用語をそのまま使う
  - HTML/CSS の Flexbox は Figma Auto Layout とほぼ等価なので、忠実に変換可能
- **ピクセル等価は目指さない**
  - フォントレンダリング、サブピクセルのずれは許容（用途は構造検証）
  - 色・余白・サイズの **大局** が合っていれば OK
- **状態バリエーションは別 YAML にしない**
  - 既定状態（デフォルト）のみプレビューを生成する
  - 状態差分は仕様書のテキストで表現する

## トップレベル構造

```yaml
preview:
  meta:
    title: "<画面名>" # 任意（ページタイトルに使う）
    viewport:
      width: 390 # ビューポート幅（px）。デフォルト 390
    background: "#f7f7f7" # 画面背景色

  root:
    # 任意のパーツノード（後述）
    layout: vertical
    children: [...]
```

## パーツノードの構造

```yaml
- id: <パーツ名>                       # 必須。仕様書のパーツ名と一致させる
  type: container | text | icon | image | placeholder   # 省略時は container

  # サイズ（Figma Auto Layout 用語）
  width: fill | hug | <N>              # fill=残幅, hug=内容, N=N px
  height: fill | hug | <N>

  # スタイル
  background: "#xxxxxx"
  border: { width: <N>, color: "#xxxxxx" }
  border_bottom: { width: <N>, color: "#xxxxxx" }
  border_radius: <N>
  shape: rect | circle                 # circle は border-radius: 50%

  # レイアウト（子要素の並べ方）
  layout: vertical | horizontal
  # ※ Figma の "stack"（子要素を重ねるオーバーレイ配置）は現時点で未対応。
  #    必要になれば子要素側に absolute 配置 + top/left プロパティを追加して実装する。
  gap: <N>                             # 子要素間の隙間（px）
  padding: <N> | { top: <N>, right: <N>, bottom: <N>, left: <N> }
  align: start | center | end          # クロス軸の揃え方
  justify: start | center | end | space_between  # メイン軸の揃え方
  scroll: horizontal | vertical        # スクロール方向

  # コンテンツ（葉ノード用）
  content: "<テキスト内容>"            # type=text のとき
  label: "<プレースホルダー表示文字>"  # type=icon/image/placeholder のとき
  font:
    size: <N>
    weight: <100..900>
    color: "#xxxxxx"
    line_height: <N>
    letter_spacing: <N>

  # 子要素
  children:
    - id: <子1>
      ...
```

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

```yaml
- id: container
  layout: vertical
  gap: 8
  padding: 16
  children:
    - id: itemA
      ...
    - id: itemB
      ...
```

### 横並び（horizontal row）

```yaml
- id: row
  layout: horizontal
  gap: 16
  align: center        # 縦方向の揃え方
  children:
    - id: left
      ...
    - id: right
      width: hug       # 内容幅
      ...
```

### 円形画像

```yaml
- id: avatar
  type: image
  width: 88
  height: 88
  shape: circle
  label: "img"
```

### テキスト

```yaml
- id: title
  type: text
  content: "スタッフ名"
  font:
    size: 14
    weight: 600
    color: "#222222"
    line_height: 20
```

### スクロール領域

```yaml
- id: list
  height: 166
  layout: horizontal
  gap: 8
  scroll: horizontal
  children:
    - id: card1
      width: 104
      ...
    - id: card2
      width: 104
      ...
```

## アンチパターン

### ❌ コンポーネント名やコードを書く

```yaml
- id: LineButton # ❌ Flutter のコンポーネント名は書かない
  type: ElevatedButton # ❌
```

→ パーツ名は画面固有の論理名（`line_button`、`btn_area` など）にする。
コンポーネント名は実装設計書の責務。

### ❌ 状態バリエーションを 1 つの YAML に詰める

```yaml
- id: heart_button
  states: # ❌ サポートしない
    default: { color: "#000" }
    active: { color: "#e34234" }
```

→ プレビューは既定状態のみ。状態差分は仕様書テキストで記述。

### ❌ `hug` を使えばいいのに `<N>` で固定する

```yaml
- id: badge
  width: 183 # ❌ Figma で「結果として 183px」表示されただけ
```

→ オートレイアウトの本質である `hug` を優先して指定する。
固定幅が必要なときだけ `<N>` を使う。

## 変換例（参考）

| YAML                                              | HTML/CSS                                       |
| ------------------------------------------------- | ---------------------------------------------- |
| `layout: vertical, gap: 8`                        | `display:flex; flex-direction:column; gap:8px` |
| `width: fill`（horizontal 親内）                  | `flex:1; min-width:0`                          |
| `padding: 16`                                     | `padding: 16px`                                |
| `padding: { top:8, right:16, bottom:8, left:16 }` | `padding: 8px 16px 8px 16px`                   |
| `shape: circle, width: 88, height: 88`            | `border-radius:50%; width:88px; height:88px`   |
| `border: { width: 1, color: "#e34234" }`          | `border: 1px solid #e34234`                    |

詳細な変換ロジックは `scripts/yaml_to_html.py` を参照。
