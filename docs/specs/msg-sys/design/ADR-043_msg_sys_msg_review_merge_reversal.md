# ADR-043 msg-review の msg-sys への正式統合（ADR-042 の撤回）

## 1. コンテキスト

ADR-042 は「msg-sys（汎用通信基盤）と msg-review（応用レビューシステム）は恒久的に別 feature として維持する」と決定した。根拠は、msg-review の内容（返信ヒント）を msg-sys の設計書へ merge すると、msg-sys 自体が「レビュー対話専用の仕組み」であるかのように読める記述に変質し、将来の独立プラグイン化・汎用応用可能性を損なう、というものだった。

この決定を踏まえて実装・運用を続けたところ、以下の事実が確認された。

- `hooks/check_inbox.py`（msg-review として実装したもの）は、Claude/Codex 双方の Stop フック登録（`.claude/settings.json` / `.codex/hooks.json`）から実際に呼ばれる **本番の hook 実装そのもの**であり、旧 bash 実装（`hooks/claude-check-inbox.sh` / `hooks/codex-check-inbox.sh`）を置き換えている。「msg-sys の上に構築された応用機能」ではなく、msg-sys の hook 実装が Python へ移行しただけである
- 返信ヒント機能（FNC-003/FNC-004/BL-001）は、レビュー対話に限定される性質を一切持たない。Claude/Codex 間で任意の非同期メッセージを往復する際に、受信側が自己完結的に返信できるようにするための汎用機能であり、msg-sys の他のユースケース（レビュー対話に限らない任意のエージェント間タスク連携）にもそのまま適用できる
- ADR-042 が懸念した「msg-sys がレビュー専用に変質する」という問題は、実際には発生しない。返信ヒントは msg-sys の Stop フック契約（`decision:block` の `reason` に何を含めるか）の話であり、レビューという用途に依存する記述を一切含まない

すなわち、ADR-042 の前提（msg-review が msg-sys とは独立した「応用」であり、両者の分離が msg-sys の汎用性を守る）は誤りだった。実態は「msg-review という別名がついていただけで、中身は msg-sys そのものの hook 実装だった」。

## 2. 決定

**msg-review（REQ-011/DES-040）を msg-sys（REQ-006/DES-034）へ正式に merge し、ADR-042 の分離決定を撤回する。**

- `/forge:merge-specs msg-sys msg-review` を実行し、REQ-011 の内容は REQ-006 §3（FNC-003/FNC-004/BL-001 として採番）へ、DES-040 の内容は DES-034 の該当各節へ統合する
- DES-034 の Stop フック記述は、旧 bash 実装（`hooks/claude-check-inbox.sh` / `hooks/codex-check-inbox.sh`）ベースの記述から、本番実装である `hooks/check_inbox.py`（返信ヒント付き・Python・単一スクリプト）ベースの記述へ更新する
- `docs/specs/msg-review/` は統合完了後に削除する
- ADR-042 は削除せず、その決定節へ失効マーカーを付けて撤回の経緯を残す（判断が誤りだったことも含めて記録に残す価値がある）

## 3. 検討した代替案

| 代替案                                                           | 棄却理由                                                                                                                                                                                               |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| ADR-042 の分離方針を維持し、msg-review を独立 feature のまま残す | 実態（`check_inbox.py` が msg-sys の本番 hook 実装そのものであること）と文書構造が乖離し続け、次に読む人が「msg-sys とは別に応用機能がある」という誤った理解をする                                     |
| ADR-042 を削除して無かったことにする                             | 一度その方針で実装・運用した経緯（frontmatter 改訂・plan 破棄等）が記録から失われ、同じ議論を将来繰り返すリスクがある。ADR は誤った決定も含めて残す価値がある（`additive_development_spec.md` の精神） |

## 4. 影響

- `docs/specs/msg-sys/requirements/REQ-006_codex_review_messaging.md` に FNC-003（返信ヒントの自己完結性）・FNC-004（双方向適用）・BL-001（内容一貫性）を追加した
- `docs/specs/msg-sys/design/DES-034_codex_review_messaging_design.md` の §1〜9 を `check_inbox.py` ベースの記述に更新し、返信ヒントの実行可能性契約・エラーフロー・テスト設計（54 ユニットテスト + 自律往復の実機検証）を統合した
- `docs/specs/msg-review/` ディレクトリを削除した
- コード側（`plugins/forge/scripts/msg-review/hooks/check_inbox.py` → `plugins/forge/scripts/msg-sys/hooks/check_inbox.py`、`tests/forge/msg-review/test_check_inbox.py` → `tests/forge/msg-sys/test_check_inbox.py`）もユーザー確認のうえリネームし、仕様と実装のディレクトリ構成を一致させた。`.claude/settings.json` / `.codex/hooks.json` の登録パスも追従修正した（Codex 側は登録内容のハッシュが変わるため、次回起動時に `/hooks` での再 trust 登録が必要）
