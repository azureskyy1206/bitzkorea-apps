"""UMAPI 이메일 변경 — 라이선스·조직 제거 분리."""

from unittest.mock import AsyncMock, patch

import pytest

from app.adobe.umapi_client import (
    AdobeUmapiError,
    build_remove_from_org_actions,
    build_remove_license_only_actions,
    run_email_change_on_adobe,
    run_remove_user_from_adobe_org,
)


@pytest.mark.asyncio
async def test_run_remove_user_from_adobe_org_two_api_calls():
    run_actions = AsyncMock()
    with patch("app.adobe.umapi_client.run_user_actions", run_actions):
        await run_remove_user_from_adobe_org(
            "old@x.com", "Profile A", contract_term="CY25-H2"
        )
    assert run_actions.await_count == 2
    assert run_actions.await_args_list[0].args[0] == build_remove_license_only_actions(
        "old@x.com", "Profile A"
    )
    assert run_actions.await_args_list[1].args[0] == build_remove_from_org_actions("old@x.com")


@pytest.mark.asyncio
async def test_run_remove_user_skips_not_in_org_on_org_step():
    run_actions = AsyncMock(
        side_effect=[
            None,
            AdobeUmapiError("error.user.not_in_org"),
        ]
    )
    with patch("app.adobe.umapi_client.run_user_actions", run_actions):
        await run_remove_user_from_adobe_org(
            "gone@x.com", "Profile", contract_term="CY26-H1"
        )


@pytest.mark.asyncio
async def test_run_email_change_on_adobe_remove_then_create():
    run_actions = AsyncMock()
    with patch("app.adobe.umapi_client.run_user_actions", run_actions):
        await run_email_change_on_adobe(
            "old@x.com",
            "new@x.com",
            "Profile",
            contract_term="CY25-H2",
        )
    assert run_actions.await_count == 3
