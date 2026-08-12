#!/usr/bin/env python3
"""review 依頼メッセージ組み立てスクリプト（DES-055）。

`templates/<pattern>_review_request_template.md` を Read し、`{{TOKEN}}` を動的データで
置換して標準出力へ書く。**本スクリプトは散文を持たない。** 依頼本文の文言・レビュー観点の
名指しはすべてテンプレート側にあり、本スクリプトの責務は次の 3 点に限られる。

    1. review_id の生成（作成日時）
    2. 絶対パスの算出（{{PLUGIN_ROOT}} / {{PROJECT_ROOT}}）
    3. 埋め込むデータの検証（fail-closed）

`${CLAUDE_PLUGIN_ROOT}` は SKILL.md がロードされるときにのみ展開される変数であり、
テンプレートを Read した本文の中では展開されない。そのためテンプレートには
`{{PLUGIN_ROOT}}/docs/...` と書き、本スクリプトが実体の絶対パスへ置換する（DES-055 §4.3）。

`secrets` パターンでは例外的に `scan_secrets.py` を import して**自分でスキャンを実行する**。
外部 JSON ファイルを受け取る形（`--scan-results-file`）を廃止したのは、`masked` の形式検証が
「その値が本当にマスクを経たか」の証明にならないためである（実値がたまたまマスク形式に一致
すれば通る）。検証を強めるのではなく、生成元を信頼境界の内側へ移すことで、依頼本文に実値が
載る経路を構造的に無くしている（`sensitive_information_spec.md` §5.3 / DES-055 §8.3）。

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

    # ディレクトリ指定（配下のファイル一覧へ展開せずディレクトリのまま渡す。REQ-013 FNC-1312）
    python3 build_review_request.py --pattern design --project-root <path> \
        --dirs-json '["docs/specs/forge/design"]'

    # 今回の依頼に固有の重点観点を添える（全パターン共通・任意）
    python3 build_review_request.py --pattern branch --project-root <path> \
        --base-branch develop --target-branch feature/x \
        --focus "文書内に記述された他文書への参照リンク"

    # 今回到達すべき範囲と意図的な未実装を添える（全パターン共通・任意・複数行可）
    python3 build_review_request.py --pattern code --project-root <path> \
        --files-json '["src/a.py"]' \
        --scope "$(printf '%s\n' 'a.py の新規作成まで。' '- b.py への組み込み — TASK-008')"

    # 機密情報の混入（対象軸を持たない。スキャンは本スクリプトが内部で実行する）
    python3 build_review_request.py --pattern secrets --project-root <path>

Output:
    標準出力に JSON envelope `{"review_id": "...", "body": "..."}`。
    エラーは stderr + 非ゼロ終了。
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# 対象軸を含む「レビューのパターン」。テンプレートのファイル名に対応する（DES-055 §3）。
RANGE_PATTERNS = ("diff", "branch")
# 利用者が対象を明示指定するパターン。ファイル指定（`--files`）とディレクトリ指定
# （`--dirs`）のどちらでも同じテンプレートを使う（DES-055 §8.4）。
SCOPED_PATTERNS = ("code", "requirement", "design", "plan", "uxui")
# 対象軸を持たないパターン。対象は常にリポジトリ全体であり、利用者が範囲を指定しない。
SCAN_PATTERNS = ("secrets",)
VALID_PATTERNS = RANGE_PATTERNS + SCOPED_PATTERNS + SCAN_PATTERNS

_TOKEN_RE = re.compile(r"\{\{([A-Z_]+)\}\}")

_TEMPLATE_DIR_NAME = "templates"
_NONE_MARKER = "（なし）"
_NO_FOCUS_MARKER = "（指定なし）"
# 到達目標・意図的な未実装が渡されなかったことを表すマーカー。**この語の意味づけ
# （「対象は最終形であるとみなす」）はテンプレート側が書く**（本スクリプトは散文を持たない）。
_NO_SCOPE_MARKER = "（指定なし）"

# 複数行を許す値に対して、行頭が構造行に見える行を拒否するためのパターン。
# markdown の見出しは行頭の空白 3 個までを許容するため、そこまでを見出しとして扱う。
_HEADING_LINE_RE = re.compile(r"^ {0,3}#{1,6}(?:\s|$)")
_FENCE_LINE_RE = re.compile(r"^ {0,3}(?:```|~~~)")
# 行全体（前後の空白を除去後）がこれらで始まる行を拒否する。前者は完了宣言行、
# 共通本文の完了宣言行を偽装する入力は拒否する。バックエンド固有のワイヤヘッダは
# 共通本文の契約ではなく、必要なバックエンドが送信直前に検証する。
_PROTOCOL_LINE_PREFIXES = ("REVIEW_RESULT:",)

# `scan_secrets.py` を同一プロセスで import する（`secrets` パターンのスキャン実行）。
# 本ファイルと同じ `scripts/` に置かれている。
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_secrets  # noqa: E402


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

    ここで扱うのはファイルパス・ブランチ名・重点観点であり、いずれも利用者が指定した値で
    機密ではないため、拒否した値をメッセージに含めて「どれを直すべきか」を示す。
    スキャン結果は本関数を通らない（`_scan_bullet_list` の説明を参照）。
    """
    for value in values:
        if "\n" in value or "\r" in value:
            raise ValueError(f"{label} に改行を含む値は指定できません: {value!r}")


