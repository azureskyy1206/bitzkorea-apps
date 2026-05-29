"""Phase 4: Adobe UMAPI 동기화 (mock)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.adobe.umapi_client import (
    AdobeUmapiError,
    build_create_actions,
    build_remove_actions,
    build_update_actions,
    is_remove_user_absent_error,
)
from app.models import Account, AccountStatus, SyncOp, SyncQueue, SyncState
from app.services.sync_processor import process_sync_job


def test_build_create_actions_shape():
    actions = build_create_actions(
        "user@school.kr",
        "기본 K-12용 CCE 모든 앱 구성",
        contract_term="CY25-H2",
    )
    assert len(actions) == 1
    assert actions[0]["user"] == "user@school.kr"
    assert "addAdobeID" in actions[0]["do"][0]
    assert actions[0]["do"][1]["add"]["group"] == ["기본 K-12용 CCE 모든 앱 구성"]


def test_build_remove_actions_includes_org_removal():
    actions = build_remove_actions("gone@school.kr", "Profile A")
    assert len(actions) == 1
    steps = actions[0]["do"]
    assert steps[0]["remove"]["group"] == ["Profile A"]
    assert steps[1]["removeFromOrg"]["deleteAccount"] is False


def test_build_update_actions_two_steps():
    actions = build_update_actions("old@x.com", "new@x.com", "Profile A", contract_term="CY25-H2")
    assert len(actions) == 2
    assert actions[0]["user"] == "old@x.com"
    assert actions[0]["do"][1]["removeFromOrg"]["deleteAccount"] is False
    assert actions[1]["user"] == "new@x.com"


@pytest.mark.asyncio
async def test_process_sync_job_update_remove_then_create():
    account = Account(
        id=11,
        school_id=1,
        email="old@school.kr",
        status=AccountStatus.pending,
        contract_term="CY25-H2",
    )
    job = SyncQueue(
        id=2,
        account_id=11,
        op=SyncOp.update,
        state=SyncState.processing,
        payload={"new_email": "new@school.kr"},
    )

    session = AsyncMock()
    session.get = AsyncMock(return_value=account)
    run_change = AsyncMock()

    with (
        patch("app.services.sync_processor.resolve_product_profile", AsyncMock(return_value="Named-Profile")),
        patch("app.services.sync_processor.run_email_change_on_adobe", run_change),
        patch("app.services.sync_processor.refresh_seats_used", AsyncMock()),
        patch("app.services.sync_processor.finalize_queued_audit", AsyncMock()),
    ):
        await process_sync_job(session, job)

    assert job.state == SyncState.done
    assert account.email == "new@school.kr"
    assert account.status == AccountStatus.active
    run_change.assert_awaited_once_with(
        "old@school.kr",
        "new@school.kr",
        "Named-Profile",
        contract_term="CY25-H2",
    )


@pytest.mark.asyncio
async def test_process_sync_job_create_success():
    school_id = 1
    account = Account(id=10, school_id=school_id, email="u@test.kr", status=AccountStatus.pending)
    job = SyncQueue(id=1, account_id=10, op=SyncOp.create, state=SyncState.processing, payload=None)
    job.account = account

    session = AsyncMock()
    session.get = AsyncMock(return_value=account)

    profile_result = AsyncMock()
    profile_result.scalar_one_or_none = lambda: "Named-Profile"
    session.execute = AsyncMock(return_value=profile_result)

    with (
        patch("app.services.sync_processor.resolve_product_profile", AsyncMock(return_value="Named-Profile")),
        patch("app.services.sync_processor.run_user_actions", AsyncMock()),
        patch("app.services.sync_processor.refresh_seats_used", AsyncMock()),
    ):
        await process_sync_job(session, job)

    assert job.state == SyncState.done
    assert account.status == AccountStatus.active
    assert account.adobe_user_id == "u@test.kr"


def test_is_remove_user_absent_error() -> None:
    msg = (
        "[{'errorCode': 'error.user.not_in_org', "
        "'message': 'User not in organization: u@test.kr'}]"
    )
    assert is_remove_user_absent_error(msg)


@pytest.mark.asyncio
async def test_process_sync_job_remove_not_in_org_treated_as_success() -> None:
    account = Account(
        id=12,
        school_id=1,
        email="ghost@school.kr",
        status=AccountStatus.pending,
        contract_term="CY26-H1",
        adobe_user_id="ghost@school.kr",
    )
    job = SyncQueue(id=3, account_id=12, op=SyncOp.remove, state=SyncState.processing)

    session = AsyncMock()
    session.get = AsyncMock(return_value=account)

    with (
        patch("app.services.sync_processor.resolve_product_profile", AsyncMock(return_value="Profile")),
        patch(
            "app.services.sync_processor.run_user_actions",
            AsyncMock(side_effect=AdobeUmapiError("error.user.not_in_org")),
        ),
        patch("app.services.sync_processor.refresh_seats_used", AsyncMock()),
        patch("app.services.sync_processor.finalize_queued_audit", AsyncMock()),
    ):
        await process_sync_job(session, job)

    assert job.state == SyncState.done
    assert account.status == AccountStatus.removed
    assert account.adobe_user_id is None
