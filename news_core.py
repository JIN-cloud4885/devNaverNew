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
from email.utils import formatdate, make_msgid, parsedate_to_datetime

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
        "include_content": False,
    },
    "schedule": {"time": "09:00", "enabled": False},
    "ai": {"api_key": "", "enabled": False, "model": "claude-opus-4-8"},
    "summary": {"enabled": False},
    "kakao": {"enabled": False, "rest_api_key": "", "refresh_token": ""},
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
    text = re.sub(r"(?s)<.*?>", "", text)
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


def fetch_article_content(url, max_chars=2000):
    """기사 URL에서 본문 텍스트를 추출. 실패 시 빈 문자열 반환.

    외부 라이브러리 없이 처리한다. 네이버 뉴스(n.news.naver.com)는 본문 영역의
    id가 고정돼 있어 우선 시도하고, 그 외 언론사는 <p> 태그를 모아 추정한다.
    """
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            html = resp.read().decode(charset, errors="replace")
    except (urllib.error.URLError, OSError, ValueError):
        return ""

    # <script>/<style> 제거
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)

    # 1) 네이버 뉴스 본문 영역 우선 추출
    body_html = ""
    m = re.search(r'(?is)<article[^>]*id="dic_area".*?</article>', html)
    if not m:
        m = re.search(r'(?is)<div[^>]*id="dic_area".*?</div>', html)
    if not m:
        m = re.search(r'(?is)<div[^>]*id="newsct_article".*?</div>', html)
    if m:
        body_html = m.group(0)
    else:
        # 2) 일반 언론사: 가장 긴 <article> 또는 <p> 모음
        article = re.search(r"(?is)<article.*?</article>", html)
        if article:
            body_html = article.group(0)
        else:
            paragraphs = re.findall(r"(?is)<p[^>]*>(.*?)</p>", html)
            body_html = " ".join(p for p in paragraphs if len(strip_tags(p)) > 20)

    text = strip_tags(re.sub(r"(?is)<br\s*/?>", "\n", body_html))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + " …"
    return text


def summarize_article(client, model, title, content):
    """기사 본문을 2줄 이내로 요약. 실패 시 빈 문자열 반환."""
    if not content:
        return ""
    prompt = (
        "다음 뉴스 기사를 한국어로 2줄 이내(약 100자)로 핵심만 요약해줘. "
        "군더더기 없이 사실만, 문장 끝맺음으로.\n\n"
        f"제목: {title}\n본문: {content[:4000]}"
    )
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception:  # noqa: BLE001 - 요약 실패 시 원문 요약으로 대체
        return ""


# 기사 페이지의 공유 버튼·UI 잡텍스트
_NOISE_TOKENS = [
    "페이스북", "트위터", "카카오톡", "카카오스토리", "네이버밴드", "밴드",
    "URL복사", "URL 복사", "글자크기", "글자 크기", "본문 글씨 크기 조정",
    "기사저장", "스크랩", "인쇄", "공유하기", "댓글", "좋아요",
    "기자페이지", "구독", "close", "레이어 닫기", "전체메뉴",
    "기사 읽어주기", "읽어주기", "다시듣기", "글씨 크기 조절", "글씨크기",
    "닫기 시 다른 기사의 본문도 동일하게 적용 됩니다", "닫기",
    "로그인", "회원가입", "제보", "무단복제", "재배포 금지",
]


