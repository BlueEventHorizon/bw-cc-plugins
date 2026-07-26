# DES-047 msg-review 修正安全ガードレール（allowlist・単一所見適用・構文検証ロールバック）設計書

## メタデータ

| 項目     | 値                                                                                              |
| -------- | ----------------------------------------------------------------------------------------------- |
| 設計ID   | DES-047                                                                                         |
| 関連要件 | REQ-012 FNC-004（Claude 直接修正）                                                              |
| 関連設計 | DES-045（msg-review 本体設計）・DES-046（介入軸実装。§2「やらないこと」の一部を本設計で再検討） |
| 作成日   | 2026-07-19                                                                                      |
| 状態     | 実装済み（ユーザー承認済み。§2/§3.1/§3.3 を「検出専用・ロールバック非自動化」方針に改訂）       |

## 1. 解決する問題

廃止された session_dir 駆動レビューパイプラインの fixer Agent は、修正実施時に以下 4 つの安全境界を Role 制約として常時適用していた:

1. **単一 finding 起動**: 1 Agent 起動 = 1 finding。バッチ適用しない
2. **allowlist 制約**: `allowed_files`（evaluator が渡す）の外へ Write/Edit しない。違反は `allowlist_violations` に記録し `status: "error"`
3. **無関係な refactor 禁止**: 指摘された修正のみ適用する
4. **修正後の構文検証**: 拡張子別コマンド表（Python: `py_compile` / Markdown: `dprint check` / YAML: `yaml_utils.read_yaml` / JSON: `json.load` / Bash: `bash -n` / TOML: `tomllib.load`）で検証し、失敗時は元の内容にロールバックする。ただし `check_baseline_violations.py` が事前取得した baseline に含まれる pre-existing 違反（dprint/Markdown 限定）はロールバック対象外とする

一方、msg-review は Claude 自身が受信モード Step 2a で直接ファイルを編集する（FNC-004。DES-046 §2 でも Agent 分離は明示的に対象外とした）。この結果、上記 4 境界に相当する仕組みが msg-review には **一切存在しない**。「これで review SKILL を置換できるか」という累次の検討の中で指摘された懸念②（fixer 相当の安全ガードレール欠如）はこの欠落を指す。

**旧実装のテストの限界**: 旧 fixer Agent に対するテストは prompt 本文に 4 制約の語彙が含まれているかを検査する **静的 grep テスト**であり、実行時の allowlist 逸脱・構文破壊を検出する **挙動テスト**ではなかった。本設計は、この「決定論的に検証可能で、msg-review の直接編集モデルに移植可能な部分」だけを切り出す。

## 2. 4 境界のうち何を移植するか（判断の内訳）

| # | fixer.md の境界                     | msg-review への移植可否                                                                                                                                                                                                                                                                                                                        | 対応方針                                   |
| - | ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| 1 | 単一 finding 起動                   | **移植する（再検討の結果、可能と判断）**。Agent 分離ありきの制約ではなく「1件適用→即検証→次へ進む」という **逐次適用の手続き**として msg-review にも実装できる。バッチ適用時の被害拡大（1件の欠陥修正が他3件の編集の後に埋もれて発覚する）を防ぐ効果は Agent 分離と独立に得られる                                                              | §3.1 逐次適用ループ（SKILL.md 手順変更）   |
| 2 | allowlist 制約                      | **移植する**。決定論的な検証（実際に変更されたファイル集合 ⊆ 依頼モード Step 3 で解決した target_files）であり、msg-review でも `target_files` を保持している                                                                                                                                                                                  | §3.2 `verify_fix_safety.py`                |
| 3 | 無関係な refactor 禁止              | **移植しない（新規コード不要）**。fixer.md でもこれは Role 制約（prompt 文言）であり、実行時に決定論的検証可能なロジックではない（`test_fixer_safety_prompt.py` も grep のみ）。msg-review の Step 1「所見評価」は既に「指摘された修正のみ実施する」相当の制約を持つ。本設計では SKILL.md の該当箇所にこの制約を明記する一文を追加するに留める | §3.4 SKILL.md 文言追加のみ                 |
| 4 | 構文検証＋baseline 考慮ロールバック | **移植する**。`check_baseline_violations.py` の判定ロジック（dprint exit code 0/14/20 の扱い、未インストール時の fail-safe）をそのまま踏襲し、`session_dir`/`refs.yaml` 依存を外してプレーンなファイルリスト入力に一般化する                                                                                                                   | §3.2 `verify_fix_safety.py` の構文検証部分 |

