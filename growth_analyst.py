"""
growth_analyst.py — 성과 분석 + 팀 신호 생성
매일 22:30 실행 (track.py 이후)

출력:
- data/team_signal.json   ← 팀 전체가 읽는 공유 브리핑
- data/growth_strategy.json ← viral-writer 전략 (team_signal 서브셋)
- Slack 알림

team_signal.json 구조:
{
  "status": "normal|stall|emergency",
  "days_since_growth": 3,
  "follower_trend": "150→153 (5일, 일평균 +0.6)",
  "best_performing": { "style": "...", "avg_score": 18.0, "example": "..." },
  "worst_performing": { "style": "...", "avg_score": 0.5 },
  "keyword_performance": { "AI활용": {"comments": 5, "growth_days_after": 2} },
  "directives": {
    "trend_scout": "구체적 지시",
    "viral_writer": "구체적 지시",
    "hunter_engager": "구체적 지시"
  },
  "updated_at": "2026-05-25"
}
"""
import csv, json, subprocess, sys, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
today = datetime.now(KST).strftime('%Y-%m-%d')

INSIGHTS_FILE  = Path('/Users/uneedcomms/thread/data/insights.csv')
FOLLOWER_FILE  = Path('/Users/uneedcomms/thread/data/follower_log.csv')
ENGAGE_LOG     = Path('/Users/uneedcomms/thread/data/engage_log.csv')
SIGNAL_FILE    = Path('/Users/uneedcomms/thread/data/team_signal.json')
STRATEGY_FILE  = Path('/Users/uneedcomms/thread/data/growth_strategy.json')
SLACK_CONFIG   = Path('/Users/uneedcomms/thread/data/slack_config.json')
CLAUDE_BIN     = '/opt/homebrew/bin/claude'


def send_slack(msg: str):
    if not SLACK_CONFIG.exists():
        return
    try:
        webhook = json.loads(SLACK_CONFIG.read_text()).get('webhook_url', '')
        if not webhook:
            return
        payload = {
            'text': msg,
            'username': '📊 thread (this Mac • verified)',
            'icon_emoji': ':bar_chart:',
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            webhook, data=data, headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req)
    except Exception as e:
        print(f'  슬랙 실패: {e}')


def load_follower_history(days: int = 21) -> list[dict]:
    if not FOLLOWER_FILE.exists():
        return []
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime('%Y-%m-%d')
    with open(FOLLOWER_FILE, encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f) if r.get('date', '') >= cutoff]
    return sorted(rows, key=lambda x: x['date'])


