#!/usr/bin/env python3
"""codex exec の出力から Markdown レビュー本文を抽出する。

codex exec は 2 種類の出力を生成する:
  1. -o <file>: 最終メッセージ(assistant の最終返答のみ)
  2. stdout:    セッション全体のログ(思考 / tool 呼び出し / 最終メッセージ)

reviewer は「最終メッセージに Markdown で指摘を返す」よう指示されているため、
通常は lastmsg ファイルを採用すれば十分。stdout はフォールバックとして使う。

Usage:
    python3 extract_codex_output.py \\
        --stdout <stdout_file> \\
        --lastmsg <lastmsg_file> \\
        --output <output_file>

Exit codes:
    0: 抽出成功(output に Markdown 本文を書き込んだ)
    1: 有効な Markdown 本文を見つけられなかった(output は空で作成される)
"""

import argparse
import re
import sys
from pathlib import Path


# Markdown レビュー本文の最低要件
_HAS_HEADING = re.compile(r'^\s*#{2,3}\s', re.MULTILINE)
_HAS_FINDING = re.compile(
    r'^\s*\d+\.\s+(?:\[(?:critical|major|minor)\]|🔴|🟡|🟢)?\s*\*\*',
    re.MULTILINE,
)
_SEVERITY_CHARS = ('🔴', '🟡', '🟢')
# ASCII severity ラベル(行マーカー primary)
_LABEL_PATTERN = re.compile(r'\[(?:critical|major|minor)\]')

# codex のセッションメタ情報行。これらに当たったら遡及を打ち切る。
_METADATA_PATTERNS = (
    re.compile(r'^\[\d{4}-\d{2}-\d{2}T'),  # ISO timestamp プレフィックス
    re.compile(
        r'^(workdir|model|user instructions|session|provider|reasoning'
        r'|version|sandbox|approval|tokens used)\s*:',
        re.IGNORECASE,
    ),
)


def _is_metadata_line(stripped):
    for pat in _METADATA_PATTERNS:
        if pat.match(stripped):
            return True
    return False


def looks_like_review_markdown(text):
    """テキストが review 本文として妥当か判定する。

    判定基準:
      - 空でない
      - `##` / `###` 見出しまたは番号付き finding(`1. **...**`)を含む
      - または ASCII ラベル `[critical]/[major]/[minor]` を含む
      - または severity 絵文字マーカー(🔴/🟡/🟢)を含む(後方互換)
    """
    if not text or not text.strip():
        return False
    if _HAS_HEADING.search(text):
        return True
    if _HAS_FINDING.search(text):
        return True
    if _LABEL_PATTERN.search(text):
        return True
    if any(c in text for c in _SEVERITY_CHARS):
        return True
    return False


def extract_from_stdout(stdout_text):
    """codex stdout から最後の Markdown 本文ブロックを抽出する。

    codex exec の stdout はセッション全体のログ形式で、先頭には
    ツール呼び出しやメタ情報が混ざる。最終メッセージは概ね末尾側にあるため、
    以下のルールで本文範囲を決定する:

      1. 最後に現れる severity ラベル行(`[critical]` / `[major]` / `[minor]`)
         または絵文字マーカー行(🔴 / 🟡 / 🟢)または
         番号付き finding(`1. **...**`)の行の位置を見つける
      2. そこから逆方向に `##`/`###` 見出しを辿り、本文の先頭を決定する
      3. 本文の末尾は `tokens used` 等のメタ情報行の直前まで
    """
    if not stdout_text:
        return ''

    lines = stdout_text.split('\n')
    n = len(lines)

    # Step 1: severity ラベル or 絵文字マーカー or finding 行の最後の出現位置を探す
    anchor = -1
    for i in range(n - 1, -1, -1):
        line = lines[i]
        if _LABEL_PATTERN.search(line):
            anchor = i
            break
        if any(c in line for c in _SEVERITY_CHARS):
            anchor = i
            break
        if re.match(r'^\s*\d+\.\s+\*\*', line):
            anchor = i
            break

    if anchor < 0:
        return ''

    # Step 2: 本文の先頭: anchor から逆方向に辿り、最上位の ## / ### 見出し
    # まで戻る。セッションメタ情報(タイムスタンプ・workdir 等)に当たったら
    # そこで打ち切る。空行ではなくメタ情報で区切るため、セクション間の空行で
    # 先頭確定されない。
    start = anchor
    for i in range(anchor, -1, -1):
        stripped = lines[i].lstrip()
        if _is_metadata_line(stripped):
            break
        if stripped.startswith('### ') or stripped.startswith('## '):
            start = i

    # 見出しが見つからない場合、severity マーカーを含むブロックを
    # 最寄りのメタ行または先頭まで遡る
    if not (lines[start].lstrip().startswith('### ')
            or lines[start].lstrip().startswith('## ')):
        start = anchor
        while start > 0:
            prev_stripped = lines[start - 1].lstrip()
            if _is_metadata_line(prev_stripped):
                break
            start -= 1

    # Step 3: 本文の末尾: メタ情報(`tokens used` 等)の直前まで
    end = n
    for i in range(anchor, n):
        stripped = lines[i].lstrip()
        if _is_metadata_line(stripped):
            end = i
            break

    body = '\n'.join(lines[start:end]).strip()
    return body


def extract(stdout_path, lastmsg_path):
    """lastmsg を優先、だめなら stdout から抽出した本文を返す。

    Returns:
        str: 抽出された Markdown 本文。見つからなければ空文字列
    """
    # lastmsg を優先的に採用
    lastmsg_text = ''
    if lastmsg_path and Path(lastmsg_path).exists():
        try:
            lastmsg_text = Path(lastmsg_path).read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            lastmsg_text = ''

    if looks_like_review_markdown(lastmsg_text):
        return lastmsg_text

    # stdout からのフォールバック抽出
    stdout_text = ''
    if stdout_path and Path(stdout_path).exists():
        try:
            stdout_text = Path(stdout_path).read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            stdout_text = ''

    extracted = extract_from_stdout(stdout_text)
    if looks_like_review_markdown(extracted):
        return extracted

    return ''


def main():
    parser = argparse.ArgumentParser(
        description="codex exec の出力から Markdown レビュー本文を抽出する"
    )
    parser.add_argument('--stdout', required=True,
                        help='codex の stdout ログファイル')
    parser.add_argument('--lastmsg', required=True,
                        help='codex -o の出力ファイル(最終メッセージ)')
    parser.add_argument('--output', required=True,
                        help='抽出した Markdown 本文の書き出し先')
    args = parser.parse_args()

    body = extract(args.stdout, args.lastmsg)
    Path(args.output).write_text(body, encoding='utf-8')
    return 0 if body else 1


if __name__ == '__main__':
    sys.exit(main())
