"""
make_card.py — 글 본문을 받아 Threads용 카드 PNG를 자동 생성.

claude/viral-writer가 쓴 글의 첫 줄(훅)을 카드 메인 타이포로,
다음 문장을 부연으로 깔아 1080x1080 카드를 Chrome headless로 렌더한다.
로컬(/Applications Chrome)·클라우드(Actions chromium) 양쪽에서 동작.

사용: python3 make_card.py --content "본문..." --out data/cards/card_2026-06-08.png
"""
import argparse
import html as html_mod
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime('%Y-%m-%d')

BASE_DIR = Path(__file__).resolve().parent
CARDS_DIR = BASE_DIR / 'data' / 'cards'
POSTS_FILE = BASE_DIR / 'data' / 'posts.json'


def content_from_posts(slot: str) -> str:
    """posts.json에서 오늘 슬롯 글의 content를 읽는다."""
    if not POSTS_FILE.exists():
        return ''
    posts = json.loads(POSTS_FILE.read_text(encoding='utf-8'))
    is_evening = slot == 'evening'
    p = next((x for x in posts if x.get('date') == TODAY and bool(x.get('evening')) == is_evening), None)
    return (p.get('content', '') if p else '')

TEMPLATE = """<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
:root {{
  --bg-0: oklch(22% 0.04 250); --bg-1: oklch(30% 0.06 255);
  --ink: oklch(97% 0.01 250); --muted: oklch(72% 0.02 250); --accent: oklch(80% 0.17 165);
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  width:1080px; height:1080px; font-family:'Pretendard',system-ui,sans-serif;
  background:radial-gradient(120% 120% at 15% 10%, var(--bg-1), var(--bg-0) 60%);
  color:var(--ink); display:flex; flex-direction:column; justify-content:space-between;
  padding:96px 88px; position:relative; overflow:hidden;
  word-break:keep-all; overflow-wrap:break-word; line-break:strict;
}}
body::after {{ content:''; position:absolute; inset:0;
  background:radial-gradient(60% 40% at 90% 95%, oklch(80% 0.17 165 / 0.18), transparent 70%); }}
.tag {{ font-size:26px; font-weight:600; letter-spacing:0.18em; color:var(--accent); text-transform:uppercase; }}
.hook {{ font-size:{hook_size}px; font-weight:800; line-height:1.18; letter-spacing:-0.02em; }}
.sub {{ font-size:38px; font-weight:500; line-height:1.5; color:var(--muted); margin-top:36px; max-width:84%; }}
.foot {{ display:flex; align-items:center; gap:18px; font-size:30px; font-weight:600; }}
.dot {{ width:14px; height:14px; border-radius:50%; background:var(--accent); }}
.handle {{ color:var(--muted); font-weight:500; }}
</style></head><body>
<div class="tag">AI · 자사몰 실무</div>
<div>
  <div class="hook">{hook}</div>
  {sub_block}
</div>
<div class="foot"><span class="dot"></span>@sebsonthebeach <span class="handle">· Threads</span></div>
</body></html>"""


def split_hook(content: str) -> tuple[str, str]:
    """첫 줄(또는 첫 문장)을 훅, 다음 1~2문장을 부연으로."""
    lines = [l.strip() for l in content.split('\n') if l.strip()]
    if not lines:
        return '', ''
    hook = lines[0]
    sub = ' '.join(lines[1:]).strip()
    # 부연은 너무 길면 자름 (카드 균형)
    if len(sub) > 90:
        cut = sub[:90]
        # 문장부호에서 끊기
        for p in ('. ', '? ', '! ', '함 ', '음 ', '임 '):
            idx = cut.rfind(p)
            if idx > 40:
                cut = cut[:idx + 1]
                break
        sub = cut.strip()
    return hook, sub


def chrome_bin() -> str:
    candidates = [
        os.environ.get('CHROME_BIN'),
        shutil.which('google-chrome'),
        shutil.which('google-chrome-stable'),
        shutil.which('chromium'),
        shutil.which('chromium-browser'),
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    raise RuntimeError('Chrome/Chromium 실행파일을 찾을 수 없음 (CHROME_BIN 지정 필요)')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--content', help='카드 본문 직접 지정')
    ap.add_argument('--slot', choices=['morning', 'evening'], help='posts.json 오늘 슬롯 글로 자동')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    content = args.content or (content_from_posts(args.slot) if args.slot else '')
    if not content:
        print('❌ 카드 본문 없음 (--content 또는 --slot으로 지정, 오늘 글 없음)')
        return 1

    hook, sub = split_hook(content)
    if not hook:
        print('❌ 본문 비어있음 — 카드 생성 안 함')
        return 1

    # 훅 길이에 따라 폰트 크기 자동 조절 (긴 훅은 작게)
    hook_size = 92 if len(hook) <= 22 else (76 if len(hook) <= 34 else 62)
    sub_block = f'<div class="sub">{html_mod.escape(sub)}</div>' if sub else ''
    html_str = TEMPLATE.format(
        hook=html_mod.escape(hook).replace('\n', '<br>'),
        sub_block=sub_block,
        hook_size=hook_size,
    )

    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    render_html = CARDS_DIR / '_render.html'
    render_html.write_text(html_str, encoding='utf-8')

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [chrome_bin(), '--headless', '--disable-gpu', '--hide-scrollbars',
         '--force-device-scale-factor=1', '--window-size=1080,1080',
         f'--screenshot={out}', f'file://{render_html}'],
        check=True, capture_output=True, timeout=60,
    )
    print(f'✅ 카드 생성: {out} (훅 {len(hook)}자, 폰트 {hook_size}px)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
