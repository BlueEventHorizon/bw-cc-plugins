# DES-006 セマンティック検索 設計書

## メタデータ

| 項目     | 値                                       |
| -------- | ---------------------------------------- |
| 設計ID   | DES-006                                  |
| 関連要件 | FNC-001, FNC-002, FNC-003, NFR-001, NFR-002, NFR-003 |
| 作成日   | 2026-03-30                               |
| 改定日   | 2026-04-11                               |

## 1. 概要

doc-advisor の文書検索（query-specs / query-rules）に、既存の ToC（キーワード検索）を維持したまま **Embedding ベースのセマンティック検索（Index）** を追加し、**3モードのハイブリッド検索アーキテクチャ** を構築する。

> **設計方針の変遷**: 初版（v1.0）では ToC を Embedding で完全置換する 3 フェーズ移行を計画した。しかし品質テスト（v0.2.0）で **ToC の検索精度が Index を上回る** ことが判明したため、ToC を主軸として維持し Index を補完に使う方針に転換した。Phase 3（ToC 廃止）は凍結。詳細は §10 参照。

採用アプローチ:
- **OpenAI Embedding API** で文書メタデータをベクトル化し、JSON ファイルに保存（Index）
- **既存 ToC YAML** は AI によるキーワードマッチングで高精度検索を提供（ToC）
- **3モード検索**: `--toc`（ToC のみ）、`--index`（Index のみ）、`auto`（ハイブリッド、デフォルト）
- auto モードでは Index と ToC の候補を union し、AI がファイルを Read して最終判定
- 固有名詞・識別子の検索は全文検索スクリプトで補完（Index モードで AI が判断して呼び出す）
- 外部依存は **OpenAI API キーのみ**（pip install 不要。ToC モードは外部依存なし）

## 2. アーキテクチャ概要

### 2.1 コンポーネント図

```mermaid
flowchart TB
    subgraph インデックス構築
        A[".doc_structure.yaml"] --> B["embed_docs.py"]
        C["文書メタデータ\n(title, purpose, keywords...)"] --> B
        B -->|"OpenAI API"| D["Embedding ベクトル"]
        D --> E["{category}_index.json"]
        F[".toc_checksums.yaml"] --> B
    end

    subgraph 検索
        G["タスク説明文"] --> H["search_docs.py"]
        H -->|"OpenAI API"| I["クエリベクトル"]
        I --> J["コサイン類似度計算"]
        E --> J
        J --> K["候補パスリスト\n(JSON 出力)"]
    end

    subgraph 全文検索補完
        L["固有名詞\nキーワード"] --> M["grep_docs.py"]
        N["全文書ファイル"] --> M
        M --> O["マッチパスリスト\n(JSON 出力)"]
    end

    subgraph AI 統合
        K --> P["AI (Claude)"]
        O --> P
        P --> Q["候補文書を Read"]
        Q --> R["最終結果\n(Required documents)"]
    end
```

### 2.2 責務の分担

| レイヤー | 責務 | 担当 |
| -------- | ---- | ---- |
| ToC 生成 | AI による文書メタデータ抽出と YAML ToC 構築 | `create_pending_yaml.py` + toc-updater agent + `merge_toc.py` |
| Index 構築 | 文書メタデータの Embedding 化と JSON 永続化 | `embed_docs.py` |
| ToC 検索 | ToC YAML の全量読み込みとキーワードマッチング | AI（`query_toc_workflow.md` の手順に従う） |
| セマンティック検索 | クエリとインデックスのコサイン類似度計算 | `search_docs.py` |
| 全文検索 | 固有名詞・識別子のテキストマッチング | `grep_docs.py` |
| 検索統合・モード切替 | 3モードの切り替え、候補の union、本文確認、最終判断 | AI（query-specs / query-rules SKILL.md） |
| ワークフロー定義 | ToC / Index 各検索手順の文書化 | `query_toc_workflow.md` / `query_index_workflow.md` |
| 設定・差分検出 | .doc_structure.yaml の読み込み、チェックサム管理、ファイル列挙 | `toc_utils.py`（既存・再利用） |

### 2.3 3モード検索アーキテクチャ

query-rules / query-specs は以下の 3 モードを提供する:

