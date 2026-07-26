#!/usr/bin/env python3
"""review: ラウンド終了時の変更ファイル一覧を決定論的に取得する CLI。

`git status --porcelain=v1 -z --untracked-files=all` の NUL 区切り出力を解析し、実際に
変更・新規追加されているファイルパスの一覧を返す。`git status --porcelain`（-z 無し）は
空白・改行・非 ASCII を含むパスを C-style quote し、rename/copy は ` -> ` を含む1行で
表現するため、行単位・矢印区切りでの手動パースでは実パスを取り違える（実 Codex レビューで
発見）。`-z` は quoting を行わず NUL 終端のみで区切られるため、これを正として解析する。

rename/copy レコードの扱い（実 git 挙動で実測確認、git-status(1) の -z 出力仕様）:
    通常のファイル: "XY PATH\0"
    rename/copy:    "XY NEW_PATH\0OLD_PATH\0"（1レコード目に status + 現在の（新）パス、
                     2レコード目は status 無しの旧パスのみ）
XY の 1桁目または2桁目が 'R'（renamed）または 'C'（copied）の場合、1トークン目のパス
（= 現在のパス）を採用し、2トークン目（旧パス）は消費するだけで使わない。

Usage:
    python3 collect_modified_files.py [--project-root <path>]
"""

import argparse
import json
import subprocess


def _parse_porcelain_z(raw: bytes) -> list[str]:
    """`git status --porcelain=v1 -z` の生出力（bytes）を現在のパス一覧に変換する。"""
    tokens = raw.split(b"\x00")
    # 末尾の空トークン（終端 NUL による）を除去する。
    if tokens and tokens[-1] == b"":
        tokens.pop()

    paths: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i].decode("utf-8", errors="surrogateescape")
        if len(token) < 3:
            i += 1
            continue
        xy = token[:2]
        path = token[3:]
        if "R" in xy or "C" in xy:
            # rename/copy: 1トークン目が現在（新）のパス。2トークン目（旧パス）は消費のみ。
            paths.append(path)
            i += 2
        else:
            paths.append(path)
            i += 1
    return paths


def collect_modified_files(project_root: str | None = None) -> dict:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            capture_output=True,
            timeout=30,
            cwd=project_root,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "error": str(exc)}

    if proc.returncode != 0:
        return {"status": "error", "error": proc.stderr.decode("utf-8", errors="replace").strip()}

    return {"status": "ok", "files": _parse_porcelain_z(proc.stdout)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="git status の変更ファイル一覧を決定論的に取得する CLI",
    )
    parser.add_argument("--project-root", default=None)
    args = parser.parse_args()

    result = collect_modified_files(args.project_root)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
