"""학교명 분할(1·2) ↔ Named 통합명 매칭."""

from types import SimpleNamespace

from app.security.school_match import (
    find_schools_matching_named_key,
    pick_canonical_school,
    school_names_match,
    school_names_match_loose,
    split_school_quota_suffix,
)


def _school(name: str, sid: int) -> SimpleNamespace:
    return SimpleNamespace(id=sid, name=name)


def test_split_suffix():
    assert split_school_quota_suffix("서울웹툰애니메이션고등학교1") == ("서울웹툰애니메이션고등학교", 1)
    assert split_school_quota_suffix("서울웹툰애니메이션고등학교") == ("서울웹툰애니메이션고등학교", None)
    assert split_school_quota_suffix("서울제2고등학교") == ("서울제2고등학교", None)


def test_loose_match_named_vs_split():
    assert school_names_match_loose("서울웹툰애니메이션고등학교1", "서울웹툰애니메이션고등학교")
    assert school_names_match_loose(
        "서울특별시교육청 체육건강예술교육과1",
        "서울특별시교육청체육건강예술교육과",
    )
    assert not school_names_match_loose("서울웹툰애니메이션고등학교1", "서울웹툰애니메이션고등학교2")


def test_strict_login_match():
    assert not school_names_match("서울웹툰애니메이션고등학교1", "서울웹툰애니메이션고등학교")


def test_find_split_schools():
    schools = [
        _school("서울웹툰애니메이션고등학교2", 2),
        _school("서울웹툰애니메이션고등학교1", 1),
        _school("다른고등학교", 3),
    ]
    found = find_schools_matching_named_key(schools, "서울웹툰애니메이션고등학교")
    assert [s.id for s in found] == [1, 2]


def test_pick_canonical_prefers_elementary_over_attached_kindergarten():
    schools = [
        _school("서울화계초등학교병설유치원", 473),
        _school("서울화계초등학교", 900),
    ]
    assert pick_canonical_school(schools).name == "서울화계초등학교"