def clean_noise(text):
    """기사 본문에서 공유 버튼/글자크기 등 UI 잡텍스트를 제거."""
    if not text:
        return ""
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"<!--.*?-->", " ", text)               # HTML 주석
    text = text.replace("-->", " ").replace("<!--", " ")  # 잘린 주석 잔여물
    text = re.sub(r"입력\s*\d{4}[-.]\d{2}[-.]\d{2}[^가-힣]*", " ", text)  # 입력 2026-..
    text = re.sub(r"수정\s*\d{4}[-.]\d{2}[-.]\d{2}[^가-힣]*", " ", text)  # 수정 2026-..
    text = re.sub(r"X\s*\(?\s*트위터\s*\)?", " ", text)   # X(트위터) 공유 버튼
    for tok in _NOISE_TOKENS + ["설정", "X ( )"]:
        text = text.replace(tok, " ")
    text = re.sub(r"[가-힣]{2,4}\s*기자", " ", text)       # 'OOO 기자' 바이라인
    text = re.sub(r"\b가\b", " ", text)                    # 글자크기 '가 가 가'
    text = re.sub(r"[\w.+-]+@[\w.-]+", " ", text)          # 이메일 주소
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extractive_summary(content, max_chars=130):
    """기사 본문에서 앞부분 핵심 문장 1~2개를 뽑아 2줄 요약(무료, API 불필요)."""
    if not content:
        return ""
    text = clean_noise(content).replace("\n", " ")
    # 사진 캡션/저작권/기자표기 등 군더더기 제거
    text = re.sub(r"\[[^\]]*\]", " ", text)                 # [울산 동구 제공 ...]
    text = re.sub(r"※[^.]*", " ", text)                     # ※ 안내문
    text = re.sub(r"재판매[^.]*금지", " ", text)
    text = re.sub(r"무단[ ]?전재[^.]*금지", " ", text)
    text = re.sub(r"\(([^)]*=)?[^)]*\)\s*[가-힣]{2,4}\s*기자\s*=\s*", " ", text)  # (울산=연합뉴스) 장지현 기자 =
    text = re.sub(r"[가-힣]{2,4}\s*기자\s*=\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # 문장 단위로 분리 (마침표/물음표/느낌표 + 공백, 또는 '다.' 종결)
    sentences = re.split(r'(?<=[.!?])\s+|(?<=다\.)\s*', text)
    summary = ""
    for s in sentences:
        s = s.strip()
        if len(s) < 10:
            continue
        if not summary:
            summary = s
        elif len(summary) + len(s) <= max_chars:
            summary += " " + s
        else:
            break
    if len(summary) > max_chars:
        summary = summary[:max_chars].rstrip() + " …"

    # 품질 검증: 너무 짧거나 잡텍스트 잔여물이 있으면 실패 처리(원문 요약으로 대체)
    if len(summary) < 25:
        return ""
    junk = ("로그인", "회원가입", "글씨", "조절", "다시듣기", "-->", "기사 읽어주기")
    if any(j in summary for j in junk):
        return ""
    if "다." not in summary and not summary.endswith(("…", ".", "?", "!")):
        return ""
    return summary


def apply_ai_summaries(config, results):
    """ai.enabled면 Claude로, summary.enabled면 무료 추출 요약으로 각 기사 'ai_summary'를 채운다."""
    ai = config.get("ai", {})
    summary_cfg = config.get("summary", {})

    if ai.get("enabled") and ai.get("api_key"):
        import anthropic
        client = anthropic.Anthropic(api_key=ai["api_key"])
        model = ai.get("model") or "claude-opus-4-8"
        for items in results.values():
            for it in items:
                link = it.get("originallink") or it.get("link", "")
                content = fetch_article_content(link)
                s = summarize_article(client, model, strip_tags(it.get("title", "")), content)
                if s:
                    it["ai_summary"] = s
    elif summary_cfg.get("enabled"):
        for items in results.values():
            for it in items:
                # 네이버 본문(dic_area)이 구조가 일정해 우선 사용
                naver = it.get("link", "")
                link = naver if "naver." in naver else (it.get("originallink") or naver)
                content = fetch_article_content(link)
                s = extractive_summary(content)
                if s:
                    it["ai_summary"] = s
    return results


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
    apply_ai_summaries(config, results)
    return results


# ---------- 이메일 ----------
def format_pubdate(pub):
    """RFC822 형식(pubDate)을 'YYYY-MM-DD HH:MM'로 변환. 실패 시 원본 반환."""
    try:
        return parsedate_to_datetime(pub).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return pub


def source_from_url(url):
    """기사 URL에서 출처(도메인)를 추출. 예: https://www.yna.co.kr/... -> yna.co.kr"""
    try:
        netloc = urllib.parse.urlparse(url).netloc
        return netloc[4:] if netloc.startswith("www.") else netloc
    except ValueError:
        return ""


def build_email_html(results, include_content=False):
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
        for idx, it in enumerate(items, 1):
            title = strip_tags(it.get("title", ""))
            ai_summary = it.get("ai_summary", "")
            if ai_summary:  # AI 요약이 있으면 2줄 그대로 사용
                desc = ai_summary
            else:
                desc = strip_tags(it.get("description", ""))
                if len(desc) > 60:  # 요약 없으면 1줄(약 60자)로 제한
                    desc = desc[:60].rstrip() + " …"
            link = it.get("originallink") or it.get("link", "")
            source = source_from_url(link) or "출처 미상"
            date = format_pubdate(it.get("pubDate", ""))
            content_html = ""
            if include_content:
                content = fetch_article_content(link)
                if content:
                    safe = content.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
                    content_html = (f'<div style="color:#444;font-size:12px;margin-top:8px;'
                                    f'padding:8px;background:#f8f9fa;border-radius:4px;'
                                    f'line-height:1.6;">{safe}</div>')
            parts.append(
                f'<div style="margin:14px 0;padding-bottom:12px;border-bottom:1px solid #eee;">'
                f'<a href="{link}" style="font-size:15px;font-weight:bold;color:#1a1a1a;'
                f'text-decoration:none;line-height:1.4;">{idx}. {title}</a>'
                f'<div style="margin:6px 0;font-size:12px;color:#888;">'
                f'<span style="color:#03c75a;font-weight:bold;">{source}</span>'
                f'&nbsp;·&nbsp;{date}</div>'
                f'<p style="color:#555;font-size:13px;margin:4px 0 0;line-height:1.6;'
                f'{"" if ai_summary else "white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"}">{desc}</p>'
                f'{content_html}'
                f'</div>'
            )
    parts.append('</div>')
    return "".join(parts)


def send_email(config, results):
    """검색 결과를 HTML 이메일로 발송. 실패 시 예외 발생."""
    email = config["email"]
    msg = MIMEText(build_email_html(results, email.get("include_content", False)),
                   "html", "utf-8")
    total = sum(len(v) for v in results.values())
    # 제목·헤더를 매번 고유하게 만들어 메일 서버의 '중복 메일' 폐기를 방지
    now = datetime.now()
    msg["Subject"] = f"[네이버 뉴스] {now.strftime('%Y-%m-%d %H:%M')} 일일 리포트 ({total}건)"
    msg["From"] = email["sender"]
    msg["To"] = email["recipient"]
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()

    with smtplib.SMTP(email["smtp_server"], int(email["smtp_port"]), timeout=20) as server:
        server.starttls()
        server.login(email["sender"], email["password"])
        server.send_message(msg)


# ---------- 카카오톡 '나에게 보내기' ----------
def kakao_refresh_access_token(rest_api_key, refresh_token):
    """리프레시 토큰으로 새 액세스 토큰 발급. (access_token, new_refresh_token|None) 반환."""
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": rest_api_key,
        "refresh_token": refresh_token,
    }).encode("utf-8")
    req = urllib.request.Request("https://kauth.kakao.com/oauth/token", data=data)
    req.add_header("Content-Type", "application/x-www-form-urlencoded;charset=utf-8")
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return result["access_token"], result.get("refresh_token")


