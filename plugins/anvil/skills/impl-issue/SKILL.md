---
name: impl-issue
description: |
  GitHub Issue の実装を準備から完了まで一貫して行う。修正のための調査（仕様書・実装ルール・類似 PR・既存コード）を自ら行い、実装計画の策定・Issue への解決内容記載・実装・レビュー・commit・PR 作成まで進める。UI Issue の場合は Figma ベースの設計・実装・レビューを `anvil:impl-ui` に委譲する。
  `/anvil:triage-issue` がワンショット実装と判定した後に起動されるのが通常経路だが、ユーザーが直接 `/anvil:impl-issue #N` で起動してもよい。
  トリガー: "この Issue を実装して", "#N を実装", "impl-issue"
user-invocable: true
argument-hint: "<issue番号 または URL>"
allowed-tools: Bash(git *), Bash(gh issue view *), Bash(gh issue edit *), Bash(gh pr list *), Bash(gh pr view *), Bash(gh pr diff *), Bash(gh pr edit *), Bash(gh repo view *), Bash(gh api *), Bash(mktemp *), Bash(tee *), Bash(python3 *), AskUserQuestion, Skill, Read, Write, Edit, Grep, Glob
---

# /anvil:impl-issue

GitHub Issue の実装を準備から完了まで一貫して行うオーケストレータ。このスキルは指定された Issue の実装のみを行う。親が依頼している他の作業を引き継いではならない。

**このスキルが Issue に書き込む内容**: 解決の内容（対策・実装計画・TODO）のみ。課題の内容（背景 / 現象 / 原因）は `/anvil:create-issue` または `/anvil:triage-issue` が書いたものであり、上書きしない。

> [!IMPORTANT]
> 本スキルの Phase 2〜5 は**修正のための調査**であり、`/anvil:triage-issue` の調査（Issue の正しさの検証）とは目的が異なる。triage の監査コメントが Issue にあれば参考にしてよいが、それを根拠に調査を省かない。直接起動された場合も同じ手順を踏む。

## Goal

Issue の調査・ブランチ確認・実装計画の Issue 記載・実装・レビュー・commit・PR 作成まで、全 Phase を完走すること。`AskUserQuestion` が必要な判断点と、レビューで確信の持てない所見の採否以外は、ユーザー介入なしに継続する。

## フロー継続

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ `AskUserQuestion` で確認する。

## ワークフロー

| #  | Phase                                            | 対象          |
| -- | ------------------------------------------------ | ------------- |
| 0  | 前処理（リポジトリ解決・再開判定・ブランチ準備） | 全て          |
| 1  | Issue の内容を把握する                           | 全て          |
| 2  | 仕様書を調査する                                 | 全て          |
| 3  | 実装ルールを調査する                             | 全て          |
| 4  | 類似 PR を調査・学習する                         | 全て          |
| 5  | 既存コードを調査する                             | 全て          |
| 6  | UI 設計を委譲する（impl-ui design）              | UI Issue のみ |
| 7  | 実装計画を策定する                               | 全て          |
| 8  | Issue を更新する（解決内容を追記）               | 全て          |
| 9  | 実装に進むか確認する                             | 全て          |
| 10 | 実装する（UI Issue は impl-ui implement）        | 全て          |
| 11 | 実装レビューを行う                               | 非 UI Issue   |
| 12 | 後処理（commit & PR 作成・Closes 保証）          | 全て          |

UI Issue の実装レビューは Phase 10 の `impl-ui --stage implement` に含まれるため、Phase 11 は非 UI Issue のみが通る。

Phase を追加・改番するときは、この表・本文の見出し・`references/` 内の Phase 番号を同時に更新する。

---

## Phase 0: 前処理（リポジトリ解決・再開判定・ブランチ準備）

### 0-1: リポジトリ情報を解決する

`.git_information.yaml` が存在する場合はそこから取得する:

```yaml
# .git_information.yaml
github:
  owner: "<owner>"
  repo: "<repo>"
  default_base_branch: develop # Phase 0-3 のデフォルトとして使用
```

ファイルが存在しない場合は `gh repo view --json nameWithOwner --jq '.nameWithOwner'` で取得する。取得した `<owner>/<repo>` と `<default_base_branch>` を以降のすべての `--repo` 引数に使用する。

#### 引数が Issue URL の場合のリポジトリ整合チェック [MANDATORY]

