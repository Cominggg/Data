"""PostToolUse 훅 — .py 파일 Write·Edit 후 ruff 정리 + 관련 테스트 실행.

- ruff check --fix 는 F401(미사용 import)을 고치지 않는다 — import를 먼저 넣고
  다음 Edit에서 사용하는 흐름에서 import가 지워지는 것을 막는다.
- 테스트 대상: 수정한 파일이 tests/test_*.py면 그 파일, 아니면 tests/test_{모듈}*.py
- 테스트가 실패하면 stderr + exit 2로 Claude에게 결과를 전달한다.
"""

import glob
import json
import os
import subprocess
import sys


def main():
    data = json.load(sys.stdin)
    path = data.get("tool_input", {}).get("file_path", "")
    project = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd", "")
    if not path.endswith(".py") or not project:
        return
    path = os.path.realpath(path)
    project = os.path.realpath(project)
    if not path.startswith(project + os.sep) or not os.path.exists(path):
        return

    python = os.path.join(project, ".venv", "bin", "python")
    if not os.path.exists(python):
        python = sys.executable

    subprocess.run(
        [python, "-m", "ruff", "check", "--fix", "--unfixable", "F401", path],
        cwd=project,
        capture_output=True,
    )
    subprocess.run([python, "-m", "ruff", "format", path], cwd=project, capture_output=True)

    name = os.path.basename(path)
    if os.path.dirname(path) == os.path.join(project, "tests"):
        tests = [path] if name.startswith("test_") else []
    else:
        stem = name[: -len(".py")]
        tests = sorted(glob.glob(os.path.join(project, "tests", "test_" + stem + "*.py")))
    if not tests:
        return

    result = subprocess.run(
        [python, "-m", "pytest", *tests, "-q", "--no-header", "--no-cov"],
        cwd=project,
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 5):  # 5: 수집된 테스트 없음 (integration만 있는 경우)
        tail = "\n".join(result.stdout.strip().splitlines()[-15:])
        print(
            "테스트 실패 ({}):\n{}".format(", ".join(os.path.basename(t) for t in tests), tail),
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
