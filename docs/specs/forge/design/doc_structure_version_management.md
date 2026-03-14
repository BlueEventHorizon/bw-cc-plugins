# .doc_structure.yaml バージョン管理設計

> doc-advisor の merge_config.py から抽出した設計仕様

## 概要

`.doc_structure.yaml`（config.yaml 互換）のバージョン管理・マイグレーション方式を定義する。
doc-advisor で実装済みの仕組みをそのまま採用する。

## バージョン識別子

YAML コメント行でバージョンを記録する:

```yaml
# doc_structure_version: 2.0
```

- **フォーマット**: `X.Y`（X = メジャー、Y = マイナー）
- **マーカー**: `doc_structure_version:` — `.doc_structure.yaml` 独自のバージョン識別子
- **配置**: ファイル先頭のコメントブロック内

### バージョン番号の意味

| 変更種別 | バージョン | 例 |
|---------|-----------|-----|
| 破壊的変更（フィールド削除、構造変更） | メジャー X を上げる | 2.0 → 3.0 |
| 後方互換の追加（新オプショナルフィールド） | マイナー Y を上げる | 2.0 → 2.1 |

## マイグレーション方式

`merge_config.py` が旧設定から新設定への移行を担う。

### マイグレーションフロー

```
1. 旧 .doc_structure.yaml を読み込み
2. バージョン検出（get_major_version）
3. 新テンプレートを展開
4. バージョンマイグレーション適用（MIGRATIONS レジストリ）
5. ユーザー設定の抽出（extract_user_settings）
6. ユーザー設定の適用（apply_user_settings）
7. 新 .doc_structure.yaml を書き出し
```

### MIGRATIONS レジストリ

メジャーバージョン変更時に、構造変換関数を登録する:

```python
MIGRATIONS = {
    # 5: migrate_to_v5,   # v4 → v5 の構造変換
    # 6: migrate_to_v6,   # v5 → v6 の構造変換
}
```

- キー: 新メジャーバージョン番号
- 値: 変換関数 `fn(new_content: str, old_config_dict: dict) -> str`
- マルチバージョンアップグレード対応（例: v4→v6 は v5, v6 の順に適用）

### マイグレーション追加手順

1. メジャーバージョンを上げる（例: 4.x → 5.0）
2. `MIGRATIONS[5] = migrate_to_v5` を登録
3. `migrate_to_v5(new_content, old_dict) -> str` を実装
4. この設計書のマイグレーション履歴セクションに記録

## ユーザー設定の保持ルール

マイグレーション時に以下のユーザー設定を保持する:

| 設定 | 保持条件 |
|------|---------|
| `root_dirs` | 非空の場合 |
| `doc_types_map` | 非空の場合 |
| `patterns.exclude` | 非空の場合 |
| `output.header_comment` | デフォルト値と異なる場合 |
| `output.metadata_name` | デフォルト値と異なる場合 |
| `common.parallel.max_workers` | デフォルト値（5）と異なる場合 |
| `common.parallel.fallback_to_serial` | デフォルト値（true）と異なる場合 |

### デフォルト値

```python
DEFAULT_OUTPUT = {
    'rules': {
        'header_comment': 'Development documentation search index for query-rules skill',
        'metadata_name': 'Development Documentation Search Index',
    },
    'specs': {
        'header_comment': 'Project specification document search index for query-specs skill',
        'metadata_name': 'Project Specification Document Search Index',
    },
}
DEFAULT_PARALLEL = {
    'max_workers': 5,
    'fallback_to_serial': True,
}
```

## バージョン検出 API

`resolve_doc_structure.py` が提供する:

```bash
python3 resolve_doc_structure.py --version
# → {"status": "ok", "version": "2.0", "major_version": 2}
```

```python
from resolve_doc_structure import get_version, get_major_version

content = open('.doc_structure.yaml').read()
version = get_version(content)      # "2.0"
major = get_major_version(content)  # 2
```

## マイグレーション履歴

| バージョン | 変更内容 |
|-----------|---------|
| 1.0 | 旧形式（doc_type-centric: `version: "1.0"` YAML フィールド） |
| 2.0 | config.yaml 互換フォーマット採用。バージョンマーカーを `doc_structure_version:` コメント行に変更 |

## 関連ファイル

| ファイル | 役割 |
|---------|------|
| `resolve_doc_structure.py` | バージョン検出（`get_version`, `get_major_version`） |
| `.claude/doc-advisor/scripts/merge_config.py` | マイグレーション実装（doc-advisor 側） |
| `doc_structure_format.md` | フォーマット仕様 |
