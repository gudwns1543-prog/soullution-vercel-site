# -*- coding: utf-8 -*-
"""
(주)솔루션 환경·에너지·탄소중립 정부지원사업 자동수집 서버 v2.1

핵심 개선사항
- 기업마당 API/RSS + 기관별 게시판 크롤링 병행
- 한국환경공단, 한국에너지공단, 신재생에너지센터, 중소벤처기업부, 산업통상자원부, 이지비즈 수집처 반영
- 공고 목록뿐 아니라 상세 본문(full_text/body), 첨부파일, PDF, 원문 링크 제공
- Claude API가 설정되어 있으면 공고 본문을 환경컨설팅 관점으로 자동 요약/분류/정제
- 사이트는 /api/supports, /api/supports/{id}, /api/file API를 통해 공고 전문과 첨부파일 표시

실행:
  python soullution_final_notice_crawler_server.py

선택 환경변수:
  set ANTHROPIC_API_KEY=Claude_API_Key
  set SOULLUTION_CLAUDE=1
  set PORT=8000
"""

import json
import os
import re
import time
import hashlib
import mimetypes
import urllib.request
import urllib.error
import urllib.parse
import ssl
from html import unescape, escape
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8000"))
# Vercel Serverless 환경에서는 코드 폴더가 읽기 전용일 수 있으므로 캐시/로그는 /tmp에 저장합니다.
RUNTIME_DIR = Path(os.environ.get("SOULLUTION_RUNTIME_DIR", "/tmp" if os.environ.get("VERCEL") else str(BASE_DIR)))
try:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass
CACHE_PATH = RUNTIME_DIR / "supports_cache.json"
LOG_PATH = RUNTIME_DIR / "crawler_log.txt"
MIN_DATE = os.environ.get("SOULLUTION_MIN_DATE", "2025-01-01")
CACHE_TTL_SECONDS = int(os.environ.get("SOULLUTION_CACHE_TTL", str(6 * 60 * 60)))
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
CLAUDE_ENABLED = os.environ.get("SOULLUTION_CLAUDE", "1").strip() not in ("0", "false", "False", "NO", "no")
CLAUDE_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
MAX_DETAIL_PER_SOURCE = int(os.environ.get("SOULLUTION_MAX_DETAIL_PER_SOURCE", "20"))
MAX_CLAUDE_ITEMS = int(os.environ.get("SOULLUTION_MAX_CLAUDE_ITEMS", "12"))

# 기관별 수집처. url이 여러 개인 경우 순차적으로 시도합니다.
SOURCES = [
    {
        "name": "기업마당",
        "type": "bizinfo_api",
        "api": True,
        "urls": [
            "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do",
            "https://www.bizinfo.go.kr/web/lay1/bbs/S1T122C128/AS/74/list.do",
        ],
    },
    {
        "name": "한국환경공단",
        "type": "html_board",
        "urls": [
            "https://www.keco.or.kr/web/lay1/bbs/S1T10C108/A/18/list.do",
            "https://www.keco.or.kr/web/lay1/bbs/S1T10C108/A/18/list.do?rows=30",
        ],
    },
    {
        "name": "한국에너지공단",
        "type": "html_board",
        "urls": [
            "https://www.energy.or.kr/front/board/List2.do",
            "https://www.energy.or.kr/front/board/List3.do",
        ],
    },
    {
        "name": "한국에너지공단 신재생에너지센터",
        "type": "html_board",
        "urls": [
            "https://www.knrec.or.kr/biz/pds/businoti/list.do",
            "https://www.knrec.or.kr/biz/pds/businoti/list.do?currentPage=1",
        ],
    },
    {
        "name": "중소벤처기업부",
        "type": "html_board",
        "urls": [
            "https://www.mss.go.kr/site/smba/ex/bbs/List.do?cbIdx=310",
            "https://www.mss.go.kr/site/smba/ex/bbs/List.do?cbIdx=81",
        ],
    },
    {
        "name": "산업통상자원부",
        "type": "html_board",
        "urls": [
            "https://www.motie.go.kr/kor/article/ATCL2826a2625",
            "https://www.motie.go.kr/kor/article/ATCL3f49a5a8c",
            "https://www.motie.go.kr/kor/article/ATCL8f2f5c9f5",
        ],
    },
    {
        "name": "이지비즈",
        "type": "html_board",
        "urls": [
            "https://www.egbiz.or.kr/prjCategory/a/m/selectPrjView.do",
            "https://www.egbiz.or.kr/prjCategory/a/m/selectPrjCategoryList.do",
            "https://www.egbiz.or.kr/",
        ],
    },
]

