"""
hunter-engager — Playwright 키워드 검색 기반 자동 engagement
team_signal.json의 directives.hunter_engager 지시를 따름.
Slack 발송 없음 — 결과는 cron.log에 print만.
"""
import os, csv, random, time, sys, json, hashlib, re
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Set, Dict
from pathlib import Path

from engage_post import is_valid_comment, type_comment_safely

# ── 경로 설정 ──────────────────────────────────────────
BASE = Path('/Users/uneedcomms/thread')
_STATE_FILE  = BASE / 'session_state.json'
_SIGNAL_FILE = BASE / 'data/team_signal.json'
LOG_FILE     = BASE / 'data/engage_log.csv'
DEBUG_FILE   = BASE / 'data/engage_debug.txt'

CLAUDE_BIN   = '/opt/homebrew/bin/claude'
KST          = timezone(timedelta(hours=9))
today        = datetime.now(KST).strftime('%Y-%m-%d')

# ── 세션 로드 ──────────────────────────────────────────
STORAGE_STATE = os.environ.get('THREADS_STORAGE_STATE', '')
if not STORAGE_STATE and _STATE_FILE.exists():
    STORAGE_STATE = _STATE_FILE.read_text()

# ── team_signal.json 읽기 ──────────────────────────────
signal = {}
if _SIGNAL_FILE.exists():
    try:
        signal = json.loads(_SIGNAL_FILE.read_text())
    except Exception:
        pass

status = signal.get('status', 'normal')

# 상태별 목표 수 결정
DAILY_LIMIT = {'normal': 25, 'stall': 35, 'emergency': 40}.get(status, 25)
# 영어 비중
english_ratio = {'normal': 0.20, 'stall': 0.40, 'emergency': 0.50}.get(status, 0.20)
# directive 텍스트가 status 기본값보다 우선 — 매일 directive 자동 반영
_directive = signal.get('directives', {}).get('hunter_engager', '') or ''
_m_goal = re.search(r'목표\s*(\d+)\s*개', _directive)
if _m_goal:
    DAILY_LIMIT = int(_m_goal.group(1))
_m_eng = re.search(r'영어[^0-9]*(\d+)\s*%', _directive)
if _m_eng:
    english_ratio = int(_m_eng.group(1)) / 100.0
ENGLISH_LIMIT = max(1, round(DAILY_LIMIT * english_ratio))
KOREAN_LIMIT  = DAILY_LIMIT - ENGLISH_LIMIT

# ── 키워드 결정 (top_search_keywords 우선, 기본 키워드 보완) ──
top_keywords = signal.get('top_search_keywords', [])

# team_signal directive에서 추출한 오늘 한국어 키워드 순서
# normal: 퍼스널브랜딩 → 디지털마케팅 → 온라인창업
# (directives 텍스트 파싱보다 top_search_keywords 활용)
DEFAULT_KO_KEYWORDS = [
    "퍼스널브랜딩", "디지털마케팅", "온라인창업",
    "부업", "N잡", "이커머스", "자동화", "노코드",
    "스타트업", "1인기업", "프리랜서", "콘텐츠마케팅",
]

# top_keywords 먼저, 나머지로 보완
ko_keywords = list(dict.fromkeys(top_keywords + DEFAULT_KO_KEYWORDS))

# emergency: 팔로워 1만+ 계정만 → 영어 대형 계정 타겟
if status == 'emergency':
    en_keywords = [
        "AI tools automation", "SaaS growth", "marketing automation",
        "startup growth", "solopreneur AI", "content marketing AI",
    ]
else:
    en_keywords = [
        "AI tools automation", "marketing automation",
        "solopreneur growth", "SaaS founder", "content creator tips",
    ]

print(f"[{today}] 상태: {status} | 목표: {DAILY_LIMIT}개 (한국어 {KOREAN_LIMIT} / 영어 {ENGLISH_LIMIT})")
print(f"한국어 키워드: {ko_keywords[:5]}")
print(f"영어 키워드: {en_keywords}")

# ── Pre-flight: Claude CLI 인증 확인 ─────────────────────
def _send_slack_alert(msg: str):
    import urllib.request
    try:
        webhook = json.loads((_SIGNAL_FILE.parent / 'slack_config.json').read_text()).get('webhook_url', '')
    except Exception:
        webhook = os.environ.get('SLACK_WEBHOOK', '')
    if not webhook:
        return
    data = json.dumps({'text': msg}).encode()
    try:
        urllib.request.urlopen(
            urllib.request.Request(webhook, data=data, headers={'Content-Type': 'application/json'}),
            timeout=10,
        )
    except Exception:
        pass

