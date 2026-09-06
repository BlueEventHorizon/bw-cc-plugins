# fix-consult 実装戦略

## アプローチ

**選択**: ボトムアップ + リスク駆動（フェーズ 1 に契約変更を集約）

**根拠**:

- 依存が一方向の直列（`agenda_schema` → `agenda_store` → `agenda_wrapper` → SKILL.md）であり、下層の API が確定しないと上層を書けない。特に `agenda_store` は `start` / `record` の CLI 廃止・関数専用化（DES-080 §6）で公開 API そのものが変わるため、これが定まる前に wrapper を書くと二度手間になる
- 最大のリスクは新規技術ではなく契約の同時変更にある——受理条件（§2.6）・決着判定「3 値そろい」（§2.6・§4.4）・ドット区切り入れ子マージ（§2.6）・採番（§3）は、store / schema / render の 3 モジュールが同じ判定で揃っていないと提示と記録が食い違う（agenda:REQ-021 FNC-003 違反）。これをフェーズ 1 で先に固め、テストで固定する
- `agenda_render` は `agenda.json` 契約のみに依存するため、契約（フェーズ 1）確定後は wrapper と並行して進められる
- 新規モジュールは無く（wrapper は移動のみ）、スケルトン先行やフィーチャースライスが与える早期 E2E の利得は小さい。E2E 確認は最終フェーズの統合テスト（結合 script 出力 → `start` → `record` → `finish`）で行う

## 現状把握

- 対象は agenda 機構 4 script（`agenda_schema` / `agenda_store` / `agenda_render` / `agenda_wrapper`）と consult SKILL.md・テンプレート 1 件・既存テスト 5 ファイル
- 現行 store は `start` / `record` を `--input-file` の CLI として持ち、許可キー集合・型検証・`title` 必須・upsert（無ければ新規）を実装している。DES-080 はこれらを撤廃し、`start` / `record` を関数専用にして wrapper だけを入力経路にする
- 結合 script の出力 `combined[]` は `{**finding, **evaluation}` で、所見本文は `text`、重大度は `severity` として項目直下に来る
- 既存テストは CLI 経由・`--input-file` 前提・撤廃対象の拒否を固定しており、大半が書き換え対象

## フェーズ

### フェーズ 1: 記録層の契約変更（`agenda_schema` / `agenda_store`）

- **目標**: 関数呼び出しで、agenda が知らないキーを含む項目が `start` / `record` で落ちずに保存され、§2.6 の受理条件と 3 値そろいの決着判定が働く状態。`pending` / `next` / `finish` の CLI は従来どおり動く
- **スコープ**:
  - `agenda_schema.py`（DES-080 §2.6 受理条件表）: 構造判断未記録時はあらゆる項目パッチを拒否（現行は `decision` トリガー時のみ検査する縮退を解く）／`decision.*` のいずれかを含むパッチは `background`・`essence` 非空を要求／「決着」を `decision.by`・`outcome`・`reason` の 3 値すべて非空と定義する述語を持つ（store が参照する）／不足フィールド名の列挙形式は維持
  - `agenda_store.py`（§2.2・§2.3・§2.5・§2.6・§3・§6）: 許可キー集合・固定キーでの組み立て直し・列挙写し・新規時 `title` 必須の撤廃／**現行の入力形式検査（`_validate_start_candidate` / `_validate_record_candidate` の文字列・object・配列の型検証）をすべて撤廃**（§2.3。既知キーの値も変換・拒否せずそのまま保存する）／`start` は「渡された項目をそのまま保持し §2.5 の既定値で欠けたキーだけ補う」正規化のみ／`id` 無しの項目にゼロ埋め 2 桁の衝突しない連番を採番／`start` は構造判断を受けず `structural_judgment.recorded: false` で開始／`record` は「構造判断」「既存項目へ 1 値」「新規項目（構造判断を伴い、採番した `id` を応答に含める）」の 3 形に再設計／`--item-id` が存在しない場合は拒否（upsert 廃止）／値の名前はドット区切りを入れ子としてキー単位マージ、`id` / `last_changed_fields` / `fields` / `decision` そのものは名前として拒否／残件判定を 3 値そろいに置き換え（`pending` / `next` / `finish` が同じ判定を参照）／`start` と `record` を CLI から除去し関数専用化
  - テスト `tests/forge/agenda/test_agenda_schema.py` / `test_agenda_store.py`: 撤廃した拒否を固定する既存テストを DES-080 §7 の観点へ改める。新規追加: 未知キーが `start` / `record` で黙って落ちないこと／既知キーに現行なら型違反となる値（例: `fields` に文字列）を渡しても拒否・変換されずそのまま保存されること／`title` 無しの受理／採番／新規項目の応答に `id`／存在しない `--item-id` の拒否／1 呼び出し 1 値／`decision.*` を 1 つずつ積んでも先の値が消えないこと／3 値が揃うまで残件・`finish` が削除しないこと／構造判断未記録時の全パッチ拒否