```mermaid
flowchart TB
    subgraph "query-rules / query-specs SKILL.md"
        A["引数パース"] --> B{モード判定}
        B -->|"--toc"| C["ToC 検索のみ"]
        B -->|"--index"| D["Index 検索のみ"]
        B -->|"auto (デフォルト)"| E["Index + ToC 両方実行"]
        
        C --> F["query_toc_workflow.md"]
        D --> G["query_index_workflow.md"]
        E --> G2["query_index_workflow.md"]
        E --> F2["query_toc_workflow.md"]
        G2 --> H["union(Index候補, ToC候補)"]
        F2 --> H
        
        F --> I["候補ファイルを Read → 最終判定"]
        G --> I
        H --> I
        I --> J["Required documents 出力"]
    end
```

| モード | フラグ | 動作 | フォールバック |
| ------ | ------ | ---- | ------------- |
| ToC | `--toc` | ToC YAML を全量 Read しキーワードマッチング | なし（ToC 不在時はエラー通知） |
| Index | `--index` | `search_docs.py` + `grep_docs.py` でセマンティック検索 | なし（API エラー時はエラー通知） |
| auto | フラグなし | Index → ToC の順で両方実行し、候補を union | 片方失敗時はもう片方の結果を使用 |

**設計判断**: auto モードでは **Index を先に実行** する。`embed_docs.py` の auto-build で最新化を行うため。

### 2.4 ワークフロー文書アーキテクチャ

検索手順を SKILL.md から分離し、再利用可能なワークフロー文書として定義する:

| ワークフロー文書 | 責務 | パラメータ |
| --------------- | ---- | --------- |
| `docs/query_toc_workflow.md` | ToC YAML の読み込みとキーワードマッチング手順 | `{category}` |
| `docs/query_index_workflow.md` | Index の auto-update + セマンティック検索手順 | `{category}` |

ワークフロー文書は **候補パスの生成まで** が責務。ファイル Read・最終判定は SKILL.md 側で行う。

## 3. モジュール設計

### 3.1 モジュール一覧

| モジュール | ファイルパス | 責務 | 依存 |
| ---------- | ------------ | ---- | ---- |
| `embed_docs.py` | `plugins/doc-advisor/scripts/embed_docs.py` | Embedding インデックス構築（全体・差分） | `toc_utils.py`, `urllib`（標準） |
| `search_docs.py` | `plugins/doc-advisor/scripts/search_docs.py` | セマンティック検索実行 | `toc_utils.py`, `urllib`（標準） |
| `grep_docs.py` | `plugins/doc-advisor/scripts/grep_docs.py` | 全文検索（テキストマッチング） | `toc_utils.py` |
| `toc_utils.py` | `plugins/doc-advisor/scripts/toc_utils.py`（既存） | 共通ユーティリティ | 標準ライブラリのみ |

### 3.2 クラス図

```mermaid
classDiagram
    class EmbedDocs {
        +main(args) void
        -load_index(index_path) dict
        -save_index(index, index_path) void
        -build_embedding_text(metadata) str
        -call_embedding_api(texts, api_key) list~list~float~~
    }

    class SearchDocs {
        +main(args) void
        -load_index(index_path) dict
        -calculate_cosine_similarity(vec_a, vec_b) float
        -search(query, index, api_key, threshold) list~dict~
    }

    class GrepDocs {
        +main(args) void
        -search_files(keyword, root_dirs, patterns) list~str~
    }

    class TocUtils {
        +load_config(category) dict
        +init_common_config(category) dict
        +get_all_md_files() tuple
        +load_metadata(category, file_path) dict
        +calculate_file_hash(path) str
        +load_checksums(path) dict
        +write_checksums_yaml(checksums, path) void
        +normalize_path(path_str) str
    }

    EmbedDocs --> TocUtils : 設定読み込み・差分検出
    SearchDocs --> TocUtils : 設定読み込み
    GrepDocs --> TocUtils : 設定読み込み・ファイル列挙
```

### 3.3 embed_docs.py 詳細設計

#### CLI インターフェース

```
python3 embed_docs.py --category {specs|rules} [--full] [--check]
```

| 引数 | 説明 |
| ---- | ---- |
| `--category` | 対象カテゴリ（必須） |
| `--full` | 全文書を再構築（省略時は差分更新） |
| `--check` | インデックスの新鮮さを確認し、古い場合は再構築を案内する（staleness check）。インデックスが存在しない場合や、文書のチェックサムが不一致の場合に `{"status": "stale", ...}` を返す |

