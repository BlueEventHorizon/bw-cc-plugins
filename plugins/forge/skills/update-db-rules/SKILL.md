---
name: update-db-rules
description: |
  ルール文書の追加・改訂後に検索インデックスを最新化する。
  新しいルール文書を /forge:query-db-rules で検索可能にしたいときに実行する。
  トリガー: "ルール検索インデックス更新", "ルールインデックス再構築"
user-invocable: true
argument-hint: ""
allowed-tools: Read, Bash, Skill
---

ルール文書（category `rules`）の検索インデックスを、利用可能な文書検索 backend（doc-db / doc-advisor）で
最新化する wrapper。設定から backend の順序リストを解決し、先位から可用性を判定して利用する。

この SKILL はルール検索インデックスの更新のみを行う。親が依頼している他の作業を引き継いではならない。

> ❌ 自己再帰禁止: `Skill` ツールで自分自身や他の `/forge:*-db-*` 抽象 SKILL を呼ばないこと（無限再帰）

## Procedure

### Step 1: 対象 backend を確定する

`$ARGUMENTS` に `--backend doc-db` または `--backend doc-advisor` がある場合、その backend を対象として
Step 2 を飛ばし、対応する手順（`doc-db` → Step 3 / `doc-advisor` → Step 4）へ直行する。指定された
backend が利用不能なら、他方へ切り替えず明示エラーとして終了する。

指定は `query-db-*` が未整備の索引を整備させるときに渡す。呼び出し元が既に backend を確定させているため、
ここで選び直すと別の索引を整備することになる。

指定が無い場合は順序リストを解決する:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/doc_backend/resolve_backend_order.py"
```

exit code だけで分岐する:

| exit code | 動作                                                                                                                      |
| --------- | ------------------------------------------------------------------------------------------------------------------------- |
| 0         | JSON の `order`（例 `["doc-advisor", "doc-db"]`）を順序リストとして Step 2 へ進む                                         |
| 20        | 設定不正（`settings_invalid`）。**既定値へ落ちず**、JSON の `message` を添えて明示エラーとして終了する。Step 2 へ進まない |

### Step 2: 順序リストの先位から backend を試す（指定が無い場合のみ）

順序リストの先頭から、backend ごとの手順を実行する:

- `doc-db` の番 → Step 3
- `doc-advisor` の番 → Step 4

後位へ進む事由は **選択前の可用性判定の失敗（利用不能）だけ** である。利用不能だった backend と
その理由は控えておき、Step 5 の通知に含める。順序リストの全 backend が利用不能な場合は、
両者の利用不能理由を並べて明示エラーとして終了する。

backend 選択後の操作失敗（sync の失敗・index-docs の失敗）は障害であり、他方の backend へ
切り替えず明示エラーとする。切替で隠すと backend 側の問題に利用者が気づけなくなる。

### Step 3: doc-db 経路（desired-state 同期）

#### Step 3.1: 同期を投入する

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/sync_documents.py" --start
```

exit code だけで分岐する。JSON は結果表示と診断情報の取得（`job_id`・`count`・`startup` 等）にのみ使い、
JSON field の組合せから状態を再構成しない:

| exit code | 意味            | 動作                                                                                                                                                                                                             |
| --------- | --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0         | 投入成功        | JSON の `job_id` を控えて Step 3.2 へ進む                                                                                                                                                                        |
| 10        | doc-db 利用不能 | **`--backend` の指定を受けている場合は切り替えず明示エラーとして終了する。** 指定が無い場合の次の行動は順序リストから決める: 後位が残っていれば理由を控えて Step 2 の次の backend へ、残っていなければ明示エラー |
| 20        | operation 失敗  | 明示エラーとして終了する（対象文書 0 件を含む）。backend を切り替えない                                                                                                                                          |

