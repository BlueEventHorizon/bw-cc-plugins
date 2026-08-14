---
name: query-db-rules
description: |
  プロジェクトの様々なルールを、キーワード・機能名・自然文で、高速・高品位に、優先度をつけて検索する。
  設計・実装・コーディング・レビュー等、開発作業のあらゆる場面でルールを参照したいときに使う。
user-invocable: true
argument-hint: "task description"
allowed-tools: Skill, Read, Bash, AskUserQuestion
---

ルール文書（category `rules`）を、利用可能な文書検索 backend（doc-db / doc-advisor）で検索して結果を返す。

この SKILL はルール文書の検索のみを行う。**索引の作成・更新は行わない**（`/forge:update-db-rules` の責務）。
親が依頼している他の作業を引き継いではならない。

**grep を backend の代替として使用しない。** backend の索引に基づかない結果を返すと、利用者は検索の
網羅性を誤認する。

索引の整備が必要な場面では `/forge:update-db-rules` を Skill ツールで起動する。整備の手順を本 SKILL に
複製せず委譲するのは、索引を整備する入口を 1 つに保つためである。渡す引数は backend 名だけであり、
親タスクの指示文を渡さない。

> ❌ 自己再帰禁止: `Skill` ツールで自分自身（`query-db-rules`）および他の `query-db-*` を呼ばないこと（無限再帰）。
> Skill ツールによる `/forge:update-db-rules` の起動は上記のとおり許可される（検索側から更新側への一方向であり循環しない）。

## この検索の性質

単語一致の検索ではない。各文書の要約・キーワード・適用タスクを収めた索引を AI が全件読み、タスクとの関連を意味で判断し、候補文書の本文を確認して選ぶ。

- 渡すのは単語ではなく、**タスクの記述と関連する概念**である。言い換え・上位概念・周辺語を並べて渡すほど当たる
- 索引の要約に載っていない事柄は、本文にあっても引けないことがある（backend によって本文の grep が併用される場合もあるが、当たりは保証されない）

## Procedure

### Step 1: セッション内でルール文書を変更したか判断する

このセッションで自分がルール文書を変更している場合、索引はその変更を含まない。`AskUserQuestion` で
索引を更新するか確認し、更新する場合は Skill ツールで `/forge:update-db-rules` を起動してから Step 2 へ進む。

変更していない場合は確認せず Step 2 へ進む。**拾えるのは自分がこのセッションで行った変更だけである**
（他セッション・利用者による直接編集・ブランチ切替は判断材料に無い）。

### Step 2: backend の順序を解決する

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/doc_backend/resolve_backend_order.py"
```

exit 0 なら JSON の `order` を先頭から試す。exit 20 なら JSON の `message` を添えて明示エラーとして終了する。

後位へ進む事由は、その backend が利用不能だったときだけである。全て利用不能なら、それぞれの理由を並べて
明示エラーとして終了する。

- `doc-db` の番 → Step 3
- `doc-advisor` の番 → Step 4

### Step 3: doc-db で検索する

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/query_documents.py" "<検索タスク記述>"
```

`$ARGUMENTS`（検索タスク記述）を 1 つの位置引数として渡す。引数を Bash ブロックへ素の形で埋め込まない
（`"` や `` ` `` を含む記述で引用が崩れる）。

| exit code | 動作                                                             |
| --------- | ---------------------------------------------------------------- |
| 0         | JSON の `result` を返して Step 6 へ                              |
| 10        | doc-db 利用不能。理由を控えて Step 2 の次の backend へ           |
| 20        | JSON の `message` を添えて明示エラーとして終了する               |
| 30        | 索引が未整備。Step 5 へ（`--backend doc-db` を指定して整備する） |

**0 件は正しい結果である。** 当該 series はその branch の完全な現在状態なので、0 件を受けて series を
外した再検索・検索対象の拡大・grep での代替を行わない。0 件のまま成功として返す。

### Step 4: doc-advisor で検索する

available-skills に `doc-advisor:index-docs` と `doc-advisor:query-docs` が揃っていなければ利用不能として
理由を控え、Step 2 の次の backend へ進む。

`Skill` ツールで `doc-advisor:query-docs` を **1 回だけ** 呼ぶ:

```
/doc-advisor:query-docs --key rules <$ARGUMENTS>
```

応答が `Required documents:` 形式であれば検索は成功である。0 件でも失敗ではないので、そのまま親へ返して
Step 6 へ進む。

**それ以外の応答を解析しない [MANDATORY]**。doc-advisor が保証している出力形式は `Required documents:` だけで
あり、それ以外の応答（索引未整備の案内・エラーの説明）の文面は保証されていない。文面に一致させて種別を
判定してはならない。

`Required documents:` 形式でない場合は、応答をそのまま利用者へ提示して Step 5 へ進む
（`--backend doc-advisor` を指定して整備する）。索引が未整備であっても他の事由であっても本 SKILL の行動は
同じ（提示して整備の可否を問う）ため、両者を区別しない。

### Step 5: 未整備の索引を整備する

`AskUserQuestion` で整備の承認を得る。

**件数を自前に数えて提示しない。** doc-advisor 経路で索引される件数を決めるのは doc-advisor 側であり、
forge が数えた値はその件数と一致する保証を持たない。

- 承認された → Skill ツールで `/forge:update-db-rules --backend <確定済みの backend>` を起動する。
  完了後に Step 3 または Step 4 の検索を **1 回だけ** 再実行し、Step 6 へ進む。整備が失敗した場合は
  検索せず明示エラーとして終了する
- 見送られた → 検索を行わず、索引が未整備である事実を報告して終了する。失敗として扱わない

`--backend` を渡すのは、既に確定させた backend と別の索引が整備されるのを防ぐためである。

### Step 6: 結果を返す

`Required documents:` 形式のパスリストを先頭に置き、その後に次を添える。

- 利用した backend
- 先位を利用できず後位を利用した場合: その理由
- 設定で優先 backend を指定していて満たされなかった場合: 指定が満たされなかったこととその理由
- doc-db の起動を試行した場合（JSON の `startup` が未試行以外）: その結果
- Step 1 の確認を行った場合: 索引を更新したか否か
- Step 5 で索引を整備した場合: その事実
- 実在しないパスを結果から除外した場合（JSON の `notices`）: その件数

## Output Format

```
Required documents:

- docs/rules/xxx.md
- docs/rules/yyy.md
```

## Notes

- doc-db の key は `{project_name}-rules`、series は現在の git branch。`/forge:update-db-rules` と同一の series を検索する。
- doc-advisor 経路の検索母集団は doc-db 経路と一致しない可能性がある。対象文書の解決規則が backend ごとに異なるため、doc-advisor 経路で検索した場合はその旨を通知する。doc-db 経路で完了した検索では出さない。