#### 処理フロー

```mermaid
sequenceDiagram
    participant Script as embed_docs.py
    participant Utils as toc_utils.py
    participant API as OpenAI API
    participant FS as ファイルシステム

    Script->>Utils: init_common_config(category)
    Utils-->>Script: 設定（root_dirs, patterns 等）

    Script->>Utils: get_all_md_files()
    Utils-->>Script: 全 .md ファイル一覧

    alt 差分モード
        Script->>Utils: load_checksums()
        Utils-->>Script: 旧チェックサム
        Script->>Script: 差分計算（新規・変更・削除）
    end

    Script->>FS: 対象文書のメタデータ読み込み
    Note over Script: title + purpose + keywords +<br/>applicable_tasks + content_details<br/>を結合して Embedding テキスト生成

    Script->>API: POST /v1/embeddings<br/>(バッチ: 最大 100 テキスト)
    API-->>Script: ベクトル配列

    Script->>FS: {category}_index.json に保存
    Script->>Utils: write_checksums_yaml()
```

#### Embedding テキストの構成

各文書のメタデータから以下の順で結合し、1つのテキストとして Embedding API に送信する:

```
{title}\n{purpose}\n{keywords をスペース区切り}\n{applicable_tasks をスペース区切り}\n{content_details を改行区切り}
```

技術選択の理由: メタデータの全フィールドを含めることで、タイトルだけでなく目的やキーワードの意味的類似性も検索に反映される。フィールドの順序は重要度順（title が先頭で最も影響大）。

#### メタデータの取得元

**既存 ToC YAML からメタデータを読み込む**。ToC は廃止せず維持する方針のため（§10.2 参照）、ToC YAML は Embedding インデックスのメタデータソースとしても継続利用する。

**抽象化レイヤー**: メタデータ取得は `toc_utils.py` の `load_metadata(category, file_path)` 関数経由で行う。`embed_docs.py` はこの関数を呼び出すため、将来 ToC YAML 以外からメタデータを取得する方式に変更する場合も `embed_docs.py` への影響を局所化できる。

#### インデックス JSON スキーマ

```json
{
  "metadata": {
    "category": "specs",
    "model": "text-embedding-3-small",
    "dimensions": 1536,
    "generated_at": "2026-03-30T12:00:00Z",
    "file_count": 29
  },
  "entries": {
    "docs/specs/doc-advisor/design/DES-004_document_model.md": {
      "title": "Document Model Design Specification",
      "embedding": [0.012, -0.045, 0.078, ...],
      "checksum": "a1b2c3d4..."
    }
  }
}
```

| フィールド | 型 | 説明 |
| ---------- | -- | ---- |
| `metadata.category` | string | `specs` または `rules` |
| `metadata.model` | string | 使用した Embedding モデル名 |
| `metadata.dimensions` | int | ベクトルの次元数 |
| `metadata.generated_at` | string | ISO 8601 形式の生成日時 |
| `metadata.file_count` | int | エントリ数 |
| `entries.{path}.title` | string | 文書タイトル（検索結果表示用） |
| `entries.{path}.embedding` | array[float] | Embedding ベクトル |
| `entries.{path}.checksum` | string | ファイル内容の SHA-256 ハッシュ |

#### 差分更新ロジック

1. `load_checksums()` で旧チェックサムを読み込む
2. 現在のファイルのハッシュを計算し、旧チェックサムと比較
3. 新規・変更ファイルのみ Embedding API を呼び出す
4. 削除ファイルはインデックスから削除
5. チェックサム更新

既存の `create_pending_yaml.py` の差分検出ロジックと同じアルゴリズムを使用する。

**NFR-002 中断再開への対応**: 処理が中断された場合、チェックサムは未更新のままとなるため、次回の差分更新で未処理分が自動的に再処理される。これにより、明示的な再開機構なしに中断再開要件を満たす。

#### OpenAI API 呼び出し

```
POST https://api.openai.com/v1/embeddings
Content-Type: application/json
Authorization: Bearer {OPENAI_API_KEY}

{
  "model": "text-embedding-3-small",
  "input": ["text1", "text2", ...]
}
```

- API キーは環境変数 `OPENAI_API_KEY` から取得
- バッチサイズ: 最大 100 テキスト/リクエスト（API 制限内）
- エラー時: JSON エラー出力（`{"status": "error", "error": "..."}`)
- API キー未設定時: エラーメッセージで設定方法を案内

