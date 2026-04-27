# Figma MCP ツール詳細リファレンス

Figma MCP サーバーが提供する全 13 ツールの詳細仕様。

## デザイン情報取得ツール

### get_design_context

選択レイヤーまたは指定ノードのデザインコンテキストを構造化データとして取得する。

- **出力形式**: React + Tailwind（デフォルト）
- **対応**: Design ファイル, Make ファイル
- **用途**: レイアウト、スタイル、コンポーネント構造の取得

**引数**:

- `nodeId`: 対象ノード ID（Desktop MCP では省略可 → 選択中のノードを自動認識）
- `fileKey`: Figma ファイルキー（Remote MCP で必須）
- `clientLanguages`: 対象言語（例: `"dart"`）
- `clientFrameworks`: 対象フレームワーク（例: `"flutter"`）

**プロンプト例**:

- 「このフレームを Vue で生成して」→ フレームワーク変換
- 「src/components/ui のコンポーネントを使って」→ 既存コンポーネント活用
- 「iOS SwiftUI コードを生成」→ プラットフォーム指定

**注意点**:

- マスク/クリッピング情報を正確に反映しない場合がある
- `<CodeConnectSnippet>` ラッパーで Code Connect 情報が含まれる（設定時）
- 大規模デザインではレスポンスが大きくなるため、先に `get_metadata` で絞り込む

### get_metadata

選択範囲のノード構造を XML 形式で返す。レイヤー ID、名前、タイプ、位置、サイズを含む。

- **出力形式**: XML（スパース表現）
- **用途**: 大規模デザインの概要把握、ノードタイプの確認

**活用シーン**:

- `get_design_context` のレスポンスが大きすぎる場合に先行確認
- 個別要素のノードタイプ確認（ellipse, rectangle 等）
- 必要なノードの絞り込み後に `get_design_context` を再実行

### get_screenshot

デザインのスクリーンショットを取得する。

- **用途**: レイアウト忠実性の視覚確認、プレースホルダーの実際表示確認
- **推奨**: `get_design_context` 後に必ず取得（構造情報と視覚を照合）

**注意点**:

- MCP が localhost ソースの画像を返す場合、そのソースをそのまま使用する
- 新しいアイコンパッケージは追加せず、Figma ペイロードのアセットを使用

### get_variable_defs

選択範囲で使用されている変数とスタイル（色、spacing、typography 等）を返す。

- **用途**: デザイントークンの確認、変数名と値のマッピング取得
- **プロンプト例**: 「このフレームの変数名と値を取得して」

**明示的にツール名を指定することで正確な結果が得られる。**

## Code Connect ツール

### get_code_connect_map

Figma ノード ID と対応するコードコンポーネントのマッピングを取得する。

**レスポンス構造**:

```json
{
  "<figma-node-id>": {
    "codeConnectSrc": "src/components/Button.tsx",
    "codeConnectName": "Button"
  }
}
```

### add_code_connect_map

Figma コンポーネントとコードコンポーネントのマッピングを追加する。デザイン→コードワークフローの品質向上に寄与。

### get_code_connect_suggestions

Figma コンポーネントとコードコンポーネントのマッピング候補を自動検出・提案する。

### send_code_connect_mappings

提案された Code Connect マッピングを確認・送信する。

### create_design_system_rules

エージェント向けのデザインシステムルールファイルを生成する。ルール/インストラクションパスに保存される。

**生成内容**:

- デザイン→フロントエンドコード変換のコンテキスト
- コンポーネントの使用方法
- デザインシステムの規約

## コード → Figma

### generate_figma_design

UI インターフェースから Figma デザインレイヤーを生成する。

- **制約**: Claude Code 専用、Remote MCP のみ
- **出力先**: 新規ファイル、既存ファイル、クリップボード

**プロンプト例**:

- 「アプリのローカルサーバーを起動して UI を新しい Figma ファイルにキャプチャ」
- 「この UI を既存の Figma ファイルに追加」

## FigJam ツール

### get_figjam

FigJam 図を XML 形式で返す。メタデータとスクリーンショットを含む。

- **用途**: フローチャートや図の構造データ取得
- **活用**: エージェントが図を参照してアプリケーションロジックのコードを作成

### generate_diagram

Mermaid 記法から FigJam 図を生成する。

**対応する図の種類**:

- Flowchart（フローチャート）
- Gantt chart（ガントチャート）
- State diagram（ステート図）
- Sequence diagram（シーケンス図）

## ユーティリティ

### whoami

認証済みユーザーの情報を返す。Remote MCP のみ。

**レスポンス**:

- メールアドレス
- 所属プラン
- 座席種別（Full/Dev/View/Collab）

**用途**: パーミッションエラー時のデバッグ、プラン確認

## MCP vs REST API の使い分け

| 用途                            | 推奨     | 理由                                     |
| ------------------------------- | -------- | ---------------------------------------- |
| デザイン情報取得                | MCP      | 構造化された情報を直接取得               |
| 変数・スタイル取得              | MCP      | `get_variable_defs` が便利               |
| スクリーンショット              | MCP      | `get_screenshot` で直接取得              |
| アセットダウンロード（SVG/PNG） | REST API | MCP にはエクスポート機能なし             |
| 大規模な一括取得                | REST API | 複数ノードをカンマ区切りで一度に指定可能 |
| コンポーネント/スタイル一覧     | REST API | ファイル全体の情報取得                   |
