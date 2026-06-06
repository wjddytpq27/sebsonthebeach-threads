"""
strategist.py — 주간 전략가 (반아첨, 데이터 기반)
매주 월요일 00:00 실행

역할: 지난 7일 데이터를 보고 현재 전략의 문제점을 날카롭게 비판.
      성장이 느리면 전략 자체를 의심. 희망적 편향 없음.
"""
import csv, json, os, shutil, subprocess, sys, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
today = datetime.now(KST).strftime('%Y-%m-%d')

# 로컬은 절대경로, 클라우드(Actions)는 PATH의 claude
CLAUDE_BIN       = os.environ.get('CLAUDE_BIN') or shutil.which('claude') or '/opt/homebrew/bin/claude'
BASE_DIR         = Path(__file__).resolve().parent
DATA_DIR         = BASE_DIR / 'data'
FOLLOWER_CSV     = DATA_DIR / 'follower_log.csv'
INSIGHTS_CSV     = DATA_DIR / 'insights.csv'
SIGNAL_FILE      = DATA_DIR / 'team_signal.json'
ATTRIBUTION_FILE = DATA_DIR / 'follow_attribution.json'
OUTPUT_FILE      = DATA_DIR / 'strategic_review.json'
PROMPTS_DIR      = BASE_DIR / 'prompts'
HISTORY_DIR      = PROMPTS_DIR / 'history'
SLACK_CONFIG     = DATA_DIR / 'slack_config.json'


def ask_claude(prompt: str) -> str:
    result = subprocess.run(
        [CLAUDE_BIN, '-p', prompt, '--model', 'opus'],
        capture_output=True, text=True, timeout=180
    )
    if result.returncode != 0:
        return f"[claude 오류: {result.stderr[:100]}]"
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


def load_recent_follower_data() -> dict:
    if not FOLLOWER_CSV.exists():
        return {}
    rows = []
    with open(FOLLOWER_CSV) as f:
        for r in csv.DictReader(f):
            try:
                rows.append({'date': r['date'], 'followers': int(r['followers'])})
            except (KeyError, ValueError):
                pass
    rows = sorted(rows, key=lambda x: x['date'])[-14:]
    if not rows:
        return {}
    return {
        'start': rows[0]['followers'],
        'end': rows[-1]['followers'],
        'delta': rows[-1]['followers'] - rows[0]['followers'],
        'days': len(rows),
        'history': rows,
    }


def load_recent_posts() -> list[dict]:
    if not INSIGHTS_CSV.exists():
        return []
    rows = []
    cutoff = (datetime.now(KST) - timedelta(days=14)).strftime('%Y-%m-%d')
    with open(INSIGHTS_CSV) as f:
        for r in csv.DictReader(f):
            if r.get('post_date', '') >= cutoff:
                try:
                    rows.append({
                        'date': r.get('post_date', ''),
                        'text': r.get('text_preview', '')[:100],
                        'score': int(r.get('engagement_score', 0) or 0),
                        'views': int(r.get('views', 0) or 0),
                        'likes': int(r.get('likes', 0) or 0),
                        'replies': int(r.get('replies', 0) or 0),
                    })
                except (KeyError, ValueError):
                    pass
    seen = {}
    for r in rows:
        key = r['text'][:30]
        if key not in seen or r['score'] > seen[key]['score']:
            seen[key] = r
    return sorted(seen.values(), key=lambda x: x['score'], reverse=True)


