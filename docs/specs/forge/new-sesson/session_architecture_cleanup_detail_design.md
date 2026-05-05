# forge session architecture cleanup 詳細設計書

## メタデータ

| 項目     | 値                                                                   |
| -------- | -------------------------------------------------------------------- |
| 種別     | 詳細設計                                                             |
| 対象     | forge session / monitor / writer / thin wrapper                      |
| 作成日   | 2026-05-05                                                           |
| 基本設計 | `docs/specs/forge/new-sesson/session_architecture_cleanup_design.md` |

## 必須参照文書 [MANDATORY]

**NEVER skip.** 実装時は下記を全て読み込み、深く理解すること。

- `docs/specs/forge/new-sesson/session_architecture_cleanup_design.md`
- `docs/rules/implementation_guidelines.md`
- `docs/rules/skill_authoring_notes.md`
- `docs/rules/document_writing_rules.md`
- `plugins/forge/docs/session_format.md`
- `docs/specs/forge/design/DES-012_show_browser_design.md`
- `docs/specs/forge/design/DES-014_orchestrator_session_protocol_design.md`
- `docs/specs/forge/design/DES-024_skill_script_layout_design.md`

## 設計判断

本詳細設計は、移行計画を別ファイルへ分割しない。理由は、session / monitor / writer / wrapper の責務境界が相互依存しており、設計と移行順を同じ文書で読む方が実装判断を誤りにくいためである。

ただし、実装開始時は本書の「実装フェーズ」をそのまま `docs/specs/forge/plan/` の計画書へ切り出してよい。

## 前提

### 維持する前提

- セッション保存場所は `.claude/.temp/{session}/` のままとする
- `session_manager.py`、`scripts/session/*.py` の public CLI path は維持する
- thin wrapper は原則維持する
- `/session` レスポンスは後方互換を維持する
- `plan.yaml` は review item state の唯一の正規情報源とする
- `session.yaml` は manifest と粗い進行状態だけを持つ
- Python は標準ライブラリのみ使用する

### 実装前に確認が必要な前提 [MANDATORY]

以下は、本書で推奨方針を示すが、実装で破壊的変更を行う前にユーザ確認を必須とする。

- `skill_monitor.py` の削除
- public CLI path の rename / move
- thin wrapper の削除
- `/session` JSON 互換を破る変更
- `.claude/.temp/` 以外のセッション保存場所導入

## 変更対象

### 追加するファイル

| パス                                               | 目的                                              |
| -------------------------------------------------- | ------------------------------------------------- |
| `plugins/forge/scripts/monitor/session_adapter.py` | session files を monitor 表示用 JSON へ正規化する |
| `tests/forge/scripts/test_session_adapter.py`      | adapter の単体テスト                              |

### 変更するファイル

| パス                                                             | 変更内容                                               |
| ---------------------------------------------------------------- | ------------------------------------------------------ |
| `plugins/forge/scripts/session_manager.py`                       | `update-meta` subcommand と atomic write helper を追加 |
| `plugins/forge/scripts/monitor/server.py`                        | `YamlReader` 相当を adapter 呼び出しへ置換             |
| `plugins/forge/scripts/session/write_refs.py`                    | 書き込み後に session meta を更新                       |
| `plugins/forge/scripts/session/update_plan.py`                   | 書き込み後に session meta を更新                       |
| `plugins/forge/scripts/session/merge_evals.py`                   | merge 後に session meta を更新                         |
| `plugins/forge/scripts/session/write_interpretation.py`          | 書き込み後に session meta を更新                       |
| `plugins/forge/skills/review/scripts/extract_review_findings.py` | plan / review 生成後に session meta を更新             |
| `plugins/forge/docs/session_format.md`                           | 正規責務表と session.yaml 追加フィールドを反映         |
| `tests/forge/scripts/test_session_manager.py`                    | `update-meta` を追加検証                               |
| `tests/forge/scripts/test_monitor_server.py`                     | adapter 利用後の server 挙動を検証                     |

### 削除候補