def _reject_structure_lines(label: str, value: str | None) -> None:
    """複数行を許す値の中に、本文の構造を偽装する行がある場合は ValueError を送出する。

    `_reject_newlines` は改行そのものを禁じることで注入を防ぐが、到達目標・意図的な未実装は
    項目が複数になりうるため単一行に収めると読めなくなる。そこで改行は許し、
    **構造として意味を持つ行だけ**を拒否する:

    - 見出し行（`#`〜`######`）— 節を偽装して以降の内容を別の節に見せられる
    - コードフェンス行（``` / ~~~）— 閉じないフェンスで以降の本文を literal に飲み込める
    - `REVIEW_RESULT:` 始まりの行 — 完了宣言行の偽装（共通応答契約）

    CR は行区切りとして扱わず一律拒否する。CR/LF の混在は受信側の行分割と本文の見た目を
    食い違わせるため、許す理由がない。

    拒否時は行番号を添える。値は利用者（または上位 SKILL）が指定したものであり機密ではない。
    """
    if value is None:
        return
    if "\r" in value:
        raise ValueError(f"{label} に CR を含む値は指定できません（改行は LF のみ）")
    for lineno, raw_line in enumerate(value.split("\n"), start=1):
        if _HEADING_LINE_RE.match(raw_line):
            raise ValueError(
                f"{label} の {lineno} 行目が見出し行です（節の偽装を防ぐため拒否します）: "
                f"{raw_line!r}"
            )
        if _FENCE_LINE_RE.match(raw_line):
            raise ValueError(
                f"{label} の {lineno} 行目がコードフェンス行です"
                f"（以降の本文を飲み込むため拒否します）: {raw_line!r}"
            )
        stripped = raw_line.strip()
        for prefix in _PROTOCOL_LINE_PREFIXES:
            if stripped.startswith(prefix):
                raise ValueError(
                    f"{label} の {lineno} 行目が契約行（{prefix}）で始まっています"
                    f"（偽装を防ぐため拒否します）: {raw_line!r}"
                )


def _scan_bullet_list(records: list[dict], empty_marker: str) -> str:
    """スキャン結果のレコード列を箇条書きへ変換する。

    **`records` は同一プロセス内で `scan_secrets.scan()` が生成したものに限る**
    （呼び出し元の責務。`main()` がその生成元を保証する）。したがって `masked` は必ず
    `scan_secrets.mask()` を通っており、**マスク形式の検証は行わない**。

    以前は外部 JSON ファイル（`--scan-results-file`）を受け取り、`masked` の形式を
    正規表現で検証していた。しかし**形式は生成元の証明にならない**（実値がたまたま
    `ABCD***[99文字]` の形であれば通る）ため、検証を強めるのではなく生成元そのものを
    信頼境界の内側へ移した。詳細は DES-055 §8.3。

    **改行の検証は生成元の保証とは独立に必要である [MANDATORY]**。`path` はファイル
    システム由来の値であり、git は改行を含むファイル名を許容する（`scan_secrets.py` は
    `git ls-files -z` の出力を扱うためそれをそのまま載せる）。したがって「正規のスキャン
    結果」のままでもセクション構造・完了宣言行を偽装できる。マスクが保証されることと、
    データが構造を壊さないことは別問題であり、後者はここで防ぐ。
    """
    if not records:
        return empty_marker

    lines = []
    for index, record in enumerate(records):
        # 拒否理由に値を含めない（`masked` は検出値の先頭を含み、`path` も混入箇所の
        # 手がかりになる）。位置だけを示す。`sensitive_information_spec.md` §5.3。
        for key in ("path", "rule", "masked"):
            if "\n" in record[key] or "\r" in record[key]:
                raise ValueError(
                    f"スキャン結果 {index} 番目の {key} に改行が含まれています"
                    "（本文構造を偽装しうるため拒否します。値は表示しません）"
                )
        lines.append(
            f"- `{record['path']}:{record['line']}` "
            f"種別: {record['rule']} / 値: {record['masked']}"
        )
    return "\n".join(lines)


