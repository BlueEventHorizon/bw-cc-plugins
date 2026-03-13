#!/usr/bin/env python3
"""forge レビューセッションの HTML レポートを生成する。

セッションディレクトリ内の YAML / Markdown ファイルを読み込み、
HTML テンプレートにデータを注入して report.html を出力する。

Usage:
    python3 generate_report.py <session_dir> [--project-root PATH]

外部依存なし（Python 標準ライブラリのみ）。
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = SCRIPT_DIR / "report_template.html"


# ---------------------------------------------------------------------------
# YAML パーサー（標準ライブラリのみ、セッションファイル専用）
# ---------------------------------------------------------------------------

def _strip_quotes(s):
    """引用符を除去する"""
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def _coerce_value(s):
    """文字列を適切な型に変換する"""
    s = _strip_quotes(s)
    if s == "":
        return ""
    if s == "true":
        return True
    if s == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    return s


def _parse_flow_array(s):
    """フロー配列 '[a, b, c]' をパース"""
    inner = s.strip()[1:-1]
    if not inner.strip():
        return []
    return [_strip_quotes(item.strip()) for item in inner.split(",") if item.strip()]


def parse_session_yaml(text):
    """セッションファイル用の限定 YAML パーサー。

    対応構造:
    - フラット key: value
    - 文字列リスト（key: の下に - val）
    - オブジェクトリスト（key: の下に - subkey: val）
    - オブジェクト内の子リスト（files_modified: の下に - val）
    """
    result = {}
    lines = text.splitlines()
    i = 0

    # 現在のリストコンテキスト
    current_top_key = None  # トップレベルのリストキー
    current_list = None  # リスト本体への参照
    current_item = None  # リスト内の現在のオブジェクト
    current_sub_key = None  # オブジェクト内の子リストキー
    list_item_indent = -1  # リスト要素の「- 」のインデント

    while i < len(lines):
        raw = lines[i]
        stripped = raw.rstrip()
        i += 1

        if not stripped or stripped.lstrip().startswith("#"):
            continue

        indent = len(raw) - len(raw.lstrip())
        content = stripped.strip()

        # indent=0: トップレベル
        if indent == 0:
            if ":" in content:
                key, _, val = content.partition(":")
                key = key.strip()
                val = val.strip()

                if val == "" or val is None:
                    # リスト開始
                    current_top_key = key
                    current_list = []
                    result[key] = current_list
                    current_item = None
                    current_sub_key = None
                    list_item_indent = -1
                elif val.startswith("["):
                    # フロー配列
                    result[key] = _parse_flow_array(val)
                    current_top_key = None
                    current_list = None
                    current_item = None
                    current_sub_key = None
                else:
                    # フラット key-value
                    result[key] = _coerce_value(val)
                    current_top_key = None
                    current_list = None
                    current_item = None
                    current_sub_key = None
            continue

        # indent > 0: リスト内
        if current_top_key is None or current_list is None:
            continue

        # 子リストの要素（オブジェクト内サブリスト）
        # リスト要素より深いインデントで「- 」が来た場合
        if (
            current_item is not None
            and current_sub_key is not None
            and content.startswith("- ")
            and indent > list_item_indent
        ):
            item_val = content[2:].strip()
            current_item[current_sub_key].append(_strip_quotes(item_val))
            continue

        # リスト要素（トップレベルリストの「- 」）
        if content.startswith("- "):
            item_content = content[2:].strip()
            current_sub_key = None
            list_item_indent = indent

            if ":" in item_content:
                # オブジェクトリストの新要素: - key: value
                key, _, val = item_content.partition(":")
                key = key.strip()
                val = val.strip()
                current_item = {key: _coerce_value(val)}
                current_list.append(current_item)
            else:
                # 文字列リストの要素: - value
                current_list.append(_strip_quotes(item_content))
                current_item = None
            continue

        # オブジェクト内のフィールド（- なし、インデントあり）
        if current_item is not None and ":" in content:
            key, _, val = content.partition(":")
            key = key.strip()
            val = val.strip()

            if val == "" or val is None:
                # 子リスト開始
                current_sub_key = key
                current_item[key] = []
            elif val.startswith("["):
                # フロー配列
                current_item[key] = _parse_flow_array(val)
                current_sub_key = None
            else:
                current_item[key] = _coerce_value(val)
                current_sub_key = None
            continue

    return result


# ---------------------------------------------------------------------------
# review.md パーサー（箇所情報の抽出）
# ---------------------------------------------------------------------------

# ファイルパス:行番号 パターン
_FILE_LOC_RE = re.compile(
    r"([\w./_\-]+\.\w+)(?::(\d+(?:-\d+)?))?",
)

# 番号付きリストアイテムの開始
_ITEM_START_RE = re.compile(r"^(\d+)\.\s+\*\*(.+?)\*\*", re.MULTILINE)


def parse_review_md(text):
    """review.md から各指摘事項の箇所情報を抽出する。

    Returns:
        dict: title -> {"location": "file:line", "description": "..."}
    """
    results = {}
    matches = list(_ITEM_START_RE.finditer(text))

    for idx, match in enumerate(matches):
        title = match.group(2).strip().rstrip(":")
        # この指摘の本文範囲を決定
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end]

        # 箇所を抽出
        location = ""
        for line in body.splitlines():
            line_stripped = line.strip()
            if line_stripped.startswith("- 箇所:") or line_stripped.startswith("- 箇所："):
                loc_text = line_stripped.split(":", 1)[-1].strip() if ":" in line_stripped[4:] else line_stripped[5:].strip()
                # 「箇所:」の後の値部分を取得
                after_label = re.split(r"箇所[:：]\s*", line_stripped, maxsplit=1)
                if len(after_label) > 1:
                    loc_text = after_label[1].strip()
                loc_match = _FILE_LOC_RE.search(loc_text)
                if loc_match:
                    location = loc_match.group(0)
                break

        results[title] = {"location": location}

    return results


# ---------------------------------------------------------------------------
# データ構築
# ---------------------------------------------------------------------------

def _read_file(path):
    """ファイルを読み込む。存在しなければ None を返す"""
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def _get_project_root(override=None):
    """プロジェクトルートを取得する"""
    if override:
        return str(Path(override).resolve())
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return str(Path.cwd())


def build_report_data(session_dir, project_root):
    """セッションディレクトリからレポートデータを構築する"""
    session_dir = Path(session_dir)

    # 必須ファイル
    session_text = _read_file(session_dir / "session.yaml")
    if session_text is None:
        print("エラー: session.yaml が見つかりません", file=sys.stderr)
        sys.exit(1)

    plan_text = _read_file(session_dir / "plan.yaml")
    if plan_text is None:
        print("エラー: plan.yaml が見つかりません", file=sys.stderr)
        sys.exit(1)

    # 任意ファイル
    review_text = _read_file(session_dir / "review.md")
    eval_text = _read_file(session_dir / "evaluation.yaml")
    refs_text = _read_file(session_dir / "refs.yaml")

    # パース
    session = parse_session_yaml(session_text)
    plan = parse_session_yaml(plan_text)
    evaluation = parse_session_yaml(eval_text) if eval_text else None
    refs = parse_session_yaml(refs_text) if refs_text else None

    # review.md から箇所情報を抽出
    locations = {}
    if review_text:
        review_items = parse_review_md(review_text)
        # plan.yaml の title とマッチング
        for item in plan.get("items", []):
            title = item.get("title", "")
            item_id = str(item.get("id", ""))
            # 完全一致を試行 → 部分一致にフォールバック
            if title in review_items:
                locations[item_id] = review_items[title].get("location", "")
            else:
                for rev_title, rev_data in review_items.items():
                    if rev_title in title or title in rev_title:
                        locations[item_id] = rev_data.get("location", "")
                        break

    return {
        "session": session,
        "plan": plan,
        "evaluation": evaluation,
        "refs": refs,
        "locations": locations,
        "project_root": project_root,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# HTML 生成
# ---------------------------------------------------------------------------

def generate_html(data):
    """テンプレートにデータを注入して HTML を生成する"""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    data_json = json.dumps(data, ensure_ascii=False)
    return template.replace(
        "/*__EMBEDDED_DATA__*/",
        f"const EMBEDDED_DATA = {data_json};",
    )


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="forge レビューセッションの HTML レポートを生成する"
    )
    parser.add_argument("session_dir", type=Path, help="セッションディレクトリのパス")
    parser.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="プロジェクトルートのパス（省略時は git rev-parse --show-toplevel）",
    )
    args = parser.parse_args()

    session_dir = args.session_dir.resolve()
    if not session_dir.is_dir():
        print(f"エラー: ディレクトリが見つかりません: {session_dir}", file=sys.stderr)
        sys.exit(1)

    project_root = _get_project_root(args.project_root)
    data = build_report_data(session_dir, project_root)
    html = generate_html(data)

    output_path = session_dir / "report.html"
    output_path.write_text(html, encoding="utf-8")
    print(f"レポート生成完了: {output_path}")


if __name__ == "__main__":
    main()
