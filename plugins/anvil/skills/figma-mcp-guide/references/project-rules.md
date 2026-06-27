# Flutter プロジェクト固有の Figma MCP ルール

本プロジェクト（DaytonaPark）で Figma MCP を使用する際の固有ルール。

## フォントルール

### フォントファミリーはシステムフォントを使用

Figma のフォントファミリー（Hiragino Kaku Gothic Pro, SF Pro 等）は **使用しない**。
iOS / Android で動作するため、システムフォントを使用する。

Figma から参照するのは **ウェイト（太さ）・サイズ・line-height** のみ。

### JP/EN テキストスタイルの区別

Figma のテキストスタイルは JP（日本語）と EN（英語）で分離定義されている。

```
JP/body/Body2_14R: Hiragino Kaku Gothic Pro W3, 14px, weight 300, lineHeight 20px
EN/Label/Label_14R: SF Pro Regular, 14px, weight 400, lineHeight 1
```

**Flutter での使い分け**:

| テキスト内容                         | 使用するテーマ               | 例                           |
| ------------------------------------ | ---------------------------- | ---------------------------- |
| 日本語を含む                         | `context.appTextThemeJP.xxx` | 「カラーをまとめる」         |
| 英数字のみ（価格、件数、ブランド名） | `context.appTextThemeEN.xxx` | 「¥1,980」「URBAN RESEARCH」 |

## デザイントークンマッピング

Figma 変数名から Flutter テーマ定義への対応:

| カテゴリ   | Figma 変数パターン      | Flutter テーマ                    |
| ---------- | ----------------------- | --------------------------------- |
| 背景色     | `var(--background/xxx)` | `context.appBackgroundColors.xxx` |
| ボタン色   | `var(--button/xxx)`     | `context.appButtonColors.xxx`     |
| テキスト色 | `var(--text/xxx)`       | `context.appTextColors.xxx`       |
| アイコン色 | `var(--icon/xxx)`       | `context.appIconColors.xxx`       |

**禁止**: `Colors.white`, `Color(0xFFxxxxxx)`, `TextStyle(fontSize: xx)` 等のハードコード

## アセット管理

### アイコン

- **禁止**: `Icons.tune`, `Icons.sort` 等の `IconData`
- **使用**: `CommonAssets.res.assets.{iconName}.svg()`
- 色変更時: `colorFilter: ColorFilter.mode(iconColors.primary, BlendMode.srcIn)`
- 既存アセット: `packages/design_ui/res/assets/`

### アセットダウンロード

MCP にはエクスポート機能がないため、アセットダウンロードは **Figma REST API** を使用:

```bash
# SVG
curl -s -H "X-Figma-Token: $FIGMA_PAT" \
  "https://api.figma.com/v1/images/{file_key}?ids={node_id}&format=svg"

# PNG（2x）
curl -s -H "X-Figma-Token: $FIGMA_PAT" \
  "https://api.figma.com/v1/images/{file_key}?ids={node_id}&format=png&scale=2"

# 複数アセット一括
curl -s -H "X-Figma-Token: $FIGMA_PAT" \
  "https://api.figma.com/v1/images/{file_key}?ids={id1},{id2},{id3}&format=svg"
```

### UI 文字列

- **禁止**: `Text('タイトル')` 等のハードコード
- **使用**: slang（`final t = Translations.of(context); Text(t.myFeature.title)`）

## Figma MCP 使用上の注意

### get_design_context のマスク/クリッピング問題

生成コードはマスク/クリッピング情報を正確に反映しない場合がある。

| 要素            | 確認方法       | get_metadata で見るべきノードタイプ    |
| --------------- | -------------- | -------------------------------------- |
| 画像/サムネイル | 円形 or 四角形 | `ellipse` = 円形, `rectangle` = 四角形 |
| アイコン        | 形状とサイズ   | `vector`, `group`, `frame`             |
| ボタン/カード   | border-radius  | `rectangle` の cornerRadius            |

**→ 形状が重要な要素は `get_metadata` で個別にノードタイプを確認すること。**

### node-id の鮮度

画面設計書に記載された node-id は **古い可能性** がある。

| MCP 方式    | 推奨手順                                                                    |
| ----------- | --------------------------------------------------------------------------- |
| Desktop MCP | Figma で選択 → nodeId なしで `get_design_context` 実行                      |
| Remote MCP  | Figma で右クリック →「選択範囲のリンクをコピー」→ 最新 URL から nodeId 取得 |

### エラー時の対応

1. **必ずユーザーに報告する** - エラーを隠さない
2. **不確かな情報で進めない** - MCP 失敗時に推測でドキュメント/実装を作成しない
3. **代替手段を試す** - REST API での取得を試みる
4. **検証不十分なら中断** - 「Figma 情報を取得できませんでした」と報告する
