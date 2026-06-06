"""
Threads 세션 갱신 — 브라우저 열어서 직접 로그인 후 쿠키 저장
Mac에서 직접 실행: python3 renew_session.py
"""
import json, time
from pathlib import Path
from playwright.sync_api import sync_playwright

STATE_FILE = Path('/Users/uneedcomms/thread/session_state.json')

def renew():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,  # 브라우저 직접 보이게
            args=['--no-sandbox']
        )
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 900},
            locale='ko-KR',
            timezone_id='Asia/Seoul',
        )
        page = ctx.new_page()
        page.goto('https://www.threads.com/login', wait_until='networkidle')

        print("🔐 브라우저 창에서 Threads 로그인하세요 (최대 2분 대기)...")

        # 로그인 완료되면 메인 피드로 리다이렉트됨
        try:
            page.wait_for_url(lambda url: 'login' not in url and 'threads.com' in url, timeout=120000)
            print(f"✅ 로그인 감지: {page.url}")
        except Exception:
            print(f"⏱️ 타임아웃 — 현재 URL: {page.url}")

        page.wait_for_timeout(2000)

        # Instagram 쿠키도 같이 수집 (Threads 인증은 Instagram 기반)
        page.goto('https://www.instagram.com/', wait_until='networkidle', timeout=20000)
        page.wait_for_timeout(2000)

        storage = ctx.storage_state()
        STATE_FILE.write_text(json.dumps(storage, ensure_ascii=False, indent=2))
        cookies = storage.get('cookies', [])
        domains = list({c['domain'] for c in cookies})
        print(f"✅ 세션 저장 완료: {STATE_FILE}")
        print(f"   쿠키 {len(cookies)}개 | 도메인: {domains}")

        browser.close()

if __name__ == '__main__':
    renew()
