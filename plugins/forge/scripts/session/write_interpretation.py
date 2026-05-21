#!/usr/bin/env python3
"""evaluator の整形結果で `review_{kind}.md` を全面書き換えする。

evaluator から呼ばれ、reviewer 原文を `.raw.md` にバックアップしてから
stdin の Markdown で `review_{kind}.md` を全面上書きする。
present-findings もユーザー対話後の更新で呼び出す(その際 `.raw.md` は保護される)。

Usage:
    cat <<'EOF' | python3 write_interpretation.py <session_dir> --kind <value>
    # evaluator 評価(...)
    (本文)
    EOF

`--kind` の値域 (REQ-004 / DES-028 §2.4 の種別と一致):
    code / design / requirement / plan / uxui / generic

動作:
    1. {session_dir}/review_{kind}.md が存在しない場合はエラー
    2. {session_dir}/review_{kind}.raw.md が存在しない場合:
       - review_{kind}.md を .raw.md にコピー(初回バックアップ)
       - backup_created = true
    3. 既に .raw.md が存在する場合:
       - .raw.md は保護(再作成しない)
       - backup_created = false
    4. stdin の内容で review_{kind}.md を上書き

出力 (stdout JSON):
    {"status": "ok", "path": ".../review_{kind}.md",
     "backup_path": ".../review_{kind}.raw.md", "backup_created": true|false}
"""

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR.parent))

from session.store import SessionStore  # noqa: E402

# DES-028 §2.4 / REQ-004 FNC-410 の種別と一致 (位置引数 <種別> の値域)
KIND_CHOICES = ("code", "design", "requirement", "plan", "uxui", "generic")


def write_interpretation(session_dir, kind, content):
    """review_{kind}.md を全面書き換えする。

    Args:
        session_dir: セッションディレクトリパス
        kind: 種別 (code / design / requirement / plan / uxui / generic)
        content: 書き込む Markdown 本文

    Returns:
        dict: {"path", "backup_path", "backup_created"}

    Raises:
        FileNotFoundError: review_{kind}.md が存在しない
        ValueError: content が空
    """
    if not content:
        raise ValueError("stdin の内容が空です")

    session_path = Path(session_dir)
    target = session_path / f"review_{kind}.md"
    backup = session_path / f"review_{kind}.raw.md"
    store = SessionStore(session_path)

    if not target.exists():
        raise FileNotFoundError(
            f"review_{kind}.md が見つかりません: {target}"
        )

    backup_created = False
    if not backup.exists():
        # バックアップもアトミックに: copyfile → rename パターンを使う代わりに、
        # shutil.copyfile は書き込みがアトミックでないため tmp 経由で行う
        with open(str(target), "r", encoding="utf-8") as f:
            raw_content = f.read()
        store.write_text(backup.name, raw_content)
        backup_created = True

    store.write_text(target.name, content)

    return {
        "path": str(target),
        "backup_path": str(backup),
        "backup_created": backup_created,
    }


def main():
    parser = argparse.ArgumentParser(
        description="review_{kind}.md を evaluator の整形結果で全面書き換えする"
    )
    parser.add_argument("session_dir", help="セッションディレクトリパス")
    parser.add_argument(
        "--kind",
        required=True,
        choices=KIND_CHOICES,
        help="種別 (code / design / requirement / plan / uxui / generic)",
    )
    args = parser.parse_args()

    content = sys.stdin.read()

    try:
        result = write_interpretation(args.session_dir, args.kind, content)
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
