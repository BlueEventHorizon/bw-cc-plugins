# バージョンマイグレーション実装仕様

バージョン付きデータ形式の段階的マイグレーションを実装するための仕様書。
COMMON-REQ-001（段階的バージョンマイグレーション要件）に準拠する。

要件定義: `docs/specs/common/requirement/COMMON-REQ-001_versioned_migration.md`
設計ルール: `docs/rules/version_migration_design.md`

---

## 基本原則

### パイプライン原則 [MANDATORY]

各マイグレーション関数は「前ステップの出力」を入力として受け取る。

```
v1データ
  ↓ migrate_v1_to_v2(v1データ)
v2データ
  ↓ migrate_v2_to_v3(v2データ)  ← v1 ではなく v2 を受け取る
v3データ
```

バージョンを飛ばした場合（v1 → v3）も、中間ステップ（v2）を経由する。

### マイグレーション関数の規約

| 規約 | 説明 |
|------|------|
| 1入力1出力 | `fn(data) -> data`。前バージョンのデータを受け取り、ターゲットバージョンのデータを返す |
| 冪等性 | 同じ入力に対して常に同じ出力を返す |
| 副作用なし | ファイル I/O、ネットワーク通信等を行わない。データ変換のみ |
| 元データ非破壊 | 入力を直接変更しない（コピーして操作） |

### エラーハンドリング

| 状況 | 対応 |
|------|------|
| マイグレーション中にエラー | マイグレーション前の状態を返す（部分適用しない） |
| 検出バージョン > 現行バージョン | マイグレーションをスキップし、そのまま使用 |
| バージョン検出失敗 | 最古のバージョン（v1）として扱う |

---

## 実装パターン

### 定数とレジストリ

```python
CURRENT_VERSION = 3  # 現行バージョン（定数で管理）

MIGRATIONS = {
    2: migrate_v1_to_v2,  # v1 → v2
    3: migrate_v2_to_v3,  # v2 → v3
}
```

- キー: ターゲットバージョン番号
- 値: 変換関数
- 適用範囲: `detected_version < v <= CURRENT_VERSION` を昇順に実行

### コアロジック

```python
def apply_migrations(data, detected_version):
    """段階的マイグレーションを適用する"""
    if detected_version >= CURRENT_VERSION:
        return data  # 未知のバージョンはスキップ

    targets = [v for v in sorted(MIGRATIONS.keys())
               if detected_version < v <= CURRENT_VERSION]

    original = data  # エラー時のロールバック用
    try:
        for v in targets:
            data = MIGRATIONS[v](data)
    except Exception:
        return original

    return data
```

### マイグレーション関数の例

```python
def migrate_v1_to_v2(data):
    """v1 → v2: フィールドのリネーム"""
    result = dict(data)  # コピー
    if "max_workers" in result:
        result["concurrency"] = result.pop("max_workers")
    return result

def migrate_v2_to_v3(data):
    """v2 → v3: 不要フィールドの除去 + 新フィールド追加"""
    result = dict(data)
    result.pop("deprecated_field", None)
    result.setdefault("new_field", "default_value")
    return result
```

### テキスト操作の場合

YAML / JSON のコメント行を保持する必要がある場合、`fn(str) -> str` で実装する。

```python
def migrate_v2_to_v3(content):
    """v2 → v3: テキスト操作で変換"""
    # バージョンマーカー更新
    content = content.replace('version: 2.0', 'version: 3.0')
    # 不要行の除去
    lines = [line for line in content.split('\n')
             if not line.strip().startswith('deprecated_field:')]
    return '\n'.join(lines)
```

---

## バージョン検出

データ自体にバージョン番号を埋め込む（セルフ記述型）。

| 形式 | バージョン埋め込み方法 |
|------|---------------------|
| YAML コメント | `# version: 3.0` |
| YAML フィールド | `version: "3.0"` |
| JSON フィールド | `"version": "3.0"` |

検出関数の例:

```python
def detect_version(content):
    """バージョン検出。検出失敗時は 1 を返す"""
    # コメント行からの検出
    for line in content.split('\n'):
        if 'version:' in line and line.strip().startswith('#'):
            version_str = line.split('version:')[1].strip()
            return int(version_str.split('.')[0])
    # フィールドからの検出
    for line in content.split('\n'):
        if line.strip().startswith('version:'):
            version_str = line.split(':')[1].strip().strip('"')
            return int(version_str.split('.')[0])
    return 1  # 検出失敗 → v1
```

---

## 新バージョン追加手順

1. `migrate_vN_to_vN1()` 関数を実装する
2. `MIGRATIONS[N+1] = migrate_vN_to_vN1` を登録する
3. `CURRENT_VERSION` を `N+1` に更新する
4. 既存のマイグレーション関数は変更しない（Open-Closed 原則）

---

## テスト要件 [MANDATORY]

| テスト | 内容 |
|--------|------|
| 直前バージョンからの変換 | v(N-1) → vN が正しく変換される |
| 多段マイグレーション | v1 → vN の段階的変換が正しく動作する |
| 冪等性 | 同じ入力に対して同じ出力を返す |
| エラー時ロールバック | マイグレーション中のエラーで元データが返される |
| 将来バージョンスキップ | 検出バージョン > CURRENT_VERSION でスキップされる |
| バージョン検出失敗 | 検出失敗時に v1 として扱われる |

---

## 実装例

forge プラグインの `.doc_structure.yaml` マイグレーション:

- スクリプト: `${CLAUDE_PLUGIN_ROOT}/scripts/migrate_doc_structure.py`
- 設計書: `docs/specs/forge/design/doc_structure_version_management_design.md`
