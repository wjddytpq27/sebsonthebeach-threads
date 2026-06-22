"""
follow_attributor.py — 팔로워 변동 ↔ 포스트 연결 분석
매일 22:30 실행 (track.py 직후)

핵심 질문: "어떤 글이 실제 팔로워를 만드는가?"
사람들은 글을 본 날 또는 다음날 팔로우하는 경향 → 포스트 날짜 기준 +1일 팔로워 증감과 연결
"""
import csv, json, os, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
today = datetime.now(KST).strftime('%Y-%m-%d')

# 로컬·클라우드 양쪽 동작: 스크립트 기준 상대경로
BASE_DIR       = Path(__file__).resolve().parent
DATA_DIR       = BASE_DIR / 'data'
FOLLOWER_CSV   = DATA_DIR / 'follower_log.csv'
INSIGHTS_CSV   = DATA_DIR / 'insights.csv'
SIGNAL_FILE    = DATA_DIR / 'team_signal.json'
OUTPUT_FILE    = DATA_DIR / 'follow_attribution.json'
SLACK_CONFIG   = DATA_DIR / 'slack_config.json'


def classify_content(text: str) -> str:
    t = (text or '').lower()
    if any(k in t for k in ['자사몰', '셀러', '카페24', '전환율', '회원가입', '재구매']):
        return 'ecommerce_tip'
    if any(k in t for k in ['ai', 'chatgpt', 'claude', 'llm', '생성형', '자동화', '바이브코딩']):
        return 'ai_tech'
    if any(k in t for k in ['①', '②', '③', '1.', '2.', '3.', '공통점', '이것부터']):
        return 'practical_list'
    if any(k in t for k in ['내가', '했더니', '파트너', '셀러가', '배운 것', '깨달은']):
        return 'personal_story'
    if '?' in text[:20] or any(k in t for k in ['틀렸', '거짓', '믿고 있어', '진짜 이유']):
        return 'controversial_opinion'
    return 'other'


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
    payload = {
        'text': msg,
        'username': '📊 thread (this Mac • verified)',
        'icon_emoji': ':bar_chart:',
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(webhook, data=data,
                                  headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req)
    except Exception:
        pass


def load_follower_log() -> list[dict]:
    if not FOLLOWER_CSV.exists():
        return []
    rows = []
    with open(FOLLOWER_CSV) as f:
        for r in csv.DictReader(f):
            try:
                rows.append({'date': r['date'], 'followers': int(r['followers'])})
            except (KeyError, ValueError):
                pass
    return sorted(rows, key=lambda x: x['date'])


def load_insights() -> list[dict]:
    if not INSIGHTS_CSV.exists():
        return []
    rows = []
    with open(INSIGHTS_CSV) as f:
        for r in csv.DictReader(f):
            try:
                rows.append({
                    'post_date': r.get('post_date', ''),
                    'post_id': r.get('post_id', ''),
                    'text': r.get('text_preview', ''),
                    'score': int(r.get('engagement_score', 0) or 0),
                    'views': int(r.get('views', 0) or 0),
                    'likes': int(r.get('likes', 0) or 0),
                    'replies': int(r.get('replies', 0) or 0),
                })
            except (KeyError, ValueError):
                pass
    # 날짜별 최신 수집 기준 dedup
    seen = {}
    for r in rows:
        key = r['post_id']
        if key not in seen or r['score'] > seen[key]['score']:
            seen[key] = r
    return list(seen.values())


if __name__ == '__main__':
    print(f"[{today}] follow_attributor.py 시작")

    follower_log = load_follower_log()
    insights = load_insights()

    # 날짜별 팔로워 증감
    daily_deltas = []
    for i, row in enumerate(follower_log):
        delta = row['followers'] - follower_log[i-1]['followers'] if i > 0 else 0
        daily_deltas.append({'date': row['date'], 'followers': row['followers'], 'delta': delta})

    # 날짜 → delta 맵
    delta_map = {d['date']: d['delta'] for d in daily_deltas}

    # 포스트별: 포스트 날짜 +1일의 팔로워 증감 연결
    def next_date(d: str) -> str:
        dt = datetime.strptime(d, '%Y-%m-%d') + timedelta(days=1)
        return dt.strftime('%Y-%m-%d')

    posts_by_date: dict[str, list] = {}
    for p in insights:
        pd = p['post_date']
        if pd:
            posts_by_date.setdefault(pd, []).append(p)

    follow_drivers = []
    for post_date, posts in posts_by_date.items():
        nxt = next_date(post_date)
        follower_delta = delta_map.get(nxt, None)

        if follower_delta is None:
            continue

        # 당일 포스트 중 가장 높은 score
        best = max(posts, key=lambda p: p['score'])

        if len(posts) == 1:
            confidence = 'high' if follower_delta > 0 else 'medium'
        elif follower_delta > 0:
            confidence = 'medium'
        else:
            confidence = 'low'

        follow_drivers.append({
            'post_date': post_date,
            'text_preview': best['text'][:80],
            'content_type': classify_content(best['text']),
            'engagement_score': best['score'],
            'views': best['views'],
            'follower_delta_next_day': follower_delta,
            'attribution_confidence': confidence,
        })

    follow_drivers.sort(key=lambda x: x['follower_delta_next_day'], reverse=True)

    # 베스트 follow driver
    positive_drivers = [d for d in follow_drivers if d['follower_delta_next_day'] > 0]
    best_driver = positive_drivers[0] if positive_drivers else None

    # content_type별 평균 팔로워 증감
    type_stats: dict[str, list] = {}
    for d in follow_drivers:
        type_stats.setdefault(d['content_type'], []).append(d['follower_delta_next_day'])
    type_avg = {t: sum(v)/len(v) for t, v in type_stats.items()}
    best_type = max(type_avg, key=lambda t: type_avg[t]) if type_avg else None

    total_posts = len(follow_drivers)
    avg_per_post = (
        sum(d['follower_delta_next_day'] for d in follow_drivers) / total_posts
        if total_posts > 0 else 0
    )

    insight_text = "데이터 부족"
    if positive_drivers:
        top_types = sorted(type_avg.items(), key=lambda x: x[1], reverse=True)[:2]
        insight_text = f"팔로워 증가 유발 콘텐츠: {', '.join(t for t, _ in top_types)}"
        if best_driver:
            insight_text += f" | 최고 사례: \"{best_driver['text_preview'][:40]}...\""

    result = {
        'updated_at': today,
        'daily_deltas': daily_deltas[-14:],
        'follow_drivers': follow_drivers,
        'best_follow_driver': {
            'text_preview': best_driver['text_preview'] if best_driver else None,
            'post_date': best_driver['post_date'] if best_driver else None,
            'content_type': best_driver['content_type'] if best_driver else None,
            'follower_delta': best_driver['follower_delta_next_day'] if best_driver else 0,
        },
        'content_type_avg_delta': type_avg,
        'best_content_type': best_type,
        'avg_followers_per_post': round(avg_per_post, 2),
        'insight': insight_text,
    }

    OUTPUT_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"  팔로워 연결 분석 완료: {len(follow_drivers)}개 포스트, 평균 +{avg_per_post:.2f}/포스트")
    print(f"  베스트 타입: {best_type} | 인사이트: {insight_text}")

    # team_signal.json 업데이트 (follow_attribution 필드만)
    if SIGNAL_FILE.exists():
        signal = json.loads(SIGNAL_FILE.read_text())
        signal['follow_attribution'] = {
            'best_content_type': best_type,
            'avg_followers_per_post': round(avg_per_post, 2),
            'best_driver_preview': best_driver['text_preview'][:60] if best_driver else None,
            'stop_types': [t for t, avg in type_avg.items() if avg <= 0],
        }
        SIGNAL_FILE.write_text(json.dumps(signal, indent=2, ensure_ascii=False))

    # 귀속 분석은 growth_analyst 팀 브리핑에 통합 — 별도 Slack 없음
    print(f"완료: 포스트당 평균 +{avg_per_post:.2f}명, 최고 타입={best_type}")
