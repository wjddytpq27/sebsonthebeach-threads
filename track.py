"""
track.py — Threads API 기반 인사이트 + 팔로워 수집
Playwright 없음. threads_config.json 토큰으로 직접 API 호출.

수집:
- 팔로워 수 (followers_count)
- 최근 포스트 리스트
- 포스트별 likes, replies, reposts, quotes, views
- engagement_score = likes + replies*3 + reposts*5
→ data/insights.csv, data/follower_log.csv 누적
→ Slack 일간 브리핑
"""
import csv, json, os, urllib.request, urllib.parse, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
today = datetime.now(KST).strftime('%Y-%m-%d')

# 로컬(절대경로)·클라우드(체크아웃 경로) 양쪽에서 동작하도록 스크립트 기준 상대경로 사용
BASE_DIR      = Path(__file__).resolve().parent
DATA_DIR      = BASE_DIR / 'data'
CONFIG_FILE   = DATA_DIR / 'threads_config.json'
INSIGHTS_FILE = DATA_DIR / 'insights.csv'
FOLLOWER_FILE = DATA_DIR / 'follower_log.csv'
SLACK_CONFIG  = DATA_DIR / 'slack_config.json'

BASE = 'https://graph.threads.net/v1.0'


def load_config() -> dict:
    # 1순위: 로컬 파일 / 2순위: 환경변수(GitHub Secrets)
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    token = os.environ.get('THREADS_ACCESS_TOKEN')
    user_id = os.environ.get('THREADS_USER_ID')
    if token and user_id:
        return {'threads_access_token': token, 'threads_user_id': user_id}
    print('❌ 토큰 없음 — threads_config.json 파일도, THREADS_ACCESS_TOKEN/THREADS_USER_ID env도 없음')
    sys.exit(1)


def api_get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read())


def get_followers(user_id: str, token: str) -> int:
    """팔로워 수 — 프로필 fields 우선, insights fallback"""
    # 1순위: fields API (단순하고 안정적)
    try:
        params = urllib.parse.urlencode({
            'fields': 'followers_count',
            'access_token': token,
        })
        data = api_get(f'{BASE}/{user_id}?{params}')
        if 'followers_count' in data:
            return int(data['followers_count'])
    except Exception as e:
        print(f'  ⚠️ followers fields 실패: {e}')

    # 2순위: threads_insights day (total_value 구조)
    try:
        params = urllib.parse.urlencode({
            'metric': 'followers_count',
            'period': 'day',
            'access_token': token,
        })
        data = api_get(f'{BASE}/{user_id}/threads_insights?{params}')
        for item in data.get('data', []):
            if item.get('name') == 'followers_count':
                tv = item.get('total_value', {})
                if 'value' in tv:
                    return int(tv['value'])
    except Exception as e:
        print(f'  ⚠️ threads_insights 실패: {e}')

    return -1


def get_post_list(user_id: str, token: str, limit: int = 20) -> list[dict]:
    """최근 포스트 목록 — id, text, timestamp"""
    try:
        params = urllib.parse.urlencode({
            'fields': 'id,text,timestamp',
            'limit': limit,
            'access_token': token,
        })
        data = api_get(f'{BASE}/{user_id}/threads?{params}')
        return data.get('data', [])
    except Exception as e:
        print(f'  ⚠️ 포스트 목록 수집 실패: {e}')
        return []


def get_post_insights(post_id: str, token: str) -> dict:
    """포스트별 인사이트 — likes, replies, reposts, quotes, views"""
    try:
        params = urllib.parse.urlencode({
            'metric': 'likes,replies,reposts,quotes,views',
            'access_token': token,
        })
        data = api_get(f'{BASE}/{post_id}/insights?{params}')
        result = {}
        for item in data.get('data', []):
            if 'values' in item:
                result[item['name']] = item['values'][-1].get('value', 0) if item['values'] else 0
            else:
                result[item['name']] = item.get('value', 0)
        return result
    except Exception as e:
        print(f'    ⚠️ {post_id} 인사이트 실패: {e}')
        return {}


