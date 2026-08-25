# agenda 実装戦略

## アプローチ

**選択**: ボトムアップ（依存の薄い基盤モジュールから積み上げる）＋各フェーズにリスク駆動の検証観点を組み込む

**根拠**:

このFeatureは新規実装ではなく**旧実装の全面置き換え**である。`plugins/forge/scripts/agenda/agenda_schema.py`・`agenda_store.py`・`agenda_render.py`は既にcommit済みだが、いずれも承認済み設計（DES-075/077）と異なる旧CLI契約（`status_vocabulary`/`terminal_statuses`/`active_statuses`、`current_item_id`/`set-current`、`agenda_state.js`によるポーリング部分更新、`--set key=value`）で書かれている。実体を読んで確認した結果、3ファイルとも新設計と字面・構造の両面で非互換であり、部分修正では収束しない（例: `agenda_render.py`は`render_agenda_state_js()`・ポーリング`<script>`・スクロール保持`<script>`という新設計に存在しない責務を丸ごと持つ）。

モジュール間の依存はDES-075 §3.1が明示する一方向グラフである: `agenda_store.py` → `agenda_schema.py`（状態遷移契約）、`agenda_store.py` → `agenda_render.py`（書き込み成功後の自動呼び出し）。`agenda_schema.py`と`agenda_render.py`は互いに依存せず、`agenda_store.py`にも依存されるだけで依存しない（独立実行可能）。この形は「安定した基盤から積み上げる」ボトムアップに適合する。加えて、新設計の中核ロジック（`decision`キーの有無だけで状態を判定する構造遷移契約）は本Featureで最もリスクが高い部分（後述リスク表）であるため、最初のフェーズに配置し早期に手戻りを検出する（リスク駆動の要素を最初のフェーズへ混ぜる）。

フェーズ分割と依存順序は、タスク依頼で既に指定された順序（agenda_schema.py→agenda_render.py→agenda_store.py→tests→discussion_file_template.md→consult SKILL.md→旧討議ファイル破棄）をそのまま採用する。この順序はモジュールの実依存方向と矛盾しない。ただし、「最後のタスクまで検証を先送りしない」という分割原則を満たすため、各フェーズに**そのフェーズ単体で確認できる検証観点**を明示する（フェーズ1・2は完全なユニットテストをフェーズ3へ委ねるが、その間は簡易な手動検証で代替し、無検証のまま2フェーズを積み上げることはしない）。

## フェーズ

### フェーズ 1: 基盤層（`agenda_schema.py` + `agenda_render.py`）の全面書き換え

- **目標**: 状態遷移契約（DES-075 §5.1・§5.1a）と表示生成（DES-077 §3・§4）が、それぞれ独立した純粋関数として新設計どおりに動作する。両モジュールは互いに依存しないため並行に書ける
- **スコープ**:
  - `agenda_schema.py`: `status_vocabulary`/`terminal_statuses`/`active_statuses`を全廃し、`patch_keys`（差分パッチのキー集合）に`decision`を含むかどうかをトリガーとする判定へ置き換える（DES-075 §5.1表）。`verification.action`固定語彙（`adopt`/`reject`）はそのまま維持する。§5.1aの「新規項目追加時は`structural_judgment.note`同時指定必須」という**新規に追加すべき契約**をここで実装する
  - `agenda_render.py`: `current_item_id`・`agenda_state.js`生成・ポーリング`<script>`・スクロール保持`<script>`を全廃する。状態表示は`background`/`essence`/`decision`の記入有無から導出する3状態（未着手/進行中/決着または棄却。DES-077 §3.3のstateDiagram）に置き換える。ガターのドットは`state-dot.changed`のみ残し`state-dot.current`を削除する（DES-077 §3.1）。単一関数`render_agenda_html()`のみを公開する（`render_agenda_state_js()`は削除）
- **検証ポイント**:
  - 両モジュールともbuild_parser等のCLIを持たないため、Pythonの対話実行（`python3 -c`等）で手作りのfixture dictを渡し、`agenda_schema.validate()`が新旧の境界ケース（§5.1a: 新規項目でnote無し→拒否、既存項目更新でnote無し→許可）で期待通りの`{"ok": bool, "missing_fields": [...]}`を返すこと、`agenda_render.render_agenda_html()`が`current_item_id`引数を要求せず、生成HTMLに`agenda_state.js`参照・ポーリングスクリプトが一切含まれないことを目視確認する
  - **正式なユニットテストの導入はフェーズ3**（tests全面書き換え）だが、フェーズ1完了時点を「無検証のまま次へ積む」状態にしないため、上記の簡易確認をこのフェーズの完了条件とする