引数が **Issue URL**（`https://github.com/<owner>/<repo>/issues/<N>`）の場合、URL から `<url-owner>/<url-repo>` と `<N>` を抽出する。

- 現在のリポジトリと**一致** → 続行。以降は `<N>` を Issue 番号として扱う
- **不一致** → 警告して**中断する**。`<url-owner>/<url-repo>` と現在のリポジトリを示し、対象リポジトリで再実行するよう案内して終了する。別リポジトリの Issue を現在のリポジトリで実装する経路は持たない（Issue 本文への実装計画の追記先と、ブランチ・PR の作成先が食い違うため）

Issue 番号のみで渡された場合はこのチェックは不要。

### 0-2: Issue を取得し、実装再開を判定する

1. Issue の内容とコメントを取得する:

   ```bash
   gh issue view <issue番号> --repo <owner>/<repo>
   gh issue view <issue番号> --repo <owner>/<repo> --comments
   ```

   `/anvil:triage-issue` の監査コメント（「トリアージ結果」）があれば、Issue の是正内容・TASK 一覧・参照先パスを Phase 1〜5 の**参考**として控える（調査の代替にはしない）。

2. **実装再開の判定（PR 作成失敗からの再開検知）**: **現在のブランチ名に Issue 番号が含まれる場合のみ**判定する。別ブランチの探索・リモートブランチの checkout は行わない。

   現在のブランチ名に Issue 番号が含まれ、かつ以下の**すべて**に該当する場合、Phase 1〜11 は完了済みで PR 作成のみが未達と推定できる:
   - 現在のブランチがベースブランチに対して commit が進んでいる
   - Issue 本文に本スキルが Phase 8 で書き込む「## 実装計画」セクションが既に存在する

   該当する場合、`AskUserQuestion` で確認する:

   ```text
   Issue #<N> は実装・commit まで完了しているようです（PR 作成のみ未達と推定）。
   - Phase 12（commit 差分確認・PR 作成）から再開する（推奨）
   - 最初から通常のフロー（Phase 1〜）を実行し直す
   ```

   「Phase 12 から再開する」を選んだ場合、Phase 1〜11 をすべてスキップし Phase 12 へ直接進む。

   ブランチ名に Issue 番号が含まれない場合は再開判定をせず 0-3 へ進む。対象 Issue のブランチで作業したい場合は、ユーザーが手動で checkout してから本スキルを再実行する。

### 0-3: ブランチを確認・作成する

0-2 で「Phase 12 から再開する」を選んだ場合は本ステップをスキップする。

1. `git branch --show-current` で現在のブランチを確認する
2. **Issue 番号がブランチ名に含まれているかを判定**する:
   - 含まれている（例: `fix/12-xxx`）→ 対応ブランチと判断し、そのまま Phase 1 へ
   - 含まれていない → `AskUserQuestion` で確認する:

     ```text
     現在 `<current-branch>` にいます。Issue #N 用の作業ブランチを作成しますか？
     - はい: ブランチを作成します
     - いいえ: 現在のブランチで作業を続けます
     ```

3. **ブランチを作成する場合**:

   a. ベースブランチを `AskUserQuestion` で確認する（デフォルト: 0-1 の `default_base_branch`、未取得なら `develop`）

   b. ベースブランチの最新状態を取得する。**ベースブランチをローカルに checkout しない**（git worktree で別 worktree に checkout 済みの環境でも失敗しないため）:

   ```bash
   git fetch origin <base-branch>
   ```

   `fetch` が失敗 → `AskUserQuestion` で対応確認（中止推奨）

   c. ブランチ名を決定する。**Issue のラベルから判定**する（部分一致・大文字小文字無視。複数一致は表の上位を優先）:

   | プレフィックス | 一致するラベル語句                                       |
   | -------------- | -------------------------------------------------------- |
   | `fix/`         | `bug`, `fix`, `defect`, `修正`, `不具合`                 |
   | `feature/`     | `feature`, `enhancement`, `feat`, `新機能`, `機能追加`   |
   | `refactor/`    | `refactor`, `refactoring`, `cleanup`, `リファクタ`       |
   | `docs/`        | `doc`, `docs`, `documentation`, `文書`                   |
   | `chore/`       | `chore`, `build`, `ci`, `test`, `dependencies`, `その他` |

   どのラベルにも該当しない場合は `AskUserQuestion` でプレフィックスを選択させる。**タイトルや本文から自動推測しない**（非決定的になるため）。

   形式: `<prefix>/<issue-number>-<slug>`（slug は Issue タイトルを kebab-case 化、英数字以外は `-` に置換、連続 `-` は 1 つに正規化、末尾 `-` 除去）

   d. `origin/<base-branch>` を起点に新規ブランチを作成する。**`--no-track` 必須**（付けないと upstream が `origin/<base-branch>` になり、`push.default=upstream` 等の設定ではベースブランチへ push されてしまう）:

   ```bash
   git checkout -b <branch-name> origin/<base-branch> --no-track
   ```

