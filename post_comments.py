"""
PHASE 3: Threads 댓글 게시기
- /Users/uneedcomms/thread/data/ready_comments.json 읽기
- 각 포스트에 Claude가 생성한 댓글 게시
- 결과를 engage_log.csv에 기록
"""
import json, csv, time, random, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
today = datetime.now(KST).strftime('%Y-%m-%d')

data_dir = Path('/Users/uneedcomms/thread/data')
ready_file = data_dir / 'ready_comments.json'
log_file = data_dir / 'engage_log.csv'
session_file = Path('/Users/uneedcomms/thread/session_state.json')

if not ready_file.exists():
    print("❌ ready_comments.json 없음. Claude 에이전트 단계가 완료되지 않았습니다.")
    sys.exit(1)

with open(ready_file, encoding='utf-8') as f:
    data = json.load(f)

comments = data.get('comments', [])
if not comments:
    print("❌ 댓글 목록이 비어 있음.")
    sys.exit(0)

print(f"[{today}] 댓글 게시 시작 | 총 {len(comments)}개")

if not session_file.exists():
    print("❌ session_state.json 없음. setup_auth.py 먼저 실행하세요.")
    sys.exit(1)

with open(session_file, encoding='utf-8') as f:
    state_data = json.load(f)

posted = []
failed = []

try:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-blink-features=AutomationControlled']
        )
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 800},
            locale='ko-KR',
            timezone_id='Asia/Seoul',
            storage_state=state_data,
        )
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            window.chrome = {runtime: {}};
        """)
        page = ctx.new_page()

        print("쿠키 로그인 시도...")
        page.goto('https://www.threads.com/', wait_until='networkidle', timeout=40000)
        page.wait_for_timeout(3000)

        if 'login' in page.url:
            print("❌ 세션 만료. session_state.json 갱신 필요.")
            browser.close()
            sys.exit(1)

        print("✅ 로그인 성공\n")

        for item in comments:
            post_id = item.get('post_id', '')
            author = item.get('author', '')
            url = item.get('url', '')
            comment = item.get('comment', '')
            keyword = item.get('keyword', '')
            post_preview = item.get('text', '')[:60]

            if not url or not comment:
                print(f"  ⏭ 데이터 누락 스킵: {post_id}")
                continue

            print(f"💬 @{author} | {post_preview}...")
            print(f"   댓글: {comment}")

            try:
                page.goto(url, timeout=15000)
                page.wait_for_timeout(2500)

                # 내 포스트면 스킵
                if 'sebsonthebeach' in page.url:
                    print(f"  ⏭ 내 포스트 스킵")
                    continue

                # 댓글 입력창 찾기
                reply_box = page.locator('div[contenteditable="true"], div[role="textbox"]').first
                reply_box.wait_for(timeout=10000)
                reply_box.click()
                page.wait_for_timeout(800)

                # 댓글 타이핑
                reply_box.type(comment, delay=25)
                page.wait_for_timeout(1200)

                # 게시 버튼 클릭
                submitted = page.evaluate("""
                    () => {
                        const btns = [...document.querySelectorAll('div[role="button"], button')];
                        const btn = btns.find(b => {
                            const t = (b.innerText||'').trim();
                            return t === '게시' || t === 'Post';
                        });
                        if (btn) { btn.click(); return true; }
                        return false;
                    }
                """)

                if not submitted:
                    page.keyboard.press('Enter')

                page.wait_for_timeout(3000)
                print(f"  ✅ 게시 완료!\n")

                posted.append({
                    'date': today,
                    'post_id': post_id,
                    'author': author,
                    'keyword': keyword,
                    'preview': post_preview,
                    'comment': comment,
                })

                # 댓글 간격: 15~30초 랜덤 (봇 탐지 방지)
                wait = random.uniform(15, 30)
                print(f"  ⏳ {wait:.0f}초 대기...")
                time.sleep(wait)

            except Exception as e:
                print(f"  ❌ 게시 실패: {e}")
                failed.append({'post_id': post_id, 'error': str(e)[:80]})

        browser.close()

except Exception as e:
    print(f"❌ Playwright 오류: {e}")

# engage_log.csv에 기록
if posted:
    is_new = not log_file.exists()
    with open(log_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['date', 'post_id', 'author', 'keyword', 'preview', 'comment'])
        if is_new:
            writer.writeheader()
        writer.writerows(posted)

# ready_comments.json에 결과 기록
data['posted'] = posted
data['failed'] = failed
data['status'] = 'done'
with open(ready_file, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"\n최종: 성공 {len(posted)}개 / 실패 {len(failed)}개")

# 결과를 stdout으로 출력 (Cowork 에이전트가 읽음)
print(f"RESULT_JSON:{json.dumps({'posted': len(posted), 'failed': len(failed), 'details': posted}, ensure_ascii=False)}")
