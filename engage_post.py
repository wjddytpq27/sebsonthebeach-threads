"""
공용 댓글 게시 헬퍼 — 모든 engage 스크립트가 공유한다.

두 가지 근본 버그를 막는다:
1) 앞글자 씹힘: Lexical 에디터 포커스 레이스로 type()의 첫 1~3자가 먹힘
   → 타이핑 후 입력창 내용을 읽어 검증하고, 어긋나면 지우고 재입력.
2) LLM 되묻기/에러 텍스트가 그대로 게시됨 ("텍스트가 보이지 않습니다…" 등)
   → 게시 직전 is_valid_comment()로 차단.
"""
from __future__ import annotations

# 게시되면 안 되는 댓글 패턴 (소문자 비교)
_META_PATTERNS = [
    # LLM이 타겟 글을 못 읽었을 때 내뱉는 되묻기/안내 문구
    "텍스트가 보이지 않", "내용이 없네", "내용이 없습니", "내용이 보이지",
    "포스트 내용을 알려", "실제 텍스트를 알려", "실제 내용을 알려",
    "포스트 링크", "스크린샷을 제공", "제공해주면", "제공해 주면",
    "댓글을 생성", "댓글을 작성하겠", "댓글을 작성해", "규칙에 맞게", "규칙에 맞춰",
    "본문 내용이", "불명확", "구체적으로 뭘", "구체적인 포스트",
    "줘야 그에 맞춰", "알려주면", "알려주세요",
    # 영어 등가
    "i can't see", "i cannot see", "please provide", "share the post",
    "the actual text", "no content", "let me know the", "i'll write",
    "i don't have access", "as an ai", "i need the", "could you share",
]

# CLI 인증 실패 / 에러 텍스트
_CLI_ERROR_PATTERNS = [
    "not logged in", "please run", "/login", "run /login",
    "authentication", "unauthorized", "log in", "sign in",
    "session expired", "token", "api key", "error:", "traceback",
    "exception", "failed to", "cannot connect",
]

# 봇티 / 범용 댓글
_BOT_PATTERNS = ["좋은 글", "공감합니다", "맞아요", "저도요", "감사합니다", "잘 봤습니다"]


def is_valid_comment(comment: str) -> tuple[bool, str]:
    """게시해도 되는 댓글이면 (True, ''), 아니면 (False, 사유)."""
    if not comment or not comment.strip():
        return False, "빈 댓글"
    c = comment.strip()
    low = c.lower()

    # 비단어 조각으로 시작 (앞글자 씹힘의 흔적) 방어용은 타이핑 검증이 담당하므로 여기선 텍스트만 본다
    for p in _META_PATTERNS:
        if p in c or p in low:
            return False, f"메타/되묻기 텍스트 감지: '{p}'"
    for p in _CLI_ERROR_PATTERNS:
        if p in low:
            return False, f"에러/인증 텍스트 감지: '{p}'"
    for p in _BOT_PATTERNS:
        if p in c:
            return False, f"봇티 감지: '{p}'"
    return True, ""


def _editor_text(reply_box) -> str:
    try:
        return (reply_box.inner_text() or "").strip()
    except Exception:
        return ""


def _norm(s: str) -> str:
    return " ".join((s or "").split())


def type_comment_safely(page, reply_box, comment: str, attempts: int = 3) -> bool:
    """입력창에 댓글을 타이핑하고, 읽어서 검증한다.

    앞글자 씹힘/누락이 감지되면 지우고 재입력 (최대 attempts회).
    최종적으로 입력창 내용이 의도한 댓글과 일치하면 True.
    """
    target = comment.strip()
    target_norm = _norm(target)

    for i in range(attempts):
        try:
            reply_box.click(force=True)
            page.wait_for_timeout(400)
            reply_box.focus()
            page.wait_for_timeout(300)

            # 기존 입력 내용 비우기 (이전 시도의 잔여물 제거)
            page.keyboard.press("ControlOrMeta+A")
            page.wait_for_timeout(100)
            page.keyboard.press("Delete")
            page.wait_for_timeout(150)

            page.keyboard.type(target, delay=20)
            page.wait_for_timeout(600)

            got_norm = _norm(_editor_text(reply_box))
            # 정확히 일치하거나, 입력창이 의도한 텍스트를 온전히 포함하면 성공
            if got_norm == target_norm or target_norm in got_norm:
                return True

            print(f"    ⚠️ 타이핑 검증 실패 (시도 {i+1}/{attempts}) | "
                  f"의도='{target_norm[:40]}' / 실제='{got_norm[:40]}'")
        except Exception as e:
            print(f"    ⚠️ 타이핑 시도 {i+1} 예외: {e}")

    return False
