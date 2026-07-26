# msg-sys

Claude / Codex 間のメッセージング用スクリプト群（`send.py` / `inbox.py` / `history.py` / `hooks/`）。

## フック登録

`.claude/settings.json` / `.codex/hooks.json` に、`git rev-parse --show-toplevel` でリポジトリルートを動的解決する形で登録する（session cwd がプロジェクトルートと一致する保証はなく、サブディレクトリから起動した場合は相対パス・cwd依存の解決が失敗するため。DES-034 §7）:

```
FORGE_MSG_PROJECT_ROOT="$(git rev-parse --show-toplevel)" bash "$(git rev-parse --show-toplevel)/plugins/forge/scripts/msg-sys/hooks/codex-check-inbox.sh"
```

Claude 側は同様に `hooks/claude-check-inbox.sh` を登録する。この方式は開発者・worktree に依存しない共通の値としてコミットできる（`git rev-parse` はどのクローン・worktreeでも実行時に自分のリポジトリルートを返す）。プロジェクトルートの固定絶対パスを埋め込んではならない。

### Codex 側の追加手順: hook の trust 登録 [必須]

Codex はプロジェクトローカルの `.codex/hooks.json` を、実行前に `/hooks` コマンドで明示的に信頼（trust）登録することを要求する。`.codex/hooks.json` を配置しただけでは hook は発火しない。各開発者がローカル環境で以下を実行すること:

```
/hooks
```

Codex 内でフック定義を確認し、`codex-check-inbox.sh` の Stop hook を trust する。`.codex/hooks.json` の内容（コマンド文字列のハッシュ）を変更した場合は再度 trust が必要になる。この trust 登録は各開発者のローカル状態であり、git にコミットされない。

## 注意: `FORGE_MSG_MAX_ROUND_TRIPS` 未設定時の挙動

`FORGE_MSG_MAX_ROUND_TRIPS` を設定しないままフックを登録すると、登録直後から**常に**人間通知モードへ降格し、自動継続（往復チェーンの自動継続）は一切発生しない（未設定＝往復0回時点で即座に上限到達扱いになるフェイルセーフ）。自動継続を有効にするには、登録前後で本環境変数に業務上適切な往復回数を設定すること（詳細は DES-034 §8 参照）。
