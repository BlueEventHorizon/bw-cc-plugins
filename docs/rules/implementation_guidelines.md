# 実装ガイドライン

プラグインの Python スクリプトおよび SKILL.md 実装時のルールを定義する。

---

## テスト必須 [MANDATORY]

`plugins/` 配下の Python スクリプトにはテストが必須。

### 対象と例外

| 対象 | テスト必須 | 理由 |
|------|-----------|------|
| `plugins/` 配下の `.py` | 必須 | プラグインとして配布されるコード |
| SKILL.md | 例外 | AI の振る舞いを記述するもので自動テスト困難 |
| `.claude/` 配下の `.py` | 対象外 | ローカルスキル・プロジェクト固有スクリプト |

### テストの配置

`tests/` にプラグイン名・スキル名で分類して配置する:

```
tests/
├── common/                 # プラグイン横断（マニフェスト整合性等）
├── forge/
│   ├── review/             # plugins/forge/skills/review/scripts/ のテスト
│   └── scripts/            # plugins/forge/scripts/ のテスト
└── {plugin}/               # 新プラグイン追加時も同構造
```

命名規則: `test_{module}.py`（例: `test_session_manager.py`）

### テスト実行

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

---

## SKILL.md にインラインスクリプトを書かない [MANDATORY]

処理ロジックを SKILL.md 内にインラインで記述してはならない。

### 理由

AI が SKILL.md 内のスクリプトを解釈して実行する際、コードを勝手に改変・省略して失敗するリスクがある。独立したスクリプトファイルであれば、AI はそのまま実行するだけで済む。

### 正しいパターン

処理ロジックは独立した Python スクリプトファイルとして実装し、SKILL.md からはそのスクリプトを呼び出す。

```markdown
# ❌ NG — SKILL.md 内にロジックを記述

以下の Python コードを実行してデータを集計する:

    import json
    data = json.load(open('plan.yaml'))
    # ... 50行のロジック ...

# ✅ OK — 外部スクリプトを呼び出す

以下のスクリプトを実行して指摘事項を抽出する:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/extract_review_findings.py" {review_md} {plan_yaml}
```

### スクリプトの配置

| 配置先 | 用途 |
|--------|------|
| `plugins/{plugin}/skills/{skill}/` | スキル固有のスクリプト |
| `plugins/{plugin}/scripts/` | プラグイン共通のスクリプト |

SKILL.md からの参照には `${CLAUDE_SKILL_DIR}` または `${CLAUDE_PLUGIN_ROOT}` を使用する。
