---
name: figma-mcp-guide
description: Figma MCP サーバーの公式知識ベース。get_design_context や get_screenshot 等のツール仕様、デザインコンテキスト取得、セットアップ、Flutter プロジェクト固有ルール（デザイントークン、フォント、アセット管理）を参照したい時に使用する。
user-invocable: false
---

# Figma MCP ガイド

Figma 公式 MCP サーバーの知識ベース。UI 実装ワークフローで Figma デザインからコンテキストを取得する際のリファレンス。

## 接続方式

| 項目             | Remote MCP                        | Desktop MCP                                      |
| ---------------- | --------------------------------- | ------------------------------------------------ |
| エンドポイント   | `https://mcp.figma.com/mcp`       | `http://127.0.0.1:3845/mcp`                      |
| コンテキスト指定 | リンクベース（URL / nodeId 必須） | 選択ベース（Figma で選択したレイヤーを自動認識） |
| Figma Desktop    | 不要                              | 必須（起動 + Dev Mode 有効化）                   |
| レート制限       | プランに依存（後述）              | Dev/Full seat: Tier 1 API と同等                 |

### セットアップ（Claude Code）

```bash
# リモートサーバー
claude mcp add --transport http figma https://mcp.figma.com/mcp
# グローバル設定の場合
claude mcp add --transport http figma https://mcp.figma.com/mcp --scope user

# デスクトップサーバー
claude mcp add --transport http figma-desktop http://127.0.0.1:3845/mcp
```

認証: `/mcp` → figma 選択 → Authenticate → Allow Access

## ツール一覧

全 13 ツール。詳細は [tools-reference.md](references/tools-reference.md) を参照。

### デザイン → コード（主要ツール）

| ツール               | 用途                                                   | 推奨順序        |
| -------------------- | ------------------------------------------------------ | --------------- |
| `get_design_context` | レイアウト・スタイル情報を React + Tailwind 形式で取得 | 1. 最初に実行   |
| `get_metadata`       | ノード構造の XML 概要（大規模デザイン向け）            | 2. 必要時       |
| `get_screenshot`     | スクリーンショット取得（レイアウト忠実性の確認）       | 3. 視覚確認     |
| `get_variable_defs`  | 色・spacing・typography の変数・スタイル抽出           | 4. トークン確認 |

### Code Connect

| ツール                         | 用途                                                   |
| ------------------------------ | ------------------------------------------------------ |
| `get_code_connect_map`         | Figma ノード ID とコードコンポーネントのマッピング取得 |
| `add_code_connect_map`         | マッピング追加                                         |
| `get_code_connect_suggestions` | マッピング候補の自動検出・提案                         |
| `send_code_connect_mappings`   | マッピング送信                                         |
| `create_design_system_rules`   | エージェント向けデザインシステムルール生成             |

### その他

| ツール                  | 用途                            | 備考                              |
| ----------------------- | ------------------------------- | --------------------------------- |
| `generate_figma_design` | UI → Figma デザインレイヤー変換 | Claude Code 専用・リモートのみ    |
| `get_figjam`            | FigJam 図を XML 形式で取得      | FigJam 対応                       |
| `generate_diagram`      | Mermaid → FigJam 図生成         | Flowchart, Gantt, State, Sequence |
| `whoami`                | 認証ユーザー情報取得            | リモートのみ                      |

## Flutter プロジェクトでの使い方

プロジェクト固有のルール（デザイントークン、フォント、アセット管理等）は [project-rules.md](references/project-rules.md) を参照。

### 関連 UI ワークフロー（impl-issue スキル）

| Phase    | 役割                       | リファレンス                 |
| -------- | -------------------------- | ---------------------------- |
| Phase 6  | Figma → デザイン仕様書作成 | `prepare-figma` スキル       |
| Phase 8  | 仕様書 → 実装設計書作成    | `impl-design-rules.md`       |
| Phase 11 | 実装設計書 → UI 実装       | `ui-implementation-rules.md` |
| Phase 12 | 実装後の三点突合検証       | `ui-review-rules.md`         |

### MCP ツール呼び出し時の引数

```
server: user-figma-remote-mcp  (または figma-dev-mode-mcp-server)
arguments: {
  nodeId: "<nodeId>",
  fileKey: "<fileKey>",
  clientLanguages: "dart",
  clientFrameworks: "flutter"
}
```

### 重要: React + Tailwind 出力の扱い

`get_design_context` はデフォルトで **React + Tailwind 形式** で出力する。これは MCP サーバーの設計上の仕様。

- AI モデルが Web データで訓練されているため、この形式が最も理解しやすい
- **プロダクション対応コードではなく、デザインコンテキストとして利用する**
- Flutter への変換はプロンプトで指示する（例: 「Flutter Widget で実装して」）
- Code Connect を設定すると `clientFrameworks` で対象を指定可能

### node-id の変換

| 形式     | 例            | 用途                         |
| -------- | ------------- | ---------------------------- |
| URL 形式 | `9474-146965` | Figma URL のクエリパラメータ |
| API 形式 | `9474:146965` | MCP / REST API の nodeId     |

変換: ハイフン `-` → コロン `:` に置換

### Figma URL からの抽出

```
https://www.figma.com/design/<fileKey>/<FileName>?node-id=<int1>-<int2>
→ fileKey: <fileKey>
→ nodeId: <int1>:<int2>
```

