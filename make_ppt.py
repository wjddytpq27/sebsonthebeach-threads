from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt
import copy

# ── 컬러 팔레트 ──────────────────────────────────────────────
BG_DARK    = RGBColor(0x0D, 0x0D, 0x0D)   # 거의 검정
BG_CARD    = RGBColor(0x1A, 0x1A, 0x2E)   # 딥 네이비
ACCENT     = RGBColor(0x7C, 0x3A, 0xED)   # 바이올렛
ACCENT2    = RGBColor(0x06, 0xB6, 0xD4)   # 시안
ACCENT3    = RGBColor(0x10, 0xB9, 0x81)   # 에메랄드
TEXT_WHITE = RGBColor(0xFF, 0xFF, 0xFF)
TEXT_GRAY  = RGBColor(0xA1, 0xA1, 0xAA)
TEXT_DIM   = RGBColor(0x52, 0x52, 0x5B)
YELLOW     = RGBColor(0xFB, 0xBF, 0x24)
RED        = RGBColor(0xEF, 0x44, 0x44)

W = Inches(13.33)
H = Inches(7.5)

prs = Presentation()
prs.slide_width  = W
prs.slide_height = H

def blank_slide(prs):
    layout = prs.slide_layouts[6]  # blank
    return prs.slides.add_slide(layout)

def bg(slide, color=BG_DARK):
    from pptx.util import Inches
    shape = slide.shapes.add_shape(1, 0, 0, W, H)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    return shape