比例性の確認（`scope_proportionality_spec.md`）: 上記②④が防ごうとしているのは「Claude の直接編集が対象外ファイルを変更する」「修正が構文エラーを埋め込む」という、通常運用で普通に起こりうる失敗（カタストロフィックな外部要因でも投機的リスクでもない）であり、同文書 §2 の3類型に該当しない。したがって同文書の3点チェックは適用されず、通常の fix 対象として扱ってよい。

### 2.1 検証スクリプトは「検出・報告専用」とし、ロールバックを自動実行しない [ユーザー指示による方針転換・2026-07-19]

当初案は、allowlist 逸脱・新規構文エラーを検出した場合にスクリプトが当該ファイルを自動でロールバック（元の内容に復元）する設計だった。しかしユーザーレビューで以下 2 点の懸念が指摘され、方針を転換した:

1. **allowlist 逸脱は常に誤りとは限らない**: レビュー基準に照らして正当な波及修正（対象ファイルの修正に伴い関連ファイルも直す必要がある場合等）まで機械的に「違反」としてロールバックすると、正しい修正を破棄してしまう
2. **検証スクリプト自体がバグの温床になりうる**: とくに「実際に変更されたファイルの検出」を git diff 等で行おうとすると、`--diff` モードでは対象ファイル自体がすでに未 commit 差分として存在するため「今回の finding 修正で新たに触れた分」と「元々あった差分」の切り分けが必要になり複雑化する（本セッションで `wake_codex.sh` の stderr 誤判定のような「検証ロジック自体のバグ」が複数回見つかっている実績を踏まえた懸念）

**転換後の設計方針**:

- `verify_fix_safety.py` は allowlist 逸脱・構文検証結果を **JSON で報告するだけ**で、いかなるファイルも書き換えない（Write/Edit 相当の操作を一切行わない）
- 「実際に変更されたファイル」は git diff 等で外部推測せず、**そのfinding の修正で Claude 自身が Edit したファイルパスを Claude が自己申告**する（Claude は自分が何を編集したか常に把握しており、外部からの検出は不要）
- ロールバックを実行するかどうかの判断は常に Claude 自身が行う: 検証結果が事故的な逸脱と判断すれば Claude が自分で Edit により元に戻す。正当な波及修正と判断すれば、その理由を修正報告に明記した上で維持する（沈黙したスコープ拡大を許さない）

## 3. 設計

### 3.1 逐次適用ループ（境界①相当、新規コード無し・SKILL.md 手順変更のみ）

受信モード Step 2a の `confirmed_fix` 適用手順を、全件をまとめて編集してから検証する方式から、**1 finding ごとに「適用 → 検証 → 次へ」を繰り返す**方式に変更する:

```
for finding in confirmed_fix:
    1. この finding の修正のみを実施する（他の confirmed_fix の編集は行わない）
    2. この finding のために実際に Edit したファイルパスを自己申告する
    3. verify_fix_safety.py を実行し、allowlist 逸脱・構文検証結果を取得する（§3.2、検出専用・ロールバックはしない）
    4. 検出結果を Claude 自身が判断する:
       - 事故的な逸脱・新規構文エラーと判断 → Claude 自身が Edit で元の内容に戻し、この finding を
         「対応しない（理由: 修正後の安全検証で問題を検出したため取り消し）」として記録する
       - 正当な波及修正（allowlist 外の関連ファイル修正等）と判断 → 維持し、修正報告にその理由を明記する
    5. 次の finding へ進む
```

これにより、ある finding の修正が原因で発生した allowlist 逸脱・構文エラーが、後続 finding の編集に埋もれて発覚しないまま最終報告まで到達することを防ぐ。判断の主体は常に Claude であり、スクリプトが自動でファイルを書き換えることはない（§2.1）。

### 3.2 新規スクリプト `capture_syntax_baseline.py`

`check_baseline_violations.py` の dprint 判定ロジック（exit code 0=ok / 14=対象外 / 20=違反 / その他=未インストール等の fail-safe で違反なし扱い）をそのまま踏襲し、`session_dir`/`refs.yaml` 結合を外してプレーンなファイルリストを入力にする（REQ-012 §2.2 により session_dir/findings_state.yaml 等のパイプライン結合は msg-review のスコープ外であるため、この一般化が必要）。

