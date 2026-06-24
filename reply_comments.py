"""
reply_comments.py — 내 포스트 댓글 자동 답장
하루 2회 (13:00, 21:00 KST)

전략:
- 댓글에 빠른 반응 = 알고리즘 재가동
- 댓글당 1회 답장, 억지 티키타카 없음
- 자연스러운 마무리 우선

흐름:
1. 최근 7일 내 포스트 목록 가져오기
2. 각 포스트의 댓글(replies) 수집
3. 내 계정 댓글 + 이미 답장한 댓글 스킵
4. Claude haiku로 질문형 답장 생성
5. Threads API로 답장 게시
6. replied_comments.csv에 기록
"""
import csv, json, subprocess, time, urllib.request, urllib.parse, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, '/Users/uneedcomms/thread')
from engage_post import is_valid_comment

KST = timezone(timedelta(hours=9))
today = datetime.now(KST).strftime('%Y-%m-%d')

CONFIG_FILE  = Path('/Users/uneedcomms/thread/data/threads_config.json')
REPLIED_FILE = Path('/Users/uneedcomms/thread/data/replied_comments.csv')
SLACK_CONFIG = Path('/Users/uneedcomms/thread/data/slack_config.json')
CLAUDE_BIN   = '/opt/homebrew/bin/claude'
MY_USERNAME  = 'sebsonthebeach'
MAX_REPLIES  = 10  # 1회 실행당 최대 답장 수
BASE         = 'https://graph.threads.net/v1.0'


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text())


def api_get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read())


def api_post(url: str, params: dict) -> dict:
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method='POST')
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def load_replied_ids() -> set:
    if not REPLIED_FILE.exists():
        return set()
    with open(REPLIED_FILE, encoding='utf-8') as f:
        return {row['comment_id'] for row in csv.DictReader(f) if row.get('comment_id')}


def save_reply(post_id: str, comment_id: str, comment_text: str, my_reply: str):
    is_new = not REPLIED_FILE.exists()
    with open(REPLIED_FILE, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['date', 'post_id', 'comment_id', 'comment_preview', 'my_reply'])
        if is_new:
            w.writeheader()
        w.writerow({
            'date': today,
            'post_id': post_id,
            'comment_id': comment_id,
            'comment_preview': comment_text[:60].replace('\n', ' '),
            'my_reply': my_reply[:80].replace('\n', ' '),
        })


def get_recent_posts(user_id: str, token: str, days: int = 7) -> list[dict]:
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S')
    params = urllib.parse.urlencode({
        'fields': 'id,text,timestamp',
        'limit': 20,
        'access_token': token,
    })
    data = api_get(f'{BASE}/{user_id}/threads?{params}')
    posts = data.get('data', [])
    return [p for p in posts if p.get('timestamp', '') >= cutoff]


def get_comments(post_id: str, token: str) -> list[dict]:
    """포스트의 직접 댓글 목록"""
    try:
        params = urllib.parse.urlencode({
            'fields': 'id,text,username,timestamp',
            'access_token': token,
        })
        data = api_get(f'{BASE}/{post_id}/replies?{params}')
        return data.get('data', [])
    except Exception as e:
        print(f'    댓글 수집 실패: {e}')
        return []