技術選択の理由: `text-embedding-3-small` を選択。コスト効率が最も高く（$0.02/1M tokens）、1536 次元で十分な精度。600 件の全体再構築でも $0.01 以下。`urllib.request` で HTTP リクエストを送信するため pip install 不要。

#### インデックスの保存先

```
.claude/doc-advisor/toc/{category}/{category}_index.json
```

既存の ToC YAML と同じディレクトリに配置する。

### 3.4 search_docs.py 詳細設計

#### CLI インターフェース

```
python3 search_docs.py --category {specs|rules} --query "タスクの説明文" [--threshold 0.3]
```

| 引数 | 説明 | デフォルト |
| ---- | ---- | ---------- |
| `--category` | 対象カテゴリ（必須） | — |
| `--query` | 検索クエリ（必須） | — |
| `--threshold` | 類似度スコアの下限閾値（この値以上の候補を全件返却） | 0.3 |

FNC-002「件数制限を設けない」要件に基づき、件数での制限（top-k）は設けず、閾値ベースで候補を返却する。

#### 処理フロー

1. `{category}_index.json` を読み込む
2. クエリを OpenAI Embedding API でベクトル化
3. インデックス内の全エントリとコサイン類似度を計算
4. スコア降順でソートし、閾値以上の全候補を JSON 出力

#### コサイン類似度の計算

```python
import math

def cosine_similarity(vec_a, vec_b):
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
```

技術選択の理由: 600 件 × 1536 次元のコサイン類似度計算は、Pure Python でも数十ミリ秒で完了する。numpy や Vector DB は不要。

#### 出力形式

```json
{
  "status": "ok",
  "query": "検索機能を改善するタスク",
  "results": [
    {"path": "docs/specs/doc-advisor/design/DES-005_toc_generation_flow.md", "title": "ToC Generation Flow Design", "score": 0.89},
    {"path": "docs/specs/doc-advisor/design/DES-004_document_model.md", "title": "Document Model Design", "score": 0.82}
  ]
}
```

#### エラーケース

| 条件 | 出力 |
| ---- | ---- |
| インデックスが存在しない | `{"status": "error", "error": "Index not found. Run embed_docs.py first."}` |
| インデックスが古い（チェックサム不一致） | `{"status": "error", "error": "Index is stale. Run embed_docs.py to update."}` — 検索を実行せず再生成を案内する（FNC-002 対応）。検出方法: インデックス JSON の各エントリに記録された `checksum`（SHA-256）を、現在のファイルのハッシュ値と照合する |
| Embedding モデル不一致 | `{"status": "error", "error": "Model mismatch: index uses {old_model}, current is {new_model}. Run embed_docs.py --full to rebuild."}` — インデックスの `metadata.model` と現在のモデル定数を比較し、不一致時は検索を実行せず `--full` 再構築を案内する |
| API キー未設定 | `{"status": "error", "error": "OPENAI_API_KEY not set."}` |
| API 呼び出し失敗 | `{"status": "error", "error": "API error: {詳細}"}` |

### 3.5 grep_docs.py 詳細設計

#### CLI インターフェース

```
python3 grep_docs.py --category {specs|rules} --keyword "doc_structure.yaml"
```

| 引数 | 説明 |
| ---- | ---- |
| `--category` | 対象カテゴリ（必須） |
| `--keyword` | 検索キーワード（必須） |

#### 処理フロー

1. `toc_utils.init_common_config(category)` で設定を読み込む
2. `toc_utils.get_all_md_files()` で対象ファイルを列挙
3. 各ファイルの内容を読み込み、キーワードの部分一致を検索（大文字小文字区別なし）
4. マッチしたファイルのパスを JSON 出力

#### 出力形式

```json
{
  "status": "ok",
  "keyword": "doc_structure.yaml",
  "results": [
    {"path": "docs/specs/doc-advisor/design/DES-004_document_model.md"},
    {"path": "docs/rules/implementation_guidelines.md"}
  ]
}
```

技術選択の理由: 600 件程度のファイルを順次読み込んでの文字列検索は、外部ツール（ripgrep 等）なしでも数百ミリ秒で完了する。AI が固有名詞を検出した場合にのみ呼び出されるため、頻度も低い。

## 4. ユースケース設計

### 4.1 ユースケース一覧

