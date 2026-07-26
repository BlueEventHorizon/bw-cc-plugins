# 実装側キャプチャ（Emulator / Simulator）

実装画面を Emulator / Simulator でキャプチャし、Figma やコードと突き合わせるための実装側手順。
現時点では Android Emulator + stub flavor に対応する。iOS Simulator は拡張予定。

## 二軸ルール（最重要）

| 判定したいこと                                                    | 主軸                                                       | スクショの役割                                             |
| ----------------------------------------------------------------- | ---------------------------------------------------------- | ---------------------------------------------------------- |
| **値が一致しているか**（色 hex / px / font / radius）             | **Figma 仕様値 ↔ コード値の数値突き合わせ**（MCP or REST） | 使わない（8px・`#3B82F6` vs `#3C82F6` は目視不可）         |
| **要素が実際に描画されているか**（有無・visible・レイアウト崩れ） | **スクショ（実描画）**                                     | これが基準（node ツリーの `visible=false` は当てにしない） |

数値はテキスト比較、見た目（有無・崩れ）はスクショ。両方を使い分ける。

## このプロジェクトの前提値（Android / stub）

| 項目               | 値                                                                     |
| ------------------ | ---------------------------------------------------------------------- |
| フレーバー         | `stub`（起動: `--dart-define-from-file=flavor/stub.json`）             |
| applicationId      | `com.freaks.freaksstoreapp.dev`（`appIdAndroid` + suffix `.dev`）      |
| 起動コンポーネント | `com.freaks.freaksstoreapp.dev/com.freaks.freaksstoreapp.MainActivity` |
| エミュレータ解像度 | 1080×2400 / density 420（Figma 基準幅 390dp。1080/390≒2.77 倍）        |

起動コンポーネントや解像度が変わったら、次で再取得する。

```bash
adb shell cmd package resolve-activity --brief com.freaks.freaksstoreapp.dev
adb shell wm size
```

## 内部スクリプト

この節は `capture-emulator-screen` Skill の内部実装向け。呼び出し元 Skill は scripts を直接実行せず、必ず `capture-emulator-screen` Skill を呼び出す。

### デバイス選択ルール

`ANDROID_SERIAL` 未指定の場合は、最初に `adb devices` で接続デバイスを確認する。

| 接続デバイス数 | 動作                                                                                     |
| -------------- | ---------------------------------------------------------------------------------------- |
| 0 台           | キャプチャ不可として中断し、Emulator / Simulator の起動を依頼する                        |
| 1 台           | その serial を対象デバイスとして固定する                                                 |
| 2 台以上       | 勝手に先頭を選ばず、AskUserQuestion（Cursor では AskQuestion）でユーザーに選択してもらう |

複数台ある場合は、各候補について次を確認して選択肢に含める。

```bash
adb devices
adb -s <serial> shell wm size
adb -s <serial> shell wm density
adb -s <serial> shell cmd package resolve-activity --brief com.freaks.freaksstoreapp.dev
```

選択後は `ANDROID_SERIAL=<selected-serial>` を設定するか、全ての `adb` / `flutter` コマンドに `-s <selected-serial>` / `-d <selected-serial>` を明示する。
以後の起動・操作・キャプチャは同じ serial に固定し、途中で別デバイスへ切り替えない。

| スクリプト                            | 用途                                                              |
| ------------------------------------- | ----------------------------------------------------------------- |
| `scripts/run_stub.sh`                 | FIFO stdin 付きで stub を `flutter run` 起動（hot_reload の前提） |
| `scripts/hot_reload.sh [r\|R]`        | コード反映（FIFO 経由で `r`/`R` 送信）                            |
| `scripts/android-prepare.sh`          | アニメーション全オフ + stub アプリ前面起動（撮影安定化）          |
| `scripts/capture.sh <name> [out_dir]` | 画面キャプチャ（既定 `.figma_tmp/captures/<name>.png`）           |
| `scripts/adb_ui.sh <cmd> ...`         | 操作（dump/find/tap/swipe/text/key/launch/stop/wait）             |

`adb_ui.sh` の主な内部コマンド: `dump` / `find` / `tap` / `swipe` / `text` / `key` / `launch` / `stop` / `wait`。

環境変数で上書きできる: `APP_ID` / `ACTIVITY` / `ANDROID_SERIAL` / `OUT_DIR`。

## 操作の選び方（座標 vs integration_test）