| パス                                        | 条件                                                                 |
| ------------------------------------------- | -------------------------------------------------------------------- |
| `plugins/forge/scripts/skill_monitor.py`    | runtime 参照がなく、テスト観点を移植し、ユーザが承認した場合のみ削除 |
| `tests/forge/scripts/test_skill_monitor.py` | `skill_monitor.py` 削除時に必要観点を移植して削除                    |

## session.yaml 詳細設計

### 追加フィールド

`session.yaml` は flat YAML のまま維持する。深いネスト、配列、成果物本文、review item は追加しない。

| フィールド        | 型     | 許容値 / 形式                                      | 既定値        | 更新者                    | 説明                     |
| ----------------- | ------ | -------------------------------------------------- | ------------- | ------------------------- | ------------------------ |
| `phase`           | string | 下記 phase enum                                    | `created`     | `session_manager`, writer | 粗い進行段階             |
| `phase_status`    | string | `pending` / `in_progress` / `completed` / `failed` | `in_progress` | `session_manager`, writer | phase の状態             |
| `focus`           | string | 1 行文字列                                         | `""`          | writer                    | monitor 表示用の短い焦点 |
| `waiting_type`    | string | `none` / `user_input` / `agent` / `command`        | `none`        | writer または SKILL       | 待機種別                 |
| `waiting_reason`  | string | 1 行文字列                                         | `""`          | writer または SKILL       | 待機理由                 |
| `active_artifact` | string | session_dir 相対パスまたは project 相対パス        | `""`          | writer                    | 直近更新成果物           |

### phase enum

phase は workflow ごとの差分を許容するが、monitor 表示とテストを安定させるため、まず以下だけを標準値とする。

| phase               | 用途                                    |
| ------------------- | --------------------------------------- |
| `created`           | セッション作成直後                      |
| `context_gathering` | refs / refs.yaml 作成中                 |
| `context_ready`     | 参照情報が揃った                        |
| `review_running`    | reviewer / evaluator / fixer 実行中     |
| `review_extracted`  | `review.md` / `plan.yaml` 初期生成済み  |
| `evaluation_merged` | evaluator 結果を `plan.yaml` へ反映済み |
| `fixing`            | fixer 実行中                            |
| `document_drafting` | requirements / design / plan 作成中     |
| `artifact_ready`    | 主要成果物が作成済み                    |
| `completed`         | 正常完了                                |
| `failed`            | 失敗                                    |

未定義 phase は拒否せず保存する。ただし `derived.phase_label` では `phase` 文字列をそのまま表示する。

### init 時の出力例

```yaml
skill: review
started_at: "2026-05-05T01:00:00Z"
last_updated: "2026-05-05T01:00:00Z"
status: in_progress
resume_policy: resume
review_type: code
engine: codex
auto_count: 0
current_cycle: 0
phase: created
phase_status: in_progress
focus: ""
waiting_type: none
waiting_reason: ""
active_artifact: ""
```

### 更新規則

- `last_updated` は `update-meta` 成功時に必ず更新する
- 未指定フィールドは既存値を保持する
- 空文字指定は明示的な clear として扱う
- `waiting_type=none` の場合、`waiting_reason` は空文字へ正規化する
- `phase_status=completed` かつ `phase=completed` の場合、既存 `status` も `completed` に更新する
- `phase_status=failed` または `phase=failed` の場合、既存 `status` は変更しない。失敗復旧を session lifecycle と分離するためである

## session_manager.py 詳細設計

### subcommand

`update-meta` を追加する。

```bash
python3 plugins/forge/scripts/session_manager.py update-meta {session_dir} \
  [--phase PHASE] \
  [--phase-status STATUS] \
  [--focus TEXT] \
  [--waiting-type TYPE] \
  [--waiting-reason TEXT] \
  [--active-artifact PATH]
```

### stdout

成功時:

```json
{
  "status": "ok",
  "session_dir": ".claude/.temp/review-a1b2c3",
  "session_path": ".claude/.temp/review-a1b2c3/session.yaml",
  "updated": ["phase", "focus", "last_updated"]
}
```

エラー時:

```json
{
  "status": "error",
  "error": "session.yaml が見つかりません: ..."
}
```

### exit code

