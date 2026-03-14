#!/usr/bin/env python3
"""
レビュー対象の検出と種別判定スクリプト

.doc_structure.yaml を参照してプロジェクト構造を把握し、
レビュー対象ファイル・種別を特定する。
.doc_structure.yaml がない場合はエラーを返す。

パース処理は resolve_doc_structure.py に委譲する。
標準ライブラリのみ使用（pyyaml 不要）。

Usage:
  python3 resolve_review_context.py [target1] [target2] ...

  target: ファイルパス（複数可）、ディレクトリパス、Feature名、または省略
  フラグ（--codex, --claude, --auto-fix）は無視される

Output (JSON):
  {
    "status": "resolved" | "needs_input" | "error",
    "has_doc_structure": true | false,
    "type": "requirement" | "design" | "code" | "plan" | "generic" | null,
    "target_files": ["path1", ...],
    "features": ["feature1", ...],
    "questions": [
      {"key": "type|feature|target", "message": "...", "options": [...]}
    ],
    "error": "エラーメッセージ（status=error 時のみ）"
  }
"""

import glob
import json
import os
import sys
from pathlib import Path

# resolve_doc_structure.py からパーサーをインポート
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', 'doc-structure', 'scripts'
))
from resolve_doc_structure import (
    load_doc_structure,
    resolve_files,
    resolve_files_by_doc_type,
    detect_features,
    match_path_to_doc_type,
    invert_doc_types_map,
    expand_globs,
    find_project_root as _find_project_root,
)

# ソースコード拡張子（汎用）
CODE_EXTENSIONS = {'.swift', '.kt', '.java', '.ts', '.tsx', '.js', '.jsx',
                   '.py', '.go', '.rs', '.c', '.cpp', '.h', '.m', '.mm'}

# generic 種別の基盤文書パターン（rules パスは doc_structure から動的取得）
GENERIC_BASE_PATTERNS = [
    '.claude/skills/',
    '.claude/commands/',
]
GENERIC_ROOT_FILES = {'CLAUDE.md', 'README.md'}

# specs doc_type → review type マッピング
SPECS_REVIEW_TYPE_MAP = {
    'requirement': 'requirement',
    'design': 'design',
    'plan': 'plan',
}


# ---------------------------------------------------------------------------
# doc_structure パーサー（resolve_doc_structure.py に委譲）
# ---------------------------------------------------------------------------

def parse_doc_structure(project_root):
    """.doc_structure.yaml を読み込み。存在しなければ None を返す。

    resolve_doc_structure.load_doc_structure() のラッパー。
    戻り値は config dict（新形式: root_dirs / doc_types_map / patterns）。
    """
    try:
        config, _ = load_doc_structure(str(project_root))
        return config
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"警告: .doc_structure.yaml のパースに失敗しました: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# doc_type → review type マッピング
# ---------------------------------------------------------------------------

def _doc_type_to_review_type(doc_type_name):
    """doc_type 名からレビュー種別を返す"""
    return SPECS_REVIEW_TYPE_MAP.get(doc_type_name, 'generic')


# ---------------------------------------------------------------------------
# パスマッチング・種別判定
# ---------------------------------------------------------------------------

def detect_type_from_doc_structure(path_str, doc_structure, project_root):
    """doc_structure のパス定義を使ってファイルの種別を判定。

    新形式では match_path_to_doc_type() で specs の doc_types_map を検索し、
    rules の root_dirs にマッチすれば generic を返す。
    """
    if not doc_structure:
        return None

    # specs の doc_types_map で判定
    specs = doc_structure.get('specs', {})
    doc_types_map = specs.get('doc_types_map', {})
    if doc_types_map:
        doc_type = match_path_to_doc_type(path_str, doc_types_map, str(project_root))
        if doc_type:
            return _doc_type_to_review_type(doc_type)

    # rules の root_dirs で判定
    rules = doc_structure.get('rules', {})
    rules_root_dirs = rules.get('root_dirs', [])
    for root_dir in rules_root_dirs:
        pattern = root_dir.rstrip('/')
        if path_str.startswith(pattern + '/') or path_str.startswith(pattern + os.sep):
            return 'generic'

    return None