def load_post_insights(days: int = 14) -> list[dict]:
    if not INSIGHTS_FILE.exists():
        return []
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime('%Y-%m-%d')
    # post_id별 가장 최근 collected_date 데이터만 사용
    latest: dict = {}
    with open(INSIGHTS_FILE, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            pid = r.get('post_id', '')
            if not pid or r.get('post_date', '') < cutoff:
                continue
            if pid not in latest or r.get('collected_date', '') > latest[pid].get('collected_date', ''):
                latest[pid] = r
    return sorted(latest.values(), key=lambda x: x.get('post_date', ''))


def detect_status(follower_history: list[dict]) -> tuple[str, int, str]:
    """팔로워 추이 → status 결정. (status, days_since_growth, reason)"""
    if len(follower_history) < 2:
        return 'normal', 0, '데이터 부족'

    counts = [(r['date'], int(r['followers'])) for r in follower_history]

    # 최근 마지막으로 팔로워가 늘었던 날 찾기
    days_since_growth = 0
    for i in range(len(counts) - 1, 0, -1):
        if counts[i][1] > counts[i - 1][1]:
            break
        days_since_growth += 1

    first, last = counts[0][1], counts[-1][1]
    period = len(counts)
    daily_avg = round((last - first) / max(period - 1, 1), 2)
    trend_str = f'{first}→{last} ({period}일, 일평균 {daily_avg:+.1f})'

    if days_since_growth >= 5:
        return 'emergency', days_since_growth, trend_str
    elif days_since_growth >= 3:
        return 'stall', days_since_growth, trend_str
    else:
        return 'normal', days_since_growth, trend_str


def analyze_keyword_performance(follower_history: list[dict]) -> dict:
    """
    engage_log.csv 키워드 × follower_log.csv 성장일 상관관계.
    어떤 키워드로 댓글 달았을 때 다음날 팔로워가 늘었나?
    """
    if not ENGAGE_LOG.exists() or len(follower_history) < 2:
        return {}

    # 팔로워 증가일 set
    growth_days = set()
    for i in range(1, len(follower_history)):
        if int(follower_history[i]['followers']) > int(follower_history[i - 1]['followers']):
            growth_days.add(follower_history[i]['date'])

    # 키워드별 댓글 날짜 집계
    keyword_days: dict[str, set] = {}
    with open(ENGAGE_LOG, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            kw = row.get('keyword', '').strip()
            date = row.get('date', '').strip()
            if kw and date:
                keyword_days.setdefault(kw, set()).add(date)

    result = {}
    for kw, days in keyword_days.items():
        growth_after = sum(
            1 for d in days
            if (datetime.strptime(d, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d') in growth_days
        )
        result[kw] = {
            'comment_days': len(days),
            'growth_days_after': growth_after,
            'hit_rate': round(growth_after / len(days), 2) if days else 0,
        }

    # hit_rate 기준 정렬
    return dict(sorted(result.items(), key=lambda x: x[1]['hit_rate'], reverse=True))


def analyze_posts(posts: list[dict]) -> tuple[dict, dict]:
    """상위/하위 포스트 패턴 분석. (best, worst)"""
    if not posts:
        return {}, {}

    scored = sorted(posts, key=lambda x: int(x.get('engagement_score', 0)), reverse=True)
    top3 = scored[:3]
    bottom3 = [p for p in scored[-3:] if int(p.get('engagement_score', 0)) == 0]

    top_avg = round(sum(int(p['engagement_score']) for p in top3) / len(top3), 1) if top3 else 0
    bot_avg = round(sum(int(p['engagement_score']) for p in bottom3) / len(bottom3), 1) if bottom3 else 0

    best = {
        'avg_score': top_avg,
        'examples': [p['text_preview'][:60] for p in top3],
    }
    worst = {
        'avg_score': bot_avg,
        'count': len(bottom3),
    }
    return best, worst


def generate_team_signal(
    status: str,
    days_since_growth: int,
    follower_trend: str,
    best: dict,
    worst: dict,
    kw_performance: dict,
) -> dict:
    """Claude haiku로 팀 신호 + 에이전트별 지시 생성"""

    top_kws = list(kw_performance.keys())[:5]
    kw_summary = ', '.join(
        f'{k}(hit={v["hit_rate"]})' for k, v in list(kw_performance.items())[:5]
    ) if kw_performance else '데이터 없음'

    best_examples = '\n'.join(f'  - {e}' for e in best.get('examples', []))

    status_ko = {'normal': '정상', 'stall': '정체', 'emergency': '비상'}.get(status, status)

    prompt = f"""너는 @sebsonthebeach Threads 팀의 성장 분석가야.
계정 포지션: AI·자동화 실무자 + 마케팅 퍼널 사고. 반말 구어체.
금지 주제: 자사몰/카페24, 추상적 AI 미래론.

오늘 분석 결과:
- 상태: {status_ko} ({days_since_growth}일째 팔로워 변화 없음)
- 팔로워 추이: {follower_trend}
- 상위 포스트 평균 score: {best.get("avg_score", 0)}
- 상위 포스트 예시:
{best_examples if best_examples else "  없음"}
- 0점 포스트 수: {worst.get("count", 0)}개
- 키워드 효과 (댓글 → 다음날 팔로워 증가 hit rate): {kw_summary}

아래 JSON만 출력 (다른 텍스트 없이):
{{
  "team_memo": "오늘 상태 한 줄 요약 (팀원들이 제일 먼저 읽는 것)",
  "best_post_style": "잘 된 포스트 공통점 (1~2줄, 구체적으로)",
  "worst_post_style": "안 된 포스트 공통점 (1줄)",
  "top_search_keywords": ["효과 좋은 키워드1", "키워드2", "키워드3"],
  "directives": {{
    "trend_scout": "{('트렌딩 10개 이상, 논쟁형/반전형 우선, 영어권 AI 반응 포함' if status in ['stall','emergency'] else '평소대로')}",
    "viral_writer": "오늘 포스트 작성 지침 (각도, 훅 강도, 피해야 할 것)",
    "hunter_engager": "오늘 댓글 목표 수 + 우선 키워드 + 영어 비중"
  }}
}}"""

    try:
        result = subprocess.run(
            [CLAUDE_BIN, '-p', prompt, '--model', 'sonnet'],
            capture_output=True, text=True, timeout=90
        )
        output = result.stdout.strip()
        if '```' in output:
            parts = output.split('```')
            output = parts[1] if len(parts) > 1 else parts[0]
            if output.startswith('json'):
                output = output[4:].strip()
        return json.loads(output)
    except Exception as e:
        print(f'  ⚠️ AI 신호 생성 실패: {e}')
        stall_directive = status in ['stall', 'emergency']
        return {
            'team_memo': f'상태: {status_ko}. {days_since_growth}일째 팔로워 변화 없음.',
            'best_post_style': '숫자+반전 훅, AI 실무 경험담',
            'worst_post_style': '범용 동기부여, 추상적 AI 전망',
            'top_search_keywords': top_kws[:3] if top_kws else ['AI활용', 'ChatGPT활용', '퍼스널브랜딩'],
            'directives': {
                'trend_scout': '트렌딩 10개 이상, 논쟁형 우선' if stall_directive else '평소대로',
                'viral_writer': '훅에 숫자 필수, 논쟁형 각도' if stall_directive else '숫자+반전 유지',
                'hunter_engager': f'목표 {"35" if stall_directive else "25"}개, 영어 비중 {"40" if stall_directive else "20"}%',
            },
        }


def devil_advocate(status: str, follower_trend: str, best: dict, worst: dict) -> str:
    """현재 분석에 반박. 아첨 방지용."""
    best_examples = '\n'.join(f'  - {e}' for e in best.get('examples', [])[:3])
    prompt = f"""너는 @sebsonthebeach Threads 팀의 비판 감사자야.
방금 growth_analyst가 아래 분석을 냈어. 이걸 반박해.

분석 결과:
- 상태: {status}
- 팔로워 추이: {follower_trend}
- 잘 됐다는 포스트:
{best_examples if best_examples else '  없음'}
- 안 됐다는 포스트 수: {worst.get('count', 0)}개

반박 지침:
- "잘 되고 있다"고 하면 "왜 팔로워 증가율이 낮은가"로 반박
- 상위 포스트 패턴이 있다면 "재현 가능한가, 우연이 아닌가" 질문
- 현재 전략이 유지되면 30일 후 어떻게 될지 예측
- 2~3문장으로 짧게, 한국어, 반말"""

    try:
        result = subprocess.run(
            [CLAUDE_BIN, '-p', prompt],
            capture_output=True, text=True, timeout=60
        )
        return result.stdout.strip()
    except Exception:
        return "악마의 변호인 분석 실패"


if __name__ == '__main__':
    print(f'[{today}] growth_analyst.py 시작')

    follower_history = load_follower_history(21)
    posts = load_post_insights(14)
    print(f'  팔로워 기록 {len(follower_history)}일치, 포스트 {len(posts)}개 로드')

    if not follower_history and not posts:
        print('  ⚠️ 데이터 없음 — track.py 먼저 실행 필요')
        send_slack(f'⚠️ [{today}] growth_analyst: 데이터 없음. track.py 확인 요망')
        sys.exit(0)

    # 분석
    status, days_since_growth, follower_trend = detect_status(follower_history)
    kw_performance = analyze_keyword_performance(follower_history)
    best, worst = analyze_posts(posts)

    print(f'  상태: {status} (정체 {days_since_growth}일)')
    print(f'  팔로워 추이: {follower_trend}')

    # 팀 신호 생성
    print('  팀 신호 생성 중...')
    ai_signal = generate_team_signal(status, days_since_growth, follower_trend, best, worst, kw_performance)

    print('  악마의 변호인 분석 중...')
    critic = devil_advocate(status, follower_trend, best, worst)
    print(f'  비판: {critic[:80]}...')

    # team_signal.json 조립
    signal = {
        'status': status,
        'days_since_growth': days_since_growth,
        'follower_trend': follower_trend,
        'best_performing': {
            **best,
            'style': ai_signal.get('best_post_style', ''),
        },
        'worst_performing': {
            **worst,
            'style': ai_signal.get('worst_post_style', ''),
        },
        'keyword_performance': kw_performance,
        'top_search_keywords': ai_signal.get('top_search_keywords', []),
        'directives': ai_signal.get('directives', {}),
        'team_memo': ai_signal.get('team_memo', ''),
        'devil_advocate': critic,
        'updated_at': today,
    }

    SIGNAL_FILE.write_text(json.dumps(signal, ensure_ascii=False, indent=2))
    print(f'  team_signal.json 저장: status={status}')

    # growth_strategy.json도 호환성 유지로 함께 저장
    strategy = {
        'weekly_focus': ai_signal.get('directives', {}).get('viral_writer', ''),
        'recommended_topics': ai_signal.get('top_search_keywords', []),
        'avoid_topics': ['자사몰/카페24 직접 언급', '추상적 AI 미래론'],
        'best_post_style': ai_signal.get('best_post_style', ''),
        'worst_post_style': ai_signal.get('worst_post_style', ''),
        'posting_times': {'morning': '10:21', 'evening': '20:00'},
        'engagement_keywords': ai_signal.get('top_search_keywords', []),
        'alert': signal['team_memo'],
        'generated_at': today,
    }
    STRATEGY_FILE.write_text(json.dumps(strategy, ensure_ascii=False, indent=2))

    # Slack 알림
    status_emoji = {'normal': '✅', 'stall': '⚠️', 'emergency': '🚨'}.get(status, '📊')
    out = [f'{status_emoji} *팀 브리핑* ({today})', '']
    out.append(f'`{signal["team_memo"]}`')
    out.append('')
    out.append(f'*팔로워*: {follower_trend}')
    out.append('')
    out.append('*에이전트 지시*')
    for agent, directive in signal['directives'].items():
        out.append(f'• *{agent}*: {directive}')

    if kw_performance:
        top_kw = list(kw_performance.items())[:3]
        kw_str = ' | '.join(f'{k} (hit {v["hit_rate"]})' for k, v in top_kw)
        out.append(f'\n*키워드 효과*: {kw_str}')

    if status in ('stall', 'emergency'):
        out.append(f'\n{status_emoji} *{days_since_growth}일째 정체 — 전략 전환 필요*')

    out.append(f'\n🔴 *비판 감사*: {critic}')

    send_slack('\n'.join(out))
    print('완료')
