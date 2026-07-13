"""
test_bandit.py — 밴딧 UCB·탐색/활용·금지필터 검증.
pytest 있으면 pytest로, 없으면 `python3 tests/test_bandit.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bandit as B


def _ledger(arms, estimated=True):
    for v in arms.values():
        v.setdefault('any_estimated', estimated)
        v.setdefault('failure_rate', 0.0)
        v.setdefault('follower_gain_attributed', 0)
    return {'arms': arms}


def test_banned_hook_not_viable():
    arms = {'morning|ko|news_relay|ai_general': {'n': 5, 'avg_reward': 100.0},
            'morning|ko|list|smartstore': {'n': 5, 'avg_reward': 100.0}}
    scored = B.score_arms(_ledger(arms)['arms'])
    assert all(not s['viable'] for s in scored)


def test_dead_arm_not_viable():
    arms = {'morning|ko|target_callout|smartstore': {'n': 5, 'avg_reward': 50.0, 'failure_rate': 0.6}}
    scored = B.score_arms(_ledger(arms)['arms'])
    assert scored[0]['dead'] is True and scored[0]['viable'] is False


def test_low_n_arm_gets_exploration_bonus():
    # 같은 avg_reward면 표본 적은 쪽 UCB가 더 높다 (탐색 유도)
    arms = {'morning|ko|reveal|coupang': {'n': 1, 'avg_reward': 50.0},
            'morning|ko|target_callout|smartstore': {'n': 20, 'avg_reward': 50.0}}
    scored = B.score_arms(_ledger(arms)['arms'])
    low = next(s for s in scored if s['n'] == 1)
    high = next(s for s in scored if s['n'] == 20)
    assert low['ucb'] > high['ucb']


def test_follower_gain_boosts_score():
    arms = {'morning|ko|target_callout|smartstore': {'n': 5, 'avg_reward': 50.0, 'follower_gain_attributed': 10},
            'morning|ko|reveal|coupang': {'n': 5, 'avg_reward': 50.0, 'follower_gain_attributed': 0}}
    scored = B.score_arms(_ledger(arms)['arms'])
    with_f = next(s for s in scored if s['topic_theme'] == 'smartstore')
    without = next(s for s in scored if s['topic_theme'] == 'coupang')
    assert with_f['ucb'] > without['ucb']


def test_recommend_estimated_forces_explore():
    # 라벨 추정 상태면 표본 많아도 explore (ground truth 아님)
    arms = {'morning|ko|target_callout|smartstore': {'n': 10, 'avg_reward': 100.0}}
    rec = B.recommend(_ledger(arms, estimated=True))
    assert rec['labels_estimated'] is True
    assert rec['slots']['morning']['mode'] == 'explore'


def test_recommend_exploits_when_confident():
    arms = {'morning|ko|target_callout|smartstore': {'n': 10, 'avg_reward': 100.0}}
    rec = B.recommend(_ledger(arms, estimated=False))
    assert rec['slots']['morning']['mode'] == 'exploit'
    assert rec['slots']['morning']['recommend']['topic_theme'] == 'smartstore'


def test_recommend_no_viable_arm_falls_back_to_explore():
    arms = {'morning|ko|news_relay|ai_general': {'n': 5, 'avg_reward': 100.0}}
    rec = B.recommend(_ledger(arms))
    assert rec['slots']['morning']['recommend'] is None
    assert rec['slots']['morning']['mode'] == 'explore'


def test_directive_line_shape():
    arms = {'evening|ko|reveal|ai_ecommerce': {'n': 8, 'avg_reward': 60.0}}
    rec = B.recommend(_ledger(arms, estimated=False))
    line = B.directive_line(rec, 'evening')
    assert 'evening' in line and 'reveal·ai_ecommerce' in line and 'exploit' in line


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    for fn in fns:
        fn()
        print(f'  ✓ {fn.__name__}')
    print(f'bandit: {len(fns)}/{len(fns)} passed')


if __name__ == '__main__':
    _run_all()