| 条件              | exit |
| ----------------- | ---- |
| 更新成功          | 0    |
| session_dir 不在  | 1    |
| session.yaml 不在 | 1    |
| YAML 読み込み失敗 | 1    |
| 許容値が不正      | 1    |
| 書き込み失敗      | 1    |

### validation

| 入力              | validation                                                    |
| ----------------- | ------------------------------------------------------------- |
| `session_dir`     | ディレクトリが存在すること                                    |
| `phase_status`    | `pending` / `in_progress` / `completed` / `failed` のいずれか |
| `waiting_type`    | `none` / `user_input` / `agent` / `command` のいずれか        |
| `focus`           | 改行を空白へ正規化                                            |
| `waiting_reason`  | 改行を空白へ正規化                                            |
| `active_artifact` | 絶対パスは許容するが YAML には入力値のまま保存する            |

phase は拒否しない。将来 skill 固有 phase を追加しやすくするためである。

### atomic write

`session.yaml` 更新は同一ディレクトリ内の一時ファイルに書き、`os.replace()` で置換する。

実装方針:

```python
def atomic_write_text(path: Path, content: str) -> None:
    ...
```

`yaml_utils.write_flat_yaml()` は既存の直接書き込み用途を維持する。`session_manager.py` では atomic helper を使う。

### notify

`update-meta` は `monitor.notify.notify_session_update(session_dir, session_yaml_path)` を呼ぶ。monitor 不在時は成功扱いである。

## writer script 詳細設計

### 内部 helper

writer script から subprocess で `session_manager.py update-meta` を呼ぶと Python 起動が増えるため、`session_manager.py` に import 可能な関数を追加する。

```python
def update_session_meta(session_dir: str, updates: dict, *, notify: bool = True) -> dict:
    ...
```

CLI の `cmd_update_meta()` はこの関数を呼ぶ。

### writer 失敗方針

成果物本文の保存に成功し、session meta 更新だけ失敗した場合は、writer 本体は成功扱いにする。ただし stderr に警告を出す。

理由:

- `session.yaml` は粗い進行状態であり、正規成果物ではない
- monitor 表示のために主処理を失敗させない
- review item state は `plan.yaml` が保持する

警告形式:

```text
[forge session] warning: update-meta failed: <reason>
```

### writer 別更新内容

| writer                       | 更新タイミング                       | updates                                                                          |
| ---------------------------- | ------------------------------------ | -------------------------------------------------------------------------------- |
| `write_refs.py`              | `refs.yaml` 書き込み成功後           | `phase=context_ready`, `phase_status=completed`, `active_artifact=refs.yaml`     |
| `extract_review_findings.py` | `plan.yaml` と `review.md` 生成後    | `phase=review_extracted`, `phase_status=completed`, `active_artifact=review.md`  |
| `merge_evals.py`             | `plan.yaml` 更新成功後               | `phase=evaluation_merged`, `phase_status=completed`, `active_artifact=plan.yaml` |
| `update_plan.py`             | `plan.yaml` 更新成功後               | `active_artifact=plan.yaml`                                                      |
| `write_interpretation.py`    | `review_{perspective}.md` 更新成功後 | `active_artifact=review_{perspective}.md`                                        |
| `summarize_plan.py`          | なし                                 | 読み取り専用のため更新しない                                                     |
| `read_session.py`            | なし                                 | 読み取り専用のため更新しない                                                     |

## monitor/session_adapter.py 詳細設計

### 目的

adapter は session files を読み、既存 `/session` JSON 互換の構造を返す。server は adapter の戻り値をそのまま JSON として返す。

### public API

```python
def build_monitor_session(session_dir: str, skill: str = "") -> dict:
    """session_dir を読み、monitor 用 JSON を返す。"""
```

補助 API:

```python
def read_session_file(session_dir: str, name: str) -> dict:
    ...

def read_refs_file(session_dir: str, name: str) -> dict:
    ...

def build_derived(data: dict, skill: str) -> dict:
    ...
```

### レスポンス schema

