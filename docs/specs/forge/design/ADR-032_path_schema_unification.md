# ADR-032: refs.yaml / session.yaml のパス系フィールド標準化

## メタデータ

| 項目       | 値                                                                   |
| ---------- | -------------------------------------------------------------------- |
| 設計ID     | ADR-032                                                              |
| 種別       | ADR                                                                  |
| 関連       | DES-011 / DES-015 / DES-028 / DES-029、Issue #99 (本 ADR で一部覆す) |
| 作成日     | 2026-06-29                                                           |
| ステータス | proposed                                                             |

---

## コンテキスト

`/forge:review` パイプライン (review orchestrator / reviewer / evaluator / fixer / present-findings) が扱う「パスを持つフィールド」は現在 11 箇所に存在し、形式が以下のように非対称である:

| #  | 出現箇所                                       | 現状形式                           |
| -- | ---------------------------------------------- | ---------------------------------- |
| 1  | refs.yaml `target_files[]`                     | 文字列配列                         |
| 2  | refs.yaml `reference_docs[]`                   | `[{path}]`                         |
| 3  | refs.yaml `related_code[]`                     | `[{path, reason, lines?}]`         |
| 4  | refs.yaml `review_packet.ssot_refs[]`          | `[{doc_path, priority, doc_type}]` |
| 5  | refs.yaml `review_packet.criteria_path`        | 単一文字列                         |
| 6  | refs.yaml `review_packet.severity_source`      | 単一文字列                         |
| 7  | refs.yaml `review_packet.output_path`          | ファイル名のみ (session_dir 内)    |
| 8  | session.yaml `files[]`                         | 文字列配列                         |
| 9  | `resolve_review_context.py` 返却 JSON          | 文字列配列                         |
| 10 | `query-db-specs` 返却 (DocAdvisor)             | テキスト箇条書きパスリスト         |
| 11 | general-purpose agent 返却 (related_code 探索) | 自由 markdown                      |

### 観測された問題

