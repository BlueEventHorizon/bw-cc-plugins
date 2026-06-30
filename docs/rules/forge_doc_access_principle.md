# forge ドキュメントアクセス原則

forge プラグインの**開発ルール**。forge 内部 (SKILL / agent / scripts) からドキュメントに**どう到達するか**を定める。配布物ではなく、この repo の開発者が遵守する設計原則。

## 2 つの経路のみ

| 経路            | 対象                                                                      | 方式                                                        |
| --------------- | ------------------------------------------------------------------------- | ----------------------------------------------------------- |
| **A. 直接参照** | forge 内蔵 docs (`plugins/forge/docs/*`, `plugins/forge/skills/*/docs/*`) | パスを直接書く: `${CLAUDE_PLUGIN_ROOT}/docs/xxx.md` を Read |
| **B. クエリ**   | プロジェクト固有 spec / rules (`docs/specs/`, `docs/rules/`)              | `/forge:query-db-specs` / `/forge:query-db-rules` を呼ぶ    |

それ以外の経路 (例: session_dir / refs/*.yaml を介したファイル受け渡し) は採用しない。

## なぜこの 2 経路だけか

- **forge 内蔵 docs**: forge プラグイン自身のリリースで参照箇所と一緒に更新できる → 固定パスが腐らない → 直接参照が最短
- **プロジェクト spec/rules**: プロジェクト側で増減・改廃が頻繁 → 固定パスは腐る → クエリ動的発見が必要

## やってはいけない (アンチパターン)

- **forge 内蔵 docs をクエリで探す**: 固定パスで済むのに動的解決を挟む冗長
- **プロジェクト spec のパスを SKILL.md に直書き**: パスが腐る、保守コスト爆発 (doc-advisor の存在意義)
- **forge 内部ロジックを「内蔵 doc」として書く**: doc は宣言的に読み取るもの。手続きは SKILL.md / scripts に閉じる
- **agent への引数として `session_dir` を渡し、ファイル経由で結果を受ける**: Agent return value で代替可能で、第三の経路を作るだけ

## 外部利用 (参考)

プロジェクト側ユーザーが forge 内蔵 docs を読みたい場合は `/forge:query-forge-rules` を使う。これは forge 内部の使い方ではなく、forge を外から利用するための入口で本原則の対象外。

## 関連

- 設計判断の根拠: 削除された `context_gathering_spec.md` (forge 内蔵 doc で「プロジェクト spec の検索手順」を定義していた矛盾) と session/refs 機構の撤廃 (start 系から)
- query 経路の実装: `plugins/forge/skills/query-db-specs/`, `plugins/forge/skills/query-db-rules/`, `plugins/forge/skills/query-forge-rules/`
