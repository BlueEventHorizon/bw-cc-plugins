#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc-db の KEY / series と、category ごとの対象文書一覧を解決する。

doc-db の索引単位は次のとおりに決まる。

| 値             | 解決方法                                                                        |
| -------------- | ------------------------------------------------------------------------------- |
| `project_name` | `git rev-parse --git-common-dir` の親ディレクトリ名。失敗時は project root 名    |
| `category`     | 呼び出し側（wrapper）が固定する `rules` または `specs`                           |
| `key`          | `{project_name}-{category}`                                                     |
| `series`       | `git rev-parse --abbrev-ref HEAD`。取得不能または detached HEAD は `main`        |

## KEY を worktree で分裂させない [MANDATORY]

git worktree は branch ごとに別ディレクトリになり、basename も異なる。
project root の basename を KEY prefix にすると、同一プロジェクトなのに worktree ごとに
別 KEY が doc-db へ登録され、series（branch）で系列を区別する設計が意味を失う。
`--git-common-dir` は同一 repo の全 worktree で共通の `.git` を指すため、その親
ディレクトリ名（= 本体 repo のルート名）を使えば、どの worktree から呼んでも同じ
`project_name` が得られる。したがって basename より git common dir を優先する。

git repo でない場合・git 実行に失敗した場合は project root 名へ縮退する。
これは「同一プロジェクトの索引が分裂しない」という目的を満たせない環境での唯一の
決定論的な代替であり、失敗を隠す縮退ではない（KEY が決まらないと operation 自体を
開始できない）。

## series を `main` へ縮退させる範囲

branch 取得の失敗・空出力・detached HEAD（`HEAD` という出力）はいずれも `main` とする。
detached HEAD には「現在の branch」が存在せず、その状態ごとに series を作ると、
checkout し直すたびに再同期の必要な系列が増えていく。読み書きで同じ series を使う
契約（query も update も現在の branch）を保つため、既定系列へ寄せる。

## 対象文書の解決は既存 resolver へ委譲する [MANDATORY]

`.doc_structure.yaml` の解釈（`root_dirs` の glob 展開、`patterns.exclude` の適用、
`.md` 収集）は既存の `scripts/doc_structure/resolve_doc_structure.py` が持つ。
本モジュールは **YAML パーサを二重実装しない**。二重実装すると同じ設定から
backend ごとに異なる母集団が導かれ、索引と検索の対象がずれる。

委譲の方式は **subprocess による CLI 呼び出し** を採る。理由は 3 つある。

1. `resolve_doc_structure.py` の公開契約は CLI（`--type` / `--project-root` と JSON 出力）
   であり、内部関数は契約として固定されていない。CLI を境界にすれば、resolver 内部の
   関数構成が変わっても本モジュールは壊れない。
2. 同 script はエラー経路で `sys.exit()` を呼ぶ。ライブラリとして import すると
   `SystemExit` を捕捉して回す実装になり、呼び出し側から見た失敗の形が歪む。
3. `plugins/` 配下の script は SKILL からパス指定で実行される配布物であり、
   別ディレクトリの script を import する package 前提を持たない。既存の script 間
   連携も CLI 呼び出しで行われている。

## テスト境界

外部コマンドの実行は `run_command()` の 1 関数に閉じている。git 呼び出しと resolver
呼び出しはどちらもこの関数を通るため、`runner=` を差し替えれば実 git・実リポジトリの
状態に依存せずに検証できる。

## 依存

Python 標準ライブラリのみ。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# --- 定数 ---------------------------------------------------------------------

#: wrapper が固定する category（KEY の suffix になる）
CATEGORIES = ("rules", "specs")

#: branch を取得できない場合・detached HEAD の場合に使う series
DEFAULT_SERIES = "main"

#: `git rev-parse --abbrev-ref HEAD` が detached HEAD で返す値
DETACHED_HEAD_OUTPUT = "HEAD"

#: git 呼び出しの timeout（秒）。KEY / series 解決を長時間ブロックさせない
GIT_TIMEOUT_SECONDS = 5

#: resolver 呼び出しの timeout（秒）。文書ツリーの走査を含むため git より長く取る
RESOLVER_TIMEOUT_SECONDS = 60

#: 対象文書の解決を委譲する既存 resolver（CLI）
RESOLVER_SCRIPT = (
    Path(__file__).resolve().parent.parent / "doc_structure" / "resolve_doc_structure.py"
)

#: 外部コマンドを実行できなかった場合に `run_command()` が返す returncode
COMMAND_UNAVAILABLE_RETURNCODE = -1

