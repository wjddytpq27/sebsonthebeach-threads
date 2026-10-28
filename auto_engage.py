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
# directive가 '한국어 N / 영어 N' 절대 개수로 명시한 경우(비율보다 우선) —
# 09-25 사고(표본 재수집기엔 % 대신 정수 스플릿 지시) 재발 대응
_m_split = re.search(r'한국어\s*(\d+)\s*/\s*영어\s*(\d+)', _directive)
if _m_split:
    KOREAN_LIMIT  = int(_m_split.group(1))
    ENGLISH_LIMIT = int(_m_split.group(2))
    DAILY_LIMIT   = KOREAN_LIMIT + ENGLISH_LIMIT
else:
    ENGLISH_LIMIT = max(1, round(DAILY_LIMIT * english_ratio))
    KOREAN_LIMIT  = DAILY_LIMIT - ENGLISH_LIMIT

# ── 키워드 결정 (top_search_keywords 우선, 기본 키워드 보완) ──
top_keywords = signal.get('top_search_keywords', [])

# team_signal directive에서 추출한 오늘 한국어 키워드 순서
# normal: 퍼스널브랜딩 → 디지털마케팅 → 온라인창업
# (directives 텍스트 파싱보다 top_search_keywords 활용)
DEFAULT_KO_KEYWORDS = [
    "AI 자동화", "ChatGPT 활용", "클로드",
    "AI 에이전트", "바이브코딩", "AI 툴", "커서",
    "프롬프트", "노코드", "생산성 AI", "AI 부업",
]

# top_keywords 먼저, 나머지로 보완
ko_keywords = list(dict.fromkeys(top_keywords + DEFAULT_KO_KEYWORDS))

# emergency: 팔로워 1만+ 계정만 → 영어 대형 계정 타겟
if status == 'emergency':
    en_keywords = [
        "AI agents", "vibe coding", "Claude Code",
        "AI automation", "LLM tools", "AI coding",
    ]
else:
    en_keywords = [
        "AI agents", "vibe coding", "Claude Code",
        "AI automation", "prompt engineering",
    ]

print(f"[{today}] 상태: {status} | 목표: {DAILY_LIMIT}개 (한국어 {KOREAN_LIMIT} / 영어 {ENGLISH_LIMIT})")
print(f"한국어 키워드: {ko_keywords[:5]}")
print(f"영어 키워드: {en_keywords}")

# ── 재실행 가드: 당일 목표 이미 달성 시 즉시 종료 ─────────
# (8/12·8/24·8/28·9/02·9/04 재발 방지: auto_engage는 remaining을
#  0부터 재시작하는 구조라, 목표 달성 후 재실행하면 과다 engagement
#  스팸 리스크. engage_log의 당일 완료 수가 목표 이상이면 skip.)
def _done_today() -> int:
    if not LOG_FILE.exists():
        return 0
    try:
        import csv as _csv
        with open(LOG_FILE, encoding="utf-8") as _f:
            return sum(1 for _r in _csv.DictReader(_f) if _r.get("date") == today)
    except Exception:
        return 0

_already = _done_today()
if _already >= DAILY_LIMIT:
    print(f"[{today}] 재실행 스킵 — 오늘 이미 {_already}/{DAILY_LIMIT}개 완료 (engage_log 기준). 과다 engagement 스팸 방지.")
    sys.exit(0)
elif _already > 0:
    _remaining = DAILY_LIMIT - _already
    KOREAN_LIMIT = max(0, min(KOREAN_LIMIT, _remaining))
    ENGLISH_LIMIT = max(0, _remaining - KOREAN_LIMIT)
    print(f"[{today}] 부분 완료 감지 — 오늘 {_already}개 기록됨 → 남은 {_remaining}개만 진행 (한국어 {KOREAN_LIMIT} / 영어 {ENGLISH_LIMIT}).")


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
# 작성기(입력창) 미발견 누적 카운터 — soft 로그아웃(세션만료) 조기 감지용
NO_COMPOSER_COUNT = 0
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
2. React to what the post is actually about. Default to adding practical info or sharing concrete experience. Avoid pushback (only if clearly wrong, and gently — never combative). Avoid questions unless genuinely curious, and even then rarely.
3. Length: 1-3 lines
4. No generic replies that could fit any post
5. No "great post", "I agree", "so true"
6. Zero or one emoji max
7. Don't over-explain AI like a tutorial — talk like someone who already knows, one specific point
8. No hype words (game-changer, revolutionary, the future). Be dry or specific
9. If it reads polished/balanced/AI-written, it failed. Sound like a person typing fast on their phone