import subprocess as _sp, re as _re
_AUTH_ERRORS = ['not logged in', 'please run', '/login', 'authentication', 'unauthorized', 'session expired']
_agent_env = BASE / 'data' / '.agent_env'
_agent_token = ''
if _agent_env.exists():
    for _line in _agent_env.read_text().splitlines():
        _m = _re.match(r"""export\s+CLAUDE_CODE_OAUTH_TOKEN=['"]?([^'"]+)['"]?""", _line.strip())
        if _m:
            _agent_token = _m.group(1).strip()
            break
_cli_env = {**os.environ, 'CLAUDE_CODE_OAUTH_TOKEN': _agent_token} if _agent_token else os.environ.copy()
_cli_test = _sp.run([CLAUDE_BIN, '-p', 'reply with: OK', '--model', 'haiku'], capture_output=True, text=True, timeout=30, env=_cli_env)
_cli_out = (_cli_test.stdout + _cli_test.stderr).lower()
if _cli_test.returncode != 0 or any(_p in _cli_out for _p in _AUTH_ERRORS) or 'ok' not in _cli_test.stdout.lower():
    msg = f"🔴 [auto_engage {today}] Claude CLI 인증 만료 — 댓글 전량 스킵.\n복구: `! claude /login` 실행 필요"
    print(msg)
    _send_slack_alert(msg)
    sys.exit(1)
print("✅ Claude CLI 인증 확인됨")

# ── Tee: stdout → 파일 동시 출력 ──────────────────────
LOG_FILE.parent.mkdir(exist_ok=True)
debug_f = open(DEBUG_FILE, 'w', encoding='utf-8')

class Tee:
    def __init__(self, *files):
        self.files = files
    def write(self, obj):
        for f in self.files:
            f.write(obj)
            f.flush()
    def flush(self):
        for f in self.files:
            f.flush()

sys.stdout = Tee(sys.__stdout__, debug_f)

