"""네이버 뉴스 검색 / 설정 / 이메일 발송 공용 모듈.

app_gui.py(데스크톱 앱)와 send_news.py(자동 발송 스크립트)가 함께 사용한다.
"""
import json
import os
import re
import smtplib
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

TASK_NAME = "NaverNewsDaily"

DEFAULT_CONFIG = {
    "api": {"client_id": "", "client_secret": ""},
    "keywords": [],
    "search": {"display": 10, "sort": "date", "period": 0},
    "email": {
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "sender": "",
        "password": "",
        "recipient": "",
    },
    "schedule": {"time": "09:00", "enabled": False},
}

# 기간 라벨 -> 일수 (0 = 전체)
PERIOD_OPTIONS = {
    "전체": 0,
    "최근 1일": 1,
    "최근 1주": 7,
    "최근 1개월": 30,
    "최근 3개월": 90,
    "최근 1년": 365,
}


# ---------- 설정 ----------
def _merge_defaults(config):
    """누락된 최상위/하위 키를 기본값으로 보충."""
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for key, val in config.items():
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key].update(val)
        else:
            merged[key] = val
    return merged


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return _merge_defaults(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def normalize_keywords(raw):
    """문자열/객체 혼용을 {text, required} 형식으로 통일 (구버전 호환)."""
    result = []
    for kw in raw:
        if isinstance(kw, str):
            result.append({"text": kw, "required": False})
        elif isinstance(kw, dict) and kw.get("text"):
            result.append({"text": kw["text"],
                           "required": bool(kw.get("required", False))})
    return result


# ---------- 검색 ----------
def strip_tags(text):
    text = re.sub(r"<.*?>", "", text)
    for a, b in [("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&"),
                 ("&quot;", '"'), ("&apos;", "'"), ("&#39;", "'")]:
        text = text.replace(a, b)
    return text.strip()


def within_period(item, cutoff):
    pub = item.get("pubDate", "")
    try:
        dt = parsedate_to_datetime(pub)
    except (TypeError, ValueError):
        return True  # 날짜 파싱 실패 시 제외하지 않음
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= cutoff


def fetch_news(query, client_id, client_secret, display, sort):
    url = "https://openapi.naver.com/v1/search/news.json?" + urllib.parse.urlencode({
        "query": query, "display": display, "sort": sort,
    })
    req = urllib.request.Request(url)
    req.add_header("X-Naver-Client-Id", client_id)
    req.add_header("X-Naver-Client-Secret", client_secret)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8")).get("items", [])


def build_queries(keywords):
    """필수 키워드는 AND로 묶어 1건, 일반 키워드는 개별. -> [(label, query), ...]"""
    required = [k["text"] for k in keywords if k["required"]]
    normal = [k["text"] for k in keywords if not k["required"]]
    queries = []
    if required:
        queries.append(("⭐ 필수: " + " + ".join(required), " ".join(required)))
    for kw in normal:
        queries.append((kw, kw))
    return queries


def run_search(config):
    """설정대로 검색을 실행해 {label: [items]} 반환. 네트워크 예외는 호출자가 처리."""
    api = config["api"]
    search = config["search"]
    keywords = normalize_keywords(config.get("keywords", []))

    cutoff = None
    if search.get("period", 0) > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=search["period"])

    results = {}
    for label, query in build_queries(keywords):
        items = fetch_news(query, api["client_id"], api["client_secret"],
                           search["display"], search["sort"])
        if cutoff is not None:
            items = [it for it in items if within_period(it, cutoff)]
        results[label] = items
    return results


# ---------- 이메일 ----------
def build_email_html(results):
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [
        '<div style="font-family:Malgun Gothic,sans-serif;max-width:680px;margin:0 auto;">',
        f'<h2 style="color:#03c75a;">📰 네이버 뉴스 일일 리포트</h2>',
        f'<p style="color:#888;font-size:13px;">생성 시각: {today}</p>',
    ]
    for label, items in results.items():
        parts.append(f'<h3 style="background:#e8f9ee;color:#1a7a3c;padding:8px 12px;'
                     f'border-radius:6px;">🔍 {label} ({len(items)}건)</h3>')
        if not items:
            parts.append('<p style="color:#aaa;">검색 결과가 없습니다.</p>')
            continue
        for it in items:
            title = strip_tags(it.get("title", ""))
            desc = strip_tags(it.get("description", ""))
            date = it.get("pubDate", "")
            link = it.get("originallink") or it.get("link", "")
            parts.append(
                f'<div style="margin:12px 0;padding-bottom:10px;border-bottom:1px solid #eee;">'
                f'<a href="{link}" style="font-size:15px;font-weight:bold;color:#222;'
                f'text-decoration:none;">{title}</a>'
                f'<p style="color:#666;font-size:13px;margin:4px 0;">{desc}</p>'
                f'<span style="color:#aaa;font-size:11px;">{date}</span>'
                f'</div>'
            )
    parts.append('</div>')
    return "".join(parts)


def send_email(config, results):
    """검색 결과를 HTML 이메일로 발송. 실패 시 예외 발생."""
    email = config["email"]
    msg = MIMEText(build_email_html(results), "html", "utf-8")
    total = sum(len(v) for v in results.values())
    msg["Subject"] = f"[네이버 뉴스] {datetime.now().strftime('%Y-%m-%d')} 일일 리포트 ({total}건)"
    msg["From"] = email["sender"]
    msg["To"] = email["recipient"]

    with smtplib.SMTP(email["smtp_server"], int(email["smtp_port"]), timeout=20) as server:
        server.starttls()
        server.login(email["sender"], email["password"])
        server.send_message(msg)
