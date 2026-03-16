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

SEMVER_PATTERN = re.compile(r'^(\d+)\.(\d+)\.(\d+)$')
BUMP_SPECS = ('patch', 'minor', 'major')


def parse_semver(version_str):
    """セマンティックバージョンをパースする。

    Args:
        version_str: バージョン文字列（例: "1.2.3"）

    Returns:
        tuple[int, int, int]: (major, minor, patch)

    Raises:
        ValueError: 不正なバージョン形式
    """
    match = SEMVER_PATTERN.match(version_str.strip())
    if not match:
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
        # 直接指定 — 形式検証のみ
        parse_semver(spec)
        new_version = spec.strip()

    result = {
        "current": current.strip(),
        "new": new_version,
        "spec": spec,
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
