#!/usr/bin/env python3
"""
レビュー対象の検出と種別判定スクリプト

DocAdvisor の config.yaml を利用してプロジェクト構造を把握し、
レビュー対象ファイル・種別・参考文書を特定する。
DocAdvisor がない場合は拡張子で判定し、判定不能な場合はユーザーへの問い合わせ情報を出力。

標準ライブラリのみ使用（pyyaml 不要）。

Usage:
  python3 resolve_review_context.py [target1] [target2] ...

  target: ファイルパス（複数可）、ディレクトリパス、Feature名、または省略
  フラグ（--codex, --claude, --auto-fix）は無視される

Output (JSON):
  {
    "status": "resolved" | "needs_input",
    "has_doc_advisor": true | false,
    "type": "requirement" | "design" | "code" | "plan" | "generic" | null,
    "target_files": ["path1", ...],
    "reference_docs": ["path1", ...],
    "features": ["feature1", ...],
    "questions": [
      {"key": "type|feature|target", "message": "...", "options": [...]}
    ]
  }
"""

import glob
import json
import os
import sys
from pathlib import Path

# ソースコード拡張子（汎用）
CODE_EXTENSIONS = {'.swift', '.kt', '.java', '.ts', '.tsx', '.js', '.jsx',
                   '.py', '.go', '.rs', '.c', '.cpp', '.h', '.m', '.mm'}

# generic 種別の判定パターン（基盤文書）
GENERIC_PATH_PATTERNS = [
    '.claude/skills/',
    '.claude/commands/',
    'rules/',
]
GENERIC_ROOT_FILES = {'CLAUDE.md', 'README.md'}


def parse_args():
    """引数を解析（フラグと対象を分離）"""
    targets = []
    for arg in sys.argv[1:]:
        if arg.startswith('--'):
            continue  # フラグはスキップ
        targets.append(arg)
    return targets


def find_project_root():
    """プロジェクトルートを検出"""
    current = Path(__file__).parent.absolute()
    for _ in range(10):
        if (current / ".git").exists() or (current / ".claude").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    # フォールバック: カレントディレクトリ
    return Path.cwd()


def load_doc_advisor_config(project_root):
    """DocAdvisor の config.yaml を読み込む（簡易パーサー）"""
    config_path = project_root / ".claude" / "doc-advisor" / "config.yaml"
    if not config_path.exists():
        return None

    # toc_utils の load_config を利用可能なら使う
    toc_utils_dir = project_root / ".claude" / "doc-advisor" / "scripts"
    if toc_utils_dir.exists():
        sys.path.insert(0, str(toc_utils_dir))
        try:
            from toc_utils import load_config
            return load_config()
        except ImportError:
            pass
        finally:
            if str(toc_utils_dir) in sys.path:
                sys.path.remove(str(toc_utils_dir))

    # フォールバック: 最小限のパース
    return _minimal_parse_config(config_path)


