"""
session_health.py — Threads 브라우저 세션 유효성 헬스체크

16일간 세션이 조용히 죽어 댓글 엔진이 0개였던 사고(2026-06~07) 재발 방지.
- soft-logout(sessionid 쿠키 소실) 조기 감지
- 만료 임박 감지
- growth_analyst(매일 22:45, 정상 cwd·Slack)에서 호출 → 죽으면 브리핑 최상단 🔴 알림

핵심: 예전 auto_renew_session.py는 crontab cwd 버그로 아예 실행이 안 됐고(알림 코드가
안 돌았음), 이 모듈은 확실히 도는 nightly 파이프라인에 얹어 알림 경로를 이중화한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / 'session_state.json'
RENEW_CMD = 'python3 /Users/uneedcomms/thread/renew_session.py'
WARN_DAYS = 3   # 만료 N일 이내면 경고

# 열람은 되지만 댓글 작성에 필요한 인증 쿠키
AUTH_COOKIE = 'sessionid'


def check(state_file: Path = STATE_FILE) -> dict:
    """
    세션 상태 판정. 반환: {ok, level, message}
    level: 'ok' | 'warn' | 'dead'
    """
    if not state_file.exists():
        return {'ok': False, 'level': 'dead',
                'message': f'session_state.json 없음 — 댓글 엔진 정지. 재로그인: `{RENEW_CMD}`'}

    try:
        state = json.loads(state_file.read_text())
    except Exception as e:
        return {'ok': False, 'level': 'dead',
                'message': f'session_state.json 파손({e}) — 재로그인: `{RENEW_CMD}`'}

    cookies = state.get('cookies', [])
    names = {c.get('name') for c in cookies}

    if AUTH_COOKIE not in names:
        return {'ok': False, 'level': 'dead',
                'message': (f'Threads 인증 상실(sessionid 쿠키 없음) — 댓글 작성 불가. '
                            f'헤드리스 갱신 불가, Mac에서 직접 로그인 필요: `{RENEW_CMD}`')}

    # sessionid 만료 임박 확인
    now = datetime.now(KST).timestamp()
    warn_cutoff = now + WARN_DAYS * 86400
    for c in cookies:
        if c.get('name') == AUTH_COOKIE:
            exp = c.get('expires', -1)
            if 0 < exp <= now:
                return {'ok': False, 'level': 'dead',
                        'message': f'sessionid 만료됨 — 재로그인: `{RENEW_CMD}`'}
            if 0 < exp <= warn_cutoff:
                exp_str = datetime.fromtimestamp(exp, tz=KST).strftime('%Y-%m-%d')
                return {'ok': True, 'level': 'warn',
                        'message': f'sessionid {exp_str} 만료 임박 — 곧 재로그인 권장: `{RENEW_CMD}`'}

    return {'ok': True, 'level': 'ok', 'message': '세션 정상'}


if __name__ == '__main__':
    r = check()
    icon = {'ok': '✅', 'warn': '⚠️', 'dead': '🔴'}.get(r['level'], '')
    print(f"{icon} [{r['level']}] {r['message']}")
