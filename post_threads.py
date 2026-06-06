"""
Threads API 직접 포스팅 스크립트
Buffer 불필요 — access token으로 직접 발행
"""
import json, os, time, sys, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
today = datetime.now(KST).strftime('%Y-%m-%d')

# 로컬(절대경로)·클라우드(체크아웃 경로) 양쪽에서 동작하도록 스크립트 기준 상대경로
BASE_DIR     = Path(__file__).resolve().parent
DATA_DIR     = BASE_DIR / 'data'
CONFIG_FILE  = DATA_DIR / 'threads_config.json'
POSTS_FILE   = DATA_DIR / 'posts.json'
SLACK_CONFIG = DATA_DIR / 'slack_config.json'
LOCK_DIR     = DATA_DIR / 'locks'

def load_config():
    # 1순위: 로컬 파일 / 2순위: 환경변수(GitHub Secrets)
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    token = os.environ.get('THREADS_ACCESS_TOKEN')
    user_id = os.environ.get('THREADS_USER_ID')
    if token and user_id:
        return {'threads_access_token': token, 'threads_user_id': user_id}
    print("❌ 토큰 없음 — threads_config.json 파일도, THREADS_ACCESS_TOKEN/THREADS_USER_ID env도 없음")
    sys.exit(1)

def post_to_threads(text: str, user_id: str, token: str, topic_tag: str = 'AI_THREADS', reply_to_id: str = None) -> dict:
    """Threads API로 포스트 발행. 2단계: container 생성 → publish"""

    params = {
        'media_type': 'TEXT',
        'text': text,
        'access_token': token
    }
    if topic_tag and not reply_to_id:
        params['topic_tag'] = topic_tag
    if reply_to_id:
        params['reply_to_id'] = reply_to_id

    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        f'https://graph.threads.net/v1.0/{user_id}/threads',
        data=data, method='POST'
    )
    with urllib.request.urlopen(req) as r:
        container = json.loads(r.read())

    container_id = container.get('id')
    if not container_id:
        return {'error': f'container 생성 실패: {container}'}

    print(f"  container_id: {container_id}")
    time.sleep(3)

    data = urllib.parse.urlencode({
        'creation_id': container_id,
        'access_token': token
    }).encode()
    req = urllib.request.Request(
        f'https://graph.threads.net/v1.0/{user_id}/threads_publish',
        data=data, method='POST'
    )
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())

    return result

def send_slack(msg: str):
    webhook = ''
    if SLACK_CONFIG.exists():
        try:
            webhook = json.loads(SLACK_CONFIG.read_text()).get('webhook_url', '')
        except Exception:
            webhook = ''
    if not webhook:  # 클라우드: 환경변수(GitHub Secrets)
        webhook = os.environ.get('SLACK_WEBHOOK', '')
    if not webhook:
        return
    data = json.dumps({'text': msg}).encode()
    req = urllib.request.Request(webhook, data=data,
                                  headers={'Content-Type': 'application/json'})
    urllib.request.urlopen(req)

def already_posted_today(user_id: str, token: str, content: str) -> bool:
    """오늘 이미 같은 내용 올렸는지 Threads API로 확인"""
    try:
        url = f"https://graph.threads.net/v1.0/{user_id}/threads?fields=text,timestamp&limit=5&access_token={token}"
        with urllib.request.urlopen(url) as r:
            result = json.loads(r.read())
        fingerprint = content[:30].strip()
        for p in result.get('data', []):
            post_date = p.get('timestamp', '')[:10]
            post_text = p.get('text', '')[:30].strip()
            if post_date == today and post_text == fingerprint:
                print(f"  ⚠️ 오늘 이미 동일 포스트 있음 (id: {p.get('id')}) — 스킵")
                return True
    except Exception as e:
        print(f"  중복 체크 실패 (무시하고 진행): {e}")
    return False


def refresh_token_if_needed(config: dict) -> dict:
    """토큰 갱신 (만료 7일 전 자동 갱신)"""
    token = config['threads_access_token']
    url = f"https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token&access_token={token}"
    try:
        with urllib.request.urlopen(url) as r:
            result = json.loads(r.read())
        if 'access_token' in result:
            config['threads_access_token'] = result['access_token']
            if CONFIG_FILE.exists():  # 로컬에서만 파일 갱신 (클라우드는 Secrets라 스킵)
                CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False))
            print(f"  토큰 갱신 완료 (expires_in: {result.get('expires_in')}s)")
    except Exception as e:
        print(f"  토큰 갱신 실패 (무시): {e}")
    return config

