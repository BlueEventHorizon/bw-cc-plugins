---
name: impl-issue
description: GitHub Issue の実装を準備から完了まで一貫して行う。ブランチ確認・作成から始まり、仕様書・ルール文書を調査し、類似PRから実装パターンを学習、解決内容（対策・実装計画）を Issue に記載する。UI Issue の場合は Figma デザイン仕様書・実装設計書の作成、UI 実装、実装レビューまでカバーする。トリガー：「この Issue を実装したい」「Issue XXX の着手前準備」「実装計画を立てて」「XXX を実装する Issue の準備をして」
user-invocable: true
argument-hint: "<issue番号 または URL>"
allowed-tools: Bash(git *), Bash(gh issue view *), Bash(gh issue edit *), Bash(gh pr list *), Bash(gh pr view *), Bash(gh pr diff *), Bash(gh pr edit *), Bash(gh repo view *), Bash(gh api *), Bash(tee *), Bash(python3 *), Bash(curl -s -H *api.figma.com*), AskUserQuestion, Agent, Skill, Read, Write, Edit, Grep, Glob
---

# /anvil:impl-issue

GitHub Issue の実装を準備から完了まで一貫して行うオーケストレータ。
UI Issue の場合は Figma デザイン仕様書・実装設計書の作成、UI 実装、実装レビューまでカバーする。

**このスキルが Issue に書き込む内容**: 解決の内容（対策・実装計画・TODO）のみ。
課題の内容（背景/現象・原因）は `/anvil:create-issue` が作成済みのため、上書きしない。

## Goal

Issue の調査・ブランチ確認・実装計画の Issue 記載・UI の場合はデザイン仕様書・実装・レビューまで、全 Phase を完走すること。`AskUserQuestion` が必要な判断点以外はユーザー介入なしに継続する。

## フロー継続 [MANDATORY]

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ `AskUserQuestion` で確認する。

## ワークフロー

全 Phase の一覧。Phase 0 と Phase 13 は anvil 固有の前処理・後処理。Phase 1-12 が impl-issue の本体。

| #  | Phase | 対象 |
| -- | ----- | ---- |
| 0  | 前処理（リポジトリ解決・ブランチ準備） | 全て |
| 1  | Issue を確認する | 全て |
| 2  | 仕様書を調査する | 全て |
| 3  | 実装ルールを調査する | 全て |
| 4  | 類似 PR を調査する | 全て |
| 5  | 既存コードを調査する | 全て |
| 6  | Figma デザイン仕様書を作成する | UI Issue のみ |
| 7  | デザイン仕様書をレビューする | UI Issue のみ |
| 8  | 実装計画を策定する | 全て |
| 9  | Issue を更新する（解決内容を追記） | 全て |
| 10 | 実装に進むか確認する | 全て |
| 11 | UI 実装を行う | UI Issue のみ |
| 12 | 実装レビューを行う | UI Issue のみ |
| 13 | 後処理（commit & PR 作成・Closes 保証） | 全て |

---

## Phase 0: 前処理（リポジトリ解決・ブランチ準備）

### 0-1: リポジトリ情報を解決する

`.git_information.yaml` が存在する場合はそこから取得する：

```yaml
# .git_information.yaml
github:
  owner: "<owner>"
  repo: "<repo>"
  default_base_branch: develop # Phase 0-2 のデフォルトとして使用
```

ファイルが存在しない場合は `gh` コマンドで取得する（フォールバック）：

```bash
gh repo view --json nameWithOwner --jq '.nameWithOwner'
```

取得した `<owner>/<repo>` と `<default_base_branch>` を変数として記録し、以降のすべての `--repo` 引数に使用する。

#### 引数が Issue URL の場合のリポジトリ整合チェック [MANDATORY]

`/anvil:impl-issue` の引数として **Issue URL**（例: `https://github.com/<owner>/<repo>/issues/<N>`）が渡された場合、URL から `<url-owner>/<url-repo>` と `<N>` を抽出する。

- `<url-owner>/<url-repo>` が現在のリポジトリ（上で解決した値）と**一致** → 続行。以降は `<N>` を Issue 番号として扱う
- **不一致** → `AskUserQuestion` で次の 3 択を提示する:
  - **中断（推奨）**: 「対象リポに移動して `/anvil:impl-issue <N>` を再実行してください」と案内し終了
  - **読み取り専用で続行**: `gh issue view --repo <url-owner>/<url-repo>` で Issue 内容のみ取得し、ブランチ作成 / Closes 連動 / PR 作成は現在のリポで行う。**`Closes #<N>` ではなく `Closes <url-owner>/<url-repo>#<N>` を使用する**（Phase 13 にも反映）
  - **中止**: 終了コード非ゼロで停止

Issue 番号のみ（URL ではない）で渡された場合はこのチェックは不要。