- **検証ポイント**:
  - `agenda_schema` の改修完了時点で `tests.forge.agenda.test_agenda_schema` が通ること（store へ進む前にここで一度止める）
  - `tests.forge.agenda.test_agenda_store` 全通過
  - `agenda_store.py start` / `record` が argparse エラーで拒否され、`pending` / `next` / `finish` は従来どおり動くこと
  - 旧記録（キーが少ない `agenda.json`）を読めること（§8。移行処理を設けないことの確認）

### フェーズ 2: 表示層の追随と入力経路の一本化（`agenda_render` / `agenda_wrapper` 移動）

- **目標**: 結合 script の標準出力を `agenda_wrapper.py start` の標準入力へつなぐだけで記録が作られ、項目直下の `severity` がバッジに出、`title` 空でも `id` で識別でき、3 値が揃うまで未決着として表示される状態。wrapper は移動先 `plugins/forge/scripts/agenda/` で動き、review 起点以外を拒否する
- **スコープ**:
  - `agenda_render.py`（§4.1・§4.2・§4.4）: 重大度を「`fields` を先に、無ければ項目直下」で探索（空値の判定は現行維持）／一覧行と項目見出しで `title` 空なら `id` を表示／決着判定を「`decision.by` / `outcome` / `reason` の 3 値すべて非空」に揃える（表示層は `agenda.json` の契約だけに依存する現行の独立性を保ち、`agenda_schema` を import しない。store 側の述語との一致は統合テストの境界ケースで固定する）／`structural_judgment.note` が `None` の記録で生成が失敗しないこと
  - `agenda_wrapper.py`（§1.3・§2.1・§2.6・§4.3・§5・§6）: `git mv` で `plugins/forge/scripts/agenda/` へ／`--origin` を `review` のみに（`consult` はエラーで停止し記録を作らない。`--session-id` と consult 用 config を削除）／置き場を `git rev-parse --show-toplevel` の絶対パスから解決、git 管理外はエラー停止／`start` は標準入力の結合出力を読み、`config`（`item_fields: []`、`severity_field: "severity"`）と `items` の入れ物を組み立て、各要素の `text` を `problem` にも置いて store の関数へメモリ上で渡す（一時ファイルと `--input-file` を撤廃）／`record` は「構造判断」「`--item-id <id> --field <name>`」「新規」の 3 形で本文を標準入力から読む／AI の文章を受け取る引数を一切持たない／応答に解決済み絶対 `path`（新規では `id` も）を含める／標準入力は `run()` にストリームを注入できる形にしてテスト容易性を確保する
  - テスト: `git mv tests/forge/consult/test_agenda_wrapper.py tests/forge/agenda/`、`tests/forge/consult/` を削除。新規追加: 作業ディレクトリを変えても同じ絶対パス／git 管理外でエラー／`--origin consult` がエラーで記録を作らない／`start` が標準入力から入れ物を組み立てる／`text` が `problem` にも置かれる／一時ファイルを書かない／`record` 本文が標準入力から入る／自由記述を受ける引数が無いこと
  - `tests/forge/agenda/test_agenda_render.py`: 重大度が `fields` 内／直下／`fields` 側が空値で直下が使われる／未知キー保存時も生成成功／`title` 空で `id` 表示／3 値が揃うまで未決着表示、を追加
