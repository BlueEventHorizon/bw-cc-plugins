#!/usr/bin/env python3
"""sync_files のバージョンドリフト契約テスト。

`.version-config.yaml` の sync_files に列挙された各ファイルが、
version_file の現行バージョンと同期しているかを検証する。

- filter パターン自体がファイルに存在しない場合、`optional: true` エントリのみ
  対象外として許容する。`optional` でないエントリの filter 消失（設定の filter が
  ファイル内容の変化で一致しなくなった等）は、それ自体が見逃してはいけない不整合
  として fail する（optional の有無を問わず一律 continue すると、
  必須エントリの filter 消失を見逃す）
- filter パターンは存在するのに現行バージョンが見当たらない場合（ドリフト）は fail する
- filter 無し（version_path 使用）の sync_file でも同様にドリフトを検出する
  （本リポジトリの現行 config には filter 無し sync_file が存在しないため、
  合成データによる回帰テストで契約を担保する）

これにより README_en.md のようなファイルが optional スキップで
サイレントに古いバージョン表記のまま放置される事態を CI で検出する。

実行:
    python3 -m unittest tests.common.test_version_sync_drift -v
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UPDATE_VERSION_SCRIPTS = REPO_ROOT / "plugins" / "forge" / "skills" / "update-version" / "scripts"
FORGE_SCRIPTS = REPO_ROOT / "plugins" / "forge" / "scripts"
sys.path.insert(0, str(UPDATE_VERSION_SCRIPTS))
sys.path.insert(0, str(FORGE_SCRIPTS))

from update_version_files import (  # noqa: E402
    FilterNotFoundError,
    VersionDriftError,
    update_version_in_text,
)
from get_version_status import (  # noqa: E402
    extract_version_from_content,
    load_version_config,
)


def _is_optional_flag(sync):
    """sync_files エントリの `optional` フラグを真偽値として解釈する。

    `get_version_status.py` の手製 YAML パーサーはスカラー値を文字列のまま返す
    （bool にキャストしない）ため、`optional: false` も文字列 `"false"` になる。
    `bool("false")` は Python では `True` になるため、単純な `bool()` 変換では
    `optional: false` を明示したエントリまで optional 扱いになってしまう。
    """
    value = sync.get("optional")
    if value is None:
        return False
    return str(value).strip().lower() == "true"


class TestSyncFilesNoDrift(unittest.TestCase):
    """sync_files の各ファイルにバージョンドリフトがないことを検証する。"""

    @classmethod
    def setUpClass(cls):
        cls.config = load_version_config(REPO_ROOT)

    def test_no_drift_in_sync_files(self):
        drifted = []

        for target in self.config.get("targets", []):
            version_file = target.get("version_file", "")
            version_path = (target.get("version_path", "version") or "version").strip().strip("'\"")
            local_path = REPO_ROOT / version_file
            if not local_path.exists():
                continue

            current_ver = extract_version_from_content(
                local_path.read_text(encoding="utf-8"), version_path
            )
            if current_ver is None:
                continue

            for sync in target.get("sync_files", []):
                sync_path = REPO_ROOT / sync["path"]
                if not sync_path.exists():
                    continue

                content = sync_path.read_text(encoding="utf-8")
                filter_pattern = sync.get("filter")
                is_optional = _is_optional_flag(sync)
                try:
                    # 現行バージョンで noop 置換を試み、filter ブロック内に
                    # 現行バージョンが実在するかを確認する
                    update_version_in_text(
                        content, current_ver, current_ver,
                        filter_pattern=filter_pattern,
                    )
                except VersionDriftError as e:
                    drifted.append(
                        f"{sync['path']} (target={target['name']}, "
                        f"expected={current_ver}): {e}"
                    )
                except FilterNotFoundError as e:
                    if is_optional:
                        # optional かつ filter パターン自体が無い（対象外）は許容
                        continue
                    # optional でないエントリの filter 消失は、
                    # そのエントリが今後一切更新されなくなる不整合であり見逃せない
                    drifted.append(
                        f"{sync['path']} (target={target['name']}): "
                        f"必須エントリの filter が見つかりません（設定 or ファイル内容の不整合）: {e}"
                    )

        self.assertEqual(
            drifted,
            [],
            "以下の sync_files でバージョンドリフトを検出しました:\n" + "\n".join(drifted),
        )


class TestFilterlessOptionalSyncFileDrift(unittest.TestCase):
    """filter 無し（version_path 使用）sync_file のドリフト検出を保証する回帰テスト。

    本リポジトリの `.version-config.yaml` は全 sync_files に filter が設定されているため、
    実データではこの経路は顕在化しない。下流プロジェクトで filter 無し optional sync_file
    が使われた場合でも `update_version_in_text` が正しくドリフトを検出することを、
    合成データで直接検証する。
    """

    def test_filterless_optional_sync_file_with_drifted_value_is_detected(self):
        """version_path 使用・filter 無しの sync_file で値が乖離している場合、
        VersionDriftError として検出できる（サイレントな status: skipped 化を防ぐ）"""
        content = '{\n  "version": "0.2.2"\n}'
        current_ver = "999.88.7"

        with self.assertRaises(VersionDriftError):
            update_version_in_text(
                content, current_ver, current_ver, version_path="version",
            )


class TestIsOptionalFlag(unittest.TestCase):
    """`optional` フラグの文字列→真偽値解釈の回帰テスト。

    手製 YAML パーサーはスカラー値を文字列のまま返すため、
    `optional: false` を素朴に `bool()` で解釈すると常に `True` になってしまう。
    """

    def test_explicit_false_string_is_not_optional(self):
        """optional: false（パーサーが文字列 "false" を返すケース）は False と解釈する"""
        self.assertFalse(_is_optional_flag({"optional": "false"}))

    def test_explicit_true_string_is_optional(self):
        """optional: true（パーサーが文字列 "true" を返すケース）は True と解釈する"""
        self.assertTrue(_is_optional_flag({"optional": "true"}))

    def test_missing_key_is_not_optional(self):
        """optional キー自体が無い場合はデフォルト False（DES-023 §2.2 sync_files エントリ定義）"""
        self.assertFalse(_is_optional_flag({}))


if __name__ == "__main__":
    unittest.main()
