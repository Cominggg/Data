---
name: data-review
description: Coming Data 코드 작성 후 커밋·PR 전 필수 실행하는 Data 전문 코드 리뷰 스킬. DML-only, logging 사용, Python 3.9 문법, 외부 API rate limit, pyproject 패키지 등록 등 CLAUDE.md 규칙 준수 여부를 검토한다. "data-review 해줘", "Data 코드 리뷰해줘", "파이프라인 리뷰해줘" 또는 코드 작성 완료 후 커밋 전 검토를 요청하는 모든 상황에서 반드시 이 스킬을 사용한다.
---

# data-review

변경된 Python 코드를 `references/data-checklist.md` 기준으로 검토하고 심각도별 이슈를 보고한다.

## 참조 파일

- `references/data-checklist.md` — 검토 항목, 자동 검사 명령, 심각도 기준

## 실행 순서

1. 검토 대상 파일을 확정한다 — 커밋 전 변경과 브랜치에 이미 커밋된 변경을 모두 포함한다
   ```bash
   BASE=$(git merge-base HEAD origin/main)
   { git diff --name-only "$BASE"; git ls-files --others --exclude-standard; } | grep '\.py$' | sort -u
   git diff "$BASE" -- '*.py'
   ```
   - 대상 파일이 없으면 "검토할 Python 변경 없음"을 보고하고 종료한다

2. 프로젝트 규칙을 로드한다 — 레포 루트 `CLAUDE.md`의 "파이썬 버전", "코딩 규칙", "외부 API 정보" 섹션

3. `references/data-checklist.md`의 **자동 검사**를 대상 파일에 실행한다
   - grep 결과는 후보일 뿐이다 — 주석·문자열·테스트 픽스처 안의 매치는 diff를 읽고 걸러낸다

4. 같은 체크리스트의 **수동 검토** 항목을 diff 기준으로 확인한다 — 변경된 줄과 그 줄이 영향을 주는 호출부만 본다

5. 심각도별로 정리해 보고한다

6. 🔴 critical 이슈가 있으면 수정 후 재실행을 요청한다. 없으면 커밋 진행을 승인한다.

## 결과 보고

```
=== Data 코드 리뷰 결과 ===
검토 파일: {파일 목록}

🔴 critical: {N}건
🟡 warning:  {N}건
🔵 suggestion: {N}건

{이슈 상세 목록 — `파일:라인` + 위반 규칙 + 수정 방향}

{이슈 없으면: "✅ 커밋 진행 가능"}
{🔴 있으면:   "🚫 커밋 전 critical 이슈를 수정하세요"}
```

## 주의사항

- 코드를 직접 수정하지 않는다 — 리뷰 결과만 보고한다.
- 변경되지 않은 기존 코드의 위반은 보고하지 않는다 (별도 이슈 제안으로만 언급).