| ユースケース | 説明 |
| ------------ | ---- |
| UC-1 インデックス構築（全体） | 初回または再構築時に全文書の Embedding を生成 |
| UC-2 インデックス更新（差分） | 文書の追加・変更・削除を検出し、差分のみ更新 |
| UC-3 セマンティック検索 | タスク説明文から関連文書を検索 |
| UC-4 全文検索補完 | 固有名詞・識別子で文書を検索 |
| UC-5 精度検証 | ゴールデンセットで検索精度を測定 |

### 4.2 シーケンス図

#### UC-1: インデックス構築（create-specs-toc 経由）

```mermaid
sequenceDiagram
    actor User
    participant Skill as create-specs-toc
    participant Script as embed_docs.py
    participant API as OpenAI API
    participant FS as ファイルシステム

    User->>Skill: /doc-advisor:create-specs-toc
    Skill->>Script: python3 embed_docs.py --category specs --full
    Script->>FS: 指定カテゴリの全 .md ファイル読み込み<br/>(.doc_structure.yaml の root_dirs に基づく)
    Script->>Script: メタデータ抽出・Embedding テキスト生成
    Script->>API: POST /v1/embeddings（バッチ）
    API-->>Script: ベクトル配列
    Script->>FS: specs_index.json 保存
    Script->>FS: .toc_checksums.yaml 更新
    Script-->>Skill: 完了（JSON: file_count, status）
    Skill-->>User: インデックス構築完了
```

#### UC-3: セマンティック検索（query-specs 経由）

```mermaid
sequenceDiagram
    actor AI as AI (Claude)
    participant QSkill as query-specs SKILL.md
    participant Search as search_docs.py
    participant Grep as grep_docs.py
    participant API as OpenAI API

    AI->>QSkill: /doc-advisor:query-specs "検索機能改善タスク"

    QSkill->>Search: python3 search_docs.py --category specs --query "..."
    Search->>API: POST /v1/embeddings（クエリ）
    API-->>Search: クエリベクトル
    Search->>Search: 全件コサイン類似度計算
    Search-->>QSkill: 候補リスト（JSON）

    alt クエリに固有名詞が含まれる場合
        QSkill->>Grep: python3 grep_docs.py --category specs --keyword "doc_structure"
        Grep-->>QSkill: マッチリスト（JSON）
    end

    QSkill->>AI: 統合候補リスト
    AI->>AI: 候補文書を Read して最終確認
    AI-->>AI: Required documents リスト
```

## 5. 使用する既存コンポーネント

| コンポーネント | ファイルパス | 用途 |
| -------------- | ------------ | ---- |
| `load_config()` | `plugins/doc-advisor/scripts/toc_utils.py` | `.doc_structure.yaml` の読み込み |
| `init_common_config()` | 同上 | root_dirs, patterns, チェックサムパス等の初期化 |
| `get_all_md_files()` | 同上（※現在は `create_pending_yaml.py` に存在。本設計の前提作業として `toc_utils.py` へ移動する） | 対象ファイルの列挙（glob パターン対応） |
| `load_metadata()` | 同上（新規追加） | メタデータ取得の抽象化レイヤー（将来のメタデータ取得方式変更時に embed_docs.py への影響を局所化） |
| `calculate_file_hash()` | 同上 | SHA-256 ハッシュによる変更検出 |
| `load_checksums()` | 同上 | 旧チェックサムの読み込み |
| `write_checksums_yaml()` | 同上 | チェックサムの書き出し |
| `normalize_path()` | 同上 | macOS NFC 正規化 |
| `ConfigNotReadyError` | 同上 | 設定未準備エラー |

## 6. SKILL.md の変更設計

### 6.1 query-specs / query-rules SKILL.md

旧 query-xxx（ToC 専用）と query-xxx-index（Index 専用）を **単一の query-xxx スキル** に統合し、3モードスイッチャーとして再設計する。

```
[旧構成]
  query-rules (SKILL) — ToC 検索のみ
  query-specs (SKILL) — ToC 検索のみ
  query-rules-index (SKILL) — Index 検索のみ
  query-specs-index (SKILL) — Index 検索のみ

[新構成（v0.2.0〜）]
  query-rules (SKILL) — 3モードスイッチャー: auto / --toc / --index
  query-specs (SKILL) — 3モードスイッチャー: auto / --toc / --index
  docs/query_toc_workflow.md — ToC 候補生成手順（ワークフロー文書）
  docs/query_index_workflow.md — Index 候補生成手順（ワークフロー文書）
```