---

## Phase 1: Issue の内容を把握する

1. タイトル・本文・ラベルから実装内容・タスク種別を把握する（内容は 0-2 で取得済み）
2. 既存の TODO や計画が記載されていれば確認する
3. **UI Issue か判定する**: 次の表で判定し、判断が割れた場合は `AskUserQuestion` でユーザーに確認する

   | 観点                                                 | UI Issue | データ / API / ドメイン Issue |
   | ---------------------------------------------------- | -------- | ----------------------------- |
   | 実装対象が UI / 画面ディレクトリ（プロジェクト規約） | ✅       | ✗                             |
   | Figma URL が「**実装対象**」として記載               | ✅       | ✗（参考添付なら非 UI）        |
   | 画面設計書への参照が「実装対象」として記載           | ✅       | ✗（参考添付なら非 UI）        |
   | ラベルに UI / 画面相当の表示                         | ✅       | ✗                             |
   | ラベルに data / domain / infrastructure / api 相当   | ✗        | ✅                            |
   | 実装対象がドメイン層 / データ層のみ                  | ✗        | ✅                            |

   「Figma URL や画面名が**参考として**書かれているだけ」のデータ / API Issue を UI Issue と誤判定しないこと。UI Issue に固有の前提確認（Figma PAT 疎通・依存ツール）は Phase 6 で `anvil:impl-ui` が行う。

## Phase 2: 仕様書を調査する

`Skill` ツールで `/forge:query-db-specs` を呼び、実装に関係する仕様書を特定する。`args` には Issue 本文をそのまま貼らず、Issue のタイトル・本文から**抽出した検索キーワード**または**短い自然文のタスク記述**を渡す。

- 特定した仕様書は**すべて** Read で本文を読む（見出しだけで済ませない）
- API レスポンス構造・画面要件・制約・バリデーションルール・用語定義を、実装に使える粒度で把握する
- 関連する周辺文書（同じ feature の要件定義書・設計書・ADR）も読む。ADR は「その案は検討済みで採らなかった」の記録であり、これから採る実装方針が過去に棄却されていないかを確認する
- 精読中に未特定の関連仕様書が判明したら追加で読む
- 該当が無ければ「該当なし」と記録する

**外部リポジトリ・symlink**: 仕様書ディレクトリが symlink で別 Git リポジトリを指している場合、ローカルに実体が無くても仕様書が無いと判断しない。実体の GitHub リポジトリを `gh api "repos/<spec-owner>/<spec-repo>/contents/<path>?ref=<ref>"` で取得し（レスポンスの `content` は base64）、Issue に記載するときは実体の GitHub URL を使う（`/forge:query-db-rules` で「外部仕様書リポジトリ」「symlink」等を検索し、リポジトリ名・URL 形式の規約を得る）。取得に失敗した場合は黙って読み飛ばさず `AskUserQuestion` で確認方法を確認する。

**UI Issue の場合の追加記録**: 画面設計書・確認/調整事項ドキュメントを読み、以下を記録する（Phase 6 で `anvil:impl-ui` に渡す）:

- 画面設計書ファイルパス / 画面設計書の GitHub URL（Issue 記載用）
- 確認・調整事項ファイルパス（存在する場合）
- Figma URL（画面設計書に記載されているもの）
- 画面 ID・画面名

## Phase 3: 実装ルールを調査する

`Skill` ツールで `/forge:query-db-rules` を呼び、実装に関係するルール文書を特定する。`args` は Phase 2 と同じく抽出キーワードまたは短いタスク記述に限る。

