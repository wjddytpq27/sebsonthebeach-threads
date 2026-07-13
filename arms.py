"""
arms.py — 콘텐츠 전략 "arm" 분류 (단일 계약)

arm = (slot, lang, hook_style, topic_theme) 조합.
- Phase 1: "의도한 것 ↔ 일어난 것" 조인키. follow_attributor의 사후 키워드 추측을 대체.
- Phase 2: 밴딧이 배분·학습하는 단위. 여기 정의를 그대로 재사용.

원칙:
- viral_writer가 생성 시점에 직접 라벨링한 값(ground truth)을 최우선 신뢰.
- 라벨이 없으면(과거 데이터·누락) 텍스트 휴리스틱으로 폴백 추정 → estimated=True 표시.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── 택소노미 (viral_writer 출력 스키마와 반드시 일치) ─────────────────────────
HOOK_STYLES = (
    'target_callout',      # "X한테만" / "only for X" — 현재 위너
    'contrarian',          # 논쟁·통념 반박 ("바이브코딩 지금도 믿어?")
    'reveal',              # 반전 폭로 ("내가 X했더니 예상 밖 결과")
    'secret',              # "아무도 안 알려주는"
    'news_relay',          # 뉴스 전달 — 과거 루저
    'list',                # 리스트형 팁 나열 — score 0 상습
    'other',
)

TOPIC_THEMES = (
    'smartstore',          # 스마트스토어/네이버
    'coupang',             # 쿠팡/로켓그로스
    'amazon',              # 아마존/해외셀링
    'own_mall',            # 자사몰/카페24/쇼피파이
    'ai_ecommerce',        # AI × 이커머스 교차 (저녁 슬롯 핵심)
    'ai_general',          # 순수 AI/도구 (이커머스 연결 없음 — 위험)
    'personal_branding',   # 퍼스널브랜딩/콘텐츠
    'marketing',           # 광고/ROAS/퍼널 일반
    'other',
)

LANGS = ('ko', 'en')

# 휴리스틱 폴백용 키워드 (라벨 누락 시에만 사용)
_HOOK_KW = {
    'target_callout': ('한테만', '한테만.', 'only for', 'just for you', '너한테만'),
    'contrarian':     ('믿고 있어', '틀렸', '진짜 이유', '착각', '거짓말', "still believe", 'myth'),
    'reveal':         ('했더니', '해봤더니', '반전', '알고 보니', '뒤집었', 'turns out', 'i stopped'),
    'secret':         ('아무도 안', '몰래', '숨겨', "no one tells", 'nobody talks'),
    'news_relay':     ('발표', '출시', '공개했', 'announced', 'launched', 'released', 'is live'),
    'list':           ('①', '②', '③', '1.', '2.', '3.', '첫째', '둘째', '- '),
}
_TOPIC_KW = {
    'smartstore':        ('스마트스토어', '네이버', 'smartstore'),
    'coupang':           ('쿠팡', '로켓그로스', 'coupang'),
    'amazon':            ('아마존', '이베이', 'amazon', 'ebay', 'shopify'),
    'own_mall':          ('자사몰', '카페24', 'cafe24', '독립몰'),
    'ai_ecommerce':      ('ai', 'gpt', 'claude', 'agent', '자동화', 'automation', '나노바나나', 'nano banana'),
    'personal_branding': ('퍼스널', '브랜딩', 'branding', '콘텐츠로', 'creator'),
    'marketing':         ('roas', '광고', '퍼널', '전환율', '마케팅', 'funnel', 'conversion', 'ads'),
}
_ECOMMERCE_MARKERS = ('셀러', 'seller', '쇼핑몰', '상품', '주문', '매출', '고객', 'store', 'sales')


@dataclass(frozen=True)
class Arm:
    slot: str          # morning | evening
    lang: str          # ko | en
    hook_style: str
    topic_theme: str
    estimated: bool    # True면 휴리스틱 추정(라벨 누락), False면 생성 시점 ground truth

    def key(self) -> str:
        """밴딧·집계용 안정 키."""
        return f'{self.slot}|{self.lang}|{self.hook_style}|{self.topic_theme}'


def detect_lang(text: str) -> str:
    """한글 문자 비율로 언어 판정."""
    if not text:
        return 'ko'
    hangul = sum(1 for ch in text if '가' <= ch <= '힣')
    letters = sum(1 for ch in text if ch.isalpha())
    if letters == 0:
        return 'ko'
    return 'ko' if hangul / letters >= 0.15 else 'en'


def guess_hook_style(text: str) -> str:
    """텍스트 휴리스틱으로 hook_style 추정 (라벨 폴백 전용)."""
    low = (text or '').lower()
    head = low[:60]
    for style, kws in _HOOK_KW.items():
        # target_callout·contrarian은 첫머리에서 강하게 드러남 → head 우선
        scope = head if style in ('target_callout', 'contrarian', 'list') else low
        if any(kw.lower() in scope for kw in kws):
            return style
    return 'other'


def guess_topic_theme(text: str) -> str:
    """텍스트 휴리스틱으로 topic_theme 추정 (라벨 폴백 전용)."""
    low = (text or '').lower()
    has_ecom = any(m in low for m in _ECOMMERCE_MARKERS)
    # 플랫폼 고유명사 우선
    for theme in ('smartstore', 'coupang', 'amazon', 'own_mall'):
        if any(kw in low for kw in _TOPIC_KW[theme]):
            return theme
    # AI 언급: 이커머스 마커 있으면 교차, 없으면 순수 AI
    if any(kw in low for kw in _TOPIC_KW['ai_ecommerce']):
        return 'ai_ecommerce' if has_ecom else 'ai_general'
    for theme in ('marketing', 'personal_branding'):
        if any(kw in low for kw in _TOPIC_KW[theme]):
            return theme
    return 'other'


def _norm(value: str, allowed: tuple[str, ...], default: str) -> str:
    v = (value or '').strip().lower()
    return v if v in allowed else default


def resolve_arm(post: dict) -> Arm:
    """
    posts.json 항목 하나 → Arm.
    라벨(hook_style/topic_theme/lang)이 있으면 신뢰, 없으면 content로 추정.
    """
    content = post.get('content', '') or ''
    slot = _norm(post.get('slot', ''), ('morning', 'evening'),
                 'evening' if post.get('evening') else 'morning')

    has_hook = bool(post.get('hook_style'))
    has_topic = bool(post.get('topic_theme'))

    hook = (_norm(post.get('hook_style', ''), HOOK_STYLES, 'other')
            if has_hook else guess_hook_style(content))
    topic = (_norm(post.get('topic_theme', ''), TOPIC_THEMES, 'other')
             if has_topic else guess_topic_theme(content))
    lang = _norm(post.get('lang', ''), LANGS, '') or detect_lang(content)

    return Arm(
        slot=slot, lang=lang, hook_style=hook, topic_theme=topic,
        estimated=not (has_hook and has_topic),
    )
