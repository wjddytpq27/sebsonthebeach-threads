"""
auth_guard.py — Claude CLI 인증 상태 확인
cron에서 && 조건으로 사용:
  python3 auth_guard.py && claude -p "..."

동작 순서:
1. .agent_env 토큰으로 CLI 테스트 (cron-safe)
2. 실패 시 Keychain(인터랙티브 세션)으로 재시도
3. Keychain 성공 시 setup-token으로 .agent_env 갱신 → 자동 복구
4. 둘 다 실패 시 Slack 알림 + exit 1 (하루 1회)
"""
import json, os, re, subprocess, sys, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST          = timezone(timedelta(hours=9))
today        = datetime.now(KST).strftime('%Y-%m-%d')
BASE_DIR     = Path(__file__).resolve().parent
AGENT_ENV    = BASE_DIR / 'data' / '.agent_env'
SLACK_CONFIG = BASE_DIR / 'data' / 'slack_config.json'
ALERT_FILE   = BASE_DIR / 'data' / '.auth_alert_sent'
CLAUDE_BIN   = '/opt/homebrew/bin/claude'

AUTH_ERROR_PATTERNS = [
    'not logged in', 'please run', '/login', 'authentication',
    'unauthorized', 'log in', 'sign in', 'session expired',
]


def send_slack(msg: str):
    try:
        webhook = json.loads(SLACK_CONFIG.read_text()).get('webhook_url', '')
        if not webhook:
            return
        data = json.dumps({'text': msg}).encode()
        req  = urllib.request.Request(webhook, data=data, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def already_alerted() -> bool:
    return ALERT_FILE.exists() and ALERT_FILE.read_text().strip() == today


def mark_alerted():
    ALERT_FILE.write_text(today)


def load_agent_token() -> str:
    """data/.agent_env에서 CLAUDE_CODE_OAUTH_TOKEN 추출"""
    if not AGENT_ENV.exists():
        return ''
    for line in AGENT_ENV.read_text().splitlines():
        m = re.match(r"""export\s+CLAUDE_CODE_OAUTH_TOKEN=['"]?([^'"]+)['"]?""", line.strip())
        if m:
            return m.group(1).strip()
    return ''


def run_claude_ping(extra_env: dict = None) -> bool:
    """haiku 핑 테스트. True = 인증 OK"""
    try:
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        result = subprocess.run(
            [CLAUDE_BIN, '-p', 'reply with: OK', '--model', 'haiku'],
            capture_output=True, text=True, timeout=30, env=env
        )
        output = (result.stdout + result.stderr).lower()
        if result.returncode != 0 or any(p in output for p in AUTH_ERROR_PATTERNS):
            return False
        return 'ok' in result.stdout.lower()
    except Exception:
        return False


def try_renew_token() -> str:
    """
    setup-token으로 새 토큰 발급 시도 (인터랙티브 세션에서만 가능).
    성공 시 토큰 문자열 반환, 실패 시 ''.
    """
    try:
        result = subprocess.run(
            [CLAUDE_BIN, 'setup-token'],
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout + result.stderr
        m = re.search(r'(sk-ant-oat01-[A-Za-z0-9_-]+)', output)
        return m.group(1) if m else ''
    except Exception:
        return ''


def update_agent_env(new_token: str):
    """data/.agent_env의 CLAUDE_CODE_OAUTH_TOKEN 교체"""
    if not AGENT_ENV.exists():
        return
    lines = AGENT_ENV.read_text().splitlines()
    updated = []
    replaced = False
    for line in lines:
        if line.strip().startswith('export CLAUDE_CODE_OAUTH_TOKEN='):
            updated.append(f"export CLAUDE_CODE_OAUTH_TOKEN='{new_token}'")
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        updated.append(f"export CLAUDE_CODE_OAUTH_TOKEN='{new_token}'")
    AGENT_ENV.write_text('\n'.join(updated) + '\n')


if __name__ == '__main__':
    # 1단계: .agent_env 토큰으로 테스트 (cron에서 Keychain 없이도 동작)
    agent_token = load_agent_token()
    if agent_token:
        ok = run_claude_ping({'CLAUDE_CODE_OAUTH_TOKEN': agent_token})
    else:
        ok = run_claude_ping()

    if ok:
        print(f'[{today}] Claude CLI 인증 OK')
        sys.exit(0)

    print(f'[{today}] .agent_env 토큰 실패 — Keychain 재시도')

    # 2단계: Keychain(인터랙티브 세션) 테스트
    keychain_ok = run_claude_ping()

    if keychain_ok:
        print('  Keychain 인증 성공 — setup-token으로 .agent_env 갱신 시도')
        new_token = try_renew_token()
        if new_token:
            update_agent_env(new_token)
            print(f'  .agent_env 토큰 갱신 완료 — 에이전트 계속 진행')
            sys.exit(0)
        else:
            print('  setup-token 파싱 실패 — 에이전트는 Keychain 세션으로 진행')
            sys.exit(0)

    # 3단계: 둘 다 실패 → Slack 알림 (90일마다 한 번꼴)
    print(f'[{today}] Claude CLI 인증 만료 (토큰 + Keychain 모두 실패)')
    if not already_alerted():
        send_slack(
            f'🔐 *Claude CLI 토큰 만료* ({today})\n'
            'Claude Code 열고 아래 한 줄 실행하면 90일 리셋:\n'
            '`! claude setup-token`\n'
            '_(오늘 에이전트 작업 정지 — 실행 후 자동 재개)_'
        )
        mark_alerted()
        print('  Slack 알림 발송')
    else:
        print('  오늘 이미 알림 발송됨 — 스킵')
    sys.exit(1)
