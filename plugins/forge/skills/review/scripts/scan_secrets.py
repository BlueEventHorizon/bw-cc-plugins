#!/usr/bin/env python3
"""review: 機密情報の混入を決定論的に検出する CLI（`/forge:review --secrets` の前段）。

`sensitive_information_spec.md` §5.1 の二段構えのうち、機械検出側を担う。既知の形式
（プレフィックス付きトークン・秘密鍵ブロック・資格情報付き接続文字列・JWT・高エントロピー
文字列・秘密らしいキーへの代入）を走査し、**値をマスクした** JSON を標準出力へ書く。

文脈判断（プレースホルダとの区別・§2.2 の妥当性・形式に当てはまらない混入の捜索）は本
スクリプトの責務ではない。それはレビュアーが行う。本スクリプトは「形式が一致した箇所」を
漏れなく列挙することだけを担当する。

**検出値の実体を出力しない [MANDATORY]**（同 §5.3）。出力は種別・位置・長さ・先頭数文字に
留める。出力はレビュー依頼本文へ載り msg-sys の DB に永続化されるため、実値を載せると検出
行為そのものが新たな複製経路になる。

**抑制を黙って行わない**（同 §5.2）。行末に `secrets-scan: ignore` を含む行の検出は
`suppressed` へ分離するが、破棄はしない。プレースホルダとして除外した件数も `counts` に残す。

標準ライブラリのみ使用する。

Usage:
    # リポジトリ全体（追跡ファイル + .gitignore されていない未追跡ファイル）
    python3 scan_secrets.py [--project-root <path>]

    # 対象を明示（テスト・部分確認用）
    python3 scan_secrets.py --paths-json '["a.py", "docs/b.md"]' [--project-root <path>]

Output:
    標準出力に JSON。エラーは status: error + 非ゼロ終了。
"""

import argparse
import json
import math
import re
import subprocess
from pathlib import Path

# 1 ファイルあたりの走査上限。超過分は skipped に理由付きで記録する（黙って落とさない）。
MAX_FILE_BYTES = 1_048_576
# 1 行あたりの走査上限。minified・データ埋め込み行でのエントロピー誤検出と実行時間の抑制。
MAX_LINE_CHARS = 4_000

SUPPRESS_MARKER = "secrets-scan: ignore"

# 値がこれらに該当する場合はプレースホルダとして扱い finding にしない（counts に件数は残す）。
_PLACEHOLDER_RE = re.compile(
    r"""(?ix)
    ^(
        [<{(\[].*[>})\]]                 # <your-key> / ${VAR} / {{TOKEN}} / [REDACTED]
      | \$.*                             # $FIGMA_TOKEN 等の環境変数参照
      | .*\$\{.*\}.*                     # 埋め込み変数参照
      | .*(example|sample|dummy|placeholder|redacted|replace[_-]?me|your[_-]|todo|changeme|test)
      | (x{4,}|\*{4,}|\.{3,}|-{4,}|0{8,})
      # 記法の説明で使われる一般語そのもの（`scheme://user:password@host` 等）。
      # 語そのものが値である場合に限る（前後に文字が付く場合は該当しない）。
      | (password|passwd|secret|token|apikey|api[_-]?key|credential|username|hostname)
      | .*(os\.environ|getenv|process\.env|secrets\.)
    )$
    """
)

# 値にこれらが含まれる場合はソースコードの式であり、秘密の literal ではない。
# 例: `token = tokens[i].decode(...)` / `_PREFIXED_TOKEN_RULES: list[tuple[...]]`
_CODE_EXPRESSION_RE = re.compile(r"[()\[\]{}]")

# 秘密として成立しうる文字集合（ASCII 印字可能・空白なし）。日本語・全角記号を含む値は
# 散文の一部であり秘密ではない（例: `Authority: Tool-provided（forge 内蔵）`）。
_SECRET_CHARSET_RE = re.compile(r"^[\x21-\x7e]+$")

# キーがファイル名・パスに見える場合の除外。
# 例: `design_token_template.md: <sha256>`（チェックサム表）はキーに token を含むだけで秘密ではない。
_PATH_LIKE_KEY_RE = re.compile(
    r"\.(md|py|ya?ml|json|toml|txt|ts|tsx|js|jsx|sh|lock|cfg|ini)$", re.IGNORECASE
)

# 同一文字の繰り返し・単調な埋め草。エントロピー検出の足切りに使う。
_MONOTONE_RE = re.compile(r"^(.)\1*$")

