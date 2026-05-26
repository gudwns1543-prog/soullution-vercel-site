(주)솔루션 대표사이트 Vercel + GitHub 배포용 패키지

1. 폴더 구조
- public/index.html : 대표사이트 화면
- api/index.py : Vercel Python WSGI API
- lib/soullution_crawler_core.py : 정부지원사업 공고 수집/파일 프록시 핵심 로직
- vercel.json : Vercel 배포 설정
- requirements.txt : Python 의존성 설정
- .gitignore : GitHub 업로드 제외 파일

2. Vercel에서 확인할 주소
- / : 홈페이지
- /api/health : 서버 상태 확인
- /api/supports : 공고 목록
- /api/supports?refresh=1 : 공고 강제수집
- /api/crawler/log : 수집 로그
- /api/file?url=... : 첨부파일/PDF 프록시
- /api/page?url=... : 원문 공고 페이지 내부 미리보기 프록시

3. Vercel 환경변수 권장값
- SOULLUTION_CLAUDE = 0
- SOULLUTION_CACHE_TTL = 21600
- SOULLUTION_MAX_DETAIL_PER_SOURCE = 6
- SOULLUTION_MAX_CLAUDE_ITEMS = 0

Claude API를 실제로 사용할 때만 아래 값을 추가합니다.
- ANTHROPIC_API_KEY = 실제 Claude API Key
- SOULLUTION_CLAUDE = 1
- SOULLUTION_MAX_CLAUDE_ITEMS = 3

4. 주의사항
Vercel은 일반 VPS처럼 24시간 켜져 있는 서버가 아니라 요청이 들어올 때 실행되는 서버리스 함수 방식입니다.
따라서 공고 수집은 /api/supports?refresh=1 요청이 들어올 때 실행됩니다.
정기 자동수집은 추후 Vercel Cron 또는 외부 스케줄러로 연결하는 것을 권장합니다.
