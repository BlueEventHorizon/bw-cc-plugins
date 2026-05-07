#!/usr/bin/env python3
"""evaluator の整形結果で `review_{perspective}.md` を全面書き換えする。

evaluator から呼ばれ、reviewer 原文を `.raw.md` にバックアップしてから
stdin の Markdown で `review_{perspective}.md` を全面上書きする。
present-findings もユーザー対話後の更新で呼び出す(その際 `.raw.md` は保護される)。

Usage:
    cat <<'EOF' | python3 write_interpretation.py <session_dir> --perspective <name>
    # evaluator 評価(...)
    (本文)
    EOF

動作:
    1. {session_dir}/review_{perspective}.md が存在しない場合はエラー
    2. {session_dir}/review_{perspective}.raw.md が存在しない場合:
       - review_{perspective}.md を .raw.md にコピー(初回バックアップ)
       - backup_created = true
    3. 既に .raw.md が存在する場合:
       - .raw.md は保護(再作成しない)
       - backup_created = false
    4. stdin の内容で review_{perspective}.md を上書き

出力 (stdout JSON):
    {"status": "ok", "path": ".../review_{perspective}.md",
     "backup_path": ".../review_{perspective}.raw.md", "backup_created": true|false}
"""

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR.parent))

from session.store import SessionStore  # noqa: E402


def write_interpretation(session_dir, perspective, content):
    """review_{perspective}.md を全面書き換えする。

    Args:
        session_dir: セッションディレクトリパス
        perspective: perspective 名
        content: 書き込む Markdown 本文

    Returns:
        dict: {"path", "backup_path", "backup_created"}

    Raises:
        FileNotFoundError: review_{perspective}.md が存在しない
        ValueError: content が空
    """
    if not content:
        raise ValueError("stdin の内容が空です")

    session_path = Path(session_dir)
    target = session_path / f"review_{perspective}.md"
    backup = session_path / f"review_{perspective}.raw.md"
    store = SessionStore(session_path)

    if not target.exists():
        raise FileNotFoundError(
            f"review_{perspective}.md が見つかりません: {target}"
        )

    backup_created = False
    if not backup.exists():
        # バックアップもアトミックに: copyfile → rename パターンを使う代わりに、
        # shutil.copyfile は書き込みがアトミックでないため tmp 経由で行う
        with open(str(target), "r", encoding="utf-8") as f:
            raw_content = f.read()
        store.write_text(backup.name, raw_content)
        backup_created = True

    store.write_text(
        target.name,
        content,
        meta={"active_artifact": target.name},
    )

    return {
        "path": str(target),
        "backup_path": str(backup),
        "backup_created": backup_created,
    }


def main():
    parser = argparse.ArgumentParser(
        description="review_{perspective}.md を evaluator の整形結果で全面書き換えする"
    )
    parser.add_argument("session_dir", help="セッションディレクトリパス")
    parser.add_argument("--perspective", required=True,
                        help="perspective 名(例: logic / resilience)")
    args = parser.parse_args()

    content = sys.stdin.read()

    try:
        result = write_interpretation(args.session_dir, args.perspective, content)
    except FileNotFoundError as e:
        json.dump({"status": "error", "error": str(e)}, sys.stderr,
                  ensure_ascii=False)
        sys.stderr.write("\n")
        sys.exit(1)
    except ValueError as e:
        json.dump({"status": "error", "error": str(e)}, sys.stderr,
                  ensure_ascii=False)
        sys.stderr.write("\n")
        sys.exit(1)

    json.dump(
        {"status": "ok", **result},
        sys.stdout, ensure_ascii=False,
    )
    print()


if __name__ == "__main__":
    main()