Output the comment text only. No quotes or explanation."""
    else:
        prompt = f"""너는 @sebsonthebeach 계정 운영자야.
AI·자동화를 실제로 써본 실무자 포지션. 말투는 완전 반말 구어체.

아래 Threads 포스트에 댓글을 달아야 해.

포스트:
{text}

규칙:
1. 포스트 안의 특정 내용(문장, 주장, 숫자)을 직접 지칭하거나 인용할 것
2. 포스트가 실제로 말하는 맥락·주제에 자연스럽게 반응해라. 기본은 "경험" 또는 "보완":
   - 경험(우선): 포스트 주제랑 연결된 구체적 내 경험/관점 한 조각
   - 보완(우선): 포스트에 없는 실용적 정보 1줄
   - 반박: 어지간하면 하지 마라. 명백히 틀렸을 때만, 그것도 부드럽게 (시비조·공격 절대 금지)
   - 질문: 웬만하면 금지. 진짜 궁금한 것만, 그것도 드물게
3. 길이: 1~3줄
4. 어느 포스트에나 붙일 수 있는 범용 댓글 절대 금지
5. "좋은 글", "공감합니다", "맞아요", 내용 단순 반복 금지
6. 이모지 없거나 최대 1개
7. "우리" 금지, "나/내가" 사용. 팀/에이전트/봇 단어 절대 금지
8. AI 얘기라고 아는 척 설명·정의·나열하지 마라. 이미 아는 사람처럼 특정 포인트 하나만 툭 던져
9. "게임체인저/혁신/미래/판 바뀐다" 같은 과장·감탄 금지. 시큰둥하거나 구체적으로
10. 봇·AI가 쓴 티(과하게 정중, 균형 잡힌 요약, 매끈한 완결문 3줄) 나면 실패. 사람이 폰으로 툭 친 느낌으로

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
        # SPA 인앱 클릭 네비게이션으로 이동.
        # 2026-09-17 회귀 확인: page.goto(개별 포스트 URL)로 직접 이동하면
        # Threads가 클라이언트 라우팅상 홈 피드(/? injected_media_ids=...)로
        # 되돌려버려서 실제로는 포스트 페이지에 도달하지 못한다.
        # (그 상태에서도 홈 피드의 아무 포스트 텍스트가 읽혀서 겉으론 정상처럼
        # 보이지만, 답글 버튼이 전혀 없어 100% 스킵되는 사고가 있었다.)
        # 검색 결과 페이지에서 해당 링크를 "클릭"해야 포스트 URL이 유지된다.
        # 검색 결과 SPA 렌더링이 간헐적으로 느려서(networkidle 기준으로도
        # 로딩 실패 관측됨) 최대 2회까지 재검색 후 링크를 찾는다.
        search_url = f'https://www.threads.com/search?q={keyword}&serp_type=default'
        clicked = False
        last_err: Optional[Exception] = None
        for attempt in range(2):
            page.goto(search_url, wait_until='load', timeout=20000)
            page.wait_for_timeout(2500 + attempt * 1500)
            link_loc = page.locator(f'a[href="{href}"]').first
            try:
                link_loc.wait_for(timeout=6000)
                link_loc.click(timeout=6000)
                clicked = True
                break
            except Exception as e:
                last_err = e
                continue
        if not clicked:
            print(f"  ❌ 링크 클릭 실패 → 스킵: {post_id} ({last_err})")
            return None
        page.wait_for_timeout(2500)

        # 내 계정 포스트 스킵
        if 'sebsonthebeach' in page.url:
            return None

        # 포스트 이동 실패(홈 등 엉뚱한 곳으로 리다이렉트) 감지 —
        # 잘못된 포스트에 댓글이 달리는 사고 방지.
        if href.split('?')[0] not in page.url:
            print(f"    ⚠️ 포스트 이동 실패 — 리다이렉트됨({page.url}) → 스킵")
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

        # 답글(작성기 트리거) 버튼 클릭 → 입력창 등장 확인까지 한 묶음.
        # 주의: Threads 포스트 페이지에는 aria-label="댓글"인 '댓글 수' 요소가 있는데
        # 이건 작성기를 열지 않는다. 실제 작성기를 여는 건 '답글'/'Reply' 버튼이므로
        # 우선순위를 '답글' > 'Reply' > '댓글' > 'Comment' 로 두고,
        # 클릭 후 입력창이 안 뜨면 다음 후보로 넘어간다.
        composer_selectors = [
            'div[contenteditable="true"]',
            'div[role="textbox"]',
            '[data-lexical-editor="true"]',
            'textarea',
        ]

        def find_composer():
            for sel in composer_selectors:
                loc = page.locator(sel).first
                try:
                    loc.wait_for(timeout=4000)
                    print(f"    입력창 발견: {sel}")
                    return loc
                except Exception:
                    continue
            return None

        # 2026-09-17 UI 변경 확인: 답글 버튼의 접근성 이름이 더 이상
        # aria-label에 없고, 내부 svg의 <title> 텍스트로 옮겨갔다
        # (aria-label 자체는 빈 문자열 "" 또는 없음). 그래서 기존
        # [aria-label="답글"] 셀렉터가 전부 못 찾고 "답글 버튼 없음"으로
        # 스킵되는 회귀가 있었다. aria-label과 svg title 둘 다 시도한다.
        reply_box = None
        tried_any = False
        candidate_labels = ['답글', 'Reply', '댓글', 'Comment']

        # 1순위: aria-label 매칭 (구버전 UI 호환)
        for aria in candidate_labels:
            loc = page.locator(f'[aria-label="{aria}"]').first
            try:
                loc.wait_for(timeout=1500)
            except Exception:
                continue
            tried_any = True
            print(f"    답글 버튼 시도(aria-label): {aria}")
            try:
                loc.click(force=True, timeout=5000)
            except Exception:
                page.evaluate(
                    """(label) => {
                        const el = document.querySelector(`[aria-label="${label}"]`);
                        if (el) el.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
                    }""",
                    aria,
                )
            page.wait_for_timeout(2000)
            reply_box = find_composer()
            if reply_box:
                break

        # 2순위: svg 내부 <title> 텍스트로 답글 버튼 찾기 (신규 UI)
        if not reply_box:
            found_via_svg = page.evaluate(
                """(labels) => {
                    const titles = [...document.querySelectorAll('svg > title')];
                    for (const t of titles) {
                        if (labels.includes((t.textContent || '').trim())) {
                            const btn = t.closest('[role="button"], button');
                            if (btn) {
                                btn.scrollIntoView({block: 'center'});
                                btn.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
                                return true;
                            }
                        }
                    }
                    return false;
                }""",
                candidate_labels,
            )
            if found_via_svg:
                tried_any = True
                print("    답글 버튼 시도(svg title)")
                page.wait_for_timeout(2000)
                reply_box = find_composer()

        if not tried_any:
            global NO_COMPOSER_COUNT
            NO_COMPOSER_COUNT += 1
            print("    답글 버튼 없음 — 스킵")
            return None

        if not reply_box:
            NO_COMPOSER_COUNT += 1
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
        NO_COMPOSER_COUNT = 0  # 성공하면 연속 실패 카운터 리셋
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
                # soft 로그아웃(세션 만료) 조기 감지: 성공 0인데 입력창 미발견이
                # SESSION_FAIL_THRESHOLD회 누적되면 세션 만료로 보고 즉시 중단.
                SESSION_FAIL_THRESHOLD = 12
                session_expired = False
                for keyword in ko_keywords:
                    if ko_done >= KOREAN_LIMIT or session_expired:
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
                        elif (not engaged_today) and NO_COMPOSER_COUNT >= SESSION_FAIL_THRESHOLD:
                            errors.append("세션만료_쿠키재발급필요(작성기_미노출)")
                            print(f"  ⚠️ 입력창 {NO_COMPOSER_COUNT}회 연속 미발견 + 성공 0 → 세션 만료로 판단, 중단")
                            session_expired = True
                            break

                # ── 2. 영어 키워드 공략 ───────────────────
                print(f"\n🌐 영어 공략 시작 (목표 {ENGLISH_LIMIT}개)")
                for keyword in en_keywords:
                    if en_done >= ENGLISH_LIMIT or session_expired:
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