def get_rules_paths(doc_structure):
    """rules カテゴリの全パスを取得（新形式: root_dirs を返す）"""
    if not doc_structure:
        return []
    return list(doc_structure.get('rules', {}).get('root_dirs', []))


def get_specs_paths_by_type(doc_structure, review_type):
    """指定 review type に対応する specs パスを取得。

    新形式では doc_types_map を逆引きして、review type に対応するパスを返す。
    """
    if not doc_structure:
        return []
    specs = doc_structure.get('specs', {})
    doc_types_map = specs.get('doc_types_map', {})
    inverted = invert_doc_types_map(doc_types_map)

    # review type → doc_type: SPECS_REVIEW_TYPE_MAP の逆引き
    for doc_type_name, r_type in SPECS_REVIEW_TYPE_MAP.items():
        if r_type == review_type:
            return list(inverted.get(doc_type_name, []))
    return []


# ---------------------------------------------------------------------------
# Feature 検出
# ---------------------------------------------------------------------------

def detect_features_from_doc_structure(project_root, doc_structure):
    """doc_structure から Feature 名を抽出。resolve_doc_structure.detect_features() に委譲"""
    if not doc_structure:
        return []
    return detect_features(doc_structure, str(project_root))


# ---------------------------------------------------------------------------
# 共通ユーティリティ
# ---------------------------------------------------------------------------

def parse_args():
    """引数を解析（フラグと対象を分離）"""
    targets = []
    for arg in sys.argv[1:]:
        if arg.startswith('--'):
            continue
        targets.append(arg)
    return targets


def find_project_root():
    """プロジェクトルートを検出"""
    try:
        root = _find_project_root()
        return Path(root)
    except RuntimeError:
        return Path.cwd()


# ---------------------------------------------------------------------------
# Exclude 判定（generic 種別判定で使用）
# ---------------------------------------------------------------------------

def _get_all_excludes(doc_structure, category):
    """カテゴリ内の全 exclude パターンを集約（新形式）"""
    if not doc_structure:
        return set()
    section = doc_structure.get(category, {})
    patterns = section.get('patterns', {})
    return set(patterns.get('exclude', []))


def _is_excluded(path_str, exclude_set):
    """パス内のいずれかのコンポーネントが exclude リストにマッチするか判定"""
    if not exclude_set:
        return False
    parts = path_str.replace('\\', '/').split('/')
    return any(part in exclude_set for part in parts)


# ---------------------------------------------------------------------------
# 種別判定
# ---------------------------------------------------------------------------

def _detect_generic_type(path_str, doc_structure=None):
    """generic 種別の判定（基盤文書パターン）"""
    # rules パスを doc_structure から動的取得
    rules_paths = get_rules_paths(doc_structure) if doc_structure else ['rules/']
    rules_excludes = _get_all_excludes(doc_structure, 'rules')
    all_patterns = GENERIC_BASE_PATTERNS + rules_paths

    for pattern in all_patterns:
        if path_str.startswith(pattern) or f'/{pattern}' in path_str:
            if not _is_excluded(path_str, rules_excludes):
                return "generic"

    filename = Path(path_str).name
    if filename in GENERIC_ROOT_FILES and '/' not in path_str.rstrip('/'):
        return "generic"
    return None


def detect_type_from_path(path_str, doc_structure, project_root):
    """パスから種別を判定"""
    # 1. コードファイル判定（拡張子ベース）
    _, ext = os.path.splitext(path_str)
    if ext.lower() in CODE_EXTENSIONS:
        return "code"

    # 2. .doc_structure.yaml パスマッチ
    ds_type = detect_type_from_doc_structure(path_str, doc_structure, project_root)
    if ds_type:
        return ds_type

    # 3. 基盤文書パターン → generic
    generic_type = _detect_generic_type(path_str, doc_structure)
    if generic_type:
        return generic_type

    return None


