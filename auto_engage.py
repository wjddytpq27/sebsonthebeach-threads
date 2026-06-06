"""
루카 — Playwright 키워드 검색 기반 자동 engagement
특정 계정 타겟 X → 카테고리 키워드 검색으로 다양한 사람들 포스트에 댓글
"""
import os, csv, random, time, sys, json, hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

_STATE_FILE = Path('/Users/uneedcomms/thread/session_state.json')
STORAGE_STATE = os.environ.get('THREADS_STORAGE_STATE', '')
if not STORAGE_STATE and _STATE_FILE.exists():
    STORAGE_STATE = _STATE_FILE.read_text()

_SLACK_FILE = Path('/Users/uneedcomms/thread/data/slack_config.json')
SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK', '')
if not SLACK_WEBHOOK and _SLACK_FILE.exists():
    try:
        SLACK_WEBHOOK = json.loads(_SLACK_FILE.read_text()).get('webhook_url', '')
    except Exception:
        pass

CLAUDE_BIN = '/opt/homebrew/bin/claude'

KST = timezone(timedelta(hours=9))
today = datetime.now(KST).strftime('%Y-%m-%d')
DAILY_LIMIT = 25

# 카테고리별 키워드 세트 — 매일 날짜 기반으로 다른 세트 사용
KEYWORD_SETS = [
    ["AI활용", "ChatGPT활용", "AI부업"],
    ["부업", "N잡", "월급외수입"],
    ["퍼스널브랜딩", "콘텐츠마케팅", "팔로워늘리기"],
    ["온라인창업", "1인기업", "프리랜서"],
    ["자사몰", "카페24", "쇼핑몰창업"],
    ["자동화", "노코드", "업무효율"],
    ["디지털마케팅", "SNS마케팅", "인스타마케팅"],
    ["재테크", "투자공부", "경제공부"],
    ["스타트업", "사이드프로젝트", "린스타트업"],
    ["이커머스", "온라인쇼핑몰", "셀러"],
]

# 날짜 기반으로 오늘 키워드 세트 선택 (7일 주기)
day_index = int(hashlib.md5(today.encode()).hexdigest(), 16) % len(KEYWORD_SETS)
today_keywords = KEYWORD_SETS[day_index]

log_file = Path('data/engage_log.csv')
debug_file = Path('data/engage_debug.txt')
log_file.parent.mkdir(exist_ok=True)

class Tee:
    def __init__(self, *files):
        self.files = files
    def write(self, obj):
        for f in self.files: f.write(obj); f.flush()
    def flush(self):
        for f in self.files: f.flush()

debug_f = open(debug_file, 'w', encoding='utf-8')
sys.stdout = Tee(sys.__stdout__, debug_f)

