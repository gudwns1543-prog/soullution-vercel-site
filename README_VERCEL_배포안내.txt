(주)솔루션 대표사이트 Vercel 배포용 v2.4

수정사항:
- Vercel 빌드 오류 "Function Runtimes must have a valid version" 해결
- vercel.json에서 runtime 직접 지정을 제거하고 Vercel의 Python 자동 감지를 사용
- __pycache__ 파일 제거

Vercel 환경변수 권장값:
SOULLUTION_CLAUDE=0
SOULLUTION_CACHE_TTL=21600
SOULLUTION_MAX_DETAIL_PER_SOURCE=6
SOULLUTION_MAX_CLAUDE_ITEMS=0

배포 확인 주소:
/
/api/health
/api/supports?refresh=1
/api/crawler/log
