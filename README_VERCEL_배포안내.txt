솔루션 대표사이트 Vercel 배포용 v2.5

변경사항:
- Vercel Build Failed 원인이던 vercel.json의 functions 설정을 제거했습니다.
- API 라우팅은 /api/(.*) -> /api/index.py rewrites만 사용합니다.
- GitHub에 기존 저장소 그대로 덮어쓰기 업로드 후 Vercel이 자동 재배포되면 됩니다.

Vercel 환경변수 권장값:
SOULLUTION_CLAUDE=0
SOULLUTION_CACHE_TTL=21600
SOULLUTION_MAX_DETAIL_PER_SOURCE=6
SOULLUTION_MAX_CLAUDE_ITEMS=0

배포 후 확인 주소:
/
/api/health
/api/supports?refresh=1
/api/crawler/log
