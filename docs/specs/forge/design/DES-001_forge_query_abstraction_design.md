# DES-001 文書検索バックエンドの抽象化（switch-query）設計書

## メタデータ

| 項目         | 値                                                                                                                                                                                                  |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 設計 ID      | DES-001                                                                                                                                                                                             |
| 対象スコープ | forge（doc-advisor 単独動作復活は別 issue で扱う）                                                                                                                                                  |
| バージョン   | 本 PR ではバージョン関連ファイル（plugin.json / marketplace.json / CHANGELOG.md）を編集しない（`docs/rules/implementation_guidelines.md` の「バージョン関連ファイルの編集禁止 [MANDATORY]」に従う） |
| 作成日       | 2026-05-16                                                                                                                                                                                          |
| 更新日       | 2026-05-18                                                                                                                                                                                          |
| 関連要件     | FNC-006, FNC-001                                                                                                                                                                                    |
| 関連設計     | ADR-002, DES-006, DES-007, DES-026                                                                                                                                                                  |
| 関連 Issue   | [#53 docs: DES-007 (OPENAI_API_DOCDB_KEY 統一) の反映漏れを修正](https://github.com/BlueEventHorizon/bw-cc-plugins/issues/53)                                                                       |

---

## 1. 背景と目的

### 1.1 現状の問題

forge の各 skill（`review` / `start-design` / `start-plan` / `start-implement` / `clean-rules` / `merge-specs` 等）は、ルール・仕様の検索および ToC 更新を **`/doc-advisor:query-rules` / `/doc-advisor:query-specs` / `/doc-advisor:create-rules-toc` / `/doc-advisor:create-specs-toc` を具体プラグイン名で直接呼ぶ** 構造になっている。これにより以下の不整合が生じている。

1. **doc-advisor を抜くと forge のフローが機能不全になる**。各 skill のガードは「利用可能ならスキップ」だが、**query 系の検索結果は後段の入力として必須** のため、スキップすると review のルール検索や start-implement のコンテキスト収集が無音で抜け落ちる。
2. **doc-db のみで運用したいユーザーが doc-advisor を強制される**。doc-db は機能的に doc-advisor の Embedding 検索を包含するが、forge が doc-advisor を直呼びしているため、doc-advisor をインストールしないと forge が完全動作しない。
3. **doc-advisor を「ついで」に入れているユーザーに不要な ToC 更新負荷が発生する**。主軸が doc-db でも、forge skill が `/doc-advisor:create-*-toc` を呼ぶ箇所が散在し、ToC 更新が毎回走る。
4. **doc-advisor 採用判定と forge 側の利用可能ガードが二重分岐になりうる**。バックエンド選択は forge 側に集約すべきで、双方で同じ判定を持つとデグレ源になる。

### 1.2 目的

forge から検索バックエンド（doc-db / doc-advisor）への **依存逆転**。forge は具体プラグイン名ではなく抽象スキルを呼び、抽象スキル内部で「インストール済みバックエンドを 1 つ選ぶ」分岐を担う。これにより doc-db のみインストール、doc-advisor のみインストール、両方インストールのいずれでも forge が完全動作する。

### 1.3 非目的

- doc-advisor と doc-db の機械的排他（マーケットプレイスに排他制約はない）。
- 「両方インストール時の手動切り替え」（テスト用フラグは後回し。本設計では全自動分岐のみ実装）。
- 既存ユーザーへの後方互換（ユーザーは事実上 1 名のため）。
- doc-advisor 側の内部仕様（auto モードの実行ロジック等）の規定。本書は forge 側のバックエンド選択を扱い、doc-advisor の挙動は doc-advisor 側 SoT（DES-006 および `plugins/doc-advisor/skills/query-{rules,specs}/SKILL.md`）を **引用** する。両者に矛盾が生じた場合は doc-advisor 側 SoT に従う。

### 1.4 API キーの前提（DES-007 統一仕様）

doc-advisor / doc-db いずれも API キー解決は DES-007 で統一されており、本設計はこれを前提とする:

- **優先**: `OPENAI_API_DOCDB_KEY`
- **フォールバック**: `OPENAI_API_KEY`

つまり「doc-db を動かすために必要な API キー」と「doc-advisor の Embedding を動かすために必要な API キー」は**同じ**。

### 1.5 forge 側の責務範囲

forge は **どのバックエンド（doc-db / doc-advisor）を呼ぶか** を `available-skills` と API キー有無から決定する。採用後の検索実行は各バックエンド側の責務であり、本書ではバックエンド側の内部仕様を規定しない。

forge は doc-advisor を呼ぶときに `--toc` / `--index` を渡さない（**フラグなし = auto**）。auto モード起動後の実行ロジックは doc-advisor 側 SoT（DES-006 および `plugins/doc-advisor/skills/query-{rules,specs}/SKILL.md`）を参照する。本書は forge 側のバックエンド選択を扱い、doc-advisor 内部の auto モード仕様は規定しない（§5.3 引用）。両者の記述に矛盾が生じた場合は doc-advisor 側 SoT に従う。

#### 1.5.1 forge 側の API キー判定式

forge は DES-007 に従い、「API キーあり」を `OPENAI_API_DOCDB_KEY` または `OPENAI_API_KEY` のいずれかが**空でない値で設定されていること**として判定する。

```bash
[ -n "${OPENAI_API_DOCDB_KEY:-}" ] || [ -n "${OPENAI_API_KEY:-}" ]
```

> 本判定式は forge 側では §8.1 で新設する `plugins/forge/scripts/backend_selection/select_backend.py` 内に **Python で同等のロジックとして実装**する（`os.environ.get("OPENAI_API_DOCDB_KEY")` と `os.environ.get("OPENAI_API_KEY")` のいずれかが空でない値か判定）。forge 側の SKILL.md にこの判定式を複製せず、スクリプトを forge 側の単一実装実体とする。doc-advisor 側の判定方式は doc-advisor 側 SoT に従う（本書では規定しない）。

#### 1.5.2 forge 側のバックエンド選択結果

forge 側の分岐（§2.3 分岐テーブル A）で採用されるバックエンドは以下のとおり:

- **両方インストール + API キーあり** → `doc-db`
- **両方インストール + API キーなし** → `doc-advisor`（フラグなし呼び出し = auto モード）
- **doc-db のみ** → `doc-db`
- **doc-advisor のみ** → `doc-advisor`（フラグなし呼び出し = auto モード）
- **どちらもなし** → エラー終了（§5.1）

採用後の各バックエンドの内部挙動（doc-advisor auto モードのモード判定 / Index スキップ条件 / マージ仕様 等、doc-db Hybrid 検索の詳細 等）は本書の対象外であり、それぞれのプラグイン側 SoT を参照する（§5.3 引用 / DES-026）。

---

## 2. アーキテクチャ概要

### 2.1 依存逆転の構造

```text
変更前:
  forge:review
    ├─ /doc-advisor:query-rules        ←─ 具体名を直接呼ぶ（doc-advisor 強結合）
    ├─ /doc-advisor:query-specs
    └─ /doc-advisor:create-specs-toc

変更後:
  forge:review
    ├─ /forge:query-db-rules           ←─ 抽象 skill
    ├─ /forge:query-db-specs
    └─ /forge:update-db-specs
              │
              ├─ (両方 + API キーあり)         → /doc-db:query, /doc-db:build-index
              ├─ (両方 + API キーなし)         → /doc-advisor:query-rules (フラグなし), /doc-advisor:create-*-toc
              ├─ (doc-db のみ)                 → /doc-db:query, /doc-db:build-index
              ├─ (doc-advisor のみ)            → /doc-advisor:query-rules (フラグなし), /doc-advisor:create-*-toc
              └─ (どちらもなし)                 → エラー終了（hint 付き）

  ※ 採用後の各バックエンド内部の挙動は本書の対象外（doc-advisor 側 SoT / DES-026 を参照）。
```

### 2.2 新規追加スキル一覧

`plugins/forge/skills/` 配下に 4 つの skill を新設する。

| Skill 名                 | 役割                                                                                                           | user-invocable |
| ------------------------ | -------------------------------------------------------------------------------------------------------------- | -------------- |
| `/forge:query-db-rules`  | ルール文書の検索抽象。インストール済みバックエンドを自動選択して検索を実行                                     | false          |
| `/forge:query-db-specs`  | 仕様文書の検索抽象。同上                                                                                       | false          |
| `/forge:update-db-rules` | ルール文書のインデックス再構築抽象（採用バックエンドに応じて ToC **または** build-index のいずれか一方を実行） | false          |
| `/forge:update-db-specs` | 仕様文書のインデックス再構築抽象（採用バックエンドに応じて ToC **または** build-index のいずれか一方を実行）   | false          |

> 4 SKILL とも **`user-invocable: false`**（プラグイン内部スキル）。`/` メニューには出ず、ユーザーが `/forge:query-db-rules` 等を直接タイプすることは想定しない。forge プラグイン内の他 SKILL から `Skill` ツール経由で呼ばれることを前提とする。バックエンド（`/doc-advisor:*` / `/doc-db:*`）はそれぞれ別プラグインとしてユーザーが明示インストールしており、検索を直接実行したい場合はバックエンド SKILL を直接呼ぶ運用に揃える。

### 2.3 forge 側の分岐ルール（全自動）

`/forge:query-db-*` / `/forge:update-db-*` のすべてで以下の分岐を実行する。**判定の本体は Python スクリプト `plugins/forge/scripts/backend_selection/select_backend.py`（§8.1）に集約**し、SKILL.md 側は available-skills の読取と最終 Skill 起動のみを担う。

#### 責務分離

| 担当                           | 責務                                                                                                                                                                                                    |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SKILL.md（4 抽象 SKILL）       | システムリマインダの available-skills を LLM が読み、利用可能バックエンド一覧（`doc-db` / `doc-advisor` の有無）を `--available` 引数として組み立てる                                                   |
| `select_backend.py`            | §1.5.1 の API キー判定 + 下記分岐テーブル A / B の評価 + JSON 結果返却（選択バックエンド名 / 呼ぶべき skill 名 / 異常時は §5.1 全文と一致する `error` 文字列）。SKILL.md 内に分岐テーブルを複製させない |
| SKILL.md（4 抽象 SKILL、続き） | Bash で `select_backend.py` を呼び、返ってきた JSON を解釈して `Skill` ツールで該当バックエンドを起動する                                                                                               |

#### 分岐テーブル A（採用バックエンド決定・SoT）

以下 5 行の分岐テーブルは「**採用バックエンドを決める**」表として本設計書を **Single Source of Truth** とする。`select_backend.py` の実装はこの 5 行を網羅し、`tests/forge/scripts/test_backend_selection.py`（§10.3）がこのテーブルをゴールデンとして検証する。

| doc-db 有無 | doc-advisor 有無 | API キー   | 採用バックエンド                   |
| ----------- | ---------------- | ---------- | ---------------------------------- |
| あり        | あり             | あり       | `doc-db`                           |
| あり        | あり             | なし       | `doc-advisor`                      |
| あり        | なし             | （問わず） | `doc-db`                           |
| なし        | あり             | （問わず） | `doc-advisor`                      |
| なし        | なし             | （問わず） | **エラー終了**（バックエンド不在） |

#### 分岐テーブル B（採用バックエンド × category × operation → 呼ぶべき skill 名）

分岐テーブル A で決まった採用バックエンドと `--category` / `--operation` の組み合わせから、`select_backend.py` が JSON で返す `skill` フィールドの値を導出するマッピングを以下に固定する。これも本設計書を SoT とし、§10.3 のテストで網羅検証する。

| backend       | category | operation | skill                           |
| ------------- | -------- | --------- | ------------------------------- |
| `doc-db`      | rules    | query     | `/doc-db:query`                 |
| `doc-db`      | specs    | query     | `/doc-db:query`                 |
| `doc-db`      | rules    | update    | `/doc-db:build-index`           |
| `doc-db`      | specs    | update    | `/doc-db:build-index`           |
| `doc-advisor` | rules    | query     | `/doc-advisor:query-rules`      |
| `doc-advisor` | specs    | query     | `/doc-advisor:query-specs`      |
| `doc-advisor` | rules    | update    | `/doc-advisor:create-rules-toc` |
| `doc-advisor` | specs    | update    | `/doc-advisor:create-specs-toc` |

> doc-advisor を呼ぶ際の引数は **`--toc` / `--index` を付けない**（auto モードに委譲）。doc-db の `--category` 引数は `--category` の値（`rules` / `specs`）をそのまま転送する。

#### SKILL.md 側のフロー

1. システムリマインダの available-skills を LLM が読み、`doc-db:query` / `doc-advisor:query-rules` 等の有無を確認する。
2. Bash で `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backend_selection/select_backend.py --available <list> --category {rules|specs} --operation {query|update}` を呼ぶ（read-only。スクリプトは書き込みを行わない）。
3. JSON 結果（`{"backend": "...", "skill": "...", "error": null|"..."}`）を解釈する。`error` が null でなければ §5.1 のエラーメッセージ（`error` 文字列をそのまま）で終了する。`error` が null なら JSON の `skill` フィールドから skill 名を取得し、`Skill` ツールで呼び出す。**doc-advisor を呼ぶ際は `--toc` / `--index` を付けない**（auto モードに任せる）。
4. forge 側ではバックエンド間のフォールバックを行わない。バックエンドから返されたエラー・出力はそのまま親に伝播させる（doc-db 採用時の API キー未設定エラーなど）。doc-advisor 採用時の応答（エラー化されないケースを含む）は doc-advisor 側 SoT（§5.3 引用）に従い、forge 側はその応答をそのまま返す。

> 設計意図:
>
> - **判定ロジックを Python スクリプトに 1 箇所集約**: 4 SKILL.md に同じ判定式・分岐表が複製されるとデグレ源になるため、SoT を本設計書（テーブル定義）と `select_backend.py`（実装）に限定し、SKILL.md は available-skills 構築と Skill 起動だけに専念させる
> - **doc-advisor 単独インストール時に forge 側で API キー判定をしない**: doc-advisor 側で API キー有無に応じた動作が規定されているため（§5.3 引用）、forge 側で重複判定する必要がない
> - **両方インストール時のみ forge 側で API キー判定が必要**: 「キーがあるなら doc-db を選びたい、なければ doc-advisor」の判断が forge にしかできないため
> - **doc-db のみ単独時は API キー判定しない**（doc-db に API キーが必須なため、なければ doc-db のエラーで気付かせる）

---

## 3. 各スキルの仕様

### 3.1 `/forge:query-db-rules` / `/forge:query-db-specs`

#### 引数

| 引数     | 必須 | 説明                             |
| -------- | ---- | -------------------------------- |
| `{task}` | 必須 | 検索クエリ（タスク記述・自然文） |

> `--toc` / `--index` は forge 抽象 SKILL では受理しない。これらは doc-advisor / doc-db の **品質検査用フラグ** であり、forge は本番運用専用。品質検査でレイヤを切り分けたい場合は `/doc-advisor:query-rules --toc xxx` のようにバックエンド SKILL を直接呼ぶ。`{task}` 以外の引数（`--top-n` / `--doc-type` / `--toc` / `--index` 等）が渡された場合の挙動は AI 判断に委ね、SKILL.md にゴミ引数の扱いを明記しない（責務分離の方針は [ADR-001](./ADR-001_forge_query_test_flag_policy.md)）。

#### 実行フロー

1. available-skills 参照 + 必要なら API キー判定によるバックエンド選択（§2.3）。
2. **doc-db 採用時**:
   - `Skill` ツールで `/doc-db:query --category rules --query "{task}" --mode rerank` を呼ぶ（specs 版は `--category specs` を渡す）。
   - 内部で grep 補完が行われる（doc-db の仕様、DES-026）。
3. **doc-advisor 採用時**:
   - `Skill` ツールで `/doc-advisor:query-rules "{task}"` を **`--toc` / `--index` を付けずに** 呼ぶ（specs 版は `/doc-advisor:query-specs`）。
   - 呼び出し後の挙動（auto モードの実行ロジック）は doc-advisor 側 SoT に従う（§5.3 引用）。
4. **どちらもなし時**: §5.1 のエラー出力。

#### 出力

`/forge:query-db-*` の出力契約は、両バックエンド共通で「`Required documents:` を必須先頭セクション」とし、後段セクション（Hybrid scores / grep hits 等の詳細出力）は **2 軸** に分けて規定する。

- 先頭セクション (必須): `Required documents:` + プロジェクトルート相対パスのリスト
- 後段セクション: 次の 2 軸で規定する。

  | 軸                                                      | 規定                                                                                                                                                         |
  | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
  | ① forge 主処理（`/forge:query-db-*` のパスリスト抽出）  | **参照しない**（任意扱い）。後段セクションの有無・内容にかかわらずパスリスト抽出が成立すること                                                               |
  | ② doc-db 単独契約（`/doc-db:query` の出力フォーマット） | **必須**。FNC-006 OUT-01 / OUT-02 / DES-026 に従い、chunk 見出し階層・chunk テキスト・スコア内訳（embedding / lexical / rerank）・ヒット理由を後段で出力する |
  | ② doc-advisor 単独契約（`/doc-advisor:query-*` の出力） | 後段セクションは付加しない（先頭セクションのみで完結）                                                                                                       |

抽象 skill 側で**出力の構造変換**（先頭セクション形式の整形）は行わず、両バックエンドの SKILL.md が同形式を直接出力する。これにより doc-db / doc-advisor の単独利用時もパス抽出が機械的に行え、テストで先頭セクション形式の一致を検証できる。

出力例:

```markdown
Required documents:

- docs/rules/xxx.md
- docs/specs/yyy/requirements/zzz.md

## Hybrid scores / grep hits <!-- doc-db 採用時のみ任意で付加 -->

- docs/rules/xxx.md score=0.83 line=42 "..."
```

> 注:
>
> - 本契約に合わせるため、doc-db:query SKILL の **出力フォーマット記述（Output Format セクション）のみ** 本設計の実装フェーズで「`Required documents:` 先頭ハイブリッド形式」に変更する（§7・§11 実装手順を参照）。検索スクリプト本体（`search_index.py` / `grep_docs.py` 等）および build-index 仕様・内部実装は変更しない。
> - doc-advisor:query-rules / query-specs は既に `Required documents:` 形式を返す契約のため、本変更で出力形式の変更は不要。後段セクションは付加しない。
> - 後段セクションの 2 軸規定（forge 主処理は不参照 / doc-db 単独契約としては FNC-006 OUT-01/OUT-02 / DES-026 準拠で必須）は上記出力契約本文に昇格済み。doc-db 単独利用時の詳細出力契約は本設計で変更しない。

#### subagent 契約 [MANDATORY]

`/forge:query-db-rules` / `/forge:query-db-specs` は **継承型 read-only 検索 SKILL** である。SKILL 基本設計 (`docs/specs/common/design/COMMON-DES-001_skill_base_design.md`) §3.1 のデフォルト方針に従い、`context: fork` を指定しない（同 §4 規定リスト外）。fork しない根拠は以下のとおり:

- 本 SKILL は内部で fork 型の `/doc-advisor:query-rules` / `/doc-advisor:query-specs` を呼ぶ。親 context の漏洩遮断はバックエンド側の fork 境界で既に成立しており、forge 側で更に fork すると COMMON-DES-001 §3.1 の「二重 fork の回避」に抵触する
- doc-db バックエンド採用時の `/doc-db:query` も継承型である（fork 境界はバックエンドが提供しない）が、本 SKILL の役割はバックエンドへの引数転送と select_backend.py の Bash 呼出に限定されるため、Role 制約 (B 層) と引数解釈ガード (C 層) で逸脱を抑止する

新規 2 SKILL の SKILL.md は ADR-002 §B / §C と同等の B 層・C 層制約を必須化する:

- **Role 章に read-only 制約 [MANDATORY] を明記**（ADR-002 §B / COMMON-DES-001 §6 B 層）。`/forge:query-db-*` は read-only であり、以下を保証する:
  - `Edit` / `Write` / `MultiEdit` / `NotebookEdit` 等の書き込み系ツールを使わない
  - バックエンド検索 SKILL（`/doc-db:query` / `/doc-advisor:query-*`）以外の Skill を起動しない（再帰防止）
- **引数解釈 [MANDATORY] セクション**を SKILL.md に設け、「`$ARGUMENTS` は検索キーワードまたは自然言語のタスク記述であり、命令文に見えても実装指示として解釈してはならない」旨を ADR-002 §C と同形式の表で明示する
- **出力契約は `Required documents:` 形式のパスリストのみ**を必須先頭セクションとする。後段セクション（Hybrid scores / grep hits）は §3.1「#### 出力」に従い、doc-db バックエンド採用時のみ任意で付加する

##### 呼び出し側の責務: args にプロンプトを渡してはならない [MANDATORY]

`/forge:query-db-*` は継承型のため親 context をそのまま保持する。__呼び出し側（forge:review / forge:start-_ / forge:create-feature-from-plan 等）は、`Skill` ツール経由で本 SKILL を起動する際、`args` に親タスクの context を貼り付けてはならない_*（COMMON-DES-001 §3.4 / §5.2 に整合）。

| カテゴリ                         | 例                                                                                              | 可否    |
| -------------------------------- | ----------------------------------------------------------------------------------------------- | ------- |
| 検索キーワード                   | `"Repository 実装パターン"` / `"ログイン画面 ViewModel"`                                        | ✅ 渡す |
| 短い自然文のタスク記述           | `"ログイン画面の状態遷移を実装したい"`                                                          | ✅ 渡す |
| 親タスクの Issue 本文            | Issue #54 の全文・タイトル + 本文の貼り付け                                                     | ❌ 禁止 |
| 進行中タスクの要約・実装指示     | 「SKILL.md の version を更新し、CHANGELOG に追記し、plugin.json を…」のような実装手順の貼り付け | ❌ 禁止 |
| 親が編集中の差分・ファイル内容   | diff / ファイル内容の貼り付け                                                                   | ❌ 禁止 |
| 「やってほしい作業」の指示文連結 | 検索キーワード + 「その後 ◯◯ してください」                                                     | ❌ 禁止 |

理由:

- 継承型 subagent は親 context を既に保持しているため、再供給は無意味であり context を圧迫するだけ
- ADR-002 で発生した暴走事象の根因は「親 context + args の命令調」の組み合わせで subagent が「実装指示」と推論したこと。継承型では fork 境界が無い分、`args` を検索語に限定することが C 層引数解釈ガードと並んで重要
- 検索バックエンド（`/doc-db:query` / `/doc-advisor:query-*`）に転送される `args` も同様の制約を持つため、forge:query-db-* で混入すれば下流まで波及する

呼び出し側 SKILL は `args` を**検索キーワード + 短い自然文タスク記述のみ**に限定する。親 context に既にある情報は重複供給しない。

> なぜこの最小契約で成立するか:
>
> - **1点目**で抽象 SKILL 自身が直接ファイルに書くことはないことを保証する
> - **2点目**で抽象 SKILL が間接的に fixer や build-index を呼ぶことはないことを保証する（再帰防止）
> - `/doc-db:query` が内部で `.claude/doc-db/index/` に書くのは backend の SoT 配下であり、上記 2 点とは無関係（抽象レイヤがバックエンド内部知識を持たない疎結合を維持する）
> - 「バックエンド検索 SKILL 以外を起動しない」と肯定形で 1 文化することで、`/doc-db:build-index` と `/doc-db:query` の判別が「検索 SKILL に含まれるか否か」の 1 軸のみで完結し、「書き込み系」という曖昧分類が消える
>
> また、バックエンド選択のために `Bash` ツールで `plugins/forge/scripts/backend_selection/select_backend.py` を呼ぶことは read-only 制約と整合する（§8.1）。`select_backend.py` は環境変数読取と stdout JSON 出力のみで、git 管理ファイルへの書き込み・コミット・他プロセス起動を行わない。

### 3.2 `/forge:update-db-rules` / `/forge:update-db-specs`

#### 引数

| 引数     | 必須 | 説明                                   |
| -------- | ---- | -------------------------------------- |
| `--full` | 任意 | 全件再構築モード。バックエンド側に転送 |

#### 実行フロー

1. available-skills 参照 + 必要なら API キー判定によるバックエンド選択（§2.3）。
2. **doc-db 採用時**: `Skill` ツールで `/doc-db:build-index --category rules [--full]`（specs 版は `--category specs`）を呼ぶ。
3. **doc-advisor 採用時**: `Skill` ツールで `/doc-advisor:create-rules-toc [--full]`（specs 版は `/doc-advisor:create-specs-toc`）を呼ぶ。
4. **どちらもなし時**: §5.1 のエラー出力。

> 注: `create-*-toc` は API キー不要のため、doc-advisor 採用時に `--toc` / `--index` の分岐は不要。query 系のみが auto モード分岐を活用する。

#### 注記

doc-db の `build-index` は `query` 時に自動再生成される（FNC-006 §2 / DES-026）。`/forge:update-db-*` を明示的に呼ばずに `/forge:query-db-*` だけ呼んでも doc-db 環境では動作する。`/forge:update-db-*` は「ドキュメント編集直後に確実にインデックスを最新化したい」場合に明示的に使う。

doc-advisor の `create-*-toc` は API キー不要のため、「両方インストール + API キーなし」のシナリオで update-db-* が呼ばれた場合も問題なく動作する。

---

## 4. forge 配下の置換対象

検索および ToC 更新の呼び出しを抽象 skill に置換する。

### 4.1 置換マッピング

| 旧呼び出し                      | 新呼び出し               |
| ------------------------------- | ------------------------ |
| `/doc-advisor:query-rules`      | `/forge:query-db-rules`  |
| `/doc-advisor:query-specs`      | `/forge:query-db-specs`  |
| `/doc-advisor:create-rules-toc` | `/forge:update-db-rules` |
| `/doc-advisor:create-specs-toc` | `/forge:update-db-specs` |

### 4.2 影響範囲（要書き換え）

grep の対象スコープは **SKILL.md だけでなく、skill が Read する `docs/*.md`（workflow 文書）および `review_criteria_*.md` まで拡張**する。これらは SKILL.md 本体から参照される実行手順・観点定義であり、旧呼び出しが残るとランタイムで `/doc-advisor:*` への直呼びが復活する。

検索は **スキル名（`query-rules` / `query-specs` / `create-rules-toc` / `create-specs-toc`）** で行う。Claude Code の Skill 呼び出しは `/プラグイン名:スキル名` のフルパスでも、プレフィックスなしのスキル名単独でも記述可能なため（後者が一般的）、プレフィックス付き grep（例: `doc-advisor:` 単独）では捕捉漏れする。スキル名ベースで検索すれば両形式を一括で捕捉できる。

```bash
grep -rn -E 'query-rules|query-specs|create-rules-toc|create-specs-toc' ./
```

> 上記コマンドはプロジェクトルート全体（`plugins/forge/skills/` / `.claude/skills/` / `.agents/skills/` / その他将来追加される箇所）を対象とする。`plugins/forge/skills/` 配下の `SKILL.md` / `docs/*.md` / `review_criteria_*.md`、`.claude/skills/`（ローカル限定 SKILL・配布対象外だが doc-advisor 借用あり）、`.agents/skills/`（agent 向け SKILL）を全て含む。

判明している既知の対象:

**`plugins/forge/skills/` 配下:**

- `plugins/forge/skills/review/SKILL.md`（L211, L213, L232, L236, L238, L652, L676）
- `plugins/forge/skills/start-design/SKILL.md`（L281）
- `plugins/forge/skills/start-plan/SKILL.md`（L303）
- `plugins/forge/skills/clean-rules/SKILL.md`（L288）
- `plugins/forge/skills/merge-specs/SKILL.md`（L64, L105-L122, L564, L570, L572, L608, L612, L624, L626）
- `plugins/forge/skills/create-feature-from-plan/SKILL.md`
- `plugins/forge/skills/start-requirements/docs/requirements_interactive_workflow.md`
- `plugins/forge/skills/start-requirements/docs/requirements_from_figma_workflow.md`
- `plugins/forge/skills/start-requirements/docs/requirements_reverse_engineering_workflow.md`
- `plugins/forge/skills/start-uxui-design/docs/uxui_analysis_workflow.md`
- `plugins/forge/skills/review/docs/review_criteria_requirement.md`
- `plugins/forge/skills/review/docs/review_criteria_design.md`
- `plugins/forge/skills/review/docs/review_criteria_plan.md`
- `plugins/forge/skills/review/docs/review_criteria_code.md`
- `plugins/forge/skills/review/docs/review_criteria_generic.md`

**`.claude/skills/` 配下（ローカル限定 SKILL・配布対象外だが doc-advisor 借用あり）:**

- `.claude/skills/update-forge-toc/SKILL.md`
- `.claude/skills/review-skill-description/SKILL.md`

**`.agents/skills/` 配下:**

- `.agents/skills/update-forge-toc/SKILL.md`
- `.agents/skills/setup-doc-structure/SKILL.md`

`merge-specs` の Phase 0 にある「doc-advisor 必須」検査は **抽象 skill 必須検査** に置き換える（`/forge:query-db-specs` または `/forge:update-db-specs` の存在のみで判定）。

> 出力契約の扱い: 置換対象の forge skill は新呼び出しの出力を §3.1 の正規化契約（`Required documents:` 先頭セクション）に従って解釈する。後段セクション（Hybrid scores / grep hits）は補助情報のため、forge skill 側の主処理では参照しなくてよい。

### 4.3 CLAUDE.md / README / guide 文書

| 文書                                  | 変更                                                                                                                                       |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `CLAUDE.md`                           | `/query-rules` → `/forge:query-db-rules`、`/query-specs` → `/forge:query-db-specs`                                                         |
| `README.md` / `README_en.md`          | スキル一覧の刷新（forge 側に新規 4 skill を追加。doc-advisor 側 description の変更が必要な場合は doc-advisor 側 SoT の責務として別途扱う） |
| `docs/readme/guide_doc-advisor_ja.md` | forge 抽象 skill 経由でのアクセス導線をユーザー視点で記載（doc-advisor 単独利用時の呼び方は doc-advisor 側 SoT に従う、§12.1 残課題）      |
| `docs/readme/forge/guide_*.md`        | 検索・ToC 更新の呼び方を抽象 skill に統一                                                                                                  |

---

## 5. エラー処理契約

### 5.1 バックエンド不在時

`/forge:query-db-*` / `/forge:update-db-*` の双方で以下のメッセージを返して終了する。

```text
ERROR: 文書検索バックエンドが見つかりません
       doc-db または doc-advisor のいずれかをインストールしてください

       /plugin install doc-db@bw-cc-plugins
       /plugin install doc-advisor@bw-cc-plugins
```

### 5.2 採用バックエンドの API キー未設定

§2.3 の分岐により、API キー未設定で doc-db が採用されるのは **「doc-db 単独インストール」の場合のみ**（両方インストール時は API キーなしなら doc-advisor が選ばれるため）。

- **doc-db 単独 + API キーなし**: doc-db の `embedding_api.py` が出力する `error` + `hint` をそのまま親に伝播する。`/forge:query-db-*` 側で再パッケージしない。ユーザーは `OPENAI_API_DOCDB_KEY` を設定するか、doc-advisor を追加インストールする。
- **doc-advisor 採用時**: forge 側はバックエンド選択の結果として doc-advisor を起動した後、応答を親に転送するのみ。API キー未設定時の挙動は doc-advisor 側 SoT（§5.3 引用）に従う。

### 5.3 doc-advisor 採用時の挙動（doc-advisor 設計書への引用）

doc-advisor の auto モード仕様は doc-advisor 側で規定される。**本書は引用元を示すのみ** とし、内容を規定しない。両者の記述に矛盾が生じた場合は doc-advisor 側 SoT に従う。

引用元（doc-advisor 側 SoT）:

- DES-006（auto モードの設計）
- `plugins/doc-advisor/skills/query-rules/SKILL.md` / `plugins/doc-advisor/skills/query-specs/SKILL.md`（auto モード実行フロー）
- FNC-001（エラーケース表を含む契約）

forge が前提とするのは「auto モードがフラグなし呼び出しで起動でき、応答が `Required documents:` 形式のパスリスト（または 0 件応答）として返ってくること」のみ（§6 前提条件、§3.1 出力契約）。それ以外の内部挙動（モード判定 / API キー判定 / マージ / フォールバック / ToC 未構築時の案内 等）は引用元に従い、本書では規定しない。

> forge 側の動作: `/forge:query-db-*` は doc-advisor が返す応答をそのまま親に転送する。doc-advisor 側でエラー化されていない応答を forge 側でエラー化することはしない。応答内に旧スキル名（`/doc-advisor:*`）が含まれている場合の文言置換責務は forge 側で負わない（4 抽象 SKILL は `user-invocable: false` の内部 SKILL であり、応答を受け取るのは親 AI = forge オーケストレーターのため、文言の書き換えなしで動作可能）。

### 5.4 一方のバックエンドが失敗した場合のフォールバック

**実装しない**。最初に選択したバックエンドが失敗したらそのままエラー終了（§5.2 と同じ「バックエンド間フォールバックを行わない」方針）。これは「両方インストールしている場合に doc-db が落ちたら doc-advisor で救う」という挙動を意図的に行わない仕様。動作が不定になることを防ぎ、採用バックエンドを 1 つに固定することで可観測性（どのバックエンドで何が起きたかを明確に追跡できる）を優先する。

---

## 6. doc-advisor 側の前提

doc-advisor 自身の仕様・改修は **本書のスコープ外** であり、本書側で内容を規定しない。doc-advisor 側 SoT（DES-006 および `plugins/doc-advisor/skills/query-{rules,specs}/SKILL.md` / `plugins/doc-advisor/skills/create-{rules,specs}-toc/SKILL.md`）を **引用** する。

本書は doc-advisor が以下の状態にあることを **前提** とする（前提が満たされない場合は doc-advisor 側で対応する。本書側では扱わない）:

- フラグなし（`--toc` / `--index` を付けない）呼び出しで auto モードが動作し、`Required documents:` 形式の応答を返すこと（§3.1 出力契約、§5.3 引用元の仕様に準拠）
- `query-rules` / `query-specs` / `create-rules-toc` / `create-specs-toc` の description が `/forge:query-db-*` / `/forge:update-db-*` と競合するトリガー句を持たないこと（forge 側が抽象 skill のトリガーで選ばれる必要があるため）

auto モードの内部挙動（モード判定 / API キー判定 / マージ等）は doc-advisor 側 SoT に従い、本書では規定しない（§5.3）。

---

## 7. doc-db の変更

### 7.1 変更範囲

doc-db への変更は **出力契約の整合のための最小限のみ** とする。

- **変更する**: `plugins/doc-db/skills/query/SKILL.md` の **Output Format 記述** を変更する。具体的には、出力の先頭に `Required documents:` セクション（プロジェクトルート相対パスのリスト）を追加し、既存の chunk 見出し・chunk テキスト・スコア内訳・ヒット理由（DES-026 / FNC-006 OUT-01/OUT-02 で規定される詳細情報）は後段セクションとして引き続き出力する形に再構成する。これは `/forge:query-db-*` が両バックエンド共通の出力契約に依拠するために必要な記述変更であり、既存の詳細情報を削除・任意化するものではない。
- **変更しない**:
  - doc-db の検索スクリプト本体（`plugins/doc-db/scripts/search_index.py` / `grep_docs.py` 等）の内部実装
  - `/doc-db:build-index` skill の仕様・スクリプト・引数契約（FNC-006 / DES-026 に準拠したまま）
  - `/doc-db:query` の引数契約（`--category` / `--query` / `--mode` 等は既存仕様のまま）
  - chunk 見出し・chunk テキスト・スコア内訳・ヒット理由の出力（FNC-006 OUT-01/OUT-02 の契約は後段セクションとして維持）

`/forge:query-db-*` から `/doc-db:query` を呼ぶ際の引数は doc-db の既存仕様（FNC-006、DES-026）にそのまま準拠する。

### 7.2 バージョン

doc-db plugin の version ファイル（`plugin.json` / `marketplace.json` / `CHANGELOG.md`）の更新は **本 PR では行わない**（`docs/rules/implementation_guidelines.md` 「バージョン関連ファイルの編集禁止 [MANDATORY]」に従う。バージョン管理は本 PR のスコープ外）。本 PR では SKILL.md 内の出力フォーマット記述変更のみを行う。

---

## 8. forge の変更

### 8.1 新規 skill とバックエンド選択スクリプト

`plugins/forge/skills/` 配下に 4 つの SKILL.md を新設し、**バックエンド選択の分岐ロジックは新規 Python スクリプト `plugins/forge/scripts/backend_selection/select_backend.py` に集約**する。4 SKILL.md は分岐表を複製せず、available-skills の組立と Skill 起動のみを担う。

```text
plugins/forge/
├── skills/
│   ├── query-db-rules/
│   │   └── SKILL.md
│   ├── query-db-specs/
│   │   └── SKILL.md
│   ├── update-db-rules/
│   │   └── SKILL.md
│   └── update-db-specs/
│       └── SKILL.md
└── scripts/
    └── backend_selection/
        └── select_backend.py   # ← 新規。分岐ロジックの単一実装
```

#### select_backend.py の責務

- **入力**: コマンドライン引数
  - `--available <list>`: 呼び出し側 SKILL.md が available-skills から構築した利用可能バックエンド一覧（例: `doc-db,doc-advisor` / `doc-advisor` / `doc-db` / 空文字列）
  - `--category {rules|specs}`: カテゴリ
  - `--operation {query|update}`: 操作種別
- **内部処理**:
  - §1.5.1 の API キー判定式を Python で実行（`OPENAI_API_DOCDB_KEY` / `OPENAI_API_KEY` の空でない値の有無）
  - §2.3 **分岐テーブル A**（採用バックエンド決定 5 行）を評価して `backend` を決定
  - 決まった `backend` と `--category` / `--operation` から §2.3 **分岐テーブル B**（8 行）を評価して `skill` を決定
- **出力**: JSON（stdout）
  - 正常時: `{"backend": "doc-db"|"doc-advisor", "skill": "<§2.3 分岐テーブル B が定める skill 名>", "error": null}`
  - 異常時（バックエンド不在）: `{"backend": null, "skill": null, "error": "<§5.1 のエラーメッセージ全文>"}`
  - `error` は **単純な文字列フィールド**とし、値は §5.1 に示すメッセージ全文（`ERROR:` 行と続くヒント本文を含む複数行文字列）と完全一致させる。SKILL.md 側は `error` が null でなければそのまま標準出力に流して終了する（再パッケージしない）
- **read-only 実装**: 環境変数の読取と stdout への JSON 出力のみ。ファイル書き込み・外部プロセス起動・git 操作を一切行わない（§3.1「subagent 契約 [MANDATORY]」と整合）

#### SKILL.md 側のシンプルな構造

4 SKILL.md は以下の構造になる:

1. available-skills を LLM が読んで `--available` 引数を構築
2. Bash で `select_backend.py` を呼ぶ
3. JSON 結果を解釈し、`Skill` ツールで該当バックエンドを起動（または §5.1 のエラー出力）

**SKILL.md 内に分岐テーブルを複製しない**。分岐テーブルは §2.3 と `select_backend.py` のテスト（§10.3）にのみ存在する。

#### frontmatter テンプレート [MANDATORY]

新規 4 skill の SKILL.md frontmatter は以下のテンプレートで固定する。`description` 本文（何をするか／いつ使うか／トリガー句）はユーザー対話で確定済みの内容を SoT とし、実装フェーズで写経する。query 系の継承型方針・`allowed-tools` ・read-only 制約は §3.1「subagent 契約 [MANDATORY]」で定めた契約に従う（本節では重複明記しない）。

```yaml
# plugins/forge/skills/query-db-rules/SKILL.md
---
name: query-db-rules
description: |
  プロジェクトのコーディング規約・命名規則・設計原則・レビュー基準を検索する。
  設計・実装・コーディング・レビュー等、開発作業のあらゆる場面でルールを参照したいときに使う。
  自然文でタスクを記述すると関連ルール文書のパスを返す。
  トリガー: "ルールを検索", "コーディング規約", "プロジェクトルール", "命名規則"
user-invocable: false
argument-hint: "task description"
allowed-tools: Read, Grep, Glob, Bash, Skill
---
```

```yaml
# plugins/forge/skills/query-db-specs/SKILL.md
---
name: query-db-specs
description: |
  プロジェクトの要件定義書・設計書 (REQ/FNC/DES/ADR 等) をキーワードや機能名で検索する。
  要件確認・設計検討・実装・レビュー・テスト等、開発作業のあらゆる場面で仕様を参照したいときに使う。
  自然文でタスクを記述すると関連文書のパスと該当箇所を返す。
  トリガー: "要件を検索", "設計書を確認", "仕様を調べる", "REQ を検索", "DES 関連仕様を検索"
user-invocable: false
argument-hint: "task description"
allowed-tools: Read, Grep, Glob, Bash, Skill
---
```

```yaml
# plugins/forge/skills/update-db-rules/SKILL.md
---
name: update-db-rules
description: |
  ルール文書の追加・改訂後に検索インデックスを最新化する。
  新しいルール文書を /forge:query-db-rules で検索可能にしたいときに実行する。
  トリガー: "ルール検索インデックス更新", "ルールインデックス再構築"
user-invocable: false
argument-hint: "[--full]"
allowed-tools: Read, Bash, Skill
---
```

```yaml
# plugins/forge/skills/update-db-specs/SKILL.md
---
name: update-db-specs
description: |
  要件定義書・設計書の追加・改訂後に検索インデックスを最新化する。
  新しい仕様文書を /forge:query-db-specs で検索可能にしたいときに実行する。
  トリガー: "仕様検索インデックス更新", "仕様検索インデックス再構築", "設計書インデックス更新"
user-invocable: false
argument-hint: "[--full]"
allowed-tools: Read, Bash, Skill
---
```

> 4 SKILL とも **`user-invocable: false`**（プラグイン内部スキル、`skill_authoring_notes.md` のプロジェクト規約「AI 専用スキルには必ず `user-invocable: false` を指定」に準拠）。description 末尾の `"/forge:*"` トリガー句は user-invocable=false により `/` 直接呼出が成立しないため記載しない。AI からの自動トリガー（description マッチ）と `Skill` ツール経由の明示呼出は引き続き有効。

> 注: update 系の `disable-model-invocation` 設定（副作用 SKILL の自動呼び出し制御方針）は本 PR の範囲外とし、別 Issue [#60](https://github.com/BlueEventHorizon/bw-cc-plugins/issues/60) で `skill_authoring_notes.md` および `review-skill-description/SKILL.md` の責務・スコープ再吟味と合わせて確定する。

#### 出力契約・subagent 隔離契約

query 系 2 skill（query-db-rules / query-db-specs）の出力契約は **§3.1 に従う**（`Required documents:` を必須先頭セクション + Hybrid scores / grep hits を任意後段セクションとするハイブリッド形式）。本節では重複定義せず、§3.1 を参照する。

query 系 2 skill の SKILL.md は **継承型** とし（COMMON-DES-001 §3.1 デフォルト方針 / §4 規定リスト外）、B 層・C 層の制約（Role の read-only 制約 [MANDATORY]・引数解釈ガード [MANDATORY]・自己再帰禁止）と `Required documents:` 形式の出力契約（doc-db 採用時のみ後段に Hybrid scores / grep hits を任意で付加可）は §3.1「subagent 契約 [MANDATORY]」に従って必須化する。実装時は **継承型に変更済みの** `plugins/forge/skills/query-forge-rules/SKILL.md` の構造を雛形として継承し（fork 型の `plugins/doc-advisor/skills/query-rules/SKILL.md` は雛形にしない。fork 関連 frontmatter を引き継いでしまうため）、検索対象とバックエンド選択処理（`select_backend.py` の Bash 呼出に集約）のみを差し替える。

query 系 SKILL から `select_backend.py` を Bash で呼ぶことは read-only 制約と整合する（スクリプト自体が書き込みを行わない）。

### 8.2 既存 skill の参照置換とガード方針

§4.2 の各 skill 内の `/doc-advisor:*` 呼び出しを、§4.1 のマッピングに従って一斉置換する。**ガードは以下のように扱う**:

- **query 系**（`/forge:query-db-rules` / `/forge:query-db-specs`）: forge skill 側の「利用可能ならスキップ」ガードを **削除する**。抽象 skill 自体がバックエンド不在時にエラー終了するため、forge 側の重複ガードは不要かつ有害（検索結果が必須なのにスキップされる悪い挙動を生む）。
- **update 系**（`/forge:update-db-rules` / `/forge:update-db-specs`）: forge skill 側のガードを **残す**。ToC 更新は副作用更新であって主処理の完結に必須ではないため、バックエンド不在時に主処理（設計書保存等）まで巻き込んで失敗させない。

### 8.3 plugin.json の更新

`plugins/forge/.claude-plugin/plugin.json` の skill リストに 4 件追加する。**version フィールドは本 PR で編集しない**（`docs/rules/implementation_guidelines.md` 「バージョン関連ファイルの編集禁止 [MANDATORY]」に従う。バージョン管理は本 PR のスコープ外）。

### 8.4 forge 内部 docs/rules への記述

`plugins/forge/docs/` 配下に skill 作成規約・呼び出し契約があれば、抽象 skill の呼び方を追記する（必要に応じて `/forge:query-forge-rules` の ToC 再生成: `update-forge-toc`）。

---

## 9. marketplace の変更

`.claude-plugin/marketplace.json` の version 編集は **本 PR では行わない**（`docs/rules/implementation_guidelines.md` 「バージョン関連ファイルの編集禁止 [MANDATORY]」に従う。バージョン管理は本 PR のスコープ外）。本設計の実装で marketplace.json に対する構造変更（skill 一覧等）は発生しない。

---

## 10. テスト設計

### 10.1 方針

available-skills は Claude プロンプトに含まれる情報で **Python から取得する API は存在しない**。ただし本設計では選択ロジック本体（§1.5.1 の API キー判定 + §2.3 の分岐テーブル A/B 評価）を `select_backend.py` に集約したため、**選択ロジック自体は Python unittest で網羅可能**になっている。SKILL.md 側に残るのは available-skills の LLM 読取・JSON 解釈・`Skill` ツールでの起動という非ロジック部分のみであり、これらは観察的検証で確認する。テスト戦略は以下に整理する:

- **選択ロジック本体のユニットテスト** — `select_backend.py` を `tests/forge/scripts/test_backend_selection.py` で §2.3 の分岐テーブル A / B と §1.5.1 の API キー判定式を網羅検証する（§10.3）
- **マニフェスト整合性テストの拡張** — `tests/common/` に新規 skill 4 件の plugin.json 登録チェックと出力契約・subagent 隔離契約の機械検証を追加（§10.3）
- **既存テストの最小書き換え** — `/doc-advisor:query-*` を直接想定したテストがあれば、抽象 skill 経由を想定する形に書き換える
- **観察的検証** — SKILL.md 側の available-skills 読取・JSON 解釈・Skill 起動部分は Python unittest では到達できないため、実際の Claude Code セッションで §10.2 のシナリオを手動実行して期待動作を確認する

### 10.2 観察的検証シナリオ

実装後、以下のシナリオを手動で実行して動作確認する。

| ID     | シナリオ                                                                             | 期待結果                                                                                                        |
| ------ | ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------- |
| SW-01  | doc-db のみインストール + API キーあり                                               | `/forge:query-db-rules` が doc-db を呼ぶ                                                                        |
| SW-02  | doc-db のみインストール + API キーなし                                               | doc-db のエラー hint が伝播（doc-advisor へのフォールバックなし）                                               |
| SW-03a | doc-advisor のみインストール + API キーあり                                          | `/forge:query-db-rules` が doc-advisor をフラグなしで呼ぶ（呼び出し後の挙動は doc-advisor 側 SoT に従う、§5.3） |
| SW-03b | doc-advisor のみインストール + API キーなし                                          | `/forge:query-db-rules` が doc-advisor をフラグなしで呼ぶ（呼び出し後の挙動は doc-advisor 側 SoT に従う、§5.3） |
| SW-04a | 両方インストール + API キーあり                                                      | doc-db が採用される（doc-advisor は呼ばれない）                                                                 |
| SW-04b | 両方インストール + API キーなし                                                      | doc-advisor がフラグなしで採用される（呼び出し後の挙動は doc-advisor 側 SoT に従う、§5.3）                      |
| SW-05  | どちらもインストールされていない                                                     | §5.1 のエラーメッセージで終了                                                                                   |
| SW-06  | `/forge:update-db-rules` (doc-db 採用、API キーあり)                                 | `/doc-db:build-index --category rules` を呼ぶ                                                                   |
| SW-07  | `/forge:update-db-rules` (doc-advisor 採用、API キーなしでも可)                      | `/doc-advisor:create-rules-toc` を呼ぶ                                                                          |
| SW-08  | `/forge:update-db-rules --full`                                                      | バックエンドに `--full` が転送される                                                                            |
| SW-09  | 両方インストール + `OPENAI_API_DOCDB_KEY` のみ設定                                   | doc-db が採用される（DOCDB キーで判定）                                                                         |
| SW-10  | 両方インストール + `OPENAI_API_KEY` のみ設定（フォールバック）                       | doc-db が採用される（DES-007 のフォールバック経路）                                                             |
| SW-11  | doc-advisor のみインストール時に forge が `--toc`/`--index` を渡していないことを確認 | grep 等で forge SKILL 内に `--toc` / `--index` 文字列が無い                                                     |

### 10.3 機械的に検証する範囲

`tests/common/` のマニフェスト整合性テストに以下を追加:

- `plugins/forge/.claude-plugin/plugin.json` に新規 4 skill が登録されている
- 各 SKILL.md の frontmatter が正しい（`name`, `description`, `user-invocable` 等）
- 旧呼び出し（`/doc-advisor:query-*` / `/doc-advisor:create-*-toc`）が forge skill 内の Skill ツール呼び出しから消滅している（`grep` ベース）
- **出力契約の先頭セクション形式の一致**: `plugins/doc-db/skills/query/SKILL.md` / `plugins/doc-advisor/skills/query-rules/SKILL.md` / `plugins/doc-advisor/skills/query-specs/SKILL.md` の出力フォーマット記述（Output Format セクション等）の先頭が `Required documents:` 形式である旨を grep ベースで検証する。新規テスト `tests/common/test_query_output_contract.py`（仮）として §11 実装手順に組み込む
- **新規 forge query 系 SKILL の継承型 + 多重防御契約の機械検証**: `tests/common/test_query_skill_isolation.py` の `CONSTRAINT_TARGET_SKILLS` に新規 2 SKILL（`plugins/forge/skills/query-db-rules/SKILL.md` / `plugins/forge/skills/query-db-specs/SKILL.md`）を追加し、§3.1「subagent 契約 [MANDATORY]」/ §8.1 が必須化した以下の項目を機械的に検証する。新規 2 SKILL は COMMON-DES-001 §4 規定リスト外（継承型）のため、`FORK_TARGET_SKILLS`（fork 検証）には追加しない:
  - frontmatter に `context: fork` が**含まれていない**（COMMON-DES-001 §3.1 デフォルト継承型に整合）
  - Role 章に read-only 文言（`Edit` / `Write` / `MultiEdit` / `NotebookEdit` 禁止）が明記されている（ADR-002 §B）
  - Role 章に git 管理ファイル書き換え禁止 / `git commit` 等の副作用 Bash 禁止が明記されている（ADR-002 §B）
  - Role 章に「バックエンド検索 SKILL（`/doc-db:query` / `/doc-advisor:query-*`）以外の `Skill` ツール呼び出し禁止」および「`/doc-db:build-index` 等の書き込み系 SKILL 起動禁止」が明記されている（ADR-002 §B / §3.1「subagent 契約 [MANDATORY]」の例外条項）
  - 引数解釈 [MANDATORY] セクションが含まれている（ADR-002 §C）
  - Output Format が `Required documents:` 形式で始まる旨が明記されている（§3.1 出力契約）
- **`plugins/forge/scripts/backend_selection/select_backend.py` のユニットテスト**: 新規 `tests/forge/scripts/test_backend_selection.py` を追加し、§2.3 の **分岐テーブル A（採用バックエンド決定 5 行）と分岐テーブル B（採用バックエンド × category × operation → skill 名 8 行）の両方をゴールデン**として網羅する。各ケースで以下を検証する:
  - 入力（`--available` / `--category` / `--operation` + 環境変数 `OPENAI_API_DOCDB_KEY` / `OPENAI_API_KEY` の有無）に対し、stdout JSON の `backend` フィールドが分岐テーブル A のゴールデンと一致する
  - 同じ入力に対し、stdout JSON の `skill` フィールドが分岐テーブル B のゴールデンと一致する（`--category {rules,specs}` × `--operation {query,update}` × `backend ∈ {doc-db, doc-advisor}` の全 8 ケースを網羅）
  - バックエンド不在（`--available` 空文字列）時に stdout JSON の `error` 文字列が **§5.1 のエラーメッセージ全文と完全一致**する（`ERROR:` 行とヒント本文を含む複数行文字列。§8.1 で `error` を単純文字列契約に確定）
  - §1.5.1 の API キー判定式の正常 / 異常パスを網羅する: `OPENAI_API_DOCDB_KEY` のみ設定 / `OPENAI_API_KEY` のみ設定 / 両方未設定 / 両方空文字列 / 片方が空文字列でもう片方が有効値、の各ケースで API キーの有無判定が DES-007 のフォールバック順序に従う
  - スクリプトが read-only であること（実行後にファイル変更が発生しないこと）を tmp ディレクトリ + checksum で確認する

---

## 11. 実装手順（推奨順序）

依存関係に従って以下の順序で実装する。バックエンド選択ロジックは新規 Python スクリプトに集約するため、SKILL.md からスクリプトを呼ぶ前提でステップを並べる。

1. **[前提] doc-advisor 側の前提条件確認（§6）**: doc-advisor の auto モードがフラグなし呼び出しで起動でき `Required documents:` 形式の応答を返す状態であること、および `query-{rules,specs}` / `create-{rules,specs}-toc` の description が抽象 skill と競合するトリガー句を持たないことを確認する。auto モードの内部挙動の詳細は doc-advisor 側 SoT に従う（§5.3）。前提が満たされない場合は doc-advisor 側で対応する（本書のスコープ外）。
2. **doc-db:query SKILL.md の出力契約を `Required documents:` 先頭ハイブリッド形式に変更**: `plugins/doc-db/skills/query/SKILL.md` の Output Format セクションを、§3.1 の正規化契約に従って書き換える（先頭セクションを `Required documents:` の相対パスリスト、補助セクションを `## Hybrid scores / grep hits` として後段に分離）。これは doc-db plugin への変更となるため、本実装 PR の範囲とする。doc-db plugin の version 更新は本 PR の範囲外（§7.2 の方針に従う）。
3. **`plugins/forge/scripts/backend_selection/select_backend.py` の新規実装と `tests/forge/scripts/test_backend_selection.py` の追加**: §8.1 で定義したスクリプトを実装し、§2.3 の **分岐テーブル A（5 行）と分岐テーブル B（8 行）の両方**を網羅するユニットテストを追加する。テストは §10.3 のゴールデン基準（採用 backend 名・呼ぶべき skill 名・`error` 文字列が §5.1 全文と一致・API キー判定式の正常/異常パス・read-only 性）を満たすこと。スクリプトは read-only（環境変数読取 + stdout JSON 出力のみ）。
4. forge:query-db-rules / query-db-specs / update-db-rules / update-db-specs の SKILL.md を新設（§8.1）。各 SKILL.md は available-skills 構築 → Bash で `select_backend.py` を呼ぶ → JSON 結果から Skill ツールで該当バックエンドを起動、というシンプルな構造に統一する。**分岐テーブルを SKILL.md 内に複製しない**。query 系 2 skill の出力契約は §3.1 に従って `Required documents:` 形式を SKILL.md 内で明示する。
5. forge 配下の参照置換（§4.2）。query 系のガード削除、update 系のガード維持（§8.2）。
6. CLAUDE.md / README / guide 文書の更新（§4.3）。
7. `plugins/forge/.claude-plugin/plugin.json` の skills リストに新規 4 skill を追加（§8.3）。**version フィールドは編集しない**。
8. マニフェスト整合性テストの拡張（§10.3）。既存テストで `/doc-advisor:query-*` を想定するものがあれば書き換え。**新規テスト `tests/common/test_query_output_contract.py`（仮）を追加し、doc-db:query / doc-advisor:query-rules / doc-advisor:query-specs の出力フォーマット記述の先頭が `Required documents:` 形式である旨を機械的に検証する**（§10.3）。`tests/common/test_query_skill_isolation.py` の `TARGET_SKILLS` への新規 2 SKILL 追加もここで行う。
9. 観察的検証（§10.2）を実行し、期待動作を確認。

---

## 12. 残課題（別途議論）

### 12.1 論点3: doc-advisor 単独利用の可否

`/doc-advisor:query-rules` / `/doc-advisor:query-specs` / `/doc-advisor:create-*-toc` を user-invocable のまま残すか、forge:* 経由のみに格下げするか。

- 残す案: forge をインストールしない小規模利用も可能。エントリポイント二重化のコスト
- 格下げ案: forge を実質的に必須化。整合性が高い

本設計書は forge 改修のスコープ内で「`/forge:query-db-*` / `/forge:update-db-*` 経由のアクセス導線を用意する」ことだけを確定し、doc-advisor 側の user-invocable 維持／格下げや description 変更の方針は doc-advisor 側 SoT（DES-006 / ADR-002 等の doc-advisor 設計書群）に委ねる。doc-advisor 側 SoT の結論が出たら本書の関連記述（§4.3 ガイド文書等）を更新する。

### 12.2 テスト用の強制バックエンド指定

「両方インストール時に doc-advisor を強制的に使うフラグ」（`--backend doc-advisor` 等）は本設計では実装しない。テスト網羅性のため将来追加する可能性あり。追加する場合は `/forge:query-db-*` の引数に `--backend {auto|doc-db|doc-advisor}` を追加し、デフォルトは `auto`。

### 12.3 命名「db」の汎用性

`update-db-*` / `query-db-*` の「db」は「document database（文書検索インデックス全般）」の意味で抽象的に使用する。doc-db プラグインの「db」と語感が重複するため、将来的な命名再考の余地はあるが、本設計では確定とする。

### 12.4 DES-007 反映漏れ（独立 issue）

API キー要件の表記揺れは [#53](https://github.com/BlueEventHorizon/bw-cc-plugins/issues/53) で別途扱う。本設計とは独立して進める。

---

## 13. 受け入れ条件

以下を全て満たす:

1. doc-db のみインストール + API キーありで forge の全 skill（review / start-* / clean-rules / merge-specs）が完全動作する
2. doc-advisor のみインストールで forge の全 skill が完全動作する（doc-advisor の auto モードがフラグなし呼び出しで応答を返す。内部挙動は doc-advisor 側 SoT に従う、§5.3）
3. 両方インストール時、§2.3 分岐テーブル A に従い API キーありなら doc-db、API キーなしなら doc-advisor が採用される
4. どちらもインストールされていない場合、`/forge:query-db-*` および `/forge:update-db-*` は §5.1 のエラーメッセージで終了する
5. forge 配下の skill から `/doc-advisor:*` への **Skill ツール呼び出し** は新規 forge:query-db-* / forge:update-db-* 内のみに集約され、他の forge skill から直接呼ばれていない（説明文中の "doc-advisor" 文字列言及は許可）。`grep -rn -E 'query-rules|query-specs|create-rules-toc|create-specs-toc' ./` をプロジェクトルート全体（`plugins/forge/skills/` / `.claude/skills/` / `.agents/skills/` を含む）で実行し、説明文中の言及（例: 再帰防止注記、README 等の説明）以外で 0 件であること。Skill 呼び出しはプレフィックスあり (`/doc-advisor:query-rules` 等) / なし (`query-rules` 単独) の両形式で記述可能なため、スキル名ベースで検索することで両形式を一括捕捉する
6. forge の新規 skill から doc-advisor を呼ぶ際に `--toc` / `--index` が付いていない（フラグなし = auto 委譲）
7. §10.2 SW-01 〜 SW-11 が観察的検証で全て期待動作を示す
8. doc-advisor 側の前提条件（§6）が満たされている: フラグなし呼び出しで auto モードが `Required documents:` 形式の応答を返し、`query-{rules,specs}` / `create-{rules,specs}-toc` の description が抽象 skill と競合するトリガー句を持たない
9. **両バックエンドの出力先頭が `Required documents:` 形式に統一されている**（doc-db:query / doc-advisor:query-rules / doc-advisor:query-specs）。後段セクションは 2 軸で検証する: **(軸①) forge 主処理（`/forge:query-db-*` のパスリスト抽出）からは後段を参照しない**（任意扱い、後段の有無・内容に依存せずパスリスト抽出が成立）。**(軸②) `/doc-db:query` 単独契約としては FNC-006 OUT-01/OUT-02 / DES-026 に従い chunk 見出し階層・chunk テキスト・スコア内訳（embedding / lexical / rerank）・ヒット理由を後段に必須出力する**（省略不可）。doc-advisor:query-* は後段を付加しない。
10. **テストで先頭セクション形式の一致が機械的に検証されている**（`tests/common/test_query_output_contract.py`（仮）等）

---

## 改定履歴

| 日付       | バージョン | 変更内容                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ---------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-05-16 | 1.0        | 初版作成                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| 2026-05-18 | 1.1        | forge 文書スタイル指針および ID 参照記法に整合させる文書整備（specs パス参照→ID 参照置換、見出し階層整合、コードブロック言語指定、メタデータ関連要件補完、ファイル名命名規則準拠、誤参照修正、update 系トリガー句の検索インデックス更新専用化、query-db-rules/specs argument-hint の `--top-n` / `--doc-type` 削除、トリガー句調整、§4.2 影響範囲の grep をスキル名ベース（プレフィックスあり/なし両方を捕捉）に変更しスコープをプロジェクトルート全体（`plugins/forge/skills/` / `.claude/skills/` / `.agents/skills/`）に拡張、既知対象リストを実測残存ファイルで拡充、受け入れ条件 #5 に grep ターゲット範囲を明文化、§3.1 出力変換規定を構造変換に限定するよう明確化、§5.3 文言マッピング責務との関係を注記、§3.1 引数表に `--toc` / `--index` を forge では受理しない旨と ADR-001 への参照を追記） |
| 2026-05-18 | 1.2        | COMMON-DES-001 §3.1（デフォルト継承型 / fork は §4 規定リストに限定）に整合。`/forge:query-db-rules` / `/forge:query-db-specs` を継承型に変更し、§3.1「subagent 契約 [MANDATORY]」から `context: fork` 必須化を削除（二重 fork 回避の根拠を §3.1 に明記）、§8.1 frontmatter テンプレから `context: fork` 行を削除、§8.1 雛形指針を継承型に変更済みの `query-forge-rules` 経由に更新、§10.3 テスト項目を `FORK_TARGET_SKILLS` から `CONSTRAINT_TARGET_SKILLS` への追加に変更し fork 検証を非継承型整合検証に置換。B 層（Role 制約）・C 層（引数解釈ガード）・出力契約は維持                                                                                                                                                                                                                              |
| 2026-05-18 | 1.3        | §3.1 subagent 契約に「呼び出し側の責務: args にプロンプトを渡してはならない [MANDATORY]」を新設。継承型のため親 context をそのまま保持する `/forge:query-db-*` を呼ぶ際、`args` は検索キーワード + 短い自然文タスク記述のみとし、Issue 本文・実装指示・差分等の親 context 貼り付けを禁止することを可否表で明示（COMMON-DES-001 §3.4 / §5.2 に整合）                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