### 0-2: ブランチを確認・作成する

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

   b. ベースブランチを最新化してブランチを作成する：

      ```bash
      git fetch origin <base-branch>
      git checkout <base-branch>
      git pull --ff-only origin <base-branch>
      ```

      - `pull --ff-only` が失敗 → `AskUserQuestion` で対応確認（中止推奨）

   c. ブランチ名を決定する。

      **判定順序 [MANDATORY]**:

      1. **Issue のラベルから判定**（最優先・決定的）。リポジトリで使われているラベル命名は揺れるので、以下の語句を**部分一致・大文字小文字無視**で照合する。複数一致した場合は表の上位を優先：

         | プレフィックス | 一致するラベル語句（部分一致・case-insensitive） |
         | -------------- | ------------------------------------------------ |
         | `fix/`         | `bug`, `fix`, `defect`, `修正`, `不具合`         |
         | `feature/`     | `feature`, `enhancement`, `feat`, `新機能`, `機能追加` |
         | `refactor/`    | `refactor`, `refactoring`, `cleanup`, `リファクタ` |
         | `docs/`        | `doc`, `docs`, `documentation`, `文書`           |
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

      ```bash
      git checkout -b <branch-name>
      ```

---

## Phase 1: Issue を確認する

1. ユーザーから Issue 番号または URL を受け取る
2. Issue の現在の内容を取得する（`<owner>/<repo>` は Phase 0-1 で解決した値）：

   ```bash
   gh issue view <issue番号> --repo <owner>/<repo>
   ```

3. コメントも確認する（既存の調査結果がある場合）：

   ```bash
   gh issue view <issue番号> --repo <owner>/<repo> --comments
   ```

4. タイトル・本文・ラベルから実装内容・タスク種別を把握する
5. 既存の TODO や計画が記載されていれば確認する
6. **UI Issue か判定する**: 次の表で判定し、判断が割れた場合は `AskUserQuestion` でユーザーに確認する

   | 観点 | UI Issue | データ / API / ドメイン Issue |
   | ---- | -------- | ----------------------------- |
   | 実装対象が UI / 画面ディレクトリ（プロジェクト規約） | ✅ | ✗ |
   | Figma URL が「**実装対象**」として記載 | ✅ | ✗（参考添付なら非 UI） |
   | 画面設計書への参照が「実装対象」として記載 | ✅ | ✗（参考添付なら非 UI） |
   | ラベルに UI / 画面相当の表示 | ✅ | ✗ |
   | ラベルに data / domain / infrastructure / api 相当 | ✗ | ✅ |
   | 実装対象がドメイン層 / データ層のみ | ✗ | ✅ |

   - 「Figma URL や画面名が**参考として**書かれているだけ」のデータ / API Issue を UI Issue と誤判定しないこと。

7. **UI Issue と判定された場合のみ、Figma PAT 疎通確認**を実施する（後方での手戻り防止）：

   ```bash
   curl -s -H "X-Figma-Token: $FIGMA_PAT" "https://api.figma.com/v1/me"
   ```

   - 成功 → 続行
   - 失敗 → サイレントスキップしない。`AskUserQuestion` で以下の 3 択を提示する:
     - **再指定**: PAT を設定し直して再実行する手順を案内し、ユーザーが整え次第再試行
     - **非 UI Issue へ切替**: 種別を非 UI Issue に変更し、Figma 関連 Phase はそもそも実行しない
     - **中断**: 非ゼロ終了コードで処理を停止し、stderr に未充足項目（FIGMA_PAT）と充足手順を出力する

## Phase 2: 仕様書を調査する

`/forge:query-db-specs` を使い、Issue のタイトル・本文から **抽出した検索キーワード** または **短い自然文のタスク記述** を `args` として渡し、関連仕様書を特定する。Issue 本文をそのまま貼り付けない。

**調査前に必ず [`references/phase-02-spec-investigation.md`](references/phase-02-spec-investigation.md) を読む。**

## Phase 3: 実装ルールを調査する

`/forge:query-db-rules` を使い、タスクに関連するルール文書を特定する。`args` は Issue 本文から **抽出した検索キーワード** または **短い自然文のタスク記述** に限定し、Issue 本文・実装手順をそのまま貼り付けない。

**必須ルール**:

- 特定したルール文書は**すべて**実際に Read tool で読み込む
- CLAUDE.md に記載されているプロジェクト構造・アーキテクチャの説明を確認する
- `/forge:query-db-rules` で「architecture」「coding」「layer」「ディレクトリ構造」等をクエリして重要文書を特定する

## Phase 4: 類似実装済み PR を調査する

今回の実装と同じスコープのマージ済み PR を 3 件以上探し、実装パターンを学習する。

**調査前に必ず [`references/phase-04-pr-investigation.md`](references/phase-04-pr-investigation.md) を読む。**

## Phase 5: 既存コードを調査する