| 方法                               | 長所                                | 短所                                                                                                 | 使う場面                     |
| ---------------------------------- | ----------------------------------- | ---------------------------------------------------------------------------------------------------- | ---------------------------- |
| `adb_ui.sh`（座標）                | 追加セットアップ不要・即試せる      | 解像度依存で脆い。Flutter は `find`（text/id）が効かないことが多い（キャンバス描画・Semantics 依存） | Android で手早く辿る         |
| `integration_test`（Key 指定）推奨 | 両 OS 共通・解像度非依存・CI 化容易 | 事前に Widget へ `Key` 付与 + テスト記述が必要                                                       | 操作フローを安定運用するとき |

Flutter 画面で `adb_ui.sh find` が空を返すのは正常。その場合はスクショで位置を見て `tap X Y`、または対象 Widget に `Key` を振って integration_test 化する。

## キャプチャ前の鉄則: 必ず最新コードを反映する [MANDATORY]

キャプチャは「いまデバイスで動いているビルド」を写すだけ。コード修正を反映せずに撮ったスクショで「直った」と判断してはならない。

- キャプチャ前に、必ず最新コードをデバイスへ反映する（hot reload / hot restart / full rebuild のいずれか）。
- 反映方法の使い分け:
  - **hot reload**（`flutter run` 中に `r`）: Widget の build 内の変更（色・余白・行高・文字など）。
  - **hot restart**（`R`）: 状態・`main`・Provider 初期化に絡む変更。
  - **full rebuild**（`flutter run` を起動し直す / `flutter build` + `adb install`）: アセット追加・slang(l10n) 生成・pubspec・ネイティブ変更。`melos run gen` を伴う変更は必ずフル反映。
- 反映の確証を取る。リロード後に「変更が出るはずの箇所」をキャプチャで確認する。
- 既存の起動アプリが編集前ビルドのままなら、そのキャプチャは現状把握の参考にしかならない。

### 反映の実行手段

内部では `run_stub.sh` で FIFO stdin 付き起動し、`hot_reload.sh` で `r` / `R` を送信する。
呼び出し元 Skill はこれらを直接実行せず、`capture-emulator-screen` Skill の結果だけを受け取る。

バックグラウンド起動した素の `flutter run` に後から `r` を送る手段はない。VM Service の `reloadSources` 単体ではソース変更を再コンパイルしないため、FIFO 経由または再起動が必要。

## ループ手順

1. コードを修正する。
2. 最新コードを反映する（hot reload / hot restart / full rebuild）。
3. 内部で `android-prepare.sh` を実行する。
4. 目的画面まで操作で遷移する（`adb_ui.sh tap/swipe/...`。Flutter は座標 or integration_test）。
5. 内部で `capture.sh <screen_name>` を使って撮影する。
6. 呼び出し元で Figma SS / 実装 SS / コードを突き合わせる。
7. 差分修正後は 2 に戻り、再反映・再キャプチャする。

## 既知の落とし穴

| 症状                         | 対策                                                                           |
| ---------------------------- | ------------------------------------------------------------------------------ |
| 古い画面が写る（遷移前撮影） | 遷移後に `adb_ui.sh wait 1` 等で待つ                                           |
| アニメ中のぼやけ・中間状態   | `android-prepare.sh` でアニメーションスケールを 0 にする                       |
| 座標タップが別の場所         | 解像度固定（1080×2400）／座標を `dump` で再特定／integration_test へ移行する   |
| hot reload 未反映            | reload 完了を待つ。必要なら restart / full rebuild を選ぶ                      |
| `find` が常に空              | Flutter は Semantics 未公開のことあり。座標 or Key 指定にする                  |
| color 変換ミス               | Flutter は `Color(0xAARRGGBB)`（アルファ先頭）。line-height は `px ÷ fontSize` |

## 保存先

既定は `.figma_tmp/captures/`（gitignore 済み）。コミットしない。
Figma SS やデザイン仕様書と並べて、呼び出し元で比較する。

## 次フェーズ

- iOS Simulator（`xcrun simctl io booted screenshot`、`convertFlutterSurfaceToImage()` 分岐、座標操作は `idb` か integration_test）。
- `integration_test` フロー（`Key` 付与 + `flows/*_test.dart` + `flutter drive`）と `drive.sh` ラッパー。
- 画面 ⇔ Figma node-id 対応表（dev リンク優先・同名フレーム注意）。
