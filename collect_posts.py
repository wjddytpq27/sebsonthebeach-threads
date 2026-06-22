"""
PHASE 1: Threads 포스트 수집기
- 오늘 키워드로 검색 → 댓글 안 단 포스트 수집
- 결과를 /Users/uneedcomms/thread/data/pending_posts.json 에 저장
- Claude 에이전트가 이 파일을 읽고 댓글 생성
"""
import json, csv, hashlib, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter

KST = timezone(timedelta(hours=9))
today = datetime.now(KST).strftime('%Y-%m-%d')

# ─────────────────────────────────────────
# 포스트 타입 분류 + 좋아요 필터링 유틸
# ─────────────────────────────────────────

def classify_post(text: str) -> tuple:
    """
    포스트 타입 분류 + 우선순위 점수 반환
    Returns: (type_label, priority_score)
    """
    t = (text or '').lower()

    # 광고/홍보형 — 무조건 스킵
    spam_signals = ['클릭', 'link in bio', '구매', '할인코드', '이벤트 참여',
                    '팔로우하고', '공유해주세요', '문의는 dm', 'dm 주세요', '협찬', '#ad', '#광고']
    if any(s in t for s in spam_signals):
        return ('spam', -1)

    # 질문형 — 최우선 (작성자가 댓글 기다리는 포스트)
    question_signals = ['어떻게', '추천', '있나요', '있을까요', '어떤가요', '알려주',
                        '여쭤봐도', '질문', '고민인데', '도움', '의견', '방법 없나', '?']
    question_score = sum(1 for s in question_signals if s in t)
    if question_score >= 2:
        return ('question', 10)

    # 고민/공감형 — 2순위 (대화 연결이 자연스러움)
    empathy_signals = ['나만', '힘들', '어렵', '모르겠', '막막', '지쳐', '솔직히', '사실',
                       '이런 경험', '공감', '나도', '맞죠', '그렇죠']
    empathy_score = sum(1 for s in empathy_signals if s in t)
    if empathy_score >= 2:
        return ('empathy', 8)

    # 정보공유형 — 3순위
    info_signals = ['방법', '팁', '노하우', '공유', '정리', '해봤', '써봤', '후기', '리뷰',
                    '알게 됐', '배웠', '깨달']
    info_score = sum(1 for s in info_signals if s in t)
    if info_score >= 2:
        return ('info', 5)

    # 일상/기타
    return ('general', 2)


def score_by_likes(like_count: int) -> int:
    """
    좋아요 수 → 우선순위 점수
    5~49:   황금 구간 (댓글 경쟁 최소, 알림 확인률 최대)
    50~199: 허용 구간
    0~4:    노출 없는 포스트 → 제외
    200+:   대형 계정, 댓글 묻힘 → 제외
    """
    if like_count < 5:
        return 0
    elif like_count <= 49:
        return 10
    elif like_count <= 199:
        return 5
    else:
        return 0

# team_signal.json 기반 키워드 결정 (hash 방식 오버라이드)
_signal_path = Path('/Users/uneedcomms/thread/data/team_signal.json')
_signal = {}
if _signal_path.exists():
    try:
        _signal = json.loads(_signal_path.read_text())
    except Exception:
        pass

# top_search_keywords 먼저 → 기본 키워드 보완
_top = _signal.get('top_search_keywords', [])
_default_ko = [
    "퍼스널브랜딩", "디지털마케팅", "이커머스",
    "온라인창업", "자사몰", "스마트스토어", "셀러",
    "1인기업", "콘텐츠마케팅", "부업", "N잡",
]
# AI 관련 키워드 제외 (team_signal 지시)
_exclude = {"AI활용", "ChatGPT활용", "AI부업", "ChatGPT", "AI API"}
today_keywords = [k for k in list(dict.fromkeys(_top + _default_ko)) if k not in _exclude]