def detect_type_from_dir(dir_path, doc_structure, project_root):
    """ディレクトリ内のファイルから種別を判定"""
    dir_p = project_root / dir_path
    if not dir_p.is_dir():
        return None, []

    code_files = []
    for ext in CODE_EXTENSIONS:
        code_files.extend(glob.glob(str(dir_p / '**' / f'*{ext}'), recursive=True))

    md_files = sorted(glob.glob(str(dir_p / '**' / '*.md'), recursive=True))

    if code_files:
        # コード+md 混在（src/ に README.md がある等）も code として扱う
        rel_files = [str(Path(f).relative_to(project_root)) for f in code_files]
        return "code", sorted(rel_files)
    elif md_files:
        first_rel = str(Path(md_files[0]).relative_to(project_root))
        review_type = detect_type_from_path(first_rel, doc_structure, project_root)
        rel_files = [str(Path(f).relative_to(project_root)) for f in md_files]
        return review_type, sorted(rel_files)

    return None, []


# ---------------------------------------------------------------------------
# Feature 解決
# ---------------------------------------------------------------------------

def find_feature_subdirs(project_root, doc_structure, feature):
    """Feature 内で存在する種別サブディレクトリを検出。

    新形式では doc_types_map を逆引きして glob 展開し、
    feature 名にマッチするディレクトリを探索する。
    """
    available = []
    if not doc_structure:
        return available

    specs = doc_structure.get('specs', {})
    doc_types_map = specs.get('doc_types_map', {})
    exclude_patterns = specs.get('patterns', {}).get('exclude', [])

    if feature in exclude_patterns:
        return available

    inverted = invert_doc_types_map(doc_types_map)

    for doc_type_name, paths in inverted.items():
        review_type = _doc_type_to_review_type(doc_type_name)
        # glob パターンを展開して feature にマッチするか確認
        expanded = expand_globs(paths, str(project_root))
        for expanded_path in expanded:
            # 展開後のパスに feature 名が含まれているか確認
            parts = expanded_path.rstrip('/').split('/')
            if feature in parts:
                concrete_dir = project_root / expanded_path.rstrip('/')
                if concrete_dir.is_dir() and any(concrete_dir.rglob('*.md')):
                    if review_type not in available:
                        available.append(review_type)
                    break  # この doc_type は確定

    return available


def find_target_files(project_root, doc_structure, feature, review_type):
    """Feature + 種別からファイル一覧を取得。

    新形式では resolve_files_by_doc_type() を使い、
    結果から feature 名を含むパスだけをフィルタリングする。
    """
    if not doc_structure:
        return []

    # review type → doc_type の逆引き
    doc_type = None
    for dt_name, r_type in SPECS_REVIEW_TYPE_MAP.items():
        if r_type == review_type:
            doc_type = dt_name
            break

    if not doc_type:
        return []

    all_files = resolve_files_by_doc_type(
        doc_structure, 'specs', doc_type, str(project_root)
    )

    # feature 名を含むファイルのみフィルタ
    return [f for f in all_files if f'/{feature}/' in f'/{f}']


# ---------------------------------------------------------------------------
# 対象解決
# ---------------------------------------------------------------------------