```json
{
  "session_dir": ".claude/.temp/review-a1b2c3",
  "skill": "review",
  "files": {
    "session.yaml": {
      "exists": true,
      "content": {}
    },
    "plan.yaml": {
      "exists": false,
      "content": null
    },
    "review.md": {
      "exists": false,
      "content": null
    },
    "requirements.md": {
      "exists": false,
      "content": null
    },
    "design.md": {
      "exists": false,
      "content": null
    }
  },
  "refs": {
    "specs.yaml": {
      "exists": false,
      "content": null
    },
    "rules.yaml": {
      "exists": false,
      "content": null
    },
    "code.yaml": {
      "exists": false,
      "content": null
    }
  },
  "refs_yaml": {
    "exists": false,
    "content": null
  },
  "derived": {
    "phase": "created",
    "phase_status": "in_progress",
    "focus": "",
    "waiting": {
      "type": "none",
      "reason": ""
    },
    "active_artifact": "",
    "review_counts": {
      "total": 0,
      "pending": 0,
      "in_progress": 0,
      "fixed": 0,
      "skipped": 0,
      "needs_review": 0
    }
  }
}
```

### 読み取り対象

既存互換のため、読み取り対象は当面固定リストにする。

```python
SESSION_FILES = [
    "session.yaml",
    "plan.yaml",
    "review.md",
    "requirements.md",
    "design.md",
]

REFS_FILES = [
    "specs.yaml",
    "rules.yaml",
    "code.yaml",
]
```

固定リストは adapter に閉じる。`server.py`、HTML templates、writer script はこのリストを持たない。

### YAML 読み取り

`session.yaml` / `plan.yaml` / `refs/*.yaml` / `refs.yaml` は `session.yaml_utils.parse_yaml()` を使う。

制約:

- parse 失敗は adapter 全体の失敗にしない
- 対象 entry は `exists: true`, `content: null`, `error: str` とする
- stderr に短い警告を出す

entry 例:

```json
{
  "exists": true,
  "content": null,
  "error": "YAML parse failed: ..."
}
```

### Markdown 読み取り

Markdown は文字列として読む。読み込み失敗時は YAML と同じ entry error 形式にする。

### derived

`derived` は表示補助であり、正規状態ではない。欠損ファイルを許容する。

#### phase

`session.yaml` の値から構築する。

| derived field     | source                    | fallback                              |
| ----------------- | ------------------------- | ------------------------------------- |
| `phase`           | `session.phase`           | `created`                             |
| `phase_status`    | `session.phase_status`    | `session.status` または `in_progress` |
| `focus`           | `session.focus`           | `""`                                  |
| `waiting.type`    | `session.waiting_type`    | `none`                                |
| `waiting.reason`  | `session.waiting_reason`  | `""`                                  |
| `active_artifact` | `session.active_artifact` | `""`                                  |

#### review_counts

`plan.yaml` の `items[]` から計算する。`plan.yaml` 不在または parse 失敗時は全 0。

```python
statuses = ["pending", "in_progress", "fixed", "skipped", "needs_review"]
```

未定義 status は `other` として数えてもよいが、初期実装では `total` のみに含める。

## monitor/server.py 詳細設計

### 変更方針

`server.py` は以下に集中する。

- HTTP endpoint
- SSE client 管理
- notify 受信
- heartbeat
- template / asset 配信

`YamlReader` は削除または thin facade にし、実体は `session_adapter.build_monitor_session()` へ委譲する。

### `_handle_session`

変更後:

```python
def _handle_session(self):
    data = build_monitor_session(self.server.session_dir, self.server.skill)
    self._send_json(data)
```

`data["skill"]` の付与は adapter 側で行う。

### 後方互換

既存 template は以下を参照しているため維持する。

- `data.files["session.yaml"]`
- `data.files["plan.yaml"]`
- `data.files["review.md"]`
- `data.refs`
- `data.refs_yaml`
- `data.skill`
- `data.session_dir`

`derived` は追加のみであり、既存 template を壊さない。

## monitor templates 詳細設計

初期実装では template の大改修をしない。`derived` は任意利用に留める。

### 優先修正

| template         | 修正内容                                                                              |
| ---------------- | ------------------------------------------------------------------------------------- |
| `document.html`  | meta 表示で `created_at` ではなく `started_at` を読む。`phase` / `focus` があれば表示 |
| `review.html`    | summary に `derived.review_counts` を使える場合は利用                                 |
| `implement.html` | `phase` / `focus` があれば表示                                                        |
| `uxui.html`      | `phase` / `focus` があれば表示                                                        |