# 영어 키워드 (normal 상태: 20%)
EN_KEYWORDS = [
    "AI tools automation", "marketing automation",
    "solopreneur growth", "SaaS founder", "content creator tips",
]
NEED_KO = 25  # 한국어 수집 목표 (여유분 포함)
NEED_EN = 8   # 영어 수집 목표 (여유분 포함)

data_dir = Path('/Users/uneedcomms/thread/data')
data_dir.mkdir(exist_ok=True)

log_file = data_dir / 'engage_log.csv'
pending_file = data_dir / 'pending_posts.json'
session_file = Path('/Users/uneedcomms/thread/session_state.json')

# 이미 댓글 단 post_id + author 불러오기
engaged_ids = set()
engaged_authors = set()
if log_file.exists():
    with open(log_file, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            engaged_ids.add(row.get('post_id', ''))
            if row.get('author'):
                engaged_authors.add(row.get('author', ''))

print(f"[{today}] 수집 시작 | 키워드: {today_keywords}")
print(f"기존 댓글 기록: {len(engaged_ids)}개 포스트, {len(engaged_authors)}명 작성자")

if not session_file.exists():
    print("❌ session_state.json 없음. setup_auth.py 먼저 실행하세요.")
    sys.exit(1)

with open(session_file, encoding='utf-8') as f:
    state_data = json.load(f)

collected = []

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

        print("✅ 로그인 성공")

        ko_collected = []
        for keyword in today_keywords:
            if len(ko_collected) >= NEED_KO:
                break
            print(f"\n🔍 한국어: '{keyword}'")
        # ---- 아래에 기존 루프 내용 재사용 (변수명만 ko_collected로)
            try:
                page.goto(
                    f'https://www.threads.com/search?q={keyword}&serp_type=default',
                    timeout=20000, wait_until='networkidle'
                )
                page.wait_for_timeout(3000)

                # 스크롤로 포스트 더 로드
                for _ in range(3):
                    page.evaluate("window.scrollBy(0, 600)")
                    page.wait_for_timeout(1000)

                post_links = page.query_selector_all('a[href*="/post/"]')
                print(f"  포스트 {len(post_links)}개 발견")

                seen_hrefs = set()
                for link in post_links[:10]:
                    if len(collected) >= 30:
                        break
                    try:
                        href = link.get_attribute('href') or ''
                    except:
                        continue

                    if '/post/' not in href or href in seen_hrefs:
                        continue
                    seen_hrefs.add(href)

                    post_id = href.split('/post/')[-1].split('/')[0].split('?')[0]
                    author = href.split('/post/')[0].lstrip('/@') if '/post/' in href else ''

                    # 내 계정 스킵
                    if author == 'sebsonthebeach':
                        continue

                    # 이미 댓글 단 포스트 스킵
                    if post_id in engaged_ids:
                        print(f"  ↩ 이미 댓글: {post_id}")
                        continue

                    # 최근 댓글 단 작성자 스킵 (오늘 이미 댓글 달면 봇티남)
                    if author and author in engaged_authors:
                        print(f"  ⏭ 기존 댓글 작성자 스킵: @{author}")
                        continue

                    # 포스트 페이지 들어가서 스레드 전체 맥락 추출
                    try:
                        page.goto(f'https://www.threads.com{href}', timeout=15000)
                        page.wait_for_timeout(2500)

                        # 스레드 전체 텍스트 블록 수집 (부모 포스트 + 본문 포함)
                        all_texts = page.evaluate("""
                            () => {
                                const candidates = [...document.querySelectorAll('[dir="auto"]')];
                                return candidates
                                    .map(el => el.innerText?.trim() || '')
                                    .filter(t => t.length > 10 && t.length < 1000);
                            }
                        """) or []

                        # 가장 긴 텍스트 = 본문
                        post_text = max(all_texts, key=len) if all_texts else ''

                        # 본문 외 나머지 = 맥락 (부모 스레드, 이전 답글 등)
                        context_texts = [t for t in all_texts if t != post_text and len(t) > 15]
                        thread_context = ' / '.join(context_texts[:3]) if context_texts else ''

                        # 포스트 텍스트 너무 짧으면 스킵
                        if len(post_text) < 20:
                            print(f"  ⏭ 텍스트 너무 짧음: '{post_text[:30]}'")
                            continue

                        # 맥락 없이 뭔가를 지칭하는 포스트 스킵 (1번/이거/저거 등 지시어만 있음)
                        vague_patterns = ['1번', '2번', '이거', '저거', '그거', '위에', '아래에']
                        is_vague = any(p in post_text for p in vague_patterns) and len(post_text) < 60
                        if is_vague and not thread_context:
                            print(f"  ⏭ 맥락 없는 지시어 포스트 스킵: '{post_text[:40]}'")
                            continue

                        # 좋아요 수 추출
                        like_count = page.evaluate("""
                            () => {
                                const spans = [...document.querySelectorAll('span')];
                                for (const s of spans) {
                                    if (s.innerText?.match(/^\\d+$/) && parseInt(s.innerText) > 0) {
                                        return parseInt(s.innerText);
                                    }
                                }
                                return 0;
                            }
                        """) or 0

                        post_url = f'https://www.threads.com{href}'

                        # ── 타입 분류 ──
                        post_type, type_score = classify_post(post_text)

                        # 광고/홍보형 스킵
                        if post_type == 'spam':
                            print(f"  ⏭ 홍보/광고 포스트 스킵")
                            continue

                        # ── 좋아요 필터 ──
                        like_score = score_by_likes(like_count)
                        if like_score == 0:
                            if like_count < 5:
                                print(f"  ⏭ 좋아요 너무 적음 ({like_count}개) — 아무도 안 보는 포스트")
                            else:
                                print(f"  ⏭ 좋아요 너무 많음 ({like_count}개) — 댓글 묻힘 위험")
                            continue

                        priority_score = type_score + like_score

                        print(f"  ✅ 수집: @{author} | 타입={post_type} | 좋아요={like_count} | 점수={priority_score} | {post_text[:40]}...")
                        if thread_context:
                            print(f"     맥락: {thread_context[:60]}...")

                        ko_collected.append({
                            'post_id': post_id,
                            'author': author,
                            'url': post_url,
                            'keyword': keyword,
                            'lang': 'ko',
                            'text': post_text,
                            'thread_context': thread_context,
                            'like_count': like_count,
                            'post_type': post_type,
                            'priority_score': priority_score,
                            'collected_at': datetime.now(KST).isoformat(),
                        })
                        engaged_authors.add(author)  # 같은 세션에서 같은 작성자 중복 방지

                    except Exception as e:
                        print(f"  ❌ 포스트 읽기 실패: {e}")

            except Exception as e:
                print(f"  ❌ 검색 실패 [{keyword}]: {e}")

        # ── 영어 키워드 수집 ──────────────────────────────────
        en_collected = []
        for keyword in EN_KEYWORDS:
            if len(en_collected) >= NEED_EN:
                break
            print(f"\n🔍 영어: '{keyword}'")
            try:
                page.goto(
                    f'https://www.threads.com/search?q={keyword.replace(" ","+")}&serp_type=default',
                    timeout=20000, wait_until='networkidle'
                )
                page.wait_for_timeout(3000)
                for _ in range(3):
                    page.evaluate("window.scrollBy(0, 600)")
                    page.wait_for_timeout(1000)

                en_links = page.query_selector_all('a[href*="/post/"]')
                en_hrefs = []
                seen_en = set()
                for lnk in en_links[:12]:
                    try:
                        href = lnk.get_attribute('href') or ''
                    except Exception:
                        continue
                    if '/post/' not in href or href in seen_en:
                        continue
                    seen_en.add(href)
                    en_hrefs.append(href)

                for href in en_hrefs:
                    if len(en_collected) >= NEED_EN:
                        break
                    post_id = href.split('/post/')[-1].split('/')[0].split('?')[0]
                    author  = href.split('/post/')[0].lstrip('/@') if '/post/' in href else ''
                    if post_id in engaged_ids or author in engaged_authors or 'sebsonthebeach' in href:
                        continue
                    try:
                        page.goto(f'https://www.threads.com{href}', timeout=15000)
                        page.wait_for_timeout(2500)
                        post_text = page.evaluate("""
                            () => {
                                const c = [...document.querySelectorAll('[dir="auto"]')];
                                const t = c.map(el => el.innerText?.trim() || '').filter(t => t.length > 15 && t.length < 1000);
                                if (t.length) return t.reduce((a,b) => a.length > b.length ? a : b);
                                const art = document.querySelector('article');
                                return art ? art.innerText?.trim() || '' : '';
                            }
                        """) or ''
                        if len(post_text) < 15:
                            continue
                        # Skip non-English posts
                        en_char_ratio = sum(1 for c in post_text if ord(c) < 256) / max(len(post_text), 1)
                        if en_char_ratio < 0.7:
                            continue
                        likes = page.evaluate("""
                            () => {
                                const els = document.querySelectorAll('[aria-label]');
                                for (const el of els) {
                                    const m = (el.getAttribute('aria-label')||'').match(/(\\d+)\\s*(like|좋아요)/i);
                                    if (m) return parseInt(m[1]);
                                }
                                return -1;
                            }
                        """) or -1
                        if likes != -1 and (likes < 5 or likes > 500):
                            continue
                        engaged_authors.add(author)
                        en_collected.append({
                            'post_id': post_id,
                            'author': author,
                            'url': f'https://www.threads.com{href}',
                            'keyword': keyword,
                            'lang': 'en',
                            'text': post_text,
                            'thread_context': '',
                            'like_count': likes,
                            'post_type': 'info',
                            'priority_score': 7,
                            'collected_at': datetime.now(KST).isoformat(),
                        })
                        print(f"    ✅ EN: {post_id} (좋아요:{likes}) — {post_text[:40].replace(chr(10),' ')}")
                    except Exception as e:
                        print(f"    ❌ EN 포스트: {e}")
            except Exception as e:
                print(f"  ❌ EN 검색 실패 [{keyword}]: {e}")

        collected = ko_collected + en_collected
        browser.close()

except Exception as e:
    print(f"❌ Playwright 오류: {e}")
    sys.exit(1)

# 우선순위 점수 높은 순으로 정렬 — Claude 에이전트가 앞에서부터 처리하므로 중요
collected.sort(key=lambda x: x.get('priority_score', 0), reverse=True)

# 결과 저장
with open(pending_file, 'w', encoding='utf-8') as f:
    json.dump({
        'date': today,
        'keywords': today_keywords,
        'posts': collected,
        'status': 'pending'  # Claude가 처리 후 'ready'로 변경
    }, f, ensure_ascii=False, indent=2)

# 수집 통계 출력
if collected:
    type_dist = Counter(p['post_type'] for p in collected)
    avg_score = sum(p['priority_score'] for p in collected) / len(collected)
    avg_likes = sum(p['like_count'] for p in collected) / len(collected)
    print(f"\n📊 수집 통계")
    print(f"  타입 분포: {dict(type_dist)}")
    print(f"  평균 점수: {avg_score:.1f} | 평균 좋아요: {avg_likes:.1f}")
    print(f"  TOP 포스트: @{collected[0]['author']} | 점수={collected[0]['priority_score']} | 좋아요={collected[0]['like_count']}")

print(f"\n✅ 수집 완료: {len(collected)}개 포스트 → {pending_file}")
print("다음 단계: Claude 에이전트가 댓글 생성")
