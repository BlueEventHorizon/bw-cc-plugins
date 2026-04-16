# xcode Detailed Guide

Xcode build and test toolkit. Auto-detects platform for iOS/macOS projects.

## Skill Details

### build

```
/xcode:build [scheme-name]
```

| Argument | Description |
|----------|-------------|
| `scheme-name` | Scheme name (omit for auto-detection from `.xcodeproj`) |

### test

```
/xcode:test [scheme-name] [test-target]
```

| Argument | Description |
|----------|-------------|
| `scheme-name` | Scheme name (omit for auto-detection) |
| `test-target` | Test target (e.g. `LibraryTests/FooTests`, omit for all tests) |

## Requirements

- Xcode with `xcodebuild` in PATH
- iOS testing: Xcode Simulator
