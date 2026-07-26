#!/usr/bin/env python3
"""セマンティックバージョニングの計算と検証。

Usage:
    python3 calculate_version.py <current_version> <spec>
    # spec: patch / minor / major / 直接指定（例: 1.2.3）

出力（JSON）:
    {"status": "ok", "current": "0.0.19", "new": "0.0.20", "spec": "patch"}
    {"status": "ok", "current": "0.0.19", "new": "0.0.20", "spec": "patch", "warning": "new <= current"}
"""

import json
import re
import sys

# 先頭 `v` を許容する（CHANGELOG を canonical version source にするケース、Issue #115 提案3）。
# `v` は normalize して計算し、出力は数値 X.Y.Z 形式に統一する。
SEMVER_PATTERN = re.compile(r'^[vV]?(\d+)\.(\d+)\.(\d+)$')
BUMP_SPECS = ('patch', 'minor', 'major')


def parse_semver(version_str):
    """セマンティックバージョンをパースする。

    先頭の `v` / `V`（例: "v1.2.3"）は許容し、normalize して扱う。

    Args:
        version_str: バージョン文字列（例: "1.2.3", "v1.2.3"）

    Returns:
        tuple[int, int, int]: (major, minor, patch)

    Raises:
        ValueError: 不正なバージョン形式
    """
    stripped = version_str.strip()
    match = SEMVER_PATTERN.match(stripped)
    if not match:
        # プレリリースサフィックスの検出（例: 1.2.3-alpha, v1.2.3-beta.1）
        if re.match(r'^[vV]?\d+\.\d+\.\d+-', stripped):
            raise ValueError(
                f"プレリリースバージョンは非対応です: '{version_str}'（X.Y.Z 形式のみ対応）"
            )
        raise ValueError(f"不正なバージョン形式: '{version_str}'（例: 1.2.3）")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def bump_version(current, spec):
    """バージョンを計算する。

    Args:
        current: 現在のバージョン文字列（例: "0.0.19"）
        spec: "patch" / "minor" / "major" / 直接指定（例: "1.2.3"）

    Returns:
        dict: {"current": str, "new": str, "spec": str, "warning": str|None}

    Raises:
        ValueError: 不正な入力
    """
    cur_major, cur_minor, cur_patch = parse_semver(current)

    if spec == 'patch':
        new_version = f"{cur_major}.{cur_minor}.{cur_patch + 1}"
    elif spec == 'minor':
        new_version = f"{cur_major}.{cur_minor + 1}.0"
    elif spec == 'major':
        new_version = f"{cur_major + 1}.0.0"
    else:
        # 直接指定 — 形式検証のうえ数値 X.Y.Z に normalize（先頭 v を除去）
        spec_major, spec_minor, spec_patch = parse_semver(spec)
        new_version = f"{spec_major}.{spec_minor}.{spec_patch}"

    result = {
        # current も数値 X.Y.Z に normalize（先頭 v を除去して一貫した出力にする）
        "current": f"{cur_major}.{cur_minor}.{cur_patch}",
        "new": new_version,
        "spec": spec.strip(),
    }

    # 新 ≦ 旧の warning
    new_parts = parse_semver(new_version)
    cur_parts = (cur_major, cur_minor, cur_patch)
    if new_parts <= cur_parts:
        result["warning"] = "new <= current"

    return result


def main():
    if len(sys.argv) != 3:
        print("Usage: calculate_version.py <current_version> <spec>", file=sys.stderr)
        print("  spec: patch / minor / major / X.Y.Z", file=sys.stderr)
        sys.exit(1)

    current = sys.argv[1]
    spec = sys.argv[2]

    try:
        result = bump_version(current, spec)
        result["status"] = "ok"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0)
    except ValueError as e:
        error = {"status": "error", "error": str(e)}
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