def _scan_stats_block(counts: dict) -> str:
    """走査統計を人が読める箇条書きにする。数値の転記のみで判断を持たない。

    `counts` も `scan_secrets.scan()` の出力であり（`_scan_bullet_list` と同じ前提）、
    スキーマ検証は行わない。
    """
    filtered = counts["filtered"]
    return "\n".join(
        [
            f"- 走査ファイル数: {counts['scanned_files']}",
            f"- スキップ: {counts['skipped_files']} 件（バイナリ・サイズ超過・読み取り不可）",
            f"- 検出: {counts['findings']} 件 / 抑制マーカー付き: {counts['suppressed']} 件",
            "- filtered（機械的に秘密でないと判定）: "
            f"プレースホルダ {filtered['placeholder']} / "
            f"コード式 {filtered['code_expression']} / "
            f"パス様のキー {filtered['path_like']} / "
            f"定数名 {filtered['constant_name']}",
        ]
    )


def _absolute_bullet_list(project_root_abs: str, paths: list[str], suffix: str = "") -> str:
    """プロジェクトルート相対パスを絶対パスの箇条書きへ変換する。空なら不在を明示する。

    レビュアーは別プロセスであり cwd が一致する保証がないため、本文に載せるパスは
    すべて絶対にする（DES-055 §4.3）。対象ファイル・ルール文書・仕様書で扱いを
    分けない（片方だけ相対だと、レビュアーが解決に失敗した理由が分かりにくい）。

    `suffix` はディレクトリ指定で `/` を付けるために使う。パスがファイルかディレクトリ
    かをレビュアーが本文から判別できるようにするための整形であり、散文ではない
    （DES-055 §2.1 の「スクリプトは散文を持たない」に触れない）。
    """
    if not paths:
        return _NONE_MARKER
    return "\n".join(f"- {project_root_abs}/{p}{suffix}" for p in paths)


