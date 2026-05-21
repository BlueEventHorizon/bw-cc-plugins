### 🔴 Critical / 致命的問題

（該当 finding が無い場合は `（なし）` と書く。priority サブセクションも `（なし）` の場合は省略可。severity 見出しは必ず残す）

#### P1 (ルール合致)

1. **[問題名]**: 具体的な説明
   - priority: P1
   - severity: critical
   - severity_source: {委譲先 principles パス} §{該当節}
   - recommendation: fix
   - target: {target_file}:{行範囲}
   - rule: {ssot_refs[].doc_path} §{該当節}

#### P2 (矛盾・齟齬)

2. **[問題名]**: 具体的な説明
   - priority: P2
   - severity: critical
   - severity_source: {委譲先 principles パス} §{該当節}
   - recommendation: fix
   - target: {target_file}:{行範囲}
   - rule: {ssot_refs[].doc_path} §{該当節}

#### P3 (不要な複雑化)

（なし）

### 🟡 Major / 品質問題

（該当 finding が無い場合は `（なし）` と書く。連番は severity セクションごとにリセットする）

#### P1 (ルール合致)

1. **[問題名]**: 具体的な説明
   - priority: P1
   - severity: major
   - severity_source: {委譲先 principles パス} §{該当節}
   - recommendation: fix
   - target: {target_file}:{行範囲}
   - rule: {ssot_refs[].doc_path} §{該当節}

#### P2 (矛盾・齟齬)

（なし）

#### P3 (不要な複雑化)

2. **[問題名]**: 具体的な説明
   - priority: P3
   - severity: major
   - severity_source: {委譲先 principles パス} §{該当節}
   - recommendation: create_issue
   - target: {target_file}:{行範囲}
   - rule: {ssot_refs[].doc_path} §{該当節}

### 🟢 Minor / 改善提案

（該当 finding が無い場合は `（なし）` と書く。連番は severity セクションごとにリセットする）

#### P1 (ルール合致)

（なし）

#### P2 (矛盾・齟齬)

（なし）

#### P3 (不要な複雑化)

1. **[提案名]**: 具体的な説明
   - priority: P3
   - severity: minor
   - severity_source: {委譲先 principles パス} §{該当節}
   - recommendation: skip
   - target: {target_file}:{行範囲}
   - rule: {ssot_refs[].doc_path} §{該当節}

### サマリー

- Critical: X 件 (P1: X / P2: X / P3: X)
- Major: X 件 (P1: X / P2: X / P3: X)
- Minor: X 件 (P1: X / P2: X / P3: X)

---

## フォーマット規約 [MANDATORY]

下流パーサ (`findings_parser.py` / `findings_renderer.py`) の安定動作のため、以下の規約に厳密に従うこと:

1. **severity 見出しは温存**: `### 🔴 Critical / 致命的問題` / `### 🟡 Major / 品質問題` / `### 🟢 Minor / 改善提案` の 3 セクションを必ず残す (該当 finding が無くても `（なし）` と書く)
2. **priority サブセクション (二軸表示)**: 各 severity セクション内で `#### P1 (ルール合致)` / `#### P2 (矛盾・齟齬)` / `#### P3 (不要な複雑化)` のサブセクションを使う。該当 finding が無い priority サブセクションは `（なし）` と書く (省略可)
3. **連番は severity セクションごとにリセット**: Critical 内の連番 (1, 2, …) と Major 内の連番 (1, 2, …) は独立。priority サブセクションを跨いでも連番は継続する (`findings_renderer.py` の二段ソート仕様と整合)
4. **finding ブロックは番号付きリスト形式**: `1. **[問題名]**: 説明` の形式で記述する。見出し形式 (`### 1. …`) は使わない
5. **必須フィールド**: 各 finding に `priority` / `severity` / `severity_source` / `recommendation` / `target` / `rule` を必ず付与する
6. **priority と severity は独立軸**: priority (P1/P2/P3) は観点の出所、severity (critical/major/minor) は修正緊急度。P1 で検出した違反が必ず critical とは限らない (DES-028 §4.1)
7. **severity ラベルは ASCII 固定**: `critical` / `major` / `minor`。絵文字 (🔴/🟡/🟢) はセクション見出しの装飾のみで使用し、finding 行の severity 値は ASCII に統一する
8. **severity_source 必須**: severity は委譲先 principles 側カタログから転記すること (reviewer は自ら判定しない)。`severity_source` フィールドに取得元 doc_path + 該当節を必ず記載する (FNC-411)
9. **recommendation 値域**: `fix` / `create_issue` / `skip` の 3 値。判定基準は criteria §3 判定ルールに従う
10. **DES-022 出力契約 3 原則を温存**: 見出し階層 / 番号採番 / コードブロック構造は変更しない