## レート制限

| プラン       | Dev/Full 座席（日/分） | View/Collab 座席 |
| ------------ | ---------------------- | ---------------- |
| Enterprise   | 600/日, 無制限/分      | 6/月             |
| Organization | 200/日, 20/分          | 6/月             |
| Pro          | 200/日, 15/分          | 6/月             |
| Starter      | 6/月                   | 6/月             |

## ベストプラクティス

### Figma ファイル構造化

- **コンポーネント化**: 繰り返し要素は Figma コンポーネントにする
- **セマンティック命名**: 「Frame1268」→「CardContainer」のように意図を示す名前に
- **Auto Layout**: レスポンシブ動作を表現（hug/fill/fixed の区別）
- **Figma 変数**: 色・間隔・タイポグラフィのトークン管理に活用

### `get_design_context` の注意点

- **node の存在 ≠ 採用**: コンポーネント流用により、**`visible=false` の未使用子 node** がツリーに残ることが多い。構造データだけで実装対象と判断しない
- **必ず `get_screenshot` と突合**: スクリーンショットに写っているものだけが「表示されている UI」。写っていなければ実装・YAML に含めない（条件付き表示は状態バリエーション表で別記）
- **REST API 補助**: 疑わしい node は Figma REST API の `visible` 属性で確認可能
- **マスク/クリッピング情報を正確に反映しない場合がある**
- 円形マスク（ellipse）の画像が単なる `<div>` として出力される等
- 形状が重要な要素は **`get_metadata` で個別にノードタイプを確認** する
- ノードタイプ: `ellipse` = 円形, `rectangle` = 四角形

### 色 / アイコンの値を変更するとき（必須手順）

**Figma の Variable 名・Style 名だけを根拠に色を変更してはならない。** 同じノードに複数の似た色変数が定義されていることがあり、名前から実装対象を推測すると誤判定する。

**必須プロセス:**

1. **`get_screenshot` で実描画を確認** — 実際にレンダリングされた色を目視する（変更前後の差を把握できる粒度で）
2. **`get_variable_defs` で候補を全件取得** — そのノードに紐づくすべての Variable / Style を一覧化する
3. **両者をクロスチェック** — スクショの見た目と、Variable の RGB 値を突合し、実際に SVG / Fill に bind されている Variable を特定する
4. **採用根拠をコードコメントに残す** — `// Figma の Variable XXX 準拠 / Style 名 YYY は別用途` のように、なぜそのコードを採用したかを明示する

<bad-example>
Figma の `get_design_context` レスポンス末尾に `Star-Dark: #DFB300` が含まれていたため、星の色を `#FFCB45` から `#DFB300` に変更した。
→ 実描画は別 Variable `Color/gold/200` (#FFCB45) を使っており、`Star-Dark` は未使用 / 別用途だった。スクショを見れば一目で気づけた誤判定。
</bad-example>

<good-example>
1. `get_screenshot` で星部分が明るい金色に見えることを確認
2. `get_variable_defs` で `Star-Dark: #DFB300` と `Color/gold/200: #ffcb45` の両方が定義されているのを把握
3. スクショの色と RGB 値を突合し、`Color/gold/200` が採用されていると判断
4. コードコメントに `// Figma の Variable Color/gold/200 準拠。Style 名 Star-Dark は別用途` と記載
</good-example>

このルールはアイコン色・テキスト色・ボーダー色・背景色など、**すべての色変更**に適用する。

> **関連（実装側のルール）**: Figma 値を Flutter 実装に落とし込む際のルール（既存デザイントークンを再発明しない／フォントサイズが異なるテキストの baseline 揃え 等）は Figma MCP ツールの話ではなく **実装規約**のため、`impl-issue` スキルの [phase-11-typography-mapping.md](../impl-issue/references/phase-11-typography-mapping.md) と [phase-11-ui-implementation.md](../impl-issue/references/phase-11-ui-implementation.md) に記載している。

### プロンプトのコツ

- フレームワーク明示: 「Flutter で実装して」「SwiftUI で生成して」
- コンポーネントパス指定: 「src/components/ui のコンポーネントを使って」
- ツール名明示: 期待通りの結果が出ない場合、プロンプトでツール名を指定する

## トラブルシューティング

| 問題                       | 対策                                                                  |
| -------------------------- | --------------------------------------------------------------------- |
| Web/React コードが返される | プロンプトでフレームワーク指定、Code Connect 設定、カスタムルール追加 |
| ツールが読み込まれない     | MCP 接続確認、Desktop アプリ再起動、`/mcp` で状態確認                 |
| node-id エラー             | URL から最新 nodeId を取得（画面設計書の nodeId は古い可能性）        |
| レート制限超過             | プランのアップグレード、一括取得の活用                                |

## 公式ドキュメント

- [Developer Docs](https://developers.figma.com/docs/figma-mcp-server/)
- [Tools and Prompts](https://developers.figma.com/docs/figma-mcp-server/tools-and-prompts/)
- [Code Connect Integration](https://developers.figma.com/docs/figma-mcp-server/code-connect-integration/)
- [Structure Your Figma File](https://developers.figma.com/docs/figma-mcp-server/structure-figma-file/)
- [GitHub Guide](https://github.com/figma/mcp-server-guide)