### フェーズ 2: 統合層（`agenda_store.py`）の全面書き換え

- **目標**: DES-075 §6の5コマンド（`start`/`record`/`next`/`pending`/`finish`）が、フェーズ1で書き換えた`agenda_schema.py`/`agenda_render.py`を正しく呼び出し、CLI全体として一貫動作する
- **スコープ**:
  - `--input-file`による候補JSON受け取り（`--set key=value`を全廃。DES-075 §6.1「AIが渡し方を組み立てない」）
  - `config.identity`の`--path`親ディレクトリ名からの自動導出（§4）、`structural_judgment.recorded`/`recorded_at`の自動導出（呼び出し側は`note`のみ渡す）
  - `upsert_item()`の差分パッチ意味論の書き換え: `structural_judgment`キーはレコード直下へ、それ以外は項目へ振り分ける2経路マージ（§6.1）。`fields`等の入れ子キーはトップレベル単位で丸ごと置換（キー単位の再帰マージをしない）
  - `next_item_id()`/`pending_item_ids()`を`decision`キーの有無で判定するよう置き換え（旧`active_statuses`参照を全廃）
  - `finish`コマンドの新設: 全項目に`decision`が記録されていれば`agenda.json`を削除、残っていれば`remaining_count`を返す（§7）
  - 書き込み成功後の自動再描画（§8.1）を`render_agenda_html()`のみの呼び出しに簡素化（`agenda_state.js`書き込み分岐を削除）。再描画失敗時は`{"status": "partial", ...}`を返す既存方針を維持
- **検証ポイント**:
  - CLIの手動スモークテスト: スクラッチパスに対し`start`（items+structural_judgment.noteをまとめて）→`record`（background/essence）→`record`（decision）→`finish`を順に実行し、各ステップで`agenda.html`が再生成されること、`agenda_state.js`が一切生成されないこと、`finish`が全件decision後に`agenda.json`を削除することをコンソール出力とファイル存在確認で確かめる
  - 旧CLI引数（`--status-vocabulary`等）を渡すと`argparse`が明確なエラーで拒否すること（新旧混在の呼び出しが黙って通らないことの確認）

### フェーズ 3: テスト全面書き換え・スイート通過

- **目標**: `tests/forge/agenda/`配下4ファイル（`test_agenda_schema.py`・`test_agenda_render.py`・`test_agenda_store.py`・`test_agenda_integration.py`、計約1400行）を新契約に基づき全面書き換えし、`python3 -m unittest discover -s tests -p 'test_*.py'`が全体通過する
- **スコープ**:
  - `test_agenda_schema.py`: §5.1の`decision`トリガー判定、§5.1aの新規項目`structural_judgment.note`必須化、`verification.action`語彙・`reject`時の`reason`必須を検証
  - `test_agenda_render.py`: 3状態導出（未着手/進行中/決着）、`current`ドット削除の確認、`severity_field`未指定時のバッジ非表示、`agenda_state.js`関連関数が存在しないこと
  - `test_agenda_store.py`: 5コマンドの正常系・異常系、`identity`自動導出、`structural_judgment`の2経路マージ、`finish`の削除条件
  - `test_agenda_integration.py`: DES-075 §6.2のシーケンス（start→record×N→next/pending→finish）と、各書き込み直後に表示が最新`agenda.json`と一致すること
  - **必須の追加テストケース（既知の未解決事項の再発防止）**: 旧`discussion_file_template.md`の「既知の未解決事項」節が記録していた不具合——検証が特定キー（旧`status`）を含むパッチにのみ発火し、それ以外のパッチは素通りする——は、新設計でも構造的に同型のリスクを持つ。新トリガーは`decision`キーの有無であるため、**「既に`decision`が記録済みの項目に対し、`decision`を含まない差分パッチ（`background`のみ等）で`record`を呼ぶ」ケースを明示的にテストし、新設計がこれをどう扱う（許可するなら意図的な仕様として、拒否するなら拒否として）かを固定する**。DES-075はこの境界を明文化していないため、実装時に挙動を決め、テストとフェーズ4のドキュメント反映（下記リスク表参照）の両方に残す
- **検証ポイント**: `python3 -m unittest discover -s tests -p 'test_*.py' -v`が全件成功し、フェーズ1・2で手動確認した境界ケースが自動テストとして固定化されていること

