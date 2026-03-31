# forge 実装計画書

## 1. 要件トレーサビリティマトリクス

| ✓ | 要件ID  | タイトル             | 設計ID  |
| - | ------- | -------------------- | ------- |
| ☑ | FNC-001 | オーケストレータ設計 | DES-010 |
| ☑ | FNC-002 | セッションディレクトリ通信 | DES-010 |
| ☑ | FNC-003 | 参照文書の自己完結性 | DES-010 |
| ☑ | FNC-004 | 並列実行可能な構造   | DES-010 |

## 2. 設計トレーサビリティマトリクス

| 設計ID  | タイトル                                | 要件ID                          | タスクID                                    |
| ------- | --------------------------------------- | ------------------------------- | ------------------------------------------- |
| DES-010 | create-* スキル オーケストレータ化設計書 | FNC-001, FNC-002, FNC-003, FNC-004 | TASK-001〜TASK-007 |

## 3. タスク一覧

| ✓ | 優先度 | タスクID | タイトル | やるべき内容 | 設計ID | 依存関係 | グループID | 受け入れ基準 | 必読 |
| - | ------ | -------- | -------- | ------------ | ------ | -------- | ---------- | ---------- | ---- |
| ☑ | 90 | TASK-001 | context_gathering_spec.md 作成 | ・コンテキスト収集 agent 用の自己完結型仕様書を新規作成<br>・DES-010 Section 3.5 のプロンプトテンプレートを仕様書に移行<br>・specs/rules/code 各 agent の収集手順を記載<br>・refs/{category}.yaml の出力スキーマを記載<br>・/query-specs, /query-rules の使い方と .doc_structure.yaml フォールバック手順を記載 | DES-010 | - | - | 仕様書が自己完結型であること | [create_skills_orchestrator_design.md](../design/create_skills_orchestrator_design.md), [session_format.md](../../../../plugins/forge/docs/session_format.md) |
| ☑ | 85 | TASK-002 | orchestrator_session_protocol.md 更新 | ・session.yaml 共通フィールドに resume_policy を追加<br>・許容値 `resume`（デフォルト）/ `none` を定義<br>・セッションライフサイクル表に resume_policy に基づく分岐を追加<br>・残存セッション検出時の処理フローを明記 | DES-010 | - | - | resume_policy の許容値・分岐フローが定義されていること | [session_format.md](../../../../plugins/forge/docs/session_format.md) |
| ☑ | 80 | TASK-003 | start-design SKILL.md オーケストレータ化 | ・前提確認 Step 5 から /query-rules を削除（defaults のみに変更）<br>・セッション作成フェーズを追加（session_dir + session.yaml + refs/）<br>・コンテキスト収集フェーズを追加（specs/rules/code 3 agent 並列）<br>・refs/ 統合・表示フェーズを追加<br>・Phase 1.1 を refs/specs.yaml 読み込みに変更<br>・Phase 1.4 を refs/code.yaml 読み込みに変更<br>・残存セッション検出フローを追加（Section 6.4）<br>・セッション削除を完了処理に追加 | DES-010 | TASK-001, TASK-002 | - | `/forge:start-design` でセッションディレクトリが作成されること | [create_skills_orchestrator_design.md](../design/create_skills_orchestrator_design.md), [create_design_workflow_design.md](../design/create_design_workflow_design.md) |
| ☑ | 80 | TASK-004 | start-plan SKILL.md オーケストレータ化 | ・前提確認 Step 4 から /query-rules を削除（defaults のみに変更）<br>・セッション作成フェーズを追加<br>・コンテキスト収集フェーズを追加（specs + rules 2 agent、code は不要）<br>・rules agent は /query-rules 利用可能時のみ実行し、不可時は skip する（DES-010 Section 4.2 適用マトリクス参照）<br>・refs/ 統合・表示フェーズを追加<br>・Phase 1.1 を refs/specs.yaml 読み込みに変更<br>・残存セッション検出フローを追加<br>・セッション削除を完了処理に追加 | DES-010 | TASK-001, TASK-002 | - | `/forge:start-plan` でセッションディレクトリが作成されること | [create_skills_orchestrator_design.md](../design/create_skills_orchestrator_design.md), [create_plan_workflow_design.md](../design/create_plan_workflow_design.md) |
| ☑ | 80 | TASK-005 | start-requirements SKILL.md オーケストレータ化 | ・前提確認 Step 3 から /query-rules を削除（defaults のみに変更）<br>・Phase 0.3 を削除（コンテキスト収集フェーズに統合）<br>・セッション作成フェーズを追加<br>・コンテキスト収集フェーズを追加（モード依存: rules 常時、specs は --add 時、code は reverse-engineering 時）<br>・refs/ 統合・表示フェーズを追加<br>・reverse-engineering Phase 1 を refs/code.yaml 起点に変更<br>・残存セッション検出フローを追加<br>・セッション削除を完了処理に追加 | DES-010 | TASK-001, TASK-002 | - | `/forge:start-requirements` でセッションディレクトリが作成されること | [create_skills_orchestrator_design.md](../design/create_skills_orchestrator_design.md), [create_requirements_workflow_design.md](../design/create_requirements_workflow_design.md) |
| ☑ | 50 | TASK-006 | 設計書を正式ディレクトリに移動 | ・docs/specs/next_forge/design/create_skills_orchestrator_design.md を docs/specs/forge/design/ に移動<br>・/create-specs-index を実行して ToC を更新<br>・next_forge ディレクトリが空なら削除 | DES-010 | TASK-003, TASK-004, TASK-005 | - | `/create-specs-index` が正常完了すること | - |
| ☑ | 40 | TASK-007 | バージョン更新 | ・/update-version forge patch でバージョンをインクリメント<br>・CHANGELOG.md に変更内容を記録 | DES-010 | TASK-006 | - | `python3 tests/test_plugin_integrity.py` が全パスすること | - |

### 優先度の目安

- 高（70〜99）: コアビジネスロジック・共通基盤・ブロッカー解消
- 中（40〜69）: 主要機能
- 低（1〜39）: UI・補助機能

## 4. 改定履歴

| 日付 | 内容 |
| ---- | ---- |
| 2026-03-13 | 初版作成 |
