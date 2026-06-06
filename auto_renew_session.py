"""
auto_renew_session.py — 헤드리스 세션 자동 갱신
기존 session_state.json 쿠키로 threads.com 방문 → 쿠키 연장
세션 만료 감지 시 Slack으로 수동 갱신 요청 알림
"""
import json, sys, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

STATE_FILE  = Path('/Users/uneedcomms/thread/session_state.json')
SLACK_FILE  = Path('/Users/uneedcomms/thread/data/slack_config.json')
KST         = timezone(timedelta(hours=9))
RENEW_DAYS  = 14  # 만료 14일 이내 쿠키 있으면 갱신 실행


def send_slack(msg: str):
    if not SLACK_FILE.exists():
        return
    webhook = json.loads(SLACK_FILE.read_text()).get('webhook_url', '')
    if not webhook:
        return
    data = json.dumps({'text': msg}).encode()
    req = urllib.request.Request(webhook, data=data, headers={'Content-Type': 'application/json'})
    urllib.request.urlopen(req, timeout=10)


def check_expiry(state: dict) -> tuple[bool, str]:
    """만료 임박 쿠키 확인. (갱신 필요 여부, 가장 빠른 만료일)"""
    cookies = state.get('cookies', [])
    cutoff = (datetime.now(KST) + timedelta(days=RENEW_DAYS)).timestamp()
    earliest = None
    for c in cookies:
        exp = c.get('expires', -1)
        if 0 < exp < cutoff:
            if earliest is None or exp < earliest:
                earliest = exp
    if earliest:
        exp_str = datetime.fromtimestamp(earliest, tz=KST).strftime('%Y-%m-%d')
        return True, exp_str
    return False, ''


def try_headless_renew(state: dict) -> tuple[bool, dict]:
    """기존 쿠키로 headless 방문 → 쿠키 갱신 시도. (성공 여부, 새 state)"""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage'],
        )
        ctx = browser.new_context(
            storage_state=state,
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 900},
            locale='ko-KR',
            timezone_id='Asia/Seoul',
        )
        page = ctx.new_page()

        try:
            page.goto('https://www.threads.com/', wait_until='networkidle', timeout=30000)
        except Exception as e:
            print(f'  ⚠️ threads.com 접속 실패: {e}')
            browser.close()
            return False, state

        final_url = page.url
        print(f'  최종 URL: {final_url}')

        # 로그인 페이지로 리다이렉트됐으면 세션 만료
        if 'login' in final_url or 'accounts' in final_url:
            browser.close()
            return False, state

        page.wait_for_timeout(2000)
        new_state = ctx.storage_state()
        browser.close()
        return True, new_state


if __name__ == '__main__':
    today = datetime.now(KST).strftime('%Y-%m-%d')
    print(f'[{today}] auto_renew_session.py 시작')

    if not STATE_FILE.exists():
        msg = f'⚠️ [{today}] session_state.json 없음 — `python3 renew_session.py` 실행 필요'
        print(msg)
        send_slack(msg)
        sys.exit(1)

    state = json.loads(STATE_FILE.read_text())
    needs_renew, earliest_exp = check_expiry(state)

    if not needs_renew:
        print(f'  쿠키 만료 {RENEW_DAYS}일 이내 없음 — 갱신 불필요')
        sys.exit(0)

    print(f'  만료 임박 쿠키 발견 (최초 만료: {earliest_exp}) — headless 갱신 시도')
    success, new_state = try_headless_renew(state)

    if success:
        STATE_FILE.write_text(json.dumps(new_state, ensure_ascii=False, indent=2))
        new_cookies = new_state.get('cookies', [])
        print(f'  ✅ 갱신 완료: 쿠키 {len(new_cookies)}개 저장')
        send_slack(f'✅ [{today}] Threads 세션 자동 갱신 완료')
    else:
        msg = (
            f'🔴 [{today}] Threads 세션 만료 — 수동 갱신 필요\n'
            f'Mac에서 실행: `python3 /Users/uneedcomms/thread/renew_session.py`'
        )
        print(f'  ❌ headless 갱신 실패 — 세션 만료')
        send_slack(msg)
        sys.exit(1)
