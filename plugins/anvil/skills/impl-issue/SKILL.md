---
name: impl-issue
description: GitHub Issue の実装を準備から完了まで一貫して行う。ブランチ確認・作成から始まり、仕様書・ルール文書を調査し、類似PRから実装パターンを学習、解決内容（対策・実装計画）を Issue に記載する。UI Issue の場合は Figma デザイン仕様書・実装設計書の作成、UI 実装、実装レビューまでカバーする。トリガー：「この Issue を実装したい」「Issue XXX の着手前準備」「実装計画を立てて」「XXX を実装する Issue の準備をして」
user-invocable: true
argument-hint: "<issue番号 または URL>"
allowed-tools: Bash(git *), Bash(gh issue view *), Bash(gh issue edit *), Bash(gh pr list *), Bash(gh pr view *), Bash(gh pr diff *), Bash(gh pr edit *), Bash(gh repo view *), Bash(tee *), Bash(python3 *), Bash(curl -s -H *api.figma.com*), AskUserQuestion, Agent, Skill, Read
---

# /anvil:impl-issue

GitHub Issue の実装を準備から完了まで一貫して行うオーケストレータ。
UI Issue の場合は Figma デザイン仕様書・実装設計書の作成、UI 実装、実装レビューまでカバーする。

**このスキルが Issue に書き込む内容**: 解決の内容（対策・実装計画・TODO）のみ。
課題の内容（背景/現象・原因）は `/anvil:create-issue` が作成済みのため、上書きしない。

## ワークフロー

以下のチェックリストをコピーして進捗を追跡する：

```
進捗:
- [ ] Phase 0: リポジトリ情報を解決する
- [ ] Phase 1: ブランチを確認・作成する
- [ ] Phase 2: Issue を確認する
- [ ] Phase 3: 仕様書を調査する
- [ ] Phase 4: 実装ルールを調査する
- [ ] Phase 5: 類似PRを調査する（ユーザにAskUserQuestionで実行するか確認）
- [ ] Phase 6: 既存コードを調査する
- [ ] Phase 7: Figma デザイン仕様書を作成する（UI Issue のみ）
- [ ] Phase 8: デザイン仕様書をレビューする（UI Issue のみ）
- [ ] Phase 9: 実装計画を策定する
- [ ] Phase 10: Issue を更新する（解決内容を追記）
- [ ] Phase 11: 実装に進むか確認する
- [ ] Phase 12: UI 実装を行う（UI Issue のみ）
- [ ] Phase 13: 実装レビューを行う（UI Issue のみ）
- [ ] Phase 14: commit & PR を作成する
```

### Phase 0: リポジトリ情報を解決する

`.git_information.yaml` が存在する場合はそこから取得する：

```yaml
# .git_information.yaml
github:
  owner: "<owner>"
  repo: "<repo>"
  default_base_branch: develop # Phase 1 のデフォルトとして使用
```

ファイルが存在しない場合は `gh` コマンドで取得する（フォールバック）：

```bash
gh repo view --json nameWithOwner --jq '.nameWithOwner'
```

取得した `<owner>/<repo>` と `<default_base_branch>` を変数として記録し、以降のすべての `--repo` 引数に使用する。

### Phase 1: ブランチを確認・作成する

1. 現在のブランチを確認する：

   ```bash
   git branch --show-current
   ```

2. **Issue 番号がブランチ名に含まれているかを判定**する:
   - 含まれている（例: `fix/12-xxx`、`feature/12-xxx`）→ 対応ブランチと判断し、そのまま Phase 2 へ
   - 含まれていない → AskUserQuestion で確認する:

     ```
     現在 `<current-branch>` にいます。Issue #N 用の作業ブランチを作成しますか？
     - はい: ブランチを作成します
     - いいえ: 現在のブランチで作業を続けます
     ```

3. **ブランチを作成する場合**:

   a. ベースブランチを AskUserQuestion で確認する（デフォルト: Phase 0 で取得した `default_base_branch`、未取得の場合は `develop`）:

   ```
   ベースブランチを入力してください（デフォルト: <default_base_branch>）:
   他のブランチが必要な場合は入力してください
   ```

   b. ベースブランチを最新化してブランチを作成する：

   ```bash
   git fetch origin <base-branch>
   git checkout <base-branch>
   git pull --ff-only origin <base-branch>
   ```

   - `pull --ff-only` が失敗 → AskUserQuestion で対応確認（中止推奨）

   c. ブランチ名を決定する:

   | Issue 内容 | プレフィックス |
   | ---------- | -------------- |
   | バグ修正   | `fix/`         |
   | 新機能     | `feature/`     |
   | リファクタ | `refactor/`    |
   | 文書       | `docs/`        |
   | その他     | `chore/`       |

   形式: `<prefix>/<issue-number>-<slug>`（slug は Issue タイトルを kebab-case 化）

   ```bash
   git checkout -b <branch-name>
   ```