```
python3 capture_syntax_baseline.py --files-json '["a.md", "b.py"]' [--project-root <path>]
```

出力（標準出力に単一 JSON）:

```json
{
  "status": "ok",
  "tool": "dprint",
  "tool_version": "0.50.0",
  "files": {
    "a.md": { "has_violations": true, "exit_code": 20 },
    "b.json": { "has_violations": false, "exit_code": 0 }
  }
}
```

`dprint` 未インストール環境では `tool: null` / 全ファイル `has_violations: false` の空 baseline を返す（`check_baseline_violations.py` と同一の fail-safe）。`.py`/`.sh` 等 dprint 管掌外の拡張子は本スクリプトの対象外（構文検証は §3.3 の `verify_fix_safety.py` 側で別途 `ast.parse`/`bash -n` 等を実施し、baseline を参照しない。後述）。

### 3.3 新規スクリプト `verify_fix_safety.py`（境界②④、検出・報告専用 [§2.1]）

依頼モード Step 3 で解決した `target_files`（allowlist の正）と、finding 適用直後に **Claude 自身が自己申告した**「実際に Edit したファイルパス」、§3.2 で取得した修正前 baseline を受け取り検証する。**ファイルを一切書き換えない**（ロールバックの実行は行わない。§2.1）。

```
python3 verify_fix_safety.py \
  --allowed-files-json '["a.md", "b.py"]' \
  --modified-files-json '["a.md", "c.py"]' \
  --baseline-json '<capture_syntax_baseline.py の出力>' \
  [--project-root <path>]
```

処理内容:

1. **allowlist 検証**: `modified_files - allowed_files` を計算し、非空なら `allowlist_violations` に列挙する（allowlist の内外を問わず、次の構文検証は `modified_files` 全件に対して行う。allowlist 外だからといって構文検証をスキップしない。**削除されたファイルであっても allowlist 検証は通常どおり行う**。後述）
2. **構文検証**: `modified_files` のうち対応拡張子（`.md`/`.json`/`.yaml`/`.yml`/`.toml`/`.py`/`.sh`）を持つ各ファイルについて、まず**実在確認**を行う。実在しない場合は削除されたファイルとみなし `syntax_skipped_deleted` に記録して構文検証をスキップする（実 Codex レビューで発見: `collect_modified_files.py` が返す `modified_files` は変更・削除・rename後の現在パスを区別せず一律で渡ってくるため、削除されたファイルにそのまま構文検証コマンドを実行すると「ファイルがない」という無関係なエラーになり、正当な削除を伴う修正が不当に構文エラー扱いされる）。実在する場合は拡張子別コマンドで検証する:
   - `.md`/`.json`/`.yaml`/`.yml`/`.toml`（このリポジトリの dprint.jsonc スコープと同一）: `dprint check` を実行し、baseline-aware に判定する（fixer.md §3.5.4 の dprint pre-existing 判定ロジックを踏襲。exit 0/14 = 違反なし、exit 20 かつ baseline 側 `has_violations: true` = pre-existing としてスキップ、exit 20 かつ baseline 側に無い/false = 新規違反）
   - `.py`: `ast.parse`（`python3 -c` 経由。baseline を参照しない。fixer.md 同様、文法エラーは pre-existing/新規の区別が無意味なため。`py_compile` を使わない理由は §3.3 の `_check_python_syntax` の説明を参照）
   - `.sh`: `bash -n`（同上、baseline を参照しない）
   - 上記いずれの拡張子でもない場合: 実在確認より前に振り分け、検証をスキップして `syntax_skipped_unsupported` に記録（エラー扱いにしない）

出力（標準出力に単一 JSON）:

```json
{
  "status": "ok" | "violations",
  "allowlist_violations": ["c.py"],
  "syntax_errors": {"a.md": "dprint check 違反（baseline外）: ..."},
  "syntax_skipped_preexisting": [],
  "syntax_skipped_unsupported": [],
  "syntax_skipped_deleted": [],
  "syntax_ok": ["b.py"]
}
```

`allowlist_violations` または `syntax_errors` のいずれかが非空なら `status: "violations"`。**この `status` はスクリプトが自動でロールバックする根拠ではなく、Claude が判断材料として使う情報にすぎない**（§2.1・§3.1）。