def build_body(
    pattern: str,
    project_root: Path,
    files: list[str] | None = None,
    dirs: list[str] | None = None,
    base_branch: str | None = None,
    target_branch: str | None = None,
    project_rules: list[str] | None = None,
    project_specs: list[str] | None = None,
    focus: str | None = None,
    scope: str | None = None,
) -> str:
    """テンプレートを読み、トークンを置換した依頼本文を返す。

    契約違反（未知パターン / 改行混入 / 絶対パス混入 / 必須データ欠落 / テンプレートの
    トークン書き損じ / テンプレートが要求しないデータ）はすべて ValueError を送出する
    （fail-closed）。トークン検査はいずれも**テンプレートに対して**行い、置換後の本文は
    走査しない（値に含まれる波括弧を誤検知しないため）。

    **スキャン結果を引数で受け取らない [MANDATORY]**。`secrets` パターンでは本関数が
    `scan_secrets.scan()` を直接呼ぶ。呼び出し元がスキャン結果を渡せる引数を持たせると、
    「外部由来の値を本文へ載せる経路」が CLI から Python API へ移るだけで、マスクを経ない
    値が本文に入る可能性が残る（DES-055 §8.3）。テストでスキャン結果を制御する場合は
    `scan_secrets.scan` を mock する。
    """
    if pattern not in VALID_PATTERNS:
        raise ValueError(
            f"不明なパターンです: {pattern!r}（有効: {', '.join(VALID_PATTERNS)}）"
        )

    files = files or []
    dirs = dirs or []
    project_rules = project_rules or []
    project_specs = project_specs or []

    _reject_newlines("対象ファイル一覧", files)
    _reject_newlines("対象ディレクトリ一覧", dirs)
    _reject_newlines("プロジェクトルール一覧", project_rules)
    _reject_newlines("プロジェクト仕様書一覧", project_specs)
    _reject_newlines(
        "ブランチ名", [b for b in (base_branch, target_branch) if b is not None]
    )
    # 重点観点は利用者の自然文をそのまま埋め込む唯一の値であり、改行を許すと見出し行・
    # 完了宣言行を偽装できる。単一行に限定して受け取る（SKILL 側で1行へ要約する）。
    _reject_newlines("重点観点", [focus] if focus is not None else [])
    # 到達目標・意図的な未実装は複数行を許す（項目が複数になりうる）。改行を一律拒否する
    # 代わりに、構造行の偽装のみを拒否する。
    _reject_structure_lines("到達目標と意図的な未実装", scope)

    for label, paths in (
        ("対象ファイル", files),
        ("対象ディレクトリ", dirs),
        ("プロジェクトルール", project_rules),
        ("プロジェクト仕様書", project_specs),
    ):
        for p in paths:
            if Path(p).is_absolute():
                raise ValueError(
                    f"{label}はプロジェクトルート相対パスで渡してください: {p!r}"
                )

    if pattern in RANGE_PATTERNS and (files or dirs):
        raise ValueError(
            f"{pattern} は範囲指定のため対象ファイル一覧・対象ディレクトリ一覧を渡せません"
            "（範囲指定をファイル一覧へ展開しない。REQ-013 FNC-1312）"
        )
    if pattern in SCOPED_PATTERNS:
        # ファイル指定とディレクトリ指定は対象軸として排他である（SKILL 側でも二重指定は
        # エラー終了する）。両方渡された場合にどちらを本文へ載せるかを推定しない。
        if files and dirs:
            raise ValueError(
                f"{pattern} に対象ファイル一覧と対象ディレクトリ一覧の両方を渡せません"
                "（対象軸は排他です）"
            )
        if not files and not dirs:
            raise ValueError(
                f"{pattern} には対象ファイル一覧または対象ディレクトリ一覧が必要です"
            )
    scan_result = None
    if pattern in SCAN_PATTERNS:
        if files or dirs:
            raise ValueError(
                f"{pattern} は対象軸を持たない（常にリポジトリ全体）ため"
                "対象ファイル一覧・対象ディレクトリ一覧を渡せません"
            )
        # スキャンはここで実行する。結果を引数で受け取らないことが、マスクを経ない値が
        # 本文へ入らないことの根拠になっている（DES-055 §8.3）。
        scan_result = scan_secrets.scan(project_root)
        if scan_result.get("status") != "ok":
            # スキャンできなかったまま依頼を送ると、二段構えの片方を黙って落とすことになる
            # （`sensitive_information_spec.md` §5.1）。fail closed とする。
            raise ValueError(
                "スキャンが失敗しています。依頼を組み立てません: "
                f"{scan_result.get('error', '理由不明')}"
            )
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
        "REVIEW_TYPE": pattern,
        "PLUGIN_ROOT": str(plugin_root()),
        "PROJECT_ROOT": project_root_abs,
        "PROJECT_RULES": _absolute_bullet_list(project_root_abs, project_rules),
        "PROJECT_SPECS": _absolute_bullet_list(project_root_abs, project_specs),
        # 対象軸がファイルでもディレクトリでも同一のトークンへ載せる。指定粒度のまま
        # 渡すため、ディレクトリを配下ファイルへ展開しない（REQ-013 FNC-1312）。
        "TARGET_PATHS": (
            _absolute_bullet_list(project_root_abs, dirs, suffix="/")
            if dirs
            else _absolute_bullet_list(project_root_abs, files)
        ),
        "FOCUS": (focus or "").strip() or _NO_FOCUS_MARKER,
        "SCOPE": (scope or "").strip() or _NO_SCOPE_MARKER,
        "SCAN_FINDINGS": _scan_bullet_list(
            (scan_result or {}).get("findings") or [], "（検出なし）"
        ),
        "SCAN_SUPPRESSED": _scan_bullet_list(
            (scan_result or {}).get("suppressed") or [], "（抑制マーカー付きの検出なし）"
        ),
        "SCAN_STATS": (
            _scan_stats_block(scan_result["counts"])
            if pattern in SCAN_PATTERNS
            else _NONE_MARKER
        ),
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

    # 渡された値をテンプレートが受け取らない場合は黙って捨てず、エラーにする。到達目標を
    # 渡したつもりでレビュアーに届いていない状態は、渡せていないことに気付けないため
    # 「渡さなかった場合」より悪い。
    if (scope or "").strip() and "SCOPE" not in used:
        raise ValueError(
            f"テンプレート {path.name} は到達目標と意図的な未実装を受け取りません"
            "（{{SCOPE}} を持たないテンプレートに --scope を渡せません）"
        )

    # テンプレート側の書き損じ（`{{lowercase}}` のように _TOKEN_RE に合致しない波括弧）を
    # **置換前に**検出する。置換後の本文を走査すると、`--focus` / `--scope` の値に含まれる
    # 波括弧をテンプレート由来の未消化トークンと誤認する（実運用で踏んだ。トークン名を
    # 議論する依頼——例:「SCOPE と TARGET_PATHS の使い分けを重点的に」——が通らなくなり、
    # かつエラーが原因をテンプレートだと誤って指す）。
    #
    # 上の検査で「テンプレートが使う正規トークンはすべて values に存在する」ことは確認済み
    # なので、正規トークンを取り除いてなお `{{` が残れば、それはテンプレートの書き損じである。
    if "{{" in _TOKEN_RE.sub("", template):
        raise ValueError(
            f"テンプレート {path.name} に、トークンとして解釈できない波括弧が残っています"
            "（トークンは {{UPPER_SNAKE_CASE}} 形式で書いてください）"
        )

    # 値は再置換されない（sub はテンプレートを 1 度走査するのみ）。したがって値に含まれる
    # 波括弧が新たなトークンとして展開されることはなく、そのまま本文のテキストになる。
    body = _TOKEN_RE.sub(lambda m: values[m.group(1)], template)

    return body


