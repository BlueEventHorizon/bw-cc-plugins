#!/usr/bin/env python3
"""review スキルの引数解析。

Usage:
    python3 parse_review_args.py "<args_string>"

出力（JSON）:
    {
      "status": "ok",
      "review_type": "code",
      "targets": ["src/"],
      "engine": "codex",
      "auto_count": 0,
      "auto_critical": false
    }
"""

import json
import sys

VALID_TYPES = ('requirement', 'design', 'code', 'plan', 'generic')
VALID_ENGINES = ('codex', 'claude')


def parse_review_args(args_string):
    """review スキルの引数を解析する。

    Args:
        args_string: 引数文字列（例: "code src/ --auto 3 --claude"）

    Returns:
        dict: 解析結果

    Raises:
        ValueError: 不正な引数
    """
    tokens = args_string.strip().split()

    if not tokens:
        raise ValueError("引数がありません。種別（code/requirement/design/plan/generic）を指定してください")

    review_type = None
    engine = 'codex'  # デフォルト
    auto_count = 0
    auto_critical = False
    targets = []

    i = 0
    while i < len(tokens):
        token = tokens[i]

        # エンジン指定
        if token == '--codex':
            engine = 'codex'
            i += 1
            continue
        if token == '--claude':
            engine = 'claude'
            i += 1
            continue

        # auto-critical（--auto の前にチェック）
        if token == '--auto-critical':
            auto_count = 1
            auto_critical = True
            i += 1
            continue

        # auto モード
        if token == '--auto':
            if i + 1 < len(tokens) and tokens[i + 1].isdigit():
                auto_count = int(tokens[i + 1])
                i += 2
            else:
                auto_count = 1
                i += 1
            continue

        # 種別判定（最初の非フラグトークン）
        if review_type is None:
            lower = token.lower()
            if lower in VALID_TYPES:
                review_type = lower
                i += 1
                continue
            else:
                raise ValueError(
                    f"不正な種別: '{token}'。"
                    f"有効な種別: {', '.join(VALID_TYPES)}"
                )

        # 残りは対象パス
        targets.append(token)
        i += 1

    if review_type is None:
        raise ValueError("種別が指定されていません。種別（code/requirement/design/plan/generic）を指定してください")

    return {
        "review_type": review_type,
        "targets": targets,
        "engine": engine,
        "auto_count": auto_count,
        "auto_critical": auto_critical,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: parse_review_args.py \"<args_string>\"", file=sys.stderr)
        sys.exit(1)

    args_string = ' '.join(sys.argv[1:])

    try:
        result = parse_review_args(args_string)
        result["status"] = "ok"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0)
    except ValueError as e:
        error = {"status": "error", "error": str(e)}
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