- 同じ「project-root-relative パスのリスト」なのにキー名 (`target_files` vs `reference_docs`) も要素型 (string vs `{path}`) も違うため、refs JSON を AI が手で組み立てる際にスキーマ違反が頻発する (`/forge:review design` セッション 2026-06-29 で実観測)
- ssot_refs だけ `doc_path` で他は `path` という命名割れ
- `write_refs.py` validation が `reference_docs[]` の要素を盲目的に `.get()` して `AttributeError` を投げる回帰 (bb0a85a で型チェック追加済みだが、根本は schema 不揃いに起因)
- 上流 (#9 / #10 / #11) から refs.yaml への変換責務が SKILL.md に明文化されておらず AI 任せ

### Issue #99 (closed PR #113) の経緯

Issue #99 で `ssot_refs[].path` → `doc_path` に改名したが、当時の根拠は「DES-028 / evaluator/reviewer/present-findings SKILL の文書側がすでに `doc_path` を使っていた」という多数派合わせのみで、深い設計原則ではない。本 ADR ではこの決定を覆す。

---

## 決定

### 標準形式

```yaml
# 単一スカラー形式 (path1) — 単独の文字列フィールド
<field>: <project-root-relative path>

# パスリスト形式 (pathN) — 配列要素は常に dict、path 必須
<field>:
  - path: <project-root-relative path> # 必須
    reason: <string> # 任意 (related_code で必須)
    lines: "<start>-<end>" # 任意
    priority: P1 | P2 | P3 # 任意 (ssot_refs で必須)
    doc_type: rules | principles | format # 任意 (ssot_refs で必須)
```

### 全 11 形式の適用方針

| #  | フィールド                            | 現状形式                           | 適用後                                              | 変更性質                         |
| -- | ------------------------------------- | ---------------------------------- | --------------------------------------------------- | -------------------------------- |
| 1  | refs.yaml `target_files[]`            | 文字列配列                         | `[{path}]`                                          | **形式変更**                     |
| 2  | refs.yaml `reference_docs[]`          | `[{path}]`                         | `[{path}]`                                          | 現状維持                         |
| 3  | refs.yaml `related_code[]`            | `[{path, reason, lines?}]`         | `[{path, reason, lines?}]`                          | 現状維持                         |
| 4  | refs.yaml `ssot_refs[]`               | `[{doc_path, priority, doc_type}]` | `[{path, priority, doc_type}]`                      | **改名 (Issue #99 を覆す)**      |
| 5  | refs.yaml `criteria_path`             | 単一文字列                         | 単一文字列                                          | 現状維持                         |
| 6  | refs.yaml `severity_source`           | 単一文字列                         | 単一文字列                                          | 現状維持                         |
| 7  | refs.yaml `output_path`               | ファイル名のみ                     | `output_filename` にリネーム                        | **改名**                         |
| 8  | session.yaml `files[]`                | 文字列配列                         | `[{path}]`                                          | **形式変更**                     |
| 9  | `resolve_review_context.py` 返却 JSON | 文字列配列                         | `[{path}]`                                          | **形式変更 (#1 と同期)**         |
| 10 | `query-db-specs` 返却                 | テキスト箇条書き                   | (現状維持、スコープ外)                              | スコープ外: 外部 DocAdvisor 依存 |
| 11 | general-purpose agent 返却            | 自由 markdown                      | prompt で `- path: ...`<br>`reason: ...` 形式を強制 | **prompt 改訂**                  |

### 設計原則

1. **パスリストは常に dict 配列**: 「文字列配列」と「dict 配列」の使い分けを廃止する。dict にすることで将来 metadata を追加するときに schema breaking change にならない
2. **キー名は `path` に統一**: `doc_path` / `output_path` (リネーム後 `output_filename`) を除き、外部参照パスはすべて `path` を使う
3. **`output_filename` は別概念として明示**: session_dir 内の出力先ファイル名は path ではなく「sandbox 内のファイル名」であり、`^review_[a-z0-9_-]+\.md$` 制約があるため別フィールド名を与える
4. **後方互換層なし**: breaking change として一括切替。旧 schema のセッションは存在しない (`.claude/.temp/` はセッション完了で消える) ため互換性負債を残さない

### スコープ外

- **#10 `query-db-specs` 返却の構造化**: 外部 plugin `BlueEventHorizon/DocAdvisor` の出力契約。改修依頼は別 Issue として記録する (`Required documents:` テキストから `[{path}]` 配列への変換は呼び出し側 SKILL の責務として明記する)
- **`session.yaml` の flat YAML 原則**: §8 で `files[]` を `[{path}]` に変えることで session.yaml は scalar/array のみという原則が崩れる。本 ADR ではこれを受け入れる (代わりに session_format.md §3 に「files[] は path entry 配列、他のメタフィールドは flat scalar」という明示的な区分を書く)

---

## 影響範囲 (実装計画は別途 `/forge:start-plan` で立てる)

### コード

| カテゴリ              | 対象ファイル (代表)                                                                               |
| --------------------- | ------------------------------------------------------------------------------------------------- |
| validation            | `plugins/forge/scripts/session/write_refs.py` / `session_manager.py` / `init_session.py`          |
| reviewer 経路 readers | `plugins/forge/agents/reviewer.md` / `skills/review/scripts/extract_review_findings.py`           |
| evaluator 経路        | `plugins/forge/agents/evaluator.md` / `scripts/session/apply_eval.py` / `write_interpretation.py` |
| fixer 経路            | `plugins/forge/agents/fixer.md` / `scripts/fixer/*.py`                                            |
| present-findings      | `plugins/forge/skills/present-findings/SKILL.md` + scripts                                        |
| review orchestrator   | `plugins/forge/skills/review/SKILL.md`                                                            |
| 共通                  | `plugins/forge/scripts/session/*.py`                                                              |

### 文書 (SoT)

- `plugins/forge/docs/session_format.md` — refs.yaml / session.yaml の schema 章を全面改訂
- `docs/specs/forge/design/DES-011 / DES-014 / DES-015 / DES-028 / DES-029` — 例 YAML を新 schema に同期

### テスト

- `tests/forge/scripts/session/test_write_refs.py` — `ssot_refs[].doc_path` → `path` に書き換え、`target_files[]` dict 形式の受理確認を追加
- 旧 schema を渡したときの reject 回帰テストを追加

---

## 代替案 (採用せず)

### 代替案 1: 現状維持 + SKILL.md 説明強化のみ (B 案)

`refs JSON のスキーマ SoT` を SKILL.md に書くだけで、形式の非対称は維持する。今回 (bb0a85a) で実施済みだが、根本原因 (異種スキーマの併存) は解消しない。AI が refs JSON を組み立てる際の認知負荷が残り、`/forge:query-db-specs` 返却 (#10) を `[{path}]` に変換する手作業も残る。

採用しない理由: 同じ「パスリスト」が 4 種類の異なる形式で存在し続けると、新しいフィールドを足すたびに「string か dict か」「どのキー名か」を毎回判断する必要があり、ドリフトを誘発する。

### 代替案 2: 後方互換層を 1 sprint だけ受理 (C 案)

`write_refs.py` で旧 schema (文字列配列 / `doc_path`) を受理し warning を出す層を作る。

採用しない理由: 旧 schema を作る作者は AI orchestrator 自身であり、新 schema のみを書くよう SKILL.md を更新すれば旧 schema は発生しない。`.claude/.temp/` のセッションは完了で消えるので persistent な互換性負債はない。互換層は誰のためでもない (本 ADR 議論で確認済み)。

### 代替案 3: ssot_refs の `doc_path` を維持 (Issue #99 を尊重)

ssot_refs のみ `doc_path` を残し、`target_files` / `session.yaml.files[]` のみ dict 化する。

採用しない理由: 統一の半端な達成にしかならず、「path フィールドが `path` か `doc_path` か」の判断が引き続き必要。Issue #99 の根拠 (多数派合わせ) が脆弱なため、ssot_refs を含めて全面統一する方が長期保守性が高い。

---

## 受け入れ条件

- refs.yaml / session.yaml の schema が単一の標準形 (`{path, ...optional metadata}`) で表現される
- `path` 以外のパス系キー名は `output_filename` のみ (= sandbox 内ファイル名であることが名前で読める)
- 全 SKILL.md / agent 定義 / scripts / docs / tests が新 schema に揃う
- 旧 schema (`doc_path` / `output_path` / 文字列配列 `target_files`) を渡したら明示的 ValueError で reject される
- 受け入れ確認用 grep が clean:
  - `grep -rn "ssot_refs.*doc_path\|doc_path:" plugins/ docs/specs/forge/ tests/` → 0 件
  - `grep -rn "output_path:" plugins/forge/docs/ plugins/forge/skills/ docs/specs/forge/` → 0 件 (`output_filename` に置換済み)
  - 既存 unit test 全 pass

---

## 改定履歴

| 日付       | 変更内容                                                                                    |
| ---------- | ------------------------------------------------------------------------------------------- |
| 2026-06-29 | 初版 (`/forge:review design` 実行時に発見された pipeline 自体の不具合 #1〜#11 を起点に作成) |
