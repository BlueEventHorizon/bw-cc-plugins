# ローカル開発・デバッグガイド

**作成日**: 2026-06-02
**目的**: プラグイン開発時のローカルデバッグ手順をまとめる
**適用範囲**: このリポジトリのコントリビューター

---

## 1. プラグインのローカルロード

### 1.1 両プラグインを同時にロードする（推奨） [MANDATORY]

forge と anvil を同時にデバッグする場合は `--plugin-dir` を複数指定する。

```bash
claude --plugin-dir ./plugins/forge --plugin-dir ./plugins/anvil
```

セッション起動後、すべての forge / anvil スキルが `/` コマンドとして使用可能になる。

### 1.2 単一プラグインのみロードする

特定プラグインだけ確認したい場合:

```bash
# forge のみ
claude --plugin-dir ./plugins/forge

# anvil のみ
claude --plugin-dir ./plugins/anvil
```

### 1.3 マーケットプレイス経由（配布後の動作確認）

```bash
/plugin marketplace add BlueEventHorizon/bw-cc-plugins
/plugin install forge@bw-cc-plugins
/plugin install anvil@bw-cc-plugins
```

> ローカル変更を反映するには `--plugin-dir` を使う。マーケットプレイス経由はリモートの公開版を取得する。

---

## 2. スキル動作の確認手順

### 2.1 起動後の確認

```
/forge:help        # forge スキル一覧
/anvil:commit      # anvil スキルの動作確認（例）
```

### 2.2 SKILL.md を編集した場合

セッションを再起動する（`--plugin-dir` オプション付きで再実行）。編集内容はセッション内では即時反映されない。

```bash
# セッションを終了して再起動
claude --plugin-dir ./plugins/forge --plugin-dir ./plugins/anvil
```

---

## 3. Python スクリプトの単体確認

SKILL.md から呼び出されるスクリプトは、Claude セッションを介さずに直接実行して動作確認できる。

```bash
# レビュー対象の自動検出
python3 plugins/forge/skills/review/scripts/resolve_review_context.py [対象パス]

# ディレクトリスキャン（メタデータ JSON 出力）
python3 plugins/forge/scripts/doc_structure/classify_dirs.py [プロジェクトルート]
```

`python3` が見つからない環境では `/opt/homebrew/bin/python3` を使う。

---

## 4. テスト実行

```bash
# 全テスト一括実行
python3 -m unittest discover -s tests -p 'test_*.py' -v

# 特定モジュールのみ
python3 -m unittest tests.forge.review.test_xxx -v
```

テストの配置ルールは `CLAUDE.md` の「Testing」セクションを参照。

---

## 5. フォーマット

```bash
dprint fmt      # JSON / TOML / Markdown / YAML に適用
dprint check    # 差分チェックのみ（CI 向け）
```

設定ファイル: `dprint.jsonc`

---

## 6. デバッグのポイント

### 6.1 スキルが認識されない

- `--plugin-dir` のパスが正しいか確認（`./plugins/forge` のように相対パスで指定）
- `plugins/{plugin}/.claude-plugin/plugin.json` が壊れていないか確認
- `plugins/{plugin}/skills/{skill}/SKILL.md` の frontmatter `user-invocable: true` を確認

### 6.2 スクリプトが期待した動作をしない

コード読解による推論で 2〜3 回修正しても解決しない場合は `print()` / 変数ダンプで実際の状態を観測する。観測後にログを除去すること（`CLAUDE.md` Debugging セクションも参照）。

### 6.3 スキル間の連携を確認したい

`--plugin-dir` で両プラグインをロードした状態で、実際のユーザー操作をトレースする。スキルが別スキルを `Skill` ツール経由で呼び出す場合も同一セッション内で解決される。

---

## 7. 参考

- `CLAUDE.md` — リポジトリ全体の規約・構成説明
- `docs/rules/skill_authoring_notes.md` — SKILL.md 作成時の留意点
- `docs/rules/implementation_guidelines.md` — 実装ガイドライン
