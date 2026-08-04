---
name: query-db-rules
description: |
  プロジェクトの様々なルールを、キーワード・機能名・自然文で、高速・高品位に、優先度をつけて検索する。
  設計・実装・コーディング・レビュー等、開発作業のあらゆる場面でルールを参照したいときに使う。
user-invocable: true
argument-hint: "task description"
allowed-tools: Skill, Read, Bash
---

ルール文書（category `rules`）を、利用可能な文書検索 backend（doc-db / doc-advisor）で検索する
read-only wrapper。設定から backend の順序リストを解決し、先位から可用性を判定して利用する。
grep を backend の代替として使用しない。両 backend が利用不能な場合は明示エラーとする。

この SKILL はルール文書の検索のみを行う。親が依頼している他の作業を引き継いではならない。

> ❌ 自己再帰禁止: `Skill` ツールで自分自身や他の `/forge:*-db-*` 抽象 SKILL を呼ばないこと（無限再帰）

## Procedure

### Step 1: backend 順序リストを解決する [MANDATORY]

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/doc_backend/resolve_backend_order.py"
```

exit code だけで分岐する:

| exit code | 動作                                                                                                                      |
| --------- | ------------------------------------------------------------------------------------------------------------------------- |
| 0         | JSON の `order`（例 `["doc-advisor", "doc-db"]`）を順序リストとして Step 2 へ進む                                         |
| 20        | 設定不正（`settings_invalid`）。**既定値へ落ちず**、JSON の `message` を添えて明示エラーとして終了する。Step 2 へ進まない |

### Step 2: 順序リストの先位から backend を試す [MANDATORY]

順序リストの先頭から、backend ごとの手順を実行する:

- `doc-db` の番 → Step 3
- `doc-advisor` の番 → Step 4

後位へ進む事由は **選択前の可用性判定の失敗（利用不能）だけ** である。利用不能だった backend と
その理由は控えておき、Step 5 の通知に含める。順序リストの全 backend が利用不能な場合は、
両者の利用不能理由を並べて明示エラーとして終了する。

backend 選択後の操作失敗（検索の失敗・索引作成/更新の失敗）は障害であり、他方の backend へ
切り替えず明示エラーとする。切替で隠すと backend 側の問題に利用者が気づけなくなる。

### Step 3: doc-db 経路（series 指定検索）

#### Step 3.1: 検索を実行する

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/query_documents.py" "<検索タスク記述>"
```

`$ARGUMENTS`（検索タスク記述）を **1 つの位置引数** として渡す。exit code だけで分岐する。
JSON は結果表示と診断情報の取得（`result`・`notices`・`warnings`・`startup` 等）にのみ使い、
JSON field の組合せから状態を再構成しない:

| exit code | 意味                | 動作                                                                                                                                                         |
| --------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 0         | 検索成功            | JSON の `result`（`Required documents:` 形式）を返して Step 5 へ。0 件・対象文書なしも成功であり、series を外した再検索や grep 代替をしない                  |
| 10        | doc-db 利用不能     | 「doc-db を利用できない」のみを意味する。次の行動は順序リストから決める: 後位が残っていれば理由を控えて Step 2 の次の backend へ、残っていなければ明示エラー |
| 20        | operation 失敗      | 明示エラーとして終了する。backend を切り替えない（KEY がゴミ箱状態の場合は、JSON の `message` にある復活操作の案内をそのまま利用者へ伝える）                 |
| 30        | KEY / series 未整備 | 障害でも切替事由でもない。索引を作成してから検索を継続する。Step 3.2 へ進む                                                                                  |

#### Step 3.2: 索引を作成する（未整備時のみ）[MANDATORY]

