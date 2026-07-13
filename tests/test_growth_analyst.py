"""
test_growth_analyst.py — ledger 통합 부분만 격리 검증 (라이브 부작용 없음).
build_ledger_block(순수) + sync 정규식 멱등성.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import growth_analyst as GA


def _digest(estimated=False):
    return {
        'north_star': {'gain': 5, 'per_day': 0.7},
        'best_follower_arm': {'arm': 'morning|ko|target_callout|smartstore',
                              'pretty': '오전·ko·target_callout·smartstore',
                              'follower_gain': 91, 'n': 3},
        'best_reward_arm': {'arm': 'morning|ko|target_callout|amazon',
                            'pretty': '오전·ko·target_callout·amazon',
                            'avg_reward': 412.1, 'n': 2},
        'failing_arms': ['저녁·ko·news_relay·ai_general'],
        'n_posts': 42, 'n_failures': 15, 'failure_rate': 0.36,
        'labels_estimated': estimated,
    }


def test_ledger_block_empty_when_none():
    assert GA.build_ledger_block(None) == ''


def test_ledger_block_contains_follower_arm_and_northstar():
    block = GA.build_ledger_block(_digest())
    assert '북극성' in block
    assert 'target_callout·smartstore' in block   # 팔로워 위너
    assert '+91' in block
    assert 'news_relay' in block                    # 죽은 arm
    assert '팔로워 arm' in block                     # 팔로워 우선 지시


def test_ledger_block_flags_estimated():
    assert '잠정적' in GA.build_ledger_block(_digest(estimated=True))
    assert '잠정적' not in GA.build_ledger_block(_digest(estimated=False))


def test_sync_regex_idempotent_with_subsection():
    """성과 데이터 섹션(### 서브섹션 포함)이 다음 실행 때 통째로 교체되는지."""
    # Arrange: 성과 데이터 안에 ### 서브섹션이 있는 문서
    doc = (
        "# 헤더\n\n"
        "## 성과 데이터 (2026-06-30 자동 업데이트)\n\n"
        "잘 된 스타일: X\n"
        "### 팔로워 순증 기준 (원장)\n"
        "7일 순증 +5\n죽은 arm: 없음\n\n"
        "## 포맷 — 슬롯별 선택\n본문 유지\n"
    )
    new_section = "## 성과 데이터 (2026-07-01 자동 업데이트)\n\n새 내용\n### 팔로워 순증 기준 (원장)\n갱신됨\n"
    # Act
    updated = re.sub(r'## 성과 데이터.*?(?=\n## |\Z)', new_section + '\n\n', doc, flags=re.DOTALL)
    # Assert: 옛 성과 데이터·옛 서브섹션은 사라지고, 포맷 섹션은 보존
    assert '2026-06-30' not in updated
    assert '2026-07-01' in updated
    assert updated.count('## 성과 데이터') == 1        # 중복 안 생김
    assert '## 포맷 — 슬롯별 선택' in updated           # 뒷 섹션 보존
    assert '본문 유지' in updated


def test_sync_regex_preserves_output_schema_section():
    """실제 viral_writer.txt에서 성과 데이터 교체가 출력형식/arm라벨 섹션을 안 건드리는지."""
    vf = Path(__file__).resolve().parent.parent / 'prompts' / 'viral_writer.txt'
    if not vf.exists():
        return
    content = vf.read_text(encoding='utf-8')
    updated = re.sub(r'## 성과 데이터.*?(?=\n## |\Z)', "## 성과 데이터\n새거\n\n", content, flags=re.DOTALL)
    # 출력 형식·arm 라벨 규칙은 성과 데이터 뒤에 있으므로 보존돼야 함
    if '## 출력 형식' in content:
        assert '## 출력 형식' in updated
        assert 'hook_style' in updated
        assert 'arm 라벨 규칙' in updated


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    for fn in fns:
        fn()
        print(f'  ✓ {fn.__name__}')
    print(f'growth_analyst: {len(fns)}/{len(fns)} passed')


if __name__ == '__main__':
    _run_all()
