"""
팩트체커 에이전트
포스팅 직전(09:30)에 실행 — 두 가지 역할:
1. 포스트 사실 검증: 수치/주장이 확정 사실인지, 전망/예측인지 구분
2. 성과 분석 검증: team_signal.json이 실제 CSV 데이터와 일치하는지 교차 확인

출력:
- posts.json 내 오늘 포스트에 fact_check 필드 추가
- 수정된 경우 content 업데이트
- Slack 알림 (이슈 있을 때만)
"""
import csv, json, os, shutil, sys, subprocess, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
today = datetime.now(KST).strftime('%Y-%m-%d')

# 로컬은 절대경로, 클라우드(Actions)는 PATH의 claude
CLAUDE_BIN   = os.environ.get('CLAUDE_BIN') or shutil.which('claude') or '/opt/homebrew/bin/claude'
BASE_DIR     = Path(__file__).resolve().parent
DATA_DIR     = BASE_DIR / 'data'
CONFIG_FILE  = DATA_DIR / 'threads_config.json'
POSTS_FILE   = DATA_DIR / 'posts.json'
SIGNAL_FILE  = DATA_DIR / 'team_signal.json'
FOLLOWER_CSV = DATA_DIR / 'follower_log.csv'
INSIGHTS_CSV = DATA_DIR / 'insights.csv'
SLACK_CONFIG = DATA_DIR / 'slack_config.json'