# 既知形式のトークン。プレフィックスが一意でエントロピー判定に頼らず確定できるもの。
_PREFIXED_TOKEN_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("openai_or_anthropic_key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("stripe_live_key", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{16,}\b")),
    ("npm_token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("pypi_token", re.compile(r"\bpypi-[A-Za-z0-9_-]{16,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN(?: [A-Z]+)* PRIVATE KEY-----")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
]

# 資格情報を埋め込んだ URI。scheme://user:password@host 形式。
_CONNECTION_STRING_RE = re.compile(
    r"\b[a-z][a-z0-9+.\-]*://(?P<user>[^\s:/@\"']{1,64}):(?P<secret>[^\s:/@\"']{1,256})@"
)

# 秘密らしいキーへの代入。値側のみを検出値として扱う。
_ASSIGNMENT_RE = re.compile(
    r"""(?ix)
    # `auth` 単独を含めないのは `Authority` / `author` に一致してしまうため。
    # 認証を指す語としては auth_token / authorization など複合形のみを拾う。
    \b(?P<key>[A-Za-z0-9_.\-]*
        (?:api[_-]?key|secret|token|password|passwd|pwd|credential
          |private[_-]?key|auth[_-]?(?:token|key|secret|header)|authorization)
       [A-Za-z0-9_.\-]*)
    \s*[:=]\s*
    (?P<quote>["'])?(?P<value>[^\s"',;]{8,256})(?(quote)["'])
    """
)

# 高エントロピー文字列。候補文字に `/` を含めないのは、含めるとファイルパス
# （`docs/specs/forge/design/...`）が軒並み一致して誤検出が支配的になるため。base64 の
# `/` を捨てることになるが、URL-safe 変種（`_` `-`）と `+` `=` で実用上の取りこぼしは小さい。
_HIGH_ENTROPY_CANDIDATE_RE = re.compile(r"[A-Za-z0-9+=_-]{40,}")
_ENTROPY_THRESHOLD = 4.5
_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")

# hex 文字列の単独検出は行わない。sha256 / sha1 / md5 のチェックサム・git SHA・
# ハッシュ表が大量に一致し、実測で検出の 7 割超が誤検出になった（この誤検出率では
# レビュアーが全件を確認せず流し読みするようになり、検出そのものが機能しなくなる）。
# hex 形式の秘密は「秘密らしいキーへの代入」ルール側で拾う。


def shannon_entropy(value: str) -> float:
    """文字列のシャノンエントロピー（bit/文字）を返す。"""
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    length = len(value)
    return -sum(
        (count / length) * math.log2(count / length) for count in counts.values()
    )


def mask(value: str) -> str:
    """検出値を、実体を復元できない形へ落とす（§5.3）。

    先頭 4 文字だけを残すのは、種別の識別（`AKIA` / `ghp_` 等）にプレフィックスが必要な
    ためである。値が短い場合は先頭を出さない（短い値ほど残りを推測されやすい）。
    """
    if len(value) <= 8:
        return f"***[{len(value)}文字]"
    return f"{value[:4]}***[{len(value)}文字]"


def _is_placeholder(value: str) -> bool:
    if _MONOTONE_RE.match(value):
        return True
    return bool(_PLACEHOLDER_RE.match(value))


def _iter_line_matches(line: str):
    """1 行から (rule, value, filtered_reason) を列挙する。

    `filtered_reason` が None 以外なら、形式は一致したが秘密ではないと機械的に判定した
    もの。呼び出し側で件数を数え、finding には載せない（黙って捨てず counts に残す）。
    値の実体は呼び出し側で必ずマスクする。
    """
    for rule, pattern in _PREFIXED_TOKEN_RULES:
        for match in pattern.finditer(line):
            yield rule, match.group(0), None

    for match in _CONNECTION_STRING_RE.finditer(line):
        yield "connection_string_with_credentials", match.group("secret"), None

    for match in _ASSIGNMENT_RE.finditer(line):
        key = match.group("key")
        value = match.group("value")
        preceding = line[match.start("key") - 1] if match.start("key") > 0 else ""
        if _PATH_LIKE_KEY_RE.search(key) or preceding == "/":
            yield "assignment_to_secret_like_key", value, "path_like"
        elif _CODE_EXPRESSION_RE.search(value) or not _SECRET_CHARSET_RE.match(value):
            yield "assignment_to_secret_like_key", value, "code_expression"
        else:
            yield "assignment_to_secret_like_key", value, None

    for match in _HIGH_ENTROPY_CANDIDATE_RE.finditer(line):
        candidate = match.group(0)
        if _HEX_RE.match(candidate):
            continue
        if shannon_entropy(candidate) >= _ENTROPY_THRESHOLD:
            yield "high_entropy_string", candidate, None


def scan_text(path: str, text: str) -> tuple[list[dict], list[dict], dict[str, int]]:
    """テキストを走査し (findings, suppressed, filtered_counts) を返す。

    同一行・同一値の重複（複数ルールが同じ値に一致する場合）は、最初に一致したルールのみ
    採用する。同じ値を種別違いで二重報告すると、レビュアーの確認作業が水増しされる。
    """
    findings: list[dict] = []
    suppressed: list[dict] = []
    filtered = {"placeholder": 0, "code_expression": 0, "path_like": 0}

    for lineno, line in enumerate(text.splitlines(), start=1):
        if len(line) > MAX_LINE_CHARS:
            line = line[:MAX_LINE_CHARS]
        is_suppressed = SUPPRESS_MARKER in line
        if is_suppressed:
            # マーカー文字列自体を走査対象から外す。`secrets-scan: ignore` は
            # 「秘密らしいキーへの代入」の形をしているため、除かないとマーカーを
            # 置いた行・マーカーを説明した文書が常に自分自身を検出する。
            line = line.replace(SUPPRESS_MARKER, "")

        # 採用済みの値。同じ値の重複に加えて、採用済みの値の部分文字列も除く。
        # 例: JWT 全体を検出したあと、その署名部分が高エントロピー文字列として再び
        # 一致する。同一の秘密を 2 件として数えるとレビュアーの確認作業が水増しされる。
        seen_values: list[str] = []
        for rule, value, reason in _iter_line_matches(line):
            if any(value in seen for seen in seen_values):
                continue
            seen_values.append(value)
            if reason is not None:
                filtered[reason] += 1
                continue
            if _is_placeholder(value):
                filtered["placeholder"] += 1
                continue
            record = {
                "path": path,
                "line": lineno,
                "rule": rule,
                "masked": mask(value),
                "length": len(value),
            }
            (suppressed if is_suppressed else findings).append(record)

    return findings, suppressed, filtered


def _list_target_files(project_root: Path) -> tuple[list[str] | None, str | None]:
    """git 管理下のファイル（追跡 + .gitignore されていない未追跡）を列挙する。

    `.gitignore` 済みのファイルを含めないのは、commit されない＝漏洩経路にならないため。
    逆に未追跡でも ignore されていないものは commit 候補であり対象に含める。
    """
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True,
            timeout=60,
            cwd=project_root,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if proc.returncode != 0:
        return None, proc.stderr.decode("utf-8", errors="replace").strip()

    tokens = [t for t in proc.stdout.split(b"\x00") if t]
    return [t.decode("utf-8", errors="surrogateescape") for t in tokens], None


def scan(project_root: Path, paths: list[str] | None = None) -> dict:
    if paths is None:
        listed, error = _list_target_files(project_root)
        if listed is None:
            return {"status": "error", "error": error}
        paths = listed

    findings: list[dict] = []
    suppressed: list[dict] = []
    skipped: list[dict] = []
    filtered_total = {"placeholder": 0, "code_expression": 0, "path_like": 0}
    scanned = 0

    for rel in paths:
        target = project_root / rel
        try:
            if not target.is_file():
                skipped.append({"path": rel, "reason": "not_a_file"})
                continue
            size = target.stat().st_size
            if size > MAX_FILE_BYTES:
                skipped.append({"path": rel, "reason": "too_large", "bytes": size})
                continue
            raw = target.read_bytes()
        except OSError as exc:
            skipped.append({"path": rel, "reason": f"unreadable: {exc}"})
            continue

        if b"\x00" in raw:
            skipped.append({"path": rel, "reason": "binary"})
            continue

        text = raw.decode("utf-8", errors="replace")
        file_findings, file_suppressed, filtered = scan_text(rel, text)
        findings.extend(file_findings)
        suppressed.extend(file_suppressed)
        for reason, count in filtered.items():
            filtered_total[reason] += count
        scanned += 1

    return {
        "status": "ok",
        "findings": findings,
        "suppressed": suppressed,
        "skipped": skipped,
        "counts": {
            "findings": len(findings),
            "suppressed": len(suppressed),
            "filtered": filtered_total,
            "scanned_files": scanned,
            "skipped_files": len(skipped),
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="機密情報の混入を決定論的に検出する（値はマスクして出力する）",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="走査の起点（既定: カレントディレクトリ）",
    )
    parser.add_argument(
        "--paths-json",
        default=None,
        help=(
            "走査対象のプロジェクトルート相対パスの JSON 配列。"
            "省略時は git 管理下のファイル全体を対象にする"
        ),
    )
    return parser.parse_args(argv)


def main() -> int:
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()

    paths = None
    if args.paths_json is not None:
        try:
            paths = json.loads(args.paths_json)
        except json.JSONDecodeError as exc:
            print(
                json.dumps(
                    {"status": "error", "error": f"--paths-json のパースに失敗: {exc}"},
                    ensure_ascii=False,
                )
            )
            return 1
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            print(
                json.dumps(
                    {"status": "error", "error": "--paths-json は文字列の JSON 配列"},
                    ensure_ascii=False,
                )
            )
            return 1

    result = scan(Path(args.project_root).resolve(), paths)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
