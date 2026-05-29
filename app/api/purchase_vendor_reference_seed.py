"""매입처·담당자 참조 표(수동 입력) — DB 시드용."""

from __future__ import annotations

# 매입처 | 담당자 | 연락처 | 이메일  (이미지 표 기준)
REFERENCE_ROWS: list[dict[str, str]] = [
    {"company": "에쓰씨케이", "contact_name": "배재호", "tel": "010-3296-3432", "email": "scott.bae@sckcorp.co.kr"},
    {"company": "디모아", "contact_name": "홍정미", "tel": "010-7551-6357", "email": "jmhong@dimoa.co.kr"},
    {"company": "Adobe Systems Software Ireland", "contact_name": "", "tel": "", "email": ""},
    {"company": "디모아", "contact_name": "엄진광", "tel": "010-6267-3866", "email": "jkeom@dimoa.co.kr"},
    {"company": "디모아", "contact_name": "황금성", "tel": "070-4616-1446", "email": "gshwang@dimoa.co.kr"},
    {"company": "디모아", "contact_name": "이태진", "tel": "010-2626-5602", "email": ""},
    {"company": "디모아", "contact_name": "김지웅", "tel": "010-7759-1448", "email": "jw-kim@dimoa.co.kr"},
    {"company": "디모아", "contact_name": "김정옥", "tel": "010-3637-1230", "email": "jokim@dimoa.co.kr"},
    {"company": "비츠코리아", "contact_name": "황태현", "tel": "010-9075-7915", "email": "thhwang@bitzkorea.com"},
    {"company": "카드매입(결제Site비고란기재)", "contact_name": "", "tel": "", "email": ""},
    {"company": "이노가드", "contact_name": "", "tel": "", "email": ""},
    {"company": "인피니소프트", "contact_name": "", "tel": "", "email": ""},
    {"company": "썬더디에스", "contact_name": "", "tel": "", "email": ""},
    {"company": "우리시스템즈", "contact_name": "", "tel": "", "email": ""},
    {"company": "엠투엠소프트", "contact_name": "", "tel": "", "email": ""},
    {"company": "기타(매입없음)", "contact_name": "", "tel": "", "email": ""},
]
