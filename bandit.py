"""
bandit.py — Phase 2 실험 레이어 (arms + reward + ledger 위)

목적: 'X한테만·smartstore' 니치 하나에 박제되지 않도록, 슬롯별로 무슨 arm을
     밀지(활용) vs 새로 시험할지(탐색)를 결정한다. 이게 진짜 "자가강화"(RL) 부분.

방식: UCB1 (avg_reward 정규화 + 탐색보너스 c·√(ln N / n)).
  - 결정론적(재현가능, Math.random 불필요) + 표본 얇은 arm에 자동 가산점 → 탐색 유도.
  - 팔로워 귀인(+) arm에 보너스: 북극성=팔로워 순증이므로.
  - 죽은 arm(실패율≥0.5)·금지 훅(news_relay/list) 제외.
  - 라벨 추정 상태면 활용 강도↓·탐색↑ (아직 ground truth 아님).

상태 없음: ledger arm 롤업이 소스에서 매번 누적 재생성되므로 밴딧은 그 함수로 stateless.
"""
from __future__ import annotations

import math

BANNED_HOOKS = {'news_relay', 'list'}     # 과거 성과 0 — 후보에서 원천 제외
DEAD_FAILURE_RATE = 0.5                    # 실패율 이 이상이면 죽은 arm
EXPLORE_C = 0.7                            # UCB 탐색 계수 (너무 크면 잡음 arm이 북극성 신호를 덮음)
MIN_EXPLOIT_N = 3                          # 이 표본 미만이면 신뢰 부족 → explore 취급
FOLLOWER_WEIGHT = 1.0                      # 팔로워 귀인 보너스(최대 귀인 대비 비례) — 북극성이라 강하게

_ARM_FIELDS = ('slot', 'lang', 'hook_style', 'topic_theme')


def parse_arm(key: str) -> dict:
    return dict(zip(_ARM_FIELDS, key.split('|')))


def _viable(key: str, stat: dict) -> bool:
    a = parse_arm(key)
    if a.get('hook_style') in BANNED_HOOKS:
        return False
    if stat.get('failure_rate', 0) >= DEAD_FAILURE_RATE:
        return False
    return True


def score_arms(arm_stats: dict) -> list[dict]:
    """관측된 arm에 UCB 점수 부여. 높은 순 정렬."""
    if not arm_stats:
        return []
    total_n = sum(v['n'] for v in arm_stats.values()) or 1
    max_reward = max((v['avg_reward'] for v in arm_stats.values()), default=0) or 1.0
    max_follower = max((v.get('follower_gain_attributed', 0) for v in arm_stats.values()), default=0)

    scored = []
    for key, v in arm_stats.items():
        n = max(v['n'], 1)
        norm_reward = v['avg_reward'] / max_reward                 # [0,1]
        explore = EXPLORE_C * math.sqrt(math.log(total_n + 1) / n)
        # 팔로워 귀인은 북극성 → 최대 귀인 대비 비례 보너스 (+91이 +4보다 훨씬 크게)
        fg = v.get('follower_gain_attributed', 0)
        follower = FOLLOWER_WEIGHT * (fg / max_follower) if (max_follower > 0 and fg > 0) else 0.0
        scored.append({
            'arm': key, **parse_arm(key),
            'n': v['n'], 'avg_reward': v['avg_reward'],
            'follower_gain': v.get('follower_gain_attributed', 0),
            'failure_rate': v.get('failure_rate', 0),
            'ucb': round(norm_reward + explore + follower, 3),
            'viable': _viable(key, v),
            'dead': v.get('failure_rate', 0) >= DEAD_FAILURE_RATE,
        })
    return sorted(scored, key=lambda s: s['ucb'], reverse=True)


def _frontier(scored: list[dict], slot: str, chosen: set) -> list[dict]:
    """탐색 프론티어: 같은 슬롯에서 아직 덜 시험된(n<MIN) viable arm 후보."""
    out = []
    for s in scored:
        if s['slot'] != slot or not s['viable'] or s['arm'] in chosen:
            continue
        if s['n'] < MIN_EXPLOIT_N or s['follower_gain'] > 0:
            out.append(s)
    return out[:3]


def recommend(ledger: dict) -> dict:
    """슬롯별 추천 arm + 모드(exploit/explore) + 탐색 후보."""
    arm_stats = ledger.get('arms', {})
    estimated = bool(arm_stats) and all(v.get('any_estimated') for v in arm_stats.values())
    scored = score_arms(arm_stats)

    slots: dict[str, dict] = {}
    for slot in ('morning', 'evening'):
        cands = [s for s in scored if s['slot'] == slot and s['viable']]
        if not cands:
            slots[slot] = {
                'recommend': None, 'mode': 'explore',
                'reason': f'{slot} 관측 viable arm 없음 — 새 각도 자유 시험',
                'frontier': [],
            }
            continue
        top = cands[0]
        # 신뢰 표본 + ground truth면 exploit, 아니면 explore
        exploit = top['n'] >= MIN_EXPLOIT_N and not estimated
        mode = 'exploit' if exploit else 'explore'
        combo = f"{top['hook_style']}·{top['topic_theme']}"
        if exploit:
            reason = (f"{combo} 활용 (avg_reward {top['avg_reward']}, "
                      f"n={top['n']}, 팔로워귀인 {top['follower_gain']:+d})")
        else:
            why = '라벨 추정 상태' if estimated else f"표본 부족(n={top['n']})"
            reason = f"{combo} 우세하나 {why} → 탐색 병행"
        slots[slot] = {
            'recommend': {'hook_style': top['hook_style'], 'topic_theme': top['topic_theme'],
                          'lang': top['lang']},
            'mode': mode, 'score': top['ucb'], 'reason': reason,
            'frontier': [{'hook_style': f['hook_style'], 'topic_theme': f['topic_theme'],
                          'n': f['n']} for f in _frontier(scored, slot, {top['arm']})],
        }

    return {
        'labels_estimated': estimated,
        'slots': slots,
        'arm_scores': scored[:10],
    }


def directive_line(rec: dict, slot: str) -> str:
    """viral_writer 프롬프트에 넣을 한 줄 지시."""
    s = rec['slots'].get(slot)
    if not s or not s['recommend']:
        return f'{slot}: 새 각도 자유 시험 (관측 데이터 부족)'
    r = s['recommend']
    base = f"{slot}: [{s['mode']}] {r['hook_style']}·{r['topic_theme']}·{r['lang']} 우선 — {s['reason']}"
    if s['mode'] == 'explore' and s['frontier']:
        alts = ', '.join(f"{f['hook_style']}·{f['topic_theme']}" for f in s['frontier'])
        base += f" | 대조군 후보: {alts}"
    return base