#### 実行フロー

```
引数パース: --toc / --index / (なし = auto)

--toc:
  Read query_toc_workflow.md → 手順に従い ToC 候補パス取得
  ToC なし → ユーザに通知（create-toc を案内）。Index にフォールバックしない
  候補あり → Read して確認 → 出力

--index:
  Read query_index_workflow.md → 手順に従い Index 候補パス取得
  Index 構築失敗（API key 等）→ ユーザに通知。ToC にフォールバックしない
  候補あり → Read して確認 → 出力

auto（デフォルト）:
  Step 1: Read query_index_workflow.md → Index 候補パス取得（失敗時 = 空）
  Step 2: Read query_toc_workflow.md → ToC 候補パス取得（不在時 = 空）
  Step 3: union(Index候補, ToC候補) で重複排除
  Step 4: 全候補ファイルを Read して関連性を最終判断 → 出力
```

query-xxx-index スキルは廃止し、ディレクトリごと削除する。

### 6.2 create-specs-toc / create-rules-toc SKILL.md

**ToC 生成パイプラインは維持する**。Embedding インデックスの構築は create-xxx-toc 実行時に **追加で** 実行される:

```
[現行（v0.2.0〜）]
Phase 1: create_pending_yaml.py → pending YAML テンプレート生成
Phase 2: toc-updater agent × N（並列 AI 解析）
Phase 3: merge_toc.py → validate_toc.py → checksums
Phase 4（追加）: embed_docs.py --category {category}（Index 構築・差分更新）
```

> **初版（v1.0）からの変更**: 初版では create-xxx-toc を `embed_docs.py` 単一コマンドに置換する計画だったが、品質テストで ToC の優位性が確認されたため、ToC パイプラインを維持し Index を追加ステップとして実行する方針に変更した。

## 7. データフロー設計

### 7.1 インデックス構築時

```
.doc_structure.yaml
    ↓ load_config()
root_dirs, patterns
    ↓ get_all_md_files()
対象 .md ファイル一覧
    ↓ load_checksums() + calculate_file_hash()
差分ファイル一覧（新規・変更のみ）
    ↓ 各ファイルのメタデータ読み込み（ToC YAML から）
Embedding テキスト生成
    ↓ OpenAI API（バッチ）
ベクトル配列
    ↓ save_index()
{category}_index.json
    ↓ write_checksums_yaml()
.toc_checksums.yaml 更新
```

### 7.2 検索時

```
タスク説明文（クエリ）
    ↓ OpenAI API
クエリベクトル
    ↓ load_index()
{category}_index.json の全エントリ
    ↓ cosine_similarity()（全件計算）
スコア付きリスト
    ↓ 閾値でフィルタ（threshold 以上の全件）
候補パスリスト（JSON 出力）
```

## 8. エラーハンドリング

| エラー | 検出方法 | 対応 |
| ------ | -------- | ---- |
| OPENAI_API_KEY 未設定 | `os.environ.get()` が None | JSON エラー出力 + 設定方法を案内 |
| API 呼び出し失敗（ネットワーク） | `urllib.error.URLError` | リトライ 1 回 → 失敗時 JSON エラー出力 |
| API 呼び出し失敗（認証エラー） | HTTP 401 | JSON エラー出力 + API キー確認を案内 |
| API 呼び出し失敗（レート制限） | HTTP 429 | 60 秒待機 → リトライ 1 回 |
| インデックス JSON が破損 | JSON パースエラー | 全体再構築を案内 |
| インデックスが存在しない | ファイル不在 | 構築を案内 |
| バッチ処理の部分失敗 | API 呼び出しエラー（バッチ途中） | 処理済み分のインデックスとチェックサムを保存し、未処理分は次回の差分更新で再処理する（冪等性を保証） |
| .doc_structure.yaml 未設定 | `ConfigNotReadyError` | JSON エラー出力（既存パターン踏襲） |

## 9. テスト設計

### 9.1 単体テスト

