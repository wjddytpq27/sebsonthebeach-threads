"""
reward.py — 2층 보상 신호 (순수 함수, I/O 없음)

북극성(계정): 7일 롤링 팔로워 순증. 최종 목적함수.
포스트 프록시: Threads API가 "이 글로 몇 명 팔로우"를 못 주므로,
  팔로우 의도가 강한 행동(리포스트·인용·댓글 > 좋아요)을 도달(views)로 정규화한 대리 지표.

engagement_score(track.py: likes + replies*3 + reposts*5)와 의도적으로 다르다:
  - engagement_score는 좋아요 중심 → 인게이지 최적화용.
  - 여기 reward는 팔로우 전환 대리 → "본 사람 중 몇 %가 팔로우할 만한 행동을 했나".
"""
from __future__ import annotations

# 팔로우 의도 가중: 좋아요는 값싸고, 공유(리포스트)·인용·댓글은 강한 신호.
INTENT_WEIGHTS = {'likes': 1.0, 'replies': 4.0, 'reposts': 8.0, 'quotes': 6.0}

# 도달이 극소인 글은 rate가 튀므로 분모 하한.
VIEW_FLOOR = 200
# 팔로워 일 변동 노이즈 밴드(±) — 이 안이면 귀인 신뢰 낮음.
FOLLOWER_NOISE_BAND = 1
# 실패 판정: 롤링 중앙값 대비 이 비율 미만이면 flop.
FAILURE_RATIO = 0.35


def follow_intent(row: dict) -> float:
    """의도 가중 합. row는 likes/replies/reposts/quotes 키를 가진 dict."""
    return sum(INTENT_WEIGHTS[k] * float(row.get(k, 0) or 0) for k in INTENT_WEIGHTS)


def post_reward(row: dict) -> float:
    """
    포스트 단위 보상 = 도달 1천 회당 의도 가중 행동 수(intent rate ‰).
    스타일 간 공정 비교용(도달 편차 정규화). views 없으면 0.
    """
    views = float(row.get('views', 0) or 0)
    if views <= 0:
        return 0.0
    return round(follow_intent(row) / max(views, VIEW_FLOOR) * 1000, 3)


def reward_components(row: dict) -> dict:
    """랭킹·디버깅용 전체 분해."""
    views = float(row.get('views', 0) or 0)
    intent = follow_intent(row)
    return {
        'intent': round(intent, 2),
        'views': int(views),
        'reward': post_reward(row),                      # 도달 정규화 (스타일 비교)
        'reach_pull': round(intent, 2),                  # 절대 견인력 (누가 끌었나)
    }


def daily_deltas(follower_log: list[dict]) -> list[dict]:
    """[{date, followers}] 정렬 입력 → [{date, followers, delta}]."""
    out: list[dict] = []
    prev = None
    for r in sorted(follower_log, key=lambda x: x['date']):
        f = int(r['followers'])
        out.append({'date': r['date'], 'followers': f,
                    'delta': 0 if prev is None else f - prev})
        prev = f
    return out


def rolling_follower_gain(follower_log: list[dict], window: int = 7) -> dict:
    """
    북극성: 최근 window일 팔로워 순증.
    {gain, per_day, first, last, days} — 데이터 부족 시 days<window.
    """
    rows = sorted(follower_log, key=lambda x: x['date'])
    if len(rows) < 2:
        return {'gain': 0, 'per_day': 0.0, 'first': None, 'last': None, 'days': len(rows)}
    tail = rows[-(window + 1):]
    gain = int(tail[-1]['followers']) - int(tail[0]['followers'])
    span = len(tail) - 1
    return {
        'gain': gain,
        'per_day': round(gain / span, 2) if span else 0.0,
        'first': int(tail[0]['followers']),
        'last': int(tail[-1]['followers']),
        'days': span,
    }


def window_follower_delta(
    post_date: str, deltas_by_date: dict[str, int], window: int = 2
) -> int:
    """
    포스트 발행 후 window일 팔로워 증감 합 (당일+다음날 등).
    사람은 본 날~며칠 내 팔로우 → 짧은 윈도우. 여러 글이 날짜 공유하면 신뢰는 confidence로 별도 표기.
    """
    from datetime import datetime, timedelta
    base = datetime.strptime(post_date, '%Y-%m-%d')
    total = 0
    for i in range(1, window + 1):
        d = (base + timedelta(days=i)).strftime('%Y-%m-%d')
        total += deltas_by_date.get(d, 0)
    return total


def attribution_confidence(follower_delta: int, posts_same_day: int) -> str:
    """
    ±노이즈 밴드와 같은 날 경쟁 글 수로 귀인 신뢰도.
    노이즈 밴드 안이면 무조건 low — +1을 성공으로 착각하지 않기 위함.
    """
    if abs(follower_delta) <= FOLLOWER_NOISE_BAND:
        return 'low'                       # ±1은 노이즈. 예전 로직의 핵심 버그였음.
    if posts_same_day <= 1:
        return 'high' if follower_delta > 0 else 'medium'
    return 'medium' if follower_delta > 0 else 'low'


def is_failure(reward: float, baseline_median: float) -> bool:
    """롤링 중앙값 대비 미달이면 실패. baseline 0이면 reward 0만 실패."""
    if baseline_median <= 0:
        return reward <= 0
    return reward < baseline_median * FAILURE_RATIO


def median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2
