# 솔루션 대표사이트 Vercel 배포용 v2.6

## v2.6 수정 내용
- Vercel에서 루트 주소(/)가 Python Function으로 들어오는 경우에도 홈페이지 HTML을 직접 반환하도록 수정했습니다.
- 기존처럼 /api/health, /api/supports, /api/file, /api/page는 Python API에서 처리합니다.
- 기존 GitHub 저장소에 이 폴더 내용을 그대로 덮어쓰기 업로드 후 Commit changes 하세요.

## Vercel 환경변수 권장값
SOULLUTION_CLAUDE=0
SOULLUTION_CACHE_TTL=21600
SOULLUTION_MAX_DETAIL_PER_SOURCE=6
SOULLUTION_MAX_CLAUDE_ITEMS=0
