#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
feature ディレクトリ (例: docs/specs/{feature}/, docs/specs/{plugin}/{feature}/) を走査し、
SKILL.md が後続の判断 (永続原則 vs 作業履歴の分離・主題ベース命名) を行うための
構造化情報を JSON で出力する。

main 仕様棚 (main_specs_root) は以下の優先順で決定する:
  1. --main-specs-root が指定されていればそれ
  2. それ以外は feature_dir.parent

ID 検出はデフォルトで forge 慣習 (REQ-001 等の 3 桁 / ハイフン区切り) を使う。
別フォーマットのプロジェクトは --id-digits / --id-separator / --no-id で調整する。

出力には以下を含む:
- feature_dir / feature_name
- main_specs_root (絶対パス)
- main_specs_dirs: main 側の requirements/ design/ plan/ ディレクトリ存在状況
- main_existing_ids: main 側の既存 ID 一覧 (重複防止用)
- files: 各ファイルの kind / 検出 ID / H1 主題 / サイズ / 行数
- warnings: 構造に関する警告 (main_specs_root が空・requirements/design 未配置 等)

互換のため plugin (= main_specs_root.name) フィールドも併存する。

使用例:
    python3 scan_feature.py docs/specs/forge/io_verb
    python3 scan_feature.py docs/specs/auth --main-specs-root docs/specs
    python3 scan_feature.py docs/specs/auth --no-id
    python3 scan_feature.py docs/specs/auth --id-prefixes RFC,ADR --id-digits 4