- 特定したルール文書は**すべて** Read で本文を読む
- CLAUDE.md に記載されているプロジェクト構造・アーキテクチャ・禁止事項を確認する
- 「architecture」「coding」「layer」「ディレクトリ構造」「テスト方針」等の一般クエリも投げ、Issue の話題に直接出てこない基盤ルールを取りこぼさない
- 該当が無ければ「該当なし」と記録する

## Phase 4: 類似 PR を調査・学習する

今回の実装と**同じスコープ**（同様の機能・同様のレイヤー変更）のマージ済み PR を **3 件以上**探し、実装パターンを学習する。

```bash
gh pr list --repo <owner>/<repo> --state merged --search "<キーワード>" --limit 20
gh pr view <pr番号> --repo <owner>/<repo>
gh pr diff <pr番号> --repo <owner>/<repo> --name-only
```

学習する観点:

- どのレイヤー・どのディレクトリのファイルが変更されているか
- ドメインモデル・値オブジェクト / リポジトリ・データソースの実装パターン
- 依存性注入・コンポジションの設定方法、状態管理の実装スタイル
- テスト対象範囲とテストの書き方

**原則**: 今回の実装は学習した PR と**同じスコープ・同じ実装方法**を採用する。独自パターンを混入させない。乖離する必要がある場合は、理由を実装計画に明記する。同じスコープの PR が見つからなければ「該当なし」と記録し、Phase 5 の兄弟機能の実装をパターンの根拠にする。

## Phase 5: 既存コードを調査する

Grep / Glob（利用可能であればコードシンボル検索ツール）で、実装に再利用できる既存資産と、変更が波及する範囲を洗い出す。表面的な検索で済ませず、実装計画に耐える粒度で特定する。

探索対象（見つからなかった場合も「該当なし」を記録する）:

- **変更対象の実体**と、その**参照元・呼び出し元**（テスト・文書・設定を含む影響範囲）
- **同一目的の状態管理・Provider・Notifier**: 機能名で全体 Grep
- **同一目的のドメインモデル / enum / 値オブジェクト**: ドメインモデル配置場所（`/forge:query-db-rules` で「ディレクトリ構造」を検索）を Glob / Grep
- **同じ場所の既存ファイル（仮実装含む）**: 同名ファイルの有無
- **兄弟機能（同種パターンを持つ他画面・他機能）の実装** を **3 件以上**。直近マージ・進行中の PR で確立されたパターンを重視し、`git log` で最近の変更を確認する
- **既存 extension / utility / helper**、**i18n / debug / route エントリ**、**共通コンポーネント**（配置先はプロジェクト規約から取得）
- 動作確認手段（debug 画面・カタログ等のプロジェクト固有導線）

特定した資産を Read で精読し、[`references/reuse-principles.md`](references/reuse-principles.md) の**新規作成回避の原則・検証チェックリスト・共通コンポーネント採用判断**を Phase 5〜7 で適用する。チェックリストに未確認項目が残る場合は補完調査する。

## Phase 6: UI 設計を委譲する（UI Issue のみ）

**条件**: Phase 1 で UI Issue と判定された場合のみ実行。それ以外はスキップして Phase 7 へ。

`Skill` ツールで `anvil:impl-ui` を起動する（args: `<issue番号> --stage design`）。Phase 2 で記録した画面 ID・画面設計書パス・確認/調整事項パス・Figma URL と、Phase 5 の既存コード調査結果は同一セッションの context で共有される。

`impl-ui` は Figma PAT・依存ツールの確認、デザイン仕様書の作成（`/anvil:prepare-figma`）、ユーザーによる視覚比較レビュー、実装設計書（Typography 対応表・アクション一覧を含む）の作成を行い、デザイン仕様書パス・実装設計書パス・承認結果を返す。中断・失敗が返った場合はその内容をそのまま報告して停止する。

## Phase 7: 実装計画を策定する

Phase 1〜5（UI Issue は Phase 1〜6）の調査結果をもとに以下を決定する:

1. **実装スコープ**: どのレイヤーに何を実装するか（具体的なクラス名・ファイルパスまで）
2. **実装順序**: 依存関係を考慮した実装の順番
3. **スコープ外**: 今回実装しないもの（理由・担当）。異常系・防御的実装をスコープに含めるか迷う場合は `Skill` ツールで `/forge:query-forge-rules` に「比例性」「過剰設計」等を渡し、判断基準を確認する
4. **参考 PR**: 実装方法の根拠となる PR（Phase 4）

