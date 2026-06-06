"""
소나 — 세션 쿠키 추출기 (최초 1회만 실행)
실행: python setup_auth.py
브라우저 창이 뜨면 직접 로그인 → Enter 누르면 쿠키 JSON 출력
"""
import json
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        viewport={'width': 1280, 'height': 800},
        locale='ko-KR',
        timezone_id='Asia/Seoul',
    )
    page = ctx.new_page()
    page.goto('https://www.threads.com/login')

    print("\n" + "="*60)
    print("브라우저에서 Threads 로그인을 완료해주세요.")
    print("2FA 코드도 입력하고 메인 피드까지 완전히 들어간 뒤")
    print("여기서 Enter를 누르세요.")
    print("="*60 + "\n")
    input()

    # 로그인 상태 확인
    if 'login' in page.url:
        print("❌ 아직 로그인 안 된 것 같아요. 다시 로그인하고 Enter 누르세요.")
        input()

    state = ctx.storage_state()
    state_json = json.dumps(state)

    print("\n✅ 세션 저장 완료!")
    print(f"쿠키 개수: {len(state.get('cookies', []))}")
    print("\n" + "="*60)
    print("아래 JSON을 복사해서 GitHub Secret 'THREADS_STORAGE_STATE'에 저장하세요:")
    print("="*60)
    print(state_json)
    print("="*60)

    # 파일로도 저장 (백업용)
    with open('session_state.json', 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print("\n📄 session_state.json 파일로도 저장됨 (로컬 백업)")

    browser.close()
