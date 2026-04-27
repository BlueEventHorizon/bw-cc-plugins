# プロジェクト固有の Figma MCP ルール（テンプレート）

このファイルは各プロジェクトでカスタマイズするためのテンプレートです。
プロジェクトに合わせて内容を書き換えてください。

## フォントルール

### フォントファミリーはシステムフォントを使用

Figma のフォントファミリーは **使用しない**。
プラットフォーム（iOS / Android / macOS / Web 等）のシステムフォントを使用する。

Figma から参照するのは **ウェイト（太さ）・サイズ・line-height** のみ。

### JP/EN テキストスタイルの区別（プロジェクトに JP/EN 分離がある場合）

Figma のテキストスタイルに JP / EN の区別がある場合は、プロジェクトの命名規則に対応させる。

## デザイントークンマッピング

Figma 変数名からプロジェクトのテーマ定義への対応はプロジェクト規約を参照すること。

**禁止**: 色・サイズ等のハードコード。プロジェクトのデザイントークンを使用する。

## アセット管理

### アイコン

プロジェクト規約に従ったアイコン参照方法を使用する。

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

プロジェクトの i18n / 文字列管理方法に従う。文字列のハードコード禁止。

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
