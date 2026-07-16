"""최종 리스트 Named 수량·Named 메일 quota 규칙."""

from pathlib import Path

import pandas as pd

from app.services.excel_import import (
    is_admin_only_contact_name,
    load_admin_contact_names_by_school_key,
    load_license_contact_names_by_school_key,
    load_list_seats_by_contact,
    load_named_seats_by_contact,
    load_school_master,
)


def test_load_list_seats_by_contact_uses_purchaser(tmp_path: Path) -> None:
    path = tmp_path / "list.xlsx"
    pd.DataFrame(
        [
            {
                "학교명": "휘경공업고등학교",
                "고유번호증번호": "205-83-01868",
                "Named 수량": "3",
                "구매자명": "기술정보부",
            },
        ]
    ).to_excel(path, index=False)
    seats = load_list_seats_by_contact(path)
    assert seats[("휘경공업고등학교", "기술정보부")] == 3


def test_load_school_master_accepts_suryang_column(tmp_path: Path) -> None:
    path = tmp_path / "cy26_list.xlsx"
    summary = pd.DataFrame([["99"]])
    body = pd.DataFrame(
        [
            {
                "학교명": "테스트고등학교",
                "고유번호증번호": "111-11-11111",
                "수량": "4",
            },
        ]
    )
    with pd.ExcelWriter(path) as writer:
        summary.to_excel(writer, index=False, header=False)
        body.to_excel(writer, index=False, startrow=1)
    master = load_school_master(path)
    assert len(master) == 1
    assert master.iloc[0]["seats"] == 4


def test_load_school_master_skips_zero_named_and_admin_contact(tmp_path: Path) -> None:
    path = tmp_path / "list.xlsx"
    df = pd.DataFrame(
        [
            {
                "학교명": "테스트고등학교",
                "고유번호증번호": "111-11-11111",
                "Named 수량": "",
                "행정담당자명": "행정담당",
            },
            {
                "학교명": "테스트고등학교",
                "고유번호증번호": "111-11-11111",
                "Named 수량": "5",
                "행정담당자명": "김행정",
            },
        ]
    )
    df.to_excel(path, index=False)
    master = load_school_master(path)
    assert len(master) == 1
    assert master.iloc[0]["seats"] == 5
    assert master.iloc[0].get("contact_name") is None


def test_load_named_seats_uses_application_qty_without_email(tmp_path: Path) -> None:
    path = tmp_path / "named.xlsx"
    df = pd.DataFrame(
        [
            {
                "학교명": "경복고등학교",
                "학교 담당자": "",
                "신청수량": "9",
                "라이선스 현재 할당 계정": "",
            },
        ]
    )
    df.to_excel(path, index=False)
    seats = load_named_seats_by_contact(path)
    assert seats.get(("경복고등학교", None)) == 9


def test_is_admin_only_false_when_same_as_purchaser(tmp_path: Path) -> None:
    list_path = tmp_path / "list.xlsx"
    pd.DataFrame(
        [
            {
                "학교명": "테스트고등학교",
                "고유번호증번호": "111-11-11111",
                "Named 수량": "3",
                "행정담당자명": "김담당",
                "구매자명": "김담당",
            },
        ]
    ).to_excel(list_path, index=False)
    admin = load_admin_contact_names_by_school_key([list_path])
    license_names = load_license_contact_names_by_school_key(
        list_paths=[list_path], mail_paths=[]
    )
    assert is_admin_only_contact_name(
        "테스트고등학교",
        "김담당",
        admin_by_school=admin,
        license_by_school=license_names,
    ) is False


def test_load_named_seats_by_contact_optional() -> None:
    from app.services.named_kpis import find_named_mail_path

    path = find_named_mail_path("CY25-H2")
    if path is None:
        return
    seats = load_named_seats_by_contact(path)
    kwai = [k for k in seats if "광운" in (k[0] or "")]
    assert kwai
    names = {k[1] for k in kwai}
    assert "김재원" not in names