if __name__ == '__main__':
    print(f"[{today}] strategist.py 시작 (주간 전략 리뷰)")

    follower_data = load_recent_follower_data()
    posts = load_recent_posts()
    signal = json.loads(SIGNAL_FILE.read_text()) if SIGNAL_FILE.exists() else {}
    attribution = json.loads(ATTRIBUTION_FILE.read_text()) if ATTRIBUTION_FILE.exists() else {}

    scores = [p['score'] for p in posts]
    avg_score = sum(scores) / len(scores) if scores else 0
    zero_posts = sum(1 for s in scores if s == 0)
    top3 = posts[:3]
    bottom3 = [p for p in posts if p['score'] == 0][:3]

    follower_delta = follower_data.get('delta', 0)
    follower_start = follower_data.get('start', 0)
    follower_end = follower_data.get('end', 0)
    days = follower_data.get('days', 7)

    data_summary_text = f"""
=== 지난 {days}일 Threads 성장 데이터 ===
계정: @sebsonthebeach (자사몰/이커머스 실무자 + AI 자동화 써본 사람)

[팔로워]
- 시작: {follower_start}명 → 현재: {follower_end}명
- 증감: {follower_delta:+d}명 ({days}일간)
- 일평균: {follower_delta/days:.1f}명/일

[포스트 성과] (총 {len(posts)}개)
- 평균 engagement score: {avg_score:.1f}
- score=0인 글: {zero_posts}개 ({zero_posts/len(posts)*100:.0f}% if posts else 0%)

[상위 3개]
{chr(10).join(f'- score={p["score"]} views={p["views"]} | {p["text"][:60]}' for p in top3)}

[score=0 글 예시]
{chr(10).join(f'- {p["text"][:60]}' for p in bottom3)}

[현재 팀 전략]
- 방향: {signal.get("directives", {}).get("viral_writer", "없음")}
- 상태: {signal.get("status", "unknown")}
- best 콘텐츠 타입: {attribution.get("best_content_type", "데이터 없음")}
- 포스트당 평균 팔로워: +{attribution.get("avg_followers_per_post", 0):.2f}명
"""

    print("  [비판 분석] Claude에게 문제점 요청 중...")
    critic_prompt = f"""너는 냉정한 소셜미디어 성장 전략가야. 아첨 없이 데이터만 봐.

다음 Threads 계정 데이터를 분석하고 현재 전략의 핵심 문제점 3가지를 말해.
각 문제점은 "문제 → 데이터 근거 → 지금 당장 바꿔야 할 것" 형식으로.
희망적인 말 금지. 잘 되고 있는 것보다 왜 느린지에 집중.

{data_summary_text}"""

    critic_result = ask_claude(critic_prompt)

    print("  [실험 설계] Claude에게 다음 2주 실험 요청 중...")
    experiment_prompt = f"""위 Threads 계정 데이터를 보고 다음 2주 동안 시도할 실험 3가지를 설계해.

각 실험 형식:
실험명: ...
가설: ...
실행 방법: 구체적으로 (어떤 포스트를, 어떤 스타일로, 몇 번)
성공 판단: 수치 기준으로

단, 지금까지 안 해본 것 위주로. "더 열심히 하자" 같은 말 금지.

{data_summary_text}"""

    experiment_result = ask_claude(experiment_prompt)

    # 전략 전환 판단
    if follower_delta <= 0 and days >= 7:
        pivot = '긴급재설계'
    elif follower_delta < days * 0.5:
        pivot = '방향전환'
    else:
        pivot = '현재유지'

    print(f"  전략 판정: {pivot}")

    print("  [핵심 방향] 다음 2주 집중 포인트 도출 중...")
    focus_prompt = f"""위 비판 분석과 실험 계획을 종합해서,
@sebsonthebeach 계정이 다음 2주 동안 가장 집중해야 할 딱 한 가지를 말해.
한 문장으로. 구체적으로. "더 잘하자" 같은 말 금지.

비판 분석 요약:
{critic_result[:500]}

실험 계획 요약:
{experiment_result[:500]}"""

    focus_result = ask_claude(focus_prompt)

    review = {
        'week_of': today,
        'data_summary': {
            'follower_start': follower_start,
            'follower_end': follower_end,
            'follower_delta': follower_delta,
            'days': days,
            'total_posts': len(posts),
            'avg_score': round(avg_score, 1),
            'zero_score_posts': zero_posts,
            'top_post': top3[0]['text'][:80] if top3 else None,
        },
        'critic_analysis': critic_result,
        'experiments': experiment_result,
        'strategic_pivot': pivot,
        'next_2weeks_focus': focus_result,
        'generated_at': today,
    }

    OUTPUT_FILE.write_text(json.dumps(review, indent=2, ensure_ascii=False))
    print(f"  strategic_review.json 저장 완료")

    # team_signal에 병합
    if SIGNAL_FILE.exists():
        signal['strategic_review'] = {
            'pivot': pivot,
            'next_2weeks_focus': focus_result,
            'week_of': today,
        }
        signal['stop_doing'] = [p['text'][:60] for p in bottom3]
        SIGNAL_FILE.write_text(json.dumps(signal, indent=2, ensure_ascii=False))

    # ── 프롬프트 업데이트 ───────────────────────────────────────
    print("\n  [프롬프트 업데이트] 에이전트 프롬프트 재작성 중...")
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    top3_text = '\n'.join(
        f'- score={p["score"]} views={p["views"]} | {p["text"][:70]}'
        for p in posts[:3]
    )
    zero_text = '\n'.join(
        f'- {p["text"][:70]}'
        for p in posts if p['score'] == 0
    )[:400]
    attribution_summary = (
        f"팔로워 유발 콘텐츠 타입: {attribution.get('best_content_type', '데이터 없음')}\n"
        f"포스트당 평균 팔로워: +{attribution.get('avg_followers_per_post', 0):.2f}명\n"
        f"효과 없는 타입: {attribution.get('content_type_avg_delta', {})}"
    ) if attribution else "귀속 데이터 없음"

    for agent_name in ['viral_writer', 'hunter_engager', 'trend_scout']:
        prompt_file = PROMPTS_DIR / f'{agent_name}.txt'
        if not prompt_file.exists():
            continue

        current_prompt = prompt_file.read_text()

        # 백업
        backup_path = HISTORY_DIR / f'{agent_name}_{today}.txt'
        backup_path.write_text(current_prompt)

        rewrite_prompt = f"""너는 @sebsonthebeach Threads 팀의 주간 전략가야.
지난 7일 성과 데이터를 보고 {agent_name} 에이전트의 프롬프트를 업데이트해.

## 성과 데이터
팔로워: {follower_start}→{follower_end} ({follower_delta:+d}명/{days}일)
평균 score: {avg_score:.1f} | zero-score 포스트: {zero_posts}개
전략 판정: {pivot}
핵심 집중 방향: {focus_result}

상위 포스트:
{top3_text}

zero-score 포스트 (피해야 할 패턴):
{zero_text if zero_text else '없음'}

팔로워 귀속 분석:
{attribution_summary}

비판 분석 요약:
{critic_result[:400]}

## 현재 프롬프트
{current_prompt}

## 지침
- 성과 데이터 기반으로 "잘 됐던 것은 강화, 안 됐던 것은 제거/수정"
- 프롬프트 전체를 다시 써. 형식은 현재와 동일하게.
- "성과 데이터 기반 지침" 섹션을 이번 주 데이터로 완전히 교체
- 추상적 지시 금지. 구체적 패턴, 예시, 금지사항으로.
- 맨 첫 줄 주석에 날짜 업데이트: # 업데이트: {today}

프롬프트 텍스트만 출력. 설명이나 마크다운 코드블록 없이."""

        try:
            result = subprocess.run(
                [CLAUDE_BIN, '-p', rewrite_prompt],
                capture_output=True, text=True, timeout=120
            )
            new_prompt = result.stdout.strip()
            if len(new_prompt) > 200:
                prompt_file.write_text(new_prompt)
                print(f"    ✅ {agent_name} 프롬프트 업데이트 완료 ({len(current_prompt)}자 → {len(new_prompt)}자)")
            else:
                print(f"    ⚠️ {agent_name} 결과 너무 짧음 — 기존 유지")
        except Exception as e:
            print(f"    ❌ {agent_name} 실패: {e}")

    print("  프롬프트 업데이트 완료")

    slack_msg = (
        f"🧠 *주간 전략 리뷰 + 프롬프트 업데이트* [{today}]\n\n"
        f"*팔로워*: {follower_start}→{follower_end} ({follower_delta:+d}명/{days}일)\n"
        f"*판정*: {pivot}\n\n"
        f"*핵심 집중*: {focus_result}\n\n"
        f"*문제점 분석*:\n{critic_result[:500]}\n\n"
        f"*실험 계획*:\n{experiment_result[:400]}\n\n"
        f"✏️ *viral_writer / hunter_engager / trend_scout 프롬프트 자동 업데이트됨*\n"
        f"└ 백업: prompts/history/{today}"
    )
    send_slack(slack_msg)
    print("완료")