def write_follower_log(count: int) -> int:
    """follower_log.csv 기록. 7일 전 수치 반환."""
    if count < 0:
        return -1

    is_new = not FOLLOWER_FILE.exists()
    prev_count = -1

    if FOLLOWER_FILE.exists():
        week_ago = (datetime.now(KST) - timedelta(days=7)).strftime('%Y-%m-%d')
        with open(FOLLOWER_FILE, encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        if any(r.get('date') == today for r in rows):
            print('follower_log: 오늘 이미 기록됨')
            prev = next((r for r in reversed(rows) if r.get('date', '') <= week_ago), None)
            return int(prev['followers']) if prev else -1
        prev = next((r for r in reversed(rows) if r.get('date', '') <= week_ago), None)
        if prev:
            prev_count = int(prev['followers'])

    with open(FOLLOWER_FILE, 'a', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(['date', 'followers'])
        w.writerow([today, count])
    print(f'follower_log.csv 기록: {count}명')
    return prev_count


def write_insights(rows: list[dict]):
    """insights.csv 기록 — 오늘 수집된 포스트 (post_id 중복 있으면 덮어쓰지 않음)"""
    existing_ids = set()
    is_new = not INSIGHTS_FILE.exists()

    if not is_new:
        with open(INSIGHTS_FILE, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row.get('collected_date') == today:
                    existing_ids.add(row.get('post_id', ''))

    new_rows = [r for r in rows if r['post_id'] not in existing_ids]
    if not new_rows:
        print('insights.csv: 오늘 이미 모두 기록됨')
        return

    with open(INSIGHTS_FILE, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=[
            'collected_date', 'post_date', 'post_id', 'text_preview',
            'likes', 'replies', 'reposts', 'quotes', 'views', 'engagement_score'
        ])
        if is_new:
            w.writeheader()
        for r in new_rows:
            w.writerow({**r, 'collected_date': today})
    print(f'insights.csv 기록: {len(new_rows)}개')


def send_slack(rows: list[dict], follower_count: int, prev_follower: int):
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

    week_ago = (datetime.now(KST) - timedelta(days=7)).strftime('%Y-%m-%d')
    avg_score = 0.0
    if INSIGHTS_FILE.exists():
        # post_id별 가장 최근 collected_date 데이터만 사용
        latest: dict = {}
        with open(INSIGHTS_FILE, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                pid = row.get('post_id', '')
                if not pid or row.get('post_date', '') < week_ago:
                    continue
                if pid not in latest or row.get('collected_date', '') > latest[pid].get('collected_date', ''):
                    latest[pid] = row
        w_scores = []
        for row in latest.values():
            try:
                w_scores.append(int(row.get('engagement_score') or 0))
            except ValueError:
                pass
        if w_scores:
            avg_score = round(sum(w_scores) / len(w_scores), 1)

    # 단건("오늘 1등")이 아니라 최근 흐름을 보여준다.
    # 1~2개짜리 일일 포스트에서 1등을 뽑는 건 의미가 없고,
    # 최근 윈도우 전체에서 뭐가 먹히고 뭐가 죽는지 추세를 봐야 방향을 잡는다.
    ranked = sorted(rows, key=lambda x: x['engagement_score'], reverse=True)
    dead = sum(1 for r in rows if r['engagement_score'] == 0)
    win_avg = round(sum(r['engagement_score'] for r in rows) / len(rows), 1) if rows else 0.0

    follower_str = f'{follower_count:,}명' if follower_count >= 0 else '수집 불가'
    if follower_count >= 0 and prev_follower >= 0:
        diff = follower_count - prev_follower
        follower_str += f" ({'+' if diff >= 0 else ''}{diff} vs 7일 전)"

    out = [f'🧵 *@sebsonthebeach 일간 브리핑* ({today})', '']
    out.append('*📊 계정 현황*')
    out.append(f'팔로워: {follower_str}')
    out.append(f'수집 포스트: {len(rows)}개 (최근 20개 기준)')
    out.append('')

    # 최근 흐름 — 뭐가 먹히는지 TOP3, 헛스윙 비율, 추세
    out.append('*🔥 최근 먹히는 글 TOP3* (최근 20개 중)')
    if ranked:
        medals = ['🥇', '🥈', '🥉']
        for i, p in enumerate(ranked[:3]):
            out.append(
                f'{medals[i]} score {p["engagement_score"]} '
                f'(❤️{p["likes"]} 💬{p["replies"]}) "{p["text_preview"][:34]}…"'
            )
    else:
        out.append('수집된 포스트 없음')
    out.append('')

    out.append('*📈 흐름*')
    if avg_score == 0 and rows and any(r['engagement_score'] > 0 for r in rows):
        out.append('⚠️ 7일 평균 집계 오류 — insights.csv 날짜 범위 확인 필요')
    else:
        arrow = '▲ 상승' if win_avg >= avg_score else '▼ 하락'
        out.append(f'최근20 평균 score {win_avg} {arrow} (7일 평균 {avg_score})')
        out.append(f'무반응(0점) {dead}/{len(rows)}개 — 헛스윙 비율')
    out.append('')

    # 방향 제안 — 단건 칭찬이 아니라 흐름 기반 판단
    out.append('*🎯 방향 제안*')
    if not rows:
        out.append('• ❗ 수집 포스트 없음 — track/포스팅 점검 필요')
    else:
        if dead >= len(rows) * 0.5:
            out.append(f'• 절반 이상({dead}개)이 무반응 — 안 먹히는 각도 정리 필요')
        if avg_score > 0 and win_avg < avg_score * 0.85:
            out.append('• 최근 반응이 7일 평균 아래로 하락 — 각도 전환 고려')
        elif avg_score > 0 and win_avg >= avg_score * 1.15:
            out.append('• 최근 반응 상승세 — 잘 나가는 글 각도 강화')
        if ranked and ranked[0]['engagement_score'] >= max(win_avg * 2, 20):
            out.append(f'• TOP 글이 평균 2배+ — "{ranked[0]["text_preview"][:24]}…" 각도로 follow-up')
        if len(out) and out[-1] == '*🎯 방향 제안*':
            out.append('• 흐름 평이 — TOP3 미리보기 보고 직접 방향 판단')

    if follower_count >= 0 and prev_follower >= 0:
        diff = follower_count - prev_follower
        if diff <= 0:
            out.append('• ⚠️ 팔로워 7일째 정체 — growth_analyst 확인 요망')

    payload = {
        'text': '\n'.join(out),
        'username': '📊 thread (this Mac • verified)',
        'icon_emoji': ':bar_chart:',
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(webhook, data=data, headers={'Content-Type': 'application/json'})
    urllib.request.urlopen(req)
    print('슬랙 발송 완료')


if __name__ == '__main__':
    print(f'[{today}] track.py 시작 (Threads API)')

    config = load_config()
    token = config['threads_access_token']
    user_id = config['threads_user_id']

    print('팔로워 수 수집 중...')
    follower_count = get_followers(user_id, token)
    print(f'  팔로워: {follower_count if follower_count >= 0 else "수집 실패"}')

    print('포스트 목록 수집 중...')
    posts = get_post_list(user_id, token, limit=20)
    print(f'  포스트 {len(posts)}개')

    rows = []
    for post in posts:
        post_id = post.get('id', '')
        text = post.get('text', '')
        timestamp = post.get('timestamp', '')
        post_date = timestamp[:10] if timestamp else today

        print(f'  인사이트 수집: {post_id} ({post_date})')
        metrics = get_post_insights(post_id, token)

        likes    = int(metrics.get('likes', 0))
        replies  = int(metrics.get('replies', 0))
        reposts  = int(metrics.get('reposts', 0))
        quotes   = int(metrics.get('quotes', 0))
        views    = int(metrics.get('views', 0))
        score    = likes + replies * 3 + reposts * 5

        rows.append({
            'post_date':        post_date,
            'post_id':          post_id,
            'text_preview':     text[:60].replace('\n', ' '),
            'likes':            likes,
            'replies':          replies,
            'reposts':          reposts,
            'quotes':           quotes,
            'views':            views,
            'engagement_score': score,
        })
        print(f'    ❤️{likes} 댓글{replies} 리포스트{reposts} score={score}')

    prev_follower = write_follower_log(follower_count)
    if rows:
        write_insights(rows)
    send_slack(rows, follower_count, prev_follower)

    print(f'완료: 팔로워 {follower_count}, 포스트 {len(rows)}개')
