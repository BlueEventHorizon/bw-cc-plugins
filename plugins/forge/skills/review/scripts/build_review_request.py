#!/usr/bin/env python3
"""review 依頼メッセージ組み立てスクリプト（DES-055）。

`templates/<pattern>_review_request_template.md` を Read し、`{{TOKEN}}` を動的データで
置換して標準出力へ書く。**本スクリプトは散文を持たない。** 依頼本文の文言・レビュー観点の
名指しはすべてテンプレート側にあり、本スクリプトの責務は次の 4 点に限られる。

    1. review_id の生成（uuid4）
    2. プロトコルヘッダの形式の担保（parse_findings.py / wait_for_reply.py /
       filter_review_history.py が同一形式を前提に噛み合う）
    3. 絶対パスの算出（{{PLUGIN_ROOT}} / {{PROJECT_ROOT}}）
    4. 埋め込むデータの検証（fail-closed）

`${CLAUDE_PLUGIN_ROOT}` は SKILL.md がロードされるときにのみ展開される変数であり、
テンプレートを Read した本文の中では展開されない。そのためテンプレートには
`{{PLUGIN_ROOT}}/docs/...` と書き、本スクリプトが実体の絶対パスへ置換する（DES-055 §4.3）。

標準ライブラリのみ使用する。

Usage:
    # 範囲指定（対象ファイル一覧を渡さない。REQ-013 FNC-1312）
    python3 build_review_request.py --pattern diff --project-root <path> \
        [--project-rules-json '[...]'] [--project-specs-json '[...]']

    python3 build_review_request.py --pattern branch --project-root <path> \
        --base-branch develop --target-branch feature/x \
        [--project-rules-json '[...]'] [--project-specs-json '[...]']

    # ファイル指定
    python3 build_review_request.py --pattern design --project-root <path> \
        --files-json '["docs/specs/x/design/DES-001_a_design.md"]' \
        [--project-rules-json '[...]'] [--project-specs-json '[...]']

Output:
    標準出力に依頼本文（テキスト）。エラーは stderr + 非ゼロ終了。
"""

import argparse
import json
import re
import sys
import uuid
from pathlib import Path

# 対象軸を含む「レビューのパターン」。テンプレートのファイル名に対応する（DES-055 §3）。
RANGE_PATTERNS = ("diff", "branch")
FILE_PATTERNS = ("code", "requirement", "design", "plan", "uxui")
VALID_PATTERNS = RANGE_PATTERNS + FILE_PATTERNS

ROUND = 1

_TOKEN_RE = re.compile(r"\{\{([A-Z_]+)\}\}")

_TEMPLATE_DIR_NAME = "templates"
_NONE_MARKER = "（なし）"


def plugin_root() -> Path:
    """forge プラグインのルート絶対パスを算出する。

    本ファイルは `<plugin_root>/skills/review/scripts/` に置かれるため 3 つ上。
    `${CLAUDE_PLUGIN_ROOT}` に依存しない（データ本文では展開されないため。DES-055 §4.3）。
    """
    return Path(__file__).resolve().parents[3]


def template_path(pattern: str) -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / _TEMPLATE_DIR_NAME
        / f"{pattern}_review_request_template.md"
    )


def _reject_newlines(label: str, values: list[str]) -> None:
    """埋め込む値に CR/LF が含まれる場合は ValueError を送出する。

    改行を含む値をそのまま本文へ差し込むと、セクション構造・返信形式契約を偽装・分断
    できてしまう（プロトコル注入）。ファイルシステムは改行を含むファイル名を許容するため、
    通常運用では起きにくくても実在の抜け道であり、埋め込み直前に一律拒否する。
    """
    for value in values:
        if "\n" in value or "\r" in value:
            raise ValueError(f"{label} に改行を含む値は指定できません: {value!r}")


def _absolute_bullet_list(project_root_abs: str, paths: list[str]) -> str:
    """プロジェクトルート相対パスを絶対パスの箇条書きへ変換する。空なら不在を明示する。

    レビュアーは別プロセスであり cwd が一致する保証がないため、本文に載せるパスは
    すべて絶対にする（DES-055 §4.3）。対象ファイル・ルール文書・仕様書で扱いを
    分けない（片方だけ相対だと、レビュアーが解決に失敗した理由が分かりにくい）。
    """
    if not paths:
        return _NONE_MARKER
    return "\n".join(f"- {project_root_abs}/{p}" for p in paths)


