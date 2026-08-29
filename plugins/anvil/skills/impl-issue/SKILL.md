---
name: impl-issue
description: |
  GitHub Issue の実装を準備から完了まで一貫して行う。triage の判定調査結果（仕様書・ルール・類似PR・既存コードの特定）を引き継ぎ、実装計画の策定・Issue への解決内容記載・実装・レビューまで進める。UI Issue の場合は Figma デザイン仕様書・実装設計書の作成、UI 実装、実装レビューまでカバーする。
  `/anvil:triage-issue` がワンショット実装と判定した Issue に対して Skill ツール経由でのみ起動される（ユーザーからの直接起動は不可）。
user-invocable: false
argument-hint: "<issue番号 または URL>"
allowed-tools: Bash(git *), Bash(gh issue view *), Bash(gh issue edit *), Bash(gh pr list *), Bash(gh pr view *), Bash(gh pr diff *), Bash(gh pr edit *), Bash(gh repo view *), Bash(gh api *), Bash(tee *), Bash(python3 *), Bash(curl -s -H *api.figma.com*), AskUserQuestion, Agent, Skill, Read, Write, Edit, Grep, Glob
---

# anvil:impl-issue

GitHub Issue の実装を準備から完了まで一貫して行うオーケストレータ。
UI Issue の場合は Figma デザイン仕様書・実装設計書の作成、UI 実装、実装レビューまでカバーする。

> [!IMPORTANT]
> 本スキルは `user-invocable: false` であり、`/anvil:impl-issue` として直接起動できない。**`/anvil:triage-issue` がワンショット実装と判定した後、Skill ツール経由で起動される**ことが唯一の開始経路。判定調査の結果（仕様書・ルール・類似 PR・既存コードの特定）は triage から引き継ぎ、Phase 2〜5 では**再調査しない**（引き継いだ参照先の精読は行う）。

**このスキルが Issue に書き込む内容**: 解決の内容（対策・実装計画・TODO）のみ。
課題の内容（背景/現象・原因）は `/anvil:create-issue` が作成済みのため、上書きしない。

## Goal

Issue の調査・ブランチ確認・実装計画の Issue 記載・UI の場合はデザイン仕様書・実装・レビューまで、全 Phase を完走すること。`AskUserQuestion` が必要な判断点と、Phase 12 のレビューで確信の持てない所見の採否以外は、ユーザー介入なしに継続する。

## フロー継続

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ `AskUserQuestion` で確認する。

## ワークフロー

全 Phase の一覧。Phase 0 と Phase 13 は anvil 固有の前処理・後処理。Phase 1-12 が impl-issue の本体。

| #  | Phase                                   | 対象          |
| -- | --------------------------------------- | ------------- |
| 0  | 前処理（リポジトリ解決・ブランチ準備）  | 全て          |
| 1  | Issue の内容を把握する                  | 全て          |
| 2  | 仕様書を確認する                        | 全て          |
| 3  | 実装ルールを確認する                    | 全て          |
| 4  | 類似 PR を学習する                      | 全て          |
| 5  | 既存コードを確認する                    | 全て          |
| 6  | Figma デザイン仕様書を作成する          | UI Issue のみ |
| 7  | デザイン仕様書をレビューする            | UI Issue のみ |
| 8  | 実装計画を策定する                      | 全て          |
| 9  | Issue を更新する（解決内容を追記）      | 全て          |
| 10 | 実装に進むか確認する                    | 全て          |
| 11 | UI 実装を行う                           | UI Issue のみ |
| 12 | 実装レビューを行う                      | UI Issue のみ |
| 13 | 後処理（commit & PR 作成・Closes 保証） | 全て          |

---

## Phase 0: 前処理（リポジトリ解決・ブランチ準備）

### 0-1: リポジトリ情報を解決する

`.git_information.yaml` が存在する場合はそこから取得する：

```yaml
# .git_information.yaml
github:
  owner: "<owner>"
  repo: "<repo>"
  default_base_branch: develop # Phase 0-3 のデフォルトとして使用
```