表示差分は小さくし、UI 再設計は行わない。

## thin wrapper 詳細設計

### 実装では原則変更しない

本整理の初期フェーズでは、thin wrapper 本体は変更しない。理由は、`session_manager.py` と adapter の導入だけで主要な複雑性低減が得られ、wrapper 変更は SKILL.md への波及が大きいためである。

### テスト helper

wrapper テストの重複縮小は後段で行う。

想定 helper:

```python
def assert_wrapper_invokes_low_level(
    test_case,
    module,
    argv,
    expected_cmd_parts,
    returncode=0,
):
    ...
```

配置:

```text
tests/forge/helpers.py
```

既存 `tests/forge/helpers.py` があるため、そこへ追加する。

## skill_monitor.py 移行設計

### 削除判定

削除前に以下を実行して確認する。

```bash
rg -n "skill_monitor.py|SkillMonitorServer|YamlReader" plugins docs tests
```

runtime 参照が `plugins/` / `docs/` に残っている場合は削除しない。

### テスト観点移植

`test_skill_monitor.py` から移植すべき観点:

- YAML / Markdown 読み取り
- `refs.yaml` 検出
- `/session` response
- `/notify` response
- SSE broadcast
- session_dir 消失時の session_end

移植先:

| 観点                     | 移植先                    |
| ------------------------ | ------------------------- |
| YAML / Markdown 読み取り | `test_session_adapter.py` |
| `refs.yaml` 検出         | `test_session_adapter.py` |
| `/session` response      | `test_monitor_server.py`  |
| `/notify` response       | `test_monitor_server.py`  |
| SSE broadcast            | `test_monitor_server.py`  |
| session_end              | `test_monitor_server.py`  |

## 実装フェーズ

### Phase 1: session meta API

目的: `session.yaml` に浅い進行状態を安全に書けるようにする。

変更:

- `session_manager.py`
  - `update-meta` subcommand 追加
  - `update_session_meta()` 追加
  - atomic write helper 追加
  - `cmd_init()` に新規フィールド既定値追加
- `tests/forge/scripts/test_session_manager.py`
  - `update-meta` 成功
  - 未指定 field 保持
  - clear
  - invalid enum
  - missing session

受け入れ条件:

- 既存 `init`, `find`, `cleanup` のテストが無変更で通る
- `update-meta` は既存 session 固有 field を消さない

### Phase 2: monitor adapter

目的: monitor の読み取り責務を `server.py` から分離する。

変更:

- `monitor/session_adapter.py` 追加
- `tests/forge/scripts/test_session_adapter.py` 追加
- `monitor/server.py` の `_handle_session()` を adapter 呼び出しに変更

受け入れ条件:

- 既存 `/session` JSON の主要キーが維持される
- `derived` が追加される
- 欠損ファイルで落ちない
- parse error が adapter entry に閉じる

### Phase 3: writer integration

目的: AI / SKILL 手順を増やさず、既存 writer が粗い状態を更新する。

変更:

- `write_refs.py`
- `extract_review_findings.py`
- `merge_evals.py`
- `update_plan.py`
- `write_interpretation.py`

受け入れ条件:

- writer の stdout JSON は後方互換
- session meta 更新失敗は警告で、成果物保存成功を壊さない
- notify は従来どおり呼ばれる

### Phase 4: docs update

目的: 実装済み契約を仕様へ反映する。

変更:

- `plugins/forge/docs/session_format.md`
  - 正規責務表
  - `session.yaml` 追加フィールド
  - `update-meta` CLI
  - monitor adapter の位置付け
- 必要に応じて `DES-012_show_browser_design.md`
  - adapter 分離の追記

受け入れ条件:

- SKILL.md に直接 monitor 更新手順を追加していない
- public CLI path 互換方針が明記されている

### Phase 5: skill_monitor.py cleanup

目的: 旧 monitor 実装の重複を削除する。

実行条件:

- runtime 参照がない
- 必要テスト観点の移植済み
- ユーザ確認済み

受け入れ条件:

