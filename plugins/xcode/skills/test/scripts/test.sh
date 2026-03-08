#!/bin/bash

# Xcodeプロジェクト テストスクリプト（SKILL用）
#
# 使用方法:
#   test.sh <scheme> <destination> [--only-testing <target>] [--sdk <sdk>]
#
# 例:
#   test.sh TemplateApp "platform=macOS"
#   test.sh TemplateApp "platform=macOS" --only-testing LibraryTests/FooTests
#   test.sh MyApp "id=DEVICE-UUID" --sdk iphonesimulator

set -e

# スクリプト自身の位置からプロジェクトルートを逆算
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$PROJECT_ROOT"

SCHEME="$1"
DESTINATION="$2"
shift 2 || true

# オプション引数の解析
ONLY_TESTING=""
SDK_OPTION=""
while [ $# -gt 0 ]; do
    case "$1" in
        --only-testing)
            ONLY_TESTING="-only-testing:$2"
            shift 2
            ;;
        --sdk)
            SDK_OPTION="-sdk $2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

if [ -z "$SCHEME" ] || [ -z "$DESTINATION" ]; then
    echo "❌ Error: scheme と destination は必須です"
    echo "Usage: test.sh <scheme> <destination> [--only-testing <target>] [--sdk <sdk>]"
    exit 1
fi

# 一時ファイルのクリーンアップ（異常終了時にも実行）
TEST_LOG=$(mktemp)
FAILED_TESTS_LOG=$(mktemp)
trap 'rm -f "$TEST_LOG" "$FAILED_TESTS_LOG"' EXIT

echo "Xcode Test"
echo "===================================="
echo "Scheme: $SCHEME"
echo "Destination: $DESTINATION"
[ -n "$ONLY_TESTING" ] && echo "Target: $ONLY_TESTING"
[ -n "$SDK_OPTION" ] && echo "SDK: $SDK_OPTION"

# 1. テスト実行（ログ保存 + フィルタリング）
echo ""
echo "Step 1: Running tests..."
echo "--------------------------------"

xcodebuild test \
    -scheme "$SCHEME" \
    -destination "$DESTINATION" \
    $SDK_OPTION \
    $ONLY_TESTING \
    -skipPackagePluginValidation \
    2>&1 | tee "$TEST_LOG" > /dev/null || true

# フィルタリング表示（ログ後処理）
grep -E "(Test case|error:|warning:|BUILD FAILED|BUILD SUCCEEDED|passed|failed)" "$TEST_LOG" | head -100 || true

# 2. テスト結果の解析（ログファイルから確実に判定）
echo ""
echo "===================================="
echo "Test Results"
echo "===================================="

# 失敗したテストを抽出
grep "Test case.*failed" "$TEST_LOG" > "$FAILED_TESTS_LOG" 2>/dev/null || true

# 成功と失敗をカウント
FAILED_COUNT=$(wc -l < "$FAILED_TESTS_LOG" | xargs)
PASSED_COUNT=$(grep -c "Test case.*passed" "$TEST_LOG" 2>/dev/null || echo "0")

echo "📊 テスト実行結果:"
echo "   ✅ 成功: $PASSED_COUNT tests"
echo "   ❌ 失敗: $FAILED_COUNT tests"

# 失敗したテストの詳細を表示
if [ "$FAILED_COUNT" -gt 0 ]; then
    echo ""
    echo "❌ 失敗したテスト:"
    cat "$FAILED_TESTS_LOG" | sed 's/^/   /'

    echo ""
    echo "💡 失敗の詳細（エラーメッセージ）:"
    grep -B 2 -A 5 "failed" "$TEST_LOG" | grep -E "(error|failed|Expected|Actual)" | head -30 | sed 's/^/   /'
fi

# 3. 結果サマリー
echo ""
echo "===================================="
echo "Test Summary"
echo "===================================="

if [ "$FAILED_COUNT" -eq 0 ] && grep -q "TEST SUCCEEDED\|passed" "$TEST_LOG"; then
    echo "✅ All tests passed successfully!"
    exit 0
else
    echo "❌ Tests failed: $FAILED_COUNT test(s)"
    exit 1
fi