`_check_python_syntax` は `python3 -m py_compile` ではなく `ast.parse`（`python3 -c` 経由）を使う。理由は py_compile.compile() が `cfile` 未指定時に `__pycache__/*.pyc` を常に書き込むためで、インタプリタの `-B` フラグ（暗黙のインポート時キャッシュにのみ作用）では抑止できない。本スクリプトの「ファイルを一切書き換えない」契約（§2.1）を守るには、ファイルを一切生成しない `ast.parse` による構文検査が必要（実 Codex レビューで py_compile 由来の `__pycache__` 残留を発見・修正）。

### 3.4 SKILL.md への統合

受信モード Step 2a に以下を追加する:

1. **Step 3（依頼モード）で解決した `target_files` を allowlist として保持する**（既存のコンテキスト保持に変更なし。新規に何かを記憶する必要はない）
2. `confirmed_fix` 適用前に `capture_syntax_baseline.py` を `target_files` に対して実行し、baseline を取得する
3. §3.1 の逐次適用ループに従い、finding ごとに「適用 → 自己申告 → `verify_fix_safety.py` で検証 → **Claude が判断**（事故的なら自分で Edit して元に戻す／正当な波及修正なら理由を記録して維持）」を実施する。スクリプトは検出・報告専用でありロールバックを自動実行しない（§2.1）
4. 「無関係な refactor 禁止」（境界③）を明文の制約として Step 1「所見評価」に一文追加する: 「実施する修正は当該所見が指摘した内容に限定し、関連する体裁修正・リファクタリングを合わせて行わない」
5. `verify_fix_safety.py` の結果を受けて Claude が元に戻した finding は、修正報告の対応表で「対応しない（理由: 修正後の安全検証で問題を検出したため取り消し）」として明記する（Step 2c 相当の非対応理由カタログにこの理由を追加）。allowlist 外の変更を正当と判断し維持した場合は、その理由を修正報告に明記する（沈黙したスコープ拡大を許さない）

### 3.5 ラウンド終了時の独立検証 [MANDATORY]（自己申告への依存の補完・実 Codex レビューで発見）

§3.1 の逐次適用ループは finding ごとの自己申告（Claude が「このために Edit したファイル」を申告）に基づいて allowlist 検証を行う。この方式は §2.1 で述べた通り、git diff ベースの複雑な検出（`--diff` モードでは対象ファイル自体が既にラウンド開始前から未 commit 差分として存在するため、finding 単位の変更を厳密に切り分けるには前後のスナップショット比較が必要になり複雑化・バグりやすくなる）を避けるために採用した。

しかし実 Codex レビューで、この方式には「申告漏れ（Claude が編集したことを自己申告し忘れる、あるいはコンテキスト喪失により見落とす）が起きた場合、そのファイルは allowlist 検証・構文検証のいずれも通過しないまま完全に見過ごされる」という盲点があると指摘された。§2.1 の「Claude は自分が何を編集したか常に把握しているため外部からの検出は不要」という前提は、まさにその「常に把握している」という前提が崩れた場合（誤操作・見落とし）を防ぐガードとしては循環している。

**採用した補完策**: finding 単位の精密な帰属（「どの finding が原因でこのファイルが変更されたか」）は諦めるが、**ラウンド終了時に1回だけ** `git status --porcelain=v1 -z --untracked-files=all` で「このラウンド終了時点で実際に変更・新規追加されているファイル全体」を取得し、`target_files`（および正当と判断し維持した波及修正）を allowlist として独立に照合する。これは git diff の内容比較ではなく単なるパス一覧の取得であり、§2.1 で懸念した「前後のスナップショット比較の複雑さ」を伴わない。自己申告に一切現れなかった変更が実在すれば、この最終チェックで検出できる（帰属は分からないが、存在は分かる）。