#: 例外メッセージへ載せる resolver 出力の最大長（診断に足り、全文を貼らない長さ）
_MAX_OUTPUT_EXCERPT = 400


# --- 例外 ---------------------------------------------------------------------


class ProjectDocumentsError(Exception):
    """KEY / series / 対象文書一覧のいずれかを確定できなかった。

    対象文書 0 件は本例外ではない（0 件は正しく確定した結果であり、呼び出し側が
    「対象文書なし」として扱う）。本例外は設定不備・resolver 実行不能のように
    一覧そのものを決められない場合に限る。
    """


# --- 外部コマンド境界 ---------------------------------------------------------


def run_command(args, cwd: Path, timeout: float):
    """外部コマンドを実行し `(returncode, stdout, stderr)` を返す。

    **本関数が唯一の外部コマンド実行境界である。** テストはここを差し替える。

    実行そのものが不能だった場合（コマンド不在・cwd 不正・timeout）は例外を投げず、
    `COMMAND_UNAVAILABLE_RETURNCODE` と理由を stderr として返す。呼び出し側は
    「非ゼロ終了」と「実行不能」を同じ分岐で扱えばよく、git の縮退規則を
    例外処理と returncode 判定の 2 箇所に分けて書く必要がなくなる。
    """
    try:
        result = subprocess.run(
            list(args),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return COMMAND_UNAVAILABLE_RETURNCODE, "", f"コマンドが {timeout} 秒で終了しませんでした"
    except OSError as exc:
        return COMMAND_UNAVAILABLE_RETURNCODE, "", f"コマンドを実行できません: {exc}"
    return result.returncode, result.stdout, result.stderr


# --- KEY / series -------------------------------------------------------------


def detect_project_name(project_root: Path, runner=run_command) -> str:
    """worktree 間で共通の project 識別名を返す。

    `--git-common-dir` の親ディレクトリ名を使う。相対パス（本体 worktree では `.git`）
    で返ることがあるため、project root を基点に解決する。
    git 非管理・実行失敗時は project root 名へ縮退する。

    project root は絶対パスへ正規化してから使う。相対パス（`Path(".")` 等）のままだと
    縮退時の `project_root.name` が空文字列になり、KEY が `-{category}` になってしまう。
    """
    project_root = Path(project_root).resolve()
    returncode, stdout, _ = runner(
        ["git", "rev-parse", "--git-common-dir"], project_root, GIT_TIMEOUT_SECONDS
    )
    if returncode == 0:
        common_dir_text = stdout.strip()
        if common_dir_text:
            common_dir = Path(common_dir_text)
            if not common_dir.is_absolute():
                common_dir = project_root / common_dir
            main_repo_root = common_dir.resolve().parent
            if main_repo_root.name:
                return main_repo_root.name
    return project_root.name


def detect_series(project_root: Path, runner=run_command) -> str:
    """現在の branch を series として返す。取得不能・detached HEAD は `main`。"""
    returncode, stdout, _ = runner(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], Path(project_root), GIT_TIMEOUT_SECONDS
    )
    if returncode != 0:
        return DEFAULT_SERIES
    branch = stdout.strip()
    if not branch or branch == DETACHED_HEAD_OUTPUT:
        return DEFAULT_SERIES
    return branch


def build_key(project_name: str, category: str) -> str:
    """doc-db の KEY（`{project_name}-{category}`）を組み立てる。"""
    return f"{project_name}-{category}"


# --- 対象文書 -----------------------------------------------------------------


def resolve_paths(
    category: str,
    project_root: Path,
    runner=run_command,
    resolver_script: Path = RESOLVER_SCRIPT,
    python_executable: str = sys.executable,
) -> list:
    """category の対象文書を project root 相対パスの一覧で返す（既存 resolver へ委譲）。

    resolver の `--type` は `{"status": "ok", "project_root": ..., "<category>": [...]}`
    を返す。`status` が `ok` でない場合、出力を JSON として解析できない場合、
    category の一覧が欠けている場合はいずれも `ProjectDocumentsError` とする。

    0 件は正常な結果として空リストで返す（例外にしない）。
    """
    _validate_category(category)
    project_root = Path(project_root)
    command = [
        python_executable,
        str(resolver_script),
        "--type",
        category,
        "--project-root",
        str(project_root),
    ]
    returncode, stdout, stderr = runner(command, project_root, RESOLVER_TIMEOUT_SECONDS)

    # resolver は異常内容によって JSON を stdout / stderr のどちらへも出す。
    # 両方を候補にして、解析できた側を採用する。
    payload = _first_json_object(stdout, stderr)
    if payload is None:
        raise ProjectDocumentsError(
            "対象文書の解決に失敗しました"
            f"（resolver exit={returncode}）: {_excerpt(stdout, stderr)}"
        )

    if payload.get("status") != "ok":
        message = payload.get("message") or "resolver が status=ok を返しませんでした"
        suggestion = payload.get("suggestion")
        if suggestion:
            message = f"{message} / {suggestion}"
        raise ProjectDocumentsError(f"対象文書の解決に失敗しました: {message}")

    files = payload.get(category)
    if not isinstance(files, list):
        raise ProjectDocumentsError(
            f"resolver の応答に '{category}' の一覧が含まれていません"
            f"（resolver exit={returncode}）"
        )
    return [str(path) for path in files]


