#!/usr/bin/env python3
"""review のセッションを初期化するラッパー。

session_manager.py init を subprocess で呼び出してセッションを作成し、
受け取った --files 引数を session.yaml に追記する (DES-028 §4.1 / §2.2 CLI 構文)。

位置引数: {review_type} {engine} {auto_count}
オプション:
  --files <path1> <path2> ...   レビュー対象ファイル群 (省略可、複数可)
  --files <path1,path2,...>     カンマ区切りでも受け付ける

--current-cycle は新規 init では常に 0 のためラッパー内でハードコード
(DES-024 §3.2 補足)。

DROP 済み引数:
  --section : DES-028 §2.7 (TBD: 旧 perspective ごとの section 抽出)。
              argparse から完全に削除済み。指定された場合は argparse の
              "unrecognized arguments" として exit code 2 で異常終了する。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# session.yaml の YAML 操作ユーティリティ
SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
from session.yaml_utils import read_yaml  # noqa: E402

LOW_LEVEL = SCRIPTS_DIR / "session_manager.py"
SKILL = "review"


def _parse_files(values):
    """--files に渡された値を flat な list[str] に正規化する。

    nargs='*' で受けた各値はカンマ区切りを許容する:
      --files a.md b.md          -> ["a.md", "b.md"]
      --files a.md,b.md          -> ["a.md", "b.md"]
      --files a.md,b.md c.md     -> ["a.md", "b.md", "c.md"]

    空文字列は除外する。
    """
    result = []
    for v in values or []:
        for part in v.split(","):
            p = part.strip()
            if p:
                result.append(p)
    return result


def _parse_args(argv):
    """位置引数 + --files のみ受け取る。--section は意図的に未定義で reject する。"""
    parser = argparse.ArgumentParser(
        prog="init_session.py",
        description="review session を初期化する (DES-028 §4.1)",
    )
    parser.add_argument("review_type", help="code | design | requirement | plan | uxui | generic")
    parser.add_argument("engine", help="レビューエンジン名 (例: codex)")
    parser.add_argument("auto_count", help="auto 件数 (現状は文字列で透過)")
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="レビュー対象ファイル群 (空白またはカンマ区切り)",
    )
    return parser.parse_args(argv)


def _append_files_to_session_yaml(session_dir, files):
    """session.yaml に ``files: [...]`` を追記する。

    既存のフラット session.yaml を読み込み、末尾に YAML インライン配列で files
    フィールドを書き加える。--files 未指定でも空配列として明示記録する
    (常に存在することで読み手の場合分けを単純化)。
    """
    yaml_path = Path(session_dir) / "session.yaml"
    if not yaml_path.exists():
        return
    text = yaml_path.read_text(encoding="utf-8")
    # 既存の files: 行があれば書き換えず単に上書き追記しない (session_manager は
    # files を出力しないので通常は存在しない。安全側で重複を避けるため早期 return)。
    existing = read_yaml(yaml_path)
    if "files" in existing:
        return
    # インライン配列で書き出す (yaml_utils は flat key:scalar しか書けないため手書き)
    if files:
        # シンプルパス前提でクォート不要だが、安全のためダブルクォートで囲む
        items = ", ".join(f'"{p}"' for p in files)
        line = f"files: [{items}]"
    else:
        line = "files: []"
    if not text.endswith("\n"):
        text += "\n"
    text += line + "\n"
    yaml_path.write_text(text, encoding="utf-8")


def main(argv=None):
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    files = _parse_files(args.files)

    cmd = [
        sys.executable,
        str(LOW_LEVEL),
        "init",
        "--skill", SKILL,
        "--review-type", args.review_type,
        "--engine", args.engine,
        "--auto-count", args.auto_count,
        "--current-cycle", "0",
    ]
    # session_manager の JSON 出力から session_dir を取得するため stdout を capture
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)

    # session_manager の出力は exit code に関わらず透過する (透過原則)
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)

    if result.returncode != 0:
        return result.returncode

    # JSON から session_dir を取得して session.yaml に files を追記
    try:
        payload = json.loads(result.stdout)
        session_dir = payload.get("session_dir")
    except (ValueError, AttributeError):
        session_dir = None

    if session_dir:
        _append_files_to_session_yaml(session_dir, files)

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
