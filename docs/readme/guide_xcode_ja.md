# xcode 詳細ガイド

Xcode ビルド・テストツールキット。プラットフォームを自動判定して iOS/macOS プロジェクトをビルド・テスト。

## スキル詳細

### build

```
/xcode:build [scheme-name]
```

| 引数 | 説明 |
|------|------|
| `scheme-name` | スキーム名（省略時は `.xcodeproj` から自動検出） |

### test

```
/xcode:test [scheme-name] [test-target]
```

| 引数 | 説明 |
|------|------|
| `scheme-name` | スキーム名（省略時は自動検出） |
| `test-target` | テストターゲット（例: `LibraryTests/FooTests`。省略時は全テスト） |

## 動作要件

- Xcode（`xcodebuild` が PATH に存在）
- iOS テスト: Xcode Simulator
