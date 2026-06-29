# path_schema_unification 実装戦略

> 本文書は ephemeral。実装完了後に削除する (ADR-032 / additive_development_spec.md §4)。
> SoT は `docs/specs/forge/design/ADR-032_path_schema_unification.md`。

## 戦略選択: ボトムアップ + ドキュメント先行

ADR-032 は **breaking change な cross-cutting refactor** であり、新機能追加ではない。リスク駆動でもなく、フィーチャー縦断スライスでもない。最も適切な戦略は:

1. **ドキュメント先行**: `session_format.md` の schema 章を新 schema に書き換えてから、それを参照しながら実装を進める
2. **入口 → 出口**: validation 層 (write_refs.py) を新 schema 専用に切り替えてから、readers を順次対応させる
3. **session.yaml は並列**: refs.yaml の修正と独立に進められる (依存先: session_format.md のみ)
4. **文書同期は遅延 OK**: SKILL.md / 設計書の例 YAML は実装が固まった後に同期しても整合性に影響しない

## なぜ「フィーチャースライス」ではないか

ADR-032 は新規機能ではなく **既存パイプラインの schema 統一**。スライスは「機能の縦断」だが、本件は「同じ schema を全レイヤーで採用する」横断改修。スライス戦略は不適合。

## なぜ「スケルトン先行」ではないか

skeleton は新規システム立ち上げの戦略。本件は既存システムを breaking change で書き換える。skeleton 経路は採れない。

## フェーズ分割と build_check ポリシー

| Phase                      | タスク             | build_check 戦略                                               |
| -------------------------- | ------------------ | -------------------------------------------------------------- |
| 1. docs-first              | TASK-001           | skip (docs のみ、コード触らず)                                 |
| 2. validation + writer     | TASK-002, TASK-003 | on_group_complete (write_refs と test を 1 group で一気に切替) |
| 3. session.yaml            | TASK-004           | per_task (session_manager 完結)                                |
| 4. readers                 | TASK-005           | per_task (agents + scripts、unit test で検証)                  |
| 5. SKILL.md + agent prompt | TASK-006           | per_task (docs と prompt のみだが、grep で検証)                |
| 6. DES 例 YAML             | TASK-007           | skip (docs のみ)                                               |
| 7. 受け入れ                | TASK-008           | per_task (final verification)                                  |
| 8. ADR status              | TASK-009           | skip (metadata 更新のみ)                                       |

## 並列性

TASK-001 が完了すれば、以下は並列実行可能:

- TASK-002+003 (GROUP-WRITE)
- TASK-004 (session.yaml)
- TASK-006 (SKILL.md)
- TASK-007 (DES 例)

TASK-005 (readers) は TASK-003 (writer) 完了後に着手すべき。さもないと writer/reader 不整合で動作不能セッションが生まれる。

## リスクと緩和

| リスク                                                               | 影響                              | 緩和                                                                                                        |
| -------------------------------------------------------------------- | --------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| writer 切替後 reader 未対応で全 review が壊れる                      | 全 forge:review 不能              | TASK-005 を TASK-003 直後に最優先で実施。GROUP-WRITE の build_check が green の間は merge しない            |
| 既存セッション (`.claude/.temp/review-*`) が新 schema で読めなくなる | 進行中セッション喪失              | breaking change の前に進行中セッションを `review_session.py finish` で全 cleanup する旨を実装着手時に確認   |
| Issue #99 で `doc_path` 採用を決めた経緯を忘れて再混乱               | ADR-032 を覆される回帰            | ADR-032 §「Issue #99 の経緯」と「代替案 3: ssot_refs の doc_path を維持」で明文化済み。改定履歴で固定       |
| general-purpose agent (#11) の構造化 prompt が遵守されない           | related_code 探索の出力が解釈不能 | TASK-006 で prompt に「以下の構造化形式で返せ、自由 markdown は禁止」と明示。実観測で違反したら prompt 強化 |