同期を投入する:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/sync_documents.py" --start
```

exit 0 なら JSON の `job_id` を控える。ここで exit 10 / 20 が返った場合、backend 選択は
Step 3.1 で確定済みのため後位へ切り替えず、明示エラーとして終了する（索引作成の失敗は障害）。

`--status` を **2 秒間隔** で繰り返し呼ぶ。ポーリングのループは本 SKILL が駆動する（script 内に完了待ちはない）。

```bash
sleep 2 && python3 "${CLAUDE_SKILL_DIR}/scripts/sync_documents.py" --status <job_id>
```

**`--status` を 1 回呼ぶたびに 1 回、その時点の進捗をテキストで利用者へ報告する。省略しない。**
報告には JSON の `job` の件数（processed / skipped / failed / deleted_paths_marked）を含める。
進捗を script の標準エラー出力に委ねない（SKILL 経由の実行では利用者に届かない）。

終了判定は JSON の `job.status` で行う（`--status` は job 未完了でも exit 0 を返す。未完了は異常ではない）:

- `running` → 継続。ただし投入からの経過が **600 秒** を超えたら打ち切り、明示エラーとして終了する
  （doc-db 側の job は継続しており、本 SKILL の再実行で冪等に収束する旨を通知に含める）
- `done` かつ `job.failed` が 0 かつ `job.errors` が空 → 索引作成完了。Step 3.3 へ進む
- `failed`、または `done` でも `job.failed` が 1 以上か `job.errors` が非空 → 索引作成の失敗。
  明示エラーとして終了する（doc-advisor へ切り替えない）

#### Step 3.3: 検索を再実行する

Step 3.1 と同じコマンド・同じ引数で query を **もう 1 回だけ** 実行する。同期の試行は 1 回のみ:

- exit 0 → 成功。**索引作成を伴った事実を結果に含めて** Step 5 へ（0 件でも「該当なし」の成功として
  返す。再同期・検索対象の拡大をしない）
- それ以外（10 / 20 / 30）→ 明示エラーとして終了する。再同期せず、backend も切り替えない

### Step 4: doc-advisor 経路（索引更新 → 検索）

#### Step 4.1: 可用性を判定する

システムリマインダの available-skills で判定する。query 経路に必要な doc-advisor SKILL は
`doc-advisor:index-docs` と `doc-advisor:query-docs` の 2 つである。

**判定は SKILL の有無だけで行う。バージョン番号を条件にしない [MANDATORY]**。特定の SKILL の
有無からバージョンを推測することもしない（成果物の有無はバージョンではなく、fork・部分インストール・
提供側の改名で推測が誤る）。

| 条件                     | 状態             | 動作                                                                        |
| ------------------------ | ---------------- | --------------------------------------------------------------------------- |
| 2 SKILL のいずれかが無い | `advisor_absent` | doc-advisor 未導入として利用不能。理由を控えて残る backend の可否確認へ進む |

後位が残っていれば Step 2 の次の backend へ、残っていなければ明示エラーとして終了する。

#### Step 4.2: 索引を更新する [MANDATORY]

**検索前に必ず索引を更新する。更新の要否を判定しない [MANDATORY]**。差分の判断は `index-docs` の
desired-state 処理が行い、対象文書に変更がなければ ToC は書き換わらない。

前回生成からの経過時間で更新の要否を判定してはならない。ToC が正しいかどうかは対象文書が
変わったかどうかで決まり、経過時間では決まらない（rules / specs の索引は他の作業者・他ブランチの
更新とも独立であり、時間は指標にならない）。

索引入力を準備する:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/prepare_advisor_index.py"
```

dprint 適用（索引作成前フォーマット）と、`.doc_structure.yaml` からの `root_dirs` / `exclude` の解決を行う。
exit code だけで分岐する:

| exit code | 動作                                                                  |
| --------- | --------------------------------------------------------------------- |
| 0         | JSON の `root_dirs` / `exclude` を index-docs へ渡す                  |
| 20        | 準備失敗。`doc-advisor:index-docs` を呼ばず、明示エラーとして終了する |

準備成功時、`Skill` ツールで `doc-advisor:index-docs` を **1 回だけ** 呼ぶ（常に dirs モード）:

```
/doc-advisor:index-docs --key rules --dirs-json '<root_dirs の JSON 配列>' --exclude-json '<exclude の JSON 配列>'
```

`exclude` が空の場合は `--exclude-json '[]'` を渡す（省略も可）。

- index 成功 → Step 4.3 へ進む。**ToC が書き換わった場合はその事実を Step 5 の通知に含める**
- index 失敗 → 検索を続行せず、明示エラーとして終了する（backend を切り替えない）

#### Step 4.3: 検索を実行する

`Skill` ツールで `doc-advisor:query-docs` を **1 回だけ** 呼ぶ:

```
/doc-advisor:query-docs --key rules <$ARGUMENTS>
```

`$ARGUMENTS`（検索タスク記述）をそのまま末尾に渡す。backend の応答はそのまま親に返す（構造変換しない）。

### Step 5: 結果と経路の通知 [MANDATORY]

結果の報告に次を含める:

- 利用した backend の識別（正常に先位を利用できた場合は、冗長な警告を出さず識別のみ）
- 先位の backend を利用できず後位を利用した場合: その理由と利用した backend。
  設定で優先 backend を指定していた場合は、指定が満たされなかったこととその理由も通知する
- doc-db の起動を試行した場合（JSON の `startup` が未試行以外）: その結果
- 索引の作成（doc-db）または ToC の更新（doc-advisor）を伴った場合: その事実と対象 backend
- 実在しないパスを検索結果から除外した場合（JSON の `notices`）: その件数
- **doc-advisor 経路で検索した場合: 対象文書の解決規則が doc-db 経路と異なるため、検索母集団が
  doc-db 経路と一致しない可能性があることを通知する。doc-db 経路で完了した検索では出さない**
- 処理を完了できない場合: 利用不能だった backend と失敗理由

## Output Format

応答の先頭は `Required documents:` 形式（どちらの backend でも維持する）:

```
Required documents:

- docs/rules/xxx.md
- docs/rules/yyy.md
```

Step 5 の通知は path リストの後に添える。

## Notes

- doc-db の key は `{project_name}-rules`、series は現在の git branch。更新（`/forge:update-db-rules`）と
  同一の series を検索する。key の意味（rules）は forge が決定し、backend へ opaque key として渡す。
- doc-db 経路の検索結果は最後の同期時点の索引に基づくため、実在しないパスは script が除外する。
  除外は検索の失敗ではない。
- 検索前の索引更新は常に行う。更新の要否を forge が判定しないため、閾値の設定を持たない。
