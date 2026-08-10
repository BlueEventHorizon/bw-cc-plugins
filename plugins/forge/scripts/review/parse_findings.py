#!/usr/bin/env python3
"""review: バックエンド共通のレビュー応答解釈 CLI。

レビュー応答は、重大度マーカー（🔴/🟡/🟢）と位置を含む自由記述 markdown
（厳密な JSON 構造ではない）である。
本文を行単位に走査し、行頭（箇条書き記号・番号付けを除く）に severity マーカーが
ある行を「新しい finding の開始」とみなして、次の finding 開始行（または完了宣言行）
までをその finding の本文として束ねる。

応答本文を厳密な完了宣言と所見契約に照らし、`approved` / `findings` /
`failure` の 3 値へ変換する。標準ライブラリのみ使用する。

使い方:
    python3 parse_findings.py --body-file <path>
"""

import argparse
import json
import re
from pathlib import Path

SEVERITY_MARKERS = {"🔴": "critical", "🟡": "major", "🟢": "minor"}
COMPLETION_LINES = ("REVIEW_RESULT: approved", "REVIEW_RESULT: findings")
FENCE_RE = re.compile(r"^(```|~~~)")
LOCATION_RE = re.compile(
    r"(?<![\w./\\-])(?P<quote>`)?"
    r"(?P<path>(?:[A-Za-z]:[\\/])?[^`\s:\"'()[\]{}<>,;!?。、，；：！？「」『』【】]+):"
    r"(?P<line>\d+)(?:-(?P<end_line>\d+))?"
    r"(?(quote)`)(?![\w./\\-])"
)
UNKNOWN_LOCATION_MARKERS = ("位置未確定", "location unknown", "unknown location")
LOCATION_OPENING_WRAPPERS = frozenset("([{<「『【")
LOCATION_CLOSING_WRAPPERS = frozenset(")]}>」』】")
CONVENTIONAL_EXTENSIONLESS_FILES = {
    "AUTHORS",
    "Brewfile",
    "CHANGELOG",
    "CONTRIBUTING",
    "Containerfile",
    "COPYING",
    "Dockerfile",
    "Gemfile",
    "Justfile",
    "LICENSE",
    "Makefile",
    "NOTICE",
    "Procfile",
    "README",
    "Rakefile",
    "SECURITY",
    "Vagrantfile",
}

#: 大文字小文字を無視して照合するための畳み込み済み集合。
#:
#: これらの名前は慣用的に表記が揺れる（`Makefile` / `makefile`、`README` / `readme`）。
#: 表記だけを理由に位置情報を捨てると、実在するファイルを指した正しい所見が
#: 「位置なし」と判定され、自動修正の対象から外れる。
_CONVENTIONAL_EXTENSIONLESS_FILES_FOLDED = frozenset(
    name.casefold() for name in CONVENTIONAL_EXTENSIONLESS_FILES
)

# 行頭（任意の箇条書き記号 `-`/`*` または番号付け `1.` を除いた直後）に severity
# マーカーがある行のみを finding の開始とみなす。文中・引用・コード例に偶然出現する
# マーカー（例:「概要: 🟡 major の基準を参照しました。」）を誤って finding として
# 抽出しないため（実レビューで発見）。
FINDING_START_RE = re.compile(r"^(?:[-*]|\d+\.)?\s*(🔴|🟡|🟢)")


def _is_indented_code_line(raw_line: str) -> bool:
    """CommonMark のインデントコードブロック（行頭4スペースまたはタブ）かどうかを判定する。

    fenced code block（\\`\\`\\`）だけでなく、Markdown のもう一つの標準的なコード
    ブロック記法も除外対象にする（実レビューで発見: `.lstrip()` によって
    インデントが失われ、インデントコードブロック内の例示マーカーが finding として
    誤抽出されていた）。
    """
    return raw_line.startswith("    ") or raw_line.startswith("\t")


