"""
test_reward.py — reward.py 순수 함수 검증.
pytest 있으면 pytest로, 없으면 `python3 tests/test_reward.py`로도 실행.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import reward as R


def test_follow_intent_weights_reposts_over_likes():
    # Arrange: 같은 개수라도 리포스트가 좋아요보다 무겁다
    likes_only = {'likes': 10, 'replies': 0, 'reposts': 0, 'quotes': 0}
    reposts_only = {'likes': 0, 'replies': 0, 'reposts': 10, 'quotes': 0}
    # Act / Assert
    assert R.follow_intent(reposts_only) > R.follow_intent(likes_only)


def test_post_reward_is_view_normalized():
    # 동일 의도, 도달 2배면 rate는 절반
    low_reach = {'likes': 4, 'replies': 2, 'reposts': 0, 'quotes': 0, 'views': 1000}
    high_reach = {'likes': 4, 'replies': 2, 'reposts': 0, 'quotes': 0, 'views': 2000}
    assert R.post_reward(low_reach) == round(R.post_reward(high_reach) * 2, 3)


def test_post_reward_zero_views_is_zero():
    assert R.post_reward({'likes': 5, 'replies': 5, 'views': 0}) == 0.0


def test_view_floor_prevents_rate_explosion():
    # views가 하한(200) 미만이면 하한으로 나눈다 → 소량 도달 튐 방지
    tiny = {'likes': 0, 'replies': 10, 'reposts': 0, 'quotes': 0, 'views': 5}
    expected = round(R.follow_intent(tiny) / R.VIEW_FLOOR * 1000, 3)
    assert R.post_reward(tiny) == expected


def test_rolling_follower_gain_basic():
    log = [{'date': '2026-06-24', 'followers': 250},
           {'date': '2026-06-25', 'followers': 255},
           {'date': '2026-06-26', 'followers': 257}]
    g = R.rolling_follower_gain(log, window=7)
    assert g['gain'] == 7 and g['last'] == 257 and g['days'] == 2


def test_rolling_follower_gain_window_clips():
    log = [{'date': f'2026-06-{d:02d}', 'followers': 100 + d} for d in range(1, 21)]
    g = R.rolling_follower_gain(log, window=7)
    assert g['days'] == 7 and g['gain'] == 7


def test_window_follower_delta_sums_next_days():
    deltas = {'2026-06-25': 3, '2026-06-26': -1}
    # 06-24 발행 → 25, 26 합 = 2
    assert R.window_follower_delta('2026-06-24', deltas, window=2) == 2


def test_attribution_confidence_noise_band_is_low():
    # ±1은 노이즈 → 무조건 low (예전 버그: +1을 high로 착각)
    assert R.attribution_confidence(1, posts_same_day=1) == 'low'
    assert R.attribution_confidence(-1, posts_same_day=1) == 'low'


def test_attribution_confidence_strong_single_post():
    assert R.attribution_confidence(5, posts_same_day=1) == 'high'


def test_attribution_confidence_shared_day_downgrades():
    assert R.attribution_confidence(5, posts_same_day=3) == 'medium'


def test_is_failure_relative_to_median():
    # 중앙값 10, 임계 0.35 → 3.5 미만이면 실패
    assert R.is_failure(3.0, baseline_median=10.0) is True
    assert R.is_failure(4.0, baseline_median=10.0) is False


def test_is_failure_zero_baseline():
    assert R.is_failure(0.0, baseline_median=0.0) is True
    assert R.is_failure(0.1, baseline_median=0.0) is False


def test_median_even_odd():
    assert R.median([1, 2, 3]) == 2
    assert R.median([1, 2, 3, 4]) == 2.5
    assert R.median([]) == 0.0


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f'  ✓ {fn.__name__}')
    print(f'reward: {passed}/{len(fns)} passed')


if __name__ == '__main__':
    _run_all()
