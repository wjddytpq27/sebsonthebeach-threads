"""
add_post.py — claude가 생성한 글(JSON 텍스트)을 posts.json에 '안전하게' append.

claude에게 파일을 직접 쓰게 하면 기존 예약 글을 덮어쓰는 사고가 남.
그래서 claude는 JSON 텍스트만 stdout/파일로 내보내고, 실제 posts.json 조작은
이 스크립트가 결정론적으로 담당한다:
  - 기존 글은 절대 건드리지 않고 append만
  - 오늘 같은 슬롯 글이 이미 있으면 스킵 (덮어쓰기 방지)
  - date / evening / topic 필드를 슬롯 규칙대로 세팅

사용: python3 add_post.py --slot morning|evening --infile /tmp/gen.txt
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
today = datetime.now(KST).strftime('%Y-%m-%d')

BASE_DIR = Path(__file__).resolve().parent
POSTS_FILE = BASE_DIR / 'data' / 'posts.json'

DEFAULT_TOPIC = {'morning': 'AI_THREADS', 'evening': 'BUSINESS_ENTREPENEURSHIP'}
VALID_TOPICS = {'AI_THREADS', 'BUSINESS_ENTREPENEURSHIP', 'PERSONAL_FINANCE', 'CAREERS_JOBS'}


def extract_json(text: str) -> dict:
    """claude 출력에서 JSON 객체 하나를 robust하게 추출 (코드펜스/설명 섞여도)."""
    # 코드펜스 제거
    cleaned = re.sub(r'```(?:json)?', '', text)
    # 첫 '{' ~ 마지막 '}' 까지
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start == -1 or end == -1 or end <= start:
        raise ValueError('출력에서 JSON 객체를 못 찾음')
    return json.loads(cleaned[start:end + 1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--slot', required=True, choices=['morning', 'evening'])
    ap.add_argument('--infile', required=True, help='claude 출력 텍스트 파일')
    args = ap.parse_args()

    raw = Path(args.infile).read_text(encoding='utf-8')
    try:
        data = extract_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        print(f'❌ JSON 파싱 실패: {e}\n--- 원문 앞 300자 ---\n{raw[:300]}')
        return 1

    content = (data.get('content') or '').strip()
    if not content:
        print('❌ content 비어있음 — 추가 안 함')
        return 1

    is_evening = args.slot == 'evening'
    posts = json.loads(POSTS_FILE.read_text(encoding='utf-8')) if POSTS_FILE.exists() else []

    # 중복 방지: 오늘 같은 슬롯 글이 이미 있으면 스킵 (절대 덮어쓰지 않음)
    for p in posts:
        if p.get('date') == today and bool(p.get('evening')) == is_evening:
            print(f'⏭ 오늘({today}) {args.slot} 글 이미 있음 — append 스킵 (덮어쓰기 방지)')
            return 0

    topic = data.get('topic')
    if topic not in VALID_TOPICS:
        topic = DEFAULT_TOPIC[args.slot]

    entry = {'date': today, 'content': content, 'topic': topic}
    reply = (data.get('reply') or '').strip()
    if reply:
        entry['reply'] = reply
    if is_evening:
        entry['evening'] = True

    posts.append(entry)
    POSTS_FILE.write_text(json.dumps(posts, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'✅ {today} {args.slot} 글 append 완료 (총 {len(posts)}개): {content[:40]}…')
    return 0


if __name__ == '__main__':
    sys.exit(main())
