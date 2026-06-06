"""
Threads API 토큰 재발급 스크립트
1. 브라우저에서 OAuth 인증 (Threads 로그인)
2. 단기 토큰 → 장기 토큰(60일) 교환
3. threads_config.json 자동 업데이트
4. 오늘 포스팅 즉시 실행
"""
import json, sys, time, urllib.request, urllib.parse, urllib.error
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

CONFIG_FILE = Path('/Users/uneedcomms/thread/data/threads_config.json')

auth_code = None

class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if 'code' in params:
            auth_code = params['code'][0]
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'<html><body><h2>&#10003; &#51064;&#51613; &#50756;&#47308;! &#51060; &#52285;&#51012; &#45803;&#44256; &#53552;&#48120;&#45184;&#47196; &#46028;&#50500;&#44032;&#49464;&#50836;.</h2></body></html>')
            print(f"\n✅ 인증 코드 수신 완료")
        elif 'error' in params:
            err = params.get('error_description', ['unknown'])[0]
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f'<html><body><h2>오류: {err}</h2></body></html>'.encode())
            print(f"\n❌ OAuth 오류: {err}")
        else:
            self.send_response(200)
            self.end_headers()

    def log_message(self, *args):
        pass  # 서버 로그 숨김


def exchange_code_for_token(code: str, app_id: str, app_secret: str) -> str:
    """인증 코드 → 단기 토큰"""
    params = {
        'client_id': app_id,
        'client_secret': app_secret,
        'grant_type': 'authorization_code',
        'redirect_uri': 'http://localhost:8080/callback',
        'code': code,
    }
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        'https://graph.threads.net/oauth/access_token',
        data=data, method='POST'
    )
    try:
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise Exception(f"토큰 교환 실패: {e.read().decode()}")
    if 'access_token' not in result:
        raise Exception(f"토큰 교환 실패: {result}")
    return result['access_token']


def exchange_for_long_lived(short_token: str, app_secret: str) -> dict:
    """단기 토큰 → 장기 토큰 (60일)"""
    url = (
        f"https://graph.threads.net/access_token"
        f"?grant_type=th_exchange_token"
        f"&client_secret={urllib.parse.quote(app_secret)}"
        f"&access_token={urllib.parse.quote(short_token)}"
    )
    try:
        with urllib.request.urlopen(url) as r:
            result = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise Exception(f"장기 토큰 교환 실패: {e.read().decode()}")
    if 'access_token' not in result:
        raise Exception(f"장기 토큰 없음: {result}")
    return result


def get_user_id(token: str) -> str:
    url = f"https://graph.threads.net/v1.0/me?fields=id,username&access_token={urllib.parse.quote(token)}"
    with urllib.request.urlopen(url) as r:
        result = json.loads(r.read())
    return result['id'], result.get('username', '')


if __name__ == '__main__':
    config = json.loads(CONFIG_FILE.read_text())
    app_id = config['app_id']
    app_secret = config['app_secret']

    # 로컬 콜백 서버 시작
    server = HTTPServer(('localhost', 8080), CallbackHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    # OAuth URL 생성 및 브라우저 열기
    oauth_url = (
        f"https://www.threads.net/oauth/authorize"
        f"?client_id={app_id}"
        f"&redirect_uri=http://localhost:8080/callback"
        f"&scope=threads_basic,threads_content_publish"
        f"&response_type=code"
    )

    print("🔐 브라우저에서 Threads 로그인 후 인증해주세요...")
    print(f"   URL: {oauth_url}\n")

    import webbrowser
    webbrowser.open(oauth_url)

    # 최대 2분 대기
    timeout = 120
    start = time.time()
    while auth_code is None and (time.time() - start) < timeout:
        time.sleep(0.5)

    server.shutdown()

    if auth_code is None:
        print("❌ 타임아웃 — 인증 코드를 받지 못했습니다.")
        sys.exit(1)

    print("🔄 단기 토큰 교환 중...")
    short_token = exchange_code_for_token(auth_code, app_id, app_secret)

    print("🔄 장기 토큰(60일) 교환 중...")
    long_token_result = exchange_for_long_lived(short_token, app_secret)
    long_token = long_token_result['access_token']
    expires_in = long_token_result.get('expires_in', 5184000)
    print(f"   만료: {expires_in // 86400}일 후")

    print("🔄 user_id 확인 중...")
    user_id, username = get_user_id(long_token)
    print(f"   @{username} (id: {user_id})")

    # config 업데이트
    config['threads_access_token'] = long_token
    config['threads_user_id'] = user_id
    config['threads_username'] = username
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False))
    print(f"✅ threads_config.json 업데이트 완료")

    # 오늘 포스팅 즉시 실행
    print("\n📤 오늘 오전 포스팅 실행 중...")
    import subprocess
    result = subprocess.run(
        [sys.executable, '/Users/uneedcomms/thread/post_threads.py'],
        capture_output=False
    )
    sys.exit(result.returncode)
