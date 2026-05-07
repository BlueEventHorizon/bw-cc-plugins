"""session files / refs files の読み取り共通処理。"""

from pathlib import Path

from session.yaml_utils import parse_yaml

# read_session.py の既定対象
SESSION_FILES = [
    "session.yaml",
    "refs.yaml",
    "review.md",
    "plan.yaml",
]

REFS_FILES = [
    "specs.yaml",
    "rules.yaml",
    "code.yaml",
]


def missing_entry():
    return {"exists": False, "content": None}


def error_entry(error):
    return {"exists": True, "content": None, "error": str(error)}


def read_entry(path, *, yaml_parser=parse_yaml):
    """単一ファイルを読み込み entry 形式で返す。"""
    filepath = Path(path)
    if not filepath.is_file():
        return missing_entry()

    try:
        content = filepath.read_text(encoding="utf-8")
        if filepath.suffix == ".md":
            return {"exists": True, "content": content}
        if filepath.suffix == ".yaml":
            return {"exists": True, "content": yaml_parser(content)}
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return error_entry(e)

    return missing_entry()


def read_session_files(
    session_dir,
    file_filter=None,
    *,
    session_files=SESSION_FILES,
    refs_files=REFS_FILES,
):
    """セッションディレクトリ内の既知ファイルを読み込む。"""
    session_path = Path(session_dir)
    result = {
        "session_dir": str(session_dir),
        "files": {},
        "refs": {},
    }

    targets = file_filter if file_filter else session_files
    for name in targets:
        if name in session_files:
            result["files"][name] = read_entry(session_path / name)

    ref_targets = file_filter if file_filter else refs_files
    refs_dir = session_path / "refs"
    for name in ref_targets:
        if name in refs_files:
            result["refs"][name] = read_entry(refs_dir / name)

    return result
