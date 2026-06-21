"""카카오톡 '나에게 보내기' 최초 토큰 발급 도우미 (1회 실행).

사용 전 카카오 개발자 콘솔에서:
  1) 애플리케이션 생성 → '앱 키 > REST API 키' 복사
  2) [카카오 로그인] 활성화 ON
  3) [카카오 로그인 > Redirect URI]에 https://localhost 등록
  4) [카카오 로그인 > 동의항목]에서 '카카오톡 메시지 전송(talk_message)' 사용 설정

그 다음 이 스크립트를 실행하면 안내에 따라 refresh_token을 발급해 config.json에 저장합니다.
"""
import json
import urllib.parse
import urllib.request
import webbrowser

import news_core

REDIRECT_URI = "https://localhost"


def main():
    print("=== 카카오톡 '나에게 보내기' 설정 ===\n")
    rest_api_key = input("REST API 키를 입력하세요: ").strip()
    if not rest_api_key:
        print("REST API 키가 필요합니다.")
        return

    # 1) 인증 코드 받기 위한 동의 URL 열기
    auth_url = (
        "https://kauth.kakao.com/oauth/authorize?"
        + urllib.parse.urlencode({
            "client_id": rest_api_key,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": "talk_message",
        })
    )
    print("\n[1] 브라우저가 열리면 카카오 로그인 후 '동의'를 누르세요.")
    print("    동의 후 주소창이 https://localhost/?code=XXXXX 로 바뀝니다.")
    print(f"\n혹시 안 열리면 아래 주소를 직접 여세요:\n{auth_url}\n")
    try:
        webbrowser.open(auth_url)
    except Exception:  # noqa: BLE001
        pass

    code = input("[2] 주소창의 code= 뒤 값을 붙여넣으세요: ").strip()
    if not code:
        print("인증 코드가 필요합니다.")
        return

    # 2) 인증 코드 → 토큰 교환
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "client_id": rest_api_key,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }).encode("utf-8")
    req = urllib.request.Request("https://kauth.kakao.com/oauth/token", data=data)
    req.add_header("Content-Type", "application/x-www-form-urlencoded;charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            token = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print("토큰 발급 실패:", e.read().decode("utf-8", errors="replace"))
        return

    refresh_token = token.get("refresh_token")
    if not refresh_token:
        print("리프레시 토큰을 받지 못했습니다. 응답:", token)
        return

    # 3) config.json에 저장
    config = news_core.load_config()
    config["kakao"] = {
        "enabled": True,
        "rest_api_key": rest_api_key,
        "refresh_token": refresh_token,
    }
    news_core.save_config(config)
    print("\n✅ 설정 완료! 카카오톡 자동 발송이 켜졌습니다.")
    print("   이제 send_news.py 실행 시 카카오톡으로도 헤드라인이 전송됩니다.")


if __name__ == "__main__":
    main()
