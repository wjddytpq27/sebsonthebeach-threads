from __future__ import annotations
"""
merge_builder_notes.py — builder-scout가 뱉은 후보(jsonl)를 안전하게 builder_notes.json에 병합.

설계 원칙(무인 시스템 안전):
- LLM(builder-scout)은 builder_notes.json을 직접 못 건드린다. 후보를 candidates.jsonl에 append만.
- 이 스크립트가 유일하게 builder_notes.json을 쓴다. 결정론적 검증 + 원자적 쓰기.
- 후보 한 줄이 깨졌어도 그 줄만 스킵 → 메인 파일은 절대 안 깨진다.
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
NOTES = BASE / 'data' / 'builder_notes.json'
CAND = BASE / 'data' / 'builder_notes_candidates.jsonl'
ARCHIVE = BASE / 'data' / 'builder_notes_candidates.archive.jsonl'

REQUIRED = ('id', 'topic', 'material', 'take')
MAX_ADD = 3  # 주당 최대 추가

# 대외비 백스톱 — 프롬프트 필터를 뚫고 온 경우 최후 차단 (명백한 재무/지표 용어만)
SECRET_TERMS = (
    '매출', '수익', '구독자', '구독 수', '구독수', '회원 수', '회원수',
    '트래픽', '방문자수', '방문자 수', '전환율', 'ARR', 'MRR', 'MAU', 'DAU',
    '억원', '억 원', '만원', '만 원', '고객사',
)


def has_secret(note: dict) -> bool:
    blob = ' '.join(str(note.get(k, '')) for k in ('topic', 'material', 'take', 'controversy'))
    return any(term in blob for term in SECRET_TERMS)


def load_notes() -> dict:
    with open(NOTES, encoding='utf-8') as f:
        return json.load(f)


def atomic_write(data: dict) -> None:
    tmp = NOTES.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # 쓰기 성공 후에만 교체 → 원본은 항상 온전
    tmp.replace(NOTES)


def main() -> int:
    if not CAND.exists() or CAND.stat().st_size == 0:
        print('  merge_builder_notes: 후보 없음 — 스킵')
        return 0

    # 메인 파일 유효성 먼저 확인 (깨져 있으면 절대 건드리지 않음)
    try:
        data = load_notes()
        assert isinstance(data.get('notes'), list)
    except Exception as e:
        print(f'  ❌ builder_notes.json 손상/이상 — 병합 중단(안전): {e}')
        return 1

    existing_ids = {n.get('id') for n in data['notes']}
    added, skipped = [], []

    for raw in CAND.read_text(encoding='utf-8').splitlines():
        raw = raw.strip()
        if not raw:
            continue
        if len(added) >= MAX_ADD:
            skipped.append(('max', raw[:40]))
            continue
        try:
            note = json.loads(raw)
        except Exception:
            skipped.append(('badjson', raw[:40]))
            continue
        if not all(note.get(k) for k in REQUIRED):
            skipped.append(('missing', str(note.get('id'))))
            continue
        if note['id'] in existing_ids:
            skipped.append(('dup', note['id']))
            continue
        if has_secret(note):
            skipped.append(('secret', note['id']))
            continue
        note.setdefault('used_dates', [])
        data['notes'].append(note)
        existing_ids.add(note['id'])
        added.append(note['id'])

    if added:
        # 백업 후 원자적 쓰기
        shutil.copy2(NOTES, NOTES.with_suffix('.json.bak'))
        atomic_write(data)
        # 병합 후 재검증 (안전 확인)
        try:
            load_notes()
        except Exception as e:
            shutil.copy2(NOTES.with_suffix('.json.bak'), NOTES)
            print(f'  ❌ 병합 결과 검증 실패 — 백업 복원: {e}')
            return 1

    # 처리한 후보는 아카이브로 이동 (재처리 방지)
    with open(ARCHIVE, 'a', encoding='utf-8') as af:
        af.write(f'# merged {datetime.now().isoformat()} added={added}\n')
        af.write(CAND.read_text(encoding='utf-8'))
        if not CAND.read_text(encoding='utf-8').endswith('\n'):
            af.write('\n')
    CAND.write_text('', encoding='utf-8')

    print(f'  ✅ merge_builder_notes: 추가 {len(added)}개 {added} / 스킵 {len(skipped)}개 {skipped}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