if __name__ == '__main__':
    # --slot morning(기본) | evening
    slot = 'morning'
    if '--slot' in sys.argv:
        idx = sys.argv.index('--slot')
        if idx + 1 < len(sys.argv):
            slot = sys.argv[idx + 1]

    slot_label = '오전' if slot == 'morning' else '저녁'
    print(f"[{today}] post_threads.py 시작 ({slot_label})")

    # 시간 게이트 — Mac 슬립 후 늦게 깨어난 경우 스킵
    now_hour = datetime.now(KST).hour
    if slot == 'morning' and now_hour >= 13:
        msg = f"⏭ [{today}] 오전 포스팅 스킵 — 현재 {now_hour}시 (오후 1시 이후엔 오전 글 안 올림)"
        print(msg)
        send_slack(msg)
        sys.exit(0)
    if slot == 'evening' and (now_hour >= 23 or now_hour < 18):
        msg = f"⏭ [{today}] 저녁 포스팅 스킵 — 현재 {now_hour}시 (18~22시 범위 밖)"
        print(msg)
        send_slack(msg)
        sys.exit(0)

    if not CONFIG_FILE.exists():
        print("❌ threads_config.json 없음")
        sys.exit(1)
    config = load_config()

    if not POSTS_FILE.exists():
        send_slack(f"❌ [{today}] posts.json 없음 — 포스팅 실패")
        sys.exit(1)

    posts = json.loads(POSTS_FILE.read_text())

    # 슬롯에 맞는 포스트 선택
    # morning: 오늘 날짜 중 evening 필드 없거나 False인 첫 번째
    # evening: 오늘 날짜 중 evening: true 인 것
    if slot == 'evening':
        post = next((p for p in posts if p['date'] == today and p.get('evening')), None)
    else:
        post = next((p for p in posts if p['date'] == today and not p.get('evening')), None)

    if not post:
        msg = f"⚠️ [{today}] {slot_label} 예약 포스트 없음"
        send_slack(msg)
        print(msg)
        sys.exit(0)

    content = post.get('content', '')
    if not content:
        send_slack(f"❌ [{today}] {slot_label} content 비어있음 — 포스팅 실패")
        sys.exit(1)

    topic_tag = post.get('topic', 'AI_THREADS')

    print(f"슬롯: {slot_label} | topic: {topic_tag}")
    print(f"내용 앞 50자: {content[:50]}...")

    config = refresh_token_if_needed(config)
    token = config['threads_access_token']
    user_id = config['threads_user_id']

    # 로컬 락 파일로 중복 방지 (API 전파 지연과 무관하게 원자적 체크)
    LOCK_DIR.mkdir(exist_ok=True)
    lock_file = LOCK_DIR / f"{today}_{slot}.lock"
    try:
        lock_file.open('x').close()
    except FileExistsError:
        msg = f"⚠️ [{today}] {slot_label} 락 파일 존재 — 중복 실행 차단"
        print(msg)
        send_slack(msg)
        sys.exit(0)

    if already_posted_today(user_id, token, content):
        send_slack(f"⚠️ [{today}] {slot_label} 이미 포스팅됨 — 중복 스킵")
        sys.exit(0)

    # 블록된 포스트 확인
    if post.get('blocked'):
        msg = f"🚫 [{today}] {slot_label} 포스트 팩트체커에 의해 블록됨 — 포스팅 중단"
        print(msg)
        send_slack(msg)
        sys.exit(0)

    try:
        result = post_to_threads(content, user_id, token, topic_tag)
        if 'id' not in result:
            raise Exception(str(result))

        post_id = result['id']
        print(f"✅ {slot_label} 포스팅 성공: post_id={post_id}")
        send_slack(f"✅ [{today}] {slot_label} 포스팅 성공\n└ {content[:60]}...")

        reply_text = post.get('reply', '')
        if reply_text:
            time.sleep(5)
            try:
                reply_result = post_to_threads(reply_text, user_id, token, reply_to_id=post_id)
                if 'id' in reply_result:
                    print(f"  💬 첫 댓글 게시 완료: {reply_result['id']}")
                else:
                    print(f"  ⚠️ 첫 댓글 실패: {reply_result}")
            except Exception as re:
                print(f"  ⚠️ 첫 댓글 예외: {re}")

    except Exception as e:
        err_msg = f"❌ [{today}] {slot_label} 포스팅 실패: {e}"
        print(err_msg)
        send_slack(err_msg)
        sys.exit(1)