### Phase 2: Issue を確認する

1. ユーザーから Issue 番号または URL を受け取る
2. Issue の現在の内容を取得する：

   ```bash
   gh issue view <issue番号> --repo <owner>/<repo>
   ```

3. コメントも確認する（既存の調査結果がある場合）：

   ```bash
   gh issue view <issue番号> --repo <owner>/<repo> --comments
   ```

4. タイトル・本文・ラベルから実装内容・タスク種別を把握する
5. 既存の TODO や計画が記載されていれば確認する
6. **UI Issue か判定する**: 以下のいずれかに該当すれば UI Issue
   - Issue に Figma URL（`figma.com/design/`）が含まれる
   - Issue に画面設計書への参照がある
   - ラベルに `UI` や `画面` が含まれる
   - タイトル・本文に画面名や UI 要素の記載がある
7. **UI Issue の場合、PAT 疎通確認**（後方での手戻り防止）：

   ```bash
   curl -s -H "X-Figma-Token: $FIGMA_PAT" "https://api.figma.com/v1/me"
   ```

   - 成功 → 続行
   - 失敗 → サイレントスキップしない。`AskUserQuestion` で以下の 3 択を提示する:
     - **再指定**: PAT を設定し直して再実行する手順を案内し、ユーザーが整え次第再試行
     - **非 UI Issue へ切替**: 種別を非 UI Issue に変更し、Figma 関連 Phase はそもそも実行しない
     - **中断**: 非ゼロ終了コードで処理を停止し、stderr に未充足項目（FIGMA_PAT）と充足手順を出力する

### Phase 3: 仕様書を調査する

`/doc-advisor:query-specs` を使い、Issue のタイトルと本文をキーワードとして関連仕様書を特定する。

**詳細は [references/phase-03-spec-investigation.md](references/phase-03-spec-investigation.md) を参照。**

### Phase 4: 実装ルールを調査する

`/doc-advisor:query-rules` を使い、タスクに関連するルール文書を特定する。

**必須ルール**:

- 特定したルール文書は**すべて**実際に Read tool で読み込む
- CLAUDE.md に記載されているプロジェクト構造・アーキテクチャの説明を確認する
- `/doc-advisor:query-rules` で "architecture" / "coding" / "layer" 等をクエリして重要文書を特定する

### Phase 5: 類似実装済みPRを調査する

- ユーザにAskUserQuestionで実行するか確認

今回の実装と同じスコープのマージ済みPRを3件以上探し、実装パターンを学習する。

**詳細は [references/phase-05-pr-investigation.md](references/phase-05-pr-investigation.md) を参照。**

### Phase 6: 既存コードを調査する

実装に再利用できる既存クラス・コンポーネントを特定する。

**詳細は [references/phase-06-code-investigation.md](references/phase-06-code-investigation.md) を参照。**

### Phase 7: Figma デザイン仕様書を作成する（UI Issue のみ）

**条件**: Phase 2 で UI Issue と判定された場合のみ実行。それ以外はスキップして Phase 9 へ。

`/anvil:prepare-figma` スキルを **subagent（Agent tool）** で実行する。
メインコンテキストで Figma MCP は呼ばない（コンテキスト効率のため）。

Phase 3 で収集した画面設計書情報を渡す：

```
Agent tool で `/anvil:prepare-figma` を呼び出す:
- 画面 ID: Phase 3 で特定した画面 ID
- 画面設計書パス: Phase 3 で読み込んだ画面設計書のファイルパス
- 確認・調整事項パス: Phase 3 で読み込んだ確認・調整事項のファイルパス（存在する場合）
- Figma URL: 画面設計書に記載されていた Figma URL
```

デザイン仕様書の出力先は `/doc-advisor:query-specs` で確認した `design/` ディレクトリを使用する。

### Phase 8: デザイン仕様書をレビューする（UI Issue のみ）

**必須チェックポイント**: Phase 9 に進む前にユーザーの承認を得る。

1. 生成されたデザイン仕様書を Read で読み込む
2. ユーザーに提示し、`AskUserQuestion` で確認する：
   > デザイン仕様書を確認してください。
   >
   > - **承認**: Phase 9 へ進みます
   > - **修正要求**: `/anvil:prepare-figma` を再実行 or 直接修正します
   > - **中断**: ここで中断し、後日再開します

### Phase 9: 実装計画を策定する

Phase 2〜6（UI Issue の場合は Phase 2〜8）の調査結果をもとに以下を決定する：