# ── engage_log 로드 (중복 방지, 60일 이상 정리) ──────────
engaged_ids = set()
if LOG_FILE.exists():
    cutoff = (datetime.now(KST) - timedelta(days=60)).strftime('%Y-%m-%d')
    kept_rows = []
    with open(LOG_FILE, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if row.get('date', '') >= cutoff:
                kept_rows.append(row)
                engaged_ids.add(row.get('post_id', ''))
    if kept_rows:
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(
                f,
                fieldnames=['date', 'post_id', 'keyword', 'preview', 'comment'],
                extrasaction='ignore',
            )
            w.writeheader()
            w.writerows(kept_rows)
    else:
        LOG_FILE.unlink(missing_ok=True)


def generate_comment(text: str, keyword: str = '', lang: str = 'ko') -> Optional[str]:
    import subprocess

    if lang == 'en':
        prompt = f"""You are the operator of @sebsonthebeach.
Position: practitioner who has actually used AI and automation in real work.
Tone: casual, direct (English).

Write a reply to this Threads post:

Post:
{text}

Rules:
1. Directly reference a specific sentence, claim, or number from the post
2. Choose exactly one of: pushback, add practical info, share concrete experience, ask a specific question
3. Length: 1-3 lines
4. No generic replies that could fit any post
5. No "great post", "I agree", "so true"
6. Zero or one emoji max

Output the comment text only. No quotes or explanation."""
    else:
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
7. "우리" 금지, "나/내가" 사용. 팀/에이전트/봇 단어 절대 금지

댓글 텍스트만 출력. 따옴표나 설명 없이."""

    try:
        result = subprocess.run(
            [CLAUDE_BIN, '-p', prompt, '--model', 'haiku'],
            capture_output=True, text=True, timeout=60, env=_cli_env
        )
        comment = result.stdout.strip().strip('"')
        if not comment:
            return None

        # 메타/되묻기/에러/봇티 텍스트 차단 (공용 가드)
        ok, reason = is_valid_comment(comment)
        if not ok:
            print(f"  ❌ 게시 부적합 → 스킵: {reason} | {comment[:50]}")
            return None

        return comment
    except Exception as e:
        print(f"  ⚠️ 댓글 생성 실패: {e}")
        return None


# ── 포스트 하나에 댓글 달기 (공통 로직) ──────────────────
def engage_post(page, href: str, keyword: str, seen_authors: set, lang: str = 'ko') -> Optional[Dict]:
    """
    주어진 href의 포스트를 방문하고 댓글을 달아 결과 dict 반환.
    스킵 시 None 반환.
    """
    post_id = href.split('/post/')[-1].split('/')[0].split('?')[0]
    author  = href.split('/post/')[0].lstrip('/@') if '/post/' in href else ''

    # 본인 계정 포스트 절대 금지
    if 'sebsonthebeach' in href.lower():
        print(f"  🚫 본인 포스트 스킵: {href[:60]}")
        return None

    if post_id in engaged_ids:
        print(f"  ↩ 이미 댓글: {post_id} (@{author}) → 해당 작성자 스킵")
        seen_authors.add(author)
        return None

    if author and author in seen_authors:
        print(f"  ⏭ 같은 스레드 작성자 스킵: @{author}")
        return None

    try:
        page.goto(f'https://www.threads.com{href}', timeout=15000)
        page.wait_for_timeout(2500)

        # 내 계정 포스트 스킵
        if 'sebsonthebeach' in page.url:
            return None

        post_text = page.evaluate("""
            () => {
                const candidates = [...document.querySelectorAll('[dir="auto"]')];
                const texts = candidates
                    .map(el => el.innerText?.trim() || '')
                    .filter(t => t.length > 10 && t.length < 1000);
                if (texts.length) return texts.reduce((a, b) => a.length > b.length ? a : b);
                const art = document.querySelector('article');
                if (art) return art.innerText?.trim() || '';
                return '';
            }
        """) or ''
        print(f"    포스트 텍스트: {post_text[:60] if post_text else '❌ 못 읽음'}")

        if not post_text:
            return None

        # 좋아요 수 필터: emergency 상태면 팔로워 1만+ 계정 판별 추가 가능
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

        like_max = 500 if status == 'emergency' else 200
        if likes_count != -1 and (likes_count < 5 or likes_count > like_max):
            print(f"  필터: 좋아요 {likes_count}개 → 스킵")
            return None

        # 댓글 버튼 클릭
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

        if not reply_btn:
            print("    댓글 버튼 없음 — 스킵")
            return None

        try:
            reply_btn.click(force=True, timeout=5000)
        except Exception:
            page.evaluate("""
                () => {
                    const el = document.querySelector('[aria-label="댓글"]');
                    if (el) el.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
                }
            """)
        page.wait_for_timeout(2000)

        # 입력창
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
            return None

        # 댓글을 먼저 생성한다 (생성 subprocess가 수 초 걸려 포커스가 식는 것 방지)
        comment = generate_comment(post_text, keyword, lang=lang)
        if not comment:
            print(f"  ↩ 댓글 생성 실패 → 스킵: {post_id}")
            return None

        # 포커스 보장 + 타이핑 검증 (앞글자 씹힘 시 자동 재입력)
        if not type_comment_safely(page, reply_box, comment):
            print(f"  ❌ 타이핑 검증 실패 → 게시 안 함: {post_id}")
            return None

        # 게시 직전 최종 가드 (생성 단계에서 못 거른 경우 대비)
        ok, reason = is_valid_comment(comment)
        if not ok:
            print(f"  ❌ 게시 직전 부적합 → 스킵: {reason}")
            return None

        submitted = page.evaluate("""
            () => {
                const btns = [...document.querySelectorAll('div[role="button"], button')];
                const btn = btns.find(b =>
                    (b.innerText||'').trim() === '게시' ||
                    (b.innerText||'').trim() === 'Post'
                );
                if (btn) { btn.click(); return true; }
                return false;
            }
        """)
        if not submitted:
            page.keyboard.press('Enter')

        page.wait_for_timeout(3000)
        print(f"  ✅ [{keyword}] 댓글 완료: {post_id} (lang={lang})")
        engaged_ids.add(post_id)
        seen_authors.add(author)
        return {
            'post_id': post_id,
            'keyword': keyword,
            'preview': post_text[:50].replace('\n', ' '),
            'comment': comment,
        }

    except Exception as e:
        print(f"  ❌ 포스트 실패: {e}")
        return None


# ── 키워드 검색 → 포스트 링크 수집 ───────────────────────
def collect_links(page, keyword: str, limit: int = 10) -> List[str]:
    try:
        page.goto(
            f'https://www.threads.com/search?q={keyword}&serp_type=default',
            timeout=30000, wait_until='load',
        )
        page.wait_for_timeout(3000)
        page.evaluate("window.scrollBy(0, 400)")
        page.wait_for_timeout(1500)

        links = page.query_selector_all('a[href*="/post/"]')
        if len(links) < 8:
            for _ in range(3):
                page.evaluate("window.scrollBy(0, 600)")
                page.wait_for_timeout(1000)
            links = page.query_selector_all('a[href*="/post/"]')

        hrefs = []
        seen = set()
        for lnk in links:
            try:
                href = lnk.get_attribute('href') or ''
            except Exception:
                continue
            if '/post/' not in href or href in seen:
                continue
            seen.add(href)
            hrefs.append(href)
            if len(hrefs) >= limit:
                break

        print(f"  포스트 {len(hrefs)}개 발견")
        return hrefs
    except Exception as e:
        print(f"  ❌ 검색 실패 [{keyword}]: {e}")
        return []


# ── 메인 실행 ──────────────────────────────────────────
engaged_today: List[Dict] = []
errors: List[str] = []

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
                args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-blink-features=AutomationControlled',
                ],
            )
            ctx = browser.new_context(
                user_agent=(
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/124.0.0.0 Safari/537.36'
                ),
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
            page.goto('https://www.threads.com/', wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(3000)

            if 'login' in page.url:
                errors.append("세션만료_쿠키재발급필요")
                print("⚠️ 세션 만료")
            else:
                print(f"✅ 로그인 성공")

                ko_done = 0
                en_done = 0

                # ── 1. 한국어 키워드 공략 ──────────────────
                print(f"\n📌 한국어 공략 시작 (목표 {KOREAN_LIMIT}개)")
                for keyword in ko_keywords:
                    if ko_done >= KOREAN_LIMIT:
                        break
                    print(f"\n🔍 검색: '{keyword}'")
                    seen_authors: Set[str] = set()
                    hrefs = collect_links(page, keyword, limit=12)

                    for href in hrefs:
                        if ko_done >= KOREAN_LIMIT:
                            break
                        result = engage_post(page, href, keyword, seen_authors, lang='ko')
                        if result:
                            engaged_today.append(result)
                            ko_done += 1
                            time.sleep(random.uniform(90, 130))  # 최소 90초 간격

                # ── 2. 영어 키워드 공략 ───────────────────
                print(f"\n🌐 영어 공략 시작 (목표 {ENGLISH_LIMIT}개)")
                for keyword in en_keywords:
                    if en_done >= ENGLISH_LIMIT:
                        break
                    print(f"\n🔍 검색 (EN): '{keyword}'")
                    seen_authors_en: Set[str] = set()
                    hrefs = collect_links(page, keyword, limit=10)

                    for href in hrefs:
                        if en_done >= ENGLISH_LIMIT:
                            break
                        result = engage_post(page, href, keyword, seen_authors_en, lang='en')
                        if result:
                            engaged_today.append(result)
                            en_done += 1
                            time.sleep(random.uniform(90, 130))

            browser.close()

    except Exception as e:
        print(f"❌ 오류: {e}")
        errors.append(str(e)[:80])

debug_f.close()
sys.stdout = sys.__stdout__

# ── engage_log.csv 기록 ───────────────────────────────
if engaged_today:
    is_new = not LOG_FILE.exists()
    with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(
            f,
            fieldnames=['date', 'post_id', 'keyword', 'preview', 'comment'],
        )
        if is_new:
            w.writeheader()
        for e in engaged_today:
            w.writerow({'date': today, **e})

# ── 결과 출력 (cron.log용) ────────────────────────────
ko_count = sum(1 for e in engaged_today if not any(
    ord(c) < 128 for c in e.get('comment', '')[:20]
))
print(f"\n{'='*50}")
print(f"[hunter-engager] {today} 완료")
print(f"총 댓글: {len(engaged_today)}/{DAILY_LIMIT}개  (상태: {status})")
if errors:
    print(f"오류: {' / '.join(errors)}")
print('='*50)