# 솔루션 고객에게 실제로 의미 있는 환경·에너지·탄소중립 지원사업을 선별하기 위한 키워드입니다.
ENV_KEYWORDS = [
    "환경", "탄소", "탄소중립", "온실가스", "배출권", "배출량", "감축", "저감", "cbam", "esg",
    "에너지", "효율", "절감", "진단", "시설개선", "고효율", "신재생", "재생에너지", "태양광", "열회수",
    "대기", "수질", "폐수", "악취", "폐기물", "자원순환", "스마트 생태공장", "생태공장", "오염", "방지시설",
    "공정개선", "클린", "녹색", "청정", "친환경", "전기화", "연료전환", "인증", "환경표지",
]
SUPPORT_KEYWORDS = [
    "지원", "보조", "보조금", "사업", "공고", "모집", "참여기업", "수혜기업", "신청", "접수",
    "융자", "자금", "정책자금", "금융", "대출", "이차보전", "바우처", "컨설팅", "진단", "구축", "개선",
    "기술개발", "r&d", "연구개발", "실증", "시범", "패키지", "원스톱", "선정", "추가모집",
]
EXCLUDE_KEYWORDS = [
    "채용", "입찰", "구매", "용역", "계약", "개찰", "낙찰", "행사", "교육생", "설문", "보도자료",
    "인사", "합격자", "회의", "홍보", "뉴스레터", "인턴", "서포터즈", "기자단", "설명회 자료", "결과보고회",
]


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def fetch_url(url: str, timeout: int = 25):
    opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 SoullutionNoticeCrawler/2.1",
        "Accept": "text/html,application/xhtml+xml,application/xml,application/json,application/rss+xml,application/pdf;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
        "Connection": "close",
    })
    with opener.open(req, timeout=timeout) as res:
        raw = res.read()
        ctype = res.headers.get("Content-Type", "")
        final_url = res.geturl()
        charset = "utf-8"
        m = re.search(r"charset=([\w\-]+)", ctype, re.I)
        if m:
            charset = m.group(1)
        for enc in [charset, "utf-8", "cp949", "euc-kr"]:
            try:
                return raw.decode(enc), ctype, final_url
            except Exception:
                pass
        return raw.decode("utf-8", errors="ignore"), ctype, final_url


def fetch_binary(url: str, timeout: int = 35):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 SoullutionNoticeCrawler/2.1",
        "Accept": "application/pdf,application/octet-stream,*/*",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            data = res.read()
            ctype = res.headers.get("Content-Type", "application/octet-stream")
            return data, guess_content_type(url, ctype, data)
    except urllib.error.URLError as first_error:
        if str(first_error).lower().find("certificate") < 0:
            raise
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as res:
            data = res.read()
            ctype = res.headers.get("Content-Type", "application/octet-stream")
            return data, guess_content_type(url, ctype, data)


def sniff_remote_file(url: str, timeout: int = 12) -> dict:
    """첨부 URL이 download.do처럼 확장자가 없어도 실제 PDF인지 가볍게 판별합니다."""
    info = {"url": url, "content_type": "", "filename": "", "type": "file", "is_pdf": False}
    if not url:
        return info
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 SoullutionNoticeCrawler/2.1",
        "Accept": "application/pdf,application/octet-stream,*/*",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
        "Range": "bytes=0-4095",
        "Connection": "close",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        try:
            res = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.URLError as first_error:
            if str(first_error).lower().find("certificate") < 0:
                raise
            res = urllib.request.urlopen(req, timeout=timeout, context=ssl._create_unverified_context())
        with res:
            ctype = res.headers.get("Content-Type", "") or ""
            disp = res.headers.get("Content-Disposition", "") or ""
            head = res.read(4096)
            filename = filename_from_disposition(disp)
            guessed = guess_content_type(url, ctype, head, filename)
            info.update({
                "content_type": guessed,
                "filename": filename,
                "type": ext_from_name(filename or url, guessed),
                "is_pdf": guessed.startswith("application/pdf") or head.startswith(b"%PDF") or (filename or url).lower().find(".pdf") >= 0,
            })
    except Exception as e:
        info["error"] = str(e)
        low = url.lower()
        info["is_pdf"] = ".pdf" in low or "pdf" in low
        info["type"] = "pdf" if info["is_pdf"] else ext_from_name(url, "")
    return info


def filename_from_disposition(value: str) -> str:
    value = value or ""
    m = re.search(r"filename\*=UTF-8''([^;]+)", value, re.I)
    if m:
        return urllib.parse.unquote(m.group(1)).strip(' "')
    m = re.search(r'filename="?([^";]+)"?', value, re.I)
    if m:
        return urllib.parse.unquote(m.group(1)).strip(' "')
    return ""


