"""
weekly_report.py — 매주 월요일 09:30 KST 주간 브리핑
launchd: com.thread.weekly

데이터: data/follower_log.csv, data/insights.csv (로컬)
"""
import csv, json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import urllib.request

KST = timezone(timedelta(hours=9))
today = datetime.now(KST)
week_ago = today - timedelta(days=7)
two_weeks_ago = today - timedelta(days=14)

CONFIG_FILE   = Path('/Users/uneedcomms/thread/data/threads_config.json')
INSIGHTS_FILE = Path('/Users/uneedcomms/thread/data/insights.csv')
FOLLOWER_FILE = Path('/Users/uneedcomms/thread/data/follower_log.csv')
SLACK_CONFIG  = Path('/Users/uneedcomms/thread/data/slack_config.json')


def send_slack(msg: str):
    if not SLACK_CONFIG.exists():
        return
    webhook = json.loads(SLACK_CONFIG.read_text()).get('webhook_url', '')
    if not webhook:
        return
    payload = {
        'text': msg,
        'username': '📊 thread (this Mac • verified)',
        'icon_emoji': ':bar_chart:',
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(webhook, data=data, headers={'Content-Type': 'application/json'})
    urllib.request.urlopen(req)


def load_posts(since: str, until: str) -> list[dict]:
    if not INSIGHTS_FILE.exists():
        return []
    latest: dict[str, dict] = {}
    with open(INSIGHTS_FILE, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            pd = row.get('post_date', '')
            pid = row.get('post_id', '')
            if not pid or pd < since or pd >= until:
                continue
            cd = row.get('collected_date', '')
            prev = latest.get(pid)
            if prev is None or cd > prev.get('collected_date', ''):
                latest[pid] = row
    result = []
    for row in latest.values():
        likes   = int(row.get('likes', 0) or 0)
        replies = int(row.get('replies', 0) or 0)
        reposts = int(row.get('reposts', 0) or 0)
        score   = likes + replies * 3 + reposts * 5
        result.append({
            'date': row.get('post_date', ''),
            'text': row.get('text_preview', ''),
            'likes': likes,
            'replies': replies,
            'reposts': reposts,
            'score': score,
        })
    return result


def load_followers(since: str) -> list[tuple[str, int]]:
    if not FOLLOWER_FILE.exists():
        return []
    rows = []
    with open(FOLLOWER_FILE, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if row.get('date', '') >= since:
                try:
                    rows.append((row['date'], int(row['followers'])))
                except (ValueError, KeyError):
                    pass
    return sorted(rows)


def classify(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ['%', '명', '개', '만원', '달러', '$']):
        return '숫자형'
    elif any(k in t for k in ['왜', '이유', '차이', '비교', '틀렸', '아님']):
        return '논쟁형'
    elif any(k in t for k in ['했다', '날렸다', '실패', '배웠다', '고백']):
        return '고백형'
    else:
        return '정보형'


this_week  = load_posts(week_ago.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d'))
last_week  = load_posts(two_weeks_ago.strftime('%Y-%m-%d'), week_ago.strftime('%Y-%m-%d'))
followers  = load_followers(week_ago.strftime('%Y-%m-%d'))

if not this_week:
    send_slack(f"⚠️ 주간 브리핑: 이번 주 포스트 데이터 없음 ({today.strftime('%m/%d')})")
    print("데이터 없음")
    exit(0)

this_week.sort(key=lambda x: x['score'], reverse=True)

total_likes   = sum(p['likes'] for p in this_week)
total_replies = sum(p['replies'] for p in this_week)
avg_likes     = round(total_likes / len(this_week), 1)
avg_replies   = round(total_replies / len(this_week), 1)
avg_score     = round(sum(p['score'] for p in this_week) / len(this_week), 1)

prev_avg_likes   = round(sum(p['likes'] for p in last_week) / len(last_week), 1) if last_week else None
prev_avg_replies = round(sum(p['replies'] for p in last_week) / len(last_week), 1) if last_week else None

# 팔로워 증감
follower_str = '데이터 수집 중'
if len(followers) >= 2:
    f_start, f_end = followers[0][1], followers[-1][1]
    diff = f_end - f_start
    follower_str = f'{f_start:,} → {f_end:,} ({"+"+str(diff) if diff >= 0 else str(diff)}명)'
elif len(followers) == 1:
    follower_str = f'{followers[0][1]:,}명'

# 유형별 평균 score
type_scores: dict[str, list] = {}
for p in this_week:
    t = classify(p['text'])
    type_scores.setdefault(t, []).append(p['score'])
type_avg = {t: round(sum(s) / len(s), 1) for t, s in type_scores.items()}
best_type = max(type_avg, key=type_avg.get) if type_avg else '-'

top3  = this_week[:3]
worst = this_week[-1]

# 지난 주 대비
likes_diff   = round(avg_likes - prev_avg_likes, 1) if prev_avg_likes is not None else None
replies_diff = round(avg_replies - prev_avg_replies, 1) if prev_avg_replies is not None else None

out = [
    f"🧵 *@sebsonthebeach Threads 주간 브리핑*",
    f"({week_ago.strftime('%m/%d')}~{today.strftime('%m/%d')})",
    "",
    "*📊 계정 성장*",
    f"팔로워: {follower_str}",
    f"포스트 {len(this_week)}개 | 좋아요 {total_likes} | 댓글 {total_replies}",
]

if likes_diff is not None:
    sl = '+' if likes_diff >= 0 else ''
    sr = '+' if replies_diff >= 0 else ''
    out.append(f"포스트당 평균: 좋아요 {avg_likes}({sl}{likes_diff}) | 댓글 {avg_replies}({sr}{replies_diff}) ← 지난 주 대비")

out += ["", "*🏆 이번 주 Top 3*"]
for i, p in enumerate(top3, 1):
    out.append(f"{i}위 (score {p['score']} | ❤️{p['likes']} 댓글{p['replies']}) \"{p['text'][:45]}...\"")

out += [
    "",
    "*📉 반응 최저*",
    f"score {worst['score']} | ❤️{worst['likes']} 댓글{worst['replies']} \"{worst['text'][:45]}...\"",
    "",
    "*🔍 유형별 평균 score*",
]
for t, avg in sorted(type_avg.items(), key=lambda x: -x[1]):
    out.append(f"{t}: {avg}점")

out += [
    "",
    "*➡️ 다음 주 방향*",
    f"• {best_type} 더 밀기 — 이번 주 최고 유형 (avg {type_avg.get(best_type, 0)}점)",
]
if avg_replies < 2:
    out.append("• 댓글 유도 강화 — self-reply 질문 더 구체적으로")
if avg_score < 5:
    out.append("• 전반적 engagement 낮음 — 훅 강도 올리기, 숫자/반전 각도 늘리기")

send_slack("\n".join(out))
print(f"주간 브리핑 발송: {len(this_week)}개 포스트 | 평균 score {avg_score}")