ファイルが存在しない場合は `gh` コマンドで取得する（フォールバック）：

```bash
gh repo view --json nameWithOwner --jq '.nameWithOwner'
```

取得した `<owner>/<repo>` と `<default_base_branch>` を変数として記録し、以降のすべての `--repo` 引数に使用する。

#### 引数が Issue URL の場合のリポジトリ整合チェック [MANDATORY]

本スキルの引数として **Issue URL**（例: `https://github.com/<owner>/<repo>/issues/<N>`）が渡された場合、URL から `<url-owner>/<url-repo>` と `<N>` を抽出する。

- `<url-owner>/<url-repo>` が現在のリポジトリ（上で解決した値）と**一致** → 続行。以降は `<N>` を Issue 番号として扱う
- **不一致** → `AskUserQuestion` で次の 3 択を提示する:
  - **中断（推奨）**: 「対象リポに移動して `/anvil:triage-issue <N>` から再実行してください」と案内し終了
  - **読み取り専用で続行**: `gh issue view --repo <url-owner>/<url-repo>` で Issue 内容のみ取得し、ブランチ作成 / Closes 連動 / PR 作成は現在のリポで行う。**`Closes #<N>` ではなく `Closes <url-owner>/<url-repo>#<N>` を使用する**（Phase 13 にも反映）
  - **中止**: 終了コード非ゼロで停止

Issue 番号のみ（URL ではない）で渡された場合はこのチェックは不要。

### 0-2: triage 引き継ぎを確認する（read-only preflight）[MANDATORY]

**ブランチ操作（0-3）より前に、副作用のない読み取り専用チェックとして実行する。** `user-invocable: false` は直接スラッシュ起動を隠すだけで実行時ゲートにはならないため、経路違反（triage を経由しない起動）を検知する唯一の手段は本チェックである。ここで失敗した場合、ブランチ作成・checkout 等の副作用は一切発生させない。

1. Issue の内容とコメントを取得する：

   ```bash
   gh issue view <issue番号> --repo <owner>/<repo>
   gh issue view <issue番号> --repo <owner>/<repo> --comments
   ```

2. **triage の調査結果を確定する**: Phase 2〜5 の入力となる調査結果（関連仕様書・ルール文書・類似 PR・既存コードの特定結果）を以下の優先順で確定する:
   - 同一セッションで triage を実行した直後 → コンテキスト上の調査結果をそのまま使う
   - コンテキストに無い（セッションを跨いだ再開等）→ 取得したコメントから `<!-- anvil:triage-result:v1:start -->` 〜 `<!-- anvil:triage-result:v1:end -->` のマーカーブロックを探す。複数存在する場合は**最も新しい（コメント一覧の末尾に近い）ブロックのみ**を採用する（手書きコメントや旧スキーマのマーカーなしコメントは無視する）
   - どちらにも無い（マーカーブロックが 1 件も見つからない）→ **自前調査にフォールバックせず停止**し、「`/anvil:triage-issue <N>` を先に実行してください」と案内する（入口一本化の経路違反を検知するため。triage-issue はマーカーをワンショット実装判定の場合のみ付与するため、SDD 判定の Issue はこの分岐で自動的に検知される）

3. **実装再開の判定（PR 作成失敗からの再開検知）**: **現在のブランチ名に Issue 番号が含まれる場合のみ**判定する。別ブランチの探索・リモートブランチの checkout は行わない（狭い happy path のみ扱う。それ以外は人間に対象ブランチへの checkout を促す）。

   現在のブランチ名に Issue 番号が含まれ、かつ以下の**すべて**に該当する場合、Phase 2〜12 は完了済みで PR 作成のみが未達と推定できる:
   - 現在のブランチがベースブランチに対して commit が進んでいる
   - Issue 本文に `impl-issue` が Phase 9 で書き込む解決内容セクションが既に存在する

   該当する場合、`AskUserQuestion` で確認する:

   ```
   Issue #<N> は実装・commit まで完了しているようです（PR 作成のみ未達と推定）。
   - Phase 13（commit 差分確認・PR 作成）から再開する（推奨）
   - 最初から通常のフロー（Phase 1〜）を実行し直す
   ```

   「Phase 13 から再開する」を選んだ場合、Phase 1〜12 をすべてスキップし Phase 13 へ直接進む（現在のブランチが対象のため checkout 不要）。

   現在のブランチ名に Issue 番号が含まれない場合は再開判定をせず、通常のフロー（0-3 のブランチ確認）へ進む。対象 Issue のブランチで作業したい場合は、ユーザーが手動で `git checkout <branch-name>` してから本スキルを再実行する。

