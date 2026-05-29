"""견적서 영업담당 표기용 라벨(이름 + 직함) 등 공통 프로필 헬퍼."""

from __future__ import annotations

# 견적서에서 흔한 직함(2토큰 라벨에서 직함/이름 구분용)
_KNOWN_JOB_TITLES = frozenset(
    {
        "사원",
        "주임",
        "대리",
        "과장",
        "차장",
        "부장",
        "이사",
        "전무",
        "상무",
        "사장",
        "실장",
        "팀장",
        "본부장",
        "계장",
        "대표",
        "매니저",
        "프로",
        "연구원",
        "수석",
        "선임",
        "책임",
        "연구소장",
    }
)


def canonical_rep_label(label: str | None) -> str:
    """
    영업담당 문자열을 '이름 직함' 형태로 통일(표시·권한 비교·rep_map 조회용).
    예: '과장 강주형' -> '강주형 과장', 이미 '강주형 과장'이면 그대로.
    """
    s = (label or "").strip()
    if not s:
        return ""
    parts = [p for p in s.split() if p]
    if len(parts) != 2:
        return s
    a, b = parts[0], parts[1]
    if a in _KNOWN_JOB_TITLES and b not in _KNOWN_JOB_TITLES:
        return f"{b} {a}"
    if b in _KNOWN_JOB_TITLES and a not in _KNOWN_JOB_TITLES:
        return f"{a} {b}"
    return s


def user_rep_label(job_title: str | None, full_name: str | None, email: str | None) -> str:
    """드롭다운 value / rep_map 키로 쓰는 문자열. 예: '홍길동 과장'. 직함+이름으로 적힌 값도 통일한다."""
    jt = (job_title or "").strip()
    fn = (full_name or "").strip()
    if jt and fn:
        base = f"{fn} {jt}"
    elif fn:
        base = fn
    elif jt:
        base = jt
    else:
        # 프로필(이름/직함)이 비어 있는 신규 가입자라도,
        # 레거시 영업담당(견적서 기본 4인) 이메일과 일치하면 그 라벨로 싱크한다.
        try:
            from quote_rep_legacy import legacy_rep_label_for_email

            base = legacy_rep_label_for_email(email) or ((email or "").split("@")[0] or "").strip()
        except Exception:
            base = ((email or "").split("@")[0] or "").strip()
    if not base:
        return ""
    return canonical_rep_label(base) or base


def rep_map_get(rep_map: dict[str, dict], label: str | None) -> dict | None:
    """rep_map에서 영업담당 라벨로 정보 조회(구형 '직함 이름' 키도 허용)."""
    s = (label or "").strip()
    if not s:
        return None
    if s in rep_map:
        return rep_map[s]
    c = canonical_rep_label(s)
    if c in rep_map:
        return rep_map[c]
    parts = [p for p in s.split() if p]
    if len(parts) == 2:
        alt = f"{parts[1]} {parts[0]}"
        if alt in rep_map:
            return rep_map[alt]
    return None


def rep_name_only_for_filename(label: str | None) -> str:
    """다운로드 파일명 등: 직함+이름에서 이름만 추출."""
    s = (label or "").strip()
    if not s:
        return ""
    parts = [p for p in s.split() if p]
    if not parts:
        return s
    if len(parts) == 1:
        return parts[0]
    a, b = parts[0], parts[1]
    if a in _KNOWN_JOB_TITLES and b not in _KNOWN_JOB_TITLES:
        return b
    if b in _KNOWN_JOB_TITLES and a not in _KNOWN_JOB_TITLES:
        return a
    return parts[-1]