### フェーズ 4: 呼び出し側・配布物・旧成果物の整理

- **目標**: `consult` SKILLが新CLI契約のみで動作し、表示構造の参照文書が新設計と一致し、旧形式の討議ファイルが残存しない
- **スコープ**:
  - `plugins/forge/skills/consult/assets/discussion_file_template.md`の全面リライト: 3状態導出・`current`ドット廃止・`agenda_state.js`削除・「表示の更新」節（ポーリング記述）の削除、および上記「既知の未解決事項」節を新設計での決定内容（フェーズ3で固定した挙動）に置き換える
  - `plugins/forge/skills/consult/SKILL.md`のPhase 2/4書き換え: `init`→`start`（items+structural_judgment.noteを1回で）、`update --set ...`→`record --input-file`（Writeツールで候補JSONを一時ファイルへ書き`--input-file`で渡す）、`set-current`呼び出しの削除（Phase 4の手順1を丸ごと削除）、Phase 5の`pending`呼び出しはそのまま維持。「初回のみopenで開く」記述は`start`実行直後に変更
  - `.claude/.temp/consult/20260818-consult-review-findings.md`の削除（REQ-019 FNC-010。旧形式の討議ファイルであり新設計のagenda.jsonへ変換する価値がないため単純破棄）
- **検証ポイント**:
  - `grep -rn "status-vocabulary\|terminal-statuses\|active-statuses\|set-current\|current_item_id\|agenda_state.js"` を`plugins/forge/skills/consult/`配下・`plugins/forge/scripts/agenda/`配下で実行し、旧記述の残存がゼロであることを機械的に確認する
  - `dprint check`（Markdown編集を伴うため）と`python3 -m unittest discover -s tests -p 'test_*.py'`の再実行で最終グリーンを確認する
  - `.claude/.temp/consult/`配下に旧形式ファイルが残っていないことを`find`で確認する

## リスクと対策

| リスク                                                                                                                                                                                                                                                                                                                                            | 影響度 | 対策（どのフェーズで潰すか）                                                                                                                                                                        |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`decision`トリガー検証の抜け穴**: 既に`decision`が記録済みの項目へ`decision`を含まない差分パッチ（`background`単独等）を送ると検証が素通りする。旧`discussion_file_template.md`の「既知の未解決事項」が記録した不具合（旧`status`キーの有無で発火する検証）と構造的に同型のリスクが、新トリガー（`decision`キーの有無）でも形を変えて存在しうる | 高     | フェーズ3で明示的な境界テストケースを追加し挙動を固定する。フェーズ4で`discussion_file_template.md`の記述をその決定内容に更新する（ドキュメントに「未解決」として先送りしない）                     |
| §5.1aの「新規追加と再判定をアトミックに完結させる」要件（中間状態を永続化しない）を`agenda_store.py`が満たさず、判定が古いまま保存される瞬間が生まれる                                                                                                                                                                                            | 中     | フェーズ2で`upsert_item()`とレコード直下`structural_judgment`マージを同一トランザクション（同一`save_agenda()`呼び出し）内で完結させる実装にし、フェーズ2の手動スモークテストで新規追加ケースを確認 |
| `fields`のトップレベル置換（再帰マージしない）という設計と、呼び出し側（consult SKILL.md）の実際の呼び出しパターンが噛み合わず、`severity`等の既存値が意図せず消える                                                                                                                                                                              | 中     | フェーズ4のSKILL.md書き換え時に「`fields`の一部だけ変えたい場合は呼び出し側が全体を読み取ってから渡す」という設計原則（DES-075 §6.1）を手順に明記する                                               |
| 旧CLI契約（`--set`・`status`語彙）を前提にした呼び出しが、書き換え漏れにより`consult` SKILL.md以外の場所（将来の`review`直接呼び出し等）に残存する                                                                                                                                                                                                | 低     | 着手前のgrep調査で現時点の参照元が`consult`のみであることを確認済み。フェーズ4で機械的grepにより再発を検出                                                                                          |
| `agenda_render.py`の表示生成が`agenda_store.py`に依存しないという設計制約（独立実行可能）を、書き換え中に誤って`agenda_store`側の内部データ構造へ依存させてしまう                                                                                                                                                                                 | 低     | フェーズ1で`agenda_render.py`単体のスモークテスト（`agenda_store`を一切importしない手動実行）を検証ポイントとすることで、依存混入があれば即座に失敗する                                             |