def rect(slide, x, y, w, h, fill, radius=False):
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    shape = slide.shapes.add_shape(1, x, y, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.fill.background()
    return shape

def add_text(slide, text, x, y, w, h, size=20, bold=False, color=TEXT_WHITE,
             align=PP_ALIGN.LEFT, italic=False, wrap=True):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = wrap
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.name = "Apple SD Gothic Neo"
    return tb

def add_multiline(slide, lines, x, y, w, h, size=16, color=TEXT_WHITE,
                  line_spacing=1.4, bold_first=False):
    from pptx.oxml.ns import qn
    from lxml import etree
    import copy
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    for i, line in enumerate(lines):
        if i == 0:
            p = tf.paragraphs[0]
        else:
            p = tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        run = p.add_run()
        run.text = line
        run.font.size = Pt(size)
        run.font.color.rgb = color
        run.font.name = "Apple SD Gothic Neo"
        run.font.bold = (bold_first and i == 0)
    return tb

def pill(slide, x, y, w, h, text, fill=ACCENT, tsize=13):
    r = rect(slide, x, y, w, h, fill)
    add_text(slide, text, x, y, w, h, size=tsize, bold=True,
             color=TEXT_WHITE, align=PP_ALIGN.CENTER)
    return r

def divider(slide, y, color=TEXT_DIM):
    r = slide.shapes.add_shape(1, Inches(0.6), y, W - Inches(1.2), Pt(1))
    r.fill.solid()
    r.fill.fore_color.rgb = color
    r.line.fill.background()

# ══════════════════════════════════════════════════════════════
# SLIDE 1 — COVER
# ══════════════════════════════════════════════════════════════
s1 = blank_slide(prs)
bg(s1)

# gradient bar 상단
rect(s1, 0, 0, W, Inches(0.08), ACCENT)

# 태그
pill(s1, Inches(0.8), Inches(1.4), Inches(3.2), Inches(0.45),
     "MARKETING × AI CASE STUDY", ACCENT, 12)

# 타이틀
add_text(s1, "AI 에이전트 팀이\n운영하는 Threads 계정",
         Inches(0.8), Inches(2.1), Inches(8), Inches(2.2),
         size=52, bold=True, color=TEXT_WHITE)

# 서브
add_text(s1, "@sebsonthebeach — 매일 자동 포스팅·댓글·분석·전략 수정까지",
         Inches(0.8), Inches(4.5), Inches(9), Inches(0.6),
         size=20, color=TEXT_GRAY)

# 우측 장식 블록
rect(s1, Inches(10.5), Inches(1.2), Inches(2.3), Inches(5.5), BG_CARD)
add_text(s1, "6", Inches(10.5), Inches(1.5), Inches(2.3), Inches(1.4),
         size=72, bold=True, color=ACCENT, align=PP_ALIGN.CENTER)
add_text(s1, "AI Agents", Inches(10.5), Inches(2.9), Inches(2.3), Inches(0.5),
         size=16, color=TEXT_GRAY, align=PP_ALIGN.CENTER)
divider(s1, Inches(3.5))  # rough
add_text(s1, "24/7", Inches(10.5), Inches(3.7), Inches(2.3), Inches(1.0),
         size=48, bold=True, color=ACCENT2, align=PP_ALIGN.CENTER)
add_text(s1, "자동 운영", Inches(10.5), Inches(4.7), Inches(2.3), Inches(0.5),
         size=16, color=TEXT_GRAY, align=PP_ALIGN.CENTER)
add_text(s1, "Self-Improving", Inches(10.5), Inches(5.5), Inches(2.3), Inches(0.5),
         size=14, bold=True, color=ACCENT3, align=PP_ALIGN.CENTER)

# 하단 바
rect(s1, 0, H - Inches(0.55), W, Inches(0.55), BG_CARD)
add_text(s1, "Uneedcomms  ·  2026",
         Inches(0.8), H - Inches(0.52), Inches(4), Inches(0.5),
         size=13, color=TEXT_DIM)

# 스크립트 노트
s1.notes_slide.notes_text_frame.text = (
    "안녕하세요. 오늘은 마케팅에서 AI를 실제로 어떻게 활용하고 있는지, "
    "저희가 직접 운영 중인 사례를 공유드리려 합니다.\n\n"
    "@sebsonthebeach라는 Threads 계정인데요, "
    "이 계정은 사람이 직접 글 쓰거나 댓글 달지 않습니다. "
    "AI 에이전트 6개가 팀처럼 역할을 나눠서 매일 돌아가고 있습니다. "
    "단순 자동화가 아니라, 성과 데이터를 보고 스스로 전략을 바꾸는 구조입니다. "
    "이게 어떻게 가능한지 하나씩 설명드리겠습니다."
)

# ══════════════════════════════════════════════════════════════
# SLIDE 2 — 전체 구조 (타임라인)
# ══════════════════════════════════════════════════════════════
s2 = blank_slide(prs)
bg(s2)

add_text(s2, "하루가 어떻게 돌아가나", Inches(0.7), Inches(0.3), Inches(9), Inches(0.7),
         size=36, bold=True)
add_text(s2, "6개 에이전트 · 11개 자동 실행 · 사람 개입 0",
         Inches(0.7), Inches(1.05), Inches(9), Inches(0.45), size=16, color=TEXT_GRAY)
divider(s2, Inches(1.55))

# 타임라인 아이템
steps = [
    ("10:02", "Trend Scout",    ACCENT,  "GitHub Trending·뉴스·HackerNews 수집\n→ 오늘 쓸 소재 + 각도 결정"),
    ("10:12", "Viral Writer",   ACCENT2, "소재 + 성과 데이터 기반으로 포스트 2개 작성\n→ posts.json 저장"),
    ("10:20", "Fact Checker",   YELLOW,  "사실 오류 감지 시 자동 수정 또는 블록\n→ 잘못된 정보 게시 방지"),
    ("10:35", "Post (오전)",    ACCENT3, "Threads API 직접 호출 → 포스팅\n→ 중복·토큰 자동 관리"),
    ("14:00", "Hunter Engager", ACCENT,  "10개 세트 하루 1세트씩 순환 (세트당 키워드 3개)\n→ Playwright 브라우저 자동화 (API 미지원)"),
    ("20:00", "Post (저녁)",    ACCENT3, "Threads API 직접 호출 → 저녁 포스팅"),
    ("22:00", "Track",          TEXT_GRAY,"팔로워 수·포스트 좋아요/댓글/조회수 수집"),
    ("22:30", "Follow Attr",   TEXT_GRAY,"댓글 키워드 → 팔로워 증감 귀속 분석\n→ follow_attribution.json 저장"),
    ("22:45", "Growth Analyst", RED,     "성과 분석 + 악마의 변호인 자기반박\n→ team_signal.json 업데이트"),
    ("매주 월", "Strategist",   YELLOW,  "주간 성과 패턴 분석\n→ 에이전트 프롬프트 직접 재작성"),
]

col_x   = [Inches(0.55), Inches(1.55), Inches(3.1), Inches(5.8)]
row_h   = Inches(0.68)
start_y = Inches(1.75)

# 세로선
rect(s2, Inches(1.45), start_y, Pt(2), row_h * len(steps) - Inches(0.15), TEXT_DIM)

for i, (time, agent, color, desc) in enumerate(steps):
    y = start_y + i * row_h
    add_text(s2, time, col_x[0], y, Inches(0.9), row_h,
             size=13, bold=True, color=color, align=PP_ALIGN.RIGHT)
    dot = s2.shapes.add_shape(9, Inches(1.38), y + Inches(0.18), Inches(0.16), Inches(0.16))
    dot.fill.solid(); dot.fill.fore_color.rgb = color
    dot.line.fill.background()
    pill(s2, col_x[1], y + Inches(0.06), Inches(1.45), Inches(0.36), agent, BG_CARD, 12)
    add_text(s2, " " + color.__class__.__name__, col_x[1], y, Inches(0.1), Inches(0.1), size=1, color=BG_DARK)
    add_text(s2, desc, col_x[2], y, Inches(4.0), row_h,
             size=12, color=TEXT_GRAY)

# ── 오른쪽: Slack 브리핑 미리보기 ──────────────────────────
rect(s2, Inches(7.6), Inches(1.75), Inches(5.3), Inches(5.5), RGBColor(0x0F, 0x0F, 0x1E))
rect(s2, Inches(7.6), Inches(1.75), Inches(5.3), Inches(0.38), RGBColor(0x4A, 0x15, 0x4B))  # Slack 보라
add_text(s2, "# threads-growth  ·  Slack 일간 브리핑",
         Inches(7.75), Inches(1.78), Inches(5.0), Inches(0.32),
         size=11, bold=True, color=TEXT_WHITE)

slack_lines = [
    (ACCENT,  "📊 계정 현황"),
    (TEXT_GRAY,"팔로워: 155명  |  수집 포스트: 20개"),
    (ACCENT2, "⚡ 최고 반응 포스트"),
    (TEXT_GRAY,'❤️ 37  댓글 24  score 124  (7일 평균 5.6 대비 +118)'),
    (TEXT_GRAY,'"바이브코딩, 지금도 믿고 있어?..."'),
    (ACCENT3, "💬 댓글 답장 — 10개 완료"),
    (TEXT_GRAY,'"1주일만에 터지는 거 진짜 봤어 ㅋㅋ"'),
    (YELLOW,  "⚠️ 팩트체커 이슈"),
    (TEXT_GRAY,"Search Info Agents 명칭 수정됨"),
    (ACCENT3, "✅ 저녁 포스팅 성공"),
    (TEXT_GRAY,"구글이 내 고객 대신 검색하기 시작했음..."),
]

for i, (col, line) in enumerate(slack_lines):
    add_text(s2, line, Inches(7.78), Inches(2.22) + i * Inches(0.29),
             Inches(5.0), Inches(0.28), size=10.5, color=col)

s2.notes_slide.notes_text_frame.text = (
    "━━━ 일반 발표용 ━━━\n\n"
    "출근하면 팀이 이미 돌아가고 있습니다. 트렌드 스카우트가 오늘 가장 뜨거운 소재를 긁어오고, 바이럴 라이터가 그 소재로 포스트 2개를 씁니다. 과거 성과 데이터를 보고 쓰기 때문에 막연히 쓰는 게 아닙니다.\n"
    "순서대로 하는 이유는 각 단계 결과물이 다음 단계 재료이기 때문입니다. 요리에 비유하면 장을 봐야 요리하고, 요리가 돼야 맛볼 수 있는 것처럼요.\n"
    "오전에 한 번, 저녁에 한 번 포스팅합니다. 오전은 출근 후 첫 SNS 확인 시간대, 저녁은 퇴근 후 황금 시간대입니다.\n"
    "오후엔 댓글을 달러 다닙니다. 점심 이후 SNS 피크 시간대입니다.\n"
    "자기 전에 하루 반응을 분석하고 팀 전체에 내일 방향을 공유합니다. 반응이 충분히 쌓인 다음에 집계해야 의미 있어서 밤늦게 돕니다.\n"
    "매주 월요일엔 전략가가 지난 주 성과로 에이전트 행동 지침 자체를 다시 씁니다. 자기진화가 여기서 일어납니다.\n\n"
    "그리고 이 팀은 Slack으로 보고합니다. 에이전트가 뭔가 하고 나면 Slack에 실시간으로 내용을 올립니다. 오른쪽에 보시는 게 실제 브리핑 예시입니다. 팔로워 증감, 어떤 글이 잘 됐는지, 오늘 어떻게 움직이겠다는 방향까지 매일 아침 받아볼 수 있습니다. 댓글을 달고 나서도 어디에 어떤 댓글을 달았는지 리포트가 옵니다.\n\n"
    "━━━ 개발자 질문 대응용 ━━━\n\n"
    "Q. Slack 알림은 어떻게 구현했나?\n"
    "→ 각 스크립트에 urllib.request로 Slack Incoming Webhook POST 호출. 라이브러리 의존 없이 표준 라이브러리만 사용.\n"
    "→ slack_config.json에 webhook_url 저장. 포스팅 성공/실패, 댓글 리포트, 일간 브리핑 등 이벤트마다 다른 포맷으로 전송.\n\n"
    "Q. 왜 에이전트 하나로 안 하나?\n"
    "→ 컨텍스트 윈도우 비용 문제: 트렌드 수집 결과 + 성과 데이터 + 글 작성 + 팩트체크를 한 번에 처리하면 토큰이 폭증.\n"
    "→ 단일 책임 원칙: 에이전트마다 역할이 다르면 프롬프트 최적화가 가능하고, 어디서 품질이 떨어지는지 추적 가능.\n"
    "→ 자기진화 구조: Strategist가 'viral-writer 프롬프트만 수정'할 수 있는 게 역할 분리 덕분. 하나로 묶이면 불가능.\n\n"
    "Q. 왜 저 시간대?\n"
    "→ 10:02: Mac 켜지는 시간에 맞춰 설계. cron은 Mac이 꺼진 동안 밀린 작업을 실행하지 않아서 출근 후 바로 돌아가도록 10시 이후로 배치.\n"
    "→ 10:35: 트렌드 수집(10:02) → 포스트 작성(10:12) → 팩트체크(10:20) 완료 후 여유 있게 포스팅. 정각을 피하는 건 cron 부하 분산 습관.\n"
    "→ 22:45: track.py(22:00) + follow_attributor.py(22:30) 완료 후 데이터 읽어야 해서 순서 보장.\n\n"
    "참고. GitHub Trending이란?\n"
    "→ 전 세계 개발자들이 오늘 가장 많이 스타(★)를 누른 오픈소스 프로젝트 순위 페이지. AI·개발 판에서 지금 뭐가 뜨는지 한눈에 볼 수 있어서 trend-scout가 매일 긁어서 글 소재로 활용."
)

# ══════════════════════════════════════════════════════════════
# SLIDE 3 — 자기진화 구조
# ══════════════════════════════════════════════════════════════
s3 = blank_slide(prs)
bg(s3)

add_text(s3, "자기진화 — 실제로 맞는 말인가?",
         Inches(0.7), Inches(0.3), Inches(10), Inches(0.7), size=36, bold=True)
add_text(s3, "에이전트가 스스로 행동 방식을 바꾸는 피드백 루프",
         Inches(0.7), Inches(1.05), Inches(10), Inches(0.45), size=16, color=TEXT_GRAY)
divider(s3, Inches(1.55))

# 루프 다이어그램 — 5개 박스를 원형으로
boxes = [
    (Inches(5.5),  Inches(1.8),  ACCENT,  "① 포스팅",      "매일 2개 게시"),
    (Inches(9.2),  Inches(3.0),  ACCENT2, "② 성과 수집",   "좋아요·댓글·팔로워"),
    (Inches(7.8),  Inches(5.3),  ACCENT3, "③ 분석",        "Growth Analyst\n+ 악마의 변호인"),
    (Inches(3.2),  Inches(5.3),  YELLOW,  "④ 전략 갱신",   "team_signal.json"),
    (Inches(1.5),  Inches(3.0),  RED,     "⑤ 프롬프트 재작성", "Strategist\n(매주 월요일)"),
]

for (bx, by, col, title, sub) in boxes:
    bw, bh = Inches(2.2), Inches(1.1)
    rect(s3, bx, by, bw, bh, BG_CARD)
    r2 = s3.shapes.add_shape(1, bx, by, Inches(0.06), bh, )
    r2.fill.solid(); r2.fill.fore_color.rgb = col
    r2.line.fill.background()
    add_text(s3, title, bx + Inches(0.15), by + Inches(0.04),
             bw - Inches(0.2), Inches(0.4), size=14, bold=True, color=col)
    add_text(s3, sub,   bx + Inches(0.15), by + Inches(0.44),
             bw - Inches(0.2), Inches(0.6), size=12, color=TEXT_GRAY)

# 화살표 텍스트로 대체
arrows = [
    (Inches(7.8),  Inches(2.3),  "→"),
    (Inches(9.6),  Inches(4.2),  "↓"),
    (Inches(6.2),  Inches(5.85), "←"),
    (Inches(2.8),  Inches(4.2),  "↑"),
    (Inches(3.8),  Inches(2.3),  "→"),
]
for (ax, ay, sym) in arrows:
    add_text(s3, sym, ax, ay, Inches(0.5), Inches(0.5),
             size=24, bold=True, color=TEXT_DIM, align=PP_ALIGN.CENTER)

# 실제 사례 박스
rect(s3, Inches(0.6), Inches(1.75), Inches(0.04), Inches(1.3), ACCENT)
add_text(s3, "실제 사례",
         Inches(0.75), Inches(1.75), Inches(4), Inches(0.4),
         size=13, bold=True, color=ACCENT)
add_text(s3,
         "영어 포스팅 → 조회수 16, 팔로워 0\n"
         "데이터 확인 후 Strategist가 프롬프트에 '영어 금지' 추가\n"
         "이후 해당 패턴 자동 제거됨",
         Inches(0.75), Inches(2.15), Inches(4.2), Inches(0.85),
         size=12, color=TEXT_GRAY)

rect(s3, Inches(0.6), Inches(3.2), Inches(0.04), Inches(1.3), YELLOW)
add_text(s3, "한계도 있음",
         Inches(0.75), Inches(3.2), Inches(4), Inches(0.4),
         size=13, bold=True, color=YELLOW)
add_text(s3,
         "학습 속도: 주 1회 (월요일만 업데이트)\n"
         "데이터 부족 초기엔 판단 불안정\n"
         "사람의 감각·맥락 판단은 아직 보완 필요",
         Inches(0.75), Inches(3.6), Inches(4.2), Inches(0.85),
         size=12, color=TEXT_GRAY)

s3.notes_slide.notes_text_frame.text = (
    "━━━ 일반 발표용 ━━━\n\n"
    "'자기진화'가 과장인지 먼저 짚겠습니다. 결론은 방향은 맞지만 완전한 자율 진화는 아닙니다.\n"
    "포스팅 → 성과 수집 → 분석 → 전략 갱신 → 프롬프트 재작성 루프가 사람 개입 없이 자동으로 돌아갑니다.\n"
    "실제 사례: 영어 포스팅이 조회수 16에 팔로워 0. Strategist가 다음 월요일에 바이럴 라이터 지침에 '영어 금지'를 추가했습니다. 이후 영어 포스팅이 나오지 않습니다.\n"
    "한계도 솔직히 말하면 학습 주기가 주 1회라 느립니다. 오늘처럼 GEO 같은 용어를 reply에 넣는 감각은 아직 사람이 보완해야 합니다.\n"
    "'자기진화'보다는 '데이터 기반 자기교정 구조'가 더 정확한 표현입니다.\n\n"
    "━━━ 개발자 질문 대응용 ━━━\n\n"
    "Q. Strategist가 프롬프트를 어떻게 수정하나?\n"
    "→ prompts/ 폴더의 .txt 파일(viral_writer, hunter_engager, trend_scout)을 직접 덮어씁니다. Python으로 claude CLI 호출, 출력 결과를 파일에 write.\n"
    "→ agents/ 폴더(역할 정의)는 건드리지 않음. Strategist는 prompts/(오늘 할 일)만 수정.\n\n"
    "Q. 악마의 변호인은 어떻게 구현했나?\n"
    "→ growth_analyst.py 안에서 분석 완료 후 claude -p '방금 네 분석을 반박해봐' 를 한 번 더 호출.\n"
    "→ 두 결과를 team_signal.json의 directives 필드와 devil_advocate 필드로 분리 저장.\n\n"
    "Q. 왜 학습 주기가 주 1회인가?\n"
    "→ 하루치 데이터로 패턴 판단하면 노이즈가 너무 큼. 최소 7일치는 쌓여야 의미 있는 패턴 추출 가능."
)

# ══════════════════════════════════════════════════════════════
# SLIDE 4 — 자동 포스팅 메커니즘
# ══════════════════════════════════════════════════════════════
s4 = blank_slide(prs)
bg(s4)

add_text(s4, "어떻게 자동으로 올리나",
         Inches(0.7), Inches(0.3), Inches(9), Inches(0.7), size=36, bold=True)
add_text(s4, "버퍼·예약툴 없음 — Threads 공식 API 직접 호출",
         Inches(0.7), Inches(1.05), Inches(9), Inches(0.45), size=16, color=TEXT_GRAY)
divider(s4, Inches(1.55))

# 왼쪽: 포스팅 플로우
left_items = [
    (ACCENT,  "① Viral Writer가 posts.json에 글 저장",
              "date, content, topic_tag, reply(첫댓글) 포함"),
    (ACCENT2, "② cron이 10:35 / 20:00 에 자동 실행",
              "Mac에 등록된 스케줄러 — 서버 없이 로컬 실행"),
    (ACCENT3, "③ Threads API 2단계 호출",
              "Container 생성(글 등록) → Publish(실제 게시)"),
    (YELLOW,  "④ 토큰 자동 갱신",
              "60일 장기 토큰 — 만료 전 자동 갱신 로직 내장"),
    (RED,     "⑤ 중복 방지",
              "'이미 올렸음' 표시를 로컬에 남겨 동시 실행 차단\n(Threads 응답 지연과 무관하게 즉시 차단)"),
]

for i, (col, title, sub) in enumerate(left_items):
    y = Inches(1.75) + i * Inches(0.98)
    rect(s4, Inches(0.6), y, Inches(5.8), Inches(0.82), BG_CARD)
    rect(s4, Inches(0.6), y, Inches(0.05), Inches(0.82), col)
    num_box = rect(s4, Inches(0.65), y + Inches(0.18), Inches(0.5), Inches(0.45), col)
    add_text(s4, title, Inches(1.25), y + Inches(0.05),
             Inches(5.0), Inches(0.38), size=14, bold=True, color=TEXT_WHITE)
    add_text(s4, sub, Inches(1.25), y + Inches(0.43),
             Inches(5.0), Inches(0.35), size=12, color=TEXT_GRAY)

# 오른쪽: API 코드 블록 느낌
rect(s4, Inches(7.0), Inches(1.75), Inches(5.8), Inches(4.9), RGBColor(0x11, 0x11, 0x1F))
add_text(s4, "# Threads API 포스팅 (실제 코드)",
         Inches(7.15), Inches(1.85), Inches(5.5), Inches(0.4),
         size=11, color=TEXT_DIM, italic=True)

code_lines = [
    ("# 1단계: Container 생성", TEXT_DIM),
    ("POST /v1.0/{user_id}/threads", ACCENT2),
    ("  media_type = TEXT", TEXT_GRAY),
    ("  text       = 포스트 본문", TEXT_GRAY),
    ("  topic_tag  = AI_THREADS", TEXT_GRAY),
    ("", TEXT_GRAY),
    ("# 2단계: 발행", TEXT_DIM),
    ("POST /v1.0/{user_id}/threads_publish", ACCENT3),
    ("  creation_id = container_id", TEXT_GRAY),
    ("", TEXT_GRAY),
    ("# 결과", TEXT_DIM),
    ('✅  post_id = "178508711..."', ACCENT3),
    ("📲  Slack 알림 자동 발송", YELLOW),
]

for i, (line, col) in enumerate(code_lines):
    add_text(s4, line, Inches(7.2), Inches(2.35) + i * Inches(0.28),
             Inches(5.5), Inches(0.3), size=11.5, color=col)

s4.notes_slide.notes_text_frame.text = (
    "━━━ 일반 발표용 ━━━\n\n"
    "버퍼·후트스위트 같은 예약 도구 없이 Threads API로 직접 보냅니다.\n"
    "바이럴 라이터가 10시 12분에 오늘 글을 쓰고, 23분 후 cron이 바로 포스팅합니다. 서버 없이 Mac 한 대로 돌아갑니다.\n"
    "Threads API는 포스팅을 두 단계로 처리합니다. 글 내용을 등록해서 ID를 받고, 그 ID로 실제 게시를 호출합니다.\n"
    "인증 토큰은 60일짜리를 쓰고 실행할 때마다 자동 갱신됩니다.\n"
    "오늘 같은 글이 두 번 올라가는 문제가 있었습니다. cron 자동 실행과 수동 실행이 5초 차이로 동시에 시작됐고, Threads API가 방금 올린 글을 즉시 반영하지 않아 중복 감지가 통과됐습니다. '이미 올렸음' 표시를 로컬 파일에 남기는 방식으로 오늘 수정했습니다.\n\n"
    "━━━ 개발자 질문 대응용 ━━━\n\n"
    "Q. Threads API 2단계 구조가 왜 그렇게 설계됐나?\n"
    "→ Meta 설계입니다. Container 생성(POST /threads) → Publish(POST /threads_publish). 미디어 첨부나 카루셀 등 복잡한 구성을 위한 구조로 보임.\n\n"
    "Q. cron이 Mac 꺼지면 어떻게 되나?\n"
    "→ 그냥 안 돌아갑니다. 서버가 없는 구조의 한계. 현재는 허용 가능한 수준으로 판단.\n\n"
    "Q. 중복 방지를 lock 파일로 한 이유?\n"
    "→ data/locks/{date}_{slot}.lock 파일을 open('x') 모드로 생성. 이미 있으면 FileExistsError 발생 → 즉시 종료. 파일시스템 레벨에서 원자적으로 처리되므로 race condition 없음. Threads API 전파 지연(eventual consistency)과 완전히 독립적."
)

# ══════════════════════════════════════════════════════════════
# SLIDE 5 — 댓글 Engagement
# ══════════════════════════════════════════════════════════════
s5 = blank_slide(prs)
bg(s5)

add_text(s5, "어떤 계정에 어떻게 댓글을 다나",
         Inches(0.7), Inches(0.3), Inches(10), Inches(0.7), size=36, bold=True)
add_text(s5, "Hunter Engager — 매일 14:00 자동 실행 · Playwright 브라우저 자동화 · 목표 25개",
         Inches(0.7), Inches(1.05), Inches(10), Inches(0.45), size=16, color=TEXT_GRAY)
divider(s5, Inches(1.55))

# 왼쪽: 타겟 선정
add_text(s5, "타겟 선정 방법",
         Inches(0.7), Inches(1.75), Inches(5.5), Inches(0.45),
         size=18, bold=True, color=ACCENT)

kw_data = [
    ("10개 세트, 하루 1세트씩 순환", "세트당 키워드 3개 — 매일 다른 사람들과 접점"),
    ("AI활용·ChatGPT활용", "1, 2일차"),
    ("자사몰·카페24", "5일차"),
    ("디지털마케팅", "7일차"),
    ("이커머스·부업", "2, 3일차"),
    ("퍼스널브랜딩", "3일차"),
]

for i, (kw, desc) in enumerate(kw_data):
    y = Inches(2.3) + i * Inches(0.58)
    if i == 0:
        col = ACCENT2
        rect(s5, Inches(0.7), y, Inches(5.5), Inches(0.46), BG_CARD)
    else:
        col = TEXT_WHITE
    add_text(s5, kw,   Inches(0.85), y + Inches(0.05), Inches(2.8), Inches(0.36),
             size=13, bold=(i==0), color=col)
    add_text(s5, desc, Inches(3.7),  y + Inches(0.05), Inches(2.3), Inches(0.36),
             size=13, color=TEXT_GRAY)

# 필터 조건
rect(s5, Inches(0.7), Inches(5.9), Inches(5.5), Inches(0.8), BG_CARD)
add_text(s5, "필터 조건 (이 포스트는 스킵)",
         Inches(0.85), Inches(5.95), Inches(5.0), Inches(0.35),
         size=13, bold=True, color=YELLOW)
add_text(s5, "좋아요 5개 미만  /  200개 초과  /  이미 댓글 단 곳  /  내 포스트",
         Inches(0.85), Inches(6.32), Inches(5.0), Inches(0.3),
         size=12, color=TEXT_GRAY)

# 오른쪽 상단: Playwright + Claude 파이프라인
add_text(s5, "어떻게 글을 읽고 댓글을 쓰나",
         Inches(6.9), Inches(1.75), Inches(5.8), Inches(0.45),
         size=16, bold=True, color=ACCENT2)

pipeline = [
    (ACCENT,  "Playwright",  "브라우저 열기 → 포스트 페이지 이동\n→ JavaScript로 본문 텍스트 추출"),
    (ACCENT2, "Claude Haiku","추출된 본문 수신 → 읽고 이해\n→ 맥락에 맞는 댓글 생성"),
    (ACCENT3, "Playwright",  "생성된 댓글 → 입력창에 타이핑 → 전송"),
]
for i, (col, label, desc) in enumerate(pipeline):
    y = Inches(2.25) + i * Inches(0.88)
    rect(s5, Inches(6.9), y, Inches(6.1), Inches(0.75), BG_CARD)
    rect(s5, Inches(6.9), y, Inches(0.05), Inches(0.75), col)
    pill(s5, Inches(7.05), y + Inches(0.18), Inches(1.3), Inches(0.32), label, col, 11)
    add_text(s5, desc, Inches(8.5), y + Inches(0.05),
             Inches(4.35), Inches(0.65), size=11, color=TEXT_GRAY)
    if i < 2:
        add_text(s5, "↓", Inches(9.3), y + Inches(0.77),
                 Inches(0.4), Inches(0.3), size=14, color=TEXT_DIM, align=PP_ALIGN.CENTER)

add_text(s5, "Playwright = 매크로(브라우저 조작)  /  Claude = 이해·생성",
         Inches(6.9), Inches(4.9), Inches(6.1), Inches(0.35),
         size=11, italic=True, color=TEXT_DIM)

# 구분선
rect(s5, Inches(6.9), Inches(5.3), Inches(6.1), Pt(1), TEXT_DIM)

# 오른쪽 하단: 댓글 원칙
add_text(s5, "댓글 작성 원칙",
         Inches(6.9), Inches(5.45), Inches(5.8), Inches(0.38),
         size=15, bold=True, color=ACCENT2)

principles = [
    (ACCENT3, "포지션 유지", "자사몰·이커머스 실무자, AI 직접 써본 사람"),
    (RED,     "자기검토",   '"프로필 클릭할 이유 있나?" → NO면 스킵'),
]
for i, (col, title, sub) in enumerate(principles):
    y = Inches(5.85) + i * Inches(0.58)
    rect(s5, Inches(6.9), y, Inches(6.1), Inches(0.5), BG_CARD)
    rect(s5, Inches(6.9), y, Inches(0.05), Inches(0.5), col)
    add_text(s5, f"{title}  —  {sub}", Inches(7.1), y + Inches(0.07),
             Inches(5.7), Inches(0.38), size=12, color=TEXT_GRAY)

s5.notes_slide.notes_text_frame.text = (
    "━━━ 일반 발표용 ━━━\n\n"
    "포스팅은 Threads API, 댓글은 다릅니다. Threads API는 내 계정 글 올리기만 지원하고, 다른 사람 글에 댓글 다는 기능은 API로 제공하지 않습니다. 그래서 Playwright로 실제 브라우저를 띄워서 사람이 손으로 하는 것처럼 댓글을 달게 만들었습니다.\n"
    "키워드를 10개 세트로 나눠서 하루 1세트씩 순환합니다. 세트당 키워드 3개라 하루에 3개 키워드로 검색합니다. 매일 다른 사람들과 접점을 만들기 위해서입니다.\n"
    "좋아요 너무 없는 글은 노출 안 되는 글이라 스킵, 너무 많은 글은 댓글이 묻혀서 스킵합니다. 예전에 달았던 곳은 기록해뒀다가 중복을 막습니다. 단 이 기록을 무한정 쌓는 건 낭비라 60일이 지나면 자동으로 정리됩니다.\n"
    "댓글 원칙: 자사몰·이커머스 실무자 포지션 유지, 반말 구어체, '이 댓글 보고 프로필 클릭할 이유 있나?' 자기검토 후 없으면 스킵. 하루 목표 25개.\n\n"
    "━━━ 개발자 질문 대응용 ━━━\n\n"
    "Q. Playwright로 댓글 달 때 로그인은 어떻게 처리하나?\n"
    "→ session_state.json에 Playwright가 저장한 쿠키·로컬스토리지를 통째로 보존. 실행 시 storageState로 주입. 세션 만료되면 renew_session.py로 재로그인.\n\n"
    "Q. engage_log.csv 60일 정리 로직은?\n"
    "→ auto_engage.py 실행 시마다 cutoff = today - 60days 계산, date 필드 기준으로 필터링해서 파일 덮어씀. 별도 cron 없이 실행 때마다 자동 처리.\n\n"
    "Q. Threads가 봇 감지하지 않나?\n"
    "→ 현재는 실제 브라우저(Playwright headless)를 쓰고, 댓글 사이에 랜덤 딜레이를 넣어서 패턴을 흐림. 완전한 우회 보장은 아님."
)

# ══════════════════════════════════════════════════════════════
# SLIDE 6 — 모델 배분 전략
# ══════════════════════════════════════════════════════════════
s6 = blank_slide(prs)
bg(s6)

add_text(s6, "AI 모델도 역할에 맞게 배분한다",
         Inches(0.7), Inches(0.3), Inches(10), Inches(0.7), size=36, bold=True)
add_text(s6, "비용·품질·속도 — 에이전트마다 최적 모델이 다르다",
         Inches(0.7), Inches(1.05), Inches(10), Inches(0.45), size=16, color=TEXT_GRAY)
divider(s6, Inches(1.55))

model_rows = [
    (ACCENT3, "Haiku",  "가장 빠름 · 비용 최소",
     [("댓글 생성 (Hunter Engager)", "하루 최대 25회 반복 호출 — 비용 최적화")]),
    (ACCENT2, "Sonnet", "속도·품질 균형 · 메인 모델",
     [("Viral Writer",  "매일 포스트 2개 작성 — 글 품질이 직접 팔로워에 영향"),
      ("Trend Scout",   "트렌드 판단 + 각도 결정"),
      ("Fact Checker",  "사실 검증 정확도 중요"),
      ("Growth Analyst","성과 분석 · team_signal 생성")]),
    (ACCENT,  "Opus",   "가장 깊은 추론 · 주 1회",
     [("Strategist",    "에이전트 프롬프트 재작성 — 시스템 전체에 영향\n→ 가장 중요한 판단, 비용보다 품질 우선")]),
]

y_cursor = Inches(1.7)
for (col, model, subtitle, agents) in model_rows:
    block_h = Inches(0.42 + len(agents) * 0.62)
    rect(s6, Inches(0.6), y_cursor, Inches(12.1), block_h, BG_CARD)
    rect(s6, Inches(0.6), y_cursor, Inches(0.06), block_h, col)

    # 모델명 + 설명
    pill(s6, Inches(0.85), y_cursor + Inches(0.08),
         Inches(1.4), Inches(0.34), model, col, 13)
    add_text(s6, subtitle,
             Inches(2.4), y_cursor + Inches(0.1),
             Inches(4), Inches(0.32), size=13, color=TEXT_GRAY, italic=True)

    for j, (agent_name, reason) in enumerate(agents):
        ay = y_cursor + Inches(0.48) + j * Inches(0.58)
        add_text(s6, "·  " + agent_name,
                 Inches(1.1), ay, Inches(3.5), Inches(0.28),
                 size=13, bold=True, color=TEXT_WHITE)
        add_text(s6, reason,
                 Inches(4.7), ay, Inches(7.7), Inches(0.48),
                 size=12, color=TEXT_GRAY)

    y_cursor += block_h + Inches(0.12)

s6.notes_slide.notes_text_frame.text = (
    "━━━ 일반 발표용 ━━━\n\n"
    "에이전트마다 쓰는 AI 모델이 다릅니다. 같은 Claude인데 왜 구분하냐면, 모델마다 속도·비용·품질이 다르기 때문입니다.\n\n"
    "Haiku는 가장 빠르고 저렴합니다. 댓글 생성처럼 하루에 25번씩 반복 호출하는 작업에 씁니다. 짧은 댓글 하나 쓰는 데 가장 비싼 모델 쓸 이유가 없습니다.\n\n"
    "Sonnet은 속도와 품질의 균형점입니다. 포스트 작성, 트렌드 분석, 사실 검증, 그리고 Growth Analyst의 성과 분석과 악마의 변호인 역할까지 메인 작업 전반에 씁니다.\n\n"
    "Opus는 가장 깊이 생각하는 모델입니다. Strategist 혼자만 씁니다. 이유는 Strategist가 에이전트 프롬프트 자체를 재작성하는 작업이기 때문입니다. 이 판단이 틀리면 이후 일주일치 글이 전부 영향받습니다. 비용보다 품질이 중요한 유일한 지점입니다.\n\n"
    "━━━ 개발자 질문 대응용 ━━━\n\n"
    "Q. Haiku로 생성한 댓글 품질이 괜찮나?\n"
    "→ 봇티 필터(좋은 글, 공감합니다 등 감지 시 자동 스킵)가 있어서 품질 하한선을 보정함. 댓글은 길이도 짧고 구어체라 Haiku로 충분.\n\n"
    "Q. Growth Analyst는 왜 Sonnet인가?\n"
    "→ 팀 전체 방향을 결정하는 team_signal.json을 생성하고, 자기 분석을 스스로 반박하는 악마의 변호인 역할까지 한다. 단순 텍스트 생성이 아니라 판단이 들어가는 작업이라 Sonnet이 적합.\n\n"
    "Q. Strategist를 Opus로 바꾼 이유?\n"
    "→ 주 1회 실행이라 비용 부담이 낮음. 반면 프롬프트 재작성 품질은 이후 7일치 에이전트 행동에 직접 영향. ROI가 가장 높은 지점에 Opus 투입."
)

# ══════════════════════════════════════════════════════════════
# SLIDE 7 — 핵심 인사이트 & Q&A
# ══════════════════════════════════════════════════════════════
s7 = blank_slide(prs)
bg(s7)

rect(s7, 0, 0, W, Inches(0.08), ACCENT)

add_text(s7, "핵심 인사이트 3가지",
         Inches(0.7), Inches(0.3), Inches(9), Inches(0.7), size=36, bold=True)
divider(s7, Inches(1.1))

insights = [
    (ACCENT,
     "01  AI는 '대체'가 아니라 '피드백 루프'로 쓸 때 강하다",
     "단순 자동화(글 대신 써줘)보다, 성과 데이터 → 전략 수정 → 실행의 루프를 자동화하는 것이 본질.\n"
     "사람이 매번 판단하던 '이 방향 맞나?'를 시스템이 대신하게 만드는 것."),
    (ACCENT2,
     "02  역할 분리 + 모델 배분이 곧 비용 설계다",
     "에이전트마다 역할을 쪼개면 품질 관리가 쉬워지고, 모델도 역할에 맞게 배분할 수 있다.\n"
     "Haiku로 충분한 곳에 Opus 쓰는 건 낭비. 반대로 가장 중요한 판단에는 최고 모델을 써야 한다."),
    (ACCENT3,
     "03  데이터 없이 AI를 믿으면 아첨 루프에 빠진다",
     "Growth Analyst에 '악마의 변호인' 역할을 추가한 이유.\n"
     "AI는 긍정적인 방향으로 분석하려는 경향이 있어, 스스로 반박하게 만드는 장치가 필요함."),
]

for i, (col, title, body) in enumerate(insights):
    y = Inches(1.3) + i * Inches(1.85)
    rect(s7, Inches(0.6), y, Inches(12.1), Inches(1.65), BG_CARD)
    rect(s7, Inches(0.6), y, Inches(0.06), Inches(1.65), col)
    add_text(s7, title, Inches(0.85), y + Inches(0.1),
             Inches(11.5), Inches(0.5), size=15, bold=True, color=col)
    add_text(s7, body,  Inches(0.85), y + Inches(0.6),
             Inches(11.5), Inches(0.95), size=13, color=TEXT_GRAY)

# 하단
rect(s7, 0, H - Inches(0.65), W, Inches(0.65), BG_CARD)
add_text(s7, "Q & A",
         Inches(0.8), H - Inches(0.62), Inches(3), Inches(0.55),
         size=20, bold=True, color=ACCENT)
add_text(s7, "@sebsonthebeach  ·  uneedcomms.com",
         Inches(9.0), H - Inches(0.62), Inches(4), Inches(0.55),
         size=14, color=TEXT_DIM, align=PP_ALIGN.RIGHT)

s7.notes_slide.notes_text_frame.text = (
    "━━━ 일반 발표용 ━━━\n\n"
    "첫째, AI는 피드백 루프로 쓸 때 강합니다. '글 써줘'가 아니라 '성과 보고 → 전략 수정 → 실행' 반복을 자동화하는 게 본질입니다.\n"
    "둘째, 역할 분리와 모델 배분이 곧 비용 설계입니다. Haiku로 충분한 댓글 생성에 Opus를 쓸 이유가 없고, 반대로 프롬프트 재작성처럼 전체 시스템에 영향을 주는 판단에는 최고 모델을 써야 합니다.\n"
    "셋째, 데이터 없이 AI를 믿으면 아첨 루프에 빠집니다. 스스로 반박하게 만드는 장치가 필요합니다.\n\n"
    "━━━ 개발자 질문 대응용 ━━━\n\n"
    "Q. 이 구조를 다른 SNS에도 적용 가능한가?\n"
    "→ team_signal.json, posts.json, prompts/ 구조는 플랫폼 독립적. 포스팅/댓글 레이어만 교체하면 됨.\n\n"
    "Q. 비용은?\n"
    "→ claude CLI 구독 기반이라 API 키 과금 없음. Opus는 Strategist 주 1회만 사용하므로 비용 부담 낮음.\n\n"
    "Q. 팔로워 153명인데 ROI가 있나?\n"
    "→ 현재는 시스템 검증 단계. 자기진화 구조가 실제로 작동하는지 확인이 현재 목표."
)

out = "/Users/uneedcomms/Desktop/threads_ai_team.pptx"
prs.save(out)
print("저장 완료:", out)