### 0-3: ブランチを確認・作成する

0-2 で「Phase 13 から再開する」を選んだ場合は本ステップをスキップする（対象ブランチは既に存在し checkout 済みのはずのため、現在のブランチをそのまま使う）。

1. 現在のブランチを確認する：

   ```bash
   git branch --show-current
   ```

2. **Issue 番号がブランチ名に含まれているかを判定**する:
   - 含まれている（例: `fix/12-xxx`、`feature/12-xxx`）→ 対応ブランチと判断し、そのまま Phase 1 へ
   - 含まれていない → `AskUserQuestion` で確認する:

     ```
     現在 `<current-branch>` にいます。Issue #N 用の作業ブランチを作成しますか？
     - はい: ブランチを作成します
     - いいえ: 現在のブランチで作業を続けます
     ```

3. **ブランチを作成する場合**:

   a. ベースブランチを `AskUserQuestion` で確認する（デフォルト: Phase 0-1 で取得した `default_base_branch`、未取得の場合は `develop`）。

   b. ベースブランチの最新状態を取得する。**ベースブランチをローカルに checkout しない**（git worktree でベースブランチが既に別 worktree に checkout 済みの環境でも失敗しないため）：

   ```bash
   git fetch origin <base-branch>
   ```

   - `fetch` が失敗 → `AskUserQuestion` で対応確認（中止推奨）

   c. ブランチ名を決定する。

   **判定順序**:

   1. **Issue のラベルから判定**（最優先・決定的）。リポジトリで使われているラベル命名は揺れるので、以下の語句を**部分一致・大文字小文字無視**で照合する。複数一致した場合は表の上位を優先：

      | プレフィックス | 一致するラベル語句（部分一致・case-insensitive）         |
      | -------------- | -------------------------------------------------------- |
      | `fix/`         | `bug`, `fix`, `defect`, `修正`, `不具合`                 |
      | `feature/`     | `feature`, `enhancement`, `feat`, `新機能`, `機能追加`   |
      | `refactor/`    | `refactor`, `refactoring`, `cleanup`, `リファクタ`       |
      | `docs/`        | `doc`, `docs`, `documentation`, `文書`                   |
      | `chore/`       | `chore`, `build`, `ci`, `test`, `dependencies`, `その他` |

   2. **どのラベルにも該当しない場合は `AskUserQuestion`** でユーザーに選択させる：

      ```
      Issue のラベルからブランチ種別が判定できませんでした。プレフィックスを選択してください:
      - fix/ : バグ修正
      - feature/ : 新機能
      - refactor/ : リファクタ
      - docs/ : 文書
      - chore/ : その他
      ```

   3. **タイトルや本文から自動推測しない**（非決定的になるため）。

   形式: `<prefix>/<issue-number>-<slug>`（slug は Issue タイトルを kebab-case 化、英数字以外は `-` に置換、連続 `-` は 1 つに正規化、末尾 `-` 除去）

   d. `fetch` した `origin/<base-branch>` を起点に新規ブランチを作成する。**`--no-track` 必須**: 付けないと upstream が `origin/<base-branch>` に設定される。`push.default=simple`（Git のデフォルト）では素の `git push` はブランチ名不一致でエラー終了するだけだが、`push.default=upstream` 等の設定ではそのままベースブランチへ push されてしまうため、設定に依存せず安全にするには `--no-track` が必須：

   ```bash
   git checkout -b <branch-name> origin/<base-branch> --no-track
   ```

