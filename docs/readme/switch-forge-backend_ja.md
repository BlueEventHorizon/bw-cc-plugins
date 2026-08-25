# forge backend の切り替え

forge には差し替え可能な backend が 2 軸ある。

| 軸               | 候補                                     | 使うスキル                                                                         |
| ---------------- | ---------------------------------------- | ---------------------------------------------------------------------------------- |
| 文書検索 backend | doc-advisor（既定先位）/ doc-db          | `/forge:query-db-rules` / `query-db-specs` / `update-db-rules` / `update-db-specs` |
| レビュー実行主体 | agent-review（既定第一候補）/ msg-review | `/forge:review`                                                                    |

どちらもプロジェクト設定ファイル `.claude/.forge.yaml`（プロジェクトルート相対）で切り替える。ファイルは任意であり、無ければ既定動作になる。

## 設定ファイルの書き方

```yaml
# .claude/.forge.yaml
doc_backend:
  prefer: doc-db # doc-db | doc-advisor

review:
  backend: msg-review # agent-review | msg-review
```

### `doc_backend.prefer`（文書検索 backend）

- 指定した backend が順序リストの先位になる（例: `doc-db` を指定すると `["doc-db", "doc-advisor"]`）。未指定の既定は doc-advisor 先位
- 先位の backend が利用不能な場合は、理由を通知して後位の backend を利用する
- 許容キーは `prefer` のみ。未知のキー・2 値以外の値は明示エラーになる（黙って既定動作へ落ちない — 設定したつもりで効いていない状態を防ぐため）

### `review.backend`（レビュー実行主体）

- 指定した backend **だけ**で実行する（明示指定扱い）。利用不能でも代替を選ばず、依頼を送らずにエラー終了する（fail closed）
- 未指定なら候補順（agent-review → msg-review）で可用性を検査して採用する
- 許容キーは `backend` のみ

## 引数による強制指定（設定より優先）

| スキル                                       | 引数                            | 挙動                                              |
| -------------------------------------------- | ------------------------------- | ------------------------------------------------- |
| `/forge:update-db-rules` / `update-db-specs` | `--backend doc-db\|doc-advisor` | 指定 backend のみを使う。利用不能なら fail closed |
| `/forge:review`                              | `--backend <name>`              | 同上                                              |
| `/forge:query-db-rules` / `query-db-specs`   | （このフラグを持たない）        | 常に順序リストで決まる                            |

優先順位は **引数 > `.claude/.forge.yaml` > 既定の候補順**。

## 注意

- `.claude/.forge.yaml` は制約付き YAML サブセットとして読まれる。アンカー・エイリアス（`&` / `*`）、複数行文字列（`|` / `>`）、flow style（`[...]` / `{...}`）は使えず、含まれるとファイル全体が解析不能として明示エラーになる
- レビュー実行主体の候補順の設計根拠・各バックエンドの前提条件は [guide_review_ja.md](forge/guide_review_ja.md) を参照