def guess_content_type(url: str, ctype: str = "", data: bytes = b"", filename: str = "") -> str:
    ctype = (ctype or "").split(";", 1)[0].strip().lower()
    low = f"{url or ''} {filename or ''}".lower()
    if data and data[:4] == b"%PDF":
        return "application/pdf"
    if ".pdf" in low or ("pdf" in low and ("download" in low or "file" in low or "atch" in low)):
        return "application/pdf"
    if ctype and ctype not in ("application/octet-stream", "binary/octet-stream", "application/unknown"):
        return ctype
    guessed = mimetypes.guess_type(filename or url or "")[0]
    return guessed or ctype or "application/octet-stream"


def ext_from_name(name: str, ctype: str = "") -> str:
    low = (name or "").lower()
    if ".pdf" in low or (ctype or "").startswith("application/pdf"):
        return "pdf"
    m = re.search(r"\.([a-z0-9]{2,5})(?:\?|$)", low)
    if m:
        return m.group(1)
    if "hwp" in low:
        return "hwp"
    return "file"


def strip_tags(s: str) -> str:
    s = s or ""
    s = re.sub(r"(?is)<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", " ", s)
    s = re.sub(r"(?is)<br\s*/?>", "\n", s)
    s = re.sub(r"(?is)</p>|</tr>|</li>|</div>|</td>|</th>|</h[1-6]>", "\n", s)
    s = re.sub(r"(?is)<.*?>", " ", s)
    s = unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n\s+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def clean_title(s: str) -> str:
    s = strip_tags(s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^(새글|공지|첨부|파일|번호|NEW|N)\s*", "", s, flags=re.I).strip()
    s = re.sub(r"\[[^\]]{1,20}\]\s*$", "", s).strip()
    return s[:240]


def abs_url(base: str, href: str) -> str:
    href = unescape(href or "").strip()
    if not href or href.startswith("#"):
        return ""
    if href.lower().startswith("javascript:"):
        # javascript:fn('123') 형태 게시판도 원문 링크 확인을 위해 현재 페이지로 남깁니다.
        return ""
    return urllib.parse.urljoin(base, href)


def make_id(source: str, title: str, url: str) -> str:
    return hashlib.md5(f"{source}|{title}|{url}".encode("utf-8")).hexdigest()[:12].upper()


def extract_date(text: str) -> str:
    text = text or ""
    patterns = [
        r"(20\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})",
        r"(20\d{2})(\d{2})(\d{2})",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            try:
                return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            except Exception:
                pass
    return ""


def extract_apply_period(text: str) -> str:
    text = text or ""
    # 2026-05-01 ~ 2026-06-01 / 2026. 5. 1. ~ 6. 1. 등 최대한 추출
    m = re.search(r"(20\d{2}[.\-/년]\s*\d{1,2}[.\-/월]\s*\d{1,2}[^\n]{0,20}[~∼～\-][^\n]{0,20}(?:20\d{2}[.\-/년]\s*)?\d{1,2}[.\-/월]\s*\d{1,2})", text)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.search(r"(?:신청|접수|공고)\s*(?:기간)?[^\n:：]{0,15}[:：]\s*([^\n]{6,80})", text)
    if m:
        return m.group(1).strip()
    return ""


def extract_labeled_value(text: str, labels, max_len: int = 500) -> str:
    text = text or ""
    label_pat = "|".join(re.escape(x) for x in labels)
    m = re.search(rf"(?:{label_pat})\s*[:：]?\s*([^\n]{{5,{max_len}}})", text, re.I)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:max_len]
    return ""


def is_target(title: str, text: str = "") -> bool:
    hay = f"{title} {text}".lower()
    if any(k.lower() in hay for k in EXCLUDE_KEYWORDS):
        return False
    has_support = any(k.lower() in hay for k in SUPPORT_KEYWORDS)
    has_env = any(k.lower() in hay for k in ENV_KEYWORDS)
    # 정부지원사업 사이트에서는 제목에 환경 키워드가 없더라도 지원사업성 키워드가 강하면 후보로 보관합니다.
    return has_support or has_env


def relevance_score(title: str, text: str = "") -> int:
    hay = f"{title} {text}".lower()
    score = 0
    score += min(50, sum(8 for k in ENV_KEYWORDS if k.lower() in hay))
    score += min(35, sum(4 for k in SUPPORT_KEYWORDS if k.lower() in hay))
    if any(k in hay for k in ["탄소중립", "온실가스", "에너지", "환경", "시설개선", "생태공장"]):
        score += 15
    if any(k.lower() in hay for k in EXCLUDE_KEYWORDS):
        score -= 40
    return max(0, min(100, score))


def classify(title: str, text: str = "") -> str:
    t = f"{title} {text}".lower()
    if any(k in t for k in ["탄소", "중립", "온실가스", "배출권", "cbam", "감축"]):
        return "탄소중립"
    if any(k in t for k in ["환경", "생태", "폐수", "수질", "대기", "악취", "오염", "폐기물", "자원순환", "방지시설"]):
        return "환경"
    if any(k in t for k in ["에너지", "효율", "절감", "신재생", "재생에너지", "태양광", "열회수"]):
        return "에너지"
    if any(k in t for k in ["융자", "자금", "금융", "대출", "이차보전", "정책자금"]):
        return "금융"
    if any(k in t for k in ["기술개발", "r&d", "연구개발", "실증"]):
        return "R&D"
    if any(k in t for k in ["규제", "감독", "의무", "고시", "지침", "인증", "검사", "공시"]):
        return "규제·인증"
    return "지원사업"


def extract_attachments(base: str, html: str):
    files, seen = [], set()
    html = html or ""

    def add_file(url, label="첨부파일", around=""):
        url = abs_url(base, url)
        if not url or url in seen:
            return
        u = url.lower()
        label_text = clean_title(label) or "첨부파일"
        around_text = clean_title(around)
        file_hint = f"{u} {label_text.lower()} {around_text.lower()}"
        is_file = (
            bool(re.search(r"\.(pdf|hwp|hwpx|doc|docx|xls|xlsx|zip|ppt|pptx)(\?|$)", u))
            or any(x in u for x in ["download", "file", "atch", "attach", "getfile", "filedown", "downfile"])
            or bool(re.search(r"\.(pdf|hwp|hwpx|docx?|xlsx?|zip|pptx?)", file_hint, re.I))
        )
        if not is_file:
            return
        seen.add(url)
        ext = ext_from_name(label_text + " " + url, "")
        if ext == "file":
            m = re.search(r"([^\s<>\"']{2,120}\.(?:pdf|hwp|hwpx|docx?|xlsx?|zip|pptx?))", around_text, re.I)
            if m:
                label_text = m.group(1)
                ext = ext_from_name(label_text, "")
        if ext == "file" and "pdf" in file_hint:
            ext = "pdf"
        files.append({"name": label_text[:160], "url": url, "type": ext})

    for m in re.finditer(r'(?is)<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html):
        around_html = html[max(0, m.start() - 600):m.end() + 600]
        add_file(m.group(1), m.group(2), strip_tags(around_html))

    for m in re.finditer(r'(?is)(?:href|src|data-url|data-href|onclick)=["\']([^"\']*(?:download|file|atch|attach|getfile|filedown|downfile)[^"\']*)["\']', html):
        around_html = html[max(0, m.start() - 600):m.end() + 600]
        add_file(m.group(1), "첨부파일", strip_tags(around_html))

    for m in re.finditer(r"https?://[^\s'\"<>]+\.(?:pdf|hwp|hwpx|docx?|xlsx?|zip|pptx?)(?:\?[^\s'\"<>]*)?", html, re.I):
        add_file(m.group(0), "첨부파일", m.group(0))

    enriched = []
    for f in files[:12]:
        low = f"{f.get('name','')} {f.get('url','')}".lower()
        if f.get("type") == "pdf" or ".pdf" in low:
            enriched.append(f)
            continue
        if any(x in low for x in ["download", "file", "atch", "attach", "getfile", "다운로드"]):
            meta = sniff_remote_file(f.get("url", ""))
            if meta.get("is_pdf"):
                f["type"] = "pdf"
                f["content_type"] = "application/pdf"
                if meta.get("filename") and f.get("name") in ("첨부파일", "다운로드", "파일", "보기"):
                    f["name"] = meta["filename"]
            elif meta.get("type") and f.get("type") == "file":
                f["type"] = meta["type"]
                if meta.get("content_type"):
                    f["content_type"] = meta["content_type"]
        enriched.append(f)
    return enriched


def build_detail_html(item: dict) -> str:
    def e(v):
        return escape(str(v or ""))

    summary = item.get("summary") or ""
    target = item.get("target") or ""
    benefit = item.get("benefit") or ""
    apply_period = item.get("apply_period") or ""
    apply_method = item.get("apply_method") or ""
    contact = item.get("contact") or ""
    reason = item.get("ai_reason") or item.get("reason") or ""
    full_text = item.get("full_text") or item.get("raw_text") or ""
    full_text = re.sub(r"\n{3,}", "\n\n", full_text).strip()
    full_text_html = e(full_text[:12000]).replace("\n", "<br>")

    rows = []
    if apply_period:
        rows.append(f"<tr><th>신청/접수기간</th><td>{e(apply_period)}</td></tr>")
    if target:
        rows.append(f"<tr><th>지원대상</th><td>{e(target)}</td></tr>")
    if benefit:
        rows.append(f"<tr><th>지원내용</th><td>{e(benefit)}</td></tr>")
    if apply_method:
        rows.append(f"<tr><th>신청방법</th><td>{e(apply_method)}</td></tr>")
    if contact:
        rows.append(f"<tr><th>문의처</th><td>{e(contact)}</td></tr>")

    summary_html = e(summary).replace("\n", "<br>")
    reason_html = e(reason).replace("\n", "<br>")

    return f"""
<div class="notice-inside-view">
  <h3>AI 핵심 요약</h3>
  <p>{summary_html or '상세 본문을 기준으로 공고 내용을 확인해 주세요.'}</p>
  {('<p style="margin-top:8px;color:#276749"><strong>솔루션 관점:</strong> ' + reason_html + '</p>') if reason_html else ''}
  <table class="detail-table">
    {''.join(rows) if rows else '<tr><th>주요내용</th><td>공고 전문에서 신청기간, 지원대상, 지원내용을 확인해 주세요.</td></tr>'}
  </table>
  <h3 style="margin-top:24px">공고 전문</h3>
  <div class="notice-full-text">{full_text_html or '전문을 불러오지 못했습니다. 원문 공고 확인 버튼을 이용해 주세요.'}</div>
</div>
""".strip()


def fetch_detail(item: dict) -> dict:
    url = item.get("detail_url", "")
    if not url:
        return item
    try:
        html, ctype, final_url = fetch_url(url, timeout=25)
        if final_url:
            item["detail_url"] = final_url
        if "application/pdf" in (ctype or "").lower() or str(final_url or url).lower().find(".pdf") >= 0:
            item["attachments"] = [{"name": item.get("title") or "공고문 PDF", "url": final_url or url, "type": "pdf", "content_type": "application/pdf"}]
            item["pdf_url"] = final_url or url
            item["full_text"] = item.get("summary") or "PDF 원문으로 제공되는 공고입니다. 아래 PDF 미리보기에서 공고문을 확인해 주세요."
            item["body"] = build_detail_html(item)
            return item

        text = strip_tags(html)
        files = extract_attachments(item["detail_url"], html)
        item["attachments"] = files
        pdf = next((f["url"] for f in files if f.get("type") == "pdf" or ".pdf" in f.get("url", "").lower() or (f.get("content_type", "").lower().startswith("application/pdf"))), "")
        item["pdf_url"] = pdf
        item["full_text"] = text[:20000]
        item["apply_period"] = item.get("apply_period") or extract_apply_period(text)
        item["target"] = item.get("target") or extract_labeled_value(text, ["지원대상", "신청대상", "대상", "자격요건"], 600)
        item["benefit"] = item.get("benefit") or extract_labeled_value(text, ["지원내용", "지원규모", "사업내용", "지원금액"], 800)
        item["apply_method"] = item.get("apply_method") or extract_labeled_value(text, ["신청방법", "접수방법", "신청 및 접수", "접수처"], 600)
        item["contact"] = item.get("contact") or extract_labeled_value(text, ["문의처", "담당자", "문의", "연락처"], 400)
        item["summary"] = item.get("summary") or re.sub(r"\s+", " ", text[:700]).strip()
        item["category"] = item.get("category") or classify(item.get("title", ""), text)
        item["relevance_score"] = relevance_score(item.get("title", ""), text)
        item["body"] = build_detail_html(item)
    except Exception as e:
        item["attachments"] = item.get("attachments", [])
        item["full_text"] = item.get("full_text", "")
        item["body"] = f"<p>상세 내용을 불러오지 못했습니다. 원문 링크를 확인하세요.<br>{escape(str(e))}</p>"
        item["crawl_error"] = str(e)
    return item


def extract_links(source: dict, html: str, base_url: str):
    rows = []
    html = html or ""
    for m in re.finditer(r'(?is)<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html):
        title = clean_title(m.group(2))
        if len(title) < 5 or len(title) > 180:
            continue
        around = strip_tags(html[max(0, m.start() - 900):m.end() + 900])
        if not is_target(title, around):
            continue
        date = extract_date(around) or datetime.now().strftime("%Y-%m-%d")
        if date < MIN_DATE:
            continue
        url = abs_url(base_url, m.group(1))
        if not url:
            continue
        text_for_class = f"{title} {around}"
        rows.append({
            "id": make_id(source["name"], title, url),
            "title": title,
            "agency": source["name"],
            "source": source["name"],
            "region": "경기" if source["name"] == "이지비즈" else "전국",
            "category": classify(title, around),
            "published_at": date,
            "apply_period": extract_apply_period(around),
            "detail_url": url,
            "pdf_url": "",
            "summary": re.sub(r"\s+", " ", around[:600]).strip(),
            "body": "",
            "full_text": "",
            "attachments": [],
            "relevance_score": relevance_score(title, around),
        })
    return rows


def normalize_bizinfo_item(x: dict):
    title = str(x.get("pblancNm") or x.get("title") or x.get("pblancTitle") or x.get("bsnsNm") or "").strip()
    blob = json.dumps(x, ensure_ascii=False)
    if not title or not is_target(title, blob):
        return None
    date = extract_date(str(x.get("creatPnttm") or x.get("registDt") or x.get("pblancBeginDt") or x.get("reqstBeginEndDe") or "")) or datetime.now().strftime("%Y-%m-%d")
    if date < MIN_DATE:
        return None
    detail = str(x.get("pblancUrl") or x.get("url") or x.get("link") or x.get("detailUrl") or "https://www.bizinfo.go.kr").strip()
    agency = str(x.get("jrsdInsttNm") or x.get("excInsttNm") or x.get("agency") or "기업마당")
    summary = str(x.get("bsnsSumryCn") or x.get("summary") or x.get("cn") or "")
    return {
        "id": make_id("기업마당", title, detail),
        "title": title,
        "agency": agency,
        "source": "기업마당",
        "region": str(x.get("areaNm") or x.get("trgetNm") or "전국"),
        "category": classify(title, blob),
        "published_at": date,
        "apply_period": str(x.get("reqstBeginEndDe") or x.get("pblancBeginDt") or ""),
        "target": str(x.get("trgetNm") or x.get("pldirSportRealmLclasCodeNm") or ""),
        "benefit": summary[:700],
        "apply_method": "",
        "contact": str(x.get("refrncNm") or x.get("telNo") or ""),
        "detail_url": detail,
        "pdf_url": "",
        "summary": summary[:900],
        "body": "",
        "full_text": summary,
        "attachments": [],
        "relevance_score": relevance_score(title, blob),
    }


def crawl_bizinfo(source: dict):
    rows = []
    urls = []
    for base in source.get("urls", []):
        if "bizinfoApi.do" in base:
            urls.extend([
                base + "?dataType=json&searchCnt=100",
                base + "?type=json&searchCnt=100",
                base,
            ])
        else:
            urls.append(base)

    for url in urls:
        try:
            raw, ctype, final_url = fetch_url(url, timeout=25)
            text = raw.strip()
            if text.startswith("{") or text.startswith("["):
                data = json.loads(text)
                arr = data
                if isinstance(data, dict):
                    for key in ["jsonArray", "items", "data", "list", "result", "body"]:
                        if key in data:
                            arr = data[key]
                            break
                if isinstance(arr, dict):
                    arr = list(arr.values())
                if isinstance(arr, list):
                    for x in arr:
                        if isinstance(x, dict):
                            item = normalize_bizinfo_item(x)
                            if item:
                                rows.append(item)
            else:
                rows.extend(extract_links({"name": "기업마당"}, raw, final_url or url))
        except Exception as e:
            log(f"기업마당 후보 실패 {url}: {e}")
    return rows


def crawl_html_source(source: dict):
    rows = []
    for url in source.get("urls", []):
        try:
            html, ctype, final_url = fetch_url(url, timeout=25)
            rows.extend(extract_links(source, html, final_url or url))
        except Exception as e:
            log(f"{source['name']} 후보 실패 {url}: {e}")
    return rows


def call_claude_for_notice(item: dict) -> dict:
    if not (ANTHROPIC_API_KEY and CLAUDE_ENABLED):
        return item
    full_text = (item.get("full_text") or item.get("summary") or "").strip()
    if len(full_text) < 120:
        return item

    prompt = f"""
다음은 정부지원사업/기관 공고 원문입니다.
(주)솔루션은 환경컨설팅, 에너지진단, 탄소중립, ESG, 환경 인허가, 환경설비 개선 컨설팅 회사입니다.

이 공고가 솔루션 고객에게 유의미한 환경/에너지/탄소중립/중소기업 지원사업인지 판단하고,
반드시 JSON 객체 하나로만 답변하세요. 설명 문장, 마크다운, 코드블록은 금지합니다.

필드:
- is_relevant: true 또는 false
- relevance_score: 0~100 정수
- category: 환경, 에너지, 탄소중립, ESG, 금융, R&D, 규제·인증, 지원사업, 기타 중 하나
- summary: 5줄 이내 핵심 요약
- target: 지원대상
- benefit: 지원내용
- apply_period: 신청기간 또는 접수기간
- apply_method: 신청방법
- contact: 문의처
- reason: 솔루션 고객에게 중요한 이유

공고명: {item.get('title')}
기관: {item.get('agency') or item.get('source')}
원문 URL: {item.get('detail_url')}

공고 원문:
{full_text[:12000]}
""".strip()

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 1800,
        "temperature": 0.1,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as res:
            data = json.loads(res.read().decode("utf-8"))
        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            raise ValueError("Claude JSON 응답을 찾지 못했습니다.")
        refined = json.loads(m.group(0))
        item["ai_refined"] = True
        item["is_relevant"] = bool(refined.get("is_relevant", True))
        item["relevance_score"] = int(refined.get("relevance_score") or item.get("relevance_score") or 0)
        item["category"] = str(refined.get("category") or item.get("category") or "지원사업")
        item["summary"] = str(refined.get("summary") or item.get("summary") or "")[:1200]
        item["target"] = str(refined.get("target") or item.get("target") or "")[:1000]
        item["benefit"] = str(refined.get("benefit") or item.get("benefit") or "")[:1200]
        item["apply_period"] = str(refined.get("apply_period") or item.get("apply_period") or "")[:400]
        item["apply_method"] = str(refined.get("apply_method") or item.get("apply_method") or "")[:1000]
        item["contact"] = str(refined.get("contact") or item.get("contact") or "")[:600]
        item["ai_reason"] = str(refined.get("reason") or "")[:1000]
    except Exception as e:
        item["ai_refined"] = False
        item["ai_error"] = str(e)[:300]
        log(f"Claude 정제 실패 [{item.get('title','')[:40]}]: {e}")
    return item


def finalize_item(item: dict) -> dict:
    # Claude/규칙 추출 이후 body 재생성
    if not item.get("category"):
        item["category"] = classify(item.get("title", ""), item.get("full_text", ""))
    if not item.get("relevance_score"):
        item["relevance_score"] = relevance_score(item.get("title", ""), item.get("full_text", ""))
    item["body"] = build_detail_html(item)
    return item


def crawl_source(source: dict):
    log(f"{source['name']} 공고 수집 시작")
    try:
        if source.get("api"):
            rows = crawl_bizinfo(source)
        else:
            rows = crawl_html_source(source)

        dedup, seen = [], set()
        for r in rows:
            key = (r.get("title", "").strip(), r.get("agency", "").strip(), r.get("detail_url", "").strip())
            if not key[0] or key in seen:
                continue
            seen.add(key)
            dedup.append(r)

        dedup = sorted(dedup, key=lambda x: (x.get("published_at", ""), x.get("relevance_score", 0)), reverse=True)
        detailed = []
        for r in dedup[:MAX_DETAIL_PER_SOURCE]:
            detailed.append(fetch_detail(r))
            time.sleep(0.12)
        log(f"{source['name']} 수집 완료: {len(detailed)}건")
        return detailed
    except Exception as e:
        log(f"{source['name']} 수집 실패: {e}")
        return []


FALLBACK = [
    {
        "id": "SAMPLE-001",
        "title": "중소기업 탄소중립 설비투자 지원사업 공고",
        "agency": "중소벤처기업부",
        "source": "중소벤처기업부",
        "region": "전국",
        "category": "탄소중립",
        "published_at": "2026-05-01",
        "apply_period": "공고문 확인",
        "detail_url": "https://www.mss.go.kr",
        "pdf_url": "",
        "attachments": [],
        "summary": "자동수집 서버 연결 전 표시되는 예비 공고입니다.",
        "full_text": "자동수집 결과가 없을 때 표시되는 예비 공고입니다. /api/crawler/log에서 크롤러 로그를 확인하세요.",
        "relevance_score": 80,
    }
]
for _x in FALLBACK:
    _x["body"] = build_detail_html(_x)


def collect(force: bool = False):
    if not force and CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if time.time() - cache.get("timestamp", 0) < CACHE_TTL_SECONDS:
                return cache.get("items", FALLBACK), cache.get("updated_at", "")
        except Exception:
            pass

    items = []
    for source in SOURCES:
        items.extend(crawl_source(source))

    dedup = {}
    for x in items:
        if x.get("published_at", "") and x.get("published_at", "") < MIN_DATE:
            continue
        key = (x.get("title", "").strip(), x.get("agency", x.get("source", "")).strip())
        if key[0] and key not in dedup:
            dedup[key] = x
        elif key in dedup:
            # 첨부/본문이 더 풍부한 쪽을 선택
            old = dedup[key]
            old_score = len(old.get("full_text", "")) + len(old.get("attachments", [])) * 500
            new_score = len(x.get("full_text", "")) + len(x.get("attachments", [])) * 500
            if new_score > old_score:
                dedup[key] = x

    items = list(dedup.values())
    items = sorted(items, key=lambda x: (x.get("published_at", ""), x.get("relevance_score", 0)), reverse=True)

    # Claude는 상위 후보에만 적용합니다. API 키가 없으면 규칙 기반 정제로만 진행됩니다.
    claude_count = 0
    for item in items:
        if claude_count >= MAX_CLAUDE_ITEMS:
            break
        if item.get("relevance_score", 0) >= 20:
            call_claude_for_notice(item)
            claude_count += 1
            time.sleep(0.2)

    finalized = []
    for x in items:
        # Claude가 명시적으로 관련 없다고 판단한 낮은 점수 공고는 제외합니다.
        if x.get("ai_refined") and x.get("is_relevant") is False and int(x.get("relevance_score", 0)) < 45:
            continue
        finalized.append(finalize_item(x))

    if not finalized:
        finalized = FALLBACK

    updated = datetime.now().strftime("%Y-%m-%d %H:%M")
    payload = {"timestamp": time.time(), "updated_at": updated, "items": finalized}
    CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return finalized, updated


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 기본 HTTP 로그를 줄이고 crawler_log.txt에는 필요한 로그만 남깁니다.
        return

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/health":
            self.send_json(200, {
                "ok": True,
                "service": "soullution-environment-notice-crawler-v2",
                "min_date": MIN_DATE,
                "cache_ttl_seconds": CACHE_TTL_SECONDS,
                "claude_enabled": bool(ANTHROPIC_API_KEY and CLAUDE_ENABLED),
                "sources": [s["name"] for s in SOURCES],
            })
            return

        if path == "/api/supports":
            items, updated = collect(force=("refresh" in query))
            self.send_json(200, {"ok": True, "updated_at": updated, "items": items})
            return

        if path.startswith("/api/supports/"):
            sid = urllib.parse.unquote(path.rsplit("/", 1)[-1])
            items, updated = collect(False)
            found = next((x for x in items if str(x.get("id")) == str(sid)), None)
            self.send_json(200, {"ok": True, "updated_at": updated, "item": found} if found else {"ok": False, "error": "공고를 찾을 수 없습니다."})
            return

        if path == "/api/crawler/log":
            text = LOG_PATH.read_text(encoding="utf-8", errors="ignore") if LOG_PATH.exists() else ""
            self.send_json(200, {"ok": True, "log": text[-20000:]})
            return

        if path == "/api/news":
            self.send_json(200, {"ok": True, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "items": []})
            return

        if path == "/api/file":
            url = query.get("url", [""])[0]
            if not url:
                self.send_json(400, {"ok": False, "error": "url 필요"})
                return
            try:
                data, ctype = fetch_binary(url)
                ctype = guess_content_type(url, ctype, data)
                filename = urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name or "notice-file")
                if ctype == "application/pdf" and not filename.lower().endswith(".pdf"):
                    filename = "notice.pdf"
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Type", ctype or "application/octet-stream")
                self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{urllib.parse.quote(filename)}")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    return
            except Exception as e:
                self.send_json(502, {"ok": False, "error": str(e)})
            return

        if path == "/":
            # 운영 기준 파일은 soullution_home.html입니다. 같은 폴더에 과거 작업본이 있어도 이 파일을 우선 표시합니다.
            path = "/soullution_home.html"

        safe = urllib.parse.unquote(path).lstrip("/").replace("\\", "/")
        if ".." in safe:
            self.send_json(403, {"ok": False, "error": "Forbidden"})
            return
        fp = BASE_DIR / safe
        if not fp.exists() or not fp.is_file():
            self.send_json(404, {"ok": False, "error": "Not Found"})
            return
        data = fp.read_bytes()
        ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    print("=" * 78)
    print("(주)솔루션 환경·에너지·탄소중립 정부지원사업 자동수집 서버 v2.1")
    print("- 공고 목록 + 사이트 내 전문 보기 + 첨부파일/PDF + 원문 링크")
    print(f"- Claude API 연동: {'사용' if ANTHROPIC_API_KEY and CLAUDE_ENABLED else '미사용 또는 API 키 없음'}")
    print(f"- 포트: {PORT}")
    print("상태:      http://localhost:%s/api/health" % PORT)
    print("강제수집:  http://localhost:%s/api/supports?refresh=1" % PORT)
    print("로그:      http://localhost:%s/api/crawler/log" % PORT)
    print("홈페이지:  http://localhost:%s/" % PORT)
    print("=" * 78)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
