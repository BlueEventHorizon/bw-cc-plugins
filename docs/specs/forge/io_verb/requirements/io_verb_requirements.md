# io_verb 要件定義: SKILL.md を script 詳細から解放する

## メタデータ

| 項目       | 値                                                                    |
| ---------- | --------------------------------------------------------------------- |
| 要件 ID    | REQ-001                                                               |
| feature ID | io_verb                                                               |
| 種別       | 要件定義（What のみ。手段は含まない）                                 |
| 作成日     | 2026-04-21                                                            |
| 対象       | forge の全 scripts（共有・SKILL 独自とも）と、それを呼び出す SKILL.md |
| 関連要件   | INV-001                                                               |

---

## 1. 背景

SKILL.md は AI が tool 呼び出しの都度ロードするコンテキストの一部であり、**常駐費用が高い**。ここに script 固有の情報（引数列挙、状態遷移規則、JSON スキーマ、誤用禁止警告など）が混入すると、AI の判断領域を圧迫し、タスクと無関係な認知負荷を生む。

現状の実測（forge プラグイン全体）:

**共有 scripts** (`plugins/forge/scripts/`):

| 配置                     | script                                                                                                                                        |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `scripts/session/`       | `update_plan.py` / `merge_evals.py` / `summarize_plan.py` / `read_session.py` / `write_interpretation.py` / `write_refs.py` / `yaml_utils.py` |
| `scripts/doc_structure/` | （forge 横断の doc 構造解決）                                                                                                                 |
| `scripts/monitor/`       | （session_end などの通知）                                                                                                                    |
| `scripts/` 直下          | `get_version_status.py` / `session_manager.py` / `skill_monitor.py`                                                                           |

**SKILL 独自 scripts** (`plugins/forge/skills/*/scripts/`):

| SKILL                | script                                                                           |
| -------------------- | -------------------------------------------------------------------------------- |
| review               | `resolve_review_context.py` / `extract_codex_output.py` / `run_review_engine.sh` |
| reviewer             | `extract_review_findings.py`                                                     |
| doc-structure        | `resolve_doc_structure.py`                                                       |
| next-spec-id         | `scan_spec_ids.py`                                                               |
| clean-rules          | `detect_forge_overlap.py`                                                        |
| setup-version-config | `scan_version_targets.py`                                                        |
| update-version       | `calculate_version.py` / `update_version_files.py`                               |

**SKILL.md → scripts の呼び出し関係**:

- 共有 scripts を呼ぶ SKILL.md: review / present-findings / fixer / evaluator / start-* 系
- 独自 scripts は各 SKILL.md から呼ばれる（review は共有 + 独自の両方を呼ぶ）
- 呼び出しは引数形式で SKILL.md に書かれており、script の CLI 変更は複数 SKILL.md の同期修正を要する
- 一部 SKILL.md には「別 script を直接呼ぶな」型の禁止警告が書かれており、script 側のガードと重複している

## 2. 目的

**AI に「どの script を呼ぶか」「どんな引数を組み立てるか」を考えさせない状態を作る。**

SKILL.md に「この場面ではこれを呼ぶ」という一意の指示が埋め込まれており、AI はそれをそのまま実行する。script 側は引数が最小化された形で提供され、AI は状態遷移ルールや flag 組合せを知る必要がない。

具体的には:

- SKILL.md の指示 = **呼ぶべき script** + **最低限必要な値（ID など）**
- AI は script の選択も、オプションの組み立ても行わない
- そのために**薄いラッパー script を operation 単位で増やす**（数の多さは問題にしない）
- ラッパーは原則**呼び出し元 SKILL の配下** (`plugins/forge/skills/{skill}/scripts/`) に置く
- 状態遷移・flag 合成・JSON スキーマは低レベル script 内部に閉じ、SKILL.md からは不可視にする

## 3. スコープ

### 3.1 含める