---

## Phase 1: Issue の内容を把握する

triage 引き継ぎの確定・実装再開判定は Phase 0-2 で完了済み（本 Phase では再実行しない）。

1. タイトル・本文・ラベルから実装内容・タスク種別を把握する（内容は Phase 0-2 で取得済み）
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

   - 「Figma URL や画面名が**参考として**書かれているだけ」のデータ / API Issue を UI Issue と誤判定しないこと。

4. **UI Issue と判定された場合のみ、Figma PAT 疎通確認**を実施する（後方での手戻り防止）：

   ```bash
   curl -s -H "X-Figma-Token: $FIGMA_PAT" "https://api.figma.com/v1/me"
   ```

   - 成功 → 続行
   - 失敗 → サイレントスキップしない。`AskUserQuestion` で以下の 3 択を提示する:
     - **再指定**: PAT を設定し直して再実行する手順を案内し、ユーザーが整え次第再試行
     - **非 UI Issue へ切替**: 種別を非 UI Issue に変更し、Figma 関連 Phase はそもそも実行しない
     - **中断**: 非ゼロ終了コードで処理を停止し、stderr に未充足項目（FIGMA_PAT）と充足手順を出力する

## Phase 2: 仕様書を確認する

関連仕様書の**特定**は triage の判定調査で完了している（Phase 0-2 で確定した調査結果を使う）。`/forge:query-db-specs` による再検索は行わない。

引き継がれた各仕様書参照は `kind: local_path` または `kind: github_url` を持つ（外部リポジトリ・symlink 経由の仕様書は triage 側で `local_path` を保持できず `github_url` のみになる。triage-issue `references/phase-02-spec-investigation.md` 参照）。**種別に応じて取得方法を分岐する**:

- `kind: local_path` → Read tool でそのまま精読する（同一セッションで既に読了済みのものは再読不要）
- `kind: github_url` → Read tool では開けない。記録されている URL は**外部リポジトリ**（symlink 実体）のものであり、現在の `<owner>/<repo>`（Phase 0-1 で解決した値）とは別リポジトリである。URL 自体から `<url-owner>` / `<url-repo>` / `<ref>`（ブランチ・タグ・コミット。無ければ `HEAD`） / `<path>` をパースし、以下で取得する:

  ```bash
  gh api "repos/<url-owner>/<url-repo>/contents/<path>?ref=<ref>"
  ```

  レスポンスの `content`（base64）をデコードして精読する。取得に失敗した場合（別 API 形式のリポジトリ・private リポジトリで権限不足等）は黙って読み飛ばさず、`AskUserQuestion` でユーザーに内容確認の方法を確認する
- **UI Issue の場合の追加記録**: 画面設計書・確認/調整事項ドキュメントが存在する場合、必ず読み、以下を記録する（Phase 6 で `/anvil:prepare-figma` に渡す）:
  - 画面設計書ファイルパス / 画面設計書の GitHub URL（Issue 記載用）
  - 確認・調整事項ファイルパス（存在する場合）
  - Figma URL（画面設計書に記載されているもの）
  - 画面 ID・画面名
- 精読中に未特定の関連仕様書が判明した場合のみ、追加で読み込む（全体の再検索はしない）

## Phase 3: 実装ルールを確認する

ルール文書の**特定**は triage の判定調査で完了している。`/forge:query-db-rules` による再検索は行わない。

- 引き継がれたルール文書を**すべて**実際に Read tool で読み込む
- CLAUDE.md に記載されているプロジェクト構造・アーキテクチャの説明を確認する

## Phase 4: 類似実装済み PR を学習する

類似 PR の**特定**は triage の判定調査で完了している。`gh pr list --search` による再探索は行わない。引き継がれた PR 番号それぞれについて `gh pr view` / `gh pr diff --name-only` で内容を確認し、以下の観点で実装パターンを学習する:

