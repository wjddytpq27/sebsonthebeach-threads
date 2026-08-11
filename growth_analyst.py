"""
growth_analyst.py — 성과 분석 + 팀 신호 생성
매일 22:30 실행 (track.py 이후)

출력:
- data/team_signal.json   ← 팀 전체가 읽는 공유 브리핑
- data/growth_strategy.json ← viral-writer 전략 (team_signal 서브셋)
- Slack 알림

team_signal.json 구조:
{
  "status": "normal|stall|emergency",
  "days_since_growth": 3,
  "follower_trend": "150→153 (5일, 일평균 +0.6)",
  "best_performing": { "style": "...", "avg_score": 18.0, "example": "..." },
  "worst_performing": { "style": "...", "avg_score": 0.5 },
  "keyword_performance": { "AI활용": {"comments": 5, "growth_days_after": 2} },
  "directives": {
    "trend_scout": "구체적 지시",
    "viral_writer": "구체적 지시",
    "hunter_engager": "구체적 지시"
  },
  "updated_at": "2026-05-25"
}
"""
from __future__ import annotations  # 3.9(cron /usr/bin/python3)에서 `dict | None` 어노테이션 크래시 방지

import csv, json, os, shutil, subprocess, sys, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import ledger  # 포스트 원장: post-side arm 진실(팔로워 귀인·실패율). follow_attributor 대체.
import bandit  # Phase 2 실험 레이어: 슬롯별 arm 탐색/활용 배분 (니치 박제 탈출)
import session_health  # 댓글 세션 유효성 — 죽으면 브리핑 최상단 🔴 (16일 침묵 사고 재발방지)

KST = timezone(timedelta(hours=9))
today = datetime.now(KST).strftime('%Y-%m-%d')

# 로컬·클라우드 양쪽 동작: 스크립트 기준 상대경로
BASE_DIR       = Path(__file__).resolve().parent
DATA_DIR       = BASE_DIR / 'data'
INSIGHTS_FILE  = DATA_DIR / 'insights.csv'
FOLLOWER_FILE  = DATA_DIR / 'follower_log.csv'
ENGAGE_LOG     = DATA_DIR / 'engage_log.csv'
SIGNAL_FILE    = DATA_DIR / 'team_signal.json'
STRATEGY_FILE  = DATA_DIR / 'growth_strategy.json'
SLACK_CONFIG   = DATA_DIR / 'slack_config.json'
BRIEFING_SENT  = DATA_DIR / '.briefing_sent'
# 로컬은 절대경로, 클라우드(Actions)는 PATH의 claude
CLAUDE_BIN     = os.environ.get('CLAUDE_BIN') or shutil.which('claude') or '/opt/homebrew/bin/claude'


def already_briefed_today() -> bool:
    return BRIEFING_SENT.exists() and BRIEFING_SENT.read_text().strip() == today


def mark_briefed():
    BRIEFING_SENT.write_text(today)


def send_slack(msg: str):
    webhook = ''
    try:
        if SLACK_CONFIG.exists():
            webhook = json.loads(SLACK_CONFIG.read_text()).get('webhook_url', '')
        if not webhook:
            webhook = os.environ.get('SLACK_WEBHOOK', '')
        if not webhook:
            return
        payload = {
            'text': msg,
            'username': '📊 thread (this Mac • verified)',
            'icon_emoji': ':bar_chart:',
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            webhook, data=data, headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req)
    except Exception as e:
        print(f'  슬랙 실패: {e}')


def load_follower_history(days: int = 21) -> list[dict]:
    if not FOLLOWER_FILE.exists():
        return []
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime('%Y-%m-%d')
    with open(FOLLOWER_FILE, encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f) if r.get('date', '') >= cutoff]
    return sorted(rows, key=lambda x: x['date'])


