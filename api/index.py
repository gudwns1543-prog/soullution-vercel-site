# -*- coding: utf-8 -*-
"""
Vercel Python WSGI entrypoint for (주)솔루션 대표사이트.
No Flask dependency: this file exposes a WSGI callable named `app`.
"""
import json
import os
import re
import sys
import urllib.parse
from datetime import datetime
from html import escape
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from lib.soullution_crawler_core import (  # noqa: E402
    ANTHROPIC_API_KEY,
    CLAUDE_ENABLED,
    CACHE_TTL_SECONDS,
    FALLBACK,
    LOG_PATH,
    MIN_DATE,
    SOURCES,
    collect,
    fetch_binary,
    fetch_url,
    guess_content_type,
)


def _start(start_response, status="200 OK", headers=None):
    base = [
        ("Access-Control-Allow-Origin", "*"),
        ("Access-Control-Allow-Headers", "Content-Type"),
        ("Access-Control-Allow-Methods", "GET, OPTIONS"),
    ]
    if headers:
        base.extend(headers)
    start_response(status, base)


def _json(start_response, data, status="200 OK"):
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    _start(start_response, status, [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ])
    return [body]


def _html(start_response, html, status="200 OK"):
    body = html.encode("utf-8", errors="ignore")
    _start(start_response, status, [
        ("Content-Type", "text/html; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ])
    return [body]


def _bytes(start_response, data, ctype="application/octet-stream", filename="notice-file"):
    _start(start_response, "200 OK", [
        ("Content-Type", ctype or "application/octet-stream"),
        ("Content-Disposition", "inline; filename*=UTF-8''" + urllib.parse.quote(filename)),
        ("X-Content-Type-Options", "nosniff"),
        ("Content-Length", str(len(data))),
    ])
    return [data]


def app(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/") or "/"
    query = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)

    if method == "OPTIONS":
        _start(start_response, "204 No Content", [])
        return [b""]

    if path == "/api/health":
        return _json(start_response, {
            "ok": True,
            "service": "soullution-vercel-notice-crawler",
            "runtime": "vercel-python-wsgi-function",
            "min_date": MIN_DATE,
            "cache_ttl_seconds": CACHE_TTL_SECONDS,
            "claude_enabled": bool(ANTHROPIC_API_KEY and CLAUDE_ENABLED),
            "sources": [s["name"] for s in SOURCES],
        })

    if path == "/api/supports":
        force = "refresh" in query
        try:
            items, updated = collect(force=force)
            return _json(start_response, {"ok": True, "updated_at": updated, "items": items})
        except Exception as e:
            updated = datetime.now().strftime("%Y-%m-%d %H:%M")
            return _json(start_response, {"ok": False, "updated_at": updated, "items": FALLBACK, "error": str(e)}, "200 OK")

    if path.startswith("/api/supports/"):
        sid = urllib.parse.unquote(path.rsplit("/", 1)[-1])
        items, updated = collect(force=False)
        found = next((x for x in items if str(x.get("id")) == str(sid)), None)
        if not found:
            return _json(start_response, {"ok": False, "error": "공고를 찾을 수 없습니다."}, "404 Not Found")
        return _json(start_response, {"ok": True, "updated_at": updated, "item": found})

    if path == "/api/crawler/log":
        text = LOG_PATH.read_text(encoding="utf-8", errors="ignore") if LOG_PATH.exists() else ""
        return _json(start_response, {"ok": True, "log": text[-20000:]})

    if path == "/api/news":
        return _json(start_response, {"ok": True, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "items": []})

    if path == "/api/file":
        url = query.get("url", [""])[0].strip()
        if not url:
            return _json(start_response, {"ok": False, "error": "url 필요"}, "400 Bad Request")
        if not url.lower().startswith(("http://", "https://")):
            return _json(start_response, {"ok": False, "error": "http/https URL만 허용됩니다."}, "400 Bad Request")
        try:
            data, ctype = fetch_binary(url)
            ctype = guess_content_type(url, ctype, data)
            filename = urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name or "notice-file")
            if ctype == "application/pdf" and not filename.lower().endswith(".pdf"):
                filename = "notice.pdf"
            return _bytes(start_response, data, ctype, filename)
        except Exception as e:
            return _json(start_response, {"ok": False, "error": str(e)}, "502 Bad Gateway")

    if path == "/api/page":
        url = query.get("url", [""])[0].strip()
        if not url:
            return _json(start_response, {"ok": False, "error": "url 필요"}, "400 Bad Request")
        if not url.lower().startswith(("http://", "https://")):
            return _json(start_response, {"ok": False, "error": "http/https URL만 허용됩니다."}, "400 Bad Request")
        try:
            text, ctype, final_url = fetch_url(url, timeout=25)
            base = escape(final_url, quote=True)
            if re.search(r"<head[^>]*>", text, re.I):
                text = re.sub(r"<head([^>]*)>", r"<head\1><base href=\"%s\">" % base, text, count=1, flags=re.I)
            else:
                text = f'<base href="{base}">' + text
            notice = """
            <style>
              body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;line-height:1.55;}
              img{max-width:100%;height:auto;}
            </style>
            """
            if re.search(r"</head>", text, re.I):
                text = re.sub(r"</head>", notice + "</head>", text, count=1, flags=re.I)
            else:
                text = notice + text
            return _html(start_response, text)
        except Exception as e:
            html = f"""
            <!doctype html><meta charset='utf-8'>
            <div style='font-family:system-ui;padding:40px;line-height:1.7;color:#334;'>
              <h2>원문 공고 미리보기를 불러오지 못했습니다.</h2>
              <p>기관 사이트 보안 설정 또는 접속 제한으로 내부 미리보기가 제한될 수 있습니다.</p>
              <p style='color:#777'>{escape(str(e))}</p>
              <p><a href='{escape(url, quote=True)}' target='_blank' rel='noopener'>원문 공고 새 창으로 열기</a></p>
            </div>
            """
            return _html(start_response, html)

    return _json(start_response, {"ok": False, "error": "Not Found", "path": path}, "404 Not Found")