def generate_reply(post_text: str, comment_text: str):
    """Claude haiku로 질문형 답장 생성"""
    prompt = f"""너는 @sebsonthebeach 본인이야. 1인 계정. 혼자 운영함.
AI·자동화 실무자. 말투는 완전 반말 구어체.

내 포스트:
{post_text[:200]}

상대 댓글:
{comment_text}

규칙:
1. 포스트 주제 + 댓글 내용 둘 다 고려해서 맥락에 맞게 답장
2. 댓글에 한 번만 답하면 끝. 대화 이어가려고 억지로 질문 달 필요 없음. 자연스럽게 마무리해도 됨.
3. 반박이나 싸우려는 톤 절대 금지. 원만하고 가볍게.
4. 억지로 달 필요 없는 댓글이면 (단순 감탄사, 의미없는 짧은 댓글 등) "SKIP" 출력
5. 1~2줄
6. "감사합니다" "좋은 의견이에요" "공감해요" 금지
7. 이모지 없거나 1개
8. 절대 금지 단어: 팀, 에이전트, 자동화, 봇, 시스템, 운영팀, 담당자 — 이 단어 쓰면 즉시 SKIP
9. 항상 나 혼자 운영하는 1인 계정처럼 써. "우리" 금지, 항상 "나/내가"
10. "너는", "네가", "너희" 같은 직접 지칭 금지 — 주어 없이 질문해. "어떻게 하고 있어?" O / "너는 어떻게 하고 있어?" X
11. AI 티 나는 표현 금지: "결국", "핵심은", "체계적이네", "정리가 잘 됐네", "명확하네", "중요한 포인트" — 너무 정리된 말투 쓰지 마. 사람이 쓰는 것처럼 좀 흐트러져도 됨
12. 완성형 문장 나열 금지 — 줄 바꿈 없이 한두 문장, 구어체로

답장 텍스트만 출력. SKIP이면 SKIP만. 따옴표나 설명 없이."""

    try:
        result = subprocess.run(
            [CLAUDE_BIN, '-p', prompt, '--model', 'haiku'],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            print(f'    ⚠️ Claude CLI 오류 (code {result.returncode}): {result.stderr[:60]}')
            return None
        reply = result.stdout.strip().strip('"')
        cli_error_patterns = [
            "not logged in", "please run", "/login", "authentication",
            "unauthorized", "log in", "sign in", "session expired",
            "traceback", "exception", "error:", "failed to", "cannot connect",
        ]
        if any(p in reply.lower() for p in cli_error_patterns):
            print(f'    ⚠️ Claude CLI 오류 문구 감지 — 차단: {reply[:50]}')
            return None
        if not reply or reply.strip().upper() == 'SKIP':
            print(f'    ↩ SKIP 판정')
            return None
        bad = ['감사합니다', '좋은 의견', '공감해요', '맞아요', '저도요']
        expose = ['팀', '에이전트', '자동화', '봇', '운영팀', '담당자', '시스템']
        ai_tone = ['결국 ', '핵심은', '체계적이네', '정리가 잘', '명확하네', '중요한 포인트', '핵심이네']
        if any(b in reply for b in bad):
            print(f'    ⚠️ 봇티 감지 스킵: {reply[:30]}')
            return None
        if any(e in reply for e in expose):
            print(f'    ⚠️ 계정 노출 위험 스킵: {reply[:30]}')
            return None
        if any(a in reply for a in ai_tone):
            print(f'    ⚠️ AI 말투 감지 스킵: {reply[:30]}')
            return None
        # 메타/되묻기 텍스트 차단 (공용 가드 — "텍스트가 보이지 않습니다" 류)
        ok, reason = is_valid_comment(reply)
        if not ok:
            print(f'    ⛔ 게시 부적합 스킵: {reason} | {reply[:30]}')
            return None
        return reply
    except Exception as e:
        print(f'    ⚠️ 답장 생성 실패: {e}')
        return None


def post_reply(user_id: str, token: str, comment_id: str, reply_text: str):
    """댓글에 답장 게시. 생성된 thread_id 반환"""
    try:
        # 1단계: container 생성
        container = api_post(
            f'{BASE}/{user_id}/threads',
            {
                'media_type': 'TEXT',
                'text': reply_text,
                'reply_to_id': comment_id,
                'access_token': token,
            }
        )
        container_id = container.get('id')
        if not container_id:
            print(f'    container 생성 실패: {container}')
            return None

        time.sleep(2)

        # 2단계: 발행
        result = api_post(
            f'{BASE}/{user_id}/threads_publish',
            {'creation_id': container_id, 'access_token': token}
        )
        return result.get('id')
    except Exception as e:
        print(f'    답장 게시 실패: {e}')
        return None


def send_slack(msg: str):
    if not SLACK_CONFIG.exists():
        return
    try:
        webhook = json.loads(SLACK_CONFIG.read_text()).get('webhook_url', '')
        if not webhook:
            return
        data = json.dumps({'text': msg}).encode()
        req = urllib.request.Request(webhook, data=data, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req)
    except Exception:
        pass


if __name__ == '__main__':
    print(f'[{today}] reply_comments.py 시작')

    config = load_config()
    token = config['threads_access_token']
    user_id = config['threads_user_id']

    replied_ids = load_replied_ids()
    print(f'  기존 답장 {len(replied_ids)}개')

    posts = get_recent_posts(user_id, token, days=7)
    print(f'  최근 7일 포스트 {len(posts)}개')

    done = []
    total_replied = 0
    cli_fail_count = 0

    for post in posts:
        if total_replied >= MAX_REPLIES:
            break

        post_id = post['id']
        post_text = post.get('text', '')
        print(f'\n  포스트: {post_text[:40]}...')

        comments = get_comments(post_id, token)
        print(f'  댓글 {len(comments)}개')

        for comment in comments:
            if total_replied >= MAX_REPLIES:
                break

            cid = comment.get('id', '')
            username = comment.get('username', '')
            ctext = comment.get('text', '').strip()

            # 내 댓글이거나 이미 답장했으면 스킵
            if username == MY_USERNAME:
                continue
            if cid in replied_ids:
                continue
            if len(ctext) < 5:
                continue

            print(f'    댓글 @{username}: {ctext[:40]}')

            reply = generate_reply(post_text, ctext)
            if not reply:
                cli_fail_count += 1
                continue

            result_id = post_reply(user_id, token, cid, reply)
            if result_id:
                save_reply(post_id, cid, ctext, reply)
                replied_ids.add(cid)
                total_replied += 1
                done.append({
                    'post': post_text[:30],
                    'comment': ctext[:40],
                    'reply': reply,
                })
                print(f'    ✅ 답장: {reply[:50]}')
                time.sleep(10)
            else:
                print(f'    ❌ 게시 실패')

    print(f'\n완료: {total_replied}개 답장')

    if cli_fail_count >= 3 and total_replied == 0:
        send_slack(
            f'🔐 *reply_comments Claude CLI 오류* ({today})\n'
            f'댓글 후보 있었으나 생성 {cli_fail_count}회 연속 실패.\n'
            '`! claude /login` 실행 필요'
        )

    if len(done) >= 3:
        out = [f'💬 *댓글 답장* ({today}) — {total_replied}개', '']
        for d in done:
            out.append(f'• "{d["comment"][:35]}"')
            out.append(f'  └ {d["reply"][:60]}')
        send_slack('\n'.join(out))