| テスト対象 | テストファイル | テスト内容 |
| ---------- | -------------- | ---------- |
| `embed_docs.py` | `tests/doc_advisor/scripts/test_embed_docs.py` | Embedding テキスト生成、インデックス JSON の読み書き、差分検出ロジック |
| `search_docs.py` | `tests/doc_advisor/scripts/test_search_docs.py` | コサイン類似度計算、閾値フィルタリング、出力 JSON 形式 |
| `grep_docs.py` | `tests/doc_advisor/scripts/test_grep_docs.py` | キーワードマッチング、大文字小文字無視、出力 JSON 形式 |

### 9.2 テスト方針

- **OpenAI API 呼び出しはモック化する**: テスト用の固定ベクトルを返すモックを使用
- **コサイン類似度の計算は実値でテスト**: 既知のベクトルペアで期待値を検証
- **差分検出は既存テスト（test_create_pending.py）のパターンを踏襲**

### 9.3 精度検証テスト（FNC-002 対応）

- ゴールデンセット（テストクエリ + 正解文書のペア）を `tests/doc_advisor/golden_set/` に配置
- テストスクリプトが search_docs.py を実行し、正解文書が全て候補に含まれるか検証
- 見落とし 0 件を自動テストで確認

## 10. 移行設計

### 10.1 移行フェーズ

| Phase | 内容 | ToC YAML | Embedding Index | ステータス |
| ----- | ---- | -------- | --------------- | --------- |
| **Phase 1** | Embedding インデックス構築スクリプト実装 | **維持** | 構築 | **完了** |
| **Phase 2** | query-xxx を 3 モードハイブリッドに統合。品質テスト実施 | **維持（主軸）** | 運用（補完） | **完了**（v0.2.0） |
| ~~Phase 3~~ | ~~精度検証完了後、ToC YAML と生成パイプラインを廃止~~ | ~~廃止~~ | ~~単独運用~~ | **凍結** |

### 10.2 Phase 3 凍結の経緯と根拠

v0.2.0 の品質テスト（ゴールデンセット 43 クエリ × 3 モード比較）で以下が判明:

| 検索モード | 精度傾向 | 特徴 |
| ---------- | -------- | ---- |
| ToC（`--toc`） | **最高** | AI が YAML メタデータ（keywords, applicable_tasks）を全量読みしてマッチング。false negative が最も少ない |
| Index（`--index`） | 良好 | コサイン類似度ベースで高速。ただし ToC メタデータが古い文書で ToC が見落とすケースを補完できる |
| auto（ハイブリッド） | **最良の網羅性** | 両方の候補を union し、AI が Read して最終判定。false negative を最小化 |

**結論**: ToC は Embedding より高い精度を示し、廃止の前提条件（NFR-002「Embedding が ToC と同等以上」）を満たさない。ToC を主軸として維持し、Index を補完に使うハイブリッド方式を正式アーキテクチャとする。

NFR-002（YAML ToC 廃止要件）は **凍結** とする。将来 Embedding の精度が ToC を上回ることが確認された場合に再検討する。

### 10.3 Phase 2 で実施した変更

Phase 2 の実装（v0.2.0）で以下を変更:

1. **query-xxx-index スキルの廃止**: query-rules-index / query-specs-index ディレクトリを削除
2. **query-xxx の 3 モード化**: query-rules / query-specs を `--toc` / `--index` / `auto` の 3 モードスイッチャーに書き換え
3. **ワークフロー文書の新設**: `docs/query_toc_workflow.md` / `docs/query_index_workflow.md` を作成し、検索手順を SKILL.md から分離
4. **plugin.json の更新**: skills リストから query-xxx-index を削除（4 スキル構成に）

### 10.4 現行アーキテクチャの安定性

ToC + Index のハイブリッド構成は以下の理由で安定的に運用可能:

- **ToC は単独で十分な精度**: Index なし（OPENAI_API_KEY 未設定）環境でも `--toc` モードで高品質な検索を提供
- **Index は任意追加**: OPENAI_API_KEY が設定されていれば auto モードで自動的に Index も活用
- **相互独立性**: ToC 障害時は Index のみ、Index 障害時は ToC のみで検索を継続可能

## 改定履歴

| 日付 | バージョン | 内容 |
| ---- | ---------- | ---- |
| 2026-03-30 | 1.0 | 初版作成 |
| 2026-04-11 | 2.0 | ハイブリッドアーキテクチャに改定。§1 概要を ToC+Index 共存方針に変更、§2.3/2.4 に 3 モード検索・ワークフロー文書を追加、§6 を実装に合わせて書き換え、§10 Phase 3 凍結 |