engaged_ids = set()
if log_file.exists():
    cutoff = (datetime.now(KST) - timedelta(days=60)).strftime('%Y-%m-%d')
    kept_rows = []
    with open(log_file, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if row.get('date', '') >= cutoff:
                kept_rows.append(row)
                engaged_ids.add(row.get('post_id', ''))
    # 60일 이상 된 항목 제거
    if kept_rows:
        with open(log_file, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=['date', 'post_id', 'keyword', 'preview', 'comment'],
                               extrasaction='ignore')
            w.writeheader()
            w.writerows(kept_rows)
    else:
        log_file.unlink(missing_ok=True)

def generate_comment(text, keyword=''):
    """포스트 본문을 실제로 읽고 claude CLI로 맥락에 맞는 댓글 생성. 구독 사용, API 키 불필요."""
    import subprocess

    prompt = f"""너는 @sebsonthebeach 계정 운영자야.
AI·자동화를 실제로 써본 실무자 포지션. 말투는 완전 반말 구어체.

아래 Threads 포스트에 댓글을 달아야 해.

포스트:
{text}

규칙:
1. 포스트 안의 특정 내용(문장, 주장, 숫자)을 직접 지칭하거나 인용할 것
2. 아래 중 하나만 선택:
   - 반박: 틀리거나 빠진 것 지적
   - 보완: 포스트에 없는 실용적 정보 1줄 추가
   - 경험: 포스트와 연결된 구체적 내 경험
   - 질문: 포스트의 특정 포인트에 대한 구체적 질문
3. 길이: 1~3줄
4. 어느 포스트에나 붙일 수 있는 범용 댓글 절대 금지
5. "좋은 글", "공감합니다", "맞아요", 내용 단순 반복 금지
6. 이모지 없거나 최대 1개

댓글 텍스트만 출력. 따옴표나 설명 없이."""

    try:
        result = subprocess.run(
            [CLAUDE_BIN, '-p', prompt, '--model', 'haiku'],
            capture_output=True, text=True, timeout=60
        )
        comment = result.stdout.strip().strip('"')
        if not comment:
            return None

        bot_patterns = ["좋은 글", "공감합니다", "맞아요", "저도요", "감사합니다", "잘 봤습니다"]
        if any(p in comment for p in bot_patterns):
            print(f"  ⚠️ 봇티 감지 → 스킵: {comment[:30]}")
            return None

        return comment
    except Exception as e:
        print(f"  ⚠️ 댓글 생성 실패: {e}")
        return None

engaged_today = []
errors = []

if not STORAGE_STATE:
    errors.append("THREADS_STORAGE_STATE 미설정")
    print("❌ THREADS_STORAGE_STATE 없음")
else:
    try:
        state_data = json.loads(STORAGE_STATE)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=['--no-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled']
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

            print(f"[{today}] 쿠키 로그인 시도...")
            page.goto('https://www.threads.com/', wait_until='networkidle', timeout=40000)
            page.wait_for_timeout(3000)

            if 'login' in page.url:
                errors.append("세션만료_쿠키재발급필요")
                print("⚠️ 세션 만료")
            else:
                print(f"✅ 로그인 성공 | 오늘 키워드: {today_keywords}")

                for keyword in today_keywords:
                    if len(engaged_today) >= DAILY_LIMIT: break
                    print(f"\n🔍 검색: '{keyword}'")
                    try:
                        page.goto(f'https://www.threads.com/search?q={keyword}&serp_type=default',
                                  timeout=30000, wait_until='load')
                        page.wait_for_timeout(3000)
                        page.evaluate("window.scrollBy(0, 400)")
                        page.wait_for_timeout(1500)

                        post_links = page.query_selector_all('a[href*="/post/"]')
                        # 포스트 적으면 스크롤 더 해서 로드
                        if len(post_links) < 8:
                            for _ in range(3):
                                page.evaluate("window.scrollBy(0, 600)")
                                page.wait_for_timeout(1000)
                            post_links = page.query_selector_all('a[href*="/post/"]')
                        print(f"  포스트 {len(post_links)}개 발견")

                        # 이미 댓글 단 post_id 기반 작성자 추출 (같은 스레드 방지)
                        seen_hrefs = set()
                        seen_authors = set()  # 이미 댓글 단 작성자 → 해당 작성자 포스트 전부 스킵
                        for link in post_links[:8]:
                            if len(engaged_today) >= DAILY_LIMIT: break
                            try:
                                href = link.get_attribute('href') or ''
                            except:
                                continue
                            if '/post/' not in href or href in seen_hrefs: continue
                            seen_hrefs.add(href)
                            post_id = href.split('/post/')[-1].split('/')[0].split('?')[0]
                            # href에서 작성자 추출 (/@username/post/...)
                            author = href.split('/post/')[0].lstrip('/@') if '/post/' in href else ''

                            if post_id in engaged_ids:
                                print(f"  ↩ 이미 댓글: {post_id} (@{author}) → 해당 작성자 스킵")
                                seen_authors.add(author)
                                continue

                            # 이미 댓글 단 작성자 포스트면 스킵 (같은 스레드 방지)
                            if author and author in seen_authors:
                                print(f"  ⏭ 같은 스레드 작성자 스킵: @{author}")
                                continue
                            try:
                                page.goto(f'https://www.threads.com{href}', timeout=15000)
                                page.wait_for_timeout(2500)
                                post_text = page.evaluate("""
                                    () => {
                                        // dir=auto 속성 가진 요소 중 가장 긴 텍스트
                                        const candidates = [...document.querySelectorAll('[dir="auto"]')];
                                        const texts = candidates
                                            .map(el => el.innerText?.trim() || '')
                                            .filter(t => t.length > 10 && t.length < 1000);
                                        if (texts.length) return texts.reduce((a,b) => a.length > b.length ? a : b);
                                        // fallback: article
                                        const art = document.querySelector('article');
                                        if (art) return art.innerText?.trim() || '';
                                        return '';
                                    }
                                """) or ''
                                print(f"    포스트 텍스트: {post_text[:60] if post_text else '❌ 못 읽음'}")

                                # 내 포스트면 스킵
                                if 'sebsonthebeach' in page.url:
                                    continue

                                # 좋아요 수 필터 (5개 미만: 노출 없는 글, 200개 초과: 댓글 묻힘)
                                likes_count = page.evaluate("""
                                    () => {
                                        const els = document.querySelectorAll('[aria-label]');
                                        for (const el of els) {
                                            const label = el.getAttribute('aria-label') || '';
                                            const m = label.match(/(\\d+)\\s*(like|좋아요)/i);
                                            if (m) return parseInt(m[1]);
                                        }
                                        return -1;
                                    }
                                """) or -1
                                if likes_count != -1 and (likes_count < 5 or likes_count > 200):
                                    print(f"  필터: 좋아요 {likes_count}개 → 스킵")
                                    continue

                                # 댓글 버튼 클릭 (aria-label='댓글' 또는 영어 fallback)
                                reply_btn = None
                                for aria in ['댓글', 'Reply', '답글', 'Comment']:
                                    loc = page.locator(f'[aria-label="{aria}"]').first
                                    try:
                                        loc.wait_for(timeout=2000)
                                        reply_btn = loc
                                        print(f"    댓글 버튼 발견: {aria}")
                                        break
                                    except Exception:
                                        continue

                                if reply_btn:
                                    try:
                                        reply_btn.click(force=True, timeout=5000)
                                    except Exception:
                                        # SVG가 막혀있으면 JS dispatchEvent로 우회
                                        page.evaluate("""
                                            () => {
                                                const el = document.querySelector('[aria-label="댓글"]');
                                                if (el) el.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
                                            }
                                        """)
                                    page.wait_for_timeout(2000)
                                else:
                                    print("    댓글 버튼 없음 — 스킵")
                                    continue

                                # 입력창 찾기
                                reply_box = None
                                for sel in [
                                    'div[contenteditable="true"]',
                                    'div[role="textbox"]',
                                    '[data-lexical-editor="true"]',
                                    'textarea',
                                ]:
                                    loc = page.locator(sel).first
                                    try:
                                        loc.wait_for(timeout=4000)
                                        reply_box = loc
                                        print(f"    입력창 발견: {sel}")
                                        break
                                    except Exception:
                                        continue

                                if not reply_box:
                                    print(f"  ❌ 댓글 입력창 없음 — 스킵: {post_id}")
                                    continue

                                reply_box.click(force=True)
                                page.wait_for_timeout(800)
                                comment = generate_comment(post_text, keyword)
                                if not comment:
                                    print(f"  ↩ 댓글 생성 실패 → 스킵: {post_id}")
                                    continue
                                page.keyboard.type(comment, delay=30)
                                page.wait_for_timeout(1200)

                                submitted = page.evaluate("""
                                    () => {
                                        const btns = [...document.querySelectorAll('div[role="button"], button')];
                                        const btn = btns.find(b => (b.innerText||'').trim()==='게시' || (b.innerText||'').trim()==='Post');
                                        if(btn){btn.click();return true;}
                                        return false;
                                    }
                                """)
                                if not submitted:
                                    page.keyboard.press('Enter')

                                page.wait_for_timeout(3000)
                                print(f"  ✅ [{keyword}] 댓글 완료: {post_id}")
                                engaged_today.append({
                                    'post_id': post_id, 'keyword': keyword,
                                    'preview': post_text[:50].replace('\n',' '),
                                    'comment': comment
                                })
                                engaged_ids.add(post_id)
                                time.sleep(random.uniform(15, 28))
                            except Exception as e:
                                print(f"  ❌ 포스트 실패: {e}")
                    except Exception as e:
                        print(f"  ❌ 검색 실패 [{keyword}]: {e}")

            browser.close()

    except Exception as e:
        print(f"❌ 오류: {e}")
        errors.append(str(e)[:80])

debug_f.close()
sys.stdout = sys.__stdout__

if engaged_today:
    is_new = not log_file.exists()
    with open(log_file, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['date','post_id','keyword','preview','comment'])
        if is_new: w.writeheader()
        for e in engaged_today: w.writerow({'date': today, **e})

import requests as req
if SLACK_WEBHOOK:
    out = [f"💬 *Threads 자동 댓글* ({today})", f"댓글 {len(engaged_today)}개 / 목표 {DAILY_LIMIT}개",
           f"오늘 키워드: {' · '.join(today_keywords)}", ""]
    for e in engaged_today:
        out.append(f"• [{e['keyword']}]")
        out.append(f"  └ 포스트: {e['preview'][:50]}")
        out.append(f"  └ 내 댓글: {e['comment']}")
    if errors: out.append(f"⚠️ {' / '.join(errors)}")
    with open(debug_file, 'r', encoding='utf-8') as f:
        out.append(f"```{f.read()[-1200:]}```")
    req.post(SLACK_WEBHOOK, json={"text": "\n".join(out)})

print(f"최종: {len(engaged_today)}개 댓글")