def _minimal_parse_config(config_path):
    """config.yaml の最小限パース（toc_utils が使えない場合）"""
    result = {'specs': {'root_dir': 'specs', 'patterns': {'target_dirs': {}}}}
    with open(config_path, 'r', encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith('root_dir:'):
                # 直前のセクションに応じて振り分け
                val = stripped.split(':', 1)[1].strip().strip('"\'')
                result['specs']['root_dir'] = val
            elif stripped.startswith('requirement:'):
                val = stripped.split(':', 1)[1].strip().strip('"\'')
                result['specs']['patterns']['target_dirs']['requirement'] = val
            elif stripped.startswith('design:'):
                val = stripped.split(':', 1)[1].strip().strip('"\'')
                result['specs']['patterns']['target_dirs']['design'] = val
    return result


def get_specs_root(config):
    """specs ルートディレクトリを取得"""
    if config and 'specs' in config:
        return config['specs'].get('root_dir', 'specs').rstrip('/')
    return 'specs'


def get_target_dirs(config):
    """種別→ディレクトリ名のマッピングを取得"""
    defaults = {'requirement': 'requirements', 'design': 'design'}
    if config and 'specs' in config:
        patterns = config['specs'].get('patterns', {})
        target_dirs = patterns.get('target_dirs', {})
        if target_dirs:
            return {**defaults, **target_dirs}
    return defaults


def detect_features(project_root, specs_root):
    """specs ディレクトリ配下の Feature 一覧を取得"""
    specs_dir = project_root / specs_root
    if not specs_dir.is_dir():
        return []

    features = []
    for entry in sorted(specs_dir.iterdir()):
        if entry.is_dir() and not entry.name.startswith('.'):
            features.append(entry.name)
    return features


def _detect_generic_type(path_str):
    """generic 種別の判定（基盤文書パターン）"""
    for pattern in GENERIC_PATH_PATTERNS:
        if path_str.startswith(pattern) or f'/{pattern}' in path_str:
            return "generic"
    filename = Path(path_str).name
    if filename in GENERIC_ROOT_FILES and '/' not in path_str.rstrip('/'):
        return "generic"
    return None


def detect_type_from_path(path_str, config, project_root):
    """パスから種別を判定"""
    # 1. コードファイル判定（拡張子ベース - 汎用）
    _, ext = os.path.splitext(path_str)
    if ext.lower() in CODE_EXTENSIONS:
        return "code"

    # 2. DocAdvisor config がある場合、ディレクトリ構造から判定
    if config:
        specs_root = get_specs_root(config)
        target_dirs = get_target_dirs(config)

        for review_type, dir_name in target_dirs.items():
            # specs/{feature}/{dir_name}/ のパターンにマッチするか
            if f'/{dir_name}/' in path_str or path_str.startswith(f'{specs_root}/'):
                # より正確にチェック: specs_root 配下で dir_name を含むか
                parts = Path(path_str).parts
                if dir_name in parts:
                    return review_type

        # plan は config に含まれない（exclude されている）が、ディレクトリ名で判定
        parts = Path(path_str).parts
        if 'plan' in parts:
            return "plan"

    # 3. 基盤文書パターン → generic（既存4種別の後に判定）
    generic_type = _detect_generic_type(path_str)
    if generic_type:
        return generic_type

    return None


def detect_type_from_dir(dir_path, config, project_root):
    """ディレクトリ内のファイルから種別を判定"""
    dir_p = project_root / dir_path
    if not dir_p.is_dir():
        return None, []

    # コードファイルを探す
    code_files = []
    for ext in CODE_EXTENSIONS:
        code_files.extend(glob.glob(str(dir_p / '**' / f'*{ext}'), recursive=True))

    # ドキュメントファイルを探す
    md_files = sorted(glob.glob(str(dir_p / '**' / '*.md'), recursive=True))

    if code_files and not md_files:
        rel_files = [str(Path(f).relative_to(project_root)) for f in code_files]
        return "code", sorted(rel_files)
    elif md_files and not code_files:
        # 最初のファイルから種別を推定
        first_rel = str(Path(md_files[0]).relative_to(project_root))
        review_type = detect_type_from_path(first_rel, config, project_root)
        rel_files = [str(Path(f).relative_to(project_root)) for f in md_files]
        return review_type, sorted(rel_files)

    return None, []


def find_feature_subdirs(project_root, specs_root, feature, target_dirs):
    """Feature 内で存在する種別サブディレクトリを検出"""
    available = []
    feature_dir = project_root / specs_root / feature

    if not feature_dir.is_dir():
        return available

    # config で定義されている種別をチェック
    for review_type, dir_name in target_dirs.items():
        subdir = feature_dir / dir_name
        if subdir.is_dir() and any(subdir.rglob('*.md')):
            available.append(review_type)

    # plan は config に含まれないが、ディレクトリが存在すれば追加
    plan_dir = feature_dir / 'plan'
    if plan_dir.is_dir() and any(plan_dir.rglob('*.md')):
        available.append('plan')

    return available


def find_target_files(project_root, specs_root, feature, review_type, target_dirs):
    """Feature + 種別からファイル一覧を取得"""
    type_to_dir = {**target_dirs, 'plan': 'plan'}
    dir_name = type_to_dir.get(review_type)
    if not dir_name:
        return []

    pattern = str(project_root / specs_root / feature / dir_name / '**' / '*.md')
    files = sorted(glob.glob(pattern, recursive=True))
    return [str(Path(f).relative_to(project_root)) for f in files]


def find_reference_docs(project_root, review_type):
    """種別に応じた参考文書を探索

    注: review_criteria_path はプラグインの review SKILL.md が
    3階層フォールバックで別途解決するため、ここでは含めない。
    """
    refs = []
    # 将来の拡張: 種別に応じた追加参考文書をここで収集可能
    return refs


def _resolve_single_target(target, config, project_root, specs_root,
                            target_dirs, features, result):
    """単一の対象（ファイル/ディレクトリ/Feature名）を解決"""
    target_path = Path(target)

    if (project_root / target_path).is_file():
        # ファイル指定
        result["type"] = detect_type_from_path(target, config, project_root)
        result["target_files"] = [target]

        if result["type"] is None:
            result["questions"].append({
                "key": "type",
                "message": f"'{target}' のレビュー種別を判定できません。種別を選択してください。",
                "options": ["requirement", "design", "plan", "code", "generic"]
            })

    elif (project_root / target_path).is_dir():
        # ディレクトリ指定
        detected_type, files = detect_type_from_dir(target, config, project_root)
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
        # Feature 名指定
        available_types = find_feature_subdirs(
            project_root, specs_root, target, target_dirs)

        if len(available_types) == 1:
            result["type"] = available_types[0]
            result["target_files"] = find_target_files(
                project_root, specs_root, target, available_types[0], target_dirs)
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
        # パスが見つからない
        result["questions"].append({
            "key": "target",
            "message": f"'{target}' が見つかりません。レビュー対象のファイルまたはディレクトリを指定してください。",
            "options": []
        })


def _resolve_multiple_targets(targets, config, project_root, result):
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
        # 見つかったファイルは target_files に含める
        result["target_files"] = valid_files
        return

    result["target_files"] = valid_files

    # 種別判定: 最初のファイルで判定
    result["type"] = detect_type_from_path(valid_files[0], config, project_root)

    if result["type"] is None:
        result["questions"].append({
            "key": "type",
            "message": "レビュー種別を判定できません。種別を選択してください。",
            "options": ["requirement", "design", "plan", "code", "generic"]
        })


def main():
    targets = parse_args()

    project_root = find_project_root()
    os.chdir(project_root)

    config = load_doc_advisor_config(project_root)
    has_doc_advisor = config is not None

    specs_root = get_specs_root(config)
    target_dirs = get_target_dirs(config) if has_doc_advisor else {}

    features = detect_features(project_root, specs_root) if has_doc_advisor else []

    result = {
        "status": "resolved",
        "has_doc_advisor": has_doc_advisor,
        "type": None,
        "target_files": [],
        "reference_docs": [],
        "features": features,
        "questions": []
    }

    if len(targets) > 1:
        # 複数ファイル指定
        _resolve_multiple_targets(targets, config, project_root, result)

    elif len(targets) == 1:
        # 単一対象（ファイル/ディレクトリ/Feature名）
        _resolve_single_target(targets[0], config, project_root, specs_root,
                               target_dirs, features, result)

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

    # 参考文書の収集
    if result["type"]:
        result["reference_docs"] = find_reference_docs(project_root, result["type"])

    # ステータス判定
    if result["questions"]:
        result["status"] = "needs_input"

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
