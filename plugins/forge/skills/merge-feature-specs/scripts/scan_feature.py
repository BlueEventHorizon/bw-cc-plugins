#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
feature ディレクトリ (docs/specs/{plugin}/{feature}/) を走査し、
SKILL.md が後続の判断 (永続原則 vs 作業履歴の分離・主題ベース命名) を行うための
構造化情報を JSON で出力する。

出力には以下を含む:
- feature_dir: 対象ディレクトリ絶対パス
- plugin: 推定 plugin 名 (docs/specs/{plugin}/{feature}/ の {plugin})
- feature: feature 名
- files: 各ファイルの kind (requirement / design / plan / inventory / other)、
         検出 ID (REQ-XXX / DES-XXX / INV-XXX / なし)、H1 主題、ファイルサイズ
- main_specs_dirs: main 側の requirements/ design/ plan/ ディレクトリ存在状況
- main_existing_ids: main 側の既存仕様 ID 一覧 (重複防止用)

使用例:
    python3 scan_feature.py docs/specs/forge/io_verb
    python3 scan_feature.py --json docs/specs/forge/io_verb
"""

import argparse
import json
import re
import sys
from pathlib import Path

# forge 慣習のデフォルト。プロジェクトによって異なる場合は --id-prefixes で上書き、
# ID 体系を持たないプロジェクトは --no-id で無効化する。
DEFAULT_ID_PREFIXES = ("REQ", "DES", "INV", "TASK", "FNC", "NFR")
H1_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def build_id_pattern(prefixes: list[str] | tuple[str, ...] | None) -> re.Pattern | None:
    """ID 検出用の正規表現を組み立てる。prefixes が空/None なら ID 検出を無効化。"""
    if not prefixes:
        return None
    # 各 prefix を re.escape してから | で連結 (記号入りの prefix にも耐える)
    alt = "|".join(re.escape(p) for p in prefixes)
    return re.compile(rf"\b({alt})-\d{{3}}(?!\d)")


def detect_kind(path: Path) -> str:
    """ファイルパス・名前から種別を推定する。

    判定優先順位 (上が強い):
      1. plan: 親ディレクトリが "plan" の YAML ファイルのみ
         (plan ディレクトリ外の YAML は SKILL.md Phase 3 の「plan 無条件削除」
          に巻き込まれないよう other 扱いにする)
      2. inventory: ファイル名に "inventory" を含む or "inv-" で始まる
      3. requirement: 親が "requirements" or ファイル名が "req-" で始まる
      4. design: 親が "design" or ファイル名が "des-" で始まる
      5. other: 上記いずれにも該当しない
    """
    name = path.name.lower()
    parent = path.parent.name.lower()
    is_yaml = name.endswith(".yaml") or name.endswith(".yml")

    if parent == "plan" and is_yaml:
        return "plan"
    if "inventory" in name or name.startswith("inv-"):
        return "inventory"
    if parent == "requirements" or name.startswith("req-"):
        return "requirement"
    if parent == "design" or name.startswith("des-"):
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


def collect_main_ids(plugin_root: Path, id_pattern: re.Pattern | None) -> dict:
    """main 側 (requirements/ design/) の既存 ID を回収する。

    id_pattern が None の場合は空 list を返す (ID 体系なしプロジェクト)。
    """
    result: dict = {"requirements": [], "design": [], "plan": []}
    if id_pattern is None:
        return result
    for sub in result.keys():
        d = plugin_root / sub
        if not d.is_dir():
            continue
        for path in sorted(d.iterdir()):
            if not path.is_file():
                continue
            m = id_pattern.search(path.name)
            if m:
                result[sub].append({"id": m.group(0), "file": path.name})
    return result


def resolve_paths(arg: str) -> tuple[Path, Path, str, str]:
    """引数 (相対 or 絶対パス) から feature_dir / plugin_root / plugin / feature を導出。

    想定構造: docs/specs/{plugin}/{feature}/

    存在しない場合は ValueError を投げる (呼び出し側で JSON エラーに整形する)。
    """
    feature_dir = Path(arg).resolve()
    if not feature_dir.is_dir():
        raise ValueError(f"feature directory not found: {feature_dir}")
    plugin_root = feature_dir.parent
    feature = feature_dir.name
    plugin = plugin_root.name
    return feature_dir, plugin_root, plugin, feature


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "feature_path",
        help="feature ディレクトリのパス (例: docs/specs/forge/io_verb)",
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
        "--no-id",
        action="store_true",
        help=(
            "ID 検出を完全に無効化 (ID 体系を持たないプロジェクト用)。"
            "--id-prefixes が同時指定されても本オプションが優先される"
        ),
    )
    args = parser.parse_args()

    if args.no_id:
        prefixes: tuple[str, ...] = ()
    else:
        prefixes = tuple(p.strip() for p in args.id_prefixes.split(",") if p.strip())
    id_pattern = build_id_pattern(prefixes)

    try:
        feature_dir, plugin_root, plugin, feature = resolve_paths(args.feature_path)
        files = scan_files(feature_dir, id_pattern)
        main_existing_ids = collect_main_ids(plugin_root, id_pattern)
    except (ValueError, OSError) as e:
        # forge 慣習: エラーも JSON で出力する (scan_spec_ids.py と同パターン)
        error_payload = {"status": "error", "message": str(e)}
        print(json.dumps(error_payload, ensure_ascii=False, indent=2))
        return 1

    main_dirs = {
        "requirements": (plugin_root / "requirements").is_dir(),
        "design": (plugin_root / "design").is_dir(),
        "plan": (plugin_root / "plan").is_dir(),
    }

    payload = {
        "status": "ok",
        "feature_dir": str(feature_dir),
        "plugin_root": str(plugin_root),
        "plugin": plugin,
        "feature": feature,
        "id_prefixes": list(prefixes),  # AI 側で「ID 体系の有無」を見るための情報
        "files": files,
        "main_specs_dirs": main_dirs,
        "main_existing_ids": main_existing_ids,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
