# DES-001 文書検索バックエンドの抽象化（switch-query）設計書

## メタデータ

| 項目         | 値                                                                              |
| ------------ | ------------------------------------------------------------------------------- |
| 設計 ID      | DES-001                                                                         |
| 対象スコープ | forge（doc-advisor 単独動作復活は別 issue で扱う）                              |
| バージョン   | forge 0.0.45 → 0.0.46、marketplace は本変更で上げない（doc-advisor のバージョン更新は #54 側で扱う） |
| 作成日       | 2026-05-16                                                                      |
| 更新日       | 2026-05-16（forge は doc-advisor をフラグなし=auto で呼び出し、auto は ToC + Index 両方を実行（API キーなしなら Index パス）する仕様に整理） |
| 関連 Issue   | [#53 docs: DES-007 (OPENAI_API_DOCDB_KEY 統一) の反映漏れを修正](https://github.com/BlueEventHorizon/bw-cc-plugins/issues/53)<br>[#54 doc-advisor: auto モードから doc-db 連携を削除し ToC + Index 並列実行に再定義](https://github.com/BlueEventHorizon/bw-cc-plugins/issues/54) |

---

## 1. 背景と目的

### 1.1 現状の問題

forge の各 skill（`review` / `start-design` / `start-plan` / `start-implement` / `clean-rules` / `merge-feature-specs` 等）は、ルール・仕様の検索および ToC 更新を **`/doc-advisor:query-rules` / `/doc-advisor:query-specs` / `/doc-advisor:create-rules-toc` / `/doc-advisor:create-specs-toc` を具体プラグイン名で直接呼ぶ** 構造になっている。これにより以下の不整合が生じている。

1. **doc-advisor を抜くと forge のフローが機能不全になる**。各 skill のガードは「利用可能ならスキップ」だが、**query 系の検索結果は後段の入力として必須** のため、スキップすると review のルール検索や start-implement のコンテキスト収集が無音で抜け落ちる。
2. **doc-db のみで運用したいユーザーが doc-advisor を強制される**。doc-db は機能的に doc-advisor の Embedding 検索を包含するが、forge が doc-advisor を直呼びしているため、doc-advisor をインストールしないと forge が完全動作しない。
3. **doc-advisor を「ついで」に入れているユーザーに不要な ToC 更新負荷が発生する**。主軸が doc-db でも、forge skill が `/doc-advisor:create-*-toc` を呼ぶ箇所が散在し、ToC 更新が毎回走る。
4. **doc-advisor 内の auto モード分岐と forge 側の利用可能ガードが二重分岐**。`plugins/doc-advisor/skills/query-rules/SKILL.md` の Step 1a で doc-db 有無を判定する処理と forge 側の判定が重複している。

### 1.2 目的

forge から検索バックエンド（doc-db / doc-advisor）への **依存逆転**。forge は具体プラグイン名ではなく抽象スキルを呼び、抽象スキル内部で「インストール済みバックエンドを 1 つ選ぶ」分岐を担う。これにより doc-db のみインストール、doc-advisor のみインストール、両方インストールのいずれでも forge が完全動作する。

### 1.3 非目的

- doc-advisor と doc-db の機械的排他（マーケットプレイスに排他制約はない）。
- 「両方インストール時の手動切り替え」（テスト用フラグは後回し。本設計では全自動分岐のみ実装）。
- 既存ユーザーへの後方互換（ユーザーは事実上 1 名のため）。

### 1.4 API キーの前提（DES-007 統一仕様）

doc-advisor / doc-db いずれも API キー解決は DES-007 で統一されており、本設計はこれを前提とする:

- **優先**: `OPENAI_API_DOCDB_KEY`
- **フォールバック**: `OPENAI_API_KEY`

つまり「doc-db を動かすために必要な API キー」と「doc-advisor の Embedding を動かすために必要な API キー」は**同じ**。

### 1.5 関心の分離（forge: バックエンド選択、doc-advisor: モード実行）

二重分岐を避けるため、**判定の責務を 2 階層に分離する**:

| 階層        | 担当                                                  | 判定軸                                                  |
| ----------- | ----------------------------------------------------- | ------------------------------------------------------- |
| forge       | **どのバックエンドを呼ぶか**（doc-db / doc-advisor）  | available-skills + API キー有無                         |
| doc-advisor | **auto モードで ToC + Index 両方を実行**              | API キー有無（Index のみ条件付きスキップ）              |

forge は doc-advisor を呼ぶときに `--toc` / `--index` を渡さない（**フラグなし = auto**）。doc-advisor 自身が:

- ToC キーワード検索を **常に実行**
- Embedding Index 検索を **API キーがあれば追加で実行**、なければ静かにスキップ

両方の結果をマージして返す。これにより各層が単一の責務を持ち、二重分岐にならない。

doc-advisor auto モードの再定義は [#54](https://github.com/BlueEventHorizon/bw-cc-plugins/issues/54) で実施。旧 auto モードは内部で doc-db を呼ぶ実装だったが、新 auto モードは「ToC + Index（API キーありなら）」のシンプルな並列実行になる。

### 1.5.1 API キー判定の共通仕様

「API キーあり」とは `OPENAI_API_DOCDB_KEY` または `OPENAI_API_KEY` のいずれかが**空でない値で設定されていること**（DES-007）。

forge / doc-advisor 双方で同じ判定式を用いる:

```bash
[ -n "${OPENAI_API_DOCDB_KEY:-}" ] || [ -n "${OPENAI_API_KEY:-}" ]
```

### 1.5.2 バックエンド + モードの最終動作

forge 側の分岐 + doc-advisor 側の auto モード仕様を統合すると、最終的な動作は以下:

- **両方インストール + API キーあり** → doc-db（Hybrid 検索）
- **両方インストール + API キーなし** → doc-advisor auto（ToC のみ実行、Index はパス）
- **doc-db のみ** → doc-db（API キー必須。なければ doc-db 側のエラーが伝播）
- **doc-advisor のみ + API キーあり** → doc-advisor auto（ToC + Index 両方実行）
- **doc-advisor のみ + API キーなし** → doc-advisor auto（ToC のみ実行、Index はパス）
- **どちらもなし** → エラー終了

---

## 2. アーキテクチャ概要

### 2.1 依存逆転の構造

```
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
              │                                   └─ doc-advisor auto モード:
              │                                      ├─ ToC キーワード検索を常に実行
              │                                      ├─ Embedding Index 検索を API キーがあれば追加実行
              │                                      └─ 両方の結果をマージして返す
              └─ (どちらもなし)                 → エラー終了（hint 付き）
```

### 2.2 新規追加スキル一覧

`plugins/forge/skills/` 配下に 4 つの skill を新設する。

| Skill 名                 | 役割                                                                       | user-invocable |
| ------------------------ | -------------------------------------------------------------------------- | -------------- |
| `/forge:query-db-rules`  | ルール文書の検索抽象。インストール済みバックエンドを自動選択して検索を実行 | true           |
| `/forge:query-db-specs`  | 仕様文書の検索抽象。同上                                                   | true           |
| `/forge:update-db-rules` | ルール文書のインデックス再構築抽象（採用バックエンドに応じて ToC **または** build-index のいずれか一方を実行） | true           |
| `/forge:update-db-specs` | 仕様文書のインデックス再構築抽象（採用バックエンドに応じて ToC **または** build-index のいずれか一方を実行）   | true           |

### 2.3 forge 側の分岐ルール（全自動）

`/forge:query-db-*` / `/forge:update-db-*` のすべてで以下の分岐を実行する。

1. SKILL.md 内で **available-skills を参照** し、doc-db / doc-advisor の有無を確認する（LLM が available-skills リストを読む）。
2. **両方インストール時のみ** Bash ツールで API キー有無を確認する（§1.5.1 の判定式）。
3. 以下のテーブルに従いバックエンドを選択する（Index 実施可否は doc-advisor 内 auto モードに委譲する）:

   | doc-db 有無 | doc-advisor 有無 | API キー   | forge が呼ぶ skill                       |
   | ----------- | ---------------- | ---------- | ---------------------------------------- |
   | あり        | あり             | あり       | `/doc-db:query`                          |
   | あり        | あり             | なし       | `/doc-advisor:query-rules`（フラグなし） |
   | あり        | なし             | （問わず） | `/doc-db:query`                          |
   | なし        | あり             | （問わず） | `/doc-advisor:query-rules`（フラグなし） |
   | なし        | なし             | （問わず） | **エラー終了**                           |

4. 選択したバックエンドの skill を `Skill` ツールで呼び出す。**doc-advisor を呼ぶ際は `--toc` / `--index` を付けない**（auto モードに任せる）。
5. バックエンド側のエラー（API キー未設定、Index 構築失敗等）はそのまま親に伝播させる。**他バックエンドへのフォールバックは行わない**。

> 設計意図:
> - **doc-advisor 単独インストール時に forge 側で API キー判定をしない**: doc-advisor の auto モードが ToC を常に動かし、Index を API キーがあれば追加実行する。forge 側で重複判定する必要がない
> - **両方インストール時のみ forge 側で API キー判定が必要**: 「キーがあるなら doc-db を選びたい、なければ doc-advisor」の判断が forge にしかできないため
> - **doc-db のみ単独時は API キー判定しない**（doc-db に API キーが必須なため、なければ doc-db のエラーで気付かせる）

---

## 3. 各スキルの仕様

### 3.1 `/forge:query-db-rules` / `/forge:query-db-specs`

#### 引数

| 引数         | 必須 | 説明                                                       |
| ------------ | ---- | ---------------------------------------------------------- |
| `{task}`     | 必須 | 検索クエリ（タスク記述・自然文）                           |
| `--top-n N`  | 任意 | 取得件数の上限。バックエンドにそのまま渡す                 |
| `--doc-type` | 任意 | specs 版のみ。`requirement,design` 等。バックエンドに転送 |

#### 実行フロー

1. available-skills 参照 + 必要なら API キー判定によるバックエンド選択（§2.3）。
2. **doc-db 採用時**:
   - `Skill` ツールで `/doc-db:query --category rules --query "{task}" --mode rerank` を呼ぶ（specs 版は `--category specs` および必要に応じ `--doc-type` を渡す）。
   - 内部で grep 補完が行われる（doc-db の仕様、DES-026）。
3. **doc-advisor 採用時**:
   - `Skill` ツールで `/doc-advisor:query-rules "{task}"` を **`--toc` / `--index` を付けずに** 呼ぶ（specs 版は `/doc-advisor:query-specs`）。
   - doc-advisor の auto モードが ToC + Index 両方を実行する。API キーがなければ Index は静かにスキップされ ToC のみが実行される（#54 で実装）。
4. **どちらもなし時**: §5.1 のエラー出力。

#### 出力

バックエンドの出力契約をそのまま親に返す（path リスト + スコア + 内容要約）。

### 3.2 `/forge:update-db-rules` / `/forge:update-db-specs`

#### 引数

| 引数     | 必須 | 説明                                       |
| -------- | ---- | ------------------------------------------ |
| `--full` | 任意 | 全件再構築モード。バックエンド側に転送 |

#### 実行フロー

1. available-skills 参照 + 必要なら API キー判定によるバックエンド選択（§2.3）。
2. **doc-db 採用時**: `Skill` ツールで `/doc-db:build-index --category rules [--full]`（specs 版は `--category specs`）を呼ぶ。
3. **doc-advisor 採用時**: `Skill` ツールで `/doc-advisor:create-rules-toc [--full]`（specs 版は `/doc-advisor:create-specs-toc`）を呼ぶ。
4. **どちらもなし時**: §5.1 のエラー出力。

> 注: `create-*-toc` は API キー不要のため、doc-advisor 採用時に `--toc` / `--index` の分岐は不要。query 系のみが auto モード分岐を活用する。

#### 注記

doc-db の `build-index` は `query` 時に自動再生成される（DES-006）。`/forge:update-db-*` を明示的に呼ばずに `/forge:query-db-*` だけ呼んでも doc-db 環境では動作する。`/forge:update-db-*` は「ドキュメント編集直後に確実にインデックスを最新化したい」場合に明示的に使う。

doc-advisor の `create-*-toc` は API キー不要のため、「両方インストール + API キーなし」のシナリオで update-db-* が呼ばれた場合も問題なく動作する。

---

## 4. forge 配下の置換対象

検索および ToC 更新の呼び出しを抽象 skill に置換する。

### 4.1 置換マッピング

| 旧呼び出し                      | 新呼び出し                |
| ------------------------------- | ------------------------- |
| `/doc-advisor:query-rules`      | `/forge:query-db-rules`   |
| `/doc-advisor:query-specs`      | `/forge:query-db-specs`   |
| `/doc-advisor:create-rules-toc` | `/forge:update-db-rules`  |
| `/doc-advisor:create-specs-toc` | `/forge:update-db-specs`  |

### 4.2 影響範囲（要書き換え）

`grep -rn "doc-advisor:query-\|doc-advisor:create-" plugins/forge/` で全件特定する。判明している既知の対象:

- `plugins/forge/skills/review/SKILL.md`（L211, L213, L232, L236, L238, L652, L676）
- `plugins/forge/skills/start-design/SKILL.md`（L281）
- `plugins/forge/skills/start-plan/SKILL.md`（L303）
- `plugins/forge/skills/clean-rules/SKILL.md`（L288）
- `plugins/forge/skills/merge-feature-specs/SKILL.md`（L64, L105-L122, L564, L570, L572, L608, L612, L624, L626）

`merge-feature-specs` の Phase 0 にある「doc-advisor 必須」検査は **抽象 skill 必須検査** に置き換える（`/forge:query-db-specs` または `/forge:update-db-specs` の存在のみで判定）。

### 4.3 CLAUDE.md / README / guide 文書

| 文書                                  | 変更                                                                            |
| ------------------------------------- | ------------------------------------------------------------------------------- |
| `CLAUDE.md`                           | `/query-rules` → `/forge:query-db-rules`、`/query-specs` → `/forge:query-db-specs` |
| `README.md` / `README_en.md`          | スキル一覧の刷新（forge 側に新規 4 skill、doc-advisor 側の description 修正）      |
| `docs/readme/guide_doc-advisor_ja.md` | doc-advisor 単独利用時の呼び方を明記（論点3 の結論を反映）                       |
| `docs/readme/forge/guide_*.md`        | 検索・ToC 更新の呼び方を抽象 skill に統一                                       |

---

## 5. エラー処理契約

### 5.1 バックエンド不在時

`/forge:query-db-*` / `/forge:update-db-*` の双方で以下のメッセージを返して終了する。

```
ERROR: 文書検索バックエンドが見つかりません
       doc-db または doc-advisor のいずれかをインストールしてください

       /plugin install doc-db@bw-cc-plugins
       /plugin install doc-advisor@bw-cc-plugins
```

### 5.2 採用バックエンドの API キー未設定

§2.3 の分岐により、API キー未設定で doc-db が採用されるのは **「doc-db 単独インストール」の場合のみ**（両方インストール時は API キーなしなら doc-advisor が選ばれるため）。

- **doc-db 単独 + API キーなし**: doc-db の `embedding_api.py` が出力する `error` + `hint` をそのまま親に伝播。`/forge:query-db-*` 側で再パッケージしない。ユーザーは `OPENAI_API_DOCDB_KEY` を設定するか、doc-advisor を追加インストールする。
- **doc-advisor 採用時**: auto モードが API キー有無で `--toc` / `--index` に内部分岐するため、常に動作する。

### 5.3 doc-advisor 採用時の ToC / Index 未構築

doc-advisor auto モード内で発生するエラーは doc-advisor 側で扱う。forge 側で再パッケージしない:

- **ToC 未構築**: doc-advisor:query-rules 内で AskUserQuestion を表示する（既存仕様）。文言中に `/doc-advisor:create-rules-toc` が含まれていれば、`/forge:update-db-rules` に書き換える（#54 で実装）。
- **Embedding Index 未構築 + API キーあり**: doc-advisor:query-rules 内で Index を自動構築する（既存仕様）。失敗時のエラー / hint はそのまま親に伝播。
- **API キーなし**: auto モードは Index を静かにスキップする。ToC のみで実行され、エラーにはならない。

### 5.4 一方のバックエンドが失敗した場合のフォールバック

**実装しない**。最初に選択したバックエンドが失敗したらそのままエラー終了。これは「両方インストールしている場合に doc-db が落ちたら doc-advisor で救う」という挙動を意図的に行わない仕様。動作が不定になることを防ぐ。

---

## 6. doc-advisor の変更（[#54](https://github.com/BlueEventHorizon/bw-cc-plugins/issues/54) で実施）

doc-advisor 自身の修正は **本設計書のスコープ外** とし、独立 issue [#54](https://github.com/BlueEventHorizon/bw-cc-plugins/issues/54) で実施する。本設計書は doc-advisor が以下の状態に修正されていることを **前提** とする:

- `query-rules` / `query-specs` の auto モードから **doc-db 連携部分（Step 1a〜3）が削除** されている
- auto モードが「ToC を常に実行、API キーがあれば Index も追加実行、両方の結果をマージ」の仕様に再定義されている
- フラグなしで呼ばれた場合に auto モードが動作する（`/forge:query-db-*` はフラグなしで呼ぶ）
- description のトリガー句行が削除され、`/forge:query-db-*` との競合がない
- `create-rules-toc` / `create-specs-toc` の description のトリガー句行も削除されている
- バージョンが 0.3.0 に上がっている

### 6.1 forge 側から呼び出す際の前提

DES-001 と #54 を別々の PR で進める場合、forge 側の呼び出し変更（§4.2）を merge する前に #54 を merge する必要がある。順序を逆にすると、forge が doc-advisor をフラグなしで呼ぶのに対し、旧 doc-advisor が doc-db 連携を試みて二重分岐の動作不整合になる。

実装手順（§11）では #54 を先に完了させる前提で記述する。

---

## 7. doc-db の変更

### 7.1 仕様変更なし

doc-db の `query` / `build-index` skill には**変更を加えない**。`/forge:query-db-*` から呼ばれる際の引数契約は doc-db の既存仕様（DES-006、DES-026）にそのまま準拠する。

### 7.2 バージョン

変更なし（0.0.1 のまま）。

---

## 8. forge の変更（v0.0.46）

### 8.1 新規 skill

`plugins/forge/skills/` 配下に以下を新設する。**SKILL.md のみ**。Python スクリプトは作成しない（分岐ロジックは SKILL.md 内のワークフロー記述で完結）。

```
plugins/forge/skills/
├── query-db-rules/
│   └── SKILL.md
├── query-db-specs/
│   └── SKILL.md
├── update-db-rules/
│   └── SKILL.md
└── update-db-specs/
    └── SKILL.md
```

### 8.2 既存 skill の参照置換とガード方針

§4.2 の各 skill 内の `/doc-advisor:*` 呼び出しを、§4.1 のマッピングに従って一斉置換する。**ガードは以下のように扱う**:

- **query 系**（`/forge:query-db-rules` / `/forge:query-db-specs`）: forge skill 側の「利用可能ならスキップ」ガードを **削除する**。抽象 skill 自体がバックエンド不在時にエラー終了するため、forge 側の重複ガードは不要かつ有害（検索結果が必須なのにスキップされる悪い挙動を生む）。
- **update 系**（`/forge:update-db-rules` / `/forge:update-db-specs`）: forge skill 側のガードを **残す**。ToC 更新は副作用更新であって主処理の完結に必須ではないため、バックエンド不在時に主処理（設計書保存等）まで巻き込んで失敗させない。

### 8.3 plugin.json の更新

`plugins/forge/.claude-plugin/plugin.json` の skill リストに 4 件追加。バージョン 0.0.45 → **0.0.46**。

### 8.4 forge 内部 docs/rules への記述

`plugins/forge/docs/` 配下に skill 作成規約・呼び出し契約があれば、抽象 skill の呼び方を追記する（必要に応じて `/forge:query-forge-rules` の ToC 再生成: `update-forge-toc`）。

---

## 9. marketplace の変更

`.claude-plugin/marketplace.json` のうち **本設計のスコープで更新するのは forge のみ**:

- forge: 0.0.45 → 0.0.46
- doc-advisor: 0.2.6 → 0.3.0 は **#54 側で更新する**（本 PR で重複編集しない）
- marketplace 全体バージョン: **本変更では更新しない**

---

## 10. テスト設計

### 10.1 方針

available-skills は Claude プロンプトに含まれる情報で、**Python から取得する API は存在しない**。そのため抽象 skill の分岐ロジックを Python unittest で網羅することはできない。テスト戦略は以下に限定する:

- **既存テストの最小書き換え** — `/doc-advisor:query-*` を直接想定したテストがあれば、抽象 skill 経由を想定する形に書き換える
- **観察的検証** — 実際の Claude Code セッションで以下シナリオを手動実行し、期待動作を確認する
- **マニフェスト整合性テストの拡張** — `tests/common/` に新規 skill 4 件の plugin.json 登録チェックを追加（機械的に検証可能）

### 10.2 観察的検証シナリオ

実装後、以下のシナリオを手動で実行して動作確認する。

| ID     | シナリオ                                                       | 期待結果                                                  |
| ------ | -------------------------------------------------------------- | --------------------------------------------------------- |
| SW-01  | doc-db のみインストール + API キーあり                          | `/forge:query-db-rules` が doc-db を呼ぶ                          |
| SW-02  | doc-db のみインストール + API キーなし                          | doc-db のエラー hint が伝播（doc-advisor へのフォールバックなし） |
| SW-03a | doc-advisor のみインストール + API キーあり                     | `/forge:query-db-rules` が doc-advisor をフラグなしで呼ぶ → auto が ToC + Index 両方を実行し結果をマージ |
| SW-03b | doc-advisor のみインストール + API キーなし                     | `/forge:query-db-rules` が doc-advisor をフラグなしで呼ぶ → auto が ToC のみ実行（Index は静かにスキップ） |
| SW-04a | 両方インストール + API キーあり                                 | doc-db が採用される（doc-advisor は呼ばれない）                   |
| SW-04b | 両方インストール + API キーなし                                 | doc-advisor がフラグなしで採用される → auto が ToC のみ実行（Index スキップ） |
| SW-05  | どちらもインストールされていない                                | §5.1 のエラーメッセージで終了                                     |
| SW-06  | `/forge:update-db-rules` (doc-db 採用、API キーあり)            | `/doc-db:build-index --category rules` を呼ぶ                     |
| SW-07  | `/forge:update-db-rules` (doc-advisor 採用、API キーなしでも可) | `/doc-advisor:create-rules-toc` を呼ぶ                            |
| SW-08  | `/forge:update-db-rules --full`                                 | バックエンドに `--full` が転送される                              |
| SW-09  | 両方インストール + `OPENAI_API_DOCDB_KEY` のみ設定              | doc-db が採用される（DOCDB キーで判定）                           |
| SW-10  | 両方インストール + `OPENAI_API_KEY` のみ設定（フォールバック）  | doc-db が採用される（DES-007 のフォールバック経路）               |
| SW-11  | doc-advisor のみインストール時に forge が `--toc`/`--index` を渡していないことを確認 | grep 等で forge SKILL 内に `--toc` / `--index` 文字列が無い |

### 10.3 機械的に検証する範囲

`tests/common/` のマニフェスト整合性テストに以下を追加:

- `plugins/forge/.claude-plugin/plugin.json` に新規 4 skill が登録されている
- 各 SKILL.md の frontmatter が正しい（`name`, `description`, `user-invocable` 等）
- 旧呼び出し（`/doc-advisor:query-*` / `/doc-advisor:create-*-toc`）が forge skill 内の Skill ツール呼び出しから消滅している（`grep` ベース）

---

## 11. 実装手順（推奨順序）

依存関係に従って以下の順序で実装する。Python スクリプトを作成しないため、すべて SKILL.md と既存ファイルの編集で完結する。

1. **[前提] #54 を先に完了させる**: doc-advisor v0.3.0 で auto モード削除・description のトリガー句削除・`--toc`/`--index` 必須化を済ませる（§6）。
2. forge:query-db-rules / query-db-specs / update-db-rules / update-db-specs の SKILL.md を新設（§8.1）。
3. forge 配下の参照置換（§4.2）。query 系のガード削除、update 系のガード維持（§8.2）。
4. CLAUDE.md / README / guide 文書の更新（§4.3）。
5. plugin.json バージョン更新（§8.3）、`.claude-plugin/marketplace.json` の forge プラグインバージョン更新（§9。doc-advisor バージョンは #54 側で更新済み）。
6. マニフェスト整合性テストの拡張（§10.3）。既存テストで `/doc-advisor:query-*` を想定するものがあれば書き換え。
7. 観察的検証（§10.2）を実行し、期待動作を確認。
8. CHANGELOG.md にエントリ追加。

---

## 12. 残課題（別途議論）

### 12.1 論点3: doc-advisor 単独利用の可否

`/doc-advisor:query-rules` / `/doc-advisor:query-specs` / `/doc-advisor:create-*-toc` を user-invocable のまま残すか、forge:* 経由のみに格下げするか。

- 残す案: forge をインストールしない小規模利用も可能。エントリポイント二重化のコスト
- 格下げ案: forge を実質的に必須化。整合性が高い

本設計書では「**残す + description のトリガー句行のみ削除**」を暫定方針として記述（#54 で実施）。論点3 の結論次第で再修正する。

### 12.2 テスト用の強制バックエンド指定

「両方インストール時に doc-advisor を強制的に使うフラグ」（`--backend doc-advisor` 等）は本設計では実装しない。テスト網羅性のため将来追加する可能性あり。追加する場合は `/forge:query-db-*` の引数に `--backend {auto|doc-db|doc-advisor}` を追加し、デフォルトは `auto`。

### 12.3 命名「db」の汎用性

`update-db-*` / `query-db-*` の「db」は「document database（文書検索インデックス全般）」の意味で抽象的に使用する。doc-db プラグインの「db」と語感が重複するため、将来的な命名再考の余地はあるが、本設計では確定とする。

### 12.4 DES-007 反映漏れ（独立 issue）

API キー要件の表記揺れは [#53](https://github.com/BlueEventHorizon/bw-cc-plugins/issues/53) で別途扱う。本設計とは独立して進める。

---

## 13. 受け入れ条件

以下を全て満たす:

1. doc-db のみインストール + API キーありで forge の全 skill（review / start-* / clean-rules / merge-feature-specs）が完全動作する
2. doc-advisor のみインストールで forge の全 skill が完全動作する（auto モードで API キーありなら ToC + Index 両方、なしなら ToC のみ）
3. 両方インストール時、API キーありなら doc-db、API キーなしなら doc-advisor（auto → ToC のみ実行）が採用される
4. どちらもインストールされていない場合、`/forge:query-db-*` および `/forge:update-db-*` は §5.1 のエラーメッセージで終了する
5. forge 配下の skill から `/doc-advisor:*` への **Skill ツール呼び出し** は新規 forge:query-db-* / forge:update-db-* 内のみに集約され、他の forge skill から直接呼ばれていない（説明文中の "doc-advisor" 文字列言及は許可）。`grep` で `plugins/forge/skills/*/SKILL.md` 内の Skill ツール呼び出し箇所を検査
6. forge の新規 skill から doc-advisor を呼ぶ際に `--toc` / `--index` が付いていない（フラグなし = auto 委譲）
7. §10.2 SW-01 〜 SW-11 が観察的検証で全て期待動作を示す
8. #54 が先に merge されており、doc-advisor の auto モードが「ToC + Index 並列実行（API キーなしは Index パス）」に再定義済みである
9. CHANGELOG.md に変更内容が記載されている
