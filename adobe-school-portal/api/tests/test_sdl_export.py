"""SDL 엑셀보내기 그룹핑."""

from types import SimpleNamespace

from app.services.sdl_export import IP_COLUMN_NAMES, build_sdl_export_rows


def _reg(school_id: int, school_name: str, ip: str, qty: int, name: str = "", email: str = ""):
    school = SimpleNamespace(name=school_name)
    return SimpleNamespace(
        school_id=school_id,
        school=school,
        registered_ip=ip,
        purchase_qty=qty,
        contact_name=name or None,
        contact_phone=None,
        contact_email=email or None,
    )


def test_build_sdl_export_rows_groups_ips_per_contact():
    rows = build_sdl_export_rows(
        [
            _reg(1, "A고", "10.0.0.1", 25, "홍", "a@x.kr"),
            _reg(1, "A고", "10.0.0.2", 0, "홍", "a@x.kr"),
            _reg(1, "A고", "10.0.0.3", 0, "홍", "a@x.kr"),
            _reg(2, "B고", "10.0.1.1", 5),
        ]
    )
    assert len(rows) == 2
    a = next(r for r in rows if r["학교명"] == "A고")
    assert a["담당자"] == "홍"
    assert a["IP 1"] == "10.0.0.1"
    assert a["IP 2"] == "10.0.0.2"
    assert a["IP 3"] == "10.0.0.3"
    assert a["SDL 구매수량"] == 25
    assert all(col in a for col in IP_COLUMN_NAMES)