- どのレイヤー・どのディレクトリのファイルが変更されているか
- ドメインモデル・値オブジェクト / リポジトリ・データソースの実装パターン
- 依存性注入・コンポジションの設定方法、状態管理の実装スタイル
- テスト対象範囲とテストの書き方

**原則**: 今回の実装は学習した PR と**同じスコープ・同じ実装方法**を採用する。独自パターンを混入させない。乖離する必要がある場合は、設計書に理由を明記する。

## Phase 5: 既存コードを確認する

再利用可能な既存コードの**特定**は triage の判定調査で完了している。新規の全体探索は行わない。

- 引き継がれたコードパスを Read で精読し、再利用方針を把握する
- **新規作成回避の原則・検証チェックリスト・共通コンポーネント採用判断（[`references/phase-05-reuse-principles.md`](references/phase-05-reuse-principles.md)）を Phase 5〜8 で適用する**。チェックリストに未確認項目が残る場合のみ補完調査する（全体の再探索はしない）

## Phase 6: Figma デザイン仕様書を作成する（UI Issue のみ）

**条件**: Phase 1 で UI Issue と判定された場合のみ実行。それ以外はスキップして Phase 8 へ。

### Phase 6 開始時の依存ツール確認

UI Issue と判定された＝ Figma からの取り込みが必要、と確定した時点で、`/anvil:prepare-figma` を呼ぶ前に必要ツールの有無をオーケストレータ側で確認する。
**AI は依存ツールを勝手にインストールしない**。

確認対象は `/anvil:prepare-figma` の前提条件セクションを参照する。

不足している場合は `AskUserQuestion` で次の選択肢を提示する。

| `id`               | `label`（ユーザーに見せる）              | AI の次アクション                                          |
| ------------------ | ---------------------------------------- | ---------------------------------------------------------- |
| `install_by_ai`    | AI が必要ツールをインストールする        | インストール実行 → 完了後に Phase 6 続行                   |
| `install_manually` | 手動でインストールするので待機           | 中断・ユーザー作業完了の合図を待つ                         |
| `skip_preview`     | プレビュー生成をスキップし仕様書のみ作成 | `/anvil:prepare-figma` に `skip_preview=true` を渡して続行 |
| `abort`            | 中断                                     | impl-issue 自体を終了                                      |

### `/anvil:prepare-figma` 呼び出し

`/anvil:prepare-figma` スキルを **subagent（Agent ツール、subagent_type: general-purpose）** で実行する。
メインコンテキストで Figma MCP は呼ばない（コンテキスト効率のため）。

Phase 2 で収集した画面設計書情報を渡す：

```
Agent tool で /anvil:prepare-figma を呼び出す:
- 画面 ID: Phase 2 で特定した画面 ID
- 画面設計書パス: Phase 2 で読み込んだ画面設計書のファイルパス
- 確認・調整事項パス: Phase 2 で読み込んだ確認・調整事項のファイルパス（存在する場合）
- Figma URL: 画面設計書に記載されていた Figma URL
```

`/anvil:prepare-figma` は以下を実行する（詳細は当該 SKILL を参照）:

1. 画面設計書を Read で読み込み
2. nodeId 発見・検証 + Figma URL 確定
3. MCP で詳細取得 + 必要に応じ PAT で精度補完
4. デザイン仕様書作成（Figma URL 必須記載、レイアウト定義を含む）
5. レイアウト定義から AI 理解プレビュー画像を自動生成
6. **AI 自己検証ループ**: Figma SS と AI プレビュー画像を Read で読み込み、構造誤りが無くなるまでレイアウト定義修正 → 再レンダリングを繰り返す
7. 三点突合（デザイン仕様書 vs 画面設計書 vs Figma）でテキスト整合性も確認

**出力先**: `/anvil:prepare-figma` が `specs/design/{id}/` に出力する（1 画面 = 1 ディレクトリ）。後続 Phase 8 の実装設計書もここに同居させる。

## Phase 7: デザイン仕様書をレビューする（UI Issue のみ）

