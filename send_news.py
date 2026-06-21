"""자동 발송 스크립트 (Windows 작업 스케줄러가 매일 실행).

설정(config.json)대로 뉴스를 검색해 이메일로 발송하고, 실행 로그를 남긴다.
"""
import sys
from datetime import datetime

import news_core

LOG_FILE = news_core.os.path.join(
    news_core.os.path.dirname(news_core.os.path.abspath(__file__)), "send_news.log")


def log(message):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    print(line)


def main():
    config = news_core.load_config()

    api = config["api"]
    email = config["email"]
    if not api["client_id"] or not api["client_secret"]:
        log("발송 중단: API 인증 정보가 없습니다.")
        return 1
    if not email["sender"] or not email["password"] or not email["recipient"]:
        log("발송 중단: 이메일 설정(보내는 주소/비밀번호/받는 주소)이 비어 있습니다.")
        return 1
    if not config.get("keywords"):
        log("발송 중단: 검색 키워드가 없습니다.")
        return 1

    try:
        results = news_core.run_search(config)
    except Exception as e:  # noqa: BLE001 - 자동 실행이라 모든 오류를 로그로 남김
        log(f"검색 실패: {e}")
        return 1

    total = sum(len(v) for v in results.values())
    try:
        news_core.send_email(config, results)
    except Exception as e:  # noqa: BLE001
        log(f"이메일 발송 실패: {e}")
        return 1

    log(f"발송 완료: {email['recipient']} 로 {total}건 전송")
    return 0


if __name__ == "__main__":
    sys.exit(main())
