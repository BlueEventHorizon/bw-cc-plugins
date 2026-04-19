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
import os
import sys
import tempfile
from pathlib import Path


def _atomic_write_text(target, content, encoding="utf-8"):
    """同一ディレクトリ内で tmp ファイル作成 → rename でアトミックに書き込む。

    途中クラッシュ / 割り込みで target が空・途中書きになるのを防ぐ。
    rename は POSIX で atomic が保証される(同一ファイルシステム上)。
    """
    target = Path(target)
    target_dir = target.parent
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target_dir)
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(target))
    except Exception:
        # 失敗したら tmp を削除する(target は変更されない)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


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
        _atomic_write_text(backup, raw_content)
        backup_created = True

    _atomic_write_text(target, content)

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
