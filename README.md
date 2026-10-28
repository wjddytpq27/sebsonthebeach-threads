# @sebsonthebeach Threads Growth Agent

Threads 계정 자동 운영 시스템. Claude 에이전트 여러 개가 파이프라인으로 연결돼 매일 돌아간다.

## 구조

```
trend-scout (10:02)
    ↓ today_trend.json
viral-writer (10:12)
    ↓ posts.json
post_threads.py (10:21 / 20:00)   ← Threads API 직접 발행
    ↓
track.py (22:00)                   ← 팔로워 수·포스트 인게이지 수집
    ↓
growth-analyst (22:30)             ← 성과 분석 + 팀 신호 생성
    ↓ team_signal.json
hunter-engager (10:00~19:00, 평일) ← 타겟 포스트 맥락 댓글
```

`growth-analyst`가 분석 결과를 바탕으로 `viral-writer`와 `hunter-engager`의 프롬프트를 직접 업데이트 → 다음 날 에이전트들이 바뀐 전략으로 실행되는 자기강화 루프.

## 에이전트 역할

| 에이전트 | 역할 |
|---|---|
| `trend-scout` | 해외 AI 뉴스·GitHub Trending 크롤링 → 오늘 소재 선정 |
| `viral-writer` | 소재 → Threads 포스트 2개 생성 (오전 트렌드 / 저녁 핫테이크) |
| `growth-analyst` | 팔로워 추이·포스트 성과·키워드 상관 분석 → 내일 전략 지시 |
| `hunter-engager` | 키워드 검색 → 맥락 댓글 게시 (Playwright) |
| `builder-scout` | 실제 작업 로그에서 빌더 노트 소재 자동 발굴 (주 1회) |

## 기술 스택

- **Claude Agent SDK** (`claude -p ... --agent ...`) — 에이전트 정의는 `~/.claude/agents/`
- **Threads API** — 포스트 발행, 중복 방지 (container → publish 2단계)
- **Playwright** — 댓글 engagement (브라우저 자동화)
- **crontab** — 전체 파이프라인 스케줄링 (Mac 로컬)
- **GitHub Actions** — 백업 실행 경로 (`.github/workflows/`)

## 파일 구조

```
├── post_threads.py       # Threads API 포스팅 (토큰 자동 갱신)
├── track.py              # 팔로워·인게이지 데이터 수집
├── auto_engage.py        # 댓글 engagement (Playwright)
├── growth_analyst.py     # 레거시 분석 스크립트 (에이전트로 대체됨)
├── ledger.py             # 포스트별 팔로워 귀인 원장
├── bandit.py             # 슬롯별 arm 탐색/활용 배분 (멀티암드 밴딧)
├── session_health.py     # 댓글 세션 상태 모니터링
├── prompts/              # 에이전트 프롬프트 파일
│   ├── trend_scout.txt
│   ├── viral_writer.txt
│   ├── hunter_engager.txt
│   ├── builder_scout.txt
│   └── growth_analyst.txt
└── .github/workflows/    # GH Actions 백업 파이프라인
```

## 설계 포인트

**자기강화 루프**
`growth-analyst`가 매일 밤 팔로워 추이와 포스트 성과를 분석하고, 그 결과를 `viral-writer`·`hunter-engager` 프롬프트에 직접 주입한다. 어제 잘 된 훅 스타일, 효과 없는 키워드, 오늘 목표 수치가 내일 에이전트의 행동을 바꾼다.

**멀티암드 밴딧 (`bandit.py`)**
포스트 스타일(트렌드 스카우트 / 핫테이크 / 빌더 노트)을 arm으로 두고 슬롯별 탐색/활용 비율을 조정. `ledger.py`가 포스트별 팔로워 순증을 귀인해서 밴딧의 reward로 넘긴다.

**댓글 가드 (`engage_post.py`)**
Playwright 댓글 게시 시 앞글자 씹힘(포커스 레이스), LLM 되묻기 응답이 공개 댓글로 올라가는 사고를 막는 검증 레이어.
