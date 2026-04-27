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

## プロジェクトでの使い方

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
  clientLanguages: "<プロジェクトの言語 (例: swift, dart, typescript)>",
  clientFrameworks: "<プロジェクトのFW (例: swiftui, flutter, react)>"
}
```

> fileKey は `.claude/figma.yaml` から取得する（`resolve-figma-node` スキル参照）。

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

- **マスク/クリッピング情報を正確に反映しない場合がある**
- 円形マスク（ellipse）の画像が単なる `<div>` として出力される等
- 形状が重要な要素は **`get_metadata` で個別にノードタイプを確認** する
- ノードタイプ: `ellipse` = 円形, `rectangle` = 四角形

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