def load_post_insights(days: int = 14) -> list[dict]:
    if not INSIGHTS_FILE.exists():
        return []
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime('%Y-%m-%d')
    # post_id별 가장 최근 collected_date 데이터만 사용
    latest: dict = {}
    with open(INSIGHTS_FILE, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            pid = r.get('post_id', '')
            if not pid or r.get('post_date', '') < cutoff:
                continue
            if pid not in latest or r.get('collected_date', '') > latest[pid].get('collected_date', ''):
                latest[pid] = r
    return sorted(latest.values(), key=lambda x: x.get('post_date', ''))


def detect_status(follower_history: list[dict]) -> tuple[str, int, str]:
    """팔로워 추이 → status 결정. (status, days_since_growth, reason)"""
    if len(follower_history) < 2:
        return 'normal', 0, '데이터 부족'

    counts = [(r['date'], int(r['followers'])) for r in follower_history]

    # 최근 마지막으로 팔로워가 늘었던 날 찾기
    days_since_growth = 0
    for i in range(len(counts) - 1, 0, -1):
        if counts[i][1] > counts[i - 1][1]:
            break
        days_since_growth += 1

    first, last = counts[0][1], counts[-1][1]
    period = len(counts)
    daily_avg = round((last - first) / max(period - 1, 1), 2)
    trend_str = f'{first}→{last} ({period}일, 일평균 {daily_avg:+.1f})'

    # days_since_growth=0 → 오늘 성장함. "0일째 변화 없음" 문구 방지용으로 여기서 덮어씀
    if days_since_growth == 0:
        trend_str = f'{first}→{last} ({period}일, 일평균 {daily_avg:+.1f}) — 오늘 성장 확인'

    if days_since_growth >= 5:
        return 'emergency', days_since_growth, trend_str
    elif days_since_growth >= 3:
        return 'stall', days_since_growth, trend_str
    else:
        return 'normal', days_since_growth, trend_str


def analyze_keyword_performance(follower_history: list[dict]) -> dict:
    """
    engage_log.csv 키워드 × follower_log.csv 성장일 상관관계.
    어떤 키워드로 댓글 달았을 때 다음날 팔로워가 늘었나?
    """
    if not ENGAGE_LOG.exists() or len(follower_history) < 2:
        return {}

    # 팔로워 증가일 set
    growth_days = set()
    for i in range(1, len(follower_history)):
        if int(follower_history[i]['followers']) > int(follower_history[i - 1]['followers']):
            growth_days.add(follower_history[i]['date'])

    # 키워드별 댓글 날짜 집계
    keyword_days: dict[str, set] = {}
    with open(ENGAGE_LOG, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            kw = row.get('keyword', '').strip()
            date = row.get('date', '').strip()
            if kw and date:
                keyword_days.setdefault(kw, set()).add(date)

    result = {}
    for kw, days in keyword_days.items():
        growth_after = sum(
            1 for d in days
            if (datetime.strptime(d, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d') in growth_days
        )
        result[kw] = {
            'comment_days': len(days),
            'growth_days_after': growth_after,
            'hit_rate': round(growth_after / len(days), 2) if days else 0,
        }

    # hit_rate 기준 정렬
    return dict(sorted(result.items(), key=lambda x: x[1]['hit_rate'], reverse=True))


def analyze_posts(posts: list[dict]) -> tuple[dict, dict]:
    """상위/하위 포스트 패턴 분석. (best, worst)"""
    if not posts:
        return {}, {}

    scored = sorted(posts, key=lambda x: int(x.get('engagement_score', 0)), reverse=True)
    top3 = scored[:3]
    bottom3 = [p for p in scored[-3:] if int(p.get('engagement_score', 0)) == 0]

    top_avg = round(sum(int(p['engagement_score']) for p in top3) / len(top3), 1) if top3 else 0
    bot_avg = round(sum(int(p['engagement_score']) for p in bottom3) / len(bottom3), 1) if bottom3 else 0

    best = {
        'avg_score': top_avg,
        'examples': [p['text_preview'][:60] for p in top3],
    }
    worst = {
        'avg_score': bot_avg,
        'count': len(bottom3),
    }
    return best, worst


CLI_ERROR_PATTERNS = [
    'not logged in', 'please run', '/login', 'authentication',
    'unauthorized', 'log in', 'sign in', 'session expired',
]


def is_cli_auth_error(output: str) -> bool:
    return any(p in output.lower() for p in CLI_ERROR_PATTERNS)


def build_ledger_block(ledger_digest: dict | None) -> str:
    """포스트 원장 다이제스트 → LLM 프롬프트용 팩트 블록. 팔로워 순증이 북극성."""
    if not ledger_digest:
        return ''
    ns = ledger_digest['north_star']
    bf = ledger_digest['best_follower_arm']
    br = ledger_digest['best_reward_arm']
    fails = ledger_digest['failing_arms']
    est = ' (⚠️ 생성라벨 아직 없음 — 휴리스틱 추정이라 잠정적, 과회전 금지)' if ledger_digest['labels_estimated'] else ''

    parts = [
        f"\n[포스트 원장 — 팔로워 순증 기준 진실{est}]",
        f"- 7일 팔로워 순증: {ns.get('gain', 0):+d} ({ns.get('per_day', 0):+.1f}/일) ← 북극성, 이게 목표",
        f"- 실패(중앙값 대비 미달) 비율: {ledger_digest['failure_rate']} "
        f"({ledger_digest['n_failures']}/{ledger_digest['n_posts']})",
    ]
    if bf:
        parts.append(f"- 실제 팔로워 끈 arm: {bf['pretty']} (+{bf['follower_gain']}, n={bf['n']})")
    if br:
        parts.append(f"- 인게이지 rate 위너 arm: {br['pretty']} (reward {br['avg_reward']}, n={br['n']})")
    parts.append(f"- 죽은 arm(실패율≥50%): {', '.join(fails) if fails else '없음'}")
    parts.append("→ 팔로워 arm과 인게이지 arm이 다르면 '팔로워 arm'을 신뢰(목표는 좋아요가 아니라 팔로워 순증).")
    return '\n'.join(parts)


def generate_team_signal(
    status: str,
    days_since_growth: int,
    follower_trend: str,
    best: dict,
    worst: dict,
    kw_performance: dict,
    ledger_digest: dict | None = None,
    bandit_rec: dict | None = None,
) -> dict:
    """Claude sonnet으로 팀 신호 + 에이전트별 지시 생성"""

    top_kws = list(kw_performance.keys())[:5]
    # 키워드 노이즈 게이트: n<3 단발 데이터는 hit_rate가 요행(1.0 남발)이라 제외
    reliable_kw = [(k, v) for k, v in kw_performance.items() if v.get('comment_days', 0) >= 3]
    kw_summary = ', '.join(
        f'{k}(hit={v["hit_rate"]}, n={v["comment_days"]})' for k, v in reliable_kw[:5]
    ) if reliable_kw else '신뢰 표본(n≥3) 없음 — 단발 데이터는 노이즈라 제외'
    ledger_block = build_ledger_block(ledger_digest)
    bandit_block = ''
    if bandit_rec:
        bandit_block = (
            '\n[밴딧 슬롯 배분 — 탐색(explore)/활용(exploit)]\n'
            + bandit.directive_line(bandit_rec, 'morning') + '\n'
            + bandit.directive_line(bandit_rec, 'evening')
            + '\n→ exploit면 그 arm 재현, explore면 추천 arm 1개 + 대조군 후보 1개로 A/B.'
        )

    best_examples = '\n'.join(f'  - {e}' for e in best.get('examples', []))

    status_ko = {'normal': '정상', 'stall': '정체', 'emergency': '비상'}.get(status, status)
    stall_note = f'{days_since_growth}일째 정체 중' if days_since_growth > 0 else '오늘 성장 확인'

    prompt = f"""너는 @sebsonthebeach Threads 팀의 성장 분석가야.
계정 포지션: 해외 AI 트렌드를 한국에 먼저 전하는 실무자/빌더. 순수 팔로워 성장이 목표. 반말 구어체.
콘텐츠 3축: 트렌드 스카우트(오전) + 핫테이크(저녁) + 빌더 노트(간간히).
금지 주제: 자사몰/카페24/셀러 실무, 추상적 AI 미래론.
hunter_engager 우선 키워드는 AI/자동화/개발 주제로(예: AI 자동화, ChatGPT 활용, AI 에이전트, 바이브코딩). 셀러/이커머스 키워드 금지 — 프로필과 안 맞아 팔로우 전환 안 됨.

오늘 분석 결과:
- 상태: {status_ko} ({stall_note})
- 팔로워 추이: {follower_trend}
- 상위 포스트 평균 score: {best.get("avg_score", 0)}
- 상위 포스트 예시:
{best_examples if best_examples else "  없음"}
- 0점 포스트 수: {worst.get("count", 0)}개
- 키워드 효과 (댓글 → 다음날 팔로워 증가 hit rate, n≥3만): {kw_summary}
{ledger_block}
{bandit_block}

지시 원칙: 인게이지(좋아요·조회)가 아니라 **팔로워 순증**이 목표다. 원장의 '팔로워 끈 arm'을 우선 재현하고,
'죽은 arm'은 피하며, 밴딧의 슬롯별 탐색/활용 배분을 viral_writer 지시에 반영해라.
라벨이 추정 상태면 단정 대신 검증할 각도(대조군)로 지시해라.

아래 JSON만 출력 (다른 텍스트 없이):
{{
  "team_memo": "오늘 상태 한 줄 요약 (팀원들이 제일 먼저 읽는 것)",
  "best_post_style": "잘 된 포스트 공통점 (1~2줄, 구체적으로)",
  "worst_post_style": "안 된 포스트 공통점 (1줄)",
  "top_search_keywords": ["효과 좋은 키워드1", "키워드2", "키워드3"],
  "directives": {{
    "trend_scout": "{('트렌딩 10개 이상, 논쟁형/반전형 우선, 영어권 AI 반응 포함' if status in ['stall','emergency'] else '평소대로')}",
    "viral_writer": "오늘 포스트 작성 지침 (각도, 훅 강도, 피해야 할 것)",
    "hunter_engager": "오늘 댓글 목표 수 + 우선 키워드 + 영어 비중"
  }}
}}"""

    try:
        result = subprocess.run(
            [CLAUDE_BIN, '-p', prompt, '--model', 'sonnet'],
            capture_output=True, text=True, timeout=90
        )
        output = result.stdout.strip()
        if result.returncode != 0 or is_cli_auth_error(output):
            raise RuntimeError(f'CLI auth error: {output[:60]}')
        if '```' in output:
            parts = output.split('```')
            output = parts[1] if len(parts) > 1 else parts[0]
            if output.startswith('json'):
                output = output[4:].strip()
        return json.loads(output)
    except Exception as e:
        print(f'  ⚠️ AI 신호 생성 실패: {e}')
        stall_directive = status in ['stall', 'emergency']
        trend_line = follower_trend.split('(')[0].strip()
        return {
            'team_memo': f'{trend_line} — {stall_note}. (AI 분석 불가 — CLI 인증 확인 필요)',
            'best_post_style': 'AI 트렌드 먼저 짚기 + 실무 관점 해석 + 각진 의견',
            'worst_post_style': '범용 동기부여, 추상적 AI 전망',
            'top_search_keywords': top_kws[:3] if top_kws else ['AI 자동화', 'ChatGPT 활용', 'AI 에이전트'],
            'directives': {
                'trend_scout': '트렌딩 10개 이상, 논쟁형 우선' if stall_directive else '평소대로',
                'viral_writer': '트렌드+핫테이크 강화, 논쟁형 우선' if stall_directive else '오전 트렌드 스카우트 / 저녁 핫테이크, 빌더 노트 간간히',
                'hunter_engager': f'목표 {"35" if stall_directive else "25"}개. 좋아요 50~500 범위 우선. 영어 비중 {"40" if stall_directive else "30"}%',
            },
            '_cli_failed': True,
        }


def sync_agent_prompts(signal: dict, ledger_digest: dict | None = None,
                       bandit_rec: dict | None = None):
    """
    team_signal 기반으로 agent 프롬프트 파일의 동적 섹션을 자동 업데이트.
    고정 섹션(역할/말투/금지)은 건드리지 않고 성과 데이터 섹션만 교체.
    """
    prompts_dir = BASE_DIR / 'prompts'

    # ── hunter_engager.txt: 키워드 우선순위 섹션 ──────────────────────────────
    hunter_file = prompts_dir / 'hunter_engager.txt'
    if hunter_file.exists():
        kw_perf  = signal.get('keyword_performance', {})
        top_kws  = signal.get('top_search_keywords', [])
        directives_he = signal.get('directives', {}).get('hunter_engager', '')

        # hit_rate는 10일+ 데이터 있는 키워드만 신뢰 (샘플 부족하면 노이즈)
        reliable       = {k: v for k, v in kw_perf.items() if v.get('comment_days', 0) >= 10}
        confirmed_good = [k for k, v in reliable.items() if v['hit_rate'] >= 0.5]
        confirmed_ban  = [k for k, v in reliable.items() if v['hit_rate'] == 0.0]

        tier1_final = list(dict.fromkeys(confirmed_good + top_kws))[:6]
        ban_line    = ', '.join(confirmed_ban) if confirmed_ban else 'AI API 가격, DeepSeek 뉴스'

        new_section = (
            f"## 타겟 키워드 우선순위 ({today} 자동 업데이트 — growth_analyst 기반)\n"
            f"1순위: {', '.join(tier1_final) if tier1_final else 'AI 자동화, ChatGPT 활용, AI 에이전트'}\n"
            f"2순위: AI 툴, 바이브코딩, 클로드, 프롬프트, 노코드 (중 1순위 제외)\n"
            f"금지 키워드: {ban_line} — 10일+ 데이터 기준 hit rate 0.0\n"
            f"\n▶ 오늘 지시 (growth_analyst {today}): {directives_he}"
        )
        import re as _re
        content = hunter_file.read_text(encoding='utf-8')
        updated = _re.sub(
            r'## 타겟 키워드 우선순위.*?(?=\n## |\Z)',
            new_section + '\n\n',
            content,
            flags=_re.DOTALL,
        )
        hunter_file.write_text(updated, encoding='utf-8')
        print(f'  ✅ hunter_engager.txt 키워드 섹션 업데이트')

    # ── viral_writer.txt: 성과 데이터 섹션 ───────────────────────────────────
    viral_file = prompts_dir / 'viral_writer.txt'
    if viral_file.exists():
        best  = signal.get('best_performing', {})
        worst = signal.get('worst_performing', {})
        examples = best.get('examples', [])
        ex_lines = '\n'.join(f'  - "{e[:55]}"' for e in examples[:3]) if examples else '  - 데이터 없음'

        # 포스트 원장: 팔로워 순증 기준 진짜 위너/루저 arm (인게이지 위너와 다를 수 있음)
        ledger_lines = ''
        if ledger_digest:
            bf = ledger_digest.get('best_follower_arm')
            fails = ledger_digest.get('failing_arms', [])
            ns = ledger_digest.get('north_star', {})
            est = ' (⚠️ 라벨 추정 상태 — 잠정적)' if ledger_digest.get('labels_estimated') else ''
            follower_arm_str = (
                f"{bf['pretty']} (+{bf['follower_gain']}, n={bf['n']})" if bf else '아직 없음'
            )
            ledger_lines = (
                f"\n### 팔로워 순증 기준 (원장{est})\n"
                f"7일 순증 {ns.get('gain', 0):+d} | 실패율 {ledger_digest.get('failure_rate', 0)} "
                f"({ledger_digest.get('n_failures', 0)}/{ledger_digest.get('n_posts', 0)})\n"
                f"실제 팔로워 끈 arm: {follower_arm_str}\n"
                f"죽은 arm(피할 것): {', '.join(fails) if fails else '없음'}\n"
                f"※ 좋아요·조회가 아니라 팔로워를 끄는 arm을 재현할 것.\n"
            )

        # 밴딧 슬롯 배분 (탐색/활용) — 결정론적 지시
        bandit_lines = ''
        if bandit_rec:
            bandit_lines = (
                f"\n### 밴딧 슬롯 배분 (탐색/활용)\n"
                f"{bandit.directive_line(bandit_rec, 'morning')}\n"
                f"{bandit.directive_line(bandit_rec, 'evening')}\n"
                f"※ explore면 추천 arm 1개 + 대조군 후보 1개로 갈라서 시험(니치 박제 방지).\n"
            )

        new_section = (
            f"## 성과 데이터 ({today} 자동 업데이트)\n\n"
            f"잘 된 포스트 스타일: {best.get('style', '데이터 없음')}\n"
            f"잘 된 포스트 avg score: {best.get('avg_score', 0)} | 예시:\n{ex_lines}\n\n"
            f"안 된 포스트 스타일: {worst.get('style', '데이터 없음')} ({worst.get('count', 0)}개)\n"
            f"{ledger_lines}"
            f"{bandit_lines}\n"
            f"오늘 viral_writer 지시: {signal.get('directives', {}).get('viral_writer', '평소대로')}"
        )
        import re as _re
        content = viral_file.read_text(encoding='utf-8')
        updated = _re.sub(
            r'## 성과 데이터.*?(?=\n## |\Z)',
            new_section + '\n\n',
            content,
            flags=_re.DOTALL,
        )
        viral_file.write_text(updated, encoding='utf-8')
        print(f'  ✅ viral_writer.txt 성과 데이터 섹션 업데이트')


def devil_advocate(status: str, follower_trend: str, best: dict, worst: dict) -> str:
    """현재 분석에 반박. 아첨 방지용."""
    best_examples = '\n'.join(f'  - {e}' for e in best.get('examples', [])[:3])
    prompt = f"""너는 @sebsonthebeach Threads 팀의 비판 감사자야.
방금 growth_analyst가 아래 분석을 냈어. 이걸 반박해.

분석 결과:
- 상태: {status}
- 팔로워 추이: {follower_trend}
- 잘 됐다는 포스트:
{best_examples if best_examples else '  없음'}
- 안 됐다는 포스트 수: {worst.get('count', 0)}개

반박 지침:
- "잘 되고 있다"고 하면 "왜 팔로워 증가율이 낮은가"로 반박
- 상위 포스트 패턴이 있다면 "재현 가능한가, 우연이 아닌가" 질문
- 현재 전략이 유지되면 30일 후 어떻게 될지 예측
- 2~3문장으로 짧게, 한국어, 반말"""

    try:
        result = subprocess.run(
            [CLAUDE_BIN, '-p', prompt],
            capture_output=True, text=True, timeout=60
        )
        output = result.stdout.strip()
        if result.returncode != 0 or is_cli_auth_error(output):
            return '(Claude CLI 인증 만료 — 비판 분석 불가. `! claude /login` 실행 필요)'
        return output
    except Exception:
        return '(비판 분석 실패)'


if __name__ == '__main__':
    print(f'[{today}] growth_analyst.py 시작')

    follower_history = load_follower_history(21)
    posts = load_post_insights(14)
    print(f'  팔로워 기록 {len(follower_history)}일치, 포스트 {len(posts)}개 로드')

    if not follower_history and not posts:
        print('  ⚠️ 데이터 없음 — track.py 먼저 실행 필요')
        send_slack(f'⚠️ [{today}] growth_analyst: 데이터 없음. track.py 확인 요망')
        sys.exit(0)

    # 분석
    status, days_since_growth, follower_trend = detect_status(follower_history)
    kw_performance = analyze_keyword_performance(follower_history)
    best, worst = analyze_posts(posts)

    print(f'  상태: {status} (정체 {days_since_growth}일)')
    print(f'  팔로워 추이: {follower_trend}')

    # 포스트 원장 빌드 + 다이제스트 (post-side arm 진실: 팔로워 귀인·실패율). 파생 캐시라 커밋 안 함.
    ledger_digest = None
    bandit_rec = None
    try:
        _ledger = ledger.build_ledger()
        (DATA_DIR / 'post_ledger.json').write_text(json.dumps(_ledger, ensure_ascii=False, indent=2))
        ledger_digest = ledger.summarize(_ledger)
        print(f"  원장: {ledger_digest['n_posts']}글, 실패율 {ledger_digest['failure_rate']}, "
              f"팔로워 arm={ledger_digest['best_follower_arm']['pretty'] if ledger_digest['best_follower_arm'] else '없음'}")
        # 밴딧: 슬롯별 arm 탐색/활용 배분
        bandit_rec = bandit.recommend(_ledger)
        (DATA_DIR / 'bandit.json').write_text(json.dumps(bandit_rec, ensure_ascii=False, indent=2))
        print(f"  밴딧 morning: {bandit.directive_line(bandit_rec, 'morning')[:70]}")
    except Exception as e:
        print(f'  ⚠️ 원장/밴딧 빌드 실패(폴백 진행): {e}')

    # 팀 신호 생성
    print('  팀 신호 생성 중...')
    ai_signal = generate_team_signal(
        status, days_since_growth, follower_trend, best, worst, kw_performance,
        ledger_digest, bandit_rec,
    )

    if ai_signal.get('_cli_failed'):
        print('  ⚠️ Claude CLI 인증 만료 — 폴백 신호 사용')
        send_slack('🔐 *growth_analyst CLI 인증 만료*\n팀 신호가 하드코딩 폴백으로 생성됨.\n`! claude /login` 실행 필요')

    print('  악마의 변호인 분석 중...')
    critic = devil_advocate(status, follower_trend, best, worst)
    print(f'  비판: {critic[:80]}')

    # team_signal.json 조립
    signal = {
        'status': status,
        'days_since_growth': days_since_growth,
        'follower_trend': follower_trend,
        'best_performing': {
            **best,
            'style': ai_signal.get('best_post_style', ''),
        },
        'worst_performing': {
            **worst,
            'style': ai_signal.get('worst_post_style', ''),
        },
        'keyword_performance': kw_performance,
        'top_search_keywords': ai_signal.get('top_search_keywords', []),
        'directives': ai_signal.get('directives', {}),
        'team_memo': ai_signal.get('team_memo', ''),
        'devil_advocate': critic,
        'ledger': ledger_digest,          # 팔로워 arm·실패율·북극성 (hunter_engager도 참고 가능)
        'bandit': bandit_rec,             # 슬롯별 arm 탐색/활용 배분
        'updated_at': today,
    }

    SIGNAL_FILE.write_text(json.dumps(signal, ensure_ascii=False, indent=2))
    print(f'  team_signal.json 저장: status={status}')

    # 프롬프트 자동 업데이트 (자기개선 루프)
    print('  프롬프트 동기화 중...')
    sync_agent_prompts(signal, ledger_digest, bandit_rec)

    # growth_strategy.json도 호환성 유지로 함께 저장
    strategy = {
        'weekly_focus': ai_signal.get('directives', {}).get('viral_writer', ''),
        'recommended_topics': ai_signal.get('top_search_keywords', []),
        'avoid_topics': ['자사몰/카페24 직접 언급', '추상적 AI 미래론'],
        'best_post_style': ai_signal.get('best_post_style', ''),
        'worst_post_style': ai_signal.get('worst_post_style', ''),
        'posting_times': {'morning': '10:21', 'evening': '20:00'},
        'engagement_keywords': ai_signal.get('top_search_keywords', []),
        'alert': signal['team_memo'],
        'generated_at': today,
    }
    STRATEGY_FILE.write_text(json.dumps(strategy, ensure_ascii=False, indent=2))

    # Slack 단일 브리핑 (track.py는 데이터만 수집, 보고는 여기서만)
    status_emoji = {'normal': '✅', 'stall': '⚠️', 'emergency': '🚨'}.get(status, '📊')
    out = [f'{status_emoji} *팀 브리핑* ({today})']

    # 댓글 세션 헬스 — 죽었으면 최상단 고정 알림 (노출 레버가 조용히 안 죽게)
    sess = session_health.check()
    if not sess['ok']:
        out.append(f'🔴 *댓글 세션 DOWN*: {sess["message"]}')
        print(f'  🔴 세션 DOWN: {sess["message"]}')
    elif sess['level'] == 'warn':
        out.append(f'⚠️ {sess["message"]}')
    out.append(f'{follower_trend} | {signal["team_memo"][:60]}')
    out.append('')

    # 포스트 TOP3
    if posts:
        ranked = sorted(posts, key=lambda x: int(x.get('engagement_score', 0)), reverse=True)
        out.append('*포스트 TOP3*')
        medals = ['🥇', '🥈', '🥉']
        for i, p in enumerate(ranked[:3]):
            score = int(p.get('engagement_score', 0))
            likes = int(p.get('likes', 0))
            replies_c = int(p.get('replies', 0))
            out.append(f'{medals[i]} score {score} (❤️{likes} 💬{replies_c}) "{p.get("text_preview","")[:35]}…"')
        dead = sum(1 for p in posts if int(p.get('engagement_score', 0)) == 0)
        if dead:
            out.append(f'무반응 {dead}/{len(posts)}개')
        out.append('')

    # 에이전트 지시
    out.append('*에이전트 지시*')
    for agt, directive in signal['directives'].items():
        out.append(f'• {agt}: {directive[:90]}')

    # 키워드 효과 (10일+ 데이터만)
    reliable_kw = {k: v for k, v in kw_performance.items() if v.get('comment_days', 0) >= 10}
    if reliable_kw:
        top_kw = list(reliable_kw.items())[:3]
        kw_str = ' | '.join(f'{k} (hit {v["hit_rate"]})' for k, v in top_kw)
        out.append(f'\n*키워드 효과*: {kw_str}')

    if status in ('stall', 'emergency'):
        out.append(f'\n{status_emoji} *{days_since_growth}일째 정체 — 전략 전환 필요*')

    out.append(f'\n🔴 *비판 감사*: {critic[:200]}')

    if already_briefed_today():
        print('  오늘 브리핑 이미 발송됨 — 중복 스킵')
    else:
        send_slack('\n'.join(out))
        mark_briefed()
    print('완료')
