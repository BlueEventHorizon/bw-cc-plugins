#!/usr/bin/env python3
"""依存ファイル（オプション・filter あり）のバージョンを更新する writer ラッパー。

`update_version_files.py {file} {cur} {new} --filter {filter} --optional` を
subprocess で呼び出し、成功時は stdout (更新後のファイル内容) を対象ファイルへ
書き戻す。低レベルは NFR-01 により元ファイルを書き換えないため、書き戻しは
ラッパーの責務（DES-024 §2.3 の writer 例外類型 / Issue #139）。

`--optional` でパターン未マッチ時は stderr に `status: skipped` が出力され
stdout は空。この場合は書き戻しをスキップして exit 0 を維持する。

位置引数: {file} {current_version} {new_version} {filter}
"""
import subprocess
import sys
from pathlib import Path

LOW_LEVEL = Path(__file__).resolve().parent / "update_version_files.py"


def main() -> int:
    file_, cur, new, filter_ = (
        sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    )
    result = subprocess.run(
        [sys.executable, str(LOW_LEVEL),
         file_, cur, new,
         "--filter", filter_,
         "--optional"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode == 0 and result.stdout:
        Path(file_).write_text(result.stdout, encoding="utf-8")
    elif result.stdout:
        sys.stdout.write(result.stdout)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
