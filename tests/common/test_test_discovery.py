"""テストが CI の discover に確実に拾われることを検査する。

CI ゲートは `python3 -m unittest discover -s tests -p 'test_*.py'` である。discover は
パッケージを辿って走査するため、`__init__.py` を欠くディレクトリは**エラーにならず黙って
飛ばされる**。テストファイルは存在し、直接指定すれば通り、`git status` にも異常が出ないため、
「テスト済み」に見えたまま 1 行も実行されない状態が成立する。

実際に 2 ディレクトリ（`tests/anvil/`・`tests/forge/agent-review/`）でこれが起き、
追加したテストが CI で一度も実行されないまま「全件通過」と報告される事故になった。
件数の増減では気づけない（元から数えられていない）ため、構造として検査する。
"""

import unittest
from pathlib import Path

_TESTS_ROOT = Path(__file__).resolve().parents[1]


def _dirs_containing_tests() -> set[Path]:
    """テストファイルを含むディレクトリと、`tests/` までのその全祖先を返す。"""
    dirs: set[Path] = set()
    for test_file in _TESTS_ROOT.rglob("test_*.py"):
        current = test_file.parent
        while True:
            dirs.add(current)
            if current == _TESTS_ROOT:
                break
            current = current.parent
    return dirs


class TestDiscoveryTest(unittest.TestCase):
    def test_every_test_directory_is_a_package(self):
        """テストを含むディレクトリとその祖先すべてに `__init__.py` があること。

        祖先まで検査するのは、末端にだけ置いても親が欠けていれば discover が
        そこで止まるためである（`tests/anvil/commit/` に置いても `tests/anvil/` が
        無ければ拾われない。実測で確認した）。
        """
        missing = sorted(
            str(d.relative_to(_TESTS_ROOT.parent))
            for d in _dirs_containing_tests()
            if not (d / "__init__.py").is_file()
        )
        self.assertEqual(
            missing,
            [],
            f"__init__.py が無いため discover に拾われないディレクトリ: {missing}",
        )


if __name__ == "__main__":
    unittest.main()