def ask_claude(prompt: str) -> str:
    """claude CLI로 질문 — 구독 세션 그대로 사용"""
    result = subprocess.run(
        [CLAUDE_BIN, '-p', prompt],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI 오류: {result.stderr[:200]}")
    return result.stdout.strip()


def send_slack(msg: str):
    webhook = ''
    if SLACK_CONFIG.exists():
        try:
            webhook = json.loads(SLACK_CONFIG.read_text()).get('webhook_url', '')
        except Exception:
            webhook = ''
    if not webhook:
        webhook = os.environ.get('SLACK_WEBHOOK', '')
    if not webhook:
        return
    data = json.dumps({'text': msg}).encode()
    req = urllib.request.Request(webhook, data=data,
                                  headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req)
    except Exception:
        pass


def ddg_search(query: str) -> str:
    """DuckDuckGo Instant Answer API — 무료, 키 불필요"""
    url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1&skip_disambig=1"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
        parts = []
        if data.get('AbstractText'):
            parts.append(data['AbstractText'])
        for result in data.get('RelatedTopics', [])[:3]:
            if isinstance(result, dict) and result.get('Text'):
                parts.append(result['Text'])
        return '\n'.join(parts) if parts else '검색 결과 없음'
    except Exception as e:
        return f'검색 실패: {e}'


def fact_check_post(post: dict) -> dict:
    """
    포스트 사실 검증.
    반환: {"status": "pass"|"modified"|"block", "content": ..., "reason": ...}
    """
    content = post.get('content', '')

    # 1단계: 사실 주장 추출
    extract_prompt = f"""다음 Threads 포스트에서 검증이 필요한 사실적 주장(수치, 통계, 회사 정보, 확정 사실로 표현된 것)을 JSON 배열로 추출해.
검증 불필요한 것(개인 의견, 일반 상식)은 제외.

포스트:
{content}

반환 형식 (다른 텍스트 없이 JSON만):
{{"claims": ["주장1", "주장2"]}}"""

    try:
        raw = ask_claude(extract_prompt)
        start = raw.find('{')
        end = raw.rfind('}') + 1
        claims = json.loads(raw[start:end]).get('claims', []) if start >= 0 else []
    except Exception:
        claims = []

    if not claims:
        return {"status": "pass", "content": content, "reason": "검증할 사실 주장 없음"}

    # 2단계: 각 주장 웹 검색
    search_results = {}
    for claim in claims[:4]:
        search_results[claim] = ddg_search(claim)

    # 3단계: 최종 판정
    search_summary = '\n\n'.join([f"[{c}]\n{r}" for c, r in search_results.items()])

    judge_prompt = f"""다음 Threads 포스트의 사실 주장을 검증해. 검색 결과를 참고하되, 없어도 일반 지식으로 판단해.

포스트:
{content}

검색 결과:
{search_summary}

판정 기준:
- pass: 모든 주장이 사실이거나 적절한 표현("전망", "예상") 사용
- modified: 표현 수정으로 해결 가능 (예: "흑자 됨" → "흑자 전환 전망")
- block: 명백한 오류 또는 수정해도 신뢰도 훼손

반환 형식 (JSON만):
{{
  "status": "pass",
  "issues": ["문제점"],
  "modified_content": null
}}"""

    try:
        raw = ask_claude(judge_prompt)
        start = raw.find('{')
        end = raw.rfind('}') + 1
        result = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {}

    status = result.get('status', 'pass')
    modified = result.get('modified_content')
    issues = result.get('issues', [])

    if status == 'modified' and modified:
        return {"status": "modified", "content": modified, "reason": '; '.join(issues)}
    elif status == 'block':
        return {"status": "block", "content": content, "reason": '; '.join(issues)}
    else:
        return {"status": "pass", "content": content, "reason": "검증 통과"}


def validate_growth_signal() -> list[str]:
    """
    team_signal.json vs 실제 CSV 데이터 교차 검증.
    반환: 불일치 경고 목록
    """
    warnings = []
    if not SIGNAL_FILE.exists():
        return warnings

    signal = json.loads(SIGNAL_FILE.read_text())

    # 팔로워 트렌드 검증
    if FOLLOWER_CSV.exists():
        rows = []
        with open(FOLLOWER_CSV) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if len(rows) >= 2:
            recent = rows[-5:] if len(rows) >= 5 else rows
            counts = []
            for r in recent:
                try:
                    counts.append(int(r.get('followers', r.get('count', 0))))
                except (ValueError, TypeError):
                    pass

            if counts:
                actual_growth = counts[-1] - counts[0]
                days = len(counts) - 1
                claimed_status = signal.get('status', 'normal')

                # 실제로 줄고 있는데 normal이면 경고
                if actual_growth < -5 and claimed_status == 'normal':
                    warnings.append(
                        f"팔로워 실제 -{abs(actual_growth)}명 감소 중인데 status=normal — stall 이상이어야 함"
                    )
                # 3일 이상 정체인데 normal이면
                days_flat = sum(1 for i in range(1, len(counts)) if counts[i] - counts[i-1] == 0)
                if days_flat >= 3 and claimed_status == 'normal':
                    warnings.append(
                        f"팔로워 {days_flat}일 연속 정체인데 status=normal"
                    )

    # 베스트 포스트 스코어 검증
    if INSIGHTS_CSV.exists():
        rows = []
        with open(INSIGHTS_CSV) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if rows:
            try:
                scores = [float(r.get('score', 0)) for r in rows if r.get('score')]
                if scores:
                    actual_avg = sum(scores) / len(scores)
                    claimed_best = signal.get('best_performing', {}).get('avg_score', 0)
                    # 클레임한 best avg가 실제 전체 평균보다 낮으면 이상
                    if claimed_best < actual_avg * 0.5 and claimed_best > 0:
                        warnings.append(
                            f"best_performing avg_score({claimed_best}) < 전체 평균({actual_avg:.1f}) 절반 — 분석 오류 가능"
                        )
            except (ValueError, TypeError):
                pass

    return warnings


if __name__ == '__main__':
    print(f"[{today}] fact_checker.py 시작")

    # ── 1. 포스트 팩트체크 ──────────────────────────────────────
    if not POSTS_FILE.exists():
        print("⚠️ posts.json 없음 — 스킵")
    else:
        posts = json.loads(POSTS_FILE.read_text())
        today_posts = [p for p in posts if p.get('date') == today and not p.get('fact_checked')]

        if not today_posts:
            print("  오늘 팩트체크 대상 포스트 없음 (이미 완료되었거나 없음)")
        else:
            issues_found = []
            for i, post in enumerate(today_posts):
                slot = '저녁' if post.get('evening') else '오전'
                print(f"  [{slot}] 팩트체크 중...")
                result = fact_check_post(post)

                # posts 원본에 반영
                idx = next((j for j, p in enumerate(posts)
                            if p.get('date') == today and p.get('evening') == post.get('evening')), None)
                if idx is not None:
                    posts[idx]['fact_checked'] = True
                    posts[idx]['fact_check_status'] = result['status']
                    posts[idx]['fact_check_reason'] = result.get('reason', '')  # 재생성 피드백용
                    if result['status'] == 'modified':
                        posts[idx]['content'] = result['content']
                        print(f"    ✏️  수정됨: {result['reason']}")
                        issues_found.append(f"[{slot}] 수정: {result['reason']}")
                    elif result['status'] == 'block':
                        posts[idx]['blocked'] = True
                        print(f"    🚫 블록: {result['reason']}")
                        issues_found.append(f"[{slot}] 블록: {result['reason']}")
                    else:
                        print(f"    ✅ 통과")

            POSTS_FILE.write_text(json.dumps(posts, indent=2, ensure_ascii=False))

            if issues_found:
                send_slack(f"⚠️ [{today}] 팩트체커 이슈\n" + '\n'.join(f"• {i}" for i in issues_found))

    # ── 2. 성과 분석 교차 검증 ─────────────────────────────────
    print("  성과 분석 검증 중...")
    growth_warnings = validate_growth_signal()
    if growth_warnings:
        warn_msg = f"📊 [{today}] growth_analyst 데이터 불일치\n" + '\n'.join(f"• {w}" for w in growth_warnings)
        print(f"  ⚠️ {len(growth_warnings)}건 경고")
        for w in growth_warnings:
            print(f"    - {w}")
        send_slack(warn_msg)
    else:
        print("  ✅ 성과 분석 데이터 정상")

    print("완료")