**必須チェックポイント**: Phase 8 に進む前にユーザーの承認を得る。

レビューは **「視覚比較」を中心に行う** ことで、AI の構造理解の誤りを暴く。

1. 生成されたデザイン仕様書を Read で読み込み、視覚比較セクションの 2 枚（Figma SS と AI プレビュー）を確認する
2. ユーザーに提示し、`AskUserQuestion` で確認する：
   > デザイン仕様書を確認してください。
   > **視覚比較セクションの 2 枚（Figma と AI プレビュー）を必ず見比べてください**。
   >
   > - **承認**: 構造が一致している。Phase 8 へ進みます
   > - **修正要求**: 差異があるのでレイアウト定義を修正して再レンダリングします
   > - **中断**: ここで中断し、後日再開します

ユーザーが修正要求した場合、`/anvil:prepare-figma` を再呼び出ししてレイアウト定義を修正・再レンダリングする。

## Phase 8: 実装計画を策定する

Phase 1〜5（UI Issue の場合は Phase 1〜7）の調査結果をもとに以下を決定する：

1. **実装スコープ**: どのレイヤーに何を実装するか（具体的なクラス名・ファイルパスまで）
2. **実装順序**: 依存関係を考慮した実装の順番
3. **スコープ外**: 今回実装しないもの（理由・担当）。異常系・防御的実装をスコープに含めるか迷う場合は `/forge:query-forge-rules` で「比例性」「過剰設計」等を検索して判断基準を確認する
4. **参考 PR**: 実装方法の根拠となる PR

Phase 8 で作成する成果物は次の 2 つ。**用途・出力先・参照テンプレートが異なる**ので混同しないこと。

| 成果物         | 用途                       | 出力先                                                                                                                                                                                                                                                  | 使うテンプレート / ルール                                                                                                             |
| -------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **実装設計書** | 「どう作るか」(How) を決定 | UI Issue: Phase 6 で `/anvil:prepare-figma` が作成した `specs/design/{id}/` ディレクトリ（デザイン仕様書と同じ場所） / 非 UI Issue: プロジェクト規約に従い、設計書置き場（無ければ Phase 0-1 のリポルート直下 `specs/design/<feature-or-issue-slug>/`） | [`references/phase-08-impl-design.md`](references/phase-08-impl-design.md) の「実装設計書テンプレート」                               |
| **Issue 本文** | 実装計画を Issue に記載    | GitHub Issue（Phase 9 で `gh` で更新）                                                                                                                                                                                                                  | [`assets/TEMPLATE.md`](assets/TEMPLATE.md)（更新手順は [`references/phase-09-issue-update.md`](references/phase-09-issue-update.md)） |

**実装設計書**は UI Issue の場合のみ作成する。既存コンポーネント対応表、**Typography 対応表**、アクション一覧、状態管理、API 連携等を含む。
**Typography 対応表**は [`references/phase-11-typography-mapping.md`](references/phase-11-typography-mapping.md) に従い、デザイン仕様書の全テキストノードを列挙すること。

**実装設計書 作成前に必ず [`references/phase-08-impl-design.md`](references/phase-08-impl-design.md) を読む。**

## Phase 9: Issue を更新する（解決内容を追記）

**書き込む内容**: 解決内容（対策・実装計画・TODO）のみを Issue に追記する。
背景 / 現象・原因はすでに記載済みのため、上書きしない。

> [!WARNING]
> `gh issue edit --body-file` は本文の**完全置換**であり追記コマンドではない。実装計画のみを書いたファイルを
> そのまま渡すと既存の背景・現象・原因が消える。**必ず既存本文を取得してから実装計画を末尾に結合した全文**を
> `--body-file` に渡す（手順は `references/phase-09-issue-update.md` 参照）。

実装計画を Issue に記載する。参照は GitHub / Figma で開けるもののみ記載する。

**Issue 更新前に必ず [`references/phase-09-issue-update.md`](references/phase-09-issue-update.md) を読む。**

