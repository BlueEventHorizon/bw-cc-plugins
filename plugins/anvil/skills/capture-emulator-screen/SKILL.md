---
name: capture-emulator-screen
description: Android Emulator / iOS Simulator 上で実装済みアプリ画面を起動・反映・操作・キャプチャする。現時点では Android/stub 対応、iOS は拡張予定。実装後レビュー、Figma との見た目突合、Emulator/Simulator のスクリーンショット取得が必要なときに使用する。
user-invocable: true
argument-hint: "<screen_name> [到達手順 / 表示状態]"
allowed-tools: Bash(adb *), Bash(flutter *), Bash(dart *), Bash(melos *), Bash(python3 *), Bash(bash *), Bash(sleep *), Bash(ls *), Bash(mkdir *), Read, Glob, Grep, AskUserQuestion
---

# capture-emulator-screen

Android Emulator / iOS Simulator 上で、実装済みアプリの画面を最新コード反映後にキャプチャする。

## 責務

- 実装アプリを Emulator / Simulator で起動する
- hot reload / hot restart / full rebuild を使い分けて最新コードを反映する
- 対象画面まで操作し、安定した状態でスクリーンショットを保存する
- キャプチャの信頼度（反映方法、端末、到達手順、未確認事項）を呼び出し元へ返す

## 非責務

- Figma screenshot の取得
- YAML プレビュー画像の生成
- Figma / 実装 / コードの差分判定
- コード修正

差分判定や修正は、呼び出し元の `impl-issue` や `sync-screen-design` が担当する。

## 現対応

- Android Emulator + stub flavor
- 既定の保存先: `.figma_tmp/captures/`
- iOS Simulator は未実装。将来 `xcrun simctl io booted screenshot` と integration_test フローで拡張する。

## 必須ルール

キャプチャ前に、必ず最新コードが Emulator / Simulator に反映されていることを確認する。
編集前ビルドのスクリーンショットは、修正後レビューの根拠にしてはいけない。

Android Emulator / iOS Simulator が複数起動している場合は、勝手に先頭デバイスを選ばない。
必ず候補（serial / 解像度 / density / アプリインストール状態）を確認し、AskUserQuestion（Cursor では AskQuestion）でユーザーに対象デバイスを選択してもらう。
選択後は `ANDROID_SERIAL` または `adb -s <serial>` で対象を固定し、以後の起動・操作・キャプチャを同じデバイスに対して実行する。

## 公開インターフェース

他の Skill は、この Skill 名（`capture-emulator-screen`）を指定して呼び出す。
呼び出し元は、この Skill 配下のスクリプトを直接実行してはいけない。

入力として、対象画面名、到達手順、表示したい状態、必要な反映方法（hot reload / hot restart / full rebuild）を受け取る。
出力として、保存先、反映方法、端末、到達手順、未確認事項を呼び出し元に返す。

## 内部手順

詳細は [docs/simulator-capture.md](docs/simulator-capture.md) を読む。
この Skill の内部実装として、必要に応じて自身の `scripts/` 配下のスクリプトを使う。

## 出力形式

呼び出し元へ次を簡潔に報告する。

```markdown
実装キャプチャ:

- 画像: `.figma_tmp/captures/<screen_name>.png`
- 対象: Android Emulator / stub
- コード反映: hot reload | hot restart | full rebuild | 未確認
- 到達手順: <実行した操作>
- 未確認事項: <あれば>
```
