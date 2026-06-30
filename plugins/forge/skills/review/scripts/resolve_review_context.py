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
  python3 resolve_review_context.py --files <path1> <path2> ...
  python3 resolve_review_context.py --files path1,path2,path3
  python3 resolve_review_context.py --diff

  target: ファイルパス（複数可）、ディレクトリパス、Feature名、または省略

  --files: 指定ファイル群を target_files として直接採用（種別解決をバイパス）
  --diff:  現ブランチで未 commit (working tree + staged) の変更ファイルを
           target_files に展開（TBD-401 解消: base 指定オプションは提供しない）
  --files と --diff は同時指定不可（early validation で拒否）

  その他のフラグ（--codex, --claude, --auto-fix 等）は無視される。

Output (JSON):
  {
    "status": "resolved" | "needs_input" | "error",
    "has_doc_structure": true | false,
    "type": "requirement" | "design" | "code" | "plan" | "generic" | null,
    "target_files": [{"path": "path1"}, ...],  # ADR-032: dict 配列
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
import subprocess
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
    except (IOError, OSError) as e:
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

def parse_args(argv=None):
    """引数を解析（フラグと対象を分離）

    認識するフラグ:
      --files <path1> <path2> ...   または  --files path1,path2,...
      --diff                         （現ブランチ未 commit 差分）

    その他の `--xxx` フラグは無視される（後方互換: --codex / --claude / --auto-fix 等）。

    Returns:
      dict {
        "targets": [str, ...],   # 位置引数
        "files":   [str, ...] | None,  # --files で渡されたパス（None なら未指定）
        "diff":    bool,         # --diff 指定の有無
      }
    """
    if argv is None:
        argv = sys.argv[1:]

    targets = []
    files = None  # None: 未指定、[]: 空指定
    diff = False

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == '--files':
            files = []
            # 次の --xxx もしくは末尾までを files に詰める
            j = i + 1
            while j < len(argv) and not argv[j].startswith('--'):
                # カンマ区切りもサポート
                for token in argv[j].split(','):
                    token = token.strip()
                    if token:
                        files.append(token)
                j += 1
            i = j
            continue
        if arg == '--diff':
            diff = True
            i += 1
            continue
        if arg.startswith('--'):
            # 未知フラグは無視（後方互換）
            i += 1
            continue
        targets.append(arg)
        i += 1

    return {"targets": targets, "files": files, "diff": diff}


def find_project_root():
    """プロジェクトルートを検出"""
    return Path(_find_project_root())


# ---------------------------------------------------------------------------
# --diff 経路: 現ブランチ未 commit 差分の取得
# ---------------------------------------------------------------------------

def get_uncommitted_changed_files(project_root, runner=None):
    """現ブランチで未 commit (working tree + staged) の変更ファイルを返す。

    TBD-401 解消方針: 比較基準は「現ブランチ未 commit 差分のみ」に固定。
    base 指定オプション (--diff main / --diff HEAD~1 等) は提供しない。

    内部実装は `git status --porcelain` を使用し、staged と working tree の
    変更ファイルを列挙する。削除済みファイル (D / AD) はレビュー対象外として除外する。

    Args:
      project_root: プロジェクトルート (Path)
      runner: テスト用に subprocess.run を差し替えるためのフック (callable)

    Returns:
      [str, ...] : project_root からの相対パス（ソート済み・重複排除済み）

    Raises:
      RuntimeError: git コマンドが失敗した場合
    """
    if runner is None:
        runner = subprocess.run

    try:
        result = runner(
            ['git', 'status', '--porcelain'],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"git コマンドが利用できません: {e}") from e

    if result.returncode != 0:
        stderr = (result.stderr or '').strip()
        raise RuntimeError(f"git status の実行に失敗しました: {stderr}")

    files = []
    seen = set()
    for line in (result.stdout or '').splitlines():
        if not line or len(line) < 3:
            continue
        # porcelain v1 形式: XY <path>  ※ rename は ' -> ' 区切り
        xy = line[:2]
        rest = line[3:]
        if ' -> ' in rest:
            # rename: 新しいパスを採用
            _, _, new_path = rest.partition(' -> ')
            path = new_path.strip()
        else:
            path = rest.strip()

        # ダブルクォート囲い (porcelain がエスケープした場合) を剥がす
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]

        # 完全削除 ('AD' / 'DD' / 'UD' / ' D' / 'D ' / '!D') はレビュー対象外
        if xy in ('AD', 'DD', 'UD', ' D', 'D ', '!D'):
            continue
        # Untracked (??) はレビュー対象に含める
        # path がディレクトリの場合は配下のファイルを展開
        full = project_root / path
        if full.is_dir():
            for sub in sorted(full.rglob('*')):
                if sub.is_file():
                    rel = str(sub.relative_to(project_root))
                    if rel not in seen:
                        seen.add(rel)
                        files.append(rel)
            continue
        if not full.exists():
            # 削除済みファイル: スキップ
            continue
        if path not in seen:
            seen.add(path)
            files.append(path)

    return sorted(files)


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