## Phase 10: 実装に進むか確認する

`AskUserQuestion` ツールで以下を確認する：

> このまま実装を開始しますか？
>
> - **はい**: 実装を開始します
> - **いいえ**: 計画の見直しや別の作業を優先します

「はい」の場合:

- **UI Issue** → Phase 11 へ進む（Phase 11 → Phase 12 → Phase 13）
- **非 UI Issue** → Issue に記載した実装計画の TODO に沿って順番に実装を進める。**実装完了後は Phase 12 → Phase 13 へ進む**

## Phase 11: UI 実装を行う（UI Issue のみ）

**条件**: UI Issue の場合のみ実行。

> [!IMPORTANT]
> **デザイン仕様書 = 構造の正 / Figma = ビジュアル詳細の正**。
> 仕様書の値（順序・サイズ・色・padding・font・条件分岐）をそのままコードに転記する。

**実装前に必ず [`references/phase-11-ui-implementation.md`](references/phase-11-ui-implementation.md) を読む。**
**Typography 照合前に必ず [`references/phase-11-typography-mapping.md`](references/phase-11-typography-mapping.md) を読む。**

実装手順:

1. デザイン仕様書と実装設計書を Read
2. **Typography 対応表を作成**（全テキストノード → トークン。実装設計書 or コンポーネント先頭コメント）
3. **アクション一覧・状態表を読み、タップ挙動を同時実装する計画を立てる**
4. 実装コードを書く前に、対応する仕様書ノード + Typography 行をコードコメントへ転記
5. 既存コンポーネント流用時は Grep で値差分照合（font / color / size / padding）
6. **共用コンポーネントを 1 画面の typography に書き換えない**（画面専用コンポーネントを作る）
7. 実装完了後、下記セルフチェックを通す

### 実装後セルフチェック