- **検証ポイント**:
  - `agenda_render` 改修完了時点で `tests.forge.agenda.test_agenda_render` 通過（wrapper に進む前に区切る）
  - `tests.forge.agenda.test_agenda_wrapper` 通過、`tests/forge/consult/` が存在しないこと
  - 手動シナリオ: リポジトリのサブディレクトリから結合出力を `agenda_wrapper.py --origin review start` の標準入力へ流し、git ルート直下の `.claude/.temp/review/agenda.json` に保存され `agenda.html` に「問題」欄とバッジが出ること。続けて構造判断 → 各項目の背景・本質・決着 3 値を記録してから `finish` で削除する（未決着が残る間は `finish` が削除しないため、途中で `finish` を呼んで削除されないことも確認する）

### フェーズ 3: 呼び出し側の追随・停止・統合検証

- **目標**: review 起点の全手順が新しい wrapper 呼び出し（移動先パス・標準入力・3 形の `record`）で SKILL.md に記述され、直接起動の入口・手順・未参照テンプレートが取り除かれ、結合 script（無変更）→ wrapper → 提示までの統合テストが通り、全テスト・dprint が緑の状態
- **スコープ**:
  - `plugins/forge/skills/consult/SKILL.md`（§1.3・§2.1・§2.6・§2.7・§6）: frontmatter を `user-invocable: false` にしトリガー語を description から外す（`disable-model-invocation` は付けない——付けると description が消え review から呼べなくなる）／「起点の判定」「Phase 1」「2.1 consult 起点」「他セッション記録の直接 `--path` 再開」「候補 JSON を Write して `--input-file`」の手順を削除／Phase 2.2 を「結合 script の出力を `start` の標準入力へつなぐ → 構造判断を `record` で記す」に、Phase 4 の record 手順を 1 回 1 値（`decision.by` / `outcome` / `reason` を各 1 回）に、新規論点を新規の `record`（応答の `id` を以後使う）に書き換え／全コマンドのパスを `${CLAUDE_PLUGIN_ROOT}/scripts/agenda/agenda_wrapper.py` へ／禁止事項「自由記述文をシェル文字列へ直接埋め込む」は残す／`allowed-tools` から `Write` を外す（候補 JSON を書く用途が消える）
  - `plugins/forge/skills/consult/assets/discussion_file_template.md` を `git rm`
  - 利用者へ consult を案内している導線（§1.3）: `plugins/forge/skills/help/SKILL.md` の一覧・引数の案内・起動手順から consult を外し、`plugins/forge/skills/review/SKILL.md` の「議論・方針検討そのものは対象外（`/forge:consult`）」の案内と `docs/readme/forge/guide_setup_ja.md` の help 出力例の consult 行も、利用者が起動できる前提を残さない形へ改める
  - `tests/forge/agenda/test_agenda_integration.py`: 結合 script（無変更で import）の出力を wrapper の `start` へつなぎ、構造判断 → 項目ごとに `background` / `essence` / `decision.*` × 3 → 新規項目（応答の `id` で同じく背景・本質・決着 3 値を記録）→ `finish` を通し、各書き込み直後の `agenda.html` が記録から生成したものと一致すること・未決着が残る途中の `finish` が削除しないこと・全決着後の `finish` で記録に属するものがすべて消えることを検証。決着判定の境界ケース（2 値のみ / 3 値そろい）で store の残件と render の表示が一致することを固定
  - 残存確認（対象を agenda 関連に限定。他機能の同名引数 `--input-file` は対象外）: `grep -rn "skills/consult/scripts\|discussion_file_template\|--origin consult\|--session-id" plugins/ tests/` が 0 件、および `grep -rn "input-file" plugins/forge/scripts/agenda/ plugins/forge/skills/consult/ tests/forge/agenda/` が 0 件（`docs/specs/` 配下の旧設計書は差分 feature の制約により触らない）
  - `dprint fmt` を変更した md に通す