実装に再利用できる既存クラス・コンポーネント・ユーティリティを特定する。

**調査前に必ず [`references/phase-05-code-investigation.md`](references/phase-05-code-investigation.md) を読む。**

## Phase 6: Figma デザイン仕様書を作成する（UI Issue のみ）

**条件**: Phase 1 で UI Issue と判定された場合のみ実行。それ以外はスキップして Phase 8 へ。

### Phase 6 開始時の依存ツール確認

UI Issue と判定された＝ Figma からの取り込みが必要、と確定した時点で、`/anvil:prepare-figma` を呼ぶ前に必要ツールの有無をオーケストレータ側で確認する。
**AI は依存ツールを勝手にインストールしない**。

確認対象は `/anvil:prepare-figma` の前提条件セクションを参照する。

不足している場合は `AskUserQuestion` で次の選択肢を提示する。

| `id` | `label`（ユーザーに見せる） | AI の次アクション |
| ---- | --------------------------- | ----------------- |
| `install_by_ai` | AI が必要ツールをインストールする | インストール実行 → 完了後に Phase 6 続行 |
| `install_manually` | 手動でインストールするので待機 | 中断・ユーザー作業完了の合図を待つ |
| `skip_preview` | プレビュー生成をスキップし仕様書のみ作成 | `/anvil:prepare-figma` に `skip_preview=true` を渡して続行 |
| `abort` | 中断 | impl-issue 自体を終了 |

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
3. **スコープ外**: 今回実装しないもの（理由・担当）
4. **参考 PR**: 実装方法の根拠となる PR

Phase 8 で作成する成果物は次の 2 つ。**用途・出力先・参照テンプレートが異なる**ので混同しないこと。

| 成果物 | 用途 | 出力先 | 使うテンプレート / ルール |
| ------ | ---- | ------ | ------------------------- |
| **実装設計書** | 「どう作るか」(How) を決定 | UI Issue: Phase 6 で `/anvil:prepare-figma` が作成した `specs/design/{id}/` ディレクトリ（デザイン仕様書と同じ場所） / 非 UI Issue: プロジェクト規約に従い、設計書置き場（無ければ Phase 0-1 のリポルート直下 `specs/design/<feature-or-issue-slug>/`） | [`references/phase-08-impl-design.md`](references/phase-08-impl-design.md) の「実装設計書テンプレート」 |
| **Issue 本文** | 実装計画を Issue に記載 | GitHub Issue（Phase 9 で `gh` で更新） | [`assets/TEMPLATE.md`](assets/TEMPLATE.md)（更新手順は [`references/phase-09-issue-update.md`](references/phase-09-issue-update.md)） |

**実装設計書**は UI Issue の場合のみ作成する。既存コンポーネント対応表、**Typography 対応表**、アクション一覧、状態管理、API 連携等を含む。
**Typography 対応表**は [`references/phase-11-typography-mapping.md`](references/phase-11-typography-mapping.md) に従い、デザイン仕様書の全テキストノードを列挙すること。

**実装設計書 作成前に必ず [`references/phase-08-impl-design.md`](references/phase-08-impl-design.md) を読む。**

## Phase 9: Issue を更新する（解決内容を追記）

**書き込む内容**: 解決内容（対策・実装計画・TODO）のみを Issue に追記する。
背景 / 現象・原因はすでに記載済みのため、上書きしない。

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

### 実装後セルフチェック [MANDATORY]

[`references/phase-11-ui-implementation.md` の「実装後セルフチェック」](references/phase-11-ui-implementation.md#実装後セルフチェック-mandatory)を実施する。
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

`Skill` ツールで `/forge:review code` を委譲実行する（デフォルトは `--diff --interactive --codex`）。

```
Skill ツールで /forge:review code を呼び出す
- 対象: 現ブランチの未 commit 差分
- 指摘発生時: reviewer の提示に従って修正、または --auto-critical 等を別途呼び直す
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
> 3. PR 作成失敗時は `/anvil:create-pr` を直接再実行**せず**、`/anvil:impl-issue #<issue-number>` から再開する（Issue 番号引き継ぎ経路を保つため）
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
- [Phase 2: 仕様書調査ルール](references/phase-02-spec-investigation.md)
- [Phase 4: 類似 PR 調査ルール](references/phase-04-pr-investigation.md)
- [Phase 5: 既存コード調査ルール](references/phase-05-code-investigation.md)
- [Phase 8: 実装設計書 作成ルール](references/phase-08-impl-design.md)
- [Phase 9: Issue 更新ルール](references/phase-09-issue-update.md)
- [Phase 11: UI 実装ルール](references/phase-11-ui-implementation.md)
- [Phase 11: Typography 照合ルール](references/phase-11-typography-mapping.md)
- [Phase 12: UI 実装レビュールール](references/phase-12-ui-review.md)