def build_body(
    pattern: str,
    project_root: Path,
    review_id: str,
    files: list[str] | None = None,
    base_branch: str | None = None,
    target_branch: str | None = None,
    project_rules: list[str] | None = None,
    project_specs: list[str] | None = None,
    round_no: int = ROUND,
) -> str:
    """テンプレートを読み、トークンを置換した依頼本文を返す。

    契約違反（未知パターン / 改行混入 / 絶対パス混入 / 必須データ欠落 / 未消化トークン /
    テンプレートが要求しないデータ）はすべて ValueError を送出する（fail-closed）。
    """
    if pattern not in VALID_PATTERNS:
        raise ValueError(
            f"不明なパターンです: {pattern!r}（有効: {', '.join(VALID_PATTERNS)}）"
        )

    files = files or []
    project_rules = project_rules or []
    project_specs = project_specs or []

    _reject_newlines("対象ファイル一覧", files)
    _reject_newlines("プロジェクトルール一覧", project_rules)
    _reject_newlines("プロジェクト仕様書一覧", project_specs)
    _reject_newlines(
        "ブランチ名", [b for b in (base_branch, target_branch) if b is not None]
    )

    for label, paths in (
        ("対象ファイル", files),
        ("プロジェクトルール", project_rules),
        ("プロジェクト仕様書", project_specs),
    ):
        for p in paths:
            if Path(p).is_absolute():
                raise ValueError(
                    f"{label}はプロジェクトルート相対パスで渡してください: {p!r}"
                )

    if pattern in RANGE_PATTERNS and files:
        raise ValueError(
            f"{pattern} は範囲指定のため対象ファイル一覧を渡せません"
            "（範囲指定をファイル一覧へ展開しない。REQ-013 FNC-1312）"
        )
    if pattern in FILE_PATTERNS and not files:
        raise ValueError(f"{pattern} には対象ファイル一覧が必要です")
    if pattern == "branch":
        missing = [
            label
            for label, value in (
                ("base ブランチ", base_branch),
                ("target ブランチ", target_branch),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"branch には {' と '.join(missing)} の指定が必要です")

    path = template_path(pattern)
    if not path.is_file():
        raise ValueError(f"テンプレートが見つかりません: {path}")
    template = path.read_text(encoding="utf-8")

    project_root_abs = str(project_root.resolve())

    values = {
        "PROTOCOL_HEADER": f"[msg-review] {pattern} review_id={review_id} round={round_no}",
        "REVIEW_TYPE": pattern,
        "PLUGIN_ROOT": str(plugin_root()),
        "PROJECT_ROOT": project_root_abs,
        "PROJECT_RULES": _absolute_bullet_list(project_root_abs, project_rules),
        "PROJECT_SPECS": _absolute_bullet_list(project_root_abs, project_specs),
        "TARGET_FILES": _absolute_bullet_list(project_root_abs, files),
        "BASE_BRANCH": base_branch or "",
        "TARGET_BRANCH": target_branch or "",
    }

    used = set(_TOKEN_RE.findall(template))
    unknown = sorted(used - values.keys())
    if unknown:
        raise ValueError(
            f"テンプレート {path.name} が未知のトークンを使っています: "
            f"{', '.join('{{' + t + '}}' for t in unknown)}"
        )

    body = _TOKEN_RE.sub(lambda m: values[m.group(1)], template)

    leftover = _TOKEN_RE.findall(body)
    if leftover or "{{" in body:
        raise ValueError(
            f"テンプレート {path.name} に未消化のトークンが残りました: {leftover}"
        )

    return body


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="review 依頼メッセージ本文の組み立て（テンプレート方式）",
    )
    parser.add_argument(
        "--pattern",
        required=True,
        choices=VALID_PATTERNS,
        help="レビューのパターン（テンプレートを選ぶ）",
    )
    parser.add_argument(
        "--project-root",
        required=True,
        help="プロジェクトルート（絶対パスの起点。レビュアーへは絶対パスで渡す）",
    )
    parser.add_argument(
        "--files-json",
        default=None,
        help=(
            "対象ファイル一覧（プロジェクトルート相対）の JSON 配列。"
            "ファイル指定パターンでのみ使う（範囲指定では受け付けない）"
        ),
    )
    parser.add_argument(
        "--base-branch",
        default=None,
        help="branch パターンの base ブランチ名（利用者が確認して確定したもの）",
    )
    parser.add_argument(
        "--target-branch",
        default=None,
        help="branch パターンの target ブランチ名",
    )
    parser.add_argument(
        "--project-rules-json",
        default=None,
        help="query-db-rules の結果パス一覧（プロジェクトルート相対）の JSON 配列",
    )
    parser.add_argument(
        "--project-specs-json",
        default=None,
        help="query-db-specs の結果パス一覧（プロジェクトルート相対）の JSON 配列",
    )
    return parser.parse_args(argv)


def _load_path_list(raw: str | None, flag: str) -> list[str] | None:
    """JSON 配列文字列を文字列リストへ変換する。不正なら None を返す（呼び出し側で報告）。"""
    if raw is None:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"{flag} の JSON パースに失敗しました: {exc}", file=sys.stderr)
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        print(f"{flag} は文字列の JSON 配列である必要があります", file=sys.stderr)
        return None
    return value


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(sys.argv[1:])

    files = _load_path_list(args.files_json, "--files-json")
    project_rules = _load_path_list(args.project_rules_json, "--project-rules-json")
    project_specs = _load_path_list(args.project_specs_json, "--project-specs-json")
    if files is None or project_rules is None or project_specs is None:
        return 1

    try:
        body = build_body(
            pattern=args.pattern,
            project_root=Path(args.project_root),
            review_id=uuid.uuid4().hex,
            files=files,
            base_branch=args.base_branch,
            target_branch=args.target_branch,
            project_rules=project_rules,
            project_specs=project_specs,
            round_no=ROUND,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
