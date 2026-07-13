"""
test_arms.py — arm 분류(라벨 신뢰 + 휴리스틱 폴백) 검증.
pytest 있으면 pytest로, 없으면 `python3 tests/test_arms.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import arms


def test_label_is_trusted_over_heuristic():
    # content는 뉴스처럼 보여도 라벨이 reveal이면 라벨을 따른다
    post = {'slot': 'morning', 'content': 'OpenAI가 새 모델 발표했음',
            'hook_style': 'reveal', 'topic_theme': 'ai_ecommerce', 'lang': 'ko'}
    arm = arms.resolve_arm(post)
    assert arm.hook_style == 'reveal'
    assert arm.topic_theme == 'ai_ecommerce'
    assert arm.estimated is False


def test_missing_label_falls_back_to_estimate():
    post = {'slot': 'morning',
            'content': '스마트스토어 셀러들한테만 함. 상품명 키워드 다 박는 게 공식인 줄 알았음'}
    arm = arms.resolve_arm(post)
    assert arm.estimated is True
    assert arm.topic_theme == 'smartstore'
    assert arm.hook_style == 'target_callout'


def test_invalid_label_normalizes_to_other():
    post = {'slot': 'evening', 'content': 'x', 'hook_style': 'ZZZ', 'topic_theme': 'ZZZ'}
    arm = arms.resolve_arm(post)
    assert arm.hook_style == 'other' and arm.topic_theme == 'other'


def test_detect_lang_english_post():
    assert arms.detect_lang('Solo Amazon sellers still saving up for a photographer') == 'en'


def test_detect_lang_korean_post():
    assert arms.detect_lang('아마존 셀러한테만. 내가 올린 적 없는 상품에 주문이 들어왔음') == 'ko'


def test_ai_without_ecommerce_is_general():
    # AI만 언급, 셀러/쇼핑 마커 없음 → ai_general (위험 신호)
    assert arms.guess_topic_theme('ChatGPT로 글쓰기 자동화해봤음') == 'ai_general'


def test_platform_proper_noun_wins_over_ai():
    # 플랫폼 고유명사가 있으면 그게 주제 (검색 유입 전략과 일치). AI는 수단.
    assert arms.guess_topic_theme('자사몰 CS를 AI 에이전트로 자동화했더니 셀러 일이 줄었음') == 'own_mall'


def test_ai_with_ecommerce_marker_is_crossover():
    # 플랫폼 고유명사 없이 이커머스 마커 + AI → 교차 주제
    assert arms.guess_topic_theme('쇼핑몰 상세페이지 카피를 AI한테 맡겼더니 매출이 이렇게 됐음') == 'ai_ecommerce'


def test_slot_from_evening_flag():
    arm = arms.resolve_arm({'evening': True, 'content': '테스트'})
    assert arm.slot == 'evening'


def test_arm_key_stable():
    a = arms.Arm('morning', 'ko', 'target_callout', 'smartstore', False)
    assert a.key() == 'morning|ko|target_callout|smartstore'


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f'  ✓ {fn.__name__}')
    print(f'arms: {passed}/{len(fns)} passed')


if __name__ == '__main__':
    _run_all()