def build_kakao_text(results, max_items=8):
    """검색 결과를 카카오 텍스트(200자 제한)로 요약. 헤드라인 목록 반환."""
    total = sum(len(v) for v in results.values())
    today = datetime.now().strftime("%m/%d %H:%M")
    lines = [f"📰 네이버 뉴스 {today} ({total}건)", ""]
    n = 0
    for items in results.values():
        for it in items:
            n += 1
            if n > max_items:
                break
            title = strip_tags(it.get("title", ""))
            lines.append(f"{n}. {title}")
        if n > max_items:
            break
    text = "\n".join(lines)
    if len(text) > 195:
        text = text[:195].rstrip() + "…"
    return text


def send_kakao_memo(config, results):
    """검색 결과 헤드라인을 카카오톡 '나에게 보내기'로 발송. 실패 시 예외 발생."""
    kakao = config["kakao"]
    access_token, new_refresh = kakao_refresh_access_token(
        kakao["rest_api_key"], kakao["refresh_token"])
    if new_refresh:  # 리프레시 토큰이 갱신되면 저장
        kakao["refresh_token"] = new_refresh
        save_config(config)

    # 헤드라인을 리스트형으로 구성 (각 항목 클릭 시 해당 기사 원문으로 이동)
    flat = []
    for items in results.values():
        flat.extend(items)
    flat = flat[:5]  # 리스트형은 최대 5건

    def naver_news_search(title):
        # 카카오는 등록된 도메인 링크만 열어주므로, 제목으로 네이버 뉴스 검색 링크 생성
        q = urllib.parse.urlencode({"where": "news", "query": title, "sort": "1"})
        url = "https://search.naver.com/search.naver?" + q
        return {"web_url": url, "mobile_web_url": url}

    contents = []
    for it in flat:
        title = strip_tags(it.get("title", ""))
        src = source_from_url(it.get("originallink") or it.get("link", ""))
        contents.append({
            "title": title[:40],
            "description": f"{src} · {format_pubdate(it.get('pubDate', ''))}",
            "link": naver_news_search(title),
        })

    total = sum(len(v) for v in results.values())
    today = datetime.now().strftime("%m/%d %H:%M")
    head_link = naver_news_search("평택") if not contents else contents[0]["link"]
    template = {
        "object_type": "list",
        "header_title": f"📰 네이버 뉴스 {today} ({total}건)",
        "header_link": head_link,
        "contents": contents,
    }
    data = urllib.parse.urlencode({
        "template_object": json.dumps(template, ensure_ascii=False)
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send", data=data)
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded;charset=utf-8")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))