[`references/phase-11-ui-implementation.md` の「実装後セルフチェック」](references/phase-11-ui-implementation.md#実装後セルフチェック)を実施する。
不合格があれば修正してから Phase 12 へ。妥協する場合は `AskUserQuestion` で確認。

## Phase 12: 実装レビューを行う

実装内容を Issue 種別で分岐してレビューする。サイレントスキップ禁止 [MANDATORY]。

### UI Issue の場合

実装後に三点突合（Figma デザイン仕様書 + 実装設計書 + 実装コード）を行い、正しい実装になっているか確認する。

**レビュー前に必ず [`references/phase-12-ui-review.md`](references/phase-12-ui-review.md) を読む。**

レビュー手順:

1. デザイン仕様書と実装設計書を読み込む
2. Figma MCP でデザインを確認する（`get_design_context` → `get_screenshot` → `get_metadata`）
3. **実装後キャプチャ**: 最新コード反映後の実装画面を、プロジェクトのプラットフォームに応じた手段（Emulator / Simulator / Web ブラウザ / Desktop アプリ等）で実機キャプチャする
   - これは AI プレビュー生成ではない。Phase 11 の最終実装を実アプリ上で確認するためのキャプチャ。
4. **三点突合**: Figma SS・実装キャプチャ・コード/設計書を突き合わせ、差異を洗い出す
5. 類似画面との実装パターン比較を行う
6. 実装ルール確認チェックリストを確認する（デザイントークン、アセット参照、i18n 等）
7. 差異があれば修正し、再度突合する
8. 完了後:
   - プロジェクトのコード生成コマンドを実行する（必要な場合）
   - 新規コンポーネント作成時はカタログへの追加 + コンポーネント一覧文書の更新

### 非 UI Issue の場合

`Skill` ツールで `/forge:review code --auto` を委譲実行する（対象は既定の `--diff`。エンジン軸フラグは `/forge:review` が持たないため付けない）。

```
Skill ツールで /forge:review code --auto を呼び出す
- 対象: 現ブランチの未 commit 差分
- 指摘発生時: 確信のある所見は自動で修正される。確信の無い所見は 1 件ずつ提示されるので採否を判断する
- 指摘なし: そのまま Phase 13 へ進む
```

レビュー結果（指摘件数・対応有無）は Phase 13 の commit メッセージ・PR 本文に簡潔に反映する。

---

## Phase 13: 後処理（commit & PR 作成・Closes 保証）

### 13-1: commit

`/anvil:commit` に委譲する。自動 commit はしない。

commit メッセージには Issue 参照を含める。**Issue が現在のリポと別リポ**（Phase 0-1 の整合チェック参照）なら `Closes <url-owner>/<url-repo>#<N>` 形式、同一リポなら `Closes #<N>` 形式：

```
<type>: <summary>

Closes #<issue-number>           # 同一リポの場合
# または
Closes <owner>/<repo>#<issue-number>  # 別リポの場合
```

### 13-2: PR 作成

`/anvil:create-pr <base-branch>` に委譲する。

> ⚠️ **PR 本文の Closes 保証**
>
> `/anvil:create-pr` の `argument-hint` は `[base-branch]` のみで、Issue 番号を引数で受け取る経路がない（PR 本文は commit 差分・テンプレートから生成される）。
> しかし PR 本文には Issue を自動クローズするため `Closes #<issue-number>` を含める必要がある。
>
> したがって impl-issue は以下を必ず行う:
>
> 1. **commit メッセージに `Closes #<issue-number>` を含めて push する**（13-1 で担保）。これにより create-pr のテンプレート生成でも本文に反映されやすくなる
> 2. create-pr に委譲した後、**生成された PR 本文に `Closes #<issue-number>` が含まれているか確認**する。含まれていない場合は `gh pr edit <PR番号> --body-file` で本文を追記する
> 3. PR 作成失敗時は `/anvil:create-pr` を直接再実行**せず**、`/anvil:triage-issue #<issue-number>` から再開する（impl-issue は直接起動できないため）。再起動された impl-issue は Phase 0-2 の「実装再開の判定」がブランチの commit 状況と Issue の解決内容セクションから実装済みを検知し、「Phase 13 から再開する」を選べば Phase 1〜12 を再実行せず直接 Phase 13 に進む（triage 側も Phase 1〜8 のフル再調査を経由するため、この検知がないと不要な再調査・再計画が発生する）
>
> 将来的に `/anvil:create-pr` の入力契約に `--issue-number` 引数を追加し、impl-issue 側で `Closes #N` 付き本文を組み立てて渡す運用に移行する。

PR 本文には以下を含める:

- `Closes #<issue-number>`（自動クローズ用、上記の手順で必ず確認・追記する）
- 対応した受け入れ条件のチェックリスト

---

## レビュー指摘対応時の必須ルール

- リベースができません。
- レビュー指摘の修正は 1 つずつコミットしないとリプライできません。
- PR review comment に対応する場合は、原則として **1 review comment / 1 修正 / 1 commit / 1 reply** で進める。
- 複数コメントをまとめて修正・コミットしない。関連が強く不可分な場合でも、先にユーザーへ確認する。
- 各コミット後、その review comment に対して「どのコミットで何を直したか」を個別に返信できる状態にする。
- ビルドエラー・解析エラー・ユーザーが未解決と言及した問題がある場合は、コミットを作成せず、先に再現確認と修正を行う。

## 参照

> Phase 追加・改番時はワークフローのチェックリスト・本文見出し・references ファイル名・本参照一覧を同時に更新する

- [Issue 更新テンプレート](assets/TEMPLATE.md)
- [Phase 5/8: 既存資産の再利用原則](references/phase-05-reuse-principles.md)
- [Phase 8: 実装設計書 作成ルール](references/phase-08-impl-design.md)
- [Phase 9: Issue 更新ルール](references/phase-09-issue-update.md)
- [Phase 11: UI 実装ルール](references/phase-11-ui-implementation.md)
- [Phase 11: Typography 照合ルール](references/phase-11-typography-mapping.md)
- [Phase 12: UI 実装レビュールール](references/phase-12-ui-review.md)