# --- 集約結果 -----------------------------------------------------------------


class ProjectDocuments:
    """1 つの category について確定した KEY / series / 対象文書一覧。

    `count` を持つのは、索引側の状態を確認する前に対象文書 0 件を判定するためである。
    索引側からは「一度も同期していない series」と「同期済みだが対象が 0 件だった
    series」を区別できないため、件数の判定を先に置いて切り分ける。

    `dataclass` を使わないのは、本モジュールが `importlib` でファイルパスから
    ロードされる経路（SKILL / テストからの直接ロード）を持つためである。
    `sys.modules` へ登録されていないモジュール内の dataclass は生成時に失敗する。
    """

    __slots__ = ("project_root", "category", "project_name", "key", "series", "paths")

    def __init__(
        self,
        project_root: Path,
        category: str,
        project_name: str,
        key: str,
        series: str,
        paths: tuple,
    ):
        self.project_root = project_root
        self.category = category
        self.project_name = project_name
        self.key = key
        self.series = series
        self.paths = tuple(paths)

    def __repr__(self) -> str:
        return (
            f"ProjectDocuments(key={self.key!r}, series={self.series!r},"
            f" count={self.count})"
        )

    @property
    def count(self) -> int:
        """対象文書数。0 件先行判定に使う。"""
        return len(self.paths)

    @property
    def is_empty(self) -> bool:
        """対象文書が 0 件か。索引に触れず「対象文書なし」とする条件。"""
        return not self.paths

    @property
    def entries(self) -> list:
        """`sync_documents` へ渡す `{path, local_path}` の一覧。"""
        return [
            {"path": path, "local_path": str(self.project_root / path)}
            for path in self.paths
        ]

    def to_dict(self) -> dict:
        """診断出力用の dict 表現（認証情報を含む値は持たない）。"""
        return {
            "project_root": str(self.project_root),
            "category": self.category,
            "project_name": self.project_name,
            "key": self.key,
            "series": self.series,
            "count": self.count,
            "paths": list(self.paths),
        }


def resolve(
    category: str,
    project_root: Path,
    runner=run_command,
    resolver_script: Path = RESOLVER_SCRIPT,
    python_executable: str = sys.executable,
) -> ProjectDocuments:
    """category の KEY / series / 対象文書一覧をまとめて解決する。

    project root は入口で絶対パスへ正規化する。相対パスのままだと、git 非管理環境で
    KEY が `-{category}` に縮退し、`entries[].local_path` の絶対パス契約も破れる。
    """
    _validate_category(category)
    project_root = Path(project_root).resolve()
    project_name = detect_project_name(project_root, runner=runner)
    series = detect_series(project_root, runner=runner)
    paths = resolve_paths(
        category,
        project_root,
        runner=runner,
        resolver_script=resolver_script,
        python_executable=python_executable,
    )
    return ProjectDocuments(
        project_root=project_root,
        category=category,
        project_name=project_name,
        key=build_key(project_name, category),
        series=series,
        paths=tuple(paths),
    )


# --- 内部 ---------------------------------------------------------------------


def _validate_category(category: str) -> None:
    if category not in CATEGORIES:
        raise ProjectDocumentsError(
            f"category は {' / '.join(CATEGORIES)} のいずれかです: {category!r}"
        )


def _first_json_object(*outputs: str):
    """引数の中から JSON object として解析できた最初の出力を返す（無ければ None）。"""
    for output in outputs:
        text = (output or "").strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _excerpt(*outputs: str) -> str:
    """例外メッセージへ載せる出力の抜粋を作る。"""
    for output in outputs:
        text = (output or "").strip()
        if text:
            if len(text) > _MAX_OUTPUT_EXCERPT:
                return text[:_MAX_OUTPUT_EXCERPT] + "…"
            return text
    return "（出力なし）"
