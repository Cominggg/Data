다음 단계로 커밋을 완료해줘:

1. `git status`와 `git diff` (staged + unstaged 모두)를 확인해서 변경 사항 파악
2. 변경 내용을 분석해서 커밋 메시지를 `feat/fix/chore/docs: <한국어 내용>` 형식으로 작성
   - feat: 새 기능
   - fix: 버그 수정
   - chore: 빌드/설정/의존성 변경
   - docs: 문서 변경
3. 관련 파일을 `git add <파일명>` 으로 스테이징 (절대 `git add -A` 나 `git add .` 사용 금지, .env 등 민감한 파일 제외)
4. `git commit -m "..."` 으로 실제 커밋 실행
5. 커밋 성공 여부 확인

변경 사항이 없으면 커밋하지 않고 사용자에게 알려줘.