- **検証ポイント**:
  - `python3 -m unittest discover -s tests -p 'test_*.py'` 全通過
  - `dprint check` 通過
  - 上記 grep が 0 件
  - `git status` に一時物が現れないこと
  - `README.md` / `README_en.md` のスキル一覧で consult の行が既存の凡例どおり AI 専用（斜体・トリガー欄「※ review が呼び出し」）になっていること（同じ変更で古くなる文書として直す。設計の内容は書かない）
  - help・review SKILL.md・setup ガイドに、利用者が consult を起動できる前提の案内が残っていないこと

## リスクと対策

| ID  | リスク                                                                                                                       | 影響度 | 対策（どのフェーズで潰すか）                                                                                                                                                                                                                 |
| --- | ---------------------------------------------------------------------------------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1  | `start` / `record` の CLI 廃止で `agenda_store` の公開 API が変わり、wrapper と既存テストが一斉に壊れる                      | 高     | フェーズ 1 で関数シグネチャを先に確定しテストで固定。wrapper・統合テストはこの API に対して書く（フェーズ 2・3）                                                                                                                             |
| R2  | 「決着 = 3 値そろい」の判定が store / render の 2 箇所に分かれると提示と記録が食い違う                                       | 高     | render に `agenda_schema` への依存を足す設計変更は DES-080 §6 に無いため行わない。render は現行どおり `agenda.json` 契約だけに依存して自前で 3 値判定し、store 側の述語との一致をフェーズ 3 の統合テスト（境界ケース）で固定する             |
| R3  | ドット区切りの入れ子マージにより、現行の「`fields` 全置換」テストと DES-075 §6.1 の記述が反転する                            | 中     | フェーズ 1 で該当テストを改め、`decision.*` を順に積んで先の値が残ることをテストで固定                                                                                                                                                       |
| R4  | `start` 直後は構造判断が無い。render がこの状態で失敗する／SKILL.md の手順が構造判断の `record` を飛ばすと以後全て拒否される | 中     | フェーズ 2 で `note: None` の記録を render するテストを追加。フェーズ 3 の SKILL.md で `start` 直後の構造判断記録を必須手順として明記し、統合テストで順序を固定                                                                              |
| R5  | `git rev-parse --show-toplevel` 依存: テストで一時ディレクトリに `git init` が必要                                           | 中     | フェーズ 2 のテストで `git init` を setUp に置き、git が無ければ `skipTest`。git 管理外のケースは一時ディレクトリ直下で検証                                                                                                                  |
| R6  | 標準入力を読む wrapper のテスト容易性                                                                                        | 低     | フェーズ 2 で `run(args, stdin=None)` のように入力ストリームを注入可能にし、`main()` だけが `sys.stdin` を渡す                                                                                                                               |
| R7  | wrapper 移動に伴い旧パス参照が残る（SKILL.md・テストのモジュールパス・wrapper 自身の docstring）                             | 中     | フェーズ 3 の残存 grep で 0 件を機械確認。`git mv` を使い履歴を保つ                                                                                                                                                                          |
| R8  | `last_changed_fields` に記録する名前の粒度（`decision.by` か `decision` か）を DES-080 が明示していない                      | 低     | 渡された名前そのまま（`decision.by`）を記録する（「その呼び出しで加えたキー」の字義どおり）。フェーズ 1                                                                                                                                      |
| R9  | `combined[]` に `text` と `problem` が両方保存され本文が重複する                                                             | 低     | フェーズ 2 で `text` を削除せず `problem` に複製する（作り替えではなく追加）ことをテストで固定。DES-080 §4.3 が wrapper の責務として認めている                                                                                               |
| R10 | 直接起動停止後も `tests/common` の整合テストや README が `user-invocable: true` を前提にしている可能性                       | 低     | フェーズ 3 の全テスト実行で検出。ただし `tests/common/test_plugin_integrity.py` の照合は太字・斜体の行を扱えず CI では検出されないため、TASK-007 で README.md / README_en.md の consult 行を凡例どおり AI 専用へ改める（機械検出に頼らない） |