- `skill_monitor.py` と対応テスト削除後も全テストが通る
- docs に旧 entrypoint として残っていない

### Phase 6: wrapper test cleanup

目的: thin wrapper のテスト重複を減らす。

変更:

- `tests/forge/helpers.py` に wrapper helper 追加
- create 系 `test_find_session.py` / `test_init_session.py` の重複 assert を helper 化

受け入れ条件:

- wrapper 本体の挙動は変えない
- テストの意図がファイルごとに残る

## リスクと対策

| リスク                                           | 影響                   | 対策                                    |
| ------------------------------------------------ | ---------------------- | --------------------------------------- |
| `session.yaml` 更新失敗で writer が失敗する      | 主作業が壊れる         | meta 更新失敗は警告扱い                 |
| `server.py` adapter 化で `/session` 互換が壊れる | monitor UI が壊れる    | adapter テストで主要キーを固定          |
| `plan.yaml` と `session.yaml` に状態が二重化する | 正規情報源が曖昧になる | `session.yaml` に item state を入れない |
| wrapper 削除で SKILL.md が複雑化する             | AI 手順が不安定になる  | wrapper は初期フェーズで削除しない      |
| `skill_monitor.py` 削除で隠れ参照が壊れる        | runtime failure        | `rg` 確認とユーザ承認を必須化           |

## テスト詳細

### `test_session_manager.py`

追加ケース:

- `test_update_meta_adds_shallow_fields`
- `test_update_meta_preserves_existing_fields`
- `test_update_meta_updates_last_updated`
- `test_update_meta_clears_waiting_reason_when_waiting_none`
- `test_update_meta_rejects_invalid_phase_status`
- `test_update_meta_rejects_invalid_waiting_type`
- `test_update_meta_missing_session_dir`
- `test_update_meta_missing_session_yaml`

### `test_session_adapter.py`

追加ケース:

- `test_build_monitor_session_empty_dir`
- `test_build_monitor_session_reads_session_yaml`
- `test_build_monitor_session_reads_review_files`
- `test_build_monitor_session_reads_refs_yaml`
- `test_build_monitor_session_reads_refs_dir`
- `test_build_monitor_session_adds_derived_from_session_yaml`
- `test_build_monitor_session_counts_plan_items`
- `test_build_monitor_session_handles_yaml_parse_error`
- `test_build_monitor_session_preserves_legacy_keys`

### `test_monitor_server.py`

追加 / 変更ケース:

- `/session` が adapter を呼ぶ
- `/session` に `derived` が含まれる
- adapter error が 500 ではなく entry error で返る
- notify / heartbeat 既存挙動が維持される

### writer tests

各 writer で追加する観点:

- session meta 更新 helper が呼ばれる
- helper 失敗時も既存 stdout JSON が維持される
- warning が stderr に出る

## 完了条件

本詳細設計の完了条件は以下である。

- `session.yaml` の浅い進行状態が低レベル API で更新できる
- monitor の session 読み取りが adapter に分離されている
- `/session` レスポンス互換が維持されている
- review item state は `plan.yaml` だけが保持している
- writer script は AI 手順追加なしで粗い進行状態を更新している
- `skill_monitor.py` 削除可否が判断可能な状態になっている
- thin wrapper の削除を前提としない整理になっている

## 実装しないこと [MANDATORY]

**NEVER** 以下を本設計の実装中に行ってはいけない。

- `session_state.yaml` を追加する
- `.forge/sessions/` へ保存場所を移す
- `plan.yaml` の `items[]` を `session.yaml` へ複製する
- public CLI path をユーザ確認なしで rename / move する
- thin wrapper をユーザ確認なしで削除する
- `/session` JSON の既存主要キーを削除する
- monitor に session file 生成責務を持たせる

## 結論

詳細実装は、まず `session_manager.py update-meta` と `monitor/session_adapter.py` に集中する。この 2 点で、正規状態を増やさずに session の粗い進行状態と monitor reader の複雑さを整理できる。

thin wrapper は複雑さの主因ではなく、SKILL.md を安定させるための意図的な薄い層である。したがって初期実装では維持し、テスト重複だけを後段で縮小する。