Issue へ記載する形式は [`assets/TEMPLATE.md`](assets/TEMPLATE.md) に従う。UI Issue の実装設計書は Phase 6 で `impl-ui` が作成済みであり、本 Phase では TEMPLATE の「関連ドキュメント」にその GitHub URL（push 済みの場合）を載せる。

## Phase 8: Issue を更新する（解決内容を追記）

**書き込む内容**: 解決内容（対策・実装計画・TODO）のみを Issue に追記する。背景 / 現象 / 原因は既に記載済みのため、上書きしない。

> [!WARNING]
> `gh issue edit --body-file` は本文の**完全置換**であり追記コマンドではない。**必ず既存本文を取得してから実装計画を末尾に結合した全文**を `--body-file` に渡す。

**Issue 更新前に必ず [`references/issue-update.md`](references/issue-update.md) を読む**（既存本文の取得・検証・結合・更新・検証の手順、参照は GitHub / Figma で開けるもののみ、非 ASCII URL のエンコード規約）。

## Phase 9: 実装に進むか確認する

`AskUserQuestion` で確認する:

```text
このまま実装を開始しますか？
- はい: 実装を開始します
- いいえ: 計画の見直しや別の作業を優先します
```

## Phase 10: 実装する

- **UI Issue** → `Skill` ツールで `anvil:impl-ui` を起動する（args: `<issue番号> --stage implement`）。`impl-ui` はデザイン仕様書・実装設計書に従って UI を実装し、三点突合レビューまで行い、実装ファイル一覧とレビュー結果（差異件数・対応有無・実機キャプチャ有無）を返す。Phase 11 はスキップして Phase 12 へ
- **非 UI Issue** → Issue に記載した実装計画の TODO に沿って順番に実装する。Phase 2〜5 で読んだ仕様書・ルール・参考 PR・既存資産に従い、推測で値を埋めない。実装完了後 Phase 11 へ

## Phase 11: 実装レビューを行う（非 UI Issue のみ） [MANDATORY]

サイレントスキップ禁止。`Skill` ツールで `/forge:review code --auto` を起動する（対象は既定の差分。エンジン軸フラグは `/forge:review` が持たないため付けない）。

- 指摘発生時: 確信のある所見は自動で修正される。確信の無い所見は 1 件ずつ提示されるので採否を判断する
- 指摘なし: そのまま Phase 12 へ

レビュー結果（指摘件数・対応有無）は Phase 12 の commit メッセージ・PR 本文に簡潔に反映する。

---

## Phase 12: 後処理（commit & PR 作成・Closes 保証）

### 12-1: commit

`Skill` ツールで `/anvil:commit` を起動する。自動 commit はしない。

commit メッセージには Issue 参照 `Closes #<N>` を含める。

### 12-2: PR 作成

`Skill` ツールで `/anvil:create-pr <base-branch>` を起動する。

> [!WARNING]
> `/anvil:create-pr` は Issue 番号を引数で受け取る経路がない。PR 本文に `Closes #<N>` を含めるため、本スキルは次を必ず行う:
>
> 1. commit メッセージに `Closes #<N>` を含める（12-1 で担保）
> 2. create-pr の完了後、生成された PR 本文に `Closes #<N>` が含まれているか確認し、無ければ `gh pr edit <PR番号> --body-file` で追記する
> 3. PR 作成に失敗した場合は `/anvil:create-pr` を直接再実行せず、`/anvil:impl-issue #<N>` を再実行する。Phase 0-2 の再開判定が実装済みを検知し、「Phase 12 から再開する」を選べば Phase 1〜11 を再実行せずここへ戻る

PR 本文には以下を含める:

- `Closes #<N>`
- 対応した受け入れ条件のチェックリスト
- レビュー結果の要約（Phase 10/11）

---

## レビュー指摘対応時の必須ルール

- リベースはしない
- PR review comment に対応する場合は **1 review comment / 1 修正 / 1 commit / 1 reply** で進める。複数コメントをまとめて修正・コミットしない。関連が強く不可分な場合でも先にユーザーへ確認する
- 各コミット後、その review comment に「どのコミットで何を直したか」を個別に返信できる状態にする
- ビルドエラー・解析エラー・ユーザーが未解決と言及した問題がある場合は、コミットを作成せず、先に再現確認と修正を行う
