"""엑셀·Named 메일의 학교명/담당자 분리."""

from app.security.school_match import normalize_school_name
from app.services.contact_service import normalize_contact_name


def parse_school_and_contact(cell: str) -> tuple[str, str | None]:
    """'학교명/담당자' 또는 '학교명' → (학교키, 담당자명|None)."""
    raw = str(cell).strip()
    if "/" in raw:
        school_part, contact_part = raw.split("/", 1)
        school_key = normalize_school_name(school_part)
        contact = normalize_contact_name(contact_part)
        return school_key, contact
    return normalize_school_name(raw), None