本要件で「作る/触る」対象は以下の 3 つに限る。

| 対象                                                                                                   |
| ------------------------------------------------------------------------------------------------------ |
| forge 全 SKILL.md の呼び出し記述の整理（flag 露出排除・禁止警告削除・引数最小化）                      |
| SKILL 配下への薄いラッパー script 追加（`plugins/forge/skills/{skill}/scripts/`、subprocess 委譲のみ） |
| 既存の配置ずれの是正（`extract_review_findings.py` 等の再判定）                                        |

### 3.2 含めない

以下は R7 [MANDATORY] により明示的にスコープ外とする。

| 非対象                                                                       | 理由                                                                   |
| ---------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| 低レベル script（`plugins/forge/scripts/` 配下）の変更・新規追加             | R7 [MANDATORY] により原則禁止。既存動作を維持する                      |
| R2 / R4 の実施強化（低レベル script 側の self-documenting / 誤用防御の強化） | 低レベル script に触らないため既存動作に委ねる。未達箇所は別要件で扱う |
| `plan.yaml` / `session.yaml` / `refs.yaml` のスキーマ変更                    | 本要件はスキーマに触れない                                             |
| 未実装機能（`fix_failed` / `last_error_*` 等）の導入                         | 仮想の敵で refactor しない                                             |
| 他プラグイン（anvil / doc-advisor / xcode）                                  | forge に閉じる。同じ問題があれば別要件で                               |

## 4. 要件

### R1: SKILL.md の clean state

SKILL.md に残してよい情報:

- AI が今なすべき操作の 1 行指示（例:「修正完了時は `mark_finding_fixed.py {session_dir} {id}` を呼ぶ」）
- AI の対話・判断戦略（例: 「critical は対話省略可」）

SKILL.md に書かない情報:

- 状態遷移の許容マトリクス
- エラー時の引数合成手順
- 出力 JSON のフィールドスキーマ
- 「別の script を直接呼ぶな」型の禁止警告
- 誤用シナリオの列挙
- flag の有無で挙動を分岐させる選択肢の提示（`--status` 値の候補列挙など）

### R1.1: 引数最小化

Script 呼び出しの引数は、AI がその時点で自然に持っている値だけで構成する:

- 必須: operation を特定する最小情報（session_dir / ID など）
- 任意: AI が文脈から自然に生成できる短い文字列（skip の理由など）
- **排除**: status 値の選択、flag の組合せ、ファイル一覧の組立

理想形は `script {session_dir} {id}` のみで完結すること。意味論が異なる operation は別 script に分離する（同一 script 内を flag で切り替える設計を避ける）。

### R2: Script の self-documenting

Script 側が以下を単独で提供する:

- `--help` だけで開発者・AI が正しく使える help 出力
- 誤用時は非 0 exit code と、次のアクションを示すエラーメッセージ
- 不正な状態遷移・引数組合せは script 内部で検証
- エラーメッセージは「何を使うべきだったか」を肯定形で提示する

> **本要件では実施対象外**: R2 は低レベル script 側の品質を記す目標状態。R7 [MANDATORY] により低レベル script を変更しないため、本要件では既存動作を維持する（未達箇所は別要件で扱う）。新規ラッパーは subprocess 委譲のみで、独自の help / ガード / エラーメッセージを持たない。

### R3: AI に選択させない

AI が「何を呼ぶか」「どのオプションを組み合わせるか」を判断する余地を残さない:

- SKILL.md の各場面で呼ぶべき script は **1 つに確定**している
- 複数候補から AI が選ぶ構造を作らない
- 同じ script の中で flag によって operation が分岐する構造は避ける（別 script にする）

命名は「AI の俯瞰」のためには不要。AI は SKILL.md の指示に従うだけで、script 名を自力で検索することはない。ただし**開発者の保守性**のための命名改善は R2（self-documenting）の範囲で扱う。

### R4: 誤用防御の配置