**パス抽出は行/矢印単位の手動パースをしない [ユーザー指示不要・実 Codex レビューで発見の修正]**: 当初 SKILL.md 手順は「`git status --porcelain` の出力を行ごとに見てパスを抽出する（rename 行は `->` の右側を採用）」と記述していたが、`-z` 無しの porcelain は空白・改行・非 ASCII を含むパスを C-style quote し、rename/copy は `->` を含む1行で表現するため、手動パースでは実パスを取り違える。これは「決定論的な処理はスクリプト化する」（`docs/rules/implementation_guidelines.md`）という既存原則そのものの違反でもある。新規スクリプト `collect_modified_files.py` を追加し、`-z`（NUL 区切り・quote 無し）出力を決定論的に解析させる。rename/copy レコードの実際のフィールド順序（実 git 挙動で実測確認）は「1トークン目 = 現在の（新）パス（status prefix 付き）、2トークン目 = 旧パス（prefix 無し、消費するだけで使わない）」であり、git-status(1) のマニュアル記述だけから類推せず実際の出力で検証した。

```
python3 collect_modified_files.py [--project-root <path>]
```

出力（標準出力に単一 JSON）:

```json
{ "status": "ok", "files": ["existing.txt", "new_file.txt", "renamed.txt"] }
```

## 4. 要件定義書への影響

- REQ-012 に FNC-004 の補足として、Claude 直接修正時も allowlist・構文検証の検証結果を確認し、必要に応じて自ら元に戻す判断を行う旨を追記する（Agent 分離を導入しないという既存の v1 判断 REQ-012 §2.3 は変更しない。ロールバックの実行は Claude 自身の判断であり、スクリプトによる自動実行ではない）
- DES-046 §2「やらないこと」の「evaluator/fixer Agent の分離: ... の安全境界は導入しない」は、**Agent 分離を導入しない**という決定自体は維持しつつ、「安全境界」のうち allowlist・構文検証（検出のみ）の2点は Agent 分離とは独立な決定論的スクリプトとして本設計で導入する旨を明記する（矛盾ではなく決定の精緻化）

## 5. テスト設計

- `test_capture_syntax_baseline.py`（8 tests）: dprint exit code 0/14/20/その他・timeout の扱い、dprint 未インストール時の fail-safe（`tool: null` で全件 `has_violations: false`）、CLI の JSON 入出力
- `test_verify_fix_safety.py`（23 tests）: allowlist 逸脱検出（`modified - allowed` 非空、**削除されたファイルでも allowlist 逸脱判定は通常どおり行われることの確認**）、拡張子別構文検証コマンドの選択（dprint系/Python(ast.parse)/bash -n/未対応拡張子）、baseline に含まれる pre-existing 違反のスキップ判定（dprint系のみ）、Python/bash は baseline を参照せず常に新規エラー扱いになること、baseline に含まれない新規違反の検出、allowlist違反と構文エラーが同時発生するケース、**ファイルを一切書き換えない（Write/Edit 相当の呼び出しをしない）ことの確認**（§2.1 の検出専用性の担保）、**モックなしの実ファイルで Python 構文検証が `__pycache__` を生成しないこと・実際の構文エラーを検出できることの確認**（実 Codex レビューで発見した py_compile 副作用の回帰テスト）、**削除された（実在しない）Python/Markdown/Shell ファイルが構文エラーではなく `syntax_skipped_deleted` に振り分けられ、subprocess 呼び出し自体が行われないことの確認**（実 Codex レビューで発見した削除ファイル誤検出の回帰テスト）
- `test_collect_modified_files.py`（13 tests）: 通常の変更/untracked ファイルの抽出、rename/copy レコードの2トークン消費と正しいフィールド（新パス採用・旧パス破棄）、非 ASCII・空白・`->` を含むファイル名の正確な抽出（行/矢印ベースの手動パースでは失敗する回帰ケース、実 Codex レビューで発見）、空出力・末尾 NUL の扱い、**実 git リポジトリでの end-to-end 動作確認**（modified/added/renamed/**deleted** を実際に発生させて検証）。この統合テスト自体が実装当初の rename フィールド順序の思い違い——git-status(1) のマニュアル記述からの類推で「旧パスが先」と誤って実装していた——を検出した。また GPG commit 署名がグローバル設定されている環境でもテストが失敗しないよう、テスト用リポジトリ限定で `commit.gpgSign=false` を設定する（`test_resolve_targets.py` の既存対策を踏襲。実 Codex レビューで発見）
- 逐次適用ループ・ロールバック判断・§3.5 のラウンド終了時独立検証自体（SKILL.md 手順）は既存の例外規定により自動テスト対象外。手動確認（実 Codex レビュー往復）で検証する

## 6. 未確定事項

なし。