"""

import argparse
import json
import re
import sys
from pathlib import Path

# forge 慣習のデフォルト。プロジェクトによって異なる場合は --id-prefixes で上書き、
# ID 体系を持たないプロジェクトは --no-id で無効化する。
DEFAULT_ID_PREFIXES = ("REQ", "DES", "INV", "TASK", "FNC", "NFR")
DEFAULT_ID_DIGITS = 3
DEFAULT_ID_SEPARATOR = "-"
H1_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def build_id_pattern(
    prefixes: list[str] | tuple[str, ...] | None,
    digits: int = DEFAULT_ID_DIGITS,
    separator: str = DEFAULT_ID_SEPARATOR,
) -> re.Pattern | None:
    """ID 検出用の正規表現を組み立てる。

    prefixes が空/None なら ID 検出を無効化。
    digits は 1 以上、separator は 1 文字以上の文字列。
    """
    if not prefixes:
        return None
    if digits < 1:
        raise ValueError(f"digits must be >= 1 (got {digits})")
    if not separator:
        raise ValueError("separator must not be empty")
    alt = "|".join(re.escape(p) for p in prefixes)
    sep = re.escape(separator)
    # 桁数固定マッチ。後続が数字の場合 (桁数超過) を弾くため (?!\d) を付ける
    return re.compile(rf"\b({alt}){sep}\d{{{digits}}}(?!\d)")


def detect_kind(path: Path) -> str:
    """ファイルパス・名前から種別を推定する。

    判定優先順位 (上が強い):
      1. plan: 親ディレクトリが "plan" の YAML ファイルのみ
         (plan ディレクトリ外の YAML は SKILL.md Phase 3 の「plan 無条件削除」
          に巻き込まれないよう other 扱いにする)
      2. inventory: ファイル名に "inventory" を含む or "inv-" / "inv_" で始まる
      3. requirement: 親が "requirements" / "requirement" or ファイル名が "req-" / "req_" で始まる
      4. design: 親が "design" or ファイル名が "des-" / "des_" で始まる
      5. other: 上記いずれにも該当しない
    """
    name = path.name.lower()
    parent = path.parent.name.lower()
    is_yaml = name.endswith(".yaml") or name.endswith(".yml")

    if parent == "plan" and is_yaml:
        return "plan"
    if "inventory" in name or name.startswith("inv-") or name.startswith("inv_"):
        return "inventory"
    if parent in ("requirements", "requirement") or name.startswith("req-") or name.startswith("req_"):
        return "requirement"
    if parent == "design" or name.startswith("des-") or name.startswith("des_"):
        return "design"
    return "other"


def detect_id(path: Path, content: str, id_pattern: re.Pattern | None) -> str | None:
    """ファイル名 → 本文先頭 200 行の順で ID を探す。

    id_pattern が None の場合 (ID 体系を持たないプロジェクト) は常に None を返す。
    """
    if id_pattern is None:
        return None
    name_match = id_pattern.search(path.name)
    if name_match:
        return name_match.group(0)
    head = "\n".join(content.splitlines()[:200])
    body_match = id_pattern.search(head)
    if body_match:
        return body_match.group(0)
    return None


def extract_h1(content: str) -> str | None:
    m = H1_PATTERN.search(content)
    if not m:
        return None
    return m.group(1).strip()


def scan_files(feature_dir: Path, id_pattern: re.Pattern | None) -> list[dict]:
    files: list[dict] = []
    for path in sorted(feature_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(feature_dir)
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            content = ""
        files.append(
            {
                "rel_path": str(rel),
                "abs_path": str(path),
                "kind": detect_kind(path),
                "id": detect_id(path, content, id_pattern),
                "h1": extract_h1(content),
                "size": path.stat().st_size,
                "lines": content.count("\n") + (1 if content else 0),
            }
        )
    return files


def collect_main_ids(main_specs_root: Path, id_pattern: re.Pattern | None) -> dict:
    """main 仕様棚の既存 ID を回収する (requirements/ design/ plan/ 配下)。

    id_pattern が None の場合は空 list を返す (ID 体系なしプロジェクト)。
    requirement / requirements の両表記を許容する。
    """
    result: dict = {"requirements": [], "design": [], "plan": []}
    if id_pattern is None:
        return result

    aliases = {
        "requirements": ("requirements", "requirement"),
        "design": ("design",),
        "plan": ("plan",),
    }

    for canonical, candidates in aliases.items():
        for sub in candidates:
            d = main_specs_root / sub
            if not d.is_dir():
                continue
            for path in sorted(d.iterdir()):
                if not path.is_file():
                    continue
                m = id_pattern.search(path.name)
                if m:
                    result[canonical].append({"id": m.group(0), "file": path.name})
            # 最初に見つかったエイリアスを採用
            if result[canonical]:
                break
    return result


def detect_main_dirs(main_specs_root: Path) -> dict:
    """main 仕様棚に requirements/ design/ plan/ ディレクトリが存在するか判定する。

    requirement / requirements の両方を許容する。
    """
    return {
        "requirements": (main_specs_root / "requirements").is_dir()
        or (main_specs_root / "requirement").is_dir(),
        "design": (main_specs_root / "design").is_dir(),
        "plan": (main_specs_root / "plan").is_dir(),
    }


def resolve_paths(
    feature_path: str,
    main_specs_root_arg: str | None = None,
) -> tuple[Path, Path, str]:
    """引数 (相対 or 絶対パス) から feature_dir / main_specs_root / feature_name を導出。

    main_specs_root の決定優先順:
      1. main_specs_root_arg が指定されればそれ
      2. それ以外は feature_dir.parent

    plugin 階層という概念は本関数の責務ではない (呼び出し側が必要なら main_specs_root.name から取得)。

    存在しない場合は ValueError を投げる (呼び出し側で JSON エラーに整形する)。
    """
    feature_dir = Path(feature_path).resolve()
    if not feature_dir.is_dir():
        raise ValueError(f"feature directory not found: {feature_dir}")

    if main_specs_root_arg:
        main_specs_root = Path(main_specs_root_arg).resolve()
        if not main_specs_root.is_dir():
            raise ValueError(f"main-specs-root not found: {main_specs_root}")
    else:
        main_specs_root = feature_dir.parent

    feature_name = feature_dir.name
    return feature_dir, main_specs_root, feature_name


def build_warnings(main_specs_root: Path, main_dirs: dict, feature_dir: Path) -> list[str]:
    """構造的な問題を warnings として返す (エラーではないが SKILL.md の判断材料になる)。"""
    warnings: list[str] = []
    if not any(main_dirs.values()):
        warnings.append(
            f"main_specs_root ({main_specs_root}) に requirements/ design/ plan/ "
            f"のいずれも存在しません。--main-specs-root を明示するか、ディレクトリを先に作成してください"
        )
    if main_specs_root == feature_dir:
        warnings.append(
            "main_specs_root が feature_dir と同一です。--main-specs-root で別ディレクトリを指定してください"
        )
    if main_specs_root in feature_dir.parents and main_specs_root.parent == feature_dir.parent:
        # まれなケース: feature の祖先と兄弟が同じ階層
        pass
    return warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "feature_path",
        help="feature ディレクトリのパス (例: docs/specs/forge/io_verb, docs/specs/auth)",
    )
    parser.add_argument(
        "--main-specs-root",
        default=None,
        help=(
            "main 仕様棚のディレクトリ (例: docs/specs/forge)。"
            "省略時は feature_dir.parent。"
            "plugin 階層なしプロジェクトで feature の親が main 仕様棚にならない場合に指定する"
        ),
    )
    parser.add_argument(
        "--id-prefixes",
        default=",".join(DEFAULT_ID_PREFIXES),
        help=(
            "ID プレフィックスをカンマ区切りで指定 "
            f"(デフォルト: {','.join(DEFAULT_ID_PREFIXES)} — forge 慣習)。"
            "例: --id-prefixes RFC,ADR,SPEC"
        ),
    )
    parser.add_argument(
        "--id-digits",
        type=int,
        default=DEFAULT_ID_DIGITS,
        help=f"ID の数字部分の桁数 (デフォルト: {DEFAULT_ID_DIGITS})。例: --id-digits 4",
    )
    parser.add_argument(
        "--id-separator",
        default=DEFAULT_ID_SEPARATOR,
        help=(
            f"プレフィックスと数字を区切る文字 (デフォルト: '{DEFAULT_ID_SEPARATOR}')。"
            "例: --id-separator _"
        ),
    )
    parser.add_argument(
        "--no-id",
        action="store_true",
        help=(
            "ID 検出を完全に無効化 (ID 体系を持たないプロジェクト用)。"
            "--id-prefixes / --id-digits / --id-separator が同時指定されても本オプションが優先される"
        ),
    )
    args = parser.parse_args()

    if args.no_id:
        prefixes: tuple[str, ...] = ()
    else:
        prefixes = tuple(p.strip() for p in args.id_prefixes.split(",") if p.strip())

    try:
        id_pattern = build_id_pattern(prefixes, digits=args.id_digits, separator=args.id_separator)
        feature_dir, main_specs_root, feature_name = resolve_paths(
            args.feature_path,
            main_specs_root_arg=args.main_specs_root,
        )
        files = scan_files(feature_dir, id_pattern)
        main_existing_ids = collect_main_ids(main_specs_root, id_pattern)
    except (ValueError, OSError) as e:
        # forge 慣習: エラーも JSON で出力する (scan_spec_ids.py と同パターン)
        error_payload = {"status": "error", "message": str(e)}
        print(json.dumps(error_payload, ensure_ascii=False, indent=2))
        return 1

    main_dirs = detect_main_dirs(main_specs_root)
    warnings = build_warnings(main_specs_root, main_dirs, feature_dir)

    payload = {
        "status": "ok",
        "feature_dir": str(feature_dir),
        "feature_name": feature_name,
        "main_specs_root": str(main_specs_root),
        # 後方互換: 旧フィールド名 (plugin / plugin_root / feature)
        "plugin": main_specs_root.name,
        "plugin_root": str(main_specs_root),
        "feature": feature_name,
        "id_prefixes": list(prefixes),  # AI 側で「ID 体系の有無」を見るための情報
        "id_digits": args.id_digits if prefixes else None,
        "id_separator": args.id_separator if prefixes else None,
        "files": files,
        "main_specs_dirs": main_dirs,
        "main_existing_ids": main_existing_ids,
        "warnings": warnings,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
