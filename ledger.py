"""
ledger.py — 포스트 원장 (조인 계층)

"의도한 것"(posts.json: arm 라벨) × "일어난 것"(insights.csv: 실측 지표)
  × "결과"(follower_log.csv: 윈도우 팔로워 증감)를 post_id 기준으로 엮는다.

출력: data/post_ledger.json
  - posts: 발행글 1건 = arm + 지표 + reward + 실패여부 + 윈도우 팔로워 귀인
  - arms:  arm별 롤업(n, avg_reward, failure_rate, reach_pull, follower_gain) — 밴딧·분석 입력
  - north_star: 7일 롤링 팔로워 순증

핵심: 생성 시점 arm 라벨을 신뢰하고, 실패한 글도 전부 기록한다.
(예전 follow_attributor의 "0점 없음=성공" 생존자 편향 + ±1 노이즈 귀인 버그를 정면 교정)
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import arms
import reward as R

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime('%Y-%m-%d')

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
POSTS_FILE = DATA_DIR / 'posts.json'
INSIGHTS_FILE = DATA_DIR / 'insights.csv'
FOLLOWER_FILE = DATA_DIR / 'follower_log.csv'
OUTPUT_FILE = DATA_DIR / 'post_ledger.json'

ATTRIBUTION_WINDOW = 2   # 발행 후 며칠까지 팔로워 증감을 본다
NORTH_STAR_WINDOW = 7


def load_posts() -> list[dict]:
    if not POSTS_FILE.exists():
        return []
    return json.loads(POSTS_FILE.read_text(encoding='utf-8'))


def load_insights_latest() -> list[dict]:
    """post_id별 최신 collected_date 행만."""
    if not INSIGHTS_FILE.exists():
        return []
    latest: dict[str, dict] = {}
    with open(INSIGHTS_FILE, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            pid = r.get('post_id', '')
            if not pid:
                continue
            if pid not in latest or r.get('collected_date', '') > latest[pid].get('collected_date', ''):
                latest[pid] = r
    return list(latest.values())


def load_follower_log() -> list[dict]:
    if not FOLLOWER_FILE.exists():
        return []
    rows = []
    with open(FOLLOWER_FILE, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            try:
                rows.append({'date': r['date'], 'followers': int(r['followers'])})
            except (KeyError, ValueError):
                pass
    return rows


def _norm_prefix(text: str, n: int = 28) -> str:
    # 공백 런(스페이스·개행·\n\n 빈 줄) 전부 단일 공백으로 뭉갬 → 프리뷰/본문 정규화 일치
    return ' '.join((text or '').split())[:n].lower()


def match_post(preview: str, post_date: str, posts: list[dict]) -> dict | None:
    """insights 행의 text_preview로 posts.json 원본(arm 라벨 보유)을 찾는다."""
    key = _norm_prefix(preview)
    if not key:
        return None
    same_day = [p for p in posts if p.get('date') == post_date]
    for p in same_day + posts:          # 같은 날 우선, 없으면 전체
        if _norm_prefix(p.get('content', '')) == key:
            return p
    return None


def build_rows(posts: list[dict], insights: list[dict], follower_log: list[dict]) -> list[dict]:
    deltas = R.daily_deltas(follower_log)
    deltas_by_date = {d['date']: d['delta'] for d in deltas}
    posts_per_day: dict[str, int] = {}
    for ins in insights:
        posts_per_day[ins.get('post_date', '')] = posts_per_day.get(ins.get('post_date', ''), 0) + 1

    rows: list[dict] = []
    for ins in insights:
        metrics = {
            'likes': int(ins.get('likes', 0) or 0),
            'replies': int(ins.get('replies', 0) or 0),
            'reposts': int(ins.get('reposts', 0) or 0),
            'quotes': int(ins.get('quotes', 0) or 0),
            'views': int(ins.get('views', 0) or 0),
        }
        preview = ins.get('text_preview', '')
        post_date = ins.get('post_date', '')
        src = match_post(preview, post_date, posts)
        arm = arms.resolve_arm(src if src else {'content': preview})

        fdelta = R.window_follower_delta(post_date, deltas_by_date, ATTRIBUTION_WINDOW) if post_date else 0
        comp = R.reward_components(metrics)
        rows.append({
            'post_id': ins.get('post_id', ''),
            'post_date': post_date,
            'text_preview': preview[:60],
            'arm': arm.key(),
            'slot': arm.slot, 'lang': arm.lang,
            'hook_style': arm.hook_style, 'topic_theme': arm.topic_theme,
            'arm_estimated': arm.estimated,          # True면 라벨 없어 추정 (신뢰 낮음)
            **metrics,
            'engagement_score': int(ins.get('engagement_score', 0) or 0),
            **comp,
            'follower_delta_window': fdelta,
            'attribution_confidence': R.attribution_confidence(fdelta, posts_per_day.get(post_date, 1)),
        })
    return rows


def rollup_arms(rows: list[dict]) -> dict:
    """arm별 집계 — 밴딧 arm 통계 + growth_analyst 입력."""
    baseline = R.median([r['reward'] for r in rows]) if rows else 0.0
    groups: dict[str, list[dict]] = {}
    for r in rows:
        r['is_failure'] = R.is_failure(r['reward'], baseline)
        groups.setdefault(r['arm'], []).append(r)

    out: dict[str, dict] = {}
    for key, items in groups.items():
        n = len(items)
        rewards = [it['reward'] for it in items]
        fails = sum(1 for it in items if it['is_failure'])
        # 신뢰 높은 귀인만 팔로워 합산 (±1 노이즈 제외)
        conf_delta = sum(it['follower_delta_window'] for it in items
                         if it['attribution_confidence'] in ('high', 'medium'))
        out[key] = {
            'n': n,
            'avg_reward': round(sum(rewards) / n, 3),
            'best_reward': round(max(rewards), 3),
            'failure_rate': round(fails / n, 2),
            'reach_pull_sum': round(sum(it['reach_pull'] for it in items), 1),
            'follower_gain_attributed': conf_delta,
            'any_estimated': any(it['arm_estimated'] for it in items),
        }
    # 표본 많고 보상 높은 순
    return dict(sorted(out.items(), key=lambda kv: (kv[1]['avg_reward'], kv[1]['n']), reverse=True))


def build_ledger() -> dict:
    posts = load_posts()
    insights = load_insights_latest()
    follower_log = load_follower_log()

    rows = build_rows(posts, insights, follower_log)
    rows.sort(key=lambda r: (r['post_date'], r['reward']), reverse=True)
    arm_stats = rollup_arms(rows)

    return {
        'updated_at': TODAY,
        'north_star': R.rolling_follower_gain(follower_log, NORTH_STAR_WINDOW),
        'reward_baseline_median': round(R.median([r['reward'] for r in rows]), 3) if rows else 0.0,
        'n_posts': len(rows),
        'n_failures': sum(1 for r in rows if r.get('is_failure')),
        'arms': arm_stats,
        'posts': rows,
    }


_SLOT_KO = {'morning': '오전', 'evening': '저녁'}


def pretty_arm(key: str) -> str:
    """'morning|ko|target_callout|smartstore' → '오전·ko·target_callout·smartstore'."""
    parts = key.split('|')
    if len(parts) != 4:
        return key
    slot, lang, hook, topic = parts
    return f'{_SLOT_KO.get(slot, slot)}·{lang}·{hook}·{topic}'


def summarize(ledger: dict, min_n: int = 2) -> dict:
    """
    growth_analyst가 프롬프트·지시 생성에 쓸 다이제스트.
    신뢰·표본 게이팅: 팔로워 귀인은 신뢰 높은 것만(ledger에서 이미 필터),
    reward 위너는 n>=min_n만(n=1 요행 배제), 추정라벨 여부 명시.
    """
    arm_stats = ledger.get('arms', {})

    fa = sorted(arm_stats.items(), key=lambda kv: kv[1]['follower_gain_attributed'], reverse=True)
    best_follower = next(((k, v) for k, v in fa if v['follower_gain_attributed'] > 0), None)

    reliable = [(k, v) for k, v in arm_stats.items() if v['n'] >= min_n]  # 이미 avg_reward 내림차순
    best_reward = reliable[0] if reliable else None

    failing = [k for k, v in arm_stats.items() if v['n'] >= min_n and v['failure_rate'] >= 0.5]

    ns = ledger.get('north_star', {})
    n_posts = ledger.get('n_posts', 0)
    all_estimated = bool(arm_stats) and all(v['any_estimated'] for v in arm_stats.values())

    return {
        'north_star': ns,
        'best_follower_arm': {
            'arm': best_follower[0], 'pretty': pretty_arm(best_follower[0]),
            'follower_gain': best_follower[1]['follower_gain_attributed'],
            'n': best_follower[1]['n'],
        } if best_follower else None,
        'best_reward_arm': {
            'arm': best_reward[0], 'pretty': pretty_arm(best_reward[0]),
            'avg_reward': best_reward[1]['avg_reward'], 'n': best_reward[1]['n'],
        } if best_reward else None,
        'failing_arms': [pretty_arm(k) for k in failing],
        'n_posts': n_posts,
        'n_failures': ledger.get('n_failures', 0),
        'failure_rate': round(ledger.get('n_failures', 0) / n_posts, 2) if n_posts else 0.0,
        'labels_estimated': all_estimated,   # True면 아직 생성라벨 없음 → 해석 신중
    }


if __name__ == '__main__':
    ledger = build_ledger()
    OUTPUT_FILE.write_text(json.dumps(ledger, ensure_ascii=False, indent=2))
    ns = ledger['north_star']
    print(f"[{TODAY}] post_ledger.json 생성: {ledger['n_posts']}개 글, "
          f"실패 {ledger['n_failures']}개, 북극성 7일 순증 {ns['gain']:+d} ({ns['per_day']:+.1f}/일)")
    top = list(ledger['arms'].items())[:3]
    for key, s in top:
        print(f"  arm {key}: n={s['n']} avg_reward={s['avg_reward']} "
              f"fail={s['failure_rate']} 팔로워귀인={s['follower_gain_attributed']:+d}")