1. **実装スコープ**: どのレイヤーに何を実装するか（具体的なクラス名・ファイルパスまで）
2. **実装順序**: 依存関係を考慮した実装の順番
3. **スコープ外**: 今回実装しないもの（理由・担当）
4. **参考PR**: 実装方法の根拠となるPR

**UI Issue の場合**: デザイン仕様書 + Phase 3〜6 の全調査結果を踏まえて**実装設計書**も作成する。
実装設計書は「どう作るか」を決定する文書（既存コンポーネント対応表、デザイントークン、状態管理、API連携等）。
出力先: `/doc-advisor:query-specs` で確認した `design/` ディレクトリ。

**実装設計書作成前に必ず [references/phase-09-impl-design.md](references/phase-09-impl-design.md) を読み込む。**

スキルディレクトリに `assets/TEMPLATE.md` が存在する場合はそれをベースに計画を作成する。

### Phase 10: Issue を更新する（解決内容を追記）

**書き込む内容**: 解決内容（対策・実装計画・TODO）のみを Issue に追記する。
背景/現象・原因はすでに記載済みのため、上書きしない。

**詳細は [references/phase-10-issue-update.md](references/phase-10-issue-update.md) を参照。**

### Phase 11: 実装に進むか確認する

`AskUserQuestion` ツールで以下を確認する：

> このまま実装を開始しますか？
>
> - **はい**: 実装を開始します
> - **いいえ**: 計画の見直しや別の作業を優先します

「はい」の場合:

- **UI Issue** → Phase 12 へ進む（Phase 12 → Phase 13 → Phase 14）
- **非 UI Issue** → Issue に記載した実装計画の TODO に沿って順番に実装を進める。**実装完了後は Phase 14 へ進む**

### Phase 12: UI 実装を行う（UI Issue のみ）

**条件**: UI Issue の場合のみ実行。非 UI Issue はスキップ。

実装設計書に基づいて UI を実装する。

**実装前に必ず [references/phase-12-ui-implementation.md](references/phase-12-ui-implementation.md) を読み込む。**

### Phase 13: 実装レビューを行う（UI Issue のみ）

**条件**: UI Issue の場合のみ実行。非 UI Issue はスキップ。

実装後に三点突合を行い、正しい実装になっているか確認する。

**レビュー前に必ず [references/phase-13-ui-review.md](references/phase-13-ui-review.md) を読み込む。**

### Phase 14: commit & PR を作成する

**commit**: `/anvil:commit` に委譲する。自動 commit はしない。

commit メッセージには Issue 参照を含める：

```
<type>: <summary>

Closes #<issue-number>
```

**PR 作成**: `/anvil:create-pr <base-branch>` に委譲する。

> ⚠️ **PR 本文の Closes 保証**
>
> `/anvil:create-pr` の `argument-hint` は `[base-branch]` のみで、Issue 番号を引数で受け取る経路がない（PR 本文は commit 差分・テンプレートから生成される）。
> しかし PR 本文には Issue を自動クローズするため `Closes #<issue-number>` を含める必要がある。
>
> したがって impl-issue は以下を必ず行う:
>
> 1. **commit メッセージに `Closes #<issue-number>` を含めて push する**（上記 commit ステップで担保）。これにより create-pr のテンプレート生成でも本文に反映されやすくなる
> 2. create-pr に委譲した後、**生成された PR 本文に `Closes #<issue-number>` が含まれているか確認**する。含まれていない場合は `gh pr edit <PR番号> --body-file` で本文を追記する
> 3. PR 作成失敗時は `/anvil:create-pr` を直接再実行**せず**、`/anvil:impl-issue #<issue-number>` から再開する（Issue 番号引き継ぎ経路を保つため）
>
> 将来的に `/anvil:create-pr` の入力契約に `--issue-number` 引数を追加し、impl-issue 側で `Closes #N` 付き本文を組み立てて渡す運用に移行する。

PR 本文には以下を含める:

- `Closes #<issue-number>`（自動クローズ用、上記の手順で必ず確認・追記する）
- 対応した受け入れ条件のチェックリスト

## 参照

> Phase 追加・改番時はワークフローのチェックリスト・本文見出し・references ファイル名・本参照一覧を同時に更新する

- [Phase 3: 仕様書調査ルール](references/phase-03-spec-investigation.md)
- [Phase 5: 類似PR調査ルール](references/phase-05-pr-investigation.md)
- [Phase 6: 既存コード調査ルール](references/phase-06-code-investigation.md)
- [Phase 9: 実装設計書 作成ルール](references/phase-09-impl-design.md)
- [Phase 10: Issue 更新ルール](references/phase-10-issue-update.md)
- [Phase 12: UI 実装ルール](references/phase-12-ui-implementation.md)
- [Phase 13: UI 実装レビュールール](references/phase-13-ui-review.md)
- [Issue 更新テンプレート](assets/TEMPLATE.md)