def _resolve_single_target(target, doc_structure, project_root, features, result):
    """単一の対象（ファイル/ディレクトリ/Feature名）を解決"""
    target_path = Path(target)

    if (project_root / target_path).is_file():
        result["type"] = detect_type_from_path(target, doc_structure, project_root)
        result["target_files"] = [target]

        if result["type"] is None:
            result["questions"].append({
                "key": "type",
                "message": f"'{target}' のレビュー種別を判定できません。種別を選択してください。",
                "options": ["requirement", "design", "plan", "code", "generic"]
            })

    elif (project_root / target_path).is_dir():
        detected_type, files = detect_type_from_dir(target, doc_structure, project_root)
        result["type"] = detected_type
        result["target_files"] = files

        if detected_type is None and files:
            result["questions"].append({
                "key": "type",
                "message": f"ディレクトリ '{target}' のレビュー種別を選択してください。",
                "options": ["requirement", "design", "plan", "code", "generic"]
            })
        elif not files:
            result["questions"].append({
                "key": "target",
                "message": f"ディレクトリ '{target}' にレビュー対象ファイルが見つかりません。パスを指定してください。",
                "options": []
            })

    elif target in features:
        available_types = find_feature_subdirs(project_root, doc_structure, target)

        if len(available_types) == 1:
            result["type"] = available_types[0]
            result["target_files"] = find_target_files(
                project_root, doc_structure, target, available_types[0])
        elif len(available_types) > 1:
            result["questions"].append({
                "key": "type",
                "message": f"Feature '{target}' のどの種別をレビューしますか？",
                "options": available_types
            })
        else:
            result["questions"].append({
                "key": "target",
                "message": f"Feature '{target}' にレビュー対象のドキュメントが見つかりません。パスを指定してください。",
                "options": []
            })

    else:
        result["questions"].append({
            "key": "target",
            "message": f"'{target}' が見つかりません。レビュー対象のファイルまたはディレクトリを指定してください。",
            "options": []
        })


def _resolve_multiple_targets(targets, doc_structure, project_root, result):
    """複数ファイル対象を解決"""
    valid_files = []
    missing = []

    for t in targets:
        if (project_root / t).is_file():
            valid_files.append(t)
        else:
            missing.append(t)

    if missing:
        result["questions"].append({
            "key": "target",
            "message": f"以下のファイルが見つかりません: {', '.join(missing)}",
            "options": []
        })
        result["target_files"] = []
        return

    result["target_files"] = valid_files

    # 種別判定: 最初のファイルで判定
    result["type"] = detect_type_from_path(valid_files[0], doc_structure, project_root)

    if result["type"] is None:
        result["questions"].append({
            "key": "type",
            "message": "レビュー種別を判定できません。種別を選択してください。",
            "options": ["requirement", "design", "plan", "code", "generic"]
        })


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main():
    targets = parse_args()

    project_root = find_project_root()

    # .doc_structure.yaml を読み込む（必須）
    doc_structure = parse_doc_structure(project_root)
    has_doc_structure = doc_structure is not None

    if not has_doc_structure:
        # .doc_structure.yaml がなければエラー
        print(json.dumps({
            "status": "error",
            "has_doc_structure": False,
            "type": None,
            "target_files": [],
            "features": [],
            "questions": [],
            "error": ".doc_structure.yaml が見つかりません。/forge:setup を実行して作成してください。"
        }, ensure_ascii=False, indent=2))
        return

    features = detect_features_from_doc_structure(project_root, doc_structure)

    result = {
        "status": "resolved",
        "has_doc_structure": True,
        "type": None,
        "target_files": [],
        "features": features,
        "questions": []
    }

    if len(targets) > 1:
        _resolve_multiple_targets(targets, doc_structure, project_root, result)

    elif len(targets) == 1:
        _resolve_single_target(targets[0], doc_structure, project_root,
                               features, result)

    else:
        # 対象未指定
        if features:
            result["questions"].append({
                "key": "feature",
                "message": "レビュー対象の Feature を選択してください（コードレビューの場合はパスを指定）。",
                "options": features
            })
        else:
            result["questions"].append({
                "key": "target",
                "message": "レビュー対象のファイルまたはディレクトリを指定してください。",
                "options": []
            })

    # ステータス判定
    if result["questions"]:
        result["status"] = "needs_input"

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