def _finding_start_severity(raw_line: str) -> str | None:
    """行が finding の開始行かどうかを判定し、該当すれば severity を返す。

    fenced/インデントいずれのコードブロックとも無関係な、通常のテキスト行のみを
    対象にする（呼び出し側で `in_fence`/`_is_indented_code_line` を確認済みの
    行のみ渡すこと）。
    """
    match = FINDING_START_RE.match(raw_line.lstrip())
    if match is None:
        return None
    return SEVERITY_MARKERS[match.group(1)]


def _looks_like_file_path(path: str) -> bool:
    """一般ラベルや数値ではなく、ファイルパスらしい決定論的な形かを判定する。"""
    if not path or path.isdigit() or path.startswith("//"):
        return False
    if re.match(r"^[A-Za-z]:[\\/]", path):
        return True
    if path.startswith("/") or "/" in path or "\\" in path:
        return True

    basename = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if basename.casefold() in _CONVENTIONAL_EXTENSIONLESS_FILES_FOLDED:
        return True
    if basename.startswith(".") and len(basename) > 1:
        return True
    stem, separator, suffix = basename.rpartition(".")
    return bool(separator and stem and suffix)


def _extract_location(text: str) -> dict | None:
    """所見本文からファイルパスらしい明示位置だけを抽出する。"""
    for match in LOCATION_RE.finditer(text):
        before = text[match.start() - 1] if match.start() > 0 else ""
        after = text[match.end()] if match.end() < len(text) else ""
        path = match.group("path")
        line = int(match.group("line"))
        end_line_text = match.group("end_line")
        end_line = int(end_line_text) if end_line_text is not None else None
        if (
            before in LOCATION_OPENING_WRAPPERS
            or after in LOCATION_CLOSING_WRAPPERS
            or not _looks_like_file_path(path)
            or line < 1
            or (end_line is not None and end_line < line)
        ):
            continue
        location = {
            "path": path,
            "line": line,
        }
        if end_line is not None:
            location["end_line"] = end_line
        return location
    lowered = text.lower()
    if any(marker in lowered for marker in UNKNOWN_LOCATION_MARKERS):
        return {"unknown": True}
    return None


def _completion_declarations(body: str) -> tuple[list[tuple[int, str]], int | None]:
    """コードブロック外の完了宣言と、意味のある最終行の位置を返す。"""
    declarations: list[tuple[int, str]] = []
    last_meaningful_index: int | None = None
    in_fence = False
    for index, raw_line in enumerate(body.splitlines()):
        stripped = raw_line.strip()
        if not stripped:
            continue
        last_meaningful_index = index
        if FENCE_RE.match(stripped):
            in_fence = not in_fence
            continue
        if in_fence or _is_indented_code_line(raw_line):
            continue
        if stripped in COMPLETION_LINES:
            declarations.append(
                (index, stripped.removeprefix("REVIEW_RESULT: "))
            )
    return declarations, last_meaningful_index


