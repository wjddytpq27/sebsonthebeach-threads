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
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
today = datetime.now(KST).strftime('%Y-%m-%d')

BASE_DIR = Path(__file__).resolve().parent
POSTS_FILE = BASE_DIR / 'data' / 'posts.json'

DEFAULT_TOPIC = {'morning': 'AI_THREADS', 'evening': 'BUSINESS_ENTREPENEURSHIP'}
VALID_TOPICS = {'AI_THREADS', 'BUSINESS_ENTREPENEURSHIP', 'PERSONAL_FINANCE', 'CAREERS_JOBS'}


def parse_sections(text: str) -> dict:
    """구분자 기반 파싱. content 안에 따옴표/개행이 있어도 안 깨진다.

    기대 형식:
      ===CONTENT===
      (본문)
      ===REPLY===
      (첫댓글, 비어도 됨)
      ===TOPIC===
      (토픽)
      ===END===
    """
    def grab(start_tag: str, end_tag: str) -> str:
        s = text.find(start_tag)
        if s == -1:
            return ''
        s += len(start_tag)
        e = text.find(end_tag, s)
        if e == -1:
            e = len(text)
        return text[s:e].strip()

    content = grab('===CONTENT===', '===REPLY===')
    reply = grab('===REPLY===', '===TOPIC===')
    topic = grab('===TOPIC===', '===END===')
    if not topic:  # ===END=== 누락 대비
        topic = grab('===TOPIC===', '\n\n')
    return {'content': content, 'reply': reply, 'topic': topic.split()[0] if topic else ''}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--slot', required=True, choices=['morning', 'evening'])
    ap.add_argument('--infile', required=True, help='claude 출력 텍스트 파일')
    args = ap.parse_args()

    raw = Path(args.infile).read_text(encoding='utf-8')
    data = parse_sections(raw)

    content = (data.get('content') or '').strip()
    if not content:
        print(f'❌ content 비어있음 — 추가 안 함\n--- 원문 앞 400자 ---\n{raw[:400]}')
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
