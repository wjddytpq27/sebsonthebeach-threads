# @sebsonthebeach Threads 성장 에이전트

## 프로젝트 목적
Threads 계정 @sebsonthebeach 자동 운영
- 매일 포스팅 자동화 (Threads API 직접 호출)
- 타 계정 댓글 engagement (Claude in Chrome)
- 팔로워/인사이트 트래킹

---

## 파일 구조

```
/Users/uneedcomms/thread/
├── post_threads.py          # ★ 메인 포스팅 스크립트 (Threads API 직접 호출)
├── track.py                 # 팔로워 + 포스트 인사이트 수집 (Threads API, Playwright 없음)
├── growth_analyst.py        # 성과 분석 → team_signal.json 생성
├── auto_engage.py           # 키워드 검색 기반 자동 댓글 (Playwright)
├── renew_session.py         # Threads 세션 갱신 (브라우저 직접 로그인)
├── session_state.json       # Threads 브라우저 세션 (댓글용)
└── data/
    ├── posts.json           # 예약 포스트 목록 (날짜별)
    ├── threads_config.json  # Threads API 토큰 + user_id ← 절대 공유 금지
    ├── slack_config.json    # Slack webhook URL
    ├── team_signal.json     # ★ 팀 공유 브리핑 (growth_analyst → 전 에이전트)
    ├── growth_strategy.json # viral-writer용 전략 (team_signal 서브셋)
    ├── today_trend.json     # trend-scout 수집 트렌드
    ├── engage_log.csv       # 댓글 달았던 post_id 기록 (중복 방지용)
    ├── insights.csv         # 내 포스트 좋아요/댓글/views 누적
    └── follower_log.csv     # 날짜별 팔로워 수 누적
```

## 에이전트 팀 소통 구조

```
10:02  trend-scout       → team_signal 읽고 → today_trend.json
10:12  viral-writer      → team_signal + today_trend → posts.json (내일 날짜 2개)
10:35  post_threads.py   → API 포스팅 (morning)
14:00  hunter-engager    → team_signal.keyword_performance 기반 댓글
20:00  post_threads.py   → API 포스팅 (evening)
22:45  track.py          → insights.csv, follower_log.csv
22:45  growth_analyst.py → team_signal.json (status: normal/stall/emergency)
                           ↓ 팀 전체에 Slack 브리핑
```

team_signal.json status 기준:
- `normal`: 각자 평소 기준
- `stall` (3일 정체): viral-writer 훅 강도↑, hunter-engager 목표 35개+영어 40%
- `emergency` (5일+): 완전히 다른 각도, 목표 40개+영어 50%, 팔로워 1만+ 계정만 타겟

---

## Threads API 세팅

- **앱 이름**: thread (Meta Developer)
- **Threads 앱 ID**: `9717907691188907`
- **user_id**: `35270768892567477` (@sebsonthebeach)
- **액세스 토큰**: `data/threads_config.json`에 저장 (60일 만료, 자동 갱신)
- **토큰 갱신**: `post_threads.py` 실행 때마다 자동 갱신 시도

### 포스팅 방법 (2단계)
```python
# 1. container 생성
POST https://graph.threads.net/v1.0/{user_id}/threads
params: media_type=TEXT, text=내용, topic_tag=AI_THREADS, access_token=TOKEN

# 2. 발행
POST https://graph.threads.net/v1.0/{user_id}/threads_publish
params: creation_id=container_id, access_token=TOKEN
```

---

## post_threads.py 동작 방식

```bash
python3 /Users/uneedcomms/thread/post_threads.py
```

1. `data/posts.json`에서 오늘 날짜 포스트 읽기
2. Threads API로 오늘 이미 올린 글 있는지 확인 (중복 방지)
3. 없으면 포스팅 (topic_tag 포함)
4. 토큰 자동 갱신
5. 성공/실패 Slack 알림

---

## posts.json 구조

```json
[
  {
    "date": "2026-05-22",
    "content": "포스트 본문...",
    "reply": "첫 댓글로 달 내용 (선택)",
    "topic": "AI_THREADS"
  }
]
```

### 유효한 topic_tag 값 (API 검증 완료)
- `AI_THREADS` — AI/자동화 관련 글
- `BUSINESS_ENTREPENEURSHIP` — 창업/이커머스/마케팅
- `PERSONAL_FINANCE` — 재테크/수익 관련
- `CAREERS_JOBS` — 커리어/직장

---

## 댓글 Engagement 워크플로우

**브라우저 자동화 필요 (Claude in Chrome MCP)**

1. 날짜 % 10으로 키워드 선택
```
0: AI활용/ChatGPT활용  1: 부업/N잡  2: 퍼스널브랜딩
3: 온라인창업/1인기업  4: 자사몰/카페24  5: 자동화/노코드
6: 디지털마케팅  7: 재테크/투자  8: 스타트업  9: 이커머스
```

2. `https://www.threads.com/search?q={키워드}` 검색
3. 포스트별 navigate → 텍스트/좋아요 수 추출
4. 필터: 좋아요 5 미만/200 초과/engage_log 중복 → 스킵
5. AI로 댓글 생성 (반말 구어체, 자사몰/이커머스 실무자 포지션)
6. 댓글 게시 → `engage_log.csv` 기록

**댓글 작성 원칙**
- 포지션: 자사몰/이커머스 실무자, AI·자동화 써본 사람
- 말투: 완전 반말 구어체
- 금지: "좋은 글", "공감합니다", 내용 단순 반복
- 기준: "이 댓글 보고 프로필 클릭할 이유 있나?" → 없으면 스킵

---

## 팔로워 트래킹

`track.py` 또는 Claude in Chrome으로 프로필 페이지 방문 시 수집:
```javascript
// 팔로워 수 추출
const labels = [...document.querySelectorAll('[aria-label]')];
for (const el of labels) {
  const m = (el.getAttribute('aria-label')||'').match(/([\d,]+)\s*(팔로워|follower)/i);
  if (m) return parseInt(m[1].replace(/,/g, ''));
}
```
→ `data/follower_log.csv`에 날짜별 누적

---

## Slack 알림

- `data/slack_config.json` → `webhook_url` 키
- 포스팅 성공/실패 자동 알림
- 일간 브리핑: 팔로워 수 + 7일 증감 + 포스트 반응

---

## crontab 설정 (Mac에서 직접 실행 권장)

```bash
# crontab -e 로 추가
21 10 * * * /usr/bin/python3 /Users/uneedcomms/thread/post_threads.py
```

Mac 켜져 있으면 매일 10:21 KST 자동 실행. Cowork/Claude 서버 의존 없음.

---

## 현재 상태 (2026-05-22 기준)

- ✅ Threads API 직접 포스팅 구축 완료
- ✅ 중복 포스팅 방지 로직 추가
- ✅ topic_tag 자동 배정 (posts.json에 `topic` 필드)
- ✅ 팔로워 트래킹 로직 추가
- ⚠️ posts.json이 로컬 Mac에만 있음 → Mac 꺼지면 cron도 안 돌아감
- ⚠️ 댓글 engagement는 Claude in Chrome MCP 필요

## 남은 과제

1. **posts.json GitHub 업로드** — Mac 꺼져도 접근 가능하게
2. **crontab 등록** — Cowork scheduled task 대신 Mac cron으로 교체
3. **댓글 engagement Claude Code 연동** — Claude in Chrome MCP 설정