def parse_findings(body: str) -> list[dict]:
    """本文から severity 別の finding リストを抽出する。

    finding の開始行（行頭に severity マーカー）が現れるたびに新しい finding を
    開始し、次の開始行（または最初の完了宣言行）までを束ねてその finding の本文と
    する。この関数は低レベル抽出 API であり、完了宣言・severity・位置を含む共通契約の
    検証は `interpret_response()` が担う。severity マーカーのない本文を推測で finding
    に変換しない。

    **fenced code block 内は finding 開始として扱わない**: 自由記述 Markdown では
    返信形式の例や既存所見の引用をコードブロック（\\`\\`\\` または ~~~ で囲まれた範囲）
    で示すことがあり、その中に severity マーカーが含まれていても実在しない finding
    として抽出してしまう（実レビューで発見）。フェンス行（\\`\\`\\` 始まりの行）を
    追跡し、フェンス内では finding の開始判定を行わない（既存 finding の本文継続、
    または抽出対象外とする）。

    **見出しによる severity のグループ化（`## 🔴 critical` 配下に所見を並べる形）も
    finding 開始として扱わない**: 見出し行はマーカーの前に `#` を持つため開始判定に
    一致せず、配下の所見にはマーカーが無い。ここで見出しから severity を継承させると
    「マーカーのない本文を推測で finding に変換しない」原則を破り、finding の境界も
    曖昧になる。マーカーを所見 1 行目の行頭に置くことは、依頼テンプレートの返信形式契約
    がレビュアーへ要求する。
    """
    lines = body.splitlines()
    declarations, _ = _completion_declarations(body)
    first_completion_index = declarations[0][0] if declarations else None
    content_lines = (
        lines if first_completion_index is None else lines[:first_completion_index]
    )

    findings: list[dict] = []
    current_severity: str | None = None
    current_lines: list[str] = []
    in_fence = False

    def flush() -> None:
        if current_severity is None:
            return
        text = "\n".join(current_lines).strip()
        if text:
            findings.append(
                {
                    "severity": current_severity,
                    "text": text,
                    "location": _extract_location(text),
                }
            )

    for raw_line in content_lines:
        stripped = raw_line.strip()

        if FENCE_RE.match(stripped):
            in_fence = not in_fence
            if current_severity is not None:
                current_lines.append(raw_line)
            continue

        if in_fence or _is_indented_code_line(raw_line):
            severity = None
        else:
            severity = _finding_start_severity(raw_line)
        if severity is not None:
            flush()
            current_severity = severity
            current_lines = [raw_line]
        elif current_severity is not None:
            current_lines.append(raw_line)

    flush()
    return findings


def interpret_response(body: str) -> dict:
    """レビュー応答を共通の 3 値判定へ変換する。契約違反は fail closed とする。

    **位置表記の欠落だけは fail closed の対象にしない [MANDATORY]**。位置を取り出せない
    所見は `location: {"unknown": True}` として受理し、件数を `warnings` で返す。
    レビュアーが `位置未確定` と明示した所見と同じ表現になり、下流の扱いも同じになる
    （自動修正の対象外。人間の確認へ回す）。

    以前は 1 件でも位置を欠くとラウンド全体を `failure` にしていた。実測では、16 件の
    所見のうち 15 件が完全な位置情報を持っていたのに、1 件の表記が許容形と合わなかった
    だけで全件が失われた。位置の欠落は「レビューが成立しなかった」ことを意味せず、
    その 1 件を人間の確認へ回せば足りる。契約違反であること自体は `warnings` で可視化する。
    """
    declarations, last_meaningful_index = _completion_declarations(body)
    if not declarations:
        return {
            "judgment": "failure",
            "findings": [],
            "error": "完了宣言行がありません",
        }
    if len(declarations) != 1:
        return {
            "judgment": "failure",
            "findings": [],
            "error": "完了宣言行は厳密に 1 行だけ必要です",
        }
    completion_index, declaration = declarations[0]
    if completion_index != last_meaningful_index:
        return {
            "judgment": "failure",
            "findings": [],
            "error": "完了宣言行の後に本文があります",
        }

    findings = parse_findings(body)
    if declaration == "approved":
        if findings:
            return {
                "judgment": "failure",
                "findings": [],
                "error": "approved 宣言と所見が矛盾しています",
            }
        return {"judgment": "approved", "findings": []}

    if not findings:
        return {
            "judgment": "failure",
            "findings": [],
            "error": "findings 宣言には重大度マーカー付き所見が必要です",
        }

    missing_location = [
        index + 1 for index, finding in enumerate(findings) if finding["location"] is None
    ]
    for finding in findings:
        if finding["location"] is None:
            finding["location"] = {"unknown": True}
    result = {"judgment": "findings", "findings": findings}
    if missing_location:
        result["warnings"] = [
            "位置表記が無い所見を位置未確定として受理しました（自動修正の対象外・人間の確認へ回します）: "
            + ", ".join(str(index) for index in missing_location)
        ]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="レビュー応答本文の共通契約解釈 CLI",
    )
    parser.add_argument("--body-file", required=True, help="レビュー応答本文のファイルパス")
    args = parser.parse_args()

    body = Path(args.body_file).read_text(encoding="utf-8")
    print(json.dumps(interpret_response(body), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
