"""
매일 KST 08:30 — 오늘 댓글 달 타겟 브리프 Slack 발송
전략: 팔로워 많은 계정 최신 포스트에 빠르게 달기 = 노출 극대화
"""
import os, json, requests, random
from datetime import datetime, timezone, timedelta
from pathlib import Path

SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK', '')
if not SLACK_WEBHOOK:
    _cfg = Path('/Users/uneedcomms/thread/data/slack_config.json')
    if _cfg.exists():
        SLACK_WEBHOOK = json.loads(_cfg.read_text()).get('webhook_url', '')
KST = timezone(timedelta(hours=9))
today = datetime.now(KST).strftime('%Y-%m-%d (%a)')

# 검색 기반 타겟 — 특정 계정 하드코딩 없음
SEARCH_TARGETS = [
    {
        "label": "AI 실무 활용",
        "url": "https://www.threads.com/search?q=AI활용",
        "angle": "포스트 내 구체적 주장에 실무 경험으로 보완 또는 반박",
    },
    {
        "label": "ChatGPT/Claude 활용",
        "url": "https://www.threads.com/search?q=ChatGPT활용",
        "angle": "도구 비교나 한계점에 대해 실제로 써본 입장 댓글",
    },
    {
        "label": "AI 자동화",
        "url": "https://www.threads.com/search?q=자동화",
        "angle": "자동화 도입 경험담이나 함정 포인트 보완",
    },
    {
        "label": "퍼스널브랜딩",
        "url": "https://www.threads.com/search?q=퍼스널브랜딩",
        "angle": "마케팅 퍼널 관점에서 구체적 액션 추가",
    },
    {
        "label": "콘텐츠마케팅",
        "url": "https://www.threads.com/search?q=콘텐츠마케팅",
        "angle": "데이터/전환율 관점에서 빠진 부분 지적",
    },
    {
        "label": "스타트업/1인기업",
        "url": "https://www.threads.com/search?q=1인기업",
        "angle": "AI 툴로 어떻게 효율화했는지 경험 연결",
    },
    {
        "label": "영어권 AI tools",
        "url": "https://www.threads.com/search?q=AI+tools",
        "angle": "hands-on practitioner angle, add what's missing or counter the hype",
    },
    {
        "label": "영어권 marketing automation",
        "url": "https://www.threads.com/search?q=marketing+automation",
        "angle": "real implementation perspective, specific numbers or edge cases",
    },
    {
        "label": "바이브코딩/노코드",
        "url": "https://www.threads.com/search?q=바이브코딩",
        "angle": "실제 한계나 놓치는 부분 짚어주기",
    },
    {
        "label": "디지털마케팅",
        "url": "https://www.threads.com/search?q=디지털마케팅",
        "angle": "CRM/퍼널 관점에서 구체적 데이터 연결",
    },
]

# 매일 랜덤 5개 선택
daily_targets = random.sample(SEARCH_TARGETS, 5)

lines = [
    f"🎯 *오늘의 engagement 브리프* ({today})",
    "",
    "댓글 = 포스팅만큼 노출 가치 있음. 오늘 5개, 5분.",
    "",
]

for i, t in enumerate(daily_targets, 1):
    lines.append(f"*{i}. {t['label']}*")
    lines.append(f"   🔗 {t['url']}")
    lines.append(f"   💬 {t['angle']}")
    lines.append("")

lines += [
    "━━━━━━━━━━━━━━",
    "• 포스팅 후 1시간 내 댓글 = 노출 3배",
    "• 포스트 내 특정 문장 직접 인용할 것",
    "• '좋아요!' '맞아요' 금지 — 안 단 것만 못함",
]

if SLACK_WEBHOOK:
    requests.post(SLACK_WEBHOOK, json={
        "text": "\n".join(lines),
        "username": "📊 thread (this Mac • verified)",
        "icon_emoji": ":dart:",
    })
    print("브리프 발송 완료")
else:
    print("\n".join(lines))
