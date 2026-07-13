"""
test_ledger.py — 조인·롤업 검증 (파일 I/O 없이 인메모리).
pytest 있으면 pytest로, 없으면 `python3 tests/test_ledger.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ledger as L


def _posts():
    return [
        {'date': '2026-06-24', 'slot': 'morning',
         'content': '바이브코딩, 지금도 믿고 있어?\nAI로 빠르게 코드 뽑는 건 맞음',
         'hook_style': 'contrarian', 'topic_theme': 'ai_general', 'lang': 'ko'},
        {'date': '2026-06-25', 'slot': 'evening',
         'content': '아마존 셀러한테만. 내가 올린 적 없는 상품에 주문이 들어왔음',
         'hook_style': 'target_callout', 'topic_theme': 'amazon', 'lang': 'ko'},
    ]


def _insights():
    return [
        {'post_id': 'p1', 'post_date': '2026-06-24', 'text_preview': '바이브코딩, 지금도 믿고 있어?  AI로 빠르게 코드 뽑는 건 맞음',
         'likes': 44, 'replies': 57, 'reposts': 4, 'quotes': 0, 'views': 3652, 'engagement_score': 235},
        {'post_id': 'p2', 'post_date': '2026-06-25', 'text_preview': '아마존 셀러한테만. 내가 올린 적 없는 상품에 주문이 들어왔음',
         'likes': 2, 'replies': 0, 'reposts': 0, 'quotes': 0, 'views': 400, 'engagement_score': 2},
    ]


def _followers():
    return [
        {'date': '2026-06-24', 'followers': 250},
        {'date': '2026-06-25', 'followers': 258},  # +8 (24일 글 귀인, 신뢰 high)
        {'date': '2026-06-26', 'followers': 258},  # +0
    ]


def test_join_uses_ground_truth_labels():
    rows = L.build_rows(_posts(), _insights(), _followers())
    by_id = {r['post_id']: r for r in rows}
    assert by_id['p1']['hook_style'] == 'contrarian'   # 라벨 신뢰
    assert by_id['p1']['arm_estimated'] is False
    assert by_id['p2']['topic_theme'] == 'amazon'


def test_unmatched_insight_falls_back_to_estimate():
    # posts.json에 없는 옛날 글도 원장에 남되 추정 표시
    orphan = _insights() + [{'post_id': 'p9', 'post_date': '2026-06-01',
                             'text_preview': '스마트스토어 셀러들한테만 함',
                             'likes': 1, 'replies': 0, 'reposts': 0, 'quotes': 0,
                             'views': 300, 'engagement_score': 1}]
    rows = L.build_rows(_posts(), orphan, _followers())
    p9 = next(r for r in rows if r['post_id'] == 'p9')
    assert p9['arm_estimated'] is True
    assert p9['topic_theme'] == 'smartstore'


def test_failure_recorded_not_hidden():
    # 저성과 글도 기록되고 is_failure로 표시됨 (생존자 편향 제거)
    rows = L.build_rows(_posts(), _insights(), _followers())
    L.rollup_arms(rows)   # is_failure 부여
    flops = [r for r in rows if r['is_failure']]
    assert len(flops) >= 1                     # p2가 중앙값 대비 미달
    assert any(r['post_id'] == 'p2' for r in flops)


def test_high_reward_post_beats_high_engagement_confusion():
    # p1은 조회 대비 의도(댓글 57)가 강함 → reward 높음
    rows = L.build_rows(_posts(), _insights(), _followers())
    by_id = {r['post_id']: r for r in rows}
    assert by_id['p1']['reward'] > by_id['p2']['reward']


def test_attribution_only_counts_confident_deltas():
    rows = L.build_rows(_posts(), _insights(), _followers())
    stats = L.rollup_arms(rows)
    # 24일 글(+8 다음날) arm은 신뢰 귀인, 25일 글(+0)은 노이즈로 0
    contrarian = stats['morning|ko|contrarian|ai_general']
    assert contrarian['follower_gain_attributed'] == 8


def test_north_star_and_baseline_present():
    rows = L.build_rows(_posts(), _insights(), _followers())
    stats = L.rollup_arms(rows)
    assert len(stats) == 2
    assert all('avg_reward' in v for v in stats.values())


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f'  ✓ {fn.__name__}')
    print(f'ledger: {passed}/{len(fns)} passed')


if __name__ == '__main__':
    _run_all()