#### Step 3.2: 完了までポーリングし、進捗を毎回報告する

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
- `done` かつ `job.failed` が 0 かつ `job.errors` が空 → 同期完了。Step 5 へ進む
- `failed`、または `done` でも `job.failed` が 1 以上か `job.errors` が非空 → 一部文書の失敗を含む update 失敗。
  明示エラーとして終了する（doc-advisor へ切り替えない）

ポーリング中に exit 10 / 20 が返った場合は、backend 選択が投入時点で確定済みのため後位へ切り替えず、
明示エラーとして終了する。

### Step 4: doc-advisor 経路（ToC 再構築）

#### Step 4.1: 可用性を判定する

システムリマインダの available-skills に `doc-advisor:index-docs` が存在するかで判定する。
update 経路が要求するのはこの 1 SKILL のみである。

存在しない場合、doc-advisor は未導入（利用不能）である。**`--backend` の指定を受けている場合は
切り替えず明示エラーとして終了する。** 指定が無い場合は、後位が残っていれば理由を控えて
Step 2 の次の backend へ、残っていなければ明示エラーとして終了する。

#### Step 4.2: 索引入力を準備する

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/prepare_advisor_index.py"
```

dprint 適用（索引作成前フォーマット）と、`.doc_structure.yaml` からの `root_dirs` / `exclude` の解決を行う。
exit code だけで分岐する:

| exit code | 動作                                                                  |
| --------- | --------------------------------------------------------------------- |
| 0         | JSON の `root_dirs` / `exclude` を Step 4.3 へ渡す                    |
| 20        | 準備失敗。`doc-advisor:index-docs` を呼ばず、明示エラーとして終了する |

dprint によりファイル内容が変わった場合、変更は作業ツリーに残る（後続の commit がそのまま対象に含める）。

#### Step 4.3: index-docs へ転送する

`Skill` ツールで `doc-advisor:index-docs` を **1 回だけ** 呼ぶ（常に dirs モード）:

```
/doc-advisor:index-docs --key rules --dirs-json '<root_dirs の JSON 配列>' --exclude-json '<exclude の JSON 配列>'
```

`exclude` が空の場合は `--exclude-json '[]'` を渡す（省略も可）。`exclude` の裸名（`/` なし、例 `plan`）は
doc-advisor 側でもパスの任意の階層にある同名ディレクトリへの完全一致として扱われるため、変換なしでそのまま渡せる。

`doc-advisor:index-docs` の完了レポート（added / updated / deleted / toc_path 等）は構造変換せず親へ返す。

### Step 5: 結果と経路の通知

結果の報告に次を含める:

- 利用した backend の識別（正常に先位を利用できた場合は、冗長な警告を出さず識別のみ）
- 先位の backend を利用できず後位を利用した場合: その理由と利用した backend。
  設定で優先 backend を指定していた場合は、指定が満たされなかったこととその理由も通知する
- doc-db の起動を試行した場合（JSON の `startup` が未試行以外）: その結果
- 処理を完了できない場合: 利用不能だった backend と失敗理由

`--backend` の指定を受けた実行では、切替は起こらない。指定された backend で完了したか、
利用不能で失敗したかのいずれかを報告する。

## Notes

- **desired-state**: 対象一覧は `.doc_structure.yaml` の rules 設定が正である。doc-db 経路では
  一覧全体が当該 series の、doc-advisor 経路では `--dirs-json` / `--exclude-json` が key `rules` の
  完全な desired state となり、含まれない文書は索引から切り離される。
- doc-db の key は `{project_name}-rules`、series は現在の git branch。検索（query）と同一の series を更新する。
- dprint の適用は doc-advisor 経路の準備 CLI（Step 4.2）に含まれる。doc-db 経路は対象文書の現在内容を
  そのまま desired state として同期するため、sync 前の dprint 適用手順を持たない（hash 一致文書の
  再計算要否は doc-db に委ねる）。
- doc-advisor 経路の索引の出力先は `.claude/doc-advisor/toc/rules-<hash>/toc.yaml`（doc-advisor が管理）。