誤用の再発防止は以下の順で責務を配置する:

1. Script 内部のガード（最優先、必ず実装）
2. Script のエラーメッセージ（ヒント提示）
3. Script の docstring / help
4. `plugins/forge/docs/` 配下の Just-In-Time 参照文書

SKILL.md での禁止警告は**使わない**。警告文は AI に禁止対象の存在を認識させ、逆効果になりうる。

> **本要件での実施範囲**:
>
> - 責務配置 1〜3（低レベル script 側のガード・エラー・help）は**実施対象外**。R7 [MANDATORY] により低レベル script を変更しないため、既存動作を維持する（未達箇所は別要件で扱う）。
> - 責務配置 4（JIT 参照文書）は必要に応じて追加可。
> - **「SKILL.md での禁止警告は使わない」部分は本要件で実施する**（既存の禁止警告を SKILL.md から削除する）。

### R5: 既存互換

- 既存 SKILL.md / script の挙動を段階的・非破壊に変える
- 途中段階でも review パイプラインが完走可能
- 旧 CLI は deprecation 期間を設ける

### R6: 実測ベース

- 仮想の敵（未実装機能の問題）を refactor の動機にしない
- 対象は実際に SKILL.md 上に存在するノイズ（flag 露出・禁止警告・多引数呼び出し等）に限る。未確認の問題を想定して拡張しない
- 合否は目視レビュー + grep による Yes/No 判定。定量的な baseline 固定・再計測による達成率判定は行わない（判定精度に対して複雑性が過剰）

### R7: 配置基準（2 分類 + 例外層）

script は以下の 2 分類に限る:

- **低レベル script** (`plugins/forge/scripts/{domain}/`)
  - 実体ロジックを持つ。複数ラッパーから再利用される
  - CLI 表面も持つが、SKILL.md から直接呼ばない前提で設計してよい
- **SKILL 固有ラッパー** (`plugins/forge/skills/{skill}/scripts/`)
  - 単一 SKILL からのみ呼ばれる、1 operation = 1 script の薄い wrapper
  - 引数を最小化し、低レベル script に委譲する
  - **ラッパーの大多数はこれに該当する**

**「共有ラッパー」は作らない**:

複数 SKILL から同じ operation を呼びたくなった場合、それは wrapper ではなく**低レベル script の責務**である。その operation を低レベル側に吸収し、各 SKILL はそれぞれ薄いラッパーで委譲する（またはラッパーなしで低レベルを直接呼ぶ）。中間に「共有ラッパー層」を作ると配置判断が複雑化し、二重実装の温床になる。

**例外層: 複合ラッパー**:

上記 2 分類に加え、**例外層として「複合ラッパー」を認める**。複合ラッパーは単一 SKILL に閉じた一括操作のみを担う wrapper であり、以下の要件をすべて満たす場合に限り追加を許容する:

- **単一 SKILL に閉じた一括操作のみ**: 配置は `plugins/forge/skills/{skill}/scripts/` とし、他 SKILL から呼ばせない（汎用化禁止）。上記の「共有ラッパー」禁止原則と整合する
- **低レベル CLI の出力スキーマを再利用するのみ**（新規スキーマ定義禁止）: 複合ラッパー内で扱う JSON スキーマは低レベル CLI が stdout/stdin で扱う既存スキーマのみ。新しい JSON スキーマやフォーマットを定義してはならない
- **ビジネスロジックを持たない**（連鎖制御のみ）: 複数 subprocess を順に呼ぶ制御のみを記述し、状態判定・値変換・検証等の業務論理は低レベル側に残す
- **本要件では `skip_all_unprocessed.py` のみ該当**: 現時点でこの例外に該当する wrapper は 1 本のみ。今後追加する場合は上記要件をすべて満たすことを設計書で明示する

**低レベル script は原則変更しない [MANDATORY]**:

本要件の実施コストを最小化するため、低レベル script への変更は原則禁止とする:

- ラッパーは既存 CLI を **subprocess 呼び出しするだけ**で実装する
- 低レベル script への新 API 追加（use-case 関数・共通ヘルパ等）は行わない
- 既存 CLI の引数仕様・動作も変更しない

**唯一の例外**: 既存 CLI に明確なバグがあり、ラッパーの動作に直接支障をきたす場合のみ最小限の修正を許容する。その場合は設計書で明示する。

**既存の配置ずれの是正**:

- `skills/reviewer/scripts/extract_review_findings.py` は review SKILL から呼ばれている。本要件の適用時に配置を再判定する

## 5. 成功基準

すべて**定性判定**（Yes/No）で合否を決める。定量目標（X% 削減・平均 ≤ N 等）は持たない。

| 判定項目                                                         | 合格条件                                                                  | 判定方法               |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------- | ---------------------- |
| SKILL.md から低レベル CLI への `--` internal flag 露出           | SKILL.md の Python / Bash スクリプト呼び出し行に internal flag が残らない | 目視レビュー + grep    |
| SKILL.md 内「〜を直接呼ぶな」型警告                              | 残存しない（ラッパー側に誤用防御を移譲済み）                              | 目視レビュー           |
| SKILL.md から呼ぶ script の引数形状                              | 位置引数のみ（session_dir + ID 等）。flag を AI が選ばない                | 目視レビュー           |
| 同一場面で AI が選択する script 候補                             | 常に 1（シナリオごとに呼び出し先が一意）                                  | 目視レビュー           |
| script の `--help` のみで使い方が完結する（開発者視点）          | `--help` 出力に引数意味・使用例・想定呼び出し元が含まれる                 | 手動確認               |
| 誤用時の script エラーメッセージ                                 | 次アクションを肯定形で提示する                                            | 代表的誤用ケースで確認 |
| review パイプライン 1 サイクル                                   | 完走する                                                                  | 実機で monitor 確認    |
| start-requirements / start-design / start-plan / start-implement | 完走する                                                                  | 実機確認               |

数値目標（baseline 固定値との比較による達成率判定等）は採用しない（設計書 §9 も同方針）。

## 6. 非目標

| 非目標                                                                       | 対応                                                        |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------- |
| ラッパー script 数の最小化                                                   | 多くてよい。引数削減を優先                                  |
| AI による script の自律選択 / 命名からの推論                                 | **設計上むしろ排除する**                                    |
| 共有ラッパー層の新設                                                         | 作らない。共有したくなったら低レベルに格上げする            |
| 統一エントリーポイント（単一 wrapper から全 operation を dispatch する構造） | 単一 script 内で operation 分岐するなら本要件の趣旨に反する |
| subagent 化の一律禁止                                                        | 要件としては排除しない。設計で判断                          |
| スケジュール・スライス分解                                                   | 設計書・計画書で決める                                      |
| 定量目標値の固定                                                             | 設計書で具体化                                              |

## 7. 制約

- **低レベル script は原則変更しない**（R7 参照）。ラッパー追加のみでスコープを完結させる
- Python 標準ライブラリのみ（CLAUDE.md: 外部依存なし）
- `plugins/forge/skills/*/scripts/` 配下に追加する Python スクリプトはテスト必須（CLAUDE.md: MANDATORY、SKILL.md はテスト対象外）
- `.claude/` 配下のローカルスキル・スクリプトはテスト対象外
- ドキュメントは日本語（CLAUDE.md: プロジェクト既定）
- 既存セッションファイル（進行中の review セッション）の継続可能性を保つ

## 8. 関連文書

- [CLAUDE.md](../../../../../CLAUDE.md) — プロジェクト憲章
- [DES-011 セッション管理設計書](../../design/DES-011_session_management_design.md) — 現行スキーマ
- `plugins/forge/docs/session_format.md` — セッションファイル現行仕様
