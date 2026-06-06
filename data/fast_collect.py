import sys, json, csv
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, '/sessions/clever-dreamy-brahmagupta/.local/lib/python3.10/site-packages')

KST = timezone(timedelta(hours=9))
today = datetime.now(KST).strftime('%Y-%m-%d')
data_dir = Path('/sessions/clever-dreamy-brahmagupta/mnt/thread/data')
session_file = Path('/sessions/clever-dreamy-brahmagupta/mnt/thread/session_state.json')

# Today's keywords
keywords = ['AI활용', 'GPT활용', '업무자동화']

# Already engaged post IDs
engaged_ids = set()
log_file = data_dir / 'engage_log.csv'
if log_file.exists():
    with open(log_file) as f:
        for row in csv.DictReader(f):
            engaged_ids.add(row.get('post_id', ''))

print(f"Already engaged: {len(engaged_ids)} posts")

with open(session_file) as f:
    state_data = json.load(f)

from playwright.sync_api import sync_playwright

posts = []
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
    ctx = browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        storage_state=state_data
    )
    page = ctx.new_page()
    
    print("Checking login...", flush=True)
    page.goto('https://www.threads.com/', wait_until='domcontentloaded', timeout=20000)
    page.wait_for_timeout(2000)
    
    if 'login' in page.url:
        print("SESSION EXPIRED")
        browser.close()
        sys.exit(1)
    
    print("Login OK", flush=True)
    
    for kw in keywords[:1]:  # Just first keyword for speed
        print(f"Searching: {kw}", flush=True)
        page.goto(f'https://www.threads.com/search?q={kw}&serp_type=default',
                  wait_until='domcontentloaded', timeout=15000)
        page.wait_for_timeout(3000)
        
        links = page.evaluate("""
            () => {
                const anchors = document.querySelectorAll('a[href*="/post/"]');
                const seen = new Set();
                const results = [];
                for (const a of anchors) {
                    const href = a.getAttribute('href');
                    if (href && !seen.has(href)) {
                        seen.add(href);
                        results.push(href);
                    }
                    if (results.length >= 8) break;
                }
                return results;
            }
        """)
        print(f"Found {len(links)} post links", flush=True)
        
        for href in links[:4]:
            post_id = href.split('/post/')[-1].split('/')[0].split('?')[0]
            if post_id in engaged_ids:
                continue
            
            try:
                page.goto(f'https://www.threads.com{href}', wait_until='domcontentloaded', timeout=10000)
                page.wait_for_timeout(1500)
                
                text = page.evaluate("""
                    () => {
                        const els = document.querySelectorAll('[data-pressable-container] span, article span');
                        return Array.from(els).map(e => e.innerText).filter(t => t && t.length > 20).slice(0,3).join(' | ');
                    }
                """)
                
                author_match = href.split('/@')
                author = author_match[1].split('/')[0] if len(author_match) > 1 else 'unknown'
                
                if text and len(text) > 30:
                    posts.append({
                        'post_id': post_id,
                        'author': author,
                        'url': f'https://www.threads.com{href}',
                        'keyword': kw,
                        'text': text[:300],
                        'thread_context': '',
                        'like_count': 0,
                        'post_type': 'general',
                        'priority_score': 5,
                        'collected_at': datetime.now(KST).isoformat()
                    })
                    print(f"  Collected: @{author} | {text[:60]}", flush=True)
                    if len(posts) >= 3:
                        break
            except Exception as e:
                print(f"  Skip {post_id}: {e}", flush=True)
    
    browser.close()

result = {
    'date': today,
    'keywords': keywords,
    'posts': posts,
    'status': 'pending'
}

out_file = data_dir / 'pending_posts.json'
with open(out_file, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"\n✅ Collected {len(posts)} posts → saved to pending_posts.json")
