from __future__ import annotations
"""
regen_if_blocked.py — fact_checker가 블록한 오늘 글을, 블록 사유를 피드백으로 '근거 있게' 재생성한다.
- 블록된 글 없으면 아무것도 안 함(정상 통과 케이스).
- 있으면: 사유 + viral_writer 원칙 + 트렌드로 다시 생성 → 그 자리에 교체 + fact_checked 리셋(재검증 대상).
- content.yml에서  fact_checker.py → regen_if_blocked.py → fact_checker.py  순으로 호출(1회 재시도).
설계: '블록하고 끝(그날 글 0개)'이 아니라 '거짓 부분 빼고 다시 써서 통과시킨다'.
"""
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
POSTS = BASE / 'data' / 'posts.json'
KST = timezone(timedelta(hours=9))
today = datetime.now(KST).strftime('%Y-%m-%d')

CLAUDE = 'claude'
if not shutil.which('claude'):
    for c in ('/opt/homebrew/bin/claude', '/usr/local/bin/claude'):
        if Path(c).exists():
            CLAUDE = c
            break

MAX_REGEN = 2  # 무한루프 방지: 이 횟수 넘으면 재생성 포기(블록 유지)


def grab(text: str, start: str, end: str) -> str:
    try:
        return text.split(start, 1)[1].split(end, 1)[0].strip()
    except Exception:
        return ''


def read_file(rel: str, default: str = '') -> str:
    p = BASE / rel
    return p.read_text(encoding='utf-8') if p.exists() else default


def main() -> int:
    if not POSTS.exists():
        print('  regen: posts.json 없음 — 스킵')
        return 0
    posts = json.loads(POSTS.read_text(encoding='utf-8'))
    idx = next((i for i, p in enumerate(posts)
                if p.get('date') == today and p.get('blocked')), None)
    if idx is None:
        print('  regen: 블록된 오늘 글 없음 — 스킵')
        return 0

    blocked = posts[idx]
    if blocked.get('regenerated', 0) >= MAX_REGEN:
        print(f'  regen: 재생성 {MAX_REGEN}회 도달 — 포기(블록 유지)')
        return 0

    reason = blocked.get('fact_check_reason', '근거 미확인 주장')
    slot = 'evening' if blocked.get('evening') else 'morning'
    print(f'  regen: 블록글 재생성 (사유: {reason[:90]})')

    signal = read_file('data/team_signal.json', '{}')
    trend = '{}'
    try:
        d = json.loads(read_file('data/today_trend.json', '{}'))
        trend = json.dumps({k: d.get(k) for k in
                            ('signal_applied', 'recommended_morning', 'recommended_evening', 'github_hot')},
                           ensure_ascii=False)
    except Exception:
        pass
    vw = read_file('prompts/viral_writer.txt')

    prompt = (
        vw
        + f"\n=== 참고 team_signal: {signal}"
        + f"\n=== 트렌드 소재: {trend}"
        + f"\n=== [직전 글이 fact_checker에 블록됨. 사유]: {reason}"
        + f"\n=== [지시] 위 사유의 문제(존재불명 툴/레포명·근거없는 수치·지어낸 사용사례)를 전부 제거하고, "
          f"웹으로 확인 가능한 사실 + 내 의견만으로 {slot} 슬롯 글을 다시 써라. "
          f"확신 안 서는 사실은 빼고 의견/전망으로 돌려라. 소박해도 통과되는 게 낫다. "
          f"출력은 ===CONTENT=== ===REPLY=== ===TOPIC=== ===END=== 형식만."
    )
    try:
        r = subprocess.run([CLAUDE, '-p', prompt], capture_output=True, text=True, timeout=180)
        out = r.stdout.strip()
    except Exception as e:
        print(f'  regen: 생성 실패 — 블록 유지: {e}')
        return 0

    content = grab(out, '===CONTENT===', '===REPLY===')
    if len(content) < 50:
        print('  regen: 재생성 결과 부실(<50자) — 블록 유지')
        return 0
    topic = grab(out, '===TOPIC===', '===END===').split()[0] if grab(out, '===TOPIC===', '===END===') else ''

    posts[idx]['content'] = content
    posts[idx]['reply'] = grab(out, '===REPLY===', '===TOPIC===')
    posts[idx]['topic'] = topic or posts[idx].get('topic', 'AI_THREADS')
    posts[idx]['blocked'] = False
    posts[idx]['fact_checked'] = False        # fact_checker 재검증 대상
    posts[idx]['fact_check_status'] = ''
    posts[idx]['regenerated'] = blocked.get('regenerated', 0) + 1
    POSTS.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  ✅ regen: 재생성 완료(#{posts[idx]["regenerated"]}) → fact_checker 재검증: {content[:50]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
