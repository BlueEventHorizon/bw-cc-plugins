---
name: build
description: |
  Xcodeプロジェクトをビルドし、エラーを報告する。iOS/macOS を自動判定。
  トリガー: "ビルド", "build", "ビルドして", "/xcode:build"
user-invocable: true
allowed-tools: Bash, Read, AskUserQuestion
argument-hint: "[scheme-name]"
---

# /xcode:build

Xcodeプロジェクトのフルビルドを実行する。

## コマンド構文

```
/xcode:build [scheme-name]
```

| 引数 | 内容 |
|-----|------|
| scheme-name | スキーム名（省略時は `.xcodeproj` から自動検出） |

---

## Step 1: プラットフォーム判定 [MANDATORY]

`Resources/XCConfig/Common.xcconfig` を Read し、`SDKROOT` の値でプラットフォームを判定する。

| SDKROOT | プラットフォーム | destination |
|---------|---------------|-------------|
| `iphoneos` | iOS | `generic/platform=iOS` |
| `macosx` | macOS | `platform=macOS` |

- ファイルが存在しない場合: AskUserQuestion で iOS / macOS を確認
- `SDKROOT` が見つからない、または上記以外の値: AskUserQuestion で確認

---

## Step 2: スキーム決定

1. `$ARGUMENTS` にスキーム名が指定されていればそのまま使用
2. 未指定の場合、プロジェクトルートの `.xcodeproj` ディレクトリ名から推定:

```bash
find . -maxdepth 1 -name "*.xcodeproj" -type d | head -1 | xargs -I{} basename {} .xcodeproj
```

検出できない場合は AskUserQuestion で確認。

---

## Step 3: ビルド実行

ビルドスクリプトを実行する。タイムアウトは **300000ms**（5分）を設定すること。

```bash
${CLAUDE_PLUGIN_ROOT}/skills/build/scripts/build.sh "{SCHEME}" "{DESTINATION}"
```

- `{SCHEME}`: Step 2 で決定したスキーム名
- `{DESTINATION}`: Step 1 で決定した destination

---

## Step 4: 結果報告

- **ビルド成功**: 成功を簡潔に報告
- **ビルド失敗**: スクリプト出力のエラー内容を分析し、修正案を提示
