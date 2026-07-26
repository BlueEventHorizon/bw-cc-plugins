# ADR-042 msg-sys（汎用通信基盤）と msg-review（応用レビューシステム）の分離維持

> **本決定は ADR-043 により撤回された（superseded）。** msg-review（REQ-011/DES-040）は msg-sys（REQ-006/DES-034）へ正式に merge 済みであり、`docs/specs/msg-review/` は削除されている。以下は撤回された決定の経緯として保持する（削除しない）。

## メタデータ

| 項目     | 値               |
| -------- | ---------------- |
| ADR ID   | ADR-042          |
| Status   | superseded       |
| 決定日   | 2026-07-18       |
| 関連設計 | DES-034, DES-040 |
| 関連要件 | REQ-006, REQ-011 |

## 1. コンテキスト

`msg-sys`（REQ-006/DES-034）は Claude・Codex 間の汎用エージェント間メッセージング基盤（送受信・履歴・hook 登録の仕組み）として設計された。`msg-review`（REQ-011/DES-040）はその上に構築された応用機能であり、Stop フックが差し戻すメッセージに「返信ヒント」（実行可能な返信コマンド案内）を付加することで、レビュー対話における受信側 AI の自己完結的な応答を可能にする。

msg-review の全実装タスク（TASK-001〜006）が完了した時点で、`additive_development_spec.md` §4 の通常フローに従い `/forge:merge-specs msg-sys msg-review` による本体仕様への統合を開始した。しかし、この統合作業の途中で以下の懸念が指摘された。

msg-review の仕様（REQ-011/DES-040）を msg-sysの仕様（REQ-006/DES-034）へ内容レベルで merge すると、msg-sys 自体の設計書が「返信ヒント付きレビュー対話のための仕組み」であるかのように読める記述に変質してしまう。しかし msg-sys の本来の価値は、レビュー対話に限らない汎用のエージェント間メッセージング基盤である点にある。将来 msg-sys を独立したプラグインとして切り出し、レビュー対話以外の用途（例: 複数エージェント間の任意の非同期タスク連携）にも配布・応用する可能性を考えると、msg-sys の仕様書がレビュー用途に特化した記述で汚染されることは、その汎用基盤としての再利用性を損なう。

## 2. 決定

**msg-sys（REQ-006/DES-034）と msg-review（REQ-011/DES-040）は、実装完了後も文書として merge せず、恒久的に別 feature として維持する。**

- msg-review の要件定義書・設計書からは `type: temporary-feature-*` frontmatter を外し、「実装完了後に旧仕様へ merge され削除される予定の一時文書」という位置づけを撤回する
- msg-review の仕様書は、msg-sys の CLI（`send.py` / `inbox.py` / `lib/notify.py`）を**外部依存として参照**する応用仕様として、`docs/specs/msg-review/` に恒久的に存置する
- msg-sys 側の仕様書は、msg-review が存在する事実に関する記述を一切追加しない（依存の向きは msg-review → msg-sys の一方向のみとし、逆方向の言及を持たない）
- 本 feature の実装は `/forge:merge-specs` による統合を実施しない。計画書（`msg-review_plan.yaml`・`msg-review_strategy.md`）のみ、実装完了済みの一時文書として通常どおり破棄可能とする（`additive_development_spec.md` §4 の「計画 → 破棄」原則は plan 文書には引き続き適用する）

## 3. 検討した代替案

| 代替案                                                                             | 棄却理由                                                                                                                                                               |
| ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/forge:merge-specs msg-sys msg-review` をそのまま実行し本体仕様へ統合する         | msg-sys の設計書がレビュー対話専用の記述に変質し、独立プラグイン化を含む将来の汎用応用可能性を損なう                                                                   |
| msg-review を独立 feature として残しつつ、DES-034 に msg-review への言及だけ加える | msg-sys → msg-review の依存が発生し、msg-sys 単体を切り出した際に不要な参照が残る。依存の方向は応用側（msg-review）→基盤側（msg-sys）の一方向であるべき                |
| msg-sys を本 ADR のタイミングで即座に独立プラグイン化する                          | プラグイン分割は配布・マーケットプレイス構成に関わる別種の意思決定であり、本 ADR のスコープ（文書統合方針）を超える。将来必要になった時点で別途 ADR/設計判断として扱う |

## 4. 影響

- `docs/specs/msg-review/requirements/REQ-011_msg_review_reply_protocol_spec.md` と `docs/specs/msg-review/design/DES-040_msg_review_reply_protocol_design.md` の frontmatter を `type: temporary-feature-*` から恒久文書相当の記述へ改訂する（別途対応）
- `docs/specs/msg-review/plan/` 配下（`msg-review_plan.yaml`・`msg-review_strategy.md`）は実装完了済みのため通常の plan 破棄フローに従う（本 ADR の対象外）
- `docs/specs/msg-sys/`（REQ-006/DES-034）は msg-review 由来の内容 merge を受けない。merge 作業は中止済みである（ディレクトリ名は forge-msg から msg-sys へ改称済みだが、これは本 ADR の merge 中止決定とは独立した別途のリネーム作業である）
- 将来 msg-sys を独立プラグインとして切り出す判断が行われる場合、本 ADR が「msg-sys は汎用基盤である」という前提の根拠として参照される

## 5. ステータス履歴

| 日付       | Status     | 備考                                                                                                                                                                         |
| ---------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-07-18 | accepted   | merge-specs 実行途中で発見された分離要件を記録                                                                                                                               |
| 2026-07-18 | superseded | ADR-043 により撤回。本 ADR の前提（§1「msg-sys 自体がレビュー対話専用の記述に変質する」）が誤りだったと判明したため、msg-review を正式に msg-sys へ merge する方針へ転換した |