#: `review_id` の書式。作成日時（年月日・時分秒・ミリ秒）で表す。
#:
#: **識別子に要るのは一意性だけではない [MANDATORY]**。以前は `uuid4().hex` の 32 桁
#: だったが、会話でもファイルの見出しでも誰も読まない文字列だった。作成時刻なら
#: いつのレビューかが読んで分かり、並べれば時系列になる。
#:
#: **ミリ秒まで持つ [MANDATORY]**。秒までに落とすと、続けて起動した 2 回のレビューが
#: 同じ識別子になる。そうなると仕分けファイルの混入ガード（既存ファイルの `review_id`
#: と食い違えば止める）が素通りし、前のレビューの所見へ今回の所見が追記される。
#: **人が読める短さのために一意性を削ってはならない**——読みやすさは末尾 3 桁では
#: ほとんど損なわれないが、衝突の実害は静かで大きい。
#:
#: **ファイル名の部品にしないこと**（コロンを含むため）。仕分けファイルは名前を
#: 固定して `review_id` を中身へ持たせる設計であり、この制約と整合している。
REVIEW_ID_FORMAT = "%Y-%m%d-%H:%M:%S.%f"


def new_review_id(now: datetime | None = None) -> str:
    # `%f` はマイクロ秒 6 桁を返す。ミリ秒 3 桁へ落として読みやすさを保つ。
    return (now or datetime.now()).strftime(REVIEW_ID_FORMAT)[:-3]


def build_request(
    pattern: str,
    project_root: Path,
    *,
    review_id: str | None = None,
    **kwargs,
) -> dict:
    """バックエンド非依存の依頼 envelope を構築する。"""
    request_id = review_id or new_review_id()
    return {
        "review_id": request_id,
        "body": build_body(pattern=pattern, project_root=project_root, **kwargs),
    }


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
        "--dirs-json",
        default=None,
        help=(
            "対象ディレクトリ一覧（プロジェクトルート相対）の JSON 配列。"
            "ディレクトリ指定パターンでのみ使う。`--files-json` とは排他。"
            "配下のファイル一覧へ展開せず、ディレクトリのまま本文へ載せる"
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
    parser.add_argument(
        "--focus",
        default=None,
        help=(
            "今回の依頼に固有の重点観点（自然文・単一行）。"
            "内蔵の観点文書を置き換えるものではなく、加えて重点的に見る対象を伝える"
        ),
    )
    parser.add_argument(
        "--scope",
        default=None,
        help=(
            "今回の変更が到達すべき範囲と、意図的に含めなかった項目（複数行可）。"
            "見出し行・コードフェンス行・契約行（REVIEW_RESULT:）で"
            "始まる行は拒否する。未指定なら依頼本文は「（指定なし）」になる"
        ),
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
    dirs = _load_path_list(args.dirs_json, "--dirs-json")
    project_rules = _load_path_list(args.project_rules_json, "--project-rules-json")
    project_specs = _load_path_list(args.project_specs_json, "--project-specs-json")
    if files is None or dirs is None or project_rules is None or project_specs is None:
        return 1

    try:
        envelope = build_request(
            pattern=args.pattern,
            project_root=Path(args.project_root),
            files=files,
            dirs=dirs,
            base_branch=args.base_branch,
            target_branch=args.target_branch,
            project_rules=project_rules,
            project_specs=project_specs,
            focus=args.focus,
            scope=args.scope,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(envelope, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
