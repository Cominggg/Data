"""PreToolUse 훅 — 시크릿 파일 읽기·쓰기 차단 (Read·Write·Edit·Grep·Bash).

Read·Write·Edit는 대상 경로의 파일명을, Grep은 검색 경로와 glob을,
Bash는 명령을 토큰으로 나눠 각 토큰의 파일명을 검사한다.
따옴표·heredoc 안의 문장(커밋 메시지, PR 본문)은 한 토큰으로 묶이거나 제거되므로 걸리지 않는다.
문자열 조립(`f=.e; f=${f}nv`) 같은 의도적 우회까지 막지는 않는다 — 실수 방지용이다.
"""

import fnmatch
import json
import os
import re
import shlex
import sys

SECRET_NAME = re.compile(r"^\.env(rc|\..+)?$|\.secret|credentials")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1.*?\n(.*?)^\s*\2\s*$", re.S | re.M)
REDIRECT_PREFIX = re.compile(r"^[0-9&]*[<>|]+")
# Grep glob이 시크릿 파일을 겨냥하는지 판별할 대표 파일명 (rg -g는 .gitignore를 무시한다)
# `*`처럼 일반 파일에도 맞는 glob은 겨냥한 것이 아니므로 통과시킨다
SECRET_SAMPLES = [".env", ".env.local", ".envrc", "x.secret", "credentials.json"]
NORMAL_SAMPLES = ["a.py", "README.md", "config.json"]


def _is_secret(path):
    return bool(SECRET_NAME.search(os.path.basename(path.rstrip("/"))))


def _targets_secret(pattern):
    if not pattern:
        return False
    hit = any(fnmatch.fnmatch(name, pattern) for name in SECRET_SAMPLES)
    return hit and not any(fnmatch.fnmatch(name, pattern) for name in NORMAL_SAMPLES)


def _bash_targets(command):
    command = HEREDOC.sub("", command)
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        tokens = command.split()
    # 공백이 든 토큰은 따옴표로 묶인 문장이므로 제외, `--env-file=.env`는 `=` 뒤만 본다
    tokens = [t for t in tokens if not re.search(r"\s", t)]
    return [REDIRECT_PREFIX.sub("", t).rsplit("=", 1)[-1] for t in tokens]


def main():
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    if tool == "Bash":
        hits = [t for t in _bash_targets(tool_input.get("command", "")) if t and _is_secret(t)]
    elif tool == "Grep":
        path = tool_input.get("path", "")
        pattern = tool_input.get("glob", "")
        hits = [path] if path and _is_secret(path) else []
        if _targets_secret(pattern):
            hits.append(pattern)
    else:
        path = tool_input.get("file_path", "")
        hits = [path] if path and _is_secret(path) else []

    if hits:
        reason = "시크릿 파일 접근 차단: " + ", ".join(hits)
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
        print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