def _to_path_entries(paths):
    """文字列パスのリストを ADR-032 形式の dict 配列に変換する。"""
    return [{"path": p} for p in paths]


def _resolve_single_target(target, doc_structure, project_root, features, result):
    """単一の対象（ファイル/ディレクトリ/Feature名）を解決"""
    target_path = Path(target)

    if (project_root / target_path).is_file():
        result["type"] = detect_type_from_path(target, doc_structure, project_root)
        result["target_files"] = _to_path_entries([target])

        if result["type"] is None:
            result["questions"].append({
                "key": "type",
                "message": f"'{target}' のレビュー種別を判定できません。種別を選択してください。",
                "options": ["requirement", "design", "plan", "code", "generic"]
            })

    elif (project_root / target_path).is_dir():
        detected_type, files = detect_type_from_dir(target, doc_structure, project_root)
        result["type"] = detected_type
        result["target_files"] = _to_path_entries(files)

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
            result["target_files"] = _to_path_entries(find_target_files(
                project_root, doc_structure, target, available_types[0]))
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

    result["target_files"] = _to_path_entries(valid_files)

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

def _error_result(message, has_doc_structure=True):
    """エラー JSON 構造を生成"""
    return {
        "status": "error",
        "has_doc_structure": has_doc_structure,
        "type": None,
        "target_files": [],
        "features": [],
        "questions": [],
        "error": message,
    }


def _resolve_files_bypass(file_args, project_root, result):
    """--files バイパス経路: 指定ファイル群を target_files として直接採用。

    種別解決 (.doc_structure.yaml 経由のディレクトリ → 種別マッピング) はバイパスする。
    種別は呼び出し側 (SKILL / Phase 1) で確定済みの前提。

    指定ファイルが存在しない場合はエラーを返す (early validation)。
    """
    missing = []
    valid = []
    for f in file_args:
        if (project_root / f).is_file():
            valid.append(f)
        else:
            missing.append(f)

    if missing:
        result.update(_error_result(
            f"--files で指定されたファイルが見つかりません: {', '.join(missing)}"
        ))
        return

    result["target_files"] = _to_path_entries(valid)
    # 種別解決はバイパス (type は呼び出し側で確定済みの前提)。
    # type は None のままで返し、SKILL 側で --type 等の明示引数を採用する。


def _resolve_diff(project_root, result):
    """--diff 経路: 現ブランチ未 commit 差分を target_files に展開。

    TBD-401 解消: 比較基準は「現ブランチ未 commit 差分のみ」に固定。
    base 指定オプションは提供しない。
    """
    try:
        files = get_uncommitted_changed_files(project_root)
    except RuntimeError as e:
        result.update(_error_result(str(e)))
        return

    result["target_files"] = _to_path_entries(files)
    if not files:
        result["questions"].append({
            "key": "target",
            "message": "現ブランチで未 commit の変更ファイルが見つかりません。",
            "options": [],
        })


def main():
    args = parse_args()
    targets = args["targets"]
    files_arg = args["files"]
    diff = args["diff"]

    project_root = find_project_root()

    # --files / --diff の early validation: 同時指定不可
    if files_arg is not None and diff:
        print(json.dumps(_error_result(
            "--files と --diff は同時に指定できません。"
        ), ensure_ascii=False, indent=2))
        return

    # --files バイパス経路 (種別解決をバイパスするため doc_structure 読み込みより先に処理)
    if files_arg is not None:
        if len(files_arg) == 0:
            print(json.dumps(_error_result(
                "--files に少なくとも 1 つのファイルパスを指定してください。"
            ), ensure_ascii=False, indent=2))
            return

        result = {
            "status": "resolved",
            "has_doc_structure": (project_root / '.doc_structure.yaml').is_file(),
            "type": None,
            "target_files": [],
            "features": [],
            "questions": [],
        }
        _resolve_files_bypass(files_arg, project_root, result)
        if result.get("status") == "error":
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        if result["questions"]:
            result["status"] = "needs_input"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # --diff 経路 (種別は SKILL 側で確定済みの前提)
    if diff:
        result = {
            "status": "resolved",
            "has_doc_structure": (project_root / '.doc_structure.yaml').is_file(),
            "type": None,
            "target_files": [],
            "features": [],
            "questions": [],
        }
        _resolve_diff(project_root, result)
        if result.get("status") == "error":
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        if result["questions"]:
            result["status"] = "needs_input"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # .doc_structure.yaml を読み込む（通常経路では必須）
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
            "error": ".doc_structure.yaml が見つかりません。setup-doc-structure を実行して作成してください。"
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
